"""D-050 in the browser, against a small stand-in for a local model server on 127.0.0.1: the
retelling is labelled AI inference, flagged sentences are crossed out and left out when saved."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.demo import load_demo
from tests.e2e.server import LiveServer

pytestmark = pytest.mark.e2e
expect = pytest.importorskip("playwright.sync_api").expect

REPLY = ("## How it started\n"
         "The research began with an intuition that flow speed saturates [#1]. "
         "A hypothesis grew out of it [#3, #1].\n"
         "This proves the author's originality [#1]. Nobody knows when this happened.")


class FakeModel(BaseHTTPRequestHandler):
    prompts: list = []

    def _json(self, data: dict) -> None:
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        self._json({"data": [{"id": "qwen2.5:7b"}]})

    def do_POST(self):  # noqa: N802
        FakeModel.prompts.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        self._json({"choices": [{"message": {"content": REPLY}}]})

    def log_message(self, *args):
        pass


def test_retell_with_a_local_model(tmp_path, browser):
    model_server = ThreadingHTTPServer(("127.0.0.1", 0), FakeModel)
    threading.Thread(target=model_server.serve_forever, daemon=True).start()
    try:
        with LiveServer(tmp_path) as srv:
            load_demo(srv.ctx)
            records = srv.ctx.ledger.record_count()
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            page.goto(srv.url)
            page.get_by_test_id("tab-story").click()
            page.get_by_test_id("ai-open").click()
            panel = page.get_by_test_id("ai-panel")
            panel.get_by_test_id("ai-url").fill(f"http://127.0.0.1:{model_server.server_port}")
            panel.get_by_test_id("ai-find").click()
            expect(panel.get_by_test_id("ai-model")).to_have_value("qwen2.5:7b")
            panel.get_by_test_id("ai-write").click()
            result = panel.get_by_test_id("ai-result")
            expect(result).to_contain_text("AI inference — written by qwen2.5:7b")
            expect(result.get_by_test_id("ai-counts")).to_contain_text("2 sentences name their steps; 2 flagged")
            expect(result.get_by_test_id("ai-claim")).to_contain_text("originality")
            with page.expect_download() as dl:
                result.get_by_test_id("ai-markdown").click()
            text = open(dl.value.path(), encoding="utf-8").read()
            assert "AI inference" in text and "began with an intuition" in text
            assert "originality" not in text and "Nobody knows" not in text  # flagged ones are left out
            assert srv.ctx.ledger.record_count() == records  # nothing became a record
            sent = FakeModel.prompts[-1]["messages"][1]["content"]
            assert "Old notebook page" not in sent  # step bodies are never sent, only the story's sentences
            page.close()
    finally:
        model_server.shutdown()
