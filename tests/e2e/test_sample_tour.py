"""The FSF sample research (D-059, D-064): offered on the first screen, opened in a space of its own
(the example) in the interface's language, with a tour whose stops open what they talk about."""

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
        page.get_by_test_id("example-banner").wait_for()
        expect(page.get_by_test_id("space-example")).to_have_attribute("aria-pressed", "true")
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
        status = page.evaluate("() => fetch('/api/status', {headers: {'X-RPROV-Space': 'example', 'X-RPROV-Lang': 'zh'}}).then(r => r.json())")
        assert status["sample"]["lang"] == "zh" and status["author_label"] == "示例作者（虚构）"
        page.close()


def test_an_empty_real_record_points_at_the_sample(tmp_path, browser):
    with LiveServer(tmp_path) as srv:
        srv.ctx.ledger.init_identity("Author")
        srv.ctx.ledger.create_project("My study")
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(srv.url)
        page.get_by_test_id("real-sample").click()
        page.get_by_test_id("example-banner").wait_for()
        expect(page.get_by_test_id("sample-tour")).to_be_visible()
        assert [p.title for p in srv.ctx.ledger.projects()] == ["My study"]  # the real record is untouched
        page.close()


def installation(page, space: str) -> str:
    return page.evaluate(f"fetch('/api/status', {{headers: {{'X-RPROV-Space': '{space}'}}}})"
                         ".then((r) => r.json()).then((s) => s.installation)")


def test_the_example_is_a_space_of_its_own(tmp_path, browser):
    """D-064: "See the example" opens the sample in its own space, from any space, with its tour from
    the first stop even after the tour was put away. Neither opening it nor loading it afresh changes
    the real record or the author's practice."""
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

        # A practice step of the author's own.
        page.get_by_test_id("space-practice").click()
        page.get_by_test_id("practice-banner").wait_for()
        page.get_by_test_id("quick-note-open").click()
        page.get_by_test_id("quick-note-text").fill("A practice step of my own")
        page.get_by_test_id("quick-note-save").click()
        expect(page.get_by_test_id("steps")).to_contain_text("A practice step of my own")
        practice = installation(page, "practice")

        page.get_by_test_id("space-real").click()
        page.get_by_test_id("settings-menu").click()
        page.get_by_test_id("menu-example").click()  # from My research: straight there, nothing to confirm
        page.get_by_test_id("example-banner").wait_for()
        expect(page.get_by_test_id("practice-banner")).to_have_count(0)
        tour = page.get_by_test_id("sample-tour")
        expect(tour.get_by_test_id("tour-steps")).to_have_class("on")  # shown again, at its first stop
        expect(tour.get_by_test_id("sample-tour-text")).to_be_visible()
        expect(page.get_by_test_id("steps").locator(".step-card")).to_have_count(29)
        assert [r.id for r in ledger.records()] == real

        # Already there: back to the first stop, nothing is loaded again.
        example = installation(page, "example")
        tour.get_by_test_id("tour-map").click()
        page.get_by_test_id("settings-menu").click()
        page.get_by_test_id("menu-example").click()
        expect(tour.get_by_test_id("tour-steps")).to_have_class("on")
        assert installation(page, "example") == example

        # Changed, then loaded afresh: as at the start again, and nothing else is touched.
        page.get_by_test_id("quick-note-open").click()
        page.get_by_test_id("quick-note-text").fill("Trying something in the example")
        page.get_by_test_id("quick-note-save").click()
        expect(page.get_by_test_id("steps").locator(".step-card")).to_have_count(30)
        page.get_by_test_id("settings-menu").click()
        page.get_by_test_id("menu-example-reload").click()
        expect(page.get_by_test_id("notice")).to_contain_text("The example is as it was at the start again.")
        expect(page.get_by_test_id("steps").locator(".step-card")).to_have_count(29)
        expect(page.get_by_test_id("sample-tour").get_by_test_id("tour-steps")).to_have_class("on")
        assert installation(page, "example") != example

        # Practice and the real record are as they were.
        page.get_by_test_id("example-banner").get_by_role("button", name="Back to My research").click()
        expect(page.get_by_test_id("example-banner")).to_have_count(0)
        expect(page.get_by_test_id("steps")).to_contain_text("My own first idea")
        page.get_by_test_id("space-practice").click()
        expect(page.get_by_test_id("steps")).to_contain_text("A practice step of my own")
        expect(page.get_by_test_id("sample-tour")).to_have_count(0)
        assert installation(page, "practice") == practice
        assert [r.id for r in ledger.records()] == real  # not one record more or less, in the same order
        page.close()


def test_switching_the_language_switches_the_example(tmp_path, browser):
    """D-065: the example's own words follow the language switch, with the same step open; what was
    tried in one language is still there on coming back to it. Practice is named in the language
    too, and the author's own words are never changed."""
    with LiveServer(tmp_path) as srv:
        srv.ctx.ledger.init_identity("Author")
        srv.ctx.ledger.create_project("My study, in English")
        page = browser.new_page(viewport={"width": 1500, "height": 950})
        page.goto(srv.url)
        page.get_by_test_id("real-sample").click()
        page.get_by_test_id("example-banner").wait_for()
        steps = page.get_by_test_id("steps")
        expect(steps.locator(".step-card")).to_have_count(29)
        page.get_by_test_id("quick-note-open").click()
        page.get_by_test_id("quick-note-text").fill("Tried in the English example")
        page.get_by_test_id("quick-note-save").click()
        expect(steps.locator(".step-card")).to_have_count(30)
        page.get_by_test_id("sample-tour").get_by_test_id("tour-turn").click()
        expect(page.get_by_test_id("detail")).to_contain_text("Hypothesis H1′")

        page.get_by_test_id("lang-switch").click()  # to Chinese
        expect(page.get_by_test_id("sample-tour")).to_contain_text("示例研究：FSF（虚构）")
        expect(page.get_by_test_id("detail")).to_contain_text("假设 H1′")  # the same step, in Chinese
        expect(steps.locator(".step-card")).to_have_count(29)
        expect(steps).to_contain_text("假设 H1′：指数随驱动强度变化")
        assert "Hypothesis" not in steps.inner_text() and "Tried in the English example" not in steps.inner_text()
        expect(page.get_by_test_id("project-select").locator("option:checked")).to_have_text("FSF（示例）")

        page.get_by_test_id("lang-switch").click()  # back to English: as it was left
        expect(page.get_by_test_id("detail")).to_contain_text("Hypothesis H1′")
        expect(steps.locator(".step-card")).to_have_count(30)
        expect(steps).to_contain_text("Tried in the English example")

        page.get_by_test_id("lang-switch").click()
        page.get_by_test_id("space-practice").click()
        expect(page.get_by_test_id("project-select").locator("option:checked")).to_have_text("练习项目")
        page.get_by_test_id("lang-switch").click()
        expect(page.get_by_test_id("project-select").locator("option:checked")).to_have_text("Practice project")
        page.get_by_test_id("lang-switch").click()
        page.get_by_test_id("space-real").click()
        expect(page.get_by_test_id("project-select").locator("option:checked")).to_have_text("My study, in English")
        page.close()
