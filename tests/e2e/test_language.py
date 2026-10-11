"""D-046: the 中文 / English button switches the whole interface, the choice survives a reload and
is shared with the menu and the report; what the author wrote stays as written."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app import preferences
from app.demo import load_demo
from tests.e2e.server import LiveServer

pytestmark = pytest.mark.e2e
expect = pytest.importorskip("playwright.sync_api").expect

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from i18n_keys import zh_catalog  # noqa: E402

ZH = zh_catalog()


def remembered(srv, page, value: str) -> bool:
    """The language saved for the menu bar / tray menu (saved in the background)."""
    for _ in range(50):
        if preferences.language(srv.ctx.settings.data_dir) == value:
            return True
        page.wait_for_timeout(100)
    return False


def test_switching_language_and_back(tmp_path, browser):
    with LiveServer(tmp_path) as srv:
        ids = load_demo(srv.ctx)
        context = browser.new_context(locale="en-US", viewport={"width": 1500, "height": 950})
        page = context.new_page()
        page.goto(srv.url)
        node = page.get_by_test_id(f"node-{ids['formula1']}")
        node.wait_for()
        expect(page.get_by_test_id("new-record")).to_have_text("+ Add a step")
        title = node.locator(".node-title").text_content()

        page.get_by_test_id("lang-switch").click()
        expect(page.get_by_test_id("new-record")).to_have_text(ZH["+ Add a step"])
        expect(page.locator("html")).to_have_attribute("lang", "zh-CN")
        expect(page.get_by_test_id("lang-switch")).to_have_text("English")
        node = page.get_by_test_id(f"node-{ids['formula1']}")
        node.click()
        verified = page.get_by_test_id("section-verified")
        expect(verified).to_contain_text(ZH["Verified record"])  # the server's words, in Chinese
        expect(node.locator(".node-title")).to_have_text(title)  # the author's title, as written
        assert remembered(srv, page, "zh")

        page.reload()
        expect(page.get_by_test_id("new-record")).to_have_text(ZH["+ Add a step"])
        share = page.get_by_role("button", name=ZH["Share"], exact=True)
        expect(share).to_be_enabled()
        share.click()
        expect(page.get_by_test_id("report-lang")).to_have_value("zh")  # the report follows by default

        # A second browser (nothing chosen there yet) follows the choice made in the first one.
        other = browser.new_context(locale="en-US").new_page()
        other.goto(srv.url)
        expect(other.get_by_test_id("new-record")).to_have_text(ZH["+ Add a step"])
        other.context.close()

        page.goto(srv.url)
        page.get_by_test_id("lang-switch").click()
        expect(page.get_by_test_id("new-record")).to_have_text("+ Add a step")
        expect(page.locator("html")).to_have_attribute("lang", "en")
        assert remembered(srv, page, "en")
        context.close()


def test_first_run_in_a_chinese_browser_starts_in_chinese(tmp_path, browser):
    with LiveServer(tmp_path) as srv:
        context = browser.new_context(locale="zh-CN")
        page = context.new_page()
        page.goto(srv.url)
        expect(page.locator("h1")).to_have_text(ZH["Keep a verifiable history of your research"])
        expect(page.get_by_test_id("lang-switch")).to_have_text("English")
        assert remembered(srv, page, "zh")  # the guess is remembered for the menu bar / tray menu
        context.close()
