"""Claims PRD §7 rule 5 forbids, in Chinese and English ("原创证明", "认证", "确权",
"保护你的想法" and their equivalents). The tests check every text the app ships; an AI
retelling is checked at run time, sentence by sentence (DECISIONS D-050)."""

from __future__ import annotations

import re

FORBIDDEN = [
    r"原创证明",
    r"认证",
    r"确权",
    r"保护你的想法",
    r"保护您的想法",
    r"proof of originality",
    r"originality proof",
    r"(?<!not )(?<!n't )proves? (?:the )?originality",
    r"proof of authorship",
    r"(?<!not )(?<!n't )proves? (?:the )?authorship",
    r"\bcertif(?:y|ied|ies|ication)\b",
    r"protects? your ideas?",
    r"proof of ownership",
    r"establish(?:es)? ownership",
    r"\bownership\b",
    r"\bauthenticated\b",
]


def forbidden_claims(text: str) -> list[str]:
    return [m.group(0) for pat in FORBIDDEN for m in re.finditer(pat, text, flags=re.IGNORECASE)]
