from __future__ import annotations

"""Build the 18-company financial.db export for AI portfolio run16."""

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from tools.financial.opportunity_profile_export import EXPORT_SCHEMA_VERSION


ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = ROOT / "opportunity_lens/research_outputs/20260801_ai_app_full_chain_portfolio_run16"
FIN_DIR = RUN_DIR / "financial_artifacts"
MODEL_PATH = FIN_DIR / "run16_independent_financial_portfolios.json"
RECON_PATH = FIN_DIR / "run16_external_reconciliation.json"
PARENT_EQUITY_PATH = FIN_DIR / "run16_parent_equity_tushare.json"
SELL_SIDE_PATH = (
    ROOT
    / "cache/research_runs/opportunity_lens_ai_app_full_chain_portfolio_20260801"
    / "workpapers/datayes_company_forecasts.json"
)
ACTUAL_PATHS = (
    FIN_DIR / "financial_actual_applications.json",
    FIN_DIR / "financial_actual_full_chain_a.json",
    FIN_DIR / "financial_actual_full_chain_b.json",
)
CONSENSUS_PATHS = (
    FIN_DIR / "financial_consensus_applications.json",
    FIN_DIR / "financial_consensus_full_chain_a.json",
    FIN_DIR / "financial_consensus_full_chain_b.json",
)
OUTPUT_PATH = RUN_DIR / "company_financial_profile_export_v1.json"
AS_OF = "2026-07-30"
RUN_REF = "opportunity_lens:ai_app_full_chain_portfolio:20260801"


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return "sha256:" + digest


def _rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")


def _ref(path: Path, pointer: str) -> str:
    return f"{_sha(path)}#{pointer}"


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _input(
    name: str, value: float | None, unit: str, period: str, source_ref: str,
    method: str, *, value_text: str | None = None, input_type: str = "expert_assumption",
) -> dict[str, Any]:
    return {
        "input_name": name, "value_num": value, "value_text": value_text,
        "unit": unit, "period_or_as_of_date": period, "source_ref": source_ref,
        "input_type": input_type, "formula_or_method": method,
        "sensitivity_note": "收入增速、净利率、现金转换、资本开支与目标倍数均按公司分别设定。",
        "limitation_note": "未来数值是研究情景，不是公司承诺或确定收益。",
    }


def _output(
    name: str, unit: str, period: str, formula: str, substitution: str,
    *, value: float | None = None, value_text: str | None = None,
    low: float | None = None, high: float | None = None,
    group: str = "独立模型", conclusion: str = "研究估计",
) -> dict[str, Any]:
    return {
        "output_name": name, "value_num": value, "value_text": value_text,
        "range_low": low, "range_high": high, "unit": unit,
        "period_or_as_of_date": period, "formula": formula,
        "substitution": substitution, "dependency_group": group,
        "conclusion": conclusion,
    }


def _observation(
    metric: str, value: float, unit: str, fact_type: str, provider: str,
    raw_feature: str, source_snapshot_key: str, *, fiscal_year: int | None = None,
    fiscal_period: str | None = None, period_end: str | None = None,
    frequency: str = "annual", scenario: str = "reported",
    currency: str | None = None, formula: str | None = None,
    model_run_key: str | None = None,
) -> dict[str, Any]:
    return {
        "metric_name": metric, "value_num": float(value), "unit": unit,
        "currency": currency, "period_end": period_end,
        "fiscal_year": fiscal_year, "fiscal_period": fiscal_period,
        "frequency": frequency, "fact_type": fact_type, "as_of_date": AS_OF,
        "provider": provider, "raw_feature_name": raw_feature,
        "formula": formula, "input_refs": [], "quality_status": "usable",
        "scenario_name": scenario, "source_snapshot_key": source_snapshot_key,
        "model_run_key": model_run_key,
    }


def _merge_snapshots(paths: tuple[Path, ...], stage_key: str) -> tuple[dict[str, Any], dict[str, Path]]:
    rows: dict[str, Any] = {}
    path_by_ticker: dict[str, Path] = {}
    for path in paths:
        payload = _read(path)
        if payload.get("stage") != stage_key:
            raise ValueError(f"{path} stage不正确")
        for identity in payload["universe"]:
            ticker = identity["ticker"]
            if ticker in rows:
                raise ValueError(f"重复证券{ticker}")
            rows[ticker] = payload
            path_by_ticker[ticker] = path
    return rows, path_by_ticker


