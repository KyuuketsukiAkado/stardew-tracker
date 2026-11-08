#!/usr/bin/env python3
"""
Stardew Valley Progress Tracker — читает файл сохранения и строит живой дашборд.

Команды:
    python tracker.py serve           # локальный сервер + автообновление (по умолчанию)
    python tracker.py build           # собрать автономный report.html (со встроенными иконками)
    python tracker.py info            # показать, что нашлось в сейве (диагностика)
    python tracker.py open            # собрать report.html и открыть в браузере

Ключи:
    --save ПУТЬ        файл сейва или папка сейва (по умолчанию ищется сам)
    --saves-dir ПУТЬ   папка со всеми сохранениями
    --port 8777        порт для serve
    --no-open          не открывать браузер
    --no-watch         отключить фоновое отслеживание изменений сейва
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import sys
import threading
import time
import webbrowser
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
SPRITES_DIR = os.path.join(HERE, "assets", "sprites")
GOALS_FILE = os.path.join(HERE, "goals.json")
TEMPLATE = os.path.join(HERE, "assets", "dashboard.html")
REPORT = os.path.join(HERE, "report.html")

SEASONS = ["spring", "summer", "fall", "winter"]
SEASON_RU = {"spring": "Весна", "summer": "Лето", "fall": "Осень", "winter": "Зима"}
GAME_VERSIONS = ("1.6",)

SPRITE_FILES = (
    "objects.png",
    "objects2.png",
    "craftables.png",
    "bundles.png",
    "npcs.png",
    "monsters.png",
    "ui.png",
)

STARDROPS = [
    (
        "CF_Fair",
        "Ярмарка Долины Стардью (2 000 жетонов)",
        "Stardew Valley Fair (2,000 tokens)",
    ),
    ("CF_Mines", "Сундук на 100-м этаже шахты", "Mine floor 100 treasure chest"),
    ("CF_Spouse", "От супруга/соседа при 12.5♥", "Spouse / Roommate at 12.5♥"),
    (
        "CF_Sewer",
        "Покупка у Кробуса в канализации (20 000g)",
        "Krobus in The Sewers (20,000g)",
    ),
    (
        "CF_Statue",
        "Старый мастер Канноли в Тайном лесу (Сладкая самоцветинка)",
        "Old Master Cannoli in Secret Woods",
    ),
    (
        "CF_Fish",
        "Письмо от Вилли за поимку всех рыб",
        "Master Angler letter from Willy",
    ),
    (
        "museumComplete",
        "Награда за полный сбор музея (95 предметов)",
        "Complete Museum collection (95 items)",
    ),
]

OBELISKS = [
    ("Earth Obelisk", "Обелиск Земли", "Earth Obelisk"),
    ("Water Obelisk", "Обелиск Воды", "Water Obelisk"),
    ("Desert Obelisk", "Обелиск Пустыни", "Desert Obelisk"),
    ("Island Obelisk", "Обелиск Острова", "Island Obelisk"),
]

# Кэши в памяти (P1-4): справочники data/*.json + разбор сейва по (abspath, mtime_ns, size)
_STATIC_CACHE: dict[str, object] = {}
_PARSE_CACHE: dict[tuple[str, int, int], dict] = {}
_STATE_CACHE: dict[tuple[str, int, int], dict] = {}
_SPRITE_B64_CACHE: dict[str, str] = {}
_GOALS_LOCK = threading.Lock()


class SaveError(SystemExit):
    """Осмысленная ошибка работы с файлом сохранения (P1-8)."""

    def __init__(self, kind: str, title: str, detail: str, steps: list[str]):
        self.kind = kind
        self.title = title
        self.detail = detail
        self.steps = steps
        msg_lines = [f"Ошибка: {title}", f"  {detail}"]
        if steps:
            msg_lines.append("Что сделать:")
            for idx, st in enumerate(steps, 1):
                msg_lines.append(f"  {idx}. {st}")
        super().__init__("\n".join(msg_lines))

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "title": self.title,
            "detail": self.detail,
            "steps": self.steps,
        }


# --------------------------------------------------------------------------- #
#  Поиск сохранения
# --------------------------------------------------------------------------- #
def candidate_save_dirs():
    home = os.path.expanduser("~")
    appdata = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
    return [
        os.path.join(appdata, "StardewValley", "Saves"),
        os.path.join(home, ".config", "StardewValley", "Saves"),
        os.path.join(home, "Library", "Application Support", "StardewValley", "Saves"),
        os.path.join(
            home,
            ".local",
            "share",
            "Steam",
            "steamapps",
            "compatdata",
            "413150",
            "pfx",
            "drive_c",
            "users",
            "steamuser",
            "AppData",
            "Roaming",
            "StardewValley",
            "Saves",
        ),
    ]


def safe_mtime(path):
    """Get a sortable mtime while tolerating files removed during save discovery."""
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0


def looks_like_save(path):
    """Сейв — XML-файл без расширения, лежащий рядом с SaveGameInfo."""
    base = os.path.basename(path)
    if not os.path.isfile(path):
        return False
    if base in ("SaveGameInfo", "startup_preferences") or base.endswith(
        ("_old", ".bak", ".tmp")
    ):
        return False
    try:
        if os.path.getsize(path) < 200:
            return False
        with open(path, "rb") as fh:
            head = fh.read(400).decode("utf-8", "ignore")
        return "<SaveGame" in head
    except OSError:
        return False


def find_saves(saves_dir=None, explicit=None):
    if explicit:
        if os.path.isdir(explicit):
            try:
                entries = os.listdir(explicit)
            except PermissionError:
                raise SaveError(
                    "permission_denied",
                    "Нет прав на чтение папки сохранений",
                    f"Операционная система запретила доступ к папке: {explicit}",
                    [
                        "Проверьте права доступа к папке или скопируйте сейвы в доступную директорию."
                    ],
                )
            except OSError as exc:
                raise SaveError(
                    "io_error",
                    "Не удалось прочитать папку сохранений",
                    f"{explicit}: {exc}",
                    ["Проверьте доступность диска и правильность пути."],
                )
            out = [
                p
                for p in (os.path.join(explicit, f) for f in entries)
                if looks_like_save(p)
            ]
            if out:
                return sorted(out, key=safe_mtime, reverse=True)
            saves_dir = explicit
        elif os.path.exists(explicit):
            return [explicit]
        else:
            raise SaveError(
                "no_saves",
                f"Путь не найден: {explicit}",
                "Указанный файл или папка сохранения не существует.",
                [
                    "Проверьте правильность пути в аргументе --save.",
                    "В Windows сохранения обычно лежат в %APPDATA%\\StardewValley\\Saves\\<Ферма>_<ID>\\<Ферма>_<ID>.",
                    "Запустите `python tracker.py info`, чтобы проверить автопоиск.",
                ],
            )

    dirs = [saves_dir] if saves_dir else []
    if not saves_dir:
        dirs += candidate_save_dirs()
        dirs.append(os.path.join(HERE, "saves"))
    found = []
    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        try:
            entries = os.listdir(d)
        except OSError:
            continue
        for name in entries:
            sub = os.path.join(d, name)
            if os.path.isdir(sub):
                try:
                    sub_entries = os.listdir(sub)
                except OSError:
                    continue
                for f in sub_entries:
                    p = os.path.join(sub, f)
                    if looks_like_save(p):
                        found.append(p)
        for f in entries:
            p = os.path.join(d, f)
            if looks_like_save(p):
                found.append(p)
    return sorted(set(found), key=safe_mtime, reverse=True)


# --------------------------------------------------------------------------- #
#  Мини-обёртки над XML (не зависит от пространств имён)
# --------------------------------------------------------------------------- #
def ln(el):
    return el.tag.rsplit("}", 1)[-1] if isinstance(el.tag, str) else ""


def lattr(el, name):
    for k, v in el.attrib.items():
        if k.rsplit("}", 1)[-1] == name or ":" + name in k:
            return v
    return None


def kid(el, name):
    if el is None:
        return None
    for c in el:
        if ln(c) == name:
            return c
    return None


def kid_all(el, name):
    return [] if el is None else [c for c in el if ln(c) == name]


def txt(el):
    return (el.text or "").strip() if el is not None else ""


def deep(el, name, limit=None):
    """Первое вхождение тега на любой глубине."""
    if el is None:
        return None
    for n, sub in enumerate(el.iter(), start=1):
        if limit and n > limit:
            break
        if ln(sub) == name:
            return sub
    return None


def deep_text(el, name, default=""):
    return txt(deep(el, name)) or default


def first_int(el):
    """Первое целое внутри элемента (для int / ArrayOfInt > int)."""
    if el is None:
        return None
    for sub in el.iter():
        t = (sub.text or "").strip()
        if not t:
            continue
        m = re.match(r"^-?\d+$", t)
        if m:
            return int(t)
        m = re.match(r"^(\d+)\s", t)
        if m:
            return int(m.group(1))
    return None


def bools(el):
    out = []
    for sub in el.iter() if el is not None else []:
        if ln(sub) == "boolean":
            out.append((sub.text or "").strip().lower() == "true")
    return out


def dict_pairs(el):
    """Словарь C# -> список (ключ, element value)."""
    out = []
    if el is None:
        return out
    for item in el:
        if ln(item) != "item":
            continue
        key_el = kid(item, "key")
        val_el = kid(item, "value")
        key = ""
        if key_el is not None:
            for sub in key_el.iter():
                if ln(sub) != "key" and (sub.text or "").strip():
                    key = sub.text.strip()
                    break
        out.append((key, val_el))
    return out


