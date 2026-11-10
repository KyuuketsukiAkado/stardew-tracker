"""Константы домена Stardew Valley 1.6."""

from __future__ import annotations

from typing import Final

SEASONS: Final = ("spring", "summer", "fall", "winter")
DAYS_PER_SEASON: Final = 28
DAYS_PER_YEAR: Final = DAYS_PER_SEASON * len(SEASONS)
WALNUTS_TOTAL: Final = 130

SEASON_RU: Final = {
    "spring": "Весна",
    "summer": "Лето",
    "fall": "Осень",
    "winter": "Зима",
}


# Атласы собираются build_data.py; имена используются и сервером, и рендером.
SPRITE_FILES: Final = (
    "objects.png",
    "objects2.png",
    "craftables.png",
    "bundles.png",
    "npcs.png",
    "monsters.png",
    "ui.png",
)

# CSS-переменные для встроенных (data:) спрайтов в автономном отчёте.
SPRITE_CSS_VARS: Final = {
    "objects.png": "--spr-obj0",
    "objects2.png": "--spr-obj1",
    "craftables.png": "--spr-bc",
    "bundles.png": "--spr-bundles",
    "npcs.png": "--spr-npcs",
    "monsters.png": "--spr-monsters",
    "ui.png": "--spr-ui",
}

STARDROPS: Final = (
    ("CF_Fair", "Ярмарка Долины Стардью (2 000 жетонов)", "Stardew Valley Fair (2,000 tokens)"),
    ("CF_Mines", "Сундук на 100-м этаже шахты", "Mine floor 100 treasure chest"),
    ("CF_Spouse", "От супруга/соседа при 12.5♥", "Spouse / Roommate at 12.5♥"),
    ("CF_Sewer", "Покупка у Кробуса в канализации (20 000g)", "Krobus in The Sewers (20,000g)"),
    ("CF_Statue", "Старый мастер Канноли в Тайном лесу (Сладкая самоцветинка)", "Old Master Cannoli in Secret Woods"),
    ("CF_Fish", "Письмо от Вилли за поимку всех рыб", "Master Angler letter from Willy"),
    ("museumComplete", "Награда за полный сбор музея (95 предметов)", "Complete Museum collection (95 items)"),
)

OBELISKS: Final = (
    ("Earth Obelisk", "Обелиск Земли", "Earth Obelisk"),
    ("Water Obelisk", "Обелиск Воды", "Water Obelisk"),
    ("Desert Obelisk", "Обелиск Пустыни", "Desert Obelisk"),
    ("Island Obelisk", "Обелиск Острова", "Island Obelisk"),
)

# Порядок опыта в Farmer.experiencePoints: farming, fishing, foraging, mining, combat.
SKILLS: Final = (
    ("farming", "Фермерство", "Farming", 16, 0),
    ("mining", "Горное дело", "Mining", 17, 3),
    ("foraging", "Собирательство", "Foraging", 18, 2),
    ("fishing", "Рыбная ловля", "Fishing", 19, 1),
    ("combat", "Боевые навыки", "Combat", 20, 4),
)
