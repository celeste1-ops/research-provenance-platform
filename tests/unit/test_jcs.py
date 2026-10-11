"""AC-01 / AC-02: RFC 8785 canonical JSON, floats rejected."""

import json

import pytest
import rfc8785

from provenance_core.jcs import JcsError, canonicalize, is_canonical, parse_json_strict

FIXED_INPUT = {
    "zeta": "最后",
    "alpha": {"nested": {"b": [3, 2, 1], "a": None}, "emoji": "🎉 done", "flag": True},
    "中文键": "研究演化证据",
    "Ünïcödé": "x",
    "escapes": "quote\" backslash\\ newline\n tab\t ctrl\u0001 del\u007f",
    "1": "digit key",
    "big": 9007199254740991,
    "neg": -42,
    "empty": {},
    "list": [],
}

# Reference bytes produced by RFC 8785 (cross-checked with the rfc8785 package below).
EXPECTED = (
    '{"1":"digit key","alpha":{"emoji":"🎉 done","flag":true,"nested":{"a":null,"b":[3,2,1]}},'
    '"big":9007199254740991,"empty":{},'
    '"escapes":"quote\\" backslash\\\\ newline\\n tab\\t ctrl\\u0001 del\u007f",'
    '"list":[],"neg":-42,"zeta":"最后","Ünïcödé":"x","中文键":"研究演化证据"}'
).encode("utf-8")


def test_fixed_input_matches_reference_bytes():
    assert canonicalize(FIXED_INPUT) == EXPECTED
    assert rfc8785.dumps(FIXED_INPUT) == EXPECTED


def test_rfc8785_sorting_example_utf16_order():
    # RFC 8785 §3.2.3: keys sort by UTF-16 code units, so the emoji (D83D…) sorts
    # before U+FB33 although its code point is larger.
    obj = {
        "€": "Euro Sign",
        "\r": "Carriage Return",
        "דּ": "Hebrew Letter Dalet With Dagesh",
        "1": "One",
        "\U0001f600": "Emoji: Grinning Face",
        "\u0080": "Control",
        "ö": "Latin Small Letter O With Diaeresis",
    }
    out = canonicalize(obj).decode("utf-8")
    keys = list(json.loads(out, object_pairs_hook=lambda p: [k for k, _ in p]))
    assert keys == ["\r", "1", "\u0080", "ö", "€", "\U0001f600", "דּ"]
    assert canonicalize(obj) == rfc8785.dumps(obj)


@pytest.mark.parametrize(
    "value",
    [
        {"b": 1, "a": [{"y": "😀", "x": "ä"}]},
        [" ", " ", "\u001f", "</script>"],
        {"deep": {"deeper": {"deepest": ["a", {"k": False}]}}},
    ],
)
def test_matches_rfc8785_package(value):
    assert canonicalize(value) == rfc8785.dumps(value)


def test_floats_rejected():
    with pytest.raises(JcsError):
        canonicalize({"x": 1.5})
    with pytest.raises(JcsError):
        canonicalize({"x": 1.0})
    with pytest.raises(JcsError):
        parse_json_strict(b'{"x":1e3}')


def test_rejects_unsafe_values():
    with pytest.raises(JcsError):
        canonicalize({"x": 2**53})
    with pytest.raises(JcsError):
        canonicalize({"x": "\ud800"})
    with pytest.raises(JcsError):
        canonicalize({1: "non-string key"})
    with pytest.raises(JcsError):
        parse_json_strict(b'{"a":1,"a":2}')
    with pytest.raises(JcsError):
        parse_json_strict(b"\xef\xbb\xbf{}")
    with pytest.raises(JcsError):
        parse_json_strict(b'{"a":NaN}')


def test_is_canonical():
    assert is_canonical(EXPECTED)
    assert not is_canonical(b'{"b":1, "a":2}')
    assert not is_canonical(b'{"b":1,"a":2}')
    assert not is_canonical(b'{"a":-0}')
    assert not is_canonical(b'{"a":"\\u00e9"}')  # must be raw UTF-8, not escaped
