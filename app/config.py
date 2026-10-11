"""Runtime settings, from environment variables with safe defaults."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PORT = 8765
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # PRD S3


def _env(name: str, default: str | None = None):
    # Read at construction time, not import time, so values set after import
    # (e.g. `python -m app --port 8766`) take effect.
    return field(default_factory=lambda: os.environ.get(name, default))


DEVICE_WORDS = {"darwin": "Mac", "win32": "PC"}
KEYCHAIN_NAMES = {"Mac": "Keychain", "PC": "Windows Credential Manager"}


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("RPROV_HOME", "~/.rprov")).expanduser())
    port: int = field(default_factory=lambda: int(os.environ.get("RPROV_PORT", DEFAULT_PORT)))
    # Third-party timestamp ("date stamp") service tried first: freetsa | digicert | mock | off
    tsa: str = _env("RPROV_TSA", "freetsa")
    tsa_url: str = _env("RPROV_TSA_URL", "https://freetsa.org/tsr")
    # Tried when the first cannot be reached: digicert | freetsa | off; empty = the other one (D-045).
    tsa_fallback: str = _env("RPROV_TSA_FALLBACK", "")
    digicert_tsa_url: str = _env("RPROV_DIGICERT_TSA_URL", "http://timestamp.digicert.com")
    # Bitcoin anchor provider: ots | mock | off
    btc: str = _env("RPROV_BTC", "ots")
    # Optional local Bitcoin node for checking block headers (else: two public block explorers)
    bitcoin_rpc: str | None = field(default_factory=lambda: os.environ.get("RPROV_BITCOIN_RPC") or None)
    # Signing-key storage: keyring (macOS Keychain) | memory (tests) | dev-insecure-file
    keystore: str = _env("RPROV_KEYSTORE", "keyring")
    dev: bool = field(default_factory=lambda: os.environ.get("RPROV_DEV", "") == "1")
    # What the interface calls this computer and its password store (display only; RPROV_DEVICE
    # lets tests and screenshots pick one). Behaviour never depends on it.
    device: str = field(default_factory=lambda: os.environ.get("RPROV_DEVICE") or DEVICE_WORDS.get(sys.platform, "computer"))

    @property
    def keychain_name(self) -> str:
        return KEYCHAIN_NAMES.get(self.device, "system keyring")
    web_dist: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent / "web" / "dist")
    # Extra Host/Origin values allowed (tests); never used to open the server up.
    extra_hosts: tuple[str, ...] = ()
    network_timeout: float = 15.0

    @property
    def db_path(self) -> Path:
        return self.data_dir / "rprov.sqlite3"

    @property
    def blob_dir(self) -> Path:
        return self.data_dir / "blobs"

    def allowed_hosts(self) -> set[str]:
        hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        if self.dev:
            hosts |= {"127.0.0.1:5173", "localhost:5173"}
        return hosts | set(self.extra_hosts)

    def allowed_origins(self) -> set[str]:
        return {f"http://{h}" for h in self.allowed_hosts()}

    def ensure_data_dir(self) -> None:
        """Create the data directory with owner-only permissions (PRD P2)."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.data_dir, 0o700)
        self.blob_dir.mkdir(exist_ok=True)
        os.chmod(self.blob_dir, 0o700)
