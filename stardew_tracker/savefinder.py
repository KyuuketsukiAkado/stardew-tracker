"""Поиск файлов сохранений Stardew Valley в стандартных папках."""

from __future__ import annotations

import os

from .constants import SEASON_RU  # noqa: F401  (реэкспорт для совместимости)
from .errors import SaveError
from .paths import FROZEN, SAVES_DIR

_SKIP_NAMES = frozenset({"SaveGameInfo", "startup_preferences"})
_SKIP_SUFFIXES = ("_old", "_old.bak", ".bak", ".tmp")

_NO_SAVE_STEPS = [
    'Укажите путь вручную: python tracker.py serve --save "путь\\к\\сейву"',
    "В Windows сейвы обычно лежат в %APPDATA%\\StardewValley\\Saves\\<Ферма>_<id>\\<Ферма>_<id>",
    "Для демо-проверки можно создать тестовый сейв: python tests/make_test_save.py saves",
]
_NO_SAVE_STEPS_APP = [
    'Укажите путь вручную: StardewTracker serve --save "путь\\к\\сейву"',
    "В Windows сейвы обычно лежат в %APPDATA%\\StardewValley\\Saves\\<Ферма>_<id>\\<Ферма>_<id>",
    "Запустите StardewTracker info, чтобы проверить автопоиск сохранений.",
]


def candidate_save_dirs() -> list[str]:
    """Стандартные расположения сейвов в Windows, Linux (включая Proton) и macOS."""

    home = os.path.expanduser("~")
    appdata = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
    return [
        os.path.join(appdata, "StardewValley", "Saves"),
        os.path.join(home, ".config", "StardewValley", "Saves"),
        os.path.join(home, "Library", "Application Support", "StardewValley", "Saves"),
        os.path.join(
            home,
            ".local",
            "share",
            "Steam",
            "steamapps",
            "compatdata",
            "413150",
            "pfx",
            "drive_c",
            "users",
            "steamuser",
            "AppData",
            "Roaming",
            "StardewValley",
            "Saves",
        ),
    ]


def safe_mtime(path: str) -> float:
    """mtime, устойчивый к удалению файла во время сканирования."""

    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def looks_like_save(path: str) -> bool:
    """Сейв — XML-файл без расширения, лежащий рядом с ``SaveGameInfo``."""

    base = os.path.basename(path)
    if not os.path.isfile(path):
        return False
    if base in _SKIP_NAMES or base.endswith(_SKIP_SUFFIXES):
        return False
    try:
        if os.path.getsize(path) < 200:
            return False
        with open(path, "rb") as handle:
            head = handle.read(400).decode("utf-8", "ignore")
        return "<SaveGame" in head
    except OSError:
        return False


def _listdir(path: str) -> list[str]:
    try:
        return os.listdir(path)
    except PermissionError as exc:
        raise SaveError(
            "permission_denied",
            "Нет прав на чтение папки сохранений",
            f"Операционная система запретила доступ к папке: {path}",
            ["Проверьте права доступа к папке или скопируйте сейвы в доступную директорию."],
        ) from exc
    except OSError as exc:
        raise SaveError(
            "io_error",
            "Не удалось прочитать папку сохранений",
            f"{path}: {exc}",
            ["Проверьте доступность диска и правильность пути."],
        ) from exc


def _scan_dir(directory: str, strict: bool = True) -> list[str]:
    """Файлы сейвов в самой папке и в её непосредственных подпапках.

    ``strict=False`` используется для автопоиска: недоступная стандартная
    папка не должна срывать запуск, если сейв лежит в другой.
    """

    found: list[str] = []
    try:
        entries = _listdir(directory)
    except SaveError:
        if strict:
            raise
        return []
    for name in entries:
        sub = os.path.join(directory, name)
        if not os.path.isdir(sub):
            continue
        try:
            sub_entries = os.listdir(sub)
        except OSError:
            continue
        for filename in sub_entries:
            candidate = os.path.join(sub, filename)
            if looks_like_save(candidate):
                found.append(candidate)
    for name in entries:
        candidate = os.path.join(directory, name)
        if looks_like_save(candidate):
            found.append(candidate)
    return found


def find_saves(saves_dir: str | None = None, explicit: str | None = None) -> list[str]:
    """Возвращает найденные сейвы, свежие первыми.

    ``explicit`` может указывать на файл сейва, папку конкретного сейва или
    общую папку ``Saves``. Ошибки доступа и отсутствие пути поднимаются как
    :class:`SaveError` с шагами решения.
    """

    if explicit:
        if os.path.isdir(explicit):
            found = _scan_dir(explicit)
            if found:
                return sorted(set(found), key=safe_mtime, reverse=True)
            saves_dir = explicit
        elif os.path.exists(explicit):
            return [explicit]
        else:
            raise SaveError(
                "no_saves",
                f"Путь не найден: {explicit}",
                "Указанный файл или папка сохранения не существует.",
                [
                    "Проверьте правильность пути в аргументе --save.",
                    "В Windows сохранения обычно лежат в %APPDATA%\\StardewValley\\Saves\\<Ферма>_<ID>\\<Ферма>_<ID>.",
                    "Запустите `python tracker.py info`, чтобы проверить автопоиск.",
                ],
            )

    directories = [saves_dir] if saves_dir else [*candidate_save_dirs(), SAVES_DIR]

    seen_dirs: set[str] = set()
    results: list[str] = []
    for directory in directories:
        if not directory or not os.path.isdir(directory):
            continue
        marker = os.path.realpath(directory)
        if marker in seen_dirs:
            continue
        seen_dirs.add(marker)
        results.extend(_scan_dir(directory, strict=False))
    return sorted(set(results), key=safe_mtime, reverse=True)


def no_saves_error() -> SaveError:
    """Единая ошибка «сейвов не найдено» для CLI и сервера."""

    return SaveError(
        "no_saves",
        "Не нашёл ни одного файла сохранения",
        "В стандартных папках Stardew Valley и папке ./saves сохранения не обнаружены.",
        list(_NO_SAVE_STEPS_APP if FROZEN else _NO_SAVE_STEPS),
    )
