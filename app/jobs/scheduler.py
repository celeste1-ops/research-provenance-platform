"""In-process background jobs (PRD §13 后台任务 — no Celery or Redis): check time proofs once
at start-up, then hourly; record new commits of watched git repositories every minute (D-047)."""

from __future__ import annotations

import logging
import threading

log = logging.getLogger("rprov.jobs")

INTERVAL_SECONDS = 3600


class AnchorScheduler:
    def __init__(self, anchors, interval: float = INTERVAL_SECONDS, after=None):
        self.anchors = anchors
        self.after = after  # e.g. automatic backup once proofs have been refreshed
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
        if self.after is not None:
            self.after()
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


GIT_INTERVAL_SECONDS = 60


class GitScheduler:
    """Looks for new commits every minute. Reading a local repository is cheap; a step is only
    saved (and stamped) when a commit is new."""

    def __init__(self, spaces, interval: float = GIT_INTERVAL_SECONDS):
        self.spaces = spaces
        self.interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="rprov-git", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                recorded = self.spaces.record_git()
                if recorded:
                    log.info("recorded %d new commit step(s)", recorded)
            except Exception:  # noqa: BLE001 - keep the job alive
                log.exception("git recording failed")
