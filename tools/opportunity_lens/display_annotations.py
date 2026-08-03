from __future__ import annotations

import re
from datetime import date
from typing import Any


YEAR_RE = re.compile(r"\b(20\d{2})\b")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
ASCII_WORD_RE = re.compile(r"[A-Za-z]{3,}")
TRANSLATION_MARKERS = (
    "中文译意：",
    "中文译意:",
    "中文译文：",
    "中文译文:",
    "中文说明：",
    "中文说明:",
)


TITLE_TRANSLATIONS = {
    "NVIDIA GB300 NVL72": "NVIDIA GB300 NVL72 平台资料",
    "Ironwood: The first Google TPU for the age of inference": "Ironwood：Google 面向推理时代的首款 TPU",
    "Huawei SuperPoD deployment note": "华为 SuperPoD 部署说明",
    "Huawei Open-Access SuperPoD deployment note": "华为开放式 SuperPoD 部署说明",
    "How Electronic Components Underpin the Growth of the AI-Driven Society": "电子元件如何支撑 AI 驱动社会的增长",
    "Technology guide to enhance power stability in AI-driven data centers": "提升 AI 数据中心供电稳定性的技术指南",
    "Inductor for Power Lines": "电源线用电感",
    "Cyntec Total Solution for AI Server and Switch": "Cyntec 面向 AI 服务器和交换机的整体方案",
    "Cyntec offers space-saving, high-efficiency TLVR inductor for AI server": "Cyntec 面向 AI 服务器的节省空间、高效率 TLVR 电感",
    "YAGEO Group's TPI Series Expanded for AI, Servers, and High-Efficiency Power": "YAGEO Group TPI 系列扩展至 AI、服务器和高效率电源应用",
    "GPU / CPU VRM inductors": "GPU / CPU VRM 电感",
    "AI, Data Center & High-Speed Electronics": "AI、数据中心和高速电子",
    "IHSR - High current SMD inductors": "IHSR 高电流 SMD 电感",
    "Molded powder inductors boost AI computing power": "模压粉末电感提升 AI 计算供电能力",
    "TAIYO YUDEN Integrated Report 2025: Power inductor advances": "太阳诱电 2025 综合报告：功率电感进展",
    "AI quad-phase power modules designed for VPD": "面向 VPD 的 AI 四相电源模块",
    "NVIDIA GB300 NVL72": "NVIDIA GB300 NVL72 平台资料",
    "NVIDIA GB200 NVL72": "NVIDIA GB200 NVL72 平台资料",
    "NVIDIA Contributes GB200 NVL72 Designs to Open Compute Project": "NVIDIA 将 GB200 NVL72 设计贡献给 OCP",
    "AI/ML Cooling Evolution at Google": "Google AI/ML 冷却技术演进",
    "Liquid to Liquid CDU Test Methodology and Performance Rating": "液-液 CDU 测试方法和性能评级",
    "OCP TCS Row Manifolds Pre-Commission Preparation": "OCP TCS 行级歧管预调试准备",
    "Coolant Distribution Units for Data Centers": "数据中心冷却液分配单元",
    "Supermicro In-Rack CDU Datasheet": "Supermicro 机柜内 CDU 数据表",
    "Supermicro In-Row CDU Datasheet": "Supermicro 行级 CDU 数据表",
    "Vertiv codevelops complete power and cooling blueprint for NVIDIA GB200 NVL72": "Vertiv 与 NVIDIA 共研 GB200 NVL72 电力和冷却蓝图",
    "CoolIT Systems announces CHx2000 row-based CDU": "CoolIT 发布 CHx2000 行级 CDU",
    "CoolIT liquid cooling solutions for NVIDIA AI factories": "CoolIT 面向 NVIDIA AI 工厂的液冷方案",
    "Motivair by Schneider Electric announces MCDU-70 CDU": "Schneider Electric 旗下 Motivair 发布 MCDU-70 CDU",
    "Schneider Electric acquires Motivair": "Schneider Electric 收购 Motivair",
    "Motivair by Schneider Electric expands U.S. manufacturing footprint": "Motivair 扩大美国制造布局",
    "Data Center Cooling Solutions": "数据中心冷却解决方案",
    "Coolant Distribution Unit for Data Centers": "数据中心 CDU 冷却液分配单元",
    "Chilldyne Reference Design for AI NVIDIA NVL72": "Chilldyne 面向 NVIDIA NVL72 的 AI 液冷参考设计",
    "IT Cooling and immersion cooling pump solutions": "IT 冷却和浸没式冷却泵方案",
    "Data Centers Cooling Pumps": "数据中心冷却泵",
    "The Critical Role of Pumps in Data Center Cooling": "泵在数据中心冷却中的关键作用",
    "Data Centers water and hydronic cooling solutions": "数据中心水力和水冷解决方案",
    "Liquid Cooling Solutions for Data Centers": "数据中心液冷方案",
    "How to choose the right CDU for your data center": "如何为数据中心选择合适的 CDU",
    "Data Center Cooling CDU Pumps Market": "数据中心冷却 CDU 泵市场",
}


