"""AC-13 (milestones only) and the rest of the P1 interface, on the FSF sample data."""

from __future__ import annotations

import pytest

from app.demo import load_demo
from tests.e2e.server import LiveServer, wait_for_step_count

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
    assert "Date stamp" in headers and "Public stamp" in headers and "unverified" in headers
    row = table.get_by_test_id(f"row-{ids['link1']}")
    assert "Link (added later)" in row.inner_text()
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
    actions.get_by_role("button", name="Mark as key step").click()
    actions.get_by_role("button", name="Unmark key step").wait_for()
    actions.get_by_role("button", name="Add statement…").click()
    actions.get_by_placeholder("Additional note or correction").fill("The 0.2 slope is a rough first guess.")
    actions.get_by_role("button", name="Add statement", exact=True).click()
    page.get_by_test_id("section-later").get_by_text("The 0.2 slope is a rough first guess.").wait_for()
    assert srv.ctx.ledger.record_count() == before + 2
    later = page.get_by_test_id("section-later").inner_text()
    assert "Marked key step" in later
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


def test_backup_and_restore_in_the_browser(tmp_path, browser):
    """Automatic encrypted backup is set up from the top bar; a fresh install restores from it."""
    folder = tmp_path / "backups"
    folder.mkdir()
    with LiveServer(tmp_path / "a") as a:
        load_demo(a.ctx)
        count = a.ctx.ledger.record_count()
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(a.url)
        pill = page.get_by_test_id("backup-pill")
        assert "Backup not set up" in pill.inner_text()
        pill.click()
        dlg = page.get_by_test_id("backup-dialog")
        dlg.get_by_label("Backup folder").fill(str(folder))
        dlg.get_by_label("Backup password (at least 8 characters)").fill("backup password 1")
        dlg.get_by_label("Repeat the password").fill("backup password 1")
        dlg.get_by_role("button", name="Turn on automatic backup").click()
        page.get_by_test_id("notice").get_by_text("Automatic backup is on").wait_for()
        # The test folder is on the same disk as the records: the app says it would not survive a lost Mac.
        assert "Backup is on this Mac only" in pill.inner_text()
        pill.click()
        dlg = page.get_by_test_id("backup-dialog")
        assert "same disk" in dlg.inner_text()
        dlg.get_by_role("button", name="Close").click()
        page.close()
    (backup,) = list(folder.iterdir())
    assert backup.name.endswith(".rprovbackup")
    assert backup.read_bytes().startswith(b"RPROV-BACKUP-ENC/1\n")
    assert b"Formula" not in backup.read_bytes()  # nothing readable without the password
    with LiveServer(tmp_path / "b") as b:
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(b.url)
        page.get_by_role("button", name="Restore from a backup").click()
        form = page.get_by_test_id("restore-form")
        form.get_by_label("Backup file").set_input_files(str(backup))
        form.get_by_label("Backup password").fill("wrong password!")
        form.get_by_role("button", name="Restore my research").click()
        form.get_by_text("wrong backup password").wait_for()
        assert b.ctx.ledger.record_count() == 0
        form.get_by_label("Backup password").fill("backup password 1")
        form.get_by_role("button", name="Restore my research").click()
        page.get_by_test_id("graph").locator(".record-node").nth(13).wait_for()
        wait_for_step_count(page, "14 steps")
        assert b.ctx.ledger.record_count() == count
        # Same folder and password: automatic backups simply continue on the new install.
        assert "Backup is on this Mac only" in page.get_by_test_id("backup-pill").inner_text()
        page.close()


