"""Вставка состояния в HTML-шаблон и сборка автономного отчёта."""

from __future__ import annotations

import base64
import contextlib
import json
import os
import re
import threading
from typing import Any

from .constants import SPRITE_CSS_VARS
from .paths import REPORT, SPRITES_DIR, TEMPLATE

_SPRITE_CACHE: dict[str, str] = {}
_SPRITE_LOCK = threading.RLock()


def _inline_sprites_css(sprites_dir: str | None = None) -> str:
    """CSS с 7 base64-атласами: отчёт работает из ``file://`` без сети."""

    directory = sprites_dir or SPRITES_DIR
    rules: list[str] = []
    for filename, css_var in SPRITE_CSS_VARS.items():
        path = os.path.join(directory, filename)
        cache_key = os.path.abspath(path)
        with _SPRITE_LOCK:
            if cache_key not in _SPRITE_CACHE:
                if os.path.isfile(path):
                    with open(path, "rb") as handle:
                        _SPRITE_CACHE[cache_key] = base64.b64encode(handle.read()).decode("ascii")
                else:
                    _SPRITE_CACHE[cache_key] = ""
            encoded = _SPRITE_CACHE[cache_key]
        if encoded:
            rules.append(f"{css_var}:url('data:image/png;base64,{encoded}');")
    if not rules:
        return ""
    return ":root{" + "".join(rules) + "}"


def _script_safe(value: Any) -> str:
    """JSON, безопасный внутри ``<script>``.

    Состояние содержит строки из чужих файлов (имя фермы и фермера, заметки).
    ``</`` экранируется, чтобы нельзя было закрыть тег; ``<!--`` — чтобы не
    перевести разбор скрипта в «двойное экранирование» (после ``<!--<script``
    закрывающий тег перестаёт работать и страница ломается); U+2028/U+2029 —
    потому что они переводят строку в JavaScript. Все четыре последовательности
    в JSON встречаются только внутри строк, где такие escape-коды равнозначны.
    """

    return (
        json.dumps(value, ensure_ascii=False)
        .replace("</", "<\\/")
        .replace("<!--", "<\\!--")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def render(
    state: dict[str, Any] | None,
    mode: str = "live",
    error: dict[str, Any] | None = None,
    template_path: str | None = None,
    sprites_dir: str | None = None,
) -> str:
    """Подставляет ``__STATE__``/``__ERROR__``/``__MODE_VALUE__`` в шаблон."""

    with open(template_path or TEMPLATE, encoding="utf-8") as handle:
        template = handle.read()

    html = re.sub(r"/\*__STATE__\*/\s*null", lambda _match: _script_safe(state), template)
    html = re.sub(r"/\*__ERROR__\*/\s*null", lambda _match: _script_safe(error), html)
    html = re.sub(
        r"/\*__MODE_VALUE__\*/\s*\"live\"",
        lambda _match: json.dumps(mode),
        html,
    )
    if mode == "static":
        inline_css = _inline_sprites_css(sprites_dir)
        if inline_css:
            html = html.replace("/*__INLINE_SPRITES__*/", inline_css)
    return html


def _atomic_write(path: str, content: str) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def build_report(
    save: str | None = None,
    saves_dir: str | None = None,
    out_path: str | None = None,
) -> tuple[dict[str, Any], str]:
    """Собирает автономный HTML и возвращает ``(state, путь)``."""

    from .state import build_state

    state = build_state(save, saves_dir)
    html = render(state, "static")
    target = out_path or REPORT
    _atomic_write(target, html)
    return state, target
