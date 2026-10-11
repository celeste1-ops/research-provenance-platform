"""Run the shared core verifier (provenance_core.verify) over the local database."""

from __future__ import annotations

from cryptography import x509

from provenance_core.certs import builtin_tsa_roots
from provenance_core.proofs import ProofCheck
from provenance_core.verify import STATUS_LABELS, LogReport, RecordMaterial, RecordResult, verify_log


def trust_roots(anchor_service) -> list[x509.Certificate]:
    roots = list(builtin_tsa_roots())
    provider = anchor_service.providers.get("tsa")
    if provider is not None:
        for cert in provider.trust_roots():
            if cert not in roots:
                roots.append(cert)
    return roots


def verify_database(ledger, anchor_service) -> LogReport:
    rows = ledger.records()
    files = ledger.all_record_files()
    anchors = anchor_service.rows_by_record()
    materials: dict[str, RecordMaterial] = {}
    for r in rows:
        content: dict[str, bytes] = {}
        for f in files.get(r.id, []):
            key = "body" if f.role == "body" else f"files/{f.name}"
            content[key] = ledger.blobs.get(f.sha256)
        a = anchors.get(r.id, {})
        tsa = a.get("tsa")
        btc = a.get("btc")
        materials[r.id] = RecordMaterial(
            r.id,
            r.manifest_bytes,
            r.payload_bytes,
            r.signature,
            tsa.proof_bytes if tsa else None,
            btc.proof_bytes if btc else None,
            content if r.kind == "entry" else None,
        )
    btc_provider = anchor_service.providers.get("btc")
    btc_check = None
    if btc_provider is not None:
        def btc_check(rid: str, proof: bytes | None) -> ProofCheck:
            from provenance_core.proofs import no_proof

            return btc_provider.verify(rid, proof) if proof else no_proof("btc")

    return verify_log(
        [r.id for r in rows],
        materials,
        tsa_roots=trust_roots(anchor_service),
        btc_check=btc_check,
    )


def proof_json(p: ProofCheck) -> dict:
    return {"kind": p.kind, "state": p.state, "time": p.time, "code": p.code, "detail": p.detail, "source": p.source}


def file_stamp_json(f) -> dict:
    return {"file": f.file, **proof_json(f.check)}


def record_file_stamps(ledger, anchor_service, record_id: str) -> list[dict]:
    """The earlier date stamps of a step's attached files (an inbox stamp, D-049), checked now."""
    from provenance_core.verify import STAMP_SUFFIX, file_stamps

    files = {f.name: f for f in ledger.record_files(record_id) if f.role != "body"}
    if not any(n.endswith(STAMP_SUFFIX) and n[: -len(STAMP_SUFFIX)] in files for n in files):
        return []
    content = {f"files/{n}": ledger.blobs.get(f.sha256) for n, f in files.items()}
    return [file_stamp_json(f) for f in file_stamps(content, trust_roots(anchor_service))]


def result_json(r: RecordResult) -> dict:
    ev = r.earliest_verified()
    return {
        "record_id": r.record_id,
        "seq": r.seq,
        "kind": r.kind,
        "status": r.status,
        "status_label": STATUS_LABELS[r.status],
        "failure_codes": r.failure_codes,
        "warning_codes": r.warning_codes,
        "issues": [{"code": i.code, "message": i.message, "severity": i.severity} for i in r.issues],
        "tsa": proof_json(r.tsa),
        "btc": proof_json(r.btc),
        "earliest_verified": {"time": ev[0], "from": ev[1]} if ev else None,
        "signature": "invalid" if "SIGNATURE_INVALID" in r.failure_codes else "valid",
        "file_stamps": [file_stamp_json(f) for f in r.file_stamps],
    }


def report_json(report: LogReport) -> dict:
    return {
        "ok": report.ok,
        "counts": report.counts,
        "log_issues": [{"code": i.code, "message": i.message} for i in report.log_issues],
        "records": [result_json(r) for r in report.records],
        "note": "Verification result at this moment on this computer; anyone can re-run it independently.",
    }
