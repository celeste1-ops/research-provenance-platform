"""The research told in sentences, without AI (DECISIONS D-048).

Walks the records in the order they were made and writes one short paragraph per step and per
later addition, from fixed sentences in the current language. Every sentence names the records
it comes from (so the interface and the report can link to them) and says what kind of
information it is: what was recorded ("record") or what the author said ("author": reasons,
notes, claimed dates, and the links between steps, which are the author's statements too).
Nothing is inferred: a "why" appears only where the author wrote one, quoted as written.

The input is whatever the caller may show: the app passes every record, the report only what
the bundle discloses (a record without payload is "not disclosed", with its date only).
"""

from __future__ import annotations

from collections.abc import Callable

from app.i18n import tr

# What the main sentence calls each kind of step ("the author recorded an idea: …").
KIND_PHRASES = {
    "idea": "an idea", "note": "a note", "claim": "a hypothesis or claim", "document": "a document",
    "code": "code", "experiment": "an experiment", "dataset": "data", "figure": "a figure",
    "publication": "a paper",
}
OTHER_KIND = "a step"
RELATION_SENTENCES = {
    "revises": "The author marked it as a new version of {targets}.",
    "derived_from": "The author noted that it grew out of {targets}.",
    "uses": "The author noted that it builds on {targets}.",
}
OTHER_RELATION = "The author linked it to {targets}."
ADDED_LINKS = {
    "revises": "On {date} the author added that {a} is a new version of {b}.",
    "derived_from": "On {date} the author added that {a} grew out of {b}.",
    "uses": "On {date} the author added that {a} builds on {b}.",
}
OTHER_ADDED_LINK = "On {date} the author added a link from {a} to {b}."
NOTE_SENTENCES = {
    False: "On {date} the author added a note about {title}: {text}",
    True: "On {date} the author added a correction about {title}: {text}",
}
MAX_FILES_NAMED = 3

Record = tuple[str, int, str, dict | None]  # id, seq, kind, payload (None: not disclosed)
When = Callable[[str], dict]  # record id -> {"time", "verified", "from"}


def _q(text: str) -> str:
    return tr("“{text}”", text=text)


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return tr("{a} and {b}", a=tr(", ").join(items[:-1]), b=items[-1])


