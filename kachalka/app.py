"""Запуск Качалки: сервер плюс окно приложения, вкладка браузера или ничего (--headless)."""
from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
import time
import urllib.request
import webbrowser
from logging.handlers import RotatingFileHandler

from . import APP_NAME, __version__, system
from .jobs import Manager
from .server import Context, make_server
from .settings import Settings
from .tools import Tools

log = logging.getLogger("kachalka")

DEFAULT_PORT = 8790
IDLE_EXIT = 15 * 60  # в режиме браузера сервер выключается, если вкладку закрыли и ничего не качается
CLOSE_QUESTION = "Идут загрузки. Закрыть Качалку? Незаконченные загрузки можно будет продолжить потом."

# Запросы к себе же на 127.0.0.1 не должны уходить в системный прокси.
_local = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def setup_logging(paths: system.Paths, verbose: bool):
    handlers: list[logging.Handler] = [RotatingFileHandler(paths.log, maxBytes=1_000_000, backupCount=1,
                                                           encoding="utf-8")]
    if verbose and sys.stderr:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=handlers, force=True)
    sys.excepthook = lambda *exc: log.critical("uncaught", exc_info=exc)


def running_instance(port: int) -> bool:
    try:
        with _local.open(f"http://127.0.0.1:{port}/api/ping", timeout=1.5) as r:
            return json.load(r).get("app") == "kachalka"
    except (OSError, ValueError):
        return False


def poke(port: int, path: str):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=b"{}", method="POST",
                                 headers={"X-Kachalka": "1", "Content-Type": "application/json"})
    try:
        _local.open(req, timeout=3).close()
    except OSError:
        pass


def wait_for_signal():
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    while not stop.wait(1):
        pass


def wait_until_idle(ctx: Context):
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    while not stop.wait(10):
        if time.time() - ctx.last_seen > IDLE_EXIT and not ctx.manager.busy():
            log.info("no open tabs for %s s, exiting", IDLE_EXIT)
            return


def run_window(ctx: Context, url: str) -> bool:
    """Отдельное окно через pywebview. False, если окно поднять не получилось."""
    try:
        import webview
    except ImportError:
        log.info("pywebview is not installed, using the browser")
        return False

    window = webview.create_window(
        APP_NAME, url, width=1120, height=860, min_size=(440, 560), text_select=True,
        background_color="#131519" if system.is_dark() else "#EDEFF2",
    )

    def on_closing():
        # Спрашиваем «Закрыть?» только когда что-то качается.
        window.confirm_close = ctx.manager.busy()

    def pick_folder(current: str):
        chosen = window.create_file_dialog(webview.FileDialog.FOLDER, directory=current)
        return chosen[0] if chosen else None

    def show():
        window.restore()
        window.show()

    window.events.closing += on_closing
    ctx.pick_folder = pick_folder
    ctx.show_window = show
    localization = {"global.quitConfirmation": CLOSE_QUESTION, "global.quit": "Закрыть", "global.cancel": "Отмена"}
    try:
        # В Windows нужен WebView2 (есть в Windows 10 и 11). Без него откроемся в браузере.
        webview.start(gui="edgechromium" if system.IS_WIN else None, localization=localization)
    except Exception:  # noqa: BLE001
        log.exception("window failed, falling back to the browser")
        ctx.pick_folder = ctx.show_window = None
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kachalka", description=f"{APP_NAME}: скачивание видео через yt-dlp")
    parser.add_argument("--browser", action="store_true", help="открыть интерфейс в браузере, а не в своём окне")
    parser.add_argument("--headless", action="store_true", help="только сервер, без окна: для тестов")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"порт сервера (по умолчанию {DEFAULT_PORT})")
    parser.add_argument("--data-dir", help="папка для настроек, истории и скачанных компонентов")
    parser.add_argument("--own-tools", action="store_true",
                        help="не брать yt-dlp и ffmpeg из системы, а скачать свои копии")
    parser.add_argument("--verbose", action="store_true", help="писать лог ещё и в консоль")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    paths = system.Paths(args.data_dir)
    paths.ensure()
    setup_logging(paths, args.verbose or args.headless)

    # Порт занимаем первым делом: так второй запуск сразу видит, что Качалка уже открыта.
    ctx = Context(paths)
    server = make_server(ctx, args.port)
    if server is None:
        # Порт занят. Если это мы же (возможно, ещё стартуем), просто показываем окно.
        for _ in range(20):
            if running_instance(args.port):
                log.info("already running on port %s", args.port)
                if args.browser:
                    webbrowser.open(f"http://127.0.0.1:{args.port}/")
                elif not args.headless:
                    poke(args.port, "/api/show")
                return 0
            time.sleep(0.5)
        server = make_server(ctx, 0)  # порт держит чужая программа
    threading.Thread(target=server.serve_forever, name="http", daemon=True).start()

    settings = Settings(paths)
    tools = Tools(paths, use_system=not args.own_tools)
    manager = Manager(paths, settings, tools)
    ctx.settings, ctx.tools, ctx.manager = settings, tools, manager
    tools.ensure_async()
    url = f"http://127.0.0.1:{ctx.port}/"
    log.info("%s %s started at %s, data in %s", APP_NAME, __version__, url, paths.root)

    try:
        if args.headless:
            print(url, flush=True)
            wait_for_signal()
        elif args.browser or not run_window(ctx, url):
            webbrowser.open(url)
            wait_until_idle(ctx)
    except KeyboardInterrupt:
        pass
    finally:
        manager.stop_all()
        server.shutdown()
        server.server_close()
        log.info("stopped")
    return 0
