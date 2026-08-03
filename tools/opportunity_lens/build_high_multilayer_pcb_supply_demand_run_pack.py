from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit

from tools.opportunity_lens.high_multilayer_pcb_models import calculate
from tools.opportunity_lens.run_pack_builder import RunPackBuilder
from tools.opportunity_lens.silicon_run_pack_support import (
    SEGMENT_FACTOR_CODES,
    build_line_visual,
    build_segment_entity,
    line_chart_panel,
    sha256_file,
    source_uri,
    write_json,
    write_pack_bundle,
)


ROOT = Path(__file__).resolve().parents[2]
AS_OF_DATE = "2026-07-20"
SLUG = "20260720_high_multilayer_pcb_supply_demand_2026_2030"
DISPLAY_TITLE = "AI服务器高多层PCB供需"
OUTPUT_DIR = ROOT / "opportunity_lens" / "research_outputs" / SLUG
INTAKE_PATH = ROOT / "opportunity_lens" / "intake_requests" / "Opportunity_Lens_高多层PCB板（18层以上）供给与需求关系.md"
CACHE_DIR = ROOT / "cache" / "opportunity_lens" / "high_multilayer_pcb_20260720"
LEDGER_SPECS = (
    ("DMD", CACHE_DIR / "agent_demand_bom" / "ledger.json"),
    ("SUP", CACHE_DIR / "agent_supply_company" / "ledger.json"),
    ("OEM", CACHE_DIR / "agent_oem_gap" / "ledger.json"),
)
MARKET_RESEARCH_LEDGER_PATH = CACHE_DIR / "agent_market_price" / "ledger.json"
MODEL_INPUT_PATH = OUTPUT_DIR / "model_inputs.json"
MODEL_OUTPUT_PATH = OUTPUT_DIR / "model_outputs.json"
FINANCIAL_PATH = ROOT / "cache" / "high_multilayer_pcb_research" / "company_financial_series.json"
MARKET_PATH = ROOT / "cache" / "high_multilayer_pcb_research" / "market_snapshots_refresh.json"


DERIVED_SOURCE_PARENT_REF = {
    "DMD-AR009": "DMD-AR008",
    "DMD-AR010": "DMD-AR008",
}

# 联合派生记录保留为本地计算底稿，但证据计数保守并入一个底层原文组。
# 这只影响独立证据组计数；underlying_source_refs 仍完整列出全部输入。
DERIVED_SOURCE_GROUP_PARENT_REF = {
    "DMD-DF006": "DMD-DF001",
    "DMD-AR004": "DMD-AR001",
    "DMD-PB012": "DMD-AR001",
}


