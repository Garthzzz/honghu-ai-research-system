from __future__ import annotations

import json
import base64
import hashlib
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

from tools.migration.stage4_recovery_set import sha256_file, sha256_json
from tools.operations import wal_offvm_sync
from tools.operations.storage_identity_transition import (
    COLLECTOR_SCHEMA,
    COLLECTOR_SIGNATURE_SCHEMA,
    COLLECTOR_SIGNED_FACTS_SCHEMA,
    REMOTE_ATTESTATION_SCHEMA,
    STAGE5_EXECUTION_AUTHORIZATION_REFERENCE,
    TRANSITION_REASON,
    TRANSITION_SCHEMA,
    artifact_anchor_identity,
    collector_script_sha256,
    endpoint_identity,
    verify_storage_identity_transition as verify_signed_storage_transition,
)
from tools.operations.wal_offvm_sync import WalSyncError, sync_archived_wal, verify_wal_sync


IDENTITY = "a" * 64
NOW = datetime(2026, 8, 16, 1, 0, 0, tzinfo=timezone.utc)

_TEST_KEY = rsa.generate_private_key(public_exponent=65537, key_size=3072)
_TEST_CERT = (
    x509.CertificateBuilder()
    .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "HonghuStage5StorageAttestation")]))
    .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "HonghuStage5StorageAttestation")]))
    .public_key(_TEST_KEY.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(datetime(2025, 1, 1, tzinfo=timezone.utc))
    .not_valid_after(datetime(2030, 1, 1, tzinfo=timezone.utc))
    .sign(_TEST_KEY, hashes.SHA256())
)
_TEST_CERT_DIR = tempfile.TemporaryDirectory()
TEST_CERT_PATH = Path(_TEST_CERT_DIR.name) / "collector.cer"
TEST_CERT_PATH.write_bytes(_TEST_CERT.public_bytes(serialization.Encoding.DER))
TEST_CERT_SHA256 = hashlib.sha256(TEST_CERT_PATH.read_bytes()).hexdigest()


