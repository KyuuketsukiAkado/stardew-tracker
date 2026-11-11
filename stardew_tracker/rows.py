"""Сборка строк разделов: рыба, музей, отправка, рецепты, люди, бандлы, гильдия."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .catalog import item_info, item_row
from .constants import OBELISKS, SEASONS, SKILLS, STARDROPS
from .timeutil import days_until_birthday, time_matches, weather_matches
from .unlocks import (
    SHIPPING_GATES,
    UnlockContext,
    evaluate,
    fish_alternatives,
    fish_location_groups,
    is_night_market_only,
    museum_alternatives,
    museum_tags,
    recipe_source,
)

NIGHT_MARKET_TIME = "1700 2600"


def _lock_fields(alternatives: list[list[str]], ctx: UnlockContext | None) -> dict[str, Any]:
    """Поля строки про обязательные условия: ``lock`` и ``req``."""

    if ctx is None:
        return {"lock": "open", "req": []}
    state, keys = evaluate(alternatives, ctx)
    return {"lock": state, "req": keys}


def build_fish_rows(
    fish: Mapping[str, dict[str, Any]],
    items: Mapping[str, dict[str, Any]],
    raw: Mapping[str, Any],
    season_now: str,
    current_minutes: int,
    save_weather: str,
    ctx: UnlockContext | None = None,
) -> list[dict[str, Any]]:
    """72 вида рыбы коллекции (+5 «легендарных II») с доступностью сейчас.

    Рыба считается «доступной сейчас», только если открыта локация: смысл
    подсказки — куда пойти ловить сегодня, а не теоретическая возможность.
    """

    rows: list[dict[str, Any]] = []
    day_now = int(raw.get("day") or 1)
    for uid, info in fish.items():
        caught = raw["fishCaught"].get(uid, 0) or 0
        seasons = [season for season in (info.get("season") or "").split() if season in SEASONS]
        time_span = info.get("time") or ""
        weather_required = info.get("weather") or "both"
        night_market = is_night_market_only(info)
        if night_market:
            # Data/Fish.json говорит «круглый год», но субмарина работает
            # только зимой 15–17 числа вечером.
            seasons = ["winter"]
            time_span = NIGHT_MARKET_TIME
        in_season = season_now in seasons or not seasons or "all" in (info.get("season") or "")
        if night_market:
            in_season = season_now == "winter" and 15 <= day_now <= 17
        time_ok, later_today = time_matches(time_span, current_minutes)
        weather_ok = weather_matches(weather_required, save_weather)
        alternatives, _common = fish_alternatives(uid, info)
        lock = _lock_fields(alternatives, ctx)
        reachable = lock["lock"] != "locked"
        now_ok = bool(in_season and time_ok and weather_ok and reachable)
        later_ok = bool(in_season and later_today and weather_ok and reachable)
        rows.append(
            item_row(
                items,
                uid,
                caught > 0,
                {
                    "count": caught,
                    "seasons": seasons,
                    "time": time_span,
                    "weather": weather_required,
                    "diff": info.get("diff"),
                    "size": info.get("size") or [],
                    "beh": info.get("beh", ""),
                    "trap": bool(info.get("trap")),
                    "water": info.get("water", ""),
                    "locs": info.get("loc") or [],
                    "in_season": in_season,
                    "weather_ok": weather_ok,
                    "later_today": later_ok,
                    "now": now_ok,
                    "groups": fish_location_groups(info),
                    "night_market": night_market,
                    "extended": bool(info.get("extended")),
                    "jelly": bool(info.get("jelly")),
                    **lock,
                },
            )
        )
    rows.sort(
        key=lambda row: (
            row["extended"],
            row["done"],
            not row["now"],
            row["lock"] == "locked",
            not row["in_season"],
            row["ru"].lower(),
        )
    )
    return rows


def build_museum_rows(
    museum: Mapping[str, list[str]],
    artifact_locations: Mapping[str, Any],
    items: Mapping[str, dict[str, Any]],
    raw: Mapping[str, Any],
    ctx: UnlockContext | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for uid in museum.get("artifacts", []):
        donated = uid in raw["museum"]
        found = uid in raw["archaeologyFound"]
        locations = artifact_locations.get(uid, {})
        sources_en = list(locations.get("en") or [])
        # Уже найденное не «заблокировано», даже если источник закрыт.
        lock = {"lock": "open", "req": []} if found or donated else _lock_fields(museum_alternatives(sources_en), ctx)
        rows.append(
            item_row(
                items,
                uid,
                donated,
                {
                    "kind": "artifact",
                    "found": found,
                    "donated": donated,
                    "locations": locations,
                    "tags": museum_tags(sources_en, "artifact"),
                    **lock,
                },
            )
        )
    for uid in museum.get("minerals", []):
        donated = uid in raw["museum"]
        rows.append(
            item_row(
                items,
                uid,
                donated,
                {
                    "kind": "mineral",
                    "found": uid in raw["mineralsFound"],
                    "donated": donated,
                    "tags": museum_tags([], "mineral"),
                    "lock": "open",
                    "req": [],
                },
            )
        )
    rows.sort(key=lambda row: (row["donated"], not row["found"], row["ru"].lower()))
    return rows


def build_shipping_rows(
    shipping: list[str],
    items: Mapping[str, dict[str, Any]],
    raw: Mapping[str, Any],
    season_now: str,
    ctx: UnlockContext | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for uid in shipping:
        count = raw["basicShipped"].get(str(uid), 0) or 0
        item_seasons = items.get(str(uid), {}).get("seasons") or []
        lock = {"lock": "open", "req": []} if count else _lock_fields(SHIPPING_GATES.get(str(uid), []), ctx)
        rows.append(
            item_row(
                items,
                uid,
                count > 0,
                {
                    "count": count,
                    "in_season": season_now in item_seasons if item_seasons else False,
                    **lock,
                },
            )
        )
    rows.sort(key=lambda row: (row["done"], not row["in_season"], row["ru"].lower()))
    return rows


def build_cooking_rows(
    recipes: Mapping[str, Mapping[str, dict[str, Any]]],
    items: Mapping[str, dict[str, Any]],
    raw: Mapping[str, Any],
    ctx: UnlockContext | None = None,
    sources: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Три состояния: приготовлено / рецепт изучен / не изучен."""

    rows: list[dict[str, Any]] = []
    for recipe_name, recipe in recipes.get("cooking", {}).items():
        uid = str(recipe.get("item", ""))
        count = raw["recipesCooked"].get(uid, 0) or 0
        known = recipe_name in raw["cookingRecipes"] or recipe.get("unlock") == "default" or count > 0
        unlock = _recipe_unlock(recipe_name, recipe, known, ctx, (sources or {}).get(recipe_name))
        rows.append(
            {
                "id": uid or recipe_name,
                "ru": recipe.get("ru") or recipe_name,
                "en": recipe.get("en") or recipe_name,
                "sp": recipe.get("sp") or items.get(uid, {}).get("sp"),
                "price": recipe.get("price") or items.get(uid, {}).get("p", 0),
                "done": count > 0,
                "known": known,
                "count": count,
                "ing": recipe.get("ing") or [],
                "unlock": unlock["unlock_ru"] or (recipe.get("unlock") or ""),
                **unlock,
            }
        )
    rows.sort(key=lambda row: (row["done"], not row["known"], row["lock"] == "locked", row["ru"].lower()))
    return rows


