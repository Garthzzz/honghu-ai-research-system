from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tools.migration import stage4_recovery_set as recovery


def _sources(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    base = tmp_path / "source-base"
    wal = tmp_path / "source-wal"
    base.mkdir(parents=True)
    wal.mkdir()
    (base / "PG_VERSION").write_text("17\n", encoding="utf-8")
    (wal / "000000010000000000000001").write_bytes(b"wal-one")
    target = {
        "sentinel_operation_id": "op-sentinel",
        "sentinel_payload": "post-backup:op-sentinel",
        "target_lsn": "0/1000028",
        "durable_target_at_utc": "2026-08-12T01:00:05+00:00",
        "required_wal_files": ["000000010000000000000001"],
    }
    return base, wal, target


def _remote_probe(_: Path) -> dict[str, object]:
    return {
        "kind": "windows_unc",
        "server": "backup-host",
        "share": "honghu",
        "resolved_addresses": ["10.5.1.241"],
        "volume_serial": "1234abcd",
        "filesystem": "NTFS",
        "failure_domain": "remote_host_storage",
        "independent_from_source_host": True,
        "derived_storage_identity": "a" * 64,
        "identity_source": "endpoint_dns_and_volume_probe",
    }


def _build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict[str, object]]:
    base, wal, target = _sources(tmp_path)
    destination = tmp_path / "recovery-set"
    monkeypatch.setattr(recovery, "probe_storage_endpoint", _remote_probe)
    manifest = recovery.build_recovery_set(
        base_backup=base,
        wal_archive=wal,
        destination=destination,
        source_identity={"source_host_id": "source-vm", "system_identifier": "123"},
        target=target,
        expected_storage_identity="a" * 64,
        require_off_vm=True,
    )
    return destination, manifest


def test_exact_recovery_set_and_restore_source_contract_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, manifest = _build(tmp_path, monkeypatch)
    checked = recovery.verify_recovery_set(
        root,
        expected_identity=str(manifest["recovery_set_identity"]),
        expected_storage_identity="a" * 64,
    )
    assert checked["target"]["sentinel_operation_id"] == "op-sentinel"
    recovery.assert_restore_sources(root, root / "base_backup", root / "wal")


def test_local_drive_cannot_claim_off_vm(tmp_path: Path) -> None:
    base, wal, target = _sources(tmp_path)
    with pytest.raises(recovery.RecoverySetError, match="same-host storage"):
        recovery.build_recovery_set(
            base_backup=base,
            wal_archive=wal,
            destination=tmp_path / "same-host-copy",
            source_identity={"source_host_id": "source-vm"},
            target=target,
            require_off_vm=True,
        )


def test_caller_supplied_fake_storage_identity_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, wal, target = _sources(tmp_path)
    monkeypatch.setattr(recovery, "probe_storage_endpoint", _remote_probe)
    with pytest.raises(recovery.RecoverySetError, match="approved expectation"):
        recovery.build_recovery_set(
            base_backup=base,
            wal_archive=wal,
            destination=tmp_path / "copy",
            source_identity={"source_host_id": "source-vm"},
            target=target,
            expected_storage_identity="b" * 64,
            require_off_vm=True,
        )


def test_missing_required_wal_fails_before_copy(tmp_path: Path) -> None:
    base, wal, target = _sources(tmp_path)
    target["required_wal_files"] = ["000000010000000000000099"]
    with pytest.raises(recovery.RecoverySetError, match="required WAL is missing"):
        recovery.build_recovery_set(
            base_backup=base,
            wal_archive=wal,
            destination=tmp_path / "copy",
            source_identity={"source_host_id": "source-vm"},
            target=target,
            require_off_vm=False,
        )


def test_missing_or_tampered_wal_and_manifest_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, manifest = _build(tmp_path, monkeypatch)
    (root / "wal" / "000000010000000000000001").unlink()
    with pytest.raises(recovery.RecoverySetError, match="exact file set mismatch"):
        recovery.verify_recovery_set(root)

    # Rebuild and alter a declared hash without recomputing the manifest identity.
    tmp2 = tmp_path / "second"
    tmp2.mkdir()
    root2, _ = _build(tmp2, monkeypatch)
    manifest_path = root2 / recovery.MANIFEST_NAME
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["artifacts"][0]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(recovery.RecoverySetError, match="manifest identity mismatch"):
        recovery.verify_recovery_set(root2)


def test_target_without_sentinel_and_external_restore_source_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, wal, target = _sources(tmp_path)
    target["sentinel_operation_id"] = ""
    monkeypatch.setattr(recovery, "probe_storage_endpoint", _remote_probe)
    with pytest.raises(recovery.RecoverySetError, match="sentinel identity"):
        recovery.build_recovery_set(
            base_backup=base,
            wal_archive=wal,
            destination=tmp_path / "copy-invalid",
            source_identity={"source_host_id": "source-vm"},
            target=target,
            require_off_vm=True,
        )

    root, _ = _build(tmp_path / "valid", monkeypatch)
    with pytest.raises(recovery.RecoverySetError, match="outside the recovery set"):
        recovery.assert_restore_sources(root, base, wal)


