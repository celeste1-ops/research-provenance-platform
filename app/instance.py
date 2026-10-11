"""One running copy per data folder (DECISIONS D-044).

Both ways of starting the app take the same lock: the double-click app (app.desktop) and
``make run`` / ``python -m app``. Otherwise two servers could read and write the same
database and backups at once, e.g. ``make run`` still open when the installed app starts.
The operating system releases the lock when the process ends, even after a crash.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


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
