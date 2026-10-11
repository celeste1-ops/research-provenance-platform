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

import logging
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

from app.db.models import AnchorRow, RecordRow
from app.services.backup import BACKUP_SUFFIX, BackupError, create_backup, write_backup_to

log = logging.getLogger("rprov.backup")

KEEP_BACKUPS = 10
DEBOUNCE_SECONDS = 20.0
MIN_PASSWORD = 8

ICLOUD_DRIVE = Path("~/Library/Mobile Documents/com~apple~CloudDocs").expanduser()
CLOUD_STORAGE = Path("~/Library/CloudStorage").expanduser()
SUGGESTED_FOLDER_NAME = "Research Provenance Backups"


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def classify_location(folder: Path, data_dir: Path) -> dict:
    """Where would a backup in ``folder`` survive? Returns kind + plain-language label.

    kind: synced (a cloud-sync folder) | external (another disk) | same-disk | missing
    """
    folder = folder.expanduser()
    if not folder.is_dir():
        return {"kind": "missing", "label": "Folder not found (is the drive connected?)", "safe": False}
    resolved = folder.resolve()
    for root, label in ((ICLOUD_DRIVE, "iCloud Drive"),):
        if root.exists() and (resolved == root.resolve() or root.resolve() in resolved.parents):
            return {"kind": "synced", "label": label, "safe": True}
    if CLOUD_STORAGE.exists():
        base = CLOUD_STORAGE.resolve()
        if base in resolved.parents:
            provider = resolved.relative_to(base).parts[0].split("-")[0]
            return {"kind": "synced", "label": provider, "safe": True}
    try:
        same = os.stat(resolved).st_dev == os.stat(data_dir).st_dev
    except OSError:
        same = True
    if not same:
        return {"kind": "external", "label": "Another disk", "safe": True}
    return {
        "kind": "same-disk",
        "label": "This Mac's own disk",
        "safe": False,
        "warning": "This folder is on the same disk as your records. It does not help if this Mac is lost "
        "or breaks — choose an external drive or a synced folder such as iCloud Drive.",
    }


def suggestions(data_dir: Path) -> list[dict]:
    """Folders worth offering: iCloud Drive, other cloud-sync folders, external drives."""
    out = []
    if ICLOUD_DRIVE.is_dir():
        out.append({"path": str(ICLOUD_DRIVE / SUGGESTED_FOLDER_NAME), "label": "iCloud Drive", "kind": "synced"})
    if CLOUD_STORAGE.is_dir():
        for entry in sorted(CLOUD_STORAGE.iterdir()):
            if entry.is_dir() and not entry.name.startswith("."):
                provider = entry.name.split("-")[0]
                out.append({"path": str(entry / SUGGESTED_FOLDER_NAME), "label": provider, "kind": "synced"})
    volumes = Path("/Volumes")
    if volumes.is_dir():
        for vol in sorted(volumes.iterdir()):
            try:
                if vol.is_dir() and not vol.is_symlink() and os.stat(vol).st_dev != os.stat(data_dir).st_dev:
                    out.append({"path": str(vol / SUGGESTED_FOLDER_NAME), "label": f"Drive “{vol.name}”",
                                "kind": "external"})
            except OSError:
                continue
    return out


class AutoBackup:
    def __init__(self, ctx, debounce: float = DEBOUNCE_SECONDS):
        self.ctx = ctx
        self.debounce = debounce
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ settings

    def _secret_name(self) -> str:
        return f"backup-password:{self.ctx.ledger.installation}"

    def _password(self) -> str | None:
        if not self.ctx.ledger.installation:
            return None
        return self.ctx.keystore.load_secret(self._secret_name())

    def configure(self, location: str, password: str, *, create: bool = False) -> dict:
        ledger = self.ctx.ledger
        if not ledger.initialized():
            raise BackupError("set up the app first")
        if len(password or "") < MIN_PASSWORD:
            raise BackupError(f"the backup password needs at least {MIN_PASSWORD} characters")
        folder = Path(location).expanduser()
        if not folder.is_absolute():
            raise BackupError("choose a full folder path")
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
        self.run("set up")
        return self.status()

    def adopt_restored_password(self, password: str) -> None:
        """After a restore the same password keeps automatic backups going."""
        self.ctx.keystore.save_secret(self._secret_name(), password)

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
            st["where"] = classify_location(Path(location), self.ctx.settings.data_dir)
        if location and not configured:
            st["needs_password"] = True
        if not configured:
            st["state"] = "off"
        elif st["last_error"]:
            st["state"] = "error"
        elif not st["where"]["safe"]:
            st["state"] = "same-disk"
        else:
            st["state"] = "ok"
        return st

    # ------------------------------------------------------------------ running

    def run(self, reason: str = "manual") -> dict:
        """Write one encrypted backup now (if configured) and prune old ones."""
        with self._lock:
            ledger = self.ctx.ledger
            location = ledger.meta("backup_location")
            password = self._password()
            if not location or password is None:
                return {"ran": False, "reason": "backup is not set up"}
            fingerprint = self._fingerprint()
            try:
                name, data = create_backup(self.ctx, password)
                path = write_backup_to(location, name, data)
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
        inst = (self.ctx.ledger.installation or "")[:8]
        mine = sorted(folder.glob(f"rprov-backup-{inst}-*{BACKUP_SUFFIX}"))
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
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self.debounce, self.maybe_run, kwargs={"reason": "after change"})
            self._timer.daemon = True
            self._timer.start()

    def stop(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
