"""Локальный HTTP-сервер дашборда и JSON API."""

from __future__ import annotations

import contextlib
import json
import os
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .constants import SPRITE_FILES
from .errors import SaveError
from .goals import GOALS_LOCK, load_goals, normalize_goals, save_goals
from .paths import SPRITES_DIR
from .render import render
from .savefinder import find_saves
from .saveparser import clear_cache as clear_parse_cache
from .state import build_state, clear_state_cache, list_saves_info

_ALLOWED_METHODS = "GET, POST, OPTIONS"
_CSP = (
    "default-src 'self'; img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'"
)


class TrackerApp:
    """Состояние приложения, общее для всех потоков HTTP-сервера."""

    def __init__(self, save: str | None = None, saves_dir: str | None = None):
        self.save = save
        self.saves_dir = saves_dir
        self.state: dict[str, Any] | None = None
        self.error: dict[str, Any] | None = None
        self.lock = threading.RLock()

    # ---- снимки состояния -------------------------------------------------
    def snapshot(self) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        with self.lock:
            return self.state, self.error

    def set_state(self, state: dict[str, Any] | None, error: dict[str, Any] | None = None) -> None:
        with self.lock:
            self.state = state
            self.error = error

    def set_error(self, error: SaveError) -> None:
        with self.lock:
            self.error = error.to_dict()

    def set_goals(self, goals: dict[str, Any]) -> None:
        with self.lock:
            if self.state is not None:
                self.state["goals"] = goals

    # ---- операции ---------------------------------------------------------
    def load(self) -> dict[str, Any]:
        state = build_state(self.save, self.saves_dir)
        self.set_state(state)
        return state

    def refresh(self, clear_caches: bool = False) -> dict[str, Any]:
        if clear_caches:
            clear_parse_cache()
            clear_state_cache()
        state = build_state(self.save, self.saves_dir)
        self.set_state(state)
        return state

    def activate(self, path: str) -> dict[str, Any]:
        """Переключает активный сейв только после успешного разбора."""

        state = build_state(path, None)
        with self.lock:
            self.save = path
            self.state = state
            self.error = None
        return state

    def allowed_save_paths(self) -> set[str]:
        """Белый список сейвов, на которые можно переключиться из UI."""

        # Без начального значения ``paths`` падал UnboundLocalError, если
        # поиск сейвов выбрасывал SaveError (папка исчезла, нет прав).
        paths: list[str] = []
        with contextlib.suppress(SaveError):
            paths = find_saves(saves_dir=self.saves_dir)
        allowed = {os.path.abspath(path) for path in paths}
        if self.save:
            allowed.add(os.path.abspath(self.save))
            parent = os.path.dirname(os.path.dirname(os.path.abspath(self.save)))
            if os.path.isdir(parent):
                with contextlib.suppress(SaveError):
                    allowed.update(os.path.abspath(path) for path in find_saves(saves_dir=parent))
        return allowed


