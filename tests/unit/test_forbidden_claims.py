"""AC-23: UI text, report templates, README and generated reports never use the
claims PRD §7 rule 5 forbids ("原创证明", "认证", "确权", "保护你的想法" and their
English equivalents). Allowed: existed no later than, not changed since, order,
signed by the same key."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

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


def _scanned_files() -> list[Path]:
    files = [ROOT / "README.md"]
    files += sorted((ROOT / "web" / "src").rglob("*.ts*"))
    files += sorted((ROOT / "app" / "report").rglob("*"))
    files += [ROOT / "web" / "index.html", ROOT / "app" / "services" / "views.py",
              ROOT / "core" / "provenance_core" / "verify_cli.py"]
    return [f for f in files if f.is_file() and f.suffix in {".md", ".ts", ".tsx", ".html", ".j2", ".py", ".css"}]


def _hits(text: str) -> list[str]:
    return [m.group(0) for pat in FORBIDDEN for m in re.finditer(pat, text, flags=re.IGNORECASE)]


def test_no_forbidden_claims_in_sources():
    files = _scanned_files()
    assert any(f.name == "README.md" for f in files)
    assert any(f.suffix == ".tsx" for f in files)
    assert any(f.name == "report.html.j2" for f in files)
    problems = {str(f.relative_to(ROOT)): _hits(f.read_text(encoding="utf-8")) for f in files}
    assert {k: v for k, v in problems.items() if v} == {}


def test_no_forbidden_claims_in_generated_report(tmp_path):
    from tests.sample import make_sample

    s = make_sample(tmp_path)
    for name in ("report.html", "VERIFY.md"):
        assert _hits(s.files[name].decode()) == [], name


def test_scanner_catches_examples():
    assert _hits("This is a proof of originality.")
    assert _hits("经过认证的记录")
    assert _hits("Certified timestamp")
    assert not _hits("certificate chain to the FreeTSA root")
    assert _hits("It proves authorship.")
    # The required disclaimers stay allowed.
    assert not _hits("This record does not prove authorship or originality.")
    assert not _hits("It does not prove authorship, priority, motives or correctness.")
