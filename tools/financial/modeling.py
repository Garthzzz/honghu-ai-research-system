from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须是有限数")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} 必须是有限数")
    return number


def _hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ForecastYear:
    fiscal_year: int
    revenue: float
    gross_margin: float
    operating_expenses: float
    net_interest: float
    tax_rate: float
    minority_interest: float
    net_income: float
    diluted_shares: float
    eps: float
    operating_cash_flow: float | None = None
    capex: float | None = None
    free_cash_flow: float | None = None
    average_equity: float | None = None
    average_total_assets: float | None = None
    roe: float | None = None
    roa: float | None = None


def build_financial_bridge(
    *,
    fiscal_year: int,
    revenue: float,
    gross_margin: float,
    operating_expenses: float,
    net_interest: float,
    tax_rate: float,
    minority_interest: float,
    diluted_shares: float,
    non_operating_after_tax: float = 0.0,
    operating_cash_flow: float | None = None,
    capex: float | None = None,
    average_equity: float | None = None,
    average_total_assets: float | None = None,
) -> ForecastYear:
    """用最小可复算财务桥生成单年利润和可选 FCF，不替代完整三表。"""
    rev = _finite(revenue, "revenue")
    gm = _finite(gross_margin, "gross_margin")
    opex = _finite(operating_expenses, "operating_expenses")
    interest = _finite(net_interest, "net_interest")
    tax = _finite(tax_rate, "tax_rate")
    minority = _finite(minority_interest, "minority_interest")
    shares = _finite(diluted_shares, "diluted_shares")
    if rev < 0 or not 0 <= gm <= 1 or not 0 <= tax <= 1 or shares <= 0:
        raise ValueError("收入、毛利率、税率或股数超出经济边界")
    gross_profit = rev * gm
    pretax = gross_profit - opex - interest
    net_income = pretax * (1 - tax) - minority + _finite(non_operating_after_tax, "non_operating_after_tax")
    eps = net_income / shares
    ocf = _finite(operating_cash_flow, "operating_cash_flow") if operating_cash_flow is not None else None
    capex_value = _finite(capex, "capex") if capex is not None else None
    fcf = ocf - capex_value if ocf is not None and capex_value is not None else None
    equity = _finite(average_equity, "average_equity") if average_equity is not None else None
    assets = _finite(average_total_assets, "average_total_assets") if average_total_assets is not None else None
    if equity is not None and equity <= 0:
        raise ValueError("平均归母净资产必须为正；负净资产公司不能机械计算 ROE")
    if assets is not None and assets <= 0:
        raise ValueError("平均总资产必须为正")
    return ForecastYear(
        fiscal_year=int(fiscal_year), revenue=rev, gross_margin=gm,
        operating_expenses=opex, net_interest=interest, tax_rate=tax,
        minority_interest=minority, net_income=net_income,
        diluted_shares=shares, eps=eps, operating_cash_flow=ocf,
        capex=capex_value, free_cash_flow=fcf,
        average_equity=equity, average_total_assets=assets,
        roe=net_income / equity if equity is not None else None,
        roa=net_income / assets if assets is not None else None,
    )


def build_three_year_forecast(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    forecasts = [build_financial_bridge(**dict(row)) for row in rows]
    if len(forecasts) != 3:
        raise ValueError("标准独立预测必须明确覆盖 FY1—FY3 三个财年")
    years = [item.fiscal_year for item in forecasts]
    if years != sorted(years) or len(set(years)) != 3:
        raise ValueError("FY1—FY3 必须按三个连续且不重复财年输入")
    if any(b != a + 1 for a, b in zip(years, years[1:])):
        raise ValueError("FY1—FY3 财年必须连续")
    payload = [asdict(item) for item in forecasts]
    return {"forecast": payload, "independent_freeze_hash": _hash(payload)}


def external_event_shock(
    *,
    baseline_revenue: float,
    exposed_revenue_share: float,
    direct_share_loss: float,
    conditional_share_loss: float,
    offset_revenue: float,
    baseline_gross_margin: float,
    extra_price_pressure: float,
    variable_cost_relief: float,
    operating_expense_change: float,
    tax_rate: float,
    event_probability: float | None = None,
) -> dict[str, Any]:
    """计算“事件已发生”情景的财务桥；概率只记录，不乘入条件损益。"""
    base = _finite(baseline_revenue, "baseline_revenue")
    exposure = _finite(exposed_revenue_share, "exposed_revenue_share")
    direct = _finite(direct_share_loss, "direct_share_loss")
    conditional = _finite(conditional_share_loss, "conditional_share_loss")
    offset = _finite(offset_revenue, "offset_revenue")
    margin = _finite(baseline_gross_margin, "baseline_gross_margin")
    price = _finite(extra_price_pressure, "extra_price_pressure")
    cost_relief = _finite(variable_cost_relief, "variable_cost_relief")
    opex = _finite(operating_expense_change, "operating_expense_change")
    tax = _finite(tax_rate, "tax_rate")
    for name, value in {
        "exposure": exposure, "direct": direct,
        "conditional": conditional, "margin": margin, "price": price,
        "cost_relief": cost_relief, "tax": tax,
    }.items():
        if not 0 <= value <= 1:
            raise ValueError(f"{name} 必须位于 0—1")
    probability = _finite(event_probability, "event_probability") if event_probability is not None else None
    if probability is not None and not 0 <= probability <= 1:
        raise ValueError("event_probability 必须位于 0—1")
    share_loss = direct + (1 - direct) * conditional
    # 份额损失与剩余业务额外降价分别进入收入，避免用事件概率直接折扣收入。
    revenue_loss_rate = share_loss + (1 - share_loss) * price
    shocked_revenue = base - base * exposure * revenue_loss_rate + offset
    shocked_margin = max(-1.0, min(1.0, margin + cost_relief))
    baseline_gross_profit = base * margin
    shocked_gross_profit = shocked_revenue * shocked_margin
    pretax_change = shocked_gross_profit - baseline_gross_profit - opex
    after_tax_profit_change = pretax_change * (1 - tax)
    return {
        "revenue": shocked_revenue,
        "gross_margin": shocked_margin,
        "after_tax_profit_change": after_tax_profit_change,
        "formula": "冲击收入＝基准收入－基准收入×受影响收入占比×[条件份额损失＋(1－条件份额损失)×额外价格下降]＋抵消收入",
        "conditional_share_loss": share_loss,
        "revenue_loss_rate": revenue_loss_rate,
        "event_probability": probability,
        "probability_usage": "事件概率与条件财务影响分列，不用概率直接乘收入或利润。",
    }


def reconcile_values(
    *,
    independent: float,
    benchmark: float,
    unit: str,
    decomposition: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    own = _finite(independent, "independent")
    external = _finite(benchmark, "benchmark")
    difference = own - external
    difference_pct = difference / abs(external) if external else None
    parts = {str(k): _finite(v, str(k)) for k, v in (decomposition or {}).items()}
    residual = difference - sum(parts.values())
    return {
        "independent_value": own,
        "benchmark_value": external,
        "difference_value": difference,
        "difference_pct": difference_pct,
        "unit": unit,
        "decomposition": parts,
        "unexplained_residual": residual,
        "fully_explained": abs(residual) <= max(1e-9, abs(difference) * 0.01),
    }