PHRASE_TRANSLATIONS = {
    "NVIDIA GB300 NVL72 integrates 72 Blackwell Ultra GPUs and 36 Grace CPUs; it is a fully liquid-cooled rack-scale AI system.": (
        "NVIDIA GB300 NVL72 集成 72 个 Blackwell Ultra GPU 和 36 个 Grace CPU，是全液冷、机架级 AI 系统。"
    ),
    "Google introduced Ironwood as its seventh-generation TPU for inference; the pod can scale to 9,216 liquid-cooled chips.": (
        "Google 发布第七代推理 TPU Ironwood；单个 pod 可扩展到 9,216 个液冷芯片。"
    ),
    "Huawei said Atlas 900 A3 SuperPoD packs up to 384 Ascend 910C chips and that more than 300 units had been deployed in 2025.": (
        "华为称 Atlas 900 A3 SuperPoD 最多包含 384 个 Ascend 910C 芯片，2025 年已部署超过 300 台。"
    ),
    "Huawei reported more than 300 Atlas 900 A3 SuperPoD deliveries in 2025 across over 20 customers.": (
        "华为披露 2025 年已交付超过 300 台 Atlas 900 A3 SuperPoD，并部署于 20 多个客户。"
    ),
    "Huawei reported more than 300 Atlas 900 A3 SuperPoD units shipped in 2025 and deployed across more than 20 customers.": (
        "华为披露 2025 年 Atlas 900 A3 SuperPoD 出货超过 300 台，并在 20 多个客户中部署。"
    ),
    "TDK said AI servers need reliable power and noise suppression; its inductors are used for voltage conversion and GPU power stability.": (
        "TDK 表示 AI 服务器需要可靠供电和噪声抑制，其电感用于电压转换和 GPU 稳定供电。"
    ),
    "TDK said AI servers need reliable power and noise suppression; its inductors support voltage conversion and stable GPU power delivery.": (
        "TDK 表示 AI 服务器需要可靠供电和噪声抑制，其电感支持电压转换和 GPU 稳定供电。"
    ),
    "Murata launched an AI server power delivery guide describing inductors and related components for evolving power layouts.": (
        "Murata 发布 AI 服务器供电指南，说明其用电感等元件支持不断演进的供电布局架构。"
    ),
    "Murata launched an AI server power delivery guide and said it supports evolving power placement architectures with inductors and other components.": (
        "Murata 发布 AI 服务器供电指南，并表示其通过电感等元件支持持续演进的供电布局架构。"
    ),
    "Murata states power inductors require high current capability, DC superposition characteristics, miniaturization and metal alloy materials.": (
        "Murata 表示功率电感需要大电流能力、直流叠加特性、小型化和金属合金材料。"
    ),
    "Murata states power inductors require high-current capability, DC superimposition characteristics, compact size, and metal alloy materials.": (
        "Murata 表示功率电感需要大电流能力、直流叠加特性、紧凑尺寸和金属合金材料。"
    ),
    "Cyntec developed compact, high-efficiency, low-loss power inductors for AI server SXM accelerator cards, UBB motherboards, and Switch.": (
        "Cyntec 开发了紧凑、高效率、低损耗功率电感，用于 AI 服务器 SXM 加速卡、UBB 主板和交换机。"
    ),
    "Cyntec TLVR inductors cover 70nH to 200nH, 0.125mΩ DCR, and saturation currents over 70A.": (
        "Cyntec TLVR 电感覆盖 70nH 至 200nH、0.125mΩ DCR 和 70A 以上饱和电流。"
    ),
    "YAGEO Group's TPI Series SMD ferrite core inductors expanded to meet growing power demands of next-generation computing platforms.": (
        "YAGEO Group 的 TPI 系列 SMD 铁氧体磁芯电感扩展至满足下一代计算平台不断增长的供电需求。"
    ),
    "Modern GPUs and CPUs draw hundreds of amps with extremely fast load transients, making VRM inductor performance a primary factor.": (
        "现代 GPU 和 CPU 会以极快负载瞬态吸收数百安培电流，因此 VRM 电感性能成为关键因素。"
    ),
    "Advanced power inductors and EMI filters for AI servers, 48V data center architectures, and GPU/CPU VRM power stages.": (
        "面向 AI 服务器、48V 数据中心架构和 GPU/CPU VRM 功率级的先进功率电感与 EMI 滤波器。"
    ),
    "IHSR features ultra-low DCR, low inductance, and small size for datacenter, AI computing, and GPUs applications.": (
        "Vishay IHSR 具备超低 DCR、低电感和小尺寸，面向数据中心、AI 计算和 GPU 应用。"
    ),
    "Eaton says molded powder inductors improve efficiency and heat dissipation, minimize power losses, and ensure long-term operation.": (
        "Eaton 表示模压粉末电感可改善效率和散热、降低功率损耗，并支持长期运行。"
    ),
    "TAIYO YUDEN will focus on high-value-added zones such as AI servers and automobiles in power inductor growth strategies.": (
        "太阳诱电表示功率电感增长战略将聚焦 AI 服务器和汽车等高附加值区域。"
    ),
    "Infineon says OptiMOS quad-phase power modules target AI data centers and enable true vertical power delivery.": (
        "Infineon 表示 OptiMOS 四相电源模块面向 AI 数据中心，并支持真正的垂直供电。"
    ),
    "The NVIDIA GB300 NVL72 features a fully liquid-cooled, rack-scale architecture that integrates 72 NVIDIA Blackwell Ultra GPUs and 36 Arm-based NVIDIA Grace CPUs into a single platform.": (
        "NVIDIA GB300 NVL72 采用全液冷机架级架构，将 72 个 Blackwell Ultra GPU 和 36 个 Grace CPU 集成到单一平台。"
    ),
    "NVIDIA GB200 NVL72 connects 36 Grace CPUs and 72 Blackwell GPUs in a rack-scale, liquid-cooled design.": (
        "NVIDIA GB200 NVL72 在液冷机架级设计中连接 36 个 Grace CPU 和 72 个 Blackwell GPU。"
    ),
    "NVIDIA contributed NVIDIA GB200 NVL72 rack and liquid-cooled compute tray designs to the Open Compute Project and worked with partners on reference architectures.": (
        "NVIDIA 将 GB200 NVL72 机架和液冷计算托盘设计贡献给 OCP，并与合作伙伴推进参考架构。"
    ),
    "Ironwood is Google's seventh-generation TPU, built for inference, and can scale up to 9,216 chips in a single pod.": (
        "Ironwood 是 Google 第七代推理 TPU，单个 pod 可扩展到 9,216 个芯片。"
    ),
    "Google's AI/ML cooling presentation lists Ironwood 2025 and describes heat out through air and liquid paths for next generation AI systems.": (
        "Google AI/ML 冷却材料列出 2025 年 Ironwood，并说明下一代 AI 系统通过空气和液体两条路径带走热量。"
    ),
    "Huawei reported that more than 300 Atlas 900 A3 SuperPoD units had been shipped in 2025 and deployed by more than 20 customers.": (
        "华为披露 2025 年 Atlas 900 A3 SuperPoD 出货超过 300 台，并部署于 20 多个客户。"
    ),
    "Coolant Distribution Unit is a key ingredient of the liquid cooling system, and it isolates the facility side of cooling loop from the IT side flow network.": (
        "CDU 是液冷系统的关键部件，用于隔离设施侧冷却回路和 IT 侧流体网络。"
    ),
    "The document describes secondary cooling loops for coolant to pass through to the racks and focuses on preparation of TCS row manifolds before commissioning.": (
        "该文件描述冷却液通向机柜的二次侧冷却回路，并聚焦 TCS 行级歧管调试前准备。"
    ),
    "UL describes CDUs designed for data centers using non-refrigerant coolants and maps safety certification to UL/CAN/IEC 62368-1.": (
        "UL 说明数据中心 CDU 使用非制冷剂冷却液，并把安全认证映射到 UL/CAN/IEC 62368-1。"
    ),
    "Supermicro's in-rack CDU data sheet lists up to 250kW cooling capacity and redundant pump, MCU and power supply architecture.": (
        "Supermicro 机柜内 CDU 数据表列出最高 250kW 冷却能力，以及冗余泵、MCU 和电源架构。"
    ),
    "Supermicro's in-row CDU data sheet lists cooling capacity up to 1.8MW, N+1 pumps, Redfish or SNMP monitoring and high density rack support.": (
        "Supermicro 行级 CDU 数据表列出最高 1.8MW 冷却能力、N+1 泵、Redfish 或 SNMP 监控和高密度机柜支持。"
    ),
    "Vertiv's reference architecture supports the NVIDIA GB200 NVL72 liquid-cooled rack-scale platform at up to 132kW per rack.": (
        "Vertiv 参考架构支持 NVIDIA GB200 NVL72 液冷机架级平台，单机柜最高 132kW。"
    ),
    "CoolIT says the CHx2000 provides 2MW of liquid cooling capacity and 1.2LPM per kW, supporting up to twelve 120kW NVIDIA GB200 NVL72 racks.": (
        "CoolIT 称 CHx2000 提供 2MW 液冷能力和 1.2LPM/kW 流量，可支持最多 12 个 120kW NVIDIA GB200 NVL72 机柜。"
    ),
    "CoolIT describes co-innovation with NVIDIA across cold plates and CDUs for Blackwell and AI factory liquid cooling deployments.": (
        "CoolIT 描述其与 NVIDIA 在 Blackwell 和 AI 工厂液冷部署中的冷板和 CDU 协同创新。"
    ),
    "Motivair by Schneider Electric announced a CDU platform ranging from 105kW to 2.5MW and designed to scale to 10MW and beyond for next-generation AI factories.": (
        "Schneider Electric 旗下 Motivair 发布 105kW 至 2.5MW 的 CDU 平台，并设计为可扩展至 10MW 以上的下一代 AI 工厂。"
    ),
    "Schneider Electric said Motivair is a global provider of advanced liquid cooling solutions for high performance computing and AI data centers.": (
        "Schneider Electric 表示 Motivair 是面向高性能计算和 AI 数据中心的先进液冷解决方案全球供应商。"
    ),
    "Motivair expanded its U.S. manufacturing footprint to support AI and HPC liquid cooling demand.": (
        "Motivair 扩大美国制造布局，以支持 AI 和 HPC 液冷需求。"
    ),
    "Delta says AI and HPC workloads push thermal limits and lists liquid-to-air and liquid-to-liquid CDUs for demanding GPU and CPU applications.": (
        "台达表示 AI 和 HPC 负载推动热管理极限，并列出面向高要求 GPU 和 CPU 应用的液-气、液-液 CDU。"
    ),
    "Eaton's CDU page highlights seal-less N+1 redundant pumps, filtration, pressure testing and serviceability for data center liquid cooling.": (
        "Eaton CDU 页面强调无轴封 N+1 冗余泵、过滤、压力测试和面向数据中心液冷的可维护性。"
    ),
    "Chilldyne's reference design lists CDU-300 for up to 300kW and CDU-1500 for up to 1.5MW liquid cooling capacity.": (
        "Chilldyne 参考设计列出 CDU-300 最高 300kW、CDU-1500 最高 1.5MW 液冷能力。"
    ),
    "Grundfos positions intelligent pumps, sensors and HVAC water solutions for data centers, including liquid cooling and uptime requirements.": (
        "格兰富把智能泵、传感器和 HVAC 水系统方案定位于数据中心，并覆盖液冷和 uptime 要求。"
    ),
    "Grundfos describes active redundancy, pump controls and support for in-row CDUs, immersion cooling and IT cooling loops.": (
        "格兰富描述主动冗余、泵控制，以及对行级 CDU、浸没式冷却和 IT 冷却回路的支持。"
    ),
    "Wilo says its pumps support chilled water circulation, direct-to-chip liquid cooling, immersion cooling and CDU systems in data centers.": (
        "威乐表示其泵支持数据中心冷冻水循环、直连芯片液冷、浸没式冷却和 CDU 系统。"
    ),
    "Wilo describes mission-critical pump requirements, stainless steel construction, dielectric fluid compatibility and high reliability for data center cooling.": (
        "威乐描述数据中心冷却中的任务关键型泵要求、不锈钢结构、介电流体兼容性和高可靠性。"
    ),
    "Xylem presents hydronic cooling, water treatment, filtration and monitoring as data center solutions to reduce downtime and resource use.": (
        "赛莱默把水力冷却、水处理、过滤和监控作为减少停机和资源消耗的数据中心方案。"
    ),
    "Moog says CoreMotion magnetic pumps for direct-to-chip and immersion cooling minimize size, eliminate rotating seals and reduce leak points.": (
        "Moog 表示 CoreMotion 磁力泵面向直连芯片和浸没式冷却，可缩小尺寸、消除旋转密封并减少泄漏点。"
    ),
    "LiquidStack says CDU selection should consider thermal capacity, flow rate, pump head, facility integration and total cost of ownership rather than only headline purchase price.": (
        "LiquidStack 表示 CDU 选型应考虑热容量、流量、泵扬程、设施集成和总拥有成本，而不是只看采购价格。"
    ),
    "The market report estimates the data center cooling CDU pumps market at USD 320 million in 2025, but the definition must be checked because market reports may mix rack CDU, centrifugal pumps and magnetic pumps.": (
        "该市场报告估计 2025 年数据中心冷却 CDU 泵市场为 3.2 亿美元，但口径可能混合 rack CDU、离心泵和磁力泵，必须复核定义。"
    ),
}


