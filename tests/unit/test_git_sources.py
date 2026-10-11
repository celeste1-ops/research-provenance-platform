"""D-047: commits of a local git repository become steps automatically. git's own dates are
only the author's claimed date; nothing but local git commands is run."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from app.services.gitrepo import Commit, GitError, Repo, find_git, strip_credentials
from app.services.gitsources import MAX_SEPARATE, history_batches
from provenance_core.jcs import parse_json_strict
from tests.gitutil import GitRepo

pytestmark = pytest.mark.skipif(find_git() is None, reason="git is not installed")


@pytest.fixture
def repo(tmp_path):
    return GitRepo(tmp_path / "fsf-code")


@pytest.fixture
def project(ctx):
    ctx.ledger.init_identity("Author")
    return ctx.ledger.create_project("FSF").id


def entries(ctx) -> list[dict]:
    return [{"id": r.id, **parse_json_strict(r.payload_bytes)} for r in ctx.ledger.records() if r.kind == "entry"]


def test_commits_are_read_oldest_first_with_their_message(repo):
    a = repo.commit("First formula\n\nE = mc^2 as a start", date="2025-03-02T10:00:00+01:00")
    b = repo.commit("Revised model", date="2025-04-05T10:00:00+01:00")
    r = Repo(repo.path)
    assert r.branches() == ["main"] and r.current_branch() == "main" and r.head("main") == b
    commits = r.commits(b)
    assert [c.sha for c in commits] == [a, b]
    assert commits[0].subject == "First formula" and commits[0].body == "E = mc^2 as a start"
    assert commits[0].date.startswith("2025-03-02T10:00:00")
    assert [c.sha for c in r.commits(b, since=a)] == [b]
    assert r.is_ancestor(a, b) and not r.is_ancestor(b, a)
    assert r.head("no-such-branch") is None
    with pytest.raises(GitError):
        r.commits("--output=/tmp/x")  # never passed to git as an option


def test_not_a_repository(tmp_path):
    (tmp_path / "plain").mkdir()
    with pytest.raises(GitError, match="not a git repository"):
        Repo(tmp_path / "plain").toplevel()


def test_passwords_never_leave_the_remote_address():
    assert strip_credentials("https://user:ghp_secret@github.com/a/b.git") == "https://github.com/a/b.git"
    assert strip_credentials("https://ghp_secret@github.com/a/b.git") == "https://github.com/a/b.git"
    assert strip_credentials("git@github.com:a/b.git") == "git@github.com:a/b.git"
    assert strip_credentials("ssh://git@github.com/a/b.git") == "ssh://git@github.com/a/b.git"


def _c(sha: str, date: str) -> Commit:
    return Commit(sha * 40, date, f"commit {sha}", "")


def test_history_is_grouped_by_tag_then_by_month():
    commits = [_c("a", "2025-01-05T00:00:00Z"), _c("b", "2025-01-20T00:00:00Z"), _c("c", "2025-02-01T00:00:00Z"),
               _c("d", "2025-02-03T00:00:00Z"), _c("e", "2025-04-01T00:00:00Z")]
    batches = history_batches(commits, {"c" * 40: ["v1.0"]})
    assert [(b.label, b.precision, len(b.commits)) for b in batches] == [
        ("2025-01", "month", 2), ("v1.0", "day", 1), ("2025-02", "month", 1), ("2025-04", "month", 1)]
    assert [b.claimed_date for b in batches] == ["2025-01", "2025-02-01", "2025-02", "2025-04"]
    many = [_c(f"{i:x}"[-1], f"{2000 + i // 12}-{i % 12 + 1:02d}-01T00:00:00Z") for i in range(60)]
    assert {b.precision for b in history_batches(many, {})} == {"year"}


def test_start_from_now_then_record_each_new_commit(ctx, project, repo):
    first = repo.commit("Initial model", date="2024-05-01T09:00:00+00:00")
    ctx.git.add(str(repo.path), "main", project, history=False, keep_code=False, background=False)
    [step] = entries(ctx)
    assert step["title"] == "Initial model" and step["node_type"] == "code"
    assert step["external"]["commit"] == first
    assert Path(step["external"]["repo_url"]).samefile(repo.path)  # no remote: the folder itself
    # git's date is older than today: kept as the author's claimed date, never as a verified time.
    assert step["import"] == {"claimed_date": "2024-05-01", "precision": "day", "level": "L1", "references": []}

    a = repo.commit("Try a smaller step size\n\nThe old one diverged.")
    b = repo.commit("Fix the boundary term")
    assert ctx.git.check() == {"recorded": 2, "busy": False}
    steps = entries(ctx)
    assert [s["title"] for s in steps] == ["Initial model", "Try a smaller step size", "Fix the boundary term"]
    assert [s["external"]["commit"] for s in steps[1:]] == [a, b]
    assert steps[1]["import"] is None  # made today: its date stamp is the time that counts
    assert steps[1]["relations"] == [{"to": steps[0]["id"], "rel": "revises"}]
    assert steps[2]["relations"] == [{"to": steps[1]["id"], "rel": "revises"}]
    assert ctx.ledger.record_files(steps[1]["id"])[0].name == "body.md"  # "The old one diverged."
    assert ctx.git.check() == {"recorded": 0, "busy": False}
    [source] = ctx.git.sources()
    assert source["recorded"] == 3 and source["last_commit"] == b and source["error"] is None


def test_history_steps_and_a_long_absence(ctx, project, repo):
    repo.commit("a", date="2025-01-05T10:00:00+00:00")
    repo.commit("b", date="2025-01-20T10:00:00+00:00", tag="v0.1")
    repo.commit("c", date="2025-02-01T10:00:00+00:00")
    ctx.git.add(str(repo.path), "main", project, history=True, keep_code=False, background=False)
    steps = entries(ctx)
    assert [s["title"] for s in steps] == ["fsf-code · v0.1", "fsf-code · 2025-02"]
    assert steps[0]["import"]["claimed_date"] == "2025-01-20" and steps[1]["import"]["claimed_date"] == "2025-02"
    assert steps[1]["relations"] == [{"to": steps[0]["id"], "rel": "revises"}]

    for i in range(MAX_SEPARATE + 1):  # the app was closed while much happened
        repo.commit(f"work {i}")
    assert ctx.git.check()["recorded"] == 1
    last = entries(ctx)[-1]
    assert last["title"].startswith("fsf-code · ") and "…" in last["title"]
    body = ctx.ledger.blobs.get(ctx.ledger.record_files(last["id"])[0].sha256).decode()
    assert body.count("\n") == MAX_SEPARATE and "work 0" in body


def test_keeping_the_code(ctx, project, repo):
    sha = repo.commit("Model")
    ctx.git.add(str(repo.path), "main", project, history=False, keep_code=True, background=False)
    [step] = entries(ctx)
    [archive] = [f for f in ctx.ledger.record_files(step["id"]) if f.name.endswith(".zip")]
    assert archive.name == f"fsf-code-{sha[:12]}.zip"
    with zipfile.ZipFile(io.BytesIO(ctx.ledger.blobs.get(archive.sha256))) as z:
        assert z.read("model.py") == b"version = 1\n"


def test_a_commit_is_never_recorded_twice(ctx, project, repo):
    repo.commit("one")
    ctx.git.add(str(repo.path), "main", project, history=False, keep_code=False, background=False)
    two = repo.commit("two")
    ctx.git.check()
    # As if the app stopped between saving the step and noting it in the list.
    data = json.loads(ctx.git.file.read_text(encoding="utf-8"))
    data["sources"][0]["last_commit"] = entries(ctx)[0]["external"]["commit"]
    ctx.git.file.write_text(json.dumps(data), encoding="utf-8")
    assert ctx.git.check()["recorded"] == 0
    assert [s["external"]["commit"] for s in entries(ctx)][-1] == two and len(entries(ctx)) == 2


def test_rewritten_history_and_missing_folder(ctx, project, repo, tmp_path):
    repo.commit("one")
    ctx.git.add(str(repo.path), "main", project, history=False, keep_code=False, background=False)
    repo.git("commit", "-q", "--amend", "-m", "one, reworded")
    assert ctx.git.check()["recorded"] == 1
    assert entries(ctx)[-1]["title"] == "one, reworded"
    repo.path.rename(tmp_path / "moved")
    ctx.git.check()
    [source] = ctx.git.sources()
    assert "not there" in source["error"]


def test_adding_checks_its_input(ctx, project, repo, tmp_path):
    repo.commit("one")
    with pytest.raises(GitError, match="full folder path"):
        ctx.git.add("relative/path", "main", project, history=False, keep_code=False)
    with pytest.raises(GitError, match="no such branch"):
        ctx.git.add(str(repo.path), "--help", project, history=False, keep_code=False)
    info = ctx.git.inspect(str(repo.path / "."))
    assert info["name"] == "fsf-code" and info["branch"] == "main" and info["commits"] == 1
    ctx.git.add(str(repo.path), "main", project, history=False, keep_code=False, background=False)
    with pytest.raises(GitError, match="already being recorded"):
        ctx.git.add(str(repo.path), "main", project, history=False, keep_code=False)
    [source] = ctx.git.sources()
    ctx.git.remove(source["id"])
    assert ctx.git.sources() == [] and len(entries(ctx)) == 1  # the step stays, as every step does


def test_the_code_copy_is_exactly_what_was_committed(tmp_path):
    """Not converted by this computer's git settings (Git for Windows: LF -> CRLF), no filter
    program run, and the same commit always gives the same zip."""
    repo = GitRepo(tmp_path / "eol")
    repo.git("config", "core.autocrlf", "true")
    (repo.path / ".gitattributes").write_bytes(b"*.dat filter=lfs\n")  # a filter that must not run
    repo.git("add", ".gitattributes")
    sha = repo.commit("Model")
    r = Repo(repo.path)
    first = r.archive(sha, 10_000_000)
    assert first == r.archive(sha, 10_000_000)
    with zipfile.ZipFile(io.BytesIO(first)) as z:
        assert z.read("model.py") == b"version = 1\n"
        assert sorted(z.namelist()) == [".gitattributes", "model.py"]
    assert r.archive(sha, 10) is None  # over the limit


def test_tags_become_key_steps_once(ctx, project, repo):
    repo.commit("v1 of the model", tag="v1")
    ctx.git.add(str(repo.path), "main", project, history=False, keep_code=False, background=False)
    ctx.git.check()
    state = ctx.ledger.state()
    [first] = state.entries.values()
    assert first.milestone  # tagged when recorded

    second = repo.commit("v2 of the model")
    ctx.git.check()
    step2 = next(e for e in ctx.ledger.state().entries.values() if e.payload["external"]["commit"] == second)
    assert not step2.milestone
    repo.git("tag", "v2")  # tagged after it was recorded: marked by a later addition
    ctx.git.check()
    assert ctx.ledger.state().entries[step2.id].milestone
    kinds = [r.kind for r in ctx.ledger.records()]
    assert kinds.count("milestone") == 1

    ctx.ledger.create_milestone(step2.id, "unset")  # the author takes the mark off
    repo.commit("v3")
    ctx.git.check()
    assert not ctx.ledger.state().entries[step2.id].milestone  # and it stays off


def test_tagged_history_steps_are_key_steps(ctx, project, repo):
    repo.commit("a", date="2025-01-05T10:00:00+00:00", tag="v0.1")
    repo.commit("b", date="2025-02-05T10:00:00+00:00")
    ctx.git.add(str(repo.path), "main", project, history=True, keep_code=False, background=False)
    by_title = {e.title: e for e in ctx.ledger.state().entries.values()}
    assert by_title["fsf-code · v0.1"].milestone
    assert not by_title["fsf-code · 2025-02"].milestone
