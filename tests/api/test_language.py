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
