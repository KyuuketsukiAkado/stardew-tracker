"""Разбор XML-сейва Stardew Valley 1.5/1.6.

Модуль намеренно не знает про браузер и UI: на вход путь к файлу, на выходе
плоский словарь с сырыми игровыми значениями. Результат кэшируется по
``(абсолютный путь, mtime_ns, size)`` — файл сейва может быть большим, а
дашборд запрашивает состояние каждые несколько секунд.
"""

from __future__ import annotations

import os
import re
import threading
import xml.etree.ElementTree as ET  # nosec B405 - разбор только через xmlutil.parse_xml
from collections import OrderedDict
from typing import Any

from . import xmlutil as xml
from .errors import SaveError
from .xmlutil import norm_id

_CACHE_LIMIT = 16
_PARSE_CACHE: OrderedDict[tuple[str, int, int], dict[str, Any]] = OrderedDict()
_CACHE_LOCK = threading.RLock()
_PARSE_BUILD_LOCK = threading.Lock()
_NUMBER_RE = re.compile(r"^-?\d+$")


def _file_sig(path: str) -> tuple[str, int, int]:
    """Подпись файла для кэша, с понятными ошибками доступа."""

    absolute = os.path.abspath(path)
    try:
        stat = os.stat(absolute)
    except FileNotFoundError as exc:
        raise SaveError(
            "no_saves",
            f"Файл сохранения не найден: {path}",
            "Файл был перемещён или удалён.",
            [
                "Проверьте путь к папке Saves игры.",
                'Укажите актуальный файл через --save "путь\\к\\сейву".',
            ],
        ) from exc
    except PermissionError as exc:
        raise SaveError(
            "permission_denied",
            "Нет прав на чтение файла сохранения",
            f"Операционная система запретила чтение файла: {absolute}",
            [
                "Проверьте права доступа к файлу и папке сохранения.",
                "Подождите пару секунд, если игра прямо сейчас записывает сейв, и нажмите «Обновить».",
                "Попробуйте скопировать папку сейва в подпапку saves/ рядом с tracker.py.",
            ],
        ) from exc
    except OSError as exc:
        raise SaveError(
            "io_error",
            "Не удалось прочитать файл сохранения",
            f"{absolute}: {exc}",
            ["Проверьте доступность диска и целостность файла сохранения."],
        ) from exc
    return (absolute, stat.st_mtime_ns, stat.st_size)


def _cache_get(signature: tuple[str, int, int]) -> dict[str, Any] | None:
    with _CACHE_LOCK:
        cached = _PARSE_CACHE.get(signature)
        if cached is not None:
            _PARSE_CACHE.move_to_end(signature)
        return cached


def _cache_put(signature: tuple[str, int, int], data: dict[str, Any]) -> None:
    with _CACHE_LOCK:
        _PARSE_CACHE[signature] = data
        _PARSE_CACHE.move_to_end(signature)
        while len(_PARSE_CACHE) > _CACHE_LIMIT:
            _PARSE_CACHE.popitem(last=False)


def clear_cache() -> None:
    with _CACHE_LOCK:
        _PARSE_CACHE.clear()


def normalize_weather_code(value: str) -> str:
    """Приводит код/флаг погоды 1.5 и 1.6 к единому словарю UI."""

    code = (value or "").strip().lower()
    if code in ("rain", "rainy"):
        return "rainy"
    if code in ("storm", "lightning", "stormy"):
        return "storm"
    if code in ("greenrain", "green_rain"):
        return "green_rain"
    if code in ("wind", "debris", "windy"):
        return "wind"
    if code in ("snow", "snowy"):
        return "snow"
    if code in ("sun", "sunny", "festival", "wedding"):
        return "sunny"
    return ""


def _players(root: ET.Element) -> list[ET.Element]:
    """Основной фермер + farmhands мультиплеера."""

    players = xml.kid_all(root, "player")
    farmhands = xml.kid(root, "farmhands")
    if farmhands is None:
        # В некоторых сейвах farmhands лежит глубже и/или после очень
        # длинного <player>. Раньше обход ограничивался 4000 узлами и мог
        # пропустить мультиплеерных фермеров.
        farmhands = xml.deep(root, "farmhands")
    if farmhands is not None:
        for element in farmhands:
            if xml.ln(element) in ("Farmer", "player") and xml.txt(xml.kid(element, "name")):
                players.append(element)
    return players or [root]


