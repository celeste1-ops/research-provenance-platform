"""Regenerate the README screenshots in docs/screenshots/ from sample data.

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

from app.services.export import build_bundle_files, plan_export, write_dir  # noqa: E402
from tests.e2e.conftest import chromium_path  # noqa: E402
from tests.e2e.server import LiveServer  # noqa: E402
from tests.sample import build_log  # noqa: E402

OUT = ROOT / "docs" / "screenshots"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp, LiveServer(Path(tmp)) as srv, sync_playwright() as p:
        ids = build_log(srv.ctx)
        browser = p.chromium.launch(executable_path=chromium_path())
        page = browser.new_page(viewport={"width": 1440, "height": 860})
        page.goto(srv.url)
        page.get_by_test_id("graph").wait_for()
        page.wait_for_timeout(600)
        page.screenshot(path=OUT / "graph.png")
        page.get_by_test_id(f"node-{ids['exp']}").click()
        page.get_by_test_id("detail").wait_for()
        page.wait_for_timeout(400)
        page.screenshot(path=OUT / "detail.png")
        page.get_by_test_id("new-record").click()
        page.wait_for_timeout(300)
        page.screenshot(path=OUT / "record-form.png")

        plan = plan_export(srv.ctx.ledger, "FSF sample", None, default="full")
        bundle = Path(tmp) / "bundle"
        write_dir(build_bundle_files(srv.ctx.ledger, srv.ctx.anchors, plan), bundle)
        report = browser.new_page(viewport={"width": 1200, "height": 900})
        report.goto((bundle / "report.html").as_uri())
        report.screenshot(path=OUT / "report.png")
        browser.close()
    print(f"wrote screenshots to {OUT}")


if __name__ == "__main__":
    main()
