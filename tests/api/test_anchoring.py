"""AC-10 (offline, then manual refresh) and the RFC 3161 provider without network."""

import hashlib
import time
from datetime import UTC, datetime

import httpx
import pytest
from rfc3161_client._rust import parse_timestamp_request

from app.jobs.scheduler import AnchorScheduler
from app.services.anchors import backoff_delay
from provenance_core.providers.base import ProviderRejected, ProviderUnavailable
from provenance_core.providers.mock import MockProvider, build_mock_tsr, mock_tsa_root
from provenance_core.providers.rfc3161 import Rfc3161Provider
from tests.conftest import Api, make_ctx


def _mock_tsa_transport(seen: list[bytes], tamper=None):
    """An httpx transport that answers like an RFC 3161 server signing with the mock CA."""

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.content)
        assert request.headers["content-type"] == "application/timestamp-query"
        req = parse_timestamp_request(request.content)
        digest = bytes(req.message_imprint.message)
        nonce = req.nonce if tamper != "nonce" else (req.nonce or 0) + 1
        tsr = build_mock_tsr(digest if tamper != "digest" else b"\x00" * 32, datetime.now(UTC), nonce)
        return httpx.Response(200, content=tsr, headers={"content-type": "application/timestamp-reply"})

    return httpx.MockTransport(handler)


def _provider(transport):
    return Rfc3161Provider("https://tsa.test/tsr", roots=[mock_tsa_root()], name="test-tsa", transport=transport)


def test_rfc3161_provider_sends_only_the_digest_and_verifies_reply():
    manifest = b'{"kind":"entry","seq":1}'
    rid = hashlib.sha256(manifest).hexdigest()
    seen: list[bytes] = []
    result = _provider(_mock_tsa_transport(seen)).submit(rid, manifest)
    assert result.status == "confirmed" and result.verified_time
    assert len(seen) == 1
    req = parse_timestamp_request(seen[0])
    assert bytes(req.message_imprint.message) == bytes.fromhex(rid)
    assert req.message_imprint.hash_algorithm.dotted_string == "2.16.840.1.101.3.4.2.1"  # SHA-256, explicit
    assert req.cert_req is True and req.nonce is not None
    assert manifest not in seen[0]


@pytest.mark.parametrize("tamper", ["nonce", "digest"])
def test_rfc3161_provider_rejects_bad_replies(tamper):
    manifest = b"{}"
    rid = hashlib.sha256(manifest).hexdigest()
    with pytest.raises(ProviderRejected):
        _provider(_mock_tsa_transport([], tamper)).submit(rid, manifest)


def test_rfc3161_provider_untrusted_root_rejected():
    manifest = b"{}"
    rid = hashlib.sha256(manifest).hexdigest()
    p = Rfc3161Provider("https://tsa.test/tsr", transport=_mock_tsa_transport([]))  # built-in roots only
    with pytest.raises(ProviderRejected, match="TSA_CHAIN_UNTRUSTED"):
        p.submit(rid, manifest)


def test_rfc3161_provider_network_errors_are_transient():
    def down(request):
        raise httpx.ConnectError("no route to host")

    manifest = b"{}"
    rid = hashlib.sha256(manifest).hexdigest()
    with pytest.raises(ProviderUnavailable):
        _provider(httpx.MockTransport(down)).submit(rid, manifest)
    with pytest.raises(ProviderUnavailable):
        _provider(httpx.MockTransport(lambda r: httpx.Response(503))).submit(rid, manifest)


def test_offline_record_succeeds_then_manual_refresh_completes(tmp_path):  # AC-10
    from fastapi.testclient import TestClient

    from app.main import create_app

    tsa = MockProvider("tsa", offline=True)
    btc = MockProvider("btc", offline=True)
    ctx = make_ctx(tmp_path, tsa=tsa, btc=btc)
    with TestClient(create_app(ctx), base_url="http://127.0.0.1:8765") as cl:
        cl.headers["X-RPROV-Token"] = ctx.session_token
        api = Api(cl, ctx).init()
        out = api.entry("written on a plane", body="offline")
        ts = out["detail"]["verified"]["timestamps"]
        assert ts["tsa"]["state"] == "none" and ts["tsa"]["time"] is None
        assert ts["tsa"]["text"].startswith("Third-party timestamp: no timestamp yet")
        assert ts["btc"]["state"] == "none"
        assert out["detail"]["verified"]["earliest_verified"] is None
        row = next(r for r in cl.get("/api/timeline").json() if r["id"] == out["id"])
        assert row["earliest_verified"] is None

        # Still offline: refreshing changes nothing and the record stays intact.
        cl.post("/api/anchors/refresh")
        assert cl.get(f"/api/records/{out['id']}").json()["verified"]["timestamps"]["tsa"]["state"] == "none"

        tsa.offline = btc.offline = False
        stats = cl.post("/api/anchors/refresh").json()
        assert stats["submitted"] >= 2
        d = cl.get(f"/api/records/{out['id']}").json()
        assert d["verified"]["timestamps"]["tsa"]["state"] == "confirmed"
        assert d["verified"]["timestamps"]["btc"]["state"] == "pending"
        assert cl.post("/api/verify/all").json()["ok"] is True
    ctx.close()


