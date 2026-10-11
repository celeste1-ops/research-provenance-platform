"""Save a real time-stamping response as a test fixture (run on a networked Mac).

    make tsa-fixture                # DigiCert and FreeTSA
    uv run python tools/capture_tsa_fixture.py digicert

Asks each authority to stamp a fixed test text (nothing private) with certReq=true, exactly
as the app does, and writes the response *as received* to tests/fixtures/tsa/<name>-<date>.tsr
with a .json next to it (record ID = SHA-256 of the text, URL, time). The offline test
tests/unit/test_tsa_der_order.py then checks every saved response: it verifies against the
built-in roots, rfc3161-client can read it after sorting, and openssl accepts it. Commit both
files (DECISIONS D-045).
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.config import Settings
from app.services.context import public_tsa

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "tsa"


def capture(name: str) -> Path:
    provider = public_tsa(Settings(), name)
    now = datetime.now(UTC)
    text = f"rprov test fixture: {name} response {now:%Y-%m-%d}".encode()
    request = provider.build_request(text)
    response = httpx.post(provider.url, content=request.as_bytes(), timeout=30,
                          headers={"Content-Type": "application/timestamp-query"})
    response.raise_for_status()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}-{now:%Y%m%d}.tsr"
    path.write_bytes(response.content)
    meta = {"authority": name, "url": provider.url, "fetched_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "text": text.decode(), "record_id": hashlib.sha256(text).hexdigest()}
    path.with_suffix(".json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    check = provider.verify(meta["record_id"], response.content)
    print(f"{path.name}: {len(response.content)} bytes, {'verified' if check.verified else check.code}")
    return path


def main(argv: list[str]) -> int:
    for name in argv or ["digicert", "freetsa"]:
        capture(name)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
