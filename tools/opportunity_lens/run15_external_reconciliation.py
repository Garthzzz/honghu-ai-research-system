from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from datetime import date, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = ROOT / "cache/chint_run15/run15_chint_financial_model.json"
WIND_PATH = (
    ROOT / "cache/chint_run15/wind_financial_snapshot_20260726.json"
)
DEFAULT_OUTPUT = (
    ROOT / "cache/chint_run15/run15_external_reconciliation.json"
)
AS_OF_DATE = date(2026, 7, 25)
RECENT_REPORT_CUTOFF = AS_OF_DATE - timedelta(days=183)
YEARS = ("2026", "2027", "2028")


REPORT_ROWS: tuple[dict[str, Any], ...] = (
    {
        "institution": "国联民生证券",
        "report_date": "2026-04-16",
        "source_ref": "r-glms-20260416",
        "coverage_status": "active_at_report_date",
        "revenue_100m_cny": {
            "2026": 632.46,
            "2027": 676.66,
            "2028": 729.63,
        },
        "parent_net_income_100m_cny": {
            "2026": 57.66,
            "2027": 70.75,
            "2028": 85.29,
        },
    },
    {
        "institution": "光大证券",
        "report_date": "2026-04-21",
        "source_ref": "r-ebscn-20260421",
        "coverage_status": "active_at_report_date",
        "revenue_100m_cny": {
            "2026": 588.86,
            "2027": 610.87,
            "2028": 635.34,
        },
        "parent_net_income_100m_cny": {
            "2026": 51.42,
            "2027": 58.10,
            "2028": 66.26,
        },
        "operating_cash_flow_100m_cny": {"2026": 120.18},
    },
    {
        "institution": "兴业证券",
        "report_date": "2026-04-27",
        "source_ref": "r-xyzq-20260427",
        "coverage_status": "active_at_report_date",
        "revenue_100m_cny": {
            "2026": 628.91,
            "2027": 679.43,
            "2028": 740.75,
        },
        "parent_net_income_100m_cny": {
            "2026": 52.55,
            "2027": 62.01,
            "2028": 73.04,
        },
    },
    {
        "institution": "长江证券",
        "report_date": "2026-05-07",
        "source_ref": "r-cjsc-20260507",
        "coverage_status": "active_at_report_date",
        "revenue_100m_cny": {
            "2026": 758.71,
            "2027": 872.51,
            "2028": 1003.39,
        },
        "parent_net_income_100m_cny": {
            "2026": 52.43,
            "2027": 60.82,
            "2028": 71.13,
        },
        "operating_cash_flow_100m_cny": {"2026": -80.72},
    },
    {
        "institution": "摩根士丹利",
        "report_date": "2026-05-18",
        "source_ref": "r-ms-20260518",
        "coverage_status": "discontinued_on_report_date",
        "coverage_note": (
            "该报告为停止覆盖时的最终模型，可用于截至当日的外部对账，"
            "但不视为仍会持续更新的活跃覆盖。"
        ),
        "revenue_100m_cny": {
            "2026": 681.30,
            "2027": 690.10,
            "2028": 718.45,
        },
        "parent_net_income_100m_cny": {
            "2026": 51.84,
            "2027": 49.36,
            "2028": 51.88,
        },
        "operating_cash_flow_100m_cny": {
            "2026": 215.57,
            "2027": 93.93,
            "2028": 90.67,
        },
        "price_target_cny": 33.27,
        "valuation": {
            "method": "DCF",
            "wacc_pct": 7.9,
            "terminal_growth_pct": 0.0,
            "forecast_horizon": "2026—2036",
        },
    },
)


def _file_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _median(
    rows: list[dict[str, Any]],
    metric: str,
    year: str,
) -> float:
    return round(
        statistics.median(
            float(row[metric][year])
            for row in rows
            if row.get(metric, {}).get(year) is not None
        ),
        2,
    )


def _difference(independent: float, benchmark: float) -> float:
    return round((independent / benchmark - 1.0) * 100.0, 2)


def _wind_consensus(snapshot: dict[str, Any]) -> dict[str, Any]:
    container = snapshot["wind"]["consensus_fy1_fy3"]["rows"]
    if not container:
        raise ValueError("Wind FY1—FY3一致预期为空")
    row = next(iter(container.values()))
    revenue = {
        year: round(float(row[f"west_sales_fy{index}"]) / 1e8, 2)
        for index, year in enumerate(YEARS, start=1)
    }
    profit = {
        year: round(float(row[f"west_netprofit_fy{index}"]) / 1e8, 2)
        for index, year in enumerate(YEARS, start=1)
    }
    eps = {
        year: round(float(row[f"west_eps_fy{index}"]), 4)
        for index, year in enumerate(YEARS, start=1)
    }
    roe = {
        year: round(float(row[f"west_avgroe_fy{index}"]), 4)
        for index, year in enumerate(YEARS, start=1)
    }
    return {
        "provider": "wind",
        "as_of_date": "2026-07-24",
        "raw_feature_names": {
            "revenue": "west_sales_fy1/west_sales_fy2/west_sales_fy3",
            "parent_net_income": (
                "west_netprofit_fy1/west_netprofit_fy2/"
                "west_netprofit_fy3"
            ),
            "eps": "west_eps_fy1/west_eps_fy2/west_eps_fy3",
            "roe": "west_avgroe_fy1/west_avgroe_fy2/west_avgroe_fy3",
        },
        "revenue_100m_cny": revenue,
        "parent_net_income_100m_cny": profit,
        "eps_cny": eps,
        "average_roe_pct": roe,
        "note": (
            "Wind一致预期是聚合基准，可能包含与本地报告相同的券商预测，"
            "因此单列对账，不与五家报告再次合并计算中位数。"
        ),
    }


