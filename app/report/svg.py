"""Static SVG evolution graph for report.html (PRD §11, §12) — no JavaScript needed.

Records run left to right by seq, one row per node type that occurs; arrows go
from the older record to the newer one. revises = solid, derived_from = dashed,
uses = dotted. Relations added later carry their added date; withdrawn ones are
grey with the withdrawal date. Milestones are highlighted.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from app.i18n import tr

COL_W = 178
ROW_H = 96
NODE_W = 152
NODE_H = 60
LEFT = 130
TOP = 58

DASH = {"revises": None, "derived_from": "7 4", "uses": "2 4"}
TYPE_LABELS = {
    "idea": "Idea",
    "note": "Note",
    "claim": "Claim",
    "document": "Document",
    "code": "Code",
    "experiment": "Experiment",
    "dataset": "Dataset",
    "figure": "Figure",
    "publication": "Publication",
}


def _short(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def _icon(x: float, y: float, letter: str, state: str) -> str:
    title = tr({"confirmed": "confirmed", "pending": "pending", "none": "none", "not_enabled": "not enabled"}.get(
        state, state
    ))
    name = tr("Third-party timestamp" if letter == "T" else "Bitcoin anchor")
    if state == "confirmed":
        circle = f'<circle cx="{x}" cy="{y}" r="7" class="ic-on"/>'
        text_cls = "ic-t-on"
    elif state == "pending":
        circle = f'<circle cx="{x}" cy="{y}" r="7" class="ic-pending"/>'
        text_cls = "ic-t"
    else:
        circle = f'<circle cx="{x}" cy="{y}" r="7" class="ic-off"/>'
        text_cls = "ic-t-off"
    return (
        f"<g><title>{escape(tr('{label}: {state}', label=name, state=title))}</title>{circle}"
        f'<text x="{x}" y="{y + 3.5}" class="{text_cls}" text-anchor="middle">{letter}</text></g>'
    )


def render_graph_svg(nodes: list[dict], edges: list[dict]) -> str:
    """nodes: id, seq, title, node_type, milestone, retracted, date (YYYY-MM-DD or ''),
    tsa_state, btc_state. edges: from (older), to (newer), rel, origin, added, withdrawn."""
    if not nodes:
        return f'<p class="muted">{escape(tr("No disclosed entries to draw."))}</p>'
    nodes = sorted(nodes, key=lambda n: n["seq"])
    known = list(TYPE_LABELS)
    present = [t for t in known if any(n["node_type"] == t for n in nodes)]
    present += sorted({n["node_type"] for n in nodes} - set(known))
    row_of = {t: i for i, t in enumerate(present)}
    pos = {}
    for col, n in enumerate(nodes):
        pos[n["id"]] = (LEFT + col * COL_W, TOP + row_of[n["node_type"]] * ROW_H)
    width = LEFT + len(nodes) * COL_W + 20
    height = TOP + len(present) * ROW_H + 40
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'role="img" aria-label="{escape(tr("Evolution graph"))}">',
        "<defs>"
        '<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        '<path d="M0,0 L10,5 L0,10 z" class="arrowhead"/></marker>'
        '<marker id="arrow-grey" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        '<path d="M0,0 L10,5 L0,10 z" class="arrowhead-grey"/></marker>'
        "</defs>",
    ]
    for t, i in row_of.items():
        y = TOP + i * ROW_H
        out.append(f'<rect x="0" y="{y - 8}" width="{width}" height="{ROW_H - 4}" class="lane{i % 2}"/>')
        out.append(
            f'<text x="12" y="{y + NODE_H / 2 + 4}" class="lane-label">{escape(tr(TYPE_LABELS[t]) if t in TYPE_LABELS else tr("Other: {type}", type=t))}</text>'
        )
    for col, n in enumerate(nodes):
        x = LEFT + col * COL_W
        out.append(f'<text x="{x + NODE_W / 2}" y="24" class="date" text-anchor="middle">{escape(n["date"] or "—")}</text>')
        out.append(f'<text x="{x + NODE_W / 2}" y="40" class="seq" text-anchor="middle">#{n["seq"]}</text>')
    for e in edges:
        if e["from"] not in pos or e["to"] not in pos:
            continue
        x1, y1 = pos[e["from"]]
        x2, y2 = pos[e["to"]]
        sx, sy = x1 + NODE_W, y1 + NODE_H / 2
        tx, ty = x2, y2 + NODE_H / 2
        if tx <= sx:  # same column cannot happen (one record per column), but stay safe
            tx = sx + 10
        mid = (sx + tx) / 2
        d = f"M{sx},{sy} C{mid},{sy} {mid},{ty} {tx},{ty}"
        grey = not e.get("active", True)
        dash = DASH.get(e["rel"], "1 3")
        attrs = f' stroke-dasharray="{dash}"' if dash else ""
        cls = "edge-grey" if grey else "edge"
        marker = "arrow-grey" if grey else "arrow"
        rel_text = tr({"revises": "revises", "derived_from": "derived from", "uses": "uses"}.get(e["rel"], "other relation"))
        out.append(f'<path d="{d}" class="{cls}"{attrs} marker-end="url(#{marker})"><title>{escape(rel_text)}</title></path>')
        label = ""
        if e.get("withdrawn"):
            label = tr("withdrawn {date}", date=e["withdrawn"])
        elif e.get("origin") == "link" and e.get("added"):
            label = tr("added {date}", date=e["added"])
        if label:
            lx, ly = (sx + tx) / 2, (sy + ty) / 2 - 6
            out.append(f'<text x="{lx}" y="{ly}" class="edge-label" text-anchor="middle">{escape(label)}</text>')
    for n in nodes:
        x, y = pos[n["id"]]
        cls = "node"
        if n.get("milestone"):
            cls += " milestone"
        if n.get("retracted"):
            cls += " retracted"
        # Pointing at a box shows what the step says, or why it is not shown (D-057).
        out.append(f'<g class="{cls}"><title>{escape(n.get("tip") or n["title"])}</title>')
        out.append(f'<rect x="{x}" y="{y}" width="{NODE_W}" height="{NODE_H}" rx="7"/>')
        title = ("★ " if n.get("milestone") else "") + n["title"]
        out.append(f'<text x="{x + 9}" y="{y + 20}" class="node-title">{escape(_short(title, 22))}</text>')
        sub = tr("retracted") if n.get("retracted") else (n["date"] or tr("no verified time"))
        out.append(f'<text x="{x + 9}" y="{y + 38}" class="node-sub">{escape(sub)}</text>')
        out.append(_icon(x + NODE_W - 34, y + NODE_H - 13, "T", n.get("tsa_state", "none")))
        out.append(_icon(x + NODE_W - 15, y + NODE_H - 13, "B", n.get("btc_state", "none")))
        out.append("</g>")
    out.append("</svg>")
    return "".join(out)
