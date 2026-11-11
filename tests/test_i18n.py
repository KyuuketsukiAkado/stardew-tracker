"""Language selection: console messages, bilingual errors and the English-first page."""

from __future__ import annotations

import contextlib
import copy
import io
import os
import pickle  # nosec B403 - only round-trips a value created by this test
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from make_test_save import write_test_save  # noqa: E402

from stardew_tracker import cli, i18n, server  # noqa: E402
from stardew_tracker.errors import SaveError  # noqa: E402
from stardew_tracker.i18n import L, Text, both, pick  # noqa: E402

TEMPLATE = Path(ROOT) / "assets" / "dashboard.html"


class LanguageCase(unittest.TestCase):
    """Starts every test from a clean language state and restores it afterwards."""

    def setUp(self):
        self.addCleanup(i18n.set_language, None)


class TestNormalize(unittest.TestCase):
    def test_locale_spellings(self):
        for value in ("ru", "RU", "ru_RU.UTF-8", "ru-RU", "Russian_Russia.1251"):
            self.assertEqual(i18n.normalize(value), "ru", value)
        for value in ("en", "en_US.UTF-8", "en-GB", "English_United States"):
            self.assertEqual(i18n.normalize(value), "en", value)

    def test_unknown_or_empty_values(self):
        for value in ("de_DE", "fr", "", "   ", None, 42):
            self.assertIsNone(i18n.normalize(value), value)


class TestDetectLanguage(LanguageCase):
    def _detect(self, env, windows=None):
        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(i18n, "_windows_ui_language", return_value=windows),
        ):
            return i18n.detect_language()

    def test_defaults_to_english(self):
        self.assertEqual(self._detect({}), "en")
        self.assertEqual(self._detect({"LANG": "de_DE.UTF-8"}), "en")

    def test_explicit_variable_wins_over_the_system(self):
        self.assertEqual(self._detect({i18n.ENV_VAR: "ru", "LANG": "en_US.UTF-8"}, windows="en"), "ru")
        self.assertEqual(self._detect({i18n.ENV_VAR: "en", "LANG": "ru_RU.UTF-8"}, windows="ru"), "en")

    def test_invalid_override_is_ignored(self):
        self.assertEqual(self._detect({i18n.ENV_VAR: "klingon", "LANG": "ru_RU.UTF-8"}), "ru")

    def test_windows_display_language(self):
        self.assertEqual(self._detect({}, windows="ru"), "ru")
        self.assertEqual(self._detect({"LANG": "ru_RU.UTF-8"}, windows="en"), "en")

    def test_posix_locale_variables_in_priority_order(self):
        self.assertEqual(self._detect({"LANG": "ru_RU.UTF-8"}), "ru")
        self.assertEqual(self._detect({"LANG": "ru_RU.UTF-8", "LC_ALL": "en_US.UTF-8"}), "en")
        self.assertEqual(self._detect({"LANGUAGE": "ru:en"}), "ru")
        self.assertEqual(self._detect({"LANGUAGE": "en:ru"}), "en")

    def test_windows_api_is_not_called_elsewhere(self):
        with mock.patch.object(i18n.sys, "platform", "linux"):
            self.assertIsNone(i18n._windows_ui_language())

    def test_set_language_pins_and_resets(self):
        self.assertEqual(i18n.set_language("ru"), "ru")
        self.assertEqual(i18n.get_language(), "ru")
        self.assertEqual(i18n.set_language("en"), "en")
        with mock.patch.object(i18n, "detect_language", return_value="ru"):
            self.assertEqual(i18n.set_language(None), "ru")


