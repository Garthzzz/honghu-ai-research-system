from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from tools.migration.stage4_identity_mapping import build_identity_mapping
from tools.migration.stage4_readiness_preflight import evaluate_readiness


ROOT = Path(__file__).resolve().parents[2]
SUBJECT = {
    "environment_id": "vm-readiness-candidate",
    "candidate_id": "pg17-isolated-1",
    "commit_sha": "a" * 40,
    "config_sha256": "b" * 64,
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha_json(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _envelope(evidence_type: str, payload: dict) -> dict:
    return {
        "schema_version": "honghu.stage4_readiness_evidence.v1",
        "evidence_type": evidence_type,
        "subject": SUBJECT,
        "observed_at_utc": "2026-08-12T00:00:00Z",
        "valid_until_utc": "2026-08-14T00:00:00Z",
        "payload": payload,
    }


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _mapping(tmp_path: Path) -> dict:
    database = tmp_path / "mapping.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE company(id INTEGER PRIMARY KEY, name TEXT, ticker TEXT, market TEXT);
            CREATE TABLE industry(id INTEGER PRIMARY KEY, name TEXT, parent_id INTEGER);
            CREATE TABLE theme(id TEXT PRIMARY KEY, name TEXT);
            INSERT INTO company VALUES(1,'Fixture','000001.SZ','A');
            INSERT INTO industry VALUES(1,'Fixture Industry',NULL);
            INSERT INTO theme VALUES('fixture','Fixture Theme');
            """
        )
    return build_identity_mapping(database)


def _bundle(tmp_path: Path) -> tuple[dict, dict[str, Path]]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    mapping = _mapping(tmp_path)
    route_sha = hashlib.sha256(
        (ROOT / "config/migration/user_content_backend_route.json").read_bytes()
    ).hexdigest()
    adapter_rehearsal = _write(
        tmp_path / "adapter-rehearsal.json",
        {
            "status": "pass",
            "production_cutover_authorized": False,
            "live_sqlite_schema_unchanged": True,
            "live_sqlite_file_hashes_unchanged": True,
            "adapter_result": {"status": "pass"},
        },
    )
    tracked_source_paths = (
        "tools/data_platform/user_content_notes.py",
        "tools/viewer/static/analyst_note_mutations.js",
        "tools/viewer/app.py",
        "tests/viewer/test_analyst_note_browser_mutations.py",
        "tests/migration/test_stage4_user_content_rehearsal.py",
    )
    recovery_set_core = {
        "schema_version": "honghu.stage4_recovery_set.v2",
        "created_at_utc": "2026-08-12T00:00:00Z",
        "source_identity": {"source_host_id": "vm-1"},
        "storage_evidence": {
            "kind": "windows_unc",
            "failure_domain": "remote_host_storage",
            "independent_from_source_host": True,
            "derived_storage_identity": "8" * 64,
        },
        "target": {
            "sentinel_operation_id": "op-sentinel",
            "target_lsn": "0/200",
            "durable_target_at_utc": "2026-08-12T00:00:00Z",
            "required_wal_files": ["000000010000000000000001"],
        },
        "artifacts": [
            {"path": "base_backup/PG_VERSION", "role": "base_backup", "size": 3, "sha256": "9" * 64},
            {"path": "wal/000000010000000000000001", "role": "wal", "size": 3, "sha256": "a" * 64},
            {"path": "target.json", "role": "metadata", "size": 3, "sha256": "b" * 64},
        ],
    }
    recovery_set = {
        **recovery_set_core,
        "recovery_set_identity": _sha_json(recovery_set_core),
    }
    artifacts = {
        "identity_mapping_manifest": _write(tmp_path / "mapping.json", mapping),
        "identity_mapping_approval": _write(
            tmp_path / "mapping-approval.json",
            _envelope(
                "identity_mapping_approval",
                {
                    "mapping_manifest_sha256": mapping["manifest_sha256"],
                    "snapshot_identity_sha256": mapping["source_snapshot"]["snapshot_identity_sha256"],
                    "mapping_count": len(mapping["mappings"]),
                    "fallback_count": 0,
                    "cutover_level_approved": False,
                    "approval_reference": "",
                },
            ),
        ),
        "application_contract": _write(
            tmp_path / "application.json",
            _envelope(
                "application_contract",
                {
                    "tracked_route_sha256": route_sha,
                    "route": {
                        "authority_state": "S0",
                        "backend": "sqlite_transition",
                        "sqlite_writer_enabled": True,
                        "production_postgresql_enabled": False,
                    },
                    "silent_fallback": "forbidden",
                    "adapter_rehearsal": {
                        "commit_sha": SUBJECT["commit_sha"],
                        "path": adapter_rehearsal.name,
                        "artifact_sha256": _sha(adapter_rehearsal),
                        "passed_cases": [
                            "create_update_delete_api_compatibility",
                            "revision_and_idempotency",
                            "trusted_principal_actor",
                            "no_silent_fallback",
                            "s3_forward_repair",
                            "schema_compatible_code_rollback",
                        ],
                    },
                    "tracked_source_identities": {
                        relative: _sha(ROOT / relative) for relative in tracked_source_paths
                    },
                },
            ),
        ),
        "postgresql_topology": _write(
            tmp_path / "topology.json",
            _envelope(
                "postgresql_topology",
                {
                    "host": {"host_id": "vm-1"},
                    "postgresql": {
                        "version": "17.10",
                        "system_identifier": "123456789",
                        "binary_sha256": "d" * 64,
                        "provenance": {
                            "source_url": "https://www.postgresql.org/download/windows/",
                            "archive_sha256": "e" * 64,
                        },
                    },
                    "capacity": {"free_bytes": 1, "memory_bytes": 1, "cpu_count": 1},
                    "service_lifecycle": {
                        "reboot_required": False,
                        "events": [
                            {"event": "start", "result": "pass"},
                            {"event": "stop", "result": "pass"},
                            {"event": "crash_recovery", "result": "pass"},
                        ],
                    },
                    "network": {"listener_scope": "loopback", "allowed_cidrs": ["127.0.0.1/32"]},
                    "protected_transport": {
                        "verified": True,
                        "protocol": "TLSv1.3",
                        "certificate_sha256": "f" * 64,
                    },
                    "role_acl_probes": [
                        {"role": "reader", "result": "pass", "allowed": ["connect", "select"], "denied": ["insert"]},
                        {"role": "writer", "result": "pass", "allowed": ["connect", "synthetic_write"], "denied": ["controller"]},
                        {"role": "controller", "result": "pass", "allowed": ["connect"], "denied": ["synthetic_write"]},
                        {"role": "backup", "result": "pass", "allowed": ["replication"], "denied": ["synthetic_write"]},
                    ],
                    "credential_lifecycle": [
                        {"event": name, "result": "pass"}
                        for name in (
                            "create",
                            "rotate",
                            "old_credential_rejected",
                            "revoke",
                            "revoked_credential_rejected",
                        )
                    ],
                },
            ),
        ),
        "recovery": _write(
            tmp_path / "recovery.json",
            _envelope(
                "recovery",
                {
                    "source_system_identifier": "123456789",
                    "base_backup": {"backup_id": "base-1", "sha256": "1" * 64},
                    "logical_backup": {"backup_id": "logical-1", "sha256": "6" * 64},
                    "authority_backup": {"backup_id": "authority-dump-1", "sha256": "7" * 64},
                    "wal_or_incremental": {
                        "start_lsn": "0/100",
                        "end_lsn": "0/200",
                        "archive_result": "pass",
                    },
                    "recovery_set": {
                        "schema_version": "honghu.stage4_recovery_set.v2",
                        "identity": recovery_set["recovery_set_identity"],
                        "storage_evidence": recovery_set["storage_evidence"],
                        "target": recovery_set["target"],
                    },
                    "whole_database_restore": {
                        "result": "pass",
                        "source_backup_id": "base-1",
                        "verification_sha256": "2" * 64,
                    },
                    "side_restore": {
                        "result": "pass",
                        "source_backup_id": "logical-1",
                        "verification_sha256": "3" * 64,
                    },
                    "authority_recovery": {
                        "result": "pass",
                        "source_backup_id": "authority-dump-1",
                        "verification_sha256": "4" * 64,
                        "cutover_unit": "user_content_notes",
                    },
                    "off_vm_storage": {
                        "verified": True,
                        "storage_host_id": "backup-host-2",
                        "failure_domain_identity": "8" * 64,
                        "recovery_set_identity": recovery_set["recovery_set_identity"],
                    },
                    "measured": {
                        "rpo_seconds": 60,
                        "rto_seconds": 120,
                        "authority_transition_loss_count": 0,
                        "authority_verification_seconds": 30,
                    },
                },
            ),
        ),
        "recovery_set_manifest": _write(
            tmp_path / "recovery-set-manifest.json", recovery_set
        ),
        "repository_governance": _write(
            tmp_path / "repository.json",
            _envelope(
                "repository_governance",
                {
                    "repository": {
                        "required_checks_green": True,
                        "branch_protection_verified": True,
                        "production_authority_approved": False,
                    },
                    "second_company_admin_or_handover": False,
                    "two_factor_and_recovery": False,
                    "company_controlled_deploy_credential": False,
                },
            ),
        ),
        "cutover_decision": _write(
            tmp_path / "cutover.json",
            _envelope(
                "cutover_decision",
                {
                    "writer_fence_plan_verified": True,
                    "rollback_recovery_decision_tree_verified": True,
                    "tracked_plan_identities": {
                        "openspec/changes/github-vm-dual-node-operations/stage4/stage4_execution_plan.md": _sha(
                            ROOT
                            / "openspec/changes/github-vm-dual-node-operations/stage4/stage4_execution_plan.md"
                        )
                    },
                    **{
                        name: {"approved": False, "approval_reference": ""}
                        for name in ("operator", "approver", "maintenance_window", "enter_s2_approval")
                    },
                },
            ),
        ),
    }
    bundle = {
        "schema_version": "honghu.stage4_user_content_readiness_bundle.v3",
        "cutover_unit": "user_content_notes",
        "production_cutover_authorized": False,
        "evidence_cutoff_utc": "2026-08-13T00:00:00Z",
        "subject": SUBJECT,
        "artifacts": {
            name: {
                "evidence_type": name,
                "path": path.name,
                "sha256": _sha(path),
            }
            for name, path in artifacts.items()
        },
    }
    return bundle, artifacts


def test_shape_only_template_is_blocked_and_does_not_self_authorize(tmp_path) -> None:
    payload = json.loads(
        (ROOT / "config/migration/stage4_user_content_readiness_template.json").read_text(encoding="utf-8")
    )
    result = evaluate_readiness(root=ROOT, evidence=payload, evidence_root=tmp_path)
    assert result["status"] == "blocked"
    assert result["production_cutover_authorized"] is False
    assert any("artifact is missing" in item or "artifact path" in item for item in result["engineering_blockers"])


def test_real_evidence_can_only_be_ready_to_request_human_authorization(tmp_path) -> None:
    bundle, _ = _bundle(tmp_path)
    result = evaluate_readiness(root=ROOT, evidence=bundle, evidence_root=tmp_path)
    assert result["status"] == "ready_to_request_production_authorization"
    assert result["production_cutover_authorized"] is False
    assert result["engineering_blockers"] == []
    assert "identity mapping requires user cutover-level approval" in result["human_decisions"]
    assert any("maintenance_window" in item for item in result["human_decisions"])


def test_true_values_and_well_formed_hashes_do_not_replace_evidence_bodies(tmp_path) -> None:
    payload = {
        "schema_version": "honghu.stage4_user_content_production_readiness.v1",
        "cutover_unit": "user_content_notes",
        "production_cutover_authorized": False,
        "verified": True,
        "sha256": "a" * 64,
    }
    result = evaluate_readiness(root=ROOT, evidence=payload, evidence_root=tmp_path)
    assert result["status"] == "blocked"
    assert any("shape-only v1" in item for item in result["engineering_blockers"])


def test_tampered_artifact_and_cross_environment_evidence_fail_closed(tmp_path) -> None:
    bundle, artifacts = _bundle(tmp_path)
    artifacts["recovery"].write_text("{}\n", encoding="utf-8")
    result = evaluate_readiness(root=ROOT, evidence=bundle, evidence_root=tmp_path)
    assert "recovery: artifact SHA256 mismatch" in result["engineering_blockers"]

    bundle, artifacts = _bundle(tmp_path / "second")
    recovery = json.loads(artifacts["recovery"].read_text(encoding="utf-8"))
    recovery["subject"] = {**SUBJECT, "environment_id": "another-vm"}
    _write(artifacts["recovery"], recovery)
    bundle["artifacts"]["recovery"]["sha256"] = _sha(artifacts["recovery"])
    result = evaluate_readiness(root=ROOT, evidence=bundle, evidence_root=tmp_path / "second")
    assert "recovery: common subject mismatch" in result["engineering_blockers"]


def test_same_vm_backup_cannot_masquerade_as_off_vm(tmp_path) -> None:
    bundle, artifacts = _bundle(tmp_path)
    recovery = json.loads(artifacts["recovery"].read_text(encoding="utf-8"))
    manifest = json.loads(
        artifacts["recovery_set_manifest"].read_text(encoding="utf-8")
    )
    manifest["storage_evidence"]["failure_domain"] = "source_host"
    manifest["storage_evidence"]["independent_from_source_host"] = False
    core = {key: value for key, value in manifest.items() if key != "recovery_set_identity"}
    manifest["recovery_set_identity"] = _sha_json(core)
    _write(artifacts["recovery_set_manifest"], manifest)
    recovery["payload"]["recovery_set"]["identity"] = manifest["recovery_set_identity"]
    recovery["payload"]["recovery_set"]["storage_evidence"] = manifest["storage_evidence"]
    recovery["payload"]["off_vm_storage"]["recovery_set_identity"] = manifest["recovery_set_identity"]
    recovery["payload"]["off_vm_storage"]["failure_domain_identity"] = "8" * 64
    _write(artifacts["recovery"], recovery)
    bundle["artifacts"]["recovery"]["sha256"] = _sha(artifacts["recovery"])
    bundle["artifacts"]["recovery_set_manifest"]["sha256"] = _sha(
        artifacts["recovery_set_manifest"]
    )
    result = evaluate_readiness(root=ROOT, evidence=bundle, evidence_root=tmp_path)
    assert "same-host storage cannot be claimed as off-VM" in result["engineering_blockers"]