def _first_int_deep(element: ET.Element | None) -> int | None:
    value = xml.first_int(element)
    if value is not None:
        return value
    for sub in element.iter() if element is not None else []:
        text = (sub.text or "").strip()
        if _NUMBER_RE.match(text):
            return int(text)
    return None


def _id_counts(host: ET.Element, name: str) -> dict[str, int]:
    """Словарь ``id -> количество`` из коллекций вида ``fishCaught``."""

    result: dict[str, int] = {}
    for key, value in xml.dict_pairs(xml.kid(host, name)):
        count = _first_int_deep(value)
        result[norm_id(key)] = count if count is not None else 1
    return result


def _recipe_counts(host: ET.Element, name: str) -> dict[str, int]:
    return {key: (xml.first_int(value) or 0) for key, value in xml.dict_pairs(xml.kid(host, name))}


def _parse_weather(root: ET.Element) -> tuple[str | None, str | None, str | None]:
    """Погода на сегодня/завтра и на острове (1.6 ``locationWeather`` + 1.5 флаги)."""

    weather: str | None = None
    weather_tomorrow: str | None = None
    island_weather: str | None = None
    location_weather = xml.kid(root, "locationWeather")
    if location_weather is not None:
        for key, value in xml.dict_pairs(location_weather):
            record = xml.kid(value, "LocationWeather") if value is not None else None
            record = record if record is not None else value
            if record is None:
                continue
            weather_text = xml.txt(xml.kid(record, "Weather"))
            tomorrow_text = xml.txt(xml.kid(record, "WeatherForTomorrow"))
            is_raining = xml.txt(xml.kid(record, "IsRaining")).lower() == "true"
            is_lightning = xml.txt(xml.kid(record, "IsLightning")).lower() == "true"
            is_green_rain = xml.txt(xml.kid(record, "IsGreenRain")).lower() == "true"
            normalized = (
                "green_rain"
                if is_green_rain
                else "storm"
                if is_lightning
                else "rainy"
                if is_raining
                else normalize_weather_code(weather_text)
            )
            if key == "Default" and normalized:
                weather = normalized
                weather_tomorrow = normalize_weather_code(tomorrow_text) or None
            elif key == "Island" and normalized:
                island_weather = normalized

    if weather is None:
        if xml.txt(xml.kid(root, "isGreenRain")).lower() == "true":
            weather = "green_rain"
        elif xml.txt(xml.kid(root, "isLightning")).lower() == "true":
            weather = "storm"
        elif xml.txt(xml.kid(root, "isRaining")).lower() == "true":
            weather = "rainy"
        elif xml.txt(xml.kid(root, "isSnowing")).lower() == "true":
            weather = "snow"
        elif xml.txt(xml.kid(root, "isDebrisWeather")).lower() == "true":
            weather = "wind"
        elif xml.kid(root, "isRaining") is not None:
            weather = "sunny"
    return weather, weather_tomorrow, island_weather


def _parse_skills(host: ET.Element) -> dict[str, int]:
    return {
        "farming": xml.first_int(xml.kid(host, "farmingLevel")) or 0,
        "mining": xml.first_int(xml.kid(host, "miningLevel")) or 0,
        "foraging": xml.first_int(xml.kid(host, "foragingLevel")) or 0,
        "fishing": xml.first_int(xml.kid(host, "fishingLevel")) or 0,
        "combat": xml.first_int(xml.kid(host, "combatLevel")) or 0,
        "luck": xml.first_int(xml.kid(host, "luckLevel")) or 0,
    }


def _parse_xp(host: ET.Element) -> list[int]:
    values: list[int] = []
    element = xml.kid(host, "experiencePoints")
    if element is not None:
        for sub in element:
            text = xml.txt(sub)
            if xml.ln(sub) == "int" and text.lstrip("-").isdigit():
                values.append(int(text))
    return values


