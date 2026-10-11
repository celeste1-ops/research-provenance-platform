"""Full backup and restore (PRD §14 S4, S7; DECISIONS D-028, D-031, D-039).

A backup file (``*.rprovbackup``) is fully encrypted:

    RPROV-BACKUP-ENC/2\n        magic
    {"slots": [...], ...}\n     header: key slots, nonce (no content)
    AES-256-GCM ciphertext       of the inner zip, under a random backup key;
                                 the header is authenticated too

The random backup key is stored in the header twice, each copy encrypted ("wrapped"):

* ``password`` slot — with a key derived from the backup password (scrypt);
* ``recovery`` slot — for the printable recovery code. The app keeps only the public
  half of an X25519 key derived from that code, so the code itself is never stored;
  each backup wraps the key to it with a fresh ephemeral key (X25519 + HKDF + AES-GCM).

Either the password or the recovery code opens the backup. The inner zip (format
``rprov.backup/1``) holds:

    rprov-backup.json          index: installation, counts, SHA-256 of every member
    db/rprov.sqlite3           consistent snapshot of the database
    blobs/ab/cd/<sha256>       every stored file
    key/signing-key.pem        the signing key, additionally encrypted on its own

Older formats still restore: ``RPROV-BACKUP-ENC/1`` (password only) and the original
unencrypted zips.

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
import secrets
import sqlite3
import stat
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from sqlalchemy import insert, select

from app.db.models import WRITE_LOCK, AnchorRow, BlobRow, MetaRow, ProjectRow, RecordFileRow, RecordRow
from app.services.ledger import LedgerError
from provenance_core.signing import KeyBackupError, export_private_key_encrypted, load_private_key_encrypted

BACKUP_FORMAT = "rprov.backup/1"
ENCRYPTED_MAGIC_V1 = b"RPROV-BACKUP-ENC/1\n"  # password only; still restorable
ENCRYPTED_MAGIC = b"RPROV-BACKUP-ENC/2\n"
ENCRYPTED_FORMAT = "rprov.backup-enc/2"
BACKUP_SUFFIX = ".rprovbackup"
RECOVERY_META = "backup_recovery"  # public half of the recovery key (JSON), see make_recovery
# scrypt cost: 2**17 * 8 * 128 bytes = 128 MiB of memory, about half a second.
SCRYPT_N = 2**17
SCRYPT_R = 8
SCRYPT_P = 1
# The recovery code carries 120 random bits, so a lighter scrypt is enough for it.
RECOVERY_SCRYPT_N = 2**14
RECOVERY_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32: no I, L, O, U
RECOVERY_LENGTH = 24
_SLOT_AAD = {"password": b"rprov-backup/2 password slot", "recovery": b"rprov-backup/2 recovery slot"}
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
    """Format 1 (password only). Kept so older backups and their tests stay readable."""
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
    return ENCRYPTED_MAGIC_V1 + header_line + AESGCM(key).encrypt(nonce, plain, ENCRYPTED_MAGIC_V1 + header_line)


def decrypt_backup(data: bytes, password: str) -> bytes:
    if not data.startswith(ENCRYPTED_MAGIC_V1):
        raise BackupError("not an encrypted backup")
    rest = data[len(ENCRYPTED_MAGIC_V1) :]
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
        return AESGCM(key).decrypt(nonce, rest[newline + 1 :], ENCRYPTED_MAGIC_V1 + header_line)
    except InvalidTag as exc:
        raise BackupError("wrong backup password (or damaged backup)") from exc


# ---------------------------------------------------------------- recovery code


def new_recovery_code() -> str:
    """24 characters from Crockford base32 (120 random bits), printed in four groups."""
    chars = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(RECOVERY_LENGTH))
    return "-".join(chars[i : i + 6] for i in range(0, RECOVERY_LENGTH, 6))


def normalize_recovery_code(code: str) -> str:
    text = "".join(code.split()).replace("-", "").upper()
    text = text.translate(str.maketrans({"O": "0", "I": "1", "L": "1"}))
    if len(text) != RECOVERY_LENGTH or any(c not in RECOVERY_ALPHABET for c in text):
        raise BackupError("a recovery code has 24 letters and digits (the dashes are optional)")
    return text


def _recovery_private_key(code: str, salt: bytes, n: int, r: int, p: int) -> X25519PrivateKey:
    raw = Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(normalize_recovery_code(code).encode())
    return X25519PrivateKey.from_private_bytes(raw)


def _raw_public(key) -> bytes:
    return key.public_bytes_raw()


def make_recovery(code: str) -> dict:
    """The public half kept by the app (the code itself is shown once and never stored)."""
    salt = secrets.token_bytes(16)
    public = _raw_public(_recovery_private_key(code, salt, RECOVERY_SCRYPT_N, 8, 1).public_key())
    return {
        "public_key": public.hex(),
        "salt": salt.hex(),
        "n": RECOVERY_SCRYPT_N,
        "r": 8,
        "p": 1,
        "id": hashlib.sha256(public).hexdigest()[:8],
        "created_local": _now(),
    }


def _hkdf(secret: bytes, salt: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=info).derive(secret)


def key_passphrase(backup_key: bytes) -> str:
    """Protects the signing key inside the inner zip; derived from the random backup key."""
    return _hkdf(backup_key, b"", b"rprov-backup/2 signing key").hex()


# ---------------------------------------------------------------- format 2


def seal_backup(plain: bytes, backup_key: bytes, password: str, recovery: dict | None) -> bytes:
    slots = []
    salt, slot_nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    kek = _derive_key(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    slots.append({
        "kind": "password", "kdf": "scrypt", "n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P, "salt": salt.hex(),
        "nonce": slot_nonce.hex(), "wrapped": AESGCM(kek).encrypt(slot_nonce, backup_key, _SLOT_AAD["password"]).hex(),
    })
    if recovery:
        public = bytes.fromhex(recovery["public_key"])
        ephemeral = X25519PrivateKey.generate()
        epk = _raw_public(ephemeral.public_key())
        kek = _hkdf(ephemeral.exchange(X25519PublicKey.from_public_bytes(public)), epk + public, _SLOT_AAD["recovery"])
        slot_nonce = secrets.token_bytes(12)
        slots.append({
            "kind": "recovery", "id": recovery["id"], "kdf": "scrypt", "n": recovery["n"], "r": recovery["r"],
            "p": recovery["p"], "salt": recovery["salt"], "public_key": recovery["public_key"], "epk": epk.hex(),
            "nonce": slot_nonce.hex(),
            "wrapped": AESGCM(kek).encrypt(slot_nonce, backup_key, _SLOT_AAD["recovery"]).hex(),
        })
    nonce = secrets.token_bytes(12)
    header = {"format": ENCRYPTED_FORMAT, "inner": BACKUP_FORMAT, "cipher": "AES-256-GCM", "nonce": nonce.hex(),
              "slots": slots}
    line = json.dumps(header, sort_keys=True).encode() + b"\n"
    return ENCRYPTED_MAGIC + line + AESGCM(backup_key).encrypt(nonce, plain, ENCRYPTED_MAGIC + line)


def _kdf_params(slot: dict) -> tuple[bytes, int, int, int]:
    n, r, p = int(slot["n"]), int(slot["r"]), int(slot["p"])
    if slot.get("kdf") != "scrypt" or not (2**10 <= n <= 2**20) or not (1 <= r <= 16) or not (1 <= p <= 4):
        raise BackupError("unsupported backup encryption")
    return bytes.fromhex(slot["salt"]), n, r, p


def _unwrap(slot: dict, password: str | None, recovery_code: str | None) -> bytes | None:
    salt, n, r, p = _kdf_params(slot)
    nonce, wrapped = bytes.fromhex(slot["nonce"]), bytes.fromhex(slot["wrapped"])
    if slot["kind"] == "password" and password is not None:
        kek = _derive_key(password, salt, n, r, p)
    elif slot["kind"] == "recovery" and recovery_code is not None:
        key = _recovery_private_key(recovery_code, salt, n, r, p)
        public = _raw_public(key.public_key())
        if public.hex() != slot["public_key"]:
            return None
        epk = bytes.fromhex(slot["epk"])
        kek = _hkdf(key.exchange(X25519PublicKey.from_public_bytes(epk)), epk + public, _SLOT_AAD["recovery"])
    else:
        return None
    try:
        return AESGCM(kek).decrypt(nonce, wrapped, _SLOT_AAD[slot["kind"]])
    except InvalidTag:
        return None


def open_backup(data: bytes, password: str | None = None, recovery_code: str | None = None):
    """Returns (inner zip bytes, backup key or None, what opened it).

    Unencrypted legacy zips pass through unchanged (the zip checks come later)."""
    if data.startswith(ENCRYPTED_MAGIC_V1):
        if not password:
            raise BackupError("this older backup has no recovery code; it opens with its password only")
        return decrypt_backup(data, password), None, "password"
    if not data.startswith(ENCRYPTED_MAGIC):
        return data, None, "password"
    rest = data[len(ENCRYPTED_MAGIC) :]
    newline = rest.find(b"\n")
    if newline < 0 or newline > 16384:
        raise BackupError("damaged backup header")
    line = rest[: newline + 1]
    try:
        header = json.loads(line)
        slots = list(header["slots"])
        nonce = bytes.fromhex(header["nonce"])
        if header.get("format") != ENCRYPTED_FORMAT or header.get("cipher") != "AES-256-GCM" or len(slots) > 4:
            raise BackupError("unsupported backup encryption")
        backup_key, opened_with = None, None
        for slot in slots:
            backup_key = _unwrap(slot, password or None, recovery_code or None)
            if backup_key is not None:
                opened_with = "recovery code" if slot["kind"] == "recovery" else "password"
                break
    except (ValueError, KeyError, TypeError) as exc:
        if isinstance(exc, BackupError):
            raise
        raise BackupError("damaged backup header") from exc
    if backup_key is None:
        if recovery_code and not any(s.get("kind") == "recovery" for s in slots):
            raise BackupError("this backup was made before a recovery code was set up; use its password")
        if recovery_code:
            raise BackupError("wrong recovery code (or damaged backup)")
        raise BackupError("wrong backup password (or damaged backup)")
    try:
        plain = AESGCM(backup_key).decrypt(nonce, rest[newline + 1 :], ENCRYPTED_MAGIC + line)
    except InvalidTag as exc:
        raise BackupError("damaged backup (the contents do not match)") from exc
    return plain, backup_key, opened_with


def create_backup(ctx, password: str) -> tuple[str, bytes]:
    """Returns (file name, encrypted backup bytes): opens with the password or the recovery code."""
    recovery = ctx.ledger.meta(RECOVERY_META)
    backup_key = secrets.token_bytes(32)
    name, plain = create_plain_backup(ctx, key_passphrase(backup_key), key_protection="backup-key")
    return name, seal_backup(plain, backup_key, password, json.loads(recovery) if recovery else None)


def create_plain_backup(ctx, key_passphrase: str, *, key_protection: str = "password") -> tuple[str, bytes]:
    """The inner zip only. ``key_protection`` says what the signing key inside is encrypted with:
    ``password`` (older backups) or ``backup-key`` (derived from the random backup key)."""
    ledger = ctx.ledger
    key = ledger.signing_key()
    key_pem = export_private_key_encrypted(key, key_passphrase)
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
        "key_protection": key_protection,
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


def restore_backup(
    ctx, data: bytes, password: str | None = None, *, recovery_code: str | None = None,
    max_bytes: int = MAX_RESTORE_BYTES,
) -> dict:
    ledger = ctx.ledger
    if ledger.record_count() > 0 or ledger.installation is not None:
        raise LedgerError("restore only works into an empty installation (this one already has records)")
    if not password and not recovery_code:
        raise BackupError("enter the backup password or the recovery code")
    data, backup_key, opened_with = open_backup(data, password or None, recovery_code or None)
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
    if index.get("key_protection", "password") == "backup-key":
        if backup_key is None:
            raise BackupError("damaged backup (the key file needs the encrypted backup around it)")
        passphrase = key_passphrase(backup_key)
    else:
        if not password:
            raise BackupError("this older backup opens with its password only")
        passphrase = password
    try:
        key = load_private_key_encrypted(contents["key/signing-key.pem"], passphrase)
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
    return {
        "installation": installation,
        "records": len(rows["records"]),
        "files": len(rows["blobs"]),
        "opened_with": opened_with,
    }
