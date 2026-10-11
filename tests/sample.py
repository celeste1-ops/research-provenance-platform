"""A small but complete sample log, exported as an evidence bundle (used by several tests)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.export import build_bundle_files, plan_export, write_dir, write_zip
from app.services.ledger import EntryInput, UploadedFile
from tests.conftest import make_ctx


@dataclass
class Sample:
    ctx: object
    ids: dict[str, str]
    bundle_dir: Path
    zip_path: Path
    files: dict[str, bytes]
    levels: dict[str, str]


def build_log(ctx) -> dict[str, str]:
    L = ctx.ledger
    ids = {"genesis": L.init_identity("Sample Author")}
    pid = L.create_project("FSF").id
    ids["idea"] = L.create_entry(EntryInput(pid, "idea", "First formula", body="E = m c^2\r\n",
                                            author_statement="came from last year's notes"))
    ids["exp"] = L.create_entry(EntryInput(
        pid, "experiment", "Numerical experiment 1", body="# Run 1\n\nconverged after 40 steps\n",
        files=[UploadedFile("run1.csv", b"t,x\n0,1\n1,0.5\n", "text/csv")],
        relations=[{"to": ids["idea"], "rel": "uses"}], milestone=True))
    ids["claim"] = L.create_entry(EntryInput(pid, "claim", "Revised model", body="secret draft wording",
                                             relations=[{"to": ids["idea"], "rel": "revises"}]))
    ids["old"] = L.create_entry(EntryInput(pid, "note", "Old notebook", body="from 2025",
                                           import_info={"claimed_date": "2025-11", "level": "L1"}))
    ids["link"] = L.create_link(ids["claim"], ids["exp"], "derived_from", statement="noticed later")
    ids["stmt"] = L.create_statement(ids["exp"], "Parameters were taken from the literature.")
    ids["paper"] = L.create_entry(EntryInput(pid, "publication", "Preprint", external={"doi": "10.5281/zenodo.1"},
                                             relations=[{"to": ids["claim"], "rel": "uses"}], milestone=True))
    return ids


def make_sample(tmp_path: Path, levels: dict[str, str] | None = None) -> Sample:
    ctx = make_ctx(tmp_path)
    ids = build_log(ctx)
    if levels is None:
        levels = {
            ids["idea"]: "full",
            ids["exp"]: "full",
            ids["claim"]: "structure",
            ids["old"]: "existence",
            ids["link"]: "structure",
            ids["stmt"]: "structure",
            ids["paper"]: "full",
        }
    plan = plan_export(ctx.ledger, "FSF sample", levels)
    files = build_bundle_files(ctx.ledger, ctx.anchors, plan)
    bundle_dir = tmp_path / "bundle"
    write_dir(files, bundle_dir)
    zip_path = tmp_path / "provenance-FSF-sample.zip"
    zip_path.write_bytes(write_zip(files))
    return Sample(ctx, ids, bundle_dir, zip_path, files, plan.levels)
