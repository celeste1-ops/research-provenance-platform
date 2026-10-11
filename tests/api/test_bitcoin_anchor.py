"""P1: Bitcoin anchor via OpenTimestamps (no network: fake calendar + fake headers)."""

from __future__ import annotations

import hashlib
import json

import pytest

from provenance_core.ots import parse_ots
from provenance_core.providers.base import ProviderRejected, ProviderUnavailable
from provenance_core.providers.explorers import ExplorerHeaderLookup, NodeHeaderLookup
from provenance_core.providers.ots import OtsProvider
from tests.conftest import Api, make_ctx
from tests.fake_calendar import POOLS, FakeCalendar


def _provider(cal: FakeCalendar, lookup=None):
    return OtsProvider(POOLS, transport=cal.transport, header_lookup=lookup or cal.header_lookup)


def test_submit_pending_then_confirmed():
    cal = FakeCalendar()
    p = _provider(cal)
    manifest = b'{"kind":"entry"}'
    rid = hashlib.sha256(manifest).hexdigest()
    res = p.submit(rid, manifest)
    assert res.status == "pending" and res.verified_time is None
    parsed = parse_ots(res.proof)
    assert parsed.file_digest.hex() == rid  # the proof starts from the manifest hash
    assert parsed.pending and parsed.bitcoin == []
    assert sum(1 for r in cal.received if r.split(b"\n")[0].endswith(b"/digest")) == 2  # two calendars
    # Calendars only ever saw a salted hash, never the record ID or the manifest.
    wire = b"".join(cal.received)
    assert bytes.fromhex(rid) not in wire and rid.encode() not in wire and manifest not in wire
    assert all(len(r.split(b"\n", 1)[1]) == 32 for r in cal.received)

    still = p.upgrade(res.proof)
    assert still.status == "pending"
    cal.confirmed = True
    done = p.upgrade(still.proof)
    assert done.status == "confirmed" and done.verified_time == "2026-10-12T12:00:00Z"
    assert parse_ots(done.proof).bitcoin[0].height == 900_000
    check = p.verify(rid, done.proof)
    assert check.verified and "fake explorers" in check.detail


def test_header_mismatch_is_rejected_and_missing_header_stays_pending():
    cal = FakeCalendar()
    manifest = b"{}"
    rid = hashlib.sha256(manifest).hexdigest()
    proof = _provider(cal).submit(rid, manifest).proof
    cal.confirmed = True
    with pytest.raises(ProviderRejected, match="BTC_INVALID"):
        _provider(cal, lookup=lambda h: ("00" * 32, 1)).upgrade(proof)
    res = _provider(cal, lookup=lambda h: None).upgrade(proof)
    assert res.status == "pending" and "could not fetch the block header" in res.detail


def test_calendar_failures():
    cal = FakeCalendar()
    cal.down = True
    with pytest.raises(ProviderUnavailable):
        _provider(cal).submit(hashlib.sha256(b"{}").hexdigest(), b"{}")
    cal.down = False
    proof = _provider(cal).submit(hashlib.sha256(b"{}").hexdigest(), b"{}").proof
    cal.down = True
    with pytest.raises(ProviderUnavailable):
        _provider(cal).upgrade(proof)


def test_non_whitelisted_calendar_is_never_contacted():
    from opentimestamps.core.notary import PendingAttestation
    from opentimestamps.core.op import OpSHA256
    from opentimestamps.core.serialize import BytesSerializationContext
    from opentimestamps.core.timestamp import DetachedTimestampFile, Timestamp

    digest = hashlib.sha256(b"{}").digest()
    dtf = DetachedTimestampFile(OpSHA256(), Timestamp(digest))
    dtf.timestamp.attestations.add(PendingAttestation("https://evil.example"))
    ctx = BytesSerializationContext()
    dtf.serialize(ctx)
    cal = FakeCalendar()
    with pytest.raises(ProviderUnavailable):
        _provider(cal).upgrade(ctx.getbytes())
    assert cal.received == []


def test_explorer_quorum():
    good = {"merkle_root": "ab" * 32, "timestamp": 1700000000, "height": 5}

    def fetch_for(answers):
        def fetch(url, data=None, headers=None):
            for host, info in answers.items():
                if host in url:
                    if info is None:
                        raise OSError("down")
                    if "/block-height/" in url:
                        return b"cd" * 32
                    return json.dumps(info).encode()
            raise AssertionError(url)

        return fetch

    both = ExplorerHeaderLookup(fetch=fetch_for({"blockstream.info": good, "mempool.space": good}))
    assert both(5) == ("ab" * 32, 1700000000)
    assert "block explorers" in both.method
    one_down = ExplorerHeaderLookup(fetch=fetch_for({"blockstream.info": good, "mempool.space": None}))
    assert one_down(5) is None
    disagree = ExplorerHeaderLookup(
        fetch=fetch_for({"blockstream.info": good, "mempool.space": {**good, "merkle_root": "ee" * 32}})
    )
    assert disagree(5) is None


