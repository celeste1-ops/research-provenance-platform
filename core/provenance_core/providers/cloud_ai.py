"""A language model at an online AI service — optional, and only on the author's word (DECISIONS D-061).

PRD §4 allows an AI company only when the author is asked first. So the app never sends anything
to one on its own: the author connects a service with their own API key, and then, every time,
sees exactly what will be sent and clicks Send (app/services/ai_cloud.py checks that what goes
out is what was shown). What is sent is the story's sentences (app/services/ai_story.py) — never
the text of a step or its files.

Two kinds of service:

* Claude, through Anthropic's own SDK, at api.anthropic.com.
* Services that speak the common chat API (``/chat/completions``): ChatGPT (OpenAI), Gemini
  (Google's endpoint for this API), DeepSeek and Qwen are named here, and any other can be given
  by its https address.

The key is sent only to that service's own address: redirects are not followed, and the SDK is
given the address and the key itself rather than reading them from the environment.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from urllib.parse import urlsplit, urlunsplit

import anthropic
import httpx

PROVIDERS = {
    "anthropic": {"name": "Claude (Anthropic)", "base": "https://api.anthropic.com", "model": "claude-opus-5-5"},
    "openai": {"name": "ChatGPT (OpenAI)", "base": "https://api.openai.com/v1", "model": "gpt-5-mini"},
    "gemini": {"name": "Gemini (Google)", "base": "https://generativelanguage.googleapis.com/v1beta/openai",
               "model": "gemini-2.5-flash"},
    "deepseek": {"name": "DeepSeek", "base": "https://api.deepseek.com", "model": "deepseek-chat"},
    "qwen": {"name": "Qwen (Alibaba Cloud)", "base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
             "model": "qwen-plus"},
    "other": {"name": "", "base": "", "model": ""},  # any other service with the common chat API
}
MAX_TOKENS = 16000  # room for the model's thinking as well as the short summary
TIMEOUT = httpx.Timeout(30.0, read=300.0)
# Claude models that take an effort level, and those that can hand a declined request to another
# model on the server ("fallbacks"); requests to other models leave these out.
_EFFORT_PREFIXES = ("claude-opus-5", "claude-sonnet-5", "claude-fable-5", "claude-haiku-5", "claude-mythos-5")
_FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"
# What a service's model names start with, and models it lists that do not write text (pictures,
# speech, embeddings…), for choosing a model when the usual one is not in its list.
_FAMILY = {"anthropic": "claude-", "openai": "gpt-", "gemini": "gemini-", "deepseek": "deepseek-", "qwen": "qwen"}
_NOT_FOR_TEXT = re.compile(r"embed|audio|tts|image|dall-e|whisper|transcri|realtime|moderation|search|imagen|veo|aqa"
                           r"|rerank|codex", re.I)


class CloudAIError(Exception):
    pass


def pick_model(provider: str, models: list[str]) -> str:
    """The model offered first: the usual one if this key may use it, else one of the service's
    own text models."""
    usual = PROVIDERS[provider]["model"]
    if not models or usual in models:
        return usual
    text = [m for m in models if not _NOT_FOR_TEXT.search(m)] or models
    family = _FAMILY.get(provider, "")
    return next((m for m in text if family and m.startswith(family)), text[0])


def service_url(url: str) -> str:
    """The base address of another service: https only, without a name or password in it."""
    raw = (url or "").strip().rstrip("/")
    parts = urlsplit(raw if "://" in raw else f"https://{raw}")
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise CloudAIError("give the service's https address (for example https://api.example.com/v1)")
    path = parts.path.rstrip("/").removesuffix("/chat/completions")
    return urlunsplit(("https", parts.netloc, path, "", ""))


def _status_error(code: int) -> CloudAIError:
    if code in (401, 403):
        return CloudAIError("the AI service did not accept the key")
    if code == 404:
        return CloudAIError("the AI service does not know this model (or the address is wrong)")
    if code == 429:
        return CloudAIError("the AI service is busy, or the key has used up its limit; try again later")
    return CloudAIError(f"the AI service answered HTTP {code}")


def _sdk_error(exc: anthropic.AnthropicError) -> CloudAIError:
    if isinstance(exc, anthropic.APITimeoutError):
        return CloudAIError("the AI service took too long to answer")
    if isinstance(exc, anthropic.APIConnectionError):
        return CloudAIError("could not reach the AI service (check the internet connection)")
    if isinstance(exc, anthropic.APIStatusError):
        return _status_error(exc.status_code)
    return CloudAIError("the AI service's answer was not readable")


class CloudModel:
    """One service, one key and (for writing) one model: what ai_story.retell_stream needs."""

    def __init__(self, provider: str, key: str, model: str = "", url: str = "", *,
                 transport: httpx.MockTransport | None = None,  # tests answer in place of the service
                 sdk_transport=None):  # the same for Anthropic's SDK (an httpx2 transport)
        if provider not in PROVIDERS:
            raise CloudAIError(f"unknown AI service {provider}")
        if not (key or "").strip():
            raise CloudAIError("paste the API key first")
        self.provider = provider
        self.key = key.strip()
        self.model = model
        self.base = service_url(url) if provider == "other" else PROVIDERS[provider]["base"]
        self.host = urlsplit(self.base).hostname or ""
        self.service = PROVIDERS[provider]["name"] or self.host
        self._transport = transport
        self._sdk_transport = sdk_transport
        self._closers: list = []  # what to close to hang up on the answer being written

    # ------------------------------------------------------------ Claude, through Anthropic's SDK

    def _anthropic(self, asynchronous: bool = False):
        # Redirects are not followed: the key (an x-api-key header) would go along with them.
        extra = {"transport": self._sdk_transport} if self._sdk_transport else {}
        if asynchronous:
            http = anthropic.DefaultAsyncHttpxClient(follow_redirects=False, **extra)
            return anthropic.AsyncAnthropic(api_key=self.key, base_url=self.base, http_client=http)
        http = anthropic.DefaultHttpxClient(follow_redirects=False, **extra)
        return anthropic.Anthropic(api_key=self.key, base_url=self.base, http_client=http)

    def _claude_request(self, system: str, user: str) -> dict:
        body = {"model": self.model, "max_tokens": MAX_TOKENS, "system": system,
                "messages": [{"role": "user", "content": user}]}
        if self.model.startswith(_EFFORT_PREFIXES):
            body["output_config"] = {"effort": "medium"}  # a short summary: no need to think long
        if self.model in _FALLBACK_MODELS:
            body.update(betas=[_FALLBACK_BETA], fallbacks="default")  # a declined request goes to another model
        return body

    async def _claude_stream(self, system: str, user: str) -> AsyncIterator[str]:
        client = self._anthropic(asynchronous=True)
        try:
            async with client.beta.messages.stream(**self._claude_request(system, user)) as stream:
                self._closers.append(stream.close)
                async for text in stream.text_stream:
                    yield text
                final = await stream.get_final_message()
            if final.stop_reason == "refusal":
                raise CloudAIError("the AI service declined to write this summary")
        except anthropic.AnthropicError as exc:
            raise _sdk_error(exc) from None
        finally:
            await client.close()

    # ------------------------------------------------------------ the common chat API

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.key}"}

    async def _compatible_stream(self, system: str, user: str) -> AsyncIterator[str]:
        body = {"model": self.model, "stream": True,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if self.provider == "openai":  # its newer models take only this name, and their own temperature
            body["max_completion_tokens"] = 8000
        else:
            body.update(temperature=0.2, max_tokens=4000)
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, transport=self._transport, follow_redirects=False) as client, \
                    client.stream("POST", f"{self.base}/chat/completions", json=body,
                                  headers=self._headers()) as response:
                self._closers.append(response.aclose)
                if response.status_code != 200:
                    raise _status_error(response.status_code)
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    try:
                        choices = json.loads(data).get("choices") or []
                        piece = choices[0].get("delta", {}).get("content") if choices else None
                    except (ValueError, AttributeError, IndexError, TypeError):
                        raise CloudAIError("the AI service's answer was not readable") from None
                    if piece:
                        yield str(piece)
        except httpx.TimeoutException:
            raise CloudAIError("the AI service took too long to answer") from None
        except httpx.HTTPError:
            raise CloudAIError("could not reach the AI service (check the internet connection)") from None

    # ------------------------------------------------------------ what ai_story uses

    def models(self) -> list[str]:
        """The models this key may use (also checks the key: nothing of the records is sent)."""
        if self.provider == "anthropic":
            try:
                with self._anthropic() as client:
                    return sorted(m.id for m in client.models.list(limit=100))
            except anthropic.AnthropicError as exc:
                raise _sdk_error(exc) from None
        try:
            with httpx.Client(timeout=TIMEOUT, transport=self._transport, follow_redirects=False) as client:
                response = client.get(f"{self.base}/models", headers=self._headers())
        except httpx.TimeoutException:
            raise CloudAIError("the AI service took too long to answer") from None
        except httpx.HTTPError:
            raise CloudAIError("could not reach the AI service (check the internet connection)") from None
        if response.status_code != 200:
            raise _status_error(response.status_code)
        try:
            data = response.json().get("data", [])
            # Gemini lists "models/gemini-…" and is asked for "gemini-…".
            return sorted(str(m["id"]).removeprefix("models/") for m in data if isinstance(m, dict) and m.get("id"))
        except (ValueError, AttributeError):
            raise CloudAIError("the AI service's answer was not readable") from None

    async def chat_stream(self, system: str, user: str) -> AsyncIterator[str]:
        """The answer piece by piece, as the service writes it."""
        if not self.model:
            raise CloudAIError("choose a model first")
        pieces = self._claude_stream(system, user) if self.provider == "anthropic" else \
            self._compatible_stream(system, user)
        try:
            async for piece in pieces:
                yield piece
        finally:
            await pieces.aclose()

    async def hang_up(self) -> bool:
        """Close the connection of the answer being written (the author clicked Stop)."""
        closed = False
        for close in self._closers:
            try:
                await close()
                closed = True
            except Exception:  # already closed or broken: nothing left to close
                pass
        return closed