class TestText(LanguageCase):
    def test_value_follows_the_language_and_keeps_both(self):
        i18n.set_language("en")
        message = L("Not found", "Не найдено")
        self.assertEqual(message, "Not found")
        self.assertEqual(message.translations, {"en": "Not found", "ru": "Не найдено"})
        i18n.set_language("ru")
        self.assertEqual(L("Not found", "Не найдено"), "Не найдено")
        # an existing Text does not change its value afterwards, but still knows both texts
        self.assertEqual(pick(message, "ru"), "Не найдено")
        self.assertEqual(pick(message, "en"), "Not found")

    def test_plain_strings_are_the_same_in_both_languages(self):
        self.assertEqual(pick("C:/saves", "ru"), "C:/saves")
        self.assertEqual(both("C:/saves"), {"en": "C:/saves", "ru": "C:/saves"})
        self.assertEqual(both(L("a", "б")), {"en": "a", "ru": "б"})

    def test_survives_copy_and_pickle(self):
        # The state cache deep-copies its data; a Text must come out intact.
        i18n.set_language("en")
        original = L("Done", "Готово")
        for clone in (copy.copy(original), copy.deepcopy(original), pickle.loads(pickle.dumps(original))):  # nosec B301
            self.assertIsInstance(clone, Text)
            self.assertEqual(clone, "Done")
            self.assertEqual(clone.translations["ru"], "Готово")
        nested = copy.deepcopy({"warnings": [original]})
        self.assertEqual(nested["warnings"][0].translations["ru"], "Готово")


class TestBilingualErrors(LanguageCase):
    def test_error_payload_carries_both_languages(self):
        error = SaveError("x", L("Title", "Заголовок"), L("Detail", "Подробности"), [L("Step", "Шаг")])
        payload = error.to_dict()
        self.assertEqual(payload["i18n"]["en"], {"title": "Title", "detail": "Detail", "steps": ["Step"]})
        self.assertEqual(payload["i18n"]["ru"], {"title": "Заголовок", "detail": "Подробности", "steps": ["Шаг"]})

    def test_real_error_from_the_save_finder_is_bilingual(self):
        from stardew_tracker.savefinder import find_saves

        with self.assertRaises(SaveError) as caught:
            find_saves(explicit=os.path.join(tempfile.gettempdir(), "definitely-missing-save-folder"))
        payload = caught.exception.to_dict()
        self.assertIn("Path not found", payload["i18n"]["en"]["title"])
        self.assertIn("Путь не найден", payload["i18n"]["ru"]["title"])
        self.assertEqual(len(payload["i18n"]["en"]["steps"]), len(payload["i18n"]["ru"]["steps"]))


class TestCommandNameInHints(LanguageCase):
    """The packaged app is started as StardewTracker, not as `python tracker.py`."""

    def _missing_path_steps(self, command):
        from stardew_tracker import savefinder

        with mock.patch.object(savefinder, "COMMAND", command), self.assertRaises(SaveError) as caught:
            savefinder.find_saves(explicit=os.path.join(tempfile.gettempdir(), "definitely-missing-save-folder"))
        return caught.exception.to_dict()["i18n"]

    def test_source_tree_hint_names_the_python_script(self):
        steps = self._missing_path_steps("python tracker.py")
        self.assertIn("python tracker.py info", " ".join(steps["en"]["steps"]))
        self.assertIn("python tracker.py info", " ".join(steps["ru"]["steps"]))

    def test_packaged_app_hint_names_the_app(self):
        steps = self._missing_path_steps("StardewTracker")
        for lang in ("en", "ru"):
            joined = " ".join(steps[lang]["steps"])
            self.assertIn("StardewTracker info", joined, lang)
            self.assertNotIn("tracker.py", joined, lang)

    def test_no_saves_hint_uses_the_same_name(self):
        from stardew_tracker import savefinder

        with mock.patch.object(savefinder, "COMMAND", "StardewTracker"):
            steps = savefinder.no_saves_error().to_dict()["i18n"]["en"]["steps"]
        self.assertTrue(all("tracker.py" not in step for step in steps), steps)
        self.assertIn("StardewTracker serve --save", steps[0])

    def test_command_matches_how_the_program_runs(self):
        from stardew_tracker import paths

        self.assertEqual(paths.COMMAND, "StardewTracker" if paths.FROZEN else "python tracker.py")


