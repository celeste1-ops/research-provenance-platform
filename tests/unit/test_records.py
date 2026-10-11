"""AC-01 (vectors), AC-02, AC-03, AC-04 and record schema rules."""

import hashlib
import json
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from provenance_core import records as R
from provenance_core.jcs import JcsError
from provenance_core.signing import private_key_from_raw, public_key_hex, sign_record_id

VECTORS = Path(__file__).resolve().parent.parent / "vectors" / "records_v1.json"
INST = str(uuid.uuid4())
PROJ = str(uuid.uuid4())


def _entry(**kw):
    base = dict(project_id=PROJ, project_title="FSF", node_type="note", title="t")
    base.update(kw)
    return R.entry_payload(**base)


def test_vector_ids_never_change():
    doc = json.loads(VECTORS.read_text(encoding="utf-8"))
    key = private_key_from_raw(bytes.fromhex(doc["ed25519_seed_hex"]))
    prev = None
    for v in doc["records"]:
        mb, pb, rid = R.encode_record(v["kind"], doc["installation"], v["seq"], prev, v["payload"])
        assert mb.decode() == v["manifest_jcs"]
        assert pb.decode() == v["payload_jcs"]
        assert rid == v["record_id"]
        assert R.sha256_hex(mb) == v["record_id"]
        assert sign_record_id(key, rid).hex() == v["signature"]
        prev = rid
    assert doc["records"][0]["payload"]["public_key"] == public_key_hex(key.public_key())
    assert R.sha256_hex(R.normalize_text(doc["body_text_crlf"])) == doc["body_sha256"]


def test_float_in_payload_fails_to_build():  # AC-02
    payload = _entry()
    payload["ext"] = {"score": 0.5}
    with pytest.raises(JcsError):
        R.encode_record("entry", INST, 1, "a" * 64, payload)


def test_same_content_twice_gives_different_ids_same_body_hash():  # AC-03
    body = R.normalize_text("same text")
    desc = R.file_descriptor(body, "text/markdown")
    p1 = _entry(content={"body": desc, "files": []}, local_time="2026-10-12T14:00:00Z")
    p2 = _entry(content={"body": desc, "files": []}, local_time="2026-10-12T14:00:00Z")
    _, _, id1 = R.encode_record("entry", INST, 1, "a" * 64, p1)
    _, _, id2 = R.encode_record("entry", INST, 1, "a" * 64, p2)
    assert id1 != id2  # different 32-byte nonces
    assert p1["content"]["body"]["sha256"] == p2["content"]["body"]["sha256"]


def test_crlf_and_lf_give_same_body_hash(tmp_path):  # AC-04
    lf = R.normalize_text("line one\nline two\n")
    crlf = R.normalize_text("line one\r\nline two\r\n")
    cr = R.normalize_text(b"line one\rline two\r")
    assert lf == crlf == cr
    exported = tmp_path / "body.md"
    exported.write_bytes(crlf)
    if shutil.which("sha256sum"):  # an independent tool where there is one (not on stock Windows)
        # Relative name: GNU sha256sum escapes backslashes in Windows paths (and marks the line with "\").
        out = subprocess.run(["sha256sum", exported.name], cwd=tmp_path, capture_output=True, text=True,
                             encoding="utf-8", check=True)
        digest = out.stdout.split()[0]
    else:
        digest = hashlib.sha256(exported.read_bytes()).hexdigest()
    assert digest == R.sha256_hex(lf)


def test_schema_rejects_bad_payloads():
    assert R.validate_payload("entry", _entry(title=" ")) != []
    bad = _entry()
    bad["extra"] = 1
    assert R.validate_payload("entry", bad) != []
    assert R.validate_payload("nope", {}) != []
    imp = _entry(import_info={"claimed_date": "2025-13", "precision": "month", "level": "L1", "references": []})
    assert R.validate_payload("entry", imp) != []
    ok = _entry(import_info={"claimed_date": "2025-11", "precision": "month", "level": "L2", "references": ["doi:x"]})
    assert R.validate_payload("entry", ok) == []
    assert R.validate_payload("entry", _entry(external={"repo_url": "https://x", "commit": "abc1234"})) == []
    assert R.validate_payload("entry", _entry(external={"repo_url": "https://x", "commit": "ZZZ"})) != []
    assert R.validate_payload("link", R.link_payload("a" * 64, "b" * 64, "uses", op="remove")) != []


def test_unknown_node_type_and_rel_are_valid_for_verifiers():
    # PRD §18: new node types and relation kinds may be added later.
    p = _entry(node_type="simulation", relations=[{"to": "a" * 64, "rel": "inspired_by"}])
    assert R.validate_payload("entry", p) == []


def test_manifest_rules():
    pb = b"{}"
    assert R.validate_manifest(R.build_manifest("genesis", INST, 0, None, pb)) == []
    assert R.validate_manifest(R.build_manifest("entry", INST, 0, None, pb)) != []
    assert R.validate_manifest(R.build_manifest("genesis", INST, 3, "a" * 64, pb)) != []
    assert R.validate_manifest(R.build_manifest("entry", INST, 3, None, pb)) != []
    assert R.validate_manifest(R.build_manifest("entry", "not-a-uuid", 3, "a" * 64, pb)) != []


def test_safe_file_names():
    assert R.safe_file_name("../../etc/passwd") == "passwd"
    assert R.safe_file_name("..\\..\\boot.ini") == "boot.ini"
    assert R.safe_file_name(".hidden") == "hidden"
    assert R.safe_file_name("") == "file"
    assert R.is_safe_file_name("run1.csv")
    assert not R.is_safe_file_name("a/b.csv")
    assert not R.is_safe_file_name("..")
