"""Which attached files the app may show itself, and how (DECISIONS D-057).

A step can hold files of any kind; they are stored as they are. Most are only ever downloaded
and opened with the program they belong to (PRD S3: an uploaded file is never rendered as a
page). Two kinds are safe to show in place: images, shown through an <img> element (which runs
no script, even in an SVG), and text, shown as text. Everything else — Word, PDF, archives,
HTML — stays download-only.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

IMAGE_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
    ".webp": "image/webp", ".bmp": "image/bmp", ".svg": "image/svg+xml",
}
TEXT_SUFFIXES = {
    ".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".log", ".tex", ".bib", ".py", ".r", ".m", ".jl", ".js", ".ts", ".c", ".h", ".cpp", ".hpp", ".java",
    ".rs", ".go", ".sh", ".sql", ".xml", ".html", ".htm",
}
TEXT_PREVIEW_BYTES = 64 * 1024  # the start of a text file is enough to see what it is
IMAGE_PREVIEW_BYTES = 20 * 1024 * 1024


def preview_kind(name: str) -> str | None:
    """'image', 'text' or None (download only)."""
    suffix = PurePosixPath(name).suffix.lower()
    if suffix in IMAGE_TYPES:
        return "image"
    if suffix in TEXT_SUFFIXES:
        return "text"
    return None


def image_type(name: str) -> str:
    return IMAGE_TYPES[PurePosixPath(name).suffix.lower()]


PREVIEW_CHARS = 280
PREVIEW_LINES = 4
# Markdown marks that would only get in the way in a few lines of plain text.
_MARKS = [
    (re.compile(r"!\[[^\]]*\]\([^)]*\)"), ""),  # images
    (re.compile(r"\[([^\]]*)\]\([^)]*\)"), r"\1"),  # links: keep their text
    (re.compile(r"^\s{0,3}(?:#{1,6}|[-*+]|\d+[.)]|>)\s+", re.M), ""),  # headings, list marks, quotes
    (re.compile(r"^\s*(?:```|~~~).*$", re.M), ""),  # code fences (the code itself stays)
    (re.compile(r"\*\*|__|`"), ""),
]


def plain_preview(text: str, more: bool = False) -> str | None:
    """The first lines of a step's text as plain text (at most four lines and 280 characters),
    ending in "…" when there is more. ``more``: the text given is itself only the start."""
    for pattern, replacement in _MARKS:
        text = pattern.sub(replacement, text)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    lines = [line for line in lines if line]
    short = "\n".join(lines[:PREVIEW_LINES])
    if len(short) > PREVIEW_CHARS:
        short = short[:PREVIEW_CHARS].rstrip()
    if short != "\n".join(lines) or more:
        short += "…"
    return short if short.strip("…") else None


def web_link(ext: dict | None) -> str | None:
    """Where a step's outside reference can be opened: a DOI, a repository, a web address."""
    if not ext:
        return None
    if ext.get("doi"):
        return "https://doi.org/" + re.sub(r"^https?://(dx\.)?doi\.org/", "", ext["doi"], flags=re.I)
    for key in ("repo_url", "url"):
        if re.match(r"^https?://", ext.get(key) or "", re.I):
            return ext[key]
    return None
