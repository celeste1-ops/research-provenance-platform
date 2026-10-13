"""Reading a git repository (DECISIONS D-047, D-060).

The app runs the ``git`` program the author already has. Reading uses only local commands:
rev-parse, symbolic-ref, for-each-ref, log, merge-base, remote get-url, ls-tree and cat-file.
Three things go over the network, each only for what the author set up or asked for:

* a repository recorded from its address (GitHub and the like) is downloaded once as a bare
  copy in the data folder (``clone --mirror``) and brought up to date with ``fetch``; this only
  downloads, the author's records are not sent;
* putting an evidence bundle into a repository commits it there and, if asked, ``push``es it.

Only https and ssh addresses are used (``GIT_ALLOW_PROTOCOL``), never local paths or helper
transports, and git never asks for a password in a terminal: it uses the sign-in the computer
already has. A date that git reports is what the author's computer wrote and can be changed
later: callers show it only as the author's statement (PRD §7 "外部引用").
"""

from __future__ import annotations

import io
import os
import re
import shutil
import stat
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

TIMEOUT_SECONDS = 60
NETWORK_TIMEOUT_SECONDS = 900  # downloading a large repository takes a while
ALLOWED_PROTOCOLS = "https:ssh"
REMOTE_SCHEMES = ("https", "ssh")
# Hosts whose web addresses (…/owner/repo/tree/main) are cut back to the repository itself.
_WEB_HOSTS = ("github.com", "gitee.com", "codeberg.org")
_SCP_LIKE = re.compile(r"[A-Za-z0-9._-]+@[A-Za-z0-9.-]+:[A-Za-z0-9._~/-]+")
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

    def fetch(self) -> None:
        """Bring a downloaded copy up to date (repositories recorded from their address)."""
        _run_network(self.git, ["fetch", "--prune", "--quiet", "origin"], cwd=self.path, timeout=300)

    def commit_paths(self, paths: list[str], message: str) -> str:
        """Commit only these paths (other changes in the folder stay as they are). Returns the commit."""
        self._run("add", "--", *paths)
        out = self._run("commit", "--quiet", "--only", "-m", message, "--", *paths, check=False)
        if out.returncode != 0:
            text = (out.stderr + out.stdout).decode("utf-8", "replace")
            if "nothing to commit" in text or "no changes added" in text:
                raise GitError("nothing changed: this evidence bundle is already in the repository")
            raise GitError(_friendly(text))
        return self._text("rev-parse", "HEAD").strip()

    def push(self) -> None:
        """Push the current branch to the branch it follows on GitHub (or wherever origin is)."""
        _run_network(self.git, ["push", "--quiet"], cwd=self.path, timeout=300)

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


def normalize_remote(text: str) -> str | None:
    """The git address in ``text``, or None if it is not one the app downloads from: https://…
    or git@host:owner/repo. "github.com/owner/repo" means https; a GitHub page address such as
    …/owner/repo/tree/main is cut back to the repository."""
    t = (text or "").strip().strip('"').strip()
    if not t or t.startswith("-"):
        return None
    if _SCP_LIKE.fullmatch(t):
        return t
    if re.match(r"(www\.)?(" + "|".join(re.escape(h) for h in _WEB_HOSTS) + r"|gitlab\.com|bitbucket\.org)/", t, re.I):
        t = "https://" + t
    parts = urlsplit(t)
    if parts.scheme not in REMOTE_SCHEMES or not parts.hostname or parts.path in ("", "/"):
        return None
    host = parts.hostname.lower().removeprefix("www.")
    if parts.scheme == "https" and host in _WEB_HOSTS:
        segments = [x for x in parts.path.split("/") if x]
        if len(segments) < 2:
            return None
        return urlunsplit(("https", parts.netloc.removeprefix("www."), "/" + "/".join(segments[:2]), "", ""))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def repo_name(url: str) -> str:
    """'https://github.com/owner/fsf-solver.git' -> 'fsf-solver'."""
    tail = re.split(r"[/:]", url.rstrip("/"))[-1]
    return tail.removesuffix(".git") or "repository"


