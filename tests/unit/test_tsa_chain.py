"""Two time-stamping authorities: FreeTSA first, DigiCert when it cannot be reached (D-045)."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from rfc3161_client._rust import parse_timestamp_request

from app.config import Settings
from app.services.context import make_providers
from app.services.export import signer_chain_file
from provenance_core import certs as C
from provenance_core.providers.base import (
    AnchorResult,
    ProviderRejected,
    ProviderUnavailable,
    TimestampProvider,
)
from provenance_core.providers.mock import build_mock_tsr, mock_tsa_root
from provenance_core.providers.rfc3161 import Rfc3161Provider
from provenance_core.providers.tsa_chain import PENALTY_SECONDS, TsaChain
from tests.conftest import Api, make_ctx


class Fake(TimestampProvider):
    kind = "tsa"

    def __init__(self, name, *, fail=None):
        self.name = name
        self.fail = fail
        self.calls = 0

    def submit(self, record_id, manifest_bytes):
        self.calls += 1
        if self.fail == "down":
            raise ProviderUnavailable(f"{self.name}: no route to host")
        if self.fail == "rejected":
            raise ProviderRejected(f"{self.name}: HTTP 400")
        return AnchorResult(status="confirmed", proof=self.name.encode())

    def verify(self, record_id, proof):
        raise NotImplementedError


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_first_authority_is_used_when_it_answers():
    a, b = Fake("freetsa"), Fake("digicert")
    result = TsaChain([a, b]).submit("ab" * 32, b"{}")
    assert result.provider == "freetsa" and result.proof == b"freetsa"
    assert (a.calls, b.calls) == (1, 0)


@pytest.mark.parametrize("failure", ["down", "rejected"])
def test_second_authority_answers_when_the_first_fails(failure):
    a, b = Fake("freetsa", fail=failure), Fake("digicert")
    result = TsaChain([a, b]).submit("ab" * 32, b"{}")
    assert result.provider == "digicert" and result.proof == b"digicert"


def test_a_failed_authority_waits_an_hour_before_it_is_tried_first_again():
    clock = Clock()
    a, b = Fake("freetsa", fail="down"), Fake("digicert")
    chain = TsaChain([a, b], clock=clock)
    chain.submit("ab" * 32, b"{}")
    assert [p.name for p in chain.order()] == ["digicert", "freetsa"]
    # The next save goes straight to DigiCert: no waiting for FreeTSA's timeout again.
    a.fail = None
    assert chain.submit("ab" * 32, b"{}").provider == "digicert"
    assert a.calls == 1
    clock.now += PENALTY_SECONDS + 1
    assert [p.name for p in chain.order()] == ["freetsa", "digicert"]
    assert chain.submit("ab" * 32, b"{}").provider == "freetsa"


def test_a_penalized_authority_is_still_tried_when_the_other_fails_too():
    clock = Clock()
    a, b = Fake("freetsa", fail="down"), Fake("digicert")
    chain = TsaChain([a, b], clock=clock)
    chain.submit("ab" * 32, b"{}")  # FreeTSA penalized
    a.fail, b.fail = None, "down"
    assert chain.submit("ab" * 32, b"{}").provider == "freetsa"
    assert [p.name for p in chain.order()] == ["freetsa", "digicert"]  # success clears the penalty


def test_no_authority_answering_is_a_transient_failure_naming_both():
    chain = TsaChain([Fake("freetsa", fail="down"), Fake("digicert", fail="down")])
    with pytest.raises(ProviderUnavailable, match="freetsa.*digicert"):
        chain.submit("ab" * 32, b"{}")


def test_default_settings_build_freetsa_then_digicert():
    chain = make_providers(Settings(tsa="freetsa", btc="off", keystore="memory"))["tsa"]
    assert isinstance(chain, TsaChain)
    assert [p.name for p in chain.providers] == ["freetsa", "digicert"]
    assert chain.providers[0].url == "https://freetsa.org/tsr"
    assert chain.providers[1].url == "http://timestamp.digicert.com"
    # Each authority trusts only its own root; the chain as a whole trusts both.
    sha = lambda c: c.fingerprint(hashes.SHA256()).hex()  # noqa: E731
    assert [sha(c) for c in chain.providers[0].trust_roots()] == [C.FREETSA_ROOT_SHA256]
    assert [sha(c) for c in chain.providers[1].trust_roots()] == [C.DIGICERT_ROOT_SHA256]
    assert sorted(sha(c) for c in chain.trust_roots()) == sorted([C.FREETSA_ROOT_SHA256, C.DIGICERT_ROOT_SHA256])
    assert {"freetsa-cacert.pem", "freetsa-tsa.crt", "digicert-trusted-root-g4.pem"} <= set(
        chain.bundle_certificates())


def test_order_and_fallback_follow_the_settings():
    names = lambda s: [p.name for p in make_providers(s)["tsa"].providers]  # noqa: E731
    assert names(Settings(tsa="digicert", btc="off", keystore="memory")) == ["digicert", "freetsa"]
    assert names(Settings(tsa="freetsa", tsa_fallback="off", btc="off", keystore="memory")) == ["freetsa"]
    assert names(Settings(tsa="freetsa", tsa_fallback="freetsa", btc="off", keystore="memory")) == ["freetsa"]


def test_pinned_roots_refuse_a_changed_certificate(monkeypatch):
    assert len(C.builtin_tsa_roots()) == 2
    monkeypatch.setattr(C, "BUILTIN_TSA_ROOTS", (("digicert-trusted-root-g4.pem", "x", "00" * 32),))
    with pytest.raises(RuntimeError, match="pinned fingerprint"):
        C.builtin_tsa_roots()


def _mock_tsa(seen):
    def handler(request):
        seen.append(request.url.host)
        req = parse_timestamp_request(request.content)
        tsr = build_mock_tsr(bytes(req.message_imprint.message), datetime.now(UTC), req.nonce)
        return httpx.Response(200, content=tsr)

    return httpx.MockTransport(handler)


def test_the_record_remembers_which_authority_stamped_it(tmp_path):
    """FreeTSA unreachable: the step is still saved, stamped by the second authority, and the
    stored proof row names it."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    def down(request):
        raise httpx.ConnectError("blocked")

    seen: list[str] = []
    chain = TsaChain([
        Rfc3161Provider("https://freetsa.test/tsr", name="freetsa", roots=[mock_tsa_root()],
                        transport=httpx.MockTransport(down)),
        Rfc3161Provider("http://digicert.test", name="digicert", roots=[mock_tsa_root()], transport=_mock_tsa(seen)),
    ])
    ctx = make_ctx(tmp_path, tsa=chain)
    with TestClient(create_app(ctx), base_url="http://127.0.0.1:8765") as cl:
        cl.headers["X-RPROV-Token"] = ctx.session_token
        api = Api(cl, ctx).init()
        out = api.entry("saved while FreeTSA is blocked")
        assert out["detail"]["verified"]["timestamps"]["tsa"]["state"] == "confirmed"
        assert cl.post("/api/verify/all").json()["ok"] is True
    rows = ctx.anchors.rows_by_record()
    assert rows[out["id"]]["tsa"].provider_name == "digicert"
    assert "digicert.test" in seen
    ctx.close()