def _collector_signature(signed_facts: dict[str, object]) -> dict[str, object]:
    payload = json.dumps(
        signed_facts, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    signature = _TEST_KEY.sign(
        payload,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
        hashes.SHA256(),
    )
    return {
        "schema_version": COLLECTOR_SIGNATURE_SCHEMA,
        "algorithm": "rsa-pss-sha256",
        "certificate_sha256": TEST_CERT_SHA256,
        "certificate_thumbprint": _TEST_CERT.fingerprint(hashes.SHA1()).hex(),
        "signed_payload_sha256": hashlib.sha256(payload).hexdigest(),
        "signed_payload_base64": base64.b64encode(payload).decode("ascii"),
        "signature_base64": base64.b64encode(signature).decode("ascii"),
    }


def _boundary(first: str = "000000010000000000000001") -> dict[str, object]:
    return {
        "schema_version": wal_offvm_sync.INITIAL_BOUNDARY_SCHEMA,
        "verified": True,
        "base_recovery_set_identity_sha256": "d" * 64,
        "first_required_wal_segment": first,
        "storage_identity": IDENTITY,
        "verified_at_utc": (NOW - timedelta(minutes=5)).isoformat(),
    }


def _remote_storage(_: Path) -> dict[str, object]:
    return {
        "kind": "windows_unc",
        "server": "backup-host",
        "share": "honghupgrecovery",
        "resolved_addresses": ["10.0.0.8"],
        "volume_serial": "1234abcd",
        "filesystem": "NTFS",
        "failure_domain": "remote_host_storage",
        "independent_from_source_host": True,
        "derived_storage_identity": IDENTITY,
        "identity_source": "endpoint_dns_and_volume_probe",
    }


def _local_storage(_: Path) -> dict[str, object]:
    return {
        "kind": "local_filesystem",
        "failure_domain": "source_host",
        "independent_from_source_host": False,
        "derived_storage_identity": "b" * 64,
    }


def _wal(source: Path, name: str, payload: bytes) -> None:
    source.mkdir(parents=True, exist_ok=True)
    (source / name).write_bytes(payload)


def _sync(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict[str, object]]:
    monkeypatch.setattr(wal_offvm_sync, "probe_storage_endpoint", _remote_storage)
    source = tmp_path / "archive"
    destination = tmp_path / "offvm"
    _wal(source, "000000010000000000000001", b"wal-1")
    _wal(source, "000000010000000000000002", b"wal-2")
    result = sync_archived_wal(
        source_archive=source,
        destination=destination,
        recoverable_target_at=NOW - timedelta(seconds=2),
        target_wal_segment="000000010000000000000002",
        expected_storage_identity=IDENTITY,
        initial_recovery_boundary=_boundary(),
        now=NOW,
    )
    return destination, result


def _rewrite_current_manifest_as_legacy(destination: Path) -> None:
    pointer_path = destination / "latest_verified_wal_manifest.json"
    pointer = json.loads(pointer_path.read_text())
    old_path = destination / pointer["manifest_path"]
    manifest = json.loads(old_path.read_text())
    manifest.pop("integrity_verification")
    manifest.pop("manifest_identity_sha256")
    identity = sha256_json(manifest)
    manifest["manifest_identity_sha256"] = identity
    new_path = destination / "manifests" / f"{identity}.json"
    new_path.write_text(json.dumps(manifest), encoding="utf-8")
    old_path.unlink()
    pointer["manifest_path"] = f"manifests/{identity}.json"
    pointer["manifest_identity_sha256"] = identity
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")


def test_sync_copies_contiguous_wal_and_publishes_immutable_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination, result = _sync(tmp_path, monkeypatch)
    assert result["verified"] is True
    assert result["artifact_count"] == 2
    assert result["continuous_rpo_measured"] is False
    assert result["at_rest_encryption"]["status"] == "unknown"
    pointer = json.loads((destination / "latest_verified_wal_manifest.json").read_text())
    manifest_path = destination / pointer["manifest_path"]
    assert manifest_path.is_file()
    assert pointer["manifest_identity_sha256"] in manifest_path.name


def test_sync_accepts_powershell_seven_digit_boundary_timestamp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wal_offvm_sync, "probe_storage_endpoint", _remote_storage)
    source = tmp_path / "archive"
    destination = tmp_path / "offvm"
    first = "000000010000000000000001"
    _wal(source, first, b"wal")
    boundary = _boundary(first)
    boundary["verified_at_utc"] = "2026-08-16T19:18:01.9167873+00:00"
    result = sync_archived_wal(
        source_archive=source,
        destination=destination,
        recoverable_target_at=NOW - timedelta(seconds=2),
        target_wal_segment=first,
        expected_storage_identity=IDENTITY,
        initial_recovery_boundary=boundary,
        now=NOW,
    )
    assert result["verified"] is True


