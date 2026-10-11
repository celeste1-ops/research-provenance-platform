"""AC-06, AC-08, AC-12, AC-15, AC-16 through the HTTP API (MockProvider)."""

import sqlite3
import time

from provenance_core.records import NODE_TYPES, RELATION_TYPES


def _proofs(detail):
    ts = detail["verified"]["timestamps"]
    return ts["tsa"], ts["btc"]


def test_record_appears_with_confirmed_tsa_and_pending_btc_within_a_second(api):  # AC-08
    api.init()
    start = time.monotonic()
    out = api.entry("numerical experiment 1", "experiment", body="# run\nconverged\n")
    elapsed = time.monotonic() - start
    assert elapsed < 1.0
    tsa, btc = _proofs(out["detail"])
    assert tsa["state"] == "confirmed" and tsa["text"] == "Third-party timestamp: verified" and tsa["time"]
    assert btc["state"] == "pending" and btc["text"] == "Bitcoin anchor: pending" and btc["time"] is None
    assert out["detail"]["verified"]["earliest_verified"]["from"] == "Third-party timestamp"


def test_later_link_is_a_new_record_and_original_bytes_unchanged(api, ctx):  # AC-06
    api.init()
    a = api.entry("first formula", "idea")["id"]
    b = api.entry("revised model", "claim")["id"]
    con = sqlite3.connect(ctx.settings.db_path)
    before = con.execute("SELECT id, seq, manifest_bytes, payload_bytes, signature FROM records").fetchall()
    r = api.client.post("/api/links", json={"from": b, "to": a, "rel": "revises", "statement": "realised later"})
    assert r.status_code == 200, r.text
    link = r.json()
    after = con.execute("SELECT id, seq, manifest_bytes, payload_bytes, signature FROM records").fetchall()
    assert set(before) < set(after)  # old rows byte-identical, one new row
    new = [row for row in after if row not in before]
    assert len(new) == 1 and new[0][0] == link["id"] and new[0][1] == max(x[1] for x in before) + 1
    assert link["detail"]["kind"] == "link"
    tsa, btc = _proofs(link["detail"])
    assert tsa["state"] == "confirmed" and btc["state"] == "pending"
    v = api.client.get(f"/api/records/{link['id']}/verify").json()
    assert v["signature"] == "valid" and v["failure_codes"] == []
    graph = api.client.get("/api/graph").json()
    edge = next(e for e in graph["edges"] if e["origin"] == "link")
    assert edge["from"] == a and edge["to"] == b and edge["rel"] == "revises"
    assert edge["added"]["time"] == tsa["time"] and edge["added"]["verified"] is True
    assert edge["source_label"] == "author"
    con.close()


def test_withdrawn_link_shows_withdrawal_date(api):
    api.init()
    a = api.entry("a", "idea")["id"]
    b = api.entry("b", "idea", relations=[{"to": a, "rel": "uses"}])["id"]
    r = api.client.post("/api/links", json={"from": b, "to": a, "rel": "uses", "op": "withdraw"})
    assert r.status_code == 200, r.text
    edge = api.client.get("/api/graph").json()["edges"][0]
    assert edge["active"] is False and edge["withdrawn"]["time"]


def test_types_relations_and_bad_references(api):  # AC-12
    api.init()
    ids = {}
    for t in NODE_TYPES:
        ids[t] = api.entry(f"a {t}", t)["id"]
    assert len(ids) == 9
    api.entry("bad", "simulation", expect=400)
    prev = ids["idea"]
    for rel in RELATION_TYPES:
        out = api.entry(f"uses {rel}", "note", relations=[{"to": prev, "rel": rel}])
        assert out["detail"]["author"]["items"][-1]["rel"] == rel
    api.entry("bad rel", "note", relations=[{"to": prev, "rel": "inspired_by"}], expect=400)
    api.entry("missing", "note", relations=[{"to": "f" * 64, "rel": "uses"}], expect=400)
    api.entry("not an id", "note", relations=[{"to": "xyz", "rel": "uses"}], expect=400)
    # A relation must point from a newer record to an older one.
    r = api.client.post("/api/links", json={"from": ids["idea"], "to": ids["publication"], "rel": "uses"})
    assert r.status_code == 400
    r = api.client.post("/api/links", json={"from": ids["publication"], "to": "e" * 64, "rel": "uses"})
    assert r.status_code == 400
    genesis = api.client.get("/api/timeline").json()[0]["id"]
    r = api.client.post("/api/links", json={"from": ids["publication"], "to": genesis, "rel": "uses"})
    assert r.status_code == 400


