"""AC-18: in a brand-new virtual environment with only verify.py's declared
dependencies, verify.py exits 0 on the untampered sample bundle.
Also runs the manual VERIFY.md commands (sha256sum / openssl) on the same bundle."""

import hashlib
import json
import shutil
import subprocess

import pytest

from tests.sample import make_sample

pytestmark = pytest.mark.e2e


def test_verify_py_in_fresh_venv(tmp_path, uv_bin):
    s = make_sample(tmp_path)
    venv = tmp_path / "fresh-venv"
    subprocess.run([uv_bin, "venv", "--quiet", "--python", "3.12", str(venv)], check=True)
    py = venv / "bin" / "python"
    # Exactly the dependencies verify.py declares in its header.
    header = (s.bundle_dir / "verify.py").read_text(encoding="utf-8").split('"""')[1]
    assert 'pip install "cryptography>=44" "rfc3161-client>=1.0.6"' in header
    subprocess.run([uv_bin, "pip", "install", "--quiet", "--python", str(py),
                    "cryptography>=44", "rfc3161-client>=1.0.6"], check=True)
    # The fresh environment really lacks the app and its libraries.
    for mod in ("provenance_core", "app", "fastapi", "httpx", "opentimestamps"):
        r = subprocess.run([str(py), "-I", "-c", f"import {mod}"], capture_output=True)
        assert r.returncode != 0, mod
    work = tmp_path / "elsewhere"
    work.mkdir()
    for target in (s.bundle_dir, s.zip_path):
        out = subprocess.run(
            [str(py), "-I", str(s.bundle_dir / "verify.py"), str(target),
             "--tsa-root", str(s.bundle_dir / "certs" / "mock-tsa-root.pem")],
            cwd=work, capture_output=True, text=True, encoding="utf-8",
        )
        assert out.returncode == 0, out.stdout + out.stderr
        assert "Result: OK" in out.stdout
    out = subprocess.run(
        [str(py), "-I", str(s.bundle_dir / "verify.py"), str(s.bundle_dir), "--json",
         "--tsa-root", str(s.bundle_dir / "certs" / "mock-tsa-root.pem")],
        cwd=work, capture_output=True, text=True, encoding="utf-8",
    )
    data = json.loads(out.stdout)
    assert data["ok"] is True
    assert {r["status"] for r in data["records"]} == {"pass_btc_pending"}
    assert all(r["third_party_timestamp"]["state"] == "verified" for r in data["records"])


def test_manual_verify_md_commands(tmp_path):
    openssl = shutil.which("openssl")
    if openssl is None or shutil.which("sha256sum") is None:
        pytest.skip("needs openssl and sha256sum")
    s = make_sample(tmp_path)
    d = s.bundle_dir
    verify_md = (d / "VERIFY.md").read_text(encoding="utf-8")
    assert "openssl ts -verify -data manifests/<id>.json -in proofs/<id>.tsr" in verify_md
    rid = s.ids["exp"]

    def sha(rel: str) -> str:
        out = subprocess.run(["sha256sum", rel], cwd=d, capture_output=True, text=True, encoding="utf-8", check=True)
        return out.stdout.split()[0]

    payload = json.loads((d / f"payloads/{rid}.json").read_bytes())
    manifest = json.loads((d / f"manifests/{rid}.json").read_bytes())
    assert sha(f"content/{rid}/body.md") == payload["content"]["body"]["sha256"]
    assert sha(f"content/{rid}/files/run1.csv") == payload["content"]["files"][0]["sha256"]
    assert sha(f"payloads/{rid}.json") == manifest["payload_sha256"]
    assert sha(f"manifests/{rid}.json") == rid

    # 2. signature (OpenSSL 3)
    if shutil.which("xxd"):
        subprocess.run(f"echo -n {rid} | xxd -r -p > id.bin", shell=True, cwd=d, check=True)
    else:  # same bytes as the VERIFY.md xxd step
        (d / "id.bin").write_bytes(bytes.fromhex(rid))
    assert (d / "id.bin").read_bytes() == bytes.fromhex(rid)
    out = subprocess.run([openssl, "pkeyutl", "-verify", "-pubin", "-inkey", "identity/public_key.pem", "-rawin",
                          "-in", "id.bin", "-sigfile", f"signatures/{rid}.sig"], cwd=d, capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0 and "Signature Verified Successfully" in out.stdout, out.stdout + out.stderr

    # 3. third-party timestamp — this bundle is from the mock TSA, so use its root (VERIFY.md says so)
    assert "Test bundle" in verify_md
    out = subprocess.run([openssl, "ts", "-verify", "-data", f"manifests/{rid}.json", "-in", f"proofs/{rid}.tsr",
                          "-CAfile", "certs/mock-tsa-root.pem", "-untrusted", "certs/mock-tsa.pem"],
                         cwd=d, capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0 and "Verification: OK" in out.stdout, out.stdout + out.stderr
    # ...and the FreeTSA root rightly refuses a mock token.
    out = subprocess.run([openssl, "ts", "-verify", "-data", f"manifests/{rid}.json", "-in", f"proofs/{rid}.tsr",
                          "-CAfile", "certs/freetsa-cacert.pem", "-untrusted", "certs/freetsa-tsa.crt"],
                         cwd=d, capture_output=True, text=True, encoding="utf-8")
    assert out.returncode != 0
    # A tampered manifest fails the manual timestamp check too.
    (d / "tampered.json").write_bytes((d / f"manifests/{rid}.json").read_bytes() + b" ")
    out = subprocess.run([openssl, "ts", "-verify", "-data", "tampered.json", "-in", f"proofs/{rid}.tsr",
                          "-CAfile", "certs/mock-tsa-root.pem", "-untrusted", "certs/mock-tsa.pem"],
                         cwd=d, capture_output=True, text=True, encoding="utf-8")
    assert out.returncode != 0
    assert hashlib.sha256((d / f"manifests/{rid}.json").read_bytes()).hexdigest() == rid
