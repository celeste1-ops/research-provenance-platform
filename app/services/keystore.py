"""Where the Ed25519 signing key lives (PRD §9, S5).

Default: the macOS Keychain through ``keyring`` — never a plaintext file.
``memory`` is for tests. ``dev-insecure-file`` exists only so the app can run in a
Linux container without a keychain during development; it is opt-in, warns loudly,
and is documented in docs/DECISIONS.md.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from provenance_core.signing import private_key_from_raw, private_key_raw

log = logging.getLogger("rprov.keystore")
KEYRING_SERVICE = "rprov-signing-key"
KEYRING_SECRET_SERVICE = "rprov-secret"


class KeyStoreError(RuntimeError):
    pass


class KeyStore(ABC):
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
    def __init__(self) -> None:
        import keyring
        from keyring.backends import fail

        if isinstance(keyring.get_keyring(), fail.Keyring):
            raise KeyStoreError(
                "No system keychain is available. On macOS the Keychain is used automatically; "
                "for development without a keychain set RPROV_KEYSTORE=dev-insecure-file."
            )
        self._keyring = keyring

    def load(self, installation: str) -> Ed25519PrivateKey | None:
        value = self._keyring.get_password(KEYRING_SERVICE, installation)
        return private_key_from_raw(bytes.fromhex(value)) if value else None

    def save(self, installation: str, key: Ed25519PrivateKey) -> None:
        self._keyring.set_password(KEYRING_SERVICE, installation, private_key_raw(key).hex())

    def delete(self, installation: str) -> None:
        from keyring.errors import PasswordDeleteError

        try:
            self._keyring.delete_password(KEYRING_SERVICE, installation)
        except PasswordDeleteError:
            pass

    def load_secret(self, name: str) -> str | None:
        return self._keyring.get_password(KEYRING_SECRET_SERVICE, name)

    def save_secret(self, name: str, value: str) -> None:
        self._keyring.set_password(KEYRING_SECRET_SERVICE, name, value)


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
