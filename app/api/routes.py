"""HTTP API (PRD §13 接口). Append-only: there is no PUT, PATCH or DELETE for records,
and no endpoint that edits an existing record."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated, Literal

import anyio
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from app.config import MAX_UPLOAD_BYTES
from app.i18n import tr, tr_message
from app.services.context import AppContext
from app.services.ledger import EntryInput, LedgerError, NotInitialized, UploadedFile
from app.services.spaces import EXAMPLE, PRACTICE, REAL, SPACE_HEADER
from app.services.verification import report_json, result_json, verify_database
from app.services.views import Snapshot, diff_view, graph_view, record_detail, timeline_view
from provenance_core.records import NODE_TYPES, RELATION_TYPES
from provenance_core.signing import export_private_key_encrypted

router = APIRouter(prefix="/api")


def space_name(request: Request) -> str:
    """Which space a request is for (DECISIONS D-038); the real record unless it says otherwise."""
    return request.headers.get(SPACE_HEADER) or request.query_params.get("space") or REAL


def ctx(request: Request) -> AppContext:
    name = space_name(request)
    spaces = getattr(request.app.state, "spaces", None)
    if name == REAL or spaces is None:
        if name != REAL:
            raise HTTPException(400, f"unknown space {name!r}")
        return request.app.state.ctx
    try:
        return spaces.get(name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


def real(request: Request) -> AppContext:
    """Backups and restore always concern the real record; practice is never backed up."""
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
    entry_count = 0
    if ledger.initialized():
        rows = ledger.records()
        if rows:
            genesis = json.loads(rows[0].payload_bytes)
        entry_count = sum(1 for r in rows if r.kind == "entry")
    providers = {
        k: (p.name if p is not None else None) for k, p in c.anchors.providers.items()
    }
    return {
        "initialized": ledger.initialized(),
        "author_label": genesis["author_label"] if genesis else None,
        "installation": ledger.installation,
        # Research steps are entries; the genesis record and later additions are not counted.
        "entry_count": entry_count,
        "record_count": ledger.record_count(),
        "providers": providers,
        "node_types": list(NODE_TYPES),
        "relation_types": list(RELATION_TYPES),
        "key_backup_done": ledger.meta("key_backup_done") == "1",
        "backup_location": ledger.meta("backup_location"),
        # Backups always concern the real record (practice is never backed up).
        "backup": real(request).autobackup.status() if real(request).ledger.initialized() else None,
        "data_dir": str(c.settings.data_dir),
        "public_key": genesis["public_key"] if genesis else None,
        "space": space_name(request),
        "inbox": c.inbox.count(),  # versions from watched folders waiting to be recorded (D-049)
        # Words for this kind of computer in the interface: "this Mac", "this PC", "this computer".
        "device": c.settings.device,
        "keychain_name": c.settings.keychain_name,
        # The keychain refused access: the app stops asking until the person clicks Try again.
        "keychain_denied": c.keystore.denied or real(request).keystore.denied,
        "data_dir_warning": _data_dir_warning(real(request)),
        "practice_dir": str(request.app.state.spaces.practice_dir),
        "example_dir": str(request.app.state.spaces.example_dir),
        # The example holds the FSF sample: its language and the ids of its steps (D-059, D-064).
        "sample": request.app.state.spaces.sample_info() if space_name(request) == EXAMPLE else None,
    }


@router.post("/keychain/retry")
def keychain_retry(request: Request):
    """The person clicked Try again: read the keychain once more, now (the system may ask them)."""
    from app.services.keystore import KeychainDenied

    c = real(request)
    for store in {id(s): s for s in (c.keystore, ctx(request).keystore)}.values():
        store.retry()
    if c.ledger.initialized():
        c.autobackup.status()  # the backup password
        try:
            c.ledger.signing_key()  # and the signing key, so both questions come now, not later
        except (KeychainDenied, NotInitialized):
            pass
    return {"keychain_denied": c.keystore.denied}


def _data_dir_warning(c: AppContext) -> str | None:
    from app.services.autobackup import data_dir_warning

    return data_dir_warning(c.settings.data_dir)


class ExampleIn(BaseModel):
    lang: str = "en"  # the sample's language: the interface's


@router.post("/practice/reset")
def practice_reset(request: Request):
    """Start the practice space over, empty. There is no such operation for the real record."""
    from app.services.spaces import PracticeResetError

    try:
        c = request.app.state.spaces.reset_practice()
    except PracticeResetError as exc:
        raise HTTPException(409, str(exc)) from None
    return {"space": PRACTICE, "record_count": c.ledger.record_count()}


@router.post("/example/open")
def example_open(body: ExampleIn, request: Request):
    """The example (D-064), loaded in the interface's language if this is its first opening."""
    c = request.app.state.spaces.example(body.lang)
    return {"space": EXAMPLE, "record_count": c.ledger.record_count()}


