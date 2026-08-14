from __future__ import annotations

"""Promote a reconciled shared-identity snapshot into its formal S1 schema."""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from tools.migration.stage4_identity_mapping import IdentityMappingResolver
from tools.migration.stage4_json_io import read_json
from tools.migration.stage4_s1_loader import _connection_from_runtime


class SharedIdentityS1Error(RuntimeError):
    pass


ENTITY_TABLES = {"company", "industry", "theme", "researcher", "financial_security"}
PROFILE_TABLES = {"company_profile", "company_sub_market_share"}
MAPPING_TABLES = {
    "company_identity_alias",
    "company_identity_redirect",
    "financial_security_company_link",
}


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = read_json(path)
    if not isinstance(value, dict):
        raise SharedIdentityS1Error(f"JSON object required: {path}")
    return value


def _record_kind(table: str) -> str:
    if table in ENTITY_TABLES:
        return "entity"
    if table in PROFILE_TABLES:
        return "profile"
    if table in MAPPING_TABLES:
        return "mapping"
    return "relationship"


def _legacy_id(payload: dict[str, Any], source_key: str) -> str:
    for name in (
        "id",
        "old_company_id",
        "research_company_id",
        "company_id",
    ):
        if payload.get(name) is not None:
            return str(payload[name])
    return str(source_key)


def _stable_key(
    *,
    source_database: str,
    source_table: str,
    legacy_id: str,
    source_key: str,
    payload: dict[str, Any],
    mapping: IdentityMappingResolver,
) -> str:
    entity_type = {
        "company": "company",
        "industry": "industry",
        "theme": "theme",
    }.get(source_table)
    if entity_type:
        return mapping.resolve(entity_type, legacy_id)
    if source_table == "financial_security" and payload.get("research_company_id") is not None:
        return mapping.resolve("company", str(payload["research_company_id"]))
    if source_table == "researcher":
        name = str(payload.get("name") or "").strip().casefold()
        if not name:
            raise SharedIdentityS1Error("researcher identity has no stable name")
        return f"researcher:name:{_sha(name)}"
    return f"shared-identity:{source_database}:{source_table}:{source_key}"


