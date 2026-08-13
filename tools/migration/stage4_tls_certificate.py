from __future__ import annotations

"""Generate the Stage 4 loopback TLS identity with the locked Python runtime.

The official PostgreSQL Windows archive is not required to ship an OpenSSL
command-line program.  The bootstrap creates this certificate only after its
hash-pinned Python environment has been verified, and this module never emits
private-key material in its JSON evidence.
"""

import argparse
import hashlib
import ipaddress
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


class TlsCertificateError(RuntimeError):
    pass


def _write_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(payload)
    except FileExistsError as exc:
        raise TlsCertificateError(f"refusing to overwrite TLS material: {path.name}") from exc


def generate_loopback_certificate(
    *,
    output_dir: Path,
    evidence_path: Path,
    valid_days: int = 825,
    subject_common_name: str = "localhost",
    san_dns: list[str] | None = None,
    san_ip: list[str] | None = None,
) -> dict[str, object]:
    if valid_days < 1 or valid_days > 825:
        raise TlsCertificateError("TLS certificate validity must be between 1 and 825 days")
    output_dir = output_dir.resolve()
    evidence_path = evidence_path.resolve()
    if evidence_path == output_dir or output_dir in evidence_path.parents:
        raise TlsCertificateError("TLS evidence must remain outside the private-key directory")

    server_key = output_dir / "server.key"
    server_cert = output_dir / "server.crt"
    root_cert = output_dir / "root.crt"
    for target in (server_key, server_cert, root_cert):
        if target.exists():
            raise TlsCertificateError(f"refusing to overwrite TLS material: {target.name}")

    common_name = subject_common_name.strip()
    if not common_name or len(common_name) > 64:
        raise TlsCertificateError("TLS common name is empty or too long")
    dns_input = ["localhost"] if san_dns is None else san_dns
    ip_input = ["127.0.0.1"] if san_ip is None else san_ip
    dns_names = list(dict.fromkeys(item.strip() for item in dns_input))
    ip_names = list(dict.fromkeys(item.strip() for item in ip_input))
    if not dns_names and not ip_names:
        raise TlsCertificateError("TLS certificate requires at least one SAN")
    if any(not item or len(item) > 253 for item in dns_names):
        raise TlsCertificateError("TLS DNS SAN is invalid")
    try:
        parsed_ips = [ipaddress.ip_address(item) for item in ip_names]
    except ValueError as exc:
        raise TlsCertificateError("TLS IP SAN is invalid") from exc

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    not_before = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=5)
    not_after = not_before + timedelta(days=valid_days)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName(item) for item in dns_names]
                + [x509.IPAddress(item) for item in parsed_ips]
            ),
            critical=False,
        )
        .sign(private_key=private_key, algorithm=hashes.SHA256())
    )
    key_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    cert_bytes = certificate.public_bytes(serialization.Encoding.PEM)
    created: list[Path] = []
    try:
        _write_new(server_key, key_bytes)
        created.append(server_key)
        _write_new(server_cert, cert_bytes)
        created.append(server_cert)
        _write_new(root_cert, cert_bytes)
        created.append(root_cert)
    except Exception:
        # A partially created identity is never reused.  Only files created by
        # this invocation are removed; a pre-existing target fails before this
        # block and is never touched.
        for target in created:
            if target.is_file():
                target.unlink()
        raise

    loaded_certificate = x509.load_pem_x509_certificate(server_cert.read_bytes())
    loaded_root = x509.load_pem_x509_certificate(root_cert.read_bytes())
    loaded_key = serialization.load_pem_private_key(server_key.read_bytes(), password=None)
    if loaded_certificate.public_key().public_numbers() != loaded_key.public_key().public_numbers():
        raise TlsCertificateError("generated TLS private key does not match certificate")
    if loaded_root.fingerprint(hashes.SHA256()) != loaded_certificate.fingerprint(
        hashes.SHA256()
    ):
        raise TlsCertificateError("generated TLS root copy does not match certificate")
    loaded_certificate.public_key().verify(
        loaded_certificate.signature,
        loaded_certificate.tbs_certificate_bytes,
        padding.PKCS1v15(),
        loaded_certificate.signature_hash_algorithm,
    )

    fingerprint = certificate.fingerprint(hashes.SHA256()).hex()
    evidence: dict[str, object] = {
        "schema_version": "honghu.stage4_tls_certificate.v1",
        "subject_common_name": common_name,
        "issuer_common_name": common_name,
        "serial_number_hex": format(certificate.serial_number, "x"),
        "not_valid_before_utc": not_before.isoformat(),
        "not_valid_after_utc": not_after.isoformat(),
        "signature_hash_algorithm": "sha256",
        "public_key_algorithm": "rsa",
        "public_key_bits": 3072,
        "san_dns": dns_names,
        "san_ip": ip_names,
        "extended_key_usage": ["serverAuth"],
        "basic_constraints_ca": False,
        "key_usage": ["digitalSignature", "keyEncipherment"],
        "self_signature_verified": True,
        "private_key_matches_certificate": True,
        "certificate_sha256": hashlib.sha256(cert_bytes).hexdigest(),
        "certificate_fingerprint_sha256": fingerprint,
        "root_certificate_sha256": hashlib.sha256(cert_bytes).hexdigest(),
        "private_key_recorded": False,
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--valid-days", type=int, default=825)
    parser.add_argument("--common-name", default="localhost")
    parser.add_argument("--san-dns", action="append")
    parser.add_argument("--san-ip", action="append")
    args = parser.parse_args(argv)
    result = generate_loopback_certificate(
        output_dir=args.output_dir,
        evidence_path=args.evidence,
        valid_days=args.valid_days,
        subject_common_name=args.common_name,
        san_dns=args.san_dns,
        san_ip=args.san_ip,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
