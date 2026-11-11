"""The release is English-first and tells people where to send feedback."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from stardew_tracker.version import __version__

ROOT = Path(__file__).resolve().parent.parent
EMAIL = "repro4chful@gmail.com"
CYRILLIC = re.compile(r"[А-Яа-яЁё]")


def read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


class TestReleaseNotes(unittest.TestCase):
    def setUp(self):
        self.notes = read(".github", "release-notes", f"v{__version__}.md")

    def test_notes_exist_for_the_current_version_and_start_in_english(self):
        # The release workflow takes the notes from .github/release-notes/<tag>.md.
        first_paragraph = self.notes.split("\n\n", 1)[0]
        self.assertFalse(CYRILLIC.search(first_paragraph), first_paragraph)
        self.assertIn("feedback", first_paragraph.lower())
        self.assertIn(EMAIL, first_paragraph)

    def test_download_table_uses_the_release_tag(self):
        for system in ("windows", "macos", "linux"):
            self.assertIn(f"StardewTracker-{system}-v{__version__}.zip", self.notes)

    def test_notes_mention_the_unsigned_apps_and_the_beta_limits(self):
        for token in ("not code-signed", "SmartScreen", "Known limitations", "SHA256SUMS.txt"):
            self.assertIn(token, self.notes)

    def test_russian_summary_follows_the_english_text(self):
        english, _, russian = self.notes.partition("## По-русски")
        self.assertTrue(russian.strip(), "the Russian section is missing")
        self.assertFalse(CYRILLIC.search(english), "Russian text leaked into the English part")
        self.assertIn(EMAIL, russian)


class TestRepositoryDocs(unittest.TestCase):
    def test_readme_is_english_and_links_the_russian_one(self):
        readme = read("README.md")
        self.assertTrue(readme.startswith("# Stardew Valley Progress Tracker"))
        self.assertFalse(CYRILLIC.search(readme.replace("README.ru.md", "").replace("Русская версия", "")))
        self.assertIn("(README.ru.md)", readme)
        self.assertIn(EMAIL, readme)
        self.assertIn("docs/screenshots/overview-light.png", readme)
        for name in ("overview-light.png", "overview-dark.png"):
            self.assertTrue((ROOT / "docs" / "screenshots" / name).is_file(), name)

    def test_russian_readme_points_back_and_has_the_same_contact(self):
        readme = read("README.ru.md")
        self.assertIn("(README.md)", readme)
        self.assertIn(EMAIL, readme)
        self.assertNotIn("догадаться самой", readme)

    def test_changelog_is_english_and_current(self):
        changelog = read("CHANGELOG.md")
        first_section = re.search(r"^## (v[^\n ]+)", changelog, re.M)  # "## Unreleased" may come first
        self.assertIsNotNone(first_section)
        self.assertEqual(first_section.group(1), f"v{__version__}")
        self.assertTrue(CYRILLIC.search(read("CHANGELOG.ru.md")))
        self.assertIn(f"## v{__version__}", read("CHANGELOG.ru.md"))
        self.assertLess(
            changelog.index("## Unreleased") if "## Unreleased" in changelog else 0,
            changelog.index(f"## v{__version__}"),
        )

    def test_issue_templates_exist_and_are_english(self):
        for name in ("bug_report.yml", "feedback.yml"):
            text = read(".github", "ISSUE_TEMPLATE", name)
            self.assertIn(EMAIL, text)
            self.assertFalse(CYRILLIC.search(text), name)

    def test_batch_files_print_english_first(self):
        for name in ("run.bat", "report.bat"):
            text = read(name)
            self.assertLess(text.index("was not found"), text.index("Не найден") if "Не найден" in text else 10**9)
            self.assertIn("Python 3.9+ was not found", text)


if __name__ == "__main__":
    unittest.main()
