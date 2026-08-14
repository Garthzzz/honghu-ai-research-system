from __future__ import annotations

"""Fail-closed production controller for the shared_identity cutover unit.

The command consumes immutable S1, mapping, recovery and user-authorization
evidence.  It persists a reusable operation intent before entering S2, fences
the local SQLite writer, advances S1->S2 through the controller role, and makes
the reconciled snapshot formal through the writer role.  Snapshot activation
and S2->S3 are one PostgreSQL transaction.  A retry reuses the same epoch and
idempotency identity and reconciles an uncertain response from durable state.
"""

import argparse
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from tools.data_platform.local_authority_fence import write_authority_fence
from tools.migration.stage4_json_io import read_json
from tools.migration.stage4_s1_loader import _connection_from_runtime


class SharedIdentityCutoverError(RuntimeError):
    pass


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = read_json(path)
    if not isinstance(value, dict):
        raise SharedIdentityCutoverError(f"JSON object required: {path}")
    return value


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def validate_inputs(
    *,
    mapping: dict[str, Any],
    decision: dict[str, Any],
    s1: dict[str, Any],
    recovery: dict[str, Any],
) -> None:
    if decision.get("schema_version") != "honghu.stage4_remaining_cutover_decision.v1":
        raise SharedIdentityCutoverError("unsupported remaining-cutover decision")
    if decision.get("approved_by") != "user" or "shared_identity" not in set(
        decision.get("approval_scope") or []
    ):
        raise SharedIdentityCutoverError("shared_identity production cutover is not approved")
    contract = decision.get("approval_contract") or {}
    for forbidden in (
        "stage5_runner_migration_authorized",
        "dual_writer_authorized",
        "shadow_write_authorized",
        "silent_fallback_authorized",
    ):
        if contract.get(forbidden) is not False:
            raise SharedIdentityCutoverError(f"unsafe approval contract: {forbidden}")
    mapping_approval = decision.get("shared_identity_mapping_approval") or {}
    if mapping_approval.get("cutover_level_approved") is not True:
        raise SharedIdentityCutoverError("shared identity mapping is not approved")
    expected_mapping = {
        "mapping_manifest_sha256": mapping.get("manifest_sha256"),
        "mapping_snapshot_identity_sha256": mapping.get("snapshot_identity_sha256"),
    }
    for field, expected in expected_mapping.items():
        if mapping_approval.get(field) != expected:
            raise SharedIdentityCutoverError(f"mapping decision mismatch: {field}")
    if int(mapping_approval.get("manual_review_item_count", -1)) != 0:
        raise SharedIdentityCutoverError("mapping still has unresolved manual review items")

    if s1.get("schema_version") != "honghu.shared_identity_s1_evidence.v1":
        raise SharedIdentityCutoverError("unsupported shared_identity S1 evidence")
    if (
        s1.get("authority_state") != "S1"
        or s1.get("authoritative_backend") != "sqlite_transition"
        or s1.get("formal_business_data") is not False
        or int(s1.get("source_row_count", -1)) != int(s1.get("target_row_count", -2))
        or s1.get("source_content_sha256") != s1.get("target_content_sha256")
    ):
        raise SharedIdentityCutoverError("shared_identity S1 reconciliation is incomplete")
    if s1.get("mapping_manifest_sha256") != mapping.get("manifest_sha256"):
        raise SharedIdentityCutoverError("S1 references another identity mapping")
    application_commit = str(s1.get("application_commit_sha") or "")
    if len(application_commit) != 40:
        raise SharedIdentityCutoverError("S1 application commit is missing")

    if recovery.get("schema_version") != "honghu.stage4_production_recovery.v1":
        raise SharedIdentityCutoverError("unsupported recovery evidence")
    if (
        recovery.get("status") != "pass"
        or recovery.get("off_vm_verified") is not True
        or recovery.get("whole_database_restore") != "pass"
        or recovery.get("application_commit_sha") != application_commit
    ):
        raise SharedIdentityCutoverError("exact-commit off-VM recovery is not verified")
    recovered = recovery.get("recovered") or {}
    target = recovery.get("target") or {}
    if (
        recovered.get("target_lsn_reached") is not True
        or not recovered.get("sentinel_operation_id")
        or recovered.get("sentinel_operation_id") != target.get("sentinel_operation_id")
    ):
        raise SharedIdentityCutoverError("recovery watermark/sentinel is not verified")


