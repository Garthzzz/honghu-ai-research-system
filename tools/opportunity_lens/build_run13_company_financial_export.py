from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from tools.financial.constants import ROOT
from tools.financial.opportunity_profile_export import EXPORT_SCHEMA_VERSION
from tools.financial.valuation import (
    book_value_profit_bridge,
    historical_pb_band,
    pb_double_click_decomposition,
)


DEFAULT_RUN_DIR = (
    ROOT
    / "opportunity_lens"
    / "research_outputs"
    / "20260722_byd_luxshare_optical_competition_run13"
)
DEFAULT_OUTPUT = DEFAULT_RUN_DIR / "company_financial_profile_export_v1.json"
RESEARCH_RUN_REF = "opportunity_lens:run13:byd_luxshare_optical_competition:20260722"
AS_OF_DATE = "2026-07-22"

COMPANIES = {
    "innolight": {
        "research_company_id": 1,
        "canonical_name": "中际旭创",
        "ticker": "300308.SZ",
        "security_id_hint": 1,
    },
    "eoptolink": {
        "research_company_id": 2,
        "canonical_name": "新易盛",
        "ticker": "300502.SZ",
        "security_id_hint": 2,
    },
    "luxshare": {
        "research_company_id": 14,
        "canonical_name": "立讯精密",
        "ticker": "002475.SZ",
        "security_id_hint": 13,
    },
    "byd": {
        "research_company_id": 414,
        "canonical_name": "比亚迪",
        "ticker": "002594.SZ",
        "security_id_hint": 400,
    },
}

MARKET_FIELDS = {
    "market_cap_cny_100m": ("market_cap_cny", "亿元人民币", "Wind WSS.mkt_cap_ard/1e8"),
    "pe_ttm": ("pe_ttm", "倍", "Wind WSS.pe_ttm"),
    "pe_forward_12m": ("pe_forward", "倍", "Wind WSS.pe_est_ftm"),
    "pb": ("pb", "倍", "Wind WSS.pb_lf"),
    "ps_ttm": ("ps_ttm", "倍", "Wind WSS.ps_ttm"),
    "ev_ebitda": ("ev_ebitda", "倍", "Wind WSS.ev2_to_ebitda"),
}

