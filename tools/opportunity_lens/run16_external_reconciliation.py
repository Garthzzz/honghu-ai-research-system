from __future__ import annotations

"""Normalize Wind FY1—FY3 fields and reconcile them to the frozen run16 model.

Wind consensus is deliberately read only after the independent model is
frozen.  The tool keeps Wind and individual sell-side reports separate because
the Wind aggregate can contain the same underlying reports.
"""

import argparse
import hashlib
import json
import math
import statistics
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


YEARS = (2026, 2027, 2028)


class ReconciliationError(ValueError):
    pass


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ReconciliationError(f"{path} 不是JSON对象")
    return payload


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")


def _content_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(float(value), digits)


def _difference(independent: float | None, external: float | None) -> float | None:
    if independent is None or external is None or external == 0:
        return None
    return _round((independent / external - 1.0) * 100.0)


def _validate_consensus(
    payload: dict[str, Any], independent_path: Path, independent: dict[str, Any]
) -> None:
    if payload.get("snapshot_version") != "run16.ai_external_consensus.v1":
        raise ReconciliationError("Wind对账快照版本不正确")
    if payload.get("stage") != "external_reconciliation_after_independent_freeze":
        raise ReconciliationError("Wind对账快照并非在独立模型冻结后生成")
    freeze = payload.get("independent_freeze")
    if not isinstance(freeze, dict):
        raise ReconciliationError("Wind对账快照缺少独立模型冻结引用")
    if freeze.get("sha256") != _file_sha256(independent_path):
        raise ReconciliationError("Wind对账快照引用的独立模型文件哈希不一致")
    if freeze.get("declared_output_hash") != independent.get("output_hash"):
        raise ReconciliationError("Wind对账快照引用的独立模型内容哈希不一致")
    declared = payload.get("content_sha256")
    unhashed = deepcopy(payload)
    unhashed.pop("content_sha256", None)
    if declared != _content_sha256(unhashed):
        raise ReconciliationError("Wind对账快照内容哈希不一致")


def _profit_basis_key(report: dict[str, Any]) -> str:
    basis = str((report.get("profit") or {}).get("basis") or "").lower()
    if any(token in basis for token in ("modelware", "调整", "adjusted", "non-gaap")):
        return "adjusted_net_profit"
    if any(token in basis for token in ("归母", "归属母公司", "归属于母公司")):
        return "parent_net_profit"
    return "unspecified_net_profit_basis"


def _eps_basis_key(report: dict[str, Any]) -> str:
    eps_basis = str((report.get("eps") or {}).get("basis") or "").lower()
    if any(token in eps_basis for token in ("调整", "adjusted", "non-gaap", "modelware")):
        accounting_basis = "adjusted_eps"
    else:
        profit_basis = _profit_basis_key(report)
        accounting_basis = {
            "adjusted_net_profit": "adjusted_eps",
            "parent_net_profit": "parent_profit_eps",
            "unspecified_net_profit_basis": "unspecified_eps_basis",
        }[profit_basis]
    if any(token in eps_basis for token in ("摊薄", "稀释", "diluted")):
        return accounting_basis + "_diluted"
    if any(token in eps_basis for token in ("基本", "basic")):
        return accounting_basis + "_basic"
    return accounting_basis


def _report_benchmark(
    rows: list[dict[str, Any]], *, value_key: str, divisor: float
) -> dict[str, Any] | None:
    usable = [row for row in rows if _finite(row.get(value_key)) is not None]
    if not usable:
        return None
    values = [float(row[value_key]) / divisor for row in usable]
    observations = [
        {
            "institution": row["institution"],
            "publish_date": row["publish_date"],
            "basis": row.get("basis") or "报告未明确说明口径",
            "value": _round(float(row[value_key]) / divisor),
        }
        for row in usable
    ]
    result: dict[str, Any] = {
        "status": "same_metric_median" if len(usable) >= 2 else "single_institution_forecast",
        "sample_size": len(usable),
        "institutions": sorted({str(row["institution"]) for row in usable}),
        "publish_dates": sorted({str(row["publish_date"]) for row in usable}),
        "range_low": _round(min(values)),
        "range_high": _round(max(values)),
        "observations": observations,
    }
    if len(usable) >= 2:
        result["median"] = _round(statistics.median(values))
    else:
        result["single_forecast"] = _round(values[0])
    return result