def promote_shared_identity_s1(
    connection: Any,
    *,
    mapping_path: Path,
    actor: str,
    approval_reference: str,
) -> dict[str, Any]:
    mapping_payload = _load(mapping_path)
    mapping = IdentityMappingResolver(mapping_payload)
    manifest_sha = str(mapping_payload["manifest_sha256"])

    with connection.transaction():
        snapshot = connection.execute(
            """
            SELECT snapshot_id,source_identity_sha256,reconciliation
              FROM migration.unit_snapshot
             WHERE cutover_unit='shared_identity' AND lifecycle_state='reconciled'
             ORDER BY imported_at DESC LIMIT 1
            """
        ).fetchone()
        if snapshot is None:
            raise SharedIdentityS1Error("reconciled shared_identity staging snapshot is missing")
        snapshot_id = str(snapshot[0])
        source_identity = str(snapshot[1])
        reconciliation = snapshot[2]
        if isinstance(reconciliation, str):
            reconciliation = json.loads(reconciliation)
        source_count = int(reconciliation["source_row_count"])
        source_content = str(reconciliation["source_content_sha256"])

        rows = connection.execute(
            """
            SELECT source_database,source_table,source_ordinal,source_key,row_sha256,payload
              FROM migration.source_row
             WHERE snapshot_id=%s
             ORDER BY source_database,source_table,source_ordinal
            """,
            (snapshot_id,),
        ).fetchall()
        if len(rows) != source_count:
            raise SharedIdentityS1Error("staging row count changed before S1 promotion")

        records: list[tuple[Any, ...]] = []
        digest = hashlib.sha256()
        for database, table, ordinal, source_key, row_sha, raw_payload in rows:
            payload = raw_payload if isinstance(raw_payload, dict) else json.loads(raw_payload)
            legacy_id = _legacy_id(payload, str(source_key))
            stable = _stable_key(
                source_database=str(database),
                source_table=str(table),
                legacy_id=legacy_id,
                source_key=str(source_key),
                payload=payload,
                mapping=mapping,
            )
            identity = [str(database), str(table), int(ordinal), str(source_key), str(row_sha)]
            digest.update(
                json.dumps(identity, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            )
            digest.update(b"\n")
            records.append(
                (
                    str(database),
                    str(table),
                    legacy_id,
                    stable,
                    _record_kind(str(table)),
                    str(row_sha),
                    json.dumps(payload, ensure_ascii=False),
                    snapshot_id,
                    int(ordinal),
                )
            )
        if digest.hexdigest() != source_content:
            raise SharedIdentityS1Error("staging content identity changed before S1 promotion")

        connection.execute(
            "DELETE FROM shared_identity.legacy_record WHERE source_snapshot_id<>%s",
            (snapshot_id,),
        )
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO shared_identity.legacy_record(
                    source_database,source_table,legacy_id,stable_key,record_kind,
                    row_sha256,payload,source_snapshot_id,source_ordinal,
                    formal_business_data,revision
                ) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,false,1)
                ON CONFLICT (source_database,source_table,legacy_id) DO UPDATE SET
                    stable_key=excluded.stable_key,
                    record_kind=excluded.record_kind,
                    row_sha256=excluded.row_sha256,
                    payload=excluded.payload,
                    source_snapshot_id=excluded.source_snapshot_id,
                    source_ordinal=excluded.source_ordinal,
                    formal_business_data=false,
                    revision=shared_identity.legacy_record.revision+1,
                    promoted_at=clock_timestamp()
                """,
                records,
            )
        target_rows = connection.execute(
            """
            SELECT source_database,source_table,source_ordinal,row_sha256
              FROM shared_identity.legacy_record
             WHERE source_snapshot_id=%s
             ORDER BY source_database,source_table,source_ordinal
            """,
            (snapshot_id,),
        ).fetchall()
        if len(target_rows) != source_count:
            raise SharedIdentityS1Error("formal shared_identity row count reconciliation failed")
        # Source digest deliberately uses the original source key.  The target
        # table retains legacy_id/stable_key separately, so compare every
        # source row hash and ordinal rather than inventing a new content hash.
        observed = {
            (str(row[0]), str(row[1]), int(row[2])): str(row[3]) for row in target_rows
        }
        for database, table, ordinal, _source_key, row_sha, _payload in rows:
            if observed.get((str(database), str(table), int(ordinal))) != str(row_sha):
                raise SharedIdentityS1Error("formal shared_identity row hash reconciliation failed")

        authority = connection.execute(
            """
            SELECT state,state_revision,authoritative_backend
              FROM operations.cutover_unit_authority
             WHERE cutover_unit='shared_identity' FOR UPDATE
            """
        ).fetchone()
        if authority is None:
            connection.execute(
                "SELECT * FROM operations.prepare_cutover_unit_authority_s1(%s,%s,%s,%s,%s,%s,%s)",
                (
                    "shared_identity",
                    "ABSENT",
                    0,
                    "S0",
                    actor,
                    approval_reference,
                    "initialize shared identity authority control",
                ),
            ).fetchone()
            authority = ("S0", 1, "sqlite_transition")
        if str(authority[0]) == "S0":
            authority = connection.execute(
                "SELECT * FROM operations.prepare_cutover_unit_authority_s1(%s,%s,%s,%s,%s,%s,%s)",
                (
                    "shared_identity",
                    "S0",
                    int(authority[1]),
                    "S1",
                    actor,
                    approval_reference,
                    "promote reconciled shared identity target schema to S1",
                ),
            ).fetchone()
            state, revision = str(authority[1]), int(authority[2])
        elif str(authority[0]) == "S1" and str(authority[2]) == "sqlite_transition":
            state, revision = "S1", int(authority[1])
        else:
            raise SharedIdentityS1Error("shared_identity authority is outside S0/S1")

        connection.execute(
            """
            INSERT INTO shared_identity.unit_snapshot(
                cutover_unit,source_snapshot_id,source_identity_sha256,
                mapping_manifest_sha256,source_row_count,target_row_count,
                source_content_sha256,target_content_sha256,
                authority_state,formal_business_data
            ) VALUES ('shared_identity',%s,%s,%s,%s,%s,%s,%s,%s,false)
            ON CONFLICT (cutover_unit) DO UPDATE SET
                source_snapshot_id=excluded.source_snapshot_id,
                source_identity_sha256=excluded.source_identity_sha256,
                mapping_manifest_sha256=excluded.mapping_manifest_sha256,
                source_row_count=excluded.source_row_count,
                target_row_count=excluded.target_row_count,
                source_content_sha256=excluded.source_content_sha256,
                target_content_sha256=excluded.target_content_sha256,
                authority_state=excluded.authority_state,
                formal_business_data=false,
                promoted_at=clock_timestamp()
            """,
            (
                snapshot_id,
                source_identity,
                manifest_sha,
                source_count,
                source_count,
                source_content,
                source_content,
                state,
            ),
        )

    core = {
        "schema_version": "honghu.shared_identity_s1_evidence.v1",
        "cutover_unit": "shared_identity",
        "authority_state": state,
        "state_revision": revision,
        "authoritative_backend": "sqlite_transition",
        "source_snapshot_id": snapshot_id,
        "source_identity_sha256": source_identity,
        "mapping_manifest_sha256": manifest_sha,
        "source_row_count": source_count,
        "target_row_count": source_count,
        "source_content_sha256": source_content,
        "target_content_sha256": source_content,
        "formal_business_data": False,
        "sqlite_writer_fenced": False,
        "production_cutover_authorized": False,
    }
    return {**core, "evidence_sha256": _sha(core)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--approval-reference", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    connection = _connection_from_runtime(args.runtime, "migration")
    try:
        result = promote_shared_identity_s1(
            connection,
            mapping_path=args.mapping,
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
