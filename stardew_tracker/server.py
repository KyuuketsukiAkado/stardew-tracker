"""Локальный HTTP-сервер дашборда и JSON API."""

from __future__ import annotations

import contextlib
import gzip
import json
import os
import secrets
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from .constants import SPRITE_FILES
from .errors import SaveError, TrackerError
from .goals import GOALS_LOCK, goals_signature, load_goals, normalize_goals, save_goals
from .i18n import L, normalize
from .paths import SPRITES_DIR
from .report import render
from .savefinder import find_saves
from .saveparser import clear_cache as clear_parse_cache
from .state import build_state, clear_state_cache, list_saves_info, secret_sections

_ALLOWED_METHODS = "GET, POST, OPTIONS"
_CSP = (
    "default-src 'self'; img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'"
)
# Имена, под которыми браузер обращается к серверу на loopback. Всё остальное в
# заголовке Host — признак DNS-rebinding: чужая страница заставила браузер
# ходить на 127.0.0.1 под своим доменом и теперь читает ваши данные «как свои».
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
# Сколько раз наблюдатель повторяет разбор одного и того же сломанного файла
# (задержка растёт вдвое: 2, 4, 8, 16, 32 с) и потом ждёт нового изменения.
_WATCH_RETRY_BASE = 2.0
_WATCH_RETRY_ATTEMPTS = 5
_UNSET: Any = object()


def client_state(state: dict[str, Any]) -> dict[str, Any]:
    """Состояние для браузера в живом режиме: без текста решений раздела «Секреты».

    Решения весят ~30 КБ и раньше уезжали в каждом ответе и в исходнике каждой
    страницы, хотя интерфейс обещает показывать их только после явного согласия.
    Теперь страница получает пометку ``secrets.lazy`` и после согласия запрашивает
    ``/api/secrets``. Это защита от случайного спойлера (просмотр исходника,
    отладчик, чужие глаза), а не секрет: данные по-прежнему отдаются любому, кто
    запросит их сам. В автономном отчёте (``build``) всё встроено, сервера там нет.
    """

    secrets = state.get("secrets")
    if not isinstance(secrets, dict) or "sections" not in secrets:
        return state
    light = {key: value for key, value in secrets.items() if key != "sections"}
    return {**state, "secrets": {**light, "lazy": True}}


class _Payload:
    """Состояние одной ревизии в виде готового JSON (и его gzip по требованию).

    Сериализация ~450 КБ стоит ~25 мс, а вкладка опрашивала её каждые 3 секунды.
    Теперь она делается один раз на ревизию и раздаётся всем клиентам.
    """

    __slots__ = ("_gzip", "raw", "rev")

    def __init__(self, rev: str, raw: bytes):
        self.rev = rev
        self.raw = raw
        self._gzip: bytes | None = None

    @property
    def gzipped(self) -> bytes:
        if self._gzip is None:
            self._gzip = gzip.compress(self.raw, compresslevel=5, mtime=0)
        return self._gzip


