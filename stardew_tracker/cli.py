"""Командная строка трекера."""

from __future__ import annotations

import argparse
import os
import sys
import time
import webbrowser

from .errors import SaveError
from .render import build_report
from .savefinder import find_saves
from .server import serve
from .state import build_state
from .version import __version__


def info(save: str | None = None, saves_dir: str | None = None) -> None:
    """Диагностика: что найдено и сколько прогресса видит парсер."""

    paths = find_saves(saves_dir=saves_dir, explicit=save)
    print(f"Найдено сохранений: {len(paths)}")
    for path in paths[:10]:
        try:
            stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(path)))
        except OSError:
            stamp = "?"
        print("  ", path, stamp)
    if not paths:
        print(
            '\nПодсказка: укажите путь вручную через --save "путь\\к\\сейву" или положите копию сейва в папку ./saves'
        )
        return

    state = build_state(save, saves_dir)
    meta, counts = state["meta"], state["counts"]
    print(
        f"\nФерма: {meta['farm']} / {meta['farmer']}   "
        f"{meta['season_ru']} {meta['day']}, год {meta['year']}, {meta['clock']}"
    )
    print(f"Версия игры в сейве: {meta['game_version'] or '?'}")
    for key in ("fish", "museum", "museum_found", "shipped", "cooking", "crafting"):
        print(f"  {key:14s} {counts[key][0]:4d} / {counts[key][1]}")
    print(f"  люди            {len(state['people'])}")
    print(
        f"  бандлы          {sum(room['done'] for room in state['bundles'])} / "
        f"{sum(room['total'] for room in state['bundles'])}"
    )
    print(f"  монстры         {state['monsters']['completed'][0]} / {state['monsters']['completed'][1]}")
    print(f"  перфекция       {state['perfection']['pct']}%")
    print(f"  найдено в музее, но не сдано: {len(state['alerts']['museum_found_not_donated'])}")
    if meta["warnings"]:
        print("\nПредупреждения:")
        for warning in meta["warnings"]:
            print("  ! " + warning)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tracker.py",
        description="Stardew Valley progress tracker",
    )
    parser.add_argument(
        "cmd",
        nargs="?",
        default="serve",
        choices=["serve", "build", "info", "open"],
        help="serve (по умолчанию), build, info или open",
    )
    parser.add_argument("--save", default=None, help="файл сейва или папка сейва")
    parser.add_argument("--saves-dir", default=None, help="папка со всеми сохранениями")
    parser.add_argument("--port", type=int, default=8777, help="порт для serve (по умолчанию 8777)")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="адрес для serve; 0.0.0.0 открывает доступ из локальной сети",
    )
    parser.add_argument("--out", default=None, help="путь для автономного report.html")
    parser.add_argument("--no-open", action="store_true", help="не открывать браузер")
    parser.add_argument("--no-watch", action="store_true", help="не следить за изменениями сейва")
    parser.add_argument("--version", action="version", version=f"Stardew Tracker {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.cmd == "info":
        info(args.save, args.saves_dir)
        return 0
    if args.cmd == "build":
        state, path = build_report(args.save, args.saves_dir, args.out)
        print(f"Готово: {path}")
        print(
            f"  музей {state['counts']['museum'][0]}/{state['counts']['museum'][1]}, "
            f"рыба {state['counts']['fish'][0]}/{state['counts']['fish'][1]}, "
            f"перфекция {state['perfection']['pct']}%"
        )
        return 0
    if args.cmd == "open":
        _state, path = build_report(args.save, args.saves_dir, args.out)
        webbrowser.open("file://" + os.path.abspath(path))
        return 0

    serve(
        port=args.port,
        save=args.save,
        saves_dir=args.saves_dir,
        open_browser=not args.no_open,
        watch=not args.no_watch,
        host=args.host,
    )
    return 0


def run() -> None:
    """Точка входа с человеческим сообщением вместо трассировки."""

    try:
        raise SystemExit(main())
    except SaveError:
        # SaveError — это SystemExit, и его сообщение уже сформировано.
        raise
    except KeyboardInterrupt:
        print("\nОстановлено.")
        raise SystemExit(130) from None
    except Exception as exc:
        print(f"Непредвиденная ошибка: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
