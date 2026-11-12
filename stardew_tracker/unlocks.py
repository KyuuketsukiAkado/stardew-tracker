"""Обязательные условия: что нужно открыть, чтобы получить предмет.

Многие вещи в Stardew Valley недоступны, пока не открыта локация или не
выполнено условие: рыба Имбирного острова требует починенной лодки Вилли,
семена Ки — Комнаты Ки с орехами, рецепт Тотема пустыни — автобуса и т. д.

Модуль описывает такие условия («ворота», gates) и по сейву вычисляет их
статус: ``True`` — открыто, ``False`` — закрыто, ``None`` — по сейву не
понять (например, топор лежит в сундуке, а не в рюкзаке).

У предмета может быть несколько способов получения (рыба водится в
нескольких местах). Предмет закрыт, только если **все** способы закрыты:
сом ловится и в Тайном лесу, и в городской реке — значит, он доступен.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Optional

from .constants import DAYS_PER_SEASON
from .timeutil import abs_day

Status = Optional[bool]

# Ключ -> (ru, en, как открыть ru, как открыть en, вид).
# Вид: "lock" — постоянное условие доступа; "schedule" — доступно только в
# определённые дни; "skill"/"friend" — уровень навыка или дружбы.
GATES: dict[str, tuple[str, str, str, str, str]] = {
    "island": (
        "Имбирный остров",
        "Ginger Island",
        "Почините лодку Вилли: она открывается после восстановления Общественного центра "
        "(или маршрута Joja). Нужны 200 твёрдой древесины, 5 иридиевых слитков и 5 аккумуляторов.",
        "Repair Willy's boat, available after the Community Center (or Joja) is finished: "
        "200 Hardwood, 5 Iridium Bars and 5 Battery Packs.",
        "lock",
    ),
    "walnut_room": (
        "Комната Ки с орехами",
        "Qi's Walnut Room",
        "Найдите 100 золотых грецких орехов на Имбирном острове — дверь в комнату мистера Ки откроется. "
        "Там доска особых заданий Ки и лавка за самоцветы Ки.",
        "Find 100 Golden Walnuts on Ginger Island to open Mr. Qi's room with the Qi special order "
        "board and the Qi Gem shop.",
        "lock",
    ),
    "desert": (
        "Пустыня Калико",
        "Calico Desert",
        "Почините автобус: сдайте Хранилище в Общественном центре (или выкупите ремонт у Joja).",
        "Repair the bus: complete the Vault in the Community Center (or pay Joja).",
        "lock",
    ),
    "skull_cavern": (
        "Пещера Черепа",
        "Skull Cavern",
        "Дойдите до 120-го этажа Шахт — в сундуке будет Ключ-череп. Вход — в Пустыне Калико.",
        "Reach floor 120 of the Mines for the Skull Key. The entrance is in the Calico Desert.",
        "lock",
    ),
    "sewers": (
        "Канализация",
        "The Sewers",
        "Сдайте 60 предметов в музей — Гюнтер подарит Ржавый ключ от люка в городе.",
        "Donate 60 items to the Museum — Gunther gives you the Rusty Key.",
        "lock",
    ),
    "bug_lair": (
        "Логово мутантов",
        "Mutant Bug Lair",
        "После завершения Общественного центра (или Joja) начнётся квест «Тёмный талисман»: "
        "Кробус в канализации пропустит в логово.",
        "After the Community Center (or Joja) is complete, the “Dark Talisman” quest starts: "
        "Krobus in the Sewers lets you into the lair.",
        "lock",
    ),
    "witch_swamp": (
        "Болото ведьмы",
        "Witch's Swamp",
        "Заберите Тёмный талисман в Логове мутантов и отнесите его к пещере у Железной дороги.",
        "Get the Dark Talisman from the Mutant Bug Lair and bring it to the cave by the Railroad.",
        "lock",
    ),
    "secret_woods": (
        "Тайный лес",
        "Secret Woods",
        "Нужен стальной топор (или лучше), чтобы разрубить большое бревно на северо-западе Пепельносмольного леса.",
        "You need a Steel Axe (or better) to chop the large log in the north-west of Cindersap Forest.",
        "lock",
    ),
    "railroad": (
        "Железная дорога",
        "The Railroad",
        "Открывается само: землетрясение 3-го дня лета 1-го года расчищает проход.",
        "Opens automatically after the earthquake on Summer 3, Year 1.",
        "lock",
    ),
    "mines_20": (
        "Шахты: 20-й этаж",
        "The Mines: floor 20",
        "Спуститесь в Шахтах до 20-го этажа — там первое подземное озеро.",
        "Reach floor 20 of the Mines — the first underground lake.",
        "lock",
    ),
    "mines_60": (
        "Шахты: 60-й этаж",
        "The Mines: floor 60",
        "Спуститесь до 60-го этажа Шахт (ледяные уровни).",
        "Reach floor 60 of the Mines (frozen levels).",
        "lock",
    ),
    "mines_100": (
        "Шахты: 100-й этаж",
        "The Mines: floor 100",
        "Спуститесь до 100-го этажа Шахт — там лавовое озеро.",
        "Reach floor 100 of the Mines — the lava lake.",
        "lock",
    ),
    "night_market": (
        "Ночной рынок",
        "Night Market",
        "Только зимой, 15–17 числа, с 17:00 до 02:00 на пляже. Рыба — на субмарине (1 000g за погружение).",
        "Winter 15–17 only, 5 pm – 2 am on the beach. Fish are caught from the submarine (1,000g per dive).",
        "schedule",
    ),
    "farm_forest": (
        "Лесная ферма",
        "Forest Farm",
        "Ловится в пруду только на «Лесной» карте фермы; на других фермах — в Тайном лесу.",
        "Only in the farm pond of the Forest Farm map; otherwise fish in the Secret Woods.",
        "lock",
    ),
    "farm_beach": (
        "Пляжная ферма",
        "Beach Farm",
        "На ферме ловится только на «Пляжной» карте; иначе — на пляже.",
        "On the farm only with the Beach Farm map; otherwise on the beach.",
        "lock",
    ),
    "qi_extended": (
        "Задание Ки «Расширенная семья»",
        "Qi's quest “Extended Family”",
        "Возьмите задание на доске в Комнате Ки. «Легендарные II» клюют только 3 дня, пока задание активно, "
        "и не входят в коллекцию и перфекцию.",
        "Take the quest from the board in Qi's Walnut Room. These fish bite only during the 3 days of the "
        "quest and do not count for the collection or perfection.",
        "lock",
    ),
    "mastery": (
        "Пещера мастерства",
        "Mastery Cave",
        "Прокачайте все 5 навыков до 10 — откроется Пещера мастерства в Пепельносмольном лесу. "
        "Рецепт выдаётся за мастерство соответствующего навыка.",
        "Raise all 5 skills to level 10 to open the Mastery Cave in Cindersap Forest; the recipe is a mastery reward.",
        "lock",
    ),
    "special_orders": (
        "Доска особых поручений",
        "Special Orders board",
        "Доска появляется у дома Пьера осенью 1-го года (со 2-го дня). Задание выпадает случайно — "
        "проверяйте доску по понедельникам.",
        "The board appears next to Pierre's in Fall of Year 1 (from day 2). Orders rotate — check it on Mondays.",
        "lock",
    ),
    "greenhouse": (
        "Теплица",
        "Greenhouse",
        "Сдайте Кладовую в Общественном центре (или купите ремонт теплицы у Joja).",
        "Complete the Pantry in the Community Center (or buy the greenhouse from Joja).",
        "lock",
    ),
    "cellar": (
        "Погреб",
        "Cellar",
        "Третье улучшение дома у Робин (погреб).",
        "The third house upgrade from Robin (cellar).",
        "lock",
    ),
    "museum_ancient_seed": (
        "Древнее семя в музее",
        "Ancient Seed donated",
        "Сдайте артефакт «Древнее семя» в музей — Гюнтер даст рецепт.",
        "Donate the Ancient Seed artifact to the Museum — Gunther gives the recipe.",
        "lock",
    ),
}

SKILL_NAMES = {
    "farming": ("Фермерство", "Farming"),
    "mining": ("Горное дело", "Mining"),
    "foraging": ("Собирательство", "Foraging"),
    "fishing": ("Рыбная ловля", "Fishing"),
    "combat": ("Боевые навыки", "Combat"),
    "luck": ("Удача", "Luck"),
}

# Рыба: локация из data/fish.json (en) -> ворота. Пустой список — доступно сразу.
LOCATION_GATES: dict[str, list[str]] = {
    "Ginger Island (north)": ["island"],
    "Ginger Island (south)": ["island"],
    "Ginger Island (southeast)": ["island"],
    "Ginger Island (west)": ["island"],
    "Pirate Cove": ["island"],
    "Caldera": ["island"],
    "Secret Woods": ["secret_woods"],
    "Calico Desert": ["desert"],
    "The Sewers": ["sewers"],
    "Mutant Bug Lair": ["bug_lair"],
    "Witch's Swamp": ["witch_swamp"],
    "The Mines": ["mines_20"],
    "The Mines (20F)": ["mines_20"],
    "The Mines (60F)": ["mines_60"],
    "The Mines (100F)": ["mines_100"],
    "Night Market Submarine": ["night_market"],
    "Night Market (Beach)": ["night_market"],
}

# Группы локаций для фильтра «Где ловить». Порядок — порядок в списке.
LOCATION_GROUPS: list[tuple[str, str, str, list[str]]] = [
    ("ocean", "Океан (пляж)", "Ocean (beach)", ["Pelican Beach", "Ocean (any saltwater)"]),
    ("town", "Река в городе", "Town river", ["Pelican Town"]),
    ("forest", "Пепельносмольный лес", "Cindersap Forest", ["Cindersap Forest"]),
    ("mountain", "Горное озеро", "Mountain lake", ["The Mountain"]),
    ("backwoods", "Глушь", "Backwoods", ["Backwoods"]),
    ("freshwater", "Любая пресная вода", "Any freshwater", ["Rivers & lakes (any freshwater)"]),
    ("farm", "Ферма (пруд)", "Farm pond", ["Farm"]),
    ("secret_woods", "Тайный лес", "Secret Woods", ["Secret Woods"]),
    (
        "mines",
        "Шахты (все этажи)",
        "The Mines (all floors)",
        ["The Mines", "The Mines (20F)", "The Mines (60F)", "The Mines (100F)"],
    ),
    ("sewers", "Канализация", "The Sewers", ["The Sewers"]),
    ("bug_lair", "Логово мутантов", "Mutant Bug Lair", ["Mutant Bug Lair"]),
    ("swamp", "Болото ведьмы", "Witch's Swamp", ["Witch's Swamp"]),
    ("desert", "Пустыня Калико", "Calico Desert", ["Calico Desert"]),
    ("night_market", "Ночной рынок", "Night Market", ["Night Market Submarine", "Night Market (Beach)"]),
    (
        "island",
        "Имбирный остров",
        "Ginger Island",
        [
            "Ginger Island (north)",
            "Ginger Island (south)",
            "Ginger Island (southeast)",
            "Ginger Island (west)",
            "Pirate Cove",
            "Caldera",
        ],
    ),
    ("crab_ocean", "Крабовая ловушка (океан)", "Crab pot (ocean)", ["Crab Pot (Ocean)"]),
    ("crab_fresh", "Крабовая ловушка (пресная)", "Crab pot (freshwater)", ["Crab Pot (Freshwater)"]),
]
_LOCATION_TO_GROUP = {loc: key for key, _ru, _en, locs in LOCATION_GROUPS for loc in locs}

# Легендарные рыбы требуют уровня рыбалки, иначе не клюют.
LEGENDARY_FISHING_LEVEL = {"159": 5, "160": 3, "163": 10, "775": 6, "682": 0}
EXTENDED_FAMILY_BASE = {"898": "159", "899": "160", "900": "163", "901": "682", "902": "775"}

# Отправка: предметы, которые можно добыть только в закрытых локациях.
# Каждый вариант — альтернатива; предмет доступен, если открыта любая.
SHIPPING_GATES: dict[str, list[list[str]]] = {
    "829": [["island"]],  # Имбирь
    "830": [["island"]],  # Корень таро
    "832": [["island"]],  # Ананас
    "834": [["island"]],  # Манго
    "91": [["island"]],  # Банан
    "848": [["island"]],  # Тлеющий осколок
    "851": [["island"]],  # Магмовый гриб
    "289": [["island"]],  # Страусиное яйцо
    "88": [["island"], ["desert"]],  # Кокос: пальмы острова или лавка Оазиса
    "90": [["desert"]],  # Плод кактуса
    "305": [["sewers"], ["witch_swamp"]],  # Яйцо пустоты: Кробус или ведьма
    "308": [["sewers"], ["witch_swamp"]],  # Майонез пустоты
    "909": [["walnut_room"]],  # Радиоактивная руда: опасные шахты после задания Ки
    "910": [["walnut_room"]],
}

# Музей: ключевые слова источника (en) -> ворота. Без совпадения — доступно.
MUSEUM_SOURCE_GATES: list[tuple[str, list[str]]] = [
    ("Skull Cavern", ["skull_cavern"]),
    ("Artifact Trove", ["desert"]),
    ("Desert", ["desert"]),
    ("Bone Nodes", ["island"]),
    ("Railroad", ["railroad"]),
    ("Secret Note", []),
]
_MINES_ONLY_PREFIX = "Tilling in Mines/Skull Cavern"

# Музей: ключевые слова (en) -> тег для фильтра «Где искать».
MUSEUM_TAGS: list[tuple[str, str, str, tuple[str, ...]]] = [
    ("mines", "Шахты", "The Mines", ("Mines",)),
    ("skull_cavern", "Пещера Черепа", "Skull Cavern", ("Skull Cavern",)),
    ("geodes", "Жеоды", "Geodes", ("Geode",)),
    ("fishing", "Сундуки на рыбалке", "Fishing chests", ("Fishing Treasure Chest",)),
    ("monsters", "Добыча с монстров", "Monster drops", ("drop", "monsters", "Bats")),
    ("beach", "Пляж", "Beach", ("Beach",)),
    ("forest", "Лес", "Forest", ("Forest",)),
    ("mountain", "Горы", "Mountain", ("Mountain",)),
    ("town", "Город", "Town", ("Town",)),
    ("bus_stop", "Автобусная остановка", "Bus Stop", ("Bus Stop",)),
    ("farm", "Ферма", "Farm", ("Farm",)),
    ("railroad", "Железная дорога", "Railroad", ("Railroad",)),
    ("backwoods", "Глушь", "Backwoods", ("Backwoods",)),
    ("desert", "Пустыня", "Desert", ("Desert", "Artifact Trove")),
    ("island", "Имбирный остров", "Ginger Island", ("Bone Nodes",)),
]


class UnlockContext:
    """Факты из сейва, нужные для проверки условий."""

    def __init__(self, raw: Mapping[str, Any], hearts: Mapping[str, int] | None = None):
        self.raw = raw
        self.mail: set[str] = set(raw.get("mail_received") or ())
        self._mail_lower = {name.lower() for name in self.mail}
        self.skills: Mapping[str, int] = raw.get("skills") or {}
        self.hearts: Mapping[str, int] = hearts or {}
        self.walnuts = int(raw.get("walnuts") or 0)
        self.deepest = int(raw.get("deepest_mine") or 0)
        self.museum: Mapping[str, Any] = raw.get("museum") or {}
        self.day_index = abs_day(raw.get("season") or "spring", raw.get("day") or 1, raw.get("year") or 1)
        self._cache: dict[str, Status] = {}

    def has_mail(self, *names: str) -> bool:
        """Есть ли хоть одно из писем; регистр не важен.

        Игра не выдерживает единый стиль имён (``jojaVault``, но ``JojaMember``):
        сравнение с точным регистром не видело членство в Joja, и у игроков на
        этом пути «сообщество завершено» никогда не выполнялось.
        """

        return any(name.lower() in self._mail_lower for name in names)

    # ---- проверки отдельных ворот -----------------------------------------
    def status(self, key: str) -> Status:
        if key not in self._cache:
            self._cache[key] = self._compute(key)
        return self._cache[key]

    def _compute(self, key: str) -> Status:
        raw = self.raw
        if key.startswith("skill_"):
            _prefix, skill, level = key.split("_", 2)
            return int(self.skills.get(skill, 0)) >= int(level)
        if key.startswith("friend_"):
            npc, level = key[len("friend_") :].rsplit("_", 1)
            return int(self.hearts.get(npc, 0)) >= int(level)
        if key == "island":
            # Орехи бывают только на острове: если они есть, остров открыт.
            return self.has_mail("willyBoatFixed", "Visited_Island") or self.walnuts > 0
        if key == "walnut_room":
            return self.walnuts >= 100
        if key == "desert":
            return self.has_mail("ccVault", "jojaVault") or bool(raw.get("has_skull_key"))
        if key == "skull_cavern":
            return bool(raw.get("has_skull_key"))
        if key == "sewers":
            return bool(raw.get("has_rusty_key")) or len(self.museum) >= 60
        if key == "bug_lair":
            if raw.get("has_dark_talisman"):
                return True
            areas = raw.get("areasComplete") or [False]
            community_done = self.has_mail("ccIsComplete", "JojaMember") or all(areas)
            return bool(raw.get("has_rusty_key")) and community_done
        if key == "witch_swamp":
            return bool(raw.get("has_dark_talisman")) or bool(raw.get("has_magic_ink"))
        if key == "secret_woods":
            axe = raw.get("axe_level")
            if axe is None:
                return None
            return int(axe) >= 2
        if key == "railroad":
            return self.day_index >= DAYS_PER_SEASON + 2  # лето 3, 1-й год
        if key.startswith("mines_"):
            return self.deepest >= int(key.split("_", 1)[1])
        if key == "night_market":
            return raw.get("season") == "winter" and 15 <= int(raw.get("day") or 0) <= 17
        if key == "farm_forest":
            return None if raw.get("farm_type") is None else raw.get("farm_type") == 2
        if key == "farm_beach":
            return None if raw.get("farm_type") is None else raw.get("farm_type") == 6
        if key == "qi_extended":
            return self.status("walnut_room")
        if key == "mastery":
            skills = ("farming", "mining", "foraging", "fishing", "combat")
            return all(int(self.skills.get(skill, 0)) >= 10 for skill in skills)
        if key == "special_orders":
            return self.day_index >= 2 * DAYS_PER_SEASON + 1  # осень 2, 1-й год
        if key == "greenhouse":
            return self.has_mail("ccPantry", "jojaPantry")
        if key == "cellar":
            return int(raw.get("house_level") or 0) >= 3
        if key == "museum_ancient_seed":
            return "114" in self.museum
        return None

    # ---- описание ворот ---------------------------------------------------
    def describe(self, key: str) -> dict[str, Any]:
        status = self.status(key)
        if key.startswith("skill_"):
            _prefix, skill, level = key.split("_", 2)
            name_ru, name_en = SKILL_NAMES.get(skill, (skill, skill))
            have = int(self.skills.get(skill, 0))
            return {
                "ru": f"{name_ru}: уровень {level}",
                "en": f"{name_en} level {level}",
                "how_ru": f"Сейчас у вас уровень {have}. Качайте навык «{name_ru}».",
                "how_en": f"Your level is {have}. Keep training {name_en}.",
                "kind": "skill",
                "met": status,
            }
        if key.startswith("friend_"):
            npc, level = key[len("friend_") :].rsplit("_", 1)
            have = int(self.hearts.get(npc, 0))
            return {
                "ru": f"{npc}: {level}♥",
                "en": f"{npc}: {level}♥",
                "how_ru": f"Сейчас {have}♥. Дарите подарки и разговаривайте каждый день.",
                "how_en": f"Currently {have}♥. Talk daily and give gifts.",
                "kind": "friend",
                "met": status,
            }
        ru, en, how_ru, how_en, kind = GATES.get(key, (key, key, "", "", "lock"))
        return {"ru": ru, "en": en, "how_ru": how_ru, "how_en": how_en, "kind": kind, "met": status}


def combine(statuses: Iterable[Status]) -> Status:
    """Все условия одной альтернативы: False сильнее None, None сильнее True."""

    result: Status = True
    for status in statuses:
        if status is False:
            return False
        if status is None:
            result = None
    return result


def evaluate(alternatives: list[list[str]], ctx: UnlockContext) -> tuple[str, list[str]]:
    """``(состояние, ключи_условий)`` для набора альтернатив.

    Состояние: ``open`` — хотя бы один способ открыт, ``locked`` — все закрыты,
    ``unknown`` — открытых нет, но часть условий по сейву не проверить.
    Ключи — условия самой «близкой» закрытой альтернативы (меньше всего
    невыполненных), чтобы подсказать, что делать дальше.
    """

    if not alternatives:
        return "open", []
    best_keys: list[str] = []
    best_missing: int | None = None
    has_unknown = False
    for gates in alternatives:
        statuses = [ctx.status(key) for key in gates]
        state = combine(statuses)
        if state is True:
            return "open", []
        if state is None:
            has_unknown = True
        missing = sum(1 for status in statuses if status is not True)
        if best_missing is None or missing < best_missing:
            best_missing = missing
            best_keys = list(gates)
    return ("unknown" if has_unknown else "locked"), best_keys


# Основные «вехи» доступа в порядке прохождения — для панели «Ключи и доступы».
MILESTONES = (
    "railroad",
    "mines_20",
    "mines_60",
    "mines_100",
    "special_orders",
    "secret_woods",
    "greenhouse",
    "sewers",
    "desert",
    "skull_cavern",
    "bug_lair",
    "witch_swamp",
    "island",
    "walnut_room",
    "mastery",
)


def build_unlocks(
    ctx: UnlockContext,
    row_groups: Iterable[Iterable[Mapping[str, Any]]],
    secrets: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Справочник условий для UI и сводка «что ещё закрыто».

    ``gates`` — описание каждого условия, на которое ссылаются строки
    (``row["req"]``), чтобы не дублировать тексты в каждой строке.
    ``milestones`` — основные доступы с числом незакрытых предметов за ними.
    """

    keys: set[str] = set(MILESTONES)
    blocked: dict[str, int] = {}
    for rows in row_groups:
        for row in rows:
            for key in row.get("req") or []:
                keys.add(key)
                if not row.get("done") and row.get("lock") != "open" and ctx.status(key) is not True:
                    blocked[key] = blocked.get(key, 0) + 1
    for section in (secrets or {}).get("sections", []):
        if section.get("gate"):
            keys.add(section["gate"])
    gates = {key: ctx.describe(key) for key in sorted(keys)}
    milestones = [{"key": key, "met": gates[key]["met"], "blocked": blocked.get(key, 0)} for key in MILESTONES]
    return {"gates": gates, "milestones": milestones}