def norm_id(raw):
    """'(O)128' -> '128'; '128' -> '128'."""
    if raw is None:
        return ""
    s = str(raw).strip()
    if s.startswith("("):
        s = s.split(")", 1)[1]
    m = re.match(r"^-?\d+", s)
    return m.group(0) if m else s


def friendship_int(friendship, name):
    """Read an integer friendship field, returning zero for missing/invalid values."""
    value = txt(kid(friendship, name))
    return int(value) if value.lstrip("-").isdigit() else 0


# --------------------------------------------------------------------------- #
#  Разбор сейва + кэш по (abspath, mtime_ns, size)
# --------------------------------------------------------------------------- #
def _file_sig(path: str) -> tuple[str, int, int]:
    ap = os.path.abspath(path)
    try:
        st = os.stat(ap)
    except FileNotFoundError:
        raise SaveError(
            "no_saves",
            f"Файл сохранения не найден: {path}",
            "Файл был перемещён или удалён.",
            [
                "Проверьте путь к папке Saves игры.",
                'Укажите актуальный файл через --save "путь\\к\\сейву".',
            ],
        )
    except PermissionError:
        raise SaveError(
            "permission_denied",
            "Нет прав на чтение файла сохранения",
            f"Операционная система запретила чтение файла: {ap}",
            [
                "Проверьте права доступа к файлу и папке сохранения.",
                "Подождите пару секунд, если игра прямо сейчас записывает сейв, и нажмите «Обновить».",
                "Попробуйте скопировать папку сейва в подпапку saves/ рядом с tracker.py.",
            ],
        )
    except OSError as exc:
        raise SaveError(
            "io_error",
            "Не удалось прочитать файл сохранения",
            f"{ap}: {exc}",
            ["Проверьте доступность диска и целостность файла сохранения."],
        )
    return (ap, st.st_mtime_ns, st.st_size)


def _normalize_weather_code(w: str) -> str:
    wl = (w or "").strip().lower()
    if wl in ("rain", "rainy"):
        return "rainy"
    if wl in ("storm", "lightning", "stormy"):
        return "storm"
    if wl in ("greenrain", "green_rain"):
        return "green_rain"
    if wl in ("wind", "debris", "windy"):
        return "wind"
    if wl in ("snow", "snowy"):
        return "snow"
    if wl in ("sun", "sunny", "festival", "wedding"):
        return "sunny"
    return ""


