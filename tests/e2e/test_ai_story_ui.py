"""D-050 in the browser, against a small stand-in for a local model server on 127.0.0.1: the
summary is labelled AI inference, comes in sections, flagged sentences are crossed out and left
out when saved, the text shows up while it is written, and Stop stops the model."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.demo import load_demo
from tests.e2e.server import LiveServer

pytestmark = pytest.mark.e2e
expect = pytest.importorskip("playwright.sync_api").expect

REPLY = ("## How it started\n"
         "- The research began with an intuition that flow speed saturates [#1].\n"
         "- A hypothesis grew out of it [#3, #1].\n\n"
         "## Where it stands now\n"
         "- This proves the author's originality [#1]. Nobody knows when this happened.")


class FakeModel(BaseHTTPRequestHandler):
    """Answers as Ollama does: the list of models, and the answer as server-sent events."""

    prompts: list = []
    delay = 0.0  # seconds between pieces
    loading = 0.0  # seconds before the first piece, as when a model is loaded the first time
    aborted = threading.Event()  # the app closed the connection before the answer was finished

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
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeModel.prompts.append(body)
        assert body["stream"] is True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        pieces = [REPLY[i:i + 12] for i in range(0, len(REPLY), 12)]
        if FakeModel.delay:
            pieces *= 20  # long enough to be stopped
        try:
            time.sleep(FakeModel.loading)
            self.wfile.write(b": loading\n\n")  # a comment line: tells whether the app still listens
            self.wfile.flush()
            for piece in pieces:
                self.wfile.write(f"data: {json.dumps({'choices': [{'delta': {'content': piece}}]})}\n\n".encode())
                self.wfile.flush()
                time.sleep(FakeModel.delay)
            self.wfile.write(b"data: [DONE]\n\n")
        except ConnectionError:  # broken pipe or reset (Linux, macOS), aborted (Windows)
            FakeModel.aborted.set()

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
            # The saved address arrives late (a slow machine): what the author typed must stay.
            page.route("**/api/ai", lambda route: (page.wait_for_timeout(600), route.continue_()))
            page.get_by_test_id("ai-open").click()
            panel = page.get_by_test_id("ai-panel")
            panel.get_by_test_id("ai-url").fill(f"http://127.0.0.1:{model_server.server_port}")
            page.wait_for_timeout(900)
            expect(panel.get_by_test_id("ai-url")).to_have_value(f"http://127.0.0.1:{model_server.server_port}")
            panel.get_by_test_id("ai-find").click()
            expect(panel.get_by_test_id("ai-model")).to_have_value("qwen2.5:7b")
            panel.get_by_test_id("ai-write").click()
            result = panel.get_by_test_id("ai-result")
            expect(result).to_contain_text("AI inference — written by qwen2.5:7b")
            expect(result.get_by_test_id("ai-counts")).to_contain_text("2 sentences name their steps; 2 flagged")
            expect(result.get_by_test_id("ai-claim")).to_contain_text("originality")
            sections = result.get_by_test_id("ai-section")
            expect(sections).to_have_count(2)
            expect(sections.first.locator("h4")).to_have_text("How it started")
            expect(sections.first.locator("li")).to_have_count(2)
            assert "[#" not in result.inner_text()  # the step numbers are buttons, not raw brackets
            sections.first.get_by_role("button", name="#3").click()
            expect(page.get_by_test_id("detail")).to_contain_text("Hypothesis H1")
            with page.expect_download() as dl:
                result.get_by_test_id("ai-markdown").click()
            text = open(dl.value.path(), encoding="utf-8").read()
            assert "AI inference" in text and "- The research began with an intuition" in text
            assert "## How it started" in text and "## Where it stands now" not in text  # nothing of it stood
            assert "originality" not in text and "Nobody knows" not in text  # flagged ones are left out
            assert srv.ctx.ledger.record_count() == records  # nothing became a record
            sent = FakeModel.prompts[-1]["messages"][1]["content"]
            assert "Old notebook page" not in sent  # step bodies are never sent, only the story's sentences
            page.close()
    finally:
        model_server.shutdown()


@pytest.mark.parametrize("loading", [0.0, 2.0], ids=["while-writing", "while-loading"])
def test_the_summary_shows_while_written_and_can_be_stopped(tmp_path, browser, loading):
    FakeModel.delay, FakeModel.loading, FakeModel.aborted = 0.15, loading, threading.Event()
    model_server = ThreadingHTTPServer(("127.0.0.1", 0), FakeModel)
    threading.Thread(target=model_server.serve_forever, daemon=True).start()
    try:
        with LiveServer(tmp_path) as srv:
            load_demo(srv.ctx)
            from app import preferences

            preferences.save(srv.ctx.settings.data_dir, ai_url=f"http://127.0.0.1:{model_server.server_port}",
                             ai_model="qwen2.5:7b")
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            page.goto(srv.url)
            page.get_by_test_id("tab-story").click()
            page.get_by_test_id("ai-jump").click()  # the button at the top opens the panel and goes there
            panel = page.get_by_test_id("ai-panel")
            # The saved model is found without a click: one click on Write is all it takes.
            expect(panel.get_by_test_id("ai-model")).to_have_value("qwen2.5:7b")
            panel.get_by_test_id("ai-write").click()
            if loading:
                expect(panel.get_by_test_id("ai-progress")).to_contain_text("Starting the model")
            else:
                expect(panel.get_by_test_id("ai-draft")).to_contain_text("The research began")
            expect(panel.get_by_test_id("ai-progress")).to_contain_text("so far")
            panel.get_by_test_id("ai-stop").click()
            expect(panel.get_by_test_id("ai-stopped")).to_be_visible()
            expect(panel.get_by_test_id("ai-draft")).to_have_count(0)
            expect(panel.get_by_test_id("ai-result")).to_have_count(0)
            assert FakeModel.aborted.wait(10)  # the model was told to stop, not left writing
            expect(panel.get_by_test_id("ai-write")).to_be_enabled()
            page.close()
    finally:
        FakeModel.delay = FakeModel.loading = 0.0
        model_server.shutdown()
