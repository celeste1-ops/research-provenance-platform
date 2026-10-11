"""Where the Ed25519 signing key lives (PRD §9, S5).

Default: the macOS Keychain through ``keyring`` — never a plaintext file.
``memory`` is for tests. ``dev-insecure-file`` exists only so the app can run in a
Linux container without a keychain during development; it is opt-in, warns loudly,
and is documented in docs/DECISIONS.md.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from abc import ABC, abstractmethod
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from provenance_core.signing import private_key_from_raw, private_key_raw

log = logging.getLogger("rprov.keystore")
KEYRING_SERVICE = "rprov-signing-key"  # versions up to 0.3.1: one keychain item per key …
KEYRING_SECRET_SERVICE = "rprov-secret"  # … and per secret
# Since 0.3.2 everything lives in one keychain item (D-052): an app without a developer signature
# is asked about each item after every upgrade, so one item means one question.
BUNDLE_SERVICE = "rprov"
BUNDLE_ACCOUNT = "secrets"


class KeyStoreError(RuntimeError):
    pass


class KeychainDenied(KeyStoreError):
    """The system keychain refused access: the person clicked Deny, or it is locked."""


DENIED = "the system keychain refused access: click Try again at the top of the page and choose Always Allow"


class KeyStore(ABC):
    @property
    def denied(self) -> bool:
        """True after the keychain refused access, until the person asks to try again."""
        return False

    def retry(self) -> None:  # noqa: B027 - nothing to reset where nothing can refuse
        """The person asks to try the keychain again (it may ask them once more)."""

    @abstractmethod
    def load(self, installation: str) -> Ed25519PrivateKey | None: ...

    @abstractmethod
    def save(self, installation: str, key: Ed25519PrivateKey) -> None: ...

    # Only used to throw away a practice space (DECISIONS D-038); never for the real key.
    @abstractmethod
    def delete(self, installation: str) -> None: ...

    # Small secrets (the backup password used for automatic encrypted backups).
    @abstractmethod
    def load_secret(self, name: str) -> str | None: ...

    @abstractmethod
    def save_secret(self, name: str, value: str) -> None: ...


class KeyringKeyStore(KeyStore):
    # One gate for every keychain access of this app (real record and practice alike): once the
    # keychain refuses, nothing touches it again — so macOS does not ask again and again — until
    # the person clicks Try again. An app that is not signed by a developer is asked about each
    # item it did not create itself, after every upgrade, unless the person chose Always Allow.
    _denied = False
    _gate = threading.Lock()
    _gate_write = threading.RLock()  # read-modify-write of the one item

    def __init__(self) -> None:
        import keyring
        from keyring.backends import fail

        if isinstance(keyring.get_keyring(), fail.Keyring):
            raise KeyStoreError(
                "No system keychain is available. On macOS the Keychain is used automatically; "
                "for development without a keychain set RPROV_KEYSTORE=dev-insecure-file."
            )
        self._keyring = keyring

    @property
    def denied(self) -> bool:
        return KeyringKeyStore._denied

    def retry(self) -> None:
        with KeyringKeyStore._gate:
            KeyringKeyStore._denied = False

    def _call(self, fn, *args):
        from keyring.errors import KeyringLocked

        if KeyringKeyStore._denied:
            raise KeychainDenied(DENIED)
        try:
            return fn(*args)
        except KeyringLocked as exc:
            with KeyringKeyStore._gate:
                KeyringKeyStore._denied = True
            log.warning("the keychain refused access (%s); not asking again until the person clicks Try again", exc)
            raise KeychainDenied(DENIED) from None

    # ---------------------------------------------------------------- the one item (D-052)

    _bundle: dict | None = None  # its contents, read once per run (shared by real record and practice)
    # Only the macOS Keychain asks about each item; Windows Credential Manager asks nothing and
    # limits an item to 2.5 KB, so there every key and secret keeps an item of its own.
    one_item = sys.platform == "darwin"

    @classmethod
    def forget(cls) -> None:
        """Read the item again next time (as a new run of the app would)."""
        with cls._gate_write:
            cls._bundle = None

    def _read_bundle(self) -> dict:
        if KeyringKeyStore._bundle is None:
            raw = self._call(self._keyring.get_password, BUNDLE_SERVICE, BUNDLE_ACCOUNT)
            try:
                data = json.loads(raw) if raw else {}
                bundle = {"keys": dict(data.get("keys", {})), "secrets": dict(data.get("secrets", {}))}
            except (ValueError, AttributeError, TypeError):
                # Never overwrite what cannot be read: it may hold the signing key.
                raise KeyStoreError("the app's keychain item could not be read") from None
            KeyringKeyStore._bundle = bundle
        return _copy(KeyringKeyStore._bundle)

    def _write_bundle(self, bundle: dict) -> None:
        self._call(self._keyring.set_password, BUNDLE_SERVICE, BUNDLE_ACCOUNT, json.dumps(bundle, sort_keys=True))
        KeyringKeyStore._bundle = bundle

    def _get(self, part: str, name: str, legacy_service: str) -> str | None:
        with KeyringKeyStore._gate_write:
            value = self._read_bundle()[part].get(name)
            if value is not None:
                return value
            # Kept by an older version in an item of its own: move it into the one item (asked once).
            value = self._call(self._keyring.get_password, legacy_service, name)
            if value is not None:
                bundle = self._read_bundle()
                bundle[part][name] = value
                self._write_bundle(bundle)
                log.info("moved a keychain entry into the app's single keychain item")
            return value

    def _set(self, part: str, name: str, value: str | None) -> None:
        with KeyringKeyStore._gate_write:
            bundle = self._read_bundle()
            if value is None:
                if name not in bundle[part]:
                    return
                del bundle[part][name]
            else:
                bundle[part][name] = value
            self._write_bundle(bundle)

    def load(self, installation: str) -> Ed25519PrivateKey | None:
        if self.one_item:
            value = self._get("keys", installation, KEYRING_SERVICE)
        else:
            value = self._call(self._keyring.get_password, KEYRING_SERVICE, installation)
        return private_key_from_raw(bytes.fromhex(value)) if value else None

    def save(self, installation: str, key: Ed25519PrivateKey) -> None:
        if self.one_item:
            self._set("keys", installation, private_key_raw(key).hex())
        else:
            self._call(self._keyring.set_password, KEYRING_SERVICE, installation, private_key_raw(key).hex())

    def delete(self, installation: str) -> None:
        # Practice keys only (D-038). On macOS an older version's own item for it stays: deleting an
        # item another version made would make the system ask again, for a key nothing uses any more.
        if self.one_item:
            self._set("keys", installation, None)
            return
        from keyring.errors import PasswordDeleteError

        try:
            self._call(self._keyring.delete_password, KEYRING_SERVICE, installation)
        except PasswordDeleteError:
            pass

    def load_secret(self, name: str) -> str | None:
        if self.one_item:
            return self._get("secrets", name, KEYRING_SECRET_SERVICE)
        return self._call(self._keyring.get_password, KEYRING_SECRET_SERVICE, name)

    def save_secret(self, name: str, value: str) -> None:
        if self.one_item:
            self._set("secrets", name, value)
        else:
            self._call(self._keyring.set_password, KEYRING_SECRET_SERVICE, name, value)


def _copy(bundle: dict) -> dict:
    return {"keys": dict(bundle["keys"]), "secrets": dict(bundle["secrets"])}


class MemoryKeyStore(KeyStore):
    def __init__(self) -> None:
        self._keys: dict[str, bytes] = {}
        self._secrets: dict[str, str] = {}

    def load_secret(self, name: str) -> str | None:
        return self._secrets.get(name)

    def save_secret(self, name: str, value: str) -> None:
        self._secrets[name] = value

    def load(self, installation: str) -> Ed25519PrivateKey | None:
        raw = self._keys.get(installation)
        return private_key_from_raw(raw) if raw else None

    def save(self, installation: str, key: Ed25519PrivateKey) -> None:
        self._keys[installation] = private_key_raw(key)

    def delete(self, installation: str) -> None:
        self._keys.pop(installation, None)


class DevInsecureFileKeyStore(KeyStore):
    """Development only: key in a 0600 file inside the data directory."""

    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "DEV-INSECURE-signing-key.hex"
        log.warning("RPROV_KEYSTORE=dev-insecure-file: the signing key is stored unencrypted at %s", self.path)

    def load(self, installation: str) -> Ed25519PrivateKey | None:
        if not self.path.exists():
            return None
        stored_inst, raw = self.path.read_text(encoding="utf-8").split(":", 1)
        if stored_inst != installation:
            return None
        return private_key_from_raw(bytes.fromhex(raw.strip()))

    def save(self, installation: str, key: Ed25519PrivateKey) -> None:
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(f"{installation}:{private_key_raw(key).hex()}\n")

    def delete(self, installation: str) -> None:
        if self.load(installation) is not None:
            self.path.unlink()

    def _secret_path(self, name: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
        return self.path.parent / f"DEV-INSECURE-secret-{safe}"

    def load_secret(self, name: str) -> str | None:
        p = self._secret_path(name)
        return p.read_text(encoding="utf-8") if p.exists() else None

    def save_secret(self, name: str, value: str) -> None:
        fd = os.open(self._secret_path(name), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(value)


def make_keystore(kind: str, data_dir: Path) -> KeyStore:
    if kind == "keyring":
        return KeyringKeyStore()
    if kind == "memory":
        return MemoryKeyStore()
    if kind == "dev-insecure-file":
        return DevInsecureFileKeyStore(data_dir)
    raise KeyStoreError(f"unknown keystore {kind!r}")