def parse_save(path):
    sig = _file_sig(path)
    cached = _PARSE_CACHE.get(sig)
    if cached is not None:
        return cached

    try:
        with open(sig[0], "rb") as fh:
            raw_bytes = fh.read()
    except PermissionError:
        raise SaveError(
            "permission_denied",
            "Нет прав на чтение файла сохранения",
            f"Не удалось открыть для чтения: {sig[0]}",
            [
                "Убедитесь, что у текущего пользователя Windows/Linux есть доступ на чтение файла.",
                "Если игра сохраняется прямо в этот момент, подождите 2–3 секунды.",
            ],
        )
    except OSError as exc:
        raise SaveError(
            "io_error",
            "Не удалось прочитать файл сохранения",
            f"{sig[0]}: {exc}",
            ["Проверьте доступность диска и целостность файла сохранения."],
        )

    try:
        root = ET.fromstring(raw_bytes)
    except ET.ParseError as exc:
        raise SaveError(
            "corrupt_save",
            "Файл сохранения не распознан (ошибка XML)",
            f"Файл {sig[0]} не является корректным XML сохранения Stardew Valley ({exc}).",
            [
                "Убедитесь, что выбран основной файл <Ферма>_<ID>, а не другой файл или архив.",
                "Если игра вылетела во время записи, проверьте соседний резервный файл <Ферма>_<ID>_old.",
            ],
        )

    if ln(root) != "SaveGame":
        raise SaveError(
            "corrupt_save",
            "Файл не похож на сохранение Stardew Valley",
            f"Корневой тег документа — <{ln(root)}>, ожидался <SaveGame>.",
            [
                "Выберите файл сохранения вида %APPDATA%\\StardewValley\\Saves\\<Ферма>_<ID>\\<Ферма>_<ID>.",
            ],
        )

    players = kid_all(root, "player")
    # Мультиплеер: дополнительные фермеры могут лежать в farmhands > Farmer
    farmhands_el = deep(root, "farmhands", limit=4000)
    if farmhands_el is not None:
        for fh_el in farmhands_el:
            if ln(fh_el) in ("Farmer", "player") and txt(kid(fh_el, "name")):
                players.append(fh_el)
    if not players:
        players = [root]
    host = players[0]
    warn = []

    def player_dict(name):
        el = kid(host, name)
        return dict_pairs(el)

    def id_set(name):
        out = {}
        for k, v in player_dict(name):
            n = first_int(v) if v is not None else None
            if n is None:
                for sub in v.iter() if v is not None else []:
                    t = (sub.text or "").strip()
                    if re.match(r"^-?\d+$", t):
                        n = int(t)
                        break
            out[norm_id(k)] = n if n is not None else 1
        return out

    # Погода (1.6 locationWeather + 1.5 корневые флаги)
    weather = None
    weather_tomorrow = None
    island_weather = None
    loc_weather = kid(root, "locationWeather")
    if loc_weather is not None:
        for lk, lv in dict_pairs(loc_weather):
            lw = kid(lv, "LocationWeather") if lv is not None else None
            lw = lw if lw is not None else lv
            if lw is None:
                continue
            w_str = txt(kid(lw, "Weather"))
            w_tom = txt(kid(lw, "WeatherForTomorrow"))
            is_r = txt(kid(lw, "IsRaining")).lower() == "true"
            is_l = txt(kid(lw, "IsLightning")).lower() == "true"
            is_gr = txt(kid(lw, "IsGreenRain")).lower() == "true"
            norm_w = (
                "green_rain"
                if is_gr
                else "storm"
                if is_l
                else "rainy"
                if is_r
                else _normalize_weather_code(w_str)
            )
            if lk == "Default" and norm_w:
                weather = norm_w
                weather_tomorrow = _normalize_weather_code(w_tom) or None
            elif lk == "Island" and norm_w:
                island_weather = norm_w

    if weather is None:
        if txt(kid(root, "isGreenRain")).lower() == "true":
            weather = "green_rain"
        elif txt(kid(root, "isLightning")).lower() == "true":
            weather = "storm"
        elif txt(kid(root, "isRaining")).lower() == "true":
            weather = "rainy"
        elif txt(kid(root, "isSnowing")).lower() == "true":
            weather = "snow"
        elif txt(kid(root, "isDebrisWeather")).lower() == "true":
            weather = "wind"
        elif kid(root, "isRaining") is not None:
            weather = "sunny"

    # Навыки и опыт
    skills_levels = {
        "farming": first_int(kid(host, "farmingLevel")) or 0,
        "mining": first_int(kid(host, "miningLevel")) or 0,
        "foraging": first_int(kid(host, "foragingLevel")) or 0,
        "fishing": first_int(kid(host, "fishingLevel")) or 0,
        "combat": first_int(kid(host, "combatLevel")) or 0,
        "luck": first_int(kid(host, "luckLevel")) or 0,
    }
    xp_list = []
    xp_el = kid(host, "experiencePoints")
    if xp_el is not None:
        for sub in xp_el:
            if ln(sub) == "int" and txt(sub).lstrip("-").isdigit():
                xp_list.append(int(txt(sub)))

    # Статистика и истребление монстров (P1-2)
    monsters_killed: dict[str, int] = {}
    stats_values: dict[str, int] = {}
    total_monsters_killed = 0
    stats_el = kid(host, "stats") or kid(root, "stats")
    if stats_el is not None:
        smk = kid(stats_el, "specificMonstersKilled")
        for mk, mv in dict_pairs(smk):
            cnt = first_int(mv) or 0
            if mk and cnt > 0:
                monsters_killed[mk] = monsters_killed.get(mk, 0) + cnt
        vals_el = kid(stats_el, "Values")
        for vk, vv in dict_pairs(vals_el):
            n = first_int(vv)
            if vk and n is not None:
                stats_values[vk] = n
        tmk = first_int(kid(stats_el, "monstersKilled")) or first_int(
            kid(stats_el, "MonstersKilled")
        )
        total_monsters_killed = (
            stats_values.get("monstersKilled") or tmk or sum(monsters_killed.values())
        )

    # Почта / Звёздные капли (Stardrops)
    mail_received = set()
    mail_el = kid(host, "mailReceived")
    if mail_el is not None:
        for sub in mail_el:
            t = txt(sub)
            if t:
                mail_received.add(t)

    mine_chests = set()
    mc_el = kid(host, "chestConsumedMineLevels")
    for mk, mv in dict_pairs(mc_el):
        if mk.isdigit():
            mine_chests.add(int(mk))

    deepest_mine = first_int(kid(host, "deepestMineLevel")) or 0
    if txt(kid(host, "hasSkullKey")).lower() == "true":
        deepest_mine = max(120, deepest_mine)
    max_stamina = first_int(kid(host, "maxStamina")) or 270

    data = {
        "player_count": len(players),
        "name": txt(kid(host, "name")) or deep_text(host, "name", "Фермер"),
        "farm_name": txt(kid(host, "farmName")) or deep_text(host, "farmName", "Ферма"),
        "money": first_int(kid(host, "money")) or 0,
        "total_earned": first_int(kid(host, "totalMoneyEarned")) or 0,
        "day": first_int(kid(host, "dayOfMonth"))
        or first_int(deep(root, "dayOfMonth"))
        or 1,
        "season": (
            txt(kid(host, "currentSeason"))
            or deep_text(root, "currentSeason", "spring")
        ).lower(),
        "year": first_int(kid(host, "year")) or first_int(deep(root, "year")) or 1,
        "time": first_int(kid(host, "timeOfDay"))
        or first_int(deep(root, "timeOfDay"))
        or 600,
        "weather": weather,
        "weather_tomorrow": weather_tomorrow,
        "island_weather": island_weather,
        "fishCaught": id_set("fishCaught"),
        "archaeologyFound": id_set("archaeologyFound"),
        "mineralsFound": id_set("mineralsFound"),
        "basicShipped": id_set("basicShipped"),
        "recipesCooked": id_set("recipesCooked"),
        "craftingRecipes": {
            k: (first_int(v) or 0) for k, v in player_dict("craftingRecipes")
        },
        "cookingRecipes": {
            k: (first_int(v) or 0) for k, v in player_dict("cookingRecipes")
        },
        "friendship": {},
        "museum": {},
        "bundles": {},
        "areasComplete": [],
        "farm_buildings": set(),
        "walnuts": None,
        "perfection_waivers": first_int(deep(root, "perfectionWaivers", limit=5000))
        or 0,
        "skills": skills_levels,
        "xp": xp_list,
        "mastery_xp": stats_values.get("MasteryExp", 0),
        "monsters_killed": monsters_killed,
        "total_monsters_killed": total_monsters_killed,
        "deepest_mine": deepest_mine,
        "mail_received": mail_received,
        "mine_chests": mine_chests,
        "max_stamina": max_stamina,
        "game_version": deep_text(root, "gameVersion", "")
        or deep_text(root, "gameVersionLabel", ""),
    }

    # Дружба
    fdata = kid(host, "friendshipData")
    for key, val in dict_pairs(fdata):
        fr = kid(val, "Friendship") if val is not None else None
        if fr is None:
            fr = val
        if fr is None:
            continue

        status = txt(kid(fr, "Status"))
        roommate = (txt(kid(fr, "RoommateMarriage")) or "").lower() == "true"
        data["friendship"][key] = {
            "points": friendship_int(fr, "Points"),
            "gifts_today": friendship_int(fr, "GiftsToday"),
            "gifts_week": friendship_int(fr, "GiftsThisWeek"),
            "talked": (txt(kid(fr, "TalkedToToday")) or "").lower() == "true",
            "status": status,
            "roommate": roommate,
        }

    # Локации (Музей, Клуб, постройки на Ферме для Перфекции)
    locations = kid(root, "locations")
    for loc in locations if locations is not None else []:
        ltype = lattr(loc, "type") or ""
        lname = txt(kid(loc, "name"))
        if "LibraryMuseum" in ltype or lname == "ArchaeologyHouse":
            for _key, val in dict_pairs(kid(loc, "museumPieces")):
                n = first_int(val)
                if n is not None:
                    data["museum"][str(n)] = 1
                else:
                    s = norm_id(txt(val))
                    if s:
                        data["museum"][s] = 1
        elif "CommunityCenter" in ltype or lname == "CommunityCenter":
            for key, val in dict_pairs(kid(loc, "bundles")):
                if not key.lstrip("-").isdigit():
                    continue
                data["bundles"][int(key)] = bools(val)
            data["areasComplete"] = bools(kid(loc, "areasComplete"))
        elif "Farm" in ltype or lname == "Farm":
            b_el = kid(loc, "buildings")
            for b in b_el if b_el is not None else []:
                btype = txt(kid(b, "buildingType"))
                if btype:
                    data["farm_buildings"].add(btype)

    wal = deep(root, "goldenWalnutsFound")
    if wal is not None and txt(wal).lstrip("-").isdigit():
        data["walnuts"] = int(txt(wal))

    if not data["friendship"]:
        warn.append("Не нашёл friendshipData — раздел «Люди» будет пустым.")
    if not data["fishCaught"]:
        warn.append("Не нашёл fishCaught — рыбалка будет показана как «не поймано».")
    if not data["museum"]:
        warn.append("Музей: не нашёл museumPieces (возможно, ещё ничего не сдано).")
    if not data["bundles"]:
        warn.append("Не нашёл состояние бандлов Community Center.")

    data["warnings"] = warn
    # Ограничиваем размер кэша на случай переключения десятков сейвов
    if len(_PARSE_CACHE) >= 16:
        _PARSE_CACHE.clear()
    _PARSE_CACHE[sig] = data
    return data


# --------------------------------------------------------------------------- #
#  Дата/время
# --------------------------------------------------------------------------- #
def game_clock(t):
    t = int(t or 600)
    h, m = t // 100, t % 100
    return h, m


def fmt_clock(t):
    h, m = game_clock(t)
    return f"{h:02d}:{m:02d}"


def abs_day(season, day, year):
    si = SEASONS.index(season) if season in SEASONS else 0
    return (int(year) - 1) * 4 * 28 + si * 28 + (int(day) - 1)


def days_until_birthday(cur_abs, season, day):
    if season not in SEASONS:
        return None
    target = (abs_day(season, day, 1)) % (4 * 28)
    return (target - (cur_abs % (4 * 28))) % (4 * 28)