class TrackerApp:
    """Состояние приложения, общее для всех потоков HTTP-сервера.

    ``state`` неизменяем «вглубь»: любое обновление подменяет словарь целиком и
    увеличивает ревизию. Клиенты узнают об изменениях по ``rev`` (``/api/version``
    или ``ETag``), а не скачивая и сравнивая всё состояние.
    """

    def __init__(self, save: str | None = None, saves_dir: str | None = None):
        self.save = save
        self.saves_dir = saves_dir
        self.state: dict[str, Any] | None = None
        self.error: dict[str, Any] | None = None
        self.lock = threading.RLock()
        # ``epoch`` отличает ревизии разных запусков: после перезапуска счётчик
        # начинается заново, и без него открытая вкладка могла бы пропустить
        # обновление из-за совпадения номера.
        self.epoch = secrets.token_hex(4)
        self._revision = 0
        self._payload: _Payload | None = None
        self._goals_sig: Any = _UNSET
        self._secrets_json: bytes | None = None

    # ---- снимки состояния -------------------------------------------------
    def snapshot(self) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        with self.lock:
            return self.state, self.error

    def _bump(self) -> None:
        """Новая ревизия; вызывать под ``self.lock``."""

        self._revision += 1
        self._payload = None
        self._goals_sig = _UNSET  # следующий sync_goals() перечитает цели один раз

    def set_state(self, state: dict[str, Any] | None, error: dict[str, Any] | None = None) -> None:
        with self.lock:
            self.state = state
            self.error = error
            self._bump()

    def set_state_if_current(self, state: dict[str, Any], save: str | None, saves_dir: str | None) -> bool:
        """Применяет состояние, только если выбор сейва не менялся, пока оно строилось.

        Разбор большого сейва идёт секунды; если за это время пользователь
        переключил ферму, результат для прежнего сейва нельзя ставить поверх.
        """

        with self.lock:
            if (self.save, self.saves_dir) != (save, saves_dir):
                return False
            self.state = state
            self.error = None
            self._bump()
            return True

    def set_error(self, error: SaveError) -> None:
        info = error.to_dict()
        with self.lock:
            if info != self.error:  # повтор той же ошибки не должен дёргать клиентов
                self.error = info
                self._bump()

    def set_goals(self, goals: dict[str, Any]) -> None:
        with self.lock:
            if self.state is not None:
                self.state = {**self.state, "goals": goals}
                self._bump()

    def sync_goals(self) -> None:
        """Подхватывает правки ``goals.json`` снаружи: один ``stat`` на проверку."""

        signature = goals_signature()
        with self.lock:
            if self.state is None or signature == self._goals_sig:
                return
        # Чтение под тем же замком, что и запись из POST: иначе можно прочитать
        # старый файл между save_goals() и set_goals() и откатить свежие цели.
        # app.lock здесь не держим: POST берёт их в порядке GOALS_LOCK -> app.lock.
        with GOALS_LOCK:
            signature = goals_signature()
            goals = load_goals()
        with self.lock:
            if self.state is not None and self.state.get("goals") != goals:
                self.state = {**self.state, "goals": goals}
                self._bump()
            self._goals_sig = signature

    # ---- публикация для клиентов -----------------------------------------
    def version(self) -> dict[str, Any]:
        """Крошечный ответ ``/api/version``: менялось ли что-то с прошлого опроса."""

        self.sync_goals()
        with self.lock:
            state = self.state
            return {
                "rev": f"{self.epoch}-{self._revision}",
                "ready": state is not None,
                "save_mtime": state["meta"]["save_mtime"] if state else None,
            }

    def state_payload(self) -> _Payload | None:
        """JSON текущего состояния (кэшируется на ревизию) или ``None`` без сейва."""

        self.sync_goals()
        with self.lock:
            state, revision, cached = self.state, self._revision, self._payload
            rev = f"{self.epoch}-{revision}"
        if state is None:
            return None
        if cached is not None and cached.rev == rev:
            return cached
        payload = _Payload(rev, json.dumps(client_state(state), ensure_ascii=False).encode("utf-8"))
        with self.lock:
            if self._revision == revision:
                self._payload = payload
        return payload

    def secrets_json(self) -> bytes:
        """JSON разделов «Секреты» (не зависит от сейва, собирается один раз)."""

        cached = self._secrets_json
        if cached is None:
            cached = json.dumps({"sections": secret_sections()}, ensure_ascii=False).encode("utf-8")
            self._secrets_json = cached
        return cached

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
            self._bump()
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

    def _text(self, en: str, ru: str) -> str:
        """Message in the language the browser asked for (``Accept-Language``); English by default."""

        first = self.headers.get("Accept-Language", "").split(",")[0].split(";")[0]
        return ru if normalize(first) == "ru" else en

    def _host_allowed(self) -> bool:
        """Защита от DNS-rebinding: на loopback принимаем только свои имена хоста."""

        allowed = getattr(self.server, "allowed_hosts", None)
        if allowed is None:  # явный ``--host 0.0.0.0``: пользователь открыл доступ сам
            return True
        header = self.headers.get("Host")
        return not header or _host_name(header) in allowed

    def _reject_host(self) -> None:
        self._json(
            403,
            {
                "error": self._text(
                    "Invalid Host header: use 127.0.0.1 or localhost",
                    "Недопустимый заголовок Host: обращайтесь по 127.0.0.1 или localhost",
                )
            },
        )

    def _etag_matches(self, etag: str) -> bool:
        header = self.headers.get("If-None-Match", "")
        candidates = {token.strip().removeprefix("W/") for token in header.split(",")}
        return etag in candidates or "*" in candidates

    def _send_state(self, payload: _Payload) -> None:
        """Состояние с ETag: 304 для неизменившегося и gzip для клиентов, которые его принимают."""

        etag = f'"{payload.rev}"'
        headers = {"ETag": etag, "Cache-Control": "no-cache", "Vary": "Accept-Encoding"}
        if self._etag_matches(etag):
            self.send_response(304)
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            return
        body = payload.raw
        if "gzip" in self.headers.get("Accept-Encoding", "").lower():
            body = payload.gzipped
            headers["Content-Encoding"] = "gzip"
        self._send(200, body, extra_headers=headers)

    # ---- GET --------------------------------------------------------------
    def do_OPTIONS(self) -> None:
        if not self._host_allowed():
            self._reject_host()
            return
        # Дашборд живёт на том же origin; произвольным сайтам CORS не нужен.
        self.send_response(204)
        self.send_header("Allow", _ALLOWED_METHODS)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        if not self._host_allowed():
            self._reject_host()
            return
        # GET ничего не меняет: раньше ``/?save=…`` переключал активный сейв, и любая
        # страница могла дёрнуть это межсайтовым запросом. Переключение — только
        # ``POST /api/saves/select`` (оно к тому же требует application/json).
        path = urlsplit(self.path).path

        if path in ("/", "/index.html"):
            state, error = self.application.snapshot()
            try:
                page = render(client_state(state) if state is not None else None, "live", error=error)
                self._send(200, page, "text/html; charset=utf-8")
            except FileNotFoundError:
                self._send(
                    500,
                    self._text("assets/dashboard.html is missing", "Нет файла assets/dashboard.html"),
                    "text/plain; charset=utf-8",
                )
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

        if path == "/api/version":
            self._json(200, self.application.version())
            return

        if path == "/api/secrets":
            # Страница просит это только после согласия на спойлеры (см. client_state).
            self._send(200, self.application.secrets_json())
            return

        if path == "/api/state":
            payload = self.application.state_payload()
            if payload is not None:
                self._send_state(payload)
            else:
                _state, error = self.application.snapshot()
                self._json(404, {"error": error or {"title": self._text("No save loaded", "Сейв не загружен")}})
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
                self.application.refresh(clear_caches=True)
                payload = self.application.state_payload()
                if payload is None:  # состояние успели сбросить — отдаём как «нет сейва»
                    self._json(404, {"error": {"title": self._text("No save loaded", "Сейв не загружен")}})
                else:
                    self._send_state(payload)
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
            self._json(400, {"error": self._text("Invalid Content-Length", "Некорректный Content-Length")})
            return None
        if length < 0:
            self._json(400, {"error": self._text("Invalid request size", "Некорректный размер запроса")})
            return None
        if length > 1_000_000:
            self._json(
                413, {"error": self._text("Request too large; the limit is 1 MB", "Слишком большой запрос; лимит 1 МБ")}
            )
            return None
        if length and "application/json" not in self.headers.get("Content-Type", "").lower():
            self._json(
                415,
                {
                    "error": self._text(
                        "Expected Content-Type: application/json", "Ожидался Content-Type: application/json"
                    )
                },
            )
            return None
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, UnicodeDecodeError) as exc:
            self._json(400, {"error": self._text(f"Invalid JSON: {exc}", f"Некорректный JSON: {exc}")})
            return None
        if not isinstance(payload, dict):
            self._json(
                400, {"error": self._text("The request JSON must be an object", "JSON запроса должен быть объектом")}
            )
            return None
        return payload

    def do_POST(self) -> None:
        if not self._host_allowed():
            self._reject_host()
            return
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
            self._json(
                400, {"error": self._text("goals and tasks must be arrays", "goals и tasks должны быть массивами")}
            )
            return
        if not all(isinstance(item, dict) for item in goals_value + tasks_value):
            self._json(
                400,
                {
                    "error": self._text(
                        "goals and tasks items must be objects", "Элементы goals и tasks должны быть объектами"
                    )
                },
            )
            return
        if "annotations" in payload and not isinstance(payload["annotations"], dict):
            self._json(400, {"error": self._text("annotations must be an object", "annotations должен быть объектом")})
            return

        try:
            # Чтение сохранённых пометок, нормализация и запись — под одним
            # замком: иначе два одновременных POST теряли пометки друг друга.
            with GOALS_LOCK:
                annotations = (
                    payload["annotations"] if "annotations" in payload else load_goals().get("annotations", {})
                )
                goals = normalize_goals({"goals": goals_value, "tasks": tasks_value, "annotations": annotations})
                save_goals(goals)
                self.application.set_goals(goals)
            self._json(200, {"ok": True, "goals": goals})
        except OSError as exc:
            # Ошибка диска — это сбой сервера, а не «плохой запрос» клиента.
            self._json(
                500,
                {"error": self._text(f"Could not write goals.json: {exc}", f"Не удалось записать goals.json: {exc}")},
            )
        except Exception as exc:
            self._json(400, {"error": str(exc)})

    def _post_select_save(self, payload: dict[str, Any]) -> None:
        requested = str(payload.get("path") or "").strip()
        if not requested:
            self._json(400, {"error": self._text("No save path given", "Не указан путь к сейву")})
            return
        target = os.path.abspath(requested)
        if target not in self.application.allowed_save_paths():
            self._json(403, {"error": self._text("Not an allowed save file", "Недопустимый файл сохранения")})
            return
        try:
            state = self.application.activate(target)
            self._json(200, client_state(state))
        except SaveError as exc:
            self._json(400, {"error": exc.to_dict()})


