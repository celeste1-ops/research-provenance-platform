"""Render report.html and VERIFY.md (Jinja2). The report is self-contained: inline
CSS, a static SVG graph, no scripts, fonts or external requests (PRD §12)."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from markdown_it import MarkdownIt
from markupsafe import Markup, escape

from app.i18n import current, tr
from app.report.svg import render_graph_svg
from provenance_core.jcs import parse_json_strict
from provenance_core.replay import replay
from provenance_core.verify import STATUS_LABELS

TEMPLATES = Path(__file__).resolve().parent / "templates"

# What the record proves and does not prove — fixed text from PRD §2; not user-editable.
PROVES = [
    "This record existed no later than the verified time. “This record” means all of it: files, type, "
    "relations to other records, and the author's notes.",
    "It has not been changed since.",
    "The order in which records were made.",
    "All records were signed with the same signing key.",
]
DOES_NOT_PROVE = [
    "That the author personally thought of it. A signing key only shows “the same key”, not a particular person.",
    "That the author was the first to think of it.",
    "Why something was changed.",
    "That the content is correct or valuable.",
]
SOURCE_NOTE = (
    "A verified record only shows that the record existed at that time and has not been changed since — "
    "not that what it says is true. Author statements are what the author said; the system can only show "
    "that the author said it at that time."
)
REL_LABELS = {"revises": "revises", "derived_from": "derived from", "uses": "uses"}
TYPE_LABELS = {
    "idea": "Idea", "note": "Note", "claim": "Claim / hypothesis", "document": "Document", "code": "Code",
    "experiment": "Experiment", "dataset": "Dataset", "figure": "Figure", "publication": "Publication",
}
# Short words the report prints next to a record (kind, type, disclosure, proof state). In English
# they are the plain codes; the Chinese report translates them (DECISIONS D-046).
WORDS = [
    "entry", "genesis", "link", "milestone", "statement", "retraction", "record",
    *TYPE_LABELS, "full", "structure", "existence",
    "verified", "confirmed", "pending", "none", "invalid", "unchecked",
]
LATER_LABELS = ["Relation added", "Relation withdrawn", "Milestone set", "Milestone unset", "Statement",
                "Statement (correction)", "Retracted"]

_md = MarkdownIt("commonmark", {"html": False}).disable("image")


def _markdown(text: str) -> Markup:
    return Markup(_md.render(text))  # raw HTML disabled; images disabled (no network requests)


def _trusted(text: str, /, **params) -> Markup:
    """The app's own words that contain markup (<b>, <code>); inserted values are escaped."""
    return Markup(tr(text, **{k: escape(v) for k, v in params.items()}))


def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=lambda name: bool(name) and name.endswith(".html.j2"),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["short"] = lambda rid: rid[:12]
    env.filters["word"] = lambda code: tr(code) if code in WORDS else code
    env.globals.update(t=tr, th=_trusted, lang=current())
    return env


def _date(time: str | None) -> str:
    return time[:10] if time else ""


def rel_label(rel: str) -> str:
    return tr(REL_LABELS.get(rel, "other relation"))