# ---- рыба -------------------------------------------------------------------
def _fish_location_gates(uid: str, loc: Mapping[str, Any]) -> list[str]:
    name = loc.get("en", "")
    if name == "Farm":
        return ["farm_forest"] if uid == "734" else ["farm_beach"]
    return list(LOCATION_GATES.get(name, []))


def fish_alternatives(uid: str, info: Mapping[str, Any]) -> tuple[list[list[str]], list[str]]:
    """``(альтернативы по локациям, общие условия)`` для вида рыбы."""

    common: list[str] = []
    base = EXTENDED_FAMILY_BASE.get(uid, uid)
    if uid in EXTENDED_FAMILY_BASE:
        common.append("qi_extended")
    level = LEGENDARY_FISHING_LEVEL.get(base)
    if level:
        common.append(f"skill_fishing_{level}")

    alternatives: list[list[str]] = []
    for loc in info.get("loc") or []:
        alternatives.append(_fish_location_gates(uid, loc) + common)
    if not alternatives:
        alternatives.append(list(common))
    # Варианты «на ферме особого типа» — в конец: при равенстве подсказываем
    # общий путь (Тайный лес), а не смену карты фермы.
    alternatives.sort(key=lambda gates: any(gate.startswith("farm_") for gate in gates))
    return alternatives, common


