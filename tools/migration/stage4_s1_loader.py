from __future__ import annotations

import argparse
import hashlib
import json
from itertools import islice
from pathlib import Path
from typing import Any, Iterable

from tools.migration.stage4_unit_s1 import UnitSnapshotError, verify_snapshot
from tools.migration.stage4_json_io import read_json


class Stage4LoadError(RuntimeError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    value = read_json(path)
    if not isinstance(value, dict):
        raise Stage4LoadError(f"JSON object required: {path}")
    return value


def validate_sqlite_authority_route(
    *, cutover_unit: str, route_path: Path, registry_path: Path
) -> dict[str, Any]:
    registry = _load_json(registry_path)
    unit = (registry.get("units") or {}).get(cutover_unit)
    if not isinstance(unit, dict):
        raise Stage4LoadError("cutover unit is absent from the reviewed registry")
    if unit.get("state") not in {"S0", "S1"}:
        raise Stage4LoadError("registry authority is outside S0/S1")
    if unit.get("authoritative_backend") != "sqlite_transition":
        raise Stage4LoadError("registry no longer names SQLite as authority")
    if cutover_unit != "user_content_notes":
        return {
            "cutover_unit": cutover_unit,
            "authority_state": unit["state"],
            "backend": unit["authoritative_backend"],
            "sqlite_writer_enabled": True,
            "production_postgresql_enabled": False,
        }
    route = _load_json(route_path)
    if route.get("cutover_unit") != cutover_unit:
        raise Stage4LoadError("unexpected tracked route cutover unit")
    if route.get("authority_state") not in {"S0", "S1"}:
        raise Stage4LoadError("tracked route is outside the S0/S1 preparation boundary")
    if route.get("backend") != "sqlite_transition":
        raise Stage4LoadError("tracked route no longer names SQLite as authority")
    if route.get("sqlite_writer_enabled") is not True:
        raise Stage4LoadError("tracked SQLite writer is unexpectedly fenced")
    if route.get("production_postgresql_enabled") is not False:
        raise Stage4LoadError("tracked production PostgreSQL route is unexpectedly enabled")
    return route


def _iter_rows(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise Stage4LoadError(f"row {line_number} is not a JSON object")
            yield value


def _batches(values: Iterable[dict[str, Any]], size: int = 1000) -> Iterable[list[dict[str, Any]]]:
    iterator = iter(values)
    while batch := list(islice(iterator, size)):
        yield batch


def load_snapshot(
    connection: Any,
    *,
    manifest_path: Path,
    rows_path: Path,
    route_path: Path,
    registry_path: Path,
) -> dict[str, Any]:
    verified = verify_snapshot(manifest_path, rows_path)
    manifest = _load_json(manifest_path)
    snapshot_id = str(manifest["snapshot_id"])
    cutover_unit = str(manifest["cutover_unit"])
    route = validate_sqlite_authority_route(
        cutover_unit=cutover_unit,
        route_path=route_path,
        registry_path=registry_path,
    )
    source_reconciliation = manifest["reconciliation"]

    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT snapshot_id
                  FROM migration.unit_snapshot
                 WHERE cutover_unit=%s AND lifecycle_state='reconciled'
                   AND snapshot_id<>%s
                 ORDER BY imported_at DESC LIMIT 1
                """,
                (cutover_unit, snapshot_id),
            )
            previous_row = cursor.fetchone()
            previous_snapshot_id = previous_row[0] if previous_row else None
            cursor.execute(
                """
                INSERT INTO migration.unit_snapshot(
                    snapshot_id, cutover_unit, source_identity_sha256,
                    application_commit_sha, registry_sha256, source_created_at,
                    source_watermark, target_watermark, reconciliation,
                    lifecycle_state, formal_business_data
                ) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,'staging',false)
                ON CONFLICT (snapshot_id) DO NOTHING
                """,
                (
                    snapshot_id,
                    cutover_unit,
                    manifest["source_identity_sha256"],
                    manifest["application_commit_sha"],
                    manifest["registry_sha256"],
                    manifest["source_created_at"],
                    json.dumps(manifest["source_identity"], ensure_ascii=False),
                    json.dumps({"status": "loading"}),
                    json.dumps(source_reconciliation),
                ),
            )
            cursor.execute(
                """
                SELECT cutover_unit, source_identity_sha256, application_commit_sha,
                       registry_sha256, formal_business_data
                  FROM migration.unit_snapshot WHERE snapshot_id=%s
                """,
                (snapshot_id,),
            )
            existing = cursor.fetchone()
            expected = (
                cutover_unit,
                manifest["source_identity_sha256"],
                manifest["application_commit_sha"],
                manifest["registry_sha256"],
                False,
            )
            if existing is None or tuple(existing) != expected:
                raise Stage4LoadError("target snapshot identity collision")
            loaded_count = 0
            for batch in _batches(_iter_rows(rows_path)):
                cursor.executemany(
                    """
                    INSERT INTO migration.source_row(
                        snapshot_id, cutover_unit, source_database, source_table,
                        source_ordinal, source_key, row_sha256, payload
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                    ON CONFLICT (snapshot_id, source_database, source_table, source_ordinal)
                    DO NOTHING
                    """,
                    [
                        (
                            snapshot_id,
                            cutover_unit,
                            row["source_database"],
                            row["source_table"],
                            int(row["source_ordinal"]),
                            row["source_key"],
                            row["row_sha256"],
                            json.dumps(row["payload"], ensure_ascii=False),
                        )
                        for row in batch
                    ],
                )
                loaded_count += len(batch)
            if loaded_count != int(source_reconciliation["source_row_count"]):
                raise Stage4LoadError("verified source row count changed before load")
            cursor.execute(
                """
                SELECT source_database, source_table, source_ordinal, source_key, row_sha256
                  FROM migration.source_row
                 WHERE snapshot_id=%s
                 ORDER BY source_database, source_table, source_ordinal
                """,
                (snapshot_id,),
            )
            target_digest = hashlib.sha256()
            target_count = 0
            for identity in cursor:
                target_digest.update(
                    json.dumps(
                        identity,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                )
                target_digest.update(b"\n")
                target_count += 1
            target_sha = target_digest.hexdigest()
            if int(target_count) != int(source_reconciliation["source_row_count"]):
                raise Stage4LoadError("target row count reconciliation failed")
            if target_sha != source_reconciliation["source_content_sha256"]:
                raise Stage4LoadError("target row identity reconciliation failed")
            target_watermark = {
                "row_count": int(target_count),
                "content_sha256": target_sha,
                "formal_business_data": False,
                "authoritative_backend": route["backend"],
            }
            reconciliation = {
                **source_reconciliation,
                "target_row_count": int(target_count),
                "target_content_sha256": target_sha,
                "status": "pass",
            }
            cursor.execute(
                """
                UPDATE migration.unit_snapshot
                   SET target_watermark=%s::jsonb,
                       reconciliation=%s::jsonb,
                       lifecycle_state='reconciled'
                 WHERE snapshot_id=%s
                """,
                (
                    json.dumps(target_watermark, ensure_ascii=False),
                    json.dumps(reconciliation, ensure_ascii=False),
                    snapshot_id,
                ),
            )
            delta = None
            if previous_snapshot_id:
                cursor.execute(
                    """
                    WITH previous AS (
                      SELECT source_database,source_table,source_key,row_sha256
                        FROM migration.source_row WHERE snapshot_id=%s
                    ), current_snapshot AS (
                      SELECT source_database,source_table,source_key,row_sha256
                        FROM migration.source_row WHERE snapshot_id=%s
                    )
                    SELECT
                      count(*) FILTER (WHERE p.source_key IS NULL),
                      count(*) FILTER (WHERE p.source_key IS NOT NULL AND p.row_sha256<>c.row_sha256),
                      (SELECT count(*) FROM previous p2
                        WHERE NOT EXISTS (
                          SELECT 1 FROM current_snapshot c2
                           WHERE c2.source_database=p2.source_database
                             AND c2.source_table=p2.source_table
                             AND c2.source_key=p2.source_key
                        ))
                      FROM current_snapshot c
                      LEFT JOIN previous p USING(source_database,source_table,source_key)
                    """,
                    (previous_snapshot_id, snapshot_id),
                )
                inserted, updated, deleted = (
                    int(value or 0) for value in cursor.fetchone()
                )
                delta_core = {
                    "base_snapshot_id": previous_snapshot_id,
                    "snapshot_id": snapshot_id,
                    "inserted": inserted,
                    "updated": updated,
                    "deleted": deleted,
                    "source_content_sha256": source_reconciliation[
                        "source_content_sha256"
                    ],
                }
                delta_id = hashlib.sha256(
                    json.dumps(
                        delta_core,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
                cursor.execute(
                    """
                    INSERT INTO migration.unit_delta_ledger(
                      delta_id,cutover_unit,base_snapshot_id,source_identity_sha256,
                      captured_at,source_watermark,row_count,content_sha256,
                      applied_at,status,expires_after_cutover
                    ) VALUES (
                      %s,%s,%s,%s,%s,%s::jsonb,%s,%s,
                      clock_timestamp(),'reconciled',true
                    ) ON CONFLICT (delta_id) DO NOTHING
                    """,
                    (
                        delta_id,
                        cutover_unit,
                        previous_snapshot_id,
                        manifest["source_identity_sha256"],
                        manifest["source_created_at"],
                        json.dumps(manifest["source_identity"], ensure_ascii=False),
                        inserted + updated + deleted,
                        source_reconciliation["source_content_sha256"],
                    ),
                )
                cursor.execute(
                    """
                    UPDATE migration.unit_snapshot SET lifecycle_state='superseded'
                     WHERE snapshot_id=%s AND lifecycle_state='reconciled'
                    """,
                    (previous_snapshot_id,),
                )
                delta = {**delta_core, "delta_id": delta_id}
    return {
        "ok": True,
        "snapshot_id": snapshot_id,
        "cutover_unit": cutover_unit,
        "source_row_count": loaded_count,
        "target_row_count": target_count,
        "source_content_sha256": source_reconciliation["source_content_sha256"],
        "target_content_sha256": source_reconciliation["source_content_sha256"],
        "authority_state": route["authority_state"],
        "authoritative_backend": route["backend"],
        "formal_business_data": False,
        "temporary_catchup": delta,
    }


def _connection_from_runtime(path: Path, role_name: str) -> Any:
    runtime = _load_json(path)
    if runtime.get("schema_version") != "honghu.postgresql_production_runtime.v1":
        raise Stage4LoadError("unsupported production runtime evidence schema")
    if runtime.get("environment_id") != "production":
        raise Stage4LoadError("runtime evidence is not production-scoped")
    roles = runtime.get("roles") or {}
    role = roles.get(role_name)
    if not isinstance(role, dict):
        raise Stage4LoadError(f"runtime role is missing: {role_name}")
    service = str(role.get("credential_service") or "")
    account = str(role.get("credential_account") or "")
    username = str(role.get("user") or "")
    if not service or not account or not username:
        raise Stage4LoadError("runtime role credential identity is incomplete")
    import keyring
    import psycopg

    password = keyring.get_password(service, account)
    if not password:
        raise Stage4LoadError("runtime role credential is unavailable")
    return psycopg.connect(
        host=runtime["host"],
        port=int(runtime["port"]),
        dbname=runtime["dbname"],
        user=username,
        password=password,
        sslmode=runtime.get("sslmode") or "verify-full",
        sslrootcert=runtime.get("sslrootcert"),
        connect_timeout=5,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument("--route", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--role", default="migration")
    args = parser.parse_args(argv)
    connection = _connection_from_runtime(args.runtime, args.role)
    try:
        result = load_snapshot(
            connection,
            manifest_path=args.manifest,
            rows_path=args.rows,
            route_path=args.route,
            registry_path=args.registry,
        )
    finally:
        connection.close()
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
