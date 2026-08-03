"""显式抓取本次 Opportunity Lens 所需的市场、财务和分析师预期快照。

只调用项目白名单中的 Tushare / yfinance，不写 research.db 或 sentiment.db。
输出文件是 C 轨计算底稿，运行时间和 API 字段会一并保留。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PIPELINE_DIR = ROOT / "tools" / "pipeline"
if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))

from company_financial_series_utils import fetch_company_financial_series  # noqa: E402
from market_snapshot_utils import (  # noqa: E402
    fetch_company_market_snapshot,
    fetch_live_fx_rates,
)


DEFAULT_OUTPUT = (
    ROOT
    / "opportunity_lens"
    / "research_outputs"
    / "20260718_byd_luxshare_optical_module_competition_deep_run"
    / "financial_market_snapshot.json"
)

COMPANIES = {
    "innolight": {"name": "中际旭创", "ticker": "300308.SZ", "yf_symbol": "300308.SZ"},
    "eoptolink": {"name": "新易盛", "ticker": "300502.SZ", "yf_symbol": "300502.SZ"},
    "luxshare": {"name": "立讯精密", "ticker": "002475.SZ", "yf_symbol": "002475.SZ"},
    "byd": {"name": "比亚迪", "ticker": "002594.SZ", "yf_symbol": "002594.SZ"},
    "byd_electronic": {"name": "比亚迪电子", "ticker": None, "yf_symbol": "0285.HK"},
}


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if hasattr(value, "item"):
        try:
            return _jsonable(value.item())
        except Exception:
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return str(value)


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _reconcile_bps_basis_in_place(snapshot: dict[str, Any]) -> None:
    """Add a non-destructive price/PB reconciliation to cached or fresh snapshots.

    Tushare's reported-period BPS can use a pre-corporate-action share basis while
    current price and PB use the current share count.  The implied value is therefore
    an audit bridge, not a replacement observation of book value.
    """

    for company in snapshot.get("companies", {}).values():
        market = company.get("market_snapshot") or {}
        price = _finite_number(market.get("price"))
        pb = _finite_number(market.get("pb"))
        existing_reconciliation = market.get("bps_basis_reconciliation") or {}
        reported_bps = (
            _finite_number(existing_reconciliation.get("reported_bps"))
            if "reported_bps" in existing_reconciliation
            else _finite_number(market.get("bps_mrq"))
        )
        implied = price / pb if price is not None and pb not in (None, 0.0) else None
        if implied is not None:
            implied = round(implied, 6)
        relative_difference = (
            reported_bps / implied - 1.0
            if reported_bps is not None and implied not in (None, 0.0)
            else None
        )
        mismatch = (
            relative_difference is not None and abs(relative_difference) > 0.03
        )
        market_as_of = market.get("trade_date")
        reported_as_of = (
            (market.get("field_as_of") or {}).get("bps_mrq")
            or market.get("financial_metrics_as_of")
            or market.get("financials_as_of")
        )
        market["bps_current_share_basis_implied"] = implied
        market["bps_basis_reconciliation"] = {
            "status": (
                "reported_bps_missing_price_over_pb_only"
                if reported_bps is None
                else "reporting_period_share_basis_not_reconciled_to_market_pb"
                if mismatch
                else "consistent_with_current_pb_within_3pct"
            ),
            "reported_bps": reported_bps,
            "reported_bps_as_of": reported_as_of,
            "current_share_basis_bps_implied": implied,
            "current_market_as_of": market_as_of,
            "reported_to_implied_ratio": (
                round(reported_bps / implied, 6)
                if reported_bps is not None and implied not in (None, 0.0)
                else None
            ),
            "relative_difference_pct": (
                round(relative_difference * 100.0, 4)
                if relative_difference is not None
                else None
            ),
            "direct_current_pb_recalculation_allowed": bool(
                reported_bps is not None and implied is not None and not mismatch
            ),
            "provenance": (
                "同一交易日price/pb反推，仅用于股本口径对账；"
                "不是独立抓取的每股净资产，也不覆盖报告期BPS。"
            ),
            "possible_causes": (
                "送转、拆并股、回购或报告期与交易日股本口径变化；"
                "公开快照不足以自动判定具体原因。"
            ),
        }
        field_methods = market.setdefault("field_methods", {})
        field_methods["bps_current_share_basis_implied"] = {
            "extraction_method": "inferred",
            "formula": "current market price / current PB",
            "basis": "同一交易日价格与PB隐含的当前股本口径；仅用于对账",
            "inputs": {
                "price": price,
                "pb": pb,
                "market_observation_date": market_as_of,
            },
        }
        market.setdefault("field_as_of", {})[
            "bps_current_share_basis_implied"
        ] = market_as_of


def _analyst_estimates(symbol: str) -> dict[str, Any]:
    import yfinance as yf  # type: ignore

    ticker = yf.Ticker(symbol)
    result: dict[str, Any] = {
        "symbol": symbol,
        "source": "Yahoo Finance/yfinance analyst estimates",
        "limitations": (
            "分析师数量、覆盖区间和复权口径可能变化；该快照只用于构建基线范围，"
            "不等同公司指引或确定性预测。"
        ),
    }
    for key, getter in {
        "revenue_estimate": ticker.get_revenue_estimate,
        "earnings_estimate": ticker.get_earnings_estimate,
        "eps_trend": ticker.get_eps_trend,
        "growth_estimates": ticker.get_growth_estimates,
    }.items():
        try:
            frame = getter()
            result[key] = _jsonable(frame.to_dict(orient="index"))
        except Exception as exc:
            result[key] = {"error": f"{type(exc).__name__}: {str(exc)[:180]}"}
    return result


def _derive_fcf_proxy(financial_series: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for period in financial_series.get("periods", []):
        revenue = (period.get("revenue") or {}).get("cny_yi")
        ocf = (period.get("operating_cash_flow") or {}).get("cny_yi")
        capex = (period.get("capex") or {}).get("cny_yi")
        fcf = round(ocf - capex, 2) if ocf is not None and capex is not None else None
        margin = round(fcf / revenue * 100, 2) if fcf is not None and revenue not in (None, 0) else None
        rows.append(
            {
                "period": period.get("period"),
                "revenue_cny_yi": revenue,
                "operating_cash_flow_cny_yi": ocf,
                "capex_cny_yi": capex,
                "fcf_proxy_cny_yi": fcf,
                "fcf_proxy_margin_pct": margin,
                "formula": "经营活动现金流 - 购建固定资产、无形资产和其他长期资产现金支出",
                "limitations": "未调整股权激励、租赁、处置、并购及其他非标准自由现金流项目。",
            }
        )
    return rows


def collect() -> dict[str, Any]:
    fetched_at = datetime.now().astimezone().isoformat(timespec="seconds")
    fx = fetch_live_fx_rates()
    rows: dict[str, Any] = {}
    for key, company in COMPANIES.items():
        financial = fetch_company_financial_series(
            company["ticker"], yf_symbol=company["yf_symbol"], fx=fx
        )
        market = fetch_company_market_snapshot(
            company["ticker"], yf_symbol=company["yf_symbol"], fx=fx
        )
        row = {
            "name": company["name"],
            "ticker": company["ticker"],
            "yf_symbol": company["yf_symbol"],
            "financial_series": financial,
            "market_snapshot": market,
            "fcf_proxy": _derive_fcf_proxy(financial),
        }
        if key in {"innolight", "eoptolink"}:
            row["analyst_estimates"] = _analyst_estimates(company["yf_symbol"])
        rows[key] = row
    result = {
        "snapshot_version": "byd_luxshare_financial_market_snapshot.v3",
        "fetched_at": fetched_at,
        "allowed_sources": ["Tushare", "Yahoo Finance/yfinance"],
        "fx_to_cny": fx,
        "query_scope": {
            "financial_series": (
                "attempt 2018 onward annual and Q1/Q2/Q3 statements through 2026Q1; "
                "Tushare A-share statements are year-to-date cumulative, while yfinance history is source-limited"
            ),
            "financial_gap_policy": (
                "missing source periods remain null/listed in coverage.missing_periods; no interpolation; "
                "employee API values are current snapshots rather than annual history"
            ),
            "market_snapshot": "latest completed trading day at fetch time",
            "analyst_estimates": "0y/+1y revenue and EPS ranges for incumbent optical-module companies",
        },
        "companies": rows,
    }
    _reconcile_bps_basis_in_place(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--sanitize-existing",
        action="store_true",
        help="不调用外部接口；仅将现有快照中的非有限值递归归一为 null，并严格重写 JSON。",
    )
    args = parser.parse_args()
    output = args.output.resolve()
    if args.sanitize_existing:
        if not output.exists():
            raise FileNotFoundError(output)
        result = _jsonable(json.loads(output.read_text(encoding="utf-8")))
    else:
        result = collect()
    result["snapshot_version"] = "byd_luxshare_financial_market_snapshot.v3"
    _reconcile_bps_basis_in_place(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    print(f"wrote {output}")
    print(f"companies={len(result['companies'])} fetched_at={result['fetched_at']}")


if __name__ == "__main__":
    main()
