import os
import shutil
from pathlib import Path

import pytest


def chromium_path() -> str | None:
    """Use the pre-installed Chromium when the bundled Playwright build is absent."""
    env = os.environ.get("RPROV_CHROMIUM")
    if env:
        return env
    pre = Path("/opt/pw-browsers/chromium")
    return str(pre) if pre.exists() else None


@pytest.fixture(scope="session")
def browser():
    """Chromium, or with RPROV_E2E_BROWSER=webkit Safari's engine: the one that draws the app's
    window on macOS (D-058), so the same tests run there too (CI job "webkit")."""
    sync_api = pytest.importorskip("playwright.sync_api")
    engine = os.environ.get("RPROV_E2E_BROWSER", "chromium")
    with sync_api.sync_playwright() as p:
        try:
            b = p.webkit.launch() if engine == "webkit" else p.chromium.launch(executable_path=chromium_path())
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"{engine} not available (run `make install`): {exc}")
        yield b
        b.close()


@pytest.fixture(scope="session")
def uv_bin():
    path = shutil.which("uv")
    if path is None:
        pytest.skip("uv is needed to build a fresh virtual environment")
    return path
