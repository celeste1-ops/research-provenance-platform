"""Appending records (PRD §13 写入规则).

Every new record is written in one database transaction while holding the global
write lock: read the latest record → compute seq and prev → build payload and
manifest → sign → insert → commit. Time proofs are requested only after commit.
There is no code path that edits or deletes a record.
"""

from __future__ import annotations

import json
import mimetypes
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.config import MAX_UPLOAD_BYTES
from app.db.models import WRITE_LOCK, BlobRow, MetaRow, ProjectRow, RecordFileRow, RecordRow
from app.services.anchors import AnchorService
from app.services.blobs import BlobStore
from app.services.keystore import KeyStore
from provenance_core import records as R
from provenance_core.chain import next_position
from provenance_core.jcs import JcsError, parse_json_strict
from provenance_core.replay import ReplayState, replay
from provenance_core.signing import generate_private_key, private_key_raw, public_key_hex, sign_record_id

_MEDIA_TYPE = re.compile(r"\A[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*\Z")


class LedgerError(ValueError):
    """Bad input: reported to the client as HTTP 400."""


class NotInitialized(RuntimeError):
    pass


def _local_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class UploadedFile:
    name: str
    data: bytes
    media_type: str | None = None


@dataclass
class EntryInput:
    project_id: str
    node_type: str
    title: str
    body: str | None = None
    files: list[UploadedFile] = field(default_factory=list)
    external: dict | None = None
    relations: list[dict] = field(default_factory=list)
    author_statement: str | None = None
    milestone: bool = False
    import_info: dict | None = None


def _clean_media_type(value: str | None, name: str) -> str:
    mt = (value or "").split(";")[0].strip().lower()
    if not _MEDIA_TYPE.match(mt) or mt == "application/x-www-form-urlencoded":
        mt = mimetypes.guess_type(name)[0] or "application/octet-stream"
    return mt


