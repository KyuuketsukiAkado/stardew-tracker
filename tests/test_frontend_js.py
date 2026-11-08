"""Синтаксическая проверка встроенного JavaScript шаблона.

Node.js не является зависимостью проекта: если его нет, тест пропускается.
В CI он установлен, поэтому релизный шаблон проверяется автоматически.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(ROOT, "assets", "dashboard.html")
NODE = shutil.which("node")

_SCRIPT_RE = re.compile(r"<script\b[^>]*>(.*?)</script>", re.DOTALL)


def script_blocks(html: str) -> list[str]:
    return [match.group(1) for match in _SCRIPT_RE.finditer(html)]


@unittest.skipUnless(NODE, "Node.js не установлен — синтаксис JS не проверить")
class TestFrontendJavaScript(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(TEMPLATE, encoding="utf-8") as handle:
            cls.html = handle.read()
        cls.scripts = script_blocks(cls.html)

    def test_template_has_expected_scripts(self):
        self.assertEqual(len(self.scripts), 2)
        self.assertIn("window.__STATE__", self.scripts[0])
        self.assertIn("window.__MODE__", self.scripts[0])
        self.assertIn("function render()", self.scripts[1])

    def test_every_script_parses(self):
        tmp = tempfile.mkdtemp(prefix="sdv-js-")
        try:
            for index, script in enumerate(self.scripts):
                path = os.path.join(tmp, f"script-{index}.js")
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(script)
                result = subprocess.run(
                    [NODE, "--check", path],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(
                    result.returncode,
                    0,
                    f"script #{index}: {result.stderr}",
                )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_no_inline_event_handlers(self):
        """CSP шаблона запрещает inline-обработчики; их не должно быть."""

        self.assertNotRegex(self.html, r"\son(?:click|change|input|submit|load)\s*=")

    def test_template_has_no_external_network_dependencies(self):
        """Автономный отчёт не должен тянуть CDN/шрифты/картинки извне."""

        external = re.findall(r"""(?:src|href)=["'](https?://[^"']+)""", self.html)
        self.assertEqual(external, [])
        self.assertNotIn("@import", self.html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
