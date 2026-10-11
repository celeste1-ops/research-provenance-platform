"""Double-click entry point of the packaged app (macOS .app, Windows setup) — DECISIONS D-044.

Starts the same local server as ``make run`` (127.0.0.1 only), opens the browser, and puts
an icon in the macOS menu bar / Windows notification area with "Open Research History",
"Quick note…" and "Quit" (in Chinese when that is the language chosen in the app, or else the system's —
D-046). There is no console window, so everything is logged to ``<data>/logs/app.log``.

Only one copy runs per data folder (app.instance; ``make run`` takes the same lock): a
second start just opens the browser at the running copy's address.
No network code here: readiness is read from the server object itself.
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

from app.config import Settings
from app.instance import InstanceLock

APP_NAME = "Research History"
log = logging.getLogger("rprov.desktop")
PORT_TRIES = 10


# ---------------------------------------------------------------- server


def setup_logging(data_dir: Path) -> Path:
    logs = data_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    path = logs / "app.log"
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    return path


def start_server(ctx, first_port: int, tries: int = PORT_TRIES):
    """Serve on the first free port from ``first_port``; returns (uvicorn server, thread, port)."""
    import uvicorn

    from app.main import create_app

    for port in range(first_port, first_port + tries):
        ctx.settings.port = port  # the Host/Origin checks follow the port actually used
        app = create_app(ctx, start_jobs=True)
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None, lifespan="on"))
        thread = threading.Thread(target=server.run, name="rprov-server", daemon=True)
        thread.start()
        deadline = time.monotonic() + 20
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.05)
        if server.started:
            return server, thread, port
        log.warning("port %d is not available, trying the next one", port)
        server.should_exit = True
        thread.join(5)
    raise RuntimeError(f"no free port between {first_port} and {first_port + tries - 1}")


def stop_server(server, thread, ctx) -> None:
    server.should_exit = True
    thread.join(15)
    ctx.close()


def open_browser(url: str) -> None:
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001 - no browser is not fatal; the address is in the log
        log.exception("could not open a browser for %s", url)


# ---------------------------------------------------------------- menu bar / tray


def tray_image(size: int = 64):
    """A small round stamp: drawn here, so no image file is needed."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = size // 16
    d.ellipse((m, m, size - m, size - m), fill=(47, 91, 211, 255))
    d.ellipse((size * 5 // 16, size * 5 // 16, size * 11 // 16, size * 11 // 16), outline=(255, 255, 255, 255),
              width=max(2, size // 12))
    return img


MENU = {
    "en": {"open": f"Open {APP_NAME}", "note": "Quick note…", "quit": "Quit"},
    "zh": {"open": f"打开 {APP_NAME}", "note": "快速记一笔…", "quit": "退出"},
}
QUICK_NOTE = "#quick-note"  # the page opens its quick note box (D-047)


def system_language() -> str:
    """'zh' when the system's first language is Chinese (used until one is chosen in the app)."""
    names = [os.environ.get(k, "") for k in ("LC_ALL", "LC_MESSAGES", "LANG")]
    try:
        if sys.platform == "darwin":
            from Foundation import NSLocale  # pyobjc, which the menu bar icon needs anyway

            names += [str(x) for x in NSLocale.preferredLanguages()[:1]]
        elif sys.platform == "win32":
            import ctypes

            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            names.append("zh" if lang_id & 0x3FF == 0x04 else "en")  # LANG_CHINESE
    except Exception:  # noqa: BLE001
        pass
    first = next((n for n in names if n and n not in ("C", "POSIX") and not n.startswith("C.")), "")
    return "zh" if first.lower().startswith("zh") else "en"


def menu_language(data_dir: Path) -> str:
    from app import preferences

    return preferences.language(data_dir) or system_language()


def run_tray(url: str, on_quit, data_dir: Path) -> bool:
    """Show the icon and block until Quit. Returns False if no tray is available here."""
    try:
        import pystray
    except Exception:  # noqa: BLE001 - e.g. no display: run without an icon
        log.warning("no menu bar / tray icon available; quit with Ctrl+C or by ending the process")
        return False
    from app import preferences

    lang = [menu_language(data_dir)]

    def quit_app(icon, _item):
        on_quit()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem(lambda _item: MENU[lang[0]]["open"], lambda _icon, _item: open_browser(url), default=True),
        pystray.MenuItem(lambda _item: MENU[lang[0]]["note"], lambda _icon, _item: open_browser(url + QUICK_NOTE)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(lambda _item: MENU[lang[0]]["quit"], quit_app),
    )
    icon = pystray.Icon("research-history", tray_image(), f"{APP_NAME} — {url}", menu)

    def relabel(prefs: dict) -> None:  # the language was switched in the app
        new = prefs.get("language") if prefs.get("language") in MENU else lang[0]
        if new == lang[0]:
            return
        lang[0] = new
        if sys.platform == "darwin":
            from PyObjCTools import AppHelper  # menus may only change on the main thread

            AppHelper.callAfter(icon.update_menu)
        elif sys.platform == "win32":
            icon.update_menu()
        # elsewhere (development only) the new labels show after the next restart

    preferences.on_change(relabel)
    try:
        icon.run()
    except Exception:  # noqa: BLE001
        log.exception("tray icon failed")
        return False
    return True


# ---------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"{APP_NAME}: local research history app")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    parser.add_argument("--no-tray", action="store_true", help="no menu bar / tray icon (stop with Ctrl+C)")
    parser.add_argument("--port", type=int, default=None, help="first port to try (default 8765)")
    args = parser.parse_args(argv)

    settings = Settings()
    settings.ensure_data_dir()
    log_path = setup_logging(settings.data_dir)
    lock = InstanceLock(settings.data_dir)
    if not lock.acquire():
        port = lock.running_port()
        if port is None:
            log.error("another copy holds %s but did not say its port", lock.path)
            return 1
        log.info("already running on port %d: opening the browser", port)
        if not args.no_browser:
            open_browser(f"http://127.0.0.1:{port}/")
        return 0

    from app.services.context import AppContext

    ctx = AppContext.create(settings)
    try:
        server, thread, port = start_server(ctx, args.port or settings.port)
    except Exception:
        log.exception("could not start the server")
        lock.release()
        ctx.close()
        return 1
    lock.publish(port)
    url = f"http://127.0.0.1:{port}/"
    log.info("%s is running at %s (data: %s, log: %s)", APP_NAME, url, settings.data_dir, log_path)
    if not args.no_browser:
        open_browser(url)

    stopped = threading.Event()

    def quit_app() -> None:
        if not stopped.is_set():
            stopped.set()
            log.info("quitting")
            stop_server(server, thread, ctx)

    try:
        if args.no_tray or not run_tray(url, quit_app, settings.data_dir):
            while thread.is_alive():
                thread.join(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        quit_app()
        lock.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
