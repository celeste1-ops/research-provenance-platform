"""AC-19: one tampered bundle per failure code; the generated verify.py exits
non-zero and prints the matching code.

Each case copies the untampered sample bundle and changes it the way an attacker
(or an accident) would, then runs ``verify.py`` as a separate process.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from provenance_core.providers.mock import build_mock_tsr
from provenance_core.verify import FAILURE_CODES
from tests.sample import make_sample

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "ots"


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    return make_sample(tmp_path_factory.mktemp("tamper-sample"))


def _rid(s, key):
    return s.ids[key]


def _chain(d: Path) -> list[str]:
    return json.loads((d / "chain.json").read_text(encoding="utf-8"))["ids"]


def _edit_json(path: Path, fn, canonical: bool = True) -> None:
    obj = json.loads(path.read_bytes())
    fn(obj)
    if canonical:
        from provenance_core.jcs import canonicalize

        path.write_bytes(canonicalize(obj))
    else:
        path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def _attacker_tsr(record_id: str) -> bytes:
    """A well-formed RFC 3161 token for the right digest, from a TSA nobody trusts."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Totally Legit TSA")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(7).not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=365))
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.TIME_STAMPING]), critical=True)
        .sign(key, hashes.SHA256())
    )
    return build_mock_tsr(bytes.fromhex(record_id), datetime(2020, 1, 1, tzinfo=UTC), 1, cert=cert, key=key)


def tamper_content(d, s):  # 改正文
    p = d / f"content/{_rid(s, 'exp')}/body.md"
    p.write_bytes(p.read_bytes().replace(b"40 steps", b"4 steps"))


def tamper_payload(d, s):  # 改载荷
    _edit_json(d / f"payloads/{_rid(s, 'claim')}.json", lambda o: o.update(title="A better model"))


def tamper_manifest(d, s):  # 改清单
    _edit_json(d / f"manifests/{_rid(s, 'claim')}.json", lambda o: o.update(payload_sha256="0" * 64))


def tamper_non_canonical(d, s):
    _edit_json(d / f"payloads/{_rid(s, 'idea')}.json", lambda o: None, canonical=False)


def tamper_schema(d, s):
    _edit_json(d / f"payloads/{_rid(s, 'idea')}.json", lambda o: o.update(node_type=""))


def tamper_signature(d, s):  # 改签名
    p = d / f"signatures/{_rid(s, 'exp')}.sig"
    sig = bytearray(p.read_bytes())
    sig[10] ^= 0x01
    p.write_bytes(bytes(sig))


def tamper_tsr_swap(d, s):  # 替换 .tsr
    shutil.copy(d / f"proofs/{_rid(s, 'idea')}.tsr", d / f"proofs/{_rid(s, 'exp')}.tsr")


def tamper_tsr_corrupt(d, s):
    p = d / f"proofs/{_rid(s, 'exp')}.tsr"
    data = bytearray(p.read_bytes())
    data[-40] ^= 0xFF  # inside the RSA signature
    p.write_bytes(bytes(data))


def tamper_tsr_untrusted(d, s):
    rid = _rid(s, "exp")
    (d / f"proofs/{rid}.tsr").write_bytes(_attacker_tsr(rid))


def tamper_btc(d, s):
    shutil.copy(FIX / "hello-world.txt.ots", d / f"manifests/{_rid(s, 'exp')}.json.ots")


def tamper_delete_manifest(d, s):  # 删中间一份清单
    (d / f"manifests/{_rid(s, 'claim')}.json").unlink()


def tamper_swap_seq(d, s):  # 调换两条记录的 seq
    chain = _chain(d)
    i, j = chain.index(_rid(s, "exp")), chain.index(_rid(s, "claim"))
    chain[i], chain[j] = chain[j], chain[i]
    (d / "chain.json").write_text(json.dumps({"format": "rprov.bundle/1", "ids": chain}), encoding="utf-8")


def tamper_ref_missing(d, s):  # 引用不存在的记录
    def fn(o):
        o["relations"][0]["to"] = "f" * 64

    _edit_json(d / f"payloads/{_rid(s, 'claim')}.json", fn)


def tamper_ref_not_earlier(d, s):
    later = _rid(s, "paper")

    def fn(o):
        o["relations"][0]["to"] = later

    _edit_json(d / f"payloads/{_rid(s, 'exp')}.json", fn)


CASES = {
    "CONTENT_MISMATCH": tamper_content,
    "PAYLOAD_HASH_MISMATCH": tamper_payload,
    "MANIFEST_HASH_MISMATCH": tamper_manifest,
    "NON_CANONICAL": tamper_non_canonical,
    "SCHEMA_INVALID": tamper_schema,
    "SIGNATURE_INVALID": tamper_signature,
    "TSA_IMPRINT_MISMATCH": tamper_tsr_swap,
    "TSA_INVALID": tamper_tsr_corrupt,
    "TSA_CHAIN_UNTRUSTED": tamper_tsr_untrusted,
    "BTC_INVALID": tamper_btc,
    "LOG_GAP": tamper_delete_manifest,
    "LOG_PREV_MISMATCH": tamper_swap_seq,
    "REF_MISSING": tamper_ref_missing,
    "REF_NOT_EARLIER": tamper_ref_not_earlier,
}


def test_every_failure_code_has_a_tamper_case():
    assert set(CASES) == set(FAILURE_CODES)


def _run(bundle: Path, verify_py: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-I", str(verify_py), str(bundle), "--tsa-root", str(bundle / "certs/mock-tsa-root.pem"),
         *extra],
        capture_output=True, text=True, encoding="utf-8",
    )


def test_untampered_sample_passes(sample):
    out = _run(sample.bundle_dir, sample.bundle_dir / "verify.py")
    assert out.returncode == 0, out.stdout


@pytest.mark.parametrize("code", sorted(CASES))
def test_tampered_bundle_fails_with_code(code, sample, tmp_path):
    bundle = tmp_path / "bundle"
    shutil.copytree(sample.bundle_dir, bundle)
    verify_py = tmp_path / "verify.py"  # keep the checker outside the tampered files
    shutil.copy(sample.bundle_dir / "verify.py", verify_py)
    CASES[code](bundle, sample)
    out = _run(bundle, verify_py)
    assert out.returncode == 1, out.stdout + out.stderr
    assert code in out.stdout, out.stdout
    data = json.loads(_run(bundle, verify_py, "--json").stdout)
    assert data["ok"] is False
    assert any(code in r["failure_codes"] for r in data["records"]) or any(
        i["code"] == code for i in data["log_issues"]
    )


def test_tampered_zip_fails_too(sample, tmp_path):
    import zipfile

    src = zipfile.ZipFile(sample.zip_path)
    target = tmp_path / "tampered.zip"
    rid = sample.ids["exp"]
    with zipfile.ZipFile(target, "w") as out:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename == f"content/{rid}/body.md":
                data = data.replace(b"converged", b"diverged")
            out.writestr(info, data)
    res = subprocess.run([sys.executable, "-I", str(sample.bundle_dir / "verify.py"), str(target),
                          "--tsa-root", str(sample.bundle_dir / "certs/mock-tsa-root.pem")],
                         capture_output=True, text=True, encoding="utf-8")
    assert res.returncode == 1 and "CONTENT_MISMATCH" in res.stdout