def _time_matches(tspan: str, cur_minutes: int) -> tuple[bool, bool]:
    """Возвращает (ловится_сейчас_по_часам, ловится_позже_сегодня). Поддерживает 1 и 2 окна."""
    if not tspan:
        return True, False
    nums = [int(x) for x in tspan.split() if x.isdigit()]
    if len(nums) < 2:
        return True, False
    now_ok = False
    later_ok = False
    for i in range(0, len(nums) - 1, 2):
        a, b = nums[i], nums[i + 1]
        am, bm = (a // 100) * 60 + a % 100, (b // 100) * 60 + b % 100
        if am <= bm:
            if am <= cur_minutes <= bm:
                now_ok = True
            elif cur_minutes < am:
                later_ok = True
        else:
            if cur_minutes >= am or cur_minutes <= bm:
                now_ok = True
            elif cur_minutes < am:
                later_ok = True
    return now_ok, (later_ok and not now_ok)


def _weather_matches(fish_weather: str, save_weather: str) -> bool:
    if not save_weather or not fish_weather or fish_weather in ("both", "all"):
        return True
    is_wet = save_weather in ("rainy", "storm", "green_rain")
    if fish_weather == "rainy":
        return is_wet
    if fish_weather == "sunny":
        return not is_wet
    return True


# --------------------------------------------------------------------------- #
#  Сборка состояния
# --------------------------------------------------------------------------- #
def load_json(name):
    if name not in _STATIC_DATA_CACHE_NAMES or name not in _STATIC_CACHE:
        p = os.path.join(DATA_DIR, name)
        if not os.path.exists(p):
            return {}
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
        if name in _STATIC_DATA_CACHE_NAMES:
            _STATIC_CACHE[name] = data
        return data
    return _STATIC_CACHE[name]


_STATIC_DATA_CACHE_NAMES = {
    "items.json",
    "big_craftables.json",
    "fish.json",
    "museum.json",
    "artifact_locations.json",
    "recipes.json",
    "npcs.json",
    "bundles.json",
    "shipping.json",
    "monsters.json",
    "misc.json",
}


def default_goals():
    return {"goals": [], "tasks": []}


def normalize_goals(value):
    """Validate user-authored goals data while keeping the legacy two-key format."""
    if not isinstance(value, dict):
        return default_goals()
    result = {
        "goals": [item for item in value.get("goals", []) if isinstance(item, dict)]
        if isinstance(value.get("goals", []), list)
        else [],
        "tasks": [item for item in value.get("tasks", []) if isinstance(item, dict)]
        if isinstance(value.get("tasks", []), list)
        else [],
    }
    annotations = value.get("annotations")
    if isinstance(annotations, dict):
        clean_annotations = {}
        for key, item in annotations.items():
            if not isinstance(item, dict):
                continue
            marked = bool(item.get("marked"))
            note = str(item.get("note") or "").strip()[:280]
            if marked or note:
                clean_annotations[str(key)] = {"marked": marked, "note": note}
        result["annotations"] = clean_annotations
    return result


def load_goals():
    """Load user data, falling back to the previous atomic-write backup when needed."""
    for path in (GOALS_FILE, GOALS_FILE + ".bak"):
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                goals = json.load(fh)
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(goals, dict):
            continue
        return normalize_goals(goals)
    return default_goals()


def save_goals(g):
    """Атомарная запись goals.json с автоматическим бэкапом goals.json.bak (P1-6)."""
    clean = normalize_goals(g)
    if os.path.exists(GOALS_FILE):
        try:
            shutil.copy2(GOALS_FILE, GOALS_FILE + ".bak")
        except OSError as exc:
            print(
                f"Предупреждение: не удалось обновить резервную копию goals.json: {exc}",
                file=sys.stderr,
            )
    tmp = GOALS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(clean, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, GOALS_FILE)


def list_saves_info(saves_dir=None, explicit=None):
    """Список всех найденных сохранений с краткой сводкой для переключателя в шапке (P1-3)."""
    paths = find_saves(saves_dir=saves_dir, explicit=explicit)
    out = []
    for p in paths:
        try:
            raw = parse_save(p)
            mtime = int(os.path.getmtime(p))
            out.append(
                {
                    "path": p,
                    "name": os.path.basename(os.path.dirname(p)) or os.path.basename(p),
                    "farm": raw["farm_name"],
                    "farmer": raw["name"],
                    "season": raw["season"],
                    "season_ru": SEASON_RU.get(raw["season"], raw["season"]),
                    "day": raw["day"],
                    "year": raw["year"],
                    "money": raw["money"],
                    "mtime": mtime,
                    "mtime_str": time.strftime(
                        "%Y-%m-%d %H:%M:%S", time.localtime(mtime)
                    ),
                }
            )
        except (SaveError, OSError):
            # A save may be removed or locked between discovery and stat/read.
            continue
    return out


def build_state(save_path=None, saves_dir=None):
    paths = find_saves(saves_dir=saves_dir, explicit=save_path)
    if not paths:
        raise SaveError(
            "no_saves",
            "Не нашёл ни одного файла сохранения",
            "В стандартных папках Stardew Valley и папке ./saves сохранения не обнаружены.",
            [
                'Укажите путь вручную: python tracker.py serve --save "путь\\к\\сейву"',
                "В Windows сейвы обычно лежат в %APPDATA%\\StardewValley\\Saves\\<Ферма>_<id>\\<Ферма>_<id>",
                "Для демо-проверки можно создать тестовый сейв: python tests/make_test_save.py saves",
            ],
        )
    sp = paths[0]
    sig = _file_sig(sp)

    # Быстрый возврат из кэша (P1-4): если файл сейва не менялся, не пересобираем коллекции
    cached_state = _STATE_CACHE.get(sig)
    if cached_state is not None:
        state_copy = dict(cached_state)
        state_copy["meta"] = dict(cached_state["meta"])
        state_copy["meta"]["saves_found"] = len(paths)
        state_copy["goals"] = load_goals()
        return state_copy

    items = load_json("items.json")
    fish = load_json("fish.json")
    museum = load_json("museum.json")
    artifact_locations = load_json("artifact_locations.json")
    recipes = load_json("recipes.json")
    npcs = load_json("npcs.json")
    bundles = load_json("bundles.json")
    shipping = load_json("shipping.json")
    monsters_cfg = load_json("monsters.json").get("goals") or []

    raw = parse_save(sp)

    def item_info(uid):
        it = items.get(str(uid), {})
        return {
            "id": str(uid),
            "ru": it.get("ru") or it.get("en") or f"#{uid}",
            "en": it.get("en") or it.get("ru") or f"#{uid}",
            "sp": it.get("sp"),
            "grp": it.get("grp", "other"),
            "seasons": it.get("seasons") or [],
            "price": it.get("p", 0),
        }

    cur_abs = abs_day(raw["season"], raw["day"], raw["year"])

    def item_row(uid, done, extra=None):
        it = items.get(str(uid), {})
        row = {
            "id": str(uid),
            "ru": it.get("ru") or it.get("en") or f"#{uid}",
            "en": it.get("en") or it.get("ru") or f"#{uid}",
            "type": it.get("t", ""),
            "grp": it.get("grp", "other"),
            "price": it.get("p", 0),
            "sp": it.get("sp"),
            "seasons": it.get("seasons") or [],
            "done": bool(done),
        }
        if extra:
            row.update(extra)
        return row

    # ---- рыба
    season_now = raw["season"]
    hour_now, minute_now = game_clock(raw["time"])
    cur_minutes = hour_now * 60 + minute_now
    save_weather = raw["weather"]
    fish_rows = []
    for uid, info in fish.items():
        caught = raw["fishCaught"].get(uid, 0) or 0
        seasons = [s for s in (info.get("season") or "").split() if s in SEASONS]
        tspan = info.get("time") or ""
        w_req = info.get("weather") or "both"
        is_trap = bool(info.get("trap"))
        in_season = (
            (season_now in seasons)
            or (not seasons)
            or ("all" in (info.get("season") or ""))
        )
        time_ok, later_today = _time_matches(tspan, cur_minutes)
        weather_ok = _weather_matches(w_req, save_weather)
        now_ok = bool(in_season and time_ok and weather_ok)
        later_ok = bool(in_season and later_today and weather_ok)
        fish_rows.append(
            item_row(
                uid,
                caught > 0,
                {
                    "count": caught,
                    "seasons": seasons,
                    "time": tspan,
                    "weather": w_req,
                    "diff": info.get("diff"),
                    "size": info.get("size") or [],
                    "beh": info.get("beh", ""),
                    "trap": is_trap,
                    "water": info.get("water", ""),
                    "locs": info.get("loc") or [],
                    "in_season": in_season,
                    "weather_ok": weather_ok,
                    "later_today": later_ok,
                    "now": now_ok,
                },
            )
        )
    fish_rows.sort(
        key=lambda r: (r["done"], not r["now"], not r["in_season"], r["ru"].lower())
    )

    # ---- музей
    museum_rows = []
    for uid in museum["artifacts"]:
        found = uid in raw["archaeologyFound"]
        museum_rows.append(
            item_row(
                uid,
                uid in raw["museum"],
                {
                    "kind": "artifact",
                    "found": found,
                    "donated": uid in raw["museum"],
                    "locations": artifact_locations.get(uid, {}),
                },
            )
        )
    for uid in museum["minerals"]:
        found = uid in raw["mineralsFound"]
        museum_rows.append(
            item_row(
                uid,
                uid in raw["museum"],
                {"kind": "mineral", "found": found, "donated": uid in raw["museum"]},
            )
        )
    museum_rows.sort(key=lambda r: (r["donated"], not r["found"], r["ru"].lower()))

    # ---- отправка
    ship_rows = []
    for uid in shipping:
        cnt = raw["basicShipped"].get(norm_id(uid), 0) or 0
        it_seasons = items.get(str(uid), {}).get("seasons") or []
        ship_rows.append(
            item_row(
                uid,
                cnt > 0,
                {
                    "count": cnt,
                    "in_season": season_now in it_seasons if it_seasons else False,
                },
            )
        )
    ship_rows.sort(key=lambda r: (r["done"], not r["in_season"], r["ru"].lower()))

    # ---- готовка (3 статуса: приготовлено / изучено / не изучено)
    cook_rows = []
    for rname, rec in recipes["cooking"].items():
        uid = str(rec.get("item", ""))
        cnt = raw["recipesCooked"].get(uid, 0) or 0
        known = (
            (rname in raw["cookingRecipes"])
            or (rec.get("unlock") == "default")
            or (cnt > 0)
        )
        uinfo = rec.get("unlock_info") or {}
        cook_rows.append(
            {
                "id": uid or rname,
                "ru": rec.get("ru") or rname,
                "en": rec.get("en") or rname,
                "sp": rec.get("sp") or items.get(uid, {}).get("sp"),
                "price": rec.get("price") or items.get(uid, {}).get("p", 0),
                "done": cnt > 0,
                "known": known,
                "count": cnt,
                "ing": rec.get("ing") or [],
                "unlock": uinfo.get("ru") or (rec.get("unlock") or ""),
                "unlock_ru": uinfo.get("ru") or "",
                "unlock_en": uinfo.get("en") or "",
            }
        )
    cook_rows.sort(key=lambda r: (r["done"], not r["known"], r["ru"].lower()))

    # ---- крафт (3 статуса: скрафчено / изучено / не изучено)
    craft_rows = []
    unmatched = []
    for rname, rec in recipes["crafting"].items():
        alt_name = "Oil of Garlic" if rname == "Oil Of Garlic" else rname
        in_save = (rname in raw["craftingRecipes"]) or (
            alt_name in raw["craftingRecipes"]
        )
        cnt = raw["craftingRecipes"].get(rname, raw["craftingRecipes"].get(alt_name, 0))
        if not in_save:
            unmatched.append(rname)
        known = in_save or (rec.get("unlock") == "default") or (cnt > 0)
        uinfo = rec.get("unlock_info") or {}
        craft_rows.append(
            {
                "id": str(rec.get("item", "")) or rname,
                "ru": rec.get("name_ru") or rec.get("ru") or rname,
                "en": rec.get("name_en") or rec.get("en") or rname,
                "rec_en": rname,
                "sp": rec.get("sp"),
                "big": bool(rec.get("big")),
                "qty": rec.get("qty", 1),
                "done": cnt > 0,
                "known": known,
                "count": cnt,
                "ing": rec.get("ing") or [],
                "unlock_ru": uinfo.get("ru") or "",
                "unlock_en": uinfo.get("en") or "",
            }
        )
    craft_rows.sort(key=lambda r: (r["done"], not r["known"], r["ru"].lower()))

    # ---- люди
    people = []
    npc_data = npcs["npcs"]
    for key, info in npc_data.items():
        fr = raw["friendship"].get(key, {})
        points = fr.get("points", 0)
        is_married = fr.get("status") == "Married"
        max_h = 14 if is_married else 10
        hearts = min(points // 250, max_h)
        is_rom = bool(info.get("romance"))
        perf_target_pts = 2000 if is_rom else 2500
        perf_done = points >= perf_target_pts
        b_season = str(info["birth"][0] or "").lower()
        du = days_until_birthday(cur_abs, b_season, info["birth"][1])
        people.append(
            {
                "key": key,
                "p_idx": info.get("p_idx", 0),
                "ru": info.get("ru") or key,
                "en": info.get("en") or key,
                "birth": [b_season, info["birth"][1]],
                "until": du,
                "hearts": hearts,
                "max_hearts": max_h,
                "perf_hearts": 8 if is_rom else 10,
                "perf_done": perf_done,
                "points": points,
                "romance": is_rom,
                "status": fr.get("status", ""),
                "roommate": fr.get("roommate", False),
                "gifts_week": fr.get("gifts_week", 0),
                "gifts_today": fr.get("gifts_today", 0),
                "talked": fr.get("talked", False),
                "loved": [item_info(i) for i in info.get("love", [])][:12],
                "liked": [item_info(i) for i in info.get("like", [])][:10],
                "hated": [item_info(i) for i in info.get("hate", [])][:8],
                "met": bool(fr),
            }
        )
    people.sort(
        key=lambda p: (p["until"] if p["until"] is not None else 999, -p["hearts"])
    )

    # ---- бандлы
    bundle_rooms = []
    for room in bundles["rooms"]:
        rlist = []
        for b in room["list"]:
            have = raw["bundles"].get(b["slot"]) or []
            done = sum(1 for x in have if x)
            need = max(1, int(b.get("need_count") or len(b["items"])))
            rlist.append(
                {
                    "slot": b["slot"],
                    "color": b.get("color", 0),
                    "ru": b.get("name_ru") or b["name_en"],
                    "en": b["name_en"],
                    "need": need,
                    "have": min(done, need),
                    "complete": done >= need,
                    "items": [
                        {
                            "id": i.get("id", ""),
                            "ru": i["ru"],
                            "en": i["en"],
                            "qty": i["qty"],
                            "qual": i.get("qual", 0),
                            "sp": i.get("sp"),
                            "seasons": i.get("seasons") or [],
                            "have": bool(have[idx]) if idx < len(have) else False,
                        }
                        for idx, i in enumerate(b["items"])
                    ],
                    "reward": b.get("reward"),
                }
            )
        bundle_rooms.append(
            {
                "key": room["key"],
                "ru": room["ru"],
                "en": room["en"],
                "list": rlist,
                "done": sum(1 for b in rlist if b["complete"]),
                "total": len(rlist),
            }
        )

    # ---- монстры / Гильдия авантюристов (P1-2)
    monster_rows = []
    for mg in monsters_cfg:
        species_counts = []
        killed_sum = 0
        for mname in mg["monsters"]:
            c = raw["monsters_killed"].get(mname, 0)
            killed_sum += c
            if c > 0:
                species_counts.append([mname, c])
        target = int(mg["target"])
        monster_rows.append(
            {
                "idx": mg["idx"],
                "key": mg["key"],
                "ru": mg["ru"],
                "en": mg["en"],
                "killed": killed_sum,
                "target": target,
                "done": killed_sum >= target,
                "where_ru": mg.get("where_ru", ""),
                "where_en": mg.get("where_en", ""),
                "reward": mg.get("reward"),
                "species": species_counts,
            }
        )
    monsters_done = sum(1 for m in monster_rows if m["done"])
    monsters_state = {
        "goals": monster_rows,
        "completed": [monsters_done, len(monster_rows)],
        "slayer_hero": len(monster_rows) > 0 and monsters_done >= len(monster_rows),
        "total_killed": raw["total_monsters_killed"],
        "deepest_mine": min(raw["deepest_mine"], 120),
        "skull_cavern": max(0, raw["deepest_mine"] - 120),
    }

    # ---- навыки и мастерство
    skill_defs = [
        ("farming", "Фермерство", "Farming", 16, 0),
        ("mining", "Горное дело", "Mining", 17, 3),
        ("foraging", "Собирательство", "Foraging", 18, 2),
        ("fishing", "Рыбная ловля", "Fishing", 19, 1),
        ("combat", "Боевые навыки", "Combat", 20, 4),
    ]
    skills_list = []
    for sk_key, sk_ru, sk_en, ui_idx, xp_idx in skill_defs:
        lvl = raw["skills"].get(sk_key, 0)
        xp = raw["xp"][xp_idx] if xp_idx < len(raw["xp"]) else 0
        skills_list.append(
            {
                "key": sk_key,
                "ru": sk_ru,
                "en": sk_en,
                "level": lvl,
                "xp": xp,
                "ui_idx": ui_idx,
            }
        )
    farmer_pt_level = (
        sum(s["level"] for s in skills_list) + raw["skills"].get("luck", 0)
    ) // 2
    farmer_pt_level = min(25, max(0, farmer_pt_level))

    # ---- Звёздные капли (Stardrops)
    stardrop_rows = []
    for sd_key, sd_ru, sd_en in STARDROPS:
        got = (sd_key in raw["mail_received"]) or (
            sd_key == "CF_Mines" and 100 in raw["mine_chests"]
        )
        stardrop_rows.append({"key": sd_key, "ru": sd_ru, "en": sd_en, "done": got})
    stardrops_done = sum(1 for s in stardrop_rows if s["done"])
    all_stardrops = (stardrops_done >= len(stardrop_rows)) or (
        "gotMaxStamina" in raw["mail_received"]
    )

    # ---- Перфекция (P1-1: точная формула Utility.percentGameComplete из Stardew Valley 1.6)
    counts = {
        "fish": [sum(1 for r in fish_rows if r["done"]), len(fish_rows)],
        "museum": [sum(1 for r in museum_rows if r["donated"]), len(museum_rows)],
        "museum_found": [
            sum(1 for r in museum_rows if r["found"] or r["donated"]),
            len(museum_rows),
        ],
        "shipped": [sum(1 for r in ship_rows if r["done"]), len(ship_rows)],
        "cooking": [sum(1 for r in cook_rows if r["done"]), len(cook_rows)],
        "crafting": [sum(1 for r in craft_rows if r["done"]), len(craft_rows)],
        "monsters": [monsters_done, len(monster_rows)],
    }
    hearts_total = sum(min(p["hearts"], 10) for p in people)
    counts["hearts"] = [hearts_total, len(people) * 10]
    counts["money"] = [raw["money"], 0]
    walnuts_have = max(0, int(raw["walnuts"] or 0))
    counts["walnuts"] = [walnuts_have, 130]

    # В одиночной игре Wedding Ring не требуется для Перфекции (149 вместо 150)
    is_mp = raw["player_count"] > 1
    craft_perf_rows = (
        craft_rows
        if is_mp
        else [r for r in craft_rows if r["rec_en"] != "Wedding Ring"]
    )
    craft_perf_done = sum(1 for r in craft_perf_rows if r["done"])
    craft_perf_total = max(1, len(craft_perf_rows))

    great_friends_done = sum(1 for p in people if p["perf_done"])
    great_friends_total = max(1, len(people))

    obelisk_rows = [
        {"key": ob_k, "ru": ob_ru, "en": ob_en, "done": ob_k in raw["farm_buildings"]}
        for ob_k, ob_ru, ob_en in OBELISKS
    ]
    num_obelisks = sum(1 for o in obelisk_rows if o["done"])
    has_gold_clock = "Gold Clock" in raw["farm_buildings"]

    def _frac(a, b):
        return min(1.0, max(0.0, a / b)) if b else 0.0

    perf_categories = [
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
            "have": monsters_done,
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
            "have": farmer_pt_level,
            "total": 25,
            "weight": 5,
            "earned": round(5.0 * _frac(farmer_pt_level, 25), 2),
            "done": farmer_pt_level >= 25,
            "go": "perfection",
            "sp": [1, 96],
        },
        {
            "key": "stardrops",
            "ru": "Все звёздные капли",
            "en": "Found All Stardrops",
            "have": 7 if all_stardrops else stardrops_done,
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
            "have": min(walnuts_have, 130),
            "total": 130,
            "weight": 5,
            "earned": round(5.0 * _frac(min(walnuts_have, 130), 130), 2),
            "done": walnuts_have >= 130,
            "go": "perfection",
            "sp": [0, 73],
        },
    ]

    raw_perf_pct = (
        num_obelisks
        + (10.0 if has_gold_clock else 0.0)
        + (10.0 if monsters_state["slayer_hero"] else 0.0)
        + (10.0 if all_stardrops else 0.0)
        + 15.0 * _frac(*counts["shipped"])
        + 11.0 * _frac(great_friends_done, great_friends_total)
        + 10.0 * _frac(*counts["cooking"])
        + 10.0 * _frac(craft_perf_done, craft_perf_total)
        + 10.0 * _frac(*counts["fish"])
        + 5.0 * _frac(min(walnuts_have, 130), 130)
        + 5.0 * _frac(farmer_pt_level, 25)
    )
    waivers = raw["perfection_waivers"]
    adj_perf_pct = min(100.0, raw_perf_pct + waivers)

    perfection_state = {
        "pct": round(adj_perf_pct, 1),
        "raw_pct": round(raw_perf_pct, 1),
        "walnut_room_pct": int(raw_perf_pct),
        "waivers": waivers,
        "categories": perf_categories,
        "obelisks": obelisk_rows,
        "gold_clock": has_gold_clock,
        "stardrops": stardrop_rows,
    }
    counts["perfection"] = [round(adj_perf_pct, 1), 100]

    # ---- Раздел «Сегодня» (P1-5)
    need_museum = [r for r in museum_rows if r["found"] and not r["donated"]]
    herbs = [p for p in people if p["until"] is not None and p["until"] <= 7]

    close_bundles = []
    for room in bundle_rooms:
        for b in room["list"]:
            rem = b["need"] - b["have"]
            if not b["complete"] and 1 <= rem <= 2:
                missing_items = [it for it in b["items"] if not it["have"]]
                close_bundles.append(
                    {
                        "room_ru": room["ru"],
                        "room_en": room["en"],
                        "slot": b["slot"],
                        "color": b["color"],
                        "ru": b["ru"],
                        "en": b["en"],
                        "have": b["have"],
                        "need": b["need"],
                        "left": rem,
                        "missing": missing_items[:6],
                        "reward": b["reward"],
                    }
                )
    close_bundles.sort(key=lambda b: (b["left"], b["slot"]))

    today_state = {
        "birthdays_today": [p for p in herbs if p["until"] == 0],
        "birthdays_soon": [p for p in herbs if p["until"] and p["until"] > 0],
        "donate_museum": need_museum,
        "fish_now": [r for r in fish_rows if not r["done"] and r["now"]],
        "fish_later": [r for r in fish_rows if not r["done"] and r["later_today"]],
        "bundles_close": close_bundles,
        "ready_cook": [r for r in cook_rows if r["known"] and not r["done"]][:16],
        "ready_craft": [r for r in craft_rows if r["known"] and not r["done"]][:16],
        "ship_season": [r for r in ship_rows if not r["done"] and r["in_season"]][:18],
    }
    save_mtime = sig[1] // 1_000_000_000

    state = {
        "meta": {
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
            "save_path": sp,
            "save_name": os.path.basename(os.path.dirname(sp)) or os.path.basename(sp),
            "save_mtime": save_mtime,
            "mtime_str": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(save_mtime)),
            "game_version": raw["game_version"],
            "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "warnings": raw["warnings"],
            "saves_found": len(paths),
        },
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
            "farmer_level": farmer_pt_level,
            "mastery_xp": raw["mastery_xp"],
        },
        "perfection": perfection_state,
        "today": today_state,
        "alerts": {
            "museum_found_not_donated": [
                {"id": r["id"], "ru": r["ru"], "en": r["en"], "sp": r["sp"]}
                for r in need_museum
            ],
            "birthdays_week": [
                {
                    "key": p["key"],
                    "p_idx": p["p_idx"],
                    "ru": p["ru"],
                    "en": p["en"],
                    "until": p["until"],
                    "birth": p["birth"],
                }
                for p in herbs
            ],
            "unmatched_craft": len(unmatched),
        },
        "goals": load_goals(),
    }

    if len(_STATE_CACHE) >= 8:
        _STATE_CACHE.clear()
    _STATE_CACHE[sig] = state

    out_copy = dict(state)
    out_copy["goals"] = load_goals()
    return out_copy


