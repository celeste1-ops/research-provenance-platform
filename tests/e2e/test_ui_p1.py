"""AC-13 (milestones only) and the rest of the P1 interface, on the FSF sample data."""

from __future__ import annotations

import pytest

from app.demo import load_demo
from tests.e2e.server import LiveServer, wait_for_step_count

pytestmark = pytest.mark.e2e
# Auto-retrying assertions: after an action the page updates in steps (notice first, status after).
expect = pytest.importorskip("playwright.sync_api").expect


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


def test_redrawing_the_map_never_hides_steps_again(demo_page):
    """The map is fetched again after start-up, a restore and every save, mostly unchanged. Steps
    handed to React Flow as new objects were hidden and measured again each time, and a redraw at
    the wrong moment left one hidden for good (seen on CI after a restore). Unchanged steps now
    stay the same objects; changed ones keep their size."""
    page, ids, _srv = demo_page
    page.wait_for_timeout(500)
    page.evaluate("""() => { window.__hidden = 0;
        new MutationObserver(ms => { for (const m of ms) if (m.target.classList?.contains('react-flow__node')
            && m.target.style.visibility === 'hidden') window.__hidden++; })
          .observe(document.querySelector('.react-flow'), {subtree: true, attributes: true, attributeFilter: ['style']}); }""")
    page.get_by_test_id("settings-menu").click()
    page.get_by_role("menuitem", name="Check stamps now").click()  # the same data again
    page.get_by_test_id(f"node-{ids['exp1']}").click()  # a redraw where two steps change
    page.get_by_test_id("detail").wait_for()
    page.get_by_test_id(f"node-{ids['exp2']}").click()
    page.wait_for_timeout(1000)
    assert page.evaluate("window.__hidden") == 0


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
    confirm = page.get_by_test_id("confirm-real")
    assert "Mark “Formula v2” as a key step?" in confirm.inner_text()
    confirm.get_by_role("button", name="Add to my record").click()
    actions.get_by_role("button", name="Unmark key step").wait_for()
    actions.get_by_role("button", name="Add statement…").click()
    actions.get_by_placeholder("Additional note or correction").fill("The 0.2 slope is a rough first guess.")
    actions.get_by_role("button", name="Add statement", exact=True).click()
    confirm = page.get_by_test_id("confirm-real")
    assert "The 0.2 slope is a rough first guess." in confirm.inner_text()
    confirm.get_by_role("button", name="Add to my record").click()
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
        expect(pill).to_contain_text("Backup not set up")
        pill.click()
        dlg = page.get_by_test_id("backup-dialog")
        dlg.get_by_label("Backup folder").fill(str(folder))
        # While choosing, the dialog says where the folder really is.
        check = dlg.get_by_test_id("location-check")
        check.get_by_text("This Mac's own disk", exact=True).wait_for()
        assert "lost with it" in check.inner_text()
        assert "can't be opened" in dlg.get_by_test_id("password-warning").inner_text()
        dlg.get_by_label("Backup password (at least 8 characters)").fill("backup password 1")
        dlg.get_by_label("Repeat the password").fill("backup password 1")
        dlg.get_by_role("button", name="Turn on automatic backup").click()
        # The printable recovery code is shown once; continuing needs a tick.
        sheet = dlg.get_by_test_id("recovery-code")
        sheet.wait_for()
        code = sheet.get_by_test_id("recovery-code-value").inner_text().strip()
        fingerprint = sheet.get_by_test_id("recovery-fingerprint").locator("b").inner_text().strip()
        assert len(fingerprint) == 19
        assert len(code) == 27 and code not in (a.ctx.ledger.meta("backup_recovery") or "")
        assert sheet.get_by_role("button", name="Continue").is_disabled()
        sheet.get_by_label("I have printed it or written it down").check()
        sheet.get_by_role("button", name="Continue").click()
        page.get_by_test_id("notice").get_by_text("Automatic backup is on").wait_for()
        # The test folder is on the same disk as the records: the app says it would not survive a lost Mac.
        expect(pill).to_contain_text("Backup is on this Mac only")
        pill.click()
        dlg = page.get_by_test_id("backup-dialog")
        expect(dlg).to_contain_text("lost with it")
        expect(dlg.get_by_test_id("recovery-status")).to_contain_text("Recovery code:")
        dlg.get_by_role("button", name="Close").click()
        page.close()
    (backup,) = list(folder.iterdir())
    assert backup.name.endswith(".rprovbackup")
    assert backup.read_bytes().startswith(b"RPROV-BACKUP-ENC/3\n")
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
        # Password forgotten: the printed recovery code opens the backup instead.
        form.get_by_role("button", name="Forgot the password? Use the recovery code instead").click()
        form.get_by_label("Recovery code").fill(code.lower())
        form.get_by_role("button", name="Restore my research").click()
        # The signing key it brought back is shown, to compare with the printed sheet.
        result = page.get_by_test_id("restore-result")
        assert fingerprint in result.get_by_test_id("restored-fingerprint").inner_text()
        result.get_by_role("button", name="Open the app").click()
        page.get_by_test_id("graph").locator(".record-node").nth(13).wait_for()
        wait_for_step_count(page, "14 steps")
        assert b.ctx.ledger.record_count() == count
        # Paused until confirmed; the old password is unknown, so resuming asks for a new one.
        pill = page.get_by_test_id("backup-pill")
        expect(pill).to_contain_text("Backup paused")
        pill.click()
        paused = page.get_by_test_id("backup-paused")
        assert "restored from a backup" in paused.inner_text()
        paused.get_by_label("Backup password (at least 8 characters)").fill("a new password")
        paused.get_by_label("Repeat the password").fill("a new password")
        paused.get_by_role("button", name="Set password and resume").click()
        page.get_by_test_id("notice").get_by_text("Automatic backup resumed").wait_for()
        assert len(list(folder.iterdir())) == 2
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
        sheet = page.get_by_test_id("recovery-code")
        sheet.wait_for()
        assert page.get_by_role("button", name="Skip for now").count() == 0  # the code can't be skipped past
        sheet.get_by_label("I have printed it or written it down").check()
        sheet.get_by_role("button", name="Continue").click()
        page.get_by_test_id("empty-state").wait_for()
        assert len(list(folder.glob("*.rprovbackup"))) == 1
        wait_for_step_count(page, "0 steps")
        # No project name given: a default one is created so the first step can be added right away.
        expect(page.get_by_label("Project").locator("option:checked")).to_have_text("My research")
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
        page.get_by_test_id("confirm-save").click()
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
        assert items == ["Check stamps now", "Check stamp services…", "Backup…", "Where is my data?",
                         "Technical details", "Back up signing key only…"]
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


