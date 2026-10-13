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

    assert client.get("/api/status", headers=P).json()["sample"] is None  # practice never holds the sample


E = {"X-RPROV-Space": "example"}


def test_the_example_is_a_space_of_its_own(api, client, ctx):
    """D-064: the FSF sample in a third installation, loaded when first opened; practice and the real
    record are never touched by it."""
    api.init(author="Ada")
    api.entry("Real step")
    real = [r.id for r in ctx.ledger.records()]
    practice_step = _practice_entry(client, "My own try")
    assert not (ctx.settings.data_dir / "example").exists()

    r = client.post("/api/example/open", json={"lang": "en"})
    assert r.status_code == 200 and r.json() == {"space": "example", "record_count": r.json()["record_count"]}
    st = client.get("/api/status", headers=E).json()
    assert st["space"] == "example" and st["entry_count"] == 32 and "fictional" in st["author_label"]
    assert st["data_dir"] == str(ctx.settings.data_dir / "example") == client.get("/api/status").json()["example_dir"]
    installations = {st["installation"], client.get("/api/status", headers=P).json()["installation"],
                     ctx.ledger.installation}
    assert len(installations) == 3  # three keys, three installations
    # The example remembers it holds the sample, for the tour (D-059); the other spaces do not.
    assert st["sample"]["lang"] == "en" and set(st["sample"]["projects"]) == {"main", "side"}
    assert client.get("/api/status").json()["sample"] is None
    assert client.get("/api/status", headers=P).json()["sample"] is None
    # Opening it again changes nothing; reloading it starts it afresh, in the language asked for.
    first = st["installation"]
    client.post("/api/example/open", json={"lang": "zh"})
    assert client.get("/api/status", headers=E).json()["installation"] == first
    client.post("/api/example/reset", json={"lang": "zh"})
    st = client.get("/api/status", headers=E).json()
    assert st["installation"] != first and st["sample"]["lang"] == "zh" and st["author_label"] == "示例作者（虚构）"
    titles = [p["title"] for p in client.get("/api/projects", headers=E).json()]
    assert sorted(titles) == sorted(["FSF（示例）", "流道装置（示例）"])
    assert ctx.keystore.load(first) is None  # the old example key is gone

    assert [r.id for r in ctx.ledger.records()] == real
    assert client.get(f"/api/records/{practice_step}", headers=P).status_code == 200
    assert [n["title"] for n in client.get("/api/graph", headers=P).json()["nodes"]] == ["My own try"]
    spaces = client.app.state.spaces
    assert len(spaces.anchor_services()) == 3  # stamps are checked in every space


def test_a_practice_space_holding_the_old_sample_becomes_the_example(tmp_path):
    """Up to v0.6.1 the sample was loaded into practice (D-059, D-062): on the first start of the new
    version that practice space becomes the example, and practice starts empty."""
    from app.services.spaces import Spaces
    from tests.conftest import make_ctx

    ctx = make_ctx(tmp_path)
    ctx.ledger.init_identity("Ada")
    old = Spaces(ctx)
    old_practice = old.practice(auto_init=False)
    from app.demo import load_sample

    info = load_sample(old_practice, "en")
    (old.practice_dir / "sample.json").write_text(__import__("json").dumps(info), encoding="utf-8")
    installation = old_practice.ledger.installation
    old.close()

    new = Spaces(ctx)
    assert not (ctx.settings.data_dir / "practice").exists()
    example = new.example()
    assert example.ledger.installation == installation and new.sample_info()["lang"] == "en"
    assert sum(1 for r in example.ledger.records() if r.kind == "entry") == 32
    practice = new.practice()
    assert sum(1 for r in practice.ledger.records() if r.kind == "entry") == 0
    new.close()
    ctx.close()


def test_reset_needs_the_session_token(client):
    r = client.post("/api/practice/reset", json={}, headers={"X-RPROV-Token": "wrong"})
    assert r.status_code == 403


@pytest.mark.parametrize("force", [False, True])
def test_stamp_checks_cover_both_spaces(api, client, ctx, force):
    api.init()
    _practice_entry(client)
    spaces = client.app.state.spaces
    assert len(spaces.anchor_services()) == 2  # the real record and practice: no example opened yet
    stats = spaces.refresh(force=force)
    assert set(stats) >= {"submitted", "upgraded", "still_pending"}


def test_start_over_reports_a_folder_it_cannot_delete(api, client, ctx, monkeypatch):
    """Windows keeps files in use undeletable for a moment; never silently keep old practice data."""
    import app.services.spaces as spaces_mod

    _practice_entry(client)
    monkeypatch.setattr(spaces_mod.shutil, "rmtree", lambda *a, **k: None)  # nothing gets deleted
    monkeypatch.setattr(spaces_mod.time, "sleep", lambda s: None)
    r = client.post("/api/practice/reset", json={})
    assert r.status_code == 409 and "still in use" in r.text
