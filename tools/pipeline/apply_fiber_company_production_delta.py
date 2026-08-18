from __future__ import annotations

"""Apply one audited optical-fiber delta to one PostgreSQL authority unit."""

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable

from tools.data_platform.domain_data import connect_domain_database
from tools.runtime_paths import resolve_runtime_layout


SCHEMA_VERSION = "fiber.company_production_delta.v1"
UNITS = ("research_publication", "shared_identity", "financial_data")


def _load(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unexpected optical-fiber delta schema")
    if payload.get("industry_id") != 50 or sorted(payload.get("company_ids") or []) != [59, 199, 200, 201, 202, 203, 204, 704]:
        raise ValueError("unexpected optical-fiber delta scope")
    payload["_sha256"] = hashlib.sha256(raw).hexdigest()
    return payload


def _insert(conn: Any, table: str, row: dict[str, Any]) -> None:
    columns = list(row)
    conn.execute(
        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
        tuple(row[column] for column in columns),
    )


def _upsert(conn: Any, table: str, row: dict[str, Any], conflict: Iterable[str]) -> None:
    columns = list(row)
    keys = tuple(conflict)
    updates = [column for column in columns if column not in keys]
    where = " AND ".join(f"{column} IS ?" for column in keys)
    key_values = tuple(row[column] for column in keys)
    existing = conn.execute(
        f"SELECT 1 FROM {table} WHERE {where} LIMIT 1", key_values
    ).fetchone()
    if existing is None:
        _insert(conn, table, row)
        return
    conn.execute(
        f"UPDATE {table} SET "
        + ",".join(f"{column}=?" for column in updates)
        + f" WHERE {where}",
        tuple(row[column] for column in updates) + key_values,
    )


def _next_id(conn: Any, table: str) -> int:
    return int(conn.execute(f"SELECT COALESCE(MAX(id),0)+1 FROM {table}").fetchone()[0])


def _open(unit: str) -> Any:
    layout = resolve_runtime_layout()
    database = "financial.db" if unit == "financial_data" else "research.db"
    return connect_domain_database(
        unit,
        layout.data_root / database,
        readonly=False,
        operation_scope=f"fiber_company_completion_{unit}",
        operation_id=os.environ.get("HONGHU_OPERATION_ID"),
    )


def _write_mapping(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def apply_research_publication(delta: dict[str, Any], mapping_path: Path) -> dict[str, Any]:
    section = delta["research"]
    mapping: dict[str, int] = {}
    conn = _open("research_publication")
    try:
        for item in section["sources"]:
            row = dict(item["row"])
            existing = conn.execute(
                "SELECT id FROM source WHERE title=? AND publisher IS ? AND publish_date IS ? ORDER BY id LIMIT 1",
                (row["title"], row.get("publisher"), row.get("publish_date")),
            ).fetchone()
            source_id = int(existing[0]) if existing else _next_id(conn, "source")
            row["id"] = source_id
            _upsert(conn, "source", row, ("id",))
            mapping[item["source_key"]] = source_id
        for item in section["source_entities"]:
            row = dict(item["row"])
            row["source_id"] = mapping[item["source_key"]]
            _upsert(conn, "source_entity", row, ("source_id", "entity_type", "entity_id"))
        conn.commit()
        _write_mapping(mapping_path, {
            "schema_version": "fiber.company_source_mapping.v1",
            "delta_sha256": delta["_sha256"],
            "sources": mapping,
        })
        return {"sources": len(mapping), "source_entities": len(section["source_entities"])}
    finally:
        conn.close()


def _load_mapping(path: Path, delta_sha256: str) -> dict[str, int]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != "fiber.company_source_mapping.v1" or value.get("delta_sha256") != delta_sha256:
        raise ValueError("source mapping is not bound to this delta")
    return {str(key): int(item) for key, item in value["sources"].items()}


def apply_shared_identity(delta: dict[str, Any], mapping_path: Path) -> dict[str, Any]:
    section = delta["research"]
    sources = _load_mapping(mapping_path, delta["_sha256"])
    conn = _open("shared_identity")
    try:
        industry = conn.execute("SELECT name FROM industry WHERE id=50").fetchone()
        if industry is None or str(industry[0]) != "光纤":
            raise RuntimeError("production industry 50 is not 光纤")
        for item in section["company_updates"]:
            row = dict(item["row"])
            identity = conn.execute("SELECT name FROM company WHERE id=?", (row["id"],)).fetchone()
            if identity is None or str(identity[0]) != row["name"]:
                raise RuntimeError(f"company identity mismatch: {row['id']}")
            conn.execute(
                "UPDATE company SET ticker=?,market=?,listing_status=?,brief_intro=?,brief_intro_src=? WHERE id=?",
                (row.get("ticker"), row.get("market"), row.get("listing_status"), row.get("brief_intro"), row.get("brief_intro_src"), row["id"]),
            )
        for row in section["company_industry"]:
            _upsert(conn, "company_industry", dict(row), ("company_id", "industry_id"))
        for item in section["company_profiles"]:
            row = dict(item["row"])
            row["source_ids"] = json.dumps(
                [sources[key] for key in item["source_keys"]], ensure_ascii=False, separators=(",", ":")
            )
            brief_key = item.get("brief_intro_source_key")
            row["brief_intro_src"] = sources.get(brief_key) if brief_key else None
            existing = conn.execute(
                "SELECT id FROM company_profile WHERE company_id=? AND industry_id=? ORDER BY id LIMIT 1",
                (row["company_id"], row["industry_id"]),
            ).fetchone()
            row["id"] = int(existing[0]) if existing else _next_id(conn, "company_profile")
            conn.execute(
                "DELETE FROM company_profile WHERE company_id=? AND industry_id=?",
                (row["company_id"], row["industry_id"]),
            )
            _insert(conn, "company_profile", row)
        conn.commit()
        return {
            "company_updates": len(section["company_updates"]),
            "company_industry": len(section["company_industry"]),
            "company_profiles": len(section["company_profiles"]),
        }
    finally:
        conn.close()


def _resolve_or_create(
    conn: Any,
    *,
    table: str,
    row: dict[str, Any],
    lookup_sql: str,
    lookup_params: tuple[Any, ...],
) -> int:
    existing = conn.execute(lookup_sql, lookup_params).fetchone()
    object_id = int(existing[0]) if existing else _next_id(conn, table)
    row["id"] = object_id
    _upsert(conn, table, row, ("id",))
    return object_id


def apply_financial_data(delta: dict[str, Any]) -> dict[str, Any]:
    section = delta["financial"]
    conn = _open("financial_data")
    security_ids: dict[str, int] = {}
    source_ids: dict[str, int] = {}
    model_ids: dict[str, int] = {}
    try:
        for item in section["securities"]:
            row = dict(item["row"])
            security_ids[item["security_key"]] = _resolve_or_create(
                conn,
                table="financial_security",
                row=row,
                lookup_sql="SELECT id FROM financial_security WHERE research_company_id=?",
                lookup_params=(row["research_company_id"],),
            )
        for item in section["sources"]:
            row = dict(item["row"])
            source_ids[item["source_key"]] = _resolve_or_create(
                conn,
                table="financial_source_snapshot",
                row=row,
                lookup_sql="SELECT id FROM financial_source_snapshot WHERE provider=? AND source_ref=? AND as_of_date IS ? AND content_hash IS ?",
                lookup_params=(row["provider"], row["source_ref"], row.get("as_of_date"), row.get("content_hash")),
            )
        for item in section["model_runs"]:
            row = dict(item["row"])
            row["security_id"] = security_ids[item["security_key"]]
            model_ids[item["model_run_key"]] = _resolve_or_create(
                conn,
                table="financial_model_run",
                row=row,
                lookup_sql="SELECT id FROM financial_model_run WHERE run_key=?",
                lookup_params=(row["run_key"],),
            )
        child_contracts = (
            ("model_inputs", "financial_model_input", ("model_run_id", "input_name", "period_or_as_of_date", "source_ref")),
            ("model_outputs", "financial_model_output", ("model_run_id", "output_name", "period_or_as_of_date")),
            ("reconciliations", "financial_reconciliation", ("model_run_id", "benchmark_type", "benchmark_source_ref", "metric_name", "period")),
        )
        for section_name, table, conflict in child_contracts:
            for item in section[section_name]:
                row = dict(item["row"])
                row["model_run_id"] = model_ids[item["model_run_key"]]
                _upsert(conn, table, row, conflict)
        for item in section["observations"]:
            row = dict(item["row"])
            row["security_id"] = security_ids[item["security_key"]]
            source_key = item.get("source_key")
            model_key = item.get("model_run_key")
            row["source_snapshot_id"] = source_ids.get(source_key) if source_key else None
            row["model_run_id"] = model_ids.get(model_key) if model_key else None
            _upsert(conn, "financial_observation", row, ("observation_key",))
        conn.commit()
        return {
            "securities": len(security_ids),
            "sources": len(source_ids),
            "model_runs": len(model_ids),
            "model_inputs": len(section["model_inputs"]),
            "model_outputs": len(section["model_outputs"]),
            "reconciliations": len(section["reconciliations"]),
            "observations": len(section["observations"]),
        }
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", required=True, choices=UNITS)
    parser.add_argument("--delta", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    args = parser.parse_args(argv)
    delta = _load(args.delta.resolve())
    if args.unit == "research_publication":
        result = apply_research_publication(delta, args.mapping.resolve())
    elif args.unit == "shared_identity":
        result = apply_shared_identity(delta, args.mapping.resolve())
    else:
        result = apply_financial_data(delta)
    print(json.dumps({
        "ok": True,
        "unit": args.unit,
        "delta_sha256": delta["_sha256"],
        "result": result,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
