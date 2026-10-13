"""Retelling the story with a language model — optional (DECISIONS D-050, D-061).

PRD §4 sets the rules for AI: answer only from the records, point every important sentence at
its records, label everything "AI inference" and keep it apart from verified records and author
statements, and either ask before sending anything to an AI company or use a model on the
author's own computer. Both ways are here: a model on this computer
(provenance_core.providers.local_ai only accepts loopback addresses), or an online service the
author connected, which is sent only the text the author was shown and agreed to send, each time
(app/services/ai_cloud.py).

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
from collections.abc import AsyncIterator
from contextlib import aclosing
from datetime import UTC, datetime

from app.i18n import tr
from app.services.claims import forbidden_claims
from provenance_core.providers.local_ai import LocalModel

model_factory = LocalModel  # tests put a fake server here

# The answer is a short summary in fixed sections with bullet points, not an essay: it is quicker
# for a local model to write, and anyone can take it in at a glance (each point still names its
# steps). The model may word the headings its own way; the page shows whatever headings it wrote.
SECTIONS = {
    "en": ("In one sentence", "How it started", "What happened", "Turning points", "Where it stands now"),
    "zh": ("一句话总结", "起点", "经过", "关键转折", "现在到哪了"),
}
SYSTEM = {
    "en": (
        "You summarise a research history so that anyone can understand it, whatever their background. You "
        "are given numbered facts taken from the author's records. Rules:\n"
        "1. Use only these facts. Add nothing, guess nothing.\n"
        "2. Write these sections in this order, each starting with its heading line:\n{headings}\n"
        "   Under each heading write 1 to 4 short bullet points, each starting with \"- \". Leave out a section "
        "no fact fits.\n"
        "3. End every bullet point with the numbers of the facts it uses in square brackets, like [#12] or "
        "[#12, #15].\n"
        "4. Use everyday words and short sentences; say what a technical term means in a few words.\n"
        "5. Say why something happened only where a fact labelled \"author's statement\" gives the reason, "
        "and then say that the author says so.\n"
        "6. Dates marked ✓ come from date stamps; other dates are only the computer's clock or the author's "
        "claim — say so if you use them.\n"
        "7. Never say the records show who had an idea first, or prove authorship, originality or ownership.\n"
        "8. Write in English. Nothing before the first heading, nothing after the last bullet point."
    ),
    "zh": (
        "你要把一段研究经过总结出来，让任何背景的人都能看懂。你拿到的是从作者记录里整理出来的、带编号的事实。规则：\n"
        "1. 只用这些事实。不要添加，不要猜测。\n"
        "2. 按顺序写下面这几个部分，每部分先写一行标题：\n{headings}\n"
        "   每个标题下面写 1 到 4 条简短的要点，每条以“- ”开头。没有事实可写的部分就不写。\n"
        "3. 每条要点最后用方括号写出它用到的事实编号，例如 [#12] 或 [#12, #15]。\n"
        "4. 用日常的词、短句子；遇到专业词，用几个字说明它是什么意思。\n"
        "5. 只有标为“作者陈述”的事实给出了原因时，才说为什么，并且要说明这是作者说的。\n"
        "6. 带 ✓ 的日期来自日期章；其他日期只是电脑时钟或作者的说法——用到时要说明。\n"
        "7. 绝不要说这些记录说明了谁先想到，也不要说它们证明了作者身份、原创性或所有权。\n"
        "8. 用中文写。第一个标题之前、最后一条要点之后都不要写别的。"
    ),
}
USER = {
    "en": "Facts from the records of “{title}”:\n\n{facts}\n\nSummarise this research history in the sections above.",
    "zh": "“{title}”的记录中的事实：\n\n{facts}\n\n请按上面的几个部分总结这段研究经过。",
}
SOURCE_WORDS = {"en": ("record", "author's statement", "clock"), "zh": ("记录", "作者陈述", "时钟")}

# What the records can never show, so no AI sentence may talk about it — stricter than the claims
# the app's own texts are checked for, which may say what the records do *not* show.
_BEYOND_THE_RECORDS = re.compile(
    r"originality|\boriginal (?:idea|work|author)|authorship|ownership|\bown(?:s|ed|er|ers|ing)\b|first to\b|\binvent|\bpioneer"
    r"|原创|首创|首先提出|最早提出|最早想到|第一个想到|所有权|作者身份|归属|发明", re.IGNORECASE)
_CITATION = re.compile(r"[\[［【]\s*#?\s*\d+(?:\s*[,，、;；]\s*#?\s*\d+)*\s*[\]］】]")
_NUMBER = re.compile(r"\d+")
_BULLET = re.compile(r"^(?:[-*•·]\s+|\d+[.)]\s+|\d+、\s*)")
_EMPHASIS = re.compile(r"\*\*|__")
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


_SECTION_NAMES = {name for names in SECTIONS.values() for name in names}


def _heading(line: str) -> str | None:
    """A heading line: "## Turning points", "**Turning points**" or "Turning points:" alone."""
    if line.startswith("#"):
        return line.lstrip("#").strip()
    bare = _EMPHASIS.sub("", line).strip()
    if _CITATION.search(bare) or len(bare) > 40:
        return None
    if line.startswith(("**", "__")) or bare.endswith((":", "：")) or bare in _SECTION_NAMES:
        return bare.rstrip(":：").strip()
    return None


def parse(reply: str, known: dict[int, str]) -> list[dict]:
    """The answer as headings, bullet points ("item" starts one) and sentences, each sentence checked."""
    blocks: list[dict] = []
    for line in reply.replace("\r", "").split("\n"):
        line = line.strip()
        if not line:
            if blocks and blocks[-1]["kind"] != "break":
                blocks.append({"kind": "break"})
            continue
        heading = _heading(line)
        if heading is not None:
            if heading:
                blocks.append({"kind": "heading", "text": heading})
            continue
        bullet = _BULLET.match(line)
        if bullet:
            blocks.append({"kind": "item"})
            line = line[bullet.end():]
        line = _EMPHASIS.sub("", line)
        for m in _SENTENCE.finditer(line):
            if m.group(1).strip():
                blocks.append({"kind": "sentence", **check(m.group(1), known)})
    return blocks


def prompt(narrative: dict, lang: str) -> tuple[str, str, dict[int, str], int]:
    """What the model is asked (system and user message), and the facts it may cite."""
    fact_text, known = facts(narrative, lang)
    headings = "\n".join(f"   ## {h}" for h in SECTIONS[lang])
    count = sum(1 for line in fact_text.split("\n") if line.startswith("[#"))
    return (SYSTEM[lang].format(headings=headings), USER[lang].format(title=narrative["title"], facts=fact_text),
            known, count)


def result(narrative: dict, model: LocalModel, reply: str, known: dict[int, str], count: int,
           label: str | None = None) -> dict:
    blocks = parse(reply, known)
    sentences = [b for b in blocks if b["kind"] == "sentence"]
    return {
        "label": label or tr("AI inference"), "model": model.model, "url": model.base,
        "service": getattr(model, "service", None),  # an online service by name; None on this computer
        "created": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "title": narrative["title"],
        "facts": count,
        "blocks": blocks,
        "counts": {"ok": sum(s["status"] == "ok" for s in sentences),
                   "flagged": sum(s["status"] != "ok" for s in sentences)},
    }


def retell(narrative: dict, model: LocalModel, lang: str) -> dict:
    lang = "zh" if lang == "zh" else "en"
    system, user, known, count = prompt(narrative, lang)
    return result(narrative, model, model.chat(system, user), known, count)


async def retell_stream(narrative: dict, model: LocalModel, lang: str, label: str | None = None,
                        prepared: tuple[str, str, dict[int, str], int] | None = None) -> AsyncIterator[dict]:
    """The same, as it is written: {"text": piece} while the model writes, then {"result": ...},
    checked sentence by sentence like retell(). ``prepared`` is prompt()'s answer when the caller
    already has it — the very text the author was shown before an online service gets it."""
    lang = "zh" if lang == "zh" else "en"
    system, user, known, count = prepared or prompt(narrative, lang)
    reply: list[str] = []
    # Closed as soon as this is: that ends the connection to the model there and then.
    async with aclosing(model.chat_stream(system, user)) as pieces:
        async for piece in pieces:
            reply.append(piece)
            yield {"text": piece}
    yield {"result": result(narrative, model, "".join(reply), known, count, label)}
