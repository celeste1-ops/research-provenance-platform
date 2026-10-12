"""Read models for the UI and report: graph, timeline, record detail.

Every piece of information carries its source label (PRD §7 rule 2):
``verified`` | ``author`` | ``ai`` (v0.1 never produces ``ai``). The two kinds of
time proof are always reported separately (rule 4).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from app.db.models import AnchorRow, RecordRow
from app.i18n import tr
from provenance_core.jcs import parse_json_strict
from provenance_core.replay import ReplayState, milestone_view, replay

TSA_LABEL = "Third-party timestamp"
BTC_LABEL = "Bitcoin anchor"
# English names; tr() gives them in the interface language when they are shown.
NODE_TYPE_LABELS = {
    "idea": "Idea",
    "note": "Note",
    "claim": "Hypothesis / claim",
    "document": "Document",
    "code": "Code",
    "experiment": "Experiment",
    "dataset": "Data",
    "figure": "Figure",
    "publication": "Paper",
}
REL_LABELS = {"revises": "revises", "derived_from": "derived from", "uses": "uses"}
CODE_NOT_SAVED = "External reference, code content not saved"


def node_type_label(node_type: str) -> str:
    return tr(NODE_TYPE_LABELS.get(node_type, "Other"))


def rel_label(rel: str) -> str:
    return tr(REL_LABELS.get(rel, "other relation"))


def proof_status(row: AnchorRow | None, kind: str, enabled: bool) -> dict:
    """Status of one kind of time proof, for display. Never merged with the other kind."""
    label = tr(TSA_LABEL if kind == "tsa" else BTC_LABEL)
    if not enabled and row is None:
        return {"kind": kind, "label": label, "state": "not_enabled", "text": tr("{label}: not enabled", label=label),
                "time": None}
    if row is None or (row.proof_bytes is None and row.status != "confirmed"):
        failing = row is not None and row.status == "failed"
        retrying = row is not None and bool(row.last_error)
        return {
            "kind": kind,
            "label": label,
            "state": "failed" if failing else "none",
            "text": tr("{label}: no timestamp yet (retrying)", label=label) if retrying
            else tr("{label}: no timestamp yet", label=label),
            "retrying": retrying,
            "time": None,
            "error": row.last_error if row is not None else None,
        }
    if row.status == "confirmed":
        return {
            "kind": kind,
            "label": label,
            "state": "confirmed",
            "text": tr("{label}: verified", label=label) if kind == "tsa" else tr("{label}: confirmed", label=label),
            "time": row.verified_time_utc,
            "provider": row.provider_name,
        }
    return {"kind": kind, "label": label, "state": "pending", "text": tr("{label}: pending", label=label), "time": None,
            "provider": row.provider_name}


def earliest_verified(tsa: dict, btc: dict) -> dict | None:
    """V8 one-line summary: the earliest verified time *and which proof it came from*."""
    candidates = [(p["time"], p["label"]) for p in (tsa, btc) if p["state"] == "confirmed" and p["time"]]
    if not candidates:
        return None
    time, label = min(candidates)
    return {"time": time, "from": label, "text": tr("Earliest verified time: {time} (from {label})", time=time, label=label)}


@dataclass
class Snapshot:
    """Everything the read models need, loaded once."""

    rows: list[RecordRow]
    payloads: dict[str, dict]
    state: ReplayState
    anchors: dict[str, dict[str, AnchorRow]]
    enabled: dict[str, bool]
    files: dict[str, list]

    @classmethod
    def load(cls, ledger, anchor_service) -> Snapshot:
        rows = ledger.records()
        payloads = {r.id: parse_json_strict(r.payload_bytes) for r in rows}
        state = replay([(r.id, r.seq, r.kind, payloads[r.id]) for r in rows])
        enabled = {k: anchor_service.providers.get(k) is not None for k in ("tsa", "btc")}
        return cls(rows, payloads, state, anchor_service.rows_by_record(), enabled, ledger.all_record_files())

    def proofs(self, rid: str) -> tuple[dict, dict]:
        a = self.anchors.get(rid, {})
        return proof_status(a.get("tsa"), "tsa", self.enabled["tsa"]), proof_status(
            a.get("btc"), "btc", self.enabled["btc"]
        )

    def when(self, rid: str) -> dict:
        """Date to show for a record: earliest verified time, else the unverified local time."""
        tsa, btc = self.proofs(rid)
        ev = earliest_verified(tsa, btc)
        if ev:
            return {"time": ev["time"], "verified": True, "from": ev["from"]}
        return {"time": self.payloads[rid]["local_time"], "verified": False, "from": tr("local clock (unverified)")}

    def row(self, rid: str) -> RecordRow | None:
        return next((r for r in self.rows if r.id == rid), None)


PREVIEW_BYTES = 4096  # read from the start of a step's text, however long it is
PREVIEW_CHARS = 280
PREVIEW_LINES = 4
# Markdown marks that would only get in the way in a few lines of plain text.
_MARKS = [
    (re.compile(r"!\[[^\]]*\]\([^)]*\)"), ""),  # images
    (re.compile(r"\[([^\]]*)\]\([^)]*\)"), r"\1"),  # links: keep their text
    (re.compile(r"^\s{0,3}(?:#{1,6}|[-*+]|\d+[.)]|>)\s+", re.M), ""),  # headings, list marks, quotes
    (re.compile(r"^\s*(?:```|~~~).*$", re.M), ""),  # code fences (the code itself stays)
    (re.compile(r"\*\*|__|`"), ""),
]


def text_preview(blobs, files: list) -> str | None:
    """The first few lines of a step's text, as plain text, so they can be read without opening it.
    Only for showing: the full text, checked against its fingerprint, is in the step's detail."""
    body = next((f for f in files if f.role == "body"), None)
    if body is None or blobs is None:
        return None
    try:
        with open(blobs.path_for(body.sha256), "rb") as fh:
            raw = fh.read(PREVIEW_BYTES)
    except (OSError, ValueError):
        return None
    text = raw.decode("utf-8", errors="ignore")
    for pattern, replacement in _MARKS:
        text = pattern.sub(replacement, text)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    lines = [line for line in lines if line]
    short = "\n".join(lines[:PREVIEW_LINES])
    if len(short) > PREVIEW_CHARS:
        short = short[:PREVIEW_CHARS].rstrip()
    if short != "\n".join(lines) or len(raw) == PREVIEW_BYTES:
        short += "…"
    return short or None


