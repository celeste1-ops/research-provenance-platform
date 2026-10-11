"""Watched folders and the inbox (DECISIONS D-049).

The author picks a folder (drafts, data, figures) and a project. Once a minute the app looks for
files that are new or changed. A file that has not changed for two minutes is a new version:
its bytes are copied into ``<data folder>/inbox`` and its SHA-256 is date-stamped at once (only
the hash goes out, as for any step). It then waits in the inbox, outside the signed record:
the author records it with one click (title, type and "new version of" its previous step are
filled in) or throws it away — which is possible because it never entered the record.

A recorded version carries its inbox date stamp as an attachment ``<name>.tsr`` next to the file
(provenance_core.verify.file_stamps): anyone can check that the file existed by then, even though
the step itself is later. Editors that save every minute therefore do not fill the record with
versions nobody wants.

Each space has its own watched folders and inbox. The inbox is not backed up: it holds copies
of files that are still in their folders and versions not yet part of the record.
"""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import shutil
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.config import MAX_UPLOAD_BYTES
from app.i18n import tr_message
from app.services.ledger import EntryInput, LedgerError, UploadedFile
from provenance_core.providers.base import ProviderRejected, ProviderUnavailable
from provenance_core.records import safe_file_name
from provenance_core.verify import STAMP_SUFFIX

log = logging.getLogger("rprov.inbox")

WATCH_FILE = "watched_folders.json"
INBOX_DIR = "inbox"
SETTLE_SECONDS = 120  # unchanged this long = a finished version
MAX_FILES = 2000  # a folder with more files is probably not the one meant (a whole home folder)
MAX_EXISTING = 100  # existing files that may be put into the inbox at once
IGNORED_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini", "Icon\r"}
IGNORED_DIRS = {".git", ".svn", ".hg", "node_modules", "__pycache__", ".venv", "venv", ".idea", ".vscode",
                ".ipynb_checkpoints"}
IGNORED_ENDINGS = ("~", ".tmp", ".temp", ".swp", ".swo", ".swx", ".part", ".crdownload", ".download", ".lock",
                   ".bak", STAMP_SUFFIX)
TYPE_BY_EXTENSION = {
    **dict.fromkeys(("png", "jpg", "jpeg", "gif", "svg", "tif", "tiff", "webp", "eps", "bmp", "heic"), "figure"),
    **dict.fromkeys(("csv", "tsv", "xlsx", "xls", "json", "parquet", "h5", "hdf5", "nc", "mat", "npy", "npz",
                     "sav", "dta", "feather", "rds", "rdata", "sqlite", "db", "xml"), "dataset"),
    **dict.fromkeys(("py", "r", "ipynb", "m", "jl", "c", "cc", "cpp", "h", "hpp", "js", "ts", "java", "go", "rs",
                     "sh", "sql", "do", "f90", "f", "stan", "rmd", "qmd"), "code"),
}


class InboxError(Exception):
    pass


def ignored(name: str) -> bool:
    """Hidden files, editor and office lock / temporary files, and stamps themselves."""
    return (name in IGNORED_NAMES or name.startswith((".", "~$", "~"))
            or name.lower().endswith(IGNORED_ENDINGS))


def guess_type(name: str) -> str:
    return TYPE_BY_EXTENSION.get(name.rsplit(".", 1)[-1].lower() if "." in name else "", "document")


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _walk(folder: Path):
    """(relative path with /, absolute path, stat) of every file worth watching."""
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if d not in IGNORED_DIRS and not d.startswith("."))
        for name in sorted(files):
            if ignored(name):
                continue
            path = Path(root) / name
            try:
                st = path.stat()
            except OSError:
                continue
            yield path.relative_to(folder).as_posix(), path, st


