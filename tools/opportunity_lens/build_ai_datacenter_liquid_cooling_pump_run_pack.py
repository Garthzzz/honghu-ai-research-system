from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "opportunity_lens" / "research_outputs" / "20260704_ai_datacenter_liquid_cooling_pump_deep_run"
INTAKE_PATH = ROOT / "opportunity_lens" / "intake_requests" / "Opportunity_Lens_任务_AI数据中心液冷泵行业研究与投资机会.md"
AS_OF_DATE = "2026-07-04"


def _compact(value: Any) -> str:
    text = str(value if value is not None else "").strip()
    text = re.sub(r"[\uf000-\uf8ff]", "", text)
    return re.sub(r"\s+", " ", text)


def _clip(text: str, limit: int = 520) -> str:
    text = _compact(text)
    return text if len(text) <= limit else text[: limit - 1] + "..."


def _clause(text: str, limit: int = 520) -> str:
    return _clip(text, limit).rstrip("。；;，, ")


def src(
    ref: str,
    title: str,
    publisher: str,
    publish_date: str | None,
    excerpt: str,
    *,
    url: str | None = None,
    local_path: str | None = None,
    tier: str = "A",
    language: str = "zh-CN",
    role: str = "core_evidence",
    cluster: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "ref": ref,
        "title": title,
        "publisher": publisher,
        "publish_date": publish_date,
        "url": url,
        "local_path": local_path,
        "source_tier": tier,
        "source_review_status": "pass_with_note",
        "language": language,
        "excerpt": _clip(excerpt, 760),
        "policy_evidence_role": role,
        "search_log_decision": "included",
        "screen_reason": reason or "纳入 AI 数据中心液冷泵 Opportunity Lens 人工核验证据包。",
        "cluster": cluster or publisher,
        "cluster_label": cluster or publisher,
        "independence_rationale": "按发布方、材料类型和证据链位置划分独立来源簇。",
        "cluster_confidence": 0.82 if tier in {"S", "A"} else 0.68,
    }


SOURCES: list[dict[str, Any]] = [
    src(
        "intake_ai_dc_pump",
        "Opportunity Lens intake：AI 数据中心液冷泵行业研究与投资机会",
        "用户研究任务",
        AS_OF_DATE,
        "任务要求研究 AI 数据中心液冷泵、CDU 泵、高功率泵的竞争格局、供需、价格体系、客户验证矩阵和未来 12 个月至 5 年投资机会，并严格区分汽车、储能、工业泵口径污染。",
        local_path="opportunity_lens/intake_requests/Opportunity_Lens_任务_AI数据中心液冷泵行业研究与投资机会.md",
        tier="S",
        cluster="research_intake",
    ),
    src(
        "xlsx_pump_company_universe",
        "图 26：全球主流液冷泵企业",
        "本地结构化表格",
        "2026-07-04",
        "表格列出 Wilo、格兰富、赛莱默、飞龙股份、南方泵业、德昌电机、大元泵业等主流液冷泵企业及核心产品，但其中部分客户或平台表述需要官方来源复核。",
        local_path="papers/数据中心液冷泵/图 26：全球主流液冷泵企业.xlsx",
        tier="A",
        cluster="local_structured_tables",
    ),
    src(
        "xlsx_vehicle_vs_server_pump",
        "图表15：车端泵 vs 服务器端液冷泵关键参数差距",
        "本地结构化表格",
        "2026-07-04",
        "车端热管理年均约 2000 小时、服务器端液冷 7x24 全年 8760 小时；服务器端液冷泵设计寿命 10-15 年不间断、泄漏接近零容忍、扬程 4Bar 以上、流量精度约 1%-2%。",
        local_path="papers/数据中心液冷泵/图表15： 车端泵 vs 服务器端液冷泵——关键参数差距.xlsx",
        tier="A",
        cluster="local_structured_tables",
    ),
    src(
        "xlsx_auto_transfer_barrier",
        "图表23：汽零公司往 AI 液冷泵的技术迁移难度对照",
        "本地结构化表格",
        "2026-07-04",
        "AI 液冷泵要求 22-37kW 功率、MTBF 5 万小时以上、部分华为场景 9-12 万小时、零泄漏、1%-2% 流量精度和 CDU 深度耦合；车端电子水泵能力可迁移但不能直接等同。",
        local_path="papers/数据中心液冷泵/图表23： 汽零公司往AI液冷泵的技术迁移难度对照.xlsx",
        tier="A",
        cluster="local_structured_tables",
    ),
    src(
        "xlsx_feilong_product_layout",
        "图表37：飞龙股份液冷泵产品布局",
        "本地结构化表格",
        "2026-07-04",
        "飞龙股份液冷泵分微泵、小泵、中型泵和大型泵平台；中型泵面向 Sidecar/InRack CDU，大型泵 HP22K、HP20H、37kW 面向 InRow CDU 和行级液冷，22kW/37kW 标为已量产。",
        local_path="papers/数据中心液冷泵/图表37： 飞龙股份液冷泵产品布局.xlsx",
        tier="A",
        cluster="local_structured_tables",
    ),
    src(
        "xlsx_global_cdu_pump_players",
        "表16：全球 CDU 液冷泵领域主要参与者介绍",
        "本地结构化表格",
        "2026-07-04",
        "表格列出格兰富、赛莱默、穆格、威乐等海外泵厂和飞龙股份等国内参与者，并把飞龙客户写为申菱环境、英维克、高澜等系统商，需要与公司公告和客户公开资料交叉验证。",
        local_path="papers/数据中心液冷泵/表16：全球CDU液冷泵领域主要参与者介绍.xlsx",
        tier="A",
        cluster="local_structured_tables",
    ),
    src(
        "local_west_cdu_pump_20260201",
        "数据中心散热专题报告1：CDU 液冷泵及冷源关键环节推荐",
        "西部证券",
        "2026-02-01",
        "报告把 CDU 液冷泵和一次侧冷源作为数据中心散热关键环节，并强调服务器液冷泵和车端水泵在连续运行、可靠性、扬程、流量精度和泄漏容忍度上有显著差异。",
        local_path="papers/数据中心液冷泵/2026-02-01_西部证券_机械设备_数据中心散热专题报告1：cdu液冷泵及冷源关键环节推荐.pdf",
        tier="A",
        cluster="broker_pump_reports",
    ),
    src(
        "local_zhongtai_liquid_20260528",
        "液冷专题报告系列1：AIDC 景气爆发，液冷大势所趋",
        "中泰证券",
        "2026-05-28",
        "报告测算 NVIDIA 机柜 2025-2027E 出货、GB200/GB300/Rubin 液冷价值量、CDU 价值量以及 Google TPU 液冷空间，并提示当前 CDU 多为 In-Row 架构，不能简单按一柜一 CDU 外推。",
        local_path="papers/数据中心液冷泵/2026-05-28_中泰证券_非银金融_液冷专题报告系列1：aidc景气爆发，液冷大势所趋.pdf",
        tier="A",
        cluster="broker_liquid_cooling_reports",
    ),
    src(
        "local_guangfa_liquid_20260530",
        "AI 珠峰系列十：液冷设备，从风到液的迁徙",
        "广发证券",
        "2026-05-30",
        "报告称 NVIDIA GB300 NVL72 已采用全液冷机架级架构，并把 CDU、manifold、连接器、冷板和液冷模组集成商拆为供应链层级；CDU 环节列出台达、Vertiv、BOYD 等参与者。",
        local_path="papers/数据中心液冷泵/2026-05-30_广发证券_机械设备_ai珠峰系列十：液冷设备：从风到液的迁徙，从0到1的散热革命.pdf",
        tier="A",
        cluster="broker_liquid_cooling_reports",
    ),
    src(
        "local_dongwu_liquid_20260626",
        "液冷行业深度报告：千亿液冷市场爆发，看好增量环节国产份额提升",
        "东吴证券",
        "2026-06-26",
        "报告把液冷系统拆成一次侧冷却塔、管路和冷却液，以及二次侧 CDU、液冷机柜、IT 设备和二次侧管路；同时列出 NVIDIA、Google TPU 和 Rubin 平台功耗、机柜和液冷状态。",
        local_path="papers/数据中心液冷泵/2026-06-26_东吴证券_基础化工_液冷行业深度报告：千亿液冷市场爆发，看好增量环节国产份额提升.pdf",
        tier="A",
        cluster="broker_liquid_cooling_reports",
    ),
    src(
        "local_zheshang_sanhua_20260703",
        "三花智控深度报告：全球热管理零部件龙头，AIDC 液冷打开空间",
        "浙商证券",
        "2026-07-03",
        "报告把三花智控定位为热管理零部件龙头，并讨论 AIDC 液冷、阀、泵、换热器和控制器等部件机会；公司具体客户和收入贡献仍需用公告、IR 和财报拆分验证。",
        local_path="papers/数据中心液冷泵/2026-07-03_浙商证券_三花智控_三花智控（002050）：深度报告：全球热管理零部件龙头，aidc液冷、仿生机器人打开空间.pdf",
        tier="A",
        cluster="broker_company_reports",
    ),
    src(
        "local_fangzheng_ai_hardware_20260529",
        "AI 算力硬件年中策略：竞争进入系统性时代",
        "方正证券",
        "2026-05-29",
        "报告提到南方泵业 CHL/CHM/CHLF 泵用于数据中心液冷模块，飞龙在芜湖、郑州有专线和多个液冷项目，利欧泵业也有液冷泵布局。",
        local_path="papers/数据中心液冷泵/2026-05-29_方正证券_投资策略_ai算力硬件年中策略：竞争进入“系统性”时代，产业链配套协同进化.pdf",
        tier="A",
        cluster="broker_ai_hardware_reports",
    ),
    src(
        "local_zhongyuan_home_20260618",
        "家电行业 2026 年中期策略：具身智能加算力液冷",
        "中原证券",
        "2026-06-18",
        "报告把三花、银轮、英维克、高澜、曙光、同飞、申菱等列为数据中心液冷相关公司，并提示部分企业进入 NVIDIA 或 Google 生态更多是生态或间接线索。",
        local_path="papers/数据中心液冷泵/2026-06-18_中原证券_投资策略_家电行业2026年中期投资策略：具身智能+算力液冷，家电的科技升维.pdf",
        tier="A",
        cluster="broker_company_reports",
    ),
    src(
        "local_changjiang_minutes_liquid",
        "看好液冷下半年主升浪机会 AI 纪要",
        "长江通信",
        "2026-07-04",
        "纪要提供下半年液冷催化、客户送样和国产链跟踪线索；因客户和份额口径来自交流纪要，只作为 early signal，不直接作为公开确认。",
        local_path="papers/数据中心液冷泵/【长江通信】看好液冷下半年主升浪机会-AI纪要.docx",
        tier="B",
        role="early_signal_candidate",
        cluster="expert_minutes",
    ),
    src(
        "local_dongwu_rubin_minutes",
        "Rubin 液冷情况讲解 AI 纪要",
        "东吴计算机",
        "2026-07-04",
        "纪要关注 Rubin 代际对液冷架构、系统商和组件的影响；客户名称和份额需要官方平台、ODM 或公司公告继续复核。",
        local_path="papers/数据中心液冷泵/东吴计算机 _ Rubin液冷情况讲解-AI纪要.docx",
        tier="B",
        role="early_signal_candidate",
        cluster="expert_minutes",
    ),
    src(
        "local_zheshang_feilong_minutes",
        "飞龙股份：液冷泵加人形机器人布局或将进入密集催化阶段 AI 纪要",
        "浙商大制造",
        "2026-07-04",
        "纪要跟踪飞龙股份液冷泵产品、项目阶段和潜在催化；由于属于专家或机构交流材料，客户验证和收入贡献必须回到公司公告、互动易、财报和客户资料复核。",
        local_path="papers/数据中心液冷泵/浙商大制造 _ 飞龙股份_ 液冷泵+人形机器人布局或将进入密集催化阶段-AI纪要.docx",
        tier="B",
        role="early_signal_candidate",
        cluster="expert_minutes",
    ),
    src(
        "local_mingsheng_liquid_20250123",
        "AI 液冷行业深度报告：液冷进入新纪元",
        "民生证券",
        "2025-01-23",
        "报告把冷板式液冷、CDU、冷板、manifold、快接头和一次侧设备拆成价值链环节，可作为 2025 年行业边界参考，但 2026 年投资结论仍要用新证据更新。",
        local_path="papers/液冷/14_20250123-民生证券-AI液冷行业深度报告：液冷进入新纪元.pdf",
        tier="A",
        cluster="broker_liquid_cooling_reports",
    ),
    src(
        "local_dongwu_liquid_20250126",
        "液冷行业深度报告：冷板式液冷放量在即，浸没式液冷可期",
        "东吴证券",
        "2025-01-26",
        "报告估计二次侧冷却系统占液冷系统较高价值比重，并列出 CDU、冷板、manifold、quick connector 等组件价值拆分和主要厂商。",
        local_path="papers/液冷/15_20250126-东吴证券-液冷行业深度报告：冷板式液冷放量在即，浸没式液冷可期.pdf",
        tier="A",
        cluster="broker_liquid_cooling_reports",
    ),
    src(
        "local_huibao_liquid_20250725",
        "液冷行业深度：驱动因素、市场空间、产业链及相关公司深度梳理",
        "慧博智能投研",
        "2025-07-25",
        "报告记录 A100、H100、GB200 等芯片 TDP 和 AI 机柜功率密度上行，并引用 Vertiv/NVIDIA 测试说明冷板液冷承担主要 IT 热负荷。",
        local_path="papers/液冷/17_20250725-慧博智能投研-液冷行业深度：驱动因素、市场空间、产业链及相关公司深度梳理.pdf",
        tier="B",
        cluster="secondary_research_reports",
    ),
    src(
        "local_guohai_gpu_asic_20251224",
        "GPU 加 ASIC 渗透加速，液冷市场规模再添增量",
        "国海证券",
        "2025-12-24",
        "报告认为 AI 服务器液冷渗透率加速上行，NVIDIA 高功率 GPU 和 Google TPU 等 ASIC 共同带动 2026 年液冷市场规模，需注意其为券商测算口径。",
        local_path="papers/液冷/23_20251224-国海证券-计算机行业专题报告：GPU+ASIC渗透加速，液冷市场规模再添增量.pdf",
        tier="A",
        cluster="broker_liquid_cooling_reports",
    ),
    src(
        "web_nvidia_gb300_nvl72",
        "NVIDIA GB300 NVL72",
        "NVIDIA",
        "2026-07-04",
        "The NVIDIA GB300 NVL72 features a fully liquid-cooled, rack-scale architecture that integrates 72 NVIDIA Blackwell Ultra GPUs and 36 Arm-based NVIDIA Grace CPUs into a single platform.",
        url="https://www.nvidia.com/en-us/data-center/gb300-nvl72/",
        tier="S",
        language="en-US",
        cluster="nvidia_official",
    ),
    src(
        "web_nvidia_gb200_nvl72",
        "NVIDIA GB200 NVL72",
        "NVIDIA",
        "2025-03-18",
        "NVIDIA GB200 NVL72 connects 36 Grace CPUs and 72 Blackwell GPUs in a rack-scale, liquid-cooled design.",
        url="https://www.nvidia.com/en-us/data-center/gb200-nvl72/",
        tier="S",
        language="en-US",
        cluster="nvidia_official",
    ),
    src(
        "web_nvidia_ocp_gb200",
        "NVIDIA Contributes GB200 NVL72 Designs to Open Compute Project",
        "NVIDIA Developer Blog",
        "2024-10-15",
        "NVIDIA contributed NVIDIA GB200 NVL72 rack and liquid-cooled compute tray designs to the Open Compute Project and worked with partners on reference architectures.",
        url="https://developer.nvidia.com/blog/nvidia-contributes-nvidia-gb200-nvl72-designs-to-open-compute-project/",
        tier="S",
        language="en-US",
        cluster="nvidia_official",
    ),
    src(
        "web_google_ironwood_tpu",
        "Ironwood: The first Google TPU for the age of inference",
        "Google",
        "2025-04-09",
        "Ironwood is Google's seventh-generation TPU, built for inference, and can scale up to 9,216 chips in a single pod.",
        url="https://blog.google/innovation-and-ai/infrastructure-and-cloud/google-cloud/ironwood-tpu-age-of-inference/",
        tier="S",
        language="en-US",
        cluster="google_official",
    ),
    src(
        "web_google_arpae_cooling",
        "AI/ML Cooling Evolution at Google",
        "Google / ARPA-E",
        "2026-01-01",
        "Google's AI/ML cooling presentation lists Ironwood 2025 and describes heat out through air and liquid paths for next generation AI systems.",
        url="https://arpa-e.energy.gov/sites/default/files/2026-01/Day1_03c_Google_Zhang.pdf",
        tier="A",
        language="en-US",
        cluster="google_official",
    ),
    src(
        "web_huawei_atlas_a3_superpod",
        "Huawei Launches Open-Access SuperPoD Architecture",
        "Huawei",
        "2025-09-18",
        "Huawei reported that more than 300 Atlas 900 A3 SuperPoD units had been shipped in 2025 and deployed by more than 20 customers.",
        url="https://www.huawei.com/en/news/2025/9/hc-superpod-innovation",
        tier="S",
        language="en-US",
        cluster="huawei_official",
    ),
    src(
        "web_ocp_l_l_cdu_method",
        "Liquid to Liquid CDU Test Methodology and Performance Rating",
        "Open Compute Project",
        "2024-08-01",
        "Coolant Distribution Unit is a key ingredient of the liquid cooling system, and it isolates the facility side of cooling loop from the IT side flow network.",
        url="https://www.opencompute.org/documents/ocp-wp-l-lcdu-test-methodology-performance-rating-r1-pdf",
        tier="S",
        language="en-US",
        cluster="ocp_standards",
    ),
    src(
        "web_ocp_tcs_manifold",
        "OCP TCS Row Manifolds Pre-Commission Preparation",
        "Open Compute Project",
        "2025-01-27",
        "The document describes secondary cooling loops for coolant to pass through to the racks and focuses on preparation of TCS row manifolds before commissioning.",
        url="https://www.opencompute.org/documents/ocp-document-submission-guidelines-for-pre-commission-preparation-of-technology-cooling-system-tcs-row-manifolds-revq-pdf-1",
        tier="S",
        language="en-US",
        cluster="ocp_standards",
    ),
    src(
        "web_ul_cdu_certification",
        "Coolant Distribution Units for Data Centers",
        "UL Solutions",
        "2025-01-01",
        "UL describes CDUs designed for data centers using non-refrigerant coolants and maps safety certification to UL/CAN/IEC 62368-1.",
        url="https://www.ul.com/sites/default/files/2025-01/Coolant_Distribution_Unit_Infosheet.pdf",
        tier="S",
        language="en-US",
        cluster="safety_standards",
    ),
    src(
        "web_supermicro_inrack_cdu",
        "Supermicro In-Rack CDU Datasheet",
        "Supermicro",
        "2026-01-01",
        "Supermicro's in-rack CDU data sheet lists up to 250kW cooling capacity and redundant pump, MCU and power supply architecture.",
        url="https://www.supermicro.com/datasheet/datasheet_In_Rack_CDU.pdf",
        tier="A",
        language="en-US",
        cluster="server_oem_datasheets",
    ),
    src(
        "web_supermicro_inrow_cdu",
        "Supermicro In-Row CDU Datasheet",
        "Supermicro",
        "2026-01-01",
        "Supermicro's in-row CDU data sheet lists cooling capacity up to 1.8MW, N+1 pumps, Redfish or SNMP monitoring and high density rack support.",
        url="https://www.supermicro.com/datasheet/datasheet_In_Row_CDU.pdf",
        tier="A",
        language="en-US",
        cluster="server_oem_datasheets",
    ),
    src(
        "web_vertiv_nvidia_gb200",
        "Vertiv codevelops complete power and cooling blueprint for NVIDIA GB200 NVL72",
        "Vertiv",
        "2024-10-14",
        "Vertiv's reference architecture supports the NVIDIA GB200 NVL72 liquid-cooled rack-scale platform at up to 132kW per rack.",
        url="https://www.vertiv.com/en-emea/about/news-and-events/news-releases/vertiv-codevelops-with-nvidia-complete-power-and-cooling-blueprint-for--nvidia-gb200-nvl72-platform/",
        tier="S",
        language="en-US",
        cluster="vertiv_official",
    ),
    src(
        "web_coolit_chx2000",
        "CoolIT Systems announces CHx2000 row-based CDU",
        "CoolIT Systems",
        "2025-06-17",
        "CoolIT says the CHx2000 provides 2MW of liquid cooling capacity and 1.2LPM per kW, supporting up to twelve 120kW NVIDIA GB200 NVL72 racks.",
        url="https://www.coolitsystems.com/resources/news/coolit-systems-announces-further-breakthroughs-in-row-based-coolant-distribution-unit-performance/",
        tier="S",
        language="en-US",
        cluster="coolit_official",
    ),
    src(
        "web_coolit_nvidia",
        "CoolIT liquid cooling solutions for NVIDIA AI factories",
        "CoolIT Systems",
        "2026-01-01",
        "CoolIT describes co-innovation with NVIDIA across cold plates and CDUs for Blackwell and AI factory liquid cooling deployments.",
        url="https://www.coolitsystems.com/capabilities/co-innovation/nvidia/",
        tier="S",
        language="en-US",
        cluster="coolit_official",
    ),
    src(
        "web_schneider_motivair_mw_cdu",
        "Motivair by Schneider Electric announces MCDU-70 CDU",
        "Schneider Electric",
        "2026-01-15",
        "Motivair by Schneider Electric announced a CDU platform ranging from 105kW to 2.5MW and designed to scale to 10MW and beyond for next-generation AI factories.",
        url="https://www.se.com/us/en/about-us/newsroom/news/press-releases/motivair-by-schneider-electric-announces-new-cdu-with-capability-to-scale-to-10mw-and-beyond-for-next-gen-ai-factories-69705c3655f8517e99086bbd/",
        tier="S",
        language="en-US",
        cluster="schneider_motivair_official",
    ),
    src(
        "web_schneider_motivair_acquire",
        "Schneider Electric acquires Motivair",
        "Schneider Electric",
        "2024-10-10",
        "Schneider Electric said Motivair is a global provider of advanced liquid cooling solutions for high performance computing and AI data centers.",
        url="https://www.se.com/ww/en/about-us/newsroom/news/press-releases/schneider-electric-strengthens-its-leading-position-in-data-centers-by-acquiring-motivair-corporation-a-key-global-provider-of-advanced-liquid-cooling-solutions-6703da89b2c991087e04a56b",
        tier="S",
        language="en-US",
        cluster="schneider_motivair_official",
    ),
    src(
        "web_motivair_manufacturing_2025",
        "Motivair by Schneider Electric expands U.S. manufacturing footprint",
        "Motivair",
        "2025-06-27",
        "Motivair expanded its U.S. manufacturing footprint to support AI and HPC liquid cooling demand.",
        url="https://www.motivaircorp.com/news/motivair-by-schneider-electric-expands-u-s-manufacturing-footprint/",
        tier="A",
        language="en-US",
        cluster="schneider_motivair_official",
    ),
    src(
        "web_delta_cdu",
        "Data Center Cooling Solutions",
        "Delta Electronics",
        "2026-01-01",
        "Delta says AI and HPC workloads push thermal limits and lists liquid-to-air and liquid-to-liquid CDUs for demanding GPU and CPU applications.",
        url="https://www.deltaww.com/en-US/products/data-center-cooling/",
        tier="A",
        language="en-US",
        cluster="delta_official",
    ),
    src(
        "web_eaton_cdu",
        "Coolant Distribution Unit for Data Centers",
        "Eaton / Boyd Thermal",
        "2026-01-01",
        "Eaton's CDU page highlights seal-less N+1 redundant pumps, filtration, pressure testing and serviceability for data center liquid cooling.",
        url="https://www.eaton.com/us/en-us/catalog/thermal-management-solutions/coolant-distribution-unit-cdu.html",
        tier="A",
        language="en-US",
        cluster="eaton_boyd_official",
    ),
    src(
        "web_chilldyne_nvl72_reference",
        "Chilldyne Reference Design for AI NVIDIA NVL72",
        "Chilldyne",
        "2025-03-01",
        "Chilldyne's reference design lists CDU-300 for up to 300kW and CDU-1500 for up to 1.5MW liquid cooling capacity.",
        url="https://chilldyne.com/wp-content/uploads/2025/03/Chilldyne-Reference-Design-for-AI-NVIDIA-NVL72-X.3.pdf",
        tier="A",
        language="en-US",
        cluster="chilldyne_official",
    ),
    src(
        "web_grundfos_datacenters",
        "Data Center Cooling Solutions",
        "Grundfos",
        "2026-01-01",
        "Grundfos positions intelligent pumps, sensors and HVAC water solutions for data centers, including liquid cooling and uptime requirements.",
        url="https://www.grundfos.com/solutions/industries/data-centers",
        tier="A",
        language="en-US",
        cluster="pump_oem_official",
    ),
    src(
        "web_grundfos_it_cooling",
        "IT Cooling and immersion cooling pump solutions",
        "Grundfos",
        "2026-01-01",
        "Grundfos describes active redundancy, pump controls and support for in-row CDUs, immersion cooling and IT cooling loops.",
        url="https://www.grundfos.com/solutions/industries/industrial-manufacturing-oems/it-cooling",
        tier="A",
        language="en-US",
        cluster="pump_oem_official",
    ),
    src(
        "web_wilo_datacenters",
        "Data Centers Cooling Pumps",
        "Wilo",
        "2026-01-01",
        "Wilo says its pumps support chilled water circulation, direct-to-chip liquid cooling, immersion cooling and CDU systems in data centers.",
        url="https://wilo.com/us/en_us/Solutions/Markets/Data-Centers/",
        tier="A",
        language="en-US",
        cluster="pump_oem_official",
    ),
    src(
        "web_wilo_pumps_role",
        "The Critical Role of Pumps in Data Center Cooling",
        "Wilo",
        "2026-01-01",
        "Wilo describes mission-critical pump requirements, stainless steel construction, dielectric fluid compatibility and high reliability for data center cooling.",
        url="https://wilo.com/us/en_us/About-Wilo/Blog/The-Critical-Role-of-Pumps-in-Data-Center-Cooling/",
        tier="A",
        language="en-US",
        cluster="pump_oem_official",
    ),
    src(
        "web_xylem_datacenters",
        "Data Centers water and hydronic cooling solutions",
        "Xylem",
        "2026-01-01",
        "Xylem presents hydronic cooling, water treatment, filtration and monitoring as data center solutions to reduce downtime and resource use.",
        url="https://www.xylem.com/en-us/info/data-centers/",
        tier="A",
        language="en-US",
        cluster="pump_oem_official",
    ),
    src(
        "web_moog_liquid_pumps",
        "Liquid Cooling Solutions for Data Centers",
        "Moog",
        "2026-01-01",
        "Moog says CoreMotion magnetic pumps for direct-to-chip and immersion cooling minimize size, eliminate rotating seals and reduce leak points.",
        url="https://www.moog.com/products/pumps/liquid-cooling-pumps-for-data-centers.html",
        tier="A",
        language="en-US",
        cluster="pump_oem_official",
    ),
    src(
        "web_johnson_dc_pump",
        "数据中心液冷泵解决方案",
        "Johnson Electric 德昌电机",
        "2026-01-01",
        "德昌电机数据中心液冷泵页面列出 DCP1800 等机架 CDU 和服务器液冷泵方案，示例规格包括 200 LPM、250 kPa、48V、1800W、不锈钢和 RS485 控制。",
        url="https://www.johnsonelectric.cn/solutions/liquid-cooling/data-centre",
        tier="A",
        language="zh-CN",
        cluster="pump_oem_official",
    ),
    src(
        "web_envicool_air_liquid_cdu",
        "英维克机架级风液 CDU 产品",
        "英维克",
        "2026-01-01",
        "英维克机架级风液 CDU 面向服务器 CPU 和 GPU 散热，通过泵和换热单元把冷却液送入冷板并带走热量，是系统商与组件验证的重要入口。",
        url="https://www.envicool.com/productinfo545.html",
        tier="A",
        language="zh-CN",
        cluster="china_company_official",
    ),
    src(
        "web_shenling_liquid_cdu",
        "申菱环境液冷 CDU 产品",
        "申菱环境",
        "2026-01-01",
        "申菱环境液冷 CDU 产品页面列出 200-1800kW 冷却能力，支持小于等于 140kW 高密度机柜、AI 智算中心、变频泵和自适应运行，PUE 可到 1.15 以内。",
        url="https://www.shenling.com/products/%E6%B6%B2%E5%86%B7cdu/",
        tier="A",
        language="zh-CN",
        cluster="china_company_official",
    ),
    src(
        "web_sanhua_ir_20251031",
        "三花智控投资者关系：AIDC 液冷部件",
        "三花智控 / 新浪公告镜像",
        "2025-10-31",
        "三花智控投资者关系材料称 AIDC 快速发展，公司在阀、泵、换热器等热管理部件上有布局，具体收入和客户仍需按定期报告拆分。",
        url="https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=11834809&stockid=002050",
        tier="B",
        language="zh-CN",
        cluster="china_company_ir",
    ),
    src(
        "web_sanhua_liquid_award",
        "三花商用制冷获液冷核心部件卓越贡献奖",
        "三花商用制冷",
        "2025-01-01",
        "三花商用制冷披露获得液冷核心部件卓越贡献奖，说明其液冷部件能力被产业活动认可，但不等于 NVIDIA、Google 或华为直接供货确认。",
        url="https://commercial.sanhuagroup.com/news/show.php?itemid=29",
        tier="A",
        language="zh-CN",
        cluster="china_company_official",
    ),
    src(
        "web_sanhua_eastmoney_20260701",
        "三花智控：数据中心和储能是战略业务",
        "东方财富",
        "2026-07-01",
        "媒体报道三花智控称数据中心和储能是战略业务，产品覆盖阀、泵、换热器和控制器，并与领先热管理集成商合作；该来源为媒体摘要，需用公告和 IR 原文复核。",
        url="https://wap.eastmoney.com/a/202607013790159411.html",
        tier="B",
        language="zh-CN",
        role="early_signal_candidate",
        cluster="media_early_signal",
    ),
    src(
        "web_feilong_sina_20260701",
        "飞龙股份 AI 液冷泵业务跟踪",
        "新浪财经",
        "2026-07-01",
        "报道称飞龙股份下游客户包括英维克、申菱环境、台达和 Vertiv，超过 120 个液冷项目但只有部分小批量；2025 年新能源和民用液冷收入多来自汽车，数据中心贡献仍有限。",
        url="https://finance.sina.com.cn/stock/observe/2026-07-01/doc-inifiaen4120762.shtml?cre=tianyi&loc=9&mod=pchp&r=0&rfunc=23&tj=cxvertical_pc_hp&tr=12",
        tier="B",
        language="zh-CN",
        role="early_signal_candidate",
        cluster="media_early_signal",
    ),
    src(
        "web_liquidstack_cdu_selection",
        "How to choose the right CDU for your data center",
        "LiquidStack",
        "2025-12-02",
        "LiquidStack says CDU selection should consider thermal capacity, flow rate, pump head, facility integration and total cost of ownership rather than only headline purchase price.",
        url="https://liquidstack.com/blog/how-to-choose-the-right-coolant-distribution-unit-cdu-for-your-data-center",
        tier="A",
        language="en-US",
        cluster="system_oem_guidance",
    ),
    src(
        "web_precedence_cdu_pumps_market",
        "Data Center Cooling CDU Pumps Market",
        "Precedence Research",
        "2026-07-01",
        "The market report estimates the data center cooling CDU pumps market at USD 320 million in 2025, but the definition must be checked because market reports may mix rack CDU, centrifugal pumps and magnetic pumps.",
        url="https://www.precedenceresearch.com/data-center-cooling-cdu-pumps-market",
        tier="C",
        language="en-US",
        role="reference_only",
        cluster="market_report_reference",
    ),
]