@router.post("/example/reset")
def example_reset(body: ExampleIn, request: Request):
    """Load the example afresh, in the interface's language."""
    from app.services.spaces import PracticeResetError

    try:
        c = request.app.state.spaces.reset_example(body.lang)
    except PracticeResetError as exc:
        raise HTTPException(409, str(exc)) from None
    return {"space": EXAMPLE, "record_count": c.ledger.record_count()}


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
    from app.services.verification import record_file_stamps

    c = ctx(request)
    detail = record_detail(Snapshot.load(c.ledger, c.anchors), record_id)
    if detail is None:
        raise HTTPException(404, "no such record")
    detail["file_stamps"] = record_file_stamps(c.ledger, c.anchors, record_id)
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


@router.get("/records/{record_id}/preview")
def get_preview(record_id: str, request: Request, file: str):
    """An attached image or the start of a text file, to show in the app (D-057). Sandboxed like any
    attachment: if it is opened on its own, no script in it can run."""
    from app.services.previews import IMAGE_PREVIEW_BYTES, TEXT_PREVIEW_BYTES, image_type, preview_kind

    c = ctx(request)
    match = next((f for f in c.ledger.record_files(record_id) if f.role == "file" and f.name == file), None)
    if match is None:
        raise HTTPException(404, "no such content")
    kind = preview_kind(match.name)
    headers = {"Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'",
               "Content-Disposition": f"inline; filename*=UTF-8''{_rfc5987(match.name)}"}
    if kind == "image" and match.size <= IMAGE_PREVIEW_BYTES:
        return Response(c.ledger.blobs.get(match.sha256), media_type=image_type(match.name), headers=headers)
    if kind == "text":
        # Only the start is read: the whole file, checked against its fingerprint, is the download.
        with open(c.ledger.blobs.path_for(match.sha256), "rb") as fh:
            start = fh.read(TEXT_PREVIEW_BYTES)
        headers["X-Preview-Truncated"] = "1" if match.size > TEXT_PREVIEW_BYTES else "0"
        return Response(start.decode("utf-8", "replace"), media_type="text/plain; charset=utf-8", headers=headers)
    raise HTTPException(415, "this kind of file can only be downloaded")


def _rfc5987(name: str) -> str:
    from urllib.parse import quote

    return quote(name, safe="")


class TranslateIn(BaseModel):
    lang: str = "en"
    url: str = ""
    model: str = ""


@router.post("/records/{record_id}/translation")
def record_translation(record_id: str, body: TranslateIn, request: Request):
    """A step's title and text translated by the model on this computer (D-066): shown beside the
    original, marked as a translation, never saved."""
    from app import preferences
    from app.i18n import normalize
    from app.services import translate
    from provenance_core.providers.local_ai import DEFAULT_URL, LocalAIError

    found = translate.source(ctx(request).ledger, record_id)
    if found is None:
        raise HTTPException(404, "no such record")
    prefs = preferences.load(real(request).settings.data_dir)
    try:
        return translate.translate(body.url or prefs.get("ai_url") or DEFAULT_URL, body.model or prefs.get("ai_model") or "",
                                   *found, normalize(body.lang))
    except LocalAIError as exc:
        raise HTTPException(400, str(exc)) from None