def build_model(plan, meta, mats, contents, report, trust) -> dict:
    results = report.by_id()
    payloads: dict[str, dict] = {}
    for r in plan.chain:
        m = mats[r.id]
        if m.payload_bytes is not None:
            payloads[r.id] = parse_json_strict(m.payload_bytes)
    state = replay([(r.id, r.seq, r.kind, payloads.get(r.id)) for r in plan.chain])

    def when(rid: str) -> dict:
        res = results.get(rid)
        ev = res.earliest_verified() if res else None
        if ev:
            return {"time": ev[0], "from": ev[1], "verified": True}
        local = payloads.get(rid, {}).get("local_time")
        return {"time": local, "from": tr("local clock (unverified)"), "verified": False}

    def title_of(rid: str) -> str:
        e = state.entries.get(rid)
        if e:
            return e.title
        kind = tr(state.kinds.get(rid, "record"))
        return tr("hidden {kind} record #{seq}", kind=kind, seq=state.seqs.get(rid, "?")) \
            if rid in state.hidden else kind

    nodes = []
    for e in sorted(state.entries.values(), key=lambda e: e.seq):
        res = results[e.id]
        nodes.append({
            "id": e.id, "seq": e.seq, "title": e.title, "node_type": e.node_type, "milestone": e.milestone,
            "retracted": bool(e.retracted_by), "date": _date(when(e.id)["time"] if when(e.id)["verified"] else None),
            "tsa_state": "confirmed" if res.tsa.verified else ("none" if res.tsa.state == "none" else res.tsa.state),
            "btc_state": "confirmed" if res.btc.verified else ("pending" if res.btc.state == "pending" else "none"),
        })
    edges = []
    for edge in state.edges:
        item = {"from": edge.target, "to": edge.source, "rel": edge.rel, "origin": edge.origin,
                "active": edge.active}
        if edge.origin == "link":
            w = when(edge.added_by)
            item["added"] = _date(w["time"]) if w["verified"] else tr("{date} (unverified)", date=_date(w["time"]))
        if edge.withdrawn_by:
            w = when(edge.withdrawn_by)
            item["withdrawn"] = _date(w["time"]) if w["verified"] else tr("{date} (unverified)",
                                                                            date=_date(w["time"]))
        edges.append(item)

    timeline = []
    for r in plan.chain:
        res = results[r.id]
        p = payloads.get(r.id)
        if p is None:
            title = tr("Hidden record (existence only)")
        elif r.kind == "entry":
            title = p["title"]
        elif r.kind == "genesis":
            title = tr("Genesis (signing key)")
        elif r.kind == "link":
            title = tr("Added relation: {a} {rel} {b}" if p["op"] == "add" else "Withdrew relation: {a} {rel} {b}",
                       a=title_of(p["from"]), rel=rel_label(p["rel"]), b=title_of(p["to"]))
        elif r.kind == "milestone":
            title = tr("Marked milestone: {target}" if p["op"] == "set" else "Unmarked milestone: {target}",
                       target=title_of(p["target"]))
        elif r.kind == "statement":
            title = tr("Statement on {target}", target=title_of(p["target"]))
        else:
            title = tr("Retracted: {target}", target=title_of(p["target"]))
        rels = []
        if p and r.kind == "entry":
            rels = [tr("{rel} {target}", rel=rel_label(x["rel"]), target=title_of(x["to"])) for x in p["relations"]]
        timeline.append({
            "seq": r.seq, "id": r.id, "kind": r.kind, "node_type": (p or {}).get("node_type"),
            "title": title, "tsa": res.tsa, "btc": res.btc, "local_time": (p or {}).get("local_time"),
            "relations": rels, "status": tr(STATUS_LABELS[res.status]), "status_key": res.status,
            "disclosure": plan.levels[r.id],
        })

    titles = {row["id"]: row["title"] for row in timeline}
    details = []
    for r in plan.chain:
        p = payloads.get(r.id)
        if p is None or r.kind == "genesis":
            continue
        res = results[r.id]
        d = {"id": r.id, "seq": r.seq, "kind": r.kind, "title": titles[r.id],
             "disclosure": plan.levels[r.id], "res": res, "ev": res.earliest_verified(),
             "author": [], "later": [], "body_html": None, "content_hashes": [], "external": None}
        declared = when(r.id)
        declared_note = tr("Author declared on {date}" if declared["verified"]
                           else "Author declared on {date} (unverified date)", date=_date(declared["time"]))
        if r.kind == "entry":
            d["node_type"] = tr(TYPE_LABELS.get(p["node_type"], "Other"))
            d["project"] = p["project"]["title"]
            content = p.get("content") or {}
            if content.get("body"):
                d["content_hashes"].append({"name": "body.md", **content["body"]})
            d["content_hashes"] += content.get("files") or []
            if p.get("external"):
                ext = dict(p["external"])
                if "commit" in ext:
                    ext["note"] = tr("Code archive attached." if content.get("files")
                                     else "External reference, code content not saved")
                else:
                    ext["note"] = tr("Evidence level L2 (third-party reference)")
                d["external"] = ext
            cont = contents.get(r.id) or {}
            if "body" in cont:
                d["body_html"] = _markdown(cont["body"].decode("utf-8", "replace"))
            if p.get("author_statement"):
                d["author"].append({"text": p["author_statement"], "note": declared_note})
            if p.get("import"):
                imp = p["import"]
                lvl = tr("L2 (third-party reference)" if imp["level"] == "L2" else "L1 (author statement only)")
                text = tr("Claimed date: {date} ({precision}), evidence level {level}", date=imp["claimed_date"],
                          precision=tr(imp["precision"]), level=lvl)
                if imp["references"]:
                    text = tr("{text} — references: {refs}", text=text, refs=", ".join(imp["references"]))
                d["author"].append({"text": text, "note": declared_note})
            for rel in p["relations"]:
                d["author"].append({"text": tr("Relation: {rel} “{target}”", rel=rel_label(rel["rel"]),
                                               target=title_of(rel["to"])), "note": declared_note})
            if p.get("milestone"):
                d["author"].append({"text": tr("Marked as a milestone when recorded"), "note": declared_note})
            e = state.entries.get(r.id)
            for add_id in (e.additions if e else []):
                ap = payloads.get(add_id, {})
                w = when(add_id)
                kind = state.kinds[add_id]
                text = ap.get("text") or ap.get("statement") or ap.get("reason") or ""
                label = tr({"link": "Relation added" if ap.get("op") == "add" else "Relation withdrawn",
                            "milestone": "Milestone set" if ap.get("op") == "set" else "Milestone unset",
                            "statement": "Statement (correction)" if ap.get("corrects") else "Statement",
                            "retraction": "Retracted"}.get(kind, kind))
                d["later"].append({"label": label, "text": text, "date": _date(w["time"]),
                                   "verified": w["verified"], "id": add_id})
        else:
            text = p.get("text") or p.get("statement") or p.get("reason")
            if text:
                d["author"].append({"text": text, "note": declared_note})
        d["author"].append({"text": tr("Local clock time: {time}", time=p["local_time"]),
                            "note": tr("self-reported, unverified")})
        details.append(d)

    from app.services.narrative import build_narrative

    stamps = {rid: [(f.file, f.check.time) for f in res.file_stamps if f.check.verified]
              for rid, res in results.items() if res.file_stamps}
    narrative = build_narrative([(r.id, r.seq, r.kind, payloads.get(r.id)) for r in plan.chain], when,
                                title=meta["title"], file_stamps=stamps)
    anchors = {d["id"] for d in details}  # records with their own section below
    return {
        "narrative": narrative, "anchors": anchors,
        "meta": meta, "plan": plan, "report": report, "counts": report.counts, "trust": trust,
        "graph_svg": Markup(render_graph_svg(nodes, edges)), "timeline": timeline, "details": details,
        "proves": [tr(x) for x in PROVES], "does_not_prove": [tr(x) for x in DOES_NOT_PROVE],
        "source_note": tr(SOURCE_NOTE), "status_labels": {k: tr(v) for k, v in STATUS_LABELS.items()}, "hidden_count": sum(1 for v in plan.levels.values() if v == "existence"),
    }


def render_report(*, plan, meta, mats, contents, report, trust) -> str:
    return _env().get_template("report.html.j2").render(**build_model(plan, meta, mats, contents, report, trust))


def render_verify_md(*, plan, meta, mats, certs, uses_mock: bool) -> str:
    example = next((r for r in plan.chain if plan.levels[r.id] == "full"), None) or plan.chain[-1]
    env = _env()
    name = "VERIFY.zh.md.j2" if current() == "zh" else "VERIFY.md.j2"  # same commands, two languages
    file_stamped = any(k.endswith(".tsr") for m in mats.values() for k in (m.content or {}))
    return env.get_template(name).render(
        plan=plan, meta=meta, example=example, mats=mats, uses_mock=uses_mock, file_stamped=file_stamped,
        has_body=example.id in mats and (mats[example.id].content or {}).get("body") is not None,
    )