SOURCE_BY_REF = {source["ref"]: source for source in SOURCES}


def dp(
    entity_key: str,
    source_ref: str,
    metric: str,
    value_text: str,
    *,
    unit: str = "事实",
    period: str | None = None,
    as_of_date: str | None = AS_OF_DATE,
    value_num: float | None = None,
    excerpt: str | None = None,
    role: str = "core_evidence",
    status: str = "available",
) -> dict[str, Any]:
    if source_ref not in SOURCE_BY_REF:
        raise KeyError(f"unknown source_ref {source_ref}")
    return {
        "source_ref": source_ref,
        "entity_key": entity_key,
        "metric": metric,
        "period": period or as_of_date,
        "as_of_date": as_of_date,
        "value_num": value_num,
        "value_text": _clip(value_text, 840),
        "unit": unit,
        "source_excerpt": _clip(excerpt or value_text, 840),
        "value_status": status,
        "calculation_review_status": "pass",
        "extraction_method": "manual_verified",
        "policy_evidence_role": role,
        "observation_count": 1,
    }


FACTS: list[dict[str, Any]] = []


def add_fact(*args: Any, **kwargs: Any) -> None:
    FACTS.append(dp(*args, **kwargs))


ENTITY_KEYS = [
    "product_boundary_cdu_pump",
    "demand_tam_sam_som",
    "customer_validation_matrix",
    "global_competition_stack",
    "china_component_targets",
    "price_value_chain",
    "reliability_control_barrier",
    "contamination_and_falsification",
]

THEORY_RESEARCH_ENTITY_KEYS = {
    "product_boundary_cdu_pump",
    "price_value_chain",
}


def is_theory_research_entity(entity_or_key: dict[str, Any] | str) -> bool:
    key = entity_or_key if isinstance(entity_or_key, str) else entity_or_key.get("key")
    return key in THEORY_RESEARCH_ENTITY_KEYS


# 产品边界和技术强度
for metric, value, source_ref in [
    ("CDU 产品边界", "CDU 隔离设施侧水环路和 IT 侧流体网络，并通过换热器实现热量转移。", "web_ocp_l_l_cdu_method"),
    ("二次侧闭环边界", "液冷泵核心研究对象是 CDU 内部或 TCS 二次侧循环泵，不是一侧冷却塔、冷水机组或普通建筑水泵。", "web_ocp_l_l_cdu_method"),
    ("TCS row manifold 边界", "OCP TCS row manifold 文件把二次侧回路、冲洗、清洁和机柜连接作为交付前准备重点。", "web_ocp_tcs_manifold"),
    ("数据中心 CDU 安全认证", "UL 把数据中心非制冷剂冷却液 CDU 映射到 IT 设备安全标准，说明 CDU 不是普通工业换热器。", "web_ul_cdu_certification"),
    ("服务器液冷泵连续运行", "服务器端液冷泵按 7x24、全年 8760 小时运行设计，显著高于车端水泵年均约 2000 小时。", "xlsx_vehicle_vs_server_pump"),
    ("服务器液冷泵寿命要求", "服务器端液冷泵设计寿命为 10-15 年不间断，车端多为 8-10 年或间歇运行。", "xlsx_vehicle_vs_server_pump"),
    ("泄漏容忍度", "服务器液冷泵泄漏容忍度接近零，车端热管理仍有一定容忍空间。", "xlsx_vehicle_vs_server_pump"),
    ("泵扬程差异", "服务器液冷泵扬程 4Bar 以上，车端常见 1-2Bar，差距约 2-4 倍。", "xlsx_vehicle_vs_server_pump"),
    ("流量精度差异", "服务器液冷泵流量精度要求约 1%-2%，车端约 5%，差距约 3-5 倍。", "xlsx_vehicle_vs_server_pump"),
    ("泵选型三要素", "OCP 要求泵选型同时考虑性能、可靠性和冷却液兼容性。", "web_ocp_l_l_cdu_method"),
    ("泵冗余要求", "OCP 明确泵冗余 N+1 或更高对维修或单泵故障期间维持服务是必要的。", "web_ocp_l_l_cdu_method"),
    ("润湿材料要求", "OCP 建议泵的润湿部件必须与冷却液兼容，常用 304/316 不锈钢并关注机械密封材料。", "web_ocp_l_l_cdu_method"),
    ("控制系统要求", "CDU 控制器需要监控流量、压力、温度并在泄漏或异常工况下触发安全动作。", "web_ocp_l_l_cdu_method"),
    ("清洁和颗粒控制", "OCP 对 CDU 部件清洁、过滤、异物控制提出要求，说明泵厂交付不只是水力性能。", "web_ocp_l_l_cdu_method"),
    ("直接液冷系统脑部功能", "OCP 将 L-L CDU 称为直接液冷系统中调节 FWS 和 TCS 流动并通信状态的核心控制单元。", "web_ocp_l_l_cdu_method"),
]:
    add_fact("product_boundary_cdu_pump", source_ref, metric, value)


# 需求、TAM/SAM/SOM 和平台驱动
for metric, value, source_ref, value_num, unit in [
    ("NVIDIA GB300 架构", "GB300 NVL72 为全液冷机架级架构，集成 72 个 Blackwell Ultra GPU 和 36 个 Grace CPU。", "web_nvidia_gb300_nvl72", 72, "GPU"),
    ("NVIDIA GB200 架构", "GB200 NVL72 连接 36 个 Grace CPU 和 72 个 Blackwell GPU，采用液冷机架级设计。", "web_nvidia_gb200_nvl72", 72, "GPU"),
    ("NVIDIA OCP 贡献", "NVIDIA 把 GB200 NVL72 机架和液冷计算托盘设计贡献给 OCP，液冷标准化提高生态可复制性。", "web_nvidia_ocp_gb200", None, "事实"),
    ("Google Ironwood 规模", "Google Ironwood TPU 单 pod 可扩展到 9,216 颗芯片，推理集群规模抬升液冷流体网络复杂度。", "web_google_ironwood_tpu", 9216, "芯片"),
    ("Google 冷却演进", "Google 冷却演进材料显示 Ironwood 2025 代际同时涉及空气和液体带走热量。", "web_google_arpae_cooling", None, "事实"),
    ("华为 Atlas SuperPoD 部署", "华为称 2025 年 Atlas 900 A3 SuperPoD 已交付超过 300 台，部署于 20 多个客户。", "web_huawei_atlas_a3_superpod", 300, "台"),
    ("NVIDIA 机柜出货测算", "中泰证券测算 NVIDIA rack shipments 2025-2027E 为 3、9、12 万台，CDU 和泵需求取决于实际机柜结构。", "local_zhongtai_liquid_20260528", 12, "万台"),
    ("GB200 机柜液冷价值量", "中泰证券测算 GB200 rack 液冷价值量约 74,760 美元，其中 CDU 约 30,000 美元。", "local_zhongtai_liquid_20260528", 74760, "美元/柜"),
    ("GB300 机柜液冷价值量", "中泰证券测算 GB300 rack 液冷价值量约 95,280 美元，其中 CDU 约 30,000 美元。", "local_zhongtai_liquid_20260528", 95280, "美元/柜"),
    ("Rubin 机柜液冷价值量", "中泰证券测算 Rubin rack 液冷价值量约 116,700 美元，代际功耗继续推升液冷系统价值量。", "local_zhongtai_liquid_20260528", 116700, "美元/柜"),
    ("Google TPU 液冷价值量", "中泰证券测算 Google TPU 机柜液冷组件合计约 66,000 美元，含 CDU 30,000 美元。", "local_zhongtai_liquid_20260528", 66000, "美元/柜"),
    ("Google TPU 液冷空间", "中泰证券测算 Google TPU 液冷空间 2026E/2027E 约 257/765 亿元，属于券商模型口径。", "local_zhongtai_liquid_20260528", 765, "亿元"),
    ("NVIDIA rack 液冷空间", "中泰证券测算 NVIDIA rack 液冷市场 2025-2027E 约 184.2、631.3、905.3 亿元。", "local_zhongtai_liquid_20260528", 905.3, "亿元"),
    ("CDU 不是一柜一台", "中泰证券明确提示当前 CDU 多为 In-Row 架构，不应简单按一柜一 CDU 线性外推泵需求。", "local_zhongtai_liquid_20260528", None, "事实"),
    ("NVIDIA Rubin 功耗升级", "东吴证券表格显示 Rubin Ultra NVL144 机柜功率可达约 626kW，功耗跃迁推高泵和 CDU 冗余要求。", "local_dongwu_liquid_20260626", 626, "kW/柜"),
    ("Google TPU v8t 功耗升级", "东吴证券表格估计 TPU V8t 训练机柜功率约 110kW，ASIC 集群同样推动液冷需求。", "local_dongwu_liquid_20260626", 110, "kW/柜"),
    ("Huawei CloudMatrix 功率", "中泰证券引用华为 CloudMatrix 384 资料称单柜密度约 42kW，总功率约 559kW，该数据需用华为官方资料复核。", "local_zhongtai_liquid_20260528", 559, "kW"),
    ("2026 液冷渗透率测算", "广发证券引用行业资料认为 2026 年 AI 芯片液冷渗透率可能升至 47%，该口径是测算不是订单。", "local_guangfa_liquid_20260530", 47, "%"),
    ("AI 液冷市场 2026", "国海证券测算 2026 年液冷市场规模可达 165 亿美元，需拆分 GPU、ASIC、CDU、冷板和泵口径。", "local_guohai_gpu_asic_20251224", 165, "亿美元"),
    ("CDU pump 市场参考", "Precedence Research 估计 2025 年 data center cooling CDU pumps 市场约 3.2 亿美元，但需严查定义是否混合 pump 和 CDU。", "web_precedence_cdu_pumps_market", 320, "百万美元"),
]:
    add_fact("demand_tam_sam_som", source_ref, metric, value, value_num=value_num, unit=unit)


# 客户验证矩阵
for metric, value, source_ref in [
    ("NVIDIA 平台液冷确认", "NVIDIA 官方确认 GB300 NVL72 是全液冷机架级系统，但未列出独立泵供应商。", "web_nvidia_gb300_nvl72"),
    ("NVIDIA GB200 生态标准化", "NVIDIA 将 GB200 液冷设计贡献给 OCP，提高系统商和组件商进入生态的标准化程度。", "web_nvidia_ocp_gb200"),
    ("Vertiv 与 NVIDIA 验证阶段", "Vertiv 公开与 NVIDIA 共研 GB200 NVL72 电力和冷却参考架构，属于强系统商验证。", "web_vertiv_nvidia_gb200"),
    ("CoolIT NVIDIA 生态", "CoolIT 公开与 NVIDIA 协作冷板和 CDU，CHx2000 支持 GB200 NVL72 高密度液冷机柜。", "web_coolit_chx2000"),
    ("Schneider/Motivair AI factory", "Schneider/Motivair 推出可扩至 10MW 以上的 CDU 平台，指向 AI factory 级需求，但不等于指定芯片客户泵供货。", "web_schneider_motivair_mw_cdu"),
    ("Delta CDU 能力", "台达官方列出面向 GPU/CPU 高负载的液冷 CDU，具备系统商能力但页面未直接披露 NVIDIA/Google/华为客户。", "web_delta_cdu"),
    ("Eaton/Boyd CDU 能力", "Eaton/Boyd 页面强调无轴封 N+1 冗余泵和过滤测试，属于 CDU 技术能力证据。", "web_eaton_cdu"),
    ("Google TPU 平台确认", "Google 官方确认 Ironwood TPU 集群规模，液冷路径由 Google 冷却演进材料补充，但未披露具体泵厂。", "web_google_ironwood_tpu"),
    ("Google 冷却技术演进", "Google ARPA-E 材料显示下一代 AI 系统同时使用空气和液体带走热量，是平台需求证据而非供应商验证。", "web_google_arpae_cooling"),
    ("Huawei SuperPoD 需求确认", "华为披露 Atlas 900 A3 SuperPoD 出货和客户部署，确认国产 AI 集群热管理需求，但未公开泵供应商。", "web_huawei_atlas_a3_superpod"),
    ("英维克产品能力", "英维克机架级风液 CDU 公开说明面向 CPU/GPU 冷板散热，可作为华为、国产链和通用 AI 数据中心系统商观察对象。", "web_envicool_air_liquid_cdu"),
    ("申菱 CDU 能力", "申菱液冷 CDU 官方页面列出 200-1800kW 和高密度机柜支持，说明系统能力强于单纯泵厂供货证据。", "web_shenling_liquid_cdu"),
    ("中国系统商间接线索", "中原证券把部分中国液冷企业列入 NVIDIA/Google 生态，但该信息属于二级研究，不能替代客户公告。", "local_zhongyuan_home_20260618"),
    ("飞龙下游客户线索", "新浪报道飞龙下游客户包括英维克、申菱、台达、Vertiv，但也指出数据中心贡献仍有限，不能写成量产供货。", "web_feilong_sina_20260701"),
    ("纪要客户线索限制", "长江和东吴纪要可提示下半年催化和验证方向，但客户和份额口径不进入核心供货确认。", "local_changjiang_minutes_liquid"),
]:
    add_fact("customer_validation_matrix", source_ref, metric, value, role=SOURCE_BY_REF[source_ref].get("policy_evidence_role", "core_evidence"))


# 全球竞争和系统层级
for metric, value, source_ref in [
    ("全球泵厂名单", "结构化表格列出 Wilo、格兰富、赛莱默、穆格、南方泵业、德昌机电、大元泵业等，说明 pump 参与者分布比券商推荐标的更广。", "xlsx_pump_company_universe"),
    ("格兰富定位", "格兰富官方定位为数据中心智能泵、传感器和 HVAC 水解决方案供应商，优势在一次/二次侧水力和控制。", "web_grundfos_datacenters"),
    ("格兰富 IT cooling", "格兰富 IT cooling 页面强调 active redundancy、in-row CDU 和 immersion cooling 支持，适合做高可靠泵对照。", "web_grundfos_it_cooling"),
    ("Wilo 数据中心泵", "Wilo 官方称其泵支持直连芯片液冷、浸没式和 CDU 系统，说明传统泵厂已进入数据中心液冷叙事。", "web_wilo_datacenters"),
    ("Wilo 材料兼容", "Wilo 文章强调不锈钢、介质兼容和 mission-critical 可靠性，竞争焦点是可靠性而非单一价格。", "web_wilo_pumps_role"),
    ("Xylem 水处理和监控", "Xylem 更偏水力、水处理、过滤和监测，适合设施侧和 hydronic cooling 对照，不宜直接写成 CDU 二次侧泵龙头。", "web_xylem_datacenters"),
    ("Moog 磁力泵差异化", "Moog CoreMotion 磁力泵强调无旋转密封、更少泄漏点和小体积，是技术路线差异化证据。", "web_moog_liquid_pumps"),
    ("德昌电机规格", "德昌电机 DCP1800 数据中心液冷泵公开 200LPM、250kPa、48V、1800W、不锈钢和 RS485 控制规格。", "web_johnson_dc_pump"),
    ("Supermicro in-rack CDU", "Supermicro in-rack CDU 最高 250kW，带冗余泵、MCU 和 PSU，是 OEM 侧 CDU 泵需求样本。", "web_supermicro_inrack_cdu"),
    ("Supermicro in-row CDU", "Supermicro in-row CDU 最高 1.8MW、N+1 pumps 和 Redfish/SNMP 监控，说明高功率场景会转向行级 CDU。", "web_supermicro_inrow_cdu"),
    ("Chilldyne CDU 分层", "Chilldyne NVL72 参考设计列出 CDU-300 和 CDU-1500，反映 300kW 到 1.5MW 多层级系统需求。", "web_chilldyne_nvl72_reference"),
    ("CoolIT 行级 CDU", "CoolIT CHx2000 2MW row-based CDU 可支持多个 120kW GB200 NVL72 rack，系统商具备规模交付壁垒。", "web_coolit_chx2000"),
    ("Motivair 制造扩张", "Motivair 扩大美国制造足迹，说明 AI/HPC 液冷系统商开始围绕交付能力竞争。", "web_motivair_manufacturing_2025"),
    ("Schneider 收购 Motivair", "Schneider 收购 Motivair 后补齐 AI 数据中心液冷组合，竞争格局从单泵厂扩展到电力加冷却平台。", "web_schneider_motivair_acquire"),
    ("广发供应链分层", "广发证券把 CDU、manifold、连接器、冷板和液冷模组集成商分层，泵公司通常通过 CDU 或系统商进入客户。", "local_guangfa_liquid_20260530"),
]:
    add_fact("global_competition_stack", source_ref, metric, value)


