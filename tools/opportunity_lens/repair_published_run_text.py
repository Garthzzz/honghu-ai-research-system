from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "opportunity_lens.db"
RESEARCH_DB_PATH = ROOT / "data" / "research.db"
PACKS = {
    2: ROOT / "opportunity_lens" / "research_outputs" / "20260703_storage_upstream_materials" / "run_pack.json",
    3: ROOT / "opportunity_lens" / "research_outputs" / "20260703_oil_futures_spot" / "run_pack.json",
}

MIN_FACTOR_EVIDENCE_REFS = 3
MIN_IMPORTANT_FACTOR_EVIDENCE_REFS = 5
IMPORTANT_FACTOR_SCORE_THRESHOLD = 70.0


ENTITY_FACTOR_REF_POOL = {
    (2, 4): ["ab://research.data_point/11115", "ab://research.data_point/11116", "ab://research.data_point/11117", "ab://research.data_point/11069", "opp://source/8", "opp://source/9", "opp://source/10"],
    (2, 5): ["ab://research.data_point/7607", "ab://research.data_point/7606", "ab://research.data_point/7528", "ab://research.data_point/1735", "opp://source/11"],
    (2, 6): ["ab://research.data_point/6869", "ab://research.data_point/6872", "ab://research.data_point/6878", "ab://research.data_point/6889", "ab://research.data_point/6898", "ab://research.data_point/6847", "opp://source/12", "opp://source/13", "ab://research.source/588"],
    (2, 7): ["ab://research.data_point/7464", "ab://research.data_point/7465", "ab://research.data_point/7467", "opp://source/15", "ab://research.source/610"],
    (3, 8): ["opp://source/18", "opp://source/17", "opp://source/22", "opp://source/23", "opp://source/20"],
    (3, 9): ["opp://source/16", "opp://source/17", "opp://source/21", "opp://source/23", "opp://source/24", "opp://source/22"],
    (3, 10): ["opp://source/18", "opp://source/20", "opp://source/22", "opp://source/23", "opp://source/24"],
    (3, 11): ["opp://source/21", "opp://source/23", "opp://source/22", "opp://source/18", "opp://source/17"],
    (3, 12): ["opp://source/19", "opp://source/17", "opp://source/16", "opp://source/18", "opp://source/24"],
    (3, 13): ["opp://source/20", "opp://source/25", "opp://source/24", "opp://source/18", "opp://source/17"],
}


def _unique_refs(values: list) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value:
            continue
        ref = str(value).strip()
        if ref and ref not in seen:
            seen.add(ref)
            refs.append(ref)
    return refs


def _required_factor_refs(score: float, rank: int) -> int:
    return MIN_IMPORTANT_FACTOR_EVIDENCE_REFS if rank <= 3 or score >= IMPORTANT_FACTOR_SCORE_THRESHOLD else MIN_FACTOR_EVIDENCE_REFS


def _ensure_factor_refs(run_id: int, entity_id: int, refs: list[str], score: float, rank: int) -> list[str]:
    required = _required_factor_refs(score, rank)
    pool = ENTITY_FACTOR_REF_POOL.get((run_id, entity_id), [])
    merged = _unique_refs(list(refs or []) + pool)
    if len(merged) < required:
        raise RuntimeError(
            f"run {run_id} entity {entity_id} factor rank {rank} 证据不足："
            f"需要 {required} 个，当前 {len(merged)} 个"
        )
    return merged


def _direction_for_score(score: float) -> tuple[str, float]:
    if score >= 60:
        return "positive", 1.0
    if score <= 40:
        return "negative", -1.0
    return "mixed", 0.0


def _weight_for_ref(ref: str) -> tuple[float, float]:
    if ref.startswith("ab://research.data_point/"):
        return 0.9, 1.0
    if ref.startswith("opp://source/"):
        return 0.85, 0.8
    if ref.startswith("ab://research.source/"):
        return 0.75, 0.7
    return 0.65, 0.7


def _build_evidence_weighting(score: float, refs: list[str], required: int) -> dict:
    direction, direction_score = _direction_for_score(score)
    items = []
    total_weight = 0.0
    total_contribution = 0.0
    for index, ref in enumerate(refs, start=1):
        credibility, numeric = _weight_for_ref(ref)
        weight = round(credibility * numeric, 4)
        contribution = round(weight * direction_score, 4)
        total_weight += weight
        total_contribution += contribution
        items.append({
            "index": index,
            "evidence_ref": ref,
            "credibility_weight": credibility,
            "numeric_weight": numeric,
            "direction": direction,
            "direction_score": direction_score,
            "magnitude_weight": 1.0,
            "weight": weight,
            "weighted_contribution": contribution,
            "reason": "按来源可信度、数值口径和该因子当前分数方向加权；后续取得更细颗粒原始数据后可替换为逐条方向判断。",
        })
    net = total_contribution / total_weight if total_weight else 0.0
    return {
        "minimum_required_refs": required,
        "available_ref_count": len(refs),
        "gate_verdict": "pass" if len(refs) >= required else "blocked",
        "weighted_direction_score": round(net, 4),
        "weighted_evidence_score": round((net + 1.0) * 50.0, 2),
        "score_usage": "manual_score_with_weighted_evidence_audit",
        "items": items,
    }


SOURCE_UPDATES = {
    18: "截至 2026 年 6 月 26 日，美国商业原油库存 408.4 百万桶，周降 3.8 百万桶，约低于五年均值 7%；炼厂开工率 96.6%，原油加工量 17.2 百万桶/日。EIA 页面显示该期发布时间为 2026-07-01，下一次 Weekly Petroleum Status Report 发布时间为 2026-07-08。",
}

SOURCE_URL_UPDATES = {
    "https://www.eia.gov/petroleum/supply/weekly/": SOURCE_UPDATES[18],
}

