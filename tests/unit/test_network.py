"""Network tests (run on the Mac): AC-09 — a real FreeTSA .tsr verifies with the openssl
command from PRD §10 — plus real OpenTimestamps calendars and block explorers.

Skipped unless RPROV_NETWORK_TESTS=1 (`make test-network` on the Mac).
"""

import shutil
import subprocess
import uuid

import pytest

from provenance_core import records as R
from provenance_core.certs import FREETSA_ROOT_FILE, FREETSA_TSA_FILE, builtin_tsa_roots
from provenance_core.proofs import verify_tsa_proof
from provenance_core.providers.rfc3161 import Rfc3161Provider

pytestmark = pytest.mark.network


def _manifest():
    payload = R.genesis_payload("network test", "ab" * 32)
    return R.encode_record("genesis", str(uuid.uuid4()), 0, None, payload)


def test_real_freetsa_token_verifies_with_openssl(tmp_path):
    manifest_bytes, _, rid = _manifest()
    result = Rfc3161Provider().submit(rid, manifest_bytes)
    assert result.status == "confirmed"
    assert verify_tsa_proof(rid, result.proof, builtin_tsa_roots()).verified
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("openssl not installed")
    (tmp_path / "manifests").mkdir()
    (tmp_path / "proofs").mkdir()
    (tmp_path / "manifests" / f"{rid}.json").write_bytes(manifest_bytes)
    (tmp_path / "proofs" / f"{rid}.tsr").write_bytes(result.proof)
    out = subprocess.run(
        [openssl, "ts", "-verify", "-data", f"manifests/{rid}.json", "-in", f"proofs/{rid}.tsr",
         "-CAfile", str(FREETSA_ROOT_FILE), "-untrusted", str(FREETSA_TSA_FILE)],
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8",
    )
    assert out.returncode == 0 and "Verification: OK" in out.stdout, out.stdout + out.stderr


def test_real_opentimestamps_submission_is_pending():
    from provenance_core.ots import parse_ots
    from provenance_core.providers.ots import OtsProvider

    manifest_bytes, _, rid = _manifest()
    res = OtsProvider().submit(rid, manifest_bytes)
    assert res.status == "pending"
    proof = parse_ots(res.proof)
    assert proof.file_digest.hex() == rid and len(proof.pending) >= 2


def test_real_block_explorers_confirm_the_official_example():
    """hello-world.txt.ots (block 358391) checked against two public block explorers."""
    import hashlib
    from pathlib import Path

    from provenance_core.proofs import verify_btc_proof
    from provenance_core.providers.explorers import ExplorerHeaderLookup

    fix = Path(__file__).resolve().parent.parent / "fixtures" / "ots"
    digest = hashlib.sha256((fix / "hello-world.txt").read_bytes()).hexdigest()
    check = verify_btc_proof(digest, (fix / "hello-world.txt.ots").read_bytes(), header_lookup=ExplorerHeaderLookup())
    assert check.verified, check
    assert check.time.startswith("2015-05-28")
    assert "block explorers" in check.detail
