from __future__ import annotations

"""One reviewed production setup path for valuation tracker seed data.

PostgreSQL migrations must already have been applied through 0024.  The tool
then creates only the three frozen missing shared identities, imports the
reviewed workbook and valuation history exactly once, and performs an exact
seven-member/eleven-version readback.
"""

import argparse
import contextlib
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path

from tools.data_platform.postgres_runtime import (
    build_catalog_connection_factory,
    load_postgres_runtime_catalog,
)
from tools.financial.valuation_tracker import WORKBOOK_SHA256
from tools.financial.valuation_tracker_identity_seed import (
    REVIEWED_SEED_SHA256,
    main as identity_seed_main,
)
from tools.financial.valuation_tracker_seed import main as workbook_seed_main
from tools.financial.valuation_tracker_history_seed import (
    REVIEWED_HISTORY_SHA256,
    canonical_history_sha256,
    main as history_seed_main,
)


REVIEWED_WORKBOOK_SEED_SHA256 = (
    "09907358d4e3ee9751e7196fcd9f27574553b434915bce38af3d7c4175f19e41"
)


def _json_value(value):
    return json.loads(value) if isinstance(value, str) else value


def _run(entrypoint, arguments: list[str]) -> dict:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        status = entrypoint(arguments)
    if status != 0:
        raise RuntimeError(f"setup entrypoint returned {status}")
    lines = [line for line in output.getvalue().splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("setup entrypoint returned no result")
    return json.loads(lines[-1])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres-runtime-catalog", type=Path, required=True)
    parser.add_argument("--cutover-unit-registry", type=Path, required=True)
    parser.add_argument("--identity-seed", type=Path, required=True)
    parser.add_argument("--workbook-seed", type=Path, required=True)
    parser.add_argument("--valuation-history", type=Path, required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--evidence-output", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)

    identity_sha = hashlib.sha256(args.identity_seed.read_bytes()).hexdigest()
    workbook_seed_sha = hashlib.sha256(args.workbook_seed.read_bytes()).hexdigest()
    workbook_payload = json.loads(args.workbook_seed.read_text(encoding="utf-8"))
    history_payload = json.loads(args.valuation_history.read_text(encoding="utf-8"))
    if identity_sha != REVIEWED_SEED_SHA256:
        raise RuntimeError("identity seed SHA does not match reviewed production input")
    if workbook_seed_sha != REVIEWED_WORKBOOK_SEED_SHA256:
        raise RuntimeError("workbook seed file SHA does not match reviewed production input")
    if workbook_payload.get("workbook_sha256") != WORKBOOK_SHA256:
        raise RuntimeError("workbook source SHA does not match reviewed production input")
    history_sha = canonical_history_sha256(history_payload)
    if (
        history_sha != REVIEWED_HISTORY_SHA256
        or history_payload.get("artifact_sha256") != history_sha
    ):
        raise RuntimeError("valuation history content hash is not reviewed")

    catalog = load_postgres_runtime_catalog(args.postgres_runtime_catalog)
    migration_reader = build_catalog_connection_factory(catalog, role="migration")
    reader = build_catalog_connection_factory(catalog, role="reader")
    connection = migration_reader()
    try:
        migration = connection.execute(
            """SELECT migration_sha256 FROM operations.schema_migration
                WHERE migration_id='0024_valuation_ranges_share_price_hk'"""
        ).fetchone()
        if migration is None:
            raise RuntimeError("migration 0021 is not applied; refusing to seed")
    finally:
        connection.close()

    identity_result = {"status": "verified_existing"}
    workbook_result = {"status": "verified_existing"}
    history_result = {"status": "verified_existing"}
    if not args.verify_only:
        identity_result = _run(identity_seed_main, [
            "--postgres-runtime-catalog", str(args.postgres_runtime_catalog),
            "--cutover-unit-registry", str(args.cutover_unit_registry),
            "--seed", str(args.identity_seed), "--actor", args.actor,
        ])
        workbook_result = _run(workbook_seed_main, [
            "--postgres-runtime-catalog", str(args.postgres_runtime_catalog),
            "--seed", str(args.workbook_seed), "--actor", args.actor,
        ])
        history_result = _run(history_seed_main, [
            "--postgres-runtime-catalog", str(args.postgres_runtime_catalog),
            "--history", str(args.valuation_history), "--actor", args.actor,
        ])

    connection = reader()
    try:
        rows = connection.execute(
            """SELECT m.company_id,m.security_id,m.canonical_name,m.canonical_ticker,
                      m.market,m.board,m.display_order,m.source_row_number,
                      m.source_row,m.identity_correction,
                      v.version_id,v.valuation_kind,v.origin,v.status,v.valuation_date,
                      v.target_year,v.ceiling_value,v.currency,v.amount_unit,
                      v.expected_net_profit,v.sources,
                      p.policy_revision,p.researcher_ratio_threshold,
                      p.ai_ratio_threshold,p.operator,p.max_snapshot_age_hours,
                      c.payload->>'name',upper(c.payload->>'ticker'),c.stable_key,
                      s.payload->>'canonical_name',upper(s.payload->>'ticker'),
                      s.payload->>'research_company_id',s.stable_key,
                      l.payload->>'security_id',l.payload->>'link_role',
                      w.workbook_sha256,w.stable_key,w.title
                 FROM valuation_tracker.member m
                 JOIN valuation_tracker.watchlist w USING(watchlist_id)
                 JOIN valuation_tracker.valuation_version v
                   ON v.member_id=m.member_id AND v.origin='workbook_seed'
                 JOIN valuation_tracker.alert_policy_revision p
                   ON p.member_id=m.member_id AND p.policy_revision=1
                 JOIN shared_identity.legacy_record c
                   ON c.source_database='research.db' AND c.source_table='company'
                  AND c.legacy_id=m.company_id::text AND c.formal_business_data=true
                 JOIN shared_identity.legacy_record s
                   ON s.source_database='financial.db'
                  AND s.source_table='financial_security'
                  AND s.legacy_id=m.security_id::text AND s.formal_business_data=true
                 JOIN shared_identity.legacy_record l
                   ON l.source_database='financial.db'
                  AND l.source_table='financial_security_company_link'
                  AND l.legacy_id=m.company_id::text AND l.formal_business_data=true
                WHERE m.enabled ORDER BY m.display_order"""
        ).fetchall()
    finally:
        connection.close()
    if len(rows) != 7:
        raise RuntimeError("production readback is not the exact seven-security basket")
    expected_rows = workbook_payload["rows"]
    seen_company_ids: set[int] = set()
    seen_security_ids: set[int] = set()
    for observed, expected in zip(rows, expected_rows, strict=True):
        (
            company_id, security_id, name, ticker, market, board, display_order,
            source_row_number, source_row, correction, version_id, valuation_kind,
            origin, status, valuation_date, target_year, ceiling, currency,
            amount_unit, expected_profit, sources, policy_revision,
            researcher_threshold, ai_threshold, operator, max_age, company_name,
            company_ticker, company_key, security_name, security_ticker,
            linked_company_id, security_key, linked_security_id, link_role,
            imported_workbook_sha, watchlist_key, watchlist_title,
        ) = observed
        expected_source = [{
            "title": workbook_payload["workbook_name"],
            "sha256": WORKBOOK_SHA256,
            "row": str(expected["source_row_number"]),
        }]
        exact = (
            int(company_id) > 0
            and int(security_id) > 0
            and str(name) == expected["canonical_name"]
            and str(ticker) == expected["canonical_ticker"]
            and str(market) == expected["market"]
            and str(board) == expected["board"]
            and int(display_order) == expected["display_order"]
            and int(source_row_number) == expected["source_row_number"]
            and _json_value(source_row) == expected["source_row"]
            and _json_value(correction) == expected["identity_correction"]
            and int(version_id) > 0
            and valuation_kind == "researcher"
            and origin == "workbook_seed"
            and status == "published"
            and str(valuation_date) == workbook_payload["valuation_date"]
            and int(target_year) == 2028
            and float(ceiling) == float(expected["ceiling_value"])
            and str(currency) == expected["currency"]
            and amount_unit == "亿元"
            and float(expected_profit) == float(expected["expected_net_profit"])
            and _json_value(sources) == expected_source
            and int(policy_revision) == 1
            and float(researcher_threshold) == 1.0
            and float(ai_threshold) == 1.0
            and operator == "gte"
            and int(max_age) == 48
            and company_name == expected["canonical_name"]
            and company_ticker == expected["canonical_ticker"]
            and security_name == expected["canonical_name"]
            and security_ticker == expected["canonical_ticker"]
            and int(linked_company_id) == int(company_id)
            and int(linked_security_id) == int(security_id)
            and company_key == security_key
            and link_role == "canonical"
            and imported_workbook_sha == WORKBOOK_SHA256
            and watchlist_key == "market-cap-space-v1"
            and watchlist_title == "市值空间与估值跟踪"
        )
        if not exact:
            raise RuntimeError(
                f"production member/version/policy identity differs at order {expected['display_order']}"
            )
        seen_company_ids.add(int(company_id))
        seen_security_ids.add(int(security_id))
    if len(seen_company_ids) != 7 or len(seen_security_ids) != 7:
        raise RuntimeError("production company or security identities are duplicated")

    expected_history = {
        (int(row["company_id"]), str(row["valuation_date"])): row
        for row in history_payload["versions"]
    }
    connection = reader()
    try:
        history_rows = connection.execute(
            """SELECT m.company_id,m.security_id,m.canonical_ticker,v.valuation_date,
                      v.lower_value,v.base_value,v.upper_value,v.currency,
                      v.operating_context,v.profit_context,v.cash_flow_context,
                      v.shareholder_return_context,v.valuation_methods,v.market_context,
                      v.sources,v.frozen_input,v.method_summary,v.change_reason
                 FROM valuation_tracker.valuation_version v
                 JOIN valuation_tracker.member m USING(member_id)
                WHERE v.model_name='honghu-reviewed-valuation-history-v2'
                ORDER BY m.company_id,v.valuation_date"""
        ).fetchall()
    finally:
        connection.close()
    if len(history_rows) != 11:
        raise RuntimeError("production valuation history is not the exact eleven-version set")
    for row in history_rows:
        expected = expected_history.get((int(row[0]), str(row[3])))
        if expected is None:
            raise RuntimeError("production valuation history contains an unexpected identity")
        exact = (
            int(row[1]) > 0
            and str(row[2]) == expected["ticker"]
            and float(row[4]) == float(expected["lower_value"])
            and float(row[5]) == float(expected["base_value"])
            and float(row[6]) == float(expected["upper_value"])
            and str(row[7]) == expected["currency"]
            and _json_value(row[8]) == expected["operating_context"]
            and _json_value(row[9]) == expected["profit_context"]
            and _json_value(row[10]) == expected["cash_flow_context"]
            and _json_value(row[11]) == expected["shareholder_return_context"]
            and _json_value(row[12]) == expected["valuation_methods"]
            and _json_value(row[13]) == expected["market_context"]
            and _json_value(row[14]) == expected["sources"]
            and _json_value(row[15]) == expected["frozen_input"]
            and str(row[16]) == expected["method_summary"]
            and str(row[17]) == expected["change_reason"]
        )
        if not exact:
            raise RuntimeError("production valuation history differs from reviewed input")

    evidence = {
        "schema_version": "honghu.valuation_tracker.production_setup_evidence.v2",
        "status": "pass",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "actor": args.actor,
        "migration_id": "0024_valuation_ranges_share_price_hk",
        "migration_sha256": str(migration[0]),
        "identity_seed_sha256": identity_sha,
        "workbook_seed_sha256": workbook_seed_sha,
        "workbook_sha256": WORKBOOK_SHA256,
        "valuation_history_sha256": history_sha,
        "contract_verified": True,
        "identity_result": identity_result,
        "workbook_result": workbook_result,
        "history_result": history_result,
        "valuation_history_version_count": len(history_rows),
        "members": [
            {
                "company_id": int(row[0]), "security_id": int(row[1]),
                "name": str(row[2]), "ticker": str(row[3]), "market": str(row[4]),
                "board": str(row[5]), "display_order": int(row[6]),
                "researcher_version_id": int(row[10]),
                "ceiling_value": str(row[16]), "currency": str(row[17]),
            }
            for row in rows
        ],
    }
    args.evidence_output.parent.mkdir(parents=True, exist_ok=True)
    args.evidence_output.write_text(
        json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