def test_copy_identity_mismatch_and_measured_recovery_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, manifest = _build(tmp_path, monkeypatch)
    with pytest.raises(recovery.RecoverySetError, match="copy identity mismatch"):
        recovery.verify_recovery_set(root, expected_identity="f" * 64)

    target = manifest["target"]
    measured = recovery.measured_recovery(
        target=target,
        recovered={
            "sentinel_operation_id": "op-sentinel",
            "target_lsn_reached": True,
            "recovered_lsn": "0/1000030",
            "recovered_watermark_at_utc": "2026-08-12T01:00:02+00:00",
        },
        restore_elapsed_seconds=12.3456,
    )
    assert measured["rpo_seconds"] == 3.0
    assert measured["rto_seconds"] == 12.346
    with pytest.raises(recovery.RecoverySetError, match="sentinel"):
        recovery.measured_recovery(
            target=target,
            recovered={"sentinel_operation_id": "wrong", "target_lsn_reached": True},
            restore_elapsed_seconds=1,
        )
    with pytest.raises(recovery.RecoverySetError, match="target LSN"):
        recovery.measured_recovery(
            target=target,
            recovered={
                "sentinel_operation_id": "op-sentinel",
                "target_lsn_reached": False,
            },
            restore_elapsed_seconds=1,
        )


def test_retention_keeps_two_newest_validated_sets_and_reports_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(recovery, "probe_storage_endpoint", _remote_probe)
    root = tmp_path / "honghu-postgresql"
    root.mkdir()
    built: list[tuple[Path, dict[str, object]]] = []
    start = datetime(2026, 8, 13, tzinfo=timezone.utc)
    for index in range(3):
        source = tmp_path / f"source-{index}"
        base, wal, target = _sources(source)
        destination = root / f"set-{index}"
        manifest = recovery.build_recovery_set(
            base_backup=base,
            wal_archive=wal,
            destination=destination,
            source_identity={"source_host_id": "source-vm", "system_identifier": "123"},
            target=target,
            expected_storage_identity="a" * 64,
            require_off_vm=True,
        )
        manifest_path = destination / recovery.MANIFEST_NAME
        manifest["created_at_utc"] = (start + timedelta(hours=index)).isoformat()
        core = {key: value for key, value in manifest.items() if key != "recovery_set_identity"}
        manifest["recovery_set_identity"] = recovery.sha256_json(core)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        built.append((destination, manifest))
    incomplete = root / "interrupted-copy"
    incomplete.mkdir()
    (incomplete / "partial.bin").write_bytes(b"partial")

    result = recovery.enforce_validated_recovery_retention(
        root,
        current=built[-1][0],
        keep=2,
    )

    assert result["retained"] == ["set-2", "set-1"]
    assert result["deleted"] == ["set-0"]
    assert result["unvalidated_not_counted_or_deleted"] == ["interrupted-copy"]
    assert not built[0][0].exists()
    assert built[1][0].is_dir() and built[2][0].is_dir()
    assert incomplete.is_dir()


def test_retention_never_deletes_prior_set_when_current_is_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = _build(tmp_path / "prior", monkeypatch)
    retention_root = tmp_path / "retention"
    retention_root.mkdir()
    prior = retention_root / "prior"
    root.rename(prior)
    current = retention_root / "current"
    current.mkdir()
    (current / "partial.bin").write_bytes(b"partial")

    with pytest.raises(recovery.RecoverySetError, match="manifest is missing"):
        recovery.enforce_validated_recovery_retention(
            retention_root,
            current=current,
            keep=2,
        )
    assert prior.is_dir()


def test_retention_reuses_current_complete_verification_but_rechecks_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(recovery, "probe_storage_endpoint", _remote_probe)
    root = tmp_path / "honghu-postgresql"
    root.mkdir()
    built: list[tuple[Path, dict[str, object]]] = []
    for index in range(2):
        source = tmp_path / f"reuse-source-{index}"
        base, wal, target = _sources(source)
        destination = root / f"set-{index}"
        manifest = recovery.build_recovery_set(
            base_backup=base,
            wal_archive=wal,
            destination=destination,
            source_identity={"source_host_id": "source-vm", "index": index},
            target=target,
            expected_storage_identity="a" * 64,
            require_off_vm=True,
        )
        built.append((destination, manifest))

    original_verify = recovery.verify_recovery_set
    verified_paths: list[Path] = []

    def counted_verify(path: Path, **kwargs: object) -> dict[str, object]:
        verified_paths.append(path.resolve())
        return original_verify(path, **kwargs)

    monkeypatch.setattr(recovery, "verify_recovery_set", counted_verify)
    result = recovery.enforce_validated_recovery_retention(
        root,
        current=built[-1][0],
        keep=2,
        current_verified_manifest=built[-1][1],
    )

    assert result["retained"] == ["set-1", "set-0"]
    assert built[-1][0].resolve() not in verified_paths
    assert verified_paths == [built[0][0].resolve()]
