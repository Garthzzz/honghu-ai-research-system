from __future__ import annotations

"""Post-freeze external reconciliation for the lithium company models.

The independent model artifact must already exist and every per-company
input/output hash must match.  Only after that check does this module open the
current market and consensus sections of the bounded Wind/Tushare snapshot.
"""

import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "cache" / "lithium_research"
MODEL_PATH = CACHE / "models" / "lithium_company_independent_models_v1.json"
SNAPSHOT_PATH = CACHE / "lithium_financial_snapshot.json"
DEFAULT_OUTPUT = CACHE / "models" / "lithium_external_reconciliation_v1.json"
AS_OF_DATE = "2026-07-27"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _verify_freezes(model: dict[str, Any]) -> list[dict[str, str]]:
    verified = []
    for record in model["independent_freeze"]["records"]:
        for prefix in ("input", "output"):
            path = ROOT / record[f"{prefix}_path"]
            expected = record[f"{prefix}_sha256"]
            actual = _sha256_file(path)
            if actual != expected:
                raise ValueError(
                    f"独立模型冻结文件哈希不一致: {path} expected={expected} actual={actual}"
                )
        verified.append(
            {
                "company": record["company"],
                "input_sha256": record["input_sha256"],
                "output_sha256": record["output_sha256"],
            }
        )
    return verified


def _wind_consensus(snapshot: dict[str, Any]) -> dict[str, dict[int, dict[str, float | None]]]:
    result: dict[str, dict[int, dict[str, float | None]]] = {}
    for batch in snapshot["wind"]["consensus_fy1_fy3"]:
        for ticker, row in batch["rows"].items():
            result[ticker] = {}
            for offset, year in enumerate((2026, 2027, 2028), start=1):
                result[ticker][year] = {
                    "revenue_rmb_bn": (
                        _finite(row.get(f"west_sales_fy{offset}")) / 1e9
                        if _finite(row.get(f"west_sales_fy{offset}")) is not None
                        else None
                    ),
                    "net_income_rmb_bn": (
                        _finite(row.get(f"west_netprofit_fy{offset}")) / 1e9
                        if _finite(row.get(f"west_netprofit_fy{offset}")) is not None
                        else None
                    ),
                    "eps_cny": _finite(row.get(f"west_eps_fy{offset}")),
                    "roe_pct": _finite(row.get(f"west_avgroe_fy{offset}")),
                }
    return result


def _recent_broker_forecasts(
    snapshot: dict[str, Any], ticker: str
) -> dict[int, dict[str, Any]]:
    rows = (
        snapshot["tushare"]["securities"]
        .get(ticker, {})
        .get("institution_forecasts_recent_six_months", [])
    )
    # Keep only one latest published report per institution and forecast year.
    latest: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        quarter = str(row.get("quarter") or "")
        if not quarter.endswith("Q4"):
            continue
        try:
            year = int(quarter[:4])
        except ValueError:
            continue
        if year not in (2026, 2027, 2028):
            continue
        report_date = str(row.get("report_date") or "")
        if report_date < "20260127":
            continue
        org = str(row.get("org_name") or "").strip()
        if not org:
            continue
        key = (org, year)
        if key not in latest or report_date > str(latest[key].get("report_date") or ""):
            latest[key] = row

    result: dict[int, dict[str, Any]] = {}
    for year in (2026, 2027, 2028):
        year_rows = [row for (org, row_year), row in latest.items() if row_year == year]
        revenue = [
            value / 1e5
            for value in (_finite(row.get("op_rt")) for row in year_rows)
            if value is not None
        ]
        net_income = [
            value / 1e5
            for value in (_finite(row.get("np")) for row in year_rows)
            if value is not None
        ]
        eps = [
            value
            for value in (_finite(row.get("eps")) for row in year_rows)
            if value is not None
        ]
        result[year] = {
            "institution_count": len({str(row["org_name"]) for row in year_rows}),
            "institutions": sorted({str(row["org_name"]) for row in year_rows}),
            "report_date_start": min(
                (str(row["report_date"]) for row in year_rows), default=None
            ),
            "report_date_end": max(
                (str(row["report_date"]) for row in year_rows), default=None
            ),
            "revenue_rmb_bn_median": statistics.median(revenue) if revenue else None,
            "net_income_rmb_bn_median": (
                statistics.median(net_income) if net_income else None
            ),
            "eps_cny_median": statistics.median(eps) if eps else None,
            "report_count": len(year_rows),
            "constituents": [
                {
                    "institution": str(row["org_name"]),
                    "report_date": str(row.get("report_date") or ""),
                    "revenue_rmb_bn": (
                        _finite(row.get("op_rt")) / 1e5
                        if _finite(row.get("op_rt")) is not None
                        else None
                    ),
                    "net_income_rmb_bn": (
                        _finite(row.get("np")) / 1e5
                        if _finite(row.get("np")) is not None
                        else None
                    ),
                    "eps_cny": _finite(row.get("eps")),
                }
                for row in sorted(
                    year_rows,
                    key=lambda item: (
                        str(item.get("org_name") or ""),
                        str(item.get("report_date") or ""),
                    ),
                )
            ],
        }
    return result


def _pct_difference(value: float | None, benchmark: float | None) -> float | None:
    if value is None or benchmark in (None, 0):
        return None
    return (value / benchmark - 1.0) * 100.0


