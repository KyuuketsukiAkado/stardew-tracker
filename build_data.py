#!/usr/bin/env python3
"""
Собирает компактный датасет трекера (data/*.json) и атласы иконок (assets/sprites/*.png)
из распакованных данных игры Stardew Valley 1.6.x.

Внешних зависимостей нет (только стандартная библиотека Python 3.9+, включая чтение/запись PNG).
Обычно запускать не нужно: готовые data/ и assets/sprites/ уже лежат в репозитории.

Пример:
    python build_data.py --content-dir "C:/Program Files (x86)/Steam/steamapps/common/Stardew Valley/Content"
    python build_data.py --content-dir ./Content_Unpacked
"""

from __future__ import annotations

import argparse
import json
import os
import re
import struct
import sys
import zlib
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data")
SPRITES_OUT = os.path.join(HERE, "assets", "sprites")
LOCALES = {"en": "", "ru": ".ru-RU"}

TOKEN_RE = re.compile(r"\[LocalizedText\s+([^\]:]+):([A-Za-z0-9_.\-]+)(?:\s+[^\]]*)?\]")

# Категории предметов, которые встречаются в рецептах как отрицательные ID + иконка-представитель (sheet, idx).
CATEGORY = {
    "-1": ("Gold", "Золото", [1, 79]),
    "-2": ("Gem", "Самоцвет", [0, 72]),
    "-4": ("Any Fish", "Любая рыба", [0, 145]),
    "-5": ("Any Egg", "Любое яйцо", [0, 176]),
    "-6": ("Any Milk", "Любое молоко", [0, 184]),
    "-7": ("Cooking", "Блюдо", [0, 194]),
    "-8": ("Crafting", "Ремесло", [0, 388]),
    "-12": ("Mineral", "Минерал", [0, 80]),
    "-14": ("Meat", "Мясо", [0, 684]),
    "-15": ("Metal / Ore", "Руда / слиток", [0, 335]),
    "-16": ("Resource", "Стройматериал", [0, 388]),
    "-17": ("Rare Product", "Редкий товар", [0, 430]),
    "-18": ("Animal Product", "Продукт животных", [0, 440]),
    "-19": ("Fertilizer", "Удобрение", [0, 368]),
    "-20": ("Trash", "Мусор", [0, 168]),
    "-21": ("Bait", "Наживка", [0, 685]),
    "-22": ("Tackle", "Снасть", [0, 686]),
    "-23": ("Beach / Roe", "Морепродукт", [0, 393]),
    "-24": ("Decor", "Декор", [0, 328]),
    "-25": ("Ingredient", "Ингредиент", [0, 246]),
    "-26": ("Artisan Good", "Ремесленный товар", [0, 348]),
    "-27": ("Syrup / Resin", "Сироп / смола", [0, 724]),
    "-28": ("Monster Loot", "Лут монстров", [0, 766]),
    "-74": ("Seeds", "Семена", [0, 472]),
    "-75": ("Vegetable", "Овощ", [0, 24]),
    "-79": ("Fruit", "Фрукт", [0, 400]),
    "-80": ("Flower", "Цветок", [0, 591]),
    "-81": ("Forage", "Дикоросы", [0, 18]),
    "-95": ("Hat", "Шляпа", [0, 106]),
    "-96": ("Ring", "Кольцо", [0, 517]),
    "-97": ("Boots", "Обувь", [0, 517]),
    "-98": ("Weapon", "Оружие", [0, 109]),
    "-99": ("Tool", "Инструмент", [0, 115]),
    "-100": ("Clothing", "Одежда", [0, 428]),
    "-102": ("Book", "Книга", [1, 102]),
    "-103": ("Skill Book", "Книга навыков", [1, 96]),
    "-777": ("Wild Seeds (any)", "Дикие семена (любые)", [0, 495]),
}

FISH_FALLBACK_LOC = {
    "158": ("The Mines (20F)", "Шахты (20 эт.)"),
    "161": ("The Mines (60F)", "Шахты (60 эт.)"),
    "162": ("The Mines (100F) / Caldera", "Шахты (100 эт.) / Кальдера"),
    "372": ("Crab Pot (Ocean)", "Крабовая ловушка (Океан)"),
    "715": ("Crab Pot (Ocean)", "Крабовая ловушка (Океан)"),
    "716": ("Crab Pot (Freshwater)", "Крабовая ловушка (Пресная)"),
    "717": ("Crab Pot (Ocean)", "Крабовая ловушка (Океан)"),
    "718": ("Crab Pot (Ocean)", "Крабовая ловушка (Океан)"),
    "719": ("Crab Pot (Ocean)", "Крабовая ловушка (Океан)"),
    "720": ("Crab Pot (Ocean)", "Крабовая ловушка (Океан)"),
    "721": ("Crab Pot (Freshwater)", "Крабовая ловушка (Пресная)"),
    "722": ("Crab Pot (Freshwater)", "Крабовая ловушка (Пресная)"),
    "723": ("Crab Pot (Ocean)", "Крабовая ловушка (Океан)"),
}

SKIP_LOCS = {"Temp", "fishingGame"}

LOC_NAMES = {
    "IslandSouth": ("Ginger Island (south)", "Имбирный остров (юг)"),
    "IslandSouthEast": ("Ginger Island (southeast)", "Имбирный остров (ЮВ)"),
    "IslandSouthEastCave": ("Pirate Cove", "Пиратская бухта"),
    "IslandNorth": ("Ginger Island (north)", "Имбирный остров (север)"),
    "IslandWest": ("Ginger Island (west)", "Имбирный остров (запад)"),
    "IslandEast": ("Ginger Island (east)", "Имбирный остров (восток)"),
    "IslandHut": ("Island Hut", "Хижина на острове"),
    "IslandSecret": ("Secret Woods", "Тайный лес"),
    "IslandFarmCave": ("Island Farm Cave", "Пещера островной фермы"),
    "IslandShrine": ("Island Shrine", "Святилище острова"),
    "VolcanoDungeon0": ("Volcano Dungeon", "Подземелье Вулкана"),
    "Caldera": ("Caldera", "Кальдера"),
    "Backwoods": ("Backwoods", "Глушь"),
    "BugLand": ("Mutant Bug Lair", "Логово мутантов"),
    "Desert": ("Calico Desert", "Пустыня Калико"),
    "Submarine": ("Night Market Submarine", "Субмарина ночного рынка"),
    "BeachNightMarket": ("Night Market (Beach)", "Ночной рынок (пляж)"),
    "WitchSwamp": ("Witch's Swamp", "Болото ведьмы"),
    "Sewer": ("The Sewers", "Канализация"),
    "Mine": ("The Mines", "Шахты"),
    "UndergroundMine": ("The Mines", "Шахты"),
    "Farm": ("Farm", "Ферма"),
    "Forest": ("Cindersap Forest", "Пепельносмольный лес"),
    "Woods": ("Secret Woods", "Тайный лес"),
    "Mountain": ("The Mountain", "Горы"),
    "Town": ("Pelican Town", "Город Пеликан"),
    "Beach": ("Pelican Beach", "Пеликанский пляж"),
}

