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


# Порядок слагаемых в итоговом проценте. Он сохранён от прежней формулы
# намеренно: ``walnut_room_pct`` берёт ``int(raw_pct)``, а сумма чисел с плавающей
# точкой зависит от порядка (…99999999 против 50.0 на границе целого).
_SUM_ORDER = (
    "obelisks",
    "gold_clock",
    "monsters",
    "stardrops",
    "shipped",
    "friends",
    "cooking",
    "crafting",
    "fish",
    "walnuts",
    "skills",
)


def _category(
    key: str,
    ru: str,
    en: str,
    *,
    have: float | int,
    total: float | int,
    weight: int,
    fraction: float,
    done: bool,
    go: str,
    sp: list[int],
) -> tuple[dict[str, Any], float]:
    """Строка категории и её точный (неокруглённый) вклад в процент.

    Вес записан один раз: и отображаемое ``earned``, и итоговая сумма считаются
    из ``weight * fraction`` — раньше те же веса дублировались в формуле
    процента, и правка одного места тихо расходилась со вторым.
    """

    exact = weight * fraction
    row = {
        "key": key,
        "ru": ru,
        "en": en,
        "have": have,
        "total": total,
        "weight": weight,
        "earned": round(exact, 2),
        "done": done,
        "go": go,
        "sp": sp,
    }
    return row, exact


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
    slayer_hero = bool(monsters_state["slayer_hero"])

    specs = [
        _category(
            "shipped",
            "Отправка урожая и находок",
            "Produce & Forage Shipped",
            have=counts["shipped"][0],
            total=counts["shipped"][1],
            weight=15,
            fraction=_frac(*counts["shipped"]),
            done=counts["shipped"][0] >= counts["shipped"][1],
            go="shipped",
            sp=[0, 24],
        ),
        _category(
            "obelisks",
            "Обелиски на ферме",
            "Obelisks on Farm",
            have=num_obelisks,
            total=4,
            weight=4,
            fraction=_frac(num_obelisks, 4),
            done=num_obelisks >= 4,
            go="perfection",
            sp=[0, 688],
        ),
        _category(
            "gold_clock",
            "Золотые часы на ферме",
            "Golden Clock on Farm",
            have=1 if has_gold_clock else 0,
            total=1,
            weight=10,
            fraction=1.0 if has_gold_clock else 0.0,
            done=has_gold_clock,
            go="perfection",
            sp=[1, 79],
        ),
        _category(
            "monsters",
            "Герой-истребитель чудовищ",
            "Monster Slayer Hero",
            have=counts["monsters"][0],
            total=len(monster_rows),
            weight=10,
            fraction=1.0 if slayer_hero else 0.0,
            done=monsters_state["slayer_hero"],
            go="perfection",
            sp=[0, 526],
        ),
        _category(
            "friends",
            "Великие друзья (макс. ♥)",
            "Great Friends",
            have=great_friends_done,
            total=great_friends_total,
            weight=11,
            fraction=_frac(great_friends_done, great_friends_total),
            done=great_friends_done >= great_friends_total,
            go="people",
            sp=[0, 458],
        ),
        _category(
            "skills",
            "Уровень фермера (все навыки 10)",
            "Farmer Level (Skills)",
            have=farmer_level,
            total=25,
            weight=5,
            fraction=_frac(farmer_level, 25),
            done=farmer_level >= 25,
            go="perfection",
            sp=[1, 96],
        ),
        _category(
            "stardrops",
            "Все звёздные капли",
            "Found All Stardrops",
            have=7 if all_stardrops else sum(1 for row in stardrop_rows if row["done"]),
            total=7,
            weight=10,
            fraction=1.0 if all_stardrops else 0.0,
            done=all_stardrops,
            go="perfection",
            sp=[0, 434],
        ),
        _category(
            "cooking",
            "Приготовленные блюда",
            "Cooking Recipes Made",
            have=counts["cooking"][0],
            total=counts["cooking"][1],
            weight=10,
            fraction=_frac(*counts["cooking"]),
            done=counts["cooking"][0] >= counts["cooking"][1],
            go="cooking",
            sp=[0, 195],
        ),
        _category(
            "crafting",
            "Созданные предметы (крафт)",
            "Crafting Recipes Made",
            have=craft_perf_done,
            total=craft_perf_total,
            weight=10,
            fraction=_frac(craft_perf_done, craft_perf_total),
            done=craft_perf_done >= craft_perf_total,
            go="crafting",
            sp=[2, 13],
        ),
        _category(
            "fish",
            "Пойманная рыба",
            "Fish Caught",
            have=counts["fish"][0],
            total=counts["fish"][1],
            weight=10,
            fraction=_frac(*counts["fish"]),
            done=counts["fish"][0] >= counts["fish"][1],
            go="fish",
            sp=[0, 128],
        ),
        _category(
            "walnuts",
            "Золотые грецкие орехи",
            "Golden Walnuts Found",
            have=walnuts_have,
            total=WALNUTS_TOTAL,
            weight=5,
            fraction=_frac(walnuts_have, WALNUTS_TOTAL),
            done=walnuts_have >= WALNUTS_TOTAL,
            go="perfection",
            sp=[0, 73],
        ),
    ]
    categories = [row for row, _exact in specs]
    exact_by_key = {row["key"]: exact for row, exact in specs}
    # Не ``sum()``: с Python 3.12 он суммирует числа с плавающей точкой с
    # компенсацией ошибки и на границе округления (53,05) даёт другой процент,
    # чем прежнее сложение «слева направо» — и разный на разных версиях Python.
    raw_pct = 0.0
    for key in _SUM_ORDER:
        raw_pct += exact_by_key[key]

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
