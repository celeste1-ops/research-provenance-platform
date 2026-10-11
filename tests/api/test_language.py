"""D-046: the server writes its own texts in the language the interface asks for; what the
author wrote is never translated."""

import json

from app import preferences


def test_server_texts_and_errors_follow_the_language_header(api, client):
    api.init()
    out = api.entry("Idea", "idea", body="kept as written")  # a title that is also a catalogue word
    rid = out["id"]
    en = client.get(f"/api/records/{rid}").json()
    zh = client.get(f"/api/records/{rid}", headers={"X-RPROV-Lang": "zh"}).json()
    assert en["verified"]["label"] == "Verified record" and zh["verified"]["label"] == "可验证记录"
    assert en["verified"]["node_type_label"] == "Idea" and zh["verified"]["node_type_label"] == "想法"
    assert zh["verified"]["title"] == "Idea"  # the author's title, not translated
    assert zh["verified"]["timestamps"]["tsa"]["label"] == "第三方签名时间证明"
    assert zh["author"]["label"] == "作者陈述"
    graph = client.get("/api/graph", headers={"X-RPROV-Lang": "zh"}).json()
    assert graph["nodes"][0]["title"] == "Idea"
    # Errors are translated where they leave the server.
    r = client.post("/api/projects", json={"title": " "}, headers={"X-RPROV-Lang": "zh"})
    assert r.status_code == 400 and r.json()["detail"] == "需要填项目名称"
    r = client.post("/api/projects", json={"title": " "})
    assert r.json()["detail"] == "project title is required"


def test_the_chosen_language_is_remembered_for_the_menu(client, ctx):
    assert client.get("/api/preferences").json() == {"language": None}
    assert client.post("/api/preferences", json={"language": "zh-CN"}).json() == {"language": "zh"}
    assert preferences.language(ctx.settings.data_dir) == "zh"
    saved = json.loads((ctx.settings.data_dir / "preferences.json").read_text(encoding="utf-8"))
    assert saved == {"language": "zh"}
    assert client.post("/api/preferences", json={"language": "fr"}).json() == {"language": "en"}


def _report(zip_bytes: bytes) -> tuple[str, str]:
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        names = z.namelist()
        read = lambda suffix: z.read(next(n for n in names if n.endswith(suffix))).decode()  # noqa: E731
        return read("report.html"), read("VERIFY.md")


def test_the_report_is_written_in_the_chosen_language(api, client):
    api.init()
    a = api.entry("Idea", "idea", body="kept as written", author_statement="来自去年的笔记")["id"]
    b = api.entry("Second step", "claim", body="x", relations=[{"to": a, "rel": "revises"}])["id"]
    body = {"title": "t", "records": {a: "full", b: "structure"}}

    html, md = _report(client.post("/api/export", json={**body, "language": "zh"}).content)
    assert '<html lang="zh-CN">' in html
    assert "能证明" in html and "是作者本人想出来的" in html  # PRD §2 in Chinese
    assert "第三方签名时间证明" in html and "比特币时间锚定" in html
    assert "这份记录不证明作者身份或原创性。" in html
    assert ">Idea<" in html and "来自去年的笔记" in html  # the author's words stay as written
    assert "修改自“Idea”" in html
    assert md.startswith("# 怎样核对这个证据包")

    # Without a language in the request: the interface's language; an explicit one wins.
    html, md = _report(client.post("/api/export", json=body, headers={"X-RPROV-Lang": "zh"}).content)
    assert '<html lang="zh-CN">' in html
    html, md = _report(client.post("/api/export", json={**body, "language": "en"},
                                   headers={"X-RPROV-Lang": "zh"}).content)
    assert '<html lang="en">' in html and "It can show" in html and "能证明" not in html
    assert md.startswith("# How to verify this evidence bundle")


def test_the_export_preview_follows_the_interface_language(api, client):
    api.init()
    a = api.entry("Idea", "idea", body="hello")["id"]
    prev = client.post("/api/export/preview", json={"records": {a: "structure"}},
                       headers={"X-RPROV-Lang": "zh"}).json()
    visible = {r["id"]: r["visible"] for r in prev["records"]}[a]
    assert "标题：Idea" in visible and "类型：想法" in visible
    assert any(w.startswith("“只公开结构”") for w in prev["warnings"])


def test_both_verify_guides_give_the_same_commands():
    import re
    from pathlib import Path

    templates = Path(__file__).resolve().parents[2] / "app" / "report" / "templates"

    def commands(name: str) -> list[str]:
        text = (templates / name).read_text(encoding="utf-8")
        blocks = re.findall(r"```bash\n(.*?)```", text, flags=re.S)
        return [re.sub(r"\s+#.*$", "", line).rstrip() for b in blocks for line in b.splitlines()]

    assert commands("VERIFY.md.j2") == commands("VERIFY.zh.md.j2")
    assert len(commands("VERIFY.md.j2")) > 10


def test_the_story_over_the_api_and_in_the_report(api, client):
    api.init()
    a = api.entry("Idea", "idea", body="hello", author_statement="because")["id"]
    zh = client.get(f"/api/narrative?project={api.project_id}", headers={"X-RPROV-Lang": "zh"}).json()
    para = zh["chapters"][0]["paragraphs"][0]
    assert para[0]["text"].endswith("作者记下了一个想法：“Idea”。") and para[0]["refs"][0]["id"] == a
    assert para[1] == {**para[1], "source": "author", "text": "作者当时写的原因：“because”"}
    html, _md = _report(client.post("/api/export", json={"title": "t", "records": {a: "full"},
                                                         "language": "en"}).content)
    assert 'id="narrative"' in html and "The research, step by step" in html
    assert f'href="#r-{a}"' in html