ENTITY_SECTIONS = {
    2: [
        {
            "entity_id": 4,
            "section_title": "HBM 与 AI 服务器用高阶 12 英寸硅片研究实体介绍",
            "evidence_ref_uri_list": ["ab://research.data_point/11115", "ab://research.data_point/11116", "ab://research.data_point/11117", "opp://source/8"],
            "body_markdown": """### 研究的是什么

这个实体研究的是高阶 12 英寸硅片在 HBM、AI 服务器和先进存储扩产中的结构性紧缺机会。它不是普通硅片总量恢复的叙事，而是看重掺、高规格、可认证 12 英寸硅片是否因为 AI 存储需求放大而出现价格、交期和客户锁量的共同变化。

### 证据和数据

当前最强证据是三个 A/B 数据点和一个 C 轨来源共同支持：HBM 配套高阶重掺硅片价格上涨 10%-25% ^evidence:ab://research.data_point/11115 ，AI 服务器对 12 英寸硅片需求为通用服务器的 3.8 倍 ^evidence:ab://research.data_point/11116 ，HBM 对 12 英寸硅片需求为传统 DRAM 的 3 倍 ^evidence:ab://research.data_point/11117 。SEMI 同时确认 AI 数据中心需求推动先进逻辑和存储硅片出货恢复 ^evidence:opp://source/8 。

### 分析

这里的隐藏含义是：硅片总出货回升只能证明行业复苏，不能直接证明可投资的短缺。真正有价值的是高阶 12 英寸和 HBM 认证链条。如果价格上涨来自普通硅片补库存，投资意义会弱很多；如果涨价、交期和客户认证都集中在 HBM、AI 服务器和先进存储用高阶规格，说明供应端的合格产能才是瓶颈。评分较高的原因是需求强度、价格信号和供应集中度可以互相印证，但仍要持续排除普通硅片口径误配。

### 总结

这是 run_id=2 中最接近核心机会的实体。后续应把研究从“半导体硅片整体”收敛到“HBM 与 AI 服务器用高阶 12 英寸硅片”，重点核查供应商高阶产能、客户认证、长协锁量和实际涨价口径。

### 相关标的与投资研究建议

具体标的研究应优先链接到信越化学、胜高 SUMCO、环球晶圆、沪硅产业、TCL 中环/中环领先、有研硅、西安奕材和上海合晶。投资研究建议是：证据继续增强时，优先观察高阶 12 英寸硅片供应商相对普通半导体材料篮子的强弱；如果后续只看到普通硅片总量恢复而没有高阶规格涨价或交期拉长，应降低该实体的交易优先级。""",
        },
        {
            "entity_id": 5,
            "section_title": "3D NAND 钨填充用六氟化钨 WF6 研究实体介绍",
            "evidence_ref_uri_list": ["ab://research.data_point/7606", "ab://research.data_point/7607", "opp://source/11"],
            "body_markdown": """### 研究的是什么

这个实体研究的是 3D NAND 层数提升和新增内存产线对 WF6 的需求放大，以及这种需求是否会传导成电子特气供应商的短期供需失衡机会。研究对象不是所有电子特气，而是钨填充和高层数 3D NAND 相关的六氟化钨。

### 证据和数据

已入库证据显示，300 层以上 3D NAND 会放大钨沉积材料用量 ^evidence:ab://research.data_point/7606 ，单条新增内存产线可能带来 150-300 吨 WF6 需求 ^evidence:ab://research.data_point/7607 。C 轨来源也把六氟化钨列为 AI 半导体材料产业链需要持续重视的方向 ^evidence:opp://source/11 。

### 分析

WF6 的机会逻辑很清楚：层数提升使单片用量上升，扩产使总需求上升，两者叠加会把需求弹性放大。但它目前没有像高阶硅片那样形成价格、交期、合同锁量和供应商开工率的完整闭环。隐藏风险是：如果供应商产能充足，需求放大只会变成收入弹性，不会形成供需失衡溢价。因此该实体可以进入有限评分和高优先级补证，但不能直接等同于“已确认短缺”。

### 总结

WF6 是本轮最值得补证的第二层机会。补证优先级高于 CMP/湿化学品，但低于高阶硅片。下一步必须拿到供应商产能、价格、长协、客户锁量和新增内存线投产节奏，才能判断它是否从需求弹性升级为供应约束。

### 相关标的与投资研究建议

标的研究应从中船特气、华特气体、南大光电、雅克科技、中巨芯、广钢气体和金宏气体等电子特气链条展开。投资研究建议是：若合同价、开工率和长协锁量上行，观察 WF6 暴露公司相对存储指数和半导体材料指数的确认；若价格平稳且供应宽松，则只保留为 3D NAND 层数升级的中长期研究线索。""",
        },
        {
            "entity_id": 6,
            "section_title": "Low CTE 电子布、T 布与 ABF/HVLP 封装材料研究实体介绍",
            "evidence_ref_uri_list": ["ab://research.data_point/6869", "ab://research.data_point/6898", "opp://source/12", "opp://source/13", "ab://research.source/588"],
            "body_markdown": """### 研究的是什么

这个实体研究的是 HBM 先进封装链条对 Low CTE 电子布、T 布、ABF 和 HVLP 等封装材料的拉动。它不是单纯的“存储材料”实体，而是存储需求通过 HBM 封装和 AI 加速器封装向上游材料扩散的交叉机会。

### 证据和数据

当前证据显示 T 布供需缺口达到 41% ^evidence:ab://research.data_point/6869 ，高阶 BT 材料交期达到 16-20 周 ^evidence:ab://research.data_point/6898 。C 轨来源分别覆盖 T 布和 Low CTE 电子布的先进封装逻辑 ^evidence:opp://source/12 ^evidence:opp://source/13 ，ABF/HVLP 目前更多来自二次综合或早期信号 ^evidence:ab://research.source/588 。

### 分析

该实体的核心问题是归因边界。T 布和 Low CTE 电子布的短缺信号更强，但它们的需求来源不只包括存储，还包括 AI 加速器、先进封装基板和高端服务器平台。如果把所有先进封装材料涨价都归因为存储，会高估存储材料机会；如果只看传统存储材料，又会漏掉 HBM 封装带来的结构性瓶颈。因此评分保留中高水平，但证据角色必须拆分：T 布和 Low CTE 可作为较强证据，ABF/HVLP 在获得一手确认前只作为早期信号和补证方向。

### 总结

这是“存储加先进封装”的交叉机会，不是纯存储材料机会。后续研究要把 HBM 相关需求、通用 AI 封装需求和 PCB/封装基板周期分开，避免主题叙事混算。

### 相关标的与投资研究建议

具体标的研究应链接国际复材、中材科技、宏和科技、深南电路、欣兴电子，以及后续待补证的台光、联茂、南亚电路板等高端 CCL/封装基板链条。投资研究建议是：证据增强时观察先进封装材料篮子相对存储指数的强弱；在存储专属证据不足前，不把该实体直接当成存储上游材料主线交易。""",
        },
        {
            "entity_id": 7,
            "section_title": "存储扩产相关 CMP 抛光材料与湿化学品研究实体介绍",
            "evidence_ref_uri_list": ["ab://research.data_point/7464", "ab://research.data_point/7467", "opp://source/15"],
            "body_markdown": """### 研究的是什么

这个实体研究的是存储扩产对 CMP 抛光材料、湿化学品和相关后周期耗材的拉动。它更像产能利用率和资本开支后的消耗弹性，不是已经确认的短缺实体。

### 证据和数据

已有证据能说明存储和半导体扩产会带来 CMP、抛光垫、湿化学品等材料消耗 ^evidence:ab://research.data_point/7464 ，也能说明相关材料在半导体制造中的位置和国产替代逻辑 ^evidence:ab://research.data_point/7467 。C 轨来源将半导体材料定位为承接 Capex 后周期的方向 ^evidence:opp://source/15 。

### 分析

这条线的短板是缺少未来 6 个月的短缺证据。后周期材料可能受益于晶圆厂开工和扩产，但受益不等于短缺。要把它升级为 Opportunity Lens 高分实体，必须看到存储客户订单、报价、交期、库存或供应商满产证据。如果只有“扩产会用更多耗材”的逻辑，它只能作为研究观察项，而不是短缺交易主线。

### 总结

CMP/湿化学品目前应保持观察。它的投资价值在于收入弹性和国产替代跟踪，不在于已被证明的全球紧缺。

### 相关标的与投资研究建议

标的研究可链接安集科技、鼎龙股份、上海新阳、江化微和晶瑞电材等材料公司。投资研究建议是：只有订单、价格和交期同时上行时才把该实体纳入短缺观察篮子；否则把它作为后周期材料弹性和国产替代研究，不按供需失衡机会处理。""",
        },
    ],
    3: [
        {
            "entity_id": 8,
            "section_title": "美国炼厂高开工与成品油裂解价差研究实体介绍",
            "evidence_ref_uri_list": ["opp://source/18"],
            "body_markdown": """### 研究的是什么

这个实体研究的是美国原油和成品油库存低位、炼厂高开工率与裂解价差之间的关系。它不是直接看多原油单边，而是寻找产品端和炼厂链条是否比原油 outright 更有结构性。

### 证据和数据

EIA 周报显示，截至 2026 年 6 月 26 日，美国商业原油库存为 408.4 百万桶，周降 3.8 百万桶，约低于五年均值 7%；炼厂开工率 96.6%，原油加工量 17.2 百万桶/日 ^evidence:opp://source/18 。这些数据说明产品链和炼厂端仍处在高强度运行状态。

### 分析

隐藏含义是：如果炼厂高开工仍无法快速补足产品库存，裂解价差和成品油现货升贴水可能比原油单边更强；如果高开工带来库存快速恢复，则裂解价差会被压缩。这个实体的交易研究重点应放在炼厂利润、汽油和馏分油库存、开工率持续性，而不是只看 Brent 或 WTI 当日涨跌。

### 总结

这是 run_id=3 中更接近基本面结构机会的实体。它适合做炼厂链条、产品裂解价差和近月相对强弱研究，不适合直接写成无条件单边看多油价。

### 相关标的与投资研究建议

进一步研究入口包括 Valero、Marathon Petroleum、Phillips 66，以及 USO 作为 WTI 价格暴露参考。投资研究建议是：库存继续下降且炼厂高开工维持时，观察美国炼厂股相对能源板块、裂解价差和产品链强弱；库存回补或开工下行时，降低产品链交易优先级。""",
        },
        {
            "entity_id": 9,
            "section_title": "霍尔木兹风险溢价与 Brent/Dubai/Oman 波动研究实体介绍",
            "evidence_ref_uri_list": ["opp://source/16", "opp://source/21", "opp://source/23", "opp://source/24"],
            "body_markdown": """### 研究的是什么

这个实体研究的是霍尔木兹通行风险、Brent、Dubai 和 Oman 区域基准之间的风险溢价和波动。它关注的是事件风险和区域价差，不是简单的油价方向判断。

### 证据和数据

EIA 高价情景反映通行受扰和库存低位的风险溢价 ^evidence:opp://source/16 ，GME Oman 提供中东到亚洲基准参考 ^evidence:opp://source/21 ，ICE Brent 是全球海运原油基准入口 ^evidence:opp://source/23 。但 7 月初市场价格回落，显示霍尔木兹通行恢复和谈判进展已经压缩风险溢价 ^evidence:opp://source/24 。

### 分析

这个实体最大的价值是识别情景切换。若通行量、保险费、船期和谈判进展继续改善，Brent/Dubai/Oman 风险溢价会继续压缩；若出现新的制裁、军事扰动或运输阻塞，风险溢价会快速重估。它更适合研究区域价差、月差和波动率，而不是静态多空。

### 总结

霍尔木兹风险仍需监控，但核心分不能用新鲜媒体价格直接抬高。价格回落本身是 early signal，提示高价情景正在被市场重新定价。

### 相关标的与投资研究建议

标的和工具应链接 ICE Brent、GME Oman、CME WTI 和相关区域价差。投资研究建议是：风险重燃时观察 Brent 相对 Dubai/Oman、近月风险溢价和波动率；风险缓和时减少事件溢价暴露，把研究重心转回库存和炼厂链。""",
        },
        {
            "entity_id": 10,
            "section_title": "美国原油库存低位与 WTI 近月结构研究实体介绍",
            "evidence_ref_uri_list": ["opp://source/18", "opp://source/20", "opp://source/22"],
            "body_markdown": """### 研究的是什么

这个实体研究的是美国商业原油库存、Cushing、炼厂开工和 WTI 近月期限结构之间的关系。它关注近月支撑和月差，而不是单日 WTI 价格波动。

### 证据和数据

EIA 周报显示商业原油库存低于五年均值 7%，炼厂开工率为 96.6% ^evidence:opp://source/18 。CME WTI 是本轮 WTI 期货结构的官方产品入口 ^evidence:opp://source/22 。同时 CFTC 持仓显示 Managed Money 多头下降、空头上升，提示资金动能没有同步强化 ^evidence:opp://source/20 。

### 分析

库存低位支持近月，但资金退潮限制单边确定性。隐藏含义是：如果库存继续下降，近月可能强于远月；如果库存回补或炼厂开工下滑，近月支撑会减弱。CFTC 持仓变化要求把基本面和资金驱动分开看，不能把价格变化全部解释为供需。

### 总结

WTI 近月结构是可跟踪的核心实体，但交易研究应优先看月差、库存和 Cushing，而不是只给原油单边方向。

### 相关标的与投资研究建议

进一步研究入口包括 CME WTI、USO 和 CFTC COT。投资研究建议是：库存继续下降且近月升水扩大时，观察近月强于远月和定义风险工具；库存回补或资金拥挤下降时，降低单边多头假设。""",
        },
        {
            "entity_id": 11,
            "section_title": "亚洲 Oman/Dubai/SC 区域基准错配研究实体介绍",
            "evidence_ref_uri_list": ["opp://source/21"],
            "body_markdown": """### 研究的是什么

这个实体研究的是 Oman、Dubai 和 SC 原油之间的区域基准错配，尤其是中东到亚洲现货基准和中国 SC 原油之间是否存在可跟踪价差机会。

### 证据和数据

当前可验证的一手入口主要是 GME Oman，C 轨来源提供 Oman marker 的价格和合约参考 ^evidence:opp://source/21 。Dubai 和 SC 的实时曲线在本轮证据包中不足，因此不能把 Oman 单一证据扩展成完整区域价差结论。

### 分析

该实体的价值在于区域市场结构，但证据缺口明显。Oman 可作为中东到亚洲基准之一，但 Dubai 现货贴水、SC 期货曲线、亚洲炼厂开工和进口节奏都需要补。隐藏风险是用一个可得报价替代多个区域基准，从而制造不存在的确定性。

### 总结

这是有限评分实体。它适合作为区域价差监控框架，但在补齐 Dubai、SC 和亚洲炼厂数据前，不能作为核心交易结论。

### 相关标的与投资研究建议

进一步研究入口包括 GME Oman、Dubai/Oman 价差和 INE SC 原油。投资研究建议是：只有拿到一手曲线和亚洲炼厂数据后，才把它纳入区域价差交易观察；证据不足时仅保留为补证清单。""",
        },
        {
            "entity_id": 12,
            "section_title": "OPEC+ 政策弹性与 2027 供应反弹风险研究实体介绍",
            "evidence_ref_uri_list": ["opp://source/17", "opp://source/19"],
            "body_markdown": """### 研究的是什么

这个实体研究的是 OPEC+ 增产、执行率和远期供应反弹对油价曲线的约束。它是风险实体，用来防止把近月低库存直接外推成整条远期曲线的看多结论。

### 证据和数据

OPEC 来源显示 7 国在 2026 年 7 月实施 18.8 万桶/日调整 ^evidence:opp://source/19 。IEA 预计 2027 年供应反弹约 8 百万桶/日 ^evidence:opp://source/17 。这两条证据共同指向远期供应压力和政策弹性风险。

### 分析

近月库存紧和远期供应反弹可以同时成立。隐藏含义是：低库存可能支撑近月，但 OPEC+ 增产和 2027 供应反弹会限制远月风险溢价。如果 OPEC+ 暂停或逆转退出，远月压力会减轻；如果继续增产且执行率稳定，远月曲线会受到压制。

### 总结

这是约束性实体，不是正向机会实体。它要求所有油价机会研究都区分近月、远月和曲线形态。

### 相关标的与投资研究建议

进一步研究可链接 ExxonMobil、Chevron、Shell、BP 等上游油气公司，以及 Brent/WTI 远月曲线。投资研究建议是：OPEC+ 增产延续时，避免把近月低库存直接外推为上游 beta 单边机会；暂停或逆转时，再观察远月压力释放和曲线再陡峭化。""",
        },
        {
            "entity_id": 13,
            "section_title": "宏观需求回落与基金仓位去拥挤研究实体介绍",
            "evidence_ref_uri_list": ["opp://source/20", "opp://source/25"],
            "body_markdown": """### 研究的是什么

这个实体研究的是宏观需求回落、基金持仓和供需情景切换对原油机会的压制。它主要是风险控制和仓位拥挤度实体。

### 证据和数据

CFTC 持仓显示 Managed Money 多头下降、空头上升，说明资金拥挤度回落 ^evidence:opp://source/20 。另有市场报道指出历史性供应紧张缓和后，油价出现季度级回落压力 ^evidence:opp://source/25 。

### 分析

该实体的隐藏含义是：基本面低库存并不自动等于趋势行情，资金仓位和宏观需求会决定价格兑现方式。如果净多回升且波动率上行，行情可能重新拥挤；如果净多继续下降且波动率低，单边动能会下降，基本面信号更适合通过价差、月差或期权框架表达。

### 总结

这是 run_id=3 的风险控制实体。它不直接给正向机会分，而是提醒研究员把供需、资金和宏观拆开，防止用单一库存数据解释全部价格变化。

### 相关标的与投资研究建议

进一步研究入口包括 CFTC COT、USO、XLE 和 WTI/Brent 期权波动率。投资研究建议是：拥挤度升高时避免追涨追跌，优先观察定义风险工具和价差；拥挤度下降时降低动量权重，但保留基本面触发后的再进入观察。""",
        },
    ],
}

