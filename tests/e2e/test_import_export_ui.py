"""D-060 in the browser: importing a notes folder and a table (Settings → Import notes or a table…),
and putting the evidence bundle into a git repository from the Share window."""

from __future__ import annotations

import pytest

from app.services.gitrepo import find_git
from provenance_core.jcs import parse_json_strict
from tests.e2e.server import LiveServer
from tests.gitutil import GitRepo

pytestmark = pytest.mark.e2e
expect = pytest.importorskip("playwright.sync_api").expect

TABLE = "title,type,date,builds on,key step\nA hunch,idea,2025-09-14,,\nFirst test,experiment,2025-10,1,yes\n"


def entry_payloads(ctx) -> list[dict]:
    return [{"id": r.id, **parse_json_strict(r.payload_bytes)} for r in ctx.ledger.records() if r.kind == "entry"]


def open_import(page):
    page.get_by_test_id("settings-menu").click()
    page.get_by_test_id("menu-import").click()
    return page.get_by_test_id("import-dialog")


def test_import_a_notes_folder_and_a_table(tmp_path, browser):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Saturation.md").write_text("---\ndate: 2024-03-01\n---\nBuilds on [[Hunch]].\n", encoding="utf-8")
    (vault / "Hunch.md").write_text("---\ndate: 2024-02-01\n---\nThe flow levels off.\n", encoding="utf-8")
    (vault / "Draft.md").write_text("Not ready yet.\n", encoding="utf-8")
    csv_file = tmp_path / "steps.csv"
    csv_file.write_text(TABLE, encoding="utf-8")
    with LiveServer(tmp_path / "app") as srv:
        srv.ctx.ledger.init_identity("Author")
        srv.ctx.ledger.create_project("FSF")
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(srv.url)
        dialog = open_import(page)
        dialog.get_by_test_id("import-notes-path").fill(str(vault))
        dialog.get_by_test_id("import-notes-look").click()
        listing = dialog.get_by_test_id("import-notes-list")
        expect(listing).to_contain_text("Hunch")
        dialog.get_by_role("checkbox", name="Draft").uncheck()  # left out
        dialog.get_by_test_id("import-notes-go").click()
        expect(dialog.get_by_test_id("import-confirm")).to_contain_text("2 steps will be added")  # the real record
        dialog.get_by_test_id("import-confirm-yes").click()
        expect(dialog.get_by_test_id("import-done")).to_contain_text("2 steps added")
        hunch, saturation = entry_payloads(srv.ctx)
        assert (hunch["title"], saturation["title"]) == ("Hunch", "Saturation")
        assert hunch["import"]["claimed_date"] == "2024-02-01"
        assert saturation["relations"] == [{"to": hunch["id"], "rel": "uses"}]
        dialog.get_by_role("button", name="Done").click()

        dialog = open_import(page)
        dialog.get_by_test_id("import-tab-table").click()
        expect(dialog.get_by_test_id("import-template")).to_have_attribute("href", "/api/import/table/template?lang=en")
        dialog.get_by_test_id("import-table-file").set_input_files(str(csv_file))
        expect(dialog.get_by_test_id("import-table-list")).to_contain_text("Experiment")
        dialog.get_by_test_id("import-table-go").click()
        dialog.get_by_test_id("import-confirm-yes").click()
        expect(dialog.get_by_test_id("import-done")).to_contain_text("2 steps added")
        steps = entry_payloads(srv.ctx)
        assert [s["title"] for s in steps[2:]] == ["A hunch", "First test"]
        assert steps[3]["milestone"] and steps[3]["relations"] == [{"to": steps[2]["id"], "rel": "uses"}]
        dialog.get_by_role("button", name="Done").click()
        expect(page.get_by_test_id("steps")).to_contain_text("First test")
        page.close()


@pytest.mark.skipif(find_git() is None, reason="git is not installed")
def test_share_into_a_repository(tmp_path, browser, monkeypatch):
    for k, v in {"GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@example.org", "GIT_COMMITTER_NAME": "A",
                 "GIT_COMMITTER_EMAIL": "a@example.org"}.items():
        monkeypatch.setenv(k, v)  # git needs a name for the commit
    repo = GitRepo(tmp_path / "fsf-code")
    repo.commit("Initial model")
    with LiveServer(tmp_path / "app") as srv:
        srv.ctx.ledger.init_identity("Author")
        project = srv.ctx.ledger.create_project("FSF")
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(srv.url)
        page.get_by_test_id("quick-note-open").click()
        page.get_by_test_id("quick-note-text").fill("Tried a smaller step size")
        page.get_by_test_id("quick-note-save").click()
        expect(page.get_by_test_id("quick-note")).to_have_count(0)
        page.get_by_test_id("share").click()
        dialog = page.get_by_test_id("export-dialog")
        expect(dialog.get_by_test_id("export-table")).to_have_attribute(
            "href", f"/api/export/table?project={project.id}&lang=en")

        dialog.get_by_test_id("dest-zenodo").check()  # not connected yet: a token first
        expect(dialog.get_by_test_id("zenodo-connect")).to_be_visible()
        expect(dialog.get_by_test_id("do-export")).to_be_disabled()

        dialog.get_by_test_id("dest-repo").check()
        dialog.get_by_test_id("dest-repo-path").fill(str(repo.path))
        dialog.get_by_test_id("do-export").click()
        expect(dialog.get_by_test_id("export-done")).to_contain_text("Committed as")
        [bundle] = list((repo.path / "provenance").glob("*/bundle.json"))
        assert (bundle.parent / "VERIFY.md").is_file()
        assert repo.git("log", "-1", "--format=%s").startswith("Evidence bundle: ")
        page.close()
