from __future__ import annotations

"""Promote reconciled migration snapshots to disposable production S1.

The owning application adapters are deliberately outside this helper.  S1
only proves that an exact, current SQLite snapshot is durably backfilled and
reconciled in PostgreSQL while SQLite remains the sole business authority and
writer.  No formal business row is created and this module cannot enter S2.
"""

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from tools.migration.stage4_s1_loader import _connection_from_runtime


class GenericUnitS1Error(RuntimeError):
    pass


DEPENDENCIES: dict[str, tuple[str, ...]] = {
    # financial_data already has a domain-specific S1 projection, but the
    # remaining-unit cutover consumes the immutable migration.source_row
    # snapshot.  Rebinding that verified snapshot to a newer compatible
    # application release must not re-copy the financial rows.
    "financial_data": ("shared_identity",),
    "research_publication": ("shared_identity",),
    "dynamic_intelligence": ("shared_identity", "research_publication"),
    "operations_governance": ("shared_identity", "dynamic_intelligence"),
    "investment_hypotheses": (
        "shared_identity",
        "research_publication",
        "dynamic_intelligence",
    ),
    "opportunity_lens": (
        "shared_identity",
        "financial_data",
        "research_publication",
        "dynamic_intelligence",
    ),
    "sentiment_analytics": ("shared_identity", "dynamic_intelligence"),
}


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    raise GenericUnitS1Error("snapshot reconciliation is not a JSON object")


def _validate_dependency_states(
    unit: str, rows: dict[str, tuple[str, str]]
) -> None:
    expected = set(DEPENDENCIES[unit])
    if set(rows) != expected:
        raise GenericUnitS1Error("dependency authority evidence is incomplete")
    for dependency, (state, backend) in rows.items():
        if state not in {"S1", "S3", "S4"}:
            raise GenericUnitS1Error(
                f"dependency is not migration-ready: {dependency}={state}"
            )
        if dependency == "shared_identity":
            if state not in {"S3", "S4"} or backend != "postgresql_production":
                raise GenericUnitS1Error(
                    "shared_identity must be PostgreSQL-authoritative before dependent S1"
                )
        elif state == "S1" and backend != "sqlite_transition":
            raise GenericUnitS1Error("S1 dependency has an invalid authoritative backend")
        elif state in {"S3", "S4"} and backend != "postgresql_production":
            raise GenericUnitS1Error("formal dependency has an invalid authoritative backend")


