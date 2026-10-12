"""AC-20: report.html opened offline shows the graph, the timeline and the
"what it proves / does not prove" text, and makes no network requests.
AC-14 (report half): author statements never appear in a Verified record section;
the two kinds of time proof are shown separately."""

import re

import pytest

from tests.sample import make_sample

pytestmark = pytest.mark.e2e


def test_report_offline_no_requests(tmp_path, browser):
    s = make_sample(tmp_path)
    report = s.bundle_dir / "report.html"
    # WebKit's offline mode also refuses file:// pages; the list of requests below shows the
    # report asks for nothing either way.
    context = browser.new_context(offline=browser.browser_type.name != "webkit")
    page = context.new_page()
    requests = []
    page.on("request", lambda req: requests.append(req.url))
    page.goto(report.as_uri())
    page.wait_for_load_state("networkidle")
    assert requests == [report.as_uri()], requests  # only the file itself

    assert page.locator("#proves").is_visible()
    proves = page.locator("#proves").inner_text()
    assert "existed no later than the verified time" in proves
    assert "the author personally thought of it" in proves

    svg = page.locator("#graph svg")
    assert svg.is_visible()
    assert svg.locator("g.node").count() == 4  # disclosed entries: idea, experiment, claim, preprint
    assert svg.locator("g.node.milestone").count() == 2
    assert "added" in svg.text_content()  # the later link carries its added date

    rows = page.locator("#timeline tbody tr")
    assert rows.count() == len(s.levels)
    headers = page.locator("#timeline thead").inner_text()
    assert "Third-party timestamp" in headers and "Bitcoin anchor" in headers
    assert page.locator("#timeline").inner_text().count("Hidden record (existence only)") == 1
    context.close()


def test_report_source_sections(tmp_path):
    s = make_sample(tmp_path)
    html = s.files["report.html"].decode()
    verified_sections = re.findall(r'<div class="section sec-verified">(.*?)</div>\s*<div class="section sec-author">',
                                   html, flags=re.S)
    assert verified_sections
    for section in verified_sections:
        assert "came from last year" not in section  # author statement
        assert "noticed later" not in section  # link statement
        assert "Claimed date" not in section and "2025-11" not in section
        assert "Local clock time" not in section
        assert "Third-party timestamp" in section and "Bitcoin anchor" in section
    assert "came from last year&#39;s notes" in html or "came from last year's notes" in html
    # No merged, unlabelled "verified time": every earliest time names its source.
    for m in re.finditer(r"Earliest verified time</dt><dd>([^<]*)</dd>", html):
        assert "(from Third-party timestamp)" in m.group(1) or "(from Bitcoin anchor)" in m.group(1) \
            or "none yet" in m.group(1)
    assert "<script" not in html.lower()
    assert "This record does not prove authorship or originality." in html
