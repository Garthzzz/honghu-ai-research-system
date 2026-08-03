from __future__ import annotations

"""Independent financial, valuation and portfolio engine for Opportunity Lens.

The engine is deliberately isolated from every live database and from external
consensus data.  It accepts one or more ``actual_before_consensus`` snapshots
created by :mod:`tools.opportunity_lens.run16_financial_snapshot` plus an
explicit research-assumption ledger.  Every future input must carry its unit,
basis, date, source reference and rationale.

The output is a frozen, hash-addressed artifact that can later be supplied to
the snapshot collector's ``consensus`` stage for external reconciliation.
"""

import argparse
import hashlib
import json
import math
import statistics
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


FORECAST_YEARS = (2026, 2027, 2028)
SCENARIOS = ("downside", "base", "upside")
REQUIRED_FORECAST_METRICS = (
    "revenue_growth_pct",
    "gross_margin_pct",
    "parent_net_margin_pct",
    "ocf_margin_pct",
    "capex_margin_pct",
    "total_assets_growth_pct",
    "dividend_payout_pct",
    "buyback_100m_cny",
    "other_equity_change_100m_cny",
)
ALLOWED_BASIS_TYPES = {"actual", "guidance", "internal_estimate", "implied"}
PORTFOLIO_TYPES = ("concentrated", "balanced", "risk_diversified")
CORRELATION_WINDOWS = (60, 120, 245)
PUBLIC_WEIGHT_DECIMALS = 2
RANK_TIE_TOLERANCE_PCT = 0.005
PORTFOLIO_SCORE_KEYS = (
    "direction_score",
    "quality_score",
    "evidence_score",
    "valuation_score",
    "risk_score",
)


class ModelContractError(ValueError):
    """Raised when an input would make the model unauditable."""


def _finite(value: Any, label: str) -> float:
    if value is None or isinstance(value, bool):
        raise ModelContractError(f"{label} 缺少有限数值")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ModelContractError(f"{label} 不是数值: {value!r}") from exc
    if not math.isfinite(number):
        raise ModelContractError(f"{label} 不是有限数值")
    return number


def _optional_finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(float(value), digits)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _contains_forbidden_consensus_key(value: Any, path: str = "") -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            lowered = str(key).lower()
            if (
                lowered != "independent_before_consensus"
                and ("consensus" in lowered or lowered.startswith("west_"))
            ):
                return child_path
            found = _contains_forbidden_consensus_key(child, child_path)
            if found:
                return found
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found = _contains_forbidden_consensus_key(child, f"{path}[{index}]")
            if found:
                return found
    return None


def _annotated(
    value: Any,
    label: str,
    *,
    allowed_units: set[str] | None = None,
    minimum: float | None = None,
    maximum: float | None = None,
) -> tuple[float, dict[str, Any]]:
    if not isinstance(value, dict):
        raise ModelContractError(f"{label} 必须是带依据的输入对象")
    required = ("value", "unit", "basis_type", "as_of", "source_ref", "rationale")
    missing = [field for field in required if value.get(field) in (None, "")]
    if missing:
        raise ModelContractError(f"{label} 缺少依据字段: {missing}")
    basis = str(value["basis_type"])
    if basis not in ALLOWED_BASIS_TYPES:
        raise ModelContractError(f"{label}.basis_type 不允许: {basis}")
    unit = str(value["unit"])
    if allowed_units is not None and unit not in allowed_units:
        raise ModelContractError(f"{label}.unit={unit!r} 不在 {sorted(allowed_units)}")
    number = _finite(value["value"], f"{label}.value")
    if minimum is not None and number < minimum:
        raise ModelContractError(f"{label}={number} 低于下限 {minimum}")
    if maximum is not None and number > maximum:
        raise ModelContractError(f"{label}={number} 高于上限 {maximum}")
    return number, deepcopy(value)


