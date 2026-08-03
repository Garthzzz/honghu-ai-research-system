from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _wind_consensus(snapshot: dict[str, Any]) -> dict[str, list[float]]:
    rows = snapshot["wind"]["consensus_fy1_fy3"]["rows"]
    row = next(iter(rows.values()))
    return {
        "revenue_100m_cny": [
            float(row[f"west_sales_fy{index}"]) / 1e8
            for index in (1, 2, 3)
        ],
        "parent_net_income_100m_cny": [
            float(row[f"west_netprofit_fy{index}"]) / 1e8
            for index in (1, 2, 3)
        ],
        "eps_cny": [float(row[f"west_eps_fy{index}"]) for index in (1, 2, 3)],
        "roe_pct": [
            float(row[f"west_avgroe_fy{index}"]) for index in (1, 2, 3)
        ],
    }


def build(
    *,
    model_path: Path,
    snapshot_path: Path,
) -> dict[str, Any]:
    model = json.loads(model_path.read_text(encoding="utf-8"))
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    consensus = _wind_consensus(snapshot)
    base = model["scenarios"]["基准情景"]
    years = [2026, 2027, 2028]
    model_revenue = [float(row["revenue_100m_cny"]) for row in base]
    model_profit = [
        float(row["parent_net_income_100m_cny"]) for row in base
    ]

    comparisons: list[dict[str, Any]] = []
    for index, year in enumerate(years):
        comparisons.append(
            {
                "year": year,
                "independent_revenue_100m_cny": model_revenue[index],
                "wind_consensus_revenue_100m_cny": round(
                    consensus["revenue_100m_cny"][index], 1
                ),
                "revenue_difference_pct": round(
                    (
                        model_revenue[index]
                        / consensus["revenue_100m_cny"][index]
                        - 1.0
                    )
                    * 100,
                    1,
                ),
                "independent_parent_net_income_100m_cny": model_profit[index],
                "wind_consensus_parent_net_income_100m_cny": round(
                    consensus["parent_net_income_100m_cny"][index], 1
                ),
                "profit_difference_pct": round(
                    (
                        model_profit[index]
                        / consensus["parent_net_income_100m_cny"][index]
                        - 1.0
                    )
                    * 100,
                    1,
                ),
                "wind_consensus_roe_pct": round(
                    consensus["roe_pct"][index], 1
                ),
            }
        )

    sell_side = [
        {
            "institution": "华创证券",
            "report_date": "2026-05-15",
            "parent_net_income_100m_cny": [101.8, 125.7, 143.0],
            "role": "外部情景参考",
        },
        {
            "institution": "中银证券",
            "report_date": "2026-05",
            "parent_net_income_100m_cny": [89.6, 115.2, 138.5],
            "role": "外部情景参考",
        },
        {
            "institution": "中信建投",
            "report_date": "2026-05",
            "parent_net_income_100m_cny": [97.0, 123.8, 142.5],
            "role": "外部情景参考",
        },
        {
            "institution": "花旗",
            "report_date": "2026-07-21",
            "parent_net_income_100m_cny": [63.6, 93.7, 128.8],
            "role": "反方压力参考",
        },
    ]

    current = snapshot["wind"]["current"]
    return {
        "reconciliation_version": "run14.huayou_external_reconciliation.v1",
        "as_of_date": model["as_of_date"],
        "independent_model_hash": _sha256_file(model_path),
        "financial_snapshot_hash": _sha256_file(snapshot_path),
        "comparison": comparisons,
        "sell_side_ranges": [
            {
                "year": year,
                "low_100m_cny": min(
                    row["parent_net_income_100m_cny"][index]
                    for row in sell_side
                ),
                "high_100m_cny": max(
                    row["parent_net_income_100m_cny"][index]
                    for row in sell_side
                ),
                "independent_100m_cny": model_profit[index],
            }
            for index, year in enumerate(years)
        ],
        "sell_side_detail": sell_side,
        "market_snapshot": {
            "trade_date": current["trade_date"],
            "price_cny": current["price"],
            "market_cap_100m_cny": current["market_cap_cny"],
            "pe_ttm": current["pe_ttm"],
            "pe_forward_12m": current["pe_forward"],
            "pb": current["pb"],
            "ev_ebitda": current["ev_ebitda"],
            "roe_ttm_pct": current["roe"],
            "roa_ttm_pct": current["roa"],
            "eps_ttm_cny": current["eps_ttm"],
            "bps_latest_cny": current["bps_mrq"],
        },
        "reconciliation_conclusion": (
            "独立模型2026—2028年收入比Wind一致预期低约3%—4%，"
            "归母净利润低约6%—12%。差异并非单位或财年错误，主要来自三项更保守判断："
            "钴价冲高后的毛利不按峰值外推；Pomalaa只按2027年爬坡而非2026年满产；"
            "正极材料和前驱体在LFP占比高、海外爬坡成本尚未完全消化时不假设快速恢复至高利润率。"
            "独立结果仍落在主要卖方区间内，因此属于可解释的谨慎差异，不是足以单独构成多空机会的重大预期差。"
        ),
        "change_log": [
            {
                "field": "独立模型输入",
                "changed_after_reconciliation": False,
                "reason": "外部对账未发现币种、单位、财年或归母口径错误，不因接近一致预期而修改独立假设。",
            }
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="华友钴业Run14独立模型与Wind一致预期、卖方预测对账"
    )
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(model_path=args.model, snapshot_path=args.snapshot)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "model_hash": result["independent_model_hash"],
                "profit_differences_pct": [
                    row["profit_difference_pct"]
                    for row in result["comparison"]
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