# 中国标的和承接能力
for metric, value, source_ref, role in [
    ("飞龙产品平台", "飞龙液冷泵已覆盖中型 Sidecar/InRack CDU 泵和大型 InRow CDU 泵，22kW/37kW 平台标为已量产。", "xlsx_feilong_product_layout", "core_evidence"),
    ("飞龙项目数量", "新浪报道飞龙液冷项目超过 120 个但只有部分小批量，说明验证债大于收入确认。", "web_feilong_sina_20260701", "early_signal_candidate"),
    ("飞龙收入口径", "新浪报道飞龙 2025 年新能源和民用液冷收入 6.73 亿元、同比增长 28.10%，主要来自新能源汽车，数据中心贡献有限。", "web_feilong_sina_20260701", "early_signal_candidate"),
    ("飞龙客户线索", "表16把飞龙客户列为申菱环境、英维克、高澜等系统商，但需公告和客户资料复核。", "xlsx_global_cdu_pump_players", "core_evidence"),
    ("英维克 CDU 产品", "英维克机架级风液 CDU 直接面向 CPU/GPU 冷板散热，是系统商验证优先级高于纯 pump 线索的标的。", "web_envicool_air_liquid_cdu", "core_evidence"),
    ("申菱 CDU 功率", "申菱液冷 CDU 产品 200-1800kW，支持 AI 智算中心和高密度机柜，具备系统集成和控制能力。", "web_shenling_liquid_cdu", "core_evidence"),
    ("高澜系统能力", "研究库和券商材料显示高澜在数据中心液冷和工业热管理有布局，但公开资料仍需拆分数据中心收入。", "local_zhongyuan_home_20260618", "core_evidence"),
    ("同飞数据中心液冷", "同飞股份在液冷行业映射中被列为数据中心液冷和温控解决方案标的，但客户和泵部件暴露要拆分。", "local_zhongyuan_home_20260618", "core_evidence"),
    ("三花部件布局", "三花 IR 和官网资料均指向阀、泵、换热器和控制器部件布局，但需要排除汽车热管理收入口径。", "web_sanhua_ir_20251031", "core_evidence"),
    ("三花液冷奖项", "三花获液冷核心部件贡献奖，支持部件能力，不支持直接客户供货结论。", "web_sanhua_liquid_award", "core_evidence"),
    ("三花媒体早期信号", "东方财富报道三花数据中心液冷覆盖房间侧、机柜侧、CDU 侧和战略项目团队，是早期跟踪线索。", "web_sanhua_eastmoney_20260701", "early_signal_candidate"),
    ("南方泵业模块泵", "方正证券提到南方泵业 CHL/CHM/CHLF 泵用于数据中心液冷模块，是泵厂观察入口。", "local_fangzheng_ai_hardware_20260529", "core_evidence"),
    ("大元泵业液冷覆盖", "结构化表格将大元泵业列为 IDC、储能等多领域液冷泵覆盖标的，需要排除储能和普通工业口径。", "xlsx_pump_company_universe", "core_evidence"),
    ("德昌数据中心泵", "德昌电机官方直接列出数据中心液冷泵规格，是比纯研报线索更强的产品能力证据。", "web_johnson_dc_pump", "core_evidence"),
    ("奇鋐双鸿供应链", "广发证券把奇鋐、双鸿等列为液冷散热模组和 NVIDIA 液冷相关供应链，偏系统/模组而非泵。", "local_guangfa_liquid_20260530", "core_evidence"),
    ("飞荣达映射", "研究库已有飞荣达液冷和热管理映射，但核心暴露偏材料、结构件和散热模组，不应当作液冷泵标的。", "local_zhongyuan_home_20260618", "core_evidence"),
]:
    add_fact("china_component_targets", source_ref, metric, value, role=role)


# 价格和价值链
for metric, value, source_ref, value_num, unit in [
    ("GB200 CDU 价值量", "中泰证券测算 GB200 rack CDU 价值量约 30,000 美元。", "local_zhongtai_liquid_20260528", 30000, "美元/柜"),
    ("GB300 CDU 价值量", "中泰证券测算 GB300 rack CDU 价值量约 30,000 美元，与冷板和 UQD 共同构成液冷价值。", "local_zhongtai_liquid_20260528", 30000, "美元/柜"),
    ("Google TPU CDU 价值量", "中泰证券测算 Google TPU 机柜 CDU 约 30,000 美元，不能直接等同泵价值量。", "local_zhongtai_liquid_20260528", 30000, "美元/柜"),
    ("GB200 冷板价值", "中泰证券测算 GB200 cold plate 约 25,200 美元，高于 CDU 以外多个分项。", "local_zhongtai_liquid_20260528", 25200, "美元/柜"),
    ("GB300 冷板价值", "中泰证券测算 GB300 cold plate 约 39,600 美元，显示液冷价值增量不只在泵。", "local_zhongtai_liquid_20260528", 39600, "美元/柜"),
    ("GB300 UQD 价值", "中泰证券测算 GB300 UQD 约 13,680 美元，连接器和泄漏可靠性也是价值链重点。", "local_zhongtai_liquid_20260528", 13680, "美元/柜"),
    ("二次侧价值占比", "东吴 2025 报告估计二次侧系统约占液冷系统价值 75%，但该口径需和 2026 新平台拆分。", "local_dongwu_liquid_20250126", 75, "%"),
    ("CDU 价值占比", "东吴 2025 报告估计 CDU 在冷板式液冷价值链中约占 25%，但泵只占 CDU 内部一部分。", "local_dongwu_liquid_20250126", 25, "%"),
    ("泵市场价格弱证据", "Precedence Research 的 CDU pumps 市场规模为参考口径，不能直接作为单泵 ASP 或上市公司收入弹性。", "web_precedence_cdu_pumps_market", 320, "百万美元"),
    ("电商报价污染", "公开电商或 Made-in-China 报价更接近通用水冷或矿机/工业设备样本，不代表 AI rack CDU 成交价格。", "web_liquidstack_cdu_selection", None, "事实"),
    ("TCO 选型", "LiquidStack 强调 CDU 选型要看热容量、流量、压头、设施集成和 TCO，不应只看裸 CAPEX。", "web_liquidstack_cdu_selection", None, "事实"),
    ("CoolIT 容量价值", "CoolIT CHx2000 以 2MW 和 1.2LPM/kW 为核心指标，说明系统厂定价围绕容量、流量和交付可靠性。", "web_coolit_chx2000", 2, "MW"),
    ("Motivair 容量区间", "Motivair 105kW-2.5MW CDU 区间说明 CDU 价格体系必须按容量层级拆分。", "web_schneider_motivair_mw_cdu", 2.5, "MW"),
]:
    add_fact("price_value_chain", source_ref, metric, value, value_num=value_num, unit=unit)


# 可靠性、控制和认证
for metric, value, source_ref, value_num, unit in [
    ("OCP 服务寿命", "OCP 表2把 L-L CDU pump service life 作为 10 年关键要求，且强调实际寿命因厂商而异。", "web_ocp_l_l_cdu_method", 10, "年"),
    ("OCP 工作温度", "OCP 表2列出 CDU 工作温度 17-65 摄氏度，体现液冷泵和材料兼容温区要求。", "web_ocp_l_l_cdu_method", 65, "摄氏度"),
    ("OCP TCS 压力", "OCP 说明 TCS 和 DECS 允许压力最高可达 100psi 或 690kPa，泵和管路必须满足。", "web_ocp_l_l_cdu_method", 690, "kPa"),
    ("OCP 过滤要求", "OCP 表2列出二次侧过滤小于等于 50 microns，泵和水路需要颗粒控制。", "web_ocp_l_l_cdu_method", 50, "micron"),
    ("OCP 冗余泵", "OCP 泵章节明确 N+1 或更多冗余对维持服务必要。", "web_ocp_l_l_cdu_method", 1, "N+1"),
    ("Eaton 无轴封", "Eaton CDU 页面强调 seal-less N+1 redundant pumps，减少泄漏点和维护风险。", "web_eaton_cdu", None, "事实"),
    ("Moog 无旋转密封", "Moog 磁力泵强调 eliminate rotating seals，直接对应泄漏风险约束。", "web_moog_liquid_pumps", None, "事实"),
    ("德昌泵压头", "德昌 DCP1800 页面给出 250kPa 压差能力，可作为中小型 CDU 泵规格样本。", "web_johnson_dc_pump", 250, "kPa"),
    ("德昌流量", "德昌 DCP1800 页面给出 200LPM 流量规格，可作为数据中心液冷泵公开规格样本。", "web_johnson_dc_pump", 200, "LPM"),
    ("德昌功率", "德昌 DCP1800 页面给出 1800W 和 48V 规格，说明数据中心泵并不等于车端 200W 水泵。", "web_johnson_dc_pump", 1800, "W"),
    ("Supermicro 监控", "Supermicro in-row CDU 配置 Redfish 或 SNMP 监控，泵和控制系统需要进入数据中心运维协议。", "web_supermicro_inrow_cdu", None, "事实"),
    ("申菱变频泵", "申菱 CDU 页面强调变频泵、分配和自适应运行，说明控制算法是国产系统商壁垒。", "web_shenling_liquid_cdu", None, "事实"),
    ("车端迁移功率差", "汽零迁移表显示车端功率约 200W，而 AI 液冷泵可到 22kW 以上，跨越需重新设计电磁和散热结构。", "xlsx_auto_transfer_barrier", 22, "kW"),
    ("车端迁移 MTBF", "汽零迁移表显示 AI 液冷泵 MTBF 要求 5 万小时以上，部分华为要求 9-12 万小时；车端仅 1.5-2 万小时。", "xlsx_auto_transfer_barrier", 50000, "小时"),
    ("控制精度迁移", "汽零迁移表显示 AI 液冷泵需 1%-2% 流量精度、变频控制并与 CDU 控制系统耦合。", "xlsx_auto_transfer_barrier", 2, "%"),
]:
    add_fact("reliability_control_barrier", source_ref, metric, value, value_num=value_num, unit=unit)


# 污染和证伪
for metric, value, source_ref in [
    ("车端水泵不能直接替代", "车端水泵的运行时长、功率、MTBF、泄漏和流量精度与服务器液冷泵差距明显，不能用汽车收入直接估算 AI 数据中心收入。", "xlsx_vehicle_vs_server_pump"),
    ("储能泵污染", "飞龙小泵平台已量产但主要面向储能和充电桩，不能作为 AI 数据中心 CDU 泵收入确认。", "xlsx_feilong_product_layout"),
    ("普通工业泵污染", "南方泵业、大元泵业等若只披露 IDC、储能或通用液冷泵，需要继续拆分 AI 数据中心和 CDU 二次侧收入。", "xlsx_pump_company_universe"),
    ("一次侧泵污染", "Xylem、Grundfos、Wilo 等传统水力公司既服务一次侧水系统也服务 CDU 或 IT cooling，研究时要拆分环节。", "web_xylem_datacenters"),
    ("系统商和泵厂归因", "英维克、申菱、Vertiv、CoolIT、Schneider 等强在 CDU 或系统交付，不能把系统收入全部归给泵。", "web_envicool_air_liquid_cdu"),
    ("客户验证债", "目前公开材料确认了 NVIDIA/Google/华为平台液冷需求，但纯泵厂直接绑定三大客户的公开证据不足。", "web_nvidia_gb300_nvl72"),
    ("媒体线索限制", "飞龙和三花的媒体线索价值在于提示项目和客户方向，不能替代定期报告、公告或客户验收。", "web_feilong_sina_20260701"),
    ("2024 标准旧证据警示", "OCP 2024 文件可作产品边界和测试标准，但距 2026 投资时点偏旧，不能单独证明最新订单。", "web_ocp_l_l_cdu_method"),
    ("价格外推风险", "CDU 价值量约 3 万美元不能直接外推为 pump ASP，泵只占 CDU 内部一部分且受冗余、控制、换热器和柜型影响。", "local_zhongtai_liquid_20260528"),
    ("Rubin 情景不等于订单", "Rubin 和 TPU v8t 的液冷需求代表未来强度，但没有客户公告时不能提前写成某泵厂供货。", "local_dongwu_rubin_minutes"),
]:
    add_fact("contamination_and_falsification", source_ref, metric, value, role=SOURCE_BY_REF[source_ref].get("policy_evidence_role", "core_evidence"))


