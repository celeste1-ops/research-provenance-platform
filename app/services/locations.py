"""Where backups can go, per operating system (DECISIONS D-030, D-043).

Two questions: which folders does a sync service the author already uses copy off this
computer (iCloud Drive, OneDrive, Dropbox, Google Drive…), and which other disks are
attached. Nothing here touches the network; it only looks at local folders.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SUGGESTED_FOLDER_NAME = "Research Provenance Backups"
_GOOGLE_DRIVE_ROOTS = ("My Drive", "我的云端硬盘", "Meine Ablage", "Mon Drive", "Mi unidad")


def _existing(roots: list[tuple[str, Path]]) -> list[tuple[str, Path]]:
    out, seen = [], set()
    for label, path in roots:
        try:
            if path.is_dir() and path.resolve() not in seen:
                seen.add(path.resolve())
                out.append((label, path))
        except OSError:
            continue
    return out


def _dropbox_from_info(env) -> list[tuple[str, Path]]:
    """Dropbox writes its folder locations to info.json (custom locations included)."""
    out = []
    for base in (env.get("APPDATA"), env.get("LOCALAPPDATA")):
        if not base:
            continue
        info = Path(base) / "Dropbox" / "info.json"
        try:
            data = json.loads(info.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for kind, entry in data.items():
            if isinstance(entry, dict) and entry.get("path"):
                out.append(("Dropbox" if kind == "personal" else f"Dropbox ({kind})", Path(entry["path"])))
    return out


def windows_drives() -> list[Path]:
    if hasattr(os, "listdrives"):  # Python 3.12+ on Windows
        try:
            return [Path(d) for d in os.listdrives()]
        except OSError:
            return []
    return [Path(f"{c}:\\") for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if Path(f"{c}:\\").exists()]


def sync_roots(platform: str | None = None, home: Path | None = None, env=None,
               drives: list[Path] | None = None) -> list[tuple[str, Path]]:
    """Folders on this computer that a sync service copies elsewhere, as (service, folder)."""
    platform = platform or sys.platform
    home = home or Path.home()
    env = os.environ if env is None else env
    roots: list[tuple[str, Path]] = []
    if platform == "darwin":
        roots.append(("iCloud Drive", home / "Library" / "Mobile Documents" / "com~apple~CloudDocs"))
        storage = home / "Library" / "CloudStorage"  # Dropbox, Google Drive, OneDrive, Box…
        try:
            for entry in sorted(storage.iterdir()):
                if entry.is_dir() and not entry.name.startswith("."):
                    roots.append((entry.name.split("-")[0], entry))
        except OSError:
            pass
        roots.append(("Dropbox", home / "Dropbox"))
    elif platform == "win32":
        for var, label in (("OneDriveConsumer", "OneDrive"), ("OneDriveCommercial", "OneDrive (work or school)"),
                           ("OneDrive", "OneDrive")):
            if env.get(var):
                roots.append((label, Path(env[var])))
        roots.append(("iCloud Drive", home / "iCloudDrive"))
        roots.extend(_dropbox_from_info(env))
        roots.append(("Dropbox", home / "Dropbox"))
        for drive in windows_drives() if drives is None else drives:  # Google Drive for desktop: G:\My Drive
            for name in _GOOGLE_DRIVE_ROOTS:
                roots.append(("Google Drive", drive / name))
        roots.append(("Google Drive", home / "Google Drive"))
    else:
        roots.append(("Dropbox", home / "Dropbox"))
    return _existing(roots)


def synced_service(path: Path, roots: list[tuple[str, Path]] | None = None) -> str | None:
    """Name of the sync service whose folder contains ``path``, if any."""
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        return None
    for label, root in sync_roots() if roots is None else roots:
        try:
            base = root.resolve()
        except OSError:
            continue
        if resolved == base or base in resolved.parents:
            return label
    return None


def _device(path: Path) -> int | None:
    try:
        return os.stat(path).st_dev
    except OSError:
        return None


def external_drives(data_dir: Path, platform: str | None = None) -> list[tuple[str, Path]]:
    """Other disks (external drives, other partitions, network drives) as (label, root)."""
    platform = platform or sys.platform
    own = _device(data_dir)
    out: list[tuple[str, Path]] = []
    if platform == "darwin":
        candidates = []
        try:
            candidates = [(f"Drive “{v.name}”", v) for v in sorted(Path("/Volumes").iterdir()) if not v.is_symlink()]
        except OSError:
            pass
    elif platform == "win32":
        candidates = [(f"Drive {str(d).rstrip(chr(92))}", d) for d in windows_drives()]
    else:
        user = os.environ.get("USER", "")
        candidates = []
        for base in (Path("/media") / user, Path("/run/media") / user):
            try:
                candidates += [(f"Drive “{v.name}”", v) for v in sorted(base.iterdir())]
            except OSError:
                pass
    for label, root in candidates:
        dev = _device(root)
        if dev is not None and dev != own:
            out.append((label, root))
    return out


def suggestions(data_dir: Path) -> list[dict]:
    """Folders worth offering in the backup dialog: sync folders first, then other disks."""
    out = []
    synced = sync_roots()
    for label, root in synced:
        out.append({"path": str(root / SUGGESTED_FOLDER_NAME), "label": label, "kind": "synced"})
    synced_devices = {_device(root) for _, root in synced}
    for label, root in external_drives(data_dir):
        if _device(root) in synced_devices and sys.platform == "win32":
            continue  # e.g. the drive Google Drive for desktop mounts is offered as Google Drive already
        out.append({"path": str(root / SUGGESTED_FOLDER_NAME), "label": label, "kind": "external"})
    return out
