"""Built-in trust anchors for third-party timestamps (PRD §9, S6).

The FreeTSA certificates are committed to the repository and never downloaded
at runtime. See docs/DECISIONS.md (D-004) for where these copies came from.
"""

from __future__ import annotations

from pathlib import Path

from cryptography import x509

CERT_DIR = Path(__file__).resolve().parent
FREETSA_ROOT_FILE = CERT_DIR / "freetsa-cacert.pem"
FREETSA_TSA_FILE = CERT_DIR / "freetsa-tsa.crt"
FREETSA_ROOT_SHA256 = "a6379e7cecc05faa3cbf076013d745e327bbbaa38c0b9af22469d4701d18aabc"


def builtin_tsa_roots() -> list[x509.Certificate]:
    return [x509.load_pem_x509_certificate(FREETSA_ROOT_FILE.read_bytes())]


def freetsa_bundle_files() -> dict[str, bytes]:
    return {
        "freetsa-cacert.pem": FREETSA_ROOT_FILE.read_bytes(),
        "freetsa-tsa.crt": FREETSA_TSA_FILE.read_bytes(),
    }
