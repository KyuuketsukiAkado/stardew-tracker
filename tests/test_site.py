"""The GitHub Pages landing page: download links, privacy, English first."""

from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import build_site  # noqa: E402

from stardew_tracker.version import __version__  # noqa: E402


class SiteTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="sdv-site-")
        cls.out = os.path.join(cls.tmp, "_site")
        cls.files = build_site.build(cls.out)
        cls.html = Path(cls.out, "index.html").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)


class TestBuild(SiteTestCase):
    def test_all_placeholders_are_filled(self):
        self.assertEqual(re.findall(r"\{\{[A-Z_]+\}\}", self.html), [])

    def test_output_has_page_screenshots_and_nojekyll(self):
        self.assertIn("index.html", self.files)
        self.assertIn(".nojekyll", self.files)
        self.assertIn("404.html", self.files)
        for name in ("overview-light.png", "overview-dark.png", "overview-light-ru.png", "overview-dark-ru.png"):
            self.assertTrue(os.path.isfile(os.path.join(self.out, "screenshots", name)), name)

    def test_every_screenshot_on_the_page_exists_and_has_a_language(self):
        sources = re.findall(r'<img lang="(en|ru)" src="(screenshots/[^"]+)"', self.html)
        self.assertEqual([lang for lang, _src in sources], ["en", "en", "ru", "ru"])
        for _lang, src in sources:
            self.assertTrue(os.path.isfile(os.path.join(self.out, src)), src)

    def test_build_is_deterministic(self):
        other = os.path.join(self.tmp, "second")
        build_site.build(other)
        self.assertEqual(Path(other, "index.html").read_text(encoding="utf-8"), self.html)

    def test_unknown_placeholder_is_an_error(self):
        original = build_site.values
        build_site.values = lambda version=__version__: {"VERSION": version}  # type: ignore[assignment]
        try:
            with self.assertRaises(KeyError):
                build_site.render_page()
        finally:
            build_site.values = original  # type: ignore[assignment]


class TestDownloadLinks(SiteTestCase):
    def test_every_system_links_to_the_asset_of_the_current_version(self):
        tag = f"v{__version__}"
        base = f"https://github.com/{build_site.OWNER}/{build_site.REPO}/releases/download/{tag}"
        for system in ("windows", "macos", "linux"):
            self.assertIn(f'href="{base}/StardewTracker-{system}-{tag}.zip"', self.html, system)

    def test_asset_names_match_what_the_release_workflow_uploads(self):
        workflow = (ROOT / ".github" / "workflows" / "build-app.yml").read_text(encoding="utf-8")
        # the workflow zips "<artifact>-<tag>.zip" for artifacts StardewTracker-windows/-macos/-linux
        self.assertIn("${name}-${GITHUB_REF_NAME}.zip", workflow)
        for system in ("windows", "macos", "linux"):
            self.assertIn(f"artifact: StardewTracker-{system}", workflow)

    def test_prerelease_is_labelled_a_public_beta(self):
        self.assertIn("Public beta", build_site.render_page("0.4.0-beta.2"))
        self.assertIn("Публичная бета", build_site.render_page("0.4.0-beta.2"))
        stable = build_site.render_page("1.0.0")
        self.assertIn(">Release<", stable)
        self.assertNotIn("Public beta", stable)
        self.assertIn("releases/download/v1.0.0/StardewTracker-windows-v1.0.0.zip", stable)

    def test_releases_list_is_linked_for_other_downloads(self):
        self.assertIn(f'https://github.com/{build_site.OWNER}/{build_site.REPO}/releases"', self.html)


class TestPrivacyAndSafety(SiteTestCase):
    def test_page_loads_nothing_from_other_servers(self):
        # Links are fine; resources (scripts, styles, fonts, images, requests) must be local.
        self.assertEqual(re.findall(r"<script[^>]+src=", self.html), [])
        self.assertEqual(re.findall(r"<link[^>]+href=\"https?://", self.html), [])
        self.assertEqual(re.findall(r"<img[^>]+src=\"https?://", self.html), [])
        self.assertNotIn("@import", self.html)
        self.assertNotRegex(self.html, r"url\(\s*['\"]?https?://")
        for call in ("fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket", "navigator.serviceWorker"):
            self.assertNotIn(call, self.html, call)

    def test_new_tab_links_are_safe(self):
        for tag in re.findall(r"<a [^>]*target=\"_blank\"[^>]*>", self.html):
            self.assertIn("noopener", tag, tag)

    def test_no_personal_paths(self):
        for needle in ("AppData", "C:\\Users", "Kyuuketsuki Akado"):
            self.assertNotIn(needle, self.html)


class TestEnglishFirst(SiteTestCase):
    def test_default_language_and_head(self):
        self.assertIn('<html lang="en" data-lang="en">', self.html)
        self.assertRegex(self.html, r"<title>Stardew Tracker — see what's done")
        self.assertIn(
            'property="og:image" content="https://kyuuketsukiakado.github.io/stardew-tracker/screenshots/', self.html
        )

    def test_every_english_block_has_a_russian_twin(self):
        english = len(re.findall(r'<span lang="en">', self.html))
        russian = len(re.findall(r'<span lang="ru">', self.html))
        self.assertGreater(english, 20)
        self.assertEqual(english, russian)

    def test_language_follows_the_browser_and_can_be_switched(self):
        for token in ('indexOf("ru") === 0', 'store.set("lang", lang)', 'id="langToggle"'):
            self.assertIn(token, self.html)

    def test_download_button_adapts_to_the_visitors_system(self):
        for token in ("function detectOS()", '"windows"', '"macos"', '"linux"', "is-mobile"):
            self.assertIn(token, self.html)
        # without JavaScript the page still offers all three downloads
        for system in ("windows", "macos", "linux"):
            self.assertIn(f'data-os="{system}"', self.html)

    def test_page_explains_the_unsigned_app_and_how_to_give_feedback(self):
        for token in ("not code-signed", "SmartScreen", "SHA-256", "repro4chful@gmail.com", "public beta"):
            self.assertIn(token.lower(), self.html.lower())
        self.assertIn("ConcernedApe", self.html)


