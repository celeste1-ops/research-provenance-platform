"""HTTP API (PRD §13 接口). Append-only: there is no PUT, PATCH or DELETE for records,
and no endpoint that edits an existing record."""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.config import MAX_UPLOAD_BYTES
from app.services.context import AppContext
from app.services.ledger import EntryInput, LedgerError, NotInitialized, UploadedFile
from app.services.verification import report_json, result_json, verify_database
from app.services.views import Snapshot, diff_view, graph_view, record_detail, timeline_view
from provenance_core.records import NODE_TYPES, RELATION_TYPES
from provenance_core.signing import export_private_key_encrypted

router = APIRouter(prefix="/api")


def ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def _bad(exc: Exception) -> HTTPException:
    if isinstance(exc, NotInitialized):
        return HTTPException(409, str(exc))
    return HTTPException(400, str(exc))


# ---------------------------------------------------------------- status & identity


@router.get("/status")
def status(request: Request):
    c = ctx(request)
    ledger = c.ledger
    genesis = None
    if ledger.initialized():
        rows = ledger.records()
        if rows:
            genesis = json.loads(rows[0].payload_bytes)
    providers = {
        k: (p.name if p is not None else None) for k, p in c.anchors.providers.items()
    }
    return {
        "initialized": ledger.initialized(),
        "author_label": genesis["author_label"] if genesis else None,
        "installation": ledger.installation,
        "record_count": ledger.record_count(),
        "providers": providers,
        "node_types": list(NODE_TYPES),
        "relation_types": list(RELATION_TYPES),
        "key_backup_done": ledger.meta("key_backup_done") == "1",
        "backup_location": ledger.meta("backup_location"),
    }


class IdentityIn(BaseModel):
    author_label: str


@router.post("/identity")
def create_identity(body: IdentityIn, request: Request):
    try:
        rid = ctx(request).ledger.init_identity(body.author_label)
    except (LedgerError, NotInitialized) as exc:
        raise _bad(exc) from None
    return {"genesis": rid, "reminder": "Back up your signing key now: if it is lost, new records start a new identity."}


class PasswordIn(BaseModel):
    password: str = Field(min_length=8)


@router.post("/identity/export")
def export_identity(body: PasswordIn, request: Request):
    c = ctx(request)
    try:
        key = c.ledger.signing_key()
    except NotInitialized as exc:
        raise _bad(exc) from None
    pem = export_private_key_encrypted(key, body.password)
    c.ledger.set_meta("key_backup_done", "1")
    return Response(
        pem,
        media_type="application/x-pem-file",
        headers={"Content-Disposition": 'attachment; filename="rprov-signing-key-backup.pem"'},
    )


# ---------------------------------------------------------------- projects


class ProjectIn(BaseModel):
    title: str


def _project_json(p) -> dict:
    return {"id": p.id, "title": p.title, "created_local": p.created_local}


@router.get("/projects")
def list_projects(request: Request):
    return [_project_json(p) for p in ctx(request).ledger.projects()]


@router.post("/projects")
def create_project(body: ProjectIn, request: Request):
    try:
        return _project_json(ctx(request).ledger.create_project(body.title))
    except LedgerError as exc:
        raise _bad(exc) from None


@router.post("/projects/{project_id}/rename")
def rename_project(project_id: str, body: ProjectIn, request: Request):
    """Local display name only; recorded entries keep the name they were recorded with."""
    try:
        return _project_json(ctx(request).ledger.rename_project(project_id, body.title))
    except LedgerError as exc:
        raise _bad(exc) from None


# ---------------------------------------------------------------- appending records


def _created(c: AppContext, rid: str) -> dict:
    snap = Snapshot.load(c.ledger, c.anchors)
    return {"id": rid, "detail": record_detail(snap, rid)}


def _parse_json_list(value: str | None, what: str) -> list:
    if not value:
        return []
    try:
        data = json.loads(value)
    except ValueError:
        raise HTTPException(400, f"{what} must be JSON") from None
    if not isinstance(data, list):
        raise HTTPException(400, f"{what} must be a JSON list")
    return data