def _source_snapshots(
    ticker: str, actual_path: Path, consensus_path: Path,
    actual_payload: dict[str, Any], consensus_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        {
            "key": "wind_actual", "provider": "wind", "source_channel": "structured_api",
            "source_ref": f"{RUN_REF}:wind_actual:{ticker}",
            "title": f"{ticker} Wind历史财务、当前估值与一年复权价格窄快照",
            "publisher": "Wind内网HTTP代理", "as_of_date": AS_OF,
            "fetched_at": actual_payload.get("accessed_at_utc"), "content_hash": _sha(actual_path),
            "raw_snapshot_path": _rel(actual_path),
            "metadata": {"ticker": ticker, "wind_priority": "A股同口径非空字段主源"},
        },
        {
            "key": "independent_model", "provider": "internal_model", "source_channel": "internal_calculation",
            "source_ref": f"{RUN_REF}:independent:{ticker}",
            "title": f"{ticker} Run16独立FY1—FY3财务、估值与组合模型",
            "publisher": "Industry Demo内部研究模型", "as_of_date": AS_OF,
            "fetched_at": None, "content_hash": _sha(MODEL_PATH), "raw_snapshot_path": _rel(MODEL_PATH),
            "metadata": {"independent_before_consensus": True},
        },
        {
            "key": "wind_consensus", "provider": "wind", "source_channel": "structured_api",
            "source_ref": f"{RUN_REF}:wind_consensus:{ticker}",
            "title": f"{ticker} Wind FY1—FY3一致预期窄快照",
            "publisher": "Wind内网HTTP代理", "as_of_date": AS_OF,
            "fetched_at": consensus_payload.get("accessed_at_utc"), "content_hash": _sha(consensus_path),
            "raw_snapshot_path": _rel(consensus_path),
            "metadata": {"sequence_control": "独立模型冻结后读取"},
        },
        {
            "key": "external_reconciliation", "provider": "internal_model", "source_channel": "internal_calculation",
            "source_ref": f"{RUN_REF}:reconciliation:{ticker}",
            "title": f"{ticker} Run16冻结后外部预测对账",
            "publisher": "Industry Demo内部研究模型", "as_of_date": AS_OF,
            "fetched_at": None, "content_hash": _sha(RECON_PATH), "raw_snapshot_path": _rel(RECON_PATH),
            "metadata": {"wind_and_sell_side_kept_separate": True},
        },
        {
            "key": "sell_side_reports", "provider": "datayes", "source_channel": "report",
            "source_ref": f"{RUN_REF}:sell_side_reports:{ticker}",
            "title": f"{ticker} 最近两个季度逐机构预测底稿",
            "publisher": "萝卜投研聚合的底层券商报告", "as_of_date": "2026-08-01",
            "fetched_at": None, "content_hash": _sha(SELL_SIDE_PATH),
            "raw_snapshot_path": _rel(SELL_SIDE_PATH),
            "metadata": {
                "wind_and_sell_side_kept_separate": True,
                "underlying_broker_is_independence_unit": True,
                "accounting_basis_grouped_before_median": True,
            },
        },
    ]


