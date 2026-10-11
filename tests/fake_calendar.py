"""A fake OpenTimestamps calendar (httpx transport) and matching block-header lookup."""

from __future__ import annotations

import httpx
from opentimestamps.core.notary import BitcoinBlockHeaderAttestation, PendingAttestation
from opentimestamps.core.op import OpAppend, OpPrepend, OpSHA256
from opentimestamps.core.serialize import BytesSerializationContext
from opentimestamps.core.timestamp import Timestamp

CAL_URI = "https://alice.btc.calendar.opentimestamps.org"
POOLS = ("https://a.pool.opentimestamps.org", "https://b.pool.opentimestamps.org")


def _ser(stamp: Timestamp) -> bytes:
    ctx = BytesSerializationContext()
    stamp.serialize(ctx)
    return ctx.getbytes()


class FakeCalendar:
    def __init__(self, height: int = 900_000, block_time: int = 1_791_806_400):
        self.received: list[bytes] = []  # every request body/URL seen (privacy checks)
        self.commitments: dict[str, bytes] = {}
        self.confirmed = False
        self.height = height
        self.block_time = block_time
        self.headers: dict[int, tuple[str, int]] = {}
        self.down = False
        self.transport = httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("calendar unreachable")
        self.received.append(str(request.url).encode() + b"\n" + request.content)
        url = str(request.url)
        if request.method == "POST" and url.endswith("/digest"):
            msg = request.content
            stamp = Timestamp(msg)
            leaf = stamp.ops.add(OpAppend(b"fake-calendar")).ops.add(OpSHA256())
            leaf.attestations.add(PendingAttestation(CAL_URI))
            self.commitments[leaf.msg.hex()] = leaf.msg
            return httpx.Response(200, content=_ser(stamp))
        if request.method == "GET" and "/timestamp/" in url:
            commitment_hex = url.rsplit("/", 1)[1]
            if not self.confirmed or commitment_hex not in self.commitments:
                return httpx.Response(404, content=b"Pending confirmation in Bitcoin blockchain")
            # Each commitment lands in its own block (heights count up from self.height).
            order = list(self.commitments).index(commitment_hex)
            height = self.height + order
            stamp = Timestamp(bytes.fromhex(commitment_hex))
            root = stamp.ops.add(OpPrepend(b"\x01" * 32)).ops.add(OpSHA256())
            root.attestations.add(BitcoinBlockHeaderAttestation(height))
            self.headers[height] = (root.msg[::-1].hex(), self.block_time)
            return httpx.Response(200, content=_ser(stamp))
        return httpx.Response(404)

    def header_lookup(self, height: int):
        return self.headers.get(height)

    header_lookup.method = "checked via fake explorers"  # type: ignore[attr-defined]
