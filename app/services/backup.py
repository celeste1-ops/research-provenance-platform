"""Full backup and restore (PRD §14 S4, S7).

A backup file (``*.rprovbackup``) is fully encrypted with the backup password:

    RPROV-BACKUP-ENC/1\n        magic
    {"kdf": "scrypt", ...}\n     header: KDF parameters, salt, nonce (no content)
    AES-256-GCM ciphertext       of the inner zip; the header is authenticated too

The inner zip (format ``rprov.backup/1``) holds:

    rprov-backup.json          index: installation, counts, SHA-256 of every member
    db/rprov.sqlite3           consistent snapshot of the database
    blobs/ab/cd/<sha256>       every stored file
    key/signing-key.pem        the signing key, additionally encrypted with the password

Older, unencrypted ``rprov.backup/1`` zips can still be restored.

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

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from sqlalchemy import insert, select

from app.db.models import WRITE_LOCK, AnchorRow, BlobRow, MetaRow, ProjectRow, RecordFileRow, RecordRow
from app.services.ledger import LedgerError
from provenance_core.signing import KeyBackupError, export_private_key_encrypted, load_private_key_encrypted

BACKUP_FORMAT = "rprov.backup/1"
ENCRYPTED_MAGIC = b"RPROV-BACKUP-ENC/1\n"
BACKUP_SUFFIX = ".rprovbackup"
# scrypt cost: 2**17 * 8 * 128 bytes = 128 MiB of memory, about half a second.
SCRYPT_N = 2**17
SCRYPT_R = 8
SCRYPT_P = 1
MAX_RESTORE_BYTES = 20 * 1024**3  # 20 GiB uncompressed (S4)
_BLOB_NAME = re.compile(r"\Ablobs/([0-9a-f]{2})/([0-9a-f]{2})/([0-9a-f]{64})\Z")
_FIXED_NAMES = {"rprov-backup.json", "db/rprov.sqlite3", "key/signing-key.pem"}
# Copied in this order (foreign keys).
_TABLES = (ProjectRow, MetaRow, RecordRow, BlobRow, RecordFileRow, AnchorRow)


class BackupError(ValueError):
    pass


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _derive_key(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(password.encode("utf-8"))


def encrypt_backup(plain: bytes, password: str) -> bytes:
    import secrets

    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(12)
    header = {
        "kdf": "scrypt",
        "n": SCRYPT_N,
        "r": SCRYPT_R,
        "p": SCRYPT_P,
        "salt": salt.hex(),
        "cipher": "AES-256-GCM",
        "nonce": nonce.hex(),
        "inner": BACKUP_FORMAT,
    }
    header_line = json.dumps(header, sort_keys=True).encode() + b"\n"
    key = _derive_key(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    return ENCRYPTED_MAGIC + header_line + AESGCM(key).encrypt(nonce, plain, ENCRYPTED_MAGIC + header_line)


def decrypt_backup(data: bytes, password: str) -> bytes:
    if not data.startswith(ENCRYPTED_MAGIC):
        raise BackupError("not an encrypted backup")
    rest = data[len(ENCRYPTED_MAGIC) :]
    newline = rest.find(b"\n")
    if newline < 0 or newline > 4096:
        raise BackupError("damaged backup header")
    header_line = rest[: newline + 1]
    try:
        header = json.loads(header_line)
        n, r, p = int(header["n"]), int(header["r"]), int(header["p"])
        salt, nonce = bytes.fromhex(header["salt"]), bytes.fromhex(header["nonce"])
    except (ValueError, KeyError, TypeError) as exc:
        raise BackupError("damaged backup header") from exc
    if header.get("kdf") != "scrypt" or header.get("cipher") != "AES-256-GCM" or not (2**10 <= n <= 2**20):
        raise BackupError("unsupported backup encryption")
    key = _derive_key(password, salt, n, r, p)
    try:
        return AESGCM(key).decrypt(nonce, rest[newline + 1 :], ENCRYPTED_MAGIC + header_line)
    except InvalidTag as exc:
        raise BackupError("wrong backup password (or damaged backup)") from exc


def create_backup(ctx, password: str) -> tuple[str, bytes]:
    """Returns (file name, encrypted backup bytes)."""
    name, plain = create_plain_backup(ctx, password)
    return name, encrypt_backup(plain, password)


def create_plain_backup(ctx, password: str) -> tuple[str, bytes]:
    """The inner zip only (the signing key inside is still password-protected)."""
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
        "note": "Normally wrapped in an encrypted .rprovbackup file; the signing key is also encrypted on its own.",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("rprov-backup.json", json.dumps(index, indent=2))
        for name in sorted(members):
            zf.writestr(name, members[name])
    inst = (ledger.installation or "unknown")[:8]
    now = datetime.now(UTC)
    # Millisecond precision so two backups in the same second never share a name.
    name = f"rprov-backup-{inst}-{now:%Y%m%d-%H%M%S}-{now.microsecond // 1000:03d}{BACKUP_SUFFIX}"
    return name, buf.getvalue()


def write_backup_to(location: str, name: str, data: bytes) -> Path:
    import os

    folder = Path(location).expanduser()
    if not folder.is_absolute() or not folder.is_dir():
        raise BackupError("the backup location must be an existing folder (absolute path)")
    target = folder / name
    tmp = folder / f".{name}.partial"
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, target)  # never leaves a half-written backup under the real name
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
    if data.startswith(ENCRYPTED_MAGIC):
        data = decrypt_backup(data, password)
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise BackupError("not a backup file") from exc
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