def build() -> dict[str, Any]:
    model = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    verified = _verify_freezes(model)
    wind_consensus = _wind_consensus(snapshot)
    companies = []
    for company in model["companies"]:
        ticker = company["ticker"]
        name = company["company"]
        current = snapshot["wind"]["current"][ticker]
        market_cap_rmb_bn = _finite(current.get("market_cap_cny"))
        if market_cap_rmb_bn is not None:
            market_cap_rmb_bn /= 10.0  # Wind snapshot stores 亿元; model uses 十亿元.
        broker = _recent_broker_forecasts(snapshot, ticker)
        base_rows = {row["year"]: row for row in company["scenarios"]["基准情景"]}
        yearly = []
        for year in (2026, 2027, 2028):
            independent = base_rows[year]
            wind = wind_consensus.get(ticker, {}).get(year, {})
            broker_row = broker[year]
            yearly.append(
                {
                    "year": year,
                    "independent": {
                        "revenue_rmb_bn": independent["revenue_rmb_bn"],
                        "net_income_rmb_bn": independent["net_income_rmb_bn"],
                        "roe_pct": independent["roe_pct"],
                    },
                    "wind_consensus": wind,
                    "recent_broker_median": broker_row,
                    "difference_vs_wind_pct": {
                        "revenue": _pct_difference(
                            independent["revenue_rmb_bn"], wind.get("revenue_rmb_bn")
                        ),
                        "net_income": _pct_difference(
                            independent["net_income_rmb_bn"],
                            wind.get("net_income_rmb_bn"),
                        ),
                        "roe": _pct_difference(independent["roe_pct"], wind.get("roe_pct")),
                    },
                    "difference_vs_recent_broker_median_pct": {
                        "revenue": _pct_difference(
                            independent["revenue_rmb_bn"],
                            broker_row["revenue_rmb_bn_median"],
                        ),
                        "net_income": _pct_difference(
                            independent["net_income_rmb_bn"],
                            broker_row["net_income_rmb_bn_median"],
                        ),
                    },
                }
            )
        equity_range = company["independent_equity_value_range"]
        low = equity_range["low_rmb_bn"]
        high = equity_range["high_rmb_bn"]
        base_fy1_profit = base_rows[2026]["net_income_rmb_bn"]
        base_fy2_profit = base_rows[2027]["net_income_rmb_bn"]
        market = {
            "trade_date": current["trade_date"],
            "price_cny": _finite(current.get("price")),
            "market_cap_rmb_bn": market_cap_rmb_bn,
            "pe_ttm": _finite(current.get("pe_ttm")),
            "pe_forward_supplier": _finite(current.get("pe_forward")),
            "pb": _finite(current.get("pb")),
            "roe_ttm_pct": _finite(current.get("roe")),
            "roa_ttm_pct": _finite(current.get("roa")),
            "independent_implied_pe_fy1": (
                market_cap_rmb_bn / base_fy1_profit
                if market_cap_rmb_bn is not None and base_fy1_profit > 0
                else None
            ),
            "independent_implied_pe_fy2": (
                market_cap_rmb_bn / base_fy2_profit
                if market_cap_rmb_bn is not None and base_fy2_profit > 0
                else None
            ),
            "market_vs_independent_range_pct": {
                "vs_low": _pct_difference(market_cap_rmb_bn, low),
                "vs_high": _pct_difference(market_cap_rmb_bn, high),
            },
        }
        wind_fy1 = wind_consensus.get(ticker, {}).get(2026, {}).get(
            "net_income_rmb_bn"
        )
        independent_fy1 = base_fy1_profit
        difference = _pct_difference(independent_fy1, wind_fy1)
        if difference is None:
            difference_summary = (
                "Wind没有形成可用FY1一致预期；本研究保留独立模型，不用缺失值反推市场共识。"
            )
        elif abs(difference) < 12:
            difference_summary = (
                f"FY1独立利润与Wind一致预期相差{difference:+.1f}%，整体接近；"
                "更重要的分歧在锂价路径、自给率和现金转换。"
            )
        elif difference > 0:
            difference_summary = (
                f"FY1独立利润高于Wind一致预期{difference:.1f}%；需要重点验证"
                "产量爬坡、自给率和单位成本，任何一项落后都会收窄差异。"
            )
        else:
            difference_summary = (
                f"FY1独立利润低于Wind一致预期{abs(difference):.1f}%；市场预测更可能"
                "采用更高锂价、更快爬坡或更强非锂利润，本研究不因对账而改写冻结输入。"
            )
        companies.append(
            {
                "company": name,
                "research_company_id": company["research_company_id"],
                "ticker": ticker,
                "freeze": company["freeze"],
                "yearly_reconciliation": yearly,
                "market_reconciliation": market,
                "difference_summary": difference_summary,
                "reconciliation_policy": (
                    "Wind为结构化一致预期主对账；Tushare逐机构预测仅使用最近两个滚动季度内"
                    "各机构最新报告，并保留机构、发布日期和预测年度，不把多份同机构报告"
                    "重复计权。英文机构与中文机构同级。"
                ),
            }
        )
    return {
        "schema_version": "lithium_external_reconciliation.v1",
        "as_of_date": AS_OF_DATE,
        "model_path": MODEL_PATH.relative_to(ROOT).as_posix(),
        "model_sha256": _sha256_file(MODEL_PATH),
        "snapshot_path": SNAPSHOT_PATH.relative_to(ROOT).as_posix(),
        "snapshot_sha256": _sha256_file(SNAPSHOT_PATH),
        "freeze_verification": verified,
        "companies": companies,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = build()
    _write_json(args.output, payload)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "companies": len(payload["companies"]),
                "model_sha256": payload["model_sha256"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
