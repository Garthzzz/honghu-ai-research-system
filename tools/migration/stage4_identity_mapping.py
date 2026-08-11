from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ENTITY_TABLES = ("company", "industry", "theme")


class IdentityMappingError(RuntimeError):
    pass


class IdentityMappingResolver:
    def __init__(self, manifest: dict[str, Any]):
        core = {
            key: value
            for key, value in manifest.items()
            if key not in {"generated_at", "manifest_sha256"}
        }
        if manifest.get("schema_version") != "honghu.user_content_identity_mapping.v1":
            raise IdentityMappingError("unsupported identity mapping schema")
        if manifest.get("manifest_sha256") != _sha(core):
            raise IdentityMappingError("identity mapping manifest hash mismatch")
        self.manifest_sha256 = str(manifest["manifest_sha256"])
        self._by_legacy: dict[tuple[str, str], str] = {}
        for record in manifest.get("mappings") or []:
            key = (str(record["entity_type"]), str(record["legacy_id"]))
            stable_key = str(record["stable_key"])
            if key in self._by_legacy and self._by_legacy[key] != stable_key:
                raise IdentityMappingError(f"legacy identity maps to multiple stable keys: {key}")
            self._by_legacy[key] = stable_key

    @classmethod
    def from_path(cls, path: str | Path) -> "IdentityMappingResolver":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def resolve(self, entity_type: str, legacy_id: str | int) -> str:
        key = (str(entity_type), str(legacy_id))
        try:
            return self._by_legacy[key]
        except KeyError as exc:
            raise IdentityMappingError(
                f"unmapped user-content dependency: {key[0]}:{key[1]}"
            ) from exc


def _canonical_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    return re.sub(r"\s+", " ", text)


