from __future__ import annotations

"""Reconcile frozen battery-company models with current external benchmarks.

Only reports published during the two quarters before the research cut-off are
eligible for company financial benchmarking.  Farasis has no qualifying fresh
broker model in the local/verified source set, so its stale 2025 reports are
explicitly excluded rather than rolled forward.
"""

import argparse
import hashlib
import json
from pathlib import Path
from statistics import median
from typing import Any

from tools.financial.constants import DB_PATH
from tools.financial.db import connect, transaction, verify_database
from tools.financial.repository import (
    record_external_reconciliation,
    record_source_snapshot,
    upsert_observation,
)


ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = (
    ROOT
    / "cache"
    / "lithium_battery_research"
    / "models"
    / "battery_independent_models_v1.json"
)
SNAPSHOT_PATH = (
    ROOT
    / "cache"
    / "lithium_battery_research"
    / "models"
    / "battery_financial_snapshot_v1.json"
)
AS_OF_DATE = "2026-07-28"
RUN_REF = "lithium_battery_b_20260728"


REPORT_BENCHMARKS: dict[str, dict[str, Any]] = {
    "3931.HK": {
        "publisher": "华泰证券",
        "date": "2026-06-09",
        "path_contains": "2026-06-09_华泰证券_中创新航",
        "revenue": {2026: 740.00, 2027: 1060.50, 2028: 1344.00},
        "net_income": {2026: 29.65, 2027: 49.48, 2028: 63.85},
        "note": "报告财务表为人民币百万元，本表换算为亿元人民币。",
    },
    "300014.SZ": {
        "publisher": "花旗研究",
        "date": "2026-06-09",
        "path_contains": "2026-06-09_citi_亿纬锂能",
        "revenue": {2026: 1095.67, 2027: 1459.24, 2028: 1938.78},
        "net_income": {2026: 83.43, 2027: 102.96, 2028: 136.64},
        "note": "使用报告模型更新后的Sales revenue和Reported net profit。",
    },
    "0666.HK": {
        "publisher": "里昂证券",
        "date": "2026-05-11",
        "path_contains": "2026-05-11_clsa_瑞浦兰钧",
        "revenue": {2026: 321.84, 2027: 380.34, 2028: 407.88},
        "net_income": {2026: 15.16, 2027: 20.54, 2028: 24.57},
        "note": "2026年7月公司正面盈利预告作为方向核验，不与卖方全年模型重复平均。",
    },
    "300207.SZ": {
        "publisher": "浙商证券",
        "date": "2026-06-03",
        "path_contains": "2026-06-03_浙商证券_欣旺达",
        "revenue": {2026: 839.00, 2027: 998.00, 2028: 1252.00},
        "net_income": {2026: 30.24, 2027: 41.76, 2028: 53.81},
        "note": "报告正文和财务表均给出2026—2028年预测。",
    },
}


def _find_report(fragment: str) -> Path:
    matches = [
        path
        for path in (ROOT / "papers" / "锂电池").rglob("*.pdf")
        if fragment in path.name
    ]
    if len(matches) != 1:
        raise FileNotFoundError(
            f"报告定位必须唯一：{fragment!r}，当前命中{len(matches)}份"
        )
    return matches[0]


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _output_map(conn: Any, model_id: int) -> dict[tuple[str, str], float]:
    return {
        (str(row["output_name"]), str(row["period_or_as_of_date"])): float(
            row["value_num"]
        )
        for row in conn.execute(
            """SELECT output_name,period_or_as_of_date,value_num
                 FROM financial_model_output
                WHERE model_run_id=? AND value_num IS NOT NULL""",
            (model_id,),
        )
    }