def _parse_stats(host: ET.Element, root: ET.Element) -> tuple[dict[str, int], dict[str, int], int]:
    monsters_killed: dict[str, int] = {}
    stats_values: dict[str, int] = {}
    total_monsters_killed = 0
    # Нельзя писать ``kid(...) or kid(...)``: Element без детей ложен, и пустой
    # ``<stats/>`` фермера молча подменялся бы чужим блоком.
    stats_el = xml.kid(host, "stats")
    if stats_el is None:
        stats_el = xml.kid(root, "stats")
    if stats_el is not None:
        for monster, value in xml.dict_pairs(xml.kid(stats_el, "specificMonstersKilled")):
            count = xml.first_int(value) or 0
            if monster and count > 0:
                monsters_killed[monster] = monsters_killed.get(monster, 0) + count
        for key, value in xml.dict_pairs(xml.kid(stats_el, "Values")):
            number = xml.first_int(value)
            if key and number is not None:
                stats_values[key] = number
        total = xml.first_int(xml.kid(stats_el, "monstersKilled")) or xml.first_int(xml.kid(stats_el, "MonstersKilled"))
        total_monsters_killed = stats_values.get("monstersKilled") or total or sum(monsters_killed.values())
    return monsters_killed, stats_values, total_monsters_killed


def _parse_mail(host: ET.Element) -> set[str]:
    mail: set[str] = set()
    element = xml.kid(host, "mailReceived")
    if element is not None:
        for sub in element:
            text = xml.txt(sub)
            if text:
                mail.add(text)
    return mail


def _flag(host: ET.Element, name: str) -> bool:
    return xml.txt(xml.kid(host, name)).lower() == "true"


def _parse_axe_level(host: ET.Element) -> int | None:
    """Уровень топора из инвентаря; ``None``, если топора в рюкзаке нет.

    Топор может лежать в сундуке — тогда честно возвращаем «неизвестно».
    """

    items = xml.kid(host, "items")
    for item in items if items is not None else []:
        if (xml.lattr(item, "type") or "") == "Axe":
            level = xml.first_int(xml.kid(item, "upgradeLevel"))
            if level is None:
                level = xml.first_int(xml.kid(item, "UpgradeLevel"))
            return level or 0
    return None


def _parse_special_orders(root: ET.Element) -> set[str]:
    orders: set[str] = set()
    element = xml.kid(root, "completedSpecialOrders")
    if element is None:
        element = xml.deep(root, "completedSpecialOrders")
    for sub in element.iter() if element is not None else []:
        text = xml.txt(sub)
        if text and sub is not element:
            orders.add(text)
    return orders


def _parse_mine_chests(host: ET.Element) -> set[int]:
    chests: set[int] = set()
    for key, _value in xml.dict_pairs(xml.kid(host, "chestConsumedMineLevels")):
        if key.isdigit():
            chests.add(int(key))
    return chests


def _friendship_number(record: ET.Element, field: str) -> int:
    text = xml.txt(xml.kid(record, field))
    return int(text) if text.lstrip("-").isdigit() else 0


def _parse_friendship(host: ET.Element) -> dict[str, dict[str, Any]]:
    """Очки дружбы, подарки и семейный статус по каждому NPC."""

    friendship: dict[str, dict[str, Any]] = {}
    for key, value in xml.dict_pairs(xml.kid(host, "friendshipData")):
        record = xml.kid(value, "Friendship") if value is not None else None
        if record is None:
            record = value
        if record is None:
            continue

        friendship[key] = {
            "points": _friendship_number(record, "Points"),
            "gifts_today": _friendship_number(record, "GiftsToday"),
            "gifts_week": _friendship_number(record, "GiftsThisWeek"),
            "talked": xml.txt(xml.kid(record, "TalkedToToday")).lower() == "true",
            "status": xml.txt(xml.kid(record, "Status")),
            "roommate": xml.txt(xml.kid(record, "RoommateMarriage")).lower() == "true",
        }
    return friendship


