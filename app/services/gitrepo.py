"""Reading a local git repository (DECISIONS D-047).

The app runs the ``git`` program the author already has, and only commands that read the
local repository: rev-parse, symbolic-ref, for-each-ref, log, merge-base, remote get-url,
ls-tree and cat-file. Nothing here fetches, pulls or pushes, so nothing goes over the network. A date
that git reports is what the author's computer wrote and can be changed later: callers show
it only as the author's statement (PRD §7 "外部引用").
"""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

TIMEOUT_SECONDS = 60
_SEP, _END = "\x1f", "\x1e"
_SHA = re.compile(r"[0-9a-f]{40}([0-9a-f]{24})?")
# Never run a repository's own helper programs while reading it.
_SAFE = ["-c", "core.fsmonitor=false", "-c", "core.quotepath=off", "-c", "log.showSignature=false"]


class GitError(Exception):
    pass


@dataclass(frozen=True)
class Commit:
    sha: str
    date: str  # author date as git reports it (ISO 8601 with offset) — the author's statement
    subject: str
    body: str  # the rest of the message, may be empty


def _xcode_tools_installed() -> bool:
    try:
        return subprocess.run(["xcode-select", "-p"], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def find_git() -> str | None:
    """The git program, or None. Apps started from the Dock or Start menu do not get the
    shell's PATH, so the usual install places are tried too. On a Mac without the developer
    tools /usr/bin/git only offers to install them, so it does not count."""
    candidates: list[str] = []
    if sys.platform == "darwin":
        candidates += ["/opt/homebrew/bin/git", "/usr/local/bin/git"]
    found = shutil.which("git")
    if found:
        candidates.append(found)
    if sys.platform == "win32":
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                     os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
            if base:
                candidates.append(os.path.join(base, "Git", "cmd", "git.exe"))
    for c in candidates:
        if not os.path.isfile(c):
            continue
        if sys.platform == "darwin" and c == "/usr/bin/git" and not _xcode_tools_installed():
            continue
        return c
    return None


class Repo:
    """One local repository, read through ``git -C <folder>``."""

    def __init__(self, path: str | Path, git: str | None = None):
        self.git = git or find_git()
        if self.git is None:
            raise GitError("git is not installed on this computer")
        self.path = Path(path)

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"}
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0  # no console flashing up
        try:
            out = subprocess.run([self.git, *_SAFE, "-C", str(self.path), *args], capture_output=True, env=env,
                                 timeout=TIMEOUT_SECONDS, stdin=subprocess.DEVNULL, creationflags=flags)
        except subprocess.TimeoutExpired:
            raise GitError("git took too long to answer") from None
        except OSError as exc:
            raise GitError(f"could not run git ({exc.strerror or exc})") from None
        if check and out.returncode != 0:
            lines = out.stderr.decode("utf-8", "replace").strip().splitlines()
            raise GitError(lines[-1] if lines else f"git {args[0]} failed")
        return out

    def _text(self, *args: str) -> str:
        return self._run(*args).stdout.decode("utf-8", "replace")

    # ------------------------------------------------------------ what the repository is

    def toplevel(self) -> Path:
        out = self._run("rev-parse", "--show-toplevel", check=False)
        if out.returncode != 0:
            raise GitError("this folder is not a git repository")
        return Path(out.stdout.decode("utf-8", "replace").strip())

    def branches(self) -> list[str]:
        return [b for b in self._text("for-each-ref", "--format=%(refname:short)", "refs/heads").split("\n") if b]

    def current_branch(self) -> str | None:
        out = self._run("symbolic-ref", "--quiet", "--short", "HEAD", check=False)
        if out.returncode != 0:
            return None  # detached HEAD
        return out.stdout.decode("utf-8", "replace").strip() or None

    def head(self, branch: str) -> str | None:
        """The newest commit of a local branch (None if the branch has no commits or is gone)."""
        if branch not in self.branches():
            return None
        out = self._run("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}^{{commit}}", check=False)
        sha = out.stdout.decode().strip()
        return sha if out.returncode == 0 and _SHA.fullmatch(sha) else None

    def remote_url(self) -> str | None:
        """Where the repository says it lives ('origin'), without any password or token in it."""
        out = self._run("remote", "get-url", "origin", check=False)
        url = out.stdout.decode("utf-8", "replace").strip()
        return strip_credentials(url) if out.returncode == 0 and url else None

    def tags(self) -> dict[str, list[str]]:
        """commit -> tag names (annotated tags point at their commit)."""
        fmt = f"%(objectname){_SEP}%(*objectname){_SEP}%(refname:short)"
        out: dict[str, list[str]] = {}
        for line in self._text("for-each-ref", f"--format={fmt}", "refs/tags").split("\n"):
            if not line:
                continue
            obj, peeled, name = line.split(_SEP)
            out.setdefault(peeled or obj, []).append(name)
        return out

    # ------------------------------------------------------------ commits

    def commits(self, tip: str, since: str | None = None) -> list[Commit]:
        """Commits on the first-parent line up to ``tip``, oldest first (after ``since`` if given)."""
        _check_sha(tip)
        rev = [tip] if since is None else [tip, "--not", _check_sha(since)]
        text = self._text("log", "--first-parent", "--reverse", f"--format=%H{_SEP}%aI{_SEP}%B{_END}", *rev, "--")
        commits = []
        for chunk in text.split(_END):
            chunk = chunk.lstrip("\n")
            if not chunk:
                continue
            sha, date, message = chunk.split(_SEP, 2)
            subject, _, body = message.strip().partition("\n")
            commits.append(Commit(sha, date, subject.strip(), body.strip()))
        return commits

    def is_ancestor(self, older: str, newer: str) -> bool:
        return self._run("merge-base", "--is-ancestor", _check_sha(older), _check_sha(newer),
                         check=False).returncode == 0

    def archive(self, sha: str, limit: int) -> bytes | None:
        """The files of one commit as a zip, exactly as committed, or None if larger than ``limit``.

        Not ``git archive``: that converts line endings by this computer's settings (Git for
        Windows turns LF into CRLF) and runs filter programs such as Git LFS, which may go over
        the network. Here every file is read as stored, so the same commit always gives the
        same bytes, on any computer, and no other program runs."""
        _check_sha(sha)
        entries = []
        for item in self._run("ls-tree", "-r", "-z", "--full-tree", sha).stdout.split(b"\0"):
            if not item:
                continue
            meta, path = item.split(b"\t", 1)
            mode, kind, obj = meta.split(b" ")
            if kind == b"blob":  # submodules (commits of other repositories) are not files here
                entries.append((mode, obj, path.decode("utf-8", "replace")))
        out = io.BytesIO()
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        proc = subprocess.Popen([self.git, *_SAFE, "-C", str(self.path), "cat-file", "--batch"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"}, creationflags=flags)
        assert proc.stdin is not None and proc.stdout is not None
        total = 0
        try:
            with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
                for mode, obj, path in entries:
                    proc.stdin.write(obj + b"\n")
                    proc.stdin.flush()
                    header = proc.stdout.readline().split()
                    if len(header) != 3 or header[1] != b"blob":
                        raise GitError("could not read a file of the commit")
                    size = int(header[2])
                    total += size
                    if total > 4 * limit:  # far too big to compress below the limit
                        return None
                    data = proc.stdout.read(size)
                    proc.stdout.read(1)  # the newline after each object
                    info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))  # same commit, same bytes
                    info.external_attr = (0o755 if mode == b"100755" else 0o644) << 16
                    info.compress_type = zipfile.ZIP_DEFLATED
                    z.writestr(info, data)
        finally:
            proc.stdin.close()
            proc.kill()
            proc.wait(timeout=TIMEOUT_SECONDS)
            proc.stdout.close()
        data = out.getvalue()
        return data if len(data) <= limit else None


def _check_sha(sha: str) -> str:
    if not _SHA.fullmatch(sha or ""):
        raise GitError("not a full commit hash")
    return sha


def strip_credentials(url: str) -> str:
    """https://user:token@host/x.git -> https://host/x.git (scp-style git@host:x stays as it is)."""
    parts = urlsplit(url)
    if parts.scheme in ("http", "https", "ssh", "git") and "@" in parts.netloc:
        host = parts.netloc.rsplit("@", 1)[1]
        user = parts.netloc.rsplit("@", 1)[0]
        if parts.scheme == "ssh" and ":" not in user:
            return url  # ssh://git@host/… names an account, not a secret
        return urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment))
    return url
