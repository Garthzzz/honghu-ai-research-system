from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


class ExecutionReadinessError(RuntimeError):
    pass


SCHEMA = "honghu.stage4_execution_evidence_bundle.v1"
SHA256 = set("0123456789abcdef")


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ExecutionReadinessError(f"JSON object required: {path}")
    return value


def _load_artifacts(
    evidence_root: Path, bundle: dict[str, Any], blockers: list[str]
) -> dict[str, dict[str, Any]]:
    loaded: dict[str, dict[str, Any]] = {}
    for name, identity in (bundle.get("artifacts") or {}).items():
        relative = str(identity.get("path") or "")
        expected = str(identity.get("sha256") or "")
        path = (evidence_root / relative).resolve()
        if evidence_root.resolve() not in path.parents or not path.is_file():
            blockers.append(f"{name}: artifact missing or outside evidence root")
            continue
        if len(expected) != 64 or set(expected) - SHA256 or _sha_file(path) != expected:
            blockers.append(f"{name}: artifact SHA256 mismatch")
            continue
        try:
            loaded[name] = _read(path)
        except (OSError, json.JSONDecodeError, ExecutionReadinessError):
            blockers.append(f"{name}: artifact is not valid JSON evidence")
    return loaded


def evaluate(
    *, repo_root: Path, evidence_root: Path, bundle: dict[str, Any]
) -> dict[str, Any]:
    blockers: list[str] = []
    humans: list[str] = []
    if bundle.get("schema_version") != SCHEMA:
        blockers.append("unsupported execution evidence bundle")
    subject = bundle.get("subject") or {}
    commit = str(subject.get("application_commit_sha") or "")
    if len(commit) != 40 or set(commit) - SHA256:
        blockers.append("bundle application commit is invalid")
    if subject.get("environment_id") != "production":
        blockers.append("bundle is not production-scoped")
    config_sha = str(subject.get("bootstrap_config_sha256") or "")
    if len(config_sha) != 64 or set(config_sha) - SHA256:
        blockers.append("bundle bootstrap config identity is invalid")
    route_path = repo_root / "config/migration/user_content_backend_route.json"
    route = _read(route_path)
    if not (
        route.get("authority_state") in {"S0", "S1"}
        and route.get("backend") == "sqlite_transition"
        and route.get("sqlite_writer_enabled") is True
        and route.get("production_postgresql_enabled") is False
    ):
        blockers.append("tracked application route exceeds S0/S1 SQLite authority")
    loaded = _load_artifacts(evidence_root, bundle, blockers)
    required = {
        "bootstrap_primary",
        "bootstrap_input",
        "bootstrap_final",
        "runtime_config",
        "production_postgresql_verification",
        "production_recovery",
        "recovery_set_manifest",
        "all_unit_preparation",
        "identity_mapping_manifest",
        "identity_mapping_crosscheck",
        "repository_governance",
        "target_rpo_rto",
        "human_decisions",
    }
    missing = sorted(required - set(loaded))
    blockers.extend(f"required evidence missing: {name}" for name in missing)

    primary = loaded.get("bootstrap_primary") or {}
    bootstrap_input = loaded.get("bootstrap_input") or {}
    runtime = loaded.get("runtime_config") or {}
    if bootstrap_input:
        if (
            bootstrap_input.get("application_commit_sha") != commit
            or bootstrap_input.get("bootstrap_config_sha256") != config_sha
            or bootstrap_input.get("tracked_route_sha256") != _sha_file(route_path)
        ):
            blockers.append("bootstrap input identity does not bind commit/config/route")
    if runtime and not (
        runtime.get("schema_version") == "honghu.postgresql_production_runtime.v1"
        and runtime.get("environment_id") == "production"
        and runtime.get("application_commit_sha") == commit
        and runtime.get("application_route") == "sqlite_transition"
        and bool(runtime.get("credential_owner_principal"))
        and runtime.get("credential_scope") == "stage4_operator_and_migration_only"
    ):
        blockers.append("production runtime config is invalid or changes application authority")
    if primary:
        if primary.get("status") != "pass" or primary.get("commit_sha") != commit:
            blockers.append("bootstrap primary did not pass for the bundle commit")
        if primary.get("production_authority_changed") is not False:
            blockers.append("bootstrap reports a production authority change")
        if primary.get("s2_or_s3_entered") is not False:
            blockers.append("bootstrap reports S2/S3 entry")
        if primary.get("formal_business_mutation_written") is not False:
            blockers.append("bootstrap reports a formal PostgreSQL mutation")
        phases = {item.get("name"): item for item in primary.get("phases") or []}
        for name in (
            "service_lifecycle",
            "credential_lifecycle",
            "tls_roles_credentials_migrations",
            "backup_wal_restore",
            "all_unit_s0_s1_preparation",
            "production_evidence_verification",
        ):
            if (phases.get(name) or {}).get("result") != "pass":
                blockers.append(f"bootstrap phase is not proven: {name}")

    final = loaded.get("bootstrap_final") or {}
    if final and not (
        final.get("service") == "Running"
        and final.get("listener_55440") is True
        and final.get("viewer_8080_ok") is True
        and final.get("production_authority_changed") is False
        and final.get("s2_or_s3_entered") is False
    ):
        blockers.append("bootstrap final service/authority evidence is not green")

    production = loaded.get("production_postgresql_verification") or {}
    if production:
        if production.get("environment_id") != "production" or production.get("application_commit_sha") != commit:
            blockers.append("production PostgreSQL verification subject mismatch")
        if production.get("application_authority") != "sqlite_transition":
            blockers.append("production verification no longer reports SQLite authority")
        if runtime and production.get("runtime_config_sha256") != _sha_file(
            evidence_root
            / str((bundle.get("artifacts") or {}).get("runtime_config", {}).get("path"))
        ):
            blockers.append("production verification references another runtime config")
        if production.get("formal_application_idempotency_records") != 0:
            blockers.append("formal PostgreSQL application mutations are present")
        server = production.get("server") or {}
        if not (
            str(server.get("version") or "").startswith("17.10")
            and server.get("listen_addresses") == "127.0.0.1"
            and server.get("ssl") == "on"
            and server.get("archive_mode") == "on"
        ):
            blockers.append("PostgreSQL version/network/TLS/WAL evidence mismatch")
        if not all((production.get("credential_presence") or {}).values()):
            blockers.append("production credential presence is incomplete")

    recovery = loaded.get("production_recovery") or {}
    recovery_manifest = loaded.get("recovery_set_manifest") or {}
    targets = loaded.get("target_rpo_rto") or {}
    tracked_targets_path = repo_root / "config/migration/target_rpo_rto_proposal.json"
    if targets:
        if _sha_file(tracked_targets_path) != _sha_file(
            evidence_root
            / str((bundle.get("artifacts") or {}).get("target_rpo_rto", {}).get("path"))
        ):
            blockers.append("RPO/RTO evidence is not the approved tracked proposal")
        target_classes = {item.get("class"): item for item in targets.get("targets") or []}
        authority_target = target_classes.get("migration_cutover_authority_control") or {}
        human_target = target_classes.get("human_authored_and_publication_control") or {}
        if not (
            targets.get("schema_version") == "honghu.target_rpo_rto_proposal.v2"
            and targets.get("approval_status") == "approved"
            and (targets.get("approval") or {}).get("approved_by") == "user"
            and "zero acknowledged" in str(authority_target.get("target_rpo") or "")
            and "5 minutes" in str(human_target.get("target_rpo") or "")
            and "4 hours" in str(human_target.get("target_rto") or "")
        ):
            blockers.append("approved target RPO/RTO contract is incomplete or changed")
    if recovery:
        if recovery.get("application_commit_sha") != commit:
            blockers.append("recovery evidence commit mismatch")
        if runtime and recovery.get("runtime_config_sha256") != production.get(
            "runtime_config_sha256"
        ):
            blockers.append("recovery and production verification runtime identities differ")
        if recovery.get("restore_source_contract") != "recovery_set_only":
            blockers.append("restore did not use only the attested recovery set")
        if recovery.get("whole_database_restore") != "pass" or recovery.get("authority_control_restore") != "pass":
            blockers.append("whole/authority restore is not green")
        if (recovery.get("side_domain_restore") or {}).get("status") != "pass":
            blockers.append("side-domain restore is not green")
        if recovery.get("recovery_set_identity") != recovery_manifest.get("recovery_set_identity"):
            blockers.append("recovery-set identity mismatch")
        storage = recovery.get("recovery_set_storage") or {}
        if not (
            recovery.get("off_vm_verified") is True
            and storage.get("independent_from_source_host") is True
            and storage.get("failure_domain") == "remote_host_storage"
        ):
            blockers.append("off-VM independent recovery is not verified")
        measurement = recovery.get("measurement") or {}
        # Numeric checks are the machine interpretation of the hash-bound,
        # approved human-content target above; they are not a new SLA.
        if float(measurement.get("rpo_seconds", 10**9)) > 5 * 60:
            blockers.append("measured recovery RPO exceeds the approved human-content target")
        if float(measurement.get("rto_seconds", 10**9)) > 4 * 60 * 60:
            blockers.append("measured recovery RTO exceeds the approved human-content target")

    preparation = loaded.get("all_unit_preparation") or {}
    if preparation:
        if preparation.get("application_commit_sha") != commit:
            blockers.append("unit preparation commit identity mismatch")
        unit_names = {item.get("cutover_unit") for item in preparation.get("units") or []}
        if len(unit_names) != 9 or preparation.get("failures"):
            blockers.append("not all nine cutover units have reconciled staging evidence")
        if not (
            preparation.get("authority_changed") is False
            and preparation.get("s2_s3_entered") is False
            and preparation.get("formal_business_mutation_written") is False
        ):
            blockers.append("unit preparation crossed the S0/S1 boundary")

    mapping = loaded.get("identity_mapping_manifest") or {}
    crosscheck = loaded.get("identity_mapping_crosscheck") or {}
    if mapping and crosscheck:
        if crosscheck.get("mapping_manifest_sha256") != mapping.get("manifest_sha256"):
            blockers.append("identity crosscheck references another mapping manifest")
        if (crosscheck.get("counts") or {}).get("fallback_requires_human", 1) > 0:
            humans.append("approve explicit resolutions for the four identity-mapping exceptions and the final bundle")

    governance = loaded.get("repository_governance") or {}
    if governance:
        if not (
            governance.get("main_protected") is True
            and governance.get("required_checks_green") is True
        ):
            blockers.append("repository main protection/required checks are not green")
        if not (governance.get("production_authority") or {}).get("approved"):
            humans.append("approve company repository control or a documented production-authority exception")
        humans.extend(governance.get("not_publicly_verifiable") or [])

    decisions = loaded.get("human_decisions") or {}
    if decisions:
        for key in ("mapping", "repository_authority", "operator", "approver", "maintenance_window", "enter_s2"):
            decision = decisions.get(key) or {}
            if not decision.get("approved") or not decision.get("approval_reference"):
                humans.append(f"human decision: {key}")
    if runtime:
        humans.append(
            "provision and verify the approved future application service principal before S2; bootstrap credentials are operator/migration scoped"
        )

    blockers = list(dict.fromkeys(blockers))
    humans = list(dict.fromkeys(humans))
    return {
        "schema_version": "honghu.stage4_execution_readiness_result.v1",
        "status": "ready_for_user_s2_decision" if not blockers else "production_readiness_blocked",
        "production_cutover_authorized": False,
        "application_commit_sha": commit,
        "tracked_authority": {"state": route.get("authority_state"), "backend": route.get("backend")},
        "engineering_blockers": blockers,
        "human_decisions": humans,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = evaluate(
        repo_root=args.repo_root.resolve(),
        evidence_root=args.evidence_root.resolve(),
        bundle=_read(args.bundle),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "ready_for_user_s2_decision" else 2


if __name__ == "__main__":
    raise SystemExit(main())