BUNDLE_NAMES_RU = {
    "Spring Crops": "Узелок весеннего урожая",
    "Summer Crops": "Узелок летнего урожая",
    "Fall Crops": "Узелок осеннего урожая",
    "Quality Crops": "Узелок отборного урожая",
    "Animal": "Животноводческий узелок",
    "Artisan": "Хозяйственный узелок",
    "Spring Foraging": "Узелок весенних дикоросов",
    "Summer Foraging": "Узелок летних дикоросов",
    "Fall Foraging": "Узелок осенних дикоросов",
    "Winter Foraging": "Узелок зимних дикоросов",
    "Construction": "Строительный узелок",
    "Exotic Foraging": "Узелок заготовки экзотики",
    "River Fish": "Речной узелок",
    "Lake Fish": "Озёрный узелок",
    "Ocean Fish": "Океанский узелок",
    "Night Fishing": "Узелок ночной рыбалки",
    "Specialty Fish": "Узелок особого улова",
    "Crab Pot": "Краболовный узелок",
    "Blacksmith's": "Кузнечный узелок",
    "Geologist's": "Геологический узелок",
    "Adventurer's": "Узелок приключенца",
    "Chef's": "Поварской узелок",
    "Field Research": "Исследовательский узелок",
    "Enchanter's": "Узелок волшебника",
    "Dye": "Красочный узелок",
    "Fodder": "Кормовой узелок",
    "The Missing": "Пропавший узелок",
}

# 12 целей Гильдии авантюристов (Stardew Valley 1.6)
MONSTER_GOALS = [
    {
        "key": "Slimes",
        "en": "Slimes",
        "ru": "Слаймы",
        "target": 1000,
        "monsters": ["Green Slime", "Frost Jelly", "Sludge", "Tiger Slime"],
        "where_ru": "Шахты (1–119), Тайный лес, Остров",
        "where_en": "The Mines (1–119), Secret Woods, Island",
        "reward_id": "520",
        "reward_ru": "Кольцо укротителя слаймов",
        "reward_en": "Slime Charmer Ring",
        "sprite_file": "Green Slime.png",
        "frame": [0, 256, 16, 24],
    },
    {
        "key": "Void Spirits",
        "en": "Void Spirits",
        "ru": "Духи пустоты",
        "target": 150,
        "monsters": [
            "Shadow Brute",
            "Shadow Shaman",
            "Shadow Sniper",
            "Shadow Guy",
            "Shadow Girl",
        ],
        "where_ru": "Шахты (80–119)",
        "where_en": "The Mines (80–119)",
        "reward_id": "523",
        "reward_ru": "Кольцо дикаря",
        "reward_en": "Savage Ring",
        "sprite_file": "Shadow Brute.png",
        "frame": [0, 0, 16, 32],
    },
    {
        "key": "Bats",
        "en": "Bats",
        "ru": "Летучие мыши",
        "target": 200,
        "monsters": ["Bat", "Frost Bat", "Lava Bat", "Iridium Bat"],
        "where_ru": "Шахты (31–119), Пещера Черепа",
        "where_en": "The Mines (31–119), Skull Cavern",
        "reward_id": "522",
        "reward_ru": "Кольцо вампира",
        "reward_en": "Vampire Ring",
        "sprite_file": "Bat.png",
        "frame": [0, 0, 16, 24],
    },
    {
        "key": "Skeletons",
        "en": "Skeletons",
        "ru": "Скелеты",
        "target": 50,
        "monsters": ["Skeleton", "Skeleton Mage"],
        "where_ru": "Шахты (70–79)",
        "where_en": "The Mines (70–79)",
        "reward_id": "",
        "reward_ru": "Маска скелета",
        "reward_en": "Skeleton Mask",
        "sprite_file": "Skeleton.png",
        "frame": [0, 0, 16, 32],
    },
    {
        "key": "Cave Insects",
        "en": "Cave Insects",
        "ru": "Пещерные насекомые",
        "target": 80,
        "monsters": ["Bug", "Fly", "Grub"],
        "where_ru": "Шахты (1–29), Логово мутантов",
        "where_en": "The Mines (1–29), Mutant Bug Lair",
        "reward_id": "",
        "reward_ru": "Голова насекомого (меч)",
        "reward_en": "Insect Head",
        "sprite_file": "Bug.png",
        "frame": [0, 0, 16, 16],
    },
    {
        "key": "Duggies",
        "en": "Duggies",
        "ru": "Копашки",
        "target": 30,
        "monsters": ["Duggy", "Magma Duggy"],
        "where_ru": "Шахты (6–29, рыхлая земля), Остров",
        "where_en": "The Mines (6–29, dirt), Island",
        "reward_id": "",
        "reward_ru": "Каска",
        "reward_en": "Hard Hat",
        "sprite_file": "Duggy.png",
        "frame": [0, 24, 16, 24],
    },
    {
        "key": "Dust Sprites",
        "en": "Dust Sprites",
        "ru": "Пыльные духи",
        "target": 500,
        "monsters": ["Dust Spirit"],
        "where_ru": "Шахты (40–79)",
        "where_en": "The Mines (40–79)",
        "reward_id": "526",
        "reward_ru": "Воровское кольцо",
        "reward_en": "Burglar's Ring",
        "sprite_file": "Dust Spirit.png",
        "frame": [0, 0, 16, 24],
    },
    {
        "key": "Rock Crabs",
        "en": "Rock Crabs",
        "ru": "Каменные крабы",
        "target": 60,
        "monsters": ["Rock Crab", "Lava Crab", "Iridium Crab"],
        "where_ru": "Шахты (1–29, 80–119), Пещера Черепа",
        "where_en": "The Mines (1–29, 80–119), Skull Cavern",
        "reward_id": "810",
        "reward_ru": "Крабовое кольцо (+5 защ.)",
        "reward_en": "Crabshell Ring",
        "sprite_file": "Rock Crab.png",
        "frame": [16, 0, 16, 24],
    },
    {
        "key": "Mummies",
        "en": "Mummies",
        "ru": "Мумии",
        "target": 100,
        "monsters": ["Mummy"],
        "where_ru": "Пещера Черепа (добить взрывом/Чародеем)",
        "where_en": "Skull Cavern (finish with bomb/Crusader)",
        "reward_id": "",
        "reward_ru": "Шляпа чародея",
        "reward_en": "Arcane Hat",
        "sprite_file": "Mummy.png",
        "frame": [0, 0, 16, 32],
    },
    {
        "key": "Pepper Rex",
        "en": "Pepper Rex",
        "ru": "Перечные динозавры",
        "target": 50,
        "monsters": ["Pepper Rex"],
        "where_ru": "Пещера Черепа (доисторические этажи)",
        "where_en": "Skull Cavern (Prehistoric floors)",
        "reward_id": "",
        "reward_ru": "Рыцарский шлем",
        "reward_en": "Knight's Helmet",
        "sprite_file": "Pepper Rex.png",
        "frame": [0, 0, 32, 32],
    },
    {
        "key": "Serpents",
        "en": "Serpents",
        "ru": "Змеи",
        "target": 250,
        "monsters": ["Serpent", "Royal Serpent"],
        "where_ru": "Пещера Черепа",
        "where_en": "Skull Cavern",
        "reward_id": "811",
        "reward_ru": "Напалмовое кольцо",
        "reward_en": "Napalm Ring",
        "sprite_file": "Serpent.png",
        "frame": [0, 0, 32, 32],
    },
    {
        "key": "Flame Spirits",
        "en": "Magma Sprites",
        "ru": "Магмовые духи",
        "target": 150,
        "monsters": ["Magma Sprite", "Magma Sparker"],
        "where_ru": "Подземелье Вулкана (Имбирный остров)",
        "where_en": "Volcano Dungeon (Ginger Island)",
        "reward_id": "",
        "reward_ru": "Номер телефона Марлона",
        "reward_en": "Marlon's Phone Number",
        "sprite_file": "Magma Sprite.png",
        "frame": [0, 32, 16, 16],
    },
]


