from __future__ import annotations

"""Fail-closed S1 -> S2 -> S3 controller for the remaining Stage 4 units.

The command is deliberately generic: unit ownership, dependencies and writer
identity come from the reviewed registry and PostgreSQL authority ledger.  It
does not alter a Scheduled Task or infer authority from a tracked route file.
Every run persists an intent before fencing SQLite, so an uncertain response
can be reconciled under the same epoch and idempotency identity.
"""

import argparse
import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any

from tools.data_platform.local_authority_fence import write_authority_fence
from tools.data_platform.routing import CutoverUnitRegistry
from tools.migration.stage4_json_io import read_json
from tools.migration.stage4_s1_loader import _connection_from_runtime


UNITS = (
    "financial_data",
    "research_publication",
    "dynamic_intelligence",
    "operations_governance",
    "investment_hypotheses",
    "opportunity_lens",
    "sentiment_analytics",
)


class RemainingUnitCutoverError(RuntimeError):
    pass


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = read_json(path)
    if not isinstance(value, dict):
        raise RemainingUnitCutoverError(f"JSON object required: {path}")
    return value


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def validate_inputs(
    *,
    unit: str,
    decision: dict[str, Any],
    s1: dict[str, Any],
    recovery: dict[str, Any],
    registry: CutoverUnitRegistry,
    expected_commit: str,
) -> None:
    if unit not in UNITS or registry.definition(unit).name != unit:
        raise RemainingUnitCutoverError("unit is outside reviewed remaining scope")
    if not re.fullmatch(r"[0-9a-f]{40}", expected_commit):
        raise RemainingUnitCutoverError("exact lowercase application commit is required")
    if decision.get("schema_version") != "honghu.stage4_remaining_cutover_decision.v1":
        raise RemainingUnitCutoverError("unsupported production decision")
    if decision.get("approved_by") != "user" or unit not in set(
        decision.get("approval_scope") or ()
    ):
        raise RemainingUnitCutoverError("unit production cutover is not user-authorized")
    contract = decision.get("approval_contract") or {}
    required_gates = set(contract.get("per_unit_gates_required") or ())
    expected_gates = {
        "live_drift",
        "dependency_transaction_boundary",
        "stable_identity_mapping",
        "source_baseline_delta_catchup",
        "migration_backfill_reconciliation",
        "unique_writer_runner",
        "least_privilege_acl",
        "off_vm_recovery",
        "s2_s3_authority_evidence",
        "application_compatibility",
        "fail_closed_rollback_recovery",
    }
    if not expected_gates <= required_gates:
        raise RemainingUnitCutoverError("production decision omits required unit gates")
    for field in (
        "stage5_runner_migration_authorized",
        "dual_writer_authorized",
        "shadow_write_authorized",
        "silent_fallback_authorized",
    ):
        if contract.get(field) is not False:
            raise RemainingUnitCutoverError(f"unsafe approval contract: {field}")

    if s1.get("schema_version") != "honghu.generic_unit_s1_evidence.v1":
        raise RemainingUnitCutoverError("unsupported generic S1 evidence")
    if (
        s1.get("cutover_unit") != unit
        or s1.get("authority_state") != "S1"
        or s1.get("authoritative_backend") != "sqlite_transition"
        or s1.get("formal_business_data") is not False
        or s1.get("application_commit_sha") != expected_commit
        or int(s1.get("source_row_count", -1)) != int(s1.get("target_row_count", -2))
        or s1.get("source_content_sha256") != s1.get("target_content_sha256")
    ):
        raise RemainingUnitCutoverError("exact S1 reconciliation is incomplete")

    if recovery.get("schema_version") not in {
        "honghu.stage4_production_recovery.v1",
        "honghu.stage4_production_recovery.v2",
    }:
        raise RemainingUnitCutoverError("unsupported recovery evidence")
    if (
        recovery.get("status") != "pass"
        or recovery.get("off_vm_verified") is not True
        or recovery.get("whole_database_restore") != "pass"
        or recovery.get("application_commit_sha") != expected_commit
    ):
        raise RemainingUnitCutoverError("exact-commit off-VM recovery is not verified")
    target = recovery.get("target") or {}
    recovered = recovery.get("recovered") or {}
    if (
        recovered.get("target_lsn_reached") is not True
        or not target.get("sentinel_operation_id")
        or recovered.get("sentinel_operation_id") != target.get("sentinel_operation_id")
    ):
        raise RemainingUnitCutoverError("recovery WAL target/sentinel is not verified")
    authority = (recovery.get("authority_snapshots") or {}).get(unit)
    if not isinstance(authority, dict) or (
        authority.get("state") != "S1"
        or authority.get("authoritative_backend") != "sqlite_transition"
    ):
        raise RemainingUnitCutoverError("off-VM recovery does not bind unit S1 authority")


