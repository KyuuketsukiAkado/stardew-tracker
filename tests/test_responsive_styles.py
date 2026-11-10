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

    def test_tablet_navigation_and_columns(self):
        tablet = self.media(900)
        self.assertIn("display: none", css_block(tablet, ".nav"))
        mobile_nav = css_block(tablet, ".mobile-nav")
        self.assertIn("display: block", mobile_nav)
        self.assertIn("min-height: 40px", mobile_nav)
        self.assertIn("position: sticky", css_block(tablet, ".sidebar"))
        self.assertIn("margin-left: 0", css_block(tablet, ".main"))
        self.assertIn("position: static", css_block(tablet, "header"))
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
        self.assertIn(
            "grid-template-columns: repeat(2, minmax(0, 1fr))",
            css_block(mobile, ".stats"),
        )
        narrow = self.media(360)
        self.assertIn("grid-template-columns: 1fr", css_block(narrow, ".stats"))

    def test_item_and_row_icons_are_centered_and_readable(self):
        small_icon = css_block(self.css, ".item-icon.small")
        self.assertIn("width: 28px", small_icon)
        self.assertIn("height: 28px", small_icon)
        compact_portrait = css_block(self.css, ".portrait.compact")
        self.assertIn("width: 32px", compact_portrait)
        self.assertIn("justify-self: center", css_block(self.css, ".row > .item-icon,"))
        html = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("scale = small ? 1.75 : 2", html)
        self.assertIn("portrait(person.p_idx, true)", html)
        self.assertIn('<span class="en"> · ${esc(a)}</span>', html)
        self.assertIn('<span class="en"> · ${esc(b)}</span>', html)

    def test_people_hearts_have_separate_space_and_larger_icons(self):
        self.assertIn("display: grid", css_block(self.css, ".person"))
        self.assertIn("grid-column: 1 / -1", css_block(self.css, ".person-hearts"))
        self.assertIn("width: 20px", css_block(self.css, ".heart-icon"))
        html = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn('class="person-hearts"', html)

    def test_localized_brand_logo_is_inline_vector(self):
        html = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn('class="brand-mark"', html)
        self.assertIn('id="brandTitle">Stardew Трекер</span>', html)
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
        self.assertIn('class="nav-group-title"', html)
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
            'class="grid two overview-panels"',
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
        self.assertIn("gap: 18px", css_block(self.css, ".overview-panels"))
        self.assertIn('class="overview-items"', html)
        self.assertIn("gap: 8px", css_block(self.css, ".overview-items"))
        self.assertIn("scroll-margin-top: 90px", css_block(self.css, ".bundle-room"))
        self.assertIn(".bundle-tip-link:hover", self.css)

    def test_bundle_item_tiles_have_uniform_adaptive_layout(self):
        items = css_block(self.css, ".bundle-room .bundle-items {")
        tile = css_block(self.css, ".bundle-room .bundle-item {")
        self.assertIn("display: grid", items)
        self.assertIn("grid-template-columns: repeat(auto-fit, minmax(120px, 1fr))", items)
        self.assertIn("align-items: stretch", items)
        self.assertIn("grid-template-rows: minmax(30px, auto) 26px", tile)
        self.assertIn("min-height: 72px", tile)
        self.assertIn(".bundle-room .bundle-item > .annotation-actions", self.css)

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
        self.assertIn('${t("greeting")}, ${esc(farmer)}!', html)
        self.assertIn('meta.farmer || ""', html)
        self.assertIn('farmerFallback: "фермер"', html)
        self.assertIn('farmerFallback: "farmer"', html)
        self.assertIn('id="welcomeTitle"', html)
        self.assertIn("overflow-wrap: anywhere", css_block(self.css, ".welcome-row h1"))
        self.assertIn("min-width: 0", css_block(self.css, ".welcome-row > div:first-child"))

    def test_today_cards_and_status_rows_fit_narrow_screens(self):
        html = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn('class="today-layout"', html)
        self.assertIn('class="grid two today-pair"', html)
        self.assertIn('class="today-list"', html)
        self.assertIn('class="card today-card"', html)
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
        frost = css_block(self.css, ':root[data-theme="frost"] {')
        for token in ("--bg:", "--surface:", "--text:", "--state-lock:", "--danger:"):
            self.assertIn(token, light)
            self.assertIn(token, dark)
            self.assertIn(token, frost)
        # Вне блоков объявления тем hex-цветов быть не должно.
        components = self.css.replace(light, "").replace(dark, "").replace(frost, "")
        import re

        self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}\b", components), [])
        for token in ("function applyTheme()", 'id="themeToggle"', "prefers-color-scheme: dark", 'LS.set("theme"'):
            self.assertIn(token, html)

    def test_frost_deco_theme_is_default_and_in_the_switcher(self):
        """B2 · Frost Deco: тема по умолчанию, участвует в цикле переключения, RU/EN-подписи."""

        html = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn('LS.get("theme", "frost")', html)
        self.assertIn('["frost", "light", "dark", "auto"]', html)
        self.assertIn('frost: "light"', html)
        self.assertIn('auto: "frost"', html)
        self.assertIn('themeFrost: "Иней"', html)
        self.assertIn('themeFrost: "Frost theme"', html)
        self.assertIn("color-scheme: light", css_block(self.css, ':root[data-theme="frost"] {'))
        # Декор Frost Deco: срезанная рамка и тёмная «hero»-плитка без хардкода цветов.
        frame = css_block(self.css, ':root[data-theme="frost"] .stat::before,')
        self.assertIn("clip-path: polygon(", frame)
        self.assertIn("var(--frost-frame)", frame)
        self.assertIn("linear-gradient(160deg, var(--frost-ink), var(--frost-ink-2))", self.css)

    def test_overview_grids_have_no_orphan_rows(self):
        """Плитки метрик (6) и карточки разделов (4) делят ряды поровну на любой ширине."""

        stats_wide = css_block(self.css, "@media (min-width: 1440px)")
        self.assertIn("repeat(6, minmax(0, 1fr))", stats_wide)
        stats_mid = css_block(self.css, "@media (min-width: 760px) and (max-width: 1439px)")
        self.assertIn("repeat(3, minmax(0, 1fr))", stats_mid)
        features_wide = css_block(self.css, "@media (min-width: 1360px)")
        self.assertIn("repeat(4, minmax(0, 1fr))", features_wide)
        features_mid = css_block(self.css, "@media (min-width: 560px) and (max-width: 1359px)")
        self.assertIn("repeat(2, minmax(0, 1fr))", features_mid)
        self.assertIn("max-width: 1840px", css_block(self.css, ".content {"))

    def test_stat_icons_sit_in_a_fixed_box(self):
        """Высокие спрайты (крафт) не сдвигают заголовки соседних плиток."""

        html = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn('<span class="stat-icon">${itemIcon(iconSp, true)}</span>', html)
        icon_box = css_block(self.css, ".stat-icon {")
        self.assertIn("width: 28px", icon_box)
        self.assertIn("height: 28px", icon_box)
        self.assertIn("display: flex", css_block(self.css, ".stat-label {"))

    def test_requirements_filters_and_danger_zone(self):
        html = TEMPLATE.read_text(encoding="utf-8")
        for token in (
            "function reqChip(r)",
            "function reqTip(r)",
            "function unlocksPanel()",
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
