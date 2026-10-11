"""AC-09 (network): a real FreeTSA .tsr verifies with the openssl command from PRD §10.

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
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert out.returncode == 0 and "Verification: OK" in out.stdout, out.stdout + out.stderr
