"""D-050: the AI retelling may only talk to a model on this computer, and its answer is checked
sentence by sentence; nothing it writes becomes a record."""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from app.i18n import language
from app.services.ai_story import facts, parse, retell
from app.services.narrative import build_narrative
from app.services.views import Snapshot
from provenance_core.providers.local_ai import LocalAIError, LocalModel, loopback_url
from tests.sample import build_log


@pytest.mark.parametrize("url,expected", [
    ("http://127.0.0.1:11434", "http://127.0.0.1:11434"),
    ("localhost:1234", "http://localhost:1234"),
    ("http://[::1]:11434/v1/", "http://[::1]:11434"),
    ("http://127.0.0.2:8080", "http://127.0.0.2:8080"),
])
def test_addresses_on_this_computer_are_accepted(url, expected):
    assert loopback_url(url) == expected


@pytest.mark.parametrize("url", [
    "http://example.com:11434", "http://192.168.1.5:11434", "http://10.0.0.1", "http://127.0.0.1.evil.com",
    "http://user:secret@127.0.0.1:11434", "ftp://127.0.0.1", "http://0.0.0.0:11434", "https://api.openai.com/v1", "",
])
def test_anything_else_is_refused(url):
    with pytest.raises(LocalAIError, match="only a model on this computer"):
        loopback_url(url)


def fake_server(reply: str = "Fine [#1].", seen: list | None = None) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.host in ("127.0.0.1", "localhost")
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "qwen2.5:7b"}, {"id": "llama3.1:8b"}]})
        if request.url.path == "/v1/chat/completions":
            body = json.loads(request.content)
            if seen is not None:
                seen.append(body)
            if body["stream"]:  # server-sent events, a few characters at a time, as Ollama sends them
                pieces = [reply[i:i + 7] for i in range(0, len(reply), 7)]
                sse = "".join(f"data: {json.dumps({'choices': [{'delta': {'content': p}}]})}\n\n" for p in pieces)
                return httpx.Response(200, text=sse + "data: [DONE]\n\n")
            return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})
        return httpx.Response(404)
    return httpx.MockTransport(handle)


def test_the_client_lists_models_and_chats():
    seen: list = []
    model = LocalModel("http://127.0.0.1:11434", "qwen2.5:7b", transport=fake_server("Hello [#1].", seen))
    assert model.models() == ["llama3.1:8b", "qwen2.5:7b"]
    assert model.chat("system", "user") == "Hello [#1]."
    assert seen[0]["model"] == "qwen2.5:7b" and seen[0]["stream"] is False
    assert [m["role"] for m in seen[0]["messages"]] == ["system", "user"]
    assert seen[0]["max_tokens"]  # an answer cannot run on for ever


def collect(pieces) -> list:
    """Every piece of an async answer. In a thread of its own: the browser tests leave an event
    loop running in this one."""
    async def run():
        return [p async for p in pieces]
    with ThreadPoolExecutor(1) as pool:
        return pool.submit(asyncio.run, run()).result()


def test_the_answer_can_come_piece_by_piece():
    seen: list = []
    model = LocalModel("http://127.0.0.1:11434", "qwen2.5:7b", transport=fake_server("A longer answer [#1].", seen))
    pieces = collect(model.chat_stream("system", "user"))
    assert len(pieces) > 1 and "".join(pieces) == "A longer answer [#1]." and seen[0]["stream"] is True
    garbled = httpx.MockTransport(lambda r: httpx.Response(200, text="data: {not json\n\n"))
    with pytest.raises(LocalAIError, match="not readable"):
        collect(LocalModel("http://127.0.0.1:11434", "m", transport=garbled).chat_stream("s", "u"))
    missing = httpx.MockTransport(lambda r: httpx.Response(404, text="model not found"))
    with pytest.raises(LocalAIError, match="HTTP 404"):
        collect(LocalModel("http://127.0.0.1:11434", "m", transport=missing).chat_stream("s", "u"))


