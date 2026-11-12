"""Раздел «Сегодня»: что стоит сделать в текущий игровой день."""

from __future__ import annotations

from typing import Any


def _brief(row: dict[str, Any]) -> dict[str, Any]:
    return {"id": row.get("id"), "ru": row["ru"], "en": row["en"], "sp": row.get("sp")}


def pick_next_action(
    birthdays_today: list[dict[str, Any]],
    need_museum: list[dict[str, Any]],
    fish_now: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Одно дело для первого экрана — только то, что точно можно сделать сегодня.

    Порядок: день рождения (бывает раз в год и ещё без подарка), находки для
    музея (предметы уже найдены), рыба, которая клюёт сейчас в открытом месте.
    Бандлы сюда не попадают: «осталось 2» не значит, что предметы есть у игрока.
    ``None`` — честное «подходящих дел нет», без выдуманной рекомендации.
    """

    for person in birthdays_today:
        if not person.get("gifts_today"):
            return {
                "kind": "birthday",
                "route": "people",
                "key": person.get("key"),
                "ru": person["ru"],
                "en": person["en"],
                "p_idx": person.get("p_idx"),
                "loved": [_brief(item) for item in (person.get("loved") or [])[:3]],
            }
    if need_museum:
        return {
            "kind": "museum",
            "route": "museum",
            "count": len(need_museum),
            "items": [_brief(row) for row in need_museum[:3]],
        }
    # Ловушки не «клюют сейчас»; места с условием «неизвестно» не советуем.
    catchable = [row for row in fish_now if row.get("lock") == "open" and not row.get("trap") and row.get("open_locs")]
    if catchable:
        fish = catchable[0]
        return {
            "kind": "fish",
            "route": "fish",
            "count": len(catchable),
            **_brief(fish),
            "locs": fish["open_locs"][:2],
            "time": fish.get("time") or "",
        }
    return None


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

    birthdays_today = [person for person in upcoming if person["until"] == 0]
    # «Легендарные II» клюют только во время задания Ки — не советуем их.
    fish_now = [row for row in fish_rows if not row["done"] and row["now"] and not row.get("extended")]

    state = {
        "next_action": pick_next_action(birthdays_today, need_museum, fish_now),
        "birthdays_today": birthdays_today,
        "birthdays_soon": [person for person in upcoming if person["until"] and person["until"] > 0],
        "donate_museum": need_museum,
        "fish_now": fish_now,
        "fish_later": [row for row in fish_rows if not row["done"] and row["later_today"] and not row.get("extended")],
        "bundles_close": close_bundles,
        "ready_cook": [row for row in cook_rows if row["known"] and not row["done"]][:16],
        "ready_craft": [row for row in craft_rows if row["known"] and not row["done"]][:16],
        "ship_season": [row for row in ship_rows if not row["done"] and row["in_season"]][:18],
    }
    return state, need_museum, upcoming
