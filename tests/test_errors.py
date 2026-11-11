"""Ошибки и имена модулей: то, что раньше тихо ломалось в потоках и в IDE."""

from __future__ import annotations

import contextlib
import importlib
import importlib.util
import io
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import stardew_tracker  # noqa: E402
from stardew_tracker import DataError, SaveError, TrackerError, cli, i18n, server  # noqa: E402
from stardew_tracker.i18n import L  # noqa: E402


def _pin_language(case: unittest.TestCase, lang: str = "en") -> None:
    i18n.set_language(lang)
    case.addCleanup(i18n.set_language, None)


def _error() -> SaveError:
    return SaveError(
        "io_error",
        L("Cannot read", "Не читается"),
        L("Disk unavailable", "Диск недоступен"),
        [L("Check the disk", "Проверьте диск"), L("Restart", "Перезапустите")],
    )


class TestErrorHierarchy(unittest.TestCase):
    def test_tracker_errors_are_ordinary_exceptions(self):
        # SystemExit, пойманный ``except Exception``, не ловится, а в потоке сервера
        # он ещё и молча обрывал обработчик (клиент получал оборванное соединение).
        for cls in (TrackerError, SaveError, DataError):
            self.assertTrue(issubclass(cls, Exception), cls)
            self.assertFalse(issubclass(cls, SystemExit), cls)
        self.assertTrue(issubclass(SaveError, TrackerError))
        self.assertTrue(issubclass(DataError, SaveError))

    def test_except_exception_catches_a_save_error(self):
        try:
            raise _error()
        except Exception as exc:
            self.assertIsInstance(exc, SaveError)
        else:
            self.fail("исключение должно было сработать")

    def test_message_and_dict_keep_their_format(self):
        _pin_language(self, "en")
        error = _error()
        self.assertEqual(
            str(error),
            "Error: Cannot read\n  Disk unavailable\nWhat to do:\n  1. Check the disk\n  2. Restart",
        )
        payload = error.to_dict()
        self.assertEqual(
            {key: payload[key] for key in ("kind", "title", "detail", "steps")},
            {
                "kind": "io_error",
                "title": "Cannot read",
                "detail": "Disk unavailable",
                "steps": ["Check the disk", "Restart"],
            },
        )
        # The page receives both languages and picks its own.
        self.assertEqual(payload["i18n"]["en"]["title"], "Cannot read")
        self.assertEqual(payload["i18n"]["ru"]["title"], "Не читается")
        self.assertEqual(payload["i18n"]["ru"]["steps"], ["Проверьте диск", "Перезапустите"])

    def test_message_follows_the_console_language(self):
        _pin_language(self, "ru")
        self.assertEqual(
            str(_error()),
            "Ошибка: Не читается\n  Диск недоступен\nЧто сделать:\n  1. Проверьте диск\n  2. Перезапустите",
        )

    def test_data_error_points_at_the_data_folder(self):
        error = DataError("Справочник", "битый")
        self.assertEqual(error.kind, "data_error")
        self.assertIn("data/", error.steps[0])


class TestCliRunMapsTrackerErrors(unittest.TestCase):
    def test_tracker_error_prints_message_without_traceback_and_exits_1(self):
        _pin_language(self, "en")
        stderr = io.StringIO()
        with mock.patch.object(cli, "main", side_effect=_error()), contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as context:
                cli.run()
        self.assertEqual(context.exception.code, 1)
        self.assertIn("Error: Cannot read", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_exit_code_of_main_is_passed_through(self):
        with mock.patch.object(cli, "main", return_value=0):
            with self.assertRaises(SystemExit) as context:
                cli.run()
        self.assertEqual(context.exception.code, 0)


class TestServeWhenPortsAreBusy(unittest.TestCase):
    def test_busy_ports_raise_a_tracker_error_with_next_steps(self):
        class Busy:
            def __init__(self, *args, **kwargs):
                raise OSError("address already in use")

        with mock.patch.object(server, "TrackerHTTPServer", Busy):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(TrackerError) as context:
                    server.serve(
                        port=8777, saves_dir=os.path.join(ROOT, "no-such-dir"), open_browser=False, watch=False
                    )
        self.assertEqual(context.exception.kind, "port_busy")
        self.assertIn("8777", context.exception.detail)
        self.assertIn("--port", context.exception.steps[0])


class TestModuleNames(unittest.TestCase):
    def test_render_is_the_function_and_report_is_the_module(self):
        self.assertTrue(callable(stardew_tracker.render))
        self.assertEqual(stardew_tracker.report.__name__, "stardew_tracker.report")
        self.assertIs(stardew_tracker.render, stardew_tracker.report.render)

    def test_old_module_names_are_gone(self):
        for old in ("collections", "requirements"):
            self.assertIsNone(importlib.util.find_spec(f"stardew_tracker.{old}"), old)
        # ``stardew_tracker.render`` — функция, а не модуль
        self.assertFalse(hasattr(sys.modules.get("stardew_tracker.render"), "__file__"))

    def test_no_module_shadows_the_standard_library(self):
        # Запуск файла пакета напрямую (``python stardew_tracker/cli.py``, «Run file»
        # в IDE) кладёт папку пакета в sys.path[0]; одноимённый модуль тогда подменил бы
        # стандартный и ломал бы чужие импорты (так делал бы ``collections.py``).
        names = getattr(sys, "stdlib_module_names", None)
        if names is None:
            self.skipTest("sys.stdlib_module_names появился в Python 3.10")
        package_dir = os.path.dirname(stardew_tracker.__file__)
        shadowing = sorted(
            name[:-3]
            for name in os.listdir(package_dir)
            if name.endswith(".py") and not name.startswith("__") and name[:-3] in names
        )
        self.assertEqual(shadowing, [])


if __name__ == "__main__":
    unittest.main()
