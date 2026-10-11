"""Backup folder suggestions on macOS and Windows (D-043), checked with fake folder layouts."""

from __future__ import annotations

import json

from app.services import locations


def test_mac_sync_folders(tmp_path):
    home = tmp_path / "home"
    icloud = home / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
    dropbox = home / "Library" / "CloudStorage" / "Dropbox"
    gdrive = home / "Library" / "CloudStorage" / "GoogleDrive-someone@example.com"
    for d in (icloud, dropbox, gdrive):
        d.mkdir(parents=True)
    roots = locations.sync_roots("darwin", home=home, env={})
    assert [label for label, _ in roots] == ["iCloud Drive", "Dropbox", "GoogleDrive"]
    assert locations.synced_service(gdrive / "Research", roots) == "GoogleDrive"
    assert locations.synced_service(home / "Documents", roots) is None


def test_windows_sync_folders(tmp_path):
    home = tmp_path / "Users" / "ada"
    onedrive = home / "OneDrive"
    work = home / "OneDrive - Example University"
    icloud = home / "iCloudDrive"
    custom_dropbox = tmp_path / "D" / "MyDropbox"
    g_drive = tmp_path / "G"
    for d in (onedrive, work, icloud, custom_dropbox, g_drive / "My Drive"):
        d.mkdir(parents=True)
    appdata = tmp_path / "AppData" / "Roaming"
    (appdata / "Dropbox").mkdir(parents=True)
    (appdata / "Dropbox" / "info.json").write_text(json.dumps({"personal": {"path": str(custom_dropbox)}}),
                                                   encoding="utf-8")
    env = {"OneDriveConsumer": str(onedrive), "OneDriveCommercial": str(work), "OneDrive": str(onedrive),
           "APPDATA": str(appdata)}
    roots = locations.sync_roots("win32", home=home, env=env, drives=[g_drive])
    labels = [label for label, _ in roots]
    assert labels == ["OneDrive", "OneDrive (work or school)", "iCloud Drive", "Dropbox", "Google Drive"]
    assert locations.synced_service(g_drive / "My Drive" / "Backups", roots) == "Google Drive"
    assert locations.synced_service(custom_dropbox / "x", roots) == "Dropbox"


def test_missing_folders_are_not_offered(tmp_path):
    assert locations.sync_roots("win32", home=tmp_path, env={"OneDrive": str(tmp_path / "nope")}, drives=[]) == []
    assert locations.sync_roots("linux", home=tmp_path, env={}) == []


def test_suggestions_list_sync_folders_then_other_disks(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    one = tmp_path / "OneDrive"
    one.mkdir()
    monkeypatch.setattr(locations, "sync_roots", lambda *a, **k: [("OneDrive", one)])
    monkeypatch.setattr(locations, "external_drives", lambda *a, **k: [("Drive E:", tmp_path / "E")])
    got = locations.suggestions(data)
    assert [(s["label"], s["kind"]) for s in got] == [("OneDrive", "synced"), ("Drive E:", "external")]
    assert got[0]["path"].endswith(locations.SUGGESTED_FOLDER_NAME)
