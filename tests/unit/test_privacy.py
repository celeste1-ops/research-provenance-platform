"""AC-21: only `providers` may touch the network, and a complete recording flow
sends nothing but hash commitments and protocol data.

1. Static: no module outside provenance_core/providers imports a network library.
2. Dynamic: run a full flow (identity, entries with body/attachments/statements,
   link, statement, retraction, refresh, export) through the HTTP API with the real
   RFC 3161 provider behind a capturing transport, and with sockets blocked
   everywhere else. No captured byte may contain the body, a title, a note, an
   attachment, or their unsalted SHA-256 hashes.
"""

from __future__ import annotations

import ast
import hashlib
import json
import socket
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from rfc3161_client._rust import parse_timestamp_request

from app.main import create_app
from provenance_core.providers.mock import MockProvider, build_mock_tsr, mock_tsa_root
from provenance_core.providers.rfc3161 import Rfc3161Provider
from tests.conftest import Api, make_ctx

ROOT = Path(__file__).resolve().parent.parent.parent
NETWORK_MODULES = {"httpx", "requests", "urllib3", "aiohttp", "http.client", "urllib.request", "socket",
                   "ftplib", "smtplib", "websockets", "pycurl"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.add(node.module)
            out.update(f"{node.module}.{a.name}" for a in node.names)
    return out


def test_only_providers_import_network_libraries():
    offenders = []
    sources = list((ROOT / "core" / "provenance_core").rglob("*.py")) + list((ROOT / "app").rglob("*.py"))
    assert len(sources) > 20
    for path in sources:
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith("core/provenance_core/providers/"):
            continue
        for mod in _imports(path):
            if any(mod == n or mod.startswith(n + ".") for n in NETWORK_MODULES):
                offenders.append(f"{rel}: {mod}")
    assert offenders == []


def test_generated_verify_py_has_no_network_imports():
    from app.services.export import verify_py_source

    tree = ast.parse(verify_py_source())
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
    assert not {m for m in mods if m.split(".")[0] in {"httpx", "requests", "urllib3", "socket", "aiohttp"}}


SECRETS = {
    "body": "The unpublished conjecture: friction scales with the cube of velocity.\n",
    "title": "Confidential experiment Alpha-7",
    "statement": "Because the reviewer from lab Zeta suggested it",
    "attachment": b"col_a,col_b\n4.2,7.7\nsecret-measurement-9931\n",
    "link_note": "only realised after the conference dinner",
    "later_note": "parameter k was taken from the unpublished thesis",
    "reason": "contaminated sample batch 12",
    "project": "Project Nightingale",
}


@pytest.fixture
def capture(monkeypatch):
    sent: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(str(request.url).encode() + b"\n" + b"\n".join(
            f"{k}: {v}".encode() for k, v in request.headers.items()) + b"\n" + request.content)
        req = parse_timestamp_request(request.content)
        tsr = build_mock_tsr(bytes(req.message_imprint.message), datetime.now(UTC), req.nonce)
        return httpx.Response(200, content=tsr)

    real_connect = socket.socket.connect

    def guarded_connect(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise AssertionError(f"unexpected network connection to {address}")
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    return sent, httpx.MockTransport(handler)


def test_full_flow_sends_only_hash_commitments(tmp_path, capture):
    sent, transport = capture
    tsa = Rfc3161Provider("https://tsa.example/tsr", roots=[mock_tsa_root()], name="capturing-tsa",
                          transport=transport)
    ctx = make_ctx(tmp_path, tsa=tsa, btc=MockProvider("btc"))
    record_ids = []
    with TestClient(create_app(ctx), base_url="http://127.0.0.1:8765") as cl:
        cl.headers["X-RPROV-Token"] = ctx.session_token
        api = Api(cl, ctx).init(author="Private Person", project=SECRETS["project"])
        a = api.entry(SECRETS["title"], "experiment", body=SECRETS["body"],
                      files=[("measurements.csv", SECRETS["attachment"])], author_statement=SECRETS["statement"])
        b = api.entry("Second", "claim", body="x", relations=[{"to": a["id"], "rel": "uses"}],
                      import_claimed_date="2025-11", import_level="L2", import_references=["https://doi.org/10.1/x"])
        record_ids += [a["id"], b["id"]]
        record_ids.append(cl.post("/api/links", json={"from": b["id"], "to": a["id"], "rel": "revises",
                                                      "statement": SECRETS["link_note"]}).json()["id"])
        record_ids.append(cl.post("/api/statements", json={"target": a["id"], "text": SECRETS["later_note"]}).json()["id"])
        record_ids.append(cl.post("/api/retractions", json={"target": b["id"], "reason": SECRETS["reason"]}).json()["id"])
        assert cl.post("/api/anchors/refresh").status_code == 200
        assert cl.post("/api/export", json={"title": "x", "default": "full"}).status_code == 200
        assert cl.post("/api/verify/all").json()["ok"] is True
        all_ids = [r["id"] for r in cl.get("/api/timeline").json()]
    ctx.close()

    assert len(sent) == len(all_ids)  # one RFC 3161 request per record, nothing else
    wire = b"\n".join(sent)
    forbidden: list[bytes] = []
    for value in SECRETS.values():
        data = value if isinstance(value, bytes) else value.encode()
        digest = hashlib.sha256(data).digest()
        forbidden += [data, digest, digest.hex().encode()]
        if isinstance(value, str):  # the body is stored LF-normalized; check that form too
            norm = value.replace("\r\n", "\n").encode()
            forbidden += [hashlib.sha256(norm).digest(), hashlib.sha256(norm).hexdigest().encode()]
    for needle in forbidden:
        assert needle not in wire, needle[:40]
    for word in ("Confidential", "Nightingale", "conjecture", "Zeta", "Private Person", "measurements.csv"):
        assert word.encode() not in wire
    # What was sent: exactly each record ID as the SHA-256 message imprint.
    imprints = []
    for blob in sent:
        req = parse_timestamp_request(_body(blob))
        imprints.append(bytes(req.message_imprint.message).hex())
    assert sorted(imprints) == sorted(all_ids)
    assert set(record_ids) <= set(imprints)


def _body(blob: bytes) -> bytes:
    # The captured blob is "URL\nheaders...\n<DER body>"; the DER body starts with a SEQUENCE tag.
    idx = blob.find(b"\n0")
    while idx != -1:
        candidate = blob[idx + 1 :]
        try:
            parse_timestamp_request(candidate)
            return candidate
        except Exception:  # noqa: BLE001
            idx = blob.find(b"\n0", idx + 1)
    raise AssertionError("no timestamp request found in captured bytes")


def test_bundle_json_has_no_content_for_existence_records(tmp_path):
    from tests.sample import make_sample

    s = make_sample(tmp_path)
    meta = json.loads(s.files["bundle.json"])
    assert "Old notebook" not in json.dumps(meta)