@router.get("/records/{record_id}/diff")
def get_diff(record_id: str, against: str, request: Request):
    c = ctx(request)
    if c.ledger.record(record_id) is None or c.ledger.record(against) is None:
        raise HTTPException(404, "no such record")
    return diff_view(c.ledger, Snapshot.load(c.ledger, c.anchors), record_id, against)


@router.get("/graph")
def get_graph(request: Request, project: str | None = None, milestones_only: bool = False):
    c = ctx(request)
    return graph_view(Snapshot.load(c.ledger, c.anchors), project, milestones_only, blobs=c.ledger.blobs)


@router.get("/timeline")
def get_timeline(request: Request, project: str | None = None):
    c = ctx(request)
    return timeline_view(Snapshot.load(c.ledger, c.anchors), project)


@router.get("/narrative")
def get_narrative(request: Request, project: str | None = None):
    """The research told in sentences from fixed templates, each linked to its records (D-048)."""
    return _narrative(ctx(request), project)


def _narrative(c: AppContext, project: str | None) -> dict:
    from app.services.narrative import build_narrative

    snap = Snapshot.load(c.ledger, c.anchors)
    title = next((p.title for p in c.ledger.projects() if p.id == project), None) if project else None
    records = [(r.id, r.seq, r.kind, snap.payloads[r.id]) for r in snap.rows]
    from app.services.verification import record_file_stamps

    stamps = {}
    for rid, files in snap.files.items():  # only steps that hold an inbox date stamp (D-049)
        if any(f.name.endswith(".tsr") for f in files):
            stamps[rid] = [(f["file"], f["time"]) for f in record_file_stamps(c.ledger, c.anchors, rid)
                           if f["state"] == "verified"]
    return build_narrative(records, snap.when, title=title or tr("My research"), project_id=project,
                           file_stamps=stamps)


# ---------------------------------------------------------------- time proofs & verification


@router.post("/anchors/refresh")
def refresh_anchors(request: Request):
    return ctx(request).anchors.refresh(force=True)


class PreferencesIn(BaseModel):
    language: str


@router.get("/preferences")
def get_preferences(request: Request):
    from app import preferences

    return {"language": preferences.language(real(request).settings.data_dir)}


@router.post("/preferences")
def set_preferences(body: PreferencesIn, request: Request):
    """Remembered for the menu bar / tray menu and as the default report language (D-046)."""
    from app import preferences
    from app.i18n import normalize

    prefs = preferences.save(real(request).settings.data_dir, language=normalize(body.language))
    return {"language": prefs["language"]}


@router.post("/network/check")
def network_check(request: Request):
    """“Check stamp services” (D-045): only on request, and only random values are sent."""
    return real(request).service_check()


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


# ---------------------------------------------------------------- recording a git repository (D-047)


class GitPathIn(BaseModel):
    path: str


class GitSourceIn(BaseModel):
    path: str
    branch: str
    project_id: str
    history: bool = False
    keep_code: bool = False


@router.get("/git")
def git_sources(request: Request):
    return ctx(request).git.status()


@router.post("/git/inspect")
def git_inspect(body: GitPathIn, request: Request):
    from app.services.gitrepo import GitError

    try:
        return ctx(request).git.inspect(body.path)
    except GitError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("/git")
def git_add(body: GitSourceIn, request: Request):
    """Start recording; the first step(s) are saved in the background (they wait for stamps)."""
    from app.services.gitrepo import GitError

    c = ctx(request)
    if not c.ledger.initialized():
        raise HTTPException(409, "set up the app first")
    try:
        c.git.add(body.path, body.branch, body.project_id, history=body.history, keep_code=body.keep_code)
    except (GitError, LedgerError) as exc:
        raise HTTPException(400, str(exc)) from None
    return c.git.status()


@router.post("/git/check")
def git_check(request: Request):
    c = ctx(request)
    return {**c.git.check(), **c.git.status()}


@router.delete("/git/{source_id}")
def git_remove(source_id: str, request: Request):
    c = ctx(request)
    try:
        c.git.remove(source_id)
    except LedgerError as exc:
        raise HTTPException(404, str(exc)) from None
    return c.git.status()


