"""Рантайм сервера: Host-защита, ревизии, ETag/gzip, наблюдатель, экранирование.

Эти тесты закрепляют исправления из архитектурного аудита:

* заголовок ``Host`` не проверялся — DNS-rebinding давал чужой странице доступ
  к состоянию фермы;
* вкладка каждые 3 с скачивала и сравнивала всё состояние (сотни КБ) без
  ETag и сжатия;
* наблюдатель считал подпись файла «обработанной» до разбора, поэтому
  кратковременный сбой оставлял состояние устаревшим до следующей записи сейва;
* результат разбора старого сейва мог затереть только что выбранный.
"""

from __future__ import annotations

import contextlib
import gzip
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.client import HTTPConnection
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from make_test_save import write_test_save  # noqa: E402

from stardew_tracker import SaveError, TrackerApp, TrackerHTTPServer, paths, server  # noqa: E402
from stardew_tracker.goals import GOALS_LOCK, save_goals  # noqa: E402
from stardew_tracker.report import _script_safe  # noqa: E402


def _error() -> SaveError:
    return SaveError("io_error", "Ошибка", "Нет доступа", ["Проверьте диск"])


class _ServerCase(unittest.TestCase):
    bind = "127.0.0.1"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sdv-runtime-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        old_goals = paths.GOALS_FILE
        paths.GOALS_FILE = os.path.join(self.tmp, "goals.json")
        self.addCleanup(setattr, paths, "GOALS_FILE", old_goals)
        self.app = TrackerApp(saves_dir=self.tmp, save=write_test_save(self.tmp))
        self.app.load()
        self.server = TrackerHTTPServer((self.bind, 0), self.app)
        # poll_interval по умолчанию 0,5 с делает каждый shutdown() вялым.
        self.thread = threading.Thread(target=self.server.serve_forever, args=(0.01,), daemon=True)
        self.thread.start()
        self.addCleanup(self._stop)

    def _stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def call(self, method, path, body=None, headers=None):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        request_headers = dict(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        connection.request(method, path, body=data, headers=request_headers)
        response = connection.getresponse()
        payload = response.read()
        connection.close()
        return response, payload

    def get_json(self, path, headers=None):
        response, payload = self.call("GET", path, headers=headers)
        self.assertEqual(response.status, 200, payload[:200])
        return json.loads(payload)


class TestHostValidation(_ServerCase):
    def test_own_loopback_names_are_accepted(self):
        port = self.server.server_port
        for host in (f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}", "LOCALHOST", "127.0.0.1"):
            response, _body = self.call("GET", "/api/version", headers={"Host": host})
            self.assertEqual(response.status, 200, host)

    def test_foreign_host_is_rejected_on_every_method_and_route(self):
        evil = {"Host": "evil.example.com"}
        for method, path, body in (
            ("GET", "/", None),
            ("GET", "/api/state", None),
            ("GET", "/api/version", None),
            ("GET", "/api/saves", None),
            ("GET", "/api/goals/export", None),
            ("GET", "/api/refresh", None),
            ("OPTIONS", "/api/goals", None),
            ("POST", "/api/goals", {"goals": [{"id": "x", "title": "evil", "metric": "fish", "target": 1}]}),
        ):
            response, payload = self.call(method, path, body, evil)
            self.assertEqual(response.status, 403, f"{method} {path}")
            if method != "OPTIONS":
                self.assertIn("Host", json.loads(payload)["error"])
        self.assertEqual(self.get_json("/api/state")["goals"]["goals"], [])  # POST не прошёл

    def test_attacker_port_or_ip_literal_is_rejected(self):
        for host in ("attacker.test:80", "192.168.1.5:8777", "127.0.0.1.evil.test", "localhost.evil.test:8777"):
            response, _body = self.call("GET", "/api/state", headers={"Host": host})
            self.assertEqual(response.status, 403, host)

    def test_host_name_parsing(self):
        self.assertEqual(server._host_name("localhost:8777"), "localhost")
        self.assertEqual(server._host_name("  LocalHost "), "localhost")
        self.assertEqual(server._host_name("[::1]:8777"), "::1")
        self.assertEqual(server._host_name("[::1]"), "::1")
        self.assertEqual(server._host_name("::1"), "::1")

    def test_allowed_hosts_policy_follows_bind_address(self):
        for bind in ("127.0.0.1", "localhost", "::1", "[::1]", "127.0.0.2"):
            allowed = server.allowed_hosts_for(bind)
            self.assertIsNotNone(allowed, bind)
            self.assertIn("localhost", allowed)
        self.assertIn("127.0.0.2", server.allowed_hosts_for("127.0.0.2"))
        for bind in ("0.0.0.0", "", "192.168.1.5", "::"):  # nosec B104 - проверка политики, не bind
            self.assertIsNone(server.allowed_hosts_for(bind), bind)


class TestExposedBindAcceptsAnyHost(_ServerCase):
    def test_explicit_lan_exposure_is_not_restricted(self):
        # Реальная привязка к 0.0.0.0 в тесте вызвала бы запрос брандмауэра
        # Windows, поэтому подменяем политику, которую для неё вычисляет сервер.
        self.assertIsNone(server.allowed_hosts_for("0.0.0.0"))  # nosec B104
        self.server.allowed_hosts = None
        response, _body = self.call("GET", "/api/version", headers={"Host": "my-pc.lan:8777"})
        self.assertEqual(response.status, 200)


class TestRevisions(_ServerCase):
    def test_version_shape(self):
        version = self.get_json("/api/version")
        self.assertEqual(set(version), {"rev", "ready", "save_mtime"})
        self.assertTrue(version["ready"])
        self.assertIsInstance(version["save_mtime"], int)
        self.assertRegex(version["rev"], r"^[0-9a-f]{8}-\d+$")

    def test_revision_is_stable_until_something_changes(self):
        first = self.get_json("/api/version")["rev"]
        for _ in range(3):
            self.assertEqual(self.get_json("/api/version")["rev"], first)
            self.get_json("/api/state")
        self.assertEqual(self.get_json("/api/version")["rev"], first)

    def test_goals_post_and_refresh_change_revision(self):
        first = self.get_json("/api/version")["rev"]
        response, _body = self.call("POST", "/api/goals", {"goals": [], "tasks": [{"id": "t", "title": "x"}]})
        self.assertEqual(response.status, 200)
        second = self.get_json("/api/version")["rev"]
        self.assertNotEqual(first, second)
        self.get_json("/api/refresh")
        self.assertNotEqual(second, self.get_json("/api/version")["rev"])

    def test_external_goals_edit_is_picked_up(self):
        first = self.get_json("/api/version")["rev"]
        with open(paths.GOALS_FILE, "w", encoding="utf-8") as handle:
            json.dump({"goals": [], "tasks": [{"id": "by-hand", "title": "edited outside"}]}, handle)
        self.assertNotEqual(self.get_json("/api/version")["rev"], first)
        self.assertEqual(self.get_json("/api/state")["goals"]["tasks"][0]["id"], "by-hand")

    def test_epoch_differs_between_runs(self):
        other = TrackerApp(saves_dir=self.tmp)
        self.assertNotEqual(self.app.epoch, other.epoch)

    def test_repeated_identical_error_does_not_bump_revision(self):
        app = TrackerApp()
        app.set_error(_error())
        first = app.version()["rev"]
        app.set_error(_error())
        self.assertEqual(app.version()["rev"], first)
        app.set_error(SaveError("no_saves", "Другая", "ошибка", []))
        self.assertNotEqual(app.version()["rev"], first)

    def test_version_without_state_is_not_ready(self):
        app = TrackerApp()
        self.assertEqual(app.version()["ready"], False)
        self.assertIsNone(app.version()["save_mtime"])
        self.assertIsNone(app.state_payload())


class TestStatePayload(_ServerCase):
    def test_serialization_happens_once_per_revision(self):
        first = self.app.state_payload()
        self.assertIs(self.app.state_payload(), first)
        goals = save_goals({"goals": [], "tasks": [{"id": "n", "title": "new"}]})  # как делает POST /api/goals
        self.app.set_goals(goals)
        second = self.app.state_payload()
        self.assertIsNot(second, first)
        self.assertNotEqual(first.rev, second.rev)
        self.assertIn(b'"id": "n"', second.raw)

    def test_state_is_replaced_not_mutated(self):
        before = self.app.state
        self.app.set_goals({"goals": [], "tasks": []})
        self.assertIsNot(self.app.state, before)
        self.assertEqual(before["goals"], {"goals": [], "tasks": []})  # прежний объект не тронут
        self.assertIs(self.app.state["meta"], before["meta"])  # а вложенное — общее, без копирования

    def test_etag_and_conditional_get(self):
        response, body = self.call("GET", "/api/state")
        etag = response.headers["ETag"]
        self.assertTrue(etag.startswith('"') and etag.endswith('"'))
        self.assertEqual(response.headers["Cache-Control"], "no-cache")
        self.assertEqual(response.headers["Vary"], "Accept-Encoding")
        self.assertGreater(len(body), 100_000)

        for header in (etag, f"W/{etag}", f'"other", {etag}', "*"):
            response, body = self.call("GET", "/api/state", headers={"If-None-Match": header})
            self.assertEqual(response.status, 304, header)
            self.assertEqual(body, b"")
            self.assertEqual(response.headers["ETag"], etag)

        self.call("POST", "/api/goals", {"goals": [], "tasks": [{"id": "z", "title": "z"}]})
        response, body = self.call("GET", "/api/state", headers={"If-None-Match": etag})
        self.assertEqual(response.status, 200)
        self.assertNotEqual(response.headers["ETag"], etag)

    def test_gzip_is_optional_and_lossless(self):
        plain_response, plain = self.call("GET", "/api/state")
        self.assertIsNone(plain_response.headers.get("Content-Encoding"))
        packed_response, packed = self.call("GET", "/api/state", headers={"Accept-Encoding": "gzip, deflate"})
        self.assertEqual(packed_response.headers["Content-Encoding"], "gzip")
        self.assertLess(len(packed), len(plain) / 3)
        self.assertEqual(gzip.decompress(packed), plain)
        self.assertEqual(packed_response.headers["ETag"], plain_response.headers["ETag"])

    def test_refresh_returns_the_same_cached_payload(self):
        response, body = self.call("GET", "/api/refresh", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(response.status, 200)
        self.assertIn("meta", json.loads(gzip.decompress(body)))
        state_response, _state_body = self.call("GET", "/api/state")
        self.assertEqual(state_response.headers["ETag"], response.headers["ETag"])

    def test_no_save_still_reports_error(self):
        app = TrackerApp()
        app.set_error(_error())
        server_ = TrackerHTTPServer(("127.0.0.1", 0), app)
        thread = threading.Thread(target=server_.serve_forever, daemon=True)
        thread.start()
        try:
            connection = HTTPConnection("127.0.0.1", server_.server_port, timeout=5)
            connection.request("GET", "/api/state")
            response = connection.getresponse()
            payload = json.loads(response.read())
            self.assertEqual(response.status, 404)
            self.assertEqual(payload["error"]["kind"], "io_error")
        finally:
            server_.shutdown()
            server_.server_close()
            thread.join(timeout=2)


class TestGoalsConcurrency(_ServerCase):
    def test_saved_annotations_are_read_under_the_goals_lock(self):
        owned: list[bool] = []
        real_load = server.load_goals

        def spying_load(*args, **kwargs):
            owned.append(GOALS_LOCK._is_owned())  # type: ignore[attr-defined]
            return real_load(*args, **kwargs)

        with mock.patch.object(server, "load_goals", side_effect=spying_load):
            response, _body = self.call("POST", "/api/goals", {"goals": [], "tasks": []})  # без annotations
        self.assertEqual(response.status, 200)
        self.assertEqual(owned, [True])

    def test_parallel_posts_never_corrupt_the_file(self):
        def post(index):
            self.call("POST", "/api/goals", {"goals": [], "tasks": [{"id": f"t{index}", "title": "x"}]})

        threads = [threading.Thread(target=post, args=(i,)) for i in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        with open(paths.GOALS_FILE, encoding="utf-8") as handle:
            saved = json.load(handle)
        self.assertEqual(len(saved["tasks"]), 1)
        self.assertEqual(self.get_json("/api/state")["goals"], saved)


class TestApplyIfCurrent(unittest.TestCase):
    def test_result_for_a_previous_selection_is_dropped(self):
        app = TrackerApp(save="old", saves_dir=None)
        marker = {"meta": {"save_mtime": 1}, "goals": {"goals": [], "tasks": []}}
        app.set_state(marker)
        rev = app.version()["rev"]
        app.save = "new"  # пользователь переключил ферму, пока строилось состояние
        self.assertFalse(app.set_state_if_current({"meta": {"save_mtime": 2}}, "old", None))
        self.assertIs(app.state, marker)
        self.assertEqual(app.version()["rev"], rev)

    def test_result_for_the_current_selection_is_applied_and_clears_error(self):
        app = TrackerApp(save="same", saves_dir="dir")
        app.set_error(_error())
        state = {"meta": {"save_mtime": 3}}
        self.assertTrue(app.set_state_if_current(state, "same", "dir"))
        self.assertIs(app.state, state)
        self.assertIsNone(app.error)


class TestWatchLoop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sdv-watch-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        old_goals = paths.GOALS_FILE
        paths.GOALS_FILE = os.path.join(self.tmp, "goals.json")
        self.addCleanup(setattr, paths, "GOALS_FILE", old_goals)
        self.save = write_test_save(self.tmp)
        self.app = TrackerApp(saves_dir=self.tmp)
        self.stop = threading.Event()
        self.addCleanup(self.stop.set)
        patch = mock.patch.object(server, "_WATCH_RETRY_BASE", 0.01)
        patch.start()
        self.addCleanup(patch.stop)

    def run_loop(self, seconds):
        thread = threading.Thread(target=server.watch_loop, args=(self.app, self.stop, 0.01), daemon=True)
        thread.start()
        time.sleep(seconds)
        self.stop.set()
        thread.join(5)
        self.assertFalse(thread.is_alive())

    def test_transient_failure_is_retried_for_the_same_signature(self):
        fresh = {"meta": {"save_mtime": 7}, "goals": {"goals": [], "tasks": []}}
        calls = []

        def flaky(save, saves_dir):
            calls.append(1)
            if len(calls) == 1:
                raise _error()  # игра ещё держит файл, а подпись уже «финальная»
            return fresh

        with mock.patch.object(server, "build_state", side_effect=flaky):
            self.run_loop(0.6)
        self.assertGreaterEqual(len(calls), 2)
        self.assertIs(self.app.state, fresh)
        self.assertIsNone(self.app.error)

    def test_oserror_is_retried_too(self):
        fresh = {"meta": {"save_mtime": 8}, "goals": {"goals": [], "tasks": []}}
        outcomes = [PermissionError("locked"), fresh]

        def build(save, saves_dir):
            outcome = outcomes.pop(0) if outcomes else fresh
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        with mock.patch.object(server, "build_state", side_effect=build):
            with contextlib.redirect_stderr(io.StringIO()):
                self.run_loop(0.6)
        self.assertIs(self.app.state, fresh)

    def test_retries_are_bounded_and_identical_errors_are_printed_once(self):
        calls = []

        def broken(save, saves_dir):
            calls.append(1)
            raise _error()

        stderr = io.StringIO()
        with mock.patch.object(server, "build_state", side_effect=broken):
            with contextlib.redirect_stderr(stderr):
                self.run_loop(1.2)
        self.assertEqual(len(calls), server._WATCH_RETRY_ATTEMPTS)
        self.assertEqual(stderr.getvalue().count("watch:"), 1)
        self.assertEqual(self.app.error["kind"], "io_error")

    def test_a_changed_file_resets_the_retry_budget(self):
        calls = []

        def broken(save, saves_dir):
            calls.append(1)
            raise _error()

        with mock.patch.object(server, "build_state", side_effect=broken):
            with contextlib.redirect_stderr(io.StringIO()):
                thread = threading.Thread(target=server.watch_loop, args=(self.app, self.stop, 0.01), daemon=True)
                thread.start()
                time.sleep(1.2)
                spent = len(calls)
                with open(self.save, "a", encoding="utf-8") as handle:
                    handle.write("\n<!-- game wrote more -->")
                time.sleep(1.2)
                self.stop.set()
                thread.join(5)
        self.assertEqual(spent, server._WATCH_RETRY_ATTEMPTS)
        self.assertEqual(len(calls), 2 * server._WATCH_RETRY_ATTEMPTS)

    def test_result_is_not_applied_after_selection_changed(self):
        self.app.save = None
        started = threading.Event()
        release = threading.Event()
        stale = {"meta": {"save_mtime": 1}, "goals": {}}

        def slow(save, saves_dir):
            started.set()
            release.wait(5)
            return stale

        with mock.patch.object(server, "build_state", side_effect=slow):
            thread = threading.Thread(target=server.watch_loop, args=(self.app, self.stop, 0.01), daemon=True)
            thread.start()
            self.assertTrue(started.wait(5))
            with self.app.lock:
                self.app.save = self.save  # пользователь выбрал другую ферму
            release.set()
            time.sleep(0.2)
            self.stop.set()
            thread.join(5)
        self.assertIsNot(self.app.state, stale)


class TestScriptSafe(unittest.TestCase):
    HOSTILE = "</script><!--<script>alert(1)\u2028\u2029"

    def test_no_dangerous_sequences_survive(self):
        text = _script_safe({"farm": self.HOSTILE})
        for sequence in ("</", "<!--", "\u2028", "\u2029"):
            self.assertNotIn(sequence, text)

    def test_value_is_unchanged_for_javascript(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js не установлен")
        expression = _script_safe({"farm": self.HOSTILE})
        script = f"process.stdout.write(JSON.stringify({expression}))"
        result = subprocess.run([node, "-e", script], capture_output=True, check=True, timeout=30)  # nosec B603
        self.assertEqual(json.loads(result.stdout.decode("utf-8")), {"farm": self.HOSTILE})


if __name__ == "__main__":
    unittest.main()
