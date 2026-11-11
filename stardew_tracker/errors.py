"""User-facing exceptions of the tracker (bilingual: English and Russian)."""

from __future__ import annotations

from . import paths
from .i18n import LANGUAGES, L, pick


class TrackerError(Exception):
    """An error a person can act on, with steps to fix it.

    A regular exception, not ``SystemExit``: ``except Exception`` in server
    threads catches it like any other, and a forgotten ``except`` no longer
    kills a handler thread silently. The console entry point turns it into a
    message and an exit code in :func:`stardew_tracker.cli.run`; the HTTP layer
    turns it into structured JSON via :meth:`to_dict`.

    ``title``, ``detail`` and ``steps`` may be plain strings or bilingual
    :class:`~stardew_tracker.i18n.Text` values. The console shows the current
    language; the page receives both languages under ``i18n`` and picks its own.
    """

    def __init__(self, kind: str, title: str, detail: str, steps: list[str]):
        self.kind = kind
        self.title = title
        self.detail = detail
        self.steps = list(steps)
        lines = [f"{L('Error: ', 'Ошибка: ')}{title}", f"  {detail}"]
        if self.steps:
            lines.append(str(L("What to do:", "Что сделать:")))
            lines.extend(f"  {idx}. {step}" for idx, step in enumerate(self.steps, 1))
        super().__init__("\n".join(lines))

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "title": str(self.title),
            "detail": str(self.detail),
            "steps": [str(step) for step in self.steps],
            # Both languages: the page picks the one the user chose.
            "i18n": {
                lang: {
                    "title": pick(self.title, lang),
                    "detail": pick(self.detail, lang),
                    "steps": [pick(step, lang) for step in self.steps],
                }
                for lang in LANGUAGES
            },
        }


class SaveError(TrackerError):
    """Failure while locating or reading a save file."""


class DataError(SaveError):
    """The ``data/*.json`` reference files are missing or damaged."""

    def __init__(self, title: str, detail: str):
        where = L(
            "next to the StardewTracker app" if paths.FROZEN else "next to tracker.py",
            "рядом с приложением StardewTracker" if paths.FROZEN else "рядом с tracker.py",
        )
        super().__init__(
            "data_error",
            title,
            detail,
            [
                L(
                    f"Make sure the data/ folder is unpacked {where.translations['en']}.",
                    f"Убедитесь, что папка data/ распакована {where.translations['ru']}.",
                ),
                L(
                    "Rebuild the reference data with: python build_data.py --content-dir <Content folder>.",
                    "Пересоберите справочники командой python build_data.py --content-dir <папка Content>.",
                ),
            ],
        )
