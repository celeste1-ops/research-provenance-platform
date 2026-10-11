"""Third-party timestamp via RFC 3161 (default: FreeTSA), PRD §9.

The request is built with ``rfc3161-client`` (≥ 1.0.6) from the manifest bytes with
SHA-256 *explicitly* selected, so the message imprint equals the record ID. Only
that 32-byte digest, a random nonce and ``certReq=true`` are sent; HTTP goes
through ``httpx``. Every response is fully verified (signature, chain to the
built-in root, imprint, nonce) before it is accepted.
"""

from __future__ import annotations

import hashlib

import httpx
from cryptography import x509
from rfc3161_client import HashAlgorithm, TimestampRequestBuilder, decode_timestamp_response

from ..certs import builtin_tsa_roots, freetsa_bundle_files
from ..proofs import ProofCheck, canonical_tsr, verify_tsa_proof
from .base import AnchorResult, ProviderRejected, ProviderUnavailable, TimestampProvider

FREETSA_URL = "https://freetsa.org/tsr"


class Rfc3161Provider(TimestampProvider):
    kind = "tsa"

    def __init__(
        self,
        url: str = FREETSA_URL,
        *,
        timeout: float = 15.0,
        roots: list[x509.Certificate] | None = None,
        name: str = "freetsa",
        bundle_files: dict[str, bytes] | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.url = url
        self.timeout = timeout
        self.name = name
        self._roots = roots if roots is not None else builtin_tsa_roots()
        self._bundle_files = bundle_files if bundle_files is not None else freetsa_bundle_files()
        self._transport = transport

    def build_request(self, manifest_bytes: bytes):
        return (
            TimestampRequestBuilder()
            .data(manifest_bytes)
            .hash_algorithm(HashAlgorithm.SHA256)
            .nonce(nonce=True)
            .cert_request(cert_request=True)
            .build()
        )

    def submit(self, record_id: str, manifest_bytes: bytes) -> AnchorResult:
        if hashlib.sha256(manifest_bytes).hexdigest() != record_id:
            raise ValueError("manifest bytes do not hash to the record ID")
        request = self.build_request(manifest_bytes)
        if bytes(request.message_imprint.message) != bytes.fromhex(record_id):
            raise ProviderRejected("request imprint is not the record ID")
        try:
            with httpx.Client(timeout=self.timeout, transport=self._transport) as client:
                response = client.post(
                    self.url,
                    content=request.as_bytes(),
                    headers={"Content-Type": "application/timestamp-query", "Accept": "application/timestamp-reply"},
                )
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"{self.name}: {type(exc).__name__}: {exc}") from None
        if response.status_code >= 500 or response.status_code == 429:
            raise ProviderUnavailable(f"{self.name}: HTTP {response.status_code}")
        if response.status_code != 200:
            raise ProviderRejected(f"{self.name}: HTTP {response.status_code}")
        tsr = canonical_tsr(response.content)  # certificates in DER order (D-045), as stored and exported
        try:
            parsed = decode_timestamp_response(tsr)
            nonce = parsed.tst_info.nonce
        except Exception as exc:  # noqa: BLE001
            raise ProviderRejected(f"{self.name}: unreadable response: {exc}") from None
        if nonce != request.nonce:
            raise ProviderRejected(f"{self.name}: nonce in the response does not match the request")
        check = self.verify(record_id, tsr)
        if not check.verified:
            raise ProviderRejected(f"{self.name}: {check.code}: {check.detail}")
        return AnchorResult("confirmed", tsr, check.time, f"signed by {check.source}")

    def verify(self, record_id: str, proof: bytes) -> ProofCheck:
        return verify_tsa_proof(record_id, proof, self._roots)

    def trust_roots(self) -> list[x509.Certificate]:
        return list(self._roots)

    def bundle_certificates(self) -> dict[str, bytes]:
        return dict(self._bundle_files)
