"""D-049 in the browser: watch a folder from Settings; a finished new version shows up in the
inbox (already date-stamped); recording it makes a step that keeps that earlier stamp."""

from __future__ import annotations

import pytest

from app.services.inbox import SETTLE_SECONDS
from tests.e2e.server import LiveServer

pytestmark = pytest.mark.e2e
expect = pytest.importorskip("playwright.sync_api").expect


def test_watch_record_and_throw_away(tmp_path, browser):
    folder = tmp_path / "paper"
    folder.mkdir()
    (folder / "intro.md").write_bytes(b"old text\n")
    with LiveServer(tmp_path / "app") as srv:
        srv.ctx.ledger.init_identity("Author")
        srv.ctx.ledger.create_project("FSF")
        clock = [1_000_000.0]
        srv.ctx.inbox._clock = lambda: clock[0]
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(srv.url)
        page.get_by_test_id("settings-menu").click()
        page.get_by_test_id("menu-folders").click()
        dialog = page.get_by_test_id("folder-dialog")
        dialog.get_by_test_id("folder-path").fill(str(folder))
        dialog.get_by_test_id("folder-look").click()
        expect(dialog.get_by_test_id("folder-info")).to_contain_text("1 file to watch")
        dialog.get_by_test_id("folder-start").click()
        expect(dialog.get_by_test_id("folder-paper")).to_be_visible()
        dialog.get_by_role("button", name="Close").click()
        expect(page.get_by_test_id("inbox-pill")).to_have_count(0)  # nothing waiting yet

        (folder / "results.csv").write_bytes(b"t,x\n0,1\n")
        (folder / "scratch.txt").write_bytes(b"junk\n")
        srv.ctx.inbox.scan()
        clock[0] += SETTLE_SECONDS
        assert srv.ctx.inbox.scan() == 2

        page.reload()
        page.get_by_test_id("inbox-pill").click()
        inbox = page.get_by_test_id("inbox-dialog")
        csv = inbox.get_by_test_id("inbox-item-results.csv")
        expect(csv.get_by_test_id("inbox-stamped")).to_be_visible()
        inbox.get_by_test_id("inbox-item-scratch.txt").get_by_test_id("inbox-discard").click()
        expect(inbox.get_by_test_id("inbox-item-scratch.txt")).to_have_count(0)
        csv.get_by_role("textbox").fill("Run 1 results")
        csv.get_by_test_id("inbox-record").click()
        expect(inbox.get_by_test_id("inbox-empty")).to_be_visible()
        inbox.get_by_role("button", name="Close").click()

        expect(page.get_by_test_id("detail").locator("h2")).to_have_text("Run 1 results")
        expect(page.get_by_test_id("file-stamp")).to_contain_text("Date stamp ✓ of the file results.csv")
        expect(page.get_by_test_id("inbox-pill")).to_have_count(0)
        assert srv.ctx.inbox.status()["items"] == []
        page.close()
