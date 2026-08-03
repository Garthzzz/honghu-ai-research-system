"""Compile the deployable three-company copper calculator model.

The compiler combines:

* researcher-supplied, recalculated Zijin/CMOC/MMG workbooks;
* the independently frozen copper operating model;
* the post-freeze external reconciliation ledger; and
* current official project disclosures used to update commissioning paths.

It writes only a versioned JSON configuration.  It does not write any project
database and it does not call Wind, Tushare or another external provider.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = (
    ROOT
    / "config"
    / "copper_calculator_models"
    / "workbook_recalculation_snapshot_v1.json"
)
INDEPENDENT = (
    ROOT / "cache" / "copper_research" / "models" / "copper_independent_models_v2.json"
)
RECONCILIATION = (
    ROOT / "cache" / "copper_research" / "models" / "copper_external_reconciliation_v2.json"
)
DEFAULT_OUTPUT = (
    ROOT
    / "config"
    / "copper_calculator_models"
    / "copper_calculator_model_v1.json"
)
YEARS = (2025, 2026, 2027, 2028)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _stable_hash(value: Any) -> str:
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _row(table: dict[str, Any], *needles: str) -> dict[str, Any]:
    for row in table.get("rows") or []:
        metric = str(row.get("metric") or "")
        if all(needle in metric for needle in needles):
            return row
    raise KeyError(f"未在工作簿表格中找到指标: {needles}")


def _annual(table: dict[str, Any], year: int, *needles: str) -> float:
    value = (_row(table, *needles).get("values") or {}).get(str(year))
    if value is None:
        raise ValueError(f"{needles} {year} 为空")
    return float(value)


def _annual_optional(table: dict[str, Any], year: int, *needles: str) -> float | None:
    try:
        value = (_row(table, *needles).get("values") or {}).get(str(year))
    except KeyError:
        return None
    return float(value) if isinstance(value, (int, float)) else None


def _dcf_value(snapshot: dict[str, Any], *needles: str) -> float | None:
    for row in (snapshot.get("dcf") or {}).get("summary") or []:
        metric = str(row.get("metric") or "")
        if all(needle in metric for needle in needles):
            value = row.get("value")
            return float(value) if isinstance(value, (int, float)) else None
    return None


def _project(
    name: str,
    region: str,
    ownership: float,
    production: Iterable[float],
    c1: Iterable[float],
    status: str,
    note: str,
    *,
    evidence_level: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "region": region,
        "enabled": True,
        "ownershipPct": ownership,
        "status": status,
        "productionKt": {
            str(year): float(value)
            for year, value in zip(YEARS, production, strict=True)
        },
        "c1UsdLb": {
            str(year): float(value)
            for year, value in zip(YEARS, c1, strict=True)
        },
        "incrementalCapex": {str(year): 0.0 for year in YEARS},
        "note": note,
        "evidenceLevel": evidence_level,
    }


def _workbook_financials(snapshot: dict[str, Any], company: str) -> dict[str, Any]:
    company_snapshot = snapshot["companies"][company]
    tables = company_snapshot["tables"]
    income = tables["Income Statement"]
    cash = tables["Cash Flow"]
    financials: dict[str, Any] = {}
    cash_metric_by_company = {
        "紫金矿业": {
            "fcf": ("自由现金流",),
            "dividend": ("分配股利",),
        },
        "洛阳钼业": {
            "fcf": ("FCF",),
            "dividend": ("分红",),
        },
        "五矿资源": {
            "fcf": ("FCF",),
            "dividend": ("分红支付",),
        },
    }
    metric_names = cash_metric_by_company[company]
    for year in YEARS:
        financials[str(year)] = {
            "revenue": _annual(income, year, "营业总收入"),
            "netIncome": _annual(income, year, "归母净利润"),
            "ocf": _annual(cash, year, "经营活动现金流净额"),
            "capex": abs(_annual(cash, year, "资本开支")),
            "fcf": _annual(cash, year, *metric_names["fcf"]),
            "dividend": (
                abs(dividend)
                if (
                    dividend := _annual_optional(
                        cash, year, *metric_names["dividend"]
                    )
                )
                is not None
                else None
            ),
            "buyback": 0.0,
        }
    return financials


def _convert_valuation(
    valuation: dict[str, Any], factor: float, *, overseas: bool
) -> list[dict[str, Any]]:
    pe = valuation["normalized_pe"]
    pb = valuation["pb_roe"]
    dcf = valuation["fcfe_dcf"]
    return [
        {
            "method": "正常化市盈率",
            "role": "核心参考",
            "low": float(
                pe[
                    "equity_value_low_usd_bn"
                    if overseas else "equity_value_low_rmb_bn"
                ]
            ) * factor,
            "high": float(
                pe[
                    "equity_value_high_usd_bn"
                    if overseas else "equity_value_high_rmb_bn"
                ]
            ) * factor,
            "calculation": {
                "kind": "multiple",
                "driver": "netIncome",
                "forecastYear": valuation["normalized_year"],
                "basisLabel": "情景归母净利润",
                "parameterLabel": "PE（倍）",
                "lowParameter": float(pe["multiple_low"]),
                "highParameter": float(pe["multiple_high"]),
                "formula": "股权价值＝情景归母净利润×目标PE",
            },
            "note": str(pe["parameter_basis"]),
        },
        {
            "method": "PB—ROE",
            "role": "诊断",
            "low": float(
                pb[
                    "equity_value_low_usd_bn"
                    if overseas else "equity_value_low_rmb_bn"
                ]
            ) * factor,
            "high": float(
                pb[
                    "equity_value_high_usd_bn"
                    if overseas else "equity_value_high_rmb_bn"
                ]
            ) * factor,
            "calculation": {
                "kind": "multiple",
                "driver": "equity",
                "forecastYear": valuation["normalized_year"],
                "basisLabel": "期末归母净资产",
                "parameterLabel": "PB（倍）",
                "lowParameter": float(pb["adopted_pb_low"]),
                "highParameter": float(pb["adopted_pb_high"]),
                "formula": (
                    "合理PB＝（可持续ROE－长期增长率）÷"
                    "（股权成本－长期增长率）；股权价值＝期末归母净资产×PB"
                ),
            },
            "note": str(pb["parameter_basis"]),
        },
        {
            "method": "股权现金流折现",
            "role": "诊断",
            "low": float(dcf["equity_value_low"]) * factor,
            "high": float(dcf["equity_value_high"]) * factor,
            "calculation": {
                "kind": "fcfe_dcf",
                "forecastYears": [2026, 2027, 2028],
                "basisLabel": "2026—2028情景自由现金流",
                "formula": (
                    "股权价值＝Σ[FCFEt÷(1＋Ke)^t]＋"
                    "FCFE2028×(1＋g)÷(Ke－g)÷(1＋Ke)^3"
                ),
                "lowValue": {
                    "costOfEquityPct": (
                        float(dcf["low_value_assumptions"]["cost_of_equity"]) * 100
                    ),
                    "terminalGrowthPct": (
                        float(dcf["low_value_assumptions"]["terminal_growth"]) * 100
                    ),
                },
                "highValue": {
                    "costOfEquityPct": (
                        float(dcf["high_value_assumptions"]["cost_of_equity"]) * 100
                    ),
                    "terminalGrowthPct": (
                        float(dcf["high_value_assumptions"]["terminal_growth"]) * 100
                    ),
                },
            },
            "note": str(dcf["parameter_basis"]),
        },
    ]


def compile_model(
    snapshot_path: Path = SNAPSHOT,
    independent_path: Path = INDEPENDENT,
    reconciliation_path: Path = RECONCILIATION,
) -> dict[str, Any]:
    snapshot = _load(snapshot_path)
    independent = _load(independent_path)
    reconciliation = _load(reconciliation_path)
    independent_by_name = {
        row["company"]: row for row in independent["outputs"]["companies"]
    }
    recon_by_name = reconciliation["companies"]

    zijin_projects = [
        _project(
            "Kamoa—Kakula",
            "刚果（金）",
            44.2,
            (388.838, 310.0, 400.0, 500.0),
            (2.20, 2.80, 2.30, 2.00),
            "2026—2027先修复井下开发，2028年目标恢复至年化50万吨以上",
            "2025为项目100%产量；2026—2028采用2026年3月更新后的官方中值/目标，较旧模型下调2026并上调2027—2028。",
            evidence_level="官方指引",
        ),
        _project(
            "Serbia Zijin Mining",
            "塞尔维亚",
            100.0,
            (172.307, 175.0, 190.0, 210.0),
            (2.09, 2.09, 2.04, 2.00),
            "在产；下部矿带块崩法准备推进",
            "2026—2028为独立模型拆分值；公司仅披露塞尔维亚基地扩产方向，未逐矿给出完整年度产量。",
            evidence_level="官方实际值＋研究假设",
        ),
        _project(
            "Serbia Zijin Copper",
            "塞尔维亚",
            63.0,
            (123.286, 125.0, 150.0, 160.0),
            (2.09, 2.09, 2.04, 2.00),
            "JM矿技改力争2027年6月建成，矿产铜目标15—16万吨/年",
            "2027—2028按公司披露的技改能力目标；投产节奏和爬坡可在网页中调整。",
            evidence_level="官方项目计划",
        ),
        _project(
            "巨龙铜矿",
            "中国西藏",
            58.16,
            (193.820, 300.0, 330.0, 350.0),
            (2.09, 2.09, 2.04, 2.00),
            "二期已于2026年1月投产，随后爬坡；三期处于准备阶段",
            "一期＋二期官方目标为30—35万吨/年；2027—2028取区间内爬坡路径。",
            evidence_level="官方投产与产能",
        ),
        _project(
            "科卢韦齐铜矿",
            "刚果（金）",
            67.0,
            (118.019, 109.0, 112.0, 115.0),
            (2.09, 2.09, 2.04, 2.00),
            "在产",
            "未来产量为独立模型路径，不代表公司逐年指引。",
            evidence_level="官方实际值＋研究假设",
        ),
        _project(
            "其他在产铜矿组合",
            "中国及海外",
            100.0,
            (304.269, 280.0, 295.0, 305.0),
            (2.09, 2.09, 2.04, 2.00),
            "在产组合",
            "承接多宝山、紫金山、阿舍勒、碧沙、珲春等项目；用权益口径组合值避免把每座矿缺失的成本伪装成精确数据。",
            evidence_level="官方实际值汇总＋研究假设",
        ),
        _project(
            "朱诺/雄村等新项目组合",
            "中国西藏",
            100.0,
            (0.0, 0.0, 0.0, 70.0),
            (2.09, 2.09, 2.04, 2.00),
            "朱诺与谢通门推进建设；2028年增量为模型代理",
            "公司未披露完全可复核的逐年权益产量，70千吨仅是独立模型中的项目组合爬坡假设。",
            evidence_level="官方建设进展＋研究假设",
        ),
    ]

    cmoc_projects = [
        _project(
            "TFM铜钴矿",
            "刚果（金）",
            80.0,
            (560.0, 590.0, 590.0, 640.0),
            (2.15, 2.15, 2.04, 2.00),
            "混合矿项目达产；西区与三期扩建准备推进",
            "TFM与KFM的年度拆分并未完整公开；在公司总产量约束下按现有能力和扩建节奏拆分。",
            evidence_level="公司总量指引＋研究拆分",
        ),
        _project(
            "KFM铜钴矿",
            "刚果（金）",
            71.25,
            (181.149, 200.0, 300.0, 320.0),
            (2.15, 2.15, 2.04, 2.00),
            "二期预计2027年投产，新增铜产能约10万吨/年",
            "2027增量来自官方KFM二期计划；2026与2028为总量目标下的研究拆分。",
            evidence_level="官方扩建计划＋研究拆分",
        ),
    ]

    mmg_projects = [
        _project(
            "Las Bambas",
            "秘鲁",
            62.5,
            (410.834, 390.0, 400.0, 410.0),
            (1.12, 1.30, 1.25, 1.25),
            "在产；2026指引38—40万吨，Chalcobamba逐步纳入",
            "2026取官方指引中值；2027—2028为稳定运营假设，社区与运输连续性仍是主要风险。",
            evidence_level="官方指引＋研究假设",
        ),
        _project(
            "Kinsevere",
            "刚果（金）",
            100.0,
            (52.791, 70.0, 72.0, 75.0),
            (3.12, 2.70, 2.55, 2.45),
            "扩建项目爬坡；电力稳定性仍限制电积系统",
            "2026取官方6.5—7.5万吨中值；后续为稳定运行与成本改善假设。",
            evidence_level="官方指引＋研究假设",
        ),
        _project(
            "Khoemacau",
            "博茨瓦纳",
            55.0,
            (42.120, 50.5, 65.0, 105.0),
            (1.97, 2.15, 1.75, 1.60),
            "扩建至13万吨/年；计划2028年上半年产出首批精矿",
            "2026取官方4.8—5.3万吨中值；2028按扩建首年爬坡而非直接按满产。",
            evidence_level="官方指引与扩建计划",
        ),
    ]

    sources = {
        "紫金矿业": [
            {
                "title": "紫金矿业2025年度业绩与主要铜矿表",
                "url": "https://www.zijinmining.com/investor/2025-newyeji.htm",
                "date": "2026-03-22",
            },
            {
                "title": "紫金矿业2026—2028主要矿产品产量规划",
                "url": "https://www.zijinmining.com/upload/file/2026/02/09/c08d3f959bdd4800a9c30c15e6afaab5.pdf",
                "date": "2026-02-09",
            },
            {
                "title": "Kamoa—Kakula 2026—2028更新矿山计划",
                "url": "https://www.ivanhoemines.com/news-stories/news-release/ivanhoe-mines-announces-updated-independent-study-results-for-the-kamoa-kakula-copper-complex/",
                "date": "2026-03-31",
            },
            {
                "title": "紫金矿业A股回购计划",
                "url": "https://www.zijinmining.com/upload/file/2026/03/23/4c2089e26ceb40f380e5b40b8dba1759.pdf",
                "date": "2026-03-23",
            },
        ],
        "洛阳钼业": [
            {
                "title": "洛阳钼业2025年度业绩",
                "url": "https://www.cmoc.com/html/2026/News_0327/398.html",
                "date": "2026-03-27",
            },
            {
                "title": "洛阳钼业2025年度业绩演示",
                "url": "https://en.cmoc.com/uploadfile/attachment/2025Annual20260331209019313.pdf",
                "date": "2026-03-31",
            },
            {
                "title": "洛阳钼业KFM二期与2028年铜产量目标",
                "url": "https://en.cmoc.com/html/2026/News_0420/84.html",
                "date": "2026-04-20",
            },
        ],
        "五矿资源": [
            {
                "title": "五矿资源2025年度报告",
                "url": "https://www.mmg.com/wp-content/uploads/2026/04/e_2026-04-21_2025-Annual-Report-1.pdf",
                "date": "2026-04-21",
            },
            {
                "title": "五矿资源2025年第四季度生产报告与2026指引",
                "url": "https://www.mmg.com/wp-content/uploads/2026/01/e_2026-01-22_4QTR-Production-Report.pdf",
                "date": "2026-01-22",
            },
            {
                "title": "五矿资源2026年第一季度生产更新",
                "url": "https://www.mmg.com/investors/reports-and-presentations/strong-q1-production-results-deliver-a-positive-start-to-2026/",
                "date": "2026-04-21",
            },
        ],
    }

    companies: list[dict[str, Any]] = []
    for name, company_id, ticker, currency, amount_unit, projects in [
        ("紫金矿业", 635, "601899.SH", "CNY", "亿元", zijin_projects),
        ("洛阳钼业", 634, "603993.SH", "CNY", "亿元", cmoc_projects),
        ("五矿资源", 636, "1208.HK", "USD", "亿美元", mmg_projects),
    ]:
        frozen = independent_by_name[name]
        recon = recon_by_name[name]
        factor = 10.0
        financials = _workbook_financials(snapshot, name)
        workbook_snapshot = snapshot["companies"][name]
        workbook_dcf = _dcf_value(workbook_snapshot, "股权价值")
        workbook_tables = workbook_snapshot["tables"]
        actual = frozen["actual_2025"]
        if name != "五矿资源":
            financials["2025"]["equity"] = (
                actual["parent_equity_rmb_bn"] * factor
            )
            base_scenario = list(frozen["scenarios"].values())[1]
            for row in base_scenario:
                year = str(row["year"])
                financials[year] = {
                    "revenue": row["revenue_rmb_bn"] * factor,
                    "netIncome": row["attributable_net_income_rmb_bn"] * factor,
                    "ocf": (row["fcfe_rmb_bn"] + row["capex_rmb_bn"]) * factor,
                    "capex": row["capex_rmb_bn"] * factor,
                    "fcf": row["fcfe_rmb_bn"] * factor,
                    "equity": row["ending_parent_equity_rmb_bn"] * factor,
                    "dividend": 0.0,
                    "buyback": (
                        20.0 if name == "紫金矿业" and year == "2026" else 0.0
                    ),
                }
        else:
            financials["2025"]["equity"] = actual["parent_equity_usd_bn"] * factor
            base_scenario = list(frozen["scenarios"].values())[1]
            for row in base_scenario:
                year = str(row["year"])
                financials[year] = {
                    "revenue": row["revenue_usd_bn"] * factor,
                    "netIncome": row["attributable_net_income_usd_bn"] * factor,
                    "ocf": (row["fcfe_usd_bn"] + row["capex_usd_bn"]) * factor,
                    "capex": row["capex_usd_bn"] * factor,
                    "fcf": row["fcfe_usd_bn"] * factor,
                    "equity": row["ending_parent_equity_usd_bn"] * factor,
                    "dividend": 0.0,
                    "buyback": 0.0,
                }
            # MMG工作簿的DCF股权价值单位为百万美元；计算器统一使用亿美元。
            if workbook_dcf is not None:
                workbook_dcf /= 100.0
        valuation = deepcopy(frozen["valuation"])
        valuation_rows = _convert_valuation(
            valuation, factor, overseas=name == "五矿资源"
        )
        if workbook_dcf is not None:
            valuation_rows.append(
                {
                    "method": "参考工作簿DCF",
                    "role": "差异诊断",
                    "low": workbook_dcf,
                    "high": workbook_dcf,
                    "calculation": {
                        "kind": "frozen",
                        "basisLabel": "参考工作簿冻结结果",
                        "formula": "按参考工作簿原有DCF公式与完整预测期计算",
                    },
                    "note": (
                        "完整还原研究员工作簿的结果；因盈利和终值假设明显高于独立模型，"
                        "单独列示而不与其他方法机械平均。"
                    ),
                }
            )
        market_value = (
            recon["valuation_vs_market"]["current_market_cap_bn"] * 10.0
            if name != "五矿资源"
            else recon["valuation_vs_market"]["current_market_cap_usd_bn_proxy"] * 10.0
        )
        companies.append(
            {
                "companyId": company_id,
                "name": name,
                "ticker": ticker,
                "currency": currency,
                "amountUnit": amount_unit,
                "years": list(YEARS),
                "asOfDate": "2026-07-27",
                "currentMarketValue": market_value,
                "fxUsdCny": 7.15,
                "afterTaxConversion": float(
                    frozen["critical_inputs"]["after_tax_conversion"]
                ),
                "incrementalCashConversion": (
                    1.05 if name == "紫金矿业"
                    else (1.00 if name == "洛阳钼业" else 1.20)
                ),
                "payoutRatio": 35.0 if name != "五矿资源" else 0.0,
                "dividendLagYears": 0 if name == "紫金矿业" else 1,
                "projects": projects,
                "financials": financials,
                "valuationMethods": valuation_rows,
                "workbookTables": workbook_tables,
                "independentModel": {
                    "method": frozen["model_method"],
                    "baseScenario": list(frozen["scenarios"].values())[1],
                    "inputSha256": independent["input_sha256"],
                    "outputSha256": independent["output_sha256"],
                },
                "externalReconciliation": {
                    "selectedReports": recon.get("selected_reports") or [],
                    "market": recon.get("valuation_vs_market") or {},
                },
                "sources": sources[name],
                "limitations": [
                    "逐项目产量与C1成本只有部分获得官方逐年指引；其余明确标为研究拆分或组合代理。",
                    "编辑项目后，集团收入采用权益铜收入代理、利润采用权益铜现金毛利变化桥接，不能替代完整合并报表。",
                    "商品价格、品位、副产品抵扣、税费、少数股东和汇回限制会使项目现金毛利与归母利润产生差异。",
                ],
                "shareholderReturnNote": (
                    "2026年回购中值来自15—25亿元计划，但主要用于员工持股或股权激励，"
                    "经济含义弱于注销式回购，网页单独列示。"
                    if name == "紫金矿业"
                    else (
                        "分红按上一年度归母净利润×支付率估算；网页允许逐年修改回购现金。"
                        if name == "洛阳钼业"
                        else (
                            "五矿资源母公司仍有累计亏损约束，2025年度未派息；"
                            "模型基准期不假定上市公司分红或回购。"
                        )
                    )
                ),
            }
        )

    inputs = {
        "workbook_snapshot": snapshot,
        "independent_model_hash": independent["output_sha256"],
        "reconciliation_hash": reconciliation["content_sha256"],
        "official_project_sources": sources,
    }
    payload: dict[str, Any] = {
        "schemaVersion": "copper_calculator.model.v1",
        "workflowContractVersion": "research.workflow.v2",
        "asOfDate": str(date(2026, 7, 27)),
        "freeze": {
            "independentModelFrozenBeforeExternalReconciliation": True,
            "inputsSha256": _stable_hash(inputs),
            "independentOutputSha256": independent["output_sha256"],
            "externalReconciliationSha256": reconciliation["content_sha256"],
            "sourceWorkbookSha256": {
                name: data["source_sha256"]
                for name, data in snapshot["companies"].items()
            },
        },
        "modelFormula": {
            "projectEquityOutput": "项目100%产量×公司权益比例",
            "projectCashMargin": (
                "项目权益产量×（铜价－C1现金成本×2,204.62262）"
            ),
            "netIncomeBridge": (
                "情景归母净利润＝冻结基准归母净利润＋项目权益铜现金毛利变化×税后归母转化率"
            ),
            "cashFlowBridge": (
                "情景经营现金流＝冻结基准经营现金流＋归母净利润变化×增量现金转换系数"
            ),
            "freeCashFlow": "自由现金流＝经营现金流－资本开支",
            "shareholderReturn": (
                "年度现金回报＝按上一年度归母净利润估算的分红＋当年回购现金"
            ),
        },
        "companies": companies,
    }
    payload["contentSha256"] = _stable_hash(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = compile_model()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "companies": [row["name"] for row in payload["companies"]],
                "sha256": payload["contentSha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
