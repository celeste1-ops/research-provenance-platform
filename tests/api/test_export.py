"""AC-17: the three disclosure levels export the right files; chain.json covers 0..max."""

import json
import subprocess
import sys
import zipfile

from cryptography import x509
from cryptography.hazmat.primitives import hashes

from provenance_core.bundle import load_bundle
from provenance_core.certs import DIGICERT_ROOT_SHA256, FREETSA_ROOT_SHA256
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
                  "certs/digicert-trusted-root-g4.pem", "certs/mock-tsa-root.pem"):
        assert fixed in names, fixed
    meta = json.loads(s.files["bundle.json"])
    # Both built-in time-stamping roots, with the fingerprints to compare by hand (D-045).
    assert meta["trusted_tsa_roots"] == {"freetsa-cacert.pem": FREETSA_ROOT_SHA256,
                                         "digicert-trusted-root-g4.pem": DIGICERT_ROOT_SHA256}
    for name, sha in meta["trusted_tsa_roots"].items():
        cert = x509.load_pem_x509_certificate(s.files[f"certs/{name}"])
        assert cert.fingerprint(hashes.SHA256()).hex() == sha
        assert sha in s.files["VERIFY.md"].decode()
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
                         capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0, out.stdout + out.stderr
    assert "Result: OK" in out.stdout
    assert f"Built-in trust root: FreeTSA Root CA, SHA-256 {FREETSA_ROOT_SHA256}" in out.stdout
    assert f"Built-in trust root: DigiCert Trusted Root G4, SHA-256 {DIGICERT_ROOT_SHA256}" in out.stdout
    # Without trusting the mock root, the mock timestamps are (correctly) untrusted.
    out = subprocess.run([sys.executable, "-I", str(s.bundle_dir / "verify.py"), str(s.zip_path)],
                         capture_output=True, text=True, encoding="utf-8")
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


def test_the_report_shows_what_was_shared_on_hover_and_says_why_not(tmp_path):
    """D-057: pointing at a step in report.html shows what it says (no script needed); a step whose
    content was not shared says so in plain words, and so does a file left out of the package."""
    s = make_sample(tmp_path)
    html = s.files["report.html"].decode()
    assert "<script" not in html.lower()  # still none
    ids = s.ids
    # A shared step: its text in the hover card, its file linked inside the package.
    assert 'class="peek-card"' in html and "run1.csv" in html
    assert f'href="content/{ids["exp"]}/files/run1.csv"' in html
    # A step shared as structure only: why its text is not there; its fingerprint-only note.
    assert "did not share what this step says" in html
    assert "secret draft wording" not in html
    # The DOI opens on the web; the graph's boxes carry the hover text too.
    assert 'href="https://doi.org/10.5281/zenodo.1"' in html
    assert "<title>Preprint\n" in html


def test_a_shared_picture_is_shown_in_the_report(tmp_path):
    from app.report.render import INLINE_IMAGE_BYTES, _image_data_uri

    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    assert _image_data_uri("figure.png", png).startswith("data:image/png;base64,")
    assert _image_data_uri("figure.svg", b"<svg/>").startswith("data:image/svg+xml;base64,")
    assert _image_data_uri("notes.docx", b"PK") is None  # not a picture
    assert _image_data_uri("huge.png", b"0" * (INLINE_IMAGE_BYTES + 1)) is None  # linked, not inlined
