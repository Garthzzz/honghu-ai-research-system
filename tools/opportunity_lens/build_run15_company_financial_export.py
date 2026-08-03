from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from tools.financial.constants import ROOT
from tools.financial.opportunity_profile_export import EXPORT_SCHEMA_VERSION
from tools.opportunity_lens.run15_portable_artifacts import (
    materialize_run15_portable_artifacts,
)


RUN_DIR = (
    ROOT
    / "opportunity_lens"
    / "research_outputs"
    / "20260725_chint_pv_profit_quality_run15"
)
SNAPSHOT_PATH = ROOT / "cache" / "chint_run15" / "financial_actual_snapshot.json"
WIND_SNAPSHOT_PATH = (
    ROOT / "cache" / "chint_run15" / "wind_financial_snapshot_20260726.json"
)
INPUT_PATH = ROOT / "cache" / "chint_run15" / "run15_chint_financial_inputs.json"
MODEL_PATH = ROOT / "cache" / "chint_run15" / "run15_chint_financial_model.json"
RECONCILIATION_PATH = (
    ROOT / "cache" / "chint_run15" / "run15_external_reconciliation.json"
)
OUTPUT_PATH = RUN_DIR / "company_financial_profile_export_v1.json"

RESEARCH_RUN_REF = "opportunity_lens:run15:chint_pv_profit_quality:20260725"
AS_OF_DATE = "2026-07-24"
TICKER = "601877.SH"
COMPANY_ID = 632


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact_ref(path: Path, pointer: str) -> str:
    return f"{_sha256_file(path)}#{pointer}"


def _input(
    name: str,
    *,
    value: float | None = None,
    value_text: str | None = None,
    unit: str,
    period: str,
    source_ref: str,
    input_type: str,
    method: str,
    sensitivity: str | None = None,
    limitation: str | None = None,
) -> dict[str, Any]:
    return {
        "input_name": name,
        "value_num": value,
        "value_text": value_text,
        "unit": unit,
        "period_or_as_of_date": period,
        "source_ref": source_ref,
        "input_type": input_type,
        "formula_or_method": method,
        "sensitivity_note": sensitivity,
        "limitation_note": limitation,
    }


def _output(
    name: str,
    value: float,
    *,
    unit: str,
    period: str,
    formula: str,
    substitution: str,
    dependency: str,
    conclusion: str,
) -> dict[str, Any]:
    return {
        "output_name": name,
        "value_num": float(value),
        "unit": unit,
        "period_or_as_of_date": period,
        "formula": formula,
        "substitution": substitution,
        "dependency_group": dependency,
        "conclusion": conclusion,
    }


def _observation(
    *,
    metric: str,
    value: float,
    unit: str,
    fact_type: str,
    provider: str,
    raw_feature_name: str,
    source_snapshot_key: str,
    fiscal_year: int | None = None,
    fiscal_period: str | None = None,
    period_end: str | None = None,
    frequency: str = "annual",
    scenario_name: str = "reported",
    currency: str | None = None,
    formula: str | None = None,
    model_run_key: str | None = None,
    announcement_date: str | None = None,
    input_refs: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "metric_name": metric,
        "value_num": float(value),
        "unit": unit,
        "currency": currency,
        "period_end": period_end,
        "fiscal_year": fiscal_year,
        "fiscal_period": fiscal_period,
        "frequency": frequency,
        "fact_type": fact_type,
        "as_of_date": AS_OF_DATE,
        "announcement_date": announcement_date,
        "provider": provider,
        "raw_feature_name": raw_feature_name,
        "formula": formula,
        "input_refs": list(input_refs or []),
        "quality_status": "usable",
        "scenario_name": scenario_name,
        "source_snapshot_key": source_snapshot_key,
        "model_run_key": model_run_key,
    }


