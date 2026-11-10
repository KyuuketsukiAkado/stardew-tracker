"""Загрузка двуязычных справочников из ``data/*.json`` с кэшем."""

from __future__ import annotations

import json
import os
import threading
from typing import Any

from .errors import DataError
from .paths import DATA_DIR

# Справочники неизменны на протяжении жизни процесса, поэтому кэшируются.
STATIC_DATA_FILES: frozenset[str] = frozenset(
    {
        "items.json",
        "big_craftables.json",
        "fish.json",
        "museum.json",
        "artifact_locations.json",
        "recipes.json",
        "npcs.json",
        "bundles.json",
        "shipping.json",
        "monsters.json",
        "misc.json",
    }
)

_CACHE: dict[str, Any] = {}
_LOCK = threading.RLock()


def load_json(name: str, data_dir: str | None = None) -> Any:
    """Читает ``data/<name>``; отсутствующий файл даёт пустой словарь.

    Повреждённый JSON — это ошибка упаковки, поэтому поднимается
    :class:`DataError` с понятным текстом, а не голый ``JSONDecodeError``.
    Результат кэшируется по абсолютному пути.
    """

    path = os.path.join(data_dir or DATA_DIR, name)
    cache_key = os.path.abspath(path)
    with _LOCK:
        if cache_key in _CACHE:
            return _CACHE[cache_key]

    if not os.path.exists(path):
        return {}

    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        raise DataError(
            f"Не удалось прочитать справочник {name}",
            f"Файл {path} отсутствует, повреждён или недоступен: {exc}",
        ) from exc

    with _LOCK:
        _CACHE[cache_key] = data
    return data


def clear_cache() -> None:
    """Сбрасывает кэш (используется тестами и пересборкой данных)."""

    with _LOCK:
        _CACHE.clear()
