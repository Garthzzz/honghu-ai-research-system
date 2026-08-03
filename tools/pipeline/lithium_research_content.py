from __future__ import annotations

"""Reader-facing narrative package for the lithium and lithium-carbonate libraries.

The module deliberately reads frozen research artifacts.  Supplier market and
financial observations remain in financial.db and are rendered by company
pages; the Markdown package only carries reproducible model conclusions and
links to those pages.
"""

import json
import re
from pathlib import Path
from typing import Any

from .lithium_research_data import SOURCE_SPECS


ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "cache" / "lithium_research"
MODEL_PATH = CACHE / "models" / "lithium_company_independent_models_v1.json"
RECON_PATH = CACHE / "models" / "lithium_external_reconciliation_v1.json"
LITHIUM_SD_PATH = CACHE / "models" / "lithium_supply_demand_model_v1.json"
CARBONATE_SD_PATH = CACHE / "models" / "carbonate_supply_demand_model_v1.json"
AS_OF_DATE = "2026-07-27"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _cite(source_ids: dict[str, int], *refs: str) -> str:
    return " ".join(f"^src:{source_ids[ref]}" for ref in refs if ref in source_ids)


def _link(company: dict[str, Any]) -> str:
    return f"[{company['company']}](/company/{company['research_company_id']})"


def _join_cn_sentences(items: list[Any], *, final: bool = True) -> str:
    """Join already punctuated Chinese evidence without producing ``。；``."""
    text = "；".join(
        str(item).strip().rstrip("。；; ")
        for item in items
        if str(item).strip().rstrip("。；; ")
    )
    return text + ("。" if text and final else "")


def _source_index(source_ids: dict[str, int], text: str) -> str:
    """Append a readable index for sources actually cited by this document."""
    cited_ids = [
        int(value) for value in dict.fromkeys(re.findall(r"\^src:(\d+)", text))
    ]
    if not cited_ids:
        return ""
    ref_by_id = {int(value): ref for ref, value in source_ids.items()}
    spec_by_ref = {
        str(item["source_ref"]): item for item in SOURCE_SPECS
    }
    lines = ["## 来源索引", ""]
    for source_id in cited_ids:
        ref = ref_by_id.get(source_id)
        item = spec_by_ref.get(str(ref))
        if not item:
            continue
        lines.append(
            f"- ^src:{source_id} {item['publisher']}，"
            f"{item['title']}，{item.get('publish_date') or '日期未标注'}。"
        )
    return "\n".join(lines) + "\n" if len(lines) > 2 else ""


def _with_source_indexes(
    documents: dict[str, str],
    source_ids: dict[str, int],
) -> dict[str, str]:
    return {
        name: (
            text.rstrip()
            + (
                "\n\n" + index.rstrip()
                if (index := _source_index(source_ids, text))
                else ""
            )
            + "\n"
        )
        for name, text in documents.items()
    }


def _front(
    *,
    industry_id: int,
    name: str,
    title: str,
    dynamic: str,
) -> str:
    return f"""---
entity_type: industry
entity_id: {industry_id}
name: {name}
parent: 有色金属
status: 深度跟踪
tier: 1
last_updated: {AS_OF_DATE}
author: codex_research_loop
ai_synthesized: true
research_track: B
research_prompt: 锂与碳酸锂行业_公司详情_估值及网页计算器_Guidance.md
document_title: {title}
core_dynamic: "{dynamic}"
data_tier_note: "政府、国际组织和公司公告用于锚定事实；2026—2028供需、公司盈利和估值为冻结的研究情景，不伪装成官方预测。"
---
"""


