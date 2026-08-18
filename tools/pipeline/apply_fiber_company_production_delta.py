from __future__ import annotations

"""Apply one audited optical-fiber delta to one PostgreSQL authority unit."""

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable

from tools.data_platform.domain_data import connect_domain_database
from tools.data_platform.postgres_runtime import (
    build_catalog_connection_factory,
    load_postgres_runtime_catalog,
)
from tools.data_platform.routing import load_environment_authority_matrix
from tools.data_platform.run_domain_operation import trusted_os_principal
from tools.data_platform.shared_identity import (
    PostgresSharedIdentityRepository,
    company_security_stable_key,
)
from tools.runtime_paths import resolve_runtime_layout


SCHEMA_VERSION = "fiber.company_production_delta.v1"
UNITS = ("research_publication", "shared_identity", "financial_data")
LEGACY_COMPANY_STABLE_KEYS = {
    204: "company:name-market:1b1cc9f41f2ed5d4c102565538980a1fc5b66caec6fc9f722f0023eb0b00b7b4",
}
PROFILE_JSON_SOURCE_FIELDS = (
    "revenue_series",
    "net_income_series",
    "recent_events",
    "risks",
)


def _repair_legacy_utf8(value: Any) -> str:
    text = str(value or "")
    try:
        repaired = text.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    return repaired


def _canonical_listing_status(ticker: str, market: str, display_status: str) -> str:
    if display_status == "已退市":
        return "delisted"
    code = str(ticker or "").strip().upper()
    if market == "A股":
        return "a_share"
    if market == "美股":
        return "us"
    if code.endswith(".T"):
        return "tse"
    return "other_listed"


def _company_identity_requires_completion(
    identity: Iterable[Any], desired: tuple[Any, ...]
) -> bool:
    return tuple(identity) != desired


def _remap_source_references(value: Any, source_ids: dict[int, int]) -> Any:
    if isinstance(value, list):
        return [_remap_source_references(item, source_ids) for item in value]
    if not isinstance(value, dict):
        return value
    remapped: dict[str, Any] = {}
    for key, item in value.items():
        if key == "source_id" and item is not None:
            remapped[key] = source_ids[int(item)]
        elif key == "source_ids" and isinstance(item, list):
            remapped[key] = [source_ids[int(source_id)] for source_id in item]
        else:
            remapped[key] = _remap_source_references(item, source_ids)
    return remapped


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


def _open_readonly(unit: str) -> Any:
    layout = resolve_runtime_layout()
    database = "financial.db" if unit == "financial_data" else "research.db"
    return connect_domain_database(
        unit,
        layout.data_root / database,
        readonly=True,
    )


def _shared_identity_repository() -> tuple[PostgresSharedIdentityRepository, Any]:
    matrix = load_environment_authority_matrix()
    if matrix is None:
        raise RuntimeError("formal shared identity authority matrix is required")
    route = matrix.route_for(
        "shared_identity",
        writer_operation="apply_company_profile_batch",
        transaction_boundary="one audited optical-fiber company profile batch",
    )
    catalog_path = os.environ.get("HONGHU_POSTGRES_RUNTIME_CONFIG")
    if not catalog_path:
        raise RuntimeError("PostgreSQL runtime catalog is required")
    catalog = load_postgres_runtime_catalog(catalog_path)
    read_factory = build_catalog_connection_factory(catalog, role="reader")
    write_factory = build_catalog_connection_factory(
        catalog, role="writer_shared_identity"
    )
    repository = PostgresSharedIdentityRepository(read_factory, write_factory, route)
    return repository, read_factory


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


def _load_mapping(path: Path, delta_sha256: str) -> tuple[dict[str, int], str]:
    raw = path.read_bytes()
    mapping_sha256 = hashlib.sha256(raw).hexdigest()
    value = json.loads(raw.decode("utf-8"))
    if value.get("schema_version") != "fiber.company_source_mapping.v1" or value.get("delta_sha256") != delta_sha256:
        raise ValueError("source mapping is not bound to this delta")
    return ({str(key): int(item) for key, item in value["sources"].items()}, mapping_sha256)


