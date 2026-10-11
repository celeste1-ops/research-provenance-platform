"""Generate the throwaway certificate chain used by the mock TSA (tests only).

The output is committed so mock time-stamps are deterministic. The private key is
deliberately public: nothing signed by it is trusted unless a verifier is explicitly
told to trust the mock root (``verify.py --tsa-root``).

    uv run python tools/gen_mock_tsa.py
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

OUT = Path(__file__).resolve().parent.parent / "core" / "provenance_core" / "providers" / "mock_tsa"


def name(cn: str) -> x509.Name:
    return x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "rprov MOCK - NOT A REAL TSA"),
            x509.NameAttribute(NameOID.COMMON_NAME, cn),
        ]
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    not_before = datetime(2020, 1, 1, tzinfo=UTC)
    not_after = datetime(2099, 12, 31, tzinfo=UTC)

    root_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    root_name = name("rprov Mock TSA Root (test only)")
    root = (
        x509.CertificateBuilder()
        .subject_name(root_name)
        .issuer_name(root_name)
        .public_key(root_key.public_key())
        .serial_number(1)
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(root_key.public_key()), critical=False)
        .sign(root_key, hashes.SHA256())
    )

    tsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    tsa = (
        x509.CertificateBuilder()
        .subject_name(name("rprov Mock TSA (test only)"))
        .issuer_name(root_name)
        .public_key(tsa_key.public_key())
        .serial_number(2)
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(True, True, False, False, False, False, False, False, False), critical=True
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.TIME_STAMPING]), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(tsa_key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(root_key.public_key()), critical=False
        )
        .sign(root_key, hashes.SHA256())
    )

    (OUT / "mock-tsa-root.pem").write_bytes(root.public_bytes(serialization.Encoding.PEM))
    (OUT / "mock-tsa.pem").write_bytes(tsa.public_bytes(serialization.Encoding.PEM))
    (OUT / "mock-tsa-key.pem").write_bytes(
        tsa_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    print(f"wrote mock TSA chain to {OUT}")


if __name__ == "__main__":
    main()
