from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from tools.migration.stage4_identity_mapping import IdentityMappingResolver
from tools.migration.stage4_s1_loader import (
    Stage4LoadError,
    _connection_from_runtime,
    _load_json,
    validate_sqlite_authority_route,
)


class UserContentS1Error(RuntimeError):
    pass


APPROVAL_SCHEMA = "honghu.identity_mapping_cutover_approval.v1"


def _sha(value: Any) -> str:
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _legacy_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return parsed


def validate_mapping_approval(
    mapping: dict[str, Any], approval: dict[str, Any]
) -> dict[str, Any]:
    IdentityMappingResolver(mapping)
    if approval.get("schema_version") != APPROVAL_SCHEMA:
        raise UserContentS1Error("unsupported cutover mapping approval schema")
    core = {key: value for key, value in approval.items() if key != "approval_sha256"}
    if approval.get("approval_sha256") != _sha(core):
        raise UserContentS1Error("cutover mapping approval hash mismatch")
    if approval.get("mapping_manifest_sha256") != mapping.get("manifest_sha256"):
        raise UserContentS1Error("mapping approval references another manifest")
    if approval.get("cutover_level_approved") is not True:
        raise UserContentS1Error("mapping does not have human cutover-level approval")
    if approval.get("approved_by") != "user":
        raise UserContentS1Error("mapping approval is not attributed to the user")
    for field in ("approval_reference", "approved_at_utc"):
        if not str(approval.get(field) or "").strip():
            raise UserContentS1Error(f"mapping approval missing {field}")
    approved_manual = approval.get("manual_review_resolutions") or []
    if int(approval.get("manual_review_item_count", -1)) != len(approved_manual):
        raise UserContentS1Error("manual mapping resolution count mismatch")
    return approval


def _authority(cursor: Any) -> tuple[Any, ...] | None:
    cursor.execute(
        """
        SELECT state, authoritative_backend, state_revision, writer_identity,
               cutover_epoch, postgresql_first_formal_commit
          FROM operations.cutover_unit_authority
         WHERE cutover_unit='user_content_notes'
        """
    )
    return cursor.fetchone()