def _parse_locations(
    root: ET.Element, museum: dict[str, int], bundles: dict[int, list[bool]], buildings: set[str]
) -> list[bool]:
    """Заполняет музей/бандлы/постройки; возвращает ``areasComplete``."""

    areas_complete: list[bool] = []
    locations = xml.kid(root, "locations")
    for location in locations if locations is not None else []:
        location_type = xml.lattr(location, "type") or ""
        location_name = xml.txt(xml.kid(location, "name"))
        if "LibraryMuseum" in location_type or location_name == "ArchaeologyHouse":
            for _key, value in xml.dict_pairs(xml.kid(location, "museumPieces")):
                number = xml.first_int(value)
                if number is not None:
                    museum[str(number)] = 1
                else:
                    identifier = norm_id(xml.txt(value))
                    if identifier:
                        museum[identifier] = 1
        elif "CommunityCenter" in location_type or location_name == "CommunityCenter":
            for key, value in xml.dict_pairs(xml.kid(location, "bundles")):
                if key.lstrip("-").isdigit():
                    bundles[int(key)] = xml.bools(value)
            areas_complete = xml.bools(xml.kid(location, "areasComplete"))
        elif "Farm" in location_type or location_name == "Farm":
            buildings_el = xml.kid(location, "buildings")
            for building in buildings_el if buildings_el is not None else []:
                building_type = xml.txt(xml.kid(building, "buildingType"))
                if building_type:
                    buildings.add(building_type)
    return areas_complete


def parse_save(path: str) -> dict[str, Any]:
    """Читает сейв и возвращает сырые данные прогресса.

    Кэш хранит словарь по ссылке; вызывающий код не должен его мутировать.
    """

    signature = _file_sig(path)
    cached = _cache_get(signature)
    if cached is not None:
        return cached

    # Один и тот же сейв могут запросить HTTP-поток, наблюдатель и CLI.
    # Сериализуем разбор, чтобы не делать одну и ту же работу N раз и чтобы
    # все вызывающие получили один и тот же кэшированный объект.
    with _PARSE_BUILD_LOCK:
        cached = _cache_get(signature)
        if cached is not None:
            return cached
        return _parse_uncached(signature)


