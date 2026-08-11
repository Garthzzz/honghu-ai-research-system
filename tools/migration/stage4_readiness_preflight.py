from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from tools.data_platform.routing import AuthorityState, Backend, load_cutover_route


SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha(value: Any) -> bool:
    return bool(SHA256.fullmatch(str(value or "")))


def evaluate_readiness(
    *,
    root: Path,
    evidence: dict[str, Any],
    identity_mapping_path: Path | None = None,
) -> dict[str, Any]:
    blockers: list[str] = []
    if evidence.get("schema_version") != "honghu.stage4_user_content_production_readiness.v1":
        blockers.append("unsupported readiness evidence schema")
    if evidence.get("cutover_unit") != "user_content_notes":
        blockers.append("readiness evidence is not for user_content_notes")
    if evidence.get("production_cutover_authorized"):
        blockers.append("readiness evidence must not self-authorize production cutover")

    route = load_cutover_route(
        root / "config/migration/user_content_backend_route.json"
    )
    if not (
        route.authority_state is AuthorityState.S0
        and route.backend is Backend.SQLITE_TRANSITION
        and route.sqlite_writer_enabled
        and not route.production_postgresql_enabled
    ):
        blockers.append("tracked default route is not SQLite/S0")

    target = json.loads(
        (root / "config/migration/target_rpo_rto_proposal.json").read_text(
            encoding="utf-8"
        )
    )
    if target.get("approval_status") != "approved":
        blockers.append("target RPO/RTO is not approved")

    identity = evidence.get("identity_mapping") or {}
    for field in ("manifest_sha256", "source_database_sha256"):
        if not _is_sha(identity.get(field)):
            blockers.append(f"identity_mapping.{field} is missing or invalid")
    for field in ("verified",):
        if identity.get(field) is not True:
            blockers.append(f"identity_mapping.{field} is not verified")
    if identity.get("collision_count") != 0:
        blockers.append("identity mapping has unresolved collisions")
    if identity.get("unapproved_alias_count") != 0:
        blockers.append("identity mapping has unapproved aliases")
    if int(identity.get("mapping_count") or 0) <= 0:
        blockers.append("identity mapping is empty")
    if not str(identity.get("approval_reference") or "").strip():
        blockers.append("identity mapping has no approval reference")
    if identity_mapping_path is not None:
        if not identity_mapping_path.is_file():
            blockers.append("identity mapping artifact is missing")
        else:
            mapping = json.loads(identity_mapping_path.read_text(encoding="utf-8"))
            if mapping.get("manifest_sha256") != identity.get("manifest_sha256"):
                blockers.append("identity mapping manifest identity mismatch")
            if mapping.get("source_database_sha256") != identity.get(
                "source_database_sha256"
            ):
                blockers.append("identity mapping source identity mismatch")
            if len(mapping.get("mappings") or []) != identity.get("mapping_count"):
                blockers.append("identity mapping count mismatch")
            if mapping.get("unapproved_alias_count") != 0:
                blockers.append("identity mapping artifact has unapproved aliases")
            for alias in mapping.get("alias_groups") or []:
                for field in ("approval_reference", "approved_by", "rationale"):
                    if not str(alias.get(field) or "").strip():
                        blockers.append(f"identity mapping alias is missing {field}")

    boolean_fields = {
        "application_contract": [
            "adapter_rehearsal_verified",
            "default_s0_route_verified",
            "no_silent_fallback_verified",
            "reader_writer_roles_distinct",
            "api_auth_csrf_revision_idempotency_verified",
            "trusted_principal_actor_verified",
            "s3_forward_repair_verified",
            "schema_compatible_code_rollback_verified",
        ],
        "postgresql_topology": [
            "approved",
            "supported_version_verified",
        ],
        "recovery": [
            "off_vm_copy_verified",
            "target_rpo_rto_met_in_rehearsal",
        ],
        "repository_governance": [
            "production_authority_approved",
            "company_control_or_approved_exception",
            "second_company_admin_or_handover",
            "two_factor_and_account_recovery_verified",
            "branch_protection_verified",
            "company_controlled_deploy_credential_ready",
        ],
        "cutover_window": [
            "operator_identified",
            "approver_identified",
            "maintenance_window_approved",
            "writer_fence_plan_verified",
            "rollback_recovery_decision_tree_approved",
        ],
    }
    sha_fields = {
        "application_contract": ["adapter_rehearsal_sha256"],
        "postgresql_topology": [
            "binary_provenance_sha256",
            "capacity_evidence_sha256",
            "service_lifecycle_evidence_sha256",
            "network_scope_evidence_sha256",
            "protected_transport_evidence_sha256",
            "role_acl_evidence_sha256",
            "credential_lifecycle_evidence_sha256",
        ],
        "recovery": [
            "base_backup_evidence_sha256",
            "wal_or_equivalent_incremental_evidence_sha256",
            "whole_database_restore_evidence_sha256",
            "side_restore_evidence_sha256",
            "authority_recovery_evidence_sha256",
        ],
    }
    for section, fields in boolean_fields.items():
        values = evidence.get(section) or {}
        for field in fields:
            if values.get(field) is not True:
                blockers.append(f"{section}.{field} is not verified")
    for section, fields in sha_fields.items():
        values = evidence.get(section) or {}
        for field in fields:
            if not _is_sha(values.get(field)):
                blockers.append(f"{section}.{field} is missing or invalid")
    for section in ("postgresql_topology", "repository_governance", "cutover_window"):
        reference_field = (
            "decision_reference" if section == "postgresql_topology" else "approval_reference"
        )
        if not str((evidence.get(section) or {}).get(reference_field) or "").strip():
            blockers.append(f"{section}.{reference_field} is missing")

    return {
        "schema_version": "honghu.stage4_user_content_readiness_result.v1",
        "cutover_unit": "user_content_notes",
        "status": "ready_to_request_production_authorization" if not blockers else "blocked",
        "production_cutover_authorized": False,
        "tracked_default_route": {
            "state": route.authority_state.value,
            "backend": route.backend.value,
            "sqlite_writer_enabled": route.sqlite_writer_enabled,
        },
        "target_rpo_rto_approval": target.get("approval_status"),
        "evidence_sha256": hashlib.sha256(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "identity_mapping_file_sha256": (
            _sha256_file(identity_mapping_path)
            if identity_mapping_path is not None and identity_mapping_path.is_file()
            else None
        ),
        "blockers": blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed Stage 4 readiness preflight")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--identity-mapping", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate_readiness(
        root=args.root.resolve(),
        evidence=json.loads(args.evidence.read_text(encoding="utf-8")),
        identity_mapping_path=(
            args.identity_mapping.resolve() if args.identity_mapping else None
        ),
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["status"] == "ready_to_request_production_authorization" else 2


if __name__ == "__main__":
    raise SystemExit(main())
