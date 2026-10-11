"""D-047 over the API: look at a repository, start recording, see the progress, stop."""

from __future__ import annotations

import time

import pytest

from app.services.gitrepo import find_git
from tests.gitutil import GitRepo

pytestmark = pytest.mark.skipif(find_git() is None, reason="git is not installed")


def wait_idle(client, headers=None):
    for _ in range(100):
        status = client.get("/api/git", headers=headers or {}).json()
        if not any(s["busy"] for s in status["sources"]):
            return status
        time.sleep(0.05)
    raise AssertionError("still recording")


def test_record_a_repository_over_the_api(api, client, tmp_path):
    api.init()
    repo = GitRepo(tmp_path / "code")
    repo.commit("First model", date="2025-01-05T10:00:00+00:00", tag="v0.1")
    repo.commit("Second model", date="2025-02-05T10:00:00+00:00")

    assert client.get("/api/git").json() == {"git": True, "sources": []}
    info = client.post("/api/git/inspect", json={"path": str(repo.path)}).json()
    assert info["commits"] == 2 and info["tags"] == 1 and info["history_steps"] == 2 and info["branch"] == "main"

    r = client.post("/api/git", json={"path": info["path"], "branch": "main", "project_id": api.project_id,
                                      "history": True})
    assert r.status_code == 200, r.text
    [source] = wait_idle(client)["sources"]
    assert source["recorded"] == 2 and source["error"] is None and source["project_title"]
    titles = [n["title"] for n in client.get("/api/graph").json()["nodes"]]
    assert "code · v0.1" in titles and "code · 2025-02" in titles

    repo.commit("Third model")
    out = client.post("/api/git/check").json()
    assert out["recorded"] == 1 and out["sources"][0]["recorded"] == 3
    assert "Third model" in [n["title"] for n in client.get("/api/graph").json()["nodes"]]

    r = client.post("/api/git", json={"path": info["path"], "branch": "main", "project_id": api.project_id},
                    headers={"X-RPROV-Lang": "zh"})
    assert r.status_code == 400 and r.json()["detail"] == "这个仓库的这个分支已经在记录了"
    assert client.delete(f"/api/git/{source['id']}").json()["sources"] == []
    assert client.delete(f"/api/git/{source['id']}").status_code == 404


def test_bad_folders_are_explained(api, client, tmp_path):
    api.init()
    (tmp_path / "plain").mkdir()
    r = client.post("/api/git/inspect", json={"path": str(tmp_path / "plain")}, headers={"X-RPROV-Lang": "zh"})
    assert r.status_code == 400 and r.json()["detail"] == "这个文件夹不是 git 仓库"
    r = client.post("/api/git/inspect", json={"path": "not/absolute"})
    assert r.status_code == 400 and r.json()["detail"] == "choose a full folder path"
