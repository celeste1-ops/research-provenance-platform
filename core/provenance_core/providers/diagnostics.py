"""“Check stamp services”: can this computer reach the services date stamps come from?
(DECISIONS D-045.) Useful where some of them are blocked or slow, for example in China.

Nothing about the author's work is sent. Each time-stamping authority gets a real
request for a random value (the answer is fully checked, like a real stamp); each
OpenTimestamps calendar is asked about a random value it has never seen (any answer
means it is reachable); each block explorer is asked for the current block height.
All checks run at the same time, each with its own time limit.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass

import httpx

from .base import ProviderRejected, ProviderUnavailable, TimestampProvider
from .explorers import PUBLIC_EXPLORERS
from .ots import DEFAULT_CALENDARS, OTS_HEADERS


@dataclass
class ServiceCheck:
    group: str  # "tsa" (date stamp), "calendar" (Bitcoin stamp), "explorer" (Bitcoin check)
    name: str
    url: str
    ok: bool
    ms: int | None
    detail: str

    def to_dict(self) -> dict:
        return asdict(self)


def _elapsed(start: float) -> int:
    return round((time.monotonic() - start) * 1000)


def check_tsa(label: str, provider: TimestampProvider) -> ServiceCheck:
    url = getattr(provider, "url", "")
    manifest = b"rprov connectivity check " + secrets.token_bytes(16)
    start = time.monotonic()
    try:
        provider.submit(hashlib.sha256(manifest).hexdigest(), manifest)
    except ProviderUnavailable as exc:
        return ServiceCheck("tsa", label, url, False, None, f"not reachable ({_short(exc)})")
    except ProviderRejected as exc:
        return ServiceCheck("tsa", label, url, False, _elapsed(start), f"answered, but the stamp did not check out ({_short(exc)})")
    return ServiceCheck("tsa", label, url, True, _elapsed(start), "stamp received and checked")


def check_calendar(url: str, client: httpx.Client) -> ServiceCheck:
    name = url.removeprefix("https://")
    start = time.monotonic()
    try:
        resp = client.get(f"{url}/timestamp/{secrets.token_hex(32)}", headers=OTS_HEADERS)
    except httpx.HTTPError as exc:
        return ServiceCheck("calendar", name, url, False, None, f"not reachable ({type(exc).__name__})")
    if resp.status_code in (200, 404):  # 404: “never seen this value” — it answered
        return ServiceCheck("calendar", name, url, True, _elapsed(start), "answered")
    return ServiceCheck("calendar", name, url, False, _elapsed(start), f"HTTP {resp.status_code}")


def check_explorer(name: str, base: str, client: httpx.Client) -> ServiceCheck:
    start = time.monotonic()
    try:
        resp = client.get(f"{base}/blocks/tip/height")
    except httpx.HTTPError as exc:
        return ServiceCheck("explorer", name, base, False, None, f"not reachable ({type(exc).__name__})")
    text = resp.text.strip()
    if resp.status_code == 200 and text.isdigit():
        return ServiceCheck("explorer", name, base, True, _elapsed(start), f"current block {int(text):,}")
    return ServiceCheck("explorer", name, base, False, _elapsed(start), f"HTTP {resp.status_code}")


def _short(exc: Exception, limit: int = 140) -> str:
    text = str(exc)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def run_checks(
    tsas: list[tuple[str, TimestampProvider]],
    *,
    calendars=DEFAULT_CALENDARS,
    explorers=PUBLIC_EXPLORERS,
    timeout: float = 15.0,
    transport: httpx.BaseTransport | None = None,
) -> list[ServiceCheck]:
    """All checks in parallel; results in a fixed order (authorities, calendars, explorers)."""
    with httpx.Client(timeout=timeout, transport=transport, headers={"User-Agent": "rprov"}) as client:
        jobs = [lambda label=label, p=p: check_tsa(label, p) for label, p in tsas]
        jobs += [lambda url=url: check_calendar(url, client) for url in calendars]
        jobs += [lambda name=name, base=base: check_explorer(name, base, client) for name, base in explorers]
        with ThreadPoolExecutor(max_workers=max(1, len(jobs))) as pool:
            return list(pool.map(lambda job: job(), jobs))
