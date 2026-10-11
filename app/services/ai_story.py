"""Retelling the story with a language model on this computer — optional (DECISIONS D-050).

PRD §4 sets the rules for AI: answer only from the records, point every important sentence at
its records, label everything "AI inference" and keep it apart from verified records and author
statements, and either ask before sending anything to an AI company or use a model on the
author's own computer. This is the second way: the model must run on this computer
(provenance_core.providers.local_ai only accepts loopback addresses).

What the model gets is the template story (app/services/narrative.py) as numbered facts — the
same sentences the author already sees, never the bodies of steps or their files. It must name
the facts behind every sentence ([#12]). Every sentence of its answer is then checked: one that
names no step, names a step that is not in the story, makes a claim the app never makes
(app/services/claims.py) or talks about what records can never show (originality, authorship,
ownership, being first) is flagged, and left out of what can be saved. The result is not a
record: it is shown, and can be saved as a Markdown draft labelled "AI inference".
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from app.i18n import tr
from app.services.claims import forbidden_claims
from provenance_core.providers.local_ai import LocalModel

model_factory = LocalModel  # tests put a fake server here

SYSTEM = {
    "en": (
        "You retell a research history for a reader. You are given numbered facts taken from the author's "
        "records. Rules:\n"
        "1. Use only these facts. Add nothing, guess nothing.\n"
        "2. After every sentence, write the numbers of the facts it uses in square brackets, like [#12] or "
        "[#12, #15].\n"
        "3. Say why something happened only where a fact labelled \"author's statement\" gives the reason, "
        "and then say that the author says so.\n"
        "4. Dates marked ✓ come from date stamps; other dates are only the computer's clock or the author's "
        "claim — say so if you use them.\n"
        "5. Never say the records show who had an idea first, or prove authorship, originality or ownership.\n"
        "6. Write plain, connected prose in English, in short paragraphs, following the order of the facts."
    ),
    "zh": (
        "你要为读者讲述一段研究经过。你拿到的是从作者记录里整理出来的、带编号的事实。规则：\n"
        "1. 只用这些事实。不要添加，不要猜测。\n"
        "2. 每句话后面用方括号写出它用到的事实编号，例如 [#12] 或 [#12, #15]。\n"
        "3. 只有标为“作者陈述”的事实给出了原因时，才说为什么，并且要说明这是作者说的。\n"
        "4. 带 ✓ 的日期来自日期章；其他日期只是电脑时钟或作者的说法——用到时要说明。\n"
        "5. 绝不要说这些记录说明了谁先想到，也不要说它们证明了作者身份、原创性或所有权。\n"
        "6. 用中文写通顺、连贯的文字，分成短段落，按事实的先后顺序。"
    ),
}
USER = {
    "en": "Facts from the records of “{title}”:\n\n{facts}\n\nRetell this research history.",
    "zh": "“{title}”的记录中的事实：\n\n{facts}\n\n请讲述这段研究经过。",
}
SOURCE_WORDS = {"en": ("record", "author's statement", "clock"), "zh": ("记录", "作者陈述", "时钟")}

# What the records can never show, so no AI sentence may talk about it — stricter than the claims
# the app's own texts are checked for, which may say what the records do *not* show.
_BEYOND_THE_RECORDS = re.compile(
    r"originality|\boriginal (?:idea|work|author)|authorship|ownership|\bown(?:s|ed|er|ers|ing)\b|first to\b|\binvent|\bpioneer"
    r"|原创|首创|首先提出|最早提出|最早想到|第一个想到|所有权|作者身份|归属|发明", re.IGNORECASE)
_CITATION = re.compile(r"[\[［【]\s*#?\s*\d+(?:\s*[,，、;；]\s*#?\s*\d+)*\s*[\]］】]")
_NUMBER = re.compile(r"\d+")
_SENTENCE = re.compile(
    r"(.+?(?:[。！？]+|[.!?]+(?=\s|$|[\[［【])|$)(?:\s*[\[［【][^\]］】]*[\]］】])*)", re.S)


def facts(narrative: dict, lang: str) -> tuple[str, dict[int, str]]:
    """The story as numbered facts for the model, and record number -> record id."""
    record, author, clock = SOURCE_WORDS[lang]
    lines: list[str] = []
    known: dict[int, str] = {}
    for ch in narrative["chapters"]:
        lines.append(f"## {ch['heading']}")
        for para in ch["paragraphs"]:
            for s in para:
                for r in s["refs"]:
                    if r.get("seq") is not None:
                        known[int(r["seq"])] = r["id"]
                first = s["refs"][0]["seq"] if s["refs"] else "?"
                d = s.get("date") or {}
                when = (d.get("time") or "")[:10] + (" ✓" if d.get("verified") else f" ({clock})")
                lines.append(f"[#{first}] ({when}) ({author if s['source'] == 'author' else record}) {s['text']}")
    return "\n".join(lines), known


def check(text: str, known: dict[int, str]) -> dict:
    """One sentence of the answer: which steps it names, and whether it may stand."""
    cited = [int(n) for c in _CITATION.findall(text) for n in _NUMBER.findall(c)]
    if forbidden_claims(text) or _BEYOND_THE_RECORDS.search(text):
        status = "claim"
    elif not cited:
        status = "no_source"
    elif any(n not in known for n in cited):
        status = "unknown_source"
    else:
        status = "ok"
    return {"text": text.strip(), "status": status,
            "refs": [{"seq": n, "id": known.get(n)} for n in dict.fromkeys(cited)]}


def parse(reply: str, known: dict[int, str]) -> list[dict]:
    blocks: list[dict] = []
    for line in reply.replace("\r", "").split("\n"):
        line = line.strip()
        if not line:
            if blocks and blocks[-1]["kind"] != "break":
                blocks.append({"kind": "break"})
            continue
        if line.startswith("#"):
            blocks.append({"kind": "heading", "text": line.lstrip("#").strip()})
            continue
        for m in _SENTENCE.finditer(line):
            if m.group(1).strip():
                blocks.append({"kind": "sentence", **check(m.group(1), known)})
    return blocks


def retell(narrative: dict, model: LocalModel, lang: str) -> dict:
    lang = "zh" if lang == "zh" else "en"
    fact_text, known = facts(narrative, lang)
    reply = model.chat(SYSTEM[lang], USER[lang].format(title=narrative["title"], facts=fact_text))
    blocks = parse(reply, known)
    sentences = [b for b in blocks if b["kind"] == "sentence"]
    return {
        "label": tr("AI inference"), "model": model.model, "url": model.base,
        "created": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "title": narrative["title"],
        "facts": sum(1 for line in fact_text.split("\n") if line.startswith("[#")),
        "blocks": blocks,
        "counts": {"ok": sum(s["status"] == "ok" for s in sentences),
                   "flagged": sum(s["status"] != "ok" for s in sentences)},
    }
