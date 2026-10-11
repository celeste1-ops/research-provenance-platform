"""Browser smoke test of the P0 flow (PRD §3 steps 1–5 and 8):
set up → record → see both time proofs → export → verify.py passes.

Also AC-14 (UI half): author statements and claimed dates never appear in the
"Verified record" section; the two time proofs are shown separately.
"""

from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from tests.e2e.server import LiveServer

pytestmark = pytest.mark.e2e
SNAPSHOT = Path(__file__).resolve().parent / "snapshots" / "ui_detail_sections.json"


def _type_body(page, text: str) -> None:
    page.locator("[data-testid=body-editor] .cm-content").click()
    page.keyboard.type(text)


def _new_record(page, node_type_label: str, title: str, body: str | None = None) -> None:
    page.get_by_test_id("new-record").click()
    form = page.get_by_test_id("record-form")
    form.locator("label.type-chip", has_text=node_type_label).click()
    form.locator("input[name=title]").fill(title)
    if body:
        _type_body(page, body)


def _sections(page) -> dict[str, str]:
    return {
        name: page.get_by_test_id(f"section-{name}").inner_text()
        for name in ("verified", "author", "later")
    }


def test_p0_flow_in_the_browser(tmp_path, browser):
    with LiveServer(tmp_path) as srv:
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(srv.url)

        # 1–2. First start: key + genesis, first project.
        page.get_by_placeholder("Your name or pen name").fill("UI Tester")
        page.get_by_placeholder("e.g. FSF").fill("FSF")
        page.get_by_role("button", name="Create signing key").click()
        page.get_by_test_id("new-record").wait_for()
        assert "Bitcoin anchor: not enabled" not in page.content()  # mock Bitcoin anchor is on here

        # 3–5. Record an idea; both proofs appear separately within a second.
        _new_record(page, "Idea", "First formula", "E = m c^2")
        page.get_by_test_id("submit-record").click()
        detail = page.get_by_test_id("detail")
        detail.wait_for()
        verified = page.get_by_test_id("section-verified")
        verified.locator("[data-proof=tsa]", has_text="Third-party timestamp: verified").wait_for()
        assert "Bitcoin anchor: pending" in verified.inner_text()
        assert "E = m c^2" in verified.inner_text()  # the content itself is part of the verified record

        # A second record with a relation, a "why", a claimed date (import) and milestone.
        _new_record(page, "Claim / hypothesis", "Revised model", "now with friction")
        form = page.get_by_test_id("record-form")
        form.get_by_role("button", name="+ Add relation").click()
        rel_row = form.locator(".group .row").first
        rel_row.locator("select").nth(0).select_option("revises")
        rel_row.locator("select").nth(1).select_option(label="#1 First formula")
        form.locator("textarea").first.fill("the experiment failed, so the hypothesis changed")
        form.get_by_label("Milestone").check()
        form.get_by_label("Importing older material").check()
        form.get_by_placeholder("Claimed date: 2025, 2025-11 or 2025-11-03").fill("2025-11")
        page.get_by_test_id("submit-record").click()
        page.get_by_test_id("section-author").get_by_text("the experiment failed").wait_for()

        s = _sections(page)
        assert "the experiment failed" in s["author"] and "the experiment failed" not in s["verified"]
        assert "2025-11" in s["author"] and "2025-11" not in s["verified"]
        assert "Local clock time" in s["author"] and "Local clock time" not in s["verified"]
        assert "revises" in s["author"] and "revises" not in s["verified"]
        assert s["verified"].count("Third-party timestamp:") == 1 and s["verified"].count("Bitcoin anchor:") == 1
        snapshot = {
            "section_order": [
                h.inner_text().strip()
                for h in page.get_by_test_id("detail").locator("section h3.src-tag").all()
            ],
            "verified_proof_lines": [
                el.get_attribute("data-proof") for el in page.get_by_test_id("section-verified").locator(".proof-line").all()
            ],
            "author_fields": [
                el.get_attribute("data-field") for el in page.get_by_test_id("section-author").locator("li").all()
            ],
        }
        if not SNAPSHOT.exists():
            SNAPSHOT.parent.mkdir(exist_ok=True)
            SNAPSHOT.write_text(json.dumps(snapshot, indent=2) + "\n")
        assert snapshot == json.loads(SNAPSHOT.read_text())

        # Graph: two nodes, one milestone, both proof icons on each node.
        graph = page.get_by_test_id("graph")
        assert graph.locator(".record-node").count() == 2
        assert graph.locator(".record-node.milestone").count() == 1
        assert graph.locator(".record-node [data-proof=tsa][data-state=confirmed]").count() == 2
        assert graph.locator(".record-node [data-proof=btc][data-state=pending]").count() == 2

        # Code reference without archive: the form says the code itself is not saved.
        _new_record(page, "Code", "solver v1")
        form = page.get_by_test_id("record-form")
        form.get_by_placeholder("Repository URL").fill("https://github.com/example/fsf")
        form.get_by_placeholder("Commit hash").fill("0123abcd")
        assert form.get_by_text("External reference, code content not saved").is_visible()
        assert form.get_by_text("Once recorded, this cannot be changed — only added to.").is_visible()
        page.get_by_test_id("submit-record").click()
        page.get_by_test_id("section-verified").get_by_text("External reference, code content not saved").wait_for()

        # 8. Export with preview, then verify the downloaded bundle independently.
        page.get_by_role("button", name="Export…").click()
        dialog = page.get_by_test_id("export-dialog")
        dialog.get_by_test_id("export-warnings").wait_for()
        warnings = dialog.get_by_test_id("export-warnings").inner_text()
        assert "hashes" in warnings and "chain.json" in warnings
        dialog.locator("select").first.select_option("full")
        with page.expect_download() as dl:
            dialog.get_by_test_id("do-export").click()
        zip_path = tmp_path / "exported.zip"
        dl.value.save_as(zip_path)
        out_dir = tmp_path / "unpacked"
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(out_dir)
        res = subprocess.run(
            [sys.executable, "-I", str(out_dir / "verify.py"), str(out_dir),
             "--tsa-root", str(out_dir / "certs" / "mock-tsa-root.pem")],
            capture_output=True, text=True,
        )
        assert res.returncode == 0, res.stdout + res.stderr
        assert "Result: OK" in res.stdout
        page.close()