def test_slow_folder_suggestions_do_not_replace_a_typed_folder(tmp_path, browser, monkeypatch):
    """Windows looks at every drive, so suggestions can arrive after the author typed a folder;
    they must not overwrite it (seen on windows-latest)."""
    import time

    from app.services import autobackup

    folder = tmp_path / "typed"
    folder.mkdir()
    other = tmp_path / "suggested"

    def slow_suggestions(data_dir):
        time.sleep(1.5)
        return [{"path": str(other), "label": "Drive D:", "kind": "external"}]

    monkeypatch.setattr(autobackup, "suggestions", slow_suggestions)
    with LiveServer(tmp_path / "a") as srv:
        srv.ctx.ledger.init_identity("Typist")
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(srv.url)
        page.get_by_test_id("backup-pill").click()
        dlg = page.get_by_test_id("backup-dialog")
        field = dlg.get_by_label("Backup folder")
        field.fill(str(folder))
        expect(dlg.get_by_text("Drive D:")).to_be_visible()  # the suggestions have arrived
        expect(field).to_have_value(str(folder))
        expect(dlg.get_by_test_id("location-check")).to_contain_text("This Mac's own disk")
        page.close()


def _check(group, name, ok, detail, ms=420):
    return {"group": group, "name": name, "url": f"https://{name}", "ok": ok, "ms": ms if ok else None,
            "detail": detail}