def _sha(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _table_rows(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    cursor = conn.execute(f'SELECT * FROM "{table}" ORDER BY 1')
    names = [item[0] for item in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _table_schema(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    return [
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


def _industry_paths(rows: list[dict[str, Any]]) -> dict[str, str]:
    by_id = {str(row["id"]): row for row in rows}
    paths: dict[str, str] = {}

    def resolve(legacy_id: str, stack: tuple[str, ...] = ()) -> str:
        if legacy_id in paths:
            return paths[legacy_id]
        if legacy_id in stack:
            raise IdentityMappingError(f"industry parent cycle: {' -> '.join(stack + (legacy_id,))}")
        row = by_id.get(legacy_id)
        if row is None:
            raise IdentityMappingError(f"industry parent missing: {legacy_id}")
        name = _canonical_text(row.get("name"))
        if not name:
            raise IdentityMappingError(f"industry name empty: {legacy_id}")
        parent = row.get("parent_id")
        parent_path = ""
        if parent is not None:
            parent_path = resolve(str(parent), stack + (legacy_id,)) + "/"
        path = f"{parent_path}{name}"
        paths[legacy_id] = path
        return path

    for identity in by_id:
        resolve(identity)
    return paths


def _mapping_record(
    *,
    entity_type: str,
    source_table: str,
    legacy_id: str,
    stable_key: str,
    basis: str,
    row: dict[str, Any],
    source_watermark: dict[str, Any],
) -> dict[str, Any]:
    return {
        "entity_type": entity_type,
        "source_database": "research.db",
        "source_table": source_table,
        "legacy_id": legacy_id,
        "stable_key": stable_key,
        "basis": basis,
        "source_watermark": source_watermark,
        "source_evidence_identity": _sha(
            {
                "entity_type": entity_type,
                "source_table": source_table,
                "legacy_id": legacy_id,
                "stable_key": stable_key,
                "row": row,
            }
        ),
    }


def build_identity_mapping(database: str | Path) -> dict[str, Any]:
    database_path = Path(database).resolve()
    if not database_path.is_file():
        raise FileNotFoundError(database_path)
    conn = sqlite3.connect(
        f"file:{database_path.as_posix()}?mode=ro", uri=True, timeout=10
    )
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=ON")
        present = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        missing = sorted(set(ENTITY_TABLES) - present)
        if missing:
            raise IdentityMappingError(f"missing identity tables: {', '.join(missing)}")
        rows = {table: _table_rows(conn, table) for table in ENTITY_TABLES}
        schemas = {table: _table_schema(conn, table) for table in ENTITY_TABLES}
    finally:
        conn.close()

    table_watermarks: dict[str, dict[str, Any]] = {}
    for table in ENTITY_TABLES:
        table_watermarks[table] = {
            "row_count": len(rows[table]),
            "schema_sha256": _sha(schemas[table]),
            "content_sha256": _sha(rows[table]),
        }

    mappings: list[dict[str, Any]] = []
    legacy_seen: dict[tuple[str, str], str] = {}
    stable_aliases: dict[tuple[str, str], list[str]] = {}

    def add(record: dict[str, Any]) -> None:
        legacy_key = (record["entity_type"], record["legacy_id"])
        previous = legacy_seen.get(legacy_key)
        if previous is not None and previous != record["stable_key"]:
            raise IdentityMappingError(
                f"legacy identity maps to multiple stable keys for "
                f"{legacy_key[0]}:{legacy_key[1]}: {previous}, {record['stable_key']}"
            )
        legacy_seen[legacy_key] = record["stable_key"]
        stable_aliases.setdefault(
            (record["entity_type"], record["stable_key"]), []
        ).append(record["legacy_id"])
        mappings.append(record)

    for row in rows["company"]:
        legacy_id = str(row["id"])
        ticker = _canonical_text(row.get("ticker")).upper()
        market = _canonical_text(row.get("market"))
        name = _canonical_text(row.get("name"))
        if ticker:
            stable_key = f"company:ticker:{ticker}"
            basis = "normalized_ticker"
        elif name:
            stable_key = f"company:name-market:{_sha([name, market])}"
            basis = "normalized_name_and_market_fallback"
        else:
            raise IdentityMappingError(f"company identity empty: {legacy_id}")
        add(
            _mapping_record(
                entity_type="company",
                source_table="company",
                legacy_id=legacy_id,
                stable_key=stable_key,
                basis=basis,
                row=row,
                source_watermark=table_watermarks["company"],
            )
        )

    industry_paths = _industry_paths(rows["industry"])
    for row in rows["industry"]:
        legacy_id = str(row["id"])
        path = industry_paths[legacy_id]
        for entity_type in ("industry", "industry_q"):
            add(
                _mapping_record(
                    entity_type=entity_type,
                    source_table="industry",
                    legacy_id=legacy_id,
                    stable_key=f"{entity_type}:path:{path}",
                    basis="normalized_full_industry_path",
                    row=row,
                    source_watermark=table_watermarks["industry"],
                )
            )

    for row in rows["theme"]:
        legacy_id = str(row["id"])
        normalized_id = _canonical_text(legacy_id)
        if not normalized_id:
            raise IdentityMappingError("theme id is empty")
        add(
            _mapping_record(
                entity_type="theme",
                source_table="theme",
                legacy_id=legacy_id,
                stable_key=f"theme:id:{normalized_id}",
                basis="normalized_existing_text_primary_key",
                row=row,
                source_watermark=table_watermarks["theme"],
            )
        )

    mappings.sort(key=lambda item: (item["entity_type"], item["legacy_id"]))
    alias_groups = [
        {
            "entity_type": entity_type,
            "stable_key": stable_key,
            "legacy_ids": sorted(legacy_ids),
        }
        for (entity_type, stable_key), legacy_ids in sorted(stable_aliases.items())
        if len(legacy_ids) > 1
    ]
    manifest_core = {
        "schema_version": "honghu.user_content_identity_mapping.v1",
        "source_database": str(database_path),
        "source_database_sha256": _file_sha(database_path),
        "source_tables": table_watermarks,
        "mappings": mappings,
        "collision_count": 0,
        "alias_group_count": len(alias_groups),
        "alias_groups": alias_groups,
    }
    return {
        **manifest_core,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest_sha256": _sha(manifest_core),
    }


def write_identity_mapping(database: str | Path, output: str | Path) -> dict[str, Any]:
    manifest = build_identity_mapping(database)
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a read-only Stage 4 identity mapping")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = write_identity_mapping(args.database, args.output)
    print(
        json.dumps(
            {
                "manifest_sha256": result["manifest_sha256"],
                "mapping_count": len(result["mappings"]),
                "source_database_sha256": result["source_database_sha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
