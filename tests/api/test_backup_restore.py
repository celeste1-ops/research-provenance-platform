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
from app.services import backup as backup_mod
from app.services.backup import BackupError, create_backup, create_plain_backup, restore_backup
from app.services.keystore import MemoryKeyStore
from app.services.ledger import EntryInput, LedgerError
from app.services.verification import report_json, verify_database
from provenance_core.jcs import parse_json_strict
from provenance_core.signing import private_key_raw
from tests.conftest import make_ctx
from tests.sample import build_log

PASSWORD = "backup password 1"


@pytest.fixture(autouse=True)
def fast_kdf(monkeypatch):
    # The real scrypt cost (128 MiB, ~0.5 s) is exercised in test_encryption_format; keep the rest fast.
    monkeypatch.setattr(backup_mod, "SCRYPT_N", 2**14)


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
    assert name.startswith("rprov-backup-") and name.endswith(".rprovbackup")
    assert data.startswith(backup_mod.ENCRYPTED_MAGIC)
    for plaintext in (b"SQLite format 3", b"Numerical experiment", b"converged after 40 steps", b"t,x\n0,1"):
        assert plaintext not in data  # everything is encrypted, not just the key
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
    _, data = create_plain_backup(a, PASSWORD)  # older unencrypted format: still restorable, still checked
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
    with pytest.raises(BackupError, match="not a backup file"):
        restore_backup(b, b"garbage", PASSWORD)
    assert b.ledger.record_count() == 0
    b.close()


def test_backup_and_restore_over_http(tmp_path):
    a = make_ctx(tmp_path / "a")
    a.autobackup.debounce = 0  # back up right after each change (no timer) in tests
    folder = tmp_path / "backups"
    with TestClient(create_app(a), base_url="http://127.0.0.1:8765") as cl:
        cl.headers["X-RPROV-Token"] = a.session_token
        cl.post("/api/identity", json={"author_label": "HTTP"})
        pid = cl.post("/api/projects", json={"title": "FSF"}).json()["id"]
        assert cl.get("/api/status").json()["backup"]["state"] == "off"
        # One-off encrypted download.
        r = cl.post("/api/backup", json={"password": PASSWORD})
        assert r.status_code == 200 and r.content.startswith(backup_mod.ENCRYPTED_MAGIC)
        assert cl.post("/api/backup", json={"password": "short"}).status_code == 422
        # Automatic backups to a folder (created on request); the first one is written immediately.
        bad = cl.post("/api/backup/settings", json={"location": "relative/dir", "password": PASSWORD})
        assert bad.status_code == 400
        st = cl.post("/api/backup/settings",
                     json={"location": str(folder), "password": PASSWORD, "create": True}).json()
        assert st["configured"] and st["last_backup"] and not st["pending_changes"]
        assert st["where"]["kind"] == "same-disk" and st["state"] == "same-disk" and "warning" in st["where"]
        assert len(list(folder.glob("*.rprovbackup"))) == 1
        # A new research step triggers the next backup by itself.
        cl.post("/api/entries", data={"project_id": pid, "node_type": "idea", "title": "first step"})
        backups = sorted(folder.glob("*.rprovbackup"))
        assert len(backups) == 2
        assert cl.get("/api/status").json()["entry_count"] == 1  # genesis is not a research step
        assert cl.post("/api/backup/run").status_code == 200
        latest = sorted(folder.glob("*.rprovbackup"))[-1].read_bytes()
    a.close()
    b = make_ctx(tmp_path / "b")
    with TestClient(create_app(b), base_url="http://127.0.0.1:8765") as cl:
        cl.headers["X-RPROV-Token"] = b.session_token
        wrong = cl.post("/api/restore", data={"password": "not it at all"},
                        files={"file": ("x.rprovbackup", latest, "application/octet-stream")})
        assert wrong.status_code == 400 and "wrong backup password" in wrong.text
        r = cl.post("/api/restore", data={"password": PASSWORD},
                    files={"file": ("x.rprovbackup", latest, "application/octet-stream")})
        assert r.status_code == 200, r.text
        assert r.json()["verification"]["ok"] is True
        # Same folder, same password — but the restored copy waits until the author confirms (D-040).
        assert r.json()["backup"]["configured"] is True and r.json()["backup"]["state"] == "paused"
        files_before = len(list(folder.iterdir()))
        r = cl.post("/api/backup/resume")
        assert r.status_code == 200 and r.json()["state"] != "paused"
        assert len(list(folder.iterdir())) == files_before + 1
        status = cl.get("/api/status").json()
        assert status["author_label"] == "HTTP" and status["entry_count"] == 1
        again = cl.post("/api/restore", data={"password": PASSWORD},
                        files={"file": ("b.rprovbackup", latest, "application/octet-stream")})
        assert again.status_code == 400
    b.close()


