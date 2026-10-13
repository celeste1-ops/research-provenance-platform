"""Three separate spaces: the real record, a practice space (DECISIONS D-038) and the example
(D-064).

Records can never be removed, so trying the app out inside the real record would
leave test steps there forever. The practice space is a complete, separate
installation in ``<data dir>/practice``: its own database, files and signing key
(a different installation ID, so a different keychain item). Nothing is shared with
the real record except the time-proof providers, so practice steps get the same kind
of stamps and look exactly like the real thing.

Practice is never backed up and can be started over (the whole practice folder and its
key are deleted). The real record has no such operation.

The example is a third installation of the same kind, in ``<data dir>/example``: the fictional
FSF sample research (D-059), loaded the first time it is opened. It is kept apart from practice,
so practice only ever holds what the author tried there. It can be reloaded the same way.

Every API request names its space in the ``X-RPROV-Space`` header (or ``?space=`` for
plain links); without one it goes to the real record. Each browser tab therefore saves
where it says it saves, even if another tab switched.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import shutil
import threading
import time

from app.db.models import WRITE_LOCK
from app.services.context import AppContext
from app.services.keystore import DevInsecureFileKeyStore

log = logging.getLogger("rprov.spaces")

REAL = "real"
PRACTICE = "practice"
EXAMPLE = "example"
SANDBOXES = (PRACTICE, EXAMPLE)  # each in a folder of that name in the data folder
SPACE_HEADER = "x-rprov-space"
PRACTICE_PROJECT = "Practice project"
SAMPLE_FILE = "sample.json"  # in the example folder: what it remembers about the FSF sample (D-059)


class PracticeResetError(RuntimeError):
    pass


def _remove_tree(path) -> None:
    """Delete a practice or example folder for real. On Windows a file another program still has open
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
        self._open: dict[str, AppContext] = {}
        self._lock = threading.RLock()
        self._move_old_sample()

    def folder(self, name: str):
        return self.real.settings.data_dir / name

    @property
    def practice_dir(self):
        return self.folder(PRACTICE)

    @property
    def example_dir(self):
        return self.folder(EXAMPLE)

    def _move_old_sample(self) -> None:
        """Up to v0.6.1 the sample was loaded into practice (D-059, D-062). A practice space holding
        it becomes the example, and practice starts empty: practice only holds the author's own."""
        if (self.practice_dir / SAMPLE_FILE).is_file() and not self.example_dir.exists():
            try:
                os.replace(self.practice_dir, self.example_dir)
                log.info("the sample research moved from practice to the example space")
            except OSError as exc:
                log.warning("could not move the sample research out of practice: %s", exc)

    def get(self, name: str | None) -> AppContext:
        if name in (None, "", REAL):
            return self.real
        if name == PRACTICE:
            return self.practice()
        if name == EXAMPLE:
            return self.example()
        raise ValueError(f"unknown space {name!r}")

    def _open_space(self, name: str) -> AppContext:
        folder = self.folder(name)
        settings = dataclasses.replace(self.real.settings, data_dir=folder)
        keystore = self.real.keystore
        if isinstance(keystore, DevInsecureFileKeyStore):
            # That store holds a single key file; each space gets its own inside its folder.
            settings.ensure_data_dir()
            keystore = DevInsecureFileKeyStore(folder)
        return AppContext.create(settings, keystore=keystore, providers=self.real.anchors.providers, backups=False)

    def _context(self, name: str) -> AppContext:
        with self._lock:
            if name not in self._open:
                self._open[name] = self._open_space(name)
            return self._open[name]

    def practice(self, *, auto_init: bool = True) -> AppContext:
        """The practice installation, created (with its own key) on first use."""
        with self._lock:
            ctx = self._context(PRACTICE)
            if auto_init and not ctx.ledger.initialized():
                ctx.ledger.init_identity(self._practice_label())
                ctx.ledger.create_project(PRACTICE_PROJECT)
            return ctx

    def example(self, lang: str | None = None) -> AppContext:
        """The example installation (D-064): the FSF sample, loaded the first time it is opened, in
        ``lang`` or else the language the interface was last set to."""
        with self._lock:
            ctx = self._context(EXAMPLE)
            if not ctx.ledger.initialized():
                from app import preferences
                from app.demo import load_sample

                info = load_sample(ctx, lang or preferences.language(self.real.settings.data_dir) or "en")
                (self.example_dir / SAMPLE_FILE).write_text(json.dumps(info, indent=1), encoding="utf-8")
            return ctx

    def _practice_label(self) -> str:
        label = None
        if self.real.ledger.initialized():
            rows = self.real.ledger.records()
            if rows:
                label = json.loads(rows[0].payload_bytes).get("author_label")
        return f"{label} (practice)" if label else "Practice"

    def sample_info(self) -> dict | None:
        """What the example remembers about the FSF sample in it (D-059), or None."""
        try:
            data = json.loads((self.example_dir / SAMPLE_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def _throw_away(self, name: str) -> None:
        """Delete a practice or example space: its folder and its signing key."""
        with WRITE_LOCK:  # no write is half-way through while the folder goes
            old = self._open.pop(name, None)
            if old is None and self.folder(name).exists():
                old = self._open_space(name)
            if old is not None:
                installation = old.ledger.installation
                old.close()
                if installation:
                    old.keystore.delete(installation)
            _remove_tree(self.folder(name))

    def reset_practice(self) -> AppContext:
        """Throw the practice space away and start a fresh, empty one."""
        with self._lock:
            self._throw_away(PRACTICE)
            log.info("practice space started over")
            return self.practice()

    def reset_example(self, lang: str = "en") -> AppContext:
        """Load the example afresh (after changes made in it, or in another language)."""
        with self._lock:
            self._throw_away(EXAMPLE)
            log.info("example loaded afresh")
            return self.example(lang)

    def _contexts(self) -> list[AppContext]:
        """The real record and every practice or example space that exists."""
        with self._lock:
            for name in SANDBOXES:
                if name not in self._open and self.folder(name).exists():
                    self._open[name] = self._open_space(name)
            return [self.real, *self._open.values()]

    def anchor_services(self) -> list:
        return [c.anchors for c in self._contexts()]

    def record_sources(self) -> int:
        """Every minute, in each existing space: new commits of the repositories it records
        (D-047) and new versions in the folders it watches (D-049)."""
        found = 0
        for c in self._contexts():
            if c.git.has_sources():
                found += c.git.check()["recorded"]
            if c.inbox.has_folders() or c.inbox.count():
                found += c.inbox.scan()
        return found

    def refresh(self, force: bool = False) -> dict[str, int]:
        """Hourly job: check stamps in every space."""
        total: dict[str, int] = {}
        for anchors in self.anchor_services():
            for key, value in anchors.refresh(force=force).items():
                total[key] = total.get(key, 0) + value
        return total

    def close(self) -> None:
        with self._lock:
            for ctx in self._open.values():
                ctx.close()
            self._open.clear()
