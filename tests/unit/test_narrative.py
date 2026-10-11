"""D-048: the research told in sentences from fixed templates. Every sentence names its records
and says whether it is what was recorded or what the author said; nothing is added."""

from __future__ import annotations

import pytest

from app.i18n import language
from app.services.narrative import build_narrative
from app.services.views import Snapshot
from tests.sample import build_log
from tests.unit.test_forbidden_claims import _hits


@pytest.fixture
def story_parts(ctx):
    ids = build_log(ctx)
    snap = Snapshot.load(ctx.ledger, ctx.anchors)
    records = [(r.id, r.seq, r.kind, snap.payloads[r.id]) for r in snap.rows]
    return ids, records, snap


def sentences(n: dict) -> list[dict]:
    return [s for ch in n["chapters"] for para in ch["paragraphs"] for s in para]


def test_every_step_and_addition_is_told_with_its_source(story_parts):
    ids, records, snap = story_parts
    n = build_narrative(records, snap.when, title="FSF")
    text = " ".join(s["text"] for s in sentences(n))
    assert n["steps"] == 5
    assert "the author recorded an idea: “First formula”" in text
    # The author's words are quoted and marked as the author's; relations are the author's too.
    why = next(s for s in sentences(n) if "came from last year" in s["text"])
    assert why["source"] == "author" and why["refs"][0]["id"] == ids["idea"]
    rel = next(s for s in sentences(n) if "new version of “First formula”" in s["text"])
    assert rel["source"] == "author" and {r["id"] for r in rel["refs"]} == {ids["claim"], ids["idea"]}
    claimed = next(s for s in sentences(n) if "2025-11" in s["text"])
    assert claimed["source"] == "author" and "not a verified date" in claimed["text"]
    assert "On" in text and "Parameters were taken from the literature." in text  # later note
    assert "secret draft wording" not in text and "converged after 40 steps" not in text  # never the body
    # Each paragraph's first sentence carries the date to show and whether it is verified.
    first = n["chapters"][0]["paragraphs"][0][0]
    assert first["date"]["verified"] is True and first["refs"][0]["seq"] == 1
    # Parts end at the key steps.
    assert [ch["heading"] for ch in n["chapters"]][:2] == ["Up to “Numerical experiment 1”", "Up to “Preprint”"]


def test_chinese_and_no_forbidden_claims(story_parts):
    _ids, records, snap = story_parts
    with language("zh"):
        n = build_narrative(records, snap.when, title="FSF")
    text = " ".join(s["text"] for s in n["intro"] + sentences(n))
    assert "作者记下了一个想法：“First formula”。" in text
    assert "作者把它标为“First formula”的新版本。" in text
    assert "没有用 AI" in text
    for lang in ("en", "zh"):
        with language(lang):
            n = build_narrative(records, snap.when, title="FSF")
        assert _hits(" ".join(s["text"] for s in n["intro"] + sentences(n))) == []


def test_undisclosed_records_and_month_parts(story_parts):
    ids, records, snap = story_parts
    # As in a bundle: two records disclosed as existence only, and no key steps among the rest.
    hidden = {ids["old"], ids["link"]}
    shown = [(rid, seq, kind, None if rid in hidden else p) for rid, seq, kind, p in records]
    for _rid, _s, kind, p in shown:
        if p is not None and kind == "entry":
            p["milestone"] = False
    n = build_narrative([r for r in shown if r[2] != "milestone"], snap.when, title="t")
    text = " ".join(s["text"] for s in sentences(n))
    assert "Old notebook" not in text and "noticed later" not in text
    assert "Records #4 to #5 are not disclosed here" in text  # neighbours are told together
    assert all(ch["heading"] and len(ch["heading"]) == 7 for ch in n["chapters"])  # YYYY-MM


def test_one_project_only(ctx, story_parts):
    ids, _records, _snap = story_parts
    other = ctx.ledger.create_project("Side project").id
    from app.services.ledger import EntryInput

    ctx.ledger.create_entry(EntryInput(other, "note", "Unrelated note"))
    snap = Snapshot.load(ctx.ledger, ctx.anchors)
    records = [(r.id, r.seq, r.kind, snap.payloads[r.id]) for r in snap.rows]
    project = snap.state.entries[ids["idea"]].project_id
    text = " ".join(s["text"] for s in sentences(build_narrative(records, snap.when, title="FSF",
                                                                 project_id=project)))
    assert "Unrelated note" not in text and "First formula" in text