def test_encryption_format_and_tamper_detection():
    plain = b"inner zip bytes " * 100
    monkey_n = backup_mod.SCRYPT_N
    backup_mod.SCRYPT_N = 2**17  # the real cost, once
    try:
        enc = backup_mod.encrypt_backup(plain, PASSWORD)
    finally:
        backup_mod.SCRYPT_N = monkey_n
    assert enc.startswith(backup_mod.ENCRYPTED_MAGIC_V1)  # format 1 stays readable
    header = json.loads(enc[len(backup_mod.ENCRYPTED_MAGIC_V1):].split(b"\n", 1)[0])
    assert header["kdf"] == "scrypt" and header["n"] == 2**17 and header["cipher"] == "AES-256-GCM"
    assert backup_mod.decrypt_backup(enc, PASSWORD) == plain
    with pytest.raises(BackupError, match="wrong backup password"):
        backup_mod.decrypt_backup(enc, "wrong password")
    flipped = bytearray(enc)
    flipped[-5] ^= 1
    with pytest.raises(BackupError):
        backup_mod.decrypt_backup(bytes(flipped), PASSWORD)
    # The header is authenticated too: lowering the KDF cost in it breaks decryption.
    forged = enc.replace(b'"n": 131072', b'"n": 16384', 1)
    with pytest.raises(BackupError):
        backup_mod.decrypt_backup(forged, PASSWORD)


def test_rotation_keeps_the_newest_backups(tmp_path, monkeypatch):
    from app.services import autobackup

    monkeypatch.setattr(autobackup, "KEEP_BACKUPS", 3)
    ctx = make_ctx(tmp_path / "a")
    ctx.ledger.init_identity("R")
    folder = tmp_path / "bk"
    folder.mkdir()
    (folder / "unrelated.txt").write_text("keep me")
    ctx.autobackup.configure(str(folder), PASSWORD)
    names = []
    for i in range(5):
        # distinct timestamps in the file name
        monkeypatch.setattr(backup_mod, "datetime", _FakeDatetime(i))
        ctx.autobackup.run("test")
    names = sorted(p.name for p in folder.glob("*.rprovbackup"))
    assert len(names) == 3 and names[-1].endswith("000004-000.rprovbackup")
    assert names[0].endswith("000002-000.rprovbackup")  # the two oldest were removed
    assert (folder / "unrelated.txt").exists()
    ctx.close()


class _FakeDatetime:
    def __init__(self, i):
        from datetime import datetime as real

        self._t = real(2030, 1, 1, 0, 0, i, tzinfo=backup_mod.UTC)  # microsecond 0

    def now(self, tz=None):
        return self._t


def test_backup_failure_is_reported_and_retried(tmp_path):
    ctx = make_ctx(tmp_path / "a")
    ctx.ledger.init_identity("F")
    folder = tmp_path / "drive"
    folder.mkdir()
    ctx.autobackup.configure(str(folder), PASSWORD)
    folder.rename(tmp_path / "unplugged")  # e.g. the external drive was disconnected
    res = ctx.autobackup.run("test")
    assert res["ran"] is False
    st = ctx.autobackup.status()
    assert st["state"] == "error" and st["where"]["kind"] == "missing"
    (tmp_path / "unplugged").rename(folder)
    assert ctx.autobackup.maybe_run("hourly")["ran"] is True  # retried because the last attempt failed
    assert ctx.autobackup.status()["state"] == "same-disk" and ctx.autobackup.status()["last_error"] is None
    ctx.close()