def test_backoff_and_due_schedule(tmp_path):
    assert backoff_delay(1).total_seconds() == 60
    assert backoff_delay(3).total_seconds() == 240
    assert backoff_delay(50).total_seconds() == 6 * 3600
    tsa = MockProvider("tsa", offline=True)
    ctx = make_ctx(tmp_path, tsa=tsa, btc=MockProvider("btc"))
    ctx.ledger.init_identity("A")
    tsa.offline = False
    assert ctx.anchors.refresh(force=False)["submitted"] == 0  # not due yet (backoff)
    assert ctx.anchors.refresh(force=True)["submitted"] == 1
    ctx.close()


def test_pending_btc_upgrades_on_refresh(tmp_path):
    btc = MockProvider("btc")
    ctx = make_ctx(tmp_path, btc=btc)
    ctx.ledger.init_identity("A")
    assert ctx.anchors.refresh(force=True)["still_pending"] == 1
    btc.confirm_on_upgrade = True
    assert ctx.anchors.refresh(force=True)["upgraded"] == 1
    rows = ctx.anchors.rows_by_record()
    (only,) = rows.values()
    assert only["btc"].status == "confirmed" and only["tsa"].status == "confirmed"
    ctx.close()


def test_scheduler_runs_at_start(tmp_path):
    ctx = make_ctx(tmp_path)
    sched = AnchorScheduler(ctx.anchors, interval=3600)
    sched.start()
    sched.stop()
    assert sched.runs == 1
    ctx.close()


def test_enabling_a_provider_later_backfills_rows(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.anchors.providers["btc"] = None
    ctx.ledger.init_identity("A")
    assert set(next(iter(ctx.anchors.rows_by_record().values()))) == {"tsa"}
    ctx.anchors.providers["btc"] = MockProvider("btc")
    assert ctx.anchors.ensure_rows() == 1
    ctx.close()


def test_saving_does_not_wait_again_for_a_service_that_just_failed(tmp_path):
    """D-045: where a stamp service is blocked, only the first save waits for its time limit."""
    from app.services import anchors as A
    from app.services.ledger import EntryInput

    class Counting(MockProvider):
        calls = 0

        def submit(self, record_id, manifest_bytes):
            self.calls += 1
            return super().submit(record_id, manifest_bytes)

    tsa, btc = Counting("tsa", offline=True), Counting("btc")
    ctx = make_ctx(tmp_path, tsa=tsa, btc=btc)
    ctx.ledger.init_identity("A")  # first save: the date stamp service is tried and fails
    assert tsa.calls == 1 and ctx.anchors.recently_unreachable("tsa")
    pid = ctx.ledger.create_project("P").id
    ctx.ledger.create_entry(EntryInput(pid, "idea", "quick save"))
    assert tsa.calls == 1, "the second save must not wait for the unreachable service again"
    assert btc.calls == 2  # the working service is still asked on every save
    # The retry job still tries it; once it answers, saving asks it again.
    tsa.offline = False
    assert ctx.anchors.refresh(force=True)["submitted"] == 2
    assert not ctx.anchors.recently_unreachable("tsa")
    assert all(r["tsa"].status == "confirmed" for r in ctx.anchors.rows_by_record().values())
    ctx.ledger.create_entry(EntryInput(pid, "idea", "online again"))
    assert tsa.calls == 4
    # After the waiting period, a save tries a still-blocked service again.
    tsa.offline = True
    ctx.ledger.create_entry(EntryInput(pid, "idea", "blocked again"))
    assert tsa.calls == 5
    ctx.anchors._unreachable_at["tsa"] = time.monotonic() - A.SKIP_AFTER_UNREACHABLE_SECONDS - 1
    ctx.ledger.create_entry(EntryInput(pid, "idea", "ten minutes later"))
    assert tsa.calls == 6
    ctx.close()
