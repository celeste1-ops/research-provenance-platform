"""Several RFC 3161 time-stamping authorities, tried in order (DECISIONS D-045).

FreeTSA first, DigiCert when FreeTSA cannot be reached (or the other way round). Each
record still gets one third-party timestamp, from whichever authority answered; the
token itself names its signer, and verification accepts any of the built-in roots.

Saving a step waits for its date stamp, so an authority that just failed would slow
down every save while it is unreachable. A failed authority therefore moves to the back
of the line for an hour; the next save goes straight to the one that works.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from cryptography import x509

from ..proofs import ProofCheck, verify_tsa_proof
from .base import AnchorResult, ProviderRejected, ProviderUnavailable, TimestampProvider

PENALTY_SECONDS = 3600.0


class TsaChain(TimestampProvider):
    kind = "tsa"

    def __init__(self, providers: list[TimestampProvider], *, clock: Callable[[], float] = time.monotonic):
        if not providers:
            raise ValueError("at least one time-stamping authority is needed")
        self.providers = list(providers)
        self.name = "+".join(p.name for p in self.providers)
        self._clock = clock
        self._failed_at: dict[str, float] = {}
        self._lock = threading.Lock()

    def order(self) -> list[TimestampProvider]:
        """Authorities that have not failed in the last hour first, in the configured order."""
        now = self._clock()
        with self._lock:
            recent = {n for n, t in self._failed_at.items() if now - t < PENALTY_SECONDS}
        return [p for p in self.providers if p.name not in recent] + [p for p in self.providers if p.name in recent]

    def submit(self, record_id: str, manifest_bytes: bytes) -> AnchorResult:
        errors = []
        for provider in self.order():
            try:
                result = provider.submit(record_id, manifest_bytes)
            except (ProviderUnavailable, ProviderRejected) as exc:
                with self._lock:
                    self._failed_at[provider.name] = self._clock()
                errors.append(str(exc))
                continue
            with self._lock:
                self._failed_at.pop(provider.name, None)
            result.provider = provider.name
            return result
        raise ProviderUnavailable("no time-stamping authority answered: " + "; ".join(errors))

    def verify(self, record_id: str, proof: bytes) -> ProofCheck:
        return verify_tsa_proof(record_id, proof, self.trust_roots())

    def trust_roots(self) -> list[x509.Certificate]:
        roots: list[x509.Certificate] = []
        for provider in self.providers:
            for cert in provider.trust_roots():
                if cert not in roots:
                    roots.append(cert)
        return roots

    def bundle_certificates(self) -> dict[str, bytes]:
        files: dict[str, bytes] = {}
        for provider in self.providers:
            for name, data in provider.bundle_certificates().items():
                files.setdefault(name, data)
        return files
