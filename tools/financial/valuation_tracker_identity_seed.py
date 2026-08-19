from __future__ import annotations

"""Create only the three reviewed missing shared company identities."""

import argparse
import hashlib
import json
from pathlib import Path

from tools.data_platform.postgres_runtime import (
    build_catalog_connection_factory,
    load_postgres_runtime_catalog,
)
from tools.data_platform.routing import load_authority_matrix
from tools.data_platform.shared_identity import PostgresSharedIdentityRepository


REVIEWED_SEED_SHA256 = "a0f27b5ffd30bda0eddaeb2f39ef6a0e49e98ad9a618f49f378003e4d874fa8f"


def _sqlstate(exc: Exception) -> str | None:
    return getattr(exc, "sqlstate", None) or getattr(
        getattr(exc, "diag", None), "sqlstate", None
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres-runtime-catalog", type=Path, required=True)
    parser.add_argument("--cutover-unit-registry", type=Path, required=True)
    parser.add_argument("--seed", type=Path, required=True)
    parser.add_argument("--actor", required=True)
    args = parser.parse_args(argv)
    raw = args.seed.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    companies = payload.get("companies") or []
    if (
        payload.get("schema_version")
        != "honghu.valuation_tracker.company_identity_seed.v1"
        or len(companies) != 3
        or {row.get("ticker") for row in companies}
        != {"000960.SZ", "600301.SH", "000426.SZ"}
    ):
        raise RuntimeError("missing-company identity seed is not the reviewed set")
    seed_sha = hashlib.sha256(raw).hexdigest()
    if seed_sha != REVIEWED_SEED_SHA256:
        raise RuntimeError("missing-company identity seed content hash is not reviewed")
    catalog = load_postgres_runtime_catalog(args.postgres_runtime_catalog)
    reader = build_catalog_connection_factory(catalog, role="reader")
    writer = build_catalog_connection_factory(catalog, role="writer_shared_identity")
    _, matrix = load_authority_matrix(args.cutover_unit_registry, reader)
    route = matrix.route_for(
        "shared_identity",
        writer_operation="valuation_tracker_missing_company_identity_seed",
        transaction_boundary="one reviewed listed-company identity per transaction",
    )
    repository = PostgresSharedIdentityRepository(reader, writer, route)
    results = []
    for company in companies:
        item = None
        for attempt in range(3):
            connection = reader()
            try:
                existing = connection.execute(
                """SELECT (payload->>'id')::bigint,payload->>'name',
                          upper(payload->>'ticker'),payload->>'market',
                          payload->>'listing_status'
                     FROM shared_identity.legacy_record
                    WHERE source_database='research.db' AND source_table='company'
                      AND formal_business_data=true
                      AND upper(payload->>'ticker')=%s""",
                (company["ticker"],),
                ).fetchall()
                if len(existing) > 1:
                    raise RuntimeError(f"ambiguous existing identity: {company['ticker']}")
                if existing:
                    expected = existing[0]
                    if tuple(expected[1:]) != (
                        company["canonical_name"], company["ticker"],
                        company["market"], company["listing_status"],
                    ):
                        raise RuntimeError(f"conflicting existing identity: {existing[0]}")
                    company_id = int(expected[0])
                else:
                    company_id = int(connection.execute(
                        """SELECT coalesce(max(legacy_id::bigint),0)+1
                             FROM shared_identity.legacy_record
                            WHERE source_database='research.db'
                              AND source_table='company'
                              AND legacy_id ~ '^[0-9]+$'"""
                    ).fetchone()[0])
            finally:
                connection.close()
            try:
                item = repository.ensure_listed_company_v2(
                    expected_company_id=company_id,
                    canonical_name=company["canonical_name"],
                    ticker=company["ticker"],
                    market=company["market"],
                    listing_status=company["listing_status"],
                    financial_market=company["financial_market"],
                    financial_listing_status=company["financial_listing_status"],
                    reporting_currency=company["reporting_currency"],
                    name_en=company["name_en"],
                    fiscal_year_end=company["fiscal_year_end"],
                    verification_source_ref=company["verification_source_ref"],
                    aliases=company["aliases"],
                    idempotency_key=f"valuation-tracker-identity:{seed_sha}:{company['ticker']}",
                    actor=args.actor,
                )
                break
            except Exception as exc:
                if _sqlstate(exc) != "40001" or attempt == 2:
                    raise
        if item is None:  # pragma: no cover - defensive guard
            raise RuntimeError(f"identity allocation did not complete: {company['ticker']}")
        results.append(item)
    print(json.dumps({
        "schema_version": "honghu.valuation_tracker.company_identity_seed.result.v1",
        "seed_sha256": seed_sha,
        "results": results,
    }, ensure_ascii=False, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