def graph_view(snap: Snapshot, project_id: str | None = None, milestones_only: bool = False,
               blobs=None) -> dict:
    st = snap.state
    entries = [e for e in sorted(st.entries.values(), key=lambda e: e.seq)
               if project_id is None or e.project_id == project_id]
    ids = {e.id for e in entries}
    nodes = []
    for e in entries:
        tsa, btc = snap.proofs(e.id)
        nodes.append(
            {
                "id": e.id,
                "seq": e.seq,
                "title": e.title,
                "node_type": e.node_type,
                "node_type_label": node_type_label(e.node_type),
                "project_id": e.project_id,
                "milestone": e.milestone,
                "retracted": e.retracted_by is not None,
                "date": snap.when(e.id),
                "tsa": tsa,
                "btc": btc,
                # What the step holds, to read at a glance: its text, its files, its reference.
                "preview": text_preview(blobs, snap.files.get(e.id, [])),
                "files": [f.name for f in snap.files.get(e.id, []) if f.role == "file"],
                "external": snap.payloads[e.id].get("external"),
            }
        )
    edges = []
    for i, edge in enumerate(st.edges):
        if edge.source not in ids or edge.target not in ids:
            continue
        item = {
            "id": f"e{i}",
            "from": edge.target,  # arrows run from the older record to the newer one
            "to": edge.source,
            "rel": edge.rel,
            "rel_label": rel_label(edge.rel),
            "origin": edge.origin,
            "source_label": "author",
            "active": edge.active,
            "statement": edge.statement,
        }
        if edge.origin == "link":
            item["added"] = snap.when(edge.added_by)
            item["added_by"] = edge.added_by
        if edge.withdrawn_by:
            item["withdrawn"] = snap.when(edge.withdrawn_by)
            item["withdrawn_by"] = edge.withdrawn_by
        edges.append(item)
    types_present = [t for t in NODE_TYPE_LABELS if any(n["node_type"] == t for n in nodes)]
    types_present += sorted({n["node_type"] for n in nodes} - set(NODE_TYPE_LABELS))
    out = {"nodes": nodes, "edges": edges, "rows": types_present}
    milestones, connectors = milestone_view(st)
    out["milestone_view"] = {
        "nodes": [m for m in milestones if m in ids],
        "connectors": [
            {"from": a, "to": b, "hidden": n, "label": tr("{n} in between", n=n)}
            for a, b, n in connectors
            if a in ids and b in ids
        ],
    }
    if milestones_only:
        keep = set(out["milestone_view"]["nodes"])
        out["nodes"] = [n for n in nodes if n["id"] in keep]
        out["edges"] = [e for e in edges if e["from"] in keep and e["to"] in keep]
    return out


