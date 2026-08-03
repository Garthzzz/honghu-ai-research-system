# -*- coding: utf-8 -*-
"""跨市场公司多期财务序列。

本模块是现有历史序列实现：A 股暂由 Tushare 提供带公告期和重述字段的原始序列，
其他市场使用 yfinance。项目的全局数据源合同已经调整为 A 股 Wind 主源、Tushare
逐字段补缺和公告口径审计；在 Wind 历史三表的报告期、公告日和重述语义完成统一
映射前，不得把本模块输出宣称为已经完成 Wind 主源合并。

金额保留原币，同时统一折算为人民币亿元和美元亿元；折算使用同一次运行取得的
即期汇率，避免把不同日期的汇率混在一张表。
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Iterable, Mapping

try:
    from .market_snapshot_utils import fetch_fx_rates, r2
    from .tushare_provider import (
        fetch_balancesheet_rows,
        fetch_cashflow_rows,
        fetch_fina_indicator_rows,
        fetch_income_rows,
        fetch_stock_company_latest,
        fnum,
        ts_code_from_ticker,
        tushare_available,
    )
except ImportError:  # pragma: no cover - direct script compatibility
    from market_snapshot_utils import fetch_fx_rates, r2
    from tushare_provider import (
        fetch_balancesheet_rows,
        fetch_cashflow_rows,
        fetch_fina_indicator_rows,
        fetch_income_rows,
        fetch_stock_company_latest,
        fnum,
        ts_code_from_ticker,
        tushare_available,
    )


TARGET_END_DATES: dict[str, str] = {}
for _year in range(2018, 2026):
    TARGET_END_DATES.update(
        {
            f"{_year}0331": f"{_year}Q1",
            f"{_year}0630": f"{_year}Q2",
            f"{_year}0930": f"{_year}Q3",
            f"{_year}1231": str(_year),
        }
    )
TARGET_END_DATES["20260331"] = "2026Q1"


BALANCE_METRICS = {
    "total_assets": "total_assets",
    "accounts_receivable": "accounts_receiv",
    "inventory": "inventories",
    "fixed_assets": "fix_assets",
    "construction_in_progress": "cip",
    "contract_liabilities": "contract_liab",
    "total_equity": "total_hldr_eqy_exc_min_int",
}


def _date_key(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y%m%d")
    text = str(value)
    return "".join(ch for ch in text if ch.isdigit())[:8]


def _latest_by_end_date(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """同一报告期优先公告日期较晚、update_flag=1 的记录。"""
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        end_date = _date_key(row.get("end_date"))
        if not end_date:
            continue
        rank = (
            str(row.get("ann_date") or ""),
            1 if str(row.get("update_flag") or "") == "1" else 0,
            str(row.get("f_ann_date") or ""),
        )
        old = best.get(end_date)
        if old is None:
            best[end_date] = row
            continue
        old_rank = (
            str(old.get("ann_date") or ""),
            1 if str(old.get("update_flag") or "") == "1" else 0,
            str(old.get("f_ann_date") or ""),
        )
        if rank > old_rank:
            best[end_date] = row
    return best


def _amounts(raw: Any, currency: str, fx: dict[str, float]) -> dict[str, Any]:
    value = fnum(raw)
    if value is None:
        return {
            "local_raw": None,
            "local_yi": None,
            "cny_yi": None,
            "usd_yi": None,
            "local_currency": currency,
            "cny_currency": "CNY",
            "usd_currency": "USD",
            "fx_to_cny": fx.get(currency),
        }
    rate = fx.get(currency)
    usd_rate = fx.get("USD")
    cny = value * rate / 1e8 if rate else None
    usd = cny / usd_rate if cny is not None and usd_rate else None
    return {
        # Keep the provider's unrounded currency-unit input so every derived
        # ratio can be reproduced exactly.  The *_yi fields remain concise
        # display values and must not be presented as the precise inputs.
        "local_raw": value,
        "local_yi": r2(value / 1e8),
        "cny_yi": r2(cny),
        "usd_yi": r2(usd),
        "local_currency": currency,
        "cny_currency": "CNY",
        "usd_currency": "USD",
        "fx_to_cny": rate,
    }


def _pct_change(current: Any, previous: Any) -> float | None:
    cur = fnum(current)
    prev = fnum(previous)
    # A percentage growth rate over a zero or negative base reverses economic
    # meaning (for example, a loss-to-profit turnaround can appear negative).
    # Callers should render those cases as 扭亏/转亏/亏损扩大或收窄 instead.
    if cur is None or prev is None or cur <= 0 or prev <= 0:
        return None
    return r2((cur / prev - 1) * 100)


def rounded_pct_change_with_interval(
    current: Any,
    previous: Any,
    *,
    display_step: float = 0.01,
    unstable_width_pct_points: float = 20.0,
) -> dict[str, float | bool] | None:
    """Recompute growth from rounded display inputs and quantify rounding risk.

    If each displayed amount is rounded to ``display_step``, the unobserved
    values lie within half a step of the display.  The returned interval is the
    resulting conservative range for the growth rate.  This is not a sampling
    confidence interval; it only exposes arithmetic sensitivity to rounding.
    """
    cur = fnum(current)
    prev = fnum(previous)
    if cur is None or prev is None or cur <= 0 or prev <= 0 or display_step <= 0:
        return None
    half = display_step / 2
    current_low = max(0.0, cur - half)
    current_high = cur + half
    previous_low = prev - half
    previous_high = prev + half
    point = r2((cur / prev - 1) * 100)
    low = r2((current_low / previous_high - 1) * 100)
    high = float("inf") if previous_low <= 0 else r2((current_high / previous_low - 1) * 100)
    width = float("inf") if not math.isfinite(high) else r2(high - low)
    return {
        "value": point,
        "low": low,
        "high": high,
        "width": width,
        "unstable": bool(width > unstable_width_pct_points),
    }


AMOUNT_FIELDS = (
    "revenue",
    "net_income",
    "rd_expense",
    "operating_cash_flow",
    "capex",
    *BALANCE_METRICS,
)


def _amount_input(amount: Mapping[str, Any] | None) -> tuple[float | None, str]:
    """Return the best local-currency input and its precision contract."""

    obj = amount or {}
    raw = fnum(obj.get("local_raw"))
    if raw is not None:
        return raw, "provider_unrounded_currency_units"
    local_yi = fnum(obj.get("local_yi"))
    if local_yi is not None:
        return local_yi, "frozen_snapshot_rounded_0.01_local_yi"
    return None, "missing"


def _change_state(current: float | None, previous: float | None) -> tuple[str, str]:
    if current is None or previous is None:
        return "insufficient_data", "缺少可比期间净利润"
    if previous == 0:
        return "zero_base", "零基数，不计算同比百分比"
    if previous < 0 < current:
        return "turnaround", "扭亏"
    if previous > 0 > current:
        return "turned_to_loss", "转亏"
    if previous < 0 and current < 0:
        if abs(current) < abs(previous):
            return "loss_narrowed", "亏损收窄"
        if abs(current) > abs(previous):
            return "loss_widened", "亏损扩大"
        return "loss_unchanged", "亏损额基本持平"
    if current == 0:
        return "zero_result", "降至盈亏平衡，不计算同比百分比"
    return "comparable_growth", "可比增长"


def build_net_income_yoy_meta(
    current_amount: Mapping[str, Any] | None,
    previous_amount: Mapping[str, Any] | None,
    *,
    currency: str,
    provider_original_value: Any = None,
    provider_original_origin: str | None = None,
    snapshot_original_value: Any = None,
) -> dict[str, Any]:
    """Build a fail-closed net-profit growth contract.

    Provider or legacy snapshot percentages are preserved for provenance but
    are never the comparison output.  A comparison value is calculated only
    from same-currency statement amounts with positive current and prior bases.
    Rounded frozen inputs additionally fail closed when their implied rounding
    interval is wider than 20 percentage points.
    """

    current, current_precision = _amount_input(current_amount)
    previous, previous_precision = _amount_input(previous_amount)
    state, state_label = _change_state(current, previous)
    valid = state == "comparable_growth"
    comparison_value: float | None = None
    rounding_interval: dict[str, Any] | None = None
    if valid:
        comparison_value = _pct_change(current, previous)
        current_display = fnum((current_amount or {}).get("local_yi"))
        previous_display = fnum((previous_amount or {}).get("local_yi"))
        if current_display is not None and previous_display is not None:
            interval = rounded_pct_change_with_interval(current_display, previous_display)
            if interval is not None:
                rounding_interval = dict(interval)
                if (
                    current_precision.startswith("frozen_snapshot")
                    or previous_precision.startswith("frozen_snapshot")
                ) and interval["unstable"]:
                    valid = False
                    comparison_value = None
                    state = "low_base_unstable"
                    state_label = "低基数，百分比不稳定"
    return {
        "state": state,
        "state_label": state_label,
        "valid_for_comparison": valid,
        "comparison_value_pct": comparison_value,
        "provider_original_value_pct": fnum(provider_original_value),
        "provider_original_origin": provider_original_origin,
        "provider_original_is_comparison_input": False,
        "snapshot_original_value_pct": fnum(snapshot_original_value),
        "current_local_input": current,
        "previous_local_input": previous,
        "currency": currency,
        "input_precision": {
            "current": current_precision,
            "previous": previous_precision,
        },
        "formula": "仅当本期和上年同期净利润均为正时，(本期÷上年同期-1)×100%",
        "rounding_interval_pct": rounding_interval,
    }


def _normalize_amount_metadata(
    amount: Any,
    *,
    currency: str,
    fx_to_cny: float | None,
) -> dict[str, Any]:
    obj = dict(amount) if isinstance(amount, Mapping) else {
        "local_raw": None,
        "local_yi": None,
        "cny_yi": None,
        "usd_yi": None,
    }
    obj.setdefault("local_raw", None)
    obj.setdefault("local_yi", None)
    obj.setdefault("cny_yi", None)
    obj.setdefault("usd_yi", None)
    obj["local_currency"] = currency
    obj["cny_currency"] = "CNY"
    obj["usd_currency"] = "USD"
    obj["fx_to_cny"] = fx_to_cny
    return obj


def annotate_financial_series(
    result: dict[str, Any],
    *,
    legacy_snapshot: bool = False,
) -> dict[str, Any]:
    """Add currency, margin-period and growth-comparability contracts in place."""

    currency = str(result.get("currency") or "USD").upper()
    fx_to_cny = fnum(result.get("fx_to_cny"))
    periods = result.get("periods") or []
    by_period = {str(row.get("period")): row for row in periods}
    source = str(result.get("source") or "")
    for row in periods:
        for field in AMOUNT_FIELDS:
            row[field] = _normalize_amount_metadata(
                row.get(field), currency=currency, fx_to_cny=fx_to_cny
            )

        # Preserve the provider/report gross-margin field and label its period.
        row["gross_margin_meta"] = {
            "period": row.get("period"),
            "end_date": row.get("end_date"),
            "value_pct": row.get("gross_margin"),
            "basis": (
                "Tushare fina_indicator.grossprofit_margin provider field"
                if source == "tushare"
                else "yfinance GrossProfit ÷ TotalRevenue"
            ),
            "provider_reported": source == "tushare",
        }

        # Net margin is always rebuilt from the same-period revenue and the
        # stored attributable/preferred net-income series.  The old provider
        # ratio remains available only as provenance.
        old_net_margin = row.get(
            "provider_net_margin_original_pct", row.get("net_margin")
        )
        revenue_input, revenue_precision = _amount_input(row.get("revenue"))
        net_income_input, net_income_precision = _amount_input(row.get("net_income"))
        rebuilt_net_margin = (
            r2(net_income_input / revenue_input * 100)
            if net_income_input is not None and revenue_input not in (None, 0)
            else None
        )
        row["provider_net_margin_original_pct"] = old_net_margin
        row["net_margin"] = rebuilt_net_margin
        row["net_margin_meta"] = {
            "period": row.get("period"),
            "end_date": row.get("end_date"),
            "value_pct": rebuilt_net_margin,
            "formula": "同期间归母/可归属净利润÷营业收入×100%",
            "net_income_basis": row.get("net_income_basis")
            or (
                "Tushare n_income_attr_p优先，缺失时n_income"
                if source == "tushare"
                else "yfinance NetIncomeCommonStockholders优先，缺失时NetIncome"
            ),
            "input_precision": {
                "revenue": revenue_precision,
                "net_income": net_income_precision,
            },
            "provider_original_value_pct": old_net_margin,
            "provider_original_is_output": False,
        }

    for row in periods:
        label = str(row.get("period"))
        prior_label = _prior_period_label(label)
        prior_row = by_period.get(prior_label or "")
        existing_meta = row.get("net_income_yoy_meta") or {}
        snapshot_original = existing_meta.get(
            "snapshot_original_value_pct", row.get("net_income_yoy")
        )
        provider_original = row.get("net_income_yoy_provider_original")
        provider_origin = row.get("net_income_yoy_provider_origin")
        if provider_original is None and legacy_snapshot and source == "tushare":
            provider_original = snapshot_original
            provider_origin = (
                "frozen snapshot v1 net_income_yoy；Tushare provider原值，"
                "原始字段名未在v1中单独保存"
            )
        elif provider_origin is None and provider_original is not None:
            provider_origin = "Tushare fina_indicator.netprofit_yoy"
        meta = build_net_income_yoy_meta(
            row.get("net_income"),
            (prior_row or {}).get("net_income"),
            currency=currency,
            provider_original_value=provider_original,
            provider_original_origin=provider_origin,
            snapshot_original_value=snapshot_original,
        )
        if source != "tushare" and legacy_snapshot:
            meta["legacy_snapshot_derived_value_pct"] = fnum(snapshot_original)
            meta["legacy_snapshot_value_origin"] = (
                "旧版基于yfinance报表金额派生，不是provider直接披露同比"
            )
        row["net_income_yoy_meta"] = meta
        row["net_income_yoy_state"] = meta["state"]
        row["net_income_yoy_valid_for_comparison"] = meta["valid_for_comparison"]
        row["net_income_yoy"] = meta["comparison_value_pct"]
    result["currency_views"] = {
        "local": currency,
        "renminbi": "CNY",
        "us_dollar": "USD",
    }
    result["comparability_contract_version"] = "pcb_financial_comparability.v2"
    return result


def _row_value(frame: Any, names: Iterable[str], column: Any) -> float | None:
    for name in names:
        try:
            if name in frame.index:
                return fnum(frame.at[name, column])
        except Exception:
            continue
    return None


def _row_value_with_name(
    frame: Any, names: Iterable[str], column: Any
) -> tuple[float | None, str | None]:
    for name in names:
        try:
            if name in frame.index:
                return fnum(frame.at[name, column]), name
        except Exception:
            continue
    return None, None


def _prior_period_label(label: str) -> str | None:
    year_text = label[:4]
    if not year_text.isdigit():
        return None
    suffix = label[4:]
    return f"{int(year_text) - 1}{suffix}"


def _coverage(periods: list[dict[str, Any]], *, source_limitations: str) -> dict[str, Any]:
    returned = {str(row.get("period")) for row in periods}
    requested = list(TARGET_END_DATES.values())
    return {
        "requested_start_year": 2018,
        "requested_through": "2026Q1",
        "requested_period_count": len(requested),
        "returned_period_count": len(returned),
        "missing_periods": [period for period in requested if period not in returned],
        "source_limitations": source_limitations,
    }


def _from_tushare(ticker: str, fx: dict[str, float]) -> dict[str, Any]:
    ts_code = ts_code_from_ticker(ticker)
    if not ts_code:
        return {"source": "tushare", "error": "不是可识别的 A 股 ticker。", "periods": []}
    years = tuple(str(year) for year in range(2018, 2027))
    income = _latest_by_end_date(fetch_income_rows(ts_code, years=years))
    indicators = _latest_by_end_date(fetch_fina_indicator_rows(ts_code, years=years))
    cashflows = _latest_by_end_date(fetch_cashflow_rows(ts_code, years=years))
    balances = _latest_by_end_date(fetch_balancesheet_rows(ts_code, years=years))
    company_snapshot = fetch_stock_company_latest(ts_code) or {}
    periods: list[dict[str, Any]] = []
    raw_by_period: dict[str, dict[str, Any]] = {}
    for end_date, label in TARGET_END_DATES.items():
        inc = income.get(end_date, {})
        ind = indicators.get(end_date, {})
        cash = cashflows.get(end_date, {})
        balance = balances.get(end_date, {})
        if not inc and not ind and not cash and not balance:
            continue
        revenue_raw = fnum(inc.get("total_revenue") or inc.get("revenue"))
        attributable_raw = fnum(inc.get("n_income_attr_p"))
        net_income_raw = (
            attributable_raw
            if attributable_raw is not None
            else fnum(inc.get("n_income"))
        )
        rd_raw = fnum(inc.get("rd_exp"))
        ocf_raw = fnum(cash.get("n_cashflow_act"))
        capex_raw = fnum(cash.get("c_pay_acq_const_fiolta"))
        raw_by_period[label] = {"revenue": revenue_raw, "net_income": net_income_raw}
        row = {
                "period": label,
                "end_date": end_date,
                "period_type": "quarterly" if "Q" in label else "annual",
                "statement_basis": "year_to_date_cumulative",
                "announcement_date": str(
                    inc.get("ann_date")
                    or ind.get("ann_date")
                    or cash.get("ann_date")
                    or balance.get("ann_date")
                    or ""
                ),
                "revenue": _amounts(revenue_raw, "CNY", fx),
                "net_income": _amounts(net_income_raw, "CNY", fx),
                "net_income_basis": (
                    "Tushare income.n_income_attr_p"
                    if attributable_raw is not None
                    else "Tushare income.n_income"
                ),
                "net_income_yoy_provider_original": r2(ind.get("netprofit_yoy")),
                "net_income_yoy_provider_origin": "Tushare fina_indicator.netprofit_yoy",
                "rd_expense": _amounts(rd_raw, "CNY", fx),
                "operating_cash_flow": _amounts(ocf_raw, "CNY", fx),
                "capex": _amounts(abs(capex_raw) if capex_raw is not None else None, "CNY", fx),
                "gross_margin": r2(ind.get("grossprofit_margin")),
                "net_margin": r2(ind.get("netprofit_margin")),
                "roe": r2(ind.get("roe")),
                "roa": r2(ind.get("roa")),
                "rd_ratio": r2(ind.get("rd_exp_to_operting_revenue"))
                if ind.get("rd_exp_to_operting_revenue") is not None
                else r2(abs(rd_raw) / abs(revenue_raw) * 100)
                if rd_raw is not None and revenue_raw not in (None, 0)
                else None,
                "source": "Tushare income/fina_indicator/cashflow/balancesheet",
                "currency": "CNY",
            }
        for output_key, source_key in BALANCE_METRICS.items():
            row[output_key] = _amounts(balance.get(source_key), "CNY", fx)
        periods.append(row)
    for row in periods:
        prior = _prior_period_label(row["period"])
        row["revenue_yoy"] = (
            _pct_change(
                raw_by_period.get(row["period"], {}).get("revenue"),
                raw_by_period.get(prior or "", {}).get("revenue"),
            )
            if prior
            else None
        )
    result = {
        "source": "tushare",
        "symbol": ts_code,
        "currency": "CNY",
        "fx_to_cny": 1.0,
        "fx_as_of": datetime.now().date().isoformat(),
        "employee_snapshot": {
            "employees": int(fnum(company_snapshot.get("employees")))
            if fnum(company_snapshot.get("employees")) is not None
            else None,
            "snapshot_observed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "basis": "Tushare stock_company 当前公司档案快照；接口不提供逐年员工历史。",
            "main_business": company_snapshot.get("main_business"),
            "business_scope": company_snapshot.get("business_scope"),
        },
        "periods": periods,
    }
    result["coverage"] = _coverage(
        periods,
        source_limitations=(
            "Tushare 财务报表为累计口径；员工数仅有当前公司档案快照，逐年员工历史需回查年报。"
        ),
    )
    return annotate_financial_series(result)


def _from_yfinance(symbol: str, fx: dict[str, float]) -> dict[str, Any]:
    import yfinance as yf  # type: ignore

    ticker = yf.Ticker(symbol)
    info = ticker.get_info()
    currency = str(info.get("financialCurrency") or info.get("currency") or "USD").upper()
    annual_income = ticker.get_income_stmt(freq="yearly")
    quarterly_income = ticker.get_income_stmt(freq="quarterly")
    annual_cashflow = ticker.get_cashflow(freq="yearly")
    quarterly_cashflow = ticker.get_cashflow(freq="quarterly")
    annual_balance = ticker.get_balance_sheet(freq="yearly")
    quarterly_balance = ticker.get_balance_sheet(freq="quarterly")

    income_names = {
        "revenue": ("TotalRevenue", "OperatingRevenue"),
        "net_income": ("NetIncomeCommonStockholders", "NetIncome", "NetIncomeIncludingNoncontrollingInterests"),
        "gross_profit": ("GrossProfit",),
        "rd": ("ResearchAndDevelopment", "ResearchAndDevelopmentExpense", "ResearchDevelopment"),
    }
    cash_names = {
        "ocf": ("OperatingCashFlow", "TotalCashFromOperatingActivities"),
        "capex": ("CapitalExpenditure", "CapitalExpenditures"),
    }
    balance_names = {
        "total_assets": ("TotalAssets",),
        "accounts_receivable": ("AccountsReceivable", "Receivables", "GrossAccountsReceivable"),
        "inventory": ("Inventory",),
        "fixed_assets": ("NetPPE", "PropertyPlantAndEquipmentNet"),
        "construction_in_progress": ("ConstructionInProgress",),
        "contract_liabilities": ("CurrentDeferredRevenue", "DeferredRevenue"),
        "total_equity": ("StockholdersEquity", "TotalStockholderEquity", "CommonStockEquity"),
    }

    def columns_by_date(frame: Any) -> dict[str, Any]:
        return {_date_key(column): column for column in getattr(frame, "columns", [])}

    annual_columns = columns_by_date(annual_income)
    quarterly_columns = columns_by_date(quarterly_income)
    annual_cf_columns = columns_by_date(annual_cashflow)
    quarterly_cf_columns = columns_by_date(quarterly_cashflow)
    annual_bs_columns = columns_by_date(annual_balance)
    quarterly_bs_columns = columns_by_date(quarterly_balance)
    periods: list[dict[str, Any]] = []
    raw_by_period: dict[str, dict[str, Any]] = {}

    for end_date, label in TARGET_END_DATES.items():
        is_quarter = "Q" in label
        income_frame = quarterly_income if is_quarter else annual_income
        income_column = (quarterly_columns if is_quarter else annual_columns).get(end_date)
        cf_frame = quarterly_cashflow if is_quarter else annual_cashflow
        cf_column = (quarterly_cf_columns if is_quarter else annual_cf_columns).get(end_date)
        balance_frame = quarterly_balance if is_quarter else annual_balance
        balance_column = (quarterly_bs_columns if is_quarter else annual_bs_columns).get(end_date)
        if income_column is None and cf_column is None and balance_column is None:
            continue
        revenue_raw = _row_value(income_frame, income_names["revenue"], income_column) if income_column is not None else None
        if income_column is not None:
            net_income_raw, net_income_field = _row_value_with_name(
                income_frame, income_names["net_income"], income_column
            )
        else:
            net_income_raw, net_income_field = None, None
        gross_profit_raw = _row_value(income_frame, income_names["gross_profit"], income_column) if income_column is not None else None
        rd_raw = _row_value(income_frame, income_names["rd"], income_column) if income_column is not None else None
        ocf_raw = _row_value(cf_frame, cash_names["ocf"], cf_column) if cf_column is not None else None
        capex_raw = _row_value(cf_frame, cash_names["capex"], cf_column) if cf_column is not None else None
        balance_raw = {
            key: _row_value(balance_frame, names, balance_column)
            if balance_column is not None
            else None
            for key, names in balance_names.items()
        }
        equity_raw = balance_raw["total_equity"]
        raw_by_period[label] = {"revenue": revenue_raw, "net_income": net_income_raw}
        row = {
                "period": label,
                "end_date": end_date,
                "period_type": "quarterly" if is_quarter else "annual",
                "statement_basis": "single_quarter" if is_quarter else "fiscal_year",
                "announcement_date": "",
                "revenue": _amounts(revenue_raw, currency, fx),
                "net_income": _amounts(net_income_raw, currency, fx),
                "net_income_basis": (
                    f"yfinance {net_income_field}"
                    if net_income_field
                    else "yfinance net income unavailable"
                ),
                "rd_expense": _amounts(rd_raw, currency, fx),
                "operating_cash_flow": _amounts(ocf_raw, currency, fx),
                "capex": _amounts(abs(capex_raw) if capex_raw is not None else None, currency, fx),
                "gross_margin": r2(gross_profit_raw / revenue_raw * 100)
                if gross_profit_raw is not None and revenue_raw not in (None, 0)
                else None,
                "net_margin": r2(net_income_raw / revenue_raw * 100)
                if net_income_raw is not None and revenue_raw not in (None, 0)
                else None,
                "roe": r2(net_income_raw / equity_raw * 100)
                if net_income_raw is not None and equity_raw not in (None, 0)
                else None,
                "roa": r2(net_income_raw / balance_raw["total_assets"] * 100)
                if net_income_raw is not None and balance_raw["total_assets"] not in (None, 0)
                else None,
                "rd_ratio": r2(abs(rd_raw) / abs(revenue_raw) * 100)
                if rd_raw is not None and revenue_raw not in (None, 0)
                else None,
                "source": "Yahoo Finance/yfinance statement",
                "currency": currency,
            }
        for output_key, raw_value in balance_raw.items():
            row[output_key] = _amounts(raw_value, currency, fx)
        periods.append(row)
    for row in periods:
        prior = _prior_period_label(row["period"])
        row["revenue_yoy"] = _pct_change(raw_by_period.get(row["period"], {}).get("revenue"), raw_by_period.get(prior, {}).get("revenue")) if prior else None
    result = {
        "source": "yfinance",
        "symbol": symbol,
        "currency": currency,
        "fx_to_cny": fx.get(currency),
        "fx_as_of": datetime.now().date().isoformat(),
        "employee_snapshot": {
            "employees": int(fnum(info.get("fullTimeEmployees")))
            if fnum(info.get("fullTimeEmployees")) is not None
            else None,
            "snapshot_observed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "basis": "yfinance get_info 当前 fullTimeEmployees 快照；不代表报告期末且无逐年历史。",
        },
        "periods": periods,
    }
    result["coverage"] = _coverage(
        periods,
        source_limitations=(
            "yfinance 通常只返回最近约 4 个年度和最近若干季度，无法满足 2018 年以来完整历史；"
            "缺失期间必须回查交易所年报，不做插值。"
        ),
    )
    return annotate_financial_series(result)


def fetch_company_financial_series(
    ticker: str | None,
    *,
    yf_symbol: str | None = None,
    fx: dict[str, float] | None = None,
) -> dict[str, Any]:
    """尝试读取 2018 年以来年度/季度序列；失败或源端缺口均返回可审计原因。"""
    rates = fx or fetch_fx_rates()
    if ticker and ts_code_from_ticker(ticker) and tushare_available():
        try:
            return _from_tushare(ticker, rates)
        except Exception as exc:
            tushare_error = f"Tushare {type(exc).__name__}: {str(exc)[:180]}"
    else:
        tushare_error = None
    symbol = yf_symbol or ticker
    if not symbol:
        return {"error": "未上市或无可用 ticker。", "periods": [], "source": "none"}
    try:
        result = _from_yfinance(symbol, rates)
        if tushare_error:
            result["tushare_error"] = tushare_error
        return result
    except Exception as exc:
        return {
            "symbol": symbol,
            "source": "yfinance",
            "error": f"yfinance {type(exc).__name__}: {str(exc)[:200]}",
            "tushare_error": tushare_error,
            "periods": [],
        }