def build() -> dict[str, Any]:
    model = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    wind = json.loads(WIND_PATH.read_text(encoding="utf-8"))
    rows = [
        dict(row)
        for row in REPORT_ROWS
        if date.fromisoformat(row["report_date"]) >= RECENT_REPORT_CUTOFF
    ]
    if len(rows) != len(REPORT_ROWS):
        raise ValueError("存在超出最近两个季度窗口的公司研报")
    independent = {
        metric: {
            str(item["year"]): round(float(item[field]), 2)
            for item in model["scenarios"]["基准情景"]
        }
        for metric, field in (
            ("revenue_100m_cny", "revenue_100m_cny"),
            ("parent_net_income_100m_cny", "parent_net_income_100m_cny"),
        )
    }
    median = {
        metric: {
            year: _median(rows, metric, year)
            for year in YEARS
        }
        for metric in ("revenue_100m_cny", "parent_net_income_100m_cny")
    }
    wind_consensus = _wind_consensus(wind)
    difference = {
        "revenue": {
            year: _difference(
                independent["revenue_100m_cny"][year],
                median["revenue_100m_cny"][year],
            )
            for year in YEARS
        },
        "parent_net_income": {
            year: _difference(
                independent["parent_net_income_100m_cny"][year],
                median["parent_net_income_100m_cny"][year],
            )
            for year in YEARS
        },
    }
    wind_difference = {
        "revenue": {
            year: _difference(
                independent["revenue_100m_cny"][year],
                wind_consensus["revenue_100m_cny"][year],
            )
            for year in YEARS
        },
        "parent_net_income": {
            year: _difference(
                independent["parent_net_income_100m_cny"][year],
                wind_consensus["parent_net_income_100m_cny"][year],
            )
            for year in YEARS
        },
    }
    ocf_2026 = [
        float(row["operating_cash_flow_100m_cny"]["2026"])
        for row in rows
        if row.get("operating_cash_flow_100m_cny", {}).get("2026")
        is not None
    ]
    return {
        "reconciliation_version": "run15.chint_external_reconciliation.v2",
        "as_of_date": AS_OF_DATE.isoformat(),
        "independent_model_hash": _file_hash(MODEL_PATH),
        "report_selection_policy": {
            "rule": "只使用研究截止日前最近两个季度（滚动183天）的公司研报进行当前模型对账",
            "cutoff_date": RECENT_REPORT_CUTOFF.isoformat(),
            "included_report_count": len(rows),
            "older_company_reports_used_in_current_median": 0,
            "note": (
                "更早报告只可用于解释预期变化，不进入当前预测中位数；"
                "行业报告不作为公司FY1—FY3预测样本。"
            ),
        },
        "benchmark_rows": rows,
        "benchmark_median": median,
        "wind_consensus": wind_consensus,
        "independent_model": independent,
        "difference_vs_recent_report_median_pct": difference,
        "difference_vs_wind_consensus_pct": wind_difference,
        "operating_cash_flow_2026_range_100m_cny": {
            "low": round(min(ocf_2026), 2),
            "high": round(max(ocf_2026), 2),
            "report_count_with_value": len(ocf_2026),
        },
        "interpretation": [
            (
                "独立模型收入高于五家近期报告中位数，主要来自对户用"
                "电站转让规模的较高假设；长江证券的收入路径最接近。"
            ),
            (
                "独立模型的归母净利润差异显著小于收入差异，因为新增"
                "转让收入按约7%的低毛利处理，合作运营毛利也没有外推2025年高点。"
            ),
            (
                "可取得的2026年经营现金流预测从负80.72亿元到正215.57亿元，"
                "分歧远大于净利润；核心变量是项目存货、应收、应付和交割节奏。"
            ),
            (
                "Wind一致预期单列核验，不与本地报告中位数混算，以避免同一"
                "卖方预测可能经数据商再次收录而被重复计权。"
            ),
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="构建Run15冻结独立模型与近期公司研报/Wind一致预期对账"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = build()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "report_count": len(payload["benchmark_rows"]),
                "model_hash": payload["independent_model_hash"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