def _record_title(snap: Snapshot, rid: str) -> str:
    p = snap.payloads.get(rid, {})
    kind = snap.state.kinds.get(rid)
    if kind == "entry":
        return p["title"]
    if kind == "genesis":
        return tr("Genesis — author label: {label}", label=p["author_label"])
    if kind == "link":
        parts = {"a": _short(snap, p["from"]), "rel": rel_label(p["rel"]), "b": _short(snap, p["to"])}
        return tr("Added relation: {a} {rel} {b}", **parts) if p["op"] == "add" else tr("Withdrew relation: {a} {rel} {b}", **parts)
    if kind == "milestone":
        target = _short(snap, p["target"])
        return tr("Marked key step: {target}", target=target) if p["op"] == "set" else tr("Unmarked key step: {target}", target=target)
    if kind == "statement":
        return tr("Statement on {target}", target=_short(snap, p["target"]))
    if kind == "retraction":
        return tr("Retracted: {target}", target=_short(snap, p["target"]))
    return kind or "record"


def _short(snap: Snapshot, rid: str) -> str:
    e = snap.state.entries.get(rid)
    return f"“{e.title}”" if e else rid[:10]


def timeline_view(snap: Snapshot, project_id: str | None = None) -> list[dict]:
    out = []
    for r in snap.rows:
        p = snap.payloads[r.id]
        if project_id is not None and r.project_id not in (None, project_id):
            continue
        tsa, btc = snap.proofs(r.id)
        rels = []
        if r.kind == "entry":
            rels = [{"rel": x["rel"], "to": x["to"], "to_title": _short(snap, x["to"]), "source_label": "author"}
                    for x in p["relations"]]
        out.append(
            {
                "id": r.id,
                "seq": r.seq,
                "kind": r.kind,
                "node_type": p.get("node_type"),
                "title": _record_title(snap, r.id),
                "tsa": tsa,
                "btc": btc,
                "earliest_verified": earliest_verified(tsa, btc),
                "local_time": {"value": p["local_time"], "note": tr("unverified")},
                "relations": rels,
                "source_label": "verified",
            }
        )
    return out