def test_check_stamp_services(tmp_path, browser):
    """D-045: FreeTSA blocked, DigiCert working, one calendar blocked: the summary says what still works."""
    with LiveServer(tmp_path) as srv:
        srv.ctx.ledger.init_identity("Checker")
        calls = []

        def fake_check():
            calls.append(1)
            return {
                "checks": [
                    _check("tsa", "FreeTSA", False, "not reachable (ConnectTimeout)"),
                    _check("tsa", "DigiCert", True, "stamp received and checked"),
                    _check("calendar", "a.pool.opentimestamps.org", True, "answered"),
                    _check("calendar", "b.pool.opentimestamps.org", True, "answered"),
                    _check("calendar", "a.pool.eternitywall.com", False, "not reachable (ConnectError)"),
                    _check("calendar", "ots.btc.catallaxy.com", True, "answered"),
                    _check("explorer", "blockstream.info", True, "current block 917,123"),
                    _check("explorer", "mempool.space", False, "not reachable (ConnectTimeout)"),
                ],
                "in_use": {"tsa": ["freetsa", "digicert"], "btc": True, "explorers": True},
            }

        srv.ctx.service_check = fake_check
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(srv.url)
        page.get_by_test_id("empty-state").wait_for()
        page.get_by_test_id("settings-menu").click()
        page.get_by_role("menuitem", name="Check stamp services…").click()
        dialog = page.get_by_test_id("service-check")
        expect(dialog).to_contain_text("nothing from your notes")
        assert calls == []  # nothing is contacted until the author asks
        dialog.get_by_test_id("service-check-run").click()
        summary = dialog.get_by_test_id("service-check-summary")
        expect(summary).to_contain_text("Date stamps work (DigiCert answered).")
        expect(summary).to_contain_text("Public stamps can start (3 of 4 services answered).")
        expect(summary).to_contain_text("Finished public stamps can't be checked from here right now")
        expect(dialog.get_by_test_id("service-FreeTSA")).to_contain_text("not reachable")
        expect(dialog.get_by_test_id("service-DigiCert")).to_contain_text("0.4 s")
        expect(dialog.get_by_test_id("service-check-run")).to_have_text("Check again")
        assert calls == [1]
        dialog.get_by_role("button", name="Close").click()
        expect(page.get_by_test_id("service-check")).to_have_count(0)
        page.close()


def test_practice_space(tmp_path, browser):
    """Practice: separate, clearly marked, saves without asking; the real record is untouched."""
    with LiveServer(tmp_path) as srv:
        srv.ctx.ledger.init_identity("Ada")
        srv.ctx.ledger.create_project("FSF")
        real_count = srv.ctx.ledger.record_count()
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(srv.url)
        page.get_by_test_id("empty-state").wait_for()
        assert page.get_by_test_id("practice-banner").count() == 0

        page.get_by_test_id("space-practice").click()
        banner = page.get_by_test_id("practice-banner")
        banner.wait_for()
        assert "nothing here goes into your real record" in banner.inner_text()
        assert "space-practice" in (page.locator(".app").get_attribute("class") or "")
        assert page.get_by_test_id("backup-pill").count() == 0  # practice is never backed up
        expect(page.get_by_label("Project").locator("option:checked")).to_have_text("Practice project")

        page.get_by_test_id("start-idea").click()
        form = page.get_by_test_id("record-form")
        assert "Practice: this does not go into your real record." in form.inner_text()
        form.locator("input[name=title]").fill("Scratch idea")
        form.get_by_role("button", name="Save practice step").click()
        page.get_by_test_id("detail").wait_for()  # saved straight away, no confirmation
        assert page.get_by_test_id("confirm-real").count() == 0
        wait_for_step_count(page, "1 step")
        assert srv.ctx.ledger.record_count() == real_count

        # Reloading keeps the space; the Settings menu offers practice-only actions.
        page.reload()
        page.get_by_test_id("practice-banner").wait_for()
        wait_for_step_count(page, "1 step")
        page.get_by_test_id("settings-menu").click()
        items = [i.inner_text() for i in page.get_by_role("menuitem").all()]
        assert "Backup…" not in items and "Start practice over…" in items
        page.get_by_role("menuitem", name="Start practice over…").click()
        page.get_by_test_id("practice-reset").get_by_role("button", name="Start over").click()
        page.get_by_test_id("empty-state").wait_for()
        wait_for_step_count(page, "0 steps")

        page.get_by_test_id("practice-sample").click()
        page.get_by_test_id("graph").locator(".record-node").nth(13).wait_for()
        wait_for_step_count(page, "14 steps")
        assert srv.ctx.ledger.record_count() == real_count

        # Back to the real record: a reminder that saving there is permanent.
        page.get_by_test_id("space-real").click()
        page.get_by_test_id("notice").get_by_text("Steps you save here are permanent").wait_for()
        page.get_by_test_id("empty-state").wait_for()
        assert page.get_by_test_id("practice-banner").count() == 0
        wait_for_step_count(page, "0 steps")
        page.close()


