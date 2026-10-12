"""Double-click entry point of the packaged app (macOS .app, Windows setup) — DECISIONS D-044, D-058.

Starts the same local server as ``make run`` (127.0.0.1 only) and shows it in the app's own
window (app.window: the system's web engine, through pywebview), or in the browser where there
is no such engine. An icon in the macOS menu bar / Windows notification area has "Open
Research History", "Quick note…", "Open in browser" and "Quit" (in Chinese when that is the
language chosen in the app, or else the system's — D-046). There is no console window, so
everything is logged to ``<data>/logs/app.log``.

Only one copy runs per data folder (app.instance; ``make run`` takes the same lock): a second
start asks the running copy to show its window, or opens the browser at its address.
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
    "en": {"open": f"Open {APP_NAME}", "note": "Quick note…", "browser": "Open in browser", "quit": "Quit"},
    "zh": {"open": f"打开 {APP_NAME}", "note": "快速记一笔…", "browser": "在浏览器中打开", "quit": "退出"},
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


class BrowserShell:
    """No window: the page opens in the default browser (as before 0.4.0, and wherever the
    system has no web engine for a window). The icon's menu works the same."""

    has_window = False

    def __init__(self, url: str, on_quit):
        self.url = url
        self._on_quit = on_quit
        self.notify = None

    def show(self, hash: str = "") -> None:
        open_browser(self.url + hash)

    def open_in_browser(self) -> None:
        open_browser(self.url)

    def quit(self) -> None:
        self._on_quit()


def reopened(url: str) -> None:
    """The app was opened again while it runs: show its page, as the first start did."""
    log.info("opened again while running: opening the browser")
    open_browser(url)


_reopen_delegate = []  # keeps the delegate alive for as long as the app runs


def watch_reopen(url: str) -> None:
    """macOS without a window: opening the app again while it runs (double-click in Finder or
    Launchpad) only re-activates the running copy, so nothing seemed to happen. Answer that by
    opening the page. (With a window, app.window answers it by showing the window.)"""
    if sys.platform != "darwin" or _reopen_delegate:
        return
    try:
        import AppKit
        import Foundation
    except Exception:  # noqa: BLE001 - no Cocoa here
        return

    class ReopenDelegate(Foundation.NSObject):
        def applicationShouldHandleReopen_hasVisibleWindows_(self, _app, _has_windows):
            reopened(url)
            return False

    delegate = ReopenDelegate.alloc().init()
    AppKit.NSApplication.sharedApplication().setDelegate_(delegate)
    _reopen_delegate.append(delegate)


def make_tray(shell, data_dir: Path):
    """The menu bar / tray icon for ``shell`` (an AppWindow or a BrowserShell), or None where
    there is no tray (e.g. no display during development)."""
    try:
        import pystray
    except Exception:  # noqa: BLE001
        log.warning("no menu bar / tray icon available; quit with Ctrl+C or by ending the process")
        return None
    from app import preferences

    lang = [menu_language(data_dir)]

    def label(key):
        return lambda _item: MENU[lang[0]][key]

    def quit_app(icon, _item):
        shell.quit()
        if not shell.has_window:
            icon.stop()  # with a window, the window's event loop ends the app

    items = [
        pystray.MenuItem(label("open"), lambda _icon, _item: shell.show(), default=True),
        pystray.MenuItem(label("note"), lambda _icon, _item: shell.show(QUICK_NOTE)),
    ]
    if shell.has_window:
        items.append(pystray.MenuItem(label("browser"), lambda _icon, _item: shell.open_in_browser()))
    items += [pystray.Menu.SEPARATOR, pystray.MenuItem(label("quit"), quit_app)]
    icon = pystray.Icon("research-history", tray_image(), f"{APP_NAME} — {shell.url}", pystray.Menu(*items))

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
    shell.notify = lambda text: icon.notify(text, APP_NAME)
    return icon


def run_tray(shell, data_dir: Path) -> bool:
    """Without a window: show the icon and block until Quit. False if there is no tray here."""
    icon = make_tray(shell, data_dir)
    if icon is None:
        return False
    watch_reopen(shell.url)
    try:
        icon.run()
    except Exception:  # noqa: BLE001
        log.exception("tray icon failed")
        return False
    return True


def run_window(shell, data_dir: Path, no_tray: bool, after_start=None) -> bool:
    """With a window: the window's event loop runs on the main thread (as macOS and pywebview
    require); the icon joins it on macOS and has a thread of its own on Windows. False when the
    window could not be shown at all, so that the caller uses the browser instead."""
    icon = None if no_tray else make_tray(shell, data_dir)
    if icon is not None:
        if sys.platform == "darwin":
            from PyObjCTools import AppHelper

            icon.run_detached(setup=lambda i: AppHelper.callAfter(setattr, i, "visible", True))
        else:
            threading.Thread(target=icon.run, name="rprov-tray", daemon=True).start()
    try:
        shell.run(after_start)
        return True
    except Exception:
        if shell.loaded.is_set() or shell.quitting or after_start is not None:
            raise
        log.exception("the app window could not be shown: using the browser")
        return False
    finally:
        if icon is not None:
            if sys.platform == "darwin":
                icon.visible = False  # on the main thread here; a browser icon may follow
            else:
                icon.stop()


