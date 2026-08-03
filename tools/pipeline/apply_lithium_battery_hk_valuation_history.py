from __future__ import annotations

"""Write the bounded HK battery valuation history to financial.db."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from tools.financial.constants import DB_PATH
from tools.financial.db import connect, initialize_database, transaction, verify_database
from tools.financial.repository import record_source_snapshot, upsert_observation


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = (
    ROOT
    / "cache"
    / "lithium_battery_research"
    / "models"
    / "battery_hk_valuation_history_v1.json"
)


def _file_sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def apply(
    input_path: Path = DEFAULT_INPUT, db_path: Path = DB_PATH
) -> dict[str, Any]:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    initialize_database(db_path)
    conn = connect(db_path)
    counts: Counter[str] = Counter()
    try:
        securities = {
            str(row["ticker"]).upper(): int(row["id"])
            for row in conn.execute("SELECT id,ticker FROM financial_security")
        }
        with transaction(conn):
            for company in payload["companies"]:
                ticker = company["ticker"].upper()
                if ticker not in securities:
                    raise ValueError(f"financial_security缺少{ticker}")
                source_id = record_source_snapshot(
                    conn,
                    provider="yfinance",
                    source_channel="structured_api",
                    source_ref=f"yfinance:hk_battery_monthly_valuation:{ticker}:2026-07-28",
                    title=f"{ticker}月末价格与已公开年报口径估值序列",
                    publisher="Yahoo Finance与公司年报",
                    as_of_date=payload["asOfDate"],
                    content_hash=_file_sha(input_path),
                    raw_snapshot_path=input_path.relative_to(ROOT).as_posix(),
                    metadata={
                        "database_boundary": "financial.db only",
                        "research_run_ref": "lithium_battery_b_20260728",
                        "look_ahead_control": payload["sourceContract"][
                            "lookAheadControl"
                        ],
                        "limitation": payload["sourceContract"]["limitation"],
                    },
                )
                for row in company["observations"]:
                    values = (
                        (
                            "close",
                            row["closeHkd"],
                            "港元/股",
                            "yfinance.history.month_end_close",
                            None,
                        ),
                        (
                            "pb",
                            row["pbApprox"],
                            "倍",
                            "yfinance.derived.point_in_time.pb",
                            (
                                "PB≈月末收盘价（港元）×HKDCNY÷"
                                "当时已公开年报每股净资产（人民币）"
                            ),
                        ),
                        (
                            "pe_ttm",
                            row["peTtmApprox"],
                            "倍",
                            "yfinance.derived.point_in_time.pe_ttm",
                            (
                                "PE近似值≈月末收盘价（港元）×HKDCNY÷"
                                "当时已公开年报归母每股收益（人民币）"
                            ),
                        ),
                    )
                    for metric, value, unit, raw_feature, formula in values:
                        if value is None:
                            continue
                        _, status = upsert_observation(
                            conn,
                            return_status=True,
                            revision_reason=(
                                "lithium_battery_hk_point_in_time_valuation_refresh"
                            ),
                            security_id=securities[ticker],
                            metric_name=metric,
                            value_num=float(value),
                            unit=unit,
                            currency="HKD" if metric == "close" else None,
                            period_end=row["date"],
                            frequency="monthly",
                            fact_type="market",
                            as_of_date=row["date"],
                            announcement_date=row["financialAvailableFrom"],
                            provider="yfinance",
                            raw_feature_name=raw_feature,
                            source_snapshot_id=source_id,
                            formula=formula,
                            input_refs=[
                                f"financial_year:{row['financialYear']}",
                                f"financial_available_from:{row['financialAvailableFrom']}",
                                f"hkd_cny:{row['hkdCny']}",
                            ],
                            quality_status=(
                                "limited" if metric in {"pb", "pe_ttm"} else "usable"
                            ),
                            scenario_name="reported",
                        )
                        counts[status] += 1
        verify_database(db_path)
    finally:
        conn.close()
    return {
        "input": input_path.relative_to(ROOT).as_posix(),
        "database": db_path.relative_to(ROOT).as_posix(),
        "counts": dict(counts),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    args = parser.parse_args()
    print(
        json.dumps(
            apply(args.input.resolve(), args.db.resolve()),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