# --------------------------------------------------------------------------- #
#  Рендер HTML (с поддержкой встраивания спрайтов для автономного report.html)
# --------------------------------------------------------------------------- #
def _inline_sprites_css() -> str:
    rules = []
    var_map = {
        "objects.png": "--spr-obj0",
        "objects2.png": "--spr-obj1",
        "craftables.png": "--spr-bc",
        "bundles.png": "--spr-bundles",
        "npcs.png": "--spr-npcs",
        "monsters.png": "--spr-monsters",
        "ui.png": "--spr-ui",
    }
    for fname, css_var in var_map.items():
        if fname not in _SPRITE_B64_CACHE:
            fp = os.path.join(SPRITES_DIR, fname)
            if os.path.isfile(fp):
                with open(fp, "rb") as fh:
                    _SPRITE_B64_CACHE[fname] = base64.b64encode(fh.read()).decode(
                        "ascii"
                    )
            else:
                _SPRITE_B64_CACHE[fname] = ""
        b64 = _SPRITE_B64_CACHE[fname]
        if b64:
            rules.append(f"{css_var}:url('data:image/png;base64,{b64}');")
    if not rules:
        return ""
    return ":root{" + "".join(rules) + "}"


def render(state, mode="live", error=None):
    with open(TEMPLATE, encoding="utf-8") as fh:
        tpl = fh.read()
    blob = json.dumps(state, ensure_ascii=False).replace("</", "<\\/")
    err_blob = json.dumps(error, ensure_ascii=False).replace("</", "<\\/")
    html = re.sub(r"/\*__STATE__\*/\s*null", lambda _match: blob, tpl)
    html = re.sub(r"/\*__ERROR__\*/\s*null", lambda _match: err_blob, html)
    html = re.sub(
        r"/\*__MODE_VALUE__\*/\s*\"live\"",
        lambda _match: json.dumps(mode),
        html,
    )
    if mode == "static":
        inline_css = _inline_sprites_css()
        if inline_css:
            html = html.replace("/*__INLINE_SPRITES__*/", inline_css)
    return html


