from __future__ import annotations

import ipaddress
import json
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.x509.oid import ExtendedKeyUsageOID

from tools.migration.stage4_preinstall_quarantine import (
    PreinstallQuarantineError,
    quarantine_preinstall_staging,
)
from tools.migration.stage4_tls_certificate import (
    TlsCertificateError,
    generate_loopback_certificate,
)


def test_tls_generator_creates_verified_loopback_server_identity(tmp_path: Path) -> None:
    tls_dir = tmp_path / "install/tls"
    evidence_path = tmp_path / "evidence/tls.json"
    evidence = generate_loopback_certificate(
        output_dir=tls_dir, evidence_path=evidence_path
    )
    certificate = x509.load_pem_x509_certificate((tls_dir / "server.crt").read_bytes())
    root = x509.load_pem_x509_certificate((tls_dir / "root.crt").read_bytes())
    private_key = serialization.load_pem_private_key(
        (tls_dir / "server.key").read_bytes(), password=None
    )

    assert certificate.fingerprint(certificate.signature_hash_algorithm).hex() == evidence[
        "certificate_fingerprint_sha256"
    ]
    assert certificate.public_key().public_numbers() == private_key.public_key().public_numbers()
    assert root.fingerprint(certificate.signature_hash_algorithm) == certificate.fingerprint(
        certificate.signature_hash_algorithm
    )
    san = certificate.extensions.get_extension_for_class(
        x509.SubjectAlternativeName
    ).value
    assert san.get_values_for_type(x509.DNSName) == ["localhost"]
    assert san.get_values_for_type(x509.IPAddress) == [
        ipaddress.ip_address("127.0.0.1")
    ]
    eku = certificate.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    assert ExtendedKeyUsageOID.SERVER_AUTH in eku
    assert evidence["public_key_bits"] == 3072
    assert evidence["basic_constraints_ca"] is False
    assert evidence["key_usage"] == ["digitalSignature", "keyEncipherment"]
    assert evidence["self_signature_verified"] is True
    assert evidence["private_key_matches_certificate"] is True
    assert evidence["private_key_recorded"] is False
    assert "PRIVATE KEY" not in evidence_path.read_text(encoding="utf-8")


def test_tls_generator_fails_closed_instead_of_overwriting(tmp_path: Path) -> None:
    tls_dir = tmp_path / "tls"
    evidence = tmp_path / "evidence/first.json"
    generate_loopback_certificate(output_dir=tls_dir, evidence_path=evidence)
    original_key = (tls_dir / "server.key").read_bytes()
    with pytest.raises(TlsCertificateError, match="refusing to overwrite"):
        generate_loopback_certificate(
            output_dir=tls_dir, evidence_path=tmp_path / "evidence/second.json"
        )
    assert (tls_dir / "server.key").read_bytes() == original_key


def test_tls_generator_supports_exact_viewer_host_and_lan_sans(tmp_path: Path) -> None:
    tls_dir = tmp_path / "viewer-tls"
    evidence = generate_loopback_certificate(
        output_dir=tls_dir,
        evidence_path=tmp_path / "evidence/viewer-tls.json",
        subject_common_name="DESKTOP-VGD07J4",
        san_dns=["localhost", "DESKTOP-VGD07J4"],
        san_ip=["127.0.0.1", "10.5.1.240"],
    )
    certificate = x509.load_pem_x509_certificate((tls_dir / "server.crt").read_bytes())
    san = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert san.get_values_for_type(x509.DNSName) == ["localhost", "DESKTOP-VGD07J4"]
    assert san.get_values_for_type(x509.IPAddress) == [
        ipaddress.ip_address("127.0.0.1"),
        ipaddress.ip_address("10.5.1.240"),
    ]
    assert evidence["subject_common_name"] == "DESKTOP-VGD07J4"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"subject_common_name": ""},
        {"san_dns": [], "san_ip": []},
        {"san_dns": ["localhost"], "san_ip": ["not-an-ip"]},
    ],
)
def test_tls_generator_rejects_invalid_viewer_identity(
    tmp_path: Path, kwargs: dict
) -> None:
    with pytest.raises(TlsCertificateError):
        generate_loopback_certificate(
            output_dir=tmp_path / "tls",
            evidence_path=tmp_path / "evidence/tls.json",
            **kwargs,
        )


def test_preinstall_staging_is_quarantined_with_auditable_identity(tmp_path: Path) -> None:
    install_root = tmp_path / "honghu-postgresql"
    staging = tmp_path / "honghu-postgresql.staging.0123456789abcdef0123456789abcdef"
    (staging / "pgsql/bin").mkdir(parents=True)
    (staging / "pgsql/bin/postgres.exe").write_bytes(b"binary")
    output = tmp_path / "evidence/quarantine.json"
    result = quarantine_preinstall_staging(
        install_root=install_root,
        staging_root=staging,
        launch_id="a" * 32,
        primary_failure="archive contract failed",
        output_path=output,
    )
    quarantine = Path(str(result["quarantine_path"]))
    assert not staging.exists()
    assert quarantine.is_dir()
    assert result["file_count"] == 1
    assert result["total_bytes"] == 6
    assert len(str(result["file_set_sha256"])) == 64
    assert result["reusable_as_install"] is False
    assert json.loads(output.read_text(encoding="utf-8"))["primary_failure"] == (
        "archive contract failed"
    )


@pytest.mark.parametrize("case", ["foreign_path", "install_exists", "destination_exists"])
def test_preinstall_quarantine_rejects_ambiguous_or_foreign_state(
    tmp_path: Path, case: str
) -> None:
    install_root = tmp_path / "honghu-postgresql"
    staging = tmp_path / "honghu-postgresql.staging.0123456789abcdef0123456789abcdef"
    staging.mkdir()
    launch_id = "b" * 32
    if case == "foreign_path":
        staging = tmp_path / "other.staging.0123456789abcdef0123456789abcdef"
        staging.mkdir()
    elif case == "install_exists":
        install_root.mkdir()
    else:
        (tmp_path / f"honghu-postgresql.preinstall.failed.{launch_id}").mkdir()
    with pytest.raises(PreinstallQuarantineError):
        quarantine_preinstall_staging(
            install_root=install_root,
            staging_root=staging,
            launch_id=launch_id,
            primary_failure="failure",
            output_path=tmp_path / "evidence.json",
        )
