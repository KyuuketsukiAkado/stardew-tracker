import unittest
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[1] / "assets" / "dashboard.html"


def css_block(source, selector):
    """Return a CSS block body, handling nested media-query braces."""
    start = source.index(selector)
    opening = source.index("{", start)
    depth = 1
    for position in range(opening + 1, len(source)):
        if source[position] == "{":
            depth += 1
        elif source[position] == "}":
            depth -= 1
            if depth == 0:
                return source[opening + 1 : position]
    raise AssertionError(f"Unclosed CSS block: {selector}")


class TestResponsiveStyles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        html = TEMPLATE.read_text(encoding="utf-8")
        cls.css = html.split("<style>", 1)[1].split("</style>", 1)[0]

    def media(self, width):
        return css_block(self.css, f"@media (max-width: {width}px)")

    def test_collection_touch_targets_stay_grouped(self):
        controls = css_block(self.css, ".collection-controls {")
        self.assertIn("display: inline-flex", controls)
        self.assertIn("white-space: nowrap", controls)
        targets = css_block(self.css, ".collection-controls .annotation-actions button,")
        self.assertIn(".unlock-item .acq-tip > summary", self.css)
        for dimension in ("width", "min-width", "height", "min-height"):
            self.assertIn(f"{dimension}: 40px", targets)
        self.assertIn("top: 40px", css_block(self.css, ".collection-controls .tip-pop,"))
        self.assertIn("width: 26px", css_block(self.css, ".acq-tip summary {"))
        self.assertIn("minmax(min(100%, 144px), 1fr)", css_block(self.css, ".icon-grid {"))
        phone = self.media(450)
        self.assertIn("grid-column: 1 / -1", css_block(phone, ".collection-row > .right,"))
        self.assertIn("flex: 1 1 0", css_block(phone, ".collection-row > .right > .status-badge {"))
        self.assertIn("minmax(min(100%, 144px), 1fr)", css_block(phone, ".icon-grid {"))
        html = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn(
            '<div class="collection-controls">${annotationTools(key, false)}${acquisitionDetails(r, type)}', html
        )
        self.assertIn(
            '<div class="collection-controls">${annotationTools(e.key, false)}${acquisitionDetails(e.row, e.type)}',
            html,
        )
        self.assertIn("${annotationPreview(key)}", html)
        self.assertIn("aria-pressed=", html)

    def test_tablet_navigation_and_columns(self):
        tablet = self.media(900)
        # Пилюли групп и подразделов прячутся, остаётся доступный селектор разделов.
        self.assertIn("display: none", css_block(tablet, ".groups,"))
        mobile_nav = css_block(tablet, ".mobile-nav")
        self.assertIn("display: block", mobile_nav)
        self.assertIn("min-height: 40px", mobile_nav)
        self.assertIn("position: sticky", css_block(self.css, ".topbar {"))
        self.assertIn(
            "grid-template-columns: repeat(2, minmax(0, 1fr))",
            css_block(tablet, ".two,"),
        )

    def test_phone_stacks_panels_and_forms(self):
        phone = self.media(600)
        self.assertIn("grid-template-columns: 1fr", css_block(phone, ".two,"))
        self.assertIn("flex: 1 1 100%", css_block(phone, '.actions input[type="search"]'))
        self.assertIn("flex: 1 1 100%", css_block(phone, '.form input[type="text"],'))

    def test_small_touch_and_narrow_screen_layout(self):
        mobile = self.media(450)
        self.assertIn("min-height: 40px", css_block(mobile, "button"))
        # На узких экранах плитки bento по умолчанию идут в одну колонку.
        self.assertIn("grid-column: span 12", css_block(self.css, ".tile {"))

    def test_item_and_row_icons_are_centered_and_readable(self):
        self.assertIn("--cell: 28px", css_block(self.css, ".item-icon.small"))
        compact_portrait = css_block(self.css, ".portrait.compact")
        self.assertIn("width: 32px", compact_portrait)
        self.assertIn("justify-self: center", css_block(self.css, ".row > .item-icon,"))
        html = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("--ix:${idx % cols};--iy:${Math.floor(idx / cols)}", html)
        self.assertIn("portrait(person.p_idx, true)", html)
        self.assertIn('<span class="en"> · ${esc(a)}</span>', html)
        self.assertIn('<span class="en"> · ${esc(b)}</span>', html)

    def test_item_sprite_offset_follows_icon_size(self):
        """On phones icons shrank to 28 px while offsets stayed 32 px: neighbours' sprites showed."""

        html = TEMPLATE.read_text(encoding="utf-8")
        icon_fn = html[html.index("function itemIcon(") :]
        icon_fn = icon_fn[: icon_fn.index("\n      }\n")]
        item_style = icon_fn[icon_fn.index("let style = ") :]
        self.assertNotIn("background-position", item_style)
        base = css_block(self.css, "\n      .item-icon {")
        self.assertIn("--cell: 32px", base)
        for rule in (
            "width: var(--cell)",
            "background-size: calc(var(--cell) * 24) calc(var(--cell) * 39)",
            "calc(var(--ix, 0) * var(--cell) * -1)",
        ):
            self.assertIn(rule, base)
        self.assertIn("calc(var(--cell) * 8) calc(var(--cell) * 20)", css_block(self.css, ".item-icon.sheet1 {"))
        tall = css_block(self.css, ".item-icon.sheet2 {")
        self.assertIn("calc(var(--cell) * 8) calc(var(--cell) * 92)", tall)
        self.assertIn("calc(var(--iy, 0) * var(--cell) * -2)", tall)
        # Narrow screens only change the cell size; no pixel sheet sizes that can drift.
        phone_icon = css_block(self.media(450), ".item-icon {")
        self.assertEqual(phone_icon.strip(), "--cell: 28px;")
        self.assertNotIn("background-size: 672px", self.css)

    def test_people_hearts_have_separate_space_and_larger_icons(self):
        self.assertIn("display: grid", css_block(self.css, ".person"))
        self.assertIn("grid-column: 1 / -1", css_block(self.css, ".person-hearts"))
        self.assertIn("width: 20px", css_block(self.css, ".heart-icon"))
        html = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn('class="person-hearts"', html)

    def test_localized_brand_logo_is_inline_vector(self):
        html = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn('class="brand-mark"', html)
        # English first: the static markup is English, the script switches it to Russian on demand.
        self.assertIn('id="brandTitle">Stardew Tracker</span>', html)
        self.assertIn('brand: "Stardew Трекер"', html)
        self.assertIn('brand: "Stardew Tracker"', html)
        self.assertIn('appTitle: "Stardew Трекер — прогресс фермы"', html)
        self.assertIn('appTitle: "Stardew Tracker — Farm Progress"', html)
        self.assertIn('document.title = t("appTitle")', html)
        self.assertIn('viewBox="0 0 40 40"', html)
        self.assertIn("width: 36px", css_block(self.css, ".brand-mark"))

    def test_player_friendly_navigation_and_home_feature_cards(self):
        html = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn('id="mobileNav"', html)
        self.assertIn('class="mobile-nav"', html)
        self.assertIn('id="nav" class="groups"', html)
        self.assertIn('id="subnav" class="subnav-links"', html)
        self.assertIn('<optgroup label="${group.label}">', html)
        self.assertIn('t("sections")', html)
        self.assertIn('class="feature-nav"', html)
        self.assertIn('class="feature-card"', html)
        self.assertIn("${featureNavigation()}", html)
        self.assertIn('id="icon-house"', html)
        self.assertIn('<use href="#icon-${icons[key]}">', html)
        self.assertIn('<use href="#icon-${group.icon}">', html)
        license_file = TEMPLATE.parents[1] / "assets" / "icons" / "LICENSE"
        self.assertIn("ISC License", license_file.read_text(encoding="utf-8"))
        self.assertIn("grid-template-columns: repeat(auto-fit, minmax(235px, 1fr))", self.css)

    def test_home_bundle_cards_deep_link_and_have_individual_tips(self):
        html = TEMPLATE.read_text(encoding="utf-8")
        for token in (
            'class="bento"',
            "function bundleRoomAnchor(room)",
            "function bundleAnchor(bundle)",
            "function bundleRoomTooltip(room)",
            "function bundleTooltip(bundle)",
            'href="#bundles/${bundleRoomAnchor(room)}"',
            'href="#bundles/${bundleAnchor(bundle)}"',
            'id="${bundleRoomAnchor(room)}"',
            'id="${bundleAnchor(bundle)}"',
            'class="acq-tip bundle-tooltip"',
            "function focusBundleTarget()",
            'target.scrollIntoView?.({ behavior: "smooth", block: "start" })',
        ):
            self.assertIn(token, html)
        self.assertIn("gap: var(--gap)", css_block(self.css, ".bento {"))
        self.assertIn('class="overview-items"', html)
        self.assertIn("gap: 8px", css_block(self.css, ".overview-items"))
        self.assertIn("scroll-margin-top: 90px", css_block(self.css, ".bundle-room"))
        self.assertIn(".bundle-tip-link:hover", self.css)

    def test_bundle_item_tiles_have_uniform_adaptive_layout(self):
        items = css_block(self.css, ".bundle-room .bundle-items {")
        tile = css_block(self.css, ".bundle-room .bundle-item {")
        targets = css_block(self.css, ".bundle-room .bundle-item-actions .annotation-actions button,")
        self.assertIn("display: grid", items)
        self.assertIn("min-width: 0", css_block(self.css, ".bundle {"))
        self.assertIn("grid-template-columns: minmax(0, 1fr)", css_block(self.media(450), ".bundles {"))
        self.assertIn("grid-template-columns: repeat(auto-fit, minmax(min(100%, 142px), 1fr))", items)
        self.assertIn("align-items: stretch", items)
        self.assertIn("display: flex", tile)
        self.assertIn("min-height: 60px", tile)
        self.assertIn("min-height: 44px", css_block(self.css, ".bundle-item-trigger {"))
        self.assertIn("flex: 1", css_block(self.css, ".bundle-room .bundle-item:not(.expanded) .bundle-item-trigger {"))
        self.assertIn("display: none", css_block(self.css, ".bundle-item-actions[hidden] {"))
        for dimension in ("width", "min-width", "height", "min-height"):
            self.assertIn(f"{dimension}: 40px", targets)
        tooltip = css_block(self.css, ".acq-tip.bundle-tooltip > summary {")
        self.assertIn("width: 40px", tooltip)
        self.assertIn("height: 40px", tooltip)
        html = TEMPLATE.read_text(encoding="utf-8")
        for marker in (
            "function bundleItemCard(bundle, item, index)",
            "opened = expandedBundleItem === actionId",
            'data-bundle-item="${actionId}"',
            "popup.style.translate = `${moveRight - moveLeft}px 0`",
            'class="bundle-item-trigger" data-bundle-item=',
            'aria-expanded="${opened}" aria-controls="${actionId}"',
            '${annotationTools(key, false)}${acquisitionDetails(item, "shipped")}',
            'if (e.key === "Escape" && expanded)',
            'focusDataControl("data-bundle-item", key)',
        ):
            self.assertIn(marker, html)

    def test_bundle_rewards_are_visually_highlighted(self):
        html = TEMPLATE.read_text(encoding="utf-8")
        reward = css_block(self.css, ".reward-card {")
        label = css_block(self.css, ".reward-card-label {")
        icon = css_block(self.css, ".reward-card-icon {")
        self.assertIn('class="reward-card"', html)
        self.assertIn('class="reward-card-icon"', html)
        self.assertIn("function rewardCard(reward)", html)
        self.assertIn('${m.reward ? rewardCard(m.reward) : ""}', html)
        self.assertIn("border-left: 4px solid var(--gold)", reward)
        self.assertIn("background: linear-gradient", reward)
        self.assertIn("background: var(--gold)", label)
        self.assertIn("font-weight: 800", label)
        self.assertIn("width: 32px", icon)
        self.assertIn("height: 32px", icon)
        reward_icon = css_block(self.css, ".reward-card-icon .item-icon.sheet2 {")
        self.assertIn("top: -5px", reward_icon)
        self.assertIn("transform: scale(0.56)", reward_icon)
        self.assertIn("font-weight: 700", css_block(self.css, ".reward-card-name {"))

    def test_museum_artifact_locations_are_localized_and_visible(self):
        html = TEMPLATE.read_text(encoding="utf-8")
        for token in (
            'artifactSources: "Где найти"',
            'artifactSources: "Where to find"',
            'r.locations?.[EN ? "en" : "ru"] || []',
            "function museumSourcePreview(item)",
            "${museumSourcePreview(r)}",
            'class="museum-source-preview"',
            'class="acq-tip museum-source-tip${req ? " req-tip" : ""}"',
            'class="museum-source-toggle"',
            'sources.map((source) => `<div class="tip-line">${esc(source)}</div>`)',
        ):
            self.assertIn(token, html)
        tooltip = css_block(self.css, ".museum-source-tip .tip-pop {")
        self.assertIn("max-height: min(360px, 70vh)", tooltip)
        self.assertIn("overflow-y: auto", tooltip)
        self.assertIn("background: var(--info-soft)", css_block(self.css, ".acq-tip summary {"))
        self.assertIn("background: var(--blue)", css_block(self.css, ".acq-tip summary:hover {"))
        self.assertIn("width: auto", css_block(self.css, ".museum-source-tip summary {"))
        self.assertIn("align-items: center", css_block(self.css, ".tabs {"))

    def test_acquisition_tooltips_close_on_pointer_and_focus_exit(self):
        html = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn('tip.addEventListener("pointerleave"', html)
        self.assertIn('tip.addEventListener("focusout"', html)
        self.assertIn("if (!tip.contains(event.relatedTarget)) tip.open = false", html)

    def test_farmer_greeting_is_localized_and_escaped(self):
        html = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("function greetingTitle(meta)", html)
        self.assertIn('${t("greeting")}, <em>${esc(farmer)}</em>!', html)
        self.assertIn('meta.farmer || ""', html)
        # No gendered noun as a fallback: without a farmer name the greeting has no name at all.
        self.assertNotIn("farmerFallback", html)
        self.assertIn('`${t("greeting")}!`', html)
        self.assertIn('id="welcomeTitle"', html)
        self.assertIn("overflow-wrap: anywhere", css_block(self.css, ".welcome-row h1"))
        self.assertIn("min-width: 0", css_block(self.css, ".welcome-row > div:first-child"))

    def test_today_cards_and_status_rows_fit_narrow_screens(self):
        html = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn('class="today-layout"', html)
        self.assertIn('class="bento"', html)
        self.assertIn('class="today-list"', html)
        self.assertIn('class="tile today-card ${span}"', html)
        self.assertIn(".today-list .row", self.css)
        self.assertIn(".today-list .row > .right", self.css)
        self.assertIn("max-width: 190px", self.css)
        self.assertIn("max-width: 100%", css_block(self.css, ".today-list .status-badge"))

    def test_semantic_color_coding_is_consistent_and_explained(self):
        html = TEMPLATE.read_text(encoding="utf-8")
        for token in (
            "--state-done:",
            "--state-progress:",
            "--state-action:",
            "--state-idle:",
            "--state-info:",
            "function colorLegend()",
            'role="note" aria-label="${t("colorCode")}"',
            "function rowStatus(row, type)",
            'class="badge ${status.className}"',
            'label: t("knownNotDone")',
            "aria-valuenow=",
        ):
            self.assertIn(token, html)
        self.assertIn(".badge.ok", self.css)
        self.assertIn(".badge.warn", self.css)
        self.assertIn(".badge.alert", self.css)
        self.assertIn(".badge.no", self.css)
        self.assertIn(".bar.done i", self.css)
        self.assertIn(".bar.progress i", self.css)
        self.assertIn("${colorLegend()}", html)
        self.assertIn('colorCode: "Цветовые статусы"', html)
        self.assertIn('colorCode: "Color guide"', html)

    def test_keyboard_and_screen_reader_affordances(self):
        html = TEMPLATE.read_text(encoding="utf-8")
        for token in (
            'aria-live="polite"',
            'aria-modal="true"',
            'aria-current="page"',
            'aria-pressed="${stateFilter === "missing"}"',
            'role="progressbar"',
            'document.documentElement.lang = EN ? "en" : "ru"',
            'document.body.classList.add("modal-open")',
            "target.focus();",
        ):
            self.assertIn(token, html)
        self.assertIn('if (event.key === "Enter" || event.key === " ")', html)
        self.assertIn("const focusable = modal.querySelectorAll(", html)

    def test_locale_toggle_and_goal_metrics_stay_consistent(self):
        html = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn('let EN = prefs.lang === "en"', html)
        self.assertIn('EN = prefs.lang === "en"', html)
        self.assertIn("metricLabel(k)", html)
        self.assertIn("${metricLabel(g.metric)}", html)
        self.assertIn('t(live ? "goalHint" : "offlineGoalsHint")', html)
        self.assertIn('document.documentElement.lang = EN ? "en" : "ru"', html)

    def test_light_and_dark_themes_use_tokens(self):
        """Цвета компонентов берутся из переменных темы, а не захардкожены."""

        html = TEMPLATE.read_text(encoding="utf-8")
        light = css_block(self.css, ":root {")
        dark = css_block(self.css, ':root[data-theme="dark"] {')
        for token in ("--bg:", "--surface:", "--text:", "--state-lock:", "--danger:", "--tile-bg:", "--seg-on-bg:"):
            self.assertIn(token, light)
            self.assertIn(token, dark)
        # Вне блоков объявления тем hex-цветов быть не должно.
        components = self.css.replace(light, "").replace(dark, "")
        import re

        self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}\b", components), [])
        for token in ("function applyTheme()", 'id="themeToggle"', "prefers-color-scheme: dark", 'LS.set("theme"'):
            self.assertIn(token, html)

    def test_cold_bento_design_system_two_palettes(self):
        """Светлая B2 «Иней» (по умолчанию) и тёмная B1 «Ночь»; старое имя темы мигрирует."""

        html = TEMPLATE.read_text(encoding="utf-8")
        self.assertNotIn('data-theme="frost"', self.css)
        self.assertIn('theme: normalizeTheme(LS.get("theme", "light"))', html)
        self.assertIn('if (value === "frost") return "light"', html)
        self.assertIn('themeNext = { light: "dark", dark: "auto", auto: "light" }', html)
        self.assertIn('themeLight: "Иней · светлая"', html)
        self.assertIn('themeDark: "Ночь · тёмная"', html)
        self.assertIn('themeLight: "Frost · light"', html)
        self.assertIn('themeDark: "Night · dark"', html)
        self.assertIn("color-scheme: light", css_block(self.css, ":root {"))
        self.assertIn("color-scheme: dark", css_block(self.css, ':root[data-theme="dark"] {'))
        light = css_block(self.css, ":root {")
        for token in ("--font-display:", "Bahnschrift", "--t9:", "--tile-radius:", "--tile-hero-bg:", "--seg-on-bg:"):
            self.assertIn(token, light)
        # Ар-деко: срезанная рамка плитки; в тёмной теме прозрачна токеном --frame.
        self.assertIn("clip-path: polygon(", css_block(self.css, ".tile::before {"))
        self.assertIn("--frame: transparent", css_block(self.css, ':root[data-theme="dark"] {'))

    def test_bento_grid_has_no_orphan_rows(self):
        """12 колонок на десктопе; метрики идут по 3 в ряд на средних ширинах, карточки разделов — 4/2."""

        self.assertIn("repeat(12, minmax(0, 1fr))", css_block(self.css, ".bento {"))
        wide = css_block(self.css, "@media (min-width: 1100px)")
        for span in (3, 4, 5, 6, 7, 8):
            self.assertIn(f"grid-column: span {span}", wide)
        mid = css_block(self.css, "@media (min-width: 600px) and (max-width: 1099px)")
        self.assertIn("grid-column: span 4", css_block(mid, ".tile.m"))
        features_wide = css_block(self.css, "@media (min-width: 1360px)")
        self.assertIn("repeat(4, minmax(0, 1fr))", features_wide)
        features_mid = css_block(self.css, "@media (min-width: 560px) and (max-width: 1359px)")
        self.assertIn("repeat(2, minmax(0, 1fr))", features_mid)
        self.assertIn("max-width: 1840px", css_block(self.css, ".content {"))

    def test_overview_is_a_bento_of_tiles(self):
        html = TEMPLATE.read_text(encoding="utf-8")
        for token in (
            "function statTile(key, label, iconSp, go, tone, span)",
            "function perfectionTile(span)",
            'class="tile metric m ${span} ${state}"',
            '<span class="stat-icon">${itemIcon(iconSp, true)}</span>',
            'perfectionTile("s4")',
            'statTile("museum", t("museum"), [0, 72], "museum", "", "s4")',
        ):
            self.assertIn(token, html)
        # Метрики спокойные: без яркой hero-заливки и «своего цвета» у каждой плитки.
        self.assertNotIn('class="tile hero m ${span}"', html)
        self.assertNotIn('"museum", "ice"', html)
        for state, token in (("progressing", "--state-progress"), ("complete", "--state-done")):
            self.assertIn(token, css_block(self.css, f".tile.metric.{state} .bar i {{"))

    def test_overview_leads_with_one_available_action(self):
        """UX-аудит P1: первое действие раньше цифр; пустое состояние честное."""

        html = TEMPLATE.read_text(encoding="utf-8")
        overview = html[html.index("function overview()") :]
        overview = overview[: overview.index("function todayHighlights()")]
        self.assertLess(overview.index("nextAction()"), overview.index("perfectionTile("))
        self.assertIn("S.today && S.today.next_action", html)
        self.assertIn('class="next-action is-empty"', html)
        self.assertIn('class="next-action-cta"', html)
        for key in ("nextKicker", "nextNoneTitle", "nextNoneText", "nextMore"):
            self.assertEqual(html.count(f"{key}:"), 2, key)  # RU и EN
        # Предложение, а не тревога: синий статус «подсказка», не красный.
        block = css_block(self.css, ".next-action {")
        self.assertIn("var(--state-info)", block)
        self.assertNotIn("--state-action", block)
        self.assertIn("min-height: 44px", css_block(self.css, ".next-action-cta,"))

    def test_phone_beta_banner_is_compact_but_complete(self):
        """На телефоне плашка короче, но текст, контакты и кнопка закрытия на месте."""

        html = TEMPLATE.read_text(encoding="utf-8")
        phone = css_block(self.css, "@media (max-width: 600px)")
        banner = css_block(phone, ".beta-banner {")
        self.assertIn("display: block", banner)
        self.assertIn("font-size: 13px", banner)
        self.assertIn("position: absolute", css_block(phone, ".beta-banner button {"))
        self.assertNotIn("display: none", banner)
        self.assertIn("mailto:${FEEDBACK_EMAIL}", html)
        self.assertIn("${ISSUES_URL}", html)
        self.assertIn("grid-column: span 4", css_block(phone, ".bento.metrics .tile {"))
        # Иконка лежит в рамке фиксированного размера, высокие спрайты не сдвигают заголовки.
        icon_box = css_block(self.css, ".stat-icon {")
        self.assertIn("width: 28px", icon_box)
        self.assertIn("height: 28px", icon_box)
        self.assertIn("display: inline-flex", css_block(self.css, ".t-name {"))

    def test_large_metrics_keep_numbers_and_units_separate(self):
        """Italic digits used to paint over the inline /total and % at large sizes."""

        html = TEMPLATE.read_text(encoding="utf-8")
        metric = css_block(self.css, ".big {")
        for rule in (
            "display: flex",
            "align-items: baseline",
            "column-gap: 14px",
            "font-style: normal",
            "line-height: 1.05",
        ):
            self.assertIn(rule, metric)
        self.assertIn('class="big-value">${p.pct}</span><span class="big-unit">%</span>', html)
        self.assertIn('class="big-value">${v[0]}</span><span class="big-unit">/${v[1]}</span>', html)
        self.assertNotIn(':root[data-theme="dark"] .big,', self.css)
        self.assertNotIn(".big sup {", self.css)

    def test_top_navigation_groups_and_subsections(self):
        html = TEMPLATE.read_text(encoding="utf-8")
        for token in (
            "function navGroups()",
            "function groupOf(key)",
            'class="topbar"',
            'class="${selected ? "selected" : ""}${group.danger ? " danger-link" : ""}"',
            'aria-current="page"',
        ):
            self.assertIn(token, html)
        self.assertNotIn('class="sidebar"', html)
        self.assertIn("position: sticky", css_block(self.css, ".topbar {"))
        self.assertIn("border-radius: 999px", css_block(self.css, ".groups {"))

    def test_requirements_filters_and_danger_zone(self):
        html = TEMPLATE.read_text(encoding="utf-8")
        for token in (
            "function reqChip(r)",
            "function reqTip(r)",
            'function unlocksPanel(span = "s12")',
            "function filterBar(type, shown, total)",
            "function applyFilters(rows, type)",
            "function secretsPage()",
            'id="dangerConsent"',
            "dangerConsent = false;",
            'data-reveal-key="${esc(key)}"',
            '.replace(/\\S/g, "•")',
        ):
            self.assertIn(token, html)
        self.assertIn("border-style: dashed", css_block(self.css, ".row.locked,"))
        self.assertIn("filter: blur(6px)", css_block(self.css, ".spoiler-text.blurred > p"))

    def test_spoiler_visuals_schemes_and_wiki_links(self):
        """Визуал к решениям: свои схемы, иконки предметов, внешние ссылки без referrer."""

        import json

        html = TEMPLATE.read_text(encoding="utf-8")
        for token in (
            "const SCHEMES = {",
            "function spoilerExtras(entry)",
            "function wikiLink(url, label)",
            'target="_blank" rel="noopener noreferrer"',
            'if (kind === "solution") el.insertAdjacentHTML("beforeend", spoilerExtras(entry));',
            # Визуал не рендерится, пока решение не раскрыто.
            'extras = open && kind === "solution" ? spoilerExtras(findSecret(id)) : ""',
        ):
            self.assertIn(token, html)
        secrets_path = TEMPLATE.parents[1] / "data" / "secrets.json"
        secrets = json.loads(secrets_path.read_text(encoding="utf-8"))
        used = {e["scheme"] for s in secrets["sections"] for e in s["entries"] if e.get("scheme")}
        self.assertGreaterEqual(len(used), 10)
        for scheme in used:
            self.assertIn(f"  {scheme}: () =>", html, scheme)
        self.assertIn("fill: var(--danger)", css_block(self.css, ".sc-target {"))

    def test_short_viewport_and_toast_are_contained(self):
        html = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("viewport-fit=cover", html)
        self.assertIn("safe-area-inset-bottom", self.css)
        dialog = css_block(self.css, ".note-dialog")
        self.assertIn("max-height: calc(100dvh - 30px)", dialog)
        self.assertIn("overflow-y: auto", dialog)
        toast = css_block(self.css, ".toast")
        self.assertIn("max-width: calc(100vw - 32px)", toast)
        self.assertIn("overflow-wrap: anywhere", toast)


if __name__ == "__main__":
    unittest.main()