# ---------------------------------------------------------------- retelling with an AI model (D-050, D-061)


class AiIn(BaseModel):
    url: str = ""
    model: str = ""
    project: str | None = None
    mode: Literal["local", "cloud"] = "local"
    confirm: str = ""  # cloud: the fingerprint of the text the author was shown and agreed to send


class CloudIn(BaseModel):
    provider: str
    key: str = Field(min_length=8, max_length=500)
    url: str = ""


def _cloud_call(fn, *args):
    from provenance_core.providers.cloud_ai import CloudAIError

    try:
        return _keystore_call(fn, *args)
    except CloudAIError as exc:
        raise HTTPException(400, str(exc)) from None


@router.get("/ai")
def ai_settings(request: Request):
    from app import preferences
    from app.services import ai_cloud
    from provenance_core.providers.local_ai import DEFAULT_URL

    prefs = preferences.load(real(request).settings.data_dir)
    return {"url": prefs.get("ai_url") or DEFAULT_URL, "model": prefs.get("ai_model") or "",
            "cloud": {**_cloud_call(ai_cloud.describe, real(request).keystore),
                      "model": prefs.get("cloud_model") or ""}}


@router.post("/ai/cloud")
def ai_cloud_connect(body: CloudIn, request: Request):
    """Connect an online AI service with the author's own key (checked by listing its models)."""
    from app.services import ai_cloud

    keystore = real(request).keystore
    models, first = _cloud_call(ai_cloud.connect, keystore, body.provider, body.key, body.url)
    return {**_cloud_call(ai_cloud.describe, keystore), "default_model": first, "models": models}


@router.delete("/ai/cloud")
def ai_cloud_forget(request: Request):
    from app.services import ai_cloud

    _cloud_call(ai_cloud.forget, real(request).keystore)
    return {"connected": False}


@router.post("/ai/cloud/models")
def ai_cloud_models(request: Request):
    from app.services import ai_cloud

    m = _cloud_call(ai_cloud.open_model, real(request).keystore)
    return {"models": _cloud_call(m.models)}


@router.post("/ai/cloud/preview")
def ai_cloud_preview(body: AiIn, request: Request):
    """Exactly what Send would send, and where to; nothing leaves the computer here. Before a
    service is connected it shows the text alone, so the author can decide whether to connect one."""
    from app.i18n import current
    from app.services import ai_cloud, ai_story

    keystore = real(request).keystore
    system, user, _known, count = ai_story.prompt(_narrative(ctx(request), body.project), current())
    text = {"system": system, "user": user, "facts": count, "characters": len(system) + len(user)}
    if _cloud_call(ai_cloud.settings, keystore) is None:
        return {"connected": False, **text}
    m = _cloud_call(ai_cloud.open_model, keystore, body.model)
    if not m.model:
        raise HTTPException(400, "choose a model first")
    return {"connected": True, "service": m.service, "host": m.host, "model": m.model, **text,
            "fingerprint": ai_cloud.fingerprint(m, system, user)}


@router.get("/ai/cloud/log")
def ai_cloud_log(request: Request):
    from app.services import ai_cloud

    return ai_cloud.read_log(real(request).settings.data_dir)


@router.post("/ai/models")
def ai_models(body: AiIn, request: Request):
    """The models the local server offers (asked only when the author clicks)."""
    from app.services import ai_story
    from provenance_core.providers.local_ai import LocalAIError

    try:
        model = ai_story.model_factory(body.url)
        return {"url": model.base, "models": model.models()}
    except LocalAIError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("/ai/story")