def test_one_time_endpoint_transition_reuses_verified_wal_and_only_copies_delta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_core = {
        "kind": "windows_unc",
        "server": "old-endpoint",
        "share": "honghupgrecovery",
        "resolved_addresses": ["10.0.0.8"],
        "volume_serial": "1234abcd",
        "filesystem": "NTFS",
    }
    new_core = {**old_core, "server": "new-endpoint", "resolved_addresses": ["10.0.0.9"]}
    old_identity = endpoint_identity(old_core)
    new_identity = endpoint_identity(new_core)
    old_storage = {
        **old_core,
        "failure_domain": "remote_host_storage",
        "independent_from_source_host": True,
        "derived_storage_identity": old_identity,
    }
    new_storage = {
        **new_core,
        "failure_domain": "remote_host_storage",
        "independent_from_source_host": True,
        "derived_storage_identity": new_identity,
    }
    source = tmp_path / "archive"
    destination = tmp_path / "offvm"
    first = "000000010000000000000001"
    second = "000000010000000000000002"
    third = "000000010000000000000003"
    fourth = "000000010000000000000004"
    fifth = "000000010000000000000005"
    for index, name in enumerate((first, second, third, fourth, fifth), start=1):
        _wal(source, name, f"wal-{index}".encode())
    boundary = {
        "schema_version": wal_offvm_sync.INITIAL_BOUNDARY_SCHEMA,
        "verified": True,
        "base_recovery_set_identity_sha256": "d" * 64,
        "first_required_wal_segment": first,
        "storage_identity": old_identity,
        "verified_at_utc": (NOW - timedelta(minutes=5)).isoformat(),
    }
    old_at_rest = {
        "schema_version": "honghu.storage_at_rest_encryption.v1",
        "status": "verified",
        "verification_method": "windows_bitlocker_volume_probe",
        "storage_identity": old_identity,
        "checked_at_utc": (NOW - timedelta(minutes=2)).isoformat(),
        "volume_encryption_enabled": True,
    }
    monkeypatch.setattr(wal_offvm_sync, "probe_storage_endpoint", lambda _: old_storage)
    sync_archived_wal(
        source_archive=source,
        destination=destination,
        recoverable_target_at=NOW - timedelta(seconds=2),
        target_wal_segment=second,
        expected_storage_identity=old_identity,
        at_rest_encryption_evidence=old_at_rest,
        initial_recovery_boundary=boundary,
        now=NOW,
    )
    pointer_path = destination / "latest_verified_wal_manifest.json"
    pointer = json.loads(pointer_path.read_text())
    manifest_path = destination / pointer["manifest_path"]
    manifest = json.loads(manifest_path.read_text())
    artifacts_identity = sha256_json(manifest["artifacts"])
    anchor = artifact_anchor_identity(
        pointer_sha256=sha256_file(pointer_path),
        manifest_identity_sha256=manifest["manifest_identity_sha256"],
        manifest_file_sha256=sha256_file(manifest_path),
        artifacts_identity_sha256=artifacts_identity,
        artifact_count=manifest["artifact_count"],
    )
    remote_machine = "2" * 64
    source_machine = "1" * 64
    collector_core = {
        "schema_version": COLLECTOR_SCHEMA,
        "collector_script_sha256": collector_script_sha256(),
        "host_name": "win-g7vo0dd37ce",
        "checked_at_utc": (NOW + timedelta(seconds=10)).isoformat(),
        "share_name": "honghupgrecovery",
        "share_local_path": r"D:\quant\industry_demo_backup_package\postgresql_recovery",
        "approved_backup_root": r"D:\quant\industry_demo_backup_package\postgresql_recovery",
        "share_local_path_verified": True,
        "unc_live_probe_path": r"\\new-endpoint\honghupgrecovery",
        "smb_endpoint_tcp_445_verified": True,
        "smb_transport_encryption_required": True,
        "machine_guid_sha256": remote_machine,
        "volume_serial": "1234abcd",
        "filesystem": "NTFS",
        "bitlocker": {
            "protection_status": "On",
            "volume_status": "FullyEncrypted",
            "encryption_percentage": 100.0,
            "verified": True,
        },
        "artifact_hashes_verified": True,
    }
    collector = {
        **collector_core,
        "collector_identity_sha256": sha256_json(collector_core),
    }
    attestation_core = {
        "schema_version": REMOTE_ATTESTATION_SCHEMA,
        "machine_guid_sha256": remote_machine,
        "share": "honghupgrecovery",
        "volume_serial": "1234abcd",
        "filesystem": "NTFS",
        "current_addresses": ["10.0.0.9"],
        "checked_at_utc": (NOW + timedelta(seconds=10)).isoformat(),
        "artifact_anchor_identity_sha256": anchor,
        "collector_identity_sha256": collector["collector_identity_sha256"],
    }
    attestation = {
        **attestation_core,
        "attestation_identity_sha256": sha256_json(attestation_core),
    }
    new_at_rest = {
        "schema_version": "honghu.storage_at_rest_encryption.v1",
        "status": "verified",
        "verification_method": "windows_bitlocker_volume_probe",
        "storage_identity": new_identity,
        "checked_at_utc": (NOW + timedelta(seconds=10)).isoformat(),
        "volume_encryption_enabled": True,
    }
    new_at_rest_identity = sha256_json(
        {key: new_at_rest[key] for key in sorted(new_at_rest)}
    )
    signed_facts = {
        "schema_version": COLLECTOR_SIGNED_FACTS_SCHEMA,
        "authorization_reference": STAGE5_EXECUTION_AUTHORIZATION_REFERENCE,
        "collector": collector_core,
        "source_host_identity_evidence": None,
        "source_machine_guid_sha256": source_machine,
        "old_endpoint_core": old_core,
        "new_endpoint_core": new_core,
        "old_storage_identity": old_identity,
        "new_storage_identity": new_identity,
        "prior_pointer_sha256": sha256_file(pointer_path),
        "prior_manifest_identity_sha256": manifest["manifest_identity_sha256"],
        "prior_manifest_file_sha256": sha256_file(manifest_path),
        "prior_artifacts": manifest["artifacts"],
        "prior_artifacts_identity_sha256": artifacts_identity,
        "prior_artifact_count": manifest["artifact_count"],
        "initial_boundary_evidence_identity_sha256": manifest[
            "initial_recovery_boundary"
        ]["evidence_identity_sha256"],
        "old_at_rest_evidence_identity_sha256": manifest["at_rest_encryption"][
            "evidence_identity_sha256"
        ],
        "artifact_anchor_identity_sha256": anchor,
    }
    transition_core = {
        "schema_version": TRANSITION_SCHEMA,
        "approved": True,
        "approved_at_utc": (NOW + timedelta(seconds=20)).isoformat(),
        "authorization_reference": STAGE5_EXECUTION_AUTHORIZATION_REFERENCE,
        "reason": TRANSITION_REASON,
        "collector_signed_facts": signed_facts,
        "collector_signature": _collector_signature(signed_facts),
        "collector": collector,
        "old_endpoint_core": old_core,
        "new_endpoint_core": new_core,
        "source_machine_guid_sha256": source_machine,
        "remote_host_attestation": attestation,
        "old_storage_identity": old_identity,
        "new_storage_identity": new_identity,
        "prior_pointer_sha256": sha256_file(pointer_path),
        "prior_manifest_identity_sha256": manifest["manifest_identity_sha256"],
        "prior_manifest_file_sha256": sha256_file(manifest_path),
        "prior_artifacts_identity_sha256": artifacts_identity,
        "prior_artifact_count": manifest["artifact_count"],
        "initial_boundary_evidence_identity_sha256": manifest[
            "initial_recovery_boundary"
        ]["evidence_identity_sha256"],
        "old_at_rest_evidence_identity_sha256": manifest["at_rest_encryption"][
            "evidence_identity_sha256"
        ],
        "new_at_rest_evidence_identity_sha256": new_at_rest_identity,
        "artifact_anchor_identity_sha256": anchor,
    }
    transition = {
        **transition_core,
        "transition_identity_sha256": sha256_json(transition_core),
    }
    old_mtime = (destination / "wal" / first).stat().st_mtime_ns
    monkeypatch.setattr(wal_offvm_sync, "probe_storage_endpoint", lambda _: new_storage)
    monkeypatch.setattr(
        wal_offvm_sync,
        "local_machine_guid_sha256",
        lambda: source_machine,
    )
    monkeypatch.setattr(
        wal_offvm_sync,
        "verify_storage_identity_transition",
        lambda evidence, **kwargs: verify_signed_storage_transition(
            evidence,
            **kwargs,
            public_certificate_path=TEST_CERT_PATH,
            expected_certificate_sha256=TEST_CERT_SHA256,
        ),
    )
    result = sync_archived_wal(
        source_archive=source,
        destination=destination,
        recoverable_target_at=NOW + timedelta(seconds=30),
        target_wal_segment=third,
        expected_storage_identity=new_identity,
        at_rest_encryption_evidence=new_at_rest,
        initial_recovery_boundary=boundary,
        storage_identity_transition=transition,
        now=NOW + timedelta(minutes=1),
    )
    assert result["verified"] is True
    assert result["storage_identity_transition"]["transition_identity_sha256"] == transition[
        "transition_identity_sha256"
    ]
    assert (destination / "wal" / first).stat().st_mtime_ns == old_mtime
    # The same transition document remains required, but cannot create a
    # second identity hop.  A later cycle only appends the next delta.
    second_result = sync_archived_wal(
        source_archive=source,
        destination=destination,
        recoverable_target_at=NOW + timedelta(minutes=1, seconds=30),
        target_wal_segment=fourth,
        expected_storage_identity=new_identity,
        at_rest_encryption_evidence=new_at_rest,
        initial_recovery_boundary=boundary,
        storage_identity_transition=transition,
        now=NOW + timedelta(minutes=2),
    )
    assert second_result["verified"] is True
    assert len(list((destination / "manifests").glob("*.json"))) == 2
    third_core = {
        **new_core,
        "server": "third-endpoint",
        "resolved_addresses": ["10.0.0.10"],
    }
    third_storage = {
        **third_core,
        "failure_domain": "remote_host_storage",
        "independent_from_source_host": True,
        "derived_storage_identity": endpoint_identity(third_core),
    }
    monkeypatch.setattr(wal_offvm_sync, "probe_storage_endpoint", lambda _: third_storage)
    with pytest.raises(WalSyncError, match="second storage identity transition"):
        sync_archived_wal(
            source_archive=source,
            destination=destination,
            recoverable_target_at=NOW + timedelta(minutes=2, seconds=30),
            target_wal_segment=fifth,
            expected_storage_identity=third_storage["derived_storage_identity"],
            at_rest_encryption_evidence={
                **new_at_rest,
                "storage_identity": third_storage["derived_storage_identity"],
            },
            initial_recovery_boundary=boundary,
            storage_identity_transition=transition,
            now=NOW + timedelta(minutes=3),
        )


