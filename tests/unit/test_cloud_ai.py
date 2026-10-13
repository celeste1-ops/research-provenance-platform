"""D-061: an online AI service, reached only with the author's key and only at its own address."""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import httpx2
import pytest

from provenance_core.providers.cloud_ai import CloudAIError, CloudModel, service_url


def collect(model: CloudModel, system: str = "SYS", user: str = "USER") -> str:
    """The whole answer. In a thread of its own: the browser tests leave an event loop running in
    this one (as tests/unit/test_local_ai.py does)."""
    async def run():
        return "".join([p async for p in model.chat_stream(system, user)])

    with ThreadPoolExecutor(1) as pool:
        return pool.submit(asyncio.run, run()).result()


@pytest.mark.parametrize(("url", "expected"), [
    ("https://api.example.com/v1/", "https://api.example.com/v1"),
    ("api.example.com/v1", "https://api.example.com/v1"),
    ("https://api.example.com/v1/chat/completions", "https://api.example.com/v1"),
])
def test_another_service_is_given_by_its_https_address(url, expected):
    assert service_url(url) == expected


@pytest.mark.parametrize("url", ["http://api.example.com/v1", "https://user:pw@api.example.com", "", "ftp://x"])
def test_other_addresses_are_refused(url):
    with pytest.raises(CloudAIError, match="https address"):
        service_url(url)


def test_a_key_is_needed_and_the_service_must_be_known():
    with pytest.raises(CloudAIError, match="API key"):
        CloudModel("deepseek", "  ")
    with pytest.raises(CloudAIError, match="unknown AI service"):
        CloudModel("nowhere", "sk-123456789")


# ---------------------------------------------------------------- Claude, through Anthropic's SDK


def claude(events: list[dict] | None = None, status: int = 200, seen: list | None = None) -> httpx2.MockTransport:
    def handle(request):
        if seen is not None:
            seen.append(request)
        if status != 200:
            return httpx2.Response(status, json={"type": "error", "error": {"type": "x", "message": "no"}})
        if request.url.path == "/v1/models":
            return httpx2.Response(200, json={"data": [
                {"type": "model", "id": i, "display_name": i, "created_at": "2026-01-01T00:00:00Z"}
                for i in ("claude-sonnet-5-5", "claude-opus-5-5")], "has_more": False, "first_id": "a", "last_id": "b"})
        text = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events or [])
        return httpx2.Response(200, text=text, headers={"content-type": "text/event-stream"})

    return httpx2.MockTransport(handle)


def message(pieces: list[str], stop: str = "end_turn") -> list[dict]:
    start = {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5", "content": [],
             "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 0}}
    return [{"type": "message_start", "message": start},
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            *({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": p}} for p in pieces),
            {"type": "content_block_stop", "index": 0},
            {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None}, "usage": {"output_tokens": 3}},
            {"type": "message_stop"}]


def test_claude_lists_models_and_writes_piece_by_piece():
    seen: list = []
    model = CloudModel("anthropic", "sk-ant-test-1", "claude-opus-5-5",
                       sdk_transport=claude(message(["## Start\n", "- An idea [#1]."]), seen=seen))
    assert model.models() == ["claude-opus-5-5", "claude-sonnet-5-5"]
    assert collect(model, "the rules", "the facts") == "## Start\n- An idea [#1]."
    assert {r.url.host for r in seen} == {"api.anthropic.com"}
    assert all(r.headers["x-api-key"] == "sk-ant-test-1" for r in seen)
    body = json.loads(seen[-1].content)
    assert body["system"] == "the rules" and body["messages"] == [{"role": "user", "content": "the facts"}]
    assert body["output_config"] == {"effort": "medium"} and body["fallbacks"] == "default"
    assert seen[-1].headers["anthropic-beta"] == "server-side-fallback-2026-07-01"
    assert (model.service, model.host) == ("Claude (Anthropic)", "api.anthropic.com")


def test_older_claude_models_get_neither_effort_nor_fallbacks():
    seen: list = []
    model = CloudModel("anthropic", "sk-ant-test-1", "claude-haiku-4-5", sdk_transport=claude(message(["Hi"]), seen=seen))
    assert collect(model) == "Hi"
    body = json.loads(seen[-1].content)
    assert "output_config" not in body and "fallbacks" not in body and "anthropic-beta" not in seen[-1].headers


def test_claude_declining_or_a_bad_key_is_said_plainly():
    declined = CloudModel("anthropic", "sk-ant-test-1", "claude-opus-5-5",
                          sdk_transport=claude(message(["Part"], stop="refusal")))
    with pytest.raises(CloudAIError, match="declined"):
        collect(declined)
    bad_key = CloudModel("anthropic", "sk-ant-wrong", "claude-opus-5-5", sdk_transport=claude(status=401))
    with pytest.raises(CloudAIError, match="did not accept the key"):
        bad_key.models()
    with pytest.raises(CloudAIError, match="did not accept the key"):
        collect(bad_key)


def test_the_environment_cannot_redirect_claude_or_supply_a_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://elsewhere.example.org")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-the-environment")
    seen: list = []
    CloudModel("anthropic", "sk-ant-test-1", sdk_transport=claude(seen=seen)).models()
    assert seen[0].url.host == "api.anthropic.com" and seen[0].headers["x-api-key"] == "sk-ant-test-1"


# ---------------------------------------------------------------- the common chat API


def chat_service(reply: list[str] | None = None, status: int = 200, seen: list | None = None) -> httpx.MockTransport:
    def handle(request):
        if seen is not None:
            seen.append(request)
        if status != 200:
            return httpx.Response(status, text="nope")
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "deepseek-chat"}, {"id": "deepseek-reasoner"}]})
        lines = [f"data: {json.dumps({'choices': [{'delta': {'content': p}}]})}\n\n" for p in reply or []]
        keepalive = f"data: {json.dumps({'choices': []})}\n\n"
        return httpx.Response(200, text=keepalive + "".join(lines) + "data: [DONE]\n\n",
                              headers={"Content-Type": "text/event-stream"})

    return httpx.MockTransport(handle)


