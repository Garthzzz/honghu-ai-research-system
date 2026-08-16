from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tools.migration.stage4_recovery_set import sha256_json
from tools.operations import wal_offvm_sync
from tools.operations.wal_offvm_sync import WalSyncError, sync_archived_wal, verify_wal_sync


IDENTITY = "a" * 64
NOW = datetime(2026, 8, 16, 1, 0, 0, tzinfo=timezone.utc)


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
        "share": "recovery",
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
