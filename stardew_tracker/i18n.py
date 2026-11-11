"""Language selection and bilingual messages (English first, Russian second).

The web interface keeps its own English/Russian dictionaries and chooses the
language in the browser. This module covers everything the Python side prints
or sends to the page:

* :func:`detect_language` picks English or Russian from, in this order, the
  ``STARDEW_TRACKER_LANG`` variable, the Windows display language and the
  POSIX locale variables. Anything else falls back to English.
* :func:`L` builds a :class:`Text`: a ``str`` that already holds the text for
  the current console language and keeps both translations, so an error raised
  deep inside the parser can still be shown in whichever language the browser
  currently uses.
"""

from __future__ import annotations

import ctypes
import locale
import os
import sys

LANGUAGES = ("en", "ru")
DEFAULT_LANGUAGE = "en"
ENV_VAR = "STARDEW_TRACKER_LANG"

# Windows primary language identifier of Russian (LANG_RUSSIAN).
_WINDOWS_LANG_RUSSIAN = 0x19

_current: str | None = None


def normalize(value: object) -> str | None:
    """``"ru_RU.UTF-8"``, ``"ru-RU"``, ``"Russian_Russia"`` -> ``"ru"``; unknown -> ``None``."""

    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if not text:
        return None
    if text.startswith("ru"):
        return "ru"
    if text.startswith("en"):
        return "en"
    return None


def _windows_ui_language() -> str | None:
    """Display language of the current Windows user, or ``None`` elsewhere."""

    windll = getattr(ctypes, "windll", None)
    if windll is None or not sys.platform.startswith("win"):
        return None
    try:
        lang_id = int(windll.kernel32.GetUserDefaultUILanguage())
    except (AttributeError, OSError, ValueError):
        return None
    return "ru" if lang_id & 0x3FF == _WINDOWS_LANG_RUSSIAN else "en"


def _posix_language() -> str | None:
    """First locale variable that is set decides (the POSIX rule)."""

    for name in ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG"):
        raw = os.environ.get(name, "")
        if not raw:
            continue
        # LANGUAGE is a colon-separated priority list: "ru:en".
        first = raw.split(":")[0]
        return normalize(first) or DEFAULT_LANGUAGE
    return None


def detect_language() -> str:
    """Language for console output: explicit override, then OS settings, then English."""

    explicit = normalize(os.environ.get(ENV_VAR))
    if explicit:
        return explicit
    windows = _windows_ui_language()
    if windows:
        return windows
    posix = _posix_language()
    if posix:
        return posix
    try:
        guessed = normalize(locale.getlocale()[0])
    except (ValueError, TypeError):
        guessed = None
    return guessed or DEFAULT_LANGUAGE


def set_language(lang: str | None) -> str:
    """Fix the console language (``None`` re-detects it) and return it."""

    global _current
    _current = normalize(lang) if lang else None
    return get_language()


def get_language() -> str:
    global _current
    if _current is None:
        _current = detect_language()
    return _current


class Text(str):
    """A string for the current language that remembers all its translations."""

    translations: dict[str, str]

    def __new__(cls, translations: dict[str, str]) -> Text:
        current = translations.get(get_language()) or translations[DEFAULT_LANGUAGE]
        instance = super().__new__(cls, current)
        instance.translations = dict(translations)
        return instance

    def to_dict(self) -> dict[str, str]:
        return dict(self.translations)

    # A Text never changes, so copying (the state cache deep-copies its data) can share it,
    # and pickling rebuilds it from its translations instead of from the bare string.
    def __copy__(self) -> Text:
        return self

    def __deepcopy__(self, memo: dict[int, object]) -> Text:
        return self

    def __getnewargs__(self) -> tuple[dict[str, str]]:  # type: ignore[override]
        return (self.translations,)


def L(en: str, ru: str) -> Text:
    """Bilingual text: ``L("Not found", "Не найдено")``."""

    return Text({"en": en, "ru": ru})


def pick(value: object, lang: str) -> str:
    """Text in ``lang`` if ``value`` is bilingual, otherwise the plain string."""

    if isinstance(value, Text):
        return value.translations.get(lang) or value.translations[DEFAULT_LANGUAGE]
    return str(value)


def both(value: object) -> dict[str, str]:
    """``{"en": ..., "ru": ...}`` for any text; plain strings are the same in both."""

    if isinstance(value, Text):
        return value.to_dict()
    text = str(value)
    return {"en": text, "ru": text}
