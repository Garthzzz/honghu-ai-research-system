from __future__ import annotations

"""Fail-closed controller for the first production cutover unit.

The controller can enter the short S2 fence only after independently produced
S1, recovery, mapping, approval and live writer-fence evidence agree.  It never
mutates SQLite and never performs a business mutation.  After the first formal
Viewer mutation has atomically advanced authority to S3, ``reconcile-s3`` binds
the runtime route to that durable authority revision.
"""

import argparse
import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

from tools.migration.stage4_json_io import read_json
from tools.migration.stage4_s1_loader import _connection_from_runtime
from tools.migration.stage4_user_content_s1 import validate_mapping_approval


class UserContentCutoverError(RuntimeError):
    pass


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    if not isinstance(payload, dict):
        raise UserContentCutoverError(f"JSON object required: {path}")
    return payload


def _validate_hashed(payload: dict[str, Any], field: str) -> None:
    value = payload.get(field)
    if not isinstance(value, str) or len(value) != 64:
        raise UserContentCutoverError(f"evidence identity is missing: {field}")
    core = {key: item for key, item in payload.items() if key != field}
    if value != _sha(core):
        raise UserContentCutoverError(f"evidence identity mismatch: {field}")


def validate_enter_s2_inputs(
    *,
    mapping: dict[str, Any],
    mapping_approval: dict[str, Any],
    s1: dict[str, Any],
    recovery: dict[str, Any],
    fence: dict[str, Any],
    approval: dict[str, Any],
) -> dict[str, Any]:
    validate_mapping_approval(mapping, mapping_approval)
    if s1.get("schema_version") != "honghu.user_content_notes_s1_evidence.v1":
        raise UserContentCutoverError("unsupported S1 evidence")
    _validate_hashed(s1, "evidence_sha256")
    if s1.get("state") != "S1" or s1.get("authoritative_backend") != "sqlite_transition":
        raise UserContentCutoverError("user-content unit is not in S1/SQLite")
    if s1.get("mapping_manifest_sha256") != mapping.get("manifest_sha256"):
        raise UserContentCutoverError("S1 evidence references another mapping")
    if s1.get("mapping_approval_sha256") != mapping_approval.get("approval_sha256"):
        raise UserContentCutoverError("S1 evidence references another mapping approval")
    if int(s1.get("source_note_count", -1)) != int(s1.get("target_note_count", -2)):
        raise UserContentCutoverError("S1 note reconciliation is not exact")
    if int(s1.get("authority_revision", 0)) < 1:
        raise UserContentCutoverError("S1 authority revision is missing")
    application_commit_sha = str(s1.get("application_commit_sha") or "")
    if len(application_commit_sha) != 40:
        raise UserContentCutoverError("S1 application commit is missing")

    if recovery.get("schema_version") != "honghu.stage4_production_recovery.v1":
        raise UserContentCutoverError("unsupported production recovery evidence")
    _validate_hashed(recovery, "evidence_sha256")
    if recovery.get("status") != "pass" or recovery.get("whole_database_restore") != "pass":
        raise UserContentCutoverError("off-VM recovery is not verified")
    if recovery.get("off_vm_verified") is not True:
        raise UserContentCutoverError("off-VM failure domain is not verified")
    recovered = recovery.get("recovered")
    target = recovery.get("target")
    if (
        not isinstance(recovered, dict)
        or not str(recovered.get("sentinel_operation_id") or "").strip()
        or recovered.get("target_lsn_reached") is not True
        or not isinstance(target, dict)
        or recovered.get("sentinel_operation_id") != target.get("sentinel_operation_id")
    ):
        raise UserContentCutoverError("post-backup recovery sentinel is not verified")
    if recovery.get("application_commit_sha") != application_commit_sha:
        raise UserContentCutoverError("recovery evidence belongs to another application commit")

    if fence.get("schema_version") != "honghu.user_content_writer_fence.v1":
        raise UserContentCutoverError("unsupported writer-fence evidence")
    _validate_hashed(fence, "evidence_sha256")
    required_fence = {
        "verified": True,
        "sqlite_writer_fenced": True,
        "old_listener_absent": True,
        "scheduled_writer_absent": True,
        "production_8080_stopped_for_cutover": True,
    }
    for field, expected in required_fence.items():
        if fence.get(field) is not expected:
            raise UserContentCutoverError(f"writer fence is not proven: {field}")
    watermark = fence.get("sqlite_final_watermark")
    if not isinstance(watermark, dict) or watermark.get("analyst_note_count") is None:
        raise UserContentCutoverError("SQLite final watermark is missing")
    if fence.get("application_commit_sha") != application_commit_sha:
        raise UserContentCutoverError("writer fence belongs to another application commit")

    if approval.get("schema_version") != "honghu.user_content_cutover_approval.v1":
        raise UserContentCutoverError("unsupported production cutover approval")
    _validate_hashed(approval, "approval_sha256")
    if approval.get("approved_by") != "user" or approval.get("enter_s2_authorized") is not True:
        raise UserContentCutoverError("S2 does not have explicit user approval")
    for field in ("approval_reference", "approved_at_utc", "operator", "writer_identity"):
        if not str(approval.get(field) or "").strip():
            raise UserContentCutoverError(f"production approval is missing: {field}")
    expected = {
        "mapping_manifest_sha256": mapping.get("manifest_sha256"),
        "mapping_approval_sha256": mapping_approval.get("approval_sha256"),
        "s1_evidence_sha256": s1.get("evidence_sha256"),
        "recovery_evidence_sha256": recovery.get("evidence_sha256"),
        "writer_fence_evidence_sha256": fence.get("evidence_sha256"),
        "application_commit_sha": application_commit_sha,
    }
    for field, value in expected.items():
        if approval.get(field) != value:
            raise UserContentCutoverError(f"production approval identity mismatch: {field}")
    return watermark