class TestCliLanguage(LanguageCase):
    def _run(self, argv):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = cli.main(argv)
        return code, output.getvalue()

    def test_lang_flag_selects_the_console_language(self):
        tmp = tempfile.mkdtemp(prefix="sdv-lang-")
        try:
            write_test_save(tmp)
            code, text = self._run(["info", "--lang", "ru", "--saves-dir", tmp])
            self.assertEqual(code, 0)
            self.assertIn("Найдено сохранений", text)
            code, text = self._run(["info", "--lang", "en", "--saves-dir", tmp])
            self.assertIn("Saves found", text)
            self.assertIn("perfection", text)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_environment_variable_is_used_without_the_flag(self):
        tmp = tempfile.mkdtemp(prefix="sdv-lang-env-")
        try:
            write_test_save(tmp)
            with mock.patch.dict(os.environ, {i18n.ENV_VAR: "ru"}):
                _code, text = self._run(["info", "--saves-dir", tmp])
            self.assertIn("перфекция", text)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_help_is_localised(self):
        i18n.set_language("ru")
        self.assertIn("файл сейва", cli.build_parser().format_help())
        i18n.set_language("en")
        self.assertIn("save file or save folder", cli.build_parser().format_help())

    def test_requested_language_ignores_garbage(self):
        self.assertEqual(cli._requested_language(["--lang", "ru"]), "ru")
        self.assertEqual(cli._requested_language(["info"]), None)
        self.assertEqual(cli._requested_language(["--lang", "klingon"]), None)


class TestHttpErrorLanguage(unittest.TestCase):
    def _handler(self, accept_language):
        handler = object.__new__(server._BaseHandler)
        handler.headers = {"Accept-Language": accept_language} if accept_language is not None else {}  # type: ignore[assignment]
        return handler

    def test_accept_language_picks_the_text(self):
        for header, expected in (
            ("ru-RU,ru;q=0.9,en;q=0.8", "ru-text"),
            ("en-US,en;q=0.9", "en-text"),
            ("de", "en-text"),
            ("", "en-text"),
            (None, "en-text"),
        ):
            self.assertEqual(self._handler(header)._text("en-text", "ru-text"), expected, header)


class TestEnglishFirstPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = TEMPLATE.read_text(encoding="utf-8")

    def test_static_markup_is_english(self):
        self.assertIn('<html lang="en">', self.html)
        self.assertIn("<title>Stardew Tracker — Farm Progress</title>", self.html)
        self.assertIn('aria-label="Sections"', self.html)

    def test_language_is_chosen_from_storage_then_the_browser(self):
        for token in (
            "function systemLanguage()",
            "function storedLanguage()",
            "navigator.languages",
            'startsWith("ru") ? "ru" : "en"',
            "lang: storedLanguage() || systemLanguage(),",
        ):
            self.assertIn(token, self.html)

    def test_first_run_chooser(self):
        for token in (
            'id="langModal"',
            'role="dialog"',
            'data-lang="en"',
            'data-lang="ru"',
            'id="langRemember"',
            "function langGate()",
            "langGate();",
            'if ($("#langRemember").checked) LS.set("lang", lang);',
            "if (langOpen) langChoose?.(prefs.lang);",
        ):
            self.assertIn(token, self.html)
        # the dialog is bilingual by itself: it is shown before a language is known
        self.assertIn("Choose your language · Выберите язык", self.html)

    def test_beta_banner_points_to_feedback(self):
        for token in (
            'id="betaBanner"',
            "function betaBanner()",
            'const FEEDBACK_EMAIL = "repro4chful@gmail.com";',
            "https://github.com/KyuuketsukiAkado/stardew-tracker/issues",
            'rel="noopener noreferrer"',
            "alpha|beta|rc|dev",
            'LS.set("betaDismissed", version);',
        ):
            self.assertIn(token, self.html)

    def test_russian_wording_does_not_assume_the_readers_gender(self):
        self.assertIn("догадаться самому", self.html)
        self.assertNotIn("догадаться самой", self.html)
        self.assertNotIn("farmerFallback", self.html)

    def test_state_tells_the_page_its_version(self):
        tmp = tempfile.mkdtemp(prefix="sdv-meta-")
        try:
            write_test_save(tmp)
            from stardew_tracker import __version__
            from stardew_tracker.state import build_state

            self.assertEqual(build_state(None, tmp)["meta"]["app_version"], __version__)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