def test_location_classification(tmp_path, monkeypatch):
    import os

    from app.services import autobackup

    data = tmp_path / "data"
    data.mkdir()
    assert autobackup.classify_location(tmp_path / "nope", data)["kind"] == "missing"
    assert autobackup.classify_location(tmp_path, data)["kind"] == "same-disk"
    fake_icloud = tmp_path / "Mobile Documents" / "com~apple~CloudDocs"
    (fake_icloud / "Research Provenance Backups").mkdir(parents=True)
    monkeypatch.setattr(autobackup, "ICLOUD_DRIVE", fake_icloud)
    got = autobackup.classify_location(fake_icloud / "Research Provenance Backups", data)
    assert got == {"kind": "synced", "label": "iCloud Drive", "safe": True}
    fake_cloud = tmp_path / "CloudStorage"
    (fake_cloud / "Dropbox" / "bk").mkdir(parents=True)
    monkeypatch.setattr(autobackup, "CLOUD_STORAGE", fake_cloud)
    assert autobackup.classify_location(fake_cloud / "Dropbox" / "bk", data)["label"] == "Dropbox"
    sugg = autobackup.suggestions(data)
    assert sugg[0]["label"] == "iCloud Drive" and sugg[0]["path"].endswith("Research Provenance Backups")
    shm = "/dev/shm"
    if os.path.isdir(shm) and os.stat(shm).st_dev != os.stat(data).st_dev:
        assert autobackup.classify_location(type(tmp_path)(shm), data)["kind"] == "external"


# ---------------------------------------------------------------- recovery code (D-039)


def _configured(tmp_path, name="a"):
    ctx = make_ctx(tmp_path / name)
    build_log(ctx)
    folder = tmp_path / f"{name}-backups"
    st = ctx.autobackup.configure(str(folder), PASSWORD, create=True)
    return ctx, folder, st


def test_recovery_code_opens_the_backup_when_the_password_is_forgotten(tmp_path):
    a, folder, st = _configured(tmp_path)
    code = st["recovery_code"]
    assert len(code) == 27 and code.count("-") == 3
    assert st["recovery"]["configured"] and "recovery_code" not in a.autobackup.status()
    stored = a.ledger.meta(backup_mod.RECOVERY_META)
    assert code.replace("-", "") not in stored and "public_key" in stored  # only the public half is kept
    before = _snapshot(a)
    (backup_file,) = folder.iterdir()
    data = backup_file.read_bytes()
    a.close()

    b = make_ctx(tmp_path / "b", keystore=MemoryKeyStore())
    with pytest.raises(BackupError, match="wrong recovery code"):
        restore_backup(b, data, recovery_code="0" * 24)
    with pytest.raises(BackupError, match="24 letters"):
        restore_backup(b, data, recovery_code="too short")
    # Typed in lower case, without dashes, with an O for a zero: still accepted.
    sloppy = code.replace("-", " ").lower().replace("0", "o")
    summary = restore_backup(b, data, recovery_code=sloppy)
    assert summary["opened_with"] == "recovery code"
    assert _snapshot(b) == before
    assert report_json(verify_database(b.ledger, b.anchors))["ok"]
    # The password is unknown after this: automatic backup asks for a new one; the code stays valid.
    st = b.autobackup.status()
    assert st["needs_password"] and not st["configured"] and st["recovery"]["configured"]
    b.close()


def test_password_still_opens_and_a_new_code_replaces_the_old_one(tmp_path):
    a, folder, st = _configured(tmp_path)
    old_code = st["recovery_code"]
    (old_file,) = folder.iterdir()
    new_code = a.autobackup.new_recovery_code()
    assert new_code != old_code
    new_file = max(folder.iterdir())
    assert new_file != old_file
    _, _, opened = backup_mod.open_backup(new_file.read_bytes(), recovery_code=new_code)
    assert opened == "recovery code"
    with pytest.raises(BackupError, match="wrong recovery code"):
        backup_mod.open_backup(new_file.read_bytes(), recovery_code=old_code)
    backup_mod.open_backup(old_file.read_bytes(), recovery_code=old_code)  # older backups keep the old code
    assert backup_mod.open_backup(new_file.read_bytes(), password=PASSWORD)[2] == "password"
    a.close()


