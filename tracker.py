#!/usr/bin/env python3
"""Stardew Valley Progress Tracker — совместимая точка входа.

Исторически весь код жил в этом файле. С версии 0.2.0 он разбит на пакет
``stardew_tracker``; здесь остались CLI и реэкспорт публичного API, чтобы
сохранить команды из README, ``run.bat`` и старые скрипты:

    python tracker.py serve           # локальный сервер + автообновление
    python tracker.py build           # автономный report.html
    python tracker.py info            # диагностика сейва
    python tracker.py open            # build + открыть в браузере

Ключи:
    --save ПУТЬ        файл сейва или папка сейва (по умолчанию ищется сам)
    --saves-dir ПУТЬ   папка со всеми сохранениями
    --port 8777        порт для serve
    --host 127.0.0.1   адрес; 0.0.0.0 открывает доступ из локальной сети
    --no-open          не открывать браузер
    --no-watch         отключить фоновое отслеживание изменений сейва
"""

from __future__ import annotations

from stardew_tracker import (
    OBELISKS,
    SEASON_RU,
    SEASONS,
    SPRITE_FILES,
    STARDROPS,
    DataError,
    SaveError,
    TrackerApp,
    TrackerError,
    TrackerHTTPServer,
    __version__,
    abs_day,
    build_report,
    build_state,
    candidate_save_dirs,
    clear_data_cache,
    clear_parse_cache,
    clear_state_cache,
    days_until_birthday,
    default_goals,
    find_saves,
    fmt_clock,
    game_clock,
    item_info,
    item_row,
    list_saves_info,
    load_goals,
    load_json,
    looks_like_save,
    make_handler,
    norm_id,
    normalize_goals,
    parse_save,
    paths,
    render,
    safe_mtime,
    save_goals,
    serve,
    time_matches,
)
from stardew_tracker import goals as goals_module
from stardew_tracker.cli import info, main, run
from stardew_tracker.saveparser import normalize_weather_code
from stardew_tracker.timeutil import weather_matches

# Псевдонимы прежних «приватных» имён — на случай внешних скриптов.
_time_matches = time_matches
_weather_matches = weather_matches

HERE = paths.HERE
DATA_DIR = paths.DATA_DIR
SPRITES_DIR = paths.SPRITES_DIR
ASSETS_DIR = paths.ASSETS_DIR
TEMPLATE = paths.TEMPLATE
REPORT = paths.REPORT
SAVES_DIR = paths.SAVES_DIR

# Только для чтения. Изменение пути к целям выполняйте через
# ``stardew_tracker.goals.save_goals(path=...)`` или ``stardew_tracker.paths``.
GOALS_FILE = paths.GOALS_FILE

__all__ = [
    "ASSETS_DIR",
    "DATA_DIR",
    "GOALS_FILE",
    "HERE",
    "OBELISKS",
    "REPORT",
    "SAVES_DIR",
    "SEASONS",
    "SEASON_RU",
    "SPRITES_DIR",
    "SPRITE_FILES",
    "STARDROPS",
    "TEMPLATE",
    "DataError",
    "SaveError",
    "TrackerApp",
    "TrackerError",
    "TrackerHTTPServer",
    "__version__",
    "_time_matches",
    "_weather_matches",
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
    "goals_module",
    "info",
    "item_info",
    "item_row",
    "list_saves_info",
    "load_goals",
    "load_json",
    "looks_like_save",
    "main",
    "make_handler",
    "norm_id",
    "normalize_goals",
    "normalize_weather_code",
    "parse_save",
    "paths",
    "render",
    "run",
    "safe_mtime",
    "save_goals",
    "serve",
    "time_matches",
    "weather_matches",
]


if __name__ == "__main__":
    run()
