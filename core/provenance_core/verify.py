"""The one and only verification logic (PRD §10), shared by the app and verify.py.

Checks per record: V1 content, V2 manifest & payload, V3 signature, V4 third-party
timestamp, V5 Bitcoin anchor, V6 log chain, V7 references. V8/V9: the two kinds of
time are always reported separately; author statements and claimed dates never
take part in any time result.

Each record ends up as exactly one of: pass, pass_btc_pending, warning, fail.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .chain import check_chain
from .jcs import JcsError, canonicalize, parse_json_strict
from .proofs import (
    BTC_KIND,
    BTC_LABEL,
    TSA_KIND,
    TSA_LABEL,
    HeaderLookup,
    ProofCheck,
    no_proof,
    verify_btc_proof,
    verify_tsa_proof,
)
from .records import REF_TARGET_KINDS, payload_refs, sha256_hex, validate_manifest, validate_payload
from .signing import public_key_from_hex, public_key_pem, verify_record_signature

FAILURE_CODES = (
    "CONTENT_MISMATCH",
    "MANIFEST_HASH_MISMATCH",
    "PAYLOAD_HASH_MISMATCH",
    "NON_CANONICAL",
    "SCHEMA_INVALID",
    "SIGNATURE_INVALID",
    "TSA_INVALID",
    "TSA_CHAIN_UNTRUSTED",
    "TSA_IMPRINT_MISMATCH",
    "BTC_INVALID",
    "LOG_GAP",
    "LOG_PREV_MISMATCH",
    "REF_MISSING",
    "REF_NOT_EARLIER",
)
WARNING_CODES = ("REF_TIME_LATER", "TIME_SKEW", "NO_VERIFIED_TIME")

STATUS_PASS = "pass"
STATUS_PASS_BTC_PENDING = "pass_btc_pending"
STATUS_WARNING = "warning"
STATUS_FAIL = "fail"
STATUS_LABELS = {
    STATUS_PASS: "Pass",
    STATUS_PASS_BTC_PENDING: "Pass (Bitcoin anchor pending)",
    STATUS_WARNING: "Warning",
    STATUS_FAIL: "Fail",
}
SKEW_LIMIT_SECONDS = 24 * 3600


@dataclass
class Issue:
    code: str
    message: str
    severity: str = "fail"  # fail | warn


@dataclass
class RecordMaterial:
    """Everything known about one record, as read from a bundle or the database.

    ``content`` maps "body" and "files/<name>" to bytes; it is present only for
    fully disclosed records.
    """

    record_id: str
    manifest_bytes: bytes | None
    payload_bytes: bytes | None = None
    signature: bytes | None = None
    tsa_proof: bytes | None = None
    btc_proof: bytes | None = None
    content: dict[str, bytes] | None = None


@dataclass
class RecordResult:
    record_id: str
    seq: int | None = None
    kind: str | None = None
    disclosure: str = "existence"  # full | structure | existence
    manifest: dict | None = None
    payload: dict | None = None
    issues: list[Issue] = field(default_factory=list)
    tsa: ProofCheck = field(default_factory=lambda: no_proof(TSA_KIND))
    btc: ProofCheck = field(default_factory=lambda: no_proof(BTC_KIND))
    status: str = STATUS_PASS

    @property
    def failure_codes(self) -> list[str]:
        return sorted({i.code for i in self.issues if i.severity == "fail"})

    @property
    def warning_codes(self) -> list[str]:
        return sorted({i.code for i in self.issues if i.severity == "warn"})

    def earliest_verified(self) -> tuple[str, str] | None:
        """(time, label of the proof it came from) — never a merged 'authoritative' time."""
        candidates = [(p.time, label) for p, label in ((self.tsa, TSA_LABEL), (self.btc, BTC_LABEL)) if p.verified]
        return min(candidates) if candidates else None  # type: ignore[return-value]


@dataclass
class LogReport:
    records: list[RecordResult]
    log_issues: list[Issue]
    public_key_hex: str | None

    @property
    def counts(self) -> dict[str, int]:
        out = {s: 0 for s in STATUS_LABELS}
        for r in self.records:
            out[r.status] += 1
        return out

    @property
    def ok(self) -> bool:
        return not any(i.severity == "fail" for i in self.log_issues) and all(
            r.status != STATUS_FAIL for r in self.records
        )

    def failure_codes(self) -> set[str]:
        codes = {i.code for i in self.log_issues if i.severity == "fail"}
        for r in self.records:
            codes.update(r.failure_codes)
        return codes

    def by_id(self) -> dict[str, RecordResult]:
        return {r.record_id: r for r in self.records}


def _parse_canonical(data: bytes, what: str, result: RecordResult) -> dict | None:
    try:
        obj = parse_json_strict(data)
    except JcsError as exc:
        result.issues.append(Issue("SCHEMA_INVALID", f"{what} is not valid record JSON: {exc}"))
        return None
    try:
        canonical = canonicalize(obj)
    except JcsError as exc:
        result.issues.append(Issue("SCHEMA_INVALID", f"{what}: {exc}"))
        return None
    if canonical != data:
        result.issues.append(Issue("NON_CANONICAL", f"{what} bytes are not in RFC 8785 canonical form"))
    return obj if isinstance(obj, dict) else None


def _check_content(m: RecordMaterial, payload: dict, result: RecordResult) -> None:
    """V1: disclosed body and attachments hash to what the payload says."""
    content = payload.get("content") or {}
    expected: dict[str, dict] = {}
    if content.get("body"):
        expected["body"] = content["body"]
    for f in content.get("files") or []:
        expected[f"files/{f['name']}"] = f
    provided = m.content or {}
    for key, desc in expected.items():
        data = provided.get(key)
        if data is None:
            result.issues.append(Issue("CONTENT_MISMATCH", f"{key} is missing from a fully disclosed record"))
        elif sha256_hex(data) != desc["sha256"] or len(data) != desc["size"]:
            result.issues.append(Issue("CONTENT_MISMATCH", f"{key} does not match its SHA-256 in the payload"))
    for key in provided:
        if key not in expected:
            result.issues.append(Issue("CONTENT_MISMATCH", f"{key} is not listed in the payload"))


def _seconds_between(a: str, b: str) -> float:
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return abs((datetime.strptime(a, fmt) - datetime.strptime(b, fmt)).total_seconds())


def verify_log(
    chain_ids: list[str],
    materials: dict[str, RecordMaterial],
    *,
    tsa_roots: list[x509.Certificate],
    btc_header_lookup: HeaderLookup | None = None,
    allow_mock: bool = False,
    identity_pem: bytes | None = None,
    btc_check: Callable[[str, bytes | None], ProofCheck] | None = None,
) -> LogReport:
    """Verify a whole log (or the prefix of it contained in a bundle)."""
    log_issues: list[Issue] = []
    results: dict[str, RecordResult] = {}
    manifests: dict[str, dict | None] = {}

    # --- V2: manifest and payload, per record
    for rid in chain_ids:
        m = materials.get(rid) or RecordMaterial(rid, None)
        res = RecordResult(rid)
        results[rid] = res
        if m.manifest_bytes is None:
            manifests[rid] = None
            continue
        if sha256_hex(m.manifest_bytes) != rid:
            res.issues.append(Issue("MANIFEST_HASH_MISMATCH", "SHA-256 of the manifest is not the record ID"))
        manifest = _parse_canonical(m.manifest_bytes, "manifest", res)
        if manifest is not None:
            errs = validate_manifest(manifest)
            if errs:
                res.issues.append(Issue("SCHEMA_INVALID", "manifest: " + "; ".join(errs)))
                manifest = None
        manifests[rid] = manifest
        if manifest is None:
            continue
        res.manifest = manifest
        res.seq = manifest["seq"]
        res.kind = manifest["kind"]
        if m.payload_bytes is not None:
            res.disclosure = "full" if m.content is not None else "structure"
            if sha256_hex(m.payload_bytes) != manifest["payload_sha256"]:
                res.issues.append(Issue("PAYLOAD_HASH_MISMATCH", "SHA-256 of the payload differs from the manifest"))
            payload = _parse_canonical(m.payload_bytes, "payload", res)
            if payload is not None:
                errs = validate_payload(manifest["kind"], payload)
                if errs:
                    res.issues.append(Issue("SCHEMA_INVALID", "payload: " + "; ".join(errs)))
                else:
                    res.payload = payload
            if res.payload is not None and m.content is not None and manifest["kind"] == "entry":
                _check_content(m, res.payload, res)  # V1
        elif m.content is not None:
            res.issues.append(Issue("CONTENT_MISMATCH", "content is present but the payload is not"))

    # --- the signing key comes from the genesis record (seq 0)
    pub: Ed25519PublicKey | None = None
    pub_hex: str | None = None
    genesis = next((r for r in results.values() if r.seq == 0 and r.kind == "genesis"), None)
    if genesis is None or genesis.payload is None:
        log_issues.append(Issue("SIGNATURE_INVALID", "the genesis record (seq 0) and its public key are not available"))
    else:
        pub_hex = genesis.payload["public_key"]
        try:
            pub = public_key_from_hex(pub_hex)
        except ValueError:
            log_issues.append(Issue("SIGNATURE_INVALID", "the genesis public key is not a valid Ed25519 key"))
        if pub is not None and identity_pem is not None and identity_pem.strip() != public_key_pem(pub).strip():
            log_issues.append(Issue("SIGNATURE_INVALID", "identity/public_key.pem does not match the genesis record"))

    # --- V3, V4, V5 per record
    for rid in chain_ids:
        res = results[rid]
        m = materials.get(rid)
        if m is None or m.manifest_bytes is None:
            continue
        if pub is not None and not verify_record_signature(pub, rid, m.signature):
            res.issues.append(Issue("SIGNATURE_INVALID", "Ed25519 signature over the record ID does not verify"))
        res.tsa = verify_tsa_proof(rid, m.tsa_proof, tsa_roots)
        if btc_check is not None:
            res.btc = btc_check(rid, m.btc_proof)
        else:
            res.btc = verify_btc_proof(rid, m.btc_proof, header_lookup=btc_header_lookup, allow_mock=allow_mock)
        for proof in (res.tsa, res.btc):
            if proof.state == "invalid" and proof.code:
                res.issues.append(Issue(proof.code, f"{proof.detail}"))

    # --- V6: the chain
    for ci in check_chain(chain_ids, manifests):
        if ci.record_id is not None and ci.record_id in results:
            results[ci.record_id].issues.append(Issue(ci.code, ci.message))
        else:
            log_issues.append(Issue(ci.code, ci.message))

    # --- V7: references point at earlier records in the bundle
    seq_of = {rid: r.seq for rid, r in results.items() if r.seq is not None}
    kind_of = {rid: r.kind for rid, r in results.items() if r.kind is not None}
    for rid in chain_ids:
        res = results[rid]
        if res.payload is None or res.kind is None:
            continue
        for fld, ref in payload_refs(res.kind, res.payload):
            if ref not in seq_of:
                res.issues.append(Issue("REF_MISSING", f"{fld} points at {ref[:12]}…, which is not in the log"))
                continue
            if seq_of[ref] >= (res.seq or 0):
                res.issues.append(Issue("REF_NOT_EARLIER", f"{fld} points at a record that is not earlier"))
                continue
            allowed = REF_TARGET_KINDS.get((res.kind, fld))
            if allowed is not None and kind_of.get(ref) not in allowed:
                res.issues.append(Issue("SCHEMA_INVALID", f"{fld} must point at an entry, not a {kind_of.get(ref)}"))
            # Warning: the referenced record's verified time is later than this one's.
            mine, theirs = res.earliest_verified(), results[ref].earliest_verified()
            if mine and theirs and theirs[0] > mine[0]:
                res.issues.append(
                    Issue(
                        "REF_TIME_LATER",
                        f"{fld} points at a record whose verified time ({theirs[0]}) is later than this "
                        f"record's ({mine[0]}); its timestamp may have been retried later",
                        "warn",
                    )
                )

    # --- warnings and final status
    for rid in chain_ids:
        res = results[rid]
        if res.manifest is not None:
            if res.tsa.verified and res.btc.verified and _seconds_between(res.tsa.time, res.btc.time) > SKEW_LIMIT_SECONDS:
                res.issues.append(
                    Issue(
                        "TIME_SKEW",
                        "the third-party timestamp and the Bitcoin anchor differ by more than 24 hours "
                        "(normal if the Bitcoin anchor was added later)",
                        "warn",
                    )
                )
            if not res.tsa.verified and not res.btc.verified and not res.failure_codes:
                res.issues.append(Issue("NO_VERIFIED_TIME", "no verified timestamp for this record yet", "warn"))
        if res.failure_codes:
            res.status = STATUS_FAIL
        elif res.warning_codes:
            res.status = STATUS_WARNING
        elif res.btc.state == "pending":
            res.status = STATUS_PASS_BTC_PENDING
        else:
            res.status = STATUS_PASS
    return LogReport([results[rid] for rid in chain_ids], log_issues, pub_hex)