def _report_medians_by_basis(reports: list[dict[str, Any]]) -> dict[str, Any]:
    revenue: dict[str, Any] = {}
    eps_by_basis: dict[str, Any] = {}
    profit_by_basis: dict[str, Any] = {}
    for year in YEARS:
        year_key = str(year)
        revenue_rows: list[dict[str, Any]] = []
        eps_grouped: dict[str, list[dict[str, Any]]] = {}
        grouped: dict[str, list[dict[str, Any]]] = {}
        for report in reports:
            institution = str(report.get("institution") or "未注明机构")
            publish_date = str(report.get("publish_date") or "日期未注明")
            revenue_value = _finite(((report.get("revenue") or {}).get("values") or {}).get(year_key))
            if revenue_value is not None:
                revenue_rows.append({
                    "value": revenue_value,
                    "institution": institution,
                    "publish_date": publish_date,
                    "basis": str((report.get("revenue") or {}).get("basis") or "营业收入"),
                })
            eps_value = _finite(((report.get("eps") or {}).get("values") or {}).get(year_key))
            if eps_value is not None:
                eps_grouped.setdefault(_eps_basis_key(report), []).append({
                    "value": eps_value,
                    "institution": institution,
                    "publish_date": publish_date,
                    "basis": str((report.get("eps") or {}).get("basis") or "报告所列每股收益"),
                })
            profit_value = _finite(((report.get("profit") or {}).get("values") or {}).get(year_key))
            if profit_value is not None:
                grouped.setdefault(_profit_basis_key(report), []).append({
                    "value": profit_value,
                    "institution": institution,
                    "publish_date": publish_date,
                    "basis": str((report.get("profit") or {}).get("basis") or "报告未明确说明利润口径"),
                })
        revenue_benchmark = _report_benchmark(revenue_rows, value_key="value", divisor=100.0)
        if revenue_benchmark:
            revenue[year_key] = {"unit": "亿元人民币", **revenue_benchmark}
        for basis, rows in eps_grouped.items():
            benchmark = _report_benchmark(rows, value_key="value", divisor=1.0)
            if benchmark:
                eps_by_basis.setdefault(basis, {})[year_key] = {
                    "unit": "元/股",
                    "eps_basis_group": basis,
                    **benchmark,
                }
        for basis, rows in grouped.items():
            benchmark = _report_benchmark(rows, value_key="value", divisor=100.0)
            if benchmark:
                profit_by_basis.setdefault(basis, {})[year_key] = {
                    "unit": "亿元人民币",
                    "profit_basis_group": basis,
                    **benchmark,
                }
    return {
        "revenue": revenue,
        "eps_by_basis": eps_by_basis,
        "profit_by_basis": profit_by_basis,
    }


