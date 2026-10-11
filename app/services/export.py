"""Evidence bundle export (PRD §12): three disclosure levels, preview, report.html,
VERIFY.md and the generated verify.py."""

from __future__ import annotations

import importlib.util
import io
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization

from app.i18n import tr
from app.report.render import render_report, render_verify_md
from app.services.ledger import LedgerError
from app.services.verification import trust_roots
from provenance_core import bundle as B
from provenance_core.certs import BUILTIN_TSA_ROOTS, digicert_bundle_files, freetsa_bundle_files
from provenance_core.jcs import parse_json_strict
from provenance_core.proofs import tsa_embedded_certificates
from provenance_core.providers.mock import MOCK_TSA_DIR, mock_tsa_root
from provenance_core.signing import public_key_from_hex, public_key_pem
from provenance_core.verify import RecordMaterial, verify_log

ROOT = Path(__file__).resolve().parent.parent.parent

HASH_WARNING = (
    "“Structure only” discloses the SHA-256 hashes of the body and attachments. Content that others "
    "already have or can easily guess (short sentences, published paragraphs, files other people also hold) "
    "can be confirmed by comparing hashes."
)


@lru_cache(maxsize=1)
def verify_py_source() -> str:
    # The installers ship verify.py built at packaging time: the core sources it is
    # assembled from are not on disk there (D-044).
    prebuilt = ROOT / "prebuilt" / "verify.py"
    if prebuilt.is_file():
        return prebuilt.read_text(encoding="utf-8")
    spec = importlib.util.spec_from_file_location("rprov_build_verify", ROOT / "tools" / "build_verify.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.build_verify_source()


@dataclass
class Plan:
    title: str
    levels: dict[str, str]  # every record in the chain prefix → disclosure level
    chain: list  # RecordRow objects, seq 0..max
    max_seq: int


def plan_export(ledger, title: str, levels: dict[str, str] | None, default: str = "existence") -> Plan:
    if default not in B.DISCLOSURE_LEVELS:
        raise LedgerError(f"unknown disclosure level {default!r}")
    rows = ledger.records()
    if not rows:
        raise LedgerError("nothing to export yet")
    by_id = {r.id: r for r in rows}
    chosen: dict[str, str] = {}
    for rid, level in (levels or {}).items():
        if rid not in by_id:
            raise LedgerError(f"unknown record {rid[:12]}…")
        if level not in B.DISCLOSURE_LEVELS:
            raise LedgerError(f"unknown disclosure level {level!r}")
        chosen[rid] = level
    if default != "existence":
        max_seq = rows[-1].seq
    else:
        disclosed = [by_id[r].seq for r, lvl in chosen.items() if lvl != "existence"]
        explicit = [by_id[r].seq for r in chosen]
        max_seq = max(disclosed or explicit or [0])
    chain = [r for r in rows if r.seq <= max_seq]
    final: dict[str, str] = {}
    for r in chain:
        level = chosen.get(r.id, default)
        if r.kind != "entry" and level == "full":
            level = "structure"  # only entries carry content
        if r.kind == "genesis" and level == "existence":
            level = "structure"  # the public key must be readable (D-007)
        final[r.id] = level
    title = (title or "").strip() or "evidence"
    return Plan(title, final, chain, max_seq)


def preview(ledger, plan: Plan) -> dict:
    items = []
    files = ledger.all_record_files()
    for r in plan.chain:
        payload = parse_json_strict(r.payload_bytes)
        level = plan.levels[r.id]
        item = {"id": r.id, "seq": r.seq, "kind": r.kind, "disclosure": level}
        if level == "existence":
            item["visible"] = [tr("record #{seq} existed by its verified time (kind: {kind})", seq=r.seq,
                                  kind=tr(r.kind))]
        else:
            vis = []
            if r.kind == "entry":
                vis += [tr("type: {type}", type=tr(payload["node_type"])), tr("title: {title}", title=payload["title"]),
                        tr("project name: {name}", name=payload["project"]["title"])]
                if payload["relations"]:
                    vis.append(tr("{n} relation(s)", n=len(payload["relations"])))
                if payload["author_statement"]:
                    vis.append(tr("author statement: {text}", text=payload["author_statement"]))
                if payload["import"]:
                    vis.append(tr("claimed date: {date}", date=payload["import"]["claimed_date"]))
                if payload["external"]:
                    vis.append(tr("external reference: {ref}",
                                  ref=json.dumps(payload["external"], ensure_ascii=False)))
                names = [f.name for f in files.get(r.id, [])]
                if level == "full":
                    vis.append(tr("full content: {names}", names=", ".join(names) if names else tr("(none)")))
                elif names:
                    vis.append(tr("SHA-256 hashes (not content) of: {names}", names=", ".join(names)))
            elif r.kind == "genesis":
                vis += [tr("author label: {label}", label=payload["author_label"]),
                        tr("signing public key (always included)")]
            else:
                text = payload.get("text") or payload.get("statement") or payload.get("reason")
                kind = tr(r.kind)
                vis.append(tr("{kind} record: {text}", kind=kind, text=text) if text
                           else tr("{kind} record", kind=kind))
            item["visible"] = vis
        items.append(item)
    total = len(plan.chain)
    return {
        "title": plan.title,
        "records": items,
        "warnings": [
            tr(HASH_WARNING),
            tr("chain.json shows that this installation has {total} record(s) up to the highest record in the "
               "bundle (seq {max_seq}), including the ones you do not disclose.", total=total, max_seq=plan.max_seq),
        ],
        "counts": {lvl: sum(1 for v in plan.levels.values() if v == lvl) for lvl in B.DISCLOSURE_LEVELS},
    }


def _materials(ledger, anchor_rows, plan: Plan) -> tuple[dict[str, RecordMaterial], dict[str, dict[str, bytes]]]:
    files = ledger.all_record_files()
    mats: dict[str, RecordMaterial] = {}
    contents: dict[str, dict[str, bytes]] = {}
    for r in plan.chain:
        level = plan.levels[r.id]
        a = anchor_rows.get(r.id, {})
        content = None
        if level == "full":
            content = {}
            for f in files.get(r.id, []):
                key = "body" if f.role == "body" else f"files/{f.name}"
                content[key] = ledger.blobs.get(f.sha256)
            contents[r.id] = content
        mats[r.id] = RecordMaterial(
            r.id,
            r.manifest_bytes,
            r.payload_bytes if level != "existence" else None,
            r.signature,
            a["tsa"].proof_bytes if a.get("tsa") else None,
            a["btc"].proof_bytes if a.get("btc") else None,
            content,
        )
    return mats, contents


def signer_chain_file(embedded: list[x509.Certificate]) -> str:
    """Which certs/ file the signing certificates of one token go to (D-045): DigiCert's
    chain is issued by DigiCert; everything else is FreeTSA's."""
    for cert in embedded:
        orgs = cert.issuer.get_attributes_for_oid(x509.NameOID.ORGANIZATION_NAME)
        if any("digicert" in str(o.value).lower() for o in orgs):
            return "digicert-tsa-chain.pem"
    return "freetsa-tsa.crt"


def _cert_files(mats: dict[str, RecordMaterial], anchor_service) -> dict[str, bytes]:
    certs = dict(freetsa_bundle_files())
    certs.update(digicert_bundle_files())
    signers: dict[str, list[x509.Certificate]] = {"freetsa-tsa.crt": [], "digicert-tsa-chain.pem": []}
    uses_mock = False
    mock_root = mock_tsa_root()
    for m in mats.values():
        if not m.tsa_proof:
            continue
        embedded = tsa_embedded_certificates(m.tsa_proof)
        group = signer_chain_file(embedded)
        for cert in embedded:
            if cert.issuer == mock_root.subject:
                uses_mock = True
            elif cert not in signers[group]:
                signers[group].append(cert)
    # The certificates that actually signed, for `openssl ts -verify -untrusted` (they are also
    # embedded in every .tsr). Untrusted on purpose: only the roots are trust anchors.
    for name, found in signers.items():
        if not found:
            continue
        pem = certs[name].rstrip(b"\n") + b"\n" if name in certs else b""
        for cert in found:
            block = cert.public_bytes(serialization.Encoding.PEM)
            if block not in pem:
                pem += block
        certs[name] = pem
    if uses_mock:
        certs["mock-tsa-root.pem"] = (MOCK_TSA_DIR / "mock-tsa-root.pem").read_bytes()
        certs["mock-tsa.pem"] = (MOCK_TSA_DIR / "mock-tsa.pem").read_bytes()
    provider = anchor_service.providers.get("tsa")
    if provider is not None:
        for name, data in provider.bundle_certificates().items():
            certs.setdefault(name, data)
    return certs


def build_bundle_files(ledger, anchor_service, plan: Plan, *, now: datetime | None = None) -> dict[str, bytes]:
    now = now or datetime.now(UTC)
    exported_local = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    anchor_rows = anchor_service.rows_by_record()
    mats, contents = _materials(ledger, anchor_rows, plan)
    files: dict[str, bytes] = {}
    for r in plan.chain:
        m = mats[r.id]
        files[B.manifest_path(r.id)] = m.manifest_bytes
        files[B.signature_path(r.id)] = m.signature
        if m.tsa_proof:
            files[B.tsr_path(r.id)] = m.tsa_proof
        if m.btc_proof:
            files[B.ots_path(r.id)] = m.btc_proof
        if m.payload_bytes is not None:
            files[B.payload_path(r.id)] = m.payload_bytes
        for key, data in contents.get(r.id, {}).items():
            if key == "body":
                files[B.body_path(r.id)] = data
            else:
                files[B.file_path(r.id, key.split("/", 1)[1])] = data
    genesis = parse_json_strict(plan.chain[0].payload_bytes)
    files["identity/public_key.pem"] = public_key_pem(public_key_from_hex(genesis["public_key"]))
    certs = _cert_files(mats, anchor_service)
    for name, data in certs.items():
        files[f"certs/{name}"] = data
    chain_ids = [r.id for r in plan.chain]
    files["chain.json"] = (
        json.dumps({"format": B.BUNDLE_FORMAT, "installation": ledger.installation, "ids": chain_ids}, indent=2) + "\n"
    ).encode()
    meta = {
        "format": B.BUNDLE_FORMAT,
        "title": plan.title,
        "author_label": genesis["author_label"],
        "author_label_note": "self-declared",
        "installation": ledger.installation,
        "exported_local_time": exported_local,
        "exported_local_time_note": "local clock of the exporting computer, unverified",
        "highest_seq": plan.max_seq,
        "records": [
            {"id": r.id, "seq": r.seq, "kind": r.kind, "disclosure": plan.levels[r.id]} for r in plan.chain
        ],
        "trusted_tsa_roots": {name: sha for name, _label, sha in BUILTIN_TSA_ROOTS},
        "note": "This index is not signed; verify.py re-derives everything from manifests, payloads, "
        "signatures and proofs.",
    }
    files["bundle.json"] = (json.dumps(meta, indent=2, ensure_ascii=False) + "\n").encode()

    roots = trust_roots(anchor_service)
    report = verify_log(chain_ids, mats, tsa_roots=roots, identity_pem=files["identity/public_key.pem"])
    root_names = []
    for root in roots:
        fp = root.fingerprint(hashes.SHA256()).hex()
        cn = root.subject.rfc4514_string()
        root_names.append({"name": cn, "sha256": fp, "mock": "MOCK" in cn})
    files["report.html"] = render_report(plan=plan, meta=meta, mats=mats, contents=contents, report=report,
                                         trust=root_names).encode("utf-8")
    files["VERIFY.md"] = render_verify_md(plan=plan, meta=meta, mats=mats, certs=certs,
                                          uses_mock="mock-tsa-root.pem" in certs).encode("utf-8")
    files["verify.py"] = verify_py_source().encode("utf-8")
    return files


def bundle_filename(title: str, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", title).strip("-")[:60] or "evidence"
    return f"provenance-{slug}-{now.strftime('%Y-%m-%d')}.zip"


def write_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if name == "verify.py" else 0o644) << 16
            zf.writestr(info, files[name])
    return buf.getvalue()


def write_dir(files: dict[str, bytes], target: Path) -> None:
    for name, data in files.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if name == "verify.py":
            path.chmod(0o755)
