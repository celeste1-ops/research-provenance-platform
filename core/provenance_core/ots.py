"""Standard-library reader for OpenTimestamps ``.ots`` proofs.

Enough of the format to replay the commitment operations from the file digest to
each attestation and report Bitcoin block heights and the merkle roots they commit
to. Keeps ``verify.py`` free of extra dependencies; the official ``opentimestamps``
package remains an optional cross-check.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

OTS_MAGIC = b"\x00OpenTimestamps\x00\x00Proof\x00\xbf\x89\xe2\xe8\x84\xe8\x92\x94"
OTS_BITCOIN_TAG = bytes.fromhex("0588960d73d71901")
OTS_PENDING_TAG = bytes.fromhex("83dfe30d2ef90c8e")
_OTS_MAX_DEPTH = 1000
_OTS_MAX_ARG = 4096


class OtsError(ValueError):
    """Malformed or unsupported .ots proof."""


@dataclass
class OtsBitcoinAttestation:
    height: int
    msg: bytes  # commitment at the attestation: the block merkle root (internal byte order)

    @property
    def merkle_root_hex(self) -> str:
        """Merkle root as block explorers and bitcoind display it (byte-reversed)."""
        return self.msg[::-1].hex()


@dataclass
class OtsPendingAttestation:
    uri: str
    msg: bytes


@dataclass
class OtsProof:
    file_hash_op: str
    file_digest: bytes
    bitcoin: list[OtsBitcoinAttestation] = field(default_factory=list)
    pending: list[OtsPendingAttestation] = field(default_factory=list)
    other: int = 0


class _OtsReader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def read(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise OtsError("unexpected end of proof")
        out = self.data[self.pos : self.pos + n]
        self.pos += n
        return out

    def varuint(self) -> int:
        value = 0
        shift = 0
        while True:
            b = self.read(1)[0]
            value |= (b & 0x7F) << shift
            if not b & 0x80:
                return value
            shift += 7
            if shift > 63:
                raise OtsError("varuint too long")

    def varbytes(self, limit: int = _OTS_MAX_ARG) -> bytes:
        n = self.varuint()
        if n > limit:
            raise OtsError("argument too long")
        return self.read(n)


def _ots_ripemd160(msg: bytes) -> bytes:
    try:
        return hashlib.new("ripemd160", msg).digest()
    except ValueError as exc:
        raise OtsError("RIPEMD-160 is not available in this Python build") from exc


_OTS_UNARY = {
    0x02: ("sha1", lambda m: hashlib.sha1(m).digest()),
    0x03: ("ripemd160", _ots_ripemd160),
    0x08: ("sha256", lambda m: hashlib.sha256(m).digest()),
    0xF2: ("reverse", lambda m: m[::-1]),
    0xF3: ("hexlify", lambda m: m.hex().encode("ascii")),
}
_OTS_DIGEST_LEN = {"sha1": 20, "ripemd160": 20, "sha256": 32}


def _ots_apply(r: _OtsReader, tag: int, msg: bytes) -> bytes:
    if tag in _OTS_UNARY:
        return _OTS_UNARY[tag][1](msg)
    if tag == 0xF0:
        return msg + r.varbytes()
    if tag == 0xF1:
        return r.varbytes() + msg
    if tag == 0x67:
        raise OtsError("keccak256 operations are not supported")
    raise OtsError(f"unknown operation tag 0x{tag:02x}")


def _ots_attestation(r: _OtsReader, msg: bytes, proof: OtsProof) -> None:
    tag = r.read(8)
    payload = _OtsReader(r.varbytes(8192))
    if tag == OTS_BITCOIN_TAG:
        proof.bitcoin.append(OtsBitcoinAttestation(payload.varuint(), msg))
    elif tag == OTS_PENDING_TAG:
        uri = payload.varbytes(1000)
        try:
            proof.pending.append(OtsPendingAttestation(uri.decode("ascii"), msg))
        except UnicodeDecodeError:
            raise OtsError("pending attestation URI is not ASCII") from None
    else:
        proof.other += 1


def parse_ots(data: bytes) -> OtsProof:
    r = _OtsReader(data)
    if r.read(len(OTS_MAGIC)) != OTS_MAGIC:
        raise OtsError("not an OpenTimestamps proof (bad magic)")
    version = r.varuint()
    if version != 1:
        raise OtsError(f"unsupported proof version {version}")
    op_tag = r.read(1)[0]
    if op_tag not in (0x02, 0x03, 0x08):
        raise OtsError("unsupported file hash operation")
    op_name = _OTS_UNARY[op_tag][0]
    digest = r.read(_OTS_DIGEST_LEN[op_name])
    proof = OtsProof(op_name, digest)

    # Iterative version of Timestamp.deserialize: each frame is a message whose
    # branches are still being read.
    stack: list[bytes] = [digest]
    while stack:
        if len(stack) > _OTS_MAX_DEPTH:
            raise OtsError("proof is nested too deeply")
        msg = stack[-1]
        tag = r.read(1)[0]
        more = tag == 0xFF
        if more:
            tag = r.read(1)[0]
        if tag == 0x00:
            _ots_attestation(r, msg, proof)
            if not more:
                stack.pop()
            continue
        result = _ots_apply(r, tag, msg)
        if not more:
            # Last branch of this frame: replace it by its child.
            stack[-1] = result
        else:
            stack.append(result)
    if r.pos != len(data):
        raise OtsError("trailing bytes after proof")
    return proof