def fish_open_locations(uid: str, info: Mapping[str, Any], ctx: UnlockContext | None) -> list[dict[str, Any]]:
    """Места ловли, доступ к которым по сейву точно открыт (без «неизвестно»)."""

    locs = list(info.get("loc") or [])
    if ctx is None:
        return locs
    _alternatives, common = fish_alternatives(uid, info)
    return [loc for loc in locs if combine(ctx.status(key) for key in _fish_location_gates(uid, loc) + common) is True]


def fish_location_groups(info: Mapping[str, Any]) -> list[str]:
    groups: list[str] = []
    for loc in info.get("loc") or []:
        group = _LOCATION_TO_GROUP.get(loc.get("en", ""))
        if group and group not in groups:
            groups.append(group)
    return groups


def is_night_market_only(info: Mapping[str, Any]) -> bool:
    locs = [loc.get("en", "") for loc in info.get("loc") or []]
    return bool(locs) and all(LOCATION_GATES.get(name) == ["night_market"] for name in locs)


def location_filter_options() -> list[dict[str, str]]:
    return [{"key": key, "ru": ru, "en": en} for key, ru, en, _locs in LOCATION_GROUPS]


# ---- музей -------------------------------------------------------------------
def museum_alternatives(sources_en: list[str]) -> list[list[str]]:
    alternatives: list[list[str]] = []
    for source in sources_en:
        gates: list[str] = []
        if not source.startswith(_MINES_ONLY_PREFIX):  # раскопки в Шахтах доступны сразу
            for keyword, keyword_gates in MUSEUM_SOURCE_GATES:
                if keyword in source:
                    gates = list(keyword_gates)
                    break
        alternatives.append(gates)
    return alternatives


