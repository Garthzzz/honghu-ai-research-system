from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from tools.data_platform.routing import AuthorityState, Backend, load_cutover_route


SHA256 = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
EVIDENCE_SCHEMA = "honghu.stage4_readiness_evidence.v1"
BUNDLE_SCHEMA = "honghu.stage4_user_content_readiness_bundle.v3"
REQUIRED_ARTIFACTS = {
    "identity_mapping_manifest": "identity_mapping_manifest",
    "identity_mapping_approval": "identity_mapping_approval",
    "application_contract": "application_contract",
    "postgresql_topology": "postgresql_topology",
    "recovery": "recovery",
    "recovery_set_manifest": "recovery_set_manifest",
    "repository_governance": "repository_governance",
    "cutover_decision": "cutover_decision",
}


class ReadinessEvidenceError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_json(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _parse_time(value: Any, field: str) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        result = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ReadinessEvidenceError(f"{field} is not a valid ISO-8601 timestamp") from exc
    if result.tzinfo is None:
        raise ReadinessEvidenceError(f"{field} must include timezone")
    return result.astimezone(timezone.utc)


def _require(condition: bool, message: str, blockers: list[str]) -> None:
    if not condition:
        blockers.append(message)


def _safe_artifact_path(evidence_root: Path, relative: Any) -> Path:
    text = str(relative or "").strip()
    path = Path(text)
    if not text or path.is_absolute() or ".." in path.parts:
        raise ReadinessEvidenceError("artifact path must be a safe relative path")
    resolved_root = evidence_root.resolve()
    resolved = (resolved_root / path).resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ReadinessEvidenceError("artifact path escapes evidence root")
    return resolved


def _load_artifacts(
    bundle: dict[str, Any], evidence_root: Path, blockers: list[str]
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    loaded: dict[str, dict[str, Any]] = {}
    identities: dict[str, str] = {}
    declarations = bundle.get("artifacts") or {}
    for name, evidence_type in REQUIRED_ARTIFACTS.items():
        declaration = declarations.get(name) or {}
        try:
            path = _safe_artifact_path(evidence_root, declaration.get("path"))
        except ReadinessEvidenceError as exc:
            blockers.append(f"{name}: {exc}")
            continue
        expected_sha = str(declaration.get("sha256") or "")
        if not SHA256.fullmatch(expected_sha):
            blockers.append(f"{name}: artifact SHA256 is missing or invalid")
            continue
        if declaration.get("evidence_type") != evidence_type:
            blockers.append(f"{name}: declared evidence type mismatch")
            continue
        if not path.is_file():
            blockers.append(f"{name}: artifact is missing")
            continue
        actual_sha = _sha256_file(path)
        identities[name] = actual_sha
        if actual_sha != expected_sha:
            blockers.append(f"{name}: artifact SHA256 mismatch")
            continue
        try:
            loaded[name] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            blockers.append(f"{name}: artifact is not readable JSON ({type(exc).__name__})")
    return loaded, identities


def _validate_subject_and_time(
    *,
    name: str,
    artifact: dict[str, Any],
    subject: dict[str, Any],
    cutoff: datetime,
    blockers: list[str],
) -> None:
    _require(artifact.get("schema_version") == EVIDENCE_SCHEMA, f"{name}: unsupported evidence schema", blockers)
    _require(artifact.get("evidence_type") == REQUIRED_ARTIFACTS[name], f"{name}: evidence type mismatch", blockers)
    _require(artifact.get("subject") == subject, f"{name}: common subject mismatch", blockers)
    try:
        observed = _parse_time(artifact.get("observed_at_utc"), f"{name}.observed_at_utc")
        _require(observed <= cutoff, f"{name}: observed after evidence cutoff", blockers)
        if artifact.get("valid_until_utc"):
            valid_until = _parse_time(artifact["valid_until_utc"], f"{name}.valid_until_utc")
            _require(cutoff <= valid_until, f"{name}: evidence expired before cutoff", blockers)
    except ReadinessEvidenceError as exc:
        blockers.append(str(exc))


def _validate_mapping(
    mapping: dict[str, Any], approval: dict[str, Any], blockers: list[str], humans: list[str]
) -> None:
    _require(mapping.get("schema_version") == "honghu.user_content_identity_mapping.v3", "identity mapping is not a consistent-snapshot v3 artifact", blockers)
    core = {key: value for key, value in mapping.items() if key not in {"generated_at", "manifest_sha256"}}
    _require(mapping.get("manifest_sha256") == _sha256_json(core), "identity mapping manifest identity mismatch", blockers)
    snapshot = mapping.get("source_snapshot") or {}
    snapshot_core = {
        "transaction_contract": snapshot.get("transaction_contract"),
        "database_pragmas": snapshot.get("database_pragmas"),
        "source_tables": mapping.get("source_tables"),
    }
    _require(snapshot.get("snapshot_identity_sha256") == _sha256_json(snapshot_core), "identity mapping snapshot identity mismatch", blockers)
    transaction = snapshot.get("transaction_contract") or {}
    _require(transaction.get("mode") == "explicit_read_transaction" and transaction.get("query_only") is True, "identity mapping was not read in an explicit query-only transaction", blockers)
    diagnostics = snapshot.get("database_file_diagnostics") or {}
    _require(diagnostics.get("role") == "diagnostic_only_not_transaction_snapshot_identity", "database file identity is incorrectly authoritative", blockers)
    mappings = mapping.get("mappings") or []
    _require(bool(mappings), "identity mapping is empty", blockers)
    _require(mapping.get("collision_count") == 0, "identity mapping has unresolved collisions", blockers)
    _require(mapping.get("unapproved_alias_count") == 0, "identity mapping has unapproved aliases", blockers)
    payload = approval.get("payload") or {}
    _require(payload.get("mapping_manifest_sha256") == mapping.get("manifest_sha256"), "identity approval references another mapping manifest", blockers)
    _require(payload.get("snapshot_identity_sha256") == snapshot.get("snapshot_identity_sha256"), "identity approval references another SQLite snapshot", blockers)
    _require(payload.get("mapping_count") == len(mappings), "identity approval mapping count mismatch", blockers)
    _require(payload.get("fallback_count") == sum(item.get("basis") == "normalized_name_and_market_fallback" for item in mappings), "identity approval fallback count mismatch", blockers)
    if not payload.get("cutover_level_approved") or not str(payload.get("approval_reference") or "").strip():
        humans.append("identity mapping requires user cutover-level approval")


def _validate_application(
    root: Path,
    evidence_root: Path,
    artifact: dict[str, Any],
    subject: dict[str, Any],
    blockers: list[str],
) -> None:
    payload = artifact.get("payload") or {}
    route_path = root / "config/migration/user_content_backend_route.json"
    _require(payload.get("tracked_route_sha256") == _sha256_file(route_path), "application evidence route SHA does not match tracked route", blockers)
    route = load_cutover_route(route_path)
    _require(
        route.authority_state is AuthorityState.S0
        and route.backend is Backend.SQLITE_TRANSITION
        and route.sqlite_writer_enabled
        and not route.production_postgresql_enabled,
        "tracked default route is not SQLite/S0",
        blockers,
    )
    _require(payload.get("route") == {"authority_state": "S0", "backend": "sqlite_transition", "sqlite_writer_enabled": True, "production_postgresql_enabled": False}, "application evidence does not bind exact S0 route", blockers)
    _require(payload.get("silent_fallback") == "forbidden", "application evidence does not forbid silent fallback", blockers)
    rehearsal = payload.get("adapter_rehearsal") or {}
    _require(rehearsal.get("commit_sha") == subject.get("commit_sha"), "adapter rehearsal commit mismatch", blockers)
    _require(SHA256.fullmatch(str(rehearsal.get("artifact_sha256") or "")) is not None, "adapter rehearsal artifact identity missing", blockers)
    try:
        rehearsal_path = _safe_artifact_path(evidence_root, rehearsal.get("path"))
        _require(rehearsal_path.is_file(), "adapter rehearsal artifact is missing", blockers)
        if rehearsal_path.is_file():
            _require(
                _sha256_file(rehearsal_path) == rehearsal.get("artifact_sha256"),
                "adapter rehearsal artifact SHA256 mismatch",
                blockers,
            )
            raw_rehearsal = json.loads(rehearsal_path.read_text(encoding="utf-8"))
            _require(raw_rehearsal.get("status") == "pass", "adapter rehearsal did not pass", blockers)
            _require(raw_rehearsal.get("production_cutover_authorized") is False, "adapter rehearsal self-authorized production", blockers)
            _require(raw_rehearsal.get("live_sqlite_schema_unchanged") is True, "adapter rehearsal changed live SQLite schema", blockers)
            _require(raw_rehearsal.get("live_sqlite_file_hashes_unchanged") is True, "adapter rehearsal changed live SQLite files", blockers)
            _require((raw_rehearsal.get("adapter_result") or {}).get("status") == "pass", "adapter repository rehearsal did not pass", blockers)
    except (ReadinessEvidenceError, OSError, json.JSONDecodeError) as exc:
        blockers.append(f"adapter rehearsal artifact is invalid ({type(exc).__name__})")

    tracked_sources = payload.get("tracked_source_identities") or {}
    required_sources = {
        "tools/data_platform/user_content_notes.py",
        "tools/viewer/static/analyst_note_mutations.js",
        "tools/viewer/app.py",
        "tests/viewer/test_analyst_note_browser_mutations.py",
        "tests/migration/test_stage4_user_content_rehearsal.py",
    }
    _require(required_sources <= tracked_sources.keys(), "application contract source identities are incomplete", blockers)
    for relative, expected_sha in tracked_sources.items():
        path = (root / relative).resolve()
        _require(root.resolve() in path.parents and path.is_file(), f"tracked application source is missing: {relative}", blockers)
        if path.is_file():
            _require(_sha256_file(path) == expected_sha, f"tracked application source SHA mismatch: {relative}", blockers)
    required_cases = {
        "create_update_delete_api_compatibility",
        "revision_and_idempotency",
        "trusted_principal_actor",
        "no_silent_fallback",
        "s3_forward_repair",
        "schema_compatible_code_rollback",
    }
    passed_cases = set(rehearsal.get("passed_cases") or [])
    _require(required_cases <= passed_cases, "adapter rehearsal is missing required concrete cases", blockers)


def _validate_topology(artifact: dict[str, Any], blockers: list[str]) -> None:
    payload = artifact.get("payload") or {}
    host = payload.get("host") or {}
    postgres = payload.get("postgresql") or {}
    _require(bool(host.get("host_id")), "topology host identity missing", blockers)
    _require(str(postgres.get("version") or "").startswith("17."), "PostgreSQL candidate is not the approved fixed major version", blockers)
    _require(str(postgres.get("system_identifier") or "").isdigit(), "PostgreSQL system identifier missing", blockers)
    _require(SHA256.fullmatch(str(postgres.get("binary_sha256") or "")) is not None, "PostgreSQL binary identity missing", blockers)
    provenance = postgres.get("provenance") or {}
    source_url = str(provenance.get("source_url") or "")
    approved_windows_sources = (
        "https://www.postgresql.org/",
        "https://get.enterprisedb.com/postgresql/",
    )
    _require(source_url.startswith(approved_windows_sources), "PostgreSQL provenance is not an approved PostgreSQL Windows distribution source", blockers)
    if source_url.startswith("https://get.enterprisedb.com/postgresql/"):
        _require(
            provenance.get("distribution_channel")
            == "EnterpriseDB Windows binaries linked by PostgreSQL.org",
            "EnterpriseDB binary provenance is missing its PostgreSQL.org distribution-channel identity",
            blockers,
        )
    _require(SHA256.fullmatch(str(provenance.get("archive_sha256") or "")) is not None, "PostgreSQL archive identity missing", blockers)
    capacity = payload.get("capacity") or {}
    for field in ("free_bytes", "memory_bytes", "cpu_count"):
        _require(int(capacity.get(field) or 0) > 0, f"topology capacity {field} is missing", blockers)
    lifecycle = payload.get("service_lifecycle") or {}
    _require(lifecycle.get("reboot_required") is False, "candidate required a VM reboot", blockers)
    events = {item.get("event"): item for item in lifecycle.get("events") or []}
    for event in ("start", "stop", "crash_recovery"):
        _require((events.get(event) or {}).get("result") == "pass", f"service lifecycle {event} was not demonstrated", blockers)
    network = payload.get("network") or {}
    _require(network.get("listener_scope") in {"loopback", "explicit_cidrs"}, "network listener scope is not minimal", blockers)
    _require("0.0.0.0/0" not in (network.get("allowed_cidrs") or []), "network evidence permits all IPv4 sources", blockers)
    tls = payload.get("protected_transport") or {}
    _require(tls.get("verified") is True and str(tls.get("protocol") or "") in {"TLSv1.2", "TLSv1.3"}, "protected transport handshake was not demonstrated", blockers)
    _require(SHA256.fullmatch(str(tls.get("certificate_sha256") or "")) is not None, "TLS certificate identity missing", blockers)
    roles = payload.get("role_acl_probes") or []
    role_probes = {item.get("role"): item for item in roles if item.get("result") == "pass"}
    _require({"reader", "writer", "controller", "backup"} <= role_probes.keys(), "role ACL probes are incomplete", blockers)
    expected_role_contract = {
        "reader": ({"connect", "select"}, {"insert"}),
        "writer": ({"connect", "synthetic_write"}, {"controller"}),
        "controller": ({"connect"}, {"synthetic_write"}),
        "backup": ({"replication"}, {"synthetic_write"}),
    }
    for role, (allowed, denied) in expected_role_contract.items():
        probe = role_probes.get(role) or {}
        _require(allowed <= set(probe.get("allowed") or []), f"{role} allowed-operation probe is incomplete", blockers)
        _require(denied <= set(probe.get("denied") or []), f"{role} denied-operation probe is incomplete", blockers)
    credential_events = {item.get("event") for item in payload.get("credential_lifecycle") or [] if item.get("result") == "pass"}
    _require({"create", "rotate", "old_credential_rejected", "revoke", "revoked_credential_rejected"} <= credential_events, "credential lifecycle is incomplete", blockers)


def _validate_recovery(
    recovery: dict[str, Any],
    topology: dict[str, Any],
    recovery_set_manifest: dict[str, Any],
    blockers: list[str],
) -> None:
    payload = recovery.get("payload") or {}
    topology_payload = topology.get("payload") or {}
    system_id = str((topology_payload.get("postgresql") or {}).get("system_identifier") or "")
    _require(payload.get("source_system_identifier") == system_id, "recovery source cluster identity mismatch", blockers)
    backup = payload.get("base_backup") or {}
    _require(bool(backup.get("backup_id")) and SHA256.fullmatch(str(backup.get("sha256") or "")) is not None, "base backup identity missing", blockers)
    wal = payload.get("wal_or_incremental") or {}
    _require(bool(wal.get("start_lsn")) and bool(wal.get("end_lsn")) and wal.get("archive_result") == "pass", "WAL/incremental evidence is incomplete", blockers)
    logical = payload.get("logical_backup") or {}
    _require(bool(logical.get("backup_id")) and SHA256.fullmatch(str(logical.get("sha256") or "")) is not None, "logical backup identity missing", blockers)
    authority_backup = payload.get("authority_backup") or {}
    _require(
        bool(authority_backup.get("backup_id"))
        and SHA256.fullmatch(str(authority_backup.get("sha256") or "")) is not None,
        "authority-control backup identity missing",
        blockers,
    )
    expected_sources = {
        "whole_database_restore": backup.get("backup_id"),
        "side_restore": logical.get("backup_id"),
        "authority_recovery": authority_backup.get("backup_id"),
    }
    for name in ("whole_database_restore", "side_restore", "authority_recovery"):
        restore = payload.get(name) or {}
        _require(restore.get("result") == "pass", f"{name} did not pass", blockers)
        _require(bool(restore.get("source_backup_id")) and restore.get("source_backup_id") == expected_sources[name], f"{name} references an invalid backup identity", blockers)
        _require(SHA256.fullmatch(str(restore.get("verification_sha256") or "")) is not None, f"{name} verification identity missing", blockers)
    authority = payload.get("authority_recovery") or {}
    _require(authority.get("cutover_unit") == "user_content_notes", "authority recovery is for another cutover unit", blockers)
    storage = payload.get("off_vm_storage") or {}
    recovery_set = payload.get("recovery_set") or {}
    _require(
        recovery_set_manifest.get("schema_version")
        == "honghu.stage4_recovery_set.v2",
        "recovery-set manifest schema is unsupported",
        blockers,
    )
    manifest_core = {
        key: value
        for key, value in recovery_set_manifest.items()
        if key != "recovery_set_identity"
    }
    manifest_identity = _sha256_json(manifest_core)
    _require(
        recovery_set_manifest.get("recovery_set_identity") == manifest_identity,
        "recovery-set manifest identity mismatch",
        blockers,
    )
    _require(
        recovery_set.get("identity") == manifest_identity,
        "recovery evidence references another recovery set",
        blockers,
    )
    manifest_target = recovery_set_manifest.get("target") or {}
    manifest_artifacts = recovery_set_manifest.get("artifacts") or []
    artifact_roles = {item.get("role") for item in manifest_artifacts}
    available_wal = {
        str(item.get("path") or "").split("/", 1)[1]
        for item in manifest_artifacts
        if item.get("role") == "wal" and str(item.get("path") or "").startswith("wal/")
    }
    required_wal = set(manifest_target.get("required_wal_files") or [])
    _require(
        {"base_backup", "wal", "metadata"} <= artifact_roles,
        "recovery set does not contain base backup, WAL and target metadata",
        blockers,
    )
    _require(
        bool(required_wal) and required_wal <= available_wal,
        "recovery set WAL cannot reach the declared target",
        blockers,
    )
    _require(
        bool(manifest_target.get("sentinel_operation_id"))
        and bool(manifest_target.get("target_lsn"))
        and bool(manifest_target.get("durable_target_at_utc")),
        "recovery target sentinel/watermark is incomplete",
        blockers,
    )
    manifest_storage = recovery_set_manifest.get("storage_evidence") or {}
    _require(
        manifest_storage == recovery_set.get("storage_evidence"),
        "recovery storage evidence differs from the recovery-set manifest",
        blockers,
    )
    _require(
        manifest_target == recovery_set.get("target"),
        "recovery target differs from the recovery-set manifest",
        blockers,
    )
    _require(storage.get("verified") is True, "off-VM recovery copy is not verified", blockers)
    _require(
        manifest_storage.get("independent_from_source_host") is True
        and manifest_storage.get("failure_domain") == "remote_host_storage",
        "same-host storage cannot be claimed as off-VM",
        blockers,
    )
    _require(
        SHA256.fullmatch(str(storage.get("failure_domain_identity") or "")) is not None
        and storage.get("failure_domain_identity")
        == manifest_storage.get("derived_storage_identity"),
        "off-VM failure-domain identity is missing or inconsistent",
        blockers,
    )
    _require(
        storage.get("recovery_set_identity") == manifest_identity,
        "off-VM storage references another recovery set",
        blockers,
    )
    measured = payload.get("measured") or {}
    _require(float(measured.get("rpo_seconds", -1)) >= 0 and float(measured.get("rpo_seconds", 10**9)) <= 300, "human-authored data measured RPO exceeds approved target", blockers)
    _require(float(measured.get("rto_seconds", -1)) >= 0 and float(measured.get("rto_seconds", 10**9)) <= 14400, "human-authored data measured RTO exceeds approved target", blockers)
    _require(measured.get("authority_transition_loss_count") == 0, "authority-control recovery lost acknowledged records", blockers)
    _require(float(measured.get("authority_verification_seconds", 10**9)) <= 3600, "authority-control verification exceeds approved target", blockers)


def _validate_governance(artifact: dict[str, Any], blockers: list[str], humans: list[str]) -> None:
    payload = artifact.get("payload") or {}
    repository = payload.get("repository") or {}
    _require(repository.get("required_checks_green") is True, "repository required checks are not green", blockers)
    _require(repository.get("branch_protection_verified") is True, "repository branch protection is not verified", blockers)
    if not repository.get("production_authority_approved"):
        humans.append("repository production authority or approved company-control exception")
    for decision in ("second_company_admin_or_handover", "two_factor_and_recovery", "company_controlled_deploy_credential"):
        if not payload.get(decision):
            humans.append(f"repository governance decision: {decision}")


def _validate_cutover_decision(
    root: Path, artifact: dict[str, Any], blockers: list[str], humans: list[str]
) -> None:
    payload = artifact.get("payload") or {}
    _require(payload.get("writer_fence_plan_verified") is True, "writer fence plan is not verified", blockers)
    _require(payload.get("rollback_recovery_decision_tree_verified") is True, "rollback/recovery decision tree is not verified", blockers)
    plan_identities = payload.get("tracked_plan_identities") or {}
    _require(bool(plan_identities), "cutover plans are not bound to tracked content", blockers)
    for relative, expected_sha in plan_identities.items():
        path = (root / relative).resolve()
        _require(root.resolve() in path.parents and path.is_file(), f"cutover plan is missing: {relative}", blockers)
        if path.is_file():
            _require(_sha256_file(path) == expected_sha, f"cutover plan SHA mismatch: {relative}", blockers)
    for decision in ("operator", "approver", "maintenance_window", "enter_s2_approval"):
        value = payload.get(decision) or {}
        if not value.get("approved") or not str(value.get("approval_reference") or "").strip():
            humans.append(f"cutover decision: {decision}")


def evaluate_readiness(
    *,
    root: Path,
    evidence: dict[str, Any],
    evidence_root: Path | None = None,
    identity_mapping_path: Path | None = None,
) -> dict[str, Any]:
    del identity_mapping_path  # v2 bundles own and hash every evidence path.
    blockers: list[str] = []
    humans: list[str] = []
    if evidence.get("schema_version") != BUNDLE_SCHEMA:
        blockers.append("unsupported readiness bundle schema; shape-only v1 evidence is retired")
    if evidence.get("cutover_unit") != "user_content_notes":
        blockers.append("readiness evidence is not for user_content_notes")
    if evidence.get("production_cutover_authorized"):
        blockers.append("readiness evidence must not self-authorize production cutover")
    subject = evidence.get("subject") or {}
    _require(bool(subject.get("environment_id")), "bundle environment identity missing", blockers)
    _require(bool(subject.get("candidate_id")), "bundle candidate identity missing", blockers)
    _require(GIT_SHA.fullmatch(str(subject.get("commit_sha") or "")) is not None, "bundle commit SHA is invalid", blockers)
    _require(SHA256.fullmatch(str(subject.get("config_sha256") or "")) is not None, "bundle config SHA is invalid", blockers)
    try:
        cutoff = _parse_time(evidence.get("evidence_cutoff_utc"), "evidence_cutoff_utc")
    except ReadinessEvidenceError as exc:
        blockers.append(str(exc))
        cutoff = datetime.min.replace(tzinfo=timezone.utc)

    route = load_cutover_route(root / "config/migration/user_content_backend_route.json")
    _require(
        route.authority_state is AuthorityState.S0
        and route.backend is Backend.SQLITE_TRANSITION
        and route.sqlite_writer_enabled
        and not route.production_postgresql_enabled,
        "tracked default route is not SQLite/S0",
        blockers,
    )
    target = json.loads((root / "config/migration/target_rpo_rto_proposal.json").read_text(encoding="utf-8"))
    _require(target.get("approval_status") == "approved", "target RPO/RTO is not approved", blockers)

    loaded, artifact_identities = _load_artifacts(evidence, evidence_root or root, blockers)
    for name, artifact in loaded.items():
        if name in {"identity_mapping_manifest", "recovery_set_manifest"}:
            continue
        _validate_subject_and_time(name=name, artifact=artifact, subject=subject, cutoff=cutoff, blockers=blockers)

    if {"identity_mapping_manifest", "identity_mapping_approval"} <= loaded.keys():
        _validate_mapping(loaded["identity_mapping_manifest"], loaded["identity_mapping_approval"], blockers, humans)
    if "application_contract" in loaded:
        _validate_application(
            root,
            evidence_root or root,
            loaded["application_contract"],
            subject,
            blockers,
        )
    if "postgresql_topology" in loaded:
        _validate_topology(loaded["postgresql_topology"], blockers)
    if {"recovery", "postgresql_topology", "recovery_set_manifest"} <= loaded.keys():
        _validate_recovery(
            loaded["recovery"],
            loaded["postgresql_topology"],
            loaded["recovery_set_manifest"],
            blockers,
        )
    if "repository_governance" in loaded:
        _validate_governance(loaded["repository_governance"], blockers, humans)
    if "cutover_decision" in loaded:
        _validate_cutover_decision(root, loaded["cutover_decision"], blockers, humans)

    blockers = list(dict.fromkeys(blockers))
    humans = list(dict.fromkeys(humans))
    status = "ready_to_request_production_authorization" if not blockers else "blocked"
    return {
        "schema_version": "honghu.stage4_user_content_readiness_result.v2",
        "cutover_unit": "user_content_notes",
        "status": status,
        "production_cutover_authorized": False,
        "tracked_default_route": {
            "state": route.authority_state.value,
            "backend": route.backend.value,
            "sqlite_writer_enabled": route.sqlite_writer_enabled,
        },
        "target_rpo_rto_approval": target.get("approval_status"),
        "bundle_sha256": _sha256_json(evidence),
        "artifact_identities": artifact_identities,
        "engineering_blockers": blockers,
        "human_decisions": humans,
        "blockers": blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed Stage 4 readiness evidence verifier")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate_readiness(
        root=args.root.resolve(),
        evidence=json.loads(args.evidence.read_text(encoding="utf-8")),
        evidence_root=(args.evidence_root or args.evidence.parent).resolve(),
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["status"] == "ready_to_request_production_authorization" else 2


if __name__ == "__main__":
    raise SystemExit(main())
