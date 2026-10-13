"""The FSF sample research (D-059): offered on the first screen, opened in the practice space in
the interface's language, with a tour whose stops open what they talk about."""

from __future__ import annotations

import pytest

from tests.e2e.server import LiveServer

pytestmark = pytest.mark.e2e
expect = pytest.importorskip("playwright.sync_api").expect


def test_the_first_screen_opens_the_sample_with_its_tour(tmp_path, browser):
    with LiveServer(tmp_path) as srv:
        page = browser.new_page(viewport={"width": 1500, "height": 950})
        page.goto(srv.url)
        page.get_by_test_id("setup-sample").click()
        page.get_by_test_id("practice-banner").wait_for()
        tour = page.get_by_test_id("sample-tour")
        expect(tour).to_contain_text("Sample research: FSF (fictional)")
        steps = page.get_by_test_id("steps")
        expect(steps.locator(".step-card")).to_have_count(29)  # the main project
        assert not srv.ctx.ledger.initialized()  # nothing went into the real record

        tour.get_by_test_id("tour-turn").click()  # a step opens, with what the stop says
        expect(page.get_by_test_id("detail")).to_contain_text("Hypothesis H1′")
        expect(tour.get_by_test_id("sample-tour-text")).to_contain_text("H1′ revised it")

        tour.get_by_test_id("tour-withdrawn").click()
        expect(page.get_by_test_id("detail")).to_contain_text("Side idea: a lattice model")
        expect(steps.locator(".step-card.retracted")).to_have_count(2)

        tour.get_by_test_id("tour-files").click()
        expect(page.get_by_test_id("detail").get_by_test_id("file-image")).to_have_count(1)

        tour.get_by_test_id("tour-key").click()
        expect(steps.locator(".step-card")).to_have_count(5)
        assert "Key steps only — 5 of 29." in steps.inner_text()

        tour.get_by_test_id("tour-map").click()
        expect(page.get_by_test_id("graph").locator(".record-node")).to_have_count(29)

        tour.get_by_test_id("tour-story").click()
        expect(page.get_by_test_id("story")).to_contain_text("Hypothesis H1")

        tour.get_by_test_id("tour-share").click()
        expect(page.get_by_test_id("export-dialog")).to_be_visible()
        page.get_by_test_id("export-dialog").get_by_role("button", name="Cancel").click()

        tour.get_by_test_id("tour-projects").click()
        expect(page.get_by_test_id("project-select").locator("option:checked")).to_have_text("Flow channel setup (sample)")
        expect(steps.locator(".step-card")).to_have_count(3)

        tour.get_by_test_id("tour-git").click()  # back to the main project, at the tagged commit
        expect(page.get_by_test_id("detail")).to_contain_text("Fix: adaptive step size (tag v0.2)")

        tour.get_by_test_id("sample-tour-hide").click()  # the tour can be put away, and stays away
        page.reload()
        page.get_by_test_id("sample-tour-show").click()
        expect(page.get_by_test_id("tour-turn")).to_be_visible()
        page.close()


def test_the_sample_comes_in_the_interface_language(tmp_path, browser):
    with LiveServer(tmp_path) as srv:
        page = browser.new_page(viewport={"width": 1500, "height": 950})
        page.goto(srv.url)
        page.get_by_role("button", name="中文").click()
        page.get_by_test_id("setup-sample").click()
        tour = page.get_by_test_id("sample-tour")
        expect(tour).to_contain_text("示例研究：FSF（虚构）")
        expect(page.get_by_test_id("steps").locator(".step-card")).to_have_count(29)
        assert "假设 H1′：指数随驱动强度变化" in page.get_by_test_id("steps").inner_text()
        status = page.evaluate("() => fetch('/api/status', {headers: {'X-RPROV-Space': 'practice'}}).then(r => r.json())")
        assert status["sample"]["lang"] == "zh" and status["author_label"] == "示例作者（虚构）"
        page.close()


