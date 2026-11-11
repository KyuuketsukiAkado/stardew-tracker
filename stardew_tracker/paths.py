"""Файловые пути проекта и standalone-приложения.

В исходниках все пути вычисляются от корня репозитория. В сборке PyInstaller
ресурсы (`data/`, `assets/`) читаются из временной папки ``sys._MEIPASS``,
а изменяемые файлы (`goals.json`, `report.html`, пользовательские сейвы) —
из каталога данных ОС, потому что папка бандла доступна только для чтения.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "StardewTracker"


def resource_root(*, frozen: bool, meipass: str | None) -> Path:
    """Корень read-only ресурсов: репозиторий или распакованный бандл."""

    if frozen and meipass:
        return Path(meipass).resolve()
    return Path(__file__).resolve().parent.parent


def user_data_dir(
    *,
    platform: str | None = None,
    env: dict[str, str] | None = None,
    home: str | os.PathLike[str] | None = None,
) -> Path:
    """Каталог изменяемых данных приложения для текущей ОС.

    ``STARDEW_TRACKER_HOME`` переопределяет расположение (удобно для
    портативной установки и тестов).
    """

    environment = os.environ if env is None else env
    override = environment.get("STARDEW_TRACKER_HOME")
    if override:
        return Path(override).expanduser()

    system = sys.platform if platform is None else platform
    home_path = Path.home() if home is None else Path(home)
    if system == "win32":
        base = Path(environment.get("APPDATA") or home_path / "AppData" / "Roaming")
    elif system == "darwin":
        base = home_path / "Library" / "Application Support"
    else:
        base = Path(environment.get("XDG_DATA_HOME") or home_path / ".local" / "share")
    return base / APP_NAME


FROZEN = bool(getattr(sys, "frozen", False))
# How a person starts the program: shown in error messages ("Run `<COMMAND> info`").
COMMAND = "StardewTracker" if FROZEN else "python tracker.py"
PROJECT_ROOT = resource_root(frozen=FROZEN, meipass=getattr(sys, "_MEIPASS", None))
WRITABLE_ROOT = user_data_dir() if FROZEN else PROJECT_ROOT

# Строки, а не Path: остальной код активно использует os.path.
HERE = os.fspath(PROJECT_ROOT)
DATA_DIR = os.path.join(HERE, "data")
SPRITES_DIR = os.path.join(HERE, "assets", "sprites")
ASSETS_DIR = os.path.join(HERE, "assets")
TEMPLATE = os.path.join(ASSETS_DIR, "dashboard.html")
GOALS_FILE = os.fspath(WRITABLE_ROOT / "goals.json")
SETTINGS_FILE = os.fspath(WRITABLE_ROOT / "settings.json")
REPORT = os.fspath(WRITABLE_ROOT / "report.html")
SAVES_DIR = os.fspath(WRITABLE_ROOT / "saves")
