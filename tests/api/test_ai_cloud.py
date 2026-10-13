"""D-061 over the API: an online AI service gets nothing until the author has connected it, looked at
exactly what will be sent and clicked Send; then only that text goes, and it is written to the log."""

from __future__ import annotations

import json

import httpx
import pytest

from app import preferences
from app.services import ai_cloud
from provenance_core.providers.cloud_ai import CloudModel

SECRET_BODY = "The unpublished derivation: dv/dt = k (1 - v)^1.3"
SECRET_FILE = b"raw measurements 0.12 0.15 0.19"


@pytest.fixture
def service(monkeypatch):
    """A stand-in for DeepSeek: what it was asked, and a short answer naming step #1."""
    seen: list[httpx.Request] = []
    state = {"status": 200}

    def handle(request):
        seen.append(request)
        if state["status"] != 200:
            return httpx.Response(state["status"], text="no")
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "deepseek-chat"}]})
        pieces = ["## Where it began\n", "- It began with an idea [#1]."]
        sse = "".join(f"data: {json.dumps({'choices': [{'delta': {'content': p}}]})}\n\n" for p in pieces)
        return httpx.Response(200, text=sse + "data: [DONE]\n\n", headers={"Content-Type": "text/event-stream"})

    monkeypatch.setattr(ai_cloud, "model_factory", lambda provider, key, model="", url="": CloudModel(
        provider, key, model, url, transport=httpx.MockTransport(handle)))
    return seen, state


def chats(seen):
    return [r for r in seen if r.url.path.endswith("/chat/completions")]