def _route(
    *, state: str, revision: int, writer_identity: str, approval_reference: str,
    cutover_epoch: str
) -> dict[str, Any]:
    return {
        "schema_version": "honghu.user_content_route.v1",
        "cutover_unit": "user_content_notes",
        "route_revision": revision,
        "authority_state": state,
        "backend": "postgresql_production",
        "sqlite_writer_enabled": False,
        "production_postgresql_enabled": True,
        "writer_identity": writer_identity,
        "cutover_epoch": cutover_epoch,
        "approval_reference": approval_reference,
        "writer_operation": "analyst_note_mutation",
        "transaction_boundary": "one analyst-note mutation under the owning authority",
    }


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def enter_s2(
    connection: Any,
    *,
    s1: dict[str, Any],
    fence: dict[str, Any],
    approval: dict[str, Any],
    route_path: Path,
) -> dict[str, Any]:
    epoch = f"user-content-notes:{uuid.uuid4().hex}"
    verification_key = f"s2-control:{uuid.uuid4().hex}"
    verification_payload = {
        "classification": "control_plane_verification_not_business_data",
        "s1_evidence_sha256": s1["evidence_sha256"],
        "writer_fence_evidence_sha256": fence["evidence_sha256"],
    }
    request_hash = _sha(verification_payload)
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT * FROM operations.transition_user_content_notes(
                    %s,%s,'S2',%s,%s,%s::jsonb,%s,%s,%s
                )""",
                (
                    "S1",
                    int(s1["authority_revision"]),
                    approval["writer_identity"],
                    epoch,
                    json.dumps(fence["sqlite_final_watermark"], ensure_ascii=False),
                    approval["operator"],
                    approval["approval_reference"],
                    "approved first production user-content cutover",
                ),
            )
            transition = cursor.fetchone()
            cursor.execute(
                "SELECT operations.record_user_content_notes_verification(%s,%s,%s,%s::jsonb)",
                (
                    approval["writer_identity"],
                    verification_key,
                    request_hash,
                    json.dumps(verification_payload, ensure_ascii=False),
                ),
            )
            cursor.fetchone()
    state, revision = str(transition[1]), int(transition[2])
    if state != "S2":
        raise UserContentCutoverError("authority transition did not finish in S2")
    route = _route(
        state="S2",
        revision=revision,
        writer_identity=str(approval["writer_identity"]),
        approval_reference=str(approval["approval_reference"]),
        cutover_epoch=epoch,
    )
    _write_atomic(route_path, route)
    core = {
        "schema_version": "honghu.user_content_s2_evidence.v1",
        "state": "S2",
        "authority_revision": revision,
        "cutover_epoch": epoch,
        "writer_identity": approval["writer_identity"],
        "approval_reference": approval["approval_reference"],
        "verification_key": verification_key,
        "verification_request_sha256": request_hash,
        "sqlite_final_watermark": fence["sqlite_final_watermark"],
        "sqlite_writer_fenced": True,
        "route_sha256": _sha(route),
    }
    return {**core, "evidence_sha256": _sha(core)}


def reconcile_s3(connection: Any, *, s2: dict[str, Any], route_path: Path) -> dict[str, Any]:
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT state, authoritative_backend, state_revision, writer_identity,
                      cutover_epoch, sqlite_final_watermark,
                      postgresql_first_formal_commit, approval_reference
                 FROM operations.user_content_notes_authority_v1
                WHERE cutover_unit='user_content_notes'"""
        )
        row = cursor.fetchone()
    if row is None or row[0] != "S3" or row[1] != "postgresql_production":
        raise UserContentCutoverError("first formal mutation has not established S3")
    if row[3] != s2.get("writer_identity") or row[4] != s2.get("cutover_epoch"):
        raise UserContentCutoverError("S3 writer/epoch drifted from S2")
    if row[5] != s2.get("sqlite_final_watermark") or not isinstance(row[6], dict):
        raise UserContentCutoverError("S3 watermarks are incomplete or inconsistent")
    route = _route(
        state="S3",
        revision=int(row[2]),
        writer_identity=str(row[3]),
        approval_reference=str(row[7]),
        cutover_epoch=str(row[4]),
    )
    _write_atomic(route_path, route)
    core = {
        "schema_version": "honghu.user_content_s3_evidence.v1",
        "state": "S3",
        "authority_revision": int(row[2]),
        "writer_identity": row[3],
        "cutover_epoch": row[4],
        "sqlite_final_watermark": row[5],
        "postgresql_first_formal_commit": row[6],
        "approval_reference": row[7],
        "route_sha256": _sha(route),
    }
    return {**core, "evidence_sha256": _sha(core)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("enter-s2", "reconcile-s3"))
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--route-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mapping", type=Path)
    parser.add_argument("--mapping-approval", type=Path)
    parser.add_argument("--s1-evidence", type=Path)
    parser.add_argument("--recovery-evidence", type=Path)
    parser.add_argument("--fence-evidence", type=Path)
    parser.add_argument("--cutover-approval", type=Path)
    parser.add_argument("--s2-evidence", type=Path)
    args = parser.parse_args(argv)

    if args.action == "enter-s2":
        required = (
            args.mapping,
            args.mapping_approval,
            args.s1_evidence,
            args.recovery_evidence,
            args.fence_evidence,
            args.cutover_approval,
        )
        if any(value is None for value in required):
            parser.error("enter-s2 requires mapping, approvals, S1, recovery and fence evidence")
        mapping = _load_object(args.mapping)
        mapping_approval = _load_object(args.mapping_approval)
        s1 = _load_object(args.s1_evidence)
        recovery = _load_object(args.recovery_evidence)
        fence = _load_object(args.fence_evidence)
        approval = _load_object(args.cutover_approval)
        validate_enter_s2_inputs(
            mapping=mapping,
            mapping_approval=mapping_approval,
            s1=s1,
            recovery=recovery,
            fence=fence,
            approval=approval,
        )
        connection = _connection_from_runtime(args.runtime, "controller")
        try:
            result = enter_s2(
                connection,
                s1=s1,
                fence=fence,
                approval=approval,
                route_path=args.route_output,
            )
        finally:
            connection.close()
    else:
        if args.s2_evidence is None:
            parser.error("reconcile-s3 requires --s2-evidence")
        s2 = _load_object(args.s2_evidence)
        _validate_hashed(s2, "evidence_sha256")
        connection = _connection_from_runtime(args.runtime, "reader")
        try:
            result = reconcile_s3(connection, s2=s2, route_path=args.route_output)
        finally:
            connection.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(args.output, result)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
