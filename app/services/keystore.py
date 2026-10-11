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


class KeyStoreError(RuntimeError):
    pass


class KeyStore(ABC):
    @abstractmethod
    def load(self, installation: str) -> Ed25519PrivateKey | None: ...

    @abstractmethod
    def save(self, installation: str, key: Ed25519PrivateKey) -> None: ...


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


class MemoryKeyStore(KeyStore):
    def __init__(self) -> None:
        self._keys: dict[str, bytes] = {}

    def load(self, installation: str) -> Ed25519PrivateKey | None:
        raw = self._keys.get(installation)
        return private_key_from_raw(raw) if raw else None

    def save(self, installation: str, key: Ed25519PrivateKey) -> None:
        self._keys[installation] = private_key_raw(key)


class DevInsecureFileKeyStore(KeyStore):
    """Development only: key in a 0600 file inside the data directory."""

    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "DEV-INSECURE-signing-key.hex"
        log.warning("RPROV_KEYSTORE=dev-insecure-file: the signing key is stored unencrypted at %s", self.path)

    def load(self, installation: str) -> Ed25519PrivateKey | None:
        if not self.path.exists():
            return None
        stored_inst, raw = self.path.read_text().split(":", 1)
        if stored_inst != installation:
            return None
        return private_key_from_raw(bytes.fromhex(raw.strip()))

    def save(self, installation: str, key: Ed25519PrivateKey) -> None:
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(f"{installation}:{private_key_raw(key).hex()}\n")


def make_keystore(kind: str, data_dir: Path) -> KeyStore:
    if kind == "keyring":
        return KeyringKeyStore()
    if kind == "memory":
        return MemoryKeyStore()
    if kind == "dev-insecure-file":
        return DevInsecureFileKeyStore(data_dir)
    raise KeyStoreError(f"unknown keystore {kind!r}")