def test_nothing_is_sent_without_a_connection_and_a_look(api, client, ctx, service):
    seen, state = service
    api.init()
    api.entry("Flow speed levels off", "idea", body=SECRET_BODY, files=[("data.csv", SECRET_FILE)],
              author_statement="the old notebook said so")
    assert client.get("/api/ai").json()["cloud"] == {"connected": False, "model": ""}
    # Before connecting, the text can be looked at — and nothing can be sent.
    look = client.post("/api/ai/cloud/preview", json={"project": api.project_id}).json()
    assert look["connected"] is False and "fingerprint" not in look and "Flow speed levels off" in look["user"]
    assert seen == []
    r = client.post("/api/ai/story", json={"mode": "cloud", "model": "deepseek-chat", "confirm": "x"})
    assert r.status_code == 400 and r.json()["detail"] == "connect an online AI service first"

    # A key the service refuses is not kept.
    state["status"] = 401
    r = client.post("/api/ai/cloud", json={"provider": "deepseek", "key": "sk-wrong-123"},
                    headers={"X-RPROV-Lang": "zh"})
    assert r.status_code == 400 and r.json()["detail"] == "这个 AI 服务不接受这个密钥"
    assert client.get("/api/ai").json()["cloud"]["connected"] is False
    state["status"] = 200
    r = client.post("/api/ai/cloud", json={"provider": "deepseek", "key": "sk-good-123456"})
    assert r.json() == {"connected": True, "provider": "deepseek", "service": "DeepSeek", "host": "api.deepseek.com",
                        "default_model": "deepseek-chat", "models": ["deepseek-chat"]}
    assert chats(seen) == []  # connecting only asked for the list of models

    # The look: the story's sentences — never the step's text or what its file holds (its name is
    # part of the story, and so is shown here).
    preview = client.post("/api/ai/cloud/preview", json={"mode": "cloud", "model": "deepseek-chat",
                                                         "project": api.project_id}).json()
    assert (preview["service"], preview["host"], preview["model"]) == ("DeepSeek", "api.deepseek.com", "deepseek-chat")
    assert "Flow speed levels off" in preview["user"] and "the old notebook said so" in preview["user"]
    assert SECRET_BODY not in preview["user"] + preview["system"]
    assert SECRET_FILE.decode() not in preview["user"] and "data.csv" in preview["user"]
    assert preview["characters"] == len(preview["system"]) + len(preview["user"])

    # Something else than what was shown: nothing goes.
    r = client.post("/api/ai/story", json={"mode": "cloud", "model": "deepseek-chat", "project": api.project_id,
                                           "confirm": "0" * 64})
    assert r.status_code == 409 and chats(seen) == []
    assert ai_cloud.read_log(ctx.settings.data_dir) == {"count": 0, "entries": []}
    api.entry("A second step")  # the story has changed since the look
    r = client.post("/api/ai/story", json={"mode": "cloud", "model": "deepseek-chat", "project": api.project_id,
                                           "confirm": preview["fingerprint"]})
    assert r.status_code == 409 and chats(seen) == []

    # Look again, then send: exactly that text goes, and is in the log first.
    preview = client.post("/api/ai/cloud/preview", json={"model": "deepseek-chat", "project": api.project_id}).json()
    r = client.post("/api/ai/story", json={"mode": "cloud", "model": "deepseek-chat", "project": api.project_id,
                                           "confirm": preview["fingerprint"]})
    events = [json.loads(line) for line in r.text.splitlines()]
    result = events[-1]["result"]
    assert result["service"] == "DeepSeek" and result["model"] == "deepseek-chat"
    assert result["counts"] == {"ok": 1, "flagged": 0}
    [sent] = chats(seen)
    assert sent.url.host == "api.deepseek.com" and sent.headers["authorization"] == "Bearer sk-good-123456"
    assert json.loads(sent.content)["messages"] == [{"role": "system", "content": preview["system"]},
                                                    {"role": "user", "content": preview["user"]}]
    log = ai_cloud.read_log(ctx.settings.data_dir)
    assert log["count"] == 1
    entry = log["entries"][0]
    assert (entry["service"], entry["host"], entry["model"], entry["space"]) == (
        "DeepSeek", "api.deepseek.com", "deepseek-chat", "real")
    assert entry["user"] == preview["user"] and entry["fingerprint"] == preview["fingerprint"]
    assert client.get("/api/ai/cloud/log").json() == log
    assert "sk-good" not in (ctx.settings.data_dir / ai_cloud.LOG).read_text(encoding="utf-8")
    assert preferences.load(ctx.settings.data_dir)["cloud_model"] == "deepseek-chat"
    assert ctx.ledger.record_count() == 3  # genesis and two steps: the summary is not a record

    assert client.delete("/api/ai/cloud").json() == {"connected": False}
    assert ai_cloud.settings(ctx.keystore) is None


def test_an_error_from_the_service_arrives_in_the_language(api, client, service):
    seen, state = service
    api.init()
    api.entry("Idea", "idea")
    client.post("/api/ai/cloud", json={"provider": "deepseek", "key": "sk-good-123456"})
    preview = client.post("/api/ai/cloud/preview", json={"model": "deepseek-chat", "project": api.project_id},
                          headers={"X-RPROV-Lang": "zh"}).json()
    assert "请按上面的几个部分总结" in preview["user"]  # the request is written in the page's language
    state["status"] = 429
    r = client.post("/api/ai/story", json={"mode": "cloud", "model": "deepseek-chat", "project": api.project_id,
                                           "confirm": preview["fingerprint"]}, headers={"X-RPROV-Lang": "zh"})
    assert json.loads(r.text.splitlines()[-1]) == {"error": "这个 AI 服务正忙，或者这个密钥的额度用完了；请稍后再试"}


def test_another_service_needs_an_https_address(api, client, service):
    r = client.post("/api/ai/cloud", json={"provider": "other", "key": "sk-good-123456", "url": "http://10.0.0.5/v1"})
    assert r.status_code == 400 and "https" in r.json()["detail"]
    r = client.post("/api/ai/cloud", json={"provider": "other", "key": "sk-good-123456", "url": "api.example.cn/v1"})
    assert r.status_code == 200 and r.json()["service"] == "api.example.cn"
