"""Test helpers: an in-memory log that appends signed records like the app does."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from provenance_core import records as R
from provenance_core.providers.mock import MockProvider, mock_tsa_root
from provenance_core.signing import generate_private_key, public_key_hex, sign_record_id
from provenance_core.verify import RecordMaterial, verify_log


class StepClock:
    """Deterministic clock: each call advances by ``step`` seconds."""

    def __init__(self, start: datetime | None = None, step: int = 60):
        self.now = start or datetime(2026, 10, 12, 14, 0, 0, tzinfo=UTC)
        self.step = timedelta(seconds=step)

    def __call__(self) -> datetime:
        current = self.now
        self.now += self.step
        return current


@dataclass
class MemRecord:
    id: str
    kind: str
    seq: int
    manifest_bytes: bytes
    payload_bytes: bytes
    payload: dict
    signature: bytes
    tsa_proof: bytes | None = None
    btc_proof: bytes | None = None
    content: dict[str, bytes] = field(default_factory=dict)


class MemoryLog:
    def __init__(self, *, with_tsa: bool = True, with_btc: bool = True, author: str = "Test Author"):
        self.key = generate_private_key()
        self.installation = str(uuid.uuid4())
        self.records: list[MemRecord] = []
        self.clock = StepClock()
        self.tsa = MockProvider("tsa", clock=self.clock) if with_tsa else None
        self.btc = MockProvider("btc", clock=self.clock) if with_btc else None
        self.project_id = str(uuid.uuid4())
        self.append("genesis", R.genesis_payload(author, public_key_hex(self.key.public_key())))

    def append(self, kind: str, payload: dict, content: dict[str, bytes] | None = None) -> MemRecord:
        seq = len(self.records)
        prev = self.records[-1].id if self.records else None
        mb, pb, rid = R.encode_record(kind, self.installation, seq, prev, payload)
        rec = MemRecord(rid, kind, seq, mb, pb, payload, sign_record_id(self.key, rid), content=content or {})
        if self.tsa:
            rec.tsa_proof = self.tsa.submit(rid, mb).proof
        if self.btc:
            rec.btc_proof = self.btc.submit(rid, mb).proof
        self.records.append(rec)
        return rec

    def entry(self, title: str, node_type: str = "note", body: str | None = None, **kw) -> MemRecord:
        content = None
        files: dict[str, bytes] = {}
        if body is not None:
            data = R.normalize_text(body)
            content = {"body": R.file_descriptor(data, "text/markdown"), "files": []}
            files["body"] = data
        payload = R.entry_payload(
            project_id=self.project_id,
            project_title="FSF",
            node_type=node_type,
            title=title,
            content=content,
            **kw,
        )
        return self.append("entry", payload, files)

    def materials(self, disclosure: str = "full") -> dict[str, RecordMaterial]:
        out = {}
        for r in self.records:
            out[r.id] = RecordMaterial(
                r.id,
                r.manifest_bytes,
                r.payload_bytes if disclosure != "existence" or r.kind == "genesis" else None,
                r.signature,
                r.tsa_proof,
                r.btc_proof,
                dict(r.content) if disclosure == "full" else None,
            )
        return out

    def verify(self, materials=None, **kw):
        ids = [r.id for r in self.records]
        kw.setdefault("tsa_roots", [mock_tsa_root()])
        return verify_log(ids, materials if materials is not None else self.materials(), **kw)
