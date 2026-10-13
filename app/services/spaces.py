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

The example is a third space of the same kind: the fictional FSF sample research (D-059), loaded
the first time it is opened. It is kept apart from practice, so practice only ever holds what the
author tried there. It comes in each language of the interface, as an installation of its own in
``<data dir>/example/<language>``, and the example a request sees is the one in the language it
names (``X-RPROV-Lang``): switching the language switches the sample's own words too (D-065).
Loading it afresh throws all of them away.

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

from app import i18n
from app.db.models import WRITE_LOCK
from app.services.context import AppContext
from app.services.keystore import DevInsecureFileKeyStore

log = logging.getLogger("rprov.spaces")

REAL = "real"
PRACTICE = "practice"
EXAMPLE = "example"
SPACE_HEADER = "x-rprov-space"
SAMPLE_FILE = "sample.json"  # in an example folder: what it remembers about the FSF sample (D-059)


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
        """The folder of every language's example."""
        return self.folder(EXAMPLE)

    @staticmethod
    def _example(lang: str | None) -> str:
        return f"{EXAMPLE}/{i18n.normalize(lang)}"

    def _sample_lang(self, folder) -> str:
        try:
            return i18n.normalize(json.loads((folder / SAMPLE_FILE).read_text(encoding="utf-8")).get("lang"))
        except (OSError, ValueError, AttributeError):
            return "en"

    def _move_old_sample(self) -> None:
        """Up to v0.6.1 the sample was loaded into practice (D-059, D-062). A practice space holding
        it becomes the example in its language, and practice starts empty: practice only holds the
        author's own. (A trial build of v0.7.0 kept a single example right in ``example``; it moves
        the same way.)"""
        try:
            if (self.example_dir / SAMPLE_FILE).is_file():
                lang = self._sample_lang(self.example_dir)
                aside = self.folder(f"{EXAMPLE}-{lang}")
                os.replace(self.example_dir, aside)
                self.example_dir.mkdir()
                os.replace(aside, self.folder(self._example(lang)))
            if (self.practice_dir / SAMPLE_FILE).is_file():
                target = self.folder(self._example(self._sample_lang(self.practice_dir)))
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(self.practice_dir, target)
                    log.info("the sample research moved from practice to the example space")
        except OSError as exc:
            log.warning("could not move the sample research to the example space: %s", exc)

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
        """The practice installation, created (with its own key) on first use; its first project
        is named in the interface's language (D-065)."""
        with self._lock:
            ctx = self._context(PRACTICE)
            if auto_init and not ctx.ledger.initialized():
                ctx.ledger.init_identity(self._practice_label())
                ctx.ledger.create_project(i18n.tr("Practice project"))
            return ctx

    def example(self, lang: str | None = None) -> AppContext:
        """The example (D-064) in ``lang``, or else in the language of the request (D-065): the FSF
        sample in that language, loaded the first time it is opened."""
        name = self._example(lang or i18n.current())
        with self._lock:
            ctx = self._context(name)
            if not ctx.ledger.initialized():
                from app.demo import load_sample

                info = load_sample(ctx, name.rsplit("/", 1)[1])
                (self.folder(name) / SAMPLE_FILE).write_text(json.dumps(info, indent=1), encoding="utf-8")
            return ctx

    def _practice_label(self) -> str:
        label = None
        if self.real.ledger.initialized():
            rows = self.real.ledger.records()
            if rows:
                label = json.loads(rows[0].payload_bytes).get("author_label")
        return i18n.tr("{label} (practice)", label=label) if label else i18n.tr("Practice")

    def sample_info(self, lang: str | None = None) -> dict | None:
        """What the example in ``lang`` (else the request's) remembers about its FSF sample (D-059)."""
        try:
            folder = self.folder(self._example(lang or i18n.current()))
            data = json.loads((folder / SAMPLE_FILE).read_text(encoding="utf-8"))
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

    def reset_example(self, lang: str | None = None) -> AppContext:
        """Load the example afresh, in every language: whatever was changed in it is gone."""
        with self._lock:
            for name in self._examples():
                self._throw_away(name)
            _remove_tree(self.example_dir)
            log.info("example loaded afresh")
            return self.example(lang)

    def _examples(self) -> list[str]:
        """The example spaces there are: one per language opened."""
        return [n for n in (self._example(lang) for lang in i18n.LANGS) if n in self._open or self.folder(n).exists()]

    def _contexts(self) -> list[AppContext]:
        """The real record and every practice or example space that exists."""
        with self._lock:
            for name in (PRACTICE, *self._examples()):
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
