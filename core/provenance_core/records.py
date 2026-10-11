"""Records: manifest + payload, the six record kinds, and their schema (PRD §8).

A record is a small *manifest* and a *payload*, each canonicalized with JCS.
The record ID is SHA-256 of the manifest bytes; the manifest carries the SHA-256
of the payload bytes. Everything here is frozen by ``rprov.record/1`` (PRD §18).
"""

from __future__ import annotations

import hashlib
import re
import secrets
import unicodedata
import uuid
from datetime import UTC, datetime
from typing import Any

from .jcs import canonicalize

RECORD_SCHEMA = "rprov.record/1"

RECORD_KINDS = ("genesis", "entry", "link", "milestone", "statement", "retraction")

# The nine node types the app offers. Verifiers accept unknown types (PRD §18).
NODE_TYPES = (
    "idea",
    "note",
    "claim",
    "document",
    "code",
    "experiment",
    "dataset",
    "figure",
    "publication",
)

# The three relation types the app offers. Verifiers accept unknown ones (PRD §8).
RELATION_TYPES = ("revises", "derived_from", "uses")

STATEMENT_SOURCES = ("author", "ai")
IMPORT_LEVELS = ("L1", "L2")
IMPORT_PRECISIONS = ("year", "month", "day")

_HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"\A[0-9a-f]{7,64}\Z")
_UTC_SECONDS = re.compile(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
_CLAIMED_DATE = {
    "year": re.compile(r"\A\d{4}\Z"),
    "month": re.compile(r"\A\d{4}-(0[1-9]|1[0-2])\Z"),
    "day": re.compile(r"\A\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\Z"),
}

MANIFEST_KEYS = frozenset({"schema", "kind", "installation", "seq", "prev", "payload_sha256"})


class RecordError(ValueError):
    """Input that cannot become a valid record."""


# --------------------------------------------------------------------------- helpers


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def new_nonce() -> str:
    """32 random bytes, hex encoded: the per-payload salt (PRD §9)."""
    return secrets.token_bytes(32).hex()


def utc_now_seconds() -> str:
    return datetime.now(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_text(text: str | bytes) -> bytes:
    """Body text as stored, hashed and exported: UTF-8 with LF line endings."""
    if isinstance(text, bytes):
        try:
            text = text.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RecordError(f"text must be UTF-8: {exc}") from None
    if text.startswith("﻿"):
        text = text[1:]
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def safe_file_name(name: str) -> str:
    """Reduce an uploaded file name to a safe single path component (PRD S3)."""
    name = unicodedata.normalize("NFC", name or "")
    name = name.replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if ch.isprintable() and ch not in '<>:"|?*')
    name = name.strip().lstrip(".").strip()
    if not name:
        name = "file"
    if len(name) > 200:
        stem, dot, ext = name.rpartition(".")
        name = (stem[: 190 - len(ext)] + dot + ext) if dot else name[:200]
    return name


def is_safe_file_name(name: Any) -> bool:
    return isinstance(name, str) and bool(name) and safe_file_name(name) == name


def is_record_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_HEX64.match(value))


def _is_uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


# --------------------------------------------------------------------------- building


def file_descriptor(data: bytes, media_type: str, name: str | None = None) -> dict[str, Any]:
    desc: dict[str, Any] = {"sha256": sha256_hex(data), "size": len(data), "media_type": media_type}
    if name is not None:
        desc["name"] = name
    return desc


def build_manifest(kind: str, installation: str, seq: int, prev: str | None, payload_bytes: bytes) -> dict:
    return {
        "schema": RECORD_SCHEMA,
        "kind": kind,
        "installation": installation,
        "seq": seq,
        "prev": prev,
        "payload_sha256": sha256_hex(payload_bytes),
    }


def encode_record(
    kind: str, installation: str, seq: int, prev: str | None, payload: dict
) -> tuple[bytes, bytes, str]:
    """Validate and canonicalize a record. Returns (manifest_bytes, payload_bytes, record_id)."""
    errors = validate_payload(kind, payload)
    if errors:
        raise RecordError("; ".join(errors))
    payload_bytes = canonicalize(payload)
    manifest = build_manifest(kind, installation, seq, prev, payload_bytes)
    errors = validate_manifest(manifest)
    if errors:
        raise RecordError("; ".join(errors))
    manifest_bytes = canonicalize(manifest)
    return manifest_bytes, payload_bytes, sha256_hex(manifest_bytes)


