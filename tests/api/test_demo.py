"""AC-25: `make demo` loads the FSF sample with the required variety."""

import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from app.demo import load_demo
from tests.conftest import make_ctx

ROOT = Path(__file__).resolve().parent.parent.parent


def test_demo_has_required_variety(tmp_path):
    ctx = make_ctx(tmp_path)
    load_demo(ctx)
    rows = ctx.ledger.records()
    state = ctx.ledger.state()
    kinds = Counter(r.kind for r in rows)
    entries = list(state.entries.values())
    assert kinds["entry"] >= 12
    assert len({e.node_type for e in entries}) >= 6
    assert {e.rel for e in state.edges} >= {"revises", "derived_from", "uses"}
    assert sum(1 for e in entries if e.milestone) >= 2
    assert any(e.origin == "link" for e in state.edges)  # a relation added later
    assert kinds["statement"] >= 1
    imports = [e.payload["import"]["level"] for e in entries if e.payload["import"]]
    assert "L1" in imports and "L2" in imports
    assert kinds["retraction"] >= 1 and any(e.retracted_by for e in entries)
    from app.services.verification import verify_database

    assert verify_database(ctx.ledger, ctx.anchors).ok
    with pytest.raises(RuntimeError, match="already contains records"):
        load_demo(ctx)  # never pollutes an existing record
    ctx.close()


def test_make_demo_command(tmp_path):
    env = {**os.environ, "RPROV_HOME": str(tmp_path / "home"), "RPROV_TSA": "mock", "RPROV_BTC": "mock",
           "RPROV_KEYSTORE": "dev-insecure-file"}
    out = subprocess.run([sys.executable, "-m", "app.demo"], cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    assert "Loaded" in out.stdout
    again = subprocess.run([sys.executable, "-m", "app.demo"], cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8")
    assert again.returncode == 1 and "already contains records" in again.stderr
