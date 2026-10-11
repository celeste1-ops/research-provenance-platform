"""Runtime settings, from environment variables with safe defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PORT = 8765
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # PRD S3


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("RPROV_HOME", "~/.rprov")).expanduser())
    port: int = int(os.environ.get("RPROV_PORT", DEFAULT_PORT))
    # Third-party timestamp provider: freetsa | mock | off
    tsa: str = os.environ.get("RPROV_TSA", "freetsa")
    tsa_url: str = os.environ.get("RPROV_TSA_URL", "https://freetsa.org/tsr")
    # Bitcoin anchor provider: ots | mock | off
    btc: str = os.environ.get("RPROV_BTC", "ots")
    # Optional local Bitcoin node for checking block headers (else: two public block explorers)
    bitcoin_rpc: str | None = os.environ.get("RPROV_BITCOIN_RPC") or None
    # Signing-key storage: keyring (macOS Keychain) | memory (tests) | dev-insecure-file
    keystore: str = os.environ.get("RPROV_KEYSTORE", "keyring")
    dev: bool = os.environ.get("RPROV_DEV", "") == "1"
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
