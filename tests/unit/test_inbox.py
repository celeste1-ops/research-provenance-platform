"""D-049: watched folders. A finished new version waits in the inbox with a date stamp of its
hash; recorded, it keeps that earlier stamp next to the file, which anyone can check."""

from __future__ import annotations

import subprocess
import sys

import pytest

from app.services.inbox import SETTLE_SECONDS, InboxError, guess_type, ignored
from app.services.verification import record_file_stamps, verify_database
from provenance_core.jcs import parse_json_strict
from provenance_core.providers.base import ProviderUnavailable


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


@pytest.fixture
def setup(ctx, tmp_path):
    ctx.ledger.init_identity("Author")
    project = ctx.ledger.create_project("FSF").id
    folder = tmp_path / "drafts"
    folder.mkdir()
    (folder / "old.md").write_bytes(b"already here\n")
    clock = Clock()
    ctx.inbox._clock = clock
    ctx.inbox.add_folder(str(folder), project)
    return ctx, folder, clock, project


def settle(ctx, clock) -> int:
    """One look sees the change; a look after the settle time takes the version in."""
    first = ctx.inbox.scan()
    clock.now += SETTLE_SECONDS
    return first + ctx.inbox.scan()


def test_a_finished_version_arrives_stamped(setup):
    ctx, folder, clock, _ = setup
    assert ctx.inbox.scan() == 0  # what was there when watching started is not new
    (folder / "draft.md").write_bytes(b"first draft\n")
    assert ctx.inbox.scan() == 0  # still changing, perhaps
    clock.now += SETTLE_SECONDS
    assert ctx.inbox.scan() == 1
    [item] = ctx.inbox.status()["items"]
    assert item["name"] == "draft.md" and item["node_type"] == "document" and item["stamp"]["time"]
    assert ctx.ledger.record_count() == 1  # only the genesis: nothing entered the record
    assert ctx.inbox.scan() == 0  # the same version arrives once


def test_lock_and_temporary_files_are_ignored(setup):
    ctx, folder, clock, _ = setup
    for name in (".DS_Store", "~$draft.docx", "draft.docx.tmp", ".~lock.paper.odt#", "notes.md~", "a.tsr"):
        (folder / name).write_bytes(b"x")
    (folder / ".git").mkdir()
    (folder / ".git" / "HEAD").write_bytes(b"ref")
    assert settle(ctx, clock) == 0
    assert ignored("~$x.docx") and not ignored("figure2.png")
    assert guess_type("fig.PNG") == "figure" and guess_type("run.csv") == "dataset" and guess_type("a.py") == "code"


def test_record_keeps_the_earlier_stamp_and_chains_versions(setup, client):
    ctx, folder, clock, project = setup
    (folder / "draft.md").write_bytes(b"first draft\n")
    settle(ctx, clock)
    [item] = ctx.inbox.status()["items"]
    first = ctx.inbox.record(item["id"])
    files = {f.name for f in ctx.ledger.record_files(first)}
    assert files == {"draft.md", "draft.md.tsr"}
    [stamp] = record_file_stamps(ctx.ledger, ctx.anchors, first)
    assert stamp["file"] == "draft.md" and stamp["state"] == "verified" and stamp["time"] == item["stamp"]["time"]
    result = verify_database(ctx.ledger, ctx.anchors).by_id()[first]
    assert result.status != "fail" and result.file_stamps[0].check.verified
    assert client.get(f"/api/records/{first}").json()["file_stamps"][0]["state"] == "verified"

    (folder / "draft.md").write_bytes(b"second draft\n")
    settle(ctx, clock)
    [item2] = ctx.inbox.status()["items"]
    assert item2["previous"] == first
    second = ctx.inbox.record(item2["id"], title="Draft, second version", node_type="document")
    payload = parse_json_strict(ctx.ledger.record(second).payload_bytes)
    assert payload["title"] == "Draft, second version"
    assert payload["relations"] == [{"to": first, "rel": "revises"}]
    assert ctx.inbox.status()["items"] == []


def test_discard_leaves_nothing(setup):
    ctx, folder, clock, _ = setup
    (folder / "scratch.txt").write_bytes(b"junk\n")
    settle(ctx, clock)
    [item] = ctx.inbox.status()["items"]
    blob = ctx.inbox._blob(item["sha256"])
    assert blob.exists()
    ctx.inbox.discard(item["id"])
    assert ctx.inbox.status()["items"] == [] and not blob.exists() and ctx.ledger.record_count() == 1