def _recipe_unlock(
    name: str,
    recipe: Mapping[str, Any],
    known: bool,
    ctx: UnlockContext | None,
    override: Mapping[str, Any] | None,
) -> dict[str, Any]:
    text_ru, text_en, kind, gates = recipe_source(name, recipe, override)
    # Изученный рецепт уже ничем не заблокирован.
    lock = {"lock": "open", "req": []} if known else _lock_fields([gates] if gates else [], ctx)
    return {"unlock_ru": text_ru, "unlock_en": text_en, "src_kind": kind, **lock}


def build_crafting_rows(
    recipes: Mapping[str, Mapping[str, dict[str, Any]]],
    raw: Mapping[str, Any],
    ctx: UnlockContext | None = None,
    sources: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Три состояния крафта и список рецептов, которых нет в сейве."""

    rows: list[dict[str, Any]] = []
    unmatched: list[str] = []
    for recipe_name, recipe in recipes.get("crafting", {}).items():
        alt_name = "Oil of Garlic" if recipe_name == "Oil Of Garlic" else recipe_name
        in_save = recipe_name in raw["craftingRecipes"] or alt_name in raw["craftingRecipes"]
        count = raw["craftingRecipes"].get(recipe_name, raw["craftingRecipes"].get(alt_name, 0))
        if not in_save:
            unmatched.append(recipe_name)
        known = in_save or recipe.get("unlock") == "default" or count > 0
        unlock = _recipe_unlock(recipe_name, recipe, known, ctx, (sources or {}).get(recipe_name))
        rows.append(
            {
                "id": str(recipe.get("item", "")) or recipe_name,
                "ru": recipe.get("name_ru") or recipe.get("ru") or recipe_name,
                "en": recipe.get("name_en") or recipe.get("en") or recipe_name,
                "rec_en": recipe_name,
                "sp": recipe.get("sp"),
                "big": bool(recipe.get("big")),
                "qty": recipe.get("qty", 1),
                "done": count > 0,
                "known": known,
                "count": count,
                "ing": recipe.get("ing") or [],
                **unlock,
            }
        )
    rows.sort(key=lambda row: (row["done"], not row["known"], row["lock"] == "locked", row["ru"].lower()))
    return rows, unmatched


def build_people(
    npcs: Mapping[str, dict[str, Any]],
    items: Mapping[str, dict[str, Any]],
    raw: Mapping[str, Any],
    current_abs_day: int,
) -> list[dict[str, Any]]:
    """34 NPC: сердца, подарки, день рождения и любимые предметы."""

    people: list[dict[str, Any]] = []
    for key, info in npcs.items():
        friendship = raw["friendship"].get(key, {})
        points = friendship.get("points", 0)
        is_married = friendship.get("status") == "Married"
        max_hearts = 14 if is_married else 10
        hearts = min(points // 250, max_hearts)
        is_romance = bool(info.get("romance"))
        perfection_target = 2000 if is_romance else 2500
        birth = info.get("birth") or ["", 1]
        birth_season = str(birth[0] or "").lower()
        birth_day = birth[1] if len(birth) > 1 else 1
        people.append(
            {
                "key": key,
                "p_idx": info.get("p_idx", 0),
                "ru": info.get("ru") or key,
                "en": info.get("en") or key,
                "birth": [birth_season, birth_day],
                "until": days_until_birthday(current_abs_day, birth_season, birth_day),
                "hearts": hearts,
                "max_hearts": max_hearts,
                "perf_hearts": 8 if is_romance else 10,
                "perf_done": points >= perfection_target,
                "points": points,
                "romance": is_romance,
                "status": friendship.get("status", ""),
                "roommate": friendship.get("roommate", False),
                "gifts_week": friendship.get("gifts_week", 0),
                "gifts_today": friendship.get("gifts_today", 0),
                "talked": friendship.get("talked", False),
                "loved": [item_info(items, uid) for uid in info.get("love", [])][:12],
                "liked": [item_info(items, uid) for uid in info.get("like", [])][:10],
                "hated": [item_info(items, uid) for uid in info.get("hate", [])][:8],
                "met": bool(friendship),
            }
        )
    people.sort(key=lambda person: (person["until"] if person["until"] is not None else 999, -person["hearts"]))
    return people


def build_bundles(bundles_config: Mapping[str, Any], raw: Mapping[str, Any]) -> list[dict[str, Any]]:
    rooms: list[dict[str, Any]] = []
    for room in bundles_config.get("rooms", []):
        bundle_list: list[dict[str, Any]] = []
        for bundle in room.get("list", []):
            have_flags = raw["bundles"].get(bundle["slot"]) or []
            done = sum(1 for flag in have_flags if flag)
            need = max(1, int(bundle.get("need_count") or len(bundle["items"])))
            bundle_list.append(
                {
                    "slot": bundle["slot"],
                    "color": bundle.get("color", 0),
                    "ru": bundle.get("name_ru") or bundle["name_en"],
                    "en": bundle["name_en"],
                    "need": need,
                    "have": min(done, need),
                    "complete": done >= need,
                    "items": [
                        {
                            "id": item.get("id", ""),
                            "ru": item["ru"],
                            "en": item["en"],
                            "qty": item["qty"],
                            "qual": item.get("qual", 0),
                            "sp": item.get("sp"),
                            "seasons": item.get("seasons") or [],
                            "have": bool(have_flags[index]) if index < len(have_flags) else False,
                        }
                        for index, item in enumerate(bundle["items"])
                    ],
                    "reward": bundle.get("reward"),
                }
            )
        rooms.append(
            {
                "key": room["key"],
                "ru": room["ru"],
                "en": room["en"],
                "list": bundle_list,
                "done": sum(1 for bundle in bundle_list if bundle["complete"]),
                "total": len(bundle_list),
            }
        )
    return rooms


def build_monsters(
    monster_goals: list[Mapping[str, Any]], raw: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for goal in monster_goals:
        species_counts: list[list[Any]] = []
        killed_sum = 0
        for monster_name in goal["monsters"]:
            count = raw["monsters_killed"].get(monster_name, 0)
            killed_sum += count
            if count > 0:
                species_counts.append([monster_name, count])
        target = int(goal["target"])
        rows.append(
            {
                "idx": goal["idx"],
                "key": goal["key"],
                "ru": goal["ru"],
                "en": goal["en"],
                "killed": killed_sum,
                "target": target,
                "done": killed_sum >= target,
                "where_ru": goal.get("where_ru", ""),
                "where_en": goal.get("where_en", ""),
                "reward": goal.get("reward"),
                "species": species_counts,
            }
        )
    done = sum(1 for row in rows if row["done"])
    state = {
        "goals": rows,
        "completed": [done, len(rows)],
        "slayer_hero": bool(rows) and done >= len(rows),
        "total_killed": raw["total_monsters_killed"],
        "deepest_mine": min(raw["deepest_mine"], 120),
        "skull_cavern": max(0, raw["deepest_mine"] - 120),
    }
    return rows, state


def build_skills(raw: Mapping[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """Уровни пяти навыков и официальный Farmer Level.

    ``Farmer Level`` в игре — это сумма пяти навыков, делённая на два
    (максимум 25). Удача — временный бафф, а не навык, и в формулу не входит.
    """

    rows: list[dict[str, Any]] = []
    for key, name_ru, name_en, ui_index, xp_index in SKILLS:
        level = raw["skills"].get(key, 0)
        xp = raw["xp"][xp_index] if xp_index < len(raw["xp"]) else 0
        rows.append(
            {
                "key": key,
                "ru": name_ru,
                "en": name_en,
                "level": level,
                "xp": xp,
                "ui_idx": ui_index,
            }
        )
    total = sum(row["level"] for row in rows) // 2
    return rows, min(25, max(0, total))


def build_obelisks(raw: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {"key": key, "ru": name_ru, "en": name_en, "done": key in raw["farm_buildings"]}
        for key, name_ru, name_en in OBELISKS
    ]


def build_stardrops(raw: Mapping[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    rows: list[dict[str, Any]] = []
    for key, name_ru, name_en in STARDROPS:
        got = key in raw["mail_received"] or (key == "CF_Mines" and 100 in raw["mine_chests"])
        rows.append({"key": key, "ru": name_ru, "en": name_en, "done": got})
    done = sum(1 for row in rows if row["done"])
    all_stardrops = done >= len(rows) or "gotMaxStamina" in raw["mail_received"]
    return rows, all_stardrops