def _source_snapshots(
    snapshot: dict[str, Any],
    wind_snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    fetched_at = snapshot.get("accessed_at_utc")
    wind_fetched_at = wind_snapshot.get("accessed_at_utc")
    return [
        {
            "key": "wind_snapshot",
            "provider": "wind",
            "source_channel": "structured_api",
            "source_ref": f"{RESEARCH_RUN_REF}:wind:{TICKER}",
            "title": "正泰电器Wind单证券市场、年度财务与一致预期快照",
            "publisher": "Wind内网HTTP代理",
            "as_of_date": AS_OF_DATE,
            "fetched_at": wind_fetched_at,
            "content_hash": _sha256_file(WIND_SNAPSHOT_PATH),
            "raw_snapshot_path": str(WIND_SNAPSHOT_PATH.relative_to(ROOT)),
            "metadata": {
                "scope": (
                    "单证券、12个市场字段、5个年度的11个财务字段及"
                    "12个FY1—FY3一致预期字段，共预计79个观测。"
                ),
                "ticker": TICKER,
                "merge_role": "A股同口径非空字段主源",
            },
        },
        {
            "key": "tushare_snapshot",
            "provider": "tushare",
            "source_channel": "structured_api",
            "source_ref": f"{RESEARCH_RUN_REF}:tushare:{TICKER}",
            "title": "正泰电器Tushare单证券市场与公告期财务快照",
            "publisher": "Tushare",
            "as_of_date": AS_OF_DATE,
            "fetched_at": fetched_at,
            "content_hash": _sha256_file(SNAPSHOT_PATH),
            "raw_snapshot_path": str(SNAPSHOT_PATH.relative_to(ROOT)),
            "metadata": {
                "scope": (
                    "单证券、有限报告期与窄字段；仅用于Wind未覆盖的"
                    "季度公告明细、股息率和逐字段补缺。"
                ),
                "ticker": TICKER,
                "merge_role": "逐字段补缺，不覆盖Wind非空同口径值",
            },
        },
        {
            "key": "independent_model",
            "provider": "internal_model",
            "source_channel": "internal_calculation",
            "source_ref": f"{RESEARCH_RUN_REF}:independent_model:{TICKER}",
            "title": "正泰电器Run15冻结独立财务与估值模型",
            "publisher": "Industry Demo内部研究模型",
            "as_of_date": AS_OF_DATE,
            "fetched_at": None,
            "content_hash": _sha256_file(MODEL_PATH),
            "raw_snapshot_path": str(MODEL_PATH.relative_to(ROOT)),
            "metadata": {
                "input_hash": _sha256_file(INPUT_PATH),
                "frozen_before_external_reconciliation": True,
            },
        },
        {
            "key": "external_reconciliation",
            "provider": "internal_model",
            "source_channel": "internal_calculation",
            "source_ref": f"{RESEARCH_RUN_REF}:external_reconciliation:{TICKER}",
            "title": "正泰电器Run15冻结后外部预测对账",
            "publisher": "Industry Demo内部研究模型",
            "as_of_date": AS_OF_DATE,
            "fetched_at": None,
            "content_hash": _sha256_file(RECONCILIATION_PATH),
            "raw_snapshot_path": str(RECONCILIATION_PATH.relative_to(ROOT)),
            "metadata": {
                "independent_model_hash": _sha256_file(MODEL_PATH),
                "sequence_control": "独立模型冻结后才读取机构预测。",
            },
        },
    ]


def _wind_frame_row(container: dict[str, Any]) -> dict[str, Any]:
    rows = container.get("rows") or {}
    if not rows:
        raise ValueError("Wind快照缺少可解析观测行")
    return next(iter(rows.values()))


def _actual_and_market_observations(
    snapshot: dict[str, Any],
    wind_snapshot: dict[str, Any],
    model: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    actual_fields = {
        "revenue_100m_cny": ("revenue", "亿元人民币", "CNY"),
        "parent_net_income_100m_cny": ("net_income", "亿元人民币", "CNY"),
        "operating_cash_flow_100m_cny": (
            "operating_cash_flow",
            "亿元人民币",
            "CNY",
        ),
        "fixed_asset_capex_100m_cny": ("capex", "亿元人民币", "CNY"),
        "roe_pct": ("roe", "%", None),
    }
    for year in (2023, 2024, 2025):
        annual = model["actual"][str(year)]
        wind_row = _wind_frame_row(
            wind_snapshot["wind"]["historical_annual"][str(year)]
        )
        for field, (metric, unit, currency) in actual_fields.items():
            if field not in annual:
                continue
            wind_feature = {
                "revenue_100m_cny": "oper_rev",
                "parent_net_income_100m_cny": "np_belongto_parcomsh",
                "operating_cash_flow_100m_cny": "net_cash_flows_oper_act",
                "fixed_asset_capex_100m_cny": "cash_pay_acq_const_fiolta",
                "roe_pct": "roe",
            }[field]
            raw_value = wind_row.get(wind_feature)
            if raw_value is None:
                raise ValueError(
                    f"Wind {year} {wind_feature}为空，需显式走Tushare补缺"
                )
            value = (
                float(raw_value) / 1e8
                if unit == "亿元人民币"
                else float(raw_value)
            )
            rows.append(
                _observation(
                    metric=metric,
                    value=value,
                    unit=unit,
                    fact_type="actual",
                    provider="wind",
                    raw_feature_name=f"WSS.{wind_feature}",
                    source_snapshot_key="wind_snapshot",
                    fiscal_year=year,
                    fiscal_period="FY",
                    period_end=f"{year}-12-31",
                    scenario_name="已披露实际",
                    currency=currency,
                    announcement_date={
                        2023: "2024-04-30",
                        2024: "2025-04-30",
                        2025: "2026-04-16",
                    }[year],
                    input_refs=[
                        _artifact_ref(
                            WIND_SNAPSHOT_PATH,
                            f"wind.historical_annual.{year}.{wind_feature}",
                        )
                    ],
                )
            )
    annual_2025 = model["actual"]["2025"]
    for field, metric, unit in (
        ("gross_profit_100m_cny", "gross_profit", "亿元人民币"),
        ("parent_equity_100m_cny", "parent_equity", "亿元人民币"),
        ("total_assets_100m_cny", "total_assets", "亿元人民币"),
        ("inventory_100m_cny", "inventory", "亿元人民币"),
    ):
        rows.append(
            _observation(
                metric=metric,
                value=annual_2025[field],
                unit=unit,
                fact_type="actual",
                provider="tushare",
                raw_feature_name={
                    "gross_profit_100m_cny": "derived.revenue_minus_oper_cost",
                    "parent_equity_100m_cny": "balancesheet.total_hldr_eqy_exc_min_int",
                    "total_assets_100m_cny": "balancesheet.total_assets",
                    "inventory_100m_cny": "balancesheet.inventories",
                }[field],
                source_snapshot_key="tushare_snapshot",
                fiscal_year=2025,
                fiscal_period="FY",
                period_end="2025-12-31",
                scenario_name="已披露实际",
                currency="CNY",
                announcement_date="2026-04-16",
                input_refs=[
                    _artifact_ref(SNAPSHOT_PATH, f"tushare.{metric}.2025")
                ],
            )
        )
    q1 = model["actual"]["2026_q1"]
    for field, metric in (
        ("revenue_100m_cny", "revenue"),
        ("parent_net_income_100m_cny", "net_income"),
        ("operating_cash_flow_100m_cny", "operating_cash_flow"),
    ):
        rows.append(
            _observation(
                metric=metric,
                value=q1[field],
                unit="亿元人民币",
                fact_type="actual",
                provider="tushare",
                raw_feature_name={
                    "revenue_100m_cny": "income.revenue",
                    "parent_net_income_100m_cny": "income.n_income_attr_p",
                    "operating_cash_flow_100m_cny": "cashflow.n_cashflow_act",
                }[field],
                source_snapshot_key="tushare_snapshot",
                fiscal_year=2026,
                fiscal_period="Q1",
                period_end="2026-03-31",
                frequency="quarterly",
                scenario_name="已披露实际",
                currency="CNY",
                announcement_date="2026-04-16",
                input_refs=[
                    _artifact_ref(SNAPSHOT_PATH, f"tushare.2026_q1.{metric}")
                ],
            )
        )
    for field, metric, raw_feature in (
        ("revenue_growth_pct", "revenue_yoy", "income.revenue_yoy"),
        (
            "parent_profit_growth_pct",
            "net_income_yoy",
            "income.n_income_attr_p_yoy",
        ),
    ):
        rows.append(
            _observation(
                metric=metric,
                value=q1[field],
                unit="%",
                fact_type="actual",
                provider="tushare",
                raw_feature_name=raw_feature,
                source_snapshot_key="tushare_snapshot",
                fiscal_year=2026,
                fiscal_period="Q1",
                period_end="2026-03-31",
                frequency="quarterly",
                scenario_name="已披露实际",
                currency=None,
                announcement_date="2026-04-16",
                input_refs=[
                    _artifact_ref(SNAPSHOT_PATH, f"tushare.2026_q1.{metric}")
                ],
            )
        )
    wind_market = wind_snapshot["wind"]["current"]
    for raw, metric, unit, currency in (
        ("price", "share_price", "元/股", "CNY"),
        ("market_cap_cny", "market_cap", "亿元人民币", "CNY"),
        ("pe_ttm", "pe_ttm", "倍", None),
        ("pe_forward", "pe_forward", "倍", None),
        ("pb", "pb", "倍", None),
        ("ps_ttm", "ps_ttm", "倍", None),
        ("ev_ebitda", "ev_ebitda", "倍", None),
        ("roe", "roe", "%", None),
        ("roa", "roa", "%", None),
        ("eps_ttm", "eps", "元/股", "CNY"),
        ("bps_mrq", "bps", "元/股", "CNY"),
    ):
        value = wind_market.get(raw)
        if value is None:
            continue
        rows.append(
            _observation(
                metric=metric,
                value=float(value),
                unit=unit,
                fact_type="market",
                provider="wind",
                raw_feature_name=(
                    wind_market.get("field_methods", {})
                    .get(raw, {})
                    .get("api_fields", [f"Wind WSS.{raw}"])[0]
                ),
                source_snapshot_key="wind_snapshot",
                period_end="2026-07-24",
                frequency="snapshot",
                scenario_name="市场实际",
                currency=currency,
                input_refs=[
                    _artifact_ref(
                        WIND_SNAPSHOT_PATH,
                        f"wind.current.{raw}",
                    )
                ],
            )
        )
    tushare_market = snapshot["tushare"]["daily_basic_latest"]
    if tushare_market.get("dv_ttm") is not None:
        rows.append(
            _observation(
                metric="dividend_yield",
                value=float(tushare_market["dv_ttm"]),
                unit="%",
                fact_type="market",
                provider="tushare",
                raw_feature_name="daily_basic.dv_ttm",
                source_snapshot_key="tushare_snapshot",
                period_end="2026-07-24",
                frequency="snapshot",
                scenario_name="市场实际",
                currency=None,
                input_refs=[
                    _artifact_ref(
                        SNAPSHOT_PATH,
                        "tushare.daily_basic_latest.dv_ttm",
                    )
                ],
            )
        )
    return rows


def _consensus_observations(
    reconciliation: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    medians = reconciliation["benchmark_median"]
    for year in (2026, 2027, 2028):
        year_key = str(year)
        for source_metric, metric in (
            ("revenue_100m_cny", "revenue"),
            ("parent_net_income_100m_cny", "net_income"),
        ):
            rows.append(
                _observation(
                    metric=metric,
                    value=medians[source_metric][year_key],
                    unit="亿元人民币",
                    fact_type="consensus",
                    provider="sell_side_median",
                    raw_feature_name=f"五家近期公司研报中位数.{source_metric}",
                    source_snapshot_key="external_reconciliation",
                    fiscal_year=year,
                    fiscal_period=f"FY{year - 2025}",
                    period_end=f"{year}-12-31",
                    scenario_name="五家近期公司研报中位数",
                    currency="CNY",
                    formula=(
                        "国联民生、光大、兴业、长江和摩根士丹利"
                        "最近两个季度同口径公司预测的中位数"
                    ),
                    input_refs=[
                        _artifact_ref(
                            RECONCILIATION_PATH,
                            f"benchmark_median.{source_metric}.{year_key}",
                        )
                    ],
                )
            )
    wind_consensus = reconciliation["wind_consensus"]
    wind_specs = (
        ("revenue_100m_cny", "revenue", "亿元人民币", "CNY"),
        (
            "parent_net_income_100m_cny",
            "net_income",
            "亿元人民币",
            "CNY",
        ),
        ("eps_cny", "eps", "元/股", "CNY"),
        ("average_roe_pct", "roe", "%", None),
    )
    for year in (2026, 2027, 2028):
        year_key = str(year)
        for source_metric, metric, unit, currency in wind_specs:
            rows.append(
                _observation(
                    metric=metric,
                    value=wind_consensus[source_metric][year_key],
                    unit=unit,
                    fact_type="consensus",
                    provider="wind",
                    raw_feature_name=(
                        "Wind WSS."
                        + wind_consensus["raw_feature_names"][
                            {
                                "revenue_100m_cny": "revenue",
                                "parent_net_income_100m_cny": (
                                    "parent_net_income"
                                ),
                                "eps_cny": "eps",
                                "average_roe_pct": "roe",
                            }[source_metric]
                        ]
                    ),
                    source_snapshot_key="wind_snapshot",
                    fiscal_year=year,
                    fiscal_period=f"FY{year - 2025}",
                    period_end=f"{year}-12-31",
                    scenario_name="Wind一致预期",
                    currency=currency,
                    formula=(
                        "Wind在2026-07-24可见的FY1—FY3聚合一致预期；"
                        "与本地卖方报告中位数分开保存"
                    ),
                    input_refs=[
                        _artifact_ref(
                            WIND_SNAPSHOT_PATH,
                            f"wind.consensus_fy1_fy3.{source_metric}.{year_key}",
                        )
                    ],
                )
            )
    return rows


def _financial_model(
    model: dict[str, Any], reconciliation: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    run_key = "ol15:601877.SH:independent_financial_bridge:v5"
    base_rows = model["scenarios"]["基准情景"]
    inputs = [
        _input(
            "2025年营业收入",
            value=model["actual"]["2025"]["revenue_100m_cny"],
            unit="亿元人民币",
            period="2025",
            source_ref=_artifact_ref(MODEL_PATH, "actual.2025.revenue_100m_cny"),
            input_type="direct_fact",
            method="公司年报实际值，统一为亿元人民币。",
        ),
        _input(
            "2025年归母净利润",
            value=model["actual"]["2025"]["parent_net_income_100m_cny"],
            unit="亿元人民币",
            period="2025",
            source_ref=_artifact_ref(
                MODEL_PATH, "actual.2025.parent_net_income_100m_cny"
            ),
            input_type="direct_fact",
            method="公司年报归母口径。",
        ),
        _input(
            "分业务预测方法",
            value_text=(
                "分别预测低压电器、逆变器与储能、户用合作运营、"
                "户用电站转让、非户用运营与EPC，再汇总毛利和归母利润；"
                "项目电站存货通过营运资金进入现金流，不重复计入固定资产资本开支。"
            ),
            unit="文字",
            period="2026—2028",
            source_ref=_artifact_ref(INPUT_PATH, "scenarios"),
            input_type="expert_assumption",
            method="Run15冻结的Level 2分部经营模型与现金流桥。",
            sensitivity="电站转让规模和毛利、合作运营毛利、营运资金与发电保障成本。",
            limitation="项目级交割、回款、发电量和合同责任公开不足，使用透明情景而非伪精确项目模型。",
        ),
    ]
    outputs: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    shares_100m = (
        model["valuation"]["market_cap_100m_cny"]
        / model["valuation"]["market_price_cny"]
    )
    ending_equity = float(model["actual"]["2025"]["parent_equity_100m_cny"])
    for row in base_rows:
        year = int(row["year"])
        field_specs = (
            ("revenue_100m_cny", "营业收入", "revenue", "亿元人民币"),
            (
                "parent_net_income_100m_cny",
                "归母净利润",
                "net_income",
                "亿元人民币",
            ),
            (
                "operating_cash_flow_100m_cny",
                "经营现金流",
                "operating_cash_flow",
                "亿元人民币",
            ),
            (
                "fixed_asset_capex_100m_cny",
                "资本开支",
                "capex",
                "亿元人民币",
            ),
            (
                "free_cash_flow_100m_cny",
                "自由现金流",
                "free_cash_flow",
                "亿元人民币",
            ),
            ("gross_margin_pct", "毛利率", "gross_margin", "%"),
        )
        for field, label, metric, unit in field_specs:
            value = float(row[field])
            formula = {
                "revenue_100m_cny": "各分部收入汇总",
                "parent_net_income_100m_cny": "合并税后利润×归母比例",
                "operating_cash_flow_100m_cny": "净利润＋非现金项目－营运资金新增占用",
                "fixed_asset_capex_100m_cny": "固定资产建设与维持性资本开支",
                "free_cash_flow_100m_cny": "经营现金流－固定资产资本开支",
                "gross_margin_pct": "合并毛利润÷营业收入",
            }[field]
            outputs.append(
                _output(
                    f"{year}年{label}",
                    value,
                    unit=unit,
                    period=str(year),
                    formula=formula,
                    substitution=f"Run15冻结基准＝{value:.2f}{unit}",
                    dependency="独立经营与现金流路径",
                    conclusion="内部独立预测，不是外部一致预期。",
                )
            )
            observations.append(
                _observation(
                    metric=metric,
                    value=value,
                    unit=unit,
                    fact_type="internal_estimate",
                    provider="internal_model",
                    raw_feature_name=f"Run15基准情景.{field}",
                    source_snapshot_key="independent_model",
                    model_run_key=run_key,
                    fiscal_year=year,
                    fiscal_period=f"FY{year - 2025}",
                    period_end=f"{year}-12-31",
                    scenario_name="Run15独立基准",
                    currency="CNY" if "人民币" in unit else None,
                    formula=formula,
                    input_refs=[
                        _artifact_ref(MODEL_PATH, f"scenarios.基准情景.{year}")
                    ],
                )
            )
        profit = float(row["parent_net_income_100m_cny"])
        payout_ratio = 0.30
        closing_equity = ending_equity + profit * (1.0 - payout_ratio)
        average_equity = (ending_equity + closing_equity) / 2
        roe = profit / average_equity * 100
        eps = profit / shares_100m
        bps = closing_equity / shares_100m
        for metric, value, unit, formula in (
            (
                "parent_equity",
                closing_equity,
                "亿元人民币",
                "期初归母权益＋归母净利润×（1－30%现金分红率）",
            ),
            ("roe", roe, "%", "归母净利润÷平均归母权益"),
            ("eps", eps, "元/股", "归母净利润÷总股本"),
            ("bps", bps, "元/股", "期末归母权益÷总股本"),
        ):
            observations.append(
                _observation(
                    metric=metric,
                    value=value,
                    unit=unit,
                    fact_type="internal_estimate",
                    provider="internal_model",
                    raw_feature_name=f"Run15归母权益桥.{metric}",
                    source_snapshot_key="independent_model",
                    model_run_key=run_key,
                    fiscal_year=year,
                    fiscal_period=f"FY{year - 2025}",
                    period_end=f"{year}-12-31",
                    scenario_name="Run15独立基准",
                    currency="CNY" if "元" in unit else None,
                    formula=formula,
                    input_refs=[
                        _artifact_ref(MODEL_PATH, f"scenarios.基准情景.{year}")
                    ],
                )
            )
        ending_equity = closing_equity

    recs: list[dict[str, Any]] = []
    medians = reconciliation["benchmark_median"]
    independent = reconciliation["independent_model"]
    for year in (2026, 2027, 2028):
        year_key = str(year)
        for metric, label, unit in (
            ("revenue_100m_cny", "revenue", "亿元人民币"),
            ("parent_net_income_100m_cny", "net_income", "亿元人民币"),
        ):
            recs.append(
                {
                    "benchmark_type": "consensus",
                    "benchmark_source_ref": _artifact_ref(
                        RECONCILIATION_PATH,
                        f"benchmark_median.{metric}.{year_key}",
                    ),
                    "metric_name": label,
                    "period": str(year),
                    "independent_value": independent[metric][year_key],
                    "benchmark_value": medians[metric][year_key],
                    "unit": unit,
                    "decomposition": {
                        "difference_pct": reconciliation[
                            "difference_vs_recent_report_median_pct"
                        ][
                            "revenue"
                            if metric == "revenue_100m_cny"
                            else "parent_net_income"
                        ][year_key],
                        "drivers": [
                            "独立模型采用更高的低毛利电站转让规模",
                            "合作运营和低压电器利润决定净利润差异",
                        ],
                    },
                    "conclusion": "收入差异显著大于利润差异，未发现单位、财年或归母口径错误。",
                }
            )
            wind_metric = (
                "revenue_100m_cny"
                if metric == "revenue_100m_cny"
                else "parent_net_income_100m_cny"
            )
            recs.append(
                {
                    "benchmark_type": "consensus",
                    "benchmark_source_ref": _artifact_ref(
                        WIND_SNAPSHOT_PATH,
                        f"wind.consensus_fy1_fy3.{wind_metric}.{year_key}",
                    ),
                    "metric_name": label,
                    "period": str(year),
                    "independent_value": independent[metric][year_key],
                    "benchmark_value": reconciliation["wind_consensus"][
                        wind_metric
                    ][year_key],
                    "unit": unit,
                    "decomposition": {
                        "difference_pct": reconciliation[
                            "difference_vs_wind_consensus_pct"
                        ][
                            "revenue"
                            if metric == "revenue_100m_cny"
                            else "parent_net_income"
                        ][year_key],
                        "duplicate_control": (
                            "Wind聚合一致预期与五份本地卖方报告分开对账，"
                            "不混算中位数。"
                        ),
                    },
                    "conclusion": (
                        "独立利润与Wind一致预期更接近，主要分歧是"
                        "低毛利电站转让收入。"
                    ),
                }
            )
    return (
        {
            "run_key": run_key,
            "skill_name": "company_financial_modeling",
            "model_name": "Run15正泰电器分业务财务与现金流桥",
            "model_role": "primary",
            "supersedes_run_keys": [
                "ol15:601877.SH:independent_financial_bridge:v1",
                "ol15:601877.SH:independent_financial_bridge:v2",
                "ol15:601877.SH:independent_financial_bridge:v3",
                "ol15:601877.SH:independent_financial_bridge:v4",
            ],
            "forecast_start": "2026",
            "forecast_end": "2028",
            "valuation_date": AS_OF_DATE,
            "assumptions": {
                "model_level": "Level 2分部经营模型与现金流桥",
                "independent_before_consensus": True,
                "cash_flow_policy": "项目存货进入营运资金，固定资产资本开支单独扣除，避免重复。",
            },
            "limitations": "逐项目交割、现金回款、区域发电量和合同责任公开不足；模型用于数量级与情景传导。",
            "finalization": "independent",
            "inputs": inputs,
            "outputs": outputs,
            "reconciliations": recs,
        },
        observations,
    )


def _valuation_models(
    model: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    valuation = model["valuation"]
    base_2026 = model["scenarios"]["基准情景"][0]
    core_value_low, core_value_high = valuation[
        "research_core_value_range_100m_cny"
    ]
    core_price_low, core_price_high = valuation[
        "research_core_price_range_cny"
    ]
    summary = {
        "conclusion": (
            f"当前24.45元低于三种适用方法严格交集形成的"
            f"{core_price_low:.2f}—{core_price_high:.2f}元，"
            "但折价主要对应电站交割、营运资金和长期责任，不能仅凭低PE判断买点。"
        ),
        "operating_analysis": (
            "2025年收入591.45亿元、归母净利润45.01亿元、经营现金流230.90亿元；"
            "当年存货增加消耗125.67亿元、经营性应付款增加贡献235.14亿元，"
            "单年现金流高点不可直接外推。独立模型把2026年低压电器、逆变器与储能、"
            "合作运营和电站转让收入分别取237/31/130/280亿元，其中转让毛利率仅7%，"
            "因此得到751亿元收入却只有54.9亿元归母净利润。2026—2028年归母净利润"
            "为54.9/66.4/78.3亿元，自由现金流69.5/82.6/96.2亿元。"
        ),
        "valuation_analysis": (
            "当前市值525.42亿元、滚动PE 11.41倍、PB 1.19倍；"
            "按独立2026年利润计算约9.57倍PE。市盈率、分部估值和PB—ROE"
            f"区间的严格交集为{core_value_low:.2f}—{core_value_high:.2f}亿元，"
            f"对应{core_price_low:.2f}—{core_price_high:.2f}元。"
            "这里的交集不是方法平均，也不代表三条完全独立证据。"
            "PB反推长期ROE约10.72%，"
            "低于独立前瞻ROE 11.83%。五份近期公司研报的2026年利润中位数为"
            "52.43亿元，Wind一致预期为54.16亿元，与独立54.90亿元接近；"
            "主要分歧不是利润，而是低毛利电站交割量和现金回收。模型另假设"
            "经营与融资等扣减率由2025年约13.8%降至12.5%；若少改善1个百分点，"
            "归母利润约少4.46亿元、每股价值约低2.39—2.90元。"
        ),
        "buy_point_analysis": (
            "24—25元可作为有条件观察区，但需要未来两个报告期看到电站转让、"
            "现金回款和项目库存下降同步，合作运营毛利率维持50%以上。"
            "若2026年利润接近54.9亿元、经营现金流接近91.5亿元，"
            f"{core_price_low:.2f}元以上才进入三种方法的共同支持区；"
            "单有收入增长而无现金改善不构成买点。"
        ),
        "sell_point_analysis": (
            f"{core_price_high:.2f}元以上若没有合作运营增长、现金回收和担保成本改善，"
            "已接近多方法区间上沿，应降低仓位或等待验证。若跌破24元同时出现"
            "年度净营运资金新增占用进入30亿元以上、合作运营毛利连续低于48%，"
            "也不能机械视为低PB买点；组合风险情景按当前PE只对应约20—22元。"
        ),
        "difference_causes": [
            "独立收入预测比五份近期公司研报中位数高18.74%—24.86%，主要来自低毛利电站转让量。",
            "独立净利润比近期报告中位数高4.71%—10.08%，与Wind一致预期只差1.37%—5.91%。",
            "市场PB隐含ROE低于独立前瞻ROE，折价对应现金波动、担保和长期发电保障。",
        ],
        "future_view": (
            "未来一年先看交割、存货和回款是否同向改善；"
            "2027—2028年重点验证合作运营毛利、发电保障成本和代理商治理。"
        ),
        "positive_trigger": (
            "电站转让现金回收同步增长、合作运营毛利率维持50%以上，"
            "且担保、代偿和预计负债占利润比例不升。"
        ),
        "risk_trigger": (
            "连续两个报告期存货和应收快于收入、年度净营运资金新增占用超过30亿元，"
            "或运营毛利跌破48%、代偿与预计负债明显上升。"
        ),
    }
    pb_framework = {
        "applicability": "有效交叉验证",
        "cycle_sensitivity": "电站交割和电价存在周期与政策波动，必须同时观察ROA和现金流。",
        "asset_intensity": "低压电器与持有型电站具有资产基础，但转让业务的存货和担保不能只看账面净资产。",
        "basis": (
            "PB—ROE用于检验账面权益的回报能否支撑估值；"
            "由于电站转让、少数股东和长期责任影响现金质量，不能作为唯一估值方法。"
        ),
        "profit_driver": "合作运营毛利、电站转让毛利、低压电器利润、营运资金和归母比例。",
        "tags": [
            {"label": "业务组合", "basis": "高毛利运营和低毛利转让共同决定ROE。"},
            {"label": "资产周转", "basis": "项目存货交割速度影响现金和资产回报。"},
            {"label": "长期责任", "basis": "发电保障、担保和运维可能形成尾部成本。"},
            {"label": "现金约束", "basis": "经营现金流受项目交割与应付款时点影响。"},
        ],
    }
    scenario_workbench = {
        "simple_ready": True,
        "detailed_ready": False,
        "default_mode": "simple",
        "reason": (
            "现有数据足以用期初归母净资产、FY1—FY3归母净利润和目标PB做简化权益桥；"
            "逐项目资产、债务、发电量和责任数据不足以支持详细模式。"
        ),
        "simple": {
            "opening_book_value_cny_100m": model["actual"]["2025"][
                "parent_equity_100m_cny"
            ],
            "current_pb": valuation["market_pb"],
            "target_pb": 1.30,
            "years": [
                {
                    "fiscal_year": int(row["year"]),
                    "net_income_cny_100m": float(
                        row["parent_net_income_100m_cny"]
                    ),
                    "payout_ratio_pct": 30.0,
                }
                for row in model["scenarios"]["基准情景"]
            ],
            "pb_presets": {
                "current": valuation["market_pb"],
                "research_low": 1.20,
                "research_mid": 1.30,
                "research_high": 1.40,
            },
        },
        "detailed": {
            "available_fields": [
                "分业务收入和毛利率",
                "归母净利润",
                "经营现金流",
                "资本开支",
                "归母净资产",
            ],
            "missing_required_fields": [
                "逐项目交割与现金回款",
                "逐项目债务与买方承接价格",
                "区域发电量与差额补偿",
                "FY1—FY3完整资产负债表",
            ],
        },
    }
    inputs = [
        _input(
            "2026年归母净利润",
            value=base_2026["parent_net_income_100m_cny"],
            unit="亿元人民币",
            period="2026",
            source_ref=_artifact_ref(MODEL_PATH, "scenarios.基准情景.2026"),
            input_type="derived_fact",
            method="Run15冻结分业务财务模型。",
            sensitivity="电站转让量、合作运营毛利和归母比例。",
        ),
        _input(
            "2026年末估计归母净资产",
            value=valuation[
                "estimated_2026_parent_equity_bridge"
            ]["ending_parent_equity_100m_cny"],
            unit="亿元人民币",
            period="2026",
            source_ref=_artifact_ref(INPUT_PATH, "valuation"),
            input_type="expert_assumption",
            method=(
                "445.03亿元期初归母权益＋54.90亿元归母净利润"
                "－16.47亿元现金分红＝483.46亿元。"
            ),
            limitation="缺少完整未来资产负债表，PB—ROE只作交叉验证。",
        ),
        _input(
            "正泰安能交易锚",
            value=353.13,
            unit="亿元人民币",
            period="2026-07",
            source_ref=_artifact_ref(INPUT_PATH, "valuation.aneng_transaction"),
            input_type="derived_fact",
            method="11.16亿元竞得3.16%股权，反推100%股权约353.13亿元。",
            sensitivity="少数股权交易、流动性和控制权折溢价。",
        ),
    ]
    outputs: list[dict[str, Any]] = []
    for method in valuation["methods"]:
        for bound, label in (("low", "下沿"), ("high", "上沿")):
            outputs.append(
                _output(
                    f"{method['method']}股价{label}",
                    method[f"price_{bound}_cny"],
                    unit="元/股",
                    period=AS_OF_DATE,
                    formula=method["basis"],
                    substitution=f"{method[f'price_{bound}_cny']:.2f}元/股",
                    dependency=method["method"],
                    conclusion=f"{method['role']}的条件结果，不是无条件目标价。",
                )
            )
    outputs.extend(
        [
            _output(
                "核心价值区间下沿",
                valuation["research_core_value_range_100m_cny"][0],
                unit="亿元人民币",
                period=AS_OF_DATE,
                formula="三种适用方法共同支持区域的下沿",
                substitution="600.00亿元",
                dependency="多方法共同支持区域",
                conclusion="需要基准利润和现金回收同时成立。",
            ),
            _output(
                "核心价值区间上沿",
                valuation["research_core_value_range_100m_cny"][1],
                unit="亿元人民币",
                period=AS_OF_DATE,
                formula="三种适用方法共同支持区域的上沿",
                substitution="672.00亿元",
                dependency="多方法共同支持区域",
                conclusion="需要合作运营增长和尾部责任稳定。",
            ),
        ]
    )
    core_model = {
        "run_key": "ol15:601877.SH:multi_method_valuation:v5",
        "skill_name": "company_valuation_modeling",
        "model_name": "Run15市盈率、分部估值与PB—ROE综合估值",
        "model_role": "core",
        "supersedes_run_keys": [
            "ol15:601877.SH:multi_method_valuation:v1",
            "ol15:601877.SH:multi_method_valuation:v2",
            "ol15:601877.SH:multi_method_valuation:v3",
            "ol15:601877.SH:multi_method_valuation:v4",
        ],
        "forecast_start": "2026",
        "forecast_end": "2028",
        "valuation_date": AS_OF_DATE,
        "assumptions": {
            "method_roles": {
                "PE": "核心盈利估值",
                "SOTP": "核心结构估值",
                "PB—ROE": "有效交叉验证",
            },
            "aggregation_policy": "取经济解释一致的共同支持区域，不机械平均。",
            "pb_framework": pb_framework,
            "scenario_workbench": scenario_workbench,
            "company_detail_summary": summary,
        },
        "limitations": "电站交割、营运资金、担保和长期责任会改变估值；核心区间是条件价值。",
        "finalization": "independent",
        "inputs": inputs,
        "outputs": outputs,
        "reconciliations": [
            {
                "benchmark_type": "market_implied",
                "benchmark_source_ref": _artifact_ref(
                    WIND_SNAPSHOT_PATH, "wind.current.market_cap_cny"
                ),
                "metric_name": "equity_value",
                "period": AS_OF_DATE,
                "independent_value": valuation[
                    "research_core_value_range_100m_cny"
                ][0],
                "benchmark_value": valuation["market_cap_100m_cny"],
                "unit": "亿元人民币",
                "decomposition": {
                    "core_high": valuation[
                        "research_core_value_range_100m_cny"
                    ][1],
                    "market_price_cny": valuation["market_price_cny"],
                },
                "conclusion": "当前市值低于多方法核心区间，兑现仍取决于现金流和长期责任。",
            }
        ],
    }
    implied_profit = valuation["market_cap_100m_cny"] / 11.5
    implied_model = {
        "run_key": "ol15:601877.SH:market_implied_expectations:v5",
        "skill_name": "company_valuation_modeling",
        "model_name": "Run15当前市场隐含盈利与资产回报",
        "model_role": "diagnostic",
        "supersedes_run_keys": [
            "ol15:601877.SH:market_implied_expectations:v1",
            "ol15:601877.SH:market_implied_expectations:v2",
            "ol15:601877.SH:market_implied_expectations:v3",
            "ol15:601877.SH:market_implied_expectations:v4",
        ],
        "forecast_start": "2026",
        "forecast_end": "2026",
        "valuation_date": AS_OF_DATE,
        "assumptions": {
            "purpose": "解释当前价格要求的利润与ROE，不预测公司必然实现。",
            "diagnostic_pe": 11.5,
            "market_pb": valuation["market_pb"],
        },
        "limitations": "隐含结果随正常化PE、股权成本和长期增长假设变化，只用于市场预期诊断。",
        "finalization": "independent",
        "inputs": [
            _input(
                "当前总市值",
                value=valuation["market_cap_100m_cny"],
                unit="亿元人民币",
                period=AS_OF_DATE,
                source_ref=_artifact_ref(
                    WIND_SNAPSHOT_PATH, "wind.current.market_cap_cny"
                ),
                input_type="direct_fact",
                method="Wind估值日总市值。",
            ),
            _input(
                "诊断市盈率",
                value=11.5,
                unit="倍",
                period="正常化",
                source_ref=_artifact_ref(INPUT_PATH, "valuation"),
                input_type="expert_assumption",
                method="使用PE方法区间下沿反推市场需要的盈利。",
            ),
            _input(
                "当前市净率",
                value=valuation["market_pb"],
                unit="倍",
                period=AS_OF_DATE,
                source_ref=_artifact_ref(
                    WIND_SNAPSHOT_PATH, "wind.current.pb"
                ),
                input_type="direct_fact",
                method="Wind WSS.pb_lf。",
            ),
        ],
        "outputs": [
            _output(
                "当前市值按11.5倍PE隐含归母净利润",
                implied_profit,
                unit="亿元人民币",
                period="正常化年度",
                formula="当前总市值÷诊断市盈率",
                substitution=f"525.42÷11.5＝{implied_profit:.2f}亿元",
                dependency="市场隐含盈利",
                conclusion="低于独立2026年54.9亿元，市场要求的利润低于研究基准。",
            ),
            _output(
                "当前PB隐含可持续ROE",
                valuation["market_implied_roe_pct_from_pb"],
                unit="%",
                period="长期诊断",
                formula="由PB＝(ROE-g)/(CoE-g)反推ROE",
                substitution=(
                    f"市场PB {valuation['market_pb']:.2f}倍对应约"
                    f"{valuation['market_implied_roe_pct_from_pb']:.2f}%"
                ),
                dependency="市场隐含资产回报",
                conclusion="低于独立前瞻ROE 11.83%，市场计入了现金与责任折价。",
            ),
        ],
        "reconciliations": [
            {
                "benchmark_type": "consensus",
                "benchmark_source_ref": _artifact_ref(
                    RECONCILIATION_PATH, "benchmark_median"
                ),
                "metric_name": "net_income",
                "period": "2026",
                "independent_value": base_2026["parent_net_income_100m_cny"],
                "benchmark_value": 52.43,
                "unit": "亿元人民币",
                "decomposition": {
                    "market_implied_at_11_5x": implied_profit,
                },
                "conclusion": "市场隐含利润低于机构中位数和独立模型，折价需要现金与责任风险解释。",
            }
        ],
    }
    implied_observations = [
        _observation(
            metric="net_income",
            value=implied_profit,
            unit="亿元人民币",
            fact_type="implied",
            provider="internal_model",
            raw_feature_name="当前市值按11.5倍PE隐含归母净利润",
            source_snapshot_key="independent_model",
            model_run_key=implied_model["run_key"],
            fiscal_year=2026,
            fiscal_period="FY1",
            period_end="2026-12-31",
            scenario_name="市场隐含",
            currency="CNY",
            formula="当前总市值÷11.5倍市盈率",
            input_refs=[
                _artifact_ref(WIND_SNAPSHOT_PATH, "wind.current.market_cap_cny")
            ],
        ),
        _observation(
            metric="roe",
            value=valuation["market_implied_roe_pct_from_pb"],
            unit="%",
            fact_type="implied",
            provider="internal_model",
            raw_feature_name="当前PB隐含可持续ROE",
            source_snapshot_key="independent_model",
            model_run_key=implied_model["run_key"],
            fiscal_year=2026,
            fiscal_period="FY1",
            period_end="2026-12-31",
            scenario_name="市场隐含",
            currency=None,
            formula="由PB＝(ROE-g)/(CoE-g)反推ROE，CoE=9.5%、g=3%",
            input_refs=[_artifact_ref(INPUT_PATH, "valuation")],
        ),
    ]
    return [core_model, implied_model], implied_observations


def build_export() -> dict[str, Any]:
    portable_artifacts = materialize_run15_portable_artifacts()
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    wind_snapshot = json.loads(
        WIND_SNAPSHOT_PATH.read_text(encoding="utf-8")
    )
    model = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    reconciliation = json.loads(RECONCILIATION_PATH.read_text(encoding="utf-8"))
    financial_model, internal_observations = _financial_model(
        model, reconciliation
    )
    valuation_models, implied_observations = _valuation_models(model)
    observations = _actual_and_market_observations(
        snapshot, wind_snapshot, model
    )
    observations.extend(_consensus_observations(reconciliation))
    observations.extend(internal_observations)
    observations.extend(implied_observations)
    return {
        "export_schema_version": EXPORT_SCHEMA_VERSION,
        "research_run_ref": RESEARCH_RUN_REF,
        "as_of_date": AS_OF_DATE,
        "source_artifacts": [
            {
                "path": str(portable_artifacts[WIND_SNAPSHOT_PATH].relative_to(ROOT)),
                "sha256": _sha256_file(WIND_SNAPSHOT_PATH),
                "role": (
                    "Wind单证券市场、年度财务与FY1—FY3一致预期快照"
                ),
            },
            {
                "path": str(portable_artifacts[SNAPSHOT_PATH].relative_to(ROOT)),
                "sha256": _sha256_file(SNAPSHOT_PATH),
                "role": "Tushare单证券市场与公告期财务快照",
            },
            {
                "path": str(portable_artifacts[INPUT_PATH].relative_to(ROOT)),
                "sha256": _sha256_file(INPUT_PATH),
                "role": "独立模型输入与假设",
            },
            {
                "path": str(portable_artifacts[MODEL_PATH].relative_to(ROOT)),
                "sha256": _sha256_file(MODEL_PATH),
                "role": "冻结独立财务、现金流与估值模型",
            },
            {
                "path": str(
                    portable_artifacts[RECONCILIATION_PATH].relative_to(ROOT)
                ),
                "sha256": _sha256_file(RECONCILIATION_PATH),
                "role": "冻结后外部预测对账",
            },
        ],
        "companies": [
            {
                "research_company_id": COMPANY_ID,
                "security": {
                    "canonical_name": "正泰电器",
                    "ticker": TICKER,
                    "market": "A股",
                    "listing_status": "a_share",
                    "reporting_currency": "CNY",
                    "identity_status": "verified",
                },
                "source_snapshots": _source_snapshots(
                    snapshot, wind_snapshot
                ),
                "model_runs": [financial_model, *valuation_models],
                "observations": observations,
            }
        ],
        "generation_note": (
            "Run15公司页导出：A股同口径非空字段以单证券Wind快照为主，"
            "Tushare只补Wind未覆盖的季度公告明细和股息率；独立模型先冻结，"
            "再与最近两个季度公司研报及Wind一致预期对账。未取得的数据不补造，"
            "详细输入台保持回退到简化模式。"
        ),
    }


def main() -> int:
    payload = build_export()
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(OUTPUT_PATH),
                "company_count": len(payload["companies"]),
                "observation_count": len(payload["companies"][0]["observations"]),
                "model_run_count": len(payload["companies"][0]["model_runs"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
