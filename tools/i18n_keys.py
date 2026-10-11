"""List the English keys used in the interface (t(), tx(), tn()) — DECISIONS D-046.

    uv run python tools/i18n_keys.py            # all keys
    uv run python tools/i18n_keys.py --missing  # keys without a Chinese translation
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web" / "src"
_STR = r'"((?:[^"\\\n]|\\.)*)"'
CALL = re.compile(r"\b(?:t|tx)\(\s*" + _STR)
PLURAL = re.compile(r"\btn\([^,]+,\s*" + _STR + r"\s*,\s*" + _STR)
ENTRY = re.compile(r"^\s*" + _STR + r"\s*:\s*" + _STR + r"\s*,?\s*$", re.M)


def _unescape(s: str) -> str:
    return json.loads(f'"{s}"')


def interface_keys(root: Path = WEB) -> dict[str, list[str]]:
    """English key -> files that use it."""
    keys: dict[str, list[str]] = {}
    for f in sorted(root.rglob("*.ts*")):
        if "locales" in f.parts or f.name == "i18n.tsx":
            continue
        text = f.read_text(encoding="utf-8")
        found = [m.group(1) for m in CALL.finditer(text)]
        for m in PLURAL.finditer(text):
            found += [m.group(1), m.group(2)]
        for k in found:
            keys.setdefault(_unescape(k), []).append(str(f.relative_to(root)))
    return keys


def zh_catalog(root: Path = WEB) -> dict[str, str]:
    text = (root / "locales" / "zh.ts").read_text(encoding="utf-8")
    return {_unescape(k): _unescape(v) for k, v in ENTRY.findall(text)}


if __name__ == "__main__":
    keys = interface_keys()
    if "--missing" in sys.argv:
        zh = zh_catalog()
        keys = {k: v for k, v in keys.items() if k not in zh}
    for k in keys:
        print(json.dumps(k, ensure_ascii=False))
    print(f"# {len(keys)} keys", file=sys.stderr)


# ---------------------------------------------------------------- server texts (app/locales/zh.py)

SERVER_DIRS = ("app", "core/provenance_core/providers/diagnostics.py")
_ERROR_CLASSES = {"LedgerError", "BackupError", "PracticeResetError", "HTTPException", "ValueError", "KeyStoreError"}


def _literal(node) -> str | None:
    """A string literal, or an f-string turned into a pattern with {placeholders}."""
    import ast

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out = []
        for part in node.values:
            if isinstance(part, ast.Constant):
                out.append(str(part.value))
            else:
                expr = part.value
                name = expr.id if isinstance(expr, ast.Name) else "value"
                out.append("{" + name + "}")
        return "".join(out)
    return None


def server_keys(root: Path | None = None) -> dict[str, str]:
    """English key -> "tr" (translated where written) or "error" (translated on the way out)."""
    import ast

    root = root or Path(__file__).resolve().parent.parent
    files: list[Path] = []
    for d in SERVER_DIRS:
        path = root / d
        files += [path] if path.is_file() else sorted(path.rglob("*.py"))
    keys: dict[str, str] = {}
    for f in files:
        if "locales" in f.parts:
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "tr" and node.args:
                key = _literal(node.args[0])
                if key:
                    keys.setdefault(key, "tr")
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
                name = getattr(node.exc.func, "id", None) or getattr(node.exc.func, "attr", None)
                if name not in _ERROR_CLASSES:
                    continue
                for arg in node.exc.args:
                    key = _literal(arg)
                    if key and re.search(r"[A-Za-z]{3}", key):
                        keys.setdefault(key, "error")
    return keys