def test_first_run_with_automatic_backup(tmp_path, browser):
    """Onboarding: name + project, then a backup folder; the first backup is written immediately."""
    folder = tmp_path / "backup-target"
    with LiveServer(tmp_path / "srv") as srv:
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(srv.url)
        page.get_by_placeholder("Name or pen name").fill("New Researcher")
        page.get_by_role("button", name="Start").click()
        setup = page.get_by_test_id("backup-setup")
        setup.get_by_label("Backup folder").fill(str(folder))  # created if needed
        setup.get_by_label("Backup password (at least 8 characters)").fill("first password")
        setup.get_by_label("Repeat the password").fill("first passwort")
        setup.get_by_role("button", name="Turn on automatic backup").click()
        setup.get_by_text("The two passwords are not the same.").wait_for()
        setup.get_by_label("Repeat the password").fill("first password")
        setup.get_by_role("button", name="Turn on automatic backup").click()
        page.get_by_test_id("empty-state").wait_for()
        assert len(list(folder.glob("*.rprovbackup"))) == 1
        wait_for_step_count(page, "0 steps")
        # No project name given: a default one is created so the first step can be added right away.
        assert page.get_by_label("Project").locator("option:checked").inner_text() == "My research"
        page.close()


def test_empty_state_and_help_panels(tmp_path, browser):
    with LiveServer(tmp_path) as srv:
        srv.ctx.ledger.init_identity("Helper")
        srv.ctx.ledger.create_project("FSF")
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(srv.url)
        empty = page.get_by_test_id("empty-state")
        empty.wait_for()
        assert "Record the first step of FSF" in empty.inner_text()
        assert "Automatic backup is not on yet" in empty.inner_text()
        wait_for_step_count(page, "0 steps")
        assert page.get_by_role("button", name="Share", exact=True).is_disabled()
        assert "Only a fingerprint is sent out to get a date stamp" in page.get_by_test_id("home-note").inner_text()

        # Picking a kind of step opens the form with that kind already chosen.
        page.get_by_test_id("start-experiment").click()
        form = page.get_by_test_id("record-form")
        assert form.get_by_role("radio", name="Experiment").is_checked()
        assert form.get_by_role("button", name="+ Connect to an earlier step").is_disabled()
        form.locator("input[name=title]").fill("Run 1")
        page.get_by_test_id("submit-record").click()
        page.get_by_test_id("detail").wait_for()
        wait_for_step_count(page, "1 step")
        assert srv.ctx.ledger.record_count() == 2  # genesis + the step; only the step is counted

        # Each stamp has a "?" that explains it in one sentence, with the formal name used in reports.
        page.get_by_test_id("help-stamp-tsa").click()
        assert "Third-party timestamp" in page.get_by_test_id("help-stamp-tsa-text").inner_text()
        page.keyboard.press("Escape")
        page.get_by_test_id("help-stamp-btc").click()
        assert "Bitcoin anchor" in page.get_by_test_id("help-stamp-btc-text").inner_text()
        page.keyboard.press("Escape")
        assert page.get_by_test_id("help-stamp-btc-text").count() == 0

        # The legend (line types, D/P icons) is behind the "?" next to Map, not always on screen.
        assert page.get_by_test_id("legend").count() == 0
        page.get_by_test_id("help-map").click()
        legend = page.get_by_test_id("legend")
        assert "Date stamp" in legend.inner_text() and "Public stamp" in legend.inner_text()
        page.locator(".brand").click()  # a click anywhere else closes it
        assert page.get_by_test_id("legend").count() == 0
        for hid in ("add-step", "share", "list", "key-steps"):
            page.get_by_test_id(f"help-{hid}").click()
            assert len(page.get_by_test_id(f"help-{hid}-text").inner_text()) > 20
            page.keyboard.press("Escape")

        # Technical actions live in the More menu.
        page.get_by_test_id("settings-menu").click()
        items = [i.inner_text() for i in page.get_by_role("menuitem").all()]
        assert items == ["Check stamps now", "Backup…", "Where is my data?", "Technical details",
                         "Back up signing key only…"]
        page.get_by_role("menuitem", name="Where is my data?").click()
        where = page.get_by_test_id("where-is-my-data")
        text = where.inner_text()
        assert str(srv.ctx.settings.data_dir) in text
        assert "Not set up yet" in text and "only receive a fingerprint" in text
        where.get_by_role("button", name="Close").click()

        page.get_by_test_id("settings-menu").click()
        page.get_by_role("menuitem", name="Technical details").click()
        tech = page.get_by_test_id("technical-details")
        assert srv.ctx.ledger.installation in tech.inner_text()
        assert "2 — 1 research step, plus" in tech.inner_text()
        page.close()