def _header(data: bytes) -> tuple[dict, bytes]:
    line = data[len(backup_mod.ENCRYPTED_MAGIC):].split(b"\n", 1)[0]
    return json.loads(line), line


def test_format_3_header_and_tampering(tmp_path):
    a, folder, st = _configured(tmp_path)
    data = next(folder.iterdir()).read_bytes()
    assert data.startswith(backup_mod.ENCRYPTED_MAGIC)
    header, header_line = _header(data)
    assert header["format"] == "rprov.backup-enc/3" and header["cipher"] == "AES-256-GCM"
    assert header["chunk_size"] == backup_mod.CHUNK_SIZE
    assert [slot["kind"] for slot in header["slots"]] == ["password", "recovery"]
    for plaintext in (b"Numerical experiment", b"SQLite format 3", b"PRIVATE KEY"):
        assert plaintext not in data
    # Changing anything in the header breaks it (it is authenticated with every piece).
    forged = data.replace(b'"inner": "rprov.backup/1"', b'"inner": "rprov.backup/9"', 1)
    with pytest.raises(BackupError, match="damaged"):
        backup_mod.open_backup(forged, password=PASSWORD)
    # Swapping in another backup's wrapped key does not open it either.
    a.autobackup.run("again")
    other = max(folder.iterdir()).read_bytes()
    header["slots"][0] = _header(other)[0]["slots"][0]
    swapped = backup_mod.ENCRYPTED_MAGIC + json.dumps(header, sort_keys=True).encode() + data[
        len(backup_mod.ENCRYPTED_MAGIC) + len(header_line):]
    with pytest.raises(BackupError, match="damaged"):
        backup_mod.open_backup(swapped, password=PASSWORD)
    a.close()


@pytest.mark.parametrize("size", [0, 1, 4095, 4096, 4097, 3 * 4096, 3 * 4096 + 17])
def test_pieces_round_trip_and_resist_cutting_and_reordering(size):
    import secrets as s

    plain = s.token_bytes(size)
    key = s.token_bytes(32)
    out = io.BytesIO()
    backup_mod.seal_stream(io.BytesIO(plain), out, key, PASSWORD, None, chunk_size=4096)
    sealed = out.getvalue()
    assert backup_mod.open_backup(sealed, password=PASSWORD)[0] == plain
    header_end = sealed.index(b"\n", len(backup_mod.ENCRYPTED_MAGIC)) + 1
    body = sealed[header_end:]
    pieces = [body[i:i + 4096 + 16] for i in range(0, len(body), 4096 + 16)]
    assert len(pieces) == size // 4096 + 1  # the last piece is always short, possibly empty
    with pytest.raises(BackupError):  # the last piece cut off
        backup_mod.open_backup(sealed[:header_end] + b"".join(pieces[:-1]), password=PASSWORD)
    with pytest.raises(BackupError):  # cut in the middle of a piece
        backup_mod.open_backup(sealed[:-5], password=PASSWORD)
    if len(pieces) >= 3:
        reordered = pieces[:]
        reordered[0], reordered[1] = reordered[1], reordered[0]
        with pytest.raises(BackupError, match="damaged"):
            backup_mod.open_backup(sealed[:header_end] + b"".join(reordered), password=PASSWORD)


def test_format_2_backups_still_restore(tmp_path):
    a = make_ctx(tmp_path / "a")
    build_log(a)
    key = backup_mod.secrets.token_bytes(32)
    _, plain = create_plain_backup(a, backup_mod.key_passphrase(key), key_protection="backup-key")
    code = backup_mod.new_recovery_code()
    old = backup_mod.seal_backup(plain, key, PASSWORD, backup_mod.make_recovery(code))
    assert old.startswith(backup_mod.ENCRYPTED_MAGIC_V2)
    a.close()
    b = make_ctx(tmp_path / "b", keystore=MemoryKeyStore())
    assert restore_backup(b, old, recovery_code=code)["opened_with"] == "recovery code"
    b.close()


