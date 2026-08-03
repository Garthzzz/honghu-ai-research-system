from __future__ import annotations

"""Reconcile frozen HDI independent models with recent sell-side forecasts.

Only reports published in the two most recent quarters are included.  The
failed Wind ``west_*`` proxy request is not treated as evidence that consensus
data does not exist; this reconciliation uses dated local reports instead.
"""

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from statistics import median
from typing import Any

from tools.financial.constants import DB_PATH
from tools.financial.repository import (
    record_external_reconciliation,
    record_source_snapshot,
    upsert_observation,
)


RUN_REF = "hdi_b_20260726"

BENCHMARKS: dict[str, dict[str, Any]] = {
    "002463.SZ": {
        "sources": [
            {
                "publisher": "长江证券",
                "date": "2026-06-28",
                "path": (
                    "papers/HDI/2026-06-28_长江证券_沪电股份_沪电股份"
                    "（002463）：点评报告：AI算力需求高增，盈利能力持续提升.pdf"
                ),
                "revenue": {2026: 261.44, 2027: 392.17, 2028: 588.25},
                "net_profit": {2026: 59.88, 2027: 98.24, 2028: 152.52},
            },
        ]
    },
    "002916.SZ": {
        "sources": [
            {
                "publisher": "Goldman Sachs",
                "date": "2026-07-13",
                "path": (
                    "papers/HDI/2026-07-14_goldman sachs_深南电路_深南电路"
                    "（002916）：ai pcb产能扩张依托强劲需求；2026年第二季度"
                    "净利润指引同比增长44%~67%，符合预期；给予买入评级.pdf"
                ),
                "revenue": {2026: 313.39, 2027: 437.56, 2028: 515.29},
                "net_profit": {2026: 52.40, 2027: 84.68, 2028: 107.10},
            },
            {
                "publisher": "甬兴证券",
                "date": "2026-06-18",
                "path": (
                    "papers/HDI/2026-06-18_甬兴证券_深南电路_深南电路"
                    "（002916）：公司点评：把握AI行业发展机遇，PCB与载板需求加速释放.pdf"
                ),
                "revenue": {2026: 312.51, 2027: 400.32, 2028: 500.35},
                "net_profit": {2026: 51.71, 2027: 71.86, 2028: 96.67},
            },
            {
                "publisher": "Nomura",
                "date": "2026-07-17",
                "path": (
                    "papers/HDI/2026-07-19_nomura_深南电路_深南电路"
                    "（002916）：pcb和ic基板驱动稳健增长；更优产品结构支撑"
                    "利润率扩张.pdf"
                ),
                "revenue": {2026: 327.44, 2027: 451.28, 2028: 601.73},
                "net_profit": {2026: 54.48, 2027: 80.37, 2028: 110.69},
            },
        ]
    },
    "300476.SZ": {
        "sources": [
            {
                "publisher": "Nomura",
                "date": "2026-07-13",
                "path": (
                    "papers/HDI/2026-07-13_nomura_胜宏科技_胜宏科技（300476）："
                    "对产品延迟和市场份额流失的担忧过度…… ……rubin升级、asic和"
                    "光收发器pcb是关键驱动力.pdf"
                ),
                "revenue": {2026: 278.50, 2027: 491.58, 2028: 709.41},
                "net_profit": {2026: 74.97, 2027: 141.64, 2028: 209.32},
            },
            {
                "publisher": "甬兴证券",
                "date": "2026-07-09",
                "path": (
                    "papers/HDI/2026-07-09_甬兴证券_胜宏科技_胜宏科技（300476）："
                    "公司点评：深耕高端pcb，受益于aipcb发展浪潮.pdf"
                ),
                "revenue": {2026: 327.97, 2027: 540.53, 2028: 766.89},
                "net_profit": {2026: 79.74, 2027: 141.20, 2028: 212.09},
            },
        ]
    },
    "002938.SZ": {
        "sources": [
            {
                "publisher": "UBS",
                "date": "2026-05-29",
                "path": (
                    "papers/HDI/2026-05-29_ubs equities_鹏鼎控股_鹏鼎控股"
                    "（002938）：快评鹏鼎控股2026 aic： ai pcb新势力.pdf"
                ),
                "revenue": {2026: 493.97, 2027: 660.90, 2028: 873.81},
                "net_profit": {2026: 51.46, 2027: 70.24, 2028: 103.38},
                "note": "净利润由UBS稀释后EPS乘本研究估算总股本得到",
            },
            {
                "publisher": "广发证券",
                "date": "2026-06-30",
                "path": (
                    "papers/HDI/2026-06-30_广发证券_鹏鼎控股_鹏鼎控股"
                    "（002938）：增资泰国子公司，高阶hdi及hlc扩产提速.pdf"
                ),
                "revenue": {2026: 452.92, 2027: 591.91, 2028: 752.61},
                "net_profit": {2026: 53.61, 2027: 80.21, 2028: 110.20},
            },
        ]
    },
    "603228.SH": {
        "sources": [
            {
                "publisher": "长江证券",
                "date": "2026-06-28",
                "path": (
                    "papers/HDI/2026-06-28_长江证券_景旺电子_景旺电子"
                    "（603228）：点评报告：聚焦ai算力与高端制造，深化1+1+n战略"
                    "布局.pdf"
                ),
                "revenue": {2026: 183.70, 2027: 229.62, 2028: 298.51},
                "net_profit": {2026: 21.51, 2027: 28.13, 2028: 38.70},
            }
        ]
    },
}