def run_browser(shell, data_dir: Path, args, server_thread: threading.Thread) -> None:
    """Without a window: open the page in the browser, and wait for Quit in the icon's menu."""
    if not args.no_browser:
        open_browser(shell.url)
    if args.no_tray or not run_tray(shell, data_dir):
        while server_thread.is_alive():
            server_thread.join(0.5)


def check_window(shell, lock: InstanceLock, server_thread: threading.Thread) -> None:
    """``--check-window``, for the packaging smoke test on macOS and Windows: the page is drawn
    in the real window, closing the window hides it while the app keeps running, a second start
    shows it again, and Quit ends the app. Each step is logged; a failure exits with 1."""
    from app import window as app_window

    def fail(why: str) -> None:
        log.error("window check failed: %s", why)
        shell.quitting = True
        shell._on_quit()
        os._exit(1)

    def wait_for(cond, seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if cond():
                return True
            time.sleep(0.2)
        return False

    if not shell.loaded.wait(90):
        fail("the page did not load")
    seen = {}

    def drawn() -> bool:
        # run_js: the page's Content-Security-Policy forbids the eval() that evaluate_js uses.
        try:
            seen["answer"] = shell.window.run_js(
                "!document.querySelector('#root .boot') && !!document.querySelector('#root [data-testid]')"
                " ? 'drawn' : 'not yet'")
        except Exception as exc:  # noqa: BLE001 - not yet
            seen["answer"] = exc
        return seen["answer"] == "drawn"

    if not wait_for(drawn, 30):
        try:
            page = shell.window.run_js("document.getElementById('root').innerHTML.slice(0, 300)")
        except Exception as exc:  # noqa: BLE001
            page = exc
        fail(f"the page was not drawn (only the start-up note, or nothing): the window answered "
             f"{seen.get('answer')!r}; the page holds {page!r}")
    log.info("window check: the page is drawn")

    if sys.platform == "darwin":
        app_window.mac_simulate_close(shell.window)
    else:
        shell.window.destroy()  # a close by the user, as far as the window can tell
    if not wait_for(lambda: shell.hidden, 15):
        fail("closing the window did not hide it")
    time.sleep(1)
    if not server_thread.is_alive() or shell.quitting:
        fail("closing the window stopped the app")
    log.info("window check: closing the window hid it; the app keeps running")

    if not InstanceLock(lock.path.parent).ask_to_show(wait=10):
        fail("a second start was not answered")
    if not wait_for(lambda: not shell.hidden, 10):
        fail("a second start did not show the window")
    log.info("window check: a second start showed the window again")
    log.info("window check passed")
    shell.quit()


# ---------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"{APP_NAME}: local research history app")
    parser.add_argument("--browser", action="store_true", help="show the app in the browser instead of its own window")
    parser.add_argument("--no-browser", action="store_true", help="show nothing: no window, no browser")
    parser.add_argument("--no-tray", action="store_true", help="no menu bar / tray icon (stop with Ctrl+C)")
    parser.add_argument("--port", type=int, default=None, help="first port to try (default 8765)")
    parser.add_argument("--check-window", action="store_true", help=argparse.SUPPRESS)  # packaging smoke test
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
        if args.no_browser:
            log.info("already running on port %d", port)
        elif not args.browser and lock.ask_to_show():
            log.info("already running on port %d: asked it to show its window", port)
        else:
            log.info("already running on port %d: opening the browser", port)
            open_browser(f"http://127.0.0.1:{port}/")
        return 0

    problem = None
    if not (args.browser or args.no_browser):
        from app.window import engine_problem

        problem = engine_problem()
        if problem:
            log.warning("no app window here (%s): using the browser", problem)
    if args.check_window and (problem or args.browser or args.no_browser):
        log.error("window check failed: %s", problem or "no window was asked for")
        lock.release()
        return 1

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

    stopped = threading.Event()

    def quit_app() -> None:
        if not stopped.is_set():
            stopped.set()
            log.info("quitting")
            stop_server(server, thread, ctx)
            lock.release()

    with_window = not (args.browser or args.no_browser or problem)
    if with_window:
        from app.window import AppWindow

        shell = AppWindow(url, settings.data_dir, quit_app, language=lambda: menu_language(settings.data_dir))
    else:
        shell = BrowserShell(url, quit_app)
    current = [shell]  # what a second start shows: the window, or the browser if it had to take over
    watching = threading.Event()
    threading.Thread(target=lock.watch_show_requests, args=(lambda: current[0].show(), watching),
                     name="rprov-show", daemon=True).start()

    try:
        shown = False
        if with_window:
            after = (lambda: check_window(shell, lock, thread)) if args.check_window else None
            try:
                shell.create()
            except Exception:
                if after:
                    raise
                log.exception("the app window could not be made: using the browser")
            else:
                shown = run_window(shell, settings.data_dir, args.no_tray, after)
            if not shown:
                current[0] = BrowserShell(url, quit_app)
        if not shown and not stopped.is_set():
            run_browser(current[0], settings.data_dir, args, thread)
    except KeyboardInterrupt:
        pass
    finally:
        watching.set()
        quit_app()
        lock.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
