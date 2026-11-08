#!/usr/bin/env python3
"""Генерирует синтетический файл сохранения Stardew Valley для тестов.

Структура повторяет реальный сейв 1.6 (те же теги и вложенность), поэтому
тесты проверяют настоящий парсер, а не заглушку.

    python tests/make_test_save.py /tmp/saves     # создать сейв в папке
"""

from __future__ import annotations

import os
import sys

FISH = {
    "128": 4,
    "129": 2,
    "141": 1,
    "159": 1,
    "164": 3,
    "683": 2,
    "699": 6,
    "700": 1,
    "701": 0,
    "836": 1,
}  # 701 с нулём — не считается пойманной
ARCH = {"96": 2, "100": 1, "114": 3, "561": 1}
MINERALS = {"72": 3, "80": 1, "82": 1, "84": 1, "86": 1, "88": 1}
SHIPPED = {
    "16": 12,
    "18": 5,
    "20": 1,
    "194": 3,
    "195": 2,
    "221": 1,
    "388": 500,
    "709": 20,
}
COOKED = {"194": 4, "195": 1, "196": 2}
COOKING_KNOWN = {
    "Fried Egg": 1,
    "Omelet": 1,
    "Salad": 1,
    "Maki Roll": 0,
    "Pancakes": 0,
    "Complete Breakfast": 0,
    "Autumn's Bounty": 0,
}
CRAFTED = {
    "Wood Fence": 40,
    "Stone Fence": 3,
    "Chest": 2,
    "Torch": 11,
    "Sprinkler": 4,
    "Scarecrow": 1,
    "Furnace": 0,
    "Preserves Jar": 0,
    "Keg": 0,
    "Bee House": 0,
    "Quality Sprinkler": 0,
}
FRIENDS = {
    "Abigail": (1875, 0, 1, "Friendly"),
    "Robin": (2500, 0, 2, "Friendly"),
    "Shane": (300, 1, 1, "Friendly"),
    "Penny": (0, 0, 0, ""),
    "Krobus": (1200, 0, 0, "Friendly"),
    "Haley": (875, 0, 2, "Friendly"),
}
MUSEUM_PIECES = ["96", "100", "72", "80"]
BUNDLES = {
    0: [True, True, True, True],
    1: [True, False, True, False],
    13: [True, True, False, False],
}
MONSTERS = {
    "Green Slime": 680,
    "Frost Jelly": 345,
    "Bat": 142,
    "Frost Bat": 74,
    "Skeleton": 53,
    "Bug": 88,
    "Duggy": 31,
    "Dust Spirit": 418,
    "Shadow Brute": 96,
    "Rock Crab": 44,
    "Mummy": 37,
    "Pepper Rex": 19,
    "Serpent": 118,
    "Magma Sprite": 89,
}


def _arr(v):
    return f"<value><ArrayOfInt><int>{v}</int></ArrayOfInt></value>"


def _int(v):
    return f"<value><int>{v}</int></value>"


def _dict(d):
    return "".join(f"<item><key><string>(O){k}</string></key>{_arr(v)}</item>" for k, v in d.items())


def _dict_int(d):
    return "".join(f"<item><key><string>(O){k}</string></key>{_int(v)}</item>" for k, v in d.items())


