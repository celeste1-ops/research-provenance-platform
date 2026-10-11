"""Protect the local server from malicious web pages (PRD §14 S1, S2).

* Host must be 127.0.0.1:<port> or localhost:<port> (stops DNS rebinding).
* A present Origin must be the app's own origin.
* Every write (any non-GET/HEAD/OPTIONS request) must carry the per-launch session
  token in the ``X-RPROV-Token`` header. The token is embedded in the page,
  never in a URL.
"""

from __future__ import annotations

import hmac

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

TOKEN_HEADER = "x-rprov-token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; "
    "frame-ancestors 'none'"
)


class LocalOnlyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, allowed_hosts: set[str], allowed_origins: set[str], token: str):
        super().__init__(app)
        self.allowed_hosts = allowed_hosts
        self.allowed_origins = allowed_origins
        self.token = token

    async def dispatch(self, request: Request, call_next) -> Response:
        host = request.headers.get("host", "")
        if host not in self.allowed_hosts:
            return JSONResponse({"detail": "forbidden host"}, status_code=403)
        origin = request.headers.get("origin")
        if origin is not None and origin not in self.allowed_origins:
            return JSONResponse({"detail": "forbidden origin"}, status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "cross-site request refused"}, status_code=403)
        if request.method not in SAFE_METHODS:
            supplied = request.headers.get(TOKEN_HEADER, "")
            if not supplied or not hmac.compare_digest(supplied, self.token):
                return JSONResponse({"detail": "missing or wrong session token"}, status_code=403)
        response = await call_next(request)
        response.headers.setdefault("Content-Security-Policy", CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Cache-Control", "no-store")
        return response
