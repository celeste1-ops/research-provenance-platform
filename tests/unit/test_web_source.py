"""A `//` comment written between JSX elements is not a comment: React shows it as text on the page
(it was on top of the "Add a step" form and under the save confirmation). Comments there are
written `{/* … */}`."""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent.parent / "web" / "src"


def test_no_slash_comment_is_shown_as_text():
    hits = []
    for f in sorted(WEB.rglob("*.tsx")):
        lines = f.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if not re.match(r"\s*//", line):
                continue
            before = next((x.rstrip() for x in reversed(lines[:i]) if x.strip()), "")
            after = next((x.strip() for x in lines[i + 1:] if x.strip()), "")
            if before.endswith((">", ")}")) and after.startswith("<"):
                hits.append(f"{f.relative_to(WEB)}:{i + 1}: {line.strip()}")
    assert hits == []
