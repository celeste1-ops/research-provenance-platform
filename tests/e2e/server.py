"""Run the real app (uvicorn + built UI) in a background thread for browser tests."""

from __future__ import annotations

import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn

from app.main import create_app
from tests.conftest import make_ctx

WEB = Path(__file__).resolve().parent.parent.parent / "web"


def ensure_web_built() -> Path:
    dist = WEB / "dist"
    if (dist / "index.html").exists():
        return dist
    npm = shutil.which("npm")
    if npm is None or not (WEB / "node_modules").exists():
        pytest.skip("web UI not built (run `make web`)")
    subprocess.run([npm, "run", "build"], cwd=WEB, check=True, capture_output=True)
    return dist


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LiveServer:
    def __init__(self, tmp_path: Path, **ctx_kwargs):
        dist = ensure_web_built()
        self.port = free_port()
        self.ctx = make_ctx(tmp_path, **ctx_kwargs)
        self.ctx.settings.port = self.port
        self.ctx.settings.web_dist = dist
        app = create_app(self.ctx)
        config = uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> LiveServer:
        self.thread.start()
        for _ in range(100):
            try:
                if httpx.get(self.url + "/api/status", timeout=0.5).status_code == 200:
                    return self
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        raise RuntimeError("server did not start")

    def __exit__(self, *exc) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)
        self.ctx.close()


def wait_for_step_count(page, text: str) -> None:
    """The top-bar counter refreshes just after a save; wait for the exact text."""
    import re

    page.locator("[data-testid=step-count]", has_text=re.compile(f"^{re.escape(text)}$")).wait_for()
