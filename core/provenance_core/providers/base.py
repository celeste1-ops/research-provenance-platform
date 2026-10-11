"""Common interface for time-proof providers (PRD §9).

``submit(record_id, manifest_bytes)`` asks for a proof, ``upgrade(proof)`` tries to
complete a pending one, ``verify(record_id, proof)`` checks one. Only the manifest
bytes — whose SHA-256 *is* the record ID — ever reach a provider; payloads and
content never do (PRD §7 rule 3).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from cryptography import x509

from ..proofs import ProofCheck


class ProviderUnavailable(Exception):
    """Transient failure (network down, service busy): retry later."""


class ProviderRejected(Exception):
    """The service answered but refused or returned something unusable."""


@dataclass
class AnchorResult:
    status: str  # "pending" | "confirmed"
    proof: bytes
    verified_time: str | None = None
    detail: str = ""


class TimestampProvider(ABC):
    kind: str  # "tsa" (third-party timestamp) or "btc" (Bitcoin anchor)
    name: str

    @abstractmethod
    def submit(self, record_id: str, manifest_bytes: bytes) -> AnchorResult: ...

    def upgrade(self, proof: bytes) -> AnchorResult:
        """Third-party timestamps are final on arrival; Bitcoin anchors override this."""
        return AnchorResult("confirmed", proof)

    @abstractmethod
    def verify(self, record_id: str, proof: bytes) -> ProofCheck: ...

    def trust_roots(self) -> list[x509.Certificate]:
        return []

    def bundle_certificates(self) -> dict[str, bytes]:
        """PEM files to place in an evidence bundle's certs/ directory."""
        return {}