def _sell_side_index(payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not payload:
        return {}
    companies = payload.get("companies")
    if not isinstance(companies, list):
        # 萝卜投研逐报告底稿的活动结构保留原始币种和每份报告，随后在这里
        # 仅为外部对账生成统一的“亿元/元每股”中位数视图。不同卖方利润
        # 口径不会与 Wind 合并，也不会反向改写独立模型。
        company_medians = payload.get("company_medians")
        reports = payload.get("reports")
        if not isinstance(company_medians, list) or not isinstance(reports, list):
            return {}
        companies = []
        for median_row in company_medians:
            if not isinstance(median_row, dict) or not median_row.get("ticker"):
                continue
            ticker = str(median_row["ticker"]).upper()
            metrics = median_row.get("metrics") or {}
            medians: dict[str, dict[str, Any]] = {}
            for year in YEARS:
                year_key = str(year)
                revenue = (metrics.get("revenue_rmb_mn") or {}).get(year_key) or {}
                profit = (metrics.get("parent_net_profit_rmb_mn") or {}).get(year_key) or {}
                eps = (metrics.get("eps_rmb_per_share") or {}).get(year_key) or {}
                revenue_mn = _finite(revenue.get("median"))
                profit_mn = _finite(profit.get("median"))
                medians[year_key] = {
                    "revenue_100m_cny": _round(revenue_mn / 100.0) if revenue_mn is not None else None,
                    "parent_net_income_100m_cny": _round(profit_mn / 100.0) if profit_mn is not None else None,
                    "eps_cny_per_share": _round(_finite(eps.get("median"))),
                    "sample_size": {
                        "revenue": int(revenue.get("n_nonmissing") or 0),
                        "parent_net_income": int(profit.get("n_nonmissing") or 0),
                        "eps": int(eps.get("n_nonmissing") or 0),
                    },
                    "institutions": sorted(set(
                        list(revenue.get("institutions") or [])
                        + list(profit.get("institutions") or [])
                        + list(eps.get("institutions") or [])
                    )),
                }
            report_rows = [
                deepcopy(report)
                for report in reports
                if isinstance(report, dict)
                and str(report.get("ticker") or "").upper() == ticker
            ]
            basis_medians = _report_medians_by_basis(report_rows)
            companies.append({
                "ticker": ticker,
                "name": median_row.get("company"),
                "revenue_medians": basis_medians["revenue"],
                "eps_medians_by_basis": basis_medians["eps_by_basis"],
                "profit_medians_by_basis": basis_medians["profit_by_basis"],
                "target_price": deepcopy(median_row.get("target_price")),
                "target_valuation_multiple_medians": deepcopy(
                    median_row.get("target_valuation_multiple_medians") or []
                ),
                "reports": report_rows,
                "report_count": len(report_rows),
                "profit_basis_warning": (
                    "逐份报告可能分别采用法定归母、调整后净利润或 ModelWare 口径；"
                    "本表按利润口径分别计算中位数，绝不跨口径合并，也不与 Wind 再次合并计权。"
                ),
            })
    return {
        str(row.get("ticker") or "").upper(): row
        for row in companies
        if isinstance(row, dict) and row.get("ticker")
    }


def _sell_side_period(row: dict[str, Any] | None, year: int) -> dict[str, Any] | None:
    if not row:
        return None
    year_key = str(year)
    revenue = (row.get("revenue_medians") or {}).get(year_key)
    eps = {
        basis: periods.get(year_key)
        for basis, periods in (row.get("eps_medians_by_basis") or {}).items()
        if isinstance(periods, dict) and periods.get(year_key)
    }
    profits = {
        basis: periods.get(year_key)
        for basis, periods in (row.get("profit_medians_by_basis") or {}).items()
        if isinstance(periods, dict) and periods.get(year_key)
    }
    if not revenue and not eps and not profits:
        return None
    return {
        "revenue_median": deepcopy(revenue),
        "eps_medians_by_basis": deepcopy(eps),
        "eps_basis_heterogeneous": len(eps) > 1,
        "eps_combination_policy": (
            "EPS优先按报告明确的调整后/基本/摊薄口径分组，未明确时继承该报告利润口径；"
            "同组至少两份才计算中位数，禁止跨法定与调整后口径合并。"
        ),
        "profit_medians_by_basis": deepcopy(profits),
        "profit_basis_heterogeneous": len(profits) > 1,
        "profit_combination_policy": (
            "同一利润口径至少两份报告才计算中位数；单份报告仅列单机构预测；"
            "不同利润口径并列展示范围，禁止机械合并。"
        ),
    }


def _summary(name: str, periods: list[dict[str, Any]]) -> str:
    focus = next((row for row in periods if int(row["year"]) == 2027), periods[0])
    diff = focus["difference_pct"].get("parent_net_income")
    revenue_diff = focus["difference_pct"].get("revenue")
    independent = focus["independent"]
    external = focus["external"]
    if diff is None:
        stance = "外部归母净利润缺失，不能判断独立模型相对市场的乐观或保守程度"
    elif diff >= 15:
        stance = f"独立FY2027归母净利润比Wind一致预期高{diff:.2f}%，属于明显偏乐观"
    elif diff <= -15:
        stance = f"独立FY2027归母净利润比Wind一致预期低{abs(diff):.2f}%，属于明显偏保守"
    else:
        stance = f"独立FY2027归母净利润与Wind一致预期相差{diff:.2f}%，处于15%以内"
    independent_margin = None
    external_margin = None
    if independent.get("revenue_100m_cny"):
        independent_margin = independent.get("parent_net_income_100m_cny") / independent["revenue_100m_cny"] * 100
    if external.get("revenue_100m_cny"):
        external_margin = external.get("parent_net_income_100m_cny") / external["revenue_100m_cny"] * 100
    cause_bits = []
    if revenue_diff is not None and abs(revenue_diff) >= 10:
        cause_bits.append(
            f"收入假设相差{revenue_diff:.2f}%"
        )
    if independent_margin is not None and external_margin is not None and abs(independent_margin - external_margin) >= 1:
        cause_bits.append(
            f"独立净利率{independent_margin:.2f}%、外部净利率{external_margin:.2f}%"
        )
    cause = "；主要差异来自" + "、".join(cause_bits) if cause_bits else "；收入和利润率没有出现单一的极端差异源"
    return f"{name}{stance}{cause}。这项差异需要用后续订单、收入确认、毛利率和现金流验证，不能因为接近或背离市场就自动修改独立模型。"


def build(
    independent_path: Path,
    consensus_paths: Iterable[Path],
    sell_side_path: Path | None = None,
) -> dict[str, Any]:
    independent = _read(independent_path)
    if independent.get("independent_before_consensus") is not True:
        raise ReconciliationError("输入不是独立预测冻结文件")
    consensus_payloads = [_read(path) for path in consensus_paths]
    if not consensus_payloads:
        raise ReconciliationError("至少需要一个Wind一致预期快照")
    for payload in consensus_payloads:
        _validate_consensus(payload, independent_path, independent)

    universe: list[dict[str, Any]] = []
    wind_rows: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    for payload in consensus_payloads:
        rows = payload.get("wind", {}).get("consensus", {})
        if not isinstance(rows, dict):
            raise ReconciliationError("Wind一致预期快照缺少证券数据")
        for identity in payload.get("universe", []):
            ticker = str(identity.get("ticker") or "").upper()
            if not ticker or ticker in seen:
                raise ReconciliationError(f"证券身份缺失或重复：{ticker}")
            seen.add(ticker)
            universe.append(deepcopy(identity))
            wind_rows[ticker] = deepcopy(rows.get(ticker, {}))
    if seen != set(independent.get("companies", {})):
        raise ReconciliationError(
            f"对账证券覆盖与独立模型不一致：缺少{sorted(set(independent.get('companies', {})) - seen)}"
        )

    sell_side = _read(sell_side_path) if sell_side_path and sell_side_path.is_file() else None
    sell_side_by_ticker = _sell_side_index(sell_side)
    reconciliations = []
    for identity in universe:
        ticker = str(identity["ticker"]).upper()
        company = independent["companies"][ticker]
        wind = wind_rows[ticker]
        periods = []
        missing: list[str] = []
        market = company["baseline"].get("market", {})
        market_cap = _finite(market.get("market_cap_100m_cny"))
        close = _finite(market.get("close_cny"))
        shares_100m = market_cap / close if market_cap and close else None
        for index, year in enumerate(YEARS, start=1):
            internal = company["scenarios"]["base"][str(year)]
            revenue = _finite(wind.get(f"WEST_SALES_FY{index}"))
            profit = _finite(wind.get(f"WEST_NETPROFIT_FY{index}"))
            eps = _finite(wind.get(f"WEST_EPS_FY{index}"))
            roe = _finite(wind.get(f"WEST_AVGROE_FY{index}"))
            external = {
                "revenue_100m_cny": _round(revenue / 1e8) if revenue is not None else None,
                "parent_net_income_100m_cny": _round(profit / 1e8) if profit is not None else None,
                "eps_cny_per_share": _round(eps),
                "roe_pct": _round(roe),
                "provider": "Wind一致预期",
                "raw_fields": {
                    "revenue": f"WEST_SALES_FY{index}",
                    "parent_net_income": f"WEST_NETPROFIT_FY{index}",
                    "eps": f"WEST_EPS_FY{index}",
                    "roe": f"WEST_AVGROE_FY{index}",
                },
            }
            independent_row = {
                "revenue_100m_cny": internal["revenue_100m_cny"],
                "parent_net_income_100m_cny": internal["parent_net_income_100m_cny"],
                "eps_cny_per_share": _round(internal["parent_net_income_100m_cny"] / shares_100m) if shares_100m else None,
                "roe_pct": internal["roe_pct"],
            }
            for metric in ("revenue_100m_cny", "parent_net_income_100m_cny", "roe_pct"):
                if external[metric] is None:
                    missing.append(f"FY{year} {metric}")
            sell_period = _sell_side_period(sell_side_by_ticker.get(ticker), year)
            periods.append({
                "year": year,
                "independent": independent_row,
                "external": external,
                "difference_pct": {
                    "revenue": _difference(independent_row["revenue_100m_cny"], external["revenue_100m_cny"]),
                    "parent_net_income": _difference(independent_row["parent_net_income_100m_cny"], external["parent_net_income_100m_cny"]),
                    "eps": _difference(independent_row["eps_cny_per_share"], external["eps_cny_per_share"]),
                    "roe": _difference(independent_row["roe_pct"], external["roe_pct"]),
                },
                "sell_side_report_median": deepcopy(sell_period),
            })
        report_row = sell_side_by_ticker.get(ticker)
        if report_row:
            report_gap = "卖方逐报告中位数单列展示，未与可能重复收录底层报告的Wind一致预期合并。"
        elif sell_side_path:
            report_gap = "近期卖方报告没有形成可复算中位数；只使用Wind一致预期做外部对账。"
        else:
            report_gap = "逐报告预测正在单独提取；当前只用Wind一致预期对账，不把报告标题当预测数值。"
        data_gap = (
            ("Wind缺失：" + "、".join(missing) + "。") if missing else "Wind FY2026—FY2028收入、归母净利润、EPS和ROE字段完整。"
        ) + report_gap
        reconciliations.append({
            "ticker": ticker,
            "name": company["name"],
            "company_id": company.get("company_id"),
            "status": "reconciled" if not missing else "partially_reconciled",
            "periods": periods,
            "summary_zh": _summary(company["name"], periods),
            "data_gap_zh": data_gap,
            "external_sources_kept_separate": True,
            "sell_side_report_audit": deepcopy(report_row),
        })

    payload: dict[str, Any] = {
        "snapshot_version": "run16.ai_external_consensus.v1",
        "stage": "external_reconciliation_after_independent_freeze",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "trade_date": consensus_payloads[0].get("trade_date"),
        "universe": universe,
        "independent_freeze": {
            "path": str(independent_path).replace("\\", "/"),
            "sha256": _file_sha256(independent_path),
            "declared_output_hash": independent.get("output_hash"),
        },
        "request_audit": {
            "security_count": len(universe),
            "fields_per_security": 12,
            "estimated_observations": len(universe) * 12,
            "purpose": "独立模型冻结后的Wind FY1—FY3外部对账；逐报告预测保持独立层",
            "consensus_snapshot_files": [
                {"path": str(path).replace("\\", "/"), "sha256": _file_sha256(path)}
                for path in consensus_paths
            ],
            "sell_side_workpaper": (
                {
                    "path": str(sell_side_path).replace("\\", "/"),
                    "sha256": _file_sha256(sell_side_path),
                    "schema_version": sell_side.get("schema_version") if sell_side else None,
                    "report_count": sell_side.get("report_count") if sell_side else None,
                    "company_count": sell_side.get("company_count") if sell_side else None,
                    "research_cutoff": sell_side.get("research_cutoff") if sell_side else None,
                    "eligible_date_range": deepcopy(sell_side.get("eligible_date_range")) if sell_side else None,
                    "excluded_record_count": len(sell_side.get("excluded_from_forecast_sample") or []) if sell_side else 0,
                    "excluded_records": deepcopy(sell_side.get("excluded_from_forecast_sample") or []) if sell_side else [],
                    "independence_note": (
                        "Wind一致预期可能收录相同底层卖方报告；两条外部基准只并列展示，禁止合并计权。"
                    ),
                }
                if sell_side_path and sell_side is not None
                else None
            ),
        },
        "units": {
            "revenue": "亿元人民币",
            "parent_net_income": "亿元人民币",
            "eps": "元/股",
            "roe": "%",
        },
        "wind": {"consensus": wind_rows},
        "reconciliations": reconciliations,
        "method_note_zh": (
            "差异＝独立预测÷外部预测−1。Wind原始收入和归母净利润字段从元换算为亿元；"
            "EPS和ROE保留原单位。Wind一致预期与逐份卖方报告可能重叠，因此只并列、"
            "不再次合并计权；外部数据用于对账，不反向改写已冻结独立模型。"
        ),
    }
    payload["content_sha256"] = _content_sha256(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--independent", type=Path, required=True)
    parser.add_argument("--consensus", type=Path, action="append", required=True)
    parser.add_argument("--sell-side", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = build(
        args.independent.resolve(),
        [path.resolve() for path in args.consensus],
        args.sell_side.resolve() if args.sell_side else None,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output.resolve()),
        "company_count": len(payload["reconciliations"]),
        "partial_count": sum(row["status"] != "reconciled" for row in payload["reconciliations"]),
        "sha256": payload["content_sha256"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
