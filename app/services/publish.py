"""Putting an evidence bundle where others can get it (DECISIONS D-060).

* Into a git repository on this computer: the bundle is written unpacked into
  ``provenance/<title>/`` (GitHub shows VERIFY.md as a page; verify.py runs in that folder),
  committed there on its own, and pushed if the author asks.
* Into a draft deposit on Zenodo, which the author then publishes on zenodo.org (for a DOI).

Both only on the author's click, and only the bundle the author made, with the disclosure chosen
for each step — the same files the "Download" button gives.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from app.services.export import write_dir
from app.services.gitrepo import GitError, Repo
from provenance_core.providers.zenodo import Zenodo, ZenodoError

FOLDER = "provenance"
ZENODO_SECRET = "zenodo"  # in the system keychain: {"token": …, "sandbox": bool}


class PublishError(Exception):
    pass


def folder_name(title: str) -> str:
    """A folder name made from the bundle's title (letters of any script are kept)."""
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "-", title)
    return re.sub(r"[\s-]+", "-", name).strip(" .-")[:80] or "evidence"


def to_repository(files: dict[str, bytes], title: str, path: str, *, commit: bool = True,
                  push: bool = False) -> dict:
    raw = (path or "").strip().strip('"')
    if not raw or not Path(raw).expanduser().is_dir():
        raise PublishError("choose the folder of a git repository on this computer")
    try:
        repo = Repo(Path(raw).expanduser())
        top = repo.toplevel()
        repo = Repo(top, repo.git)
    except GitError as exc:
        raise PublishError(str(exc)) from None
    rel = f"{FOLDER}/{folder_name(title)}"
    target = top / FOLDER / folder_name(title)
    if target.exists():
        if not (target / "bundle.json").is_file():
            raise PublishError(f"{rel} already exists and is not an evidence bundle; give the bundle another title")
        shutil.rmtree(target)  # an earlier bundle of the same title: its old version stays in git history
    write_dir(files, target)
    out = {"folder": str(target), "commit": None, "pushed": False, "remote_url": repo.remote_url()}
    if not commit:
        return out
    try:
        out["commit"] = repo.commit_paths([rel], f"Evidence bundle: {title}")
        if push:
            repo.push()
            out["pushed"] = True
    except GitError as exc:
        out["error"] = str(exc)
    return out


# ---------------------------------------------------------------- Zenodo


def zenodo_settings(keystore) -> dict | None:
    raw = keystore.load_secret(ZENODO_SECRET)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) and data.get("token") else None


def connect_zenodo(keystore, token: str, sandbox: bool, transport=None) -> None:
    client = Zenodo(token, sandbox, transport)
    try:
        client.check()
    except ZenodoError as exc:
        raise PublishError(str(exc)) from None
    finally:
        client.close()
    keystore.save_secret(ZENODO_SECRET, json.dumps({"token": token.strip(), "sandbox": bool(sandbox)}))


def forget_zenodo(keystore) -> None:
    keystore.save_secret(ZENODO_SECRET, "")


def zenodo_metadata(title: str, author_label: str | None, description: str) -> dict:
    return {
        "title": title,
        "upload_type": "dataset",
        "description": description,
        "creators": [{"name": author_label or "Unknown"}],
        "keywords": ["research history", "provenance", "evidence bundle"],
        "access_right": "open",
        "license": "cc-by-4.0",
        "prereserve_doi": True,
    }


def to_zenodo(keystore, filename: str, data: bytes, metadata: dict, transport=None) -> dict:
    settings = zenodo_settings(keystore)
    if settings is None:
        raise PublishError("connect Zenodo first: choose Zenodo under “Where should it go?” and paste a token")
    client = Zenodo(settings["token"], settings.get("sandbox", False), transport)
    try:
        return {**client.create_draft(filename, data, metadata), "sandbox": bool(settings.get("sandbox"))}
    except ZenodoError as exc:
        raise PublishError(str(exc)) from None
    finally:
        client.close()