class _BaseHandler(BaseHTTPRequestHandler):
    application: TrackerApp

    # Без версии Python в заголовке Server.
    server_version = "StardewTracker"
    sys_version = ""
    timeout = 30

    def version_string(self) -> str:
        return self.server_version

    def log_message(self, fmt: str, *args: Any) -> None:
        """Не логируем пути: в них бывают имена ферм и локальные каталоги."""

    # ---- ответы -----------------------------------------------------------
    def _send(
        self,
        code: int,
        body: str | bytes,
        ctype: str = "application/json; charset=utf-8",
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        payload = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header(
            "Cache-Control",
            (extra_headers or {}).get("Cache-Control", "no-store"),
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", _CSP)
        if extra_headers:
            for key, value in extra_headers.items():
                if key != "Cache-Control":
                    self.send_header(key, value)
        self.end_headers()
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):
            self.wfile.write(payload)

    def _json(self, code: int, value: Any, extra_headers: dict[str, str] | None = None) -> None:
        self._send(code, json.dumps(value, ensure_ascii=False), extra_headers=extra_headers)

    # ---- GET --------------------------------------------------------------
    def do_OPTIONS(self) -> None:
        # Дашборд живёт на том же origin; произвольным сайтам CORS не нужен.
        self.send_response(204)
        self.send_header("Allow", _ALLOWED_METHODS)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        requested_save = (query.get("save") or [""])[0]

        if requested_save and path in ("/", "/index.html", "/api/state"):
            target = os.path.abspath(requested_save)
            if target in self.application.allowed_save_paths():
                try:
                    self.application.activate(target)
                except SaveError as exc:
                    self.application.set_error(exc)

        if path in ("/", "/index.html"):
            state, error = self.application.snapshot()
            try:
                self._send(200, render(state, "live", error=error), "text/html; charset=utf-8")
            except FileNotFoundError:
                self._send(500, "Нет файла assets/dashboard.html", "text/plain; charset=utf-8")
            return

        if path.startswith("/assets/sprites/"):
            filename = os.path.basename(path)
            file_path = os.path.join(SPRITES_DIR, filename)
            if filename in SPRITE_FILES and os.path.isfile(file_path):
                with open(file_path, "rb") as handle:
                    png = handle.read()
                self._send(200, png, "image/png", {"Cache-Control": "public, max-age=86400"})
            else:
                self._send(404, b"not found", "text/plain; charset=utf-8")
            return

        if path == "/api/state":
            with self.application.lock:
                state = self.application.state
                error = self.application.error
                if state is not None:
                    state["goals"] = load_goals()
            if state is not None:
                self._json(200, state)
            else:
                self._json(404, {"error": error or {"title": "Сейв не загружен"}})
            return

        if path == "/api/saves":
            try:
                saves = list_saves_info(
                    saves_dir=self.application.saves_dir,
                    explicit=None if self.application.saves_dir else self.application.save,
                )
                if self.application.save and not self.application.saves_dir:
                    parent = os.path.dirname(os.path.dirname(os.path.abspath(self.application.save)))
                    if os.path.isdir(parent):
                        known = {item["path"] for item in saves}
                        for item in list_saves_info(saves_dir=parent):
                            if item["path"] not in known:
                                saves.append(item)
                state, _error = self.application.snapshot()
                active = state["meta"]["save_path"] if state else (self.application.save or "")
                self._json(200, {"saves": saves, "active": active})
            except SaveError as exc:
                self._json(200, {"saves": [], "active": "", "error": exc.to_dict()})
            return

        if path == "/api/goals/export":
            blob = json.dumps(load_goals(), ensure_ascii=False, indent=2)
            self._send(
                200,
                blob,
                "application/json; charset=utf-8",
                {"Content-Disposition": 'attachment; filename="stardew-goals.json"'},
            )
            return

        if path == "/api/refresh":
            try:
                state = self.application.refresh(clear_caches=True)
                self._json(200, state)
            except SaveError as exc:
                self.application.set_error(exc)
                self._json(500, {"error": exc.to_dict()})
            except Exception as exc:
                self._json(500, {"error": f"{type(exc).__name__}: {exc}"})
            return

        self._json(404, {"error": "not found"})

    # ---- POST -------------------------------------------------------------
    def _read_payload(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._json(400, {"error": "Некорректный Content-Length"})
            return None
        if length < 0:
            self._json(400, {"error": "Некорректный размер запроса"})
            return None
        if length > 1_000_000:
            self._json(413, {"error": "Слишком большой запрос; лимит 1 МБ"})
            return None
        if length and "application/json" not in self.headers.get("Content-Type", "").lower():
            self._json(415, {"error": "Ожидался Content-Type: application/json"})
            return None
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, UnicodeDecodeError) as exc:
            self._json(400, {"error": f"Некорректный JSON: {exc}"})
            return None
        if not isinstance(payload, dict):
            self._json(400, {"error": "JSON запроса должен быть объектом"})
            return None
        return payload

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        payload = self._read_payload()
        if payload is None:
            return

        if path == "/api/goals":
            self._post_goals(payload)
            return
        if path == "/api/saves/select":
            self._post_select_save(payload)
            return
        self._json(404, {"error": "not found"})

    def _post_goals(self, payload: dict[str, Any]) -> None:
        goals_value = payload.get("goals", [])
        tasks_value = payload.get("tasks", [])
        if not isinstance(goals_value, list) or not isinstance(tasks_value, list):
            self._json(400, {"error": "goals и tasks должны быть массивами"})
            return
        if not all(isinstance(item, dict) for item in goals_value + tasks_value):
            self._json(400, {"error": "Элементы goals и tasks должны быть объектами"})
            return
        if "annotations" in payload and not isinstance(payload["annotations"], dict):
            self._json(400, {"error": "annotations должен быть объектом"})
            return

        try:
            goals = normalize_goals(
                {
                    "goals": goals_value,
                    "tasks": tasks_value,
                    "annotations": payload.get("annotations", load_goals().get("annotations", {})),
                }
            )
            with GOALS_LOCK:
                save_goals(goals)
                self.application.set_goals(goals)
            self._json(200, {"ok": True, "goals": goals})
        except OSError as exc:
            # Ошибка диска — это сбой сервера, а не «плохой запрос» клиента.
            self._json(500, {"error": f"Не удалось записать goals.json: {exc}"})
        except Exception as exc:
            self._json(400, {"error": str(exc)})

    def _post_select_save(self, payload: dict[str, Any]) -> None:
        requested = str(payload.get("path") or "").strip()
        if not requested:
            self._json(400, {"error": "Не указан путь к сейву"})
            return
        target = os.path.abspath(requested)
        if target not in self.application.allowed_save_paths():
            self._json(403, {"error": "Недопустимый файл сохранения"})
            return
        try:
            state = self.application.activate(target)
            self._json(200, state)
        except SaveError as exc:
            self._json(400, {"error": exc.to_dict()})


def make_handler(app: TrackerApp) -> type[_BaseHandler]:
    """Фабрика обработчика: у каждого сервера свой ``TrackerApp``."""

    class Handler(_BaseHandler):
        application = app

    return Handler


class TrackerHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], app: TrackerApp):
        self.app = app
        super().__init__(address, make_handler(app))


