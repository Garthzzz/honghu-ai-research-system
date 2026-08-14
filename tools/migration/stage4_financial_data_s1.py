from __future__ import annotations

"""Promote the reconciled financial-data staging snapshot into formal S1.

S1 remains disposable migration material: SQLite is still the sole business
authority and writer.  The promotion verifies all cross-table references and
all security references against the shared-identity S1 snapshot before it
records an authority state.
"""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from tools.migration.stage4_s1_loader import _connection_from_runtime


class FinancialDataS1Error(RuntimeError):
    pass


OWNED_TABLES = {
    "financial_schema_meta",
    "financial_source_snapshot",
    "financial_observation",
    "financial_observation_revision",
    "financial_model_run",
    "financial_model_input",
    "financial_model_output",
    "financial_reconciliation",
}


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _legacy_id(payload: dict[str, Any], source_key: str) -> str:
    if payload.get("id") is not None:
        return str(payload["id"])
    if payload.get("key") is not None:
        return str(payload["key"])
    return str(source_key)


def _stable_key(table: str, legacy_id: str, payload: dict[str, Any]) -> str:
    if table == "financial_observation" and str(payload.get("observation_key") or "").strip():
        return f"financial:observation:{payload['observation_key']}"
    if table == "financial_model_run" and str(payload.get("run_key") or "").strip():
        return f"financial:model-run:{payload['run_key']}"
    return f"financial:{table}:{legacy_id}"


def _require_reference(
    value: Any,
    allowed: set[str],
    *,
    table: str,
    field: str,
    nullable: bool = False,
) -> None:
    if value is None or str(value).strip() == "":
        if nullable:
            return
        raise FinancialDataS1Error(f"{table}.{field} is missing")
    if str(value) not in allowed:
        raise FinancialDataS1Error(f"{table}.{field} has an unmapped reference: {value}")


def _validate_references(
    records: list[dict[str, Any]], shared_security_ids: set[str]
) -> None:
    ids: dict[str, set[str]] = {table: set() for table in OWNED_TABLES}
    for record in records:
        ids[record["table"]].add(record["legacy_id"])
    for record in records:
        table = record["table"]
        payload = record["payload"]
        if table == "financial_observation":
            _require_reference(payload.get("security_id"), shared_security_ids, table=table, field="security_id")
            _require_reference(payload.get("source_snapshot_id"), ids["financial_source_snapshot"], table=table, field="source_snapshot_id", nullable=True)
            _require_reference(payload.get("model_run_id"), ids["financial_model_run"], table=table, field="model_run_id", nullable=True)
        elif table == "financial_observation_revision":
            _require_reference(payload.get("observation_id"), ids["financial_observation"], table=table, field="observation_id")
        elif table == "financial_model_run":
            _require_reference(payload.get("security_id"), shared_security_ids, table=table, field="security_id", nullable=True)
        elif table in {"financial_model_input", "financial_model_output", "financial_reconciliation"}:
            _require_reference(payload.get("model_run_id"), ids["financial_model_run"], table=table, field="model_run_id")


