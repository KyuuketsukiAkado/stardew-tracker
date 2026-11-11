"""The tracker asks before it looks for saves on its own."""

from __future__ import annotations

import builtins
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from langpin import pin_english, unpin  # noqa: E402
from make_test_save import write_test_save  # noqa: E402

from stardew_tracker import cli, consent, i18n, paths, savefinder  # noqa: E402
from stardew_tracker.errors import ConsentRequired, SaveError  # noqa: E402
from stardew_tracker.server import TrackerApp, TrackerHTTPServer  # noqa: E402
from stardew_tracker.state import build_state, list_saves_info  # noqa: E402

# The real function, captured before the fixtures replace it.
_REAL_CANDIDATES = savefinder.candidate_save_dirs


def setUpModule():
    pin_english()


def tearDownModule():
    unpin()


class ConsentCase(unittest.TestCase):
    """A private settings file and a fake 'standard folder' with one save in it."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sdv-consent-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.settings = os.path.join(self.tmp, "settings.json")
        self.standard = os.path.join(self.tmp, "StardewValley", "Saves")
        self.save = write_test_save(self.standard)
        self.unused_saves = os.path.join(self.tmp, "no-saves-here")
        environment = {key: value for key, value in os.environ.items() if key != consent.ALLOW_ENV}
        for patcher in (
            mock.patch.object(paths, "SETTINGS_FILE", self.settings),
            mock.patch.object(paths, "GOALS_FILE", os.path.join(self.tmp, "goals.json")),
            mock.patch.object(savefinder, "candidate_save_dirs", return_value=[self.standard]),
            mock.patch.object(savefinder, "SAVES_DIR", self.unused_saves),
            mock.patch.dict(os.environ, environment, clear=True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(setattr, consent, "_memory", None)
        self.addCleanup(setattr, consent, "_env_withdrawn", False)
        consent._memory = None
        consent._env_withdrawn = False


class TestStore(ConsentCase):
    def test_nothing_is_allowed_until_asked(self):
        self.assertEqual(consent.load(), {"scan_standard_folders": False, "extra_folders": []})
        self.assertFalse(consent.standard_allowed())
        self.assertFalse(os.path.exists(self.settings))

    def test_choice_is_written_and_can_be_withdrawn(self):
        consent.allow_standard(True)
        with open(self.settings, encoding="utf-8") as handle:
            self.assertTrue(json.load(handle)["scan_standard_folders"])
        self.assertTrue(consent.standard_allowed())
        consent.forget()
        self.assertFalse(consent.standard_allowed())
        self.assertEqual(consent.extra_folders(), [])

    def test_damaged_or_foreign_settings_mean_not_asked(self):
        for content in ("{not json", "[]", '{"scan_standard_folders": "yes", "extra_folders": "x"}'):
            with open(self.settings, "w", encoding="utf-8") as handle:
                handle.write(content)
            self.assertFalse(consent.standard_allowed(), content)
            self.assertEqual(consent.extra_folders(), [], content)

    def test_added_folder_must_exist_and_is_stored_once(self):
        with self.assertRaises(ValueError):
            consent.add_folder(os.path.join(self.tmp, "missing"))
        folder = os.path.join(self.tmp, "Mine")
        os.makedirs(folder)
        self.assertEqual(consent.add_folder(folder), os.path.abspath(folder))
        consent.add_folder(folder)
        self.assertEqual(consent.extra_folders(), [os.path.abspath(folder)])
        self.assertFalse(consent.standard_allowed(), "a folder of your own is not permission for the standard ones")

    def test_unwritable_settings_keep_the_answer_for_this_run(self):
        with mock.patch("os.replace", side_effect=OSError("read-only")):
            consent.allow_standard(True)
        self.assertTrue(consent.standard_allowed())
        self.assertFalse(os.path.exists(self.settings))
        self.assertEqual([name for name in os.listdir(self.tmp) if name.endswith(".tmp")], [])

    def test_environment_variable_allows_without_writing(self):
        with mock.patch.dict(os.environ, {consent.ALLOW_ENV: "1"}):
            self.assertTrue(consent.standard_allowed())
            self.assertTrue(consent.status(["x"])["by_environment"])
        self.assertFalse(os.path.exists(self.settings))

    def test_withdrawal_overrides_environment_for_this_run(self):
        with mock.patch.dict(os.environ, {consent.ALLOW_ENV: "1"}):
            self.assertTrue(consent.standard_allowed())
            consent.forget()
            self.assertFalse(consent.standard_allowed())
            self.assertFalse(consent.status(["x"])["by_environment"])
            consent.allow_standard(True)
            self.assertTrue(consent.standard_allowed())

    def test_status_describes_what_the_page_shows(self):
        self.assertEqual(
            consent.status(["a", "b"]),
            {"standard": ["a", "b"], "standard_allowed": False, "by_environment": False, "extra": []},
        )


class TestAutomaticSearch(ConsentCase):
    def test_no_folder_is_touched_before_permission(self):
        with (
            mock.patch.object(savefinder, "_scan_dir", side_effect=AssertionError("must not scan")),
            mock.patch.object(savefinder.os, "listdir", side_effect=AssertionError("must not list")),
            self.assertRaises(ConsentRequired) as caught,
        ):
            savefinder.find_saves()
        error = caught.exception
        self.assertEqual(error.kind, "consent_required")
        self.assertEqual(error.data["folders"], [self.standard, self.unused_saves])
        self.assertIsInstance(error, SaveError)

    def test_every_entry_point_of_the_automatic_search_asks(self):
        for call in (lambda: build_state(None, None), lambda: list_saves_info()):
            with self.assertRaises(ConsentRequired):
                call()

    def test_search_works_after_the_user_allows_it(self):
        consent.allow_standard(True)
        self.assertEqual(savefinder.find_saves(), [self.save])

    def test_a_folder_added_by_hand_is_searched_without_the_standard_ones(self):
        mine = os.path.join(self.tmp, "Elsewhere")
        other = write_test_save(mine)
        consent.add_folder(mine)
        self.assertEqual(savefinder.find_saves(), [other])

    def test_pointing_at_a_path_needs_no_permission(self):
        self.assertEqual(savefinder.find_saves(explicit=self.save), [self.save])
        self.assertEqual(savefinder.find_saves(saves_dir=self.standard), [self.save])
        self.assertEqual(build_state(self.save, None)["meta"]["farm"], "Тестовая")

    def test_standard_folders_belong_to_the_current_system(self):
        windows = _REAL_CANDIDATES("win32")
        mac = _REAL_CANDIDATES("darwin")
        linux = _REAL_CANDIDATES("linux")
        self.assertEqual(len(windows), 1)
        self.assertTrue(windows[0].endswith(os.path.join("StardewValley", "Saves")))
        self.assertEqual(len(mac), 1)
        self.assertIn("Application Support", mac[0])
        self.assertEqual(len(linux), 2)
        self.assertTrue(any("compatdata" in item for item in linux))
        self.assertFalse(set(windows) & set(linux), "other systems' folders are not listed or opened")

    def test_payload_carries_both_languages_and_the_folders(self):
        with self.assertRaises(ConsentRequired) as caught:
            savefinder.find_saves()
        payload = caught.exception.to_dict()
        self.assertEqual(payload["kind"], "consent_required")
        self.assertEqual(payload["data"]["folders"], [self.standard, self.unused_saves])
        self.assertIn("Allow the tracker", payload["i18n"]["en"]["title"])
        self.assertIn("Разрешить трекеру", payload["i18n"]["ru"]["title"])
        self.assertTrue(all(self.standard in payload["i18n"][lang]["detail"] for lang in ("en", "ru")))
        joined = " ".join(payload["i18n"]["en"]["steps"])
        self.assertIn("--allow-scan", joined)
        self.assertIn("--saves-dir", joined)


class TestCommandLine(ConsentCase):
    def _run(self, argv, *, interactive=False, answer=None):
        output = io.StringIO()
        patches = [mock.patch.object(cli, "_interactive", return_value=interactive)]
        if answer is not None:
            patches.append(mock.patch.object(builtins, "input", return_value=answer))
        with contextlib.ExitStack() as stack:
            for patcher in patches:
                stack.enter_context(patcher)
            stack.enter_context(contextlib.redirect_stdout(output))
            code = cli.main(argv)
        return code, output.getvalue()

    def test_a_script_without_permission_gets_the_explanation(self):
        with self.assertRaises(ConsentRequired) as caught:
            self._run(["info"])
        self.assertIn("--allow-scan", str(caught.exception))
        self.assertFalse(os.path.exists(self.settings))

    def test_allow_scan_flag_allows_and_remembers(self):
        code, text = self._run(["info", "--allow-scan"])
        self.assertEqual(code, 0)
        self.assertIn("Saves found: 1", text)
        self.assertTrue(consent.load()["scan_standard_folders"])
        # next time no flag is needed
        self.assertEqual(self._run(["info"])[0], 0)

    def test_terminal_user_is_asked_and_the_answer_is_respected(self):
        for answer in ("y", "yes", "да"):
            consent.forget()
            code, text = self._run(["info"], interactive=True, answer=answer)
            self.assertEqual(code, 0, answer)
            self.assertIn(self.standard, text)
            self.assertIn("nothing is sent anywhere", text)
            self.assertTrue(consent.standard_allowed(), answer)
        consent.forget()
        with self.assertRaises(ConsentRequired):
            self._run(["info"], interactive=True, answer="n")
        self.assertFalse(consent.standard_allowed())

    def test_naming_a_path_never_asks(self):
        with mock.patch.object(builtins, "input", side_effect=AssertionError("must not ask")):
            self.assertEqual(self._run(["info", "--saves-dir", self.standard], interactive=True)[0], 0)
            self.assertEqual(self._run(["info", "--save", self.save], interactive=True)[0], 0)
        self.assertFalse(consent.standard_allowed())

    def test_serve_never_blocks_on_a_console_question(self):
        with (
            mock.patch.object(cli, "serve") as serve,
            mock.patch.object(builtins, "input", side_effect=AssertionError("must not ask")),
        ):
            self.assertEqual(self._run(["serve", "--no-open"], interactive=True)[0], 0)
        serve.assert_called_once()

    def test_help_mentions_the_flag(self):
        self.assertIn("--allow-scan", cli.build_parser().format_help())


class TestHttp(ConsentCase):
    def setUp(self):
        super().setUp()
        self.app = TrackerApp()
        try:
            self.app.load()
        except SaveError as exc:
            self.app.set_error(exc)  # what serve() does when there is nothing to show yet
        self.server = TrackerHTTPServer(("127.0.0.1", 0), self.app)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_port

    def call(self, method, path, payload=None, headers=None):
        connection = HTTPConnection("127.0.0.1", self.port, timeout=5)
        body = None if payload is None else json.dumps(payload)
        request_headers = dict(headers or {})
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, (json.loads(data) if data[:1] in (b"{", b"[") else data)

    def test_a_watcher_result_from_before_withdrawal_is_discarded(self):
        self.call("POST", "/api/consent", {"allow": True})
        revision = self.app._permission_revision
        self.call("POST", "/api/consent", {"forget": True})
        self.assertFalse(self.app.set_state_if_current({"meta": {}}, None, None, revision))
        self.assertIsNone(self.app.state)

    def test_page_and_state_ask_for_permission_first(self):
        status, body = self.call("GET", "/api/state")
        self.assertEqual(status, 404)
        self.assertEqual(body["error"]["kind"], "consent_required")
        self.assertEqual(body["error"]["data"]["folders"], [self.standard, self.unused_saves])
        status, page = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b'"kind": "consent_required"', page)
        self.assertIn(self.standard.replace("\\", "\\\\").encode(), page)

    def test_consent_info_endpoint(self):
        status, info = self.call("GET", "/api/consent")
        self.assertEqual(status, 200)
        self.assertEqual(info["standard"], [self.standard, self.unused_saves])
        self.assertFalse(info["standard_allowed"])
        self.assertEqual(info["extra"], [])

    def test_allowing_loads_the_save_at_once(self):
        status, body = self.call("POST", "/api/consent", {"allow": True})
        self.assertEqual((status, body["ok"], body["consent"]["standard_allowed"]), (200, True, True))
        status, state = self.call("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(state["meta"]["farm"], "Тестовая")
        self.assertTrue(consent.load()["scan_standard_folders"])

    def test_withdrawing_removes_the_data_and_asks_again(self):
        self.call("POST", "/api/consent", {"allow": True})
        status, body = self.call("POST", "/api/consent", {"forget": True})
        self.assertEqual(status, 200)
        self.assertFalse(body["consent"]["standard_allowed"])
        status, body = self.call("GET", "/api/state")
        self.assertEqual((status, body["error"]["kind"]), (404, "consent_required"))

    def test_environment_grant_can_also_be_withdrawn_from_the_page(self):
        with mock.patch.dict(os.environ, {consent.ALLOW_ENV: "1"}):
            self.assertTrue(self.call("GET", "/api/consent")[1]["by_environment"])
            status, body = self.call("POST", "/api/consent", {"forget": True})
            self.assertEqual(status, 200)
            self.assertFalse(body["consent"]["standard_allowed"])
            self.assertFalse(body["consent"]["by_environment"])
            self.assertEqual(self.call("GET", "/api/state")[1]["error"]["kind"], "consent_required")

    def test_selected_save_is_no_longer_readable_after_withdrawal(self):
        self.call("POST", "/api/consent", {"allow": True})
        status, _ = self.call("POST", "/api/saves/select", {"path": self.save})
        self.assertEqual(status, 200)
        self.assertEqual(self.app.save, os.path.abspath(self.save))
        self.call("POST", "/api/consent", {"forget": True})
        self.assertIsNone(self.app.save)
        self.assertEqual(self.call("GET", "/api/state")[1]["error"]["kind"], "consent_required")
        self.assertEqual(self.call("GET", "/api/saves")[1]["saves"], [])
        self.assertEqual(self.call("POST", "/api/saves/select", {"path": self.save})[0], 403)
        self.assertEqual(self.call("GET", "/api/refresh")[1]["error"]["kind"], "consent_required")

    def test_explicit_launch_save_remains_available_without_scan_permission(self):
        explicit = TrackerApp(save=self.save)
        explicit.load()
        explicit.apply_consent(forget=True)
        self.assertEqual(explicit.save, self.save)
        self.assertEqual(explicit.state["meta"]["farm"], "Тестовая")
        self.assertFalse(consent.standard_allowed())

    def test_explicit_save_does_not_open_or_offer_siblings(self):
        sibling = os.path.join(self.standard, "Other_777", "Other_777")
        os.makedirs(os.path.dirname(sibling))
        shutil.copyfile(self.save, sibling)
        self.app.save = self.app._launch_save = self.save
        self.app.load()
        for allow in (False, True):
            if allow:
                consent.allow_standard(True)
            with mock.patch.object(savefinder, "_scan_dir", side_effect=AssertionError("no sibling scan")):
                status, result = self.call("GET", "/api/saves")
                self.assertEqual(status, 200)
                self.assertEqual([item["path"] for item in result["saves"]], [self.save])
                self.assertEqual(self.app.allowed_save_paths(), {os.path.abspath(self.save)})
                self.assertEqual(self.call("POST", "/api/saves/select", {"path": sibling})[0], 403)

    def test_a_folder_of_your_own_is_accepted_and_validated(self):
        mine = os.path.join(self.tmp, "Elsewhere")
        write_test_save(mine)
        status, body = self.call("POST", "/api/consent", {"folder": os.path.join(self.tmp, "missing")})
        self.assertEqual(status, 400)
        self.assertIn("Not a folder", body["error"])
        status, body = self.call("POST", "/api/consent", {"folder": mine})
        self.assertEqual(status, 200)
        self.assertEqual(body["consent"]["extra"], [os.path.abspath(mine)])
        self.assertFalse(body["consent"]["standard_allowed"])
        self.assertEqual(self.call("GET", "/api/state")[0], 200)

    def test_bad_requests_are_rejected_in_the_browsers_language(self):
        for payload in ({}, {"allow": "yes"}, {"folder": 5}, {"allow": None}):
            status, body = self.call("POST", "/api/consent", payload)
            self.assertEqual(status, 400, payload)
        status, body = self.call("POST", "/api/consent", {}, headers={"Accept-Language": "ru-RU,ru;q=0.9"})
        self.assertEqual((status, body["error"]), (400, "Нечего менять"))
        self.assertFalse(consent.standard_allowed())

    def test_other_pages_do_not_crash_without_permission(self):
        status, body = self.call("GET", "/api/saves")
        self.assertEqual(status, 200)
        self.assertEqual(body["saves"], [])
        self.assertEqual(body["error"]["kind"], "consent_required")
        status, body = self.call("GET", "/api/version")
        self.assertEqual((status, body["ready"]), (200, False))

    def test_changing_permission_needs_a_json_post_from_this_computer(self):
        # no JSON content type -> refused; a foreign Host header -> refused
        connection = HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request("POST", "/api/consent", body='{"allow": true}', headers={"Content-Type": "text/plain"})
        self.assertEqual(connection.getresponse().status, 415)
        connection.close()
        status, _ = self.call("POST", "/api/consent", {"allow": True}, headers={"Host": "evil.example"})
        self.assertEqual(status, 403)
        self.assertFalse(consent.standard_allowed())


class TestWatcherAndLanguage(ConsentCase):
    def test_withdrawal_waits_for_inflight_read_and_blocks_later_reads(self):
        from stardew_tracker import server

        i18n.set_language("en")
        app = TrackerApp()
        consent.allow_standard(True)
        stop = threading.Event()
        started, release, withdrawn = threading.Event(), threading.Event(), threading.Event()
        touched_after_withdrawal = []
        real_build, real_scan = server.build_state, savefinder._scan_dir

        def slow_build(save, saves_dir):
            if not started.is_set():
                started.set()
                release.wait(5)
            return real_build(save, saves_dir)

        def guarded_scan(directory, strict=True):
            if withdrawn.is_set():
                touched_after_withdrawal.append(directory)
            return real_scan(directory, strict=strict)

        with (
            mock.patch.object(server, "build_state", side_effect=slow_build),
            mock.patch.object(savefinder, "_scan_dir", side_effect=guarded_scan),
        ):
            watcher = threading.Thread(target=server.watch_loop, args=(app, stop, 0.01), daemon=True)
            revoker = None
            watcher.start()
            try:
                self.assertTrue(started.wait(5))

                def withdraw():
                    app.apply_consent(forget=True)
                    withdrawn.set()

                revoker = threading.Thread(target=withdraw, daemon=True)
                revoker.start()
                self.assertFalse(withdrawn.wait(0.1), "withdrawal must wait for the in-flight save read")
                release.set()
                self.assertTrue(withdrawn.wait(5))
                self.assertIsNone(app.state)
                self.assertEqual(app.error["kind"], "consent_required")
                stop.wait(0.15)  # let the watcher attempt its next pass
            finally:
                release.set()
                stop.set()
                watcher.join(5)
                if revoker is not None:
                    revoker.join(5)
        self.assertEqual(touched_after_withdrawal, [])

    def test_waiting_for_an_answer_is_quiet_in_the_console(self):
        from stardew_tracker.server import watch_loop

        app = TrackerApp()
        stop = threading.Event()
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            thread = threading.Thread(target=watch_loop, args=(app, stop, 0.01), daemon=True)
            thread.start()
            deadline = threading.Event()
            deadline.wait(0.2)
            stop.set()
            thread.join(2)
        self.assertEqual(errors.getvalue(), "")
        self.assertEqual(app.error["kind"], "consent_required")

    def test_console_waiting_message_lists_the_folders(self):
        from stardew_tracker import server

        out = io.StringIO()
        with (
            mock.patch.object(server, "TrackerHTTPServer") as httpd,
            contextlib.redirect_stdout(out),
        ):
            httpd.return_value.serve_forever.side_effect = KeyboardInterrupt
            server.serve(port=0, open_browser=False, watch=False)
        text = out.getvalue()
        self.assertIn(self.standard, text)
        self.assertIn("Allow", text)
        i18n.set_language("ru")
        out = io.StringIO()
        with (
            mock.patch.object(server, "TrackerHTTPServer") as httpd,
            contextlib.redirect_stdout(out),
        ):
            httpd.return_value.serve_forever.side_effect = KeyboardInterrupt
            server.serve(port=0, open_browser=False, watch=False)
        self.assertIn("Разрешить", out.getvalue())


if __name__ == "__main__":
    unittest.main()
