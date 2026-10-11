"""Double-click entry point of the packaged app (macOS .app, Windows setup) — DECISIONS D-044.

Starts the same local server as ``make run`` (127.0.0.1 only), opens the browser, and puts
an icon in the macOS menu bar / Windows notification area with "Open Research History"
and "Quit". There is no console window, so everything is logged to ``<data>/logs/app.log``.

Only one copy runs per data folder: a lock file in the data folder (released by the
operating system when the process ends, even after a crash) tells a second start that
the app is already running; it then just opens the browser at the running app's address.
No network code here: readiness is read from the server object itself.
"""

from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

from app.config import Settings

APP_NAME = "Research History"
log = logging.getLogger("rprov.desktop")
PORT_TRIES = 10


# ---------------------------------------------------------------- one copy per data folder


class InstanceLock:
    """Exclusive, non-blocking lock on ``<data>/app.lock``; held for the life of the process."""

    def __init__(self, data_dir: Path):
        self.path = data_dir / "app.lock"
        self.port_file = data_dir / "app.port"
        self._fh = None

    def acquire(self) -> bool:
        fh = open(self.path, "a+b")  # noqa: SIM115 - kept open while the app runs
        try:
            if sys.platform == "win32":
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        self._fh = fh
        return True

    def publish(self, port: int) -> None:
        tmp = self.port_file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"port": port, "pid": os.getpid()}), encoding="utf-8")
        os.replace(tmp, self.port_file)

    def running_port(self, wait: float = 10.0) -> int | None:
        """The port of the copy that holds the lock (it may still be starting)."""
        deadline = time.monotonic() + wait
        while True:
            try:
                return int(json.loads(self.port_file.read_text(encoding="utf-8"))["port"])
            except (OSError, ValueError, KeyError):
                if time.monotonic() > deadline:
                    return None
                time.sleep(0.2)

    def release(self) -> None:
        if self._fh is not None:
            try:
                self.port_file.unlink()
            except OSError:
                pass
            self._fh.close()
            self._fh = None


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


def run_tray(url: str, on_quit) -> bool:
    """Show the icon and block until Quit. Returns False if no tray is available here."""
    try:
        import pystray
    except Exception:  # noqa: BLE001 - e.g. no display: run without an icon
        log.warning("no menu bar / tray icon available; quit with Ctrl+C or by ending the process")
        return False

    def quit_app(icon, _item):
        on_quit()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem(f"Open {APP_NAME}", lambda _icon, _item: open_browser(url), default=True),
        pystray.MenuItem("Quit", quit_app),
    )
    icon = pystray.Icon("research-history", tray_image(), f"{APP_NAME} — {url}", menu)
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
        if args.no_tray or not run_tray(url, quit_app):
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
