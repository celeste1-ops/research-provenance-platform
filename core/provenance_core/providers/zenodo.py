"""Zenodo: upload an evidence bundle as a draft deposit (DECISIONS D-060).

Only when the author asks, and only the bundle the author made (with the disclosure chosen for
each step). The deposit stays a private draft: the author looks at it on zenodo.org and publishes
it there — publishing is permanent, so the app never does it. The token is the author's own
personal access token (scope deposit:write) and is sent only to the Zenodo API host.
"""

from __future__ import annotations

from urllib.parse import quote, urlsplit

import httpx

API = {False: "https://zenodo.org/api", True: "https://sandbox.zenodo.org/api"}
TIMEOUT = httpx.Timeout(30.0, write=600.0, read=120.0)  # a bundle with attachments can be large


class ZenodoError(Exception):
    pass


class Zenodo:
    def __init__(self, token: str, sandbox: bool = False, transport: httpx.BaseTransport | None = None):
        if not token.strip():
            raise ZenodoError("no Zenodo token")
        self.base = API[bool(sandbox)]
        self.host = urlsplit(self.base).hostname
        self._client = httpx.Client(base_url=self.base, headers={"Authorization": f"Bearer {token.strip()}"},
                                    timeout=TIMEOUT, transport=transport, follow_redirects=False)

    def close(self) -> None:
        self._client.close()

    def _call(self, method: str, url: str, **kwargs) -> httpx.Response:
        target = httpx.URL(url)
        if target.is_absolute_url and (target.scheme != "https" or target.host != self.host):
            raise ZenodoError("Zenodo answered with an address on another server; nothing was sent there")
        try:
            r = self._client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise ZenodoError(f"could not reach Zenodo ({exc.__class__.__name__})") from None
        if r.status_code in (401, 403):
            raise ZenodoError("Zenodo did not accept the token (it needs the deposit:write scope)")
        if r.status_code >= 400:
            try:
                detail = r.json().get("message") or r.text[:200]
            except ValueError:
                detail = r.text[:200]
            raise ZenodoError(f"Zenodo said: {detail} (HTTP {r.status_code})")
        return r

    def check(self) -> None:
        """Is the token good? (Lists at most one of the author's deposits.)"""
        self._call("GET", "/deposit/depositions", params={"size": 1})

    def create_draft(self, filename: str, data: bytes, metadata: dict) -> dict:
        """A new draft deposit holding ``filename``. Returns its id, its page on zenodo.org and the
        DOI Zenodo reserved for it (the DOI only works once the author publishes)."""
        dep = self._call("POST", "/deposit/depositions", json={}).json()
        bucket = (dep.get("links") or {}).get("bucket")
        if not bucket:
            raise ZenodoError("Zenodo did not say where to put the file")
        self._call("PUT", f"{bucket}/{quote(filename)}", content=data,
                   headers={"Content-Type": "application/octet-stream"})
        updated = self._call("PUT", f"/deposit/depositions/{dep['id']}", json={"metadata": metadata}).json()
        links = updated.get("links") or dep.get("links") or {}
        doi = ((updated.get("metadata") or {}).get("prereserve_doi") or {}).get("doi")
        return {"id": dep["id"], "html": links.get("html"), "doi": doi}