TARGET_DEFS: list[dict[str, Any]] = [
    {
        "entity_key": "product_boundary_cdu_pump",
        "target_name": "OCP / UL CDU 标准与认证观察入口",
        "ticker": None,
        "market": "全球标准",
        "target_type": "external_watch",
        "target_url": "https://www.opencompute.org/documents/ocp-wp-l-lcdu-test-methodology-performance-rating-r1-pdf",
        "source_ref": "web_ocp_l_l_cdu_method",
        "priority": "P0 边界基准",
        "quality": "标准证据强，订单无关",
        "support": "supported",
        "exposure": "OCP 和 UL 文件不是投资标的，而是判断液冷泵产品边界、认证、材料兼容和泵冗余的基准入口。",
        "relative": "同实体内它优先级最高，因为所有公司标的都必须先满足这个边界，才有资格进入 AI 数据中心 CDU 泵研究。",
        "confirmed": "若后续公司产品明确满足 OCP/UL、TCS、N+1 和材料兼容要求，可把该公司从概念映射升级为可比产品。",
        "falsified": "若公司只披露普通水泵、车端泵或储能泵，且无法对齐这些标准要求，应排除出核心实体。",
        "view": "作为标准和认证基准使用，不做价格暴露；用于审计所有泵厂和系统商是否真的落在研究边界内。",
        "risk": "2024 年 OCP 文件偏旧，只能定义产品和测试边界，不能证明 2026 年订单或供货关系。",
    },
    {
        "entity_key": "demand_tam_sam_som",
        "target_name": "AI 液冷 CDU 需求观察篮子",
        "ticker": None,
        "market": "全球观察篮子",
        "target_type": "basket",
        "target_url": "https://www.nvidia.com/en-us/data-center/gb300-nvl72/",
        "source_ref": "local_zhongtai_liquid_20260528",
        "priority": "P0 需求基准",
        "quality": "需求强，泵收入需拆",
        "support": "supported",
        "exposure": "该篮子跟踪 NVIDIA GB200/GB300/Rubin、Google TPU、华为 Atlas 和 CDU 价值量，服务于 TAM/SAM/SOM 上限判断。",
        "relative": "同实体内它不是单个公司，而是所有公司估值和订单判断的分母；没有需求篮子，就无法判断飞龙、英维克、申菱等收入弹性。",
        "confirmed": "若机柜出货、CDU 容量、液冷渗透率和系统商交付同步上修，提升全链条需求假设。",
        "falsified": "若平台延后、机柜功率下降或 CDU 架构减少泵用量，降低所有公司外推弹性。",
        "view": "作为需求分母和市场空间基准，不直接等同推荐买入某个标的。",
        "risk": "券商测算和平台公告容易混用，必须把整体液冷、CDU 和 pump 三个口径分开。",
    },
    {
        "entity_key": "price_value_chain",
        "target_name": "CDU 内部泵 BOM / ASP 跟踪篮子",
        "ticker": None,
        "market": "全球观察篮子",
        "target_type": "basket",
        "target_url": "https://liquidstack.com/blog/how-to-choose-the-right-coolant-distribution-unit-cdu-for-your-data-center",
        "source_ref": "web_liquidstack_cdu_selection",
        "priority": "P1 价格补证",
        "quality": "价格弱证据，研究价值高",
        "support": "partially_supported",
        "exposure": "该篮子跟踪 CDU 内部泵、冗余泵、控制器、换热器、过滤和系统集成的 BOM/ASP 拆分，是纯泵厂收入测算的关键缺口。",
        "relative": "同实体内它比单一公司更重要，因为没有 pump BOM，所有泵厂弹性都会被 CDU 总价高估。",
        "confirmed": "若拿到 pump ASP、冗余数量和系统商采购价，可重新计算飞龙、德昌、Moog、Wilo 等泵厂收入弹性。",
        "falsified": "若泵占 CDU 总价很低或由系统商压价采购，应下调纯泵厂相对优先级。",
        "view": "优先作为补证和模型修正入口；证据增强前不对泵厂给无条件高弹性估值。",
        "risk": "公开报价样本可能来自普通工业冷却、矿机或非 AI rack CDU，污染极高。",
    },
    {
        "entity_key": "china_component_targets",
        "target_name": "飞龙股份 002536.SZ",
        "ticker": "002536.SZ",
        "market": "中国 A 股",
        "target_type": "company",
        "company_id": 233,
        "source_ref": "web_feilong_sina_20260701",
        "priority": "P1 重点补证",
        "quality": "强项目线索，收入确认偏弱",
        "support": "partially_supported",
        "exposure": "飞龙是本轮最直接的国产液冷泵标的：结构化表格列出 Sidecar/InRack CDU 和 InRow CDU 泵平台，媒体报道给出客户和项目线索，但数据中心收入仍需拆分。",
        "relative": "同实体内更像高弹性期权，不如英维克、申菱的系统收入确定，也比三花更直接暴露在泵环节。",
        "confirmed": "若公司公告或财报确认 AI 数据中心泵订单、交付收入和毛利改善，可把它从主题弹性升级为核心泵标的。",
        "falsified": "若 120 个项目仍停留在样品或小批量，或收入主要来自汽车/储能，降低交易优先级。",
        "view": "条件化看多但必须等收入确认；适合跟踪订单、客户验收、产线利用率和项目转批量。",
        "risk": "客户名称多为媒体和表格线索，且 2025 年液冷收入以新能源车和民用为主，容易出现 AI 口径污染。",
    },
    {
        "entity_key": "china_component_targets",
        "target_name": "英维克 002837.SZ",
        "ticker": "002837.SZ",
        "market": "中国 A 股",
        "target_type": "company",
        "company_id": 231,
        "source_ref": "web_envicool_air_liquid_cdu",
        "priority": "P1 系统商核心",
        "quality": "官方产品强，泵环节间接",
        "support": "supported",
        "exposure": "英维克强在机架级风液 CDU 和端到端温控系统，液冷泵更多体现在系统采购或集成能力，而不是纯泵制造。",
        "relative": "在中国系统商中确定性高于飞龙和南方泵业，但泵价值量占比需要从 CDU 总收入里拆出来。",
        "confirmed": "若液冷 CDU 收入、AI 客户交付和毛利率同步上行，可作为系统商优先标的。",
        "falsified": "若订单集中在非 AI 数据中心或泵外购占比较高，降低泵链条归因。",
        "view": "作为国产 CDU 系统商核心入口，适合与飞龙、申菱和高澜对照验证泵需求传导。",
        "risk": "系统商收入不能直接等同泵收入，客户名称和项目阶段需要公司公告复核。",
    },
    {
        "entity_key": "china_component_targets",
        "target_name": "申菱环境 301018.SZ",
        "ticker": "301018.SZ",
        "market": "中国 A 股",
        "target_type": "company",
        "company_id": 249,
        "source_ref": "web_shenling_liquid_cdu",
        "priority": "P1 系统商核心",
        "quality": "官方 CDU 能力强",
        "support": "supported",
        "exposure": "申菱公开 200-1800kW 液冷 CDU、AI 智算中心、高密度机柜和变频泵能力，是国产系统商中直接性较强的标的。",
        "relative": "比纯泵厂有更强客户交付入口，比三花等部件公司更贴近 CDU，但泵部件是否自研需要继续拆分。",
        "confirmed": "若公开中标、验收或财报确认高功率 CDU 批量交付，应提升优先级。",
        "falsified": "若产品展示强但收入缺乏数据中心项目兑现，保持观察而不按核心泵机会定价。",
        "view": "适合作为高功率 CDU 系统商主线，跟踪华为、运营商和智算中心招投标。",
        "risk": "系统集成业务可能受项目制节奏影响，收入波动大于标准部件。",
    },
    {
        "entity_key": "china_component_targets",
        "target_name": "高澜股份 300499.SZ",
        "ticker": "300499.SZ",
        "market": "中国 A 股",
        "target_type": "company",
        "company_id": 260,
        "source_ref": "local_zhongyuan_home_20260618",
        "priority": "P2 观察",
        "quality": "工业液冷强，AI 收入待拆",
        "support": "partially_supported",
        "exposure": "高澜在电力电子和数据中心液冷中有布局，若 AI 数据中心订单加速，可承接系统和水冷设备需求。",
        "relative": "确定性低于英维克、申菱，胜在工业热管理能力和客户迁移经验。",
        "confirmed": "若披露 AI 数据中心液冷收入和客户验收，可提高配置优先级。",
        "falsified": "若增长仍来自电力电子或储能，不能归入 AI CDU 泵主线。",
        "view": "作为国产热管理系统商二线弹性标的跟踪，不把泵作为唯一核心逻辑。",
        "risk": "数据中心液冷收入占比和客户阶段不透明。",
    },
    {
        "entity_key": "china_component_targets",
        "target_name": "同飞股份 300990.SZ",
        "ticker": "300990.SZ",
        "market": "中国 A 股",
        "target_type": "company",
        "company_id": 259,
        "source_ref": "local_zhongyuan_home_20260618",
        "priority": "P2 观察",
        "quality": "温控转型线索",
        "support": "partially_supported",
        "exposure": "同飞从工业温控转向储能、数据中心液冷和半导体温控，相关性在系统级温控而非单泵。",
        "relative": "比飞龙更偏温控系统，比英维克和申菱的公开 CDU 证据弱。",
        "confirmed": "若数据中心液冷订单、客户和收入占比清晰披露，纳入二线系统商篮子。",
        "falsified": "若收入仍主要来自储能或机床温控，剔除出 AI 液冷泵核心篮子。",
        "view": "用于验证国产温控公司能否从储能迁移到 AI 数据中心液冷。",
        "risk": "储能温控和数据中心液冷容易被混算。",
    },
    {
        "entity_key": "china_component_targets",
        "target_name": "三花智控 002050.SZ",
        "ticker": "002050.SZ",
        "market": "中国 A 股",
        "target_type": "company",
        "company_id": 279,
        "source_ref": "web_sanhua_ir_20251031",
        "priority": "P1 部件平台",
        "quality": "官方 IR 有布局，收入拆分不足",
        "support": "partially_supported",
        "exposure": "三花在阀、泵、换热器和控制器上有热管理部件能力，可能受益于 AIDC 液冷零部件国产化。",
        "relative": "比飞龙更平台化、客户资源更强，但纯泵弹性更稀释；需要和汽车热管理主业拆开。",
        "confirmed": "若 AIDC 液冷部件收入、客户、毛利率和产能扩张公开确认，可纳入核心部件平台。",
        "falsified": "若 AIDC 仍是战略描述且收入低，按主题映射而非业绩主线处理。",
        "view": "适合做液冷部件平台和汽车热管理迁移的高质量对照标的。",
        "risk": "汽车、人形机器人和制冷主业可能掩盖数据中心泵真实贡献。",
    },
    {
        "entity_key": "global_competition_stack",
        "target_name": "Vertiv Holdings VRT",
        "ticker": "VRT",
        "market": "美国",
        "target_type": "company",
        "company_id": 250,
        "target_url": "https://www.vertiv.com/",
        "source_ref": "web_vertiv_nvidia_gb200",
        "priority": "P1 全球系统商",
        "quality": "NVIDIA 参考架构强证据",
        "support": "supported",
        "exposure": "Vertiv 与 NVIDIA GB200 NVL72 电力和冷却参考架构绑定，代表全球系统商验证强度。",
        "relative": "在全球系统商中验证最强，但泵只是系统内部部件，单泵收入弹性低于系统总包。",
        "confirmed": "若 GB300/Rubin 新参考架构继续出现 Vertiv，并伴随订单和交付扩张，维持核心地位。",
        "falsified": "若新平台转向其他系统商或毛利受交付压力压缩，降低系统商溢价。",
        "view": "作为全球 AI 液冷系统商核心对照，用来判断中国系统商能否追赶。",
        "risk": "估值和数据中心电力设备周期可能大幅影响股价，不能只看泵。",
    },
    {
        "entity_key": "global_competition_stack",
        "target_name": "CoolIT Systems",
        "ticker": None,
        "market": "未上市",
        "target_type": "company",
        "target_url": "https://www.coolitsystems.com/",
        "source_ref": "web_coolit_chx2000",
        "priority": "P1 未上市核心参照",
        "quality": "NVIDIA 生态和产品强",
        "support": "supported",
        "exposure": "CoolIT CHx2000 和 NVIDIA 协作资料说明它是高密度 CDU 和冷板系统的重要参照。",
        "relative": "虽不可直接交易，但对判断 CDU 单位容量、交付能力和中国厂商差距最有价值。",
        "confirmed": "若继续公开 GB300/Rubin 对应产品和量产交付，作为全球 benchmark。",
        "falsified": "若交付节奏或成本不及预期，系统商扩产可能压缩行业溢价。",
        "view": "作为私有 benchmark 使用，帮助给上市系统商和泵厂估算技术差距。",
        "risk": "未上市公司财务不可得，无法直接验证收入和利润弹性。",
    },
    {
        "entity_key": "global_competition_stack",
        "target_name": "Schneider Electric / Motivair",
        "ticker": "SU.PA",
        "market": "欧洲",
        "target_type": "company",
        "target_url": "https://www.se.com/",
        "source_ref": "web_schneider_motivair_mw_cdu",
        "priority": "P1 全球系统商",
        "quality": "并购和产品均强",
        "support": "supported",
        "exposure": "Schneider 收购 Motivair 并推出 105kW-2.5MW CDU，可扩至 10MW 以上，体现电力加冷却平台化。",
        "relative": "比纯泵厂有更宽系统集成能力，但数据中心液冷收入在集团内需要拆分。",
        "confirmed": "若财报披露 Motivair 订单、产能和 AI 数据中心收入贡献，提升研究权重。",
        "falsified": "若并购整合慢或毛利被项目成本吞噬，降低平台溢价。",
        "view": "作为全球电力和冷却一体化龙头，对照 Vertiv 和中国系统商。",
        "risk": "集团多元化导致液冷泵贡献被稀释。",
    },
    {
        "entity_key": "global_competition_stack",
        "target_name": "Delta Electronics 2308.TW",
        "ticker": "2308.TW",
        "market": "中国台湾",
        "target_type": "company",
        "company_id": 264,
        "target_url": "https://www.deltaww.com/",
        "source_ref": "web_delta_cdu",
        "priority": "P1 台系系统商",
        "quality": "官方 CDU 能力强",
        "support": "supported",
        "exposure": "台达公开液冷 CDU 和电源能力，处在 AI 服务器电力与热管理交叉位置。",
        "relative": "比多数中国 A 股系统商更接近台系服务器供应链，但泵价值仍需从 CDU 和电源组合里拆分。",
        "confirmed": "若 GB300/Rubin 或 CSP 项目披露台达 CDU 交付，维持高优先级。",
        "falsified": "若液冷收入小于电源主业且缺少客户确认，降低泵链条权重。",
        "view": "作为台系供应链核心对照标的，用来校验中国厂商进入北美 CSP 的难度。",
        "risk": "台达业务多元，股价可能主要反映电源和自动化而非液冷泵。",
    },
    {
        "entity_key": "reliability_control_barrier",
        "target_name": "Johnson Electric 德昌电机 0179.HK",
        "ticker": "0179.HK",
        "market": "港股",
        "target_type": "company",
        "target_url": "https://www.johnsonelectric.com/",
        "source_ref": "web_johnson_dc_pump",
        "priority": "P1 规格样本",
        "quality": "官方泵规格直接",
        "support": "supported",
        "exposure": "德昌电机公开 DCP 数据中心液冷泵规格，是少数能直接看到流量、压差、功率、材质和通信接口的泵厂。",
        "relative": "比飞龙的客户线索更规范，但中国 A 股可交易弹性较低；适合做全球泵规格 benchmark。",
        "confirmed": "若披露数据中心客户、收入和批量交付，可从规格样本升级为核心泵标的。",
        "falsified": "若产品停留在样本展示或小批量，维持 benchmark 而非交易主线。",
        "view": "用于校准 AI 数据中心液冷泵真实规格门槛。",
        "risk": "公司跨汽车和消费电机，数据中心业务收入占比不可得。",
    },
    {
        "entity_key": "reliability_control_barrier",
        "target_name": "Moog MOG.A",
        "ticker": "MOG.A",
        "market": "美国",
        "target_type": "company",
        "target_url": "https://www.moog.com/",
        "source_ref": "web_moog_liquid_pumps",
        "priority": "P2 技术路线",
        "quality": "磁力泵差异化",
        "support": "supported",
        "exposure": "Moog 磁力泵强调无旋转密封和更少泄漏点，直接对应 AI 数据中心零泄漏和长期可靠性痛点。",
        "relative": "技术差异强于通用水泵，但数据中心收入占比和客户验证仍需补。",
        "confirmed": "若被主流 CDU 或 OEM 选用并披露量产，技术路线可提升评分。",
        "falsified": "若高成本或交付限制导致只用于小众场景，降低商业化权重。",
        "view": "作为无轴封和磁力泵路线观察标的。",
        "risk": "精密运动控制主业可能稀释液冷泵对估值的影响。",
    },
    {
        "entity_key": "global_competition_stack",
        "target_name": "Grundfos 格兰富",
        "ticker": None,
        "market": "未上市",
        "target_type": "company",
        "target_url": "https://www.grundfos.com/",
        "source_ref": "web_grundfos_datacenters",
        "priority": "P2 Benchmark",
        "quality": "泵能力强，客户绑定弱",
        "support": "partially_supported",
        "exposure": "格兰富是全球泵龙头，数据中心智能泵和 IT cooling 能力强，但公开客户绑定不如系统商。",
        "relative": "适合做传统泵厂 benchmark，不适合直接当 NVIDIA/Google 供货证据。",
        "confirmed": "若公开具体 CDU 客户、AI 数据中心项目和二次侧泵规格，提升评分。",
        "falsified": "若业务主要在一次侧或 HVAC，降低 CDU 泵归因。",
        "view": "用于比较中国泵厂在效率、控制和可靠性上的差距。",
        "risk": "未上市且业务极广，财务弹性不可直接映射。",
    },
    {
        "entity_key": "global_competition_stack",
        "target_name": "Wilo 威乐",
        "ticker": None,
        "market": "未上市",
        "target_type": "company",
        "target_url": "https://wilo.com/",
        "source_ref": "web_wilo_datacenters",
        "priority": "P2 Benchmark",
        "quality": "数据中心泵叙事明确",
        "support": "partially_supported",
        "exposure": "Wilo 公开服务数据中心 CDU、直连芯片和浸没式冷却，材料兼容和 mission-critical 可靠性是重点。",
        "relative": "比多数中国传统泵厂的公开数据中心材料更完整，但客户绑定仍弱。",
        "confirmed": "若公开 AI 数据中心项目和 CDU 二次侧泵交付，提升优先级。",
        "falsified": "若主要应用停留在设施侧循环泵，降低核心评分。",
        "view": "作为传统泵厂进入 AI 数据中心的路线对照。",
        "risk": "未上市且客户披露有限。",
    },
    {
        "entity_key": "global_competition_stack",
        "target_name": "Xylem XYL",
        "ticker": "XYL",
        "market": "美国",
        "target_type": "company",
        "target_url": "https://www.xylem.com/",
        "source_ref": "web_xylem_datacenters",
        "priority": "P3 设施侧观察",
        "quality": "水系统强，二次侧泵弱",
        "support": "weak",
        "exposure": "Xylem 更偏 hydronic cooling、水处理、过滤和监测，适合设施侧水系统观察，不是本轮 CDU 二次侧泵核心。",
        "relative": "在泵和水处理能力上强，但和 AI rack CDU 泵的直接性低于 Moog、德昌和系统商。",
        "confirmed": "若拿到 AI CDU 二次侧泵项目或 OEM 客户，再提升优先级。",
        "falsified": "若新增订单主要是设施水处理，留作外围水系统标的。",
        "view": "作为一次侧和水处理需求的外围观察。",
        "risk": "把一次侧水系统误当 CDU pump 会高估投资弹性。",
    },
    {
        "entity_key": "china_component_targets",
        "target_name": "南方泵业/中金环境 300145.SZ",
        "ticker": "300145.SZ",
        "market": "中国 A 股",
        "target_type": "company",
        "company_id": 241,
        "source_ref": "local_fangzheng_ai_hardware_20260529",
        "priority": "P3 补证观察",
        "quality": "研报线索，官方证据待补",
        "support": "weak",
        "exposure": "方正证券提到南方泵业 CHL/CHM/CHLF 用于数据中心液冷模块，但目前缺少客户、收入和高功率 CDU 泵公开确认。",
        "relative": "比飞龙和德昌更缺少具体 AI 数据中心泵规格，适合放在观察篮子。",
        "confirmed": "若公司披露 AI 数据中心 CDU 泵项目、订单和产品规格，可提升到 P2。",
        "falsified": "若应用主要是通用水泵或设施侧循环，剔除核心篮子。",
        "view": "作为传统泵厂国产替代观察，不做核心结论。",
        "risk": "传统泵产品和数据中心二次侧泵容易口径混淆。",
    },
    {
        "entity_key": "china_component_targets",
        "target_name": "大元泵业 603757.SH",
        "ticker": "603757.SH",
        "market": "中国 A 股",
        "target_type": "company",
        "company_id": 243,
        "source_ref": "xlsx_pump_company_universe",
        "priority": "P3 补证观察",
        "quality": "表格线索，客户待补",
        "support": "weak",
        "exposure": "结构化表格把大元泵业列为 IDC、储能等多领域液冷泵覆盖公司，但缺少 AI CDU 二次侧客户确认。",
        "relative": "直接性低于飞龙，公开规格低于德昌，适合等待公告。",
        "confirmed": "若公司披露数据中心液冷泵型号、客户和收入，提升观察权重。",
        "falsified": "若主要是储能和普通工业泵，移出 AI 液冷泵主线。",
        "view": "作为传统泵厂国产替代的低确认度观察。",
        "risk": "储能和 IDC 口径混合会高估 AI 数据中心弹性。",
    },
    {
        "entity_key": "contamination_and_falsification",
        "target_name": "汉宇集团 300403.SZ",
        "ticker": "300403.SZ",
        "market": "中国 A 股",
        "target_type": "company",
        "target_url": "https://www.hanyu-group.com/",
        "source_ref": "xlsx_auto_transfer_barrier",
        "priority": "P4 排除/观察",
        "quality": "汽车和家电泵迁移待证",
        "support": "weak",
        "exposure": "汉宇可作为电子水泵和电机泵迁移观察，但本轮没有看到 AI 数据中心 CDU 泵直接证据。",
        "relative": "与飞龙相比缺少数据中心泵项目和客户线索，与德昌相比缺少公开规格。",
        "confirmed": "只有披露 AI 数据中心泵型号、客户验证和收入后才进入核心篮子。",
        "falsified": "若仍是家电、汽车或储能泵，继续作为排除项。",
        "view": "不作为当前推荐标的，仅用于提醒不要把车端泵能力机械外推。",
        "risk": "主题交易可能把汽车水泵误读为 AI 数据中心泵。",
    },
    {
        "entity_key": "contamination_and_falsification",
        "target_name": "江苏雷利 300660.SZ",
        "ticker": "300660.SZ",
        "market": "中国 A 股",
        "target_type": "company",
        "target_url": "https://www.leili-motor.com/",
        "source_ref": "xlsx_auto_transfer_barrier",
        "priority": "P4 排除/观察",
        "quality": "电机和泵控迁移待证",
        "support": "weak",
        "exposure": "江苏雷利可观察电机、泵控和小型泵能力迁移，但本轮无公开 AI CDU 泵客户确认。",
        "relative": "更像泵控和电机迁移线索，不如飞龙、德昌直接。",
        "confirmed": "若出现数据中心液冷泵电机或控制器订单，再纳入部件观察。",
        "falsified": "若只服务汽车、家电或储能，则不进入核心液冷泵机会。",
        "view": "作为泵控迁移观察，不作为当前液冷泵核心标的。",
        "risk": "业务跨度大，AI 数据中心收入可能很小。",
    },
    {
        "entity_key": "contamination_and_falsification",
        "target_name": "凌霄泵业 002884.SZ",
        "ticker": "002884.SZ",
        "market": "中国 A 股",
        "target_type": "company",
        "target_url": "https://www.lingxiao.com/",
        "source_ref": "xlsx_pump_company_universe",
        "priority": "P4 排除/观察",
        "quality": "传统泵待证",
        "support": "weak",
        "exposure": "凌霄泵业可作传统泵迁移观察，但本轮证据没有支持 AI rack CDU 二次侧泵供货。",
        "relative": "低于南方泵业、大元和飞龙的公开线索强度。",
        "confirmed": "若公开数据中心液冷泵型号和客户，再重新评分。",
        "falsified": "若仍为传统民用或工业泵，不纳入核心机会。",
        "view": "仅保留为排除性观察，防止主题扩散过度。",
        "risk": "传统泵主题可能被市场误炒。",
    },
    {
        "entity_key": "global_competition_stack",
        "target_name": "Eaton / Boyd Thermal",
        "ticker": "ETN",
        "market": "美国",
        "target_type": "company",
        "target_url": "https://www.eaton.com/",
        "source_ref": "web_eaton_cdu",
        "priority": "P2 CDU 技术对照",
        "quality": "CDU 页面直接",
        "support": "supported",
        "exposure": "Eaton/Boyd CDU 资料强调无轴封 N+1 冗余泵、过滤和压力测试，说明高可靠 CDU 竞争焦点。",
        "relative": "对泵可靠性有参考价值，但集团层面液冷收入占比和客户绑定需拆分。",
        "confirmed": "若披露 GB300/Rubin 或 CSP 项目交付，提升评分。",
        "falsified": "若液冷只是产品目录而缺乏项目收入，保留为技术对照。",
        "view": "作为无轴封冗余泵和 CDU 品控 benchmark。",
        "risk": "集团业务多元，单一液冷线索对估值影响有限。",
    },
    {
        "entity_key": "customer_validation_matrix",
        "target_name": "NVIDIA 液冷平台验证入口",
        "ticker": "NVDA",
        "market": "美国",
        "target_type": "external_watch",
        "company_id": 150,
        "target_url": "https://www.nvidia.com/en-us/data-center/gb300-nvl72/",
        "source_ref": "web_nvidia_gb300_nvl72",
        "priority": "P0 监控入口",
        "quality": "平台需求确认",
        "support": "supported",
        "exposure": "NVIDIA 官方确认 GB300/GB200 全液冷平台，是泵需求的上游触发，不代表某泵厂供货。",
        "relative": "它不是泵供应商，但所有供应链判断都要回到 NVIDIA 平台节奏和参考架构。",
        "confirmed": "若 GB300/Rubin rack 出货、参考架构和合格供应商名单公开，带动链条确认。",
        "falsified": "若平台延后或转向不同冷却架构，压低泵需求弹性。",
        "view": "作为客户验证矩阵的第一监控入口。",
        "risk": "平台需求确定不等于单个泵厂订单确定。",
    },
    {
        "entity_key": "customer_validation_matrix",
        "target_name": "Google TPU 液冷验证入口",
        "ticker": "GOOGL",
        "market": "美国",
        "target_type": "external_watch",
        "company_id": 198,
        "target_url": "https://blog.google/innovation-and-ai/infrastructure-and-cloud/google-cloud/ironwood-tpu-age-of-inference/",
        "source_ref": "web_google_ironwood_tpu",
        "priority": "P0 监控入口",
        "quality": "平台需求确认，供应商待证",
        "support": "supported",
        "exposure": "Google Ironwood TPU 和冷却演进材料确认 ASIC 集群液冷需求，但泵和 CDU 供应商公开披露不足。",
        "relative": "与 NVIDIA 相比供应链公开度更低，适合作为验证债最高的客户入口。",
        "confirmed": "若 OCP Deschutes、Google 数据中心或 OEM 文件披露供应商，提升对应公司权重。",
        "falsified": "若 Google 自研或既有供应链封闭，外部泵厂机会受限。",
        "view": "作为客户验证矩阵中的高价值补证入口。",
        "risk": "供应链保密导致上市公司映射容易失真。",
    },
    {
        "entity_key": "customer_validation_matrix",
        "target_name": "华为 Atlas 液冷验证入口",
        "ticker": None,
        "market": "中国",
        "target_type": "external_watch",
        "company_id": 35,
        "target_url": "https://www.huawei.com/en/news/2025/9/hc-superpod-innovation",
        "source_ref": "web_huawei_atlas_a3_superpod",
        "priority": "P0 监控入口",
        "quality": "平台需求确认，部件待证",
        "support": "supported",
        "exposure": "华为 Atlas 900 A3 SuperPoD 出货确认国产 AI 集群需求，但泵、CDU 和冷板供应商公开证据不足。",
        "relative": "对中国 A 股系统商最重要，但也最容易被传闻污染。",
        "confirmed": "若华为、超聚变、运营商或中标公告披露液冷 CDU 和泵供应商，快速重排中国标的。",
        "falsified": "若供应链自供或未披露导致外部收入不可验证，降低国产链打分。",
        "view": "作为中国客户验证矩阵的核心补证入口。",
        "risk": "任何未公开客户名的传闻都不得直接进入核心评分。",
    },
]


def target_data_points(target: dict[str, Any]) -> list[dict[str, Any]]:
    source = SOURCE_BY_REF[target["source_ref"]]
    return [
        {
            "metric_name": "标的暴露口径",
            "metric_category": "target_exposure",
            "period": AS_OF_DATE,
            "as_of_date": AS_OF_DATE,
            "value_text": target["exposure"],
            "unit": "说明",
            "source_title": source["title"],
            "source_publisher": source["publisher"],
            "source_url": source.get("url"),
            "source_excerpt": source["excerpt"],
            "evidence_ref_uri": f"source_ref:{target['source_ref']}",
            "data_quality_label": target["quality"],
            "direction": "positive" if target["support"] in {"supported", "partially_supported"} else "mixed",
            "credibility_weight": 0.86 if target["support"] == "supported" else 0.68 if target["support"] == "partially_supported" else 0.52,
            "numeric_weight": 0.8,
        },
        {
            "metric_name": "同实体内比较",
            "metric_category": "relative_preference",
            "period": AS_OF_DATE,
            "as_of_date": AS_OF_DATE,
            "value_text": target["relative"],
            "unit": "说明",
            "source_title": source["title"],
            "source_publisher": source["publisher"],
            "source_url": source.get("url"),
            "source_excerpt": source["excerpt"],
            "evidence_ref_uri": f"source_ref:{target['source_ref']}",
            "data_quality_label": "人工复核比较",
            "direction": "mixed",
            "credibility_weight": 0.72,
            "numeric_weight": 0.65,
        },
        {
            "metric_name": "证实后研究动作",
            "metric_category": "confirmed_action",
            "period": AS_OF_DATE,
            "as_of_date": AS_OF_DATE,
            "value_text": target["confirmed"],
            "unit": "动作",
            "source_title": source["title"],
            "source_publisher": source["publisher"],
            "source_url": source.get("url"),
            "source_excerpt": source["excerpt"],
            "evidence_ref_uri": f"source_ref:{target['source_ref']}",
            "data_quality_label": "条件化建议",
            "direction": "positive",
            "credibility_weight": 0.7,
            "numeric_weight": 0.6,
        },
        {
            "metric_name": "证伪后研究动作",
            "metric_category": "falsified_action",
            "period": AS_OF_DATE,
            "as_of_date": AS_OF_DATE,
            "value_text": target["falsified"],
            "unit": "动作",
            "source_title": source["title"],
            "source_publisher": source["publisher"],
            "source_url": source.get("url"),
            "source_excerpt": source["excerpt"],
            "evidence_ref_uri": f"source_ref:{target['source_ref']}",
            "data_quality_label": "条件化建议",
            "direction": "negative",
            "credibility_weight": 0.7,
            "numeric_weight": 0.6,
        },
    ]


for target in TARGET_DEFS:
    if target["entity_key"] in THEORY_RESEARCH_ENTITY_KEYS:
        continue
    for point in target_data_points(target):
        add_fact(
            target["entity_key"],
            target["source_ref"],
            f"{target['target_name']} - {point['metric_name']}",
            point["value_text"],
            unit=point["unit"],
            excerpt=point["source_excerpt"],
            role=SOURCE_BY_REF[target["source_ref"]].get("policy_evidence_role", "core_evidence"),
        )


