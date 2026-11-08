"""Пользовательские исключения трекера."""

from __future__ import annotations

from . import paths


class SaveError(SystemExit):
    """Понятная пользователю ошибка чтения сейва или данных.

    Наследуется от ``SystemExit``, чтобы CLI завершался с сообщением без
    трассировки стека. HTTP-слой перехватывает исключение явно и отдаёт
    структурированный JSON.
    """

    def __init__(self, kind: str, title: str, detail: str, steps: list[str]):
        self.kind = kind
        self.title = title
        self.detail = detail
        self.steps = list(steps)
        lines = [f"Ошибка: {title}", f"  {detail}"]
        if self.steps:
            lines.append("Что сделать:")
            lines.extend(f"  {idx}. {step}" for idx, step in enumerate(self.steps, 1))
        super().__init__("\n".join(lines))

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "title": self.title,
            "detail": self.detail,
            "steps": self.steps,
        }


class DataError(SaveError):
    """Справочники ``data/*.json`` отсутствуют или повреждены."""

    def __init__(self, title: str, detail: str):
        where = "рядом с приложением StardewTracker" if paths.FROZEN else "рядом с tracker.py"
        super().__init__(
            "data_error",
            title,
            detail,
            [
                f"Убедитесь, что папка data/ распакована {where}.",
                "Пересоберите справочники командой python build_data.py --content-dir <папка Content>.",
            ],
        )
