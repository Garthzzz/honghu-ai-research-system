"""比亚迪/立讯高速光模块专题的公开报告组合层。

本模块只负责把已经核验的证据、模型输出和财务快照写成人能直接阅读的研究报告。
计算底稿、审计字段和完整结构化记录仍保留在 run pack 与模型产物中，不在这里展开。
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_HALF_UP
from textwrap import dedent
from typing import Any, Iterable


PUBLIC_FORBIDDEN_FRAGMENTS = (
    "本节结论状态与专属边界",
    "决策含义",
    "下一次更新",
    "最低可证含义",
    "不可推出",
    "破坏程度",
    "[未知]",
    "本节专属缺口",
    "canonical",
    "intake",
    "字段完成度",
    "字段完成情况",
    "输出覆盖卡",
    "完成矩阵",
    "参数 owner",
    "参数owner",
    "本轮代理",
    "D0/D1/D2",
    "A—F",
    "P/H/C",
    "low/mode/high",
    "P10",
    "P90",
    "Wilson",
    "Fréchet",
    "专家压力带",
    "决策验证债",
    "受影响参数",
    "概率加权signed",
    "zero-floor",
)


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _body(value: str) -> str:
    # f-string 中动态插入的 Markdown 表格行可能从第 0 列开始，标准 dedent
    # 会因此保留其余正文缩进并把表格误渲染成代码块。这里移除正文中最小的
    # 正缩进，同时保持已经位于第 0 列的动态行不变。
    lines = value.strip("\n").splitlines()
    positive_indents = [
        len(line) - len(line.lstrip())
        for line in lines
        if line.strip() and len(line) != len(line.lstrip())
    ]
    margin = min(positive_indents) if positive_indents else 0
    cleaned = [
        line[margin:].rstrip() if margin and line[:margin].isspace() else line.rstrip()
        for line in lines
    ]
    return "\n".join(cleaned).strip()


def _cite(ref: str) -> str:
    return f"^src:source_ref:{ref} "


def _source_uri(ref: str) -> str:
    return f"source_ref:{ref}"


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean(value)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _valid_refs(
    body_markdown: str,
    refs: Iterable[str],
    source_lookup: dict[str, dict[str, Any]],
) -> list[str]:
    inline = re.findall(r"\^src:source_ref:([A-Za-z0-9_.-]+)", body_markdown)
    result = [ref for ref in _unique([*refs, *inline]) if ref in source_lookup]
    if not result:
        raise ValueError("公开章节没有可解析的证据引用")
    return result


def _section(
    *,
    key: str,
    title: str,
    body_markdown: str,
    refs: Iterable[str],
    source_lookup: dict[str, dict[str, Any]],
    sort_order: int,
) -> dict[str, Any]:
    body_markdown = _body(body_markdown)
    valid_refs = _valid_refs(body_markdown, refs, source_lookup)
    return {
        "section_key": key,
        "section_title": title,
        "body_markdown": body_markdown,
        "support_status": "partially_supported",
        "evidence_ref_uri_list": [_source_uri(ref) for ref in valid_refs],
        "sort_order": sort_order,
    }


def _probability(model: dict[str, Any], horizon: str, metric: str) -> float:
    value = model["probability"]["horizons"][horizon]["marginal_probability"][metric]
    if isinstance(value, dict):
        value = value.get("mean", value.get("median", 0.0))
    return float(value)


def _probability_range(
    model: dict[str, Any], company_key: str, horizon: str
) -> tuple[float, float, float]:
    bridge = model.get("probability", {}).get("prior_update_bridge", {})
    company = bridge.get("company_updates", {}).get(company_key, {})
    triangle = company.get("posterior", {}).get(horizon, {}).get("triangle")
    if isinstance(triangle, list) and len(triangle) == 3:
        return tuple(float(value) for value in triangle)  # type: ignore[return-value]
    fallbacks = {
        ("byd", "3y"): (0.06, 0.12, 0.22),
        ("byd", "5y"): (0.18, 0.30, 0.45),
        ("luxshare", "3y"): (0.32, 0.45, 0.60),
        ("luxshare", "5y"): (0.50, 0.66, 0.80),
    }
    return fallbacks[(company_key, horizon)]


def _pct(value: Any, digits: int = 0) -> str:
    number = float(value) * 100.0
    return f"{number:.{digits}f}%"


def _number(value: Any, digits: int = 0) -> str:
    number = float(value)
    return f"{number:,.{digits}f}"


def _usd_to_cny(financial: dict[str, Any]) -> float:
    value = float(financial.get("fx_to_cny", {}).get("USD") or 0.0)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("财务快照缺少有效的USD/CNY换算汇率")
    return value


def _cny_yi_dual(
    value: Any,
    usd_to_cny: float,
    *,
    cny_digits: int = 2,
    usd_digits: int = 2,
) -> str:
    """以报告统一口径同时显示亿元人民币和约合亿美元。"""

    amount = float(value)
    return (
        f"{_number(amount, cny_digits)}亿元人民币"
        f"（约{_number(amount / usd_to_cny, usd_digits)}亿美元）"
    )


def _cny_yi_table_value(value: Any, usd_to_cny: float, digits: int = 2) -> str:
    """表头已写明单位时，以“人民币（美元）”紧凑显示。"""

    amount = float(value)
    return f"{_number(amount, digits)}（{_number(amount / usd_to_cny, 2)}）"


def _ports_million_cn(value: Any) -> str:
    """把模型的“百万个端口”转换成自然中文数量。"""
    million = float(value)
    if million >= 100:
        return f"{million / 100:.2f}".rstrip("0").rstrip(".") + "亿个"
    return f"{million * 100:,.0f}万个"


def _usd_bn_cn(value: Any) -> str:
    """把模型的十亿美元转换成中文报告使用的亿美元。"""
    amount = (Decimal(str(value)) * Decimal("10")).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )
    return f"{amount:,.1f}亿美元"


def _model_market_row(model: dict[str, Any], year: int) -> dict[str, Any]:
    rows = model.get("market", {}).get("rows", [])
    return next(row for row in rows if int(row["year"]) == year)


def _financial_company(financial: dict[str, Any], key: str) -> dict[str, Any]:
    return financial.get("companies", {}).get(key, {})


def _annual_financial_row(
    financial: dict[str, Any], company_key: str, year: int
) -> dict[str, Any]:
    company = _financial_company(financial, company_key)
    periods = company.get("financial_series", {}).get("periods", [])
    return next(row for row in periods if str(row.get("period")) == str(year))


def _annual_fcf(
    financial: dict[str, Any], company_key: str, year: int
) -> float:
    rows = _financial_company(financial, company_key).get("fcf_proxy", [])
    row = next(item for item in rows if str(item.get("period")) == str(year))
    return float(row["fcf_proxy_cny_yi"])


def _historical_sequence(
    financial: dict[str, Any], company_key: str, field: str, usd_to_cny: float
) -> str:
    values: list[float] = []
    for year in (2023, 2024, 2025):
        row = _annual_financial_row(financial, company_key, year)
        payload = row[field]
        values.append(float(payload.get("cny_yi") if isinstance(payload, dict) else payload))
    return " → ".join(_cny_yi_table_value(value, usd_to_cny) for value in values)


def _historical_fcf_sequence(
    financial: dict[str, Any], company_key: str, usd_to_cny: float
) -> str:
    return " → ".join(
        _cny_yi_table_value(
            _annual_fcf(financial, company_key, year), usd_to_cny
        )
        for year in (2023, 2024, 2025)
    )


def _baseline_2031(company: dict[str, Any]) -> dict[str, Any]:
    rows = company.get("cross_state_rows", {}).get("A|P", [])
    if rows:
        return next(row for row in rows if int(row["year"]) == 2031)
    baseline = company.get("baseline", {})
    if isinstance(baseline, dict):
        row = baseline.get("2031") or baseline.get(2031)
        if row:
            return {
                **row,
                "net_income_cny_yi": float(row["revenue_cny_yi"])
                * float(row["net_margin_pct"])
                / 100.0,
                "fcf_cny_yi": float(row["revenue_cny_yi"])
                * float(row["fcf_margin_pct"])
                / 100.0,
            }
    raise ValueError("财务模型缺少2031年对照情景")


def _cross_state_2031(company: dict[str, Any], key: str) -> dict[str, Any]:
    rows = company.get("cross_state_rows", {}).get(key, [])
    return next(row for row in rows if int(row["year"]) == 2031)


def _weighted_2031(company: dict[str, Any]) -> dict[str, Any]:
    return next(
        row
        for row in company.get("probability_weighted_rows", [])
        if int(row["year"]) == 2031
    )


def _baseline_revenue_range_2031(company: dict[str, Any]) -> tuple[float, float, float]:
    paths = company["baseline_revenue_sensitivity"]
    return tuple(float(paths[key][-1]) for key in ("low", "base", "high"))


def _loss_text(value: float, baseline: float, usd_to_cny: float) -> str:
    loss = (1.0 - value / max(abs(baseline), 1e-12)) * 100.0
    amount = _cny_yi_dual(
        value, usd_to_cny, cny_digits=0, usd_digits=2
    )
    if abs(loss) < 0.05:
        return f"{amount}（对照值）"
    return f"{amount}（较对照低{loss:.0f}%）"


def _financial_cell(
    row: dict[str, Any], baseline: dict[str, Any], usd_to_cny: float
) -> str:
    revenue = _loss_text(
        float(row["revenue_cny_yi"]),
        float(baseline["revenue_cny_yi"]),
        usd_to_cny,
    )
    profit = _loss_text(
        float(row["net_income_cny_yi"]),
        float(baseline["net_income_cny_yi"]),
        usd_to_cny,
    )
    fcf = float(row["fcf_cny_yi"])
    fcf_text = (
        _cny_yi_dual(fcf, usd_to_cny, cny_digits=0, usd_digits=2)
        if fcf < 0
        else _loss_text(fcf, float(baseline["fcf_cny_yi"]), usd_to_cny)
    )
    return f"收入：{revenue}<br>净利润：{profit}<br>现金流：{fcf_text}"


def _financial_assumption_cell(row: dict[str, Any]) -> str:
    """把模型参数翻译成读者可以直接核查的经营假设。"""

    def parameter_pct(value: Any) -> str:
        return f"{float(value):.2f}".rstrip("0").rstrip(".")

    parts = [
        f"份额下降{parameter_pct(row['exposed_segment_share_loss_pct'])}%；"
        f"同规格额外降价{parameter_pct(row['exposed_segment_extra_asp_pressure_pct'])}%；"
        f"毛利率下降{parameter_pct(row['gross_margin_shock_ppt'])}个百分点"
    ]
    fixed_cost_drag = float(row["fixed_cost_drag_ppt"])
    if fixed_cost_drag > 0:
        parts.append(f"固定成本使净利率再降{parameter_pct(fixed_cost_drag)}个百分点")
    parts.append(
        f"防守性扩产与营运资本新增占受影响收入"
        f"{parameter_pct(row['expansion_capex_pct_revenue'])}%和"
        f"{parameter_pct(row['working_capital_change_pct_revenue'])}%"
    )
    return "；".join(parts)


def _financial_extra_cash(row: dict[str, Any]) -> float:
    return float(row["expansion_capex_cny_yi"]) + float(
        row["working_capital_change_cny_yi"]
    )


def _exposure_elasticity(model: dict[str, Any], company_key: str) -> dict[str, float]:
    """返回受影响收入占比每增加10个百分点时的2031年线性损失。"""

    company = model["financial"]["exposure_sensitivity"]["cases"][
        "exposure_100pct"
    ]["companies"][company_key]
    return {
        "revenue_pct": float(company["2031_revenue_loss_pct"]) / 10.0,
        "profit_pct": float(company["2031_net_income_loss_pct"]) / 10.0,
        "fcf_pct": float(company["2031_actual_fcf_loss_pct"]) / 10.0,
        "revenue_cny_yi": (
            float(company["2031_baseline_revenue_cny_yi"])
            - float(company["2031_weighted_revenue_cny_yi"])
        )
        / 10.0,
        "profit_cny_yi": (
            float(company["2031_baseline_net_income_cny_yi"])
            - float(company["2031_weighted_net_income_cny_yi"])
        )
        / 10.0,
        "fcf_cny_yi": (
            float(company["2031_baseline_actual_fcf_cny_yi"])
            - float(company["2031_weighted_actual_fcf_cny_yi"])
        )
        / 10.0,
    }


def build_human_report_sections(
    *,
    model: dict[str, Any],
    sources: list[dict[str, Any]],
    financial: dict[str, Any],
    as_of_date: str,
) -> list[dict[str, Any]]:
    """生成公开主章节；所有生产审计字段留在 run pack 内部。"""

    lookup = {source["ref"]: source for source in sources}
    usd_to_cny = _usd_to_cny(financial)
    probabilities = {
        "byd3": _probability(model, "3y", "byd_meaningful_entry"),
        "byd5": _probability(model, "5y", "byd_meaningful_entry"),
        "lux3": _probability(model, "3y", "luxshare_meaningful_entry"),
        "lux5": _probability(model, "5y", "luxshare_meaningful_entry"),
        "any3": _probability(model, "3y", "at_least_one_entry"),
        "any5": _probability(model, "5y", "at_least_one_entry"),
        "global3": _probability(model, "3y", "at_least_one_global_entry"),
        "global5": _probability(model, "5y", "at_least_one_global_entry"),
        "both3": _probability(model, "3y", "both_entry"),
        "both5": _probability(model, "5y", "both_entry"),
        "both_global3": _probability(model, "3y", "both_global_entry"),
        "both_global5": _probability(model, "5y", "both_global_entry"),
        "byd_china3": _probability(model, "3y", "byd_china_entry"),
        "byd_china5": _probability(model, "5y", "byd_china_entry"),
        "lux_china3": _probability(model, "3y", "luxshare_china_entry"),
        "lux_china5": _probability(model, "5y", "luxshare_china_entry"),
        "byd_global3": _probability(model, "3y", "byd_global_entry"),
        "byd_global5": _probability(model, "5y", "byd_global_entry"),
        "lux_global3": _probability(model, "3y", "luxshare_global_entry"),
        "lux_global5": _probability(model, "5y", "luxshare_global_entry"),
        "china_only3": _probability(model, "3y", "china_only_system_entry"),
        "china_only5": _probability(model, "5y", "china_only_system_entry"),
    }
    probability_horizons = model["probability"]["horizons"]
    competition_severity = {
        horizon: {
            level: float(
                probability_horizons[horizon][
                    "conditional_deterioration_probability"
                ]["conditional_on_at_least_one_entry"][level]["mean"]
            )
            for level in ("mild", "material", "severe")
        }
        for horizon in ("3y", "5y")
    }
    long_term_damage = probability_horizons["5y"][
        "financial_threshold_deterioration"
    ]["long_term_significant_damage"]
    market_2026 = _model_market_row(model, 2026)
    market_2029 = _model_market_row(model, 2029)
    market_2031 = _model_market_row(model, 2031)
    market_cases = model.get("market", {}).get("sensitivity_cases", {})
    market_demand_slow_2031 = market_cases.get("demand_slow_supply_base", {}).get("rows", [{}])[-1]
    market_demand_fast_2031 = market_cases.get("demand_fast_supply_base", {}).get("rows", [{}])[-1]
    market_supply_slow_2031 = market_cases.get("supply_slow_demand_base", {}).get("rows", [{}])[-1]
    market_supply_fast_2031 = market_cases.get("supply_fast_demand_base", {}).get("rows", [{}])[-1]
    probability_cases = model.get("probability_sensitivity", {}).get("cases", {})
    dependence_any = {
        horizon: [
            float(probability_cases[case]["horizons"][horizon]["at_least_one_entry"])
            for case in ("negative_dependence", "independent_events", "high_positive_dependence")
        ]
        for horizon in ("3y", "5y")
    }
    threshold_any = {
        case: {
            horizon: float(
                probability_cases[case]["horizons"][horizon][
                    "at_least_one_entry"
                ]
            )
            for horizon in ("3y", "5y")
        }
        for case in ("loose_entry_threshold", "strict_entry_threshold")
    }
    qualification_delay_any = {
        horizon: float(
            probability_cases["qualification_delay"]["horizons"][horizon][
                "at_least_one_entry"
            ]
        )
        for horizon in ("3y", "5y")
    }
    inno_model = model["financial"]["companies"]["innolight"]
    eopt_model = model["financial"]["companies"]["eoptolink"]
    architecture_weights = model["financial"]["architecture_probability"]
    inno_base = _baseline_2031(inno_model)
    eopt_base = _baseline_2031(eopt_model)
    inno_weighted = _weighted_2031(inno_model)
    eopt_weighted = _weighted_2031(eopt_model)
    inno_after_entry = inno_model["conditional_on_at_least_one_entry_2031"]
    eopt_after_entry = eopt_model["conditional_on_at_least_one_entry_2031"]
    inno_revenue_range = _baseline_revenue_range_2031(inno_model)
    eopt_revenue_range = _baseline_revenue_range_2031(eopt_model)
    inno_exposure_elasticity = _exposure_elasticity(model, "innolight")
    eopt_exposure_elasticity = _exposure_elasticity(model, "eoptolink")
    exposure_cases = model["financial"]["exposure_sensitivity"]["cases"]
    inno_exposure_cases = {
        share: exposure_cases[f"exposure_{share}pct"]["companies"]["innolight"]
        for share in (50, 75, 100)
    }
    eopt_exposure_cases = {
        share: exposure_cases[f"exposure_{share}pct"]["companies"]["eoptolink"]
        for share in (50, 75, 100)
    }

    sections: list[dict[str, Any]] = []
    sections.append(
        _section(
            key="summary",
            title="摘要",
            refs=(
                "BYD-S01",
                "BYD-LEAD-FIRSTSH-20250901",
                "BYD-LEAD-CMBI-20250902",
                "BYD-LEAD-CINDA-20250905",
                "BYD-PAT-CN122362593A",
                "LX-OPTICS-CURRENT",
                "LX-TRANSCEIVER-CURRENT",
                "LX-IR-202508",
                "SRC-INNO-AR25",
                "SRC-EOPT-AR25",
                "MODEL-WORKPAPER",
            ),
            source_lookup=lookup,
            sort_order=10,
            body_markdown=f"""
            截至 {as_of_date}，最重要的判断不是“比亚迪和立讯会不会做光模块”，而是它们能否在未来三至五年跨过客户认证、重复交付和规模盈利三道门槛。立讯已经公开10G至1.6T产品，发行人还披露800G量产和1.6T客户验证，因此它是需要进入龙头估值讨论的真实潜在进入者；但公司关于头部客户的不同披露尚未完全一致，可分光模块收入、合格产线良率和跨代重复订单也没有公开闭环。{_cite('LX-OPTICS-CURRENT')}{_cite('LX-TRANSCEIVER-CURRENT')}{_cite('LX-IR-202508')}{_cite('LX-IR-20260507')}

            三家具名券商在2025年中期业绩会后都记录了800G和1.6T路线：共同的保守口径是800G进入量产准备或具备量产能力、正在客户推广，1.6T处于优化测试或量产准备；其中信达国际还记录了2025年内月出货5万只的目标及CPO研发计划。这些相近口径大概率来自同一次未公开的管理层交流，因此只能确认多家券商在当时记录了同一条产品路线线索，不能确认发行人已正式披露，也不能确认目标已兑现。公司2025年年报只明确披露服务器、液冷、电源和高速互联，没有确认光模块客户、实际出货、良率、专线或收入。所以，这组线索只提高后续核验优先级并扩大上行情形，不作为已形成产品、客户或量产事实的直接证据，更不能写成已向英伟达或海外云客户批量交付。{_cite('BYD-LEAD-FIRSTSH-20250901')}{_cite('BYD-LEAD-CMBI-20250902')}{_cite('BYD-LEAD-CINDA-20250905')}{_cite('BYD-S01')}

            按本报告对“有意义进入”的严格定义，用于财务测算的代表值是：比亚迪约三年{_pct(probabilities['byd3'])}、五年{_pct(probabilities['byd5'])}；立讯约三年{_pct(probabilities['lux3'])}、五年{_pct(probabilities['lux5'])}。至少一家形成有意义进入约三年{_pct(probabilities['any3'])}、五年{_pct(probabilities['any5'])}，但至少一家进入全球头部客户体系只有约三年{_pct(probabilities['global3'])}、五年{_pct(probabilities['global5'])}。这些数值来自公司证据约束下的较宽估算范围，不是历史成功率；历史案例的进入方式和观察终点不一致，不能用一个小样本比例替代公司分析。{_cite('MODEL-WORKPAPER')}

            对中际旭创和新易盛，当前风险不是“新玩家出现就必然失去长期利润”。两家公司2025年收入、净利润和简单自由现金流均处在明显扩张阶段，多代产品、量产良率、客户共同开发和海外交付仍是有效防线；与此同时，前五大客户收入占比均超过70%，2026年7月17日快照的市盈率分别约73倍和63倍，市场价格已经要求高增长继续兑现。真正会改变盈利中枢的组合是：新进入者取得全球头部客户资格，连续两个采购周期形成重复订单，同规格产品出现额外降价，同时龙头毛利率和现金流连续恶化。{_cite('SRC-INNO-AR25')}{_cite('SRC-EOPT-AR25')}{_cite('FIN-INNOLIGHT')}{_cite('FIN-EOPTOLINK')}

            财务模型把客户份额、同规格额外降价、良率与固定成本压力、扩产支出和营运资本分别传导到收入、净利润和现金流。公开资料尚不能把两家公司总收入准确拆成800G以上高速产品与其他业务，因此“全部收入都受影响”的结果只能作为压力上限，不能直接当目标价。加入逐年进入概率后，2031年在这一压力口径下，中际旭创的加权收入约为{_cny_yi_dual(inno_weighted['revenue_cny_yi'], usd_to_cny, cny_digits=0)}、净利润约{_cny_yi_dual(inno_weighted['net_income_cny_yi'], usd_to_cny, cny_digits=0)}、情景现金流约{_cny_yi_dual(inno_weighted['fcf_cny_yi'], usd_to_cny, cny_digits=0)}；新易盛分别约为{_cny_yi_dual(eopt_weighted['revenue_cny_yi'], usd_to_cny, cny_digits=0)}、{_cny_yi_dual(eopt_weighted['net_income_cny_yi'], usd_to_cny, cny_digits=0)}和{_cny_yi_dual(eopt_weighted['fcf_cny_yi'], usd_to_cny, cny_digits=0)}。

            这里的参考路径冻结了本模型新增的竞争和架构冲击，但2026—2027年起点来自市场聚合预期，可能已经包含部分已知竞争影响，不能理解成纯粹的“没有竞争”反事实。相对这一路径，现金流损失大于收入损失，说明扩产与营运资本假设会放大结果，也说明这些输入必须进一步补证。{_cite('MODEL-WORKPAPER')}

            ### 本节结论

            根据现有证据，可以认为立讯已进入需要持续跟踪的商业化前段；比亚迪存在多家券商共同归因于一次管理层交流的产品路线线索，但仍缺发行人原文、客户和规模经营闭环。三年内更现实的路径是立讯先在中国或区域客户形成第二供应，同时继续核验券商所述比亚迪产品与客户目标是否兑现；五年风险显著上升，但是否伤害龙头长期价值，仍取决于客户、价格、份额、毛利和现金流是否连续同向恶化。本报告不能据此给出无条件买卖结论，也不能把压力测试当股权公允价值。

            ### 如果想进一步研究，需要补充

            最优先需要三类原始信息：立讯和比亚迪逐产品的客户准入与两期以上订单；中际旭创、新易盛按速率、客户和地区拆分的收入与毛利；同客户、同距离、同形态产品的成交价和良率。补齐这三类信息后，才能把进入概率、实际受影响收入比例和现金流冲击从宽范围收敛到可用于估值的判断。
            """,
        )
    )

    sections.append(
        _section(
            key="research_definition",
            title="我们怎样判断一家新进入者真正形成了竞争",
            refs=(
                "LX-IR-202508",
                "BYD-LEAD-CINDA-20250905",
                "BYD-S01",
                "SRC-CISCO-ACACIA21",
                "SRC-INTEL-Q323",
                "SRC-FN-10K24",
                "MODEL-WORKPAPER",
            ),
            source_lookup=lookup,
            sort_order=20,
            body_markdown=f"""
            本报告要回答的是，比亚迪电子或立讯精密能否在2029年和2031年前成为足以影响高速光模块竞争格局的供应商。展示样机、出现在合作伙伴演示、拥有相关专利或获得一次小批订单都不是终点；只有产品、客户、重复交付和经营规模同时成立，才记为“有意义进入”。经营规模要求年化相关收入达到{_cny_yi_dual(10, usd_to_cny, cny_digits=0)}、全球市场份额达到1%或中国市场份额达到5%三项中的至少一项，并且已经覆盖两个客户，或在同一客户完成跨代产品延续。这个定义比“公司涉足光通信”严格，因为投资者真正关心的是它会不会改变中际旭创、新易盛的份额、价格和现金回报。

            | 判断环节 | 本报告要求看到的证据 | 为什么这一环节不能被前一环节替代 |
            |---|---|---|
            | 可销售产品 | 经营主体可归属的800G以上数据中心模块、规格和可靠性记录 | 服务器、铜缆或车载光学能力不等于高速模块产品 |
            | 客户准入 | 大型客户或平台正式认证、合格供应名录或设计导入 | 伙伴互操作只证明工程兼容，不证明客户采购 |
            | 重复批量 | 至少两个采购或披露周期的持续交付，最好覆盖多客户或跨代产品 | 一次送样和一次小批量无法证明良率与需求可持续 |
            | 经营影响 | 可售产能、良率、收入或份额达到能影响行业价格的规模 | 集团制造规模不能代替光模块业务自身经济性 |

            中国客户体系和全球头部云客户分别判断。两条路径可能重叠，也可能出现客户地域没有公开的订单，所以中国与全球概率不能简单相加。全球路径门槛更高，不仅要看到发行人说“国际客户”，还要有客户侧或平台侧准入、重复订单以及商业规模的交叉印证。立讯在产品和发行人披露上已经跨过前两段的一部分，但公开材料仍无法确认其全球头部客户闭环；比亚迪有管理层产品路线的具名转述，却还没有经营主体可归属的原始规格、客户和规模交付闭环。{_cite('LX-IR-202508')}{_cite('NVIDIA-CX8-VALIDATED')}{_cite('BYD-LEAD-CINDA-20250905')}{_cite('BYD-S01')}

            新进入者对龙头盈利的影响按结果而不是抽象标签判断。若新增供应只是有限的第二来源、需求仍能吸收产能，且龙头同规格价格、毛利和现金流没有持续恶化，就视为可以吸收的竞争扰动；若全球客户份额和同规格价格同时下降，并连续压低利润与现金流，就视为盈利中枢受到实质压力；只有多客户、多代产品和大规模低价供货持续发生，龙头又不能通过新产品、降本或新架构抵消，才构成长期结构性风险。后文所有财务情景都按这组可观察结果解释。

            历史案例只用于理解路径，不用于制造一个看似精确的成功率。Cisco收购Acacia和Lumentum收购Cloud Light时，同时获得了成熟产品、团队和客户基础；Intel内部孵化的可插拔模块后来选择剥离；Fabrinet长期成功于专业光学制造，却不能据此被视为自有完整模块平台。收购成熟平台、内部从零建设、承接产品族和专业代工面对的起点不同，放在同一个二元样本中会混淆问题。{_cite('SRC-CISCO-ACACIA21')}{_cite('SRC-LITE-CLOUD23')}{_cite('SRC-INTEL-Q323')}{_cite('SRC-FN-10K24')}

            分析时先把事实按里程碑归位，再看证据之间是相互支持还是冲突。产品目录与独立互操作可以共同提高工程成熟度判断；发行人“量产”与后续“业务仍处起步阶段”的表述发生冲突，就应扩大判断范围，而不是选择更乐观的一句；公开未见客户名称不能证明客户不存在，但会限制我们把项目写成已经规模化。这个处理方式既避免把保密项目机械记为零，也避免用匿名传闻填满缺口。

            ### 本节结论

            根据这一口径，立讯是“产品和部分商业化已得到支持、全球头部客户与经营规模仍需闭环”；比亚迪是“管理层交流的二手记录支持产品工程化和客户推广，客户资格、重复交付与规模经营仍未得到直接证据”。这一差异决定了立讯的三年判断仍高于比亚迪，也决定了任何新证据必须只更新它真正证明的环节，不能因为一条新闻同时上调产品、客户、产能和收入。

            ### 如果想进一步研究，需要补充

            需要建立按同一口径记录的客户阶段时间线：送样日期、认证通过日期、首批交付、第二个采购周期、可售产能、良率和收入。若能取得客户或平台侧文件，应优先于发行人宣传；若受保密协议限制，至少需要可核验的订单持续性、产线爬坡和分部收入交叉证明。
            """,
        )
    )

    sections.append(
        _section(
            key="byd_assessment",
            title="比亚迪电子离高速光模块商业化还有多远",
            refs=("BYD-S01", "BYD-S02", "BYD-S04", "BYD-S06", "BYD-S11", "BYD-S14", "BYD-S16", "BYD-S17", "BYD-S18", "BYD-LEAD-FIRSTSH-20250901", "BYD-LEAD-CMBI-20250902", "BYD-LEAD-CINDA-20250905", "BYD-LEAD-IDCE-2026", "BYD-LEAD-TGB-20260718", "BYD-PAT-CN122052920A", "BYD-PAT-CN122362593A", "BYD-PAT-CN121012567A"),
            source_lookup=lookup,
            sort_order=30,
            body_markdown=f"""
            比亚迪电子最值得研究的地方，是它已经进入AI数据中心，而且多家具名券商曾将具体光模块路线归因于同一次管理层交流。2025年年报披露，公司形成服务器、液冷、电源和高速互联的一体化方案，AI基础设施收入约{_cny_yi_dual(9.43, usd_to_cny)}，服务器出货增长，液冷通过客户认证并进入小规模试产。这些事实说明比亚迪电子拥有真实的数据中心客户入口、资金、采购和大规模制造基础，但不能由此确认高速光模块产品或交付。{_cite('BYD-S01')}{_cite('BYD-S04')}

            第一上海、招银国际和信达国际在2025年9月分别记录了同一次中期业绩会后的公司路线。三份材料的共同部分是：800G处于量产准备、具备量产能力或客户推广阶段，1.6T处于优化测试或量产准备；信达还记录了2025年内月出货5万只目标和CPO研发计划。三份报告的措辞并不完全一致，所以报告采用较保守的共同含义，不把“具备能力”改写成“已经批量出货”，也不把“月出货目标”改写成已建成合格产能。它们来自同一次管理层交流，只计一个底层信息源。{_cite('BYD-LEAD-FIRSTSH-20250901')}{_cite('BYD-LEAD-CMBI-20250902')}{_cite('BYD-LEAD-CINDA-20250905')}

            这些信息足以确认市场说法有具名且更早的出处，并提高核验优先级，但不能确认发行人已正式披露，更不能确认产品工程阶段。2025年年报没有拆出模块收入、专线设备、良率、客户或重复订单；NVIDIA公开兼容清单和IDCE公开材料也没有证明比亚迪电子光模块资格或800G展品。2026年市场文章增加的海外云客户、NVIDIA批量交付和1.6T验证完成等细节，仍未找到原始材料确认，只作为高关注线索保留。{_cite('BYD-S01')}{_cite('BYD-S18')}{_cite('BYD-LEAD-IDCE-2026')}{_cite('BYD-LEAD-TGB-20260718')}

            专利证据也比单一“单纤双向”更系统。连续申请覆盖车载硅光网络、收发架构、光混频接收、故障检测、模块封装和热设计；CN122362593A甚至涉及多类光源、探测器、COB/BOSA和2.5D/3D封装。但申请主体分属比亚迪股份和济南比亚迪半导体，全文仍以车辆为场景，没有800G、1.6T、数据中心形态或客户信息。它提高的是集团技术迁移能力，不是比亚迪电子当前的客户或量产阶段。{_cite('BYD-S14')}{_cite('BYD-PAT-CN122052920A')}{_cite('BYD-PAT-CN122362593A')}{_cite('BYD-PAT-CN121012567A')}

            主体边界也很重要。比亚迪电子是本报告判断数据中心业务和潜在模块经营影响的直接主体，比亚迪股份通过控股关系间接暴露于其经营结果；母公司的功率半导体、资本开支或汽车客户不能自动算成比亚迪电子光模块能力。公开披露可以确认控制与并表关系，却不能确认尚未公开的联合团队、技术转移或客户项目。{_cite('BYD-S02')}

            ### 估算方法

            估算方法是按照产品、客户认证、重复订单、专用产能和可分收入五类证据，分别设定保守值、最可能值和上限；财务模型需要单一输入时，用三者平均数作为代表值。多家券商共同归因于一次管理层交流的转述只扩大上行情形，不改变最可能值或保守值；系统性车载光通信专利使长期技术迁移的最可能值小幅上调；发行人仍无正式产品规格、客户资格、专线、良率或重复收入证据。三年代表值约{_pct(probabilities['byd3'])}，估算范围为{_pct(_probability_range(model, 'byd', '3y')[0])}至{_pct(_probability_range(model, 'byd', '3y')[2])}；五年代表值约{_pct(probabilities['byd5'])}，范围为{_pct(_probability_range(model, 'byd', '5y')[0])}至{_pct(_probability_range(model, 'byd', '5y')[2])}。这些是证据约束下的工作判断，不是管理层目标的兑现概率，也不是历史统计频率。{_cite('MODEL-WORKPAPER')}

            对现有龙头而言，比亚迪三年内更可能先影响供应链预期和中国客户的第二来源选择，而不是直接夺取全球头部客户份额。管理层产品路线已足以进入工程风险观察，但不能直接下调龙头实际盈利；只有客户资格、重复订单、可售良率和收入同时出现，才把比亚迪的影响完整传导到份额与价格模型。

            反方情形也需要保留：比亚迪可能通过未公开项目、客户共同开发或收购比公开材料更快推进，保密安排会让当前判断低估真实阶段。这个可能性已经体现在较宽的五年范围中，但在客户、产线和收入没有交叉证据前，不能把它当作最可能的情形。相反，如果未来两年仍只有服务器和液冷进展而没有模块产品，三年进入判断应进一步下调。

            ### 本节结论

            根据现有证据，可以认为比亚迪电子已不只是数据中心相邻进入者：管理层交流的多份具名记录支持800G工程化与客户推广、1.6T测试或量产准备。但目前仍没有直接证据证明2025年目标已经转化为合格产能、客户资格、重复交付和可分收入。把它写成“已向英伟达或海外云客户批量交付”会超出证据，把它继续写成“没有800G/1.6T产品阶段信号”同样不准确。

            ### 如果想进一步研究，需要补充

            最关键的是取得比亚迪电子或明确子公司的产品规格、光模块岗位与团队归属、专用耦合和测试设备、客户送样与认证记录、两期订单、良率和可分收入。若公司选择收购或合资，还需要核验被收购平台是否连同客户和团队进入并表范围，而不是只获得一项器件或制造合同。
            """,
        )
    )

    sections.append(
        _section(
            key="luxshare_assessment",
            title="立讯的产品进度离全球头部客户还有多远",
            refs=(
                "LX-TRANSCEIVER-CURRENT",
                "LX-800G-LPO-SPEC",
                "LX-FRO-2026",
                "LX-IR-202508",
                "LX-ANNUAL-2024",
                "LX-IR-20260507",
                "OIF-OFC2026",
                "KEYSIGHT-LX-202410",
            ),
            source_lookup=lookup,
            sort_order=40,
            body_markdown=f"""
            本节要回答的是：立讯已有800G和1.6T产品之后，离全球头部客户的稳定、可扩、跨代订单还有多远。它与比亚迪的核心差异，是已经越过“有没有产品”这一层。立讯技术公开目录覆盖10G至1.6T，形态包括传统数字处理可插拔（DPO）、线性可插拔（LPO）和线性接收（LRO）等路线；800G规格、合作伙伴联合开发、测试设备记录和OIF互操作参与共同说明，公司拥有真实的光模块工程团队和生态接入。2025年8月投资者交流披露800G已量产、1.6T处于客户验证；截至2026年7月18日的网页快照，立讯技术官网当前页面另称1.6T进入早期商业化，但页面本身没有发布日期。这些证据足以把立讯从概念进入者提升为商业化前段的真实竞争者，同时不能把网页素材时间误写成正式披露日期。{_cite('LX-OPTICS-CURRENT')}{_cite('LX-TRANSCEIVER-CURRENT')}{_cite('LX-800G-LPO-SPEC')}{_cite('LX-IR-202508')}{_cite('LX-FRO-2026')}{_cite('OIF-OFC2026')}{_cite('KEYSIGHT-LX-202410')}

            | 关键进展 | 公开证据支持到哪一步 | 仍然影响判断的缺口 |
            |---|---|---|
            | 产品 | 已有800G与1.6T目录、规格和多种架构路线 | 逐代产品的真实出货结构没有拆分 |
            | 工程验证 | 有伙伴、测试和行业互操作记录 | 互操作不能代替客户正式准入 |
            | 商业交付 | 2025年8月公司称800G量产、1.6T客户验证；当前官网称1.6T进入早期商业化 | 官网页面未标发布日期，订单数量、良率、收入和利润也没有单列 |
            | 全球客户 | 2024年报提到国际头部客户测试与交付 | 后续披露又称主要面向中小数据中心，口径需闭环 |

            最重要的反方证据正是公司自身披露冲突。2024年年报曾提到头部AI客户测试和多家国际头部客户量产交付；2025年8月投资者交流又称800G和1.6T主要向中小型数据中心客户交付，尚未获得头部客户明确商务机会；2026年5月公司继续强调光连接业务仍处起步阶段。三条记录可能对应不同产品、地区、客户阶段或统计边界，也可能反映项目进度变化。公开资料不足以判断具体原因，因此最合理的处理不是选一句最乐观的话，而是承认立讯已经有产品和有限商业化，同时显著压低全球头部客户判断。{_cite('LX-ANNUAL-2024')}{_cite('LX-IR-202508')}{_cite('LX-IR-20260507')}

            立讯的三年有意义进入代表值约{_pct(probabilities['lux3'])}，估算范围为{_pct(_probability_range(model, 'luxshare', '3y')[0])}至{_pct(_probability_range(model, 'luxshare', '3y')[2])}；五年约{_pct(probabilities['lux5'])}，范围为{_pct(_probability_range(model, 'luxshare', '5y')[0])}至{_pct(_probability_range(model, 'luxshare', '5y')[2])}。总进入概率明显高于全球头部客户概率，说明近期更可能出现的是中国或区域客户规模，而不是直接复制中际旭创、新易盛在全球云客户中的地位。{_cite('MODEL-WORKPAPER')}

            立讯的大规模连接器制造、系统集成和客户协同提供了产能爬坡上限，但高速光模块的良率、返工、保修和光电器件采购约束与传统电子制造不同。集团资本开支和通信分部收入不能直接代替模块线经济性。若立讯通过低价进入区域客户，却未取得全球客户认证，行业影响更可能是局部报价和第二来源压力；若它取得客户侧准入并跨两代产品重复交付，才会把风险推进到全球份额与长期毛利。

            ### 本节结论

            根据现有证据，可以认为立讯已经是商业化前段的真实进入者，其产品和工程进度明显领先比亚迪；但目前没有足够的直接证据证明它已经在全球头部客户形成稳定、可扩、跨代的光模块份额。三年应重点跟踪区域规模与客户阶段，五年才需要把全球突破作为更实质的盈利风险。

            ### 如果想进一步研究，需要补充

            需要取得按客户层级和产品速率拆分的准入、订单和收入，解释2024年至2026年披露差异；同时需要专用模块线的产能、良率、返工率、保修成本和主要光电器件来源。客户侧合格供应名录、平台验证或连续采购记录的证明力高于发行人单次“量产”表述。
            """,
        )
    )

    sections.append(
        _section(
            key="commercialization_evidence",
            title="从产品到规模：人才、专利、产线和客户证据怎样相互印证",
            refs=(
                "BYD-S06",
                "BYD-S11",
                "BYD-S14",
                "BYD-S16",
                "BYD-LEAD-CINDA-20250905",
                "BYD-PAT-CN122052920A",
                "BYD-PAT-CN122362593A",
                "BYD-PAT-CN121012567A",
                "LX-TRANSCEIVER-CURRENT",
                "OIF-OFC2026",
                "NVIDIA-CX8-VALIDATED",
                "SRC-COHR-10K25",
            ),
            source_lookup=lookup,
            sort_order=50,
            body_markdown=f"""
            本节要回答的是，招聘、专利、互操作、工厂和上游采购分别能证明什么，以及它们在什么情况下才会共同指向商业规模。单独看任何一条都容易高估进展：招聘说明公司愿意配置能力，不说明团队已到位；专利说明技术覆盖，不说明数据中心产品已通过可靠性；互操作说明设备之间能工作，不说明客户会采购；通用智慧工厂说明自动化基础，不说明光学耦合线已经达到可售良率。

            | 证据维度 | 比亚迪电子 | 立讯精密 | 对当前判断的实际作用 |
            |---|---|---|---|
            | 人才与团队 | 集团招聘覆盖半导体和通信，模块团队归属未闭环 | 有耦合、测试等岗位与产品组织线索 | 只判断组织准备，不能代替量产 |
            | 产品工程 | 多家券商共同转述800G量产准备/能力、1.6T测试或量产准备，但缺发行人原文 | 有公开规格、产品路线与发行人交付口径 | 比亚迪的转述只作待核验线索；立讯的公开链条更完整 |
            | 专利与技术 | 有连续车载硅光、收发、封装、热管理专利簇 | 有完整产品路线与伙伴开发记录 | 两者都不能用专利代替数据中心客户资格 |
            | 制造 | 大规模自动化和精密装配能力明确 | 通信制造与系统集成基础明确 | 两者都缺公开的模块线良率与可售产能 |
            | 客户与平台 | 数据中心客户入口已成立，模块准入未见直接证据 | 有发行人交付口径，全球头部客户仍有冲突 | 这是两家公司概率差异最大的来源 |
            | 上游器件 | 集团采购规模可能有帮助，具体模块器件未披露 | 已进入工程生态，核心器件来源仍不完整 | DSP、激光器和PIC约束会限制爬坡速度 |

            比亚迪的证据链现在可以分成两条：车载专利和招聘证明集团技术与人才邻接；2025年业绩会的具名卖方转述则把比亚迪电子推进到800G产品工程化与客户推广信号。两条线仍没有在同一经营主体下与产品规格、客户资格、专用产线和收入连起来，因此不能把管理层目标写成已实现量产。立讯的证据链更长：产品、规格、合作伙伴、互操作与发行人交付表述彼此印证，足以证明工程活动和有限商业化；但NVIDIA公开清单中可见的是立讯200G铜缆，不是800G以上光模块准入。铜缆平台记录不能迁移成光模块客户资格。{_cite('BYD-LEAD-CINDA-20250905')}{_cite('BYD-S14')}{_cite('BYD-PAT-CN122362593A')}{_cite('LX-TRANSCEIVER-CURRENT')}{_cite('OIF-OFC2026')}{_cite('NVIDIA-CX8-VALIDATED')}

            上游约束会使“有产品”与“能规模交付”之间出现很长距离。高速模块依赖数字信号处理芯片（DSP）、激光器、光子集成芯片（PIC）、驱动与探测器，还要经过封装、耦合、烧机、可靠性和客户系统测试。Coherent披露部分投入存在有限或单一来源风险，说明即使总装厂具备采购规模，也不能假定关键器件随时可得。新进入者若以低价抢单，却没有稳定器件供应和良率，可能带来短期报价扰动而无法形成持续份额；反过来，客户出于供应安全主动扶持第二来源，也可能帮助其跨过早期爬坡。{_cite('SRC-COHR-10K25')}{_cite('SRC-MRVL-10Q25')}

            比较方法是把每类材料放回“团队准备—产品工程—客户认证—重复订单—经营规模”的顺序，并检查不同来源是否指向同一经营主体、产品和时点。只有相邻环节相互印证才推进阶段；任何单一前置信号都不直接进入收入和份额估算。

            客户证据必须放在整个链条的最后判断。伙伴联合演示可以证明工程接口，发行人“国际客户”可以证明业务接触，但只有客户侧准入、重复批量和收入才能证明经营结果。保密协议可能使公开资料低估真实进展，因而概率需要保留较宽范围；这并不构成用匿名传闻填补客户、产线或收入的理由。没有直接证据与项目不存在不是一回事，但在投资研究中，尚未闭环的阶段不能当成已经确认的商业进展。

            ### 本节结论

            根据现有证据，可以认为立讯已经形成“产品—工程—有限交付”的连续链条；比亚迪形成了“管理层产品路线—集团技术邻接—数据中心客户入口”的非完整链条。两家公司共同的关键缺口不是招聘数量，而是光模块线良率、核心器件保障、客户准入和重复收入。只有这些证据相互印证，进入风险才会从产品计划升级为持续竞争。

            ### 如果想进一步研究，需要补充

            需要把岗位、专利、设备、产品、客户和订单放到同一时间轴，并核验经营法人。最有价值的新材料包括模块线设备清单和良率、核心器件长期采购安排、客户可靠性报告、正式准入、连续订单和分部收入；招聘转载、同族专利和公司宣传页应先去重，不能按页面数量累积判断。
            """,
        )
    )

    sections.append(
        _section(
            key="market_outlook",
            title="2026—2031年高速光互联市场能否吸收新增供给",
            refs=("SRC-LC-MAR26", "SRC-CIGNAL-4Q24", "SRC-HKEX-ASP26", "SRC-OIF-2025", "MODEL-WORKPAPER"),
            source_lookup=lookup,
            sort_order=60,
            body_markdown=f"""
            新进入者会不会伤害龙头，首先取决于市场增长能否吸收新增合格供给。报告把800G、1.6T和3.2T数据中心高速互联分别估算，再汇总端口、正常代际价格和市场收入；“合格供给”只计通过工程与客户约束后可以交付的能力，不把名义厂房或设备数量直接当产能。LPO、LRO和CPO则作为价值链迁移情景单独估算，避免与速率需求重复相加。下表数值是外部预测、产品节奏和价格假设组合后的模型结果，不是任何一家外部机构直接发布的数字。{_cite('SRC-LC-MAR26')}{_cite('SRC-CIGNAL-4Q24')}{_cite('SRC-OIF-2025')}{_cite('MODEL-WORKPAPER')}

            | 年份 | 高速端口需求 | 市场收入 | 合格供给/需求 | LPO/LRO占比 | CPO占比 |
            |---:|---:|---:|---:|---:|---:|
            | 2026 | {_ports_million_cn(market_2026['total_ports_million'])} | {_usd_bn_cn(market_2026['normal_market_revenue_usd_bn'])} | {_number(market_2026['qualified_supply_demand_ratio'], 2)}倍 | {_number(market_2026['lpo_lro_share_pct'], 0)}% | {_number(market_2026['cpo_share_pct'], 0)}% |
            | 2029 | {_ports_million_cn(market_2029['total_ports_million'])} | {_usd_bn_cn(market_2029['normal_market_revenue_usd_bn'])} | {_number(market_2029['qualified_supply_demand_ratio'], 2)}倍 | {_number(market_2029['lpo_lro_share_pct'], 0)}% | {_number(market_2029['cpo_share_pct'], 0)}% |
            | 2031 | {_ports_million_cn(market_2031['total_ports_million'])} | {_usd_bn_cn(market_2031['normal_market_revenue_usd_bn'])} | {_number(market_2031['qualified_supply_demand_ratio'], 2)}倍 | {_number(market_2031['lpo_lro_share_pct'], 0)}% | {_number(market_2031['cpo_share_pct'], 0)}% |

            按表中的需求和价格假设，需求从2026年的约{_ports_million_cn(market_2026['total_ports_million'])}增至2031年的约{_ports_million_cn(market_2031['total_ports_million'])}，市场收入从约{_usd_bn_cn(market_2026['normal_market_revenue_usd_bn'])}增至{_usd_bn_cn(market_2031['normal_market_revenue_usd_bn'])}。端口增长快于收入，原因是800G逐步成熟降价，而1.6T和3.2T以更高单价接棒。海光芯正文件显示，800G以上产品平均售价从2024年的2,443元降至2025年的1,557元，并说明其中既有商业化早期的小批高价基数，也有竞争和大批量采购影响。这提醒我们，正常代际降价与新进入者带来的额外降价必须分开。{_cite('SRC-HKEX-ASP26')}

            合格供给/需求从2026年略低于1上升到2029年约{_number(market_2029['qualified_supply_demand_ratio'], 2)}倍、2031年约{_number(market_2031['qualified_supply_demand_ratio'], 2)}倍，意味着供给宽松风险主要在中后期出现。这个比率不是行业统计事实，而是公开预测、产品节奏和资格约束组合成的工作路径。若AI集群部署更快或1.6T/3.2T爬坡更慢，供给宽松会后移；若更多供应商通过认证、客户加快多供应商导入或需求下修，价格压力会提前。

            慢、中、快三条综合路径都会同时改变需求和供给，因此不能用它们证明“2031年必然过剩”。把两边拆开后，若合格供给维持中性路径，只改变需求，2031年供给/需求会从需求偏快时的约{_number(market_demand_fast_2031['qualified_supply_demand_ratio'], 2)}倍变到需求偏慢时的约{_number(market_demand_slow_2031['qualified_supply_demand_ratio'], 2)}倍；若需求维持中性路径，只改变供给爬坡，范围约为{_number(market_supply_slow_2031['qualified_supply_demand_ratio'], 2)}—{_number(market_supply_fast_2031['qualified_supply_demand_ratio'], 2)}倍。也就是说，强需求足以让市场接近平衡，供给宽松是中性判断而不是已经锁定的结论。

            架构迁移与新进入者并非简单叠加。线性可插拔和线性接收方案仍保留可插拔形态，可能让既有模块厂通过新设计继续捕获价值；共封装光学（CPO）或光引擎提高时，部分价值可能从传统模块转向交换芯片、光引擎和封装。新进入者也可能利用架构切换绕过旧产品学习曲线，但同样要面对更复杂的共同设计和客户验证。报告因而不把共封装光学份额直接算成龙头收入损失，而是观察龙头能否参与新价值链。

            还要警惕模型与公司口径错位。全球高速端口市场按产品速率计算，公司收入却可能包含电信、器件、不同距离产品和其他业务。两者不能直接相除来推导份额；若未来拿到逐速率收入，应先统一产品边界和汇率，再检查两家龙头受影响业务合计是否合理，不能让公司总收入无解释地超过对应市场。

            ### 本节结论

            根据现有数据，可以认为高速光互联需求到2031年仍有显著增长，新增进入者并不必然造成行业收入萎缩；真正的竞争拐点更可能出现在合格供给持续超过需求、客户完成第二来源认证且同规格额外降价同时发生时。市场增长能够吸收部分区域供给，但不能自动保护高估值龙头的份额、毛利和现金流。

            ### 如果想进一步研究，需要补充

            需要按速率、距离、形态和客户建立同口径的出货、成交价与合格供给数据，并将客户认证滞后显式放入年度路径。当前最缺的是可售而非名义产能、同规格成交价、1.6T与3.2T真实部署节奏，以及龙头在LPO、LRO、CPO和光引擎中的收入捕获比例。
            """,
        )
    )

    company_probability_rows = []
    for company_label, company_key, total_metric, china_metric, global_metric in (
        ("比亚迪电子", "byd", "byd_meaningful_entry", "byd_china_entry", "byd_global_entry"),
        ("立讯精密", "luxshare", "luxshare_meaningful_entry", "luxshare_china_entry", "luxshare_global_entry"),
    ):
        for horizon, label in (("3y", "3年"), ("5y", "5年")):
            center = _probability(model, horizon, total_metric)
            probability_range = _probability_range(model, company_key, horizon)
            company_probability_rows.append(
                f"| {company_label} | {label} | 约{_pct(center)}（估算范围{_pct(probability_range[0])}—{_pct(probability_range[2])}） | "
                f"约{_pct(_probability(model, horizon, china_metric))} | "
                f"约{_pct(_probability(model, horizon, global_metric))} |"
            )
    sections.append(
        _section(
            key="entry_probability",
            title="比亚迪和立讯未来三至五年形成有意义竞争的概率",
            refs=(
                "BYD-S01",
                "LX-TRANSCEIVER-CURRENT",
                "LX-IR-202508",
                "SRC-CISCO-ACACIA21",
                "SRC-INTEL-Q323",
                "MODEL-WORKPAPER",
            ),
            source_lookup=lookup,
            sort_order=70,
            body_markdown=f"""
            本节判断的是到2029年和2031年前，两家公司能否同时具备可销售高速模块、客户准入、重复批量和足以影响行业的经营规模。由于没有同一进入方式、同一事件定义和同一观察期限的历史样本，概率不是从案例成功次数直接推出来的。研究先根据产品、客户、订单、产能和收入证据，为每家公司设定一个保守值、一个最可能值和一个上限；财务模型需要单一输入时，使用三者的平均数。例如比亚迪三年采用{_pct(_probability_range(model, 'byd', '3y')[0])}、{_pct(_probability_range(model, 'byd', '3y')[1])}和{_pct(_probability_range(model, 'byd', '3y')[2])}三个判断，三者相加后除以3，代表值约{_pct(probabilities['byd3'])}。随机抽样只把这些估算范围传导到联合结果，不会把分析判断变成客观频率。{_cite('MODEL-WORKPAPER')}

            | 公司 | 期限 | 形成有意义进入 | 其中：中国客户体系 | 其中：全球头部客户 |
            |---|---|---:|---:|---:|
            {chr(10).join(company_probability_rows)}

            比亚迪三年中心值约{_pct(probabilities['byd3'])}，主要因为AI服务器、液冷和数据中心客户入口提高了跨界可行性，但产品、模块客户、专线和重复订单没有公开闭环；五年升至约{_pct(probabilities['byd5'])}，是因为更长时间允许自建、合作或收购。立讯三年约{_pct(probabilities['lux3'])}、五年约{_pct(probabilities['lux5'])}，其产品和工程证据更强，但全球头部客户披露冲突以及收入、良率不可分限制了上限。{_cite('BYD-S01')}{_cite('LX-TRANSCEIVER-CURRENT')}{_cite('LX-IR-202508')}{_cite('LX-IR-20260507')}

            中国和全球路径分别根据对应地区的客户证据独立判断，是总进入之下可以重叠的两条路径，不是把总概率机械拆成两块，也不能相加。总进入还可能包含客户地域未公开或其他地区的项目，因此地域数字比公司总概率更依赖保密信息。表中的估算范围用于呈现证据不确定性，不是统计置信区间；精确到个位百分点只用于财务情景传导，不代表证据本身有同等精度。

            两家公司共同受AI网络需求、DSP和激光器供给、客户多供应商策略及架构切换影响，所以联合计算允许它们同向变化。最简单的关系是“至少一家进入＝比亚迪进入＋立讯进入－两家同时进入”。基础结果如下：

            | 联合问题 | 3年 | 5年 |
            |---|---:|---:|
            | 至少一家形成有意义进入 | 约{_pct(probabilities['any3'])} | 约{_pct(probabilities['any5'])} |
            | 两家同时形成有意义进入 | 约{_pct(probabilities['both3'])} | 约{_pct(probabilities['both5'])} |
            | 至少一家进入全球头部客户 | 约{_pct(probabilities['global3'])} | 约{_pct(probabilities['global5'])} |
            | 两家同时进入全球头部客户 | 约{_pct(probabilities['both_global3'], 1)} | 约{_pct(probabilities['both_global5'])} |

            两家公司之间的关系没有可观察的历史系数，因此联合结果必须做假设检查。把“共同受益或共同受阻”与“彼此争夺同一客户和器件”设成不同强度后，至少一家进入的三年结果约在{_pct(min(dependence_any['3y']))}—{_pct(max(dependence_any['3y']))}之间，五年约在{_pct(min(dependence_any['5y']))}—{_pct(max(dependence_any['5y']))}之间。基础结果位于这个范围内；方向性结论仍是三年接近一半、五年约三分之二至五分之四，但不能把50%和72%理解成不受关系假设影响的精确答案。

            事件门槛和客户认证时点带来的摆幅更大。若把经营规模门槛放宽为年化收入{_cny_yi_dual(5, usd_to_cny, cny_digits=0)}、全球份额0.5%或中国份额3%，至少一家进入约为三年{_pct(threshold_any['loose_entry_threshold']['3y'])}、五年{_pct(threshold_any['loose_entry_threshold']['5y'])}；若提高到年化收入{_cny_yi_dual(20, usd_to_cny, cny_digits=0)}、全球份额2%或中国份额10%，则降至三年{_pct(threshold_any['strict_entry_threshold']['3y'])}、五年{_pct(threshold_any['strict_entry_threshold']['5y'])}。若客户认证和重复交付整体延后，三年结果进一步降至约{_pct(qualification_delay_any['3y'])}；五年仍约{_pct(qualification_delay_any['5y'])}，是因为该压力测试只假定项目延迟、没有假定终局能力永久消失。这说明定义和认证进度可以让三年判断变化十多个百分点，基础值只能作为当前研究口径下的代表结果。

            历史案例只改变对路径的理解：收购成熟产品与客户平台更容易缩短进入时间；内部孵化、产品承接和联合开发可能长期停留在未形成规模；专业制造和器件能力不能自动成为完整模块平台。这些案例解释了为什么比亚迪的收购路径会显著改变五年判断，也解释了为什么立讯已有产品却仍需客户和经营闭环。它们不能提供可直接套用的成功率。{_cite('SRC-CISCO-ACACIA21')}{_cite('SRC-LITE-CLOUD23')}{_cite('SRC-INTEL-Q323')}{_cite('SRC-FN-10K24')}

            进入以后究竟只是可吸收的竞争扰动，还是会实质压低龙头盈利，目前不能从历史样本得到可信频率。为了回答投资决策仍然需要的条件问题，下一节会把各进入路径按份额、额外降价、毛利和现金流冲击加权，给出温和、明显和严重三种结果；这只是在现有研究假设下比较风险层级，不是行业历史发生率。公开资料仍缺新进入者真实份额、同规格成交价和龙头受影响收入比例，因此模型结果必须与具体财务阈值和业务暴露上限一起阅读。

            ### 本节结论

            根据现有证据，可以认为三年内最值得防范的是立讯先形成区域或中国客户规模；两家公司同时突破全球头部客户仍是低概率事件。五年内至少一家进入的可能性已高到不能忽略，但它只说明竞争者跨过经营门槛，不等于龙头利润必然恶化。客户资格、重复订单和实际价格冲击仍需在财务章节单独传导。

            ### 如果想进一步研究，需要补充

            若要收窄这些范围，需要建立同口径的历史跨界样本，并取得两家公司逐产品的客户阶段、重复订单、产线良率和收入。每条新证据只应改变对应公司、期限和地域；只有客户侧准入与持续订单出现，才应显著上调全球头部客户判断。
            """,
        )
    )

    scenario_specs = (
        ("冻结本模型新增冲击的参考路径", "A|P"),
        ("只有立讯形成有意义规模，尚未进入全球头部客户体系", "B|P"),
        ("只有一家进入全球头部客户，传统可插拔仍占主导", "E|P"),
        ("两家均进入全球客户，同时发生显著架构迁移", "F|C"),
    )
    scenario_lines = []
    for label, key in scenario_specs:
        inno_row = _cross_state_2031(inno_model, key)
        eopt_row = _cross_state_2031(eopt_model, key)
        note = {
            "A|P": "起点来自市场聚合预期，可能已含部分竞争影响，不是公司指引或纯无竞争反事实",
            "B|P": "更可能先体现为局部份额和现金回报压力",
            "E|P": "客户突破与额外降价同时发生后，现金流损失放大",
            "F|C": "多项不利条件同发的尾部压力，不是当前中心预测",
        }[key]
        scenario_lines.append(
            f"| {label} | {_financial_cell(inno_row, inno_base, usd_to_cny)} | "
            f"{_financial_cell(eopt_row, eopt_base, usd_to_cny)} | {note} |"
        )
    assumption_specs = (
        (
            "立讯先在区域或中国客户形成规模",
            "B|P",
            "只有立讯跨过经营规模门槛，尚未证实进入全球头部客户；传统可插拔模块仍占主导。",
        ),
        (
            "一家进入全球头部客户",
            "E|P",
            "只有一家新进入者取得全球头部客户并形成重复交付；传统可插拔模块仍占主导。",
        ),
        (
            "两家进入全球客户且架构显著迁移",
            "F|C",
            "两家均在全球客户形成规模，同时线性驱动或共封装光学等新架构明显替代传统可插拔模块。",
        ),
    )
    assumption_lines = []
    for label, key, event in assumption_specs:
        inno_row = _cross_state_2031(inno_model, key)
        eopt_row = _cross_state_2031(eopt_model, key)
        assumption_lines.append(
            f"| {label} | {event} | "
            f"中际旭创：{_financial_assumption_cell(inno_row)}<br>"
            f"新易盛：{_financial_assumption_cell(eopt_row)} | "
            f"中际旭创约{_cny_yi_dual(_financial_extra_cash(inno_row), usd_to_cny)}；"
            f"新易盛约{_cny_yi_dual(_financial_extra_cash(eopt_row), usd_to_cny)} |"
        )
    inno_market = _financial_company(financial, "innolight").get("market_snapshot", {})
    eopt_market = _financial_company(financial, "eoptolink").get("market_snapshot", {})
    inno_2025 = _annual_financial_row(financial, "innolight", 2025)
    eopt_2025 = _annual_financial_row(financial, "eoptolink", 2025)
    sections.append(
        _section(
            key="financial_impact",
            title="新进入者会怎样影响中际旭创和新易盛的盈利",
            refs=("SRC-INNO-AR25", "SRC-EOPT-AR25", "FIN-INNOLIGHT", "FIN-EOPTOLINK", "MODEL-WORKPAPER"),
            source_lookup=lookup,
            sort_order=80,
            body_markdown=f"""
            真正需要回答的不是龙头会不会少卖一点，而是新增供应是否同时压低客户份额、同规格售价和现金回报，并把短期压力变成长期能力受损。两家公司当前都处于盈利快速扩张阶段：中际旭创2025年收入{_cny_yi_dual(382.40, usd_to_cny)}、归母净利润{_cny_yi_dual(107.97, usd_to_cny)}、简单自由现金流{_cny_yi_dual(81.36, usd_to_cny)}；新易盛分别为{_cny_yi_dual(248.42, usd_to_cny)}、{_cny_yi_dual(95.32, usd_to_cny)}和{_cny_yi_dual(63.81, usd_to_cny)}。简单自由现金流只按经营现金流减购建长期资产支出计算，不等同于完整企业自由现金流。{_cite('SRC-INNO-AR25')}{_cite('SRC-EOPT-AR25')}

            表内主数值单位为亿元人民币，括号内为按1美元={usd_to_cny:.4f}元人民币换算的约合亿美元；市场估值为2026年7月17日快照。

            | 公司 | 收入（2023→2024→2025） | 归母净利润（2023→2024→2025） | 简单自由现金流（2023→2024→2025） | 2025年核心光产品毛利率 | 当前估值 |
            |---|---|---|---|---:|---|
            | 中际旭创 | {_historical_sequence(financial, 'innolight', 'revenue', usd_to_cny)} | {_historical_sequence(financial, 'innolight', 'net_income', usd_to_cny)} | {_historical_fcf_sequence(financial, 'innolight', usd_to_cny)} | 光通信收发模块42.61% | 市值{_cny_yi_dual(inno_market['market_cap_cny'], usd_to_cny, cny_digits=0)}；市盈率{float(inno_market['pe_ttm']):.2f}倍；市净率{float(inno_market['pb']):.2f}倍；市销率{float(inno_market['ps_ttm']):.2f}倍 |
            | 新易盛 | {_historical_sequence(financial, 'eoptolink', 'revenue', usd_to_cny)} | {_historical_sequence(financial, 'eoptolink', 'net_income', usd_to_cny)} | {_historical_fcf_sequence(financial, 'eoptolink', usd_to_cny)} | 光互联产品47.81% | 市值{_cny_yi_dual(eopt_market['market_cap_cny'], usd_to_cny, cny_digits=0)}；市盈率{float(eopt_market['pe_ttm']):.2f}倍；市净率{float(eopt_market['pb']):.2f}倍；市销率{float(eopt_market['ps_ttm']):.2f}倍 |

            历史数据揭示两种相反力量。多代产品、客户共同开发、海外交付和正现金流给龙头留下研发、扩产与降本空间；但两家公司前五大客户收入占比均超过70%，单一大客户引入第二供应商时，份额、价格和营运资本会同时受压。当前估值也不低，投资者已经在为未来高增长和高利润买单，因此即使绝对收入继续增长，增速和现金回报低于预期也会影响估值。{_cite('SRC-INNO-AR25')}{_cite('SRC-EOPT-AR25')}{_cite('FIN-INNOLIGHT')}{_cite('FIN-EOPTOLINK')}

            模型先建立冻结本模型新增竞争和架构冲击的参考路径，再加入客户份额流失、同规格额外降价、良率与固定成本压力，以及防守性扩产和营运资本占用。参考路径的2026—2027年起点来自分析师聚合预期，可能已经包含市场对既有竞争或架构变化的部分判断，因此它不是可用于因果解释的纯无竞争反事实；模型只计算在这一路径之上新增的压力。对照路径中的毛利率、净利率和正常化现金流率是基于历史水平设置的递减假设，不是公司指引：中际旭创从2026年的44% / 29% / 18%逐步降至2031年的39% / 24% / 14%，新易盛从47% / 37% / 22%降至38% / 25% / 13%。

            年度结果使用当年的进入概率，不把2031年的终局风险提前施加到2027年。概率加权沿用上一节的公司进入判断；架构情景约按{float(architecture_weights['P']):.0%}传统可插拔、{float(architecture_weights['H']):.0%}显著LPO/LRO迁移和{float(architecture_weights['C']):.0%}CPO增量风险加权。这些是研究情景的发生权重，不是市场份额统计；目前没有数据校准新进入者成功与架构迁移是否同时发生，基础计算暂按两者独立，同时发生的情况另作为尾部压力展示。

            所有比例先作用于金额，再由加权毛利额和净利润反算利润率。最核心的收入关系是：情景总收入等于不受本风险影响的收入，加上受影响高速产品收入乘以“1减份额损失”，再乘以“1减额外降价”。净利润的计算先把毛利率下降的72%传导到净利率，再加上固定成本对净利率的额外拖累；72%是为了压力测算设置的专家假设，不是公司披露，取得分业务费用率后必须重估。现金流在正常化现金流基础上，再扣除防守性扩产和新增营运资本。{_cite('MODEL-WORKPAPER')}

            模型中的未来份额、额外降价、利润率和现金占用不是公司披露的预测，而是根据进入阶段与架构变化设置的压力假设。为了让结果可以复核，下表直接列出三个关键情景在2031年的输入；“下降”均相对冻结新增冲击的参考路径。百分比作用于受影响收入；由于分产品收入尚不可得，表中绝对现金投入按“全部公司收入均受影响”的压力上限计算，不是一般情景估计。防守性扩产和营运资本只用于计算现金流，不重复扣减利润。在“立讯先形成区域规模”这一行，扩产与营运资本比例恰好相同，是因为缺少分业务现金转化数据，模型暂时把两项设为同一档共同压力参数；这不是两笔独立估计得到了相同答案，更不表示真实资本开支与营运资本必然相等。{_cite('MODEL-WORKPAPER')}

            | 2031年情景 | 假设发生了什么 | 两家公司的关键经营假设 | 额外现金投入 |
            |---|---|---|---|
            {chr(10).join(assumption_lines)}

            当前公开资料无法给出两家公司按800G、1.6T、3.2T和其他业务拆分的未来收入，所以下一张表暂时把公司总收入视为受影响收入，目的只是观察最坏情况下的传导方向。这个口径明显宽于800G以上市场边界，属于压力上限，不能当作中心预测或目标价。每个单元格依次是2031年收入、净利润和情景现金流；括号是相对参考路径的降幅。表中选四条代表路径帮助读者理解传导，后面的年度概率加权结果还纳入其他可能的公司进入与架构组合，并不是对这四行直接取平均。{_cite('MODEL-WORKPAPER')}

            | 2031年情景 | 中际旭创：收入 / 净利润 / 现金流 | 新易盛：收入 / 净利润 / 现金流 | 解释 |
            |---|---|---|---|
            {chr(10).join(scenario_lines)}

            在年度概率传导后的压力上限中，中际旭创2031年收入、净利润和现金流相对对照路径分别约低{(1-float(inno_weighted['revenue_cny_yi'])/float(inno_base['revenue_cny_yi']))*100:.1f}%、{(1-float(inno_weighted['net_income_cny_yi'])/float(inno_base['net_income_cny_yi']))*100:.1f}%和{(1-float(inno_weighted['fcf_cny_yi'])/float(inno_base['fcf_cny_yi']))*100:.1f}%；新易盛分别约低{(1-float(eopt_weighted['revenue_cny_yi'])/float(eopt_base['revenue_cny_yi']))*100:.1f}%、{(1-float(eopt_weighted['net_income_cny_yi'])/float(eopt_base['net_income_cny_yi']))*100:.1f}%和{(1-float(eopt_weighted['fcf_cny_yi'])/float(eopt_base['fcf_cny_yi']))*100:.1f}%。现金流降幅大于收入，首先来自收入与利润率受压，防守性扩产和营运资本又进一步放大损失；后两项在2031年全收入受压的测算中约占现金流损失四成。这些输入目前证据较弱，结果只能用于比较方向和量级。

            这里有一个必须正视的数量边界：2031年两家公司参考路径收入合计约{_cny_yi_dual(4900, usd_to_cny, cny_digits=0)}，而同年全球800G以上市场估算约253亿美元。两者的产品、速率和地区口径并不相同，说明公司总收入绝不能被解释成对应高速市场收入。与其用任意档位制造虚假的现实范围，更有用的是给出一个可复算的线性敏感度：在当前压力模型中，受影响收入占公司总收入每增加10个百分点，中际旭创2031年收入、净利润和现金流相对参考路径分别再下降约{inno_exposure_elasticity['revenue_pct']:.2f}、{inno_exposure_elasticity['profit_pct']:.2f}和{inno_exposure_elasticity['fcf_pct']:.2f}个百分点，对应约{_cny_yi_dual(inno_exposure_elasticity['revenue_cny_yi'], usd_to_cny)}、{_cny_yi_dual(inno_exposure_elasticity['profit_cny_yi'], usd_to_cny)}和{_cny_yi_dual(inno_exposure_elasticity['fcf_cny_yi'], usd_to_cny)}；新易盛分别约下降{eopt_exposure_elasticity['revenue_pct']:.2f}、{eopt_exposure_elasticity['profit_pct']:.2f}和{eopt_exposure_elasticity['fcf_pct']:.2f}个百分点，对应约{_cny_yi_dual(eopt_exposure_elasticity['revenue_cny_yi'], usd_to_cny)}、{_cny_yi_dual(eopt_exposure_elasticity['profit_cny_yi'], usd_to_cny)}和{_cny_yi_dual(eopt_exposure_elasticity['fcf_cny_yi'], usd_to_cny)}。这是模型对业务暴露假设的敏感度，不是公司真实业务占比；实际占比仍需分产品收入补证。

            对未来增长速度的假设同样重要。当前参考路径把2026至2027年分析师聚合预测继续外推，要求中际旭创和新易盛2025至2031年收入年均增长约43%和37%。在低增长、参考和高增长三条外推路径下，中际旭创2031年收入约为{_cny_yi_dual(inno_revenue_range[0], usd_to_cny, cny_digits=0)}、{_cny_yi_dual(inno_revenue_range[1], usd_to_cny, cny_digits=0)}和{_cny_yi_dual(inno_revenue_range[2], usd_to_cny, cny_digits=0)}，新易盛约为{_cny_yi_dual(eopt_revenue_range[0], usd_to_cny, cny_digits=0)}、{_cny_yi_dual(eopt_revenue_range[1], usd_to_cny, cny_digits=0)}和{_cny_yi_dual(eopt_revenue_range[2], usd_to_cny, cny_digits=0)}；这些是分析师近端聚合预期加显式递减增速得到的范围，不是公司指引。低增长与高增长结果接近三倍，说明模型的绝对经营价值首先受AI网络需求和龙头自身增长影响，其次才是新进入者额外造成多少损失。终值还假定2031年的防守性扩产和营运资本占用从2032年起立即回到正常水平，这可能偏乐观；如果客户切换、库存或应收压力延续，正常化现金流和终值都应下调。正常化现金流为负的极端情景不使用永续增长估值，而应另行研究重组、融资或退出。

            ### 本节结论

            根据现有证据，可以认为立讯已经足以让竞争风险进入盈利与估值讨论，但当前模型的绝对损失仍是全收入暴露的压力上限，不是中心预测。若新进入者只在区域客户形成有限供给，龙头可能用市场增长和产品升级吸收部分压力；若全球客户准入、重复订单、额外降价与现金流恶化同时出现，盈利损失会明显大于收入损失。由于当前估值不低且股权价值桥尚未完整，本研究不能据此给目标价或无条件买卖结论。

            ### 如果想进一步研究，需要补充

            需要按速率、客户、地区和产品形态拆分龙头收入与毛利，取得同规格成交价、客户份额和重复订单；同时补充分业务扩产支出、存货、应收账款、净现金或净债务、少数股东权益、非经营资产和稀释股本。只有这些输入闭环后，才能把压力上限改成可用于股权估值的中心情景。
            """,
        )
    )

    sections.append(
        _section(
            key="valuation_interpretation",
            title="当前估值是否已经补偿远期竞争风险",
            refs=("FIN-INNOLIGHT", "FIN-EOPTOLINK", "SRC-INNO-AR25", "SRC-EOPT-AR25", "SRC-LC-MAR26"),
            source_lookup=lookup,
            sort_order=90,
            body_markdown=f"""
            “竞争风险存在”与“当前价格已经过高”不是同一个命题。2026年7月17日，中际旭创市值约{_cny_yi_dual(inno_market['market_cap_cny'], usd_to_cny, cny_digits=0)}，市盈率约{float(inno_market['pe_ttm']):.2f}倍、市净率约{float(inno_market['pb']):.2f}倍、市销率约{float(inno_market['ps_ttm']):.2f}倍；新易盛市值约{_cny_yi_dual(eopt_market['market_cap_cny'], usd_to_cny, cny_digits=0)}，对应约{float(eopt_market['pe_ttm']):.2f}倍、{float(eopt_market['pb']):.2f}倍和{float(eopt_market['ps_ttm']):.2f}倍。这不是可以忽略增长风险的低估值区间，但倍数本身也不能回答市场已经计入多少竞争概率。{_cite('FIN-INNOLIGHT')}{_cite('FIN-EOPTOLINK')}

            估值方法先分解三层假设。第一层是AI网络需求和产品代际：若800G、1.6T和3.2T端口继续快速增长，龙头即使丢失部分份额，收入仍可能扩张；若需求本身低于预期，对照情景就会先下修。第二层是新进入者的增量影响：只有客户准入、重复订单和额外降价超过正常代际降价，才应从龙头收入中额外扣除。第三层是价值链迁移：LPO、LRO、CPO或光引擎提高时，要看龙头是否参与新架构，而不是把所有新架构份额机械记成收入损失。{_cite('SRC-LC-MAR26')}{_cite('SRC-OIF-2025')}

            当前模型可以比较经营现金流和长期经营价值相对变化，却不能直接给股权公允价值。原因并非缺少一个公式，而是企业价值到股权价值之间还缺净现金或净债务、少数股东、非经营资产、估值日至年末现金流、稀释股本和公司行动；更重要的是，受影响高速产品收入占比没有闭环。用公司全部收入承受光模块竞争冲击会得到压力上限，把这个数与市值直接比较，会把不同业务边界伪装成同口径估值。

            中际旭创和新易盛的风险承受力也不同。中际旭创2025年绝对自由现金流和产能规模更大，客户共同开发和多代量产提供更深防线；但其高增长对照路径和客户集中使单一大客户切换影响显著。新易盛2025年光产品毛利率更高、海外收入占比高、1.6T与LRO/硅光项目路线较多，产品组合可能带来弹性；其绝对现金流缓冲较小，项目阶段从样品验证到小批量不等，客户或海外线认证延迟会更快传导到现金回报。{_cite('SRC-INNO-AR25')}{_cite('SRC-EOPT-AR25')}

            因此，估值折扣不应由“立讯有产品”一次性触发，而应随证据逐级变化。区域客户有限交付更可能影响短期报价和情绪；全球头部客户准入会提高收入与毛利风险；连续两个采购周期、跨代产品和龙头同规格价格下降，则支持长期份额重估；若毛利和自由现金流也持续恶化，才需要下调长期经营中枢。反过来，若AI需求继续超预期、龙头新产品保持资格和良率、现金流随收入恢复，即使出现第二供应商，也不能自动推导永久损伤。

            ### 本节结论

            根据当前估值和证据，本研究不能得出“估值低所以风险已补偿”，因为两家公司静态倍数并不低；也不能得出“长期竞争确定恶化所以任何价格都不能买”，因为全球客户、受影响收入比例和股权价值桥尚未闭环。更稳健的判断是：立讯的商业进展已经要求投资者为尾部风险留出折扣，但折扣应随着客户、价格、份额和现金流证据更新，而不是由产品宣传一次性决定。

            ### 如果想进一步研究，需要补充

            需要建立同一估值日的企业价值到股权价值桥，并把需求、份额、价格和架构四类风险分别量化。最关键的市场验证是龙头逐客户份额和同规格成交价；最关键的财务验证是按业务的毛利、现金转换和资本开支；最关键的估值验证是不同增长与竞争情景下的每股价值，而不是只比较静态倍数。
            """,
        )
    )

    sections.append(
        _section(
            key="monitoring_plan",
            title="未来十二至二十四个月最值得跟踪的证据",
            refs=("BYD-S01", "LX-IR-20260507", "SRC-INNO-AR25", "SRC-EOPT-AR25", "SRC-OIF-2025", "SRC-BIS-JAN26"),
            source_lookup=lookup,
            sort_order=100,
            body_markdown=f"""
            未来十二至二十四个月的研究重点不是增加新闻数量，而是等待少数能跨越里程碑的硬证据。对比亚迪，最重要的是经营主体明确的高速模块产品、模块团队和客户测试；对立讯，最重要的是解释头部客户披露差异，并证明重复订单、良率和收入；对中际旭创与新易盛，最重要的是客户份额、同规格价格、毛利和现金流是否连续同向变化。

            | 观察事项 | 看到什么才真正改变判断 | 对研究结论的影响 |
            |---|---|---|
            | 比亚迪产品与团队 | 明确经营主体的800G以上规格、模块岗位和专用设备 | 将三年判断从相邻能力推进到工程验证 |
            | 比亚迪客户进展 | 客户或平台侧准入、首批交付及第二个采购周期 | 才能进入实际份额和价格分析 |
            | 立讯全球客户 | 解释既有披露差异，并出现客户侧准入或连续订单 | 显著提高全球头部客户路径的重要性 |
            | 立讯经营规模 | 模块收入、毛利、可售产能和良率开始单列 | 判断规模是否足以持续影响行业价格 |
            | 龙头经营变化 | 同规格价格、客户份额、毛利和现金流连续恶化 | 将竞争风险从估值折扣升级为盈利中枢下修 |
            | 架构与上游 | 1.6T/3.2T部署、CPO价值归属和核心器件供给变化 | 判断新进入者是否借代际切换缩短学习曲线 |

            时间顺序同样重要。产品发布、互操作和送样通常领先客户准入；客户准入领先可售产能和重复订单；收入增长又可能领先现金回报，因为扩产、存货和应收账款会先占用资金。监控时应保存事件发生日和披露日，避免把旧项目的新宣传当作新进展，也避免把同一公告的转载当成多个独立信号。比亚迪年报已经说明其数据中心相邻业务真实存在，后续只有高速模块产品或客户证据才会明显改变判断；立讯已经有产品，继续看到产品宣传的边际信息很低，客户与经济性证据更重要。{_cite('BYD-S01')}{_cite('LX-IR-20260507')}

            跟踪方法是按产品、客户、订单、产线、价格和财务六个环节记录事件，并只在新证据跨过相邻环节时更新判断。客户准入影响对应地区的进入估算，重复订单影响持续规模，龙头价格、毛利和现金流连续变化才影响盈利结论；转载和重复宣传不增加权重。

            反方证据也必须预先定义。若立讯在未来两个披露周期仍没有头部客户闭环、模块收入继续不可分或相关表述回撤，全球路径应下调；若比亚迪没有产品与团队证据，不能因为集团扩大AI服务器业务就自动提高模块概率。若中际旭创、新易盛在新增供应出现后仍保持同规格价格、毛利和现金流，说明市场增长、产品升级或客户关系吸收了竞争，盈利压力应下调。{_cite('SRC-INNO-AR25')}{_cite('SRC-EOPT-AR25')}

            外部条件包括核心器件供应、出口许可和架构标准。美国对相关半导体出口许可采用逐案审查，可能影响高端DSP或器件获取，但公开政策不能直接告诉我们某家公司具体订单是否获批；CPO和光引擎标准推进可能重分价值，却也可能让有共同设计能力的龙头继续参与。政策和标准只在影响实际产品、客户或供应时更新公司判断。{_cite('SRC-BIS-JAN26')}{_cite('SRC-OIF-2025')}

            ### 本节结论

            根据当前证据，最有信息价值的三个触发点依次是：客户侧准入、连续两个采购周期的订单、龙头同规格价格与现金流的持续变化。产品页、伙伴演示、招聘和专利仍可作为前置信号，但它们不能单独改变盈利结论。采用这套顺序可以减少噪声，并让每次概率或财务更新都能对应一条真实证据链。

            ### 如果想进一步研究，需要补充

            应建立按公司和产品维护的季度证据记录，明确产品、客户、订单、产线、价格和财务六个环节，并为每条记录保留原始来源和反方材料。若能够获得客户、供应商或设备侧原始文件，应优先用于确认阶段；无法公开的项目只保留在宽范围中，不用匿名转述替代。
            """,
        )
    )
    section_by_key = {row["section_key"]: row for row in sections}

    def compact_financial_triplet(row: dict[str, Any]) -> str:
        return (
            f"收入{_cny_yi_table_value(row['revenue_cny_yi'], usd_to_cny, 0)}<br>"
            f"净利润{_cny_yi_table_value(row['net_income_cny_yi'], usd_to_cny, 0)}<br>"
            f"现金流{_cny_yi_table_value(row['fcf_cny_yi'], usd_to_cny, 0)}"
        )

    def after_entry_amount_cell(
        summary: dict[str, Any], field: str, loss_key: str
    ) -> str:
        reference = summary["reference_row"][field]
        conditioned = summary["row"][field]
        loss = summary["loss_vs_reference_pct"][loss_key]
        return (
            f"{_number(reference, 2)} → {_number(conditioned, 2)}"
            f"<br>下降{float(loss):.2f}%"
        )

    def after_entry_terminal_cell(summary: dict[str, Any]) -> str:
        return (
            f"{_number(summary['reference_terminal_value_cny_yi'], 2)} → "
            f"{_number(summary['terminal_value_cny_yi'], 2)}"
            f"<br>下降{float(summary['loss_vs_reference_pct']['terminal']):.2f}%"
        )

    overview = _section(
        key="core_answers",
        title="核心答案：谁更可能进入，何时会真正影响龙头",
        refs=(
            "BYD-S01",
            "LX-TRANSCEIVER-CURRENT",
            "LX-IR-202508",
            "LX-IR-20260507",
            "SRC-LC-MAR26",
            "MODEL-WORKPAPER",
        ),
        source_lookup=lookup,
        sort_order=20,
        body_markdown=f"""
        ### 问题

        投资判断要分开回答三件事：比亚迪和立讯能否形成有意义进入；高速光互联需求能否吸收新增合格供给；新进入者取得客户后，是否会同时压低中际旭创和新易盛的份额、价格与现金回报。把三件事合成一个“会不会竞争”的标签，会把产品发布误写成盈利冲击。

        ### 证据与数据

        | 需要回答的问题 | 当前答案 | 最关键的证据限制 |
        |---|---|---|
        | 比亚迪电子未来三至五年能否形成规模 | 3年约{_pct(probabilities['byd3'])}，5年约{_pct(probabilities['byd5'])} | 多家具名券商记录了同一管理层交流线索；发行人原文、客户准入、实际批量和重复订单仍未闭环 |
        | 立讯精密未来三至五年能否形成规模 | 3年约{_pct(probabilities['lux3'])}，5年约{_pct(probabilities['lux5'])} | 已有800G/1.6T产品与有限商业化，全球头部客户、良率和可分收入仍未闭环 |
        | 至少一家能否形成有意义进入 | 3年约{_pct(probabilities['any3'])}，5年约{_pct(probabilities['any5'])} | 两家公司共同受AI需求、器件供给、客户多供应商策略和架构切换影响 |
        | 至少一家能否进入全球头部客户体系 | 3年约{_pct(probabilities['global3'])}，5年约{_pct(probabilities['global5'])} | 全球路径需要客户侧准入、连续订单和规模交付，明显严于区域进入 |
        | 2031年市场能否吸收新增供给 | 约{_ports_million_cn(market_2031['total_ports_million'])}端口、{_usd_bn_cn(market_2031['normal_market_revenue_usd_bn'])}收入；合格供给/需求约{_number(market_2031['qualified_supply_demand_ratio'], 2)}倍 | 这是资格与良率约束后的工作路径，不是已发生的行业统计 |

        地域差异比总进入概率更能说明风险先从哪里出现。比亚迪进入中国客户体系的判断约为三年{_pct(probabilities['byd_china3'])}、五年{_pct(probabilities['byd_china5'])}，进入全球头部客户约为三年{_pct(probabilities['byd_global3'])}、五年{_pct(probabilities['byd_global5'])}；立讯对应约为中国三年{_pct(probabilities['lux_china3'])}、五年{_pct(probabilities['lux_china5'])}，全球三年{_pct(probabilities['lux_global3'])}、五年{_pct(probabilities['lux_global5'])}。从两家公司合并看，“至少一家已在中国客户形成规模、但两家都尚未进入全球头部客户”的路径约为三年{_pct(probabilities['china_only3'])}、五年{_pct(probabilities['china_only5'])}。中国与全球数字可以重叠，且都受限于客户保密和项目地域披露，不能相加成公司总概率；对判断最重要的是，区域报价压力可能明显早于全球龙头客户的份额冲击。{_cite('MODEL-WORKPAPER')}

        立讯的产品目录、发行人量产与客户验证表述，使它成为需要进入盈利讨论的真实潜在进入者；但2024年至2026年的客户口径并不完全一致。对比亚迪电子，多家券商共同转述的800G工程化和客户推广路线只能作为待核验线索；这些目标还没有被发行人原文、公司年报、客户资格、实际批量、专线良率和可分收入串成商业闭环。{_cite('LX-TRANSCEIVER-CURRENT')}{_cite('LX-IR-202508')}{_cite('LX-IR-20260507')}{_cite('BYD-LEAD-FIRSTSH-20250901')}{_cite('BYD-LEAD-CMBI-20250902')}{_cite('BYD-LEAD-CINDA-20250905')}{_cite('BYD-S01')}

        ### 判断方法

        “有意义进入”要求可归属经营主体的800G以上产品、客户准入、跨两个采购或披露周期的重复交付，以及足以影响行业价格的经营规模同时成立。每家公司分别设置保守值、最可能值和上限；财务测算需要单一输入时取三者平均。公司之间的共同需求和供给因素进入联合计算，但随机抽样只传播已有范围，不制造新证据。详细证据、公司边界、概率计算、行业供需、客户认证与招聘专利审计只在本页后面的专题研究中展开一次。{_cite('MODEL-WORKPAPER')}

        历史案例只用于判断进入路径，不用于凑出一个成功率。收购成熟产品、团队和客户平台可能缩短时间，内部从零建设则要逐项跨过产品、客户和良率；专业制造或器件能力也不能自动等同于完整模块业务。因此，比亚迪的合作或收购证据会主要改变五年判断，立讯的客户与重复订单则会直接改变三年判断。

        ### 结论

        根据现有证据，可以认为三年内最现实的路径仍是立讯先在中国或区域客户形成第二来源；比亚迪则需要从三年维度开始跟踪800G目标是否兑现，并在五年维度评估能否形成规模。五年至少一家形成规模的可能性已经不能忽略，但“形成进入”仍不等于“龙头利润确定受损”。只有全球客户准入、重复订单、额外降价和龙头现金流恶化连续同向出现，才应下调长期盈利中枢。

        ### 如果想深入研究，需要补充

        最优先补充两家公司逐产品的客户准入、两期以上订单、模块线良率和可分收入；同时补齐龙头按速率、客户、地区拆分的收入、毛利与成交价。没有这些原始信息，概率范围可以比较方向，却不能被当成精确频率。
        """,
    )

    financial_summary = _section(
        key="financial_method_and_results",
        title="龙头盈利测算：用了什么数据，怎样计算，结果意味着什么",
        refs=(
            "SRC-INNO-AR25",
            "SRC-EOPT-AR25",
            "FIN-INNOLIGHT",
            "FIN-EOPTOLINK",
            "MODEL-WORKPAPER",
        ),
        source_lookup=lookup,
        sort_order=30,
        body_markdown=f"""
        ### 问题

        财务测算要回答的不是“新玩家出现后龙头会不会少卖一点”，而是客户份额、同规格额外降价、良率与固定成本、扩产支出和营运资本如何共同传导到收入、净利润和现金流，以及当前高估值是否足以承受这种变化。

        ### 2025年历史与2031年未来财务情景：收入、净利润和现金流

        下表用同一金额单位和展示结构比较2025年实际值与2031年未来情景。表内金额单位为亿元人民币，括号内为按1美元={usd_to_cny:.4f}元人民币换算的亿美元。2025年简单自由现金流等于经营现金流减去购建固定资产、无形资产和其他长期资产的现金支出；2031年情景现金流则从正常化现金流中再扣除防守性扩产和新增营运资本，两者都不等同于完整的企业自由现金流。2031年参考路径冻结了本模型新增的比亚迪/立讯竞争与架构冲击，但2026—2027年起点来自市场聚合预期，可能已经含有部分已知竞争，因此不是纯粹的“没有竞争”反事实。

        | 公司 | 2025年实际 | 2031年参考路径 | 2031年按年度概率加权的压力上限 | 相对参考路径 |
        |---|---|---|---|---|
        | 中际旭创 | 收入382.40（56.43）<br>净利润107.97（15.93）<br>简单现金流81.36（12.01） | {compact_financial_triplet(inno_base)} | {compact_financial_triplet(inno_weighted)} | 收入低{(1-float(inno_weighted['revenue_cny_yi'])/float(inno_base['revenue_cny_yi']))*100:.1f}%<br>净利润低{(1-float(inno_weighted['net_income_cny_yi'])/float(inno_base['net_income_cny_yi']))*100:.1f}%<br>现金流低{(1-float(inno_weighted['fcf_cny_yi'])/float(inno_base['fcf_cny_yi']))*100:.1f}% |
        | 新易盛 | 收入248.42（36.66）<br>净利润95.32（14.07）<br>简单现金流63.81（9.42） | {compact_financial_triplet(eopt_base)} | {compact_financial_triplet(eopt_weighted)} | 收入低{(1-float(eopt_weighted['revenue_cny_yi'])/float(eopt_base['revenue_cny_yi']))*100:.1f}%<br>净利润低{(1-float(eopt_weighted['net_income_cny_yi'])/float(eopt_base['net_income_cny_yi']))*100:.1f}%<br>现金流低{(1-float(eopt_weighted['fcf_cny_yi'])/float(eopt_base['fcf_cny_yi']))*100:.1f}% |

        2025年实际数据来自两家公司年报；当前市值分别约{_cny_yi_dual(inno_market['market_cap_cny'], usd_to_cny, cny_digits=0)}和{_cny_yi_dual(eopt_market['market_cap_cny'], usd_to_cny, cny_digits=0)}，市盈率约73倍和63倍。两家公司前五大客户收入占比都超过70%，高增长、高客户集中和较高估值共同放大了执行低于预期的风险。{_cite('SRC-INNO-AR25')}{_cite('SRC-EOPT-AR25')}{_cite('FIN-INNOLIGHT')}{_cite('FIN-EOPTOLINK')}

        ### 计算方法

        参考路径先用2026—2027年分析师聚合预期约束近端收入，再显式递减增长率，并把毛利率、净利率和正常化现金流率逐年下调；这些是研究假设，不是公司指引。中际旭创的三项比例从2026年的44% / 29% / 18%逐步降至2031年的39% / 24% / 14%，新易盛从47% / 37% / 22%降至38% / 25% / 13%。每个年度使用当年的进入概率，不把2031年终局风险提前施加到2027年。传统可插拔、显著LPO/LRO迁移和CPO增量风险约按{float(architecture_weights['P']):.0%}、{float(architecture_weights['H']):.0%}和{float(architecture_weights['C']):.0%}加权；它们是情景发生权重，不是市场份额。由于没有数据校准公司进入与架构迁移是否同时发生，基础测算暂按两者独立，联合发生只作为尾部压力。

        收入先把不受影响业务保留，再令受影响高速产品收入依次乘以“1减份额损失”和“1减额外降价”；毛利率下降的72%传导到净利率，再叠加固定成本拖累；现金流从正常化现金流中扣除防守性扩产和新增营运资本。72%是专家压力假设，不是公司披露。在“立讯先形成区域规模”的情景里，防守性扩产和新增营运资本占收入的比例暂时取相同值：中际旭创到2031年两项均约0.55%，新易盛均约0.65%。这不是两笔独立估计恰好相等，而是公开资料不能拆出分业务现金转化率时，为避免凭空制造差异而使用的临时假设；取得分业务资本开支和营运资本数据后应分别重估。{_cite('MODEL-WORKPAPER')}

        ### 三种最有意义的压力路径

        立讯只在区域或中国客户形成规模时，模型给中际旭创的份额、额外降价和毛利率压力分别约3.68%、2.76%和1.84个百分点；新易盛约4.32%、3.24%和2.16个百分点。这更像局部报价和现金回报压力，市场增长仍可能吸收一部分影响。

        只有一家新进入者进入全球头部客户、传统可插拔仍占主导时，中际旭创的三项压力约9.20%、7.36%和4.14个百分点；新易盛约10.80%、8.64%和4.86个百分点。客户突破与同规格额外降价同时发生后，利润和现金流损失会明显大于收入损失。

        两家公司都进入全球客户并同时发生显著架构迁移时，中际旭创份额、额外降价和毛利率压力约31.28%、18.40%和14.26个百分点，新易盛约36.72%、21.60%和16.74个百分点。这是多个不利条件同发的尾部压力，不是当前中心预测；极端负现金流情景不使用永续增长终值。

        ### 至少一家进入后，竞争和长期盈利会恶化到什么程度

        如果至少一家形成有意义进入，模型先按研究请求的定义，把各条进入路径分别赋予温和、明显和严重三种结果的判断权重，再用各路径的进入概率加权并重新归一。温和是新进入者主要成为第二供应商、市场增长仍能吸收大部分新增供给；明显是报价、份额或利润率持续承压；严重是份额、现金流和长期价值受到广泛且难以抵消的冲击。三年内三种结果约为{_pct(competition_severity['3y']['mild'], 2)}、{_pct(competition_severity['3y']['material'], 2)}和{_pct(competition_severity['3y']['severe'], 2)}，五年约为{_pct(competition_severity['5y']['mild'], 2)}、{_pct(competition_severity['5y']['material'], 2)}和{_pct(competition_severity['5y']['severe'], 2)}。这组数字回答“进入已经发生后可能走向哪一档”，属于结构化研究判断，不是从下文财务结果反算的分类，也不是行业历史发生率；下段的15%和20%阈值是另一项独立计算，专门回答龙头长期盈利是否受到显著损害。{_cite('MODEL-WORKPAPER')}

        下表进一步只保留“至少一家已经形成有意义进入”的路径，把没有任何一家进入的路径排除后重新加权。金额单位为亿元人民币；“情景现金流”是在正常化现金流基础上扣除防守性扩产和新增营运资本，“正常化终值”由2031年正常化现金流计算。

        | 公司 | 2031年收入：参考→进入后均值 | 2031年净利润：参考→进入后均值 | 2031年情景现金流：参考→进入后均值 | 2031年正常化终值：参考→进入后均值 | 进入后达到长期显著损害标准的概率 |
        |---|---:|---:|---:|---:|---:|
        | 中际旭创 | {after_entry_amount_cell(inno_after_entry, 'revenue_cny_yi', 'revenue')} | {after_entry_amount_cell(inno_after_entry, 'net_income_cny_yi', 'net_income')} | {after_entry_amount_cell(inno_after_entry, 'fcf_cny_yi', 'fcf')} | {after_entry_terminal_cell(inno_after_entry)} | {_pct(long_term_damage['conditional_by_company']['innolight'], 2)} |
        | 新易盛 | {after_entry_amount_cell(eopt_after_entry, 'revenue_cny_yi', 'revenue')} | {after_entry_amount_cell(eopt_after_entry, 'net_income_cny_yi', 'net_income')} | {after_entry_amount_cell(eopt_after_entry, 'fcf_cny_yi', 'fcf')} | {after_entry_terminal_cell(eopt_after_entry)} | {_pct(long_term_damage['conditional_by_company']['eoptolink'], 2)} |

        对龙头的长期显著损害采用更严格、可复算的定义：2029—2031年平均净利润和情景现金流都比冻结本模型新增冲击的参考路径低至少15%，同时2031年正常化终值低至少20%。在至少一家已经形成有意义进入的路径中，中际旭创达到该标准的概率约{_pct(long_term_damage['conditional_by_company']['innolight'], 2)}，新易盛约{_pct(long_term_damage['conditional_by_company']['eoptolink'], 2)}；把“没有任何一家进入”的可能性也纳入后，进入事件与长期显著损害同时发生的联合概率分别约{_pct(long_term_damage['unconditional_by_company']['innolight'], 2)}和{_pct(long_term_damage['unconditional_by_company']['eoptolink'], 2)}。新易盛更高，主要因为模型给它更大的高速业务竞争暴露和利润、现金流传导系数；但两组结果仍建立在全公司收入100%受影响的压力上限上，不是中心预测、目标价或经验频率。{_cite('MODEL-WORKPAPER')}

        当前公开资料无法把两家公司未来800G以上收入与其他业务准确拆开，所以表中把全公司收入都视为受影响收入，只能看作压力上限。量化敏感度如下：受影响收入占比每增加10个百分点，中际旭创2031年收入、净利润和现金流相对参考路径分别再下降约{inno_exposure_elasticity['revenue_pct']:.2f}、{inno_exposure_elasticity['profit_pct']:.2f}和{inno_exposure_elasticity['fcf_pct']:.2f}个百分点；新易盛约{eopt_exposure_elasticity['revenue_pct']:.2f}、{eopt_exposure_elasticity['profit_pct']:.2f}和{eopt_exposure_elasticity['fcf_pct']:.2f}个百分点。这个敏感度只回答业务暴露假设改变后结果怎样变化，不代表真实暴露比例。

        为避免100%全收入压力上限遮蔽结果范围，再把受影响收入分别设为公司总收入的50%、75%和100%。中际旭创2031年的收入 / 净利润 / 现金流相对参考路径分别下降{inno_exposure_cases[50]['2031_revenue_loss_pct']:.2f}% / {inno_exposure_cases[50]['2031_net_income_loss_pct']:.2f}% / {inno_exposure_cases[50]['2031_actual_fcf_loss_pct']:.2f}%、{inno_exposure_cases[75]['2031_revenue_loss_pct']:.2f}% / {inno_exposure_cases[75]['2031_net_income_loss_pct']:.2f}% / {inno_exposure_cases[75]['2031_actual_fcf_loss_pct']:.2f}%和{inno_exposure_cases[100]['2031_revenue_loss_pct']:.2f}% / {inno_exposure_cases[100]['2031_net_income_loss_pct']:.2f}% / {inno_exposure_cases[100]['2031_actual_fcf_loss_pct']:.2f}%；新易盛分别下降{eopt_exposure_cases[50]['2031_revenue_loss_pct']:.2f}% / {eopt_exposure_cases[50]['2031_net_income_loss_pct']:.2f}% / {eopt_exposure_cases[50]['2031_actual_fcf_loss_pct']:.2f}%、{eopt_exposure_cases[75]['2031_revenue_loss_pct']:.2f}% / {eopt_exposure_cases[75]['2031_net_income_loss_pct']:.2f}% / {eopt_exposure_cases[75]['2031_actual_fcf_loss_pct']:.2f}%和{eopt_exposure_cases[100]['2031_revenue_loss_pct']:.2f}% / {eopt_exposure_cases[100]['2031_net_income_loss_pct']:.2f}% / {eopt_exposure_cases[100]['2031_actual_fcf_loss_pct']:.2f}%。这些档位不是对真实业务占比的估计，而是说明在相同竞争假设下，现金流损失如何随着实际暴露范围扩大。{_cite('MODEL-WORKPAPER')}

        未来增长路径带来的摆幅更大。把2026—2027年聚合预期以低、参考和高三种递减速度外推，中际旭创2031年收入约为{_cny_yi_dual(inno_revenue_range[0], usd_to_cny, cny_digits=0)}、{_cny_yi_dual(inno_revenue_range[1], usd_to_cny, cny_digits=0)}和{_cny_yi_dual(inno_revenue_range[2], usd_to_cny, cny_digits=0)}；新易盛约为{_cny_yi_dual(eopt_revenue_range[0], usd_to_cny, cny_digits=0)}、{_cny_yi_dual(eopt_revenue_range[1], usd_to_cny, cny_digits=0)}和{_cny_yi_dual(eopt_revenue_range[2], usd_to_cny, cny_digits=0)}。低增长与高增长接近三倍，说明AI需求和龙头自身执行首先决定绝对价值，新进入者是其上的增量压力，而不是全部差异的来源。

        ### 结论

        根据现有数据，可以认为立讯进展已经足以进入龙头盈利与估值讨论，但当前绝对损失仍是全收入暴露的压力上限，不是中心预测或目标价。最值得重视的是现金流对收入冲击更敏感：扩产、库存和应收会在利润率受压后继续放大结果。当前高估值没有提供“风险已经充分补偿”的证据，完整股权价值仍缺受影响收入比例、净现金或净债务、少数股东、非经营资产和稀释股本桥。

        ### 如果想深入研究，需要补充

        需要按速率、客户、地区和产品形态拆分收入、毛利与成交价，并取得分业务扩产支出、存货、应收、可售良率和重复订单；完成净现金、少数股东、非经营资产和稀释股本桥后，才能把压力上限改成可用于每股估值的中心情景。
        """,
    )

    guide = _section(
        key="topic_guide",
        title="九个专题页分别解决什么问题",
        refs=("BYD-S01", "LX-IR-202508", "MODEL-WORKPAPER"),
        source_lookup=lookup,
        sort_order=40,
        body_markdown=f"""
        主报告只保留跨公司的核心结论和两张用途不同的财务结果表：一张把2025年实际、2031年参考路径和包含未进入可能性的总体压力放在一起，另一张专门回答至少一家进入后两家龙头的盈利与终值会怎样变化。页面下方的九个可点击专题页分别展开：比亚迪进入风险、立讯商业化进度、中际旭创盈利风险、新易盛盈利风险、主体和阶段定义、概率计算方法、行业供需模型、客户认证与上游约束、招聘专利与产能证据。公司证据、模型细节和反方分析只在对应专题页完整出现，不在主报告再次复制。

        阅读顺序可以按问题选择：想判断谁更接近商业化，先看比亚迪和立讯两页；想验证概率，查看主体定义和概率方法；想理解盈利和估值，结合龙头两页与主报告财务章节；想跟踪早期信号，再看客户认证、上游、招聘专利和产能。真实Viewer会在本节之后给出九个专题的可点击入口；独立Markdown报告也在后文提供同页目录。

        公司专题页还会给出对应证券或观察标的的入口，标的页只保留与该公司直接相关的市值、估值、收入、利润、现金流和条件化建议。主报告不再复制这些标的数据，也不把标的页的行情快照当成行业证据。这样既能从结论进入公司，也能从公司继续进入证券，而不会在三个页面重复同一张宽表。

        ### 结论

        详细分析按问题只保留一份：主报告回答“现在应该怎样判断”，专题页回答“证据和方法为什么支持这一判断”。这种分工减少重复，也让读者可以直接进入最关心的公司或方法。

        ### 如果想深入研究，需要补充

        若后续出现新的公司、技术路线或标的，应先判断它能否并入现有九个问题；只有确实需要独立证据、计算和结论时才新增专题，避免为了字段覆盖制造低信息页面。
        """,
    )

    selected = [
        section_by_key["summary"],
        overview,
        financial_summary,
        section_by_key["monitoring_plan"],
    ]
    for row in selected:
        row["body_markdown"] = (
            row["body_markdown"]
            .replace("### 本节结论", "### 结论")
            .replace(
                "### 如果想进一步研究，需要补充",
                "### 如果想深入研究，需要补充",
            )
        )
    return selected


_ENTITY_REFS: dict[str, tuple[str, ...]] = {
    "byd_entry_risk": (
        "BYD-S01",
        "BYD-S02",
        "BYD-S04",
        "BYD-S06",
        "BYD-S11",
        "BYD-S14",
        "BYD-S16",
        "BYD-S18",
        "BYD-LEAD-FIRSTSH-20250901",
        "BYD-LEAD-CMBI-20250902",
        "BYD-LEAD-CINDA-20250905",
        "BYD-LEAD-IDCE-2026",
        "BYD-LEAD-TGB-20260718",
        "BYD-PAT-CN122052920A",
        "BYD-PAT-CN122362593A",
        "BYD-PAT-CN121012567A",
        "MODEL-WORKPAPER",
        "FIN-BYD_ELECTRONIC",
        "FIN-BYD",
    ),
    "luxshare_entry_risk": (
        "LX-OPTICS-CURRENT",
        "LX-TRANSCEIVER-CURRENT",
        "LX-800G-LPO-SPEC",
        "LX-FRO-2026",
        "LX-IR-202508",
        "LX-ANNUAL-2024",
        "LX-IR-20260507",
        "OIF-OFC2026",
        "NVIDIA-CX8-VALIDATED",
        "FIN-LUXSHARE",
        "MODEL-WORKPAPER",
    ),
    "innolight_terminal_risk": (
        "SRC-INNO-AR25",
        "SRC-INNO-1600",
        "SRC-INNO-FUND26",
        "FIN-INNOLIGHT",
        "MODEL-WORKPAPER",
    ),
    "eoptolink_terminal_risk": (
        "SRC-EOPT-AR25",
        "FIN-EOPTOLINK",
        "MODEL-WORKPAPER",
    ),
    "entity_scope_and_stage_definitions": (
        "BYD-S01",
        "BYD-S02",
        "LX-TRANSCEIVER-CURRENT",
        "LX-IR-202508",
        "SRC-CISCO-ACACIA21",
        "SRC-LITE-CLOUD23",
        "SRC-FN-10K24",
    ),
    "probability_method_and_baserate": (
        "BYD-S01",
        "LX-IR-202508",
        "SRC-CISCO-ACACIA21",
        "SRC-INTEL-Q323",
        "SRC-FN-10K24",
        "MODEL-WORKPAPER",
    ),
    "industry_demand_supply_model": (
        "SRC-LC-MAR26",
        "SRC-CIGNAL-4Q24",
        "SRC-HKEX-ASP26",
        "SRC-OIF-2025",
        "MODEL-WORKPAPER",
    ),
    "qualification_upstream_constraints": (
        "LX-IR-202508",
        "NVIDIA-CX8-VALIDATED",
        "OIF-OFC2026",
        "SRC-COHR-10K25",
        "SRC-MRVL-10Q25",
        "SRC-BIS-JAN26",
    ),
    "recruitment_patent_capacity_audit": (
        "BYD-S06",
        "BYD-S11",
        "BYD-S14",
        "BYD-S16",
        "BYD-PAT-CN122052920A",
        "BYD-PAT-CN122362593A",
        "BYD-PAT-CN121012567A",
        "LX-TRANSCEIVER-CURRENT",
        "LX-ANNUAL-2025",
        "JOB-ZHAOPIN-COUPLING",
        "OIF-OFC2026",
    ),
}


_ENTITY_ADDITIONAL_ANALYSIS: dict[str, str] = {
    "byd_entry_risk": """
    ## 哪些情况会改变上述判断

    低估比亚迪的主要风险，是公开资料可能滞后于客户共同开发。公司已经服务数据中心客户，具备系统、电源、液冷和制造协同，理论上可以通过合作开发、采购核心器件或收购成熟团队缩短路径；客户保密也可能让产品在正式发布前长期不可见。如果后续出现明确子公司的光模块设备投入、供应商配套和客户可靠性测试，即使收入尚未披露，也足以把判断从前置准备推进到工程验证。

    高估比亚迪的主要风险，则是把集团能力理解成产品能力。大规模电子制造对装配、采购和资本投入有帮助，但高速光学耦合、烧机、可靠性和客户系统验证存在专门学习曲线。数据中心客户购买服务器或液冷，也不会自动把光模块资格交给同一供应商。集团专利数量和招聘范围很大，只有能连接到经营法人、目标产品和客户项目的记录才改变判断。

    三条可能路径的证明要求不同。内部自建要看到团队、产品、设备和客户连续推进；与现有厂商合作要确认比亚迪实际承担的设计、制造和客户责任，不能只看联合展示；收购要确认产品、团队、客户合同和收入是否真正转移并进入合并报表。收购成熟平台可能最快，却也面临交易价格、客户重新认证和核心人员留存。当前证据没有支持其中任何一条成为确定主线，因此五年范围保持宽而不选择单一路径。

    对投资研究而言，上行与风险应分开。比亚迪电子若完成进入，可能获得AI基础设施新增收入；在此之前，把光模块收入提前放入盈利预测会重复计算系统业务的协同。比亚迪股份的主题暴露更加间接，不能因为母公司知名度更高就获得更强结论。最合适的做法是按产品、客户、产线和收入四个触发点逐级更新，而不是用集团层新闻一次性重估。
    """,
    "luxshare_entry_risk": """
    ## 哪些情况会改变上述判断

    低估立讯的可能性来自客户保密和产品口径差异。2024年“国际头部客户交付”、2025年“主要面向中小数据中心”和2026年“业务仍处起步阶段”未必互相否定，可能分别描述测试、小批、不同产品或不同地区。如果后续客户侧记录确认其中一条高速模块路线已进入正式供应，即使集团仍称业务规模较小，全球客户判断也应明显上调。

    高估立讯的风险来自把工程能力直接换算成经营规模。产品目录可以长期保留尚未形成大额收入的型号，伙伴演示也可能只覆盖样品或特定接口；发行人“量产”没有交付数量、良率和可分收入时，无法判断是小批稳定生产还是足以改变行业价格的规模。集团连接器和线缆优势能降低系统协同成本，但光模块核心器件、封装和可靠性仍需独立学习。

    客户为什么导入立讯同样影响结果。若客户只是增加备份供应、分配很小份额，立讯可以获得收入却不会显著改变龙头长期利润；若客户以多供应商策略推动同规格降价并逐代扩大份额，经营影响会持续增强。反过来，若良率、核心器件或交付稳定性不满足要求，客户可能保留资格却不扩大采购。客户准入、订单比例和重复周期必须分开观察。

    立讯还可能通过LPO、LRO或光引擎等新路线绕开部分传统模块竞争，但新架构要求更深的交换芯片、链路和封装协同，并不天然降低门槛。公司是否能在新架构中捕获利润，取决于设计责任、核心器件采购、客户共同开发和售后成本。研究因此不把产品路线数量当收入上限，只在看到客户与经济数据后改变盈利判断。
    """,
    "innolight_terminal_risk": """
    ## 哪些情况会改变上述判断

    竞争者进入不是中际旭创未来表现的唯一解释。AI资本开支、交换芯片周期、客户网络架构、正常代际降价、其他现有厂商和公司自身产品执行都可能改变收入与毛利。若未来毛利下降而立讯尚未取得对应客户订单，不能把变化全部归因于本研究主题；同样，如果竞争者取得资格但市场增长更快，中际旭创绝对收入仍可能上升。

    客户集中具有双重含义。大客户占比高会放大份额切换，但也说明公司已经通过严格认证、建立共同开发与交付记录。新供应商要复制的不只是产品参数，还包括大规模良率、响应速度、海外交付和跨代协同。中际旭创可以通过更快推出1.6T及后续产品、参与新架构、降本或提高客户服务来抵消部分份额压力，因此压力情景不应被理解成被动静态损失。

    现金流是区分短期防守和长期受损的关键。扩产会在需求强时暂时压低现金，却增加未来可售能力；客户切换导致的库存、应收和低利用率则可能让现金流持续弱于利润。研究应同时看资本开支用途、产能利用、存货周转和经营现金流，不能因单季现金流下降就确认长期损伤，也不能因净利润仍增长就忽略现金占用。

    当前估值要求对照情景本身保持很高增长。若AI需求低于预期，即使没有新进入者，绝对价值也会显著下修；若需求超预期，中际旭创可能在份额略降时仍创造更多利润。因而估值更新应先重估行业需求与公司产品执行，再增加可识别的新进入者冲击。缺少受影响收入比例和完整股权桥时，经营价值相对变化只能用于比较，不能直接换成目标价。
    """,
    "eoptolink_terminal_risk": """
    ## 哪些情况会改变上述判断

    新易盛的高毛利并不自动等于更容易被低价竞争击穿。较高毛利可能来自高端产品组合、客户共同开发、技术价值和海外供应能力，也为研发与价格应对提供空间；但如果高毛利集中在少数客户和速率，客户导入第二来源时，利润弹性又可能大于收入弹性。需要逐客户和逐产品数据才能区分这两种解释。

    多条研发路线既是选择权，也可能分散资源。1.6T完成内部验证、LRO与硅光PIC进入小批、线性可插拔仍在样品评估，说明不同项目处在不同阶段。若其中一条快速获得客户并形成良率，架构变化可以成为防线；若多条路线同时投入却没有规模订单，研发、设备和营运资本会拖累现金回报。项目数量不能代替阶段质量。

    海外制造也需要区分资产与资格。泰国子公司提供地理和供应链选择，但注册资本或工厂存在不代表具体高速产品已通过客户认证。海外线资格、核心器件来源、可售产能与客户订单必须相互印证。政策变化可能提高海外布局价值，也可能增加器件替代和重新认证成本，不能只按“海外产能”给出单向结论。

    新易盛2024年至2025年的现金流变化表明，扩产阶段会让现金转换显著波动。若未来现金流下降，应先拆分资本开支、存货、应收和利润变化；只有客户份额、同规格价格、毛利和现金流连续同向走弱，才支持长期盈利中枢下修。静态估值较高使执行不及预期更敏感，但没有完整股权价值桥时，不能从压力金额直接得到买卖价位。

    还需要把“利润高”与“现金可持续”分开。新易盛高端产品放量可以同时提高收入和毛利，但若客户账期延长、备货增加或海外线继续投入，现金回报可能暂时落后。只有把这些经营变化与竞争者订单放在同一季度比较，才能判断现金压力来自成长投入还是份额防守。
    """,
    "entity_scope_and_stage_definitions": """
    ## 哪些情况会改变上述判断

    严格阶段定义可能低估保密项目，但宽松定义会系统性高估进入。客户通常不会公开完整合格供应名单，发行人也可能在业务尚小时不单列收入；因此“公开没有”只能表示当前没有直接证据，不能证明项目不存在。研究用较宽的估算范围吸收这种低估风险，同时仍要求客户、订单、产线或收入中至少出现可核验连接，避免匿名消息成为确定事实。

    主体划分也可能在合作模式下变得复杂。一家公司可以负责系统销售，另一家负责模块设计，第三方提供光引擎或代工；收入、客户责任和技术所有权未必在同一法人。此时不能只问“谁做了产品”，还要问谁承担质量、谁拥有客户合同、谁确认收入以及谁的产能影响行业。合作伙伴演示只能证明参与，不能回答这些经营问题。

    阶段不是简单直线。产品可能通过一次客户测试后因器件变更重新认证；获得资格可能只有很小份额；量产可能限于单一速率或距离；跨代产品又可能重新打开竞争。因此研究记录要保存产品、客户、版本和时间，不能把一项早期资格永久继承给后续代际。反过来，已经形成两期重复订单的产品比单次“量产”表述更能证明持久性。

    财务影响还要求事件规模阈值。少量区域交付可以确认公司进入，却未必改变龙头价格或利润；只有可售产能和订单达到客户采购中的实质份额，才进入强冲击情景。研究因此把“是否进入”和“进入后影响多大”分开，避免用一个状态同时回答产品、客户和盈利三个问题。
    """,
    "probability_method_and_baserate": """
    ## 哪些情况会改变上述判断

    概率范围最容易被误读成精确预测。中心值只是三个工作判断的平均数，端点来自现有证据、反方材料和事件门槛，不具有历史频率的含义。即使随机抽样次数非常多，数值误差变小，也不会让客户保密、样本异质或主观端点消失。公开报告因此舍弃多个分位数字，只保留能改变判断的中心和完整范围。

    事件门槛本身会显著改变答案。若把一次区域小批也算进入，两家公司概率都会上升，尤其是已经有产品的立讯；若要求全球头部客户、跨代订单和可分利润同时成立，概率会明显下降。研究选择严格口径，是因为问题关心对行业格局和龙头盈利的实质影响。任何读者用不同口径比较时，都应先重新定义事件，而不是直接搬用数字。

    公司间关系也不是固定常数。AI需求强、客户主动增加第二来源或核心器件普遍改善时，两家公司可能同向受益；稀缺器件、认证资源和客户份额相互挤出时，又可能一家公司推进、另一家延后。联合结果对这种关系有敏感性，但最大不确定性仍是公司自身产品与客户阶段。模型不应让复杂的联合运算遮住这一事实。

    更新规则应保持局部。比亚迪出现数据中心服务器订单，不应提高其光模块客户概率；立讯新增一次伙伴演示，不应同时提高重复订单和利润判断；客户侧准入只影响对应客户与地区，跨两期订单才影响持久规模。这样做虽然不能消除判断成分，却能让每次变化有可解释的证据来源。

    计算复核也应保持简单透明。公司中心值可以由三个工作判断直接相加再除以三，联合结果可以由“至少一家”与“两家同时”的集合关系复核，五年累计判断不得低于三年。若任何复杂模拟与这些基本关系不一致，应先修正计算，而不是增加更多术语解释。

    数字最终服务于判断，而不是替代判断。
    """,
    "industry_demand_supply_model": """
    ## 哪些情况会改变上述判断

    需求预测面临部署节奏、网络架构和客户集中三类风险。大型AI集群可能比预期更快扩张，也可能因芯片供给、资本开支回报或网络设计变化推迟；800G与1.6T可以长期共存，不一定按整齐年份替换；少数头部客户的采购变化会让年度出货波动明显大于长期趋势。表中的需求与价格假设只用于比较，不能当成行业承诺。

    供给预测比设备数量更难。产线安装、试产、客户认证、良率和可售产量之间存在时间差，且不同速率和距离不能完全互换。新进入者获得一条客户线的资格，不代表其全部设备都成为合格供给；龙头扩产也可能先服务更高速产品。只有按产品和客户统计的可售能力，才能判断供给/需求何时真正宽松。

    价格下降同样有多种来源。成熟产品的正常降本、采购规模、客户议价、竞争者低价和产品组合变化会同时影响平均售价。若只看公司平均价格，可能把更多短距离或成熟产品占比误判为竞争冲击。研究需要同客户、同形态、同距离、同采购条款的成交价，才能识别新进入者带来的额外折价。

    架构变化既可能减少传统可插拔价值，也可能创造新的光引擎、封装和系统协同收入。若龙头成功进入新环节，传统模块占比下降不等于公司价值同比例下降；若新进入者借合作伙伴获得完整方案，也可能缩短学习时间。市场模型只给出架构比例的工作路径，财务结果仍要看每家公司实际捕获什么价值。

    三类不确定性应分开呈现：需求高低决定市场总量，客户认证与良率决定合格供给，产品组合和架构决定单位价值。把三者压成一个市场规模数字会隐藏风险来源，也无法解释为何端口增长而收入增速较低。未来更新应保持三条链分别可追溯。

    只有三条链的变化方向相互一致，才应显著调整长期行业结论；单一预测更新不足以完成重估。
    """,
    "qualification_upstream_constraints": """
    ## 哪些情况会改变上述判断

    客户认证不是一个永久标签，而是与产品、版本、器件、产线和客户项目绑定。更换DSP、激光器或工厂可能触发重新测试，同一供应商的铜缆资格也不能转移到光模块。研究应保存准入对象和版本，避免把一个公开清单放大成整个产品族或后续代际的证明。

    客户也可能主动帮助新供应商跨过门槛。为了供应安全、议价和多来源，头部客户可以提供共同设计、测试资源和初始订单；这会让有制造基础的立讯或比亚迪比普通创业公司更快爬坡。相反，若现有供应商能保证产能、性能和成本，客户没有必要为第二来源承担重新认证与质量风险。客户策略决定资格是否转成实质份额。

    上游替代不是即时的。高端器件短缺时，新进入者可能选择不同供应商或自研方案，但每次替代都会影响功耗、可靠性、固件和系统兼容，并可能延长认证。集团采购规模可以改善谈判，却不能消除单一来源和技术验证。只有器件清单、长期采购与产品版本能够证明供应稳定。

    政策信息也需要落到具体经营。逐案许可可能造成延迟、成本或设计替代，但没有公司产品与器件连接时，不能直接上调或下调进入概率。政策变化应通过供应交期、产品改版、客户认证和实际订单传导，而不是成为独立的情绪标签。公开资料无法识别具体许可时，应说明影响方向而不造出数量。

    验证顺序可以减少误判：先确认具体产品与器件版本，再确认使用该版本的合格产线，随后核对客户准入和重复订单，最后观察收入、毛利与保修。若中间任一环发生器件替换或产线迁移，后续证据需要重新连接，不能沿用旧资格。
    """,
    "recruitment_patent_capacity_audit": """
    ## 哪些情况会改变上述判断

    前置信号既会出现假阳性，也会出现假阴性。集团常规岗位、历史专利续展和通用设备采购可能与目标项目无关，造成假阳性；保密招聘、内部调岗、代工设备和未公开专利又可能让真实项目不可见，造成假阴性。因此这些材料最适合调整研究优先级和范围，不适合单独决定商业阶段。

    时间顺序可以提高解释力。岗位首次出现后，若随后出现专用设备、产品规格、伙伴测试和客户送样，多个独立环节共同推进才支持项目成熟；若多年只有重复招聘和同族专利，没有产品或客户，信号应衰减。专利申请通常早于公开授权，设备安装又早于收入，分析必须使用事件发生日而不是网页访问日。

    归属核验比数量更重要。一个岗位要确认雇佣法人、地点、业务线和技能，一个专利要确认权利人、应用场景与产品连接，一项设备要确认产线与速率，一个标准活动要确认公司角色。相同公告的转载、同一专利族和公司不同语言页面不能增加独立证明力。少量强连接证据比大量松散网页更有价值。

    产能必须从名义能力走到经济能力。设备数量只有结合节拍、良率、利用率、客户资格和订单才能转成可售产量；低良率或没有客户时，扩产反而增加折旧、存货和现金占用。招聘与专利解释公司是否准备，客户与可售良率决定准备是否成为经营结果，财务数据最后验证项目是否创造价值。

    综合来看，招聘与专利只能回答公司是否在准备，专用设备和良率说明准备是否形成可售能力，客户准入、重复订单与财务数据才验证项目是否创造价值。只有时间顺序、主体归属和产品连接同时成立，前置信号才能升级为商业化证据；否则应明确还缺哪一条连接。
    """,
}


def _target_names(
    targets_by_entity: dict[str, list[dict[str, Any]]], entity_key: str
) -> str:
    values = []
    for target in targets_by_entity.get(entity_key, []):
        ticker = _clean(target.get("ticker"))
        label = _clean(target.get("target_name"))
        values.append(f"{label}（{ticker}）" if ticker else label)
    return "、".join(values)


def build_human_entity_sections(
    *,
    entities: list[dict[str, Any]],
    targets: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    model: dict[str, Any],
    financial: dict[str, Any],
) -> list[dict[str, Any]]:
    """为每个研究实体生成独立回答，不公开因子矩阵或研究底稿清单。"""

    lookup = {source["ref"]: source for source in sources}
    usd_to_cny = _usd_to_cny(financial)
    targets_by_entity: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for target in targets:
        targets_by_entity[target["entity_key"]].append(target)

    byd3 = _probability(model, "3y", "byd_meaningful_entry")
    byd5 = _probability(model, "5y", "byd_meaningful_entry")
    lux3 = _probability(model, "3y", "luxshare_meaningful_entry")
    lux5 = _probability(model, "5y", "luxshare_meaningful_entry")
    probability_cases = model.get("probability_sensitivity", {}).get("cases", {})
    dependence_any = {
        horizon: [
            float(probability_cases[case]["horizons"][horizon]["at_least_one_entry"])
            for case in (
                "negative_dependence",
                "independent_events",
                "high_positive_dependence",
            )
        ]
        for horizon in ("3y", "5y")
    }
    threshold_any = {
        case: {
            horizon: float(
                probability_cases[case]["horizons"][horizon]["at_least_one_entry"]
            )
            for horizon in ("3y", "5y")
        }
        for case in ("loose_entry_threshold", "strict_entry_threshold")
    }
    qualification_delay_any = {
        horizon: float(
            probability_cases["qualification_delay"]["horizons"][horizon][
                "at_least_one_entry"
            ]
        )
        for horizon in ("3y", "5y")
    }
    market_2026 = _model_market_row(model, 2026)
    market_2029 = _model_market_row(model, 2029)
    market_2031 = _model_market_row(model, 2031)
    market_cases = model.get("market", {}).get("sensitivity_cases", {})
    market_demand_slow_2031 = market_cases.get("demand_slow_supply_base", {}).get("rows", [{}])[-1]
    market_demand_fast_2031 = market_cases.get("demand_fast_supply_base", {}).get("rows", [{}])[-1]
    market_supply_slow_2031 = market_cases.get("supply_slow_demand_base", {}).get("rows", [{}])[-1]
    market_supply_fast_2031 = market_cases.get("supply_fast_demand_base", {}).get("rows", [{}])[-1]
    inno_model = model["financial"]["companies"]["innolight"]
    eopt_model = model["financial"]["companies"]["eoptolink"]
    inno_base = _baseline_2031(inno_model)
    eopt_base = _baseline_2031(eopt_model)
    inno_weighted = _weighted_2031(inno_model)
    eopt_weighted = _weighted_2031(eopt_model)
    inno_market = _financial_company(financial, "innolight").get("market_snapshot", {})
    eopt_market = _financial_company(financial, "eoptolink").get("market_snapshot", {})

    bodies: dict[str, str] = {
        "byd_entry_risk": f"""
        # 比亚迪电子高速光模块进入风险

        ## 研究问题

        本页研究比亚迪电子能否在未来三至五年，从AI服务器、液冷、电源和大规模电子制造的相邻能力，跨到800G以上数据中心光模块的客户认证、重复交付和规模经营。直接相关的观察标的是{_target_names(targets_by_entity, 'byd_entry_risk')}。比亚迪电子是数据中心业务和潜在光模块经营结果的主要判断主体；比亚迪股份通过控股关系间接暴露，但母公司的汽车、功率半导体和资本开支不能自动算作比亚迪电子的模块能力。{_cite('BYD-S02')}

        ## 证据与数据

        2025年年报确认了一个真实而重要的起点：比亚迪电子已经形成服务器、液冷、电源和高速互联的一体化方案，AI基础设施收入约{_cny_yi_dual(9.43, usd_to_cny)}，服务器出货增长，液冷通过客户认证并进入小规模试产。它因此拥有数据中心客户入口、系统集成、采购组织、资金和规模制造，而不是从零开始。{_cite('BYD-S01')}{_cite('BYD-S04')}

        第一上海、招银国际和信达国际在2025年中期业绩会后留下了相互一致的产品路线线索：800G处于量产准备、具备量产能力或客户推广阶段，1.6T处于优化测试或量产准备；信达还记录了2025年内月出货5万只的目标和CPO研发计划。三份报告都指向同一次未公开的管理层交流，因此只能算一个底层信息源；“量产准备”“具备能力”“客户推广”“月出货目标”也不能合并成“已稳定批量交付”。{_cite('BYD-LEAD-FIRSTSH-20250901')}{_cite('BYD-LEAD-CMBI-20250902')}{_cite('BYD-LEAD-CINDA-20250905')}

        后续证据没有把这些目标闭环。2025年年报没有披露高速光模块规格、客户、实际出货、连续订单、专用光学产线、良率或收入；本报告核验的IDCE官方参展商名单只确认参展，NVIDIA ConnectX-8指定兼容清单也没有比亚迪光模块资格。2026年7月市场文章把路线扩写成向海外云客户或NVIDIA批量交付、1.6T完成验证和IDCE展示800G，未找到公司、客户、平台或展会原文确认。目前只能确认多家具名券商曾将800G、1.6T路线归因于同一次管理层交流；不能确认发行人已正式披露，也不能确认目标已兑现为规模经营。{_cite('BYD-S01')}{_cite('BYD-LEAD-IDCE-2026')}{_cite('BYD-S18')}{_cite('BYD-LEAD-TGB-20260718')}

        专利进一步说明集团不是只会通用装配。比亚迪股份与济南比亚迪半导体的连续申请涉及车载硅光网络、光收发、混频接收、故障检测、COB/BOSA及2.5D/3D光电封装；但申请主体不是比亚迪电子，应用仍以车辆为主。技术迁移可能提高长期成功率，却不能替代数据中心产品规格、客户验证和可售良率。{_cite('BYD-S14')}{_cite('BYD-PAT-CN122052920A')}{_cite('BYD-PAT-CN122362593A')}{_cite('BYD-PAT-CN121012567A')}

        ## 判断方法与结果

        研究按产品、客户认证、重复订单、专用产能和可分收入五个环节评估。券商转述只扩大上行情形，不改变最可能值或保守值；系统性车载光通信专利只使技术迁移的最可能值小幅上调；发行人正式产品规格、客户、专线和规模收入缺口继续限制结果。比亚迪的三年代表值约{_pct(byd3)}，估算范围{_pct(_probability_range(model, 'byd', '3y')[0])}至{_pct(_probability_range(model, 'byd', '3y')[2])}；五年代表值约{_pct(byd5)}，范围{_pct(_probability_range(model, 'byd', '5y')[0])}至{_pct(_probability_range(model, 'byd', '5y')[2])}。这是结构化研究判断，不是管理层目标兑现率或历史成功率。{_cite('MODEL-WORKPAPER')}

        ## 对相关标的意味着什么

        对比亚迪电子，光模块是潜在新增业务而非当前已确认利润来源。研究上不应因为服务器和液冷进展就提前计入模块收入，也不应忽略一旦产品与客户闭环可能带来的业务上限。对比亚迪股份，暴露主要来自控股权益和集团协同，汽车电子或半导体进展不能当作光模块业绩。只有经营主体明确的产品、客户和收入出现后，才适合把这一主题纳入盈利预测。

        对中际旭创和新易盛，比亚迪短期更像预期与供应链信号，而非已落地份额冲击。若公司只扩张AI服务器和液冷，龙头盈利不应下调；若出现800G以上产品和客户测试，才进入工程风险；若客户准入、连续订单和可售良率同时成立，才进入份额、价格和现金流模型。

        ## 本页结论

        根据现有证据，可以确认多家具名券商曾将800G/1.6T工程化和客户推广路线归因于同一次管理层交流；目前不能确认发行人已正式披露，也不能确认目标已兑现。客户资格、实际批量、良率、重复订单和可分收入仍没有直接证据。三年内把它作为确定性规模竞争者会高估进展；忽略这组有具名出处的待验证线索，则会低估上行风险。

        ## 如果想进一步研究，需要补充

        需要经营主体明确的产品规格、模块团队、耦合与测试设备、客户送样和认证、两个采购周期以上的订单、良率和可分收入。若信息受保密协议限制，至少需要设备投入、可售产能和分部经营数据交叉印证；集团招聘、专利和工厂宣传只能作为前置信号。
        """,
        "luxshare_entry_risk": f"""
        # 立讯精密高速光模块进入风险

        ## 研究问题

        本页判断立讯精密及Luxshare-Tech能否把已经公开的800G和1.6T产品、工程验证和有限交付，推进到全球头部客户准入、跨代重复订单和可分经营规模。直接观察标的是{_target_names(targets_by_entity, 'luxshare_entry_risk')}。与比亚迪相比，立讯已经越过“有没有产品”的问题，真正的不确定性集中在客户层级、良率、收入和利润捕获。

        ## 证据与数据

        Luxshare-Tech公开产品目录覆盖10G至1.6T，包含传统数字信号处理、线性可插拔、线性接收和有源回环等路线；800G规格、合作伙伴开发、测试记录以及行业互操作共同证明公司拥有真实的产品与工程活动。2025年8月投资者交流披露800G已经量产、1.6T处于客户验证；截至2026年7月18日的网页快照，官网当前页面另称1.6T进入早期商业化，但页面没有发布日期。因此，立讯已经高于概念、招聘或单次样机阶段，同时不能把官网素材时间当正式披露日期。{_cite('LX-OPTICS-CURRENT')}{_cite('LX-TRANSCEIVER-CURRENT')}{_cite('LX-800G-LPO-SPEC')}{_cite('LX-IR-202508')}{_cite('LX-FRO-2026')}{_cite('OIF-OFC2026')}

        最大限制来自公司披露没有形成一致的客户图景。2024年年报提到头部AI客户测试和多家国际头部客户量产交付；2025年8月交流又称800G和1.6T主要面向中小数据中心，尚无头部客户明确商务机会；2026年5月公司继续强调光连接业务仍处起步阶段。三种说法可能对应不同产品、地区和时点，也可能反映项目变化，但公开资料不足以判断具体原因。研究因此确认产品和有限商业化，同时保留对全球客户的明显折扣。{_cite('LX-ANNUAL-2024')}{_cite('LX-IR-202508')}{_cite('LX-IR-20260507')}

        平台侧证据也要严格区分。OIF参与和伙伴测试提高工程可信度，却不是客户采购；NVIDIA公开清单里可见立讯200G铜缆，并不能证明800G以上光模块进入同一平台。集团通信制造、连接器和系统集成能力有助于产能爬坡，但光模块线的耦合、烧机、返工、保修和核心器件采购仍需独立核验。{_cite('NVIDIA-CX8-VALIDATED')}{_cite('KEYSIGHT-LX-202410')}

        ## 判断方法与结果

        产品、工程和发行人交付证据把立讯的三年代表值推到约{_pct(lux3)}，估算范围{_pct(_probability_range(model, 'luxshare', '3y')[0])}至{_pct(_probability_range(model, 'luxshare', '3y')[2])}；五年约{_pct(lux5)}，范围{_pct(_probability_range(model, 'luxshare', '5y')[0])}至{_pct(_probability_range(model, 'luxshare', '5y')[2])}。总进入明显高于全球头部客户路径，反映近期更容易形成中国或区域客户规模。范围较宽不是计算误差，而是客户披露冲突、收入和良率不可分造成的认识不确定性。{_cite('MODEL-WORKPAPER')}

        ## 对相关标的意味着什么

        对立讯精密，光模块有望补充高速连接业务，但公开资料还不足以量化其对集团收入和利润的贡献。投资研究不应把官网产品数量直接转成收入，也不应把“起步阶段”误解成完全没有交付。真正抬高盈利价值的证据是全球客户准入、跨代重复订单、专线良率和分部利润。

        对中际旭创和新易盛，立讯先在区域客户形成第二来源更可能带来局部报价、订单分流和客户议价压力；只有进入全球头部客户并持续交付，才足以改变长期份额。若立讯低价进入却无法维持器件供应和良率，冲击可能短暂；若客户主动扶持第二来源并跨两代采购，风险会明显放大。

        ## 本页结论

        根据现有证据，可以认为立讯已经是商业化前段的真实进入者，产品与工程进度明显领先比亚迪；但目前没有足够直接证据证明它已在全球头部客户形成稳定、可扩、跨代的份额。三年看区域规模，五年看全球客户，是当前最符合证据的时间划分。

        ## 如果想进一步研究，需要补充

        需要解释2024年至2026年的客户口径差异，并取得客户侧准入、连续订单、按速率收入、模块线良率、可售产能、返工和保修成本。供应商或客户原始材料的证明力高于发行人单次表述；产品发布和伙伴演示不再是最稀缺的信息。
        """,
        "innolight_terminal_risk": f"""
        # 中际旭创面对新进入者时的盈利风险

        ## 研究问题

        本页研究比亚迪或立讯形成规模后，中际旭创的客户份额、价格、利润和现金流会怎样变化，以及当前估值是否有足够缓冲。直接观察标的是{_target_names(targets_by_entity, 'innolight_terminal_risk')}。这里讨论的是新增进入者带来的额外影响，不把正常代际降价、其他竞争者、AI需求变化和CPO价值迁移全部归因于比亚迪或立讯。

        ## 证据与数据

        中际旭创的防线来自多代高速产品量产、客户共同开发、海外交付和较大的绝对现金流。2025年公司收入{_cny_yi_dual(382.40, usd_to_cny)}、归母净利润{_cny_yi_dual(107.97, usd_to_cny)}、经营现金流{_cny_yi_dual(108.96, usd_to_cny)}、购建长期资产支出{_cny_yi_dual(27.60, usd_to_cny)}，简单自由现金流约{_cny_yi_dual(81.36, usd_to_cny)}；光通信收发模块毛利率约42.61%。产能从2024年的2,088万只增至2025年的2,806万只，说明公司仍在扩张而不是收缩。{_cite('SRC-INNO-AR25')}

        脆弱点同样明确。前五大客户占收入75.98%，第一大客户占24.06%，单一大客户引入第二供应商会同时影响份额、价格和营运资本。公司2026年7月17日市值约{_cny_yi_dual(inno_market['market_cap_cny'], usd_to_cny, cny_digits=0)}，市盈率{float(inno_market['pe_ttm']):.2f}倍、市净率{float(inno_market['pb']):.2f}倍、市销率{float(inno_market['ps_ttm']):.2f}倍，估值要求高增长和高利润继续兑现。扩产和研发可以防守份额，也会在客户切换或需求低于预期时放大现金占用。{_cite('FIN-INNOLIGHT')}{_cite('SRC-INNO-FUND26')}

        产品路线决定冲击是否永久。若800G、1.6T和后续代际继续由龙头共同设计并保持良率，新进入者在区域客户的有限供给可能被市场增长吸收；若客户把全球份额持续转给第二来源，同时同规格价格出现额外下降，收入和毛利会一起受压。CPO或光引擎提高并不等于中际旭创必然失去价值，关键是公司能否进入新架构的光引擎、封装或模块环节。{_cite('SRC-INNO-1600')}

        ## 估算方法与结果

        模型先建立冻结本模型新增竞争与架构冲击的2031年参考路径，再按年度进入概率加入份额、额外降价、良率和现金占用。该路径以市场聚合预期为起点，可能已包含部分竞争影响，不是纯无竞争反事实。当前参考收入约{_cny_yi_dual(inno_base['revenue_cny_yi'], usd_to_cny, cny_digits=0)}、净利润约{_cny_yi_dual(inno_base['net_income_cny_yi'], usd_to_cny, cny_digits=0)}、现金流约{_cny_yi_dual(inno_base['fcf_cny_yi'], usd_to_cny, cny_digits=0)}；在全部收入都承受高速产品冲击的压力上限下，年度概率传导后的2031年结果约为{_cny_yi_dual(inno_weighted['revenue_cny_yi'], usd_to_cny, cny_digits=0)}、{_cny_yi_dual(inno_weighted['net_income_cny_yi'], usd_to_cny, cny_digits=0)}和{_cny_yi_dual(inno_weighted['fcf_cny_yi'], usd_to_cny, cny_digits=0)}。现金流相对损失明显大于收入，首先来自收入与利润率受压，防守性扩产和营运资本进一步放大结果；全收入受压时，后两项约占2031年现金流损失四成。{_cite('MODEL-WORKPAPER')}

        这一绝对金额不能直接与市值比较。公开资料尚未给出未来800G以上收入占总收入的准确比例，而参考路径又要求2025至2031年收入年均增长约43%，未来需求增长速度对结果影响很大。模型能说明“客户突破加额外降价会使现金流比收入更敏感”，却不能证明全部收入都会受同等冲击，也不能在缺少净债务、其他资产、少数股东和稀释股本时给出每股价值。

        ## 对标的意味着什么

        区域第二来源出现时，首先观察同规格价格和大客户份额，不应仅因竞争者发布产品就永久下调盈利。全球客户准入、连续两个采购周期和中际旭创自身毛利、现金流连续走弱，是把风险升级为长期盈利中枢下修的必要组合。若1.6T及后续产品保持客户资格、海外产线顺利爬坡且现金流恢复，说明防线仍有效。

        ## 本页结论

        根据现有数据，中际旭创拥有更强的规模、产品和现金流防线，但高客户集中和高增长估值会放大客户切换的影响。立讯已足以进入风险折扣，尚不足以证明长期利润已经确定恶化；当前财务结果应视为压力上限而非目标价依据。

        ## 如果想进一步研究，需要补充

        需要按客户、速率、地区和产品形态拆分收入、份额、毛利与成交价，并取得海外线资格、良率、存货、应收账款和分业务资本开支。完成净现金、少数股东、非经营资产和稀释股本桥接后，才适合把经营压力转成每股估值。
        """,
        "eoptolink_terminal_risk": f"""
        # 新易盛面对新进入者时的盈利风险

        ## 研究问题

        本页研究立讯或比亚迪形成有意义规模后，新易盛能否依靠高端产品、海外客户和较高毛利维持盈利，以及其较小的绝对现金流缓冲是否会放大竞争冲击。直接观察标的是{_target_names(targets_by_entity, 'eoptolink_terminal_risk')}。分析把新进入者影响与正常降价、需求变化和架构迁移分开，避免把全部波动归因于一个竞争主题。

        ## 证据与数据

        新易盛2025年收入{_cny_yi_dual(248.42, usd_to_cny)}、归母净利润{_cny_yi_dual(95.32, usd_to_cny)}、经营现金流{_cny_yi_dual(77.01, usd_to_cny)}、购建长期资产支出{_cny_yi_dual(13.20, usd_to_cny)}，简单自由现金流约{_cny_yi_dual(63.81, usd_to_cny)}；光互联产品毛利率47.81%，境外收入占96.16%。公司收入、利润和现金流相较2024年显著扩张，证明其高端产品和海外交付处在强势阶段。{_cite('SRC-EOPT-AR25')}

        产品管线提供多条防御路径，但阶段不能混写。2025年年报显示1.6T高速模块完成设计与验证并通过验收，LRO模块和硅光PIC研究进入小批量阶段，1.6T线性可插拔模块仍处样品测试与评估。内部验收、小批和前期样品不是同一商业阶段；它们共同说明公司在为代际和架构变化准备，却不能证明所有路线都已量产。泰国制造子公司提供海外交付选择，客户资格和分产品产能仍需单独核验。{_cite('SRC-EOPT-AR25')}

        风险来自客户集中、现金转换和较小绝对缓冲。前五大客户收入占72.34%，第一大客户占22.97%；若同一海外大客户导入第二供应商，份额和价格可能同时变化。新易盛2024年简单自由现金流曾为负，2025年才显著恢复，说明扩产和营运资本可以让现金流比利润更波动。2026年7月17日公司市值约{_cny_yi_dual(eopt_market['market_cap_cny'], usd_to_cny, cny_digits=0)}，市盈率{float(eopt_market['pe_ttm']):.2f}倍、市净率{float(eopt_market['pb']):.2f}倍、市销率{float(eopt_market['ps_ttm']):.2f}倍，同样不是可以忽略增长风险的估值。{_cite('FIN-EOPTOLINK')}

        ## 估算方法与结果

        模型对新易盛使用与中际旭创相同的收入传导逻辑，但保留公司自身利润率和冲击敏感度。冻结本模型新增竞争与架构冲击的2031年参考收入约{_cny_yi_dual(eopt_base['revenue_cny_yi'], usd_to_cny, cny_digits=0)}、净利润约{_cny_yi_dual(eopt_base['net_income_cny_yi'], usd_to_cny, cny_digits=0)}、现金流约{_cny_yi_dual(eopt_base['fcf_cny_yi'], usd_to_cny, cny_digits=0)}；该路径以市场聚合预期为起点，可能已包含部分竞争影响，不是纯无竞争反事实。在全部收入承受高速产品冲击的压力上限下，年度概率传导后的2031年结果约为{_cny_yi_dual(eopt_weighted['revenue_cny_yi'], usd_to_cny, cny_digits=0)}、{_cny_yi_dual(eopt_weighted['net_income_cny_yi'], usd_to_cny, cny_digits=0)}和{_cny_yi_dual(eopt_weighted['fcf_cny_yi'], usd_to_cny, cny_digits=0)}。{_cite('MODEL-WORKPAPER')}

        新易盛在压力模型中的现金流降幅通常大于中际旭创，原因是较小绝对规模、客户集中与扩产现金占用共同作用。这只是模型中的方向判断，不代表两家公司真实受损概率完全相同。当前高速产品受影响收入比例没有闭环，多个现金占用输入又来自情景假设，因此不能把个位数精度当预测；正常化现金流为负的尾部情景也不使用永续增长估值。

        ## 对标的意味着什么

        新易盛的较高毛利和多路线产品可能在需求强、代际升级顺利时吸收区域竞争；海外客户集中和较小现金缓冲则会在客户切换时放大波动。最重要的验证不是竞争者是否参展，而是泰国等海外线资格、1.6T和新架构从样品到重复量产的推进、同规格价格以及应收与存货是否恶化。若毛利维持而现金流短期下降，应先判断是否来自扩产；若份额、价格、毛利和现金流连续同向恶化，才支持长期中枢下修。

        ## 本页结论

        根据现有数据，新易盛仍有高端产品、海外交付和较高毛利防线，但客户集中和较小绝对现金流缓冲使其对全球客户切换更敏感。当前竞争压力值得进入估值折扣，却不足以证明其长期盈利确定受损，也不足以给出公允价值或无条件买卖判断。

        ## 如果想进一步研究，需要补充

        需要按速率、客户和地区拆分收入与毛利，核验泰国及其他海外线资格、可售产能、良率和重复订单，并把存货、应收、资本开支和营运资本按业务拆开。完成净现金、其他资产和稀释股本桥接后，再将经营情景传导到每股价值。
        """,
        "entity_scope_and_stage_definitions": f"""
        # 主体边界与商业化阶段

        ## 研究问题与范围

        本页解决两个基础问题：哪些公司和子公司才是实际经营主体，以及什么证据才算高速光模块真正进入。若主体划错，母公司的资产、招聘或客户会被错误迁移到子公司；若阶段划得太宽，产品发布、互操作和一次小批会被误写成规模竞争。研究对象限定为800G以上数据中心光模块及与其直接相关的光引擎，不把服务器、液冷、铜缆、车载光学或单一器件直接计入完整模块。

        ## 证据与方法

        比亚迪部分以比亚迪电子为数据中心业务和潜在模块经营主体。控股与并表关系可以从公开披露确认，但比亚迪股份的汽车、半导体和集团资本投入不能自动成为比亚迪电子模块资产。2025年年报确认服务器、液冷、电源与高速互联方案，却没有把高速互联具体拆成800G以上模块，因此只能确认相邻数据中心能力。{_cite('BYD-S01')}{_cite('BYD-S02')}

        立讯部分区分立讯精密集团与Luxshare-Tech产品和项目。产品目录、800G规格、合作伙伴和互操作可以证明产品与工程活动；集团通信制造、资本开支和客户关系只能解释规模化上限，不能代替模块线的良率、收入和利润。立讯已经越过产品门槛，但不同披露对全球头部客户和商业阶段的描述没有完全一致，因而客户与经营阶段仍需单独判断。{_cite('LX-TRANSCEIVER-CURRENT')}{_cite('LX-IR-202508')}

        “有意义进入”要求四个环节共同成立：经营主体可归属的产品；大型客户或平台正式准入；至少两个采购或披露周期的重复批量；可售产能、良率和收入达到能影响行业价格的规模。四个环节有先后关系，却不能相互代替。互操作领先于客户采购，首批订单领先于重复规模，名义产能领先于合格供给。中国客户体系和全球头部客户分别判断，两条路径可以重叠，地域没有公开的项目保留在总进入中。

        经营规模采用一个可复核的代表门槛：年化相关收入达到{_cny_yi_dual(10, usd_to_cny, cny_digits=0)}、全球市场份额达到1%或中国市场份额达到5%，三项满足其一；同时还要覆盖两个客户，或在同一客户完成跨代产品延续。门槛不是行业统一标准，而是为了避免把一次样品或小批订单误写成足以影响竞争格局的规模事件。后续若取得客户采购额和真实市场规模，应直接替换这组研究口径。

        历史案例帮助识别路径边界。收购Acacia或Cloud Light时，买方同时获得成熟产品、团队与客户，不能直接类比内部从零建设；Intel内部孵化的可插拔模块后来选择剥离，说明技术能力不保证长期经营；Fabrinet的专业光学制造可以长期成功，但它没有接受“成为自有完整模块供应商”这一事件检验。{_cite('SRC-CISCO-ACACIA21')}{_cite('SRC-LITE-CLOUD23')}{_cite('SRC-INTEL-Q323')}{_cite('SRC-FN-10K24')}

        ## 分析与回答

        这一判断方法让比亚迪和立讯得到不同结论，而不是把所有证据压成“有或没有”。比亚迪确认的是数据中心相邻业务与制造条件，完整模块产品尚无直接证据；立讯确认的是产品、工程和有限商业化，全球客户与经营规模尚未闭环。公开未见客户名称不等于客户不存在，可能受保密安排影响，但在缺乏客户侧或持续订单证据时，不能把项目提前写成已经确认的商业事实。

        主体与阶段还决定财务传导。只有归属于经营主体并达到重复规模的项目才进入份额冲击；集团制造能力只影响进入速度，不直接形成收入；只有全球头部客户突破才触发更强的价格与份额压力。这样可以防止服务器收入、铜缆平台记录或器件专利被错误放大为完整模块竞争。

        ## 本页结论

        根据现有证据，最合理的主体判断是：比亚迪电子承接比亚迪数据中心相邻业务，立讯精密与Luxshare-Tech共同构成产品和制造体系；最合理的阶段判断是：比亚迪处在前置准备，立讯处在商业化前段。只有产品、客户、重复批量和经营规模共同成立，才足以改变龙头份额和盈利。

        ## 如果想进一步研究，需要补充

        需要经营法人、产品归属、团队组织、产线设备、客户准入、连续订单和分部财务的同一时间线。若项目跨母子公司或合资平台，还应核验并表比例、技术与客户是否真正转移；任何集团层数字都不能在没有连接证据时直接填入模块经营主体。
        """,
        "probability_method_and_baserate": f"""
        # 进入概率怎样从证据得到

        ## 研究问题与范围

        本页解释比亚迪和立讯三年、五年判断如何形成，以及为什么这些数字不能被理解成历史频率。研究事件仍是产品、客户准入、重复批量和经营规模共同成立；中国客户与全球头部客户分别判断。方法的目的不是制造小数点精度，而是把证据、认识不确定性和财务情景放在同一可复核框架里。

        ## 历史材料能告诉我们什么

        九个历史案例包含收购成熟平台、内部孵化、产品承接、联合开发、专业制造和器件平台，进入方式与观察终点都不一致。Cisco收购Acacia与Lumentum收购Cloud Light说明成熟产品、团队和客户一并转移可以缩短路径；Intel后来剥离可插拔模块说明内部技术并不保证持久经营；Fabrinet和Marvell的制造或器件邻接可以成功，却不能回答完整模块进入。未决项目也不能提前记成成功或失败。{_cite('SRC-CISCO-ACACIA21')}{_cite('SRC-LITE-CLOUD23')}{_cite('SRC-INTEL-Q323')}{_cite('SRC-FN-10K24')}{_cite('SRC-MRVL-INPHI21')}

        因此，历史案例只支持方向性判断：收购成熟平台与内部建设不是同一路径；精密制造和器件能力不能代替客户认证；宣布进入不等于形成持久规模。本报告没有把小样本比例当作公司概率起点，也不展示会造成统计有效性错觉的区间公式。

        ## 计算方法

        对每家公司和每个期限，研究根据产品、客户、重复订单、专用产能和可分收入，设定保守值、最可能值和上限。财务模型需要一个代表值时，用三者相加后除以三。例如比亚迪三年使用{_pct(_probability_range(model, 'byd', '3y')[0])}、{_pct(_probability_range(model, 'byd', '3y')[1])}和{_pct(_probability_range(model, 'byd', '3y')[2])}，代表值约{_pct(byd3)}；立讯三年使用{_pct(_probability_range(model, 'luxshare', '3y')[0])}、{_pct(_probability_range(model, 'luxshare', '3y')[1])}和{_pct(_probability_range(model, 'luxshare', '3y')[2])}，代表值约{_pct(lux3)}。随机抽样只把这些范围传导到“至少一家”“两家同时”等联合问题，不会增加新证据。{_cite('MODEL-WORKPAPER')}

        公司间不是完全无关。两者共同受AI需求、核心器件供给、客户多供应商策略和架构切换影响，因此联合结果允许同向变化。基本关系是“至少一家进入等于两家公司各自进入之和，再减去两家同时进入”。当前结果为至少一家约三年{_pct(_probability(model, '3y', 'at_least_one_entry'))}、五年{_pct(_probability(model, '5y', 'at_least_one_entry'))}；两家同时约三年{_pct(_probability(model, '3y', 'both_entry'))}、五年{_pct(_probability(model, '5y', 'both_entry'))}。全球客户路径更低，说明区域进入与全球规模不是同一个事件。

        由于找不到可以直接估计两家公司联动程度的历史数据，报告把“共同受益或共同受阻”和“争夺相同客户、器件”设成不同强度重新计算。至少一家进入的三年结果约在{_pct(min(dependence_any['3y']))}—{_pct(max(dependence_any['3y']))}之间，五年约在{_pct(min(dependence_any['5y']))}—{_pct(max(dependence_any['5y']))}之间。关系假设会改变具体数字，但没有改变“三年接近一半、五年明显高于三年”的方向。

        事件定义与客户认证时点带来的影响更大。若把规模门槛放宽为年化收入{_cny_yi_dual(5, usd_to_cny, cny_digits=0)}、全球份额0.5%或中国份额3%，至少一家进入约为三年{_pct(threshold_any['loose_entry_threshold']['3y'])}、五年{_pct(threshold_any['loose_entry_threshold']['5y'])}；若提高到年化收入{_cny_yi_dual(20, usd_to_cny, cny_digits=0)}、全球份额2%或中国份额10%，则降至三年{_pct(threshold_any['strict_entry_threshold']['3y'])}、五年{_pct(threshold_any['strict_entry_threshold']['5y'])}。若客户认证和重复交付整体延后，三年结果进一步降至约{_pct(qualification_delay_any['3y'])}，五年仍约{_pct(qualification_delay_any['5y'])}。这说明当前公开资料不能给出可信的经验概率，报告数字只能作为统一定义下的工作判断。

        ## 分析与回答

        比亚迪的中心较低，原因是数据中心相邻业务成立而模块产品、客户与专线没有闭环；五年较高，是因为自建、合作和收购有更多时间。立讯的中心较高，原因是产品、工程和有限交付形成连续证据；全球客户路径被后续披露冲突、收入和良率不可分压低。概率范围表达的是我们对证据的认识，不是重复试验的置信区间。

        模型最需要警惕的是“精确运算掩盖主观输入”。抽样次数增加可以降低数值误差，却不能回答区间端点为什么是某个百分比。公开报告因此只保留用于测算的代表值与完整估算范围，不展示多个分位数字，也不把每条网页机械加减百分点。新证据出现时，只更新对应公司、期限和地域。

        ## 本页结论

        根据现有证据，立讯三年和五年形成有意义进入的代表值约{_pct(lux3)}和{_pct(lux5)}，比亚迪约{_pct(byd3)}和{_pct(byd5)}；这些数值用于公司间比较和财务传导，不是统计事实。最大不确定性来自客户、良率和收入，而不是联合公式或抽样精度。

        ## 如果想进一步研究，需要补充

        若要把工作判断升级为经验估计，需要重新建立同一进入方式、同一事件定义、同一观察期限并区分未决与失败的历史样本；同时补齐两家公司客户阶段、重复订单、可售产能和收入，以便用真实里程碑替换当前宽范围。
        """,
        "industry_demand_supply_model": f"""
        # 2026—2031年高速光互联供需与架构

        ## 研究问题与范围

        本页研究AI数据中心800G、1.6T和3.2T高速互联需求能否吸收新增合格供给，以及LPO、LRO、CPO和光引擎会怎样改变价值归属。模型覆盖2026至2031年，端口、正常代际价格和收入分别估算；“合格供给”必须经过产品、良率和客户认证约束，名义厂房和设备不直接计入可售供给。

        ## 数据与方法

        表中的需求与价格估算综合行业预测、客户平台节奏、产品规格和公开价格。2026年模型约{_ports_million_cn(market_2026['total_ports_million'])}高速端口、{_usd_bn_cn(market_2026['normal_market_revenue_usd_bn'])}市场收入；2029年约{_ports_million_cn(market_2029['total_ports_million'])}、{_usd_bn_cn(market_2029['normal_market_revenue_usd_bn'])}；2031年约{_ports_million_cn(market_2031['total_ports_million'])}、{_usd_bn_cn(market_2031['normal_market_revenue_usd_bn'])}。LightCounting同时保留高增长与颠簸情景，说明远期需求不能只用单一路径表达。{_cite('SRC-LC-MAR26')}{_cite('SRC-CIGNAL-4Q24')}{_cite('MODEL-WORKPAPER')}

        端口增长快于市场收入，是因为成熟速率正常降价、新速率以较高单价接棒。海光芯正文件显示，800G以上平均售价从2024年2,443元降至2025年1,557元，并把变化同时归因于产品成熟、竞争、大批量采购和早期小批高价基数。这一证据不代表所有厂商或距离的价格，却说明必须把正常代际降价与新进入者额外折价分开。{_cite('SRC-HKEX-ASP26')}

        模型中的合格供给/需求从2026年约{_number(market_2026['qualified_supply_demand_ratio'], 2)}倍，提高到2029年约{_number(market_2029['qualified_supply_demand_ratio'], 2)}倍和2031年约{_number(market_2031['qualified_supply_demand_ratio'], 2)}倍。这不是已发生的行业统计，而是用资格和爬坡约束后的工作路径。若客户认证慢、核心器件短缺或1.6T良率爬坡延后，宽松供给会推迟；若需求下修或多家第二来源同时通过，报价压力会提前。

        综合慢/快路径会同时调整需求和供给，不能证明远期过剩必然发生。把两侧拆开后，2031年在中性供给下，需求偏快与偏慢对应的供给/需求约为{_number(market_demand_fast_2031['qualified_supply_demand_ratio'], 2)}倍和{_number(market_demand_slow_2031['qualified_supply_demand_ratio'], 2)}倍；在中性需求下，供给爬坡偏慢与偏快对应约{_number(market_supply_slow_2031['qualified_supply_demand_ratio'], 2)}—{_number(market_supply_fast_2031['qualified_supply_demand_ratio'], 2)}倍。强需求情景接近平衡，因此公开结论只把供给宽松视为需要监控的中性路径，不写成确定拐点。

        架构按价值链单独判断。LPO和LRO仍保留可插拔形态，主要改变功耗、线性链路和模块设计；CPO或光引擎提高时，价值可能向交换芯片、光引擎和先进封装迁移。OIF推进3.2T CPO项目说明产业在准备新架构，但标准和演示不等于客户规模部署。龙头能否参与新架构、进入者能否借架构切换缩短学习曲线，决定了架构变化是防线还是威胁。{_cite('SRC-OIF-2025')}

        ## 分析与回答

        市场增长意味着新增供应不必然造成行业收入下降。三年内若1.6T需求快速上升、可售供给仍受资格限制，立讯区域交付可能被增量需求吸收；五年内合格供给持续超过需求，客户多供应商策略和新进入者规模才更容易转成额外价格压力。对龙头而言，份额下降与绝对收入下降不是一回事，但高估值对增长速度敏感，即使绝对收入上升也可能出现估值下修。

        公开资料目前无法把公司收入与全球800G以上市场做同产品边界对账。龙头总收入包含不同速率、距离、地区和其他业务，不能与模型的全球高速市场直接相除。财务专题因此把全收入冲击标成压力上限，并用受影响收入比例做范围，而不是让行业市场和公司收入互相证明。

        ## 本页结论

        根据当前模型，高速互联需求到2031年仍显著增长，但合格供给/需求可能在中后期持续超过1。新增进入者近期更可能造成局部议价，远期才可能与供给宽松和架构迁移共同压低利润。需求、资格和价值捕获必须同时观察，不能只看名义产能。

        ## 如果想进一步研究，需要补充

        需要按速率、距离、形态、客户和地区建立出货、成交价与合格供给数据；补齐1.6T和3.2T真实部署、客户认证滞后、核心器件瓶颈以及龙头在LPO、LRO、CPO和光引擎中的收入捕获。只有同口径数据才能判断新增供给究竟被需求吸收还是转成额外降价。
        """,
        "qualification_upstream_constraints": f"""
        # 客户认证、上游器件与政策约束

        ## 研究问题与范围

        本页研究为什么有产品不等于能够规模供货，以及客户准入、DSP、激光器、PIC、制造良率和出口许可会怎样限制比亚迪与立讯的进入速度。重点不是罗列供应商，而是识别哪一环会把样品、演示或发行人“量产”挡在重复商业订单之外。

        ## 客户认证证据

        高速模块通常经历样品、可靠性、系统互操作、客户准入、小批量、重复订单和跨代延续。伙伴联合开发和OIF演示能够证明接口与工程能力，却不代表客户采购；平台清单必须核对产品类型。NVIDIA清单中可见立讯200G铜缆，不能据此写成800G以上光模块资格。立讯发行人称800G量产、1.6T验证，说明商业阶段领先比亚迪，但全球头部客户仍需客户侧或持续订单闭环。{_cite('OIF-OFC2026')}{_cite('NVIDIA-CX8-VALIDATED')}{_cite('LX-IR-202508')}

        客户保密会使公开研究低估进度，但解决办法是扩大判断范围，而不是用匿名传闻补齐客户。可接受的替代证据包括客户或平台正式清单、连续两个采购周期的订单、可售产能与收入同步增长、供应商和设备侧对同一项目的独立印证。一次“国际客户”表述或伙伴演示的证明力低于这些材料。

        ## 上游与制造约束

        高速模块依赖DSP、激光器、PIC、驱动、探测器、连接器和高精度封装，并需要耦合、烧机、可靠性和系统测试。Coherent披露部分投入来源有限或单一，Marvell等上游的产品节奏也会影响新进入者爬坡。总装规模可以提高采购议价，却不能确保高端器件随时可得；缺料会延迟认证，替代器件又可能触发重新验证。{_cite('SRC-COHR-10K25')}{_cite('SRC-MRVL-10Q25')}

        良率是连接产品与经济性的桥。样品能工作不代表数万只产品可稳定交付，名义设备数也不代表合格产能。低良率会同时提高材料损耗、返工、保修和交付不确定性，使低价进入难以持续。立讯和比亚迪都有大规模制造基础，但公开资料没有给出模块专线良率、返工和可售产能，因此财务模型不能把集团制造规模直接转成利润。

        ## 政策与架构影响

        美国对相关半导体出口许可采用逐案审查，可能影响高端器件获取、交货和替代设计，但政策文本不能直接告诉我们某家公司具体订单是否获批。政策只在实际器件来源、产品设计、认证或交付发生变化时进入公司判断。{_cite('SRC-BIS-JAN26')}

        LPO、LRO和CPO可能减少部分传统DSP或模块价值，也可能提高共同设计、光引擎和先进封装门槛。对进入者而言，架构切换既是绕开旧代产品积累的窗口，也是更复杂的客户协同要求。不能因为公司展示某一新架构，就假设它同时跨过器件供给、良率和客户准入。

        ## 分析与回答

        立讯当前的核心约束已从“产品是否存在”转向“全球客户与经营规模能否持续”；比亚迪仍需先证明经营主体可归属的产品，再进入客户与上游约束。两者若只获得区域项目，可能带来局部价格压力；若核心器件稳定、良率爬坡和客户重复订单同时闭环，才会形成长期份额。上游短缺也可能保护龙头，使客户不愿把大量份额交给尚未验证的新来源。

        ## 本页结论

        根据现有证据，客户准入和模块线良率是从工程活动到行业竞争的两个最重要关口，上游器件和政策决定它们能否按时完成。伙伴演示、产品目录和集团制造基础都不能单独替代这两道关口。

        ## 如果想进一步研究，需要补充

        需要客户侧准入与重复订单、核心器件清单和长期采购安排、专线设备、良率、返工、保修和可售产能；同时按具体产品核验出口许可和替代器件。任何平台证据都要先确认产品类型、速率和版本，防止把铜缆、器件或其他业务迁移成光模块资格。
        """,
        "recruitment_patent_capacity_audit": f"""
        # 招聘、专利与产能证据怎样用于判断

        ## 研究问题与范围

        本页研究招聘、专利、工厂自动化、标准参与和产能信息能否提前识别高速光模块进入，以及如何避免把前置信号写成商业事实。这些材料有价值，因为客户和项目可能受保密限制；它们也容易误导，因为集团岗位、同族专利、伙伴活动和通用工厂能力都可能与目标产品没有直接归属。

        分析方法是先按原始岗位和专利族去重，再核对经营主体、产品、事件日期与后续客户或产线证据；只有不同环节形成连续时间链，才提高商业化判断。单一网页只决定补证优先级，不直接进入收入、份额或盈利估算。

        ## 招聘与团队

        比亚迪集团招聘覆盖半导体、通信和AI数据中心相关方向，说明公司有配置技术资源的可能；但公开岗位没有完整闭环到比亚迪电子高速模块项目、团队人数和专线计划。因此招聘只能支持“项目准备度可能上升”，不能证明产品或量产。立讯的光通信产品与耦合、测试岗位线索更接近模块工程，且与公开产品矩阵相互印证，但招聘数量仍不能代替在岗团队、产品阶段和交付结果。{_cite('BYD-S06')}{_cite('JOB-ZHAOPIN-COUPLING')}{_cite('LX-TRANSCEIVER-CURRENT')}

        招聘分析应记录首次出现、持续时间、经营法人、岗位地点、具体技能和对应产品，并对转载去重。短期大量岗位可能是新建项目，也可能是集团常规招聘；岗位消失可能表示招满，也可能表示项目调整。没有公司确认时，不能仅从招聘网页推断团队规模或量产日期。

        ## 专利、标准和技术资产

        按申请人、专利族和应用场景核验，可以确认比亚迪集团存在连续而非零散的车载光通信研发。下面只保留最能区分“技术储备”和“数据中心商业化”的四件代表性申请。

        | 专利记录 | 申请主体 | 它实际证明了什么 | 它不能证明什么 |
        |---|---|---|---|
        | CN121644261A | 比亚迪股份 | 车载通信系统中的光发射/接收模块，速率列示5/10/25/50/100Gbps | 800G/1.6T数据中心形态、客户或量产 |
        | CN122052920A | 比亚迪股份 | 模块级本振光与光混频接收方案 | 数据速率、数据中心应用和比亚迪电子产品归属 |
        | CN122362593A | 比亚迪股份 | 终端与光模块分置，涉及DFB/VCSEL、PIN/APD、COB/BOSA和2.5D/3D封装 | CPO产品、服务器客户、专线良率或批量交付 |
        | CN121012567A | 济南比亚迪半导体 | 车载光通信系统；同时纠正市场文章的申请人混写 | 比亚迪股份或比亚迪电子的800G产品 |

        这些专利共同提高的是“集团具备硅光、收发、封装和车载光网络研发能力”的可信度，不是“比亚迪电子已经完成数据中心光模块商业化”。公开检索也没有在比亚迪电子常用运营子公司名下找到可直接归属的800G/1.6T数据中心光模块专利。专利申请、授权、产品定型和客户量产是不同日期与事件，不能按专利数量机械上调商业判断。{_cite('BYD-S14')}{_cite('BYD-PAT-CN122052920A')}{_cite('BYD-PAT-CN122362593A')}{_cite('BYD-PAT-CN121012567A')}

        立讯的产品、合作伙伴和OIF参与构成更直接的数据中心工程证据，仍只支持产品和互操作接近度，不能替代客户采购。标准成员身份与具体方案采用也不同，不能和专利放在一条“进度”时间线上简单比较。{_cite('OIF-OFC2026')}

        专利研究要按同族去重，并看权利人、发明人、应用场景、速率、封装与产品之间是否有连接；标准活动要看具体实现协议、测试项目和参与角色。只有专利、团队、设备、产品和客户在同一主体与时间段相互印证，技术资产才真正提高商业化判断。

        ## 工厂与产能

        比亚迪电子智慧工厂的机器人覆盖、精密装配和视觉检测证明大规模自动化基础；立讯的通信制造与系统集成说明其具备扩产组织能力。但高速光模块可售产能取决于耦合、测试、烧机、可靠性、核心器件和良率。通用自动化、集团资本开支或通信分部面积不能直接填成光模块产线。{_cite('BYD-S16')}{_cite('LX-ANNUAL-2025')}

        产能判断至少需要设备类型、安装与投产时间、每月设计能力、良率、可售产量、产品速率、客户资格和利用率。设备到位领先于客户认证，客户认证又可能要求特定线体；因此“产线建成”也不等于收入。若新进入者先扩设备后拿订单，现金占用可能很高；若客户先承诺第二来源，产线爬坡可能更快。

        ## 分析与回答

        比亚迪的招聘、车载专利和工厂证据共同支持长期技术迁移能力；另有卖方转述指向一项可能的产品工程化计划，尚待发行人原文、产品规格、客户、产线和收入证据闭环。立讯的相同证据与公开产品和工程活动相互印证，使其阶段更靠前，但公开产线经济性仍不足。招聘与专利最适合判断准备度，不适合直接决定收入和份额；产能只有在良率、客户和订单同步时才进入财务模型。

        ## 本页结论

        根据现有材料，比亚迪的产品路线线索高于普通匿名传闻，车载专利簇也显示持续的光通信研发；但这两类材料都不能替代发行人产品规格、客户、可售良率、重复订单和收入。立讯同样需要这些经营证据把工程链条闭环。任何一个单独网页、专利或业绩会目标都不足以宣布规模进入。

        ## 如果想进一步研究，需要补充

        需要同一经营主体下的岗位、团队、专利、设备、产品和客户时间线；招聘按原始岗位去重，专利按同族去重，产能按可售良率而非名义设备计量。设备供应商、客户可靠性文件和分部财务能够提供比宣传页更有价值的交叉验证。
        """,
    }

    output: list[dict[str, Any]] = []
    for index, entity in enumerate(entities, start=1):
        key = entity["key"]
        if key not in bodies:
            raise ValueError(f"缺少面向用户的实体研究正文：{key}")
        extra = _body(_ENTITY_ADDITIONAL_ANALYSIS[key])
        body_markdown = _body(bodies[key]).replace(
            "## 本页结论", f"{extra}\n\n## 本页结论", 1
        )
        body_markdown = body_markdown.replace("## 本页结论", "## 结论").replace(
            "## 如果想进一步研究，需要补充",
            "## 如果想深入研究，需要补充",
        )
        refs = _valid_refs(body_markdown, _ENTITY_REFS[key], lookup)
        output.append(
            {
                "entity_key": key,
                "section_key": f"entity_answer_{key}",
                "section_title": entity["display_name"],
                "body_markdown": body_markdown,
                "support_status": "partially_supported",
                "evidence_ref_uri_list": [_source_uri(ref) for ref in refs],
                "sort_order": 1000 + index * 10,
            }
        )
    return output


def _chart_panel(
    title: str,
    *,
    periods: list[str],
    series: list[tuple[str, str, list[float]]],
    unit: str,
) -> dict[str, Any]:
    all_values = [value for _, _, values in series for value in values]
    low = min(all_values)
    high = max(all_values)
    if math.isclose(low, high):
        low -= 1.0
        high += 1.0
    pad = (high - low) * 0.08
    low -= pad
    high += pad
    rendered = []
    for label, color, values in series:
        points = []
        for index, value in enumerate(values):
            x = 0.0 if len(values) == 1 else index / (len(values) - 1) * 100.0
            y = (1.0 - (value - low) / (high - low)) * 100.0
            points.append(f"{x:.2f},{y:.2f}")
        rendered.append(
            {
                "label": label,
                "color": color,
                "svg_points": " ".join(points),
                "observation_count": len(values),
                "latest_period": periods[-1],
                "latest_value": f"{values[-1]:.2f}{unit}",
            }
        )
    return {
        "title": title,
        "unit": unit,
        "axis_mode": "sequence",
        "x_axis_label": "横轴：年份",
        "y_axis_label": f"纵轴：{unit}",
        "x_ticks": [
            {"position": 0, "label": periods[0]},
            {"position": 50, "label": periods[len(periods) // 2]},
            {"position": 100, "label": periods[-1]},
        ],
        "y_ticks": [
            {"position": 0, "label": f"{high:.1f}"},
            {"position": 50, "label": f"{(low + high) / 2:.1f}"},
            {"position": 100, "label": f"{low:.1f}"},
        ],
        "x_start": periods[0],
        "x_end": periods[-1],
        "y_min": f"{low:.2f}",
        "y_max": f"{high:.2f}",
        "series": rendered,
    }


def build_human_visuals(
    *, model: dict[str, Any], sources: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """只保留能增加趋势理解的信息图，删除与正文表格重复的审计看板。"""

    lookup = {source["ref"]: source for source in sources}
    rows = model.get("market", {}).get("rows", [])
    periods = [str(row["year"]) for row in rows]
    refs = [
        ref
        for ref in ("MODEL-WORKPAPER", "SRC-LC-MAR26", "SRC-OIF-2025")
        if ref in lookup
    ]
    panels = [
        _chart_panel(
            "高速端口需求与合格供给",
            periods=periods,
            series=[
                ("高速端口需求", "#2563eb", [float(row["total_ports_million"]) for row in rows]),
                ("合格供给", "#dc2626", [float(row["qualified_supply_million"]) for row in rows]),
            ],
            unit="百万端口",
        ),
        _chart_panel(
            "新架构占高速互联的工作比例",
            periods=periods,
            series=[
                ("LPO/LRO", "#0f766e", [float(row["lpo_lro_share_pct"]) for row in rows]),
                ("CPO", "#7c3aed", [float(row["cpo_share_pct"]) for row in rows]),
            ],
            unit="%",
        ),
    ]
    return [
        {
            "block_key": "market_supply_demand_visual",
            "block_type": "line_chart",
            "title": "2026—2031年需求、合格供给与架构变化",
            "subtitle": "先比较合格供给能否覆盖需求，再观察新架构是否改变传统模块的价值归属。",
            "data": {
                "what": "高速光互联需求、合格供给与架构变化",
                "time_window": "2026—2031",
                "how_to_read": "合格供给只计通过产品、良率和客户约束后能够销售的能力；架构比例不与速率端口重复相加。",
                "analysis": "图中需求与价格估算用于比较趋势，不是公司指引；完整输入和敏感性保留在计算底稿。",
                "chart": {"panels": panels},
            },
            "print_fallback": {
                "columns": ["年份", "高速端口需求", "合格供给", "LPO/LRO", "CPO"],
                "rows": [
                    [
                        row["year"],
                        row["total_ports_million"],
                        row["qualified_supply_million"],
                        row["lpo_lro_share_pct"],
                        row["cpo_share_pct"],
                    ]
                    for row in rows
                ],
            },
            "evidence_ref_uri_list": [_source_uri(ref) for ref in refs],
            "support_status": "partially_supported",
            "red_flag_level": "none",
            "sort_order": 510,
        }
    ]


def build_human_nav() -> list[dict[str, Any]]:
    return [
        {"nav_key": "summary", "label": "摘要", "href": "#summary", "sort_order": 10},
        {"nav_key": "answers", "label": "核心答案", "href": "#core_answers", "sort_order": 20},
        {"nav_key": "financial", "label": "盈利测算", "href": "#financial_method_and_results", "sort_order": 30},
        {"nav_key": "topics", "label": "专题研究", "href": "#entity_research_profiles", "sort_order": 40},
        {"nav_key": "monitor", "label": "后续跟踪", "href": "#monitoring_plan", "sort_order": 50},
    ]


def _markdown_table_count(markdown: str) -> int:
    return len(
        re.findall(
            r"(?m)^\|[^\n]+\|\s*\n\|\s*:?-{3,}",
            markdown,
        )
    )


def _long_last_cells(markdown: str, limit: int = 96) -> list[str]:
    result: list[str] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        cells = [cell.strip() for cell in stripped[1:-1].split("|")]
        if cells and not re.fullmatch(r":?-+:?", cells[-1]) and len(cells[-1]) > limit:
            result.append(cells[-1])
    return result


def audit_human_public_content(
    sections: list[dict[str, Any]], entity_sections: list[dict[str, Any]]
) -> dict[str, Any]:
    """在人审前拦截机器字段、低信息表格和模板化尾巴。"""

    if len(sections) != 4:
        raise ValueError(f"公开主报告应为4个高信息章节，当前为{len(sections)}")
    section_keys = {section["section_key"] for section in sections}
    expected = {
        "summary",
        "core_answers",
        "financial_method_and_results",
        "monitoring_plan",
    }
    if section_keys != expected:
        raise ValueError(f"公开章节集合不完整：{sorted(expected - section_keys)}")

    table_counts: dict[str, int] = {}
    paragraphs: Counter[str] = Counter()
    for row in [*sections, *entity_sections]:
        key = row.get("section_key") or row.get("entity_key")
        body_markdown = str(row.get("body_markdown") or "")
        audit_text = re.sub(
            r"\^src:source_ref:[A-Za-z0-9_.-]+[ \t]*", "", body_markdown
        )
        leftovers = [text for text in PUBLIC_FORBIDDEN_FRAGMENTS if text in audit_text]
        if leftovers:
            raise ValueError(f"公开正文 {key} 含内部或模板词：{leftovers}")
        machine_tokens = sorted(
            set(
                re.findall(
                    r"(?<![A-Za-z0-9_-])[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+(?![A-Za-z0-9_-])",
                    audit_text,
                )
            )
        )
        if machine_tokens:
            raise ValueError(f"公开正文 {key} 暴露机器变量：{machine_tokens}")
        headings = {
            heading.strip()
            for heading in re.findall(r"(?m)^#{2,4}[ \t]+([^\r\n]+)$", audit_text)
        }
        if not headings.intersection({"结论", "综合判断", "本节结论", "本页结论"}):
            raise ValueError(f"公开正文 {key} 缺少直接结论")
        if not (
            "如果想深入研究，需要补充" in audit_text
            or "如果想进一步研究，需要补充" in audit_text
        ):
            raise ValueError(f"公开正文 {key} 缺少进一步研究所需信息")
        table_count = _markdown_table_count(body_markdown)
        table_counts[str(key)] = table_count
        # 财务章节同时保留“总体预期结果”和“至少一家进入后的条件影响”两张
        # 决策表；其他章节仍执行单表上限，避免重新引入低信息密度表格。
        limit = 2 if key == "financial_method_and_results" else 1
        if table_count > limit:
            raise ValueError(f"公开正文 {key} 表格过多：{table_count}>{limit}")
        long_cells = _long_last_cells(body_markdown)
        if long_cells:
            raise ValueError(f"公开正文 {key} 最后一列承载长段结论：{long_cells[:2]}")
        for paragraph in re.split(r"\n\s*\n", audit_text):
            normalized = re.sub(r"\s+", "", paragraph)
            if len(normalized) >= 120 and not normalized.startswith(("|", "#")):
                paragraphs[normalized] += 1

    duplicates = [text for text, count in paragraphs.items() if count > 1]
    if duplicates:
        raise ValueError(f"公开正文存在重复长段落：{len(duplicates)}处")
    return {
        "human_public_section_count": len(sections),
        "human_public_entity_section_count": len(entity_sections),
        "human_public_table_count": sum(table_counts.values()),
        "human_public_table_count_by_section": table_counts,
        "human_public_forbidden_fragment_count": 0,
        "human_public_duplicate_long_paragraph_count": 0,
    }


def assert_human_public_markdown(markdown: str) -> None:
    """检查渲染后的完整 Markdown，覆盖组合层之外的标题和来源索引。"""

    audit_text = re.sub(
        r"\^src:source_ref:[A-Za-z0-9_.-]+[ \t]*", "", markdown
    )
    leftovers = [text for text in PUBLIC_FORBIDDEN_FRAGMENTS if text in audit_text]
    if leftovers:
        raise ValueError(f"最终公开报告含内部或模板词：{leftovers}")
    raw_date_tokens = re.findall(
        r"(?:current_at_(?:fetch|access)|current_page|"
        r"\d{4}-(?:spring|campus-cycle)|\d{4}-campus-cycle|"
        r"\d{4}-\d{2}-\d{2}/\d{4}-\d{2}-\d{2})",
        audit_text,
    )
    if raw_date_tokens:
        raise ValueError(f"最终公开报告含机器日期：{sorted(set(raw_date_tokens))}")