def promote_user_content_to_s1(
    connection: Any,
    *,
    snapshot_id: str,
    mapping: dict[str, Any],
    approval: dict[str, Any],
    actor: str,
) -> dict[str, Any]:
    approval = validate_mapping_approval(mapping, approval)
    if not actor.startswith("principal:"):
        raise UserContentS1Error("S1 migration actor must be a trusted principal identity")
    resolver = IdentityMappingResolver(mapping)
    approval_reference = str(approval["approval_reference"])
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT cutover_unit, lifecycle_state, formal_business_data,
                       reconciliation, application_commit_sha
                  FROM migration.unit_snapshot
                 WHERE snapshot_id=%s
                 FOR UPDATE
                """,
                (snapshot_id,),
            )
            snapshot = cursor.fetchone()
            if (
                snapshot is None
                or snapshot[0] != "user_content_notes"
                or snapshot[1] != "reconciled"
                or snapshot[2] is not False
                or (snapshot[3] or {}).get("status") != "pass"
            ):
                raise UserContentS1Error("user-content staging snapshot is not reconciled")
            application_commit_sha = str(snapshot[4])
            if len(application_commit_sha) != 40 or any(
                character not in "0123456789abcdef" for character in application_commit_sha
            ):
                raise UserContentS1Error("staging snapshot application commit is invalid")

            authority = _authority(cursor)
            if authority is None:
                cursor.execute(
                    """
                    SELECT * FROM operations.prepare_user_content_notes_authority_s1(
                        'ABSENT',0,'S0',%s,%s,%s
                    )
                    """,
                    (actor, approval_reference, "initialize approved S1 preparation"),
                )
                authority = _authority(cursor)
            if authority is None or authority[0] not in {"S0", "S1"}:
                raise UserContentS1Error("user-content authority is outside S0/S1")
            if authority[1] != "sqlite_transition" or any(
                value is not None for value in (authority[3], authority[4], authority[5])
            ):
                raise UserContentS1Error("S0/S1 authority contains production-writer state")
            if authority[0] == "S0":
                cursor.execute(
                    """
                    SELECT * FROM operations.prepare_user_content_notes_authority_s1(
                        'S0',%s,'S1',%s,%s,%s
                    )
                    """,
                    (
                        int(authority[2]),
                        actor,
                        approval_reference,
                        "mapping, backfill and reconciliation candidate approved for S1",
                    ),
                )
                authority = _authority(cursor)
            assert authority is not None
            authority_revision = int(authority[2])

            mapping_count = 0
            for record in mapping.get("mappings") or []:
                cursor.execute(
                    """
                    SELECT * FROM operations.register_user_content_notes_dependency_mapping(
                        %s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s
                    )
                    """,
                    (
                        authority_revision,
                        record["entity_type"],
                        record["source_database"],
                        record["source_table"],
                        str(record["legacy_id"]),
                        record["stable_key"],
                        json.dumps(record["source_watermark"], ensure_ascii=False),
                        record["source_evidence_identity"],
                        actor,
                        approval_reference,
                        "approved legacy-to-stable identity mapping",
                    ),
                )
                mapping_count += 1

            cursor.execute(
                """
                SELECT payload
                  FROM migration.source_row
                 WHERE snapshot_id=%s
                   AND source_database='research.db'
                   AND source_table='analyst_note'
                 ORDER BY source_ordinal
                """,
                (snapshot_id,),
            )
            source_rows = cursor.fetchall()
            for (payload,) in source_rows:
                legacy_note_id = int(payload["id"])
                entity_type = str(payload["entity_type"])
                legacy_entity_id = str(payload["entity_id"])
                entity_key = resolver.resolve(entity_type, legacy_entity_id)
                note_key = f"analyst-note:legacy:research.db:{legacy_note_id}"
                created_at = _legacy_time(payload.get("created_at"))
                updated_at = _legacy_time(payload.get("updated_at")) or created_at
                cursor.execute(
                    """
                    INSERT INTO user_content.analyst_note(
                        note_key, entity_type, entity_id, q_number, q_label,
                        note_type, title, content, author, revision,
                        entity_key, legacy_entity_id_text, legacy_note_id,
                        legacy_created_at_text, legacy_updated_at_text,
                        created_at, updated_at
                    ) VALUES (
                        %s,%s,%s,NULL,%s,%s,%s,%s,%s,1,%s,%s,%s,%s,%s,
                        coalesce(%s,clock_timestamp()),coalesce(%s,%s,clock_timestamp())
                    )
                    ON CONFLICT (note_key) DO NOTHING
                    """,
                    (
                        note_key,
                        entity_type,
                        int(legacy_entity_id) if legacy_entity_id.isdigit() else None,
                        payload.get("q_number"),
                        payload.get("note_type") or "general",
                        payload.get("title"),
                        payload["content"],
                        payload.get("author") or "legacy",
                        entity_key,
                        legacy_entity_id,
                        legacy_note_id,
                        payload.get("created_at"),
                        payload.get("updated_at"),
                        created_at,
                        updated_at,
                        created_at,
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO audit.user_content_revision(
                        object_type, object_key, revision, action, actor,
                        idempotency_key, payload
                    )
                    SELECT 'analyst_note', n.note_key, 1, 'create', %s,
                           %s, to_jsonb(n)
                      FROM user_content.analyst_note n
                     WHERE n.note_key=%s
                    ON CONFLICT (object_type, object_key, revision) DO NOTHING
                    """,
                    (actor, f"s1-backfill:{snapshot_id}:{legacy_note_id}", note_key),
                )

            cursor.execute(
                """
                SELECT count(*), count(*) FILTER (WHERE n.note_id IS NOT NULL)
                  FROM migration.source_row s
                  LEFT JOIN user_content.analyst_note n
                    ON n.legacy_note_id=(s.payload->>'id')::bigint
                 WHERE s.snapshot_id=%s
                   AND s.source_database='research.db'
                   AND s.source_table='analyst_note'
                """,
                (snapshot_id,),
            )
            source_count, matched_count = cursor.fetchone()
            cursor.execute(
                """
                SELECT count(*) FROM operations.cutover_dependency_mapping
                 WHERE cutover_unit='user_content_notes'
                """
            )
            target_mapping_count = int(cursor.fetchone()[0])
            if int(source_count) != int(matched_count):
                raise UserContentS1Error("analyst-note backfill reconciliation failed")
            if target_mapping_count != mapping_count:
                raise UserContentS1Error("dependency mapping reconciliation failed")
            final_authority = _authority(cursor)
            if final_authority is None or final_authority[:2] != (
                "S1",
                "sqlite_transition",
            ):
                raise UserContentS1Error("authority did not finish in S1/SQLite")

    result_core = {
        "schema_version": "honghu.user_content_notes_s1_evidence.v1",
        "cutover_unit": "user_content_notes",
        "state": "S1",
        "authoritative_backend": "sqlite_transition",
        "sqlite_formal_writer_enabled": True,
        "postgresql_formal_business_mutations": False,
        "snapshot_id": snapshot_id,
        "application_commit_sha": application_commit_sha,
        "mapping_manifest_sha256": mapping["manifest_sha256"],
        "mapping_approval_sha256": approval["approval_sha256"],
        "mapping_count": mapping_count,
        "source_note_count": int(source_count),
        "target_note_count": int(matched_count),
        "authority_revision": authority_revision,
        "actor": actor,
        "approval_reference": approval_reference,
    }
    return {**result_core, "evidence_sha256": _sha(result_core)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--route", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--mapping-approval", type=Path, required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    validate_sqlite_authority_route(
        cutover_unit="user_content_notes",
        route_path=args.route,
        registry_path=args.registry,
    )
    mapping = _load_json(args.mapping)
    approval = _load_json(args.mapping_approval)
    connection = _connection_from_runtime(args.runtime, "migration")
    try:
        result = promote_user_content_to_s1(
            connection,
            snapshot_id=args.snapshot_id,
            mapping=mapping,
            approval=approval,
            actor=args.actor,
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
