"""Сборка состояния дашборда из сейва и справочников."""

from __future__ import annotations

import copy
import os
import threading
import time
from collections import OrderedDict
from typing import Any, NamedTuple

from .catalog import item_info
from .constants import SEASON_RU
from .errors import SaveError
from .gamedata import load_json
from .goals import load_goals
from .perfection import build_perfection, compute_counts
from .rows import (
    build_bundles,
    build_cooking_rows,
    build_crafting_rows,
    build_fish_rows,
    build_monsters,
    build_museum_rows,
    build_obelisks,
    build_people,
    build_shipping_rows,
    build_skills,
    build_stardrops,
)
from .savefinder import find_saves, no_saves_error
from .saveparser import _file_sig, cached_save, parse_save, read_save_summary
from .timeutil import abs_day, fmt_clock, minutes_of_day
from .today import build_today
from .unlocks import (
    UnlockContext,
    build_unlocks,
    location_filter_options,
    museum_tag_options,
    recipe_kind_options,
)
from .version import __version__

_STATE_CACHE_LIMIT = 8
_STATE_CACHE: OrderedDict[tuple[str, int, int], dict[str, Any]] = OrderedDict()
_STATE_LOCK = threading.RLock()


def _state_cache_get(signature: tuple[str, int, int]) -> dict[str, Any] | None:
    with _STATE_LOCK:
        cached = _STATE_CACHE.get(signature)
        if cached is not None:
            _STATE_CACHE.move_to_end(signature)
        return cached


def _state_cache_put(signature: tuple[str, int, int], state: dict[str, Any]) -> None:
    with _STATE_LOCK:
        _STATE_CACHE[signature] = state
        _STATE_CACHE.move_to_end(signature)
        while len(_STATE_CACHE) > _STATE_CACHE_LIMIT:
            _STATE_CACHE.popitem(last=False)


def clear_state_cache() -> None:
    with _STATE_LOCK:
        _STATE_CACHE.clear()


def _cached_copy(cached: dict[str, Any], saves_found: int) -> dict[str, Any]:
    """Копия состояния, чтобы HTTP-слой не менял закэшированное."""

    # Глубокая копия (~40 мс) сознательно оставлена: попадания в кэш бывают
    # только при переключении на уже разобранную ферму, а защита от тихой
    # порчи кэша мутацией вложенного списка дороже этих миллисекунд.
    state = copy.deepcopy(cached)
    state["meta"]["saves_found"] = saves_found
    state["goals"] = load_goals()
    return state


def secret_sections() -> list[dict[str, Any]]:
    """Разделы danger zone целиком. Не зависят от сейва, только от справочников."""

    return _secret_sections(load_json("secrets.json"), load_json("items.json"), load_json("big_craftables.json"))


def _secret_sections(
    secrets: dict[str, Any], items: dict[str, Any], big_craftables: dict[str, Any]
) -> list[dict[str, Any]]:
    """Разделы danger zone: ID предметов -> иконки, относительные ссылки -> полные URL."""

    base = str(secrets.get("wiki_base") or "")

    def resolve(uid: str) -> dict[str, Any] | None:
        if uid.startswith("BC:"):
            info = big_craftables.get(uid[3:])
            if not info:
                return None
            return {"id": uid, "ru": info.get("ru", ""), "en": info.get("en", ""), "sp": info.get("sp")}
        if uid not in items:
            return None
        return item_info(items, uid)

    def link(value: Any) -> str:
        return base + str(value) if value else ""

    sections: list[dict[str, Any]] = []
    for section in secrets.get("sections", []):
        entries = []
        for entry in section.get("entries", []):
            resolved = [item for item in (resolve(str(uid)) for uid in entry.get("items", [])) if item]
            entries.append({**entry, "items": resolved, "wiki_url": link(entry.get("wiki"))})
        sections.append({**section, "entries": entries, "wiki_url": link(section.get("wiki"))})
    return sections


class _Reference(NamedTuple):
    """Справочники из ``data/*.json``, нужные для сборки состояния."""

    items: dict[str, Any]
    fish: dict[str, Any]
    museum: dict[str, Any]
    artifact_locations: dict[str, Any]
    recipes: dict[str, Any]
    npcs: dict[str, Any]
    bundles: dict[str, Any]
    shipping: list[Any]
    monsters_config: list[Any]
    recipe_sources: dict[str, Any]
    secrets: dict[str, Any]
    big_craftables: dict[str, Any]