def apply_shared_identity(delta: dict[str, Any], mapping_path: Path) -> dict[str, Any]:
    section = delta["research"]
    sources, mapping_sha256 = _load_mapping(mapping_path, delta["_sha256"])
    source_items = {item["source_key"]: item for item in section["sources"]}
    if set(sources) != set(source_items):
        raise RuntimeError("research source mapping keys do not exactly match the delta")
    if any(item.get("legacy_source_id") is None for item in source_items.values()):
        raise RuntimeError("delta source identity is missing its legacy source id")
    legacy_to_production_source = {
        int(item["legacy_source_id"]): sources[key]
        for key, item in source_items.items()
    }
    expected_source_ids = sorted(set(sources.values()))
    source_reader = _open_readonly("research_publication")
    try:
        placeholders = ",".join("?" for _ in expected_source_ids)
        observed_rows = source_reader.execute(
                f"""SELECT id,title,publisher,publish_date,url,source_url,file_path
                       FROM source WHERE id IN ({placeholders})""",
                tuple(expected_source_ids),
            ).fetchall()
    finally:
        source_reader.close()
    observed_sources = {int(row[0]): tuple(row[1:]) for row in observed_rows}
    if set(observed_sources) != set(expected_source_ids):
        raise RuntimeError("research source mapping is not fully present in production")
    for key, item in source_items.items():
        expected = item["row"]
        observed = observed_sources[sources[key]]
        identity = (
            expected.get("title"),
            expected.get("publisher"),
            expected.get("publish_date"),
            expected.get("url"),
            expected.get("source_url"),
            expected.get("file_path"),
        )
        if observed != identity:
            raise RuntimeError(f"production research source identity mismatch: {key}")
    actor = trusted_os_principal()
    repository, read_factory = _shared_identity_repository()
    profile_source = {
        int(item["row"]["company_id"]): sources[item["source_keys"][0]]
        for item in section["company_profiles"]
    }
    financial_security_by_company = {
        int(item["row"]["research_company_id"]): dict(item["row"])
        for item in delta["financial"]["securities"]
    }
    industry_result = repository.ensure_industry(
        industry={
            "id": 50,
            "name": "光纤",
            "parent_id": 6,
            "level": 2,
            "tier": 1,
            "status": "深度跟踪",
            "core_dynamic": (
                "传统实芯光纤按产品和区域判断有效供需，空芯光纤按认证、"
                "产能和部署里程碑验证商业化。"
            ),
            "last_updated": "2026-08-18",
            "created_at": "2026-08-18 16:36:38",
        },
        stable_key="industry:path:通信/光纤",
        idempotency_key=f"fiber-industry:{delta['_sha256']}",
        actor=actor,
    )
    if int(industry_result["industry_id"]) != 50:
        raise RuntimeError("created industry identity did not preserve expected id: 50")
    identity_created = 0
    stable_keys: dict[int, str] = {}
    stored_names: dict[int, str] = {}
    reader = read_factory()
    try:
        industry = reader.execute(
            """SELECT payload->>'name' FROM shared_identity.legacy_record
                WHERE source_database='research.db' AND source_table='industry'
                  AND (payload->>'id')::bigint=50 AND formal_business_data=true"""
        ).fetchone()
        if industry is None or str(industry[0]) != "光纤":
            raise RuntimeError("production industry 50 is not 光纤")
        for item in section["company_updates"]:
            row = dict(item["row"])
            identity_listing_status = _canonical_listing_status(
                row["ticker"], row["market"], row["listing_status"]
            )
            identities = reader.execute(
                """SELECT payload->>'name',payload->>'ticker',payload->>'market',
                          payload->>'listing_status',stable_key,legacy_id
                      FROM shared_identity.legacy_record
                    WHERE source_database='research.db' AND source_table='company'
                      AND legacy_id=%s AND formal_business_data=true""",
                (str(row["id"]),),
            ).fetchall()
            payload_id_count = int(reader.execute(
                """SELECT count(*) FROM shared_identity.legacy_record
                    WHERE source_database='research.db' AND source_table='company'
                      AND payload->>'id'=%s AND formal_business_data=true""",
                (str(row["id"]),),
            ).fetchone()[0])
            if len(identities) > 1 or payload_id_count > 1:
                raise RuntimeError(f"company identity is ambiguous: {row['id']}")
            identity = identities[0] if identities else None
            expected_stable_key = LEGACY_COMPANY_STABLE_KEYS.get(
                int(row["id"])
            ) or company_security_stable_key(
                row["ticker"], row["market"], identity_listing_status
            )
            if identity is None:
                if int(row["id"]) != 704:
                    raise RuntimeError(
                        "only the reviewed Prysmian identity may be created by this delta: "
                        f"{row['id']}"
                    )
                financial_identity = financial_security_by_company[int(row["id"])]
                ensured = repository.ensure_listed_company_v2(
                    expected_company_id=int(row["id"]),
                    canonical_name=row["name"],
                    ticker=row["ticker"],
                    market=row["market"],
                    listing_status=identity_listing_status,
                    financial_market=financial_identity["market"],
                    financial_listing_status=financial_identity["listing_status"],
                    reporting_currency=financial_identity["reporting_currency"],
                    name_en=financial_identity.get("name_en"),
                    fiscal_year_end=financial_identity.get("fiscal_year_end"),
                    verification_source_ref=(
                        f"research.db:source:{profile_source[int(row['id'])]}"
                    ),
                    aliases=[row["name"]],
                    idempotency_key=(
                        f"fiber-company-identity:{delta['_sha256']}:{row['id']}"
                    ),
                    actor=actor,
                )
                if int(ensured["company_id"]) != int(row["id"]):
                    raise RuntimeError(
                        "created company identity did not preserve expected id: "
                        f"{row['id']}"
                    )
                identity_created += 1
                if str(ensured["stable_key"]) != expected_stable_key:
                    raise RuntimeError(f"created company stable identity mismatch: {row['id']}")
            else:
                live_name, _ticker, _market, _status, live_stable_key, _legacy_id = identity
                if _repair_legacy_utf8(live_name) != row["name"]:
                    raise RuntimeError(f"company name identity mismatch: {row['id']}")
                if str(live_stable_key) != expected_stable_key:
                    raise RuntimeError(f"company stable identity mismatch: {row['id']}")
                desired = (
                    row["name"], str(row["ticker"]).upper(), row["market"],
                    identity_listing_status, expected_stable_key, str(row["id"]),
                )
                if _company_identity_requires_completion(identity, desired):
                    repository.complete_company_identity_v2(
                        expected_company_id=int(row["id"]),
                        previous_name=str(live_name),
                        canonical_name=row["name"],
                        ticker=row["ticker"],
                        market=row["market"],
                        listing_status=identity_listing_status,
                        verification_source_ref=(
                            f"research.db:source:{profile_source[int(row['id'])]}"
                        ),
                        stable_key=expected_stable_key,
                        idempotency_key=(
                            f"fiber-company-identity-complete:{delta['_sha256']}:{row['id']}"
                        ),
                        actor=actor,
                    )
            verification_reader = read_factory()
            try:
                verified = verification_reader.execute(
                    """SELECT payload->>'name',payload->>'ticker',payload->>'market',
                              payload->>'listing_status',stable_key,legacy_id
                         FROM shared_identity.legacy_record
                        WHERE source_database='research.db' AND source_table='company'
                          AND legacy_id=%s AND formal_business_data=true""",
                    (str(row["id"]),),
                ).fetchall()
            finally:
                verification_reader.close()
            expected_identity = (
                row["name"], str(row["ticker"]).upper(), row["market"],
                identity_listing_status, expected_stable_key, str(row["id"]),
            )
            if len(verified) != 1 or tuple(verified[0]) != expected_identity:
                raise RuntimeError(f"company formal identity is incomplete: {row['id']}")
            stable_keys[int(row["id"])] = expected_stable_key
            stored_names[int(row["id"])] = row["name"]
    finally:
        reader.close()

    profiles: list[dict[str, Any]] = []
    for item in section["company_profiles"]:
        row = dict(item["row"])
        for field in PROFILE_JSON_SOURCE_FIELDS:
            parsed = json.loads(row[field])
            row[field] = json.dumps(
                _remap_source_references(parsed, legacy_to_production_source),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        row["source_ids"] = json.dumps(
            [sources[key] for key in item["source_keys"]],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        brief_key = item.get("brief_intro_source_key")
        row["brief_intro_src"] = sources.get(brief_key) if brief_key else None
        profiles.append(row)
    batch = {
        "industry_id": 50,
        "industry_name": "光纤",
        "source_mapping_sha256": mapping_sha256,
        "company_updates": [
            {
                "id": item["row"]["id"],
                "name": item["row"]["name"],
                "stored_name": stored_names[int(item["row"]["id"])],
                "stable_key": stable_keys[int(item["row"]["id"])],
                "brief_intro": item["row"]["brief_intro"],
                "brief_intro_src": item["row"].get("brief_intro_src"),
            }
            for item in section["company_updates"]
        ],
        "company_industry": [dict(row) for row in section["company_industry"]],
        "company_profiles": profiles,
    }
    result = repository.apply_company_profile_batch(
        batch=batch,
        idempotency_key=f"fiber-company-profile:{delta['_sha256']}",
        actor=actor,
    )
    if result.get("source_mapping_sha256") != mapping_sha256:
        raise RuntimeError("shared profile mutation did not preserve source mapping hash")
    return {
        "source_mapping_sha256": mapping_sha256,
        "industry_created": bool(industry_result["created"]),
        "company_identities_created": identity_created,
        "company_updates": int(result["company_updates"]),
        "company_industry": int(result["company_industry"]),
        "company_profiles": int(result["company_profiles"]),
        "records_added": int(result["records_added"]),
    }


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


def _resolve_financial_security_readonly(conn: Any, row: dict[str, Any]) -> int:
    securities = conn.execute(
        """SELECT id,research_company_id,canonical_name,ticker,market,
                  listing_status,reporting_currency,name_en,fiscal_year_end,
                  identity_status
             FROM financial_security
            WHERE research_company_id=?""",
        (row["research_company_id"],),
    ).fetchall()
    links = conn.execute(
        """SELECT research_company_id,security_id,link_role
             FROM financial_security_company_link
            WHERE research_company_id=?""",
        (row["research_company_id"],),
    ).fetchall()
    expected = (
        int(row["research_company_id"]), row["canonical_name"],
        str(row["ticker"]).upper(), row["market"], row["listing_status"],
        row["reporting_currency"], row.get("name_en"), row.get("fiscal_year_end"),
        row["identity_status"], "canonical",
    )
    if len(securities) != 1 or len(links) != 1:
        raise RuntimeError(
            "shared financial security identity is missing or ambiguous: "
            f"{row['research_company_id']}"
        )
    security = tuple(securities[0])
    link = tuple(links[0])
    if (
        security[1:10] + (link[2],) != expected
        or int(link[0]) != int(security[1])
        or int(link[1]) != int(security[0])
    ):
        raise RuntimeError(
            "shared financial security identity mismatch: "
            f"{row['research_company_id']}"
        )
    return int(security[0])


def apply_financial_data(delta: dict[str, Any]) -> dict[str, Any]:
    section = delta["financial"]
    conn = _open("financial_data")
    security_ids: dict[str, int] = {}
    source_ids: dict[str, int] = {}
    model_ids: dict[str, int] = {}
    try:
        for item in section["securities"]:
            row = dict(item["row"])
            security_ids[item["security_key"]] = _resolve_financial_security_readonly(
                conn, row
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
