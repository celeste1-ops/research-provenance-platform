"""In-process background job: check time proofs once at start-up, then hourly
(PRD §13 后台任务 — no Celery or Redis)."""

from __future__ import annotations

import logging
import threading

log = logging.getLogger("rprov.jobs")

INTERVAL_SECONDS = 3600


class AnchorScheduler:
    def __init__(self, anchors, interval: float = INTERVAL_SECONDS):
        self.anchors = anchors
        self.interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="rprov-anchor-refresh", daemon=True)
        self.runs = 0

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def run_once(self) -> dict:
        stats = self.anchors.refresh(force=False)
        self.runs += 1
        log.info("time-proof check: %s", stats)
        return stats

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:  # noqa: BLE001 - keep the scheduler alive
                log.exception("time-proof check failed")
            self._stop.wait(self.interval)
