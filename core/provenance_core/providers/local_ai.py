"""A language model running on this computer (DECISIONS D-050).

Ollama, LM Studio, llama.cpp's server and others speak the same small chat API
(``/v1/models``, ``/v1/chat/completions``). The app only ever talks to such a server at a
loopback address — 127.0.0.1, ::1 or localhost — so nothing the model is given leaves the
computer. Proxy settings are ignored and redirects are not followed, so a request cannot be
sent anywhere else either.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

import httpx

DEFAULT_URL = "http://127.0.0.1:11434"  # Ollama's usual address; LM Studio uses port 1234
TIMEOUT_SECONDS = 300.0  # a local model can be slow on a laptop


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
                 transport: httpx.BaseTransport | None = None):
        self.base = loopback_url(url)
        self.model = model
        self.timeout = timeout
        self._transport = transport

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

    def chat(self, system: str, user: str) -> str:
        if not self.model:
            raise LocalAIError("choose a model first")
        data = self._call("POST", "/v1/chat/completions", json={
            "model": self.model, "stream": False, "temperature": 0.2,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        })
        try:
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError):
            raise LocalAIError("the local model's answer was not readable") from None