def test_local_path_never_counts_as_offvm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wal_offvm_sync, "probe_storage_endpoint", _local_storage)
    source = tmp_path / "archive"
    _wal(source, "000000010000000000000001", b"wal")
    with pytest.raises(WalSyncError, match="cannot satisfy off-VM"):
        sync_archived_wal(
            source_archive=source,
            destination=tmp_path / "another-drive",
            recoverable_target_at=NOW,
            target_wal_segment="000000010000000000000001",
            initial_recovery_boundary=_boundary(),
            now=NOW,
        )


def test_source_gap_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wal_offvm_sync, "probe_storage_endpoint", _remote_storage)
    source = tmp_path / "archive"
    _wal(source, "000000010000000000000001", b"wal-1")
    _wal(source, "000000010000000000000003", b"wal-3")
    with pytest.raises(WalSyncError, match="gap"):
        sync_archived_wal(
            source_archive=source,
            destination=tmp_path / "offvm",
            recoverable_target_at=NOW,
            target_wal_segment="000000010000000000000003",
            initial_recovery_boundary=_boundary(),
            now=NOW,
        )


def test_target_segment_must_exist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wal_offvm_sync, "probe_storage_endpoint", _remote_storage)
    source = tmp_path / "archive"
    _wal(source, "000000010000000000000001", b"wal-1")
    with pytest.raises(WalSyncError, match="not durably present"):
        sync_archived_wal(
            source_archive=source,
            destination=tmp_path / "offvm",
            recoverable_target_at=NOW,
            target_wal_segment="000000010000000000000002",
            initial_recovery_boundary=_boundary(),
            now=NOW,
        )


