"""Пользовательские исключения трекера."""

from __future__ import annotations

from . import paths


class TrackerError(Exception):
    """Понятная пользователю ошибка с шагами решения.

    Обычное исключение, а не ``SystemExit``: ``except Exception`` в серверных
    потоках ловит его как любое другое, и забытый ``except`` больше не убивает
    поток обработчика молча (``SystemExit`` в потоке не печатает ничего, а
    клиент получал оборванное соединение). Консольный запуск превращает его в
    сообщение и код выхода в :func:`stardew_tracker.cli.run`, HTTP-слой — в
    структурированный JSON через :meth:`to_dict`.
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


class SaveError(TrackerError):
    """Ошибка поиска или чтения файла сохранения."""


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
