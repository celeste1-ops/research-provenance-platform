"""Ed25519 signing identity (PRD §9).

The signed message is the 32 raw bytes of the record ID. A signature only shows
that the same key signed every record; it says nothing about who holds the key.
"""

from __future__ import annotations

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


class KeyBackupError(ValueError):
    """A key backup could not be read (wrong password or not a key)."""


def generate_private_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def private_key_from_raw(raw: bytes) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(raw)


def private_key_raw(key: Ed25519PrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )


def public_key_hex(key: Ed25519PublicKey) -> str:
    return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


def public_key_from_hex(value: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(bytes.fromhex(value))


def public_key_pem(key: Ed25519PublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)


def public_key_from_pem(data: bytes) -> Ed25519PublicKey:
    key = serialization.load_pem_public_key(data)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("not an Ed25519 public key")
    return key


def sign_record_id(key: Ed25519PrivateKey, record_id: str) -> bytes:
    return key.sign(bytes.fromhex(record_id))


def verify_record_signature(key: Ed25519PublicKey, record_id: str, signature: bytes | None) -> bool:
    if not signature or len(signature) != 64:
        return False
    try:
        key.verify(signature, bytes.fromhex(record_id))
    except (InvalidSignature, ValueError):
        return False
    return True


def export_private_key_encrypted(key: Ed25519PrivateKey, password: str) -> bytes:
    """Password-protected PKCS#8 PEM backup of the signing key (PRD S5)."""
    if not password:
        raise ValueError("a key backup must have a password")
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(password.encode("utf-8")),
    )


def load_private_key_encrypted(data: bytes, password: str) -> Ed25519PrivateKey:
    try:
        key = serialization.load_pem_private_key(data, password=password.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise KeyBackupError(f"cannot open key backup: {exc}") from None
    if not isinstance(key, Ed25519PrivateKey):
        raise KeyBackupError("key backup does not contain an Ed25519 key")
    return key
