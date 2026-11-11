"""Permission to look for save files without being pointed at them.

Pointing the tracker at a file or a folder (``--save``, ``--saves-dir``, a folder typed
into the page) is the user's own decision and needs nothing more. Looking into the
*standard* Stardew Valley folders on its own is different: until the user has said yes,
the tracker lists, opens and reads nothing there. The answer is remembered in
``settings.json`` (next to ``goals.json``) and can be withdrawn at any time.

``STARDEW_TRACKER_ALLOW_SCAN=1`` means "yes" for one process without writing anything;
it is meant for scripts and CI. A user who withdraws permission in the page overrides
that environment grant until the process restarts.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading
from typing import Any

from . import paths
from .errors import ConsentRequired

ALLOW_ENV = "STARDEW_TRACKER_ALLOW_SCAN"

_LOCK = threading.RLock()
# Used only when settings.json cannot be written (read-only folder): the answer then
# lasts until the program ends instead of crashing it.
_memory: dict[str, Any] | None = None
# A browser withdrawal must override an environment grant for this process.
# The environment may grant access again on a future launch.
_env_withdrawn = False


def _defaults() -> dict[str, Any]:
    return {"scan_standard_folders": False, "extra_folders": []}


def load() -> dict[str, Any]:
    """The saved answer; a missing or damaged file means "not asked yet"."""

    with _LOCK:
        if _memory is not None:
            return {**_memory, "extra_folders": list(_memory["extra_folders"])}
        try:
            with open(paths.SETTINGS_FILE, encoding="utf-8") as handle:
                raw = json.load(handle)
        except (OSError, ValueError):
            raw = {}
        data = _defaults()
        if isinstance(raw, dict):
            data["scan_standard_folders"] = raw.get("scan_standard_folders") is True
            folders = raw.get("extra_folders")
            if isinstance(folders, list):
                data["extra_folders"] = [item for item in folders if isinstance(item, str) and item]
        return data


def _save(data: dict[str, Any]) -> None:
    global _memory
    with _LOCK:
        target = paths.SETTINGS_FILE
        directory = os.path.dirname(os.path.abspath(target))
        tmp = ""
        try:
            os.makedirs(directory, exist_ok=True)
            descriptor, tmp = tempfile.mkstemp(prefix="settings.", suffix=".tmp", dir=directory)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, target)
            _memory = None
        except OSError:
            if tmp:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
            _memory = {**data, "extra_folders": list(data["extra_folders"])}


def allowed_by_environment() -> bool:
    return os.environ.get(ALLOW_ENV, "").strip().lower() in {"1", "true", "yes"}


def standard_allowed() -> bool:
    """May the tracker look into the standard Stardew Valley folders by itself?"""

    return (allowed_by_environment() and not _env_withdrawn) or bool(load()["scan_standard_folders"])


def extra_folders() -> list[str]:
    """Folders the user added by hand; they are always scanned."""

    return list(load()["extra_folders"])


def folders_to_scan(standard: list[str]) -> list[str]:
    """Folders the automatic search may open now, or :class:`ConsentRequired` if none."""

    extra = extra_folders()
    if standard_allowed():
        return [*standard, *extra]
    if extra:
        return extra
    raise ConsentRequired(standard)


def allow_standard(allow: bool) -> None:
    global _env_withdrawn
    with _LOCK:
        data = load()
        data["scan_standard_folders"] = bool(allow)
        _save(data)
        _env_withdrawn = not allow


def add_folder(path: str) -> str:
    """Remember a folder chosen by the user. Raises ``ValueError`` if it is not a folder."""

    folder = os.path.abspath(os.path.expanduser(path.strip()))
    if not os.path.isdir(folder):
        raise ValueError(folder)
    data = load()
    if folder not in data["extra_folders"]:
        data["extra_folders"].append(folder)
        _save(data)
    return folder


def forget() -> None:
    """Withdraw every permission, including an environment grant for this run."""

    global _env_withdrawn
    with _LOCK:
        _save(_defaults())
        _env_withdrawn = True


def status(standard: list[str]) -> dict[str, Any]:
    """What the page shows: where the tracker would look, and what it has been allowed."""

    data = load()
    return {
        "standard": list(standard),
        "standard_allowed": standard_allowed(),
        "by_environment": allowed_by_environment() and not _env_withdrawn,
        "extra": list(data["extra_folders"]),
    }