def promote_financial_data_s1(
    connection: Any, *, actor: str, approval_reference: str
) -> dict[str, Any]:
    with connection.transaction():
        snapshot = connection.execute(
            """
            SELECT snapshot_id,source_identity_sha256,reconciliation
              FROM migration.unit_snapshot
             WHERE cutover_unit='financial_data' AND lifecycle_state='reconciled'
             ORDER BY imported_at DESC LIMIT 1
            """
        ).fetchone()
        if snapshot is None:
            raise FinancialDataS1Error("reconciled financial_data staging snapshot is missing")
        snapshot_id = str(snapshot[0])
        source_identity = str(snapshot[1])
        reconciliation = snapshot[2]
        if isinstance(reconciliation, str):
            reconciliation = json.loads(reconciliation)
        source_count = int(reconciliation["source_row_count"])
        source_content = str(reconciliation["source_content_sha256"])

        shared = connection.execute(
            """
            SELECT source_snapshot_id,mapping_manifest_sha256,authority_state,
                   formal_business_data,target_row_count
              FROM shared_identity.unit_snapshot
             WHERE cutover_unit='shared_identity'
            """
        ).fetchone()
        if shared is None or str(shared[2]) not in {"S1", "S3", "S4"}:
            raise FinancialDataS1Error("shared identity dependency is not prepared")
        shared_snapshot_id = str(shared[0])
        mapping_sha = str(shared[1])
        shared_security_ids = {
            str(row[0])
            for row in connection.execute(
                """
                SELECT legacy_id FROM shared_identity.legacy_record
                 WHERE source_database='financial.db'
                   AND source_table='financial_security'
                   AND source_snapshot_id=%s
                """,
                (shared_snapshot_id,),
            ).fetchall()
        }
        if not shared_security_ids:
            raise FinancialDataS1Error("shared identity contains no financial security mapping")

        rows = connection.execute(
            """
            SELECT source_table,source_ordinal,source_key,row_sha256,payload
              FROM migration.source_row
             WHERE snapshot_id=%s AND source_database='financial.db'
             ORDER BY source_table,source_ordinal
            """,
            (snapshot_id,),
        ).fetchall()
        if len(rows) != source_count:
            raise FinancialDataS1Error("financial staging row count changed before S1")

        records: list[dict[str, Any]] = []
        digest = hashlib.sha256()
        for table, ordinal, source_key, row_sha, raw_payload in rows:
            table_name = str(table)
            if table_name not in OWNED_TABLES:
                raise FinancialDataS1Error(f"unowned financial table in snapshot: {table_name}")
            payload = raw_payload if isinstance(raw_payload, dict) else json.loads(raw_payload)
            legacy_id = _legacy_id(payload, str(source_key))
            digest.update(
                json.dumps(
                    ["financial.db", table_name, int(ordinal), str(source_key), str(row_sha)],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            digest.update(b"\n")
            records.append(
                {
                    "table": table_name,
                    "legacy_id": legacy_id,
                    "stable_key": _stable_key(table_name, legacy_id, payload),
                    "row_sha": str(row_sha),
                    "payload": payload,
                    "ordinal": int(ordinal),
                }
            )
        if digest.hexdigest() != source_content:
            raise FinancialDataS1Error("financial staging content identity changed before S1")
        _validate_references(records, shared_security_ids)

        connection.execute(
            "DELETE FROM financial_data.legacy_record WHERE source_snapshot_id<>%s",
            (snapshot_id,),
        )
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO financial_data.legacy_record(
                    source_table,legacy_id,stable_key,row_sha256,payload,
                    source_snapshot_id,source_ordinal,formal_business_data,revision
                ) VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s,false,1)
                ON CONFLICT (source_table,legacy_id) DO UPDATE SET
                    stable_key=excluded.stable_key,row_sha256=excluded.row_sha256,
                    payload=excluded.payload,source_snapshot_id=excluded.source_snapshot_id,
                    source_ordinal=excluded.source_ordinal,formal_business_data=false,
                    revision=financial_data.legacy_record.revision+1,
                    promoted_at=clock_timestamp()
                """,
                [
                    (
                        row["table"], row["legacy_id"], row["stable_key"], row["row_sha"],
                        json.dumps(row["payload"], ensure_ascii=False), snapshot_id, row["ordinal"],
                    )
                    for row in records
                ],
            )
        target_rows = connection.execute(
            """
            SELECT source_table,source_ordinal,row_sha256
              FROM financial_data.legacy_record
             WHERE source_snapshot_id=%s
             ORDER BY source_table,source_ordinal
            """,
            (snapshot_id,),
        ).fetchall()
        observed = {(str(row[0]), int(row[1])): str(row[2]) for row in target_rows}
        if len(observed) != source_count:
            raise FinancialDataS1Error("financial formal row-count reconciliation failed")
        for row in records:
            if observed.get((row["table"], row["ordinal"])) != row["row_sha"]:
                raise FinancialDataS1Error("financial formal row-hash reconciliation failed")

        authority = connection.execute(
            """
            SELECT state,state_revision,authoritative_backend
              FROM operations.cutover_unit_authority
             WHERE cutover_unit='financial_data' FOR UPDATE
            """
        ).fetchone()
        if authority is None:
            connection.execute(
                "SELECT * FROM operations.prepare_cutover_unit_authority_s1(%s,%s,%s,%s,%s,%s,%s)",
                ("financial_data", "ABSENT", 0, "S0", actor, approval_reference, "initialize financial authority control"),
            ).fetchone()
            authority = ("S0", 1, "sqlite_transition")
        if str(authority[0]) == "S0":
            promoted = connection.execute(
                "SELECT * FROM operations.prepare_cutover_unit_authority_s1(%s,%s,%s,%s,%s,%s,%s)",
                ("financial_data", "S0", int(authority[1]), "S1", actor, approval_reference, "promote reconciled financial target to S1"),
            ).fetchone()
            state, revision = str(promoted[1]), int(promoted[2])
        elif str(authority[0]) == "S1" and str(authority[2]) == "sqlite_transition":
            state, revision = "S1", int(authority[1])
        else:
            raise FinancialDataS1Error("financial_data authority is outside S0/S1")

        connection.execute(
            """
            INSERT INTO financial_data.unit_snapshot(
                cutover_unit,source_snapshot_id,source_identity_sha256,
                shared_identity_snapshot_id,shared_identity_mapping_sha256,
                source_row_count,target_row_count,source_content_sha256,target_content_sha256,
                authority_state,formal_business_data
            ) VALUES ('financial_data',%s,%s,%s,%s,%s,%s,%s,%s,%s,false)
            ON CONFLICT (cutover_unit) DO UPDATE SET
                source_snapshot_id=excluded.source_snapshot_id,
                source_identity_sha256=excluded.source_identity_sha256,
                shared_identity_snapshot_id=excluded.shared_identity_snapshot_id,
                shared_identity_mapping_sha256=excluded.shared_identity_mapping_sha256,
                source_row_count=excluded.source_row_count,target_row_count=excluded.target_row_count,
                source_content_sha256=excluded.source_content_sha256,
                target_content_sha256=excluded.target_content_sha256,
                authority_state=excluded.authority_state,formal_business_data=false,
                promoted_at=clock_timestamp()
            """,
            (snapshot_id, source_identity, shared_snapshot_id, mapping_sha, source_count, source_count, source_content, source_content, state),
        )

    core = {
        "schema_version": "honghu.financial_data_s1_evidence.v1",
        "cutover_unit": "financial_data",
        "authority_state": state,
        "state_revision": revision,
        "authoritative_backend": "sqlite_transition",
        "source_snapshot_id": snapshot_id,
        "source_identity_sha256": source_identity,
        "shared_identity_snapshot_id": shared_snapshot_id,
        "shared_identity_mapping_sha256": mapping_sha,
        "source_row_count": source_count,
        "target_row_count": source_count,
        "source_content_sha256": source_content,
        "target_content_sha256": source_content,
        "formal_business_data": False,
        "production_cutover_authorized": False,
    }
    return {**core, "evidence_sha256": _sha(core)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--approval-reference", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    connection = _connection_from_runtime(args.runtime, "migration")
    try:
        result = promote_financial_data_s1(
            connection, actor=args.actor, approval_reference=args.approval_reference
        )
    finally:
        connection.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