class Ledger:
    def __init__(self, sessions: sessionmaker, blobs: BlobStore, keystore: KeyStore, anchors: AnchorService):
        self.sessions = sessions
        self.blobs = blobs
        self.keystore = keystore
        self.anchors = anchors
        self._write_lock = WRITE_LOCK
        self._key: Ed25519PrivateKey | None = None
        self.listeners: list = []  # called with the new record ID after each append (e.g. auto-backup)

    # ------------------------------------------------------------------ identity

    def meta(self, key: str) -> str | None:
        with self.sessions() as s:
            row = s.get(MetaRow, key)
            return row.value if row else None

    def set_meta(self, key: str, value: str) -> None:
        with WRITE_LOCK, self.sessions.begin() as s:
            row = s.get(MetaRow, key)
            if row is None:
                s.add(MetaRow(key=key, value=value))
            else:
                row.value = value

    @property
    def installation(self) -> str | None:
        return self.meta("installation")

    def initialized(self) -> bool:
        return self.installation is not None

    def public_key(self) -> str | None:
        """The identity's public key (hex) from its first record — without touching the keychain."""
        with self.sessions() as s:
            row = s.scalar(select(RecordRow).where(RecordRow.kind == "genesis").order_by(RecordRow.seq).limit(1))
        return json.loads(row.payload_bytes).get("public_key") if row is not None else None

    def signing_key(self) -> Ed25519PrivateKey:
        if self._key is None:
            inst = self.installation
            if inst is None:
                raise NotInitialized("no identity yet")
            key = self.keystore.load(inst)
            if key is None:
                raise NotInitialized(
                    "the signing key for this installation is not in the keychain; restore a key backup"
                )
            self._key = key
        return self._key

    def init_identity(self, author_label: str) -> str:
        """First start: create the key pair (kept in the keychain) and the genesis record."""
        author_label = (author_label or "").strip()
        if not author_label:
            raise LedgerError("an author label is required (it is shown as a self-declaration)")
        with self._write_lock:
            if self.initialized():
                raise LedgerError("this installation already has an identity")
            installation = str(uuid.uuid4())
            key = generate_private_key()
            self.keystore.save(installation, key)
            self._key = key
            self.set_meta("installation", installation)
            payload = R.genesis_payload(author_label, public_key_hex(key.public_key()))
            rid = self._append_locked("genesis", payload, None, [])
        self.anchors.submit_for(rid)
        return rid

    def adopt_identity(self, installation: str, key: Ed25519PrivateKey) -> None:
        """Used by restore: the key from a backup goes back into the keychain.

        If the keychain already holds this installation's key (a restore on the same Mac),
        it is left alone; a different key is never overwritten."""
        existing = self.keystore.load(installation)
        if existing is None:
            self.keystore.save(installation, key)
        elif private_key_raw(existing) != private_key_raw(key):
            raise LedgerError("the keychain already holds a different signing key for this installation")
        self._key = key

    # ------------------------------------------------------------------ projects

    def projects(self) -> list[ProjectRow]:
        with self.sessions() as s:
            return list(s.scalars(select(ProjectRow).order_by(ProjectRow.created_local, ProjectRow.title)))

    def create_project(self, title: str) -> ProjectRow:
        title = (title or "").strip()
        if not title:
            raise LedgerError("project title is required")
        row = ProjectRow(id=str(uuid.uuid4()), title=title, created_local=_local_now())
        with WRITE_LOCK, self.sessions.begin() as s:
            s.add(row)
        return row

    def rename_project(self, project_id: str, title: str) -> ProjectRow:
        """Changes only the local display name; entries keep the name they were recorded with."""
        title = (title or "").strip()
        if not title:
            raise LedgerError("project title is required")
        with WRITE_LOCK, self.sessions.begin() as s:
            row = s.get(ProjectRow, project_id)
            if row is None:
                raise LedgerError("unknown project")
            row.title = title
        return row

    # ------------------------------------------------------------------ reading

    def records(self) -> list[RecordRow]:
        with self.sessions() as s:
            return list(s.scalars(select(RecordRow).order_by(RecordRow.seq)))

    def record(self, record_id: str) -> RecordRow | None:
        with self.sessions() as s:
            return s.get(RecordRow, record_id)

    def record_files(self, record_id: str) -> list[RecordFileRow]:
        with self.sessions() as s:
            return list(s.scalars(select(RecordFileRow).where(RecordFileRow.record_id == record_id)))

    def all_record_files(self) -> dict[str, list[RecordFileRow]]:
        out: dict[str, list[RecordFileRow]] = {}
        with self.sessions() as s:
            for f in s.scalars(select(RecordFileRow)):
                out.setdefault(f.record_id, []).append(f)
        return out

    def state(self) -> ReplayState:
        rows = self.records()
        return replay([(r.id, r.seq, r.kind, parse_json_strict(r.payload_bytes)) for r in rows])

    # ------------------------------------------------------------------ appending

    def _append_locked(
        self, kind: str, payload: dict, project_id: str | None, files: list[tuple[str, str, bytes, str]]
    ) -> str:
        """Caller holds ``self._write_lock``. ``files``: (role, name, data, media_type)."""
        key = self.signing_key()
        installation = self.installation
        assert installation is not None
        for _, _, data, _ in files:
            self.blobs.put(data)  # content-addressed; harmless if the transaction fails
        with self.sessions.begin() as s:
            last = s.scalar(select(RecordRow).order_by(RecordRow.seq.desc()).limit(1))
            seq, prev = next_position(last.id if last else None, last.seq if last else None)
            try:
                manifest_bytes, payload_bytes, rid = R.encode_record(kind, installation, seq, prev, payload)
            except (R.RecordError, JcsError) as exc:
                raise LedgerError(str(exc)) from None
            s.add(
                RecordRow(
                    id=rid,
                    kind=kind,
                    seq=seq,
                    prev_id=prev,
                    manifest_bytes=manifest_bytes,
                    payload_bytes=payload_bytes,
                    signature=sign_record_id(key, rid),
                    project_id=project_id,
                    created_local=payload["local_time"],
                )
            )
            s.flush()
            for role, name, data, media_type in files:
                digest = R.sha256_hex(data)
                if s.get(BlobRow, digest) is None:
                    s.add(BlobRow(sha256=digest, size=len(data), created_local=payload["local_time"]))
                    s.flush()
                s.add(
                    RecordFileRow(
                        record_id=rid, role=role, name=name, sha256=digest, size=len(data), media_type=media_type
                    )
                )
        return rid

    def _append(self, kind: str, payload: dict, project_id: str | None, files=()) -> str:
        with self._write_lock:
            rid = self._append_locked(kind, payload, project_id, list(files))
        self.anchors.submit_for(rid)  # after commit; failures only affect the proof
        self._notify(rid)
        return rid

    def _notify(self, rid: str) -> None:
        for listener in list(self.listeners):
            try:
                listener(rid)
            except Exception:  # noqa: BLE001 - a listener never breaks recording
                import logging

                logging.getLogger("rprov.ledger").exception("listener failed")

    def _require(self, record_id: str, kinds: tuple[str, ...] | None, what: str) -> RecordRow:
        if not R.is_record_id(record_id):
            raise LedgerError(f"{what} must be a record ID")
        row = self.record(record_id)
        if row is None:
            raise LedgerError(f"{what} points at a record that does not exist")
        if kinds is not None and row.kind not in kinds:
            raise LedgerError(f"{what} must point at an entry, not a {row.kind} record")
        return row

    # ------------------------------------------------------------------ the six kinds

    def create_entry(self, inp: EntryInput) -> str:
        if not self.initialized():
            raise NotInitialized("create an identity first")
        if inp.node_type not in R.NODE_TYPES:
            raise LedgerError(f"unknown node type {inp.node_type!r}; use one of {', '.join(R.NODE_TYPES)}")
        title = (inp.title or "").strip()
        if not title:
            raise LedgerError("title is required")
        with self.sessions() as s:
            project = s.get(ProjectRow, inp.project_id or "")
        if project is None:
            raise LedgerError("unknown project")

        files: list[tuple[str, str, bytes, str]] = []
        body_desc = None
        if inp.body is not None and inp.body.strip() != "":
            body = R.normalize_text(inp.body)
            if len(body) > MAX_UPLOAD_BYTES:
                raise LedgerError("body text is larger than 50 MB")
            body_desc = R.file_descriptor(body, "text/markdown")
            files.append(("body", "body.md", body, "text/markdown"))
        file_descs = []
        used: set[str] = set()
        for up in inp.files:
            if len(up.data) > MAX_UPLOAD_BYTES:
                raise LedgerError(f"{up.name}: files are limited to 50 MB each")
            name = R.safe_file_name(up.name)
            stem, dot, ext = name.rpartition(".")
            n = 2
            while name in used:
                name = f"{stem} ({n}).{ext}" if dot else f"{ext} ({n})"
                n += 1
            used.add(name)
            mt = _clean_media_type(up.media_type, name)
            file_descs.append(R.file_descriptor(up.data, mt, name))
            files.append(("file", name, up.data, mt))
        content = {"body": body_desc, "files": file_descs} if (body_desc or file_descs) else None

        external = self._clean_external(inp.external, inp.node_type)
        relations = []
        for rel in inp.relations:
            to, kind = (rel or {}).get("to", ""), (rel or {}).get("rel", "")
            if kind not in R.RELATION_TYPES:
                raise LedgerError(f"unknown relation {kind!r}; use one of {', '.join(R.RELATION_TYPES)}")
            self._require(to, ("entry",), "relation")
            relations.append({"to": to, "rel": kind})
        import_info = self._clean_import(inp.import_info)
        statement = (inp.author_statement or "").strip() or None
        payload = R.entry_payload(
            project_id=project.id,
            project_title=project.title,
            node_type=inp.node_type,
            title=title,
            content=content,
            external=external,
            relations=relations,
            author_statement=statement,
            milestone=bool(inp.milestone),
            import_info=import_info,
        )
        return self._append("entry", payload, project.id, files)

    @staticmethod
    def _clean_external(ext: dict | None, node_type: str) -> dict | None:
        if not ext:
            return None
        ext = {k: (v or "").strip() for k, v in ext.items() if (v or "").strip()}
        if not ext:
            return None
        if set(ext) == {"repo_url", "commit"}:
            ext["commit"] = ext["commit"].lower()
            if not re.fullmatch(r"[0-9a-f]{7,64}", ext["commit"]):
                raise LedgerError("commit must be a hexadecimal commit hash")
            return ext
        if set(ext) in ({"doi"}, {"url"}):
            return ext
        raise LedgerError("external reference must be a repository URL + commit, a DOI, or a URL")

    @staticmethod
    def _clean_import(imp: dict | None) -> dict | None:
        if not imp or not (imp.get("claimed_date") or "").strip():
            return None
        date = imp["claimed_date"].strip()
        precision = imp.get("precision") or {4: "year", 7: "month", 10: "day"}.get(len(date), "")
        level = imp.get("level") or "L1"
        refs = [r.strip() for r in imp.get("references") or [] if r and r.strip()]
        info = {"claimed_date": date, "precision": precision, "level": level, "references": refs}
        errors: list[str] = []
        R._validate_import(info, errors)
        if errors:
            raise LedgerError("; ".join(errors))
        if level == "L2" and not refs:
            raise LedgerError("L2 (third-party reference) needs at least one reference, e.g. a DOI or archive link")
        return info

    def create_link(self, from_id: str, to_id: str, rel: str, op: str = "add", statement: str | None = None) -> str:
        if rel not in R.RELATION_TYPES:
            raise LedgerError(f"unknown relation {rel!r}; use one of {', '.join(R.RELATION_TYPES)}")
        if op not in ("add", "withdraw"):
            raise LedgerError("op must be add or withdraw")
        src = self._require(from_id, ("entry",), "from")
        dst = self._require(to_id, ("entry",), "to")
        if dst.seq >= src.seq:
            raise LedgerError("relations point from a newer record to an older one ('to' is later than 'from')")
        active = [e for e in self.state().edges if e.active and (e.source, e.target, e.rel) == (from_id, to_id, rel)]
        if op == "add" and active:
            raise LedgerError("this relation already exists")
        if op == "withdraw" and not active:
            raise LedgerError("there is no such active relation to withdraw")
        payload = R.link_payload(from_id, to_id, rel, op, (statement or "").strip() or None)
        return self._append("link", payload, src.project_id)

    def create_milestone(self, target: str, op: str = "set") -> str:
        if op not in ("set", "unset"):
            raise LedgerError("op must be set or unset")
        row = self._require(target, ("entry",), "target")
        entry = self.state().entries[target]
        if entry.milestone == (op == "set"):
            raise LedgerError(f"the entry is already {'a milestone' if entry.milestone else 'not a milestone'}")
        return self._append("milestone", R.milestone_payload(target, op), row.project_id)

    def create_statement(self, target: str, text: str, corrects: str | None = None) -> str:
        text = (text or "").strip()
        if not text:
            raise LedgerError("statement text is required")
        row = self._require(target, None, "target")
        if row.kind == "genesis":
            raise LedgerError("statements cannot target the genesis record")
        if corrects:
            self._require(corrects, ("statement", "entry", "link"), "corrects")
        return self._append("statement", R.statement_payload(target, text, corrects or None), row.project_id)

    def create_retraction(self, target: str, reason: str) -> str:
        reason = (reason or "").strip()
        if not reason:
            raise LedgerError("a reason is required")
        row = self._require(target, ("entry",), "target")
        if self.state().entries[target].retracted_by:
            raise LedgerError("this entry is already retracted")
        return self._append("retraction", R.retraction_payload(target, reason), row.project_id)

    def record_count(self) -> int:
        with self.sessions() as s:
            return s.scalar(select(func.count()).select_from(RecordRow)) or 0
