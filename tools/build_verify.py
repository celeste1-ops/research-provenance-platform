"""Generate the single-file ``verify.py`` from the core library (PRD §10, §13).

The verification logic is written once, in ``provenance_core``; this script
concatenates the modules it needs into one readable file that depends only on
the standard library, ``cryptography`` and ``rfc3161-client``. The FreeTSA root
certificate is embedded as text, so the trust anchor travels with the verifier,
not with the (untrusted) bundle.

    uv run python tools/build_verify.py --out dist/verify.py
"""

from __future__ import annotations

import argparse
import ast
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "core" / "provenance_core"

# Dependency order matters: each module may only use names defined above it.
MODULES = ["der", "jcs", "ots", "proofs", "records", "signing", "chain", "verify", "bundle", "verify_cli"]

ALLOWED_IMPORTS = {
    "__future__", "argparse", "collections", "dataclasses", "datetime", "hashlib", "json", "posixpath",
    "re", "secrets", "sys", "typing", "unicodedata", "uuid", "zipfile", "pathlib", "abc",
    "cryptography", "rfc3161_client",
}

HEADER = '''#!/usr/bin/env python3
"""verify.py — independent checker for rprov evidence bundles (format rprov.bundle/1).

Generated from the provenance_core library by tools/build_verify.py; do not edit by hand.
Requires Python 3.12+ and:  pip install "cryptography>=44" "rfc3161-client>=1.0.6"

    python3 verify.py <bundle directory or .zip>        # human-readable report
    python3 verify.py <bundle> --json                   # machine-readable

Checks every record: content hashes (V1), manifest/payload hashes and canonical
form (V2), Ed25519 signature (V3), third-party RFC 3161 timestamp against the
built-in FreeTSA root (V4), Bitcoin anchor (V5, OpenTimestamps), log chain (V6),
references (V7). The two kinds of time are always reported separately.
Exit code: 0 = nothing failed, 1 = at least one failure, 2 = unreadable bundle.
"""
'''


def _strip_module(name: str, source: str) -> str:
    tree = ast.parse(source)
    drop: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.level > 0 or node.module == "__future__"):
            drop.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for m in mods:
                if m.split(".")[0] not in ALLOWED_IMPORTS:
                    raise SystemExit(f"{name}.py imports {m!r}, which verify.py may not depend on")
    lines = source.splitlines()
    kept = [line for i, line in enumerate(lines, start=1) if i not in drop]
    return "\n".join(kept).strip() + "\n"


def _top_level_names(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
    return names


def _certs_block() -> str:
    root_pem = (CORE / "certs" / "freetsa-cacert.pem").read_text().strip()
    from provenance_core.certs import FREETSA_ROOT_SHA256

    return f'''
# ---------------------------------------------------------------- built-in trust anchor
# FreeTSA Root CA (SHA-256 fingerprint {FREETSA_ROOT_SHA256}).
# Embedded here so the trust decision does not depend on files inside the bundle.
FREETSA_ROOT_SHA256 = "{FREETSA_ROOT_SHA256}"
_FREETSA_ROOT_PEM = b"""{root_pem}
"""


def builtin_tsa_roots():
    cert = x509.load_pem_x509_certificate(_FREETSA_ROOT_PEM)
    assert cert.fingerprint(hashes.SHA256()).hex() == FREETSA_ROOT_SHA256
    return [cert]
'''


def build_verify_source() -> str:
    parts = [HEADER, "from __future__ import annotations\n"]
    seen: dict[str, str] = {}
    for mod in MODULES:
        src = (CORE / f"{mod}.py").read_text(encoding="utf-8")
        body = _strip_module(mod, src)
        for n in _top_level_names(body):
            if n in seen and n not in ("__all__",):
                raise SystemExit(f"name {n!r} is defined in both {seen[n]}.py and {mod}.py")
            seen[n] = mod
        if mod == "bundle":
            parts.append(_certs_block())
        parts.append(f"\n# {'=' * 70}\n# provenance_core/{mod}.py\n# {'=' * 70}\n")
        parts.append(body)
    parts.append('\nif __name__ == "__main__":\n    sys.exit(main())\n')
    text = "\n".join(parts)
    compile(text, "verify.py", "exec")
    return text


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "dist" / "verify.py"))
    args = parser.parse_args()
    text = build_verify_source()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    out.chmod(0o755)
    print(f"wrote {out} ({len(text.splitlines())} lines, sha256 {hashlib.sha256(text.encode()).hexdigest()[:16]})")


if __name__ == "__main__":
    main()
