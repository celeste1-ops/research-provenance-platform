"""Bitcoin block headers for checking Bitcoin anchors (PRD §9).

Full verification needs a Bitcoin node (a pruned node is enough). Without one, the
header is taken from at least two public block explorers that must agree, and the
result says "checked via block explorers". Only block heights are sent.

Standard library only (urllib), so the same code runs inside verify.py.
"""

from __future__ import annotations

import base64
import json
import urllib.request
from collections.abc import Callable

PUBLIC_EXPLORERS = (
    ("blockstream.info", "https://blockstream.info/api"),
    ("mempool.space", "https://mempool.space/api"),
)

# fetch(url, data=None, headers=None) -> response body
Fetcher = Callable[..., bytes]


def _urllib_fetch(url: str, data: bytes | None = None, headers: dict | None = None, timeout: float = 15) -> bytes:
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "rprov-verify", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https endpoints
        return resp.read(1_000_000)


class ExplorerHeaderLookup:
    """height -> (merkle_root_hex, block_time) when at least ``quorum`` explorers agree."""

    def __init__(self, explorers=PUBLIC_EXPLORERS, quorum: int = 2, fetch: Fetcher | None = None):
        self.explorers = list(explorers)
        self.quorum = quorum
        self.fetch = fetch or _urllib_fetch
        self.cache: dict[int, tuple[str, int] | None] = {}
        self.last_sources: list[str] = []
        self.method = "checked via block explorers (" + ", ".join(n for n, _ in self.explorers) + ")"

    def _one(self, base: str, height: int) -> tuple[str, int] | None:
        block_hash = self.fetch(f"{base}/block-height/{height}").decode("ascii").strip()
        if len(block_hash) != 64:
            return None
        info = json.loads(self.fetch(f"{base}/block/{block_hash}"))
        if info.get("height") != height:
            return None
        return str(info["merkle_root"]).lower(), int(info["timestamp"])

    def __call__(self, height: int) -> tuple[str, int] | None:
        if height in self.cache:
            return self.cache[height]
        answers: dict[tuple[str, int], list[str]] = {}
        for name, base in self.explorers:
            try:
                got = self._one(base, height)
            except Exception:  # noqa: BLE001 - an unreachable explorer simply does not count
                continue
            if got is not None:
                answers.setdefault(got, []).append(name)
        best = max(answers.items(), key=lambda kv: len(kv[1]), default=None)
        result = None
        if best is not None and len(best[1]) >= self.quorum and len(answers) == 1:
            result = best[0]
            self.last_sources = best[1]
        self.cache[height] = result  # also cache failures: one attempt per height per run
        return result


class NodeHeaderLookup:
    """Block headers from a local Bitcoin node's JSON-RPC (``http://user:pass@127.0.0.1:8332``)."""

    method = "checked against a local Bitcoin node"

    def __init__(self, rpc_url: str, fetch: Fetcher | None = None):
        self.fetch = fetch or _urllib_fetch
        scheme, rest = rpc_url.split("://", 1)
        self.auth = None
        if "@" in rest:
            cred, rest = rest.rsplit("@", 1)
            self.auth = base64.b64encode(cred.encode()).decode()
        self.url = f"{scheme}://{rest}"
        self.cache: dict[int, tuple[str, int] | None] = {}

    def _call(self, method: str, *params):
        headers = {"Content-Type": "application/json"}
        if self.auth:
            headers["Authorization"] = f"Basic {self.auth}"
        body = json.dumps({"jsonrpc": "1.0", "id": "rprov", "method": method, "params": list(params)}).encode()
        data = json.loads(self.fetch(self.url, data=body, headers=headers))
        if data.get("error"):
            raise RuntimeError(data["error"])
        return data["result"]

    def __call__(self, height: int) -> tuple[str, int] | None:
        if height not in self.cache:
            try:
                header = self._call("getblockheader", self._call("getblockhash", height))
                self.cache[height] = (str(header["merkleroot"]).lower(), int(header["time"]))
            except Exception:  # noqa: BLE001
                return None
        return self.cache[height]
