"""Локальный HTTP-сервер: отдаёт интерфейс и принимает команды от окна."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import REPO_URL, __version__, system
from .jobs import Manager
from .settings import LANG_RE, ApiError, Settings, clean_opts
from .tools import Tools
from .ytdlp import fetch_info, normalize_url

log = logging.getLogger(__name__)

HOST = "127.0.0.1"
WEB = Path(__file__).resolve().parent / "web"
MIME = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
    ".ico": "image/x-icon", ".json": "application/json", ".woff2": "font/woff2", ".woff": "font/woff",
}


class Context:
    """Всё, что нужно обработчику запросов. Окно приложения подставляет свои функции."""

    def __init__(self, paths: system.Paths, settings: Settings | None = None, tools: Tools | None = None,
                 manager: Manager | None = None):
        self.paths = paths
        self.settings = settings
        self.tools = tools
        self.manager = manager
        self.port = 0
        self.last_seen = time.time()
        self.show_window = None
        self.pick_folder = None


class Handler(BaseHTTPRequestHandler):
    ctx: Context
    server_version = "Kachalka"

    def log_message(self, *args):
        pass

    def host_ok(self) -> bool:
        # Проверка Host защищает от DNS rebinding: чужой домен, указывающий на 127.0.0.1.
        port = self.ctx.port
        return self.headers.get("Host", "") in (f"{HOST}:{port}", f"localhost:{port}")

    def send_json(self, data, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_api_error(self, e: ApiError):
        self.send_json({"error": e.message, "hint": e.hint, "raw": e.raw}, e.status)

    def starting(self, path: str) -> bool:
        """Порт занят сразу при запуске, а остальное ещё готовится: отвечаем только на ping и show."""
        if self.ctx.manager is not None or path in ("/api/ping", "/api/show"):
            return False
        self.send_json({"error": "Качалка ещё запускается."}, 503)
        return True

    def do_GET(self):
        if not self.host_ok():
            return self.send_error(403)
        path = urlparse(self.path).path
        if self.starting(path):
            return
        if not path.startswith("/api/"):
            return self.static(path)
        try:
            self.send_json(self.api_get(path))
        except ApiError as e:
            self.send_api_error(e)

    def do_POST(self):
        # Свой заголовок не даёт чужим сайтам слать запросы на localhost: без CORS его не поставить.
        if not self.host_ok() or self.headers.get("X-Kachalka") != "1":
            return self.send_error(403)
        if self.starting(urlparse(self.path).path):
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}") if length else {}
            if not isinstance(body, dict):
                raise ValueError("ожидался объект")
            self.send_json(self.api_post(urlparse(self.path).path, body))
        except ApiError as e:
            self.send_api_error(e)
        except (ValueError, TypeError) as e:
            self.send_json({"error": f"Неверный запрос: {e}"}, 400)

    def static(self, path: str):
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (WEB / rel).resolve()
        if WEB.resolve() not in target.parents or not target.is_file():
            return self.send_error(404)
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(target.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    # -- чтение
    def api_get(self, path: str):
        ctx = self.ctx
        if path == "/api/ping":
            return {"ok": True, "app": "kachalka", "version": __version__,
                    "seen_ago": round(time.time() - ctx.last_seen, 1)}
        if path == "/api/jobs":
            ctx.last_seen = time.time()
            return {"jobs": ctx.manager.list(), "tools": ctx.tools.snapshot()}
        if path == "/api/settings":
            return self.settings_payload()
        if path == "/api/clipboard":
            text = system.clipboard_text().strip()
            first = text.split()[0] if text else ""
            return {"url": first if re.match(r"^https?://\S+$", first) and len(first) < 2000 else ""}
        raise ApiError("Нет такого адреса.", status=404)

    def settings_payload(self) -> dict:
        return {
            "settings": self.ctx.settings.get(),
            "home": str(Path.home()),
            "platform": system.PLATFORM,
            "version": __version__,
            "repo": REPO_URL,
            "tools": self.ctx.tools.snapshot(),
        }

    # -- действия
    def api_post(self, path: str, body: dict):
        ctx = self.ctx
        m = ctx.manager
        if path == "/api/info":
            if not ctx.tools.ready:
                raise ApiError("Качалка ещё скачивает нужные программы. Подожди немного.", "setup", status=409)
            url = normalize_url(body.get("url"))
            return fetch_info(ctx.tools, url, bool(body.get("playlist")), ctx.settings.get())
        if path == "/api/download":
            items = body.get("items") or []
            if not items or not isinstance(items, list):
                raise ApiError("Нечего скачивать: выбери хотя бы одно видео.")
            opts = clean_opts(body.get("opts"))
            # Язык дорожки запоминаем как пожелание: «ru», а не код дорожки конкретного видео.
            last = dict(opts, audio_orig="", audio_label="")
            if "pref_lang" in body:
                pref = str(body.get("pref_lang") or "").strip()
                last["audio_lang"] = pref if LANG_RE.fullmatch(pref or "-") else ""
            ctx.settings.update({"last": last})
            group = str(body.get("group") or "").strip() or None
            return {"ids": m.add(items[:2000], group, opts)}
        if path == "/api/settings":
            ctx.settings.update(body)
            m.wake.set()
            return self.settings_payload()
        if path == "/api/pick-folder":
            current = ctx.settings.data["folder"]
            picker = ctx.pick_folder or system.pick_folder_fallback
            folder = picker(current)
            if folder:
                ctx.settings.update({"folder": folder})
            return self.settings_payload()
        if path == "/api/open-folder":
            folder = Path(ctx.settings.data["folder"])
            folder.mkdir(parents=True, exist_ok=True)
            system.open_path(str(folder))
            return {"ok": True}
        if path == "/api/open-url":
            url = str(body.get("url") or "")
            # Наружу открываем только страницы проекта, а не что угодно из запроса.
            if not (url == REPO_URL or url.startswith(REPO_URL + "/")):
                raise ApiError("Эту ссылку открыть нельзя.", status=403)
            webbrowser.open(url)
            return {"ok": True}
        if path == "/api/update":
            threading.Thread(target=ctx.tools.update_ytdlp, name="update", daemon=True).start()
            time.sleep(0.05)
            return {"tools": ctx.tools.snapshot()}
        if path == "/api/tools/install":
            ctx.tools.refresh()
            ctx.tools.ensure_async()
            return {"tools": ctx.tools.snapshot()}
        if path == "/api/show":
            if ctx.show_window:
                ctx.show_window()
            return {"ok": True}
        if path == "/api/jobs/clear":
            m.clear()
            return {"ok": True}
        hit = re.fullmatch(r"/api/jobs/([0-9a-f]{12})/(cancel|retry|remove|reveal|open)", path)
        if hit:
            return self.job_action(*hit.groups(), body)
        raise ApiError("Нет такого адреса.", status=404)

    def job_action(self, jid: str, action: str, body: dict):
        m = self.ctx.manager
        if action == "cancel":
            m.cancel(jid)
        elif action == "retry":
            m.retry(jid, force=bool(body.get("force")))
        elif action == "remove":
            m.remove(jid)
        else:
            job = m.get(jid)
            if job.file and Path(job.file).exists():
                (system.reveal if action == "reveal" else system.open_path)(job.file)
            elif Path(job.folder).is_dir():
                system.open_path(job.folder)
            else:
                raise ApiError("Файл не найден: его переместили или удалили.")
        return {"ok": True}


def make_server(ctx: Context, port: int) -> ThreadingHTTPServer | None:
    """Сервер на 127.0.0.1. None, если порт уже занят: решать, что делать, будет вызывающий."""
    handler = type("BoundHandler", (Handler,), {"ctx": ctx})
    try:
        server = ThreadingHTTPServer((HOST, port), handler)
    except OSError:
        return None
    server.daemon_threads = True
    ctx.port = server.server_address[1]
    return server
