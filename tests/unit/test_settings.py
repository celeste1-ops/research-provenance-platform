"""Settings read the environment when constructed, so `--port` set after import works."""

import os

from app.config import Settings


def test_port_and_providers_read_at_construction(monkeypatch):
    monkeypatch.setenv("RPROV_PORT", "8766")
    monkeypatch.setenv("RPROV_TSA", "mock")
    monkeypatch.setenv("RPROV_DEV", "1")
    s = Settings()
    assert s.port == 8766 and s.tsa == "mock" and s.dev is True
    assert "127.0.0.1:8766" in s.allowed_hosts()
    monkeypatch.delenv("RPROV_PORT")
    assert Settings().port == 8765
    assert os.environ.get("RPROV_PORT") is None


def test_main_port_flag_reaches_settings(monkeypatch):
    import sys

    from app import main as app_main

    seen = {}

    def fake_run(app, host, port, **kw):
        seen["host"], seen["port"] = host, port

    monkeypatch.setattr(sys, "argv", ["app", "--port", "8799"])
    monkeypatch.setattr(app_main, "app_factory", lambda: object())
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", fake_run)
    monkeypatch.setenv("RPROV_PORT", "8765")  # recorded, so the value main() writes is undone afterwards
    app_main.main()
    assert seen == {"host": "127.0.0.1", "port": 8799}
