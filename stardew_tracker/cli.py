"""Command line of the tracker (English by default, Russian on a Russian system)."""

from __future__ import annotations

import argparse
import os
import sys
import time
import webbrowser

from . import consent
from .errors import TrackerError
from .i18n import ENV_VAR, LANGUAGES, L, get_language, set_language
from .report import build_report
from .savefinder import find_saves, standard_folders
from .server import serve
from .state import build_state
from .version import __version__


def configure_stdio() -> None:
    """Do not crash on Cyrillic when stdout is redirected to cp1252/cp866.

    A Windows console program prints UTF-8, but when redirected to a file or a
    pipe Python picks the locale encoding. Encoding errors are replaced with
    ``?`` so diagnostics never turn into a traceback.
    """

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="replace")
        except (ValueError, OSError):
            continue


def info(save: str | None = None, saves_dir: str | None = None) -> None:
    """Diagnostics: what was found and how much progress the parser sees."""

    paths = find_saves(saves_dir=saves_dir, explicit=save)
    print(L(f"Saves found: {len(paths)}", f"Найдено сохранений: {len(paths)}"))
    for path in paths[:10]:
        try:
            stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(path)))
        except OSError:
            stamp = "?"
        print("  ", path, stamp)
    if not paths:
        print(
            "\n"
            + L(
                'Hint: pass the path yourself with --save "path\\to\\save" or put a copy of the save into ./saves',
                'Подсказка: укажите путь вручную через --save "путь\\к\\сейву" или положите копию в папку ./saves',
            )
        )
        return

    state = build_state(save, saves_dir)
    meta, counts = state["meta"], state["counts"]
    ru = get_language() == "ru"
    season = meta["season_ru"] if ru else str(meta["season"]).capitalize()
    print(
        "\n"
        + L(
            f"Farm: {meta['farm']} / {meta['farmer']}   {season} {meta['day']}, year {meta['year']}, {meta['clock']}",
            f"Ферма: {meta['farm']} / {meta['farmer']}   {season} {meta['day']}, год {meta['year']}, {meta['clock']}",
        )
    )
    print(
        L(
            f"Game version in the save: {meta['game_version'] or '?'}",
            f"Версия игры в сейве: {meta['game_version'] or '?'}",
        )
    )
    for key in ("fish", "museum", "museum_found", "shipped", "cooking", "crafting"):
        print(f"  {key:14s} {counts[key][0]:4d} / {counts[key][1]}")
    bundles_done = sum(room["done"] for room in state["bundles"])
    bundles_total = sum(room["total"] for room in state["bundles"])
    monsters = state["monsters"]["completed"]

    def row(en: str, ru_label: str, value: object) -> None:
        print(f"  {ru_label if ru else en:14s} {value}")

    row("villagers", "люди", len(state["people"]))
    row("bundles", "бандлы", f"{bundles_done} / {bundles_total}")
    row("monsters", "монстры", f"{monsters[0]} / {monsters[1]}")
    row("perfection", "перфекция", f"{state['perfection']['pct']}%")
    not_donated = len(state["alerts"]["museum_found_not_donated"])
    print(
        L(
            f"  found for the museum but not donated: {not_donated}",
            f"  найдено в музее, но не сдано: {not_donated}",
        )
    )
    if meta["warnings"]:
        print("\n" + L("Warnings:", "Предупреждения:"))
        for warning in meta["warnings"]:
            print("  ! " + warning)


