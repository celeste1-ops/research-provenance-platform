"""AC-13 (milestones only) and the rest of the P1 interface, on the FSF sample data."""

from __future__ import annotations

import pytest

from app.demo import load_demo
from tests.e2e.server import LiveServer

pytestmark = pytest.mark.e2e


@pytest.fixture
def demo_page(tmp_path, browser):
    with LiveServer(tmp_path) as srv:
        ids = load_demo(srv.ctx)
        page = browser.new_page(viewport={"width": 1500, "height": 950})
        page.goto(srv.url)
        page.get_by_test_id("graph").locator(".record-node").nth(13).wait_for()
        yield page, ids, srv
        page.close()


def test_milestones_only_view(demo_page):  # AC-13
    page, ids, srv = demo_page
    graph = page.get_by_test_id("graph")
    assert graph.locator(".record-node").count() == 14
    page.get_by_test_id("milestones-only").check()
    graph.get_by_test_id(f"node-{ids['formula1']}").wait_for(state="detached")
    graph.locator(".react-flow__edge-text").nth(2).wait_for()
    nodes = graph.locator(".record-node")
    assert nodes.count() == 3  # exp1 (set later), H1′, preprint
    assert graph.locator(".record-node.milestone").count() == 3
    assert graph.get_by_test_id(f"node-{ids['formula1']}").count() == 0  # non-milestones fold away
    labels = [t.text_content() for t in graph.locator(".react-flow__edge-text").all()]
    assert "2 in between" in labels  # exp1 -> run-1 data -> figure 2 -> preprint
    assert "directly related" in labels
    dashed = graph.locator(".react-flow__edge.milestone-connector path.react-flow__edge-path")
    assert dashed.count() >= 3
    assert all("6" in (p.get_attribute("style") or "") for p in dashed.all())
    page.get_by_test_id("milestones-only").uncheck()
    graph.locator(".record-node").nth(13).wait_for()
    assert graph.locator(".record-node").count() == 14


def test_timeline_view(demo_page):
    page, ids, srv = demo_page
    page.get_by_test_id("tab-timeline").click()
    table = page.get_by_test_id("timeline")
    table.wait_for()
    assert table.locator("tbody tr").count() == srv.ctx.ledger.record_count()
    headers = table.locator("thead").inner_text()
    assert "Third-party timestamp" in headers and "Bitcoin anchor" in headers and "unverified" in headers
    row = table.get_by_test_id(f"row-{ids['link1']}")
    assert "Relation (later)" in row.inner_text()
    row.click()
    page.get_by_test_id("detail").wait_for()


def test_changes_and_later_actions(demo_page):
    page, ids, srv = demo_page
    page.get_by_test_id(f"node-{ids['formula2']}").click()
    changes = page.get_by_test_id("section-changes")
    changes.locator("pre.diff").wait_for()
    diff = changes.inner_text()
    assert "against Formula v1" in diff
    assert "+alpha(F) = 1.5 - 0.2 F" in diff

    # Append-only actions from the sidebar: milestone and statement become new records.
    before = srv.ctx.ledger.record_count()
    actions = page.get_by_test_id("later-actions")
    actions.get_by_role("button", name="Mark as milestone").click()
    actions.get_by_role("button", name="Unmark milestone").wait_for()
    actions.get_by_role("button", name="Add statement…").click()
    actions.get_by_placeholder("Additional note or correction").fill("The 0.2 slope is a rough first guess.")
    actions.get_by_role("button", name="Add statement", exact=True).click()
    page.get_by_test_id("section-later").get_by_text("The 0.2 slope is a rough first guess.").wait_for()
    assert srv.ctx.ledger.record_count() == before + 2
    later = page.get_by_test_id("section-later").inner_text()
    assert "Marked milestone" in later
    assert "The 0.2 slope" not in page.get_by_test_id("section-verified").inner_text()


def test_200_nodes_render_within_a_second(tmp_path, browser):
    """PRD §11: up to 200 nodes, first render under one second."""
    import time

    from app.services.ledger import EntryInput

    with LiveServer(tmp_path) as srv:
        L = srv.ctx.ledger
        L.init_identity("Perf")
        pid = L.create_project("Perf").id
        prev = None
        types = ["idea", "note", "claim", "document", "code", "experiment", "dataset", "figure", "publication"]
        for i in range(200):
            rels = [{"to": prev, "rel": "revises"}] if prev and i % 3 else []
            prev = L.create_entry(EntryInput(pid, types[i % 9], f"Record {i}", relations=rels, milestone=i % 25 == 0))
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(srv.url + "/api/graph")  # warm the server-side read path
        page.goto("about:blank")
        start = time.monotonic()
        page.goto(srv.url)
        page.get_by_test_id("graph").locator(".record-node").nth(199).wait_for(state="attached")
        elapsed = time.monotonic() - start
        page.close()
    print(f"200-node first render: {elapsed:.3f}s")
    assert elapsed < 1.0, f"first render took {elapsed:.2f}s"
