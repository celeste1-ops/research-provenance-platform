"""One running copy per data folder (DECISIONS D-044).

Both ways of starting the app take the same lock: the double-click app (app.desktop) and
``make run`` / ``python -m app``. Otherwise two servers could read and write the same
database and backups at once, e.g. ``make run`` still open when the installed app starts.
The operating system releases the lock when the process ends, even after a crash.

A second start of the desktop app asks the running copy to show its window (D-058) by leaving
a file in the data folder, which the running copy looks for and removes. A file, not a socket:
no network code outside the providers, and nothing another program could connect to.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger("rprov.desktop")


class InstanceLock:
    """Exclusive, non-blocking lock on ``<data>/app.lock``; held for the life of the process."""

    def __init__(self, data_dir: Path):
        self.path = data_dir / "app.lock"
        self.port_file = data_dir / "app.port"
        self.show_file = data_dir / "app.show"
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

    def ask_to_show(self, wait: float = 3.0) -> bool:
        """Ask the running copy to show its window. True when it took the request; False when it
        does not answer (``make run``, or a version without a window): open the browser then."""
        try:
            self.show_file.write_text(str(os.getpid()), encoding="utf-8")
        except OSError:
            return False
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            if not self.show_file.exists():
                return True
            time.sleep(0.05)
        try:
            self.show_file.unlink()
        except FileNotFoundError:
            return True  # taken just now
        except OSError:
            pass
        return False

    def watch_show_requests(self, on_request: Callable[[], None], stop: threading.Event,
                            interval: float = 0.25) -> None:
        """Run by the copy that holds the lock, in a thread of its own, until ``stop`` is set."""
        try:
            self.show_file.unlink()  # left over from a start that gave up
        except OSError:
            pass
        while not stop.wait(interval):
            if not self.show_file.exists():
                continue
            try:
                self.show_file.unlink()
            except OSError:
                continue
            try:
                on_request()
            except Exception:  # noqa: BLE001 - keep answering later requests
                log.exception("could not show the window")

    def release(self) -> None:
        if self._fh is not None:
            try:
                self.port_file.unlink()
            except OSError:
                pass
            self._fh.close()
            self._fh = None
