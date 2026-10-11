"""Full backup and restore (PRD §14 S4, S7).

A backup is one zip (format ``rprov.backup/1``):

    rprov-backup.json          index: installation, counts, SHA-256 of every member
    db/rprov.sqlite3           consistent snapshot of the database
    blobs/ab/cd/<sha256>       every stored file
    key/signing-key.pem        the signing key, encrypted with the backup password

Restore only goes into an installation without records: rows are inserted (never
updated) and the key returns to the keychain, so the restored app signs new records
with the same identity. Extraction never follows member paths blindly: only the
expected names are accepted, links and traversal are rejected, and the total
uncompressed size is capped.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import sqlite3
import stat
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import insert, select

from app.db.models import WRITE_LOCK, AnchorRow, BlobRow, MetaRow, ProjectRow, RecordFileRow, RecordRow
from app.services.ledger import LedgerError
from provenance_core.signing import KeyBackupError, export_private_key_encrypted, load_private_key_encrypted

BACKUP_FORMAT = "rprov.backup/1"
MAX_RESTORE_BYTES = 20 * 1024**3  # 20 GiB uncompressed (S4)
_BLOB_NAME = re.compile(r"\Ablobs/([0-9a-f]{2})/([0-9a-f]{2})/([0-9a-f]{64})\Z")
_FIXED_NAMES = {"rprov-backup.json", "db/rprov.sqlite3", "key/signing-key.pem"}
# Copied in this order (foreign keys).
_TABLES = (ProjectRow, MetaRow, RecordRow, BlobRow, RecordFileRow, AnchorRow)


class BackupError(ValueError):
    pass


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_backup(ctx, password: str) -> tuple[str, bytes]:
    """Returns (file name, zip bytes)."""
    ledger = ctx.ledger
    key = ledger.signing_key()
    key_pem = export_private_key_encrypted(key, password)
    members: dict[str, bytes] = {}
    with tempfile.TemporaryDirectory(dir=ctx.settings.data_dir) as tmp:
        snap = Path(tmp) / "snapshot.sqlite3"
        with WRITE_LOCK:  # no writer runs during the snapshot
            src = sqlite3.connect(ctx.settings.db_path)
            dst = sqlite3.connect(snap)
            src.backup(dst)
            dst.close()
            src.close()
        members["db/rprov.sqlite3"] = snap.read_bytes()
    with ctx.sessions() as s:
        digests = list(s.scalars(select(BlobRow.sha256)))
    for digest in digests:
        members[f"blobs/{digest[:2]}/{digest[2:4]}/{digest}"] = ctx.blobs.get(digest)
    members["key/signing-key.pem"] = key_pem
    index = {
        "format": BACKUP_FORMAT,
        "installation": ledger.installation,
        "created_local": _now(),
        "record_count": ledger.record_count(),
        "blob_count": len(digests),
        "members": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(members.items())},
        "note": "The signing key inside is encrypted with the backup password; the database and files are not.",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("rprov-backup.json", json.dumps(index, indent=2))
        for name in sorted(members):
            zf.writestr(name, members[name])
    name = f"rprov-backup-{datetime.now(UTC).strftime('%Y-%m-%d-%H%M%S')}.zip"
    return name, buf.getvalue()


def write_backup_to(location: str, name: str, data: bytes) -> Path:
    folder = Path(location).expanduser()
    if not folder.is_absolute() or not folder.is_dir():
        raise BackupError("the backup location must be an existing folder (absolute path)")
    target = folder / name
    target.write_bytes(data)
    return target


def _safe_members(zf: zipfile.ZipFile, max_bytes: int) -> dict[str, zipfile.ZipInfo]:
    seen: dict[str, zipfile.ZipInfo] = {}
    total = 0
    for info in zf.infolist():
        name = info.filename
        if info.is_dir():
            continue
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise BackupError(f"refusing symbolic link {name!r}")
        if name.startswith("/") or "\\" in name or ".." in name.split("/") or ":" in name:
            raise BackupError(f"refusing unsafe path {name!r}")
        if name not in _FIXED_NAMES and not _BLOB_NAME.match(name):
            raise BackupError(f"unexpected file {name!r} in backup")
        if name in seen:
            raise BackupError(f"duplicate entry {name!r}")
        total += info.file_size
        if total > max_bytes:
            raise BackupError("backup is larger than the allowed uncompressed size")
        seen[name] = info
    missing = _FIXED_NAMES - set(seen)
    if missing:
        raise BackupError(f"backup is missing {sorted(missing)}")
    return seen


def _read_capped(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    # Never trust the declared size alone (zip bombs): read at most declared + 1 bytes.
    with zf.open(info) as fh:
        data = fh.read(info.file_size + 1)
    if len(data) != info.file_size:
        raise BackupError(f"{info.filename}: size does not match the archive directory")
    return data


def restore_backup(ctx, data: bytes, password: str, *, max_bytes: int = MAX_RESTORE_BYTES) -> dict:
    ledger = ctx.ledger
    if ledger.record_count() > 0 or ledger.installation is not None:
        raise LedgerError("restore only works into an empty installation (this one already has records)")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise BackupError("not a backup zip") from exc
    with zf:
        members = _safe_members(zf, max_bytes)
        index = json.loads(_read_capped(zf, members["rprov-backup.json"]))
        if index.get("format") != BACKUP_FORMAT:
            raise BackupError(f"unsupported backup format {index.get('format')!r}")
        expected = index.get("members") or {}
        contents: dict[str, bytes] = {}
        for name, info in members.items():
            if name == "rprov-backup.json":
                continue
            blob = _read_capped(zf, info)
            if expected.get(name) != hashlib.sha256(blob).hexdigest():
                raise BackupError(f"{name} does not match the backup index (damaged backup?)")
            m = _BLOB_NAME.match(name)
            if m and m.group(3) != hashlib.sha256(blob).hexdigest():
                raise BackupError(f"{name} is not the file its name says")
            contents[name] = blob
        if set(expected) != set(contents):
            raise BackupError("backup index and contents differ")
    try:
        key = load_private_key_encrypted(contents["key/signing-key.pem"], password)
    except KeyBackupError as exc:
        raise BackupError("wrong backup password (or damaged key file)") from exc

    with tempfile.TemporaryDirectory(dir=ctx.settings.data_dir) as tmp:
        snap = Path(tmp) / "restore.sqlite3"
        snap.write_bytes(contents["db/rprov.sqlite3"])
        src = sqlite3.connect(f"file:{snap}?mode=ro", uri=True)
        src.row_factory = sqlite3.Row
        rows = {t.__tablename__: [dict(r) for r in src.execute(f"SELECT * FROM {t.__tablename__}")] for t in _TABLES}
        src.close()
    installation = next((r["value"] for r in rows["meta"] if r["key"] == "installation"), None)
    if installation is None or installation != index.get("installation"):
        raise BackupError("backup does not name its installation consistently")
    # Files first (content-addressed, harmless), then all rows in one transaction.
    for name, blob in contents.items():
        if name.startswith("blobs/"):
            ctx.blobs.put(blob)
    with WRITE_LOCK, ctx.sessions.begin() as s:
        for table in _TABLES:
            batch = rows[table.__tablename__]
            if table is MetaRow:  # local settings: merge with whatever the fresh install has
                for r in batch:
                    s.merge(MetaRow(**r))
                continue
            if table is AnchorRow:
                for r in batch:
                    r.pop("id", None)
            if batch:
                s.execute(insert(table), batch)
    ledger.adopt_identity(installation, key)
    return {"installation": installation, "records": len(rows["records"]), "files": len(rows["blobs"])}
