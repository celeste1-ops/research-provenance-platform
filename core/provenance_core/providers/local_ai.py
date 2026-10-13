"""A language model running on this computer (DECISIONS D-050).

Ollama, LM Studio, llama.cpp's server and others speak the same small chat API
(``/v1/models``, ``/v1/chat/completions``). The app only ever talks to such a server at a
loopback address — 127.0.0.1, ::1 or localhost — so nothing the model is given leaves the
computer. Proxy settings are ignored and redirects are not followed, so a request cannot be
sent anywhere else either.
"""

from __future__ import annotations

import ipaddress
import json
from collections.abc import AsyncIterator
from urllib.parse import urlsplit

import httpx

DEFAULT_URL = "http://127.0.0.1:11434"  # Ollama's usual address; LM Studio uses port 1234
TIMEOUT_SECONDS = 300.0  # a local model can be slow on a laptop; loading it the first time counts too
MAX_TOKENS = 1500  # bounds how long an answer can take: a short summary, not an essay


class LocalAIError(Exception):
    pass


def loopback_url(url: str) -> str:
    """The server's base address, if (and only if) it is on this computer."""
    raw = (url or "").strip().rstrip("/")
    parts = urlsplit(raw if "://" in raw else f"http://{raw}")
    host = (parts.hostname or "").lower()
    try:
        local = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = False
    if parts.scheme not in ("http", "https") or not local or parts.username or parts.password:
        raise LocalAIError("only a model on this computer can be used (an address like http://127.0.0.1:11434)")
    netloc = f"[{host}]" if ":" in host else host
    if parts.port:
        netloc += f":{parts.port}"
    path = parts.path.rstrip("/").removesuffix("/v1")
    return f"{parts.scheme}://{netloc}{path}"


class LocalModel:
    def __init__(self, url: str, model: str = "", *, timeout: float = TIMEOUT_SECONDS,
                 max_tokens: int = MAX_TOKENS,  # a translation (D-066) may be as long as the text
                 transport: httpx.MockTransport | None = None):  # tests answer in place of a server
        self.base = loopback_url(url)
        self.model = model
        self.timeout = timeout
        self.max_tokens = max_tokens
        self._transport = transport
        self._streams: list = []  # connections of the answer being streamed, for hang_up()

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=self.base, timeout=self.timeout, transport=self._transport, trust_env=False,
                            follow_redirects=False)

    def _call(self, method: str, path: str, **kwargs) -> dict:
        try:
            with self._client() as client:
                response = client.request(method, path, **kwargs)
        except httpx.TimeoutException:
            raise LocalAIError("the local model took too long to answer") from None
        except httpx.HTTPError:
            raise LocalAIError("no local model answered at this address (is it running?)") from None
        if response.status_code != 200:
            raise LocalAIError(f"the local model answered HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError:
            raise LocalAIError("the local model's answer was not readable") from None

    def models(self) -> list[str]:
        data = self._call("GET", "/v1/models")
        return sorted(str(m["id"]) for m in data.get("data", []) if isinstance(m, dict) and m.get("id"))

    def _request(self, system: str, user: str, stream: bool) -> dict:
        if not self.model:
            raise LocalAIError("choose a model first")
        return {
            "model": self.model, "stream": stream, "temperature": 0.2, "max_tokens": self.max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }

    def chat(self, system: str, user: str) -> str:
        data = self._call("POST", "/v1/chat/completions", json=self._request(system, user, False))
        try:
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError):
            raise LocalAIError("the local model's answer was not readable") from None

    async def chat_stream(self, system: str, user: str) -> AsyncIterator[str]:
        """The answer piece by piece, as the model writes it, so the author sees it coming instead
        of waiting minutes for all of it. Closing it closes the connection, and hang_up() ends it
        from outside, even while the model is still loading; either way the server stops writing."""
        body = self._request(system, user, True)

        async def trace(event: str, info: dict) -> None:
            if event == "connection.connect_tcp.complete" and info.get("return_value") is not None:
                self._streams.append(info["return_value"])

        try:
            async with httpx.AsyncClient(base_url=self.base, timeout=self.timeout, transport=self._transport,
                                         trust_env=False, follow_redirects=False) as client, \
                    client.stream("POST", "/v1/chat/completions", json=body,
                                  extensions={"trace": trace}) as response:
                if response.status_code != 200:
                    raise LocalAIError(f"the local model answered HTTP {response.status_code}")
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    try:
                        piece = json.loads(data)["choices"][0].get("delta", {}).get("content")
                    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                        raise LocalAIError("the local model's answer was not readable") from None
                    if piece:
                        yield str(piece)
        except httpx.TimeoutException:
            raise LocalAIError("the local model took too long to answer") from None
        except httpx.HTTPError:
            raise LocalAIError("no local model answered at this address (is it running?)") from None

    async def hang_up(self) -> bool:
        """Close the connection of the answer being streamed, at once: the model stops writing, and
        whatever waits for its next piece gets an error instead. (Cancelling that wait is not
        enough everywhere, and neither is shutting the socket: on Windows the wait can go on and
        the connection stay open.) False when there is no connection to close."""
        closed = False
        for stream in self._streams:
            try:
                await stream.aclose()
                closed = True
            except Exception:  # already closed or broken: nothing left to close
                pass
        return closed