def _load_reference() -> _Reference:
    """Все справочники одним местом (каждый кэшируется в :mod:`gamedata`)."""

    return _Reference(
        items=load_json("items.json"),
        fish=load_json("fish.json"),
        museum=load_json("museum.json"),
        artifact_locations=load_json("artifact_locations.json"),
        recipes=load_json("recipes.json"),
        npcs=load_json("npcs.json"),
        bundles=load_json("bundles.json"),
        shipping=load_json("shipping.json"),
        monsters_config=load_json("monsters.json").get("goals") or [],
        recipe_sources=load_json("recipe_sources.json"),
        secrets=load_json("secrets.json"),
        big_craftables=load_json("big_craftables.json"),
    )


def _build_meta(raw: dict[str, Any], selected: str, save_mtime: int, saves_found: int) -> dict[str, Any]:
    """Шапка состояния: ферма, дата, погода, путь и время сейва."""

    return {
        "farm": raw["farm_name"],
        "farmer": raw["name"],
        "players": raw["player_count"],
        "season": raw["season"],
        "season_ru": SEASON_RU.get(raw["season"], raw["season"]),
        "day": raw["day"],
        "year": raw["year"],
        "clock": fmt_clock(raw["time"]),
        "weather": raw["weather"],
        "weather_tomorrow": raw["weather_tomorrow"],
        "island_weather": raw["island_weather"],
        "money": raw["money"],
        "total_earned": raw["total_earned"],
        "walnuts": raw["walnuts"],
        "save_path": selected,
        "save_name": os.path.basename(os.path.dirname(selected)) or os.path.basename(selected),
        "save_mtime": save_mtime,
        "mtime_str": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(save_mtime)),
        "game_version": raw["game_version"],
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "warnings": raw["warnings"],
        "saves_found": saves_found,
        "app_version": __version__,
    }


def _build_alerts(
    need_museum: list[dict[str, Any]], upcoming: list[dict[str, Any]], unmatched: list[str]
) -> dict[str, Any]:
    """Короткие напоминания: не сданное в музей, ближайшие дни рождения, «потерянные» рецепты."""

    return {
        "museum_found_not_donated": [
            {"id": row["id"], "ru": row["ru"], "en": row["en"], "sp": row["sp"]} for row in need_museum
        ],
        "birthdays_week": [
            {
                "key": person["key"],
                "p_idx": person["p_idx"],
                "ru": person["ru"],
                "en": person["en"],
                "until": person["until"],
                "birth": person["birth"],
            }
            for person in upcoming
        ],
        "unmatched_craft": len(unmatched),
    }