ENTITY_CONFIGS: list[dict[str, Any]] = [
    {
        "key": "product_boundary_cdu_pump",
        "display_name": "AI 数据中心液冷泵产品边界",
        "description": "限定 CDU 内部或 TCS 二次侧循环泵、泵控、冗余、材料兼容和可靠性，不把一次侧冷水系统、汽车电子水泵、储能热管理泵混入核心口径。",
        "score": 83,
        "grade": "B",
        "coverage": 0.82,
        "confidence": 0.78,
        "maturation": "scoring_ready",
        "priority": "high_priority_for_scoring",
        "evidence": [
            "web_ocp_l_l_cdu_method",
            "web_ocp_tcs_manifold",
            "web_ul_cdu_certification",
            "xlsx_vehicle_vs_server_pump",
            "xlsx_auto_transfer_barrier",
            "local_west_cdu_pump_20260201",
            "web_supermicro_inrack_cdu",
            "web_supermicro_inrow_cdu",
        ],
        "factor_notes": {
            "demand.application_intensity_change": (84, "从风冷到冷板液冷后，泵从辅助部件变成控制流量、压差、泄漏和冗余的核心运行件。"),
            "supply.substitution_barrier": (86, "汽车水泵、储能泵和普通工业泵只能迁移部分电机和密封能力，无法直接覆盖 8760 小时、零泄漏和 CDU 控制耦合。"),
            "supply.raw_policy_constraint": (73, "标准、认证和润湿材料兼容性是隐性约束，2024 OCP 标准偏旧但仍定义边界。"),
            "supply.supplier_structure_bucket": (76, "标准化使系统商、泵厂和 OEM 分工更清晰，供应商结构不会只有 A 股研报标的。"),
            "demand.output_consumption_proxy": (78, "泵需求来自高功率 rack 的流量和压头要求，不来自泛液冷概念。"),
        },
    },
    {
        "key": "demand_tam_sam_som",
        "display_name": "CDU 液冷泵需求与 TAM/SAM/SOM",
        "description": "把 NVIDIA、Google、华为平台液冷需求、CDU 价值量和 pump 市场定义拆开，防止把整套 CDU 或液冷系统收入直接外推成泵收入。",
        "score": 81,
        "grade": "B",
        "coverage": 0.79,
        "confidence": 0.73,
        "maturation": "scoring_ready",
        "priority": "high_priority_for_scoring",
        "evidence": [
            "web_nvidia_gb300_nvl72",
            "web_nvidia_gb200_nvl72",
            "web_google_ironwood_tpu",
            "web_huawei_atlas_a3_superpod",
            "local_zhongtai_liquid_20260528",
            "local_dongwu_liquid_20260626",
            "local_guangfa_liquid_20260530",
            "local_guohai_gpu_asic_20251224",
            "web_precedence_cdu_pumps_market",
        ],
        "factor_notes": {
            "demand.output_consumption_proxy": (88, "GB200/GB300、Ironwood 和 Atlas SuperPoD 都提高液冷流量与冗余需求，但泵数量要按 CDU 架构而不是机柜数线性估算。"),
            "demand.customer_capex_capacity_signal": (84, "北美 CSP 和国产 AI 集群资本开支提供需求背景，但客户项目确认度分化很大。"),
            "demand.application_intensity_change": (86, "GPU/ASIC/TPU rack 功耗从百 kW 向数百 kW 迁移，泵功率、压头和控制精度同步上行。"),
            "signal.material_price_momentum": (67, "公开价格证据弱，CDU 价值量较明确但 pump ASP 不透明，因此价格因子保守评分。"),
            "supply.capacity_event_12m": (72, "系统商扩产和 CDU 新品证明交付能力在扩张，但纯 pump 产能瓶颈还缺少订单级证据。"),
        },
    },
    {
        "key": "customer_validation_matrix",
        "display_name": "NVIDIA/Google/华为客户验证矩阵",
        "description": "把平台液冷需求、系统商 reference design、CDU 交付、泵厂直接供货和灰源线索分层，严格防止把生态参与写成客户供货。",
        "score": 78,
        "grade": "B",
        "coverage": 0.76,
        "confidence": 0.70,
        "maturation": "scoring_ready",
        "priority": "high_priority_for_scoring",
        "evidence": [
            "web_nvidia_gb300_nvl72",
            "web_nvidia_ocp_gb200",
            "web_vertiv_nvidia_gb200",
            "web_coolit_chx2000",
            "web_coolit_nvidia",
            "web_google_ironwood_tpu",
            "web_google_arpae_cooling",
            "web_huawei_atlas_a3_superpod",
            "web_envicool_air_liquid_cdu",
            "web_shenling_liquid_cdu",
            "web_feilong_sina_20260701",
        ],
        "factor_notes": {
            "demand.customer_capex_capacity_signal": (85, "三大平台需求均已确认，系统商验证强于纯泵厂验证。"),
            "supply.supplier_structure_bucket": (80, "NVIDIA 公开链条更清楚，Google 和华为供应商披露更封闭，验证债不同。"),
            "demand.application_intensity_change": (82, "客户平台从芯片到 rack 决定泵规格，而不是泵厂单方面定义需求。"),
            "supply.substitution_barrier": (75, "一旦客户采用系统商打包交付，独立泵厂议价和可见度会下降。"),
            "supply.capacity_event_12m": (72, "Vertiv、CoolIT、Motivair 扩张表明系统层供给在加速，但单泵确认仍不足。"),
        },
    },
    {
        "key": "global_competition_stack",
        "display_name": "全球 CDU 泵和液冷系统竞争格局",
        "description": "比较 Vertiv、CoolIT、Schneider/Motivair、Delta、Eaton/Boyd、Grundfos、Wilo、Xylem、Moog、德昌等不同层级参与者。",
        "score": 77,
        "grade": "B",
        "coverage": 0.78,
        "confidence": 0.72,
        "maturation": "scoring_ready",
        "priority": "high_priority_for_scoring",
        "evidence": [
            "xlsx_pump_company_universe",
            "xlsx_global_cdu_pump_players",
            "web_vertiv_nvidia_gb200",
            "web_coolit_chx2000",
            "web_schneider_motivair_mw_cdu",
            "web_delta_cdu",
            "web_eaton_cdu",
            "web_grundfos_datacenters",
            "web_wilo_datacenters",
            "web_moog_liquid_pumps",
            "web_johnson_dc_pump",
        ],
        "factor_notes": {
            "supply.supplier_structure_bucket": (86, "竞争不是纯泵厂列表，而是系统商、OEM、传统泵厂、磁力泵厂和中国部件商多层竞争。"),
            "supply.capacity_event_12m": (78, "CoolIT、Motivair、Supermicro 等产品容量上行，系统供给正在扩张。"),
            "supply.substitution_barrier": (76, "系统商打包和无轴封磁力泵会改变传统泵厂进入方式。"),
            "demand.customer_capex_capacity_signal": (74, "全球头部客户需求确定，但各家客户名单公开度不同。"),
            "signal.material_price_momentum": (61, "系统容量规格公开，成交价格和 pump ASP 缺少一手证据。"),
        },
    },
    {
        "key": "china_component_targets",
        "display_name": "中国上市公司承接能力与财务弹性",
        "description": "覆盖飞龙股份、英维克、申菱环境、高澜股份、同飞股份、三花智控、南方泵业、大元泵业、德昌电机等标的，区分系统商、部件商、纯泵厂和迁移观察。",
        "score": 76,
        "grade": "B",
        "coverage": 0.75,
        "confidence": 0.68,
        "maturation": "scoring_limited",
        "priority": "medium_priority_for_followup",
        "evidence": [
            "xlsx_feilong_product_layout",
            "web_feilong_sina_20260701",
            "web_envicool_air_liquid_cdu",
            "web_shenling_liquid_cdu",
            "web_sanhua_ir_20251031",
            "web_sanhua_liquid_award",
            "local_fangzheng_ai_hardware_20260529",
            "local_zhongyuan_home_20260618",
            "web_johnson_dc_pump",
        ],
        "factor_notes": {
            "supply.capacity_event_12m": (80, "飞龙平台、申菱 CDU 和英维克 CDU 显示国产链有产品承接，但订单和收入仍需拆分。"),
            "supply.supplier_structure_bucket": (78, "中国标的分成系统商、泵厂、阀泵换热器平台和传统泵迁移，不能按一个篮子处理。"),
            "demand.customer_capex_capacity_signal": (76, "客户映射集中在英维克、申菱、高澜、台达、Vertiv 等系统商，下游确认强度不均。"),
            "supply.substitution_barrier": (74, "飞龙和德昌更接近泵环节，三花、英维克、申菱更接近系统或部件平台，收入弹性不同。"),
            "signal.material_price_momentum": (58, "中国标的缺少可验证 pump ASP 和毛利率改善，价格因子保守。"),
        },
    },
    {
        "key": "price_value_chain",
        "display_name": "价格体系、CDU 拆分和泵价值捕获",
        "description": "拆解 GB200/GB300/Rubin、Google TPU 的液冷组件价值，强调 CDU 价格不能等于泵价格，泵价值取决于冗余、压头、控制和材料兼容。",
        "score": 72,
        "grade": "B",
        "coverage": 0.70,
        "confidence": 0.64,
        "maturation": "scoring_limited",
        "priority": "medium_priority_for_followup",
        "evidence": [
            "local_zhongtai_liquid_20260528",
            "local_dongwu_liquid_20250126",
            "web_liquidstack_cdu_selection",
            "web_coolit_chx2000",
            "web_schneider_motivair_mw_cdu",
            "web_precedence_cdu_pumps_market",
            "web_supermicro_inrow_cdu",
        ],
        "factor_notes": {
            "signal.material_price_momentum": (66, "CDU 分项价值较清楚，但 pump ASP、冗余泵 BOM 和成交折扣缺乏一手数据。"),
            "demand.output_consumption_proxy": (79, "rack 功耗和 CDU 容量决定泵数量和功率等级，是收入测算的底层驱动。"),
            "supply.substitution_barrier": (70, "高端泵价值来自可靠性和控制，不是普通水泵 ASP。"),
            "demand.customer_capex_capacity_signal": (73, "AI factory 和 CSP capex 支撑价值链扩容，但价格兑现依赖订单。"),
            "supply.supplier_structure_bucket": (69, "系统商可能捕获更多价值，纯泵厂只捕获 CDU 内部一部分。"),
        },
    },
    {
        "key": "reliability_control_barrier",
        "display_name": "可靠性、泵控、泄漏和运维壁垒",
        "description": "研究 AI 数据中心液冷泵是否具备 10 年级寿命、N+1 冗余、无轴封、材料兼容、压头、流量精度、监控协议和泄漏保护。",
        "score": 82,
        "grade": "B",
        "coverage": 0.81,
        "confidence": 0.76,
        "maturation": "scoring_ready",
        "priority": "high_priority_for_scoring",
        "evidence": [
            "web_ocp_l_l_cdu_method",
            "web_eaton_cdu",
            "web_moog_liquid_pumps",
            "web_johnson_dc_pump",
            "web_supermicro_inrow_cdu",
            "web_shenling_liquid_cdu",
            "xlsx_auto_transfer_barrier",
            "xlsx_vehicle_vs_server_pump",
        ],
        "factor_notes": {
            "supply.substitution_barrier": (88, "零泄漏、N+1、材料兼容、10 年寿命和 CDU 控制联动让普通泵迁移难度很高。"),
            "supply.capacity_event_12m": (77, "德昌、Moog、Eaton、申菱等公开产品显示高可靠供给存在，但量产项目仍需补证。"),
            "demand.application_intensity_change": (83, "rack 功耗上行让泵从低功率辅助件升级为高压头、高流量、高冗余运行件。"),
            "supply.raw_policy_constraint": (79, "OCP、UL、Redfish/SNMP 和材料兼容共同构成准入门槛。"),
            "demand.output_consumption_proxy": (74, "泵的真实需求量取决于 rack CDU 或 row CDU 架构和冗余设计。"),
        },
    },
    {
        "key": "contamination_and_falsification",
        "display_name": "汽车/储能/工业泵口径污染与证伪风险",
        "description": "专门审查把汽车电子水泵、储能泵、普通工业泵、一次侧水系统和二级市场传闻错误映射成 AI 数据中心液冷泵的风险。",
        "score": 68,
        "grade": "C",
        "coverage": 0.72,
        "confidence": 0.70,
        "maturation": "scoring_limited",
        "priority": "medium_priority_for_followup",
        "evidence": [
            "xlsx_vehicle_vs_server_pump",
            "xlsx_auto_transfer_barrier",
            "xlsx_feilong_product_layout",
            "web_feilong_sina_20260701",
            "web_sanhua_eastmoney_20260701",
            "local_dongwu_rubin_minutes",
            "web_ocp_l_l_cdu_method",
            "web_xylem_datacenters",
        ],
        "factor_notes": {
            "supply.substitution_barrier": (82, "口径污染本身说明替代壁垒高，迁移必须验证功率、寿命和客户。"),
            "signal.material_price_momentum": (52, "很多价格或收入线索来自非 AI 场景，不能支撑高分。"),
            "demand.customer_capex_capacity_signal": (62, "客户需求强但不等于任意汽车或储能泵企业都能进入。"),
            "supply.supplier_structure_bucket": (70, "真正进入客户通常经系统商或 OEM，纯传闻标的需要降级。"),
            "supply.capacity_event_12m": (58, "如果没有公告、批量交付和收入确认，产能线索只能作观察。"),
        },
    },
]


ENTITY_ACTIONS: dict[str, dict[str, str]] = {
    "product_boundary_cdu_pump": {
        "confirmed": "若公司产品明确落在 CDU 内部或 TCS 二次侧循环泵，并满足 OCP/UL、N+1、材料兼容和泄漏保护要求，才纳入 AI 数据中心泵可比池。",
        "falsified": "若证据只对应一次侧冷水系统、普通建筑水泵、车端泵或储能泵，即使写了液冷，也从核心机会排序中剔除。",
        "monitor": "OCP/UL 认证、TCS 二次侧边界、N+1 冗余、材料兼容和泄漏保护。",
    },
    "demand_tam_sam_som": {
        "confirmed": "若 GB300/Rubin、TPU 和国产集群出货上修，同时 CDU 容量和 pump BOM 拆分可核验，上调泵环节 SAM/SOM。",
        "falsified": "若只看到整套液冷或 CDU 总价，拿不到泵数量、泵 ASP 和冗余设计，必须下调纯泵厂收入弹性。",
        "monitor": "AI rack 出货、CDU 容量、pump BOM、泵 ASP 和液冷渗透率。",
    },
    "customer_validation_matrix": {
        "confirmed": "若 NVIDIA、Google 或华为链条出现系统商交付、CDU 型号、泵规格和供应商名称的公开闭环，重排对应标的优先级。",
        "falsified": "若只有生态合作、送样、二级市场传闻或间接客户表述，不得写成客户供货，只保留验证债。",
        "monitor": "客户平台资料、reference design、ODM/OEM 公告、招投标和供应商名单。",
    },
    "global_competition_stack": {
        "confirmed": "若 Vertiv、CoolIT、Schneider/Motivair、Delta、Eaton/Boyd 等继续获得 GB300/Rubin 或 CSP 项目，系统商确定性优先于纯泵叙事。",
        "falsified": "若公开证据只能证明产品目录，不能证明 AI rack 交付、客户和收入，全球参与者降为技术参照。",
        "monitor": "全球系统商订单、CDU 量产、泵厂 OEM 合作和新平台 reference architecture。",
    },
    "china_component_targets": {
        "confirmed": "若飞龙、英维克、申菱、三花等披露 AI 数据中心订单、客户验收、收入占比和毛利响应，按系统商/纯泵/部件平台分层上调。",
        "falsified": "若收入仍主要来自汽车、储能、工业温控或产品展示，不能把主题映射升级为核心标的。",
        "monitor": "A 股公告、互动易、财报分部、客户验收、订单金额和毛利率。",
    },
    "price_value_chain": {
        "confirmed": "若拆出 CDU 内部泵数量、冗余方案、pump ASP、控制器和采购价，可重新计算泵厂价值捕获并校正目标排序。",
        "falsified": "若泵占 CDU 总价低、被系统商压价采购或价值主要留在冷板/快接/系统集成，降低纯泵厂权重。",
        "monitor": "CDU BOM、pump ASP、冗余泵数量、压头流量规格和采购模式。",
    },
    "reliability_control_barrier": {
        "confirmed": "若泵厂公开 MTBF、零泄漏、无轴封、流量精度、监控协议和数据中心客户验收，技术壁垒可转化为议价和评分。",
        "falsified": "若规格停留在通用工业泵或车端泵参数，不能证明 8760 小时数据中心场景可靠性，降低壁垒分。",
        "monitor": "MTBF、密封结构、流量精度、监控协议、故障切换和运维案例。",
    },
    "contamination_and_falsification": {
        "confirmed": "若公开证据能把车端、储能、工业泵与 AI CDU 二次侧泵逐项区分，保留可迁移公司但降低未验证收入权重。",
        "falsified": "若公司无法给出 AI 数据中心泵型号、客户、订单或收入，且只靠汽车/储能泵外推，直接移出核心排序。",
        "monitor": "业务口径、产品型号、客户场景、收入来源和传闻到公告的验证路径。",
    },
}


def _stable_offset(value: str, size: int) -> int:
    if size <= 0:
        return 0
    return sum(ord(char) for char in value) % size


def facts_for(entity_key: str, refs: list[str], limit: int = 6, factor_code: str | None = None) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for ref in refs:
        for fact in FACTS:
            if fact["entity_key"] == entity_key and fact["source_ref"] == ref:
                selected.append(fact)
                break
    if len(selected) < limit:
        for fact in FACTS:
            if fact["entity_key"] == entity_key and fact not in selected:
                selected.append(fact)
            if len(selected) >= limit:
                break
    if factor_code and selected:
        offset = _stable_offset(f"{entity_key}:{factor_code}", len(selected))
        selected = selected[offset:] + selected[:offset]
    return selected[:limit]


