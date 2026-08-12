from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator


SCHEMA_VERSION = "honghu.stage4_unit_snapshot.v1"
PRODUCTION_UNITS = (
    "user_content_notes",
    "shared_identity",
    "financial_data",
    "research_publication",
    "dynamic_intelligence",
    "operations_governance",
    "investment_hypotheses",
    "opportunity_lens",
    "sentiment_analytics",
)
DATABASE_FILES = ("research.db", "financial.db", "opportunity_lens.db", "sentiment.db")


class UnitSnapshotError(RuntimeError):
    pass


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _encode(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"$binary_base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, float) and not math.isfinite(value):
        return {"$nonfinite_float": repr(value)}
    return value


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise UnitSnapshotError(f"JSON object required: {path}")
    return payload


def _unit_objects(registry: dict[str, Any], unit: str) -> dict[str, list[str]]:
    units = registry.get("units") or {}
    record = units.get(unit)
    if not isinstance(record, dict):
        raise UnitSnapshotError(f"unknown cutover unit: {unit}")
    objects: dict[str, list[str]] = {}
    for item in record.get("objects") or []:
        database = str(item.get("database") or "")
        table = str(item.get("object") or item.get("table") or "")
        object_type = str(item.get("object_type") or "table")
        if object_type != "table" or not database or not table:
            continue
        objects.setdefault(database, []).append(table)
    if not objects:
        raise UnitSnapshotError(f"cutover unit has no owned tables: {unit}")
    return {database: sorted(set(tables)) for database, tables in sorted(objects.items())}


def _table_schema(conn: sqlite3.Connection, table: str) -> dict[str, Any]:
    columns = [
        {
            "cid": row[0],
            "name": row[1],
            "type": row[2],
            "notnull": row[3],
            "default": row[4],
            "pk": row[5],
        }
        for row in conn.execute(f'PRAGMA table_info("{table}")')
    ]
    if not columns:
        raise UnitSnapshotError(f"missing source table: {table}")
    indexes = []
    for row in conn.execute(f'PRAGMA index_list("{table}")'):
        index_name = row[1]
        indexes.append(
            {
                "name": index_name,
                "unique": bool(row[2]),
                "columns": [
                    item[2]
                    for item in conn.execute(f'PRAGMA index_info("{index_name}")')
                ],
            }
        )
    foreign_keys = [list(row) for row in conn.execute(f'PRAGMA foreign_key_list("{table}")')]
    return {"columns": columns, "indexes": indexes, "foreign_keys": foreign_keys}


def _row_key(columns: list[dict[str, Any]], values: dict[str, Any], ordinal: int) -> str:
    pk = [item for item in columns if int(item.get("pk") or 0) > 0]
    pk.sort(key=lambda item: int(item["pk"]))
    if pk:
        return _sha([[item["name"], _encode(values.get(item["name"]))] for item in pk])
    return f"ordinal:{ordinal:020d}:{_sha(values)}"


def _iter_rows(
    conn: sqlite3.Connection, table: str, columns: list[dict[str, Any]]
) -> Iterator[tuple[int, str, str, dict[str, Any]]]:
    names = [item["name"] for item in columns]
    pk = [item for item in columns if int(item.get("pk") or 0) > 0]
    pk.sort(key=lambda item: int(item["pk"]))
    order = [item["name"] for item in pk] or names
    query = f'SELECT * FROM "{table}"'
    if order:
        query += " ORDER BY " + ",".join(f'"{name}"' for name in order)
    cursor = conn.execute(query)
    for ordinal, row in enumerate(cursor, start=1):
        payload = {name: _encode(value) for name, value in zip(names, row)}
        yield ordinal, _row_key(columns, payload, ordinal), _sha(payload), payload


def _backup_database(source: Path, target: Path) -> dict[str, Any]:
    if not source.is_file():
        raise FileNotFoundError(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    source_uri = f"file:{source.as_posix()}?mode=ro"
    source_conn = sqlite3.connect(source_uri, uri=True, timeout=30)
    source_conn.execute("PRAGMA query_only=ON")
    target_conn = sqlite3.connect(target)
    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()
    check = sqlite3.connect(f"file:{target.as_posix()}?mode=ro", uri=True)
    try:
        integrity = str(check.execute("PRAGMA integrity_check").fetchone()[0])
        quick = str(check.execute("PRAGMA quick_check").fetchone()[0])
        user_version = int(check.execute("PRAGMA user_version").fetchone()[0])
        schema_version = int(check.execute("PRAGMA schema_version").fetchone()[0])
    finally:
        check.close()
    if integrity != "ok" or quick != "ok":
        raise UnitSnapshotError(f"SQLite online backup failed integrity check: {source.name}")
    return {
        "database": source.name,
        "snapshot_sha256": _file_sha(target),
        "snapshot_size": target.stat().st_size,
        "integrity_check": integrity,
        "quick_check": quick,
        "user_version": user_version,
        "schema_version": schema_version,
    }


def _snapshot_table(
    database: str,
    path: Path,
    table: str,
    row_sink: Callable[[dict[str, Any]], None],
    unit_digest: Any,
) -> dict[str, Any]:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=ON")
    try:
        present = conn.execute(
            "SELECT type FROM sqlite_master WHERE name=?", (table,)
        ).fetchone()
        if present is None or present[0] != "table":
            raise UnitSnapshotError(f"owned source table missing: {database}.{table}")
        schema = _table_schema(conn, table)
        digest = hashlib.sha256()
        row_count = 0
        for ordinal, key, row_sha, payload in _iter_rows(conn, table, schema["columns"]):
            record = {
                "source_database": database,
                "source_table": table,
                "source_ordinal": ordinal,
                "source_key": key,
                "row_sha256": row_sha,
                "payload": payload,
            }
            digest.update(_json_bytes(record))
            digest.update(b"\n")
            identity = [database, table, ordinal, key, row_sha]
            unit_digest.update(_json_bytes(identity))
            unit_digest.update(b"\n")
            row_sink(record)
            row_count += 1
        updated_candidates = [
            item["name"]
            for item in schema["columns"]
            if item["name"].casefold()
            in {"updated_at", "fetched_at", "created_at", "as_of", "publish_date", "ts"}
        ]
        watermark: dict[str, Any] = {"row_count": row_count}
        for name in updated_candidates:
            value = conn.execute(f'SELECT max("{name}") FROM "{table}"').fetchone()[0]
            watermark[f"max_{name}"] = _encode(value)
        return {
            "source_database": database,
            "source_table": table,
            "schema": schema,
            "schema_sha256": _sha(schema),
            "row_count": row_count,
            "content_sha256": digest.hexdigest(),
            "watermark": watermark,
            "source_key_contract": (
                "primary_key" if any(int(item.get("pk") or 0) > 0 for item in schema["columns"])
                else "ordered_snapshot_ordinal_no_incremental_delete_support"
            ),
        }
    finally:
        conn.close()


def build_unit_snapshot(
    *,
    unit: str,
    source_data_root: Path,
    registry_path: Path,
    application_commit_sha: str,
    output_dir: Path,
    include_rows: bool = True,
) -> dict[str, Any]:
    if unit not in PRODUCTION_UNITS:
        raise UnitSnapshotError(f"unit is not a production cutover unit: {unit}")
    if len(application_commit_sha) != 40 or any(c not in "0123456789abcdef" for c in application_commit_sha):
        raise UnitSnapshotError("application commit must be a lowercase full Git SHA")
    registry = _read_json(registry_path)
    if not bool((registry.get("validation") or {}).get("passed")):
        raise UnitSnapshotError("cutover registry validation is not green")
    registry_sha = str(registry.get("registry_sha256") or "")
    if len(registry_sha) != 64:
        raise UnitSnapshotError("cutover registry identity is missing")
    objects = _unit_objects(registry, unit)
    output_dir.mkdir(parents=True, exist_ok=True)
    source_created_at = _utc_now()
    with tempfile.TemporaryDirectory(prefix=f"honghu-{unit}-snapshot-") as temp_name:
        temp_root = Path(temp_name)
        database_evidence: dict[str, Any] = {}
        table_evidence: list[dict[str, Any]] = []
        row_count = 0
        unit_digest = hashlib.sha256()
        temp_rows_path = temp_root / "rows.jsonl"
        with temp_rows_path.open("w", encoding="utf-8", newline="\n") as row_handle:
            def sink(record: dict[str, Any]) -> None:
                nonlocal row_count
                row_count += 1
                if include_rows:
                    row_handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

            for database, tables in objects.items():
                if database not in DATABASE_FILES:
                    raise UnitSnapshotError(f"unapproved source database: {database}")
                snapshot_path = temp_root / database
                database_evidence[database] = _backup_database(
                    source_data_root / database, snapshot_path
                )
                for table in tables:
                    table_record = _snapshot_table(
                        database, snapshot_path, table, sink, unit_digest
                    )
                    table_evidence.append(table_record)
        source_identity_core = {
            "cutover_unit": unit,
            "registry_sha256": registry_sha,
            "objects": objects,
            "databases": database_evidence,
            "tables": table_evidence,
        }
        source_identity = _sha(source_identity_core)
        snapshot_id = f"{unit}:{source_identity[:24]}"
        result_core = {
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": snapshot_id,
            "cutover_unit": unit,
            "application_commit_sha": application_commit_sha,
            "registry_sha256": registry_sha,
            "source_created_at": source_created_at,
            "source_identity_sha256": source_identity,
            "source_identity": source_identity_core,
            "formal_business_data": False,
            "authority_contract": {
                "state": "S0_or_S1",
                "authoritative_backend": "sqlite_transition",
                "sqlite_writer_fenced": False,
                "postgresql_formal_business_writes": False,
                "silent_fallback": False,
                "dual_or_shadow_write": False,
            },
            "reconciliation": {
                "source_row_count": row_count,
                "source_content_sha256": unit_digest.hexdigest(),
                "content_order": "source_database_source_table_source_ordinal",
                "target_status": "not_loaded",
            },
        }
        result = {**result_core, "manifest_sha256": _sha(result_core)}
        manifest_path = output_dir / f"{unit}.snapshot.json"
        manifest_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if include_rows:
            rows_path = output_dir / f"{unit}.rows.jsonl"
            shutil.move(str(temp_rows_path), str(rows_path))
            result["rows_artifact"] = {
                "path": str(rows_path),
                "sha256": _file_sha(rows_path),
                "row_count": row_count,
            }
        return result


def verify_snapshot(manifest_path: Path, rows_path: Path | None = None) -> dict[str, Any]:
    manifest = _read_json(manifest_path)
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise UnitSnapshotError("unsupported unit snapshot schema")
    core = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if manifest.get("manifest_sha256") != _sha(core):
        raise UnitSnapshotError("unit snapshot manifest hash mismatch")
    authority = manifest.get("authority_contract") or {}
    expected = {
        "authoritative_backend": "sqlite_transition",
        "sqlite_writer_fenced": False,
        "postgresql_formal_business_writes": False,
        "silent_fallback": False,
        "dual_or_shadow_write": False,
    }
    for key, value in expected.items():
        if authority.get(key) != value:
            raise UnitSnapshotError(f"unsafe authority contract: {key}")
    row_result = None
    if rows_path is not None:
        if not rows_path.is_file():
            raise FileNotFoundError(rows_path)
        count = 0
        digest = hashlib.sha256()
        with rows_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                if row.get("row_sha256") != _sha(row.get("payload")):
                    raise UnitSnapshotError("source row payload hash mismatch")
                identity = [
                    row["source_database"],
                    row["source_table"],
                    int(row["source_ordinal"]),
                    row["source_key"],
                    row["row_sha256"],
                ]
                digest.update(_json_bytes(identity))
                digest.update(b"\n")
                count += 1
        reconciliation = manifest.get("reconciliation") or {}
        if count != int(reconciliation.get("source_row_count", -1)):
            raise UnitSnapshotError("source row count mismatch")
        if digest.hexdigest() != reconciliation.get("source_content_sha256"):
            raise UnitSnapshotError("source row identity set mismatch")
        row_result = {"row_count": count, "sha256": _file_sha(rows_path)}
    return {
        "ok": True,
        "cutover_unit": manifest["cutover_unit"],
        "snapshot_id": manifest["snapshot_id"],
        "manifest_sha256": manifest["manifest_sha256"],
        "rows": row_result,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--unit", choices=PRODUCTION_UNITS, required=True)
    build.add_argument("--source-data-root", type=Path, required=True)
    build.add_argument("--registry", type=Path, required=True)
    build.add_argument("--application-commit-sha", required=True)
    build.add_argument("--output-dir", type=Path, required=True)
    build.add_argument("--manifest-only", action="store_true")
    verify = subparsers.add_parser("verify")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--rows", type=Path)
    args = parser.parse_args(argv)
    if args.command == "build":
        result = build_unit_snapshot(
            unit=args.unit,
            source_data_root=args.source_data_root,
            registry_path=args.registry,
            application_commit_sha=args.application_commit_sha,
            output_dir=args.output_dir,
            include_rows=not args.manifest_only,
        )
    else:
        result = verify_snapshot(args.manifest, args.rows)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