def test_practice_before_setting_up(tmp_path, browser):
    with LiveServer(tmp_path) as srv:
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(srv.url)
        page.get_by_test_id("setup-practice").click()
        page.get_by_test_id("practice-banner").wait_for()
        assert not srv.ctx.ledger.initialized()
        page.get_by_test_id("space-real").click()
        page.get_by_placeholder("Name or pen name").wait_for()  # the real record is still to be set up
        page.close()


def test_restored_copy_waits_before_backing_up(tmp_path, browser):
    """D-040: after a restore, automatic backup is paused until the author confirms the folder."""
    folder = tmp_path / "shared-backups"
    with LiveServer(tmp_path / "a") as a:
        load_demo(a.ctx)
        a.ctx.autobackup.configure(str(folder), "backup password 1", create=True)
    (backup,) = list(folder.iterdir())
    with LiveServer(tmp_path / "b") as b:
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(b.url)
        page.get_by_role("button", name="Restore from a backup").click()
        form = page.get_by_test_id("restore-form")
        form.get_by_label("Backup file").set_input_files(str(backup))
        form.get_by_label("Backup password").fill("backup password 1")
        form.get_by_role("button", name="Restore my research").click()
        pill = page.get_by_test_id("backup-pill")
        pill.get_by_text("Backup paused — confirm to resume").wait_for()
        assert list(folder.iterdir()) == [backup]  # nothing written by the restored copy
        pill.click()
        paused = page.get_by_test_id("backup-paused")
        assert "restored from a backup" in paused.inner_text() and "only a test" in paused.inner_text()
        paused.get_by_role("button", name="Resume automatic backup to this folder").click()
        page.get_by_test_id("notice").get_by_text("Automatic backup resumed").wait_for()
        assert len(list(folder.iterdir())) == 2 and backup.exists()
        expect(pill).to_contain_text("Backup is on this Mac only")
        page.close()


def test_old_mac_warns_when_a_new_mac_backs_up_into_the_same_folder(tmp_path, browser):
    """D-041: two copies of the same research writing into one folder are told about each other."""
    from app.services.backup import restore_backup
    from app.services.keystore import MemoryKeyStore
    from tests.conftest import make_ctx

    folder = tmp_path / "icloud"
    with LiveServer(tmp_path / "old-mac") as old:
        load_demo(old.ctx)
        old.ctx.autobackup.configure(str(folder), "backup password 1", create=True)
        new = make_ctx(tmp_path / "new-mac", keystore=MemoryKeyStore())
        restore_backup(new, next(folder.iterdir()).read_bytes(), "backup password 1")
        new.autobackup.adopt_restored_password("backup password 1")
        new.autobackup.resume()  # the new Mac now backs up into the same folder
        new.close()

        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(old.url)
        banner = page.get_by_test_id("other-copy-banner")
        banner.wait_for()
        assert "Use only one Mac" in banner.inner_text()
        expect(page.get_by_test_id("backup-pill")).to_contain_text("Another Mac is backing up here too")
        banner.get_by_role("button", name="What to do").click()
        box = page.get_by_test_id("other-copy")
        assert "histories split" in box.inner_text()
        box.get_by_role("button", name="The other copy is gone — stop warning").click()
        page.get_by_test_id("notice").get_by_text("no more warnings").wait_for()
        page.get_by_test_id("other-copy-banner").wait_for(state="detached")
        expect(page.get_by_test_id("backup-pill")).not_to_contain_text("Another Mac")
        page.close()
