"""Regenerate the README screenshots in docs/screenshots/ from the FSF sample research (D-059).

Uses the mock time-stamping authority, so the screenshots show "rprov Mock TSA".

    uv run python tools/screenshots.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

from app.demo import load_sample  # noqa: E402
from app.services.export import build_bundle_files, plan_export, write_dir  # noqa: E402
from tests.e2e.conftest import chromium_path  # noqa: E402
from tests.e2e.server import LiveServer  # noqa: E402

OUT = ROOT / "docs" / "screenshots"


def first_run(browser) -> None:
    """The two onboarding screens: about you, then automatic backup."""
    with tempfile.TemporaryDirectory() as tmp, LiveServer(Path(tmp)) as srv:
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(srv.url)
        page.get_by_placeholder("Name or pen name").fill("A. Researcher")
        page.get_by_placeholder("e.g. FSF").fill("FSF")
        page.screenshot(path=OUT / "first-run.png")
        page.get_by_role("button", name="Start").click()
        # This machine has no iCloud Drive: answer the folder check as a Mac with one would.
        page.route("**/api/backup/check?*", lambda route: route.fulfill(json={
            "ok": True, "kind": "synced", "label": "iCloud Drive", "safe": True, "creates": True}))
        page.get_by_test_id("backup-setup").get_by_label("Backup folder").fill(
            "/Users/you/Library/Mobile Documents/com~apple~CloudDocs/Research Provenance Backups"
        )
        page.wait_for_timeout(300)
        page.screenshot(path=OUT / "first-run-backup.png")
        page.get_by_role("button", name="Skip for now").click()
        page.get_by_test_id("empty-state").wait_for()
        page.wait_for_timeout(300)
        page.screenshot(path=OUT / "empty-project.png")
        page.close()


def app_screens(browser, tmp: Path) -> None:
    """The map, a step's panel and the shared report, with the FSF sample research (D-059) in
    My research, as if it were the author's own."""
    with LiveServer(tmp) as srv:
        load_sample(srv.ctx, "en")
        page = browser.new_page(viewport={"width": 1440, "height": 860})
        page.add_init_script("localStorage.setItem('rprov-tips-hidden', '1')")  # the how-to line, read
        page.goto(srv.url)
        page.get_by_test_id("steps").locator(".step-card").first.wait_for()
        page.get_by_test_id("tab-graph").click()
        page.get_by_test_id("graph").wait_for()
        page.get_by_role("checkbox", name="Key steps only").check()  # the turning points, large enough to read
        page.get_by_test_id("map-legend-hide").click()  # so that it covers no step
        page.locator(".react-flow__controls-fitview").click()
        page.wait_for_timeout(800)
        page.screenshot(path=OUT / "graph.png")
        page.get_by_test_id("map-legend-open").click()
        page.get_by_role("checkbox", name="Key steps only").uncheck()

        page.get_by_test_id("tab-steps").click()
        page.get_by_role("button", name="Hypothesis H1′: the exponent depends on the forcing").first.click()
        page.get_by_test_id("detail").wait_for()
        page.wait_for_timeout(500)
        page.screenshot(path=OUT / "detail.png")
        page.get_by_test_id("new-record").click()
        page.wait_for_timeout(300)
        page.screenshot(path=OUT / "record-form.png")
        page.close()

        plan = plan_export(srv.ctx.ledger, "FSF (sample)", None, default="full")
        bundle = tmp / "bundle"
        write_dir(build_bundle_files(srv.ctx.ledger, srv.ctx.anchors, plan), bundle)
        report = browser.new_page(viewport={"width": 1200, "height": 900})
        report.goto((bundle / "report.html").as_uri())
        report.wait_for_timeout(500)
        report.screenshot(path=OUT / "report.png")
        report.close()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium_path())
        first_run(browser)
        with tempfile.TemporaryDirectory() as tmp:
            app_screens(browser, Path(tmp))
        browser.close()
    print(f"wrote screenshots to {OUT}")


if __name__ == "__main__":
    main()