def _balance_table(model: dict[str, Any], *, carbonate: bool = False) -> str:
    rows = model["rows"] if carbonate else model["base_rows"]
    lines = [
        "| 年份 | 可用供给 | 需求 | 余额 | 余额/需求 | 数值性质 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        supply = row["available_supply_mt"] if carbonate else row["available_supply_mt_lce"]
        demand = row["demand_mt"] if carbonate else row["demand_mt_lce"]
        balance = row["balance_mt"] if carbonate else row["balance_mt_lce"]
        ratio = balance / demand * 100 if demand else 0
        status = row.get("status") or ("公开约束下重建" if row["year"] == 2025 else "研究估算")
        lines.append(
            f"| {row['year']} | {supply:.2f} | {demand:.2f} | {balance:+.2f} | "
            f"{ratio:+.2f}% | {status} |"
        )
    return "\n".join(lines)


def _supply_scenarios(model: dict[str, Any]) -> str:
    lines = [
        "| 情景 | 2026余额 | 2028余额 | 2030余额 | 2031余额 | 需要发生什么 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    explanations = {
        "投产顺利情景": "相对官方基准，供给高3%—10%、需求低2%—5%的压力测试",
        "基准情景": "澳大利亚政府2026年6月公布的同口径全球供需序列",
        "投产受限且需求偏强情景": "相对官方基准，供给低3%—10%、需求高2%—5%的压力测试",
    }
    for name, rows in model["scenarios"].items():
        values = {int(row["year"]): float(row["balance_mt_lce"]) for row in rows}
        lines.append(
            f"| {name} | {values[2026]:+.2f} | {values[2028]:+.2f} | "
            f"{values[2030]:+.2f} | {values[2031]:+.2f} | {explanations[name]} |"
        )
    return "\n".join(lines)


def _broker_reconciliation_table(
    companies: list[dict[str, Any]],
    recon_by_name: dict[str, dict[str, Any]],
) -> str:
    """Show who contributed to the recent-report median and when."""
    lines = [
        "| 公司 | 最近报告区间 | 机构数 | 2026E独立利润 | Wind一致预期 | 最近机构中位数 | 核心差异 |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for company in companies:
        recon = recon_by_name[company["company"]]
        row = next(
            item for item in recon["yearly_reconciliation"]
            if int(item["year"]) == 2026
        )
        broker = row.get("recent_broker_median") or {}
        independent = row["independent"]["net_income_rmb_bn"] * 10
        wind_value = (row.get("wind_consensus") or {}).get("net_income_rmb_bn")
        broker_value = broker.get("net_income_rmb_bn_median")
        institutions = "、".join((broker.get("institutions") or [])[:5])
        if int(broker.get("institution_count") or 0) > 5:
            institutions += "等"
        date_start = broker.get("report_date_start")
        date_end = broker.get("report_date_end")
        period = (
            f"{str(date_start)[:4]}-{str(date_start)[4:6]}-{str(date_start)[6:]}至"
            f"{str(date_end)[:4]}-{str(date_end)[4:6]}-{str(date_end)[6:]}"
            if date_start and date_end else "没有足够近期机构样本"
        )
        lines.append(
            f"| {_link(company)} | {period} | {broker.get('institution_count') or 0} "
            f"（{institutions or '—'}） | {independent:.2f} | "
            f"{wind_value * 10:.2f} "
            if wind_value is not None
            else f"| {_link(company)} | {period} | {broker.get('institution_count') or 0} "
                 f"（{institutions or '—'}） | {independent:.2f} | — "
        )
        # Complete the row separately to keep optional numeric formatting clear.
        lines[-1] += (
            f"| {broker_value * 10:.2f} | {recon['difference_summary']} |"
            if broker_value is not None
            else f"| — | {recon['difference_summary']} |"
        )
    return "\n".join(lines)


def _company_model_table(
    companies: list[dict[str, Any]],
    recon_by_name: dict[str, dict[str, Any]],
) -> str:
    lines = [
        "| 公司 | 2025归母净利 | 2026E基准 | 2027E基准 | 2028E基准 | 2026 Wind一致预期 | 研究差异 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for company in companies:
        base = {int(row["year"]): row for row in company["scenarios"]["基准情景"]}
        recon = recon_by_name.get(company["company"], {})
        yr = next(
            (row for row in recon.get("yearly_reconciliation", []) if int(row["year"]) == 2026),
            None,
        )
        consensus = yr.get("wind_consensus") if yr else None
        consensus_ni = consensus.get("net_income_rmb_bn") if consensus else None
        diff = (
            yr.get("difference_vs_wind_pct", {}).get("net_income")
            if yr and consensus
            else None
        )
        lines.append(
            "| {name} | {actual:.2f} | {fy1:.2f} | {fy2:.2f} | {fy3:.2f} | {consensus} | {diff} |".format(
                name=_link(company),
                actual=company["actual_2025"]["net_income_rmb_bn"] * 10,
                fy1=base[2026]["net_income_rmb_bn"] * 10,
                fy2=base[2027]["net_income_rmb_bn"] * 10,
                fy3=base[2028]["net_income_rmb_bn"] * 10,
                consensus=(
                    f"{consensus_ni * 10:.2f}" if consensus_ni is not None else "公开一致预期不足"
                ),
                diff=(f"{diff:+.1f}%" if diff is not None else "不比较"),
            )
        )
    return "\n".join(lines)


def _valuation_table(
    companies: list[dict[str, Any]],
    recon_by_name: dict[str, dict[str, Any]],
) -> str:
    lines = [
        "| 公司 | 2027基准净利 | 正常化PE价值 | PB—ROE价值 | FCFE比较值 | 当前市值 | 研究判断 |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for company in companies:
        base = {int(row["year"]): row for row in company["scenarios"]["基准情景"]}
        vals = {row["method"]: row for row in company["valuations"]}
        pe = vals.get("正常化市盈率")
        pb = vals.get("PB—ROE")
        fcfe = vals.get("股权自由现金流")
        market = recon_by_name.get(company["company"], {}).get("market_reconciliation", {})
        market_cap = market.get("market_cap_rmb_bn")
        core_range = company["independent_equity_value_range"]
        low_raw = core_range.get("low_rmb_bn")
        high_raw = core_range.get("high_rmb_bn")
        low = low_raw * 10 if low_raw is not None else None
        high = high_raw * 10 if high_raw is not None else None
        current = market_cap * 10 if market_cap is not None else None
        if low is None or high is None:
            judgment = "缺少可复算核心方法，暂不评级"
        elif current is None:
            judgment = "当前市场数据不足，只展示模型区间"
        elif current < low:
            judgment = "当前市值低于核心方法下沿，先核验项目和现金流"
        elif current > high:
            judgment = "当前市值高于核心方法上沿，兑现要求偏高"
        else:
            judgment = "当前市值位于核心方法区间，选择取决于周期与项目兑现"

        def vrange(value: dict[str, Any] | None) -> str:
            return (
                f"{value['low_rmb_bn'] * 10:.0f}—{value['high_rmb_bn'] * 10:.0f}"
                f"（{value['role']}）"
                if value
                and value.get("low_rmb_bn") is not None
                and value.get("high_rmb_bn") is not None
                else (
                    f"未采用（{value.get('limitation', '数据不足')}）"
                    if value else "不适用"
                )
            )

        lines.append(
            f"| {_link(company)} | {base[2027]['net_income_rmb_bn'] * 10:.2f} | "
            f"{vrange(pe)} | {vrange(pb)} | {vrange(fcfe)} | "
            f"{current:.2f} | {judgment} |"
            if current is not None
            else
            f"| {_link(company)} | {base[2027]['net_income_rmb_bn'] * 10:.2f} | "
            f"{vrange(pe)} | {vrange(pb)} | {vrange(fcfe)} | 暂缺 | {judgment} |"
        )
    return "\n".join(lines)


def _valuation_parameter_table(companies: list[dict[str, Any]]) -> str:
    lines = [
        "| 公司 | 正常化PE上下限怎样得到 | PB—ROE上下限怎样得到 | FCFE上下限怎样得到 |",
        "|---|---|---|---|",
    ]
    for company in companies:
        vals = {row["method"]: row for row in company["valuations"]}
        pe = vals.get("正常化市盈率")
        pb = vals.get("PB—ROE")
        fcfe = vals.get("股权自由现金流")
        nav = vals.get("条件化项目NAV")
        if pe:
            pe_inputs = pe["inputs"]
            pe_text = (
                f"{pe_inputs['net_income_rmb_bn'] * 10:.2f}亿元×"
                f"{pe_inputs['pe_range'][0]:.2f}—{pe_inputs['pe_range'][1]:.2f}倍。"
                f"{pe.get('parameter_basis', '')}"
            )
        else:
            pe_text = "基准利润不为正，关闭PE。"
        if pb:
            pb_inputs = pb["inputs"]
            pb_text = (
                "合理PB＝（ROE－g）÷（Ke－g）；可持续ROE"
                f"{pb_inputs['sustainable_roe_range_pct'][0]:.2f}%—"
                f"{pb_inputs['sustainable_roe_range_pct'][1]:.2f}%，"
                f"低值Ke/g＝{pb_inputs['low_value_cost_of_equity_pct']:.2f}%/"
                f"{pb_inputs['low_value_terminal_growth_pct']:.2f}%，"
                f"高值Ke/g＝{pb_inputs['high_value_cost_of_equity_pct']:.2f}%/"
                f"{pb_inputs['high_value_terminal_growth_pct']:.2f}%；"
                f"得到{pb_inputs['pb_range'][0]:.2f}—"
                f"{pb_inputs['pb_range'][1]:.2f}倍PB。"
            )
        else:
            pb_text = (
                "预测ROE不足以覆盖长期增长或净资产不代表稳定经营资本，关闭PB—ROE。"
            )
        if fcfe:
            f_inputs = fcfe["inputs"]
            fcfe_text = (
                "三年FCFE为"
                + "/".join(
                    f"{value * 10:.2f}" for value in f_inputs["fcfe_rmb_bn"]
                )
                + "亿元；低值Ke/g＝"
                f"{f_inputs['low_value_cost_of_equity_pct']:.2f}%/"
                f"{f_inputs['low_value_terminal_growth_pct']:.2f}%，高值＝"
                f"{f_inputs['high_value_cost_of_equity_pct']:.2f}%/"
                f"{f_inputs['high_value_terminal_growth_pct']:.2f}%。"
            )
        elif nav:
            fcfe_text = (
                f"FCFE关闭；{nav.get('parameter_basis', '')}"
                f"{nav.get('limitation', '')}"
            )
        else:
            fcfe_text = "缺少正的连续现金流，关闭FCFE。"
        lines.append(
            f"| {_link(company)} | {pe_text} | {pb_text} | {fcfe_text} |"
        )
    return "\n".join(lines)


def _scenario_financial_table(
    companies: list[dict[str, Any]],
    recon_by_name: dict[str, dict[str, Any]],
) -> str:
    """Compare a common 2027 horizon without pretending the companies are identical."""
    lines = [
        "| 公司 | 2027下行情景净利 | 2027基准净利 | 2027上行情景净利 | 基准ROE | 基准FCFE近似值 | 当前市值 | 当前市值/基准利润 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for company in companies:
        scenario_rows = {
            scenario: {
                int(row["year"]): row
                for row in rows
            }
            for scenario, rows in company["scenarios"].items()
        }
        downside = scenario_rows["下行情景"][2027]
        base = scenario_rows["基准情景"][2027]
        upside = scenario_rows["上行情景"][2027]
        market = recon_by_name.get(company["company"], {}).get(
            "market_reconciliation", {}
        )
        market_cap = market.get("market_cap_rmb_bn")
        implied_pe = (
            market_cap / base["net_income_rmb_bn"]
            if market_cap is not None and base["net_income_rmb_bn"] > 0
            else None
        )
        market_cap_text = (
            f"{market_cap * 10:.2f}" if market_cap is not None else "暂缺"
        )
        implied_pe_text = f"{implied_pe:.2f}倍" if implied_pe is not None else "不适用"
        fcfe_value = 0.0 if abs(base["fcfe_rmb_bn"]) < 0.00005 else base["fcfe_rmb_bn"]
        lines.append(
            f"| {_link(company)} | {downside['net_income_rmb_bn'] * 10:.2f} | "
            f"{base['net_income_rmb_bn'] * 10:.2f} | "
            f"{upside['net_income_rmb_bn'] * 10:.2f} | "
            f"{base['roe_pct']:.2f}% | {fcfe_value * 10:.2f} | "
            f"{market_cap_text} | {implied_pe_text} |"
        )
    return "\n".join(lines)


def _market_expectation_table(
    companies: list[dict[str, Any]],
    recon_by_name: dict[str, dict[str, Any]],
) -> str:
    """Expose what the current price is asking the operating model to deliver."""
    lines = [
        "| 公司 | 交易日 | 当前价 | 当前市值 | 市盈率TTM | 供应商前瞻PE | 独立模型FY1/FY2隐含PE | PB | ROE TTM |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for company in companies:
        market = recon_by_name.get(company["company"], {}).get(
            "market_reconciliation", {}
        )

        def show(key: str, suffix: str = "") -> str:
            value = market.get(key)
            return f"{value:.2f}{suffix}" if value is not None else "—"

        market_cap = market.get("market_cap_rmb_bn")
        market_cap_text = (
            f"{market_cap * 10:.2f}亿元" if market_cap is not None else "—"
        )
        lines.append(
            f"| {_link(company)} | {market.get('trade_date') or '—'} | "
            f"{show('price_cny', '元')} | {market_cap_text} | "
            f"{show('pe_ttm', '倍')} | {show('pe_forward_supplier', '倍')} | "
            f"{show('independent_implied_pe_fy1', '倍')}/{show('independent_implied_pe_fy2', '倍')} | "
            f"{show('pb', '倍')} | {show('roe_ttm_pct', '%')} |"
        )
    return "\n".join(lines)


def _company_project_table(
    companies: list[dict[str, Any]],
    source_ids: dict[str, int],
) -> str:
    operating_fields: dict[str, tuple[str, str, str, str]] = {
        "赣锋锂业": (
            "Cauchari-Olaroz、Goulamina、Mariana及国内锂盐线",
            "Cauchari 46.67%；Goulamina 65%；其余逐项目按并表或权益法",
            "Cauchari碳酸锂3.41万吨；Goulamina干基精矿33.66万吨",
            "Cauchari 2026年目标3.5—4.0万吨；Mariana、加不斯和四川锂盐线继续爬坡",
        ),
        "融捷股份": (
            "甲基卡134号脉采选与联营锂盐线",
            "矿山并表；锂盐合并与联营产能分开",
            "锂精矿18.56万吨；采矿105万吨原矿/年、选矿45万吨原矿/年",
            "新增35万吨/年选矿与联营锂盐线扩建按许可、建设和稳定产量分期",
        ),
        "盛新锂能": (
            "业隆沟、Sabi Star、木绒与锂盐加工",
            "在产矿与待开发木绒分别计量，不把设计产能当权益销量",
            "精矿能力7.5＋29万吨/年；锂盐能力13.7万吨/年",
            "木绒300万吨原矿处理项目决定2027—2028自给率和资本开支",
        ),
        "盐湖股份": (
            "察尔汗盐湖碳酸锂与钾肥",
            "盐湖锂并表；钾肥利润和锂利润分部处理",
            "碳酸锂产量4.65万吨、销量4.56万吨",
            "新增4万吨/年装置按试生产、稳定运行、合格品和销量逐步计入",
        ),
        "大中矿业": (
            "鸡脚山、加达锂矿与现有铁矿业务",
            "锂项目尚处建设；铁矿为当前并表现金来源",
            "锂项目尚无稳定商业销量",
            "鸡脚山一期2万吨计划2026年投产；加达预计2027年开始贡献",
        ),
        "雅化集团": (
            "Kamativi、李家沟、锂盐加工与民爆",
            "矿端权益/包销、加工利润和民爆利润分开",
            "Kamativi精矿能力35万吨/年；李家沟18—20万吨/年；锂盐13万吨/年",
            "两矿稳定供料、锂盐实际销量和加工价差共同决定利润",
        ),
        "天华新能": (
            "Ogapa、金子峰与氢氧化锂/碳酸锂加工",
            "Ogapa经济权益37.5%；矿端权益与加工业务分别计量",
            "氢氧化锂5.95万吨、碳酸锂4.74万吨；锂盐能力16.5万吨/年",
            "金子峰计划2027年贡献，需同时验证资源供给、产品结构和现金转换",
        ),
        "天齐锂业": (
            "Greenbushes、CGP3、锂盐加工与SQM权益",
            "Greenbushes穿透权益26.01%；SQM权益收益和少数股东单列",
            "Greenbushes精矿135万吨，其中化学级约130万吨",
            "CGP3在2026年初出产品；后续看产量、成本、分红和公司层现金",
        ),
        "永杉锂业": (
            "外购原料的碳酸锂与氢氧化锂加工",
            "资源覆盖按零处理，利润来自采购—产品价差",
            "碳酸锂1.3814万吨、氢氧化锂1.4463万吨；现有能力4.5万吨/年",
            "2.2万吨扩建目标2026年10月投产，必须与原料、利用率和周转联立",
        ),
        "中矿资源": (
            "Bikita矿山、国内锂盐与铯铷业务",
            "Bikita并表；不同精矿品位、锂盐转换和铯铷利润分开",
            "两条200万吨原矿/年选矿线，各约30万吨精矿设计能力",
            "锂盐能力7.1万吨/年；津巴布韦本地加工规则决定新增资本和产品形态",
        ),
        "藏格矿业": (
            "察尔汗现有锂、钾肥、铜权益与Mamico",
            "Mamico间接权益约26.95%；钾肥、铜和锂分部处理",
            "碳酸锂产量0.8808万吨、销量0.8957万吨",
            "Mamico名义5万吨项目只按穿透权益、建设和爬坡计入",
        ),
        "西藏城投": (
            "龙木错、结则茶卡盐湖与地产存量业务",
            "国能矿业41%权益；项目未商业化，不并入成熟锂业务",
            "约390万吨LCE资源；尚无稳定商业产量",
            "7＋3万吨规划须依次跨过融资、建设、试车、品质和销售",
        ),
        "永兴材料": (
            "宜春锂云母采选冶与特钢",
            "锂业务并表；特钢利润和现金单列",
            "锂业务产量2.4823万吨",
            "后续增量取决于品位、环保尾渣、采选冶稳定和合格品销量",
        ),
    }
    lines = [
        "| 公司 | 经营类型 | 核心资源/项目 | 权益与会计归属 | 2025实际产量或能力 | 2026/2027/2028基准销量（万吨LCE） | 资源或权益覆盖 | 资源全现金成本假设（万元/吨） | 2027归母利润/FCFE | 2026—2028验证节点 |",
        "|---|---|---|---|---|---:|---:|---:|---:|---|",
    ]
    for company in companies:
        a = company["assumptions"]
        volumes = "/".join(f"{a['product_volume'][str(y)]:g}" for y in (2026, 2027, 2028))
        shares = "/".join(f"{a['resource_share'][str(y)] * 100:.0f}%" for y in (2026, 2027, 2028))
        costs = "/".join(
            (
                "不适用"
                if a["resource_share"][str(y)] <= 0
                else f"{a['resource_cost'][str(y)]:g}"
            )
            for y in (2026, 2027, 2028)
        )
        base_2027 = next(
            row
            for row in company["scenarios"]["基准情景"]
            if int(row["year"]) == 2027
        )
        asset, ownership, actual, milestone = operating_fields[company["company"]]
        lines.append(
            f"| {_link(company)} | {company['model_type']} | {asset} | "
            f"{ownership} | {actual} | {volumes} | {shares} | {costs} | "
            f"{base_2027['net_income_rmb_bn'] * 10:.2f}/"
            f"{base_2027['fcfe_rmb_bn'] * 10:.2f}亿元 | {milestone} |"
        )
    return "\n".join(lines)


def _common_company_analysis(
    companies: list[dict[str, Any]],
    source_ids: dict[str, int],
) -> str:
    by_name = {row["company"]: row for row in companies}
    cid = {
        name: f"ar_{row['ticker'].replace('.', '_')}_2025"
        for name, row in by_name.items()
    }
    c = lambda name: _cite(source_ids, cid[name])
    return f"""
### 全球一体化与资源控制

{_link(by_name['赣锋锂业'])}的优势是资源形态、国家和产品多元，Cauchari-Olaroz、Goulamina、Mariana与国内锂盐线能够形成矿—盐—电池材料组合；代价是项目多、资本开支大、权益法与并表口径复杂。模型没有把每一个规划项目都按名义产能纳入销量，而是把2026—2028产品销量设为12.5/16.0/19.0万吨LCE、资源自给或权益覆盖比例设为80%/82%/84%。如果Goulamina与阿根廷盐湖爬坡慢一个年度，利润受到的不是单纯销量损失，还包括外购原料占比上升和现金回收延后。{c('赣锋锂业')}

{_link(by_name['天齐锂业'])}的核心不是锂盐名义产能，而是Greenbushes的低成本资源和26.01%穿透权益。2025年Greenbushes锂精矿产量135万吨，其中化学级约130万吨；这使公司在低锂价下仍有成本支撑，但少数股东、海外税负、SQM权益收益与资本结构会放大归母利润与经营现金流的差异。PB—ROE只有在把高周期ROE折回可持续水平后才有意义，不能把资源景气顶点的ROE永久化。{c('天齐锂业')}

### 中国盐湖与低成本锂云母

{_link(by_name['盐湖股份'])}的锂业务依托察尔汗盐湖，原有4万吨加新增4万吨碳酸锂项目，但公司利润基座仍有钾肥。其投资逻辑不是最高锂价弹性，而是低成本盐湖、钾肥现金流和新增装置稳定运行的组合；模型因此将非锂利润单独列示。若新装置达产而碳酸锂价格回落，销量可以增长但单位盈利下降，ROE未必同步提升。{c('盐湖股份')}

{_link(by_name['永兴材料'])}以低成本锂云母与特钢双主业形成现金流缓冲，2025年锂业务产量2.4823万吨。模型看重一体化程度、渣处理和采选冶稳定性，而不把“云母资源量”直接当作低成本产量；环保、尾渣和地方监管都会改变现金成本与持续产量。{c('永兴材料')}

{_link(by_name['藏格矿业'])}现有碳酸锂设计产能1万吨、2025年销量0.8957万吨，钾肥产量103.32万吨提供盈利基座；Mamico 5万吨规划项目只有约26.95%间接权益，不能把100%项目产能全部计入归母销量。模型把现有盐湖、钾肥和远期海外期权分开估值，避免一个远期项目把短期利润抬得过高。{c('藏格矿业')}

### 非洲矿山与锂盐加工

{_link(by_name['中矿资源'])}拥有Bikita资源与418万吨/年选矿能力，锂盐产能7.1万吨；它的关键不是“矿石量×价格”，而是不同精矿品位、运输、税费、津巴布韦本地加工政策和国内锂盐转换利润。公司在资源自给较高时拥有周期弹性，但出口限制或当地加工投入会提高资本占用。{c('中矿资源')}

{_link(by_name['雅化集团'])}的锂盐设计产能13万吨，上游由Kamativi与李家沟提供原料，同时民爆业务形成非锂利润。模型对其加工量与自给量分开计价：高锂价并不自动改善外购矿加工利润，只有原料锁定、客户长协与加工价差共同改善才会转成归母利润。{c('雅化集团')}

{_link(by_name['天华新能'])}2025年锂盐建成产能16.5万吨，其中氢氧化锂13.5万吨、碳酸锂3万吨；实际产量结构与设计产能不同。Ogapa经济权益37.5%能提高资源保障，但海外项目爬坡、产品认证与加工价差仍决定现金转换。模型因此没有用单一碳酸锂价格乘全部产能，而是把资源利润、加工利润和公司层成本拆开。{c('天华新能')}

{_link(by_name['盛新锂能'])}拥有13.7万吨锂盐建成产能、Sabi Star与业隆沟精矿能力，木绒项目是远期期权。其价值取决于自有资源供给占比能否提高，而不是盐厂满产本身；外购矿加工在价差收窄时可能贡献收入却难贡献利润。{c('盛新锂能')}

### 小体量资源弹性与待兑现项目

{_link(by_name['融捷股份'])}2025年锂精矿产量18.56万吨，134号脉采矿能力105万吨原矿/年，但合并锂盐产能较小。资源放量对利润弹性较高，也意味着采选衔接、品位、外售价格和关联交易口径对单年利润影响更大。估值应优先看可售精矿和归母利润，不看原矿处理能力。{c('融捷股份')}

{_link(by_name['大中矿业'])}的锂业务尚处兑现阶段，鸡脚山一期2万吨碳酸锂和加达锂矿的贡献年份是主要变量；铁矿业务是当前现金流基础。模型对2026—2028设置渐进销量而不是一次性满产，因此独立利润低于部分市场预测。{c('大中矿业')}

{_link(by_name['西藏城投'])}通过国能矿业持有41%权益，两盐湖规划碳酸锂产能10万吨、资源量约390万吨LCE，但规划、建设、试车、稳定产量与归母现金流之间仍有多道门槛。公司当前利润主要并非锂业务，不能用项目名义产能直接套成熟锂企倍数。{c('西藏城投')}

{_link(by_name['永杉锂业'])}2025年碳酸锂与氢氧化锂产量分别约1.3814万吨和1.4463万吨，现有产能4.5万吨并计划扩产。它更接近加工型企业，利润取决于采购、库存、加工价差和产能利用率；高锂价如果伴随原料涨得更快，未必形成更高利润。{c('永杉锂业')}
"""


COMPANY_RESEARCH_LENSES = {
    "赣锋锂业": {
        "position": "全球多资源、多产品的一体化平台，项目分散降低单矿风险，也增加资本开支、少数股东和会计口径复杂度。",
        "short": "短期重点是Cauchari-Olaroz、Goulamina和国内锂盐线的销量、现金成本及回款，而不是规划资源量。",
        "long": "长期上限来自资源组合、产品认证和电池循环协同；下限取决于扩产资本回报和海外现金能否回到上市公司。",
        "risk": "阿根廷盐湖或Goulamina爬坡慢、外购矿占比高于模型、资本开支继续高于经营现金流。",
        "trigger": "连续两个季度权益产量、自给率和自由现金流同时高于基准，而市值仍未上修。",
    },
    "融捷股份": {
        "position": "集中于甲基卡资源与精矿销售的小体量高弹性标的，原矿处理量与可售精矿不能混用。",
        "short": "短期利润主要看品位、回收率、可售精矿吨位和销售定价；锂盐并表产能较小。",
        "long": "长期价值取决于采选扩张、资源接续和关联交易后的归母现金，而非单一矿权稀缺性。",
        "risk": "采选衔接、品位或销售价格偏离，任何一项都能显著改变单位利润。",
        "trigger": "精矿销量和经营现金流共同验证扩产，且没有用应收或库存替代现金回款。",
    },
    "盛新锂能": {
        "position": "锂盐加工规模较大，上游由Sabi Star、业隆沟和远期木绒补充，核心是自给率提升而非盐厂满产。",
        "short": "短期看自有矿进入生产的比例、锂盐销量和加工价差，外购矿加工可能增收不增利。",
        "long": "木绒若按权益、建设和爬坡兑现，可把公司从加工弹性转向资源弹性；未投产前仍属于期权。",
        "risk": "海外矿政策、本地加工投入、木绒建设时点和客户结构导致现金转换低于利润。",
        "trigger": "自有矿覆盖率连续上升、单位成本下降且资本开支后的自由现金流转正。",
    },
    "盐湖股份": {
        "position": "察尔汗盐湖低成本碳酸锂与钾肥现金流双主业，防守性高于纯锂价弹性。",
        "short": "短期看新增4万吨装置的稳定运行、产品品质与销量，同时钾肥价格决定利润底仓。",
        "long": "长期价值来自盐湖资源综合利用和新装置效率；名义8万吨只有在可售产量与现金成本验证后才成立。",
        "risk": "装置爬坡慢、单位成本高于预期，或钾肥盈利回落抵消锂业务增量。",
        "trigger": "新增装置稳定产销、锂业务毛利改善且钾肥现金流能够覆盖扩产。",
    },
    "大中矿业": {
        "position": "铁矿提供现有利润，鸡脚山与加达锂项目提供远期成长，当前锂业务仍处建设与兑现阶段。",
        "short": "短期应看许可、建设、试车和产品合格率，不应按名义产能直接给成熟锂企倍数。",
        "long": "若两处项目形成低成本资源与锂盐一体化，利润结构会改变；若延期，估值仍应回到铁矿底盘。",
        "risk": "建设进度、资本开支、工艺成本或投产年份任何一项后移，都会压低远期价值。",
        "trigger": "首批合格产品、稳定月产和成本披露依次出现后，再提高锂业务估值权重。",
    },
    "雅化集团": {
        "position": "民爆业务提供利润缓冲，锂盐通过Kamativi、李家沟和客户关系获得资源与加工协同。",
        "short": "短期利润看锂盐销量、外购矿与自有矿比例、加工价差以及民爆业务稳定性。",
        "long": "资源保障和氢氧化锂客户认证决定长期溢价，但矿端权益和加工利润必须分开计算。",
        "risk": "原料涨幅高于产品、海外矿物流或李家沟产量低于计划，导致收入增长但利润不增。",
        "trigger": "资源覆盖提高、加工价差改善且民爆现金流没有被锂业务扩产吞噬。",
    },
    "天华新能": {
        "position": "以氢氧化锂加工和客户交付能力为核心，Ogapa等上游权益用于降低外购矿风险。",
        "short": "短期看氢氧化锂与碳酸锂实际产品结构、产能利用率和加工价差，不能用全部产能乘碳酸锂价格。",
        "long": "资源权益、客户认证和稳定质量若同时兑现，可提升可持续ROE；仅扩产会提高资本占用。",
        "risk": "原料保障不及预期、产品结构偏低毛利或海外项目爬坡慢。",
        "trigger": "单位加工利润、资源自给和经营现金流三个指标连续改善。",
    },
    "天齐锂业": {
        "position": "Greenbushes低成本资源与SQM权益构成核心资产，上市公司归母价值还受少数股东、税负和资本结构影响。",
        "short": "短期看Greenbushes产量、售价、成本、CGP3爬坡与分红，而非只看锂盐现货。",
        "long": "优质资源寿命和扩建能力支撑周期底部，但海外加工项目若回报不足会拖累自由现金流。",
        "risk": "矿山品位/回收率、分红、少数股东或海外加工减值使资源盈利无法等比例转为归母现金。",
        "trigger": "Greenbushes运行改善、分红恢复且公司净负债和自由现金流同步改善。",
    },
    "永杉锂业": {
        "position": "碳酸锂与氢氧化锂加工型公司，资源自给弱，盈利更接近原料—产品价差而非绝对锂价。",
        "short": "短期看采购成本、库存、加工价差和利用率；锂价快速上行也可能先造成营运资金压力。",
        "long": "扩产只有在原料锁定、客户与现金转换具备时才提高价值，否则会放大周期风险。",
        "risk": "高价库存、价差收窄、扩产利用不足和营运资金占用。",
        "trigger": "销量提升同时库存周转加快、经营现金流与利润一致。",
    },
    "中矿资源": {
        "position": "Bikita资源与铯铷业务形成资源弹性和非锂底仓，津巴布韦政策使本地加工与物流成为关键变量。",
        "short": "短期看精矿品位、出货节奏、国内锂盐转换成本和铯铷利润稳定性。",
        "long": "高资源自给可以在上行周期放大利润，但新增加工资本开支和资源国权益会改变归母回报。",
        "risk": "出口与本地加工政策、运输、产量或成本低于模型；独立利润高于一致预期需要更严格验证。",
        "trigger": "Bikita出货、单位成本和现金回款均达到模型，而市场仍按较低利润定价。",
    },
    "藏格矿业": {
        "position": "现有盐湖锂与钾肥规模有限但成本较低，巨龙铜业投资收益和Mamico期权决定公司并非纯锂标的。",
        "short": "短期利润对铜、钾和锂三项共同敏感，不能用锂价解释全部业绩。",
        "long": "Mamico需要按26.95%间接权益、建设和爬坡计入；100%项目产能不能进入归母销量。",
        "risk": "投资收益波动、海外项目延迟或市场把远期项目提前全部资本化。",
        "trigger": "现有业务现金分红稳定，Mamico形成可核验产量后再提高远期权重。",
    },
    "西藏城投": {
        "position": "国能矿业盐湖资源是远期期权，当前公司盈利和现金流仍受地产存量与项目建设约束。",
        "short": "短期不以规划10万吨产能计利润，只看许可、融资、建设和试验进度。",
        "long": "盐湖若形成稳定产品和现金流会改变公司属性；在此之前只能使用分阶段折价。",
        "risk": "建设、工艺、资本开支和公司层负担使资源量长期无法货币化。",
        "trigger": "正式投资决策、融资闭环、稳定试车和产品销售按顺序完成。",
    },
    "永兴材料": {
        "position": "低成本锂云母与特钢双主业，资源一体化带来利润弹性，也承担环保、尾渣和地方监管约束。",
        "short": "短期看锂业务实际产量、现金成本、尾渣处理和特钢利润底仓。",
        "long": "持续成本优势必须由采选冶稳定和合规投入证明，不能只用资源量或历史低成本外推。",
        "risk": "环保/采矿监管、品位、成本或锂价回落使可持续ROE低于市场要求。",
        "trigger": "产量成本稳定、自由现金流覆盖分红与维持资本开支，且估值未永久化高周期ROE。",
    },
}


def _deep_company_dossiers(
    companies: list[dict[str, Any]],
    recon_by_name: dict[str, dict[str, Any]],
    source_ids: dict[str, int],
) -> str:
    sections: list[str] = []
    for company in companies:
        name = company["company"]
        lens = COMPANY_RESEARCH_LENSES[name]
        recon = recon_by_name[name]
        base = {
            int(row["year"]): row
            for row in company["scenarios"]["基准情景"]
        }
        downside = {
            int(row["year"]): row
            for row in company["scenarios"]["下行情景"]
        }
        upside = {
            int(row["year"]): row
            for row in company["scenarios"]["上行情景"]
        }
        fy1_recon = next(
            row for row in recon["yearly_reconciliation"]
            if int(row["year"]) == 2026
        )
        broker = fy1_recon.get("recent_broker_median") or {}
        wind = (fy1_recon.get("wind_consensus") or {}).get("net_income_rmb_bn")
        broker_ni = broker.get("net_income_rmb_bn_median")
        market = recon["market_reconciliation"]
        market_cap = market.get("market_cap_rmb_bn")
        core_range = company["independent_equity_value_range"]
        low = core_range.get("low_rmb_bn")
        high = core_range.get("high_rmb_bn")
        range_position = (
            "没有满足门槛的核心估值区间，不能与当前市值作目标价比较"
            if low is None or high is None
            else "当前市场数据不足，无法与研究区间比较"
            if market_cap is None
            else "低于研究区间下沿"
            if market_cap < low
            else "高于研究区间上沿"
            if market_cap > high
            else "位于研究区间内"
        )
        annual_ref = f"ar_{company['ticker'].replace('.', '_')}_2025"
        evidence = _cite(source_ids, annual_ref)
        methods = "；".join(
            (
                f"{item['method']} {item['low_rmb_bn'] * 10:.0f}—"
                f"{item['high_rmb_bn'] * 10:.0f}亿元（{item['role']}）"
                if item.get("low_rmb_bn") is not None
                and item.get("high_rmb_bn") is not None
                else f"{item['method']}未采用（{item['role']}）"
            )
            for item in company["valuations"]
        )
        institutions = "、".join((broker.get("institutions") or [])[:6])
        if int(broker.get("institution_count") or 0) > 6:
            institutions += "等"
        wind_text = (
            f"{wind * 10:.2f}亿元"
            if wind is not None
            else "没有形成可用一致预期"
        )
        broker_text = (
            f"{broker_ni * 10:.2f}亿元"
            if broker_ni is not None
            else "没有足够近期机构样本"
        )
        market_text = (
            f"{market_cap * 10:.2f}亿元"
            if market_cap is not None
            else "当前市值客观不可得"
        )
        pe_fy1 = market.get("independent_implied_pe_fy1")
        pe_fy2 = market.get("independent_implied_pe_fy2")
        pe_text = (
            f"{pe_fy1:.2f}/{pe_fy2:.2f}倍"
            if pe_fy1 is not None and pe_fy2 is not None
            else "基准利润为负或市场数据不足，不能计算正市盈率"
        )
        actual = company["actual_2025"]
        project_evidence = _join_cn_sentences(
            company["project_and_operating_evidence"]
        )
        limitations = _join_cn_sentences(company["limitations"])
        profit_change = (
            (base[2026]["net_income_rmb_bn"] / actual["net_income_rmb_bn"] - 1)
            * 100
            if actual["net_income_rmb_bn"] > 0
            else None
        )
        profit_change_text = (
            f"较2025年实际值变化{profit_change:+.1f}%"
            if profit_change is not None
            else "2025年基数为亏损，不能用增长率描述修复"
        )
        sections.append(
            f"""
### <span class="company-analysis-kicker" aria-hidden="true">公司</span> {_link(company)}：{lens['position'].split('，')[0]} {{.company-analysis-heading}}

#### 问题

{_link(company)}的现有利润究竟来自资源、加工还是其他业务；2026—2028项目和锂价变化怎样传到归母利润、自由现金、ROE和合理价值；当前市值已经计入了多少兑现？

#### 研究方法与数据

公司公告和年报能够确认：{project_evidence}本研究先把项目产量、穿透权益、资源覆盖、加工价差、非锂利润和资本开支拆开，冻结2026—2028独立模型，再与Wind一致预期和研究截止日前最近两个季度的机构预测对账。公开资料的主要限制是：{limitations} {evidence}

#### 研究与分析

| 财务/经营指标 | 2025实际 | 2026E基准 | 2027E基准 | 2028E基准 |
|---|---:|---:|---:|---:|
| 营业收入 | {actual['revenue_rmb_bn'] * 10:.2f}亿元 | {base[2026]['revenue_rmb_bn'] * 10:.2f}亿元 | {base[2027]['revenue_rmb_bn'] * 10:.2f}亿元 | {base[2028]['revenue_rmb_bn'] * 10:.2f}亿元 |
| 归母净利润 | {actual['net_income_rmb_bn'] * 10:.2f}亿元 | {base[2026]['net_income_rmb_bn'] * 10:.2f}亿元 | {base[2027]['net_income_rmb_bn'] * 10:.2f}亿元 | {base[2028]['net_income_rmb_bn'] * 10:.2f}亿元 |
| 经营现金流/预测FCFE | {actual['operating_cash_flow_rmb_bn'] * 10:.2f}亿元经营现金流 | {base[2026]['fcfe_rmb_bn'] * 10:.2f}亿元FCFE | {base[2027]['fcfe_rmb_bn'] * 10:.2f}亿元FCFE | {base[2028]['fcfe_rmb_bn'] * 10:.2f}亿元FCFE |
| 归母权益 | {actual['equity_rmb_bn'] * 10:.2f}亿元 | {base[2026]['equity_rmb_bn'] * 10:.2f}亿元 | {base[2027]['equity_rmb_bn'] * 10:.2f}亿元 | {base[2028]['equity_rmb_bn'] * 10:.2f}亿元 |
| ROE | {actual['roe_pct']:.2f}% | {base[2026]['roe_pct']:.2f}% | {base[2027]['roe_pct']:.2f}% | {base[2028]['roe_pct']:.2f}% |
| 锂产品等价销量 | — | {base[2026]['product_volume_10kt_lce']:.2f}万吨 | {base[2027]['product_volume_10kt_lce']:.2f}万吨 | {base[2028]['product_volume_10kt_lce']:.2f}万吨 |
| 资源或权益覆盖 | — | {base[2026]['resource_share_pct']:.0f}% | {base[2027]['resource_share_pct']:.0f}% | {base[2028]['resource_share_pct']:.0f}% |

2026年下行、基准和上行情景归母利润分别为{downside[2026]['net_income_rmb_bn'] * 10:.2f}亿元、{base[2026]['net_income_rmb_bn'] * 10:.2f}亿元和{upside[2026]['net_income_rmb_bn'] * 10:.2f}亿元；基准{profit_change_text}。三种情景共同使用已列销量、资源覆盖和非锂利润框架，只改变锂价及与景气相关的销量和非锂系数，所以它回答的是价格与项目兑现敏感性，不是三个目标价投票。

**建模与外部对账。** 基准销量为{company['assumptions']['product_volume']['2026']:.2f}/{company['assumptions']['product_volume']['2027']:.2f}/{company['assumptions']['product_volume']['2028']:.2f}万吨LCE，资源或权益覆盖为{company['assumptions']['resource_share']['2026'] * 100:.0f}%/{company['assumptions']['resource_share']['2027'] * 100:.0f}%/{company['assumptions']['resource_share']['2028'] * 100:.0f}%。2026年独立归母利润为{base[2026]['net_income_rmb_bn'] * 10:.2f}亿元，Wind一致预期为{wind_text}，最近两个滚动季度的机构中位数为{broker_text}；样本为{broker.get('institution_count') or 0}家机构，报告日期从{broker.get('report_date_start') or '—'}到{broker.get('report_date_end') or '—'}，包括{institutions or '近期公开样本不足'}。{recon['difference_summary']}

**估值与交易观察。** 适用方法给出的结果为：{methods}。截至{market.get('trade_date')}，当前市值约{market_text}，按独立2026/2027利润对应{pe_text}，{range_position}。PB—ROE只有在表中ROE能够跨周期维持、净资产真实产生现金回报时才有意义；FCFE用于检查利润增长是否被资本开支和营运资金抵消。各方法不机械平均，差异用于识别市场究竟在押注锂价、销量、ROE还是项目终值。

#### 总结

**{_link(company)}的核心判断是：{lens['position']}** {lens['short']} {lens['long']} **偏积极验证点**是{lens['trigger'].rstrip('。；')}；**下修或回避条件**是{lens['risk'].rstrip('。；')}。
"""
        )
    return "\n".join(sections)


def _carbonate_h1_table(model: dict[str, Any]) -> str:
    row = model["observed_2026_h1"]
    low, high = row["domestic_output_range_mt"]
    apparent_low, apparent_high = row["apparent_supply_range_mt"]
    routes = row["route_output_mt"]
    return f"""| 指标 | 2026H1数值 | 口径和用途 |
|---|---:|---|
| 国内产量 | {low * 100:.2f}—{high * 100:.2f}万吨 | 隆众/Mysteel/SMM覆盖不同，保留区间 |
| SMM国内产量 | {row['smm_domestic_output_mt'] * 100:.2f}万吨 | 用于SMM自身供需和月度跟踪 |
| 进口 / 出口 | {row['imports_mt'] * 100:.2f} / {row['exports_mt'] * 100:.4f}万吨 | 海关累计值 |
| 表观供给 | {apparent_low * 100:.2f}—{apparent_high * 100:.2f}万吨 | 国内产量＋进口－出口，未扣库存 |
| 分路线产量 | 辉石{routes['锂辉石'] * 100:.2f}、云母{routes['锂云母'] * 100:.2f}、盐湖{routes['盐湖'] * 100:.2f}、回收{routes['回收'] * 100:.2f}万吨 | 同一隆众路线表，可横向比较 |
| 月度需求 | 1月{row['demand_monthly_start_end_mt'][0] * 100:.2f} → 6月{row['demand_monthly_start_end_mt'][1] * 100:.2f}万吨 | 只有起止点，不伪造中间月份 |
| 样本库存 | {row['inventory_sample_mt'] * 100:.2f}万吨 | 样本库存，不等于全部可交易库存 |"""


def _carbonate_forecast_ranges(model: dict[str, Any]) -> str:
    lines = [
        "| 年份 | 国内产量区间 | 净进口区间 | 需求区间 | 可能余额区间 | 研究含义 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    meanings = {
        "2026": "上半年已有较强约束，方向仍取决于下半年产量和储能需求",
        "2027": "项目与需求误差放大，不能把中值小缺口写成确定事实",
        "2028": "供需两端区间高度重叠，更适合做价格和公司压力测试",
    }
    for year, row in model["forecast_ranges"].items():
        lines.append(
            f"| {year} | {row['domestic_output_mt'][0] * 100:.0f}—"
            f"{row['domestic_output_mt'][1] * 100:.0f}万吨 | "
            f"{row['net_imports_mt'][0] * 100:.0f}—{row['net_imports_mt'][1] * 100:.0f}万吨 | "
            f"{row['demand_mt'][0] * 100:.0f}—{row['demand_mt'][1] * 100:.0f}万吨 | "
            f"{row['balance_mt'][0] * 100:+.0f}至{row['balance_mt'][1] * 100:+.0f}万吨 | "
            f"{meanings[year]} |"
        )
    return "\n".join(lines)


def _lithium_documents(
    industry_id: int,
    source_ids: dict[str, int],
    models: dict[str, Any],
    recon: dict[str, Any],
    supply: dict[str, Any],
) -> dict[str, str]:
    companies = models["companies"]
    recon_by_name = {row["company"]: row for row in recon["companies"]}
    usgs = _cite(source_ids, "usgs_mcs_2026")
    iea = _cite(source_ids, "iea_gcm_2026")
    aus = _cite(source_ids, "australia_req_202606")
    sqm = _cite(source_ids, "sqm_20f_2025")
    policy = _cite(
        source_ids,
        "argentina_mining_2025",
        "chile_maricunga_202602",
        "zimbabwe_export_202602",
        "mali_lithium_2026",
    )
    reports = _cite(
        source_ids,
        "dongwu_carbonate_20260226",
        "zheshang_lithium_20260614",
        "dongfang_lithium_20260222",
    )
    association = _cite(
        source_ids,
        "lithium_association_2025",
        "lithium_association_2025_competition",
        "lithium_association_2025h1",
    )
    company_filings = _cite(
        source_ids,
        *(
            f"ar_{company['ticker'].replace('.', '_')}_2025"
            for company in companies
        ),
    )
    front = _front(
        industry_id=industry_id,
        name="锂",
        title="锂行业主文档",
        dynamic="官方基准显示2029年前仍有余量、2030附近趋于平衡；项目兑现和储能决定压力情景何时转缺。",
    )
    main = front + f"""
# 锂行业：不是缺资源，而是缺按时、按成本兑现的有效供给

> **核心结论。** 全球锂的长期矛盾不是地质资源总量不足，而是需求增长与有效项目兑现速度的竞赛。澳大利亚政府2026年6月最新同口径基准显示：2025—2029年供给仍分别高于需求11.5、14.4、15.0、11.7和4.7万吨LCE，2030年转为约3.2万吨缺口，2031年接近平衡。**这意味着“2026—2028确定短缺”不能作为基准结论；较早短缺只存在于项目延迟且需求偏强的压力情景。** USGS同时显示2025年澳大利亚、中国和智利占全球矿端产量约72.41%，加入津巴布韦和阿根廷后CR5约90.00%，供应风险集中在少数资源国，但企业化学品销售CR5只有约41%，国家集中与企业竞争不能混写。{usgs} {aus} {sqm} {iea}

![全球锂供需与余额](/static/generated/lithium/lithium_global_balance.png)

## 本报告回答什么

本报告把锂拆成资源、矿石/卤水、精矿、碳酸锂/氢氧化锂、正极与电池、回收六层，统一使用锂金属、LCE、精矿品位和产品吨位的转换边界。全球锂资源供需与中国碳酸锂产品平衡分别建模，不用一个数字替代另一个。公司研究覆盖13家A股公司，财务模型先冻结2026—2028销量、资源覆盖、成本、非锂利润与现金转换，再读取Wind一致预期和最近两个季度的机构预测对账；供应商快照只存在公司财务库。

## 供需基准

单位：百万吨LCE；余额为供给减需求。

{_balance_table(supply)}

表中2025为澳大利亚政府估计，2026—2031为同一机构、同一统计口径的官方预测。压力测试另行计算，不改写基准。核心关系是：

**全球余额＝官方全球生产－官方全球需求；压力情景供给＝官方供给×（1＋项目兑现调整）；压力情景需求＝官方需求×（1＋需求强弱调整）。**

基准不再把来源不同的地区供给、回收和终端分项强行加总。项目层只用于解释压力测试：Rio Tinto的Rincon目标6万吨/年电池级碳酸锂，预计2028年首产并用三年爬坡；Fenix 1B和Sal de Vida在2026年一季度已机械完工、计划下半年首产。相反，Albemarle在2026年2月将Kemerton剩余氢氧化锂产线停产维护，说明优质矿源、海外转换能力和有利润的产品供给是三件不同的事。{_cite(source_ids, 'rio_rincon_202603', 'rio_q1_2026', 'albemarle_kemerton_202602')} {aus}

## 竞争格局

SQM在2025年20-F中估计其全球锂化学品销售份额约14%，Albemarle约12%，赣锋约6%，天齐约5%，Rio Tinto约4%；据此复算化学品销售CR3约32%、CR5约41%。这不是矿山产量集中度，也不能直接解释中国碳酸锂现货份额。资源控制、锂盐销售、客户认证和归母权益是四套不同分母。{sqm}

国家矿端按USGS 2025年锂金属产量复算，澳大利亚31.72%、中国21.38%、智利19.31%，CR3为72.41%；再加津巴布韦9.66%和阿根廷7.93%，CR5为90.00%。企业层则用SQM同年化学品销售估计，CR3约32%、CR5约41%。前者回答资源国供应集中度，后者回答化学品销售格局；没有一张官方表同时覆盖矿山权益、盐湖、精矿、碳酸锂和氢氧化锂，因此不拼造“全球矿企统一份额”。

![2025年主要国家锂矿产量](/static/generated/lithium/lithium_2025_mine_countries.png)

## 公司盈利与估值

单位：亿元人民币；差异为独立模型相对Wind一致预期。

{_company_model_table(companies, recon_by_name)}

{_broker_reconciliation_table(companies, recon_by_name)}

{company_filings} {reports}

13家公司不能按“锂价弹性”一条轴排序。资源控制高、现金成本低的公司在价格回落时更有韧性；加工型公司更依赖原料价差和库存；有钾肥、特钢、民爆或铁矿业务的公司利润弹性更低但现金流更稳；尚未投产的项目型公司估值主要来自项目成功与时间，而不是当前利润。完整方法与区间见[估值对比](/industry/{industry_id}/valuation)，单公司输入、PE/PB Band、PB—ROE/PB—ROA、市场隐含预期和交易观察见各公司页。

## 投资判断

1. **行业层面先做情景而不是押单点。** 投产顺利时供需可以继续过剩；项目延期叠加储能偏强时缺口会快速扩大。
2. **公司层面先看权益产量和成本。** 名义产能、原矿处理量和资源量不能直接进入归母利润。
3. **估值使用正常化利润。** 正常化PE是主要比较工具；PB—ROE用于检查资产回报是否足以支撑PB；FCFE用于识别资本开支与利润的背离，不对三种结果机械平均。
4. **交易验证顺序是产量—库存—价差—现金流。** 只看碳酸锂价格会错过精矿折扣、加工价差、库存收益和项目资本开支。

## 研究边界

公司模型的产品销量、资源覆盖比例和成本包含研究估算，模型文件已冻结但不是公司指引。不同机构对回收、精矿折算和可销售产品覆盖不同，外部供需表只作对账，不取机械平均。2024年及更早资料只用于周期历史，不用于替代2026年现状。{reports}
"""

    q0 = _front(
        industry_id=industry_id,
        name="锂",
        title="Q0 历史发展与周期",
        dynamic="周期从需求冲击转为供给兑现与资本纪律主导。",
    ) + f"""
# Q0｜历史发展与周期

## 本章综述

**锂行业的每一轮大周期都不是简单重复价格曲线。** 2015—2020主要是第一轮新能源汽车预期与澳洲矿山扩张，2021—2022是需求、库存和供应链同时紧张，2023—2025则是高价激励的矿山、盐湖、回收和锂盐产能集中释放。2026以后最重要的变量不是“还有多少规划项目”，而是这些项目能否按时达到可售质量并产生现金。

## 问题

历史上供需预测为什么反复失效？哪些规律还能约束2026—2028判断？

## 证据与数据

USGS显示2025年全球锂产量约29万吨锂、消费约26.3万吨锂，电池用途占88%，说明终端需求已经高度电池化；澳大利亚政府的季度预测又显示矿端恢复和出口收入对价格高度敏感。两者共同说明，长期需求增长不等于每一年都短缺，供给对价格的反应存在两到四年的项目时滞。{usgs} {aus}

| 阶段 | 需求主线 | 供给反应 | 价格与库存特征 | 对当前的约束 |
|---|---|---|---|---|
| 2015—2020 | 新能源汽车从小基数增长 | 澳洲硬岩矿快速扩张、盐湖增量较慢 | 先涨后跌，高成本矿退出 | 价格足够低会延后项目，但不会消灭资源 |
| 2021—2022 | 动力电池、补库和供应链安全共振 | 疫情、建设与爬坡限制有效供给 | 现货紧张、库存极低、价格超调 | 不能用峰值价格推长期利润 |
| 2023—2025 | 电动车增长放缓但储能提速 | 非洲、阿根廷、中国云母与回收集中释放 | 价格下行、库存和成本曲线重新定价 | 规划产能必须乘投产和爬坡率 |
| 2026—2029 | 动力稳增，储能成为边际变量 | 新矿、盐湖、本地加工与回收并进 | 官方基准仍有余量、但逐年收窄 | 重点跟踪项目而不是单一TAM |
| 2030—2031 | 需求继续增长 | 新供给需要二次资本开支 | 官方基准转向接近平衡 | 长期激励价格和项目纪律重要 |

## 建模方法

历史周期只用于设定三个约束：第一，新项目不能在投产年份立即满产；第二，高价格会同时提高需求替代、回收和新供给；第三，矿端、锂盐和库存的时钟不同。模型因此逐年计入项目爬坡，不用长期需求CAGR直接减长期名义产能。

## 研究与分析

上一轮最常见的错误是把“资源量×回收率”当供给，把“电池装机×固定锂强度”当需求，再用二者相减得到精确缺口。前者忽略许可、融资、电水、建设、品位和产品认证，后者忽略化学体系、单位能量锂耗下降、回收与库存。新模型的价值不在某一个缺口点，而在于明确：官方基准直到2030年附近才趋平，若研究要主张更早短缺，就必须逐项目证明供给少了多少、逐需求证明消费多了多少。

另一个错误是用现货价格解释所有公司利润。资源型公司受权益产量与成本影响，加工型公司受原料价差和库存影响，盐湖公司受产量、品质和联产品影响，项目型公司主要受投产时间影响。历史周期的可迁移结论是：**利润弹性必须从业务结构算，不能从股票名称判断。**

历史还揭示了资本开支与价格之间的非线性。矿山停产以后重新启动并不等于恢复原有产量，设备、人员、剥采和客户重新认证都会造成时滞；相反，已经完成大部分建设的项目即使价格回落，也可能为了回收沉没成本继续投产。因此，价格跌破行业平均成本不会让供给立刻下降，价格高于激励价格也不会让供给立刻增加。供给曲线必须按项目阶段分层，而不是假设统一的一年反应期。

库存周期同样会误导历史对照。上游精矿、锂盐厂、正极、电芯和终端分别持有不同形态库存，某一环节去库可能与另一环节补库同时发生。2021—2022的极低可用库存放大上涨，2023—2024的去库又放大下跌；这说明年度需求增长与月度现货价格之间缺少一条固定系数。当前研究因此把库存作为验证变量，而不是将一个库存样本直接并入年度供需。

## 总结

2026—2028的锂行业更像“项目兑现周期”，不是上一轮价格行情的机械重演。价格可以先于年度缺口上涨或下跌，但持续盈利最终仍要由可售产量、成本和现金流证明。{iea}
"""

    q1 = _front(
        industry_id=industry_id,
        name="锂",
        title="Q1 竞争格局",
        dynamic="国家供给集中，但边际项目与企业控制权分散在不同资源国和产品环节。",
    ) + f"""
# Q1｜竞争格局

## 本章综述

**全球锂化学品销售CR3约32%、CR5约41%，集中度不低但也远未形成单一寡头定价。** 更重要的是，矿端国家、盐湖许可、精矿贸易、锂盐客户认证和上市公司权益并不属于同一个竞争市场。真正的壁垒是低成本资源、可扩建许可、稳定工艺、客户认证与资本纪律的组合。{sqm}

## 问题

全球与中国竞争格局如何衡量？13家A股公司的位置有何不同？

## 证据与数据

SQM的2025年20-F提供了少数同口径的全球化学品销售份额。按其估计复算，SQM、Albemarle和赣锋合计约32%，加入天齐和Rio Tinto后约41%。它回答的是“锂化学品销售”，不回答矿山权益产量。中国锂业分会披露的另一套同口径事实是：2025年上半年碳酸锂CR10为51%，前三为九岭锂业、天齐锂业和中信国安；2025全年有29家碳酸锂企业产量超过1万吨，前五依次为九岭、中信国安、天齐、赣锋和华友。协会没有公开前五各自产量，因此可以确认头部身份和CR10，不能据此伪造当年CR3/CR5。{sqm} {association}

| 竞争层 | 可比单位 | 领先者的优势 | 不能混入的数字 |
|---|---|---|---|
| 资源国 | 万吨锂或LCE | 资源、许可、基础设施、政策 | 资源量、规划产能 |
| 矿山/盐湖 | 权益可售精矿或LCE | 品位、成本、寿命、爬坡 | 原矿处理量、100%项目产量 |
| 锂化学品 | 同品级销量 | 工艺、客户认证、供应稳定 | 混合碳酸锂与氢氧化锂产能 |
| 上市公司 | 归母利润与现金流 | 权益、税负、资本结构 | 项目EBITDA、少数股东利润 |

## 研究与分析

### 国家资源集中与企业竞争为什么不是一回事

USGS的2025年锂金属矿端产量显示，澳大利亚、中国、智利合计约72.41%，加入津巴布韦和阿根廷后约90.00%。这意味着罢工、出口政策、许可和基础设施风险集中在少数资源国；但同年全球锂化学品销售CR5约41%，说明资源经过项目权益、精矿贸易和转换产能后，企业销售格局明显更分散。国家CR5不能直接当作企业议价能力，企业CR5也不能替代上游安全判断。{usgs} {sqm}

### 新项目怎样改变既有龙头的排序

国家矿端高度集中，但边际项目在阿根廷、非洲、澳大利亚和中国之间分散。Rio Tinto等大型矿企进入提高融资和执行能力，也降低传统纯锂公司的稀缺性溢价：Rincon总投资25亿美元，6万吨目标产能要到2028年首产并再用三年爬坡；PLS的P2000虽研究200万吨精矿能力，但仍处可研和资本纪律审查阶段。相反，Greenbushes在2026年一季度产量35.1万吨、售价1,668美元/吨、EBITDA率75%，说明已投产低成本资源与规划产能的经济价值不能同权。{_cite(source_ids, 'rio_rincon_202603', 'pls_pilgangoora_2026', 'igo_greenbushes_2026q1')}

项目对竞争格局的影响需要穿过“融资完成—建设—机械完工—首产—稳定品质—可售量—现金回收”七个节点。名义产能只改变远期候选池；机械完工才改变近期供给概率；稳定销量和成本才改变企业排名。Rio Tinto 2026年一季度披露Fenix 1B和Sal de Vida机械完工、目标下半年首产，属于比规划更强的证据，但仍不能按满产进入2026供给。Albemarle停运Kemerton剩余产线则表明矿源优势并不保证每个转换资产都有经济性。{_cite(source_ids, 'rio_q1_2026', 'albemarle_kemerton_202602')}

### 中国碳酸锂供给为什么比矿端更分散

2025年国内碳酸锂产能178万吨、产量97.6万吨，简单利用率约54.8%；这并不意味着每条线闲置程度相同，因为部分柔性产线会切换碳酸锂与氢氧化锂，部分装置受原料、环保、检修和品质约束。上半年CR10只有51%，而同期氢氧化锂CR10达到98%，说明“锂盐行业集中度”这一笼统标签会掩盖产品差异。九岭和中信国安等非13家样本公司进入前列，也证明本地上市公司池不能作为竞争候选上限。{association}

国内13家公司可分四组：赣锋、天齐是全球资源一体化；盐湖、藏格、永兴是低成本资源与非锂业务组合；中矿、雅化、天华、盛新是资源与加工协同；融捷、大中、西藏城投、永杉的价值更依赖单项目或加工价差。分组的目的不是贴标签，而是决定应该比较哪一组销量、成本和估值。

{_common_company_analysis(companies, source_ids)}

## 总结

锂行业竞争不是一张“产能排名表”。投资上优先比较同口径的权益销量、现金成本、在建资本开支和归母现金流；无法统一分母时，明确不计算比生成一个看似完整的CR5更可靠。
"""

    q2 = _front(
        industry_id=industry_id,
        name="锂",
        title="Q2 市场空间与供需",
        dynamic="官方基准到2029年仍有余量，2030附近趋平；更早短缺只属于带明确输入的压力情景。",
    ) + f"""
# Q2｜市场空间与供需

## 本章综述

**澳大利亚政府2026年6月基准显示，全球锂在2025—2029年仍过剩，余额从11.5万吨扩大到2027年的15.0万吨后收窄，2030年才出现约3.2万吨缺口。** 因此行业的中长期矛盾是“余量收窄并接近平衡”，不是2026年立即短缺。卖方报告给出更高的供给和需求总量，是因为回收、可销售产品和其他统计边界不同，只能作为情景对照。{aus} {iea} {reports}

## 问题

2025—2028全球锂的有效供给、分项需求和情景边界是什么？

## 证据与数据

{_balance_table(supply)}

{_supply_scenarios(supply)}

![全球锂供需情景](/static/generated/lithium/lithium_global_balance.png)

## 建模方法

**全球余额＝官方生产－官方需求。投产顺利压力测试在官方供给上增加3%—10%、在需求上减少2%—5%；投产受限且需求偏强压力测试则把供给降低3%—10%、需求提高2%—5%。**

压力比例不是概率，也不是第二套事实。它的用途是回答：官方2028年11.7万吨余量能否承受项目和需求误差。按悲观压力输入，2027年已经接近平衡，2028年转为约11万吨缺口；按投产顺利压力输入，2028年余量扩大到约35万吨。区间很宽，说明精确缺口不可靠，但也明确了需要验证的量级。{usgs} {iea} {aus}

## 研究与分析

东吴2026年2月和浙商2026年6月给出的2026—2028供需量明显高于澳大利亚政府官方表。差异首先来自统计边界：卖方常把回收、锂盐可销售量和更广的项目池纳入，官方表使用自身生产与消费口径。其次才是储能和项目判断。研究不能因为卖方数字更新更快就直接覆盖官方序列，也不能把三张表平均成“市场一致答案”。本报告把官方表作为基准，卖方表只回答更乐观需求或更宽供给口径下会怎样。{reports}

2026年的官方余量14.4万吨，约为需求9.2%；2028年余量11.7万吨，约为需求5.8%；2030年缺口3.2万吨，仅约为需求1.3%。这些比例都可能被库存、贸易和项目时点放大或吸收。真正需要验证的是官方余量是否按计划收窄、项目是否系统性延期，以及储能需求是否持续高于基准，而不是某个月价格是否与年度平衡同方向。

### 哪些项目最可能改变2026—2029平衡

| 项目或资产 | 最新可核验状态 | 名义规模或经营数据 | 本研究怎样进入供给 |
|---|---|---:|---|
| Rio Tinto Rincon | 2026年3月融资推进；预计2028年首产，之后三年爬坡 | 6万吨/年电池级碳酸锂 | 2026—2027不计量，2028只计首产和爬坡，不按满产 |
| Rio Tinto Fenix 1B / Sal de Vida | 2026年一季度机械完工，目标下半年首产 | 公司披露为阿根廷盐湖增量组合 | 先作为2026下半年供给验证项，稳定品质后再上调 |
| Greenbushes | 2026年一季度精矿产量35.1万吨、售价1,668美元/吨 | EBITDA率75% | 属于已投产低成本供给，优先级高于规划产能 |
| Pilgangoora P2000 | 仍处可研和资本纪律审查 | 研究目标200万吨/年精矿能力 | 不进入近期基准，仅进入2029以后上限 |
| Kemerton氢氧化锂 | 2026年2月剩余产线停产维护 | 海外转换资产收缩 | 不减少矿端资源，但降低海外可盈利化学品供给 |

{_cite(source_ids, 'rio_rincon_202603', 'rio_q1_2026', 'igo_greenbushes_2026q1', 'pls_pilgangoora_2026', 'albemarle_kemerton_202602')}

这张表有两个投资含义。第一，新增供给并不是把所有规划产能按年份相加，首产年份和满产年份之间常隔两到三年；第二，矿端供给和化学品供给可以反向变化，例如Kemerton停产不改变Greenbushes资源，却改变海外转换与客户交付结构。对赣锋、天齐、中矿等公司，项目兑现既增加自身销量，也可能压低全行业价格，增量利润必须同时扣除价格反身影响。

### 需求增长为什么未必立即造成年度短缺

IEA 2026年报告指出，过去两年锂需求年均增速约25%，2025年至2026年初价格又因储能需求和供给约束明显反弹；与此同时，更新后的项目管线使中长期锂供给缺口较此前预测收窄。两者并不矛盾：短期价格取决于可交易库存、项目扰动和需求集中交付，年度供需则统计全年可用量；中长期项目池扩大又会压缩更远期缺口。研究因此把储能、动力、回收和单位锂耗分别跟踪，而不把“需求高增长”直接翻译成“当年总量短缺”。{iea}

### 余额怎样传到价格与公司利润

年度余额只是价格链条的第一层。它还要经过可交易库存、区域价差、精矿折扣、转换能力和边际现金成本，最后才进入碳酸锂或氢氧化锂价格。公司利润则再经过产品结构、权益比例、长协、库存成本、资本开支和税负。**行业余额变动1万吨不会对应固定价格变化，锂价变动1万元/吨也不会对应所有公司同一利润变化。**

模型更新使用阈值而不是每日追价：官方或可比口径供给/需求相对基准偏离5%以上、关键项目首产或爬坡推迟一个季度以上、全球可交易库存连续三个观察期同向变化，才重算年度情景。这样既能捕捉结构拐点，也避免用短期资金行情改写三年财务模型。

## 总结

行业基准是“先过剩、后趋平”，并非立即短缺。只有投产受限且需求偏强时，缺口才会提前且扩大；价格上涨只有在项目、库存和需求同时验证后，才应上调公司的长期利润与估值中枢。
"""

    q3 = _front(
        industry_id=industry_id,
        name="锂",
        title="Q3 公司壁垒",
        dynamic="壁垒由资源质量、权益、工艺、客户与资本纪律共同构成。",
    ) + f"""
# Q3｜公司壁垒

## 本章综述

**公司壁垒不能用资源量或名义产能排名。** 低成本资源决定周期底部，权益比例决定归母收益，工艺与认证决定可售产品，资本纪律决定高景气利润能否变成股东现金。13家公司中，资源一体化、盐湖/云母低成本、非洲资源加工和项目期权四种模式的风险收益完全不同。

## 问题

哪些经营变量能形成可持续壁垒，哪些只是周期放大的表象？

## 证据与数据

{_company_project_table(companies, source_ids)}

## 建模方法

公司模型使用同一传导框架，但参数逐公司设定：

**资源税后利润＝产品销量×资源覆盖比例×（含税锂价－含税资源成本）÷1.13×税后归母转换系数；加工税后利润＝产品销量×（1－资源覆盖比例）×单位加工利润÷1.13×税后归母转换系数；归母净利润＝资源利润＋加工利润＋其他业务利润－公司层成本。**

这套公式不会把全部销量都假设为自有资源，也不会让钾肥、民爆、铁矿、特钢和地产利润随锂价同比例变化。

## 研究与分析

资源壁垒必须经过“权益—产量—成本—可售质量”四层验证。天齐的Greenbushes、盐湖股份的察尔汗、永兴的锂云母和中矿的Bikita具有不同工艺与政策风险，不能用同一个现金成本。全球项目还要扣少数股东、资源国税费和本地加工资本开支。

客户壁垒在氢氧化锂和高端产品上更重要，但公开客户信息不足以精确分配长期份额。研究只把已经形成产能、量产或正式披露的项目作为事实；未公开认证和采购份额不进入基准模型。

{_common_company_analysis(companies, source_ids)}

## 总结

最强壁垒是“低成本权益资源＋稳定可售产品＋客户＋自由现金流”的组合。只有资源没有产量、只有产能没有原料、只有利润没有现金，均不足以支撑长期估值溢价。
"""

    q4 = _front(
        industry_id=industry_id,
        name="锂",
        title="Q4 行业经济性",
        dynamic="价格、精矿折扣、加工价差和资本开支共同决定股东回报。",
    ) + f"""
# Q4｜行业经济性与估值

## 本章综述

**锂价不是利润，产能也不是现金流。** 资源型企业的盈利由权益销量和成本决定，加工型企业看原料—产品价差，扩产期企业还要扣资本开支与营运资金。估值上，正常化PE是主比较，PB—ROE用于判断资产回报是否支撑PB，FCFE用于识别现金流质量；三种结果不做机械平均。

## 问题

如何把行业价格传到13家公司的盈利、现金流与估值？

## 证据与数据

{_company_model_table(companies, recon_by_name)}

![13家公司2027年模型利润与资源覆盖](/static/generated/lithium/lithium_company_2027_model.png)

最近两个滚动季度的机构样本与发布日期如下。机构中位数只用于对账，不参与独立模型计算；同一机构同一预测年度只保留最新一份，英文机构与中文机构等权。

{_broker_reconciliation_table(companies, recon_by_name)}

{company_filings} {reports}

## 建模方法

三种锂价路径均为含税人民币产品等价：下行情景为2026—2028年10/9/9万元/吨，基准为15/14/13万元/吨，上行为18/17/16万元/吨。每家公司再叠加独立销量、资源覆盖、成本、加工利润和非锂利润。情景表示可复算经营状态，不给主观发生概率。

估值门禁如下：盈利与业务相对稳定时使用正常化PE；净资产与可持续ROE有经济意义时才用PB—ROE；现金流数据可解释时用FCFE作比较；缺少逐项目储量、成本、资本开支和税制时不伪造完整矿山NAV。PB—ROE中的高周期ROE必须折价，FCFE终值占比过高则降为参考。

实际计算并不是“销量×锂价＝利润”。资源端先按权益或自给覆盖量计算价差，加工端只对外购部分计算加工利润，再叠加钾肥、铁矿、民爆、特钢等非锂业务，最后扣公司层成本。以赣锋2027年基准为例，16万吨LCE产品销量中资源覆盖假设82%，含税产品价格14万元/吨、资源成本5.8万元/吨、外购部分加工利润1.3万元/吨，叠加7亿元其他业务利润并扣2.5亿元公司层成本，得到约73.46亿元归母净利润；这一结果只在销量、覆盖率与成本同时成立时有效。

## 研究与分析

独立模型与Wind一致预期存在真实分歧。赣锋、天齐、天华等基准利润低于一致预期，主要因为本研究采用较慢爬坡、较低资源覆盖或更保守锂价；中矿的独立利润高于一致预期，则需要重点验证Bikita产量、成本与锂盐转换。大中矿业差异较大，反映市场可能更快计入锂项目，而本研究仍以阶段性销量处理。对账不会反向改写已经冻结的模型。

### 同一价格情景为什么产生不同利润弹性

{_scenario_financial_table(companies, recon_by_name)}

下行到基准的利润增量主要衡量已投产权益资源的价格弹性；基准到上行的增量还受公司设定的销量、覆盖率和非锂利润约束。天齐、赣锋、中矿等资源覆盖较高的公司利润随价格—成本差扩大更明显；永杉等加工型公司不应获得同样的资源弹性；盐湖股份、藏格、永兴有钾肥或特钢底仓，锂价下跌时利润降幅会被部分缓冲。西藏城投仍未形成稳定锂业务利润，PE与FCFE不适用，不能因为拥有盐湖资源就套用成熟资源股估值。

### 当前市场究竟在要求什么

{_market_expectation_table(companies, recon_by_name)}

“当前市值/基准利润”与供应商前瞻PE不同是正常现象：前者使用本研究冻结的独立利润，后者使用供应商一致预期。差异越大，越需要找到具体经营变量，而不是争论哪一个倍数更正确。大中矿业和永杉锂业当前市值明显高于正常化PE核心区间，市场更可能在提前计入尚未兑现的项目或利润修复；中矿资源的独立利润高于市场一致预期，只有Bikita产量、资源覆盖和成本兑现时才构成正向预期差。

### PB—ROE与PB—ROA怎样用于资源股

PB—ROE回答的是净资产能否持续创造超过股权成本的回报，不直接给矿山寿命或资源价值。高锂价会同时抬升利润和净资产，周期顶部ROE不能永久化；资源项目减值、少数股东和高杠杆也会让ROE偏离经营质量。因此PB—ROE只对盐湖、成熟资源与多元业务提供资产回报检查，周期折价后再与正常化PE交叉验证。PB—ROA则用于区分ROE究竟来自资产效率还是杠杆：ROE上升而ROA不升，不能自动提高PB中枢。

### 现金流为什么比利润更严格

模型中的FCFE按利润乘公司特定现金转换率形成近似，目的是识别“利润增长但现金没有回来”的风险，不是伪装成完整现金流预测。逐年资本开支、营运资金和项目融资公开不足时，FCFE只作比较值；公司详情页的远期经营现金流与资本开支保持为空，不用2025实际值机械外推。若未来取得项目级资本预算、投产节奏和营运资金数据，再升级为完整股权现金流模型。

完整估值结果如下，单位为亿元人民币：

{_valuation_table(companies, recon_by_name)}

## 总结

买点不等于“PE低”：只有当前市值低于多个适用模型、项目和现金流又能验证时，低估才有意义。卖点也不等于“锂价跌”：若低成本产量增长抵消价格回落，盈利仍可能上升。公司页给出具体区间、市场隐含条件和验证指标。
"""

    q5 = _front(
        industry_id=industry_id,
        name="锂",
        title="Q5 资源政治",
        dynamic="资源国从采矿税转向本地加工、国有权益与出口约束。",
    ) + f"""
# Q5｜全球项目与资源政治

## 本章综述

**资源民族主义对锂企业的影响不只是一项税率。** 津巴布韦限制精矿出口、智利推动国有主导合同、马里提高国家与本地权益、阿根廷则以项目和出口扩张吸引资本。它们分别改变产品形态、资本开支、项目权益、建设周期和现金汇回，因此必须进入产量和现金流，而不能只提高一个贴现率。{policy}

## 问题

主要资源国的政策如何改变全球有效供给和中国公司的项目价值？

## 证据与数据

| 国家/地区 | 可核验进展 | 对供给的影响 | 对公司财务的影响 |
|---|---|---|---|
| 阿根廷 | 2025矿业出口创纪录，锂在产矿山增加 | 盐湖增量重要，但爬坡分散 | 汇率、税费、基础设施和项目权益决定归母现金 |
| 智利 | Maricunga合同推进，国家战略强调国有参与 | 新项目更可控但审批与合作结构更复杂 | 国有伙伴、税制和水资源影响价值分配 |
| 津巴布韦 | 政府继续推动本地加工并约束精矿出口 | 原矿/精矿不能无条件出口 | 需要新增加工资本开支，影响中矿、盛新等项目现金 |
| 马里 | Bougouni与Goulamina推进，国家与本地权益提高 | 2026精矿增量可观但权益受限 | 赣锋等公司不能按项目100%产量计算归母利润 |
| 玻利维亚 | 国有企业目标仍小，产业化慢 | 资源量大但近期有效供给有限 | 不应把巨大资源量纳入三年供给 |
| 尼日利亚 | 公开的是原矿处理能力 | 显示本地加工政策，但无法直接折LCE | 缺品位、回收率和权益时不进入供给模型 |

{policy} {_cite(source_ids, 'bolivia_ylb_2026', 'nigeria_lithium_plant')}

## 建模方法

政策通过四个参数传导：投产年份、爬坡率、公司权益、单位成本/资本开支。只有有公开量化依据时才调整；没有品位和回收率的原矿处理厂不换算成LCE。政策事件如果只改变远期期权而不改变三年销量，就进入估值上限和风险说明，不进入基准利润。

## 研究与分析

津巴布韦与马里的共同趋势是从资源出口转向本地加工和国家参与。这可能抬高进入门槛、减少简单精矿出口，却也提高先行企业的沉没资本与政策暴露。阿根廷的项目并行提高全球盐湖供给弹性，但各省、基础设施和爬坡差异使“阿根廷总规划产能”不能被当作单一项目。

中国公司的优势是工程、融资和下游消化能力；劣势是海外权益、税费和现金汇回更复杂。海外项目盈利要同时回答：公司穿透权益多少、可售产品是什么、资本开支由谁承担、现金何时能回到上市公司。

对具体公司，政策传导具有明显差异。赣锋的阿根廷与马里项目要分别处理地方税制、国家权益和产品出口；中矿、盛新和雅化在津巴布韦的项目更直接面对本地加工与电力物流；天齐的澳大利亚资源虽然制度稳定，但少数股东、税费和海外分红仍会改变归母现金。把所有海外项目统一加两个百分点折现率，会掩盖投产年份和权益比例这两个更重要的财务变量。

政策也可能改善竞争格局。更高的本地加工门槛会淘汰缺乏资金、工程与客户能力的项目，已有配套的企业可能获得先发优势；但先发优势只有在新增资本开支能获得合理回报、项目现金可以汇回时才成立。研究因此不把“资源国政策收紧”机械解释为利空或利多，而是逐项重算销量、成本、权益和现金分配。

## 总结

未来三年资源政策会让“有资源”和“能产生归母现金”进一步分化。公司模型应优先下调权益和爬坡，而不是在最后用一个模糊国家风险折价掩盖经营影响。
"""

    q6 = _front(
        industry_id=industry_id,
        name="锂",
        title="Q6 综合判断",
        dynamic="官方基准先过剩后趋平，压力情景分叉大，选股重于单一方向押注。",
    ) + f"""
# Q6｜综合判断

## 本章综述

**锂行业官方基准在2029年前仍有余量、2030附近趋平，最有价值的结论是公司分化，而不是统一看多。** 2028年官方余量约11.7万吨LCE；项目延迟且需求偏强的压力测试会转为约11万吨缺口，投产顺利情景则扩大到约35万吨余量。因此行业仓位要跟随项目和库存验证，公司仓位则跟随权益产量、成本与现金流。

## 问题

行业、公司和估值三层信息如何转成可执行的研究结论？

## 证据与数据

{_supply_scenarios(supply)}

{_valuation_table(companies, recon_by_name)}

{company_filings} {aus}

## 研究与分析

行业看多条件是：全球库存没有重新累积、阿根廷与非洲项目爬坡低于基准、储能需求保持高增、回收增量没有抵消原生需求。反方条件是：澳洲复产与新矿顺利、盐湖集中达产、储能需求或单位锂耗低于基准。两种情况都能在季度数据中验证。

公司选择优先级是：第一，低成本权益资源和已投产销量；第二，资本开支后的自由现金流；第三，当前市值相对正常化利润和可持续ROE；第四，项目与国家风险。仅有远期资源量或规划产能的公司必须使用更高的兑现折扣。

从正常化PE核心区间看，一些公司当前市场已计入较强锂价或更快项目爬坡，另一些公司仍处在区间下部。PB—ROE和FCFE只作交叉检查，不扩宽核心区间。它们不是静态买卖评级：当季度产量、资源覆盖、成本和现金流偏离模型时，估值区间必须随输入更新。

## 总结

基准配置偏向低成本、权益清晰、现金流可验证的公司；高弹性项目型公司只在投产节点得到证明后提高权重。行业价格是公共因子，项目兑现和资本纪律才是超额收益来源。
"""

    q7 = _front(
        industry_id=industry_id,
        name="锂",
        title="Q7 方法、监控与资料边界",
        dynamic="用项目、库存、价差和现金流四层指标持续证伪模型。",
    ) + f"""
# Q7｜方法、监控与资料边界

## 本章综述

**研究需要持续更新的不是一篇长报告，而是有限几个可证伪参数。** 行业模型每季度更新项目产量、区域供给、分项需求和库存；公司模型更新权益销量、资源覆盖、成本、资本开支和非锂利润；价格变化只有通过这些参数才进入长期估值。

## 问题

如何持续监控模型，哪些资料限制会改变结论？

## 证据与数据

| 频率 | 指标 | 触发阈值 | 研究动作 |
|---|---|---|---|
| 周/月 | 碳酸锂价格、精矿折扣、库存、期现结构 | 连续4周偏离模型方向 | 检查库存与短期价差，不立即改长期需求 |
| 月/季 | 主要国家和项目产量、出口、开工 | 单一年度供给偏离基准5%以上 | 更新区域供给与行业余额 |
| 季 | 13家公司销量、成本、毛利、现金流、资本开支 | 利润或现金流偏离基准15%以上 | 逐公司重建利润桥 |
| 半年 | 储能、动力和回收需求 | 分项需求偏离10%以上 | 更新需求结构和价格情景 |
| 事件 | 许可、税费、出口、本地加工、权益变化 | 改变投产年或归母权益 | 同时更新供给和公司现金流 |

## 研究与分析

公开资料的最大限制是口径：精矿吨位需要品位和回收率，盐湖名义产能需要爬坡与品质，资源量需要项目时间与资本开支，化学品销量需要区分碳酸锂和氢氧化锂。模型对这些限制使用宽情景，不通过补一个“行业平均值”伪造精确性。

外部一致预期在独立模型冻结后才读取，使用Wind作为结构化主对账、Tushare最近六个月内逐机构最新报告作为明细核验；同一机构多份报告不重复计权，英文机构与中文机构同级。差异只有找到新的项目或财务事实才修改，否则保留为预期差。

资料更新还要保持版本纪律。同一公司年报、季度报告、交易所公告和投资者交流若披露同一项目的不同时间表，采用发布日期更晚且口径更直接的记录，并保留旧版本用于解释变化；卖方报告引用公司公告时不再算一条独立证据。动态财务与行情按各自时点刷新，公司与行业研究只冻结模型输入、输出和对账结论，避免把旧快照复制成永久事实。

模型的数量级需要持续反算。一万吨LCE与一万元/吨相乘等于一亿元收入，不是十亿元；项目100%产量还要乘上市公司穿透权益；含税价格与含税成本相减后，再除增值税口径并乘税后归母转换系数。任何一项单位或权益错误都可能让远期利润放大十倍，因此每次更新必须先完成量纲检查，再讨论估值。

公开资料仍客观不足的部分包括部分项目的逐年资本开支、单位现金成本、客户长协和少数股东现金分配。当前做法是降低模型复杂度、给经营情景和估值区间，并明确哪些参数是研究假设；这些缺口会降低远期估值置信度，但不妨碍用已披露产量、权益和现金流识别方向。

监控结果必须区分“触发复查”和“改变结论”。单月产量低于计划、一次检修或一周库存波动只触发复查；只有偏差持续、改变年度可售量或公司现金流时，才修改供需和估值。相反，项目正式投产也不自动上调利润，仍需观察稳定运行、产品质量、销售和回款。这样可以避免研究在每个短期价格波动后反复追涨杀跌，也能在真正的项目拐点出现时及时更新，并保留每次假设变化的依据。

换言之，数据先改变参数，参数再改变结论，不能用短期行情直接替代经营证据。

## 总结

模型最重要的证伪条件是项目实际产量、库存方向、加工价差和自由现金流。任何单一价格或卖方目标价都不能替代这四层验证。
"""

    company_doc = _front(
        industry_id=industry_id,
        name="锂",
        title="锂行业公司透视",
        dynamic="13家公司按资源、加工、非锂业务和项目兑现分别建模。",
    ) + f"""
# 锂行业公司透视

## 问题

13家重点公司的锂业务分别依赖什么资源、项目和加工环节，实际权益和会计归属是什么；2026—2028产量、成本、非锂利润和资本开支怎样形成归母利润、自由现金与估值；哪些公司已经有成熟现金，哪些仍主要是项目期权？

## 研究方法与数据

公司公告、年报和项目文件用于确认资源、穿透权益、2025实际产量或能力以及投产节点；独立模型把销量、资源覆盖、全现金成本、其他业务、归母利润和FCFE逐年冻结，再读取Wind一致预期和研究截止日前最近两个季度的机构预测对账。下表中的未来数值是研究情景，不是公司指引；动态PE、PB和市场数据只由公司页读取财务库。

{_company_project_table(companies, source_ids)}

## 研究与分析

以下逐家公司把经营事实、2026—2028情景、Wind与最近机构预测、适用估值、当前市值隐含条件和验证点放在同一位置。不同公司分别建模，不用“锂价上涨/下跌”替代公司分析。

{_deep_company_dossiers(companies, recon_by_name, source_ids)}

## 财务与外部对账

{_company_model_table(companies, recon_by_name)}

{_broker_reconciliation_table(companies, recon_by_name)}

公司详情页展示Wind/Tushare财务、PE/PB Band、PB—ROE/PB—ROA、独立模型、市场隐含预期与交易观察。行业文档不复制随时变化的供应商快照，以免形成第二套过期财务事实。

## 总结

**13家公司都已分别建立2026—2028经营、盈利、现金和估值链，不能再用一个“锂价弹性”排序。** 资源型公司比较权益销量和成本，加工型公司比较加工价差与库存，多元公司比较分部利润和现金，项目型公司比较融资、投产和爬坡。跨组直接比较PE会误导；更可执行的优先级是先验证项目和权益，再看现金，最后判断当前估值是否已经计满。
"""

    valuation_doc = _front(
        industry_id=industry_id,
        name="锂",
        title="锂行业估值对比",
        dynamic="正常化利润、PB—ROE和FCFE交叉核验，当前市场用反向估值解释。",
    ) + f"""
# 锂行业估值对比

## 问题

如何把13家公司的项目、权益销量、资源覆盖、成本、非锂业务和现金流差异转成可复算的盈利与估值区间，并判断当前市值已经计入了多高的锂价、产量和回报率？

## 研究方法与数据

本研究先以2025实际财务和项目事实冻结2026—2028年逐公司销量、资源覆盖、资源成本、加工利润、非锂利润与现金转换，再读取Wind一致预期和研究截止日前最近两个季度的机构预测进行外部对账。三条价格路径分别代表下行、基准和上行经营状态，不赋主观概率；当前市值只用于反推市场要求的利润，不用于改写独立模型。

估值只启用经济逻辑与数据同时适用的方法：正常化PE资本化2027年基准利润；PB—ROE检查净资产能否产生可持续回报，并用PB—ROA识别杠杆放大；FCFE检查利润能否转为股东现金。公开资料不足以逐项目复原储量、税制、资本开支和寿命时，不伪造完整矿山NAV，也不对三种方法机械平均。

## 研究与分析

### 模型结果

{_valuation_table(companies, recon_by_name)}

### 各公司上下限参数、公式与依据

{_valuation_parameter_table(companies)}

{company_filings} {reports}

### 方法与实际代入

#### 正常化PE

正常化PE使用2027年基准归母利润，因为2026仍包含项目爬坡、2028又更依赖远期产量。倍数不是全行业统一：低成本成熟资源和稳定非锂业务可以使用区间上部；外购矿加工、单项目或尚未盈利公司使用区间下部或关闭PE。以赣锋为例，2027基准利润73.46亿元乘12—16倍，对应约882—1,175亿元；以中矿资源35.45亿元乘11—15倍，对应约390—532亿元。倍数只资本化正常化利润，不另加一遍同一项目的远期价值。

#### PB—ROE

PB—ROE按“可持续PB＝（可持续ROE－长期增长率）÷（股权成本－长期增长率）”计算。可持续ROE上限不超过22%，下限再根据资源覆盖、业务成熟度和项目风险降低；低值统一用较高股权成本12.5%与较低长期增长2.0%，高值用10.5%与3.0%。每家公司实际ROE范围和结果均列在上表；没有再对计算结果机械加减百分比，也没有设置最低PB托底。它适合判断低成本盐湖、成熟资源或多元业务的资产回报是否被过度资本化；对加工型公司和项目型亏损公司解释力较弱，不能因为公式能算就升为核心方法。

#### 股权自由现金流

FCFE先使用2026—2028冻结的利润和公司特定现金转换率，再按股权成本与长期增长折现。当前公开资料无法对13家公司全部项目逐年拆出建设资本、维持资本和营运资金，因此模型输出的是现金流比较值，并披露终值占比；终值主导时只用于验证PE或PB的数量级，不作为精确目标价。未来取得项目级资本预算后再升级，不能用2025资本开支固定比例替代。

### 三情景财务与当前市场隐含预期

{_scenario_financial_table(companies, recon_by_name)}

{_market_expectation_table(companies, recon_by_name)}

这两张表分别回答“经营变量变化会产生多大财务范围”和“当前价格已经要求多少利润”。交易判断的关键不是选择上行情景，而是识别当前市值更接近哪一个情景、市场尚未计入的变量是否有可验证证据。公司当前价与市值来自财务库的最新市场快照，独立利润来自冻结研究模型，二者的时点和来源分开保留。

### 为什么三种方法会不同

正常化PE对盈利假设最敏感，适合看周期中段的归母利润；PB—ROE对净资产与可持续ROE敏感，适合盐湖、资源与成熟业务，但必须给周期ROE折价；FCFE对资本开支和现金转换最敏感，当终值占比过高时只作诊断。矿山NAV需要逐项目储量、成本、资本开支、税制、权益和折现率，公开数据不足的公司不强行计算。

三种方法分歧不是噪声。PE显著高于PB—ROE，通常表示利润假设较强但资产回报持续性不足；PE高于FCFE，表示盈利没有充分转成股东现金；PB高于PE，可能是当前利润处于周期底部或账面资产尚未盈利。研究先解释分歧，再选择核心区间，不对三个结果做算术平均。

### 与Wind和最近两个季度机构预测对账

{_broker_reconciliation_table(companies, recon_by_name)}

Wind提供结构化一致预期，最近机构样本保留机构名与发布日期；同一机构同一年度只取最新报告，英文机构与中文机构同级。赣锋、天齐、天华和大中的独立利润低于市场，是更慢项目爬坡、更低资源覆盖或更保守锂价共同造成；中矿独立利润高于市场，则是对Bikita和自给率的更强假设。对账只定位变量，不把独立模型硬改到中位数。

### 买卖点如何使用

当前市值低于核心方法下沿不是自动买入，需要同时验证项目产量和现金流；高于核心方法上沿也不是自动卖出，可能反映市场采用更高长期锂价或更快爬坡。真正的买点是“项目/现金流上修而市值仍按旧假设定价”，卖点是“价格或项目下修已发生而估值仍要求旧利润”。

执行上按四个层次判断：

1. 现货和库存只决定是否启动复查，不直接决定长期估值。
2. 项目产量、权益和成本改变公司独立利润，是模型的第一层修订。
3. 经营现金流、资本开支和营运资金决定利润能否转成FCFE，是第二层修订。
4. 当前市值和估值倍数决定好经营是否已经被定价，只有事实上修快于定价上修时才形成更好的买点。

反方也必须对称处理：锂价上涨但精矿成本、库存或资本开支同步上升，可能只改善会计利润而不改善股东现金；锂价回落但低成本产量快速增长，也可能维持利润。价格方向不能替代逐公司财务桥。

## 总结

公司页中的综合估值与交易观察区是正式落点；本页用于横向比较方法适用性和差异，不替代逐公司的项目与财务判断。
"""

    return {
        "锂.md": main,
        "锂_Q0_历史发展.md": q0,
        "锂_Q1_竞争格局.md": q1,
        "锂_Q2_市场空间.md": q2,
        "锂_Q3_公司壁垒.md": q3,
        "锂_Q4_行业特征.md": q4,
        "锂_Q5_资源政治.md": q5,
        "锂_Q6_综述.md": q6,
        "锂_Q7_补充.md": q7,
        "锂_公司透视.md": company_doc,
        "锂_估值对比.md": valuation_doc,
    }


def _carbonate_documents(
    industry_id: int,
    source_ids: dict[str, int],
    models: dict[str, Any],
    recon: dict[str, Any],
    carbonate: dict[str, Any],
) -> dict[str, str]:
    companies = models["companies"]
    recon_by_name = {row["company"]: row for row in recon["companies"]}
    iea = _cite(source_ids, "iea_gcm_2026")
    miit = _cite(source_ids, "miit_lithium_2026q1")
    production = _cite(
        source_ids, "cnfin_carbonate_2026h1", "cnmn_carbonate_2026h1"
    )
    association = _cite(
        source_ids,
        "lithium_association_2025",
        "lithium_association_2025_competition",
        "lithium_association_2025h1",
    )
    h1_market = _cite(
        source_ids,
        "smm_carbonate_2026h1",
        "smm_customs_carbonate_2026h1",
    )
    reports = _cite(
        source_ids,
        "dongwu_carbonate_20260226",
        "zheshang_lithium_20260614",
        "dongbei_carbonate_20260519",
        "haizheng_futures_20260724",
    )
    company_filings = _cite(
        source_ids,
        *(
            f"ar_{company['ticker'].replace('.', '_')}_2025"
            for company in companies
        ),
    )
    front = _front(
        industry_id=industry_id,
        name="碳酸锂",
        title="碳酸锂行业主文档",
        dynamic="2026上半年供需紧平衡，年度中值接近均衡；库存、进口、路线成本与需求决定价格传导。",
    )
    main = front + f"""
# 碳酸锂行业：小缺口不等于单边价格，关键是库存和边际成本

> **核心结论。** 2025年中国碳酸锂实际产量97.6万吨、进口24.30万吨、出口0.529万吨，表观供给约121.37万吨，与外部行业估计的121.2万吨需求基本相当。2026年上半年国内产量因样本不同为59.36万—63.0万吨，进口17.9万吨、出口0.2348万吨，表观供给约77.03万—80.67万吨；SMM同时把上半年描述为紧平衡，月度需求从1月12.47万吨升至6月15.10万吨。**因此当前证据支持“紧平衡和高波动”，不支持把一个窄幅年度缺口写成确定短缺。** {association} {production} {h1_market}

![中国碳酸锂表观平衡](/static/generated/lithium/carbonate_china_balance.png)

## 本报告回答什么

本报告独立研究碳酸锂产品市场，口径为国内产量＋进口－出口与下游需求的年度平衡；不把全球锂资源LCE平衡直接搬过来。研究覆盖产量、进口、库存、需求、价格、成本、期现结构和13家公司财务传导。计算器后续将作为独立“工具”侧栏的第一个工具恢复Excel的逐矿项目、权益和备注，目前研究结论不依赖尚未完成的交互界面。

## 产品平衡

单位：百万吨碳酸锂；余额为可用供给减需求。

{_balance_table(carbonate, carbonate=True)}

公式是：**可用供给＝国内产量＋进口－出口；产品余额＝可用供给－下游需求。** 2025产量和海关是实际值，需求来自外部行业估计；2026—2028表内数字是研究中值，必须与下面的范围一起阅读。2026中值为国内产量139.5万吨、进口36.5万吨、出口0.5万吨、需求177万吨，余额约-1.5万吨，但合理范围同时包含过剩和短缺，不能把中值当确定预测。{association} {h1_market}

### 2026年上半年已经发生了什么

{_carbonate_h1_table(carbonate)}

{production} {h1_market}

### 未来情景的真实不确定性

{_carbonate_forecast_ranges(carbonate)}

## 为什么余额不能直接定价

年度平衡没有显式扣减库存。库存样本在扩容时会制造跳变，仓单、工厂库存、贸易库存和下游库存的可用性也不同；本研究只用库存方向验证，不把不同样本相加。进口还存在保税、转口和品类差异，氢氧化锂虽可转换为碳酸锂但有成本与时滞。2026上半年样本库存约9.77万吨，规模大于年度中值1.5万吨缺口，因此余额只有与持续去库、进口变化和边际成本同向时才具备价格解释力。

价格判断还要穿过成本曲线。国内盐湖、锂云母、外购精矿和回收的边际成本不同，海外盐湖进口又受汇率、运费和国内外价差影响。当价格接近高成本供给的现金成本时，检修和减产会减少供给；当价格显著高于激励价格时，停产矿、低品位资源和回收会重新进入。成本曲线因此是动态的，不能用一个静态“行业成本线”推断长期价格。

从时间维度看，现货、期货和公司财务也不同步。现货先反映可交易库存和临时检修，期货反映远期供需与资金结构，公司利润还要经过产品结构、长协、原料库存和会计结转。年度紧平衡可以与短期贴水并存，也可以与期货升水并存。研究必须先解释是哪一层变化，再判断是否需要修改公司三年模型。{reports}

## 公司财务传导

单位：亿元人民币。

{_company_model_table(companies, recon_by_name)}

{_broker_reconciliation_table(companies, recon_by_name)}

{company_filings} {reports}

公司模型使用含税碳酸锂等价价格路径，不代表每家公司所有产品都按现货成交。氢氧化锂、精矿、长协和代加工需要通过销量、资源覆盖与单位加工利润体现。完整公司估值和市场隐含预期见[估值对比](/industry/{industry_id}/valuation)与各公司页。

按业务结构看，天齐、中矿、赣锋等资源覆盖较高的公司对价格—成本差更敏感；盐湖股份、藏格和永兴还要分别考虑钾肥、盐湖工艺、锂云母环保与特钢利润；天华、雅化、永杉等加工占比较高的公司不能只看产品价；大中与西藏城投则主要看项目兑现。**同一条价格路径只是公共输入，不代表同一利润增速。**

## 投资结论

碳酸锂交易应先看库存与期现结构，再看月度产量、进口和需求；锂股票则必须继续看权益产量、成本和资本开支。行业价格反弹可以改善资源型公司利润，但对外购矿加工企业可能先形成库存收益、后形成价差挤压，不能用同一弹性。

本报告把“产品价格观点”和“股票价值判断”明确分开。前者可以在月度库存与期现结构变化后调整，后者只有在年度销量、成本、现金流或可持续ROE改变时才调整。若产品价格上涨但股票已经隐含更高的长期价格，行业方向正确仍可能缺少回报空间；若价格短期偏弱而低成本项目与现金流持续上修，公司价值也可能改善。
"""

    q0 = _front(
        industry_id=industry_id,
        name="碳酸锂",
        title="Q0 历史发展与价格周期",
        dynamic="库存、供给时滞与边际成本共同解释价格超调。",
    ) + f"""
# Q0｜历史发展与价格周期

## 本章综述

**碳酸锂价格周期是供需、库存与成本曲线的叠加。** 2021—2022低库存放大需求冲击，2023—2024新增供给和累库压低价格，2025下半年至2026上半年又出现需求提速、进口增长、国内增产和库存下降并存。紧平衡只有在库存持续去化、边际成本抬升且进口不能完全补充时，才会变成更高价格中枢。

## 问题

为什么年度供需和现货价格经常不同步？历史规律怎样用于当前判断？

## 证据与数据

工信部披露2026年一季度进口8.3万吨，同比增长64.6%；海关上半年累计进口17.9万吨、出口0.2348万吨。国内产量口径在59.36万—63.0万吨之间，分路线低口径为辉石37.37万吨、云母7.67万吨、盐湖9.05万吨、回收5.45万吨。数据说明进口和辉石供给增长很快，锂云母却受换证与成本扰动；“总量紧”与“路线分化”可以同时成立。{miit} {production} {h1_market}

| 阶段 | 供需状态 | 库存与价格 | 对模型的启示 |
|---|---|---|---|
| 2021—2022 | 需求和补库快于供给 | 低库存放大价格上涨 | 峰值价格不能作长期基准 |
| 2023—2024 | 新矿、盐湖和锂盐产能释放 | 去库存与成本下移放大下跌 | 规划供给要看可售产量 |
| 2025 | 国内产量97.6万吨、净进口23.7万吨 | 下半年去库、价格修复 | 产量和进口都要纳入表观供给 |
| 2026H1 | 产量59.36万—63.0万吨、进口17.9万吨 | 月度需求上升、样本库存约9.77万吨 | 路线、库存与需求必须同口径跟踪 |
| 2026以后 | 年度中值接近平衡、区间很宽 | 库存去化时波动向上 | 区间和验证条件比单点更重要 |

## 研究与分析

年度缺口只有2%—4%时，仓单释放、进口变化和生产检修足以改变现货；但连续两年小缺口会逐步耗尽可用库存，使价格对事件更敏感。研究因此把“年度平衡”和“可交易库存”分开：前者决定中期方向，后者决定短期斜率。

成本曲线也不是固定的。矿石折扣、汇率、能源、副产品、税费和产能利用率都会移动边际成本；高价还会激励低品位资源、回收和转换。不能用单一“行业成本线”给所有公司估值。

2015—2020也提供了一个重要反例：价格下跌会让高成本供给退出，但已经建成且现金成本较低的项目仍可能继续增产，导致供给调整慢于市场预期。2021—2022则显示，当可交易库存足够低时，即使年度缺口不大，补库和交付约束也能造成价格超调。把两段历史合起来，当前研究更关注库存的绝对可用性与项目现金成本，而不是只比较年度增速。

价格周期对企业会计利润还有库存效应。上行初期，持有低价原料或产品库存的加工企业可能先释放库存收益；上行持续后，原料采购价上升可能压缩加工价差。下行时则相反，资源企业利润直接下滑，加工企业还可能承担高价库存减值。因而季度毛利率和经营现金流比单一收入增速更能识别利润质量。

对2026判断最有用的历史检验是：月度缺口是否连续、库存是否跨样本下降、价格上涨后供给是否恢复。如果只有价格上涨而产量、进口和库存没有支持，行情更可能来自交易与预期；如果三者同步验证，年度平衡才需要上修价格路径。

历史比较还必须使用相同的价格和库存定义。电池级、工业级、长协和期货价格不能无差别拼接，社会库存样本扩容也不能被解释为真实累库。研究保留每条序列的来源、样本和时点，只在同口径内判断趋势，再用多个独立样本确认方向。

这也是本轮不把旧价格图直接续接到新库存样本、避免错误趋势的核心原因。

## 总结

当前碳酸锂更接近紧平衡下的高波动，而不是确定单边趋势。只有缺口、库存去化和边际成本抬升同时成立，价格上行才具有持续性。
"""

    q1 = _front(
        industry_id=industry_id,
        name="碳酸锂",
        title="Q1 竞争格局",
        dynamic="盐湖、锂云母、硬岩矿和外购矿加工对应不同成本与供给弹性。",
    ) + f"""
# Q1｜竞争格局

## 本章综述

**碳酸锂的竞争格局首先是工艺路线竞争，其次才是公司产量排名。** 2025年上半年碳酸锂前十企业产量占全国51%，前三为九岭锂业、天齐锂业和中信国安；全年有29家企业产量超过1万吨，前五企业依次为九岭、中信国安、天齐、赣锋和华友。官方公开材料没有披露前五各自产量，所以本报告给出可核验的CR10和企业身份，不伪造2025年CR3/CR5。{association}

## 问题

中国碳酸锂供给由谁决定，13家公司如何分层？

## 证据与数据

| 路线 | 主要公司例子 | 成本与弹性 | 主要约束 |
|---|---|---|---|
| 盐湖提锂 | 盐湖股份、藏格矿业 | 低成本、爬坡较慢 | 卤水品位、吸附/膜工艺、季节、钾锂协同 |
| 锂云母 | 永兴材料等 | 国内资源、成本对品位敏感 | 能耗、渣处理、环保与采选稳定 |
| 硬岩矿一体化 | 赣锋、天齐、中矿、盛新 | 资源覆盖提高价格弹性 | 品位、运输、权益、资源国政策 |
| 外购矿加工 | 天华、雅化、永杉等 | 收入规模大，利润看价差 | 采购、库存、客户认证和利用率 |
| 项目期权 | 大中、西藏城投等 | 上行弹性大 | 许可、建设、试车、融资与产量 |

## 研究与分析

2025年国内碳酸锂产能178万吨、产量97.6万吨，简单利用率约54.8%。这个比值不能直接解释每条产线，因为锂盐柔性线会在氢氧化锂和碳酸锂之间切换，协会又明确不重复统计产品互转；但它足以说明名义产能远大于当年有效产量。盐湖装置需要逐季爬坡，锂云母受环保与渣处理约束，外购矿加工受原料和价差限制，能稳定生产电池级产品并销售的有效产能小于名义产能。{association}

中国2025H1碳酸锂CR10为51%，说明国内产品市场比全球矿端国家格局分散得多；同期香港氢氧化锂CR10达到98%，又说明产品结构不同会产生完全不同的集中度。全球化学品销售CR3/CR5约32%/41%，回答的是跨碳酸锂和氢氧化锂的企业销售，不能替代中国碳酸锂份额。三个数字并列的意义是避免用一张“龙头排名”掩盖分母差异。{association} {_cite(source_ids, 'sqm_20f_2025')}

对投资最有用的结论不是谁的名义产能最大，而是谁能在价格回落时保持可售量和现金成本、在价格上涨时又不被外购矿和库存吞噬利润。九岭、中信国安等非本研究13家公司进入全国前列，也说明A股本地样本不能被当作竞争候选上限；行业格局必须同时覆盖非上市和全球公司。

{_common_company_analysis(companies, source_ids)}

## 总结

碳酸锂竞争应按路线、资源覆盖和可售质量比较。低成本路线决定周期底部，加工和库存管理决定中段利润，项目兑现决定上行期弹性。
"""

    q2 = _front(
        industry_id=industry_id,
        name="碳酸锂",
        title="Q2 市场空间与供需",
        dynamic="2026H1紧平衡，年度中值接近均衡但合理区间同时包含过剩和短缺。",
    ) + f"""
# Q2｜市场空间与供需

## 本章综述

**2026—2028中国碳酸锂年度研究中值分别为-1.5、-1.8和0万吨，均接近均衡；更重要的是合理区间同时包含明显过剩和短缺。** 2026年余额区间约-7万至+6万吨，2027和2028因项目与需求不确定性进一步扩大。结论不是“缺口逐年扩大”，而是库存、进口、路线成本和需求的边际变化会放大价格波动。

## 问题

中国碳酸锂的国内产量、进出口、需求和库存如何形成可复算平衡？

## 证据与数据

{_balance_table(carbonate, carbonate=True)}

![中国碳酸锂供需与余额](/static/generated/lithium/carbonate_china_balance.png)

{_carbonate_h1_table(carbonate)}

{_carbonate_forecast_ranges(carbonate)}

## 建模方法

**可用供给＝国内产量＋进口－出口；产品余额＝可用供给－动力、储能、消费和非电池需求。**

2026年度中值139.5万吨国内产量受到上半年59.36万—63.0万吨实际区间和SMM下半年约78.6万吨展望约束，36.5万吨进口受到上半年17.9万吨实际值约束；这不是把不同样本机械平均，而是把中值与59.36万—63.0万吨实际区间、138万—141万吨全年产量范围同时展示。库存只用于方向校验，避免样本扩容后同一批货被解释为新增供给。{miit} {production} {h1_market}

## 研究与分析

需求侧最重要的变化是储能，动力仍是大项但增速更稳定。储能项目集中交付会造成月度需求尖峰，也可能因电芯和系统库存产生阶段性回落。供给侧的进口相当于缓冲器：当海外盐湖和矿山增量释放、国内外价差打开时，进口会扩大。

碳酸锂与氢氧化锂并非完全同质。转换存在成本、损耗、品质和时间，因此在极端价差下才显著改变可用供给。模型把转换作为边界而非固定数量，避免重复计算。

### 2026年上半年各路线怎样贡献供给

SMM和行业样本口径虽有差异，但路线结构能揭示边际来源：锂辉石约37.37万吨，占所列路线产量约62%；盐湖约9.05万吨、锂云母约7.67万吨、回收约5.45万吨。辉石路线决定进口精矿与国内锂盐厂负荷，盐湖决定低成本底部，云母受采矿、环保和渣处理影响，回收则同时受废料量与原料价格约束。把四条路线合成一个“国内产量”会掩盖供给在不同价格下的响应速度。{production} {h1_market}

| 路线 | 2026H1样本产量 | 对价格的典型反应 | 最需要验证的变量 |
|---|---:|---|---|
| 锂辉石 | 37.37万吨 | 原料与产品价差收窄时盐厂减产，进口增量可较快进入 | 精矿进口、折扣系数、盐厂开工和库存 |
| 盐湖 | 9.05万吨 | 现金成本较低，短期对价格回落不敏感 | 季节、吸附/膜稳定性、品质和爬坡 |
| 锂云母 | 7.67万吨 | 靠近边际成本，环保或采矿变化可快速影响供给 | 采矿证、品位、渣处理、能耗与现金成本 |
| 回收 | 5.45万吨 | 原料折价与回收经济性决定开工 | 废料来源、金属价格联动和回收率 |

### 进口为什么既是缓冲器也是放大器

2026年上半年碳酸锂进口17.9万吨，已经接近2025全年24.3万吨的四分之三。进口增加可以缓冲国内项目延误，但也可能在国内价格下跌时形成库存压力；船期、保税和境内外价差又会使进口量与当月消费错位。研究不把进口简单外推十二个月，而是用“上半年实际＋海外项目/价差约束”形成35万—37万吨全年净进口范围。{association} {h1_market}

### 年度紧平衡为什么可以与价格大幅波动并存

IEA指出，2025年至2026年初锂价在储能需求强劲和供给受限下明显反弹，即使更新后的中长期项目池使远期供给缺口收窄。中国样本库存约9.77万吨，远大于2026年中值1.5万吨缺口；但库存并非全部可交割、可销售或位于需求地。只要可交易库存、进口船期或某条高占比路线出现扰动，现货价格就可能先于年度余额变化。反过来，年度小缺口也可能被库存释放吸收而不造成持续上涨。{iea} {h1_market}

模型对2026国内产量和需求同样敏感。若全年产量比139.5万吨中值高5%，供给增加约7.0万吨；若进口比36.5万吨中值少10%，供给减少约3.7万吨；若需求177万吨中值高5%，需要再增加约8.9万吨供给。任一项都大于1.5万吨中值缺口，说明当前不是“预测到小缺口就结束”，而是要持续识别哪一个参数偏离。

月度数据不能直接年化。上半年检修、春节、环保和新装置试车会改变季节分布，进口也受船期和价差影响。研究使用滚动三个月和累计同比观察趋势，再检查项目与需求原因；单月创高或创低只触发复查，不自动重写年度数。

与全球LCE模型对账时，只比较方向和可解释的产品转换。全球模型包含精矿、盐湖、回收及不同锂化学品，中国碳酸锂模型只统计产品可用量；若全球资源偏紧而中国产品仍过剩，可能来自库存、产品结构或进口提前释放，并不构成逻辑矛盾。

情景更新采用阈值而非每日追价：滚动三个月供给或需求偏离年度基准5%以上，才重算年度余额；公司季度销量或利润偏离15%以上，才重建公司桥。这样既能捕捉真实拐点，也避免把短期噪声误当结构变化。

### 哪些变化会推翻当前判断

若下半年国内月均产量持续高于11.8万吨、净进口保持每月3万吨以上且样本库存连续累积，2026基准应向过剩端移动；若锂云母或进口精矿同时收缩、样本库存持续下降且月度需求保持15万吨以上，基准应向短缺端移动。这里的阈值来自年度中值反算，不是外部事实，也不是交易信号；它们的作用是规定何时必须重算，而不是在任一单月命中后直接下结论。

## 总结

基准是紧平衡，但未来范围同时包含过剩和短缺。价格上修需要月度产量、进口、库存和需求共同验证；只看到一个年度中值，不足以把上行情景写进公司基准利润。
"""

    q3 = _front(
        industry_id=industry_id,
        name="碳酸锂",
        title="Q3 公司壁垒",
        dynamic="资源覆盖与加工价差决定公司对碳酸锂价格的真实弹性。",
    ) + f"""
# Q3｜公司壁垒

## 本章综述

**同样生产锂盐，公司对碳酸锂价格的弹性可能相反。** 自有资源企业受益于价格—成本差扩大，外购矿加工企业可能被原料涨价挤压，盐湖和云母企业还受工艺与环保约束，多元企业的非锂业务会平滑利润。

## 问题

哪些公司能把行业价格变成可持续归母利润和现金流？

## 证据与数据

{_company_project_table(companies, source_ids)}

## 建模方法

公司模型把产品销量拆成资源覆盖部分和加工部分，并把非锂利润独立：

**归母净利润＝资源覆盖销量×资源单位利润＋外购加工销量×加工单位利润＋其他业务利润－公司层成本。**

含税碳酸锂等价价格只进入资源单位利润；氢氧化锂、精矿和长协通过销量、加工利润和资源覆盖调整，不假设所有产品按同一现货价出售。

## 研究与分析

{_common_company_analysis(companies, source_ids)}

## 总结

真正的碳酸锂壁垒是低成本资源、稳定工艺、客户和现金流的共同结果。若季度销量增长但资源覆盖下降、库存上升或现金流变差，名义产能增长不能视为壁垒增强。
"""

    q4 = _front(
        industry_id=industry_id,
        name="碳酸锂",
        title="Q4 盈利与估值",
        dynamic="三种价格情景穿透到13家公司利润、ROE、现金流与估值。",
    ) + f"""
# Q4｜盈利、现金流与估值

## 本章综述

**本研究用10/9/9、15/14/13、18/17/16万元/吨三条含税价格路径分别计算13家公司，而不是给当前利润统一乘涨跌幅。** 基准利润与Wind一致预期的差异主要来自项目爬坡、资源覆盖和价格路径，必须保留并跟踪。

## 问题

未来三年价格和项目如何传导到财务，当前估值隐含什么？

## 证据与数据

{_company_model_table(companies, recon_by_name)}

{_broker_reconciliation_table(companies, recon_by_name)}

{company_filings} {reports}

## 建模方法

模型先用2025实际财务与公司项目事实冻结2026—2028销量、资源覆盖、成本、加工利润、非锂利润与现金转换，再读取Wind一致预期和最近两个季度机构预测。市场市值用于计算独立FY1/FY2隐含PE，不能反向决定销量或锂价。

正常化PE是核心方法；PB—ROE只在净资产和可持续ROE能解释价值时使用，并对高周期ROE折价；FCFE用于识别资本开支和营运资金，但终值占比高时降为参考。结果如下，单位亿元：

{_valuation_table(companies, recon_by_name)}

## 研究与分析

赣锋、天齐、天华的独立基准低于一致预期，意味着市场更依赖高锂价、快爬坡或非锂业务；大中矿业的差异说明项目时间是核心分歧；中矿资源独立模型高于一致预期，需要用实际产量和成本证明。没有一致预期的融捷、永杉和西藏城投只显示独立情景，不伪造市场中位数。

### 从碳酸锂价格到公司利润实际代入了什么

**资源税后利润＝产品销量×资源覆盖率×（含税产品价－含税资源成本）÷1.13×税后归母转换系数；加工税后利润＝产品销量×（1－资源覆盖率）×单位加工利润÷1.13×税后归母转换系数；归母净利润＝资源利润＋加工利润＋非锂利润－公司层成本。**

三条价格路径为10/9/9、15/14/13、18/17/16万元/吨，但公司销量、资源覆盖、成本和非锂利润逐家不同。以中矿资源为例，模型把Bikita资源覆盖与国内锂盐转换分开；以盐湖股份为例，钾肥利润不随碳酸锂价格同步变化；以永杉为例，外购矿加工只赚加工价差，不获得完整资源价差。这是相同锂价下公司利润弹性不同的根本原因。

{_scenario_financial_table(companies, recon_by_name)}

### 市场价格和独立模型的差异在哪里

{_market_expectation_table(companies, recon_by_name)}

供应商前瞻PE使用市场一致利润，独立模型隐含PE使用本研究利润。赣锋、天齐、天华的两组PE差异较大，说明争议集中在价格路径、资源覆盖与爬坡；大中和永杉的当前市值高于正常化PE核心区间，市场更依赖尚未兑现的项目或利润修复；中矿的独立利润较高，必须用实际销量和成本验证，不能把模型上行直接当成买入理由。

### 为什么PB—ROE与现金流不能只是装饰

PB—ROE用于检查资产回报是否能持续覆盖股权成本。盐湖、成熟资源和多元业务拥有可解释净资产时，该方法有参考意义；加工型公司、亏损公司或远期项目公司则弱化。PB—ROA进一步检查高ROE是否由资产效率而非杠杆造成。股权自由现金流则检查利润能否在资本开支、营运资金和少数股东后回到股东；当前逐年资本数据不足，所以FCFE是比较值，公司页不再用2025资本开支比例机械填充未来经营现金流。

### 与最近两个季度机构预测怎样对账

{_broker_reconciliation_table(companies, recon_by_name)}

对账样本只使用最近两个滚动季度、同一机构同一年度的最新报告，英文与中文机构等权。机构中位数不是模型输入，只用于解释差异。只有新项目、产量、成本或财务事实改变，才修改冻结模型；单纯因为市场中位数更高或更低，不把独立结果硬凑到一致。

碳酸锂项目计算器将在行研重建验收后恢复为独立“工具”侧栏，完整还原Excel逐矿项目、权益年份和备注，并支持新增项目。当前估值全部来自冻结研究模型，不引用尚未完成的计算器界面，也不把试算方案伪装成正式目标价。

## 总结

估值分歧最终都可还原为价格、销量、资源覆盖、成本、非锂利润和现金转换。买卖点应绑定这些参数的变化，不能只绑定现货价格。
"""

    q5 = _front(
        industry_id=industry_id,
        name="碳酸锂",
        title="Q5 政策、贸易与库存",
        dynamic="进口、出口、本地加工与库存口径共同改变国内产品可用性。",
    ) + f"""
# Q5｜政策、贸易与库存

## 本章综述

**中国碳酸锂不是封闭市场。** 一季度进口快速增长说明海外盐湖可以缓冲国内缺口；资源国本地加工政策又会改变出口产品形态和成本。库存样本的定义则决定短期“去库”是否真实可交易。

## 问题

政策、贸易和库存怎样改变碳酸锂的年度平衡与价格传导？

## 证据与数据

工信部披露2026年一季度进口8.3万吨，同比增长64.6%。津巴布韦推动本地加工、智利强化国有参与、马里提高国家与本地权益，这些政策可能减少简单精矿出口，却增加当地锂盐或中间品供给。{miit} {_cite(source_ids, 'zimbabwe_export_202602', 'chile_maricunga_202602', 'mali_lithium_2026')}

| 变量 | 方向 | 进入模型的方式 | 不能做的推断 |
|---|---|---|---|
| 进口 | 缓冲国内缺口 | 国内可用供给加项 | 把一季度高增永续化 |
| 出口 | 减少国内可用量 | 国内可用供给减项 | 忽略产品品类与转口 |
| 本地加工 | 改变精矿/中间品形态 | 调整项目投产、成本和产品 | 把原矿处理量直接折LCE |
| 库存 | 延缓或放大价格传导 | 方向与持续时间验证 | 跨样本相加或把扩容当累库 |

## 研究与分析

进口能否持续取决于海外项目、国内外价差和贸易条件。资源国限制精矿出口并不一定减少全球锂供给，可能只是延迟项目并改变产品形态；但对中国加工企业而言，会提高海外资本开支和原料采购不确定性。

库存需要区分可交割、可销售和被锁定库存。期货仓单下降不一定等于全社会去库，工厂库存增加也不一定可立即流通。只有不同样本方向一致并持续多个周期，才上调缺口的价格影响。

资源国政策还会改变进口产品形态。精矿出口限制可能促使当地建设锂盐或中间品工厂，短期延迟供给并提高资本开支，长期却可能增加可直接进口的化学品。对国内加工企业而言，原料供应可能减少；对拥有海外一体化项目的企业而言，项目壁垒可能提高，但上市公司能否获得现金还取决于权益和分红。

国内产业政策主要通过环保、能耗、安全和项目审批影响边际供给。锂云母的尾渣和能源、盐湖的水资源与生态、回收的原料合规，都会让名义产能与可持续产量不同。研究不把一次停产简单年化，也不把复产公告直接视为满产，而是观察连续产量和库存。

贸易与库存之间还存在重复计算风险。进口货物可能仍在保税区、港口或贸易商手中，尚未形成下游可用供给；同一批货又可能进入某些社会库存样本。年度模型以海关口径记录进口，但价格分析只在货物进入可交易库存后提高权重，从而避免同一数量同时解释供给和库存。

对公司财务而言，政策和库存的传导必须落到具体变量：进口增加会压低产品价格或原料溢价，出口限制会提高海外项目资本开支，环保检修会减少销量，库存重估会影响毛利与现金流。只有能够指出传导路径，政策事件才进入估值。

政策判断还需要主动寻找反方。出口限制可能延期供给，也可能推动当地加工后增加化学品出口；国有参与可能降低民营权益，也可能改善许可和基础设施；环保约束可能减少高成本供给，也可能被技术改造消化。模型只在时间、数量或权益得到证据支持时调整，不把方向性新闻直接变成利润。

没有量化证据的政策线索只进入风险监控，不进入基准产量、利润、自由现金流和估值。

## 总结

政策和贸易决定国内缺口能否被外部供给填补，库存决定缺口何时转成价格。两者都必须独立验证，不能被一个年度平衡数字替代。
"""

    q6 = _front(
        industry_id=industry_id,
        name="碳酸锂",
        title="Q6 综合判断",
        dynamic="紧平衡需要库存验证，股票收益取决于公司资源与现金流。",
    ) + f"""
# Q6｜综合判断

## 本章综述

**碳酸锂基准是接近平衡、库存决定斜率、公司分化决定回报。** 年度中值不能单独为价格提供方向，必须看实际产量、进口、库存和需求是否向同一方向偏离；资源型与加工型公司的利润传导不同，估值也不能只看PE。

## 问题

怎样把产品平衡、价格、公司盈利和估值组成一个可执行判断？

## 证据与数据

{_balance_table(carbonate, carbonate=True)}

{_valuation_table(companies, recon_by_name)}

{company_filings} {association} {h1_market}

## 研究与分析

行业上行确认需要三项同时发生：月度供给低于基准、库存持续下降、动力与储能需求不弱。若进口和国内产量超预期、库存重新上升，年度小缺口可以被完全覆盖。价格观点应随三项证据调整。

公司层面，低成本权益资源企业对价格上行的利润弹性更直接；外购矿加工企业需要价差扩大而非产品价格单独上涨；多元企业还要判断钾肥、特钢、民爆、铁矿或地产的贡献。当前市值如果已隐含高于基准的锂价和项目爬坡，价格上涨也未必带来超额收益。

## 总结

行业价格偏强也不等于所有锂股都便宜。优先选择资源覆盖、成本和现金流能被季度数据验证、且当前市值未提前计入上行情景的公司；若产量和进口持续高于基准并重新累库，应先下调价格路径。
"""

    q7 = _front(
        industry_id=industry_id,
        name="碳酸锂",
        title="Q7 计算器、监控与边界",
        dynamic="把价格、产量、库存和公司模型变成可复算的持续研究工具。",
    ) + f"""
# Q7｜计算器、监控与资料边界

## 本章综述

**计算器用于测试假设，不用于制造目标价；研究结论仍以冻结模型和已核验证据为准。** Excel中的逐矿项目、权益年份、备注以及原“汇总”和“Sheet1”的计算链已经恢复到独立工具页，并改成更容易理解的名称。研究员可以新增或停用项目、调整各年权益产量和成本，所有公司汇总、利润与估值结果都由当前项目记录动态重算。

## 问题

如何使用模型与计算器，怎样避免错误输入产生伪精确结果？

## 证据与数据

| 模式 | 适用场景 | 最小输入 | 输出 |
|---|---|---|---|
| 简化模式 | 快速测试锂价和公司整体弹性 | 价格、总销量、资源覆盖、成本、其他利润 | 终值利润、隐含PE、目标市值与股价 |
| 项目明细模式 | 资源与加工项目差异较大 | 每个项目销量、权益、成本、处理利润 | 项目合计利润与敏感性 |

## 建模方法

计算器的资源利润按“销量×权益或资源覆盖×（价格－成本）÷1.13×税后因子”计算，加工利润按加工销量×单位加工利润计算，再加非锂利润并扣公司层成本。目标市值等于终值利润×目标PE，目标股价按当前股本换算。简化模式缺少逐项目债务、少数股东和现金分配，不适合替代详细矿山NAV。

## 研究与分析

最常见的错误是把原矿处理能力填成LCE销量、把项目100%产量填成归母销量、把含税价格与不含税成本相减，或者给亏损公司套正PE。计算器对单位给出显式标签，但研究员仍需核对产品形态与权益。

数据更新顺序为：月度产品平衡和库存，季度公司产量与现金流，半年需求与项目重估。任何输入修改都应留下理由并与公司公告或公开模型对应；无法核验的参数只用于压力测试。

一个合格的方案需要同时保存三类信息：原始输入、修改理由和结果差异。例如把2027碳酸锂价格从14万元/吨改为12万元/吨，还要说明是因为供给高于基准、库存重新累积还是需求下修；若只是为了让目标价接近市场，则不应保存为研究方案。项目明细模式还要分别记录100%产量和公司权益，不能用“权益产量”标签隐藏二者。

简化模式适合快速判断价格敏感性，但它把同一公司的不同项目、税区、少数股东与资本开支压缩为总销量、资源覆盖和税后因子。详细模式能够拆项目，却仍缺少完整资产负债表、债务期限和少数股东现金分配。两种模式都不能替代正式DCF或矿山NAV，只能作为利润与倍数的条件化比较。

计算结果需要进行三项反算：一万吨产品乘一万元/吨等于一亿元；项目利润乘权益后才能进入归母；目标市值除以股本才得到股价。若结果与公司规模相差一个数量级，应先检查单位、含税/不含税和股本，而不是调整倍数。亏损或净资产为负时，相关PE或PB方法自动失去解释力。

后续保存和导出功能只影响研究员自己的试算方案，不会修改正式研究与公司财务数据。要把方案升级为正式研究输入，必须经过来源核验、模型冻结、外部对账和审查；这条边界避免试算方案污染公司详情页的动态数据。

完成后的计算器默认方案与正式模型使用同一截点，但二者职责不同：正式模型可审计、冻结并进入公司页，计算器方案可随时删除、复制和比较。若后续财报或项目公告改变事实，先更新正式底稿，再更新计算器默认值；不能让个人浏览器方案反向覆盖公共研究结论。

独立工具页保留了Excel原“汇总”和“Sheet1”的主要计算链，分别展示为“公司资源、利润与估值总览”和“公司资源增长与终局估值比较”。逐矿权益、投产年份、各年产量、成本和备注均作为可新增、可停用的项目记录；汇总只从当前项目记录自动计算，不另存一套可能与明细失配的冻结数字。原表2024年资源基数仅作为可辨识的历史参照，不参与覆盖研究员当前输入。

## 总结

计算器的价值是把分歧还原为参数。结论必须说明哪个输入改变、为什么改变、结果如何变化，不能只展示一个目标价。
"""

    company_doc = _front(
        industry_id=industry_id,
        name="碳酸锂",
        title="碳酸锂行业公司透视",
        dynamic="13家公司按资源、路线、产品与非锂利润拆分。",
    ) + f"""
# 碳酸锂行业公司透视

> **结论。** 13家公司均已建立独立财务模型并接入公司详情页。资源、加工、盐湖、锂云母和项目期权不能用同一个产能倍数估值；计算器将在行研验收后作为独立工具恢复，不影响本页结论。

## 问题

13家公司怎样把碳酸锂价格、资源权益、加工结构、项目时间和非锂业务转成不同的利润、现金和估值；哪些公司已经拥有可验证的产量，哪些仍主要是远期项目期权？

## 研究方法与数据

本页先核对2025实际产量、资源与权益，再冻结2026—2028公司特定销量、资源覆盖、成本、加工利润、非锂利润和现金转换；Wind一致预期及最近两个季度机构预测只在独立模型冻结后用于对账。供应商动态快照继续保存在独立财务库，不复制为本页研究事实。

{_company_project_table(companies, source_ids)}

## 研究与分析

以下逐家公司给出经营事实、三年情景、外部预测、估值和验证条件。碳酸锂只是公共价格输入，企业的资源权益、加工结构和非锂业务分别建模。

{_deep_company_dossiers(companies, recon_by_name, source_ids)}

### 盈利与外部对账

{_company_model_table(companies, recon_by_name)}

{_broker_reconciliation_table(companies, recon_by_name)}

## 总结

公司页的PE/PB Band、PB—ROE/PB—ROA、独立模型、市场隐含预期和交易观察读取独立财务库；本页只解释碳酸锂业务如何传导，不复制动态供应商数据。
"""

    valuation_doc = _front(
        industry_id=industry_id,
        name="碳酸锂",
        title="碳酸锂行业估值对比",
        dynamic="价格—销量—成本模型与市场隐含预期对账。",
    ) + f"""
# 碳酸锂行业估值对比

## 问题

怎样在13家公司经营结构和数据完整度不同的情况下，分别计算可复核的2026—2028盈利与估值，并判断当前市值已经计入多高的锂价、项目爬坡和可持续ROE？

## 研究方法与数据

模型先按公司项目与三条价格路径计算2026—2028利润，再执行正常化PE、PB—ROE和FCFE门禁。结果不机械平均；当前市场用反向PE解释已经计入的锂价与项目预期。公司公告用于实际经营与权益，冻结模型用于独立预测，Wind一致预期和最近两个季度机构预测用于外部对账。

{_valuation_table(companies, recon_by_name)}

### 各公司上下限参数、公式与依据

{_valuation_parameter_table(companies)}

{company_filings} {reports}

### 建模方法与实际代入

公司利润先按同一公式桥计算，但每家公司的销量、资源覆盖、资源成本、加工利润、非锂利润与公司层成本独立冻结。三条含税碳酸锂等价价格为10/9/9、15/14/13、18/17/16万元/吨；这里的等价价格不代表氢氧化锂、精矿或长协都按现货结算，而是通过公司特定的覆盖率、成本和加工利润映射。

正常化PE使用2027基准利润，成熟低成本资源使用相对更高的区间，外购加工和单项目公司降低倍数，亏损公司关闭PE。PB—ROE按公司特定的可持续ROE范围、股权成本和长期增长率直接得到PB，不再对结果机械加减；PB—ROA用于判断ROE是否被杠杆放大。股权自由现金流（FCFE）按三年利润和公司特定现金转换形成比较值，再用Ke/g上下限折现；由于逐年资本开支与营运资金不全，终值占比高时不作为核心。

## 研究与分析

### 三情景财务结果

{_scenario_financial_table(companies, recon_by_name)}

情景表显示的是经营范围而非概率。资源覆盖高的公司在价格—成本差扩大时利润弹性更强；加工型公司更依赖价差和库存；有钾肥、铁矿、特钢或民爆的公司下行时有利润底仓；远期项目公司可能在基准期仍亏损，不能用资源量直接替代利润。

### 当前市场隐含预期

{_market_expectation_table(companies, recon_by_name)}

独立FY1/FY2隐含PE用当前市值除以本研究利润，供应商前瞻PE则使用市场一致利润。两者差异正是需要解释的预期差。若当前市值高于核心方法上沿，市场可能计入更高锂价、更快爬坡或尚未入模的资产；若低于核心方法下沿，还必须核验是否存在模型遗漏、现金流问题或长期成本上移，不能自动解释为低估。

### 与市场和最近两个季度机构预测对账

{_broker_reconciliation_table(companies, recon_by_name)}

机构样本保留报告日期与机构名称，同一机构同一年度只取最近一份，英文机构与中文机构同级。对账发生在独立模型冻结之后；只有补查发现新的项目、产量、成本或财务事实时才修改模型，否则保留差异。赣锋、天齐、天华与大中低于市场的差异，需要分别用项目爬坡、资源覆盖和非锂利润验证；中矿高于市场的差异，需要Bikita产量和成本共同证明。

### 方法分歧与投资判断

资源型公司PB—ROE可帮助检查资产回报能否覆盖资本成本，但高锂价ROE必须折价；加工型公司PB解释力较弱，应以正常化利润和现金流为主；项目型公司在量产前缺少稳定利润，估值上限只能当条件情景。

估值差异应还原为价格、销量、资源覆盖、成本、非锂利润和现金转换。公司详情页给出这些输入、与Wind和近期机构预测的差异，以及当前市值相对核心方法区间的位置。

三种估值方法不平均。PE高于PB—ROE，可能是利润假设强但可持续资产回报不足；PE高于FCFE，可能是项目资本开支和营运资金吞噬现金；PB高于PE，可能是当前利润处在周期底部。研究选择能解释公司经济机器的方法作为核心，把其他方法作为诊断，并在结果分歧时追查经营原因。

买点需要同时满足经营和定价两条线：项目、成本或现金流相对冻结模型上修，而市场仍按旧利润定价。卖点则是价格、项目或现金流下修已经发生，当前估值仍要求旧基准。现货上涨但外购矿和资本开支同步增加，并不必然改善自由现金流；现货回落但低成本销量增长，也不必然破坏长期价值。

完整逐矿NAV理论上适用于资源资产，但需要逐矿储量、品位、回收率、采序、建设与维持资本、税制、权益和闭矿责任。13家公司公开深度不一致，本研究不拿Excel模板假设填满这些缺口。后续碳酸锂工具负责逐项目情景试算，正式估值仍必须经过证据核验、模型冻结和外部对账。

## 总结

当前价格是否便宜取决于市场已经隐含什么，而不是历史PE分位本身。只有项目和现金流上修、而市场仍按旧基准定价时，才形成更强的买点。
"""

    return {
        "碳酸锂.md": main,
        "碳酸锂_Q0_历史发展.md": q0,
        "碳酸锂_Q1_竞争格局.md": q1,
        "碳酸锂_Q2_市场空间.md": q2,
        "碳酸锂_Q3_公司壁垒.md": q3,
        "碳酸锂_Q4_行业特征.md": q4,
        "碳酸锂_Q5_资源政治.md": q5,
        "碳酸锂_Q6_综述.md": q6,
        "碳酸锂_Q7_补充.md": q7,
        "碳酸锂_公司透视.md": company_doc,
        "碳酸锂_估值对比.md": valuation_doc,
    }


def make_documents(
    industry: str,
    industry_id: int,
    source_ids: dict[str, int],
) -> dict[str, str]:
    models = _load(MODEL_PATH)
    recon = _load(RECON_PATH)
    if industry == "锂":
        from .lithium_industry_rewrite import make_lithium_rewrite

        legacy_documents = _lithium_documents(
            industry_id,
            source_ids,
            models,
            recon,
            _load(LITHIUM_SD_PATH),
        )
        legacy_documents.update(
            make_lithium_rewrite(
                industry_id,
                source_ids,
                models,
                _load(LITHIUM_SD_PATH),
            )
        )
        return _with_source_indexes(
            legacy_documents,
            source_ids,
        )
    if industry == "碳酸锂":
        from .carbonate_industry_rewrite import make_carbonate_rewrite

        legacy_documents = _carbonate_documents(
            industry_id,
            source_ids,
            models,
            recon,
            _load(CARBONATE_SD_PATH),
        )
        legacy_documents.update(
            make_carbonate_rewrite(
                industry_id,
                source_ids,
                models,
                _load(CARBONATE_SD_PATH),
            )
        )
        return _with_source_indexes(
            legacy_documents,
            source_ids,
        )
    raise ValueError(f"unsupported industry: {industry}")
