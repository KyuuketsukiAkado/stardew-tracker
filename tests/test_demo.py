"""Сборка демо: одинаковые исходники дают одинаковый файл и ничего локального в нём нет."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from stardew_tracker import paths  # noqa: E402

SCRIPT = os.path.join(ROOT, "tools", "build_demo.py")
_spec = importlib.util.spec_from_file_location("build_demo", SCRIPT)
assert _spec is not None and _spec.loader is not None
build_demo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_demo)


class TestDemoContent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = build_demo.build_demo_html()

    def test_it_is_a_static_report_of_the_test_farm(self):
        self.assertIn('window.__MODE__ = "static";', self.html)
        self.assertIn("Тестовая", self.html)
        self.assertGreater(self.html.count("data:image/png;base64,"), 6)

    def test_nothing_local_leaks_into_the_file(self):
        for marker in ("/tmp", "AppData", "\\\\Users\\\\", "/Users/", "sdv-demo-", tempfile.gettempdir()):
            self.assertNotIn(marker, self.html, marker)

    def test_environment_dependent_fields_are_constants(self):
        state_text = self.html.split("window.__STATE__ = ", 1)[1].split(";\n", 1)[0]
        meta = json.loads(state_text)["meta"]
        for key, value in build_demo.DEMO_META.items():
            self.assertEqual(meta[key], value, key)

    def test_two_builds_are_identical(self):
        self.assertEqual(build_demo.build_demo_html(), self.html)


class TestDemoIsIndependentOfTheEnvironment(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sdv-demo-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_local_goals_do_not_change_the_demo(self):
        baseline = build_demo.build_demo_html()
        old = paths.GOALS_FILE
        paths.GOALS_FILE = os.path.join(self.tmp, "goals.json")
        self.addCleanup(setattr, paths, "GOALS_FILE", old)
        with open(paths.GOALS_FILE, "w", encoding="utf-8") as handle:
            json.dump({"goals": [], "tasks": [{"id": "mine", "title": "личная задача"}]}, handle)
        self.assertEqual(build_demo.build_demo_html(), baseline)
        self.assertNotIn("личная задача", baseline)

    def test_time_zone_does_not_change_the_demo(self):
        outputs = []
        for zone in ("UTC", "Pacific/Auckland"):
            target = os.path.join(self.tmp, f"{zone.replace('/', '-')}.html")
            env = {**os.environ, "TZ": zone, "PYTHONIOENCODING": "utf-8"}
            subprocess.run(  # nosec B603 - собственный скрипт репозитория
                [sys.executable, SCRIPT, "--out", target], check=True, env=env, capture_output=True, timeout=120
            )
            with open(target, "rb") as handle:
                outputs.append(handle.read())
        self.assertEqual(outputs[0], outputs[1])


class TestFreshnessCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sdv-demo-check-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.target = os.path.join(self.tmp, "index.html")

    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = build_demo.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_missing_file_is_stale(self):
        code, _out, err = self.run_main("--check", "--out", self.target)
        self.assertEqual(code, 1)
        self.assertIn("tools/build_demo.py", err)

    def test_written_file_is_current(self):
        self.assertEqual(self.run_main("--out", self.target)[0], 0)
        code, out, _err = self.run_main("--check", "--out", self.target)
        self.assertEqual(code, 0)
        self.assertIn("актуален", out)

    def test_changed_file_is_stale(self):
        self.run_main("--out", self.target)
        with open(self.target, "a", encoding="utf-8") as handle:
            handle.write("<!-- правка вручную -->")
        self.assertEqual(self.run_main("--check", "--out", self.target)[0], 1)

    def test_crlf_checkout_is_still_current(self):
        # на Windows git кладёт в рабочую копию CRLF, а в репозитории лежит LF
        self.run_main("--out", self.target)
        with open(self.target, "rb") as handle:
            data = handle.read()
        with open(self.target, "wb") as handle:
            handle.write(data.replace(b"\n", b"\r\n"))
        self.assertEqual(self.run_main("--check", "--out", self.target)[0], 0)


if __name__ == "__main__":
    unittest.main()
