"""Content-addressed file storage: data/blobs/ab/cd/<sha256> (PRD §8)."""

from __future__ import annotations

import hashlib
import os
import secrets
from pathlib import Path


class BlobStore:
    def __init__(self, root: Path):
        self.root = root

    def path_for(self, sha256: str) -> Path:
        if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
            raise ValueError("not a SHA-256 hex digest")
        return self.root / sha256[:2] / sha256[2:4] / sha256

    def put(self, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        path = self.path_for(digest)
        if path.exists():
            return digest
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{digest}.{secrets.token_hex(4)}.tmp")
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        return digest

    def get(self, sha256: str) -> bytes:
        data = self.path_for(sha256).read_bytes()
        if hashlib.sha256(data).hexdigest() != sha256:
            raise OSError(f"blob {sha256} is corrupted on disk")
        return data

    def exists(self, sha256: str) -> bool:
        return self.path_for(sha256).exists()
