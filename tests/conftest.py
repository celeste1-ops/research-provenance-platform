from __future__ import annotations

import json
import os

import pytest

from app.config import Settings
from app.services.context import AppContext
from app.services.keystore import MemoryKeyStore
from provenance_core.providers.mock import MockProvider

BASE_URL = "http://127.0.0.1:8765"


def pytest_collection_modifyitems(config, items):
    if os.environ.get("RPROV_NETWORK_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="needs real FreeTSA / OpenTimestamps; run `make test-network` on the Mac")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)


def make_ctx(tmp_path, *, tsa=None, btc=None, keystore=None) -> AppContext:
    # device="Mac": interface wording is fixed in tests, whatever system they run on.
    settings = Settings(data_dir=tmp_path / "rprov", port=8765, tsa="mock", btc="mock", keystore="memory",
                        device="Mac")
    providers = {
        "tsa": tsa if tsa is not None else MockProvider("tsa"),
        "btc": btc if btc is not None else MockProvider("btc"),
    }
    return AppContext.create(settings, keystore=keystore or MemoryKeyStore(), providers=providers)


@pytest.fixture(autouse=True)
def _fresh_location_scan():
    """Each test sees its own (possibly monkeypatched) sync folders, not a cached scan."""
    from app.services import locations

    locations.clear_cache()
    yield
    locations.clear_cache()


@pytest.fixture
def ctx(tmp_path):
    c = make_ctx(tmp_path)
    yield c
    c.close()


class Api:
    """Small helper around the TestClient for creating records."""

    def __init__(self, client, ctx):
        self.client = client
        self.ctx = ctx
        self.project_id = None

    def init(self, author="Test Author", project="FSF"):
        r = self.client.post("/api/identity", json={"author_label": author})
        assert r.status_code == 200, r.text
        r = self.client.post("/api/projects", json={"title": project})
        assert r.status_code == 200, r.text
        self.project_id = r.json()["id"]
        return self

    def entry(self, title="Entry", node_type="note", body=None, files=None, expect=200, **fields):
        data = {"project_id": self.project_id, "node_type": node_type, "title": title}
        if body is not None:
            data["body"] = body
        if "relations" in fields:
            fields["relations"] = json.dumps(fields["relations"])
        if "import_references" in fields and isinstance(fields["import_references"], list):
            fields["import_references"] = json.dumps(fields["import_references"])
        for k, v in fields.items():
            data[k] = "true" if v is True else ("false" if v is False else v)
        multipart = [("files", (name, content, "application/octet-stream")) for name, content in (files or [])]
        r = self.client.post("/api/entries", data=data, files=multipart or None)
        assert r.status_code == expect, r.text
        return r.json()


@pytest.fixture
def client(ctx):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(ctx), base_url=BASE_URL) as cl:
        cl.headers["X-RPROV-Token"] = ctx.session_token
        yield cl


@pytest.fixture
def api(client, ctx):
    return Api(client, ctx)