ACTUAL_SNAPSHOT_FIELDS = {
    "roe_ttm_pct": ("roe", "%", "Wind WSS.roe_ttm"),
    "roa_ttm_pct": ("roa", "%", "Wind WSS.roa2_ttm"),
    "eps_ttm_cny": ("eps_ttm", "元/股", "Wind WSS.eps_ttm"),
    "bps_latest_cny": ("bps_mrq", "元/股", "Wind WSS.bps_new"),
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return "sha256:" + digest


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
    fiscal_year: int | None,
    fiscal_period: str | None,
    fact_type: str,
    provider: str,
    raw_feature_name: str,
    formula: str | None,
    source_snapshot_key: str,
    model_run_key: str | None = None,
    scenario_name: str = "reported",
    currency: str | None = "CNY",
    period_end: str | None = None,
    announcement_date: str | None = None,
    frequency: str | None = None,
    as_of_date: str = AS_OF_DATE,
    input_refs: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "metric_name": metric,
        "value_num": value,
        "unit": unit,
        "currency": currency,
        "period_end": period_end,
        "fiscal_year": fiscal_year,
        "fiscal_period": fiscal_period,
        "frequency": frequency or ("annual" if fiscal_year else "snapshot"),
        "fact_type": fact_type,
        "as_of_date": as_of_date,
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


def _baseline_rows(independent: dict[str, Any], key: str) -> list[dict[str, Any]]:
    if key in {"innolight", "eoptolink"}:
        return list(independent["baseline"][key])
    group = independent["entrant_group_baseline_non_external_fact"][key]
    return [
        {
            "year": year,
            "revenue_cny_100m": group["revenue_cny_100m"][index],
            "net_income_cny_100m": group["parent_net_income_cny_100m"][index],
        }
        for index, year in enumerate(range(2026, 2032))
    ]


def _financial_model(
    independent: dict[str, Any],
    reconciliation: dict[str, Any],
    independent_path: Path,
    reconciliation_path: Path,
    key: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    company = COMPANIES[key]
    actual_2025 = independent["actuals"][key]["2025"]
    baseline = _baseline_rows(independent, key)
    run_key = f"ol13:{company['ticker']}:independent_financial_bridge:v4"
    basis = (
        independent["financial_model_level"]["baseline_method"]
        if key in {"innolight", "eoptolink"}
        else independent["entrant_group_baseline_non_external_fact"][key]["baseline_basis"]
    )
    inputs = [
        _input(
            "2025年营业收入",
            value=actual_2025["revenue_cny_100m"],
            unit="亿元人民币",
            period="2025",
            source_ref=_artifact_ref(independent_path, f"actuals.{key}.2025.revenue_cny_100m"),
            input_type="direct_fact",
            method="公司年度报告实际值，已在Run13冻结模型中统一为亿元人民币。",
        ),
        _input(
            "2025年归母净利润",
            value=actual_2025["parent_net_income_cny_100m"],
            unit="亿元人民币",
            period="2025",
            source_ref=_artifact_ref(
                independent_path, f"actuals.{key}.2025.parent_net_income_cny_100m"
            ),
            input_type="direct_fact",
            method="公司年度报告实际值，已在Run13冻结模型中统一为归母口径。",
        ),
        _input(
            "独立预测方法",
            value_text=basis,
            unit="文字",
            period="2026—2031",
            source_ref=_artifact_ref(independent_path, f"baseline_method.{key}"),
            input_type="expert_assumption",
            method="Run13在读取Wind一致预期前冻结的Level 3财务桥。",
            sensitivity="收入增速、净利率、现金转换和资本开支是主要敏感项。",
            limitation=independent["financial_model_level"]["use_boundary"],
        ),
    ]
    outputs: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    for row in baseline[:3]:
        year = int(row["year"])
        revenue = float(row["revenue_cny_100m"])
        net_income = float(row.get("net_income_cny_100m", row.get("parent_net_income_cny_100m")))
        outputs.extend(
            [
                _output(
                    f"{year}年营业收入",
                    revenue,
                    unit="亿元人民币",
                    period=str(year),
                    formula="上一年收入×（1＋独立研究设定的业务增速）",
                    substitution=f"Run13冻结路径＝{revenue:.2f}亿元",
                    dependency="独立经营路径",
                    conclusion="这是独立研究路径，不是一致预期。",
                ),
                _output(
                    f"{year}年归母净利润",
                    net_income,
                    unit="亿元人民币",
                    period=str(year),
                    formula=(
                        "营业收入×净利率"
                        if key in {"innolight", "eoptolink"}
                        else "各主要业务收入与利润桥汇总"
                    ),
                    substitution=f"Run13冻结路径＝{net_income:.2f}亿元",
                    dependency="独立经营路径",
                    conclusion="基线没有提前计入光模块规模化带来的条件增量。",
                ),
            ]
        )
        observations.extend(
            [
                _observation(
                    metric="revenue",
                    value=revenue,
                    unit="亿元人民币",
                    fiscal_year=year,
                    fiscal_period=f"FY{year - 2025}",
                    fact_type="internal_estimate",
                    provider="internal_model",
                    raw_feature_name="Run13独立营业收入预测",
                    formula="上一年收入×（1＋独立研究设定的业务增速）",
                    source_snapshot_key="independent_model",
                    model_run_key=run_key,
                    scenario_name="Run13独立基线",
                ),
                _observation(
                    metric="net_income",
                    value=net_income,
                    unit="亿元人民币",
                    fiscal_year=year,
                    fiscal_period=f"FY{year - 2025}",
                    fact_type="internal_estimate",
                    provider="internal_model",
                    raw_feature_name="Run13独立归母净利润预测",
                    formula=(
                        "营业收入×净利率"
                        if key in {"innolight", "eoptolink"}
                        else "各主要业务收入与利润桥汇总"
                    ),
                    source_snapshot_key="independent_model",
                    model_run_key=run_key,
                    scenario_name="Run13独立基线",
                ),
            ]
        )
        if key in {"innolight", "eoptolink"}:
            for metric, field, label, formula in (
                ("operating_cash_flow", "operating_cash_flow_cny_100m", "经营现金流", "归母净利润×现金转换率"),
                ("capex", "capex_cny_100m", "资本开支", "Run13逐年资本开支假设"),
                ("free_cash_flow", "free_cash_flow_cny_100m", "自由现金流", "经营现金流－资本开支"),
                ("net_margin", "net_margin_pct", "净利率", "归母净利润÷营业收入"),
            ):
                value = float(row[field])
                unit = "%" if metric == "net_margin" else "亿元人民币"
                outputs.append(
                    _output(
                        f"{year}年{label}",
                        value,
                        unit=unit,
                        period=str(year),
                        formula=formula,
                        substitution=f"Run13冻结路径＝{value:.2f}{unit}",
                        dependency="独立现金流路径",
                        conclusion="现金流结果用于情景比较；缺完整资产负债桥时不直接形成目标价。",
                    )
                )
                observations.append(
                    _observation(
                        metric=metric,
                        value=value,
                        unit=unit,
                        fiscal_year=year,
                        fiscal_period=f"FY{year - 2025}",
                        fact_type="internal_estimate",
                        provider="internal_model",
                        raw_feature_name=f"Run13独立{label}预测",
                        formula=formula,
                        source_snapshot_key="independent_model",
                        model_run_key=run_key,
                        scenario_name="Run13独立基线",
                    )
                )

    reconciliations = []
    for row in reconciliation["comparison"][key]:
        year = int(row["fiscal_year"])
        for metric, independent_field, benchmark_field, unit, label in (
            (
                "revenue",
                "independent_revenue_cny_100m",
                "wind_consensus_revenue_cny_100m",
                "亿元人民币",
                "营业收入",
            ),
            (
                "net_income",
                "independent_parent_net_income_cny_100m",
                "wind_consensus_parent_net_income_cny_100m",
                "亿元人民币",
                "归母净利润",
            ),
        ):
            independent_value = float(row[independent_field])
            benchmark_value = float(row[benchmark_field])
            reconciliations.append(
                {
                    "benchmark_type": "consensus",
                    "benchmark_source_ref": _artifact_ref(
                        reconciliation_path, f"comparison.{key}.{year}.{metric}"
                    ),
                    "metric_name": metric,
                    "period": str(year),
                    "independent_value": independent_value,
                    "benchmark_value": benchmark_value,
                    "unit": unit,
                    "decomposition": {
                        "difference_value": independent_value - benchmark_value,
                        "difference_pct": (
                            independent_value / benchmark_value - 1 if benchmark_value else None
                        ),
                    },
                    "conclusion": f"Run13独立{label}与Wind一致预期的差异已保留，未向市场预测硬凑。",
                }
            )
    model = {
        "run_key": run_key,
        "skill_name": "company_financial_modeling",
        "model_name": "Run13独立财务桥（FY2026—FY2028）",
        "model_role": "primary",
        "forecast_start": "2026",
        "forecast_end": "2028",
        "valuation_date": AS_OF_DATE,
        "assumptions": {
            "model_level": independent["financial_model_level"]["level"],
            "baseline_basis": basis,
            "independent_before_consensus": True,
        },
        "limitations": independent["financial_model_level"]["use_boundary"],
        "finalization": "independent",
        "inputs": inputs,
        "outputs": outputs,
        "reconciliations": reconciliations,
    }
    return model, observations


def _reverse_pe_model(
    independent: dict[str, Any],
    reconciliation: dict[str, Any],
    independent_path: Path,
    reconciliation_path: Path,
    key: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    company = COMPANIES[key]
    market_cap = float(
        reconciliation["external_benchmarks"][key]["market"]["market_cap_cny_100m"]
    )
    comparisons = reconciliation["comparison"][key]
    run_key = f"ol13:{company['ticker']}:reverse_pe_diagnostic:v4"
    inputs = [
        _input(
            "估值日总市值",
            value=market_cap,
            unit="亿元人民币",
            period=AS_OF_DATE,
            source_ref=_artifact_ref(
                reconciliation_path, f"external_benchmarks.{key}.market.market_cap_cny_100m"
            ),
            input_type="external_consensus",
            method="Wind估值日总市值。",
        )
    ]
    outputs: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    for row in comparisons:
        year = int(row["fiscal_year"])
        profit = float(row["independent_parent_net_income_cny_100m"])
        pe = market_cap / profit
        inputs.append(
            _input(
                f"{year}年独立归母净利润",
                value=profit,
                unit="亿元人民币",
                period=str(year),
                source_ref=_artifact_ref(
                    independent_path, f"independent_financial_path.{key}.{year}.net_income"
                ),
                input_type="derived_fact",
                method="Run13在读取一致预期前冻结的独立财务桥。",
            )
        )
        outputs.append(
            _output(
                f"{year}年当前市值对应市盈率",
                pe,
                unit="倍",
                period=str(year),
                formula="估值日总市值÷独立预测归母净利润",
                substitution=f"{market_cap:.2f}÷{profit:.2f}＝{pe:.2f}倍",
                dependency="当前市场反向估值",
                conclusion="该倍数说明当前价格对独立盈利路径的要求，不是目标市盈率。",
            )
        )
        observations.append(
            _observation(
                metric="pe_forward",
                value=pe,
                unit="倍",
                fiscal_year=year,
                fiscal_period=f"FY{year - 2025}",
                fact_type="implied",
                provider="internal_model",
                raw_feature_name="当前市值对应的独立预测市盈率",
                formula="估值日总市值÷独立预测归母净利润",
                source_snapshot_key="external_reconciliation",
                model_run_key=run_key,
                scenario_name="Run13独立盈利路径",
                currency=None,
            )
        )

    if key in reconciliation.get("incumbent_valuation_reconciliation", {}):
        reverse = reconciliation["incumbent_valuation_reconciliation"][key][
            "discounted_reverse_terminal_pe"
        ]
        for multiple_text, required_profit in reverse[
            "required_2031_net_income_cny_100m"
        ].items():
            multiple = float(multiple_text.replace("倍", ""))
            required_profit = float(required_profit)
            outputs.append(
                _output(
                    f"2031年终值{multiple_text}所需归母净利润",
                    required_profit,
                    unit="亿元人民币",
                    period="2031",
                    formula="（当前市值－显性期自由现金流现值）×终值折现还原÷终值市盈率",
                    substitution=(
                        f"Run13反向终值桥在{multiple:.0f}倍终值市盈率下要求"
                        f"{required_profit:.2f}亿元归母净利润"
                    ),
                    dependency="当前市场反向终值",
                    conclusion="这是给定终值倍数后的市场要求，不是公司盈利预测。",
                )
            )
            observations.append(
                _observation(
                    metric="net_income",
                    value=required_profit,
                    unit="亿元人民币",
                    fiscal_year=2031,
                    fiscal_period="FY6",
                    fact_type="implied",
                    provider="internal_model",
                    raw_feature_name="终值倍数情景要求的归母净利润",
                    formula="（当前市值－显性期自由现金流现值）×终值折现还原÷终值市盈率",
                    source_snapshot_key="external_reconciliation",
                    model_run_key=run_key,
                    scenario_name=f"2031年终值{multiple_text}",
                )
            )
    model = {
        "run_key": run_key,
        "skill_name": "company_valuation_modeling",
        "model_name": "当前市值下的反向市盈率诊断",
        "model_role": "diagnostic",
        "forecast_start": "2026",
        "forecast_end": "2031" if key in {"innolight", "eoptolink"} else "2028",
        "valuation_date": AS_OF_DATE,
        "assumptions": {
            "market_cap_fixed_at_valuation_date": True,
            "purpose": "解释当前价格对独立盈利路径的要求，不生成目标价。",
        },
        "limitations": "结果依赖Run13独立盈利路径；市值与盈利口径不含估值日后的市场变化。",
        "finalization": "reviewed",
        "inputs": inputs,
        "outputs": outputs,
    }
    return model, observations


PB_FRAMEWORK = {
    "innolight": {
        "applicability": "诊断方法",
        "cycle_sensitivity": "中高：AI资本开支、产品代际和客户份额共同驱动",
        "asset_intensity": "中等：制造与扩产重要，但技术、客户和产品组合比账面资产更能解释价值",
        "basis": (
            "公司ROE和ROA很高，但当前估值主要反映高速光模块增长、客户份额和"
            "技术代际，不适合把历史PB中枢直接当目标倍数。PB用于检查盈利留存后"
            "估值能否消化，以及高回报是否伴随现金流兑现。"
        ),
        "price_exposure": "800G/1.6T产品ASP、客户议价和新进入者额外降价",
        "profit_driver": "高速产品出货、产品组合、客户份额、良率和毛利率",
        "tags": [
            {"label": "高资产回报", "basis": "2025年Wind ROE和ROA均处于较高水平"},
            {"label": "客户与代际驱动", "basis": "价值更依赖客户份额和高速产品迭代，而非账面资产重置价值"},
            {"label": "现金流需跟踪", "basis": "扩产、存货和应收会放大竞争冲击"},
        ],
    },
    "eoptolink": {
        "applicability": "诊断方法",
        "cycle_sensitivity": "中高：AI需求、产品放量和客户集中度共同驱动",
        "asset_intensity": "中等：需要持续扩产，但高回报更多来自产品与客户而非资产稀缺性",
        "basis": (
            "公司盈利和资产回报处于快速扩张期，当前PB显著受高速产品增长预期影响。"
            "PB—ROE适合检查净资产增长和估值收敛，不适合作为脱离产品周期的主目标价。"
        ),
        "price_exposure": "高速光模块ASP、客户采购节奏和第二供应商报价",
        "profit_driver": "高速产品放量、客户结构、产品组合、良率和净利率",
        "tags": [
            {"label": "高资产回报", "basis": "2025年ROE和ROA处于很高水平"},
            {"label": "高增长高波动", "basis": "利润路径对AI需求和客户项目兑现高度敏感"},
            {"label": "估值收敛需验证", "basis": "需要观察盈利留存是否足以消化当前PB"},
        ],
    },
    "luxshare": {
        "applicability": "有效参考",
        "cycle_sensitivity": "中等：消费电子周期、客户项目和新业务爬坡共同影响",
        "asset_intensity": "较高：制造资产、营运资本和持续资本开支对回报形成约束",
        "basis": (
            "立讯是大型制造平台，账面资本、资产周转和杠杆对ROE具有实质影响；"
            "PB—ROE可以作为有效参考，但复合业务和客户结构仍要求PE、现金流与"
            "分部经营判断共同约束。"
        ),
        "price_exposure": "消费电子代工价格、新项目爬坡效率和潜在光模块报价",
        "profit_driver": "项目份额、制造良率、资产周转、毛利率和费用率",
        "tags": [
            {"label": "制造平台型", "basis": "总资产和资本开支规模较大，资产周转影响ROE"},
            {"label": "稳健扩张观察", "basis": "新业务扩张需与现金流和资本回报同步验证"},
            {"label": "杠杆质量需拆解", "basis": "权益乘数较高，需区分经营性占款与有息负债"},
        ],
    },
    "byd": {
        "applicability": "有效参考",
        "cycle_sensitivity": "高：汽车价格、销量、产品结构和产能利用率共同驱动",
        "asset_intensity": "高：整车、电池和垂直整合需要大量固定资产与资本开支",
        "basis": (
            "比亚迪属于重资产、强资本开支和价格竞争敏感的制造企业，单期PE容易受"
            "汽车价格周期与扩产节奏影响。PB—ROE适合作为重要参考，但复合业务、"
            "少数股东和产业链协同决定其不能只靠单一PB历史分位估值。"
        ),
        "price_exposure": "整车售价、价格竞争、车型结构和电池成本",
        "profit_driver": "销量、单车利润、产能利用率、电池与电子业务盈利、资本开支",
        "tags": [
            {"label": "重资产周期成长", "basis": "资产规模与资本开支大，销量和价格周期同时影响回报"},
            {"label": "资本开支兑现型", "basis": "利润增长必须与ROE、ROA和现金流改善共同验证"},
            {"label": "右侧确认优先", "basis": "价格竞争和高资本投入下，需确认利润率与现金流拐点"},
        ],
    },
}

COMPANY_DETAIL_SUMMARIES = {
    "innolight": {
        "conclusion": (
            "中际旭创的核心价值仍来自高速光模块产品、全球客户份额和现金转换，"
            "PB—ROE只用于检验高资产回报能否持续消化高估值。"
        ),
        "operating_analysis": (
            "冻结模型预计2026—2028年归母净利润236.0/288.0/330.4亿元、自由现金流"
            "179.2/233.4/277.8亿元；Wind一致预期为303.8/534.9/794.1亿元，差距从"
            "22%扩大到58%。这不是小幅参数差，而是市场对1.6T出货、全球份额和利润率"
            "持续时间的判断明显更强。若现金流没有跟上利润，或新进入者获得全球客户复购，"
            "高增长叙事会同时受到盈利和估值两端压力。"
        ),
        "valuation_analysis": (
            "估值日市值11830亿元、滚动PE 79.14倍、PB 34.16倍，ROE/ROA为"
            "42.01%/33.44%。按独立2026年利润计算约50倍PE，按2028年利润仍约36倍；"
            "当前1060.8元也高于五年月度PE估值带80%分位对应的约849.8元。公司是高ROA的"
            "轻资产成长股，PB不能独立给目标价；现金流法因缺少完整净现金桥只作下行校验。"
            "因此现价要求的不只是增长，而是连续超越独立基线并接近市场一致预期。"
        ),
        "buy_point_analysis": (
            "风险收益开始改善的观察条件是价格回到约850元以下，同时2026年归母净利润至少"
            "达到236亿元、自由现金流接近179亿元且1.6T全球客户份额稳定。若价格不回落，"
            "则需要利润和现金流明显向Wind一致预期靠拢，才能用盈利上修而非估值扩张消化现价。"
        ),
        "sell_point_analysis": (
            "在1060元附近或更高位置，若2026年利润仍接近独立基线而非303.8亿元一致预期，"
            "或经营现金流转弱、同代ASP额外下滑、全球客户出现持续份额流失，应把它视为"
            "减仓或回避信号；估值跌破历史分位本身不是卖点，经营假设被证伪才是。"
        ),
        "difference_causes": [
            "市场对1.6T放量、有效产能和利润率的假设高于本报告独立基线",
            "当前估值同时依赖全球客户份额稳定和经营现金流跟上利润增长",
            "现金流敏感值缺少完整净现金桥，只能用于识别市场要求，不能直接当目标价",
        ],
        "future_view": (
            "短期看1.6T量产、毛利率和经营现金流；长期看新进入者是否获得全球客户复购，"
            "以及公司在CPO/XPO等架构变化中的单位资本回报。"
        ),
        "positive_trigger": (
            "利润和经营现金流连续兑现、全球客户份额稳定，且估值回到历史估值带较低位置后，"
            "风险收益比才会明显改善。"
        ),
        "risk_trigger": (
            "若同代ASP额外下降、毛利率和现金转换持续走弱，同时立讯或比亚迪取得全球客户复购，"
            "盈利与估值倍数可能同时收缩。"
        ),
    },
    "eoptolink": {
        "conclusion": (
            "新易盛处于高速产品放量和扩产期，高ROE主要来自资产效率而非金融杠杆；"
            "估值判断必须把产品迭代、扩产回报和现金流放在一起。"
        ),
        "operating_analysis": (
            "冻结模型预计2026—2028年归母净利润122.4/146.3/164.3亿元、自由现金流"
            "79.0/106.7/130.5亿元；Wind一致预期为190.2/304.9/484.1亿元，差距从"
            "36%扩大到66%。关键分歧是高速产品收入、毛利率和扩产利用率能否长期保持，"
            "不是单一年度出货。高ROA说明当前经营效率优秀，但扩产、库存和应收会决定这种"
            "效率能否转成可分配现金。"
        ),
        "valuation_analysis": (
            "估值日市值7094亿元、滚动PE 66.05倍、PB 36.54倍，ROE/ROA为"
            "52.70%/41.21%。按独立2026年利润计算约58倍PE，按2028年利润仍约43倍；"
            "508.8元高于五年月度PE估值带80%分位对应的约449.5元。PB的高倍数只有在"
            "净资产扩张后ROE仍维持高位时才合理，不能把当前高ROA永久化；现金流模型缺少"
            "完整资产负债桥，也只能用来核验而不能当作目标价。"
        ),
        "buy_point_analysis": (
            "较合理的观察区是约326—450元，并要求2026年利润至少达到122亿元、自由现金流"
            "接近79亿元、1.6T产能利用率和客户复购同步确认。若股价维持在500元以上，"
            "需要盈利明显高于独立基线并向190亿元一致预期靠拢，才能补偿估值风险。"
        ),
        "sell_point_analysis": (
            "若股价在约509元或更高而利润仍落在独立路径，或资本开支与营运资金继续快于收入、"
            "同代产品额外降价、全球第二供应商形成持续复购，应降低仓位。真正的卖出理由是"
            "高ROA和现金转换被破坏，而不是价格短期跌回历史估值带。"
        ),
        "difference_causes": [
            "外部一致预期对高速产品收入和利润率的假设显著高于独立基线",
            "高PB要求净资产快速增长后ROE仍保持高位",
            "扩产、预付款、库存和应收会使净利润与自由现金流出现明显时点差",
        ],
        "future_view": (
            "短期验证1.6T出货、毛利率和经营现金流恢复；长期验证XPO/NPO/CPO等新架构"
            "能否保住客户价值，以及新进入者是否形成持续价格压力。"
        ),
        "positive_trigger": (
            "高速产品收入和现金流同步增长、扩产利用率提高，且估值回到历史估值带较低位置，"
            "才构成更有吸引力的观察区。"
        ),
        "risk_trigger": (
            "若全球第二供应商复购成立、同代价格额外下行且资本开支和营运资金继续快于收入，"
            "高ROA与高估值会同时承压。"
        ),
    },
    "luxshare": {
        "conclusion": (
            "立讯精密是制造平台型公司，PB—ROE具有参考价值，但光模块能否改善集团估值，"
            "取决于项目利润率、资产周转和自由现金流，而不是只有收入规模。"
        ),
        "operating_analysis": (
            "冻结模型预计2026—2028年归母净利润210/260/310亿元，Wind一致预期为"
            "216.6/278.4/344.7亿元，差距仅3%—10%，集团盈利并不存在重大预测分歧。"
            "真正需要额外验证的是光模块项目的客户资格、重复订单、项目净利率和现金占用；"
            "即使业务进入量产，若只是低毛利配套，也可能增加收入却不改善集团ROA。"
        ),
        "valuation_analysis": (
            "估值日市值4570亿元、滚动PE 26.55倍、PB 4.16倍，ROE 19.37%而ROA仅"
            "6.35%。按独立2026年利润计算约21.8倍PE、按2028年利润约14.7倍，当前"
            "59.16元处在五年月度PE估值带约50.1—71.9元的中段。PB—ROE适合作为制造"
            "平台参考，但ROE与ROA差距表明杠杆和资产周转非常重要；缺少FY1—FY3自由现金流"
            "桥时，不把PB低分位自动解释为便宜。"
        ),
        "buy_point_analysis": (
            "50—59元可作为有条件观察区：集团2026年利润需接近210亿元以上，经营现金流和"
            "资本开支改善，同时光模块出现正式客户资格、重复订单和可验证利润率。若只有产品"
            "页面或小批量消息，没有现金回报证据，不应为光模块另付估值溢价。"
        ),
        "sell_point_analysis": (
            "接近或超过约72元时，需要集团ROA上升、自由现金流改善及光模块项目回报高于资本"
            "成本共同支撑；若仍是低毛利配套、营运资金扩张或客户复购不成立，应减仓或回避。"
            "跌破50元后也要先检查主业盈利是否被下修，不能机械按历史分位补仓。"
        ),
        "difference_causes": [
            "集团一致预期包含消费电子、汽车和通信等多业务，不能当作光模块分部预测",
            "潜在光模块收入较集团体量仍小，短期资本开支和营运资金可能先于利润",
            "历史低PB只有在ROE和现金流质量不继续恶化时才有估值含义",
        ],
        "future_view": (
            "短期看正式客户资格、重复订单、专线良率和项目现金流；长期看光模块净利率"
            "能否稳定高于集团新增资本成本，并形成可持续全球客户关系。"
        ),
        "positive_trigger": (
            "全球客户复购、项目净利率稳定、资本开支回落且自由现金流转正时，"
            "光模块才可能为集团ROE和估值提供增量支撑。"
        ),
        "risk_trigger": (
            "若只有低毛利配套收入，新增资产和营运资金会抵消增长；PB即使处于历史低位，"
            "也不等于已经形成安全边际。"
        ),
    },
    "byd": {
        "conclusion": (
            "比亚迪是重资产、强资本开支且受汽车价格周期影响的制造企业，PB—ROE比单期PE"
            "更有参考意义；潜在光模块业务目前不足以单独改变集团价值判断。"
        ),
        "operating_analysis": (
            "冻结模型预计2026—2028年归母净利润400/480/560亿元，Wind一致预期为"
            "409.7/515.7/622.8亿元，差距仅2%—10%。集团价值主要由整车、电池和电子"
            "业务的销量、单车利润、资产周转和资本开支决定；目前光模块线索既不足以单列收入，"
            "也不足以改变三年利润路径。新增业务只有在客户复购和回报率高于集团资本成本后，"
            "才可能改善业务组合。"
        ),
        "valuation_analysis": (
            "估值日市值8349亿元、滚动PE 30.31倍、PB 3.60倍，ROE/ROA仅"
            "11.02%/3.71%。按独立2026年利润计算约20.9倍PE、按2028年利润约14.9倍；"
            "91.57元接近五年月度PE中位对应的96.2元，但低于PB估值带20%分位对应的"
            "112.9元。两种方法出现差异的原因是当前资产回报偏低：PB看似处在低位，若ROA"
            "不回升仍可能合理，因此PB—ROE必须与现金流和资产周转一起使用。"
        ),
        "buy_point_analysis": (
            "70—96元是更可解释的观察区，但买点成立需要汽车主业利润率止跌、经营现金流覆盖"
            "资本开支、ROA回升，并且2026年利润接近400亿元以上。光模块只有正式规格、"
            "客户资格、重复订单和项目回报均可核验后，才能作为额外上行而不是买入理由本身。"
        ),
        "sell_point_analysis": (
            "若股价升至约113元以上而ROE仍接近11%、ROA仍不足4%，或价格竞争继续压缩"
            "单车利润、资本开支和营运资金维持高位，应降低估值和仓位。跌向70元也不是自动"
            "买点：若独立利润路径被下修或自由现金流恶化，应先按基本面重新定价。"
        ),
        "difference_causes": [
            "集团盈利和估值主要由整车、电池及电子业务决定，光模块属于条件性增量",
            "汽车价格、产品结构、产能利用率和资本开支对ROE/ROA的影响远大于当前光模块线索",
            "历史低PB必须与未来ROE、资产周转和自由现金流改善共同验证",
        ],
        "future_view": (
            "短期看汽车主业利润率、现金流和资本开支，同时等待光模块正式规格、客户资格与重复订单；"
            "长期只有项目回报高于集团资本成本，光模块才会小幅改善业务组合。"
        ),
        "positive_trigger": (
            "主业利润率和自由现金流确认改善、ROE回升，同时估值处于历史估值带较低位置时，"
            "才构成更可靠的左侧观察区。"
        ),
        "risk_trigger": (
            "若价格竞争和资本投入继续压低ROA，即使PB处于历史低分位也可能合理；"
            "不能仅凭光模块传闻上调集团盈利或目标估值。"
        ),
    },
}


def _tushare_period_rows(
    snapshot: dict[str, Any],
    key: str,
    table: str,
) -> dict[str, dict[str, Any]]:
    rows = snapshot["securities"][key]["tushare"].get(table) or []
    selected: dict[str, dict[str, Any]] = {}
    for row in rows:
        end_date = str(row.get("end_date") or "")
        if len(end_date) != 8:
            continue
        current = selected.get(end_date)
        if current is None or str(row.get("ann_date") or "") > str(
            current.get("ann_date") or ""
        ):
            selected[end_date] = row
    return selected


def _wind_annual_record(
    history: dict[str, Any],
    key: str,
    report_date: str,
) -> dict[str, Any]:
    ticker = COMPANIES[key]["ticker"]
    records = history["annual"][report_date]["records"]
    return next(
        row for row in records if str(row.get("index") or "").upper() == ticker
    )


def _pb_records(history: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return [
        row
        for row in history["monthly_pb"][key]["records"]
        if row.get("pb_lf") is not None
    ]


def _history_observations(
    *,
    snapshot: dict[str, Any],
    history: dict[str, Any],
    snapshot_path: Path,
    history_path: Path,
    key: str,
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    announcement_sources = {
        **_tushare_period_rows(snapshot, key, "income_2023_2026"),
        **_tushare_period_rows(snapshot, key, "fina_indicator_2023_2026"),
    }
    annual_mapping = (
        ("revenue", "oper_rev", "亿元人民币", 1e8),
        ("net_income", "np_belongto_parcomsh", "亿元人民币", 1e8),
        ("operating_cash_flow", "net_cash_flows_oper_act", "亿元人民币", 1e8),
        ("capex", "cash_pay_acq_const_fiolta", "亿元人民币", 1e8),
        ("total_assets", "tot_assets", "亿元人民币", 1e8),
        ("total_equity", "tot_equity", "亿元人民币", 1e8),
        ("roe", "roe", "%", 1),
        ("roa", "roa2", "%", 1),
        ("gross_margin", "grossprofitmargin", "%", 1),
        ("net_margin", "netprofitmargin", "%", 1),
    )
    for report_date in history["request_scope"]["annual_report_dates"]:
        year = int(report_date[:4])
        record = _wind_annual_record(history, key, report_date)
        announcement = announcement_sources.get(report_date, {}).get("ann_date")
        announcement_iso = (
            f"{announcement[:4]}-{announcement[4:6]}-{announcement[6:8]}"
            if announcement and len(str(announcement)) == 8
            else None
        )
        period_end = f"{year}-12-31"
        for metric, field, unit, divisor in annual_mapping:
            value = record.get(field)
            if value is None:
                continue
            observations.append(
                _observation(
                    metric=metric,
                    value=float(value) / divisor,
                    unit=unit,
                    fiscal_year=year,
                    fiscal_period="FY",
                    fact_type="actual",
                    provider="wind",
                    raw_feature_name=f"Wind WSS.{field}",
                    formula=None,
                    source_snapshot_key="pb_return_history",
                    period_end=period_end,
                    announcement_date=announcement_iso,
                    frequency="annual",
                    input_refs=[
                        _artifact_ref(
                            history_path,
                            f"annual.{report_date}.{COMPANIES[key]['ticker']}.{field}",
                        )
                    ],
                )
            )
        assets = record.get("tot_assets")
        equity = record.get("tot_equity")
        if assets is not None and equity is not None:
            liabilities = (float(assets) - float(equity)) / 1e8
            debt_ratio = (
                (float(assets) - float(equity)) / float(assets) * 100
                if float(assets)
                else None
            )
            observations.append(
                _observation(
                    metric="total_liabilities",
                    value=liabilities,
                    unit="亿元人民币",
                    fiscal_year=year,
                    fiscal_period="FY",
                    fact_type="actual",
                    provider="internal_model",
                    raw_feature_name="Wind总资产减总权益推导总负债",
                    formula="总负债＝总资产－总权益",
                    source_snapshot_key="pb_return_history",
                    period_end=period_end,
                    announcement_date=announcement_iso,
                    frequency="annual",
                    input_refs=[
                        _artifact_ref(
                            history_path,
                            f"annual.{report_date}.{COMPANIES[key]['ticker']}.tot_assets",
                        ),
                        _artifact_ref(
                            history_path,
                            f"annual.{report_date}.{COMPANIES[key]['ticker']}.tot_equity",
                        ),
                    ],
                )
            )
            if debt_ratio is not None:
                observations.append(
                    _observation(
                        metric="debt_ratio",
                        value=debt_ratio,
                        unit="%",
                        fiscal_year=year,
                        fiscal_period="FY",
                        fact_type="actual",
                        provider="internal_model",
                        raw_feature_name="Wind总资产与总权益推导资产负债率",
                        formula="资产负债率＝（总资产－总权益）÷总资产",
                        source_snapshot_key="pb_return_history",
                        period_end=period_end,
                        announcement_date=announcement_iso,
                        frequency="annual",
                    )
                )
        ocf = record.get("net_cash_flows_oper_act")
        capex = record.get("cash_pay_acq_const_fiolta")
        if ocf is not None and capex is not None:
            observations.append(
                _observation(
                    metric="free_cash_flow",
                    value=(float(ocf) - float(capex)) / 1e8,
                    unit="亿元人民币",
                    fiscal_year=year,
                    fiscal_period="FY",
                    fact_type="actual",
                    provider="internal_model",
                    raw_feature_name="Wind经营现金流减购建长期资产现金支出",
                    formula="简化自由现金流＝经营现金流－购建固定资产、无形资产及其他长期资产支付的现金",
                    source_snapshot_key="pb_return_history",
                    period_end=period_end,
                    announcement_date=announcement_iso,
                    frequency="annual",
                )
            )

    balance_rows = _tushare_period_rows(snapshot, key, "balancesheet_2023_2026")
    for report_date, row in balance_rows.items():
        if not report_date.endswith("1231"):
            continue
        value = row.get("total_hldr_eqy_exc_min_int")
        if value is None:
            continue
        year = int(report_date[:4])
        announcement = str(row.get("ann_date") or "")
        observations.append(
            _observation(
                metric="book_value",
                value=float(value) / 1e8,
                unit="亿元人民币",
                fiscal_year=year,
                fiscal_period="FY",
                fact_type="actual",
                provider="tushare",
                raw_feature_name="balancesheet.total_hldr_eqy_exc_min_int",
                formula=None,
                source_snapshot_key="tushare_snapshot",
                period_end=f"{year}-12-31",
                announcement_date=(
                    f"{announcement[:4]}-{announcement[4:6]}-{announcement[6:8]}"
                    if len(announcement) == 8
                    else None
                ),
                frequency="annual",
                input_refs=[
                    _artifact_ref(
                        snapshot_path,
                        f"securities.{key}.tushare.balancesheet_2023_2026.{year}."
                        "total_hldr_eqy_exc_min_int",
                    )
                ],
            )
        )
    for row in _pb_records(history, key):
        observed = str(row["index"])[:10]
        observations.append(
            _observation(
                metric="pb",
                value=float(row["pb_lf"]),
                unit="倍",
                fiscal_year=None,
                fiscal_period=None,
                fact_type="market",
                provider="wind",
                raw_feature_name="Wind WSD.pb_lf",
                formula=None,
                source_snapshot_key="pb_return_history",
                scenario_name="reported",
                currency=None,
                frequency="monthly",
                as_of_date=observed,
                input_refs=[
                    _artifact_ref(
                        history_path,
                        f"monthly_pb.{key}.{observed}.pb_lf",
                    )
                ],
            )
        )
    return observations


def _pb_return_model(
    independent: dict[str, Any],
    reconciliation: dict[str, Any],
    snapshot: dict[str, Any],
    history: dict[str, Any],
    independent_path: Path,
    reconciliation_path: Path,
    snapshot_path: Path,
    history_path: Path,
    key: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    company = COMPANIES[key]
    diagnostic = reconciliation["pb_roe_pb_roa_diagnostics"][key]
    current = diagnostic["current"]
    run_key = f"ol13:{company['ticker']}:pb_return_framework:v9"
    balance_rows = _tushare_period_rows(snapshot, key, "balancesheet_2023_2026")
    opening_row = balance_rows["20251231"]
    opening_book_value = float(
        opening_row["total_hldr_eqy_exc_min_int"]
    ) / 1e8
    baseline = _baseline_rows(independent, key)[:3]
    profit_path = [
        float(
            row.get(
                "net_income_cny_100m",
                row.get("parent_net_income_cny_100m"),
            )
        )
        for row in baseline
    ]
    retention_path = [
        float(row["retention_assumption_pct"]) / 100
        for row in diagnostic["static_market_cap_retained_earnings_bridge"]
    ]
    payout_path = [1 - value for value in retention_path]
    bridge = book_value_profit_bridge(
        opening_book_value=opening_book_value,
        net_income_path=profit_path,
        payout_path=payout_path,
    )
    history_rows = _pb_records(history, key)
    history_values = [float(row["pb_lf"]) for row in history_rows]
    # Use the exact final WSD observation for percentile calculations.  The
    # market snapshot is rounded to two decimals for display and can otherwise
    # move a near-boundary rank by one observation.
    current_pb = float(history_rows[-1]["pb_lf"])
    scenario_pb = round(current_pb, 2)
    band = historical_pb_band(history_values, current_pb=current_pb)
    decomposition = pb_double_click_decomposition(
        opening_book_value=opening_book_value,
        ending_book_value=float(bridge["ending_book_value"]),
        current_pb=scenario_pb,
        target_pb=scenario_pb,
    )
    framework = PB_FRAMEWORK[key]
    detailed_available = key in {"innolight", "eoptolink"}
    simple_defaults = {
        "opening_book_value_cny_100m": round(opening_book_value, 4),
        "current_pb": scenario_pb,
        "target_pb": scenario_pb,
        "target_pb_basis": "默认保持估值日PB不变；历史分位只作为可选情景，不自动视为合理价值。",
        "years": [
            {
                "fiscal_year": int(row["year"]),
                "net_income_cny_100m": round(profit, 4),
                "payout_ratio_pct": round(payout * 100, 2),
                "source_type": "冻结内部预测",
            }
            for row, profit, payout in zip(baseline, profit_path, payout_path)
        ],
        "pb_presets": {
            "historical_q20": round(float(band["q20"]), 4),
            "historical_median": round(float(band["median"]), 4),
            "historical_q80": round(float(band["q80"]), 4),
            "current": scenario_pb,
        },
    }
    inputs = [
        _input(
            "当前市净率",
            value=current_pb,
            unit="倍",
            period=AS_OF_DATE,
            source_ref=_artifact_ref(
                reconciliation_path, f"pb_roe_pb_roa_diagnostics.{key}.current.pb"
            ),
            input_type="external_consensus",
            method="Wind估值日PB。",
        ),
        _input(
            "当前TTM净资产收益率",
            value=float(current["roe_ttm_pct"]),
            unit="%",
            period=AS_OF_DATE,
            source_ref=_artifact_ref(
                reconciliation_path, f"pb_roe_pb_roa_diagnostics.{key}.current.roe_ttm_pct"
            ),
            input_type="direct_fact",
            method="Wind估值日可见TTM ROE。",
        ),
        _input(
            "当前TTM总资产收益率",
            value=float(current["roa_ttm_pct"]),
            unit="%",
            period=AS_OF_DATE,
            source_ref=_artifact_ref(
                reconciliation_path, f"pb_roe_pb_roa_diagnostics.{key}.current.roa_ttm_pct"
            ),
            input_type="direct_fact",
            method="Wind估值日可见TTM ROA。",
        ),
        _input(
            "2025年权益乘数",
            value=float(current["equity_multiplier_2025"]),
            unit="倍",
            period="2025",
            source_ref=_artifact_ref(
                reconciliation_path,
                f"pb_roe_pb_roa_diagnostics.{key}.current.equity_multiplier_2025",
            ),
            input_type="derived_fact",
            method="2025年总资产÷归母权益。",
            limitation="仅用于判断ROE来自资产效率还是杠杆，不外推FY1—FY3 ROA。",
        ),
        _input(
            "2025年末归母净资产",
            value=opening_book_value,
            unit="亿元人民币",
            period="2025",
            source_ref=_artifact_ref(
                snapshot_path,
                f"securities.{key}.tushare.balancesheet_2023_2026.2025."
                "total_hldr_eqy_exc_min_int",
            ),
            input_type="direct_fact",
            method="Tushare资产负债表归母权益；Wind总权益包含不同口径，二者不混写。",
        ),
    ]
    outputs = [
        _output(
            "当前PB",
            float(current["pb"]),
            unit="倍",
            period=AS_OF_DATE,
            formula="股价÷每股净资产",
            substitution=f"{float(current['pb']):.2f}倍",
            dependency="当前资本回报诊断",
            conclusion="当前PB需与ROE、ROA和杠杆共同解释。",
        ),
        _output(
            "当前TTM ROE",
            float(current["roe_ttm_pct"]),
            unit="%",
            period=AS_OF_DATE,
            formula="归母净利润÷平均归母权益",
            substitution=f"{float(current['roe_ttm_pct']):.2f}%",
            dependency="当前资本回报诊断",
            conclusion="ROE并非独立估值结论。",
        ),
        _output(
            "当前TTM ROA",
            float(current["roa_ttm_pct"]),
            unit="%",
            period=AS_OF_DATE,
            formula="净利润÷平均总资产",
            substitution=f"{float(current['roa_ttm_pct']):.2f}%",
            dependency="当前资本回报诊断",
            conclusion="ROA用于识别高ROE是否主要来自资产效率。",
        ),
    ]
    observations: list[dict[str, Any]] = []
    for baseline_row, bridge_row, retention in zip(
        baseline, bridge["path"], retention_path
    ):
        year = int(baseline_row["year"])
        internal_profit = float(bridge_row["net_income"])
        inputs.extend(
            [
                _input(
                    f"{year}年冻结内部归母净利润",
                    value=internal_profit,
                    unit="亿元人民币",
                    period=str(year),
                    source_ref=_artifact_ref(
                        independent_path,
                        f"baseline.{key}.{year}.net_income",
                    ),
                    input_type="derived_fact",
                    method="Run13在读取一致预期前冻结的FY1—FY3独立盈利路径。",
                ),
                _input(
                    f"{year}年利润留存率假设",
                    value=retention * 100,
                    unit="%",
                    period=str(year),
                    source_ref=_artifact_ref(
                        reconciliation_path,
                        f"pb_roe_pb_roa_diagnostics.{key}.bridge.{year}.retention",
                    ),
                    input_type="expert_assumption",
                    method="Run13留存收益诊断假设。",
                    sensitivity="留存率越高，固定市值下未来PB下降越快。",
                ),
            ]
        )
        projected_roe = float(bridge_row["roe"]) * 100
        book_value = float(bridge_row["closing_book_value"])
        outputs.append(
            _output(
                f"{year}年冻结内部路径ROE",
                projected_roe,
                unit="%",
                period=str(year),
                formula="归母净利润÷期初与期末归母净资产平均值",
                substitution=(
                    f"{internal_profit:.2f}÷"
                    f"{float(bridge_row['average_book_value']):.2f}"
                    f"＝{projected_roe:.2f}%"
                ),
                dependency="简化净资产桥",
                conclusion="该ROE来自冻结内部盈利路径和显式留存率，不等同于Wind一致预期。",
            )
        )
        outputs.append(
            _output(
                f"{year}年末归母净资产",
                book_value,
                unit="亿元人民币",
                period=str(year),
                formula="期初归母净资产＋归母净利润－分红－回购＋增发及其他权益变动",
                substitution=(
                    f"{float(bridge_row['opening_book_value']):.2f}＋"
                    f"{internal_profit:.2f}－{float(bridge_row['dividend']):.2f}"
                    f"＝{book_value:.2f}亿元"
                ),
                dependency="简化净资产桥",
                conclusion="缺少回购、增发与其他综合收益预测时暂按零处理，详细模式必须另补。",
            )
        )
        observations.extend(
            [
                _observation(
                    metric="roe",
                    value=projected_roe,
                    unit="%",
                    fiscal_year=year,
                    fiscal_period=f"FY{year - 2025}",
                    fact_type="internal_estimate",
                    provider="internal_model",
                    raw_feature_name="冻结内部盈利与净资产桥推导ROE",
                    formula="归母净利润÷期初与期末归母净资产平均值",
                    source_snapshot_key="independent_model",
                    model_run_key=run_key,
                    scenario_name="Run13简化净资产桥",
                    currency=None,
                ),
                _observation(
                    metric="book_value",
                    value=book_value,
                    unit="亿元人民币",
                    fiscal_year=year,
                    fiscal_period=f"FY{year - 2025}",
                    fact_type="internal_estimate",
                    provider="internal_model",
                    raw_feature_name="冻结内部盈利与留存率推导归母净资产",
                    formula="期初归母净资产＋归母净利润－分红－回购＋增发及其他权益变动",
                    source_snapshot_key="independent_model",
                    model_run_key=run_key,
                    scenario_name="Run13简化净资产桥",
                ),
            ]
        )
    outputs.extend(
        [
            _output(
                "五年月度PB中位数",
                float(band["median"]),
                unit="倍",
                period="2021-01至2026-07",
                formula="五年月末PB样本的中位数",
                substitution=f"{int(band['sample_size'])}个月末样本，中位数{float(band['median']):.2f}倍",
                dependency="历史PB区间",
                conclusion="历史位置只用于对照，不自动等同于合理PB。",
            ),
            _output(
                "保持当前PB的FY3情景市值",
                float(decomposition["target_market_value"]),
                unit="亿元人民币",
                period=str(int(baseline[-1]["year"])),
                formula="FY3归母净资产×估值日PB",
                substitution=(
                    f"{float(bridge['ending_book_value']):.2f}×{scenario_pb:.2f}"
                    f"＝{float(decomposition['target_market_value']):.2f}亿元"
                ),
                dependency="PB—ROE双击情景",
                conclusion="默认不假设PB扩张，全部变化来自冻结盈利留存带来的净资产增长。",
            ),
        ]
    )
    model = {
        "run_key": run_key,
        "supersedes_run_keys": [
            f"ol13:{company['ticker']}:pb_return_diagnostic:v4",
            f"ol13:{company['ticker']}:pb_return_framework:v5",
            f"ol13:{company['ticker']}:pb_return_framework:v6",
            f"ol13:{company['ticker']}:pb_return_framework:v7",
            f"ol13:{company['ticker']}:pb_return_framework:v8",
        ],
        "skill_name": "company_valuation_modeling",
        "model_name": "PB—ROE主线与ROA/现金流质量框架",
        "model_role": (
            "reference"
            if framework["applicability"] == "有效参考"
            else "diagnostic"
        ),
        "forecast_start": "2026",
        "forecast_end": "2028",
        "valuation_date": AS_OF_DATE,
        "assumptions": {
            "pb_framework": framework,
            "company_detail_summary": COMPANY_DETAIL_SUMMARIES[key],
            "historical_pb_band": band,
            "book_value_bridge": {
                "opening_book_value_cny_100m": opening_book_value,
                "ending_book_value_cny_100m": bridge["ending_book_value"],
                "book_value_growth_pct": bridge["book_value_growth"] * 100,
                "formula": bridge["formula"],
                "boundary": bridge["boundary"],
            },
            "double_click_default": decomposition,
            "scenario_workbench": {
                "simple_ready": True,
                "detailed_ready": False,
                "default_mode": "simple",
                "reason": (
                    "简化模式已有期初归母净资产、冻结FY1—FY3净利润、留存率和当前PB；"
                    "未来总资产、ROA、有息负债和完整三表路径不足，详细模式默认不作为正式结果。"
                ),
                "simple": simple_defaults,
                "detailed": {
                    "available_fields": (
                        ["内部经营现金流", "内部资本开支", "实际总资产", "实际ROA"]
                        if detailed_available
                        else ["实际总资产", "实际ROA"]
                    ),
                    "missing_required_fields": [
                        "FY1—FY3总资产或ROA路径",
                        "FY1—FY3有息负债与经营性负债拆分",
                        "完整回购、增发及其他权益变动",
                    ],
                    "manual_inputs_allowed": True,
                },
            },
        },
        "limitations": (
            framework["basis"]
            + " "
            + bridge["boundary"]
            + " "
            + diagnostic["roa_boundary"]
        ),
        "finalization": "reviewed",
        "inputs": inputs,
        "outputs": outputs,
    }
    return model, observations


def _cash_flow_model(
    independent: dict[str, Any],
    reconciliation: dict[str, Any],
    independent_path: Path,
    reconciliation_path: Path,
    key: str,
) -> dict[str, Any]:
    company = COMPANIES[key]
    grid = independent["independent_valuation_diagnostics"][key][
        "cash_flow_sensitivity_grid"
    ]["回报要求11%__长期增长3%"]
    baseline = independent["baseline"][key]
    market_cap = float(
        reconciliation["external_benchmarks"][key]["market"]["market_cap_cny_100m"]
    )
    run_key = f"ol13:{company['ticker']}:cash_flow_sensitivity:v4"
    inputs = []
    for row in baseline:
        inputs.append(
            _input(
                f"{row['year']}年独立自由现金流",
                value=float(row["free_cash_flow_cny_100m"]),
                unit="亿元人民币",
                period=str(row["year"]),
                source_ref=_artifact_ref(
                    independent_path, f"baseline.{key}.{row['year']}.free_cash_flow_cny_100m"
                ),
                input_type="derived_fact",
                method="归母净利润×现金转换率－资本开支。",
            )
        )
    for name, field, unit in (
        ("股权回报要求", "required_return_pct", "%"),
        ("长期增长率", "terminal_growth_pct", "%"),
        ("长期可持续ROE", "sustainable_roe_pct", "%"),
    ):
        inputs.append(
            _input(
                name,
                value=float(grid[field]),
                unit=unit,
                period="长期",
                source_ref=_artifact_ref(
                    independent_path, f"independent_valuation_diagnostics.{key}.{field}"
                ),
                input_type="expert_assumption",
                method="Run13现金流敏感性中档假设。",
                sensitivity="回报要求和长期增长率变化会显著改变终值。",
            )
        )
    value = float(grid["cash_flow_value_before_balance_sheet_bridge_cny_100m"])
    model = {
        "run_key": run_key,
        "skill_name": "company_valuation_modeling",
        "model_name": "股权现金流敏感性（未含资产负债桥）",
        "model_role": "reference",
        "forecast_start": "2026",
        "forecast_end": "2031",
        "valuation_date": AS_OF_DATE,
        "assumptions": {
            "required_return_pct": grid["required_return_pct"],
            "terminal_growth_pct": grid["terminal_growth_pct"],
            "sustainable_roe_pct": grid["sustainable_roe_pct"],
            "remaining_2026_fraction": grid["remaining_2026_fraction"],
        },
        "limitations": (
            "缺完整净现金、净举债、少数股东和三表桥，只能作为现金流敏感性，"
            "不能当作正式目标市值或目标价。"
        ),
        "finalization": "independent",
        "inputs": inputs,
        "outputs": [
            _output(
                "现金流价值（资产负债桥前）",
                value,
                unit="亿元人民币",
                period=AS_OF_DATE,
                formula="显性期自由现金流现值＋终值现值",
                substitution=(
                    f"{grid['pv_explicit_cash_flow_cny_100m']:.2f}＋"
                    f"{grid['pv_terminal_cny_100m']:.2f}＝{value:.2f}亿元"
                ),
                dependency="现金流敏感性",
                conclusion=f"终值占比{grid['terminal_share_pct']:.2f}%，结果对长期假设高度敏感。",
            )
        ],
        "reconciliations": [
            {
                "benchmark_type": "market_implied",
                "benchmark_source_ref": _artifact_ref(
                    reconciliation_path,
                    f"external_benchmarks.{key}.market.market_cap_cny_100m",
                ),
                "metric_name": "equity_value_before_balance_sheet_bridge",
                "period": AS_OF_DATE,
                "independent_value": value,
                "benchmark_value": market_cap,
                "unit": "亿元人民币",
                "decomposition": {
                    "market_cap_divided_by_cash_flow_sensitivity": market_cap / value
                },
                "conclusion": "市场市值显著高于未含资产负债桥的现金流敏感性值；该差异不能在缺净现金桥时直接解释为高估幅度。",
            }
        ],
    }
    return model


def build_export(run_dir: Path) -> dict[str, Any]:
    independent_path = run_dir / "independent_model_v4.json"
    reconciliation_path = run_dir / "external_reconciliation_v4.json"
    snapshot_path = run_dir / "financial_snapshot_v4.json"
    history_path = run_dir / "pb_return_history_v1.json"
    independent = json.loads(independent_path.read_text(encoding="utf-8"))
    reconciliation = json.loads(reconciliation_path.read_text(encoding="utf-8"))
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    history = json.loads(history_path.read_text(encoding="utf-8"))

    companies = []
    for key, company in COMPANIES.items():
        market = reconciliation["external_benchmarks"][key]["market"]
        consensus = reconciliation["external_benchmarks"][key]["consensus"]
        financial_model, internal_observations = _financial_model(
            independent, reconciliation, independent_path, reconciliation_path, key
        )
        reverse_model, reverse_observations = _reverse_pe_model(
            independent, reconciliation, independent_path, reconciliation_path, key
        )
        pb_model, pb_observations = _pb_return_model(
            independent,
            reconciliation,
            snapshot,
            history,
            independent_path,
            reconciliation_path,
            snapshot_path,
            history_path,
            key,
        )
        model_runs = [financial_model, reverse_model, pb_model]
        if key in {"innolight", "eoptolink"}:
            model_runs.append(
                _cash_flow_model(
                    independent, reconciliation, independent_path, reconciliation_path, key
                )
            )

        observations: list[dict[str, Any]] = []
        observations.extend(
            _history_observations(
                snapshot=snapshot,
                history=history,
                snapshot_path=snapshot_path,
                history_path=history_path,
                key=key,
            )
        )
        for source_field, (metric, unit, raw_feature) in MARKET_FIELDS.items():
            value = market.get(source_field)
            if value is not None:
                observations.append(
                    _observation(
                        metric=metric,
                        value=float(value),
                        unit=unit,
                        fiscal_year=None,
                        fiscal_period=None,
                        fact_type="market",
                        provider="wind",
                        raw_feature_name=raw_feature,
                        formula=None,
                        source_snapshot_key="wind_snapshot",
                        scenario_name="reported",
                        currency=None if unit == "倍" else "CNY",
                    )
                )
        for source_field, (metric, unit, raw_feature) in ACTUAL_SNAPSHOT_FIELDS.items():
            value = market.get(source_field)
            if value is not None:
                observations.append(
                    _observation(
                        metric=metric,
                        value=float(value),
                        unit=unit,
                        fiscal_year=None,
                        fiscal_period=None,
                        fact_type="actual",
                        provider="wind",
                        raw_feature_name=raw_feature,
                        formula=None,
                        source_snapshot_key="wind_snapshot",
                        scenario_name="reported",
                        currency="CNY" if "元/股" in unit else None,
                    )
                )
        for row in consensus["years"]:
            year = int(row["fiscal_year"])
            for metric, field, unit, raw_feature in (
                ("revenue", "revenue_cny_100m", "亿元人民币", "Wind WSS.west_sales_fy*"),
                (
                    "net_income",
                    "parent_net_income_cny_100m",
                    "亿元人民币",
                    "Wind WSS.west_netprofit_fy*",
                ),
                ("eps", "eps_cny", "元/股", "Wind WSS.west_eps_fy*"),
                ("roe", "average_roe_pct", "%", "Wind WSS.west_avgroe_fy*"),
            ):
                observations.append(
                    _observation(
                        metric=metric,
                        value=float(row[field]),
                        unit=unit,
                        fiscal_year=year,
                        fiscal_period=f"FY{year - 2025}",
                        fact_type="consensus",
                        provider="wind",
                        raw_feature_name=raw_feature,
                        formula=None,
                        source_snapshot_key="wind_snapshot",
                        scenario_name="Wind一致预期",
                        currency="CNY" if "元" in unit else None,
                    )
                )
        observations.extend(internal_observations)
        observations.extend(reverse_observations)
        observations.extend(pb_observations)
        companies.append(
            {
                "research_company_id": company["research_company_id"],
                "security": {
                    "canonical_name": company["canonical_name"],
                    "ticker": company["ticker"],
                    "market": "A股",
                    "listing_status": "a_share",
                    "reporting_currency": "CNY",
                    "identity_status": "verified",
                },
                "source_snapshots": [
                    {
                        "key": "wind_snapshot",
                        "provider": "wind",
                        "source_channel": "structured_api",
                        "source_ref": f"{RESEARCH_RUN_REF}:wind:{company['ticker']}",
                        "title": f"{company['canonical_name']} Wind市场与一致预期窄字段快照",
                        "publisher": "Wind",
                        "as_of_date": AS_OF_DATE,
                        "fetched_at": snapshot.get("accessed_at_utc"),
                        "content_hash": _sha256_file(snapshot_path),
                        "raw_snapshot_path": str(snapshot_path.relative_to(ROOT)),
                        "metadata": {
                            "scope": "单证券窄字段；来自Run13已完成取数，不触发新外部请求。",
                            "ticker": company["ticker"],
                        },
                    },
                    {
                        "key": "tushare_snapshot",
                        "provider": "tushare",
                        "source_channel": "structured_api",
                        "source_ref": f"{RESEARCH_RUN_REF}:tushare:{company['ticker']}",
                        "title": f"{company['canonical_name']} Tushare财务补缺与公告期快照",
                        "publisher": "Tushare",
                        "as_of_date": AS_OF_DATE,
                        "fetched_at": snapshot.get("accessed_at_utc"),
                        "content_hash": _sha256_file(snapshot_path),
                        "raw_snapshot_path": str(snapshot_path.relative_to(ROOT)),
                        "metadata": {
                            "scope": (
                                "只补充Wind当前集成没有提供的归母权益和公告期；"
                                "不覆盖同口径Wind非空值。"
                            ),
                            "ticker": company["ticker"],
                        },
                    },
                    {
                        "key": "pb_return_history",
                        "provider": "wind",
                        "source_channel": "structured_api",
                        "source_ref": (
                            f"{RESEARCH_RUN_REF}:wind_history:{company['ticker']}"
                        ),
                        "title": f"{company['canonical_name']} Wind五年财务与月度PB窄字段历史",
                        "publisher": "Wind",
                        "as_of_date": AS_OF_DATE,
                        "fetched_at": history.get("accessed_at_utc"),
                        "content_hash": _sha256_file(history_path),
                        "raw_snapshot_path": str(history_path.relative_to(ROOT)),
                        "metadata": {
                            "scope": history.get("request_scope"),
                            "interpretation_boundary": history.get(
                                "interpretation_boundary"
                            ),
                        },
                    },
                    {
                        "key": "independent_model",
                        "provider": "internal_model",
                        "source_channel": "internal_calculation",
                        "source_ref": (
                            f"{RESEARCH_RUN_REF}:independent_model:{company['ticker']}"
                        ),
                        "title": f"{company['canonical_name']} Run13冻结独立财务模型",
                        "publisher": "Industry Demo内部研究模型",
                        "as_of_date": AS_OF_DATE,
                        "fetched_at": independent.get("generated_at_utc"),
                        "content_hash": _sha256_file(independent_path),
                        "raw_snapshot_path": str(independent_path.relative_to(ROOT)),
                        "metadata": {
                            "frozen_before_external_consensus": independent.get(
                                "frozen_before_external_consensus"
                            ),
                            "content_sha256": independent.get("content_sha256"),
                        },
                    },
                    {
                        "key": "external_reconciliation",
                        "provider": "internal_model",
                        "source_channel": "internal_calculation",
                        "source_ref": (
                            f"{RESEARCH_RUN_REF}:external_reconciliation:{company['ticker']}"
                        ),
                        "title": f"{company['canonical_name']} Run13外部对账与反向估值",
                        "publisher": "Industry Demo内部研究模型",
                        "as_of_date": AS_OF_DATE,
                        "fetched_at": reconciliation.get("created_at_utc"),
                        "content_hash": _sha256_file(reconciliation_path),
                        "raw_snapshot_path": str(reconciliation_path.relative_to(ROOT)),
                        "metadata": {
                            "independent_model_file_sha256": reconciliation.get(
                                "independent_model_file_sha256"
                            ),
                            "sequence_control": reconciliation.get("sequence_control"),
                        },
                    },
                ],
                "model_runs": model_runs,
                "observations": observations,
            }
        )
    return {
        "export_schema_version": EXPORT_SCHEMA_VERSION,
        "research_run_ref": RESEARCH_RUN_REF,
        "as_of_date": AS_OF_DATE,
        "source_artifacts": [
            {
                "path": str(independent_path.relative_to(ROOT)),
                "sha256": _sha256_file(independent_path),
                "role": "冻结独立财务与情景模型",
            },
            {
                "path": str(reconciliation_path.relative_to(ROOT)),
                "sha256": _sha256_file(reconciliation_path),
                "role": "冻结后外部对账与反向估值",
            },
            {
                "path": str(snapshot_path.relative_to(ROOT)),
                "sha256": _sha256_file(snapshot_path),
                "role": "Wind市场与一致预期窄字段快照",
            },
            {
                "path": str(history_path.relative_to(ROOT)),
                "sha256": _sha256_file(history_path),
                "role": "Wind五年财务与月度PB窄字段历史",
            },
        ],
        "companies": companies,
        "generation_note": (
            "转换Run13已冻结模型、已完成Wind窄字段快照、五年月度PB历史和外部对账；"
            "PB历史总请求仅四只证券472个预计观测，不生成正式目标价。"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="构建Run13公司财务画像标准导出")
    parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    run_dir = Path(args.run_dir).resolve()
    output = Path(args.output).resolve()
    payload = build_export(run_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "company_count": len(payload["companies"]),
                "model_run_count": sum(
                    len(company["model_runs"]) for company in payload["companies"]
                ),
                "observation_count": sum(
                    len(company["observations"]) for company in payload["companies"]
                ),
                "sha256": _sha256_file(output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