def test_existing_different_wal_is_never_overwritten(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination, _ = _sync(tmp_path, monkeypatch)
    path = destination / "wal" / "000000010000000000000002"
    path.write_bytes(b"tampered")
    source = tmp_path / "archive"
    with pytest.raises(WalSyncError, match="integrity mismatch"):
        sync_archived_wal(
            source_archive=source,
            destination=destination,
            recoverable_target_at=NOW,
            target_wal_segment="000000010000000000000002",
            expected_storage_identity=IDENTITY,
            now=NOW,
        )
    assert path.read_bytes() == b"tampered"


def test_tampered_manifest_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    destination, _ = _sync(tmp_path, monkeypatch)
    pointer_path = destination / "latest_verified_wal_manifest.json"
    pointer = json.loads(pointer_path.read_text())
    manifest_path = destination / pointer["manifest_path"]
    manifest = json.loads(manifest_path.read_text())
    manifest["artifact_count"] = 999
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(WalSyncError, match="manifest identity"):
        verify_wal_sync(
            destination=destination,
            expected_storage_identity=IDENTITY,
            max_age_seconds=60,
            now=NOW,
        )


def test_stale_manifest_fails_freshness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    destination, _ = _sync(tmp_path, monkeypatch)
    with pytest.raises(WalSyncError, match="stale"):
        verify_wal_sync(
            destination=destination,
            expected_storage_identity=IDENTITY,
            max_age_seconds=5,
            now=NOW + timedelta(seconds=6),
        )


def test_recent_manifest_cannot_hide_stale_recoverable_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wal_offvm_sync, "probe_storage_endpoint", _remote_storage)
    source = tmp_path / "archive"
    destination = tmp_path / "offvm"
    _wal(source, "000000010000000000000001", b"wal")
    sync_archived_wal(
        source_archive=source,
        destination=destination,
        recoverable_target_at=NOW - timedelta(hours=1),
        target_wal_segment="000000010000000000000001",
        initial_recovery_boundary=_boundary(),
        now=NOW,
    )
    with pytest.raises(WalSyncError, match="stale"):
        verify_wal_sync(
            destination=destination,
            max_age_seconds=60,
            now=NOW,
        )


