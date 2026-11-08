"""Собирает standalone StardewTracker через PyInstaller.

Использование (из любой папки):
    python packaging/build_app.py

Нужен PyInstaller: ``python -m pip install -r requirements-build.txt``.
Результат — ``dist/StardewTracker`` (``.exe`` в Windows).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "packaging" / "stardew-tracker.spec"


def _safe_stdio() -> None:
    """Русский текст не должен ронять сборку в Windows с cp1252."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(errors="replace")
            except (ValueError, OSError):
                pass


def main() -> int:
    _safe_stdio()
    try:
        import PyInstaller  # noqa: F401
    except ModuleNotFoundError:
        print(
            "PyInstaller не установлен. Выполните:\n  python -m pip install -r requirements-build.txt",
            file=sys.stderr,
        )
        return 1

    for stale in (ROOT / "build", ROOT / "dist"):
        shutil.rmtree(stale, ignore_errors=True)

    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(SPEC)]
    print("$ " + " ".join(command))
    code = subprocess.call(command, cwd=ROOT)
    if code == 0:
        suffix = ".exe" if sys.platform == "win32" else ""
        print(f"\nГотово: {ROOT / 'dist' / ('StardewTracker' + suffix)}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