def test_a_chat_service_lists_models_and_writes_piece_by_piece():
    seen: list = []
    model = CloudModel("deepseek", "sk-ds-1", "deepseek-chat", transport=chat_service(["## 起点\n", "- 想法 [#1]。"], seen=seen))
    assert model.models() == ["deepseek-chat", "deepseek-reasoner"]
    assert collect(model, "规则", "事实") == "## 起点\n- 想法 [#1]。"
    assert [str(r.url) for r in seen] == ["https://api.deepseek.com/models", "https://api.deepseek.com/chat/completions"]
    assert all(r.headers["authorization"] == "Bearer sk-ds-1" for r in seen)
    assert json.loads(seen[-1].content)["messages"] == [{"role": "system", "content": "规则"},
                                                        {"role": "user", "content": "事实"}]


def test_another_chat_service_at_its_own_address():
    seen: list = []
    model = CloudModel("other", "sk-1", "kimi", "https://api.example.cn/v1", transport=chat_service(["ok"], seen=seen))
    assert (model.service, model.host) == ("api.example.cn", "api.example.cn")
    assert collect(model) == "ok" and str(seen[0].url) == "https://api.example.cn/v1/chat/completions"


def test_a_redirect_is_not_followed_with_the_key():
    seen: list = []

    def redirect(request):
        seen.append(request)
        return httpx.Response(302, headers={"Location": "https://elsewhere.example.org/v1/models"})

    with pytest.raises(CloudAIError, match="HTTP 302"):
        CloudModel("qwen", "sk-q-1", transport=httpx.MockTransport(redirect)).models()
    assert len(seen) == 1 and seen[0].url.host == "dashscope.aliyuncs.com"


@pytest.mark.parametrize(("status", "words"), [(401, "did not accept the key"), (404, "does not know this model"),
                                               (429, "busy"), (500, "HTTP 500")])
def test_chat_service_errors_say_what_to_do(status, words):
    model = CloudModel("deepseek", "sk-ds-1", "deepseek-chat", transport=chat_service(status=status))
    with pytest.raises(CloudAIError, match=words):
        collect(model)


def test_no_model_no_request():
    seen: list = []
    with pytest.raises(CloudAIError, match="choose a model"):
        collect(CloudModel("deepseek", "sk-ds-1", "", transport=chat_service(seen=seen)))
    assert seen == []


def test_chatgpt_gets_the_parameter_names_its_newer_models_take():
    seen: list = []
    model = CloudModel("openai", "sk-oa-1", "gpt-5-mini", transport=chat_service(["ok"], seen=seen))
    assert collect(model) == "ok"
    body = json.loads(seen[-1].content)
    assert str(seen[-1].url) == "https://api.openai.com/v1/chat/completions"
    assert body["max_completion_tokens"] == 8000 and "max_tokens" not in body and "temperature" not in body
    assert model.service == "ChatGPT (OpenAI)"


def test_gemini_through_googles_endpoint_for_the_chat_api():
    seen: list = []

    def gemini(request):
        seen.append(request)
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "models/gemini-2.5-flash"}, {"id": "models/embedding-001"}]})
        return chat_service(["ok"]).handle_request(request)

    model = CloudModel("gemini", "AIza-test-1", "gemini-2.5-flash", transport=httpx.MockTransport(gemini))
    assert model.models() == ["embedding-001", "gemini-2.5-flash"]
    assert collect(model) == "ok"
    assert str(seen[-1].url) == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert seen[-1].headers["authorization"] == "Bearer AIza-test-1"


@pytest.mark.parametrize(("provider", "models", "first"), [
    ("openai", ["dall-e-3", "gpt-4o-mini", "gpt-5-mini", "text-embedding-3-small"], "gpt-5-mini"),
    ("openai", ["dall-e-3", "gpt-4o-audio-preview", "gpt-4o-mini", "whisper-1"], "gpt-4o-mini"),
    ("gemini", ["embedding-001", "gemini-3-flash", "imagen-4"], "gemini-3-flash"),
    ("other", ["text-embedding", "kimi-k2"], "kimi-k2"),
    ("deepseek", [], "deepseek-chat"),
])
def test_the_model_offered_first_writes_text(provider, models, first):
    from provenance_core.providers.cloud_ai import pick_model

    assert pick_model(provider, models) == first
