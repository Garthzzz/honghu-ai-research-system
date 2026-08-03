from __future__ import annotations

"""Build the validated financial.db export for the copper research companies.

The script performs no network calls.  It compiles the already frozen
independent model, Wind/yfinance snapshot and post-freeze external
reconciliation into ``company_financial_profile_export.v1``.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from tools.financial.accounting_sanity import normalize_nonmeaningful_annual_roe


ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_PATH = ROOT / "cache/copper_research/copper_financial_snapshot.json"
MODEL_PATH = ROOT / "cache/copper_research/models/copper_independent_models_v2.json"
RECON_PATH = ROOT / "cache/copper_research/models/copper_external_reconciliation_v2.json"
DEFAULT_OUTPUT = ROOT / "cache/copper_research/copper_financial_profile_export.json"
AS_OF_DATE = "2026-07-26"

A_IDENTITIES = {
    "紫金矿业": {
        "research_company_id": 635,
        "ticker": "601899.SH",
        "market": "A股",
        "listing_status": "a_share",
    },
    "洛阳钼业": {
        "research_company_id": 634,
        "ticker": "603993.SH",
        "market": "A股",
        "listing_status": "a_share",
    },
}
MMG_IDENTITY = {
    "research_company_id": 636,
    "ticker": "1208.HK",
    "market": "港股",
    "listing_status": "hk",
}

ANNOUNCEMENT_DATES = {
    "601899.SH": {
        2021: "2022-03-19",
        2022: "2023-03-25",
        2023: "2024-03-23",
        2024: "2025-03-22",
        2025: "2026-03-21",
    },
    "603993.SH": {
        2021: "2022-03-19",
        2022: "2023-03-18",
        2023: "2024-03-23",
        2024: "2025-03-22",
        2025: "2026-03-28",
    },
}

CURRENT_RAW = {
    "price": ("close", "元/股", "CNY", "close"),
    "pe_ttm": ("pe_ttm", "倍", None, "pe_ttm"),
    "pe_forward": ("pe_forward", "倍", None, "pe_est_ftm"),
    "pb": ("pb", "倍", None, "pb_lf"),
    "ps_ttm": ("ps_ttm", "倍", None, "ps_ttm"),
    "ev_ebitda": ("ev_ebitda", "倍", None, "ev2_to_ebitda"),
    "roe": ("roe", "%", None, "roe_ttm"),
    "roa": ("roa", "%", None, "roa2_ttm"),
    "eps_ttm": ("eps_ttm", "元/股", "CNY", "eps_ttm"),
    "bps_mrq": ("bps_mrq", "元/股", "CNY", "bps_new"),
    "market_cap_cny": (
        "market_cap_cny",
        "亿元人民币",
        "CNY",
        "mkt_cap_ard",
    ),
}

ANNUAL_RAW = {
    "oper_rev": ("revenue", "亿元人民币", "CNY", 1e8),
    "np_belongto_parcomsh": (
        "net_income",
        "亿元人民币",
        "CNY",
        1e8,
    ),
    "net_cash_flows_oper_act": (
        "operating_cash_flow",
        "亿元人民币",
        "CNY",
        1e8,
    ),
    "cash_pay_acq_const_fiolta": ("capex", "亿元人民币", "CNY", 1e8),
    "tot_assets": ("total_assets", "亿元人民币", "CNY", 1e8),
    "tot_equity": ("total_equity", "亿元人民币", "CNY", 1e8),
    "tot_liab": ("total_liabilities", "亿元人民币", "CNY", 1e8),
    "roe": ("roe", "%", None, 1.0),
    "roa2": ("roa", "%", None, 1.0),
    "grossprofitmargin": ("gross_margin", "%", None, 1.0),
    "netprofitmargin": ("net_margin", "%", None, 1.0),
}


def _file_hash(path: Path) -> str:
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


def _relative(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def _snapshot(
    *,
    key: str,
    provider: str,
    source_ref: str,
    title: str,
    as_of_date: str,
    content_hash: str,
    raw_snapshot_path: str,
    metadata: dict[str, Any],
    publisher: str,
    source_channel: str = "structured_api",
) -> dict[str, Any]:
    return {
        "key": key,
        "provider": provider,
        "source_channel": source_channel,
        "source_ref": source_ref,
        "title": title,
        "publisher": publisher,
        "as_of_date": as_of_date,
        "content_hash": content_hash,
        "raw_snapshot_path": raw_snapshot_path,
        "metadata": {
            "database_boundary": "financial.db only",
            **metadata,
        },
    }


def _model_company(models: dict[str, Any], name: str) -> dict[str, Any]:
    for company in models["outputs"]["companies"]:
        if company["company"] == name:
            return company
    raise KeyError(name)


def _input(
    name: str,
    value: float | None,
    unit: str,
    period: str,
    source_ref: str,
    input_type: str,
    method: str,
    *,
    value_text: str | None = None,
    low: float | None = None,
    high: float | None = None,
    limitation: str | None = None,
) -> dict[str, Any]:
    return {
        "input_name": name,
        "value_num": value,
        "value_text": value_text,
        "range_low": low,
        "range_high": high,
        "unit": unit,
        "period_or_as_of_date": period,
        "source_ref": source_ref,
        "input_type": input_type,
        "formula_or_method": method,
        "limitation_note": limitation,
    }


def _output(
    name: str,
    *,
    value: float | None,
    low: float | None,
    high: float | None,
    unit: str,
    period: str,
    formula: str,
    substitution: str,
    conclusion: str,
    dependency: str,
) -> dict[str, Any]:
    return {
        "output_name": name,
        "value_num": value,
        "range_low": low,
        "range_high": high,
        "unit": unit,
        "period_or_as_of_date": period,
        "formula": formula,
        "substitution": substitution,
        "dependency_group": dependency,
        "conclusion": conclusion,
    }


def _company_summary(name: str) -> dict[str, Any]:
    if name == "紫金矿业":
        return {
            "conclusion": (
                "正常化PE下限较当前市值高约4.75%，DCF下限较当前市值低约1.41%，"
                "并已位于PB—ROE区间；存在有限余量，不再判断为三种方法全面低估。"
            ),
            "difference_causes": [
                "独立模型使用项目权益量和正常化铜价，Wind一致预期对远期利润更乐观。",
                "金与锂的利润缓冲提高组合质量，但多项目资本开支会延迟现金回收。",
                "把非铜及公司层残余按10—13倍估值后，当前价格隐含铜资源业务约970—2,680亿元；区间较宽，说明紫金的结论不能只靠单一铜业务SOTP。",
            ],
            "operating_analysis": (
                "2025年经营现金流754.30亿元明显覆盖309.82亿元资本开支。"
                "2026—2028增长由多个项目共同提供，单一项目事故不会完全破坏组合，"
                "但Kamoa恢复和多项目同时建设仍会改变短期自由现金流。"
            ),
            "valuation_analysis": (
                "当前约13.58倍滚动PE、4.48倍PB对应约30.78%滚动ROE。"
                "PB看似高，但资产回报也高；估值风险在于把周期高ROE永久化，"
                "因此使用22%—28%可持续ROE推导2.53—3.33倍前瞻PB。以11,500美元/吨铜价、"
                "约99.19万吨权益铜和307.80亿元权益铜税后利润代理测算，当前市场"
                "隐含资源业务PE约3.15—8.71倍、单位权益产量市值约9.78—27.02万元/吨；"
                "该结果高度依赖非铜残余倍数，只作市场定价诊断。"
            ),
            "buy_point_analysis": (
                "更好的买点是价格进入五年PB/PE中低分位，同时Kamoa与巨龙季度产量"
                "不再下修、经营现金流继续覆盖资本开支；只满足价格便宜而项目下修不构成买点。"
            ),
            "sell_point_analysis": (
                "若铜价显著低于11,000美元/吨、Kamoa恢复再次延后，或资本开支持续增加"
                "而自由现金流没有同步改善，应下调利润和估值；高估值分位且项目不及预期时减仓。"
            ),
            "future_view": "未来两年仍有产量与非铜利润增量，但收益率取决于兑现速度而非单纯铜价。",
            "positive_trigger": "Kamoa恢复、巨龙和塞尔维亚爬坡、金锂利润兑现、资本开支见顶。",
            "risk_trigger": "铜价均值回落、项目延期、海外税费上升或扩张现金流长期转负。",
        }
    if name == "洛阳钼业":
        return {
            "conclusion": (
                "当前市值位于正常化PE区间上部，但已高于PB—ROE和DCF上限；"
                "基准利润与近期卖方预测接近，当前估值需要高利润、现金与KFM二期共同兑现。"
            ),
            "difference_causes": [
                "Wind一致预期对KFM二期和铜钴价格的远期贡献略高于独立模型。",
                "IXM放大营业收入但利润率低，不能用总营收增速直接解释矿山估值。",
                "按8—11倍估值非铜及公司层残余后，当前价格隐含铜资源业务约2,362—2,829亿元。",
            ],
            "operating_analysis": (
                "TFM/KFM在2025年形成高盈利铜钴基座，2026Q1利润强劲。"
                "下一阶段要验证高价能否转成经营现金，以及电力、硫酸、税费与营运资金"
                "是否吞噬账面利润。"
            ),
            "valuation_analysis": (
                "当前约16.87倍滚动PE、4.92倍PB对应约27.09%滚动ROE。"
                "高PB部分由高ROE支持，但刚果（金）集中风险使估值不应按稳定消费股资本化。"
                "在11,500美元/吨铜价和约67.64万吨组合权益铜近似下，资源业务隐含PE"
                "约11.63—13.93倍、单位权益产量市值约34.92—41.82万元/吨；"
                "TFM/KFM公开权益与成本拆分不足，使这一结果只能作为组合近似。"
            ),
            "buy_point_analysis": (
                "价格回到历史估值中低分位，且TFM/KFM季度成本、经营现金流和KFM二期"
                "三项同时确认时，风险收益改善。"
            ),
            "sell_point_analysis": (
                "若国家税费、出口或现金汇回限制上升，或铜钴产量成本连续低于指引，"
                "即使铜价高位也应下调目标倍数。"
            ),
            "future_view": "KFM二期提供2027年后增量，短期更应关注现金流质量和国家风险。",
            "positive_trigger": "产量位于指引上沿、单位成本下降、经营现金流跟上利润、政策稳定。",
            "risk_trigger": "刚果（金）政策或电力硫酸恶化、贸易营运资金占用、铜钴价格回落。",
        }
    return {
        "conclusion": (
            "当前市值高于正常化PE、PB—ROE和股权现金流三个独立结果；"
            "市场已经要求Khoemacau扩建、Las Bambas低成本和高铜价同时兑现。"
        ),
        "difference_causes": [
            "独立模型按项目权益和少数股东约束归母利润，低于JPMorgan预测约33%—43%。",
            "当前估值提前反映Khoemacau扩建与铜价高位，对延期的容错率较低。",
            "五矿资源的权益铜利润代理高于集团归母利润，不能机械拆出正的其他业务价值。",
        ],
        "operating_analysis": (
            "Las Bambas是现金流基座，Kinsevere成本仍高，Khoemacau决定远期增量。"
            "2025年经营现金流26.90亿美元覆盖10.80亿美元资本开支，"
            "但债务与少数股东使企业现金不等于母公司自由现金。"
        ),
        "valuation_analysis": (
            "当前约25.15倍滚动PE、3.25倍PB对应约14.50%ROE，"
            "价格已显著高于1.25—1.65倍前瞻PB研究区间；高估值需要增长兑现而非历史资产回报。"
            "以11,500美元/吨铜价和约35.78万吨权益铜计算，当前折算市值对应"
            "2027年集团隐含PE约14.61倍、单位权益产量市值约27.32万元/吨。"
            "由于公司层残余为负，这里保留集团口径，不虚构资源业务SOTP。"
        ),
        "buy_point_analysis": (
            "只有价格回到独立价值区间，同时Khoemacau按期、Las Bambas成本优于指引"
            "并且净债务下降，才形成更完整买点。"
        ),
        "sell_point_analysis": (
            "Khoemacau延期、Las Bambas成本回升、秘鲁社区物流中断或铜价均值下移，"
            "任一项发生都会削弱当前估值支撑。"
        ),
        "future_view": "增长选择权真实存在，但当前价格对项目失误的容忍度有限。",
        "positive_trigger": "Khoemacau按期和低成本、Las Bambas稳定、净债务下降、铜价高于基准。",
        "risk_trigger": "扩建延期、成本超支、少数股东现金分配上升或铜价回落。",
    }


def _pb_framework(name: str) -> dict[str, Any]:
    if name == "紫金矿业":
        return {
            "applicability": "有效参考，与正常化PE和现金流交叉使用",
            "cycle_sensitivity": "强周期；当期高ROE必须向可持续水平回归",
            "asset_intensity": "重资产、多项目建设、矿权与资源寿命重要",
            "basis": "2025实际ROE、2026当前PB/ROE和2027前瞻归母权益均可核验。",
            "price_exposure": "铜、金、锂价格与海外项目产量",
            "profit_driver": "权益产量、现金成本、伴生金属、资本开支与项目权益",
            "tags": ["重资产", "资源周期", "多金属组合", "全球项目"],
        }
    if name == "洛阳钼业":
        return {
            "applicability": "有效参考，但国家与贸易结构需折价",
            "cycle_sensitivity": "铜钴高景气显著抬升ROE",
            "asset_intensity": "重资产矿山加低利润率贸易平台",
            "basis": "TFM/KFM高回报可见，前瞻权益和ROE可建模。",
            "price_exposure": "铜、钴、钼钨铌磷价格及刚果（金）政策",
            "profit_driver": "TFM/KFM权益产量、成本、税费和IXM营运资金",
            "tags": ["重资产", "铜钴共生", "国家集中", "贸易平台"],
        }
    return {
        "applicability": "诊断参考，少数股东和债务降低解释力",
        "cycle_sensitivity": "高铜价与项目爬坡共同影响ROE",
        "asset_intensity": "重资产、扩建期、母公司权益低于总权益",
        "basis": "2025母公司权益和项目现金流可用，但长期ROE受少数股东影响。",
        "price_exposure": "铜价、Las Bambas成本、Khoemacau进度",
        "profit_driver": "项目权益现金毛利、资本开支、净债务与少数股东",
        "tags": ["重资产", "项目弹性", "少数股东", "高杠杆敏感"],
    }


def _financial_model(
    company: dict[str, Any],
    *,
    model_file_ref: str,
    market_ref: str,
    unit: str,
    scale: float,
    seller: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    name = company["company"]
    ticker = company["ticker"]
    actual = company["actual_2025"]
    base_rows = company["scenarios"]["基准情景"]
    actual_ni_key = (
        "attributable_net_income_rmb_bn"
        if company["currency"] == "CNY"
        else "attributable_net_income_usd_bn"
    )
    inputs = [
        _input(
            "2025归母净利润",
            float(actual[actual_ni_key]) * scale,
            unit,
            "2025",
            model_file_ref,
            "direct_fact",
            "公司年报归母口径",
        ),
        _input(
            "2026—2028铜价路径",
            None,
            "美元/吨",
            "2026—2028",
            model_file_ref,
            "expert_assumption",
            "12,500/11,500/11,000美元/吨",
            value_text="2026年12,500；2027年11,500；2028年11,000",
            limitation="价格是研究情景，不是外部事实。",
        ),
        _input(
            "权益产量与现金成本",
            None,
            "项目明细",
            "2026—2028",
            model_file_ref,
            "derived_fact",
            company["model_method"],
            value_text="按项目权益、产量指引和现金成本逐年桥接",
        ),
    ]
    outputs: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    metric_fields = {
        "revenue": "revenue_rmb_bn" if company["currency"] == "CNY" else "revenue_usd_bn",
        "net_income": (
            "attributable_net_income_rmb_bn"
            if company["currency"] == "CNY"
            else "attributable_net_income_usd_bn"
        ),
        "free_cash_flow": "fcfe_rmb_bn" if company["currency"] == "CNY" else "fcfe_usd_bn",
        "capex": "capex_rmb_bn" if company["currency"] == "CNY" else "capex_usd_bn",
        "roe": "roe",
        "roa": "roa",
    }
    for index, row in enumerate(base_rows, 1):
        year = int(row["year"])
        for metric, raw in metric_fields.items():
            value = float(row[raw])
            metric_unit = unit
            if metric in {"roe", "roa"}:
                value *= 100.0
                metric_unit = "%"
            outputs.append(
                _output(
                    f"FY{index}{metric}",
                    value=value * (scale if metric not in {"roe", "roa"} else 1.0),
                    low=None,
                    high=None,
                    unit=metric_unit,
                    period=str(year),
                    formula=company["model_method"],
                    substitution=f"{metric}={value:.4f}×{scale if metric not in {'roe','roa'} else 1}",
                    conclusion=f"{year}年基准情景{metric}。",
                    dependency="铜价—权益产量—成本—归母现金流",
                )
            )
            observations.append(
                {
                    "metric_name": metric,
                    "value_num": value * (scale if metric not in {"roe", "roa"} else 1.0),
                    "unit": metric_unit,
                    "currency": "CNY" if company["currency"] == "CNY" and metric_unit != "%" else (
                        "USD" if company["currency"] == "USD" and metric_unit != "%" else None
                    ),
                    "period_start": f"{year}-01-01",
                    "period_end": f"{year}-12-31",
                    "fiscal_year": year,
                    "fiscal_period": f"FY{index}",
                    "frequency": "annual",
                    "fact_type": "internal_estimate",
                    "as_of_date": AS_OF_DATE,
                    "provider": "internal_model",
                    "raw_feature_name": f"copper.independent_model.{raw}",
                    "formula": company["model_method"],
                    "input_refs": [model_file_ref],
                    "quality_status": "usable",
                    "scenario_name": "base",
                    "model_run_key": f"copper_b_20260726:{ticker}:financial_bridge:v2",
                }
            )
    reconciliations = []
    wind = seller.get("wind_consensus") or {}
    wind_net = wind.get("net_income_bn") or {}
    for index, row in enumerate(base_rows, 1):
        year = str(row["year"])
        benchmark = _finite(wind_net.get(year))
        if benchmark is None:
            benchmark = _finite((seller.get("seller_median") or {}).get("net_income_bn", {}).get(year))
        if benchmark is None:
            continue
        independent = float(row[metric_fields["net_income"]])
        reconciliations.append(
            {
                "benchmark_type": "consensus",
                "benchmark_source_ref": market_ref,
                "metric_name": "net_income",
                "period": f"FY{index}",
                "independent_value": independent * scale,
                "benchmark_value": benchmark * scale,
                "unit": unit,
                "decomposition": {
                    "company": name,
                    "independent_model_currency": company["currency"],
                },
                "conclusion": (
                    f"独立模型与市场预测的差异来自铜价、权益产量、成本、"
                    f"非铜业务和少数股东口径。"
                ),
            }
        )
    model = {
        "run_key": f"copper_b_20260726:{ticker}:financial_bridge:v2",
        "supersedes_run_keys": [
            f"copper_b_20260726:{ticker}:financial_bridge:v1"
        ],
        "skill_name": "company_financial_modeling",
        "model_name": "权益产量—铜价—成本—归母现金流桥",
        "model_role": "core",
        "forecast_start": "2026-01-01",
        "forecast_end": "2028-12-31",
        "valuation_date": "2026-07-24",
        "assumptions": {
            "model_method": company["model_method"],
            "scenario_policy": "基准情景是研究估算，不是发生概率。",
            "actual_2025": actual,
        },
        "limitations": "；".join(company.get("limitations") or []),
        "inputs": inputs,
        "outputs": outputs,
        "finalization": "independent",
        "reconciliations": reconciliations,
    }
    return model, observations


def _valuation_models(
    company: dict[str, Any],
    *,
    model_file_ref: str,
    unit: str,
    scale: float,
) -> list[dict[str, Any]]:
    name = company["company"]
    ticker = company["ticker"]
    valuation = company["valuation"]
    pe = valuation["normalized_pe"]
    pb = valuation["pb_roe"]
    dcf = valuation["fcfe_dcf"]
    pe_low_key = next(key for key in pe if key.startswith("equity_value_low"))
    pe_high_key = next(key for key in pe if key.startswith("equity_value_high"))
    pb_low_key = next(key for key in pb if key.startswith("equity_value_low"))
    pb_high_key = next(key for key in pb if key.startswith("equity_value_high"))
    equity_key = next(key for key in pb if key.startswith("forward_parent_equity"))
    normalized_key = next(key for key in valuation if key.startswith("normalized_net_income"))
    summary = _company_summary(name)
    common_assumptions = {
        "company_detail_summary": summary,
        "pb_framework": _pb_framework(name),
    }
    pe_model = {
        "run_key": f"copper_b_20260726:{ticker}:normalized_pe:v5",
        "supersedes_run_keys": [
            f"copper_b_20260726:{ticker}:normalized_pe:v4"
        ],
        "skill_name": "company_valuation_modeling",
        "model_name": "正常化市盈率估值",
        "model_role": "core",
        "forecast_start": "2026-01-01",
        "forecast_end": "2028-12-31",
        "valuation_date": "2026-07-24",
        "assumptions": common_assumptions,
        "limitations": "资源品低PE可能来自周期高点，必须与现金流和PB—ROE交叉验证。",
        "inputs": [
            _input(
                "2027正常化归母净利润",
                float(valuation[normalized_key]) * scale,
                unit,
                "2027",
                model_file_ref,
                "derived_fact",
                "权益产量—铜价—成本桥",
            ),
            _input(
                "适用PE区间",
                None,
                "倍",
                "2027",
                model_file_ref,
                "expert_assumption",
                pe.get("parameter_basis")
                or "同业、周期、国家风险与增长综合判断",
                low=float(pe["multiple_low"]),
                high=float(pe["multiple_high"]),
            ),
        ],
        "outputs": [
            _output(
                "目标市值",
                value=None,
                low=float(pe[pe_low_key]) * scale,
                high=float(pe[pe_high_key]) * scale,
                unit=unit,
                period="2027",
                formula="目标市值＝正常化归母净利润×适用PE",
                substitution=(
                    f"{float(valuation[normalized_key]) * scale:.2f}×"
                    f"{pe['multiple_low']:.2f}—{pe['multiple_high']:.2f}"
                ),
                conclusion="正常化PE给出的股权价值区间。",
                dependency="正常化利润与周期倍数",
            )
        ],
        "finalization": "independent",
    }
    pb_model = {
        "run_key": f"copper_b_20260726:{ticker}:pb_roe:v5",
        "supersedes_run_keys": [
            f"copper_b_20260726:{ticker}:pb_roe:v4"
        ],
        "skill_name": "company_valuation_modeling",
        "model_name": "PB—ROE资产回报估值",
        "model_role": "reference",
        "forecast_start": "2026-01-01",
        "forecast_end": "2028-12-31",
        "valuation_date": "2026-07-24",
        "assumptions": common_assumptions,
        "limitations": (
            "PB—ROE只检查正常化资产回报，不替代逐矿NAV；"
            + str(pb.get("parameter_basis") or "")
        ),
        "inputs": [
            _input(
                "2027前瞻归母权益",
                float(pb[equity_key]) * scale,
                unit,
                "2027",
                model_file_ref,
                "derived_fact",
                "2025权益加留存收益和资本变动",
            ),
            _input(
                "可持续ROE区间",
                None,
                "%",
                "长期",
                model_file_ref,
                "expert_assumption",
                pb.get("parameter_basis")
                or "周期正常化后的资产回报",
                low=float(pb["sustainable_roe_low"]) * 100,
                high=float(pb["sustainable_roe_high"]) * 100,
            ),
            _input(
                "采用PB区间",
                None,
                "倍",
                "2027",
                model_file_ref,
                "expert_assumption",
                pb.get("parameter_basis") or "由PB—ROE公式直接推导",
                low=float(pb["adopted_pb_low"]),
                high=float(pb["adopted_pb_high"]),
            ),
        ],
        "outputs": [
            _output(
                "目标市值（PB—ROE）",
                value=None,
                low=float(pb[pb_low_key]) * scale,
                high=float(pb[pb_high_key]) * scale,
                unit=unit,
                period="2027",
                formula="目标市值＝前瞻归母权益×采用PB",
                substitution=(
                    f"{float(pb[equity_key]) * scale:.2f}×"
                    f"{pb['adopted_pb_low']:.2f}—{pb['adopted_pb_high']:.2f}"
                ),
                conclusion="PB—ROE用于资产回报和周期位置对账。",
                dependency="归母权益与可持续ROE",
            )
        ],
        "finalization": "independent",
    }
    dcf_model = {
        "run_key": f"copper_b_20260726:{ticker}:fcfe_dcf:v5",
        "supersedes_run_keys": [
            f"copper_b_20260726:{ticker}:fcfe_dcf:v4"
        ],
        "skill_name": "company_valuation_modeling",
        "model_name": "股权自由现金流折现",
        "model_role": "reference",
        "forecast_start": "2026-01-01",
        "forecast_end": "2028-12-31",
        "valuation_date": "2026-07-24",
        "assumptions": common_assumptions,
        "limitations": (
            f"终值占比{float(dcf['terminal_value_share']) * 100:.1f}%，"
            "对股权成本和长期增长敏感，只作交叉验证。"
        ),
        "inputs": [
            _input(
                "股权成本区间",
                None,
                "%",
                "估值日",
                model_file_ref,
                "expert_assumption",
                dcf.get("parameter_basis")
                or "跨市场无风险利率、权益风险与公司风险综合",
                low=float(dcf["high_value_assumptions"]["cost_of_equity"]) * 100,
                high=float(dcf["low_value_assumptions"]["cost_of_equity"]) * 100,
            ),
            _input(
                "长期增长率区间",
                None,
                "%",
                "长期",
                model_file_ref,
                "expert_assumption",
                "低于股权成本的稳定增长",
                low=float(dcf["low_value_assumptions"]["terminal_growth"]) * 100,
                high=float(dcf["high_value_assumptions"]["terminal_growth"]) * 100,
            ),
            _input(
                "FY1—FY3股权自由现金流",
                None,
                unit,
                "2026—2028",
                model_file_ref,
                "derived_fact",
                "归母利润、资本开支和现金转换桥",
                value_text="读取冻结财务模型三年FCFE路径",
            ),
        ],
        "outputs": [
            _output(
                "股权现金流价值",
                value=None,
                low=float(dcf["equity_value_low"]) * scale,
                high=float(dcf["equity_value_high"]) * scale,
                unit=unit,
                period="2026-07-24",
                formula="股权价值＝FY1—FY3 FCFE折现值＋终值折现值",
                substitution=str(dcf.get("parameter_basis") or ""),
                conclusion="现金流比较值，不是无条件目标价。",
                dependency="FCFE、股权成本与长期增长",
            )
        ],
        "finalization": "independent",
    }
    return [pe_model, pb_model, dcf_model]


def _resource_implied_diagnostic_model(
    company: dict[str, Any],
    *,
    reconciliation: dict[str, Any],
    model_file_ref: str,
    reconciliation_ref: str,
    unit: str,
    scale: float,
) -> dict[str, Any]:
    name = company["company"]
    ticker = company["ticker"]
    diagnostic = reconciliation["workbook_style_resource_diagnostic"]
    price_rows = diagnostic["price_sensitivity"]
    inputs = [
        _input(
            "2027权益铜产量",
            float(diagnostic["attributable_copper_kt"]),
            "千吨",
            "2027",
            model_file_ref,
            "derived_fact",
            "逐项目产量×权益比例汇总；洛阳钼业采用已披露组合权益近似。",
        ),
        _input(
            "2027铜价—资源利润矩阵",
            None,
            "美元/吨",
            "2027",
            model_file_ref,
            "expert_assumption",
            "在8,000—14,500美元/吨的六档铜价上重算权益资源利润。",
            value_text="；".join(
                f"{row['copper_price_usd_t']:,.0f}美元/吨"
                for row in price_rows
            ),
            limitation="铜价档位是敏感性输入，不是发生概率。",
        ),
    ]
    outputs: list[dict[str, Any]] = []
    if name != "五矿资源":
        current_cap = float(diagnostic["current_market_cap_bn"]) * scale
        residual_profit = (
            float(diagnostic["non_copper_corporate_residual_profit_bn"]) * scale
        )
        residual_multiple = diagnostic["residual_profit_multiple_range"]
        resource_value = diagnostic["resource_implied_equity_value_range_bn"]
        resource_pe = diagnostic["resource_implied_pe_range"]
        unit_value = diagnostic[
            "unit_resource_value_wan_rmb_per_attributable_t_range"
        ]
        inputs.extend(
            [
                _input(
                    "当前总市值",
                    current_cap,
                    unit,
                    "2026-07-24",
                    reconciliation_ref,
                    "direct_fact",
                    "冻结模型完成后读取当前市场快照。",
                ),
                _input(
                    "2027非铜及公司层残余利润",
                    residual_profit,
                    unit,
                    "2027",
                    model_file_ref,
                    "derived_fact",
                    "基准归母利润减权益铜税后利润代理。",
                    limitation="残余项不是经审计分部利润。",
                ),
                _input(
                    "残余利润估值倍数",
                    None,
                    "倍",
                    "2027",
                    reconciliation_ref,
                    "expert_assumption",
                    "结合业务组合、周期性和国家风险后的诊断区间。",
                    low=float(residual_multiple[0]),
                    high=float(residual_multiple[1]),
                ),
            ]
        )
        outputs.extend(
            [
                _output(
                    "当前市场隐含资源业务市值",
                    value=None,
                    low=float(resource_value[0]) * scale,
                    high=float(resource_value[1]) * scale,
                    unit=unit,
                    period="2027",
                    formula="资源业务隐含市值＝当前总市值－非铜及公司层残余利润×适用倍数",
                    substitution=(
                        f"{current_cap:.2f}－{residual_profit:.2f}×"
                        f"{residual_multiple[0]:.2f}—{residual_multiple[1]:.2f}"
                    ),
                    conclusion="这是当前价格的业务拆分诊断，不是目标市值。",
                    dependency="当前市值、残余利润及其倍数",
                ),
                _output(
                    "当前市场隐含资源业务PE",
                    value=None,
                    low=float(resource_pe[0]),
                    high=float(resource_pe[1]),
                    unit="倍",
                    period="2027",
                    formula="资源业务隐含PE＝资源业务隐含市值÷权益铜税后利润代理",
                    substitution=(
                        f"{resource_pe[0]:.2f}—{resource_pe[1]:.2f}倍"
                    ),
                    conclusion="用于检查当前价格对铜资源利润的资本化程度。",
                    dependency="资源业务隐含市值与权益铜利润",
                ),
                _output(
                    "单位权益铜产量隐含市值",
                    value=None,
                    low=float(unit_value[0]),
                    high=float(unit_value[1]),
                    unit="万元人民币/吨",
                    period="2027",
                    formula="单位权益产量市值＝资源业务隐含市值÷权益铜产量",
                    substitution=f"{unit_value[0]:.2f}—{unit_value[1]:.2f}",
                    conclusion="只适合在一致权益和成本口径下横向比较。",
                    dependency="资源业务隐含市值与权益铜产量",
                ),
            ]
        )
    else:
        current_cap = (
            float(diagnostic["current_market_cap_usd_bn_proxy"]) * scale
        )
        inputs.append(
            _input(
                "当前美元折算市值",
                current_cap,
                unit,
                "2026-07-26",
                reconciliation_ref,
                "direct_fact",
                "港元市值按7.80港元/美元折算。",
            )
        )
        outputs.extend(
            [
                _output(
                    "当前市值下集团隐含PE",
                    value=float(diagnostic["current_group_implied_pe"]),
                    low=None,
                    high=None,
                    unit="倍",
                    period="2027",
                    formula="集团隐含PE＝当前美元折算市值÷2027年归母利润",
                    substitution=f"{diagnostic['current_group_implied_pe']:.2f}倍",
                    conclusion="五矿资源不强拆正的其他业务价值，保留集团口径。",
                    dependency="当前市值与集团归母利润",
                ),
                _output(
                    "单位权益铜产量隐含市值",
                    value=float(
                        diagnostic[
                            "unit_group_value_wan_rmb_per_attributable_t"
                        ]
                    ),
                    low=None,
                    high=None,
                    unit="万元人民币/吨",
                    period="2027",
                    formula="单位权益产量市值＝美元折算市值×美元兑人民币÷权益铜产量",
                    substitution=(
                        f"{diagnostic['unit_group_value_wan_rmb_per_attributable_t']:.2f}"
                    ),
                    conclusion="这是集团口径的单位产量诊断，不是资源SOTP。",
                    dependency="当前市值、汇率与权益铜产量",
                ),
            ]
        )
    return {
        "run_key": f"copper_b_20260726:{ticker}:resource_implied_valuation:v2",
        "supersedes_run_keys": [
            f"copper_b_20260726:{ticker}:resource_implied_valuation:v1"
        ],
        "skill_name": "company_valuation_modeling",
        "model_name": "铜价—资源利润—市场隐含估值诊断",
        "model_role": "diagnostic",
        "forecast_start": "2027-01-01",
        "forecast_end": "2027-12-31",
        "valuation_date": "2026-07-24",
        "assumptions": {
            "reference_workbook": "碳酸锂标的估值测算20260606.xlsx",
            "transfer_policy": (
                "迁移权益产量、资源利润矩阵和市值拆分公式；不迁移锂行业税率、"
                "产品折算、成本、税后系数或估值倍数。"
            ),
            "price_sensitivity": price_rows,
        },
        "limitations": diagnostic["limitations"],
        "inputs": inputs,
        "outputs": outputs,
        "finalization": "reviewed",
    }


def _a_company(
    name: str,
    *,
    snapshot: dict[str, Any],
    models: dict[str, Any],
    recon: dict[str, Any],
) -> dict[str, Any]:
    identity = A_IDENTITIES[name]
    ticker = identity["ticker"]
    model = _model_company(models, name)
    seller = recon["companies"][name]
    raw_snapshot_path = _relative(SNAPSHOT_PATH)
    snapshot_hash = _file_hash(SNAPSHOT_PATH)
    model_ref = f"sha256:{_file_hash(MODEL_PATH).split(':', 1)[1]}"
    reconciliation_ref = _file_hash(RECON_PATH)
    current_key = f"wind_current_{ticker}"
    consensus_key = f"wind_consensus_{ticker}"
    seller_key = f"seller_recent_{ticker}"
    source_snapshots = [
        _snapshot(
            key=current_key,
            provider="wind",
            source_ref=f"wind:WSS:{ticker}:current:20260724",
            title=f"{name} Wind当前市场与财务快照",
            as_of_date="2026-07-24",
            content_hash=snapshot_hash,
            raw_snapshot_path=raw_snapshot_path,
            metadata={"ticker": ticker, "frequency": "snapshot"},
            publisher="Wind",
        ),
        _snapshot(
            key=consensus_key,
            provider="wind",
            source_ref=f"wind:WSS:{ticker}:west_fy1_fy3:20260724",
            title=f"{name} Wind FY1—FY3一致预期",
            as_of_date="2026-07-24",
            content_hash=snapshot_hash,
            raw_snapshot_path=raw_snapshot_path,
            metadata={"ticker": ticker, "frequency": "snapshot"},
            publisher="Wind",
        ),
        _snapshot(
            key=seller_key,
            provider="external_consensus",
            source_channel="report",
            source_ref=f"recent_reports:{ticker}:2026Q2Q3",
            title=f"{name}最近两个季度卖方预测对账",
            as_of_date=AS_OF_DATE,
            content_hash=_file_hash(RECON_PATH),
            raw_snapshot_path=_relative(RECON_PATH),
            metadata={
                "ticker": ticker,
                "institutions": [
                    {
                        "institution": row["institution"],
                        "published_date": row["published_date"],
                        "language": row["language"],
                    }
                    for row in seller["selected_reports"]
                ],
            },
            publisher="多家研究机构",
        ),
    ]
    observations: list[dict[str, Any]] = []
    current = snapshot["wind"]["current"][ticker]
    for raw_key, (metric, unit, currency, wind_field) in CURRENT_RAW.items():
        value = _finite(current.get(raw_key))
        if value is None:
            continue
        observations.append(
            {
                "metric_name": metric,
                "value_num": value,
                "unit": unit,
                "currency": currency,
                "period_end": "2026-07-24",
                "frequency": "snapshot",
                "fact_type": "market",
                "as_of_date": "2026-07-24",
                "provider": "wind",
                "raw_feature_name": f"Wind WSS.{wind_field}",
                "source_snapshot_key": current_key,
                "quality_status": "usable",
                "scenario_name": "reported",
            }
        )
    for year in range(2021, 2026):
        annual_key = f"wind_annual_{ticker}_{year}"
        source_snapshots.append(
            _snapshot(
                key=annual_key,
                provider="wind",
                source_ref=f"wind:WSS:{ticker}:annual:{year}",
                title=f"{name} Wind {year}年财务快照",
                as_of_date=f"{year}-12-31",
                content_hash=snapshot_hash,
                raw_snapshot_path=raw_snapshot_path,
                metadata={
                    "ticker": ticker,
                    "fiscal_year": year,
                    "announcement_date": ANNOUNCEMENT_DATES[ticker][year],
                },
                publisher="Wind",
            )
        )
        row = snapshot["wind"]["annual"][str(year)]["rows"][ticker]
        for raw_field, (metric, unit, currency, divisor) in ANNUAL_RAW.items():
            value = _finite(row.get(raw_field))
            if value is None:
                continue
            observations.append(
                {
                    "metric_name": metric,
                    "value_num": value / divisor,
                    "unit": unit,
                    "currency": currency,
                    "period_start": f"{year}-01-01",
                    "period_end": f"{year}-12-31",
                    "fiscal_year": year,
                    "fiscal_period": "FY",
                    "frequency": "annual",
                    "fact_type": "actual",
                    "as_of_date": f"{year}-12-31",
                    "announcement_date": ANNOUNCEMENT_DATES[ticker][year],
                    "provider": "wind",
                    "raw_feature_name": f"Wind WSS.{raw_field}",
                    "source_snapshot_key": annual_key,
                    "quality_status": "usable",
                    "scenario_name": "reported",
                }
            )
    consensus = snapshot["wind"]["consensus_fy1_fy3"]["rows"][ticker]
    for index, year in enumerate((2026, 2027, 2028), 1):
        specs = {
            "revenue": (f"west_sales_fy{index}", 1e8, "亿元人民币", "CNY"),
            "net_income": (
                f"west_netprofit_fy{index}",
                1e8,
                "亿元人民币",
                "CNY",
            ),
            "eps": (f"west_eps_fy{index}", 1.0, "元/股", "CNY"),
            "roe": (f"west_avgroe_fy{index}", 1.0, "%", None),
        }
        for metric, (raw, divisor, unit, currency) in specs.items():
            value = _finite(consensus.get(raw))
            if value is None:
                continue
            observations.append(
                {
                    "metric_name": metric,
                    "value_num": value / divisor,
                    "unit": unit,
                    "currency": currency,
                    "period_start": f"{year}-01-01",
                    "period_end": f"{year}-12-31",
                    "fiscal_year": year,
                    "fiscal_period": f"FY{index}",
                    "frequency": "annual",
                    "fact_type": "consensus",
                    "as_of_date": "2026-07-24",
                    "provider": "wind",
                    "raw_feature_name": f"Wind WSS.{raw}",
                    "source_snapshot_key": consensus_key,
                    "quality_status": "usable",
                    "scenario_name": "median",
                }
            )
    financial_model, internal_observations = _financial_model(
        model,
        model_file_ref=model_ref,
        market_ref=f"wind:WSS:{ticker}:west_fy1_fy3:20260724",
        unit="亿元人民币",
        scale=10.0,
        seller=seller,
    )
    observations.extend(internal_observations)
    observations = normalize_nonmeaningful_annual_roe(observations)
    return {
        "research_company_id": identity["research_company_id"],
        "security": {
            "canonical_name": name,
            "ticker": ticker,
            "market": identity["market"],
            "listing_status": identity["listing_status"],
            "reporting_currency": "CNY",
            "identity_status": "verified",
        },
        "source_snapshots": source_snapshots,
        "model_runs": [
            financial_model,
            *_valuation_models(
                model,
                model_file_ref=model_ref,
                unit="亿元人民币",
                scale=10.0,
            ),
            _resource_implied_diagnostic_model(
                model,
                reconciliation=seller,
                model_file_ref=model_ref,
                reconciliation_ref=reconciliation_ref,
                unit="亿元人民币",
                scale=10.0,
            ),
        ],
        "observations": observations,
    }


def _yf_row(
    payload: dict[str, Any],
    statement: str,
    line_item: str,
    year: int,
) -> float | None:
    row = payload["yfinance"][statement]["rows"].get(line_item) or {}
    return _finite(row.get(f"{year}-12-31 00:00:00"))


def _mmg_company(
    *,
    snapshot: dict[str, Any],
    models: dict[str, Any],
    recon: dict[str, Any],
) -> dict[str, Any]:
    name = "五矿资源"
    ticker = MMG_IDENTITY["ticker"]
    model = _model_company(models, name)
    seller = recon["companies"][name]
    snapshot_hash = _file_hash(SNAPSHOT_PATH)
    model_ref = _file_hash(MODEL_PATH)
    reconciliation_ref = _file_hash(RECON_PATH)
    raw_path = _relative(SNAPSHOT_PATH)
    yf_key = "yfinance_1208hk"
    seller_key = "seller_recent_1208hk"
    source_snapshots = [
        _snapshot(
            key=yf_key,
            provider="yfinance",
            source_ref="yfinance:1208.HK:get_info+financials:20260726",
            title="五矿资源 yfinance市场与财务快照",
            as_of_date=AS_OF_DATE,
            content_hash=snapshot_hash,
            raw_snapshot_path=raw_path,
            metadata={"ticker": ticker, "financial_currency": "USD"},
            publisher="Yahoo Finance",
        ),
        _snapshot(
            key=seller_key,
            provider="external_consensus",
            source_channel="report",
            source_ref="recent_reports:1208.HK:2026Q2Q3",
            title="五矿资源最近两个季度卖方预测对账",
            as_of_date=AS_OF_DATE,
            content_hash=_file_hash(RECON_PATH),
            raw_snapshot_path=_relative(RECON_PATH),
            metadata={
                "ticker": ticker,
                "institutions": [
                    {
                        "institution": row["institution"],
                        "published_date": row["published_date"],
                        "language": row["language"],
                    }
                    for row in seller["selected_reports"]
                ],
            },
            publisher="多家研究机构",
        ),
    ]
    observations: list[dict[str, Any]] = []
    info = snapshot["yfinance"]["info"]
    current_specs = {
        "currentPrice": ("close", "港元/股", "HKD", 1.0),
        "trailingPE": ("pe_ttm", "倍", None, 1.0),
        "forwardPE": ("pe_forward", "倍", None, 1.0),
        "priceToBook": ("pb", "倍", None, 1.0),
        "trailingEps": ("eps_ttm", "港元/股", "HKD", 1.0),
        "bookValue": ("bps_mrq", "港元/股", "HKD", 1.0),
        "returnOnEquity": ("roe", "%", None, 100.0),
        "returnOnAssets": ("roa", "%", None, 100.0),
        "marketCap": ("market_cap_cny", "亿元人民币", "CNY", 7.15 / 7.8 / 1e8),
    }
    for raw, (metric, unit, currency, multiplier) in current_specs.items():
        value = _finite(info.get(raw))
        if value is None:
            continue
        observations.append(
            {
                "metric_name": metric,
                "value_num": value * multiplier,
                "unit": unit,
                "currency": currency,
                "period_end": AS_OF_DATE,
                "frequency": "snapshot",
                "fact_type": "market",
                "as_of_date": AS_OF_DATE,
                "provider": "yfinance",
                "raw_feature_name": f"yfinance.get_info.{raw}",
                "source_snapshot_key": yf_key,
                "formula": (
                    "港元市值÷7.80×7.15÷1e8"
                    if raw == "marketCap"
                    else None
                ),
                "input_refs": (
                    ["yfinance marketCap", "7.80 HKD/USD", "7.15 CNY/USD"]
                    if raw == "marketCap"
                    else []
                ),
                "quality_status": "usable",
                "scenario_name": "reported",
            }
        )
    for year in range(2022, 2026):
        fields = {
            "revenue": ("income_stmt", "Total Revenue"),
            "net_income": (
                "income_stmt",
                "Net Income Common Stockholders",
            ),
            "operating_cash_flow": (
                "cash_flow",
                "Operating Cash Flow",
            ),
            "capex": ("cash_flow", "Capital Expenditure"),
            "free_cash_flow": ("cash_flow", "Free Cash Flow"),
            "total_assets": ("balance_sheet", "Total Assets"),
            "total_equity": (
                "balance_sheet",
                "Total Equity Gross Minority Interest",
            ),
            "book_value": ("balance_sheet", "Stockholders Equity"),
            "total_liabilities": (
                "balance_sheet",
                "Total Liabilities Net Minority Interest",
            ),
            "net_debt": ("balance_sheet", "Net Debt"),
        }
        for metric, (statement, line_item) in fields.items():
            value = _yf_row(snapshot, statement, line_item, year)
            if value is None:
                continue
            if metric == "capex":
                value = abs(value)
            observations.append(
                {
                    "metric_name": metric,
                    "value_num": value / 1e8,
                    "unit": "亿美元",
                    "currency": "USD",
                    "period_start": f"{year}-01-01",
                    "period_end": f"{year}-12-31",
                    "fiscal_year": year,
                    "fiscal_period": "FY",
                    "frequency": "annual",
                    "fact_type": "actual",
                    "as_of_date": f"{year}-12-31",
                    "provider": "yfinance",
                    "raw_feature_name": f"yfinance.{statement}.{line_item}",
                    "source_snapshot_key": yf_key,
                    "quality_status": "usable",
                    "scenario_name": "reported",
                }
            )
        net_income = _yf_row(
            snapshot,
            "income_stmt",
            "Net Income Common Stockholders",
            year,
        )
        equity = _yf_row(snapshot, "balance_sheet", "Stockholders Equity", year)
        assets = _yf_row(snapshot, "balance_sheet", "Total Assets", year)
        revenue = _yf_row(snapshot, "income_stmt", "Total Revenue", year)
        if net_income is not None and equity not in {None, 0.0}:
            observations.append(
                {
                    "metric_name": "roe",
                    "value_num": net_income / equity * 100,
                    "unit": "%",
                    "period_start": f"{year}-01-01",
                    "period_end": f"{year}-12-31",
                    "fiscal_year": year,
                    "fiscal_period": "FY",
                    "frequency": "annual",
                    "fact_type": "actual",
                    "as_of_date": f"{year}-12-31",
                    "provider": "yfinance",
                    "raw_feature_name": "derived.net_income/common_stock_equity",
                    "source_snapshot_key": yf_key,
                    "formula": "归母净利润÷期末母公司权益",
                    "input_refs": ["net_income", "book_value"],
                    "quality_status": "usable",
                    "scenario_name": "reported",
                }
            )
        if net_income is not None and assets not in {None, 0.0}:
            observations.append(
                {
                    "metric_name": "roa",
                    "value_num": net_income / assets * 100,
                    "unit": "%",
                    "period_start": f"{year}-01-01",
                    "period_end": f"{year}-12-31",
                    "fiscal_year": year,
                    "fiscal_period": "FY",
                    "frequency": "annual",
                    "fact_type": "actual",
                    "as_of_date": f"{year}-12-31",
                    "provider": "yfinance",
                    "raw_feature_name": "derived.net_income/total_assets",
                    "source_snapshot_key": yf_key,
                    "formula": "归母净利润÷期末总资产",
                    "input_refs": ["net_income", "total_assets"],
                    "quality_status": "usable",
                    "scenario_name": "reported",
                }
            )
        if net_income is not None and revenue not in {None, 0.0}:
            observations.append(
                {
                    "metric_name": "net_margin",
                    "value_num": net_income / revenue * 100,
                    "unit": "%",
                    "period_start": f"{year}-01-01",
                    "period_end": f"{year}-12-31",
                    "fiscal_year": year,
                    "fiscal_period": "FY",
                    "frequency": "annual",
                    "fact_type": "actual",
                    "as_of_date": f"{year}-12-31",
                    "provider": "yfinance",
                    "raw_feature_name": "derived.net_income/revenue",
                    "source_snapshot_key": yf_key,
                    "formula": "归母净利润÷营业收入",
                    "input_refs": ["net_income", "revenue"],
                    "quality_status": "usable",
                    "scenario_name": "reported",
                }
            )
    seller_median = seller["seller_median"]
    for index, year in enumerate((2026, 2027, 2028), 1):
        for metric, key in (("revenue", "revenue_bn"), ("net_income", "net_income_bn")):
            value = _finite(seller_median.get(key, {}).get(str(year)))
            if value is None:
                continue
            observations.append(
                {
                    "metric_name": metric,
                    "value_num": value * 10.0,
                    "unit": "亿美元",
                    "currency": "USD",
                    "period_start": f"{year}-01-01",
                    "period_end": f"{year}-12-31",
                    "fiscal_year": year,
                    "fiscal_period": f"FY{index}",
                    "frequency": "annual",
                    "fact_type": "consensus",
                    "as_of_date": AS_OF_DATE,
                    "provider": "external_consensus",
                    "raw_feature_name": f"recent_reports.{metric}.median",
                    "source_snapshot_key": seller_key,
                    "quality_status": "usable",
                    "scenario_name": "median",
                }
            )
    financial_model, internal_observations = _financial_model(
        model,
        model_file_ref=model_ref,
        market_ref="recent_reports:1208.HK:2026Q2Q3",
        unit="亿美元",
        scale=10.0,
        seller=seller,
    )
    observations.extend(internal_observations)
    observations = normalize_nonmeaningful_annual_roe(observations)
    return {
        "research_company_id": MMG_IDENTITY["research_company_id"],
        "security": {
            "canonical_name": name,
            "ticker": ticker,
            "market": MMG_IDENTITY["market"],
            "listing_status": MMG_IDENTITY["listing_status"],
            "reporting_currency": "USD",
            "identity_status": "verified",
        },
        "source_snapshots": source_snapshots,
        "model_runs": [
            financial_model,
            *_valuation_models(
                model,
                model_file_ref=model_ref,
                unit="亿美元",
                scale=10.0,
            ),
            _resource_implied_diagnostic_model(
                model,
                reconciliation=seller,
                model_file_ref=model_ref,
                reconciliation_ref=reconciliation_ref,
                unit="亿美元",
                scale=10.0,
            ),
        ],
        "observations": observations,
    }


def build_export() -> dict[str, Any]:
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    models = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    recon = json.loads(RECON_PATH.read_text(encoding="utf-8"))
    return {
        "export_schema_version": "company_financial_profile_export.v1",
        "research_run_ref": "copper_b_20260726",
        "as_of_date": AS_OF_DATE,
        "source_artifacts": [
            {"path": _relative(SNAPSHOT_PATH), "sha256": _file_hash(SNAPSHOT_PATH)},
            {"path": _relative(MODEL_PATH), "sha256": _file_hash(MODEL_PATH)},
            {"path": _relative(RECON_PATH), "sha256": _file_hash(RECON_PATH)},
        ],
        "companies": [
            _a_company(
                "紫金矿业",
                snapshot=snapshot,
                models=models,
                recon=recon,
            ),
            _a_company(
                "洛阳钼业",
                snapshot=snapshot,
                models=models,
                recon=recon,
            ),
            _mmg_company(snapshot=snapshot, models=models, recon=recon),
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    payload = build_export()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "companies": len(payload["companies"]),
                "observations": sum(
                    len(company["observations"])
                    for company in payload["companies"]
                ),
                "model_runs": sum(
                    len(company["model_runs"])
                    for company in payload["companies"]
                ),
                "sha256": _file_hash(output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