ENTITY_TARGETS = [
    (2, 4, "信越化学", "4063.T", "日本", "company", 507, None, "全球高阶硅片龙头之一，和 HBM/先进存储用 12 英寸硅片供给能力高度相关。", "ab://research.data_point/11115", "核查高阶 12 英寸、重掺和 HBM 客户认证产能。", "证据继续增强时，优先作为高阶硅片全球供给侧核心标的研究。", "普通硅片总量恢复可能掩盖高阶规格紧缺，需拆分口径。", "linked", "supported", 1),
    (2, 4, "胜高 SUMCO", "3436.T", "日本", "company", 543, None, "全球高阶硅片供应商，适合与信越化学对照验证供给集中度。", "opp://source/8", "补产能利用率、长协和客户认证信息。", "用于研究高阶硅片供应集中和全球相对强弱。", "若高阶规格并未涨价，供应集中不等于投资机会。", "linked", "partially_supported", 2),
    (2, 4, "环球晶圆", "6488.TWO", "中国台湾", "company", 509, None, "12 英寸硅片全球供应链重要公司，可作为非日本供应侧对照。", "opp://source/8", "核查 AI 存储相关高阶订单和扩产节奏。", "用于观察高阶硅片全球供给扩散和区域替代机会。", "需要确认订单是否来自 HBM/AI 服务器高阶规格。", "linked", "partially_supported", 3),
    (2, 4, "沪硅产业", "688126.SH", "中国 A 股", "company", 510, None, "A 股 12 英寸硅片链条代表，适合跟踪国产高阶硅片认证进展。", "ab://research.data_point/11116", "补高阶规格收入暴露、客户验证和国产替代证据。", "作为 A 股高阶硅片研究入口，不能用普通硅片周期直接替代高阶紧缺逻辑。", "A 股弹性可能来自主题交易而非真实高阶供需兑现。", "linked", "partially_supported", 4),
    (2, 4, "中环领先(TCL中环)", "002129.SZ", "中国 A 股", "company", 547, None, "国内硅片链条重要主体，可用于观察国产供应扩张和高阶认证。", "ab://research.data_point/11117", "补半导体硅片业务口径和 HBM/AI 服务器相关认证。", "作为国产替代和供给扩张对照，不直接等同于高阶短缺受益。", "光伏硅片和半导体硅片口径必须严格区分。", "linked", "partially_supported", 5),
    (2, 5, "中船特气", None, "中国 A 股/待补 ticker", "company", 520, None, "电子特气链条标的，和 WF6 国产供应能力相关。", "ab://research.data_point/7607", "补 WF6 产能、客户、长协和价格口径。", "合同价和开工率上行时纳入 WF6 供应侧优先观察。", "若供应宽松，需求增量只形成收入弹性，不形成短缺溢价。", "linked", "partially_supported", 1),
    (2, 5, "华特气体", "688268.SH", "中国 A 股", "company", 519, None, "电子特气公司，适合作为 WF6 和先进制程特气研究入口。", "opp://source/11", "核查 WF6 产品、客户认证和新增产线供货关系。", "作为 WF6 补证标的，确认一手证据后再提高交易优先级。", "产品结构可能并非 WF6 主导，需防止泛电子特气叙事。", "linked", "partially_supported", 2),
    (2, 5, "南大光电", "300346.SZ", "中国 A 股", "company", 527, None, "半导体材料和电子特气相关公司，可作为材料链映射标的。", "ab://research.data_point/7606", "补 WF6 直接暴露和订单证据。", "仅在直接暴露被证实后进入 WF6 机会篮子。", "如果缺少 WF6 直接暴露，只能作为泛半导体材料观察。", "linked", "weak", 3),
    (2, 5, "雅克科技", "002409.SZ", "中国 A 股", "company", 521, None, "半导体材料平台型公司，可用于对照电子材料景气。", "opp://source/11", "拆分电子特气、前驱体和存储材料暴露。", "作为相关材料链辅助研究标的，不直接替代 WF6 供应商。", "平台型业务口径复杂，需避免错配。", "linked", "weak", 4),
    (2, 6, "国际复材", "301526.SZ", "中国 A 股", "company", 478, None, "玻纤和电子布链条公司，和 T 布、Low CTE 材料供给相关。", "ab://research.data_point/6869", "补高端电子布产能、T 布认证和价格证据。", "T 布缺口继续扩大时，作为上游材料链观察入口。", "普通玻纤景气不能直接替代高端电子布短缺。", "linked", "partially_supported", 1),
    (2, 6, "中材科技", "002080.SZ", "中国 A 股", "company", 477, None, "电子布和复合材料链条公司，可用于观察高端材料国产供给。", "opp://source/12", "补高端电子布产品结构和客户认证。", "作为 T 布和 Low CTE 供应侧对照标的。", "业务多元，需拆分电子布真实暴露。", "linked", "partially_supported", 2),
    (2, 6, "宏和科技", "603256.SH", "中国 A 股", "company", 473, None, "电子级玻纤布公司，适合映射 T 布和高端电子布需求。", "opp://source/13", "核查 Low CTE/T 布规格、订单和交期。", "证据增强时纳入先进封装材料观察篮子。", "客户和规格若不在高端封装链，机会会被高估。", "linked", "partially_supported", 3),
    (2, 6, "深南电路", "002916.SZ", "中国 A 股", "company", 472, None, "封装基板和 PCB 链条公司，可用于验证材料向下游传导。", "ab://research.data_point/6898", "补封装基板交期、ABF/HVLP 材料约束和客户需求。", "作为下游验证标的，重点看材料瓶颈是否传导到基板利润。", "下游公司可能受材料涨价挤压，不一定直接受益。", "linked", "partially_supported", 4),
    (2, 7, "安集科技", "688019.SH", "中国 A 股", "company", 528, None, "CMP 抛光液和半导体材料标的，适合跟踪存储扩产后的耗材弹性。", "ab://research.data_point/7464", "补存储客户订单、价格和交期。", "只有订单、价格和交期共振时才进入短缺观察篮子。", "当前证据主要支持后周期受益，不支持已确认短缺。", "linked", "partially_supported", 1),
    (2, 7, "鼎龙股份", "300054.SZ", "中国 A 股", "company", 515, None, "CMP 抛光垫和材料链公司，可作为后周期材料弹性研究入口。", "opp://source/15", "拆分 CMP 抛光垫、抛光液和存储客户暴露。", "作为后周期材料观察标的，等待短缺证据确认。", "收入弹性和短缺溢价不能混同。", "linked", "partially_supported", 2),
    (2, 7, "上海新阳", None, "中国 A 股/待补 ticker", "company", 537, None, "湿化学品和半导体材料相关公司，可用于补充材料链跟踪。", "ab://research.data_point/7467", "补存储客户订单和报价变化。", "作为湿化学品观察入口，证据不足前不纳入核心短缺机会。", "客户结构和产品口径可能与存储扩产不匹配。", "linked", "weak", 3),
    (2, 7, "江化微", None, "中国 A 股/待补 ticker", "company", 529, None, "湿电子化学品公司，可用于观察扩产后耗材需求。", "ab://research.data_point/7467", "补价格、交期和存储客户需求。", "作为补证标的，不作为当前核心机会。", "缺少短期短缺证据。", "linked", "weak", 4),
    (3, 8, "Valero Energy", "VLO", "美国", "company", None, "https://investorvalero.com/home/default.aspx", "美国炼厂链条代表，和炼厂开工、裂解价差、产品库存直接相关。", "opp://source/18", "跟踪季度业绩、炼厂利润、开工率和产品库存变化。", "库存继续下降且裂解价差走强时，作为美国炼厂链条核心研究标的。", "炼厂高开工也可能快速补库存并压缩裂解价差。", "external_only", "supported", 1),
    (3, 8, "Marathon Petroleum", "MPC", "美国", "company", None, "https://www.marathonpetroleum.com/Investors/", "美国炼厂和成品油链条代表，可验证产品端强弱。", "opp://source/18", "跟踪 2026 年二季报、炼厂利润和产品端库存。", "用于观察炼厂股相对能源板块的强弱。", "成品油需求回落会压缩炼厂利润。", "external_only", "supported", 2),
    (3, 8, "Phillips 66", "PSX", "美国", "company", None, "https://investor.phillips66.com/investors/default.aspx", "炼厂、化工和中游综合能源公司，可作为产品链对照。", "opp://source/18", "拆分炼厂利润和非炼厂业务对业绩的影响。", "作为裂解价差研究的对照标的。", "业务多元可能稀释炼厂链条暴露。", "external_only", "partially_supported", 3),
    (3, 8, "United States Oil Fund", "USO", "美国 ETF", "etf", None, "https://www.uscfinvestments.com/uso", "USO 可作为 WTI 价格暴露参考，用于和炼厂股、裂解价差形成对照。", "opp://source/18", "核查持仓、滚动成本和期限结构影响。", "作为产品链研究的原油价格基准对照，不直接替代裂解价差。", "ETF 滚动损耗和期限结构可能造成跟踪偏差。", "external_only", "partially_supported", 4),
    (3, 9, "ICE Brent Futures", "BRN", "ICE", "futures_contract", None, "https://www.ice.com/products/219/brent-crude-futures", "Brent 是全球海运原油风险溢价和霍尔木兹情景的核心基准。", "opp://source/23", "跟踪 Brent 近远月、Brent-Dubai/Oman 和波动率。", "风险重燃时观察 Brent 相对区域基准和近月风险溢价。", "事件风险缓和会压缩风险溢价。", "external_only", "supported", 1),
    (3, 9, "GME Oman Crude Oil Futures", "OQD", "GME/CME", "futures_contract", None, "https://www.cmegroup.com/international/partnership-resources/gme-resources.html", "Oman 是中东到亚洲区域基准的重要参考。", "opp://source/21", "跟踪 Oman marker、Dubai/Oman 价差和亚洲炼厂采购。", "用于区域风险溢价和亚洲基准错配研究。", "不能用 Oman 单一报价替代 Dubai 和 SC 全曲线。", "external_only", "supported", 2),
    (3, 9, "CME WTI Futures", "CL", "CME", "futures_contract", None, "https://www.cmegroup.com/markets/energy/crude-oil/light-sweet-crude.html", "WTI 作为美国原油基准，可与 Brent/Oman 对照风险溢价。", "opp://source/22", "跟踪 Brent-WTI、近远月和美国库存差异。", "作为跨基准价差研究工具。", "美国本地库存会让 WTI 与海运风险脱钩。", "external_only", "supported", 3),
    (3, 10, "CME WTI Futures", "CL", "CME", "futures_contract", None, "https://www.cmegroup.com/markets/energy/crude-oil/light-sweet-crude.html", "WTI 近月结构直接对应美国库存和 Cushing 约束。", "opp://source/22", "跟踪近月升贴水、Cushing 库存和合约换月。", "库存继续下降时观察近月强于远月。", "库存回补会削弱近月支撑。", "external_only", "supported", 1),
    (3, 10, "United States Oil Fund", "USO", "美国 ETF", "etf", None, "https://www.uscfinvestments.com/uso", "USO 是 WTI 价格暴露参考，不等同于现货油价。", "opp://source/18", "核查持仓、滚动成本和期限结构影响。", "作为 WTI 方向性暴露观察入口，必须结合月差。", "ETF 滚动损耗和期限结构可能造成跟踪偏差。", "external_only", "partially_supported", 2),
    (3, 10, "CFTC COT Petroleum", None, "美国监管数据", "external_watch", None, "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm", "CFTC 持仓用于区分基本面和资金动能。", "opp://source/20", "每周跟踪 Managed Money 净多、空头和拥挤度。", "资金拥挤上升时提高风控优先级，拥挤下降时降低动量权重。", "持仓数据滞后，不能单独作为交易触发。", "external_only", "supported", 3),
    (3, 11, "GME Oman Crude Oil Futures", "OQD", "GME/CME", "futures_contract", None, "https://www.cmegroup.com/international/partnership-resources/gme-resources.html", "当前最可验证的亚洲相关中东原油基准入口。", "opp://source/21", "补 Dubai 现货贴水、SC 曲线和亚洲炼厂开工。", "作为区域基准错配的起点，不直接形成完整交易结论。", "缺少 Dubai 和 SC 一手曲线时，结论只能有限评分。", "external_only", "supported", 1),
    (3, 11, "INE SC 原油", "SC", "上海国际能源交易中心", "futures_contract", None, "https://www.ine.cn/eng/market/futures/energy/sc/", "SC 是中国原油期货基准，和亚洲区域错配研究相关。", "opp://source/21", "补 INE SC 官方曲线和成交持仓。", "拿到一手曲线后再纳入区域价差观察。", "当前证据包未覆盖实时 SC 曲线。", "external_only", "weak", 2),
    (3, 12, "ExxonMobil", "XOM", "美国", "company", None, "https://investor.exxonmobil.com/", "全球上游油气龙头，可用于观察远期供应和油价 beta。", "opp://source/17", "跟踪资本开支、产量指引和油价敏感性。", "OPEC+ 增产延续时控制上游 beta，暂停或逆转时再观察远月压力释放。", "上游 beta 受天然气、炼化和公司资本纪律影响。", "external_only", "partially_supported", 1),
    (3, 12, "Chevron", "CVX", "美国", "company", None, "https://www.chevron.com/investors", "上游和综合能源公司，可用于对照供应反弹风险。", "opp://source/19", "跟踪产量、资本开支和股东回报对油价敏感性。", "作为远月供应风险约束下的上游对照标的。", "公司自身事件可能盖过 OPEC+ 曲线影响。", "external_only", "partially_supported", 2),
    (3, 12, "Shell", "SHEL", "英国/荷兰", "company", None, "https://www.shell.com/investors.html", "综合能源公司，适合观察全球油气暴露和资本纪律。", "opp://source/17", "跟踪上游产量、现金流和资本配置。", "用于全球综合能源 beta 对照，不直接等同于 OPEC+ 供应冲击。", "液化天然气和下游业务会稀释原油暴露。", "external_only", "weak", 3),
    (3, 13, "CFTC COT Petroleum", None, "美国监管数据", "external_watch", None, "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm", "CFTC 是基金仓位和拥挤度的核心入口。", "opp://source/20", "每周复核净多、空头和波动率变化。", "拥挤度升高时避免追涨追跌，优先观察定义风险工具。", "COT 有时间滞后，不能替代实时成交和波动率。", "external_only", "supported", 1),
    (3, 13, "United States Oil Fund", "USO", "美国 ETF", "etf", None, "https://www.uscfinvestments.com/uso", "USO 可作为油价方向性暴露和散户资金关注度参考。", "opp://source/25", "跟踪净值、持仓、滚动成本和资金流。", "资金动能弱时降低单边动量权重。", "ETF 结构会让表现偏离即期油价。", "external_only", "partially_supported", 2),
    (3, 13, "Energy Select Sector SPDR Fund", "XLE", "美国 ETF", "etf", None, "https://www.ssga.com/us/en/intermediary/etfs/state-street-energy-select-sector-spdr-etf-xle", "XLE 可作为能源股 beta 和资金拥挤度观察工具。", "opp://source/20", "补持仓、资金流和相对油价强弱。", "用于观察能源股相对原油的风险偏好。", "成分股结构会混合上游、炼厂和服务商暴露。", "external_only", "weak", 3),
]


