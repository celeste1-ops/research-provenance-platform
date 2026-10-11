"""Minimal ASN.1 DER reader/writer.

Just enough to (a) read the CMS structure inside an RFC 3161 time-stamp token so the
verifier can tell a broken signature apart from an untrusted certificate chain, and
(b) let the deterministic mock TSA produce real RFC 3161 responses for tests.
"""

from __future__ import annotations

from datetime import datetime


class DerError(ValueError):
    """Malformed DER."""


# --------------------------------------------------------------------------- reading


def der_read(data: bytes, offset: int = 0) -> tuple[int, int, int]:
    """Read one TLV at ``offset``. Returns (tag, content_start, end)."""
    if offset + 2 > len(data):
        raise DerError("truncated TLV")
    tag = data[offset]
    if tag & 0x1F == 0x1F:
        raise DerError("high-tag-number form not supported")
    length = data[offset + 1]
    pos = offset + 2
    if length & 0x80:
        n = length & 0x7F
        if n == 0 or n > 4 or pos + n > len(data):
            raise DerError("bad length")
        length = int.from_bytes(data[pos : pos + n], "big")
        pos += n
    end = pos + length
    if end > len(data):
        raise DerError("TLV runs past end of data")
    return tag, pos, end


def der_children(data: bytes, start: int, end: int) -> list[tuple[int, int, int, int]]:
    """Children of a constructed value. Each item is (tag, tlv_start, content_start, end)."""
    items = []
    pos = start
    while pos < end:
        tag, cstart, cend = der_read(data, pos)
        if cend > end:
            raise DerError("child runs past parent")
        items.append((tag, pos, cstart, cend))
        pos = cend
    return items


def der_decode_oid(content: bytes) -> str:
    if not content:
        raise DerError("empty OID")
    parts: list[int] = []
    value = 0
    for b in content:
        value = (value << 7) | (b & 0x7F)
        if not b & 0x80:
            parts.append(value)
            value = 0
    first = parts[0]
    head = [0, first] if first < 40 else ([1, first - 40] if first < 80 else [2, first - 80])
    return ".".join(str(x) for x in head + parts[1:])


def der_decode_int(content: bytes) -> int:
    return int.from_bytes(content, "big", signed=True)


# --------------------------------------------------------------------------- writing


def der_tlv(tag: int, content: bytes) -> bytes:
    n = len(content)
    if n < 0x80:
        head = bytes([tag, n])
    else:
        lb = n.to_bytes((n.bit_length() + 7) // 8, "big")
        head = bytes([tag, 0x80 | len(lb)]) + lb
    return head + content


def der_seq(*items: bytes) -> bytes:
    return der_tlv(0x30, b"".join(items))


def der_set(*items: bytes) -> bytes:
    # DER requires SET OF elements in ascending order of their encodings.
    return der_tlv(0x31, b"".join(sorted(items)))


def der_int(value: int) -> bytes:
    length = max(1, (value.bit_length() + 8) // 8)
    return der_tlv(0x02, value.to_bytes(length, "big", signed=True))


def der_oid(dotted: str) -> bytes:
    nums = [int(x) for x in dotted.split(".")]
    body = [40 * nums[0] + nums[1]] + nums[2:]
    out = bytearray()
    for n in body:
        chunk = [n & 0x7F]
        n >>= 7
        while n:
            chunk.append(0x80 | (n & 0x7F))
            n >>= 7
        out.extend(reversed(chunk))
    return der_tlv(0x06, bytes(out))


def der_octets(value: bytes) -> bytes:
    return der_tlv(0x04, value)


def der_null() -> bytes:
    return b"\x05\x00"


def der_bool(value: bool) -> bytes:
    return der_tlv(0x01, b"\xff" if value else b"\x00")


def der_gentime(dt: datetime) -> bytes:
    return der_tlv(0x18, dt.strftime("%Y%m%d%H%M%SZ").encode("ascii"))


def der_explicit(n: int, content: bytes) -> bytes:
    return der_tlv(0xA0 | n, content)