def _base(local_time: str | None, nonce: str | None) -> dict[str, Any]:
    return {"nonce": nonce or new_nonce(), "local_time": local_time or utc_now_seconds(), "ext": {}}


def genesis_payload(author_label: str, public_key_hex: str, *, local_time=None, nonce=None) -> dict:
    return {**_base(local_time, nonce), "author_label": author_label, "public_key": public_key_hex}


def entry_payload(
    *,
    project_id: str,
    project_title: str,
    node_type: str,
    title: str,
    content: dict | None = None,
    external: dict | None = None,
    relations: list[dict] | None = None,
    author_statement: str | None = None,
    milestone: bool = False,
    import_info: dict | None = None,
    local_time: str | None = None,
    nonce: str | None = None,
) -> dict:
    return {
        **_base(local_time, nonce),
        "project": {"id": project_id, "title": project_title},
        "node_type": node_type,
        "title": title,
        "content": content,
        "external": external,
        "relations": list(relations or []),
        "author_statement": author_statement,
        "milestone": bool(milestone),
        "import": import_info,
    }


def link_payload(from_id, to_id, rel, op="add", statement=None, *, local_time=None, nonce=None) -> dict:
    return {**_base(local_time, nonce), "from": from_id, "to": to_id, "rel": rel, "op": op, "statement": statement}


def milestone_payload(target, op="set", *, local_time=None, nonce=None) -> dict:
    return {**_base(local_time, nonce), "target": target, "op": op}


def statement_payload(target, text, corrects=None, *, source="author", local_time=None, nonce=None) -> dict:
    return {**_base(local_time, nonce), "target": target, "source": source, "text": text, "corrects": corrects}


def retraction_payload(target, reason, *, local_time=None, nonce=None) -> dict:
    return {**_base(local_time, nonce), "target": target, "reason": reason}


# --------------------------------------------------------------------------- validation


def validate_manifest(m: Any) -> list[str]:
    if not isinstance(m, dict):
        return ["manifest must be an object"]
    errors: list[str] = []
    if set(m) != MANIFEST_KEYS:
        errors.append(f"manifest keys must be exactly {sorted(MANIFEST_KEYS)}")
        return errors
    if m["schema"] != RECORD_SCHEMA:
        errors.append(f"unsupported schema {m['schema']!r}")
    if m["kind"] not in RECORD_KINDS:
        errors.append(f"unknown record kind {m['kind']!r}")
    if not _is_uuid(m["installation"]):
        errors.append("installation must be a lowercase UUID string")
    seq = m["seq"]
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 0:
        errors.append("seq must be a non-negative integer")
    elif seq == 0:
        if m["prev"] is not None:
            errors.append("seq 0 must have prev = null")
        if m["kind"] != "genesis":
            errors.append("seq 0 must be the genesis record")
    else:
        if not is_record_id(m["prev"]):
            errors.append("prev must be a record ID")
        if m["kind"] == "genesis":
            errors.append("only seq 0 may be a genesis record")
    if not is_record_id(m["payload_sha256"]):
        errors.append("payload_sha256 must be 64 lowercase hex characters")
    return errors


def _check_keys(p: dict, required: set[str], optional: set[str], errors: list[str]) -> bool:
    keys = set(p)
    missing = required - keys
    extra = keys - required - optional
    if missing:
        errors.append(f"missing fields {sorted(missing)}")
    if extra:
        errors.append(f"unknown fields {sorted(extra)}")
    return not missing and not extra


def _opt_str(v: Any) -> bool:
    return v is None or isinstance(v, str)


def _nonempty_str(v: Any) -> bool:
    return isinstance(v, str) and v.strip() != ""


