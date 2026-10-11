"""Full backup and restore (PRD §14 S4, S7; DECISIONS D-028, D-031, D-039, D-040, D-042).

A backup file (``*.rprovbackup``) is fully encrypted:

    RPROV-BACKUP-ENC/3\\n        magic
    {"slots": [...], ...}\\n     header: key slots, chunk size, nonce prefix (no content)
    chunk 0, chunk 1, …          the inner zip in 4 MiB pieces, each AES-256-GCM under a
                                 random backup key; every piece is bound to the header,
                                 its position and whether it is the last one, so pieces
                                 cannot be swapped, dropped or cut off unnoticed

The random backup key is stored in the header twice, each copy encrypted ("wrapped"):

* ``password`` slot — with a key derived from the backup password (scrypt);
* ``recovery`` slot — for the printable recovery code. The app keeps only the public
  half of an X25519 key derived from that code, so the code itself is never stored;
  each backup wraps the key to it with a fresh ephemeral key (X25519 + HKDF + AES-GCM).

Either the password or the recovery code opens the backup. Backups are written and read
piece by piece through temporary files, so their size is not limited by memory or by
AES-GCM's single-message limit. The inner zip (format ``rprov.backup/1``) holds:

    rprov-backup.json          index: installation, counts, SHA-256 of every member
    db/rprov.sqlite3           consistent snapshot of the database
    blobs/ab/cd/<sha256>       every stored file
    key/signing-key.pem        the signing key, additionally encrypted on its own

Older formats still restore: ``RPROV-BACKUP-ENC/2`` (one piece), ``RPROV-BACKUP-ENC/1``
(password only) and the original unencrypted zips.

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
import os
import re
import secrets
import shutil
import sqlite3
import stat
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from sqlalchemy import insert, select

from app.db.models import WRITE_LOCK, AnchorRow, BlobRow, MetaRow, ProjectRow, RecordFileRow, RecordRow
from app.services.ledger import LedgerError
from provenance_core.signing import (
    KeyBackupError,
    export_private_key_encrypted,
    load_private_key_encrypted,
    private_key_raw,
    public_key_hex,
)

BACKUP_FORMAT = "rprov.backup/1"
ENCRYPTED_MAGIC_V1 = b"RPROV-BACKUP-ENC/1\n"  # password only, one piece; still restorable
ENCRYPTED_MAGIC_V2 = b"RPROV-BACKUP-ENC/2\n"  # key slots, one piece; still restorable
ENCRYPTED_MAGIC = b"RPROV-BACKUP-ENC/3\n"
ENCRYPTED_FORMAT_V2 = "rprov.backup-enc/2"
ENCRYPTED_FORMAT = "rprov.backup-enc/3"
CHUNK_SIZE = 4 * 1024 * 1024
BACKUP_SUFFIX = ".rprovbackup"
RECOVERY_META = "backup_recovery"  # public half of the recovery key (JSON), see make_recovery
COPY_META = "backup_copy"  # which copy of the installation wrote a backup file (D-040)
COPY_ANCHOR_META = "backup_copy_anchor"  # identity of the data folder the copy id belongs to (D-042)
ORIGIN_META = "backup_origin"  # "" for the original install, "restored" or "copied" otherwise
SINCE_META = "backup_since"  # other copies' files up to this time are known/expected (D-041)
# rprov-backup-<installation[:8]>[-<copy>]-<YYYYMMDD-HHMMSS-mmm>.rprovbackup (no copy id before D-040)
_BACKUP_NAME = re.compile(
    r"\Arprov-backup-(?P<inst>[0-9a-z]{1,8})(?:-(?P<copy>c[0-9a-f]{5}))?-(?P<stamp>\d{8}-\d{6}-\d{3})\.rprovbackup\Z"
)
# scrypt cost: 2**17 * 8 * 128 bytes = 128 MiB of memory, about half a second.
SCRYPT_N = 2**17
SCRYPT_R = 8
SCRYPT_P = 1
MAX_KDF_MEMORY = 256 * 1024 * 1024  # a backup header may never ask for more (crafted files)
# The recovery code carries 120 random bits, so a lighter scrypt is enough for it.
RECOVERY_SCRYPT_N = 2**14
RECOVERY_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32: no I, L, O, U
RECOVERY_LENGTH = 24
_DASHES = "-‐‑‒–—―−"
_SLOT_AAD = {"password": b"rprov-backup/2 password slot", "recovery": b"rprov-backup/2 recovery slot"}
MAX_RESTORE_BYTES = 20 * 1024**3  # 20 GiB uncompressed (S4)
_BLOB_NAME = re.compile(r"\Ablobs/([0-9a-f]{2})/([0-9a-f]{2})/([0-9a-f]{64})\Z")
_FIXED_NAMES = {"rprov-backup.json", "db/rprov.sqlite3", "key/signing-key.pem"}
_SMALL_MEMBER = 64 * 1024 * 1024  # index and key file are read into memory, nothing bigger
_COPY_BUF = 1024 * 1024
# Copied in this order (foreign keys).
_TABLES = (ProjectRow, MetaRow, RecordRow, BlobRow, RecordFileRow, AnchorRow)


class BackupError(ValueError):
    pass


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _check_kdf(n: int, r: int, p: int) -> None:
    if n < 2**10 or n & (n - 1) or not (1 <= r <= 32) or not (1 <= p <= 4) or 128 * n * r > MAX_KDF_MEMORY:
        raise BackupError("unsupported backup encryption")


def _derive_key(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    _check_kdf(n, r, p)
    try:
        return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(password.encode("utf-8"))
    except MemoryError as exc:
        raise BackupError("not enough memory to open this backup") from exc


def key_fingerprint(public_hex: str) -> str:
    """Short, readable form of a signing public key: the first 16 hex digits in groups of 4."""
    return " ".join(public_hex[i : i + 4] for i in range(0, 16, 4))


# ---------------------------------------------------------------- format 1 (read; written only by tests)


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
    if header.get("kdf") != "scrypt" or header.get("cipher") != "AES-256-GCM":
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
    text = "".join(c for c in "".join(code.split()) if c not in _DASHES).upper()
    text = text.translate(str.maketrans({"O": "0", "I": "1", "L": "1"}))
    if len(text) != RECOVERY_LENGTH or any(c not in RECOVERY_ALPHABET for c in text):
        raise BackupError("a recovery code has 24 letters and digits (the dashes are optional)")
    return text


def _recovery_private_key(code: str, salt: bytes, n: int, r: int, p: int) -> X25519PrivateKey:
    normalized = normalize_recovery_code(code)
    raw = _derive_key(normalized, salt, n, r, p)
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


# ---------------------------------------------------------------- key slots (formats 2 and 3)


def _make_slots(backup_key: bytes, password: str, recovery: dict | None) -> list[dict]:
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
    return slots


def _kdf_params(slot: dict) -> tuple[bytes, int, int, int]:
    n, r, p = int(slot["n"]), int(slot["r"]), int(slot["p"])
    if slot.get("kdf") != "scrypt":
        raise BackupError("unsupported backup encryption")
    _check_kdf(n, r, p)
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


def _unlock(header: dict, password: str | None, recovery_code: str | None) -> tuple[bytes, str]:
    """Find a slot the password or recovery code opens; returns (backup key, what opened it)."""
    try:
        slots = list(header["slots"])
        if len(slots) > 4:
            raise BackupError("unsupported backup encryption")
        for slot in slots:
            backup_key = _unwrap(slot, password or None, recovery_code or None)
            if backup_key is not None:
                return backup_key, ("recovery code" if slot["kind"] == "recovery" else "password")
    except BackupError:
        raise
    except (ValueError, KeyError, TypeError) as exc:
        raise BackupError("damaged backup header") from exc
    if recovery_code and not any(isinstance(s, dict) and s.get("kind") == "recovery" for s in slots):
        raise BackupError("this backup was made before a recovery code was set up; use its password")
    if recovery_code:
        raise BackupError("wrong recovery code (or damaged backup)")
    raise BackupError("wrong backup password (or damaged backup)")


def seal_backup(plain: bytes, backup_key: bytes, password: str, recovery: dict | None) -> bytes:
    """Format 2 (one piece). Only kept so its reader stays tested; new backups use format 3."""
    nonce = secrets.token_bytes(12)
    header = {"format": ENCRYPTED_FORMAT_V2, "inner": BACKUP_FORMAT, "cipher": "AES-256-GCM", "nonce": nonce.hex(),
              "slots": _make_slots(backup_key, password, recovery)}
    line = json.dumps(header, sort_keys=True).encode() + b"\n"
    return ENCRYPTED_MAGIC_V2 + line + AESGCM(backup_key).encrypt(nonce, plain, ENCRYPTED_MAGIC_V2 + line)


# ---------------------------------------------------------------- format 3 (pieces)


def _chunk_nonce(prefix: bytes, index: int) -> bytes:
    return prefix + index.to_bytes(4, "big")


def _chunk_aad(head: bytes, index: int, final: bool) -> bytes:
    return head + index.to_bytes(8, "big") + (b"\x01" if final else b"\x00")


def seal_stream(src: BinaryIO, dst: BinaryIO, backup_key: bytes, password: str, recovery: dict | None,
                chunk_size: int | None = None) -> None:
    """Encrypt the inner zip from ``src`` into ``dst`` piece by piece (format 3)."""
    chunk_size = chunk_size or CHUNK_SIZE
    prefix = secrets.token_bytes(8)
    header = {"format": ENCRYPTED_FORMAT, "inner": BACKUP_FORMAT, "cipher": "AES-256-GCM", "chunk_size": chunk_size,
              "nonce_prefix": prefix.hex(), "slots": _make_slots(backup_key, password, recovery)}
    head = ENCRYPTED_MAGIC + json.dumps(header, sort_keys=True).encode() + b"\n"
    dst.write(head)
    aead = AESGCM(backup_key)
    index = 0
    while True:
        piece = src.read(chunk_size)
        final = len(piece) < chunk_size  # the last piece is always short (empty if need be)
        if index >= 2**32:
            raise BackupError("backup too large")
        dst.write(aead.encrypt(_chunk_nonce(prefix, index), piece, _chunk_aad(head, index, final)))
        index += 1
        if final:
            return


def _read_header(src: BinaryIO, magic: bytes) -> tuple[dict, bytes]:
    line = src.readline(16385)
    if not line.endswith(b"\n"):
        raise BackupError("damaged backup header")
    try:
        header = json.loads(line)
    except ValueError as exc:
        raise BackupError("damaged backup header") from exc
    if not isinstance(header, dict):
        raise BackupError("damaged backup header")
    return header, magic + line


def _open_v3(src: BinaryIO, dst: BinaryIO, password, recovery_code) -> tuple[bytes, str]:
    header, head = _read_header(src, ENCRYPTED_MAGIC)
    try:
        chunk_size = int(header["chunk_size"])
        prefix = bytes.fromhex(header["nonce_prefix"])
    except (ValueError, KeyError, TypeError) as exc:
        raise BackupError("damaged backup header") from exc
    if (header.get("format") != ENCRYPTED_FORMAT or header.get("cipher") != "AES-256-GCM" or len(prefix) != 8
            or not (4096 <= chunk_size <= 64 * 1024 * 1024)):
        raise BackupError("unsupported backup encryption")
    backup_key, opened_with = _unlock(header, password, recovery_code)
    aead = AESGCM(backup_key)
    index = 0
    while True:
        block = src.read(chunk_size + 16)
        if len(block) < 16:
            raise BackupError("damaged backup (cut short)")
        final = len(block) < chunk_size + 16
        try:
            dst.write(aead.decrypt(_chunk_nonce(prefix, index), block, _chunk_aad(head, index, final)))
        except InvalidTag as exc:
            raise BackupError("damaged backup (the contents do not match)") from exc
        index += 1
        if final:
            return backup_key, opened_with


def _open_v2(src: BinaryIO, dst: BinaryIO, password, recovery_code) -> tuple[bytes, str]:
    header, head = _read_header(src, ENCRYPTED_MAGIC_V2)
    try:
        nonce = bytes.fromhex(header["nonce"])
    except (ValueError, KeyError, TypeError) as exc:
        raise BackupError("damaged backup header") from exc
    if header.get("format") != ENCRYPTED_FORMAT_V2 or header.get("cipher") != "AES-256-GCM":
        raise BackupError("unsupported backup encryption")
    backup_key, opened_with = _unlock(header, password, recovery_code)
    try:
        dst.write(AESGCM(backup_key).decrypt(nonce, src.read(), head))
    except InvalidTag as exc:
        raise BackupError("damaged backup (the contents do not match)") from exc
    return backup_key, opened_with


def open_backup_stream(src: BinaryIO, dst: BinaryIO, password: str | None = None,
                       recovery_code: str | None = None) -> tuple[bytes | None, str]:
    """Decrypt any backup format from ``src`` into ``dst`` (the inner zip).

    Returns (backup key or None, what opened it). Unencrypted legacy zips are copied as they are."""
    magic = src.read(len(ENCRYPTED_MAGIC))
    if magic == ENCRYPTED_MAGIC:
        return _open_v3(src, dst, password, recovery_code)
    if magic == ENCRYPTED_MAGIC_V2:
        return _open_v2(src, dst, password, recovery_code)
    if magic == ENCRYPTED_MAGIC_V1:
        if not password:
            raise BackupError("this older backup has no recovery code; it opens with its password only")
        dst.write(decrypt_backup(magic + src.read(), password))
        return None, "password"
    dst.write(magic)
    shutil.copyfileobj(src, dst, _COPY_BUF)
    return None, "password"


def open_backup(data: bytes, password: str | None = None, recovery_code: str | None = None):
    """In-memory convenience: (inner zip bytes, backup key or None, what opened it)."""
    out = io.BytesIO()
    backup_key, opened_with = open_backup_stream(io.BytesIO(data), out, password, recovery_code)
    return out.getvalue(), backup_key, opened_with


# ---------------------------------------------------------------- writing backups


def name_stamp(now: datetime | None = None) -> str:
    """UTC time as used in backup file names: YYYYMMDD-HHMMSS-mmm (sorts as text)."""
    now = now or datetime.now(UTC)
    return f"{now:%Y%m%d-%H%M%S}-{now.microsecond // 1000:03d}"


def parse_backup_name(name: str) -> dict | None:
    m = _BACKUP_NAME.match(name)
    return m.groupdict() if m else None


def stamp_to_iso(stamp: str) -> str:
    return f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]}T{stamp[9:11]}:{stamp[11:13]}:{stamp[13:15]}Z"


def folder_anchor(data_dir: Path) -> str:
    """Identity of the data folder on disk. A copy made by Migration Assistant, Time Machine or
    ``cp -r`` is a new folder (new inode and creation time) even though its contents match."""
    st = os.stat(data_dir)
    birth = getattr(st, "st_birthtime", None)
    return f"{st.st_ino}:{int(birth) if birth else ''}"


def backup_copy_id(ctx) -> str:
    """A short id for this copy of the installation, part of every backup file name.

    A restored or copied installation keeps its installation ID; the copy id keeps the
    copies' backup files apart, so one copy never prunes the other's backups. It is reset
    by every restore and whenever the data folder turns out to be a copy (D-040, D-042)."""
    ledger = ctx.ledger
    copy = ledger.meta(COPY_META)
    if not copy:
        copy = "c" + secrets.token_hex(3)[:5]
        ledger.set_meta(COPY_META, copy)
        ledger.set_meta(COPY_ANCHOR_META, folder_anchor(ctx.settings.data_dir))
    return copy


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(_COPY_BUF):
            h.update(block)
    return h.hexdigest()


def write_plain_backup(ctx, key_passphrase: str, target: Path, *, key_protection: str = "password") -> str:
    """Write the inner zip to ``target`` and return the backup's file name.

    ``key_protection`` says what the signing key inside is encrypted with: ``password``
    (older backups) or ``backup-key`` (derived from the random backup key). Files are
    added one at a time, so memory use stays small whatever the size of the research."""
    ledger = ctx.ledger
    key = ledger.signing_key()
    key_pem = export_private_key_encrypted(key, key_passphrase)
    digests_of: dict[str, str] = {}
    with tempfile.TemporaryDirectory(dir=ctx.settings.data_dir) as tmp:
        snap = Path(tmp) / "snapshot.sqlite3"
        with WRITE_LOCK:  # no writer runs during the snapshot
            src = sqlite3.connect(ctx.settings.db_path)
            dst = sqlite3.connect(snap)
            src.backup(dst)
            dst.close()
            src.close()
        with ctx.sessions() as s:
            digests = sorted(s.scalars(select(BlobRow.sha256)))
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            zf.write(snap, "db/rprov.sqlite3")
            digests_of["db/rprov.sqlite3"] = _hash_file(snap)
            for digest in digests:
                data = ctx.blobs.get(digest)
                name = f"blobs/{digest[:2]}/{digest[2:4]}/{digest}"
                zf.writestr(name, data)
                digests_of[name] = hashlib.sha256(data).hexdigest()
            zf.writestr("key/signing-key.pem", key_pem)
            digests_of["key/signing-key.pem"] = hashlib.sha256(key_pem).hexdigest()
            index = {
                "format": BACKUP_FORMAT,
                "installation": ledger.installation,
                "key_protection": key_protection,
                "created_local": _now(),
                "record_count": ledger.record_count(),
                "blob_count": len(digests),
                "members": dict(sorted(digests_of.items())),
                "note": "Normally wrapped in an encrypted .rprovbackup file; the signing key is also encrypted on its own.",
            }
            zf.writestr("rprov-backup.json", json.dumps(index, indent=2))
    inst = (ledger.installation or "unknown")[:8]
    # Millisecond precision so two backups in the same second never share a name.
    return f"rprov-backup-{inst}-{backup_copy_id(ctx)}-{name_stamp()}{BACKUP_SUFFIX}"


def create_plain_backup(ctx, key_passphrase: str, *, key_protection: str = "password") -> tuple[str, bytes]:
    """The inner zip as bytes (tests and the older unencrypted format)."""
    with tempfile.TemporaryDirectory(dir=ctx.settings.data_dir) as tmp:
        target = Path(tmp) / "inner.zip"
        name = write_plain_backup(ctx, key_passphrase, target, key_protection=key_protection)
        return name, target.read_bytes()


def write_backup_file(ctx, password: str, folder: Path) -> Path:
    """Write one encrypted backup into ``folder``: it opens with the password or the recovery code.

    Written to a hidden ``.partial`` name, flushed, then renamed, so a crash never leaves
    a broken backup under a real name."""
    folder = Path(folder).expanduser()
    if not folder.is_absolute() or not folder.is_dir():
        raise BackupError("the backup location must be an existing folder (absolute path)")
    recovery = ctx.ledger.meta(RECOVERY_META)
    backup_key = secrets.token_bytes(32)
    with tempfile.TemporaryDirectory(dir=ctx.settings.data_dir) as tmp:
        inner = Path(tmp) / "inner.zip"
        name = write_plain_backup(ctx, key_passphrase(backup_key), inner, key_protection="backup-key")
        target = folder / name
        partial = folder / f".{name}.partial"
        try:
            with open(inner, "rb") as src, open(partial, "wb") as dst:
                seal_stream(src, dst, backup_key, password, json.loads(recovery) if recovery else None)
                dst.flush()
                os.fsync(dst.fileno())
            os.replace(partial, target)
        finally:
            if partial.exists():
                partial.unlink()
    return target


def create_backup(ctx, password: str) -> tuple[str, bytes]:
    """(file name, encrypted backup bytes) — for tests and small one-off downloads."""
    with tempfile.TemporaryDirectory(dir=ctx.settings.data_dir) as tmp:
        path = write_backup_file(ctx, password, Path(tmp))
        return path.name, path.read_bytes()


# ---------------------------------------------------------------- restore


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
    if info.file_size > _SMALL_MEMBER and not info.filename.startswith("blobs/"):
        raise BackupError(f"{info.filename}: unexpectedly large")
    with zf.open(info) as fh:
        data = fh.read(info.file_size + 1)
    if len(data) != info.file_size:
        raise BackupError(f"{info.filename}: size does not match the archive directory")
    return data


def _stream_member(zf: zipfile.ZipFile, info: zipfile.ZipInfo, out: BinaryIO | None = None) -> str:
    """SHA-256 of a member, read in pieces and never past its declared size (optionally copied out)."""
    h = hashlib.sha256()
    size = 0
    with zf.open(info) as fh:
        while block := fh.read(min(_COPY_BUF, info.file_size - size + 1)):
            size += len(block)
            if size > info.file_size:
                break
            h.update(block)
            if out is not None:
                out.write(block)
    if size != info.file_size:
        raise BackupError(f"{info.filename}: size does not match the archive directory")
    return h.hexdigest()


def restore_backup(
    ctx, data: bytes | Path, password: str | None = None, *, recovery_code: str | None = None,
    max_bytes: int = MAX_RESTORE_BYTES,
) -> dict:
    ledger = ctx.ledger
    if ledger.record_count() > 0 or ledger.installation is not None:
        raise LedgerError("restore only works into an empty installation (this one already has records)")
    if not password and not recovery_code:
        raise BackupError("enter the backup password or the recovery code")
    with tempfile.TemporaryDirectory(dir=ctx.settings.data_dir) as tmp:
        inner = Path(tmp) / "inner.zip"
        src = open(data, "rb") if isinstance(data, Path) else io.BytesIO(data)  # noqa: SIM115
        with src, open(inner, "wb") as dst:
            backup_key, opened_with = open_backup_stream(src, dst, password or None, recovery_code or None)
        try:
            zf = zipfile.ZipFile(inner)
        except zipfile.BadZipFile as exc:
            raise BackupError("not a backup file") from exc
        with zf:
            members = _safe_members(zf, max_bytes)
            index = json.loads(_read_capped(zf, members["rprov-backup.json"]))
            if index.get("format") != BACKUP_FORMAT:
                raise BackupError(f"unsupported backup format {index.get('format')!r}")
            expected = index.get("members") or {}
            if set(expected) != set(members) - {"rprov-backup.json"}:
                raise BackupError("backup index and contents differ")
            # 1. Check every member against the index, piece by piece; keep only the small ones.
            snap = Path(tmp) / "restore.sqlite3"
            key_pem = b""
            for name, info in members.items():
                if name == "rprov-backup.json":
                    continue
                if name == "db/rprov.sqlite3":
                    with open(snap, "wb") as out:
                        digest = _stream_member(zf, info, out)
                elif name == "key/signing-key.pem":
                    key_pem = _read_capped(zf, info)
                    digest = hashlib.sha256(key_pem).hexdigest()
                else:
                    digest = _stream_member(zf, info)
                    if _BLOB_NAME.match(name).group(3) != digest:
                        raise BackupError(f"{name} is not the file its name says")
                if expected.get(name) != digest:
                    raise BackupError(f"{name} does not match the backup index (damaged backup?)")
            if index.get("key_protection", "password") == "backup-key":
                if backup_key is None:
                    raise BackupError("damaged backup (the key file needs the encrypted backup around it)")
                passphrase = key_passphrase(backup_key)
            else:
                if not password:
                    raise BackupError("this older backup opens with its password only")
                passphrase = password
            try:
                key = load_private_key_encrypted(key_pem, passphrase)
            except KeyBackupError as exc:
                raise BackupError("wrong backup password (or damaged key file)") from exc

            db = sqlite3.connect(f"file:{snap}?mode=ro", uri=True)
            db.row_factory = sqlite3.Row
            rows = {t.__tablename__: [dict(r) for r in db.execute(f"SELECT * FROM {t.__tablename__}")]
                    for t in _TABLES}
            db.close()
            installation = next((r["value"] for r in rows["meta"] if r["key"] == "installation"), None)
            if installation is None or installation != index.get("installation"):
                raise BackupError("backup does not name its installation consistently")
            # On the same Mac the keychain may already hold this installation's key (a restore drill).
            # It must be the very same key; a different one is never overwritten.
            existing = ctx.keystore.load(installation)
            if existing is not None and private_key_raw(existing) != private_key_raw(key):
                raise BackupError(
                    "this Mac's keychain already holds a different signing key for this installation; "
                    "nothing was restored"
                )
            # 2. Files (content-addressed, harmless if anything below fails), one at a time.
            for name, info in members.items():
                if name.startswith("blobs/"):
                    ctx.blobs.put(_read_capped(zf, info))
    # 3. All rows in one transaction.
    with WRITE_LOCK, ctx.sessions.begin() as s:
        for table in _TABLES:
            batch = rows[table.__tablename__]
            if table is MetaRow:  # local settings: merge with whatever the fresh install has
                for r in batch:
                    s.merge(MetaRow(**r))
                # A restored copy remembers the backup folder but never writes there by itself:
                # the author confirms first (another Mac may still be backing up into it). D-040.
                # It is a new copy with its own id; files other copies wrote before this restore
                # are the past it came from (D-041, D-042).
                for meta_key, meta_value in (("backup_auto", "0"), ("backup_paused", "restored"),
                                             (COPY_META, ""), (COPY_ANCHOR_META, ""), (ORIGIN_META, "restored"),
                                             ("backup_last_error", ""), ("backup_last_fingerprint", ""),
                                             (SINCE_META, name_stamp())):
                    s.merge(MetaRow(key=meta_key, value=meta_value))
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
        "key_fingerprint": key_fingerprint(public_key_hex(key.public_key())),
    }
