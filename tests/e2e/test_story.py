"""D-048 in the browser: the Story tab tells the research in sentences; each paragraph's tag
opens its step."""

from __future__ import annotations

import pytest

from app.demo import load_demo
from tests.e2e.server import LiveServer

pytestmark = pytest.mark.e2e
expect = pytest.importorskip("playwright.sync_api").expect


def test_story_tab(tmp_path, browser):
    with LiveServer(tmp_path) as srv:
        load_demo(srv.ctx)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(srv.url)
        page.get_by_test_id("graph").locator(".record-node").first.wait_for()
        page.get_by_test_id("tab-story").click()
        story = page.get_by_test_id("story")
        expect(story).to_contain_text("no AI")
        expect(story).to_contain_text("the author recorded an idea: “Intuition: flow speed saturates”")
        assert story.locator(".s-author").count() > 5  # the author's statements are highlighted
        first = page.get_by_test_id("story-ref").first
        expect(first).to_contain_text("#1")
        first.click()
        expect(page.get_by_test_id("detail").locator("h2")).to_have_text("Intuition: flow speed saturates")
        with page.expect_download() as dl:
            page.get_by_test_id("story-markdown").click()
        text = open(dl.value.path(), encoding="utf-8").read()
        assert text.startswith("# FSF") and "[#1 · " in text and "*The author's reason at the time:" in text
        page.close()
