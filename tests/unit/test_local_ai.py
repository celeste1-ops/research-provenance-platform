"""D-050: the AI retelling may only talk to a model on this computer, and its answer is checked
sentence by sentence; nothing it writes becomes a record."""

from __future__ import annotations

import json

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
            if seen is not None:
                seen.append(json.loads(request.content))
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
    assert "Retell this research history." in seen[0]["messages"][1]["content"]
    with language("zh"):
        out = retell(story, LocalModel("http://127.0.0.1:11434", "m", transport=fake_server("一句 [#1]。", seen)), "zh")
    assert out["label"] == "AI 推断" and "请讲述这段研究经过" in seen[1]["messages"][1]["content"]
    assert [b["status"] for b in parse("没有来源。有来源【#1】。", {1: "x"})] == ["no_source", "ok"]


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
