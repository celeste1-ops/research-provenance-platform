"""Two separate spaces: the real record and a practice space (DECISIONS D-038).

Records can never be removed, so trying the app out inside the real record would
leave test steps there forever. The practice space is a complete, separate
installation in ``<data dir>/practice``: its own database, files and signing key
(a different installation ID, so a different keychain item). Nothing is shared with
the real record except the time-proof providers, so practice steps get the same kind
of stamps and look exactly like the real thing.

Practice is never backed up and can be started over (the whole practice folder and its
key are deleted). The real record has no such operation.

Every API request names its space in the ``X-RPROV-Space`` header (or ``?space=`` for
plain links); without one it goes to the real record. Each browser tab therefore saves
where it says it saves, even if another tab switched.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import shutil
import threading
import time

from app.db.models import WRITE_LOCK
from app.services.context import AppContext
from app.services.keystore import DevInsecureFileKeyStore

log = logging.getLogger("rprov.spaces")

REAL = "real"
PRACTICE = "practice"
SPACE_HEADER = "x-rprov-space"
PRACTICE_DIR_NAME = "practice"
PRACTICE_PROJECT = "Practice project"
SAMPLE_FILE = "sample.json"  # in the practice folder when it holds the FSF sample (D-059)


class PracticeResetError(RuntimeError):
    pass


def _remove_tree(path) -> None:
    """Delete the practice folder for real. On Windows a file another program still has open
    (an indexer, an antivirus scan) cannot be deleted for a moment: retry, then say so instead
    of silently reopening the old practice data."""
    for attempt in range(5):
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return
        time.sleep(0.2 * (attempt + 1))
    raise PracticeResetError(
        f"could not delete {path}: some file in it is still in use. Close other programs that may be "
        "using it and try again."
    )


class Spaces:
    def __init__(self, real: AppContext):
        self.real = real
        self._practice: AppContext | None = None
        self._lock = threading.RLock()

    @property
    def practice_dir(self):
        return self.real.settings.data_dir / PRACTICE_DIR_NAME

    def get(self, name: str | None) -> AppContext:
        if name in (None, "", REAL):
            return self.real
        if name == PRACTICE:
            return self.practice()
        raise ValueError(f"unknown space {name!r}")

    def _open_practice(self) -> AppContext:
        settings = dataclasses.replace(self.real.settings, data_dir=self.practice_dir)
        keystore = self.real.keystore
        if isinstance(keystore, DevInsecureFileKeyStore):
            # That store holds a single key file; practice gets its own inside its folder.
            settings.ensure_data_dir()
            keystore = DevInsecureFileKeyStore(self.practice_dir)
        return AppContext.create(settings, keystore=keystore, providers=self.real.anchors.providers, backups=False)

    def practice(self, *, auto_init: bool = True) -> AppContext:
        """The practice installation, created (with its own key) on first use."""
        with self._lock:
            if self._practice is None:
                self._practice = self._open_practice()
            ctx = self._practice
            if auto_init and not ctx.ledger.initialized():
                ctx.ledger.init_identity(self._practice_label())
                ctx.ledger.create_project(PRACTICE_PROJECT)
            return ctx

    def _practice_label(self) -> str:
        label = None
        if self.real.ledger.initialized():
            rows = self.real.ledger.records()
            if rows:
                label = json.loads(rows[0].payload_bytes).get("author_label")
        return f"{label} (practice)" if label else "Practice"

    def sample_info(self) -> dict | None:
        """What the practice space remembers about the FSF sample in it (D-059), or None."""
        try:
            data = json.loads((self.practice_dir / SAMPLE_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def reset_practice(self, *, with_sample: bool = False, lang: str = "en") -> AppContext:
        """Throw the practice space away and start a fresh one (optionally with the sample, in
        the interface's language)."""
        with self._lock:
            with WRITE_LOCK:  # no write is half-way through while the folder goes
                old = self._practice
                if old is None and self.practice_dir.exists():
                    old = self._open_practice()
                if old is not None:
                    installation = old.ledger.installation
                    old.close()
                    if installation:
                        old.keystore.delete(installation)
                self._practice = None
                _remove_tree(self.practice_dir)
            log.info("practice space started over")
            if not with_sample:
                return self.practice()
            from app.demo import load_sample

            ctx = self.practice(auto_init=False)
            info = load_sample(ctx, lang)
            (self.practice_dir / SAMPLE_FILE).write_text(json.dumps(info, indent=1), encoding="utf-8")
            return ctx

    def anchor_services(self) -> list:
        with self._lock:
            out = [self.real.anchors]
            if self._practice is None and self.practice_dir.exists():
                self._practice = self._open_practice()
            if self._practice is not None:
                out.append(self._practice.anchors)
            return out

    def record_sources(self) -> int:
        """Every minute, in each existing space: new commits of the repositories it records
        (D-047) and new versions in the folders it watches (D-049)."""
        with self._lock:
            contexts = [self.real]
            if self._practice is None and self.practice_dir.exists():
                self._practice = self._open_practice()
            if self._practice is not None:
                contexts.append(self._practice)
        found = 0
        for c in contexts:
            if c.git.has_sources():
                found += c.git.check()["recorded"]
            if c.inbox.has_folders() or c.inbox.count():
                found += c.inbox.scan()
        return found

    def refresh(self, force: bool = False) -> dict[str, int]:
        """Hourly job: check stamps in both spaces."""
        total: dict[str, int] = {}
        for anchors in self.anchor_services():
            for key, value in anchors.refresh(force=force).items():
                total[key] = total.get(key, 0) + value
        return total

    def close(self) -> None:
        with self._lock:
            if self._practice is not None:
                self._practice.close()
                self._practice = None