def test_wrong_storage_identity_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    destination, _ = _sync(tmp_path, monkeypatch)
    with pytest.raises(WalSyncError, match="approved endpoint"):
        verify_wal_sync(
            destination=destination,
            expected_storage_identity="f" * 64,
            max_age_seconds=60,
            now=NOW,
        )


def test_idempotent_same_content_sync_does_not_rewrite_wal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination, first = _sync(tmp_path, monkeypatch)
    wal_path = destination / "wal" / "000000010000000000000001"
    before = wal_path.stat().st_mtime_ns
    second = sync_archived_wal(
        source_archive=tmp_path / "archive",
        destination=destination,
        recoverable_target_at=NOW - timedelta(seconds=2),
        target_wal_segment="000000010000000000000002",
        expected_storage_identity=IDENTITY,
        now=NOW + timedelta(milliseconds=1),
    )
    assert wal_path.stat().st_mtime_ns == before
    assert second["verified"] is True
    assert first["last_wal_segment"] == second["last_wal_segment"]


def test_verified_at_rest_encryption_must_bind_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wal_offvm_sync, "probe_storage_endpoint", _remote_storage)
    source = tmp_path / "archive"
    _wal(source, "000000010000000000000001", b"wal")
    evidence = {
        "schema_version": "honghu.storage_at_rest_encryption.v1",
        "status": "verified",
        "verification_method": "windows_bitlocker_volume_probe",
        "storage_identity": "c" * 64,
        "checked_at_utc": NOW.isoformat(),
        "volume_encryption_enabled": True,
    }
    with pytest.raises(WalSyncError, match="not bound"):
        sync_archived_wal(
            source_archive=source,
            destination=tmp_path / "offvm",
            recoverable_target_at=NOW,
            target_wal_segment="000000010000000000000001",
            at_rest_encryption_evidence=evidence,
            initial_recovery_boundary=_boundary(),
            now=NOW,
        )