@router.post("/entries")
async def create_entry(
    request: Request,
    project_id: Annotated[str, Form()],
    node_type: Annotated[str, Form()],
    title: Annotated[str, Form()],
    body: Annotated[str | None, Form()] = None,
    files: Annotated[list[UploadFile] | None, File()] = None,
    repo_url: Annotated[str | None, Form()] = None,
    commit: Annotated[str | None, Form()] = None,
    doi: Annotated[str | None, Form()] = None,
    url: Annotated[str | None, Form()] = None,
    relations: Annotated[str | None, Form()] = None,
    author_statement: Annotated[str | None, Form()] = None,
    milestone: Annotated[bool, Form()] = False,
    import_claimed_date: Annotated[str | None, Form()] = None,
    import_precision: Annotated[str | None, Form()] = None,
    import_level: Annotated[str | None, Form()] = None,
    import_references: Annotated[str | None, Form()] = None,
):
    c = ctx(request)
    uploads: list[UploadedFile] = []
    for f in files or []:
        data = await f.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"{f.filename}: files are limited to 50 MB each")
        uploads.append(UploadedFile(f.filename or "file", data, f.content_type))
    external = None
    if (repo_url or commit) and not (doi or url):
        external = {"repo_url": repo_url or "", "commit": commit or ""}
        if not (repo_url and commit):
            raise HTTPException(400, "a code reference needs both a repository URL and a commit hash")
    elif doi or url:
        if repo_url or commit or (doi and url):
            raise HTTPException(400, "give one external reference: repository + commit, a DOI, or a URL")
        external = {"doi": doi} if doi else {"url": url}
    refs = []
    if import_references:
        try:
            refs = json.loads(import_references)
        except ValueError:
            refs = [line for line in import_references.splitlines() if line.strip()]
        if not isinstance(refs, list):
            raise HTTPException(400, "import_references must be a list")
    inp = EntryInput(
        project_id=project_id,
        node_type=node_type,
        title=title,
        body=body,
        files=uploads,
        external=external,
        relations=_parse_json_list(relations, "relations"),
        author_statement=author_statement,
        milestone=milestone,
        import_info={
            "claimed_date": import_claimed_date or "",
            "precision": import_precision,
            "level": import_level,
            "references": refs,
        },
    )
    from starlette.concurrency import run_in_threadpool

    try:
        rid = await run_in_threadpool(c.ledger.create_entry, inp)
    except (LedgerError, NotInitialized) as exc:
        raise _bad(exc) from None
    return await run_in_threadpool(_created, c, rid)


class LinkIn(BaseModel):
    from_: str = Field(alias="from")
    to: str
    rel: str
    op: str = "add"
    statement: str | None = None


@router.post("/links")
def create_link(body: LinkIn, request: Request):
    c = ctx(request)
    try:
        rid = c.ledger.create_link(body.from_, body.to, body.rel, body.op, body.statement)
    except (LedgerError, NotInitialized) as exc:
        raise _bad(exc) from None
    return _created(c, rid)


class MilestoneIn(BaseModel):
    target: str
    op: str = "set"


@router.post("/milestones")
def create_milestone(body: MilestoneIn, request: Request):
    c = ctx(request)
    try:
        rid = c.ledger.create_milestone(body.target, body.op)
    except (LedgerError, NotInitialized) as exc:
        raise _bad(exc) from None
    return _created(c, rid)


class StatementIn(BaseModel):
    target: str
    text: str
    corrects: str | None = None


@router.post("/statements")
def create_statement(body: StatementIn, request: Request):
    c = ctx(request)
    try:
        rid = c.ledger.create_statement(body.target, body.text, body.corrects)
    except (LedgerError, NotInitialized) as exc:
        raise _bad(exc) from None
    return _created(c, rid)


class RetractionIn(BaseModel):
    target: str
    reason: str