def _wind_benchmarks(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = snapshot["wind"]["consensus_fy1_fy3"]["rows"]
    result: dict[str, dict[str, Any]] = {}
    for ticker in ("300438.SZ", "300750.SZ", "002594.SZ", "002074.SZ"):
        raw = rows[ticker]
        result[ticker] = {
            "publisher": "Wind一致预期",
            "date": AS_OF_DATE,
            "source_ref": (
                f"wind:WSS:{ticker}:west_sales_fy1-fy3,"
                f"west_netprofit_fy1-fy3:{AS_OF_DATE.replace('-', '')}"
            ),
            "revenue": {
                year: float(raw[f"west_sales_fy{index}"]) / 1e8
                for index, year in enumerate((2026, 2027, 2028), start=1)
            },
            "net_income": {
                year: float(raw[f"west_netprofit_fy{index}"]) / 1e8
                for index, year in enumerate((2026, 2027, 2028), start=1)
            },
            "note": (
                "Wind一致预期为独立数据商快照；底层卖方若与本地报告重复，不再次合并计权。"
            ),
        }
    return result


def _market_snapshot(snapshot: dict[str, Any], ticker: str) -> tuple[float, str]:
    if ticker in snapshot["wind"]["current"]:
        row = snapshot["wind"]["current"][ticker]
        return float(row["market_cap_cny"]), (
            f"wind:WSS:{ticker}:mkt_cap_ard:{AS_OF_DATE.replace('-', '')}"
        )
    info = snapshot["yfinance"][ticker]["info"]
    fx = float(snapshot["fx"]["latest"]["close"])
    return (
        float(info["marketCap"]) / 1e8 * fx,
        f"yfinance:get_info:{ticker}:marketCap:{AS_OF_DATE};HKDCNY={fx:.6f}",
    )


def reconcile(db_path: Path) -> dict[str, Any]:
    models = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    benchmarks = _wind_benchmarks(snapshot)
    for ticker, row in REPORT_BENCHMARKS.items():
        path = _find_report(row["path_contains"])
        benchmarks[ticker] = {
            **row,
            "path": str(path.relative_to(ROOT)),
            "source_ref": (
                f"report:{row['publisher']}:{row['date']}:{path.relative_to(ROOT)}"
            ),
            "content_hash": _file_hash(path),
        }

    conn = connect(db_path)
    counts = {
        "companies_reconciled": 0,
        "financial_reconciliations": 0,
        "valuation_reconciliations": 0,
        "consensus_observations_inserted": 0,
        "consensus_observations_revised": 0,
        "consensus_observations_unchanged": 0,
        "stale_benchmark_exclusions": [
            {
                "ticker": "688567.SH",
                "reason": "最近可得卖方公司模型停留在2025年8月，不进入2026年7月当前财务对账。",
            }
        ],
    }
    by_ticker = {row["ticker"]: row for row in models["companies"]}
    try:
        with transaction(conn):
            for ticker, benchmark in benchmarks.items():
                company = by_ticker[ticker]
                financial_run = conn.execute(
                    """SELECT id,security_id FROM financial_model_run
                         WHERE run_key=?""",
                    (f"{RUN_REF}:{ticker}:financial:v1",),
                ).fetchone()
                valuation_run = conn.execute(
                    """SELECT id FROM financial_model_run WHERE run_key=?""",
                    (f"{RUN_REF}:{ticker}:valuation:v1",),
                ).fetchone()
                if financial_run is None or valuation_run is None:
                    raise ValueError(f"冻结模型不存在：{ticker}")
                financial_id = int(financial_run["id"])
                valuation_id = int(valuation_run["id"])
                security_id = int(financial_run["security_id"])
                outputs = _output_map(conn, financial_id)

                metadata = {
                    "selection_rule": "研究截止日前最近两个季度的公司财务预测；Wind一致预期单列且不与重复报告合并。",
                    "ticker": ticker,
                    "benchmark": benchmark,
                }
                payload_hash = benchmark.get("content_hash")
                if not payload_hash:
                    payload_hash = "sha256:" + hashlib.sha256(
                        json.dumps(
                            metadata,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ).hexdigest()
                source_snapshot_id = record_source_snapshot(
                    conn,
                    provider=(
                        "wind"
                        if benchmark["publisher"] == "Wind一致预期"
                        else "external_consensus"
                    ),
                    source_channel=(
                        "structured_api"
                        if benchmark["publisher"] == "Wind一致预期"
                        else "report"
                    ),
                    source_ref=benchmark["source_ref"],
                    title=(
                        f"{company['company']} Wind FY1—FY3一致预期"
                        if benchmark["publisher"] == "Wind一致预期"
                        else (
                            f"{company['company']} {benchmark['publisher']} "
                            f"{benchmark['date']}财务预测"
                        )
                    ),
                    publisher=benchmark["publisher"],
                    as_of_date=benchmark["date"],
                    content_hash=payload_hash,
                    raw_snapshot_path=benchmark.get("path"),
                    metadata=metadata,
                )

                for metric_key, output_label in (
                    ("revenue", "营业收入"),
                    ("net_income", "归母净利润"),
                ):
                    for index, year in enumerate((2026, 2027, 2028), start=1):
                        independent = outputs[(f"{year}年{output_label}", str(year))]
                        external = float(benchmark[metric_key][year])
                        gap_pct = (
                            (independent - external) / abs(external) * 100
                            if external
                            else None
                        )
                        conclusion = (
                            f"独立模型{independent:.2f}亿元，"
                            f"{benchmark['publisher']}为{external:.2f}亿元，"
                            f"差异{gap_pct:+.2f}%；差异保留并拆到量价、利润率和现金流，"
                            "不为贴合外部预测修改冻结模型。"
                        )
                        record_external_reconciliation(
                            conn,
                            financial_id,
                            benchmark_type="consensus",
                            benchmark_source_ref=benchmark["source_ref"],
                            metric_name=output_label,
                            period=str(year),
                            independent_value=independent,
                            benchmark_value=external,
                            unit="亿元人民币",
                            decomposition={
                                "publisher": benchmark["publisher"],
                                "publication_date": benchmark["date"],
                                "note": benchmark["note"],
                            },
                            conclusion=conclusion,
                        )
                        counts["financial_reconciliations"] += 1
                        _, status = upsert_observation(
                            conn,
                            return_status=True,
                            revision_reason=(
                                f"{RUN_REF}:latest_two_quarters_external_reconciliation"
                            ),
                            security_id=security_id,
                            metric_name=metric_key,
                            value_num=external,
                            unit="亿元人民币",
                            currency="CNY",
                            period_end=f"{year}-12-31",
                            fiscal_year=year,
                            fiscal_period=f"FY{index}",
                            frequency="annual",
                            fact_type="consensus",
                            as_of_date=benchmark["date"],
                            announcement_date=benchmark["date"],
                            provider=(
                                "wind"
                                if benchmark["publisher"] == "Wind一致预期"
                                else "external_consensus"
                            ),
                            raw_feature_name=(
                                f"west_{'sales' if metric_key == 'revenue' else 'netprofit'}_fy{index}"
                                if benchmark["publisher"] == "Wind一致预期"
                                else f"{benchmark['publisher']} {output_label}预测"
                            ),
                            source_snapshot_id=source_snapshot_id,
                            input_refs=[benchmark["source_ref"]],
                            quality_status="usable",
                            scenario_name="market_consensus",
                        )
                        counts[f"consensus_observations_{status}"] += 1

                pe_output = next(
                    item
                    for item in company["valuationMethods"]
                    if item["method"] == "正常化市盈率"
                )
                midpoint = (
                    float(pe_output["valueLow"]) + float(pe_output["valueHigh"])
                ) / 2
                market_cap, market_ref = _market_snapshot(snapshot, ticker)
                record_external_reconciliation(
                    conn,
                    valuation_id,
                    benchmark_type="market_implied",
                    benchmark_source_ref=market_ref,
                    metric_name="正常化市盈率目标市值中值",
                    period=AS_OF_DATE,
                    independent_value=midpoint,
                    benchmark_value=market_cap,
                    unit="亿元人民币",
                    decomposition={
                        "independent_low": pe_output["valueLow"],
                        "independent_high": pe_output["valueHigh"],
                        "market_date": AS_OF_DATE,
                    },
                    conclusion=(
                        f"正常化PE独立区间中值{midpoint:.2f}亿元，当前市值"
                        f"{market_cap:.2f}亿元；这是市场对账，不回写独立估值参数。"
                    ),
                )
                counts["valuation_reconciliations"] += 1
                counts["companies_reconciled"] += 1
        verify_database(db_path)
        return counts
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DB_PATH)
    args = parser.parse_args()
    print(json.dumps(reconcile(args.db), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
