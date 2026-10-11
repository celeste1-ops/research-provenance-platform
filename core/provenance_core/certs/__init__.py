"""Built-in trust anchors for third-party timestamps (PRD §9, S6; DECISIONS D-004, D-045).

Two time-stamping authorities are trusted: FreeTSA (the default) and DigiCert (the
fallback when FreeTSA cannot be reached). Their root certificates are committed to
the repository, pinned by SHA-256 fingerprint and never downloaded at runtime.
"""

from __future__ import annotations

from pathlib import Path

from cryptography import x509

CERT_DIR = Path(__file__).resolve().parent
FREETSA_ROOT_FILE = CERT_DIR / "freetsa-cacert.pem"
FREETSA_TSA_FILE = CERT_DIR / "freetsa-tsa.crt"
FREETSA_ROOT_SHA256 = "a6379e7cecc05faa3cbf076013d745e327bbbaa38c0b9af22469d4701d18aabc"


# DigiCert Trusted Root G4: the root of DigiCert's public timestamping service
# (http://timestamp.digicert.com). Copy taken from the operating system trust store and
# checked against DigiCert's published fingerprint (D-045).
DIGICERT_ROOT_FILE = CERT_DIR / "digicert-trusted-root-g4.pem"
DIGICERT_ROOT_SHA256 = "552f7bdcf1a7af9e6ce672017f4f12abf77240c78e761ac203d1d9d20ac89988"

# (file name in certs/, label, SHA-256 of the DER certificate)
BUILTIN_TSA_ROOTS = (
    ("freetsa-cacert.pem", "FreeTSA Root CA", FREETSA_ROOT_SHA256),
    ("digicert-trusted-root-g4.pem", "DigiCert Trusted Root G4", DIGICERT_ROOT_SHA256),
)


def load_pinned(name: str, sha256: str) -> x509.Certificate:
    from cryptography.hazmat.primitives import hashes

    cert = x509.load_pem_x509_certificate((CERT_DIR / name).read_bytes())
    if cert.fingerprint(hashes.SHA256()).hex() != sha256:
        raise RuntimeError(f"built-in certificate {name} does not match its pinned fingerprint")
    return cert


def builtin_tsa_roots() -> list[x509.Certificate]:
    return [load_pinned(name, sha) for name, _label, sha in BUILTIN_TSA_ROOTS]


def builtin_tsa_root_labels() -> list[tuple[str, str]]:
    return [(label, sha) for _name, label, sha in BUILTIN_TSA_ROOTS]


def digicert_bundle_files() -> dict[str, bytes]:
    return {"digicert-trusted-root-g4.pem": DIGICERT_ROOT_FILE.read_bytes()}


def freetsa_bundle_files() -> dict[str, bytes]:
    return {
        "freetsa-cacert.pem": FREETSA_ROOT_FILE.read_bytes(),
        "freetsa-tsa.crt": FREETSA_TSA_FILE.read_bytes(),
    }
