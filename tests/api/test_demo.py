"""AC-25: `make demo` loads the FSF sample with the required variety."""

import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from app.demo import load_demo
from provenance_core.records import NODE_TYPES
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


# ---------------------------------------------------------------- the FSF sample research (D-059)


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_the_sample_research_shows_everything_the_app_does(tmp_path, lang):
    from app.demo import load_sample
    from app.services.previews import preview_kind

    ctx = make_ctx(tmp_path)
    info = load_sample(ctx, lang)
    state = ctx.ledger.state()
    kinds = Counter(r.kind for r in ctx.ledger.records())
    entries = list(state.entries.values())
    assert info["lang"] == lang and set(info["projects"]) == {"main", "side"}
    assert kinds["entry"] == 32 and len(ctx.ledger.projects()) == 2
    assert {e.node_type for e in entries} == set(NODE_TYPES)  # every kind of step
    assert {e.rel for e in state.edges} == {"revises", "derived_from", "uses"}
    assert any(e.origin == "link" and e.active for e in state.edges)  # a relation added later
    assert any(not e.active for e in state.edges)  # and one withdrawn
    assert sum(1 for e in entries if e.milestone) == 5 and kinds["milestone"] == 1  # one marked later
    assert kinds["statement"] == 3 and any(r.kind == "statement" and json.loads(r.payload_bytes).get("corrects")
                                           for r in ctx.ledger.records())  # a correction of a statement
    assert kinds["retraction"] == 2
    imports = [e.payload["import"]["level"] for e in entries if e.payload["import"]]
    assert sorted(imports) == ["L1", "L1", "L2"]  # a notebook page, git history, a preprint
    externals = [e.payload["external"] for e in entries if e.payload["external"]]
    assert sum(1 for x in externals if x.get("commit")) == 4 and sum(1 for x in externals if x.get("doi")) == 2
    files = [f for e in entries for f in ctx.ledger.record_files(e.id)]
    shown = Counter(preview_kind(f.name) for f in files)
    assert shown["image"] >= 5 and shown["text"] >= 10 and shown[None] >= 3  # pictures, text, PDF and zips
    assert {f.name.rsplit(".", 1)[-1] for f in files} >= {"png", "svg", "csv", "json", "py", "tex", "bib", "md", "pdf", "zip"}
    assert set(info["ids"]) >= {"intuition", "h1b", "solver21", "fig2", "exp1", "lattice", "preprint"}
    assert all(info["ids"][k] in state.entries for k in ("h1b", "lattice", "setup"))
    from app.services.verification import verify_database

    assert verify_database(ctx.ledger, ctx.anchors).ok
    ctx.close()


def test_the_sample_is_the_same_research_in_both_languages():
    from app.demo import SAMPLE, sample_spec

    def shape(spec):
        out = []
        for s in spec["steps"]:
            files = [f if isinstance(f, str) else f["name"] for f in s.get("files", [])]
            out.append({k: v for k, v in s.items() if k not in ("title", "body", "author_statement", "statement",
                                                                  "text", "reason", "files")} | {"files": files})
        return out

    en, zh = sample_spec("en"), sample_spec("zh")
    assert shape(en) == shape(zh) and set(en["projects"]) == set(zh["projects"])
    assert "fictional" in en["author_label"] and "虚构" in zh["author_label"]
    assert all(e["title"] != z["title"] for e, z in zip(en["steps"], zh["steps"], strict=True) if "title" in e)
    for spec in (en, zh):  # every attached file is there
        for s in spec["steps"]:
            for f in s.get("files", []):
                assert (SAMPLE / "files" / (f if isinstance(f, str) else f["src"])).is_file()


def test_the_sample_files_are_made_by_the_script(tmp_path, monkeypatch):
    """fixtures/fsf_sample/files is exactly what tools/make_fsf_sample.py writes."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("make_fsf_sample", ROOT / "tools" / "make_fsf_sample.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "OUT", tmp_path)
    module.main()
    committed = ROOT / "fixtures" / "fsf_sample" / "files"
    made = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file())
    assert made == sorted(p.relative_to(committed) for p in committed.rglob("*") if p.is_file())
    for rel in made:
        assert (tmp_path / rel).read_bytes() == (committed / rel).read_bytes(), rel