def _actual_observations(ticker: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    actual = payload["wind"]["reported"]
    amount_fields = {
        "OPER_REV": ("revenue", "亿元人民币"),
        "NP_BELONGTO_PARCOMSH": ("net_income", "亿元人民币"),
        "NET_CASH_FLOWS_OPER_ACT": ("operating_cash_flow", "亿元人民币"),
        "CASH_PAY_ACQ_CONST_FIOLTA": ("capex", "亿元人民币"),
        "TOT_ASSETS": ("total_assets", "亿元人民币"),
        "TOT_EQUITY": ("total_equity", "亿元人民币"),
        "TOT_LIAB": ("total_liabilities", "亿元人民币"),
    }
    ratio_fields = {
        "ROE": ("roe", "%"), "ROA2": ("roa", "%"),
        "GROSSPROFITMARGIN": ("gross_margin", "%"),
        "NETPROFITMARGIN": ("net_margin", "%"),
    }
    for end_date, by_ticker in actual.items():
        row = by_ticker.get(ticker) or {}
        if not row:
            continue
        year = int(str(end_date)[:4])
        is_annual = str(end_date)[4:] == "1231"
        period = f"FY{year}" if is_annual else f"{year}Q1"
        for raw, (metric, unit) in {**amount_fields, **ratio_fields}.items():
            value = _finite(row.get(raw))
            if value is None:
                continue
            if raw in amount_fields:
                value = abs(value) / 1e8 if raw == "CASH_PAY_ACQ_CONST_FIOLTA" else value / 1e8
            rows.append(_observation(
                metric, value, unit, "actual", "wind", f"wss.{raw.lower()}", "wind_actual",
                fiscal_year=year, fiscal_period=period, period_end=f"{str(end_date)[:4]}-{str(end_date)[4:6]}-{str(end_date)[6:8]}",
                frequency="annual" if is_annual else "quarterly", currency="CNY" if "人民币" in unit else None,
            ))
        assets = _finite(row.get("TOT_ASSETS"))
        liabilities = _finite(row.get("TOT_LIAB"))
        if assets and liabilities is not None:
            rows.append(_observation(
                "debt_ratio", liabilities / assets * 100, "%", "actual", "wind", "derived.tot_liab/tot_assets", "wind_actual",
                fiscal_year=year, fiscal_period=period, period_end=f"{str(end_date)[:4]}-{str(end_date)[4:6]}-{str(end_date)[6:8]}",
                frequency="annual" if is_annual else "quarterly", formula="总负债÷总资产",
            ))
    current = payload["wind"]["current"].get(ticker) or {}
    current_fields = {
        "CLOSE": ("close", "元/股", 1), "PE_TTM": ("pe_ttm", "倍", 1),
        "PB_LF": ("pb", "倍", 1), "PS_TTM": ("ps_ttm", "倍", 1),
        "MKT_CAP_ARD": ("market_cap_cny", "亿元人民币", 1e8),
        "ROE_TTM": ("roe", "%", 1), "ROA2_TTM": ("roa", "%", 1),
        "EPS_TTM": ("eps_ttm", "元/股", 1), "BPS_NEW": ("bps_mrq", "元/股", 1),
        "EV2_TO_EBITDA": ("ev_ebitda", "倍", 1),
    }
    for raw, (metric, unit, divisor) in current_fields.items():
        value = _finite(current.get(raw))
        if value is None or (metric in {"pe_ttm", "pb"} and value <= 0):
            continue
        rows.append(_observation(
            metric, value / divisor, unit, "market", "wind", f"wss.{raw.lower()}", "wind_actual",
            period_end=AS_OF, frequency="snapshot", currency="CNY" if "人民币" in unit or "元/股" in unit else None,
        ))
    return rows


def _sell_side_benchmark_reconciliations(
    ticker: str,
    reconciliation: dict[str, Any],
    report_index: dict[tuple[str, str, str], int],
) -> list[dict[str, Any]]:
    """Compile accounting-basis-safe sell-side benchmarks for company detail.

    Wind consensus remains a separate benchmark family.  A sell-side group
    produces a median only when at least two reports share the same metric and
    accounting basis; otherwise it remains an explicitly named single-report
    forecast.  EPS is never combined across statutory/adjusted or
    basic/diluted groups.
    """

    rows: list[dict[str, Any]] = []

    def append_group(
        *,
        year: int,
        metric_name: str,
        metric_source_key: str,
        basis_group: str,
        unit: str,
        benchmark: dict[str, Any],
        independent_value: float | None,
        comparable_to_independent: bool,
    ) -> None:
        status = str(benchmark.get("status") or "")
        if status == "same_metric_median":
            benchmark_value = _finite(benchmark.get("median"))
            value_type = "same_basis_median"
        else:
            benchmark_value = _finite(benchmark.get("single_forecast"))
            value_type = "single_institution_forecast"
        if benchmark_value is None:
            return
        observations = []
        underlying_refs = []
        for observation in benchmark.get("observations") or []:
            institution = str(observation.get("institution") or "机构未注明")
            publish_date = str(observation.get("publish_date") or "日期未注明")
            index = report_index.get((ticker, institution, publish_date))
            source_ref = (
                _ref(SELL_SIDE_PATH, f"reports.{index}.{metric_source_key}.values.{year}")
                if index is not None
                else _ref(
                    RECON_PATH,
                    f"reconciliations.{ticker}.{year}.{metric_source_key}.{basis_group}",
                )
            )
            underlying_refs.append(source_ref)
            observations.append({
                "institution": institution,
                "publish_date": publish_date,
                "basis": observation.get("basis") or "报告未明确说明口径",
                "value": observation.get("value"),
                "unit": unit,
                "source_ref": source_ref,
            })
        benchmark_source_ref = (
            underlying_refs[0]
            if value_type == "single_institution_forecast" and len(underlying_refs) == 1
            else _ref(
                RECON_PATH,
                f"reconciliations.{ticker}.{year}.{metric_source_key}.{basis_group}.same_basis_median",
            )
        )
        conclusion = (
            f"FY{year}卖方{metric_name}按{basis_group}口径"
            f"{'计算同口径中位数' if value_type == 'same_basis_median' else '保留单机构预测'}；"
            "与Wind一致预期并列但不合并计权。"
        )
        if not comparable_to_independent:
            conclusion += "该口径与独立模型不完全一致，因此不计算机械差异。"
        rows.append({
            "benchmark_type": "sell_side_report",
            "benchmark_source_ref": benchmark_source_ref,
            "metric_name": metric_name,
            "period": str(year),
            "independent_value": independent_value if comparable_to_independent else None,
            "benchmark_value": benchmark_value,
            "unit": unit,
            "decomposition": {
                "benchmark_record_type": value_type,
                "accounting_basis_group": basis_group,
                "sample_size": int(benchmark.get("sample_size") or 0),
                "institutions": list(benchmark.get("institutions") or []),
                "publish_dates": list(benchmark.get("publish_dates") or []),
                "range_low": benchmark.get("range_low"),
                "range_high": benchmark.get("range_high"),
                "observations": observations,
                "underlying_source_refs": underlying_refs,
                "comparable_to_independent": comparable_to_independent,
                "wind_and_sell_side_kept_separate": True,
                "aggregation_rule": (
                    "同一指标和会计口径n>=2才取中位数；n=1保留单机构；"
                    "法定/调整后及basic/diluted EPS禁止跨组聚合。"
                ),
            },
            "conclusion": conclusion,
        })

    for period in reconciliation["periods"]:
        year = int(period["year"])
        independent = period["independent"]
        benchmark_set = period.get("sell_side_report_median") or {}
        revenue = benchmark_set.get("revenue_median")
        if revenue:
            append_group(
                year=year, metric_name="revenue", metric_source_key="revenue",
                basis_group="revenue", unit="亿元人民币", benchmark=revenue,
                independent_value=_finite(independent.get("revenue_100m_cny")),
                comparable_to_independent=True,
            )
        for basis, benchmark in (benchmark_set.get("profit_medians_by_basis") or {}).items():
            append_group(
                year=year, metric_name="net_income", metric_source_key="profit",
                basis_group=str(basis), unit="亿元人民币", benchmark=benchmark,
                independent_value=_finite(independent.get("parent_net_income_100m_cny")),
                comparable_to_independent=basis == "parent_net_profit",
            )
        for basis, benchmark in (benchmark_set.get("eps_medians_by_basis") or {}).items():
            append_group(
                year=year, metric_name="eps", metric_source_key="eps",
                basis_group=str(basis), unit="元/股", benchmark=benchmark,
                independent_value=None, comparable_to_independent=False,
            )
    return rows


def _financial_model(
    ticker: str,
    company: dict[str, Any],
    reconciliation: dict[str, Any],
    report_index: dict[tuple[str, str, str], int],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    run_key = f"ol16:{ticker}:independent_financial_bridge:v1"
    baseline = company["baseline"]
    inputs = [
        _input("FY2025营业收入", baseline["revenue_100m_cny"], "亿元人民币", "2025", _ref(MODEL_PATH, f"companies.{ticker}.baseline"), "Wind实际值作为收入桥起点。", input_type="direct_fact"),
        _input("FY2025正常化归母净利润", baseline["parent_net_income_100m_cny"], "亿元人民币", "2025", _ref(MODEL_PATH, f"companies.{ticker}.baseline.normalization_adjustments"), "保留公告原值；存在明确一次性项目时采用正常化经营基线。", input_type="derived_fact"),
        _input("FY2025归母股东权益", baseline["parent_equity_100m_cny"], "亿元人民币", "2025", _ref(MODEL_PATH, f"companies.{ticker}.baseline.parent_equity_100m_cny"), "归母权益按字段使用Tushare balancesheet.total_hldr_eqy_exc_min_int；经营、利润、现金流和总资产事实来自Wind。", input_type="direct_fact"),
        _input("公司经营传导机制", None, "文字", "2026—2028", _ref(MODEL_PATH, f"companies.{ticker}.economic_mechanism"), "从行业需求、产品/客户、收入、利润率、现金流逐层传导。", value_text=company["economic_mechanism"]),
    ]
    outputs: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    for year in (2026, 2027, 2028):
        row = company["scenarios"]["base"][str(year)]
        fields = (
            ("revenue_100m_cny", "营业收入", "revenue", "亿元人民币", "上年收入×(1+收入增速)"),
            ("parent_net_income_100m_cny", "归母净利润", "net_income", "亿元人民币", "收入×归母净利率"),
            ("ocf_100m_cny", "经营现金流", "operating_cash_flow", "亿元人民币", "收入×经营现金流率"),
            ("capex_100m_cny", "资本开支", "capex", "亿元人民币", "收入×资本开支率"),
            ("fcf_100m_cny", "自由现金流", "free_cash_flow", "亿元人民币", "经营现金流−资本开支"),
            (
                "dividends_100m_cny",
                "预计支付现金分红",
                "cash_dividend",
                "亿元人民币",
                row.get("dividend_timing_basis")
                or "上年归母净利润×本年分红支付率",
            ),
            ("roe_pct", "净资产收益率", "roe", "%", "归母净利润÷平均权益代理"),
            ("roa_pct", "总资产收益率", "roa", "%", "归母净利润÷平均总资产"),
            ("ending_parent_equity_100m_cny", "期末归母权益", "book_value", "亿元人民币", row.get("equity_bridge_note") or "期初归母权益+归母净利润−分红−回购+其他权益变动"),
        )
        for field, label, metric, unit, formula in fields:
            value = float(row[field])
            outputs.append(_output(
                f"{year}年{label}", unit, str(year), formula, f"Run16基准情景={value:.2f}{unit}",
                value=value, conclusion="独立预测，不是外部一致预期。",
            ))
            observations.append(_observation(
                metric, value, unit, "internal_estimate", "internal_model", f"run16.base.{field}", "independent_model",
                fiscal_year=year, fiscal_period=f"FY{year-2025}", period_end=f"{year}-12-31",
                scenario="base", currency="CNY" if "人民币" in unit else None,
                formula=formula, model_run_key=run_key,
            ))
    recs = []
    for period in reconciliation["periods"]:
        year = int(period["year"])
        for metric, field, unit in (
            ("revenue", "revenue_100m_cny", "亿元人民币"),
            ("net_income", "parent_net_income_100m_cny", "亿元人民币"),
            ("roe", "roe_pct", "%"),
        ):
            recs.append({
                "benchmark_type": "consensus",
                "benchmark_source_ref": _ref(RECON_PATH, f"reconciliations.{ticker}.{year}.{field}"),
                "metric_name": metric, "period": str(year),
                "independent_value": period["independent"].get(field),
                "benchmark_value": period["external"].get(field), "unit": unit,
                "decomposition": {"difference_pct": period["difference_pct"].get(metric if metric != "net_income" else "parent_net_income")},
                "conclusion": (
                    f"FY{year}独立{metric}与Wind一致预期的差异为"
                    f"{period['difference_pct'].get(metric if metric != 'net_income' else 'parent_net_income')}%；"
                    "只用于逐年口径和假设对账。"
                ),
            })
    recs.extend(_sell_side_benchmark_reconciliations(ticker, reconciliation, report_index))
    model = {
        "run_key": run_key, "skill_name": "company_financial_modeling",
        "model_name": f"Run16 {company['name']}独立FY1—FY3财务与现金流桥", "model_role": "primary",
        "forecast_start": "2026", "forecast_end": "2028", "valuation_date": AS_OF,
        "assumptions": {"model_level": company["model_level"], "independent_before_consensus": True, "economic_mechanism": company["economic_mechanism"]},
        "limitations": "公开数据不足以建立逐产品完整三表；采用公司特定收入、利润率、现金流、资本开支和权益桥，结果是可复核情景。",
        "finalization": "independent", "inputs": inputs, "outputs": outputs, "reconciliations": recs,
    }
    return model, observations


def _consensus_observations(ticker: str, reconciliation: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for period in reconciliation["periods"]:
        year = int(period["year"])
        for field, metric, unit in (
            ("revenue_100m_cny", "revenue", "亿元人民币"),
            ("parent_net_income_100m_cny", "net_income", "亿元人民币"),
            ("eps_cny_per_share", "eps", "元/股"),
            ("roe_pct", "roe", "%"),
        ):
            value = _finite(period["external"].get(field))
            if value is None:
                continue
            rows.append(_observation(
                metric, value, unit, "consensus", "wind", period["external"]["raw_fields"].get(
                    "parent_net_income" if field == "parent_net_income_100m_cny" else
                    "revenue" if field == "revenue_100m_cny" else
                    "eps" if field == "eps_cny_per_share" else "roe"
                ), "wind_consensus", fiscal_year=year, fiscal_period=f"FY{year-2025}",
                period_end=f"{year}-12-31", scenario="median", currency="CNY" if "人民币" in unit or "元/股" in unit else None,
            ))
    return rows


def _valuation_models(
    ticker: str, company: dict[str, Any], reconciliation: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    market = company["baseline"]["market"]
    market_cap = float(market["market_cap_100m_cny"])
    close = float(market["close_cny"])
    shares_100m = market_cap / close
    calculated = [m for m in company["valuation_methods"] if m.get("status") == "calculated" and m.get("equity_value_low_100m_cny") is not None]
    pe = next((m for m in calculated if m["method"] == "Forward PE"), None)
    if pe is None:
        raise ValueError(f"{ticker}缺少有效Forward PE")
    low, high = pe["equity_value_low_100m_cny"], pe["equity_value_high_100m_cny"]
    price_low, price_high = low / shares_100m, high / shares_100m
    current_to_low = (market_cap / low - 1) * 100
    reverse = next(m for m in company["valuation_methods"] if m["method"] == "当前市值隐含市盈率")
    pbroe = next((m for m in company["valuation_methods"] if m["method"].startswith("PB—ROE")), None)
    if close < price_low:
        stance = "当前价格低于独立PE区间下沿，但只有经营和现金流按基准兑现时才构成有条件买点"
    elif close <= price_high:
        stance = "当前价格处于独立PE区间内，适合用后续业绩逐步验证而非一次性押注"
    else:
        stance = "当前价格高于独立PE区间上沿，需要更高收入、利润率或更长高增长期才能消化估值"
    base = company["scenarios"]["base"]
    ni_path = "/".join(f"{base[str(y)]['parent_net_income_100m_cny']:.2f}" for y in (2026, 2027, 2028))
    fcf_path = "/".join(f"{base[str(y)]['fcf_100m_cny']:.2f}" for y in (2026, 2027, 2028))
    summary = {
        "conclusion": f"{stance}。PE法对应{price_low:.2f}—{price_high:.2f}元/股，当前{close:.2f}元。",
        "operating_analysis": f"FY2025收入{company['baseline']['revenue_100m_cny']:.2f}亿元；独立FY2026—FY2028归母净利润为{ni_path}亿元，自由现金流为{fcf_path}亿元。{company['economic_mechanism']}",
        "valuation_analysis": (
            f"当前总市值{market_cap:.2f}亿元；独立FY2027利润对应当前市值隐含PE "
            f"{reverse['implied_pe']:.2f}倍。Forward PE采用FY2027基准归母净利润"
            f"{pe['input']['parent_net_income_100m_cny']:.2f}亿元×"
            f"{pe['input']['multiple_low']['value']:.2f}—{pe['input']['multiple_high']['value']:.2f}倍；"
            "倍数下限由FY2025—FY2028正常化利润复合增速与历史PE_TTM Q25共同约束，上限由"
            f"1.5倍利润增速与历史PE_TTM中位共同约束。股东现金流代理折现和PB—ROE只在方法门禁"
            f"允许时作为诊断。{reconciliation['summary_zh']}"
        ),
        "buy_point_analysis": f"有条件观察/加仓区以{price_low:.2f}元附近及以下为起点，同时要求FY2026—FY2027收入、净利率和现金流不低于基准路径；价格便宜但经营证伪时不能机械买入。",
        "sell_point_analysis": f"{price_high:.2f}元附近及以上若没有上行情景利润兑现，已越过独立PE区间上沿，应降低风险预算；若基本面下修，卖出条件可早于价格触及上沿。",
        "difference_causes": [reconciliation["summary_zh"], reconciliation["data_gap_zh"]],
        "future_view": "未来12个月核验订单/付费、收入确认、利润率和自由现金流；三年维度核验竞争壁垒、资本开支回报与高增长持续期。",
        "positive_trigger": "核心收入驱动、归母净利率和经营现金流连续两个报告期达到或高于独立基准，同时外部预期没有通过更高估值提前完全反映。",
    }
    if pbroe and pbroe.get("status") == "calculated":
        pb_low, pb_high = pbroe["implied_pb_low"], pbroe["implied_pb_high"]
        pb_ready = True
        pb_basis = "历史盈利与资本回报通过稳定性门禁；PB—ROE仍只作为诊断，不取代经营与现金流模型。"
    else:
        pb_low = pb_high = float(market.get("pb_lf") or 1)
        pb_ready = False
        pb_basis = "可持续ROE没有通过稳定性门禁，PB—ROE不计算目标值；当前PB仅作资产回报观察。"
    framework = {
        "applicability": "诊断方法" if pb_ready else "ROE稳定性不足，暂不估值",
        "cycle_sensitivity": "受AI资本开支、产品代际、客户预算或市场活跃度影响，不能把高景气ROE直接永续化。",
        "asset_intensity": "总资产采用Wind合并口径，归母权益采用Tushare归母股东权益窄字段补缺；逐业务资本占用公开不足。",
        "basis": pb_basis, "price_exposure": company["portfolio_candidate"]["direction"],
        "profit_driver": company["economic_mechanism"],
        "tags": [
            {"label": "盈利驱动", "basis": "收入增长和归母净利率共同决定利润。"},
            {"label": "现金质量", "basis": "经营现金流减资本开支决定可分配价值。"},
            {"label": "ROE门禁", "basis": pb_basis},
        ],
    }
    workbench = {
        "simple_ready": pb_ready, "detailed_ready": False, "default_mode": "simple",
        "reason": pb_basis if pb_ready else "可持续ROE不足，不用简化输入台自动生成目标PB。",
        "simple": {
            "opening_book_value_cny_100m": (
                company["baseline"].get("current_year_q1_checkpoint", {}).get("parent_equity_100m_cny")
                or company["baseline"]["parent_equity_100m_cny"]
            ),
            "current_pb": market.get("pb_lf"), "target_pb": (pb_low + pb_high) / 2,
            "years": [
                {
                    "fiscal_year": y,
                    "net_income_cny_100m": base[str(y)][
                        "parent_net_income_100m_cny"
                    ],
                    "dividend_base_parent_net_income_cny_100m": base[str(y)][
                        "dividend_base_parent_net_income_100m_cny"
                    ],
                    "payout_ratio_pct": base[str(y)]["input_ledger"][
                        "dividend_payout_pct"
                    ]["value"],
                    "estimated_cash_dividend_cny_100m": base[str(y)][
                        "dividends_100m_cny"
                    ],
                    "timing_basis": base[str(y)]["dividend_timing_basis"],
                }
                for y in (2026, 2027, 2028)
            ],
            "pb_presets": {"current": market.get("pb_lf"), "research_low": pb_low, "research_mid": (pb_low + pb_high) / 2, "research_high": pb_high},
        },
        "detailed": {"available_fields": ["收入", "归母净利润", "经营现金流", "资本开支", "权益与总资产代理"], "missing_required_fields": ["逐业务完整三表", "客户级订单与回款", "净债务跨期计划"]},
    }
    val_key = f"ol16:{ticker}:multi_method_valuation:v1"
    inputs = [
        _input("FY2027独立归母净利润", base["2027"]["parent_net_income_100m_cny"], "亿元人民币", "2027", _ref(MODEL_PATH, f"companies.{ticker}.scenarios.base.2027"), "独立财务模型。", input_type="derived_fact"),
        _input("当前总市值", market_cap, "亿元人民币", AS_OF, _ref(MODEL_PATH, f"companies.{ticker}.baseline.market"), "Wind当前市值。", input_type="direct_fact"),
    ]
    outputs = [_output(
        "Forward PE目标市值", "亿元人民币", "2027", "FY2027归母净利润×目标PE区间",
        pe["formula"], low=low, high=high, group="核心估值", conclusion=f"对应{price_low:.2f}—{price_high:.2f}元/股。",
    )]
    for method in calculated:
        if method is pe:
            continue
        outputs.append(_output(
            f"{method['method']}目标市值", "亿元人民币", "2026-07-30", method.get("formula", "按冻结输入计算"),
            str(method.get("input") or "冻结输入"), low=method["equity_value_low_100m_cny"], high=method["equity_value_high_100m_cny"],
            group="诊断估值", conclusion=method.get("limitation", "仅作交叉验证。"),
        ))
    valuation_model = {
        "run_key": val_key, "skill_name": "company_valuation_modeling", "model_name": f"Run16 {company['name']}多方法估值与交易观察",
        "model_role": "reference", "forecast_start": "2026", "forecast_end": "2028", "valuation_date": AS_OF,
        "assumptions": {"pb_framework": framework, "scenario_workbench": workbench, "company_detail_summary": summary, "core_method": "Forward PE", "diagnostic_methods": [m["method"] for m in calculated if m is not pe]},
        "limitations": "核心区间只采用适用的Forward PE；DCF和PB—ROE不机械平均，方法依赖和终值占比需单独检查。",
        "finalization": "reviewed", "inputs": inputs, "outputs": outputs,
        # 市场价格已经作为参考模型输入并由下方“市场隐含预期”诊断模型单独
        # 输出；reviewed 模型不能伪装成“先独立冻结、再外部对账”的主模型。
        "reconciliations": [],
    }
    implied_profit = market_cap / ((pe["input"]["multiple_low"]["value"] + pe["input"]["multiple_high"]["value"]) / 2)
    implied_key = f"ol16:{ticker}:market_implied:v1"
    implied_model = {
        "run_key": implied_key, "skill_name": "company_valuation_modeling", "model_name": f"Run16 {company['name']}当前市场隐含预期",
        "model_role": "diagnostic", "forecast_start": "2027", "forecast_end": "2027", "valuation_date": AS_OF,
        "assumptions": {"target_pe_midpoint": (pe["input"]["multiple_low"]["value"] + pe["input"]["multiple_high"]["value"]) / 2},
        "limitations": "隐含利润只解释当前价格在目标PE中值下要求的利润，不代表市场真实唯一预期。",
        "finalization": "reviewed",
        "inputs": [_input("当前总市值", market_cap, "亿元人民币", AS_OF, _ref(MODEL_PATH, f"companies.{ticker}.baseline.market"), "Wind当前总市值。", input_type="direct_fact")],
        "outputs": [_output("隐含归母净利润", "亿元人民币", "2027", "当前总市值÷目标PE中值", f"{market_cap:.2f}÷目标PE中值={implied_profit:.2f}", value=implied_profit, group="市场隐含", conclusion="与独立FY2027利润比较判断定价要求。")],
        "reconciliations": [],
    }
    implied_observations = [_observation(
        "net_income", implied_profit, "亿元人民币", "implied", "internal_model", "目标PE中值下的隐含归母净利润", "external_reconciliation",
        fiscal_year=2027, fiscal_period="FY2", period_end="2027-12-31", scenario="target_pe_midpoint", currency="CNY",
        formula="当前总市值÷目标PE中值", model_run_key=implied_key,
    )]
    return [valuation_model, implied_model], implied_observations


def build() -> dict[str, Any]:
    model = _read(MODEL_PATH)
    reconciliation = _read(RECON_PATH)
    sell_side = _read(SELL_SIDE_PATH)
    report_index: dict[tuple[str, str, str], int] = {}
    for index, report in enumerate(sell_side.get("reports") or []):
        key = (
            str(report.get("ticker") or "").upper(),
            str(report.get("institution") or "机构未注明"),
            str(report.get("publish_date") or "日期未注明"),
        )
        if key in report_index:
            raise ValueError(f"卖方报告来源键重复，无法建立唯一引用：{key}")
        report_index[key] = index
    actual_payloads, actual_paths = _merge_snapshots(ACTUAL_PATHS, "actual_before_consensus")
    consensus_payloads, consensus_paths = _merge_snapshots(CONSENSUS_PATHS, "external_reconciliation_after_independent_freeze")
    rec_by_ticker = {row["ticker"]: row for row in reconciliation["reconciliations"]}
    artifacts = [
        MODEL_PATH,
        RECON_PATH,
        PARENT_EQUITY_PATH,
        SELL_SIDE_PATH,
        *ACTUAL_PATHS,
        *CONSENSUS_PATHS,
    ]
    companies = []
    for ticker, company in model["companies"].items():
        actual_payload = actual_payloads[ticker]
        consensus_payload = consensus_payloads[ticker]
        rec = rec_by_ticker[ticker]
        financial_model, internal_observations = _financial_model(
            ticker, company, rec, report_index
        )
        valuation_models, implied_observations = _valuation_models(ticker, company, rec)
        observations = _actual_observations(ticker, actual_payload)
        observations.extend(_consensus_observations(ticker, rec))
        observations.extend(internal_observations)
        observations.extend(implied_observations)
        companies.append({
            "research_company_id": int(company["company_id"]),
            "security": {"canonical_name": company["name"], "ticker": ticker, "market": ticker.split(".")[-1], "listing_status": "listed", "reporting_currency": "CNY", "identity_status": "verified"},
            "source_snapshots": _source_snapshots(ticker, actual_paths[ticker], consensus_paths[ticker], actual_payload, consensus_payload),
            "model_runs": [financial_model, *valuation_models], "observations": observations,
        })
    return {
        "export_schema_version": EXPORT_SCHEMA_VERSION, "research_run_ref": RUN_REF,
        "as_of_date": AS_OF,
        "source_artifacts": [{"path": _rel(path), "sha256": _sha(path)} for path in artifacts],
        "companies": companies,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    payload = build()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output.resolve()), "companies": len(payload["companies"]), "observations": sum(len(row["observations"]) for row in payload["companies"]), "model_runs": sum(len(row["model_runs"]) for row in payload["companies"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
