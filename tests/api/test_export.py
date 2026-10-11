"""AC-17: the three disclosure levels export the right files; chain.json covers 0..max."""

import json
import subprocess
import sys
import zipfile

from provenance_core.bundle import load_bundle
from provenance_core.providers.mock import mock_tsa_root
from provenance_core.verify import verify_log
from tests.sample import make_sample


def _names(files):
    return set(files)


def test_disclosure_levels_contain_the_right_files(tmp_path):
    s = make_sample(tmp_path)
    names = _names(s.files)
    ids = s.ids
    chain = json.loads(s.files["chain.json"])["ids"]
    for rid in chain:  # every chain record: manifest, signature, proof
        assert f"manifests/{rid}.json" in names
        assert f"signatures/{rid}.sig" in names
        assert f"proofs/{rid}.tsr" in names
        assert f"manifests/{rid}.json.ots" in names
    # full: manifest, payload, content, proofs, signature
    for key in ("idea", "exp"):
        rid = ids[key]
        assert f"payloads/{rid}.json" in names and f"content/{rid}/body.md" in names
    assert f"content/{ids['exp']}/files/run1.csv" in names
    # structure: payload but no content
    rid = ids["claim"]
    assert f"payloads/{rid}.json" in names
    assert not any(n.startswith(f"content/{rid}/") for n in names)
    assert b"secret draft wording" not in b"".join(s.files.values())
    # existence only: no payload, no content
    rid = ids["old"]
    assert f"payloads/{rid}.json" not in names and not any(n.startswith(f"content/{rid}/") for n in names)
    assert b"Old notebook" not in s.files["report.html"]
    # genesis payload always present (public key)
    assert f"payloads/{ids['genesis']}.json" in names
    for fixed in ("report.html", "bundle.json", "chain.json", "VERIFY.md", "verify.py",
                  "identity/public_key.pem", "certs/freetsa-cacert.pem", "certs/freetsa-tsa.crt",
                  "certs/mock-tsa-root.pem"):
        assert fixed in names, fixed
    meta = json.loads(s.files["bundle.json"])
    assert meta["format"] == "rprov.bundle/1"
    assert {r["id"]: r["disclosure"] for r in meta["records"]}[ids["old"]] == "existence"


def test_chain_covers_seq_zero_to_highest_selected(tmp_path):
    s = make_sample(tmp_path)
    rows = s.ctx.ledger.records()
    chain = json.loads(s.files["chain.json"])["ids"]
    assert chain == [r.id for r in rows]  # paper (the last record) is selected
    # Selecting only an early record exports the prefix up to it — and nothing later.
    from app.services.export import build_bundle_files, plan_export

    plan = plan_export(s.ctx.ledger, "prefix", {s.ids["exp"]: "full"})
    files = build_bundle_files(s.ctx.ledger, s.ctx.anchors, plan)
    chain2 = json.loads(files["chain.json"])["ids"]
    exp_seq = next(r.seq for r in rows if r.id == s.ids["exp"])
    assert chain2 == [r.id for r in rows if r.seq <= exp_seq]
    assert not any(s.ids["paper"] in n for n in files)


def test_bundle_verifies_from_dir_and_zip(tmp_path):
    s = make_sample(tmp_path)
    for path in (s.bundle_dir, s.zip_path):
        b = load_bundle(path)
        report = verify_log(b.chain_ids, b.materials, tsa_roots=[mock_tsa_root()], identity_pem=b.identity_pem)
        assert report.ok, report.failure_codes()
        disclosures = {r.record_id: r.disclosure for r in report.records}
        assert disclosures[s.ids["exp"]] == "full"
        assert disclosures[s.ids["claim"]] == "structure"
        assert disclosures[s.ids["old"]] == "existence"
    with zipfile.ZipFile(s.zip_path) as zf:
        assert zf.getinfo("verify.py").external_attr >> 16 == 0o755


def test_generated_verify_py_runs_in_repo_python(tmp_path):
    s = make_sample(tmp_path)
    out = subprocess.run([sys.executable, "-I", str(s.bundle_dir / "verify.py"), str(s.bundle_dir),
                          "--tsa-root", str(s.bundle_dir / "certs/mock-tsa-root.pem")],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "Result: OK" in out.stdout
    # Without trusting the mock root, the mock timestamps are (correctly) untrusted.
    out = subprocess.run([sys.executable, "-I", str(s.bundle_dir / "verify.py"), str(s.zip_path)],
                         capture_output=True, text=True)
    assert out.returncode == 1 and "TSA_CHAIN_UNTRUSTED" in out.stdout


def test_export_api_preview_and_download(api, client):
    api.init()
    a = api.entry("a", "idea", body="hello")["id"]
    b = api.entry("b", "claim", body="world", relations=[{"to": a, "rel": "revises"}])["id"]
    p = client.post("/api/export/preview", json={"title": "t", "records": {a: "full", b: "structure"}})
    assert p.status_code == 200, p.text
    prev = p.json()
    assert any("hashes" in w for w in prev["warnings"])
    assert any("chain.json" in w for w in prev["warnings"])
    by_id = {r["id"]: r for r in prev["records"]}
    assert any("full content" in v for v in by_id[a]["visible"])
    assert any("SHA-256 hashes" in v for v in by_id[b]["visible"])
    r = client.post("/api/export", json={"title": "t", "records": {a: "full", b: "structure"}})
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert "provenance-t-" in r.headers["content-disposition"]
    assert client.post("/api/export", json={"records": {a: "everything"}}).status_code == 400
