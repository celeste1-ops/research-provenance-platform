"""The sample research.

* ``make demo`` loads the small fictional FSF sample (fixtures/fsf_demo, 14 steps; the tests use
  it too) into an empty data directory.
* The app's practice space can be filled with the larger FSF sample (fixtures/fsf_sample,
  DECISIONS D-059), in English or Chinese: two projects and 32 steps that use every kind of step,
  relation and later addition, so a new user sees how the app works before recording anything.

Records are append-only, so neither loads into a data directory that already holds records. To
keep your real record clean, load the demo into its own directory:

    RPROV_HOME=~/.rprov-demo make demo
    RPROV_HOME=~/.rprov-demo make run
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.config import Settings
from app.services.context import AppContext
from app.services.ledger import EntryInput, UploadedFile

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "fsf_demo"
SAMPLE = Path(__file__).resolve().parent.parent / "fixtures" / "fsf_sample"
SAMPLE_LANGS = ("en", "zh")


def load_records(ctx: AppContext, spec: dict, files_dir: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Write the steps of a sample spec, in order. Returns the record id of each step key and the
    id of each project key."""
    ledger = ctx.ledger
    if ledger.record_count() > 0:
        raise RuntimeError(
            f"{ctx.settings.data_dir} already contains records; the demo only loads into an empty data "
            "directory (records cannot be removed). Try: RPROV_HOME=~/.rprov-demo make demo"
        )
    ids: dict[str, str] = {"genesis": ledger.init_identity(spec["author_label"])}
    titles = spec.get("projects") or {"main": spec["project"]}
    projects = {key: ledger.create_project(title).id for key, title in titles.items()}
    first = next(iter(projects))

    def upload(item) -> UploadedFile:
        name, src = (item, item) if isinstance(item, str) else (item["name"], item["src"])
        return UploadedFile(name, (files_dir / src).read_bytes(), None)

    for step in spec["steps"]:
        kind = step["kind"]
        if kind == "entry":
            ids[step["key"]] = ledger.create_entry(
                EntryInput(
                    project_id=projects[step.get("project", first)],
                    node_type=step["node_type"],
                    title=step["title"],
                    body=step.get("body"),
                    files=[upload(f) for f in step.get("files", [])],
                    external=step.get("external"),
                    relations=[{"to": ids[r["to"]], "rel": r["rel"]} for r in step.get("relations", [])],
                    author_statement=step.get("author_statement"),
                    milestone=step.get("milestone", False),
                    import_info=step.get("import"),
                )
            )
        elif kind == "link":
            ids[step["key"]] = ledger.create_link(
                ids[step["from"]], ids[step["to"]], step["rel"], step.get("op", "add"), step.get("statement")
            )
        elif kind == "statement":
            corrects = ids[step["corrects"]] if step.get("corrects") else None
            ids[step["key"]] = ledger.create_statement(ids[step["target"]], step["text"], corrects)
        elif kind == "milestone":
            ids[step["key"]] = ledger.create_milestone(ids[step["target"]], step.get("op", "set"))
        elif kind == "retraction":
            ids[step["key"]] = ledger.create_retraction(ids[step["target"]], step["reason"])
        else:
            raise ValueError(f"unknown step kind {kind!r}")
    return ids, projects


def load_demo(ctx: AppContext, fixtures: Path = FIXTURES) -> dict[str, str]:
    """The small sample (``make demo`` and the tests)."""
    spec = json.loads((fixtures / "records.json").read_text(encoding="utf-8"))
    ids, _projects = load_records(ctx, spec, fixtures / "files")
    return ids


def sample_spec(lang: str) -> dict:
    lang = lang if lang in SAMPLE_LANGS else "en"
    return json.loads((SAMPLE / f"records.{lang}.json").read_text(encoding="utf-8"))


def load_sample(ctx: AppContext, lang: str = "en") -> dict:
    """The FSF sample research in ``lang`` (D-059). Returns what the practice space remembers
    about it: the language, and the record id of each step and project, which the sample tour in
    the interface points at."""
    lang = lang if lang in SAMPLE_LANGS else "en"
    ids, projects = load_records(ctx, sample_spec(lang), SAMPLE / "files")
    return {"version": 1, "lang": lang, "ids": ids, "projects": projects}


def main() -> int:
    settings = Settings()
    ctx = AppContext.create(settings)
    try:
        ids = load_demo(ctx)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        ctx.close()
        return 1
    stats = ctx.anchors.refresh(force=False)
    print(f"Loaded {len(ids)} demo records into {settings.data_dir}")
    print(f"Time proofs: {stats}. Start the app with `make run` (same RPROV_HOME).")
    ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
