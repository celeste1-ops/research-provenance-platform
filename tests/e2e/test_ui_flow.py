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

from tests.e2e.server import LiveServer, wait_for_step_count

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


def _save_to_real_record(page) -> str:
    """Saving into the real record asks first and lists what will be saved; returns that summary."""
    page.get_by_test_id("submit-record").click()
    confirm = page.get_by_test_id("confirm-real")
    confirm.wait_for()
    text = confirm.inner_text()
    assert "can't be changed or deleted" in text
    confirm.get_by_role("button", name="Save to my record").click()
    return text


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
        page.get_by_placeholder("Name or pen name").fill("UI Tester")
        page.get_by_placeholder("e.g. FSF").fill("FSF")
        page.get_by_role("button", name="Start").click()
        # Onboarding step 2 offers automatic backup; it can be skipped.
        page.get_by_test_id("backup-setup").wait_for()
        page.get_by_role("button", name="Skip for now").click()
        page.get_by_test_id("empty-state").wait_for()
        wait_for_step_count(page, "0 steps")  # genesis is not a step
        assert page.get_by_test_id("backup-pill").inner_text().strip().endswith("Backup not set up")
        assert "Public stamp (Bitcoin): off" not in page.content()  # mock Bitcoin anchor is on here

        # 3–5. Record an idea; both proofs appear separately within a second.
        _new_record(page, "Idea", "First formula", "E = m c^2")
        # "Go back" returns to the unchanged form; nothing is saved yet.
        page.get_by_test_id("submit-record").click()
        page.get_by_test_id("confirm-real").get_by_role("button", name="Go back").click()
        assert page.get_by_test_id("record-form").locator("input[name=title]").input_value() == "First formula"
        assert srv.ctx.ledger.record_count() == 1
        summary = _save_to_real_record(page)
        assert "First formula" in summary and "E = m c^2" in summary and "Idea" in summary
        detail = page.get_by_test_id("detail")
        detail.wait_for()
        verified = page.get_by_test_id("section-verified")
        verified.locator("[data-proof=tsa]", has_text="Date stamp ✓").wait_for()
        assert "Public stamp: waiting" in verified.inner_text()
        assert "E = m c^2" in verified.inner_text()  # the content itself is part of the verified record

        # Saving without a backup folder says so, with a way to set it up.
        assert "Automatic backup is not set up yet" in page.get_by_test_id("notice").inner_text()

        # Key backup (More menu): password-protected, opens with the password, matches the genesis key.
        page.get_by_test_id("settings-menu").click()
        page.get_by_role("menuitem", name="Back up signing key only…").click()
        kb = page.get_by_test_id("key-backup-dialog")
        kb.get_by_label("Password (at least 8 characters)").fill("correct horse battery")
        kb.get_by_label("Repeat password").fill("correct horse battery")
        with page.expect_download() as key_dl:
            kb.get_by_role("button", name="Download backup").click()
        key_file = tmp_path / "key.pem"
        key_dl.value.save_as(key_file)
        from provenance_core.signing import load_private_key_encrypted, public_key_hex

        key = load_private_key_encrypted(key_file.read_bytes(), "correct horse battery")
        genesis = json.loads(srv.ctx.ledger.records()[0].payload_bytes)
        assert public_key_hex(key.public_key()) == genesis["public_key"]
        assert b"ENCRYPTED" in key_file.read_bytes()

        # A second record with a relation, a "why", a claimed date (import) and milestone.
        _new_record(page, "Hypothesis / claim", "Revised model", "now with friction")
        form = page.get_by_test_id("record-form")
        form.get_by_role("button", name="+ Connect to an earlier step").click()
        rel_row = form.locator(".group .row").first
        rel_row.locator("select").nth(0).select_option("revises")
        rel_row.locator("select").nth(1).select_option(label="#1 First formula")
        form.locator("textarea").first.fill("the experiment failed, so the hypothesis changed")
        form.get_by_label("Mark as a key step").check()
        form.get_by_label("This is older material I'm adding now").check()
        form.get_by_placeholder("Claimed date: 2025, 2025-11 or 2025-11-03").fill("2025-11")
        summary = _save_to_real_record(page)
        assert "Connected to" in summary and "First formula" in summary
        assert "the experiment failed" in summary and "Key step" in summary and "2025-11" in summary
        page.get_by_test_id("section-author").get_by_text("the experiment failed").wait_for()

        page.get_by_test_id("section-verified").locator(".proof-line").nth(1).wait_for()
        page.get_by_test_id("section-author").locator("li[data-field=milestone]").wait_for()
        s = _sections(page)
        assert "the experiment failed" in s["author"] and "the experiment failed" not in s["verified"]
        assert "2025-11" in s["author"] and "2025-11" not in s["verified"]
        assert "Local clock time" in s["author"] and "Local clock time" not in s["verified"]
        assert "revises" in s["author"] and "revises" not in s["verified"]
        assert s["verified"].count("Date stamp") == 1 and s["verified"].count("Public stamp") == 1
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
        graph.locator(".record-node").nth(1).wait_for()
        graph.locator(".record-node [data-proof=tsa][data-state=confirmed]").nth(1).wait_for()
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
        assert form.get_by_text("Saved steps can't be edited later").is_visible()
        assert "0123abcd" in _save_to_real_record(page)
        page.get_by_test_id("section-verified").get_by_text("External reference, code content not saved").wait_for()

        # 8. Export with preview, then verify the downloaded bundle independently.
        wait_for_step_count(page, "3 steps")
        page.get_by_role("button", name="Share", exact=True).click()
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