def _cert(issuer_org: str) -> x509.Certificate:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(x509.NameOID.ORGANIZATION_NAME, issuer_org),
                      x509.NameAttribute(x509.NameOID.COMMON_NAME, "test")])
    now = datetime.now(UTC)
    return (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(1).not_valid_before(now).not_valid_after(now + timedelta(days=1))
            .sign(key, hashes.SHA256()))


def test_exported_signer_certificates_are_grouped_per_authority():
    assert signer_chain_file([_cert("DigiCert, Inc.")]) == "digicert-tsa-chain.pem"
    assert signer_chain_file([_cert("Free TSA"), _cert("DigiCert Inc")]) == "digicert-tsa-chain.pem"
    assert signer_chain_file([_cert("Free TSA")]) == "freetsa-tsa.crt"
    assert signer_chain_file([]) == "freetsa-tsa.crt"


def test_digicert_root_file_matches_its_pin():
    cert = x509.load_pem_x509_certificate(C.DIGICERT_ROOT_FILE.read_bytes())
    assert cert.fingerprint(hashes.SHA256()).hex() == C.DIGICERT_ROOT_SHA256
    assert cert.subject.rfc4514_string() == "CN=DigiCert Trusted Root G4,OU=www.digicert.com,O=DigiCert Inc,C=US"