def test_crafted_kdf_parameters_are_refused_quickly():
    plain = b"x"
    enc = bytearray(backup_mod.encrypt_backup(plain, PASSWORD))
    forged = bytes(enc).replace(b'"r": 8', b'"r": 1048576', 1)
    with pytest.raises(BackupError, match="unsupported"):
        backup_mod.decrypt_backup(forged, PASSWORD)
    huge_n = bytes(enc).replace(b'"n": 16384', b'"n": 1048576', 1)  # 1 GiB of memory with r = 8
    with pytest.raises(BackupError, match="unsupported"):
        backup_mod.decrypt_backup(huge_n, PASSWORD)


def test_recovery_code_typed_with_other_dashes():
    code = backup_mod.new_recovery_code()
    assert backup_mod.normalize_recovery_code(code.replace("-", "\u2013")) == code.replace("-", "")
    assert backup_mod.normalize_recovery_code(code.replace("-", " \u2014 ")) == code.replace("-", "")


def test_format_1_backups_still_restore(tmp_path):
    a = make_ctx(tmp_path / "a")
    build_log(a)
    _, plain = create_plain_backup(a, PASSWORD)
    old = backup_mod.encrypt_backup(plain, PASSWORD)
    a.close()
    b = make_ctx(tmp_path / "b", keystore=MemoryKeyStore())
    with pytest.raises(BackupError, match="older backup"):
        restore_backup(b, old, recovery_code="0" * 24)
    assert restore_backup(b, old, PASSWORD)["opened_with"] == "password"
    b.close()


def test_location_checks(tmp_path, monkeypatch):
    from app.services import autobackup

    ctx = make_ctx(tmp_path / "a")
    ctx.ledger.init_identity("L")
    data_dir = ctx.settings.data_dir
    assert autobackup.check_location(str(data_dir / "bk"), data_dir)["kind"] == "inside-data"
    with pytest.raises(BackupError, match="outside the app's data folder"):
        ctx.autobackup.configure(str(data_dir / "bk"), PASSWORD, create=True)
    new = autobackup.check_location(str(tmp_path / "new-folder"), data_dir)
    assert new["ok"] and new["creates"] and new["kind"] == "same-disk"
    assert "lost with it" in new["warning"]
    assert not autobackup.check_location("relative/path", data_dir)["ok"]

    icloud = tmp_path / "Mobile Documents" / "com~apple~CloudDocs"
    icloud.mkdir(parents=True)
    monkeypatch.setattr(autobackup, "ICLOUD_DRIVE", icloud)
    synced = autobackup.check_location(str(icloud / "Research Provenance Backups"), data_dir)
    assert synced["ok"] and synced["kind"] == "synced" and synced["label"] == "iCloud Drive" and synced["safe"]
    # The live database must not live in a synced folder; backups may.
    assert autobackup.data_dir_warning(data_dir) is None
    warning = autobackup.data_dir_warning(icloud / "rprov")
    assert "iCloud Drive" in warning and "database" in warning
    ctx.close()


def test_recovery_code_over_http(tmp_path):
    a = make_ctx(tmp_path / "a")
    folder = tmp_path / "bk"
    with TestClient(create_app(a), base_url="http://127.0.0.1:8765") as cl:
        cl.headers["X-RPROV-Token"] = a.session_token
        cl.post("/api/identity", json={"author_label": "HTTP"})
        check = cl.get("/api/backup/check", params={"location": str(folder)}).json()
        assert check["creates"] and check["kind"] == "same-disk"
        r = cl.post("/api/backup/settings", json={"location": str(folder), "password": PASSWORD, "create": True})
        code = r.json()["recovery_code"]
        r = cl.post("/api/backup/settings", json={"location": str(folder), "password": "another password"})
        assert "recovery_code" not in r.json()  # changing the password keeps the same code
        r = cl.post("/api/backup/recovery-code")
        assert r.status_code == 200 and r.json()["recovery_code"] != code
        code = r.json()["recovery_code"]
        assert cl.get("/api/status").json()["data_dir_warning"] is None
        latest = max(folder.iterdir()).read_bytes()
    a.close()
    b = make_ctx(tmp_path / "b", keystore=MemoryKeyStore())
    with TestClient(create_app(b), base_url="http://127.0.0.1:8765") as cl:
        cl.headers["X-RPROV-Token"] = b.session_token
        r = cl.post("/api/restore", files={"file": ("x.rprovbackup", latest, "application/octet-stream")})
        assert r.status_code == 400 and "password or the recovery code" in r.text
        r = cl.post("/api/restore", data={"recovery_code": code},
                    files={"file": ("x.rprovbackup", latest, "application/octet-stream")})
        assert r.status_code == 200, r.text
        assert r.json()["opened_with"] == "recovery code" and r.json()["backup"]["needs_password"]
    b.close()