def test_first_sync_requires_explicit_verified_base_recovery_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wal_offvm_sync, "probe_storage_endpoint", _remote_storage)
    source = tmp_path / "archive"
    _wal(source, "000000010000000000000001", b"old")
    _wal(source, "000000010000000000000002", b"target")
    with pytest.raises(WalSyncError, match="first-required WAL boundary"):
        sync_archived_wal(
            source_archive=source,
            destination=tmp_path / "offvm",
            recoverable_target_at=NOW,
            target_wal_segment="000000010000000000000002",
            now=NOW,
        )


def test_first_sync_starts_at_verified_boundary_not_archive_origin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wal_offvm_sync, "probe_storage_endpoint", _remote_storage)
    source = tmp_path / "archive"
    for number in range(1, 6):
        _wal(source, f"00000001000000000000000{number}", f"wal-{number}".encode())
    destination = tmp_path / "offvm"
    result = sync_archived_wal(
        source_archive=source,
        destination=destination,
        recoverable_target_at=NOW,
        target_wal_segment="000000010000000000000005",
        initial_recovery_boundary=_boundary("000000010000000000000004"),
        now=NOW,
    )
    assert result["first_wal_segment"] == "000000010000000000000004"
    assert result["artifact_count"] == 2
    assert not (destination / "wal" / "000000010000000000000001").exists()


def test_initial_boundary_must_bind_approved_offvm_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wal_offvm_sync, "probe_storage_endpoint", _remote_storage)
    source = tmp_path / "archive"
    _wal(source, "000000010000000000000001", b"wal")
    boundary = _boundary()
    boundary["storage_identity"] = "e" * 64
    with pytest.raises(WalSyncError, match="another off-VM storage"):
        sync_archived_wal(
            source_archive=source,
            destination=tmp_path / "offvm",
            recoverable_target_at=NOW,
            target_wal_segment="000000010000000000000001",
            initial_recovery_boundary=boundary,
            now=NOW,
        )


def test_only_two_latest_immutable_wal_manifests_are_retained(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wal_offvm_sync, "probe_storage_endpoint", _remote_storage)
    source = tmp_path / "archive"
    destination = tmp_path / "offvm"
    for number in range(1, 4):
        _wal(source, f"00000001000000000000000{number}", f"wal-{number}".encode())
    identities: list[str] = []
    for number in range(1, 4):
        result = sync_archived_wal(
            source_archive=source,
            destination=destination,
            recoverable_target_at=NOW + timedelta(seconds=number),
            target_wal_segment=f"00000001000000000000000{number}",
            initial_recovery_boundary=_boundary() if number == 1 else None,
            now=NOW + timedelta(seconds=number),
        )
        identities.append(result["manifest_identity_sha256"])
    retained = {path.stem for path in (destination / "manifests").glob("*.json")}
    assert retained == set(identities[-2:])
    assert result["retention"]["retained_manifest_count"] == 2
    assert result["retention"]["wal_artifacts_pruned"] is False


def test_incremental_cycle_reuses_prior_verified_hashes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination, _ = _sync(tmp_path, monkeypatch)
    source = tmp_path / "archive"
    third = "000000010000000000000003"
    _wal(source, third, b"wal-3")
    original = wal_offvm_sync.sha256_file
    hashed: list[Path] = []

    def observed_hash(path: Path) -> str:
        hashed.append(Path(path))
        return original(path)

    monkeypatch.setattr(wal_offvm_sync, "sha256_file", observed_hash)
    result = sync_archived_wal(
        source_archive=source,
        destination=destination,
        recoverable_target_at=NOW + timedelta(seconds=1),
        target_wal_segment=third,
        expected_storage_identity=IDENTITY,
        now=NOW + timedelta(seconds=1),
    )
    assert result["verification_mode"] == "incremental_chain"
    assert result["full_content_verified_this_call"] is False
    assert result["integrity_verification"]["reused_artifact_count"] == 2
    assert result["integrity_verification"]["newly_verified_artifact_count"] == 1
    assert result["integrity_verification"]["full_scrub_performed_this_cycle"] is False
    assert all(path.name not in {
        "000000010000000000000001",
        "000000010000000000000002",
    } for path in hashed)
    assert {path.name for path in hashed} == {third, f".{third}.{wal_offvm_sync.os.getpid()}.tmp"}


