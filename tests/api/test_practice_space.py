"""Practice space (DECISIONS D-038): a separate installation that never touches the real record."""

from __future__ import annotations

import pytest

P = {"X-RPROV-Space": "practice"}


def _practice_entry(client, title="Trying it out", body="scratch text"):
    pid = client.get("/api/projects", headers=P).json()[0]["id"]
    r = client.post("/api/entries", headers=P,
                    data={"project_id": pid, "node_type": "idea", "title": title, "body": body})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_practice_is_a_separate_installation(api, client, ctx):
    api.init(author="Ada")
    api.entry("Real step")
    real_before = ctx.ledger.record_count()

    st = client.get("/api/status", headers=P).json()
    assert st["space"] == "practice" and st["initialized"]
    assert st["author_label"] == "Ada (practice)"
    assert st["installation"] != ctx.ledger.installation
    real_st = client.get("/api/status").json()
    assert st["public_key"] != real_st["public_key"]  # its own signing key
    assert st["data_dir"] == str(ctx.settings.data_dir / "practice") == real_st["practice_dir"]
    assert [p["title"] for p in client.get("/api/projects", headers=P).json()] == ["Practice project"]

    rid = _practice_entry(client)
    assert ctx.ledger.record_count() == real_before  # nothing went into the real record
    assert client.get(f"/api/records/{rid}").status_code == 404
    assert client.get(f"/api/records/{rid}", headers=P).status_code == 200
    # Plain links (attachments) name the space in the query string.
    assert client.get(f"/api/records/{rid}/content?space=practice").text == "scratch text"
    titles = [n["title"] for n in client.get("/api/graph", headers=P).json()["nodes"]]
    assert titles == ["Trying it out"]
    assert [n["title"] for n in client.get("/api/graph").json()["nodes"]] == ["Real step"]
    assert client.post("/api/verify/all", headers=P).json()["ok"]


def test_practice_works_before_the_real_record_is_set_up(client, ctx):
    st = client.get("/api/status", headers=P).json()
    assert st["initialized"] and st["author_label"] == "Practice"
    _practice_entry(client)
    assert not ctx.ledger.initialized()
    assert client.get("/api/status").json()["initialized"] is False


def test_unknown_space_is_refused(client):
    assert client.get("/api/status", headers={"X-RPROV-Space": "other"}).status_code == 400


def test_practice_is_never_backed_up(api, client, ctx, tmp_path, monkeypatch):
    import app.services.backup as backup

    monkeypatch.setattr(backup, "SCRYPT_N", 2**10)
    ctx.autobackup.debounce = 0
    api.init()
    folder = tmp_path / "backups"
    folder.mkdir()
    assert client.post("/api/backup/settings", json={"location": str(folder), "password": "pw-123456"}).status_code == 200
    first = sorted(folder.iterdir())
    _practice_entry(client)
    assert sorted(folder.iterdir()) == first  # a practice step does not trigger a backup
    # Backup settings always concern the real record, whichever space the page is in.
    st = client.get("/api/backup/status", headers=P).json()
    assert st["configured"] and st["location"] == str(folder)
    api.entry("A real step")
    assert len(list(folder.iterdir())) == len(first) + 1


def test_start_practice_over(api, client, ctx):
    api.init()
    api.entry("Real")
    real_count = ctx.ledger.record_count()
    _practice_entry(client)
    old = client.get("/api/status", headers=P).json()["installation"]
    old_key = ctx.keystore.load(old)
    assert old_key is not None

    r = client.post("/api/practice/reset", json={})
    assert r.status_code == 200
    st = client.get("/api/status", headers=P).json()
    assert st["installation"] != old and st["entry_count"] == 0
    assert ctx.keystore.load(old) is None  # the old practice key is gone
    assert ctx.ledger.record_count() == real_count and ctx.keystore.load(ctx.ledger.installation) is not None

    r = client.post("/api/practice/reset", json={"sample": True})
    assert r.status_code == 200
    st = client.get("/api/status", headers=P).json()
    assert st["entry_count"] == 14 and "fictional" in st["author_label"]
    assert ctx.ledger.record_count() == real_count


def test_reset_needs_the_session_token(client):
    r = client.post("/api/practice/reset", json={}, headers={"X-RPROV-Token": "wrong"})
    assert r.status_code == 403


@pytest.mark.parametrize("force", [False, True])
def test_stamp_checks_cover_both_spaces(api, client, ctx, force):
    api.init()
    _practice_entry(client)
    spaces = client.app.state.spaces
    assert len(spaces.anchor_services()) == 2
    stats = spaces.refresh(force=force)
    assert set(stats) >= {"submitted", "upgraded", "still_pending"}