def test_node_lookup():
    calls = []

    def fetch(url, data=None, headers=None):
        req = json.loads(data)
        calls.append((url, req["method"], headers.get("Authorization")))
        if req["method"] == "getblockhash":
            return json.dumps({"result": "ff" * 32, "error": None}).encode()
        return json.dumps({"result": {"merkleroot": "AB" * 32, "time": 1600000000}, "error": None}).encode()

    node = NodeHeaderLookup("http://user:pw@127.0.0.1:8332", fetch=fetch)
    assert node(10) == ("ab" * 32, 1600000000)
    assert calls[0][0] == "http://127.0.0.1:8332" and calls[0][2].startswith("Basic ")


def test_app_flow_with_bitcoin_anchor(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app

    cal = FakeCalendar()
    ctx = make_ctx(tmp_path, btc=_provider(cal))
    with TestClient(create_app(ctx), base_url="http://127.0.0.1:8765") as cl:
        cl.headers["X-RPROV-Token"] = ctx.session_token
        api = Api(cl, ctx).init()
        out = api.entry("anchored", body="x")
        btc = out["detail"]["verified"]["timestamps"]["btc"]
        assert btc["state"] == "pending" and btc["text"] == "Bitcoin anchor: pending"
        cl.post("/api/anchors/refresh")
        assert cl.get(f"/api/records/{out['id']}").json()["verified"]["timestamps"]["btc"]["state"] == "pending"
        cal.confirmed = True
        stats = cl.post("/api/anchors/refresh").json()
        assert stats["upgraded"] == 2  # genesis + entry
        d = cl.get(f"/api/records/{out['id']}").json()["verified"]
        assert d["timestamps"]["btc"]["state"] == "confirmed"
        assert d["timestamps"]["btc"]["text"] == "Bitcoin anchor: confirmed"
        assert d["timestamps"]["btc"]["time"] == "2026-10-12T12:00:00Z"
        assert d["timestamps"]["tsa"]["state"] == "confirmed"  # still reported separately
        report = cl.post("/api/verify/all").json()
        assert report["ok"] is True, json.dumps([(r["kind"], r["issues"]) for r in report["records"]])
        rec = next(r for r in report["records"] if r["record_id"] == out["id"])
        assert rec["btc"]["state"] == "verified" and rec["tsa"]["state"] == "verified"
        # The mock TSA time is "now" and the fake block time is fixed, so they differ: a warning, not a failure.
        assert rec["status"] in ("pass", "warning")
    ctx.close()


def test_bundle_with_confirmed_bitcoin_anchor_verifies(tmp_path):
    import subprocess
    import sys

    from app.services.export import build_bundle_files, plan_export, write_dir
    from provenance_core.bundle import load_bundle
    from provenance_core.providers.mock import mock_tsa_root
    from provenance_core.verify import verify_log
    from tests.sample import build_log

    cal = FakeCalendar()
    ctx = make_ctx(tmp_path, btc=_provider(cal))
    build_log(ctx)
    cal.confirmed = True
    ctx.anchors.refresh(force=True)
    plan = plan_export(ctx.ledger, "btc", None, default="full")
    bundle = tmp_path / "bundle"
    write_dir(build_bundle_files(ctx.ledger, ctx.anchors, plan), bundle)
    ctx.close()
    b = load_bundle(bundle)
    report = verify_log(b.chain_ids, b.materials, tsa_roots=[mock_tsa_root()], btc_header_lookup=cal.header_lookup)
    assert report.ok
    assert all(r.btc.verified and r.tsa.verified for r in report.records)
    out = subprocess.run([sys.executable, "-I", str(bundle / "verify.py"), str(bundle), "--offline",
                          "--tsa-root", str(bundle / "certs/mock-tsa-root.pem")], capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0, out.stdout + out.stderr
    assert "Bitcoin anchor: attested, block header not checked" in out.stdout
    # A forged .ots (commitment changed) fails even offline, because the start digest no longer matches.
    rid = b.chain_ids[1]
    ots = bundle / f"manifests/{rid}.json.ots"
    data = bytearray(ots.read_bytes())
    data[60] ^= 0xFF
    ots.write_bytes(bytes(data))
    out = subprocess.run([sys.executable, "-I", str(bundle / "verify.py"), str(bundle), "--offline",
                          "--tsa-root", str(bundle / "certs/mock-tsa-root.pem")], capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 1 and "BTC_INVALID" in out.stdout