def museum_tags(sources_en: list[str], kind: str) -> list[str]:
    if kind == "mineral":
        return ["mines", "geodes"]
    tags: list[str] = []
    joined = " | ".join(sources_en)
    for key, _ru, _en, keywords in MUSEUM_TAGS:
        if any(keyword in joined for keyword in keywords) and key not in tags:
            tags.append(key)
    return tags


def museum_tag_options() -> list[dict[str, str]]:
    return [{"key": key, "ru": ru, "en": en} for key, ru, en, _kw in MUSEUM_TAGS]


# ---- рецепты -----------------------------------------------------------------
_SEASON_RU_GEN = {"spring": "весны", "summer": "лета", "fall": "осени", "winter": "зимы"}
_SEASON_EN = {"spring": "Spring", "summer": "Summer", "fall": "Fall", "winter": "Winter"}

RECIPE_KINDS: list[tuple[str, str, str]] = [
    ("start", "Со старта", "Starter"),
    ("skill", "Уровень навыка", "Skill level"),
    ("friend", "Дружба", "Friendship"),
    ("tv", "ТВ «Королева соуса»", "TV: Queen of Sauce"),
    ("shop", "Покупка", "Shop"),
    ("quest", "Особые поручения", "Special orders"),
    ("qi", "Мистер Ки", "Mr. Qi"),
    ("island", "Имбирный остров", "Ginger Island"),
    ("mastery", "Мастерство", "Mastery"),
    ("event", "Событие / письмо", "Event / mail"),
]