def _authority(connection: Any) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT state,authoritative_backend,state_revision,writer_identity,
               cutover_epoch,approval_reference,sqlite_final_watermark,
               postgresql_first_formal_commit
          FROM operations.cutover_unit_authority
         WHERE cutover_unit='shared_identity'
        """
    ).fetchone()
    if row is None:
        raise SharedIdentityCutoverError("shared_identity authority row is absent")
    return {
        "state": str(row[0]),
        "backend": str(row[1]),
        "revision": int(row[2]),
        "writer_identity": row[3],
        "cutover_epoch": row[4],
        "approval_reference": row[5],
        "sqlite_final_watermark": row[6],
        "postgresql_first_formal_commit": row[7],
    }


def _intent(
    path: Path,
    *,
    s1: dict[str, Any],
    decision: dict[str, Any],
    writer_identity: str,
    actor: str,
) -> dict[str, Any]:
    if path.exists():
        value = _load(path)
        if (
            value.get("schema_version") != "honghu.shared_identity_cutover_intent.v1"
            or value.get("source_snapshot_id") != s1.get("source_snapshot_id")
            or value.get("application_commit_sha") != s1.get("application_commit_sha")
            or value.get("writer_identity") != writer_identity
        ):
            raise SharedIdentityCutoverError("existing cutover intent belongs to another operation")
        return value
    core = {
        "schema_version": "honghu.shared_identity_cutover_intent.v1",
        "cutover_unit": "shared_identity",
        "application_commit_sha": s1["application_commit_sha"],
        "source_snapshot_id": s1["source_snapshot_id"],
        "source_identity_sha256": s1["source_identity_sha256"],
        "writer_identity": writer_identity,
        "actor": actor,
        "approval_reference": decision["approval_reference"],
        "cutover_epoch": f"shared-identity:{uuid.uuid4().hex}",
        "activation_idempotency_key": f"shared-identity-activate:{uuid.uuid4().hex}",
    }
    core["activation_request_sha256"] = _sha(
        {
            "source_snapshot_id": core["source_snapshot_id"],
            "application_commit_sha": core["application_commit_sha"],
            "approval_reference": core["approval_reference"],
        }
    )
    payload = {**core, "intent_sha256": _sha(core)}
    _write(path, payload)
    return payload


def cutover(
    *,
    controller: Any,
    writer: Any,
    reader: Any,
    s1: dict[str, Any],
    decision: dict[str, Any],
    intent: dict[str, Any],
    data_root: Path,
) -> dict[str, Any]:
    watermark = {
        "source_snapshot_id": s1["source_snapshot_id"],
        "source_identity_sha256": s1["source_identity_sha256"],
        "source_row_count": int(s1["source_row_count"]),
        "source_content_sha256": s1["source_content_sha256"],
    }
    approval = str(intent["approval_reference"])
    epoch = str(intent["cutover_epoch"])
    writer_identity = str(intent["writer_identity"])
    actor = str(intent["actor"])

    before = _authority(reader)
    if before["state"] == "S1":
        write_authority_fence(
            data_root,
            cutover_unit="shared_identity",
            authority_state="S2_PENDING",
            authoritative_backend="postgresql_production",
            authority_evidence_sha256=intent["intent_sha256"],
            approval_reference=approval,
            cutover_epoch=epoch,
        )
        with controller.transaction():
            row = controller.execute(
                """SELECT * FROM operations.transition_shared_identity(
                    'S1',%s,'S2',%s,%s,%s::jsonb,%s,%s,%s
                )""",
                (
                    before["revision"], writer_identity, epoch,
                    json.dumps(watermark, ensure_ascii=False), actor, approval,
                    "approved shared identity production cutover",
                ),
            ).fetchone()
        if row is None or str(row[1]) != "S2":
            raise SharedIdentityCutoverError("shared_identity did not enter S2")
    elif before["state"] not in {"S2", "S3"}:
        raise SharedIdentityCutoverError("shared_identity authority is outside S1/S2/S3")

    after_s2 = _authority(reader)
    if (
        after_s2["backend"] != "postgresql_production"
        or after_s2["writer_identity"] != writer_identity
        or after_s2["cutover_epoch"] != epoch
        or after_s2["approval_reference"] != approval
    ):
        raise SharedIdentityCutoverError("S2 authority does not match persisted intent")

    if after_s2["state"] == "S2":
        with writer.transaction():
            result_row = writer.execute(
                """SELECT shared_identity.activate_snapshot_v1(
                    %s,%s,%s,%s,%s,%s
                )""",
                (
                    s1["source_snapshot_id"], after_s2["revision"],
                    intent["activation_idempotency_key"],
                    intent["activation_request_sha256"], writer_identity, actor,
                ),
            ).fetchone()
        if result_row is None:
            raise SharedIdentityCutoverError("snapshot activation returned no result")

    final = _authority(reader)
    if (
        final["state"] != "S3"
        or final["backend"] != "postgresql_production"
        or final["writer_identity"] != writer_identity
        or final["cutover_epoch"] != epoch
        or not isinstance(final["postgresql_first_formal_commit"], dict)
    ):
        raise SharedIdentityCutoverError("durable shared_identity S3 is not established")
    snapshot = reader.execute(
        """SELECT authority_state,formal_business_data,current_formal_row_count,
                  source_snapshot_id,target_content_sha256
             FROM shared_identity.unit_snapshot WHERE cutover_unit='shared_identity'"""
    ).fetchone()
    if (
        snapshot is None
        or str(snapshot[0]) != "S3"
        or not bool(snapshot[1])
        or int(snapshot[2]) != int(s1["target_row_count"])
        or str(snapshot[3]) != str(s1["source_snapshot_id"])
        or str(snapshot[4]) != str(s1["target_content_sha256"])
    ):
        raise SharedIdentityCutoverError("formal shared identity snapshot is inconsistent")
    core = {
        "schema_version": "honghu.shared_identity_s3_evidence.v1",
        "cutover_unit": "shared_identity",
        "state": "S3",
        "authoritative_backend": "postgresql_production",
        "state_revision": final["revision"],
        "writer_identity": writer_identity,
        "cutover_epoch": epoch,
        "approval_reference": approval,
        "source_snapshot_id": s1["source_snapshot_id"],
        "source_identity_sha256": s1["source_identity_sha256"],
        "formal_row_count": int(snapshot[2]),
        "sqlite_final_watermark": final["sqlite_final_watermark"],
        "postgresql_first_formal_commit": final["postgresql_first_formal_commit"],
        "sqlite_writer_fenced": True,
        "intent_sha256": intent["intent_sha256"],
        "application_commit_sha": s1["application_commit_sha"],
    }
    evidence = {**core, "evidence_sha256": _sha(core)}
    write_authority_fence(
        data_root,
        cutover_unit="shared_identity",
        authority_state="S3",
        authoritative_backend="postgresql_production",
        authority_evidence_sha256=evidence["evidence_sha256"],
        approval_reference=approval,
        cutover_epoch=epoch,
    )
    return evidence


def route_from_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "honghu.cutover_route.v1",
        "cutover_unit": "shared_identity",
        "route_revision": int(evidence["state_revision"]),
        "authority_state": "S3",
        "backend": "postgresql_production",
        "sqlite_writer_enabled": False,
        "production_postgresql_enabled": True,
        "writer_identity": evidence["writer_identity"],
        "cutover_epoch": evidence["cutover_epoch"],
        "approval_reference": evidence["approval_reference"],
        "writer_operation": "shared_identity_mutation",
        "transaction_boundary": "one shared identity mutation under owning authority",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--decision", type=Path, required=True)
    parser.add_argument("--s1-evidence", type=Path, required=True)
    parser.add_argument("--recovery-evidence", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--writer-identity", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--intent", type=Path, required=True)
    parser.add_argument("--route-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    mapping = _load(args.mapping)
    decision = _load(args.decision)
    s1 = _load(args.s1_evidence)
    recovery = _load(args.recovery_evidence)
    validate_inputs(mapping=mapping, decision=decision, s1=s1, recovery=recovery)
    intent = _intent(
        args.intent,
        s1=s1,
        decision=decision,
        writer_identity=args.writer_identity,
        actor=args.actor,
    )
    controller = _connection_from_runtime(args.runtime, "controller")
    writer = _connection_from_runtime(args.runtime, "writer_shared_identity")
    reader = _connection_from_runtime(args.runtime, "reader")
    try:
        result = cutover(
            controller=controller,
            writer=writer,
            reader=reader,
            s1=s1,
            decision=decision,
            intent=intent,
            data_root=args.data_root,
        )
    finally:
        controller.close()
        writer.close()
        reader.close()
    _write(args.route_output, route_from_evidence(result))
    _write(args.output, result)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