# --------------------------------------------------------------------------- #
#  Минимальный декодер/кодер PNG на stdlib (struct + zlib)
# --------------------------------------------------------------------------- #
def read_png(path):
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"Не PNG: {path}")
    pos = 8
    w = h = bd = ct = 0
    palette = trns = None
    idat = bytearray()
    while pos < len(data):
        length, ctype = struct.unpack(">I4s", data[pos : pos + 8])
        chunk = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if ctype == b"IHDR":
            w, h, bd, ct, _c, _f, interlace = struct.unpack(">IIBBBBB", chunk)
            if bd != 8 or interlace != 0:
                raise ValueError(
                    f"Неподдерживаемый PNG ({bd}-bit, interlace={interlace}): {path}"
                )
        elif ctype == b"PLTE":
            palette = chunk
        elif ctype == b"tRNS":
            trns = chunk
        elif ctype == b"IDAT":
            idat.extend(chunk)
        elif ctype == b"IEND":
            break
    raw = zlib.decompress(bytes(idat))
    bpp = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ct]
    stride = w * bpp
    rows = []
    prev = bytearray(stride)
    p = 0
    for _y in range(h):
        ft = raw[p]
        row = bytearray(raw[p + 1 : p + 1 + stride])
        p += 1 + stride
        if ft == 1:
            for i in range(bpp, stride):
                row[i] = (row[i] + row[i - bpp]) & 0xFF
        elif ft == 2:
            for i in range(stride):
                row[i] = (row[i] + prev[i]) & 0xFF
        elif ft == 3:
            for i in range(stride):
                a = row[i - bpp] if i >= bpp else 0
                row[i] = (row[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif ft == 4:
            for i in range(stride):
                a = row[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                row[i] = (row[i] + pr) & 0xFF
        prev = row
        if ct == 6:
            rows.append(row)
        elif ct == 2:
            rgba = bytearray(w * 4)
            for x in range(w):
                rgba[x * 4 : x * 4 + 3] = row[x * 3 : x * 3 + 3]
                rgba[x * 4 + 3] = 255
            rows.append(rgba)
        elif ct == 3:
            rgba = bytearray(w * 4)
            for x in range(w):
                idx = row[x]
                rgba[x * 4 : x * 4 + 3] = palette[idx * 3 : idx * 3 + 3]
                rgba[x * 4 + 3] = trns[idx] if (trns and idx < len(trns)) else 255
            rows.append(rgba)
        elif ct == 4:
            rgba = bytearray(w * 4)
            for x in range(w):
                g, al = row[x * 2], row[x * 2 + 1]
                rgba[x * 4 : x * 4 + 4] = bytes((g, g, g, al))
            rows.append(rgba)
        elif ct == 0:
            rgba = bytearray(w * 4)
            for x in range(w):
                g = row[x]
                rgba[x * 4 : x * 4 + 4] = bytes((g, g, g, 255))
            rows.append(rgba)
    return w, h, rows


def write_png(path, w, h, rows):
    """Записывает компактный PNG (PLTE+tRNS при <=256 цветах, иначе сжатый RGBA)."""

    def mk_chunk(ctype, payload):
        crc = zlib.crc32(ctype + payload) & 0xFFFFFFFF
        return (
            struct.pack(">I4s", len(payload), ctype) + payload + struct.pack(">I", crc)
        )

    colors = {}
    can_index = True
    for r in rows:
        for x in range(0, w * 4, 4):
            px = bytes(r[x : x + 4])
            if px[3] == 0:
                px = b"\x00\x00\x00\x00"
            if px not in colors:
                if len(colors) >= 256:
                    can_index = False
                    break
                colors[px] = len(colors)
        if not can_index:
            break

    if can_index and colors:
        # Сортируем прозрачные цвета вперёд, чтобы tRNS был коротким
        sorted_cols = sorted(colors.keys(), key=lambda c: (c[3] == 255, c))
        cmap = {c: i for i, c in enumerate(sorted_cols)}
        plte = bytearray()
        trns = bytearray()
        last_non_opaque = -1
        for i, c in enumerate(sorted_cols):
            plte.extend(c[:3])
            trns.append(c[3])
            if c[3] < 255:
                last_non_opaque = i
        raw = bytearray()
        for r in rows:
            raw.append(0)
            for x in range(0, w * 4, 4):
                px = bytes(r[x : x + 4])
                if px[3] == 0:
                    px = b"\x00\x00\x00\x00"
                raw.append(cmap[px])
        chunks = [
            mk_chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 3, 0, 0, 0)),
            mk_chunk(b"PLTE", bytes(plte)),
        ]
        if last_non_opaque >= 0:
            chunks.append(mk_chunk(b"tRNS", bytes(trns[: last_non_opaque + 1])))
        chunks.append(mk_chunk(b"IDAT", zlib.compress(bytes(raw), 9)))
        chunks.append(mk_chunk(b"IEND", b""))
    else:
        raw = bytearray()
        prev = bytearray(w * 4)
        for r in rows:
            # Нормализуем полностью прозрачные пиксели для лучшего сжатия
            norm = bytearray(r)
            for x in range(0, w * 4, 4):
                if norm[x + 3] == 0:
                    norm[x : x + 3] = b"\x00\x00\x00"
            # Выбираем между фильтром None (0) и Up (2) по сумме модулей
            f0 = sum(b if b < 128 else 256 - b for b in norm)
            up = bytearray((norm[i] - prev[i]) & 0xFF for i in range(w * 4))
            f2 = sum(b if b < 128 else 256 - b for b in up)
            if f2 < f0:
                raw.append(2)
                raw.extend(up)
            else:
                raw.append(0)
                raw.extend(norm)
            prev = norm
        chunks = [
            mk_chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)),
            mk_chunk(b"IDAT", zlib.compress(bytes(raw), 9)),
            mk_chunk(b"IEND", b""),
        ]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n" + b"".join(chunks))