def watch_loop(app: TrackerApp, stop: threading.Event, interval: float = 2.0) -> None:
    """Следит за mtime сейва и пересобирает состояние при изменении."""

    last_signature: tuple[str, int, int] | None = None
    while not stop.is_set():
        try:
            with app.lock:
                current_save, current_dir = app.save, app.saves_dir
            paths = find_saves(saves_dir=current_dir, explicit=current_save)
            if paths:
                selected = paths[0]
                stat = os.stat(selected)
                signature = (os.path.abspath(selected), stat.st_mtime_ns, stat.st_size)
                if signature != last_signature:
                    last_signature = signature
                    app.set_state(build_state(current_save, current_dir))
                    print(f"[{time.strftime('%H:%M:%S')}] сейв обновлён -> состояние пересобрано")
        except SaveError as exc:
            # SaveError наследуется от SystemExit: без явного перехвата поток
            # наблюдателя молча умирал при исчезновении сейва.
            print("watch:", exc, file=sys.stderr)
        except Exception as exc:
            print("watch:", exc, file=sys.stderr)
        stop.wait(interval)


def serve(
    port: int = 8777,
    save: str | None = None,
    saves_dir: str | None = None,
    open_browser: bool = True,
    watch: bool = True,
    host: str = "127.0.0.1",
) -> None:
    """Запускает локальный сервер; при явном неверном ``--save`` падает."""

    app = TrackerApp(save, saves_dir)
    try:
        state = app.load()
        meta = state["meta"]
        print(f"Ферма «{meta['farm']}», {meta['farmer']}, {meta['season_ru']} {meta['day']}, год {meta['year']}")
        print(f"Сейв: {meta['save_path']}")
        for warning in meta["warnings"]:
            print("  ! " + warning)
    except SaveError as exc:
        if save:
            raise
        app.set_error(exc)
        print(str(exc), file=sys.stderr)
        print("\nСервер запущен в режиме ожидания сейва — создайте/скопируйте сейв и нажмите «Обновить» в браузере.")

    stop = threading.Event()
    if watch:
        threading.Thread(target=watch_loop, args=(app, stop), daemon=True).start()

    httpd: TrackerHTTPServer | None = None
    for candidate in range(port, port + 12):
        try:
            httpd = TrackerHTTPServer((host, candidate), app)
            port = candidate
            break
        except OSError:
            continue
    if httpd is None:
        sys.exit("Не удалось занять порт")

    browser_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host  # nosec B104 - сравнение, не bind
    url = f"http://{browser_host}:{port}/"
    print(f"\nТрекер: {url}   (Ctrl+C — остановить)")
    if open_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено.")
    finally:
        stop.set()
        httpd.server_close()