def build_state(save_path: str | None = None, saves_dir: str | None = None) -> dict[str, Any]:
    """Полное состояние дашборда для самого свежего (или явно выбранного) сейва."""

    paths = find_saves(saves_dir=saves_dir, explicit=save_path)
    if not paths:
        raise no_saves_error()
    selected = paths[0]
    signature = _file_sig(selected)

    cached = _state_cache_get(signature)
    if cached is not None:
        return _cached_copy(cached, len(paths))

    ref = _load_reference()
    raw = parse_save(selected)
    current_abs_day = abs_day(raw["season"], raw["day"], raw["year"])
    current_minutes = minutes_of_day(raw["time"])
    hearts = {key: int(value.get("points", 0)) // 250 for key, value in raw["friendship"].items()}
    ctx = UnlockContext(raw, hearts)

    fish_rows = build_fish_rows(
        ref.fish,
        ref.items,
        raw,
        raw["season"],
        current_minutes,
        raw["weather"],
        ctx,
    )
    museum_rows = build_museum_rows(ref.museum, ref.artifact_locations, ref.items, raw, ctx)
    ship_rows = build_shipping_rows(ref.shipping, ref.items, raw, raw["season"], ctx)
    cook_rows = build_cooking_rows(ref.recipes, ref.items, raw, ctx, ref.recipe_sources.get("cooking"))
    craft_rows, unmatched = build_crafting_rows(ref.recipes, raw, ctx, ref.recipe_sources.get("crafting"))
    people = build_people(ref.npcs.get("npcs", {}), ref.items, raw, current_abs_day)
    bundle_rooms = build_bundles(ref.bundles, raw)
    monster_rows, monsters_state = build_monsters(ref.monsters_config, raw)
    skills_list, farmer_level = build_skills(raw)
    obelisk_rows = build_obelisks(raw)
    has_gold_clock = "Gold Clock" in raw["farm_buildings"]
    stardrop_rows, all_stardrops = build_stardrops(raw)

    counts = compute_counts(
        fish_rows=fish_rows,
        museum_rows=museum_rows,
        ship_rows=ship_rows,
        cook_rows=cook_rows,
        craft_rows=craft_rows,
        monster_rows=monster_rows,
        people=people,
        raw=raw,
    )
    perfection_state = build_perfection(
        counts,
        craft_rows=craft_rows,
        people=people,
        farmer_level=farmer_level,
        monster_rows=monster_rows,
        monsters_state=monsters_state,
        obelisk_rows=obelisk_rows,
        has_gold_clock=has_gold_clock,
        stardrop_rows=stardrop_rows,
        all_stardrops=all_stardrops,
        raw=raw,
    )

    save_mtime = signature[1] // 1_000_000_000
    today_state, need_museum, upcoming = build_today(
        fish_rows=fish_rows,
        museum_rows=museum_rows,
        people=people,
        bundle_rooms=bundle_rooms,
        cook_rows=cook_rows,
        craft_rows=craft_rows,
        ship_rows=ship_rows,
    )

    state: dict[str, Any] = {
        "meta": _build_meta(raw, selected, save_mtime, len(paths)),
        "counts": counts,
        "fish": fish_rows,
        "museum": museum_rows,
        "shipped": ship_rows,
        "cooking": cook_rows,
        "crafting": craft_rows,
        "people": people,
        "bundles": bundle_rooms,
        "monsters": monsters_state,
        "skills": {
            "list": skills_list,
            "farmer_level": farmer_level,
            "mastery_xp": raw["mastery_xp"],
        },
        "perfection": perfection_state,
        "today": today_state,
        "unlocks": build_unlocks(ctx, [fish_rows, museum_rows, ship_rows, cook_rows, craft_rows], ref.secrets),
        "filters": {
            "fish_locations": location_filter_options(),
            "museum_tags": museum_tag_options(),
            "recipe_kinds": recipe_kind_options(),
        },
        "secrets": {
            "sections": _secret_sections(ref.secrets, ref.items, ref.big_craftables),
            "qi_orders_completed": sorted(order for order in raw["special_orders"] if order.startswith("QiChallenge")),
        },
        "alerts": _build_alerts(need_museum, upcoming, unmatched),
        "goals": load_goals(),
    }

    _state_cache_put(signature, state)
    # Возвращаем изолированную копию, чтобы вызывающий код не мутировал кэш.
    return _cached_copy(state, len(paths))


def list_saves_info(saves_dir: str | None = None, explicit: str | None = None) -> list[dict[str, Any]]:
    """Краткая сводка всех найденных сейвов для переключателя в шапке."""

    out: list[dict[str, Any]] = []
    for path in find_saves(saves_dir=saves_dir, explicit=explicit):
        try:
            # Дёшево -> дорого: уже разобранный сейв, затем ``SaveGameInfo``
            # (десятки КБ) и только в крайнем случае полный разбор файла.
            parsed = cached_save(path) or read_save_summary(path) or parse_save(path)
            mtime = int(os.path.getmtime(path))
            out.append(
                {
                    "path": path,
                    "name": os.path.basename(os.path.dirname(path)) or os.path.basename(path),
                    "farm": parsed["farm_name"],
                    "farmer": parsed["name"],
                    "season": parsed["season"],
                    "season_ru": SEASON_RU.get(parsed["season"], parsed["season"]),
                    "day": parsed["day"],
                    "year": parsed["year"],
                    "money": parsed["money"],
                    "mtime": mtime,
                    "mtime_str": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime)),
                }
            )
        except (SaveError, OSError):
            # Сейв мог исчезнуть или заблокироваться между обнаружением и чтением.
            continue
    return out
