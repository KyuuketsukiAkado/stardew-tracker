"""Поиск файлов сохранений Stardew Valley в стандартных папках."""

from __future__ import annotations

import os
import sys

from . import consent
from .constants import SEASON_RU  # noqa: F401  (реэкспорт для совместимости)
from .errors import SaveError
from .i18n import L
from .paths import COMMAND, SAVES_DIR

_SKIP_NAMES = frozenset({"SaveGameInfo", "startup_preferences"})
_SKIP_SUFFIXES = ("_old", "_old.bak", ".bak", ".tmp")

_SAVE_LOCATION_EN = r"On Windows saves usually live in %APPDATA%\StardewValley\Saves\<Farm>_<id>\<Farm>_<id>"
_SAVE_LOCATION_RU = r"В Windows сейвы обычно лежат в %APPDATA%\StardewValley\Saves\<Ферма>_<id>\<Ферма>_<id>"


def _no_save_steps() -> list[str]:
    """Steps shown when no save is found (built per call so they follow the language)."""

    return [
        L(
            f'Give the path yourself: {COMMAND} serve --save "path\\to\\save"',
            f'Укажите путь вручную: {COMMAND} serve --save "путь\\к\\сейву"',
        ),
        L(_SAVE_LOCATION_EN, _SAVE_LOCATION_RU),
        L(
            f"Run `{COMMAND} info` to check the automatic save search.",
            f"Запустите `{COMMAND} info`, чтобы проверить автопоиск сохранений.",
        ),
    ]


def candidate_save_dirs(platform: str | None = None) -> list[str]:
    """Standard save folders of the current system (Windows, macOS, or Linux incl. Proton)."""

    system = sys.platform if platform is None else platform
    home = os.path.expanduser("~")
    if system == "win32":
        appdata = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
        return [os.path.join(appdata, "StardewValley", "Saves")]
    if system == "darwin":
        return [os.path.join(home, "Library", "Application Support", "StardewValley", "Saves")]
    return [
        os.path.join(home, ".config", "StardewValley", "Saves"),
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


def standard_folders() -> list[str]:
    """Where the tracker looks on its own once the user has allowed it (no disk access here)."""

    return [*candidate_save_dirs(), SAVES_DIR]


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
            L("No permission to read the saves folder", "Нет прав на чтение папки сохранений"),
            L(
                f"The operating system denied access to the folder: {path}",
                f"Операционная система запретила доступ к папке: {path}",
            ),
            [
                L(
                    "Check the folder permissions or copy the saves to a folder you can read.",
                    "Проверьте права доступа к папке или скопируйте сейвы в доступную директорию.",
                )
            ],
        ) from exc
    except OSError as exc:
        raise SaveError(
            "io_error",
            L("Could not read the saves folder", "Не удалось прочитать папку сохранений"),
            f"{path}: {exc}",
            [
                L(
                    "Check that the drive is available and the path is correct.",
                    "Проверьте доступность диска и правильность пути.",
                )
            ],
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
                L(f"Path not found: {explicit}", f"Путь не найден: {explicit}"),
                L(
                    "The save file or folder you specified does not exist.",
                    "Указанный файл или папка сохранения не существует.",
                ),
                [
                    L("Check the path you passed to --save.", "Проверьте правильность пути в аргументе --save."),
                    L(_SAVE_LOCATION_EN + ".", _SAVE_LOCATION_RU + "."),
                    L(
                        f"Run `{COMMAND} info` to check the automatic save search.",
                        f"Запустите `{COMMAND} info`, чтобы проверить автопоиск.",
                    ),
                ],
            )

    # A folder the caller names is the user's own choice; the standard folders need permission.
    directories = [saves_dir] if saves_dir else consent.folders_to_scan(standard_folders())

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
        L("No save file found", "Не нашёл ни одного файла сохранения"),
        L(
            "No saves were found in the standard Stardew Valley folders or in ./saves.",
            "В стандартных папках Stardew Valley и папке ./saves сохранения не обнаружены.",
        ),
        _no_save_steps(),
    )
