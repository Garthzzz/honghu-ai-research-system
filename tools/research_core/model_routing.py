from __future__ import annotations

"""Deterministic routing for the four governed modeling Skills.

The router decides *which* contract must be loaded.  It does not embed the
long-form Skill instructions into every agent context.
"""

from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import Any, Iterable

from .config import resolve_track_config


@dataclass(frozen=True)
class ModelingRoute:
    skill_name: str
    skill_path: str
    contract_strength: str
    trigger_reasons: tuple[str, ...]
    required_outputs: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["trigger_reasons"] = list(self.trigger_reasons)
        data["required_outputs"] = list(self.required_outputs)
        return data


TERM_GROUPS = {
    "company_financial_modeling": {
        "future": ("未来收入", "未来利润", "利润预测", "收入预测", "盈利预测", "财务预测", "利润基线", "现金流预测", "财务建模", "正常化利润", "利润影响", "盈利影响"),
        "company": ("公司", "标的", "上市公司", "企业", "证券", "股票"),
    },
    "company_valuation_modeling": {
        # ROE/ROA 本身也是财务预测输出，不能仅因问题要求预测 ROE/ROA
        # 就误加载整套估值方法；PB-ROE/PB-ROA 会由 PB 或估值词触发。
        "valuation": ("估值", "目标价", "高估", "低估", "合理价值", "合理市值", "pe", "pb", "ev/ebitda", "dcf", "残余收益", "反向估值"),
    },
    "industry_supply_demand_modeling": {
        "industry": ("市场空间", "市场规模", "供需", "供给", "需求", "产能", "缺口", "渗透率", "替换需求", "有效供给", "tam", "sam", "数量×单价", "量价"),
    },
    "probability_scenario_modeling": {
        "scenario": ("概率", "可能性", "情景", "进入", "竞争者", "技术替代", "政策冲击", "事件冲击", "量产概率", "认证概率", "发生概率", "成功率"),
    },
}

PURE_EVIDENCE_TERMS = ("单纯新闻", "新闻核验", "专利核验", "招聘核验", "只核验", "事实核验")
NEGATED_MODELING_REQUEST_RE = re.compile(
    r"不(?:做|进行|要求|需要)(?:公司)?(?:财务预测|财务建模|收入预测|利润预测|盈利预测|估值|目标价测算)"
    r"(?:或(?:公司)?估值)?"
)


def _matches(text: str, terms: Iterable[str]) -> list[str]:
    lowered = text.lower()
    matched: list[str] = []
    for term in terms:
        needle = term.lower()
        if needle.isascii() and len(needle) <= 4:
            if re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", lowered):
                matched.append(term)
        elif needle in lowered:
            matched.append(term)
    return matched


def route_modeling_skills(
    *,
    track: str,
    title: str,
    research_question: str,
    requirements: Iterable[str] = (),
    required_artifacts: Iterable[str] = (),
    require_skill_files: bool = True,
) -> list[ModelingRoute]:
    text = "\n".join([title, research_question, *requirements])
    artifacts = {str(item) for item in required_artifacts}
    pure_evidence = bool(_matches(text, PURE_EVIDENCE_TERMS))
    trigger_text = NEGATED_MODELING_REQUEST_RE.sub("", text)
    config = resolve_track_config(track).get("modeling_skills", {})
    selected: dict[str, list[str]] = {}

    financial_future = _matches(trigger_text, TERM_GROUPS["company_financial_modeling"]["future"])
    company_terms = _matches(trigger_text, TERM_GROUPS["company_financial_modeling"]["company"])
    valuation_terms = _matches(trigger_text, TERM_GROUPS["company_valuation_modeling"]["valuation"])
    industry_terms = _matches(trigger_text, TERM_GROUPS["industry_supply_demand_modeling"]["industry"])
    scenario_terms = _matches(trigger_text, TERM_GROUPS["probability_scenario_modeling"]["scenario"])
    normalized_requirements = " ".join(str(item).lower() for item in requirements)
    if any(token in normalized_requirements for token in ("market_size", "supply_demand", "market_space")):
        industry_terms.append("默认覆盖包含市场空间/供需")

    if not pure_evidence or any((financial_future, valuation_terms, industry_terms, scenario_terms)):
        if financial_future or valuation_terms or ("company_financials" in artifacts and company_terms):
            selected["company_financial_modeling"] = [
                *(f"命中：{term}" for term in financial_future[:4]),
                *(f"估值需要预测财务输入：{term}" for term in valuation_terms[:2]),
            ] or ["产物要求包含公司财务"]
        if valuation_terms:
            selected["company_valuation_modeling"] = [f"命中：{term}" for term in valuation_terms[:5]]
            selected.setdefault("company_financial_modeling", []).append("正式估值必须先建立独立财务基线")
        if industry_terms:
            selected["industry_supply_demand_modeling"] = [f"命中：{term}" for term in industry_terms[:5]]
        if scenario_terms:
            selected["probability_scenario_modeling"] = [f"命中：{term}" for term in scenario_terms[:5]]
            if company_terms and any(term in text for term in ("影响", "冲击", "利润", "估值", "股价")):
                selected.setdefault("company_financial_modeling", []).append("外部事件需要传入公司财务桥")
                selected.setdefault("company_valuation_modeling", []).append("事件影响需要重估公司价值")
        if scenario_terms and industry_terms:
            selected.setdefault("industry_supply_demand_modeling", []).append("事件判断包含行业供需变量")

    routes: list[ModelingRoute] = []
    for name in (
        "company_financial_modeling",
        "company_valuation_modeling",
        "industry_supply_demand_modeling",
        "probability_scenario_modeling",
    ):
        if name not in selected:
            continue
        entry = config.get(name) or {}
        skill_path = str(entry.get("path") or "")
        if not skill_path or (
            require_skill_files
            and not (Path(__file__).resolve().parents[2] / skill_path).is_file()
        ):
            raise RuntimeError(f"建模 Skill 未注册或文件不存在：{name} -> {skill_path}")
        routes.append(ModelingRoute(
            skill_name=name,
            skill_path=skill_path,
            contract_strength=str(entry.get("contract_strength") or "governed"),
            trigger_reasons=tuple(dict.fromkeys(selected[name])),
            required_outputs=tuple(entry.get("required_outputs") or ()),
        ))
    return routes


def routing_obligations(routes: Iterable[ModelingRoute]) -> list[str]:
    names = {item.skill_name for item in routes}
    obligations: list[str] = []
    if "company_financial_modeling" in names:
        obligations.extend(("independent_fy1_fy3_freeze", "financial_input_output_ledger"))
    if "company_valuation_modeling" in names:
        obligations.extend(("valuation_method_gate", "external_reconciliation", "reverse_valuation"))
    if "industry_supply_demand_modeling" in names:
        obligations.append("report_web_channel_isolation")
    if "probability_scenario_modeling" in names:
        obligations.extend(("evidence_precision_control", "event_to_financial_bridge"))
    return list(dict.fromkeys(obligations))
