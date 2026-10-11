"""DigiCert lists the certificates in its tokens in chain order, which DER does not allow;
rfc3161-client then refuses the whole token (InvalidSetOrdering, found on the Mac with a
real DigiCert response). The certificates are sorted before anything reads or stores the
token (D-045)."""

import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from rfc3161_client import decode_timestamp_response
from rfc3161_client._rust import parse_timestamp_request

from app.services.export import signer_chain_file
from provenance_core.certs import DIGICERT_ROOT_FILE, FREETSA_ROOT_FILE, builtin_tsa_roots
from provenance_core.proofs import canonical_tsr, tsa_embedded_certificates, verify_tsa_proof
from provenance_core.providers.mock import MOCK_TSA_DIR, build_mock_tsr, mock_tsa_root
from provenance_core.providers.rfc3161 import Rfc3161Provider

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "tsa"
MANIFEST = b'{"kind":"entry","title":"chain order"}'
RID = hashlib.sha256(MANIFEST).hexdigest()


def _chain_ordered_tsr(nonce=None) -> bytes:
    """Signer, then two more certificates, deliberately not in DER order."""
    extra = [mock_tsa_root(), x509.load_pem_x509_certificate(FREETSA_ROOT_FILE.read_bytes())]
    der = lambda c: c.public_bytes(serialization.Encoding.DER)  # noqa: E731
    signer = x509.load_pem_x509_certificate((MOCK_TSA_DIR / "mock-tsa.pem").read_bytes())
    if [der(signer)] + [der(c) for c in extra] == sorted([der(signer)] + [der(c) for c in extra]):
        extra.reverse()
    return build_mock_tsr(bytes.fromhex(RID), datetime.now(UTC), nonce, chain=extra, chain_order=True)


def test_a_token_with_certificates_in_chain_order_is_refused_by_rfc3161_client():
    raw = _chain_ordered_tsr()
    with pytest.raises(Exception, match="(?i)ordering"):
        decode_timestamp_response(raw)


def test_sorting_the_certificates_makes_it_readable_and_changes_nothing_signed():
    raw = _chain_ordered_tsr()
    fixed = canonical_tsr(raw)
    assert fixed != raw and len(fixed) == len(raw)
    assert canonical_tsr(fixed) == fixed  # already in order: unchanged
    assert len(decode_timestamp_response(fixed).signed_data.certificates) == 3
    for token in (raw, fixed):  # the check sorts by itself, so a stored raw token still verifies
        check = verify_tsa_proof(RID, token, [mock_tsa_root()])
        assert check.verified, check
    assert len(tsa_embedded_certificates(raw)) == 3


def test_canonical_tsr_leaves_what_it_cannot_read_alone():
    for junk in (b"", b"\x30\x03\x02\x01", b"not a token at all"):
        assert canonical_tsr(junk) == junk


def test_the_provider_stores_the_sorted_token():
    def handler(request):
        req = parse_timestamp_request(request.content)
        return httpx.Response(200, content=_chain_ordered_tsr(req.nonce))

    p = Rfc3161Provider("http://digicert.test", name="digicert", roots=[mock_tsa_root()],
                        transport=httpx.MockTransport(handler))
    result = p.submit(RID, MANIFEST)
    assert result.status == "confirmed"
    assert decode_timestamp_response(result.proof)  # rfc3161-client reads what was stored
    assert canonical_tsr(result.proof) == result.proof


def test_openssl_accepts_the_sorted_token(tmp_path):
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("openssl not installed")
    (tmp_path / "m.json").write_bytes(MANIFEST)
    (tmp_path / "t.tsr").write_bytes(canonical_tsr(_chain_ordered_tsr()))
    out = subprocess.run(
        [openssl, "ts", "-verify", "-data", "m.json", "-in", "t.tsr",
         "-CAfile", str(MOCK_TSA_DIR / "mock-tsa-root.pem")],
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8",
    )
    assert out.returncode == 0 and "Verification: OK" in out.stdout, out.stdout + out.stderr


# Real responses saved with `make tsa-fixture` on a networked machine (tools/capture_tsa_fixture.py).
REAL = sorted(FIXTURES.glob("*.tsr"))


@pytest.mark.parametrize("path", REAL, ids=[p.stem for p in REAL])
def test_real_saved_responses_verify_offline(path, tmp_path):
    meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    raw = path.read_bytes()
    check = verify_tsa_proof(meta["record_id"], raw, builtin_tsa_roots())
    assert check.verified, check
    fixed = canonical_tsr(raw)
    assert decode_timestamp_response(fixed)
    embedded = tsa_embedded_certificates(raw)
    if meta["authority"] == "digicert":
        assert "DigiCert" in check.source
        assert signer_chain_file(embedded) == "digicert-tsa-chain.pem"
        ca_file, chain_name = DIGICERT_ROOT_FILE, "digicert-tsa-chain.pem"
    else:
        assert signer_chain_file(embedded) == "freetsa-tsa.crt"
        ca_file, chain_name = FREETSA_ROOT_FILE, "freetsa-tsa.crt"
    openssl = shutil.which("openssl")
    if openssl is None:
        return
    (tmp_path / chain_name).write_bytes(b"".join(c.public_bytes(serialization.Encoding.PEM) for c in embedded))
    (tmp_path / "t.tsr").write_bytes(fixed)
    out = subprocess.run(
        [openssl, "ts", "-verify", "-digest", meta["record_id"], "-in", "t.tsr", "-CAfile", str(ca_file),
         "-untrusted", chain_name],
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8",
    )
    assert out.returncode == 0 and "Verification: OK" in out.stdout, out.stdout + out.stderr
