"""Files dragged in from Finder / Explorer: onto the page they open "Add a step" with the files
attached; onto the form they are added wherever they land; nothing ever replaces the app."""

from __future__ import annotations

import pytest

from tests.e2e.server import LiveServer

pytestmark = pytest.mark.e2e
expect = pytest.importorskip("playwright.sync_api").expect

# What the browser hands the page when files are dropped on an element.
DROP = """([selector, names]) => {
  const dt = new DataTransfer();
  for (const name of names) dt.items.add(new File(["data of " + name], name, { type: "text/plain" }));
  const target = document.querySelector(selector);
  for (const type of ["dragenter", "dragover", "drop"]) {
    target.dispatchEvent(new DragEvent(type, { bubbles: true, cancelable: true, dataTransfer: dt }));
  }
}"""


def test_dropping_files_on_the_page_opens_a_step_with_them(tmp_path, browser):
    with LiveServer(tmp_path) as srv:
        srv.ctx.ledger.init_identity("Author")
        srv.ctx.ledger.create_project("FSF")
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(srv.url)
        page.get_by_test_id("backup-pill").wait_for()

        page.evaluate(DROP, [".app", ["results.csv", "draft.txt"]])
        form = page.get_by_test_id("record-form")
        expect(form.locator(".file-list")).to_contain_text("results.csv")
        expect(form.locator(".file-list")).to_contain_text("draft.txt")
        assert page.url.startswith(srv.url)  # the page is still the app

        # Dropped on the form, outside the attachment box, a file is added too.
        page.evaluate(DROP, ["[data-testid=record-form] input[name=title]", ["figure.png"]])
        expect(form.locator(".file-list li")).to_have_count(3)

        form.locator("label.type-chip", has_text="Data").click()
        form.locator("input[name=title]").fill("Dropped files")
        page.get_by_test_id("submit-record").click()
        page.get_by_test_id("confirm-real").get_by_role("button", name="Save to my record").click()
        page.get_by_test_id("detail").wait_for()
        [row] = [r for r in srv.ctx.ledger.records() if r.kind == "entry"]
        names = sorted(f.name for f in srv.ctx.ledger.record_files(row.id))
        assert names == ["draft.txt", "figure.png", "results.csv"]
        page.close()


def test_a_drop_while_another_window_is_open_does_nothing(tmp_path, browser):
    with LiveServer(tmp_path) as srv:
        srv.ctx.ledger.init_identity("Author")
        srv.ctx.ledger.create_project("FSF")
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(srv.url)
        page.get_by_test_id("backup-pill").click()  # the backup window is open
        expect(page.get_by_test_id("backup-dialog")).to_be_visible()
        page.evaluate(DROP, ["body", ["stray.txt"]])
        expect(page.get_by_test_id("record-form")).to_have_count(0)
        assert page.url.startswith(srv.url)
        page.close()
