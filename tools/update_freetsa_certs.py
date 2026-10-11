"""Refresh the built-in FreeTSA certificates from freetsa.org and check the built-in
DigiCert root against digicert.com (run on a networked Mac).

    make freetsa-certs

Downloads https://freetsa.org/files/cacert.pem and tsa.crt, prints their SHA-256
fingerprints, and writes them into core/provenance_core/certs/. The root is
pinned: if freetsa.org serves a root with a different fingerprint, nothing is
written and the script exits non-zero (review it by hand, then update
FREETSA_ROOT_SHA256 and docs/DECISIONS.md). Commit the result.

The DigiCert Trusted Root G4 (fallback authority, D-045) is only compared: the copy
DigiCert publishes must have the pinned fingerprint and equal the committed file.
"""

from __future__ import annotations

import sys

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization

from provenance_core.certs import (
    DIGICERT_ROOT_FILE,
    DIGICERT_ROOT_SHA256,
    FREETSA_ROOT_FILE,
    FREETSA_ROOT_SHA256,
    FREETSA_TSA_FILE,
)

BASE = "https://freetsa.org/files/"
DIGICERT_ROOT_URL = "https://cacerts.digicert.com/DigiCertTrustedRootG4.crt"


def fingerprint(cert: x509.Certificate) -> str:
    return cert.fingerprint(hashes.SHA256()).hex()


def check_digicert(client: httpx.Client) -> bool:
    raw = client.get(DIGICERT_ROOT_URL).raise_for_status().content
    try:
        published = x509.load_der_x509_certificate(raw)
    except ValueError:
        published = x509.load_pem_x509_certificate(raw)
    committed = x509.load_pem_x509_certificate(DIGICERT_ROOT_FILE.read_bytes())
    print(f"digicert {published.subject.rfc4514_string()}\n      SHA-256 {fingerprint(published)}")
    if fingerprint(published) != DIGICERT_ROOT_SHA256 or published != committed:
        print(f"\nPROBLEM: {DIGICERT_ROOT_URL} differs from the pinned {DIGICERT_ROOT_SHA256}", file=sys.stderr)
        return False
    print("      matches the committed copy and its pin\n")
    return True


def main() -> int:
    with httpx.Client(timeout=30) as client:
        if not check_digicert(client):
            return 1
        root_pem = client.get(BASE + "cacert.pem").raise_for_status().content
        tsa_raw = client.get(BASE + "tsa.crt").raise_for_status().content
    root = x509.load_pem_x509_certificate(root_pem)
    try:
        tsa = x509.load_pem_x509_certificate(tsa_raw)
    except ValueError:
        tsa = x509.load_der_x509_certificate(tsa_raw)
    print(f"root  {root.subject.rfc4514_string()}\n      valid {root.not_valid_before_utc} → {root.not_valid_after_utc}")
    print(f"      SHA-256 {fingerprint(root)}")
    print(f"tsa   {tsa.subject.rfc4514_string()}\n      valid {tsa.not_valid_before_utc} → {tsa.not_valid_after_utc}")
    print(f"      SHA-256 {fingerprint(tsa)}")
    if fingerprint(root) != FREETSA_ROOT_SHA256:
        print(f"\nREFUSING: root fingerprint differs from the pinned {FREETSA_ROOT_SHA256}", file=sys.stderr)
        return 1
    tsa.verify_directly_issued_by(root)
    FREETSA_ROOT_FILE.write_bytes(root.public_bytes(serialization.Encoding.PEM))
    FREETSA_TSA_FILE.write_bytes(tsa.public_bytes(serialization.Encoding.PEM))
    print(f"\nwrote {FREETSA_ROOT_FILE} and {FREETSA_TSA_FILE}; review and commit them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