# ---------------------------------------------------------------- restoring on the same Mac (D-040)


def _shared_keychain_pair(tmp_path):
    """The real install and a restore-drill copy on the same Mac: one keychain for both."""
    keychain = MemoryKeyStore()
    real = make_ctx(tmp_path / "real", keystore=keychain)
    build_log(real)
    folder = tmp_path / "icloud"
    code = real.autobackup.configure(str(folder), PASSWORD, create=True)["recovery_code"]
    drill = make_ctx(tmp_path / "drill", keystore=keychain)
    return real, drill, folder, code, keychain


@pytest.mark.parametrize("secret", ["password", "recovery code"])
def test_a_restored_copy_does_not_back_up_by_itself(tmp_path, secret):
    real, drill, folder, code, keychain = _shared_keychain_pair(tmp_path)
    real.autobackup.configure(str(folder), "the newer password")  # changed since that backup was made
    before = sorted(p.name for p in folder.iterdir())
    data = (folder / before[0]).read_bytes()  # made with PASSWORD
    real_key = private_key_raw(keychain.load(real.ledger.installation))

    if secret == "password":
        restore_backup(drill, data, PASSWORD)
        drill.autobackup.adopt_restored_password(PASSWORD)
    else:
        restore_backup(drill, data, recovery_code=code)
        drill.autobackup.adopt_restored_password(None)

    # The real install's keychain entries are untouched: same key, still the newer password.
    assert private_key_raw(keychain.load(real.ledger.installation)) == real_key
    assert real.autobackup._password() == "the newer password"
    # The copy knows the folder but stays paused until the author confirms it.
    st = drill.autobackup.status()
    assert st["location"] == str(folder) and st["state"] == "paused" and st["paused_after_restore"]
    assert drill.autobackup.maybe_run("hourly")["ran"] is False
    drill.autobackup.debounce = 0
    drill.ledger.create_project("a change in the copy")
    drill.autobackup.schedule()
    assert sorted(p.name for p in folder.iterdir()) == before  # nothing written
    real.close()
    drill.close()


def test_resuming_after_restore_keeps_each_copys_files_apart(tmp_path, monkeypatch):
    from app.services import autobackup

    monkeypatch.setattr(autobackup, "KEEP_BACKUPS", 2)
    real, drill, folder, code, _ = _shared_keychain_pair(tmp_path)
    for _ in range(2):
        real.autobackup.run("more")
    real_files = sorted(p.name for p in folder.iterdir())
    assert len(real_files) == 2
    restore_backup(drill, (folder / real_files[-1]).read_bytes(), PASSWORD)
    drill.autobackup.adopt_restored_password(PASSWORD)
    st = drill.autobackup.resume()
    assert st["state"] != "paused" and st["auto"]
    for _ in range(3):
        drill.autobackup.run("drill")
    names = sorted(p.name for p in folder.iterdir())
    assert set(real_files) <= set(names)  # the copy never prunes the other copy's backups
    assert len(names) == 4
    real.close()
    drill.close()


def test_restore_refuses_to_replace_a_different_key_in_the_keychain(tmp_path):
    real, drill, folder, code, keychain = _shared_keychain_pair(tmp_path)
    from provenance_core.signing import generate_private_key

    keychain.save(real.ledger.installation, generate_private_key())
    data = next(folder.iterdir()).read_bytes()
    with pytest.raises(BackupError, match="different signing key"):
        restore_backup(drill, data, PASSWORD)
    assert drill.ledger.record_count() == 0
    real.close()
    drill.close()


# ---------------------------------------------------------------- two Macs, one backup folder (D-041)


def _old_and_new_mac(tmp_path):
    """The old Mac keeps running; the new Mac restored from its backup and resumed backups."""
    old = make_ctx(tmp_path / "old-mac", keystore=MemoryKeyStore())
    build_log(old)
    folder = tmp_path / "icloud"
    old.autobackup.configure(str(folder), PASSWORD, create=True)
    new = make_ctx(tmp_path / "new-mac", keystore=MemoryKeyStore())
    restore_backup(new, max(folder.iterdir()).read_bytes(), PASSWORD)
    new.autobackup.adopt_restored_password(PASSWORD)
    return old, new, folder