def recipe_kind_options() -> list[dict[str, str]]:
    return [{"key": key, "ru": ru, "en": en} for key, ru, en in RECIPE_KINDS]


def _tv_text(tv: list[Any]) -> tuple[str, str]:
    day, season, year = tv
    return (
        f"ТВ «Королева соуса»: {day} {_SEASON_RU_GEN.get(season, season)}, {year}-й год (воскресенье)",
        f"TV “Queen of Sauce”: {_SEASON_EN.get(season, season)} {day}, Year {year} (Sunday)",
    )


def recipe_source(
    name: str, recipe: Mapping[str, Any], override: Mapping[str, Any] | None
) -> tuple[str, str, str, list[str]]:
    """``(текст_ru, текст_en, вид_источника, условия)`` для рецепта."""

    unlock = str(recipe.get("unlock") or "")
    info = recipe.get("unlock_info") or {}
    if override:
        ru = override.get("ru", "")
        en = override.get("en", "")
        if override.get("tv"):
            tv_ru, tv_en = _tv_text(override["tv"])
            ru = f"{tv_ru}; {ru}" if ru else tv_ru
            en = f"{tv_en}; {en}" if en else tv_en
            if override.get("saloon"):
                ru += f"; Салун «Звёздная капля», {override['saloon']:,}g".replace(",", " ")
                en += f"; Stardrop Saloon, {override['saloon']:,}g"
            ru += ". Повторы рецептов, которых у вас нет, — с 3-го года."
            en += ". Reruns of missing recipes from Year 3."
        return ru, en, str(override.get("kind") or "other"), list(override.get("gates") or [])

    parts = unlock.split()
    if unlock == "default":
        return info.get("ru", "Со старта"), info.get("en", "Starter recipe"), "start", []
    if len(parts) == 3 and parts[0] == "s":
        skill = parts[1].lower()
        name_ru, name_en = SKILL_NAMES.get(skill, (parts[1], parts[1]))
        return f"{name_ru}: уровень {parts[2]}", f"{name_en} level {parts[2]}", "skill", [f"skill_{skill}_{parts[2]}"]
    if len(parts) == 3 and parts[0] == "f":
        npc, hearts = parts[1], parts[2]
        gates = [f"friend_{npc}_{hearts}"]
        if npc == "Leo":
            gates.insert(0, "island")
        return (
            f"Письмо от {npc} при дружбе {hearts}♥",
            f"Mail from {npc} at {hearts}♥",
            "friend",
            gates,
        )
    return info.get("ru", ""), info.get("en", ""), "other", []
