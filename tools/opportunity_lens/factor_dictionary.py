from __future__ import annotations

from dataclasses import dataclass

from .constants import FACTOR_DICTIONARY_VERSION


@dataclass(frozen=True)
class Factor:
    code: str
    label: str
    category: str
    weight: float
    applies_to: tuple[str, ...]
    formula: str
    description: str
    human_question: str


SEGMENT_FACTORS: tuple[Factor, ...] = (
    Factor(
        "demand.downstream_price_momentum",
        "下游价格动量",
        "demand",
        7,
        ("segment", "product_material", "company"),
        "因子分 = Σ(指标槽分数 × 指标槽权重) / Σ(可用指标槽权重)，再乘以 min(覆盖度调整, 置信度调整, 审计调整)",
        "衡量下游产品或终端需求价格是否正在上行。价格上行通常意味着需求或紧缺程度增强。",
        "下游客户或终端产品是否已经出现能支撑机会的涨价信号？",
    ),
    Factor(
        "demand.customer_capex_capacity_signal",
        "客户资本开支/产能信号",
        "demand",
        8,
        ("segment", "product_material", "company"),
        "因子分 = 客户扩产、资本开支、订单或排产信号的加权评分 × 可靠性调整",
        "衡量客户是否真的在扩产或加大投入，而不是只有概念热度。",
        "客户是否用资本开支、产能或排产动作证明需求在落地？",
    ),
    Factor(
        "demand.output_consumption_proxy",
        "产出消耗代理指标",
        "demand",
        7,
        ("segment", "product_material", "company"),
        "因子分 = 与单位产出消耗量相关的代理指标加权评分 × 可靠性调整",
        "衡量下游产量变化会不会实质拉动该材料、零部件或环节的消耗。",
        "下游产出增加时，该对象的消耗量是否同步放大？",
    ),
    Factor(
        "demand.application_intensity_change",
        "应用强度变化",
        "demand",
        8,
        ("segment", "product_material", "company"),
        "因子分 = 单位应用使用强度变化评分 × 可靠性调整",
        "衡量每台设备、每个系统或每个应用场景中该对象的用量是否提升。",
        "新应用是否让单位需求强度变高，而不只是市场规模变大？",
    ),
    Factor(
        "supply.capacity_event_12m",
        "12 个月产能事件",
        "supply",
        12,
        ("segment", "product_material", "company"),
        "因子分 = 未来 12 个月产能释放、受限、认证或爬坡事件评分 × 可靠性调整",
        "衡量供给端未来一年是否存在关键瓶颈或释放点。",
        "未来 12 个月供给是更紧、缓解，还是存在不确定爬坡？",
    ),
    Factor(
        "supply.expansion_cycle_bucket",
        "扩产周期分层",
        "supply",
        8,
        ("segment", "product_material", "company"),
        "因子分 = 扩产周期长短、设备/认证/良率约束评分 × 可靠性调整",
        "衡量扩产从决策到有效供给需要多久，周期越长越容易形成持续紧缺。",
        "供给扩张是否慢到足以形成持续机会窗口？",
    ),
    Factor(
        "supply.raw_policy_constraint",
        "原材料/政策约束",
        "supply",
        10,
        ("segment", "product_material", "company"),
        "因子分 = 原材料、政策、出口管制、环保或资质约束评分 × 可靠性调整",
        "衡量非产线因素是否限制供给扩张。",
        "原材料或政策约束是否会让供给无法快速响应需求？",
    ),
    Factor(
        "supply.supplier_structure_bucket",
        "供应商结构分层",
        "supply",
        10,
        ("segment", "product_material", "company"),
        "因子分 = 合格供应商数量、集中度和替代难度评分 × 可靠性调整",
        "衡量供应商是否少、集中，或者客户切换供应商是否困难。",
        "合格供应商结构是否足够紧，使紧缺能传导为议价权？",
    ),
    Factor(
        "supply.substitution_barrier",
        "替代壁垒",
        "supply",
        10,
        ("segment", "product_material", "company"),
        "因子分 = 认证周期、技术门槛、客户锁定和替代风险评分 × 可靠性调整",
        "衡量客户在短期内是否难以绕开该对象。",
        "客户是否很难用替代品、替代供应商或替代技术绕开瓶颈？",
    ),
    Factor(
        "signal.material_price_momentum",
        "材料价格动量",
        "signal",
        20,
        ("segment", "product_material", "company"),
        "因子分 = 材料或环节价格动量评分 × 可靠性调整",
        "衡量机会是否已经反映在材料、零部件或环节价格中。",
        "价格是否正在确认供需失衡，而不是只有叙事？",
    ),
)

COMPANY_FACTORS: tuple[Factor, ...] = (
    Factor(
        "company.exposure_directness",
        "受益暴露直接性",
        "company",
        35,
        ("company",),
        "因子分 = 公司业务与机会对象直接相关程度评分 × 可靠性调整",
        "衡量公司是不是直接卖相关产品、材料、设备或服务，而不是间接受益。",
        "这家公司和机会对象的业务联系有多直接？",
    ),
    Factor(
        "company.revenue_exposure_proxy",
        "收入暴露代理",
        "company",
        25,
        ("company",),
        "因子分 = 可归因收入、订单、客户、产线或业务占比代理指标评分 × 可靠性调整",
        "衡量机会如果兑现，能影响公司收入的程度。",
        "该机会对公司收入或订单的影响可能有多大？",
    ),
    Factor(
        "company.capacity_readiness_window",
        "产能兑现窗口",
        "company",
        20,
        ("company",),
        "因子分 = 公司产能、认证、交付和爬坡窗口评分 × 可靠性调整",
        "衡量公司是否能在机会窗口内真正供货，而不是只具备远期想象。",
        "公司能否在机会窗口内把供给兑现为收入？",
    ),
    Factor(
        "company.financial_capture_quality",
        "财务捕获质量",
        "company",
        20,
        ("company",),
        "因子分 = 毛利率、价格传导、产品结构和费用约束评分 × 可靠性调整",
        "衡量供需机会能否转化为利润质量，而不是只有收入增长。",
        "供需机会能否被公司捕获为更好的利润或现金流？",
    ),
)

FACTORS: tuple[Factor, ...] = SEGMENT_FACTORS + COMPANY_FACTORS
FACTOR_BY_CODE = {factor.code: factor for factor in FACTORS}


def factors_for_entity_type(entity_type: str) -> tuple[Factor, ...]:
    if entity_type == "company":
        return FACTORS
    return SEGMENT_FACTORS


def factor_weight(code: str) -> float:
    return FACTOR_BY_CODE[code].weight


def factor_metadata(code: str) -> dict:
    factor = FACTOR_BY_CODE[code]
    return {
        "factor_code": factor.code,
        "factor_label": factor.label,
        "factor_category": factor.category,
        "factor_weight": factor.weight,
        "factor_formula": factor.formula,
        "factor_description": factor.description,
        "factor_human_question": factor.human_question,
    }


def factor_version() -> str:
    return FACTOR_DICTIONARY_VERSION
