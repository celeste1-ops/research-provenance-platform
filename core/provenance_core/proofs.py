"""Checking the two kinds of time evidence, kept strictly apart (PRD §7 rule 4).

* Third-party timestamp — RFC 3161 time-stamp responses (``.tsr``), checked against
  built-in trust roots. Failure codes TSA_INVALID, TSA_CHAIN_UNTRUSTED,
  TSA_IMPRINT_MISMATCH.
* Bitcoin anchor — OpenTimestamps proofs (``.ots``) whose start digest must be the
  record ID. BTC_INVALID on failure; a proof without a Bitcoin attestation yet is
  pending, which is not a failure.

No network access happens here. Block headers, when needed, come from a lookup
function supplied by the caller.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from rfc3161_client import VerificationError, VerifierBuilder, decode_timestamp_response

from .der import DerError, der_children, der_decode_int, der_decode_oid, der_read
from .ots import OtsError, parse_ots

TSA_KIND = "tsa"
BTC_KIND = "btc"
TSA_LABEL = "Third-party timestamp"
BTC_LABEL = "Bitcoin anchor"


@dataclass
class ProofCheck:
    """Outcome of checking one time proof.

    state: verified | pending | none | invalid | unchecked
    """

    kind: str
    state: str
    time: str | None = None
    code: str | None = None
    detail: str = ""
    source: str = ""

    @property
    def verified(self) -> bool:
        return self.state == "verified" and self.time is not None


def format_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def no_proof(kind: str, detail: str = "") -> ProofCheck:
    return ProofCheck(kind, "none", detail=detail or "No timestamp yet")


# --------------------------------------------------------------------------- RFC 3161

_OID_SIGNED_DATA = "1.2.840.113549.1.7.2"
_OID_TST_INFO = "1.2.840.113549.1.9.16.1.4"
_OID_MESSAGE_DIGEST = "1.2.840.113549.1.9.4"
_OID_CONTENT_TYPE = "1.2.840.113549.1.9.3"
_OID_SHA256 = "2.16.840.1.101.3.4.2.1"
_TSA_HASHES = {
    "2.16.840.1.101.3.4.2.1": hashes.SHA256,
    "2.16.840.1.101.3.4.2.2": hashes.SHA384,
    "2.16.840.1.101.3.4.2.3": hashes.SHA512,
    "1.3.14.3.2.26": hashes.SHA1,
}
_RSA_SIG_OIDS = {
    "1.2.840.113549.1.1.1": None,  # rsaEncryption: hash given by digestAlgorithm
    "1.2.840.113549.1.1.5": hashes.SHA1,
    "1.2.840.113549.1.1.11": hashes.SHA256,
    "1.2.840.113549.1.1.12": hashes.SHA384,
    "1.2.840.113549.1.1.13": hashes.SHA512,
}
_ECDSA_SIG_OIDS = {
    "1.2.840.10045.4.3.2": hashes.SHA256,
    "1.2.840.10045.4.3.3": hashes.SHA384,
    "1.2.840.10045.4.3.4": hashes.SHA512,
}


class _TsaSignatureUnsupported(Exception):
    pass


def _tsa_signer_signature_ok(tsr: bytes) -> tuple[bool, str, x509.Certificate | None]:
    """Check the CMS signature of a time-stamp token against its own embedded signer
    certificate, independent of any trust decision.

    Returns (ok, detail, signer_cert). Raises _TsaSignatureUnsupported for algorithms
    this pre-check does not implement (the full check still runs afterwards).
    """
    _, s, e = der_read(tsr)
    resp = der_children(tsr, s, e)
    if len(resp) < 2:
        return False, "response has no time-stamp token", None
    _, _, cs, ce = resp[1]
    ci = der_children(tsr, cs, ce)
    if len(ci) != 2 or der_decode_oid(tsr[ci[0][2] : ci[0][3]]) != _OID_SIGNED_DATA:
        return False, "token is not CMS SignedData", None
    _, _, xs, xe = ci[1]
    (sd_tag, _, sds, sde), *_ = der_children(tsr, xs, xe)
    sd = der_children(tsr, sds, sde)
    encap = der_children(tsr, sd[2][2], sd[2][3])
    if der_decode_oid(tsr[encap[0][2] : encap[0][3]]) != _OID_TST_INFO:
        return False, "token does not contain TSTInfo", None
    (_, _, os_, oe), = der_children(tsr, encap[1][2], encap[1][3])
    e_content = tsr[os_:oe]
    certs: list[x509.Certificate] = []
    signer_infos = None
    for tag, _ts, cs2, ce2 in sd[3:]:
        if tag == 0xA0:
            for _, cts, _, cte in der_children(tsr, cs2, ce2):
                try:
                    certs.append(x509.load_der_x509_certificate(tsr[cts:cte]))
                except ValueError:
                    pass
        elif tag == 0x31:
            signer_infos = der_children(tsr, cs2, ce2)
    if not signer_infos or len(signer_infos) != 1:
        return False, "expected exactly one SignerInfo", None
    si = der_children(tsr, signer_infos[0][2], signer_infos[0][3])
    sid_tag, sid_ts, sid_cs, sid_ce = si[1]
    signer = None
    if sid_tag == 0x30:
        (_, iss_ts, _, iss_te), (_, _, ser_cs, ser_ce) = der_children(tsr, sid_cs, sid_ce)
        issuer_der = tsr[iss_ts:iss_te]
        serial = der_decode_int(tsr[ser_cs:ser_ce])
        for c in certs:
            if c.serial_number == serial and c.issuer.public_bytes() == issuer_der:
                signer = c
                break
    else:
        ski = tsr[sid_cs:sid_ce]
        for c in certs:
            try:
                if c.extensions.get_extension_for_class(x509.SubjectKeyIdentifier).value.digest == ski:
                    signer = c
                    break
            except x509.ExtensionNotFound:
                continue
    if signer is None:
        return False, "signer certificate is not embedded in the token", None
    digest_alg = der_children(tsr, si[2][2], si[2][3])
    digest_oid = der_decode_oid(tsr[digest_alg[0][2] : digest_alg[0][3]])
    idx = 3
    signed_attrs = None
    if si[idx][0] == 0xA0:
        signed_attrs = si[idx]
        idx += 1
    sig_alg = der_children(tsr, si[idx][2], si[idx][3])
    sig_oid = der_decode_oid(tsr[sig_alg[0][2] : sig_alg[0][3]])
    signature = tsr[si[idx + 1][2] : si[idx + 1][3]]
    hash_cls = _TSA_HASHES.get(digest_oid)
    if hash_cls is None:
        raise _TsaSignatureUnsupported(f"digest algorithm {digest_oid}")
    if signed_attrs is None:
        return False, "token has no signed attributes", signer
    attrs = {}
    for _, _, acs, ace in der_children(tsr, signed_attrs[2], signed_attrs[3]):
        a = der_children(tsr, acs, ace)
        attrs[der_decode_oid(tsr[a[0][2] : a[0][3]])] = (tsr, a[1][2], a[1][3])
    if _OID_MESSAGE_DIGEST not in attrs:
        return False, "token has no message-digest attribute", signer
    buf, ms, me = attrs[_OID_MESSAGE_DIGEST]
    (_, _, mds, mde), = der_children(buf, ms, me)
    h = hashes.Hash(hash_cls())
    h.update(e_content)
    if h.finalize() != buf[mds:mde]:
        return False, "message-digest attribute does not match the TSTInfo", signer
    signed_bytes = b"\x31" + tsr[signed_attrs[1] + 1 : signed_attrs[3]]
    key = signer.public_key()
    try:
        if sig_oid in _RSA_SIG_OIDS and isinstance(key, rsa.RSAPublicKey):
            sig_hash = _RSA_SIG_OIDS[sig_oid] or hash_cls
            key.verify(signature, signed_bytes, padding.PKCS1v15(), sig_hash())
        elif sig_oid in _ECDSA_SIG_OIDS and isinstance(key, ec.EllipticCurvePublicKey):
            key.verify(signature, signed_bytes, ec.ECDSA(_ECDSA_SIG_OIDS[sig_oid]()))
        else:
            raise _TsaSignatureUnsupported(f"signature algorithm {sig_oid}")
    except InvalidSignature:
        return False, "the TSA signature does not verify", signer
    return True, "signature verifies against the embedded TSA certificate", signer


def _cert_common_name(cert: x509.Certificate | None) -> str:
    if cert is None:
        return ""
    names = cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)
    return str(names[0].value) if names else cert.subject.rfc4514_string()


def verify_tsa_proof(record_id: str, tsr: bytes | None, roots: list[x509.Certificate]) -> ProofCheck:
    """V4: signature valid, chain to a built-in root, imprint == record ID."""
    if not tsr:
        return no_proof(TSA_KIND)
    try:
        resp = decode_timestamp_response(tsr)
        info = resp.tst_info
        imprint = info.message_imprint
        algo = imprint.hash_algorithm.dotted_string
        message = bytes(imprint.message)
        gen_time = info.gen_time
    except Exception as exc:  # noqa: BLE001 - any parse failure is an invalid proof
        return ProofCheck(TSA_KIND, "invalid", code="TSA_INVALID", detail=f"cannot parse time-stamp response: {exc}")
    if resp.status != 0:
        return ProofCheck(TSA_KIND, "invalid", code="TSA_INVALID", detail=f"TSA status {resp.status} is not granted")
    if algo != _OID_SHA256 or message != bytes.fromhex(record_id):
        return ProofCheck(
            TSA_KIND,
            "invalid",
            code="TSA_IMPRINT_MISMATCH",
            detail="the time-stamp is for a different digest than this record ID",
        )
    signer = None
    try:
        ok, detail, signer = _tsa_signer_signature_ok(tsr)
        if not ok:
            return ProofCheck(TSA_KIND, "invalid", code="TSA_INVALID", detail=detail, source=_cert_common_name(signer))
        presigned = True
    except _TsaSignatureUnsupported:
        presigned = False
    except (DerError, ValueError, IndexError) as exc:
        return ProofCheck(TSA_KIND, "invalid", code="TSA_INVALID", detail=f"malformed token: {exc}")
    if not roots:
        return ProofCheck(TSA_KIND, "invalid", code="TSA_CHAIN_UNTRUSTED", detail="no trusted TSA root configured")
    builder = VerifierBuilder()
    for root in roots:
        builder = builder.add_root_certificate(root)
    try:
        builder.build().verify(resp, message)
    except VerificationError as exc:
        text = str(exc)
        if presigned or "certificate verify error" in text or "issuer" in text:
            code = "TSA_CHAIN_UNTRUSTED"
        else:
            code = "TSA_INVALID"
        return ProofCheck(TSA_KIND, "invalid", code=code, detail=text, source=_cert_common_name(signer))
    return ProofCheck(
        TSA_KIND,
        "verified",
        time=format_utc(gen_time),
        detail="RFC 3161 signature valid; chains to a trusted root; digest equals the record ID",
        source=_cert_common_name(signer),
    )


def tsa_embedded_certificates(tsr: bytes) -> list[x509.Certificate]:
    """Certificates embedded in a time-stamp token (for exporting certs/)."""
    try:
        resp = decode_timestamp_response(tsr)
        return [x509.load_der_x509_certificate(bytes(c)) for c in resp.signed_data.certificates]
    except Exception:  # noqa: BLE001
        return []


# --------------------------------------------------------------------------- Bitcoin anchor

MOCK_BTC_MAGIC = b"RPROV-MOCK-BTC/1\n"

# (height) -> (merkle_root_hex as shown by block explorers, block_time_unix) or None.
HeaderLookup = Callable[[int], tuple[str, int] | None]


def verify_btc_proof(
    record_id: str,
    proof: bytes | None,
    *,
    header_lookup: HeaderLookup | None = None,
    allow_mock: bool = False,
) -> ProofCheck:
    """V5: the proof must start from the record ID; Bitcoin attestations are checked
    against block headers from a node or block explorers when a lookup is given."""
    if not proof:
        return no_proof(BTC_KIND)
    if proof.startswith(MOCK_BTC_MAGIC):
        return _verify_mock_btc(record_id, proof, allow_mock)
    try:
        ots = parse_ots(proof)
    except OtsError as exc:
        return ProofCheck(BTC_KIND, "invalid", code="BTC_INVALID", detail=f"cannot parse .ots proof: {exc}")
    if ots.file_hash_op != "sha256" or ots.file_digest != bytes.fromhex(record_id):
        return ProofCheck(BTC_KIND, "invalid", code="BTC_INVALID", detail="proof does not start from the manifest hash")
    if not ots.bitcoin:
        uris = ", ".join(sorted({a.uri for a in ots.pending})) or "no calendar"
        return ProofCheck(BTC_KIND, "pending", code="BTC_PENDING", detail=f"waiting for Bitcoin confirmation ({uris})")
    att = min(ots.bitcoin, key=lambda a: a.height)
    if header_lookup is None:
        return ProofCheck(
            BTC_KIND,
            "unchecked",
            detail=f"Bitcoin attestation at block {att.height}; block header not checked "
            "(run with a Bitcoin node or block explorers to confirm)",
            source=f"Bitcoin block {att.height}",
        )
    header = header_lookup(att.height)
    if header is None:
        return ProofCheck(
            BTC_KIND,
            "unchecked",
            detail=f"Bitcoin attestation at block {att.height}; could not fetch the block header",
            source=f"Bitcoin block {att.height}",
        )
    merkle_root_hex, block_time = header
    if att.merkle_root_hex != merkle_root_hex.lower():
        return ProofCheck(
            BTC_KIND,
            "invalid",
            code="BTC_INVALID",
            detail=f"commitment does not match the merkle root of block {att.height}",
        )
    return ProofCheck(
        BTC_KIND,
        "verified",
        time=format_utc(datetime.fromtimestamp(block_time, UTC)),
        detail=f"commitment matches the merkle root of Bitcoin block {att.height}",
        source=f"Bitcoin block {att.height}",
    )


def _verify_mock_btc(record_id: str, proof: bytes, allow_mock: bool) -> ProofCheck:
    try:
        data = json.loads(proof[len(MOCK_BTC_MAGIC) :])
    except ValueError:
        return ProofCheck(BTC_KIND, "invalid", code="BTC_INVALID", detail="malformed mock proof")
    if data.get("digest") != record_id:
        return ProofCheck(BTC_KIND, "invalid", code="BTC_INVALID", detail="proof does not start from the manifest hash")
    if data.get("status") != "confirmed":
        return ProofCheck(BTC_KIND, "pending", code="BTC_PENDING", detail="waiting for Bitcoin confirmation (mock calendar)")
    if not allow_mock:
        return ProofCheck(
            BTC_KIND, "invalid", code="BTC_INVALID", detail="mock Bitcoin anchors are only accepted in test mode"
        )
    expected = hashlib.sha256(b"rprov-mock-btc:" + bytes.fromhex(record_id)).hexdigest()
    if data.get("commitment") != expected:
        return ProofCheck(BTC_KIND, "invalid", code="BTC_INVALID", detail="mock commitment mismatch")
    return ProofCheck(
        BTC_KIND,
        "verified",
        time=data["time"],
        detail="MOCK Bitcoin anchor (test mode only)",
        source=f"mock block {data.get('height')}",
    )