def test_existing_files_on_request_and_folder_checks(ctx, tmp_path, monkeypatch):
    ctx.ledger.init_identity("Author")
    project = ctx.ledger.create_project("FSF").id
    folder = tmp_path / "figures"
    folder.mkdir()
    (folder / "fig1.png").write_bytes(b"\x89PNG fake")
    ctx.inbox.add_folder(str(folder), project, include_existing=True)
    assert ctx.inbox.scan() == 1 and ctx.inbox.status()["items"][0]["node_type"] == "figure"
    with pytest.raises(InboxError, match="already being watched"):
        ctx.inbox.add_folder(str(folder), project)
    with pytest.raises(InboxError, match="data folder"):
        ctx.inbox.add_folder(str(ctx.settings.data_dir.parent), project)
    with pytest.raises(InboxError, match="full folder path"):
        ctx.inbox.add_folder("relative", project)
    import app.services.inbox as inbox_module

    monkeypatch.setattr(inbox_module, "MAX_FILES", 2)
    many = tmp_path / "many"
    many.mkdir()
    for i in range(3):
        (many / f"f{i}.txt").write_bytes(b"x")
    with pytest.raises(InboxError, match="too many files"):
        ctx.inbox.add_folder(str(many), project)


def test_unreachable_stamp_service_is_retried(setup, monkeypatch):
    ctx, folder, clock, _ = setup
    provider = ctx.anchors.providers["tsa"]
    real_submit = provider.submit

    def down(*_a, **_k):
        raise ProviderUnavailable("no time-stamping authority answered")

    monkeypatch.setattr(provider, "submit", down)
    (folder / "draft.md").write_bytes(b"text\n")
    settle(ctx, clock)
    [item] = ctx.inbox.status()["items"]
    assert item["stamp"] is None and "no time-stamping" in item["stamp_error"]
    monkeypatch.setattr(provider, "submit", real_submit)
    ctx.inbox.scan()
    assert ctx.inbox.status()["items"][0]["stamp"]["time"]


def test_verify_py_reports_the_file_stamp(setup, tmp_path):
    from app.services.export import build_bundle_files, plan_export, write_dir

    ctx, folder, clock, _ = setup
    (folder / "draft.md").write_bytes(b"first draft\n")
    settle(ctx, clock)
    rid = ctx.inbox.record(ctx.inbox.status()["items"][0]["id"])
    plan = plan_export(ctx.ledger, "inbox", {rid: "full"})
    files = build_bundle_files(ctx.ledger, ctx.anchors, plan)
    html, verify_md = files["report.html"].decode(), files["VERIFY.md"].decode()
    assert "Date stamp of draft.md" in html and "verified — the file existed by" in html
    assert "The file draft.md already existed by" in html  # and the story says so
    assert "### 3b." in verify_md and "-data content/<id>/files/<name>" in verify_md
    out = tmp_path / "bundle"
    write_dir(files, out)
    run = subprocess.run([sys.executable, "-I", str(out / "verify.py"), str(out), "--tsa-root",
                          str(out / "certs" / "mock-tsa-root.pem"), "--offline"],
                         capture_output=True, text=True, encoding="utf-8")
    assert "File draft.md existed by" in run.stdout, run.stdout + run.stderr
    # A stamp that no longer matches its file is reported (altering the file also fails the record).
    tsr = next(p for p in out.rglob("draft.md.tsr"))
    (tsr.parent / "draft.md").write_bytes(b"other bytes\n")
    run = subprocess.run([sys.executable, "-I", str(out / "verify.py"), str(out), "--tsa-root",
                          str(out / "certs" / "mock-tsa-root.pem"), "--offline"],
                         capture_output=True, text=True, encoding="utf-8")
    assert "File stamp of draft.md: not verified" in run.stdout


def test_a_file_in_use_is_tried_again(setup, monkeypatch):
    import app.services.inbox as inbox_module

    ctx, folder, clock, _ = setup
    (folder / "table.xlsx").write_bytes(b"cells")
    ctx.inbox.scan()
    clock.now += SETTLE_SECONDS
    real_copy = inbox_module.shutil.copyfile

    def locked(*_a, **_k):  # as Windows does while Excel has the file open
        raise PermissionError(13, "The process cannot access the file")

    monkeypatch.setattr(inbox_module.shutil, "copyfile", locked)
    assert ctx.inbox.scan() == 0 and ctx.inbox.status()["folders"][0]["error"] is None
    monkeypatch.setattr(inbox_module.shutil, "copyfile", real_copy)
    assert ctx.inbox.scan() == 1  # not lost: it arrives once the file is free