@router.post("/retractions")
def create_retraction(body: RetractionIn, request: Request):
    c = ctx(request)
    try:
        rid = c.ledger.create_retraction(body.target, body.reason)
    except (LedgerError, NotInitialized) as exc:
        raise _bad(exc) from None
    return _created(c, rid)


# ---------------------------------------------------------------- reading


@router.get("/records/{record_id}")
def get_record(record_id: str, request: Request):
    c = ctx(request)
    detail = record_detail(Snapshot.load(c.ledger, c.anchors), record_id)
    if detail is None:
        raise HTTPException(404, "no such record")
    return detail


@router.get("/records/{record_id}/content")
def get_content(record_id: str, request: Request, file: str | None = None):
    c = ctx(request)
    files = c.ledger.record_files(record_id)
    if file is None:
        match = next((f for f in files if f.role == "body"), None)
    else:
        match = next((f for f in files if f.role == "file" and f.name == file), None)
    if match is None:
        raise HTTPException(404, "no such content")
    data = c.ledger.blobs.get(match.sha256)
    if match.role == "body":
        return Response(data, media_type="text/plain; charset=utf-8")
    # Never render uploaded files inline: download only, sandboxed (PRD S3).
    return Response(
        data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{_rfc5987(match.name)}",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        },
    )


def _rfc5987(name: str) -> str:
    from urllib.parse import quote

    return quote(name, safe="")


@router.get("/records/{record_id}/diff")
def get_diff(record_id: str, against: str, request: Request):
    c = ctx(request)
    if c.ledger.record(record_id) is None or c.ledger.record(against) is None:
        raise HTTPException(404, "no such record")
    return diff_view(c.ledger, Snapshot.load(c.ledger, c.anchors), record_id, against)


@router.get("/graph")
def get_graph(request: Request, project: str | None = None, milestones_only: bool = False):
    c = ctx(request)
    return graph_view(Snapshot.load(c.ledger, c.anchors), project, milestones_only)


@router.get("/timeline")
def get_timeline(request: Request, project: str | None = None):
    c = ctx(request)
    return timeline_view(Snapshot.load(c.ledger, c.anchors), project)


# ---------------------------------------------------------------- time proofs & verification


@router.post("/anchors/refresh")
def refresh_anchors(request: Request):
    return ctx(request).anchors.refresh(force=True)


@router.get("/records/{record_id}/verify")
def verify_record(record_id: str, request: Request):
    c = ctx(request)
    report = verify_database(c.ledger, c.anchors)
    result = report.by_id().get(record_id)
    if result is None:
        raise HTTPException(404, "no such record")
    return result_json(result)


@router.post("/verify/all")
def verify_all(request: Request):
    c = ctx(request)
    return report_json(verify_database(c.ledger, c.anchors))


# ---------------------------------------------------------------- evidence bundle


class ExportIn(BaseModel):
    title: str = "evidence"
    records: dict[str, str] = Field(default_factory=dict)  # record ID -> full | structure | existence
    default: str = "existence"


@router.post("/export/preview")
def export_preview(body: ExportIn, request: Request):
    from app.services.export import plan_export, preview

    c = ctx(request)
    try:
        return preview(c.ledger, plan_export(c.ledger, body.title, body.records, body.default))
    except LedgerError as exc:
        raise _bad(exc) from None


@router.post("/export")
def export_bundle(body: ExportIn, request: Request):
    import os

    from app.services.export import build_bundle_files, bundle_filename, plan_export, write_zip

    c = ctx(request)
    try:
        plan = plan_export(c.ledger, body.title, body.records, body.default)
    except LedgerError as exc:
        raise _bad(exc) from None
    data = write_zip(build_bundle_files(c.ledger, c.anchors, plan))
    name = bundle_filename(plan.title)
    exports = c.settings.data_dir / "exports"
    exports.mkdir(exist_ok=True)
    os.chmod(exports, 0o700)
    (exports / name).write_bytes(data)
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