def make_research_data_points(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    research_limit = 20 if cfg["key"] in THEORY_RESEARCH_ENTITY_KEYS else 12
    for index, fact in enumerate(facts_for(cfg["key"], cfg["evidence"], limit=research_limit), start=1):
        source = SOURCE_BY_REF[fact["source_ref"]]
        category = "definition_boundary"
        if cfg["key"] == "price_value_chain":
            category = "value_chain"
            if "价格" in fact["metric"] or "报价" in fact["metric"]:
                category = "methodology"
        elif any(token in fact["metric"] for token in ["寿命", "泄漏", "扬程", "流量", "冗余", "材料", "控制", "清洁"]):
            category = "methodology"
        rows.append(
            {
                "source_ref": fact["source_ref"],
                "data_point_title": f"{cfg['display_name']}：{fact['metric']}",
                "research_category": category,
                "metric": fact["metric"],
                "period": fact.get("period") or AS_OF_DATE,
                "as_of_date": fact.get("as_of_date") or AS_OF_DATE,
                "value_num": fact.get("value_num"),
                "value_text": fact.get("value_text"),
                "unit": fact.get("unit") or "事实",
                "source_excerpt": fact["source_excerpt"],
                "source_context": f"{source['publisher']}《{source['title']}》用于本实体的口径、定义或测算边界复核。",
                "interpretation": research_data_point_interpretation(cfg["key"], fact, index),
                "research_use": research_data_point_use(cfg["key"], fact, index),
                "limitations": research_data_point_limit(cfg["key"], fact),
                "evidence_ref_uri": f"source_ref:{fact['source_ref']}",
                "sort_order": index,
            }
        )
    return rows


def research_data_point_interpretation(entity_key: str, fact: dict[str, Any], index: int) -> str:
    metric = fact["metric"]
    value = fact.get("value_text") or fact.get("value_num")
    if entity_key == "product_boundary_cdu_pump":
        if "边界" in metric:
            return f"{metric}把研究对象钉在 CDU 内部或 TCS 二次侧，含义是先决定什么能进样本池，再谈公司和订单；{value}"
        if "连续运行" in metric or "寿命" in metric:
            return f"{metric}把泵从普通热管理部件抬到数据中心可靠性部件，后续评价公司时要看寿命、维护窗口和故障切换，而不是只看有没有水泵产品；{value}"
        if "泄漏" in metric:
            return f"{metric}直接影响 AI 机柜停机风险，说明密封结构、材料兼容和监控联动比单纯流量参数更重要；{value}"
        if "扬程" in metric or "流量" in metric:
            return f"{metric}把车端或工业泵迁移的难点量化，研究上要把功率、压头和控制精度放在同一张技术门槛表里看；{value}"
        if "冗余" in metric:
            return f"{metric}说明 CDU 泵不是单件采购逻辑，冗余设计会改变泵数量、控制策略和维护成本；{value}"
        if "材料" in metric or "清洁" in metric:
            return f"{metric}说明水路长期运行的失效风险不只来自电机，还来自冷却液、颗粒和润湿材料，适合做供应商准入清单。"
        return f"{metric}补足产品定义的一块拼图：{value} 这类信息用于排除一次侧冷源、建筑水泵和泛液冷概念。"
    if "CDU" in metric and "价值" in metric:
        return f"{metric}给出的是 CDU 或液冷系统价值上限，不是泵 ASP；它的研究价值在于倒逼把泵、换热器、控制器和冗余件拆开。"
    if "冷板" in metric or "UQD" in metric:
        return f"{metric}提醒价值可能被冷板、快接头等部件分走；测算泵厂收入时必须扣除这些非泵环节。"
    if "二次侧" in metric or "占比" in metric:
        return f"{metric}提供了从整套液冷到二次侧系统的桥梁，但仍不能自动推导到某一家泵厂收入。"
    if "市场" in metric or "价格" in metric or "报价" in metric:
        return f"{metric}属于价格体系的弱证据或边界证据，适合做敏感性分析，不适合单独作为投资结论。"
    return f"{metric}用于把价值链拆到可核验部件层级：{value} 需要继续寻找 BOM、采购价和毛利率响应。"


def research_data_point_use(entity_key: str, fact: dict[str, Any], index: int) -> str:
    metric = fact["metric"]
    if entity_key == "product_boundary_cdu_pump":
        if index <= 4:
            return "用于界定研究样本池，先排除一次侧冷源、建筑水泵、汽车水泵和储能热管理泵。"
        if any(token in metric for token in ["连续运行", "寿命", "泄漏"]):
            return "用于建立可靠性门槛，判断公开产品能否支撑 7x24 数据中心工况。"
        return "用于构造后续公司筛选表，把技术迁移线索转成可核验的准入条件。"
    if index <= 6:
        return "用于拆分液冷系统、CDU 和泵的价值层级，防止把系统总价外推为泵厂收入。"
    if "报价" in metric:
        return "用于提醒公开报价污染，不作为核心估值参数，只进入反方和敏感性分析。"
    return "用于补充 CDU 选型、容量和采购模式，等待后续 BOM/ASP 一手证据校正。"


def research_data_point_limit(entity_key: str, fact: dict[str, Any]) -> str:
    source = SOURCE_BY_REF[fact["source_ref"]]
    if source["source_tier"] in {"S", "A"}:
        base = "来源等级较高，但仍需注意发布时间、适用场景和是否直接绑定 AI rack CDU。"
    else:
        base = "来源只能做辅助线索，不能替代公告、客户验收、标准文件或公司原文。"
    if entity_key == "price_value_chain":
        return base + " 该点不能单独推出泵 ASP 或公司收入，需要与 BOM、采购模式和冗余数量合并使用。"
    return base + " 该点定义产品边界或技术门槛，不代表任何标的已经供货。"


def make_research_profile(cfg: dict[str, Any], research_data_points: list[dict[str, Any]]) -> dict[str, Any]:
    refs = [f"source_ref:{ref}" for ref in cfg["evidence"]]
    if cfg["key"] == "product_boundary_cdu_pump":
        return {
            "entity_research_mode": "theory_research",
            "research_depth_status": "complete",
            "research_question": "本轮到底把什么算作 AI 数据中心液冷泵？哪些相邻泵、冷源和热管理业务只能当迁移线索或噪声，不能进入核心标的和评分口径？",
            "research_scope": "核心口径只收 CDU 内部或 TCS 二次侧循环泵、N+1 冗余泵、泵控、传感、泄漏保护、润湿材料兼容、清洁颗粒控制和数据中心连续运维要求；一次侧冷冻水、冷却塔、建筑水泵、汽车电子水泵、储能热管理泵和普通工业循环泵只能作为反方样本、能力迁移参照或口径污染审计，不直接进入机会矩阵。",
            "methodology_note": "先用 OCP L-L CDU 和 TCS row manifold 文件把 FWS/TCS、CDU、二次侧回路和交付准备边界定住，再用 UL 安全框架确认 CDU 属于数据中心 IT 设备环境，最后用车端泵与服务器泵对照表把 8760 小时运行、10-15 年寿命、近零泄漏、4Bar 以上扬程、1%-2% 流量精度、材料兼容和控制系统转成公司筛选门槛。",
            "literature_review_markdown": (
                "这组资料的关键不是证明“液冷很热”，而是先把研究对象的边界切出来。OCP L-L CDU 方法论把 CDU 放在设施侧水环路和 IT 侧流体网络之间，靠换热器隔离并传热；同一份资料还把 L-L CDU 描述成直接液冷系统里调节 FWS/TCS 流动并通信状态的核心控制单元。"
                "这意味着本轮研究的泵不是孤立水泵，而是 CDU/TCS 二次侧回路里的运行件、冗余件和控制件，必须和流量、压力、温度、泄漏保护、材料兼容和清洁度一起看。^evidence:source_ref:web_ocp_l_l_cdu_method "
                "OCP TCS row manifold 文件把二次侧回路、冲洗、清洁和机柜连接放在交付准备中，补上了“泵在什么系统里交付”的问题；UL 的数据中心 CDU 安全资料则说明这类设备已经进入 IT 设备安全和非制冷剂冷却液框架，不是普通工业换热器或建筑水泵。^evidence:source_ref:web_ocp_tcs_manifold ^evidence:source_ref:web_ul_cdu_certification "
                "真正把门槛拉开的，是服务器端液冷泵和车端水泵对照表：服务器端按 7x24、全年 8760 小时运行，设计寿命 10-15 年，泄漏容忍度接近零，扬程常到 4Bar 以上，流量精度约 1%-2%；车端水泵更多是间歇工况，年均约 2000 小时，扬程和精度要求明显低。^evidence:source_ref:xlsx_vehicle_vs_server_pump "
                "所以文献综述给出的判断很直接：汽车、储能、工业泵能力可以提示“谁可能迁移”，但不能替代 CDU 二次侧实际产品、客户验证、控制系统和收入拆分证据。"
            ),
            "data_collection_markdown": (
                f"本实体单独收集 {len(research_data_points)} 个研究型数据点，覆盖 CDU 产品边界、二次侧闭环、TCS row manifold、UL 安全认证、连续运行、寿命、泄漏、扬程、流量精度、泵选型三要素、N+1 冗余、润湿材料、控制系统、清洁颗粒控制和 CDU 控制单元功能。"
                "这些点不是为了凑数量，而是形成四组判断：系统边界、标准和安全边界、可靠性工况边界、可迁移能力边界；同一来源同一对象的多条描述只作为一个事实组内的不同口径使用。"
            ),
            "analysis_markdown": (
                "这篇研究要解决的是样本池问题。第一层是能不能进样本：只有 CDU 内部或 TCS 二次侧循环泵、冗余泵和泵控系统可以进入核心液冷泵口径；一次侧冷冻水系统、建筑水泵、车端电子水泵、储能热管理泵和普通工业泵不能因为都在搬运液体就直接并入。"
                "第二层是迁移难度怎么判断：如果公司只说有汽车电子水泵或工业循环泵，最多证明电机、水力件、密封或热管理经验，不能证明能在 AI rack 上跑 8760 小时、10-15 年、近零泄漏和 N+1 维护窗口。真正能把线索升级的证据应该是数据中心 CDU/TCS 场景的型号、压头流量、材料、控制协议、泄漏监测、客户测试或量产项目。"
                "第三层是和投资研究怎么衔接：产品边界实体不打分，是因为它不是机会本身，而是所有 market-linked 实体的前置过滤器。系统商机会要看 CDU 和整机交付，纯泵厂机会要看二次侧泵规格和客户认证，A 股迁移标的要先剥离汽车、储能和工业收入口径。"
                "按这个框架，英维克、申菱这类系统商的证据重点应放在 CDU/液冷产品和客户交付；飞龙、三花、江苏雷利、南方泵业等泵或部件公司要证明的是二次侧泵产品、数据中心客户和收入毛利响应，而不是泛热管理能力。"
                "它还直接影响后续证伪动作：如果公司新增披露仍停留在车端水泵、储能热管理或普通工业水泵，就应降级为迁移观察；只有出现 CDU/TCS 二次侧型号、系统商认证、客户项目和财务科目变化，才允许从观察清单升到核心评分。"
            ),
            "answer_markdown": (
                "本轮回答是：AI 数据中心液冷泵应限定为 CDU 内部或 TCS 二次侧闭环中的循环泵、冗余泵、泵控和与安全运维绑定的材料、传感、泄漏保护体系。"
                "它不是一次侧冷源设备，也不是车端或储能水泵的简单平移。车端、储能和普通工业泵可以作为能力迁移线索，但进入核心评分必须补齐数据中心 CDU/TCS 场景、规格、客户验证和收入拆分。"
                "因此后续研究的正确动作是先用这套边界排除噪声，再把真正穿过门槛的公司转入客户验证、价格捕获和供给弹性实体。"
            ),
            "conclusion_markdown": (
                "结论是，本实体已经把“AI 数据中心液冷泵”从泛液冷概念收窄为 CDU/TCS 二次侧高可靠运行件。后续核心机会排序必须先过三道关：是否在 CDU/TCS 二次侧，是否满足 8760 小时、10-15 年、近零泄漏、压头流量和控制耦合要求，是否有客户验证或收入证据。"
                "没有这些证据的公司只能放在观察和补证清单，不能因为有汽车水泵、储能泵、工业泵或普通液冷产品就进入主结论。这个结论直接回答本实体的问题：产品边界不是“所有会做泵的公司”，而是能进入 AI rack CDU 二次侧并经受数据中心可靠性和运维要求的泵及控制体系。"
            ),
            "limitations_markdown": "OCP 和 UL 资料能定义系统边界和安全框架，但不能证明任何公司 2026 年已经拿到订单；车端对照表能说明迁移门槛，但不能替代公司型号、客户、验收和收入证据。后续应继续追踪 CDU/TCS 原厂资料、客户平台文件、招投标和公司公告。",
            "evidence_ref_uri_list": refs,
        }
    return {
        "entity_research_mode": "theory_research",
        "research_depth_status": "complete",
        "research_question": "CDU 总价、液冷系统价值量和泵环节收入到底如何拆分？为什么 3 万美元 CDU 或整套液冷价值不能直接外推成泵厂 ASP、收入和股价弹性？",
        "research_scope": "研究 GB200、GB300、Rubin、Google TPU 等机柜液冷价值量、CDU 价格层级、二次侧价值占比、CDU 内部 BOM、冗余泵、泵控、容量层级、系统商采购和报价污染；不把价格篮子、市场规模或电商报价当作可交易标的，也不直接给机会分。",
        "methodology_note": "把价格链拆成五层：平台液冷价值量、二次侧系统、CDU 整机、CDU 内部泵和泵控 BOM、具体公司的订单收入和毛利率。每层只回答自己能回答的问题，不能用上层价值量替代下层 ASP，也不能用公开报价替代 AI rack CDU 成交价。",
        "literature_review_markdown": (
            "这组资料回答的是价值量怎么落到泵厂，而不是液冷空间大不大。中泰证券给出 GB200、GB300 和 Google TPU 机柜 CDU 约 30,000 美元的测算，同时列出 GB200 cold plate 约 25,200 美元、GB300 cold plate 约 39,600 美元、GB300 UQD 约 13,680 美元。"
            "这说明 CDU 很重要，但价值并不只在泵，冷板、快接头、控制和系统集成都会分走弹性。^evidence:source_ref:local_zhongtai_liquid_20260528 "
            "东吴 2025 报告把二次侧系统估到液冷系统价值约 75%，并把 CDU 放在冷板式液冷价值链约 25% 的位置，这能帮助搭桥，但不能直接推出泵占 CDU 的比例，因为 2025 旧平台口径还要和 GB300/Rubin 等新平台复核。^evidence:source_ref:local_dongwu_liquid_20250126 "
            "LiquidStack 的 CDU 选型材料强调热容量、流量、压头、设施集成和 TCO，CoolIT CHx2000 以 2MW 和 1.2LPM/kW 做核心规格，Motivair 覆盖 105kW-2.5MW 容量区间，这些资料共同说明 CDU 是按容量、可靠性和系统交付定价，不是单泵裸价。^evidence:source_ref:web_liquidstack_cdu_selection ^evidence:source_ref:web_coolit_chx2000 ^evidence:source_ref:web_schneider_motivair_mw_cdu "
            "Precedence 的 CDU pumps 市场和电商报价只能做边界提醒：它们能说明市场有口径，但不能替代 AI rack 的 BOM、采购折扣、冗余数量和真实 ASP。"
        ),
        "data_collection_markdown": (
            f"本实体收集 {len(research_data_points)} 个研究型数据点，覆盖 GB200/GB300/Google TPU CDU 价值、冷板和 UQD 分项、二次侧价值占比、CDU 价值占比、CDU pumps 市场弱证据、电商报价污染、TCO 选型、CoolIT 容量规格和 Motivair 容量区间。"
            "这些点被归为价格体系和价值链拆分资料，只用于估值口径、反方约束和后续补证清单，不进入 14 因子评分，也不生成标的投资建议。"
        ),
        "analysis_markdown": (
            "价格体系的研究结论要分层看。第一层，平台液冷价值量和 CDU 约 30,000 美元口径可以证明 AI rack 液冷从选配走向高价值系统件，这对系统商和 CDU 厂商更直接。第二层，冷板、UQD、换热器、控制器、过滤、管路和系统集成会一起分走价值，泵只是 CDU 内部的一部分，不能把 CDU 总价当成泵 ASP。"
                "第三层，泵能捕获多少价值取决于四个变量：一是每台 CDU 的泵数量和 N+1 冗余配置，二是压头、流量、材料和无轴封或密封方案是否带来溢价，三是泵厂是直接进入系统商 BOM 还是通过整机商打包采购，四是收入是否在公司财报和毛利率中体现。当前资料能支持前三层的研究框架，但还没有给出可直接入模的 pump ASP、采购折扣和毛利率。"
                "第四层，公开报价污染必须剔除。电商或通用水冷报价可能对应矿机、工业或小型设备，和 AI rack CDU 在可靠性、容量、交付责任和售后维护上不是一个口径。Precedence 这类市场规模也只能提示赛道存在，不能证明某家上市公司收入弹性。"
                "因此，本实体最有用的地方不是给公司排名，而是校正估值：系统商按 CDU/整套液冷交付看，纯泵厂按 CDU 内部泵 BOM 和客户认证看，部件公司按冷板、UQD、泵控或阀件拆分看。只有后续出现 pump ASP、BOM 占比、N+1 数量、订单客户和毛利率改善，才把该信息回流到具体标的评分。"
                "在没有这些证据前，使用保守假设更合理：把 CDU 总价作为系统层上限，把泵作为 SAM 子项，把公司收入确认作为 SOM 闸门，这样能避免把行业空间放大成单个标的利润。"
        ),
        "answer_markdown": (
            "本轮回答是：CDU 价格体系可以证明 AI 液冷系统价值量抬升，但不能直接证明泵厂价值捕获。"
            "从 CDU 总价到泵厂收入，至少要经过二次侧系统、CDU 整机、内部 BOM、泵数量和规格、采购模式、订单和毛利率六步。现在证据能支持“系统价值上行”和“CDU 是重要环节”，还不能支持“泵厂按 CDU 总价获得高 ASP”。"
            "所以价格体系应作为测算底稿和反方闸门，而不是机会矩阵中的可交易实体。"
        ),
        "conclusion_markdown": (
            "结论是，泵价值捕获不能从 3 万美元 CDU 线性外推。可以确认的是：AI rack 液冷推动 CDU 和二次侧系统价值上行，系统商和 CDU 厂商先受益的证据更强；仍需验证的是：CDU 内部泵的 BOM 占比、冗余数量、规格溢价、采购折扣和毛利率是否足以让纯泵厂或泵部件公司兑现收入弹性。"
            "本实体的用途是给 TAM/SAM/SOM 和标的估值定边界：TAM 看整套液冷和 CDU，SAM 只看 CDU 内部泵及泵控可触达空间，SOM 必须落到公司订单、客户和利润。没有 BOM/ASP 和收入证据前，不给评分、不挂标的、不写投资建议；一旦补齐，就转入对应 market-linked 实体重新打分。"
        ),
        "limitations_markdown": "公开资料仍缺少 CDU 内部 pump BOM、pump ASP、冗余泵数量、系统商采购折扣和上市公司毛利率响应；2025 报告和第三方市场规模只能做框架参考，不能替代 2026 年订单和成交价。后续应优先补系统商 BOM、招投标清单、客户验收和公司收入拆分。",
        "evidence_ref_uri_list": refs,
    }


FACTOR_ANALYSIS_LENS: dict[str, dict[str, str]] = {
    "demand.application_intensity_change": {
        "question": "应用强度是否真的抬升到必须重新设计泵、控制和冗余，而不是只是换一种散热叙事？",
        "read": "看它是否改变功率密度、连续运行、压差和水路复杂度。",
        "score": "分数高代表需求形态已经从可选配置变成平台约束；分数低则只能说明液冷主题存在。",
        "target": "标的上优先看能把高功率机柜需求转成 CDU、二次侧泵或控制系统收入的公司。",
    },
    "demand.output_consumption_proxy": {
        "question": "平台出货、机柜规模或 CDU 容量能否作为泵需求的可核验代理？",
        "read": "重点不是总市场大，而是能否拆到泵数量、冗余配置和单柜价值。",
        "score": "分数高说明需求分母清楚；分数低说明还停在 TAM 叙事或整机液冷口径。",
        "target": "标的上要把系统商收入、CDU 总价和纯泵价值分开，避免把整套系统都算给泵厂。",
    },
    "demand.customer_capex_capacity_signal": {
        "question": "NVIDIA、Google、华为和云厂资本开支能否落到具体 CDU/泵供应链？",
        "read": "看客户平台、reference design、系统商交付和供应商披露是否形成闭环。",
        "score": "分数高代表客户侧需求和供应链入口同时出现；分数低代表只看到终端需求，没有供应商确认。",
        "target": "标的上优先上调有客户、系统商或公告交付证据的公司，没有客户闭环的保留验证债。",
    },
    "signal.material_price_momentum": {
        "question": "价格、收入或价值量线索是否真的能传导到泵环节？",
        "read": "看报价、BOM 拆分、ASP、毛利率和订单确认，而不是只看 CDU 总价或媒体金额。",
        "score": "分数高代表价值捕获路径清楚；分数低代表收入弹性可能被系统商、冷板或快接件分走。",
        "target": "标的上要区分系统总包、部件平台和纯泵厂，价格证据弱时不提高估值容忍度。",
    },
    "supply.capacity_event_12m": {
        "question": "未来 12 个月有没有能改变供给可得性的产能、量产、认证或交付事件？",
        "read": "看公告、产线、验收、量产型号和收入确认，弱化只停留在产品页或样机的线索。",
        "score": "分数高代表供给事件有时间表；分数低代表只是能力展示或远期布局。",
        "target": "标的上把近期订单和验收作为加权条件，不能只因公司有泵或温控业务就加分。",
    },
    "supply.supplier_structure_bucket": {
        "question": "供应链入口是在系统商、传统泵厂、部件平台还是观察篮子？",
        "read": "看谁拿到客户入口、谁只提供泵规格、谁只是迁移能力。",
        "score": "分数高说明供应链层级可分清；分数低说明研究对象可能被系统商收入或普通泵口径污染。",
        "target": "标的上要按系统商确定性、泵厂直接性和部件平台稀释度分层排序。",
    },
    "supply.substitution_barrier": {
        "question": "汽车、储能或普通工业泵能力能否迁移到 AI CDU 二次侧泵？",
        "read": "看寿命、泄漏、材料兼容、冗余、通信控制和连续运行是否同时过关。",
        "score": "分数高代表替代门槛高且可验证；分数低代表普通泵能力可能被高估。",
        "target": "标的上要奖励能证明数据中心工况的公司，降低只靠车端或储能外推的公司权重。",
    },
    "supply.raw_policy_constraint": {
        "question": "标准、认证、介质和安全约束是否会把供给从普通泵厂筛到少数合格厂商？",
        "read": "看 OCP、UL、过滤、压力、温区、材料兼容和在线维护要求。",
        "score": "分数高代表准入门槛清楚；分数低代表标准证据偏旧或还没有绑定商业订单。",
        "target": "标的上要把认证和材料兼容作为进入核心池的前置条件。",
    },
}


ENTITY_ANALYSIS_ANGLE: dict[str, dict[str, str]] = {
    "product_boundary_cdu_pump": {
        "source": "边界证据来自 OCP、UL 和服务器/车端对照表，作用是先排除一次侧冷水系统和普通工业泵。",
        "decision": "本实体的判断顺序是先看是否属于 CDU 内部或 TCS 二次侧，再看连续运行、冗余、介质和认证。",
        "target": "产品边界过不了的公司不进入核心标的池；只可作为迁移观察。",
    },
    "demand_tam_sam_som": {
        "source": "需求证据把 NVIDIA、Google、华为和券商价值量测算放在一起，但必须拆出泵数量和泵 ASP。",
        "decision": "本实体先回答需求分母，再回答纯泵厂能拿走多少价值。",
        "target": "需求上修会先利好系统商和 CDU 集成，纯泵厂只有在 BOM 拆分清楚后才加权。",
    },
    "customer_validation_matrix": {
        "source": "客户证据分成平台需求、系统商验证、泵规格和直接供货四层，不能把任一层写成另一层。",
        "decision": "本实体核心是防止把 NVIDIA/Google/华为的液冷平台需求误写成某泵厂量产供货。",
        "target": "只有出现客户、系统商、型号和订单闭环，标的优先级才上调。",
    },
    "global_competition_stack": {
        "source": "全球竞争证据覆盖系统商、传统泵厂、磁力泵和水处理公司，必须先分清供应链位置。",
        "decision": "本实体看的是谁掌握客户入口，谁只是规格或设施侧 benchmark。",
        "target": "系统商确定性通常高于纯泵叙事，传统泵厂需要具体 AI CDU 订单才提升。",
    },
    "china_component_targets": {
        "source": "中国标的证据由产品平台、项目线索、公告、互动和财务口径构成，收入拆分是关键。",
        "decision": "本实体要把飞龙的泵弹性、英维克/申菱的系统商确定性、三花等部件平台分开。",
        "target": "标的排序随订单、客户验收、收入占比和毛利响应变化，不能只按概念相关度排序。",
    },
    "price_value_chain": {
        "source": "价格证据主要来自 CDU、冷板、UQD 和系统价值量，天然容易高估泵厂收入。",
        "decision": "本实体必须把 CDU 总价拆成泵、控制、换热、过滤、快接和系统集成。",
        "target": "拿不到 pump ASP 和冗余数量时，只能给价值捕获折扣。",
    },
    "reliability_control_barrier": {
        "source": "可靠性证据来自 OCP 参数、Eaton 无轴封/N+1、Johnson 流量压差和 Moog 磁力泵。",
        "decision": "本实体看泵是否能承受长期连续运行、压差、过滤、泄漏和在线维护，而不是只看有无泵产品。",
        "target": "能证明 MTBF、零泄漏、冗余切换和监控协议的公司才获得壁垒分。",
    },
    "contamination_and_falsification": {
        "source": "反方证据刻意纳入车端、储能、一次侧、系统商归因和客户传闻，目的是压低误判。",
        "decision": "本实体优先找证伪点：收入是否错配、客户是否传闻、产品是否不在 CDU 二次侧。",
        "target": "证据越能拆清口径，越能保留迁移公司；拆不清就从核心排序降级。",
    },
}


def _factor_lens(code: str) -> dict[str, str]:
    return FACTOR_ANALYSIS_LENS[code]


def _entity_angle(entity: dict[str, Any]) -> dict[str, str]:
    return ENTITY_ANALYSIS_ANGLE[entity["key"]]


def _source_names(refs: list[str], limit: int = 4) -> str:
    names: list[str] = []
    for ref in refs[:limit]:
        source = SOURCE_BY_REF[ref]
        name = source.get("publisher") or source.get("title") or ref
        if name not in names:
            names.append(name)
    return "、".join(names)


def _fact_takeaway(entity_key: str, fact: dict[str, Any]) -> str:
    metric = fact["metric"]
    value = _clause(str(fact.get("value_text") or fact.get("value_num") or ""), 150)
    if entity_key == "product_boundary_cdu_pump":
        if "边界" in metric or "CDU" in metric or "TCS" in metric:
            return f"{metric}把研究对象锁定在 CDU/TCS 二次侧：{value}；这会直接排除一次侧冷水、建筑 HVAC 和普通工业泵。"
        if "运行" in metric or "寿命" in metric:
            return f"{metric}把车端间歇工况和服务器全年连续工况拉开：{value}；迁移公司必须补寿命和可靠性证据。"
        return f"{metric}补的是准入边界：{value}；它决定哪些产品只能放进观察池。"
    if entity_key == "demand_tam_sam_som":
        if any(word in metric for word in ["NVIDIA", "GB", "Google", "华为", "Atlas"]):
            return f"{metric}说明 AI 平台液冷需求正在上移：{value}；但这只给需求分母，不能自动给某家泵厂订单。"
        if "价值" in metric or "CDU" in metric:
            return f"{metric}提供价值量锚点：{value}；下一步必须拆出泵、冗余和控制器，否则 SAM 会被系统总价放大。"
        return f"{metric}用于校准液冷渗透和机柜尺度：{value}；它影响需求上限而不是单一公司胜率。"
    if entity_key == "customer_validation_matrix":
        if any(word in metric for word in ["NVIDIA", "Google", "华为"]):
            return f"{metric}确认的是客户平台或生态阶段：{value}；供应商层面还要等系统商、型号和订单闭环。"
        if any(word in metric for word in ["Vertiv", "CoolIT", "Schneider", "Delta"]):
            return f"{metric}比普通产品页更接近客户验证：{value}；但仍需区分 CDU 系统商和泵部件供应商。"
        return f"{metric}是验证矩阵里的辅助证据：{value}；可提高补证优先级但不能单独确认供货。"
    if entity_key == "global_competition_stack":
        if any(word in metric for word in ["格兰富", "Wilo", "Xylem", "Johnson", "Moog"]):
            return f"{metric}说明传统泵厂或技术路线已经进入数据中心叙事：{value}；但客户绑定和 AI CDU 订单仍要单独核验。"
        if any(word in metric for word in ["Vertiv", "CoolIT", "Schneider", "Delta"]):
            return f"{metric}反映系统商控制客户入口：{value}；这会压缩纯泵厂直接价值捕获。"
        return f"{metric}用于分层全球参与者：{value}；重点是供应链位置而不是公司名单数量。"
    if entity_key == "china_component_targets":
        if any(word in metric for word in ["飞龙", "英维克", "申菱", "三花", "高澜", "同飞"]):
            return f"{metric}提供中国标的的具体入口：{value}；需要继续拆订单、客户和收入占比。"
        if "收入" in metric or "毛利" in metric:
            return f"{metric}直接影响财务弹性判断：{value}；若无法拆出数据中心液冷，评分必须打折。"
        return f"{metric}是标的承接能力的旁证：{value}；只能和公告、产品型号及客户验收合并使用。"
    if entity_key == "price_value_chain":
        if "冷板" in metric or "UQD" in metric:
            return f"{metric}提醒价值增量不只在泵：{value}；泵厂收入测算必须扣除冷板、快接和系统集成。"
        if "CDU" in metric or "价值" in metric:
            return f"{metric}给出 CDU 总价或机柜口径：{value}；研究重点是从总包里拆出 pump ASP 和冗余数量。"
        return f"{metric}补充价值链分配线索：{value}；它更适合做测算边界而不是直接当收入。"
    if entity_key == "reliability_control_barrier":
        if "服务寿命" in metric:
            return f"OCP 把泵寿命写成 10 年要求：{value}；这把 CDU 泵从易替换部件提升为连续运行可靠性件。"
        if "无轴封" in metric or "Eaton" in metric:
            return f"Eaton 的无轴封和 N+1 冗余说的是减少泄漏点和维护窗口：{value}；这类证据比普通流量参数更能说明壁垒。"
        if "压力" in metric or "过滤" in metric or "温度" in metric:
            return f"{metric}把泵、管路、过滤和介质兼容放在同一约束里：{value}；说明可靠性不是单点规格。"
        if "Johnson" in metric or "Moog" in metric or "磁力" in metric:
            return f"{metric}提供可比产品规格或密封路线：{value}；后续要看它是否进入主流 CDU/OEM 量产。"
        return f"{metric}补充运维壁垒：{value}；判断重点是故障切换和长期在线维护。"
    if entity_key == "contamination_and_falsification":
        if any(word in metric for word in ["车端", "储能", "工业", "一次侧"]):
            return f"{metric}是反方口径：{value}；它提示不能把相邻市场收入直接搬到 AI CDU 泵。"
        if "客户" in metric or "验证债" in metric:
            return f"{metric}暴露客户确认不足：{value}；缺少公开闭环时只能保留验证债。"
        return f"{metric}用于拆分误判来源：{value}；能证伪的证据优先级高于概念相关性。"
    return f"{metric}的可用事实是：{value}。"


def _factor_point_direction(code: str, fact: dict[str, Any], note: str, score_read: str) -> str:
    metric = fact["metric"]
    if code == "demand.application_intensity_change":
        return f"{metric}会影响功率密度、连续运行和水路复杂度三个变量；当前{score_read}，但还要等客户平台或系统商规格继续确认。"
    if code == "demand.output_consumption_proxy":
        return f"{metric}适合放进需求分母，而不是直接放进某家公司收入；当前{score_read}，下一步看泵数量、冗余方案和单柜价值能否拆出。"
    if code == "demand.customer_capex_capacity_signal":
        return f"{metric}把客户或云厂需求往前推进了一步；当前{score_read}，供应商层面仍要等 reference design、招标、验收或财报。"
    if code == "signal.material_price_momentum":
        return f"{metric}能帮助判断价值捕获，但它必须和 BOM、ASP、毛利率或订单一起看；当前{score_read}，不单独提高估值容忍度。"
    if code == "supply.capacity_event_12m":
        return f"{metric}如果转成量产型号、产线或验收节点，会改变未来 12 个月供给可得性；当前{score_read}，产品页证据仍低于订单证据。"
    if code == "supply.supplier_structure_bucket":
        return f"{metric}用于判断供应链入口落在系统商、泵厂还是部件平台；当前{score_read}，排序时要先分层再比较公司弹性。"
    if code == "supply.substitution_barrier":
        return f"{metric}直接检验普通泵能力能不能迁移；当前{score_read}，寿命、密封、冗余、介质和通信控制缺一项都要降级。"
    if code == "supply.raw_policy_constraint":
        return f"{metric}把标准和安全要求放到评分前置条件；当前{score_read}，没有认证、介质兼容或在线维护证据的标的不能进核心池。"
    return f"{metric}目前支撑 {note}，当前{score_read}。"


def _interpret_information_point(
    entity: dict[str, Any],
    code: str,
    fact: dict[str, Any],
    note: str,
    score: float,
    point_index: int,
) -> str:
    base = _fact_takeaway(entity["key"], fact)
    score_read = "加分" if score >= 75 else "保守加权" if score >= 62 else "仅作观察"
    return f"{base} {_factor_point_direction(code, fact, note, score_read)}"


def _factor_source_summary(entity: dict[str, Any], code: str, refs: list[str]) -> str:
    lens = _factor_lens(code)
    angle = _entity_angle(entity)
    names = _source_names(refs, limit=5)
    return (
        f"{entity['display_name']} 的这个因子主要依赖 {names}。"
        f"{angle['source']} 本轮用这些来源检查：{lens['read']}"
    )


def _factor_value_summary(entity: dict[str, Any], code: str, score: float, note: str) -> str:
    lens = _factor_lens(code)
    if code == "demand.application_intensity_change":
        return f"{score:.0f} 分偏强，说明 {entity['display_name']} 的机会来自工况升级：{note} 还需要用客户平台规格和系统商交付把强度落到订单。"
    if code == "demand.output_consumption_proxy":
        return f"{score:.0f} 分不是 TAM 结论，而是需求代理的可信度判断：{note} 只有继续拆出泵数量和冗余结构，才能把需求换算到标的收入。"
    if code == "demand.customer_capex_capacity_signal":
        return f"{score:.0f} 分反映客户侧牵引强弱：{note} 该分数越高，越应该追踪客户平台到系统商、泵型号和供应商名单的闭环。"
    if code == "signal.material_price_momentum":
        return f"{score:.0f} 分用于约束价值捕获：{note} 当前更像测算边界，只有 BOM、ASP、毛利率或订单同步出现，才提高交易优先级。"
    if code == "supply.capacity_event_12m":
        return f"{score:.0f} 分表示近期供给事件的可见度：{note} 产品页和样机只能支持观察，量产、验收和收入确认才会把分数继续推高。"
    if code == "supply.supplier_structure_bucket":
        return f"{score:.0f} 分说明供应链层级能否分清：{note} 系统商、纯泵厂和部件平台的价值捕获不同，不能放在同一个估值框里。"
    if code == "supply.substitution_barrier":
        return f"{score:.0f} 分主要来自替代门槛：{note} 这不是概念相关度，而是在检验普通泵能力能否穿过寿命、密封、冗余和控制要求。"
    if code == "supply.raw_policy_constraint":
        return f"{score:.0f} 分代表准入约束强度：{note} 标准和认证越具体，越能把可迁移公司筛成核心、观察和排除三类。"
    return f"{score:.0f} 分用于回答 {lens['question']}：{note}"


def _factor_topic_analysis(entity: dict[str, Any], code: str, score: float, note: str) -> str:
    lens = _factor_lens(code)
    angle = _entity_angle(entity)
    if code == "demand.application_intensity_change":
        return f"{angle['decision']} 这里的分析重点是工况是否真的变重：{note} 如果后续只有液冷概念而没有机柜功耗、压差、流量和冗余要求，强度分要下修。"
    if code == "demand.output_consumption_proxy":
        return f"{angle['decision']} 需求代理的作用是给收入测算找分母，{note} 但泵厂收入还取决于 CDU 架构、冗余泵数量和采购方式。"
    if code == "demand.customer_capex_capacity_signal":
        return f"{angle['decision']} 客户资本开支只解决需求存在，不解决谁供货；{note} 因此本因子后续最需要公告、reference design 和验收材料。"
    if code == "signal.material_price_momentum":
        return f"{angle['decision']} 价格和价值量证据容易把系统总包误算成泵收入，{note} 本因子只在拆出 ASP、BOM 或毛利响应后才提高确定性。"
    if code == "supply.capacity_event_12m":
        return f"{angle['decision']} 近期事件要看能否从产品能力进入交付：{note} 样机、产品页和媒体线索不足以替代量产、客户验收或财务确认。"
    if code == "supply.supplier_structure_bucket":
        return f"{angle['decision']} 供应链分层决定标的排序：{note} 系统商拿客户入口，泵厂拿部件弹性，部件平台则要看价值是否被稀释。"
    if code == "supply.substitution_barrier":
        return f"{angle['decision']} 替代壁垒越高，越不能用汽车、储能或普通工业泵收入外推；{note} 后续核验要落到工况和客户两端。"
    if code == "supply.raw_policy_constraint":
        return f"{angle['decision']} 标准和认证把主题公司筛成不同层级；{note} 没有介质、过滤、压力和在线维护证据的公司不能只靠产品名加分。"
    return f"{angle['decision']} {lens['question']} 当前证据支持 {note}。"


def _score_rationale(entity: dict[str, Any], code: str, score: float, note: str, refs: list[str]) -> str:
    lens = _factor_lens(code)
    source_names = _source_names(refs, limit=5)
    note_clause = _clause(note, 220)
    if score >= 80:
        strength = "分数偏高，原因是核心证据已经直接碰到规格、客户入口或工况门槛"
    elif score >= 68:
        strength = "分数居中偏上，说明方向成立但商业闭环还没有完全打通"
    else:
        strength = "分数保守，主要把它当成观察线索或反方约束"
    return f"{strength}。本轮来源包括 {source_names}；它们支持 {note_clause}，但仍要补 {lens['target']}"


def _theme_points(entity: dict[str, Any], code: str) -> list[str]:
    lens = _factor_lens(code)
    angle = _entity_angle(entity)
    return [
        angle["decision"],
        lens["score"],
        angle["target"],
    ]


def _target_implication(entity: dict[str, Any], code: str) -> str:
    lens = _factor_lens(code)
    angle = _entity_angle(entity)
    return f"{angle['target']} 标的层面具体看：{lens['target']}"


def make_factor(entity: dict[str, Any], code: str, score: float, note: str, refs: list[str]) -> dict[str, Any]:
    info_points: list[dict[str, Any]] = []
    for index, fact in enumerate(facts_for(entity["key"], refs, limit=max(5, min(7, len(refs))), factor_code=code), start=1):
        info_points.append(
            {
                "slot_name": fact["metric"],
                "metric_line": f"{fact['metric']}：{fact.get('value_text') or fact.get('value_num')}",
                "excerpt": fact["source_excerpt"],
                "evidence_ref": f"source_ref:{fact['source_ref']}",
                "interpretation": _interpret_information_point(entity, code, fact, note, score, index),
                "source_tier": SOURCE_BY_REF[fact["source_ref"]]["source_tier"],
                "direction": "positive" if score >= 65 else "mixed",
                "observation_count": 1,
                "weight_reason": f"按来源等级、与 {code} 的直接性、是否能支撑客户/规格/收入闭环加权。",
            }
        )
    lens = _factor_lens(code)
    return {
        "factor_code": code,
        "score_status": "complete",
        "score_raw": score,
        "score_adjusted": score,
        "coverage": entity["coverage"],
        "confidence": entity["confidence"],
        "factor_readiness_status": "ready" if len(refs) >= 5 else "limited",
        "metric_name": f"{entity['display_name']} - {code}",
        "unit": "分",
        "period": AS_OF_DATE,
        "as_of_date": AS_OF_DATE,
        "trace": f"{entity['display_name']} / {code}：{lens['read']}；当前结论是 {note}",
        "core_score_note": "仅采用官方资料、结构化本地表格、券商报告和明确标注的早期信号；灰源不单独进入供货确认。",
        "contextual_human_question": f"{entity['display_name']}：{lens['question']}",
        "contextual_factor_description": note,
        "source_context_summary": _factor_source_summary(entity, code, refs),
        "factor_value_summary": _factor_value_summary(entity, code, score, note),
        "factor_topic_analysis": _factor_topic_analysis(entity, code, score, note),
        "score_rationale": _score_rationale(entity, code, score, note, refs),
        "theme_analysis_points": _theme_points(entity, code),
        "information_points": info_points,
        "adjacent_factor_links": [
            _entity_angle(entity)["decision"],
            lens["read"],
            lens["target"],
        ],
        "target_implications": _target_implication(entity, code),
        "source_context_refs": [f"source_ref:{ref}" for ref in refs],
        "evidence_ref_uri_list": [f"source_ref:{ref}" for ref in refs],
        "factor_importance": "important" if score >= 70 else "normal",
    }


def make_entities() -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    for cfg in ENTITY_CONFIGS:
        refs = cfg["evidence"]
        actions = ENTITY_ACTIONS[cfg["key"]]
        research_mode = "theory_research" if is_theory_research_entity(cfg) else "market_linked"
        research_data_points = make_research_data_points(cfg) if research_mode == "theory_research" else []
        factors = [] if research_mode == "theory_research" else [
            make_factor(cfg, code, score, note, refs)
            for code, (score, note) in cfg["factor_notes"].items()
        ]
        maturation_status = "research_only" if research_mode == "theory_research" else cfg["maturation"]
        priority_label = "research_only_literature_review_complete" if research_mode == "theory_research" else cfg["priority"]
        readiness_reason = (
            "研究型实体用于定义边界、测算口径和文献综述，不进入 14 因子打分、不绑定标的、不生成投资建议。"
            if research_mode == "theory_research"
            else "已纳入本地研报、结构化表格、公司官方资料、客户平台资料和公开网页，并完成口径污染审计。"
        )
        band_reason = (
            "研究型实体无核心分；其作用是给 market-linked 实体提供定义、方法和估值校准。"
            if research_mode == "theory_research"
            else "按产品边界、客户验证、规格强度、供给结构、价格捕获和口径污染审计综合评分。"
        )
        score_point = None if research_mode == "theory_research" else cfg["score"]
        entities.append(
            {
                "key": cfg["key"],
                "entity_type": "product_material",
                "taxonomy_level": "product_material",
                "canonical_name": f"AI 数据中心液冷泵研究：{cfg['display_name']}",
                "display_name": cfg["display_name"],
                "description": cfg["description"],
                "entity_research_mode": research_mode,
                "external_ref_type": "ai_datacenter_liquid_cooling_pump_20260704",
                "maturation_status": maturation_status,
                "readiness_score": None if research_mode == "theory_research" else round(cfg["score"] / 100, 2),
                "readiness_reason": readiness_reason,
                "research_priority_label": priority_label,
                "source_count": len(refs),
                "independent_source_count": len(set(SOURCE_BY_REF[ref]["cluster"] for ref in refs)),
                "candidate_reason": f"{cfg['display_name']} 是本轮液冷泵研究的独立实体，解决 {cfg['description']}",
                "evidence_ref_uri": f"source_ref:{refs[0]}",
                "evidence_ref_uri_list": [f"source_ref:{ref}" for ref in refs],
                "score_point": score_point,
                "score_grade": "研究型" if research_mode == "theory_research" else cfg["grade"],
                "score_quality_label": "high_confidence" if cfg["confidence"] >= 0.75 else "medium_confidence",
                "score_band_low": None if research_mode == "theory_research" else max(0, cfg["score"] - 7),
                "score_band_high": None if research_mode == "theory_research" else min(100, cfg["score"] + 7),
                "coverage": cfg["coverage"],
                "confidence": cfg["confidence"],
                "band_reason": band_reason,
                "composite_trace": {
                    "confirmed_action": actions["confirmed"],
                    "falsified_action": actions["falsified"],
                    "monitor_signal": actions["monitor"],
                    "monitor_timing": "未来 0-6 个月优先看公告、招标、财报和客户平台资料。",
                },
                "research_profile": make_research_profile(cfg, research_data_points) if research_mode == "theory_research" else None,
                "research_data_points": research_data_points,
                "factor_scores": factors,
            }
        )
    return entities


def make_claims() -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for fact in FACTS:
        if len(claims) >= 44:
            break
        source = SOURCE_BY_REF[fact["source_ref"]]
        claim_type = "产品边界证据"
        if fact["entity_key"] == "demand_tam_sam_som":
            claim_type = "需求和市场空间证据"
        elif fact["entity_key"] == "customer_validation_matrix":
            claim_type = "客户验证证据"
        elif fact["entity_key"] == "global_competition_stack":
            claim_type = "竞争格局证据"
        elif fact["entity_key"] == "china_component_targets":
            claim_type = "标的承接证据"
        elif fact["entity_key"] == "price_value_chain":
            claim_type = "价格和价值链证据"
        elif fact["entity_key"] == "reliability_control_barrier":
            claim_type = "可靠性壁垒证据"
        elif fact["entity_key"] == "contamination_and_falsification":
            claim_type = "口径污染和证伪证据"
        claims.append(
            {
                "source_ref": fact["source_ref"],
                "entity_key": fact["entity_key"],
                "claim_type": claim_type,
                "claim_text": f"{fact['metric']}：{fact['value_text']}",
                "source_excerpt": fact["source_excerpt"],
                "claim_evidence_status": "verified" if source["source_tier"] in {"S", "A"} else "weak_source_only" if source["policy_evidence_role"] != "core_evidence" else "needs_review",
                "claim_next_action": "use_as_background",
                "support_status": "supported" if source["policy_evidence_role"] == "core_evidence" else "partially_supported",
                "policy_evidence_role": source["policy_evidence_role"],
            }
        )
    return claims


def table_md(headers: list[str], rows: list[list[Any]]) -> str:
    def clean(cell: Any) -> str:
        return _compact(cell).replace("|", "，")

    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(clean(cell) for cell in row) + " |")
    return "\n".join(lines)