def test_both_macs_notice_each_other(tmp_path):
    old, new, folder = _old_and_new_mac(tmp_path)
    # Before the new Mac writes anything, nobody sees a second active copy.
    assert old.autobackup.status()["other_copy"] is None
    assert new.autobackup.status()["other_copy"] is None  # the old Mac's files predate the restore
    new.autobackup.resume()
    st = old.autobackup.status()
    assert st["other_copy"] is not None and st["state"] == "other-copy"
    assert new.autobackup.status()["other_copy"] is None
    # The old Mac keeps adding steps: now the new Mac sees it too.
    old.ledger.create_entry(EntryInput(old.ledger.projects()[0].id, "note", "Added on the old Mac"))
    old.autobackup.run("change")
    st = new.autobackup.status()
    assert st["other_copy"] is not None and st["state"] == "other-copy"
    assert st["other_copy"]["last_backup"].endswith("Z")
    # "That copy is gone": the warning stops until the other copy writes again.
    assert new.autobackup.acknowledge_other_copy()["other_copy"] is None
    old.autobackup.run("again")
    assert new.autobackup.status()["other_copy"] is not None
    old.close()
    new.close()


def test_own_older_file_names_are_not_another_copy(tmp_path):
    ctx = make_ctx(tmp_path / "a")
    ctx.ledger.init_identity("A")
    folder = tmp_path / "bk"
    ctx.autobackup.configure(str(folder), PASSWORD, create=True)
    inst = ctx.ledger.installation[:8]
    # A file named the way versions before per-copy ids named them (this copy's own past).
    (folder / f"rprov-backup-{inst}-20261011-044417-152.rprovbackup").write_bytes(b"x")
    assert ctx.autobackup.status()["other_copy"] is None
    ctx.close()


def test_other_copy_over_http(tmp_path):
    old, new, folder = _old_and_new_mac(tmp_path)
    new.autobackup.resume()
    with TestClient(create_app(old), base_url="http://127.0.0.1:8765") as cl:
        cl.headers["X-RPROV-Token"] = old.session_token
        assert cl.get("/api/status").json()["backup"]["state"] == "other-copy"
        r = cl.post("/api/backup/other-copy/acknowledge")
        assert r.status_code == 200 and r.json()["other_copy"] is None
    old.close()
    new.close()


# ---------------------------------------------------------------- copied folders, per-copy passwords (D-042)


def _reopen(path, keystore):
    from app.config import Settings
    from app.services.context import AppContext
    from provenance_core.providers.mock import MockProvider

    settings = Settings(data_dir=path, port=8765, tsa="mock", btc="mock", keystore="memory")
    return AppContext.create(settings, keystore=keystore,
                             providers={"tsa": MockProvider("tsa"), "btc": MockProvider("btc")})


def test_a_copied_data_folder_becomes_its_own_copy(tmp_path, monkeypatch):
    """Migration Assistant / Time Machine / cp -r copy the database *and* the keychain."""
    import shutil

    from app.services import autobackup

    monkeypatch.setattr(autobackup, "KEEP_BACKUPS", 3)
    keychain = MemoryKeyStore()
    old = make_ctx(tmp_path / "old", keystore=keychain)
    build_log(old)
    folder = tmp_path / "icloud"
    old.autobackup.configure(str(folder), PASSWORD, create=True)
    old_dir = old.settings.data_dir
    old.close()
    new_dir = tmp_path / "new-mac" / "rprov"
    shutil.copytree(old_dir, new_dir)
    old = _reopen(old_dir, keychain)
    new = _reopen(new_dir, keychain)

    assert old.autobackup.status()["state"] != "paused"  # the original carries on
    st = new.autobackup.status()
    assert st["state"] == "paused" and st["paused_reason"] == "copied"
    assert new.autobackup.run("hourly")["ran"] is False  # nothing written until confirmed
    assert st["needs_password"]  # its own keychain entry: the original's is never shared
    new.autobackup.configure(str(folder), PASSWORD)  # the author confirms on the new Mac
    assert new.ledger.meta("backup_copy") != old.ledger.meta("backup_copy")
    for _ in range(4):
        old.autobackup.run("old mac")
        new.autobackup.run("new mac")
    names = [p.name for p in folder.iterdir()]
    for ctx in (old, new):
        mine = [n for n in names if f"-{ctx.ledger.meta('backup_copy')}-" in n]
        assert len(mine) == 3  # each keeps its own newest three; neither deletes the other's
    assert old.autobackup.status()["other_copy"] and new.autobackup.status()["other_copy"]
    old.close()
    new.close()


