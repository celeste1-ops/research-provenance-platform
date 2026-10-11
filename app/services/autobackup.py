"""Automatic encrypted backups to a folder the author chooses (PRD S7, D-030..D-033).

The author picks a folder once — ideally *not* on this Mac's own disk: an external
drive, or a folder that a sync service the author already uses copies elsewhere
(iCloud Drive, Dropbox, Google Drive, OneDrive). After every change the app writes
a fully encrypted ``.rprovbackup`` there (debounced), and the hourly job catches
time-proof upgrades. The password lives in the system keychain so backups can run
unattended; it is needed again only to restore. The app itself never uploads
anything: writing the file is a local operation, and the encrypted file leaves the
Mac only if the chosen folder is synced by the author's own service.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

from app.db.models import AnchorRow, RecordRow
from app.i18n import device_word, tr
from app.services.backup import (
    BACKUP_SUFFIX,
    COPY_ANCHOR_META,
    COPY_META,
    ORIGIN_META,
    RECOVERY_META,
    SINCE_META,
    BackupError,
    backup_copy_id,
    folder_anchor,
    key_fingerprint,
    make_recovery,
    name_stamp,
    new_recovery_code,
    parse_backup_name,
    stamp_to_iso,
    write_backup_file,
)
from app.services.locations import SUGGESTED_FOLDER_NAME, suggestions, synced_service  # noqa: F401
from provenance_core.signing import public_key_hex

log = logging.getLogger("rprov.backup")

KEEP_BACKUPS = 10
DEBOUNCE_SECONDS = 20.0
MIN_PASSWORD = 8

def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def data_dir_warning(data_dir: Path) -> str | None:
    """The live database must not sit in a synced folder: sync can corrupt a database in use."""
    service = synced_service(data_dir)
    if service is None:
        return None
    return tr(
        "Your working data folder ({folder}) is inside {service}. Syncing can damage a database that is "
        "in use. Move it out (set RPROV_HOME to a normal folder) and let only the encrypted backups go into "
        "{service}.",
        folder=data_dir, service=service,
    )


def inside(folder: Path, data_dir: Path) -> bool:
    try:
        f, d = folder.expanduser().resolve(), data_dir.resolve()
    except OSError:
        return False
    return f == d or d in f.parents


def check_location(location: str, data_dir: Path, device: str = "computer") -> dict:
    """What the backup dialog shows while the author types or picks a folder."""
    folder = Path(location).expanduser()
    if not location.strip() or not folder.is_absolute():
        return {"ok": False, "kind": "invalid", "label": tr("Choose a full folder path"), "safe": False}
    if inside(folder, data_dir):
        return {"ok": False, "kind": "inside-data", "label": tr("Inside the app's own data folder"), "safe": False,
                "warning": tr("Choose a folder outside the app's data folder — and ideally not on this {device} at all.",
                              device=device_word(device))}
    if folder.is_dir():
        return {"ok": True, **classify_location(folder, data_dir, device)}
    if folder.parent.is_dir():
        where = classify_location(folder.parent, data_dir, device)
        return {"ok": True, **where, "creates": True}
    return {"ok": False, **classify_location(folder, data_dir, device)}


def classify_location(folder: Path, data_dir: Path, device: str = "computer") -> dict:
    """Where would a backup in ``folder`` survive? Returns kind + plain-language label.

    kind: synced (a cloud-sync folder) | external (another disk) | same-disk | missing
    """
    folder = folder.expanduser()
    if not folder.is_dir():
        return {"kind": "missing", "label": tr("Folder not found (is the drive connected?)"), "safe": False}
    resolved = folder.resolve()
    service = synced_service(resolved)
    if service is not None:
        return {"kind": "synced", "label": service, "safe": True}
    try:
        same = os.stat(resolved).st_dev == os.stat(data_dir).st_dev
    except OSError:
        same = True
    if not same:
        return {"kind": "external", "label": tr("Another disk"), "safe": True}
    return {
        "kind": "same-disk",
        "label": tr("This {device}'s own disk", device=device_word(device)),
        "safe": False,
        "warning": tr("This folder is on this {device}'s own disk: if this {device} is lost or breaks, this backup "
                      "is lost with it. Choose an external drive or a folder your sync service (iCloud Drive, OneDrive, "
                      "Dropbox…) copies elsewhere.", device=device_word(device)),
    }


class AutoBackup:
    def __init__(self, ctx, debounce: float = DEBOUNCE_SECONDS):
        self.ctx = ctx
        self.debounce = debounce
        self._timer: threading.Timer | None = None
        # Separate locks: saving a step (which only schedules) never waits for a running backup.
        self._run_lock = threading.Lock()
        self._timer_lock = threading.Lock()

    # ------------------------------------------------------------------ settings

    def _secret_name(self) -> str:
        # Per copy (D-042): a restored or copied installation shares the installation ID and,
        # on the same Mac, the keychain; its own entry keeps it from touching the original's.
        return f"backup-password:{self.ctx.ledger.installation}:{backup_copy_id(self.ctx)}"

    def _password(self) -> str | None:
        ledger = self.ctx.ledger
        if not ledger.installation:
            return None
        password = self.ctx.keystore.load_secret(self._secret_name())
        if password is None and not ledger.meta(ORIGIN_META):
            # Set up before per-copy entries existed: only the original install may take it over.
            legacy = self.ctx.keystore.load_secret(f"backup-password:{ledger.installation}")
            if legacy is not None:
                self.ctx.keystore.save_secret(self._secret_name(), legacy)
                password = legacy
        return password

    def detect_copied_folder(self) -> bool:
        """At start-up: is this data folder a copy (Migration Assistant, Time Machine, ``cp -r``)?

        A copy carries the original's copy id inside its database. It then gets a new id, its
        automatic backup pauses until the author confirms, and the original's files count as
        another copy's from now on (D-042)."""
        ledger = self.ctx.ledger
        copy, anchor = ledger.meta(COPY_META), ledger.meta(COPY_ANCHOR_META)
        if not copy:
            return False
        current = folder_anchor(self.ctx.settings.data_dir)
        if not anchor:
            ledger.set_meta(COPY_ANCHOR_META, current)  # first start since copy ids were tied to folders
            return False
        if anchor == current:
            return False
        for key, value in ((COPY_META, ""), (COPY_ANCHOR_META, ""), (ORIGIN_META, "copied"),
                           ("backup_auto", "0"), ("backup_paused", "copied"), ("backup_last_error", ""),
                           ("backup_last_fingerprint", ""), (SINCE_META, name_stamp())):
            ledger.set_meta(key, value)
        log.warning("this data folder is a copy of another one: automatic backup paused until confirmed")
        return True

    def configure(self, location: str, password: str, *, create: bool = False) -> dict:
        ledger = self.ctx.ledger
        if not ledger.initialized():
            raise BackupError("set up the app first")
        if len(password or "") < MIN_PASSWORD:
            raise BackupError(f"the backup password needs at least {MIN_PASSWORD} characters")
        folder = Path(location).expanduser()
        if not folder.is_absolute():
            raise BackupError("choose a full folder path")
        if inside(folder, self.ctx.settings.data_dir):
            raise BackupError("choose a folder outside the app's data folder")
        if create and not folder.exists():
            if not folder.parent.is_dir():
                raise BackupError("the folder's parent does not exist")
            folder.mkdir()
        if not folder.is_dir():
            raise BackupError("that folder does not exist")
        if not os.access(folder, os.W_OK):
            raise BackupError("this app cannot write to that folder")
        self.ctx.keystore.save_secret(self._secret_name(), password)
        ledger.set_meta("backup_location", str(folder))
        ledger.set_meta("backup_auto", "1")
        ledger.set_meta("backup_paused", "")
        code = None if ledger.meta(RECOVERY_META) else self._store_recovery()
        self.run("set up")
        out = self.status()
        if code:
            out["recovery_code"] = code  # shown once, never stored
        return out

    def _store_recovery(self) -> str:
        code = new_recovery_code()
        self.ctx.ledger.set_meta(RECOVERY_META, json.dumps(make_recovery(code), sort_keys=True))
        return code

    def new_recovery_code(self) -> str:
        """Replace the recovery code: new backups open with the new one (older ones with the old one)."""
        st = self.status()
        if not st["configured"]:
            raise BackupError("turn on automatic backup first")
        if st["state"] == "paused":
            raise BackupError("confirm the backup folder first (automatic backup is paused)")
        code = self._store_recovery()
        self.run("new recovery code")
        return code

    def adopt_restored_password(self, password: str | None) -> None:
        """Remember the password a backup was restored with, for when the author resumes backups.

        After a restore with the recovery code the password is unknown: the app asks for a new
        one. A password already in the keychain for this installation (a restore drill on the
        same Mac) is never replaced: it may be newer than the backup's."""
        if password and self._password() is None:
            self.ctx.keystore.save_secret(self._secret_name(), password)

    def resume(self) -> dict:
        """After a restore or copy: the author confirms this copy should back up to the folder."""
        if not self.status()["configured"]:
            raise BackupError("set a backup password first")
        ledger = self.ctx.ledger
        ledger.set_meta("backup_auto", "1")
        ledger.set_meta("backup_paused", "")
        self.run("resumed")
        return self.status()

    # ------------------------------------------------------------------ other copies (D-041)

    def _latest_other_copy(self) -> tuple[str, str | None] | None:
        """Newest backup in the folder written by *another* copy of this installation after this
        copy's starting point: e.g. the old Mac still running after the new Mac was restored."""
        ledger = self.ctx.ledger
        location = ledger.meta("backup_location")
        if not location or not ledger.installation:
            return None
        folder = Path(location)
        inst = ledger.installation[:8]
        mine = ledger.meta(COPY_META) or None
        since = ledger.meta(SINCE_META) or ""
        latest = None
        try:
            names = [p.name for p in folder.glob(f"rprov-backup-{inst}-*{BACKUP_SUFFIX}")]
        except OSError:
            return None
        for name in names:
            parsed = parse_backup_name(name)
            if parsed is None or parsed["inst"] != inst:
                continue
            copy = parsed["copy"]
            if copy is not None and copy == mine:
                continue
            if copy is None and not since:
                continue  # older file names: this copy's own past, before per-copy ids
            if parsed["stamp"] <= since:
                continue
            if latest is None or parsed["stamp"] > latest[0]:
                latest = (parsed["stamp"], copy)
        return latest

    def acknowledge_other_copy(self) -> dict:
        """The author says the other copy is gone: stop warning until it writes again."""
        latest = self._latest_other_copy()
        if latest is not None:
            self.ctx.ledger.set_meta(SINCE_META, latest[0])
        return self.status()

    # ------------------------------------------------------------------ state

    def _fingerprint(self) -> str:
        with self.ctx.sessions() as s:
            seq = s.scalar(select(func.max(RecordRow.seq)))
            confirmed = s.scalar(select(func.count()).select_from(AnchorRow).where(AnchorRow.status == "confirmed"))
            proofs = s.scalar(select(func.count()).select_from(AnchorRow).where(AnchorRow.proof_bytes.is_not(None)))
        return f"{seq}:{confirmed}:{proofs}"

    def status(self) -> dict:
        ledger = self.ctx.ledger
        location = ledger.meta("backup_location")
        configured = bool(location) and self._password() is not None
        st: dict = {
            "configured": configured,
            "location": location,
            "auto": ledger.meta("backup_auto") == "1",
            "last_backup": ledger.meta("backup_last_local"),
            "last_file": ledger.meta("backup_last_file"),
            "last_error": ledger.meta("backup_last_error") or None,
            "pending_changes": configured and ledger.meta("backup_last_fingerprint") != self._fingerprint(),
            "keep": KEEP_BACKUPS,
        }
        if location:
            st["where"] = classify_location(Path(location), self.ctx.settings.data_dir, self.ctx.settings.device)
        if location and not configured:
            st["needs_password"] = True
        paused = ledger.meta("backup_paused") or ""
        st["paused_after_restore"] = paused == "restored"
        st["paused_reason"] = paused or None
        other = self._latest_other_copy() if location else None
        st["other_copy"] = {"last_backup": stamp_to_iso(other[0]), "copy": other[1]} if other else None
        recovery = ledger.meta(RECOVERY_META)
        st["recovery"] = (
            {"configured": True, **{k: v for k, v in json.loads(recovery).items() if k in ("id", "created_local")}}
            if recovery
            else {"configured": False}
        )
        st["data_dir_warning"] = data_dir_warning(self.ctx.settings.data_dir)
        try:  # printed on the recovery sheet, shown again after a recovery-code restore
            st["key_fingerprint"] = key_fingerprint(public_key_hex(ledger.signing_key().public_key()))
        except Exception:  # noqa: BLE001 - no key available (not set up yet)
            st["key_fingerprint"] = None
        if location and paused:
            st["state"] = "paused"  # even without a password: confirm the folder first (D-040)
        elif not configured:
            st["state"] = "off"
        elif not st["auto"]:
            st["state"] = "paused"
        elif st["last_error"]:
            st["state"] = "error"
        elif st["other_copy"]:
            st["state"] = "other-copy"
        elif not st["where"]["safe"]:
            st["state"] = "same-disk"
        else:
            st["state"] = "ok"
        return st

    # ------------------------------------------------------------------ running

    def run(self, reason: str = "manual") -> dict:
        """Write one encrypted backup now (if configured and not paused) and prune old ones."""
        with self._run_lock:
            ledger = self.ctx.ledger
            location = ledger.meta("backup_location")
            password = self._password()
            if not location or password is None:
                return {"ran": False, "reason": "backup is not set up"}
            if ledger.meta("backup_paused"):
                return {"ran": False, "reason": "automatic backup is paused: confirm the backup folder first"}
            fingerprint = self._fingerprint()
            try:
                path = write_backup_file(self.ctx, password, Path(location))
                self._prune(Path(location))
            except Exception as exc:  # noqa: BLE001 - report, keep the app running
                msg = f"{type(exc).__name__}: {exc}"
                ledger.set_meta("backup_last_error", msg)
                log.warning("backup failed (%s): %s", reason, msg)
                return {"ran": False, "reason": msg}
            ledger.set_meta("backup_last_local", _iso(_now()))
            ledger.set_meta("backup_last_file", str(path))
            ledger.set_meta("backup_last_error", "")
            ledger.set_meta("backup_last_fingerprint", fingerprint)
            ledger.set_meta("key_backup_done", "1")
            log.info("backup written (%s): %s", reason, path)
            return {"ran": True, "path": str(path)}

    def _prune(self, folder: Path) -> None:
        # Only this copy's own files: another Mac (or a restored copy) may share the folder.
        inst = (self.ctx.ledger.installation or "")[:8]
        copy = backup_copy_id(self.ctx)
        mine = sorted(folder.glob(f"rprov-backup-{inst}-{copy}-*{BACKUP_SUFFIX}"))
        for old in mine[:-KEEP_BACKUPS]:
            try:
                old.unlink()
            except OSError:
                pass

    def maybe_run(self, reason: str = "scheduled") -> dict:
        st = self.status()
        if not st["configured"] or not st["auto"]:
            return {"ran": False, "reason": "automatic backup is off"}
        if not st["pending_changes"] and not st["last_error"]:
            return {"ran": False, "reason": "no changes since the last backup"}
        return self.run(reason)

    def schedule(self, *_args) -> None:
        """Called after each change: back up once things have been quiet for a moment."""
        if self.debounce <= 0:
            self.maybe_run("after change")
            return
        with self._timer_lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self.debounce, self.maybe_run, kwargs={"reason": "after change"})
            self._timer.daemon = True
            self._timer.start()

    def stop(self) -> None:
        with self._timer_lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