def build_narrative(records: list[Record], when: When, *, title: str, project_id: str | None = None,
                    file_stamps: dict[str, list[tuple[str, str]]] | None = None) -> dict:
    """``records`` in recording order. With ``project_id`` only that project's steps (and the
    later additions about them) are told. ``file_stamps``: record id -> verified (file, time)
    date stamps of its attached files (D-049)."""
    from provenance_core.replay import replay

    state = replay(records)
    seqs = {rid: seq for rid, seq, _k, _p in records}

    def in_scope(rid: str) -> bool:
        e = state.entries.get(rid)
        return e is not None and (project_id is None or e.project_id == project_id)

    def title_of(rid: str) -> str:
        e = state.entries.get(rid)
        return _q(e.title) if e else tr("record #{seq}", seq=seqs.get(rid, "?"))

    def date(rid: str) -> str:
        return (when(rid).get("time") or "")[:10]

    def sentence(text: str, refs: list[str], source: str = "record") -> dict:
        return {"text": text, "source": source,
                "refs": [{"id": r, "seq": seqs.get(r)} for r in refs], "date": when(refs[0]) if refs else None}

    def entry_paragraph(rid: str, p: dict) -> list[dict]:
        out = [sentence(tr("On {date} the author recorded {kind}: {title}.", date=date(rid),
                           kind=tr(KIND_PHRASES.get(p["node_type"], OTHER_KIND)), title=_q(p["title"])), [rid])]
        if p.get("import"):
            out.append(sentence(tr("It is older material added that day; the author dates it to {claimed} — "
                                   "the author's statement, not a verified date.", claimed=p["import"]["claimed_date"]),
                                [rid], "author"))
        by_rel: dict[str, list[str]] = {}
        for rel in p.get("relations") or []:
            by_rel.setdefault(rel["rel"], []).append(rel["to"])
        for rel, targets in by_rel.items():
            out.append(sentence(tr(RELATION_SENTENCES.get(rel, OTHER_RELATION),
                                   targets=_join([title_of(t) for t in targets])), [rid, *targets], "author"))
        if p.get("author_statement"):
            out.append(sentence(tr("The author's reason at the time: {text}", text=_q(p["author_statement"])),
                                [rid], "author"))
        ext = p.get("external") or {}
        files = [f["name"] for f in ((p.get("content") or {}).get("files") or []) if not f["name"].endswith(".tsr")]
        if ext.get("commit"):
            repo = ext.get("repo_url", "").rstrip("/").rsplit("/", 1)[-1].removesuffix(".git") or ext.get("repo_url", "")
            out.append(sentence(tr("It refers to commit {commit} of {repo}.", commit=ext["commit"][:7], repo=repo), [rid]))
            out.append(sentence(tr("The code itself is kept with it.") if files else
                                tr("The code itself is not kept in the record, only the reference."), [rid]))
        elif ext.get("doi") or ext.get("url"):
            out.append(sentence(tr("It refers to {ref}.", ref=ext.get("doi") or ext.get("url")), [rid]))
        if files and not ext.get("commit"):
            named = files[:MAX_FILES_NAMED]
            if len(files) > MAX_FILES_NAMED:
                named.append(tr("{n} more files", n=len(files) - MAX_FILES_NAMED))
            out.append(sentence(tr("It holds {files}.", files=_join(named)), [rid]))
        for file, time in (file_stamps or {}).get(rid, []):
            out.append(sentence(tr("The file {file} already existed by {time}, when it arrived in the inbox "
                                   "(date stamp).", file=file, time=time), [rid]))
        if p.get("milestone"):
            out.append(sentence(tr("The author marked it as a key step."), [rid], "author"))
        return out

    def addition_paragraph(rid: str, kind: str, p: dict) -> list[dict] | None:
        d = date(rid)
        if kind == "link":
            if not (in_scope(p["from"]) or in_scope(p["to"])):
                return None
            a, b = title_of(p["from"]), title_of(p["to"])
            if p["op"] == "withdraw":
                text = tr("On {date} the author withdrew the link between {a} and {b}.", date=d, a=a, b=b)
            else:
                text = tr(ADDED_LINKS.get(p["rel"], OTHER_ADDED_LINK), date=d, a=a, b=b)
            out = [sentence(text, [rid, p["from"], p["to"]], "author")]
            if p.get("statement"):
                out.append(sentence(tr("Reason given: {text}", text=_q(p["statement"])), [rid], "author"))
            return out
        target = p.get("target")
        if not in_scope(target):
            return None
        t = title_of(target)
        if kind == "milestone":
            text = (tr("On {date} the author marked {title} as a key step.", date=d, title=t) if p["op"] == "set"
                    else tr("On {date} the author removed the key-step mark from {title}.", date=d, title=t))
            return [sentence(text, [rid, target], "author")]
        if kind == "statement":
            template = NOTE_SENTENCES[bool(p.get("corrects"))]
            return [sentence(tr(template, date=d, title=t, text=_q(p["text"])), [rid, target], "author")]
        if kind == "retraction":
            return [sentence(tr("On {date} {title} was retracted.", date=d, title=t), [rid, target]),
                    sentence(tr("Reason given: {text}", text=_q(p["reason"])), [rid], "author")]
        return None

    # One paragraph per step or later addition, in recording order.
    items: list[tuple[str, list[dict]]] = []  # (record id, sentences)
    hidden: list[str] = []

    def flush_hidden() -> None:
        if not hidden:
            return
        first, last = seqs[hidden[0]], seqs[hidden[-1]]
        text = ((tr("Record #{seq} is not disclosed here; only that it existed by {date} is shown.",
                    seq=first, date=date(hidden[0])) if date(hidden[0])
                 else tr("Record #{seq} is not disclosed here.", seq=first)) if len(hidden) == 1 else
                tr("Records #{first} to #{last} are not disclosed here; only that they existed is shown.",
                   first=first, last=last))
        items.append((hidden[0], [sentence(text, hidden[:1])]))
        hidden.clear()

    for rid, _seq, kind, p in records:
        if kind == "genesis":
            continue
        if p is None:
            hidden.append(rid)
            continue
        flush_hidden()
        para = entry_paragraph(rid, p) if kind == "entry" and in_scope(rid) else (
            None if kind == "entry" else addition_paragraph(rid, kind, p))
        if para:
            items.append((rid, para))
    flush_hidden()

    # Chapters end at the steps the author marked as key steps; without any, one per month.
    entries = [state.entries[r] for r, *_ in records if in_scope(r)]
    key_steps = {e.id for e in entries if e.milestone}
    chapters: list[dict] = []
    current: list[list[dict]] = []
    month = None
    for rid, para in items:
        m = date(rid)[:7]
        if not key_steps and current and m != month:
            chapters.append({"heading": month, "paragraphs": current})
            current = []
        month = m
        current.append(para)
        if rid in key_steps:
            chapters.append({"heading": tr("Up to {title}", title=title_of(rid)), "paragraphs": current})
            current = []
    if current:
        last_key = next((e.id for e in reversed(entries) if e.id in key_steps), None)
        heading = tr("After {title}", title=title_of(last_key)) if last_key else month
        chapters.append({"heading": heading, "paragraphs": current})

    dates = [date(e.id) for e in entries]
    intro = [sentence(tr("This account of {title} was put together from the records with fixed sentences — "
                         "no AI, and nothing that is not in the records.", title=_q(title)), [])]
    if entries:
        if len(entries) == 1:
            span = tr("It covers one step, recorded on {first}.", first=dates[0])
        elif min(dates) == max(dates):
            span = tr("It covers {n} steps, all recorded on {first}.", n=len(entries), first=dates[0])
        else:
            span = tr("It covers {n} steps recorded from {first} to {last}.", n=len(entries), first=min(dates),
                      last=max(dates))
        intro.append(sentence(span, []))
        if key_steps:
            intro.append(sentence(tr("{n} of them are marked as key steps; each part ends with one.",
                                     n=len(key_steps)), []))
    intro.append(sentence(tr("A ✓ marks a date from a date stamp; other dates are the computer's own clock. "
                             "Highlighted sentences are the author's statements: reasons, notes, claimed dates "
                             "and the links between steps."), []))
    return {"title": title, "intro": intro, "chapters": chapters, "steps": len(entries)}
