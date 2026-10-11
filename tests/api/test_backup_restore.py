"""AC-24: back up, restore into an empty directory: same record IDs, time proofs and
verification results; the restored key signs new records as the same identity.
Plus S4: restore refuses unsafe archives."""

from __future__ import annotations

import io
import json
import stat
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.backup import BackupError, create_backup, restore_backup
from app.services.keystore import MemoryKeyStore
from app.services.ledger import EntryInput, LedgerError
from app.services.verification import report_json, verify_database
from provenance_core.jcs import parse_json_strict
from tests.conftest import make_ctx
from tests.sample import build_log

PASSWORD = "backup password 1"


def _snapshot(ctx):
    rows = [(r.id, r.seq, r.kind, r.manifest_bytes, r.payload_bytes, r.signature) for r in ctx.ledger.records()]
    anchors = {
        (rid, kind): (a.status, a.proof_bytes, a.verified_time_utc, a.provider_name)
        for rid, by in ctx.anchors.rows_by_record().items()
        for kind, a in by.items()
    }
    files = sorted((rid, f.name, f.sha256) for rid, fs in ctx.ledger.all_record_files().items() for f in fs)
    return rows, anchors, files


def test_backup_and_restore_into_empty_directory(tmp_path):
    a = make_ctx(tmp_path / "a")
    build_log(a)
    before = _snapshot(a)
    report_a = report_json(verify_database(a.ledger, a.anchors))
    name, data = create_backup(a, PASSWORD)
    assert name.startswith("rprov-backup-") and name.endswith(".zip")
    a.close()

    b = make_ctx(tmp_path / "b", keystore=MemoryKeyStore())  # fresh directory, empty keychain
    summary = restore_backup(b, data, PASSWORD)
    assert summary["records"] == len(before[0])
    after = _snapshot(b)
    assert after == before  # record IDs, bytes, signatures, time proofs, files
    assert report_json(verify_database(b.ledger, b.anchors)) == report_a
    for sha in {s for _, _, s in after[2]}:
        assert b.blobs.get(sha)

    # The restored key signs new records as the same identity.
    pid = b.ledger.projects()[0].id
    new_id = b.ledger.create_entry(EntryInput(pid, "note", "after restore", body="still me"))
    report = verify_database(b.ledger, b.anchors)
    assert report.ok
    assert report.by_id()[new_id].failure_codes == []
    genesis = parse_json_strict(b.ledger.records()[0].payload_bytes)
    assert report.public_key_hex == genesis["public_key"]
    b.close()


def test_restore_refuses_non_empty_installation_and_wrong_password(tmp_path):
    a = make_ctx(tmp_path / "a")
    build_log(a)
    _, data = create_backup(a, PASSWORD)
    with pytest.raises(LedgerError, match="empty installation"):
        restore_backup(a, data, PASSWORD)
    a.close()
    b = make_ctx(tmp_path / "b")
    with pytest.raises(BackupError, match="wrong backup password"):
        restore_backup(b, data, "not the password")
    assert b.ledger.record_count() == 0
    b.close()


def _rewrite(data: bytes, edit) -> bytes:
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        for info in src.infolist():
            content = src.read(info.filename)
            result = edit(info, content)
            if result is not None:
                zf.writestr(*result) if isinstance(result, tuple) else zf.writestr(info, result)
        extra = getattr(edit, "extra", None)
        if extra:
            for item in extra:
                zf.writestr(*item)
    return out.getvalue()


@pytest.fixture(scope="module")
def backup_bytes(tmp_path_factory):
    a = make_ctx(tmp_path_factory.mktemp("bk"))
    build_log(a)
    _, data = create_backup(a, PASSWORD)
    a.close()
    return data


def _with_extra(*items):
    def edit(info, content):
        return content

    edit.extra = items
    return edit


@pytest.mark.parametrize(
    "editor, message",
    [
        (_with_extra(("../outside.txt", b"x")), "unsafe path"),
        (_with_extra(("/etc/passwd", b"x")), "unsafe path"),
        (_with_extra(("blobs/../../x", b"x")), "unsafe path"),
        (_with_extra(("notes.txt", b"x")), "unexpected file"),
    ],
)
def test_restore_rejects_unsafe_paths(tmp_path, backup_bytes, editor, message):
    b = make_ctx(tmp_path)
    with pytest.raises(BackupError, match=message):
        restore_backup(b, _rewrite(backup_bytes, editor), PASSWORD)
    assert b.ledger.record_count() == 0
    assert not (tmp_path.parent / "outside.txt").exists()
    b.close()


def test_restore_rejects_symlinks_tampering_and_oversize(tmp_path, backup_bytes):
    b = make_ctx(tmp_path)
    link = zipfile.ZipInfo("blobs/aa/bb/" + "a" * 64)
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(BackupError, match="symbolic link"):
        restore_backup(b, _rewrite(backup_bytes, _with_extra((link, b"/etc/passwd"))), PASSWORD)

    def tamper_db(info, content):
        return content + b"x" if info.filename == "db/rprov.sqlite3" else content

    with pytest.raises(BackupError, match="does not match the backup index"):
        restore_backup(b, _rewrite(backup_bytes, tamper_db), PASSWORD)
    with pytest.raises(BackupError, match="larger than the allowed"):
        restore_backup(b, backup_bytes, PASSWORD, max_bytes=1000)
    with pytest.raises(BackupError, match="not a backup zip"):
        restore_backup(b, b"garbage", PASSWORD)
    assert b.ledger.record_count() == 0
    b.close()


def test_backup_and_restore_over_http(tmp_path):
    a = make_ctx(tmp_path / "a")
    folder = tmp_path / "backups"
    folder.mkdir()
    with TestClient(create_app(a), base_url="http://127.0.0.1:8765") as cl:
        cl.headers["X-RPROV-Token"] = a.session_token
        cl.post("/api/identity", json={"author_label": "HTTP"})
        assert cl.post("/api/backup", json={"password": "short"}).status_code == 422
        r = cl.post("/api/backup", json={"password": PASSWORD, "location": str(folder)})
        assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
        written = list(folder.iterdir())
        assert len(written) == 1 and written[0].read_bytes() == r.content
        assert r.headers["x-backup-path"] == str(written[0])
        status = cl.get("/api/status").json()
        assert status["backup_location"] == str(folder) and status["key_backup_done"] is True
        data = r.content
        assert cl.post("/api/backup", json={"password": PASSWORD, "location": "relative/dir"}).status_code == 400
    a.close()
    b = make_ctx(tmp_path / "b")
    with TestClient(create_app(b), base_url="http://127.0.0.1:8765") as cl:
        cl.headers["X-RPROV-Token"] = b.session_token
        r = cl.post("/api/restore", data={"password": PASSWORD}, files={"file": ("backup.zip", data, "application/zip")})
        assert r.status_code == 200, r.text
        assert r.json()["verification"]["ok"] is True
        assert cl.get("/api/status").json()["author_label"] == "HTTP"
        again = cl.post("/api/restore", data={"password": PASSWORD}, files={"file": ("b.zip", data, "application/zip")})
        assert again.status_code == 400
    b.close()
    meta = json.loads(zipfile.ZipFile(io.BytesIO(data)).read("rprov-backup.json"))
    assert meta["format"] == "rprov.backup/1"