def _requested_language(argv: list[str] | None) -> str | None:
    """``--lang`` is needed before the real parser is built: its help text depends on it."""

    args = list(sys.argv[1:] if argv is None else argv)
    for index, arg in enumerate(args):
        value: str | None = None
        if arg == "--lang" and index + 1 < len(args):
            value = args[index + 1]
        elif arg.startswith("--lang="):
            value = arg.split("=", 1)[1]
        # An invalid value is ignored here; the full parser reports it with a proper message.
        if value in LANGUAGES:
            return value
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tracker.py",
        description=str(
            L(
                "Local progress tracker for Stardew Valley saves (1.5 / 1.6).",
                "Локальный трекер прогресса сохранений Stardew Valley (1.5 / 1.6).",
            )
        ),
    )
    parser.add_argument(
        "cmd",
        nargs="?",
        default="serve",
        choices=["serve", "build", "info", "open"],
        help=str(L("serve (default), build, info or open", "serve (по умолчанию), build, info или open")),
    )
    parser.add_argument("--save", default=None, help=str(L("save file or save folder", "файл сейва или папка сейва")))
    parser.add_argument(
        "--saves-dir",
        default=None,
        help=str(L("folder that holds all saves", "папка со всеми сохранениями")),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8777,
        help=str(L("port for serve (default 8777)", "порт для serve (по умолчанию 8777)")),
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help=str(
            L(
                "address for serve; 0.0.0.0 opens access from the local network",
                "адрес для serve; 0.0.0.0 открывает доступ из локальной сети",
            )
        ),
    )
    parser.add_argument(
        "--out",
        default=None,
        help=str(L("path of the standalone report.html", "путь для автономного report.html")),
    )
    parser.add_argument(
        "--no-open", action="store_true", help=str(L("do not open the browser", "не открывать браузер"))
    )
    parser.add_argument(
        "--no-watch",
        action="store_true",
        help=str(L("do not watch the save for changes", "не следить за изменениями сейва")),
    )
    parser.add_argument(
        "--lang",
        choices=LANGUAGES,
        default=None,
        help=str(
            L(
                f"language of console messages (default: system language, or the {ENV_VAR} variable)",
                f"язык сообщений консоли (по умолчанию язык системы или переменная {ENV_VAR})",
            )
        ),
    )
    parser.add_argument(
        "--allow-scan",
        action="store_true",
        help=str(
            L(
                "allow the tracker to look for saves in the standard Stardew Valley folders and remember that",
                "разрешить трекеру искать сохранения в стандартных папках Stardew Valley и запомнить выбор",
            )
        ),
    )
    parser.add_argument("--version", action="version", version=f"Stardew Tracker {__version__}")
    return parser


def _interactive() -> bool:
    return bool(sys.stdin and sys.stdin.isatty() and sys.stdout and sys.stdout.isatty())


def _ask_permission(folders: list[str]) -> bool:
    """Console version of the page's permission question."""

    print(
        L(
            "Stardew Tracker can look for your saves in these folders:",
            "Stardew Tracker может искать сохранения в этих папках:",
        )
    )
    for folder in folders:
        print("  " + folder)
    print(
        L(
            "It only opens save files (XML) to read them; nothing is sent anywhere.",
            "Он только открывает файлы сохранений (XML), чтобы их прочитать; ничего никуда не отправляется.",
        )
    )
    answer = input(str(L("Allow this and remember my choice? [y/N] ", "Разрешить и запомнить выбор? [y/N] ")))
    return answer.strip().lower() in {"y", "yes", "д", "да"}


def ensure_consent(args: argparse.Namespace) -> None:
    """Looking into the standard folders needs the user's yes; pointing at a path does not."""

    if args.allow_scan:
        consent.allow_standard(True)
        return
    if args.save or args.saves_dir or consent.standard_allowed():
        return
    # ``serve`` asks in the browser; the one-off commands can ask right here.
    if args.cmd in ("info", "build", "open") and _interactive() and _ask_permission(standard_folders()):
        consent.allow_standard(True)


def main(argv: list[str] | None = None) -> int:
    set_language(_requested_language(argv))
    args = build_parser().parse_args(argv)
    ensure_consent(args)

    if args.cmd == "info":
        info(args.save, args.saves_dir)
        return 0
    if args.cmd == "build":
        state, path = build_report(args.save, args.saves_dir, args.out)
        counts = state["counts"]
        print(L(f"Done: {path}", f"Готово: {path}"))
        print(
            L(
                f"  museum {counts['museum'][0]}/{counts['museum'][1]}, "
                f"fish {counts['fish'][0]}/{counts['fish'][1]}, "
                f"perfection {state['perfection']['pct']}%",
                f"  музей {counts['museum'][0]}/{counts['museum'][1]}, "
                f"рыба {counts['fish'][0]}/{counts['fish'][1]}, "
                f"перфекция {state['perfection']['pct']}%",
            )
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
    """Entry point: a human-readable message instead of a traceback."""

    configure_stdio()
    try:
        code = main()
    except TrackerError as exc:
        # The message with steps is already built - no stack trace.
        print(exc, file=sys.stderr)
        raise SystemExit(1) from exc
    except KeyboardInterrupt:
        print("\n" + L("Stopped.", "Остановлено."))
        raise SystemExit(130) from None
    except Exception as exc:
        print(L("Unexpected error: ", "Непредвиденная ошибка: ") + f"{type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    raise SystemExit(code)
