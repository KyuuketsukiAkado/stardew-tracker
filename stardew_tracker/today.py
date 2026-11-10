"""Раздел «Сегодня»: что стоит сделать в текущий игровой день."""

from __future__ import annotations

from typing import Any


def build_today(
    *,
    fish_rows: list[dict[str, Any]],
    museum_rows: list[dict[str, Any]],
    people: list[dict[str, Any]],
    bundle_rooms: list[dict[str, Any]],
    cook_rows: list[dict[str, Any]],
    craft_rows: list[dict[str, Any]],
    ship_rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Возвращает ``(today_state, музей_найдено_но_не_сдано, ближайшие_ДР)``."""

    need_museum = [row for row in museum_rows if row["found"] and not row["donated"]]
    upcoming = [person for person in people if person["until"] is not None and person["until"] <= 7]

    close_bundles: list[dict[str, Any]] = []
    for room in bundle_rooms:
        for bundle in room["list"]:
            remaining = bundle["need"] - bundle["have"]
            if not bundle["complete"] and 1 <= remaining <= 2:
                close_bundles.append(
                    {
                        "room_ru": room["ru"],
                        "room_en": room["en"],
                        "slot": bundle["slot"],
                        "color": bundle["color"],
                        "ru": bundle["ru"],
                        "en": bundle["en"],
                        "have": bundle["have"],
                        "need": bundle["need"],
                        "left": remaining,
                        "missing": [item for item in bundle["items"] if not item["have"]][:6],
                        "reward": bundle["reward"],
                    }
                )
    close_bundles.sort(key=lambda bundle: (bundle["left"], bundle["slot"]))

    state = {
        "birthdays_today": [person for person in upcoming if person["until"] == 0],
        "birthdays_soon": [person for person in upcoming if person["until"] and person["until"] > 0],
        "donate_museum": need_museum,
        "fish_now": [row for row in fish_rows if not row["done"] and row["now"]],
        "fish_later": [row for row in fish_rows if not row["done"] and row["later_today"]],
        "bundles_close": close_bundles,
        "ready_cook": [row for row in cook_rows if row["known"] and not row["done"]][:16],
        "ready_craft": [row for row in craft_rows if row["known"] and not row["done"]][:16],
        "ship_season": [row for row in ship_rows if not row["done"] and row["in_season"]][:18],
    }
    return state, need_museum, upcoming
