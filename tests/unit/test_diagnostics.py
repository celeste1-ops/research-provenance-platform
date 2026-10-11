"""“Check stamp services” (D-045), without network: every service answered by a fake."""

from datetime import UTC, datetime

import httpx
from fastapi.testclient import TestClient
from rfc3161_client._rust import parse_timestamp_request

from app.config import Settings
from app.main import create_app
from app.services import context
from provenance_core.providers import diagnostics as D
from provenance_core.providers.mock import build_mock_tsr, mock_tsa_root
from provenance_core.providers.rfc3161 import Rfc3161Provider
from tests.conftest import make_ctx

CALENDARS = ("https://cal-a.test", "https://cal-b.test")
EXPLORERS = (("explorer-a", "https://exp-a.test/api"), ("explorer-b", "https://exp-b.test/api"))


def tsa_answer(request):
    req = parse_timestamp_request(request.content)
    return httpx.Response(200, content=build_mock_tsr(bytes(req.message_imprint.message), datetime.now(UTC),
                                                       req.nonce))


def down(request):
    raise httpx.ConnectError("connection refused")


def services(request):
    host = request.url.host
    if host == "cal-a.test":
        assert request.url.path.startswith("/timestamp/") and len(request.url.path) == len("/timestamp/") + 64
        assert request.headers["accept"] == "application/vnd.opentimestamps.v1"
        return httpx.Response(404, text="Not found")  # never saw this random value: reachable
    if host == "cal-b.test":
        raise httpx.ConnectTimeout("timed out")
    if host == "exp-a.test":
        assert request.url.path == "/api/blocks/tip/height"
        return httpx.Response(200, text="917123")
    if host == "exp-b.test":
        return httpx.Response(503)
    raise AssertionError(f"unexpected request to {request.url}")


def test_each_service_is_reported_in_a_fixed_order():
    seen = []

    def stamp(request):
        seen.append(request.content)
        return tsa_answer(request)

    tsas = [
        ("Good TSA", Rfc3161Provider("https://good.test/tsr", roots=[mock_tsa_root()], name="good",
                                     transport=httpx.MockTransport(stamp))),
        ("Blocked TSA", Rfc3161Provider("https://blocked.test/tsr", roots=[mock_tsa_root()], name="blocked",
                                        transport=httpx.MockTransport(down))),
        # Answers, but signed by someone the built-in FreeTSA root does not vouch for.
        ("Wrong TSA", Rfc3161Provider("https://wrong.test/tsr", name="wrong",
                                      transport=httpx.MockTransport(tsa_answer))),
    ]
    checks = D.run_checks(tsas, calendars=CALENDARS, explorers=EXPLORERS, transport=httpx.MockTransport(services))
    got = [(c.group, c.name, c.ok) for c in checks]
    assert got == [
        ("tsa", "Good TSA", True), ("tsa", "Blocked TSA", False), ("tsa", "Wrong TSA", False),
        ("calendar", "cal-a.test", True), ("calendar", "cal-b.test", False),
        ("explorer", "explorer-a", True), ("explorer", "explorer-b", False),
    ]
    by_name = {c.name: c for c in checks}
    assert by_name["Good TSA"].detail == "stamp received and checked" and by_name["Good TSA"].ms is not None
    assert by_name["Blocked TSA"].detail.startswith("not reachable") and by_name["Blocked TSA"].ms is None
    assert "did not check out" in by_name["Wrong TSA"].detail
    assert by_name["cal-b.test"].detail == "not reachable (ConnectTimeout)"
    assert by_name["explorer-a"].detail == "current block 917,123"
    assert by_name["explorer-b"].detail == "HTTP 503"
    # Only a digest of a random value went to the authority.
    req = parse_timestamp_request(seen[0])
    assert len(bytes(req.message_imprint.message)) == 32
    assert b"rprov" not in seen[0]


def test_default_check_covers_both_authorities_all_calendars_and_both_explorers(monkeypatch):
    captured = {}

    def fake_run(tsas, **kwargs):
        captured["tsas"] = [(label, p.name, p.url) for label, p in tsas]
        captured.update(kwargs)
        return []

    monkeypatch.setattr(D, "run_checks", fake_run)
    out = context.check_stamp_services(Settings(btc="ots", keystore="memory"))
    assert captured["tsas"] == [("FreeTSA", "freetsa", "https://freetsa.org/tsr"),
                                ("DigiCert", "digicert", "http://timestamp.digicert.com")]
    assert out["in_use"] == {"tsa": ["freetsa", "digicert"], "btc": True, "explorers": True}
    assert len(D.DEFAULT_CALENDARS) == 4 and len(D.PUBLIC_EXPLORERS) == 2


def test_in_use_follows_the_settings():
    use = context.services_in_use
    assert use(Settings(tsa="off", btc="off", keystore="memory")) == {"tsa": [], "btc": False, "explorers": False}
    assert use(Settings(tsa="digicert", tsa_fallback="off", btc="ots", bitcoin_rpc="http://node",
                        keystore="memory")) == {"tsa": ["digicert"], "btc": True, "explorers": False}


def test_check_route_needs_the_session_token_and_runs_only_on_request(tmp_path):
    ctx = make_ctx(tmp_path)
    calls = []
    ctx.service_check = lambda: calls.append(1) or {"checks": [{"group": "tsa", "name": "FreeTSA", "ok": True}],
                                                    "in_use": {"tsa": ["freetsa"], "btc": True, "explorers": True}}
    with TestClient(create_app(ctx), base_url="http://127.0.0.1:8765") as cl:
        assert cl.post("/api/network/check").status_code == 403
        cl.get("/api/status")
        assert calls == []  # nothing is checked unless asked
        cl.headers["X-RPROV-Token"] = ctx.session_token
        r = cl.post("/api/network/check")
        assert r.status_code == 200 and r.json()["checks"][0]["name"] == "FreeTSA"
        assert calls == [1]
    ctx.close()
