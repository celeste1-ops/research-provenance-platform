"""FastAPI application and the `python -m app` entry point (127.0.0.1 only, PRD S1)."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import router
from app.api.security import LocalOnlyMiddleware
from app.config import Settings
from app.i18n import set_language, tr_message
from app.instance import InstanceLock
from app.services.context import AppContext
from app.services.keystore import KeychainDenied
from app.services.spaces import Spaces

log = logging.getLogger("rprov")


class LanguageMiddleware:
    """Texts the server writes follow the interface language the request names (D-046)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        value = next((v.decode("latin-1") for k, v in scope.get("headers", []) if k == b"x-rprov-lang"), None)
        set_language(value)
        await self.app(scope, receive, send)


# The types of the page's own files, not left to the mimetypes module: on Windows it takes them from
# the registry, where other software often maps .js to text/plain, and a browser does not run a
# script sent as plain text — the page stayed empty on such a computer.
WEB_TYPES = {
    ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".html": "text/html",
    ".json": "application/json", ".map": "application/json", ".svg": "image/svg+xml", ".png": "image/png",
    ".ico": "image/x-icon", ".woff2": "font/woff2", ".woff": "font/woff",
}


def create_app(ctx: AppContext, *, start_jobs: bool = False) -> FastAPI:
    spaces = Spaces(ctx)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        jobs = []
        if start_jobs:
            from app.jobs.scheduler import AnchorScheduler, SourcesScheduler

            # Stamps are checked in both spaces; only the real record is backed up.
            jobs = [AnchorScheduler(spaces, after=lambda: ctx.autobackup.maybe_run("hourly")), SourcesScheduler(spaces)]
            for job in jobs:
                job.start()
        try:
            yield
        finally:
            for job in jobs:
                job.stop()
            spaces.close()

    app = FastAPI(title="Research provenance (local)", docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=lifespan)
    app.state.ctx = ctx
    app.state.spaces = spaces
    app.add_middleware(
        LocalOnlyMiddleware,
        allowed_hosts=ctx.settings.allowed_hosts(),
        allowed_origins=ctx.settings.allowed_origins(),
        token=ctx.session_token,
    )
    app.add_middleware(LanguageMiddleware)
    app.include_router(router)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        # Error messages are written in English where they are raised; translated on the way out.
        detail = tr_message(exc.detail) if isinstance(exc.detail, str) else exc.detail
        return JSONResponse({"detail": detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(KeychainDenied)
    async def keychain_denied(request: Request, exc: KeychainDenied):
        # Not an internal error: the person said no to the keychain. The page offers Try again.
        return JSONResponse({"detail": tr_message(str(exc)), "keychain_denied": True}, status_code=403)

    @app.exception_handler(Exception)
    async def log_unexpected(request: Request, exc: Exception):
        # Unexpected errors go to the log with their traceback (the desktop app has no console).
        log.error("unexpected error on %s %s", request.method, request.url.path, exc_info=exc)
        return JSONResponse({"detail": tr_message("internal error (see the app log)")}, status_code=500)
    dist: Path = ctx.settings.web_dist

    def index() -> HTMLResponse:
        page = dist / "index.html"
        if not page.exists():
            return HTMLResponse("<p>The UI has not been built. Run <code>make run</code>.</p>", status_code=503)
        html = page.read_text(encoding="utf-8").replace("__RPROV_SESSION_TOKEN__", ctx.session_token)
        return HTMLResponse(html)

    @app.get("/", include_in_schema=False)
    def root():
        return index()

    @app.get("/{path:path}", include_in_schema=False)
    def static(path: str, request: Request):
        if path.startswith("api/"):
            raise HTTPException(404)
        target = (dist / path).resolve()
        if dist.resolve() in target.parents and target.is_file():
            return FileResponse(target, media_type=WEB_TYPES.get(target.suffix.lower()))
        return index()

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local research provenance app")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--reload", action="store_true", help="development: reload on code changes")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    if args.port:
        os.environ["RPROV_PORT"] = str(args.port)
    import uvicorn

    settings = Settings()
    settings.ensure_data_dir()
    lock = InstanceLock(settings.data_dir)  # the installed app takes the same lock (D-044)
    if not lock.acquire():
        port = lock.running_port(wait=2)
        where = f" at http://127.0.0.1:{port}/" if port else ""
        sys.exit(f"The app is already running for {settings.data_dir}{where}. Quit that copy first "
                 "(menu bar / notification area icon → Quit, or Ctrl+C), or choose another data folder "
                 "with RPROV_HOME.")
    lock.publish(settings.port)
    try:
        # PRD S1: bind to the loopback interface only — never 0.0.0.0.
        if args.reload:
            uvicorn.run("app.main:app_factory", factory=True, host="127.0.0.1", port=settings.port, reload=True)
        else:
            uvicorn.run(app_factory(), host="127.0.0.1", port=settings.port, log_level="info")
    finally:
        lock.release()


def app_factory() -> FastAPI:
    settings = Settings()
    ctx = AppContext.create(settings)
    if settings.dev:
        token_file = settings.data_dir / "dev-session-token"
        fd = os.open(token_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(ctx.session_token)
    log.info("Serving on http://127.0.0.1:%d (data: %s)", settings.port, settings.data_dir)
    return create_app(ctx, start_jobs=True)