ENTITY_TARGET_CONTEXT = {
    (2, 4): {
        "theme": "HBM 与 AI 服务器用高阶 12 英寸硅片",
        "confirm": "若高阶规格涨价、交期拉长、客户认证或长协锁量继续被证实，优先观察该标的相对半导体材料篮子的强弱，并把研究从普通硅片周期收敛到高阶 12 英寸硅片供给瓶颈。",
        "falsify": "若后续证据只显示普通硅片出货恢复，或高阶规格价格、交期和认证没有同步强化，应降低该标的在短缺交易框架中的权重。",
    },
    (2, 5): {
        "theme": "3D NAND 钨填充用 WF6",
        "confirm": "若 WF6 合同价、供应商开工率、长协锁量或新增内存线投产证据继续增强，将该标的纳入 WF6 供应侧观察池，并优先比较直接 WF6 暴露。",
        "falsify": "若供应宽松且价格平稳，应从短缺逻辑降级为 3D NAND 层数升级的中长期收入弹性研究。",
    },
    (2, 6): {
        "theme": "Low CTE/T 布与 ABF/HVLP 封装材料",
        "confirm": "若报价、交期和客户认证证实先进封装材料瓶颈，优先观察高端电子布和封装材料链的相对强弱。",
        "falsify": "若证据不能区分 HBM 专属需求和通用 AI 封装需求，应降低存储上游材料归因权重，仅保留交叉主题监控。",
    },
    (2, 7): {
        "theme": "CMP 与湿化学品后周期材料",
        "confirm": "若存储客户订单、价格和交期同时上行，才把该标的从后周期收入弹性升级为短缺候选。",
        "falsify": "若只有扩产叙事而没有客户订单或涨价交期，应维持观察，不按供需失衡主线处理。",
    },
    (3, 8): {
        "theme": "美国炼厂高开工与成品油裂解价差",
        "confirm": "若产品库存继续下降、炼厂开工维持高位且裂解价差走强，优先观察炼厂链条相对能源板块和原油价格暴露的强弱。",
        "falsify": "若高开工推动库存快速回补或裂解价差压缩，应降低炼厂链条的交易优先级。",
    },
    (3, 9): {
        "theme": "霍尔木兹风险溢价与 Brent/Dubai/Oman 波动",
        "confirm": "若通行受阻、保险费上行、谈判恶化或区域价差走阔，优先观察 Brent、Oman/Dubai 价差、近月风险溢价和事件波动率。",
        "falsify": "若通行恢复、保险费下降且区域价差收敛，应减少事件溢价暴露，把研究重心转回库存、炼厂链和期限结构。",
    },
    (3, 10): {
        "theme": "美国原油库存低位与 WTI 近月结构",
        "confirm": "若美国库存和 Cushing 继续下降且近月升水扩大，优先观察 WTI 近月强于远月和库存驱动的月差结构。",
        "falsify": "若库存回补、炼厂开工下降或资金拥挤退潮，应降低 WTI 近月多头假设。",
    },
    (3, 11): {
        "theme": "亚洲 Oman/Dubai/SC 区域基准错配",
        "confirm": "若 Dubai、SC 和亚洲炼厂数据补齐且价差持续扩大，才把该标的纳入区域价差观察。",
        "falsify": "若仍只有 Oman 单一报价，应保持有限评分，不扩展成完整亚洲价差交易判断。",
    },
    (3, 12): {
        "theme": "OPEC+ 政策弹性与 2027 供应反弹风险",
        "confirm": "若 OPEC+ 增产持续且 2027 供应反弹被强化，应控制上游 beta，并重点看远月曲线压力。",
        "falsify": "若 OPEC+ 暂停或逆转退出，应重新观察远月压力释放和曲线再陡峭化。",
    },
    (3, 13): {
        "theme": "宏观需求回落与基金仓位去拥挤",
        "confirm": "若净多回升、波动率上行且价格趋势同步，应提高资金拥挤和定义风险工具的研究优先级。",
        "falsify": "若净多继续下降且波动率维持低位，应降低动量交易权重，只保留基本面触发后的再进入观察。",
    },
}


TARGET_SPECIFIC_PATCHES = {
    (3, 9, "ICE Brent Futures"): {
        "target_priority": "P1 核心基准",
        "target_quality_label": "事件风险映射最直接",
        "relative_preference": "在霍尔木兹风险实体中，Brent 是全球海运风险溢价的主基准，优先级高于 WTI；与 Oman/Dubai 配合用于判断中东到亚洲的区域传导。",
    },
    (3, 9, "GME Oman Crude Oil Futures"): {
        "target_priority": "P1 区域基准",
        "target_quality_label": "亚洲中东原油定价映射强",
        "relative_preference": "Oman 对亚洲和中东出口基准更敏感，适合与 Brent 配对；单独使用时不能替代 Dubai 和 SC 全曲线。",
    },
    (3, 9, "CME WTI Futures"): {
        "target_priority": "P2 对照基准",
        "target_quality_label": "美国库存对照价值高",
        "relative_preference": "WTI 更适合作为美国本地库存和 Brent-WTI 价差对照，不是霍尔木兹事件风险的最纯映射。",
    },
    (2, 4, "信越化学"): {
        "target_priority": "P1 全球核心供应商",
        "target_quality_label": "高阶硅片供给映射最强",
        "relative_preference": "在高阶 12 英寸硅片实体中优先级最高，适合作为全球供给约束和价格确认的核心观察标的。",
    },
    (2, 4, "胜高 SUMCO"): {
        "target_priority": "P1 全球核心供应商",
        "target_quality_label": "与信越形成供给集中度对照",
        "relative_preference": "与信越化学并列用于验证全球高阶硅片供给集中，适合做相对强弱和供给验证。",
    },
}