def _load_actual_snapshots(paths: Iterable[Path]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    securities: dict[str, Any] = {}
    audit: list[dict[str, Any]] = []
    for path in paths:
        payload = _load_json(path)
        if payload.get("stage") != "actual_before_consensus":
            raise ModelContractError(f"{path} 不是 actual_before_consensus 快照")
        if payload.get("request_audit", {}).get("consensus_fields_read") not in (None, []):
            raise ModelContractError(f"{path} 声明读取过一致预期字段")
        wind = payload.get("wind")
        if not isinstance(wind, dict) or "consensus" in wind:
            raise ModelContractError(f"{path} 包含外部一致预期数据")
        declared = payload.get("content_sha256")
        if declared:
            unhashed = dict(payload)
            unhashed.pop("content_sha256", None)
            if declared != _sha256(unhashed):
                raise ModelContractError(f"{path} 内容哈希校验失败")
        universe = payload.get("universe")
        if not isinstance(universe, list):
            raise ModelContractError(f"{path} 缺少 universe")
        current = wind.get("current", {})
        reported = wind.get("reported", {})
        prices = wind.get("price_history", {})
        for row in universe:
            ticker = str(row.get("ticker") or "").strip().upper()
            if not ticker:
                raise ModelContractError(f"{path} universe 含空 ticker")
            if ticker in securities:
                raise ModelContractError(f"多个快照重复证券 {ticker}")
            field_keys = {
                str(key).upper()
                for values in reported.values()
                for key in (values.get(ticker, {}) if isinstance(values, dict) else {})
            }
            if any(key.startswith("WEST_") for key in field_keys):
                raise ModelContractError(f"{path} 的 {ticker} 含 Wind 一致预期字段")
            securities[ticker] = {
                "identity": deepcopy(row),
                "trade_date": payload.get("trade_date"),
                "current": deepcopy(current.get(ticker, {})),
                "reported": {
                    str(period): deepcopy(rows.get(ticker, {}))
                    for period, rows in reported.items()
                    if isinstance(rows, dict)
                },
                "prices": deepcopy(prices.get(ticker, [])),
            }
        audit.append(
            {
                "path": str(path),
                "file_sha256": _file_sha256(path),
                "declared_content_sha256": declared,
                "trade_date": payload.get("trade_date"),
                "security_count": len(universe),
            }
        )
    if not securities:
        raise ModelContractError("至少需要一个 actual snapshot")
    return securities, audit


def _merge_parent_equity_snapshot(
    securities: dict[str, Any], path: Path
) -> dict[str, Any]:
    """Attach parent-company equity without changing the Wind actual snapshot.

    Wind ``TOT_EQUITY`` includes minority interests and therefore cannot be
    paired with parent-company net profit for ROE or PB--ROE.  The narrow
    Tushare fallback contains ``total_hldr_eqy_exc_min_int`` and is merged only
    for that missing field, period by period.
    """

    payload = _load_json(path)
    if payload.get("artifact_version") != "run16.parent_equity_tushare.v1":
        raise ModelContractError(f"{path} 不是 Run16 归母权益窄字段快照")
    by_ticker = payload.get("by_ticker")
    if not isinstance(by_ticker, dict):
        raise ModelContractError(f"{path} 缺少 by_ticker")
    missing: list[str] = []
    for ticker, security in securities.items():
        rows = by_ticker.get(ticker)
        if not isinstance(rows, dict):
            missing.append(ticker)
            continue
        for period, report in security.get("reported", {}).items():
            fallback = rows.get(str(period))
            if not isinstance(fallback, dict):
                continue
            value = _optional_finite(fallback.get("total_hldr_eqy_exc_min_int"))
            if value is not None and value > 0:
                report["PARENT_EQUITY"] = value
                report["PARENT_EQUITY_PROVIDER"] = "Tushare"
                report["PARENT_EQUITY_RAW_FEATURE"] = (
                    "balancesheet.total_hldr_eqy_exc_min_int"
                )
        annual = security.get("reported", {}).get("20251231", {})
        if _optional_finite(annual.get("PARENT_EQUITY")) is None:
            missing.append(ticker)
    if missing:
        raise ModelContractError(
            "归母权益窄字段快照未覆盖 FY2025: " + ", ".join(sorted(set(missing)))
        )
    return {
        "path": str(path),
        "file_sha256": _file_sha256(path),
        "provider": "Tushare",
        "raw_feature_name": "balancesheet.total_hldr_eqy_exc_min_int",
        "security_count": len(securities),
    }


def _roe_stability(security: Mapping[str, Any]) -> dict[str, Any]:
    observations: list[dict[str, Any]] = []
    for period, row in sorted(security.get("reported", {}).items()):
        if not str(period).endswith("1231") or not str(period)[:4].isdigit():
            continue
        year = int(str(period)[:4])
        if not 2021 <= year <= 2025:
            continue
        value = _optional_finite(row.get("ROE"))
        if value is not None:
            observations.append({"period": str(period), "roe_pct": value})
    values = [float(row["roe_pct"]) for row in observations]
    result: dict[str, Any] = {
        "observations": observations,
        "rule": "至少5个完整年度、ROE均为正、极差不超过5个百分点、变异系数不超过0.25",
        "passed": False,
    }
    if len(values) < 5:
        result["reason"] = "完整年度ROE不足5个"
        return result
    mean = statistics.fmean(values)
    roe_range = max(values) - min(values)
    cv = statistics.pstdev(values) / abs(mean) if mean else float("inf")
    result.update(
        {
            "mean_pct": _round(mean),
            "min_pct": _round(min(values)),
            "max_pct": _round(max(values)),
            "range_pp": _round(roe_range),
            "coefficient_of_variation": _round(cv, 4),
        }
    )
    result["passed"] = bool(
        all(value > 0 for value in values) and roe_range <= 5.0 and cv <= 0.25
    )
    result["reason"] = (
        "量化稳定性门槛通过"
        if result["passed"]
        else "历史ROE存在负值、极差超过5个百分点或变异系数超过0.25"
    )
    return result


def _amount_100m(row: Mapping[str, Any], field: str, label: str) -> float:
    raw = _finite(row.get(field), label)
    return raw / 1e8


def _actual_baseline(security: Mapping[str, Any]) -> dict[str, Any]:
    report = security.get("reported", {}).get("20251231")
    if not isinstance(report, dict):
        raise ModelContractError(
            f"{security['identity'].get('ticker')} 缺少 2025-12-31 年度事实基线"
        )
    baseline = {
        "period": "FY2025",
        "revenue_100m_cny": _amount_100m(report, "OPER_REV", "OPER_REV"),
        "parent_net_income_100m_cny": _amount_100m(
            report, "NP_BELONGTO_PARCOMSH", "NP_BELONGTO_PARCOMSH"
        ),
        "ocf_100m_cny": _amount_100m(
            report, "NET_CASH_FLOWS_OPER_ACT", "NET_CASH_FLOWS_OPER_ACT"
        ),
        "capex_100m_cny": abs(
            _amount_100m(report, "CASH_PAY_ACQ_CONST_FIOLTA", "CASH_PAY_ACQ_CONST_FIOLTA")
        ),
        "total_assets_100m_cny": _amount_100m(report, "TOT_ASSETS", "TOT_ASSETS"),
        "parent_equity_100m_cny": _amount_100m(
            report, "PARENT_EQUITY", "PARENT_EQUITY"
        ),
        "gross_margin_pct": _optional_finite(report.get("GROSSPROFITMARGIN")),
        "net_margin_pct": _optional_finite(report.get("NETPROFITMARGIN")),
        "source_role": "actual",
        "source_provider": "mixed",
        "field_providers": {
            "revenue_100m_cny": "Wind HTTP proxy",
            "parent_net_income_100m_cny": "Wind HTTP proxy",
            "ocf_100m_cny": "Wind HTTP proxy",
            "capex_100m_cny": "Wind HTTP proxy",
            "total_assets_100m_cny": "Wind HTTP proxy",
            "gross_margin_pct": "Wind HTTP proxy",
            "net_margin_pct": "Wind HTTP proxy",
            "parent_equity_100m_cny": str(
                report.get("PARENT_EQUITY_PROVIDER") or "field-level fallback"
            ),
        },
        "field_raw_features": {
            "parent_equity_100m_cny": str(
                report.get("PARENT_EQUITY_RAW_FEATURE")
                or "balancesheet.total_hldr_eqy_exc_min_int"
            )
        },
    }
    q1 = security.get("reported", {}).get("20260331")
    if isinstance(q1, dict):
        baseline["current_year_q1_checkpoint"] = {
            "period": "2026Q1",
            "revenue_100m_cny": _amount_100m(q1, "OPER_REV", "2026Q1.OPER_REV"),
            "parent_net_income_100m_cny": _amount_100m(
                q1, "NP_BELONGTO_PARCOMSH", "2026Q1.NP_BELONGTO_PARCOMSH"
            ),
            "ocf_100m_cny": _amount_100m(
                q1, "NET_CASH_FLOWS_OPER_ACT", "2026Q1.NET_CASH_FLOWS_OPER_ACT"
            ),
            "capex_100m_cny": abs(
                _amount_100m(
                    q1,
                    "CASH_PAY_ACQ_CONST_FIOLTA",
                    "2026Q1.CASH_PAY_ACQ_CONST_FIOLTA",
                )
            ),
            "parent_equity_100m_cny": (
                _amount_100m(q1, "PARENT_EQUITY", "2026Q1.PARENT_EQUITY")
                if _optional_finite(q1.get("PARENT_EQUITY")) is not None
                else None
            ),
            "total_assets_100m_cny": _amount_100m(
                q1, "TOT_ASSETS", "2026Q1.TOT_ASSETS"
            ),
            "source_role": "actual",
            "source_provider": "mixed",
            "field_providers": {
                "revenue_100m_cny": "Wind HTTP proxy",
                "parent_net_income_100m_cny": "Wind HTTP proxy",
                "ocf_100m_cny": "Wind HTTP proxy",
                "capex_100m_cny": "Wind HTTP proxy",
                "total_assets_100m_cny": "Wind HTTP proxy",
                "parent_equity_100m_cny": str(
                    q1.get("PARENT_EQUITY_PROVIDER") or "field-level fallback"
                ),
            },
            "field_raw_features": {
                "parent_equity_100m_cny": str(
                    q1.get("PARENT_EQUITY_RAW_FEATURE")
                    or "balancesheet.total_hldr_eqy_exc_min_int"
                )
            },
        }
    if baseline["revenue_100m_cny"] <= 0:
        raise ModelContractError("FY2025 收入必须为正")
    if baseline["total_assets_100m_cny"] <= 0 or baseline["parent_equity_100m_cny"] <= 0:
        raise ModelContractError("FY2025 总资产和权益基线必须为正")
    current = security.get("current", {})
    baseline["market"] = {
        "trade_date": security.get("trade_date"),
        "close_cny": _optional_finite(current.get("CLOSE")),
        "market_cap_100m_cny": (
            _optional_finite(current.get("MKT_CAP_ARD")) / 1e8
            if _optional_finite(current.get("MKT_CAP_ARD")) is not None
            else None
        ),
        "free_float_market_cap_100m_cny": _optional_finite(
            current.get("FREE_FLOAT_MARKET_CAP_CNY_100M")
        ),
        "pe_ttm": _optional_finite(current.get("PE_TTM")),
        "pb_lf": _optional_finite(current.get("PB_LF")),
    }
    return baseline


def _apply_normalization_overrides(
    ticker: str,
    baseline: Mapping[str, Any],
    raw_overrides: Any,
) -> dict[str, Any]:
    """Apply explicit non-GAAP research normalization without erasing actuals."""

    result = deepcopy(dict(baseline))
    result["reported_actual_before_normalization"] = {
        key: value
        for key, value in baseline.items()
        if key.endswith("_100m_cny") and not key.startswith("market")
    }
    result["normalization_adjustments"] = []
    if isinstance(result.get("current_year_q1_checkpoint"), dict):
        result["reported_q1_actual_before_normalization"] = deepcopy(
            result["current_year_q1_checkpoint"]
        )
    if raw_overrides in (None, {}):
        result["normalization_status"] = "未调整；预测利润率仍须由显式独立假设给出"
        return result
    if not isinstance(raw_overrides, dict):
        raise ModelContractError(f"{ticker}.normalization_overrides 必须是对象")
    allowed = {
        "parent_equity_100m_cny",
        "parent_net_income_100m_cny",
        "ocf_100m_cny",
        "capex_100m_cny",
        "q1_2026_parent_net_income_100m_cny",
        "q1_2026_ocf_100m_cny",
        "q1_2026_capex_100m_cny",
    }
    unknown = set(raw_overrides) - allowed
    if unknown:
        raise ModelContractError(f"{ticker}.normalization_overrides 含不允许字段: {sorted(unknown)}")
    for metric, item in raw_overrides.items():
        if not isinstance(item, dict):
            raise ModelContractError(f"{ticker}.normalization_overrides.{metric} 必须是对象")
        if not str(item.get("affected_reported_item") or "").strip():
            raise ModelContractError(
                f"{ticker}.normalization_overrides.{metric} 缺少 affected_reported_item"
            )
        if not str(item.get("adjustment_reason") or "").strip():
            raise ModelContractError(
                f"{ticker}.normalization_overrides.{metric} 缺少 adjustment_reason"
            )
        number, ledger = _annotated(
            item,
            f"{ticker}.normalization_overrides.{metric}",
            allowed_units={"亿元人民币"},
        )
        if metric.startswith("q1_2026_"):
            checkpoint = result.get("current_year_q1_checkpoint")
            if not isinstance(checkpoint, dict):
                raise ModelContractError(f"{ticker} 缺少2026Q1事实，不能应用 {metric} 调整")
            target_metric = metric.removeprefix("q1_2026_")
            reported = checkpoint[target_metric]
            checkpoint[target_metric] = number
            period = "2026Q1"
        else:
            reported = result[metric]
            result[metric] = number
            target_metric = metric
            period = "FY2025"
        result["normalization_adjustments"].append(
            {
                "metric": metric,
                "target_metric": target_metric,
                "period": period,
                "reported_value_100m_cny": _round(float(reported)),
                "normalized_value_100m_cny": _round(number),
                "adjustment_100m_cny": _round(number - float(reported)),
                "affected_reported_item": item["affected_reported_item"],
                "adjustment_reason": item["adjustment_reason"],
                "ledger": ledger,
                "warning": "研究正常化口径不改写公司公告事实，也不进入供应商actual层。",
            }
        )
    result["normalization_status"] = "已按显式研究依据形成正常化基线；原始公告值完整保留"
    return result


def _parse_forecast_inputs(company: Mapping[str, Any]) -> dict[str, Any]:
    compact = company.get("forecast_assumptions")
    if compact is not None:
        if not isinstance(compact, dict) or set(compact) != set(REQUIRED_FORECAST_METRICS):
            raise ModelContractError(
                f"{company.get('ticker')}.forecast_assumptions 必须且只能包含全部9项预测指标"
            )
        parsed: dict[str, Any] = {scenario: {} for scenario in SCENARIOS}
        for scenario in SCENARIOS:
            for year in FORECAST_YEARS:
                parsed[scenario][year] = {}
        for metric, series in compact.items():
            if not isinstance(series, dict):
                raise ModelContractError(f"{company.get('ticker')}.{metric} 必须是带依据的序列对象")
            values = series.get("values")
            if not isinstance(values, dict) or set(values) != set(SCENARIOS):
                raise ModelContractError(
                    f"{company.get('ticker')}.{metric}.values 必须且只能包含 {SCENARIOS}"
                )
            ledger_base = {key: deepcopy(value) for key, value in series.items() if key != "values"}
            allowed_units = {"%"} if metric.endswith("_pct") else {"亿元人民币"}
            for scenario in SCENARIOS:
                yearly = values[scenario]
                if not isinstance(yearly, dict):
                    raise ModelContractError(f"{company.get('ticker')}.{metric}.{scenario} 不是年度对象")
                for year in FORECAST_YEARS:
                    raw = yearly.get(str(year), yearly.get(year))
                    item = {**deepcopy(ledger_base), "value": raw}
                    number, ledger = _annotated(
                        item,
                        f"{company.get('ticker')}.{metric}.{scenario}.{year}",
                        allowed_units=allowed_units,
                        minimum=-100.0 if metric.endswith("_pct") else None,
                        maximum=(
                            500.0
                            if metric in {"revenue_growth_pct", "total_assets_growth_pct"}
                            else 100.0 if metric.endswith("_pct") else None
                        ),
                    )
                    parsed[scenario][year][metric] = {"value": number, "ledger": ledger}
        for scenario in SCENARIOS:
            for year in FORECAST_YEARS:
                row = parsed[scenario][year]
                for metric in (
                    "gross_margin_pct",
                    "parent_net_margin_pct",
                    "ocf_margin_pct",
                    "capex_margin_pct",
                    "dividend_payout_pct",
                ):
                    if not -50.0 <= row[metric]["value"] <= 100.0:
                        raise ModelContractError(
                            f"{company.get('ticker')}.{scenario}.{year}.{metric} 超出可审计范围"
                        )
                if row["capex_margin_pct"]["value"] < 0:
                    raise ModelContractError("capex_margin_pct 不能为负")
                if not 0 <= row["dividend_payout_pct"]["value"] <= 100:
                    raise ModelContractError("dividend_payout_pct 必须在 0%—100%")
        return parsed

    scenarios = company.get("scenarios")
    if not isinstance(scenarios, dict) or set(scenarios) != set(SCENARIOS):
        raise ModelContractError(
            f"{company.get('ticker')} scenarios 必须且只能包含 {SCENARIOS}"
        )
    parsed: dict[str, Any] = {}
    for scenario in SCENARIOS:
        yearly = scenarios[scenario]
        if not isinstance(yearly, dict):
            raise ModelContractError(f"{company.get('ticker')}.{scenario} 不是年度对象")
        parsed[scenario] = {}
        for year in FORECAST_YEARS:
            values = yearly.get(str(year), yearly.get(year))
            if not isinstance(values, dict):
                raise ModelContractError(f"{company.get('ticker')}.{scenario}.{year} 缺失")
            parsed_values: dict[str, Any] = {}
            for metric in REQUIRED_FORECAST_METRICS:
                allowed_units = {"%"} if metric.endswith("_pct") else {"亿元人民币"}
                lower, upper = (
                    (-100.0, 500.0)
                    if metric in {"revenue_growth_pct", "total_assets_growth_pct"}
                    else (-100.0, 100.0) if metric.endswith("_pct") else (None, None)
                )
                number, ledger = _annotated(
                    values.get(metric),
                    f"{company.get('ticker')}.{scenario}.{year}.{metric}",
                    allowed_units=allowed_units,
                    minimum=lower,
                    maximum=upper,
                )
                parsed_values[metric] = {"value": number, "ledger": ledger}
            for metric in (
                "gross_margin_pct",
                "parent_net_margin_pct",
                "ocf_margin_pct",
                "capex_margin_pct",
                "dividend_payout_pct",
            ):
                value = parsed_values[metric]["value"]
                if not -50.0 <= value <= 100.0:
                    raise ModelContractError(
                        f"{company.get('ticker')}.{scenario}.{year}.{metric} 超出可审计范围"
                    )
            if parsed_values["capex_margin_pct"]["value"] < 0:
                raise ModelContractError("capex_margin_pct 不能为负")
            if not 0 <= parsed_values["dividend_payout_pct"]["value"] <= 100:
                raise ModelContractError("dividend_payout_pct 必须在 0%—100%")
            parsed[scenario][year] = parsed_values
    return parsed


def _build_scenario(
    ticker: str,
    baseline: Mapping[str, Any],
    inputs: Mapping[int, Mapping[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    previous_revenue = float(baseline["revenue_100m_cny"])
    previous_net_income = float(baseline["parent_net_income_100m_cny"])
    previous_equity = float(baseline["parent_equity_100m_cny"])
    previous_assets = float(baseline["total_assets_100m_cny"])
    outputs: dict[str, Any] = {}
    formulas: list[dict[str, Any]] = []
    for year in FORECAST_YEARS:
        row = inputs[year]
        get = lambda metric: float(row[metric]["value"])
        revenue = previous_revenue * (1.0 + get("revenue_growth_pct") / 100.0)
        if revenue <= 0:
            raise ModelContractError(f"{ticker}.{year} 收入增速使预测收入非正")
        gross_profit = revenue * get("gross_margin_pct") / 100.0
        net_income = revenue * get("parent_net_margin_pct") / 100.0
        ocf = revenue * get("ocf_margin_pct") / 100.0
        capex = revenue * get("capex_margin_pct") / 100.0
        if capex < 0:
            raise ModelContractError(f"{ticker}.{year} 资本开支不能为负")
        fcf = ocf - capex
        # The distribution paid in forecast year t is tied to prior-year
        # earnings, not to earnings that will normally be declared after the
        # current balance-sheet date.  For the 2026 Q1 bridge this is the
        # research estimate of FY2025 profit distributed after Q1; for later
        # years it is the preceding modeled year's profit.
        dividend_base_net_income = previous_net_income
        dividends = (
            max(dividend_base_net_income, 0.0)
            * get("dividend_payout_pct")
            / 100.0
        )
        buyback = get("buyback_100m_cny")
        other_equity = get("other_equity_change_100m_cny")
        equity_bridge_opening = previous_equity
        equity_profit_contribution = net_income
        equity_bridge_note = (
            "全年桥：上年末归母权益加本年归母净利润，扣除按上年归母净利润估算的本年支付分红和回购，"
            "再加其他权益变动"
        )
        if year == 2026:
            q1_checkpoint = baseline.get("current_year_q1_checkpoint")
            if isinstance(q1_checkpoint, Mapping):
                q1_equity = _optional_finite(q1_checkpoint.get("parent_equity_100m_cny"))
                q1_net_income = _optional_finite(q1_checkpoint.get("parent_net_income_100m_cny"))
                if q1_equity is not None and q1_equity > 0 and q1_net_income is not None:
                    # FY2025→2026Q1 已披露的分红、增发、OCI及其他权益变化已经
                    # 反映在Q1归母权益中。以Q1为桥接锚，仅加入剩余三个季度的
                    # 预测利润，避免把已知权益变化机械设为零。这里的分红/回购
                    # 假设解释为Q1之后的研究期分配，并非供应商事实。
                    equity_bridge_opening = q1_equity
                    equity_profit_contribution = net_income - q1_net_income
                    equity_bridge_note = (
                        "2026Q1桥：最新披露归母权益加FY2026预测归母净利润扣除Q1已实现归母净利润，"
                        "再扣按FY2025归母净利润估算的Q1后支付分红和回购，并加Q1后其他权益变动"
                    )
        equity = (
            equity_bridge_opening
            + equity_profit_contribution
            - dividends
            - buyback
            + other_equity
        )
        asset_bridge_opening = previous_assets
        asset_growth_period_fraction = 1.0
        asset_bridge_note = "全年桥：上年末总资产×(1+本年总资产增速)"
        if year == 2026:
            q1_checkpoint = baseline.get("current_year_q1_checkpoint")
            if isinstance(q1_checkpoint, Mapping):
                q1_assets = _optional_finite(q1_checkpoint.get("total_assets_100m_cny"))
                if q1_assets is not None and q1_assets > 0:
                    asset_bridge_opening = q1_assets
                    asset_growth_period_fraction = 0.75
                    asset_bridge_note = (
                        "2026Q1桥：最新披露总资产×(1+全年总资产增速)的剩余三个季度复合比例"
                    )
        annual_asset_growth = get("total_assets_growth_pct") / 100.0
        if annual_asset_growth <= -1.0:
            raise ModelContractError(f"{ticker}.{year} 总资产增速不能小于或等于-100%")
        asset_growth_candidate = asset_bridge_opening * (
            (1.0 + annual_asset_growth) ** asset_growth_period_fraction
        )
        # The only accounting lower bound available without a full liability
        # and minority-interest schedule is total assets >= parent equity.
        # Liabilities and minority interests may fall, so the opening
        # non-parent claims are disclosed as a diagnostic and never frozen as
        # an artificial balance-sheet floor.
        opening_non_parent_claims = max(
            asset_bridge_opening - equity_bridge_opening,
            0.0,
        )
        accounting_asset_floor = equity
        asset_floor_applied = asset_growth_candidate < accounting_asset_floor
        assets = max(asset_growth_candidate, accounting_asset_floor)
        if asset_floor_applied:
            asset_bridge_note += (
                "；资产增速结果低于期末归母权益时，按总资产不得低于归母权益的会计下限调整"
            )
        if equity <= 0 or assets <= 0:
            raise ModelContractError(f"{ticker}.{year} 预测权益或总资产非正")
        if assets + 1e-9 < equity:
            raise ModelContractError(f"{ticker}.{year} 预测总资产低于归母权益")
        average_equity = (previous_equity + equity) / 2.0
        average_assets = (previous_assets + assets) / 2.0
        roe = net_income / average_equity * 100.0
        roa = net_income / average_assets * 100.0
        below_gross_deductions = gross_profit - net_income
        outputs[str(year)] = {
            "revenue_100m_cny": _round(revenue),
            "gross_profit_100m_cny": _round(gross_profit),
            "below_gross_profit_deductions_100m_cny": _round(below_gross_deductions),
            "parent_net_income_100m_cny": _round(net_income),
            "ocf_100m_cny": _round(ocf),
            "capex_100m_cny": _round(capex),
            "fcf_100m_cny": _round(fcf),
            "dividends_100m_cny": _round(dividends),
            "dividend_base_parent_net_income_100m_cny": _round(
                dividend_base_net_income
            ),
            "dividend_timing_basis": "本年支付分配按上年归母净利润×本年支付率估算；2026年仅解释Q1后预计支付额",
            "buyback_100m_cny": _round(buyback),
            "other_equity_change_100m_cny": _round(other_equity),
            "equity_bridge_opening_100m_cny": _round(equity_bridge_opening),
            "equity_profit_contribution_100m_cny": _round(equity_profit_contribution),
            "equity_bridge_note": equity_bridge_note,
            "ending_parent_equity_100m_cny": _round(equity),
            "asset_bridge_opening_100m_cny": _round(asset_bridge_opening),
            "asset_growth_period_fraction": asset_growth_period_fraction,
            "asset_growth_candidate_100m_cny": _round(asset_growth_candidate),
            "opening_non_parent_claims_100m_cny": _round(opening_non_parent_claims),
            "accounting_asset_floor_100m_cny": _round(accounting_asset_floor),
            "asset_floor_applied": asset_floor_applied,
            "asset_bridge_note": asset_bridge_note,
            "ending_total_assets_100m_cny": _round(assets),
            "roe_pct": _round(roe),
            "roa_pct": _round(roa),
            "input_ledger": {metric: deepcopy(item["ledger"]) for metric, item in row.items()},
        }
        formulas.extend(
            [
                {
                    "output": f"{year}收入",
                    "formula": "上年收入×(1+收入增速)",
                    "substitution": f"{previous_revenue:.4f}×(1+{get('revenue_growth_pct'):.4f}%)={revenue:.4f}",
                    "unit": "亿元人民币",
                },
                {
                    "output": f"{year}自由现金流",
                    "formula": "经营现金流−资本开支",
                    "substitution": f"{ocf:.4f}−{capex:.4f}={fcf:.4f}",
                    "unit": "亿元人民币",
                },
                {
                    "output": f"{year}期末归母权益代理",
                    "formula": equity_bridge_note,
                    "substitution": (
                        f"{equity_bridge_opening:.4f}+{equity_profit_contribution:.4f}−{dividends:.4f}−"
                        f"{buyback:.4f}+{other_equity:.4f}={equity:.4f}"
                    ),
                    "unit": "亿元人民币",
                },
                {
                    "output": f"{year}ROE",
                    "formula": "归母净利润÷期初期末平均归母权益",
                    "substitution": f"{net_income:.4f}÷{average_equity:.4f}={roe:.4f}%",
                    "unit": "%",
                },
                {
                    "output": f"{year}期末总资产",
                    "formula": asset_bridge_note,
                    "substitution": (
                        f"{asset_bridge_opening:.4f}×(1+{get('total_assets_growth_pct'):.4f}%)^"
                        f"{asset_growth_period_fraction:.2f}={asset_growth_candidate:.4f}；"
                        f"会计下限=期末归母权益{accounting_asset_floor:.4f}；"
                        f"期初非归母资金{opening_non_parent_claims:.4f}仅作诊断；期末总资产={assets:.4f}"
                    ),
                    "unit": "亿元人民币",
                },
            ]
        )
        previous_revenue, previous_net_income, previous_equity, previous_assets = (
            revenue,
            net_income,
            equity,
            assets,
        )
    return outputs, formulas


def _parse_valuation_input(value: Any, label: str, unit: str) -> tuple[float, dict[str, Any]]:
    return _annotated(value, label, allowed_units={unit})


def _valuation(
    company: Mapping[str, Any],
    baseline: Mapping[str, Any],
    scenarios: Mapping[str, Any],
    roe_stability: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ticker = str(company["ticker"])
    config = company.get("valuation_methods")
    if not isinstance(config, dict):
        raise ModelContractError(f"{ticker} 缺少 valuation_methods")
    methods: list[dict[str, Any]] = []
    formulas: list[dict[str, Any]] = []
    current_market_cap = baseline["market"].get("market_cap_100m_cny")

    pe = config.get("pe", {})
    if pe.get("enabled"):
        year = int(pe.get("target_year", 0))
        if year not in FORECAST_YEARS:
            raise ModelContractError(f"{ticker}.pe.target_year 无效")
        low, low_ledger = _parse_valuation_input(
            pe.get("multiple_low"), f"{ticker}.pe.multiple_low", "倍"
        )
        high, high_ledger = _parse_valuation_input(
            pe.get("multiple_high"), f"{ticker}.pe.multiple_high", "倍"
        )
        net_income = scenarios["base"][str(year)]["parent_net_income_100m_cny"]
        if net_income is None or net_income <= 0:
            methods.append(
                {
                    "method": "Forward PE",
                    "role": "不适用",
                    "status": "skipped",
                    "reason": f"FY{year} 基准归母净利润非正，PE没有经济意义",
                }
            )
        elif low <= 0 or high < low:
            raise ModelContractError(f"{ticker}.pe 倍数范围无效")
        else:
            value_low, value_high = net_income * low, net_income * high
            methods.append(
                {
                    "method": "Forward PE",
                    "role": str(pe.get("role") or "参考"),
                    "status": "calculated",
                    "target_year": year,
                    "formula": "目标市值＝目标年度归母净利润×目标市盈率",
                    "input": {
                        "parent_net_income_100m_cny": net_income,
                        "multiple_low": low_ledger,
                        "multiple_high": high_ledger,
                    },
                    "equity_value_low_100m_cny": _round(value_low),
                    "equity_value_high_100m_cny": _round(value_high),
                    "upside_low_pct": _round((value_low / current_market_cap - 1) * 100)
                    if current_market_cap and current_market_cap > 0
                    else None,
                    "upside_high_pct": _round((value_high / current_market_cap - 1) * 100)
                    if current_market_cap and current_market_cap > 0
                    else None,
                    "limitation": "倍数是研究情景；周期顶部、一次性利润或增长失速会使方法失真。",
                }
            )
            formulas.append(
                {
                    "method": "Forward PE",
                    "substitution": f"{net_income:.4f}×[{low:.4f},{high:.4f}]",
                    "result_100m_cny": [_round(value_low), _round(value_high)],
                }
            )

    dcf = config.get("dcf", {})
    if dcf.get("enabled"):
        ke_low, ke_low_ledger = _parse_valuation_input(
            dcf.get("cost_of_equity_low_pct"), f"{ticker}.dcf.cost_of_equity_low_pct", "%"
        )
        ke_high, ke_high_ledger = _parse_valuation_input(
            dcf.get("cost_of_equity_high_pct"), f"{ticker}.dcf.cost_of_equity_high_pct", "%"
        )
        g_low, g_low_ledger = _parse_valuation_input(
            dcf.get("terminal_growth_low_pct"), f"{ticker}.dcf.terminal_growth_low_pct", "%"
        )
        g_high, g_high_ledger = _parse_valuation_input(
            dcf.get("terminal_growth_high_pct"), f"{ticker}.dcf.terminal_growth_high_pct", "%"
        )
        if not (ke_high >= ke_low > g_high >= g_low):
            raise ModelContractError(f"{ticker}.dcf 必须满足 ke_high≥ke_low>g_high≥g_low")
        fcfs = [scenarios["base"][str(year)]["fcf_100m_cny"] for year in FORECAST_YEARS]
        if any(value is None for value in fcfs) or fcfs[-1] <= 0:
            methods.append(
                {
                    "method": "股东现金流代理折现",
                    "role": "不适用",
                    "status": "skipped",
                    "reason": "终端年度自由现金流非正，不能建立有意义的正增长终值。",
                }
            )
        else:
            def dcf_value(ke_pct: float, g_pct: float) -> tuple[float, float]:
                ke, growth = ke_pct / 100.0, g_pct / 100.0
                pv_explicit = sum(float(fcf) / ((1 + ke) ** index) for index, fcf in enumerate(fcfs, 1))
                terminal = float(fcfs[-1]) * (1 + growth) / (ke - growth)
                pv_terminal = terminal / ((1 + ke) ** len(fcfs))
                return pv_explicit + pv_terminal, pv_terminal

            low_value, low_terminal = dcf_value(ke_high, g_low)
            high_value, high_terminal = dcf_value(ke_low, g_high)
            methods.append(
                {
                    "method": "股东现金流代理折现",
                    "role": "诊断",
                    "status": "calculated",
                    "formula": "诊断比较值＝预测期经营现金流减资本开支的现值＋终端代理现金流现值",
                    "input": {
                        "fcf_100m_cny": dict(zip(map(str, FORECAST_YEARS), fcfs)),
                        "cost_of_equity_low_pct": ke_low_ledger,
                        "cost_of_equity_high_pct": ke_high_ledger,
                        "terminal_growth_low_pct": g_low_ledger,
                        "terminal_growth_high_pct": g_high_ledger,
                    },
                    "equity_value_low_100m_cny": _round(low_value),
                    "equity_value_high_100m_cny": _round(high_value),
                    "terminal_value_share_low_case_pct": _round(low_terminal / low_value * 100),
                    "terminal_value_share_high_case_pct": _round(high_terminal / high_value * 100),
                    "upside_low_pct": _round((low_value / current_market_cap - 1) * 100)
                    if current_market_cap and current_market_cap > 0
                    else None,
                    "upside_high_pct": _round((high_value / current_market_cap - 1) * 100)
                    if current_market_cap and current_market_cap > 0
                    else None,
                    "limitation": "该值只是经营现金流减资本开支的诊断代理；没有显式加入净借款、净现金及完整营运资本桥，且终值占比较高，因此不进入核心估值区间。",
                }
            )
            formulas.append(
                {
                    "method": "股东现金流代理折现",
                    "substitution": {
                        "low": f"FCF/{ke_high:.2f}%折现，终值增速{g_low:.2f}%",
                        "high": f"FCF/{ke_low:.2f}%折现，终值增速{g_high:.2f}%",
                    },
                    "result_100m_cny": [_round(low_value), _round(high_value)],
                }
            )

    pbroe = config.get("pb_roe", {})
    if pbroe.get("enabled"):
        if not pbroe.get("stable_roe") or not roe_stability.get("passed"):
            methods.append(
                {
                    "method": "PB—ROE（Wilcox）",
                    "role": "不适用",
                    "status": "skipped",
                    "stability_test": deepcopy(roe_stability),
                    "reason": "未通过可持续ROE门禁；PB—ROE只保留为质量观察，不计算目标值。",
                }
            )
        else:
            evidence = pbroe.get("stability_evidence")
            if not isinstance(evidence, list) or not evidence:
                raise ModelContractError(f"{ticker}.pb_roe 缺少 ROE稳定性依据")
            ke_low, ke_low_ledger = _parse_valuation_input(
                pbroe.get("cost_of_equity_low_pct"), f"{ticker}.pb_roe.cost_of_equity_low_pct", "%"
            )
            ke_high, ke_high_ledger = _parse_valuation_input(
                pbroe.get("cost_of_equity_high_pct"), f"{ticker}.pb_roe.cost_of_equity_high_pct", "%"
            )
            terminal_low, terminal_low_ledger = _parse_valuation_input(
                pbroe.get("terminal_pb_low"), f"{ticker}.pb_roe.terminal_pb_low", "倍"
            )
            terminal_high, terminal_high_ledger = _parse_valuation_input(
                pbroe.get("terminal_pb_high"), f"{ticker}.pb_roe.terminal_pb_high", "倍"
            )
            years, years_ledger = _parse_valuation_input(
                pbroe.get("convergence_years"), f"{ticker}.pb_roe.convergence_years", "年"
            )
            if ke_low <= 0 or ke_high < ke_low or terminal_low <= 0 or terminal_high < terminal_low or years <= 0:
                raise ModelContractError(f"{ticker}.pb_roe 输入范围无效")
            scenario_roe = {
                scenario: statistics.fmean(
                    float(scenarios[scenario][str(year)]["roe_pct"]) for year in FORECAST_YEARS
                )
                for scenario in SCENARIOS
            }
            roe_low, roe_high = min(scenario_roe.values()), max(scenario_roe.values())
            q1_checkpoint = baseline.get("current_year_q1_checkpoint")
            current_equity = (
                float(q1_checkpoint["parent_equity_100m_cny"])
                if isinstance(q1_checkpoint, Mapping)
                and _optional_finite(q1_checkpoint.get("parent_equity_100m_cny")) is not None
                else float(baseline["parent_equity_100m_cny"])
            )
            current_equity_period = (
                "2026Q1"
                if isinstance(q1_checkpoint, Mapping)
                and _optional_finite(q1_checkpoint.get("parent_equity_100m_cny")) is not None
                else "FY2025"
            )
            pb_low = terminal_low * math.exp((roe_low / 100.0 - ke_high / 100.0) * years)
            pb_high = terminal_high * math.exp((roe_high / 100.0 - ke_low / 100.0) * years)
            value_low, value_high = current_equity * pb_low, current_equity * pb_high
            methods.append(
                {
                    "method": "PB—ROE（Wilcox）",
                    "role": str(pbroe.get("role") or "诊断"),
                    "status": "calculated",
                    "formula": "当前合理PB＝终端PB×exp[(可持续ROE−股权成本)×回归年限]；股权价值＝当前权益×合理PB",
                    "input": {
                        "forecast_average_roe_by_scenario_pct": {key: _round(value) for key, value in scenario_roe.items()},
                        "cost_of_equity_low_pct": ke_low_ledger,
                        "cost_of_equity_high_pct": ke_high_ledger,
                        "terminal_pb_low": terminal_low_ledger,
                        "terminal_pb_high": terminal_high_ledger,
                        "convergence_years": years_ledger,
                        "stability_evidence": deepcopy(evidence),
                        "quantitative_stability_test": deepcopy(roe_stability),
                        "current_parent_equity_100m_cny": _round(current_equity),
                        "current_parent_equity_period": current_equity_period,
                    },
                    "implied_pb_low": _round(pb_low),
                    "implied_pb_high": _round(pb_high),
                    "equity_value_low_100m_cny": _round(value_low),
                    "equity_value_high_100m_cny": _round(value_high),
                    "upside_low_pct": _round((value_low / current_market_cap - 1) * 100)
                    if current_market_cap and current_market_cap > 0
                    else None,
                    "upside_high_pct": _round((value_high / current_market_cap - 1) * 100)
                    if current_market_cap and current_market_cap > 0
                    else None,
                    "limitation": "结果依赖ROE可持续性、股权成本、回归年限和终端PB；高成长科技或周期顶部仅作诊断。",
                }
            )
            formulas.append(
                {
                    "method": "PB—ROE（Wilcox）",
                    "substitution": {
                        "low": f"{terminal_low:.4f}×exp[({roe_low:.4f}%−{ke_high:.4f}%)×{years:.4f}]",
                        "high": f"{terminal_high:.4f}×exp[({roe_high:.4f}%−{ke_low:.4f}%)×{years:.4f}]",
                    },
                    "result_pb": [_round(pb_low), _round(pb_high)],
                    "result_100m_cny": [_round(value_low), _round(value_high)],
                }
            )

    reverse_year = int(config.get("reverse_pe_year", 2027))
    reverse_profit = scenarios["base"].get(str(reverse_year), {}).get("parent_net_income_100m_cny")
    if current_market_cap and current_market_cap > 0 and reverse_profit and reverse_profit > 0:
        methods.append(
            {
                "method": "当前市值隐含市盈率",
                "role": "诊断",
                "status": "calculated",
                "target_year": reverse_year,
                "formula": "当前总市值÷独立预测归母净利润",
                "implied_pe": _round(current_market_cap / reverse_profit),
                "input": {
                    "current_market_cap_100m_cny": _round(current_market_cap),
                    "independent_parent_net_income_100m_cny": reverse_profit,
                },
            }
        )
    return methods, formulas


def _daily_returns(price_rows: list[dict[str, Any]]) -> dict[str, float]:
    values: dict[str, float] = {}
    clean = sorted(
        (
            str(row.get("date")),
            _optional_finite(row.get("close_forward_adjusted")),
        )
        for row in price_rows
        if row.get("date")
    )
    previous: float | None = None
    for date, close in clean:
        if close is None or close <= 0:
            continue
        if previous is not None and previous > 0:
            values[date] = math.log(close / previous)
        previous = close
    return values


def _correlation(a: Mapping[str, float], b: Mapping[str, float], minimum: int) -> tuple[float | None, int]:
    dates = sorted(set(a) & set(b))
    if len(dates) < minimum:
        return None, len(dates)
    left = [a[date] for date in dates]
    right = [b[date] for date in dates]
    if statistics.pstdev(left) == 0 or statistics.pstdev(right) == 0:
        return None, len(dates)
    return statistics.correlation(left, right), len(dates)


def _portfolio_candidate(
    company: Mapping[str, Any],
    baseline: Mapping[str, Any],
    scenarios: Mapping[str, Any],
    actual_security: Mapping[str, Any],
) -> dict[str, Any]:
    config = company.get("portfolio")
    if not isinstance(config, dict):
        raise ModelContractError(f"{company.get('ticker')} 缺少 portfolio 配置")
    scopes = config.get("scopes")
    if not isinstance(scopes, list) or not scopes:
        raise ModelContractError(f"{company.get('ticker')}.portfolio.scopes 必须非空")
    direction = str(config.get("direction") or "").strip()
    if not direction:
        raise ModelContractError(f"{company.get('ticker')}.portfolio.direction 缺失")
    ticker = str(company["ticker"])
    base = scenarios["base"]
    downside = scenarios["downside"]
    anchor = company.get("quantitative_anchor")
    if not isinstance(anchor, Mapping):
        anchor = {}

    def metric_stat(metric: str, field: str) -> float | None:
        row = anchor.get(metric)
        return _optional_finite(row.get(field)) if isinstance(row, Mapping) else None

    def metric_count(metric: str) -> int:
        value = metric_stat(metric, "count")
        return int(value) if value is not None and value >= 0 else 0

    def cagr(start: float | None, end: float | None, years: int) -> float | None:
        if start is None or end is None or start <= 0 or end <= 0 or years <= 0:
            return None
        return ((end / start) ** (1.0 / years) - 1.0) * 100.0

    revenue_cagr = cagr(
        _optional_finite(baseline.get("revenue_100m_cny")),
        _optional_finite(base["2028"].get("revenue_100m_cny")),
        3,
    )
    profit_cagr = cagr(
        _optional_finite(baseline.get("parent_net_income_100m_cny")),
        _optional_finite(base["2028"].get("parent_net_income_100m_cny")),
        3,
    )
    market_cap = _optional_finite(baseline.get("market", {}).get("market_cap_100m_cny"))
    current_pb = _optional_finite(baseline.get("market", {}).get("pb_lf"))
    fy2027_profit = _optional_finite(base["2027"].get("parent_net_income_100m_cny"))
    reverse_pe = (
        market_cap / fy2027_profit
        if market_cap is not None and market_cap > 0 and fy2027_profit is not None and fy2027_profit > 0
        else None
    )
    peg_proxy = (
        reverse_pe / profit_cagr
        if reverse_pe is not None and profit_cagr is not None and profit_cagr > 0
        else None
    )
    fy2027_fcf = _optional_finite(base["2027"].get("fcf_100m_cny"))
    fcf_yield = (
        fy2027_fcf / market_cap * 100.0
        if fy2027_fcf is not None and market_cap is not None and market_cap > 0
        else None
    )
    fy2028_roe = _optional_finite(base["2028"].get("roe_pct"))
    downside_profit = _optional_finite(downside["2027"].get("parent_net_income_100m_cny"))
    downside_profit_decline = (
        max(0.0, (1.0 - downside_profit / fy2027_profit) * 100.0)
        if downside_profit is not None and fy2027_profit is not None and fy2027_profit > 0
        else None
    )
    returns = _daily_returns(list(actual_security.get("prices") or []))
    annualized_volatility = _annualized_volatility(returns, 245)

    def binary_criterion(
        *, name: str, rule: str, observed: str, passed: bool, points: float
    ) -> dict[str, Any]:
        return {
            "criterion": name,
            "rule": rule,
            "observed": observed,
            "passed": bool(passed),
            "awarded_points": _round(points if passed else 0.0),
            "maximum_points": _round(points),
        }

    direction_criteria = [
        binary_criterion(
            name="FY2026收入增速",
            rule="基准FY2026收入增速不低于15%得20分",
            observed=f"{base['2026']['input_ledger']['revenue_growth_pct']['value']:.2f}%",
            passed=float(base["2026"]["input_ledger"]["revenue_growth_pct"]["value"]) >= 15.0,
            points=20,
        ),
        binary_criterion(
            name="三年收入复合增速",
            rule="FY2025—FY2028基准收入复合增速不低于15%得20分",
            observed="不可计算" if revenue_cagr is None else f"{revenue_cagr:.2f}%",
            passed=revenue_cagr is not None and revenue_cagr >= 15.0,
            points=20,
        ),
        binary_criterion(
            name="三年利润复合增速",
            rule="FY2025—FY2028基准归母净利润复合增速不低于15%得20分",
            observed="不可计算" if profit_cagr is None else f"{profit_cagr:.2f}%",
            passed=profit_cagr is not None and profit_cagr >= 15.0,
            points=20,
        ),
        binary_criterion(
            name="毛利率保持",
            rule="FY2028基准毛利率不低于FY2026减1个百分点得20分",
            observed=(
                f"FY2026 {base['2026']['input_ledger']['gross_margin_pct']['value']:.2f}% / "
                f"FY2028 {base['2028']['input_ledger']['gross_margin_pct']['value']:.2f}%"
            ),
            passed=(
                float(base["2028"]["input_ledger"]["gross_margin_pct"]["value"])
                >= float(base["2026"]["input_ledger"]["gross_margin_pct"]["value"]) - 1.0
            ),
            points=20,
        ),
        binary_criterion(
            name="上行情景弹性",
            rule="FY2028上行情景收入至少比基准高15%得20分",
            observed=(
                f"上行/基准={float(scenarios['upside']['2028']['revenue_100m_cny']) / float(base['2028']['revenue_100m_cny']):.4f}倍"
            ),
            passed=(
                float(scenarios["upside"]["2028"]["revenue_100m_cny"])
                >= float(base["2028"]["revenue_100m_cny"]) * 1.15
            ),
            points=20,
        ),
    ]

    historical_net_margin = metric_stat("net_margin_pct", "median")
    historical_ocf_margin = metric_stat("ocf_margin_pct", "median")
    quality_criteria = [
        binary_criterion(
            name="正常化盈利",
            rule="FY2025正常化归母净利润为正得20分",
            observed=f"{float(baseline['parent_net_income_100m_cny']):.2f}亿元",
            passed=float(baseline["parent_net_income_100m_cny"]) > 0,
            points=20,
        ),
        binary_criterion(
            name="历史净利率",
            rule="FY2021—FY2025净利率中位数不低于5%得20分",
            observed="无足够历史" if historical_net_margin is None else f"{historical_net_margin:.2f}%",
            passed=historical_net_margin is not None and historical_net_margin >= 5.0,
            points=20,
        ),
        binary_criterion(
            name="历史经营现金流率",
            rule="FY2021—FY2025经营现金流率中位数不低于5%得20分",
            observed="无足够历史" if historical_ocf_margin is None else f"{historical_ocf_margin:.2f}%",
            passed=historical_ocf_margin is not None and historical_ocf_margin >= 5.0,
            points=20,
        ),
        binary_criterion(
            name="三年自由现金流",
            rule="FY2026—FY2028基准自由现金流均为正得20分",
            observed="/".join(f"{base[str(year)]['fcf_100m_cny']:.2f}" for year in FORECAST_YEARS) + "亿元",
            passed=all(float(base[str(year)]["fcf_100m_cny"]) > 0 for year in FORECAST_YEARS),
            points=20,
        ),
        binary_criterion(
            name="资本效率",
            rule="FY2028基准ROE不低于10%得20分",
            observed="不可计算" if fy2028_roe is None else f"{fy2028_roe:.2f}%",
            passed=fy2028_roe is not None and fy2028_roe >= 10.0,
            points=20,
        ),
    ]

    data_quality = str(company.get("data_quality") or "low")
    data_quality_points = {"high": 40.0, "medium": 25.0, "low": 10.0}.get(data_quality, 0.0)
    evidence_criteria = [
        {
            "criterion": "快照数据质量",
            "rule": "high/medium/low分别得40/25/10分",
            "observed": data_quality,
            "passed": data_quality in {"high", "medium", "low"},
            "awarded_points": data_quality_points,
            "maximum_points": 40.0,
        }
    ]
    for metric, label in (
        ("revenue_growth_pct", "收入增速历史"),
        ("gross_margin_pct", "毛利率历史"),
        ("net_margin_pct", "净利率历史"),
        ("ocf_margin_pct", "经营现金流率历史"),
    ):
        count = metric_count(metric)
        evidence_criteria.append(
            binary_criterion(
                name=label,
                rule="FY2021—FY2025可用年度观测至少4期得15分",
                observed=f"{count}期",
                passed=count >= 4,
                points=15,
            )
        )

    historical_pe_q25 = metric_stat("pe_ttm", "q25")
    historical_pe_median = metric_stat("pe_ttm", "median")
    historical_pe_q75 = metric_stat("pe_ttm", "q75")
    if peg_proxy is None:
        peg_points = 0.0
    elif peg_proxy <= 1.0:
        peg_points = 40.0
    elif peg_proxy <= 1.5:
        peg_points = 30.0
    elif peg_proxy <= 2.0:
        peg_points = 20.0
    elif peg_proxy <= 3.0:
        peg_points = 10.0
    else:
        peg_points = 0.0
    if reverse_pe is None or historical_pe_q25 is None or historical_pe_median is None or historical_pe_q75 is None:
        historical_pe_points = 0.0
        historical_pe_observed = "缺少可比历史PE或基准利润"
    elif reverse_pe <= historical_pe_q25:
        historical_pe_points = 25.0
        historical_pe_observed = f"隐含{reverse_pe:.2f}倍≤历史Q25 {historical_pe_q25:.2f}倍"
    elif reverse_pe <= historical_pe_median:
        historical_pe_points = 15.0
        historical_pe_observed = f"隐含{reverse_pe:.2f}倍≤历史中位{historical_pe_median:.2f}倍"
    elif reverse_pe <= historical_pe_q75:
        historical_pe_points = 8.0
        historical_pe_observed = f"隐含{reverse_pe:.2f}倍≤历史Q75 {historical_pe_q75:.2f}倍"
    else:
        historical_pe_points = 0.0
        historical_pe_observed = f"隐含{reverse_pe:.2f}倍>历史Q75 {historical_pe_q75:.2f}倍"
    if fcf_yield is None:
        fcf_yield_points = 0.0
    elif fcf_yield >= 5.0:
        fcf_yield_points = 20.0
    elif fcf_yield >= 2.0:
        fcf_yield_points = 10.0
    elif fcf_yield >= 0.0:
        fcf_yield_points = 5.0
    else:
        fcf_yield_points = 0.0
    pb_roe_points = (
        15.0
        if fy2028_roe is not None and fy2028_roe >= 15.0 and current_pb is not None and current_pb <= 5.0
        else 8.0
        if fy2028_roe is not None and fy2028_roe >= 10.0 and current_pb is not None and current_pb <= 8.0
        else 0.0
    )
    valuation_criteria = [
        {
            "criterion": "增长估值匹配",
            "rule": "FY2027隐含PE÷FY2025—FY2028利润CAGR：≤1/1.5/2/3分别得40/30/20/10分",
            "observed": "不可计算" if peg_proxy is None else f"{peg_proxy:.2f}",
            "awarded_points": peg_points,
            "maximum_points": 40.0,
        },
        {
            "criterion": "历史PE位置",
            "rule": "隐含Forward PE位于历史TTM Q25/中位/Q75以内分别得25/15/8分",
            "observed": historical_pe_observed,
            "awarded_points": historical_pe_points,
            "maximum_points": 25.0,
        },
        {
            "criterion": "自由现金流收益率",
            "rule": "FY2027基准FCF/当前市值≥5%/2%/0%分别得20/10/5分",
            "observed": "不可计算" if fcf_yield is None else f"{fcf_yield:.2f}%",
            "awarded_points": fcf_yield_points,
            "maximum_points": 20.0,
        },
        {
            "criterion": "PB与ROE组合",
            "rule": "FY2028 ROE≥15%且PB≤5倍得15分；ROE≥10%且PB≤8倍得8分",
            "observed": (
                "不可计算" if fy2028_roe is None or current_pb is None else f"ROE {fy2028_roe:.2f}% / PB {current_pb:.2f}倍"
            ),
            "awarded_points": pb_roe_points,
            "maximum_points": 15.0,
        },
    ]

    if annualized_volatility is None:
        volatility_points = 30.0
    elif annualized_volatility >= 0.70:
        volatility_points = 30.0
    elif annualized_volatility >= 0.50:
        volatility_points = 20.0
    elif annualized_volatility >= 0.35:
        volatility_points = 10.0
    else:
        volatility_points = 5.0
    if downside_profit_decline is None:
        downside_points = 25.0
    elif downside_profit_decline >= 40.0:
        downside_points = 25.0
    elif downside_profit_decline >= 20.0:
        downside_points = 15.0
    elif downside_profit_decline >= 10.0:
        downside_points = 8.0
    else:
        downside_points = 0.0
    if reverse_pe is None:
        pe_risk_points = 20.0
    elif reverse_pe >= 80.0:
        pe_risk_points = 20.0
    elif reverse_pe >= 50.0:
        pe_risk_points = 15.0
    elif reverse_pe >= 30.0:
        pe_risk_points = 8.0
    else:
        pe_risk_points = 0.0
    negative_fcf_points = 15.0 if any(float(base[str(year)]["fcf_100m_cny"]) <= 0 for year in FORECAST_YEARS) else 0.0
    data_risk_points = {"high": 0.0, "medium": 10.0, "low": 20.0}.get(data_quality, 20.0)
    risk_criteria = [
        {"criterion": "历史波动", "rule": "245日年化波动率≥70%/50%/35%分别记30/20/10分，否则5分；缺失按30分", "observed": "缺失" if annualized_volatility is None else f"{annualized_volatility * 100.0:.2f}%", "awarded_points": volatility_points, "maximum_points": 30.0},
        {"criterion": "下行情景利润损失", "rule": "FY2027下行较基准利润下降≥40%/20%/10%分别记25/15/8分；不可计算按25分", "observed": "不可计算" if downside_profit_decline is None else f"{downside_profit_decline:.2f}%", "awarded_points": downside_points, "maximum_points": 25.0},
        {"criterion": "估值风险", "rule": "FY2027隐含PE≥80/50/30倍分别记20/15/8分；不可计算按20分", "observed": "不可计算" if reverse_pe is None else f"{reverse_pe:.2f}倍", "awarded_points": pe_risk_points, "maximum_points": 20.0},
        {"criterion": "现金流风险", "rule": "FY2026—FY2028任一年基准FCF非正记15分", "observed": "/".join(f"{base[str(year)]['fcf_100m_cny']:.2f}" for year in FORECAST_YEARS) + "亿元", "awarded_points": negative_fcf_points, "maximum_points": 15.0},
        {"criterion": "数据质量折损", "rule": "high/medium/low分别记0/10/20分", "observed": data_quality, "awarded_points": data_risk_points, "maximum_points": 20.0},
    ]

    score_criteria = {
        "direction_score": direction_criteria,
        "quality_score": quality_criteria,
        "evidence_score": evidence_criteria,
        "valuation_score": valuation_criteria,
        "risk_score": risk_criteria,
    }
    descriptions = {
        "direction_score": "盈利轨迹与上行情景方向分",
        "quality_score": "盈利、现金流与资本效率质量分",
        "evidence_score": "冻结财务快照和历史序列完整度分",
        "valuation_score": "当前价格相对增长、历史PE、FCF与PB—ROE的估值分",
        "risk_score": "波动、下行情景、估值、现金流和数据质量风险分",
    }
    scores: dict[str, float] = {}
    ledger: dict[str, Any] = {}
    for key in PORTFOLIO_SCORE_KEYS:
        raw_score = sum(float(row["awarded_points"]) for row in score_criteria[key])
        score = min(100.0, max(0.0, raw_score))
        scores[key] = _round(score)
        ledger[key] = {
            "value": _round(score),
            "unit": "分",
            "basis_type": "implied",
            "as_of": str(baseline.get("market", {}).get("trade_date") or "2026-07-30"),
            "source_ref": "冻结actual/market快照、FY2021—FY2025历史锚与Run16独立三情景模型；未读取一致预期",
            "rationale": descriptions[key],
            "formula": "各公开判定项得分相加，并限制在0—100分",
            "criteria": score_criteria[key],
        }
    float_cap = baseline["market"].get("free_float_market_cap_100m_cny")
    return {
        "ticker": company["ticker"],
        "name": company["name"],
        "direction": direction,
        "scopes": scopes,
        "eligible": bool(config.get("eligible", True)),
        "free_float_market_cap_100m_cny": float_cap,
        "scores": scores,
        "scorecard_contract_version": "run16.portfolio_scorecard.v2",
        "scorecard": deepcopy(score_criteria),
        "adjustment_multiplier": 1.0,
        "adjusted_float_cap": float_cap if float_cap and float_cap > 0 else None,
        "score_ledger": ledger,
        "formula": "自由流通市值、等权和逆波动形成混合锚；五项评分按公开逐项刻度复算并只形成有上下限的加法主动倾斜",
    }


def _window_values(values: Mapping[str, float], days: int) -> list[float]:
    return [values[key] for key in sorted(values)[-days:]]


def _annualized_volatility(values: Mapping[str, float], days: int) -> float | None:
    sample = _window_values(values, days)
    if len(sample) < min(days, 40) or len(sample) < 2:
        return None
    deviation = statistics.stdev(sample)
    return deviation * math.sqrt(252.0) if deviation > 0 else None


def _active_tilt(
    candidate: Mapping[str, Any], policy: Mapping[str, Any]
) -> tuple[float, dict[str, Any]]:
    weights = policy.get("score_weights")
    if not isinstance(weights, dict) or set(weights) != set(PORTFOLIO_SCORE_KEYS):
        raise ModelContractError(
            "portfolio policy score_weights 必须且只能包含五项评分权重"
        )
    parsed_weights = {
        key: _finite(weights[key], f"score_weights.{key}")
        for key in PORTFOLIO_SCORE_KEYS
    }
    if any(value < 0 for value in parsed_weights.values()):
        raise ModelContractError("score_weights 不能为负")
    total_weight = sum(parsed_weights.values())
    if total_weight <= 0:
        raise ModelContractError("score_weights 合计必须为正")
    scores = candidate["scores"]
    adjusted_scores = {
        key: (100.0 - scores[key] if key == "risk_score" else scores[key])
        for key in PORTFOLIO_SCORE_KEYS
    }
    composite = sum(
        adjusted_scores[key] * parsed_weights[key] for key in PORTFOLIO_SCORE_KEYS
    ) / total_weight
    strength = _finite(policy.get("active_tilt_strength", 0.25), "active_tilt_strength")
    lower = _finite(policy.get("active_tilt_min", 0.85), "active_tilt_min")
    upper = _finite(policy.get("active_tilt_max", 1.15), "active_tilt_max")
    if not 0 < lower <= 1 <= upper or strength < 0:
        raise ModelContractError("主动倾斜上下限或强度无效")
    uncapped = 1.0 + strength * ((composite - 50.0) / 50.0)
    tilt = min(max(uncapped, lower), upper)
    return tilt, {
        "weighted_composite_score": _round(composite, 4),
        "uncapped_tilt": _round(uncapped, 4),
        "active_tilt_multiplier": _round(tilt, 4),
        "score_weights": parsed_weights,
        "score_values_after_risk_reversal": adjusted_scores,
        "formula": "tilt=clip(1+强度×(加权综合分−50)/50,下限,上限)；风险分使用100−风险分",
    }


def _score_candidates(
    candidates: list[dict[str, Any]],
    returns: Mapping[str, Mapping[str, float]],
    policy: Mapping[str, Any],
    volatility_window_days: int,
) -> list[dict[str, Any]]:
    mix = policy.get("anchor_mix")
    if not isinstance(mix, dict) or set(mix) != {
        "free_float",
        "equal",
        "inverse_volatility",
    }:
        raise ModelContractError(
            "anchor_mix 必须且只能包含 free_float/equal/inverse_volatility"
        )
    mix_values = {
        key: _finite(value, f"anchor_mix.{key}") for key, value in mix.items()
    }
    if any(value < 0 for value in mix_values.values()) or abs(sum(mix_values.values()) - 1.0) > 1e-9:
        raise ModelContractError("anchor_mix 必须非负且合计为1")
    float_total = sum(float(row["free_float_market_cap_100m_cny"]) for row in candidates)
    if float_total <= 0:
        raise ModelContractError("自由流通市值合计必须为正")
    volatility: dict[str, float] = {}
    for row in candidates:
        value = _annualized_volatility(
            returns[row["ticker"]], volatility_window_days
        )
        if value is None or value <= 0:
            raise ModelContractError(
                f"{row['ticker']} 缺少{volatility_window_days}日有效波动率，不能建立逆波动锚"
            )
        volatility[row["ticker"]] = value
    inverse_total = sum(1.0 / value for value in volatility.values())
    equal = 1.0 / len(candidates)
    scored: list[dict[str, Any]] = []
    for source in candidates:
        row = deepcopy(source)
        ticker = row["ticker"]
        components = {
            "free_float": float(row["free_float_market_cap_100m_cny"]) / float_total,
            "equal": equal,
            "inverse_volatility": (1.0 / volatility[ticker]) / inverse_total,
        }
        anchor = sum(components[key] * mix_values[key] for key in components)
        tilt, tilt_audit = _active_tilt(row, policy)
        score = anchor * tilt
        row.update(
            {
                "anchor_components": components,
                "anchor_mix": mix_values,
                "mixed_anchor": anchor,
                "active_tilt_multiplier": tilt,
                "adjustment_multiplier": tilt,
                "adjusted_float_cap": score,
                "portfolio_score": score,
                "annualized_volatility_pct": volatility[ticker] * 100.0,
                "tilt_audit": tilt_audit,
            }
        )
        scored.append(row)
    return scored


def _select_candidates(candidates: list[dict[str, Any]], kind: str, maximum: int) -> list[dict[str, Any]]:
    def selection_value(row: Mapping[str, Any]) -> float:
        value = row.get("portfolio_score", row.get("adjusted_float_cap"))
        return _finite(value, f"{row.get('ticker', 'candidate')}.portfolio_score")

    ranked = sorted(candidates, key=selection_value, reverse=True)
    if kind != "balanced":
        return ranked[:maximum]
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in ranked:
        groups.setdefault(row["direction"], []).append(row)
    selected: list[dict[str, Any]] = []
    while len(selected) < maximum:
        added = False
        active_directions = [direction for direction, rows in groups.items() if rows]
        for direction in sorted(
            active_directions,
            key=lambda key: selection_value(groups[key][0]),
            reverse=True,
        ):
            if groups[direction] and len(selected) < maximum:
                selected.append(groups[direction].pop(0))
                added = True
        if not added:
            break
    return selected


def _pair_window_diagnostics(
    left: Mapping[str, float], right: Mapping[str, float]
) -> dict[str, Any]:
    dates = sorted(set(left) & set(right))
    diagnostics: dict[str, Any] = {"overlap_days": len(dates)}
    for window in CORRELATION_WINDOWS:
        use = dates[-window:]
        if len(use) < min(window, 40):
            value = None
        else:
            lhs = [left[date] for date in use]
            rhs = [right[date] for date in use]
            value = (
                statistics.correlation(lhs, rhs)
                if statistics.pstdev(lhs) > 0 and statistics.pstdev(rhs) > 0
                else None
            )
        diagnostics[f"correlation_{window}d"] = _round(value, 4)
    rolling: list[float] = []
    if len(dates) >= 60:
        for end in range(60, len(dates) + 1):
            use = dates[end - 60 : end]
            lhs = [left[date] for date in use]
            rhs = [right[date] for date in use]
            if statistics.pstdev(lhs) > 0 and statistics.pstdev(rhs) > 0:
                rolling.append(statistics.correlation(lhs, rhs))
    diagnostics["rolling_60d_peak"] = _round(max(rolling), 4) if rolling else None
    return diagnostics


def _prune_correlated(
    selected: list[dict[str, Any]],
    returns: Mapping[str, Mapping[str, float]],
    maximum_correlation: float,
    minimum_overlap: int,
    minimum_holdings: int,
    correlation_window_days: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    selected = list(selected)
    pruned: list[dict[str, Any]] = []
    while len(selected) > minimum_holdings:
        violations: list[tuple[float, dict[str, Any], dict[str, Any], int]] = []
        for index, left in enumerate(selected):
            for right in selected[index + 1 :]:
                pair = _pair_window_diagnostics(
                    returns[left["ticker"]], returns[right["ticker"]]
                )
                overlap = int(pair["overlap_days"])
                corr = pair.get(f"correlation_{correlation_window_days}d")
                if overlap >= minimum_overlap and corr is not None and corr > maximum_correlation:
                    violations.append((corr, left, right, overlap))
        if not violations:
            break
        corr, left, right, overlap = max(violations, key=lambda item: item[0])
        remove = left if left["portfolio_score"] < right["portfolio_score"] else right
        selected.remove(remove)
        pruned.append(
            {
                "ticker": remove["ticker"],
                "reason": f"与更高排序候选的{correlation_window_days}日收益相关性超过约束",
                "pair": [left["ticker"], right["ticker"]],
                "correlation": _round(corr, 4),
                "overlap_days": overlap,
            }
        )
    diagnostics: list[dict[str, Any]] = []
    for index, left in enumerate(selected):
        for right in selected[index + 1 :]:
            pair = _pair_window_diagnostics(
                returns[left["ticker"]], returns[right["ticker"]]
            )
            corr = pair.get(f"correlation_{correlation_window_days}d")
            overlap = int(pair["overlap_days"])
            diagnostics.append(
                {
                    "left": left["ticker"],
                    "right": right["ticker"],
                    "correlation": _round(corr, 4),
                    **pair,
                    "constraint_window_days": correlation_window_days,
                    "sufficient_history": overlap >= minimum_overlap and corr is not None,
                    "exceeds_limit": (
                        overlap >= minimum_overlap
                        and corr is not None
                        and corr > maximum_correlation
                    ),
                }
            )
    return selected, pruned, diagnostics


def _cap_weights(raw: dict[str, float], investable: float, cap: float) -> dict[str, float]:
    if not raw or investable <= 0:
        return {}
    if cap * len(raw) + 1e-9 < investable:
        raise ModelContractError("单股上限与持仓数量不能容纳计划股票仓位")
    remaining = set(raw)
    weights = {key: 0.0 for key in raw}
    remaining_total = investable
    while remaining:
        score_total = sum(raw[key] for key in remaining)
        if score_total <= 0:
            raise ModelContractError("组合原始权重合计非正")
        tentative = {key: remaining_total * raw[key] / score_total for key in remaining}
        over = [key for key, weight in tentative.items() if weight > cap + 1e-12]
        if not over:
            for key, weight in tentative.items():
                weights[key] = weight
            break
        for key in over:
            weights[key] = cap
            remaining.remove(key)
            remaining_total -= cap
    return weights


def _cap_weights_variable(
    raw: Mapping[str, float], investable: float, caps: Mapping[str, float]
) -> dict[str, float]:
    if set(raw) != set(caps):
        raise ModelContractError("可变上限权重的对象与上限集合不一致")
    if sum(caps.values()) + 1e-9 < investable:
        raise ModelContractError("分组容量不能容纳计划股票仓位")
    remaining = set(raw)
    weights = {key: 0.0 for key in raw}
    remaining_total = investable
    while remaining:
        score_total = sum(raw[key] for key in remaining)
        if score_total <= 0:
            raise ModelContractError("分组原始权重合计非正")
        tentative = {
            key: remaining_total * raw[key] / score_total for key in remaining
        }
        over = [
            key for key, weight in tentative.items() if weight > caps[key] + 1e-12
        ]
        if not over:
            weights.update(tentative)
            break
        for key in over:
            weights[key] = caps[key]
            remaining.remove(key)
            remaining_total -= caps[key]
    return weights


def _allocate_selected(
    selected: list[dict[str, Any]],
    returns: Mapping[str, Mapping[str, float]],
    policy: Mapping[str, Any],
    volatility_window_days: int,
    requested_cash_pct: float,
) -> tuple[list[dict[str, Any]], dict[str, float], float, dict[str, Any]]:
    scored = _score_candidates(selected, returns, policy, volatility_window_days)
    cap_pct = _finite(policy.get("max_weight_pct"), "max_weight_pct")
    direction_cap_pct = _finite(
        policy.get("max_direction_weight_pct", 100.0),
        "max_direction_weight_pct",
    )
    desired_investable = 100.0 - requested_cash_pct
    direction_counts: dict[str, int] = {}
    for row in scored:
        direction_counts[row["direction"]] = direction_counts.get(row["direction"], 0) + 1
    direction_caps = {
        direction: min(direction_cap_pct, cap_pct * count)
        for direction, count in direction_counts.items()
    }
    feasible_investable = min(
        desired_investable,
        cap_pct * len(scored),
        sum(direction_caps.values()),
    )
    effective_cash = 100.0 - feasible_investable
    raw = {row["ticker"]: row["portfolio_score"] for row in scored}
    raw_by_direction: dict[str, float] = {}
    for row in scored:
        raw_by_direction[row["direction"]] = (
            raw_by_direction.get(row["direction"], 0.0) + raw[row["ticker"]]
        )
    direction_budgets = _cap_weights_variable(
        raw_by_direction, feasible_investable, direction_caps
    )
    weights: dict[str, float] = {}
    for direction, budget in direction_budgets.items():
        group_raw = {
            row["ticker"]: raw[row["ticker"]]
            for row in scored
            if row["direction"] == direction
        }
        weights.update(_cap_weights(group_raw, budget, cap_pct))
    adjustment = {
        "requested_cash_weight_pct": _round(requested_cash_pct),
        "effective_cash_weight_pct": _round(effective_cash),
        "candidate_capacity_cash_increase_pct": _round(
            max(effective_cash - requested_cash_pct, 0.0)
        ),
        "reason": (
            "候选数量或方向容量不足以在单股/方向上限内投入目标股票仓位，因此剩余资金保留现金"
            if effective_cash > requested_cash_pct + 1e-9
            else None
        ),
    }
    return scored, weights, effective_cash, adjustment


def _portfolio_risk_diagnostics(
    selected: list[dict[str, Any]],
    weights_pct: Mapping[str, float],
    returns: Mapping[str, Mapping[str, float]],
) -> dict[str, Any]:
    tickers = [row["ticker"] for row in selected]
    common_dates = sorted(set.intersection(*(set(returns[ticker]) for ticker in tickers)))
    by_window: dict[str, Any] = {}
    contribution: dict[str, float | None] = {ticker: None for ticker in tickers}
    for window in CORRELATION_WINDOWS:
        dates = common_dates[-window:]
        if len(dates) < min(window, 40):
            by_window[str(window)] = {
                "annualized_volatility_pct": None,
                "observation_days": len(dates),
            }
            continue
        series = {
            ticker: [returns[ticker][date] for date in dates] for ticker in tickers
        }
        covariance = [
            [statistics.covariance(series[left], series[right]) for right in tickers]
            for left in tickers
        ]
        weights = [weights_pct[ticker] / 100.0 for ticker in tickers]
        marginal = [
            sum(covariance[i][j] * weights[j] for j in range(len(tickers)))
            for i in range(len(tickers))
        ]
        variance = sum(weights[i] * marginal[i] for i in range(len(tickers)))
        annualized = math.sqrt(max(variance, 0.0) * 252.0) * 100.0
        by_window[str(window)] = {
            "annualized_volatility_pct": _round(annualized),
            "observation_days": len(dates),
        }
        if window == 245 and variance > 0:
            contribution = {
                ticker: weights[index] * marginal[index] / variance * 100.0
                for index, ticker in enumerate(tickers)
            }
    return {
        "by_window_days": by_window,
        "primary_window_days": 245,
        "annualized_volatility_pct": by_window["245"]["annualized_volatility_pct"],
        "single_name_risk_contribution_pct": {
            key: _round(value) for key, value in contribution.items()
        },
        "risk_contribution_sum_pct": _round(
            sum(value for value in contribution.values() if value is not None)
        ),
        "formula": "组合方差=w'Σw；单股风险贡献=w_i×(Σw)_i÷组合方差；现金按零波动处理",
        "limitation": "历史波动与协方差只用于风险诊断，不代表未来分布。",
    }


def _rank_positions(weights: Mapping[str, float]) -> dict[str, float]:
    """Rank displayed weights and assign average ranks to public-precision ties.

    Weights are published to two decimal places.  Floating-point tails that
    disappear at that precision must not create an artificial ordering.  The
    rounding boundary is approximately 0.005 percentage points.
    """

    ordered = sorted(
        (
            (ticker, round(float(value), PUBLIC_WEIGHT_DECIMALS))
            for ticker, value in weights.items()
        ),
        key=lambda item: (-item[1], item[0]),
    )
    ranks: dict[str, float] = {}
    index = 0
    while index < len(ordered):
        end = index + 1
        displayed_weight = ordered[index][1]
        while end < len(ordered) and ordered[end][1] == displayed_weight:
            end += 1
        average_rank = ((index + 1) + end) / 2.0
        for ticker, _ in ordered[index:end]:
            ranks[ticker] = average_rank
        index = end
    return ranks


def _spearman(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    keys = sorted(set(left) & set(right))
    if len(keys) < 2:
        return 1.0
    lhs = [float(left[key]) for key in keys]
    rhs = [float(right[key]) for key in keys]
    left_constant = max(lhs) == min(lhs)
    right_constant = max(rhs) == min(rhs)
    if left_constant and right_constant:
        return 1.0
    if left_constant or right_constant:
        return 0.0
    return statistics.correlation(lhs, rhs)


def _weight_sensitivity(
    selected: list[dict[str, Any]],
    returns: Mapping[str, Mapping[str, float]],
    policy: Mapping[str, Any],
    requested_cash_pct: float,
) -> dict[str, Any]:
    cases: dict[str, dict[str, float]] = {}
    ranks: dict[str, dict[str, float]] = {}
    cash: dict[str, float] = {}
    for window in CORRELATION_WINDOWS:
        _, weights, effective_cash, _ = _allocate_selected(
            selected, returns, policy, window, requested_cash_pct
        )
        cases[str(window)] = weights
        ranks[str(window)] = _rank_positions(weights)
        cash[str(window)] = effective_cash
    pairs = [("60", "120"), ("60", "245"), ("120", "245")]
    correlations = {
        f"{left}_vs_{right}": _spearman(ranks[left], ranks[right])
        for left, right in pairs
    }
    ranges = {
        ticker: {
            "weight_low_pct": _round(min(case[ticker] for case in cases.values())),
            "weight_high_pct": _round(max(case[ticker] for case in cases.values())),
            "rank_best": min(ranks[window][ticker] for window in ranks),
            "rank_worst": max(ranks[window][ticker] for window in ranks),
        }
        for ticker in cases["245"]
    }
    return {
        "sensitivity_type": "逆波动锚窗口",
        "window_days": list(CORRELATION_WINDOWS),
        "weights_by_window_pct": {
            window: {ticker: _round(value) for ticker, value in values.items()}
            for window, values in cases.items()
        },
        "effective_cash_by_window_pct": {
            window: _round(value) for window, value in cash.items()
        },
        "weight_and_rank_ranges": ranges,
        "rank_spearman": {
            key: _round(value, 4) for key, value in correlations.items()
        },
        "mean_rank_stability": _round(statistics.fmean(correlations.values()), 4),
        "rank_tie_policy": {
            "published_weight_decimals": PUBLIC_WEIGHT_DECIMALS,
            "approximate_boundary_tolerance_pct": RANK_TIE_TOLERANCE_PCT,
            "method": "权重按公开两位小数分组；同组使用平均秩，全等权窗口之间稳定性记为1.0000",
        },
        "interpretation": "越接近1表示60/120/245日逆波动窗口下的排序越稳定；权重区间不是收益置信区间。",
    }


def _build_portfolios(
    assumptions: Mapping[str, Any],
    candidates: list[dict[str, Any]],
    actual: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    policies = assumptions.get("portfolio_policies")
    if not isinstance(policies, dict):
        raise ModelContractError("缺少 portfolio_policies")
    returns = {ticker: _daily_returns(row.get("prices", [])) for ticker, row in actual.items()}
    outputs: list[dict[str, Any]] = []
    formula_audit: list[dict[str, Any]] = []
    for scope in ("applications", "full_chain"):
        scope_candidates = [
            row
            for row in candidates
            if row["eligible"]
            and scope in row["scopes"]
            and row["free_float_market_cap_100m_cny"] is not None
            and row["free_float_market_cap_100m_cny"] > 0
        ]
        scope_float_total = sum(
            float(row["free_float_market_cap_100m_cny"])
            for row in scope_candidates
            if row["free_float_market_cap_100m_cny"] is not None
        )
        if not scope_candidates:
            continue
        for kind in PORTFOLIO_TYPES:
            policy = policies.get(kind)
            if not isinstance(policy, dict):
                raise ModelContractError(f"portfolio_policies.{kind} 缺失")
            minimum = int(policy.get("min_holdings", 0))
            maximum = int(policy.get("max_holdings", 0))
            target_minimum = int(policy.get("target_min_holdings", minimum))
            cap_pct = _finite(policy.get("max_weight_pct"), f"{kind}.max_weight_pct")
            direction_cap_pct = _finite(
                policy.get("max_direction_weight_pct", 100.0),
                f"{kind}.max_direction_weight_pct",
            )
            requested_cash_pct = _finite(
                policy.get("cash_weight_pct", 0), f"{kind}.cash_weight_pct"
            )
            max_corr = _finite(policy.get("max_pair_correlation"), f"{kind}.max_pair_correlation")
            min_overlap = int(policy.get("min_overlap_days", 120))
            correlation_window = int(policy.get("correlation_window_days", 245))
            if correlation_window not in CORRELATION_WINDOWS:
                raise ModelContractError(
                    f"portfolio_policies.{kind}.correlation_window_days 必须是60/120/245"
                )
            if (
                not 1 <= minimum <= maximum
                or not minimum <= target_minimum <= maximum
                or not 0 < cap_pct <= 100
                or not 0 < direction_cap_pct <= 100
                or not 0 <= requested_cash_pct < 100
            ):
                raise ModelContractError(f"portfolio_policies.{kind} 约束无效")
            kind_candidates = scope_candidates
            if kind == "concentrated":
                by_scope = policy.get("conviction_directions_by_scope") or {}
                allowed_directions = by_scope.get(scope) if isinstance(by_scope, dict) else None
                if not isinstance(allowed_directions, list) or not allowed_directions:
                    raise ModelContractError(
                        f"portfolio_policies.concentrated 缺少 {scope} 的明确方向范围"
                    )
                allowed = {str(value).strip() for value in allowed_directions if str(value).strip()}
                kind_candidates = [
                    row for row in scope_candidates if row["direction"] in allowed
                ]
                if len(kind_candidates) < minimum:
                    raise ModelContractError(
                        f"{scope}.concentrated 明确方向候选不足最小持仓数"
                    )
            scored_pool = _score_candidates(
                kind_candidates, returns, policy, correlation_window
            )
            selected = _select_candidates(scored_pool, kind, maximum)
            selected, pruned, correlation = _prune_correlated(
                selected,
                returns,
                max_corr,
                min_overlap,
                minimum,
                correlation_window,
            )
            if len(selected) < minimum:
                raise ModelContractError(f"{scope}.{kind} 候选不足最小持仓数")
            selected, weights, cash_pct, cash_adjustment = _allocate_selected(
                selected,
                returns,
                policy,
                correlation_window,
                requested_cash_pct,
            )
            sensitivity = _weight_sensitivity(
                selected, returns, policy, requested_cash_pct
            )
            risk = _portfolio_risk_diagnostics(selected, weights, returns)
            rounded = {key: round(value, 2) for key, value in weights.items()}
            if rounded:
                correction = round((100.0 - cash_pct) - sum(rounded.values()), 2)
                if correction < 0:
                    receiver = max(rounded, key=rounded.get)
                elif correction > 0:
                    rounded_by_direction: dict[str, float] = {}
                    for row in selected:
                        rounded_by_direction[row["direction"]] = (
                            rounded_by_direction.get(row["direction"], 0.0)
                            + rounded[row["ticker"]]
                        )
                    eligible_receivers = [
                        row["ticker"]
                        for row in selected
                        if rounded[row["ticker"]] + correction <= cap_pct + 1e-9
                        and rounded_by_direction[row["direction"]] + correction
                        <= direction_cap_pct + 1e-9
                    ]
                    if not eligible_receivers:
                        raise ModelContractError(
                            f"{scope}.{kind} 四舍五入余数无法在单股/方向上限内分配"
                        )
                    receiver = max(eligible_receivers, key=lambda key: rounded[key])
                else:
                    receiver = None
                if receiver is not None:
                    rounded[receiver] = round(rounded[receiver] + correction, 2)
            holdings = []
            for row in sorted(selected, key=lambda item: weights[item["ticker"]], reverse=True):
                holdings.append(
                    {
                        "ticker": row["ticker"],
                        "name": row["name"],
                        "direction": row["direction"],
                        "weight_pct": rounded[row["ticker"]],
                        "starting_free_float_weight_pct": _round(
                            row["free_float_market_cap_100m_cny"] / scope_float_total * 100
                        )
                        if scope_float_total > 0
                        else None,
                        "free_float_market_cap_100m_cny": _round(row["free_float_market_cap_100m_cny"]),
                        "adjustment_multiplier": _round(row["adjustment_multiplier"], 4),
                        "active_tilt_multiplier": _round(
                            row["active_tilt_multiplier"], 4
                        ),
                        "mixed_anchor_weight_pct": _round(
                            row["mixed_anchor"] * 100.0, 4
                        ),
                        "anchor_components": {
                            key: _round(value * 100.0, 4)
                            for key, value in row["anchor_components"].items()
                        },
                        "annualized_volatility_pct": _round(
                            row["annualized_volatility_pct"]
                        ),
                        "risk_contribution_pct": risk[
                            "single_name_risk_contribution_pct"
                        ].get(row["ticker"]),
                        "weight_sensitivity": sensitivity[
                            "weight_and_rank_ranges"
                        ][row["ticker"]],
                        "tilt_audit": row["tilt_audit"],
                        "score_ledger": row["score_ledger"],
                    }
                )
            # 有效持仓数用于衡量股票仓位内部的集中度。组合保留现金时，必须先
            # 把股票权重重新归一到 100%；否则 10% 现金会把平方和机械压低，
            # 甚至产生“有效持仓数大于实际股票数”的不可能结果。
            equity_total = sum(weights.values())
            equity_weights = (
                [value / equity_total for value in weights.values()]
                if equity_total > 0
                else []
            )
            effective_n = 1.0 / sum(value * value for value in equity_weights) if equity_weights else 0.0
            unresolved = [row for row in correlation if not row["sufficient_history"]]
            violations = [row for row in correlation if row["exceeds_limit"]]
            rolling_limit = _optional_finite(
                policy.get("rolling_60d_diagnostic_threshold")
            )
            rolling_breaches = [
                row
                for row in correlation
                if rolling_limit is not None
                and row.get("rolling_60d_peak") is not None
                and row["rolling_60d_peak"] > rolling_limit
            ]
            direction_weights: dict[str, float] = {}
            for row in selected:
                direction_weights[row["direction"]] = direction_weights.get(row["direction"], 0.0) + weights[row["ticker"]]
            concentration_violations = [
                direction
                for direction, weight in direction_weights.items()
                if weight > direction_cap_pct + 1e-8
            ]
            status = (
                "constraint_satisfied"
                if not unresolved and not violations and not concentration_violations
                else "constraint_not_satisfied"
            )
            outputs.append(
                {
                    "scope": scope,
                    "portfolio_type": kind,
                    "status": status,
                    "policy": deepcopy(policy),
                    "conviction_theme": (
                        str((policy.get("conviction_theme_by_scope") or {}).get(scope) or "").strip()
                        if kind == "concentrated"
                        else None
                    ),
                    "holdings": holdings,
                    "requested_cash_weight_pct": _round(requested_cash_pct),
                    "cash_weight_pct": _round(cash_pct),
                    "cash_capacity_adjustment": cash_adjustment,
                    "candidate_pool": {
                        "available_count": len(kind_candidates),
                        "target_min_holdings": target_minimum,
                        "feasible_min_holdings": minimum,
                        "selected_count": len(selected),
                        "shortfall_count": max(target_minimum - len(kind_candidates), 0),
                        "shortfall_explanation": (
                            f"现有完成财务与价格门禁的候选只有{len(kind_candidates)}家，"
                            f"低于目标{target_minimum}家；未虚构或越过门禁补入候选。"
                            if len(kind_candidates) < target_minimum
                            else None
                        ),
                    },
                    "effective_number_of_holdings": _round(effective_n),
                    "top3_weight_pct": _round(sum(sorted(weights.values(), reverse=True)[:3])),
                    "direction_weight_pct": {
                        key: _round(value) for key, value in sorted(direction_weights.items())
                    },
                    "correlation_diagnostics": correlation,
                    "correlation_pruning": pruned,
                    "rolling_60d_correlation_diagnostic_threshold": rolling_limit,
                    "rolling_60d_breach_count": len(rolling_breaches),
                    "portfolio_risk_diagnostics": risk,
                    "weight_sensitivity": sensitivity,
                    "direction_concentration_violations": concentration_violations,
                    "limitations": (
                        "相关性同时展示60/120/245日及滚动60日峰值，只用于识别集中暴露，不代表未来相关性；"
                        "历史不足或约束未满足时状态不会标成已满足。"
                    ),
                }
            )
            formula_audit.append(
                {
                    "scope": scope,
                    "portfolio_type": kind,
                    "formula": "混合锚＝自由流通市值权重×a＋等权×b＋逆波动权重×c；候选分数＝混合锚×有限主动倾斜；随后执行持仓数、单股、方向、现金和相关性约束",
                    "anchor_mix": deepcopy(policy["anchor_mix"]),
                    "active_tilt_contract": {
                        "score_weights": deepcopy(policy["score_weights"]),
                        "strength": policy.get("active_tilt_strength"),
                        "lower": policy.get("active_tilt_min"),
                        "upper": policy.get("active_tilt_max"),
                    },
                    "raw_portfolio_score": {
                        row["ticker"]: _round(row["portfolio_score"], 6)
                        for row in selected
                    },
                    "final_weight_pct": rounded,
                    "portfolio_annualized_volatility_pct": risk[
                        "annualized_volatility_pct"
                    ],
                }
            )
    return outputs, formula_audit


def _parse_stress_delta(value: Any, label: str) -> float:
    number, _ = _annotated(value, label, allowed_units={"百分点", "%"})
    return number


def _stress_tests(
    assumptions: Mapping[str, Any],
    companies: Mapping[str, Any],
    portfolios: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    configurations = assumptions.get("stress_scenarios", [])
    if not isinstance(configurations, list):
        raise ModelContractError("stress_scenarios 必须是数组")
    outputs: list[dict[str, Any]] = []
    for config in configurations:
        name = str(config.get("name") or "").strip()
        shocks = config.get("direction_shocks")
        if not name or not isinstance(shocks, dict):
            raise ModelContractError("每个压力情景需要 name 和 direction_shocks")
        stressed_companies: dict[str, Any] = {}
        for ticker, company in companies.items():
            direction = company["portfolio_candidate"]["direction"]
            shock = shocks.get(direction, shocks.get("default"))
            if not isinstance(shock, dict):
                raise ModelContractError(f"压力情景 {name} 未覆盖方向 {direction}")
            growth_delta = _parse_stress_delta(
                shock.get("revenue_growth_delta_pp"), f"{name}.{direction}.revenue_growth_delta_pp"
            )
            margin_delta = _parse_stress_delta(
                shock.get("parent_net_margin_delta_pp"), f"{name}.{direction}.parent_net_margin_delta_pp"
            )
            ocf_delta = _parse_stress_delta(
                shock.get("ocf_margin_delta_pp"), f"{name}.{direction}.ocf_margin_delta_pp"
            )
            capex_delta = _parse_stress_delta(
                shock.get("capex_margin_delta_pp"), f"{name}.{direction}.capex_margin_delta_pp"
            )
            multiple_change = _parse_stress_delta(
                shock.get("valuation_multiple_change_pct"), f"{name}.{direction}.valuation_multiple_change_pct"
            )
            base_inputs = company["parsed_inputs"]["base"]
            stressed_inputs = deepcopy(base_inputs)
            for year in FORECAST_YEARS:
                stressed_inputs[year]["revenue_growth_pct"]["value"] += growth_delta
                stressed_inputs[year]["parent_net_margin_pct"]["value"] += margin_delta
                stressed_inputs[year]["ocf_margin_pct"]["value"] += ocf_delta
                stressed_inputs[year]["capex_margin_pct"]["value"] += capex_delta
            stressed, _ = _build_scenario(ticker, company["baseline"], stressed_inputs)
            base_2027 = company["scenarios"]["base"]["2027"]
            stress_2027 = stressed["2027"]
            ni_base = float(base_2027["parent_net_income_100m_cny"])
            ni_stress = float(stress_2027["parent_net_income_100m_cny"])
            valuation_proxy = (
                (ni_stress / ni_base) * (1.0 + multiple_change / 100.0) - 1.0
                if ni_base > 0 and ni_stress > 0
                else None
            )
            stressed_companies[ticker] = {
                "direction": direction,
                "fy2027_revenue_change_pct": _round(
                    (stress_2027["revenue_100m_cny"] / base_2027["revenue_100m_cny"] - 1) * 100
                ),
                "fy2027_parent_net_income_change_pct": _round(
                    (ni_stress / ni_base - 1) * 100 if ni_base != 0 else None
                ),
                "fy2027_fcf_change_100m_cny": _round(
                    stress_2027["fcf_100m_cny"] - base_2027["fcf_100m_cny"]
                ),
                "valuation_proxy_change_pct": _round(valuation_proxy * 100)
                if valuation_proxy is not None
                else None,
                "valuation_proxy_formula": "压力归母净利润/基准归母净利润×(1+估值倍数变动)−1",
            }
        portfolio_results = []
        for portfolio in portfolios:
            coverage, weighted_proxy, weighted_profit = 0.0, 0.0, 0.0
            for holding in portfolio["holdings"]:
                weight = holding["weight_pct"] / 100.0
                result = stressed_companies[holding["ticker"]]
                profit_change = result["fy2027_parent_net_income_change_pct"]
                if profit_change is not None:
                    weighted_profit += weight * profit_change
                proxy = result["valuation_proxy_change_pct"]
                if proxy is not None:
                    coverage += weight
                    weighted_proxy += weight * proxy
            portfolio_results.append(
                {
                    "scope": portfolio["scope"],
                    "portfolio_type": portfolio["portfolio_type"],
                    "weighted_fy2027_profit_change_pct": _round(weighted_profit),
                    "weighted_valuation_proxy_change_pct": _round(weighted_proxy / coverage)
                    if coverage > 0
                    else None,
                    "valuation_proxy_equity_weight_coverage_pct": _round(coverage * 100),
                    "limitation": "这是同一盈利口径下的压力代理，不是回测收益，也不把情景概率乘入估值。",
                }
            )
        outputs.append(
            {
                "name": name,
                "description": str(config.get("description") or ""),
                "input_shocks": deepcopy(shocks),
                "company_results": stressed_companies,
                "portfolio_results": portfolio_results,
            }
        )
    return outputs


def _sanity_checks(payload: Mapping[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    for ticker, company in payload["companies"].items():
        candidate = company["portfolio_candidate"]
        add(
            f"{ticker}.portfolio_scorecard.contract",
            candidate.get("scorecard_contract_version") == "run16.portfolio_scorecard.v2"
            and set(candidate.get("score_ledger", {})) == set(PORTFOLIO_SCORE_KEYS),
            "五项组合评分全部来自公开v2评分卡",
        )
        for score_key in PORTFOLIO_SCORE_KEYS:
            ledger = candidate["score_ledger"][score_key]
            criteria = ledger.get("criteria") or []
            recomputed = min(
                100.0,
                max(
                    0.0,
                    sum(float(row.get("awarded_points") or 0.0) for row in criteria),
                ),
            )
            add(
                f"{ticker}.portfolio_scorecard.{score_key}",
                ledger.get("basis_type") == "implied"
                and abs(float(ledger["value"]) - recomputed) <= 1e-9,
                f"公开判定项复算={recomputed:.2f}分",
            )
        prior_net_income = {
            scenario: float(company["baseline"]["parent_net_income_100m_cny"])
            for scenario in SCENARIOS
        }
        for year in map(str, FORECAST_YEARS):
            down = company["scenarios"]["downside"][year]
            base = company["scenarios"]["base"][year]
            up = company["scenarios"]["upside"][year]
            add(
                f"{ticker}.{year}.scenario_revenue_order",
                down["revenue_100m_cny"] <= base["revenue_100m_cny"] <= up["revenue_100m_cny"],
                "下行≤基准≤上行",
            )
            add(
                f"{ticker}.{year}.scenario_profit_order",
                down["parent_net_income_100m_cny"]
                <= base["parent_net_income_100m_cny"]
                <= up["parent_net_income_100m_cny"],
                "下行≤基准≤上行",
            )
            for scenario in SCENARIOS:
                row = company["scenarios"][scenario][year]
                payout = float(
                    row["input_ledger"]["dividend_payout_pct"]["value"]
                )
                expected_dividend = (
                    max(prior_net_income[scenario], 0.0) * payout / 100.0
                )
                add(
                    f"{ticker}.{scenario}.{year}.fcf_bridge",
                    abs(row["fcf_100m_cny"] - (row["ocf_100m_cny"] - row["capex_100m_cny"])) <= 0.03,
                    "自由现金流＝经营现金流−资本开支（允许展示四舍五入误差）",
                )
                add(
                    f"{ticker}.{scenario}.{year}.gross_vs_net",
                    row["gross_profit_100m_cny"] + 0.03 >= row["parent_net_income_100m_cny"],
                    "毛利润不低于归母净利润",
                )
                add(
                    f"{ticker}.{scenario}.{year}.assets_cover_parent_equity",
                    row["ending_total_assets_100m_cny"] + 0.03
                    >= row["ending_parent_equity_100m_cny"],
                    "期末总资产不低于期末归母权益",
                )
                add(
                    f"{ticker}.{scenario}.{year}.asset_floor_contract",
                    abs(
                        row["accounting_asset_floor_100m_cny"]
                        - row["ending_parent_equity_100m_cny"]
                    )
                    <= 0.03,
                    "资产会计下限仅为期末归母权益，期初非归母资金不冻结",
                )
                add(
                    f"{ticker}.{scenario}.{year}.dividend_timing",
                    abs(row["dividends_100m_cny"] - expected_dividend) <= 0.03
                    and abs(
                        row["dividend_base_parent_net_income_100m_cny"]
                        - prior_net_income[scenario]
                    )
                    <= 0.03,
                    "本年预计支付分红＝上年归母净利润×本年支付率",
                )
                prior_net_income[scenario] = float(
                    row["parent_net_income_100m_cny"]
                )
        for method in company["valuation_methods"]:
            if method.get("status") == "calculated" and "equity_value_low_100m_cny" in method:
                add(
                    f"{ticker}.{method['method']}.range_order",
                    method["equity_value_low_100m_cny"] <= method["equity_value_high_100m_cny"],
                    "估值下限≤上限",
                )
    for portfolio in payload["portfolios"]:
        total = sum(row["weight_pct"] for row in portfolio["holdings"]) + portfolio["cash_weight_pct"]
        add(
            f"{portfolio['scope']}.{portfolio['portfolio_type']}.weight_sum",
            abs(total - 100.0) <= 0.02,
            f"股票与现金权重合计={total:.4f}%",
        )
        cap = float(portfolio["policy"]["max_weight_pct"])
        direction_cap = float(portfolio["policy"].get("max_direction_weight_pct", 100.0))
        add(
            f"{portfolio['scope']}.{portfolio['portfolio_type']}.single_name_cap",
            all(row["weight_pct"] <= cap + 0.02 for row in portfolio["holdings"]),
            f"单股权重不超过{cap:.2f}%",
        )
        add(
            f"{portfolio['scope']}.{portfolio['portfolio_type']}.direction_cap",
            all(value <= direction_cap + 0.02 for value in portfolio["direction_weight_pct"].values()),
            f"单方向权重不超过{direction_cap:.2f}%",
        )
        add(
            f"{portfolio['scope']}.{portfolio['portfolio_type']}.constraints",
            portfolio["status"] == "constraint_satisfied",
            "相关性均有足够重合历史且没有未解决超限组合",
        )
        target = int(portfolio["candidate_pool"]["target_min_holdings"])
        feasible = int(portfolio["candidate_pool"]["feasible_min_holdings"])
        count = len(portfolio["holdings"])
        add(
            f"{portfolio['scope']}.{portfolio['portfolio_type']}.feasible_holding_count",
            count >= feasible,
            f"实际{count}只，门禁内可行下限{feasible}只；目标为{target}只",
        )
        risk = portfolio["portfolio_risk_diagnostics"]
        add(
            f"{portfolio['scope']}.{portfolio['portfolio_type']}.risk_contribution_sum",
            risk["risk_contribution_sum_pct"] is not None
            and abs(risk["risk_contribution_sum_pct"] - 100.0) <= 0.05,
            "单股风险贡献合计约为100%",
        )
        add(
            f"{portfolio['scope']}.{portfolio['portfolio_type']}.portfolio_volatility",
            risk["annualized_volatility_pct"] is not None
            and risk["annualized_volatility_pct"] > 0,
            "245日组合年化波动率为正且有限",
        )
        for pair in portfolio["correlation_diagnostics"]:
            values = [
                pair.get("correlation_60d"),
                pair.get("correlation_120d"),
                pair.get("correlation_245d"),
                pair.get("rolling_60d_peak"),
            ]
            add(
                f"{portfolio['scope']}.{portfolio['portfolio_type']}.correlation_bounds.{pair['left']}.{pair['right']}",
                all(value is None or -1.0001 <= value <= 1.0001 for value in values),
                "60/120/245日与滚动60日相关性均在[-1,1]",
            )
        sensitivity = portfolio["weight_sensitivity"]
        add(
            f"{portfolio['scope']}.{portfolio['portfolio_type']}.sensitivity_rank_stability",
            sensitivity["mean_rank_stability"] is not None
            and -1.0001 <= sensitivity["mean_rank_stability"] <= 1.0001,
            "相关窗口敏感性的平均排名稳定系数在[-1,1]",
        )
    failed = [row for row in checks if not row["passed"]]
    return {
        "verdict": "GREEN" if not failed else "RED",
        "checks": checks,
        "failed_count": len(failed),
        "red_rule": "任何财务恒等式、情景顺序、估值范围或组合约束失败均为RED，不自动重试。",
    }


def build_independent_model(
    actual_paths: list[Path],
    assumptions_path: Path,
    parent_equity_path: Path | None = None,
) -> dict[str, Any]:
    actual, snapshot_audit = _load_actual_snapshots(actual_paths)
    parent_equity_audit = None
    if parent_equity_path is not None:
        parent_equity_audit = _merge_parent_equity_snapshot(actual, parent_equity_path)
    else:
        # Test/legacy compatibility only.  Production Run16 passes the explicit
        # parent-equity artifact; a missing field must never be silently
        # substituted with total equity.
        for security in actual.values():
            for report in security.get("reported", {}).values():
                if report.get("PARENT_EQUITY") is None and report.get("TOT_EQUITY") is not None:
                    report["PARENT_EQUITY"] = report["TOT_EQUITY"]
                    report["PARENT_EQUITY_PROVIDER"] = "legacy_test_proxy"
    assumptions = _load_json(assumptions_path)
    if assumptions.get("template_only") is True:
        raise ModelContractError("假设文件仍标记 template_only=true；替换示例值和依据后才能运行")
    if assumptions.get("independent_before_consensus") is not True:
        raise ModelContractError("假设文件必须声明 independent_before_consensus=true")
    forbidden = _contains_forbidden_consensus_key(assumptions)
    if forbidden:
        raise ModelContractError(f"假设文件含一致预期字段或概念: {forbidden}")
    company_rows = assumptions.get("companies")
    if not isinstance(company_rows, list) or not company_rows:
        raise ModelContractError("假设文件 companies 必须是非空数组")
    companies: dict[str, Any] = {}
    candidates: list[dict[str, Any]] = []
    for company in company_rows:
        ticker = str(company.get("ticker") or "").strip().upper()
        if ticker not in actual:
            raise ModelContractError(f"{ticker} 不在 actual snapshot")
        if ticker in companies:
            raise ModelContractError(f"假设文件重复公司 {ticker}")
        if str(company.get("name") or "").strip() != str(actual[ticker]["identity"].get("name") or "").strip():
            raise ModelContractError(f"{ticker} 公司名称与 snapshot 不一致")
        if not str(company.get("economic_mechanism") or "").strip():
            raise ModelContractError(f"{ticker} 缺少 economic_mechanism")
        if str(company.get("data_quality") or "") not in {"high", "medium", "low"}:
            raise ModelContractError(f"{ticker}.data_quality 必须为 high/medium/low")
        baseline = _apply_normalization_overrides(
            ticker,
            _actual_baseline(actual[ticker]),
            company.get("normalization_overrides"),
        )
        parsed_inputs = _parse_forecast_inputs(company)
        scenario_outputs: dict[str, Any] = {}
        formula_audit: list[dict[str, Any]] = []
        for scenario in SCENARIOS:
            scenario_outputs[scenario], formulas = _build_scenario(
                ticker, baseline, parsed_inputs[scenario]
            )
            formula_audit.extend({"scenario": scenario, **row} for row in formulas)
        stability = _roe_stability(actual[ticker])
        valuations, valuation_formulas = _valuation(
            company, baseline, scenario_outputs, stability
        )
        candidate = _portfolio_candidate(
            company,
            baseline,
            scenario_outputs,
            actual[ticker],
        )
        candidates.append(candidate)
        companies[ticker] = {
            "ticker": ticker,
            "name": company["name"],
            "company_id": company.get("company_id"),
            "economic_mechanism": company["economic_mechanism"],
            "data_quality": company["data_quality"],
            "quantitative_anchor": deepcopy(company.get("quantitative_anchor", {})),
            "model_level": "简化财务桥与权益桥",
            "baseline": baseline,
            "scenarios": scenario_outputs,
            "valuation_methods": valuations,
            "roe_stability_test": stability,
            "portfolio_candidate": candidate,
            "formula_audit": formula_audit + valuation_formulas,
            "parsed_inputs": parsed_inputs,
        }
    portfolios, portfolio_formulas = _build_portfolios(assumptions, candidates, actual)
    payload: dict[str, Any] = {
        "artifact_version": "opportunity_lens.ai_financial_portfolio_freeze.v1",
        "independent_before_consensus": True,
        "external_consensus_read": False,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "as_of_date": assumptions.get("as_of_date"),
        "currency": "CNY",
        "amount_unit": "亿元人民币",
        "input_artifacts": {
            "actual_snapshots": snapshot_audit,
            "assumptions": {
                "path": str(assumptions_path),
                "file_sha256": _file_sha256(assumptions_path),
            },
            "parent_equity_fallback": parent_equity_audit,
        },
        "model_contract": {
            "forecast_years": list(FORECAST_YEARS),
            "scenarios": list(SCENARIOS),
            "financial_formula": (
                "收入由增速桥接；归母净利润＝收入×归母净利率；经营现金流与资本开支分别按收入占比；"
                "自由现金流＝经营现金流−资本开支；2026年归母权益和总资产以已披露2026Q1为桥接锚，"
                "权益只加入剩余三个季度预测利润，并扣按FY2025归母净利润估算的Q1后支付分红；"
                "2027—2028年支付分红均按上年归母净利润×当年支付率估算。总资产先按资产增速滚动，"
                "且只采用‘总资产不得低于期末归母权益’这一最低会计约束；期初负债和少数股东权益"
                "可以变化，只保留为诊断，不再冻结成资产下限。由于没有完整负债预测，ROA仍是诊断结果"
                "而非完整三表预测。"
            ),
            "portfolio_formula": (
                "从自由流通市值、等权和逆波动混合锚出发；方向、质量、财务证据、估值和风险五项分数"
                "均由公开阈值逐项加总，再形成0.85—1.15倍的有限主动倾斜，最后执行持仓、现金、单股上限、"
                "方向和相关性约束。评分未做历史收益校准，不解释为上涨概率。"
            ),
            "precision": "公开金额、比例和倍数保留两位；相关性与内部调整乘数保留四位；不把精度解释为预测确定性。",
        },
        "companies": companies,
        "portfolios": portfolios,
        "stress_tests": [],
        "portfolio_formula_audit": portfolio_formulas,
    }
    payload["stress_tests"] = _stress_tests(assumptions, companies, portfolios)
    for company in payload["companies"].values():
        company.pop("parsed_inputs", None)
    payload["sanity"] = _sanity_checks(payload)
    hash_payload = deepcopy(payload)
    payload["output_hash"] = _sha256(hash_payload)
    return payload


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actual", type=Path, action="append", required=True)
    parser.add_argument("--assumptions", type=Path, required=True)
    parser.add_argument("--parent-equity", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    payload = build_independent_model(
        [path.resolve() for path in args.actual],
        args.assumptions.resolve(),
        args.parent_equity.resolve() if args.parent_equity else None,
    )
    _write(args.output.resolve(), payload)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "output_hash": payload["output_hash"],
                "sanity_verdict": payload["sanity"]["verdict"],
                "company_count": len(payload["companies"]),
                "portfolio_count": len(payload["portfolios"]),
            },
            ensure_ascii=False,
        )
    )
    return 0 if payload["sanity"]["verdict"] == "GREEN" else 2


if __name__ == "__main__":
    raise SystemExit(main())