def _is_nonneg_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _validate_file_desc(d: Any, named: bool, where: str, errors: list[str]) -> None:
    if not isinstance(d, dict):
        errors.append(f"{where} must be an object")
        return
    required = {"sha256", "size", "media_type"} | ({"name"} if named else set())
    if not _check_keys(d, required, set(), errors):
        return
    if not is_record_id(d["sha256"]):
        errors.append(f"{where}.sha256 must be 64 lowercase hex characters")
    if not _is_nonneg_int(d["size"]):
        errors.append(f"{where}.size must be a non-negative integer")
    if not _nonempty_str(d["media_type"]):
        errors.append(f"{where}.media_type must be a string")
    if named and not is_safe_file_name(d["name"]):
        errors.append(f"{where}.name must be a safe file name")


def _validate_content(c: Any, errors: list[str]) -> None:
    if c is None:
        return
    if not isinstance(c, dict) or not _check_keys(c, {"body", "files"}, set(), errors):
        if not isinstance(c, dict):
            errors.append("content must be an object or null")
        return
    if c["body"] is not None:
        _validate_file_desc(c["body"], False, "content.body", errors)
    if not isinstance(c["files"], list):
        errors.append("content.files must be a list")
        return
    names = set()
    for i, f in enumerate(c["files"]):
        _validate_file_desc(f, True, f"content.files[{i}]", errors)
        if isinstance(f, dict) and isinstance(f.get("name"), str):
            if f["name"] in names:
                errors.append(f"duplicate file name {f['name']!r}")
            names.add(f["name"])


def _validate_external(e: Any, errors: list[str]) -> None:
    if e is None:
        return
    if not isinstance(e, dict):
        errors.append("external must be an object or null")
        return
    keys = set(e)
    if keys == {"repo_url", "commit"}:
        if not _nonempty_str(e["repo_url"]):
            errors.append("external.repo_url must be a string")
        if not (isinstance(e["commit"], str) and _COMMIT.match(e["commit"])):
            errors.append("external.commit must be a lowercase hex commit hash")
    elif keys == {"doi"} or keys == {"url"}:
        if not _nonempty_str(next(iter(e.values()))):
            errors.append("external reference must be a non-empty string")
    else:
        errors.append("external must be {repo_url, commit}, {doi} or {url}")


def _validate_import(imp: Any, errors: list[str]) -> None:
    if imp is None:
        return
    if not isinstance(imp, dict):
        errors.append("import must be an object or null")
        return
    if not _check_keys(imp, {"claimed_date", "precision", "level", "references"}, set(), errors):
        return
    if imp["precision"] not in IMPORT_PRECISIONS:
        errors.append("import.precision must be year, month or day")
    elif not (isinstance(imp["claimed_date"], str) and _CLAIMED_DATE[imp["precision"]].match(imp["claimed_date"])):
        errors.append("import.claimed_date does not match its precision")
    if imp["level"] not in IMPORT_LEVELS:
        errors.append("import.level must be L1 or L2")
    if not (isinstance(imp["references"], list) and all(_nonempty_str(r) for r in imp["references"])):
        errors.append("import.references must be a list of strings")


