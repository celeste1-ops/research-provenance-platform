"""A translation of a step, by the language model on this computer (DECISIONS D-066).

It is shown beside the original and marked as a translation; it is never saved and never a
record. The author's own words are the record, signed and date-stamped exactly as written
(D-065); a translation is other words, which the stamps do not cover. Only a model on this
computer is asked (D-050): an online service is never given the text of a step (D-061).
"""

from __future__ import annotations

import json
import re

from provenance_core.providers.local_ai import LocalAIError, LocalModel

LANG_NAMES = {"en": "English", "zh": "Simplified Chinese"}
MAX_CHARS = 8000  # title and text; a longer text is translated up to here, and says so
MAX_TOKENS = 6000
SYSTEM = (
    "You translate a researcher's notes into {language}. Translate faithfully: keep the meaning, and keep "
    "numbers, formulas, code, names, links and Markdown exactly as they are. Add nothing, leave nothing out, "
    "and do not explain or comment. Answer in exactly this form and nothing else:\n"
    "<<TITLE>>\nthe translated title\n<<TEXT>>\nthe translated text (empty if there is no text)"
)
_THINKING = re.compile(r"<think>.*?</think>", re.S | re.I)  # some local models write their thinking first
_TEXT_MODELS = re.compile(r"embed|rerank|whisper|tts|vision-only", re.I)

model_factory = LocalModel  # tests put a fake server here


def source(ledger, record_id: str) -> tuple[str, str] | None:
    """The title and text of a step as written, or None if it is not a step."""
    rec = ledger.record(record_id)
    if rec is None or rec.kind != "entry":
        return None
    title = str(json.loads(rec.payload_bytes).get("title") or "")
    body = next((f for f in ledger.record_files(record_id) if f.role == "body"), None)
    text = ledger.blobs.get(body.sha256).decode("utf-8", "replace") if body else ""
    return title, text


def pick_model(model: LocalModel) -> str:
    """A model of the local server that writes text, when the author has not chosen one yet."""
    names = model.models()
    return next((n for n in names if not _TEXT_MODELS.search(n)), names[0] if names else "")


def parse(reply: str) -> tuple[str, str]:
    reply = _THINKING.sub("", reply).strip()
    if "<<TITLE>>" in reply and "<<TEXT>>" in reply:
        title, _, text = reply.split("<<TITLE>>", 1)[1].partition("<<TEXT>>")
        return title.strip(), text.strip()
    first, _, rest = reply.partition("\n")  # the form was not kept: the first line is the title
    return first.strip(), rest.strip()


def translate(url: str, model_name: str, title: str, text: str, lang: str) -> dict:
    """Ask the model on this computer; return the translation and what made it."""
    model = model_factory(url, model_name, max_tokens=MAX_TOKENS)
    if not model.model:
        model.model = pick_model(model)
        if not model.model:
            raise LocalAIError("choose a model first")
    shortened = len(title) + len(text) > MAX_CHARS
    text = text[: max(0, MAX_CHARS - len(title))]
    user = f"<<TITLE>>\n{title}\n<<TEXT>>\n{text}"
    new_title, new_text = parse(model.chat(SYSTEM.format(language=LANG_NAMES[lang]), user))
    return {"title": new_title, "text": new_text, "model": model.model, "url": model.base, "lang": lang,
            "shortened": shortened}
