"""A throwaway git repository for tests (D-047), with fixed author and dates."""

from __future__ import annotations

import os
import subprocess


class GitRepo:
    def __init__(self, path):
        self.path = path
        path.mkdir()
        self.git("init", "-q", "-b", "main")
        self.n = 0

    def git(self, *args, date: str | None = None) -> str:
        env = {**os.environ, "GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@example.org",
               "GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": "a@example.org", "GIT_CONFIG_NOSYSTEM": "1",
               "HOME": str(self.path)}
        if date:
            env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
        out = subprocess.run(["git", "-C", str(self.path), *args], env=env, capture_output=True, text=True,
                             encoding="utf-8")
        assert out.returncode == 0, out.stderr
        return out.stdout.strip()

    def commit(self, message: str, date: str | None = None, tag: str | None = None) -> str:
        self.n += 1
        (self.path / "model.py").write_text(f"version = {self.n}\n", encoding="utf-8")
        self.git("add", "model.py")
        self.git("commit", "-q", "-m", message, date=date)
        if tag:
            self.git("tag", "-a", tag, "-m", tag, date=date)
        return self.git("rev-parse", "HEAD")