class Inbox:
    """The watched folders of one space and the versions waiting in its inbox."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.data_dir = Path(ctx.settings.data_dir)
        self.watch_file = self.data_dir / WATCH_FILE
        self.dir = self.data_dir / INBOX_DIR
        self.items_file = self.dir / "items.json"
        self._lock = threading.RLock()
        self._clock = time.time

    # ------------------------------------------------------------ storage

    def _read(self, path: Path, key: str) -> list[dict]:
        try:
            return json.loads(path.read_text(encoding="utf-8")).get(key, [])
        except (OSError, ValueError):
            return []

    def _write(self, path: Path, key: str, value: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps({key: value}, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)

    def _folders(self) -> list[dict]:
        return self._read(self.watch_file, "folders")

    def _items(self) -> list[dict]:
        return self._read(self.items_file, "items")

    def _blob(self, sha: str, suffix: str = "") -> Path:
        return self.dir / "files" / f"{sha}{suffix}"

    def has_folders(self) -> bool:
        return self.watch_file.exists() and bool(self._folders())

    def count(self) -> int:
        return len(self._items()) if self.items_file.exists() else 0

    # ------------------------------------------------------------ watched folders

    def _folder_path(self, path: str) -> Path:
        raw = (path or "").strip().strip('"')
        folder = Path(os.path.expanduser(raw)) if raw else None
        if folder is None or not folder.is_absolute():
            raise InboxError("choose a full folder path")
        if not folder.is_dir():
            raise InboxError("that folder does not exist")
        folder = folder.resolve()
        data = self.data_dir.resolve()
        if folder == data or data.is_relative_to(folder) or folder.is_relative_to(data):
            raise InboxError("choose a folder that does not contain the app's data folder")
        return folder

    def inspect(self, path: str) -> dict:
        folder = self._folder_path(path)
        files = too_large = 0
        for _rel, _p, st in _walk(folder):
            files += 1
            too_large += st.st_size > MAX_UPLOAD_BYTES
            if files > MAX_FILES:
                break
        return {"path": str(folder), "name": folder.name, "files": min(files, MAX_FILES + 1),
                "too_large": too_large, "too_many": files > MAX_FILES, "max_files": MAX_FILES,
                "max_existing": MAX_EXISTING,
                "already": any(Path(f["path"]) == folder for f in self._folders())}

    def add_folder(self, path: str, project_id: str, *, include_existing: bool = False) -> dict:
        info = self.inspect(path)
        if info["too_many"]:
            raise InboxError("this folder has too many files; choose the folder of one piece of work")
        if info["already"]:
            raise InboxError("this folder is already being watched")
        if include_existing and info["files"] > MAX_EXISTING:
            raise InboxError("too many files to put into the inbox at once")
        if project_id not in {p.id for p in self.ctx.ledger.projects()}:
            raise LedgerError("unknown project")
        folder = Path(info["path"])
        now = self._clock()
        state = {}
        for rel, p, st in _walk(folder):  # what is there now is known; only later changes are new
            if st.st_size > MAX_UPLOAD_BYTES:
                continue
            state[rel] = {"size": st.st_size, "mtime": st.st_mtime_ns, "changed": now,
                          "version": None if include_existing else _sha256(p), "pending": include_existing}
            if include_existing:
                state[rel]["changed"] = now - SETTLE_SECONDS  # settled already
        entry = {"id": uuid.uuid4().hex, "path": str(folder), "name": folder.name, "project_id": project_id,
                 "added": _now(), "checked": None, "error": None, "files": state, "steps": {}}
        with self._lock:
            folders = self._folders()
            folders.append(entry)
            self._write(self.watch_file, "folders", folders)
        return self._public(entry)

    def remove_folder(self, folder_id: str) -> None:
        """Stop watching; versions already in the inbox stay there until recorded or thrown away."""
        with self._lock:
            folders = self._folders()
            kept = [f for f in folders if f["id"] != folder_id]
            if len(kept) == len(folders):
                raise LedgerError("no such record")
            self._write(self.watch_file, "folders", kept)

    def _public(self, f: dict) -> dict:
        projects = {p.id: p.title for p in self.ctx.ledger.projects()}
        return {"id": f["id"], "path": f["path"], "name": f["name"], "project_id": f["project_id"],
                "project_title": projects.get(f["project_id"], ""), "added": f["added"], "checked": f["checked"],
                "error": tr_message(f["error"]) if f.get("error") else None, "files": len(f.get("files", {})),
                "recorded": len(f.get("steps", {}))}

    def status(self) -> dict:
        items = sorted(self._items(), key=lambda i: i["seen"], reverse=True)
        names = {f["id"]: f["name"] for f in self._folders()}
        return {"folders": [self._public(f) for f in self._folders()],
                "items": [{**i, "folder": names.get(i["folder_id"], "")} for i in items]}

    # ------------------------------------------------------------ looking for new versions

    def scan(self) -> int:
        """Look at every watched folder once (the background job runs this every minute); then
        date-stamp what is waiting for a stamp. Returns how many versions arrived."""
        arrived = 0
        with self._lock:
            folders = self._folders()
            for f in folders:
                try:
                    arrived += self._scan_one(f)
                    f["error"] = None
                except OSError as exc:
                    f["error"] = "the folder is not there (is the drive connected?)" if not Path(
                        f["path"]).is_dir() else f"could not read the folder ({exc.strerror or exc})"
                f["checked"] = _now()
            self._write(self.watch_file, "folders", folders)
        self.stamp_waiting()
        return arrived

    def _scan_one(self, f: dict) -> int:
        folder = Path(f["path"])
        if not folder.is_dir():
            raise FileNotFoundError(str(folder))
        now = self._clock()
        state = f.setdefault("files", {})
        arrived = 0
        seen = set()
        for rel, path, st in _walk(folder):
            seen.add(rel)
            if st.st_size > MAX_UPLOAD_BYTES:
                continue
            known = state.get(rel)
            if known is None or (known["size"], known["mtime"]) != (st.st_size, st.st_mtime_ns):
                state[rel] = {**(known or {"version": None}), "size": st.st_size, "mtime": st.st_mtime_ns,
                              "changed": now, "pending": True}
                continue
            if known.get("pending") and now - known["changed"] >= SETTLE_SECONDS:
                try:
                    sha = _sha256(path)
                    if sha != known.get("version"):
                        outcome = self._arrive(f, rel, path, sha)
                        if outcome is None:
                            continue  # changed while being copied: seen again at the next look
                        known["version"] = sha
                        arrived += outcome == "new"
                except OSError:
                    continue  # in use by another program (Windows) or just removed: the next look retries
                known["pending"] = False
        for rel in list(state):
            if rel not in seen:
                state[rel]["pending"] = False  # deleted for now; a later file with the same bytes is not new
        return arrived

    def _arrive(self, f: dict, rel: str, path: Path, sha: str) -> str | None:
        """Copy the version into the inbox: "new", "seen" (already waiting) or None (try again)."""
        blob = self._blob(sha)
        blob.parent.mkdir(parents=True, exist_ok=True)
        if not blob.exists():
            tmp = blob.with_name(blob.name + ".tmp")
            try:
                shutil.copyfile(path, tmp)
                if _sha256(tmp) != sha:
                    return None
                os.replace(tmp, blob)
            finally:
                tmp.unlink(missing_ok=True)
        name = path.name
        items = self._items()
        if any(i["folder_id"] == f["id"] and i["path"] == rel and i["sha256"] == sha for i in items):
            return "seen"
        items.append({
            "id": uuid.uuid4().hex, "folder_id": f["id"], "path": rel, "name": name, "sha256": sha,
            "size": blob.stat().st_size, "media_type": mimetypes.guess_type(name)[0] or "application/octet-stream",
            "node_type": guess_type(name), "seen": _now(), "stamp": None, "stamp_error": None,
            "previous": f.get("steps", {}).get(rel),
        })
        self._write(self.items_file, "items", items)
        return "new"

    def stamp_waiting(self) -> int:
        """Date-stamp the hash of every version still waiting for one (only the hash is sent)."""
        provider = self.ctx.anchors.providers.get("tsa")
        if provider is None:
            return 0
        done = 0
        with self._lock:
            items = self._items()
            for item in items:
                if item.get("stamp"):
                    continue
                try:
                    result = provider.submit(item["sha256"], self._blob(item["sha256"]).read_bytes())
                except (ProviderUnavailable, ProviderRejected) as exc:
                    item["stamp_error"] = str(exc)
                    break  # the service is unreachable now; the next look tries again
                except OSError as exc:
                    item["stamp_error"] = str(exc)
                    continue
                self._blob(item["sha256"], STAMP_SUFFIX).write_bytes(result.proof)
                item["stamp"] = {"time": result.verified_time, "provider": result.provider or provider.name}
                item["stamp_error"] = None
                done += 1
            if items:
                self._write(self.items_file, "items", items)
        return done

    # ------------------------------------------------------------ recording or throwing away

    def _take(self, item_id: str) -> dict:
        item = next((i for i in self._items() if i["id"] == item_id), None)
        if item is None:
            raise LedgerError("no such record")
        return item

    def _drop(self, item: dict) -> None:
        items = [i for i in self._items() if i["id"] != item["id"]]
        self._write(self.items_file, "items", items)
        if not any(i["sha256"] == item["sha256"] for i in items):
            self._blob(item["sha256"]).unlink(missing_ok=True)
            self._blob(item["sha256"], STAMP_SUFFIX).unlink(missing_ok=True)

    def discard(self, item_id: str) -> None:
        """Throw a version away: it never entered the record, so nothing of it remains."""
        with self._lock:
            self._drop(self._take(item_id))

    def record(self, item_id: str, *, title: str | None = None, node_type: str | None = None) -> str:
        """Make an inbox version a step: the file, its inbox date stamp next to it, and "new
        version of" the step of the file's previous recorded version."""
        with self._lock:
            item = self._take(item_id)
            folder = next((f for f in self._folders() if f["id"] == item["folder_id"]), None)
            project_id = folder["project_id"] if folder else None
            if project_id is None:
                projects = self.ctx.ledger.projects()
                project_id = projects[0].id if projects else ""
            name = safe_file_name(item["name"])
            if len(name) > 190:
                stem, dot, ext = name.rpartition(".")
                name = (stem[: 180 - len(ext)] + dot + ext) if dot else name[:190]
            files = [UploadedFile(name, self._blob(item["sha256"]).read_bytes(), item["media_type"])]
            tsr = self._blob(item["sha256"], STAMP_SUFFIX)
            if item.get("stamp") and tsr.exists():
                files.append(UploadedFile(name + STAMP_SUFFIX, tsr.read_bytes(), "application/timestamp-reply"))
            previous = item.get("previous")
            if folder is not None:  # a version recorded since this one arrived is the newer "previous"
                previous = folder.get("steps", {}).get(item["path"], previous)
            relations = [{"to": previous, "rel": "revises"}] if previous and self.ctx.ledger.record(previous) else []
            rid = self.ctx.ledger.create_entry(EntryInput(
                project_id=project_id, node_type=node_type or item["node_type"],
                title=(title or "").strip() or item["name"], files=files, relations=relations,
            ))
            if folder is not None:
                folders = self._folders()
                for f in folders:
                    if f["id"] == folder["id"]:
                        f.setdefault("steps", {})[item["path"]] = rid
                self._write(self.watch_file, "folders", folders)
            self._drop(item)
            return rid