def _compact(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def year_from_values(*values: Any) -> int | None:
    years: list[int] = []
    for value in values:
        for match in YEAR_RE.findall(str(value or "")):
            try:
                years.append(int(match))
            except ValueError:
                continue
    return min(years) if years else None


def freshness_warning(*values: Any) -> str | None:
    year = year_from_values(*values)
    if year is None:
        return None
    current_year = max(date.today().year, 2026)
    if year <= current_year - 2:
        return (
            f"严重警惕：该数据或来源时间为 {year} 年，距当前研究时点已偏旧，"
            "不能单独作为最新判断；必须用 2025/2026 年订单、IR、财报、公告或官方数据复核。"
        )
    return None


def is_english_text(text: Any, language: Any = None) -> bool:
    lang = str(language or "").lower()
    source = _compact(text)
    if not source:
        return False
    cjk_count = len(CJK_RE.findall(source))
    ascii_words = ASCII_WORD_RE.findall(source)
    ascii_letters = sum(len(word) for word in ascii_words)
    if lang.startswith("en"):
        return ascii_letters >= 12 and ascii_letters >= max(12, cjk_count * 2)
    return ascii_letters >= 24 and ascii_letters > cjk_count * 3


def chinese_translation(text: Any, language: Any = None) -> str | None:
    source = _compact(text)
    if not source:
        return None
    for marker in TRANSLATION_MARKERS:
        if marker in source:
            translated = source.split(marker, 1)[1].strip()
            if len(CJK_RE.findall(translated)) >= 4:
                return translated
    if source in TITLE_TRANSLATIONS:
        return TITLE_TRANSLATIONS[source]
    if source in PHRASE_TRANSLATIONS:
        return PHRASE_TRANSLATIONS[source]
    if not is_english_text(source, language):
        return None
    if len(CJK_RE.findall(source)) >= 8:
        # 标题或摘要本身已经是中英混排的人读文本，不再追加“未命中翻译”占位。
        return None
    for phrase, translation in PHRASE_TRANSLATIONS.items():
        if phrase in source:
            return translation
    for title, translation in TITLE_TRANSLATIONS.items():
        if title in source:
            return translation
    return f"英文来源中文说明：该字段来自英文材料，当前未命中人工译句；请以英文原文为准，阅读时需人工补充完整中文译文。原文要点：{source[:180]}"


def source_original_text(text: Any) -> str:
    """Return the original-language segment from legacy bilingual fields."""
    source = _compact(text)
    positions = [source.find(marker) for marker in TRANSLATION_MARKERS if marker in source]
    if positions:
        return source[: min(positions)].strip()
    return source
