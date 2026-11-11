"""Тесты жизненного цикла сервера, наблюдателя и CLI."""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from typing import ClassVar
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from langpin import pin_english, unpin  # noqa: E402
from make_test_save import write_test_save  # noqa: E402

from stardew_tracker import (  # noqa: E402
    SaveError,
    cli,
    server,
)


def setUpModule():
    pin_english()


def tearDownModule():
    unpin()


class FakeHTTPD:
    instances: ClassVar[list[FakeHTTPD]] = []

    def __init__(self, address, app):
        self.address = address
        self.app = app
        self.closed = False
        self.served = False
        FakeHTTPD.instances.append(self)

    def serve_forever(self):
        self.served = True
        raise KeyboardInterrupt

    def server_close(self):
        self.closed = True


class TestServe(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sdv-serve-")
        self.save = write_test_save(self.tmp)
        FakeHTTPD.instances.clear()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_serve_starts_and_stops_cleanly(self):
        output = io.StringIO()
        with mock.patch.object(server, "TrackerHTTPServer", FakeHTTPD), contextlib.redirect_stdout(output):
            server.serve(port=0, save=self.save, open_browser=False, watch=False)
        self.assertTrue(FakeHTTPD.instances)
        self.assertTrue(FakeHTTPD.instances[0].served)
        self.assertTrue(FakeHTTPD.instances[0].closed)
        self.assertIn("Тестовая", output.getvalue())
        self.assertIn("Stopped", output.getvalue())

    def test_serve_waiting_mode_without_save(self):
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(empty)
        output, errors = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(server, "TrackerHTTPServer", FakeHTTPD),
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(errors),
        ):
            server.serve(port=0, saves_dir=empty, open_browser=False, watch=False)
        self.assertIn("waiting for a save", output.getvalue())
        self.assertIn("No save file found", errors.getvalue())

    def test_explicit_missing_save_is_fatal(self):
        with mock.patch.object(server, "TrackerHTTPServer", FakeHTTPD):
            with self.assertRaises(SaveError):
                server.serve(port=0, save=os.path.join(self.tmp, "missing"), open_browser=False, watch=False)


class TestWatchLoop(unittest.TestCase):
    def test_watch_rebuilds_state_after_save_change(self):
        tmp = tempfile.mkdtemp(prefix="sdv-watch-")
        try:
            save = write_test_save(tmp)
            app = server.TrackerApp(save=save)
            app.load()
            before = app.state["meta"]["save_path"]
            stop = threading.Event()
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                thread = threading.Thread(target=server.watch_loop, args=(app, stop, 0.02), daemon=True)
                thread.start()
                try:
                    time.sleep(0.1)
                    with open(save, "a", encoding="utf-8") as handle:
                        handle.write(" ")
                    stat = os.stat(save)
                    os.utime(save, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
                    deadline = time.time() + 5
                    while time.time() < deadline and "save updated" not in output.getvalue():
                        time.sleep(0.02)
                finally:
                    stop.set()
                    thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(app.state["meta"]["save_path"], before)
            self.assertIn("save updated", output.getvalue())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestCliRun(unittest.TestCase):
    def test_open_command_opens_browser(self):
        tmp = tempfile.mkdtemp(prefix="sdv-open-")
        try:
            target = os.path.join(tmp, "report.html")
            with open(target, "w", encoding="utf-8") as handle:
                handle.write("<html></html>")
            with (
                mock.patch.object(cli, "build_report", return_value=({}, target)),
                mock.patch.object(cli.webbrowser, "open") as opener,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(cli.main(["open"]), 0)
            opener.assert_called_once()
            self.assertTrue(opener.call_args[0][0].startswith("file://"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_info_without_saves_prints_hint(self):
        tmp = tempfile.mkdtemp(prefix="sdv-no-saves-")
        try:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(cli.main(["info", "--saves-dir", tmp]), 0)
            self.assertIn("Hint", output.getvalue())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_run_maps_errors_to_exit_codes(self):
        with (
            mock.patch.object(cli, "main", side_effect=RuntimeError("boom")),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            with self.assertRaises(SystemExit) as context:
                cli.run()
        self.assertEqual(context.exception.code, 1)

        with mock.patch.object(cli, "main", side_effect=KeyboardInterrupt), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as context:
                cli.run()
        self.assertEqual(context.exception.code, 130)

    def test_serve_command_forwards_options(self):
        with mock.patch.object(cli, "serve") as serve_mock:
            self.assertEqual(
                cli.main(["serve", "--port", "9000", "--host", "0.0.0.0", "--no-open", "--no-watch"]),
                0,
            )
        serve_mock.assert_called_once()
        kwargs = serve_mock.call_args.kwargs
        self.assertEqual(kwargs["port"], 9000)
        self.assertEqual(kwargs["host"], "0.0.0.0")
        self.assertFalse(kwargs["open_browser"])
        self.assertFalse(kwargs["watch"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
