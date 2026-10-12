"""AC-22: non-local Host refused; writes without the session token get 403."""

from pathlib import Path

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


def test_the_page_scripts_are_sent_as_javascript_whatever_the_system_says(ctx, tmp_path, monkeypatch):
    """On Windows the mimetypes module reads file types from the registry, where other software
    often maps .js to text/plain; a browser then refuses to run the page's script and the page
    stays empty (seen on a friend's computer with v0.3.2)."""
    import starlette.responses

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<p>page</p>", encoding="utf-8")
    (dist / "assets" / "index-abc.js").write_text("console.log(1)", encoding="utf-8")
    (dist / "assets" / "index-abc.css").write_text("body{}", encoding="utf-8")
    ctx.settings.web_dist = dist
    monkeypatch.setattr(starlette.responses, "guess_type", lambda *a, **k: ("text/plain", None))  # as that registry
    with TestClient(create_app(ctx), base_url="http://127.0.0.1:8765") as cl:
        js = cl.get("/assets/index-abc.js")
        assert js.status_code == 200 and js.headers["content-type"].startswith("text/javascript")
        assert js.headers["x-content-type-options"] == "nosniff"  # which is why the type must be right
        assert cl.get("/assets/index-abc.css").headers["content-type"].startswith("text/css")


def test_the_built_page_says_what_to_do_if_it_cannot_start():
    """If the script still cannot run, the page shows what to do instead of staying empty."""
    page = (Path(__file__).resolve().parents[2] / "web" / "index.html").read_text(encoding="utf-8")
    root = page[page.index('<div id="root">'):page.index("<script")]
    assert "退出程序，再重新打开" in root and "Quit the app" in root


def test_server_binds_loopback_only():
    import inspect

    from app import main

    src = inspect.getsource(main)
    assert 'host="127.0.0.1"' in src
    assert "0.0.0.0" not in src.replace("never 0.0.0.0", "")
