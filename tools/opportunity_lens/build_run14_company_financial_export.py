from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from tools.financial.constants import ROOT
from tools.financial.opportunity_profile_export import EXPORT_SCHEMA_VERSION


RUN_DIR = (
    ROOT
    / "opportunity_lens"
    / "research_outputs"
    / "20260724_huayou_nickel_cobalt_lithium_run14"
)
SNAPSHOT_PATH = ROOT / "cache" / "run14_huayou" / "financial_snapshot.json"
INPUT_PATH = RUN_DIR / "independent_model_inputs.json"
MODEL_PATH = RUN_DIR / "independent_model_output.json"
RECONCILIATION_PATH = RUN_DIR / "external_reconciliation.json"
OUTPUT_PATH = RUN_DIR / "company_financial_profile_export_v1.json"

RESEARCH_RUN_REF = "opportunity_lens:run14:huayou_nickel_cobalt_lithium:20260724"
AS_OF_DATE = "2026-07-24"
TICKER = "603799.SH"
COMPANY_ID = 631


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
        "value_num": value,
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
    frequency: str | None = None,
    scenario_name: str = "reported",
    currency: str | None = "CNY",
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
        "frequency": frequency or ("annual" if fiscal_year else "snapshot"),
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


def _first_current_row(rows: list[dict[str, Any]], end_date: str) -> dict[str, Any]:
    candidates = [
        row
        for row in rows
        if str(row.get("end_date") or "") == end_date
        and str(row.get("update_flag") or "") == "1"
    ]
    if not candidates:
        candidates = [
            row for row in rows if str(row.get("end_date") or "") == end_date
        ]
    if not candidates:
        raise ValueError(f"Tushare snapshot 缺少报告期 {end_date}")
    return candidates[0]