def _parse_uncached(signature: tuple[str, int, int]) -> dict[str, Any]:
    try:
        with open(signature[0], "rb") as handle:
            raw_bytes = handle.read()
    except PermissionError as exc:
        raise SaveError(
            "permission_denied",
            "Нет прав на чтение файла сохранения",
            f"Не удалось открыть для чтения: {signature[0]}",
            [
                "Убедитесь, что у текущего пользователя Windows/Linux есть доступ на чтение файла.",
                "Если игра сохраняется прямо в этот момент, подождите 2–3 секунды.",
            ],
        ) from exc
    except OSError as exc:
        raise SaveError(
            "io_error",
            "Не удалось прочитать файл сохранения",
            f"{signature[0]}: {exc}",
            ["Проверьте доступность диска и целостность файла сохранения."],
        ) from exc

    try:
        root = xml.parse_xml(raw_bytes)
    except ET.ParseError as exc:
        raise SaveError(
            "corrupt_save",
            "Файл сохранения не распознан (ошибка XML)",
            f"Файл {signature[0]} не является корректным XML сохранения Stardew Valley ({exc}).",
            [
                "Убедитесь, что выбран основной файл <Ферма>_<ID>, а не другой файл или архив.",
                "Если игра вылетела во время записи, проверьте соседний резервный файл <Ферма>_<ID>_old.",
            ],
        ) from exc

    if xml.ln(root) != "SaveGame":
        raise SaveError(
            "corrupt_save",
            "Файл не похож на сохранение Stardew Valley",
            f"Корневой тег документа — <{xml.ln(root)}>, ожидался <SaveGame>.",
            [
                "Выберите файл сохранения вида %APPDATA%\\StardewValley\\Saves\\<Ферма>_<ID>\\<Ферма>_<ID>.",
            ],
        )

    players = _players(root)
    host = players[0]
    warnings: list[str] = []

    weather, weather_tomorrow, island_weather = _parse_weather(root)
    skills = _parse_skills(host)
    xp = _parse_xp(host)
    monsters_killed, stats_values, total_monsters_killed = _parse_stats(host, root)
    mail_received = _parse_mail(host)
    mine_chests = _parse_mine_chests(host)

    deepest_mine = xml.first_int(xml.kid(host, "deepestMineLevel")) or 0
    has_skull_key = _flag(host, "hasSkullKey")
    if has_skull_key:
        deepest_mine = max(120, deepest_mine)
    farm_type_el = xml.kid(root, "whichFarm")
    if farm_type_el is None:
        farm_type_el = xml.deep(root, "whichFarm", limit=5000)
    farm_type = xml.first_int(farm_type_el)
    max_stamina = xml.first_int(xml.kid(host, "maxStamina")) or 270

    museum: dict[str, int] = {}
    bundles: dict[int, list[bool]] = {}
    buildings: set[str] = set()
    areas_complete = _parse_locations(root, museum, bundles, buildings)

    walnuts: int | None = None
    walnuts_el = xml.deep(root, "goldenWalnutsFound")
    if walnuts_el is not None and xml.txt(walnuts_el).lstrip("-").isdigit():
        walnuts = int(xml.txt(walnuts_el))

    data: dict[str, Any] = {
        "player_count": len(players),
        "name": xml.txt(xml.kid(host, "name")) or xml.deep_text(host, "name", "Фермер"),
        "farm_name": xml.txt(xml.kid(host, "farmName")) or xml.deep_text(host, "farmName", "Ферма"),
        "money": xml.first_int(xml.kid(host, "money")) or 0,
        "total_earned": xml.first_int(xml.kid(host, "totalMoneyEarned")) or 0,
        "day": xml.first_int(xml.kid(host, "dayOfMonth")) or xml.first_int(xml.deep(root, "dayOfMonth")) or 1,
        "season": (xml.txt(xml.kid(host, "currentSeason")) or xml.deep_text(root, "currentSeason", "spring")).lower(),
        "year": xml.first_int(xml.kid(host, "year")) or xml.first_int(xml.deep(root, "year")) or 1,
        "time": xml.first_int(xml.kid(host, "timeOfDay")) or xml.first_int(xml.deep(root, "timeOfDay")) or 600,
        "weather": weather,
        "weather_tomorrow": weather_tomorrow,
        "island_weather": island_weather,
        "fishCaught": _id_counts(host, "fishCaught"),
        "archaeologyFound": _id_counts(host, "archaeologyFound"),
        "mineralsFound": _id_counts(host, "mineralsFound"),
        "basicShipped": _id_counts(host, "basicShipped"),
        "recipesCooked": _id_counts(host, "recipesCooked"),
        "craftingRecipes": _recipe_counts(host, "craftingRecipes"),
        "cookingRecipes": _recipe_counts(host, "cookingRecipes"),
        "friendship": _parse_friendship(host),
        "museum": museum,
        "bundles": bundles,
        "areasComplete": areas_complete,
        "farm_buildings": buildings,
        "walnuts": walnuts,
        "perfection_waivers": xml.first_int(xml.deep(root, "perfectionWaivers", limit=5000)) or 0,
        "skills": skills,
        "xp": xp,
        "mastery_xp": stats_values.get("MasteryExp", 0),
        "monsters_killed": monsters_killed,
        "total_monsters_killed": total_monsters_killed,
        "deepest_mine": deepest_mine,
        "mail_received": mail_received,
        "mine_chests": mine_chests,
        "max_stamina": max_stamina,
        # Флаги доступа к локациям: из них считаются «обязательные условия».
        "has_skull_key": has_skull_key,
        "has_rusty_key": _flag(host, "hasRustyKey"),
        "has_dark_talisman": _flag(host, "hasDarkTalisman"),
        "has_magic_ink": _flag(host, "hasMagicInk"),
        "has_club_card": _flag(host, "hasClubCard"),
        "house_level": xml.first_int(xml.kid(host, "houseUpgradeLevel")) or 0,
        "axe_level": _parse_axe_level(host),
        "farm_type": farm_type,
        "special_orders": _parse_special_orders(root),
        "game_version": xml.deep_text(root, "gameVersion", "") or xml.deep_text(root, "gameVersionLabel", ""),
    }

    if not data["friendship"]:
        warnings.append("Не нашёл friendshipData — раздел «Люди» будет пустым.")
    if not data["fishCaught"]:
        warnings.append("Не нашёл fishCaught — рыбалка будет показана как «не поймано».")
    if not museum:
        warnings.append("Музей: не нашёл museumPieces (возможно, ещё ничего не сдано).")
    if not bundles:
        warnings.append("Не нашёл состояние бандлов Community Center.")

    data["warnings"] = warnings
    _cache_put(signature, data)
    return data
