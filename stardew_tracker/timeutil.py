"""Игровое время, даты и сезоны."""

from __future__ import annotations

from .constants import DAYS_PER_SEASON, DAYS_PER_YEAR, SEASONS


def _as_int(value: object, default: int) -> int:
    """Мягкое приведение к int: XML/JSON иногда дают строку или None."""

    if isinstance(value, (int, float, str)):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
    return default


def game_clock(value: object) -> tuple[int, int]:
    """``1350`` -> ``(13, 50)``; значения после полуночи сохраняются (26:00)."""

    minutes = _as_int(value, 600) if value else 600
    return minutes // 100, minutes % 100


def fmt_clock(value: object) -> str:
    hours, minutes = game_clock(value)
    return f"{hours:02d}:{minutes:02d}"


def abs_day(season: str, day: object, year: object) -> int:
    """Абсолютный игровой день (0 — весна 1-го года, 1-й день)."""

    season_index = SEASONS.index(season) if season in SEASONS else 0
    day_num = _as_int(day, 1)
    year_num = _as_int(year, 1)
    return (max(1, year_num) - 1) * DAYS_PER_YEAR + season_index * DAYS_PER_SEASON + (max(1, day_num) - 1)


def days_until_birthday(cur_abs: int, season: str, day: object) -> int | None:
    """Сколько дней осталось до дня рождения (0 — сегодня).

    Прошедший в этом году день рождения переносится на следующий игровой год.
    """

    if season not in SEASONS:
        return None
    day_num = _as_int(day, 0)
    if not 1 <= day_num <= DAYS_PER_SEASON:
        return None
    target = abs_day(season, day_num, 1) % DAYS_PER_YEAR
    return (target - (cur_abs % DAYS_PER_YEAR)) % DAYS_PER_YEAR


def minutes_of_day(value: object) -> int:
    hours, minutes = game_clock(value)
    return hours * 60 + minutes


def time_matches(time_span: str, current_minutes: int) -> tuple[bool, bool]:
    """Возвращает ``(ловится_сейчас, ловится_позже_сегодня)``.

    Поддерживаются одно или два окна вида ``"600 1200"`` / ``"1800 0200"``.
    Пустое или некорректное окно означает «без ограничения по времени».
    """

    if not time_span:
        return True, False
    numbers = [int(token) for token in time_span.split() if token.isdigit()]
    if len(numbers) < 2:
        return True, False

    now_ok = False
    later_ok = False
    for index in range(0, len(numbers) - 1, 2):
        start, end = numbers[index], numbers[index + 1]
        start_min = (start // 100) * 60 + start % 100
        end_min = (end // 100) * 60 + end % 100
        if start_min <= end_min:
            if start_min <= current_minutes <= end_min:
                now_ok = True
            elif current_minutes < start_min:
                later_ok = True
        else:  # окно переходит через полночь
            if current_minutes >= start_min or current_minutes <= end_min:
                now_ok = True
            elif current_minutes < start_min:
                later_ok = True
    return now_ok, (later_ok and not now_ok)


def weather_matches(fish_weather: str, save_weather: str) -> bool:
    """Совместима ли погода сейва с требованием рыбы."""

    if not save_weather or not fish_weather or fish_weather in ("both", "all"):
        return True
    is_wet = save_weather in ("rainy", "storm", "green_rain")
    if fish_weather == "rainy":
        return is_wet
    if fish_weather == "sunny":
        return not is_wet
    return True
