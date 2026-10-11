"""`make demo`: load the fictional FSF sample (fixtures/fsf_demo) into an empty data directory.

Records are append-only, so the demo refuses to touch a data directory that already
holds records. To keep your real record clean, load the demo into its own directory:

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


def load_demo(ctx: AppContext, fixtures: Path = FIXTURES) -> dict[str, str]:
    spec = json.loads((fixtures / "records.json").read_text(encoding="utf-8"))
    ledger = ctx.ledger
    if ledger.record_count() > 0:
        raise RuntimeError(
            f"{ctx.settings.data_dir} already contains records; the demo only loads into an empty data "
            "directory (records cannot be removed). Try: RPROV_HOME=~/.rprov-demo make demo"
        )
    ids: dict[str, str] = {"genesis": ledger.init_identity(spec["author_label"])}
    project = ledger.create_project(spec["project"])
    for step in spec["steps"]:
        kind = step["kind"]
        if kind == "entry":
            files = [
                UploadedFile(name, (fixtures / "files" / name).read_bytes(), None) for name in step.get("files", [])
            ]
            ids[step["key"]] = ledger.create_entry(
                EntryInput(
                    project_id=project.id,
                    node_type=step["node_type"],
                    title=step["title"],
                    body=step.get("body"),
                    files=files,
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
            ids[step["key"]] = ledger.create_statement(ids[step["target"]], step["text"])
        elif kind == "milestone":
            ids[step["key"]] = ledger.create_milestone(ids[step["target"]], step.get("op", "set"))
        elif kind == "retraction":
            ids[step["key"]] = ledger.create_retraction(ids[step["target"]], step["reason"])
        else:
            raise ValueError(f"unknown step kind {kind!r}")
    return ids


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
