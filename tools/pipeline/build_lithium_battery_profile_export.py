from __future__ import annotations

"""Compile the frozen lithium-battery company models for financial.db.

The upstream independent-model artifact deliberately excludes consensus and
sell-side forecasts.  This compiler only reshapes that frozen artifact into the
generic company financial-profile contract; external reconciliation is a
separate step.
"""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = (
    ROOT
    / "cache"
    / "lithium_battery_research"
    / "models"
    / "battery_independent_models_v1.json"
)
SNAPSHOT_PATH = (
    ROOT
    / "cache"
    / "lithium_battery_research"
    / "models"
    / "battery_financial_snapshot_v1.json"
)
DEFAULT_OUTPUT = (
    ROOT
    / "cache"
    / "lithium_battery_research"
    / "models"
    / "battery_company_financial_profile_export_v1.json"
)
AS_OF_DATE = "2026-07-28"
RUN_REF = "lithium_battery_b_20260728"


COMPANY_ANALYSIS: dict[str, dict[str, Any]] = {
    "宁德时代": {
        "difference_causes": [
            "独立模型把动力、储能和材料分别建模，2026年收入受全球装机份额、ASP下降和欧洲产能爬坡共同约束。",
            "模型没有把储能行业接近翻倍的增速全部归给公司，因此与一致预期的差异主要取决于储能出货和海外盈利。",
        ],
        "operating": (
            "宁德时代的关键不是单纯扩产，而是动力电池规模、储能产品升级和材料回收共同维持单位盈利。"
            "独立模型预计2026—2028年收入5880/6896/7848亿元，归母净利润1005.98/1160.74/"
            "1284.43亿元，自由现金流938.67/1065.04/1143.98亿元。若欧洲产能利用率和储能大电芯"
            "兑现，现金流仍能覆盖资本开支；若海外本地化成本和ASP降幅超过模型，利润率会先于收入承压。"
        ),
        "valuation": (
            "2027年正常化市盈率18—24倍对应市值20893—27858亿元。PB—ROE以2027年末净资产"
            "4826.60亿元、FY2—FY3平均ROE约25.24%测算，给出的15678—19516亿元只作资产回报"
            "约束：它提示当前高估值依赖超额ROE维持，而不是否定现金流和技术壁垒的价值。"
        ),
        "buy": "市值接近核心市盈率区间下沿，同时储能出货、海外利用率和季度自由现金流至少两项继续改善时，风险收益更有吸引力。",
        "sell": "若市值超过核心区间上沿但储能毛利、海外爬坡或动力份额没有同步上修，或自由现金流连续弱于资本开支，应降低估值假设。",
        "future": "重点跟踪全球动力份额、储能500Ah+产品量产、欧洲产能利用率、单位Wh盈利和自由现金流。",
        "positive": "储能量价好于模型、海外产能利用率上升且经营现金流持续覆盖资本开支。",
        "risk": "动力ASP降幅扩大、海外本地化成本超预期或储能竞争使毛利率低于模型。",
    },
    "比亚迪": {
        "difference_causes": [
            "模型以整车销量和单车收入为主线，刀片电池内部供应不重复计收入，因此比把电池产值单列的口径更保守。",
            "外部预测对海外销量、车型结构和外供储能的判断会直接改变集团净利率，而非只改变电池业务收入。",
        ],
        "operating": (
            "比亚迪是整车、电池、电子和储能一体化集团，电池规模优势首先通过成本和车型竞争力体现。"
            "独立模型预计2026—2028年收入9325/10749/12063亿元，归母净利润337.30/430.87/"
            "516.73亿元，自由现金流分别约-1060.92/-846.79/-652.41亿元；负自由现金流反映海外"
            "工厂和全产业链资本开支，若销量增长不能转化为净利率和现金回收，规模本身不等于价值创造。"
        ),
        "valuation": (
            "2027年正常化市盈率16—22倍对应6894—9479亿元。PB—ROE以2027年末净资产"
            "2863.58亿元和FY2—FY3平均ROE约16.44%得到4991—5922亿元，显示当前定价不仅要求"
            "账面回报改善，也要求海外和高端车型延长增长期，PB方法因业务综合性仅作交叉约束。"
        ),
        "buy": "市值位于核心区间下部，且海外销量、车型结构、单车盈利和经营现金流同时改善时，价格回落才构成更可靠买点。",
        "sell": "若高估值仍在而海外工厂利用率、单车盈利或现金转换恶化，或者竞争迫使促销强度持续上升，应下调长期回报假设。",
        "future": "跟踪海外销量与本地化产能、单车收入、汽车业务毛利、外供储能和经营现金流。",
        "positive": "海外销量与高端车型占比提升，集团净利率上行且资本开支强度见顶。",
        "risk": "国内价格竞争加剧、海外政策阻力或扩产导致自由现金流长期为负。",
    },
    "国轩高科": {
        "difference_causes": [
            "独立模型分别约束动力和储能出货，未把大众合作、海外规划和在建产能直接视为已确认订单。",
            "利润弹性主要来自利用率和毛利率，外部预测若采用更快海外爬坡会明显高于本模型。",
        ],
        "operating": (
            "国轩高科的价值取决于大众体系、储能和海外基地能否把规模转化为盈利，而不是名义产能。"
            "独立模型预计2026—2028年收入649.4/824.4/1001.0亿元，归母净利润22.06/30.42/42.01亿元，"
            "自由现金流约-70.80/-55.89/-33.29亿元。盈利上行但现金流仍被扩产占用，说明订单兑现、"
            "利用率和回款是比收入增速更重要的验证指标。"
        ),
        "valuation": (
            "2027年16—24倍市盈率对应487—730亿元；PB—ROE以334.21亿元期末净资产和约10.71%"
            "可持续ROE得到306—343亿元。两者差异说明市场若给予成长溢价，必须由海外量产、利用率"
            "和现金流兑现支撑，不能仅凭合作关系维持。"
        ),
        "buy": "市值接近正常化市盈率区间下沿，同时大众项目、储能出货和现金流至少两项改善时再提高仓位更合理。",
        "sell": "若估值接近上沿但海外项目延期、毛利率不升或自由现金流缺口扩大，应降低成长溢价。",
        "future": "跟踪大众体系量产、动力与储能出货、海外基地利用率、毛利率和资本开支回收。",
        "positive": "海外项目按期量产、单位盈利改善且自由现金流缺口收窄。",
        "risk": "扩产先于订单、价格竞争导致毛利率低于模型或客户放量延期。",
    },
    "中创新航": {
        "difference_causes": [
            "模型以2025年报和最新经营进展为基数，动力与储能客户分别处理，未用动力装机份额替代储能订单。",
            "港股一致预期和机构覆盖差异较大，当前低倍数也包含资本密集、专利诉讼和客户集中折价。",
        ],
        "operating": (
            "中创新航2025年规模和现金流已有改善，但未来回报仍取决于动力客户结构、储能放量和折旧吸收。"
            "独立模型预计2026—2028年收入599.0/751.3/913.0亿元，归母净利润32.30/48.02/67.37亿元，"
            "自由现金流约-26.39/-12.58/9.22亿元；2028年才转正的路径说明估值不能只看利润增速。"
        ),
        "valuation": (
            "2027年10—16倍正常化市盈率对应480—768亿元人民币，PB—ROE给出480—538亿元。"
            "当前市值明显低于两种独立方法，但折价是否收敛取决于自由现金流转正和客户结构改善；"
            "港股流动性、汇率与治理折价不能机械归零。"
        ),
        "buy": "低估值同时伴随自由现金流缺口收窄、储能占比提升和核心客户份额稳定时，才具备重估基础。",
        "sell": "若价格已反映扭亏和现金流转正，而资本开支、专利或客户风险再次上升，应降低估值中枢。",
        "future": "跟踪动力装机份额、储能出货、客户集中、专利风险、折旧和自由现金流。",
        "positive": "储能和海外客户放量，现金流提前转正且单位盈利持续提高。",
        "risk": "动力份额下滑、客户集中或专利事项增加成本，扩产继续吞噬现金。",
    },
    "亿纬锂能": {
        "difference_causes": [
            "模型将动力、储能、消费电池和投资收益分开，避免把思摩尔等投资收益误当成电池经营利润。",
            "储能价格传导和消费电池稳定性是利润差异的主要来源，行业出货增长不能直接等比例外推净利润。",
        ],
        "operating": (
            "亿纬锂能的优势是动力、储能与消费电池组合，但不同业务的资本强度和利润率并不相同。"
            "独立模型预计2026—2028年收入952.5/1155.1/1352.6亿元，归母净利润67.75/85.38/"
            "105.69亿元，自由现金流约-28.53/-14.01/7.11亿元。储能放量若只增加低毛利收入，"
            "现金流和ROE不会自动改善，因此需要同时验证单位盈利和应收周转。"
        ),
        "valuation": (
            "2027年15—21倍市盈率对应1281—1793亿元；PB—ROE基于604.40亿元净资产和约15.67%"
            "可持续ROE得到918—1061亿元。当前市值处于两类方法之间，意味着市场对储能盈利改善"
            "已有预期，但尚未完全计入高成长情景。"
        ),
        "buy": "估值接近核心区间下沿且储能毛利、回款和自由现金流同步改善时，组合业务的重估更可信。",
        "sell": "若市值逼近上沿而储能单位盈利、动力客户或现金转换未兑现，需防范量增利不增。",
        "future": "跟踪储能出货与单Wh利润、动力客户、消费电池稳定性、投资收益质量和自由现金流。",
        "positive": "储能毛利率提升、应收周转改善并使自由现金流提前转正。",
        "risk": "储能价格竞争、动力项目爬坡不及预期或投资收益掩盖主业现金流。",
    },
    "瑞浦兰钧": {
        "difference_causes": [
            "2026年上半年盈利预告已验证规模效应，但独立模型仍对客户集中、价格和港股融资折价保留约束。",
            "动力与储能分别建模；储能订单不能简单等同于未来三年持续份额。",
        ],
        "operating": (
            "瑞浦兰钧的核心变化是从规模扩张进入盈利验证期。独立模型预计2026—2028年收入322.5/"
            "404.0/487.6亿元，归母净利润14.21/21.72/31.01亿元，自由现金流约-20.24/-15.93/"
            "-8.41亿元。利润转正不等于现金流转正，仍需观察产能利用率、客户回款和资本开支。"
        ),
        "valuation": (
            "2027年12—18倍市盈率对应261—391亿元人民币；PB—ROE给出228—260亿元。当前市值"
            "接近PB约束下沿，若盈利预告可持续且现金流改善，折价有收敛空间；若扩产继续快于订单，"
            "低PB本身不是安全边际。"
        ),
        "buy": "盈利转正后自由现金流缺口持续收窄、储能客户更加分散且估值仍在核心区间下部时更具吸引力。",
        "sell": "若估值先行上修而利用率、回款或毛利率恶化，需警惕扭亏预期被过度交易。",
        "future": "跟踪半年报兑现、动力和储能客户结构、产能利用率、应收账款及自由现金流。",
        "positive": "盈利预告兑现、储能订单分散化且现金流改善快于模型。",
        "risk": "客户集中、价格下行或资本开支使现金流持续承压。",
    },
    "欣旺达": {
        "difference_causes": [
            "模型保留消费电池基本盘，同时单列动力和储能，避免把集团收入全部视为动力电池。",
            "动力业务利润修复慢于收入增长，外部预测若忽略少数股东和资本开支会高估归母与现金流。",
        ],
        "operating": (
            "欣旺达的消费电池提供收入稳定性，动力和储能决定增量，但也带来更高资本占用。独立模型"
            "预计2026—2028年收入734.8/860.5/989.2亿元，归母净利润22.08/27.77/36.27亿元，"
            "自由现金流约-61.30/-53.29/-41.47亿元。集团需要证明动力电池不仅放量，还能改善归母"
            "利润和现金流，否则低PB只反映资产回报偏低。"
        ),
        "valuation": (
            "2027年12—18倍市盈率对应333—500亿元；PB—ROE基于285.07亿元净资产和约11.13%"
            "可持续ROE得到274—307亿元。当前市值接近市盈率区间下沿，但高现金流消耗限制估值上修。"
        ),
        "buy": "动力业务毛利改善、自由现金流缺口收窄且市值仍接近核心区间下沿时，低估值才有质量。",
        "sell": "若动力和储能继续增收但归母、ROE或现金流不改善，或者估值接近上沿，应降低仓位。",
        "future": "跟踪消费电池现金牛、动力电池毛利与客户、储能放量、少数股东损益和资本开支。",
        "positive": "动力盈利改善并转化为归母利润，经营现金流覆盖扩产。",
        "risk": "动力业务量增利薄、少数股东分流或持续扩产压低自由现金流。",
    },
    "鹏辉能源": {
        "difference_causes": [
            "模型以储能出货和可识别扩产为主，未把满产状态机械外推为全年及三年持续高利用率。",
            "正常化市盈率与PB—ROE的差异来自盈利高弹性和净资产基数较小，ROE上升需要现金流验证。",
        ],
        "operating": (
            "鹏辉能源对储能周期最敏感，规模较小使量价和利用率变化被放大。独立模型预计2026—2028年"
            "收入234/308.4/378.7亿元，归母净利润19.73/27.62/35.91亿元，自由现金流约-4.32/"
            "0.59/6.30亿元。若扩产按期且储能毛利维持，现金流可在2027年转正；若价格或回款转弱，"
            "高ROE和估值上沿会快速失效。"
        ),
        "valuation": (
            "2027年14—20倍市盈率对应387—552亿元；PB—ROE给出309—361亿元。当前市值接近"
            "PB约束区间，市场仍未完全计入高盈利情景，但模型ROE超过30%，必须对利用率、应收和"
            "资本开支执行更严格验证。"
        ),
        "buy": "市值处于核心区间下部，储能出货、毛利率和经营现金流均未走弱时，可关注盈利兑现带来的重估。",
        "sell": "若高利用率回落、储能价格下行或回款转弱，即使收入仍增长也应下调目标ROE和估值。",
        "future": "跟踪储能产能利用率、出货、ASP、毛利率、应收账款和扩产后的自由现金流。",
        "positive": "储能毛利稳定、扩产顺利且自由现金流按模型转正。",
        "risk": "储能价格战、利用率回落或应收和资本开支同时上升。",
    },
    "孚能科技": {
        "difference_causes": [
            "2025年8月旧研报不进入当前财务预测中位数；模型以2025年报、2026年一季报和最新产线进度重建。",
            "2026年仍亏损，2027年小幅盈利高度依赖广州、赣州产线爬坡和费用率下降，不能直接套用成熟公司PE。",
        ],
        "operating": (
            "孚能科技仍是扭亏研究，不是稳定盈利研究。独立模型预计2026—2028年收入95/127.4/"
            "168.5亿元，归母净利润-3.38/2.30/8.31亿元，自由现金流约-12/-12.47/-8.44亿元。"
            "2026年一季报收入1.667亿元、毛利率13.82%、归母亏损1.40亿元说明产线爬坡尚未完成；"
            "固态电池和新客户只能作为催化剂，未进入基准收入。"
        ),
        "valuation": (
            "2027年盈利基数过低，12—18倍PE仅给出28—41亿元，经济意义有限；PB—ROE约41—50亿元"
            "也低于当前市值。扭亏期更适合用1.0—1.5倍收入倍数作辅助，并用现金消耗和净资产安全性"
            "约束。当前定价已提前反映更强的2028年盈利或技术期权。"
        ),
        "buy": "只有季度收入、毛利率、费用率和现金流连续证明扭亏路径，且市值回落至不再提前计入远期高盈利时，才出现更可靠买点。",
        "sell": "若产线爬坡、客户放量或费用下降再次延期，而市值仍按成功扭亏交易，应回避技术期权被过度定价。",
        "future": "跟踪广州和赣州产线利用率、核心客户出货、毛利率、费用率、经营现金流及固态电池真实量产节点。",
        "positive": "连续季度毛利和费用率改善、经营现金流收窄并确认新增客户量产。",
        "risk": "产线利用率不足、客户项目延期、持续亏损和融资稀释。",
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _input(
    name: str,
    *,
    value: float | None = None,
    low: float | None = None,
    high: float | None = None,
    unit: str,
    period: str,
    source_ref: str,
    input_type: str,
    method: str,
    limitation: str | None = None,
) -> dict[str, Any]:
    return {
        "input_name": name,
        "value_num": value,
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
    value: float | None = None,
    low: float | None = None,
    high: float | None = None,
    unit: str,
    period: str,
    formula: str,
    substitution: str,
    conclusion: str,
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
        "dependency_group": "battery_company_operating_model",
        "conclusion": conclusion,
    }


def _current_market(snapshot: dict[str, Any], ticker: str) -> dict[str, float | None]:
    if ticker in snapshot["wind"]["current"]:
        row = snapshot["wind"]["current"][ticker]
        return {
            "price": row.get("price"),
            "pb": row.get("pb"),
            "pe": row.get("pe_ttm"),
            "market_cap": row.get("market_cap_cny"),
        }
    info = snapshot["yfinance"][ticker]["info"]
    fx = float(snapshot["fx"]["latest"]["close"])
    market_cap = (
        float(info["marketCap"]) / 1e8 * fx if info.get("marketCap") else None
    )
    return {
        "price": info.get("currentPrice"),
        "pb": info.get("priceToBook"),
        "pe": info.get("trailingPE"),
        "market_cap": market_cap,
    }


def _company_export(
    company: dict[str, Any],
    *,
    snapshot: dict[str, Any],
    artifact_hash: str,
) -> dict[str, Any]:
    name = company["company"]
    ticker = company["ticker"]
    analysis = COMPANY_ANALYSIS[name]
    market = _current_market(snapshot, ticker)
    source_ref = "; ".join(company["sourceRefs"])
    model_ref = f"{RUN_REF}:{ticker}:independent_model:{artifact_hash}"

    inputs: list[dict[str, Any]] = []
    for segment in company["inputs"]["segments"]:
        for year in (2026, 2027, 2028):
            year_key = str(year)
            if segment["kind"] in {"battery_gwh", "vehicle_million_units"}:
                volume_unit = (
                    "GWh" if segment["kind"] == "battery_gwh" else "百万辆"
                )
                inputs.append(
                    _input(
                        f"{segment['name']}出货量",
                        value=float(segment["volume"][year_key]),
                        unit=volume_unit,
                        period=str(year),
                        source_ref=source_ref,
                        input_type="expert_assumption",
                        method=segment["note"],
                        limitation="行业需求、客户份额与产能利用率共同约束，非公司指引。",
                    )
                )
                inputs.append(
                    _input(
                        f"{segment['name']}平均售价",
                        value=float(segment["asp"][year_key]),
                        unit=(
                            "元/Wh"
                            if segment["kind"] == "battery_gwh"
                            else "元/辆"
                        ),
                        period=str(year),
                        source_ref=source_ref,
                        input_type="expert_assumption",
                        method=segment["formula"],
                        limitation="公开资料无法直接观察完整客户结构，采用可复算中性假设。",
                    )
                )
            else:
                inputs.append(
                    _input(
                        f"{segment['name']}收入",
                        value=float(segment["revenue"][year_key]),
                        unit="亿元人民币",
                        period=str(year),
                        source_ref=source_ref,
                        input_type="expert_assumption",
                        method=segment["note"],
                    )
                )
            inputs.append(
                _input(
                    f"{segment['name']}毛利率",
                    value=float(segment["grossMargin"][year_key]) * 100,
                    unit="%",
                    period=str(year),
                    source_ref=source_ref,
                    input_type="expert_assumption",
                    method="参考历史分部毛利、产品结构、价格与产能利用率。",
                )
            )
    for key, label, unit in (
        ("opexRatio", "经营费用率", "%"),
        ("otherPretax", "税前其他收益", "亿元人民币"),
        ("taxRate", "所得税率", "%"),
        ("minority", "少数股东损益", "亿元人民币"),
        ("cashConversion", "经营现金转换率", "倍"),
        ("capex", "资本开支", "亿元人民币"),
        ("payoutRatio", "分红率", "%"),
    ):
        for index, year in enumerate((2026, 2027, 2028)):
            raw_value = float(company["inputs"][key][index])
            if key in {"opexRatio", "taxRate", "payoutRatio"}:
                raw_value *= 100
            inputs.append(
                _input(
                    label,
                    value=raw_value,
                    unit=unit,
                    period=str(year),
                    source_ref=model_ref,
                    input_type="expert_assumption",
                    method="以历史财务、最新报告期和经营情景形成的显式假设。",
                )
            )
    inputs.extend(
        [
            _input(
                "期初归母净资产",
                value=float(company["inputs"]["openingEquity"]),
                unit="亿元人民币",
                period="2025-12-31",
                source_ref=source_ref,
                input_type="direct_fact",
                method="2025年末归母权益。",
            ),
            _input(
                "期初总资产",
                value=float(company["inputs"]["openingAssets"]),
                unit="亿元人民币",
                period="2025-12-31",
                source_ref=source_ref,
                input_type="direct_fact",
                method="2025年末总资产。",
            ),
        ]
    )

    outputs: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    horizon_by_year = {2026: "FY1", 2027: "FY2", 2028: "FY3"}
    metric_map = (
        ("revenue", "营业收入", "亿元人民币"),
        ("netIncome", "归母净利润", "亿元人民币"),
        ("ocf", "经营现金流", "亿元人民币"),
        ("capex", "资本开支", "亿元人民币"),
        ("freeCashFlow", "自由现金流", "亿元人民币"),
        ("endingEquity", "期末归母净资产", "亿元人民币"),
        ("roe", "ROE", "%"),
        ("roa", "ROA", "%"),
    )
    metric_name_map = {
        "revenue": "revenue",
        "netIncome": "net_income",
        "ocf": "operating_cash_flow",
        "capex": "capex",
        "freeCashFlow": "free_cash_flow",
        "endingEquity": "book_value",
        "roe": "roe",
        "roa": "roa",
    }
    for row in company["forecast"]:
        year = int(row["year"])
        for key, label, unit in metric_map:
            value = float(row[key])
            if key in {"roe", "roa"}:
                value *= 100
            formula = (
                row["formula"]
                if key
                in {"revenue", "netIncome", "ocf", "capex", "freeCashFlow"}
                else (
                    "ROE＝归母净利润÷平均归母净资产"
                    if key == "roe"
                    else (
                        "ROA＝归母净利润÷平均总资产"
                        if key == "roa"
                        else "期末净资产＝期初净资产＋归母净利润－分红"
                    )
                )
            )
            outputs.append(
                _output(
                    f"{year}年{label}",
                    value=value,
                    unit=unit,
                    period=str(year),
                    formula=formula,
                    substitution=f"{name} {year}年冻结模型结果＝{value:.2f}{unit}",
                    conclusion="结果取决于同年度量价、毛利率、费用率和现金流假设。",
                )
            )
            observations.append(
                {
                    "metric_name": metric_name_map[key],
                    "value_num": value,
                    "unit": unit,
                    "currency": None if unit == "%" else "CNY",
                    "period_end": f"{year}-12-31",
                    "fiscal_year": year,
                    "fiscal_period": horizon_by_year[year],
                    "frequency": "annual",
                    "fact_type": "internal_estimate",
                    "as_of_date": AS_OF_DATE,
                    "provider": "internal_model",
                    "raw_feature_name": f"{name}{year}年独立模型{label}",
                    "source_snapshot_key": f"independent_{ticker}",
                    "formula": formula,
                    "input_refs": [company["inputHash"], company["outputHash"]],
                    "quality_status": (
                        "limited"
                        if name == "孚能科技" and year >= 2027
                        else "usable"
                    ),
                    "scenario_name": "base",
                    "model_run_key": f"{RUN_REF}:{ticker}:financial:v1",
                }
            )

    financial_run = {
        "run_key": f"{RUN_REF}:{ticker}:financial:v1",
        "skill_name": "company_financial_modeling",
        "model_name": f"{name}分业务量价、利润与现金流桥接",
        "model_role": "primary",
        "forecast_start": "2026-01-01",
        "forecast_end": "2028-12-31",
        "valuation_date": None,
        "assumptions": {
            "model_type": company["modelType"],
            "no_consensus_input": True,
            "input_artifact_hash": company["inputHash"],
            "output_artifact_hash": company["outputHash"],
        },
        "limitations": "未来量价、产能利用率和利润率包含显式研究假设；不把规划产能、技术样品或行业增速自动视为公司收入。",
        "finalization": "independent",
        "inputs": inputs,
        "outputs": outputs,
        "reconciliations": [],
    }

    pe_method = next(
        item for item in company["valuationMethods"] if item["method"] == "正常化市盈率"
    )
    pb_method = next(
        item for item in company["valuationMethods"] if item["method"] == "PB—ROE"
    )
    reverse_method = next(
        item
        for item in company["valuationMethods"]
        if item["method"] == "当前市场隐含市盈率"
    )
    fy2 = company["forecast"][1]
    share_count_100m = (
        float(market["market_cap"]) / float(market["price"])
        if market.get("market_cap") and market.get("price")
        else None
    )
    scenario_results: list[dict[str, Any]] = []
    for scenario_name, label, revenue_factor, margin_factor, pe in (
        ("downside", "下行情景", 0.90, 0.80, float(pe_method["lowParameter"])),
        (
            "base",
            "基准情景",
            1.00,
            1.00,
            (float(pe_method["lowParameter"]) + float(pe_method["highParameter"]))
            / 2,
        ),
        ("upside", "上行情景", 1.08, 1.15, float(pe_method["highParameter"])),
    ):
        revenue = float(fy2["revenue"]) * revenue_factor
        net_income = float(fy2["netIncome"]) * margin_factor
        ocf = float(fy2["ocf"]) * margin_factor
        capex = float(fy2["capex"]) * (1.05 if scenario_name == "upside" else 1.0)
        fcf = ocf - capex
        target_cap = net_income * pe
        scenario_results.append(
            {
                "scenario_name": scenario_name,
                "scenario_label": label,
                "condition": {
                    "downside": "出货或销量低于基准10%，单位盈利仅达到基准80%。",
                    "base": "量价、毛利、费用率和资本开支按冻结模型兑现。",
                    "upside": "收入高于基准8%，规模效应使归母净利润高于基准15%。",
                }[scenario_name],
                "revenue": revenue,
                "net_income": net_income,
                "operating_cash_flow": ocf,
                "capex": capex,
                "free_cash_flow": fcf,
                "target_pe": pe,
                "target_market_cap": target_cap,
                "target_price": (
                    target_cap / share_count_100m if share_count_100m else 0.0
                ),
            }
        )

    valuation_outputs = [
        _output(
            "正常化市盈率目标市值",
            low=float(pe_method["valueLow"]),
            high=float(pe_method["valueHigh"]),
            unit="亿元人民币",
            period="2027",
            formula=pe_method["formula"],
            substitution=(
                f"{float(pe_method['basisValue']):.2f}亿元×"
                f"{float(pe_method['lowParameter']):.2f}—"
                f"{float(pe_method['highParameter']):.2f}倍"
            ),
            conclusion=pe_method["parameterBasis"],
        ),
        _output(
            "PB—ROE目标市值",
            low=float(pb_method["valueLow"]),
            high=float(pb_method["valueHigh"]),
            unit="亿元人民币",
            period="2027",
            formula=pb_method["formula"],
            substitution=(
                f"{float(pb_method['basisValue']):.2f}亿元净资产×"
                f"{float(pb_method['lowParameter']):.2f}—"
                f"{float(pb_method['highParameter']):.2f}倍PB"
            ),
            conclusion=pb_method["parameterBasis"],
        ),
        _output(
            "当前市值隐含FY2市盈率",
            value=float(reverse_method["impliedMultiple"]),
            unit="倍",
            period=AS_OF_DATE,
            formula=reverse_method["formula"],
            substitution=(
                f"{float(reverse_method['valueLow']):.2f}亿元÷"
                f"{float(reverse_method['basisValue']):.2f}亿元"
            ),
            conclusion=reverse_method["parameterBasis"],
        ),
    ]
    if name == "孚能科技":
        revenue_2027 = float(fy2["revenue"])
        valuation_outputs.append(
            _output(
                "收入倍数辅助目标市值",
                low=revenue_2027,
                high=revenue_2027 * 1.5,
                unit="亿元人民币",
                period="2027",
                formula="目标市值＝FY2营业收入×目标市销率",
                substitution=f"{revenue_2027:.2f}亿元×1.00—1.50倍",
                conclusion="扭亏早期PE经济意义有限，PS只作现金消耗和净资产约束下的辅助方法。",
            )
        )
    current_pb = float(market["pb"]) if market.get("pb") else None
    valuation_run = {
        "run_key": f"{RUN_REF}:{ticker}:valuation:v1",
        "skill_name": "company_valuation_modeling",
        "model_name": f"{name}多方法估值与市场隐含预期",
        "model_role": "core",
        "forecast_start": "2026-01-01",
        "forecast_end": "2028-12-31",
        "valuation_date": AS_OF_DATE,
        "assumptions": {
            "valuation_role": "core",
            "no_consensus_input": True,
            "company_detail_summary": {
                "conclusion": (
                    f"{analysis['valuation']} 当前总市值约"
                    f"{float(market['market_cap']):.2f}亿元人民币；"
                    "价格判断必须同时满足相应经营和现金流条件。"
                ),
                "scenario_results": scenario_results,
                "difference_causes": analysis["difference_causes"],
                "operating_analysis": analysis["operating"],
                "valuation_analysis": analysis["valuation"],
                "buy_point_analysis": analysis["buy"],
                "sell_point_analysis": analysis["sell"],
                "future_view": analysis["future"],
                "positive_trigger": analysis["positive"],
                "risk_trigger": analysis["risk"],
            },
            "scenario_workbench": {
                "simple_ready": bool(current_pb and current_pb > 0),
                "detailed_ready": False,
                "default_mode": "simple",
                "reason": "公司页默认使用净利润—留存—净资产—目标PB简化桥接；分业务量价和现金流详细调整进入锂电池行业计算器。",
                "simple": {
                    "opening_book_value_cny_100m": float(
                        company["inputs"]["openingEquity"]
                    ),
                    "current_pb": current_pb,
                    "target_pb": current_pb,
                    "years": [
                        {
                            "fiscal_year": int(row["year"]),
                            "net_income_cny_100m": float(row["netIncome"]),
                            "payout_ratio_pct": float(
                                company["inputs"]["payoutRatio"][
                                    int(row["year"]) - 2026
                                ]
                            )
                            * 100,
                        }
                        for row in company["forecast"]
                    ],
                    "pb_presets": {
                        "current": current_pb,
                        "research_low": float(pb_method["lowParameter"]),
                        "research_mid": (
                            float(pb_method["lowParameter"])
                            + float(pb_method["highParameter"])
                        )
                        / 2,
                        "research_high": float(pb_method["highParameter"]),
                    },
                },
                "detailed": {
                    "available_fields": [
                        "分业务出货或销量",
                        "ASP与毛利率",
                        "费用率、资本开支与现金转换",
                    ],
                    "missing_required_fields": [
                        "公司页通用实验台尚未提供分业务编辑器，请使用锂电池行业计算器。",
                    ],
                },
            },
            "pb_framework": {
                "applicability": (
                    "核心交叉验证"
                    if name in {"宁德时代", "比亚迪", "亿纬锂能"}
                    else "资产回报诊断"
                ),
                "cycle_sensitivity": "高；产能利用率和ASP会同时改变盈利、净资产积累与市场目标PB。",
                "asset_intensity": company["modelType"],
                "basis": pb_method["parameterBasis"],
                "price_exposure": "锂电池ASP、原材料成本和产品结构通过毛利率传导。",
                "profit_driver": "出货或销量×ASP×毛利率－费用，并由资本开支和营运资本转化为现金流。",
                "tags": ["锂电池", "产能利用率", "PB—ROE", "现金流", "资本开支"],
            },
        },
        "limitations": "正常化PE是核心方法，PB—ROE用于检验资产回报与估值一致性；两者共享盈利假设，不机械平均。孚能科技扭亏期的PE仅作诊断。",
        "finalization": "independent",
        "inputs": [
            _input(
                "FY2归母净利润",
                value=float(pe_method["basisValue"]),
                unit="亿元人民币",
                period="2027",
                source_ref=f"{RUN_REF}:{ticker}:financial:v1",
                input_type="derived_fact",
                method="来自先冻结的独立公司财务模型。",
            ),
            _input(
                "正常化市盈率",
                low=float(pe_method["lowParameter"]),
                high=float(pe_method["highParameter"]),
                unit="倍",
                period=AS_OF_DATE,
                source_ref=model_ref,
                input_type="expert_assumption",
                method=pe_method["parameterBasis"],
            ),
            _input(
                "FY2期末归母净资产",
                value=float(pb_method["basisValue"]),
                unit="亿元人民币",
                period="2027",
                source_ref=f"{RUN_REF}:{ticker}:financial:v1",
                input_type="derived_fact",
                method="期初归母权益＋留存利润。",
            ),
            _input(
                "PB—ROE合理PB",
                low=float(pb_method["lowParameter"]),
                high=float(pb_method["highParameter"]),
                unit="倍",
                period=AS_OF_DATE,
                source_ref=model_ref,
                input_type="derived_fact",
                method=pb_method["parameterBasis"],
            ),
        ],
        "outputs": valuation_outputs,
        "reconciliations": [],
    }
    return {
        "research_company_id": int(company["companyId"]),
        "security": {
            "canonical_name": name,
            "ticker": ticker,
            "market": "港股" if ticker.endswith(".HK") else "A股",
            "listing_status": "hk_share" if ticker.endswith(".HK") else "a_share",
            "reporting_currency": "CNY",
            "identity_status": "verified",
        },
        "source_snapshots": [
            {
                "key": f"independent_{ticker}",
                "provider": "internal_model",
                "source_channel": "internal_calculation",
                "source_ref": model_ref,
                "title": f"{name}锂电池分业务独立财务模型",
                "publisher": "本研究",
                "as_of_date": AS_OF_DATE,
                "content_hash": artifact_hash,
                "raw_snapshot_path": str(MODEL_PATH.relative_to(ROOT)),
                "metadata": {
                    "frozen_before_external_reconciliation": True,
                    "database_boundary": "financial.db only",
                },
            }
        ],
        "model_runs": [financial_run, valuation_run],
        "observations": observations,
    }


def build(output_path: Path) -> dict[str, Any]:
    models = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    artifact_hash = _sha256(MODEL_PATH)
    payload = {
        "export_schema_version": "company_financial_profile_export.v1",
        "research_run_ref": RUN_REF,
        "as_of_date": AS_OF_DATE,
        "source_artifacts": [
            {
                "path": str(MODEL_PATH.relative_to(ROOT)),
                "sha256": artifact_hash,
            }
        ],
        "companies": [
            _company_export(
                company, snapshot=snapshot, artifact_hash=artifact_hash
            )
            for company in models["companies"]
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "output": str(output_path),
        "companies": len(payload["companies"]),
        "models": sum(len(row["model_runs"]) for row in payload["companies"]),
        "observations": sum(
            len(row["observations"]) for row in payload["companies"]
        ),
        "artifact_sha256": artifact_hash,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(build(args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