def test_a_drill_copy_cannot_change_the_real_password(tmp_path):
    real, drill, folder, code, keychain = _shared_keychain_pair(tmp_path)
    restore_backup(drill, next(folder.iterdir()).read_bytes(), recovery_code=code)
    drill.autobackup.configure(str(tmp_path / "elsewhere"), "drill throwaway", create=True)
    assert real.autobackup._password() == PASSWORD
    assert drill.autobackup._password() == "drill throwaway"
    real.close()
    drill.close()


def test_the_pause_is_enforced_by_the_server(tmp_path):
    real, drill, folder, code, keychain = _shared_keychain_pair(tmp_path)
    restore_backup(drill, next(folder.iterdir()).read_bytes(), PASSWORD)
    drill.autobackup.adopt_restored_password(PASSWORD)
    before = sorted(folder.iterdir())
    assert drill.autobackup.run("manual")["ran"] is False
    with pytest.raises(BackupError, match="confirm the backup folder"):
        drill.autobackup.new_recovery_code()
    assert sorted(folder.iterdir()) == before
    real.close()
    drill.close()


def test_recovery_code_restore_is_paused_and_asks_for_a_password(tmp_path):
    a, folder, st = _configured(tmp_path)
    fingerprint = st["key_fingerprint"]
    assert len(fingerprint) == 19
    data = next(folder.iterdir()).read_bytes()
    a.close()
    b = make_ctx(tmp_path / "b", keystore=MemoryKeyStore())
    summary = restore_backup(b, data, recovery_code=st["recovery_code"])
    assert summary["key_fingerprint"] == fingerprint  # the same as on the printed recovery sheet
    st = b.autobackup.status()
    assert st["state"] == "paused" and st["needs_password"] and st["paused_after_restore"]
    b.close()


def test_a_password_set_up_before_per_copy_entries_keeps_working(tmp_path):
    ctx = make_ctx(tmp_path / "a")
    ctx.ledger.init_identity("A")
    folder = tmp_path / "bk"
    folder.mkdir()
    ctx.ledger.set_meta("backup_location", str(folder))
    ctx.ledger.set_meta("backup_auto", "1")
    ctx.keystore.save_secret(f"backup-password:{ctx.ledger.installation}", PASSWORD)  # older entry name
    st = ctx.autobackup.status()
    assert st["configured"] and st["state"] != "paused"
    assert ctx.autobackup.run("after update")["ran"]
    ctx.close()


def test_saving_a_step_does_not_wait_for_a_running_backup(tmp_path, monkeypatch):
    import threading
    import time

    from app.services import autobackup

    ctx = make_ctx(tmp_path / "a")
    build_log(ctx)
    ctx.autobackup.configure(str(tmp_path / "bk"), PASSWORD, create=True)
    started = threading.Event()
    real_write = autobackup.write_backup_file

    def slow_write(*args, **kwargs):
        started.set()
        time.sleep(1.5)
        return real_write(*args, **kwargs)

    monkeypatch.setattr(autobackup, "write_backup_file", slow_write)
    ctx.autobackup.debounce = 30  # the change only schedules a later backup
    ctx.ledger.set_meta("backup_last_fingerprint", "")
    worker = threading.Thread(target=ctx.autobackup.run, args=("slow",))
    worker.start()
    started.wait(5)
    t0 = time.monotonic()
    ctx.ledger.create_entry(EntryInput(ctx.ledger.projects()[0].id, "note", "saved during a backup"))
    assert time.monotonic() - t0 < 1.0
    worker.join()
    ctx.close()
