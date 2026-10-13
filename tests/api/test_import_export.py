"""D-060: notes folders and tables come in as steps (their dates as the author's claim only);
steps go out as a table; an evidence bundle goes into a git repository or a Zenodo draft."""

from __future__ import annotations

import csv
import io
import json
import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from app.services import importer, publish
from app.services.gitrepo import find_git
from provenance_core.jcs import parse_json_strict
from tests.gitutil import GitRepo

NEEDS_GIT = pytest.mark.skipif(find_git() is None, reason="git is not installed")


def payloads(ctx) -> list[dict]:
    return [{"id": r.id, **parse_json_strict(r.payload_bytes)} for r in ctx.ledger.records() if r.kind == "entry"]


def old_file(path: Path, text: str, day: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    t = time.mktime(time.strptime(day, "%Y-%m-%d"))
    os.utime(path, (t, t))


@pytest.fixture
def vault(tmp_path):
    """A small Obsidian-style notes folder."""
    v = tmp_path / "FSF vault"
    old_file(v / "Intuition.md", "---\ndate: 2025-09-14\ntags: [fsf]\n---\n# Flow speed levels off\n\nA hunch.\n",
             "2026-01-01")
    old_file(v / "Hypothesis H1.md", "---\ncreated: 2025-10-02\n---\nBuilds on [[Intuition]] and "
             "[the reading](notes/Reading.md).\n\n![[sketch.png]]\n", "2026-01-01")
    old_file(v / "notes" / "Reading.md", "Reading notes without a date in them.\n", "2025-09-20")
    (v / "attachments").mkdir()
    (v / "attachments" / "sketch.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 20)
    old_file(v / ".obsidian" / "workspace.md", "settings, not a note", "2025-01-01")
    return v


def test_a_notes_folder_comes_in_oldest_first_with_its_links(api, ctx, vault):
    api.init()
    r = api.client.post("/api/import/notes/inspect", json={"path": str(vault)})
    assert r.status_code == 200, r.text
    info = r.json()
    assert info["count"] == 3 and info["dated"] == 2  # the .obsidian folder is not notes
    assert [n["title"] for n in info["notes"]] == ["Flow speed levels off", "Reading", "Hypothesis H1"]
    assert [(n["date"], n["date_source"]) for n in info["notes"]] == [
        ("2025-09-14", "front matter"), ("2025-09-20", "file date"), ("2025-10-02", "front matter")]
    assert info["notes"][2]["links"] == 2 and info["notes"][2]["images"] == 1

    r = api.client.post("/api/import/notes", json={"path": str(vault), "project_id": api.project_id})
    assert r.status_code == 200 and r.json() == {"imported": 3}
    steps = payloads(ctx)
    assert [s["title"] for s in steps] == ["Flow speed levels off", "Reading", "Hypothesis H1"]
    # The dates are the author's claim (L1), never a verified time.
    assert [s["import"]["claimed_date"] for s in steps] == ["2025-09-14", "2025-09-20", "2025-10-02"]
    assert {s["import"]["level"] for s in steps} == {"L1"}
    assert steps[2]["relations"] == [{"to": steps[0]["id"], "rel": "uses"}, {"to": steps[1]["id"], "rel": "uses"}]
    assert [f.name for f in ctx.ledger.record_files(steps[2]["id"]) if f.role == "file"] == ["sketch.png"]
    assert "FSF vault" in steps[0]["author_statement"] and "Intuition.md" in steps[0]["author_statement"]
    body = next(f for f in ctx.ledger.record_files(steps[0]["id"]) if f.role == "body")
    assert ctx.ledger.blobs.get(body.sha256).decode() == "# Flow speed levels off\n\nA hunch."  # no front matter


def test_only_the_notes_chosen_come_in(api, ctx, vault):
    api.init()
    r = api.client.post("/api/import/notes", json={"path": str(vault), "project_id": api.project_id,
                                                   "selected": ["Hypothesis H1.md"]})
    assert r.json() == {"imported": 1}
    [step] = payloads(ctx)
    assert step["relations"] == []  # the notes it links to were not brought in


def test_a_folder_that_is_not_notes(api, tmp_path):
    api.init()
    (tmp_path / "empty").mkdir()
    r = api.client.post("/api/import/notes/inspect", json={"path": str(tmp_path / "empty")})
    assert r.status_code == 400 and "no Markdown notes" in r.json()["detail"]
    r = api.client.post("/api/import/notes/inspect", json={"path": "relative/path"})
    assert r.status_code == 400


TABLE = """title,type,date,text,builds on,key step
Flow speed levels off,idea,2025-09-14,A hunch,,
Saturation follows a power law,hypothesis,2025-10,,1,
Numerical experiment 1,实验,2025/11/2,Exponent about 1.3,2,yes
,note,,a row without a title,,
Odd one,banana,someday,,7,
"""


def test_a_table_comes_in_one_step_per_row(api, ctx):
    api.init()
    r = api.client.post("/api/import/table/inspect", files={"file": ("steps.csv", TABLE.encode(), "text/csv")})
    assert r.status_code == 200, r.text
    info = r.json()
    assert info["count"] == 4
    rows = info["rows"]
    assert [x["type"] for x in rows] == ["idea", "claim", "experiment", "note", "note"]
    assert rows[2]["date"] == "2025-11-02" and rows[2]["builds_on"] == [2] and rows[2]["key"]
    assert rows[3]["problems"] == ["no title: this row is left out"]
    assert any("unknown type" in p for p in rows[4]["problems"])
    assert any("could not be read" in p for p in rows[4]["problems"])
    assert any("not an earlier row" in p for p in rows[4]["problems"])
    r = api.client.post("/api/import/table/inspect", files={"file": ("steps.csv", TABLE.encode(), "text/csv")},
                        headers={"X-RPROV-Lang": "zh-CN"})
    assert r.json()["rows"][4]["problems"][0] == "不认识的类型“banana”：按笔记记录"

    r = api.client.post("/api/import/table", data={"project_id": api.project_id},
                        files={"file": ("steps.csv", TABLE.encode(), "text/csv")})
    assert r.status_code == 200 and r.json() == {"imported": 4}
    steps = payloads(ctx)
    assert [s["node_type"] for s in steps] == ["idea", "claim", "experiment", "note"]
    assert [s["import"] and s["import"]["claimed_date"] for s in steps] == ["2025-09-14", "2025-10", "2025-11-02", None]
    assert steps[1]["import"]["precision"] == "month"
    assert steps[2]["relations"] == [{"to": steps[1]["id"], "rel": "uses"}] and steps[2]["milestone"]


def test_a_chinese_excel_table_in_gbk():
    table = "标题,类型,日期,基于,关键步骤\n直觉,想法,2025-09-14,,\n假设 H1,假设,2025-10-02,1,是\n"
    rows = importer.parse_table(table.encode("gb18030"))
    assert [(r.title, r.node_type, r.builds_on, r.key) for r in rows] == [
        ("直觉", "idea", [], False), ("假设 H1", "claim", [1], True)]
    with pytest.raises(importer.ImportProblem, match="title"):
        importer.parse_table(b"name\nx\n".replace(b"name", b"what"))


def test_step_numbers_in_a_table_name_the_rows():
    table = "step,title,builds on\n#7,First,\n#9,Second,#7\n#12,Third,\"#9, #7\"\n"
    assert [r.builds_on for r in importer.parse_table(table.encode())] == [[], [1], [2, 1]]


def test_the_table_template_reads_back():
    for lang in ("en", "zh"):
        data = importer.table_template(lang)
        assert data.startswith(b"\xef\xbb\xbf")  # Excel reads it as UTF-8
        rows = importer.parse_table(data)
        assert len(rows) == 3 and rows[2].key and rows[2].builds_on == [2] and not any(r.problems for r in rows)


def test_steps_go_out_as_a_table(api, ctx):
    api.init()
    a = api.entry("Formula v1", node_type="document", body="dv/dt = k (1 - v)^alpha")
    api.entry("Formula v2", node_type="document", relations=[{"to": a["id"], "rel": "revises"}], milestone=True)
    r = api.client.get(f"/api/export/table?project={api.project_id}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.content.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert rows[0][:2] == ["Step", "Date"] and len(rows) == 3
    assert rows[1][5] == "Formula v1" and rows[1][6] == "dv/dt = k (1 - v)^alpha"
    assert rows[2][7] == f"#{rows[1][0][1:]} revises" and rows[2][8] == "★"
    zh = api.client.get(f"/api/export/table?project={api.project_id}&lang=zh")
    head, first, second = list(csv.reader(io.StringIO(zh.content.decode("utf-8-sig"))))
    assert head[:2] == ["步骤编号", "日期"] and first[4] == "文档"
    # The table reads back in (the steps' own dates become the author's statement).
    again = importer.parse_table(zh.content)
    assert [(r.title, r.node_type, r.builds_on, r.key) for r in again] == [
        ("Formula v1", "document", [], False), ("Formula v2", "document", [1], True)]


# ---------------------------------------------------------------- into a git repository


@NEEDS_GIT
def test_the_evidence_bundle_goes_into_a_repository(api, ctx, tmp_path, monkeypatch):
    api.init()
    api.entry("Step one", body="hello")
    repo = GitRepo(tmp_path / "fsf-code")
    repo.commit("Initial model")
    (repo.path / "work-in-progress.py").write_text("unfinished = True\n")  # not part of the commit
    for k, v in {"GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@example.org", "GIT_COMMITTER_NAME": "A",
                 "GIT_COMMITTER_EMAIL": "a@example.org"}.items():
        monkeypatch.setenv(k, v)
    body = {"title": "FSF evidence", "default": "full", "path": str(repo.path)}
    r = api.client.post("/api/export/repository", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    folder = repo.path / "provenance" / "FSF-evidence"
    assert Path(out["folder"]) == folder and (folder / "bundle.json").is_file() and (folder / "VERIFY.md").is_file()
    assert repo.git("log", "-1", "--format=%s") == "Evidence bundle: FSF evidence" and out["commit"]
    assert repo.git("show", "--stat", "--format=", "HEAD").count("provenance/FSF-evidence/") >= 3
    assert "work-in-progress.py" in repo.git("status", "--porcelain")  # left alone

    # A repository the app is recording does not record the app's own evidence-bundle commit as a
    # step of the research (the v0.6.0 check, D-062).
    assert repo.git("log", "-1", "--format=%b").strip() == "Research-History: evidence bundle"
    ctx.git.add(str(repo.path), "main", api.project_id, history=False, keep_code=False, background=False)
    steps = len(payloads(ctx))
    (repo.path / "model.py").write_text("version = 2\n")
    repo.git("commit", "-q", "-am", "A real change")
    api.entry("Step one, revised")
    r = api.client.post("/api/export/repository", json=body)
    assert r.status_code == 200 and r.json()["commit"], r.text
    assert ctx.git.check()["recorded"] == 1  # the real change, not the bundle
    assert [p["title"] for p in payloads(ctx)][steps:] == ["Step one, revised", "A real change"]
    ctx.git.remove(ctx.git.sources()[0]["id"])

    # A folder of that name that is not a bundle is never overwritten.
    (repo.path / "provenance" / "Notes").mkdir()
    (repo.path / "provenance" / "Notes" / "mine.txt").write_text("keep me")
    r = api.client.post("/api/export/repository", json={**body, "title": "Notes"})
    assert r.status_code == 400 and "not an evidence bundle" in r.json()["detail"]
    assert (repo.path / "provenance" / "Notes" / "mine.txt").read_text() == "keep me"

    # Saved and committed, but there is nowhere to push to: said, not hidden.
    api.entry("Step one and a half")
    r = api.client.post("/api/export/repository", json={**body, "push": True}, headers={"X-RPROV-Lang": "zh-CN"})
    assert r.status_code == 200, r.text
    assert r.json()["commit"] and not r.json()["pushed"] and r.json()["error"]

    # Pushed when asked (to a bare copy standing in for GitHub).
    from app.services import gitrepo

    monkeypatch.setattr(gitrepo, "ALLOWED_PROTOCOLS", "file:https:ssh")
    server = tmp_path / "server.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(repo.path), str(server)], check=True)
    repo.git("remote", "add", "origin", str(server))
    repo.git("push", "-q", "-u", "origin", "main")
    api.entry("Step two")
    r = api.client.post("/api/export/repository", json={**body, "push": True})
    assert r.status_code == 200 and r.json()["pushed"], r.text
    log = subprocess.run(["git", "-C", str(server), "log", "-1", "--format=%s"], capture_output=True, text=True)
    assert log.stdout.strip() == "Evidence bundle: FSF evidence"


def test_folder_names_from_titles():
    assert publish.folder_name("FSF evidence") == "FSF-evidence"
    assert publish.folder_name("证据：FSF / 第一版") == "证据：FSF-第一版"
    assert publish.folder_name("..") == "evidence"


# ---------------------------------------------------------------- Zenodo


class FakeZenodo:
    """Answers like the Zenodo deposit API."""

    def __init__(self, bucket_host="sandbox.zenodo.org"):
        self.calls = []
        self.bucket_host = bucket_host

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path, request.headers.get("authorization")))
        if request.headers.get("authorization") != "Bearer good-token-123":
            return httpx.Response(401, json={"message": "nope"})
        if request.method == "GET":
            return httpx.Response(200, json=[])
        if request.method == "POST":
            return httpx.Response(201, json={"id": 77, "links": {
                "bucket": f"https://{self.bucket_host}/api/files/b-1", "html": "https://sandbox.zenodo.org/deposit/77"}})
        if request.url.path.startswith("/api/files/"):
            self.uploaded = (request.url.path, len(request.content))
            return httpx.Response(201, json={})
        self.metadata = json.loads(request.content)["metadata"]
        return httpx.Response(200, json={"id": 77, "links": {"html": "https://sandbox.zenodo.org/deposit/77"},
                                         "metadata": {"prereserve_doi": {"doi": "10.5072/zenodo.77"}}})


@pytest.fixture
def fake_zenodo(monkeypatch):
    fake = FakeZenodo()
    real = publish.Zenodo
    monkeypatch.setattr(publish, "Zenodo", lambda token, sandbox=False, transport=None:
                        real(token, sandbox, httpx.MockTransport(fake)))
    return fake


def test_a_zenodo_draft_with_the_evidence_bundle(api, ctx, fake_zenodo):
    api.init(author="Ada Example")
    api.entry("Step one")
    assert api.client.get("/api/zenodo").json() == {"connected": False, "sandbox": False}
    r = api.client.post("/api/export/zenodo", json={"title": "FSF", "default": "full"})
    assert r.status_code == 400 and "connect Zenodo first" in r.json()["detail"]

    r = api.client.post("/api/zenodo", json={"token": "wrong-token-123", "sandbox": True})
    assert r.status_code == 400 and "did not accept the token" in r.json()["detail"]
    r = api.client.post("/api/zenodo", json={"token": "good-token-123", "sandbox": True})
    assert r.json() == {"connected": True, "sandbox": True}

    r = api.client.post("/api/export/zenodo", json={"title": "FSF", "default": "full"})
    assert r.status_code == 200, r.text
    assert r.json() == {"id": 77, "html": "https://sandbox.zenodo.org/deposit/77", "doi": "10.5072/zenodo.77",
                        "sandbox": True}
    path, size = fake_zenodo.uploaded
    assert path.startswith("/api/files/b-1/provenance-FSF-") and path.endswith(".zip") and size > 1000
    assert fake_zenodo.metadata["creators"] == [{"name": "Ada Example"}] and fake_zenodo.metadata["prereserve_doi"]
    assert "verify.py" in fake_zenodo.metadata["description"]
    assert [m for m, _p, _a in fake_zenodo.calls] == ["GET", "GET", "POST", "PUT", "PUT"]  # never "publish"
    assert all(path.find("/actions/publish") < 0 for _m, path, _a in fake_zenodo.calls)

    assert api.client.delete("/api/zenodo").json() == {"connected": False, "sandbox": False}


def test_the_token_never_goes_to_another_server(ctx):
    fake = FakeZenodo(bucket_host="evil.example.org")
    client = publish.Zenodo("good-token-123", True, httpx.MockTransport(fake))
    with pytest.raises(publish.ZenodoError, match="another server"):
        client.create_draft("x.zip", b"data", {})
    assert all(not p.startswith("/api/files/") for _m, p, _a in fake.calls)
    for address in ("HTTPS://evil.example.org/api/files/b-1", "http://sandbox.zenodo.org/api/files/b-1"):
        with pytest.raises(publish.ZenodoError, match="another server"):
            client._call("PUT", address, content=b"data")
    assert len(fake.calls) == 1  # only the first request, to Zenodo itself