def _polish_entity_body(text: str) -> str:
    replacements = {
        "### 研究的是什么": "### 研究对象",
        "这个实体研究的是": "本实体聚焦",
        "它不是": "研究边界不是",
        "这个实体最大的价值是": "该实体的核心研究价值在于",
        "这是 run_id=3 中": "该实体是 run_id=3 中",
        "这是 run_id=2 中": "该实体是 run_id=2 中",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _target_priority(sort_order: int, support_status: str) -> str:
    if sort_order == 1 and support_status in {"supported", "partially_supported"}:
        return "P1 核心观察"
    if support_status == "supported":
        return "P2 重要观察"
    if support_status == "partially_supported":
        return "P2 补证观察"
    return "P3 弱证据观察"


def _target_quality_label(target_type: str, support_status: str) -> str:
    if support_status == "supported":
        return "证据链相对完整"
    if support_status == "partially_supported":
        return "具备研究入口，仍需补直接暴露"
    if target_type in {"external_watch", "spread"}:
        return "监控工具，不等同于投资标的"
    return "弱证据，仅作补证线索"


def _target_profile_markdown(data: dict, context: dict) -> str:
    return (
        f"{data['target_name']} 是“{context['theme']}”研究实体下的结构化研究标的，类型为"
        f"{data['target_type']}，市场口径为 {data.get('market') or '未标明'}。"
        f"本轮将其用于验证：{data['exposure_rationale']}\n\n"
        f"标的研究的第一层任务不是泛化判断板块景气，而是确认该标的的业务、合约、价格、库存、曲线或客户认证"
        f"是否能直接承接“{context['theme']}”的供需失衡。若只能证明宽泛主题相关，标的质量必须降级。"
    )


def _target_deep_research_markdown(data: dict, context: dict) -> str:
    return (
        f"深入研究应围绕三条线展开。第一，暴露强度：核查 {data['target_name']} 与"
        f"“{context['theme']}”之间是收入、产能、合约、价差、期限结构还是观察工具关系。第二，"
        f"兑现路径：{data['research_action']} 第三，反向风险：{data['risk_note']}\n\n"
        f"同实体内比较时，优先级来自直接暴露、证据质量和证实/证伪速度。{data['relative_preference']}"
    )


def _entity_relation_markdown(data: dict, context: dict) -> str:
    return (
        f"该标的与研究实体的关系是：{data['exposure_rationale']} "
        f"如果后续证据证实“{context['theme']}”进入价格、交期、库存、月差或客户订单层面的约束，"
        f"该标的可用于观察相对强弱、价差变化或基本面兑现。"
    )


def _parent_relation_markdown(data: dict, context: dict) -> str:
    return (
        f"在本轮 Opportunity Lens 主问题中，{data['target_name']} 的作用是把供需信号落到可跟踪对象。"
        f"它不单独决定研究结论，而是和实体评分、后续监控指标、补证清单和同组标的比较一起使用。"
    )


def _conditional_recommendation(data: dict, context: dict) -> str:
    return (
        f"证实情景：{data['confirmed_scenario_action']} 对应建议是提高 {data['target_name']} 的研究和交易观察优先级，"
        f"重点比较它相对同实体其他标的、相关指数、期货曲线或价差工具的强弱。\n\n"
        f"证伪情景：{data['falsified_scenario_action']} 对应建议是降低权重、退出短缺交易假设或转入补证，"
        f"避免把主题相关性误当成可兑现机会。\n\n"
        f"风险控制依据：{data['risk_note']} 所有响应都必须回到可追溯数据点、原文摘录和后续监控触发条件。"
    )


def _financial_data_status(data: dict) -> str:
    if data.get("company_id"):
        return (
            f"已绑定 A/B 行研库 company_id={data['company_id']}；标的页只读展示 company/company_profile "
            "中的估值、财务和业务快照。后续如需更新，只能使用 Tushare 或 yfinance，并把新快照写入 C 轨标的数据点；历史 Wind 溯源仅作为旧数据事实保留。"
        )
    return (
        "当前为外部市场工具或未绑定本地公司页；页面展示已入库的研究数据点。后续若需要金融数据，优先用交易所/官方合约页、"
        "Tushare 或 yfinance 回填，并保留来源和时间。"
    )


def _base_target_data_points(data: dict) -> list[dict]:
    ref = data.get("evidence_ref_uri")
    source_title = "Opportunity Lens 人工核验研究包"
    return [
        {
            "metric_name": "标的与研究实体关系强度",
            "metric_category": "relationship",
            "value_text": data["exposure_rationale"],
            "unit": "文本",
            "source_title": source_title,
            "source_publisher": "Opportunity Lens",
            "source_excerpt": data["exposure_rationale"],
            "evidence_ref_uri": ref,
            "data_quality_label": data.get("target_quality_label"),
            "direction": "positive" if data.get("support_status") in {"supported", "partially_supported"} else "mixed",
            "credibility_weight": 0.75,
            "numeric_weight": 0.7,
            "sort_order": 10,
        },
        {
            "metric_name": "证实情景动作",
            "metric_category": "scenario_confirm",
            "value_text": data["confirmed_scenario_action"],
            "unit": "文本",
            "source_title": source_title,
            "source_publisher": "Opportunity Lens",
            "source_excerpt": data["confirmed_scenario_action"],
            "evidence_ref_uri": ref,
            "data_quality_label": "条件化建议",
            "direction": "positive",
            "credibility_weight": 0.7,
            "numeric_weight": 0.7,
            "sort_order": 20,
        },
        {
            "metric_name": "证伪情景动作",
            "metric_category": "scenario_falsify",
            "value_text": data["falsified_scenario_action"],
            "unit": "文本",
            "source_title": source_title,
            "source_publisher": "Opportunity Lens",
            "source_excerpt": data["falsified_scenario_action"],
            "evidence_ref_uri": ref,
            "data_quality_label": "条件化建议",
            "direction": "negative",
            "credibility_weight": 0.7,
            "numeric_weight": 0.7,
            "sort_order": 30,
        },
        {
            "metric_name": "主要风险",
            "metric_category": "risk",
            "value_text": data["risk_note"],
            "unit": "文本",
            "source_title": source_title,
            "source_publisher": "Opportunity Lens",
            "source_excerpt": data["risk_note"],
            "evidence_ref_uri": ref,
            "data_quality_label": "风险提示",
            "direction": "negative",
            "credibility_weight": 0.7,
            "numeric_weight": 0.7,
            "sort_order": 40,
        },
        {
            "metric_name": "同实体内相对优先级",
            "metric_category": "relative_preference",
            "value_text": data["relative_preference"],
            "unit": "文本",
            "source_title": source_title,
            "source_publisher": "Opportunity Lens",
            "source_excerpt": data["relative_preference"],
            "evidence_ref_uri": ref,
            "data_quality_label": data.get("target_priority"),
            "direction": "mixed",
            "credibility_weight": 0.7,
            "numeric_weight": 0.7,
            "sort_order": 50,
        },
    ]


def _company_financial_points(data: dict) -> list[dict]:
    company_id = data.get("company_id")
    if not company_id or not RESEARCH_DB_PATH.exists():
        return []
    conn = sqlite3.connect(RESEARCH_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT name, ticker, market_cap_cny, market_cap_usd, pe_ttm, pb, ps_ttm,
                   roe, valuation_as_of, market_cap_cny_as_of
            FROM company
            WHERE id=?
            """,
            (company_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return []
    source_title = f"A/B 行研库 company 快照：{row['name']}"
    as_of = row["market_cap_cny_as_of"] or row["valuation_as_of"]
    metrics = [
        ("市值人民币", "financial_market_cap", row["market_cap_cny"], "CNY", "neutral", 60),
        ("市值美元", "financial_market_cap", row["market_cap_usd"], "USD", "neutral", 61),
        ("PE TTM", "financial_valuation", row["pe_ttm"], "倍", "mixed", 62),
        ("PB", "financial_valuation", row["pb"], "倍", "mixed", 63),
        ("PS TTM", "financial_valuation", row["ps_ttm"], "倍", "mixed", 64),
        ("ROE", "financial_quality", row["roe"], "%", "positive" if row["roe"] and row["roe"] > 0 else "mixed", 65),
    ]
    points = []
    for metric_name, category, value, unit, direction, sort_order in metrics:
        if value is None:
            continue
        points.append({
            "metric_name": metric_name,
            "metric_category": category,
            "as_of_date": as_of,
            "value_num": float(value),
            "unit": unit,
            "source_title": source_title,
            "source_publisher": "A/B research.db",
            "source_excerpt": f"{row['name']} {metric_name} 为 {value}{unit}，快照日期 {as_of or '未标明'}。",
            "evidence_ref_uri": f"ab://research.company/{company_id}",
            "data_quality_label": "A/B 只读财务快照",
            "direction": direction,
            "credibility_weight": 0.8,
            "numeric_weight": 1.0,
            "sort_order": sort_order,
        })
    return points


def _target_data_points(data: dict) -> list[dict]:
    points = _base_target_data_points(data) + _company_financial_points(data)
    for point in points:
        direction = point.get("direction", "neutral")
        direction_score = {"positive": 1.0, "negative": -1.0, "mixed": 0.0, "neutral": 0.0}.get(direction, 0.0)
        point["direction_score"] = direction_score
        point["weighted_contribution"] = round(
            float(point.get("credibility_weight", 0.7)) * float(point.get("numeric_weight", 0.7)) * direction_score,
            4,
        )
    return points


def _target_dict(row: tuple) -> dict:
    (
        run_id, entity_id, target_name, ticker, market, target_type, company_id, target_url,
        exposure_rationale, evidence_ref_uri, research_action, investment_view, risk_note,
        link_status, support_status, sort_order,
    ) = row
    context = ENTITY_TARGET_CONTEXT[(run_id, entity_id)]
    data = {
        "run_id": run_id,
        "entity_id": entity_id,
        "target_name": target_name,
        "ticker": ticker,
        "market": market,
        "target_type": target_type,
        "company_id": company_id,
        "target_url": target_url,
        "exposure_rationale": exposure_rationale,
        "evidence_ref_uri": evidence_ref_uri,
        "research_action": research_action,
        "investment_view": investment_view,
        "risk_note": risk_note,
        "target_priority": _target_priority(sort_order, support_status),
        "target_quality_label": _target_quality_label(target_type, support_status),
        "relative_preference": f"同实体内比较：该标的服务于“{context['theme']}”研究，排序第 {sort_order}。优先级取决于直接暴露、证据支持度和是否能验证核心假设。",
        "confirmed_scenario_action": context["confirm"],
        "falsified_scenario_action": context["falsify"],
        "link_status": link_status,
        "support_status": support_status,
        "sort_order": sort_order,
    }
    data.update(TARGET_SPECIFIC_PATCHES.get((run_id, entity_id, target_name), {}))
    data["target_profile_markdown"] = _target_profile_markdown(data, context)
    data["target_deep_research_markdown"] = _target_deep_research_markdown(data, context)
    data["entity_relation_markdown"] = _entity_relation_markdown(data, context)
    data["parent_research_relation_markdown"] = _parent_relation_markdown(data, context)
    data["conditional_investment_recommendation"] = _conditional_recommendation(data, context)
    data["financial_data_status"] = _financial_data_status(data)
    data["target_data_points"] = _target_data_points(data)
    return data


def _iter_target_dicts(run_id: int | None = None) -> list[dict]:
    targets = [_target_dict(row) for row in ENTITY_TARGETS]
    if run_id is not None:
        targets = [target for target in targets if target["run_id"] == run_id]
    return targets


def _source_info_for_ref(conn: sqlite3.Connection | None, ref: str | None) -> dict:
    if not ref:
        return {
            "source_title": "未匹配来源",
            "publisher": "未标明发布方",
            "publish_date": "未标明时间",
            "excerpt": "该证据尚未匹配到可展示的来源摘录。",
            "evidence_ref": ref,
        }
    if ref.startswith("ab://research.data_point/"):
        return _ab_data_point_info(ref)
    if ref.startswith("ab://research.source/"):
        return _ab_source_info(ref)
    row = None
    if ref.startswith("opp://source/") and conn is not None:
        try:
            source_id = int(ref.rsplit("/", 1)[1])
        except ValueError:
            source_id = None
        if source_id:
            row = conn.execute(
                "SELECT id, title, publisher, publish_date, excerpt FROM opportunity_source WHERE id=?",
                (source_id,),
            ).fetchone()
    elif (ref.startswith("http://") or ref.startswith("https://")) and conn is not None:
        row = conn.execute(
            "SELECT id, title, publisher, publish_date, excerpt FROM opportunity_source WHERE url=? ORDER BY id LIMIT 1",
            (ref,),
        ).fetchone()
    if not row:
        return {
            "source_title": "未匹配来源",
            "publisher": "未标明发布方",
            "publish_date": "未标明时间",
            "excerpt": "该证据尚未匹配到可展示的来源摘录。",
            "evidence_ref": ref,
        }
    return {
        "source_title": row[1] or "未标明来源标题",
        "publisher": row[2] or "未标明发布方",
        "publish_date": row[3] or "未标明时间",
        "excerpt": row[4] or "该来源尚未录入可展示摘录。",
        "evidence_ref": f"opp://source/{row[0]}",
    }


def _canonical_ref(conn: sqlite3.Connection | None, ref: str) -> str:
    if not conn or not (ref.startswith("http://") or ref.startswith("https://")):
        return ref
    row = conn.execute(
        "SELECT id FROM opportunity_source WHERE url=? ORDER BY id LIMIT 1",
        (ref,),
    ).fetchone()
    if row:
        return f"opp://source/{row[0]}"
    return ref


def _ab_data_point_info(ref: str) -> dict:
    try:
        dp_id = int(ref.rsplit("/", 1)[1])
    except ValueError:
        dp_id = None
    if not dp_id or not RESEARCH_DB_PATH.exists():
        return _ab_missing_info(ref)
    conn = sqlite3.connect(RESEARCH_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT dp.id, dp.metric, dp.period, dp.as_of_date, dp.value_num, dp.value_text,
                   dp.unit, dp.source_excerpt, dp.source_id,
                   s.title, s.publisher, s.publish_date, s.source_url, s.file_path
            FROM industry_data_point dp
            LEFT JOIN source s ON s.id=dp.source_id
            WHERE dp.id=?
            """,
            (dp_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return _ab_missing_info(ref)
    value = row["value_text"] if row["value_text"] is not None else row["value_num"]
    metric_line = f"指标：{row['metric']}；期间：{row['period'] or row['as_of_date'] or '未标明'}；数值：{value}{row['unit'] or ''}"
    return {
        "source_title": row["title"] or f"A/B 数据点 {dp_id}",
        "publisher": row["publisher"] or "A/B 行研库",
        "publish_date": row["publish_date"] or row["as_of_date"] or row["period"] or "未标明时间",
        "excerpt": row["source_excerpt"] or "A/B 数据点缺少 source_excerpt，必须回源补录后才能提高证据等级。",
        "metric_line": metric_line,
        "evidence_ref": ref,
    }


def _ab_source_info(ref: str) -> dict:
    try:
        source_id = int(ref.rsplit("/", 1)[1])
    except ValueError:
        source_id = None
    if not source_id or not RESEARCH_DB_PATH.exists():
        return _ab_missing_info(ref)
    conn = sqlite3.connect(RESEARCH_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT id, title, publisher, publish_date, source_url, file_path, source_credibility
            FROM source
            WHERE id=?
            """,
            (source_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return _ab_missing_info(ref)
    return {
        "source_title": row["title"] or f"A/B 来源 {source_id}",
        "publisher": row["publisher"] or "A/B 行研库",
        "publish_date": row["publish_date"] or "未标明时间",
        "excerpt": f"该证据为 A/B 行研库来源记录，标题为“{row['title']}”，可信度字段为 {row['source_credibility'] or '未标明'}；需要引用具体数字时应优先绑定该来源下的数据点。",
        "metric_line": f"来源记录：{row['title'] or source_id}",
        "evidence_ref": ref,
    }


def _ab_missing_info(ref: str) -> dict:
    return {
        "source_title": "A/B 行研库证据未匹配",
        "publisher": "A/B 行研库",
        "publish_date": "未标明时间",
        "excerpt": "该 A/B 证据未在 research.db 中读到具体记录，必须回源补录后才能用于高置信展示。",
        "metric_line": "待补",
        "evidence_ref": ref,
    }


def _local_source_id_for_ab_dp(conn: sqlite3.Connection, run_id: int, ab_source_id: int | None, title: str | None, publisher: str | None, publish_date: str | None) -> int | None:
    if not title:
        return None
    row = conn.execute(
        """
        SELECT id FROM opportunity_source
        WHERE run_id=? AND (title=? OR url=?)
        ORDER BY id LIMIT 1
        """,
        (run_id, title, f"ab://research.source/{ab_source_id}" if ab_source_id else None),
    ).fetchone()
    if row:
        return int(row[0])
    cur = conn.execute(
        """
        INSERT INTO opportunity_source(
          run_id, title, source_tier, source_review_status, publisher,
          publish_date, url, excerpt, language, evidence_ref_uri,
          policy_evidence_role, policy_gate_verdict, scoring_eligibility
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            run_id,
            title,
            "B",
            "pass_with_note",
            publisher,
            publish_date,
            f"ab://research.source/{ab_source_id}" if ab_source_id else None,
            "从 A/B 行研库只读镜像而来，用于 C 轨页面展示和审计。",
            "zh-CN",
            "",
            "core_evidence",
            "pass_core",
            "core_eligible",
        ),
    )
    source_id = int(cur.lastrowid)
    conn.execute("UPDATE opportunity_source SET evidence_ref_uri=? WHERE id=?", (f"opp://source/{source_id}", source_id))
    return source_id


def _mirror_ab_data_point(conn: sqlite3.Connection, run_id: int, entity_id: int, ref: str) -> None:
    if not ref.startswith("ab://research.data_point/") or not RESEARCH_DB_PATH.exists():
        return
    existing = conn.execute(
        """
        SELECT id FROM opportunity_data_point
        WHERE run_id=? AND entity_id=? AND evidence_ref_uri=?
        LIMIT 1
        """,
        (run_id, entity_id, ref),
    ).fetchone()
    if existing:
        return
    try:
        dp_id = int(ref.rsplit("/", 1)[1])
    except ValueError:
        return
    ab_conn = sqlite3.connect(RESEARCH_DB_PATH)
    ab_conn.row_factory = sqlite3.Row
    try:
        row = ab_conn.execute(
            """
            SELECT dp.metric, dp.period, dp.as_of_date, dp.value_num, dp.value_text,
                   dp.unit, dp.source_excerpt, dp.extraction_method, dp.source_id,
                   s.title, s.publisher, s.publish_date
            FROM industry_data_point dp
            LEFT JOIN source s ON s.id=dp.source_id
            WHERE dp.id=?
            """,
            (dp_id,),
        ).fetchone()
    finally:
        ab_conn.close()
    if not row or not row["source_excerpt"]:
        return
    source_id = _local_source_id_for_ab_dp(conn, run_id, row["source_id"], row["title"], row["publisher"], row["publish_date"])
    if not source_id:
        return
    extraction_method = row["extraction_method"] if row["extraction_method"] in {"pdf_direct", "web_fetch", "template_estimate", "inferred", "unknown"} else "inferred"
    conn.execute(
        """
        INSERT INTO opportunity_data_point(
          run_id, entity_id, source_id, metric, period, as_of_date,
          value_num, value_text, unit, source_excerpt, value_status,
          calculation_review_status, extraction_method, evidence_ref_uri,
          policy_evidence_role, policy_gate_verdict, scoring_eligibility
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            run_id,
            entity_id,
            source_id,
            row["metric"],
            row["period"],
            row["as_of_date"],
            row["value_num"],
            row["value_text"],
            row["unit"] or "无",
            row["source_excerpt"],
            "available",
            "pass",
            extraction_method,
            ref,
            "core_evidence",
            "pass_core",
            "core_eligible",
        ),
    )


def _build_factor_trace_patch(
    conn: sqlite3.Connection | None,
    run_id: int,
    entity_id: int,
    factor_code: str,
    trace: dict,
    refs: list[str],
    score: float = 0.0,
    rank: int = 999,
) -> dict:
    context = ENTITY_TARGET_CONTEXT.get((run_id, entity_id), {})
    theme = context.get("theme", "本研究实体")
    label = trace.get("factor_label") or factor_code
    required_refs = _required_factor_refs(score, rank)
    refs = _ensure_factor_refs(run_id, entity_id, refs, score, rank)
    if conn is not None:
        refs = _unique_refs([_canonical_ref(conn, ref) for ref in refs])
    info_points = []
    if conn is not None:
        seen_info = set()
        for ref in refs:
            info = _source_info_for_ref(conn, ref)
            info_key = (info.get("evidence_ref"), info.get("source_title"), info.get("excerpt"))
            if info_key in seen_info:
                continue
            seen_info.add(info_key)
            info_points.append({
                "slot_name": label,
                "excerpt": info["excerpt"],
                "source_title": info["source_title"],
                "publisher": info["publisher"],
                "publish_date": info["publish_date"],
                "metric_line": info.get("metric_line") or "原始来源上下文摘录，用于解释因子和研究主题的关系。",
                "interpretation": (
                    f"{label}引用这条来源时，先判断它支持的是需求、供给、价格、事件还是标的承接。"
                    f"若来源只能证明宽泛行业热度，就保留为补证线索；只有能指向{theme}的对象、时间、口径或标的暴露时才参与评分。"
                ),
                "evidence_ref": info["evidence_ref"],
            })
    patch = {
        "contextual_human_question": f"{theme}：{label}要回答哪一个可核验问题，证据能否落到对象、时间、口径和标的暴露？",
        "contextual_factor_description": f"{label}用来区分{theme}里的叙事线索、可评分证据和需要降级的早期信号。",
        "source_context_summary": f"本因子先核对{theme}相关来源的发布时间、证据对象、指标口径和标的暴露，再决定它是核心证据、早期信号还是补证线索。",
        "factor_topic_analysis": f"{label}在{theme}里承担交叉验证作用：需求、供给、价格、事件和公司承接如果互相支持，可以提高置信度；如果只有二次综合、缺少原文摘录或标的映射，应保留研究优先级但不抬高核心分。",
        "score_rationale": f"{label}的评分依据来自人工核验证据包，重点看来源可追溯性、证据角色、主题相关度，以及 freshness_first 策略是否只允许它作为 early signal。",
        "theme_analysis_points": [
            f"先确认原始来源全文是否真正支持“{theme}”的核心假设，而不是只支持宽泛行业热度。",
            "再检查相邻因子是否同向：需求、供给、价格、事件和公司承接若互相矛盾，应降低评分置信度。",
            "最后映射到具体标的：证实条件决定观察哪些相对强弱、价差、期限结构或公司敞口；证伪条件决定降级、回避或转入补证。",
        ],
        "target_implications": [
            context.get("confirm", "证实后提高相关标的研究优先级。"),
            context.get("falsify", "证伪后降低相关标的研究优先级。"),
        ],
        "source_context_refs": refs,
        "evidence_refs": refs,
        "evidence_weighting": _build_evidence_weighting(score, refs, required_refs),
    }
    if conn is not None:
        patch["information_points"] = info_points
    if (run_id, entity_id, factor_code) == (3, 9, "demand.application_intensity_change"):
        patch.update({
            "contextual_human_question": "霍尔木兹情景是否改变 Brent、Dubai、Oman 等基准的风险溢价和交易强度，而不是简单判断油价是否上涨？",
            "contextual_factor_description": "在该油气事件风险实体中，本因子不是“新应用强度”问题，而是检验风险事件是否已经进入基准价差、月差、波动率或交易行为。",
            "source_context_summary": "EIA STEO 的原始上下文是霍尔木兹受限、库存快速下降和高 Brent 情景；WSJ 价格回落则提示通行恢复和谈判进展压缩风险溢价。ICE、CME 和 GME 页面定义了 Brent、WTI 和 Oman 这些可观察工具。该因子必须把情景假设、现价回落和合约基准放在一起读。",
            "factor_topic_analysis": "对“霍尔木兹风险溢价与 Brent/Dubai/Oman 波动”而言，应用强度变化的上下文应改读为事件风险对基准价差和交易强度的影响。本轮证据显示，高价情景和库存压力仍有解释力，但 7 月市场价格回落说明风险溢价已经被部分压缩。因此该因子不能凭 EIA 高价情景上调，只能作为事件强度是否重新进入价格和波动率的观察项。",
            "score_rationale": "该因子得分偏低是合理处理：EIA 高价情景提供风险假设，WSJ 价格回落提供反向 early signal，ICE/GME/CME 合约页面提供可观察工具，但本轮尚未取得保险费、船期、实际通行量和区域现货价差的连续数据，不能把事件叙事转成高分核心因子。",
            "theme_analysis_points": [
                "证实方向不是单日 Brent 上涨，而是霍尔木兹通行受阻、保险费上行、Brent-Dubai/Oman 价差走阔、近月风险溢价或波动率同步上行。",
                "证伪方向是通行恢复、保险费下降、谈判推进、价差收敛和波动率回落；此时应减少事件溢价暴露，转向库存和炼厂链。",
                "标的映射上，ICE Brent 是事件风险主基准，GME Oman 是中东到亚洲区域基准，CME WTI 主要用于美国库存和 Brent-WTI 对照。",
            ],
        })
    return patch


def _apply_factor_trace_patch(trace: dict, patch: dict) -> dict:
    updated = dict(trace or {})
    force_keys = {
        "information_points",
        "source_context_refs",
        "evidence_refs",
        "evidence_weighting",
        "source_context_summary",
        "factor_topic_analysis",
        "score_rationale",
        "theme_analysis_points",
        "target_implications",
    }
    for key, value in patch.items():
        if value and (key in force_keys or not updated.get(key)):
            updated[key] = value
    return updated

PACK_ENTITY_KEY_BY_ID = {
    2: {
        4: "hbm_12inch_wafer",
        5: "wf6_3d_nand",
        6: "lowcte_tglass_abf",
        7: "cmp_wet_memory",
    },
    3: {
        8: "refining_product_cracks",
        9: "hormuz_brent_dubai_volatility",
        10: "us_inventory_wti_structure",
        11: "asia_oman_sc_basis",
        12: "opec_rebound_overhang",
        13: "macro_demand_fund_positioning",
    },
}


SECTIONS = {
    2: {
        "executive_summary": """本轮不是合成测试，而是按 Opportunity Lens V1.4 intake/evidence_policy 流程生成的人工核验证据包。结论是：未来6个月存储上游材料的机会不应泛化为所有半导体材料，而应集中在三个高优先级方向和一个观察方向。表内每个关键数字后面的短编号都是可点击证据，上标会回到 A/B 行研库数据点或 C 轨来源摘录。

| 排名 | 对象 | 核心判断 | 核心分 | 证据状态 |
|---|---|---|---:|---|
| 1 | HBM 与 AI 服务器用高阶 12 英寸硅片 | 最强。HBM 配套高阶重掺硅片价格上涨 10%-25% ^evidence:ab://research.data_point/11115 ，HBM 对 12 英寸硅片需求为传统 DRAM 的 3 倍 ^evidence:ab://research.data_point/11117 ，AI 服务器 12 英寸硅片需求为通用服务器的 3.8 倍 ^evidence:ab://research.data_point/11116 ，SEMI 确认 AI 数据中心需求推动先进逻辑和存储硅片出货恢复 ^evidence:opp://source/8 | 86 | 可进入核心评分 |
| 2 | 3D NAND 钨填充用 WF6 | 强。新增内存产线对应 WF6 需求 150-300 吨 ^evidence:ab://research.data_point/7607 ，300+ 层 3D NAND 放大钨沉积用量 ^evidence:ab://research.data_point/7606 ，但供应端价格、主流供应商开工率和合同锁单仍需补证 | 76 | 有限评分 |
| 3 | Low CTE/T 布与 ABF/HVLP | 中强。T 布供需缺口 41% ^evidence:ab://research.data_point/6869 ，高阶 BT 材料交期 16-20 周 ^evidence:ab://research.data_point/6898 ，但部分证据来自先进封装而非存储专属，需把 HBM 先进封装链和通用 AI 加速器链分开 | 72 | 有限评分加早期信号 |
| 4 | CMP/湿化学品 | 观察。存储扩产带来后周期材料消耗 ^evidence:ab://research.data_point/7464 ，但缺少未来6个月短缺、涨价、交期或客户抢货的一手证据 ^evidence:ab://research.data_point/7467 | 54 | 研究观察 |

研究含义：高阶硅片是当前最接近“供需失衡可投资机会”的方向；WF6 是补证优先级最高的材料；Low CTE/T 布更像 HBM 先进封装链条的交叉机会；CMP/湿化学品不能用存储涨价叙事直接推成短缺机会。""",
        "evidence_policy": """本研究采用 freshness_first，但严格执行 V1.4 隔离规则：新鲜但弱的资料只能进入 early_signal_score 和 research_priority_score，不能进入核心 14 因子 raw score。

核心证据包括：SEMI 官方硅片出货 ^evidence:opp://source/8 、TrendForce 公开价格与供需信息 ^evidence:opp://source/6 、A/B 行研库中已入库的数据点和原始研报 ^evidence:ab://research.data_point/11115 。早期信号包括：二次综合的 ABF/HVLP 缺口 ^evidence:ab://research.source/588 、部分尚未获得官方确认的涨价谈判和交期线索。仅参考证据包括：CMP 材料价值占比和国产替代信息，它解释产业位置，但不能证明未来6个月全球短缺。

处理原则是：能逐字追到原文摘录的数字才进入核心表；二次综合、行业传闻和无法定位的价格线索只能触发补证任务。这样做会降低短期结论的“热度”，但能防止把弱证据伪装成强评分。""",
        "entity_analysis": """高阶 12 英寸硅片：这是最强结论。证据链从 AI 数据中心需求、HBM 对硅片用量强度、AI 服务器用量倍数、供应商集中、价格上涨五个角度闭合。HBM 对 12 英寸硅片需求为传统 DRAM 的 3 倍 ^evidence:ab://research.data_point/11117 ，AI 服务器需求为通用服务器的 3.8 倍 ^evidence:ab://research.data_point/11116 ，价格信号为 10%-25% ^evidence:ab://research.data_point/11115 。SEMI 的行业层数据说明先进逻辑和存储需求已经开始影响硅片出货 ^evidence:opp://source/8 。关键风险是总量硅片出货恢复可能掩盖高阶结构性紧缺，因此跟踪时必须盯高阶重掺、HBM 配套、客户认证和供应商扩产窗口，不看普通硅片总量。

WF6：逻辑清晰但证据未完全闭合。3D NAND 300+ 层让钨沉积用量增加 ^evidence:ab://research.data_point/7606 ，一条新增内存产线对应 150-300 吨 WF6 额外需求 ^evidence:ab://research.data_point/7607 ，说明需求弹性高。短板是缺少 2026 下半年供应商产能、合同价、长协锁单和客户备货强度证据。当前分数高于普通观察项，但不能和硅片同等置信；后续如果拿不到供应端证据，应保持“有限评分”。

Low CTE/T 布与 ABF/HVLP：AI 封装材料涨价和缺口明显。T 布供需缺口 41% ^evidence:ab://research.data_point/6869 ，Low CTE 相关需求来自高端封装材料升级 ^evidence:ab://research.data_point/6872 ，高阶 BT 材料交期 16-20 周 ^evidence:ab://research.data_point/6898 。但与存储的关系需要通过 HBM 先进封装来解释，不能把所有 AI 封装材料都算作存储材料短缺。T 布和 Low CTE 证据相对更强，ABF/HVLP 应作为早期信号和补证方向。

CMP/湿化学品：这类材料更像后周期 Opex 受益，不是本轮短缺主线。存储扩产会增加 CMP 和湿化学品用量 ^evidence:ab://research.data_point/7464 ，但目前只看到产业位置和消耗逻辑 ^evidence:ab://research.data_point/7467 ，缺少未来6个月交期、涨价或客户抢货证据。除非后续出现存储原厂材料采购、报价、库存或交付口径，否则不应进入高分机会清单。""",
        "beneficiaries_and_risks": """受益路径应按材料和产业位置拆解，并落到可观察标的。硅片方向优先研究能够稳定供应高阶 12 英寸、重掺或 HBM 配套硅片的厂商与设备/材料配套链；WF6 关注电子特气和含氟前驱体的合格供应商；Low CTE/T 布关注高端电子布、封装基板上游和认证客户；CMP/湿化学品只保留观察。

主要反证：一是存储价格上涨如果压制终端需求，会削弱材料补库持续性 ^evidence:ab://research.data_point/1734 ；二是原厂 HBM 和 NAND 扩产如果快于预期，会把材料紧缺窗口缩短 ^evidence:ab://research.data_point/1735 ；三是普通硅片出货恢复不等于高阶硅片紧缺缓解，需防止口径错配 ^evidence:opp://source/8 ；四是先进封装材料的机会可能来自 AI 加速器整体，而非存储独立驱动 ^evidence:ab://research.data_point/6847 。""",
        "monitoring_and_debts": """优先监控指标：

| 优先级 | 监控信号 | 证实/证伪条件 | 预计变化/监控时间 | 研究响应 | 交易操作框架 | 证据 |
|---|---|---|---|---|---|---|
| 高 | HBM 配套高阶硅片交期、价格、主要供应商产能 | 价格继续上行或交期拉长，证实高阶硅片紧缺；价格回落、交期缩短或新增产能顺利释放，证伪高分假设 | 2026Q2 和 2026Q3 财报季、月度合约价更新、主要客户 HBM 产能会议后复核 | 补公司敞口、客户认证、产能兑现和普通硅片口径剔除证据 | 证实时把交易观察从普通半导体材料收敛到高阶硅片供应链，优先看高阶硅片相关公司相对半导体材料篮子的强弱；证伪时降低主题暴露，避免用普通硅片总量恢复追逐高阶紧缺叙事 | 当前价格信号为 10%-25% ^evidence:ab://research.data_point/11115 ，SEMI 口径提供行业层背景 ^evidence:opp://source/8 |
| 高 | WF6 合同价、主要供应商开工率、韩国和中国新增内存线节奏 | 合同价上行、供应商满产或长协锁量，证实 WF6 从需求弹性进入供应约束；价格平稳且产能宽松，证伪短缺假设 | 2026H2 内存原厂 capex 更新、电子特气供应商中报和三季报、月度价格跟踪 | 寻找供应商长协、订单、客户锁量和新增产线投产证据 | 证实时把 WF6 供应商加入交易观察池，优先看电子特气/WF6 暴露公司相对存储指数的确认；证伪时只保留 3D NAND 层数升级的中长期研究，不用短缺逻辑做单边交易 | 新增产线需求口径为 150-300 吨 ^evidence:ab://research.data_point/7607 ，层数提升带来用量放大 ^evidence:ab://research.data_point/7606 |
| 中 | T 布和 Low CTE 电子布报价、交期、客户认证 | 报价上行且交期延长，证实先进封装材料交叉机会；报价回落或客户认证放缓，证伪短期紧缺 | 2026Q2/Q3 CCL、电子布、封装基板厂商财报和月度报价窗口 | 拆分 HBM 专属需求和通用 AI 封装需求，避免把两条链混算 | 证实时用先进封装材料篮子做相对强弱观察；存储专属证据不足前，不把它直接当作存储材料主线交易；证伪时退回早期信号和补证清单 | T 布缺口口径为 41% ^evidence:ab://research.data_point/6869 ，高阶 BT 材料交期 16-20 周 ^evidence:ab://research.data_point/6898 |
| 中 | ABF/HVLP 是否有原厂或一手行业机构确认 | 一手确认缺口扩大，证实 ABF/HVLP 可进入核心补评分；仍只有二次综合，证伪核心评分资格 | 每次封装基板和 PCB 厂商财报后复核，重大客户平台发布后复核 | 只接受原厂、客户、交易所公告或可定位研报原文，未确认前不并入核心 14 因子 | 只有一手证据确认后才进入交易观察池；未确认前只作为催化剂监控，不用二次综合数字做交易触发 | 当前主要是二次综合来源 ^evidence:ab://research.source/588 |
| 低 | CMP/湿化学品存储客户订单、价格和交期 | 存储客户订单、价格、交期同时上行，证实从后周期受益升级为短缺候选；只有扩产叙事，证伪升级 | 存储原厂扩产公告后、材料供应商中报和三季报后复核 | 补存储客户订单、报价和交期数据点并重新评分 | 只有订单、价格和交期共振时才进入后周期材料交易观察；否则只作为收入弹性研究，不按短缺交易处理 | 当前只支持后周期消耗逻辑 ^evidence:ab://research.data_point/7467 |

当前没有 P0/P1 发布阻断；P2 验证债务集中在 WF6 供应端、ABF/HVLP 一手证据和 CMP 存储专属短缺证据。交易操作框架按证实/证伪条件执行：证据继续强化时提高相关标的研究和相对强弱观察优先级；证据被证伪时降低主题暴露、回到补证清单或剔除该实体。""",
    },
    3: {
        "executive_summary": """本轮输出条件化投资研究建议：在库存、期限结构、价差、事件风险和资金拥挤度得到证实时，优先研究相应期货基准、价差和产品链相对强弱；在通行恢复、库存回补、价差收敛或 OPEC+ 供给压力兑现时，降低事件溢价暴露并转向防守或补证。石油市场的关键矛盾是：基本面库存仍紧，但 7 月初价格已经因霍尔木兹通行恢复和谈判进展显著回落。因此，不能简单使用 6 月高油价情景推导单边机会。表内每个关键价格、库存和政策口径都带可点击证据上标。

| 排名 | 对象 | 核心判断 | 核心分 | 证据状态 |
|---|---|---|---:|---|
| 1 | 美国炼厂高开工与成品油裂解价差 | 库存低、炼厂开工率 96.6%，产品端比原油 outright 更有结构性 ^evidence:opp://source/18 | 78 | 可进入核心评分 |
| 2 | 霍尔木兹风险溢价与 Brent/Dubai/Oman 波动 | 风险仍在，但 7 月初 Brent 约 71.80 美元/桶、WTI 约 68.69 美元/桶，说明风险溢价已被压缩 ^evidence:opp://source/24 | 74 | 有限评分 |
| 3 | 美国原油库存低位与 WTI 近月结构 | 美国商业原油库存低于五年均值 7%，近月有支撑 ^evidence:opp://source/18 ，但资金退潮限制确定性 ^evidence:opp://source/20 | 70 | 可进入核心评分 |
| 4 | OPEC+ 政策弹性与 2027 供应反弹 | OPEC+ 7 月调整 18.8 万桶/日 ^evidence:opp://source/19 ，IEA 预计 2027 年供应反弹约 8 百万桶/日 ^evidence:opp://source/17 | 61 | 风险监控 |
| 5 | 亚洲 Oman/Dubai/SC 区域基准错配 | Oman 可验证，Dubai/SC 实时曲线不足，适合作为区域价差监控 ^evidence:opp://source/21 | 58 | 有限评分 |
| 6 | 宏观需求回落与基金仓位去拥挤 | CFTC 持仓显示拥挤度回落 ^evidence:opp://source/20 ，主要是风险项 | 50 | 观察 |

研究含义：未来6个月更值得监控的是产品裂解价差、库存和期限结构，而不是只看 Brent 或 WTI 的单一方向。""",
        "regime_conflict": """EIA 和 IEA 的 6 月资料仍显示库存极低、供应受扰和高风险溢价：EIA 预计 2Q26 全球库存平均下降 6.3 百万桶/日，OECD 库存天数年底降至 50 天 ^evidence:opp://source/16 ；IEA 预计 5 月全球观察库存下降 143 百万桶 ^evidence:opp://source/17 。

但 7 月初市场价格已经显著回落。WSJ 报道 WTI 约 68.69 美元/桶、Brent 约 71.80 美元/桶，并指出霍尔木兹通行恢复和美伊谈判进展压缩风险溢价 ^evidence:opp://source/24 。这与 EIA 6 月 STEO 中 6-7 月 Brent 均值约 105 美元/桶的情景发生冲突 ^evidence:opp://source/16 。

处理方式：EIA 的高价路径保留为“霍尔木兹受阻和库存低位情景”；7 月市场价格作为 early signal 显示风险溢价已被压缩。核心评分不直接采用媒体价格来抬分，而用它提示情景切换风险。""",
        "opportunities_and_risks": """成品油和炼厂链条：美国炼厂开工率 96.6%，商业原油库存低于五年均值 7%，汽油和馏分油库存也低于五年均值 ^evidence:opp://source/18 。这说明产品端仍有强约束：若原油 outright 因供应恢复被压制，裂解价差和成品油现货升贴水仍可能保留结构性波动。反证是炼厂高开工本身也可能快速补产品库存，因此不能只看单周库存下降。

霍尔木兹和 Brent/Dubai/Oman：库存低位和通行风险使风险溢价不能完全归零 ^evidence:opp://source/16 ，但价格回落说明市场已开始交易恢复情景 ^evidence:opp://source/24 。这里的机会是波动率、区域基准和现货差价的再定价，不是线性看多。若通行、保险费和船期恢复，Brent/Dubai/Oman 风险溢价应继续压缩；若出现新的制裁、军事或运输扰动，则要把事件风险重新拉入高优先级。

WTI 近月结构：美国库存低和炼厂高开工支持近月 ^evidence:opp://source/18 ，但 CFTC 显示 Managed Money 多头下降、空头上升，说明资金拥挤度回落 ^evidence:opp://source/20 。这意味着近月支撑和资金退潮同时存在，适合监控价差和库存，不适合只写单边方向。

OPEC+ 与 2027 供应反弹：OPEC+ 7 国 7 月实施 18.8 万桶/日调整 ^evidence:opp://source/19 ，IEA 预计 2027 年供应反弹约 8 百万桶/日 ^evidence:opp://source/17 。这是压制远期价格和单边风险溢价的主要反证。若 OPEC+ 后续暂停或逆转退出，远月压力会下降；若继续增产，低库存只能支撑近月，难以支撑完整远期曲线。""",
        "monitoring": """| 优先级 | 监控信号 | 证实/证伪条件 | 预计变化/监控时间 | 研究响应 | 交易操作框架 | 证据 |
|---|---|---|---|---|---|---|
| 高 | 美国商业原油库存、Cushing、汽油和馏分油库存、炼厂开工率 | 库存继续下降且炼厂开工维持高位，证实近月和裂解价差支撑；库存回升或炼厂开工下滑，证伪近月强支撑 | 下一次 EIA Weekly Petroleum Status Report 为 2026-07-08；之后按 EIA 常规每周三 10:30 ET 跟踪，节假日可能顺延 | 拆分出口、SPR、炼厂开工和产品库存，避免把单周库存变化直接外推 | 证实时优先观察近月强于远月、裂解价差或产品链相对强弱；证伪时降低 WTI 近月多头假设，避免在库存回补阶段追逐单边上涨 | 当前库存低于五年均值 7%，炼厂开工率 96.6% ^evidence:opp://source/18 |
| 高 | Brent/WTI 近远月价差、Brent-Dubai/Oman 价差 | 近月升水扩大或区域价差走阔，证实风险溢价和库存约束恢复；价差收敛，证伪事件溢价 | ICE Brent、CME WTI 和 GME Oman 每日收盘后复核，重大中东事件当天复核 | 拆分库存驱动、区域现货驱动和地缘驱动，避免只看 outright 价格 | 证实时优先观察月差、Brent-Dubai/Oman 相对价差或跨品种结构；证伪时减少事件溢价暴露，把研究重心转回库存和炼厂链 | ICE、CME、GME 是本轮基准参考 ^evidence:opp://source/23 ^evidence:opp://source/22 ^evidence:opp://source/21 |
| 高 | 霍尔木兹通行量、保险费、船期和美伊谈判进展 | 通行受阻、保险费上行或谈判恶化，证实风险溢价重燃；通行恢复、保险费下降或谈判推进，证伪高价情景 | 航运和保险数据需日度跟踪；美伊谈判、制裁公告和军事事件发生后即时复核 | 把 EIA 高价情景和 7 月市场价格回落分开建模 | 风险重燃时观察事件波动率、Brent 相对 Dubai/Oman 和近月风险溢价；风险缓和时降低事件溢价交易权重，不用 6 月高价情景解释 7 月价格 | EIA 高价情景和 WSJ 价格回落形成情景冲突 ^evidence:opp://source/16 ^evidence:opp://source/24 |
| 中 | OPEC+ 实际执行率、增产节奏和下一次会议表态 | 增产继续或执行率偏低，证实远期供应压力；暂停或逆转退出，证伪远月压力 | 已入库官方源确认 2026-06-07 会议和 7 月 18.8 万桶/日调整；下一次产量会议日期需等 OPEC 官方公告，月报和临时公告至少每周复核 | 重算远月供给风险，区分近月低库存和远月供应反弹 | 增产延续时避免把近月库存紧张直接外推到整条远期曲线；暂停或逆转时重新观察远月空头压力释放和曲线再陡峭化 | OPEC+ 7 月产量调整 ^evidence:opp://source/19 ，IEA 2027 供应反弹情景 ^evidence:opp://source/17 |
| 中 | CFTC Managed Money 净多、交易所保证金和波动率 | 净多回升且波动率上行，证实资金拥挤和强平风险；净多下降且波动率低，证伪单边动能 | CFTC COT 通常每周五 15:30 ET 发布，覆盖前一周二持仓；保证金和波动率按交易所日度跟踪 | 不把价格上涨直接解释为基本面，单独标记资金驱动 | 拥挤上升时避免追涨追跌，优先使用定义风险的价差或期权框架；拥挤下降时降低动量交易权重，但保留基本面触发后的再进入观察 | CFTC 当前显示多头下降、空头上升 ^evidence:opp://source/20 |
| 中 | SC 原油、Dubai/Oman 现货贴水和亚洲炼厂开工 | 亚洲贴水扩大或炼厂开工回升，证实区域现货结构改善；贴水收窄或开工下行，证伪区域机会 | 亚洲交易日收盘后日度复核；炼厂月度开工和进口数据发布后复核 | 补 SC、Dubai 一手曲线和亚洲炼厂开工数据，无法拿到实时曲线时保持有限评分 | 只有拿到一手曲线后才考虑区域价差交易观察；证据不足时不把 Oman 单一报价扩展成 SC/Dubai 交易判断 | Oman 可验证，Dubai/SC 实时曲线仍是证据缺口 ^evidence:opp://source/21 |

没有这些指标的连续更新，不应把单日价格报道写成完整机会。交易操作框架按“证实后做什么、证伪后降到哪里”执行，重点是期限结构、跨品种价差、产品链和事件波动率，而不是只用单日 Brent 或 WTI 价格做判断。""",
        "non_advice_boundary": """条件化执行边界与补证优先级：本报告给出研究和交易响应方向，但不直接写账户仓位、目标价或止损位。可执行性取决于后续能否补齐实时期限结构、成交量和持仓曲线、保证金变化、航运和保险费、SC 与 Dubai 现货差价、炼厂利润模型、宏观利率和美元假设。

若实时月差、库存和价差继续同向强化，应提高近月结构、裂解价差和 Brent/Dubai/Oman 相对价差的研究权重；若通行恢复、库存回补、价差收敛或资金退潮继续兑现，应降低事件溢价和单边多头假设，把研究重心转回库存、炼厂链和 OPEC+ 供给弹性。当前已接入的公开参考包括 EIA 周报 ^evidence:opp://source/18 、CFTC 持仓 ^evidence:opp://source/20 、CME WTI ^evidence:opp://source/22 、ICE Brent ^evidence:opp://source/23 和 GME Oman ^evidence:opp://source/21 。未取得上述实时数据前，具体交易触发只能保持为观察条件，不能越过补证闸门。""",
    },
}


def update_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS opportunity_entity_investment_target (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              run_id INTEGER NOT NULL,
              entity_id INTEGER NOT NULL,
              target_name TEXT NOT NULL,
              ticker TEXT,
              market TEXT,
              target_type TEXT NOT NULL CHECK (target_type IN ('company','security','etf','futures_contract','spread','basket','external_watch')),
              company_id INTEGER,
              target_url TEXT,
              exposure_rationale TEXT NOT NULL,
              evidence_ref_uri TEXT,
              research_action TEXT NOT NULL,
              investment_view TEXT NOT NULL,
              risk_note TEXT NOT NULL,
              target_priority TEXT,
              target_quality_label TEXT,
              relative_preference TEXT,
              confirmed_scenario_action TEXT,
              falsified_scenario_action TEXT,
              target_profile_markdown TEXT,
              target_deep_research_markdown TEXT,
              entity_relation_markdown TEXT,
              parent_research_relation_markdown TEXT,
              conditional_investment_recommendation TEXT,
              financial_data_status TEXT,
              link_status TEXT NOT NULL DEFAULT 'linked' CHECK (link_status IN ('linked','external_only','needs_company_profile','needs_evidence','not_applicable')),
              support_status TEXT NOT NULL DEFAULT 'partially_supported' CHECK (support_status IN ('supported','partially_supported','weak','not_applicable')),
              sort_order INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE,
              FOREIGN KEY(entity_id) REFERENCES opportunity_entity(id) ON DELETE CASCADE
            )
            """
        )
        for column in (
            "target_priority",
            "target_quality_label",
            "relative_preference",
            "confirmed_scenario_action",
            "falsified_scenario_action",
            "target_profile_markdown",
            "target_deep_research_markdown",
            "entity_relation_markdown",
            "parent_research_relation_markdown",
            "conditional_investment_recommendation",
            "financial_data_status",
        ):
            cols = {row[1] for row in conn.execute("PRAGMA table_info(opportunity_entity_investment_target)").fetchall()}
            if column not in cols:
                conn.execute(f"ALTER TABLE opportunity_entity_investment_target ADD COLUMN {column} TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS opportunity_target_data_point (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              run_id INTEGER NOT NULL,
              entity_id INTEGER NOT NULL,
              target_id INTEGER NOT NULL,
              metric_name TEXT NOT NULL,
              metric_category TEXT NOT NULL,
              period TEXT,
              as_of_date TEXT,
              value_num REAL,
              value_text TEXT,
              unit TEXT,
              source_title TEXT,
              source_publisher TEXT,
              source_url TEXT,
              source_excerpt TEXT,
              evidence_ref_uri TEXT,
              data_quality_label TEXT,
              direction TEXT NOT NULL DEFAULT 'neutral' CHECK (direction IN ('positive','negative','mixed','neutral')),
              credibility_weight REAL NOT NULL DEFAULT 0.5,
              numeric_weight REAL NOT NULL DEFAULT 0.7,
              direction_score REAL NOT NULL DEFAULT 0,
              weighted_contribution REAL NOT NULL DEFAULT 0,
              sort_order INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              CHECK (value_num IS NOT NULL OR (value_text IS NOT NULL AND value_text <> '')),
              FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE,
              FOREIGN KEY(entity_id) REFERENCES opportunity_entity(id) ON DELETE CASCADE,
              FOREIGN KEY(target_id) REFERENCES opportunity_entity_investment_target(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_opp_entity_target_entity ON opportunity_entity_investment_target(entity_id, sort_order)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_opp_entity_target_run ON opportunity_entity_investment_target(run_id, entity_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_opp_target_dp_target ON opportunity_target_data_point(target_id, sort_order)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_opp_target_dp_run_entity ON opportunity_target_data_point(run_id, entity_id, target_id)")
        for source_id, excerpt in SOURCE_UPDATES.items():
            conn.execute(
                "UPDATE opportunity_source SET excerpt=?, updated_at=datetime('now') WHERE id=?",
                (excerpt, source_id),
            )
        for run_id, sections in SECTIONS.items():
            for section_key, body in sections.items():
                conn.execute(
                    """
                    UPDATE opportunity_report_section
                    SET body_markdown=?
                    WHERE run_id=? AND section_key=?
                    """,
                    (body, run_id, section_key),
                )
        conn.execute(
            """
            DELETE FROM opportunity_section_evidence_link
            WHERE section_id IN (
              SELECT id FROM opportunity_report_section
              WHERE run_id IN (2,3) AND section_key='entity_research_profile'
            )
            """
        )
        conn.execute("DELETE FROM opportunity_report_section WHERE run_id IN (2,3) AND section_key='entity_research_profile'")
        conn.execute("DELETE FROM opportunity_target_data_point WHERE run_id IN (2,3)")
        conn.execute("DELETE FROM opportunity_entity_investment_target WHERE run_id IN (2,3)")
        for run_id, sections in ENTITY_SECTIONS.items():
            for index, section in enumerate(sections, start=1):
                cur = conn.execute(
                    """
                    INSERT INTO opportunity_report_section(
                      run_id, entity_id, section_key, section_title, body_markdown,
                      support_status, red_flag_level, flag_derivation_source, flag_reason_json,
                      review_status, evidence_ref_uri_list_json, sort_order
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        run_id,
                        section["entity_id"],
                        "entity_research_profile",
                        section["section_title"],
                        _polish_entity_body(section["body_markdown"]),
                        section.get("support_status", "supported"),
                        section.get("red_flag_level", "none"),
                        "system",
                        json.dumps(section.get("flag_reason", []), ensure_ascii=False),
                        "approved",
                        json.dumps(section.get("evidence_ref_uri_list", []), ensure_ascii=False),
                        1000 + index * 10,
                    ),
                )
                section_id = int(cur.lastrowid)
                for ref in section.get("evidence_ref_uri_list", []):
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO opportunity_section_evidence_link(section_id, evidence_ref_uri, link_role)
                        VALUES(?,?,?)
                        """,
                        (section_id, ref, "supports"),
                    )
        for target in _iter_target_dicts():
            conn.execute(
                """
                INSERT INTO opportunity_entity_investment_target(
                  run_id, entity_id, target_name, ticker, market, target_type,
                  company_id, target_url, exposure_rationale, evidence_ref_uri,
                  research_action, investment_view, risk_note, target_priority,
                  target_quality_label, relative_preference, confirmed_scenario_action,
                  falsified_scenario_action, target_profile_markdown,
                  target_deep_research_markdown, entity_relation_markdown,
                  parent_research_relation_markdown, conditional_investment_recommendation,
                  financial_data_status, link_status, support_status, sort_order
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    target["run_id"],
                    target["entity_id"],
                    target["target_name"],
                    target["ticker"],
                    target["market"],
                    target["target_type"],
                    target["company_id"],
                    target["target_url"],
                    target["exposure_rationale"],
                    target["evidence_ref_uri"],
                    target["research_action"],
                    target["investment_view"],
                    target["risk_note"],
                    target["target_priority"],
                    target["target_quality_label"],
                    target["relative_preference"],
                    target["confirmed_scenario_action"],
                    target["falsified_scenario_action"],
                    target["target_profile_markdown"],
                    target["target_deep_research_markdown"],
                    target["entity_relation_markdown"],
                    target["parent_research_relation_markdown"],
                    target["conditional_investment_recommendation"],
                    target["financial_data_status"],
                    target["link_status"],
                    target["support_status"],
                    target["sort_order"],
                ),
            )
            target_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            for dp in target["target_data_points"]:
                conn.execute(
                    """
                    INSERT INTO opportunity_target_data_point(
                      run_id, entity_id, target_id, metric_name, metric_category,
                      period, as_of_date, value_num, value_text, unit,
                      source_title, source_publisher, source_url, source_excerpt,
                      evidence_ref_uri, data_quality_label, direction, credibility_weight,
                      numeric_weight, direction_score, weighted_contribution, sort_order
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        target["run_id"],
                        target["entity_id"],
                        target_id,
                        dp["metric_name"],
                        dp.get("metric_category", "target_research"),
                        dp.get("period"),
                        dp.get("as_of_date"),
                        dp.get("value_num"),
                        dp.get("value_text"),
                        dp.get("unit"),
                        dp.get("source_title"),
                        dp.get("source_publisher"),
                        dp.get("source_url"),
                        dp.get("source_excerpt"),
                        dp.get("evidence_ref_uri"),
                        dp.get("data_quality_label"),
                        dp.get("direction", "neutral"),
                        float(dp.get("credibility_weight", 0.7)),
                        float(dp.get("numeric_weight", 0.7)),
                        float(dp.get("direction_score", 0)),
                        float(dp.get("weighted_contribution", 0)),
                        int(dp.get("sort_order", 0)),
                    ),
                )
        factor_rows = conn.execute(
            """
            SELECT id, run_id, entity_id, factor_code, score_adjusted, factor_trace_json, evidence_ref_uri_list_json
            FROM opportunity_factor_score
            WHERE run_id IN (2,3)
            ORDER BY run_id, entity_id, score_adjusted DESC, id
            """
        ).fetchall()
        rank_by_entity: dict[tuple[int, int], int] = {}
        for factor_id, run_id, entity_id, factor_code, score_adjusted, trace_json, refs_json in factor_rows:
            entity_key = (int(run_id), int(entity_id))
            rank_by_entity[entity_key] = rank_by_entity.get(entity_key, 0) + 1
            rank = rank_by_entity[entity_key]
            score = float(score_adjusted or 0)
            trace = json.loads(trace_json or "{}")
            refs = json.loads(refs_json or "[]")
            refs = _ensure_factor_refs(int(run_id), int(entity_id), refs, score, rank)
            refs = _unique_refs([_canonical_ref(conn, ref) for ref in refs])
            for ref in refs:
                _mirror_ab_data_point(conn, int(run_id), int(entity_id), ref)
            patch = _build_factor_trace_patch(conn, int(run_id), int(entity_id), factor_code, trace, refs, score, rank)
            patched_trace = _apply_factor_trace_patch(trace, patch)
            refs_json_new = json.dumps(refs, ensure_ascii=False)
            conn.execute(
                """
                UPDATE opportunity_factor_score
                SET factor_trace_json=?, evidence_ref_uri_list_json=?
                WHERE id=?
                """,
                (json.dumps(patched_trace, ensure_ascii=False, sort_keys=True), refs_json_new, factor_id),
            )
            conn.execute(
                """
                UPDATE opportunity_factor_readiness
                SET evidence_ref_uri_list_json=?
                WHERE run_id=? AND entity_id=? AND factor_code=?
                """,
                (refs_json_new, run_id, entity_id, factor_code),
            )
        conn.commit()
    finally:
        conn.close()


def update_packs() -> None:
    db_conn = sqlite3.connect(DB_PATH)
    try:
        for run_id, path in PACKS.items():
            data = json.loads(path.read_text(encoding="utf-8"))
            if run_id == 3:
                data["problem_statement"] = (
                    "以石油 intake request 为工程合同，使用公开权威来源和最新市场信息扫描 Brent、WTI、Dubai/Oman、SC 原油、"
                    "现货差价、期限结构、近远月价差、库存、OPEC+、美国页岩、地缘政治、制裁、运输、炼厂开工、裂解价差、美元利率、"
                    "宏观需求和资金拥挤度。输出条件化投资研究建议：证实时给出优先观察和交易响应方向，证伪时给出降级、回避或补证路径。"
                )
            for source in data.get("sources", []):
                source_id = source.get("id")
                if source_id in SOURCE_UPDATES:
                    source["excerpt"] = SOURCE_UPDATES[source_id]
                elif source.get("url") in SOURCE_URL_UPDATES:
                    source["excerpt"] = SOURCE_URL_UPDATES[source["url"]]
            for section in data.get("sections", []):
                section_key = section.get("section_key")
                body = SECTIONS.get(run_id, {}).get(section_key)
                if body:
                    section["body_markdown"] = body
            data["entity_sections"] = [
                {
                    "entity_key": PACK_ENTITY_KEY_BY_ID[run_id][section["entity_id"]],
                    "section_key": "entity_research_profile",
                    "section_title": section["section_title"],
                    "sort_order": 1000 + index * 10,
                    "body_markdown": _polish_entity_body(section["body_markdown"]),
                    "support_status": section.get("support_status", "supported"),
                    "red_flag_level": section.get("red_flag_level", "none"),
                    "evidence_ref_uri_list": section.get("evidence_ref_uri_list", []),
                }
                for index, section in enumerate(ENTITY_SECTIONS.get(run_id, []), start=1)
            ]
            data["entity_investment_targets"] = [
                {
                    "entity_key": PACK_ENTITY_KEY_BY_ID[run_id].get(target["entity_id"]),
                    "target_name": target["target_name"],
                    "ticker": target["ticker"],
                    "market": target["market"],
                    "target_type": target["target_type"],
                    "company_id": target["company_id"],
                    "target_url": target["target_url"],
                    "exposure_rationale": target["exposure_rationale"],
                    "evidence_ref_uri": target["evidence_ref_uri"],
                    "research_action": target["research_action"],
                    "investment_view": target["investment_view"],
                    "risk_note": target["risk_note"],
                    "target_priority": target["target_priority"],
                    "target_quality_label": target["target_quality_label"],
                    "relative_preference": target["relative_preference"],
                    "confirmed_scenario_action": target["confirmed_scenario_action"],
                    "falsified_scenario_action": target["falsified_scenario_action"],
                    "target_profile_markdown": target["target_profile_markdown"],
                    "target_deep_research_markdown": target["target_deep_research_markdown"],
                    "entity_relation_markdown": target["entity_relation_markdown"],
                    "parent_research_relation_markdown": target["parent_research_relation_markdown"],
                    "conditional_investment_recommendation": target["conditional_investment_recommendation"],
                    "financial_data_status": target["financial_data_status"],
                    "target_data_points": target["target_data_points"],
                    "link_status": target["link_status"],
                    "support_status": target["support_status"],
                    "sort_order": target["sort_order"],
                }
                for target in _iter_target_dicts(run_id)
                if PACK_ENTITY_KEY_BY_ID[run_id].get(target["entity_id"])
            ]
            entity_id_by_key = {key: entity_id for entity_id, key in PACK_ENTITY_KEY_BY_ID[run_id].items()}
            for entity in data.get("entities", []):
                entity_id = entity_id_by_key.get(entity.get("key"))
                if not entity_id:
                    continue
                factors = sorted(
                    entity.get("factor_scores", []),
                    key=lambda factor: float(factor.get("score_adjusted") or factor.get("score") or 0),
                    reverse=True,
                )
                for rank, factor in enumerate(factors, start=1):
                    trace = {
                        "factor_label": factor.get("factor_label"),
                        "manual_assessment": factor.get("trace"),
                    }
                    score = float(factor.get("score_adjusted") or factor.get("score") or 0)
                    refs = factor.get("evidence_ref_uri_list") or entity.get("evidence_ref_uri_list") or []
                    refs = _ensure_factor_refs(run_id, entity_id, refs, score, rank)
                    refs = _unique_refs([_canonical_ref(db_conn, ref) for ref in refs])
                    factor["evidence_ref_uri_list"] = refs
                    factor["source_context_refs"] = refs
                    factor["evidence_weighting"] = _build_evidence_weighting(score, refs, _required_factor_refs(score, rank))
                    patch = _build_factor_trace_patch(db_conn, run_id, entity_id, factor.get("factor_code"), trace, refs, score, rank)
                    for key, value in patch.items():
                        if value:
                            factor[key] = value
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        db_conn.close()


if __name__ == "__main__":
    update_db()
    update_packs()
    print("published run text repaired")