def test_import_claimed_date_is_author_statement(api):  # AC-15
    api.init()
    out = api.entry(
        "old notebook page",
        "note",
        body="notes from last year",
        import_claimed_date="2025-11",
        import_level="L1",
    )
    d = out["detail"]
    claimed = [i for i in d["author"]["items"] if i["field"] == "claimed_date"]
    assert claimed and claimed[0]["level"] == "L1" and "2025-11" in claimed[0]["text"]
    assert "author statement only" in claimed[0]["note"]
    assert "2025-11" not in str(d["verified"])
    tsa, _ = _proofs(d)
    assert d["verified"]["earliest_verified"]["time"] == tsa["time"]  # import time, not the claim
    out2 = api.entry(
        "preprint", "publication", doi="10.5281/zenodo.1234567",
        import_claimed_date="2025-12-03", import_level="L2", import_references=["https://doi.org/10.5281/zenodo.1234567"],
    )
    c2 = [i for i in out2["detail"]["author"]["items"] if i["field"] == "claimed_date"][0]
    assert c2["level"] == "L2" and "third-party reference" in c2["note"]
    assert out2["detail"]["verified"]["external"]["evidence_level"] == "L2 (third-party reference)"
    api.entry("L2 without reference", "note", import_claimed_date="2025", import_level="L2", expect=400)
    api.entry("bad date", "note", import_claimed_date="2025-13", expect=400)


def test_code_reference_without_archive_is_flagged(api):  # AC-16
    api.init()
    out = api.entry("solver v1", "code", repo_url="https://github.com/example/fsf", commit="0123abcdef")
    d = out["detail"]
    assert d["verified"]["external"]["note"] == "External reference, code content not saved"
    tsa, btc = _proofs(d)
    assert tsa["state"] == "confirmed" and btc["state"] == "pending"
    # No git commit date is ever shown as verified; only proof times are.
    verified_times = {tsa["time"], btc["time"]} - {None}
    assert d["verified"]["earliest_verified"]["time"] in verified_times
    assert "commit date" not in str(d["verified"]).lower()
    with_archive = api.entry(
        "solver v2", "code", repo_url="https://github.com/example/fsf", commit="fedcba9876",
        files=[("fsf-fedcba9.tar", b"tar bytes")],
    )
    assert with_archive["detail"]["verified"]["external"]["note"].startswith("Code archive attached")
    api.entry("bad commit", "code", repo_url="https://x", commit="not-hex", expect=400)
    api.entry("half", "code", repo_url="https://x", expect=400)


def test_files_body_and_content_endpoint(api):
    api.init()
    out = api.entry(
        "experiment", "experiment", body="line1\r\nline2\r\n",
        files=[("../../etc/run1.csv", b"t,x\n0,1\n"), ("run1.csv", b"other")],
    )
    names = sorted(f["name"] for f in out["detail"]["files"] if f["role"] == "file")
    assert names == ["run1 (2).csv", "run1.csv"]
    rid = out["id"]
    body = api.client.get(f"/api/records/{rid}/content")
    assert body.content == b"line1\nline2\n"
    att = api.client.get(f"/api/records/{rid}/content", params={"file": "run1.csv"})
    assert att.content == b"t,x\n0,1\n"
    assert att.headers["content-disposition"].startswith("attachment")
    assert "sandbox" in att.headers["content-security-policy"]


def test_milestone_statement_retraction_and_replay(api):
    api.init()
    a = api.entry("a", "idea")["id"]
    assert api.client.post("/api/milestones", json={"target": a}).status_code == 200
    assert api.client.post("/api/milestones", json={"target": a}).status_code == 400  # already set
    s = api.client.post("/api/statements", json={"target": a, "text": "clarification"})
    assert s.status_code == 200
    assert api.client.post("/api/retractions", json={"target": a, "reason": "wrong setup"}).status_code == 200
    assert api.client.post("/api/retractions", json={"target": a, "reason": "again"}).status_code == 400
    d = api.client.get(f"/api/records/{a}").json()
    assert d["retracted"] is True
    kinds = [x["kind"] for x in d["later"]["items"]]
    assert kinds == ["milestone", "statement", "retraction"]
    node = api.client.get("/api/graph").json()["nodes"][0]
    assert node["milestone"] is True and node["retracted"] is True
    report = api.client.post("/api/verify/all").json()
    assert report["ok"] is True
    assert {r["status"] for r in report["records"]} == {"pass_btc_pending"}


def test_key_backup_export_is_password_protected(api):
    import pytest as _pytest

    from provenance_core.signing import KeyBackupError, load_private_key_encrypted, public_key_hex

    api.init()
    assert api.client.get("/api/status").json()["key_backup_done"] is False
    assert api.client.post("/api/identity/export", json={"password": "short"}).status_code == 422
    r = api.client.post("/api/identity/export", json={"password": "a long password"})
    assert r.status_code == 200 and b"ENCRYPTED PRIVATE KEY" in r.content
    key = load_private_key_encrypted(r.content, "a long password")
    genesis = api.client.get("/api/timeline").json()[0]["id"]
    pub = api.client.get(f"/api/records/{genesis}").json()["verified"]["public_key"]
    assert public_key_hex(key.public_key()) == pub
    with _pytest.raises(KeyBackupError):
        load_private_key_encrypted(r.content, "wrong password!")
    assert api.client.get("/api/status").json()["key_backup_done"] is True