def test_an_empty_real_record_points_at_the_sample(tmp_path, browser):
    with LiveServer(tmp_path) as srv:
        srv.ctx.ledger.init_identity("Author")
        srv.ctx.ledger.create_project("My study")
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(srv.url)
        page.get_by_test_id("real-sample").click()
        page.get_by_test_id("practice-banner").wait_for()
        expect(page.get_by_test_id("sample-tour")).to_be_visible()
        assert [p.title for p in srv.ctx.ledger.projects()] == ["My study"]  # the real record is untouched
        page.close()


def practice_installation(page) -> str:
    return page.evaluate("fetch('/api/status', {headers: {'X-RPROV-Space': 'practice'}})"
                         ".then((r) => r.json()).then((s) => s.installation)")


def test_see_the_example_from_settings_never_touches_the_real_record(tmp_path, browser):
    """D-062: "See the example" in Settings, from either space — the sample in practice and its tour
    from the first stop, even after the tour was put away; practice of the author's own is replaced
    only after they say so; the real record keeps every record it had."""
    from app.services.ledger import EntryInput

    with LiveServer(tmp_path) as srv:
        ledger = srv.ctx.ledger
        ledger.init_identity("Author")
        ledger.create_entry(EntryInput(ledger.create_project("FSF").id, "idea", "My own first idea"))
        real = [r.id for r in ledger.records()]
        page = browser.new_page(viewport={"width": 1500, "height": 950})
        page.goto(srv.url)
        page.evaluate("localStorage.setItem('rprov-tour-hidden', '1')")  # put away some time ago
        page.reload()

        page.get_by_test_id("settings-menu").click()
        page.get_by_test_id("menu-example").click()  # from My research
        page.get_by_test_id("practice-banner").wait_for()
        tour = page.get_by_test_id("sample-tour")
        expect(tour.get_by_test_id("tour-steps")).to_have_class("on")  # shown again, at its first stop
        expect(tour.get_by_test_id("sample-tour-text")).to_be_visible()
        expect(page.get_by_test_id("steps").locator(".step-card")).to_have_count(29)
        assert [r.id for r in ledger.records()] == real

        # Practice already holds the sample: straight to the tour, nothing is loaded again.
        installation = practice_installation(page)
        tour.get_by_test_id("tour-map").click()
        page.get_by_test_id("settings-menu").click()
        page.get_by_test_id("menu-example").click()
        expect(tour.get_by_test_id("tour-steps")).to_have_class("on")
        expect(page.get_by_test_id("example-confirm")).to_have_count(0)
        assert practice_installation(page) == installation

        # Practice of the author's own: asked first, from either space.
        page.get_by_test_id("settings-menu").click()
        page.get_by_role("menuitem", name="Start practice over…").click()
        page.get_by_test_id("practice-reset").get_by_role("button", name="Start over").click()
        expect(page.get_by_test_id("sample-tour")).to_have_count(0)
        page.get_by_test_id("quick-note-open").click()
        page.get_by_test_id("quick-note-text").fill("A practice step of my own")
        page.get_by_test_id("quick-note-save").click()
        expect(page.get_by_test_id("steps")).to_contain_text("A practice step of my own")
        page.get_by_test_id("settings-menu").click()
        page.get_by_test_id("menu-example").click()
        confirm = page.get_by_test_id("example-confirm")
        expect(confirm).to_contain_text("This replaces what is in the practice space. Your real record is not touched.")
        confirm.get_by_role("button", name="Cancel").click()
        expect(page.get_by_test_id("steps")).to_contain_text("A practice step of my own")  # left as it was

        page.get_by_test_id("space-real").click()
        page.get_by_test_id("settings-menu").click()
        page.get_by_test_id("menu-example").click()
        page.get_by_test_id("example-confirm-yes").click()
        page.get_by_test_id("practice-banner").wait_for()
        expect(page.get_by_test_id("sample-tour").get_by_test_id("tour-steps")).to_have_class("on")
        expect(page.get_by_test_id("steps").locator(".step-card")).to_have_count(29)
        assert [r.id for r in ledger.records()] == real  # not one record more or less, in the same order
        page.close()