def _model_outputs(
    conn: sqlite3.Connection, model_id: int
) -> dict[tuple[str, str], float]:
    rows = conn.execute(
        """SELECT output_name,period_or_as_of_date,value_num
             FROM financial_model_output
            WHERE model_run_id=? AND value_num IS NOT NULL""",
        (model_id,),
    ).fetchall()
    return {
        (str(row["output_name"]), str(row["period_or_as_of_date"])): float(
            row["value_num"]
        )
        for row in rows
    }


def reconcile(db_path: Path) -> dict[str, Any]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    inserted = 0
    observations = {"inserted": 0, "revised": 0, "unchanged": 0}
    details: list[dict[str, Any]] = []
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("BEGIN IMMEDIATE")
        for ticker, benchmark in BENCHMARKS.items():
            run_key = f"{RUN_REF}.{ticker}.financial_bridge.v3"
            row = conn.execute(
                """SELECT id,security_id,status,input_hash,output_hash
                     FROM financial_model_run WHERE run_key=?""",
                (run_key,),
            ).fetchone()
            if row is None:
                raise ValueError(f"冻结模型不存在: {run_key}")
            model_id = int(row["id"])
            outputs = _model_outputs(conn, model_id)
            source_refs = [
                f"{item['publisher']} {item['date']} {item['path']}"
                for item in benchmark["sources"]
            ]
            benchmark_source_ref = " | ".join(source_refs)
            latest_date = max(str(item["date"]) for item in benchmark["sources"])
            snapshot_payload = {
                "ticker": ticker,
                "selection_rule": "仅使用截至2026-07-24最近两个季度发布的公司财务预测",
                "reports": benchmark["sources"],
            }
            snapshot_hash = "sha256:" + hashlib.sha256(
                json.dumps(
                    snapshot_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            source_snapshot_id = record_source_snapshot(
                conn,
                provider="external_consensus",
                source_channel="report",
                source_ref=benchmark_source_ref,
                title=(
                    f"{ticker}最近两个季度{len(benchmark['sources'])}份"
                    "卖方财务预测中位数"
                ),
                publisher="; ".join(
                    str(item["publisher"]) for item in benchmark["sources"]
                ),
                as_of_date=latest_date,
                content_hash=snapshot_hash,
                metadata=snapshot_payload,
            )
            for metric_key, output_name in (
                ("revenue", "营业收入"),
                ("net_profit", "归母净利润"),
            ):
                for year in (2026, 2027, 2028):
                    values = [
                        float(item[metric_key][year])
                        for item in benchmark["sources"]
                        if year in item[metric_key]
                    ]
                    benchmark_value = median(values)
                    independent_value = outputs[(output_name, str(year))]
                    conclusion = (
                        f"独立预测{independent_value:.2f}亿元，最近两个季度内"
                        f"{len(values)}份可比报告的中位数为{benchmark_value:.2f}亿元；"
                        "差异保留，不为贴合卖方预测而改模。"
                    )
                    record_external_reconciliation(
                        conn,
                        model_id,
                        benchmark_type="consensus",
                        benchmark_source_ref=benchmark_source_ref,
                        metric_name=output_name,
                        period=str(year),
                        independent_value=independent_value,
                        benchmark_value=benchmark_value,
                        unit="亿元人民币",
                        decomposition={
                            "included_reports": [
                                {
                                    "publisher": item["publisher"],
                                    "date": item["date"],
                                    "value": item[metric_key][year],
                                    "note": item.get("note"),
                                }
                                for item in benchmark["sources"]
                                if year in item[metric_key]
                            ],
                            "selection_rule": "仅使用截至2026-07-24最近两个季度发布的公司财务预测",
                        },
                        conclusion=conclusion,
                    )
                    inserted += 1
                    canonical_metric = (
                        "revenue" if metric_key == "revenue" else "net_income"
                    )
                    _, observation_status = upsert_observation(
                        conn,
                        return_status=True,
                        revision_reason=(
                            f"{RUN_REF}:latest_two_quarters_consensus_refresh"
                        ),
                        security_id=int(row["security_id"]),
                        metric_name=canonical_metric,
                        value_num=benchmark_value,
                        unit="亿元人民币",
                        currency="CNY",
                        period_start=f"{year}-01-01",
                        period_end=f"{year}-12-31",
                        fiscal_year=year,
                        fiscal_period=f"FY{year - 2025}",
                        frequency="annual",
                        fact_type="consensus",
                        as_of_date=latest_date,
                        provider="external_consensus",
                        raw_feature_name=(
                            f"latest_two_quarters_median.{canonical_metric}"
                        ),
                        source_snapshot_id=source_snapshot_id,
                        formula=(
                            f"{len(values)}份最近两个季度卖方报告预测的中位数"
                        ),
                        input_refs=source_refs,
                        quality_status="usable",
                        scenario_name="median",
                    )
                    observations[observation_status] += 1
                    details.append(
                        {
                            "ticker": ticker,
                            "metric": output_name,
                            "year": year,
                            "independent": independent_value,
                            "benchmark_median": benchmark_value,
                            "report_count": len(values),
                        }
                    )
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"financial.db foreign_key_check failed: {violations[:3]}")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {
        "reconciliations_recorded": inserted,
        "consensus_observations": observations,
        "details": details,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("cache/hdi_research/external_reconciliation_summary.json"),
    )
    args = parser.parse_args(argv)
    result = reconcile(args.db.resolve())
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
