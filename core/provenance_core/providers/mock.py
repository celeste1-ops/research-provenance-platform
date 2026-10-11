"""MockProvider: deterministic, offline time proofs for development and tests.

* ``kind="tsa"`` issues *real* RFC 3161 time-stamp responses signed by a throwaway
  mock CA (``mock_tsa/``), so tests exercise exactly the verification path FreeTSA
  tokens take. Nothing trusts the mock root unless told to (``--tsa-root``).
* ``kind="btc"`` issues a clearly marked mock Bitcoin anchor that stays pending
  until ``confirm_on_upgrade`` is enabled; confirmed mock anchors are only accepted
  by verifiers running in explicit test mode.

Results depend only on the record ID and the injected clock.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from ..der import (
    der_explicit,
    der_gentime,
    der_int,
    der_null,
    der_octets,
    der_oid,
    der_seq,
    der_set,
    der_tlv,
)
from ..proofs import MOCK_BTC_MAGIC, ProofCheck, format_utc, verify_btc_proof, verify_tsa_proof
from .base import AnchorResult, ProviderUnavailable, TimestampProvider

MOCK_TSA_DIR = Path(__file__).resolve().parent / "mock_tsa"
MOCK_TSA_POLICY = "1.2.3.4.1"

_SHA256 = "2.16.840.1.101.3.4.2.1"
_RSA = "1.2.840.113549.1.1.1"
_SIGNED_DATA = "1.2.840.113549.1.7.2"
_TST_INFO = "1.2.840.113549.1.9.16.1.4"
_CONTENT_TYPE = "1.2.840.113549.1.9.3"
_MESSAGE_DIGEST = "1.2.840.113549.1.9.4"
_SIGNING_CERT_V2 = "1.2.840.113549.1.9.16.2.47"


def mock_tsa_root() -> x509.Certificate:
    return x509.load_pem_x509_certificate((MOCK_TSA_DIR / "mock-tsa-root.pem").read_bytes())


def _alg(oid: str) -> bytes:
    return der_seq(der_oid(oid), der_null())


def build_mock_tsr(
    digest: bytes, gen_time: datetime, nonce: int | None = None, *, cert: x509.Certificate | None = None, key=None
) -> bytes:
    """A complete, verifiable RFC 3161 TimeStampResp from the mock TSA (or from the
    given certificate and RSA key, e.g. an "attacker" TSA in tamper tests)."""
    if cert is None or key is None:
        cert = x509.load_pem_x509_certificate((MOCK_TSA_DIR / "mock-tsa.pem").read_bytes())
        key = serialization.load_pem_private_key((MOCK_TSA_DIR / "mock-tsa-key.pem").read_bytes(), None)
    cert_der = cert.public_bytes(serialization.Encoding.DER)
    serial = int.from_bytes(digest[:8], "big") >> 1 or 1
    fields = [
        der_int(1),
        der_oid(MOCK_TSA_POLICY),
        der_seq(_alg(_SHA256), der_octets(digest)),
        der_int(serial),
        der_gentime(gen_time),
        der_seq(der_int(1)),  # accuracy: 1 second
    ]
    if nonce is not None:
        fields.append(der_int(nonce))
    tst_info = der_seq(*fields)
    attrs = [
        der_seq(der_oid(_CONTENT_TYPE), der_set(der_oid(_TST_INFO))),
        der_seq(der_oid(_MESSAGE_DIGEST), der_set(der_octets(hashlib.sha256(tst_info).digest()))),
        der_seq(
            der_oid(_SIGNING_CERT_V2),
            der_set(der_seq(der_seq(der_seq(der_octets(hashlib.sha256(cert_der).digest()))))),
        ),
    ]
    signed_attrs = der_set(*attrs)
    signature = key.sign(signed_attrs, padding.PKCS1v15(), hashes.SHA256())
    signer_info = der_seq(
        der_int(1),
        der_seq(cert.issuer.public_bytes(), der_int(cert.serial_number)),
        _alg(_SHA256),
        der_tlv(0xA0, _set_content(signed_attrs)),
        _alg(_RSA),
        der_octets(signature),
    )
    signed_data = der_seq(
        der_int(3),
        der_set(_alg(_SHA256)),
        der_seq(der_oid(_TST_INFO), der_explicit(0, der_octets(tst_info))),
        der_tlv(0xA0, cert_der),
        der_set(signer_info),
    )
    token = der_seq(der_oid(_SIGNED_DATA), der_explicit(0, signed_data))
    return der_seq(der_seq(der_int(0)), token)


def _set_content(encoded_set: bytes) -> bytes:
    """Content octets of a DER SET (strip tag and length)."""
    length = encoded_set[1]
    if length & 0x80:
        return encoded_set[2 + (length & 0x7F) :]
    return encoded_set[2:]


class MockProvider(TimestampProvider):
    def __init__(
        self,
        kind: str = "tsa",
        *,
        clock: Callable[[], datetime] | None = None,
        offline: bool = False,
        confirm_on_upgrade: bool = False,
    ):
        if kind not in ("tsa", "btc"):
            raise ValueError("kind must be tsa or btc")
        self.kind = kind
        self.name = "mock-tsa" if kind == "tsa" else "mock-btc"
        self.clock = clock or (lambda: datetime.now(UTC).replace(microsecond=0))
        self.offline = offline
        self.confirm_on_upgrade = confirm_on_upgrade
        self.submissions: list[bytes] = []  # what was sent "over the wire" (for privacy tests)

    def _now(self) -> datetime:
        return self.clock().astimezone(UTC).replace(microsecond=0)

    def submit(self, record_id: str, manifest_bytes: bytes) -> AnchorResult:
        if self.offline:
            raise ProviderUnavailable(f"{self.name}: offline")
        if hashlib.sha256(manifest_bytes).hexdigest() != record_id:
            raise ValueError("manifest bytes do not hash to the record ID")
        digest = bytes.fromhex(record_id)
        self.submissions.append(digest)
        now = self._now()
        if self.kind == "tsa":
            nonce = int.from_bytes(hashlib.sha256(b"nonce" + digest).digest()[:8], "big")
            proof = build_mock_tsr(digest, now, nonce)
            return AnchorResult("confirmed", proof, format_utc(now), "mock TSA")
        proof = MOCK_BTC_MAGIC + json.dumps(
            {"digest": record_id, "status": "pending", "submitted": format_utc(now)}, sort_keys=True
        ).encode()
        return AnchorResult("pending", proof, None, "submitted to mock calendar")

    def upgrade(self, proof: bytes) -> AnchorResult:
        if self.kind == "tsa":
            return AnchorResult("confirmed", proof)
        if self.offline:
            raise ProviderUnavailable(f"{self.name}: offline")
        data = json.loads(proof[len(MOCK_BTC_MAGIC) :])
        if data.get("status") == "confirmed":
            return AnchorResult("confirmed", proof, data["time"])
        if not self.confirm_on_upgrade:
            return AnchorResult("pending", proof, None, "still waiting for mock confirmation")
        now = format_utc(self._now())
        digest = bytes.fromhex(data["digest"])
        data.update(
            status="confirmed",
            height=800000 + digest[0],
            time=now,
            commitment=hashlib.sha256(b"rprov-mock-btc:" + digest).hexdigest(),
        )
        return AnchorResult(
            "confirmed", MOCK_BTC_MAGIC + json.dumps(data, sort_keys=True).encode(), now, "mock confirmation"
        )

    def verify(self, record_id: str, proof: bytes) -> ProofCheck:
        if self.kind == "tsa":
            return verify_tsa_proof(record_id, proof, self.trust_roots())
        return verify_btc_proof(record_id, proof, allow_mock=True)

    def trust_roots(self) -> list[x509.Certificate]:
        return [mock_tsa_root()] if self.kind == "tsa" else []

    def bundle_certificates(self) -> dict[str, bytes]:
        if self.kind != "tsa":
            return {}
        return {
            "mock-tsa-root.pem": (MOCK_TSA_DIR / "mock-tsa-root.pem").read_bytes(),
            "mock-tsa.pem": (MOCK_TSA_DIR / "mock-tsa.pem").read_bytes(),
        }
