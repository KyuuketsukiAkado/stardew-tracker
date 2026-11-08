"""Файловые пути проекта.

Все пути вычисляются от корня репозитория, поэтому трекер работает и из
исходников, и из распакованного архива без установки пакета.
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Строки, а не Path: остальной код активно использует os.path.
HERE = os.fspath(PROJECT_ROOT)
DATA_DIR = os.path.join(HERE, "data")
SPRITES_DIR = os.path.join(HERE, "assets", "sprites")
ASSETS_DIR = os.path.join(HERE, "assets")
TEMPLATE = os.path.join(ASSETS_DIR, "dashboard.html")
GOALS_FILE = os.path.join(HERE, "goals.json")
REPORT = os.path.join(HERE, "report.html")
SAVES_DIR = os.path.join(HERE, "saves")
