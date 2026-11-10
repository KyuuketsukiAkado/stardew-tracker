"""Пользовательские цели, задачи и пометки предметов."""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import sys
import tempfile
import threading
from typing import Any

from . import paths

GOALS_LOCK = threading.RLock()
NOTE_LIMIT = 280


def _goals_path(path: str | None = None) -> str:
    return path or paths.GOALS_FILE


def default_goals() -> dict[str, Any]:
    return {"goals": [], "tasks": []}


def normalize_goals(value: Any) -> dict[str, Any]:
    """Приводит произвольный JSON к безопасной структуре целей.

    Сохраняется прежний двухключевой формат (``goals``/``tasks``) и
    необязательный ``annotations``. Некорректные элементы отбрасываются,
    заметки обрезаются до :data:`NOTE_LIMIT` символов.
    """

    if not isinstance(value, dict):
        return default_goals()

    def dict_list(key: str) -> list[dict[str, Any]]:
        raw = value.get(key, [])
        if not isinstance(raw, list):
            return []
        return [item for item in raw if isinstance(item, dict)]

    result: dict[str, Any] = {"goals": dict_list("goals"), "tasks": dict_list("tasks")}
    annotations = value.get("annotations")
    if isinstance(annotations, dict):
        clean: dict[str, dict[str, Any]] = {}
        for key, item in annotations.items():
            if not isinstance(item, dict):
                continue
            marked = bool(item.get("marked"))
            note = str(item.get("note") or "").strip()[:NOTE_LIMIT]
            if marked or note:
                clean[str(key)] = {"marked": marked, "note": note}
        result["annotations"] = clean
    return result


def load_goals(path: str | None = None) -> dict[str, Any]:
    """Читает цели, откатываясь на ``goals.json.bak`` при повреждении."""

    target = _goals_path(path)
    for candidate in (target, target + ".bak"):
        if not os.path.exists(candidate):
            continue
        try:
            with open(candidate, encoding="utf-8") as handle:
                goals = json.load(handle)
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(goals, dict):
            continue
        return normalize_goals(goals)
    return default_goals()


def save_goals(goals: Any, path: str | None = None) -> dict[str, Any]:
    """Атомарно сохраняет ``goals.json`` и обновляет ``.bak``.

    Запись идёт во временный файл рядом с целевым и затем ``os.replace``,
    поэтому обрыв питания или Ctrl+C не оставит полузаписанный JSON.
    Возвращает нормализованные данные, которые реально легли на диск.
    """

    target = _goals_path(path)
    clean = normalize_goals(goals)
    directory = os.path.dirname(os.path.abspath(target))

    # RLock, а не Lock: HTTP-слой уже держит GOALS_LOCK вокруг вызова.
    with GOALS_LOCK:
        os.makedirs(directory, exist_ok=True)

        if os.path.exists(target):
            try:
                shutil.copy2(target, target + ".bak")
            except OSError as exc:
                print(
                    f"Предупреждение: не удалось обновить резервную копию goals.json: {exc}",
                    file=sys.stderr,
                )

        descriptor, tmp = tempfile.mkstemp(prefix=os.path.basename(target) + ".", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(clean, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, target)
        except OSError:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
    return clean