class TestWhiteDesign(SiteTestCase):
    """The site uses the tracker's light Frost look, whatever the visitor's system theme is."""

    def test_light_only(self):
        self.assertNotIn("prefers-color-scheme: dark", self.html)
        self.assertIn("color-scheme: light;", self.html)
        self.assertIn('name="color-scheme" content="light"', self.html)
        self.assertIn("--bg: #e8eef4;", self.html)


class TestRussianCopy(SiteTestCase):
    """Wording that read badly in review must not come back."""

    def test_old_phrasings_are_gone(self):
        for bad in (
            "Знайте",
            "а ещё то, что",
            "Issue на GitHub",
            "приложение не подписано",
            "Все загрузки",
            "сейв",
            "Берёт файл",
        ):
            self.assertNotIn(bad, self.html, bad)

    def test_russian_page_has_its_own_title_description_and_screenshots(self):
        self.assertIn("что сделано и что осталось в вашем сохранении", self.html)
        self.assertIn("Бесплатный офлайн-трекер прогресса", self.html)
        self.assertIn("overview-light-ru.png", self.html)

    def test_cyrillic_capitals_get_room_for_their_marks(self):
        # Й and Ё carry a mark above the letter; a tight line height made it touch the line above.
        self.assertRegex(self.html, r'\[data-lang="ru"\] h1 \{[^}]*line-height: 1\.1;')


class TestHeroIllustration(SiteTestCase):
    """The scene on the right of the hero is our own vector drawing, decorative and quiet."""

    def setUp(self):
        match = re.search(r'<figure class="hero-art" aria-hidden="true">(.*?)</figure>', self.html, re.S)
        self.assertIsNotNone(match, "hero illustration is missing or not marked decorative")
        self.art = match.group(1)

    def test_scene_is_inline_vector_art_without_game_sprites_or_requests(self):
        self.assertIn("<svg", self.art)
        self.assertNotIn("<image", self.art)
        self.assertNotIn("data:image", self.art)
        self.assertNotIn("http", self.art.replace("http://www.w3.org", ""))
        self.assertNotIn("sprites", self.art)

    def test_scene_has_the_farm_motifs(self):
        # farmhouse roof, crop field, pond with a fish, sun and the perfection star
        for token in ('class="fish"', 'class="rays"', "crop field", "farmhouse", "pond with a jumping fish"):
            self.assertIn(token, self.art, token)
        self.assertIn("★", self.art)

    def test_cards_over_the_scene_carry_no_translatable_words(self):
        # digits and symbols only: the picture must read the same in English and Russian
        cards = re.findall(
            r'<div class="art-card[^"]*">(.*?)</div>\s*(?=<div class="art-card|</figure>)', self.html, re.S
        )
        text = re.sub(r"<[^>]+>", " ", " ".join(cards))
        self.assertFalse(re.search(r"[A-Za-zА-Яа-яЁё]{3,}", text), text)

    def test_motion_is_switched_off_for_people_who_ask(self):
        reduced = self.html.split("@media (prefers-reduced-motion: reduce)", 1)[1]
        for selector in (".hero-art .cloud", ".hero-art .rays", ".hero-art .fish"):
            self.assertIn(selector, reduced, selector)
        self.assertIn("animation: none", reduced)

    def test_hero_stacks_on_narrow_screens(self):
        self.assertRegex(self.html, r"@media \(max-width: 920px\) \{\s*\.hero \{\s*grid-template-columns: 1fr;")


class TestNotFoundPage(SiteTestCase):
    def setUp(self):
        self.page = Path(self.out, "404.html").read_text(encoding="utf-8")

    def test_page_is_complete_bilingual_and_points_home_absolutely(self):
        self.assertEqual(re.findall(r"\{\{[A-Z_]+\}\}", self.page), [])
        self.assertIn('href="https://kyuuketsukiakado.github.io/stardew-tracker/"', self.page)
        self.assertIn("Page not found", self.page)
        self.assertIn("Страница не найдена", self.page)
        self.assertEqual(
            len(re.findall(r'<span lang="en">', self.page)), len(re.findall(r'<span lang="ru">', self.page))
        )

    def test_page_is_light_and_loads_nothing_external(self):
        self.assertIn("color-scheme: light;", self.page)
        self.assertNotIn("prefers-color-scheme", self.page)
        self.assertEqual(re.findall(r"<script[^>]+src=|<link[^>]+href=\"https?://", self.page), [])
        self.assertIn('name="robots" content="noindex"', self.page)


class TestPagesWorkflow(unittest.TestCase):
    text = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")

    def test_deploys_with_the_pages_actions_and_minimal_permissions(self):
        for token in (
            "actions/configure-pages@",
            "actions/upload-pages-artifact@",
            "actions/deploy-pages@",
            "pages: write",
            "id-token: write",
            "python tools/build_site.py --out _site",
        ):
            self.assertIn(token, self.text)
        self.assertIn("contents: read", self.text)

    def test_rebuilds_when_the_version_or_the_site_changes(self):
        for path in ('"site/**"', '"tools/build_site.py"', '"stardew_tracker/version.py"', '"docs/screenshots/**"'):
            self.assertIn(path, self.text)
        self.assertIn("branches: [master]", self.text)


if __name__ == "__main__":
    unittest.main()