def make_handler(app: TrackerApp) -> type[_BaseHandler]:
    """Фабрика обработчика: у каждого сервера свой ``TrackerApp``."""

    class Handler(_BaseHandler):
        application = app

    return Handler


def _host_name(header: str) -> str:
    """Имя хоста из заголовка ``Host`` без порта: ``localhost:8777`` -> ``localhost``."""

    value = header.strip().lower()
    if value.startswith("["):  # IPv6: [::1]:8777
        end = value.find("]")
        return value[1:end] if end > 0 else value
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def allowed_hosts_for(bind_host: str) -> frozenset[str] | None:
    """Допустимые значения ``Host`` для адреса привязки; ``None`` — без ограничений.

    Привязка к loopback — режим «только этот компьютер», и там чужие имена
    хоста отклоняются. Явный ``--host 0.0.0.0`` или адрес в локальной сети —
    сознательное решение открыть доступ, имена заранее неизвестны.
    """

    host = bind_host.strip("[]").lower()
    if host in _LOOPBACK_HOSTS or host.startswith("127."):
        return _LOOPBACK_HOSTS | {host}
    return None


class TrackerHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], app: TrackerApp):
        self.app = app
        self.allowed_hosts = allowed_hosts_for(str(address[0]))
        super().__init__(address, make_handler(app))


