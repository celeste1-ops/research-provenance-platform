"""Refresh the built-in FreeTSA certificates from freetsa.org (run on a networked Mac).

    make freetsa-certs

Downloads https://freetsa.org/files/cacert.pem and tsa.crt, prints their SHA-256
fingerprints, and writes them into core/provenance_core/certs/. The root is
pinned: if freetsa.org serves a root with a different fingerprint, nothing is
written and the script exits non-zero (review it by hand, then update
FREETSA_ROOT_SHA256 and docs/DECISIONS.md). Commit the result.
"""

from __future__ import annotations

import sys

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization

from provenance_core.certs import FREETSA_ROOT_FILE, FREETSA_ROOT_SHA256, FREETSA_TSA_FILE

BASE = "https://freetsa.org/files/"


def fingerprint(cert: x509.Certificate) -> str:
    return cert.fingerprint(hashes.SHA256()).hex()


def main() -> int:
    with httpx.Client(timeout=30) as client:
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