def build_report(save=None, saves_dir=None, out_path=None):
    state = build_state(save, saves_dir)
    html = render(state, "static")
    target = out_path or REPORT
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(html)
    return state, target


# --------------------------------------------------------------------------- #
#  HTTP-сервер
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    state = None
    error = None
    save = None
    saves_dir = None
    lock = threading.Lock()

    def log_message(self, fmt, *args):
        pass

    def _send(
        self, code, body, ctype="application/json; charset=utf-8", extra_headers=None
    ):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header(
            "Cache-Control",
            extra_headers.get("Cache-Control", "no-store")
            if extra_headers
            else "no-store",
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        if extra_headers:
            for hk, hv in extra_headers.items():
                if hk != "Cache-Control":
                    self.send_header(hk, hv)
        self.end_headers()
        try:
            self.wfile.write(data)
        except BrokenPipeError:
            pass

    def do_OPTIONS(self):
        # The dashboard is same-origin; do not grant arbitrary websites CORS access to local saves.
        self.send_response(204)
        self.send_header("Allow", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        parsed_url = urlsplit(self.path)
        path = parsed_url.path
        query = parse_qs(parsed_url.query)
        requested_save = (query.get("save") or [""])[0]
        if requested_save and path in ("/", "/index.html", "/api/state"):
            allowed = {
                os.path.abspath(p) for p in find_saves(saves_dir=Handler.saves_dir)
            }
            if Handler.save:
                allowed.add(os.path.abspath(Handler.save))
                parent = os.path.dirname(os.path.dirname(os.path.abspath(Handler.save)))
                if os.path.isdir(parent):
                    allowed.update(
                        os.path.abspath(p) for p in find_saves(saves_dir=parent)
                    )
            target = os.path.abspath(requested_save)
            if target in allowed:
                try:
                    with self.lock:
                        Handler.save = target
                        Handler.state = build_state(target, None)
                        Handler.error = None
                except SaveError as exc:
                    with self.lock:
                        Handler.error = exc.to_dict()
        if path in ("/", "/index.html"):
            with self.lock:
                state, err = Handler.state, Handler.error
            try:
                self._send(
                    200, render(state, "live", error=err), "text/html; charset=utf-8"
                )
            except FileNotFoundError:
                self._send(
                    500, "Нет файла assets/dashboard.html", "text/plain; charset=utf-8"
                )
        elif path.startswith("/assets/sprites/"):
            fname = os.path.basename(path)
            fp = os.path.join(SPRITES_DIR, fname)
            if fname in SPRITE_FILES and os.path.isfile(fp):
                with open(fp, "rb") as fh:
                    raw_png = fh.read()
                self._send(
                    200,
                    raw_png,
                    "image/png",
                    {"Cache-Control": "public, max-age=86400"},
                )
            else:
                self._send(404, b"not found", "text/plain; charset=utf-8")
        elif path == "/api/state":
            with self.lock:
                if Handler.state is not None:
                    Handler.state["goals"] = load_goals()
                    self._send(200, json.dumps(Handler.state, ensure_ascii=False))
                else:
                    self._send(
                        404,
                        json.dumps(
                            {"error": Handler.error or {"title": "Сейв не загружен"}},
                            ensure_ascii=False,
                        ),
                    )
        elif path == "/api/saves":
            try:
                saves = list_saves_info(
                    saves_dir=Handler.saves_dir,
                    explicit=None if Handler.saves_dir else Handler.save,
                )
                # Если save задан явно, но рядом в папке Saves есть и другие сейвы — покажем все
                if Handler.save and not Handler.saves_dir:
                    parent = os.path.dirname(
                        os.path.dirname(os.path.abspath(Handler.save))
                    )
                    if os.path.isdir(parent):
                        extra = list_saves_info(saves_dir=parent)
                        seen = {s["path"] for s in saves}
                        for es in extra:
                            if es["path"] not in seen:
                                saves.append(es)
                active = (
                    Handler.state["meta"]["save_path"]
                    if Handler.state
                    else (Handler.save or "")
                )
                self._send(
                    200,
                    json.dumps({"saves": saves, "active": active}, ensure_ascii=False),
                )
            except SaveError as exc:
                self._send(
                    200,
                    json.dumps(
                        {"saves": [], "active": "", "error": exc.to_dict()},
                        ensure_ascii=False,
                    ),
                )
        elif path == "/api/goals/export":
            goals_blob = json.dumps(load_goals(), ensure_ascii=False, indent=2)
            self._send(
                200,
                goals_blob,
                "application/json; charset=utf-8",
                {"Content-Disposition": 'attachment; filename="stardew-goals.json"'},
            )
        elif path == "/api/refresh":
            try:
                with self.lock:
                    _PARSE_CACHE.clear()
                    _STATE_CACHE.clear()
                    Handler.state = build_state(Handler.save, Handler.saves_dir)
                    Handler.error = None
                self._send(200, json.dumps(Handler.state, ensure_ascii=False))
            except SaveError as exc:
                with self.lock:
                    Handler.error = exc.to_dict()
                self._send(
                    500, json.dumps({"error": exc.to_dict()}, ensure_ascii=False)
                )
            except Exception as exc:  # noqa: BLE001
                self._send(
                    500,
                    json.dumps(
                        {"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False
                    ),
                )
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        path = urlsplit(self.path).path
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._send(400, json.dumps({"error": "Некорректный Content-Length"}))
            return
        if length < 0:
            self._send(400, json.dumps({"error": "Некорректный размер запроса"}))
            return
        if length > 1_000_000:
            self._send(413, json.dumps({"error": "Слишком большой запрос; лимит 1 МБ"}))
            return
        if (
            length
            and "application/json" not in self.headers.get("Content-Type", "").lower()
        ):
            self._send(
                415, json.dumps({"error": "Ожидался Content-Type: application/json"})
            )
            return
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, UnicodeDecodeError) as exc:
            self._send(
                400,
                json.dumps({"error": f"Некорректный JSON: {exc}"}, ensure_ascii=False),
            )
            return
        if not isinstance(payload, dict):
            self._send(
                400,
                json.dumps(
                    {"error": "JSON запроса должен быть объектом"}, ensure_ascii=False
                ),
            )
            return

        if path == "/api/goals":
            if not isinstance(payload.get("goals", []), list) or not isinstance(
                payload.get("tasks", []), list
            ):
                self._send(
                    400,
                    json.dumps(
                        {"error": "goals и tasks должны быть массивами"},
                        ensure_ascii=False,
                    ),
                )
                return
            if not all(
                isinstance(item, dict)
                for item in payload.get("goals", []) + payload.get("tasks", [])
            ):
                self._send(
                    400,
                    json.dumps(
                        {"error": "Элементы goals и tasks должны быть объектами"},
                        ensure_ascii=False,
                    ),
                )
                return
            if "annotations" in payload and not isinstance(
                payload["annotations"], dict
            ):
                self._send(
                    400,
                    json.dumps({"error": "annotations должен быть объектом"}),
                )
                return
            try:
                goals = normalize_goals(
                    {
                        "goals": payload.get("goals", []),
                        "tasks": payload.get("tasks", []),
                        "annotations": payload.get(
                            "annotations", load_goals().get("annotations", {})
                        ),
                    }
                )
                with _GOALS_LOCK:
                    save_goals(goals)
                    with self.lock:
                        if Handler.state is not None:
                            Handler.state["goals"] = goals
                self._send(
                    200, json.dumps({"ok": True, "goals": goals}, ensure_ascii=False)
                )
            except Exception as exc:  # noqa: BLE001
                self._send(400, json.dumps({"error": str(exc)}))
        elif path == "/api/saves/select":
            req_path = str(payload.get("path") or "").strip()
            if not req_path:
                self._send(400, json.dumps({"error": "Не указан путь к сейву"}))
                return
            # Разрешаем переключение только на реальные файлы сейвов из доступных папок
            allowed = set(find_saves(saves_dir=Handler.saves_dir))
            if Handler.save:
                allowed.add(os.path.abspath(Handler.save))
                parent = os.path.dirname(os.path.dirname(os.path.abspath(Handler.save)))
                if os.path.isdir(parent):
                    allowed.update(
                        os.path.abspath(p) for p in find_saves(saves_dir=parent)
                    )
            allowed_abs = {os.path.abspath(p) for p in allowed}
            target_abs = os.path.abspath(req_path)
            if target_abs not in allowed_abs:
                self._send(
                    403,
                    json.dumps(
                        {"error": "Недопустимый файл сохранения"}, ensure_ascii=False
                    ),
                )
                return
            try:
                with self.lock:
                    Handler.save = target_abs
                    Handler.state = build_state(Handler.save, None)
                    Handler.error = None
                self._send(200, json.dumps(Handler.state, ensure_ascii=False))
            except SaveError as exc:
                self._send(
                    400, json.dumps({"error": exc.to_dict()}, ensure_ascii=False)
                )
        else:
            self._send(404, json.dumps({"error": "not found"}))


def watch_loop(stop, interval=2.0):
    last_sig = None
    while not stop.is_set():
        try:
            with Handler.lock:
                cur_save, cur_dir = Handler.save, Handler.saves_dir
            paths = find_saves(saves_dir=cur_dir, explicit=cur_save)
            if paths:
                sp = paths[0]
                st = os.stat(sp)
                sig = (os.path.abspath(sp), st.st_mtime_ns, st.st_size)
                if sig != last_sig:
                    last_sig = sig
                    new_state = build_state(cur_save, cur_dir)
                    with Handler.lock:
                        Handler.state = new_state
                        Handler.error = None
                    print(
                        f"[{time.strftime('%H:%M:%S')}] сейв обновлён -> состояние пересобрано"
                    )
        except Exception as exc:  # noqa: BLE001
            print("watch:", exc)
        stop.wait(interval)


def serve(port=8777, save=None, saves_dir=None, open_browser=True, watch=True):
    Handler.save, Handler.saves_dir = save, saves_dir
    try:
        Handler.state = build_state(save, saves_dir)
        Handler.error = None
        m = Handler.state["meta"]
        print(
            f"Ферма «{m['farm']}», {m['farmer']}, {m['season_ru']} {m['day']}, год {m['year']}"
        )
        print(f"Сейв: {m['save_path']}")
        if m["warnings"]:
            for w in m["warnings"]:
                print("  ! " + w)
    except SaveError as exc:
        # Показываем понятную диагностику в консоли; если сейв явно не найден при ручном --save, выходим с кодом ошибки
        if save:
            raise
        Handler.state = None
        Handler.error = exc.to_dict()
        print(str(exc), file=sys.stderr)
        print(
            "\nСервер запущен в режиме ожидания сейва — создайте/скопируйте сейв и нажмите «Обновить» в браузере."
        )

    stop = threading.Event()
    if watch:
        threading.Thread(target=watch_loop, args=(stop,), daemon=True).start()

    httpd = None
    for p in range(port, port + 12):
        try:
            httpd = ThreadingHTTPServer(("0.0.0.0", p), Handler)
            port = p
            break
        except OSError:
            continue
    if httpd is None:
        sys.exit("Не удалось занять порт")

    url = f"http://127.0.0.1:{port}/"
    print(f"\nТрекер: {url}   (Ctrl+C — остановить)")
    if open_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено.")
    finally:
        stop.set()
        httpd.server_close()


def info(save=None, saves_dir=None):
    paths = find_saves(saves_dir=saves_dir, explicit=save)
    print(f"Найдено сохранений: {len(paths)}")
    for p in paths[:10]:
        print(
            "  ",
            p,
            time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(p))),
        )
    if not paths:
        print(
            '\nПодсказка: укажите путь вручную через --save "путь\\к\\сейву" или положите копию сейва в папку ./saves'
        )
        return
    st = build_state(save, saves_dir)
    m, c = st["meta"], st["counts"]
    print(
        f"\nФерма: {m['farm']} / {m['farmer']}   {m['season_ru']} {m['day']}, год {m['year']}, {m['clock']}"
    )
    print(f"Версия игры в сейве: {m['game_version'] or '?'}")
    for k in ("fish", "museum", "museum_found", "shipped", "cooking", "crafting"):
        print(f"  {k:14s} {c[k][0]:4d} / {c[k][1]}")
    print(f"  люди            {len(st['people'])}")
    print(
        f"  бандлы          {sum(r['done'] for r in st['bundles'])} / {sum(r['total'] for r in st['bundles'])}"
    )
    print(
        f"  монстры         {st['monsters']['completed'][0]} / {st['monsters']['completed'][1]}"
    )
    print(f"  перфекция       {st['perfection']['pct']}%")
    print(
        f"  найдено в музее, но не сдано: {len(st['alerts']['museum_found_not_donated'])}"
    )
    if m["warnings"]:
        print("\nПредупреждения:")
        for w in m["warnings"]:
            print("  ! " + w)


def main():
    ap = argparse.ArgumentParser(description="Stardew Valley progress tracker")
    ap.add_argument(
        "cmd", nargs="?", default="serve", choices=["serve", "build", "info", "open"]
    )
    ap.add_argument("--save", default=None)
    ap.add_argument("--saves-dir", default=None)
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--no-watch", action="store_true")
    a = ap.parse_args()

    if a.cmd == "info":
        info(a.save, a.saves_dir)
    elif a.cmd == "build":
        st, path = build_report(a.save, a.saves_dir)
        print(f"Готово: {path}")
        print(
            f"  музей {st['counts']['museum'][0]}/{st['counts']['museum'][1]}, "
            f"рыба {st['counts']['fish'][0]}/{st['counts']['fish'][1]}, "
            f"перфекция {st['perfection']['pct']}%"
        )
    elif a.cmd == "open":
        st, path = build_report(a.save, a.saves_dir)
        webbrowser.open("file://" + os.path.abspath(path))
    else:
        serve(a.port, a.save, a.saves_dir, not a.no_open, not a.no_watch)


if __name__ == "__main__":
    main()
