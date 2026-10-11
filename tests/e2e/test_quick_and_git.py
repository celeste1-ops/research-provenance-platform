"""D-047 in the browser: the quick note box (also opened by the tray menu's "Quick note…") and
recording a git repository from Settings."""

from __future__ import annotations

import pytest

from app.services.gitrepo import find_git
from provenance_core.jcs import parse_json_strict
from tests.e2e.server import LiveServer
from tests.gitutil import GitRepo

pytestmark = pytest.mark.e2e
expect = pytest.importorskip("playwright.sync_api").expect


def entry_payloads(ctx) -> list[dict]:
    return [parse_json_strict(r.payload_bytes) for r in ctx.ledger.records() if r.kind == "entry"]


def test_quick_note_from_the_tray_link(tmp_path, browser):
    with LiveServer(tmp_path) as srv:
        srv.ctx.ledger.init_identity("Author")
        srv.ctx.ledger.create_project("FSF")
        page = browser.new_page()
        page.goto(srv.url + "/#quick-note")  # what the tray menu opens
        box = page.get_by_test_id("quick-note-text")
        expect(box).to_be_focused()
        box.fill("Tried a smaller step size\nIt converged after 40 steps.")
        page.get_by_test_id("quick-note-save").click()
        expect(page.get_by_test_id("notice")).to_contain_text("Saved")
        expect(page.get_by_test_id("quick-note")).to_have_count(0)
        [note] = entry_payloads(srv.ctx)
        assert note["title"] == "Tried a smaller step size" and note["node_type"] == "note"
        assert note["content"]["body"] is not None  # the second line became the text
        assert "#" not in page.url  # a reload does not open the box again

        page.get_by_test_id("quick-note-open").click()  # also from the top bar
        page.get_by_test_id("quick-note-text").fill("One line only")
        page.keyboard.press("Control+Enter")
        expect(page.get_by_test_id("quick-note")).to_have_count(0)
        assert [p["title"] for p in entry_payloads(srv.ctx)] == ["Tried a smaller step size", "One line only"]
        page.close()


@pytest.mark.skipif(find_git() is None, reason="git is not installed")
def test_record_a_repository_from_settings(tmp_path, browser):
    repo = GitRepo(tmp_path / "fsf-code")
    first = repo.commit("Initial model")
    with LiveServer(tmp_path / "app") as srv:
        srv.ctx.ledger.init_identity("Author")
        srv.ctx.ledger.create_project("FSF")
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(srv.url)
        page.get_by_test_id("settings-menu").click()
        page.get_by_test_id("menu-git").click()
        dialog = page.get_by_test_id("git-dialog")
        dialog.get_by_test_id("git-path").fill(str(repo.path))
        dialog.get_by_test_id("git-look").click()
        expect(dialog.get_by_test_id("git-info")).to_contain_text("fsf-code")
        dialog.get_by_test_id("git-start").click()
        expect(dialog.get_by_test_id("git-recorded")).to_have_text("1 step recorded")
        [step] = entry_payloads(srv.ctx)
        assert step["title"] == "Initial model" and step["external"]["commit"] == first

        repo.commit("Fix the boundary term")
        dialog.get_by_test_id("git-check").click()
        expect(dialog.get_by_test_id("git-recorded")).to_have_text("2 steps recorded")
        page.get_by_role("button", name="Close").click()
        expect(page.get_by_test_id("graph")).to_contain_text("Fix the boundary term")
        page.close()
