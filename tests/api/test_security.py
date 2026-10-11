"""AC-22: non-local Host refused; writes without the session token get 403."""

from fastapi.testclient import TestClient

from app.main import create_app


def test_foreign_host_rejected(ctx):
    app = create_app(ctx)
    with TestClient(app, base_url="http://evil.example:8765") as cl:
        assert cl.get("/api/status").status_code == 403
    with TestClient(app, base_url="http://127.0.0.1:9999") as cl:
        assert cl.get("/api/status").status_code == 403
    with TestClient(app, base_url="http://localhost:8765") as cl:
        assert cl.get("/api/status").status_code == 200
    with TestClient(app, base_url="http://127.0.0.1:8765") as cl:
        assert cl.get("/api/status").status_code == 200


def test_writes_need_the_session_token(ctx):
    app = create_app(ctx)
    with TestClient(app, base_url="http://127.0.0.1:8765") as cl:
        assert cl.post("/api/identity", json={"author_label": "x"}).status_code == 403
        r = cl.post("/api/identity", json={"author_label": "x"}, headers={"X-RPROV-Token": "wrong"})
        assert r.status_code == 403
        r = cl.post("/api/identity", json={"author_label": "x"}, headers={"X-RPROV-Token": ctx.session_token})
        assert r.status_code == 200


def test_foreign_origin_rejected(client):
    r = client.post("/api/projects", json={"title": "x"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    r = client.get("/api/status", headers={"Origin": "http://evil.example"})
    assert r.status_code == 403
    r = client.post("/api/projects", json={"title": "x"}, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    r = client.post("/api/projects", json={"title": "x"}, headers={"Origin": "http://127.0.0.1:8765"})
    assert r.status_code == 200


def test_token_is_in_the_page_not_the_url(ctx, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text('<meta name="rprov-session-token" content="__RPROV_SESSION_TOKEN__">', encoding="utf-8")
    ctx.settings.web_dist = dist
    app = create_app(ctx)
    with TestClient(app, base_url="http://127.0.0.1:8765") as cl:
        page = cl.get("/")
        assert ctx.session_token in page.text
        assert ctx.session_token not in str(page.url)
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]


def test_server_binds_loopback_only():
    import inspect

    from app import main

    src = inspect.getsource(main)
    assert 'host="127.0.0.1"' in src
    assert "0.0.0.0" not in src.replace("never 0.0.0.0", "")