def test_redirects_are_not_followed_and_errors_are_plain():
    redirect = httpx.MockTransport(lambda r: httpx.Response(302, headers={"Location": "https://example.com/v1/models"}))
    with pytest.raises(LocalAIError, match="HTTP 302"):
        LocalModel("http://127.0.0.1:11434", transport=redirect).models()

    def refuse(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(LocalAIError, match="no local model answered"):
        LocalModel("http://127.0.0.1:9", transport=httpx.MockTransport(refuse)).models()
    with pytest.raises(LocalAIError, match="choose a model"):
        LocalModel("http://127.0.0.1:11434", transport=fake_server()).chat("s", "u")


@pytest.fixture
def story(ctx):
    build_log(ctx)
    snap = Snapshot.load(ctx.ledger, ctx.anchors)
    return build_narrative([(r.id, r.seq, r.kind, snap.payloads[r.id]) for r in snap.rows], snap.when, title="FSF")


def test_the_model_gets_the_story_never_the_bodies(story):
    text, known = facts(story, "en")
    assert "[#1]" in text and "(author's statement)" in text and "came from last year" in text
    assert "secret draft wording" not in text and "converged after 40 steps" not in text and "E = m c^2" not in text
    assert set(known) == {1, 2, 3, 4, 5, 6, 7}  # every step and later addition the story names


def test_every_sentence_is_checked(story):
    seen: list = []
    reply = ("## Beginning\nThe work began with an idea [#1]. It was tested in an experiment [#2, #1].\n"
             "This shows the author's originality and proves authorship [#1]. A claim without a source.\n"
             "It cites a record that does not exist [#40].")
    model = LocalModel("http://127.0.0.1:11434", "qwen2.5:7b", transport=fake_server(reply, seen))
    out = retell(story, model, "en")
    statuses = [b["status"] for b in out["blocks"] if b["kind"] == "sentence"]
    assert statuses == ["ok", "ok", "claim", "no_source", "unknown_source"]
    assert out["counts"] == {"ok": 2, "flagged": 3} and out["label"] == "AI inference"
    assert out["blocks"][1]["refs"][0]["id"]  # each cited step links to its record
    assert "Summarise this research history" in seen[0]["messages"][1]["content"]
    assert "## Turning points" in seen[0]["messages"][0]["content"]  # the sections it is asked for
    with language("zh"):
        out = retell(story, LocalModel("http://127.0.0.1:11434", "m", transport=fake_server("一句 [#1]。", seen)), "zh")
    assert out["label"] == "AI 推断" and "请按上面的几个部分总结" in seen[1]["messages"][1]["content"]
    assert "## 关键转折" in seen[1]["messages"][0]["content"]
    assert [b["status"] for b in parse("没有来源。有来源【#1】。", {1: "x"})] == ["no_source", "ok"]


def test_the_summary_comes_in_sections_of_points(story):
    """Models write headings and bullet points in several ways; each becomes a heading, or an item
    whose sentences are checked one by one."""
    reply = ("## In one sentence\n- The work tested an idea [#1].\n\n**How it started**\n"
             "* It began with an idea [#1]. Then came an experiment [#2].\n"
             "Where it stands now:\n1. **A result** was written down [#3].\n2. Something without a source.")
    blocks = parse(reply, {1: "a", 2: "b", 3: "c"})
    assert [b["kind"] if b["kind"] != "sentence" else b["status"] for b in blocks] == [
        "heading", "item", "ok", "break", "heading", "item", "ok", "ok", "heading", "item", "ok", "item", "no_source"]
    assert [b["text"] for b in blocks if b["kind"] == "heading"] == [
        "In one sentence", "How it started", "Where it stands now"]
    assert blocks[-3]["text"] == "A result was written down [#3]."  # emphasis marks are dropped


def test_the_streamed_summary_is_checked_like_the_whole(story):
    from app.services.ai_story import retell_stream

    reply = "## How it started\n- It began with an idea [#1].\n- This proves authorship [#1]."
    model = LocalModel("http://127.0.0.1:11434", "m", transport=fake_server(reply))
    events = collect(retell_stream(story, model, "en"))
    assert "".join(e["text"] for e in events[:-1]) == reply
    out = events[-1]["result"]
    assert [b["status"] for b in out["blocks"] if b["kind"] == "sentence"] == ["ok", "claim"]
    assert out["counts"] == {"ok": 1, "flagged": 1}


@pytest.mark.parametrize("sentence,status", [
    ("This proves the author's originality [#1].", "claim"),
    ("这证明了作者的原创性 [#1]。", "claim"),
    ("She was the first to propose it [#1].", "claim"),
    ("The code is owned by the lab [#1].", "claim"),
    ("The date is the computer's own clock [#1].", "ok"),
    ("The idea was recorded on 2026-05-03 [#1].", "ok"),
])
def test_sentences_about_what_records_cannot_show_are_flagged(sentence, status):
    from app.services.ai_story import check

    assert check(sentence, {1: "x"})["status"] == status
