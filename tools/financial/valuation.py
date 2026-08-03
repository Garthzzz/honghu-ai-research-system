from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import median
from typing import Any, Iterable, Mapping, Sequence


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须是有限数")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} 必须是有限数")
    return result


def forward_pe_valuation(*, forecast_net_income: float, target_pe: float, net_cash_adjustment: float = 0.0, diluted_shares: float | None = None) -> dict[str, float | str | None]:
    profit = _finite(forecast_net_income, "forecast_net_income")
    multiple = _finite(target_pe, "target_pe")
    adjustment = _finite(net_cash_adjustment, "net_cash_adjustment")
    if profit <= 0 or multiple <= 0:
        raise ValueError("Forward PE 只适用于正的正常化盈利和正倍数")
    value = profit * multiple + adjustment
    shares = _finite(diluted_shares, "diluted_shares") if diluted_shares is not None else None
    if shares is not None and shares <= 0:
        raise ValueError("稀释股数必须为正")
    return {
        "equity_value": value,
        "per_share_value": value / shares if shares else None,
        "formula": "股权价值＝预测归母净利润×目标市盈率＋额外净现金调整；每股价值＝股权价值÷稀释后股数",
    }


def target_multiple_bridge(*, base_multiple: float, adjustments: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Keep every qualitative premium/discount visible instead of hiding a chosen multiple."""
    base = _finite(base_multiple, "base_multiple")
    if base <= 0:
        raise ValueError("基础倍数必须为正")
    rows: list[dict[str, Any]] = []
    total = base
    for index, raw in enumerate(adjustments, start=1):
        value = _finite(raw.get("multiple_points"), f"adjustment_{index}")
        label = str(raw.get("label") or "").strip()
        reason = str(raw.get("reason") or "").strip()
        source_ref = str(raw.get("source_ref") or "").strip()
        as_of_date = str(raw.get("as_of_date") or "").strip()
        if not all((label, reason, source_ref, as_of_date)):
            raise ValueError("每项倍数调整必须有名称、理由、来源和截至日")
        total += value
        rows.append({**dict(raw), "multiple_points": value, "cumulative_multiple": total})
    if total <= 0:
        raise ValueError("调整后的目标倍数必须为正")
    return {
        "base_multiple": base, "adjustments": rows, "target_multiple": total,
        "formula": "目标倍数＝历史或同行基础倍数＋逐项可审计溢价/折价",
    }


def peer_multiple_valuation(
    peers: Iterable[Mapping[str, Any]],
    *,
    forecast_metric: float,
    metric_name: str,
    adjustments: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    rows = [dict(row) for row in peers if row.get("multiple") is not None]
    if len(rows) < 3:
        raise ValueError("同行倍数至少需要三个可比公司")
    values = [_finite(row["multiple"], "peer_multiple") for row in rows]
    if any(value <= 0 for value in values):
        raise ValueError("同行倍数必须为正")
    bridge = target_multiple_bridge(base_multiple=median(values), adjustments=adjustments)
    fundamental = _finite(forecast_metric, "forecast_metric")
    return {
        "peer_count": len(rows), "peers": rows, "metric_name": metric_name,
        "peer_median_multiple": median(values), "multiple_bridge": bridge,
        "equity_value": fundamental * bridge["target_multiple"],
        "formula": f"股权价值＝本公司预测{metric_name}×经差异调整后的同行倍数",
    }


def valuation_method_gate(
    *,
    normalized_profit_positive: bool,
    ebitda_positive: bool,
    revenue_economically_meaningful: bool,
    full_fcff_inputs_available: bool,
    book_value_economically_meaningful: bool,
    is_financial_company: bool = False,
    is_cyclical_peak_or_trough: bool = False,
    segment_profit_available: bool = False,
    high_leverage: bool = False,
    asset_nav_inputs_available: bool = False,
    pipeline_rnpv_inputs_available: bool = False,
    dividend_model_applicable: bool = False,
    sustainable_roe_available: bool = False,
    cost_of_equity_available: bool = False,
    roe_fade_period_supported: bool = False,
    cycle_position_assessed: bool = False,
) -> dict[str, dict[str, str]]:
    """Return economic applicability; it does not choose assumptions or values."""
    pe_ok = normalized_profit_positive and not is_cyclical_peak_or_trough
    pb_roe_ready = book_value_economically_meaningful and (
        not is_cyclical_peak_or_trough or cycle_position_assessed
    )
    wilcox_ready = (
        pb_roe_ready and sustainable_roe_available
        and cost_of_equity_available and roe_fade_period_supported
    )
    result = {
        "forward_pe": {"status": "core_or_reference" if pe_ok else "not_applicable", "reason": "正常化盈利为正且不是周期极值" if pe_ok else "亏损、利润接近零或处于周期极值"},
        "ev_ebitda": {"status": "core_or_reference" if ebitda_positive and not is_financial_company else "not_applicable", "reason": "EBITDA为正且企业价值桥适用" if ebitda_positive and not is_financial_company else "EBITDA或金融企业口径不适用"},
        "ps": {"status": "reference" if revenue_economically_meaningful else "not_applicable", "reason": "收入仍具有经济意义，需由长期利润率约束" if revenue_economically_meaningful else "收入不能代表可实现经济价值"},
        "dcf_fcff": {"status": "core_or_reference" if full_fcff_inputs_available and not is_financial_company else "diagnostic_or_not_applicable", "reason": "CAPEX、营运资本、折旧、税率和经营预测可解释" if full_fcff_inputs_available and not is_financial_company else "三表/FCFF输入不完整或金融企业口径不适用"},
        "pb_roe": {
            "status": "core_or_reference" if pb_roe_ready else "diagnostic_or_not_applicable",
            "reason": (
                "账面价值与资产回报具有经济意义，周期公司已判断ROE所处阶段"
                if pb_roe_ready and is_cyclical_peak_or_trough else
                "账面价值与资产回报具有经济意义"
                if pb_roe_ready else
                "账面价值不能充分表示核心经济资产，或周期公司尚未判断ROE所处阶段"
            ),
        },
        "wilcox_pb_roe": {
            "status": "reference" if wilcox_ready else "diagnostic_or_not_applicable",
            "reason": (
                "可持续预期ROE、股权成本、回归长期均衡年限和终端PB均可解释"
                if wilcox_ready else
                "缺少可持续预期ROE、股权成本或ROE回归年限，不能发布理论PB"
            ),
        },
        "pb_roa": {"status": "required_diagnostic" if high_leverage else "diagnostic", "reason": "高杠杆必须拆解ROE来源" if high_leverage else "用于区分资产效率与杠杆贡献"},
        "sotp": {"status": "reference" if segment_profit_available else "not_applicable", "reason": "分部利润和边界可得" if segment_profit_available else "分部利润不足，不制造分部估值"},
        "nav": {"status": "core_or_reference" if asset_nav_inputs_available else "not_applicable", "reason": "可识别资产、负债和折价口径齐全" if asset_nav_inputs_available else "资产边界、储量/项目价值或负债口径不足"},
        "rnpv": {"status": "core_or_reference" if pipeline_rnpv_inputs_available else "not_applicable", "reason": "管线价值、成功概率、时间和成本可审计" if pipeline_rnpv_inputs_available else "管线现金流或概率依据不足"},
        "ddm": {"status": "core_or_reference" if dividend_model_applicable else "not_applicable", "reason": "分红能力、资本约束和长期派息路径可解释" if dividend_model_applicable else "分红路径不能代表可分配价值"},
        "reverse_valuation": {"status": "required_diagnostic", "reason": "正式估值必须解释当前价格隐含条件"},
    }
    return result


def ev_ebitda_valuation(*, forecast_ebitda: float, target_multiple: float, net_debt: float, minority_interest: float = 0.0, non_operating_assets: float = 0.0) -> dict[str, float | str]:
    ebitda = _finite(forecast_ebitda, "forecast_ebitda")
    multiple = _finite(target_multiple, "target_multiple")
    if ebitda <= 0 or multiple <= 0:
        raise ValueError("EV/EBITDA 只适用于正 EBITDA 和正倍数")
    enterprise_value = ebitda * multiple
    equity_value = enterprise_value - _finite(net_debt, "net_debt") - _finite(minority_interest, "minority_interest") + _finite(non_operating_assets, "non_operating_assets")
    return {"enterprise_value": enterprise_value, "equity_value": equity_value, "formula": "股权价值＝预测EBITDA×目标EV/EBITDA－净债务－少数股东权益＋非经营资产"}


def ps_valuation(*, forecast_revenue: float, target_ps: float, net_cash_adjustment: float = 0.0) -> dict[str, float | str]:
    revenue = _finite(forecast_revenue, "forecast_revenue")
    multiple = _finite(target_ps, "target_ps")
    if revenue <= 0 or multiple <= 0:
        raise ValueError("PS 估值需要正收入和正倍数")
    return {"equity_value": revenue * multiple + _finite(net_cash_adjustment, "net_cash_adjustment"), "formula": "股权价值＝预测收入×目标市销率＋额外净现金调整"}


def sotp_valuation(
    segments: Iterable[Mapping[str, Any]],
    *,
    net_debt: float,
    minority_interest: float = 0.0,
    non_operating_assets: float = 0.0,
) -> dict[str, Any]:
    """Sum auditable segment enterprise values without inventing segment profit."""
    rows: list[dict[str, Any]] = []
    for index, raw in enumerate(segments, start=1):
        row = dict(raw)
        name = str(row.get("name") or "").strip()
        method = str(row.get("method") or "").strip()
        source_ref = str(row.get("source_ref") or "").strip()
        as_of_date = str(row.get("as_of_date") or "").strip()
        if not all((name, method, source_ref, as_of_date)):
            raise ValueError("每个 SOTP 分部必须有名称、方法、来源和截至日")
        value = _finite(row.get("enterprise_value"), f"segment_{index}_enterprise_value")
        if value < 0:
            raise ValueError("SOTP 分部企业价值不能为负；困境负价值应在负债桥单列")
        rows.append({**row, "enterprise_value": value})
    if len(rows) < 2:
        raise ValueError("SOTP 至少需要两个边界清楚且可独立估值的分部")
    enterprise_value = sum(row["enterprise_value"] for row in rows)
    equity_value = (
        enterprise_value - _finite(net_debt, "net_debt")
        - _finite(minority_interest, "minority_interest")
        + _finite(non_operating_assets, "non_operating_assets")
    )
    return {
        "segments": rows, "enterprise_value": enterprise_value, "equity_value": equity_value,
        "formula": "股权价值＝各可独立估值分部企业价值之和－净债务－少数股东权益＋非经营资产",
        "boundary": "只有分部边界和利润/现金流足以独立估值时使用；不得用集团利润重复计入多个分部。",
    }


def nav_valuation(
    assets: Iterable[Mapping[str, Any]],
    liabilities: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Adjusted NAV with every asset haircut and liability visible."""
    asset_rows: list[dict[str, Any]] = []
    for index, raw in enumerate(assets, start=1):
        row = dict(raw)
        name = str(row.get("name") or "").strip()
        source_ref = str(row.get("source_ref") or "").strip()
        as_of_date = str(row.get("as_of_date") or "").strip()
        if not all((name, source_ref, as_of_date)):
            raise ValueError("每项 NAV 资产必须有名称、来源和截至日")
        value = _finite(row.get("gross_value"), f"asset_{index}_gross_value")
        haircut = _finite(row.get("haircut", 0.0), f"asset_{index}_haircut")
        if value < 0 or not 0 <= haircut <= 1:
            raise ValueError("NAV 资产价值须非负，折价率须位于 0—1")
        asset_rows.append({**row, "gross_value": value, "haircut": haircut, "adjusted_value": value * (1 - haircut)})
    if not asset_rows:
        raise ValueError("NAV 至少需要一项可识别资产")
    liability_rows: list[dict[str, Any]] = []
    for index, raw in enumerate(liabilities, start=1):
        row = dict(raw)
        name = str(row.get("name") or "").strip()
        source_ref = str(row.get("source_ref") or "").strip()
        as_of_date = str(row.get("as_of_date") or "").strip()
        if not all((name, source_ref, as_of_date)):
            raise ValueError("每项 NAV 负债必须有名称、来源和截至日")
        value = _finite(row.get("value"), f"liability_{index}_value")
        if value < 0:
            raise ValueError("NAV 负债金额必须以非负扣减额输入")
        liability_rows.append({**row, "value": value})
    adjusted_assets = sum(row["adjusted_value"] for row in asset_rows)
    total_liabilities = sum(row["value"] for row in liability_rows)
    return {
        "assets": asset_rows, "liabilities": liability_rows,
        "adjusted_assets": adjusted_assets, "total_liabilities": total_liabilities,
        "equity_value": adjusted_assets - total_liabilities,
        "formula": "调整后净资产价值＝Σ[资产毛价值×(1－逐项折价率)]－Σ负债与其他优先索取权",
    }


def risk_adjusted_npv(
    projects: Iterable[Mapping[str, Any]],
    *,
    discount_rate: float,
    net_cash_adjustment: float = 0.0,
) -> dict[str, Any]:
    """Small, auditable rNPV primitive for pipeline/project companies."""
    rate = _finite(discount_rate, "discount_rate")
    if not 0 < rate < 1:
        raise ValueError("rNPV 折现率必须位于 0—1")
    rows: list[dict[str, Any]] = []
    for index, raw in enumerate(projects, start=1):
        row = dict(raw)
        name = str(row.get("name") or "").strip()
        source_ref = str(row.get("source_ref") or "").strip()
        probability_basis = str(row.get("probability_basis") or "").strip()
        as_of_date = str(row.get("as_of_date") or "").strip()
        if not all((name, source_ref, probability_basis, as_of_date)):
            raise ValueError("每个 rNPV 项目必须有名称、来源、概率依据和截至日")
        success_value = _finite(row.get("success_value"), f"project_{index}_success_value")
        probability = _finite(row.get("success_probability"), f"project_{index}_success_probability")
        years = _finite(row.get("years_to_value"), f"project_{index}_years_to_value")
        cost_pv = _finite(row.get("cost_to_complete_pv", 0.0), f"project_{index}_cost_to_complete_pv")
        if success_value < 0 or cost_pv < 0 or years < 0 or not 0 <= probability <= 1:
            raise ValueError("rNPV 项目价值、成本、时间或成功概率超出边界")
        value = success_value * probability / ((1 + rate) ** years) - cost_pv
        rows.append({
            **row, "success_value": success_value, "success_probability": probability,
            "years_to_value": years, "cost_to_complete_pv": cost_pv,
            "risk_adjusted_present_value": value,
        })
    if not rows:
        raise ValueError("rNPV 至少需要一个可审计项目")
    adjustment = _finite(net_cash_adjustment, "net_cash_adjustment")
    return {
        "projects": rows, "equity_value": sum(row["risk_adjusted_present_value"] for row in rows) + adjustment,
        "net_cash_adjustment": adjustment,
        "formula": "股权价值＝Σ[成功后价值×成功概率÷(1＋折现率)^兑现年限－完成成本现值]＋净现金调整",
        "boundary": "成功概率必须注明参考类别或专家判断依据；rNPV 不把主观概率伪装成历史频率。",
    }


def dividend_discount_valuation(
    *,
    dividend_path: Sequence[float],
    cost_of_equity: float,
    terminal_growth: float,
) -> dict[str, Any]:
    dividends = [_finite(value, f"dividend_{index}") for index, value in enumerate(dividend_path, start=1)]
    if len(dividends) < 3 or any(value < 0 for value in dividends):
        raise ValueError("DDM 至少需要三年非负可分配股利路径")
    k = _finite(cost_of_equity, "cost_of_equity")
    g = _finite(terminal_growth, "terminal_growth")
    if not 0 < k < 1 or not -0.2 < g < k:
        raise ValueError("DDM 股权成本与永续增长率不满足边界")
    present_values = [value / ((1 + k) ** year) for year, value in enumerate(dividends, start=1)]
    terminal_value = dividends[-1] * (1 + g) / (k - g)
    terminal_present = terminal_value / ((1 + k) ** len(dividends))
    equity_value = sum(present_values) + terminal_present
    return {
        "equity_value": equity_value,
        "forecast_dividend_present_value": sum(present_values),
        "terminal_value_present_value": terminal_present,
        "terminal_value_share": terminal_present / equity_value if equity_value else None,
        "annual_trace": [
            {"year": year, "dividend": value, "present_value": present}
            for year, (value, present) in enumerate(zip(dividends, present_values), start=1)
        ],
        "formula": "股权价值＝预测期各年可分配股利折现值之和＋永续股利终值折现值",
        "terminal_formula": "终值＝最后一年股利×(1＋永续增长率)÷(股权成本－永续增长率)",
    }


def wilcox_pb_roe_valuation(
    *,
    expected_sustainable_roe: float,
    cost_of_equity: float,
    fade_years: float,
    terminal_pb: float = 1.0,
    opening_book_value: float | None = None,
    diluted_shares: float | None = None,
) -> dict[str, Any]:
    """Wilcox log-linear PB-ROE bridge with explicit terminal-PB assumption.

    ROE and cost of equity are decimals (15% = 0.15).  This is a theoretical
    reference path, not a substitute for an auditable earnings/book-value
    forecast or for cycle-position analysis.
    """
    roe = _finite(expected_sustainable_roe, "expected_sustainable_roe")
    k = _finite(cost_of_equity, "cost_of_equity")
    years = _finite(fade_years, "fade_years")
    terminal = _finite(terminal_pb, "terminal_pb")
    if not -1 < roe < 2 or not 0 < k < 1:
        raise ValueError("Wilcox 模型的预期ROE或股权成本超出经济边界")
    if not 0 <= years <= 100 or terminal <= 0:
        raise ValueError("ROE回归年限须位于0—100年，终端PB必须为正")
    exponent = (roe - k) * years
    if abs(exponent) > 50:
        raise ValueError("Wilcox 指数项过大，输入会产生无经济意义的估值")
    reasonable_pb = terminal * math.exp(exponent)
    book = _finite(opening_book_value, "opening_book_value") if opening_book_value is not None else None
    shares = _finite(diluted_shares, "diluted_shares") if diluted_shares is not None else None
    if book is not None and book <= 0:
        raise ValueError("期初归母净资产必须为正")
    if shares is not None and shares <= 0:
        raise ValueError("稀释股数必须为正")
    if shares is not None and book is None:
        raise ValueError("计算每股价值时必须同时提供期初归母净资产")
    equity_value = book * reasonable_pb if book is not None else None
    return {
        "reasonable_pb": reasonable_pb,
        "equity_value": equity_value,
        "per_share_value": equity_value / shares if equity_value is not None and shares else None,
        "expected_sustainable_roe": roe,
        "cost_of_equity": k,
        "fade_years": years,
        "terminal_pb": terminal,
        "formula": "ln(当前合理PB)＝ln(长期均衡PB)＋(可持续预期ROE－股权成本)×回归长期均衡年限",
        "substitution": f"PB＝{terminal:.4f}×exp[({roe:.4f}－{k:.4f})×{years:.2f}]＝{reasonable_pb:.4f}",
        "boundary": "原式采用连续复利近似；终端PB不必等于1。周期顶部ROE、杠杆抬升ROE或未经验证的超长持续期不能直接代入。",
    }


def sustainable_growth_pb_valuation(
    *,
    sustainable_roe: float,
    payout_ratio: float,
    cost_of_equity: float,
    opening_book_value: float | None = None,
    roe_basis: str = "current_period",
) -> dict[str, Any]:
    """One-stage PB implied by sustainable growth and dividend policy.

    The PPT equation uses current-period EPS/book ROE and therefore grows the
    dividend once into the next period.  When the input is already a forward
    ROE defined as next-period earnings/opening book, use ``forward_period``
    so growth is not counted twice.
    """
    roe = _finite(sustainable_roe, "sustainable_roe")
    payout = _finite(payout_ratio, "payout_ratio")
    k = _finite(cost_of_equity, "cost_of_equity")
    if not 0 < roe < 2 or not 0 < payout <= 1 or not 0 < k < 1:
        raise ValueError("稳定增长PB需要正的ROE、分红率和股权成本")
    growth = roe * (1 - payout)
    if growth >= k:
        raise ValueError("可持续增长率必须低于股权成本；否则永续模型不收敛")
    basis = str(roe_basis or "").strip().lower()
    if basis not in {"current_period", "forward_period"}:
        raise ValueError("roe_basis 只允许 current_period 或 forward_period")
    forward_factor = 1 + growth if basis == "current_period" else 1.0
    reasonable_pb = roe * payout * forward_factor / (k - growth)
    book = _finite(opening_book_value, "opening_book_value") if opening_book_value is not None else None
    if book is not None and book <= 0:
        raise ValueError("期初归母净资产必须为正")
    return {
        "reasonable_pb": reasonable_pb,
        "equity_value": book * reasonable_pb if book is not None else None,
        "sustainable_growth": growth,
        "roe_basis": basis,
        "formula": (
            "合理PB＝当期ROE×分红率×(1＋可持续增长率)÷(股权成本－可持续增长率)"
            if basis == "current_period" else
            "合理PB＝下一期ROE×分红率÷(股权成本－可持续增长率)"
        ),
        "growth_formula": "可持续增长率＝ROE×(1－分红率)",
        "substitution": f"g＝{roe:.4f}×(1－{payout:.4f})＝{growth:.4f}；前推因子＝{forward_factor:.4f}；PB＝{reasonable_pb:.4f}",
        "boundary": "必须先说明ROE是当期还是下一期口径；假设ROE、分红率、资本结构和经营效率长期稳定，不适合把周期高点或短期异常ROE直接永续化。",
    }


def multistage_pb_roe_valuation(
    stages: Sequence[Mapping[str, Any]],
    *,
    opening_book_value: float,
    cost_of_equity: float,
    terminal_roe: float,
    terminal_payout_ratio: float,
    diluted_shares: float | None = None,
) -> dict[str, Any]:
    """Roll book value and dividends explicitly instead of hiding stage algebra."""
    if not stages:
        raise ValueError("多阶段PB-ROE至少需要一个明确阶段")
    opening = _finite(opening_book_value, "opening_book_value")
    k = _finite(cost_of_equity, "cost_of_equity")
    terminal_return = _finite(terminal_roe, "terminal_roe")
    terminal_payout = _finite(terminal_payout_ratio, "terminal_payout_ratio")
    shares = _finite(diluted_shares, "diluted_shares") if diluted_shares is not None else None
    if opening <= 0 or not 0 < k < 1 or not 0 < terminal_return < 2 or not 0 < terminal_payout <= 1:
        raise ValueError("多阶段PB-ROE的净资产、股权成本或终端ROE/分红率不满足边界")
    if shares is not None and shares <= 0:
        raise ValueError("稀释股数必须为正")

    book = opening
    year = 0
    dividend_pv = 0.0
    trace: list[dict[str, Any]] = []
    stage_inputs: list[dict[str, Any]] = []
    for index, raw in enumerate(stages, start=1):
        row = dict(raw)
        name = str(row.get("name") or f"阶段{index}").strip()
        years_raw = _finite(row.get("years"), f"stage_{index}_years")
        years = int(years_raw)
        roe = _finite(row.get("roe"), f"stage_{index}_roe")
        payout = _finite(row.get("payout_ratio"), f"stage_{index}_payout_ratio")
        if years_raw != years or years < 1 or years > 50:
            raise ValueError("每个PB-ROE阶段必须是1—50年的整数年限")
        if not -1 < roe < 2 or not 0 <= payout <= 1:
            raise ValueError("阶段ROE或分红率超出经济边界")
        if roe < 0 and payout > 0:
            raise ValueError("亏损阶段不能按正分红率计算；请显式输入0并单独解释分红资金来源")
        growth = roe * (1 - payout)
        stage_inputs.append({"name": name, "years": years, "roe": roe, "payout_ratio": payout, "sustainable_growth": growth})
        for _ in range(years):
            year += 1
            net_income = roe * book
            dividend = payout * net_income
            closing = book + net_income - dividend
            if closing <= 0:
                raise ValueError("阶段假设导致归母净资产归零或为负，PB-ROE不再适用")
            present = dividend / ((1 + k) ** year)
            trace.append({
                "year": year, "stage": name, "opening_book_value": book,
                "roe": roe, "payout_ratio": payout, "net_income": net_income,
                "dividend": dividend, "dividend_present_value": present,
                "closing_book_value": closing,
            })
            dividend_pv += present
            book = closing

    terminal_growth = terminal_return * (1 - terminal_payout)
    if terminal_growth >= k:
        raise ValueError("终端可持续增长率必须低于股权成本")
    # ``book`` is already the closing book value at the end of the explicit
    # period.  terminal_return is defined as next-period NI / this opening
    # book, so multiplying by (1+g) again would double-count one growth step.
    next_dividend = book * terminal_return * terminal_payout
    terminal_value = next_dividend / (k - terminal_growth)
    terminal_present = terminal_value / ((1 + k) ** year)
    equity_value = dividend_pv + terminal_present
    return {
        "stages": stage_inputs,
        "annual_trace": trace,
        "closing_book_value": book,
        "forecast_dividend_present_value": dividend_pv,
        "terminal_growth": terminal_growth,
        "terminal_value_present_value": terminal_present,
        "terminal_value_share": terminal_present / equity_value if equity_value else None,
        "equity_value": equity_value,
        "reasonable_pb": equity_value / opening,
        "per_share_value": equity_value / shares if shares else None,
        "formula": "每年净资产＝期初净资产＋ROE×期初净资产－分红；股权价值＝各年分红现值＋终端股利价值现值；合理PB＝股权价值÷当前归母净资产",
        "terminal_formula": "下一年股利＝预测期末净资产×终端ROE×终端分红率；终端增长率＝终端ROE×(1－终端分红率)；终值＝下一年股利÷(股权成本－终端增长率)",
        "boundary": "阶段ROE必须来自独立盈利预测和周期判断；模型假设不依赖外部增发，若有回购、增发或其他权益变动应改用完整权益桥/残余收益模型。",
    }


def reverse_pe(*, market_cap: float, target_pe: float, net_cash_adjustment: float = 0.0) -> dict[str, float | str]:
    cap = _finite(market_cap, "market_cap")
    multiple = _finite(target_pe, "target_pe")
    if cap <= 0 or multiple <= 0:
        raise ValueError("反向 PE 需要正市值和正倍数")
    implied = (cap - _finite(net_cash_adjustment, "net_cash_adjustment")) / multiple
    return {"implied_net_income": implied, "formula": "市场隐含归母净利润＝(当前市值－额外净现金调整)÷目标市盈率"}


def historical_multiple_valuation(
    history: Iterable[Mapping[str, Any]],
    *,
    current_fundamental: float,
    multiple_name: str,
    selected_percentile: float = 0.5,
) -> dict[str, Any]:
    """Use one independent observation per declared period, never daily duplication."""
    if not 0 <= selected_percentile <= 1:
        raise ValueError("selected_percentile 必须位于 0—1")
    by_period: dict[str, float] = {}
    for row in history:
        period = str(row.get("period") or row.get("as_of_date") or "").strip()
        if not period or row.get("multiple") is None:
            continue
        value = _finite(row["multiple"], "multiple")
        if value > 0:
            by_period[period] = value
    values = sorted(by_period.values())
    if len(values) < 3:
        raise ValueError("历史估值至少需要三个独立时期")
    position = selected_percentile * (len(values) - 1)
    low_index = int(math.floor(position))
    high_index = int(math.ceil(position))
    weight = position - low_index
    selected = values[low_index] * (1 - weight) + values[high_index] * weight
    fundamental = _finite(current_fundamental, "current_fundamental")
    return {
        "sample_size": len(values), "period_count": len(by_period),
        "multiple_name": multiple_name, "selected_percentile": selected_percentile,
        "selected_multiple": selected, "value": fundamental * selected,
        "minimum_multiple": min(values), "median_multiple": median(values), "maximum_multiple": max(values),
        "formula": f"估值＝当前适用基本面×历史{multiple_name}所选分位数",
        "sample_rule": "每个独立时期只保留一个估值观察值，不能用日频重复同一财务值扩大样本。",
    }


def dcf_fcff_valuation(
    *,
    fcff_path: Sequence[float],
    wacc: float,
    terminal_growth: float,
    net_debt: float,
    minority_interest: float = 0.0,
    non_operating_assets: float = 0.0,
    diluted_shares: float | None = None,
) -> dict[str, Any]:
    if len(fcff_path) < 3:
        raise ValueError("DCF 至少需要三年明确 FCFF 路径")
    cash_flows = [_finite(value, f"fcff_{index}") for index, value in enumerate(fcff_path, start=1)]
    discount = _finite(wacc, "wacc")
    growth = _finite(terminal_growth, "terminal_growth")
    if not 0 < discount < 1 or not -0.2 < growth < discount:
        raise ValueError("WACC 与永续增长率不满足 DCF 边界")
    present_values = [value / ((1 + discount) ** year) for year, value in enumerate(cash_flows, start=1)]
    terminal_value = cash_flows[-1] * (1 + growth) / (discount - growth)
    terminal_present = terminal_value / ((1 + discount) ** len(cash_flows))
    enterprise_value = sum(present_values) + terminal_present
    equity_value = (
        enterprise_value - _finite(net_debt, "net_debt")
        - _finite(minority_interest, "minority_interest")
        + _finite(non_operating_assets, "non_operating_assets")
    )
    shares = _finite(diluted_shares, "diluted_shares") if diluted_shares is not None else None
    if shares is not None and shares <= 0:
        raise ValueError("稀释股数必须为正")
    return {
        "enterprise_value": enterprise_value,
        "equity_value": equity_value,
        "per_share_value": equity_value / shares if shares else None,
        "forecast_fcff_present_value": sum(present_values),
        "terminal_value_present_value": terminal_present,
        "terminal_value_share": terminal_present / enterprise_value if enterprise_value else None,
        "annual_trace": [
            {"year": year, "fcff": value, "discount_factor": 1 / ((1 + discount) ** year), "present_value": present}
            for year, (value, present) in enumerate(zip(cash_flows, present_values), start=1)
        ],
        "formula": "企业价值＝预测期各年FCFF折现值之和＋终值折现值；股权价值＝企业价值－净债务－少数股东权益＋非经营资产",
        "terminal_formula": "终值＝最后一年FCFF×(1＋永续增长率)÷(WACC－永续增长率)",
    }


def reverse_dcf_constant_growth(
    *,
    enterprise_value: float,
    current_fcff: float,
    wacc: float,
    explicit_years: int,
    terminal_growth: float,
    lower_growth: float = -0.5,
    upper_growth: float = 2.0,
) -> dict[str, Any]:
    """Solve the constant explicit-period FCFF growth implied by market EV."""
    ev = _finite(enterprise_value, "enterprise_value")
    base = _finite(current_fcff, "current_fcff")
    discount = _finite(wacc, "wacc")
    terminal = _finite(terminal_growth, "terminal_growth")
    if ev <= 0 or base <= 0 or explicit_years < 3 or not terminal < discount:
        raise ValueError("反向 DCF 输入不满足经济边界")

    def value_at(growth: float) -> float:
        path = [base * ((1 + growth) ** year) for year in range(1, explicit_years + 1)]
        return float(dcf_fcff_valuation(
            fcff_path=path,
            wacc=discount, terminal_growth=terminal, net_debt=0,
        )["enterprise_value"])

    low, high = lower_growth, upper_growth
    low_value, high_value = value_at(low), value_at(high)
    if not low_value <= ev <= high_value:
        return {
            "implied_growth": None, "bracket_low_value": low_value, "bracket_high_value": high_value,
            "conclusion": "当前企业价值超出给定增长搜索区间，不能输出伪精确隐含增速。",
        }
    for _ in range(100):
        middle = (low + high) / 2
        if value_at(middle) < ev:
            low = middle
        else:
            high = middle
    implied = (low + high) / 2
    return {
        "implied_growth": implied, "reconstructed_enterprise_value": value_at(implied),
        "formula": "求解使预测期FCFF按固定增速增长后的DCF企业价值等于当前企业价值的增速。",
        "iterations": 100,
    }


def _ols_one(x: Sequence[float], y: Sequence[float]) -> tuple[float, float, float]:
    if len(x) != len(y) or len(x) < 3:
        raise ValueError("回归至少需要三个成对样本")
    mx, my = sum(x) / len(x), sum(y) / len(y)
    var = sum((v - mx) ** 2 for v in x)
    if var <= 0:
        raise ValueError("ROE/ROA 样本没有横截面或时间差异")
    slope = sum((a - mx) * (b - my) for a, b in zip(x, y)) / var
    intercept = my - slope * mx
    fitted = [intercept + slope * value for value in x]
    total = sum((value - my) ** 2 for value in y)
    residual = sum((actual - pred) ** 2 for actual, pred in zip(y, fitted))
    r2 = 1 - residual / total if total > 0 else 0.0
    return intercept, slope, r2


def _historical_pb_return(
    history: Iterable[Mapping[str, Any]],
    *,
    current_return: float,
    return_name: str,
    log_pb: bool = True,
) -> dict[str, Any]:
    by_period: dict[str, Mapping[str, Any]] = {}
    for row in history:
        period = str(row.get("period") or row.get("as_of_date") or "").strip()
        if period and row.get("pb") is not None and row.get(return_name) is not None:
            by_period[period] = row
    rows = list(by_period.values())
    if len(rows) < 3:
        raise ValueError("历史 PB-ROE 至少需要三个独立报告期/月末配对点")
    x = [_finite(row[return_name], return_name) for row in rows]
    raw_pb = [_finite(row["pb"], "pb") for row in rows]
    if any(value <= 0 for value in raw_pb):
        raise ValueError("PB 必须为正，才能进行对数PB与资产回报关系估计")
    y = [math.log(value) for value in raw_pb] if log_pb else raw_pb
    intercept, slope, r2 = _ols_one(x, y)
    current_x = _finite(current_return, f"current_{return_name}")
    fitted_current = intercept + slope * current_x
    reasonable_pb = math.exp(fitted_current) if log_pb else fitted_current
    residuals = [actual - (intercept + slope * observed) for actual, observed in zip(y, x)]
    residual_sigma = math.sqrt(sum(value * value for value in residuals) / max(1, len(residuals) - 2))
    low = fitted_current - 1.96 * residual_sigma
    high = fitted_current + 1.96 * residual_sigma
    return {
        "sample_size": len(rows), "period_count": len(by_period), "intercept": intercept,
        f"{return_name}_coefficient": slope,
        "r_squared": r2, "reasonable_pb": reasonable_pb,
        "residual_sigma": residual_sigma,
        "descriptive_band_low": math.exp(low) if log_pb else low,
        "descriptive_band_high": math.exp(high) if log_pb else high,
        "response_transform": "ln(pb)" if log_pb else "pb",
        "residual_space": "ln(pb)" if log_pb else "pb",
        "formula": (
            f"ln(合理PB)＝{intercept:.4f}＋{slope:.4f}×{return_name.upper()}"
            if log_pb else
            f"合理PB＝{intercept:.4f}＋{slope:.4f}×{return_name.upper()}"
        ),
        "sample_rule": "每个报告期只配一个报告后月末或事件时点 PB，避免日频重复同一财务值",
        "band_note": "区间是历史回归残差的描述带，不是未来回报保证；历史实际ROE只是当时可得预期ROE的代理。",
    }


def historical_pb_roe(history: Iterable[Mapping[str, Any]], *, current_roe: float) -> dict[str, Any]:
    return _historical_pb_return(history, current_return=current_roe, return_name="roe")


def historical_pb_roa(history: Iterable[Mapping[str, Any]], *, current_roa: float) -> dict[str, Any]:
    return _historical_pb_return(history, current_return=current_roa, return_name="roa")


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    n = len(vector)
    augmented = [matrix[i][:] + [vector[i]] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(augmented[row][col]))
        if abs(augmented[pivot][col]) < 1e-12:
            raise ValueError("同行回归矩阵不可逆；样本或变量高度共线")
        augmented[col], augmented[pivot] = augmented[pivot], augmented[col]
        divisor = augmented[col][col]
        augmented[col] = [value / divisor for value in augmented[col]]
        for row in range(n):
            if row == col:
                continue
            factor = augmented[row][col]
            augmented[row] = [a - factor * b for a, b in zip(augmented[row], augmented[col])]
    return [augmented[i][-1] for i in range(n)]


def peer_pb_model(
    peers: Iterable[Mapping[str, Any]],
    *,
    target: Mapping[str, float],
    feature_names: Sequence[str] = ("roe", "growth", "leverage", "risk"),
    ridge: float = 1e-8,
    log_pb: bool = True,
) -> dict[str, Any]:
    rows = [row for row in peers if row.get("pb") is not None and all(row.get(name) is not None for name in feature_names)]
    feature_count = len(feature_names)
    if len(rows) < feature_count + 2:
        raise ValueError("同行 PB 模型样本数必须至少比解释变量多两个")
    x = [[1.0] + [_finite(row[name], name) for name in feature_names] for row in rows]
    raw_pb = [_finite(row["pb"], "pb") for row in rows]
    if any(value <= 0 for value in raw_pb):
        raise ValueError("同行PB必须为正")
    y = [math.log(value) for value in raw_pb] if log_pb else raw_pb
    width = feature_count + 1
    xtx = [[sum(row[i] * row[j] for row in x) for j in range(width)] for i in range(width)]
    for i in range(1, width):
        xtx[i][i] += ridge
    xty = [sum(row[i] * value for row, value in zip(x, y)) for i in range(width)]
    coefficients = _solve(xtx, xty)
    target_vector = [1.0] + [_finite(target[name], name) for name in feature_names]
    fitted_target = sum(a * b for a, b in zip(coefficients, target_vector))
    reasonable_pb = math.exp(fitted_target) if log_pb else fitted_target
    predictions = [sum(a * b for a, b in zip(coefficients, row)) for row in x]
    mean_y = sum(y) / len(y)
    total = sum((value - mean_y) ** 2 for value in y)
    residual = sum((value - pred) ** 2 for value, pred in zip(y, predictions))
    return {
        "sample_size": len(rows),
        "features": list(feature_names),
        "coefficients": {"intercept": coefficients[0], **dict(zip(feature_names, coefficients[1:]))},
        "reasonable_pb": reasonable_pb,
        "r_squared": 1 - residual / total if total > 0 else 0.0,
        "peer_median_pb": median(raw_pb),
        "response_transform": "ln(pb)" if log_pb else "pb",
        "formula": (
            "ln(同行合理PB)＝截距＋ROE系数×ROE＋增长系数×增长＋杠杆系数×杠杆＋风险系数×风险"
            if log_pb else
            "同行合理PB＝截距＋ROE系数×ROE＋增长系数×增长＋杠杆系数×杠杆＋风险系数×风险"
        ),
    }


def residual_income_valuation(
    *,
    opening_book_value: float,
    roe_path: Sequence[float],
    payout_path: Sequence[float],
    cost_of_equity: float,
    terminal_roe: float,
    terminal_growth: float,
    buyback_path: Sequence[float] | None = None,
    issuance_path: Sequence[float] | None = None,
    other_equity_path: Sequence[float] | None = None,
) -> dict[str, Any]:
    n = len(roe_path)
    if n < 1 or len(payout_path) != n:
        raise ValueError("ROE 与分红率路径必须长度相同且非空")
    buybacks = list(buyback_path or [0.0] * n)
    issuances = list(issuance_path or [0.0] * n)
    others = list(other_equity_path or [0.0] * n)
    if not all(len(path) == n for path in (buybacks, issuances, others)):
        raise ValueError("权益桥各路径长度必须一致")
    book = _finite(opening_book_value, "opening_book_value")
    k = _finite(cost_of_equity, "cost_of_equity")
    g = _finite(terminal_growth, "terminal_growth")
    terminal_return = _finite(terminal_roe, "terminal_roe")
    if book <= 0 or not 0 < k < 1 or not g < k:
        raise ValueError("账面价值、股权成本或永续增长不满足残余收益模型边界")
    path = []
    pv_residual = 0.0
    for index, (roe, payout, buyback, issuance, other) in enumerate(zip(roe_path, payout_path, buybacks, issuances, others), start=1):
        r = _finite(roe, f"roe_{index}")
        p = _finite(payout, f"payout_{index}")
        if not -1 <= r <= 2 or not 0 <= p <= 1:
            raise ValueError("ROE 或分红率超出模型边界")
        net_income = r * book
        dividend = p * net_income
        residual = (r - k) * book
        present = residual / ((1 + k) ** index)
        closing = book + net_income - dividend - _finite(buyback, "buyback") + _finite(issuance, "issuance") + _finite(other, "other")
        path.append({"year": index, "opening_book_value": book, "roe": r, "net_income": net_income, "dividend": dividend, "residual_income": residual, "present_value": present, "closing_book_value": closing})
        pv_residual += present
        book = closing
    # Terminal ROE is the next-period return on closing book value.  Growth
    # applies after that first terminal residual-income observation.
    terminal_residual_next = (terminal_return - k) * book
    terminal_value = terminal_residual_next / (k - g)
    terminal_present = terminal_value / ((1 + k) ** n)
    equity_value = _finite(opening_book_value, "opening_book_value") + pv_residual + terminal_present
    return {
        "equity_value": equity_value,
        "opening_book_value": opening_book_value,
        "forecast_residual_income_pv": pv_residual,
        "terminal_value_pv": terminal_present,
        "terminal_value_share": terminal_present / equity_value if equity_value else None,
        "book_value_path": path,
        "formula": "股权价值＝期初账面价值＋预测期各年(ROE－股权成本)×期初账面价值的折现值＋终值的折现值",
        "terminal_formula": "终值＝下一年(永续ROE－股权成本)×账面价值÷(股权成本－永续增长率)",
    }


def pb_roa_diagnosis(*, pb: float, roa: float, roe: float, equity_multiplier: float, debt_ratio: float | None = None, asset_turnover: float | None = None, net_margin: float | None = None) -> dict[str, Any]:
    values = {"pb": _finite(pb, "pb"), "roa": _finite(roa, "roa"), "roe": _finite(roe, "roe"), "equity_multiplier": _finite(equity_multiplier, "equity_multiplier")}
    implied_roe = values["roa"] * values["equity_multiplier"]
    return {
        **values,
        "implied_roe_from_roa_and_leverage": implied_roe,
        "roe_bridge_residual": values["roe"] - implied_roe,
        "debt_ratio": _finite(debt_ratio, "debt_ratio") if debt_ratio is not None else None,
        "asset_turnover": _finite(asset_turnover, "asset_turnover") if asset_turnover is not None else None,
        "net_margin": _finite(net_margin, "net_margin") if net_margin is not None else None,
        "formula": "ROE≈ROA×权益乘数；PB-ROA 用资产效率、杠杆、增长和资产质量共同解释市净率",
        "warning": "高ROE若主要来自高权益乘数，不应与高ROA驱动的ROE获得相同估值解释",
    }


def book_value_profit_bridge(
    *,
    opening_book_value: float,
    net_income_path: Sequence[float],
    payout_path: Sequence[float],
    buyback_path: Sequence[float] | None = None,
    issuance_and_other_path: Sequence[float] | None = None,
) -> dict[str, Any]:
    """Project book value and average-equity ROE without inventing a balance sheet.

    This is deliberately the simple-mode bridge.  It is useful when a frozen
    profit path and opening parent equity are available but a complete future
    balance sheet is not.  Missing buybacks or other equity changes are set to
    zero only when callers explicitly omit them, and the returned boundary
    keeps that simplification visible.
    """
    profits = list(net_income_path)
    payouts = list(payout_path)
    if not profits or len(profits) != len(payouts):
        raise ValueError("净利润与分红率路径必须长度相同且非空")
    buybacks = list(buyback_path or [0.0] * len(profits))
    others = list(issuance_and_other_path or [0.0] * len(profits))
    if len(buybacks) != len(profits) or len(others) != len(profits):
        raise ValueError("回购、增发及其他权益变动路径必须与净利润路径等长")
    opening = _finite(opening_book_value, "opening_book_value")
    if opening <= 0:
        raise ValueError("期初归母净资产必须为正")
    rows: list[dict[str, float | int]] = []
    book = opening
    for index, (profit, payout, buyback, other) in enumerate(
        zip(profits, payouts, buybacks, others),
        start=1,
    ):
        income = _finite(profit, f"net_income_{index}")
        payout_ratio = _finite(payout, f"payout_{index}")
        repurchase = _finite(buyback, f"buyback_{index}")
        equity_change = _finite(other, f"issuance_and_other_{index}")
        if income < 0:
            raise ValueError("简化净资产桥不适用于亏损路径，应改用显式权益桥")
        if not 0 <= payout_ratio <= 1:
            raise ValueError("分红率必须位于0—1")
        dividend = income * payout_ratio
        closing = book + income - dividend - repurchase + equity_change
        if closing <= 0:
            raise ValueError("净资产桥产生非正期末净资产")
        average_equity = (book + closing) / 2
        roe = income / average_equity
        rows.append(
            {
                "year": index,
                "opening_book_value": book,
                "net_income": income,
                "payout_ratio": payout_ratio,
                "dividend": dividend,
                "buyback": repurchase,
                "issuance_and_other": equity_change,
                "closing_book_value": closing,
                "average_book_value": average_equity,
                "roe": roe,
            }
        )
        book = closing
    return {
        "opening_book_value": opening,
        "ending_book_value": book,
        "book_value_growth": book / opening - 1,
        "path": rows,
        "formula": (
            "期末归母净资产＝期初归母净资产＋归母净利润－分红－回购＋增发及其他权益变动；"
            "预测ROE＝归母净利润÷平均归母净资产"
        ),
        "boundary": (
            "这是数据不足时的简化权益桥；若缺少回购、增发和其他综合收益预测，"
            "默认值为零但必须保留该限制，不能据此声称已完成详细三表模型。"
        ),
    }


def pb_double_click_decomposition(
    *,
    opening_book_value: float,
    ending_book_value: float,
    current_pb: float,
    target_pb: float,
) -> dict[str, Any]:
    """Decompose market-value change into book growth and PB re-rating.

    The sequential decomposition keeps the interaction term visible: book
    growth is valued at the current PB first, then the target PB is applied to
    ending book value.  The result is an arithmetic identity, not a forecast.
    """
    opening = _finite(opening_book_value, "opening_book_value")
    ending = _finite(ending_book_value, "ending_book_value")
    current = _finite(current_pb, "current_pb")
    target = _finite(target_pb, "target_pb")
    if min(opening, ending, current, target) <= 0:
        raise ValueError("净资产和PB必须为正")
    current_market_value = opening * current
    book_only_market_value = ending * current
    target_market_value = ending * target
    book_contribution = book_only_market_value - current_market_value
    rerating_contribution = target_market_value - book_only_market_value
    total_change = target_market_value - current_market_value
    return {
        "current_market_value": current_market_value,
        "book_only_market_value": book_only_market_value,
        "target_market_value": target_market_value,
        "book_value_growth_factor": ending / opening,
        "pb_change_factor": target / current,
        "total_market_value_factor": target_market_value / current_market_value,
        "book_value_contribution": book_contribution,
        "pb_rerating_contribution": rerating_contribution,
        "total_change": total_change,
        "book_value_contribution_share": (
            book_contribution / total_change if total_change else None
        ),
        "pb_rerating_contribution_share": (
            rerating_contribution / total_change if total_change else None
        ),
        "formula": (
            "目标市值＝预测归母净资产×目标PB；先按当前PB计量净资产增长贡献，"
            "再按期末净资产计量PB扩张或收缩贡献"
        ),
        "boundary": (
            "双击分解只解释给定净资产与目标PB时价值变化来自哪里；"
            "目标PB若没有周期、历史区间或资产质量依据，就只能作为研究情景。"
        ),
    }


def historical_pb_band(values: Iterable[float], *, current_pb: float) -> dict[str, Any]:
    """Summarize a positive PB history without treating percentiles as fair value."""
    clean = sorted(
        _finite(value, "historical_pb")
        for value in values
        if value is not None
    )
    if len(clean) < 12:
        raise ValueError("历史PB区间至少需要12个独立月末或季度观察值")
    if clean[0] <= 0:
        raise ValueError("历史PB必须为正")
    current = _finite(current_pb, "current_pb")
    if current <= 0:
        raise ValueError("当前PB必须为正")

    def percentile(probability: float) -> float:
        position = (len(clean) - 1) * probability
        lower = math.floor(position)
        upper = math.ceil(position)
        if lower == upper:
            return clean[lower]
        weight = position - lower
        return clean[lower] * (1 - weight) + clean[upper] * weight

    below = sum(value < current for value in clean)
    equal = sum(value == current for value in clean)
    rank = (below + 0.5 * equal) / len(clean)
    q20 = percentile(0.20)
    q40 = percentile(0.40)
    q60 = percentile(0.60)
    q80 = percentile(0.80)
    if current < q20:
        status = "低于历史偏低区"
    elif current <= q60:
        status = "处于历史中枢区"
    elif current <= q80:
        status = "处于历史偏高区"
    else:
        status = "高于历史偏高区"
    return {
        "sample_size": len(clean),
        "minimum": clean[0],
        "q20": q20,
        "q40": q40,
        "median": percentile(0.50),
        "mean": sum(clean) / len(clean),
        "q60": q60,
        "q80": q80,
        "maximum": clean[-1],
        "current_pb": current,
        "current_percentile": rank,
        "historical_status": status,
        "low_zone": [clean[0], q20],
        "central_zone": [q40, q60],
        "high_zone": [q80, clean[-1]],
        "formula": "历史位置＝当前PB在独立月末PB样本中的经验分位",
        "boundary": (
            "历史分位只是估值位置，不是合理价值；必须结合当期ROE、周期、"
            "资产质量、杠杆和现金流判断是否可比。"
        ),
    }


def synthesize_models(results: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [dict(row) for row in results if row.get("role") != "not_applicable" and row.get("equity_value") is not None]
    if not rows:
        return {"models": [], "clusters": [], "core_range": None}
    clusters: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        clusters.setdefault(str(row.get("dependency_group") or row.get("model_name") or "unclassified"), []).append(row)
    cluster_values = []
    for name, members in clusters.items():
        values = [_finite(row["equity_value"], "equity_value") for row in members]
        cluster_values.append({"dependency_group": name, "model_count": len(values), "representative_value": median(values), "min": min(values), "max": max(values)})
    core = [row for row in rows if row.get("role") == "core"] or rows
    core_values = [_finite(row["equity_value"], "equity_value") for row in core]
    return {
        "models": rows,
        "clusters": cluster_values,
        "core_range": {"low": min(core_values), "high": max(core_values), "median": median(core_values)},
        "aggregation_rule": "先按共同经营假设聚类，再解释核心模型区间；不对高度相关模型机械平均",
    }
