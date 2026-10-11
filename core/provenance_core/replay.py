"""Derive the *current state* by replaying every record in ``seq`` order (PRD §7 rule 1).

Nothing is ever edited: a later ``link`` adds or withdraws a relation, a
``milestone`` record sets or unsets a flag, a ``statement`` adds a note or
correction, a ``retraction`` withdraws an entry. The state below is a pure
function of the log, so it can be rebuilt at any time.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Edge:
    """A relation "source rel target" (new record rel older record).

    Arrows are drawn from ``target`` (older) to ``source`` (newer).
    """

    source: str
    target: str
    rel: str
    origin: str  # "entry" (fixed in the entry's payload) or "link" (added later)
    added_by: str
    statement: str | None = None
    withdrawn_by: str | None = None

    @property
    def active(self) -> bool:
        return self.withdrawn_by is None


@dataclass
class EntryState:
    id: str
    seq: int
    project_id: str
    project_title: str
    node_type: str
    title: str
    milestone: bool
    payload: dict
    milestone_changes: list[tuple[str, str]] = field(default_factory=list)  # (record_id, op)
    statements: list[str] = field(default_factory=list)
    retracted_by: str | None = None
    additions: list[str] = field(default_factory=list)  # later records that touch this entry


@dataclass
class StatementState:
    id: str
    seq: int
    target: str
    source: str
    text: str
    corrects: str | None
    corrected_by: list[str] = field(default_factory=list)


@dataclass
class ReplayState:
    entries: dict[str, EntryState] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    statements: dict[str, StatementState] = field(default_factory=dict)
    kinds: dict[str, str] = field(default_factory=dict)
    seqs: dict[str, int] = field(default_factory=dict)
    payloads: dict[str, dict] = field(default_factory=dict)
    hidden: set[str] = field(default_factory=set)
    genesis: dict | None = None

    def additions_for(self, record_id: str) -> list[str]:
        e = self.entries.get(record_id)
        return list(e.additions) if e else []


def _touch(state: ReplayState, target: str, by: str) -> None:
    e = state.entries.get(target)
    if e is not None and by not in e.additions:
        e.additions.append(by)


def replay(records: list[tuple[str, int, str, dict | None]]) -> ReplayState:
    """``records``: (record_id, seq, kind, payload or None if not disclosed)."""
    state = ReplayState()
    for rid, seq, kind, payload in sorted(records, key=lambda r: r[1]):
        state.kinds[rid] = kind
        state.seqs[rid] = seq
        if payload is None:
            state.hidden.add(rid)
            continue
        state.payloads[rid] = payload
        if kind == "genesis":
            state.genesis = payload
        elif kind == "entry":
            state.entries[rid] = EntryState(
                id=rid,
                seq=seq,
                project_id=payload["project"]["id"],
                project_title=payload["project"]["title"],
                node_type=payload["node_type"],
                title=payload["title"],
                milestone=bool(payload["milestone"]),
                payload=payload,
            )
            for rel in payload.get("relations") or []:
                state.edges.append(Edge(rid, rel["to"], rel["rel"], "entry", rid))
        elif kind == "link":
            src, dst, rel = payload["from"], payload["to"], payload["rel"]
            if payload["op"] == "add":
                state.edges.append(Edge(src, dst, rel, "link", rid, payload.get("statement")))
            else:
                for edge in state.edges:
                    if edge.active and (edge.source, edge.target, edge.rel) == (src, dst, rel):
                        edge.withdrawn_by = rid
            _touch(state, src, rid)
            _touch(state, dst, rid)
        elif kind == "milestone":
            e = state.entries.get(payload["target"])
            if e is not None:
                e.milestone = payload["op"] == "set"
                e.milestone_changes.append((rid, payload["op"]))
            _touch(state, payload["target"], rid)
        elif kind == "statement":
            st = StatementState(
                rid, seq, payload["target"], payload["source"], payload["text"], payload.get("corrects")
            )
            state.statements[rid] = st
            if st.corrects and st.corrects in state.statements:
                state.statements[st.corrects].corrected_by.append(rid)
            target = payload["target"]
            e = state.entries.get(target)
            if e is not None:
                e.statements.append(rid)
            elif target in state.statements:
                # A statement about a statement belongs to the same entry.
                root = state.statements[target].target
                if root in state.entries:
                    state.entries[root].statements.append(rid)
                    target = root
            _touch(state, target, rid)
        elif kind == "retraction":
            e = state.entries.get(payload["target"])
            if e is not None and e.retracted_by is None:
                e.retracted_by = rid
            _touch(state, payload["target"], rid)
    return state


def milestone_view(state: ReplayState) -> tuple[list[str], list[tuple[str, str, int]]]:
    """Milestones only (PRD §11): the milestone entries, plus one dashed connector
    per pair of milestones joined by a relation path through non-milestones.

    Returns (milestone_ids, [(older_id, newer_id, hidden_count)]).
    """
    milestones = [e.id for e in sorted(state.entries.values(), key=lambda e: e.seq) if e.milestone]
    ms = set(milestones)
    # Graph from older to newer along active relations.
    forward: dict[str, list[str]] = {}
    for edge in state.edges:
        if edge.active:
            forward.setdefault(edge.target, []).append(edge.source)
    connectors: list[tuple[str, str, int]] = []
    for start in milestones:
        # BFS through non-milestone nodes; stop at the first milestone on each path.
        best: dict[str, int] = {}
        frontier = [(start, 0)]
        seen = {start}
        while frontier:
            node, hidden = frontier.pop(0)
            for nxt in forward.get(node, []):
                if nxt in seen:
                    continue
                seen.add(nxt)
                if nxt in ms:
                    if nxt not in best or hidden < best[nxt]:
                        best[nxt] = hidden
                else:
                    frontier.append((nxt, hidden + 1))
        for end, hidden in best.items():
            connectors.append((start, end, hidden))
    return milestones, connectors