def watch_loop(app: TrackerApp, stop: threading.Event, interval: float = 2.0) -> None:
    """Следит за mtime сейва и пересобирает состояние при изменении.

    Подпись файла запоминается только после УСПЕШНОГО разбора. Игра пишет
    большой сейв не мгновенно, а антивирус или сама игра могут ненадолго
    удерживать файл: раньше такой сбой помечал подпись как «обработанную», и
    состояние оставалось старым до следующей записи сейва. Теперь неудачный
    разбор повторяется с нарастающей паузой, но не бесконечно: сломанный файл
    в 25 МБ нельзя перечитывать каждые две секунды.
    """

    last_signature: tuple[str, int, int] | None = None
    failed_signature: tuple[str, int, int] | None = None
    failures = 0
    retry_at = 0.0
    last_message = ""
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
                    if signature != failed_signature:  # файл изменился — счётчик сбоев не нужен
                        failed_signature, failures, retry_at = None, 0, 0.0
                    if failures < _WATCH_RETRY_ATTEMPTS and time.monotonic() >= retry_at:
                        try:
                            state = build_state(current_save, current_dir)
                        except (SaveError, OSError):
                            failed_signature = signature
                            failures += 1
                            retry_at = time.monotonic() + _WATCH_RETRY_BASE * 2 ** (failures - 1)
                            raise
                        last_signature = signature
                        failed_signature, failures, last_message = None, 0, ""
                        if app.set_state_if_current(state, current_save, current_dir):
                            print(
                                f"[{time.strftime('%H:%M:%S')}] "
                                + L("save updated -> state rebuilt", "сейв обновлён -> состояние пересобрано")
                            )
        except SaveError as exc:
            # Ошибки сейва показываем в интерфейсе (set_error), а не только в консоли.
            app.set_error(exc)
            if str(exc) != last_message:
                last_message = str(exc)
                print("watch:", exc, file=sys.stderr)
        except Exception as exc:
            if str(exc) != last_message:  # одну и ту же ошибку не печатаем каждые 2 с
                last_message = str(exc)
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
        season_en = str(meta["season"]).capitalize()
        print(
            L(
                f'Farm "{meta["farm"]}", {meta["farmer"]}, {season_en} {meta["day"]}, year {meta["year"]}',
                f"Ферма «{meta['farm']}», {meta['farmer']}, {meta['season_ru']} {meta['day']}, год {meta['year']}",
            )
        )
        print(L(f"Save: {meta['save_path']}", f"Сейв: {meta['save_path']}"))
        for warning in meta["warnings"]:
            print("  ! " + warning)
    except SaveError as exc:
        if save:
            raise
        app.set_error(exc)
        print(str(exc), file=sys.stderr)
        print(
            "\n"
            + L(
                'The server is waiting for a save - create or copy one, then press "Refresh" in the browser.',
                "Сервер запущен в режиме ожидания сейва — создайте/скопируйте сейв и нажмите «Обновить» в браузере.",
            )
        )

    stop = threading.Event()
    if watch:
        threading.Thread(target=watch_loop, args=(app, stop), daemon=True).start()

    httpd: TrackerHTTPServer | None = None
    last_error: OSError | None = None
    for candidate in range(port, port + 12):
        try:
            httpd = TrackerHTTPServer((host, candidate), app)
            port = candidate
            break
        except OSError as exc:
            last_error = exc
    if httpd is None:
        stop.set()
        raise TrackerError(
            "port_busy",
            L("Could not bind a port", "Не удалось занять порт"),
            L(
                f"Ports {port}-{port + 11} on {host or 'all interfaces'} are unavailable: {last_error}",
                f"Порты {port}–{port + 11} на {host or 'всех интерфейсах'} недоступны: {last_error}",
            ),
            [
                L(
                    "Close the other tracker instance or pass a free port: --port 9000.",
                    "Закройте другой экземпляр трекера или укажите свободный порт: --port 9000.",
                ),
                L(
                    "If the system holds the port, pick a number above 1024.",
                    "Если порт занят системой, выберите номер выше 1024.",
                ),
            ],
        )

    browser_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host  # nosec B104 - сравнение, не bind
    url = f"http://{browser_host}:{port}/"
    print("\n" + L(f"Tracker: {url}   (Ctrl+C to stop)", f"Трекер: {url}   (Ctrl+C — остановить)"))
    if open_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n" + L("Stopped.", "Остановлено."))
    finally:
        stop.set()
        httpd.server_close()
