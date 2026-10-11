"""Evidence bundle layout ``rprov.bundle/1`` (PRD §12) and a reader for it.

The reader never extracts anything: it only opens paths it constructs from
validated record IDs and payload-declared file names, from a directory or a zip.
``bundle.json`` is an unsigned index — the verifier re-derives everything that
matters from manifests, payloads, signatures and proofs.
"""

from __future__ import annotations

import json
import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .records import is_record_id, is_safe_file_name
from .verify import RecordMaterial

BUNDLE_FORMAT = "rprov.bundle/1"
DISCLOSURE_LEVELS = ("full", "structure", "existence")
_ID = re.compile(r"\A[0-9a-f]{64}\Z")


class BundleError(ValueError):
    """The bundle cannot be read at all (not a partial verification failure)."""


def manifest_path(rid: str) -> str:
    return f"manifests/{rid}.json"


def ots_path(rid: str) -> str:
    return f"manifests/{rid}.json.ots"


def tsr_path(rid: str) -> str:
    return f"proofs/{rid}.tsr"


def signature_path(rid: str) -> str:
    return f"signatures/{rid}.sig"


def payload_path(rid: str) -> str:
    return f"payloads/{rid}.json"


def body_path(rid: str) -> str:
    return f"content/{rid}/body.md"


def file_path(rid: str, name: str) -> str:
    return f"content/{rid}/files/{name}"


class _Source:
    """Read-only view of a bundle directory or zip file."""

    def __init__(self, path: Path):
        self.path = path
        self.zip: zipfile.ZipFile | None = None
        self.prefix = ""
        if path.is_file():
            try:
                self.zip = zipfile.ZipFile(path)
            except zipfile.BadZipFile as exc:
                raise BundleError(f"{path} is not a zip file") from exc
            names = self.zip.namelist()
            # Allow the whole bundle to sit inside one top-level folder.
            if "bundle.json" not in names:
                tops = {n.split("/", 1)[0] for n in names if "/" in n}
                if len(tops) == 1 and f"{next(iter(tops))}/bundle.json" in names:
                    self.prefix = next(iter(tops)) + "/"
            self._names = set(names)
        elif not path.is_dir():
            raise BundleError(f"{path} does not exist")

    def read(self, rel: str) -> bytes | None:
        rel = posixpath.normpath(rel)
        if rel.startswith("../") or rel.startswith("/"):
            raise BundleError(f"refusing path {rel}")
        if self.zip is not None:
            name = self.prefix + rel
            if name not in self._names:
                return None
            return self.zip.read(name)
        p = self.path / rel
        return p.read_bytes() if p.is_file() else None

    def listdir(self, rel: str) -> list[str]:
        rel = rel.rstrip("/") + "/"
        if self.zip is not None:
            base = self.prefix + rel
            out = set()
            for n in self._names:
                if n.startswith(base) and n != base:
                    out.add(n[len(base) :].split("/", 1)[0])
            return sorted(out)
        p = self.path / rel
        return sorted(x.name for x in p.iterdir()) if p.is_dir() else []

    def exists_dir(self, rel: str) -> bool:
        if self.zip is not None:
            base = self.prefix + rel.rstrip("/") + "/"
            return any(n.startswith(base) for n in self._names)
        return (self.path / rel).is_dir()


@dataclass
class LoadedBundle:
    meta: dict
    chain_ids: list[str]
    materials: dict[str, RecordMaterial]
    identity_pem: bytes | None
    certs: dict[str, bytes] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)


def _json(src: _Source, rel: str) -> dict:
    data = src.read(rel)
    if data is None:
        raise BundleError(f"{rel} is missing")
    try:
        obj = json.loads(data)
    except ValueError as exc:
        raise BundleError(f"{rel} is not valid JSON: {exc}") from None
    if not isinstance(obj, dict):
        raise BundleError(f"{rel} must contain a JSON object")
    return obj


def load_bundle(path: str | Path) -> LoadedBundle:
    src = _Source(Path(path))
    meta = _json(src, "bundle.json")
    if meta.get("format") != BUNDLE_FORMAT:
        raise BundleError(f"unsupported bundle format {meta.get('format')!r} (expected {BUNDLE_FORMAT})")
    chain = _json(src, "chain.json")
    ids = chain.get("ids")
    if not isinstance(ids, list) or not all(isinstance(i, str) and _ID.match(i) for i in ids):
        raise BundleError("chain.json must list record IDs")
    declared = {}
    for item in meta.get("records") or []:
        if isinstance(item, dict) and is_record_id(item.get("id")):
            declared[item["id"]] = item.get("disclosure")
    materials: dict[str, RecordMaterial] = {}
    for rid in ids:
        payload = src.read(payload_path(rid))
        content = None
        if declared.get(rid) == "full" or src.exists_dir(f"content/{rid}"):
            content = {}
            body = src.read(body_path(rid))
            if body is not None:
                content["body"] = body
            for name in src.listdir(f"content/{rid}/files"):
                if is_safe_file_name(name):
                    data = src.read(file_path(rid, name))
                    if data is not None:
                        content[f"files/{name}"] = data
                else:
                    content[f"files/{name}"] = b""  # reported as not listed in the payload
            for extra in src.listdir(f"content/{rid}"):
                if extra not in ("body.md", "files"):
                    content[extra] = src.read(f"content/{rid}/{extra}") or b""
        materials[rid] = RecordMaterial(
            record_id=rid,
            manifest_bytes=src.read(manifest_path(rid)),
            payload_bytes=payload,
            signature=src.read(signature_path(rid)),
            tsa_proof=src.read(tsr_path(rid)),
            btc_proof=src.read(ots_path(rid)),
            content=content,
        )
    certs = {}
    for name in src.listdir("certs"):
        data = src.read(f"certs/{name}")
        if data is not None:
            certs[name] = data
    return LoadedBundle(meta, ids, materials, src.read("identity/public_key.pem"), certs)