def build_xml():
    friends = "".join(
        f"<item><key><string>{k}</string></key><value><Friendship>"
        f"<Points>{p}</Points><GiftsToday>{gt}</GiftsToday>"
        f"<GiftsThisWeek>{gw}</GiftsThisWeek><TalkedToToday>true</TalkedToToday>"
        f"<Status>{st}</Status></Friendship></value></item>"
        for k, (p, gt, gw, st) in FRIENDS.items()
    )
    museum = "".join(
        f"<item><key><Vector2><X>{12 + i}</X><Y>5</Y></Vector2></key><value><int>{v}</int></value></item>"
        for i, v in enumerate(MUSEUM_PIECES)
    )
    bundles = "".join(
        f"<item><key><int>{idx}</int></key><value><ArrayOfBoolean>"
        + "".join(f"<boolean>{str(b).lower()}</boolean>" for b in flags)
        + "</ArrayOfBoolean></value></item>"
        for idx, flags in BUNDLES.items()
    )
    cooking = "".join(
        f"<item><key><string>{k}</string></key><value><int>{v}</int></value></item>" for k, v in COOKING_KNOWN.items()
    )
    crafting = "".join(
        f"<item><key><string>{k}</string></key><value><int>{v}</int></value></item>" for k, v in CRAFTED.items()
    )
    monsters = "".join(
        f"<item><key><string>{k}</string></key><value><int>{v}</int></value></item>" for k, v in MONSTERS.items()
    )

    return f"""<?xml version="1.0" encoding="utf-8"?>
<SaveGame xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <gameVersion>1.6.15</gameVersion>
  <player>
    <name>Фермер</name>
    <farmName>Тестовая</farmName>
    <money>54230</money>
    <totalMoneyEarned>418900</totalMoneyEarned>
    <dayOfMonth>12</dayOfMonth>
    <currentSeason>fall</currentSeason>
    <year>3</year>
    <timeOfDay>1350</timeOfDay>
    <farmingLevel>10</farmingLevel>
    <miningLevel>9</miningLevel>
    <foragingLevel>9</foragingLevel>
    <fishingLevel>8</fishingLevel>
    <combatLevel>8</combatLevel>
    <!-- Удача не входит в Farmer Level; значение проверяет регрессию формулы. -->
    <luckLevel>4</luckLevel>
    <deepestMineLevel>155</deepestMineLevel>
    <hasSkullKey>true</hasSkullKey>
    <mailReceived>
      <string>CF_Fair</string>
      <string>CF_Mines</string>
      <string>CF_Sewer</string>
    </mailReceived>
    <stats>
      <MonstersKilled>2224</MonstersKilled>
      <specificMonstersKilled>{monsters}</specificMonstersKilled>
    </stats>
    <UniqueMultiplayerID>345678901</UniqueMultiplayerID>
    <fishCaught>{_dict(FISH)}</fishCaught>
    <archaeologyFound>{_dict(ARCH)}</archaeologyFound>
    <mineralsFound>{_dict_int(MINERALS)}</mineralsFound>
    <basicShipped>{_dict_int(SHIPPED)}</basicShipped>
    <recipesCooked>{_dict_int(COOKED)}</recipesCooked>
    <cookingRecipes>{cooking}</cookingRecipes>
    <craftingRecipes>{crafting}</craftingRecipes>
    <friendshipData>{friends}</friendshipData>
  </player>
  <locationWeather>
    <item>
      <key><string>Default</string></key>
      <value><LocationWeather><Weather>Sun</Weather><WeatherForTomorrow>Rain</WeatherForTomorrow><IsRaining>false</IsRaining></LocationWeather></value>
    </item>
  </locationWeather>
  <locations>
    <GameLocation xsi:type="Farm">
      <name>Farm</name>
      <buildings>
        <Building><buildingType>Earth Obelisk</buildingType></Building>
        <Building><buildingType>Desert Obelisk</buildingType></Building>
      </buildings>
    </GameLocation>
    <GameLocation xsi:type="LibraryMuseum">
      <name>ArchaeologyHouse</name>
      <museumPieces>{museum}</museumPieces>
    </GameLocation>
    <GameLocation xsi:type="CommunityCenter">
      <name>CommunityCenter</name>
      <areasComplete><boolean>true</boolean><boolean>true</boolean><boolean>false</boolean>
        <boolean>false</boolean><boolean>false</boolean><boolean>false</boolean></areasComplete>
      <bundles>{bundles}</bundles>
    </GameLocation>
  </locations>
  <goldenWalnutsFound>74</goldenWalnutsFound>
</SaveGame>
"""


def write_test_save(base_dir):
    """Создаёт <base_dir>/Тестовая_345678901/Тестовая_345678901 и возвращает путь к сейву."""
    folder = os.path.join(base_dir, "Тестовая_345678901")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "Тестовая_345678901")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(build_xml())
    with open(os.path.join(folder, "SaveGameInfo"), "w", encoding="utf-8") as fh:
        fh.write("<SaveGame/>")
    return path


def _safe_output() -> None:
    """Кириллица в cp1252-канал Windows не должна ронять генератор."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(errors="replace")
            except (ValueError, OSError):
                pass


if __name__ == "__main__":
    _safe_output()
    target = sys.argv[1] if len(sys.argv) > 1 else "saves"
    p = write_test_save(os.path.abspath(target))
    print("Создан тестовый сейв:", p)
