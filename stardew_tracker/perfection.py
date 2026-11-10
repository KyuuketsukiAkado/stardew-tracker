"""Официальная формула перфекции Stardew Valley 1.6."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .constants import WALNUTS_TOTAL


def _frac(value: float, total: float) -> float:
    return min(1.0, max(0.0, value / total)) if total else 0.0


def compute_counts(
    *,
    fish_rows: list[dict[str, Any]],
    museum_rows: list[dict[str, Any]],
    ship_rows: list[dict[str, Any]],
    cook_rows: list[dict[str, Any]],
    craft_rows: list[dict[str, Any]],
    monster_rows: list[dict[str, Any]],
    people: list[dict[str, Any]],
    raw: Mapping[str, Any],
) -> dict[str, list[float | int]]:
    """Счётчики для шапок разделов, карточек и пользовательских целей."""

    # «Легендарные II» (задание Ки) не входят во вкладку «Рыба» и в перфекцию.
    collection_fish = [row for row in fish_rows if not row.get("extended")]
    counts: dict[str, list[float | int]] = {
        "fish": [sum(1 for row in collection_fish if row["done"]), len(collection_fish)],
        "museum": [sum(1 for row in museum_rows if row["donated"]), len(museum_rows)],
        "museum_found": [
            sum(1 for row in museum_rows if row["found"] or row["donated"]),
            len(museum_rows),
        ],
        "shipped": [sum(1 for row in ship_rows if row["done"]), len(ship_rows)],
        "cooking": [sum(1 for row in cook_rows if row["done"]), len(cook_rows)],
        "crafting": [sum(1 for row in craft_rows if row["done"]), len(craft_rows)],
        "monsters": [sum(1 for row in monster_rows if row["done"]), len(monster_rows)],
    }
    counts["hearts"] = [
        sum(min(person["hearts"], 10) for person in people),
        len(people) * 10,
    ]
    counts["money"] = [raw["money"], 0]
    counts["walnuts"] = [max(0, int(raw["walnuts"] or 0)), WALNUTS_TOTAL]
    return counts


def build_perfection(
    counts: dict[str, list[float | int]],
    *,
    craft_rows: list[dict[str, Any]],
    people: list[dict[str, Any]],
    farmer_level: int,
    monster_rows: list[dict[str, Any]],
    monsters_state: Mapping[str, Any],
    obelisk_rows: list[dict[str, Any]],
    has_gold_clock: bool,
    stardrop_rows: list[dict[str, Any]],
    all_stardrops: bool,
    raw: Mapping[str, Any],
) -> dict[str, Any]:
    """Считает 11 категорий, веса, waivers и итоговый процент."""

    num_obelisks = sum(1 for obelisk in obelisk_rows if obelisk["done"])
    walnuts_have = min(max(0, int(raw["walnuts"] or 0)), WALNUTS_TOTAL)

    # В одиночной игре Wedding Ring не требуется для перфекции (149 вместо 150).
    is_multiplayer = raw["player_count"] > 1
    craft_perf_rows = craft_rows if is_multiplayer else [row for row in craft_rows if row["rec_en"] != "Wedding Ring"]
    craft_perf_done = sum(1 for row in craft_perf_rows if row["done"])
    craft_perf_total = max(1, len(craft_perf_rows))
    great_friends_done = sum(1 for person in people if person["perf_done"])
    great_friends_total = max(1, len(people))

    categories: list[dict[str, Any]] = [
        {
            "key": "shipped",
            "ru": "Отправка урожая и находок",
            "en": "Produce & Forage Shipped",
            "have": counts["shipped"][0],
            "total": counts["shipped"][1],
            "weight": 15,
            "earned": round(15.0 * _frac(*counts["shipped"]), 2),
            "done": counts["shipped"][0] >= counts["shipped"][1],
            "go": "shipped",
            "sp": [0, 24],
        },
        {
            "key": "obelisks",
            "ru": "Обелиски на ферме",
            "en": "Obelisks on Farm",
            "have": num_obelisks,
            "total": 4,
            "weight": 4,
            "earned": float(num_obelisks),
            "done": num_obelisks >= 4,
            "go": "perfection",
            "sp": [0, 688],
        },
        {
            "key": "gold_clock",
            "ru": "Золотые часы на ферме",
            "en": "Golden Clock on Farm",
            "have": 1 if has_gold_clock else 0,
            "total": 1,
            "weight": 10,
            "earned": 10.0 if has_gold_clock else 0.0,
            "done": has_gold_clock,
            "go": "perfection",
            "sp": [1, 79],
        },
        {
            "key": "monsters",
            "ru": "Герой-истребитель чудовищ",
            "en": "Monster Slayer Hero",
            "have": counts["monsters"][0],
            "total": len(monster_rows),
            "weight": 10,
            "earned": 10.0 if monsters_state["slayer_hero"] else 0.0,
            "done": monsters_state["slayer_hero"],
            "go": "perfection",
            "sp": [0, 526],
        },
        {
            "key": "friends",
            "ru": "Великие друзья (макс. ♥)",
            "en": "Great Friends",
            "have": great_friends_done,
            "total": great_friends_total,
            "weight": 11,
            "earned": round(11.0 * _frac(great_friends_done, great_friends_total), 2),
            "done": great_friends_done >= great_friends_total,
            "go": "people",
            "sp": [0, 458],
        },
        {
            "key": "skills",
            "ru": "Уровень фермера (все навыки 10)",
            "en": "Farmer Level (Skills)",
            "have": farmer_level,
            "total": 25,
            "weight": 5,
            "earned": round(5.0 * _frac(farmer_level, 25), 2),
            "done": farmer_level >= 25,
            "go": "perfection",
            "sp": [1, 96],
        },
        {
            "key": "stardrops",
            "ru": "Все звёздные капли",
            "en": "Found All Stardrops",
            "have": 7 if all_stardrops else sum(1 for row in stardrop_rows if row["done"]),
            "total": 7,
            "weight": 10,
            "earned": 10.0 if all_stardrops else 0.0,
            "done": all_stardrops,
            "go": "perfection",
            "sp": [0, 434],
        },
        {
            "key": "cooking",
            "ru": "Приготовленные блюда",
            "en": "Cooking Recipes Made",
            "have": counts["cooking"][0],
            "total": counts["cooking"][1],
            "weight": 10,
            "earned": round(10.0 * _frac(*counts["cooking"]), 2),
            "done": counts["cooking"][0] >= counts["cooking"][1],
            "go": "cooking",
            "sp": [0, 195],
        },
        {
            "key": "crafting",
            "ru": "Созданные предметы (крафт)",
            "en": "Crafting Recipes Made",
            "have": craft_perf_done,
            "total": craft_perf_total,
            "weight": 10,
            "earned": round(10.0 * _frac(craft_perf_done, craft_perf_total), 2),
            "done": craft_perf_done >= craft_perf_total,
            "go": "crafting",
            "sp": [2, 13],
        },
        {
            "key": "fish",
            "ru": "Пойманная рыба",
            "en": "Fish Caught",
            "have": counts["fish"][0],
            "total": counts["fish"][1],
            "weight": 10,
            "earned": round(10.0 * _frac(*counts["fish"]), 2),
            "done": counts["fish"][0] >= counts["fish"][1],
            "go": "fish",
            "sp": [0, 128],
        },
        {
            "key": "walnuts",
            "ru": "Золотые грецкие орехи",
            "en": "Golden Walnuts Found",
            "have": walnuts_have,
            "total": WALNUTS_TOTAL,
            "weight": 5,
            "earned": round(5.0 * _frac(walnuts_have, WALNUTS_TOTAL), 2),
            "done": walnuts_have >= WALNUTS_TOTAL,
            "go": "perfection",
            "sp": [0, 73],
        },
    ]

    raw_pct = (
        num_obelisks
        + (10.0 if has_gold_clock else 0.0)
        + (10.0 if monsters_state["slayer_hero"] else 0.0)
        + (10.0 if all_stardrops else 0.0)
        + 15.0 * _frac(*counts["shipped"])
        + 11.0 * _frac(great_friends_done, great_friends_total)
        + 10.0 * _frac(*counts["cooking"])
        + 10.0 * _frac(craft_perf_done, craft_perf_total)
        + 10.0 * _frac(*counts["fish"])
        + 5.0 * _frac(walnuts_have, WALNUTS_TOTAL)
        + 5.0 * _frac(farmer_level, 25)
    )
    waivers = int(raw["perfection_waivers"] or 0)
    adjusted_pct = min(100.0, raw_pct + waivers)

    state = {
        "pct": round(adjusted_pct, 1),
        "raw_pct": round(raw_pct, 1),
        "walnut_room_pct": int(raw_pct),
        "waivers": waivers,
        "categories": categories,
        "obelisks": obelisk_rows,
        "gold_clock": has_gold_clock,
        "stardrops": stardrop_rows,
    }
    counts["perfection"] = [round(adjusted_pct, 1), 100]
    return state
