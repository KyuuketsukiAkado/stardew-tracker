#!/usr/bin/env python3
"""Сборка демо ``docs/index.html`` из синтетического сейва — детерминированно.

    python tools/build_demo.py            # перезаписать docs/index.html
    python tools/build_demo.py --check    # только проверить, что файл актуален (для CI)

Демо — это автономный отчёт по вымышленной ферме Sunny Acres (данные фейковые;
английские имена: демо открывают англоязычные посетители GitHub Pages). Раньше его
пересобирали руками, и он отставал от ``assets/dashboard.html`` и справочников,
а в файл попадали время сборки и путь вроде ``/tmp/...``. Здесь всё, что
зависит от времени, часового пояса, пути и локальных ``goals.json``, заменено
константами, поэтому одинаковые исходники всегда дают одинаковый файл.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from make_test_save import write_test_save  # noqa: E402

from stardew_tracker import build_state, default_goals, render  # noqa: E402

DEMO_PATH = os.path.join(ROOT, "docs", "index.html")
# Всё, что в настоящем состоянии зависит от окружения, — константы.
DEMO_META = {
    "farm": "Sunny Acres",
    "farmer": "Riley",
    "save_path": "demo/Sunny_Acres_345678901/Sunny_Acres_345678901",
    "save_name": "Sunny_Acres_345678901",
    "save_mtime": 1794355200,
    "mtime_str": "2026-11-11 00:00:00",
    "generated": "2026-11-11 00:00:00",
    "saves_found": 1,
}


def build_demo_html() -> str:
    """HTML демо; не читает ни ``goals.json``, ни часы, ни путь к временной папке."""

    tmp = tempfile.mkdtemp(prefix="sdv-demo-")
    try:
        write_test_save(tmp, save_info=True)
        state = build_state(None, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    state["meta"].update(DEMO_META)
    state["goals"] = default_goals()
    return render(state, "static")


def _normalize(text: str) -> str:
    """LF: в репозитории файлы хранятся с LF, а в рабочей копии Windows — с CRLF."""

    return text.replace("\r\n", "\n")


def is_current(path: str = DEMO_PATH) -> bool:
    try:
        with open(path, encoding="utf-8", newline="") as handle:
            existing = handle.read()
    except OSError:
        return False
    return _normalize(existing) == _normalize(build_demo_html())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the demo docs/index.html")
    parser.add_argument("--check", action="store_true", help="do not write the file, only check that it is up to date")
    parser.add_argument("--out", default=DEMO_PATH, help="where to write (default: docs/index.html)")
    args = parser.parse_args(argv)

    if args.check:
        if is_current(args.out):
            print(f"OK: {os.path.relpath(args.out, ROOT)} is up to date")
            return 0
        print(
            f"STALE: {os.path.relpath(args.out, ROOT)} does not match assets/dashboard.html and data/.\n"
            "Run `python tools/build_demo.py` and commit the result.",
            file=sys.stderr,
        )
        return 1

    html = build_demo_html()
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(html)
    print(f"Done: {os.path.relpath(args.out, ROOT)} ({len(html) // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
