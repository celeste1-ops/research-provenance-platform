"""RFC 8785 JSON Canonicalization Scheme (JCS), restricted to the rprov data model.

The record format forbids floating-point numbers (PRD §8), so the only numbers that
can appear are integers. That removes the hard part of JCS (ECMAScript number
formatting); what remains is: no insignificant whitespace, object keys sorted by
their UTF-16 code units, the ECMAScript string escaping rules, UTF-8 output.

Integers are limited to the IEEE-754 "safe" range (|n| <= 2**53 - 1) so every JCS
implementation, including JavaScript ones, produces the same bytes.
"""

from __future__ import annotations

import json
from typing import Any

JCS_MAX_SAFE_INT = 2**53 - 1


class JcsError(ValueError):
    """The value cannot be represented in canonical rprov JSON."""


_JCS_ESCAPES = {
    0x08: "\\b",
    0x09: "\\t",
    0x0A: "\\n",
    0x0C: "\\f",
    0x0D: "\\r",
    0x22: '\\"',
    0x5C: "\\\\",
}


def _jcs_string(value: str) -> str:
    out = ['"']
    for ch in value:
        cp = ord(ch)
        if 0xD800 <= cp <= 0xDFFF:
            raise JcsError("strings must be well-formed Unicode (lone surrogate found)")
        esc = _JCS_ESCAPES.get(cp)
        if esc is not None:
            out.append(esc)
        elif cp < 0x20:
            out.append(f"\\u{cp:04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _jcs_utf16_key(key: str) -> bytes:
    # Big-endian UTF-16 bytes compare in the same order as UTF-16 code units.
    return key.encode("utf-16-be", "surrogatepass")


def _jcs_write(value: Any, out: list[str]) -> None:
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, int):
        if abs(value) > JCS_MAX_SAFE_INT:
            raise JcsError(f"integer {value} is outside the safe range ±(2**53-1)")
        out.append(str(int(value)))
    elif isinstance(value, float):
        raise JcsError("floating-point numbers are not allowed in records")
    elif isinstance(value, str):
        out.append(_jcs_string(value))
    elif isinstance(value, (list, tuple)):
        out.append("[")
        for i, item in enumerate(value):
            if i:
                out.append(",")
            _jcs_write(item, out)
        out.append("]")
    elif isinstance(value, dict):
        for key in value:
            if not isinstance(key, str):
                raise JcsError("object keys must be strings")
        out.append("{")
        for i, key in enumerate(sorted(value, key=_jcs_utf16_key)):
            if i:
                out.append(",")
            out.append(_jcs_string(key))
            out.append(":")
            _jcs_write(value[key], out)
        out.append("}")
    else:
        raise JcsError(f"type {type(value).__name__} is not allowed in records")


def canonicalize(value: Any) -> bytes:
    """Return the RFC 8785 canonical UTF-8 bytes of ``value``."""
    out: list[str] = []
    _jcs_write(value, out)
    return "".join(out).encode("utf-8")


def _jcs_reject_float(text: str) -> Any:
    raise JcsError(f"floating-point number {text!r} is not allowed in records")


def _jcs_reject_constant(text: str) -> Any:
    raise JcsError(f"{text} is not valid JSON")


def _jcs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, val in pairs:
        if key in result:
            raise JcsError(f"duplicate object key {key!r}")
        result[key] = val
    return result


def parse_json_strict(data: bytes) -> Any:
    """Parse UTF-8 JSON, rejecting floats, NaN/Infinity, duplicate keys and bad UTF-8."""
    if data.startswith(b"\xef\xbb\xbf"):
        raise JcsError("byte order mark is not allowed")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise JcsError(f"not valid UTF-8: {exc}") from None
    try:
        return json.loads(
            text,
            parse_float=_jcs_reject_float,
            parse_constant=_jcs_reject_constant,
            object_pairs_hook=_jcs_no_duplicates,
        )
    except json.JSONDecodeError as exc:
        raise JcsError(f"not valid JSON: {exc}") from None


def is_canonical(data: bytes) -> bool:
    """True if ``data`` is exactly the JCS form of the JSON value it encodes."""
    try:
        return canonicalize(parse_json_strict(data)) == data
    except JcsError:
        return False