def _authority(connection: Any, unit: str) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT state,authoritative_backend,state_revision,writer_identity,
               cutover_epoch,approval_reference,sqlite_final_watermark,
               postgresql_first_formal_commit
          FROM operations.cutover_unit_authority WHERE cutover_unit=%s
        """,
        (unit,),
    ).fetchone()
    if row is None:
        raise RemainingUnitCutoverError(f"authority row is absent: {unit}")
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


def build_or_load_intent(
    path: Path,
    *,
    unit: str,
    s1: dict[str, Any],
    decision: dict[str, Any],
    writer_identity: str,
    actor: str,
) -> dict[str, Any]:
    if path.exists():
        value = _load(path)
        if (
            value.get("schema_version") != "honghu.remaining_unit_cutover_intent.v1"
            or value.get("cutover_unit") != unit
            or value.get("source_snapshot_id") != s1.get("source_snapshot_id")
            or value.get("application_commit_sha") != s1.get("application_commit_sha")
            or value.get("writer_identity") != writer_identity
        ):
            raise RemainingUnitCutoverError("persisted intent belongs to another cutover")
        return value
    core = {
        "schema_version": "honghu.remaining_unit_cutover_intent.v1",
        "cutover_unit": unit,
        "application_commit_sha": s1["application_commit_sha"],
        "source_snapshot_id": s1["source_snapshot_id"],
        "source_identity_sha256": s1["source_identity_sha256"],
        "writer_identity": writer_identity,
        "actor": actor,
        "approval_reference": decision["approval_reference"],
        "cutover_epoch": f"{unit}:{uuid.uuid4().hex}",
        "activation_idempotency_key": f"{unit}:activate:{uuid.uuid4().hex}",
    }
    core["activation_request_sha256"] = _sha(
        {
            "cutover_unit": unit,
            "source_snapshot_id": core["source_snapshot_id"],
            "application_commit_sha": core["application_commit_sha"],
            "approval_reference": core["approval_reference"],
        }
    )
    result = {**core, "intent_sha256": _sha(core)}
    _write(path, result)
    return result


def cutover(
    *,
    unit: str,
    controller: Any,
    writer: Any,
    reader: Any,
    s1: dict[str, Any],
    intent: dict[str, Any],
    data_root: Path,
) -> dict[str, Any]:
    watermark = {
        "source_snapshot_id": s1["source_snapshot_id"],
        "source_identity_sha256": s1["source_identity_sha256"],
        "source_row_count": int(s1["source_row_count"]),
        "source_content_sha256": s1["source_content_sha256"],
    }
    writer_identity = str(intent["writer_identity"])
    actor = str(intent["actor"])
    approval = str(intent["approval_reference"])
    epoch = str(intent["cutover_epoch"])
    before = _authority(reader, unit)
    if before["state"] == "S1":
        write_authority_fence(
            data_root,
            cutover_unit=unit,
            authority_state="S2_PENDING",
            authoritative_backend="postgresql_production",
            authority_evidence_sha256=intent["intent_sha256"],
            approval_reference=approval,
            cutover_epoch=epoch,
        )
        with controller.transaction():
            row = controller.execute(
                """SELECT * FROM operations.transition_remaining_unit(
                    %s,'S1',%s,'S2',%s,%s,%s::jsonb,%s,%s,%s
                )""",
                (
                    unit,
                    before["revision"],
                    writer_identity,
                    epoch,
                    json.dumps(watermark, ensure_ascii=False),
                    actor,
                    approval,
                    "approved remaining-unit production authority transition",
                ),
            ).fetchone()
        if row is None or str(row[1]) != "S2":
            raise RemainingUnitCutoverError("unit did not enter the short S2 fence")
    elif before["state"] not in {"S2", "S3"}:
        raise RemainingUnitCutoverError("unit authority is outside S1/S2/S3")

    fenced = _authority(reader, unit)
    if (
        fenced["backend"] != "postgresql_production"
        or fenced["writer_identity"] != writer_identity
        or fenced["cutover_epoch"] != epoch
        or fenced["approval_reference"] != approval
    ):
        raise RemainingUnitCutoverError("S2/S3 authority does not match persisted intent")
    if fenced["state"] == "S2":
        with writer.transaction():
            result = writer.execute(
                """SELECT domain_data.activate_unit_snapshot_v1(
                    %s,%s,%s,%s,%s,%s,%s,%s
                )""",
                (
                    unit,
                    s1["source_snapshot_id"],
                    fenced["revision"],
                    intent["activation_idempotency_key"],
                    intent["activation_request_sha256"],
                    s1["application_commit_sha"],
                    writer_identity,
                    actor,
                ),
            ).fetchone()
        if result is None:
            raise RemainingUnitCutoverError("snapshot activation returned no result")

    final = _authority(reader, unit)
    snapshot = reader.execute(
        """
        SELECT source_snapshot_id,source_identity_sha256,source_content_sha256,
               source_row_count,formal_revision,application_commit_sha
          FROM domain_data.formal_unit_snapshot WHERE cutover_unit=%s
        """,
        (unit,),
    ).fetchone()
    if (
        final["state"] != "S3"
        or final["backend"] != "postgresql_production"
        or final["writer_identity"] != writer_identity
        or final["cutover_epoch"] != epoch
        or not isinstance(final["postgresql_first_formal_commit"], dict)
        or snapshot is None
        or str(snapshot[0]) != str(s1["source_snapshot_id"])
        or str(snapshot[1]) != str(s1["source_identity_sha256"])
        or str(snapshot[2]) != str(s1["source_content_sha256"])
        or int(snapshot[3]) != int(s1["source_row_count"])
        or str(snapshot[5]) != str(s1["application_commit_sha"])
    ):
        raise RemainingUnitCutoverError("durable unit S3 reconciliation failed")
    core = {
        "schema_version": "honghu.remaining_unit_s3_evidence.v1",
        "cutover_unit": unit,
        "state": "S3",
        "authoritative_backend": "postgresql_production",
        "state_revision": final["revision"],
        "writer_identity": writer_identity,
        "cutover_epoch": epoch,
        "approval_reference": approval,
        "source_snapshot_id": str(snapshot[0]),
        "source_identity_sha256": str(snapshot[1]),
        "source_content_sha256": str(snapshot[2]),
        "formal_row_count": int(snapshot[3]),
        "formal_revision": int(snapshot[4]),
        "source_snapshot_application_commit_sha": s1.get(
            "source_snapshot_application_commit_sha", s1["application_commit_sha"]
        ),
        "sqlite_final_watermark": final["sqlite_final_watermark"],
        "postgresql_first_formal_commit": final["postgresql_first_formal_commit"],
        "sqlite_writer_fenced": True,
        "intent_sha256": intent["intent_sha256"],
        "application_commit_sha": s1["application_commit_sha"],
    }
    evidence = {**core, "evidence_sha256": _sha(core)}
    write_authority_fence(
        data_root,
        cutover_unit=unit,
        authority_state="S3",
        authoritative_backend="postgresql_production",
        authority_evidence_sha256=evidence["evidence_sha256"],
        approval_reference=approval,
        cutover_epoch=epoch,
    )
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", choices=UNITS, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--decision", type=Path, required=True)
    parser.add_argument("--s1-evidence", type=Path, required=True)
    parser.add_argument("--recovery-evidence", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--writer-identity", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--intent", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    registry = CutoverUnitRegistry.from_path(args.registry)
    decision = _load(args.decision)
    s1 = _load(args.s1_evidence)
    recovery = _load(args.recovery_evidence)
    validate_inputs(
        unit=args.unit,
        decision=decision,
        s1=s1,
        recovery=recovery,
        registry=registry,
        expected_commit=args.expected_commit,
    )
    intent = build_or_load_intent(
        args.intent,
        unit=args.unit,
        s1=s1,
        decision=decision,
        writer_identity=args.writer_identity,
        actor=args.actor,
    )
    controller = _connection_from_runtime(args.runtime, "controller")
    writer = _connection_from_runtime(args.runtime, f"writer_{args.unit}")
    reader = _connection_from_runtime(args.runtime, "migration")
    try:
        result = cutover(
            unit=args.unit,
            controller=controller,
            writer=writer,
            reader=reader,
            s1=s1,
            intent=intent,
            data_root=args.data_root,
        )
    finally:
        controller.close()
        writer.close()
        reader.close()
    _write(args.output, result)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
