"""The page starts on a Windows computer whose registry maps .js to text/plain (v0.3.2 stayed
empty there: the browser would not run a script sent as plain text)."""

from __future__ import annotations

import pytest

from app.demo import load_demo
from tests.e2e.server import LiveServer

pytestmark = pytest.mark.e2e
expect = pytest.importorskip("playwright.sync_api").expect


def test_the_page_starts_when_the_system_calls_scripts_plain_text(tmp_path, browser, monkeypatch):
    import starlette.responses

    monkeypatch.setattr(starlette.responses, "guess_type", lambda *a, **k: ("text/plain", None))
    with LiveServer(tmp_path) as srv:
        load_demo(srv.ctx)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.goto(srv.url)
        expect(page.get_by_test_id("steps").locator(".step-card")).to_have_count(14)
        expect(page.get_by_test_id("boot-fallback")).to_have_count(0)  # replaced by the app
        assert not [e for e in errors if "MIME type" in e]
        page.close()


def test_a_page_that_cannot_start_says_what_to_do(tmp_path, browser):
    with LiveServer(tmp_path) as srv:
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.route("**/assets/*.js", lambda route: route.abort())  # the script never arrives
        page.goto(srv.url)
        fallback = page.get_by_test_id("boot-fallback")
        expect(fallback).to_contain_text("退出程序，再重新打开")
        expect(fallback).to_contain_text("Quit the app")
        expect(fallback).to_have_css("opacity", "1", timeout=8000)  # shown after a few seconds
        page.close()
