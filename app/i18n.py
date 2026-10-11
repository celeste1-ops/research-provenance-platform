"""Language of the texts the server writes (DECISIONS D-046).

The interface sends its language with every request (``X-RPROV-Lang``); the middleware puts
it in a context variable, so code anywhere can write ``tr("Verified record")`` and get the
Chinese from ``app/locales/zh.py`` when that is the language in use. The English text is the
key, as in the interface. Error messages raised deep in the code are translated once, where
they leave the server (``tr_message``), by matching them against the catalogue's patterns.

Only the app's own words are translated, never what the author wrote (titles, notes, reasons).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache

from app.locales.zh import ZH

LANGS = ("en", "zh")
_lang: ContextVar[str] = ContextVar("rprov_lang", default="en")
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def normalize(value: str | None) -> str:
    v = (value or "").strip().lower()
    return "zh" if v.startswith("zh") else "en"


def current() -> str:
    return _lang.get()


def set_language(value: str | None):
    return _lang.set(normalize(value))


@contextmanager
def language(value: str | None) -> Iterator[None]:
    token = set_language(value)
    try:
        yield
    finally:
        _lang.reset(token)


def _spaced(s: str) -> str:
    # Chinese next to Latin letters or digits reads better with a space between them.
    s = re.sub(r"([㐀-鿿])([A-Za-z0-9])", r"\1 \2", s)
    return re.sub(r"([A-Za-z0-9%])([㐀-鿿])", r"\1 \2", s)


def _fill(text: str, params: dict) -> str:
    return _PLACEHOLDER.sub(lambda m: str(params[m.group(1)]) if m.group(1) in params else m.group(0), text)


def tr(text: str, **params) -> str:
    """The app's own words in the current language; ``{name}`` placeholders are filled in."""
    if current() == "zh":
        return _spaced(_fill(ZH.get(text, text), params))
    return _fill(text, params)


def device_word(device: str) -> str:
    """'Mac' / 'PC' / 'computer' as the interface says it (Chinese: 'Mac' or '电脑')."""
    if current() == "zh":
        return {"Mac": "Mac"}.get(device, "电脑")
    return device


@lru_cache(maxsize=1)
def _patterns() -> list[tuple[re.Pattern, str]]:
    out = []
    for key, value in ZH.items():
        if "{" not in key:
            continue
        parts = _PLACEHOLDER.split(key)
        seen: dict[str, int] = {}
        regex = ""
        for i, part in enumerate(parts):
            if i % 2 == 0:
                regex += re.escape(part)
                continue
            seen[part] = seen.get(part, 0) + 1  # a repeated {value} becomes value, value_2, …
            name = part if seen[part] == 1 else f"{part}_{seen[part]}"
            regex += f"(?P<{name}>.+?)"
        literal = len(_PLACEHOLDER.sub("", key))
        out.append((literal, re.compile(f"^{regex}$", re.S), value))
    # The most specific pattern first: "{label}: not enabled" before "{stamp}: {state}".
    return [(pat, value) for _n, pat, value in sorted(out, key=lambda x: -x[0])]


def tr_message(message: str) -> str:
    """A message already written in English (an error, a check result), in the current language."""
    if current() != "zh" or not message:
        return message
    if message in ZH:
        return _spaced(ZH[message])
    for pattern, value in _patterns():
        m = pattern.match(message)
        if m:
            return _spaced(_fill(value, {k: tr_message(v) for k, v in m.groupdict().items()}))
    return message