def make_canvas(w, h):
    return [bytearray(w * 4) for _ in range(h)]


def blit(dst, src, sx, sy, sw, sh, dx, dy):
    sh_max = min(sh, len(src) - sy, len(dst) - dy)
    sw_max = min(sw, (len(src[0]) // 4) - sx, (len(dst[0]) // 4) - dx)
    if sh_max <= 0 or sw_max <= 0:
        return
    for r in range(sh_max):
        dst[dy + r][dx * 4 : (dx + sw_max) * 4] = src[sy + r][
            sx * 4 : (sx + sw_max) * 4
        ]


# --------------------------------------------------------------------------- #
#  Загрузка JSON и локализации
# --------------------------------------------------------------------------- #
def load(path):
    with open(path, encoding="utf-8-sig") as fh:
        return json.load(fh)


def find_file(content_dir, rel):
    p = os.path.join(content_dir, rel)
    if os.path.exists(p):
        return p
    rel_norm = rel.replace("\\", "/").lower()
    base = os.path.basename(rel_norm)
    best = None
    for root, _dirs, files in os.walk(content_dir):
        for name in files:
            if name.lower() == base:
                cand = os.path.join(root, name)
                if cand.replace("\\", "/").lower().endswith(rel_norm):
                    return cand
                best = best or cand
    return best


class Resolver:
    """Разворачивает токены [LocalizedText Strings\\Objects:Foo_Name] с корректным языком."""

    def __init__(self, content_dir):
        self.maps = {}
        for asset in (
            "Objects",
            "BigCraftables",
            "NPCNames",
            "Locations",
            "UI",
            "Weapons",
            "StringsFromCSFiles",
            "BundleNames",
            "1_6_Strings",
            "Characters",
        ):
            for loc, suffix in LOCALES.items():
                path = find_file(content_dir, f"Strings/{asset}{suffix}.json")
                if path:
                    self.maps[(asset, loc)] = load(path)

    def text(self, value, loc="en", default=""):
        if not isinstance(value, str):
            return value or default
        m = TOKEN_RE.search(value)
        if not m:
            return value
        asset, key = m.group(1).replace("/", "\\").split("\\")[-1], m.group(2)
        if key == "MapPage.cs.11064":
            return "Ферма" if loc == "ru" else "Farm"
        # Ищем ТОЛЬКО в запрошенном языке (или фолбэк на en, но никогда ru -> en!)
        lang_order = (loc, "en") if loc != "en" else ("en",)
        for lg in lang_order:
            table = self.maps.get((asset, lg)) or {}
            if table.get(key):
                return table[key]
        for lg in lang_order:
            for (_a2, loc2), table in self.maps.items():
                if loc2 == lg and table.get(key):
                    return table[key]
        return default or key.split(".")[-1].replace("_Name", "").replace("_", " ")


def parse_int_map(raw):
    return [t for t in re.split(r"[\s,/]+", raw.strip()) if t]


def item_group(obj_type, cat, uid):
    """Человекочитаемая группа предмета для колоркодинга и фильтров."""
    if obj_type == "Arch":
        return "artifact"
    if obj_type == "Minerals" or cat in (-2, -12):
        return "mineral"
    if obj_type == "Fish" or cat == -4:
        return "fish"
    if obj_type == "Cooking" or cat == -7:
        return "cooking"
    if cat == -75:
        return "vegetable"
    if cat == -79:
        return "fruit"
    if cat == -80:
        return "flower"
    if cat == -81 or cat == -23:
        return "forage"
    if cat in (-5, -6, -17, -18):
        return "animal"
    if cat in (-26, -27):
        return "artisan"
    if cat == -15:
        return "metal"
    if cat == -28:
        return "monster"
    if cat == -16 or str(uid) in (
        "92",
        "330",
        "388",
        "390",
        "709",
        "771",
        "787",
        "Moss",
    ):
        return "resource"
    if cat == -74 or obj_type == "Seeds":
        return "seed"
    return "other"


def format_unlock(raw_unlock, npcs_map):
    """Переводит код разблокировки рецепта в читаемый RU/EN вид."""
    u = (raw_unlock or "").strip()
    if not u or u in ("null", "none"):
        return {"ru": "Магазин / событие", "en": "Shop / Event"}
    if u == "default":
        return {"ru": "Доступно со старта", "en": "Starter recipe"}
    parts = u.split()
    Skills = {
        "Farming": ("Фермерство", "Farming"),
        "Mining": ("Горное дело", "Mining"),
        "Foraging": ("Собирательство", "Foraging"),
        "Fishing": ("Рыбная ловля", "Fishing"),
        "Combat": ("Боевые навыки", "Combat"),
        "Luck": ("Удача", "Luck"),
    }
    if parts[0] == "s" and len(parts) >= 3:
        sk_ru, sk_en = Skills.get(parts[1], (parts[1], parts[1]))
        lvl = parts[2]
        return {"ru": f"{sk_ru} ур. {lvl}", "en": f"{sk_en} Lv. {lvl}"}
    if parts[0] == "f" and len(parts) >= 3:
        npc_key = parts[1]
        hearts = parts[2]
        npc_ru = npcs_map.get(npc_key, {}).get("ru", npc_key)
        npc_en = npcs_map.get(npc_key, {}).get("en", npc_key)
        return {"ru": f"{npc_ru} ({hearts}♥)", "en": f"{npc_en} ({hearts}♥)"}
    if parts[0] == "l" and len(parts) >= 2:
        if parts[1] == "100":
            return {
                "ru": "ТВ «Королева соуса» / Салун",
                "en": "Queen of Sauce / Saloon",
            }
        return {"ru": f"Уровень / ТВ ({parts[1]})", "en": f"Level / TV ({parts[1]})"}
    return {"ru": u, "en": u}


def build_sprites(content, npc_keys_ordered):
    """Собирает 7 компактных PNG-атласов в assets/sprites/."""
    spring_p = find_file(content, "Maps/springobjects.png")
    obj2_p = find_file(content, "TileSheets/Objects_2.png")
    craft_p = find_file(content, "TileSheets/Craftables.png")
    junimo_p = find_file(content, "LooseSprites/JunimoNote.png")
    cursors_p = find_file(content, "LooseSprites/Cursors.png")
    if not (spring_p and obj2_p and craft_p):
        print(
            "  (текстуры в --content-dir не найдены — существующие assets/sprites/ не тронуты)"
        )
        return

    os.makedirs(SPRITES_OUT, exist_ok=True)
    for src, dst_name in (
        (spring_p, "objects.png"),
        (obj2_p, "objects2.png"),
        (craft_p, "craftables.png"),
    ):
        w, h, rows = read_png(src)
        out_p = os.path.join(SPRITES_OUT, dst_name)
        write_png(out_p, w, h, rows)
        print(
            f"  sprite {dst_name:16s} {w:4d}x{h:<4d} {os.path.getsize(out_p) / 1024:6.1f} KB"
        )

    # Бандлы: 640x96 (0..64 — 32x32 иконки слотов 0..39; 64..96 — цветные узелки 0..6)
    if junimo_p:
        _jw, _jh, jrows = read_png(junimo_p)
        bcanvas = make_canvas(640, 96)
        blit(bcanvas, jrows, 0, 180, 640, 64, 0, 0)
        # 7 цветов узелков из JunimoNote.png (закрытый 16x16 и раскрытый цветок 16x16)
        # В JunimoNote.png начиная с y=244 лежат полосы по 256px (16 кадров 16x16):
        # кадр 0 — закрытый узелок, кадр 14 — раскрытый цветок.
        # Позиции 7 цветов (0 Green, 1 Purple, 2 Orange, 3 Yellow, 4 Red, 5 Blue, 6 Teal):
        bag_coords = [
            (0, 244),  # 0 green
            (256, 244),  # 1 purple
            (0, 260),  # 2 orange
            (256, 260),  # 3 yellow
            (0, 276),  # 4 red
            (256, 276),  # 5 blue
            (0, 292),  # 6 teal
        ]
        for ci, (bx, by) in enumerate(bag_coords):
            blit(bcanvas, jrows, bx, by, 16, 16, ci * 32, 64)
            blit(bcanvas, jrows, bx + 14 * 16, by, 16, 16, ci * 32 + 16, 64)
        bp = os.path.join(SPRITES_OUT, "bundles.png")
        write_png(bp, 640, 96, bcanvas)
        print(
            f"  sprite {'bundles.png':16s}  640x96   {os.path.getsize(bp) / 1024:6.1f} KB"
        )

    # Портреты 34 NPC: сетка 6x6 по 64x64 = 384x384
    char_data = load(find_file(content, "Data/Characters.json"))
    ncanvas = make_canvas(384, 384)
    for idx, nkey in enumerate(npc_keys_ordered):
        ch = char_data.get(nkey) or {}
        tex = (ch.get("TextureName") or nkey).replace("\\", "/").split("/")[-1]
        pp = find_file(content, f"Portraits/{tex}.png") or find_file(
            content, f"Portraits/{nkey}.png"
        )
        if pp:
            _pw, _ph, prows = read_png(pp)
            col, row = idx % 6, idx // 6
            blit(ncanvas, prows, 0, 0, 64, 64, col * 64, row * 64)
    np_out = os.path.join(SPRITES_OUT, "npcs.png")
    write_png(np_out, 384, 384, ncanvas)
    print(
        f"  sprite {'npcs.png':16s}  384x384  {os.path.getsize(np_out) / 1024:6.1f} KB"
    )

    # Монстры (12 целей Гильдии): сетка 6x2 по 32x32 = 192x64
    mcanvas = make_canvas(192, 64)
    for idx, mg in enumerate(MONSTER_GOALS):
        mp = find_file(content, f"Characters/Monsters/{mg['sprite_file']}")
        if mp:
            _mw, _mh, mrows = read_png(mp)
            fx, fy, fw, fh = mg["frame"]
            col, row = idx % 6, idx // 6
            dx = col * 32 + (32 - fw) // 2
            dy = row * 32 + (32 - fh) // 2
            blit(mcanvas, mrows, fx, fy, fw, fh, dx, dy)
    mp_out = os.path.join(SPRITES_OUT, "monsters.png")
    write_png(mp_out, 192, 64, mcanvas)
    print(
        f"  sprite {'monsters.png':16s}  192x64   {os.path.getsize(mp_out) / 1024:6.1f} KB"
    )

    # UI-иконки из Cursors.png: 16x2 по 16x16 = 256x32
    if cursors_p:
        _cw, _ch, crows = read_png(cursors_p)
        ucanvas = make_canvas(256, 32)
        ui_specs = [
            # row 0 (0..15)
            (211, 428, 7, 6),  # 0 heart full
            (218, 428, 7, 6),  # 1 heart empty
            (229, 410, 14, 14),  # 2 gift box
            (280, 412, 15, 14),  # 3 gold coins
            (338, 400, 8, 8),  # 4 silver star
            (346, 400, 8, 8),  # 5 gold star
            (346, 392, 8, 8),  # 6 iridium star
            (406, 441, 12, 8),  # 7 spring
            (406, 449, 12, 8),  # 8 summer
            (406, 457, 12, 8),  # 9 fall
            (406, 465, 12, 8),  # 10 winter
            (341, 421, 12, 8),  # 11 weather sun
            (365, 421, 12, 8),  # 12 weather rain
            (377, 421, 12, 8),  # 13 weather storm
            (389, 421, 12, 8),  # 14 weather wind
            (401, 421, 12, 8),  # 15 weather snow
            # row 1 (16..23)
            (10, 428, 10, 10),  # 16 skill farming
            (30, 428, 10, 10),  # 17 skill mining
            (60, 428, 10, 10),  # 18 skill foraging
            (20, 428, 10, 10),  # 19 skill fishing
            (120, 428, 10, 10),  # 20 skill combat
            (190, 423, 14, 11),  # 21 mail
            (140, 428, 10, 10),  # 22 skull
            (434, 475, 9, 9),  # 23 clock
        ]
        for idx, (sx, sy, sw, sh) in enumerate(ui_specs):
            col, row = idx % 16, idx // 16
            dx = col * 16 + (16 - sw) // 2
            dy = row * 16 + (16 - sh) // 2
            blit(ucanvas, crows, sx, sy, sw, sh, dx, dy)
        up_out = os.path.join(SPRITES_OUT, "ui.png")
        write_png(up_out, 256, 32, ucanvas)
        print(
            f"  sprite {'ui.png':16s}  256x32   {os.path.getsize(up_out) / 1024:6.1f} KB"
        )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--content-dir", default=os.environ.get("SDV_CONTENT", "."))
    args = ap.parse_args()
    content = os.path.abspath(args.content_dir)
    os.makedirs(OUT, exist_ok=True)

    def need(rel):
        p = find_file(content, rel)
        if not p:
            sys.exit(f"Не найден файл: {rel} в {content}")
        return load(p)

    res = Resolver(content)
    objects = need("Data/Objects.json")
    big_raw = need("Data/BigCraftables.json")

    # ---------- сезоны выращивания/сбора для предметов ----------
    item_seasons = defaultdict(list)
    crops_path = find_file(content, "Data/Crops.json")
    if crops_path:
        for cr in load(crops_path).values():
            if not isinstance(cr, dict):
                continue
            hid = str(cr.get("HarvestItemId") or "")
            hid = hid.removeprefix("(O)")
            for s in cr.get("Seasons") or []:
                sl = str(s).lower()
                if hid and sl not in item_seasons[hid]:
                    item_seasons[hid].append(sl)

    ft_path = find_file(content, "Data/FruitTrees.json")
    if ft_path:
        for ft in load(ft_path).values():
            if not isinstance(ft, dict):
                continue
            for fr in ft.get("Fruit") or []:
                fid = str((fr or {}).get("ItemId") or "")
                fid = fid.removeprefix("(O)")
                for s in ft.get("Seasons") or []:
                    sl = str(s).lower()
                    if fid and sl not in item_seasons[fid]:
                        item_seasons[fid].append(sl)

    locs_file = find_file(content, "Data/Locations.json")
    locdata = load(locs_file) if locs_file else {}
    for loc in locdata.values():
        if not isinstance(loc, dict):
            continue
        for fg in loc.get("Forage") or []:
            if not isinstance(fg, dict):
                continue
            fid = str(fg.get("ItemId") or "")
            fid = fid.removeprefix("(O)")
            s = str(fg.get("Season") or "").lower()
            if (
                fid
                and s in ("spring", "summer", "fall", "winter")
                and s not in item_seasons[fid]
            ):
                item_seasons[fid].append(s)

    # ---------- предметы (Objects) ----------
    items = {}
    for oid, o in objects.items():
        if not isinstance(o, dict):
            continue
        uid = oid.removeprefix("(O)")
        tex = o.get("Texture") or ""
        sheet = 1 if "Objects_2" in tex else 0
        sidx = int(o.get("SpriteIndex") or 0)
        otype = o.get("Type", "")
        ocat = o.get("Category", 0)
        en_name = (
            res.text(o.get("DisplayName"), "en", o.get("Name", uid))
            or o.get("Name", uid)
            or uid
        )
        ru_name = res.text(o.get("DisplayName"), "ru", en_name) or en_name
        entry = {
            "en": en_name,
            "ru": ru_name,
            "n": o.get("Name", ""),
            "t": otype,
            "c": ocat,
            "p": o.get("Price", 0),
            "sp": [sheet, sidx],
            "grp": item_group(otype, ocat, uid),
        }
        if item_seasons.get(uid):
            order_s = ["spring", "summer", "fall", "winter"]
            entry["seasons"] = sorted(
                item_seasons[uid], key=lambda x: order_s.index(x) if x in order_s else 9
            )
        items[uid] = entry

    # ---------- большие механизмы (BigCraftables) ----------
    big_craftables = {}
    for bid, b in big_raw.items():
        if not isinstance(b, dict):
            continue
        uid = bid.removeprefix("(BC)")
        sidx = int(b.get("SpriteIndex") or 0)
        en_name = (
            res.text(b.get("DisplayName"), "en", b.get("Name", uid))
            or b.get("Name", uid)
            or uid
        )
        ru_name = res.text(b.get("DisplayName"), "ru", en_name) or en_name
        big_craftables[uid] = {
            "en": en_name,
            "ru": ru_name,
            "n": b.get("Name", ""),
            "p": b.get("Price", 0),
            "sp": [2, sidx],
        }

    def item_name(uid, loc):
        it = items.get(str(uid))
        return it[loc] if it else f"#{uid}"

    def item_sp(uid):
        it = items.get(str(uid))
        return it["sp"] if it and "sp" in it else None

    # ---------- NPC ----------
    char_data = need("Data/Characters.json")
    gift_raw = need("Data/NPCGiftTastes.json")
    universal = {
        k: parse_int_map(v) for k, v in gift_raw.items() if k.startswith("Universal_")
    }
    by_name = {it["n"]: uid for uid, it in items.items()}

    def taste_ids(raw_list):
        out = []
        for tok in raw_list:
            clean = tok.removeprefix("(O)")
            if clean in items:
                out.append(clean)
            elif clean in by_name:
                out.append(by_name[clean])
        return out

    npcs_unsorted = {}
    for key, ch in char_data.items():
        if not isinstance(ch, dict):
            continue
        if ch.get("CanSocialize") is False or not ch.get("BirthSeason"):
            continue
        tastes = gift_raw.get(key)
        loves, likes, hates = [], [], []
        if isinstance(tastes, str):
            parts = tastes.split("/")
            if len(parts) > 1:
                loves = parse_int_map(parts[1])
            if len(parts) > 3:
                likes = parse_int_map(parts[3])
            if len(parts) > 7:
                hates = parse_int_map(parts[7])
        npcs_unsorted[key] = {
            "en": res.text(ch.get("DisplayName", key), "en", key),
            "ru": res.text(ch.get("DisplayName", key), "ru", key),
            "birth": [ch.get("BirthSeason"), ch.get("BirthDay")],
            "romance": bool(ch.get("CanBeRomanced")),
            "home": ch.get("HomeRegion", ""),
            "love": taste_ids(loves),
            "like": taste_ids(likes)[:24],
            "hate": taste_ids(hates),
            "love_tok": [i for i in loves if i not in items and i not in by_name],
            "like_tok": [i for i in likes if i not in items and i not in by_name][:12],
        }

    npc_keys_ordered = sorted(npcs_unsorted.keys())
    npcs = {}
    for idx, key in enumerate(npc_keys_ordered):
        entry = dict(npcs_unsorted[key])
        entry["p_idx"] = idx
        npcs[key] = entry

    # ---------- рыба ----------
    fish_raw = need("Data/Fish.json")
    fish = {}
    for fid, raw in fish_raw.items():
        if not isinstance(raw, str):
            continue
        f = raw.split("/")
        uid = fid.removeprefix("(O)")
        if uid not in items:
            continue
        if len(f) > 1 and f[1] == "trap":
            water = f[4] if len(f) > 4 else "ocean"
            fish[uid] = {
                "diff": None,
                "beh": "trap",
                "trap": True,
                "water": water,
                "size": [f[5], f[6]] if len(f) > 6 else None,
                "time": "",
                "season": "spring summer fall winter",
                "weather": "both",
                "loc": [],
            }
        else:
            fish[uid] = {
                "diff": int(f[1]) if len(f) > 1 and f[1].isdigit() else None,
                "beh": f[2] if len(f) > 2 else "",
                "trap": False,
                "size": [f[3], f[4]] if len(f) > 4 else None,
                "time": f[5] if len(f) > 5 else "",
                "season": f[6] if len(f) > 6 else "",
                "weather": f[7] if len(f) > 7 else "",
                "loc": [],
            }

    for loc_key, loc in locdata.items():
        if not isinstance(loc, dict) or loc_key in SKIP_LOCS:
            continue
        if loc_key in LOC_NAMES:
            lname_en, lname_ru = LOC_NAMES[loc_key]
        else:
            display = loc.get("DisplayName")
            if display:
                lname_ru = res.text(display, "ru", loc_key)
                lname_en = res.text(display, "en", loc_key)
            else:
                lname_en, lname_ru = loc_key, loc_key
        for entry in loc.get("Fish") or []:
            if not isinstance(entry, dict):
                continue
            fid = str(entry.get("ItemId") or "")
            uid = fid.removeprefix("(O)")
            rec = fish.get(uid)
            if rec is not None and not rec.get("trap"):
                pair = {"ru": lname_ru, "en": lname_en}
                if pair not in rec["loc"] and len(rec["loc"]) < 6:
                    rec["loc"].append(pair)

    for uid, rec in fish.items():
        if (not rec.get("loc") or rec.get("trap")) and uid in FISH_FALLBACK_LOC:
            en, ru = FISH_FALLBACK_LOC[uid]
            rec["loc"] = [{"en": en, "ru": ru}]

    # ---------- музей ----------
    artifacts, minerals = [], []
    for uid, it in items.items():
        if it["t"] == "Arch":
            artifacts.append(uid)
        elif it["t"] == "Minerals":
            minerals.append(uid)
    artifacts.sort(key=lambda i: int(i) if i.isdigit() else 0)
    minerals.sort(key=lambda i: int(i) if i.isdigit() else 0)

    # ---------- рецепты ----------
    def resolve_ing(raw_tok):
        tok = raw_tok.strip()
        if tok.startswith("(BC)"):
            bc_id = tok[4:]
            bc = big_craftables.get(bc_id)
            if bc:
                return bc["ru"], bc["en"], bc["sp"]
            return f"#{bc_id}", f"#{bc_id}", None
        tok = tok.removeprefix("(O)")
        if tok.startswith("-"):
            c = CATEGORY.get(tok)
            if c:
                return c[1], c[0], c[2]
            return f"категория {tok}", f"category {tok}", None
        if tok in items:
            it = items[tok]
            return it["ru"], it["en"], it["sp"]
        if tok in by_name:
            it = items[by_name[tok]]
            return it["ru"], it["en"], it["sp"]
        return f"#{tok}", f"#{tok}", None

    def parse_ing_pairs(raw_str):
        toks = [t for t in raw_str.strip().split() if t]
        out = []
        for i in range(0, len(toks) - 1, 2):
            iid = toks[i]
            try:
                qty = int(toks[i + 1])
            except ValueError:
                qty = 1
            ru_n, en_n, sp = resolve_ing(iid)
            out.append([ru_n, en_n, qty, sp])
        return out

    cook_raw = need("Data/CookingRecipes.json")
    craft_raw = need("Data/CraftingRecipes.json")
    recipes = {"cooking": {}, "crafting": {}}

    for name, line in cook_raw.items():
        if not isinstance(line, str):
            continue
        f = line.split("/")
        out_parts = (f[2] if len(f) > 2 else "").strip().split()
        out_id = out_parts[0] if out_parts else ""
        out_id = out_id.removeprefix("(O)")
        out_qty = (
            int(out_parts[1]) if len(out_parts) > 1 and out_parts[1].isdigit() else 1
        )
        unlock_raw = f[3] if len(f) > 3 else ""
        it = items.get(out_id, {})
        recipes["cooking"][name] = {
            "en": it.get("en", name),
            "ru": it.get("ru", name),
            "item": out_id,
            "qty": out_qty,
            "sp": it.get("sp"),
            "price": it.get("p", 0),
            "ing": parse_ing_pairs(f[0]),
            "unlock": unlock_raw,
            "unlock_info": format_unlock(unlock_raw, npcs),
        }

    for name, line in craft_raw.items():
        if not isinstance(line, str):
            continue
        f = line.split("/")
        out_parts = (f[2] if len(f) > 2 else "").strip().split()
        out_id = out_parts[0] if out_parts else ""
        out_qty = (
            int(out_parts[1]) if len(out_parts) > 1 and out_parts[1].isdigit() else 1
        )
        is_bc = (f[3].strip().lower() == "true") if len(f) > 3 else False
        unlock_raw = f[4] if len(f) > 4 else ""
        if is_bc:
            clean_id = out_id.removeprefix("(BC)")
            bc = big_craftables.get(clean_id, {})
            name_en = bc.get("en", name)
            name_ru = bc.get("ru", name)
            sp = bc.get("sp")
            item_ref = f"(BC){clean_id}" if clean_id else ""
        else:
            clean_id = out_id.removeprefix("(O)")
            it = items.get(clean_id, {})
            name_en = it.get("en", name)
            name_ru = it.get("ru", name)
            sp = it.get("sp")
            item_ref = clean_id
        recipes["crafting"][name] = {
            "en": name,
            "ru": name_ru,
            "item": item_ref,
            "big": is_bc,
            "qty": out_qty,
            "sp": sp,
            "name_en": name_en,
            "name_ru": name_ru,
            "ing": parse_ing_pairs(f[0]),
            "unlock": unlock_raw,
            "unlock_info": format_unlock(unlock_raw, npcs),
        }

    # ---------- бандлы ----------
    bundles_raw = need("Data/Bundles.json")
    bundles_ru_path = find_file(content, "Data/Bundles.ru-RU.json")
    bundles_ru = load(bundles_ru_path) if bundles_ru_path else {}
    room_names = {
        "Pantry": ("Pantry", "Кладовая"),
        "Crafts Room": ("Crafts Room", "Комната ремёсел"),
        "Fish Tank": ("Fish Tank", "Аквариум"),
        "Boiler Room": ("Boiler Room", "Котельная"),
        "Vault": ("Vault", "Хранилище"),
        "Bulletin Board": ("Bulletin Board", "Доска объявлений"),
        "Abandoned Joja Mart": ("Abandoned Joja Mart", "Заброшенный Joja Mart"),
    }
    rooms = defaultdict(list)
    for key, raw in bundles_raw.items():
        if not isinstance(raw, str):
            continue
        room, _, idx = key.rpartition("/")
        f = raw.split("/")
        ru_f = bundles_ru.get(key, "").split("/") if bundles_ru.get(key) else []
        reqs = parse_int_map(f[2]) if len(f) > 2 else []
        req_items = []
        for i in range(0, len(reqs) - 2, 3):
            iid, qty, qual = reqs[i], reqs[i + 1], reqs[i + 2]
            if iid == "-1":
                req_items.append(
                    {
                        "id": "-1",
                        "qty": int(qty),
                        "qual": 0,
                        "en": "Gold",
                        "ru": "Золото",
                        "sp": [1, 79],
                    }
                )
            else:
                clean_iid = iid.removeprefix("(O)")
                req_items.append(
                    {
                        "id": clean_iid,
                        "qty": int(qty),
                        "qual": int(qual),
                        "en": item_name(clean_iid, "en"),
                        "ru": item_name(clean_iid, "ru"),
                        "sp": item_sp(clean_iid),
                        "seasons": items.get(clean_iid, {}).get("seasons", []),
                    }
                )
        reward = (f[1] if len(f) > 1 else "").strip()
        rw = reward.split()
        reward_item = None
        if len(rw) >= 2:
            rtype, rid = rw[0], rw[1]
            rqty = rw[2] if len(rw) > 2 else "1"
            if rtype == "BO" and rid in big_craftables:
                bc = big_craftables[rid]
                reward_item = {
                    "id": f"(BC){rid}",
                    "qty": rqty,
                    "en": bc["en"],
                    "ru": bc["ru"],
                    "sp": bc["sp"],
                }
            elif rid in items:
                reward_item = {
                    "id": rid,
                    "qty": rqty,
                    "en": item_name(rid, "en"),
                    "ru": item_name(rid, "ru"),
                    "sp": item_sp(rid),
                }
        rooms[room].append(
            {
                "idx": int(idx) if idx.isdigit() else 0,
                "slot": int(idx) if idx.isdigit() else 0,
                "name_en": f[6] if len(f) > 6 and f[6] else (f[0] if f else ""),
                "name_ru": (
                    ru_f[6]
                    if len(ru_f) > 6 and ru_f[6]
                    else (
                        BUNDLE_NAMES_RU.get(f[0])
                        or (f[6] if len(f) > 6 and f[6] else (f[0] if f else ""))
                    )
                ),
                "items": req_items,
                "need_count": int(f[4])
                if len(f) > 4 and f[4].isdigit()
                else len(req_items),
                "color": int(f[3]) if len(f) > 3 and f[3].isdigit() else 0,
                "reward": reward_item,
            }
        )

    bundles = []
    order = [
        "Pantry",
        "Crafts Room",
        "Fish Tank",
        "Boiler Room",
        "Vault",
        "Bulletin Board",
        "Abandoned Joja Mart",
    ]
    for room in order:
        if room in rooms:
            bundles.append(
                {
                    "key": room,
                    "en": room_names.get(room, (room, room))[0],
                    "ru": room_names.get(room, (room, room))[1],
                    "list": sorted(rooms[room], key=lambda b: b["slot"]),
                }
            )

    bn_ru = find_file(content, "Strings/BundleNames.ru-RU.json")
    if bn_ru:
        try:
            ru_map = load(bn_ru)
            for room in bundles:
                for b in room["list"]:
                    if ru_map.get(b["name_en"]):
                        b["name_ru"] = ru_map[b["name_en"]]
        except (OSError, ValueError, TypeError) as exc:
            print(
                f"Предупреждение: не удалось прочитать локализацию имён бандлов: {exc}",
                file=sys.stderr,
            )

    # ---------- монстры и цели Гильдии ----------
    monsters_out = []
    for idx, mg in enumerate(MONSTER_GOALS):
        rid = mg["reward_id"]
        monsters_out.append(
            {
                "idx": idx,
                "key": mg["key"],
                "en": mg["en"],
                "ru": mg["ru"],
                "target": mg["target"],
                "monsters": mg["monsters"],
                "where_ru": mg["where_ru"],
                "where_en": mg["where_en"],
                "reward": {
                    "ru": mg["reward_ru"],
                    "en": mg["reward_en"],
                    "sp": item_sp(rid) if rid else None,
                },
            }
        )

    misc = {
        "seasons": [
            ["spring", "Весна", 28],
            ["summer", "Лето", 28],
            ["fall", "Осень", 28],
            ["winter", "Зима", 28],
        ],
        "build": "1.6",
    }

    payloads = {
        "items.json": items,
        "big_craftables.json": big_craftables,
        "fish.json": fish,
        "museum.json": {"artifacts": artifacts, "minerals": minerals},
        "recipes.json": recipes,
        "npcs.json": {"npcs": npcs, "universal": universal},
        "bundles.json": {"rooms": bundles},
        "monsters.json": {"goals": monsters_out},
        "misc.json": misc,
    }
    for name, data in payloads.items():
        p = os.path.join(OUT, name)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
        print(f"  data   {name:20s} {os.path.getsize(p) / 1024:7.1f} KB")

    build_sprites(content, npc_keys_ordered)

    print(
        f"\nГотово: {len(items)} предметов, {len(big_craftables)} механизмов, {len(fish)} рыб, "
        f"{len(artifacts)} артефактов, {len(minerals)} минералов, "
        f"{len(recipes['cooking'])} блюд, {len(recipes['crafting'])} крафтов, "
        f"{len(npcs)} NPC, {sum(len(r['list']) for r in bundles)} бандлов, "
        f"{len(monsters_out)} целей Гильдии"
    )


if __name__ == "__main__":
    main()