def record_detail(snap: Snapshot, rid: str, verification: dict | None = None) -> dict | None:
    row = snap.row(rid)
    if row is None:
        return None
    p = snap.payloads[rid]
    tsa, btc = snap.proofs(rid)
    files = snap.files.get(rid, [])
    verified: dict = {
        "label": tr("Verified record"),
        "source": "verified",
        "record_id": rid,
        "seq": row.seq,
        "kind": row.kind,
        "title": _record_title(snap, rid),
        "signature": (verification or {}).get("signature", "valid"),
        "timestamps": {"tsa": tsa, "btc": btc},
        "earliest_verified": earliest_verified(tsa, btc),
        "content_hashes": [],
        "note": tr("Shows that this record existed by the verified time and has not changed since. "
                   "It does not show that what it says is true."),
    }
    author_items: list[dict] = []
    declared = snap.when(rid)
    declared_text = (tr("Author declared on {date}", date=declared["time"][:10]) if declared["verified"]
                     else tr("Author declared on {date} (unverified date)", date=declared["time"][:10]))
    author_items.append(
        {"field": "local_time", "text": tr("Local clock time: {time}", time=p["local_time"]),
         "note": tr("self-reported, unverified")}
    )
    if row.kind == "entry":
        verified["node_type"] = p["node_type"]
        verified["node_type_label"] = node_type_label(p["node_type"])
        verified["project_title"] = p["project"]["title"]
        content = p.get("content") or {}
        if content.get("body"):
            verified["content_hashes"].append({"name": "body.md", **content["body"]})
            verified["has_body"] = True
        for f in content.get("files") or []:
            verified["content_hashes"].append(f)
        ext = p.get("external")
        if ext:
            verified["external"] = dict(ext)
            if "commit" in ext:
                has_archive = bool(content.get("files"))
                verified["external"]["note"] = (
                    tr("Code archive attached: the code content itself is preserved.")
                    if has_archive
                    else tr(CODE_NOT_SAVED)
                )
                verified["external"]["saved"] = has_archive
                verified["external"]["kind"] = "code"
            else:
                verified["external"]["kind"] = "publication"
                verified["external"]["evidence_level"] = tr("L2 (third-party reference)")
        if p.get("author_statement"):
            author_items.append({"field": "why", "text": p["author_statement"], "note": declared_text})
        if p.get("import"):
            imp = p["import"]
            level = tr("L2 (third-party reference)") if imp["level"] == "L2" else tr("L1 (author statement only)")
            author_items.append(
                {
                    "field": "claimed_date",
                    "text": tr("Claimed date: {date} ({precision})", date=imp["claimed_date"],
                               precision=tr(imp["precision"])),
                    "note": tr("{declared}; evidence level {level}", declared=declared_text, level=level),
                    "level": imp["level"],
                    "references": imp["references"],
                }
            )
        for rel in p["relations"]:
            author_items.append(
                {
                    "field": "relation",
                    "text": f"{rel_label(rel['rel'])} {_short(snap, rel['to'])}",
                    "note": declared_text,
                    "to": rel["to"],
                    "rel": rel["rel"],
                }
            )
        if p.get("milestone"):
            author_items.append({"field": "milestone", "text": tr("Marked as a key step when recorded"), "note": declared_text})
    elif row.kind == "genesis":
        verified["public_key"] = p["public_key"]
        author_items.append({"field": "author_label", "text": tr("Author label: {label}", label=p["author_label"]),
                             "note": tr("self-declared; a key does not identify a person")})
    elif row.kind in ("link", "statement", "retraction", "milestone"):
        text = {"link": p.get("statement"), "statement": p.get("text"), "retraction": p.get("reason")}.get(row.kind)
        if text:
            author_items.append({"field": row.kind, "text": text, "note": declared_text})

    later = []
    entry = snap.state.entries.get(rid)
    if entry:
        for add_id in entry.additions:
            ap = snap.payloads[add_id]
            later.append(
                {
                    "record_id": add_id,
                    "kind": snap.state.kinds[add_id],
                    "title": _record_title(snap, add_id),
                    "date": snap.when(add_id),
                    "text": ap.get("text") or ap.get("statement") or ap.get("reason"),
                    "source_label": "author",
                }
            )
    detail = {
        "id": rid,
        "seq": row.seq,
        "kind": row.kind,
        "verified": verified,
        "author": {"label": tr("Author statement"), "source": "author", "items": author_items},
        "later": {"label": tr("Later additions"), "items": later},
        "retracted": bool(entry and entry.retracted_by),
        "files": [{"role": f.role, "name": f.name, "size": f.size, "media_type": f.media_type, "sha256": f.sha256}
                  for f in files],
    }
    if entry:
        prev_rel = [e for e in snap.state.edges if e.source == rid and e.rel == "revises" and e.active]
        detail["revises"] = [e.target for e in prev_rel]
    return detail


def diff_view(ledger, snap: Snapshot, rid: str, against: str) -> dict:
    """Line diff of the bodies and a by-hash comparison of attachments."""

    def body_and_files(record_id: str) -> tuple[list[str], dict[str, str]]:
        files = snap.files.get(record_id, [])
        body = next((f for f in files if f.role == "body"), None)
        text = ledger.blobs.get(body.sha256).decode("utf-8") if body else ""
        return text.splitlines(keepends=True), {f.name: f.sha256 for f in files if f.role == "file"}

    new_lines, new_files = body_and_files(rid)
    old_lines, old_files = body_and_files(against)
    diff = list(difflib.unified_diff(old_lines, new_lines, fromfile=against[:12], tofile=rid[:12]))
    return {
        "record": rid,
        "against": against,
        "body_diff": "".join(diff),
        "files": {
            "added": sorted(set(new_files) - set(old_files)),
            "removed": sorted(set(old_files) - set(new_files)),
            "modified": sorted(n for n in set(new_files) & set(old_files) if new_files[n] != old_files[n]),
            "unchanged": sorted(n for n in set(new_files) & set(old_files) if new_files[n] == old_files[n]),
        },
    }