def test_legacy_v1_manifest_is_reused_as_recent_full_scrub_anchor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination, _ = _sync(tmp_path, monkeypatch)
    _rewrite_current_manifest_as_legacy(destination)
    source = tmp_path / "archive"
    third = "000000010000000000000003"
    _wal(source, third, b"wal-3")
    original = wal_offvm_sync.sha256_file
    hashed: list[str] = []

    def observed_hash(path: Path) -> str:
        hashed.append(Path(path).name)
        return original(path)

    monkeypatch.setattr(wal_offvm_sync, "sha256_file", observed_hash)
    result = sync_archived_wal(
        source_archive=source,
        destination=destination,
        recoverable_target_at=NOW + timedelta(seconds=1),
        target_wal_segment=third,
        expected_storage_identity=IDENTITY,
        now=NOW + timedelta(seconds=1),
    )
    assert result["integrity_verification"]["full_scrub_performed_this_cycle"] is False
    assert "000000010000000000000001" not in hashed
    assert "000000010000000000000002" not in hashed


def test_incremental_cycle_still_fails_on_missing_prior_segment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination, _ = _sync(tmp_path, monkeypatch)
    (destination / "wal" / "000000010000000000000001").unlink()
    _wal(tmp_path / "archive", "000000010000000000000003", b"wal-3")
    with pytest.raises(WalSyncError, match="missing or unsafe"):
        sync_archived_wal(
            source_archive=tmp_path / "archive",
            destination=destination,
            recoverable_target_at=NOW + timedelta(seconds=1),
            target_wal_segment="000000010000000000000003",
            expected_storage_identity=IDENTITY,
            now=NOW + timedelta(seconds=1),
        )


def test_overdue_full_scrub_detects_same_size_historical_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination, _ = _sync(tmp_path, monkeypatch)
    (destination / "wal" / "000000010000000000000001").write_bytes(b"evil!")
    _wal(tmp_path / "archive", "000000010000000000000003", b"wal-3")
    with pytest.raises(WalSyncError, match="integrity mismatch"):
        sync_archived_wal(
            source_archive=tmp_path / "archive",
            destination=destination,
            recoverable_target_at=NOW + timedelta(seconds=61),
            target_wal_segment="000000010000000000000003",
            expected_storage_identity=IDENTITY,
            now=NOW + timedelta(seconds=61),
            max_full_scrub_age_seconds=60,
        )


def test_explicit_full_verification_detects_historical_tamper_before_scrub_due(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination, _ = _sync(tmp_path, monkeypatch)
    (destination / "wal" / "000000010000000000000001").write_bytes(b"evil!")
    with pytest.raises(WalSyncError, match="integrity mismatch"):
        verify_wal_sync(
            destination=destination,
            expected_storage_identity=IDENTITY,
            max_age_seconds=60,
            now=NOW,
        )


def test_overdue_clean_chain_runs_full_scrub_then_continues_incrementally(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination, _ = _sync(tmp_path, monkeypatch)
    third = "000000010000000000000003"
    _wal(tmp_path / "archive", third, b"wal-3")
    result = sync_archived_wal(
        source_archive=tmp_path / "archive",
        destination=destination,
        recoverable_target_at=NOW + timedelta(seconds=61),
        target_wal_segment=third,
        expected_storage_identity=IDENTITY,
        now=NOW + timedelta(seconds=61),
        max_full_scrub_age_seconds=60,
    )
    integrity = result["integrity_verification"]
    assert integrity["full_scrub_performed_this_cycle"] is True
    assert integrity["last_full_scrub_age_seconds"] == 0
    assert integrity["reused_artifact_count"] == 2
    assert integrity["newly_verified_artifact_count"] == 1
