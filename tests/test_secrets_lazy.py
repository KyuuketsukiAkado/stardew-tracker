"""Решения раздела «Секреты» не едут в каждом ответе; GET не меняет активный сейв.

Интерфейс обещает показывать спойлеры только после явного согласия, а текст
решений (~30 КБ) лежал и в каждом ответе ``/api/state``, и в исходнике каждой
страницы. Теперь живой сервер отдаёт их отдельным запросом ``/api/secrets``;
автономный отчёт без сервера по-прежнему содержит всё внутри.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from make_test_save import write_test_save  # noqa: E402
from test_runtime import _ServerCase  # noqa: E402

from stardew_tracker import build_report, render  # noqa: E402
from stardew_tracker.gamedata import load_json  # noqa: E402
from stardew_tracker.server import client_state  # noqa: E402
from stardew_tracker.state import build_state, secret_sections  # noqa: E402

TEMPLATE = Path(ROOT) / "assets" / "dashboard.html"


def _spoiler_snippet() -> str:
    """Кусок реального текста решения, не требующий экранирования в JSON."""

    for section in load_json("secrets.json")["sections"]:
        for entry in section["entries"]:
            text = (entry.get("sol_ru") or "").strip()[:28]
            if len(text) >= 20 and json.dumps(text, ensure_ascii=False)[1:-1] == text and "<" not in text:
                return text
    raise AssertionError("в data/secrets.json нет подходящего текста решения")


SNIPPET = _spoiler_snippet()


class TestLiveServerKeepsSolutionsOut(_ServerCase):
    def test_state_has_the_lazy_marker_and_no_section_text(self):
        response, body = self.call("GET", "/api/state")
        self.assertEqual(response.status, 200)
        secrets = json.loads(body)["secrets"]
        self.assertNotIn("sections", secrets)
        self.assertIs(secrets["lazy"], True)
        self.assertIn("qi_orders_completed", secrets)  # счётчик не спойлер и остаётся
        self.assertNotIn(SNIPPET, body.decode("utf-8"))

    def test_page_source_has_no_solution_text(self):
        _response, body = self.call("GET", "/")
        page = body.decode("utf-8")
        self.assertIn('window.__MODE__ = "live";', page)
        self.assertNotIn(SNIPPET, page)

    def test_refresh_and_save_switch_responses_have_no_solution_text(self):
        for method, path, payload in (
            ("GET", "/api/refresh", None),
            ("POST", "/api/saves/select", {"path": self.app.state["meta"]["save_path"]}),
        ):
            response, body = self.call(method, path, payload)
            self.assertEqual(response.status, 200, path)
            self.assertNotIn(SNIPPET, body.decode("utf-8"), path)
            self.assertIs(json.loads(body)["secrets"]["lazy"], True, path)

    def test_secrets_endpoint_returns_all_sections(self):
        response, body = self.call("GET", "/api/secrets")
        self.assertEqual(response.status, 200)
        sections = json.loads(body)["sections"]
        self.assertEqual(sections, secret_sections())
        self.assertIn(SNIPPET, body.decode("utf-8"))
        self.assertGreater(len(body), 20_000)

    def test_secrets_endpoint_is_built_once(self):
        self.assertIs(self.app.secrets_json(), self.app.secrets_json())

    def test_secrets_endpoint_respects_the_host_check(self):
        response, body = self.call("GET", "/api/secrets", headers={"Host": "evil.example.com"})
        self.assertEqual(response.status, 403)
        self.assertNotIn(SNIPPET, body.decode("utf-8"))

    def test_state_stays_much_smaller(self):
        light = len(self.call("GET", "/api/state")[1])
        full = len(json.dumps(self.app.state, ensure_ascii=False).encode("utf-8"))
        self.assertLess(light, full - 20_000)

    def test_server_state_in_memory_keeps_the_sections(self):
        # отчёт, CLI и тесты работают с полным состоянием; обрезается только то, что уходит в браузер
        self.assertIn("sections", self.app.state["secrets"])


class TestGetHasNoSideEffects(_ServerCase):
    def test_save_query_does_not_switch_the_active_save(self):
        other = os.path.join(self.tmp, "Вторая_2")
        os.makedirs(other)
        shutil.copy(self.app.save, os.path.join(other, "Вторая_2"))
        shutil.copy(os.path.join(os.path.dirname(self.app.save), "SaveGameInfo"), os.path.join(other, "SaveGameInfo"))
        before, state_before = self.app.save, self.app.state
        target = os.path.join(other, "Вторая_2")
        from urllib.parse import quote

        for path in ("/", "/index.html", "/api/state"):
            response, _body = self.call("GET", f"{path}?save={quote(target)}")
            self.assertEqual(response.status, 200, path)
        self.assertEqual(self.app.save, before)
        self.assertEqual(self.app.state["meta"]["save_path"], state_before["meta"]["save_path"])

    def test_switching_still_works_through_post(self):
        other = os.path.join(self.tmp, "Третья_3")
        os.makedirs(other)
        shutil.copy(self.app.save, os.path.join(other, "Третья_3"))
        shutil.copy(os.path.join(os.path.dirname(self.app.save), "SaveGameInfo"), os.path.join(other, "SaveGameInfo"))
        response, body = self.call("POST", "/api/saves/select", {"path": os.path.join(other, "Третья_3")})
        self.assertEqual(response.status, 200)
        self.assertTrue(json.loads(body)["meta"]["save_path"].endswith("Третья_3"))


class TestStaticReportIsSelfContained(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sdv-secrets-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_report_keeps_the_solutions_inside(self):
        tmp = self.tmp
        save = write_test_save(tmp)
        _state, path = build_report(save, out_path=os.path.join(tmp, "report.html"))
        with open(path, encoding="utf-8") as handle:
            html = handle.read()
        self.assertIn('window.__MODE__ = "static";', html)
        self.assertIn(SNIPPET, html)
        self.assertNotIn('"lazy": true', html)

    def test_render_of_a_full_state_in_static_mode_is_unchanged(self):
        write_test_save(self.tmp)
        self.assertIn(SNIPPET, render(build_state(None, self.tmp), "static"))


class TestClientState(unittest.TestCase):
    def test_removes_sections_adds_marker_and_does_not_mutate_the_input(self):
        state = {"meta": {"x": 1}, "secrets": {"sections": [{"key": "a"}], "qi_orders_completed": ["Q"]}}
        light = client_state(state)
        self.assertEqual(light["secrets"], {"qi_orders_completed": ["Q"], "lazy": True})
        self.assertIs(light["meta"], state["meta"])  # остальное — общее, без копирования
        self.assertIn("sections", state["secrets"])  # вход не тронут

    def test_state_without_sections_is_returned_as_is(self):
        for state in ({"meta": {}}, {"secrets": {"qi_orders_completed": []}}, {"secrets": None}):
            self.assertIs(client_state(state), state)


class TestFrontendLoadsSolutionsLazily(unittest.TestCase):
    html = TEMPLATE.read_text(encoding="utf-8")

    def test_template_asks_the_server_only_through_the_lazy_loader(self):
        self.assertEqual(self.html.count('fetch("/api/secrets"'), 1)
        self.assertIn("async function loadSecrets()", self.html)
        self.assertIn('MODE !== "live"', self.html.split("async function loadSecrets()", 1)[1].split("}", 3)[0])

    def test_solutions_are_forgotten_when_leaving_the_section(self):
        self.assertIn("function forgetSecrets()", self.html)
        # выход кнопкой и уход по навигации сбрасывают кэш решений
        self.assertGreaterEqual(self.html.count("forgetSecrets();"), 2)

    def test_both_languages_have_the_loading_messages(self):
        self.assertEqual(self.html.count("secretsLoading:"), 2)
        self.assertEqual(self.html.count("secretsFailed:"), 2)


if __name__ == "__main__":
    unittest.main()
