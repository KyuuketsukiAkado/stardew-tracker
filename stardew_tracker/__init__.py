"""Stardew Valley Progress Tracker.

Пакет разбит по ответственности:

* :mod:`stardew_tracker.savefinder` — поиск сейвов;
* :mod:`stardew_tracker.saveparser` — разбор XML;
* :mod:`stardew_tracker.state` — сборка состояния дашборда;
* :mod:`stardew_tracker.rows` — строки разделов (рыба, музей, рецепты, люди…);
* :mod:`stardew_tracker.unlocks` — обязательные условия получения;
* :mod:`stardew_tracker.report` — HTML-страница и автономный отчёт (функция
  ``render`` экспортируется отсюда, но модуль называется иначе, чтобы она не
  заслоняла его);
* :mod:`stardew_tracker.server` — локальный HTTP API;
* :mod:`stardew_tracker.cli` — командная строка.

Публичный API остаётся доступен и через тонкую обёртку ``tracker.py``.
"""

from __future__ import annotations

from .catalog import item_info, item_row
from .constants import OBELISKS, SEASON_RU, SEASONS, SPRITE_FILES, STARDROPS
from .errors import DataError, SaveError, TrackerError
from .gamedata import clear_cache as clear_data_cache
from .gamedata import load_json
from .goals import default_goals, load_goals, normalize_goals, save_goals
from .report import build_report, render
from .savefinder import candidate_save_dirs, find_saves, looks_like_save, safe_mtime
from .saveparser import clear_cache as clear_parse_cache
from .saveparser import parse_save
from .server import TrackerApp, TrackerHTTPServer, make_handler, serve
from .state import build_state, clear_state_cache, list_saves_info
from .timeutil import abs_day, days_until_birthday, fmt_clock, game_clock, time_matches
from .version import __version__
from .xmlutil import norm_id

__all__ = [
    "OBELISKS",
    "SEASONS",
    "SEASON_RU",
    "SPRITE_FILES",
    "STARDROPS",
    "DataError",
    "SaveError",
    "TrackerApp",
    "TrackerError",
    "TrackerHTTPServer",
    "__version__",
    "abs_day",
    "build_report",
    "build_state",
    "candidate_save_dirs",
    "clear_data_cache",
    "clear_parse_cache",
    "clear_state_cache",
    "days_until_birthday",
    "default_goals",
    "find_saves",
    "fmt_clock",
    "game_clock",
    "item_info",
    "item_row",
    "list_saves_info",
    "load_goals",
    "load_json",
    "looks_like_save",
    "make_handler",
    "norm_id",
    "normalize_goals",
    "parse_save",
    "render",
    "safe_mtime",
    "save_goals",
    "serve",
    "time_matches",
]
