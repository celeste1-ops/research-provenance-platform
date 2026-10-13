"""D-066 in the browser: a step in the other language can be translated by the model on this
computer; the translation is shown beside the original, marked as such, and never saved."""

from __future__ import annotations

import httpx
import pytest

from app.services import translate
from app.services.ledger import EntryInput
from provenance_core.providers.local_ai import LocalModel
from tests.e2e.server import LiveServer

pytestmark = pytest.mark.e2e
expect = pytest.importorskip("playwright.sync_api").expect


def test_translate_a_step_beside_the_original(tmp_path, browser, monkeypatch):
    def handle(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "qwen3:8b"}]})
        return httpx.Response(200, json={"choices": [{"message": {
            "content": "<<TITLE>>\n流速趋于平稳\n<<TEXT>>\n强迫增大时，流速不会无限增长。"}}]})

    monkeypatch.setattr(translate, "model_factory", lambda url, model="", **kw: LocalModel(
        url, model, transport=httpx.MockTransport(handle), **kw))
    with LiveServer(tmp_path) as srv:
        ledger = srv.ctx.ledger
        ledger.init_identity("Author")
        project = ledger.create_project("FSF").id
        english = ledger.create_entry(EntryInput(project, "idea", "Flow speed levels off",
                                                 body="When the forcing rises, the flow speed does not grow."))
        ledger.create_entry(EntryInput(project, "idea", "已经是中文的一步"))
        count = ledger.record_count()
        page = browser.new_page(viewport={"width": 1500, "height": 950})
        page.goto(srv.url)
        page.get_by_test_id("lang-switch").click()  # to Chinese
        page.get_by_role("button", name="已经是中文的一步").first.click()
        expect(page.get_by_test_id("detail")).to_contain_text("已经是中文的一步")
        expect(page.get_by_test_id("translate")).to_have_count(0)  # nothing to translate

        page.get_by_role("button", name="Flow speed levels off").first.click()
        expect(page.get_by_test_id("detail").locator("h2")).to_have_text("Flow speed levels off")
        page.get_by_test_id("translate-run").click()
        box = page.get_by_test_id("translation")
        expect(box).to_contain_text("翻译——不属于记录")
        expect(box).to_contain_text("流速趋于平稳")
        expect(box).to_contain_text("强迫增大时，流速不会无限增长。")
        expect(box).to_contain_text("由本机的 qwen3:8b 刚刚翻译")
        expect(page.get_by_test_id("detail").locator("h2")).to_have_text("Flow speed levels off")  # the original stays
        assert ledger.record_count() == count  # never saved
        box.get_by_role("button", name="收起翻译").click()
        expect(page.get_by_test_id("translation")).to_have_count(0)
        assert ledger.record(english) is not None
        page.close()