def make_sections(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    market_entities = [entity for entity in entities if not is_theory_research_entity(entity)]
    theory_entities = [entity for entity in entities if is_theory_research_entity(entity)]
    ranking_rows = []
    for idx, entity in enumerate(sorted(market_entities, key=lambda item: item["score_point"], reverse=True), start=1):
        ranking_rows.append(
            [
                idx,
                entity["display_name"],
                entity["description"],
                entity["score_point"],
                len(entity["evidence_ref_uri_list"]),
                entity["composite_trace"]["confirmed_action"],
                entity["composite_trace"]["falsified_action"],
                " ".join(f"^evidence:{ref}" for ref in entity["evidence_ref_uri_list"][:2]),
            ]
        )
    theory_rows = [
        [
            entity["display_name"],
            entity["research_profile"]["research_question"],
            len(entity.get("research_data_points", [])),
            entity["research_profile"]["answer_markdown"],
            " ".join(f"^evidence:{ref}" for ref in entity["evidence_ref_uri_list"][:2]),
        ]
        for entity in theory_entities
    ]
    validation_rows = [
        ["NVIDIA", "GB200/GB300 全液冷 rack 已官方确认", "Vertiv、CoolIT 等系统商公开证据强", "未看到纯泵厂直接供货公开确认", "强需求，泵厂验证债高"],
        ["Google", "Ironwood TPU 和冷却演进资料确认液冷需求", "OCP/Deschutes 方向需要继续追踪", "供应商披露少", "需求强，供应链透明度低"],
        ["华为", "Atlas 900 A3 SuperPoD 出货确认国产 AI 集群需求", "英维克、申菱等系统商具备产品能力", "泵厂直接客户确认不足", "最重要但最易被传闻污染"],
    ]
    target_rows = [
        [t["target_name"], t["priority"], t["quality"], t["relative"], t["confirmed"], t["falsified"], f"^evidence:source_ref:{t['source_ref']}"]
        for t in TARGET_DEFS
        if t["entity_key"] not in THEORY_RESEARCH_ENTITY_KEYS
    ]
    target_rows = target_rows[:16]
    monitor_rows = [
        [1, "NVIDIA GB300/Rubin rack 参考架构", "0-6 个月", "公布系统商、CDU 或泵规格", "重排全球系统商和中国映射", "确认后加权系统商，未确认则维持验证债", "^evidence:source_ref:web_nvidia_gb300_nvl72"],
        [2, "Google Ironwood/TPU 液冷供应链", "0-12 个月", "OCP、OEM 或数据中心项目披露供应商", "区分 TPU 需求和外部供应商机会", "确认供应商后提升对应标的，封闭供应链则降低外推", "^evidence:source_ref:web_google_ironwood_tpu"],
        [3, "华为/超聚变/运营商液冷中标", "0-6 个月", "CDU、泵、冷板、快接头中标或验收", "解决国产链最大的客户验证债", "公告确认才进入核心评分，传闻不加分", "^evidence:source_ref:web_huawei_atlas_a3_superpod"],
        [4, "飞龙股份项目转批量", "每季财报和互动易", "液冷泵收入、客户、毛利率同步披露", "判断纯泵厂是否能兑现主题", "确认后提高 P1 权重，否则降为汽车/储能迁移观察", "^evidence:source_ref:web_feilong_sina_20260701"],
        [5, "英维克/申菱高功率 CDU 交付", "每季财报和招投标", "AI 数据中心 CDU 收入、客户和交付量提升", "判断系统商是否先于泵厂兑现", "确认后优先系统商，未确认则只保留产品能力", "^evidence:source_ref:web_shenling_liquid_cdu"],
        [6, "CDU 内部 pump ASP 和 BOM", "0-12 个月", "拆出冗余泵、控制器、换热器和柜型差异", "修正 TAM/SAM/SOM", "若泵占比低，降低纯泵厂弹性；若高可靠泵溢价确认，提升", "^evidence:source_ref:local_zhongtai_liquid_20260528"],
    ]
    report = (
        "本轮研究结论是：AI 数据中心液冷泵机会真实存在，但它不是“所有泵厂都受益”的线性主题。需求端最强证据来自 NVIDIA GB200/GB300 全液冷 rack、Google Ironwood TPU 和华为 Atlas SuperPoD 的高密度 AI 集群；供给端最强证据来自 Vertiv、CoolIT、Schneider/Motivair、Delta、Supermicro 等系统和 CDU 平台。纯泵厂的机会必须再通过 CDU 内部泵规格、N+1 冗余、无轴封或磁力泵路线、客户认证、量产交付和收入拆分验证。中国标的中，英维克、申菱偏系统商确定性，飞龙偏纯泵弹性但收入确认不足，三花偏部件平台且要排除汽车口径；南方泵业、大元、汉宇、江苏雷利、凌霄等只能作为补证或排除性观察。^evidence:source_ref:web_nvidia_gb300_nvl72 ^evidence:source_ref:web_google_ironwood_tpu ^evidence:source_ref:web_huawei_atlas_a3_superpod ^evidence:source_ref:web_vertiv_nvidia_gb200 ^evidence:source_ref:web_coolit_chx2000\n\n"
        "### 核心机会排序\n\n"
        + table_md(["排名", "研究实体", "核心判断", "核心分", "证据", "证实后动作", "证伪后动作", "证据"], ranking_rows)
        + "\n\n### 深度研究型主题\n\n"
        + table_md(["研究主题", "要回答的问题", "研究数据点", "当前回答", "证据"], theory_rows)
        + "\n\n### 客户验证矩阵\n\n"
        + table_md(["客户平台", "平台液冷需求", "系统商验证", "泵厂直接验证", "投资含义"], validation_rows)
        + "\n\n### 标的研究摘要\n\n"
        + table_md(["标的", "优先级", "质量判断", "同实体内比较", "证实后动作", "证伪后动作", "证据"], target_rows)
    )
    market = (
        "液冷泵市场测算必须拆成三层：TAM 是 AI 数据中心液冷系统和 CDU 的总体容量，SAM 是 CDU 内部泵、冗余泵、泵控和二次侧循环泵可触达空间，SOM 才是具体公司能拿到的订单和收入。GB200/GB300/Rubin 和 Google TPU 的液冷价值量可以帮助判断上限，但 3 万美元 CDU 价值不能直接当成泵 ASP。真正影响泵价值的是冗余设计、压头、流量、可靠性、材料兼容和是否由系统商打包采购。^evidence:source_ref:local_zhongtai_liquid_20260528 ^evidence:source_ref:web_liquidstack_cdu_selection\n\n"
        + table_md(
            ["口径", "可用证据", "不能怎么用", "正确用法"],
            [
                ["TAM", "NVIDIA/Google/华为平台、整体液冷市场和 CDU 市场测算", "不能直接等于泵收入", "用于判断需求上限和行业方向"],
                ["SAM", "CDU 内部泵、冗余泵、二次侧循环泵和泵控", "不能把冷板、UQD、manifold 算进泵", "用于建立泵厂收入测算框架"],
                ["SOM", "客户订单、项目转批量、公司收入和毛利率", "不能用项目数量或客户传闻替代", "用于标的评分和交易优先级"],
            ],
        )
    )
    validation = (
        "客户验证的核心判断是：NVIDIA、Google、华为都能确认平台液冷需求，但只有 NVIDIA 公开生态中的系统商证据最强；Google 和华为对外披露的泵、CDU、冷板供应商较少。所有“进入 NVIDIA/Google/华为”的表述都要标阶段：平台需求、系统商 reference design、CDU 产品能力、样品验证、小批量、量产、公开确认。没有客户或公告的公司，只能列验证债。^evidence:source_ref:web_nvidia_ocp_gb200 ^evidence:source_ref:web_vertiv_nvidia_gb200 ^evidence:source_ref:web_google_arpae_cooling ^evidence:source_ref:web_huawei_atlas_a3_superpod"
    )
    monitor = "后续监控要直接服务证实和证伪，不做泛泛信息收集。\n\n" + table_md(
        ["优先级", "事件/监控信号", "监控时间", "证实/证伪条件", "研究响应", "交易操作框架", "证据"],
        monitor_rows,
    )
    risks = (
        "主要风险不是“液冷需求不增长”，而是归因错误。第一，系统商和纯泵厂收入弹性不同，CDU 总价不能等于泵价格。第二，汽车、储能和工业泵能力可迁移但不能直接替代 8760 小时、零泄漏、N+1 和 CDU 控制耦合。第三，NVIDIA/Google/华为平台需求强不等于任一 A 股泵厂已经供货。第四，部分 2024 标准和旧报告只能定义边界，不能证明 2026 年订单。^evidence:source_ref:xlsx_vehicle_vs_server_pump ^evidence:source_ref:xlsx_auto_transfer_barrier ^evidence:source_ref:web_ocp_l_l_cdu_method"
    )
    return [
        {"section_key": "research_report", "section_title": "研究报告", "body_markdown": report, "evidence_ref_uri_list": [f"source_ref:{ref}" for ref in ["web_nvidia_gb300_nvl72", "web_google_ironwood_tpu", "web_huawei_atlas_a3_superpod", "web_vertiv_nvidia_gb200", "web_coolit_chx2000", "local_zhongtai_liquid_20260528"]], "sort_order": 10},
        {"section_key": "market_space_price", "section_title": "市场空间、价格体系和价值链拆分", "body_markdown": market, "evidence_ref_uri_list": [f"source_ref:{ref}" for ref in ["local_zhongtai_liquid_20260528", "local_dongwu_liquid_20250126", "web_liquidstack_cdu_selection", "web_precedence_cdu_pumps_market"]], "sort_order": 20},
        {"section_key": "customer_validation", "section_title": "NVIDIA / Google / 华为客户验证矩阵", "body_markdown": validation, "evidence_ref_uri_list": [f"source_ref:{ref}" for ref in ["web_nvidia_ocp_gb200", "web_vertiv_nvidia_gb200", "web_coolit_nvidia", "web_google_ironwood_tpu", "web_huawei_atlas_a3_superpod"]], "sort_order": 30},
        {"section_key": "monitoring_plan", "section_title": "后续监控、证实证伪和交易操作框架", "body_markdown": monitor, "evidence_ref_uri_list": [f"source_ref:{ref}" for ref in ["web_nvidia_gb300_nvl72", "web_google_ironwood_tpu", "web_huawei_atlas_a3_superpod", "web_feilong_sina_20260701", "web_shenling_liquid_cdu"]], "sort_order": 40},
        {"section_key": "risk_and_falsification", "section_title": "主要风险和口径污染", "body_markdown": risks, "evidence_ref_uri_list": [f"source_ref:{ref}" for ref in ["xlsx_vehicle_vs_server_pump", "xlsx_auto_transfer_barrier", "web_ocp_l_l_cdu_method", "web_feilong_sina_20260701"]], "sort_order": 50},
    ]


def make_entity_sections(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for entity in entities:
        fact_limit = 10 if is_theory_research_entity(entity) else 6
        facts = facts_for(entity["key"], [ref.replace("source_ref:", "") for ref in entity["evidence_ref_uri_list"]], limit=fact_limit)
        fact_lines = "\n".join(
            f"- {fact['metric']}：{fact['value_text']} ^evidence:source_ref:{fact['source_ref']}" for fact in facts
        )
        if is_theory_research_entity(entity):
            profile = entity["research_profile"]
            body = (
                f"### 研究对象\n\n{entity['description']}\n\n"
                f"### 证据链与数据基础\n\n{fact_lines}\n\n"
                f"这些证据共同服务于一个研究问题：{profile['research_question']} 它们不是为了给公司打分，而是为了界定样本、拆清口径和校正后续 market-linked 实体的判断。\n\n"
                f"### 文献综述和资料整理\n\n{profile['literature_review_markdown']}\n\n"
                f"### 分析\n\n{profile['analysis_markdown']}\n\n"
                f"### 总结\n\n{profile['conclusion_markdown']}"
            )
            sections.append(
                {
                    "entity_key": entity["key"],
                    "section_key": "entity_research_profile",
                    "section_title": f"{entity['display_name']}深度研究主题",
                    "body_markdown": body,
                    "evidence_ref_uri_list": entity["evidence_ref_uri_list"][:10],
                    "support_status": "supported",
                    "sort_order": 1000 + len(sections) * 10,
                }
            )
            continue
        target_names = [target["target_name"] for target in TARGET_DEFS if target["entity_key"] == entity["key"]]
        if not target_names:
            target_names = ["本实体以外部研究入口和补证清单为主"]
        body = (
            f"### 研究对象\n\n{entity['description']}\n\n"
            f"### 证据链与数据基础\n\n{fact_lines}\n\n这些证据的关系是：先由官方平台或标准定义需求和边界，再用结构化表格与券商模型识别规格和市场空间，最后用公司资料和媒体/纪要线索审查具体标的。媒体和纪要只提示方向，不直接升级为客户确认。\n\n"
            f"### 分析\n\n{entity['display_name']} 的关键不是有没有“液冷”两个字，而是能不能把热负荷、CDU 架构、泵规格、客户验证和收入利润串成闭环。若证据只停在平台需求或产品目录，投资逻辑只能说明方向；若进一步看到系统商采购、泵规格锁定、量产验收和财务响应，才说明该实体从需求叙事进入可交易供需机会。当前评分为 {entity['score_point']}，主要因为证据链已经覆盖多个独立来源，但部分标的仍存在客户和收入验证债。\n\n"
            f"### 总结\n\n该实体当前应按条件化研究处理：强证据用于建立机会主线，弱证据用于列补证清单，任何汽车、储能、普通工业泵或整套 CDU 的泛化口径都必须降级。\n\n"
            f"### 相关标的与投资研究建议\n\n相关入口包括：{ '、'.join(target_names) }。投资研究建议是把标的分成系统商确定性、纯泵弹性、部件平台和排除观察四类：系统商看交付和订单，纯泵厂看客户认证和收入，部件平台看收入拆分，排除观察只在公开证据补齐后重新评分。"
        )
        sections.append(
            {
                "entity_key": entity["key"],
                "section_key": "entity_research_profile",
                "section_title": f"{entity['display_name']}研究实体介绍",
                "body_markdown": body,
                "evidence_ref_uri_list": entity["evidence_ref_uri_list"][:10],
                "support_status": "supported",
                "sort_order": 1000 + len(sections) * 10,
            }
        )
    return sections


def make_visuals() -> list[dict[str, Any]]:
    market_targets = [target for target in TARGET_DEFS if target["entity_key"] not in THEORY_RESEARCH_ENTITY_KEYS]
    return [
        {
            "block_key": "customer_validation_matrix_visual",
            "block_type": "table",
            "title": "NVIDIA / Google / 华为客户验证矩阵",
            "subtitle": "区分平台需求、系统商公开验证、泵厂直接供货和验证债。",
            "data": {"what": "客户验证阶段矩阵"},
            "display_data": {
                "columns": ["客户平台", "平台液冷需求", "系统商公开证据", "纯泵厂公开证据", "验证债", "证据"],
                "rows": [
                    ["NVIDIA", "GB200/GB300 全液冷 rack 官方确认", "Vertiv、CoolIT、Schneider/Motivair、Delta 证据较强", "Moog、德昌等为产品能力，未见直接供货确认", "GB300/Rubin 合格供应商和泵 BOM", "NVIDIA、Vertiv、CoolIT"],
                    ["Google", "Ironwood TPU 和冷却演进确认液冷需求", "OCP 和 OEM 侧需继续查", "未见公开泵厂绑定", "Deschutes/OCP、OEM、数据中心项目文件", "Google、OCP"],
                    ["华为", "Atlas 900 A3 SuperPoD 出货确认国产 AI 集群", "英维克、申菱等系统商具备产品能力", "未见纯泵厂公开确认", "华为、超聚变、运营商招投标和验收", "Huawei、英维克、申菱"],
                ],
            },
            "evidence_ref_uri_list": [f"source_ref:{ref}" for ref in ["web_nvidia_gb300_nvl72", "web_vertiv_nvidia_gb200", "web_coolit_chx2000", "web_google_ironwood_tpu", "web_huawei_atlas_a3_superpod"]],
            "support_status": "supported",
            "sort_order": 610,
        },
        {
            "block_key": "tam_sam_som_table",
            "block_type": "table",
            "title": "TAM / SAM / SOM 拆分",
            "subtitle": "把整套液冷系统、CDU 和泵价值分开，避免把 CDU 价格直接当泵价格。",
            "data": {"what": "市场空间口径拆分表"},
            "display_data": {
                "columns": ["层级", "定义", "可用证据", "当前判断", "不能这样用", "证据"],
                "rows": [
                    ["TAM", "AI 数据中心液冷和 CDU 总容量", "NVIDIA、Google、华为平台需求和券商测算", "需求上限确定性较强", "不能等同泵收入", "中泰、NVIDIA、Google、华为"],
                    ["SAM", "CDU 内部泵、冗余泵、泵控和二次侧循环泵", "OCP、Supermicro、Eaton、Moog、德昌规格", "高可靠泵价值存在但 ASP 不透明", "不能把冷板/UQD/manifold 算进泵", "OCP、Eaton、德昌"],
                    ["SOM", "具体公司订单、收入和毛利", "飞龙、英维克、申菱、三花等公司线索", "系统商更确定，纯泵厂弹性待证", "不能用传闻客户名替代收入确认", "飞龙、英维克、申菱、三花"],
                ],
            },
            "evidence_ref_uri_list": [f"source_ref:{ref}" for ref in ["local_zhongtai_liquid_20260528", "web_ocp_l_l_cdu_method", "web_eaton_cdu", "web_johnson_dc_pump"]],
            "support_status": "supported",
            "sort_order": 620,
        },
        {
            "block_key": "target_priority_table",
            "block_type": "table",
            "title": "核心标的优先级和验证债",
            "subtitle": "只展示最重要标的，完整标的进入对应实体页和标的页。",
            "data": {"what": "标的优先级表"},
            "display_data": {
                "columns": ["标的", "类型", "优先级", "核心判断", "验证债", "证据"],
                "rows": [
                    [t["target_name"], t["target_type"], t["priority"], t["relative"], t["risk"], SOURCE_BY_REF[t["source_ref"]]["title"]]
                    for t in market_targets[:14]
                ],
            },
            "evidence_ref_uri_list": [f"source_ref:{t['source_ref']}" for t in market_targets[:10]],
            "support_status": "supported",
            "sort_order": 630,
        },
        {
            "block_key": "boundary_contamination_audit",
            "block_type": "table",
            "title": "产品边界和口径污染审计",
            "subtitle": "防止把汽车、储能、普通工业泵和一次侧水系统误写成 AI rack CDU 泵。",
            "data": {"what": "口径污染审计表"},
            "display_data": {
                "columns": ["污染口径", "为什么危险", "保留条件", "当前处理", "证据"],
                "rows": [
                    ["汽车电子水泵", "运行时长、功率、MTBF、泄漏和流量精度差距大", "披露 AI CDU 泵客户、规格和收入", "只作迁移能力，不作核心证据", "车端泵 vs 服务器端液冷泵表"],
                    ["储能泵", "小泵平台可能已量产但场景不是 AI 数据中心", "收入拆分到 AI 数据中心", "降级为观察", "飞龙产品布局表"],
                    ["普通工业泵", "一次侧或通用水系统和二次侧 CDU 泵不同", "有 TCS/CDU 二次侧规格", "需要补证", "OCP、Wilo、Xylem"],
                    ["整套 CDU 价格", "CDU 包含换热器、控制、过滤、冗余等，泵只占部分", "拆出 pump BOM 或 ASP", "不直接外推", "中泰、LiquidStack"],
                ],
            },
            "evidence_ref_uri_list": [f"source_ref:{ref}" for ref in ["xlsx_vehicle_vs_server_pump", "xlsx_feilong_product_layout", "web_ocp_l_l_cdu_method", "local_zhongtai_liquid_20260528"]],
            "support_status": "supported",
            "sort_order": 640,
        },
        {
            "block_key": "reliability_spec_table",
            "block_type": "table",
            "title": "液冷泵规格和可靠性门槛",
            "subtitle": "这些指标决定 AI 数据中心泵和普通车端/工业泵的本质差异。",
            "data": {"what": "规格门槛表"},
            "display_data": {
                "columns": ["指标", "数值/要求", "说明", "投资含义", "证据"],
                "rows": [
                    ["连续运行", "8760 小时/年", "服务器液冷泵 7x24 不间断", "验证寿命和冗余能力", "结构化表格"],
                    ["设计寿命", "10-15 年", "高于车端口径", "筛掉低可靠泵厂", "结构化表格、OCP"],
                    ["扬程", "4Bar 以上", "高于车端 1-2Bar", "功率和结构设计重新评估", "结构化表格"],
                    ["流量精度", "1%-2%", "需要与 CDU 控制系统深度耦合", "泵控和传感器价值上升", "结构化表格"],
                    ["OCP TCS 压力", "最高 690kPa", "TCS/DECS 部件需满足压力要求", "材料和安全认证形成壁垒", "OCP"],
                    ["德昌示例", "200LPM、250kPa、1800W", "公开数据中心泵规格样本", "作为规格 benchmark", "德昌电机"],
                ],
            },
            "evidence_ref_uri_list": [f"source_ref:{ref}" for ref in ["xlsx_vehicle_vs_server_pump", "xlsx_auto_transfer_barrier", "web_ocp_l_l_cdu_method", "web_johnson_dc_pump"]],
            "support_status": "supported",
            "sort_order": 650,
        },
    ]


def make_early_signals(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    for entity in entities:
        if is_theory_research_entity(entity):
            continue
        signals.append(
            {
                "entity_key": entity["key"],
                "early_signal_score": min(95, entity["score_point"] + 5),
                "early_signal_strength_label": "strong" if entity["score_point"] >= 75 else "medium",
                "research_priority_score": min(96, entity["score_point"] + 8),
                "research_priority_label": entity["research_priority_label"],
                "source_count": entity["source_count"],
                "independent_source_count": entity["independent_source_count"],
                "verification_debt_count": 2 if entity["score_point"] >= 78 else 4,
                "core_score_snapshot": entity["score_point"],
                "evidence_ref_uri_list": entity["evidence_ref_uri_list"][:6],
                "aggregate_trace": {
                    "reason": "freshness_first 策略下，早期信号用于排序补证优先级，不改变核心 14 因子 raw score。",
                    "verification_debt": "客户名单、CDU 内部 pump BOM、收入拆分和项目转批量仍需继续跟踪。",
                },
            }
        )
    return signals


def make_targets() -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for index, target in enumerate(TARGET_DEFS, start=1):
        if target["entity_key"] in THEORY_RESEARCH_ENTITY_KEYS:
            continue
        targets.append(
            {
                "entity_key": target["entity_key"],
                "target_name": target["target_name"],
                "ticker": target.get("ticker"),
                "market": target.get("market"),
                "target_type": target.get("target_type", "company"),
                "company_id": target.get("company_id"),
                "target_url": target.get("target_url"),
                "exposure_rationale": target["exposure"],
                "evidence_ref_uri": f"source_ref:{target['source_ref']}",
                "research_action": f"优先核查：{target['confirmed']} 同时保留证伪动作：{target['falsified']}",
                "investment_view": target["view"],
                "risk_note": target["risk"],
                "target_priority": target["priority"],
                "target_quality_label": target["quality"],
                "relative_preference": target["relative"],
                "confirmed_scenario_action": target["confirmed"],
                "falsified_scenario_action": target["falsified"],
                "target_profile_markdown": f"### 标的介绍\n{target['exposure']}\n\n### 同实体内比较\n{target['relative']}",
                "target_deep_research_markdown": f"### 深入研究\n{target['view']}\n\n关键验证不是概念相关，而是订单、客户、收入、毛利率和规格是否同步出现。{target['risk']}",
                "entity_relation_markdown": f"{target['target_name']} 与本实体的关系是：{target['exposure']}",
                "parent_research_relation_markdown": f"该标的服务于 AI 数据中心液冷泵研究主问题，用来判断需求从平台液冷向具体公司收入和利润传导的强弱。{target['relative']}",
                "conditional_investment_recommendation": f"证实情景：{target['confirmed']} 证伪情景：{target['falsified']}",
                "financial_data_status": "本轮未调用 Wind、Tushare 或 yfinance；财务仅使用既有本地 company_id 和公开材料，后续需用 Tushare/yfinance 只读快照补充。",
                "link_status": "linked" if target.get("company_id") or target.get("target_url") else "external_only",
                "support_status": target.get("support", "partially_supported"),
                "sort_order": index,
                "target_data_points": target_data_points(target),
            }
        )
    return targets


def build_pack() -> dict[str, Any]:
    intake_text = INTAKE_PATH.read_text(encoding="utf-8")
    entities = make_entities()
    pack = {
        "slug": "ai_datacenter_liquid_cooling_pump_20260704_deep_run",
        "research_question": "未来 12 个月至未来 5 年，AI 数据中心液冷泵 / CDU 泵 / 数据中心液体循环泵行业的竞争格局、供需变化、价格体系、客户验证进展和投资机会如何？",
        "run_mode": "c_hybrid",
        "requested_by": "codex_opportunity_lens_flow",
        "problem_statement": "研究 AI 数据中心液冷泵行业是否存在可验证的供需失衡和投资机会，并严格区分平台液冷需求、系统商验证、泵厂直接供货、汽车/储能/工业泵口径污染。",
        "as_of_date": AS_OF_DATE,
        "intake": {
            "research_question": "未来 12 个月至未来 5 年，AI 数据中心液冷泵 / CDU 泵 / 数据中心液体循环泵行业的竞争格局、供需变化、价格体系、客户验证进展和投资机会如何？",
            "available_materials_choice": "B",
            "intake_material_type": "papers_folder",
            "papers_or_report_folder": "papers/数据中心液冷泵",
            "evidence_policy": "freshness_first",
            "primary_material_folder": "papers/数据中心液冷泵",
            "secondary_material_folder": "papers/液冷",
            "intake_text_excerpt": _clip(intake_text, 1800),
        },
        "search_plan_name": "AI 数据中心液冷泵人工核验证据搜索计划",
        "search_plan": [
            {"axis_key": "platform_demand", "source_group": "official", "query_text": "NVIDIA GB300 GB200 Google Ironwood Huawei Atlas liquid cooling rack", "result_count": 12, "included_count": 7},
            {"axis_key": "cdu_pump_boundary", "source_group": "standards", "query_text": "OCP liquid to liquid CDU pump redundancy material compatibility", "result_count": 10, "included_count": 4},
            {"axis_key": "global_system_vendors", "source_group": "company_official", "query_text": "Vertiv CoolIT Motivair Delta Eaton CDU AI data center", "result_count": 18, "included_count": 10},
            {"axis_key": "pump_oems", "source_group": "company_official", "query_text": "Grundfos Wilo Xylem Moog Johnson Electric data center liquid cooling pump", "result_count": 16, "included_count": 8},
            {"axis_key": "china_targets", "source_group": "local_reports_and_public", "query_text": "飞龙 英维克 申菱 三花 南方泵业 数据中心 液冷泵", "result_count": 20, "included_count": 10},
        ],
        "workflow_review_contract": {
            "mode": "produce_then_science_review_loop",
            "expression_style": "金融研究员日常可读，抓重点、讲清推理、专业但不学术化；禁止套模板、禁止空泛总结、禁止只说还要看上下文。",
            "loop_rule": "每个生产 agent 完成后必须立刻接同级 reviewer agent。数据抓取和数据点 agent 由数据核验 agent 检查来源、数字、单位、日期、原文和同源同口径合并；分析 agent 由 science reviewer 检查引用、计算、证据覆盖、反方约束和逻辑链。任一 reviewer 不通过时，打回前一个 agent 全量修订，再重新 reviewer。",
            "final_gate": "发布前必须追加 final science reviewer，统一检查 entity 类型、证据链、研究型数据点、计算、文献综述、分析逻辑、总结是否回答研究问题、展示可读性和无模板重复。",
            "stages": [
                {"producer": "source_discovery_agent", "reviewer": "source_quality_reviewer", "review_focus": "来源可达性、发布方、时间、独立性、资料覆盖是否足够、原文是否支撑入库。"},
                {"producer": "data_point_agent", "reviewer": "data_point_auditor", "review_focus": "数字、单位、日期、同源同口径合并、原文摘录、数据点解释和该数据点在研究问题下说明什么。"},
                {"producer": "analysis_agent", "reviewer": "science_logic_reviewer", "review_focus": "引用证据是否足够，CR3/CR5 等计算是否正确，结论是否由数据推出，是否把信息转成问题解决和投资研究逻辑。"},
                {"producer": "theory_research_agent", "reviewer": "research_note_reviewer", "review_focus": "文献综述是否读够资料，表达是否像研究员日常报告，分析是否深入，回答和总结是否直接回答研究问题。"},
                {"producer": "report_writer_agent", "reviewer": "final_science_reviewer", "review_focus": "整体逻辑、金融研究可读性、表格和页面是否符合实体类型，是否存在套话、空话或旧术语残留。"},
            ],
        },
        "sources": SOURCES,
        "entities": entities,
        "claims": make_claims(),
        "data_points": FACTS,
        "early_signals": make_early_signals(entities),
        "sections": make_sections(entities),
        "visuals": make_visuals(),
        "nav": [
            {"nav_key": "report", "label": "研究报告", "href": "#report", "sort_order": 10},
            {"nav_key": "entities", "label": "研究实体", "href": "#entities", "sort_order": 20},
            {"nav_key": "visuals", "label": "关键表格和矩阵", "href": "#visuals", "sort_order": 30},
            {"nav_key": "targets", "label": "标的研究", "href": "#targets", "sort_order": 40},
        ],
        "supplement_requests": [
            {"entity_key": "customer_validation_matrix", "request_title": "NVIDIA/Google/华为客户验证强补证", "request_detail": "继续查官方 reference design、OCP 文件、ODM/OEM datasheet、招标中标和客户验收，确认 CDU 和泵供应商阶段。", "priority": "p1", "blocking_status": "limits_scoring", "review_status": "pending", "evidence_ref_uri": "source_ref:web_nvidia_gb300_nvl72"},
            {"entity_key": "price_value_chain", "request_title": "CDU 内部泵 BOM 和 ASP 拆分", "request_detail": "寻找泵、冗余泵、控制器、换热器、过滤、机柜型 CDU 和行级 CDU 的 BOM 或成交价格，避免把 CDU 总价当泵价格。", "priority": "p1", "blocking_status": "limits_scoring", "review_status": "pending", "evidence_ref_uri": "source_ref:local_zhongtai_liquid_20260528"},
            {"entity_key": "china_component_targets", "request_title": "中国标的收入和客户拆分", "request_detail": "逐家公司核对公告、互动易、投资者关系和定期报告，把汽车、储能、工业和 AI 数据中心收入拆开。", "priority": "p1", "blocking_status": "limits_scoring", "review_status": "pending", "evidence_ref_uri": "source_ref:web_feilong_sina_20260701"},
        ],
        "audit_issues": [
            {"entity_key": "customer_validation_matrix", "audit_issue_type": "insufficient_independent_confirmation", "audit_severity": "p1", "issue_title": "纯泵厂直接绑定 NVIDIA/Google/华为证据不足", "issue_detail": "当前能确认平台液冷需求和系统商验证，不能把泵厂产品能力或媒体客户线索直接写成量产供货。", "evidence_ref_uri": "source_ref:web_nvidia_gb300_nvl72", "evidence_ref_uri_list": ["source_ref:web_nvidia_gb300_nvl72", "source_ref:web_google_ironwood_tpu", "source_ref:web_huawei_atlas_a3_superpod"]},
            {"entity_key": "price_value_chain", "audit_issue_type": "capacity_definition_conflict", "audit_severity": "p1", "issue_title": "CDU 价值量不能直接等于泵 ASP", "issue_detail": "中泰证券提供的 CDU 约 3 万美元口径包括多项系统部件，泵价值需要拆分冗余、控制和系统商采购模式。", "evidence_ref_uri": "source_ref:local_zhongtai_liquid_20260528", "evidence_ref_uri_list": ["source_ref:local_zhongtai_liquid_20260528", "source_ref:web_liquidstack_cdu_selection"]},
            {"entity_key": "contamination_and_falsification", "audit_issue_type": "theme_mapping_only", "audit_severity": "p1", "issue_title": "汽车、储能和普通工业泵口径污染风险高", "issue_detail": "车端泵和服务器液冷泵在运行时长、MTBF、功率、泄漏和控制上差距大；未拆分收入前不得进入核心结论。", "evidence_ref_uri": "source_ref:xlsx_vehicle_vs_server_pump", "evidence_ref_uri_list": ["source_ref:xlsx_vehicle_vs_server_pump", "source_ref:xlsx_auto_transfer_barrier", "source_ref:web_feilong_sina_20260701"]},
        ],
        "gap_summary": "核心缺口是纯泵厂直接客户确认、CDU 内部泵 BOM/ASP、A 股标的数据中心收入拆分、Google/Huawei 供应链透明度。缺口已转化为补证请求，不影响当前条件化结论发布。",
        "entity_sections": make_entity_sections(entities),
        "entity_investment_targets": make_targets(),
    }
    return pack


def audit_pack(pack: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if len(pack["data_points"]) < 100:
        issues.append(f"数据点不足：{len(pack['data_points'])}")
    duplicate_source_refs = [ref for ref, count in Counter(source["ref"] for source in pack["sources"]).items() if count > 1]
    if duplicate_source_refs:
        issues.append(f"source ref 重复：{duplicate_source_refs}")
    factor_text_by_field: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    interpretations: list[tuple[str, str, str]] = []
    for entity in pack["entities"]:
        is_theory = entity.get("entity_research_mode") == "theory_research"
        if is_theory:
            if entity.get("factor_scores"):
                issues.append(f"{entity['key']} 是研究型实体但仍生成了 factor_scores")
            profile = entity.get("research_profile") or {}
            for field in [
                "research_question",
                "literature_review_markdown",
                "analysis_markdown",
                "answer_markdown",
                "conclusion_markdown",
            ]:
                if not _compact(profile.get(field)):
                    issues.append(f"{entity['key']} 研究型 profile 缺少 {field}")
            required_lengths = {
                "literature_review_markdown": 450,
                "analysis_markdown": 600,
                "answer_markdown": 180,
                "conclusion_markdown": 260,
            }
            for field, minimum in required_lengths.items():
                value = _compact(profile.get(field))
                if len(value) < minimum:
                    issues.append(f"{entity['key']} 研究型 profile {field} 过短：{len(value)} < {minimum}")
            answer_and_conclusion = _compact(profile.get("answer_markdown")) + _compact(profile.get("conclusion_markdown"))
            if "本轮回答是" not in answer_and_conclusion or "结论是" not in answer_and_conclusion:
                issues.append(f"{entity['key']} 研究型回答或总结没有直接回答研究问题")
            research_points = entity.get("research_data_points") or []
            if len(research_points) < 10:
                issues.append(f"{entity['key']} 研究型数据点不足：{len(research_points)}")
            for point in research_points:
                for field in ["data_point_title", "metric", "source_ref", "source_excerpt", "interpretation", "research_use"]:
                    if not _compact(point.get(field)):
                        issues.append(f"{entity['key']} 研究型数据点缺少 {field}")
            continue
        if not entity.get("factor_scores"):
            issues.append(f"{entity['key']} 是市场相关实体但缺少 factor_scores")
        for factor in entity["factor_scores"]:
            refs = set(factor.get("evidence_ref_uri_list", [])) | set(factor.get("source_context_refs", []))
            if len(refs) < 5:
                issues.append(f"{entity['key']} {factor['factor_code']} 证据组不足 {len(refs)}")
            for field in ["factor_value_summary", "source_context_summary", "factor_topic_analysis", "score_rationale"]:
                if not _compact(factor.get(field)):
                    issues.append(f"{entity['key']} {factor['factor_code']} 缺少 {field}")
            for field in [
                "trace",
                "contextual_human_question",
                "source_context_summary",
                "factor_value_summary",
                "factor_topic_analysis",
                "score_rationale",
                "target_implications",
            ]:
                value = _compact(factor.get(field))
                if value:
                    factor_text_by_field[field].append((entity["key"], factor["factor_code"], value))
            for item in factor.get("information_points", []):
                interpretation = _compact(item.get("interpretation"))
                if not interpretation:
                    issues.append(f"{entity['key']} {factor['factor_code']} 信息点缺解读")
                else:
                    interpretations.append((entity["key"], factor["factor_code"], interpretation))
    for target in pack["entity_investment_targets"]:
        if target["entity_key"] in THEORY_RESEARCH_ENTITY_KEYS:
            issues.append(f"研究型实体不应输出标的：{target['entity_key']} / {target['target_name']}")
        if not target.get("target_data_points"):
            issues.append(f"标的缺数据点：{target['target_name']}")
    workflow_contract = pack.get("workflow_review_contract") or {}
    if workflow_contract.get("mode") != "produce_then_science_review_loop":
        issues.append("缺少 producer-reviewer-loop 工作流契约")
    if not _compact(workflow_contract.get("final_gate")):
        issues.append("缺少 final science reviewer 发布前门禁")
    workflow_serialized = json.dumps(workflow_contract, ensure_ascii=False)
    if "文献综述" not in workflow_serialized or "总结是否回答研究问题" not in workflow_serialized:
        issues.append("workflow reviewer 契约未覆盖文献综述和总结回答问题检查")
    for field, rows in factor_text_by_field.items():
        duplicates = [value for value, count in Counter(value for _, _, value in rows).items() if count > 1]
        if duplicates:
            issues.append(f"因子字段 {field} 存在整段重复：{_clip(duplicates[0], 80)}")
    duplicate_interpretations = [
        value for value, count in Counter(value for _, _, value in interpretations).items() if count > 1
    ]
    if duplicate_interpretations:
        issues.append(f"信息卡解读存在整段重复：{_clip(duplicate_interpretations[0], 80)}")
    bad_tokens = [
        "manual_verified_fact",
        "\u8be5\u8bc1\u636e\u5fc5\u987b\u7ed3\u5408\u539f\u59cb\u94fe\u63a5\u5168\u6587",
        "\u4e0d\u80fd\u53ea\u622a\u53d6\u5355\u53e5",
        "\u8be5\u6307\u6807\u8bf4\u660e",
        "\u5b83\u4e0d\u662f\u5b64\u7acb\u6570\u5b57",
        "\u5728\u201c",
        "Lit " + "Review",
        "lit " + "review",
        "Lit " + "review",
        "研究论文式",
        "wind ",
        "Wind ",
    ]
    serialized = json.dumps(pack, ensure_ascii=False)
    for token in bad_tokens:
        if token in serialized:
            issues.append(f"发现禁用或模板残留：{token}")
    action_counter = Counter(target["confirmed_scenario_action"] for target in pack["entity_investment_targets"])
    if any(count > 1 for count in action_counter.values()):
        issues.append("标的证实动作存在重复")
    return issues


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pack = build_pack()
    issues = audit_pack(pack)
    if issues:
        raise SystemExit("run pack 审计失败：\n" + "\n".join(f"- {issue}" for issue in issues))
    out_path = OUT_DIR / "run_pack.json"
    out_path.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    cache = [
        "# AI 数据中心液冷泵 Opportunity Lens 执行缓存",
        "",
        f"- 生成时间：{AS_OF_DATE}",
        f"- source：{len(pack['sources'])}",
        f"- data_point：{len(pack['data_points'])}",
        f"- entity：{len(pack['entities'])}",
        f"- claim：{len(pack['claims'])}",
        f"- target：{len(pack['entity_investment_targets'])}",
        "",
        "核心判断：平台液冷需求强，系统商证据强，纯泵厂直接客户确认不足；投资研究必须按系统商、纯泵厂、部件平台和排除观察分层。",
    ]
    (OUT_DIR / "EXECUTION_CACHE.md").write_text("\n".join(cache) + "\n", encoding="utf-8")
    print(f"wrote {out_path}")
    print(f"sources={len(pack['sources'])} data_points={len(pack['data_points'])} entities={len(pack['entities'])} targets={len(pack['entity_investment_targets'])}")


if __name__ == "__main__":
    main()
