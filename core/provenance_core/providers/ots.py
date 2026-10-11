"""Bitcoin anchor via OpenTimestamps (PRD §9).

The manifest bytes are timestamped as a file: the proof (``<id>.json.ots``) starts
from SHA-256(manifest) = the record ID. As the official client does, a random
16-byte nonce is appended and hashed before submission, so calendars only see
SHA-256(record ID ‖ nonce). The commitment goes to several calendars; the proof
stays *pending* until a calendar returns a Bitcoin attestation, and is
*confirmed* only after the block header has been checked (local node, or at least
two agreeing block explorers).

Uses the official ``opentimestamps`` library to build and merge proofs; HTTP goes
through ``httpx``.
"""

from __future__ import annotations

import hashlib
import secrets

import httpx

from ..ots import OtsError, parse_ots
from ..proofs import ProofCheck, verify_btc_proof
from .base import AnchorResult, ProviderRejected, ProviderUnavailable, TimestampProvider
from .explorers import ExplorerHeaderLookup

DEFAULT_CALENDARS = (
    "https://a.pool.opentimestamps.org",
    "https://b.pool.opentimestamps.org",
    "https://a.pool.eternitywall.com",
    "https://ots.btc.catallaxy.com",
)
OTS_HEADERS = {"Accept": "application/vnd.opentimestamps.v1", "User-Agent": "rprov"}
MAX_RESPONSE = 10_000


def _lib():
    try:
        from opentimestamps.calendar import DEFAULT_CALENDAR_WHITELIST
        from opentimestamps.core.notary import PendingAttestation
        from opentimestamps.core.op import OpAppend, OpSHA256
        from opentimestamps.core.serialize import BytesDeserializationContext, BytesSerializationContext
        from opentimestamps.core.timestamp import DetachedTimestampFile, Timestamp
    except ImportError as exc:  # pragma: no cover - depends on installation
        raise RuntimeError("the Bitcoin anchor needs the 'opentimestamps' package (uv sync --extra ots)") from exc
    return {
        "whitelist": DEFAULT_CALENDAR_WHITELIST,
        "Pending": PendingAttestation,
        "OpAppend": OpAppend,
        "OpSHA256": OpSHA256,
        "Des": BytesDeserializationContext,
        "Ser": BytesSerializationContext,
        "DTF": DetachedTimestampFile,
        "Timestamp": Timestamp,
    }


def _walk(stamp):
    yield stamp
    for child in stamp.ops.values():
        yield from _walk(child)


class OtsProvider(TimestampProvider):
    kind = "btc"
    name = "opentimestamps"

    def __init__(
        self,
        calendars=DEFAULT_CALENDARS,
        *,
        min_calendars: int = 2,
        timeout: float = 15.0,
        header_lookup=None,
        transport: httpx.BaseTransport | None = None,
        extra_whitelist: tuple[str, ...] = (),
    ):
        self.calendars = list(calendars)
        self.min_calendars = min_calendars
        self.timeout = timeout
        self.header_lookup = header_lookup if header_lookup is not None else ExplorerHeaderLookup()
        self._transport = transport
        self._extra_whitelist = set(extra_whitelist)

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=self.timeout, transport=self._transport, headers=OTS_HEADERS)

    def _serialize(self, dtf) -> bytes:
        lib = _lib()
        ctx = lib["Ser"]()
        dtf.serialize(ctx)
        return ctx.getbytes()

    def submit(self, record_id: str, manifest_bytes: bytes) -> AnchorResult:
        lib = _lib()
        digest = hashlib.sha256(manifest_bytes).digest()
        if digest.hex() != record_id:
            raise ValueError("manifest bytes do not hash to the record ID")
        dtf = lib["DTF"](lib["OpSHA256"](), lib["Timestamp"](digest))
        nonced = dtf.timestamp.ops.add(lib["OpAppend"](secrets.token_bytes(16)))
        commitment = nonced.ops.add(lib["OpSHA256"]())
        ok, errors = 0, []
        with self._client() as client:
            for url in self.calendars:
                try:
                    resp = client.post(f"{url}/digest", content=commitment.msg)
                    if resp.status_code != 200 or len(resp.content) > MAX_RESPONSE:
                        errors.append(f"{url}: HTTP {resp.status_code}")
                        continue
                    commitment.merge(lib["Timestamp"].deserialize(lib["Des"](resp.content), commitment.msg))
                    ok += 1
                except httpx.HTTPError as exc:
                    errors.append(f"{url}: {type(exc).__name__}")
                except Exception as exc:  # noqa: BLE001 - malformed calendar answer
                    errors.append(f"{url}: bad response ({exc})")
        if ok < self.min_calendars:
            raise ProviderUnavailable(f"only {ok} calendar(s) answered: " + "; ".join(errors))
        return AnchorResult("pending", self._serialize(dtf), None, f"submitted to {ok} calendars")

    def _whitelisted(self, uri: str) -> bool:
        return uri in self._extra_whitelist or uri in _lib()["whitelist"]

    def upgrade(self, proof: bytes) -> AnchorResult:
        lib = _lib()
        try:
            dtf = lib["DTF"].deserialize(lib["Des"](proof))
        except Exception as exc:  # noqa: BLE001
            raise ProviderRejected(f"unreadable .ots proof: {exc}") from None
        record_id = dtf.file_digest.hex()
        # Already has a Bitcoin attestation? Then only the header check is left.
        if not parse_ots(proof).bitcoin:
            reached = False
            with self._client() as client:
                for stamp in list(_walk(dtf.timestamp)):
                    for att in list(stamp.attestations):
                        if not isinstance(att, lib["Pending"]) or not self._whitelisted(att.uri):
                            continue
                        try:
                            resp = client.get(f"{att.uri}/timestamp/{stamp.msg.hex()}")
                        except httpx.HTTPError:
                            continue
                        reached = True
                        if resp.status_code != 200 or len(resp.content) > MAX_RESPONSE:
                            continue  # 404: not in a block yet
                        try:
                            stamp.merge(lib["Timestamp"].deserialize(lib["Des"](resp.content), stamp.msg))
                        except Exception:  # noqa: BLE001
                            continue
            if not reached:
                raise ProviderUnavailable("no calendar reachable")
            proof = self._serialize(dtf)
        check = self.verify(record_id, proof)
        if check.verified:
            return AnchorResult("confirmed", proof, check.time, check.detail)
        if check.state == "invalid":
            raise ProviderRejected(f"{check.code}: {check.detail}")
        return AnchorResult("pending", proof, None, check.detail)

    def verify(self, record_id: str, proof: bytes) -> ProofCheck:
        return verify_btc_proof(record_id, proof, header_lookup=self.header_lookup)


__all__ = ["OtsProvider", "OtsError", "DEFAULT_CALENDARS"]
