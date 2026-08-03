from __future__ import annotations

"""Compile the lithium B-track models into financial.db's validated export.

The generated JSON is imported by ``tools.financial.opportunity_profile_export``.
This compiler performs no database writes and no network calls.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "cache" / "lithium_research"
MODEL_PATH = CACHE / "models" / "lithium_company_independent_models_v1.json"
RECON_PATH = CACHE / "models" / "lithium_external_reconciliation_v1.json"
DEFAULT_OUTPUT = CACHE / "lithium_financial_profile_export.json"
RESEARCH_RUN_REF = "btrack_lithium_and_carbonate_20260727"
AS_OF_DATE = "2026-07-27"
VALUATION_DATE = "2026-07-24"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _model_input(
    name: str,
    *,
    value: float | None = None,
    value_text: str | None = None,
    unit: str,
    period: str,
    source_ref: str,
    input_type: str,
    method: str,
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


def _model_output(
    name: str,
    *,
    value: float | None = None,
    value_text: str | None = None,
    low: float | None = None,
    high: float | None = None,
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
        "value_text": value_text,
        "range_low": low,
        "range_high": high,
        "unit": unit,
        "period_or_as_of_date": period,
        "formula": formula,
        "substitution": substitution,
        "dependency_group": dependency,
        "conclusion": conclusion,
    }


COMPANY_ANALYSIS = {
    "赣锋锂业": {
        "operating": (
            "公司同时暴露于阿根廷盐湖、马里和中国锂矿、锂盐及电池业务。2026—2028年"
            "利润的第一驱动不是名义产能，而是Cauchari稳定产量、Goulamina与加不斯爬坡"
            "以及自有资源进入锂盐的比例。高资本开支使净利润恢复快于自由现金流。"
        ),
        "valuation": (
            "正常化PE衡量中期资源利润，PB—ROE约束高资本投入后的资产回报，FCFE反映"
            "扩产现金占用。三者不平均；若终值占比过高，现金流法只作下限或压力参照。"
        ),
        "buy": "锂价进入基准区间且三大项目按季兑现、经营现金流重新覆盖资本开支时，估值折价才具有质量。",
        "sell": "项目爬坡连续下修、资源自给率不升反降，或市值进入独立区间上沿而现金流仍弱时降低仓位。",
        "future": "中期弹性来自低成本资源放量，短期约束来自扩产现金流和多项目执行。",
        "positive": "Cauchari达标、Goulamina/加不斯连续爬坡、资本开支见顶、FCF转正。",
        "risk": "矿山延期、海外税费或物流上升、锂价低于9万元/吨并持续两个季度。",
    },
    "融捷股份": {
        "operating": (
            "134号脉是公司价值核心，2025年精矿产量已经显著增长。利润弹性高，但产能"
            "集中、采选扩建审批和单矿运营使风险也集中；联营锂盐不能按合并收入重复计算。"
        ),
        "valuation": "资源利润法和正常化PE为主，PB—ROE只用于限制周期顶部估值，扩产未获实质进展前不计满规划产能。",
        "buy": "采选扩建获得可执行许可且季度精矿产量稳定，同时估值位于独立区间中下部。",
        "sell": "审批延期、矿山扰动或高锂价下仍不能提升销量时，资源期权应折价。",
        "future": "小体量带来高弹性，也使单一矿山偏差直接传导到利润。",
        "positive": "扩建审批、精矿产量和联营锂盐分红同步改善。",
        "risk": "单矿停产、社区环保约束、扩建进度低于预期。",
    },
    "盛新锂能": {
        "operating": (
            "公司锂盐产能大于当前自有矿供给，利润必须拆成资源租金和外购矿加工利润。"
            "Sabi Star稳定、业隆沟与木绒增量将提高自给率；只看锂盐销量会高估利润质量。"
        ),
        "valuation": "PE适合观察利润恢复，PB—ROE检验大额扩产能否转成资产回报；FCFE受建设期资本开支影响，权重较低。",
        "buy": "自给率连续提升、单位成本下降且经营现金流跟上利润恢复时，低位PE才可兑现。",
        "sell": "锂盐销量增长但资源自给率和现金流不改善，或木绒项目继续延后。",
        "future": "利润恢复取决于自有矿替代外购矿，而不只是碳酸锂现货反弹。",
        "positive": "木绒/业隆沟爬坡、Sabi Star稳定、库存损失下降。",
        "risk": "外购矿价差收窄、非洲运营扰动、扩产现金占用。",
    },
    "盐湖股份": {
        "operating": (
            "钾肥提供稳定利润和现金流，低成本盐湖锂决定增量。新4万吨项目从试生产到"
            "稳定达产是关键，名义8万吨能力不能在爬坡前全部计入销量。"
        ),
        "valuation": "钾肥底仓使正常化PE和PB—ROE都具经济意义；锂业务采用价格—成本—产量桥，避免把高ROE永久化。",
        "buy": "新锂项目达产、钾肥价格稳定且PB处在历史中低位时，组合防御与弹性兼具。",
        "sell": "新项目成本高于预期、盐湖资源约束或市场已按8万吨满产和高锂价计价。",
        "future": "钾肥降低下行风险，锂项目决定利润上沿。",
        "positive": "4万吨项目达产、锂回收率稳定、钾肥销量和价格保持。",
        "risk": "盐湖工艺爬坡、资源品价格同步下行、资本开支超预算。",
    },
    "大中矿业": {
        "operating": (
            "铁矿仍是当前利润基础，鸡脚山和加达是尚待兑现的锂增量。FY1与市场分歧较大，"
            "本研究没有在投产前计满锂产能，因此必须用季度工程进度来更新，而不是直接抬价。"
        ),
        "valuation": "现有铁矿用正常化PE，锂项目用风险折价分部估值；PB—ROE只作资产回报检查。",
        "buy": "鸡脚山实现商业化产出、成本可验证且价格未提前计入完整6万吨产能时。",
        "sell": "投产继续延后，或市场估值已经要求2027年加达与鸡脚山同时满产。",
        "future": "公司从铁矿向锂扩张，价值取决于项目从建设转为可销售产量的速度。",
        "positive": "鸡脚山出产品、加达建设按期、铁矿现金流覆盖锂资本开支。",
        "risk": "工程延期、锂项目融资增加、铁矿利润下行。",
    },
    "雅化集团": {
        "operating": (
            "Kamativi和李家沟提升资源自给，民爆业务提供非锂利润。锂盐产能不是主要瓶颈，"
            "自有矿稳定供给、锂盐产销和库存价差才决定利润质量。"
        ),
        "valuation": "正常化PE为主，PB—ROE检验扩产后回报，民爆业务单独提供估值缓冲。",
        "buy": "自给率提升、锂业务现金流转正且估值仍低于独立区间中位时。",
        "sell": "矿端产量未兑现、锂盐库存亏损重现或现货上涨已被高倍数充分计入。",
        "future": "资源自给改善使利润对锂价更敏感，也降低外购矿挤压。",
        "positive": "李家沟稳产、Kamativi成本下降、民爆利润稳定。",
        "risk": "海外矿运营、锂盐库存周期、客户集中和价格回落。",
    },
    "天华新能": {
        "operating": (
            "公司拥有大规模锂盐能力，但利润取决于非洲资源自给率而非单纯销量。独立模型"
            "低于一致预期，主要因没有假定Ogapa和后续项目迅速覆盖全部加工需求。"
        ),
        "valuation": "PE反映规模和资源化，PB—ROE约束重资产扩张，FCFE因扩产资本开支仅作参考。",
        "buy": "资源自给率、单位现金成本和自由现金流三项同时改善，而市场仍按纯加工企业折价。",
        "sell": "销量扩张主要依靠外购矿，或资本开支增长快于经营现金流。",
        "future": "从加工向资源一体化转型能否兑现，是估值重估的核心。",
        "positive": "Ogapa稳定、金子峰按期、锂盐产销和现金回款同步增长。",
        "risk": "非洲项目延期、外购矿价差收窄、扩产负现金流。",
    },
    "天齐锂业": {
        "operating": (
            "Greenbushes提供全球低成本资源，SQM贡献权益法收益，自有锂盐决定加工兑现。"
            "三部分必须分开；独立模型较市场保守，主要因未把SQM高盈利和CGP3爬坡同时按高位计入。"
        ),
        "valuation": "资源利润、正常化PE、PB—ROE和FCFE交叉验证；SQM权益不能与自产资源重复计量。",
        "buy": "Greenbushes产销恢复、SQM分红和公司现金流改善，同时估值未计满高锂价。",
        "sell": "锂价和SQM利润回落、CGP3/Kwinana效率不达预期，或市场已按共识上沿定价。",
        "future": "资源质量强，但归母利润受权益结构、锂价和海外锂盐效率共同影响。",
        "positive": "CGP3达产、SQM分红稳定、债务和资本开支压力下降。",
        "risk": "Greenbushes产销调整、SQM政策税费、锂盐工厂效率。",
    },
    "永杉锂业": {
        "operating": (
            "公司主要是外购原料加工，销量不能直接乘锂价形成资源利润。2026扩产提高收入能力，"
            "但在加工费薄和库存波动下，盈利恢复仍很脆弱。"
        ),
        "valuation": "亏损和低利润阶段不使用高倍数PE；PB—ROE仅作资产约束，核心是加工费和库存情景。",
        "buy": "连续两个季度实现正加工利润、经营现金流转正且扩产利用率上升。",
        "sell": "扩产后利用率低、库存跌价或市场按资源型公司估值。",
        "future": "规模增长不等于利润增长，价差和库存纪律比现货方向更重要。",
        "positive": "扩建投产、客户锁量、加工费修复、库存周转改善。",
        "risk": "无资源自给、价格急跌导致库存损失、现金流持续为负。",
    },
    "中矿资源": {
        "operating": (
            "Bikita资源、选矿和7.1万吨锂盐形成较高自给率，铯铷提供非锂利润。独立FY1"
            "高于一致预期，关键假设是升级产线利用率和资源自给率能在2026年兑现。"
        ),
        "valuation": "资源利润与SOTP为主，PE和PB—ROE交叉验证；高自给率使价格弹性高，但不应永久化周期ROE。",
        "buy": "锂盐产量、Bikita精矿和单位成本同时验证，且市值仍低于多方法区间中位。",
        "sell": "产线利用率、自给率或成本任一连续低于模型，或价格进入区间上沿。",
        "future": "一体化兑现可形成反共识上行，但模型对锂价和产能利用率敏感。",
        "positive": "3万吨升级线满产、Bikita精矿稳定、铯铷利润增长。",
        "risk": "非洲运营、产能利用率低、锂价低于成本敏感区。",
    },
    "藏格矿业": {
        "operating": (
            "钾肥与巨龙铜业权益提供主要利润，盐湖锂和Mamico提供增量。不能用公司总利润"
            "反推锂业务估值，也不能在Mamico投产前计满26.95%权益产量。"
        ),
        "valuation": "SOTP与正常化PE为主，PB—ROE适合作组合回报检查；锂项目只估增量。",
        "buy": "Mamico工程进度、巨龙分红和钾肥现金流同时稳定，且估值未计满三项上行。",
        "sell": "铜、钾、锂三项均按高价定价，或Mamico延期而市场不降估值。",
        "future": "组合利润稳定性强于纯锂公司，但高市值需要多资产共同兑现。",
        "positive": "Mamico投产、巨龙增产分红、钾肥价格稳定。",
        "risk": "项目延期、铜钾价格回落、关联权益现金回收弱。",
    },
    "西藏城投": {
        "operating": (
            "盐湖项目资源量大但尚未商业化，地产存量和负债约束仍主导当前财务。规划产能"
            "只能作为条件价值，不能转成FY1利润或用PE估值。"
        ),
        "valuation": "只使用风险折价项目NAV和资产负债约束；PB也因项目未产生回报而仅作辅助。",
        "buy": "取得可执行审批、融资闭环、工程开工并出现连续中试/商业化数据后，项目折价才可收窄。",
        "sell": "项目长期停留在规划、地产现金流恶化或市场按满产资源价值定价。",
        "future": "价值由项目去风险进度决定，而非短期锂价。",
        "positive": "审批、融资、工程和产品认证依次闭环。",
        "risk": "项目延期、技术路线不达标、资产负债压力。",
    },
    "永兴材料": {
        "operating": (
            "锂云母采选冶一体化提供资源利润，特钢提供现金流缓冲。锂云母成本和环保约束"
            "高于优质锂辉石，扩产必须同时验证单位成本和渣处理。"
        ),
        "valuation": "正常化PE、资源利润和PB—ROE交叉验证；特钢与锂业务分开估值。",
        "buy": "锂业务扩产同时保持成本优势、环保运行稳定，且特钢现金流覆盖扩建。",
        "sell": "云母成本上升、环保约束收紧或市场按上行情景满产定价。",
        "future": "产量增长较清楚，决定回报的是云母成本曲线和合规稳定性。",
        "positive": "锂业务爬坡、成本下降、特钢现金流稳定。",
        "risk": "锂云母成本、环保停产、锂价跌破成本安全垫。",
    },
}


def _summary(
    company: dict[str, Any], recon: dict[str, Any]
) -> dict[str, Any]:
    name = company["company"]
    analysis = COMPANY_ANALYSIS[name]
    market = recon["market_reconciliation"]
    core_range = company["independent_equity_value_range"]
    low_raw = core_range.get("low_rmb_bn")
    high_raw = core_range.get("high_rmb_bn")
    low = low_raw * 10.0 if low_raw is not None else None
    high = high_raw * 10.0 if high_raw is not None else None
    market_cap = market["market_cap_rmb_bn"] * 10.0
    if low is None or high is None:
        conclusion = (
            f"当前市值约{market_cap:.0f}亿元，但项目、资本开支和现金流数据不足以"
            "形成可复算的核心估值区间；暂不根据规划产能给出目标价。"
        )
    elif market_cap < low:
        conclusion = (
            f"本研究适用方法给出约{low:.0f}—{high:.0f}亿元的宽区间，当前市值约"
            f"{market_cap:.0f}亿元，低于区间下沿；但买入仍需项目、成本和现金流验证。"
        )
    elif market_cap > high:
        conclusion = (
            f"本研究适用方法给出约{low:.0f}—{high:.0f}亿元的宽区间，当前市值约"
            f"{market_cap:.0f}亿元，高于区间上沿；市场已计入更高锂价或更快项目兑现。"
        )
    else:
        conclusion = (
            f"本研究适用方法给出约{low:.0f}—{high:.0f}亿元的宽区间，当前市值约"
            f"{market_cap:.0f}亿元，位于区间内；收益取决于经营兑现而非单纯估值修复。"
        )
    base = {row["year"]: row for row in company["scenarios"]["基准情景"]}
    scenarios = []
    current_price = market.get("price_cny")
    shares_100m = market_cap / current_price if current_price else None
    pe_range = None
    for valuation in company["valuations"]:
        if valuation["method"] == "正常化市盈率":
            pe_range = valuation["inputs"]["pe_range"]
            break
    for scenario_name, target_pe in (
        ("下行情景", (pe_range or [6.0, 9.0])[0]),
        ("基准情景", sum(pe_range or [8.0, 12.0]) / 2.0),
        ("上行情景", (pe_range or [10.0, 14.0])[-1]),
    ):
        row = company["scenarios"][scenario_name][1]
        net_income_100m = row["net_income_rmb_bn"] * 10.0
        free_cash = row["fcfe_rmb_bn"] * 10.0
        target_market_cap = max(0.0, net_income_100m * target_pe)
        target_price = target_market_cap / shares_100m if shares_100m else 0.0
        condition = {
            "下行情景": "锂价回落、项目延期或自给率低于计划；估值倍数同步收缩。",
            "基准情景": "按冻结的产量、自给率、成本和含税锂价路径逐年兑现。",
            "上行情景": "锂价更强且项目按期，资源自给率、成本和现金回收均优于基准。",
        }[scenario_name]
        scenarios.append(
            {
                "scenario_label": scenario_name,
                "revenue": row["revenue_rmb_bn"] * 10.0,
                "net_income": net_income_100m,
                "operating_cash_flow": None,
                "capex": None,
                "free_cash_flow": free_cash,
                "target_pe": target_pe,
                "target_market_cap": target_market_cap,
                "target_price": target_price,
                "condition": condition,
                "cash_flow_boundary": (
                    "当前只形成FCFE研究近似；缺少逐公司FY2资本开支与营运资金依据，"
                    "不以2025实际值乘固定系数伪造经营现金流和资本开支。"
                ),
            }
        )
    return {
        "ready": True,
        "conclusion": conclusion,
        "difference_causes": [
            recon["difference_summary"],
            "独立模型按含税锂价、权益/自给产量、成本、加工利润和非锂业务逐项计算；一致预期只在冻结后对账。",
            "多方法结果不作算术平均，周期PE、PB—ROE和FCFE的适用性按公司资产结构分别解释。",
        ],
        "scenario_results": scenarios,
        "operating_analysis": analysis["operating"],
        "valuation_analysis": analysis["valuation"],
        "buy_point_analysis": analysis["buy"],
        "sell_point_analysis": analysis["sell"],
        "future_view": analysis["future"],
        "positive_trigger": analysis["positive"],
        "risk_trigger": analysis["risk"],
    }


def build() -> dict[str, Any]:
    models = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    recons = json.loads(RECON_PATH.read_text(encoding="utf-8"))
    recon_by_ticker = {row["ticker"]: row for row in recons["companies"]}
    model_hash = _sha256_file(MODEL_PATH)
    recon_hash = _sha256_file(RECON_PATH)
    companies = []
    for company in models["companies"]:
        name = company["company"]
        ticker = company["ticker"]
        recon = recon_by_ticker[ticker]
        model_key = f"lithium_b_20260727:{ticker}:financial_bridge:v5"
        valuation_key = f"lithium_b_20260727:{ticker}:valuation:v5"
        base = company["scenarios"]["基准情景"]
        financial_outputs = []
        observations = []
        formula = company["formula"]["net_income"]
        for index, row in enumerate(base, start=1):
            year = row["year"]
            for metric_name, field, unit in (
                ("revenue", "revenue_rmb_bn", "亿元人民币"),
                ("net_income", "net_income_rmb_bn", "亿元人民币"),
                ("free_cash_flow", "fcfe_rmb_bn", "亿元人民币"),
                ("total_equity", "equity_rmb_bn", "亿元人民币"),
                ("roe", "roe_pct", "%"),
            ):
                value = row[field] * 10.0 if unit == "亿元人民币" else row[field]
                financial_outputs.append(
                    _model_output(
                        f"FY{index}{metric_name}",
                        value=value,
                        unit=unit,
                        period=str(year),
                        formula=formula,
                        substitution=(
                            f"{field}={row[field]:.4f}十亿元×10"
                            if unit == "亿元人民币"
                            else f"{field}={row[field]:.4f}%"
                        ),
                        dependency="锂价—权益/自给产量—成本—加工利润—非锂业务",
                        conclusion=f"{year}年基准情景{metric_name}。",
                    )
                )
                observations.append(
                    {
                        "metric_name": metric_name,
                        "value_num": value,
                        "unit": unit,
                        "currency": "CNY" if unit == "亿元人民币" else None,
                        "period_end": f"{year}-12-31",
                        "fiscal_year": year,
                        "fiscal_period": "FY",
                        "frequency": "annual",
                        "fact_type": "internal_estimate",
                        "as_of_date": AS_OF_DATE,
                        "provider": "internal_model",
                        "raw_feature_name": f"lithium_company_model.base.{field}",
                        "source_snapshot_key": f"model_{ticker}",
                        "formula": formula,
                        "input_refs": [
                            company["freeze"]["input_sha256"],
                            company["freeze"]["output_sha256"],
                        ],
                        "quality_status": "usable",
                        "scenario_name": "基准情景",
                        "model_run_key": model_key,
                    }
                )
        reconciliations = []
        for index, year_row in enumerate(recon["yearly_reconciliation"], start=1):
            wind_value = year_row["wind_consensus"].get("net_income_rmb_bn")
            if wind_value is None:
                continue
            reconciliations.append(
                {
                    "benchmark_type": "consensus",
                    "benchmark_source_ref": (
                        f"wind:WSS:{ticker}:west_netprofit_fy{index}:{VALUATION_DATE.replace('-', '')}"
                    ),
                    "metric_name": "net_income",
                    "period": f"FY{index}",
                    "independent_value": year_row["independent"]["net_income_rmb_bn"]
                    * 10.0,
                    "benchmark_value": wind_value * 10.0,
                    "unit": "亿元人民币",
                    "decomposition": {
                        "company": name,
                        "price_path": "15/14/13万元每吨（含税）",
                        "difference_drivers": "权益或自给产量、资源成本、加工利润、非锂业务",
                    },
                    "conclusion": recon["difference_summary"],
                }
            )
        financial_run = {
            "run_key": model_key,
            "supersedes_run_keys": [
                f"lithium_b_20260727:{ticker}:financial_bridge:v4"
            ],
            "skill_name": "company_financial_modeling",
            "model_name": "锂价—权益产量—成本—归母利润桥",
            "model_role": "core",
            "forecast_start": "2026-01-01",
            "forecast_end": "2028-12-31",
            "valuation_date": VALUATION_DATE,
            "assumptions": {
                "model_method": (
                    f"{company['formula']['resource_profit']}；"
                    f"{company['formula']['processing_profit']}；"
                    f"{company['formula']['net_income']}。"
                ),
                "scenario_policy": "三种情景是可复算经营状态，不是发生概率。",
                "actual_2025": company["actual_2025"],
                "project_and_operating_evidence": company[
                    "project_and_operating_evidence"
                ],
                "independent_freeze": company["freeze"],
            },
            "limitations": "；".join(
                str(item).rstrip("。；; ") for item in company["limitations"]
            ) + "。",
            "inputs": [
                _model_input(
                    "2025归母净利润",
                    value=company["actual_2025"]["net_income_rmb_bn"] * 10.0,
                    unit="亿元人民币",
                    period="2025",
                    source_ref=company["freeze"]["input_sha256"],
                    input_type="direct_fact",
                    method="Wind年报口径；市场数据与研究模型分层保存并分别标注时点。",
                ),
                _model_input(
                    "2026—2028含税碳酸锂价格路径",
                    value_text="15/14/13",
                    unit="万元/吨",
                    period="2026—2028",
                    source_ref=company["freeze"]["input_sha256"],
                    input_type="expert_assumption",
                    method="基准情景；另有10/9/9下行与18/17/16上行情景。",
                    limitation="研究假设，不是外部事实。",
                ),
                _model_input(
                    "产品销量、资源自给率与单位成本",
                    value_text=json.dumps(
                        company["assumptions"], ensure_ascii=False, sort_keys=True
                    ),
                    unit="逐年项目口径",
                    period="2026—2028",
                    source_ref=company["freeze"]["input_sha256"],
                    input_type="derived_fact",
                    method="以公司项目产能、权益、投产和爬坡事实形成研究估算。",
                    limitation="产能不等于销量；海外项目、工艺和权益法口径均可能偏离。",
                ),
            ],
            "outputs": financial_outputs,
            "finalization": "independent",
            "reconciliations": reconciliations,
        }
        valuation_outputs = []
        for valuation in company["valuations"]:
            if (
                valuation.get("low_rmb_bn") is None
                or valuation.get("high_rmb_bn") is None
            ):
                continue
            valuation_outputs.append(
                _model_output(
                    f"{valuation['method']}目标市值"
                    if valuation["method"] != "股权自由现金流"
                    else "股权自由现金流价值",
                    low=valuation["low_rmb_bn"] * 10.0,
                    high=valuation["high_rmb_bn"] * 10.0,
                    unit="亿元人民币",
                    period=str(valuation["forecast_year"]),
                    formula=valuation["method"],
                    substitution=json.dumps(
                        valuation.get("inputs") or {}, ensure_ascii=False
                    ),
                    dependency=f"{valuation['method']}估值",
                    conclusion=valuation.get("limitation")
                    or "按适用方法给出区间，不与其他方法机械平均。",
                )
            )
        if not valuation_outputs:
            valuation_outputs.append(
                _model_output(
                    "估值结论状态",
                    value_text="暂不评级",
                    unit="不适用",
                    period=VALUATION_DATE,
                    formula=(
                        "只有在项目权益、可采储量、产量爬坡、单位成本、资本开支、"
                        "税制和投产时点可复算时，才形成项目净现值或公司估值区间。"
                    ),
                    substitution=(
                        "现有公开资料不足以把规划产能转为公司可归属现金流，"
                        "因此不设置最低PB、不沿用旧条件NAV，也不给出目标市值。"
                    ),
                    dependency="估值不可得状态",
                    conclusion=(
                        "目前没有足够证据形成可复算估值；该结论用于关闭旧数值，"
                        "不是把缺失信息机械替换为零。"
                    ),
                )
            )
        market = recon["market_reconciliation"]
        pb_valuation = next(
            (
                valuation
                for valuation in company["valuations"]
                if valuation["method"] == "PB—ROE"
            ),
            None,
        )
        pb_range = (
            (pb_valuation.get("inputs") or {}).get("pb_range")
            if pb_valuation else None
        )
        current_pb = float(
            market.get("pb")
            or (sum(pb_range) / len(pb_range) if pb_range else 1.0)
        )
        market_cap_yi = float(market["market_cap_rmb_bn"]) * 10.0
        fy1_profit_yi = float(base[0]["net_income_rmb_bn"]) * 10.0
        if fy1_profit_yi > 0:
            observations.append(
                {
                    "metric_name": "pe_forward",
                    "value_num": market_cap_yi / fy1_profit_yi,
                    "unit": "倍",
                    "currency": None,
                    "period_end": "2026-12-31",
                    "fiscal_year": 2026,
                    "fiscal_period": "FY1",
                    "frequency": "annual",
                    "fact_type": "implied",
                    "as_of_date": VALUATION_DATE,
                    "provider": "internal_model",
                    "raw_feature_name": "当前市值对应的独立模型FY1市盈率",
                    "source_snapshot_key": f"model_{ticker}",
                    "formula": "当前市值÷独立模型FY1归母净利润",
                    "input_refs": [
                        company["freeze"]["output_sha256"],
                        f"wind:WSS:{ticker}:mkt_cap_ard:{VALUATION_DATE.replace('-', '')}",
                    ],
                    "quality_status": "usable",
                    "scenario_name": "base",
                    "model_run_key": valuation_key,
                }
            )

        normalized_pe = next(
            (
                valuation
                for valuation in company["valuations"]
                if valuation["method"] == "正常化市盈率"
            ),
            None,
        )
        pe_range = (
            (normalized_pe.get("inputs") or {}).get("pe_range")
            if normalized_pe else None
        )
        if pe_range:
            pe_mid = sum(float(value) for value in pe_range) / len(pe_range)
            if pe_mid > 0:
                observations.append(
                    {
                        "metric_name": "net_income",
                        "value_num": market_cap_yi / pe_mid,
                        "unit": "亿元人民币",
                        "currency": "CNY",
                        "period_end": "2028-12-31",
                        "fiscal_year": 2028,
                        "fiscal_period": "FY3",
                        "frequency": "annual",
                        "fact_type": "implied",
                        "as_of_date": VALUATION_DATE,
                        "provider": "internal_model",
                        "raw_feature_name": "正常化市盈率中值下当前市值要求的归母净利润",
                        "source_snapshot_key": f"model_{ticker}",
                        "formula": "当前市值÷正常化市盈率区间中值",
                        "input_refs": [
                            company["freeze"]["output_sha256"],
                            f"wind:WSS:{ticker}:mkt_cap_ard:{VALUATION_DATE.replace('-', '')}",
                        ],
                        "quality_status": "usable",
                        "scenario_name": "target_pe_midpoint",
                        "model_run_key": valuation_key,
                    }
                )

        pb_inputs = (pb_valuation or {}).get("inputs") or {}
        if market.get("pb") is not None:
            cost_of_equity = pb_inputs.get("base_cost_of_equity_pct")
            terminal_growth = pb_inputs.get("base_terminal_growth_pct")
            if (
                cost_of_equity is not None
                and terminal_growth is not None
                and float(cost_of_equity) > float(terminal_growth)
            ):
                implied_roe = (
                    float(market["pb"])
                    * (float(cost_of_equity) - float(terminal_growth))
                    + float(terminal_growth)
                )
                observations.append(
                    {
                        "metric_name": "roe",
                        "value_num": implied_roe,
                        "unit": "%",
                        "currency": None,
                        "period_end": "2028-12-31",
                        "fiscal_year": 2028,
                        "fiscal_period": "long_term",
                        "frequency": "annual",
                        "fact_type": "implied",
                        "as_of_date": VALUATION_DATE,
                        "provider": "internal_model",
                        "raw_feature_name": "当前PB隐含的长期可持续ROE",
                        "source_snapshot_key": f"model_{ticker}",
                        "formula": "隐含ROE＝当前PB×（股权资本成本－永续增长率）＋永续增长率",
                        "input_refs": [
                            company["freeze"]["output_sha256"],
                            f"wind:WSS:{ticker}:pb_lf:{VALUATION_DATE.replace('-', '')}",
                        ],
                        "quality_status": "usable",
                        "scenario_name": "market_pb_gordon",
                        "model_run_key": valuation_key,
                    }
                )
        scenario_workbench = {
            "simple_ready": bool(pb_range),
            "detailed_ready": False,
            "default_mode": "simple" if pb_range else None,
            "reason": (
                "现有数据足以使用期初归母净资产、FY1—FY3独立归母净利润、分红率"
                "和目标PB建立简化权益桥；逐项目债务、完整三表和少数股东现金分配"
                "尚不足以支持通用详细模式，项目级锂价与产量调整请进入碳酸锂计算器。"
                if pb_range
                else "预测ROE不足以支持PB—ROE，且逐项目现金流数据不完整；不提供伪精确输入台。"
            ),
            "simple": {
                "opening_book_value_cny_100m": (
                    company["actual_2025"]["equity_rmb_bn"] * 10.0
                ),
                "current_pb": current_pb,
                "target_pb": sum(pb_range) / len(pb_range) if pb_range else None,
                "years": [
                    {
                        "fiscal_year": row["year"],
                        "net_income_cny_100m": row["net_income_rmb_bn"] * 10.0,
                        "payout_ratio_pct": 25.0,
                    }
                    for row in company["scenarios"]["基准情景"]
                ],
                "pb_presets": {
                    "current": current_pb,
                    "research_low": float(pb_range[0]) if pb_range else None,
                    "research_mid": (
                        sum(pb_range) / len(pb_range) if pb_range else None
                    ),
                    "research_high": float(pb_range[-1]) if pb_range else None,
                },
            },
            "detailed": {
                "available_fields": [
                    "历史财务与当前估值",
                    "FY1—FY3归母净利润",
                    "资源/加工产量、成本和价格情景",
                    "经营现金流与资本开支历史",
                ],
                "missing_required_fields": [
                    "FY1—FY3完整资产负债表",
                    "逐项目债务与少数股东现金分配",
                    "逐项目营运资本和资本开支计划",
                ],
            },
        }
        valuation_run = {
            "run_key": valuation_key,
            "supersedes_run_keys": [
                f"lithium_b_20260727:{ticker}:valuation:v{version}"
                for version in range(1, 5)
            ],
            "skill_name": "company_valuation_modeling",
            "model_name": "锂资源公司多方法估值与当前市场诊断",
            "model_role": "reference",
            "forecast_start": "2026-01-01",
            "forecast_end": "2028-12-31",
            "valuation_date": VALUATION_DATE,
            "assumptions": {
                "company_detail_summary": _summary(company, recon),
                "scenario_workbench": scenario_workbench,
                "pb_framework": {
                    "applicability": (
                        "核心方法"
                        if name in {"盐湖股份", "中矿资源", "藏格矿业"}
                        else "辅助或诊断方法"
                    ),
                    "cycle_sensitivity": "高；锂价变化会同时改变盈利、净资产积累和市场给定PB。",
                    "asset_intensity": company["model_type"],
                    "basis": company["valuation_note"],
                    "price_exposure": "基准含税碳酸锂价格15/14/13万元/吨。",
                    "profit_driver": "权益或自给产量×价格成本差＋加工利润＋非锂业务。",
                    "tags": ["锂价", "权益产量", "资源自给率", "PB—ROE", "现金流"],
                },
                "independent_valuation_range_rmb_bn": company[
                    "independent_equity_value_range"
                ],
                "current_market": market,
            },
            "limitations": (
                f"{company['valuation_note']}；市场数据只在独立模型冻结后用于对账。"
            ),
            "inputs": (
                [
                    _model_input(
                        "独立核心估值区间",
                        low=company["independent_equity_value_range"]["low_rmb_bn"] * 10.0,
                        high=company["independent_equity_value_range"]["high_rmb_bn"] * 10.0,
                        unit="亿元人民币",
                        period=VALUATION_DATE,
                        source_ref=company["freeze"]["output_sha256"],
                        input_type="derived_fact",
                        method="只使用核心方法；参考与诊断方法不并入区间。",
                    )
                ]
                if company["independent_equity_value_range"].get("low_rmb_bn")
                is not None
                else []
            ) + [
                _model_input(
                    "当前总市值",
                    value=market["market_cap_rmb_bn"] * 10.0,
                    unit="亿元人民币",
                    period=market["trade_date"],
                    source_ref=f"wind:WSS:{ticker}:mkt_cap_ard:{market['trade_date'].replace('-', '')}",
                    input_type="direct_fact",
                    method="Wind交易日总市值。",
                ),
            ],
            "outputs": valuation_outputs,
            "finalization": "reviewed",
            "reconciliations": [],
        }
        model_runs = [financial_run]
        model_runs.append(valuation_run)
        companies.append(
            {
                "research_company_id": company["research_company_id"],
                "security": {
                    "canonical_name": name,
                    "ticker": ticker,
                    "market": "A股",
                    "listing_status": "a_share",
                    "reporting_currency": "CNY",
                    "identity_status": "verified",
                },
                "source_snapshots": [
                    {
                        "key": f"model_{ticker}",
                        "provider": "internal_model",
                        "source_channel": "internal_calculation",
                        "source_ref": company["freeze"]["output_sha256"],
                        "title": f"{name}独立锂价—权益产量财务模型",
                        "publisher": "本研究",
                        "as_of_date": AS_OF_DATE,
                        "content_hash": company["freeze"]["output_sha256"],
                        "raw_snapshot_path": company["freeze"]["output_path"],
                        "metadata": {
                            "database_boundary": "financial.db only",
                            "frozen_before_external_reconciliation": True,
                        },
                    }
                ],
                "model_runs": model_runs,
                "observations": observations,
            }
        )
    return {
        "export_schema_version": "company_financial_profile_export.v1",
        "research_run_ref": RESEARCH_RUN_REF,
        "as_of_date": AS_OF_DATE,
        "source_artifacts": [
            {"path": MODEL_PATH.relative_to(ROOT).as_posix(), "sha256": model_hash},
            {"path": RECON_PATH.relative_to(ROOT).as_posix(), "sha256": recon_hash},
        ],
        "companies": companies,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = build()
    _write_json(args.output, payload)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "companies": len(payload["companies"]),
                "model_runs": sum(
                    len(company["model_runs"]) for company in payload["companies"]
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