def ai_retell(body: AiIn, request: Request):
    """Retell the story with the chosen model: one on this computer, or — only with the
    fingerprint of the text the author was shown — the online service the author connected.

    The answer comes as it is written, one JSON object per line — {"text": ...} pieces, then
    {"result": ...} checked sentence by sentence, or {"error": ...} — so the page can show it
    growing instead of a minutes-long wait. When the page stops reading (the author clicked
    Stop), the connection to the model is closed and it stops writing.
    """
    from app import preferences
    from app.i18n import current, language, tr_message
    from app.services import ai_cloud, ai_story
    from provenance_core.providers.cloud_ai import CloudAIError
    from provenance_core.providers.local_ai import LocalAIError

    c = ctx(request)
    lang, label = current(), tr("AI inference")
    data_dir = real(request).settings.data_dir
    narrative = _narrative(c, body.project)
    prepared = ai_story.prompt(narrative, lang)
    if body.mode == "cloud":
        model = _cloud_call(ai_cloud.open_model, real(request).keystore, body.model)
        if not model.model:
            raise HTTPException(400, "choose a model first")
        system, user = prepared[0], prepared[1]
        if body.confirm != ai_cloud.fingerprint(model, system, user):
            raise HTTPException(409, "what would be sent has changed since you looked at it; look at it again")
        ai_cloud.write_log(data_dir, model, system, user, title=narrative["title"], space=space_name(request))
        remember = {"cloud_model": model.model}
    else:
        try:
            model = ai_story.model_factory(body.url, body.model)
            if not model.model:
                raise LocalAIError("choose a model first")
        except LocalAIError as exc:
            raise HTTPException(400, str(exc)) from None
        remember = {"ai_url": model.base, "ai_model": body.model}

    # Texts are put into the language now: the lines are written later, piece by piece. After each
    # piece, and every half second while the model is quiet (loading, thinking), it looks whether
    # the page is still reading; when it is not, the answer is cancelled, which closes the
    # connection to the model. (Writing to a page that has gone raises no error to notice it by.)
    async def lines():
        events = ai_story.retell_stream(narrative, model, lang, label=label, prepared=prepared)
        step: asyncio.Future | None = None
        try:
            while True:
                step = asyncio.ensure_future(anext(events, None))
                while True:
                    await asyncio.wait({step}, timeout=0.5)
                    if await request.is_disconnected():
                        return
                    if step.done():
                        break
                event = step.result()
                if event is None:
                    return
                if "result" in event:
                    preferences.save(data_dir, **remember)
                yield json.dumps(event, ensure_ascii=False) + "\n"
        except (LocalAIError, CloudAIError) as exc:
            with language(lang):
                message = tr_message(str(exc))
            yield json.dumps({"error": message}, ensure_ascii=False) + "\n"
        finally:
            # The page has gone while the model is between pieces (or still loading): hang up on
            # the model, so the wait for its next piece ends, and wait until it has; cancelling is
            # the fallback. Then the answer is closed. Nothing is left for the garbage collector.
            with anyio.CancelScope(shield=True):
                if step is not None and not step.done():
                    if await model.hang_up():
                        await asyncio.wait({step}, timeout=5)
                    if not step.done():
                        step.cancel()
                        await asyncio.wait({step}, timeout=5)
                if step is not None and step.done() and not step.cancelled():
                    step.exception()  # a broken answer after hanging up is expected; not "never retrieved"
                await events.aclose()

    return StreamingResponse(lines(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------- watched folders and the inbox (D-049)


class FolderIn(BaseModel):
    path: str
    project_id: str | None = None
    include_existing: bool = False


class InboxRecordIn(BaseModel):
    title: str | None = None
    node_type: str | None = None


@router.get("/inbox")
def inbox_status(request: Request):
    return ctx(request).inbox.status()


@router.post("/inbox/folders/inspect")
def inbox_inspect(body: FolderIn, request: Request):
    from app.services.inbox import InboxError

    try:
        return ctx(request).inbox.inspect(body.path)
    except InboxError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("/inbox/folders")
def inbox_add_folder(body: FolderIn, request: Request):
    from app.services.inbox import InboxError

    c = ctx(request)
    if not c.ledger.initialized():
        raise HTTPException(409, "set up the app first")
    try:
        c.inbox.add_folder(body.path, body.project_id or "", include_existing=body.include_existing)
    except (InboxError, LedgerError) as exc:
        raise HTTPException(400, str(exc)) from None
    return c.inbox.status()


@router.delete("/inbox/folders/{folder_id}")
def inbox_remove_folder(folder_id: str, request: Request):
    c = ctx(request)
    try:
        c.inbox.remove_folder(folder_id)
    except LedgerError as exc:
        raise HTTPException(404, str(exc)) from None
    return c.inbox.status()


@router.post("/inbox/check")
def inbox_check(request: Request):
    c = ctx(request)
    return {"arrived": c.inbox.scan(), **c.inbox.status()}


@router.post("/inbox/items/{item_id}/record")
def inbox_record(item_id: str, body: InboxRecordIn, request: Request):
    c = ctx(request)
    try:
        rid = c.inbox.record(item_id, title=body.title, node_type=body.node_type)
    except LedgerError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"id": rid, **c.inbox.status()}


@router.delete("/inbox/items/{item_id}")
def inbox_discard(item_id: str, request: Request):
    c = ctx(request)
    try:
        c.inbox.discard(item_id)
    except LedgerError as exc:
        raise HTTPException(404, str(exc)) from None
    return c.inbox.status()


# ---------------------------------------------------------------- evidence bundle


class ExportIn(BaseModel):
    title: str = "evidence"
    records: dict[str, str] = Field(default_factory=dict)  # record ID -> full | structure | existence
    default: str = "existence"
    language: str | None = None  # of report.html and VERIFY.md; the interface's language if not given (D-046)


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

    from app.i18n import current, language
    from app.services.export import build_bundle_files, bundle_filename, plan_export, write_zip

    c = ctx(request)
    try:
        plan = plan_export(c.ledger, body.title, body.records, body.default)
    except LedgerError as exc:
        raise _bad(exc) from None
    with language(body.language or current()):
        data = write_zip(build_bundle_files(c.ledger, c.anchors, plan))
    name = bundle_filename(plan.title)
    exports = c.settings.data_dir / "exports"
    exports.mkdir(exist_ok=True)
    os.chmod(exports, 0o700)
    (exports / name).write_bytes(data)
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _bundle_files(request: Request, body: ExportIn):
    from app.i18n import current, language
    from app.services.export import build_bundle_files, plan_export

    c = ctx(request)
    try:
        plan = plan_export(c.ledger, body.title, body.records, body.default)
    except LedgerError as exc:
        raise _bad(exc) from None
    with language(body.language or current()):
        files = build_bundle_files(c.ledger, c.anchors, plan)
    return c, plan, files


class ExportRepoIn(ExportIn):
    path: str  # a git repository on this computer
    commit: bool = True
    push: bool = False


@router.post("/export/repository")
def export_to_repository(body: ExportRepoIn, request: Request):
    """The evidence bundle into provenance/<title>/ of a repository, committed, pushed if asked (D-060)."""
    from app.services.publish import PublishError, to_repository

    _c, plan, files = _bundle_files(request, body)
    try:
        out = to_repository(files, plan.title, body.path, commit=body.commit, push=body.push)
    except PublishError as exc:
        raise HTTPException(400, str(exc)) from None
    if out.get("error"):  # saved, but the commit or the push did not go through
        out["error"] = tr_message(out["error"])
    return out


ZENODO_DESCRIPTION = (
    "Evidence bundle made with Research History. It holds report.html (open it in a browser), VERIFY.md and "
    "verify.py, with which anyone can check the records: that they existed by their date stamps and have not "
    "changed since. What the records do not show is written in report.html."
)


def _keystore_call(fn, *args):
    from app.services.keystore import KeyStoreError
    from app.services.publish import PublishError

    try:
        return fn(*args)
    except PublishError as exc:
        raise HTTPException(400, str(exc)) from None
    except KeyStoreError as exc:
        raise HTTPException(409, str(exc)) from None


def _zenodo_status(request: Request) -> dict:
    from app.services.publish import zenodo_settings

    s = _keystore_call(zenodo_settings, real(request).keystore)
    return {"connected": bool(s), "sandbox": bool(s and s.get("sandbox"))}


@router.get("/zenodo")
def zenodo_status(request: Request):
    return _zenodo_status(request)


class ZenodoIn(BaseModel):
    token: str = Field(min_length=10, max_length=500)
    sandbox: bool = False


@router.post("/zenodo")
def zenodo_connect(body: ZenodoIn, request: Request):
    """Check the author's Zenodo token and keep it in the system keychain."""
    from app.services.publish import connect_zenodo

    _keystore_call(connect_zenodo, real(request).keystore, body.token, body.sandbox)
    return _zenodo_status(request)


@router.delete("/zenodo")
def zenodo_forget(request: Request):
    from app.services.publish import forget_zenodo

    _keystore_call(forget_zenodo, real(request).keystore)
    return _zenodo_status(request)


@router.post("/export/zenodo")
def export_to_zenodo(body: ExportIn, request: Request):
    """The evidence bundle as a draft deposit on Zenodo, to be published there by the author (D-060)."""
    from app.i18n import current, language
    from app.services.export import bundle_filename, write_zip
    from app.services.publish import to_zenodo, zenodo_metadata

    c, plan, files = _bundle_files(request, body)
    rows = c.ledger.records()
    label = json.loads(rows[0].payload_bytes).get("author_label") if rows else None
    with language(body.language or current()):
        description = tr(ZENODO_DESCRIPTION)
    meta = zenodo_metadata(plan.title, label, f"<p>{description}</p>")
    return _keystore_call(to_zenodo, real(request).keystore, bundle_filename(plan.title), write_zip(files), meta)


@router.get("/export/table")
def export_table(request: Request, project: str | None = None, lang: str | None = None):
    """Every step of a project as a CSV table (Excel opens it); not evidence (D-060). A plain link
    cannot send the language header, so it comes as ``lang``."""
    import re as _re
    from datetime import date

    from app.i18n import current, language
    from app.services.importer import steps_table

    c = ctx(request)
    snap = Snapshot.load(c.ledger, c.anchors)
    title = next((p.title for p in c.ledger.projects() if p.id == project), "steps")
    slug = _re.sub(r"[^A-Za-z0-9._-]+", "-", title).strip("-")[:60] or "steps"
    with language(lang or current()):
        data = steps_table(snap, c.ledger.blobs, project)
    return Response(data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="steps-{slug}-{date.today()}.csv"'})


# ---------------------------------------------------------------- importing notes and tables (D-060)


class NotesIn(BaseModel):
    path: str
    project_id: str = ""
    selected: list[str] | None = None


@router.post("/import/notes/inspect")
def import_notes_inspect(body: NotesIn):
    from app.services.importer import ImportProblem, inspect_notes

    try:
        return inspect_notes(body.path)
    except (ImportProblem, OSError) as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("/import/notes")
def import_notes_route(body: NotesIn, request: Request):
    from app.services.importer import ImportProblem, import_notes

    c = ctx(request)
    try:
        return import_notes(c.ledger, body.path, body.project_id, body.selected)
    except (ImportProblem, LedgerError, OSError) as exc:
        raise _bad(exc) from None


async def _table_bytes(file: UploadFile) -> bytes:
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "the table is too large")
    return data


@router.post("/import/table/inspect")
async def import_table_inspect(file: Annotated[UploadFile, File()]):
    from app.services.importer import ImportProblem, inspect_table

    try:
        return inspect_table(await _table_bytes(file))
    except ImportProblem as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("/import/table")
async def import_table_route(request: Request, file: Annotated[UploadFile, File()],
                             project_id: Annotated[str, Form()]):
    from app.services.importer import ImportProblem, import_table

    data = await _table_bytes(file)
    c = ctx(request)
    try:
        return await anyio.to_thread.run_sync(lambda: import_table(c.ledger, data, project_id))
    except (ImportProblem, LedgerError) as exc:
        raise _bad(exc) from None


@router.get("/import/table/template")
def import_table_template(lang: str = "en"):
    from app.services.importer import table_template

    name = "steps-template.csv" if lang != "zh" else "steps-template-zh.csv"
    return Response(table_template(lang), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ---------------------------------------------------------------- backup & restore


class BackupIn(BaseModel):
    password: str = Field(min_length=8)


@router.post("/backup")
def create_backup_route(body: BackupIn, request: Request):
    """Download one encrypted backup now (independent of the automatic backups)."""
    import shutil
    import tempfile
    from pathlib import Path

    from fastapi.responses import FileResponse
    from starlette.background import BackgroundTask

    from app.services.backup import write_backup_file

    c = real(request)
    tmp = tempfile.mkdtemp(dir=c.settings.data_dir)
    try:
        path = write_backup_file(c, body.password, Path(tmp))
    except NotInitialized as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        raise _bad(exc) from None
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    c.ledger.set_meta("key_backup_done", "1")
    return FileResponse(path, media_type="application/octet-stream", filename=path.name,
                        background=BackgroundTask(shutil.rmtree, tmp, ignore_errors=True))


@router.get("/backup/status")
def backup_status(request: Request):
    c = real(request)
    if not c.ledger.initialized():
        raise HTTPException(409, "set up the app first")
    return c.autobackup.status()


@router.get("/backup/suggestions")
def backup_suggestions(request: Request):
    from app.services.autobackup import suggestions

    return suggestions(real(request).settings.data_dir)


@router.get("/backup/check")
def backup_check(location: str, request: Request):
    """Where would a backup in this folder survive? Shown while the author picks a folder."""
    from app.services.autobackup import check_location

    settings = real(request).settings
    return check_location(location, settings.data_dir, settings.device)


@router.post("/backup/resume")
def backup_resume(request: Request):
    """After a restore, automatic backup waits until the author confirms the folder (D-040)."""
    from app.services.backup import BackupError

    c = real(request)
    try:
        return c.autobackup.resume()
    except BackupError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("/backup/other-copy/acknowledge")
def backup_acknowledge_other_copy(request: Request):
    """The author says the other copy writing into the folder is gone (D-041)."""
    return real(request).autobackup.acknowledge_other_copy()


@router.post("/backup/recovery-code")
def backup_new_recovery_code(request: Request):
    """Make a new printable recovery code (shown once; the app keeps only its public half)."""
    from app.services.backup import BackupError

    c = real(request)
    try:
        code = c.autobackup.new_recovery_code()
    except BackupError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"recovery_code": code, "status": c.autobackup.status()}


class BackupSettingsIn(BaseModel):
    location: str
    password: str = Field(min_length=8)
    create: bool = False  # create the folder if it does not exist yet


@router.post("/backup/settings")
def backup_settings(body: BackupSettingsIn, request: Request):
    """Turn on automatic encrypted backups to this folder; writes the first one right away."""
    from app.services.backup import BackupError

    c = real(request)
    try:
        return c.autobackup.configure(body.location, body.password, create=body.create)
    except BackupError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("/backup/run")
def backup_run(request: Request):
    c = real(request)
    result = c.autobackup.run("manual")
    if not result["ran"]:
        raise HTTPException(400, result["reason"])
    return {**result, "status": c.autobackup.status()}


@router.post("/restore")
async def restore_route(
    request: Request,
    file: Annotated[UploadFile, File()],
    password: Annotated[str, Form()] = "",
    recovery_code: Annotated[str, Form()] = "",
):
    import shutil
    import tempfile
    from pathlib import Path

    from starlette.concurrency import run_in_threadpool

    from app.services.backup import BackupError, restore_backup
    from app.services.verification import report_json, verify_database

    c = real(request)
    # Stream the upload to a temporary file: backups can be larger than memory.
    tmp = tempfile.mkdtemp(dir=c.settings.data_dir)
    try:
        upload = Path(tmp) / "upload.rprovbackup"
        with open(upload, "wb") as out:
            while block := await file.read(1024 * 1024):
                out.write(block)
        summary = await run_in_threadpool(
            lambda: restore_backup(c, upload, password or None, recovery_code=recovery_code or None)
        )
    except (BackupError, LedgerError) as exc:
        raise HTTPException(400, str(exc)) from None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    # Same password, same folder (if it exists on this Mac): automatic backups simply continue.
    # Opened with the recovery code: the status asks for a new backup password.
    c.autobackup.adopt_restored_password(password if summary["opened_with"] == "password" else None)
    report = await run_in_threadpool(verify_database, c.ledger, c.anchors)
    return {**summary, "verification": report_json(report), "backup": c.autobackup.status()}