def promote_generic_unit_s1(
    connection: Any,
    *,
    unit: str,
    application_commit_sha: str,
    actor: str,
    approval_reference: str,
) -> dict[str, Any]:
    if unit not in DEPENDENCIES:
        raise GenericUnitS1Error(f"unit has no reviewed generic S1 contract: {unit}")
    if not re.fullmatch(r"[0-9a-f]{40}", application_commit_sha):
        raise GenericUnitS1Error("full lowercase application commit SHA is required")
    if not actor.strip() or not approval_reference.strip():
        raise GenericUnitS1Error("actor and approval reference are required")

    with connection.transaction():
        snapshot = connection.execute(
            """
            SELECT snapshot_id,source_identity_sha256,reconciliation,
                   target_watermark,application_commit_sha,formal_business_data
              FROM migration.unit_snapshot
             WHERE cutover_unit=%s AND lifecycle_state='reconciled'
             ORDER BY imported_at DESC LIMIT 1
            """,
            (unit,),
        ).fetchone()
        if snapshot is None:
            raise GenericUnitS1Error("reconciled migration snapshot is missing")
        source_snapshot_application_commit = str(snapshot[4])
        if not re.fullmatch(r"[0-9a-f]{40}", source_snapshot_application_commit):
            raise GenericUnitS1Error("migration snapshot application identity is invalid")
        if bool(snapshot[5]):
            raise GenericUnitS1Error("S1 snapshot unexpectedly contains formal business data")
        snapshot_id = str(snapshot[0])
        source_identity = str(snapshot[1])
        reconciliation = _mapping(snapshot[2])
        target_watermark = _mapping(snapshot[3])
        source_count = int(reconciliation.get("source_row_count", -1))
        source_content = str(reconciliation.get("source_content_sha256") or "")
        if (
            reconciliation.get("status") != "pass"
            or int(reconciliation.get("target_row_count", -2)) != source_count
            or str(reconciliation.get("target_content_sha256") or "") != source_content
            or int(target_watermark.get("row_count", -3)) != source_count
            or str(target_watermark.get("content_sha256") or "") != source_content
            or target_watermark.get("formal_business_data") is not False
        ):
            raise GenericUnitS1Error("snapshot reconciliation/watermark contract is incomplete")

        digest = hashlib.sha256()
        row_count = 0
        for identity in connection.execute(
            """
            SELECT source_database,source_table,source_ordinal,source_key,row_sha256
              FROM migration.source_row
             WHERE snapshot_id=%s
             ORDER BY source_database,source_table,source_ordinal
            """,
            (snapshot_id,),
        ):
            digest.update(
                json.dumps(
                    tuple(identity),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            digest.update(b"\n")
            row_count += 1
        if row_count != source_count or digest.hexdigest() != source_content:
            raise GenericUnitS1Error("durable PostgreSQL source-row reconciliation failed")

        dependency_names = DEPENDENCIES[unit]
        dependency_rows = connection.execute(
            """
            SELECT cutover_unit,state,authoritative_backend
              FROM operations.cutover_unit_authority
             WHERE cutover_unit=ANY(%s)
            """,
            (list(dependency_names),),
        ).fetchall()
        dependencies = {
            str(row[0]): (str(row[1]), str(row[2])) for row in dependency_rows
        }
        _validate_dependency_states(unit, dependencies)

        authority = connection.execute(
            """
            SELECT state,state_revision,authoritative_backend
              FROM operations.cutover_unit_authority
             WHERE cutover_unit=%s
            """,
            (unit,),
        ).fetchone()
        if authority is None:
            connection.execute(
                "SELECT * FROM operations.prepare_cutover_unit_authority_s1(%s,%s,%s,%s,%s,%s,%s)",
                (
                    unit,
                    "ABSENT",
                    0,
                    "S0",
                    actor,
                    approval_reference,
                    "initialize reconciled migration target authority control",
                ),
            ).fetchone()
            authority = ("S0", 1, "sqlite_transition")
        if str(authority[0]) == "S0" and str(authority[2]) == "sqlite_transition":
            promoted = connection.execute(
                "SELECT * FROM operations.prepare_cutover_unit_authority_s1(%s,%s,%s,%s,%s,%s,%s)",
                (
                    unit,
                    "S0",
                    int(authority[1]),
                    "S1",
                    actor,
                    approval_reference,
                    "promote exact reconciled migration target to disposable S1",
                ),
            ).fetchone()
            state, revision = str(promoted[1]), int(promoted[2])
        elif str(authority[0]) == "S1" and str(authority[2]) == "sqlite_transition":
            state, revision = "S1", int(authority[1])
        else:
            raise GenericUnitS1Error("unit authority is outside the S0/S1 preparation boundary")

    core = {
        "schema_version": "honghu.generic_unit_s1_evidence.v1",
        "cutover_unit": unit,
        "application_commit_sha": application_commit_sha,
        "source_snapshot_application_commit_sha": source_snapshot_application_commit,
        "release_binding_contract": (
            "reconciled rows remain immutable; this evidence separately binds the "
            "reviewed production adapter release without copying unchanged source rows"
        ),
        "authority_state": state,
        "state_revision": revision,
        "authoritative_backend": "sqlite_transition",
        "source_snapshot_id": snapshot_id,
        "source_identity_sha256": source_identity,
        "source_row_count": source_count,
        "target_row_count": row_count,
        "source_content_sha256": source_content,
        "target_content_sha256": source_content,
        "dependencies": {
            key: {"state": value[0], "authoritative_backend": value[1]}
            for key, value in sorted(dependencies.items())
        },
        "target_storage": "migration.source_row",
        "formal_business_data": False,
        "application_compatibility_ready": False,
        "production_cutover_authorized": False,
        "s2_s3_entered": False,
    }
    return {**core, "evidence_sha256": _sha(core)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--unit", choices=tuple(DEPENDENCIES), required=True)
    parser.add_argument("--application-commit-sha", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--approval-reference", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    connection = _connection_from_runtime(args.runtime, "migration")
    try:
        result = promote_generic_unit_s1(
            connection,
            unit=args.unit,
            application_commit_sha=args.application_commit_sha,
            actor=args.actor,
            approval_reference=args.approval_reference,
        )
    finally:
        connection.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