def validate_payload(kind: str, p: Any) -> list[str]:
    """Schema check for a payload of the given kind. Returns a list of problems."""
    if not isinstance(p, dict):
        return ["payload must be an object"]
    errors: list[str] = []
    base = {"nonce", "local_time", "ext"}
    if kind == "genesis":
        ok = _check_keys(p, base | {"author_label", "public_key"}, set(), errors)
        if ok:
            if not isinstance(p["author_label"], str):
                errors.append("author_label must be a string")
            if not is_record_id(p["public_key"]):
                errors.append("public_key must be the 32-byte Ed25519 key as 64 hex characters")
    elif kind == "entry":
        req = base | {
            "project",
            "node_type",
            "title",
            "content",
            "external",
            "relations",
            "author_statement",
            "milestone",
            "import",
        }
        ok = _check_keys(p, req, set(), errors)
        if ok:
            proj = p["project"]
            if not (isinstance(proj, dict) and set(proj) == {"id", "title"} and _is_uuid(proj["id"])
                    and isinstance(proj["title"], str)):
                errors.append("project must be {id: uuid, title: string}")
            if not _nonempty_str(p["node_type"]):
                errors.append("node_type must be a non-empty string")
            if not _nonempty_str(p["title"]):
                errors.append("title must be a non-empty string")
            _validate_content(p["content"], errors)
            _validate_external(p["external"], errors)
            rels = p["relations"]
            if not isinstance(rels, list):
                errors.append("relations must be a list")
            else:
                for i, r in enumerate(rels):
                    if not (isinstance(r, dict) and set(r) == {"to", "rel"} and is_record_id(r["to"])
                            and _nonempty_str(r["rel"])):
                        errors.append(f"relations[{i}] must be {{to: record ID, rel: string}}")
            if not _opt_str(p["author_statement"]):
                errors.append("author_statement must be a string or null")
            if not isinstance(p["milestone"], bool):
                errors.append("milestone must be a boolean")
            _validate_import(p["import"], errors)
    elif kind == "link":
        ok = _check_keys(p, base | {"from", "to", "rel", "op", "statement"}, set(), errors)
        if ok:
            if not (is_record_id(p["from"]) and is_record_id(p["to"])):
                errors.append("from and to must be record IDs")
            if not _nonempty_str(p["rel"]):
                errors.append("rel must be a non-empty string")
            if p["op"] not in ("add", "withdraw"):
                errors.append("op must be add or withdraw")
            if not _opt_str(p["statement"]):
                errors.append("statement must be a string or null")
    elif kind == "milestone":
        ok = _check_keys(p, base | {"target", "op"}, set(), errors)
        if ok:
            if not is_record_id(p["target"]):
                errors.append("target must be a record ID")
            if p["op"] not in ("set", "unset"):
                errors.append("op must be set or unset")
    elif kind == "statement":
        ok = _check_keys(p, base | {"target", "source", "text", "corrects"}, {"based_on"}, errors)
        if ok:
            if not is_record_id(p["target"]):
                errors.append("target must be a record ID")
            if p["source"] not in STATEMENT_SOURCES:
                errors.append("source must be author or ai")
            if not _nonempty_str(p["text"]):
                errors.append("text must be a non-empty string")
            if p["corrects"] is not None and not is_record_id(p["corrects"]):
                errors.append("corrects must be a record ID or null")
            if "based_on" in p and not (isinstance(p["based_on"], list)
                                        and all(is_record_id(x) for x in p["based_on"])):
                errors.append("based_on must be a list of record IDs")
            if p["source"] == "ai" and "based_on" not in p:
                errors.append("AI statements must list based_on")
    elif kind == "retraction":
        ok = _check_keys(p, base | {"target", "reason"}, set(), errors)
        if ok:
            if not is_record_id(p["target"]):
                errors.append("target must be a record ID")
            if not _nonempty_str(p["reason"]):
                errors.append("reason must be a non-empty string")
    else:
        return [f"unknown record kind {kind!r}"]
    if not errors:
        if not (isinstance(p["nonce"], str) and _HEX64.match(p["nonce"])):
            errors.append("nonce must be 32 random bytes as 64 lowercase hex characters")
        if not (isinstance(p["local_time"], str) and _UTC_SECONDS.match(p["local_time"])):
            errors.append("local_time must look like 2026-10-12T14:03:05Z")
        if not isinstance(p["ext"], dict):
            errors.append("ext must be an object")
    return errors


# Kinds a reference field must point at (None = any earlier record).
REF_TARGET_KINDS: dict[tuple[str, str], tuple[str, ...] | None] = {
    ("entry", "relations"): ("entry",),
    ("link", "from"): ("entry",),
    ("link", "to"): ("entry",),
    ("milestone", "target"): ("entry",),
    ("retraction", "target"): ("entry",),
    ("statement", "target"): None,
    ("statement", "corrects"): None,
    ("statement", "based_on"): None,
}


def payload_refs(kind: str, p: dict) -> list[tuple[str, str]]:
    """All (field, record_id) references a payload makes to earlier records."""
    refs: list[tuple[str, str]] = []
    if kind == "entry":
        refs += [("relations", r["to"]) for r in p.get("relations") or []]
    elif kind == "link":
        refs += [("from", p["from"]), ("to", p["to"])]
    elif kind in ("milestone", "retraction"):
        refs.append(("target", p["target"]))
    elif kind == "statement":
        refs.append(("target", p["target"]))
        if p.get("corrects"):
            refs.append(("corrects", p["corrects"]))
        refs += [("based_on", x) for x in p.get("based_on") or []]
    return refs