def _normalize_public_url(url: str) -> str:
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def _normalize_source_provenance(sources: Sequence[dict[str, Any]]) -> None:
    """Group aliases that resolve to the same underlying public document."""
    sources_by_ref = {str(source["ref"]): source for source in sources}
    for child_ref, parent_ref in DERIVED_SOURCE_PARENT_REF.items():
        child = sources_by_ref.get(child_ref)
        parent = sources_by_ref.get(parent_ref)
        if not child or not parent or child.get("url"):
            continue
        if parent.get("url"):
            child["url"] = parent["url"]
            child.pop("local_path", None)
            child["local_locator"] = f"由{parent_ref}的公开原文数据计算；公式与边界见本条数据点说明。"
            child["date_note"] = "这是由公开原文输入计算的派生量，不增加独立证据数量。"

    for source in sources:
        url = str(source.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        normalized_url = _normalize_public_url(url)
        source["independence_key"] = f"url:{hashlib.sha256(normalized_url.encode('utf-8')).hexdigest()[:24]}"
        source["independence_rationale"] = "同一原始URL及其页码定位统一归为一个底层证据组；别名、翻译和逐项摘录不重复计数。"

    for child_ref, parent_ref in DERIVED_SOURCE_GROUP_PARENT_REF.items():
        child = sources_by_ref.get(child_ref)
        parent = sources_by_ref.get(parent_ref)
        if not child or not parent:
            continue
        child["independence_key"] = parent["independence_key"]
        child["independence_rationale"] = (
            f"该记录由逐项列明的底层证据联合计算，不是新增外部事实；"
            f"为避免高估独立性，证据计数保守并入{parent_ref}的底层原文组。"
        )

    document_families = {
        "delton_hkex_2026": {
            "DMD-DF005", "DMD-PB004", "DMD-PB005", "DMD-PB006", "DMD-PB011",
        },
        "wus_hkex_2026": {
            *{str(source["ref"]) for source in sources if str(source["ref"]).startswith("AB-WUS-")},
        },
    }
    for family, refs in document_families.items():
        key = f"document:{family}"
        for ref in refs:
            source = sources_by_ref.get(ref)
            if source:
                source["independence_key"] = key
                source["independence_rationale"] = "同一份发行申请材料中的公司披露与受托行业研究统一归为一个底层文件；事实层级分别保留，但不互相构成交叉验证。"


TARGET_SPECS: dict[str, dict[str, str]] = {
    "wus": {"entity": "rack_scale_gpu_boards", "market": "深圳证券交易所", "url": "https://www.wuspc.com/", "evidence_ref": "SUP-SUP-WUS-001", "view": "32层以上产品面积和单价同步提升，是当前最透明的高端板经营验证样本；但发行人披露的100层以上是技术能力，不能当作批量收入。"},
    "gold_circuit": {"entity": "rack_scale_gpu_boards", "market": "台湾证券交易所", "url": "https://www.gce.com.tw/", "evidence_ref": "SUP-SUP-GCE-001", "view": "官方材料披露56层多层板能力和较强近期盈利，适合跟踪机架级与交换板需求；具体平台份额仍需客户侧证据。"},
    "shengyi_electronics": {"entity": "rack_scale_gpu_boards", "market": "上海证券交易所科创板", "url": "https://www.sye.com.cn/", "evidence_ref": "SUP-SUP-SYE-001", "view": "数据中心产品与盈利改善提供经营验证，但产品组合仍需与≥18层、纯HDI和普通板严格拆分。"},
    "victory_giant": {"entity": "eight_accelerator_ubb", "market": "深圳证券交易所", "url": "https://www.shpcb.com/", "evidence_ref": "SUP-SUP-VG-001", "view": "32层AI服务器高多层板已有大规模量产；70层只确认研发制造能力，泰国14层以上规划也不能全部计入18层以上有效供给。"},
    "guanghe": {"entity": "eight_accelerator_ubb", "market": "深圳证券交易所", "url": "https://www.delton.com.cn/", "evidence_ref": "SUP-SUP-DELTON-001", "view": "发行材料对UBB、交换板和加速器板层数范围披露较细，是验证8加速器节点BOM的重要标的；客户份额没有直接证据时不量化。"},
    "shennan": {"entity": "custom_asic_system_boards", "market": "深圳证券交易所", "url": "https://www.scc.com.cn/", "evidence_ref": "SUP-SUP-SCC-001", "view": "68层批量能力和数据中心产品基础使其具备高端供给条件；120层样品不能等同于量产，也不能据此推断具名云客户。"},
    "kinwong": {"entity": "custom_asic_system_boards", "market": "上海证券交易所", "url": "https://www.kinwong.com/", "evidence_ref": "SUP-SUP-KW-001", "view": "40层以上高多层和高阶HDI能力覆盖复合结构机会，但必须分别观察严格高多层与局部HDI的收入贡献。"},
    "unimicron": {"entity": "custom_asic_system_boards", "market": "台湾证券交易所", "url": "https://www.unimicron.com/", "evidence_ref": "SUP-SUP-UMC-002", "view": "AI系统板研发方向使其成为观察对象，但本轮一手资料不足以确认18层以上量产规模；载板、HDI与高多层业务边界必须拆开。"},
    "ttm": {"entity": "datacenter_switch_boards", "market": "NASDAQ", "url": "https://investors.ttm.com/", "evidence_ref": "SUP-SUP-TTM-006", "view": "2025年第四季度数据中心计算与网络合计占收入36%，并披露70层以上能力；季度合并口径不能写成全年数据中心单项收入。"},
    "isu_petasys": {"entity": "datacenter_switch_boards", "market": "Korea Exchange", "url": "https://www.isu.co.kr/eng/business/it.jsp", "evidence_ref": "SUP-SUP-ISU-002", "view": "公司定位为超高多层PCB专业制造商，HPC产品资料给出约36层；公开资料没有足够的分客户份额和逐年有效产能。"},
}


ENTITY_SPECS: dict[str, dict[str, Any]] = {
    "rack_scale_gpu_boards": {
        "name": "机架级GPU系统高多层板",
        "description": "覆盖GB200/GB300/NVL与后续机架级架构中的计算板、交换板、中板和背板，只把有依据达到18层以上的刚性板计入。",
    },
    "eight_accelerator_ubb": {
        "name": "8加速器UBB与配套高多层板",
        "description": "覆盖OCP UBB、OAM、HGX和MI300X等8加速器节点，公开尺寸与层数相交后只计18层以上部分。",
    },
    "custom_asic_system_boards": {
        "name": "云厂ASIC与国产算力系统高多层板",
        "description": "覆盖TPU、Trainium、昇腾及国产GPU/ASIC系统；芯片、服务器节点、机柜和云厂自用部署分别记录。",
    },
    "datacenter_switch_boards": {
        "name": "数据中心交换与互联高多层板",
        "description": "覆盖AI集群内高速交换机板、NVLink交换板、PCIe交换板和网络背板，重点观察层数、材料、背钻和客户认证。",
    },
}


FACTOR_LABELS = {
    "demand.downstream_price_momentum": "下游AI系统价格证据与订单背景",
    "demand.customer_capex_capacity_signal": "客户资本开支和算力建设",
    "demand.output_consumption_proxy": "AI服务器与系统部署强度",
    "demand.application_intensity_change": "单节点高多层板用量变化",
    "supply.capacity_event_12m": "未来十二个月有效供给变化",
    "supply.expansion_cycle_bucket": "扩产、爬坡和认证周期",
    "supply.raw_policy_constraint": "材料、工艺与供应约束证据",
    "supply.supplier_structure_bucket": "具备高端交付能力的供应格局",
    "supply.substitution_barrier": "客户切换与量产良率门槛",
    "signal.material_price_momentum": "材料价格证据与工艺升级背景",
}


# 因子证据必须先回答指标本身；不再用关键词把“资本开支”之类的高热度事实
# 自动填进价格、材料或认证指标。每组清单按研究相关性排序，选择时仍会按
# independence_key 去重。AB-WUS 的两条经营序列来自同一份申报材料，因此只算
# 一个独立组；它们可以共同解释面积与单价，但不能被伪装成两组交叉验证。
FACTOR_PREFERRED_REFS = {
    "demand.downstream_price_momentum": (
        "SUP-SUP-SCC-003", "SUP-SUP-DELTON-003", "SUP-SUP-GCE-005", "SUP-SUP-TTM-006",
        "SUP-SUP-UMC-001", "SUP-SUP-ISU-001",
    ),
    "demand.customer_capex_capacity_signal": (
        "DMD-DF009", "DMD-DF010", "DMD-DF011", "DMD-DF012",
        "DMD-DR001", "DMD-DF008", "OEM-OEM001",
    ),
    "demand.output_consumption_proxy": (
        "DMD-DF003", "DMD-DF004", "DMD-DF013", "DMD-DF014", "DMD-DF008",
        "OEM-OEM001", "OEM-OEM006",
    ),
    "demand.application_intensity_change": (
        "DMD-AR001", "DMD-AR006", "DMD-AR008", "DMD-AR011",
        "DMD-AR012", "DMD-AR014", "DMD-AR015", "DMD-DR006",
        "DMD-AR002", "DMD-AR003", "DMD-AR004", "DMD-AR009", "DMD-AR010",
        "DMD-PB008", "DMD-PB009", "DMD-PB012", "SUP-SUP-WUS-006",
    ),
    "supply.capacity_event_12m": (
        "SUP-SUP-SCC-004", "SUP-SUP-WUS-004", "SUP-SUP-SYE-003",
        "SUP-SUP-KW-005", "SUP-SUP-GCE-004", "SUP-SUP-ISU-004",
        "SUP-SUP-DELTON-006", "SUP-SUP-TTM-004", "SUP-SUP-UMC-004",
        "SUP-SUP-VG-004",
    ),
    "supply.expansion_cycle_bucket": (
        "SUP-SUP-WUS-005", "SUP-SUP-SCC-004", "SUP-SUP-SYE-004",
        "SUP-SUP-TTM-005", "SUP-SUP-UMC-003", "SUP-SUP-DELTON-004",
        "SUP-SUP-KW-005",
    ),
    "supply.raw_policy_constraint": (
        "SUP-SUP-TTM-002", "SUP-SUP-SCC-002", "SUP-SUP-WUS-006",
        "SUP-SUP-VG-003", "DMD-PB008", "SUP-SUP-DELTON-001",
        "DMD-DR006", "SUP-SUP-WUS-009",
    ),
    "supply.supplier_structure_bucket": (
        "SUP-SUP-TTM-001", "SUP-SUP-SCC-001", "SUP-SUP-SYE-001",
        "SUP-SUP-VG-001", "SUP-SUP-KW-001", "SUP-SUP-GCE-001",
        "SUP-SUP-ISU-002", "SUP-SUP-DELTON-001", "SUP-SUP-UMC-002",
        "SUP-SUP-WUS-005", "SUP-SUP-UMC-003", "SUP-SUP-DELTON-004",
        "SUP-SUP-WUS-008",
    ),
    "supply.substitution_barrier": (
        "SUP-SUP-WUS-005", "SUP-SUP-UMC-003", "SUP-SUP-DELTON-004",
        "SUP-SUP-VG-005", "SUP-SUP-ISU-005", "SUP-SUP-TTM-005",
        "SUP-SUP-SYE-004", "SUP-SUP-TTM-002", "SUP-SUP-SCC-002",
        "SUP-SUP-VG-003", "SUP-SUP-WUS-008",
    ),
    "signal.material_price_momentum": (
        "AB-WUS-ASP-32PLUS", "AB-WUS-AREA-32PLUS", "DMD-PB008", "DMD-PB009", "SUP-SUP-TTM-002", "SUP-SUP-SCC-002",
        "SUP-SUP-WUS-006", "SUP-SUP-VG-003", "SUP-SUP-DELTON-001",
        "DMD-DR006", "SUP-SUP-ISU-002",
    ),
}


# 只有能够直接回答协议指标槽的数据点才进入该槽。其余来源仍可解释因子背景，
# 但不会继承分数。空映射是有意保留的客观缺口，而不是漏填。
FACTOR_SLOT_REFS = {
    "demand.downstream_price_momentum": {},
    "demand.customer_capex_capacity_signal": {
        "customer_capex_yoy_or_guidance": ("DMD-DF009", "DMD-DF010", "DMD-DF011", "DMD-DF012"),
        "confirmed_capacity_expansion_event": ("DMD-DR001", "DMD-DF008", "OEM-OEM001"),
    },
    "demand.output_consumption_proxy": {},
    "demand.application_intensity_change": {},
    "supply.capacity_event_12m": {
        "planned_or_rumored_capacity": (
            "SUP-SUP-SCC-004", "SUP-SUP-WUS-004", "SUP-SUP-SYE-003",
            "SUP-SUP-KW-005", "SUP-SUP-GCE-004", "SUP-SUP-ISU-004",
            "SUP-SUP-DELTON-006", "SUP-SUP-TTM-004", "SUP-SUP-UMC-004", "SUP-SUP-VG-004",
        ),
    },
    "supply.expansion_cycle_bucket": {
        "expansion_cycle_months_or_bucket": ("SUP-SUP-SYE-004",),
        "qualification_or_ramp_cycle_bucket": ("SUP-SUP-WUS-005", "SUP-SUP-TTM-005", "SUP-SUP-UMC-003", "SUP-SUP-DELTON-004"),
    },
    "supply.raw_policy_constraint": {},
    "supply.supplier_structure_bucket": {
        "qualification_bottleneck_text": ("SUP-SUP-WUS-005", "SUP-SUP-UMC-003", "SUP-SUP-DELTON-004"),
    },
    "supply.substitution_barrier": {
        "process_criticality_bucket": ("SUP-SUP-TTM-002", "SUP-SUP-SCC-002", "SUP-SUP-VG-003"),
        "switching_validation_burden": ("SUP-SUP-WUS-005", "SUP-SUP-UMC-003", "SUP-SUP-DELTON-004", "SUP-SUP-VG-005"),
    },
    "signal.material_price_momentum": {
        "material_price_yoy_change": ("AB-WUS-ASP-32PLUS",),
    },
}


APPLICATION_SLOT_REFS_BY_ENTITY = {
    "rack_scale_gpu_boards": {
        "technology_generation_shift": ("DMD-PB008", "DMD-PB009", "DMD-DR006"),
        "material_intensity_proxy": ("DMD-AR008", "DMD-AR009", "DMD-AR010"),
    },
    "eight_accelerator_ubb": {
        "technology_generation_shift": ("DMD-AR011",),
        "material_intensity_proxy": ("DMD-PB012",),
    },
    "custom_asic_system_boards": {},
    "datacenter_switch_boards": {
        "technology_generation_shift": ("DMD-PB008", "DMD-PB009", "SUP-SUP-WUS-006", "DMD-DR006"),
        "material_intensity_proxy": ("DMD-AR009",),
    },
}


# 同一数据在不同实体中使用同一计分规则。只有应用强度因实体BOM证据不同而采用
# 实体专属规则；这里的差异来自输入事实，而不是先验总分或隐含权重。
SLOT_SCORE_RULES = {
    ("signal.material_price_momentum", "material_price_yoy_change"): (
        60.0,
        "单家公司高层板单价温和上涨",
        "2026Q1同比低于-10%记30分，-10%—0%记45分，0%—10%记60分，高于10%记75分；沪电32层以上ASP同比8.21%，对应60分。",
    ),
    ("demand.customer_capex_capacity_signal", "customer_capex_yoy_or_guidance"): (
        80.0,
        "多家客户维持高资本开支",
        "至少三家独立云厂给出当期高位或增长资本开支指引记80分，两家记65分，一家记55分；本槽有四家。",
    ),
    ("demand.customer_capex_capacity_signal", "confirmed_capacity_expansion_event"): (
        75.0,
        "实物算力扩容已发生",
        "至少两组独立官方资料确认新增容量或已部署系统记75分，只有规划记55分，无直接事件记50分；本槽有三组。",
    ),
    ("supply.expansion_cycle_bucket", "expansion_cycle_months_or_bucket"): (
        85.0,
        "建设和达产周期较长",
        "官方披露从建设到达产超过24个月记85分，12—24个月记70分，少于12个月记55分；生益项目约30个月且分期达产。",
    ),
    ("supply.expansion_cycle_bucket", "qualification_or_ramp_cycle_bucket"): (
        70.0,
        "多家新厂仍在认证或爬坡",
        "至少三组当期官方资料显示认证、导入或爬坡尚未结束记70分，一至两组记60分，无直接资料记50分；本槽有四组。",
    ),
    ("supply.supplier_structure_bucket", "qualification_bottleneck_text"): (
        70.0,
        "认证与爬坡形成现实约束",
        "至少三组当期公司资料显示认证或爬坡未完成记70分，一至两组记60分，无直接资料记50分；本槽有三组。",
    ),
    ("supply.substitution_barrier", "process_criticality_bucket"): (
        75.0,
        "高层板工艺具有多重关键步骤",
        "至少三组直接资料同时覆盖多次压合、低损耗、高层或高阶HDI等关键工艺记75分，一至两组记60分；本槽有三组。",
    ),
    ("supply.substitution_barrier", "switching_validation_burden"): (
        70.0,
        "切换需要重新认证和爬坡",
        "至少三组当期公司资料显示认证、导入或爬坡负担记70分，一至两组记60分，无直接资料记50分；本槽有四组。",
    ),
}


APPLICATION_SLOT_SCORE_RULES = {
    ("rack_scale_gpu_boards", "technology_generation_shift"): (
        75.0, "机架互联向高密度中板和交换板迁移", "官方架构与两组板级资料共同确认代际变化记75分；仅概念方向记55分。",
    ),
    ("rack_scale_gpu_boards", "material_intensity_proxy"): (
        70.0, "公开拓扑确认每机架多块计算与交换托盘", "官方资料给出计算板或交换托盘数量但缺成品面积记70分；数量与面积均可核验记85分。",
    ),
    ("eight_accelerator_ubb", "technology_generation_shift"): (
        70.0, "8加速器UBB已有当前平台实例", "当前平台官方资料确认8加速器UBB结构，且另有公开标准作背景时记70分；只有概念方向记55分。",
    ),
    ("eight_accelerator_ubb", "material_intensity_proxy"): (
        85.0, "UBB与八块OAM的尺寸和面积可直接计算", "官方尺寸和板数可复算严格面积与扩展面积记85分；只有板数无面积记70分。",
    ),
    ("datacenter_switch_boards", "technology_generation_shift"): (
        75.0, "交换板向24层HDI、M9和1.6T演进", "至少三组板级或官方架构资料确认层数、材料或速率代际变化记75分；本槽有四组。",
    ),
    ("datacenter_switch_boards", "material_intensity_proxy"): (
        70.0, "NVL72公开九个交换托盘但未披露板面积", "官方拓扑给出每机架交换托盘数量但缺成品面积记70分；数量与面积均可核验记85分。",
    ),
}


FACTOR_CONCLUSIONS = {
    "demand.downstream_price_momentum": (
        "深南、广合、金像、TTM等经营披露支持高端板订单较强，但这些是PCB供应商收入、订单或业务结构，不是下游AI服务器和系统成交价；"
        "本轮没有找到同口径下游系统价格序列，因此价格槽保持缺失，最终分收敛到中性。"
    ),
    "demand.customer_capex_capacity_signal": (
        "Amazon、Microsoft、Alphabet和Meta给出的2026年资本开支指引仍处高位，微软扩容和华为、Amazon的已部署系统提供实物侧验证；"
        "资本开支同时覆盖芯片、网络、机房和电力，不能按固定比例直接换算PCB订单。"
    ),
    "demand.output_consumption_proxy": (
        "TrendForce在2026年5月仍预计AI服务器全年增长超过28%，Amazon、华为和中兴的部署披露说明需求已经进入实物系统；"
        "公开数据的服务器、芯片和超节点分母不同，不能相加成统一出货量，因此协议评分收敛到中性，但不代表出货增长为零。"
    ),
    "demand.application_intensity_change": (
        "OCP、NVIDIA及供应商资料共同显示，8加速器基板、机架中板、交换板和更高层HDI正在提高单节点板面积与工艺价值；"
        "专有平台未公开完整可生产BOM，且部分几何资料较早，因此只能给出严格下限和扩展上限，可靠性门禁把最终分压回中性。"
    ),
    "supply.capacity_event_12m": (
        "多家公司已经投产或规划中国、泰国和北美扩产，但公开口径大多混合层数、应用和认证状态；"
        "目前没有可直接相加的18层以上AI板有效产能起点，所以本因子不把规划产能当成当前供给，得分应向中性收敛。"
    ),
    "supply.expansion_cycle_bucket": (
        "生益披露的高多层项目建设期约30个月，多家海外新厂仍处认证或爬坡阶段，说明从投资到可用供给存在明显时滞；"
        "各厂没有统一披露同口径认证周期和良率，不能据此预测精确投产月份。"
    ),
    "supply.raw_policy_constraint": (
        "公开资料能够确认M8/M9、超低损耗材料、多次压合和背钻等工艺升级，但没有同口径的当前材料产能、供应集中度、价格或政策冲击数据；"
        "因此无法根据现有资料判断材料是否已经形成可量化短缺，本因子保持证据不足。"
    ),
    "supply.supplier_structure_bucket": (
        "至少八家公司有18层以上直接制造能力或量产证据，说明技术供给不是单一来源；"
        "但最高层数不等于完成AI认证的有效供给，且没有严格AI口径份额，因此无法判断有效供应集中度，结构指标保持中性。"
    ),
    "supply.substitution_barrier": (
        "多次压合、超低损耗、高层HDI以及客户认证和爬坡记录表明替换供应商需要重新验证工艺、良率与可靠性；"
        "公开资料没有统一的验证时长、良率和替代报价，壁垒强度只能分档，不能换算为份额或溢价。"
    ),
    "signal.material_price_momentum": (
        "沪电32层以上PCB单价由2025年一季度6.09万元/平方米升至2026年一季度6.59万元/平方米，同比约8.21%；"
        "这是研究对象自身价格的一家公司样本，不是下游系统价格，也不能替代M8/M9投入材料价格，覆盖率门禁因此仍把最终分压回中性。"
    ),
}


APPLICATION_CONCLUSIONS_BY_ENTITY = {
    "rack_scale_gpu_boards": (
        "NVL72官方拓扑给出18个计算托盘、9个交换托盘和18—36块主计算板，Rubin又把连接功能迁向高密度中板；"
        "这支持机架级板卡强度上升，但专有板尺寸和18层以上占比未公开，最终分因可靠性门禁向中性收敛。"
    ),
    "eight_accelerator_ubb": (
        "OCP UBB 1.5和AMD UBB 2.0都支持8个OAM，公开尺寸可复算每节点0.243945平方米严格下限与0.378585平方米扩展上限；"
        "OAM并非全部达到18层，因此两组面积不能相加，扩展上限仍需逐型号验证。"
    ),
    "custom_asic_system_boards": (
        "Google、Amazon和华为公开了芯片、主机或机柜拓扑，但没有披露定制ASIC系统中18层以上PCB的成品块数和面积；"
        "因此无法把芯片数量直接换成板面积，本因子保持缺失并收敛到中性。"
    ),
    "datacenter_switch_boards": (
        "NVL72每机架含9个交换托盘，Rubin资料又指向24层HDI、M9和更高速交换板，说明交换侧工艺强度上升；"
        "公开资料没有每托盘成品板面积和完整层数分布，因此只能确认方向，不能计算单位机架面积。"
    ),
}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_question() -> str:
    text = INTAKE_PATH.read_text(encoding="utf-8")
    heading = text.index("## 必填 1：研究问题")
    match = re.search(r"```text\s*\n(.*?)\n```", text[heading:], re.DOTALL)
    if not match:
        raise ValueError("研究请求中没有找到研究问题")
    return match.group(1).strip()


def _ref(prefix: str, fact_id: str) -> str:
    return f"{prefix}-{re.sub(r'[^A-Za-z0-9_.-]+', '-', fact_id).strip('-')}"


def _valid_date(value: Any) -> str | None:
    text = str(value or "").strip()
    return text if re.fullmatch(r"\d{4}(?:-\d{2}(?:-\d{2})?)?", text) else None


def _clean_source_excerpt(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _fact_source(prefix: str, fact: Mapping[str, Any], ledger_path: Path) -> dict[str, Any]:
    ref = _ref(prefix, str(fact["fact_id"]))
    urls = fact.get("url") or fact.get("source_url_or_file")
    direct_url = urls if isinstance(urls, str) else None
    is_web_url = bool(direct_url and direct_url.startswith(("http://", "https://")))
    inferred = str(fact.get("extraction_method") or "").lower() == "inferred" or isinstance(urls, list)
    original_excerpt = _clean_source_excerpt(fact.get("source_excerpt") or fact.get("excerpt"))
    translated_excerpt = str(fact.get("excerpt_zh") or original_excerpt).strip()
    if fact.get("excerpt_is_verbatim") is False:
        original_excerpt = f"[Researcher paraphrase; not a verbatim quotation] {original_excerpt}"
        translated_excerpt = f"研究者归纳（非逐字引文）：{translated_excerpt}"
    language = "zh-CN" if re.search(r"[\u4e00-\u9fff]", original_excerpt) else "en"
    tier_raw = str(fact.get("evidence_tier") or fact.get("source_tier") or "B").upper()
    fact_id = str(fact.get("fact_id"))
    if prefix == "DMD" and fact_id in {"DF005", "PB011"}:
        tier_raw = "C"
    if prefix == "MKT" and fact_id in {"MKT-013", "MKT-014", "CTR-044"}:
        tier_raw = "B"
    tier = tier_raw if tier_raw in {"S", "A", "B", "C"} else "B"
    publish_date = _valid_date(fact.get("publication_date") or fact.get("publish_date"))
    stale = bool(publish_date and publish_date[:4] <= "2024")
    explicit_review_status = str(fact.get("source_review_status") or "").strip()
    valid_review_statuses = {
        "pending", "pass", "pass_with_note", "weak_source_only", "duplicate",
        "paywalled", "stale", "conflict", "reject",
    }
    source: dict[str, Any] = {
        "ref": ref,
        "title": str(fact.get("source_title") or fact.get("title") or fact.get("topic") or fact.get("metric_or_claim") or fact.get("claim") or fact.get("claim_zh")),
        "title_zh": str(fact.get("source_title_zh") or fact.get("metric_or_claim") or fact.get("claim") or fact.get("claim_zh") or fact.get("source_title") or fact.get("topic"))[:180],
        "publisher": str(fact.get("publisher") or "研究资料"),
        "publish_date": publish_date,
        "event_date": publish_date,
        "fetch_date": AS_OF_DATE,
        "source_tier": tier,
        "source_review_status": (
            explicit_review_status
            if explicit_review_status in valid_review_statuses
            else "stale" if stale else (
                "pass_with_note" if inferred or fact.get("excerpt_is_verbatim") is False else "pass"
            )
        ),
        "excerpt": original_excerpt,
        "excerpt_zh": translated_excerpt,
        "language": language,
        "independence_key": str(fact.get("independence_key") or ref),
        "independence_rationale": str(fact.get("independence_rationale") or "按原始发布主体和底层材料归并，转载不重复计数。"),
        "local_locator": str(fact.get("locator") or fact.get("document_locator") or fact.get("metric_or_claim") or fact.get("claim") or fact.get("claim_zh"))[:500],
    }
    if is_web_url:
        source["url"] = direct_url
        if inferred:
            source["local_locator"] = (
                "计算或转译说明："
                f"{fact.get('inference_boundary') or fact.get('boundary') or '见该事实记录'}"
            )
    elif inferred or not direct_url:
        source["local_path"] = ledger_path.relative_to(ROOT).as_posix()
        source["local_locator"] = (
            f"{'联合底层资料的' if isinstance(urls, list) else '研究底稿'}计算说明："
            f"{fact.get('inference_boundary') or fact.get('boundary') or '见该事实记录'}"
        )
    else:
        candidate = Path(direct_url)
        source["local_path"] = candidate.as_posix()
        source["local_locator"] = str(fact.get("document_locator") or fact.get("locator") or direct_url)
    if stale:
        source["staleness_warning"] = "该资料发布于2024年或更早，只用于架构、历史基准或技术机理；当前需求判断必须与2025—2026年资料交叉。"
    if isinstance(urls, list):
        underlying_fact_ids = [str(value) for value in fact.get("underlying_fact_ids") or []]
        if not underlying_fact_ids:
            raise ValueError(f"联合推导 {ref} 必须显式列出 underlying_fact_ids")
        source["underlying_source_refs"] = [_ref(prefix, value) for value in underlying_fact_ids]
        formula_note = str(fact.get("inference_boundary") or fact.get("boundary") or "见该事实记录")
        source.update(
            {
                "title": f"{fact.get('subject') or fact.get('metric_or_claim')}计算底稿",
                "title_zh": f"{fact.get('subject') or fact.get('metric_or_claim')}计算底稿"[:180],
                "publisher": "本研究计算底稿",
                "source_tier": "B",
                "source_review_status": "pass_with_note",
                "excerpt": f"计算方法：{formula_note}",
                "excerpt_zh": f"计算方法：{formula_note}",
                "language": "zh-CN",
                "local_locator": f"计算公式与适用边界：{formula_note}",
                "date_note": (
                    "该记录联合多个底层来源进行计算，并逐项保留原始证据引用；"
                    "它不增加独立证据组，也不能替代底层原文。"
                ),
            }
        )
    elif publish_date is None:
        source["date_note"] = "原始页面未给出可独立核验的标准发布日期；以本轮访问日和文内时期约束时效。"
    if fact.get("excerpt_is_verbatim") is False:
        source["excerpt_is_verbatim"] = False
        source["excerpt_kind"] = "researcher_paraphrase"
        source["date_note"] = (
            f"{source.get('date_note', '')} 本条摘录是研究者对原文的忠实归纳，不是逐字引文；"
            "公开结论按来源层级和原始链接复核，不把该归纳当作新增事实。"
        ).strip()
    if tier == "C":
        source["policy_evidence_role"] = "reference_only"
        source["date_note"] = (
            f"{source.get('date_note', '')} C级受托研究或弱来源只用于背景和口径对照，"
            "不得进入核心因子、客户关系、份额或供需结论。"
        ).strip()
    return source


def _fact_data_point(prefix: str, fact: Mapping[str, Any], source: Mapping[str, Any]) -> dict[str, Any]:
    value = fact.get("value")
    method = str(fact.get("extraction_method") or "web_fetch")
    if method not in {"web_fetch", "pdf_direct", "inferred"}:
        method = "inferred" if "deriv" in str(fact.get("fact_type") or "").lower() else "web_fetch"
    point: dict[str, Any] = {
        "source_ref": source["ref"],
        "data_point_key": f"DP-{prefix}-{fact['fact_id']}",
        "data_point_title": f"{fact.get('subject') or fact.get('company') or fact.get('topic') or '研究对象'}：{fact.get('category') or fact.get('claim_axis') or fact.get('claim_type') or '事实'}",
        "research_category": "calculated_inference" if method == "inferred" else ("industry_or_company_forecast" if "forecast" in str(fact.get("fact_type") or "") else "observed_fact"),
        "original_fact_type": str(fact.get("fact_type") or "fact"),
        "fact_type": str(fact.get("fact_type") or "fact"),
        "metric": str(fact.get("metric_or_claim") or fact.get("claim") or fact.get("claim_zh") or fact.get("metric")),
        "period": str(fact.get("period") or fact.get("period_or_as_of") or fact.get("period_or_as_of_date") or AS_OF_DATE),
        "unit": str(fact.get("unit") or "文本"),
        "scope_key": f"{prefix}|{fact.get('subject') or fact.get('company') or fact.get('topic')}|{fact.get('category') or fact.get('claim_axis') or fact.get('claim_type')}|{fact['fact_id']}",
        "source_excerpt": str(source.get("excerpt") or ""),
        "interpretation": str(fact.get("metric_or_claim") or fact.get("claim") or fact.get("claim_zh") or fact.get("metric")),
        "research_use": str(fact.get("relevance_to_18plus_rigid_pcb") or fact.get("research_use") or "用于约束18层以上刚性高多层PCB的需求、供给或验证边界。"),
        "extraction_method": method,
        "note": "；".join(str(v) for v in (fact.get("inference_boundary"), fact.get("boundary"), fact.get("dedupe_note")) if v),
    }
    if source.get("language") != "zh-CN":
        point["source_excerpt_zh"] = str(source.get("excerpt_zh") or "")
    if source.get("excerpt_is_verbatim") is False:
        point["source_excerpt_kind"] = "researcher_paraphrase"
    if source.get("policy_evidence_role"):
        point["policy_evidence_role"] = source["policy_evidence_role"]
    if source.get("underlying_source_refs"):
        point["underlying_source_refs"] = list(source["underlying_source_refs"])
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        point["value_num"] = float(value)
    elif value is not None:
        point["value_text"] = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
    else:
        point["value_text"] = str(fact.get("metric_or_claim") or fact.get("claim") or fact.get("claim_zh"))
    if fact.get("observations"):
        observations = []
        for observation_index, raw in enumerate(fact.get("observations") or [], start=1):
            period = str(
                raw.get("period")
                or raw.get("year")
                or raw.get("date")
                or f"{fact.get('period') or fact.get('period_or_as_of') or fact.get('period_or_as_of_date') or AS_OF_DATE}:{raw.get('metric') or raw.get('bucket') or observation_index}"
            )
            numeric_candidates = [
                value for key, value in raw.items()
                if key not in {"period", "year", "date"}
                and isinstance(value, (int, float)) and not isinstance(value, bool)
            ]
            if len(numeric_candidates) == 1:
                observations.append({"period": period, "value_num": float(numeric_candidates[0])})
            else:
                observations.append({
                    "period": period,
                    "value_text": "；".join(f"{key}={value}" for key, value in raw.items() if key not in {"period", "year", "date"}),
                })
        point["observations"] = observations
    return point


def _load_agent_materials() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    sources: list[dict[str, Any]] = []
    points: list[dict[str, Any]] = []
    metadata: list[dict[str, Any]] = []
    for prefix, path in LEDGER_SPECS:
        payload = _read_json(path)
        facts = payload.get("facts") or payload.get("data_points") or []
        if int(payload.get("fact_count") or len(facts)) != len(facts):
            raise ValueError(f"{path} 声明计数与事实数不一致")
        for fact in facts:
            source = _fact_source(prefix, fact, path)
            point = _fact_data_point(prefix, fact, source)
            sources.append(source)
            points.append(point)
            metadata.append({"prefix": prefix, "fact": dict(fact), "source": source, "point": point})
    refs = [row["ref"] for row in sources]
    keys = [row["data_point_key"] for row in points]
    if len(refs) != len(set(refs)) or len(keys) != len(set(keys)):
        raise ValueError("并行账本的来源或数据点标识重复")
    return sources, points, metadata


def _ab_wus_materials() -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Import a small, grouped, read-only snapshot from the A/B research DB."""
    specifications = (
        (771, "全球22层以上MLPCB严格可观测市场", "AB-WUS-22PLUS-MARKET", "CIC在沪电港交所申请材料中的22层以上市场序列", "C"),
        (771, "全球MLPCB市场规模-22-30层", "AB-WUS-22-30-MARKET", "CIC在沪电港交所申请材料中的22—30层市场序列", "C"),
        (771, "全球MLPCB市场规模-32层及以上", "AB-WUS-32PLUS-MARKET", "CIC在沪电港交所申请材料中的32层以上市场序列", "C"),
        (771, "2025全球22层以上MLPCB CR5", "AB-WUS-CR5", "2025年全球22层以上市场前五集中度", "C"),
        (771, "2025全球22层以上MLPCB第1名份额-沪电股份", "AB-WUS-SHARE", "沪电股份在2025年全球22层以上市场的公开份额", "C"),
        (772, "沪电股份22-30层PCB ASP", "AB-WUS-ASP-22-30", "沪电股份22—30层PCB单价序列", "S"),
        (772, "沪电股份32+层PCB ASP", "AB-WUS-ASP-32PLUS", "沪电股份32层以上PCB单价序列", "S"),
        (772, "沪电股份22-30层PCB销售面积", "AB-WUS-AREA-22-30", "沪电股份22—30层PCB销售面积序列", "S"),
        (772, "沪电股份32+层PCB销售面积", "AB-WUS-AREA-32PLUS", "沪电股份32层以上PCB销售面积序列", "S"),
        (772, "沪电股份N+N量产层数", "AB-WUS-NN", "沪电股份N+N量产层数", "S"),
        (772, "沪电股份N+M量产层数", "AB-WUS-NM", "沪电股份N+M量产层数", "S"),
        (772, "沪电股份PCB技术能力上限", "AB-WUS-TECH-CAP", "沪电股份PCB技术能力上限", "S"),
    )
    excerpt_zh_by_ref = {
        "AB-WUS-22PLUS-MARKET": "受发行人委聘的CIC/Prismark研究估计，全球22层以上多层板市场由2025年49亿美元增至2030年131亿美元；预测不是实际订单。",
        "AB-WUS-22-30-MARKET": "受发行人委聘的CIC/Prismark研究估计，全球22—30层多层板市场由2025年34亿美元增至2030年82亿美元。",
        "AB-WUS-32PLUS-MARKET": "受发行人委聘的CIC/Prismark研究估计，全球32层以上多层板市场由2025年15亿美元增至2030年49亿美元。",
        "AB-WUS-CR5": "CIC估计2025年全球22层以上多层板市场前五家收入合计占62.3%；除沪电外，原表未公开其余公司名称。",
        "AB-WUS-SHARE": "CIC估计沪电股份2025年在全球22层以上多层板市场的收入份额为14.9%。",
        "AB-WUS-ASP-22-30": "沪电股份22—30层PCB平均售价由2023年1.82万元/平方米升至2025年2.21万元，2026年一季度为2.37万元。",
        "AB-WUS-ASP-32PLUS": "沪电股份32层以上PCB平均售价由2023年4.73万元/平方米升至2025年6.42万元，2026年一季度为6.59万元。",
        "AB-WUS-AREA-22-30": "沪电股份22—30层PCB销售面积由2023年14.71万平方米增至2025年27.89万平方米，2026年一季度为7.16万平方米。",
        "AB-WUS-AREA-32PLUS": "沪电股份32层以上PCB销售面积由2023年1.61万平方米增至2025年6.62万平方米，2026年一季度为3.02万平方米。",
        "AB-WUS-NN": "沪电股份披露N+N结构已量产至44层；量产上限不等于该层数的出货面积。",
        "AB-WUS-NM": "沪电股份披露N+M结构已量产至54层；量产上限不等于该层数的出货面积。",
        "AB-WUS-TECH-CAP": "沪电股份披露PCB技术能力达到100层以上；技术上限不能替代批量面积、良率或收入。",
    }
    db_path = ROOT / "data" / "research.db"
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    sources: list[dict[str, Any]] = []
    points: list[dict[str, Any]] = []
    metadata: list[dict[str, Any]] = []
    try:
        for source_id, metric, ref, title_zh, tier in specifications:
            source_row = connection.execute("SELECT * FROM source WHERE id=?", (source_id,)).fetchone()
            rows = connection.execute(
                "SELECT * FROM industry_data_point WHERE source_id=? AND metric=? ORDER BY id",
                (source_id, metric),
            ).fetchall()
            if not rows:
                raise ValueError(f"A/B只读快照缺少指标：source={source_id}, metric={metric}")
            excerpt = _clean_source_excerpt(rows[0]["source_excerpt"])
            source = {
                "ref": ref,
                "title": str(source_row["title"]),
                "title_zh": title_zh,
                "publisher": str(source_row["publisher"]),
                "publish_date": str(source_row["publish_date"]),
                "event_date": str(source_row["publish_date"]),
                "fetch_date": AS_OF_DATE,
                "source_tier": tier,
                "source_review_status": "pass_with_note" if source_id == 771 else "pass",
                "excerpt": excerpt,
                "excerpt_zh": excerpt_zh_by_ref[ref],
                "language": "en",
                "independence_key": f"ab_source:{source_id}",
                "independence_rationale": "同一港交所申请材料章节中的所有序列按一个底层证据组计；不同事实别名只为打开精确摘录，不增加独立性。",
                "url": str(source_row["source_url"] or source_row["url"]),
                "local_locator": f"A/B只读快照 source_id={source_id}；metric={metric}；原文件定位见来源记录",
                "date_note": "市场序列来自发行人委聘行业顾问，只作为有利益关系的行业估计；公司经营序列来自发行申报材料。",
            }
            if tier == "C":
                source["policy_evidence_role"] = "reference_only"
            sources.append(source)
            observations = []
            for row in rows:
                observation: dict[str, Any] = {"period": str(row["period"])}
                if row["value_num"] is not None:
                    observation["value_num"] = float(row["value_num"])
                else:
                    observation["value_text"] = str(row["value_text"] or "")
                observations.append(observation)
            point: dict[str, Any] = {
                "source_ref": ref,
                "data_point_key": f"DP-{ref}",
                "data_point_title": title_zh,
                "research_category": "industry_or_company_forecast" if any(str(row["is_forecast"]) == "1" for row in rows) else "observed_time_series",
                "original_fact_type": "ab_readonly_grouped_snapshot",
                "fact_type": "observed_series" if len(rows) > 1 else "observed_fact",
                "metric": metric,
                "period": f"{rows[0]['period']}—{rows[-1]['period']}" if len(rows) > 1 else str(rows[0]["period"]),
                "unit": str(rows[0]["unit"]),
                "scope_key": f"ab|{source_id}|{metric}",
                "source_excerpt": excerpt,
                "source_excerpt_zh": excerpt_zh_by_ref[ref],
                "interpretation": title_zh,
                "research_use": "用于校准22层以上总市场、32层以上结构和沪电批量经营验证；委聘预测与公司实际序列分开使用。",
                "extraction_method": "inferred" if any(str(row["extraction_method"]) == "inferred" for row in rows) else "pdf_direct",
                "note": "从A/B研究库只读导入；同一指标的逐期观测合并为一个C轨数据点。匿名竞争者不作具名映射。",
            }
            if len(observations) > 1:
                point["observations"] = observations
            elif observations[0].get("value_num") is not None:
                point["value_num"] = observations[0]["value_num"]
            else:
                point["value_text"] = observations[0]["value_text"]
            if source.get("policy_evidence_role"):
                point["policy_evidence_role"] = source["policy_evidence_role"]
            points.append(point)
            metadata.append(
                {
                    "prefix": "AB",
                    "fact": {
                        "fact_id": ref,
                        "metric_or_claim": excerpt_zh_by_ref[ref],
                        "category": "公司经营序列" if tier == "S" else "受托市场研究",
                    },
                    "source": source,
                    "point": point,
                }
            )
    finally:
        connection.close()
    return sources, points, metadata


def _model_sources_and_points(outputs: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    input_hash = sha256_file(MODEL_INPUT_PATH)
    output_hash = sha256_file(MODEL_OUTPUT_PATH)
    sources = [
        {
            "ref": "MODEL-PCB-INPUTS",
            "title": "18层以上高多层PCB供需模型输入",
            "title_zh": "18层以上高多层PCB供需模型输入",
            "publisher": "Opportunity Lens研究底稿",
            "publish_date": AS_OF_DATE,
            "event_date": AS_OF_DATE,
            "fetch_date": AS_OF_DATE,
            "source_tier": "B",
            "source_review_status": "pass_with_note",
            "excerpt": "研究底稿逐项列出服务器数量、架构占比、有效板面积、单价与条件供给增速，并区分外部事实、由事实计算和研究敏感性假设。",
            "excerpt_zh": "研究底稿逐项列出服务器数量、架构占比、有效板面积、单价与条件供给增速，并区分外部事实、由事实计算和研究敏感性假设。",
            "language": "zh-CN",
            "independence_key": "research_model:high_multilayer_pcb:inputs:v1",
            "independence_rationale": "这是研究假设底稿，不作为外部独立证据；模型输出也不能反向抬高证据组数量。",
            "local_path": MODEL_INPUT_PATH.relative_to(ROOT).as_posix(),
            "local_locator": f"研究底稿；内容哈希{input_hash}",
        },
        {
            "ref": "MODEL-PCB-OUTPUTS",
            "title": "18层以上高多层PCB供需模型结果",
            "title_zh": "18层以上高多层PCB供需模型结果",
            "publisher": "Opportunity Lens研究底稿",
            "publish_date": AS_OF_DATE,
            "event_date": AS_OF_DATE,
            "fetch_date": AS_OF_DATE,
            "source_tier": "B",
            "source_review_status": "pass_with_note",
            "excerpt": "节点数×有效面积×单价得到AI需求；供给只给假设2026年平衡后的面积增长门槛，不使用22层以上市场作为供给分母。",
            "excerpt_zh": "节点数×有效面积×单价得到AI需求；供给只给假设2026年平衡后的面积增长门槛，不使用22层以上市场作为供给分母。",
            "language": "zh-CN",
            "independence_key": "research_model:high_multilayer_pcb:outputs:v1",
            "independence_rationale": "这是由冻结输入计算的结果，不是新增外部事实或独立来源。",
            "local_path": MODEL_OUTPUT_PATH.relative_to(ROOT).as_posix(),
            "local_locator": f"研究结果底稿；内容哈希{output_hash}",
        },
    ]
    points: list[dict[str, Any]] = []
    for scenario_key, scenario in outputs["scenarios"].items():
        for metric, unit, title in (
            ("ai_server_units_million", "百万台", "AI服务器节点情景"),
            ("strict_demand_area_million_m2", "百万平方米", "严格口径高多层板面积需求"),
            ("bottom_up_demand_usd_bn", "十亿美元", "AI高多层板产值需求"),
        ):
            observations = [{"period": str(row["year"]), "value_num": row[metric]} for row in scenario["rows"]]
            points.append(
                {
                    "source_ref": "MODEL-PCB-OUTPUTS",
                    "data_point_key": f"DP-MODEL-{scenario_key}-{metric}",
                    "data_point_title": f"{scenario['label']}：{title}",
                    "research_category": "calculated_inference",
                    "original_fact_type": "model_series",
                    "fact_type": "calculated_series",
                    "metric": title,
                    "period": "2026—2030",
                    "unit": unit,
                    "scope_key": f"model|{scenario_key}|{metric}",
                    "source_excerpt": sources[1]["excerpt"],
                    "interpretation": f"该序列是{scenario['label']}下的{title}，所有输入均在模型底稿中冻结。",
                    "research_use": "用于比较情景和检验供需关系；研究假设不能写成公司指引或行业实际值。",
                    "extraction_method": "inferred",
                    "note": outputs["method_note"],
                    "observations": observations,
                }
            )
    for path_key, path in outputs["conditional_supply_paths"].items():
        for metric, unit, title in (
            ("conditional_supply_area_million_m2", "百万平方米", "条件有效供给面积"),
            ("conditional_supply_minus_demand_area_million_m2", "百万平方米", "条件有效供给面积减基准需求"),
        ):
            observations = [
                {"period": str(row["year"]), "value_num": row[metric]}
                for row in path["rows"]
            ]
            points.append(
                {
                    "source_ref": "MODEL-PCB-OUTPUTS",
                    "data_point_key": f"DP-MODEL-supply-{path_key}-{metric}",
                    "data_point_title": f"{path['label']}：{title}",
                    "research_category": "calculated_inference",
                    "original_fact_type": "conditional_model_series",
                    "fact_type": "calculated_series",
                    "metric": title,
                    "period": "2026—2030",
                    "unit": unit,
                    "scope_key": f"model|conditional_supply|{path_key}|{metric}",
                    "source_excerpt": sources[1]["excerpt"],
                    "source_excerpt_zh": sources[1]["excerpt_zh"],
                    "interpretation": f"{path['anchor_rule']}；该序列只说明若供给面积按{path['annual_growth']:.0%}增长时，基准需求会怎样穿透。",
                    "research_use": "用于计算有效供给需要达到的增长门槛；不能解释为行业实际产能、公司份额或价格预测。",
                    "extraction_method": "inferred",
                    "note": outputs["method_note"],
                    "observations": observations,
                }
            )
    architecture_observations = [
        {"period": year, "value_num": row["weighted_strict_area_m2_per_server"]}
        for year, row in outputs["yearly_architecture"].items()
    ]
    points.append(
        {
            "source_ref": "MODEL-PCB-OUTPUTS",
            "data_point_key": "DP-MODEL-weighted-strict-area",
            "data_point_title": "架构加权的18层以上刚性板有效面积",
            "research_category": "calculated_inference",
            "original_fact_type": "model_series",
            "fact_type": "calculated_series",
            "metric": "每台AI服务器节点的18层以上刚性板有效面积",
            "period": "2026—2030",
            "unit": "平方米/台",
            "scope_key": "model|architecture|weighted_area",
            "source_excerpt": sources[1]["excerpt"],
            "interpretation": "按各架构占比和板面积研究区间加权，不能套用于某个专有平台。",
            "research_use": "连接服务器节点与PCB面积需求。",
            "extraction_method": "inferred",
            "note": "板面积为工程假设，不是公开专有BOM。",
            "observations": architecture_observations,
        }
    )
    return sources, points


def _financial_sources_and_targets() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    financial = _read_json(FINANCIAL_PATH)
    market = _read_json(MARKET_PATH)
    sources: list[dict[str, Any]] = []
    targets: list[dict[str, Any]] = []
    for order, (company_key, specification) in enumerate(TARGET_SPECS.items(), start=1):
        company = financial["companies"][company_key]
        snapshot = market["companies"][company_key]
        fin_ref = f"FIN-{company_key.upper()}-SERIES"
        mkt_ref = f"MKT-{company_key.upper()}-20260711"
        periods = company.get("periods") or []
        latest = periods[-1]
        finance_excerpt = (
            f"{company['name']}结构化财务覆盖{periods[0]['period']}至{latest['period']}；"
            f"最新收入{latest['revenue']['cny_yi']:.2f}亿元人民币、毛利率{latest.get('gross_margin'):.2f}%、"
            f"经营现金流{latest['operating_cash_flow']['cny_yi']:.2f}亿元人民币、资本开支{latest['capex']['cny_yi']:.2f}亿元人民币。"
            f"非人民币报表统一按{company.get('fx_as_of', financial['as_of'])}汇率折算人民币，便于横向比较，但不是各财年的平均汇率。"
        )
        latest_net_income = float(latest["net_income"]["cny_yi"])
        pe_text = (
            f"{snapshot['pe_ttm']}倍"
            if snapshot.get("pe_ttm") is not None
            else ("未取得" if latest_net_income > 0 else "因亏损不适用")
        )
        pb_text = f"{snapshot['pb']}倍" if snapshot.get("pb") is not None else "未取得"
        ps_text = f"{snapshot['ps_ttm']}倍" if snapshot.get("ps_ttm") is not None else "未取得"
        market_excerpt = (
            f"截至{market['as_of']}可取得的最近交易日，{company['name']}收盘价{snapshot.get('price')} {snapshot.get('currency')}；"
            f"市值{snapshot.get('market_cap_cny'):.2f}亿元人民币（约{snapshot.get('market_cap_usd'):.2f}亿美元），"
            f"PE {pe_text}、PB {pb_text}、PS {ps_text}。"
        )
        sources.extend(
            [
                {
                    "ref": fin_ref,
                    "title": f"{company['name']}历史财务结构化快照",
                    "title_zh": f"{company['name']}历史财务结构化快照",
                    "publisher": "Tushare或yfinance；缓存于本项目",
                    "publish_date": financial["as_of"],
                    "event_date": financial["as_of"],
                    "fetch_date": financial["as_of"],
                    "source_tier": "B",
                    "source_review_status": "pass_with_note",
                    "excerpt": finance_excerpt,
                    "excerpt_zh": finance_excerpt,
                    "language": "zh-CN",
                    "independence_key": f"structured_financial:{company['ticker']}:{financial['as_of']}",
                    "independence_rationale": "同一证券、同一批次结构化财务按一个数据来源组计，不把逐期记录拆成多组。",
                    "local_path": FINANCIAL_PATH.relative_to(ROOT).as_posix(),
                    "local_locator": f"companies.{company_key}",
                },
                {
                    "ref": mkt_ref,
                    "title": f"{company['name']}行情与估值快照",
                    "title_zh": f"{company['name']}行情与估值快照",
                    "publisher": "Tushare或Yahoo Finance / yfinance；缓存于本项目",
                    "publish_date": market["as_of"],
                    "event_date": market["as_of"],
                    "fetch_date": market["as_of"],
                    "source_tier": "B",
                    "source_review_status": "pass_with_note",
                    "excerpt": market_excerpt,
                    "excerpt_zh": market_excerpt,
                    "language": "zh-CN",
                    "independence_key": f"market_snapshot:{company['ticker']}:{market['as_of']}",
                    "independence_rationale": "同一证券截至同一研究时点可取得的最近交易日行情、估值和汇率换算按一个数据来源组计。",
                    "local_path": MARKET_PATH.relative_to(ROOT).as_posix(),
                    "local_locator": f"companies.{company_key}",
                },
            ]
        )
        target_points = []
        for row in periods:
            value_text = (
                f"收入{row['revenue']['cny_yi']:.2f}亿元人民币（约{row['revenue']['usd_yi']:.2f}亿美元）；"
                f"净利润{row['net_income']['cny_yi']:.2f}亿元人民币；毛利率{row.get('gross_margin'):.2f}%；"
                f"经营现金流{row['operating_cash_flow']['cny_yi']:.2f}亿元人民币；"
                f"资本开支{row['capex']['cny_yi']:.2f}亿元人民币"
            )
            target_points.append(
                {
                    "metric_name": f"{company['name']}核心财务",
                    "metric_category": "financial_history",
                    "period": row["period"],
                    "as_of_date": row["end_date"],
                    "value_text": value_text,
                    "unit": "亿元人民币，比例除外",
                    "source_title": f"{company['name']}历史财务结构化快照",
                    "source_title_zh": f"{company['name']}历史财务结构化快照",
                    "source_publisher": "Tushare或yfinance；缓存于本项目",
                    "source_url": specification["url"],
                    "source_excerpt": finance_excerpt,
                    "source_excerpt_zh": finance_excerpt,
                    "source_language": "zh-CN",
                    "evidence_ref_uri": source_uri(fin_ref),
                    "data_quality_label": f"结构化财务快照；非人民币报表按{company.get('fx_as_of', financial['as_of'])}汇率统一折算，仍需以发行人报表复核",
                    "direction": "mixed",
                    "credibility_weight": 0.86,
                    "numeric_weight": 1.0,
                }
            )
        target_points.append(
            {
                "metric_name": f"{company['name']}同一研究时点估值",
                "metric_category": "valuation",
                "period": market["as_of"],
                "as_of_date": market["as_of"],
                "value_text": market_excerpt,
                "unit": "原币、亿元人民币、亿美元、倍",
                "source_title": f"{company['name']}行情与估值快照",
                "source_title_zh": f"{company['name']}行情与估值快照",
                "source_publisher": "Tushare或Yahoo Finance / yfinance；缓存于本项目",
                "source_url": specification["url"],
                "source_excerpt": market_excerpt,
                "source_excerpt_zh": market_excerpt,
                "source_language": "zh-CN",
                "evidence_ref_uri": source_uri(mkt_ref),
                "data_quality_label": "截至同一研究时点可取得的最近交易日第三方行情快照",
                "direction": "mixed",
                "credibility_weight": 0.82,
                "numeric_weight": 1.0,
            }
        )
        targets.append(
            {
                "entity_key": specification["entity"],
                "target_name": company["name"],
                "ticker": company["ticker"],
                "market": specification["market"],
                "target_type": "security",
                "target_url": specification["url"],
                "exposure_rationale": specification["view"],
                "evidence_ref_uri": source_uri(specification["evidence_ref"]),
                "research_action": f"按季度跟踪{company['name']}的18层以上产品收入、面积、单价、良率、客户认证、产能利用率、资本开支和经营现金流。",
                "investment_view": specification["view"],
                "risk_note": f"{company['name']}的总PCB收入和总产能不能替代AI高多层板敞口；若扩产先于认证和良率，折旧与现金支出可能早于盈利。重点风险与本公司产品结构和在建项目对应。",
                "target_priority": "P1" if order <= 6 else "P2",
                "target_quality_label": "直接业务相关，客户份额和有效供给仍需验证",
                "relative_preference": f"对{company['name']}优先比较可核验的32层以上量产面积、单价、利用率和现金回报，并结合“{specification['view']}”这一公司特有证据，不按技术最高层数或泛AI表述排序。",
                "confirmed_scenario_action": f"只有{company['name']}的18层以上AI产品批量面积、单价和良率连续改善，且客户认证后出货穿透到经营现金流，才提高该公司的研究优先级。",
                "falsified_scenario_action": f"若{company['name']}的高端板扩产完成但利用率、良率或客户认证没有改善，或收入增长主要来自非本研究口径产品，则下调该公司的研究优先级。",
                "target_profile_markdown": f"{company['name']}与{ENTITY_SPECS[specification['entity']]['name']}存在产品或业务关系。{specification['view']} 本研究不把泛数据中心收入、总产能或最高技术层数直接写成AI高多层板供给。",
                "target_deep_research_markdown": f"对{company['name']}的判断分三步：先确认18层以上刚性板的量产口径，再确认客户认证后批量面积和单价，最后检查毛利与经营现金流是否覆盖扩产支出。当前缓存财务覆盖至少三期，并补充截至2026年7月11日可取得的最近交易日估值；非人民币历史财务统一按2026年7月11日汇率折算人民币，便于比较但不代表各期平均汇率。这些数据只能验证经营结果，不能单独证明具名客户或平台份额。",
                "entity_relation_markdown": f"{company['name']}用于检验{ENTITY_SPECS[specification['entity']]['name']}的需求能否转成供应商批量出货与盈利。",
                "parent_research_relation_markdown": "该标的是从架构需求、有效供给到上市公司盈利兑现的观察点。",
                "conditional_investment_recommendation": "在分产品有效供给、认证后出货、良率和现金回报没有同时改善前，只作为跟踪对象，不给出交易指令或目标价。",
                "financial_data_status": f"已取得{periods[0]['period']}至{latest['period']}结构化财务，并保留截至{market['as_of']}可取得的最近交易日PE/PB/PS和市值；非人民币历史财务按{company.get('fx_as_of', financial['as_of'])}汇率统一折算。数据来自已有缓存，未在本任务中调用外部财务接口。",
                "link_status": "linked",
                "support_status": "partially_supported",
                "sort_order": order,
                "target_data_points": target_points,
            }
        )
    return sources, targets


def _text_blob(metadata: Mapping[str, Any]) -> str:
    fact = metadata["fact"]
    return " ".join(
        str(fact.get(key) or "")
        for key in (
            "fact_id", "category", "claim_axis", "subject", "company", "metric_or_claim",
            "claim", "claim_zh", "claim_type", "topic", "publisher", "source_title", "inference_boundary", "boundary",
        )
    ).lower()


def _fact_statement(fact: Mapping[str, Any]) -> str:
    for key in ("metric_or_claim", "claim", "claim_zh", "topic", "source_title"):
        value = str(fact.get(key) or "").strip()
        if value and value.lower() != "none":
            return value
    raise ValueError(f"事实缺少可读陈述：{fact.get('fact_id')}")


def _find_ref(metadata: Sequence[Mapping[str, Any]], *terms: str, prefix: str | None = None) -> str:
    normalized = tuple(term.lower() for term in terms)
    for row in metadata:
        if prefix and row["prefix"] != prefix:
            continue
        blob = _text_blob(row)
        if all(term in blob for term in normalized):
            return str(row["source"]["ref"])
    raise ValueError(f"没有找到证据：prefix={prefix}, terms={terms}")


def _select_factor_materials(
    metadata: Sequence[Mapping[str, Any]],
    code: str,
    *,
    minimum_groups: int = 5,
) -> list[Mapping[str, Any]]:
    rows_by_ref = {str(row["source"]["ref"]): row for row in metadata}
    preferred_refs = FACTOR_PREFERRED_REFS.get(code)
    if not preferred_refs:
        raise ValueError(f"{code} 没有配置逐项相关证据")
    chosen: list[Mapping[str, Any]] = []
    groups: set[str] = set()
    for ref in preferred_refs:
        row = rows_by_ref.get(ref)
        if row is None:
            raise ValueError(f"{code} 配置的证据不存在：{ref}")
        source = row["source"]
        if (
            source["source_tier"] == "C"
            or source["source_review_status"] == "reject"
            or source.get("excerpt_is_verbatim") is False
        ):
            continue
        group = str(source["independence_key"])
        chosen.append(row)
        groups.add(group)
    if len(groups) < minimum_groups:
        raise ValueError(f"{code} 独立证据组不足：{len(groups)}")
    return chosen


def _factor_input(
    *,
    entity_key: str,
    entity: Mapping[str, Any],
    code: str,
    materials: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    label = FACTOR_LABELS[code]
    refs = [str(row["source"]["ref"]) for row in materials]
    points = [dict(row["point"]) for row in materials]
    rows_by_ref = {str(row["source"]["ref"]): row for row in materials}
    evidence_examples = "；".join(
        _fact_statement(row["fact"]).rstrip("。")[:95] for row in materials[:3]
    )
    conclusion = (
        APPLICATION_CONCLUSIONS_BY_ENTITY[entity_key]
        if code == "demand.application_intensity_change"
        else FACTOR_CONCLUSIONS[code]
    )
    slot_inputs: dict[str, dict[str, Any]] = {}
    context_slot_codes = {"price_source_quality", "planned_or_rumored_capacity"}
    slot_ref_config = (
        APPLICATION_SLOT_REFS_BY_ENTITY[entity_key]
        if code == "demand.application_intensity_change"
        else FACTOR_SLOT_REFS[code]
    )
    for slot_code, slot_refs in slot_ref_config.items():
        selected_rows = [rows_by_ref[ref] for ref in slot_refs if ref in rows_by_ref]
        if len(selected_rows) != len(slot_refs):
            missing_refs = [ref for ref in slot_refs if ref not in rows_by_ref]
            raise ValueError(f"{code}.{slot_code} 的逐槽证据未纳入因子：{missing_refs}")
        selected_points = [row["point"] for row in selected_rows]
        selected_sources = [row["source"] for row in selected_rows]
        raw_units = {
            str(point.get("unit") or "").strip()
            for point in selected_points
            if str(point.get("unit") or "").strip()
        }
        raw_text = "；".join(
            _fact_statement(row["fact"]).rstrip("。") for row in selected_rows
        )
        is_context = slot_code in context_slot_codes
        score_entry = None
        if not is_context:
            score_entry = (
                APPLICATION_SLOT_SCORE_RULES[(entity_key, slot_code)]
                if code == "demand.application_intensity_change"
                else SLOT_SCORE_RULES[(code, slot_code)]
            )
        slot_score = float(score_entry[0]) if score_entry else None
        bucket = str(score_entry[1]) if score_entry else ""
        scoring_rule = str(score_entry[2]) if score_entry else ""
        explicit: dict[str, Any] = {
            "data_point_keys": [str(point["data_point_key"]) for point in selected_points],
            "raw_unit": next(iter(raw_units)) if len(raw_units) == 1 else "多口径公开披露",
            "raw_value_text": raw_text,
            "standardized_value_text": "只作背景，不进入得分" if is_context else bucket,
            "standardized_unit": "文本判断" if is_context else "研究分档",
            "normalization_method": "只合并能够直接回答该指标槽的事实；不同分母和单位不相加，缺失值不由相邻指标继承",
            "value_status": (
                "stale_but_usable"
                if any(source["source_review_status"] == "stale" for source in selected_sources)
                else "available"
            ),
            "preprocess_trace": "逐条保留原始口径并按底层文件去重；没有把销售面积写成价格、把投资额写成有效产能，也没有把工艺能力写成材料涨价。",
            "scoring_trace": (
                "该槽只说明已宣布扩产或价格来源范围，不进入因子得分。"
                if is_context
                else f"直接证据按冻结规则归为“{bucket}”，对应{slot_score:.0f}分；未被直接回答的协议槽保持缺失并使最终分数向中性收敛。"
            ),
            "period": "；".join(dict.fromkeys(str(point.get("period") or AS_OF_DATE) for point in selected_points)),
            "as_of_date": AS_OF_DATE,
        }
        if not is_context:
            explicit.update(
                {
                    "bucket": bucket,
                    "scoring_rule": scoring_rule,
                    "slot_score": slot_score,
                }
            )
        if code == "demand.application_intensity_change":
            explicit["extraction_quality_weight"] = 0.90
            explicit["preprocessing_quality_weight"] = (
                0.98 if slot_refs == ("DMD-PB012",) else 0.95
            )
            explicit["preprocess_trace"] = (
                "只使用对应实体的官方板数、尺寸、层数或拓扑；精确几何按冻结公式复算，"
                "没有把UBB面积继承给机架、ASIC或交换板，也没有把芯片数直接改写成PCB面积。"
            )
        if code == "signal.material_price_momentum" and slot_code == "material_price_yoy_change":
            explicit.update(
                {
                    "standardized_value_num": round((65_900 - 60_900) / 60_900 * 100, 4),
                    "standardized_value_text": "",
                    "standardized_unit": "%（2026Q1同比）",
                    "normalization_method": "按沪电32层以上PCB同口径季度单价计算：(65,900-60,900)÷60,900×100%=8.21%；面积和其他公司收入不进入价格算式",
                }
            )
        slot_inputs[slot_code] = explicit
    topic = (
        f"问题是{entity['name']}的{label}能否被当前公开数据直接验证。证据包括：{evidence_examples}。"
        f"分析与结论：{conclusion} 对本板型的适用边界是：{entity['description']}"
        "事实、行业预测和研究推导分别保留；没有同名口径的数据不填值，也不借其他指标抬高得分。"
    )
    independent_group_count = len(
        {str(row["source"]["independence_key"]) for row in materials}
    )
    return {
        "metric_name": f"{entity['name']}：{label}",
        "period": "2026—2030",
        "as_of_date": AS_OF_DATE,
        "unit": "分",
        "expert_bucket_score": 50.0,
        "source_refs": refs,
        "candidate_data_points": points,
        "metric_slot_inputs": slot_inputs,
        "factor_value_summary": f"{entity['name']}：{conclusion}",
        "source_context_summary": f"共引用{len(refs)}条事实，归入{independent_group_count}个独立证据组；来源为公司/监管披露、官方架构资料或行业数据，同一底层材料不重复增加独立性。",
        "factor_topic_analysis": topic,
        "score_rationale": f"评分只使用能够直接回答“{label}”协议指标的数据；没有直接价格、有效产能、材料供应或认证周期数据的槽保持缺失，并通过覆盖率门禁把结果压回中性。同一事实在不同实体使用同一分档；只有实体拥有不同的BOM或板数证据时才采用实体专属规则。分数不是外部机构结论，也不代表收益率、订单份额或供需缺口。",
        "theme_analysis_points": [
            f"直接事实：{_fact_statement(materials[0]['fact'])[:180]}",
            f"交叉证据：{_fact_statement(materials[1]['fact'])[:180]}",
            f"结论与边界：{conclusion}",
        ],
        "evidence_interpretations": {
            str(row["source"]["ref"]): (
                f"该资料用于判断{entity['name']}的{label}；只采用“{_fact_statement(row['fact'])[:180]}”这一披露范围，"
                "不外推未披露客户、板数、层数、面积、产能或份额。"
            )
            for row in materials
        },
        "score_input_kind": "researcher_bucket_classification_not_external_fact",
    }


def _entities(metadata: Sequence[Mapping[str, Any]], sources_by_ref: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    material_by_factor = {
        code: _select_factor_materials(metadata, code) for code in SEGMENT_FACTOR_CODES
    }
    entities = []
    for key, specification in ENTITY_SPECS.items():
        factor_inputs = {}
        for code in SEGMENT_FACTOR_CODES:
            factor_inputs[code] = _factor_input(
                entity_key=key,
                entity=specification,
                code=code,
                materials=material_by_factor[code],
            )
        entities.append(
            build_segment_entity(
                {
                    "key": key,
                    "canonical_name": specification["name"],
                    "display_name": specification["name"],
                    "description": specification["description"],
                    "factor_inputs": factor_inputs,
                    "band_reason": "区间反映公开BOM、客户认证、有效供给和价格证据的不完整性；不代表收益率预测。",
                    "research_bias_label": "unrated_insufficient_evidence",
                },
                sources_by_ref=sources_by_ref,
                as_of_date=AS_OF_DATE,
            )
        )
    return entities


def _cite(*refs: str) -> str:
    return " ".join(f"^src:source_ref:{ref}" for ref in dict.fromkeys(ref for ref in refs if ref))


def _entity_sections(metadata: Sequence[Mapping[str, Any]], outputs: Mapping[str, Any]) -> list[dict[str, Any]]:
    base = outputs["scenarios"]["base"]["rows"]
    slow_supply_2030 = outputs["conditional_supply_paths"]["slow"]["rows"][-1]
    demand_ref = "DMD-DF014"
    asic_mix_ref = "DMD-DF013"
    capex_ref = "DMD-DF007"
    ubb_ref = "DMD-AR002"
    nvl_ref = "DMD-AR008"
    switch_ref = "DMD-AR009"
    asic_ref = "DMD-AR012"
    lead_ref = "DMD-DR004"
    wus_ref = "AB-WUS-AREA-32PLUS"
    supplier_ref = "SUP-SUP-VG-004"
    material_ref = "DMD-PB008"
    material_next_ref = "DMD-PB009"
    supplement_tail = {
        "rack_scale_gpu_boards": (
            "\n\n### 如果想进一步研究，需要补充的信息\n\n"
            "需要取得GB300、Rubin等机架平台每个计算托盘、交换托盘、中板和背板的成品块数、尺寸、层数、材料与备品率，"
            "并以供应商32层以上季度面积、良率、单价和认证日期核验。缺少这些信息时，可以判断机架化提高单位价值，不能把GPU颗数直接写成厂商订单。"
        ),
        "eight_accelerator_ubb": (
            "\n\n### 如果想进一步研究，需要补充的信息\n\n"
            "需要逐平台确认UBB、OAM和配套交换板是否分别达到18层，补齐拼板利用率、量产良率、二供认证与同层数成交价。"
            "只有这些数据齐备，才能在0.244平方米严格下限与0.379平方米广义上限之间确定更窄的单位节点面积。"
        ),
        "custom_asic_system_boards": (
            "\n\n### 如果想进一步研究，需要补充的信息\n\n"
            "需要把TPU、Trainium、昇腾和国产GPU的芯片、主机、机柜与集群逐层换算，再取得板卡层数、成品面积、认证后出货和客户侧二供证据。"
            "在具名客户关系没有公司与客户两端交叉支持前，只能比较平台部署方向和供应商能力，不能给出精确份额。"
        ),
        "datacenter_switch_boards": (
            "\n\n### 如果想进一步研究，需要补充的信息\n\n"
            "需要取得800G、1.6T、NVLink与下一代无缆架构中交换板、中板和背板的块数、层数、面积、材料与背钻次数，"
            "同时跟踪HVLP铜箔、低热膨胀玻纤的可售产能和长协价格。这样才能判断瓶颈来自板厂良率、材料还是客户认证。"
        ),
    }
    sections = {
        "rack_scale_gpu_boards": f"""### 问题

机架级GPU系统是否会成为2026—2030年高多层板需求最强的增量来源，取决于连接功能是否从线缆和独立模块迁移到计算板、交换板、中板和背板，而不是简单取决于GPU颗数。NVL72官方资料确认一套系统有18个计算托盘、9个NVLink交换托盘和72颗GPU；它没有公开每个交换托盘的PCB块数、层数和面积，因此本研究不会把72颗GPU直接乘成72台服务器，也不会假装知道专有BOM。{_cite(nvl_ref, switch_ref)}

### 证据与数据

需求方向较强。TrendForce在2026年5月仍预计当年AI服务器出货增长超过28%，4月更新给出的ASIC服务器占比约27%；两项都是滚动行业预测而非实际交付。{_cite(demand_ref, asic_mix_ref)} 同时，云厂资本开支与机架部署表明算力建设仍在扩张；这些金额包含建筑、电力、网络和其他设备，只能做需求方向代理，不能直接换算PCB。{_cite(capex_ref)} 供应侧最新披露显示32层以上产品的面积和单价增长显著快于22—30层，这比“最高可做多少层”更接近批量需求验证。{_cite(wus_ref)}

### 建模与分析

模型把机架级GPU作为一种服务器节点架构，与PCIe、8加速器UBB和ASIC节点互斥计数。基准路径中该架构占比由2026年的14%逐步升至2030年的25%；每节点严格口径有效面积由0.46平方米升至0.62平方米。两个数都是研究假设，分别反映机架化渗透和板内互联增加，不是NVIDIA公开BOM。需求以节点数乘面积再乘单价计算，绝不再把机柜数或GPU颗数加回节点总量。

### 分析与结论

机架级GPU高多层板是四个实体中单位用量上升最快、客户切换壁垒最高的一类，机会集中在32层以上、M8/M9低损耗材料、超大尺寸、高纵横比通孔、背钻与复杂中板。下一代平台的M8/M9和更高层数目前仍主要来自行业预测，需要后续量产资料验证。{_cite(material_ref, material_next_ref)} 公开资料只能支持“高端有效供给偏紧”，不能支持“所有18层以上PCB普遍短缺”。若专有架构继续增加板内互联、客户认证速度慢于需求，单价和毛利有上行弹性；若下一代架构通过更高集成度减少板数，或者供应商快速复制良率，单位需求会低于模型。{_cite(lead_ref, supplier_ref)}""" + supplement_tail["rack_scale_gpu_boards"],
        "eight_accelerator_ubb": f"""### 问题

8加速器UBB/HGX/OAM节点是目前最容易建立公开几何边界的架构，但仍不能把公开尺寸直接当作18层以上成品需求。OCP UBB 1.5给出417毫米×585毫米的基板，毛面积0.243945平方米，并支持8个OAM；OAM尺寸另有公开标准。{_cite(ubb_ref)} 层数证据来自具体供应商产品范围，只有二者相交时才能进入严格口径。

### 证据与数据

OCP标准回答板型和尺寸，不回答某代GPU平台采用哪家供应商、多少层、良率或采购价。广合科技等发行材料显示UBB和交换板可处在22—50层范围，但加速器板、CPU主板的层数区间可能跨过18层门槛，不能整族全计。趋势上，AI服务器PCB价值通常高于通用服务器，但第三方倍数只作为方向，不替代公司订单和板面积。

### 建模与分析

最透明的条件化区间是：只计UBB时，8加速器节点可明确归入18层以上的毛面积基准约0.244平方米；若8块OAM也全部达到18层以上，UBB加OAM的广义毛面积上限约0.379平方米。实际模型以0.28平方米为2026年中值，并逐步升至2030年0.36平方米；这个中值还综合了并非所有OAM都落入严格层数以及配套交换板的可能贡献。拼板利用率、边料、返工和备品没有公开一致数据，因此没有把毛面积误写成成品交付面积。

### 分析与结论

8加速器节点的优势是BOM边界比机架级专有系统透明，供应商数量也可能更多；因此需求确定性较高，但长期价格弹性弱于最复杂的机架级板。真正的约束是高层UBB的大板良率、低损耗材料、通孔可靠性和客户认证，而不是普通多层板总产能。模型基准路径下，该架构占比从33%降至24%，但单节点面积和单价上升，需求金额仍增长。若OCP兼容设计扩大、第二供应商认证加快，供给释放会快于机架级板；若板层继续上升且局部HDI成为必需，扩展口径会比严格口径多约18%，两者必须分列。""" + supplement_tail["eight_accelerator_ubb"],
        "custom_asic_system_boards": f"""### 问题

云厂ASIC、昇腾和国产GPU系统能否形成独立高多层板机会，必须把芯片、主机、机柜、集群和云厂自用部署分开。Google TPU v5p公开的是芯片、主机和Pod拓扑，AWS公开的是每个Trn2实例与UltraServer的芯片组合；这些架构事实可以约束节点换算，却没有公开PCB层数和供应商。{_cite(asic_ref, 'DMD-AR014', 'DMD-AR015')}

### 证据与数据

ASIC路线的需求有两类证据：一是Google、Amazon等自研芯片已形成可核验部署，二是2026年资本开支仍高。云厂自建是最终部署，不是OEM新增出货，不能与服务器厂交付再相加。Amazon披露Trainium2累计部署和UltraServer拓扑，为ASIC规模提供代理；华为披露SuperPoD的最大NPU配置和部署数量，但没有公开每套配置、PCB层数或板供应商。{_cite('DMD-DF008', 'DMD-AR014', 'DMD-AR016')}

### 建模与分析

模型把ASIC节点作为AI服务器节点的一部分，2026年占27%，与TrendForce 2026年4月更新后的约27%校准；到2030年升至33%。每节点严格高多层板有效面积由0.22平方米增至0.30平方米。面积上升是假设更强互联和更高功耗带来主板、基板与交换板升级；效率提升、芯片集成和光互联也可能抵消板数，因此没有采用GPU平台的BOM直接外推。{_cite('DMD-DF013')}

### 分析与结论

ASIC系统给高多层板带来的不是单一标准化大市场，而是多个客户私有平台。对供应商而言，这意味着一旦完成认证，生命周期和切换壁垒可能较高；但公开资料对具名客户和份额最不透明，不能用“服务国际客户”“进入数据中心”补成某云厂关系。中国需求还受国产加速器可得性、整机生态和网络互联影响。基准模型把中国最终需求从2026年17%升至2030年21%，这只是研究区间中值，与2026年中国生产地占全球22层以上产值约69.1%完全不同。生产地比例不能替代客户部署地，也不能证明国产客户份额。""" + supplement_tail["custom_asic_system_boards"],
        "datacenter_switch_boards": f"""### 问题

数据中心交换与互联板是否比计算主板更紧，关键看800G/1.6T交换、NVLink域扩大和无缆化设计怎样增加高速层数、材料等级与背钻，而不是看整个交换机市场出货。AI集群里的交换板、PCIe板、背板和中板可能同时存在，但它们属于同一系统BOM，不能分别估算后再与整机PCB总额重复相加。

### 证据与数据

NVL72官方确认9个交换托盘和18颗NVSwitch，为交换域数量提供硬边界；板块数、层数和面积仍未披露。{_cite(switch_ref)} TrendForce对下一代平台的材料和层数预测显示部分板进入M8/M9与更复杂层数，但属于行业预测，必须由供应商量产面积、单价和客户认证继续验证。{_cite(material_ref)} TTM、ISU Petasys、沪电和金像电等公开材料能证明高层板或数据中心业务能力，不等于已经获得某一平台的确定份额。

### 建模与分析

本实体没有单独加到服务器节点需求之外；交换与互联板已经包含在各架构有效面积中。独立实体页的作用是追踪其材料、层数、认证和价格强度，而不是制造第二套需求总量。供给判断看完成高速材料、超大板、背钻和可靠性认证的有效产能，普通交换机板和18层以下板不计入。

### 分析与结论

交换与互联高多层板的订单可见性可能晚于芯片和服务器规划，但信号完整性、孔铜可靠性和大板良率共同限制扩产。TTM公开超低损耗材料与PCIe Gen5/Gen6工艺，ISU公开约36层HPC板，说明技术门槛存在；这些能力证据本身不能证明2026年短缺。若32层以上面积、单价和供应商现金流同步改善，供给偏紧判断增强；若第二供应商认证、材料供给和良率同时改善，价格弹性会减弱。{_cite('SUP-SUP-TTM-002', 'SUP-SUP-ISU-002', wus_ref, 'AB-WUS-ASP-32PLUS')}""" + supplement_tail["datacenter_switch_boards"],
    }
    additions = {
        "rack_scale_gpu_boards": f"""

### 供需怎样穿透到厂商

机架级板的供应商筛选不能只看最高层数。第一道门槛是至少有32层以上或复杂高层板批量证据；第二道门槛是超大尺寸、低损耗材料、背钻和多次压合能稳定通过客户验证；第三道门槛是面积与单价同步增长，而不是样品层数上升；第四道门槛是经营现金流能够覆盖扩产。沪电的32层以上销售面积由2025年一季度10,644平方米升至2026年一季度30,233平方米，单价由60,900升至65,900元/平方米，是目前最透明的批量验证之一。{_cite('AB-WUS-AREA-32PLUS', 'AB-WUS-ASP-32PLUS')}

供给反方来自扩产。TTM在美国建设面向AI数据中心的先进PCB能力，亚洲厂商也在泰国和中国大陆扩建；但是厂房、投资和混合产品产能都不能直接变成机架级有效面积。若新厂在2027—2028年完成认证并复制良率，当前紧张会缓解；若架构继续转向中央中板与无缆互联，单节点面积上升可能抵消扩产。两个方向都要用季度面积、良率和交期核验，而不是用项目公告预判。

从模型结果看，机架级架构不是靠当前占比获得最高评价，而是靠“占比和单位用量同时上升”。基准路径假设其在AI服务器中的占比由2026年的14%提高到2030年的25%，每节点严格口径面积由0.46平方米提高到0.62平方米；这使其对总面积增量的贡献明显快于传统PCIe服务器。该结果应理解为架构变化的压力测试，不是NVIDIA采购预测。对沪电、金像电子和生益电子，最有价值的验证顺序分别是32层以上季度面积与单价、机架与交换应用的量产收入、以及高层板收入和现金流能否覆盖扩产。只有三类指标同时改善，才能把“具备能力”升级为“正在兑现”。

盈利上也不能把行业需求增长机械套给所有公司。基准情景的严格面积由2026年{base[0]['strict_demand_area_million_m2'] * 100:.1f}万平方米增至2030年{base[-1]['strict_demand_area_million_m2'] * 100:.1f}万平方米，对完成认证的有效供给提出约{outputs['cross_check']['base_required_effective_supply_area_cagr_2026_2030']:.0%}的年均面积增长门槛。由于公开资料没有同口径的行业有效供给面积，这不是实际缺口预测。条件测试显示：若假设2026年供需恰好平衡，此后有效供给面积只增长20%，2030年会比基准需求少约{abs(slow_supply_2030['conditional_supply_minus_demand_area_million_m2']) * 100:.1f}万平方米；增长32%大致追平，增长45%则形成余量。厂商实际盈利还取决于高端产品占比、客户议价、材料转嫁、良率和新增折旧，必须由面积、单价、毛利和现金流共同验证。{_cite('MODEL-PCB-INPUTS', 'MODEL-PCB-OUTPUTS')}

### 可证伪条件

三类数据会推翻偏紧判断：下一代平台在相同算力下减少计算板或交换板成品面积；32层以上单价和交期连续两个季度回落而面积供给上升；第二来源认证后高端板利用率仍低。相反，若平台设计冻结后板面积增加、32层以上单价继续高于22—30层且材料交期没有改善，偏紧判断会增强。""",
        "eight_accelerator_ubb": f"""

### 供需怎样穿透到厂商

UBB机会更适合比较可复制的量产效率。广合公开18—46层AI服务器产品认证与400G/800G交换板量产，胜宏公开32层AI服务器高多层板大规模量产，这些证据比“能做70层”更接近当前供给。{_cite(_find_ref(metadata, '广合', '18', prefix='SUP'), _find_ref(metadata, '胜宏', '32', prefix='SUP'))} 但胜宏泰国项目只披露14层以上占比超过60%，广合收入等价能力也不是面积；两家公司都不能据此填出严格口径产能。

价格弹性取决于大板良率和材料，而不是UBB面积本身。若多家厂商掌握OCP兼容设计并完成客户认证，标准化会压缩超额利润；若同一外形继续增加层数、背钻和局部HDI，单位面积价格仍可能上升。沪电32层以上产品从2025年一季度到2026年一季度同时出现面积和单价上升，是更接近本研究口径的经营验证；但单一公司的产品组合仍不能外推成行业价格。{_cite('AB-WUS-AREA-32PLUS', 'AB-WUS-ASP-32PLUS')}

这里最容易犯的错误，是把0.244平方米UBB毛面积、8块OAM面积和配套交换板全部相加后，又把同一节点计入服务器PCB总额。本研究把UBB节点作为一种互斥架构：2026年基准占AI服务器节点的33%，到2030年降至24%；每节点严格口径面积从0.28平方米提高到0.36平方米。占比下降反映机架级和ASIC架构渗透，面积上升反映层数、配套板与互联复杂度提高。两者共同作用下，UBB仍是增长市场，但不再被写成所有AI服务器的统一BOM。

厂商受益程度应分三层核验。第一层看广合、胜宏等是否持续披露18层以上或32层以上的认证后批量产品，而非最高样品层数；第二层看高端多层板面积、单价和毛利率是否同步上升；第三层看泰国及其他新厂投产后是否复制原有客户良率。标准化有利于扩大合格供应商数量，却也会削弱单家厂商的价格权。若扩产只增加14—18层普通产品，严格口径供给不会等比例增加；若大板良率与材料认证同步改善，UBB反而可能成为四类架构中最早达到供需平衡的一类。因此本实体的核心机会是持续放量而非永久短缺。

对投资判断而言，胜宏的优势在批量和扩张弹性，广合的优势在产品层数与应用披露更清楚；但两者公开口径都不足以计算精确市场份额。与其给出一个无法复核的份额，不如持续比较认证后面积增速、平均售价、现金流和新增产线利用率。只有这些经营数据超过行业总量增速，才能证明公司在取得份额，而不只是随行业景气增长。

还要单独观察OAM是否真正跨过18层门槛：若只有UBB本体符合，严格面积更接近公开几何下限；若OAM和配套交换板也稳定采用高层设计，单位节点价值才会向扩展口径靠近。这项差异足以改变厂商收入测算，不能用统一倍数替代。

### 可证伪条件

如果主要平台从8加速器UBB转向机架级或更高度集成的专有架构，UBB份额会下降；如果OAM大量落在18层以下，当前面积中值也会偏高。相反，若OCP兼容节点继续增长、UBB层数稳定高于22层且配套交换板进入同一认证链，需求会比只计UBB的严格下限更高。""",
        "custom_asic_system_boards": f"""

### 供需怎样穿透到厂商

ASIC平台的订单更可能通过私有认证而非公开标准释放。深南、景旺、欣兴等候选都需要同时证明系统板层数、批量状态和最终应用；仅有“AI板研发”或“国际客户”不能映射成Google、AWS、华为或某一国产平台。深南的68层批量能力确认技术门槛，景旺40层以上N+N量产确认另一条供给路径；欣兴在本轮公开一手资料中缺少18层以上量产规模，因此只能作为观察对象。{_cite(_find_ref(metadata, '深南', '68', prefix='SUP'), _find_ref(metadata, '景旺', '40', prefix='SUP'), _find_ref(metadata, '欣兴', '不足', prefix='SUP'))}

中国与海外必须分开。中国最终需求的增长可能利好中国大陆供应商，但海外云厂私有ASIC仍可能由中国台湾、韩国、美国或东南亚产能交付；供应商注册地不能决定客户地。出口限制、加速器可得性和国产网络生态也会使中国节点数与海外不同步，因此模型对中国只给14%—25%的研究区间，不把某一年度生产地份额套入。

模型把ASIC节点占AI服务器的比例从2026年的27%提高到2030年的33%，每节点严格口径面积由0.22平方米提高到0.30平方米。这个设定同时承认两件事：云厂自研芯片的部署规模在扩大，但专有系统可能通过更高集成度减少板数。因而结果不是把TPU、Trainium或昇腾芯片颗数直接换算成PCB，而是先统一到可比较的服务器节点，再用面积区间计量。任何新证据若只给芯片数而没有主机拓扑，都只能影响方向，不能直接改写面积需求。

深南、景旺和欣兴的定位也不同。深南已有复杂高层板批量能力，更需要验证AI系统板收入和客户认证；景旺同时覆盖高多层与高阶HDI，更需要拆分两种工艺的实际贡献；欣兴在本轮公开一手证据中只确认AI系统板研发，尚不足以证明18层以上批量规模。三家公司都可能受益，但证据强度不能写成同一档。后续若公司披露的只是“数据中心”“国际客户”或研发能力，而没有层数、批量状态和出货面积，结论仍应停留在候选供应商。

中国最终需求的基准金额由2026年约{base[0]['china_end_demand_usd_bn'] * 10:.1f}亿美元增加到2030年约{base[-1]['china_end_demand_usd_bn'] * 10:.1f}亿美元，这是模型按最终部署地划分的结果；同期中国生产地在全球高层板产值中的高占比是供给地概念。两者不能相减成出口量，也不能据此推导国产替代率。真正决定盈利的是供应商是否跨过私有认证、能否稳定交付低损耗高层板，以及客户是否允许第二来源。由于这些数据大多受保密协议限制，本研究宁可保留区间，也不使用匿名传闻填补具名客户关系。{_cite('MODEL-PCB-INPUTS', 'MODEL-PCB-OUTPUTS')}

### 可证伪条件

若自研芯片验证推迟、每芯片性能提升快于部署数量，或云厂资本开支更多流向电力和建筑而非服务器，ASIC板需求会低于情景。若Trainium、TPU、昇腾和国产GPU的公开部署持续扩大，同时供应商披露18层以上认证后批量面积，机会判断才会从架构方向升级为公司订单判断。""",
        "datacenter_switch_boards": f"""

### 供需怎样穿透到厂商

交换板候选需要公开高速网络和高层板同时存在。TTM披露数据中心工艺、超低损耗材料和PCIe Gen5/6能力，ISU定位为超高多层专业制造商且HPC产品资料给出约36层，金像电子公开56层能力，沪电交换机与路由器PCB收入增长较快；这些事实支持候选池，但没有一项自动等于某个NVLink或以太网平台份额。{_cite(_find_ref(metadata, 'ttm', 'pcie', prefix='SUP'), _find_ref(metadata, 'isu', '36', prefix='SUP'), _find_ref(metadata, '金像', '56', prefix='SUP'), _find_ref(metadata, '沪电', '交换机', prefix='SUP'))}

材料等级会随平台升级。公开行业预测把Rubin交换托盘指向M8U、部分中板和互联板指向M9，但这只能说明设计方向，不能证明2026—2028年的可售材料产能或缺口。{_cite(material_ref, material_next_ref)} 因此材料是否成为瓶颈，要由板厂实际投料、良率、交期和材料厂可售产能共同验证，不能用技术等级名称直接推断短缺。

交换与互联板没有在总量模型中另加一遍，是为了避免与机架级、UBB和ASIC节点内已经包含的配套板重复。独立追踪它仍然重要，因为同一节点面积中，交换板往往采用更高材料等级、更复杂背钻和更大尺寸，单位面积价值和良率约束可能显著高于计算主板。需求总量回答“需要多少板”，本实体回答“其中价值量和短缺更可能集中在哪些板”，两者用途不同。

对TTM、ISU、金像电子和沪电，证据强弱也要分开：TTM和ISU的一手资料能够把数据中心应用与高层板能力连接起来；金像电子确认较高层数能力；沪电则能用32层以上面积、单价及交换机与路由器收入观察量产兑现。没有公开料号和具名平台时，四家公司都不能写成某个NVLink或以太网系统的确定份额。更稳妥的比较是看高端板销售面积、平均售价、交期、经营现金流与客户认证是否同向变化。

价格弹性更可能集中在高层交换板和复杂中板，而非均匀分布到普通多层板；但公开资料没有同口径有效供给起点，因此不能指定某一年由宽松转为短缺。更可靠的时序判断是：材料扩产、泰国新厂爬坡、第二供应商认证和良率改善属于供给领先指标，终端节点数量与单节点面积属于需求指标。只有两组指标同时指向紧张，并且同层数单价与毛利连续验证，才可以上调对交换板盈利弹性的判断。

### 可证伪条件

下一代互联可能减少部分传统板卡，也可能把连接功能迁入中央中板。NVIDIA只确认Rubin采用无电缆计算托盘，没有公开成品板面积净变化；因此必须跟踪逐板BOM，不能按“无缆化”概念直接上调或下调需求。若板数与面积下降、第二供应商认证和良率同步改善，价格弹性会减弱；若功能迁移使中板层数和面积上升，单位系统价值仍可能增加。{_cite('DMD-DR006')}""",
    }
    for key, addition in additions.items():
        sections[key] += addition
    result = []
    for key, body in sections.items():
        refs = sorted(set(re.findall(r"\^src:source_ref:([A-Za-z0-9_.-]+)", body)))
        result.append(
            {
                "entity_key": key,
                "section_key": "entity_research",
                "section_title": f"{ENTITY_SPECS[key]['name']}：证据、估算与结论",
                "body_markdown": body,
                "support_status": "partially_supported",
                "evidence_ref_uri_list": [source_uri(ref) for ref in refs],
            }
        )
    return result


def _main_sections(
    outputs: Mapping[str, Any], metadata: Sequence[Mapping[str, Any]], inputs: Mapping[str, Any]
) -> list[dict[str, Any]]:
    base = outputs["scenarios"]["base"]["rows"]
    slow = outputs["scenarios"]["conservative"]["rows"]
    fast = outputs["scenarios"]["optimistic"]["rows"]
    lead_ref = "DMD-DR004"
    material_ref = "DMD-PB008"
    material_next_ref = "DMD-PB009"
    expansion_ref = "SUP-SUP-VG-004"
    ttm_ref = _find_ref(metadata, "ttm", "70", prefix="SUP")
    shennan_ref = _find_ref(metadata, "深南", "68", prefix="SUP")
    victory_ref = _find_ref(metadata, "胜宏", "32", prefix="SUP")
    guanghe_ref = _find_ref(metadata, "广合", "18", prefix="SUP")
    anchor = inputs["ai_server_anchor"]
    slow_supply_2030 = outputs["conditional_supply_paths"]["slow"]["rows"][-1]
    fast_supply_2030 = outputs["conditional_supply_paths"]["fast"]["rows"][-1]
    required_supply_cagr = outputs["cross_check"]["base_required_effective_supply_area_cagr_2026_2030"]
    architecture_labels = {
        "pcie_gpu": "PCIe GPU服务器",
        "oam_ubb": "8加速器OAM/UBB",
        "rack_scale_gpu": "机架级GPU",
        "custom_asic": "定制ASIC",
        "other_domestic": "其他国产系统",
    }
    architecture_2026 = outputs["yearly_architecture"]["2026"]
    architecture_2030 = outputs["yearly_architecture"]["2030"]
    architecture_rows = "\n".join(
        "| {label} | {share_2026:.0%} | {share_2030:.0%} | {area_2026:.2f} | {area_2030:.2f} |".format(
            label=label,
            share_2026=architecture_2026["mix"][key],
            share_2030=architecture_2030["mix"][key],
            area_2026=architecture_2026["strict_area_m2_per_server"][key],
            area_2030=architecture_2030["strict_area_m2_per_server"][key],
        )
        for key, label in architecture_labels.items()
    )
    sections = [
        {
            "section_key": "summary",
            "section_title": "摘要",
            "body_markdown": f"""### 研究回答

2026—2030年，18层以上刚性高多层PCB的需求大概率继续增长，但不能据此得出“全行业持续短缺”。更准确的结论是：22—30层的可复制供给会随着中国大陆、东南亚和北美扩产逐步增加；32层以上、M8/M9低损耗材料、超大尺寸、复杂背钻和客户认证同时满足的有效供给，在机架级GPU与高速交换场景中更紧。TrendForce在2026年5月仍预计当年AI服务器出货增长超过28%，4月更新给出的ASIC占比约27%；4月更新还提到接近一年的交期，但明确指向通用服务器关键PCB与CPU，只能说明服务器供应链错配和AI订单优先级，不能当作18层以上AI板的直接交期证据。{_cite('DMD-DF014', 'DMD-DF013', 'DMD-DR004')}

### 核心数字

模型以2024年167万台预测和2025年28%增长预测计算出{anchor['units_million'] * 100:.0f}万台的2025年情景起点；它不是2025年实际统计。基准路径得到2026年{base[0]['ai_server_units_million'] * 100:.0f}万台、2030年{base[-1]['ai_server_units_million'] * 100:.0f}万台。按架构占比和18层以上有效面积估算，严格口径面积由2026年{base[0]['strict_demand_area_million_m2'] * 100:.1f}万平方米增至2030年{base[-1]['strict_demand_area_million_m2'] * 100:.1f}万平方米；含局部HDI复合板的扩展口径为{base[0]['strict_plus_local_hdi_area_million_m2'] * 100:.1f}万至{base[-1]['strict_plus_local_hdi_area_million_m2'] * 100:.1f}万平方米，两者不相加。基准产值需求由{base[0]['bottom_up_demand_usd_bn'] * 10:.1f}亿美元增至{base[-1]['bottom_up_demand_usd_bn'] * 10:.1f}亿美元。CIC受发行人委聘的研究把22层以上全应用市场估为2026年80亿美元、2030年131亿美元；它排除18—21层却包含汽车、通信等非AI应用，与本研究集合互不包含，因此不再用来计算AI份额、有效供给或缺口。{_cite('DMD-DF001', 'DMD-DF003', 'MODEL-PCB-INPUTS', 'MODEL-PCB-OUTPUTS', 'AB-WUS-22PLUS-MARKET')}

### 供需判断

公开资料没有给出全球18层以上、完成AI客户认证并达到批量良率的同口径成品面积，因此本研究不能负责任地给出2026—2030年的行业绝对供给或实际缺口。可以计算的是追赶门槛：基准需求面积四年年均增长约{required_supply_cagr:.0%}；若假设2026年供需恰好平衡，有效供给面积此后也要维持相近增速才能在2030年大致跟上。20%和45%的供给增速只用于展示下方与上方敏感性，不是产能预测。{_cite('MODEL-PCB-INPUTS', 'MODEL-PCB-OUTPUTS')}

### 公司与客户

十家公司中，TTM、深南、胜宏、景旺、金像电子和ISU有明确的18层以上直接能力或量产证据；生益电子、沪电、广合分别有高层板产品、AI/交换收入或18—46层认证证据，但公开总产能不能直接换算为严格口径；欣兴电子的AI系统板研发和业务敞口值得跟踪，本轮一手资料不足以确认18层以上量产规模。{_cite(ttm_ref, shennan_ref, victory_ref, _find_ref(metadata, '景旺', '40', prefix='SUP'), _find_ref(metadata, '金像', '56', prefix='SUP'), _find_ref(metadata, 'isu', '36', prefix='SUP'), _find_ref(metadata, '生益', '20', '50', prefix='SUP'), _find_ref(metadata, '沪电', 'ai服务器', prefix='SUP'), guanghe_ref, _find_ref(metadata, '欣兴', '研发', prefix='SUP'))} 客户份额方面，只有一项受托研究明确列出沪电在2025年全球22层以上全应用市场的估计份额14.9%，它不是AI客户份额；同一研究给出的前五份额为62.3%，其余竞争者匿名，不能擅自映射。{_cite('AB-WUS-SHARE', 'AB-WUS-CR5')}

### 结论

机会最集中在“已经批量、完成客户认证、32层以上产品面积与单价同时上升”的供应商，而不是宣称最高层数或宣布大额扩产的公司。沪电32层以上产品的销售面积由2025年一季度1.06万平方米增至2026年一季度3.02万平方米，单价由6.09万元升至6.59万元/平方米，是目前最直接的经营验证之一；它仍不能外推成行业价格。{_cite('AB-WUS-AREA-32PLUS', 'AB-WUS-ASP-32PLUS')} 沪电在2026年6月的最新交流中同时提示：成熟技术平台的新增产能可能压低准入门槛和利润，而高阶产品仍可能“入场者多、通关者少”。这是单一公司的前瞻判断，不是行业实测，但它说明扩产与高端认证壁垒可以同时存在。{_cite('SUP-SUP-WUS-007', 'SUP-SUP-WUS-008')} 后续最重要的证伪信号是：AI服务器增长下调、架构集成减少板数、供应商良率和第二来源认证快速改善、M8/M9材料实际可售产能增加，以及新厂资本开支先于订单形成过剩。{_cite('DMD-DR006', material_ref, material_next_ref, expansion_ref, 'SUP-SUP-TTM-004')}

### 如果想进一步研究，需要补充的信息

最能收窄结论区间的是专有平台的板级BOM、供应商按18—30层与32层以上拆分的季度面积和单价、认证后良率及第二来源进度。没有这些数据前，报告可以判断需求方向、约束环节和受益候选，不能把行业情景写成具名客户订单或精确公司份额。""",
        },
        {
            "section_key": "scope_and_counting",
            "section_title": "口径与防止重复计算",
            "body_markdown": f"""### 问题

本研究先解决“究竟在数什么”。GPU/ASIC供应商卖芯片或模组，云厂商部署自用算力，OEM/ODM交付服务器，最终客户再把服务器组成机柜和集群。这四层描述同一条链条的不同位置，不能相加。NVIDIA一套NVL72的72颗GPU、18个计算托盘和一个机架是同一系统的三个单位；Google一个TPU Pod的芯片、主机、机柜和Pod也是嵌套关系。{_cite('DMD-AR008', 'DMD-AR012')}

### 统计规则

需求模型只选择“AI服务器节点/整机”作为主计数单位。GPU、ASIC和NPU颗数用于校验每节点加速器数；机柜和集群用于校验拓扑；云厂自建与OEM交付只用于判断渠道和最终部署，不再加到节点总量。公开资料显示2024年AI服务器预测在167万至200万台之间，差约19.8%，主要来自定义和更新时间差异；本研究不机械平均两家口径，而是把差异转成情景宽度。{_cite('DMD-DF001', 'DMD-DF005', 'DMD-DF006')}

对华为、浪潮信息、新华三、超聚变、中兴通讯、中科曙光、联想、宁畅、华鲲振宇和神州鲲泰的2025—2026年官方材料复核后，只有华为披露累计部署300多套SuperPoD、中兴披露一个千卡级国产GPU资源池，其他公开数字主要是单机或单柜满配规格。即使是实际部署，也缺少可统一的服务器节点配置；因此这些数字只校验产品存在、拓扑和部署方向，不直接加到年度节点预测。华鲲振宇约10.35万台年产能还包含通用服务器和外协能力，不能改写成AI服务器出货。{_cite('OEM-OEM001', 'OEM-OEM006', 'OEM-OEM011')}

产品边界同样严格。核心只计18层以上刚性高多层板，包括达到门槛的主板、UBB、GPU/ASIC底板、PCIe/交换板、背板、中板和交换机板。18层以下普通板、纯HDI、IC/ABF载板、FPC全部排除；高多层加局部HDI的复合板只在扩展口径中单列。公开产品资料显示，加速器板可跨12—22层、CPU主板可跨14—24层，不能把整个产品族都纳入18层以上；每条公司证据都必须回到具体层数和产品。{_cite('DMD-PB005', 'DMD-PB006')}

### 地域规则

生产地、供应商注册地、直接客户和最终部署地分别记录。中国大陆生产了多少高层板，不等于中国最终部署了多少AI服务器；中国供应商在海外工厂生产，也不能自动归入中国最终需求。模型只给中国最终需求研究区间：基准由2026年的17%升至2030年的21%，对应{base[0]['china_end_demand_usd_bn'] * 10:.1f}亿美元升至{base[-1]['china_end_demand_usd_bn'] * 10:.1f}亿美元；海外需求由{base[0]['overseas_end_demand_usd_bn'] * 10:.1f}亿美元升至{base[-1]['overseas_end_demand_usd_bn'] * 10:.1f}亿美元。这个拆分是研究假设，不是把某一生产地份额改名为需求份额。{_cite('MODEL-PCB-INPUTS', 'MODEL-PCB-OUTPUTS')}

### 结果怎样使用

自下而上结果回答AI服务器可能消耗多少18层以上板。公开的CIC 22层以上市场覆盖全部下游，与本研究集合不一致，只用于说明为什么不能直接比较，不能充当该估算的上限或供给分母。公司总PCB产能、总收入、厂房面积和资本开支也不能直接填入有效供给；只有18层以上、完成客户认证、达到批量良率并可在研究期交付的部分才可比较。若公开资料只写“国际客户”“AI相关”或“服务器板”，报告保留应用方向，不补成具名云厂、具体料号或供应份额。""",
        },
        {
            "section_key": "architecture_and_demand",
            "section_title": "架构、板卡BOM与需求测算",
            "body_markdown": f"""### 问题

需要回答的是：不同AI服务器架构各自消耗多少18层以上刚性板，架构占比和单节点面积变化后，2026—2030年的需求区间有多大，以及哪些工程假设最影响结果。

### 证据与数据

板卡需求的关键不是服务器数量单一变量，而是架构变化。OCP UBB 1.5公开417毫米×585毫米尺寸并支持8个OAM；一块UBB毛面积为0.243945平方米，若再把8块102毫米×165毫米OAM全部计入，合计0.378585平方米。{_cite('DMD-AR001', 'DMD-AR002', 'DMD-AR003', 'DMD-AR004')} 但层数来自具体产品资料，OAM并非全部达到18层，且NVL72、TPU、Trainium和昇腾都有专有拓扑，不能共用一套BOM。这些公开尺寸和拓扑约束单节点面积的上下界，供应商产品资料再约束哪些板能够进入18层以上严格口径。

### 建模方法

模型把节点分成五类。数据较多且需要横向比较，因此把2026年起点与2030年终点集中列在一张表中：

| 节点架构 | 2026年占比 | 2030年占比 | 2026年严格有效面积（平方米/节点） | 2030年严格有效面积（平方米/节点） |
|---|---:|---:|---:|---:|
{architecture_rows}

2026年的GPU相关架构合计72%、定制ASIC占27%；ASIC占比采用TrendForce 2026年4月更新后的约27%，此后占比是研究假设。{_cite('DMD-DF013')} 每类架构的有效面积是工程区间中值，不是专有BOM。

> **核心需求模型**
>
> 年度严格需求面积 = AI服务器节点数 × Σ（各架构占比 × 该架构单节点18层以上有效面积）
>
> 年度产值需求 = 年度严格需求面积 × 当年情景单价

节点数乘以架构加权面积得到严格口径面积；再乘以单价得到产值。单价从2026年的5800美元/平方米升至2030年的6700美元/平方米，参考沪电22—30层与32层以上实际单价差异校准，但仍是情景输入。沪电2026年一季度22—30层单价约2.37万元人民币/平方米，32层以上约6.59万元人民币/平方米，说明层数和工艺组合会显著改变价值量。{_cite('AB-WUS-ASP-22-30', 'AB-WUS-ASP-32PLUS')}

### 结果与交叉验证

基准严格面积依次为{'、'.join(f"{row['year']}年{row['strict_demand_area_million_m2'] * 100:.1f}万平方米" for row in base)}；产值依次为{'、'.join(f"{row['year']}年{row['bottom_up_demand_usd_bn'] * 10:.1f}亿美元" for row in base)}。含局部HDI扩展口径统一乘1.18，只用于敏感性，不与严格口径相加。面积由节点数量与单位节点面积共同推动，产值还叠加单价假设；因此面积结果比产值结果少一层价格假设，更适合与未来供给面积比较。{_cite('MODEL-PCB-INPUTS', 'MODEL-PCB-OUTPUTS')}

### 分析与结论

公开市场资料没有给出与本研究完全一致的总量。CIC/Prismark的受托研究给出22层以上全应用市场，但本研究计算的是18层以上AI服务器需求：前者排除18—21层且包含汽车、通信等非AI应用，后者包含18—21层且只取AI服务器，两者集合互不包含。因此该序列只作为口径背景，不充当供给分母或需求上限。{_cite('AB-WUS-22PLUS-MARKET')}

因此报告不再输出“AI占22层以上市场比例”，也不再根据两条不可比序列是否交叉来判断模型失效。真正可复核的敏感性来自三项输入：AI服务器节点数、不同架构的占比、每节点达到18层门槛的成品面积。需求较快情景只是三项假设同时偏高的压力测试；若未来取得专有BOM或同口径18层以上全市场数据，应优先替换这些输入，而不是把咨询机构口径差异解释成市场突然扩大。

### 如果想进一步研究，需要补充的信息

最需要的是GB300/Rubin、TPU、Trainium、昇腾和国产GPU平台的可生产板级BOM：每块板数量、成品尺寸、层数、材料、拼板利用率、良率与备品率。没有这些信息，面积区间可以支持方向和压力测试，但不能支持厂商订单的伪精确值。""",
        },
        {
            "section_key": "supply_and_customer",
            "section_title": "厂商有效供给、扩产与客户验证",
            "body_markdown": f"""### 问题

“能做70层”与“2027年能向AI客户稳定交付多少平方米”是两件事。有效供给至少同时满足具体产品达到18层以上、客户认证完成、批量良率稳定、关键材料可得和研究期内可交付。厂房面积、投资额、14层以上混合产能、普通多层板收入和最高样品层数都不能直接折算。

### 当前证据

TTM公开70层以上能力，并把东莞、广州列为先进多层与高层数板批量基地；深南披露68层批量、120层样品；胜宏有32层AI服务器高多层板大规模量产；景旺有40层以上N+N量产；金像电子公开最高56层；ISU定位为超高多层专业制造商，HPC产品资料给出约36层。{_cite(ttm_ref, shennan_ref, victory_ref, _find_ref(metadata, '景旺', '40', prefix='SUP'), _find_ref(metadata, '金像', '56', prefix='SUP'), _find_ref(metadata, 'isu', '36', prefix='SUP'))} 这些事实确认候选资格，但仍没有统一的公司级18层以上有效面积。

生益电子公开服务器板20—50层、背板最高56层，但吉安70万平方米是混合高多层口径；沪电AI服务器和交换机收入已经兑现，泰国有2家正式认证、4家导入，却没有在最新文件中拆出这些收入对应层数；广合有18—46层AI服务器产品认证和400G/800G交换板量产，仍需剔除纯HDI。欣兴电子在本轮一手资料中只确认AI系统板研发与业务方向，无法确认18层以上量产规模，因此不进入定量供给加总。

### 扩产与爬坡

扩产是主要反方。胜宏泰国高多层项目规划150万平方米，TTM美国先进PCB项目以及深南、生益、广合的泰国项目均处于建设、投产或爬坡阶段。{_cite(expansion_ref, 'SUP-SUP-TTM-004', 'SUP-SUP-SCC-004', 'SUP-SUP-SYE-005', 'SUP-SUP-DELTON-004')} 但这些项目混合14层以上、HDI、普通多层与高端产品，不能全额放进供给。模型因此不再编造公司产能加总，只计算假设2026年供需平衡后，有效供给面积需要接近32%的年增速才能追上基准需求。这个门槛后续必须用分产品面积、良率和认证数据替换。

沪电在2026年6月24日的最新交流中把这一反方说得更直接：同行新增产能落地可能摊薄成熟技术平台的准入门槛，使竞争同质化并挤压利润；同时，高阶产品仍受研发、稳定量产和全球产能协同约束，可能继续向头部集中。{_cite('SUP-SUP-WUS-007', 'SUP-SUP-WUS-008')} 这两项是发行人的行业判断，不是已经发生的产能或利润数据。它们支持的是分层结论：22—30层等较成熟平台的供给压力可能更早出现，32层以上复杂产品是否宽松仍要看认证和良率。

### 客户和份额

客户矩阵只记录直接客户、间接渠道、终端应用和验证阶段。公开“覆盖全球前十大服务器厂商中的8家”不能告诉我们哪一家、采购什么板或份额多少；“多家全球客户认可”也不能证明全部采购18层以上板。沪电泰国2家正式认证与4家导入是验证阶段，不是客户份额。受托市场研究估计沪电在2025年22层以上全应用市场占14.9%、前五合计62.3%，其余前五名匿名；本研究只把它作为市场结构参考，不采用历史数据点中对匿名公司的名称映射。{_cite('AB-WUS-SHARE', 'AB-WUS-CR5')}

### 结论

供给端最值得优先跟踪的是沪电32层以上面积和单价、胜宏32层批量与泰国爬坡、TTM/深南/景旺/金像/ISU的高层板批量与客户认证，以及广合/生益对混合口径的进一步拆分。任何供应份额只有在分母、年份、产品范围和客户关系同时明确时才给精确值；其他公司只保留证据边界，不用总收入强算份额，也不给高、中、低概率标签。""",
        },
        {
            "section_key": "balance_price_profit",
            "section_title": "2026—2030年供需、价格与利润",
            "body_markdown": f"""### 问题

本节要回答的是：在没有同口径行业产能数据的情况下，2026—2030年完成认证的有效供给至少要增长多快，才能追上18层以上AI高多层板需求；现有公开证据能否支持“行业已经或即将全面短缺”。

### 证据与数据

需求侧有服务器增速、公开架构尺寸和公司分层单价；供给侧却只有分散的最高层数、混合产能、项目投资和少量量产状态。十家公司的分母不同，不能相加成全球18层以上有效面积。沪电32层以上销售面积和单价同步上升，支持“高端细分需求较强”；TrendForce所说接近一年的交期针对通用服务器关键PCB与CPU，不能当作18层以上AI板的直接交期证据。泰国、中国大陆和北美扩产构成反方。{_cite('AB-WUS-AREA-32PLUS', 'AB-WUS-ASP-32PLUS', lead_ref, expansion_ref, 'SUP-SUP-TTM-004')}

### 计算方法

模型先算基准需求面积：2026年{base[0]['strict_demand_area_million_m2'] * 100:.1f}万平方米，2030年{base[-1]['strict_demand_area_million_m2'] * 100:.1f}万平方米，对应四年年均增长约{required_supply_cagr:.0%}。供给部分不再用22层以上市场金额乘人工比例，而改成条件门槛：假设2026年有效供给面积恰好等于当年基准需求，再分别测试此后年增20%、32%和45%。这个起点只是为了回答“供给增速要多快”，不能说明2026年实际平衡。{_cite('MODEL-PCB-INPUTS', 'MODEL-PCB-OUTPUTS')}

> **条件供给路径**
>
> 某年有效供给面积 = 2026年基准需求面积 ×（1 + 假设年增长率）^（该年份 − 2026）

由于没有同口径的行业有效供给起点和足够长的历史回归样本，本研究不输出数值化的行业价格或毛利率预测。价格与盈利只用同层数产品的实际面积、单价、毛利率，以及材料、折旧和产能爬坡证据判断方向；只有这些指标连续两个季度同向变化，才增强对价格和利润弹性的判断。

### 分析与结论

在上述条件起点下，有效供给面积若年增20%，2030年约{slow_supply_2030['conditional_supply_area_million_m2'] * 100:.1f}万平方米，比基准需求少约{abs(slow_supply_2030['conditional_supply_minus_demand_area_million_m2']) * 100:.1f}万平方米；年增32%时与需求大致相当；年增45%时约{fast_supply_2030['conditional_supply_area_million_m2'] * 100:.1f}万平方米，形成明显余量。因此真正的判断不是“2030年必然短缺”，而是完成认证的有效面积能否持续接近{required_supply_cagr:.0%}的年增速。公开资料尚不足以证明全球行业能或不能达到这个门槛。

当前能够支持的结论更窄：32层以上、低损耗材料、超大尺寸、复杂背钻和客户认证同时满足的供给，比普通多层板更紧；已经量产且面积、单价、良率与现金流同步改善的厂商更可能受益。沪电2026年6月还披露部分超低损耗树脂、HVLP铜箔和特种玻纤布存在阶段性产能受限，但没有给出交期、价格或可售量，因此只能确认约束方向，不能量化材料缺口。{_cite('SUP-SUP-WUS-009')} 行业绝对缺口、缺口发生年份以及由此产生的价格和毛利变化，目前都无法根据公开资料直接推断。

### 价格和利润的现实证据

沪电2026年一季度32层以上销售面积由上年同期1.06万平方米增至3.02万平方米，单价由6.09万元升至6.59万元/平方米，比单看最高层数更能验证批量需求。{_cite('AB-WUS-AREA-32PLUS', 'AB-WUS-ASP-32PLUS')} 深南2025年PCB业务收入同比增长36.84%、毛利率35.53%，并称AI服务器相关订单显著增加；广合2025年收入和净利润分别增长46.89%与50.24%。{_cite('SUP-SUP-SCC-003', 'SUP-SUP-DELTON-003')} 后两项是公司或PCB业务整体口径，不能把全部增量归因于18层以上AI板，也不能由此估计行业毛利弹性。

### 反方与证伪条件

偏紧判断会在四种情况下明显转弱：AI服务器增速持续低于当前情景；更高集成或无缆化减少成品板面积；泰国、中国大陆和北美扩产快速完成客户认证与良率爬坡；M8/M9相关材料的实际可售供给和板厂良率明显改善。{_cite('DMD-DR006', material_ref, material_next_ref, expansion_ref, 'SUP-SUP-TTM-004')} 相反，若32层以上面积和单价继续强于22—30层，并且经营现金流覆盖资本开支，细分供给偏紧判断增强。

### 如果想进一步研究，需要补充的信息

需要补齐按层数和应用拆分的实际成品面积、客户认证后良率、利用率、交期和材料长协价格，用真实供给起点与增速替换条件路径。只有拿到公司产品组合、材料成本转嫁和新增折旧，面积缺口才可能进一步转成逐公司的盈利变化。""",
        },
        {
            "section_key": "monitoring_and_limits",
            "section_title": "结论边界与后续跟踪",
            "body_markdown": f"""### 当前可以认为的结论

第一，AI服务器高多层板需求在2026—2030年增长的方向证据较强，增量更集中于机架级GPU、高速交换和私有ASIC系统，而不是所有普通服务器板。第二，供给瓶颈是完成客户认证后的32层以上、低损耗材料、超大板和复杂工艺能力，不是PCB总产能。第三，公开资料不足以形成十家公司逐年的精确有效供给和客户份额，因此报告只计算有效供给需要达到的面积增长门槛，不声称存在可量化的行业绝对缺口；公司层面比较量产、认证、面积、单价与现金回报。

### 哪些结论仍然不能下

目前不能声称某云厂的板由哪家公司供应多少，也不能把厂商总收入、14层以上产能、厂房面积或技术最高层数换成18层以上有效面积。受托研究对沪电14.9%的估计只能描述全球22层以上全应用市场；其他前五名匿名，任何具名映射或AI客户份额转译都会制造假确定性。不能把GPU颗数、服务器节点、机柜、集群、云厂部署和OEM交付相加；也不能把严格高多层与局部HDI扩展口径相加。

### 每季度跟踪什么

需求侧先看AI服务器节点增速和GPU/ASIC结构，再看NVL、TPU、Trainium、昇腾等平台的板内互联变化；供给侧看18—30层与32层以上的面积、单价、良率、利用率、交期、第二供应商认证和低损耗材料供给；公司侧看相关收入能否穿透到毛利、经营现金流和资本开支回报。事件优先于固定日历：平台设计冻结、客户认证、试产、批量、良率拐点、材料扩产和订单下修发生时立即更新。

### 模型怎样更新

节点数只在同一机构定义下滚动；架构占比按实际部署修正；单节点面积只在取得新平台BOM或可信拆解后更新；单价用同层数、同材料、同板种的公司实际序列校准。条件供给路径必须逐步被公司分产品面积、良率和认证数据替代。CIC的22层以上全应用市场与18层以上AI需求不是包含关系，后续也不得把两者相除或用交叉点判断模型失效。

### 如果想进一步研究，需要补充的信息

优先级最高的是专有平台可生产BOM和供应商分产品季度数据；其次是客户认证后批量出货、良率和二供进度；再次是HVLP铜箔、低介电玻纤、M8/M9覆铜板的可售产能与长协价格。拿到这些信息后，才能把当前行业情景收敛为公司级有效供给、客户份额和盈利敏感性；在此之前，本研究只给条件化机会判断，不给交易指令、仓位或目标价。""",
        },
    ]
    additions = {
        "scope_and_counting": f"""

### 一个具体例子

NVL72的官方口径可以同时写成72颗GPU、18个计算托盘或一个机架。如果以节点作为主计数，18个计算托盘进入节点换算；72颗GPU只校验每托盘4颗，机架只校验18托盘和9交换托盘的拓扑。任何一项再加回总量都会重复。Google TPU v5p的8960颗芯片Pod、64芯片机柜和16台主机同理，只能逐层相除，不能逐层相加。{_cite('DMD-AR008', 'DMD-AR009', 'DMD-AR012')}

产品也有同样陷阱。一个服务器节点可能同时有UBB、OAM、CPU主板、交换板和控制板；如果第三方给出的“AI服务器PCB价值”已经包含整机所有板，再把逐板估算加上去就会重复。因此本研究最终需求只采用一条自下而上链条，第三方总市场仅作为口径冲突背景，不做数值边界。18层门槛按每块板判断：例如CPU主板14—24层时，不能把全部CPU主板面积纳入；加速器板12—22层也只取达到门槛的型号。{_cite('DMD-PB005', 'DMD-PB006')}

时点上，实际值、公司目标、行业预测和研究估算分别标注。公司说2026年试产，不等于全年产能；行业机构预测2030年市场，不等于订单；模型给出的面积和单价不是公司指引。这个分层使读者能够在新证据出现时只替换相应输入，而不是推倒整个模型。

### 如果想进一步研究，需要补充的信息

需要取得各平台从芯片、板卡、节点到机柜的完整换算关系，以及每块板的层数和成品面积；同时要让第三方市场数据明确是否包含HDI、载板、样板和地区内销。只有把分子、分母、产品边界和时点对齐，才适合进一步收窄需求区间。""",
        "supply_and_customer": f"""

### 为什么不做公司产能加总

十家公司的公开产能分母不一致：有的按14层以上，有的按高多层与HDI混合，有的只给厂房或投资额，有的给收入等价能力，还有的只披露技术层数。把这些数字相加会制造一个看似完整、实则不可比较的供应总量。胜宏泰国150万平方米规划包含服务器、交换机和消费电子且14层以上占比并不等于18层以上；生益吉安70万平方米没有按层数拆分；TTM美国项目给厂房面积而非成品面积。{_cite(expansion_ref, _find_ref(metadata, '生益', '70万', prefix='SUP'), _find_ref(metadata, 'ttm', '75万', prefix='SUP'))}

因此本研究把公司层面留在“可验证能力与爬坡风险”，行业层面只计算假设2026年供需平衡后所需的供给面积增长门槛，不把它写成实际供给。未来只有拿到同口径18—30层、32层以上成品面积，才能把公司表与行业需求直接衔接。份额也必须先定分母：全球22层以上市场份额、某云厂采购份额、某板种份额和某区域产能份额不是同一个指标，不能都叫“供应份额”。

### 经营检验

如果需求真实，最终应在面积、单价、利用率、毛利和现金流中至少出现两到三项一致变化。只看收入可能被汇率和产品组合误导，只看毛利可能被材料价格影响，只看资本开支则可能是未来供给而非当前订单。十家标的页因此保留至少三期财务和截至同一研究时点可取得的最近交易日估值；非人民币历史财务统一按2026年7月11日汇率折算人民币，便于横向比较，但不是各财年的平均汇率。财务只回答“需求是否兑现到经营”，不反向证明具名客户。

### 如果想进一步研究，需要补充的信息

优先补充分公司、分层数、分应用的季度成品面积、平均售价、良率、利用率、客户认证日期和量产日期；扩产项目还需要设计产能、爬坡曲线及产品组合。若能同时取得客户侧第二来源状态，才可以把当前的供应可能性进一步转成可比较的有效供给和份额。""",
        "balance_price_profit": f"""

### 单位与数量级复核

产值计算的量纲是：百万台节点×平方米/台=百万平方米，再乘美元/平方米并除以1000，得到十亿美元。以2026年基准为例，{base[0]['ai_server_units_million']:.4f}百万台×{base[0]['weighted_strict_area_m2_per_server']:.4f}平方米/台≈{base[0]['strict_demand_area_million_m2']:.4f}百万平方米；再乘{base[0]['blended_asp_usd_per_m2']:.0f}美元/平方米≈{base[0]['bottom_up_demand_usd_bn']:.4f}十亿美元。2030年同样得到{base[-1]['strict_demand_area_million_m2']:.4f}百万平方米和{base[-1]['bottom_up_demand_usd_bn']:.4f}十亿美元。这个反算与模型表一致，避免只改单位标签却不换算数值。{_cite('MODEL-PCB-INPUTS', 'MODEL-PCB-OUTPUTS')}

条件供给使用物理面积：把2026年{base[0]['strict_demand_area_million_m2'] * 100:.2f}万平方米基准需求暂作平衡起点，再按不同年增速外推。它回答“认证后有效面积至少要增长多快”，不回答行业当前真实产能，也不能推断某家公司能交付多少平方米。由于缺少可校准样本，模型不把面积偏离机械换算成价格或毛利率变化。

### 公司盈利怎样使用

对于供应商，需求增长不必然改善利润。新工厂折旧、低利用率、认证费用和材料上涨可能先压低毛利；只有高端产品面积、单价和良率共同提升，经营现金流改善，盈利才算兑现。沪电32层以上面积与单价同步上升提供正向验证；TTM披露槟城新厂仍有爬坡成本，沪电泰国工厂2025年上半年仍亏损，说明扩产初期可能先拖累利润。{_cite('AB-WUS-AREA-32PLUS', 'AB-WUS-ASP-32PLUS', 'SUP-SUP-TTM-005', 'SUP-SUP-WUS-005')}""",
        "monitoring_and_limits": f"""

### 已有证据怎样更新

现有资料已经把服务器、资本开支、架构、公司量产、扩产、客户与经营数据分开。后续更新时，同一公告的转载和翻译仍只算一个证据组，卖方研报不能覆盖公司或客户的相反披露。OCP和官方架构资料可以改变板型边界，行业机构可以改变情景起点，公司实际面积和单价才可以改变经营验证。{_cite('DMD-AR001', 'AB-WUS-AREA-32PLUS', 'AB-WUS-ASP-32PLUS')}

建议设置三组触发器。第一组是需求：AI服务器节点增速低于15%、ASIC验证再次延后、云厂资本开支下修或利用率不足；第二组是供给：新厂正式量产、第二来源认证、32层以上良率提升、关键材料产能按期释放；第三组是价格：同层数ASP、交期和毛利连续两个季度同向变化。只要其中一组触发，就重新跑三种情景，而不是等到年度报告。

研究边界本身也要复核。如果行业能够公开按18层门槛、应用和主工艺统一分类的市场与产能序列，才可以新增可比较的总量校验；如果局部HDI成为高层板必需工艺，严格与扩展口径仍需分别报告；如果无缆化减少部分板卡但增加中央中板，应按成品面积净变化更新，不能按概念方向加减。NVIDIA对Rubin的官方材料只确认无电缆计算托盘，没有公开PCB净面积。{_cite('DMD-DR006')}""",
    }
    for section in sections:
        addition = additions.get(str(section["section_key"]))
        if addition:
            section["body_markdown"] += addition
    for section in sections:
        refs = sorted(set(re.findall(r"\^src:source_ref:([A-Za-z0-9_.-]+)", section["body_markdown"])))
        section["support_status"] = "partially_supported"
        section["evidence_ref_uri_list"] = [source_uri(ref) for ref in refs]
    return sections


def _table_visual(
    *,
    key: str,
    title: str,
    subtitle: str,
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
    refs: Iterable[str],
    sort_order: int,
) -> dict[str, Any]:
    return {
        "block_key": key,
        "block_type": "table",
        "title": title,
        "subtitle": subtitle,
        "data": {"what": title, "table": {"columns": list(columns), "rows": [list(row) for row in rows]}},
        "print_fallback": {"columns": list(columns), "rows": [list(row) for row in rows]},
        "evidence_ref_uri_list": [source_uri(ref) for ref in dict.fromkeys(refs)],
        "support_status": "partially_supported",
        "red_flag_level": "none",
        "sort_order": sort_order,
    }


def _oem_rows() -> tuple[list[list[Any]], list[str]]:
    payload = _read_json(CACHE_DIR / "agent_oem_gap" / "ledger.json")
    facts_by_id = {str(fact["fact_id"]): fact for fact in payload["facts"]}
    specifications = (
        ("华为", ("OEM001",), "Atlas 900 A3 SuperPoD累计部署300多套、服务20多个客户", "公司自报的累计部署，不是服务器、NPU或PCB数量", "只确认已经形成实际部署；配置和期间拆分不足，不能换算年度节点"),
        ("浪潮信息", ("OEM002",), "元脑SD200单机可互连64路GPU", "单机满配拓扑，不是出货量", "只校验高密度系统存在；没有交付台数，不进入节点总量"),
        ("新华三", ("OEM003",), "R5500 G6最多8张GPU；400G单POD约覆盖256台服务器", "单机上限与网络设计容量", "不能把256台乘8卡后再叠加云厂部署"),
        ("超聚变", ("OEM004",), "FusionPoD for AI每机架设计64张GPU", "机架级产品设计密度", "缺少已交付机架数，只作拓扑校验"),
        ("中兴通讯", ("OEM005", "OEM006"), "自研超节点单柜64颗GPU；南京电信项目为千卡级国产GPU资源池", "前者是满配规格，后者是单项目部署量级", "两项可能指向同类设备，不能相加；只把项目作为部署方向证据"),
        ("中科曙光", ("OEM007",), "AI超集群单柜最多96张GPU，并称可扩展至百万卡级", "单柜上限与系统扩展能力", "百万卡不是已部署量，不能换算2026—2030出货"),
        ("联想", ("OEM008",), "ThinkSystem SR680a V4配置8颗NVIDIA B300 GPU", "标准产品配置", "没有地区和年度出货，只校验8卡节点形态"),
        ("宁畅", ("OEM009",), "X680 G55官方白皮书确认8-GPU AI服务器", "产品规格与产品存在性", "没有生产、销售或部署数量，不进入节点总量"),
        ("华鲲振宇", ("OEM010", "OEM011"), "AT9508 G3支持10张双宽或20张单宽卡；全部服务器年产能约10.35万台", "产品上限与混合产品产能上限", "年产能含通用服务器和外协生产，不能当作AI服务器产量"),
        ("神州数码／神州鲲泰", ("OEM012",), "R624 K2、R622 K2可用单卡昇腾NPU运行千亿参数模型", "最低可运行配置和产品能力", "没有整机交付量，不能由单卡配置倒推出服务器节点"),
    )
    rows: list[list[Any]] = []
    refs: list[str] = []
    for company, fact_ids, evidence, number_type, use_rule in specifications:
        missing = [fact_id for fact_id in fact_ids if fact_id not in facts_by_id]
        if missing:
            raise ValueError(f"OEM账本缺少{company}事实：{missing}")
        row_refs = [_ref("OEM", fact_id) for fact_id in fact_ids]
        refs.extend(row_refs)
        rows.append([company, evidence, number_type, use_rule, _cite(*row_refs)])
    return rows, refs


def _supplier_rows(metadata: Sequence[Mapping[str, Any]]) -> tuple[list[list[Any]], list[list[Any]], list[str]]:
    supply_payload = _read_json(CACHE_DIR / "agent_supply_company" / "ledger.json")
    assessments = supply_payload.get("company_assessments") or []
    facts = supply_payload["facts"]
    rows: list[list[Any]] = []
    customer_rows: list[list[Any]] = []
    refs: list[str] = []
    supply_conclusions = {
        "TTM Technologies": "现有高层板能力可确认；美国新厂和槟城扩张能贡献多少AI有效面积，取决于投产、认证与良率，公开资料不足以逐年量化。",
        "深南电路": "现有批量能力可确认；南通与泰国新线处于爬坡期，未披露18层以上面积、利用率和良率。",
        "沪电股份": "32层以上已有销售面积与单价序列，可验证放量；泰国及苏州项目的新增有效面积仍需后续季度披露。",
        "生益电子": "服务器板和背板层数符合范围；70万平方米项目是混合高多层口径，不能全额计入18层以上AI供给。",
        "胜宏科技": "32层AI服务器板已批量；泰国项目只披露14层以上占比，18层以上有效供给需重新拆分。",
        "景旺电子": "40层以上批量能力可确认；历史总产能平均层数仅高于12层，不能用总面积外推严格供给。",
        "欣兴电子": "AI系统板研发和业务敞口可确认，但本轮一手资料不足以确认18层以上量产规模，不进入公司有效供给估算。",
        "金像电子": "56层能力与AI/高速网络应用可确认；各基地没有按层数拆分面积、利用率和客户认证进度。",
        "ISU Petasys": "超高多层与HPC约36层产品能力可确认；新厂和钻孔投资不能折算为成品有效面积。",
        "广合科技": "18—46层AI产品认证和400G/800G量产可确认；收入等价能力不能换算为18层以上面积。",
    }
    customer_product = {
        "TTM Technologies": "数据中心、网络、PCIe Gen5/Gen6高层板",
        "深南电路": "AI服务器及复杂高速背板",
        "沪电股份": "AI服务器、高速交换与1.6T交换机PCB",
        "生益电子": "20—50层服务器板与最高56层背板",
        "胜宏科技": "32层AI服务器高多层板",
        "景旺电子": "20层以上数据基础设施板与40层以上N+N板",
        "欣兴电子": "高速AI服务器板与高速光通信板研发",
        "金像电子": "AI及先进服务器、高速网络多层板",
        "ISU Petasys": "HPC约36层板与网络高层板",
        "广合科技": "30层以上PCIe交换板、28—46层UBB/IO板、18层以上OAM板",
    }
    relationship_stage = {
        "TTM Technologies": "公司整体客户群披露；未公开具名客户与18层以上料号的对应关系",
        "沪电股份": "匿名客户共同开发、样品与认证；泰国另有2家认证、4家导入，但均未具名",
        "胜宏科技": "公司披露客户认可；没有客户侧交叉确认，也未把各客户与18层以上产品绑定",
        "ISU Petasys": "历史合作与供应商奖；时点较早，不能证明2026年AI高层板供货",
        "广合科技": "公司披露整体覆盖与历史奖项；没有逐家披露当前产品、直接/间接关系和份额",
    }
    for assessment in assessments:
        company = str(assessment["company"])
        company_facts = [fact for fact in facts if str(fact.get("company")) == company]
        capability = next((fact for fact in company_facts if fact.get("claim_axis") == "capability"), company_facts[0])
        capability_ref = _ref("SUP", str(capability["fact_id"]))
        expansion_facts = [
            fact for fact in company_facts
            if fact.get("claim_axis") in {"expansion", "ramp", "capacity_current"}
        ]
        expansion_refs = [_ref("SUP", str(fact["fact_id"])) for fact in expansion_facts]
        refs.extend([capability_ref, *expansion_refs])
        evidence_text = re.sub(
            r"^(?:很强|中强|强能力证据|强|暂不充分)：\s*", "", str(assessment["ge18_evidence"])
        )
        rows.append(
            [
                company,
                evidence_text,
                assessment["supply_status"],
                supply_conclusions[company],
                _cite(capability_ref, *expansion_refs),
            ]
        )
        customer_fact = next((fact for fact in company_facts if fact.get("claim_axis") == "customer_relation"), None)
        if customer_fact:
            customer_ref = _ref("SUP", str(customer_fact["fact_id"]))
            refs.append(customer_ref)
            customer_evidence = str(customer_fact.get("claim") or customer_fact.get("claim_zh"))
            date_text = str(customer_fact.get("publication_date") or customer_fact.get("publish_date") or AS_OF_DATE)
            relation_text = relationship_stage[company]
            source_refs = [customer_ref, capability_ref]
        else:
            customer_evidence = "本轮公开检索没有找到可把具名客户与18层以上产品绑定的直接证据。"
            date_text = f"检索截至{AS_OF_DATE}"
            relation_text = "公开资料只支持应用方向或制造能力；无法判断直接客户、间接渠道和认证阶段"
            source_refs = [capability_ref]
        share_text = (
            "没有公开客户采购份额。受托研究估计沪电2025年占全球22层以上全应用市场14.9%，这不是AI客户份额。"
            if company == "沪电股份"
            else "没有公开客户采购份额，也未进行模型估计。"
        )
        if company == "沪电股份":
            source_refs.append("AB-WUS-SHARE")
        customer_rows.append(
            [
                company,
                customer_evidence,
                customer_product[company],
                relation_text,
                share_text,
                date_text,
                _cite(*source_refs),
            ]
        )
    return rows, customer_rows, list(dict.fromkeys(refs))


def _financial_visual_rows() -> tuple[list[list[Any]], list[str]]:
    financial = _read_json(FINANCIAL_PATH)
    market = _read_json(MARKET_PATH)
    rows: list[list[Any]] = []
    refs: list[str] = []
    for company_key in TARGET_SPECS:
        company = financial["companies"][company_key]
        snapshot = market["companies"][company_key]
        year = next((row for row in company["periods"] if str(row["period"]) == "2025"), company["periods"][-1])
        fin_ref = f"FIN-{company_key.upper()}-SERIES"
        mkt_ref = f"MKT-{company_key.upper()}-20260711"
        refs.extend((fin_ref, mkt_ref))
        if snapshot.get("pe_ttm") is not None and snapshot["pe_ttm"] > 0:
            pe = f"{snapshot['pe_ttm']:.2f}倍"
        elif float(year["net_income"]["cny_yi"]) > 0:
            pe = "未取得"
        else:
            pe = "因亏损不适用"
        pb = f"{snapshot['pb']:.2f}倍" if snapshot.get("pb") is not None else "未取得"
        ps = f"{snapshot['ps_ttm']:.2f}倍" if snapshot.get("ps_ttm") is not None else "未取得"
        rows.append(
            [
                company["name"],
                f"{year['revenue']['cny_yi']:.2f}亿元人民币（约{year['revenue']['usd_yi']:.2f}亿美元）",
                f"毛利率{year.get('gross_margin'):.2f}%；净利率{year.get('net_margin'):.2f}%",
                f"经营现金流{year['operating_cash_flow']['cny_yi']:.2f}亿元；资本开支{year['capex']['cny_yi']:.2f}亿元",
                f"PE {pe}；PB {pb}；PS {ps}",
                _cite(fin_ref, mkt_ref),
            ]
        )
    return rows, refs


def _visuals(outputs: Mapping[str, Any], metadata: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    scenarios = outputs["scenarios"]
    base = scenarios["base"]["rows"]
    conditional_paths = outputs["conditional_supply_paths"]
    supply_path_order = ("slow", "threshold", "fast")
    scenario_panel = line_chart_panel(
        title="严格口径AI高多层板需求",
        unit="十亿美元",
        series=[
            {
                "label": scenarios[key]["label"],
                "observations": [{"period": str(row["year"]), "value": row["bottom_up_demand_usd_bn"]} for row in scenarios[key]["rows"]],
            }
            for key in ("conservative", "base", "optimistic")
        ],
    )
    balance_panel = line_chart_panel(
        title="基准需求与条件有效供给面积",
        unit="百万平方米",
        series=[
            {"label": "基准需求面积", "observations": [{"period": str(row["year"]), "value": row["strict_demand_area_million_m2"]} for row in base]},
            *[
                {
                    "label": conditional_paths[key]["label"],
                    "observations": [
                        {"period": str(row["year"]), "value": row["conditional_supply_area_million_m2"]}
                        for row in conditional_paths[key]["rows"]
                    ],
                }
                for key in supply_path_order
            ],
        ],
    )
    supplier_rows, customer_rows, supplier_refs = _supplier_rows(metadata)
    oem_rows, oem_refs = _oem_rows()
    financial_rows, financial_refs = _financial_visual_rows()
    role_rows = [
        ["GPU/加速器供应商", "芯片、加速卡、OAM或GPU基板数量", "OCP/HGX每节点加速器数、NVL72每托盘4颗", "跨代际实际出货与板级绑定通常未公开", "只校验节点内部配置，不与服务器节点相加", _cite("DMD-AR006", "DMD-AR007", "DMD-AR008", "DMD-AR011")],
        ["云厂商与自研ASIC使用方", "自建部署、芯片数量、资本开支与最大集群", "Trainium部署、TPU拓扑、资本开支和算力容量", "资本开支包含建筑、电力和网络；芯片数不等于节点数", "用于判断部署方向，不与OEM/ODM交付相加", _cite("DMD-DF008", "DMD-DF010", "DMD-DF011", "DMD-AR012")],
        ["OEM/ODM与系统集成商", "服务器节点或整机交付", "统一到服务器节点，作为需求模型主计数单位", "公司级2026—2030 AI节点拆分公开不足", "同一设备无论经过多少品牌和渠道只计一次", _cite("DMD-DF005")],
        ["机柜、SuperPod与集群", "托盘、机柜、芯片和最大拓扑", "NVL72可由18个计算托盘换算机柜；其他平台逐项处理", "公开数字多是最大配置，不是年度出货或实际利用量", "只校验拓扑；集群不能再加回节点总量", _cite("DMD-AR008", "DMD-AR012", "DMD-AR015")],
    ]
    bom_rows = [
        ["PCIe GPU服务器", "主板、GPU卡、PCIe交换板；公开资料未给统一块数", "行业资料称GPU板可达20层以上；各型号须逐板核验", "没有统一公开尺寸和材料表", "模型只计达到18层的部分，2026—2030取0.08→0.10平方米/节点", "块数、尺寸、拼板利用率和型号占比", _cite("DMD-PB003")],
        ["OCP 8-OAM/UBB", "1块UBB + 8块OAM；另有交换与控制板", "相关服务器UBB/IO产品公开为28—46层，不能外推所有OCP平台", "UBB 417×585毫米；OAM 102×165毫米；材料未统一公开", "公开毛面积0.378585平方米，严格模型因层数筛选取0.28→0.36平方米/节点", "各OAM、交换板是否达到18层及量产良率", _cite("DMD-AR001", "DMD-AR002", "DMD-AR003", "DMD-PB004", "DMD-PB005")],
        ["NVIDIA HGX H100/B200/B300", "每GPU基板8颗GPU；H100为4颗NVSwitch，B200/B300为2颗", "公开资料没有给出完整主板、交换板层数", "未公开可生产板尺寸和材料组合", "作为8加速器架构校验，不另加一套需求", "各代GPU基板、主板和交换板的块数、层数与面积", _cite("DMD-AR006", "DMD-AR007")],
        ["GB200/GB300/NVL72及后续机架级GPU", "1机架含18个计算托盘、9个交换托盘；每计算托盘1—2块计算板", "Rubin层数来自第三方预测且含HDI，不能当作全部严格刚性板规格", "官方未公开PCB尺寸；M8/M9只作材料方向", "按计算托盘作为节点，模型取0.46→0.62平方米/节点；交换板不重复相加", "计算板、交换板、中板和背板逐板层数、面积、材料与备品率", _cite("DMD-AR008", "DMD-AR009", "DMD-AR010", "DMD-PB008", "DMD-PB009")],
        ["Google TPU v5p / Ironwood", "TPU v5p每主机4颗，64芯片机柜对应16台主机；最大Pod/切片不是出货量", "官方未公开系统板层数", "官方未公开板面积和材料", "并入定制ASIC节点0.22→0.30平方米的研究区间，不用最大Pod直接换算", "实际主机数、板卡BOM、层数、部署量与供应商", _cite("DMD-AR012", "DMD-AR013")],
        ["AWS Trainium2/3", "Trn2 UltraServer含64颗Trainium2；公开资料未给完整主机与板数", "官方未公开板层数", "官方未公开板面积和材料", "并入定制ASIC节点研究区间；140万颗部署数只作方向校验", "芯片到节点的稳定换算、板卡BOM和2026—2030实际部署", _cite("DMD-AR014", "DMD-DF008", "DMD-DR005")],
        ["华为昇腾Atlas 900 A3", "最大系统含12个计算柜、4个总线柜、384颗NPU和192颗CPU", "官方未公开逐板层数", "官方未公开板面积和材料", "并入国产ASIC/NPU研究区间，不把SuperPod、机柜和芯片重复相加", "不同配置的服务器节点、板卡BOM、层数与供应商", _cite("DMD-AR015", "DMD-AR016")],
        ["其他国产GPU/ASIC系统", "本轮没有取得可跨厂商统一的公开板级拓扑", "公开资料不足以判断", "公开资料不足以判断", "只在整体国产系统中保留小比例研究区间，不生成公司级精确出货", "主要整机商逐平台节点定义、板卡BOM、层数和部署量", _cite("MODEL-PCB-INPUTS")],
    ]
    annual_node_rows: list[list[Any]] = []
    regional_rows: list[list[Any]] = []
    for index, row in enumerate(base):
        architecture = outputs["yearly_architecture"][str(row["year"])]
        mix = architecture["mix"]
        gpu_nodes = row["ai_server_units_million"] * (mix["pcie_gpu"] + mix["oam_ubb"] + mix["rack_scale_gpu"])
        asic_nodes = row["ai_server_units_million"] * (mix["custom_asic"] + mix["other_domestic"])
        oam_modules = row["ai_server_units_million"] * mix["oam_ubb"] * 8
        nvl72_racks_ten_thousand = row["ai_server_units_million"] * mix["rack_scale_gpu"] / 18 * 100
        annual_node_rows.append([
            row["year"],
            f"{scenarios['conservative']['rows'][index]['ai_server_units_million']:.2f} / {row['ai_server_units_million']:.2f} / {scenarios['optimistic']['rows'][index]['ai_server_units_million']:.2f}",
            f"{gpu_nodes:.2f} / {asic_nodes:.2f}",
            f"{oam_modules:.2f}百万个",
            f"{nvl72_racks_ten_thousand:.2f}万套",
            _cite("MODEL-PCB-INPUTS", "MODEL-PCB-OUTPUTS", "DMD-AR001", "DMD-AR008"),
        ])
        low = scenarios["conservative"]["rows"][index]
        high = scenarios["optimistic"]["rows"][index]
        regional_rows.append([
            row["year"],
            f"{low['bottom_up_demand_usd_bn']:.2f} / {row['bottom_up_demand_usd_bn']:.2f} / {high['bottom_up_demand_usd_bn']:.2f}",
            f"{low['china_end_demand_usd_bn']:.2f} / {row['china_end_demand_usd_bn']:.2f} / {high['china_end_demand_usd_bn']:.2f}",
            f"{low['overseas_end_demand_usd_bn']:.2f} / {row['overseas_end_demand_usd_bn']:.2f} / {high['overseas_end_demand_usd_bn']:.2f}",
            f"{low['china_end_demand_share_assumption']:.0%} / {row['china_end_demand_share_assumption']:.0%} / {high['china_end_demand_share_assumption']:.0%}",
            _cite("MODEL-PCB-INPUTS", "MODEL-PCB-OUTPUTS"),
        ])

    architecture_labels = {
        "pcie_gpu": "PCIe GPU服务器",
        "oam_ubb": "8-OAM/UBB节点",
        "rack_scale_gpu": "机架级GPU计算节点",
        "custom_asic": "云厂定制ASIC节点",
        "other_domestic": "其他国产GPU/ASIC节点",
    }
    architecture_demand_rows: list[list[Any]] = []
    for key, label in architecture_labels.items():
        values: dict[int, dict[str, float]] = {}
        for row in (base[0], base[-1]):
            architecture = outputs["yearly_architecture"][str(row["year"])]
            nodes = row["ai_server_units_million"] * architecture["mix"][key]
            area = nodes * architecture["strict_area_m2_per_server"][key]
            value = area * row["blended_asp_usd_per_m2"] / 1000
            values[int(row["year"])] = {"nodes": nodes, "area": area, "value": value}
        architecture_demand_rows.append([
            label,
            f"{values[2026]['nodes']:.3f} → {values[2030]['nodes']:.3f}",
            f"{values[2026]['area']:.3f} → {values[2030]['area']:.3f}",
            f"{values[2026]['value']:.2f} → {values[2030]['value']:.2f}",
            f"{values[2030]['value'] / base[-1]['bottom_up_demand_usd_bn']:.1%}",
            _cite("MODEL-PCB-INPUTS", "MODEL-PCB-OUTPUTS"),
        ])

    market_scope_rows = [
        ["本研究自下而上需求", "18层以上刚性板 ∩ AI服务器；排除纯HDI、载板、FPC", f"2026年{base[0]['bottom_up_demand_usd_bn']:.2f}", f"2030年{base[-1]['bottom_up_demand_usd_bn']:.2f}", "作为需求主结果；由节点、架构面积和单价计算", _cite("MODEL-PCB-INPUTS", "MODEL-PCB-OUTPUTS")],
        ["CIC/Prismark受托研究", "22层以上多层板，覆盖全部下游；与18层以上AI服务器不是包含关系", "2026年8.00", "2030年13.10", "只说明公开市场口径不匹配；不作为AI需求上限、供给分母或份额分母", _cite("AB-WUS-22PLUS-MARKET")],
    ]
    profit_evidence_rows = [
        ["沪电32层以上产品", "销售面积：2025Q1 1.0644万㎡ → 2026Q1 3.0233万㎡", "单价：6.09万元/㎡ → 6.59万元/㎡", "未披露该层数毛利率", "面积与单价同步上升是批量验证；不能外推全行业价格", _cite("AB-WUS-AREA-32PLUS", "AB-WUS-ASP-32PLUS")],
        ["深南PCB业务", "2025年收入143.59亿元，同比增长36.84%", "毛利率35.53%", "公司称AI服务器相关订单显著增加，但未拆分18层以上面积和单价", "经营改善与AI订单方向一致；不能反推出单品价格或行业毛利弹性", _cite("SUP-SUP-SCC-003")],
        ["广合公司整体", "2025年收入54.85亿元，同比增长46.89%", "净利润10.16亿元，同比增长50.24%", "公司整体口径，含不同层数和应用", "利润增长快于收入是经营验证；不能全部归因于18层以上AI板", _cite("SUP-SUP-DELTON-003")],
    ]
    return [
        build_line_visual(
            block_key="demand_scenarios_2026_2030",
            title="2026—2030年AI高多层板需求情景",
            subtitle="节点数×架构加权有效面积×单价；三条线分别是需求下限、基准和输入同时偏高的压力测试，不与22层以上全应用市场相除。",
            how_to_read="纵轴是严格18层以上刚性板产值需求，不含纯HDI、载板和FPC；三条线不是概率区间。",
            analysis=f"基准需求由{base[0]['bottom_up_demand_usd_bn'] * 10:.1f}亿美元增至{base[-1]['bottom_up_demand_usd_bn'] * 10:.1f}亿美元；结构升级使产值增长快于节点数。",
            panels=[scenario_panel],
            print_columns=["年份", "需求较慢", "基准", "需求较快", "单位"],
            print_rows=[[row["year"], scenarios["conservative"]["rows"][i]["bottom_up_demand_usd_bn"], row["bottom_up_demand_usd_bn"], scenarios["optimistic"]["rows"][i]["bottom_up_demand_usd_bn"], "十亿美元"] for i, row in enumerate(base)],
            source_refs=["MODEL-PCB-OUTPUTS", "DMD-DF004"],
            sort_order=100,
        ),
        build_line_visual(
            block_key="base_supply_demand_2026_2030",
            title="若2026年平衡：有效供给需要多快增长",
            subtitle="三条供给线均以2026年基准需求面积为条件起点，只回答增长门槛，不代表实际行业产能。",
            how_to_read="纵轴是百万平方米；基准需求与20%、32%、45%三种条件供给面积可比较，CIC的22层以上市场不进入计算。",
            analysis="基准需求面积四年年均增长约32%；供给年增20%会落后，32%大致追平，45%形成余量。",
            panels=[balance_panel],
            print_columns=["年份", "基准需求面积", "供给年增20%", "供给年增32%", "供给年增45%", "单位"],
            print_rows=[
                [
                    row["year"],
                    row["strict_demand_area_million_m2"],
                    conditional_paths["slow"]["rows"][i]["conditional_supply_area_million_m2"],
                    conditional_paths["threshold"]["rows"][i]["conditional_supply_area_million_m2"],
                    conditional_paths["fast"]["rows"][i]["conditional_supply_area_million_m2"],
                    "百万平方米",
                ]
                for i, row in enumerate(base)
            ],
            source_refs=["MODEL-PCB-OUTPUTS"],
            sort_order=110,
        ),
        _table_visual(key="annual_node_and_topology_bridge", title="2026—2030年AI服务器节点与可核验拓扑换算", subtitle="服务器节点给出需求较慢/基准/需求较快三种情景；只对有官方拓扑的8-OAM和NVL72做换算，不伪造全行业加速器或集群出货。", columns=["年份", "AI服务器节点：慢 / 基准 / 快（百万台）", "基准GPU路线 / ASIC-NPU（百万节点）", "8-OAM模块代理", "NVL72机架等价", "来源"], rows=annual_node_rows, refs=["MODEL-PCB-INPUTS", "MODEL-PCB-OUTPUTS", "DMD-AR001", "DMD-AR008"], sort_order=200),
        _table_visual(key="counting_roles", title="GPU、ASIC、云厂部署与整机交付怎样避免重复", subtitle="同一套设备在芯片、云厂、整机商和机柜层会出现多个数字；本表明确可用代理、不可得项和唯一计数规则。", columns=["角色", "公开数字通常是什么", "可复核代理", "目前缺少什么", "防重复规则", "来源"], rows=role_rows, refs=["DMD-AR006", "DMD-AR011", "DMD-DF008", "DMD-DF010", "DMD-DF011", "DMD-DF005", "DMD-AR008", "DMD-AR012", "DMD-AR015"], sort_order=210),
        _table_visual(key="oem_product_and_deployment_evidence", title="十家整机商的公开数字能否计入服务器节点", subtitle="优先使用2025—2026年官方或受监管披露；产品满配、系统扩展能力、混合产能和实际部署分别处理，不把同一设备在供应方与云厂口径重复相加。", columns=["整机商或集成商", "官方产品或部署证据", "公开数字的性质", "怎样用于需求测算", "来源"], rows=oem_rows, refs=oem_refs, sort_order=215),
        _table_visual(key="architecture_bom_matrix", title="主要AI服务器架构的高多层板BOM边界", subtitle="公开块数、层数、尺寸与模型计入规则分别列出；专有BOM没有直接证据时明确保留缺口。", columns=["架构", "公开拓扑或板卡数量", "层数证据", "尺寸与材料证据", "模型如何计入", "仍需补充", "来源"], rows=bom_rows, refs=["DMD-PB003", "DMD-AR001", "DMD-AR002", "DMD-AR003", "DMD-AR006", "DMD-AR007", "DMD-AR008", "DMD-AR009", "DMD-AR010", "DMD-AR012", "DMD-AR014", "DMD-AR015"], sort_order=220),
        _table_visual(key="architecture_demand_split", title="不同架构贡献多少高多层板需求", subtitle="同一基准情景下，把节点、严格面积和产值按五类互斥架构拆分；交换板已包含在相应节点中，不另加。这是模型拆分，不是公司订单。", columns=["架构", "节点：2026 → 2030（百万台）", "严格面积：2026 → 2030（百万㎡）", "产值：2026 → 2030（十亿美元）", "2030需求占比", "来源"], rows=architecture_demand_rows, refs=["MODEL-PCB-INPUTS", "MODEL-PCB-OUTPUTS"], sort_order=230),
        _table_visual(key="bottom_up_top_down_scope", title="自下而上结果与公开市场数据为什么不能直接相除", subtitle="两组数字的产品集合不同；保留口径冲突比强行拼接出一个错误的供需缺口更可复核。", columns=["数据", "产品与下游范围", "起点（十亿美元）", "终点（十亿美元）", "在本研究中的用途", "来源"], rows=market_scope_rows, refs=["MODEL-PCB-INPUTS", "MODEL-PCB-OUTPUTS", "AB-WUS-22PLUS-MARKET"], sort_order=240),
        _table_visual(key="regional_demand_scenarios", title="2026—2030年全球、中国与海外需求情景", subtitle="每格依次为需求较慢 / 基准 / 需求较快；地域按最终部署地研究区间，不等于PCB生产地或供应商注册地。", columns=["年份", "全球需求（十亿美元）", "中国最终需求（十亿美元）", "海外最终需求（十亿美元）", "中国占比假设", "来源"], rows=regional_rows, refs=["MODEL-PCB-INPUTS", "MODEL-PCB-OUTPUTS"], sort_order=300),
        _table_visual(key="supplier_effective_supply", title="十家厂商的18层以上能力、扩产与有效供给边界", subtitle="只写可以核验的量产、项目和爬坡节点；总产能、厂房和投资额不改名为AI有效供给。", columns=["厂商", "已确认的18层以上证据", "现状与扩产进度", "可量化供给与结论", "来源"], rows=supplier_rows, refs=supplier_refs, sort_order=400),
        _table_visual(key="customer_validation_and_share", title="厂商—客户关系与份额证据矩阵", subtitle="当前只有五家公司披露客户关系线索，且没有客户侧第二来源；14.9%是沪电在22层以上全应用市场的受托研究份额，不是AI客户份额。", columns=["厂商", "公开客户证据", "产品或应用", "关系与进展", "客户份额结论", "证据日期", "来源"], rows=customer_rows, refs=[*supplier_refs, "AB-WUS-SHARE"], sort_order=410),
        _table_visual(key="price_profit_evidence", title="价格与利润弹性目前有哪些经营证据", subtitle="优先展示公司实际面积、单价和经营变化；三组口径不同，不能拼成行业平均弹性。", columns=["观察对象", "数量或收入", "单价或毛利", "成本与范围边界", "可以得出的结论", "来源"], rows=profit_evidence_rows, refs=["AB-WUS-AREA-32PLUS", "AB-WUS-ASP-32PLUS", "SUP-SUP-SCC-003", "SUP-SUP-DELTON-003"], sort_order=420),
        _table_visual(key="target_financial_snapshot", title="十家上市公司的2025年经营与2026年7月估值快照", subtitle="估值取截至7月11日可得的最近交易日；非人民币历史财务按7月11日汇率统一折算。财务不能单独证明AI高多层板收入或客户份额。", columns=["公司", "2025收入", "盈利", "现金流与资本开支", "估值快照", "来源"], rows=financial_rows, refs=financial_refs, sort_order=500),
    ]


def _claims(metadata: Sequence[Mapping[str, Any]], sources_by_ref: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    preferred: list[Mapping[str, Any]] = []
    groups: set[str] = set()
    for row in sorted(
        metadata,
        key=lambda item: (
            0 if item["source"]["source_tier"] in {"S", "A"} else 1,
            item["source"]["ref"],
        ),
    ):
        source = row["source"]
        if source["source_tier"] == "C" or source["source_review_status"] == "reject":
            continue
        group = str(source["independence_key"])
        if group in groups:
            continue
        preferred.append(row)
        groups.add(group)
        if len(preferred) >= 45:
            break
    claims = []
    for row in preferred:
        source = row["source"]
        fact = row["fact"]
        claim_text = str(fact.get("metric_or_claim") or fact.get("claim") or fact.get("claim_zh") or source["excerpt_zh"])
        claims.append(
            {
                "source_ref": source["ref"],
                "claim_text": claim_text,
                "source_excerpt": source["excerpt"],
                **({"source_excerpt_zh": source["excerpt_zh"]} if source["language"] != "zh-CN" else {}),
                "claim_type": str(fact.get("fact_type") or fact.get("claim_type") or "fact"),
                "note": str(fact.get("inference_boundary") or fact.get("boundary") or "只在来源披露的产品、时期和公司范围内使用。"),
            }
        )
    for ref in ("AB-WUS-22PLUS-MARKET", "AB-WUS-AREA-32PLUS", "AB-WUS-ASP-32PLUS", "AB-WUS-CR5", "AB-WUS-SHARE"):
        source = sources_by_ref[ref]
        claims.append(
            {
                "source_ref": ref,
                "claim_text": source["title_zh"],
                "source_excerpt": source["excerpt"],
                **({"source_excerpt_zh": source["excerpt_zh"]} if source["language"] != "zh-CN" else {}),
                "claim_type": "industry_forecast" if "MARKET" in ref else "observed_fact",
                "note": "委聘行业预测与公司经营事实分开使用；匿名竞争者不作具名映射。",
                **({"policy_evidence_role": source["policy_evidence_role"]} if source.get("policy_evidence_role") else {}),
            }
        )
    return claims


def build_pack(*, output_dir: Path) -> dict[str, Any]:
    inputs = _read_json(MODEL_INPUT_PATH)
    outputs = calculate(inputs)
    write_json(MODEL_OUTPUT_PATH, outputs)

    agent_sources, agent_points, metadata = _load_agent_materials()
    ab_sources, ab_points, ab_metadata = _ab_wus_materials()
    metadata = [*metadata, *ab_metadata]
    model_sources, model_points = _model_sources_and_points(outputs)
    financial_sources, targets = _financial_sources_and_targets()
    sources = [*agent_sources, *ab_sources, *model_sources, *financial_sources]
    _normalize_source_provenance(sources)
    sources_by_ref = {source["ref"]: source for source in sources}
    if len(sources_by_ref) != len(sources):
        raise ValueError("来源标识重复")
    points = [*agent_points, *ab_points, *model_points]
    entities = _entities(metadata, sources_by_ref)
    entity_sections = _entity_sections(metadata, outputs)
    sections = _main_sections(outputs, metadata, inputs)
    visuals = _visuals(outputs, metadata)

    builder = RunPackBuilder(
        slug=SLUG,
        display_title=DISPLAY_TITLE,
        research_question=_extract_question(),
        requested_by="codex_opportunity_lens_research_workflow_v2",
        run_mode="c_hybrid",
        quality_profile="deep_research",
        problem_statement="2026—2030年AI服务器会消耗多少18层以上刚性高多层PCB，完成客户认证的有效供给能否跟上，哪些厂商真正具备可验证的量产与盈利弹性？",
        intake={
            "research_question": _extract_question(),
            "available_materials_choice": "B",
            "intake_material_type": "papers_folder",
            "materials_delivery_note": "本地研报只用于线索和历史校准；核心证据优先采用2025—2026年公司、监管、官方架构、行业协会与公开技术资料。",
            "evidence_policy": "balanced",
            "time_window": {"core": "2026—2030", "monitoring": "未来12个月事件驱动", "history": "2023—2025用于校准"},
            "research_scope": {
                "geography": "全球；中国大陆、中国台湾、美国、日本、韩国、欧洲和东南亚分别核验",
                "product": "18层及以上刚性高多层PCB；局部HDI复合板仅在扩展口径单列",
                "exclusion": "18层以下普通板、纯HDI、IC/ABF载板、FPC和未经证实的客户份额",
            },
            "special_constraints": {
                "counting": "芯片、服务器节点、机柜、集群、云厂部署和OEM交付不重复相加",
                "supply": "公司总产能、厂房面积、投资额和最高技术层数不折算为有效供给",
                "customer": "没有直接强证据时不输出具名客户精确份额",
            },
            "field_origin": {"research_question": "user_provided", "scope": "user_provided", "model": "user_required_and_researcher_refined"},
            "default_accepted": {},
        },
    )
    builder.sources = sources
    builder.evidence_groups = {source["ref"]: source["independence_key"] for source in sources}
    builder.data_points = points
    builder.claims = _claims(metadata, sources_by_ref)
    builder.entities = entities
    builder.entity_sections = entity_sections
    builder.entity_investment_targets = targets
    builder.sections = sections
    builder.visuals = visuals
    builder.search_plan = [
        {"axis_key": "demand_and_counting", "query_text": "AI服务器、GPU/ASIC、云厂部署、OEM交付和机柜拓扑；防止重复计数", "languages": ["zh", "en"], "status": "completed"},
        {"axis_key": "architecture_bom", "query_text": "OCP UBB/OAM、HGX、NVL、TPU、Trainium、昇腾的板型、尺寸、层数和材料", "languages": ["zh", "en"], "status": "completed"},
        {"axis_key": "oem_official_products_and_deployment", "query_text": "华为、浪潮、新华三、超聚变、中兴、曙光、联想、宁畅、华鲲、神州鲲泰的官方产品配置与实际部署", "languages": ["zh", "en"], "status": "completed"},
        {"axis_key": "supplier_capacity_customer", "query_text": "十家PCB厂商的18层以上量产、扩产、良率、认证、客户关系和份额", "languages": ["zh", "en", "ja", "ko"], "status": "completed"},
        {"axis_key": "market_price_counterevidence", "query_text": "18/22/32层市场、单价、毛利、交期、材料扩产、CPO和资本开支反方", "languages": ["zh", "en", "ja"], "status": "completed"},
    ]
    builder.supplement_requests = [
        {
            "entity_key": "rack_scale_gpu_boards",
            "request_title": "补充专有机架平台的可生产板级BOM",
            "request_detail": "取得GB300/Rubin计算板、交换板、中板和背板的块数、成品面积、层数、材料、拼板利用率、良率和备品率。",
            "priority": "p1",
            "blocking_status": "limits_scoring",
            "review_status": "pending",
            "evidence_ref_uri": source_uri("DMD-AR008"),
        },
        {
            "entity_key": "custom_asic_system_boards",
            "request_title": "补充ASIC与国产算力平台的板级映射",
            "request_detail": "取得TPU、Trainium、昇腾和国产GPU系统的节点定义、板卡层数、面积及供应商认证证据，避免用芯片数外推服务器和PCB。",
            "priority": "p1",
            "blocking_status": "limits_scoring",
            "review_status": "pending",
            "evidence_ref_uri": source_uri("DMD-AR012"),
        },
        {
            "entity_key": "datacenter_switch_boards",
            "request_title": "补充分供应商的高端有效供给和客户份额",
            "request_detail": "取得18—30层、32层以上季度面积、单价、利用率、良率、认证后出货和具名客户料号；没有强证据前不估算精确份额。",
            "priority": "p1",
            "blocking_status": "limits_scoring",
            "review_status": "pending",
            "evidence_ref_uri": source_uri("AB-WUS-AREA-32PLUS"),
        },
    ]
    builder.audit_issues = []
    builder.review_records = []
    pack = builder.build(publication_mode="stage")
    pack["as_of_date"] = AS_OF_DATE
    pack["model_artifacts"] = {
        "model_inputs_sha256": sha256_file(MODEL_INPUT_PATH),
        "model_outputs_sha256": sha256_file(MODEL_OUTPUT_PATH),
        "model_code_sha256": sha256_file(ROOT / "tools" / "opportunity_lens" / "high_multilayer_pcb_models.py"),
        "builder_sha256": sha256_file(Path(__file__)),
        "demand_ledger_sha256": sha256_file(LEDGER_SPECS[0][1]),
        "supply_ledger_sha256": sha256_file(LEDGER_SPECS[1][1]),
        "market_research_ledger_sha256": sha256_file(MARKET_RESEARCH_LEDGER_PATH),
        "market_research_ledger_usage": "仅作为检索底稿；其中非逐字归纳未装入公开研究包、核心因子或证据抽屉",
        "oem_ledger_sha256": sha256_file(LEDGER_SPECS[2][1]),
        "financial_cache_sha256": sha256_file(FINANCIAL_PATH),
        "market_cache_sha256": sha256_file(MARKET_PATH),
        "method": outputs["method_note"],
    }
    pack["counting_audit"] = {
        "primary_unit": "AI服务器节点/整机",
        "not_additive": ["GPU/ASIC芯片或卡", "云厂自用部署", "OEM/ODM交付", "机柜/集群/SuperPod"],
        "strict_product_scope": inputs["scope"]["included"],
        "excluded": inputs["scope"]["excluded"],
        "market_reference_comparability": "CIC 22层以上全应用市场与18层以上AI需求集合互不包含，不参与份额、供给、缺口或价格计算",
        "base_required_effective_supply_area_cagr": outputs["cross_check"]["base_required_effective_supply_area_cagr_2026_2030"],
        "conditional_supply_anchor_is_observed": False,
        "request_output_audit": [
            {"item": 1, "request": "口径与防重复计算说明", "status": "completed", "artifact": "scope_and_counting / counting_roles"},
            {"item": 2, "request": "加速器、服务器节点、机柜与集群总表", "status": "completed_with_public_data_limit", "artifact": "annual_node_and_topology_bridge / oem_product_and_deployment_evidence", "limit": "只有8-OAM和NVL72具备可统一换算的公开拓扑；其余不伪造年度出货"},
            {"item": 3, "request": "GPU、ASIC、云厂自建与OEM/ODM口径对照", "status": "completed", "artifact": "counting_roles / oem_product_and_deployment_evidence"},
            {"item": 4, "request": "主要架构BOM、板数、层数与面积矩阵", "status": "completed_with_public_data_limit", "artifact": "architecture_bom_matrix", "limit": "专有平台未公开完整可生产BOM"},
            {"item": 5, "request": "自下而上与自上而下需求测算", "status": "completed_with_objective_gap", "artifact": "bottom_up_top_down_scope", "limit": "公开的18层以上和22层以上总市场与18层以上AI需求集合不可比，未强行拼接"},
            {"item": 6, "request": "全球、中国与海外逐年需求", "status": "completed", "artifact": "regional_demand_scenarios"},
            {"item": 7, "request": "厂商产能、扩产、有效供给和爬坡风险", "status": "completed_with_objective_gap", "artifact": "supplier_effective_supply", "limit": "多数公司未披露按18层以上、AI应用、认证良率拆分的面积"},
            {"item": 8, "request": "厂商与AI客户供应关系矩阵", "status": "completed_with_public_data_limit", "artifact": "customer_validation_and_share", "limit": "仅五家公司有发行人侧关系线索，未取得客户侧第二来源"},
            {"item": 9, "request": "供应份额分层", "status": "completed_with_objective_gap", "artifact": "customer_validation_and_share", "limit": "只有沪电22层以上全应用市场份额可引用；没有公司满足AI客户精确份额门槛"},
            {"item": 10, "request": "逐年供需平衡与三种情景", "status": "completed_as_conditional_threshold", "artifact": "base_supply_demand_2026_2030", "limit": "缺少同口径实际供给起点，因此输出追赶增速门槛而非伪精确缺口"},
            {"item": 11, "request": "正反证据、证伪条件与后续核验", "status": "completed", "artifact": "balance_price_profit / monitoring_and_limits"},
            {"item": 12, "request": "来源、证据等级、缺口和后续跟踪", "status": "completed", "artifact": "sources / supplement_requests / monitoring_and_limits"},
        ],
    }
    return pack


def write_bundle(*, output_dir: Path) -> Path:
    pack = build_pack(output_dir=output_dir)
    pack_path = write_pack_bundle(pack, output_dir=output_dir, audit_profile="generic")
    write_json(output_dir / "source_catalog.json", pack["sources"])
    write_json(
        output_dir / "artifact_hashes.json",
        {
            "run_pack_sha256": sha256_file(pack_path),
            "final_report_sha256": sha256_file(output_dir / "final_report.md"),
            **pack["model_artifacts"],
        },
    )
    return pack_path


def main() -> int:
    parser = argparse.ArgumentParser(description="构建AI服务器18层以上高多层PCB供需Opportunity Lens研究包")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    path = write_bundle(output_dir=args.output_dir)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
