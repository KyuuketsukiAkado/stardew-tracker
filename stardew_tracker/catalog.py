"""Построение строк коллекций из справочника ``items.json``."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def item_info(items: Mapping[str, dict[str, Any]], uid: Any) -> dict[str, Any]:
    """Краткая карточка предмета для подарков NPC."""

    info = items.get(str(uid), {})
    return {
        "id": str(uid),
        "ru": info.get("ru") or info.get("en") or f"#{uid}",
        "en": info.get("en") or info.get("ru") or f"#{uid}",
        "sp": info.get("sp"),
        "grp": info.get("grp", "other"),
        "seasons": info.get("seasons") or [],
        "price": info.get("p", 0),
    }


def item_row(
    items: Mapping[str, dict[str, Any]],
    uid: Any,
    done: bool,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Строка коллекции: локализованное имя, спрайт, цена и статус."""

    info = items.get(str(uid), {})
    row: dict[str, Any] = {
        "id": str(uid),
        "ru": info.get("ru") or info.get("en") or f"#{uid}",
        "en": info.get("en") or info.get("ru") or f"#{uid}",
        "type": info.get("t", ""),
        "grp": info.get("grp", "other"),
        "price": info.get("p", 0),
        "sp": info.get("sp"),
        "seasons": info.get("seasons") or [],
        "done": bool(done),
    }
    if extra:
        row.update(extra)
    return row