def _network_env() -> dict:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ALLOW_PROTOCOL": ALLOWED_PROTOCOLS, "LC_ALL": "C"}
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")  # never wait for a password or a host question
    return env


def _friendly(stderr: str) -> str:
    """git's own words, turned into what to do about them."""
    low = stderr.lower()
    if any(k in low for k in ("authentication failed", "could not read username", "repository not found",
                              "permission denied", "terminal prompts disabled", "403")):
        return ("could not get in: check the address; for a private repository, sign in once on this computer "
                "(GitHub Desktop, or git clone in a terminal), then try again")
    if any(k in low for k in ("could not resolve host", "unable to access", "network is unreachable",
                              "connection timed out", "failed to connect")):
        return "could not reach the server: check the internet connection, then try again"
    if "please tell me who you are" in low or "user.email" in low:
        return "git does not know your name and e-mail yet: set them once (git config --global user.name / user.email)"
    if "no upstream" in low or "has no upstream branch" in low:
        return "this branch is not connected to GitHub yet: push it once yourself, then the app can push too"
    if "rejected" in low or "non-fast-forward" in low or "fetch first" in low:
        return "GitHub has newer commits than this computer: pull them first, then push again"
    lines = stderr.strip().splitlines()
    return lines[-1] if lines else "git failed"


def _run_network(git: str, args: list[str], cwd: Path | None = None,
                 timeout: int = NETWORK_TIMEOUT_SECONDS) -> subprocess.CompletedProcess:
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    base = [git, *_SAFE] + (["-C", str(cwd)] if cwd else [])
    try:
        out = subprocess.run([*base, *args], capture_output=True, env=_network_env(), timeout=timeout,
                             stdin=subprocess.DEVNULL, creationflags=flags)
    except subprocess.TimeoutExpired:
        raise GitError("git took too long (the repository may be very large, or the connection slow)") from None
    except OSError as exc:
        raise GitError(f"could not run git ({exc.strerror or exc})") from None
    if out.returncode != 0:
        raise GitError(_friendly(out.stderr.decode("utf-8", "replace")))
    return out


def remote_branches(url: str, git: str | None = None) -> tuple[list[str], str | None]:
    """The branches of a repository at ``url`` and its default branch, without downloading it."""
    git = git or find_git()
    if git is None:
        raise GitError("git is not installed on this computer")
    text = _run_network(git, ["ls-remote", "--symref", "--", url], timeout=120).stdout.decode("utf-8", "replace")
    branches, default = [], None
    for line in text.splitlines():
        if line.startswith("ref: refs/heads/") and line.endswith("\tHEAD"):
            default = line[len("ref: refs/heads/"):].split("\t")[0]
        else:
            _sha, _, ref = line.partition("\t")
            if ref.startswith("refs/heads/"):
                branches.append(ref[len("refs/heads/"):])
    return branches, default if default in branches else (branches[0] if branches else None)


def clone_mirror(url: str, target: Path, git: str | None = None) -> None:
    """A bare copy of every branch and tag: no working files, so no checkout filters run."""
    git = git or find_git()
    if git is None:
        raise GitError("git is not installed on this computer")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        _run_network(git, ["clone", "--mirror", "--quiet", "--", url, str(target)])
    except GitError:
        remove_copy(target)  # half a copy (it took too long): start again next time
        raise


def remove_copy(path: Path) -> None:
    """Delete a downloaded copy. git marks its pack files read-only, which keeps Windows from
    deleting them, so the mark is taken off first."""
    def writable(func, name, _exc):
        os.chmod(name, stat.S_IWRITE)
        func(name)

    try:
        shutil.rmtree(path, onexc=writable)
    except OSError:
        pass  # still in use (Windows): it is only a copy, and is not used any more


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
