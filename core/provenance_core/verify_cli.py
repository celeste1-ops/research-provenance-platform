"""Command-line front end of the verifier; becomes ``verify.py`` in every bundle.

    python3 verify.py <bundle directory or .zip> [--json] [--tsa-root PEM ...]

Exit code 0: no record failed (warnings and pending Bitcoin anchors allowed).
Exit code 1: at least one failure. Exit code 2: the bundle could not be read.
"""

from __future__ import annotations

import argparse
import json
import sys

from cryptography import x509

from .bundle import BundleError, load_bundle
from .certs import FREETSA_ROOT_SHA256, builtin_tsa_roots
from .proofs import BTC_LABEL, TSA_LABEL
from .providers.explorers import ExplorerHeaderLookup, NodeHeaderLookup
from .verify import STATUS_LABELS, LogReport, verify_log

_PROOF_WORDS = {
    ("tsa", "verified"): "verified",
    ("btc", "verified"): "confirmed",
    ("tsa", "pending"): "pending",
    ("btc", "pending"): "pending",
    ("tsa", "none"): "none",
    ("btc", "none"): "none",
    ("tsa", "invalid"): "INVALID",
    ("btc", "invalid"): "INVALID",
    ("tsa", "unchecked"): "not checked",
    ("btc", "unchecked"): "attested, block header not checked",
}


def _proof_text(p) -> str:
    label = TSA_LABEL if p.kind == "tsa" else BTC_LABEL
    word = _PROOF_WORDS.get((p.kind, p.state), p.state)
    return f"{label}: {word}" + (f" {p.time}" if p.time else "")


def report_to_dict(report: LogReport) -> dict:
    out = {
        "ok": report.ok,
        "counts": report.counts,
        "log_issues": [{"code": i.code, "message": i.message} for i in report.log_issues],
        "records": [],
    }
    for r in report.records:
        ev = r.earliest_verified()
        out["records"].append(
            {
                "id": r.record_id,
                "seq": r.seq,
                "kind": r.kind,
                "disclosure": r.disclosure,
                "status": r.status,
                "failure_codes": r.failure_codes,
                "warning_codes": r.warning_codes,
                "issues": [{"code": i.code, "severity": i.severity, "message": i.message} for i in r.issues],
                "third_party_timestamp": {"state": r.tsa.state, "time": r.tsa.time, "source": r.tsa.source},
                "bitcoin_anchor": {"state": r.btc.state, "time": r.btc.time, "source": r.btc.source},
                "earliest_verified": {"time": ev[0], "from": ev[1]} if ev else None,
            }
        )
    return out


def _print_report(report: LogReport, meta: dict) -> None:
    print(f"Evidence bundle: {meta.get('title', '(untitled)')}")
    label = meta.get("author_label")
    if label:
        print(f"Author label (self-declared): {label}")
    if meta.get("exported_local_time"):
        print(f"Exported (local clock, unverified): {meta['exported_local_time']}")
    print()
    for r in report.records:
        seq = "?" if r.seq is None else r.seq
        kind = r.kind or "?"
        line = f"#{seq:<4} {r.record_id[:16]}  {kind:<10} {r.disclosure:<9}  {STATUS_LABELS[r.status]}"
        if r.failure_codes:
            line += "  [" + ", ".join(r.failure_codes) + "]"
        if r.warning_codes:
            line += "  (" + ", ".join(r.warning_codes) + ")"
        print(line)
        print(f"       {_proof_text(r.tsa)} | {_proof_text(r.btc)}")
        ev = r.earliest_verified()
        print(f"       Earliest verified time: {ev[0]} (from {ev[1]})" if ev else "       No verified time")
        for issue in r.issues:
            print(f"         {issue.severity.upper()} {issue.code}: {issue.message}")
    for issue in report.log_issues:
        print(f"LOG {issue.code}: {issue.message}")
    c = report.counts
    print()
    print(
        f"Summary: {c['pass']} pass, {c['pass_btc_pending']} pass (Bitcoin anchor pending), "
        f"{c['warning']} warning, {c['fail']} fail"
    )
    print("Result: OK — no record failed verification." if report.ok else "Result: FAILED — see the codes above.")
    print(
        "This shows the records existed by the verified times and have not changed since, their order, "
        "and that one key signed them all. It does not prove authorship, priority, motives or correctness."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Independently verify an rprov evidence bundle.")
    parser.add_argument("bundle", help="bundle directory or .zip file")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--tsa-root",
        action="append",
        default=[],
        metavar="PEM",
        help="also trust this TSA root certificate (only after checking its fingerprint yourself)",
    )
    parser.add_argument("--allow-mock", action="store_true", help="accept mock Bitcoin anchors (testing only)")
    parser.add_argument(
        "--bitcoin-node",
        metavar="URL",
        help="check Bitcoin anchors against your own node's JSON-RPC, e.g. http://user:pass@127.0.0.1:8332",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="make no network requests; Bitcoin attestations are then reported as not checked",
    )
    args = parser.parse_args(argv)

    roots = list(builtin_tsa_roots())
    for path in args.tsa_root:
        try:
            with open(path, "rb") as fh:
                roots.append(x509.load_pem_x509_certificate(fh.read()))
        except (OSError, ValueError) as exc:
            print(f"cannot read --tsa-root {path}: {exc}", file=sys.stderr)
            return 2
    try:
        bundle = load_bundle(args.bundle)
    except BundleError as exc:
        print(f"cannot read bundle: {exc}", file=sys.stderr)
        return 2
    # Bitcoin block headers: a local node if given, otherwise at least two agreeing public
    # block explorers (only block heights are sent). Nothing is fetched with --offline.
    header_lookup = None
    if args.bitcoin_node:
        header_lookup = NodeHeaderLookup(args.bitcoin_node)
    elif not args.offline:
        header_lookup = ExplorerHeaderLookup()
    report = verify_log(
        bundle.chain_ids,
        bundle.materials,
        tsa_roots=roots,
        allow_mock=args.allow_mock,
        identity_pem=bundle.identity_pem,
        btc_header_lookup=header_lookup,
    )
    if args.json:
        print(json.dumps(report_to_dict(report), indent=2, ensure_ascii=False))
    else:
        _print_report(report, bundle.meta)
        if "TSA_CHAIN_UNTRUSTED" in report.failure_codes() and "mock-tsa-root.pem" in bundle.certs:
            print(
                "\nNote: these timestamps come from the MOCK test TSA, which nothing trusts by default. "
                "For testing only: --tsa-root certs/mock-tsa-root.pem"
            )
        print(f"\nBuilt-in trust root: FreeTSA Root CA, SHA-256 {FREETSA_ROOT_SHA256}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
