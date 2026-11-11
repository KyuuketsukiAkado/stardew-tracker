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
        for name in ("overview-light.png", "overview-dark.png"):
            self.assertTrue(os.path.isfile(os.path.join(self.out, "screenshots", name)), name)

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
