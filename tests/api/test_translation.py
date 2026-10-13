"""D-066: a step translated by the model on this computer — shown beside the original, never saved."""

from __future__ import annotations

import json

import httpx
import pytest

from app.services import translate
from provenance_core.providers.local_ai import LocalModel


@pytest.fixture
def local_model(monkeypatch):
    """A stand-in for Ollama at 127.0.0.1: what it was asked, and a translation in the asked-for form."""
    seen: list[httpx.Request] = []
    state = {"reply": "<think>Let me see.</think><<TITLE>>\n流速趋于平稳\n<<TEXT>>\n强迫增大时，**流速**不会无限增长。"}

    def handle(request):
        seen.append(request)
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "nomic-embed-text"}, {"id": "qwen3:8b"}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": state["reply"]}}]})

    monkeypatch.setattr(translate, "model_factory", lambda url, model="", **kw: LocalModel(
        url, model, transport=httpx.MockTransport(handle), **kw))
    return seen, state


def test_a_step_is_translated_on_this_computer_and_nothing_is_saved(api, client, ctx, local_model):
    seen, _state = local_model
    api.init()
    rid = api.entry("Flow speed levels off", "idea", body="When the forcing rises, the **flow speed** does not grow.")["id"]
    before = ctx.ledger.record_count()

    r = client.post(f"/api/records/{rid}/translation", json={"lang": "zh"})
    assert r.status_code == 200
    out = r.json()
    assert out["title"] == "流速趋于平稳" and out["text"] == "强迫增大时，**流速**不会无限增长。"
    assert out["model"] == "qwen3:8b"  # the first model that writes text, none being chosen yet
    assert out["lang"] == "zh" and out["shortened"] is False
    assert {r.url.host for r in seen} == {"127.0.0.1"}  # only this computer was asked
    sent = json.loads(seen[-1].content)["messages"]
    assert "Simplified Chinese" in sent[0]["content"]
    assert "Flow speed levels off" in sent[1]["content"] and "does not grow" in sent[1]["content"]
    assert ctx.ledger.record_count() == before  # a translation is never a record
    assert client.get(f"/api/records/{rid}").json()["verified"]["title"] == "Flow speed levels off"


def test_the_model_chosen_for_the_summary_is_used(api, client, ctx, local_model):
    from app import preferences

    seen, state = local_model
    state["reply"] = "Flow speed levels off\nWhen the forcing rises it does not grow."  # the form not kept
    preferences.save(ctx.settings.data_dir, ai_url="http://localhost:1234", ai_model="llama-3.1-8b")
    api.init()
    rid = api.entry("流速趋于平稳", "idea", body="强迫增大时流速不会无限增长。")["id"]
    out = client.post(f"/api/records/{rid}/translation", json={"lang": "en"}).json()
    assert (out["title"], out["text"]) == ("Flow speed levels off", "When the forcing rises it does not grow.")
    assert out["model"] == "llama-3.1-8b" and [r.url.path for r in seen] == ["/v1/chat/completions"]
    assert seen[0].url.port == 1234


def test_no_local_model_is_said_plainly(api, client, monkeypatch):
    def refuse(request):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(translate, "model_factory", lambda url, model="", **kw: LocalModel(
        url, model, transport=httpx.MockTransport(refuse), **kw))
    api.init()
    rid = api.entry("An idea")["id"]
    r = client.post(f"/api/records/{rid}/translation", json={"lang": "zh"}, headers={"X-RPROV-Lang": "zh"})
    assert r.status_code == 400 and r.json()["detail"] == "这个地址上没有本机模型回答（它在运行吗？）"
    assert client.post("/api/records/nope/translation", json={"lang": "zh"}).status_code == 404


def test_only_a_computer_of_its_own_is_asked():
    with pytest.raises(Exception, match="this computer|loopback|127.0.0.1"):
        translate.translate("http://192.168.1.20:11434", "m", "t", "x", "en")
