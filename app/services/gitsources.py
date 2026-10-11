"""Recording a local git repository automatically (DECISIONS D-047).

The author points the app at a repository folder on this computer and picks a branch and a
project. From then on every new commit on that branch becomes a "code" step — title and text
from the commit message, the commit as its external reference, "revises" the previous commit's
step — and gets its date stamps like any other step. Only local git commands are used
(app/services/gitrepo.py); nothing is fetched and nothing extra leaves the computer.

The history before that point can be added once, grouped into a few steps (one per tag, or
per month when there are no tags). Those steps are older material added now: the dates git
reports are kept as the author's claimed date (L1), never as a verified time. The same goes
for a commit made more than a day before it was recorded (the app was closed).

The list of repositories lives in ``<data folder>/git_sources.json`` (each space has its own).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from app.config import MAX_UPLOAD_BYTES
from app.i18n import tr_message
from app.services.gitrepo import Commit, GitError, Repo, find_git
from app.services.ledger import EntryInput, LedgerError, UploadedFile
from provenance_core.jcs import parse_json_strict

log = logging.getLogger("rprov.git")

FILE = "git_sources.json"
MAX_SEPARATE = 20  # more new commits than this at once become one step listing them
MAX_MONTH_STEPS = 48  # longer histories without tags are grouped by year
TITLE_LIMIT = 200


@dataclass
class Batch:
    label: str  # tag name, YYYY-MM or YYYY
    commits: list[Commit] = field(default_factory=list)
    precision: str = "month"

    @property
    def claimed_date(self) -> str:
        day = self.commits[-1].date[:10]
        return {"day": day, "month": day[:7], "year": day[:4]}[self.precision]


def history_batches(commits: list[Commit], tags: dict[str, list[str]]) -> list[Batch]:
    """Oldest first: a batch ends at every tagged commit; untagged stretches are cut per month
    (per year when that would make more than MAX_MONTH_STEPS steps)."""

    def cut(period: int) -> list[Batch]:
        out: list[Batch] = []
        cur: Batch | None = None
        for c in commits:
            key = c.date[:period]
            if cur is not None and cur.label != key:
                out.append(cur)
                cur = None
            if cur is None:
                cur = Batch(key, precision="month" if period == 7 else "year")
            cur.commits.append(c)
            if c.sha in tags:  # a tag closes the batch and names it
                cur.label, cur.precision = sorted(tags[c.sha])[0], "day"
                out.append(cur)
                cur = None
        if cur is not None:
            out.append(cur)
        return out

    batches = cut(7)
    if sum(1 for b in batches if b.precision == "month") > MAX_MONTH_STEPS:
        batches = cut(4)
    return batches


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today() -> str:
    return datetime.now().astimezone().date().isoformat()


class GitSources:
    """The repositories one space records, and the job that records their new commits."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.file = Path(ctx.settings.data_dir) / FILE
        self._lock = threading.RLock()  # the list
        self._recording = threading.Lock()  # one recording run at a time
        self._busy: dict[str, dict] = {}

    # ------------------------------------------------------------ the list

    def _load(self) -> list[dict]:
        try:
            data = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [s for s in data.get("sources", []) if isinstance(s, dict) and s.get("id")]

    def _save(self, sources: list[dict]) -> None:
        tmp = self.file.with_name(FILE + ".tmp")
        tmp.write_text(json.dumps({"sources": sources}, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.file)

    def _update(self, source_id: str, **changes) -> dict | None:
        with self._lock:
            sources = self._load()
            for s in sources:
                if s["id"] == source_id:
                    s.update(changes)
                    self._save(sources)
                    return s
        return None

    def sources(self) -> list[dict]:
        projects = {p.id: p.title for p in self.ctx.ledger.projects()}
        out = []
        for s in self._load():
            out.append({**s, "project_title": projects.get(s.get("project_id"), ""),
                        "error": tr_message(s["error"]) if s.get("error") else None,
                        "busy": self._busy.get(s["id"])})
        return out

    def has_sources(self) -> bool:
        return self.file.exists() and bool(self._load())

    def status(self) -> dict:
        return {"git": find_git() is not None, "sources": self.sources()}

    # ------------------------------------------------------------ adding and removing

    @staticmethod
    def _folder(path: str) -> Path:
        raw = (path or "").strip().strip('"')
        folder = Path(os.path.expanduser(raw)) if raw else None
        if folder is None or not folder.is_absolute():
            raise GitError("choose a full folder path")
        if not folder.is_dir():
            raise GitError("that folder does not exist")
        return folder

    def inspect(self, path: str) -> dict:
        """What the add dialog shows before anything is recorded."""
        repo = Repo(self._folder(path))
        top = repo.toplevel()
        repo = Repo(top, repo.git)
        branches = repo.branches()
        current = repo.current_branch()
        branch = current if current in branches else (branches[0] if branches else None)
        commits = repo.commits(repo.head(branch)) if branch and repo.head(branch) else []
        tags = repo.tags()
        return {
            "path": str(top), "name": top.name, "branches": branches, "branch": branch,
            "remote_url": repo.remote_url(), "commits": len(commits),
            "tags": sum(1 for c in commits if c.sha in tags),
            "first_date": commits[0].date[:10] if commits else None,
            "last_date": commits[-1].date[:10] if commits else None,
            "history_steps": len(history_batches(commits, tags)) if commits else 0,
            "already": any(Path(s["path"]) == top and s["branch"] == branch for s in self._load()),
        }

    def add(self, path: str, branch: str, project_id: str, *, history: bool, keep_code: bool,
            background: bool = True) -> dict:
        repo = Repo(self._folder(path))
        top = repo.toplevel()
        repo = Repo(top, repo.git)
        if branch not in repo.branches():
            raise GitError("there is no such branch")
        head = repo.head(branch)
        if head is None:
            raise GitError("this branch has no commits yet")
        if project_id not in {p.id for p in self.ctx.ledger.projects()}:
            raise LedgerError("unknown project")
        with self._lock:
            sources = self._load()
            if any(Path(s["path"]) == top and s["branch"] == branch for s in sources):
                raise GitError("this branch of this repository is already being recorded")
            source = {
                "id": uuid.uuid4().hex, "path": str(top), "name": top.name, "branch": branch,
                "project_id": project_id, "repo_url": repo.remote_url() or str(top), "keep_code": bool(keep_code),
                "added": _now(), "last_commit": None, "last_entry": None, "recorded": 0,
                "checked": None, "error": None,
            }
            sources.append(source)
            self._save(sources)
        self._busy[source["id"]] = {"done": 0, "total": None}
        job = threading.Thread(target=self._first_run, args=(source["id"], history), name="rprov-git-first",
                               daemon=True)
        if background:
            job.start()
        else:
            job.run()
        return source

    def remove(self, source_id: str) -> None:
        """Stop recording a repository; the steps already recorded stay, as every step does."""
        with self._lock:
            sources = self._load()
            kept = [s for s in sources if s["id"] != source_id]
            if len(kept) == len(sources):
                raise LedgerError("no such record")
            self._save(kept)

    # ------------------------------------------------------------ recording

    def _first_run(self, source_id: str, history: bool) -> None:
        with self._recording:
            try:
                source = next(s for s in self._load() if s["id"] == source_id)
                repo = Repo(source["path"])
                head = repo.head(source["branch"])
                if head is None:
                    raise GitError("this branch has no commits yet")
                commits = repo.commits(head)
                if not history:  # start from where the code stands now
                    self._busy[source_id] = {"done": 0, "total": 1}
                    self._record_commit(source, repo, commits[-1])
                    batches = []
                else:
                    batches = history_batches(commits, repo.tags())
                    self._busy[source_id] = {"done": 0, "total": len(batches)}
                for i, batch in enumerate(batches):
                    self._record_batch(source, repo, batch)
                    self._busy[source_id] = {"done": i + 1, "total": len(batches)}
                self._update(source_id, checked=_now(), error=None)
            except (GitError, LedgerError, OSError) as exc:
                log.warning("git first run failed: %s", exc)
                self._update(source_id, error=str(exc), checked=_now())
            except Exception:  # noqa: BLE001
                log.exception("git first run failed")
                self._update(source_id, error="internal error (see the app log)", checked=_now())
            finally:
                self._busy.pop(source_id, None)

    def check(self) -> dict:
        """Record new commits on every repository (the background job runs this every minute)."""
        if not self._recording.acquire(blocking=False):
            return {"recorded": 0, "busy": True}
        try:
            recorded = 0
            for source in self._load():
                if self._busy.get(source["id"]):
                    continue
                try:
                    recorded += self._check_one(source)
                    self._update(source["id"], checked=_now(), error=None)
                except (GitError, LedgerError, OSError) as exc:
                    self._update(source["id"], checked=_now(), error=str(exc))
                except Exception:  # noqa: BLE001
                    log.exception("git check failed")
                    self._update(source["id"], checked=_now(), error="internal error (see the app log)")
            return {"recorded": recorded, "busy": False}
        finally:
            self._recording.release()

    def _check_one(self, source: dict) -> int:
        if not Path(source["path"]).is_dir():
            raise GitError("the repository folder is not there (is the drive connected?)")
        repo = Repo(source["path"])
        head = repo.head(source["branch"])
        if head is None:
            raise GitError("the branch is gone or has no commits")
        last = source.get("last_commit")
        if head == last:
            return 0
        try:
            new = repo.commits(head, since=last) if last else repo.commits(head)[-1:]
        except GitError:  # the last recorded commit no longer exists (history was rewritten)
            new = repo.commits(head)[-1:]
        if not new:  # the branch moved back to an older commit
            self._update(source["id"], last_commit=head)
            return 0
        done = self._already_recorded(source)
        new = [c for c in new if c.sha not in done]
        if not new:
            self._update(source["id"], last_commit=head, last_entry=done.get(head, source.get("last_entry")))
            return 0
        if len(new) > MAX_SEPARATE:
            self._record_batch(source, repo, Batch(f"{new[0].sha[:7]}…{new[-1].sha[:7]}", new, precision="day"))
            return 1
        for c in new:
            self._record_commit(source, repo, c)
        return len(new)

    def _already_recorded(self, source: dict) -> dict[str, str]:
        """commit -> step, for this repository (guards against recording a commit twice after a crash)."""
        out = {}
        for r in self.ctx.ledger.records():
            if r.kind != "entry":
                continue
            ext = parse_json_strict(r.payload_bytes).get("external") or {}
            if ext.get("repo_url") == source["repo_url"] and ext.get("commit"):
                out[ext["commit"]] = r.id
        return out

    def _claimed(self, commit: Commit, precision: str = "day", date: str | None = None) -> dict | None:
        """A git date earlier than today is kept as the author's claimed date (L1)."""
        day = commit.date[:10]
        if day >= _today():
            return None
        return {"claimed_date": date or {"day": day, "month": day[:7], "year": day[:4]}[precision], "level": "L1"}

    def _files(self, source: dict, repo: Repo, commit: Commit) -> list[UploadedFile]:
        if not source.get("keep_code"):
            return []
        data = repo.archive(commit.sha, MAX_UPLOAD_BYTES)
        if data is None:
            log.info("code of %s is larger than 50 MB: recorded as a reference only", commit.sha[:12])
            return []
        return [UploadedFile(f"{source['name']}-{commit.sha[:12]}.zip", data, "application/zip")]

    def _append(self, source: dict, repo: Repo, commit: Commit, title: str, body: str | None,
                claimed: dict | None) -> str:
        current = next((s for s in self._load() if s["id"] == source["id"]), source)
        prev = current.get("last_entry")
        rid = self.ctx.ledger.create_entry(EntryInput(
            project_id=current["project_id"], node_type="code", title=title[:TITLE_LIMIT].strip() or commit.sha[:12],
            body=body or None, files=self._files(current, repo, commit),
            external={"repo_url": current["repo_url"], "commit": commit.sha},
            relations=[{"to": prev, "rel": "revises"}] if prev and self.ctx.ledger.record(prev) else [],
            import_info=claimed,
        ))
        self._update(source["id"], last_commit=commit.sha, last_entry=rid,
                     recorded=int(current.get("recorded") or 0) + 1)
        source.update(last_commit=commit.sha, last_entry=rid)
        return rid

    def _record_commit(self, source: dict, repo: Repo, commit: Commit) -> str:
        """One commit, one step: the commit message is the author's own words."""
        return self._append(source, repo, commit, commit.subject or commit.sha[:12], commit.body,
                            self._claimed(commit))

    def _record_batch(self, source: dict, repo: Repo, batch: Batch) -> str:
        """Several commits in one step that lists them; the newest is its reference."""
        lines = [f"- `{c.sha[:12]}` {c.subject}" for c in batch.commits]
        last = batch.commits[-1]
        claimed = self._claimed(last, batch.precision, batch.claimed_date)
        return self._append(source, repo, last, f"{source['name']} · {batch.label}", "\n".join(lines), claimed)