def _source_snapshots(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    fetched_at = snapshot.get("accessed_at_utc")
    return [
        {
            "key": "wind_snapshot",
            "provider": "wind",
            "source_channel": "structured_api",
            "source_ref": f"{RESEARCH_RUN_REF}:wind:{TICKER}",
            "title": "华友钴业 Wind市场、历史财务与一致预期窄字段快照",
            "publisher": "Wind",
            "as_of_date": AS_OF_DATE,
            "fetched_at": fetched_at,
            "content_hash": _sha256_file(SNAPSHOT_PATH),
            "raw_snapshot_path": str(SNAPSHOT_PATH.relative_to(ROOT)),
            "metadata": {
                "scope": "单证券、窄字段、2021—2025年年度及FY1—FY3；本文件生成时不再调用外部接口。",
                "ticker": TICKER,
            },
        },
        {
            "key": "tushare_snapshot",
            "provider": "tushare",
            "source_channel": "structured_api",
            "source_ref": f"{RESEARCH_RUN_REF}:tushare:{TICKER}",
            "title": "华友钴业 Tushare公告期财务补缺快照",
            "publisher": "Tushare",
            "as_of_date": AS_OF_DATE,
            "fetched_at": fetched_at,
            "content_hash": _sha256_file(SNAPSHOT_PATH),
            "raw_snapshot_path": str(SNAPSHOT_PATH.relative_to(ROOT)),
            "metadata": {
                "scope": "用于2026年一季度、归母权益和公告日期补缺，不覆盖同口径Wind非空值。",
                "ticker": TICKER,
            },
        },
        {
            "key": "independent_model",
            "provider": "internal_model",
            "source_channel": "internal_calculation",
            "source_ref": f"{RESEARCH_RUN_REF}:independent_model:{TICKER}",
            "title": "华友钴业 Run14冻结独立财务与估值模型",
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
            "title": "华友钴业 Run14外部一致预期对账",
            "publisher": "Industry Demo内部研究模型",
            "as_of_date": AS_OF_DATE,
            "fetched_at": None,
            "content_hash": _sha256_file(RECONCILIATION_PATH),
            "raw_snapshot_path": str(RECONCILIATION_PATH.relative_to(ROOT)),
            "metadata": {
                "independent_model_hash": _sha256_file(MODEL_PATH),
                "sequence_control": "先冻结独立模型，再读取Wind一致预期和卖方研究。",
            },
        },
    ]


def _actual_and_market_observations(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    annual_mapping = (
        ("oper_rev", "revenue", "亿元人民币", 1e8, "Wind WSS.oper_rev"),
        (
            "np_belongto_parcomsh",
            "net_income",
            "亿元人民币",
            1e8,
            "Wind WSS.np_belongto_parcomsh",
        ),
        (
            "net_cash_flows_oper_act",
            "operating_cash_flow",
            "亿元人民币",
            1e8,
            "Wind WSS.net_cash_flows_oper_act",
        ),
        (
            "cash_pay_acq_const_fiolta",
            "capex",
            "亿元人民币",
            1e8,
            "Wind WSS.cash_pay_acq_const_fiolta",
        ),
        ("tot_assets", "total_assets", "亿元人民币", 1e8, "Wind WSS.tot_assets"),
        (
            "tot_liab",
            "total_liabilities",
            "亿元人民币",
            1e8,
            "Wind WSS.tot_liab",
        ),
        ("roe", "roe", "%", 1.0, "Wind WSS.roe"),
        ("roa2", "roa", "%", 1.0, "Wind WSS.roa2"),
        (
            "grossprofitmargin",
            "gross_margin",
            "%",
            1.0,
            "Wind WSS.grossprofitmargin",
        ),
        (
            "netprofitmargin",
            "net_margin",
            "%",
            1.0,
            "Wind WSS.netprofitmargin",
        ),
    )
    for year_text, annual in snapshot["wind"]["historical_annual"].items():
        year = int(year_text)
        source = annual["rows"][TICKER]
        input_refs = [
            _artifact_ref(
                SNAPSHOT_PATH,
                f"wind.historical_annual.{year_text}.rows.{TICKER}",
            )
        ]
        for source_field, metric, unit, divisor, raw_feature in annual_mapping:
            value = source.get(source_field)
            if value is None:
                continue
            rows.append(
                _observation(
                    metric=metric,
                    value=float(value) / divisor,
                    unit=unit,
                    fact_type="actual",
                    provider="wind",
                    raw_feature_name=raw_feature,
                    source_snapshot_key="wind_snapshot",
                    fiscal_year=year,
                    fiscal_period="FY",
                    period_end=f"{year}-12-31",
                    announcement_date=None,
                    currency="CNY" if "人民币" in unit else None,
                    input_refs=input_refs,
                )
            )
        ocf = float(source["net_cash_flows_oper_act"]) / 1e8
        capex = float(source["cash_pay_acq_const_fiolta"]) / 1e8
        assets = float(source["tot_assets"]) / 1e8
        liabilities = float(source["tot_liab"]) / 1e8
        rows.extend(
            [
                _observation(
                    metric="free_cash_flow",
                    value=ocf - capex,
                    unit="亿元人民币",
                    fact_type="actual",
                    provider="wind",
                    raw_feature_name="Wind推导：经营现金流-购建长期资产支出",
                    source_snapshot_key="wind_snapshot",
                    fiscal_year=year,
                    fiscal_period="FY",
                    period_end=f"{year}-12-31",
                    currency="CNY",
                    formula="自由现金流＝经营现金流－购建固定资产、无形资产和其他长期资产支付的现金",
                    input_refs=input_refs,
                ),
                _observation(
                    metric="debt_ratio",
                    value=liabilities / assets * 100,
                    unit="%",
                    fact_type="actual",
                    provider="wind",
                    raw_feature_name="Wind推导：总负债/总资产",
                    source_snapshot_key="wind_snapshot",
                    fiscal_year=year,
                    fiscal_period="FY",
                    period_end=f"{year}-12-31",
                    currency=None,
                    formula="资产负债率＝总负债÷总资产",
                    input_refs=input_refs,
                ),
            ]
        )

    balancesheets = snapshot["tushare"]["balancesheet_2021_2026"]
    for year in range(2021, 2026):
        end_date = f"{year}1231"
        row = _first_current_row(balancesheets, end_date)
        equity = row.get("total_hldr_eqy_exc_min_int")
        if equity is None:
            continue
        rows.append(
            _observation(
                metric="book_value",
                value=float(equity) / 1e8,
                unit="亿元人民币",
                fact_type="actual",
                provider="tushare",
                raw_feature_name="Tushare balancesheet.total_hldr_eqy_exc_min_int",
                source_snapshot_key="tushare_snapshot",
                fiscal_year=year,
                fiscal_period="FY",
                period_end=f"{year}-12-31",
                announcement_date=(
                    f"{row['ann_date'][:4]}-{row['ann_date'][4:6]}-{row['ann_date'][6:8]}"
                    if row.get("ann_date")
                    else None
                ),
                currency="CNY",
                input_refs=[
                    _artifact_ref(
                        SNAPSHOT_PATH,
                        f"tushare.balancesheet_2021_2026.end_date={end_date}",
                    )
                ],
            )
        )

    current = snapshot["wind"]["current"]
    market_specs = (
        ("price", "close", "元/股", "Wind WSS.close", "CNY"),
        (
            "market_cap_cny",
            "market_cap_cny",
            "亿元人民币",
            "Wind WSS.mkt_cap_ard/1e8",
            "CNY",
        ),
        ("pe_ttm", "pe_ttm", "倍", "Wind WSS.pe_ttm", None),
        ("pe_forward", "pe_forward", "倍", "Wind WSS.pe_est_ftm", None),
        ("pb", "pb", "倍", "Wind WSS.pb_lf", None),
        ("ps_ttm", "ps_ttm", "倍", "Wind WSS.ps_ttm", None),
        ("ev_ebitda", "ev_ebitda", "倍", "Wind WSS.ev2_to_ebitda", None),
    )
    for field, metric, unit, raw_feature, currency in market_specs:
        value = current.get(field)
        if value is None:
            continue
        rows.append(
            _observation(
                metric=metric,
                value=float(value),
                unit=unit,
                fact_type="market",
                provider="wind",
                raw_feature_name=raw_feature,
                source_snapshot_key="wind_snapshot",
                period_end=current["trade_date"],
                frequency="snapshot",
                currency=currency,
                input_refs=[_artifact_ref(SNAPSHOT_PATH, f"wind.current.{field}")],
            )
        )
    actual_specs = (
        ("roe", "roe", "%", "Wind WSS.roe_ttm", None),
        ("roa", "roa", "%", "Wind WSS.roa2_ttm", None),
        ("eps_ttm", "eps_ttm", "元/股", "Wind WSS.eps_ttm", "CNY"),
        ("bps_mrq", "bps_mrq", "元/股", "Wind WSS.bps_new", "CNY"),
    )
    for field, metric, unit, raw_feature, currency in actual_specs:
        value = current.get(field)
        if value is None:
            continue
        rows.append(
            _observation(
                metric=metric,
                value=float(value),
                unit=unit,
                fact_type="actual",
                provider="wind",
                raw_feature_name=raw_feature,
                source_snapshot_key="wind_snapshot",
                period_end=current["trade_date"],
                frequency="ttm_snapshot",
                currency=currency,
                input_refs=[_artifact_ref(SNAPSHOT_PATH, f"wind.current.{field}")],
            )
        )

    q1_income = _first_current_row(
        snapshot["tushare"]["income_2021_2026"], "20260331"
    )
    q1_indicator = _first_current_row(
        snapshot["tushare"]["fina_indicator_2021_2026"], "20260331"
    )
    q1_cashflow = _first_current_row(
        snapshot["tushare"]["cashflow_2021_2026"], "20260331"
    )
    q1_balance = _first_current_row(
        snapshot["tushare"]["balancesheet_2021_2026"], "20260331"
    )
    q1_specs = (
        (q1_income, "revenue", "revenue", "亿元人民币", 1e8, "Tushare income.revenue"),
        (q1_income, "n_income_attr_p", "net_income", "亿元人民币", 1e8, "Tushare income.n_income_attr_p"),
        (q1_cashflow, "n_cashflow_act", "operating_cash_flow", "亿元人民币", 1e8, "Tushare cashflow.n_cashflow_act"),
        (q1_cashflow, "c_pay_acq_const_fiolta", "capex", "亿元人民币", 1e8, "Tushare cashflow.c_pay_acq_const_fiolta"),
        (q1_balance, "total_assets", "total_assets", "亿元人民币", 1e8, "Tushare balancesheet.total_assets"),
        (q1_balance, "total_hldr_eqy_exc_min_int", "book_value", "亿元人民币", 1e8, "Tushare balancesheet.total_hldr_eqy_exc_min_int"),
        (q1_indicator, "eps", "eps_ytd", "元/股", 1.0, "Tushare fina_indicator.eps"),
        (q1_indicator, "bps", "bps_mrq", "元/股", 1.0, "Tushare fina_indicator.bps"),
        (q1_indicator, "grossprofit_margin", "gross_margin", "%", 1.0, "Tushare fina_indicator.grossprofit_margin"),
        (q1_indicator, "netprofit_margin", "net_margin", "%", 1.0, "Tushare fina_indicator.netprofit_margin"),
        (q1_indicator, "roe", "roe", "%", 1.0, "Tushare fina_indicator.roe"),
        (q1_indicator, "roa", "roa", "%", 1.0, "Tushare fina_indicator.roa"),
    )
    for source_row, field, metric, unit, divisor, raw_feature in q1_specs:
        value = source_row.get(field)
        if value is None:
            continue
        rows.append(
            _observation(
                metric=metric,
                value=float(value) / divisor,
                unit=unit,
                fact_type="actual",
                provider="tushare",
                raw_feature_name=raw_feature,
                source_snapshot_key="tushare_snapshot",
                fiscal_year=2026,
                fiscal_period="Q1",
                period_end="2026-03-31",
                announcement_date="2026-04-17",
                frequency="quarterly_ytd",
                currency="CNY" if ("人民币" in unit or "元/股" in unit) else None,
                input_refs=[
                    _artifact_ref(
                        SNAPSHOT_PATH,
                        f"tushare.{raw_feature}.20260331",
                    )
                ],
            )
        )
    rows.append(
        _observation(
            metric="free_cash_flow",
            value=(
                float(q1_cashflow["n_cashflow_act"])
                - float(q1_cashflow["c_pay_acq_const_fiolta"])
            )
            / 1e8,
            unit="亿元人民币",
            fact_type="actual",
            provider="tushare",
            raw_feature_name="Tushare推导：经营现金流-购建长期资产支出",
            source_snapshot_key="tushare_snapshot",
            fiscal_year=2026,
            fiscal_period="Q1",
            period_end="2026-03-31",
            announcement_date="2026-04-17",
            frequency="quarterly_ytd",
            currency="CNY",
            formula="自由现金流＝经营现金流－购建固定资产、无形资产和其他长期资产支付的现金",
            input_refs=[
                _artifact_ref(
                    SNAPSHOT_PATH,
                    "tushare.cashflow_2021_2026.end_date=20260331",
                )
            ],
        )
    )
    return rows


def _consensus_observations(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    source = snapshot["wind"]["consensus_fy1_fy3"]["rows"][TICKER]
    for horizon, year in enumerate(range(2026, 2029), start=1):
        for metric, field, unit, raw_feature, currency in (
            (
                "revenue",
                f"west_sales_fy{horizon}",
                "亿元人民币",
                f"Wind WSS.west_sales_fy{horizon}",
                "CNY",
            ),
            (
                "net_income",
                f"west_netprofit_fy{horizon}",
                "亿元人民币",
                f"Wind WSS.west_netprofit_fy{horizon}",
                "CNY",
            ),
            (
                "eps",
                f"west_eps_fy{horizon}",
                "元/股",
                f"Wind WSS.west_eps_fy{horizon}",
                "CNY",
            ),
            (
                "roe",
                f"west_avgroe_fy{horizon}",
                "%",
                f"Wind WSS.west_avgroe_fy{horizon}",
                None,
            ),
        ):
            divisor = 1e8 if metric in {"revenue", "net_income"} else 1.0
            rows.append(
                _observation(
                    metric=metric,
                    value=float(source[field]) / divisor,
                    unit=unit,
                    fact_type="consensus",
                    provider="wind",
                    raw_feature_name=raw_feature,
                    source_snapshot_key="wind_snapshot",
                    fiscal_year=year,
                    fiscal_period=f"FY{horizon}",
                    period_end=f"{year}-12-31",
                    frequency="annual",
                    scenario_name="Wind一致预期",
                    currency=currency,
                    input_refs=[
                        _artifact_ref(
                            SNAPSHOT_PATH,
                            f"wind.consensus_fy1_fy3.rows.{TICKER}.{field}",
                        )
                    ],
                )
            )
    return rows


def _financial_model(
    model: dict[str, Any],
    reconciliation: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    run_key = "ol14:603799.SH:independent_financial_bridge:v1"
    base_rows = model["scenarios"]["基准情景"]
    inputs = [
        _input(
            "2025年营业收入",
            value=model["actual_reference"]["2025"]["revenue_100m_cny"],
            unit="亿元人民币",
            period="2025",
            source_ref=_artifact_ref(MODEL_PATH, "actual_reference.2025.revenue_100m_cny"),
            input_type="direct_fact",
            method="公司年报实际值，统一为亿元人民币。",
        ),
        _input(
            "2025年归母净利润",
            value=model["actual_reference"]["2025"]["parent_net_income_100m_cny"],
            unit="亿元人民币",
            period="2025",
            source_ref=_artifact_ref(
                MODEL_PATH,
                "actual_reference.2025.parent_net_income_100m_cny",
            ),
            input_type="direct_fact",
            method="公司年报归母口径。",
        ),
        _input(
            "2025年经营现金流",
            value=model["actual_reference"]["2025"]["operating_cash_flow_100m_cny"],
            unit="亿元人民币",
            period="2025",
            source_ref=_artifact_ref(
                MODEL_PATH,
                "actual_reference.2025.operating_cash_flow_100m_cny",
            ),
            input_type="direct_fact",
            method="公司现金流量表实际值。",
        ),
        _input(
            "2025年归母净资产",
            value=model["actual_reference"]["2025"]["parent_equity_100m_cny"],
            unit="亿元人民币",
            period="2025",
            source_ref=_artifact_ref(
                MODEL_PATH,
                "actual_reference.2025.parent_equity_100m_cny",
            ),
            input_type="direct_fact",
            method="公司资产负债表归母权益口径。",
        ),
        _input(
            "项目与分部建模方法",
            value_text=(
                "以2025年八个经营分部为基数，逐年改变销量、价格、产品结构和毛利率；"
                "Pomalaa从2027年爬坡，未完成或规划项目不进入基准；"
                "合并利润再按归母比例、营运资金和资本开支生成现金流。"
            ),
            unit="文字",
            period="2026—2028",
            source_ref=_artifact_ref(INPUT_PATH, "base_segment_forecast"),
            input_type="expert_assumption",
            method="Run14在外部一致预期对账前冻结的分部财务桥。",
            sensitivity="金属价差、项目爬坡、材料毛利、归母比例、营运资金和资本开支。",
            limitation="项目级良率、酸耗、客户合同价和内部交易抵销公开不足，使用透明情景而非伪精确输入。",
        ),
    ]
    outputs: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    shares_100m = (
        model["valuation"]["market_cap_100m_cny"]
        / model["valuation"]["market_price_cny"]
    )
    opening_equity = model["actual_reference"]["2025"]["parent_equity_100m_cny"]
    ending_equity = opening_equity
    roe_by_year: dict[int, float] = {}
    for row in base_rows:
        year = int(row["year"])
        for field, label, metric, unit, formula in (
            (
                "revenue_100m_cny",
                "营业收入",
                "revenue",
                "亿元人民币",
                "各分部收入汇总",
            ),
            (
                "parent_net_income_100m_cny",
                "归母净利润",
                "net_income",
                "亿元人民币",
                "合并税后利润×归母比例",
            ),
            (
                "operating_cash_flow_100m_cny",
                "经营现金流",
                "operating_cash_flow",
                "亿元人民币",
                "净利润＋非现金项目－营运资金占用",
            ),
            (
                "capex_100m_cny",
                "资本开支",
                "capex",
                "亿元人民币",
                "按项目建设与维持性资本开支汇总",
            ),
            (
                "free_cash_flow_100m_cny",
                "自由现金流",
                "free_cash_flow",
                "亿元人民币",
                "经营现金流－资本开支",
            ),
            (
                "gross_margin_pct",
                "毛利率",
                "gross_margin",
                "%",
                "合并毛利润÷营业收入",
            ),
        ):
            value = float(row[field])
            outputs.append(
                _output(
                    f"{year}年{label}",
                    value,
                    unit=unit,
                    period=str(year),
                    formula=formula,
                    substitution=f"Run14冻结基准＝{value:.2f}{unit}",
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
                    raw_feature_name=f"Run14基准情景.{field}",
                    source_snapshot_key="independent_model",
                    model_run_key=run_key,
                    fiscal_year=year,
                    fiscal_period=f"FY{year - 2025}",
                    period_end=f"{year}-12-31",
                    frequency="annual",
                    scenario_name="Run14独立基准",
                    currency="CNY" if "人民币" in unit else None,
                    formula=formula,
                    input_refs=[_artifact_ref(MODEL_PATH, f"scenarios.基准情景.{year}")],
                )
            )
        profit = float(row["parent_net_income_100m_cny"])
        closing_equity = (
            float(model["valuation"]["estimated_2026_bps_cny"]) * shares_100m
            if year == 2026
            else ending_equity + profit * 0.90
        )
        average_equity = (ending_equity + closing_equity) / 2
        roe = profit / average_equity * 100
        if year == 2026:
            roe = float(model["valuation"]["independent_forward_roe_pct"])
        roe_by_year[year] = roe
        ending_equity = closing_equity
        observations.extend(
            [
                _observation(
                    metric="roe",
                    value=roe,
                    unit="%",
                    fact_type="internal_estimate",
                    provider="internal_model",
                    raw_feature_name="Run14归母权益桥推导ROE",
                    source_snapshot_key="independent_model",
                    model_run_key=run_key,
                    fiscal_year=year,
                    fiscal_period=f"FY{year - 2025}",
                    period_end=f"{year}-12-31",
                    frequency="annual",
                    scenario_name="Run14独立基准",
                    currency=None,
                    formula="预测ROE＝归母净利润÷平均归母净资产；2026年使用冻结模型显式结果",
                    input_refs=[_artifact_ref(MODEL_PATH, "valuation")],
                ),
                _observation(
                    metric="eps",
                    value=profit / shares_100m,
                    unit="元/股",
                    fact_type="internal_estimate",
                    provider="internal_model",
                    raw_feature_name="Run14归母净利润/估值日总股本",
                    source_snapshot_key="independent_model",
                    model_run_key=run_key,
                    fiscal_year=year,
                    fiscal_period=f"FY{year - 2025}",
                    period_end=f"{year}-12-31",
                    frequency="annual",
                    scenario_name="Run14独立基准",
                    currency="CNY",
                    formula="预测EPS＝归母净利润÷估值日总股本",
                    input_refs=[_artifact_ref(MODEL_PATH, "valuation")],
                ),
            ]
        )
    recs = []
    for row in reconciliation["comparison"]:
        recs.append(
            {
                "benchmark_type": "consensus",
                "benchmark_source_ref": _artifact_ref(
                    RECONCILIATION_PATH,
                    f"comparison.{row['year']}.parent_net_income",
                ),
                "metric_name": "net_income",
                "period": str(row["year"]),
                "independent_value": row[
                    "independent_parent_net_income_100m_cny"
                ],
                "benchmark_value": row[
                    "wind_consensus_parent_net_income_100m_cny"
                ],
                "unit": "亿元人民币",
                "decomposition": {
                    "difference_pct": row["profit_difference_pct"],
                    "drivers": [
                        "钴分部毛利不按政策冲击后的峰值外推",
                        "Pomalaa从2027年爬坡而非2026年满产",
                        "正极与前驱体利润率恢复更审慎",
                    ],
                },
                "conclusion": "差异可由项目时点和利润率解释，未发现单位、财年或归母口径错误。",
            }
        )
    return (
        {
            "run_key": run_key,
            "skill_name": "company_financial_modeling",
            "model_name": "Run14华友钴业独立分部财务桥",
            "model_role": "primary",
            "forecast_start": "2026",
            "forecast_end": "2028",
            "valuation_date": "2026-07-23",
            "assumptions": {
                "model_level": "Level 2分部经营模型与三表现金流桥",
                "independent_before_consensus": True,
                "project_timing": "Pomalaa从2027年爬坡；Sorowako与未交割Ewoyaa不进入基准。",
            },
            "limitations": "项目级成本、良率、内部交易和客户合同价公开不足；以分部毛利和透明情景约束，不输出伪精确项目净现值。",
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
    method_by_name = {
        str(row["method"]): row for row in valuation["methods"]
    }
    summary = {
        "conclusion": (
            "当前41.55元接近三种适用方法共同支持区间的下沿；估值有一定安全边际，"
            "但2026年自由现金流仍可能为负，低倍数必须由项目兑现和现金流拐点确认。"
        ),
        "operating_analysis": (
            "2025年公司归母净利润61.10亿元、经营现金流40.12亿元，但资本开支"
            "107.58亿元，自由现金流约-67.46亿元。冻结基准模型预计2026—2028年"
            "归母净利润88.2/105.6/123.4亿元，自由现金流-36.1/26.3/79.5亿元。"
            "利润增长先于现金流改善，说明钴价、镍项目和锂盐爬坡只是第一层，库存应收、"
            "资本开支、项目归母比例和材料毛利才决定股东最终得到多少现金。"
        ),
        "valuation_analysis": (
            "估值日市值786.76亿元、滚动PE 10.70倍、PB 1.59倍，ROE/ROA为"
            "14.56%/6.97%。按独立2026年利润计算约8.9倍PE；PE、PB—ROE和"
            "EV/EBITDA共同支持的市值区间为779—970亿元，对应41.14—51.24元。"
            "当前PB隐含约16.7%的可持续ROE，与独立前瞻ROE 16.3%接近，低估值主要"
            "反映现金流、杠杆、非全资项目和商品周期折价，而不是市场漏算了确定性高回报。"
        ),
        "buy_point_analysis": (
            "40—43元接近多方法区间和历史PB低位，可作为有条件观察区；成立条件是2026年"
            "利润接近88亿元、钴与现有印尼项目稳定、锂产品销量和毛利同步上升，且经营现金流"
            "开始覆盖更多资本开支。46—51元需要2027年自由现金流转正和Pomalaa按计划爬坡，"
            "不能只依赖金属价格上涨。"
        ),
        "sell_point_analysis": (
            "超过51元后若没有项目爬坡、材料毛利修复和ROA上升，估值已超出三种方法的核心"
            "共同区间，应减仓或等待。若跌破40元同时出现项目延期、库存应收快于收入、净债务"
            "上升和连续两个季度自由现金流弱于基准，也不应把低PB机械视为买点。"
        ),
        "difference_causes": [
            "独立归母净利润比Wind一致预期低约6%—12%，主要来自Pomalaa爬坡和材料利润率假设。",
            "市场PB隐含可持续ROE约16.7%，与独立前瞻ROE约16.3%接近，不存在显著的PB—ROE错配。",
            "ROE高于ROA，说明杠杆、非全资项目和资本结构对股东回报有实质影响。",
        ],
        "future_view": (
            "未来一年先看钴配额、现有印尼项目稳定和锂盐连续交付；"
            "2027—2028年重点验证Pomalaa爬坡、材料毛利和自由现金流转正。"
        ),
        "positive_trigger": (
            "Pomalaa按计划爬坡、锂产品销量与毛利同步上升、经营现金流覆盖资本开支，"
            "且ROA上升而不是单靠杠杆维持ROE。"
        ),
        "risk_trigger": (
            "项目延期、材料毛利不修复、库存应收继续快于收入、净债务上升，"
            "并连续两个季度自由现金流弱于基准。"
        ),
    }
    pb_framework = {
        "applicability": "有效交叉验证",
        "cycle_sensitivity": "强周期与项目周期并存，必须使用正常化ROE并同时观察ROA。",
        "asset_intensity": "重资产资源冶炼与材料制造，净资产、资本开支和杠杆具有直接经济意义。",
        "basis": (
            "公司拥有大量矿冶与材料资产，PB—ROE可以检验账面溢价是否由资产回报支撑；"
            "但商品价格、项目爬坡、少数股东和资产重估使其不适合作为唯一方法。"
        ),
        "price_exposure": "钴出口配额、印尼镍矿与HPAL价差、锂项目供需和材料加工价差。",
        "profit_driver": "有效产量×价差、分部毛利、归母比例、营运资金、资本开支和净债务。",
        "tags": [
            {
                "label": "强周期",
                "basis": "镍钴锂价格与库存会改变分部收入、毛利和资产回报。",
            },
            {
                "label": "重资产",
                "basis": "2025年资本开支107.58亿元，项目投产前先增加资产和负债。",
            },
            {
                "label": "非全资项目",
                "basis": "华飞、华越等项目的合并利润不能全部归属上市公司股东。",
            },
            {
                "label": "现金流约束",
                "basis": "2025年经营现金流低于净利润且自由现金流为负。",
            },
        ],
    }
    scenario_workbench = {
        "simple_ready": True,
        "detailed_ready": False,
        "default_mode": "simple",
        "reason": (
            "现有数据足以用期初归母净资产、FY1—FY3归母净利润和目标PB做简化权益桥；"
            "项目级产量、成本、净债务与少数股东现金流不足以支持详细模式。"
        ),
        "simple": {
            "opening_book_value_cny_100m": model["actual_reference"]["2025"][
                "parent_equity_100m_cny"
            ],
            "current_pb": 1.5897333622,
            "target_pb": 1.5897333622,
            "years": [
                {
                    "fiscal_year": int(row["year"]),
                    "net_income_cny_100m": float(
                        row["parent_net_income_100m_cny"]
                    ),
                    "payout_ratio_pct": 0.0 if row["year"] == 2026 else 10.0,
                }
                for row in model["scenarios"]["基准情景"]
            ],
            "pb_presets": {
                "historical_q20": 1.56508612636,
                "historical_median": 2.819051981,
                "historical_q80": 6.61318979262,
                "current": 1.5897333622,
            },
        },
        "detailed": {
            "available_fields": [
                "分部收入和毛利率",
                "归母净利润",
                "经营现金流",
                "资本开支",
                "总资产与总负债",
            ],
            "missing_required_fields": [
                "逐项目有效产量和现金成本",
                "FY1—FY3净债务桥",
                "逐项目少数股东现金流",
                "客户级材料价格与营运资金",
            ],
        },
    }
    core_inputs = [
        _input(
            "2026年归母净利润",
            value=88.2,
            unit="亿元人民币",
            period="2026",
            source_ref=_artifact_ref(MODEL_PATH, "scenarios.基准情景.2026"),
            input_type="derived_fact",
            method="Run14冻结分部财务模型。",
            sensitivity="钴价差、项目爬坡、材料利润率和归母比例。",
        ),
        _input(
            "2026年末估计归母净资产",
            value=577.0,
            unit="亿元人民币",
            period="2026",
            source_ref=_artifact_ref(
                INPUT_PATH,
                "valuation_assumptions.estimated_2026_ending_parent_equity_100m_cny",
            ),
            input_type="expert_assumption",
            method="2025年归母权益与2026年利润、留存及其他权益变动的简化桥。",
            limitation="缺少完整未来资产负债表，PB—ROE只作交叉验证。",
        ),
        _input(
            "2026年EBITDA",
            value=188.0,
            unit="亿元人民币",
            period="2026",
            source_ref=_artifact_ref(
                INPUT_PATH,
                "valuation_assumptions.estimated_2026_ebitda_100m_cny",
            ),
            input_type="expert_assumption",
            method="分部利润、折旧摊销和资本开支路径推导。",
            sensitivity="对商品价差、折旧和项目爬坡敏感。",
        ),
        _input(
            "估计净债务与少数股东权益",
            value_text="净债务430亿元，少数股东权益估值110亿元",
            unit="亿元人民币",
            period="2026",
            source_ref=_artifact_ref(INPUT_PATH, "valuation_assumptions"),
            input_type="expert_assumption",
            method="用于EV到股权价值的资本结构桥。",
            limitation="少数股东公允价值和未来净债务缺少完整逐年桥。",
        ),
    ]
    core_outputs: list[dict[str, Any]] = []
    for method_name in ("市盈率", "PB—ROE", "EV/EBITDA"):
        row = method_by_name[method_name]
        core_outputs.extend(
            [
                _output(
                    f"{method_name}权益价值下沿",
                    row["equity_value_low_100m_cny"],
                    unit="亿元人民币",
                    period="2026估值",
                    formula=row["assumption"],
                    substitution=f"{row['equity_value_low_100m_cny']:.1f}亿元",
                    dependency=method_name,
                    conclusion=f"{method_name}的条件区间下沿，不是无条件目标价。",
                ),
                _output(
                    f"{method_name}权益价值上沿",
                    row["equity_value_high_100m_cny"],
                    unit="亿元人民币",
                    period="2026估值",
                    formula=row["assumption"],
                    substitution=f"{row['equity_value_high_100m_cny']:.1f}亿元",
                    dependency=method_name,
                    conclusion=f"{method_name}的条件区间上沿，需要对应经营假设兑现。",
                ),
            ]
        )
    core_outputs.extend(
        [
            _output(
                "目标市值核心区间下沿",
                valuation["core_value_range_100m_cny"][0],
                unit="亿元人民币",
                period="截至2026-07-23",
                formula="三种适用方法共同支持区域的下沿",
                substitution="779.0亿元",
                dependency="多方法共同支持区域",
                conclusion="接近当前市值，仅在基准利润和现金流路径成立时有效。",
            ),
            _output(
                "目标市值核心区间上沿",
                valuation["core_value_range_100m_cny"][1],
                unit="亿元人民币",
                period="截至2026-07-23",
                formula="三种适用方法共同支持区域的上沿",
                substitution="970.2亿元",
                dependency="多方法共同支持区域",
                conclusion="需要项目爬坡、材料毛利和资产回报共同兑现。",
            ),
        ]
    )
    core_model = {
        "run_key": "ol14:603799.SH:multi_method_valuation:v2",
        "supersedes_run_keys": [
            "ol14:603799.SH:multi_method_valuation:v1",
        ],
        "skill_name": "company_valuation_modeling",
        "model_name": "Run14 PE、PB—ROE与EV/EBITDA综合估值",
        "model_role": "core",
        "forecast_start": "2026",
        "forecast_end": "2028",
        "valuation_date": "2026-07-23",
        "assumptions": {
            "method_roles": {
                "PE": "核心方法",
                "PB—ROE": "有效交叉验证",
                "EV/EBITDA": "资本结构校验",
            },
            "aggregation_policy": "只取共同支持区域，不对高度相关方法机械平均。",
            "pb_framework": pb_framework,
            "scenario_workbench": scenario_workbench,
            "company_detail_summary": summary,
        },
        "limitations": "商品周期、项目爬坡、净债务和少数股东均会改变估值；核心区间是条件价值，不是无条件目标价。",
        "finalization": "independent",
        "inputs": core_inputs,
        "outputs": core_outputs,
        "reconciliations": [
            {
                "benchmark_type": "market_implied",
                "benchmark_source_ref": _artifact_ref(
                    RECONCILIATION_PATH,
                    "market_snapshot.market_cap_100m_cny",
                ),
                "metric_name": "equity_value",
                "period": "2026-07-23",
                "independent_value": valuation["core_value_range_100m_cny"][0],
                "benchmark_value": valuation["market_cap_100m_cny"],
                "unit": "亿元人民币",
                "decomposition": {
                    "core_high": valuation["core_value_range_100m_cny"][1],
                    "market_price_cny": valuation["market_price_cny"],
                },
                "conclusion": "当前市值接近多方法核心区间下沿，仍需基准盈利和现金流兑现。",
            }
        ],
    }
    implied_profit_8x = valuation["market_cap_100m_cny"] / 8.0
    implied_model = {
        "run_key": "ol14:603799.SH:market_implied_expectations:v1",
        "skill_name": "company_valuation_modeling",
        "model_name": "Run14当前市场隐含盈利与资产回报",
        "model_role": "diagnostic",
        "forecast_start": "2026",
        "forecast_end": "2026",
        "valuation_date": "2026-07-23",
        "assumptions": {
            "purpose": "解释当前价格要求的利润与ROE，不预测公司必然实现。",
            "terminal_pe": 8.0,
            "market_pb": 1.5897333622,
        },
        "limitations": "隐含结果随选定正常化PE、长期增长和股权回报要求变化，只用于诊断市场已经定价的条件。",
        "finalization": "independent",
        "inputs": [
            _input(
                "当前总市值",
                value=valuation["market_cap_100m_cny"],
                unit="亿元人民币",
                period="2026-07-23",
                source_ref=_artifact_ref(
                    RECONCILIATION_PATH,
                    "market_snapshot.market_cap_100m_cny",
                ),
                input_type="direct_fact",
                method="Wind估值日总市值。",
            ),
            _input(
                "诊断市盈率",
                value=8.0,
                unit="倍",
                period="正常化",
                source_ref=_artifact_ref(INPUT_PATH, "valuation_assumptions.pe_range"),
                input_type="expert_assumption",
                method="使用PE方法区间下沿反推市场需要的盈利。",
                sensitivity="若使用更高倍数，隐含利润会下降。",
            ),
            _input(
                "当前市净率",
                value=1.5897333622,
                unit="倍",
                period="2026-07-23",
                source_ref=_artifact_ref(SNAPSHOT_PATH, "wind.current.pb"),
                input_type="direct_fact",
                method="Wind WSS.pb_lf。",
            ),
        ],
        "outputs": [
            _output(
                "隐含归母净利润（8倍市盈率）",
                implied_profit_8x,
                unit="亿元人民币",
                period="正常化年度",
                formula="当前总市值÷诊断市盈率",
                substitution=f"786.76÷8＝{implied_profit_8x:.2f}亿元",
                dependency="市场隐含盈利",
                conclusion="高于独立2026年88.2亿元、低于独立2027年105.6亿元，市场要求盈利继续增长。",
            ),
            _output(
                "当前PB隐含可持续ROE",
                valuation["market_implied_roe_pct_from_pb"],
                unit="%",
                period="长期诊断",
                formula="由PB＝(ROE-g)/(CoE-g)反推ROE",
                substitution=f"市场PB 1.59倍对应约{valuation['market_implied_roe_pct_from_pb']:.2f}%",
                dependency="市场隐含资产回报",
                conclusion="与独立前瞻ROE约16.3%接近，PB—ROE层面分歧有限。",
            ),
        ],
        "reconciliations": [
            {
                "benchmark_type": "consensus",
                "benchmark_source_ref": _artifact_ref(
                    RECONCILIATION_PATH,
                    "comparison.2026.parent_net_income",
                ),
                "metric_name": "net_income",
                "period": "2026",
                "independent_value": 88.2,
                "benchmark_value": 93.9,
                "unit": "亿元人民币",
                "decomposition": {
                    "market_implied_at_8x": implied_profit_8x,
                },
                "conclusion": "市场隐含正常化利润位于独立2026与2027路径之间。",
            }
        ],
    }
    implied_observations = [
        _observation(
            metric="net_income",
            value=implied_profit_8x,
            unit="亿元人民币",
            fact_type="implied",
            provider="internal_model",
            raw_feature_name="当前市值按8倍正常化PE隐含归母净利润",
            source_snapshot_key="independent_model",
            model_run_key=implied_model["run_key"],
            fiscal_year=2026,
            fiscal_period="FY1",
            period_end="2026-12-31",
            frequency="annual",
            scenario_name="市场隐含",
            currency="CNY",
            formula="隐含归母净利润＝当前总市值÷8倍正常化市盈率",
            input_refs=[_artifact_ref(RECONCILIATION_PATH, "market_snapshot")],
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
            frequency="annual",
            scenario_name="市场隐含",
            currency=None,
            formula="由PB＝(ROE-g)/(CoE-g)反推ROE，CoE=12%、g=4%",
            input_refs=[_artifact_ref(INPUT_PATH, "valuation_assumptions")],
        ),
    ]
    return [core_model, implied_model], implied_observations


def build_export() -> dict[str, Any]:
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    model = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    reconciliation = json.loads(RECONCILIATION_PATH.read_text(encoding="utf-8"))
    financial_model, internal_observations = _financial_model(
        model, reconciliation
    )
    valuation_models, implied_observations = _valuation_models(model)
    observations = _actual_and_market_observations(snapshot)
    observations.extend(_consensus_observations(snapshot))
    observations.extend(internal_observations)
    observations.extend(implied_observations)
    return {
        "export_schema_version": EXPORT_SCHEMA_VERSION,
        "research_run_ref": RESEARCH_RUN_REF,
        "as_of_date": AS_OF_DATE,
        "source_artifacts": [
            {
                "path": str(SNAPSHOT_PATH.relative_to(ROOT)),
                "sha256": _sha256_file(SNAPSHOT_PATH),
                "role": "Wind与Tushare结构化财务、市场和一致预期窄字段快照",
            },
            {
                "path": str(INPUT_PATH.relative_to(ROOT)),
                "sha256": _sha256_file(INPUT_PATH),
                "role": "独立模型输入与假设",
            },
            {
                "path": str(MODEL_PATH.relative_to(ROOT)),
                "sha256": _sha256_file(MODEL_PATH),
                "role": "冻结独立财务、现金流与估值模型",
            },
            {
                "path": str(RECONCILIATION_PATH.relative_to(ROOT)),
                "sha256": _sha256_file(RECONCILIATION_PATH),
                "role": "冻结后外部一致预期与卖方预测对账",
            },
        ],
        "companies": [
            {
                "research_company_id": COMPANY_ID,
                "security": {
                    "canonical_name": "华友钴业",
                    "ticker": TICKER,
                    "market": "A股",
                    "listing_status": "a_share",
                    "reporting_currency": "CNY",
                    "identity_status": "verified",
                },
                "source_snapshots": _source_snapshots(snapshot),
                "model_runs": [financial_model, *valuation_models],
                "observations": observations,
            }
        ],
        "generation_note": (
            "Run14公司页导出：Wind为A股主源，Tushare只补2026Q1、归母权益和公告日期；"
            "独立模型先冻结再与一致预期对账。PB历史分位使用financial.db中已完成的单证券月末窄字段刷新，"
            "本次导出不发起新的外部数据请求。"
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
