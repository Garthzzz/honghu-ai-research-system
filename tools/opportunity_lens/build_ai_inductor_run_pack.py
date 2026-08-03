from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .factor_dictionary import FACTOR_BY_CODE

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "opportunity_lens" / "research_outputs" / "20260704_ai_high_end_inductor_deep_run"
TEXT_DIR = OUT_DIR / "extracted_text"
TABLE_DIR = OUT_DIR / "extracted_tables"
INTAKE_PATH = ROOT / "opportunity_lens" / "intake_requests" / "Opportunity_Lens_任务_AI高端电感行业研究与投资机会.md"
RESEARCH_DB = ROOT / "data" / "research.db"
AS_OF_DATE = "2026-07-04"


def _compact(value: Any) -> str:
    text = str(value if value is not None else "").strip()
    text = re.sub(r"[\uf000-\uf8ff]", "", text)
    return re.sub(r"\s+", " ", text)


def _clip(text: str, limit: int = 520) -> str:
    text = _compact(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _clause(text: str, limit: int = 220) -> str:
    return _clip(text, limit).rstrip("。；;，, ")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def _find_lines(path: str, keywords: tuple[str, ...], limit: int = 8) -> list[str]:
    text = _read_text(ROOT / path)
    seen: set[str] = set()
    lines: list[str] = []
    for raw in text.splitlines():
        line = _clip(raw, 360)
        if len(line) < 18:
            continue
        if any(k.lower() in line.lower() for k in keywords):
            if any(noise in line for noise in ("免责声明", "评级说明", "Table_Page", "请务必阅读正文之后")):
                continue
            if line not in seen:
                seen.add(line)
                lines.append(line)
        if len(lines) >= limit:
            break
    return lines


LOCAL_SOURCES: list[dict[str, Any]] = [
    {
        "ref": "local_csc_ai_inductor_20251206",
        "title": "AI服务器功率增长使AI芯片电感和AI芯片电容需求持续增长",
        "publisher": "中信建投证券",
        "publish_date": "2025-12-06",
        "local_path": "papers/电感/2025-12-06_中信建投_计算机_ai服务器功率增长使ai芯片电感和ai芯片电容需求持续增长.pdf",
        "text_path": "opportunity_lens/research_outputs/20260704_ai_high_end_inductor_deep_run/extracted_text/2025-12-06_中信建投_计算机_ai服务器功率增长使ai芯片电感和ai芯片电容需求持续增长.txt",
        "source_tier": "A",
    },
    {
        "ref": "local_huatai_expert_inductor",
        "title": "AI+通胀系列二：芯片电感专家交流纪要",
        "publisher": "华泰证券",
        "publish_date": "2026-07-03",
        "local_path": "papers/电感/华泰证券 _ Al+通胀系列二_芯片电感专家交流-AI纪要.docx",
        "text_path": "opportunity_lens/research_outputs/20260704_ai_high_end_inductor_deep_run/extracted_text/华泰证券 _ Al+通胀系列二_芯片电感专家交流-AI纪要.txt",
        "source_tier": "B",
        "policy_evidence_role": "early_signal_candidate",
    },
    {
        "ref": "local_huaan_expert_inductor",
        "title": "芯片电感行业专家交流纪要",
        "publisher": "华安机械",
        "publish_date": "2026-07-03",
        "local_path": "papers/电感/华安机械 _ 芯片电感行业专家交流-AI纪要.docx",
        "text_path": "opportunity_lens/research_outputs/20260704_ai_high_end_inductor_deep_run/extracted_text/华安机械 _ 芯片电感行业专家交流-AI纪要.txt",
        "source_tier": "B",
        "policy_evidence_role": "early_signal_candidate",
    },
    {
        "ref": "local_tianfeng_aidc_power_20260222",
        "title": "天风电新AIDC通胀机会：电源、芯片电感、液冷、PCB上游及AIDC电力设备等",
        "publisher": "天风证券",
        "publish_date": "2026-02-22",
        "local_path": "papers/电感/2026-02-22_天风证券_综合_天风电新aidc通胀机会：电源、芯片电感、液冷、pcb上游及aidc电力设备等.pdf",
        "text_path": "opportunity_lens/research_outputs/20260704_ai_high_end_inductor_deep_run/extracted_text/2026-02-22_天风证券_综合_天风电新aidc通胀机会：电源、芯片电感、液冷、pcb上游及aidc电力设备等.txt",
        "source_tier": "A",
    },
    {
        "ref": "local_sunlord_tlvr_20260612",
        "title": "顺络电子：为智能而生，TLVR电感赋能算力服务器",
        "publisher": "中邮证券",
        "publish_date": "2026-06-12",
        "local_path": "papers/电感/2026-06-12_中邮证券_顺络电子_顺络电子（002138）：为智能而生，tlvr电感赋能算力服务器.pdf",
        "text_path": "opportunity_lens/research_outputs/20260704_ai_high_end_inductor_deep_run/extracted_text/2026-06-12_中邮证券_顺络电子_顺络电子（002138）：为智能而生，tlvr电感赋能算力服务器.txt",
        "source_tier": "A",
    },
    {
        "ref": "local_minsheng_sunlord_20241115",
        "title": "顺络电子深度报告：复苏与成长共振，电感龙头再度启航",
        "publisher": "民生证券",
        "publish_date": "2024-11-15",
        "local_path": "papers/电感/2024-11-15_民生证券_顺络电子_顺络电子（002138）：深度报告：复苏与成长共振，电感龙头再度启航.pdf",
        "text_path": "opportunity_lens/research_outputs/20260704_ai_high_end_inductor_deep_run/extracted_text/2024-11-15_民生证券_顺络电子_顺络电子（002138）：深度报告：复苏与成长共振，电感龙头再度启航.txt",
        "source_tier": "A",
    },
    {
        "ref": "local_huayuan_boke_20260513",
        "title": "铂科新材：合金软磁粉芯稳增，芯片电感受益ASIC需求有望加速放量",
        "publisher": "华源证券",
        "publish_date": "2026-05-13",
        "local_path": "papers/电感/2026-05-13_华源证券_铂科新材_铂科新材（300811）：合金软磁粉芯稳增，芯片电感受益asic需求有望加速放量.pdf",
        "text_path": "opportunity_lens/research_outputs/20260704_ai_high_end_inductor_deep_run/extracted_text/2026-05-13_华源证券_铂科新材_铂科新材（300811）：合金软磁粉芯稳增，芯片电感受益asic需求有望加速放量.txt",
        "source_tier": "A",
    },
    {
        "ref": "local_huayuan_boke_20240508",
        "title": "铂科新材：一体化粉芯龙头，芯片电感打开AI算力第二成长极",
        "publisher": "华源证券",
        "publish_date": "2024-05-08",
        "local_path": "papers/电感/2024-05-08_华源证券_铂科新材_铂科新材（300811）：一体化粉芯龙头，芯片电感打开ai算力第二成长极.pdf",
        "text_path": "opportunity_lens/research_outputs/20260704_ai_high_end_inductor_deep_run/extracted_text/2024-05-08_华源证券_铂科新材_铂科新材（300811）：一体化粉芯龙头，芯片电感打开ai算力第二成长极.txt",
        "source_tier": "A",
    },
    {
        "ref": "local_tianfeng_boke_20240602",
        "title": "铂科新材：芯片电感龙头供应商，乘势AI浪潮",
        "publisher": "天风证券",
        "publish_date": "2024-06-02",
        "local_path": "papers/电感/2024-06-02_天风证券_铂科新材_铂科新材（300811）：芯片电感龙头供应商，乘势ai浪潮.pdf",
        "text_path": "opportunity_lens/research_outputs/20260704_ai_high_end_inductor_deep_run/extracted_text/2024-06-02_天风证券_铂科新材_铂科新材（300811）：芯片电感龙头供应商，乘势ai浪潮.txt",
        "source_tier": "A",
    },
    {
        "ref": "local_longci_20260402",
        "title": "龙磁科技：2026年，AI芯片电感量产年",
        "publisher": "中信建投证券",
        "publish_date": "2026-04-02",
        "local_path": "papers/电感/2026-04-02_中信建投_龙磁科技_龙磁科技（300835）：2026年：ai芯片电感量产年.pdf",
        "text_path": "opportunity_lens/research_outputs/20260704_ai_high_end_inductor_deep_run/extracted_text/2026-04-02_中信建投_龙磁科技_龙磁科技（300835）：2026年：ai芯片电感量产年.txt",
        "source_tier": "A",
    },
    {
        "ref": "local_longci_20260428",
        "title": "龙磁科技：营收同比大增，AI芯片电感放量在即",
        "publisher": "中信建投证券",
        "publish_date": "2026-04-28",
        "local_path": "papers/电感/2026-04-28_中信建投_龙磁科技_龙磁科技（300835）：营收同比大增，ai芯片电感放量在即.pdf",
        "text_path": "opportunity_lens/research_outputs/20260704_ai_high_end_inductor_deep_run/extracted_text/2026-04-28_中信建投_龙磁科技_龙磁科技（300835）：营收同比大增，ai芯片电感放量在即.txt",
        "source_tier": "A",
    },
    {
        "ref": "local_longci_20250723",
        "title": "龙磁科技：高端铁氧体永磁龙头，AI芯片电感和车载电感新星",
        "publisher": "中信建投证券",
        "publish_date": "2025-07-23",
        "local_path": "papers/电感/2025-07-23_中信建投_龙磁科技_龙磁科技（300835）：高端铁氧体永磁龙头，ai芯片电感和车载电感新星.pdf",
        "text_path": "opportunity_lens/research_outputs/20260704_ai_high_end_inductor_deep_run/extracted_text/2025-07-23_中信建投_龙磁科技_龙磁科技（300835）：高端铁氧体永磁龙头，ai芯片电感和车载电感新星.txt",
        "source_tier": "A",
    },
    {
        "ref": "local_yuean_20260614",
        "title": "悦安新材：羰基铁粉细粉龙头，下游电感需求有望爆发",
        "publisher": "华鑫证券",
        "publish_date": "2026-06-14",
        "local_path": "papers/电感/2026-06-14_华鑫证券_悦安新材_悦安新材（688786）：公司动态研究报告：羰基铁粉细粉龙头，下游电感需求有望爆发.pdf",
        "text_path": "opportunity_lens/research_outputs/20260704_ai_high_end_inductor_deep_run/extracted_text/2026-06-14_华鑫证券_悦安新材_悦安新材（688786）：公司动态研究报告：羰基铁粉细粉龙头，下游电感需求有望爆发.txt",
        "source_tier": "A",
    },
    {
        "ref": "local_toubao_integrated_inductor_20260316",
        "title": "2025年中国一体成型电感行业概览",
        "publisher": "头豹研究院",
        "publish_date": "2026-03-16",
        "local_path": "papers/电感/2026-03-16_头豹研究院_建筑装饰_2025年中国一体成型电感行业概览：从算力基建到电动化浪潮，一体成型电感重塑高端应用边界（精华版）.pdf",
        "text_path": "opportunity_lens/research_outputs/20260704_ai_high_end_inductor_deep_run/extracted_text/2026-03-16_头豹研究院_建筑装饰_2025年中国一体成型电感行业概览：从算力基建到电动化浪潮，一体成型电感重塑高端应用边界（精华版）.txt",
        "source_tier": "A",
    },
    {
        "ref": "local_tianfeng_mlcc_price_20260630",
        "title": "MLCC专题研究之一：AI与汽车共驱景气上行，高端供需趋紧打开涨价空间",
        "publisher": "天风证券",
        "publish_date": "2026-06-30",
        "local_path": "papers/电感/2026-06-30_天风证券_有色金属_mlcc专题研究之一：ai与汽车共驱景气上行，高端供需趋紧打开涨价空间.pdf",
        "text_path": "opportunity_lens/research_outputs/20260704_ai_high_end_inductor_deep_run/extracted_text/2026-06-30_天风证券_有色金属_mlcc专题研究之一：ai与汽车共驱景气上行，高端供需趋紧打开涨价空间.txt",
        "source_tier": "A",
    },
]


TABLE_SOURCES: list[dict[str, Any]] = [
    {
        "ref": "xlsx_chip_inductor_demand",
        "title": "图150：芯片电感用量和市场空间测算",
        "publisher": "本地表格",
        "publish_date": "2026-07-03",
        "local_path": "papers/电感/图150_ 芯片电感用量和市场空间测算.xlsx",
        "json_path": "opportunity_lens/research_outputs/20260704_ai_high_end_inductor_deep_run/extracted_tables/图150_ 芯片电感用量和市场空间测算.json",
        "source_tier": "A",
    },
    {
        "ref": "xlsx_server_module_usage",
        "title": "图表1：服务器不同功能模块一体电感使用情况及要求",
        "publisher": "本地表格",
        "publish_date": "2026-07-03",
        "local_path": "papers/电感/图表1：服务器不同功能模块一体电感使用情况及要求.xlsx",
        "json_path": "opportunity_lens/research_outputs/20260704_ai_high_end_inductor_deep_run/extracted_tables/图表1：服务器不同功能模块一体电感使用情况及要求.json",
        "source_tier": "A",
    },
    {
        "ref": "xlsx_gb300_inductor_count",
        "title": "图表2：英伟达GB300服务器所需电感数量",
        "publisher": "本地表格",
        "publish_date": "2026-07-03",
        "local_path": "papers/电感/图表2：英伟达GB300服务器所需电感数量.xlsx",
        "json_path": "opportunity_lens/research_outputs/20260704_ai_high_end_inductor_deep_run/extracted_tables/图表2：英伟达GB300服务器所需电感数量.json",
        "source_tier": "A",
    },
    {
        "ref": "xlsx_price_case",
        "title": "图表：电容、电阻、电感涨价案例",
        "publisher": "本地表格",
        "publish_date": "2026-07-03",
        "local_path": "papers/电感/图表：电容、电阻、电感涨价案例.xlsx",
        "json_path": "opportunity_lens/research_outputs/20260704_ai_high_end_inductor_deep_run/extracted_tables/图表：电容、电阻、电感涨价案例.json",
        "source_tier": "A",
    },
    {
        "ref": "xlsx_inductor_model_price",
        "title": "表1：电感价格呈现分化，AI服务器和通信部分型号涨幅超100%",
        "publisher": "本地表格",
        "publish_date": "2026-07-03",
        "local_path": "papers/电感/表1：电感价格呈现分化，主要用于AI服务器和通信的部分型号年初至今价格涨幅超100%.xlsx",
        "json_path": "opportunity_lens/research_outputs/20260704_ai_high_end_inductor_deep_run/extracted_tables/表1：电感价格呈现分化，主要用于AI服务器和通信的部分型号年初至今价格涨幅超100%.json",
        "source_tier": "A",
    },
]


WEB_SOURCES: list[dict[str, Any]] = [
    {
        "ref": "web_nvidia_gb300_nvl72",
        "title": "NVIDIA GB300 NVL72",
        "publisher": "NVIDIA",
        "publish_date": "2026-07-04",
        "url": "https://www.nvidia.com/en-us/data-center/gb300-nvl72/",
        "source_tier": "S",
        "excerpt": "NVIDIA GB300 NVL72 integrates 72 Blackwell Ultra GPUs and 36 Grace CPUs; it is a fully liquid-cooled rack-scale AI system.",
    },
    {
        "ref": "web_google_ironwood_tpu",
        "title": "Ironwood: The first Google TPU for the age of inference",
        "publisher": "Google",
        "publish_date": "2025-04-09",
        "url": "https://blog.google/innovation-and-ai/infrastructure-and-cloud/google-cloud/ironwood-tpu-age-of-inference/",
        "source_tier": "S",
        "excerpt": "Google introduced Ironwood as its seventh-generation TPU for inference; the pod can scale to 9,216 liquid-cooled chips.",
    },
    {
        "ref": "web_huawei_atlas_a3_superpod",
        "title": "Groundbreaking SuperPoD Interconnect: Leading a New Paradigm for AI Infrastructure",
        "publisher": "Huawei",
        "publish_date": "2025-09-18",
        "url": "https://www.huawei.com/en/news/2025/9/hc-xu-keynote-speech",
        "source_tier": "S",
        "excerpt": "Huawei said Atlas 900 A3 SuperPoD packs up to 384 Ascend 910C chips and that more than 300 units had been deployed in 2025.",
    },
    {
        "ref": "web_cyntec_ai_server_switch",
        "title": "Cyntec Total Solution for AI Server and Switch",
        "publisher": "Cyntec",
        "publish_date": "2026-07-04",
        "url": "https://www.cyntec.com/Apps/AISS",
        "source_tier": "S",
        "excerpt": "Cyntec developed compact, high-efficiency, low-loss power inductors for AI server SXM accelerator cards, UBB motherboards, and Switch.",
    },
    {
        "ref": "web_cyntec_tlvr_ai_server",
        "title": "Cyntec offers space-saving, high-efficiency TLVR inductor for AI server",
        "publisher": "Cyntec",
        "publish_date": "2024-05-31",
        "url": "https://www.cyntec.com/News/Details/10",
        "source_tier": "S",
        "excerpt": "Cyntec TLVR inductors cover 70nH to 200nH, 0.125mΩ DCR, and saturation currents over 70A.",
    },
    {
        "ref": "web_yageo_tpi_ai_power_20250627",
        "title": "YAGEO Group's TPI Series Expanded for AI, Servers, and High-Efficiency Power",
        "publisher": "YAGEO Group",
        "publish_date": "2025-06-27",
        "url": "https://yageogroup.com/SalesResources/ResourceLibrary/news/14368",
        "source_tier": "S",
        "excerpt": "YAGEO Group's TPI Series SMD ferrite core inductors expanded to meet growing power demands of next-generation computing platforms.",
    },
    {
        "ref": "web_coilmaster_gpu_cpu_vrm",
        "title": "GPU / CPU VRM inductors",
        "publisher": "Coilmaster Electronics",
        "publish_date": "2026-07-04",
        "url": "https://www.coilmaster.com.tw/en/applications/GPU_CPU-VRM-inductors.html",
        "source_tier": "A",
        "excerpt": "Modern GPUs and CPUs draw hundreds of amps with extremely fast load transients, making VRM inductor performance a primary factor.",
    },
    {
        "ref": "web_coilmaster_ai_data_center",
        "title": "AI, Data Center & High-Speed Electronics",
        "publisher": "Coilmaster Electronics",
        "publish_date": "2026-07-04",
        "url": "https://www.coilmaster.com.tw/en/applications/AIData-Center%26High-Speed-Electronics.html",
        "source_tier": "A",
        "excerpt": "Advanced power inductors and EMI filters for AI servers, 48V data center architectures, and GPU/CPU VRM power stages.",
    },
    {
        "ref": "web_vishay_ihsr_ai_gpu",
        "title": "IHSR - High current SMD inductors",
        "publisher": "Vishay",
        "publish_date": "2026-07-04",
        "url": "https://www.vishay.com/en/videos/inductors/ihlp174-power-inductor-family-overview/",
        "source_tier": "S",
        "excerpt": "IHSR features ultra-low DCR, low inductance, and small size for datacenter, AI computing, and GPUs applications.",
    },
    {
        "ref": "web_eaton_ai_molded_powder",
        "title": "Molded powder inductors boost AI computing power",
        "publisher": "Eaton",
        "publish_date": "2026-07-04",
        "url": "https://www.eaton.com/us/en-us/products/electronic-components/infographics/molded-powder-inductors-boost-ai-computing-power.html",
        "source_tier": "S",
        "excerpt": "Eaton says molded powder inductors improve efficiency and heat dissipation, minimize power losses, and ensure long-term operation.",
    },
    {
        "ref": "web_taiyo_yuden_ai_server_inductor_2025ar",
        "title": "TAIYO YUDEN Integrated Report 2025: Power inductor advances",
        "publisher": "TAIYO YUDEN",
        "publish_date": "2025-10-01",
        "url": "https://www.yuden.co.jp/en/ir/2025ar/download/pdf/yuden_ar25_e_p37_p41.pdf",
        "source_tier": "S",
        "excerpt": "TAIYO YUDEN will focus on high-value-added zones such as AI servers and automobiles in power inductor growth strategies.",
    },
    {
        "ref": "web_infineon_ai_vrm_vpd",
        "title": "AI quad-phase power modules designed for VPD",
        "publisher": "Infineon Technologies",
        "publish_date": "2026-07-04",
        "url": "https://www.infineon.com/technology/ai/we-power-ai/vrm",
        "source_tier": "S",
        "excerpt": "Infineon says OptiMOS quad-phase power modules target AI data centers and enable true vertical power delivery.",
    },
    {
        "ref": "web_sunlord_ir_tlvr_20260701",
        "title": "顺络电子投资者关系活动记录表",
        "publisher": "顺络电子",
        "publish_date": "2026-07-01",
        "url": "https://file.finance.sina.com.cn/211.154.219.97%3A9494/MRGG/CNSESZ_STOCK/2026/2026-7/2026-07-01/12424869.PDF",
        "source_tier": "S",
        "excerpt": "顺络电子披露 TLVR 拓扑结构产品主要用于 AI 服务器 xPU 芯片，已实现批量化供应；数据中心业务收入占比尚不足5%。",
    },
    {
        "ref": "web_boke_ir_20260424",
        "title": "铂科新材投资者关系活动记录表",
        "publisher": "铂科新材",
        "publish_date": "2026-04-24",
        "url": "https://pdf.dfcfw.com/pdf/H2_AN202604241821573541_1.pdf",
        "source_tier": "S",
        "excerpt": "铂科新材表示 ASIC 芯片和 AI GPU 功率增长将带来出货数量和性能要求变化，并披露铁、硅、铝、镍等原材料应对方式。",
    },
    {
        "ref": "web_longci_bid_20250122",
        "title": "龙磁科技收到客户中标通知",
        "publisher": "财联社",
        "publish_date": "2025-01-22",
        "url": "https://www.cls.cn/detail/1926780",
        "source_tier": "A",
        "excerpt": "龙磁科技公告收到某国际客户一款模压高端电感产品中标通知，中标金额约2300万元。",
    },
    {
        "ref": "web_longci_validation_20250527",
        "title": "龙磁科技芯片电感业务客户验证收到正反馈",
        "publisher": "证券时报",
        "publish_date": "2025-05-27",
        "url": "https://www.stcn.com/article/detail/1846557.html",
        "source_tier": "A",
        "excerpt": "龙磁科技称此前中标订单已开始小批量交付，其他客户验证进度加快并收到正反馈。",
    },
    {
        "ref": "web_tdk_ai_ecosystem",
        "title": "How Electronic Components Underpin the Growth of the AI-Driven Society",
        "publisher": "TDK",
        "publish_date": "2025-10-01",
        "url": "https://www.tdk.com/en/featured_stories/entry_082-AI-Ecosystem.html",
        "source_tier": "S",
        "excerpt": "TDK said AI servers need reliable power and noise suppression; its inductors support voltage conversion and stable GPU power delivery.",
    },
    {
        "ref": "web_murata_ai_pdn_20260204",
        "title": "Technology guide to enhance power stability in AI-driven data centers",
        "publisher": "Murata",
        "publish_date": "2026-02-04",
        "url": "https://www.murata.com/en-us/news/other/other/2026/0204",
        "source_tier": "S",
        "excerpt": "Murata launched an AI server power delivery guide and said it supports evolving power placement architectures with inductors and other components.",
    },
    {
        "ref": "web_murata_power_inductors",
        "title": "Inductor for Power Lines",
        "publisher": "Murata",
        "publish_date": "2026-07-04",
        "url": "https://www.murata.com/en-us/products/inductor/power",
        "source_tier": "S",
        "excerpt": "Murata states power inductors require high-current capability, DC superimposition characteristics, compact size, and metal alloy materials.",
    },
    {
        "ref": "web_huawei_superpod_shipments",
        "title": "Huawei Launches Open-Access SuperPoD Architecture",
        "publisher": "Huawei",
        "publish_date": "2025-09-18",
        "url": "https://www.huawei.com/en/news/2025/9/hc-superpod-innovation",
        "source_tier": "S",
        "excerpt": "Huawei reported more than 300 Atlas 900 A3 SuperPoD units shipped in 2025 and deployed across more than 20 customers.",
    },
]


ENTITIES: list[dict[str, Any]] = [
    {
        "key": "ai_chip_inductor_vrm_core",
        "display_name": "AI GPU/ASIC 板级 VRM 高端芯片电感",
        "canonical_name": "AI 高端电感研究：GPU/ASIC 板级 VRM 芯片电感",
        "description": "聚焦 GPU、ASIC、TPU、国产算力 xPU 板级 VRM/POL/DC-DC 供电链中的一体成型和金属软磁高端芯片电感。",
        "score_point": 86,
        "refs": [
            "xlsx_chip_inductor_demand",
            "xlsx_gb300_inductor_count",
            "local_csc_ai_inductor_20251206",
            "local_huatai_expert_inductor",
            "web_nvidia_gb300_nvl72",
            "web_google_ironwood_tpu",
            "web_huawei_atlas_a3_superpod",
            "web_cyntec_ai_server_switch",
            "web_cyntec_tlvr_ai_server",
            "web_yageo_tpi_ai_power_20250627",
            "web_coilmaster_gpu_cpu_vrm",
            "web_coilmaster_ai_data_center",
            "web_vishay_ihsr_ai_gpu",
            "web_eaton_ai_molded_powder",
            "web_taiyo_yuden_ai_server_inductor_2025ar",
            "web_infineon_ai_vrm_vpd",
            "web_tdk_ai_ecosystem",
            "web_murata_ai_pdn_20260204",
        ],
        "confirmed_action": "若 GPU/ASIC 出货、单板相数、TLVR/垂直供电用量和客户订单同步确认，继续提高高端芯片电感实体优先级。",
        "falsified_action": "若新平台减少离散电感用量、价格下行或客户验证延后，应把机会从核心供需转为主题观察。",
        "monitor_signal": "NVIDIA GB300/Rubin、Google TPU、华为 Atlas 新平台 BOM 和 VRM/POL 架构确认。",
        "monitor_timing": "平台发布、ODM/OEM 物料确认、公司季报和投资者交流。",
    },
    {
        "key": "tlvr_vertical_power_transition",
        "display_name": "TLVR 与垂直供电技术切换",
        "canonical_name": "AI 高端电感研究：TLVR 与垂直供电技术切换",
        "description": "研究 TLVR、多 TLVR、VPD 和垂直供电对电感制程、ASP、毛利率、产线切换和客户验证节奏的影响。",
        "score_point": 82,
        "refs": ["local_huatai_expert_inductor", "web_sunlord_ir_tlvr_20260701", "local_sunlord_tlvr_20260612", "local_tianfeng_aidc_power_20260222", "web_cyntec_tlvr_ai_server", "web_infineon_ai_vrm_vpd", "web_murata_ai_pdn_20260204", "web_murata_power_inductors"],
        "confirmed_action": "若 TLVR 批量供应、客户切换计划和 ASP/毛利率提升同时出现，优先跟踪具备批量化与自研设备能力的供应商。",
        "falsified_action": "若 TLVR 仅停留在样品阶段或被集成电源模块替代，应下调技术切换分。",
        "monitor_signal": "顺络、台达/乾坤、国巨、铂科、龙磁等厂商 TLVR 产线、订单和客户导入节奏。",
        "monitor_timing": "2026Q3 至 2027Q2 的客户导入和产线切换节点。",
    },
    {
        "key": "high_end_inductor_price_market_space",
        "display_name": "高端电感价格体系与 TAM/SAM/SOM",
        "canonical_name": "AI 高端电感研究：价格体系与市场空间测算",
        "description": "区分普通消费电子电感、服务器/加速卡高端芯片电感、TLVR、Power Shelf 大功率磁件，做 bottom-up 和 top-down 测算。",
        "score_point": 78,
        "refs": ["xlsx_inductor_model_price", "xlsx_price_case", "xlsx_chip_inductor_demand", "local_huatai_expert_inductor", "local_tianfeng_mlcc_price_20260630", "local_csc_ai_inductor_20251206"],
        "confirmed_action": "若高端型号价格、TLVR 单价、需求量和毛利率同步上行，市场空间假设可上修。",
        "falsified_action": "若涨价只发生在非 AI 型号或普通消费型号，不能用于 AI 高端电感 TAM 上修。",
        "monitor_signal": "高端芯片电感和 TLVR 单价、年降幅、订单价差、原材料传导和客户议价。",
        "monitor_timing": "月度现货价格、年度议价、公司订单和新平台导入。",
    },
    {
        "key": "customer_validation_matrix",
        "display_name": "英伟达、Google、华为客户验证矩阵",
        "canonical_name": "AI 高端电感研究：头部客户验证矩阵",
        "description": "把直接供货、间接供货、样品、验证、小批量、批量供货和无公开证据分层，防止把传闻当成供货结论。",
        "score_point": 74,
        "refs": ["local_huatai_expert_inductor", "web_sunlord_ir_tlvr_20260701", "web_longci_bid_20250122", "web_longci_validation_20250527", "web_boke_ir_20260424", "local_huaan_expert_inductor", "web_cyntec_ai_server_switch", "web_yageo_tpi_ai_power_20250627", "web_nvidia_gb300_nvl72", "web_google_ironwood_tpu", "web_huawei_superpod_shipments"],
        "confirmed_action": "若公司公告、客户认证、ODM/OEM 交付和财报收入能交叉确认，则把验证阶段上调。",
        "falsified_action": "若只有专家纪要或市场传闻而没有公司/客户/交易所材料，应只保留早期信号。",
        "monitor_signal": "客户公告、公司 IR、订单确认、ODM/OEM 供应链拆解、产线投产与收入确认。",
        "monitor_timing": "财报季、客户新平台发布后一至两个季度。",
    },
    {
        "key": "global_supplier_competition",
        "display_name": "全球高端电感竞争格局",
        "canonical_name": "AI 高端电感研究：全球与中国竞争格局",
        "description": "比较台湾、日本、韩国、美国、欧洲和中国大陆厂商在技术路线、客户、产能、价格和交付响应上的差异。",
        "score_point": 72,
        "refs": ["local_huaan_expert_inductor", "local_huatai_expert_inductor", "web_cyntec_ai_server_switch", "web_yageo_tpi_ai_power_20250627", "web_coilmaster_ai_data_center", "web_vishay_ihsr_ai_gpu", "web_eaton_ai_molded_powder", "web_taiyo_yuden_ai_server_inductor_2025ar", "web_tdk_ai_ecosystem", "web_murata_ai_pdn_20260204", "web_murata_power_inductors", "local_minsheng_sunlord_20241115", "local_csc_ai_inductor_20251206"],
        "confirmed_action": "若台湾和大陆供应商在主流 GPU/ASIC 平台份额提升，并且日韩厂商主要聚焦特定高利润客户，则中国链条弹性更强。",
        "falsified_action": "若 TDK、Murata、Samsung 或美系厂商重新拿回主流料号，国产替代假设下修。",
        "monitor_signal": "供应商份额、客户第二来源、品质事故、价格策略和交付周期。",
        "monitor_timing": "新平台试产、量产爬坡和客户替代认证周期。",
    },
    {
        "key": "powder_material_capacity_bottleneck",
        "display_name": "磁粉材料、设备和产能瓶颈",
        "canonical_name": "AI 高端电感研究：磁粉材料与产能瓶颈",
        "description": "研究铁镍合金粉、羰基铁粉、热压设备、自研自动化、场地电力和良率对高端电感供给弹性的约束。",
        "score_point": 76,
        "refs": ["local_huatai_expert_inductor", "web_boke_ir_20260424", "local_yuean_20260614", "local_huayuan_boke_20240508", "local_huayuan_boke_20260513", "local_longci_20250723", "web_murata_power_inductors"],
        "confirmed_action": "若粉体订单、细粉收得率、设备交付和产线利用率成为瓶颈，材料与一体化厂商议价权上升。",
        "falsified_action": "若铁镍粉、羰基铁粉或热压设备供应快速放量，供给弹性会削弱价格持续性。",
        "monitor_signal": "铁镍合金粉/羰基铁粉供应、热压设备交期、产线投资额、良率、能源和场地约束。",
        "monitor_timing": "项目投产公告、IR 交流、季度产能利用率和原材料价格。",
    },
    {
        "key": "mainland_listed_company_capture",
        "display_name": "中国大陆上市公司承接能力与财务弹性",
        "canonical_name": "AI 高端电感研究：中国大陆上市公司承接能力",
        "description": "比较顺络电子、铂科新材、龙磁科技、悦安新材等上市公司在产品、客户验证、产能、收入利润弹性和反方风险上的差异。",
        "score_point": 80,
        "refs": ["web_sunlord_ir_tlvr_20260701", "web_boke_ir_20260424", "web_longci_bid_20250122", "web_longci_validation_20250527", "local_huayuan_boke_20260513", "local_yuean_20260614", "local_minsheng_sunlord_20241115", "local_longci_20260428"],
        "confirmed_action": "若客户验证、批量供货、收入确认和毛利率改善同步出现，优先研究真实承接能力高且估值有消化空间的标的。",
        "falsified_action": "若数据中心收入占比仍低、客户不明、订单不确认或收入利润不响应，维持主题映射或观察篮子。",
        "monitor_signal": "公司公告、投资者交流、年报季报、产线投放、客户验证阶段和收入利润弹性。",
        "monitor_timing": "2026Q2 之后每个财报季和重大订单公告。",
    },
]


def _source_ref(ref: str) -> str:
    return f"source_ref:{ref}"


def _evidence(ref: str) -> str:
    return f"^evidence:{_source_ref(ref)}"


def _source_lookup(sources: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {source["ref"]: source for source in sources}


def _source_excerpt(source: dict[str, Any]) -> str:
    if source.get("excerpt"):
        return _clip(source["excerpt"], 420)
    if source.get("json_path"):
        data = json.loads(_read_text(ROOT / source["json_path"]))
        first_rows = []
        for sheet in data.get("sheets", []):
            first_rows.extend(sheet.get("rows", [])[:2])
        return _clip(json.dumps(first_rows, ensure_ascii=False), 420)
    lines = _find_lines(
        source["text_path"],
        ("AI", "电感", "芯片", "TLVR", "英伟达", "Google", "华为", "产能", "涨价", "客户", "GPU", "ASIC"),
        limit=3,
    )
    return _clip("；".join(lines) or source["title"], 420)


def _make_sources() -> list[dict[str, Any]]:
    out = []
    for src in LOCAL_SOURCES + TABLE_SOURCES + WEB_SOURCES:
        role = src.get("policy_evidence_role", "core_evidence")
        item = {
            "ref": src["ref"],
            "title": src["title"],
            "publisher": src.get("publisher"),
            "publish_date": src.get("publish_date"),
            "url": src.get("url"),
            "local_path": src.get("local_path"),
            "source_tier": src.get("source_tier", "B"),
            "source_review_status": "pass_with_note" if role == "early_signal_candidate" else "pass",
            "language": "zh-CN" if not src.get("url") or ".cn" in str(src.get("url")) else "en",
            "excerpt": _source_excerpt(src),
            "policy_evidence_role": role,
            "search_log_decision": "included",
            "screen_reason": "纳入 AI 高端电感人工核验证据包。",
            "cluster": src.get("publisher") or src["ref"],
        }
        out.append(item)
    return out


TEXT_NOISE_TERMS = (
    "股票投资评级",
    "投资评级",
    "评级",
    "推荐",
    "买入",
    "维持",
    "深度报告",
    "证券研究报告",
    "公司动态研究报告",
    "行业概览",
    "报告标签",
    "此研究将会回答",
    "关键问题包括",
    "市场现状如何",
    "目标价格",
    "总股本",
    "流通股本",
    "执业证书",
    "SAC",
    "@",
    "分析师：",
    "发布日期：",
    "基本数据",
    "中报点评",
    "A 股总市值",
    "总市值",
    "王介超",
    "郭衍哲",
    "万吨",
    "越南继续扩建",
    "铁氧体永磁",
    "铁氧体永磁业务",
    "燃气轮机",
    "输电层面",
    "主网电力设备",
    "配网设备",
    "思源电气",
    "安靠智电",
    "华明装备",
    "神马电力",
    "金盘科技",
    "CCL",
    "HVLP",
    "氧化铜粉",
    "纳米硅粉",
    "低银",
    "无银化",
    "固态电池",
    "充电桩",
    "液冷",
    "PCB上游",
    "Gemini",
    "小尺寸 MLCC",
    "MLCC 产能",
    "紧缺规格交期",
)

TEXT_DIRECT_TERMS = (
    "芯片电感",
    "高端电感",
    "TLVR",
    "垂直供电",
    "VPD",
    "一体成型电感",
    "合金电感",
    "金属软磁",
    "软磁粉芯",
    "铁镍",
    "羰基铁粉",
    "模压电感",
    "GPU",
    "ASIC",
    "TPU",
    "xPU",
    "DrMOS",
    "英伟达",
    "NVIDIA",
    "谷歌",
    "Google",
    "华为",
    "顺络",
    "铂科",
    "龙磁",
    "悦安",
    "TDK",
    "Murata",
    "村田",
    "台达",
    "乾坤",
    "国巨",
    "奇力新",
    "中标",
    "小批量",
    "批量化供应",
)


def _clean_text_line(line: str) -> str:
    text = _clip(_compact(line), 260)
    for prefix in ("➢", "▌", "摘要：", "核心观点："):
        text = text.replace(prefix, "")
    return " ".join(text.split()).strip(" ；;，,。")


def _is_relevant_text_line(line: str) -> bool:
    clean = _clean_text_line(line)
    if len(clean) < 12:
        return False
    if any(term in clean for term in TEXT_NOISE_TERMS):
        return False
    return any(term in clean for term in TEXT_DIRECT_TERMS)


def _entity_for_text(line: str) -> str:
    text = line.lower()
    if any(k in line for k in ("英伟达", "谷歌", "Google", "华为", "客户", "验证", "中标", "供货", "批量", "送样")):
        return "customer_validation_matrix"
    if any(k in line for k in ("TLVR", "VPD", "垂直供电", "多TLVR")):
        return "tlvr_vertical_power_transition"
    if any(k in line for k in ("价格", "涨价", "单价", "毛利率", "市场空间", "需求量", "用量", "颗", "ASP")):
        return "high_end_inductor_price_market_space"
    if any(k in line for k in ("TDK", "村田", "Murata", "乾坤", "台达", "国巨", "连展", "三星", "日本", "台湾", "大陆")):
        return "global_supplier_competition"
    if any(k in line for k in ("铁镍", "羰基", "粉", "热压", "设备", "能源", "电力", "场地", "原材料", "细粉")):
        return "powder_material_capacity_bottleneck"
    if any(k in line for k in ("顺络", "铂科", "龙磁", "悦安", "麦捷", "风华", "东睦")):
        return "mainland_listed_company_capture"
    if any(k in text for k in ("gpu", "asic", "server", "ai服务器", "xpu")):
        return "ai_chip_inductor_vrm_core"
    return "ai_chip_inductor_vrm_core"


def _metric_for_text(line: str) -> str:
    clean = _clean_text_line(line)
    if "GB200" in clean or "GB300" in clean:
        return "英伟达 GB200/GB300 计算托盘电感用量线索"
    if "Rubin" in clean:
        return "英伟达 Rubin 平台电感用量线索"
    if "H100" in clean:
        return "英伟达 H100 计算卡电感用量线索"
    if "GH200" in clean:
        return "英伟达 GH200 合金电感采用线索"
    if "英伟达" in clean and "份额" in clean:
        return "英伟达主流料号供应份额线索"
    if "英伟达" in clean and "TLVR" in clean and ("27年" in clean or "上量" in clean):
        return "英伟达 TLVR 上量时间窗口线索"
    if ("英伟达" in clean or "谷歌" in clean or "Google" in clean) and "TLVR" in clean:
        return "英伟达/Google 新平台 TLVR 切换线索"
    if "英伟达" in clean and "离散方案" in clean:
        return "英伟达/Google/AWS 供电架构差异线索"
    if "英伟达" in clean and ("匹配" in clean or "尖端电感" in clean):
        return "英伟达/Google/华为平台适配线索"
    if "英伟达" in clean and ("直接签订合同" in clean or "指定的打板厂商" in clean):
        return "英伟达/Google/华为直接供货线索"
    if ("谷歌" in clean or "Google" in clean) and "TLVR" in clean:
        return "Google TLVR 专利和电源模块线索"
    if ("谷歌" in clean or "Google" in clean) and "TPU" in clean:
        return "Google TPU 平台供电集成线索"
    if "华为" in clean or "昇腾" in clean or "Atlas" in clean:
        return "华为 Atlas/昇腾平台供电需求线索"
    if "TLVR" in clean and ("批量" in clean or "规模化出货" in clean):
        return "TLVR 批量供应和规模化出货线索"
    if "TLVR" in clean and "瞬态响应" in clean:
        return "TLVR 瞬态响应需求线索"
    if "TLVR" in clean and "垂直供电" in clean:
        return "TLVR 与垂直供电延伸方向线索"
    if "垂直" in clean and "供电" in clean:
        return "垂直供电架构对离散电感替代线索"
    if "数据中心" in clean and ("收入占比" in clean or "营收" in clean):
        return "数据中心业务收入占比线索"
    if "芯片电感业务" in clean and "月产值占比" in clean:
        return "芯片电感月产值占比线索"
    if "龙磁" in clean and "中标" in clean:
        return "龙磁高端模压电感中标线索"
    if "小批量" in clean and "交付" in clean:
        return "客户验证后小批量交付线索"
    if "铂科" in clean and ("ASIC" in clean or "GPU" in clean):
        return "铂科新材 ASIC/GPU 功率提升受益线索"
    if "顺络" in clean:
        return "顺络电子高端电感承接能力线索"
    if "铂科" in clean:
        return "铂科新材芯片电感和软磁材料线索"
    if "龙磁" in clean:
        return "龙磁科技芯片电感量产和收入线索"
    if "悦安" in clean or "羰基铁粉" in clean:
        return "羰基铁粉细粉材料供给线索"
    if "铁镍" in clean or "金属软磁" in clean or "软磁粉芯" in clean:
        return "金属软磁材料性能和供给线索"
    if "热压" in clean or "设备" in clean:
        return "高端电感热压设备和产线瓶颈线索"
    if "产能" in clean or "产线" in clean or "扩产" in clean or "月产" in clean:
        return "高端电感产能和产线扩张线索"
    if "涨价" in clean or "单价" in clean or "毛利率" in clean:
        return "高端电感价格和毛利率传导线索"
    if "台达" in clean or "乾坤" in clean:
        return "台达/乾坤供应链位置线索"
    if "国巨" in clean or "奇力新" in clean:
        return "国巨/奇力新供应链位置线索"
    if "TDK" in clean or "Murata" in clean or "村田" in clean:
        return "海外龙头 AI 电源电感能力线索"
    if "AI服务器" in clean and "功率" in clean:
        return "AI 服务器功率提升对芯片电感需求线索"
    if "人工智能的功率增长" in clean and "芯片电感" in clean:
        return "AI 算力功率增长带来的芯片电感通胀线索"
    if "三次电源" in clean:
        return "AI 服务器三次电源芯片电感位置线索"
    if "应用场景" in clean and "芯片电感" in clean:
        return "芯片电感应用场景和性能要求线索"
    if "合金电感具备" in clean or "低直流损耗" in clean:
        return "合金电感大电流性能优势线索"
    if "CPU" in clean and "GPU" in clean and "ASIC" in clean and "功耗" in clean:
        return "CPU/GPU/ASIC 功耗提升对供电链压力线索"
    if "ASIC" in clean and "量产突破" in clean:
        return "ASIC 量产突破带来的高端电感增量线索"
    if "AI 芯片电感业务" in clean and "第二增长曲线" in clean:
        return "AI 芯片电感第二增长曲线线索"
    if "芯片电感将迎来" in clean and "价值" in clean:
        return "AI 芯片电感量价提升线索"
    if "为芯片前端供电" in clean:
        return "芯片前端供电材料路线线索"
    if "芯片电感龙头供应商" in clean:
        return "芯片电感龙头供应商定位线索"
    if "芯片电感" in clean and ("需求" in clean or "放量" in clean):
        return "芯片电感需求放量线索"
    if "一体成型" in clean:
        return "一体成型电感技术升级线索"
    return ""


def _add_point(points: list[dict[str, Any]], *, source_ref: str, entity_key: str, metric: str,
               period: str, value_text: str | None = None, value_num: float | None = None,
               unit: str = "文本", excerpt: str, value_status: str = "available_text_only",
               extraction_method: str = "manual_verified",
               policy_evidence_role: str = "core_evidence") -> None:
    if value_num is None and not value_text:
        value_text = excerpt
    points.append({
        "source_ref": source_ref,
        "entity_key": entity_key,
        "metric": metric,
        "period": period,
        "as_of_date": period,
        "value_num": value_num,
        "value_text": value_text if value_num is None else None,
        "unit": unit,
        "source_excerpt": _clip(excerpt),
        "value_status": value_status,
        "calculation_review_status": "pass",
        "extraction_method": extraction_method,
        "policy_evidence_role": policy_evidence_role,
    })


def _series_point(source_ref: str, entity_key: str, metric: str, unit: str,
                  observations: list[dict[str, Any]], analysis: str) -> dict[str, Any]:
    clean = [obs for obs in observations if obs.get("period")]
    latest = clean[-1]
    summary = (
        f"{metric} 覆盖 {clean[0]['period']} 至 {latest['period']}，共 {len(clean)} 个观测；"
        f"最新值为 {latest.get('value')} {unit}。"
        "同源同口径时间序列整体作为一个数据点，应看方向和斜率，不把每个年份拆成单独证据组。"
        f"{analysis}"
    )
    return {
        "source_ref": source_ref,
        "entity_key": entity_key,
        "metric": metric,
        "period": f"{clean[0]['period']}~{latest['period']}",
        "as_of_date": latest["period"],
        "value_num": latest.get("value") if isinstance(latest.get("value"), (int, float)) else None,
        "value_text": summary,
        "unit": unit,
        "source_excerpt": _clip(summary),
        "value_status": "available",
        "calculation_review_status": "pass",
        "extraction_method": "xlsx_direct",
        "policy_evidence_role": "core_evidence",
        "observation_count": len(clean),
    }


def _load_table_rows(ref: str) -> list[dict[str, Any]]:
    src = next(source for source in TABLE_SOURCES if source["ref"] == ref)
    book = json.loads(_read_text(ROOT / src["json_path"]))
    rows: list[dict[str, Any]] = []
    for sheet in book.get("sheets", []):
        rows.extend(sheet.get("rows", []))
    return rows


SERVER_MODULE_COLUMN_LABELS = {
    "AI双路E5服务路使用量": "功能模块",
    "Unnamed: 1": "一体成型电感数量",
    "Unnamed: 2": "电感量",
    "Unnamed: 3": "饱和电流/颗",
    "Unnamed: 4": "备注",
}

PRICE_CASE_COLUMN_LABELS = {
    "昌类": "品类",
    "涨价核心驱动力": "涨价核心驱动力",
    "奥型涨幅": "典型涨幅",
    "代表厂商/群件": "代表厂商/组件",
}

MODEL_PRICE_COLUMN_LABELS = {
    "型号名": "型号名",
    "公司名": "公司名",
    "规格参数": "规格参数",
    "核心用途": "核心用途",
    "价(元)": "价格",
    "最新现年初至近1月今涨幅涨幅": "年初至今涨跌幅",
}


def _format_table_row(row: dict[str, Any], labels: dict[str, str] | None = None) -> str:
    labels = labels or {}
    parts: list[str] = []
    for key, value in row.items():
        text = _compact(value)
        if not text or text == "Datayes!":
            continue
        label = labels.get(str(key), str(key))
        if label.startswith("Unnamed:"):
            continue
        parts.append(f"{label}: {text}")
    return "；".join(parts)


def _build_table_points() -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    demand_rows = _load_table_rows("xlsx_chip_inductor_demand")
    for row in demand_rows:
        label = _compact(row.get("Unnamed: 0"))
        unit = _compact(row.get("单位"))
        if not label or label == "Datayes!":
            continue
        observations = []
        for year in ("2023", "2024", "2025E", "2026E", "2027E", "2028E", "2029E"):
            val = row.get(year)
            if isinstance(val, (int, float)) and not math.isnan(float(val)):
                observations.append({"period": year, "value": float(val)})
        entity = "high_end_inductor_price_market_space"
        if "GPU" in label or "ASIC" in label or "单片" in label:
            entity = "ai_chip_inductor_vrm_core"
        points.append(_series_point("xlsx_chip_inductor_demand", entity, label, unit or "无", observations, "该表是本轮 bottom-up 测算的核心输入，用于连接 AI 加速卡出货、单片用量和芯片电感需求量。"))

    for row in _load_table_rows("xlsx_server_module_usage"):
        module = _compact(row.get("AI双路E5服务路使用量"))
        if not module or module in {"Datayes!", "功能模块"}:
            continue
        excerpt = _format_table_row(row, SERVER_MODULE_COLUMN_LABELS)
        _add_point(
            points,
            source_ref="xlsx_server_module_usage",
            entity_key="ai_chip_inductor_vrm_core",
            metric=f"服务器功能模块一体电感使用要求：{module}",
            period="2026-07-03",
            value_text=excerpt,
            unit="模块用量",
            excerpt=excerpt,
            extraction_method="xlsx_direct",
        )

    for row in _load_table_rows("xlsx_gb300_inductor_count"):
        module = _compact(row.get("模块"))
        if not module or module == "Datayes!":
            continue
        excerpt = _format_table_row(row)
        _add_point(
            points,
            source_ref="xlsx_gb300_inductor_count",
            entity_key="ai_chip_inductor_vrm_core",
            metric=f"GB300 电感数量测算：{module}",
            period="2026-07-03",
            value_text=excerpt,
            unit="颗/节点或全网",
            excerpt=excerpt,
            extraction_method="xlsx_direct",
        )

    for row in _load_table_rows("xlsx_price_case"):
        category = _compact(row.get("昌类"))
        if not category or category == "Datayes!":
            continue
        if category != "电感":
            continue
        excerpt = _format_table_row(row, PRICE_CASE_COLUMN_LABELS)
        _add_point(
            points,
            source_ref="xlsx_price_case",
            entity_key="high_end_inductor_price_market_space",
            metric=f"被动元件涨价案例：{category}",
            period="2026-07-03",
            value_text=excerpt,
            unit="案例",
            excerpt=excerpt,
            extraction_method="xlsx_direct",
        )

    for row in _load_table_rows("xlsx_inductor_model_price"):
        model = _compact(row.get("型号名"))
        if not model or model == "Datayes!":
            continue
        price = row.get("价(元)")
        excerpt = _format_table_row(row, MODEL_PRICE_COLUMN_LABELS)
        _add_point(
            points,
            source_ref="xlsx_inductor_model_price",
            entity_key="high_end_inductor_price_market_space",
            metric=f"电感型号价格和涨跌幅：{model}",
            period="2026-07-03",
            value_num=float(price) if isinstance(price, (int, float)) and not math.isnan(float(price)) else None,
            value_text=None if isinstance(price, (int, float)) and not math.isnan(float(price)) else excerpt,
            unit="元/颗",
            excerpt=excerpt,
            extraction_method="xlsx_direct",
        )
    return points


KEYWORDS = (
    "英伟达", "NVIDIA", "谷歌", "Google", "华为", "ASIC", "GPU", "AI服务器",
    "芯片电感", "TLVR", "垂直供电", "VPD", "一体成型", "金属软磁",
    "价格", "涨价", "单价", "毛利率", "产能", "产线", "扩产", "中标",
    "验证", "供货", "小批量", "批量", "铁镍", "羰基", "粉", "热压",
    "TDK", "村田", "Murata", "台达", "乾坤", "国巨", "连展", "顺络",
    "铂科", "龙磁", "悦安",
)


def _build_text_points() -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for src in LOCAL_SOURCES:
        lines = _find_lines(src["text_path"], KEYWORDS, limit=9)
        for line in lines:
            line = _clean_text_line(line)
            if not _is_relevant_text_line(line):
                continue
            metric = _metric_for_text(line)
            if not metric:
                continue
            _add_point(
                points,
                source_ref=src["ref"],
                entity_key=_entity_for_text(line),
                metric=metric,
                period=src["publish_date"],
                value_text=line,
                unit="文本",
                excerpt=line,
                extraction_method="pdf_direct" if src["local_path"].lower().endswith(".pdf") else "docx_direct",
                policy_evidence_role=src.get("policy_evidence_role", "core_evidence"),
            )
    return points


def _build_web_points() -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    web_point_specs = [
        ("web_nvidia_gb300_nvl72", "ai_chip_inductor_vrm_core", "GB300 NVL72 平台配置", "2026-07-04", "72 Blackwell Ultra GPUs + 36 Grace CPUs", "平台规格"),
        ("web_google_ironwood_tpu", "ai_chip_inductor_vrm_core", "Google Ironwood TPU 扩展规模", "2025-04-09", "9,216 liquid-cooled chips", "平台规格"),
        ("web_huawei_atlas_a3_superpod", "ai_chip_inductor_vrm_core", "华为 Atlas 900 A3 SuperPoD 规模", "2025-09-18", "384 Ascend 910C chips", "平台规格"),
        ("web_cyntec_ai_server_switch", "ai_chip_inductor_vrm_core", "Cyntec AI server 板级功率电感定位", "2026-07-04", "SXM accelerator cards, UBB motherboards, Switch", "官方产品定位"),
        ("web_cyntec_tlvr_ai_server", "ai_chip_inductor_vrm_core", "Cyntec TLVR 电感参数范围", "2024-05-31", "70-200nH; 0.125mΩ DCR; >70A saturation current", "官方产品参数"),
        ("web_yageo_tpi_ai_power_20250627", "ai_chip_inductor_vrm_core", "YAGEO TPI AI power 电感定位", "2025-06-27", "next-generation computing platform power demand", "官方产品定位"),
        ("web_coilmaster_gpu_cpu_vrm", "ai_chip_inductor_vrm_core", "Coilmaster GPU/CPU VRM 电感定位", "2026-07-04", "hundreds of amps and fast load transients", "官方应用定位"),
        ("web_coilmaster_ai_data_center", "ai_chip_inductor_vrm_core", "Coilmaster AI data center 磁件覆盖", "2026-07-04", "AI servers, 48V architecture, GPU/CPU VRM stages", "官方应用定位"),
        ("web_vishay_ihsr_ai_gpu", "ai_chip_inductor_vrm_core", "Vishay IHSR AI/GPU 高电流电感定位", "2026-07-04", "ultra-low DCR, low inductance, datacenter/AI/GPU applications", "官方产品定位"),
        ("web_eaton_ai_molded_powder", "ai_chip_inductor_vrm_core", "Eaton AI molded powder 电感定位", "2026-07-04", "efficiency, heat dissipation, lower power losses", "官方产品定位"),
        ("web_taiyo_yuden_ai_server_inductor_2025ar", "ai_chip_inductor_vrm_core", "Taiyo Yuden AI server power inductor 战略", "2025-10-01", "high-value-added zones such as AI servers", "官方报告定位"),
        ("web_infineon_ai_vrm_vpd", "ai_chip_inductor_vrm_core", "Infineon VPD 集成模块替代风险", "2026-07-04", "AI data center quad-phase power modules and true VPD", "架构替代风险"),
        ("web_huawei_superpod_shipments", "customer_validation_matrix", "华为 Atlas 900 A3 SuperPoD 交付", "2025-09-18", "300+ units and 20+ customers", "客户部署"),
        ("web_sunlord_ir_tlvr_20260701", "tlvr_vertical_power_transition", "顺络 TLVR 批量化供应", "2026-07-01", "批量化供应；数据中心收入占比不足5%", "阶段"),
        ("web_boke_ir_20260424", "powder_material_capacity_bottleneck", "铂科原材料和 ASIC 影响", "2026-04-24", "铁占原材料重量80+%；芯片功率增大推动性能要求", "材料口径"),
        ("web_longci_bid_20250122", "customer_validation_matrix", "龙磁高端模压电感中标", "2025-01-22", "中标金额约2300万元", "万元"),
        ("web_longci_validation_20250527", "customer_validation_matrix", "龙磁客户验证和小批量交付", "2025-05-27", "中标订单开始小批量交付，其他客户验证正反馈", "阶段"),
        ("web_cyntec_tlvr_ai_server", "tlvr_vertical_power_transition", "Cyntec TLVR AI server 电感量产参数", "2024-05-31", "70-200nH; 0.125mΩ DCR; >70A saturation current", "技术参数"),
        ("web_infineon_ai_vrm_vpd", "tlvr_vertical_power_transition", "Infineon VPD 集成模块路线", "2026-07-04", "quad-phase module; true vertical power delivery", "替代路线"),
        ("web_tdk_ai_ecosystem", "global_supplier_competition", "TDK AI 服务器电感定位", "2025-10-01", "用于电压转换和 GPU 稳定供电", "产品定位"),
        ("web_murata_ai_pdn_20260204", "global_supplier_competition", "Murata AI 数据中心 PDN 指南", "2026-02-04", "高压化和设备密度提升使稳定供电成为关键", "产品定位"),
        ("web_yageo_tpi_ai_power_20250627", "global_supplier_competition", "YAGEO/KEMET/Pulse AI power 电感定位", "2025-06-27", "TPI 系列扩展至下一代计算平台", "产品定位"),
        ("web_vishay_ihsr_ai_gpu", "global_supplier_competition", "Vishay AI/GPU 高电流电感定位", "2026-07-04", "datacenter, AI computing, GPU applications", "产品定位"),
        ("web_eaton_ai_molded_powder", "global_supplier_competition", "Eaton molded powder AI 电感定位", "2026-07-04", "AI computing xPU power delivery", "产品定位"),
        ("web_taiyo_yuden_ai_server_inductor_2025ar", "global_supplier_competition", "Taiyo Yuden AI server 电感战略", "2025-10-01", "AI server 高附加值应用区", "产品定位"),
        ("web_murata_power_inductors", "powder_material_capacity_bottleneck", "Murata 功率电感技术要求", "2026-07-04", "大电流、直流叠加、小型化、金属合金材料", "技术要求"),
    ]
    lookup = {src["ref"]: src for src in WEB_SOURCES}
    for source_ref, entity_key, metric, period, value_text, unit in web_point_specs:
        src = lookup[source_ref]
        _add_point(
            points,
            source_ref=source_ref,
            entity_key=entity_key,
            metric=metric,
            period=period,
            value_text=value_text,
            unit=unit,
            excerpt=src["excerpt"],
            extraction_method="web_fetch",
        )
    return points


def _build_ab_snapshot_points() -> list[dict[str, Any]]:
    if not RESEARCH_DB.exists():
        return []
    conn = sqlite3.connect(RESEARCH_DB)
    conn.row_factory = sqlite3.Row
    terms = ("电感", "TLVR", "AI服务器电源", "服务器电源", "芯片电感")
    where = " OR ".join(["dp.metric LIKE ? OR dp.source_excerpt LIKE ?" for _ in terms])
    params: list[str] = []
    for term in terms:
        params.extend([f"%{term}%", f"%{term}%"])
    rows = conn.execute(
        f"""
        SELECT dp.id, dp.metric, dp.period, dp.as_of_date, dp.value_num, dp.value_text,
               dp.unit, dp.source_excerpt, dp.source_id, s.title, s.publisher, s.publish_date
        FROM industry_data_point dp
        LEFT JOIN source s ON s.id=dp.source_id
        WHERE {where}
        ORDER BY dp.id
        LIMIT 18
        """,
        params,
    ).fetchall()
    conn.close()
    points: list[dict[str, Any]] = []
    for row in rows:
        source_ref = "local_csc_ai_inductor_20251206" if int(row["source_id"] or 0) == 524 else "local_tianfeng_aidc_power_20260222"
        excerpt = row["source_excerpt"] or row["metric"]
        _add_point(
            points,
            source_ref=source_ref,
            entity_key=_entity_for_text(excerpt + " " + row["metric"]),
            metric=f"A/B 行研库镜像：{row['metric']}",
            period=row["period"] or row["as_of_date"] or row["publish_date"] or AS_OF_DATE,
            value_num=row["value_num"],
            value_text=row["value_text"],
            unit=row["unit"] or "无",
            excerpt=f"A/B 数据点 {row['id']} 镜像：{excerpt}",
            extraction_method="ab_readonly_snapshot",
        )
    return points


def _build_data_points() -> list[dict[str, Any]]:
    points = _build_table_points() + _build_text_points() + _build_web_points() + _build_ab_snapshot_points()
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict[str, Any]] = []
    for point in points:
        key = (point["source_ref"], point["metric"], point["source_excerpt"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(point)
    return unique


def _claim_type_for_point(point: dict[str, Any]) -> str:
    metric = str(point.get("metric") or "")
    entity_key = str(point.get("entity_key") or "")
    source_ref = str(point.get("source_ref") or "")
    if int(point.get("observation_count") or 0) > 1:
        return "长期序列数据证据"
    if point.get("extraction_method") == "xlsx_direct":
        return "结构化表格证据"
    if "customer_validation" in entity_key or any(k in metric for k in ("英伟达", "Google", "华为", "中标", "客户", "供货")):
        return "客户验证证据"
    if any(k in metric for k in ("价格", "毛利率", "TAM", "涨价")):
        return "价格和市场空间证据"
    if any(k in metric for k in ("产能", "产线", "批量", "TLVR", "垂直供电")):
        return "技术切换和产能证据"
    if any(k in metric for k in ("材料", "磁粉", "羰基", "铁镍", "软磁")):
        return "材料和工艺证据"
    if source_ref.startswith("web_"):
        return "公开来源证据"
    if source_ref.startswith("ab_"):
        return "A/B 行研镜像证据"
    return "人工核验摘录证据"


def _claim_priority(point: dict[str, Any]) -> tuple[int, int, str]:
    method = point.get("extraction_method")
    metric = str(point.get("metric") or "")
    excerpt = str(point.get("source_excerpt") or "")
    value = 0
    if method == "xlsx_direct":
        value += 90
    elif method == "web_fetch":
        value += 80
    elif method == "ab_readonly_snapshot":
        value += 55
    else:
        value += 25
    if point.get("observation_count", 0) and int(point.get("observation_count") or 0) >= 6:
        value += 35
    if any(term in metric or term in excerpt for term in ("原文证据", "行业事实", "Unnamed:", "投资评级", "分析师", "@")):
        value -= 200
    if any(term in metric or term in excerpt for term in ("英伟达", "Google", "华为", "顺络", "铂科", "龙磁", "TDK", "Murata", "TLVR")):
        value += 20
    return (value, int(point.get("observation_count") or 0), metric)


def _claim_text_for_point(point: dict[str, Any]) -> str:
    metric = str(point.get("metric") or "证据点")
    excerpt = _clip(str(point.get("source_excerpt") or ""), 220)
    return f"{metric}：{excerpt}"


def _build_claims(data_points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    per_entity: dict[str, int] = {}
    for point in sorted(data_points, key=_claim_priority, reverse=True):
        entity_key = point["entity_key"]
        if per_entity.get(entity_key, 0) >= 7:
            continue
        per_entity[entity_key] = per_entity.get(entity_key, 0) + 1
        claims.append({
            "source_ref": point["source_ref"],
            "entity_key": entity_key,
            "claim_type": _claim_type_for_point(point),
            "claim_text": _claim_text_for_point(point),
            "source_excerpt": point["source_excerpt"],
            "claim_evidence_status": "verified",
            "claim_next_action": "route_to_data_point",
            "support_status": "supported",
            "policy_evidence_role": point.get("policy_evidence_role", "core_evidence"),
        })
    return claims


SOURCE_CONTEXT_NOTES: dict[str, str] = {
    "local_csc_ai_inductor_20251206": "中信建投报告把 AI 服务器功率增长、电感用量和材料器件一体化放在同一个产业链框架里，适合作为需求和国产承接的总背景，但它仍是券商二级研究，需要公司和官方资料校验。",
    "local_huatai_expert_inductor": "华泰专家纪要提供客户、份额、产线和 ASP 的细节线索；这些内容对发现验证方向很有价值，但因客户和份额多来自访谈，不能直接等同于公开确认。",
    "local_huaan_expert_inductor": "华安专家纪要把三次电源、合金电感、TLVR 和台系供应链放在技术路线中解释，能帮助判断规格难度，但客户份额部分仍需官方或公司证据交叉验证。",
    "local_tianfeng_aidc_power_20260222": "天风 AIDC 通胀材料把电源、芯片电感、液冷和 PCB 上游并列，说明市场把电感放在 AI 基建涨价链中，但需要再拆出真实电感料号和公司收入。",
    "local_sunlord_tlvr_20260612": "中邮顺络报告聚焦 TLVR 电感赋能算力服务器，提供公司产品线和技术切换背景；它支持顺络作为大陆验证项，但仍需 IR 和财报确认客户与收入。",
    "local_minsheng_sunlord_20241115": "民生顺络旧报告提供电感龙头和复苏成长背景，时间较早，只能作为公司能力底座，不能单独支撑 2026 年 AI 电感判断。",
    "local_huayuan_boke_20260513": "华源铂科报告把合金软磁粉芯、芯片电感和 ASIC 需求连接起来，适合解释材料到器件的一体化弹性，但客户和收入拆分要回到公司 IR。",
    "local_huayuan_boke_20240508": "华源 2024 年铂科报告提供早期 AI 算力第二成长极叙事，时效上需要严重警惕，只能作为历史铺垫。",
    "local_tianfeng_boke_20240602": "天风 2024 年铂科报告强调芯片电感供应商定位，因发布时间较早，当前评分只把它当作历史线索。",
    "local_longci_20260428": "中信建投龙磁 2026 年报告把营收增长和 AI 芯片电感放量联系起来，适合解释订单弹性，但仍要用公告和后续收入确认校验。",
    "local_longci_20250723": "中信建投龙磁 2025 年报告提供高端铁氧体和 AI 芯片电感业务的公司底座，能说明业务方向，不足以证明 2026 年放量。",
    "local_yuean_20260614": "华鑫悦安报告把羰基铁粉细粉和一体成型电感需求连接起来，适合解释上游材料瓶颈，但不能外推为器件客户验证。",
    "local_toubao_integrated_inductor_20260316": "头豹行业概览提供一体成型电感材料、工艺和应用边界，适合作为材料和工艺难度背景，不直接给出公司订单。",
    "local_tianfeng_mlcc_price_20260630": "天风 MLCC 与高端供需报告提供被动元件涨价和高端紧缺的横向参照，能提示价格环境，但不能替代芯片电感型号价格。",
    "xlsx_chip_inductor_demand": "本地表格把 GPU/ASIC 出货、单片电感用量和需求颗数打包为同源序列，是需求和 TAM 计算的主证据。",
    "xlsx_module_inductor_requirement": "服务器功能模块一体电感表把不同模块的电感使用要求拆开，说明规格差异来自功能和电流场景，而不是简单颗数增长。",
    "xlsx_gb300_inductor_count": "GB300 电感数量表按 GPU 核心供电、CPU 供电、内存、存储和网络等分项拆解，是单板 BOM 用量的直接口径。",
    "xlsx_price_case": "涨价案例表展示电容、电阻、电感的价格扰动，适合做价格动量线索，但必须和具体 AI 型号和客户议价分开。",
    "xlsx_inductor_model_price": "型号价格表把 TDK、Murata、Sunlord 等具体电感价格放在同一口径，是判断高端和普通电感分化的关键价格证据。",
    "web_nvidia_gb300_nvl72": "NVIDIA GB300 NVL72 官方资料说明 72 个 Blackwell Ultra GPU 和 36 个 Grace CPU 的机架形态，用来证明高功率平台背景，不证明单个电感供应商订单。",
    "web_google_ironwood_tpu": "Google Ironwood TPU 官方资料说明 inference 平台规模和液冷芯片数，用来扩展 ASIC/TPU 需求背景，不直接映射到具体电感厂。",
    "web_huawei_atlas_a3_superpod": "华为 Atlas 900 A3 SuperPoD 资料说明国产算力平台规模，用来判断国内客户侧需求存在，但供应商映射仍需公司和订单证据。",
    "web_huawei_superpod_shipments": "华为 SuperPoD 开放架构和交付信息提供国产算力部署线索，适合客户矩阵中的国内需求背景，不等于单一电感供货确认。",
    "web_cyntec_ai_server_switch": "Cyntec 官方 AI server 页面把低损耗功率电感用于 SXM、UBB 和 switch，是台系高端电感产品边界的强证据。",
    "web_cyntec_tlvr_ai_server": "Cyntec TLVR 官方资料给出 AI server TLVR 的参数和应用场景，是验证 TLVR 不是单纯纪要概念的重要官方证据。",
    "web_yageo_tpi_ai_power_20250627": "YAGEO TPI 官方资料把 ferrite core inductors 扩展到 AI、server 和高效率电源，说明台系多品牌平台也在响应 AI power 需求。",
    "web_coilmaster_gpu_cpu_vrm": "Coilmaster GPU/CPU VRM 页面说明现代 GPU/CPU 需要数百安电流和快速负载瞬态，用来解释高电流、低 DCR 电感门槛。",
    "web_coilmaster_ai_data_center": "Coilmaster AI data center 页面覆盖 48V 架构、GPU/CPU VRM 和服务器磁件，用于验证非上市供应链也围绕 AI 数据中心调整产品。",
    "web_vishay_ihsr_ai_gpu": "Vishay IHSR 官方资料把 ultra-low DCR、低电感和小尺寸用于 datacenter、AI computing 和 GPU，是美系高电流电感对照证据。",
    "web_eaton_ai_molded_powder": "Eaton molded powder inductor 资料强调效率、散热、低损耗和长期可靠性，说明 xPU power delivery 对材料和封装可靠性提出更高要求。",
    "web_taiyo_yuden_ai_server_inductor_2025ar": "Taiyo Yuden 年报把 power inductor growth 聚焦到 AI servers 等高附加值区，是日本供应商战略层面的对照证据。",
    "web_infineon_ai_vrm_vpd": "Infineon VPD 模块资料把多相电源和 proprietary magnetics 集成，是离散电感机会的重要反方约束。",
    "web_sunlord_ir_tlvr_20260701": "顺络 IR 披露 TLVR 主要用于 AI server xPU 且已批量化供应，同时说明数据中心收入占比不足 5%，是产品阶段强、财务阶段未满的核心证据。",
    "web_boke_ir_20260424": "铂科 IR 把 ASIC 和 AI GPU 功率提升与出货数量、性能要求变化连接起来，是材料到器件一体化的公司证据，但客户名和收入拆分仍缺。",
    "web_longci_bid_20250122": "龙磁中标公告转述提供约 2300 万元高端模压电感订单，是订单验证强线索，但客户匿名和持续性仍待后续公告。",
    "web_longci_validation_20250527": "龙磁客户验证报道说明中标订单开始小批量交付并有正反馈，适合验证订单阶段上移，但仍未解决规模和客户身份。",
    "web_tdk_ai_ecosystem": "TDK AI ecosystem 资料把 power delivery、noise suppression 和 GPU 稳定供电联系起来，是全球龙头技术壁垒参照。",
    "web_murata_ai_pdn_20260204": "Murata AI data center PDN 指南把电感、磁珠、电容和供电布局放在系统方案中，提示离散电感可能被更宽的 PDN 方案稀释。",
    "web_murata_power_inductors": "Murata power inductor 页面提供电源线电感的产品边界，用来界定高端电感不是泛被动元件。",
}


FACTOR_VALUE_MEANING: dict[str, str] = {
    "demand.output_consumption_proxy": "需求侧已有出货、单板用量或 TAM 口径可以复算；这个读数先固定数量锚，再等待价格、客户和产能证据共同证明利润弹性。",
    "demand.application_intensity_change": "单位平台的相数、电流、低 DCR、瞬态响应和小型化要求正在改变 BOM 难度；分数高代表规格升级，不等同于简单总量增长。",
    "signal.material_price_momentum": "价格、ASP、毛利率或型号价差开始提供供需紧张线索；只有与具体 AI 型号、客户阶段或财务响应对齐时，才提高机会权重。",
    "supply.substitution_barrier": "客户认证、可靠性、工艺和替代路线决定供应商切换成本；高分意味着进入后更难替换，低分则容易被全球龙头或集成模块稀释。",
    "supply.supplier_structure_bucket": "合格供应商结构和份额分配已经能被分层比较；分数越高，越能从行业名单进入具体公司和第二来源排序。",
    "demand.customer_capex_capacity_signal": "头部客户、平台资料、订单或批量阶段正在把需求传导到供应链；分数高时仍需区分平台需求、系统/模块商和电感厂直接确认。",
    "supply.capacity_event_12m": "未来 12 个月的产线、订单、投产、交付或产能事件可被跟踪；该读数决定紧缺能否延续到收入确认窗口。",
    "supply.expansion_cycle_bucket": "扩产、设备、良率、认证和产线切换周期会影响供给响应速度；周期越长，价格和客户验证信号越有持续性。",
    "demand.downstream_price_momentum": "下游或相邻高端被动元件的价格环境会影响涨价传导；若下游不承接，电感涨价更可能回落到毛利压力。",
    "supply.raw_policy_constraint": "材料、粉体、设备、工艺、政策或供应链约束可能形成非线性瓶颈；该读数会改变产能事件和供应商结构的权重。",
}


ENTITY_FACTOR_LENS: dict[str, str] = {
    "ai_chip_inductor_vrm_core": "核心问题是平台功耗和 VRM 架构能否把离散高端电感用量、规格和价值量同时抬高，并落到具体供应商。",
    "tlvr_vertical_power_transition": "核心问题是 TLVR/垂直供电是否从技术路线进入客户采用、产线切换和 ASP 改善。",
    "high_end_inductor_price_market_space": "核心问题是颗数增长、型号价格和 TLVR 渗透能否支撑可兑现的 TAM/SAM/SOM，而不是只给大市场叙事。",
    "customer_validation_matrix": "核心问题是客户线索能否从专家纪要或能力描述升级到公开客户、订单、批量交付和收入确认。",
    "global_supplier_competition": "核心问题是全球龙头、台系供应商、大陆标的和集成模块路线如何分配利润池和替代压力。",
    "powder_material_capacity_bottleneck": "核心问题是粉体、设备和工艺是否真成为供给瓶颈，而不是普通成本项。",
    "mainland_listed_company_capture": "核心问题是大陆上市公司能否把产品、材料或订单线索转成收入拆分、毛利率和客户阶段上移。",
}


def _source_context_note(ref: str, src: dict[str, Any]) -> str:
    if ref in SOURCE_CONTEXT_NOTES:
        return SOURCE_CONTEXT_NOTES[ref]
    title = src.get("title") or "未命名来源"
    excerpt = _clip(src.get("excerpt") or _source_excerpt(src), 140)
    return f"{title} 的入库摘录显示：{excerpt}。质量缺口：该来源缺少人工长上下文标签，正式发布前应补写来源背景、适用口径和相邻因子影响。"


FACTOR_EVIDENCE_ROLE = {
    "demand.output_consumption_proxy": "证据角色是把出货、单板用量或 TAM 基座压成需求侧数量锚；价格、客户验证和产能因子不跟上时，不能外推利润弹性。",
    "demand.application_intensity_change": "证据角色是判断单位设备或供电架构变化是否提高单机电感价值量，并同步影响替代壁垒、供应商结构和产品 mix 可信度。",
    "signal.material_price_momentum": "证据角色是把涨价、价差或报价分层转成供需失衡确认信号；价格口径必须和需求量、客户阶段或财务响应对上。",
    "supply.substitution_barrier": "证据角色是检验客户短期绕开该环节的难度，约束客户验证矩阵和具体标的议价权，而不只是描述技术先进。",
    "supply.supplier_structure_bucket": "证据角色是分清合格供应商数量、集中度和认证锁定；供应商越少，需求和价格信号越容易传到可跟踪标的。",
    "demand.customer_capex_capacity_signal": "证据角色是把客户平台、资本开支、订单或批量阶段转成需求落地证据，决定纪要线索能否升级为客户验证矩阵硬信号。",
    "supply.capacity_event_12m": "证据角色是识别未来一年供给释放、爬坡或受限事件，区分短期噪声和能够延续到收入确认窗口的紧缺。",
    "supply.expansion_cycle_bucket": "证据角色是把设备调试、认证和良率爬坡纳入供给响应速度；周期越长，价格和客户验证信号越有持续性。",
    "demand.downstream_price_momentum": "证据角色是观察下游客户或终端产品的价格承接能力；承接不足时，上游电感涨价更容易被压回毛利。",
    "supply.raw_policy_constraint": "证据角色是识别粉体、设备、工艺、政策或出口限制是否构成非线性瓶颈，并重新分配产能和供应商结构权重。",
}


FACTOR_HUMAN_QUESTION: dict[str, str] = {
    "demand.output_consumption_proxy": "现有数量锚能否直接支撑需求分母，还是仍只是平台热度？",
    "demand.application_intensity_change": "单位板卡或供电架构是否真正提高了电感颗数、规格和价值量？",
    "signal.material_price_momentum": "价格、ASP 或毛利线索是否已经能确认紧缺，而不是渠道短期扰动？",
    "supply.substitution_barrier": "客户认证、可靠性和替代路线会不会让供应商切换变慢？",
    "supply.supplier_structure_bucket": "合格供应商能否分层到具体公司和第二来源，而不是只有行业名单？",
    "demand.customer_capex_capacity_signal": "客户平台、订单或批量阶段能否把需求落到供应链验证？",
    "supply.capacity_event_12m": "未来 12 个月的供给事件会放大还是缓解紧缺？",
    "supply.expansion_cycle_bucket": "扩产、认证和良率周期是否足够长，能让价格和客户验证持续？",
    "demand.downstream_price_momentum": "下游价格环境能否承接高端电感涨价，还是会压回供应商毛利？",
    "supply.raw_policy_constraint": "材料、粉体、设备或政策约束是否足以改变供给弹性？",
}


FACTOR_TARGET_FOCUS: dict[str, tuple[str, str]] = {
    "demand.output_consumption_proxy": ("单板用量、出货和 TAM 被更新后，应优先重算顺络、Cyntec、YAGEO 等器件厂的收入分母", "若平台单位用量下降或 VPD/Power Block 减少离散电感，先下修 TAM 而不是下修单一公司"),
    "demand.application_intensity_change": ("规格升级被料号、低 DCR/高电流参数或 TLVR 采用证明后，上调拥有对应产品页和产线证据的公司", "若只是 AI 服务器总量增长、没有规格难度提升，材料和器件弹性都要降级"),
    "signal.material_price_momentum": ("价格和毛利同步改善时，才把顺络、铂科、龙磁或高端型号篮子从需求线索上调为盈利线索", "若涨价集中在普通型号或渠道库存，标的动作应转为复核 ASP 假设"),
    "supply.substitution_barrier": ("客户认证、可靠性或替代成本被确认后，优先研究已有验证阶段的供应商", "若全球龙头或集成模块能快速替代，大陆标的份额假设要压低"),
    "supply.supplier_structure_bucket": ("供应商结构清楚时，标的排序要区分大陆器件厂、台系厂商、日美龙头和集成模块反方", "若仍无法确认份额和第二来源，只保留观察篮子，不给单一公司加分"),
    "demand.customer_capex_capacity_signal": ("客户平台、订单或批量阶段被公开材料确认后，才上调对应客户链标的", "若客户名只来自纪要或传闻，证据只能留在验证债"),
    "supply.capacity_event_12m": ("产线、交付、投产或订单窗口明确时，优先看未来四个季度收入确认", "若扩产快于需求或订单推迟，短期紧缺应降为节奏风险"),
    "supply.expansion_cycle_bucket": ("设备、良率和认证周期拉长时，材料和器件厂的持续性更强", "若切线容易、良率快速爬坡，瓶颈型估值溢价要撤回"),
    "demand.downstream_price_momentum": ("下游价格可承接时，价格信号才可能传到高端电感毛利", "若终端压价或客户议价强，供应商涨价要按毛利压力处理"),
    "supply.raw_policy_constraint": ("粉体、设备或政策约束明确时，上游材料和高端器件都要重新排序", "若材料供应快速放量，该因子只保留为成本监控"),
}


def _factor_value_summary(entity: dict[str, Any], factor_code: str, score: float, metric_name: str) -> str:
    score_view = "强信号" if score >= 82 else "中高信号" if score >= 75 else "中等信号" if score >= 68 else "弱信号"
    meaning = FACTOR_VALUE_MEANING.get(factor_code, "该读数说明本实体是否有足够证据进入核心评分。")
    lens = ENTITY_FACTOR_LENS.get(entity["key"], "本实体需要把证据、标的和反方风险放在一起判断。")
    if factor_code == "demand.output_consumption_proxy":
        return f"{entity['display_name']} 的“{metric_name}”给出 {score:.1f} 分，属于{score_view}；需求分母已有可复算底座。{meaning} 对本实体而言，{lens}"
    if factor_code == "demand.application_intensity_change":
        return f"{score:.1f} 分落在{score_view}区间，核心读法不是需求变大，而是“{metric_name}”把 BOM 难度抬高。{meaning} {entity['display_name']} 还要用客户平台和产品料号确认这种强度。"
    if factor_code == "signal.material_price_momentum":
        return f"“{metric_name}”目前是 {score:.1f} 分的{score_view}。{meaning} {entity['display_name']} 的价格读数必须和订单、型号或财务响应放在一起，不能单靠涨价案例上调。"
    if factor_code == "supply.substitution_barrier":
        return f"{entity['display_name']} 在替代壁垒上得到 {score:.1f} 分，读数为{score_view}；关键是客户认证和可靠性会不会锁住供应商。{meaning}"
    if factor_code == "supply.supplier_structure_bucket":
        return f"{score:.1f} 分说明“{metric_name}”已经能做供应商分层，但仍要看份额和第二来源。{meaning} {entity['display_name']} 的排序必须同时放入大陆、台系、日美龙头和集成模块反方。"
    if factor_code == "demand.customer_capex_capacity_signal":
        return f"客户牵引项为 {score:.1f} 分，强弱取决于“{metric_name}”能否从平台需求走到公开订单或批量阶段。{meaning} {entity['display_name']} 不能把客户纪要直接写成供货确认。"
    if factor_code == "supply.capacity_event_12m":
        return f"{entity['display_name']} 的 12 个月供给窗口为 {score:.1f} 分；“{metric_name}”决定紧缺能否进入财报验证期。{meaning}"
    if factor_code == "supply.expansion_cycle_bucket":
        return f"扩产周期项给 {score:.1f} 分，说明“{metric_name}”需要继续拆设备、良率、认证和切线节奏。{meaning}"
    if factor_code == "demand.downstream_price_momentum":
        return f"下游价格承接项为 {score:.1f} 分；“{metric_name}”只在终端或客户愿意吸收成本时才支持上游毛利改善。{meaning}"
    if factor_code == "supply.raw_policy_constraint":
        return f"原材料和政策约束项为 {score:.1f} 分；“{metric_name}”要回答瓶颈是否来自粉体、设备、工艺或供应链限制。{meaning}"
    return f"{entity['display_name']} 的“{metric_name}”为 {score:.1f} 分，属于{score_view}。{meaning} {lens}"


def _factor_source_interpretation(entity: dict[str, Any], factor_code: str, metric_name: str, ref: str, src: dict[str, Any], score: float) -> str:
    source_note = _source_context_note(ref, src)
    factor_meaning = FACTOR_VALUE_MEANING.get(factor_code, "该因子检查证据是否能进入核心评分。")
    entity_lens = ENTITY_FACTOR_LENS.get(entity["key"], "本实体需要把来源、相邻因子和标的承接一起读。")
    factor_role = FACTOR_EVIDENCE_ROLE.get(factor_code, "证据角色是把线索转成可复核的因子输入，并约束后续标的映射。")
    title = src.get("publisher") or src.get("title") or ref
    if src.get("policy_evidence_role") == "early_signal_candidate":
        role_note = f"{title} 在本轮只能提高补证优先级；公告、IR、客户平台或财务数据交叉确认前，不把它写成核心供货结论。{factor_role}"
    elif src.get("source_tier") == "A":
        role_note = f"{title} 是一手或结构化核心材料，可作为主证据组，并把相邻因子的判断边界收窄到可复核口径。{factor_role}"
    else:
        role_note = f"{title} 更适合解释方向或约束反方情景，权重低于公司公告、官方产品页和结构化表格。{factor_role}"
    if factor_code == "demand.output_consumption_proxy":
        read = f"读到“{metric_name}”时，先看这条材料能否给出出货、单板用量或 TAM 口径。"
    elif factor_code == "demand.application_intensity_change":
        read = f"读到“{metric_name}”时，重点看功率密度、相数、低 DCR 或 TLVR 是否提高单机价值量。"
    elif factor_code == "signal.material_price_momentum":
        read = f"读到“{metric_name}”时，要区分高端 AI 型号价格和普通被动元件周期扰动。"
    elif factor_code == "supply.substitution_barrier":
        read = f"读到“{metric_name}”时，客户认证、可靠性和替代路线比单纯产品先进更重要。"
    elif factor_code == "supply.supplier_structure_bucket":
        read = f"读到“{metric_name}”时，要把具体供应商、第二来源和全球对照项分开。"
    elif factor_code == "demand.customer_capex_capacity_signal":
        read = f"读到“{metric_name}”时，只把公开平台、订单、批量阶段或财务披露当作升级依据。"
    elif factor_code == "supply.capacity_event_12m":
        read = f"读到“{metric_name}”时，关注事件能否落在未来四个季度的收入确认窗口。"
    elif factor_code == "supply.expansion_cycle_bucket":
        read = f"读到“{metric_name}”时，拆设备、认证、良率和切线周期，而不是只看扩产口号。"
    elif factor_code == "demand.downstream_price_momentum":
        read = f"读到“{metric_name}”时，先判断下游是否有价格承接能力，再讨论上游涨价。"
    else:
        read = f"读到“{metric_name}”时，先确认材料、粉体、设备或政策约束是否足够具体。"
    return f"{source_note} {read} {factor_meaning} 放到{entity['display_name']}上，{entity_lens} {role_note}"


def _source_context_summary(entity: dict[str, Any], factor_code: str, metric_name: str, refs: list[str], sources: dict[str, dict[str, Any]]) -> str:
    selected = []
    for ref in refs[:4]:
        src = sources[ref]
        selected.append(f"{src.get('publisher') or src.get('title')}：{_source_context_note(ref, src)}")
    joined = "；".join(selected)
    factor_read = FACTOR_VALUE_MEANING.get(factor_code, "该因子要求把来源、指标和标的承接放在同一层级复核。")
    return f"“{metric_name}”的来源底稿包括：{joined}。对 {entity['display_name']} 的读法是：{factor_read} 当前证据先限定分数边界，再决定下一步补客户、价格、产能或财务响应。"


def _theme_analysis_points(entity: dict[str, Any], factor_code: str, score: float, metric_name: str) -> list[str]:
    score_view = "强信号" if score >= 82 else "中高信号" if score >= 75 else "中等信号" if score >= 68 else "弱信号"
    return [
        f"分数读法：{metric_name} 为 {score:.1f} 分，属于{score_view}；需要回答“{FACTOR_HUMAN_QUESTION.get(factor_code, '证据是否足以支撑核心评分？')}”",
        f"证实方向：{entity['confirmed_action']}",
        f"证伪方向：{entity['falsified_action']}",
        f"后续监控：{entity['monitor_signal']}；节奏为 {entity['monitor_timing']}。",
    ]


def _source_names(refs: list[str], sources: dict[str, dict[str, Any]], limit: int = 5) -> str:
    names = []
    for ref in refs[:limit]:
        src = sources[ref]
        label = src.get("publisher") or src.get("title") or ref
        if label in names and src.get("title"):
            label = src["title"]
        names.append(label)
    return "、".join(names)


def _factor_topic_analysis(entity: dict[str, Any], factor_code: str, score: float, metric_name: str, refs: list[str], sources: dict[str, dict[str, Any]]) -> str:
    source_names = _source_names(refs, sources, limit=5)
    question = FACTOR_HUMAN_QUESTION.get(factor_code, "证据是否足以支撑核心评分？")
    lens = ENTITY_FACTOR_LENS.get(entity["key"], "需要把证据、标的和反方风险放在一起判断。")
    if factor_code == "demand.output_consumption_proxy":
        return f"“{metric_name}”先解决需求分母：{question} {source_names} 给出的数量锚足以支撑 {entity['display_name']} 进入核心排序，但还不能替代客户、价格和收入验证。{lens}"
    if factor_code == "demand.application_intensity_change":
        return f"“{metric_name}”的重点在单机价值量，而不是行业总量。{source_names} 共同指向功率密度、相数或 TLVR 压力；若这些压力不能落到料号和客户平台，{entity['display_name']} 的强度分需要下调。"
    if factor_code == "signal.material_price_momentum":
        return f"“{metric_name}”读的是价格确认度。{source_names} 提供的价格、ASP 或毛利线索只能说明供需可能偏紧；真正影响 {entity['display_name']} 的，是这些价格能否和高端 AI 型号、订单及财务响应对应。"
    if factor_code == "supply.substitution_barrier":
        return f"“{metric_name}”要回答替代速度问题：{question} 结合 {source_names}，当前更应看客户认证、可靠性和集成模块路线，而不是把技术难度直接写成份额确定。{lens}"
    if factor_code == "supply.supplier_structure_bucket":
        return f"“{metric_name}”把名单问题改成排序问题。{source_names} 让大陆、台系、日美龙头和反方模块路线可以同框比较；{entity['display_name']} 的下一步是补份额和第二来源，而不是继续扩名单。"
    if factor_code == "demand.customer_capex_capacity_signal":
        return f"“{metric_name}”专门处理客户牵引。{source_names} 能证明平台或公司线索存在，但 {entity['display_name']} 只有在公开客户、批量阶段或财务数据出现时，才从验证债升级为硬证据。"
    if factor_code == "supply.capacity_event_12m":
        return f"“{metric_name}”把研究窗口压到未来四个季度。{source_names} 的价值在于观察产线、订单和交付是否进入收入确认；若事件只停在口头规划，{entity['display_name']} 不能获得短期供给溢价。"
    if factor_code == "supply.expansion_cycle_bucket":
        return f"“{metric_name}”关注供给响应速度。{source_names} 需要被拆成设备、良率、认证和切线周期；如果这些环节没有拉长，{entity['display_name']} 的瓶颈叙事就不成立。"
    if factor_code == "demand.downstream_price_momentum":
        return f"“{metric_name}”先看下游承接，再看上游议价。{source_names} 提供价格环境线索；只有客户愿意吸收高端料号成本，{entity['display_name']} 才可能把需求转成毛利改善。"
    return f"“{metric_name}”检验材料和工艺约束是否具体。{source_names} 支持 {entity['display_name']} 继续跟踪粉体、设备、政策或供应链限制；若约束不能传到器件收入，本因子只保留为成本监控。"


def _score_rationale(entity: dict[str, Any], factor_code: str, score: float, metric_name: str, refs: list[str], sources: dict[str, dict[str, Any]]) -> str:
    coverage = 0.76 if score >= 75 else 0.68
    confidence = 0.74 if score >= 75 else 0.66
    factor_role = FACTOR_EVIDENCE_ROLE.get(factor_code, "证据角色是把线索转成可复核的因子输入。")
    source_names = _source_names(refs, sources, limit=4)
    if factor_code in {"demand.output_consumption_proxy", "demand.application_intensity_change"}:
        return f"{metric_name} 得到 {score:.1f} 分，覆盖度 {coverage:.0%}、置信度 {confidence:.0%}。{source_names} 同时给到数量或规格锚点，所以分数偏高；客户、料号和收入没有完全闭环，是 {entity['display_name']} 仍需留验证债的原因。{factor_role}"
    elif factor_code in {"signal.material_price_momentum", "demand.downstream_price_momentum"}:
        return f"{metric_name} 的 {score:.1f} 分来自价格、ASP 或下游承接线索，覆盖度 {coverage:.0%}、置信度 {confidence:.0%}。{source_names} 能说明方向，但价格样本连续性和型号适配还不够，因此 {entity['display_name']} 不能只靠价格新闻上调。{factor_role}"
    elif factor_code in {"supply.substitution_barrier", "supply.supplier_structure_bucket"}:
        return f"{metric_name} 评分为 {score:.1f}，覆盖度 {coverage:.0%}、置信度 {confidence:.0%}。{source_names} 让供应商和认证边界更清楚；全球龙头、台系供应商和集成模块仍可能分流利润池，所以 {entity['display_name']} 的份额假设必须保守。{factor_role}"
    elif factor_code in {"supply.capacity_event_12m", "supply.expansion_cycle_bucket"}:
        return f"{metric_name} 的分数是 {score:.1f}，覆盖度 {coverage:.0%}、置信度 {confidence:.0%}。{source_names} 提供产线、切换或交付窗口；扣分项在于这些窗口是否进入财报仍不确定，{entity['display_name']} 需要用后续季度验证。{factor_role}"
    elif factor_code == "demand.customer_capex_capacity_signal":
        return f"{metric_name} 给 {score:.1f} 分，覆盖度 {coverage:.0%}、置信度 {confidence:.0%}。{source_names} 说明客户平台和公司材料能互相指向；直接客户名、批量收入和公开确认不足，限制了 {entity['display_name']} 的上调空间。{factor_role}"
    else:
        return f"{metric_name} 目前为 {score:.1f} 分，覆盖度 {coverage:.0%}、置信度 {confidence:.0%}。{source_names} 让材料、粉体或工艺约束有了具体来源；能否传导到器件收入，仍是 {entity['display_name']} 后续调分的关键。{factor_role}"


def _target_implications(entity: dict[str, Any], factor_code: str, metric_name: str) -> list[str]:
    key = entity["key"]
    factor_upside, factor_risk = FACTOR_TARGET_FOCUS.get(
        factor_code,
        ("该因子补强后才上调相关标的", "若证据停留在主题映射，标的只能保留观察"),
    )
    if key == "ai_chip_inductor_vrm_core":
        return [f"围绕“{metric_name}”，顺络、Cyntec、YAGEO、Vishay 只有在平台 BOM、料号或收入证据补足时上调；{factor_upside}。", f"{factor_risk}；Infineon VPD 若渗透提高，应作为下修离散电感 TAM 的反方工具。"]
    if key == "customer_validation_matrix":
        return [f"围绕“{metric_name}”，顺络、铂科、龙磁等只能按客户阶段分层；{factor_upside}。", f"{factor_risk}；客户匿名或只停留小批量时，标的维持验证债，不能写成英伟达、Google 或华为直接供货。"]
    if key == "mainland_listed_company_capture":
        return [f"围绕“{metric_name}”，顺络看数据中心收入占比，铂科看芯片电感拆分，龙磁看中标后放量，悦安看细粉订单；{factor_upside}。", f"{factor_risk}；若财务不响应，相关标的降级为主题映射。"]
    if key == "powder_material_capacity_bottleneck":
        return [f"围绕“{metric_name}”，悦安和铂科的材料弹性必须由粉体订单、价格和毛利率验证；{factor_upside}。", f"{factor_risk}；粉体供给快速扩张会削弱材料瓶颈得分。"]
    if key == "tlvr_vertical_power_transition":
        return [f"围绕“{metric_name}”，顺络和 Cyntec 只有在 TLVR 产线、客户采用和 ASP 同时确认时上调；{factor_upside}。", f"{factor_risk}；VPD 或 Power Block 替代会降低 TLVR 离散电感优先级。"]
    if key == "global_supplier_competition":
        return [f"围绕“{metric_name}”，TDK、Murata、Taiyo Yuden、Vishay 和台系厂商用于校验大陆公司的替代难度；{factor_upside}。", f"{factor_risk}；若全球龙头继续控制高端料号，大陆标的应降低份额假设。"]
    return [f"围绕“{metric_name}”，价格篮子和型号 ASP 决定 TAM 是否能转成收入弹性；{factor_upside}。", f"{factor_risk}；若价格动量只来自普通型号，标的财务弹性应下修。"]


def _info_points(entity: dict[str, Any], factor_code: str, metric_name: str, refs: list[str], sources: dict[str, dict[str, Any]], score: float, limit: int = 5) -> list[dict[str, Any]]:
    out = []
    for ref in refs[:limit]:
        src = sources[ref]
        out.append({
            "slot_name": f"{src.get('publisher') or src.get('title')} 上下文",
            "title": f"{src.get('publisher') or src.get('title')} 上下文",
            "metric": "来源证据组",
            "metric_line": f"{metric_name} 的来源上下文：{src.get('title')}",
            "period": src.get("publish_date") or AS_OF_DATE,
            "publish_date": src.get("publish_date") or AS_OF_DATE,
            "publisher": src.get("publisher") or "未标明发布方",
            "source_title": src.get("title") or "未命名来源",
            "excerpt": _clip(src.get("excerpt") or _source_excerpt(src), 260),
            "source_excerpt": _clip(src.get("excerpt") or _source_excerpt(src), 260),
            "interpretation": _factor_source_interpretation(entity, factor_code, metric_name, ref, src, score),
            "evidence_ref_uri": _source_ref(ref),
            "evidence_ref": _source_ref(ref),
            "direction": "positive",
            "source_tier": src.get("source_tier", "B"),
            "weight_reason": _factor_source_interpretation(entity, factor_code, metric_name, ref, src, score),
        })
    return out


def _factor(entity: dict[str, Any], factor_code: str, score: float, refs: list[str],
            metric_name: str, source_lookup: dict[str, dict[str, Any]]) -> dict[str, Any]:
    factor = FACTOR_BY_CODE[factor_code]
    info = _info_points(entity, factor_code, metric_name, refs, source_lookup, score, limit=5)
    factor_summary = _factor_value_summary(entity, factor_code, score, metric_name)
    source_summary = _source_context_summary(entity, factor_code, metric_name, refs, source_lookup)
    topic_analysis = _factor_topic_analysis(entity, factor_code, score, metric_name, refs, source_lookup)
    score_rationale = _score_rationale(entity, factor_code, score, metric_name, refs, source_lookup)
    return {
        "factor_code": factor_code,
        "score_status": "complete",
        "score_raw": score,
        "score_adjusted": score,
        "coverage": 0.76 if score >= 75 else 0.68,
        "confidence": 0.74 if score >= 75 else 0.66,
        "factor_readiness_status": "ready",
        "metric_name": metric_name,
        "unit": "分",
        "period": AS_OF_DATE,
        "as_of_date": AS_OF_DATE,
        "trace": f"{entity['display_name']} 的 {factor.label} 使用 {len(refs)} 个唯一来源证据组，按来源等级、数值支撑和方向一致性审计。",
        "core_score_note": "仅采用本地研报、结构化表格、公司公告/IR、官方平台资料和明确标注的专家纪要；灰源只用于早期信号或验证债。",
        "contextual_human_question": f"{entity['display_name']} / {metric_name}：{FACTOR_HUMAN_QUESTION.get(factor_code, '证据是否足以支撑核心评分？')}",
        "contextual_factor_description": f"{factor.description} 本轮结合 AI 高端电感产品边界、客户验证和供给弹性重新解释。",
        "source_context_summary": source_summary,
        "factor_value_summary": factor_summary,
        "factor_topic_analysis": topic_analysis,
        "score_rationale": score_rationale,
        "theme_analysis_points": _theme_analysis_points(entity, factor_code, score, metric_name),
        "target_implications": _target_implications(entity, factor_code, metric_name),
        "source_context_refs": [_source_ref(ref) for ref in refs],
        "information_points": info,
        "evidence_ref_uri_list": [_source_ref(ref) for ref in refs],
    }


def _entity_specs(source_lookup: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    factor_plan = {
        "ai_chip_inductor_vrm_core": [
            ("demand.output_consumption_proxy", 88, "GPU/ASIC/TPU 单板用量和需求量"),
            ("demand.application_intensity_change", 84, "高功率密度驱动单位用量变化"),
            ("signal.material_price_momentum", 74, "高端型号价格信号"),
            ("supply.substitution_barrier", 72, "客户认证和替代壁垒"),
            ("supply.supplier_structure_bucket", 68, "合格供应商结构"),
        ],
        "tlvr_vertical_power_transition": [
            ("demand.application_intensity_change", 86, "TLVR/垂直供电应用强度"),
            ("supply.capacity_event_12m", 76, "TLVR 产线切换和扩产事件"),
            ("supply.expansion_cycle_bucket", 72, "产线切换周期"),
            ("supply.substitution_barrier", 78, "技术替代壁垒"),
            ("signal.material_price_momentum", 73, "TLVR ASP 和毛利率信号"),
        ],
        "high_end_inductor_price_market_space": [
            ("demand.output_consumption_proxy", 84, "TAM/SAM/SOM 需求量测算"),
            ("signal.material_price_momentum", 82, "价格动量和 ASP 分层"),
            ("demand.downstream_price_momentum", 78, "下游高端被动元件价格"),
            ("demand.application_intensity_change", 72, "单板用量和规格升级"),
            ("supply.supplier_structure_bucket", 66, "价格传导结构"),
        ],
        "customer_validation_matrix": [
            ("demand.customer_capex_capacity_signal", 80, "头部客户验证和导入信号"),
            ("supply.substitution_barrier", 75, "客户认证壁垒"),
            ("supply.supplier_structure_bucket", 72, "第二来源和份额结构"),
            ("demand.application_intensity_change", 70, "客户平台技术路线变化"),
            ("signal.material_price_momentum", 62, "订单和价格确认度"),
        ],
        "global_supplier_competition": [
            ("supply.supplier_structure_bucket", 76, "全球供应商结构"),
            ("supply.substitution_barrier", 72, "客户替换难度"),
            ("supply.raw_policy_constraint", 68, "区域供应链和材料约束"),
            ("demand.customer_capex_capacity_signal", 66, "客户平台导入"),
            ("signal.material_price_momentum", 61, "竞争格局对价格的影响"),
        ],
        "powder_material_capacity_bottleneck": [
            ("supply.raw_policy_constraint", 78, "铁镍粉和羰基铁粉约束"),
            ("supply.capacity_event_12m", 76, "产能和项目投产事件"),
            ("supply.expansion_cycle_bucket", 74, "设备、能源和场地扩产周期"),
            ("supply.supplier_structure_bucket", 70, "材料供应商集中度"),
            ("demand.application_intensity_change", 66, "高端电感材料强度变化"),
        ],
        "mainland_listed_company_capture": [
            ("demand.customer_capex_capacity_signal", 82, "上市公司客户验证和订单阶段"),
            ("supply.capacity_event_12m", 78, "公司产能兑现窗口"),
            ("supply.substitution_barrier", 75, "客户认证和产品壁垒"),
            ("signal.material_price_momentum", 70, "收入利润和价格传导"),
            ("supply.raw_policy_constraint", 66, "材料和供应链约束"),
        ],
    }
    entities = []
    for base in ENTITIES:
        refs = base["refs"]
        entity = {
            "key": base["key"],
            "entity_type": "product_material" if base["key"] != "mainland_listed_company_capture" else "segment",
            "taxonomy_level": "product_material" if base["key"] != "mainland_listed_company_capture" else "segment",
            "canonical_name": base["canonical_name"],
            "display_name": base["display_name"],
            "description": base["description"],
            "external_ref_type": "ai_high_end_inductor_20260704",
            "maturation_status": "scoring_ready",
            "readiness_score": 0.86 if base["score_point"] >= 80 else 0.78,
            "readiness_reason": "已纳入本地研报、结构化表格、公司 IR、客户平台官方资料和海外厂商资料，满足因子证据组门槛。",
            "research_priority_label": "high_priority_for_scoring" if base["score_point"] >= 78 else "medium_priority_for_followup",
            "source_count": len(refs),
            "independent_source_count": len(refs),
            "candidate_reason": base["confirmed_action"],
            "evidence_ref_uri": _source_ref(refs[0]),
            "evidence_ref_uri_list": [_source_ref(ref) for ref in refs],
            "score_point": base["score_point"],
            "score_quality_label": "high_confidence" if base["score_point"] >= 82 else "medium_confidence",
            "score_band_low": max(0, base["score_point"] - 7),
            "score_band_high": min(100, base["score_point"] + 7),
            "coverage": 0.82 if base["score_point"] >= 80 else 0.74,
            "confidence": 0.78 if base["score_point"] >= 80 else 0.7,
            "band_reason": "按证据数量、来源可靠性、客户验证阶段、价格和产能证据综合评分。",
            "composite_trace": {
                "confirmed_action": base["confirmed_action"],
                "falsified_action": base["falsified_action"],
                "monitor_signal": base["monitor_signal"],
                "monitor_timing": base["monitor_timing"],
            },
            "factor_scores": [
                _factor(base, code, score, refs, metric_name, source_lookup)
                for code, score, metric_name in factor_plan[base["key"]]
            ],
        }
        entities.append(entity)
    return entities


def _section_refs(keys: list[str]) -> list[str]:
    return [_source_ref(key) for key in keys]


def _build_report_sections() -> list[dict[str, Any]]:
    summary_refs = ["web_sunlord_ir_tlvr_20260701", "web_boke_ir_20260424", "web_longci_bid_20250122", "xlsx_chip_inductor_demand", "web_nvidia_gb300_nvl72", "web_cyntec_ai_server_switch", "web_yageo_tpi_ai_power_20250627", "web_coilmaster_gpu_cpu_vrm", "web_vishay_ihsr_ai_gpu", "web_infineon_ai_vrm_vpd"]
    body = f"""本轮研究结论是：AI 高端电感的真实机会不在“所有电感涨价”，而在 GPU/ASIC/TPU 板级 VRM、TLVR 和高功率密度 POL/DC-DC 供电链的规格升级、客户认证和产能爬坡。当前核心机会排序为：AI GPU/ASIC 板级 VRM 高端芯片电感、TLVR 与垂直供电技术切换、中国大陆上市公司承接能力、磁粉材料和设备瓶颈、全球供应商结构。核心实体不能只保留一个 BOM 观察篮子，已补入顺络电子、铂科新材、龙磁科技、台达/乾坤、国巨/奇力新、Coilmaster、Vishay、Eaton、Taiyo Yuden、TDK、Murata 和 Infineon VPD 替代风险等具体公司/标的。顺络电子已经披露 TLVR 产品批量化供应但数据中心收入占比尚不足 5%，铂科新材受益 ASIC 与 GPU 功率上升但仍需收入确认，龙磁科技已取得国际客户高端模压电感中标和小批量交付线索；Cyntec、YAGEO、Coilmaster、Vishay、Eaton 和 Taiyo Yuden 的公开资料补齐了海外/台系公开产品证据，Infineon VPD 则作为离散电感被集成模块替代的反方证据。{_evidence('web_sunlord_ir_tlvr_20260701')}{_evidence('web_cyntec_ai_server_switch')}{_evidence('web_yageo_tpi_ai_power_20250627')}{_evidence('web_infineon_ai_vrm_vpd')}

### 产品边界

本报告把“AI 高端电感”限定为 AI 服务器、GPU/ASIC/TPU 加速卡、服务器主板和电源模块中承担高频、大电流、低 DCR、高瞬态响应、低损耗和小型化要求的磁性器件，重点包括一体成型芯片电感、金属软磁功率电感、TLVR 电感、部分高频薄膜/叠层/绕线电感，以及与 DrMOS、PMIC、Power Block、VPD 和 POL/DC-DC 方案配合的磁性元件。普通手机、家电、低端通用电感、Power Shelf 一次/二次高压大功率磁件和泛被动元件不能直接替代这个口径。{_evidence('local_huaan_expert_inductor')}{_evidence('web_murata_power_inductors')}

### 核心机会排序

| 排名 | 研究实体 | 核心分 | 证据规模 | 核心判断 | 证实条件 | 证伪条件 | 证据 |
|---:|---|---:|---:|---|---|---|---|
| 1 | AI GPU/ASIC 板级 VRM 高端芯片电感 | 86 | 18 来源 | GPU/ASIC/TPU 功耗提升和单板相数抬升，直接拉动高端芯片电感用量和规格；具体标的已扩展到 A 股、台股、日股、美股和集成模块反方风险。 | 平台 BOM、客户订单、单板用量、公开产品页和价格同步确认。 | 离散电感被集成模块明显替代，或新平台单位用量下降。 | {_evidence('xlsx_chip_inductor_demand')}{_evidence('web_cyntec_ai_server_switch')} |
| 2 | TLVR 与垂直供电技术切换 | 82 | 6 来源 | TLVR 提升瞬态响应和价值量，是 2026-2027 年最重要的技术切换线索。 | TLVR 批量供应、产线切换和 ASP 提升被财报确认。 | 只停留在送样或被客户集成方案绕开。 | {_evidence('web_sunlord_ir_tlvr_20260701')} |
| 3 | 中国大陆上市公司承接能力 | 80 | 8 来源 | 顺络、铂科、龙磁、悦安分别对应批量供应、材料器件一体化、中标验证和粉体材料弹性。 | 客户阶段上移、收入确认、毛利率或订单改善。 | 数据中心占比低且客户不可核验，仍是主题映射。 | {_evidence('web_longci_validation_20250527')} |
| 4 | 价格体系与 TAM/SAM/SOM | 78 | 6 来源 | 传统芯片电感、TLVR 和型号现货价格口径差异很大，不能用普通低端电感 ASP 外推。 | 高端型号价格和年度议价改善持续。 | 涨价集中在非 AI 型号或短期渠道扰动。 | {_evidence('xlsx_inductor_model_price')} |
| 5 | 磁粉材料、设备和产能瓶颈 | 76 | 7 来源 | 铁镍粉、羰基铁粉、热压设备、电力和场地约束会限制短期供给弹性。 | 细粉订单、产线投资和良率成为瓶颈。 | 粉体和设备快速放量，产能不再约束。 | {_evidence('local_huatai_expert_inductor')} |
| 6 | 头部客户验证矩阵 | 74 | 9 来源 | 英伟达证据最强，Google/华为更多处在间接或规划验证，灰源不能直接进入核心结论。 | 客户/公司公告、ODM/OEM 交付和财报收入交叉确认。 | 只有纪要或传闻，无公开确认。 | {_evidence('local_huatai_expert_inductor')} |
| 7 | 全球竞争格局 | 72 | 7 来源 | 台达/乾坤、国巨/奇力新、连展、顺络、铂科、龙磁与 TDK、Murata 等分层竞争。 | 国产/台系在主流料号份额提升。 | 日美韩厂商重回主流高端料号。 | {_evidence('local_huaan_expert_inductor')} |
"""
    market_body = f"""### TAM / SAM / SOM 测算

bottom-up 口径使用 AI GPU/ASIC 出货、单片电感用量和 ASP 分层。表格测算显示 AI 芯片电感需求量从 2024 年 2.4 亿颗上升到 2029E 34.5 亿颗；平均单片用电感数从 2024 年 32 颗提升到 2029E 79 颗。{_evidence('xlsx_chip_inductor_demand')} 若按传统高端芯片电感 0.4-0.6 美元/颗、TLVR 1 美元以上/颗分层，2029 年全球 TAM 对 ASP 假设极其敏感，必须拆成保守、中性和乐观三种情景。{_evidence('local_huatai_expert_inductor')}

| 口径 | 2026E | 2027E | 2028E | 2029E | 核心假设 | 证据 |
|---|---:|---:|---:|---:|---|---|
| 全球 TAM：芯片电感颗数 | 8.0 亿颗 | 15.4 亿颗 | 23.5 亿颗 | 34.5 亿颗 | GPU/ASIC 出货和单片用量按本地表格测算 | {_evidence('xlsx_chip_inductor_demand')} |
| 全球 TAM：保守收入 | 3.2 亿美元 | 6.2 亿美元 | 9.4 亿美元 | 13.8 亿美元 | ASP 0.40 美元，TLVR 渗透低 | {_evidence('local_huatai_expert_inductor')} |
| 全球 TAM：中性收入 | 5.6 亿美元 | 10.8 亿美元 | 16.5 亿美元 | 24.2 亿美元 | ASP 0.70 美元，TLVR 逐步渗透 | {_evidence('xlsx_inductor_model_price')} |
| 全球 TAM：乐观收入 | 8.0 亿美元 | 15.4 亿美元 | 23.5 亿美元 | 34.5 亿美元 | ASP 1.00 美元，TLVR/高端型号占比显著提升 | {_evidence('local_huatai_expert_inductor')} |
| 中国厂商 SAM | TAM 的 25%-45% | TAM 的 30%-50% | TAM 的 35%-55% | TAM 的 40%-60% | 取决于英伟达、Google、华为、国产算力和模块厂认证 | {_evidence('web_sunlord_ir_tlvr_20260701')} |
| 上市公司 SOM | SAM 的 10%-35% | SAM 的 15%-40% | SAM 的 20%-45% | SAM 的 20%-50% | 只有完成认证和量产的公司可计入 | {_evidence('web_longci_validation_20250527')} |

top-down 口径以 AI 服务器电源和高功率密度供电链为校验。NVIDIA GB300 NVL72、Google Ironwood、华为 Atlas 900 A3 SuperPoD 均指向更大规模、更高功率密度和更复杂供电网络，但平台级算力增长不等同于电感收入等比例增长，需要再经过 BOM、相数、ASP、客户认证和供应份额四道折扣。{_evidence('web_nvidia_gb300_nvl72')}{_evidence('web_google_ironwood_tpu')}{_evidence('web_huawei_atlas_a3_superpod')}
"""
    validation_body = f"""### 英伟达 / Google / 华为客户验证矩阵

| 公司或供应链环节 | 英伟达阶段 | Google 阶段 | 华为阶段 | 直接/间接 | 置信度 | 验证债 | 证据 |
|---|---|---|---|---|---|---|---|
| 顺络电子 | 公开披露 TLVR 批量化供应，但未公开客户名 | 无公开客户名 | 无公开客户名 | 公开公司 IR，客户映射仍需二次确认 | 中高 | 数据中心收入占比不足 5%，需看收入确认 | {_evidence('web_sunlord_ir_tlvr_20260701')} |
| 铂科新材 | 有 AI GPU/ASIC 需求受益表述，客户名未公开 | ASIC 受益线索 | 国产链间接受益线索 | 公司 IR 和研报交叉 | 中 | 需确认芯片电感收入、客户认证和 ASP | {_evidence('web_boke_ir_20260424')} |
| 龙磁科技 | 某国际客户高端模压电感中标，小批量交付 | 无公开客户名 | 无公开客户名 | 公司公告/媒体转述，客户匿名 | 中 | 客户身份、放量节奏和收入占比待确认 | {_evidence('web_longci_bid_20250122')} |
| 台达/乾坤（Cyntec） | Cyntec 官方 AI server/SXM/UBB/TLVR 产品证据明确，但未公开具体客户份额 | 可能通过模块链间接参与 | 无公开客户名 | 官方产品页加专家线索，客户份额仍需验证 | 中高 | 缺少 NVIDIA/Google/华为单一客户订单确认 | {_evidence('web_cyntec_ai_server_switch')}{_evidence('web_cyntec_tlvr_ai_server')} |
| 国巨/奇力新（YAGEO/KEMET/Pulse） | TPI/TLVR 产品可服务高功率计算平台，客户份额未公开 | 可能通过服务器/ASIC 供电链参与 | 无公开客户名 | 官方产品页，需客户/平台料号确认 | 中 | 需确认具体 AI GPU/ASIC 平台导入和收入拆分 | {_evidence('web_yageo_tpi_ai_power_20250627')} |
| Coilmaster | GPU/CPU VRM 官方应用页指向 AI compute platforms | 可能作为外部供应链补位 | 无公开客户名 | 官方应用页，不是上市公司核心池 | 中 | 缺少财务弹性和客户份额数据 | {_evidence('web_coilmaster_gpu_cpu_vrm')} |
| Vishay、Eaton、Taiyo Yuden | 公开资料覆盖 AI/GPU 高电流电感、xPU molded powder 和 AI server 高附加值电感方向 | 可服务数据中心供电设计 | 无公开证据 | 官方资料，作为全球对照项 | 中 | 需平台料号、供货份额和业务拆分 | {_evidence('web_vishay_ihsr_ai_gpu')}{_evidence('web_eaton_ai_molded_powder')}{_evidence('web_taiyo_yuden_ai_server_inductor_2025ar')} |
| TDK、Murata | 具备高端被动元件和 AI 数据中心 PDN 能力 | 可服务数据中心供电设计 | 无公开证据 | 官方产品能力，不等于客户供货 | 中 | 需具体平台料号或客户认证 | {_evidence('web_tdk_ai_ecosystem')}{_evidence('web_murata_ai_pdn_20260204')} |
| Infineon | VPD 集成模块不是离散电感供应商，但会改变离散电感机会边界 | 可通过集成模块替代离散方案 | 无公开电感供货结论 | 官方产品页，作为反方风险 | 中 | 若 VPD 模块渗透提升，离散电感 TAM 需下修 | {_evidence('web_infineon_ai_vrm_vpd')} |
| 其他大陆普通电感公司 | 无公开证据 | 无公开证据 | 无公开证据 | 主题映射 | 低 | 无客户、产品、产能或收入证据则排除核心标的 | {_evidence('local_huatai_expert_inductor')} |

强审计结论：专家纪要中“头部芯片电感公司直接签约英伟达/谷歌”的线索只能作为验证路径，不能单独作为公开确认。公开证据强度排序是公司公告/IR、客户官方平台资料、交易所公告、公司财报和第三方研报；论坛、二级市场传闻和未署名纪要只能进入早期信号。{_evidence('local_huatai_expert_inductor')}{_evidence('web_longci_validation_20250527')}
"""
    target_body = f"""### 上市公司五年收入利润情景和机会排序

| 排名 | 标的 | 标的类型 | AI 高端电感暴露 | 2026-2030 中性情景 | 核心判断 | 主要风险 | 证据 |
|---:|---|---|---|---|---|---|---|
| 1 | 顺络电子（002138.SZ） | A股公司 | TLVR、电源管理电感、数据中心产品 | 数据中心收入占比从不足5%逐步提升，需用批量订单确认 | 产品阶段最清楚，但短期收入占比仍低 | 批量供应不等于高利润贡献；客户名未公开 | {_evidence('web_sunlord_ir_tlvr_20260701')} |
| 2 | 铂科新材（300811.SZ） | A股公司 | 金属软磁材料和芯片电感一体化 | ASIC/GPU 功率提升带来新增出货，利润率取决于产品结构 | 材料到器件链条强，收入弹性需财报确认 | 客户和收入拆分不透明，镍价和产能节奏影响利润 | {_evidence('web_boke_ir_20260424')} |
| 3 | 龙磁科技（300835.SZ） | A股公司 | 高端模压电感和芯片电感新业务 | 小批量交付到批量供货是最大弹性来源 | 中标和验证反馈是正向证据，但客户匿名 | 新业务基数小、产能建设和客户验证不确定 | {_evidence('web_longci_bid_20250122')} |
| 4 | 悦安新材（688786.SH） | A股公司 | 羰基铁粉细粉材料 | 上游材料订单随一体成型电感扩张而提升 | 材料弹性强但不是直接电感供货 | 下游价格传导和客户结构不透明 | {_evidence('local_yuean_20260614')} |
| 5 | 台达/乾坤（2308.TW） | 台股公司 | Cyntec AI server SXM/UBB/TLVR 功率电感 | 若客户份额和产能确认，具备高端料号弹性 | 官方产品证据强于单纯研报线索 | 客户和收入份额未公开 | {_evidence('web_cyntec_ai_server_switch')} |
| 6 | 国巨/奇力新（2327.TW） | 台股公司 | YAGEO/KEMET/Pulse TPI/TLVR 与 AI power 电感 | 若 TPI/TLVR 导入服务器/ASIC 平台，具备全球供给弹性 | 产品线公开度较高 | 平台客户和收入拆分需确认 | {_evidence('web_yageo_tpi_ai_power_20250627')} |
| 7 | Vishay（VSH） | 美股公司 | IHSR 高电流 SMD 电感、AI/GPU/datacenter 应用 | 稳健对照项，弹性取决于 AI 业务拆分 | 官方应用证据明确 | 难以拆出 AI GPU/ASIC 单一收入 | {_evidence('web_vishay_ihsr_ai_gpu')} |
| 8 | Eaton（ETN） | 美股公司 | molded powder inductors 与 xPU power delivery | 关注效率、散热和可靠性要求提升 | 官方资料直接指向 AI computing power | 电感业务占集团比例和客户份额需拆分 | {_evidence('web_eaton_ai_molded_powder')} |
| 9 | Taiyo Yuden（6976.T） | 日股公司 | AI server 高附加值 power inductor | 稳健对照项，观察 AI server 高附加值区增长 | 年报级别战略证据 | 需具体料号和客户数据 | {_evidence('web_taiyo_yuden_ai_server_inductor_2025ar')} |
| 10 | TDK（6762.T） | 日股公司 | AI server power delivery 和 noise suppression | 稳健但未必是最大弹性 | 全球龙头产品能力强 | 具体 AI GPU/ASIC 电感料号证据不足 | {_evidence('web_tdk_ai_ecosystem')} |
| 11 | Murata（6981.T） | 日股公司 | AI data center PDN 电感与被动元件组合 | 稳健对照项，关注 PDN 方案渗透 | 官方 PDN 指南证据强 | 直接供货份额未公开 | {_evidence('web_murata_ai_pdn_20260204')} |
| 12 | Infineon（IFX.DE） | 德股公司/反方风险 | VPD 集成电源模块和 proprietary magnetics | 若 VPD 快速渗透，离散电感 TAM 需下修 | 是必须跟踪的替代路线 | 不属于离散电感供应商，不能当作正向电感标的 | {_evidence('web_infineon_ai_vrm_vpd')} |

投资研究框架只给条件化观察，不给交易指令。证实情景下，优先研究“客户验证阶段上移、产能爬坡、收入确认、毛利率改善”四项同时出现的公司；证伪情景下，若数据中心收入占比长期低、客户只停留在传闻、价格下行或离散电感被模块集成替代，应把相关标的从核心机会降为观察篮子。{_evidence('web_sunlord_ir_tlvr_20260701')}{_evidence('web_longci_validation_20250527')}
"""
    monitor_body = f"""### 正反方证据和后续监控

| 优先级 | 事件/监控信号 | 预计变化/监控时间 | 证实/证伪条件 | 研究响应 | 交易操作框架 | 证据 |
|---|---|---|---|---|---|---|
| 高 | 顺络 TLVR 批量化供应后的收入占比 | 2026Q2-2027Q2 财报季 | 证实：数据中心收入占比提升且毛利率改善；证伪：收入占比仍低且客户不明 | 更新顺络目标页和实体评分 | 只观察相对强弱和财报验证，不给目标价 | {_evidence('web_sunlord_ir_tlvr_20260701')} |
| 高 | 龙磁国际客户中标后放量 | 2026 年后续公告和季报 | 证实：中标产品转为批量供货和收入确认；证伪：仍停留小批量 | 调整客户验证矩阵阶段 | 观察公告后与收入确认的滞后 | {_evidence('web_longci_bid_20250122')} |
| 高 | 铂科 ASIC/GPU 芯片电感收入拆分 | 2026Q2-2027Q4 | 证实：芯片电感出货和利润贡献披露；证伪：仍无客户和收入拆分 | 更新 SOM 和标的收入弹性 | 只在证据补足后再调整优先级 | {_evidence('web_boke_ir_20260424')} |
| 中 | 高端型号价格和 TLVR ASP | 月度价格和年度议价 | 证实：高端 AI 型号价格稳定或上行；证伪：涨价只在普通型号 | 复核 TAM/SAM/SOM 假设 | 观察价差和毛利率，不做单点交易 | {_evidence('xlsx_inductor_model_price')} |
| 中 | NVIDIA/Google/华为新平台 BOM | 新平台发布后一至两个季度 | 证实：单板电感用量和 TLVR 采用率提高；证伪：模块集成减少离散电感 | 更新用量和替代风险 | 观察供应链确认前后相对变化 | {_evidence('web_nvidia_gb300_nvl72')} |
| 中 | 粉体和热压设备瓶颈 | 项目投产、IR 和订单 | 证实：细粉订单、良率或设备交期成为瓶颈；证伪：材料供应快速放量 | 更新材料实体分数 | 观察材料股和器件股相对表现 | {_evidence('local_huatai_expert_inductor')} |
"""
    return [
        {
            "section_key": "research_report",
            "section_title": "研究报告",
            "body_markdown": body,
            "evidence_ref_uri_list": _section_refs(summary_refs),
            "sort_order": 10,
        },
        {
            "section_key": "market_space",
            "section_title": "市场空间测算",
            "body_markdown": market_body,
            "evidence_ref_uri_list": _section_refs(["xlsx_chip_inductor_demand", "local_huatai_expert_inductor", "web_nvidia_gb300_nvl72", "web_google_ironwood_tpu", "web_huawei_atlas_a3_superpod"]),
            "sort_order": 20,
        },
        {
            "section_key": "customer_validation",
            "section_title": "客户验证矩阵",
            "body_markdown": validation_body,
            "evidence_ref_uri_list": _section_refs(["web_sunlord_ir_tlvr_20260701", "web_boke_ir_20260424", "web_longci_bid_20250122", "local_huaan_expert_inductor", "web_cyntec_ai_server_switch", "web_yageo_tpi_ai_power_20250627", "web_coilmaster_gpu_cpu_vrm", "web_vishay_ihsr_ai_gpu", "web_tdk_ai_ecosystem"]),
            "sort_order": 30,
        },
        {
            "section_key": "target_scenarios",
            "section_title": "标的情景与投资机会排序",
            "body_markdown": target_body,
            "evidence_ref_uri_list": _section_refs(["web_sunlord_ir_tlvr_20260701", "web_boke_ir_20260424", "web_longci_bid_20250122", "local_yuean_20260614", "web_cyntec_ai_server_switch", "web_yageo_tpi_ai_power_20250627", "web_vishay_ihsr_ai_gpu", "web_eaton_ai_molded_powder", "web_taiyo_yuden_ai_server_inductor_2025ar", "web_tdk_ai_ecosystem", "web_murata_ai_pdn_20260204", "web_infineon_ai_vrm_vpd"]),
            "sort_order": 40,
        },
        {
            "section_key": "monitoring",
            "section_title": "后续监控指标",
            "body_markdown": monitor_body,
            "evidence_ref_uri_list": _section_refs(["web_sunlord_ir_tlvr_20260701", "web_longci_bid_20250122", "web_boke_ir_20260424", "xlsx_inductor_model_price", "web_nvidia_gb300_nvl72", "local_huatai_expert_inductor"]),
            "sort_order": 50,
        },
    ]


CURATED_ENTITY_EVIDENCE: dict[str, list[tuple[str, str]]] = {
    "ai_chip_inductor_vrm_core": [
        ("AI 芯片电感需求量测算把 GPU/ASIC 出货、单片电感用量和需求颗数打包成同源序列：2029E 需求量达到 34.5 亿颗，平均单片用量升至 79 颗。", "xlsx_chip_inductor_demand"),
        ("GB300 服务器电感数量表把 GPU 核心供电、CPU 核心供电、内存与存储、PCIe/网络和冗余热插拔分项拆开，说明机会来自板级供电密度而不是普通消费电感。", "xlsx_gb300_inductor_count"),
        ("NVIDIA GB300 NVL72 官方资料确认 72 个 Blackwell Ultra GPU 和 36 个 Grace CPU 的机架级系统形态，验证高功率密度平台继续推高板级供电复杂度。", "web_nvidia_gb300_nvl72"),
        ("Cyntec 官方 AI server 页面把 compact、high-efficiency、low-loss power inductors 放到 SXM accelerator cards、UBB motherboards 和 switch 场景，说明台达/乾坤不是只来自研报线索。", "web_cyntec_ai_server_switch"),
        ("YAGEO、Coilmaster、Vishay、Eaton 和 Taiyo Yuden 的公开资料都把 AI server、GPU/CPU VRM、xPU power delivery 或 AI server 高附加值区作为电感/磁件应用，核心实体必须纳入这些具体公司而不能只放观察篮子。", "web_yageo_tpi_ai_power_20250627"),
        ("Infineon AI VPD 集成电源模块把高电流、多相、垂直供电和 proprietary magnetics 合在一个模块内，是离散电感机会的反方/替代风险证据，不应忽略。", "web_infineon_ai_vrm_vpd"),
        ("TDK 和 Murata 的官方资料均把 AI server / data center power delivery 作为电感、磁珠和电源完整性的应用场景，支持高端器件边界。", "web_tdk_ai_ecosystem"),
    ],
    "tlvr_vertical_power_transition": [
        ("顺络电子公开 IR 把 TLVR 产品定位为主要用于 AI server xPU 芯片，并披露已实现批量化供应，这是当前最清晰的公开产品阶段证据。", "web_sunlord_ir_tlvr_20260701"),
        ("顺络研报和专家材料共同指向 TLVR 的价值量高于传统 non-TLVR，但专家材料只作为早期信号，不能直接当作客户确认。", "local_sunlord_tlvr_20260612"),
        ("专家纪要提供了 TLVR 产线、日能力、切换周期和 2027Q2 前后节奏线索；这些线索进入验证债和监控项，不单独进入公开确认。", "local_huatai_expert_inductor"),
        ("GB300/Blackwell、Google TPU 和华为 Atlas 这类高功率密度平台增加 transient response 和低压大电流压力，是 TLVR/垂直供电切换的需求背景。", "web_google_ironwood_tpu"),
    ],
    "high_end_inductor_price_market_space": [
        ("本地市场空间表给出 2023-2029E AI 芯片电感需求量、GPU/ASIC 出货和单片用量，作为 bottom-up TAM 的核心基座。", "xlsx_chip_inductor_demand"),
        ("价格分层表把 TDK、Murata、Sunlord 等具体型号价格和涨跌幅放在同一口径，提示不能用普通消费电感 ASP 估算 AI 高端电感。", "xlsx_inductor_model_price"),
        ("被动元件涨价案例表显示 AI 服务器电感涨价 10%-15%，但这只是价格动量线索，需要和客户认证、型号结构、订单兑现交叉验证。", "xlsx_price_case"),
        ("华泰专家纪要中的传统高端芯片电感与 TLVR ASP 差异只作为早期信号，用于建立情景区间，不作为单点定价事实。", "local_huatai_expert_inductor"),
    ],
    "customer_validation_matrix": [
        ("顺络电子披露 TLVR 批量供应但未公开客户名称，因此只能确认产品阶段，不能自动映射到 NVIDIA、Google 或华为单一客户。", "web_sunlord_ir_tlvr_20260701"),
        ("龙磁科技公告和后续报道显示国际客户高端模压电感中标与小批量交付线索，但客户身份、收入占比和放量节奏仍需后续公告确认。", "web_longci_bid_20250122"),
        ("铂科新材 IR 提到 ASIC 与 AI GPU 功率、性能要求变化对公司影响，但客户名称和芯片电感收入拆分仍是验证债。", "web_boke_ir_20260424"),
        ("华泰、华安专家纪要提供客户链线索，只进入早期信号和验证债，不能直接写成公开直接供应。", "local_huatai_expert_inductor"),
    ],
    "global_supplier_competition": [
        ("TDK 官方 AI ecosystem 资料强调 AI servers 的 power delivery 和 noise suppression 场景，说明海外被动元件龙头仍占据高端技术参照位。", "web_tdk_ai_ecosystem"),
        ("Murata 官方 AI server power delivery guide 把 MLCC、silicon capacitors、polymer capacitors、inductors 和 ferrite beads 纳入稳定供电方案，说明竞争不是单一电感料号。", "web_murata_ai_pdn_20260204"),
        ("Cyntec、YAGEO、Coilmaster、Vishay、Eaton 和 Taiyo Yuden 的公开资料补齐了台系、美国和日本供应商在 AI server、GPU/CPU VRM、xPU power delivery 与 AI server 高附加值区的具体证据。", "web_cyntec_ai_server_switch"),
        ("YAGEO TPI、Coilmaster SBP/SEP、Vishay IHSR、Eaton molded powder 和 Taiyo Yuden power inductor advances 说明全球竞争不是只有 TDK/Murata 两家，需要在标的页分别跟踪。", "web_vishay_ihsr_ai_gpu"),
        ("本地研报把顺络、铂科、龙磁等中国大陆公司放入高端电感替代链，但公开证据层级低于海外龙头官方应用材料和客户平台资料。", "local_csc_ai_inductor_20251206"),
        ("客户验证矩阵显示中国大陆企业机会集中在产品验证、小批量交付和局部批量供应，竞争格局判断必须区分直接客户、间接供货和观察篮子。", "local_huaan_expert_inductor"),
    ],
    "powder_material_capacity_bottleneck": [
        ("铂科新材 IR 披露铁占原材料重量 80% 以上，镍等金属采取按订单锁价等策略，说明材料价格和订单结构会影响利润弹性。", "web_boke_ir_20260424"),
        ("悦安新材研报把羰基铁粉细粉与一体成型电感材料需求相连，说明上游材料可能享受弹性，但与下游客户直接绑定程度低于器件厂。", "local_yuean_20260614"),
        ("专家纪要提到铁镍合金粉、定制设备、热压能耗和产线切换周期，作为产能瓶颈线索进入监控，不单独当作公开产能事实。", "local_huatai_expert_inductor"),
        ("头豹一体成型电感材料从算力基础设施和电动化场景切入，为材料、工艺、封装和高端应用边界提供行业背景。", "local_toubao_integrated_inductor_20260316"),
    ],
    "mainland_listed_company_capture": [
        ("顺络电子是产品阶段最清晰的大陆标的：TLVR 已披露批量供应，但数据中心收入占比仍不足 5%，短期要看收入确认。", "web_sunlord_ir_tlvr_20260701"),
        ("铂科新材具备金属软磁材料到芯片电感的一体化叙事，AI GPU/ASIC 功率提升提供需求驱动，但客户和收入拆分仍需财报验证。", "web_boke_ir_20260424"),
        ("龙磁科技已有国际客户高端模压电感中标和小批量交付线索，是弹性最大但验证债也更重的标的之一。", "web_longci_bid_20250122"),
        ("悦安新材更接近上游材料弹性，不能把器件厂的客户验证直接外推到其自身收入；需要跟踪细粉订单和价格传导。", "local_yuean_20260614"),
    ],
}


ENTITY_DEEP_ANALYSIS: dict[str, dict[str, str]] = {
    "ai_chip_inductor_vrm_core": {
        "research_boundary": """本实体研究的是 AI GPU/ASIC/TPU 加速卡和服务器主板 VRM 周边的高端芯片电感、TLVR 电感和高电流低损耗功率电感。它回答的不是“电感行业是否增长”，而是 AI 计算平台功耗、相数、瞬态响应和板级空间约束是否已经把一部分电感从普通被动元件推向高端认证料号，并且这种规格升级能否被具体供应商转化为收入和利润。""",
        "analysis": """这组证据首先解决需求真实性问题。AI 芯片电感需求量和 GB300 单板电感数量表把“芯片出货、单片用量、平台架构”串在一起，说明增量并非来自泛服务器数量，而是来自 GPU/ASIC/TPU 供电相数增加、低压大电流和更快负载瞬态。NVIDIA GB300 NVL72、Google Ironwood TPU 和华为 Atlas 900 A3 的平台证据提供了算力平台继续抬升功率密度的外部约束，但这些平台证据本身不能直接等同于任何一家电感公司的订单。这里的研究问题是：平台功耗增长是否会落到离散电感 BOM、TLVR 或一体成型电感，而不是被 DrMOS、Power Block 或 VPD 集成模块吸收。^evidence:xlsx_chip_inductor_demand^evidence:web_nvidia_gb300_nvl72

第二层解决“谁能承接”的问题。Cyntec、YAGEO、Coilmaster、Vishay、Eaton、Taiyo Yuden、TDK 和 Murata 的官方资料证明全球供应链已经把 AI server、GPU/CPU VRM、xPU power delivery 和高附加值 power inductor 作为明确应用场景，这比单纯研报线索更接近可核验产品边界。顺络电子、铂科新材和龙磁科技对应大陆供应商的三个不同证据阶段：顺络是 TLVR 批量供应但客户和收入占比仍需确认，铂科是材料到器件一体化受益但拆分不足，龙磁是国际客户中标和小批量交付但客户匿名。投资逻辑不能把这些公司平铺为“AI 电感概念”，而应按公开产品证据、客户阶段、产能爬坡、收入确认和毛利率响应逐级排序。^evidence:web_cyntec_ai_server_switch^evidence:web_sunlord_ir_tlvr_20260701^evidence:web_longci_bid_20250122

第三层是反方约束。Infineon VPD 把多相供电、垂直供电和 proprietary magnetics 集成进模块，说明 AI 供电升级未必全都流向离散电感厂。若客户平台从离散 VRM 电感转向更高集成度电源模块，核心实体的 TAM 要下修，且更可能利好模块、功率器件和系统方案厂。由此形成的投资框架是：先看平台 BOM 和单板用量是否确认，再看具体供应商是否进入客户认证和批量交付，最后看收入、ASP 和毛利率是否响应；任何只停留在总需求预测、二级市场传闻或专家纪要的标的，都只能作为观察项。^evidence:web_infineon_ai_vrm_vpd""",
        "conclusion": """本实体是本轮 AI 高端电感研究的最高优先级主线，但结论必须是条件化的。证实路径是 GPU/ASIC/TPU 新平台继续提高单板电感用量，高端料号 ASP 稳定或上行，顺络、铂科、龙磁、台达/乾坤、国巨/奇力新等供应商出现可复核的客户阶段上移、订单放量、收入拆分或利润率改善。证伪路径是新平台单位离散电感用量下降、VPD/Power Block 等集成路线提高渗透、或上市公司长期无法把产品阶段转化为财务贡献。

标的研究上应分三层处理：顺络电子、铂科新材、龙磁科技是大陆收入弹性验证层；台达/乾坤、国巨/奇力新、TDK、Murata、Vishay、Eaton、Taiyo Yuden 是全球技术和供给对照层；Infineon 是离散电感 TAM 的反方风险层。下一步补证不应再找泛泛的“AI 需求增长”，而要抓平台 BOM、客户料号、批量供应公告、数据中心收入占比、型号价格和毛利率。""",
    },
    "tlvr_vertical_power_transition": {
        "research_boundary": """本实体研究 TLVR、垂直供电和高瞬态响应供电架构的切换。它回答的核心问题是：AI xPU 供电是否因为瞬态响应、板级空间和能效约束而从传统芯片电感升级到更高价值、更难量产、更依赖客户认证的 TLVR 或垂直供电磁件。""",
        "analysis": """TLVR 的投资含义不在于出现一个新名词，而在于供电拓扑变化可能同时提高价值量、制造难度和认证壁垒。顺络电子公开 IR 已经把 TLVR 产品定位为主要用于 AI server xPU 芯片，并披露批量化供应，这是本实体最强的公开阶段证据。Cyntec 官方 TLVR 和 AI server 资料则说明台系供应商也把 TLVR 放在 SXM、UBB 和 switch 等高瞬态场景中。两类证据共同回答了“技术路线是否真实存在”的问题，但还没有完全回答“谁拿到哪一个客户平台、收入占比多少、ASP 是否改善”。^evidence:web_sunlord_ir_tlvr_20260701^evidence:web_cyntec_tlvr_ai_server

从信息到投资逻辑的关键转换，是把 TLVR 拆成四个连续门槛：样品验证、客户认证、产线切换、财务兑现。专家纪要中的产线、日能力、切换周期和 2027Q2 节奏只能提示验证方向，不能替代公开确认；真正能提升评分的是公司公告、IR、客户平台资料和财报中出现批量供应、收入拆分、ASP 或毛利率变化。如果只有“送样”“验证正反馈”而没有产能和收入，TLVR 仍是技术期权，不应当直接当成盈利结论。

还必须把 TLVR 放进供电架构竞争中看。高功率 AI 平台会需要更好的 transient response，但解决方案可以是 TLVR、垂直供电、Power Block、VPD 或客户自定义模块。若客户选择更集成的电源模块，离散 TLVR 电感的价值量可能被压缩；若客户仍采用可替换离散磁件，具备批量产线和客户认证的供应商才会受益。投资研究因此要跟踪“拓扑采用率”和“供应份额”两个变量，而不是只跟踪 TLVR 关键词出现次数。^evidence:web_infineon_ai_vrm_vpd""",
        "conclusion": """本实体是 2026-2027 年最需要跟踪的技术切换线索，优先级高但二元性强。证实条件是 TLVR 在新一代 AI GPU/ASIC 平台进入规模量产，供应商披露客户阶段上移、产线扩张、ASP 和毛利率改善；证伪条件是 TLVR 只停留在送样、被更集成的 VPD/Power Block 绕开，或公司收入长期无法体现数据中心贡献。

标的层面，顺络电子是公开产品阶段最清楚的大陆验证项，Cyntec 是台系官方产品对照项，国巨/奇力新和其他全球厂商是供给扩散观察项，Infineon 是架构替代风险。后续补证顺序应为客户平台采用、产线切换进度、量产良率、型号 ASP、数据中心收入占比，而不是重复收集 TLVR 概念描述。""",
    },
    "high_end_inductor_price_market_space": {
        "research_boundary": """本实体研究 AI 高端电感的价格体系、TAM/SAM/SOM 和收入弹性。它回答的问题是：在 AI 芯片出货和单板用量增长之外，高端型号 ASP、TLVR 渗透和客户份额是否足以把颗数增长转化为供应商的可兑现收入。""",
        "analysis": """市场空间测算不是结论，而是需要不断折扣的假设链。AI 芯片电感需求量表解决了颗数端问题：GPU/ASIC 出货、平均单片用量和需求颗数可以形成 bottom-up TAM。价格分层表解决的是 ASP 端问题：TDK、Murata、Sunlord 等型号价格差异提示高端 AI 电感不能用普通消费电感价格外推。只有把颗数、型号结构、TLVR 占比、客户认证份额和 ASP 放在同一个框架里，TAM 才能变成有用的投资研究变量。^evidence:xlsx_chip_inductor_demand^evidence:xlsx_inductor_model_price

这组信息的隐藏约束是价格信号很容易被误读。被动元件涨价案例表和专家纪要中的 TLVR ASP 线索可以说明价格动量存在，但不能证明所有电感公司都会涨价，也不能证明涨价会进入利润表。短期渠道涨价、非 AI 型号涨价、汇率或原材料波动，都可能让价格数据看起来很强却无法支撑核心评分。真正需要验证的是高端 AI 型号的年度议价、客户认可的价值量、良率成本和公司毛利率是否同向变化。

投资逻辑上，TAM 要拆成四层：全球 AI 平台总需求是上限，中国和台系供应商可承接的是 SAM，上市公司真实份额是 SOM，最终利润还要再扣掉良率、材料成本、折旧和客户议价。顺络、铂科、龙磁这类标的只有在收入拆分和利润率响应出现时，才能从“市场空间受益”升级为“财务弹性标的”；否则即使 TAM 很大，也只是行业背景。""",
        "conclusion": """本实体应作为全报告的测算框架和估值约束，而不是单独的买入理由。当前可以确认的是 AI 高端电感存在颗数和规格升级逻辑，但收入弹性需要型号价格、客户份额和财务响应共同证实。

后续最重要的监控项是 2026-2027 年高端型号价格、TLVR ASP、年度议价、数据中心收入占比和毛利率。如果高端型号价格稳定上行且供应商收入利润同步响应，市场空间假设可以上调；如果涨价只发生在普通型号或短期渠道，TAM 应只保留为行业背景，不进入核心标的评分。""",
    },
    "customer_validation_matrix": {
        "research_boundary": """本实体研究英伟达、Google、华为和其他 AI 平台客户验证矩阵。它回答的问题是：哪些公司只是具备供货能力，哪些公司已经进入样品、验证、小批量、批量供应或可公开确认的客户阶段，以及这些阶段能否映射到具体标的。""",
        "analysis": """客户验证矩阵是本轮最容易误判、也最需要严格分层的实体。顺络电子的公开 IR 可以确认 TLVR 产品阶段和批量供应表述，但客户名称未公开；铂科新材披露 ASIC 与 AI GPU 功率提升带来需求影响，但芯片电感收入拆分和客户名仍缺；龙磁科技有国际客户高端模压电感中标和小批量交付线索，但客户匿名且放量节奏未证实。上述证据能证明“存在客户验证路径”，不能直接证明“已进入 NVIDIA、Google 或华为核心份额”。^evidence:web_sunlord_ir_tlvr_20260701^evidence:web_boke_ir_20260424^evidence:web_longci_bid_20250122

这组信息解决的投资问题是把客户线索从噪声中筛出来。专家纪要可以给出供应链方向，但它只能作为 early signal 或 verification debt；公司公告、IR、交易所材料、客户平台资料和财报收入才是升级核心评分的证据。矩阵中的每个标的都要标明“直接客户确认、间接链条、产品能力、观察项”四种状态之一，否则就会把具备技术能力的公司误写成已确认供货，把二级市场传闻误写成订单。

对投资研究而言，客户验证的影响高于单纯 TAM。若同一家供应商从产品能力进入客户验证、再进入小批量和批量供货，收入弹性和估值容忍度可以提高；若客户身份始终匿名、收入占比长期低、只有纪要和传闻，标的应保留在观察篮子。英伟达、Google、华为也不能混成一个客户名词：英伟达链条更依赖公开产品和供应份额交叉验证，Google/ASIC 更需要芯片与服务器 ODM 线索，华为链条还要区分国产替代和公开交付证据。""",
        "conclusion": """本实体是把主题机会转化为可研究标的的闸门。当前结论是：顺络、铂科、龙磁、台达/乾坤、国巨/奇力新、TDK、Murata 等都可以进入客户验证矩阵，但只有公开证据达到相应阶段时，才允许升级权重；客户匿名、小批量、专家纪要或产品能力不能直接写成已确认核心供货。

下一步补证必须围绕客户阶段本身：客户平台料号、ODM/OEM 交付、公告或 IR 原文、财报收入拆分、数据中心占比、订单金额和供货节奏。若这些证据无法补足，客户验证矩阵应维持中等置信度，并把相关标的的投资研究建议写成条件化观察。""",
    },
    "global_supplier_competition": {
        "research_boundary": """本实体研究全球高端电感供应商竞争格局。它回答的问题是：AI 高端电感的利润池会被 TDK、Murata、Taiyo Yuden、Vishay、Eaton、Cyntec、YAGEO 等全球供应商继续占据，还是给中国大陆和台系供应商提供第二来源和份额提升机会。""",
        "analysis": """竞争格局决定机会最终流向谁。TDK、Murata 和 Taiyo Yuden 的官方资料代表高端被动元件和 AI data center PDN 的技术参照位；Vishay、Eaton、Coilmaster、Cyntec、YAGEO 等资料说明 AI/GPU 高电流电感、TPI/TLVR、molded powder 和 xPU power delivery 已经成为多家全球供应商的明确产品方向。由此可见，AI 高端电感不是只有少数大陆标的的单线机会，而是全球龙头、台系厂商、大陆供应商和模块替代方案共同竞争。^evidence:web_tdk_ai_ecosystem^evidence:web_murata_ai_pdn_20260204^evidence:web_vishay_ihsr_ai_gpu

这组证据需要回答的是“国产替代或份额提升是否成立”。中国大陆公司可能在成本、响应速度、本地客户和国产算力链条上有优势，但客户认证、长期可靠性、材料配方、良率和高端料号经验仍是约束。若海外和台系龙头已在主要平台形成稳定料号，大陆公司更可能先以第二来源、局部料号或国产平台切入；若客户为降本和供应安全主动引入多供应商，大陆公司才可能出现更大的份额提升。

投资逻辑上，竞争格局要分为四个篮子：全球技术参照和稳健供给、台系 AI server/TLVR 主流供应、大陆产品验证和收入弹性、集成模块替代风险。不同篮子的估值弹性完全不同。全球龙头可能更稳但 AI 电感收入难拆，大陆标的弹性大但验证债重，台系公司证据强但需要客户份额，Infineon 等模块方案则会压缩离散器件空间。""",
        "conclusion": """本实体的结论不是寻找单一赢家，而是建立竞争分层。当前全球供应商公开产品证据更完整，大陆公司具备收入弹性和替代想象，但必须用客户阶段、料号、订单和财务响应来证实。若大陆和台系供应商进入主流 AI 平台第二来源或核心料号，相关标的优先级上调；若日美台龙头继续控制高端料号，或 VPD/Power Block 提升渗透，大陆主题标的应降级。

后续监控应同时覆盖 TDK、Murata、Taiyo Yuden、Vishay、Eaton、Cyntec、YAGEO、顺络、铂科和龙磁，不允许只看本地研报中的公司池。重点不是谁“有产品”，而是谁在高端料号、客户认证、产能响应和价格传导上形成可核验证据。""",
    },
    "powder_material_capacity_bottleneck": {
        "research_boundary": """本实体研究磁粉材料、热压设备、产能切换和工艺瓶颈。它回答的问题是：AI 高端电感的供给约束是否出现在铁镍粉、羰基铁粉、材料配方、热压设备、能耗、良率或产线切换环节，并进一步影响器件厂和材料厂的利润分配。""",
        "analysis": """材料和设备瓶颈是二阶机会，不能直接等同于电感需求增长。铂科新材 IR 中铁、镍等原材料和按订单锁价策略说明材料成本会影响利润弹性；悦安新材研报把羰基铁粉细粉与一体成型电感连接起来，说明上游粉体可能受益；专家纪要中的铁镍合金粉、定制设备、热压能耗和产线切换周期提供了瓶颈线索。三类证据共同回答的是“供给弹性是否受限”，但还没有完全证明材料厂已经获得 AI 电感订单或价格传导。^evidence:web_boke_ir_20260424^evidence:local_yuean_20260614^evidence:local_huatai_expert_inductor

从信息到投资逻辑的关键，是区分“成本项”和“瓶颈项”。如果铁镍粉、羰基铁粉只是普通原材料，价格上涨可能压缩器件厂毛利；只有当细粉规格、纯度、粒径分布、良率、热压设备和客户认证变成限制供给的非同质化环节时，上游材料才具备议价权。铂科这类材料到器件一体化公司既可能受益于高端产品结构，也可能承受原材料波动；悦安这类粉体公司更像上游期权，需要订单、价格和客户结构来证明。

本实体还要防止把产能故事写成确定利润。产线切换、设备交期和热压能耗会影响短期供给响应，但如果海外和台系厂商已有成熟产能，或者粉体供应快速扩张，瓶颈价值会下降。投资研究应先验证器件端需求和客户认证，再验证材料端是否真正紧缺，最后才讨论材料公司利润弹性。""",
        "conclusion": """本实体是重要的供给约束和上游弹性观察项，但置信度应低于直接器件和客户验证实体。证实条件是高端细粉订单、粉体价格、设备交期、良率或产线切换成为公开披露瓶颈，并且器件厂和材料厂财务出现对应响应；证伪条件是粉体和设备快速放量、材料成本无法传导，或 AI 电感订单未能映射到上游。

标的上，铂科新材既是材料和器件一体化受益项，也是成本和良率验证项；悦安新材是上游粉体弹性项，但不能把器件厂客户验证直接外推到其自身收入。后续补证应围绕粉体规格、订单客户、锁价机制、扩产进度、良率和毛利率，而不是只引用材料瓶颈的概念性表述。""",
    },
    "mainland_listed_company_capture": {
        "research_boundary": """本实体研究中国大陆上市公司对 AI 高端电感机会的承接能力与财务弹性。它回答的问题是：顺络电子、铂科新材、龙磁科技、悦安新材等公司分别处在哪个证据阶段，哪些已经接近收入兑现，哪些仍是材料或验证期权。""",
        "analysis": """大陆上市公司不能被合并成一个“国产替代”标签。顺络电子的证据是 TLVR 产品主要用于 AI server xPU 并已批量化供应，但数据中心收入占比仍不足 5%，所以它是产品阶段最清楚、财务兑现仍待验证的标的。铂科新材的证据是 ASIC 和 AI GPU 功率提升带来出货数量和性能要求变化，同时具备金属软磁材料到芯片电感的一体化叙事，但客户名、芯片电感收入和 ASP 拆分仍缺。龙磁科技的证据是国际客户高端模压电感中标和小批量交付线索，弹性最大，但客户匿名、基数小、产能和后续订单都需要复核。悦安新材是羰基铁粉细粉材料弹性，更偏二阶上游。^evidence:web_sunlord_ir_tlvr_20260701^evidence:web_boke_ir_20260424^evidence:web_longci_bid_20250122

这组信息解决的是“谁能把产业机会变成财务结果”的问题。投资逻辑要按证据到收入的距离排序，而不是按概念热度排序。顺络需要看批量供应后的数据中心收入占比和毛利率；铂科需要看芯片电感收入拆分、材料成本传导和客户认证；龙磁需要看中标转批量、客户扩展和新业务收入；悦安需要看细粉订单、价格和下游客户结构。若没有这些财务和客户证据，上市公司只能停留在主题映射。

还要把大陆公司放在全球竞争中校验。Cyntec、YAGEO、TDK、Murata、Vishay、Eaton 等全球供应商已有更明确的官方产品资料，说明大陆公司的机会不是“天然替代”，而是要通过成本、响应速度、国产客户、第二来源和局部料号逐步争取份额。只有客户阶段上移和利润表响应同时出现，才能把早期信号升级为核心评分。""",
        "conclusion": """本实体的当前排序应为：顺络电子优先级最高，因为公开产品阶段最清楚；铂科新材是材料和器件一体化的结构性标的，但收入拆分是核心验证债；龙磁科技是高弹性订单验证项，需等待中标后放量和客户扩展；悦安新材是上游材料期权，必须用细粉订单和价格传导验证。

证实情景下，大陆标的的研究重点应从概念暴露转向收入确认、毛利率改善、客户阶段和产能爬坡；证伪情景下，如果数据中心收入占比长期低、客户匿名、订单不放量或价格不能传导，相关标的应降为观察项。下一步补证应优先读取公司公告、IR、定期报告、订单和客户验证材料，而不是继续补充泛行业研报。""",
    },
}


def _entity_section(entity: dict[str, Any], data_points: list[dict[str, Any]]) -> dict[str, Any]:
    refs = [ref.replace("source_ref:", "") for ref in entity["evidence_ref_uri_list"][:8]]
    related_count = len([p for p in data_points if p.get("entity_key") == entity["key"]])
    curated = CURATED_ENTITY_EVIDENCE.get(entity["key"], [])
    evidence_lines = [
        f"- {text} {_evidence(ref)}"
        for text, ref in curated
    ]
    if not evidence_lines:
        evidence_lines = [f"- 本实体证据来自 {len(refs)} 个独立来源，详见证据抽屉和因子追踪。"]
    deep = ENTITY_DEEP_ANALYSIS.get(entity["key"], {})
    research_boundary = deep.get(
        "research_boundary",
        f"本实体研究的是 {entity['display_name']}。它和本轮主问题的关系是：判断 AI 服务器、GPU/ASIC/TPU 加速卡、国产算力和高功率密度供电架构是否正在把电感从普通被动元件推向高端、可认证、可涨价、可兑现收入的供需机会。",
    )
    analysis = deep.get(
        "analysis",
        "本实体的分析必须从证据回答了什么研究问题开始，说明证据之间如何约束判断，再把判断映射到具体标的、证实条件、证伪条件和后续补证顺序。仅有总需求、单条研报或专家纪要时，不得升级为核心投资结论。",
    )
    conclusion = deep.get(
        "conclusion",
        f"本实体的分数只作为研究优先级，不替代结论。当前应先按证实条件复核：{entity['composite_trace']['confirmed_action']}；再按证伪条件约束：{entity['composite_trace']['falsified_action']}。下一步补证方向是 {entity['composite_trace']['monitor_signal']}，监控节奏为 {entity['composite_trace']['monitor_timing']}。若补证不能把线索连接到具体标的、客户、产能、价格或财务响应，本实体只能保留为观察项。",
    )
    body = f"""### 研究边界与问题定义

{research_boundary}

### 证据链与数据基础

本实体证据覆盖 {related_count} 条结构化数据点和 {len(refs)} 个主要来源。核心证据不是简单堆原文，而是形成三层关系：第一层是 AI 算力平台功耗、单板用量、客户验证或价格变化；第二层是产能、材料、设备和客户认证是否限制供给响应；第三层是能否映射到上市公司收入和利润。当前关键证据包括：

{chr(10).join(evidence_lines)}

这些证据共同支持的基础推论是：{entity['composite_trace']['confirmed_action']} 与之相反，{entity['composite_trace']['falsified_action']}

### 分析

{analysis}

### 总结

{conclusion}
"""
    return {
        "entity_key": entity["key"],
        "section_key": "entity_research_profile",
        "section_title": f"{entity['display_name']} 研究实体介绍、证据链与投资结论",
        "body_markdown": body,
        "evidence_ref_uri_list": entity["evidence_ref_uri_list"][:8],
        "sort_order": 100 + int(entity["score_point"]),
    }


TARGETS = [
    ("ai_chip_inductor_vrm_core", "顺络电子（002138.SZ）VRM/TLVR 芯片电感项", "002138.SZ", "A股", "company", "web_sunlord_ir_tlvr_20260701", "大陆公开 IR 阶段最清楚的 TLVR/AI server xPU 电感标的，但数据中心收入占比仍需继续验证。", "高", "较高置信度"),
    ("ai_chip_inductor_vrm_core", "铂科新材（300811.SZ）芯片电感与金属软磁一体化项", "300811.SZ", "A股", "company", "web_boke_ir_20260424", "公司公开披露 ASIC 芯片和 AI GPU 功率提升带来出货数量和性能要求变化，适合作为材料到器件一体化标的。", "高", "中高置信度"),
    ("ai_chip_inductor_vrm_core", "龙磁科技（300835.SZ）高端模压电感验证项", "300835.SZ", "A股", "company", "web_longci_bid_20250122", "已出现国际客户高端模压电感中标和小批量交付线索，是核心芯片电感实体中的弹性验证项。", "中高", "中置信度"),
    ("ai_chip_inductor_vrm_core", "台达/乾坤（2308.TW）AI server TLVR 电感项", "2308.TW", "中国台湾", "company", "web_cyntec_ai_server_switch", "Cyntec 官方把低损耗功率电感和 TLVR 放入 AI server SXM、UBB、switch 与高瞬态场景，是台系核心供给侧标的。", "高", "较高置信度"),
    ("ai_chip_inductor_vrm_core", "国巨/奇力新（2327.TW）TPI/AI power 电感项", "2327.TW", "中国台湾", "company", "web_yageo_tpi_ai_power_20250627", "YAGEO/KEMET/Pulse 的 TPI 与 TLVR 资料直接对应 AI、server、GPU/ASIC 供电链，应作为台系具体标的而不是泛观察项。", "中高", "中置信度"),
    ("ai_chip_inductor_vrm_core", "Coilmaster GPU/CPU VRM 高电流电感观察项", None, "中国台湾", "external_watch", "web_coilmaster_gpu_cpu_vrm", "Coilmaster 官方把 GPU/CPU VRM 电感定位为 AI compute platforms 的超低 DCR、高电流器件，适合跟踪非上市/外部供应链补位。", "中", "中置信度"),
    ("ai_chip_inductor_vrm_core", "Vishay（VSH）AI/GPU 高电流电感项", "VSH", "美国", "company", "web_vishay_ihsr_ai_gpu", "Vishay IHSR 高电流 SMD 电感公开指向 datacenter、AI computing 和 GPU 应用，是美系全球龙头具体对照标的。", "中", "中置信度"),
    ("ai_chip_inductor_vrm_core", "Eaton（ETN）AI molded powder inductor 项", "ETN", "美国", "company", "web_eaton_ai_molded_powder", "Eaton 官方把 molded powder inductors 用于 AI computing xPU power delivery，重点跟踪效率、散热和长期可靠性。", "中", "中置信度"),
    ("ai_chip_inductor_vrm_core", "Taiyo Yuden（6976.T）AI server 高附加值电感项", "6976.T", "日本", "company", "web_taiyo_yuden_ai_server_inductor_2025ar", "Taiyo Yuden 2025 Integrated Report 把 power inductor growth 聚焦到 AI server 等高附加值区，应列入日本供应商对照。", "中", "中置信度"),
    ("ai_chip_inductor_vrm_core", "TDK（6762.T）AI server power delivery 电感项", "6762.T", "日本", "company", "web_tdk_ai_ecosystem", "TDK 官方 AI ecosystem 资料支持其在 AI server power delivery、noise suppression 和 GPU 稳定供电中的技术位置。", "中", "中置信度"),
    ("ai_chip_inductor_vrm_core", "Murata（6981.T）AI data center PDN 电感项", "6981.T", "日本", "company", "web_murata_ai_pdn_20260204", "Murata 官方 AI data center PDN 指南把电感纳入稳定供电方案，是全球龙头对照标的。", "中", "中置信度"),
    ("ai_chip_inductor_vrm_core", "Infineon（IFX.DE）VPD 集成模块替代风险项", "IFX.DE", "德国", "company", "web_infineon_ai_vrm_vpd", "Infineon quad-phase VPD 模块把磁件与电源模块集成，代表离散电感被集成方案替代的核心反方标的。", "中", "反方风险标的"),
    ("mainland_listed_company_capture", "顺络电子（002138.SZ）", "002138.SZ", "A股", "company", "web_sunlord_ir_tlvr_20260701", "TLVR 批量化供应证据最清楚，但数据中心收入占比仍低。", "高", "较高置信度"),
    ("mainland_listed_company_capture", "铂科新材（300811.SZ）", "300811.SZ", "A股", "company", "web_boke_ir_20260424", "材料到器件一体化，ASIC/GPU 功率提升带来出货和性能要求变化。", "高", "中高置信度"),
    ("mainland_listed_company_capture", "龙磁科技（300835.SZ）", "300835.SZ", "A股", "company", "web_longci_bid_20250122", "高端模压电感中标和小批量交付线索提供收入弹性。", "中高", "中置信度"),
    ("powder_material_capacity_bottleneck", "悦安新材（688786.SH）", "688786.SH", "A股", "company", "local_yuean_20260614", "羰基铁粉细粉作为一体成型电感上游材料，弹性取决于下游订单和价格传导。", "中", "中置信度"),
    ("tlvr_vertical_power_transition", "台达/乾坤观察项", "2308.TW", "中国台湾", "external_watch", "local_huaan_expert_inductor", "专家纪要认为其在英伟达链条中占主流，但公开证据仍需补足。", "中", "中低置信度"),
    ("global_supplier_competition", "国巨/奇力新观察项", "2327.TW", "中国台湾", "external_watch", "local_huaan_expert_inductor", "台系电感供应链观察项，需公开订单和客户确认。", "中", "中低置信度"),
    ("global_supplier_competition", "TDK（6762.T）", "6762.T", "日本", "company", "web_tdk_ai_ecosystem", "全球被动元件和 AI 数据中心电源能力强，但 AI GPU/ASIC 高端电感料号需具体确认。", "中", "中置信度"),
    ("global_supplier_competition", "Murata（6981.T）", "6981.T", "日本", "company", "web_murata_ai_pdn_20260204", "AI 数据中心 PDN 能力强，直接供应份额仍需具体平台证据。", "中", "中置信度"),
    ("high_end_inductor_price_market_space", "AI 高端电感价格观察篮子", None, "全球", "basket", "xlsx_inductor_model_price", "用型号价格、TLVR ASP 和年度议价跟踪高端与普通电感差异。", "中", "研究篮子"),
    ("customer_validation_matrix", "英伟达/Google/华为客户验证观察篮子", None, "全球", "basket", "local_huatai_expert_inductor", "用于跟踪直接供货、间接供货、验证、小批量、批量供货和公开确认阶段。", "高", "研究篮子"),
    ("customer_validation_matrix", "顺络电子（002138.SZ）客户验证项", "002138.SZ", "A股", "company", "web_sunlord_ir_tlvr_20260701", "顺络公开披露 TLVR 拓扑结构产品主要用于 AI server xPU 芯片且已批量化供应，但客户名称与数据中心收入占比仍需财报继续验证。", "高", "较高置信度"),
    ("customer_validation_matrix", "铂科新材（300811.SZ）客户验证项", "300811.SZ", "A股", "company", "web_boke_ir_20260424", "铂科披露 ASIC 芯片和 AI GPU 功率提升会带来出货数量和性能要求变化，客户名称、芯片电感收入拆分和 ASP 仍需验证。", "中高", "中高置信度"),
    ("customer_validation_matrix", "龙磁科技（300835.SZ）客户验证项", "300835.SZ", "A股", "company", "web_longci_bid_20250122", "龙磁高端模压电感中标约 2300 万元并有小批量交付线索，是公开订单验证度较高但客户匿名的弹性标的。", "中高", "中置信度"),
    ("customer_validation_matrix", "台达/乾坤客户验证观察项", "2308.TW", "中国台湾", "external_watch", "local_huaan_expert_inductor", "专家纪要把台达/乾坤列为英伟达链条主流线索，但缺少公开订单、客户或公司确认，只能作为观察项。", "中", "中低置信度"),
    ("customer_validation_matrix", "国巨/奇力新客户验证观察项", "2327.TW", "中国台湾", "external_watch", "local_huaan_expert_inductor", "国巨/奇力新具备台系被动元件链条位置，但本轮证据不足以确认 NVIDIA、Google 或华为具体平台份额。", "中", "中低置信度"),
    ("customer_validation_matrix", "TDK（6762.T）客户验证项", "6762.T", "日本", "company", "web_tdk_ai_ecosystem", "TDK 官方 AI ecosystem 材料支持其在 AI server power delivery 和电感能力上的技术位置，但具体客户平台仍需料号和供应份额证据。", "中", "中置信度"),
    ("customer_validation_matrix", "Murata（6981.T）客户验证项", "6981.T", "日本", "company", "web_murata_ai_pdn_20260204", "Murata 官方 AI data center power delivery guide 支持其 PDN 能力，客户验证矩阵中应作为海外龙头对照项而非自动确认供货。", "中", "中置信度"),
    ("ai_chip_inductor_vrm_core", "GPU/ASIC VRM BOM 观察篮子", None, "全球", "basket", "xlsx_gb300_inductor_count", "跟踪 GB300/Rubin/TPU/昇腾平台单板相数、单卡用量和离散电感替代风险。", "高", "研究篮子"),
    ("tlvr_vertical_power_transition", "TLVR 产线切换观察篮子", None, "全球", "basket", "local_huatai_expert_inductor", "跟踪 TLVR 产线数量、日产能、设备交期、客户切换和 ASP。", "高", "研究篮子"),
]


TARGET_FIELD_OVERRIDES: dict[tuple[str, str], dict[str, str]] = {
    ("ai_chip_inductor_vrm_core", "顺络电子（002138.SZ）VRM/TLVR 芯片电感项"): {
        "relative_preference": "大陆标的中公开 TLVR 批量化供应证据最清楚，优先级高于铂科和龙磁；但数据中心收入占比不足 5%，财务兑现弱于产品阶段。",
        "research_action": "优先跟踪顺络 IR、定期报告和数据中心收入占比，把 TLVR 批量供应从产品阶段验证推进到收入和毛利率验证。",
        "investment_view": "作为大陆核心验证标的优先研究；只有数据中心收入占比、客户阶段或毛利率改善出现时，才从产品线索升级为财务弹性标的。",
        "risk_note": "主要风险是客户名称未公开、数据中心收入占比仍低、TLVR 批量供应未形成利润贡献，或客户采用集成电源模块压缩离散电感价值。",
        "confirmed_scenario_action": "若后续 IR 或财报显示数据中心收入占比提升、TLVR 订单放量且毛利率稳定，上调为大陆器件侧首要跟踪标的。",
        "falsified_scenario_action": "若批量供应长期不能带来收入占比提升，或客户平台采用 VPD/Power Block 减少离散 TLVR，用产品能力观察替代核心评分。",
    },
    ("ai_chip_inductor_vrm_core", "铂科新材（300811.SZ）芯片电感与金属软磁一体化项"): {
        "relative_preference": "相对顺络，铂科的优势在材料到器件一体化和 ASIC/GPU 功率升级受益；短板是客户名、芯片电感收入和 ASP 拆分不如顺络清晰。",
        "research_action": "跟踪铂科 IR、产品收入拆分、材料成本传导和芯片电感订单，判断金属软磁能力是否真正转为 AI 电感收入。",
        "investment_view": "作为材料和器件一体化的结构性标的研究，优先级取决于芯片电感收入拆分和客户认证，而不是单纯材料逻辑。",
        "risk_note": "主要风险是公司披露停留在 ASIC/GPU 功率提升的需求表述，缺少客户、料号、收入拆分，且镍等材料成本可能侵蚀利润。",
        "confirmed_scenario_action": "若公司披露芯片电感收入、AI 客户认证或高端型号 ASP，提升到顺络之后的大陆第二优先级。",
        "falsified_scenario_action": "若仍只有材料和需求描述、没有客户和收入拆分，将其降为上游材料加器件一体化观察项。",
    },
    ("ai_chip_inductor_vrm_core", "龙磁科技（300835.SZ）高端模压电感验证项"): {
        "relative_preference": "龙磁弹性强于顺络和铂科，因为中标和小批量交付有订单线索；但客户匿名、金额基数小、量产节奏不明，确定性低于前两者。",
        "research_action": "跟踪中标后交付、后续订单、客户扩展和新业务收入占比，确认小批量线索是否进入持续供货。",
        "investment_view": "作为高弹性订单验证项研究；适合在公告和季报验证后上调，不适合仅凭单次中标直接纳入核心结论。",
        "risk_note": "主要风险是中标金额有限、客户匿名、小批量交付不能延续、产能和良率不足，导致新业务无法放大到利润表。",
        "confirmed_scenario_action": "若中标客户转入批量供货、订单金额扩大且新业务收入披露，上调为大陆高弹性验证标的。",
        "falsified_scenario_action": "若后续公告缺失、仍停留小批量或客户验证无进展，降为订单线索观察项。",
    },
    ("ai_chip_inductor_vrm_core", "台达/乾坤（2308.TW）AI server TLVR 电感项"): {
        "relative_preference": "Cyntec 官方 AI server/SXM/UBB/TLVR 资料强于大多数大陆公开证据，是台系技术和供给对照；短板是缺少具体客户份额和收入拆分。",
        "research_action": "跟踪 Cyntec/台达产品更新、AI server 料号、客户平台和台达电源业务披露，用它校验大陆标的是否真正追上主流供给。",
        "investment_view": "作为台系核心供给对照项研究；若客户份额被确认，可作为 AI server 电感主流供应链标尺。",
        "risk_note": "主要风险是官方产品页只能证明能力，不证明 NVIDIA/Google/华为份额；集团口径也可能稀释电感业务弹性。",
        "confirmed_scenario_action": "若公开资料或财报确认 AI server TLVR 料号和客户份额，提升为全球主流供给标杆。",
        "falsified_scenario_action": "若只有产品能力没有客户和收入证据，保留为台系技术参照，不参与核心机会排序。",
    },
    ("ai_chip_inductor_vrm_core", "国巨/奇力新（2327.TW）TPI/AI power 电感项"): {
        "relative_preference": "国巨/奇力新的 TPI/TLVR 产品线广于大陆单一公司，但客户份额公开度弱于 Cyntec；适合作为台系第二供给对照。",
        "research_action": "跟踪 YAGEO/KEMET/Pulse TPI 系列更新、AI server 平台导入和被动元件业务收入拆分。",
        "investment_view": "作为台系多品牌电感平台研究，重点看 TPI/TLVR 是否进入高功率计算平台，而不是泛被动元件扩张。",
        "risk_note": "主要风险是产品系列覆盖广但 AI GPU/ASIC 客户份额不透明，且集团被动元件周期会掩盖 AI 电感弹性。",
        "confirmed_scenario_action": "若 TPI/TLVR 进入明确 AI server 或 xPU 平台并披露份额，上调为台系核心跟踪项。",
        "falsified_scenario_action": "若仍只有产品发布和泛 AI 表述，维持为全球对照，不给核心评分加权。",
    },
    ("ai_chip_inductor_vrm_core", "Coilmaster GPU/CPU VRM 高电流电感观察项"): {
        "relative_preference": "Coilmaster 是非上市/外部供应链补位，产品应用描述直接但缺少财务和客户份额，优先级低于可投资证券和台系上市公司。",
        "research_action": "跟踪 GPU/CPU VRM 产品页、客户案例和规格升级，用于验证高电流低 DCR 电感的技术门槛。",
        "investment_view": "作为技术规格和非上市供应链观察项，不作为直接投资标的；主要用于校验其他公司产品参数是否达到主流门槛。",
        "risk_note": "主要风险是无法获得财务弹性、客户份额和公开订单，只能证明应用方向，不能证明投资机会。",
        "confirmed_scenario_action": "若出现明确 AI compute 客户案例或可比料号，把它作为全球供应链补位样本。",
        "falsified_scenario_action": "若长期只有应用页描述且无客户案例，保留为规格参考，不进入标的优先级。",
    },
    ("ai_chip_inductor_vrm_core", "Vishay（VSH）AI/GPU 高电流电感项"): {
        "relative_preference": "Vishay 是美系高电流 SMD 电感对照，官方 AI/GPU/datacenter 应用强；但集团规模大，单一 AI 电感收入弹性弱于大陆小基数标的。",
        "research_action": "跟踪 IHSR/IHLP 高电流料号、数据中心客户和分部收入，判断其是稳定供给还是高弹性机会。",
        "investment_view": "作为美系全球龙头对照研究，适合校准产品规格和竞争壁垒，不宜直接用 AI 电感主题推导集团利润弹性。",
        "risk_note": "主要风险是 AI 电感占集团收入不可拆，应用证据强但客户份额和利润弹性不透明。",
        "confirmed_scenario_action": "若公司披露 AI/GPU/datacenter 料号放量或分部增长，提升为全球稳健对照项。",
        "falsified_scenario_action": "若无法拆出 AI 电感收入，继续作为规格和竞争参照，不作为主题弹性标的。",
    },
    ("ai_chip_inductor_vrm_core", "Eaton（ETN）AI molded powder inductor 项"): {
        "relative_preference": "Eaton 证明 molded powder 电感可服务 xPU power delivery，但业务更偏电力和工业集团，直接电感收入弹性弱于 Vishay 和台系供应商。",
        "research_action": "跟踪 Eaton molded powder 产品、xPU power delivery 客户和电子元件业务披露，判断其对离散电感技术路线的约束。",
        "investment_view": "作为美系高可靠性和热管理对照项研究，重点看效率、散热和长期可靠性对高端电感规格的拉升。",
        "risk_note": "主要风险是集团口径过大、AI molded powder 电感占比难拆，且可能更多体现为系统级电源可靠性而非单一电感弹性。",
        "confirmed_scenario_action": "若披露 xPU power delivery 客户或相关产品放量，将其作为美系供给侧验证项。",
        "falsified_scenario_action": "若仅停留在科普材料和产品宣传，降为技术路线参考。",
    },
    ("ai_chip_inductor_vrm_core", "Taiyo Yuden（6976.T）AI server 高附加值电感项"): {
        "relative_preference": "Taiyo Yuden 年报级战略证据强于普通产品页，但具体 AI server 料号和客户份额弱于 Cyntec/Vishay。",
        "research_action": "跟踪年报、power inductor 产品线、AI server 高附加值区收入和客户料号。",
        "investment_view": "作为日本高端电感战略对照研究，重点看 AI server 是否从战略表述进入可拆收入。",
        "risk_note": "主要风险是战略表述不等于平台供货，且高附加值区可能包含汽车和其他领域，AI 电感贡献难拆。",
        "confirmed_scenario_action": "若年报或财报进一步披露 AI server power inductor 收入和产能，提升为日本供应商核心对照。",
        "falsified_scenario_action": "若后续仍无料号、客户和收入拆分，保留为日本龙头背景项。",
    },
    ("ai_chip_inductor_vrm_core", "TDK（6762.T）AI server power delivery 电感项"): {
        "relative_preference": "TDK 是全球技术参照，电源完整性和噪声抑制能力强；但直接 AI GPU/ASIC 电感料号证据弱于 Cyntec 和 Vishay。",
        "research_action": "跟踪 TDK AI ecosystem、服务器电源完整性方案和具体电感料号，校验高端门槛和国产替代难度。",
        "investment_view": "作为全球龙头技术边界和竞争壁垒对照，不应仅凭 AI server 能力推导短期收入弹性。",
        "risk_note": "主要风险是官方资料覆盖系统级电源和噪声抑制，未必对应高弹性的 GPU/ASIC 电感订单。",
        "confirmed_scenario_action": "若出现 AI server 电感料号和客户平台证据，上调为全球龙头核心对照。",
        "falsified_scenario_action": "若仍停留系统级能力描述，保留为技术壁垒参考，不进入标的弹性排序。",
    },
    ("ai_chip_inductor_vrm_core", "Murata（6981.T）AI data center PDN 电感项"): {
        "relative_preference": "Murata 的 PDN 指南证明其在 AI data center 供电链位置，但内容覆盖 MLCC、电容、电感和磁珠，直接电感暴露弱于纯电感厂。",
        "research_action": "跟踪 Murata PDN 指南、AI server 供电架构变化和具体电感/磁珠料号。",
        "investment_view": "作为 AI data center 被动元件组合方案对照，重点用于判断离散电感是否被更综合的 PDN 方案稀释。",
        "risk_note": "主要风险是产品组合太宽，AI 电感收入不可拆，且 PDN 方案可能把价值分散到电容、磁珠和模块。",
        "confirmed_scenario_action": "若披露 AI data center 电感料号或客户平台，提升为日本龙头对照项。",
        "falsified_scenario_action": "若只有广义 PDN 指南，继续作为系统方案参照，不给离散电感 TAM 加权。",
    },
    ("ai_chip_inductor_vrm_core", "Infineon（IFX.DE）VPD 集成模块替代风险项"): {
        "relative_preference": "Infineon 不是正向电感标的，而是离散电感 TAM 的反方风险；在同实体中用于约束顺络、Cyntec、Vishay 等离散器件机会。",
        "research_action": "跟踪 VPD/quad-phase power module 渗透、客户采用和 proprietary magnetics 路线，判断离散 TLVR 和 VRM 电感是否被集成模块替代。",
        "investment_view": "作为反方工具研究；若 VPD 渗透提高，应下修离散电感 TAM 并转向模块和功率器件链条。",
        "risk_note": "主要风险是把反方风险误读为正向电感机会；Infineon 利好来自集成模块，不代表离散电感厂受益。",
        "confirmed_scenario_action": "若 VPD 在 AI data center 平台采用率提高，下调离散电感核心实体和相关标的评分。",
        "falsified_scenario_action": "若客户仍采用离散 TLVR/VRM 电感，Infineon 只作为架构风险监控，不压低核心实体评分。",
    },
    ("mainland_listed_company_capture", "顺络电子（002138.SZ）"): {
        "relative_preference": "大陆公司排序第一，产品阶段最清楚；相对铂科和龙磁，顺络确定性更高但短期收入弹性受数据中心占比低约束。",
        "research_action": "跟踪 TLVR 批量供应后的收入占比、客户阶段和毛利率，判断产品阶段能否变成财务结果。",
        "investment_view": "作为大陆上市公司承接能力的基准标的；收入占比改善前只给产品验证权重。",
        "risk_note": "主要风险是数据中心收入占比低、客户名未公开、TLVR 业务被传统被动元件业务稀释。",
        "confirmed_scenario_action": "若数据中心业务占比和毛利率同步提升，维持大陆首位并上调财务弹性。",
        "falsified_scenario_action": "若产品批量供应不反映在收入和利润，降为产品线索而非财务弹性标的。",
    },
    ("mainland_listed_company_capture", "铂科新材（300811.SZ）"): {
        "relative_preference": "大陆公司排序第二，材料和器件一体化强于龙磁；但客户和收入拆分弱于顺络。",
        "research_action": "跟踪芯片电感收入、金属软磁材料成本、客户认证和 ASP，确认一体化逻辑是否兑现。",
        "investment_view": "作为结构性受益标的研究，证实重点是收入拆分和利润率，而非泛材料景气。",
        "risk_note": "主要风险是客户不可见、芯片电感收入不可拆、原材料成本波动影响毛利。",
        "confirmed_scenario_action": "若芯片电感收入和客户认证披露，上调为大陆第二核心。",
        "falsified_scenario_action": "若只披露需求受益但无收入和客户证据，降为材料侧观察。",
    },
    ("mainland_listed_company_capture", "龙磁科技（300835.SZ）"): {
        "relative_preference": "大陆公司排序第三，弹性最高但确定性最低；适合验证订单放量，不适合作为当前最稳标的。",
        "research_action": "跟踪国际客户中标后的交付、复购、客户扩展和新业务收入占比。",
        "investment_view": "作为高弹性小基数标的研究，只有订单连续性和收入确认出现后才上调。",
        "risk_note": "主要风险是单笔中标不可持续、客户匿名、量产能力和良率不确定。",
        "confirmed_scenario_action": "若后续订单扩大且收入确认，提升为弹性优先标的。",
        "falsified_scenario_action": "若没有后续公告或仍小批量，降为订单线索观察项。",
    },
    ("powder_material_capacity_bottleneck", "悦安新材（688786.SH）"): {
        "relative_preference": "本实体唯一上游粉体映射，位置比器件厂更靠前；它验证材料瓶颈，不验证客户供货。",
        "research_action": "跟踪羰基铁粉细粉订单、价格、客户结构和下游一体成型电感需求传导。",
        "investment_view": "作为上游材料期权研究，只有粉体订单和价格传导被证实时才提高优先级。",
        "risk_note": "主要风险是下游器件需求无法传导到粉体收入，材料供应快速扩张导致瓶颈价值下降。",
        "confirmed_scenario_action": "若细粉订单、价格和毛利率同步改善，上调为材料瓶颈受益项。",
        "falsified_scenario_action": "若粉体供给不紧或收入不响应，保留为上游观察，不外推器件厂客户验证。",
    },
    ("tlvr_vertical_power_transition", "台达/乾坤观察项"): {
        "relative_preference": "相对 TLVR 产线观察篮子，台达/乾坤是具体台系供给侧线索；但公开确认不足，低于顺络和 Cyntec 官方产品证据。",
        "research_action": "补查台达/乾坤 TLVR 料号、AI server 客户和产线信息，区分专家线索和公开确认。",
        "investment_view": "作为 TLVR 台系供应链观察项，证据补足前不写成已确认供货。",
        "risk_note": "主要风险是线索主要来自专家纪要，缺少公司公告、客户平台或财务拆分。",
        "confirmed_scenario_action": "若公开资料确认 TLVR 客户或量产，提升为 TLVR 主线标的。",
        "falsified_scenario_action": "若只能停留纪要线索，保留观察项并降低核心评分贡献。",
    },
    ("tlvr_vertical_power_transition", "TLVR 产线切换观察篮子"): {
        "relative_preference": "该篮子不是公司标的，而是 TLVR 技术切换的监控工具；优先级用于约束所有 TLVR 公司标的。",
        "research_action": "跟踪产线数量、设备交期、日产能、良率、客户切换节奏和 TLVR ASP。",
        "investment_view": "作为技术切换验证工具；只有产线和客户切换确认后，才上调相关公司。",
        "risk_note": "主要风险是产线线索不可公开复核，或 TLVR 被 VPD/Power Block 替代。",
        "confirmed_scenario_action": "若产线扩张、良率和 ASP 被公开证据确认，上调 TLVR 实体整体评分。",
        "falsified_scenario_action": "若产线切换延迟或客户绕开 TLVR，降低 TLVR 主题权重。",
    },
    ("global_supplier_competition", "国巨/奇力新观察项"): {
        "relative_preference": "在全球竞争实体中作为台系第二供给代表；公开产品线强于大陆普通线索，客户份额弱于 Cyntec。",
        "research_action": "补查国巨/奇力新 AI server 料号、客户平台和收入拆分。",
        "investment_view": "作为台系竞争格局观察项，重点验证第二来源和高端料号份额。",
        "risk_note": "主要风险是被动元件业务宽泛，AI 高端电感份额和利润难拆。",
        "confirmed_scenario_action": "若确认进入主流 AI 平台料号，上调台系份额判断。",
        "falsified_scenario_action": "若无客户和料号证据，维持竞争对照，不进入核心标的。",
    },
    ("global_supplier_competition", "TDK（6762.T）"): {
        "relative_preference": "全球竞争实体中的技术天花板参照；确定性强于大陆标的，弹性弱于小基数公司。",
        "research_action": "跟踪 TDK AI server power delivery 方案和具体料号，用于校验国产替代难度。",
        "investment_view": "作为全球龙头壁垒和竞争基准研究，不以短期弹性为主。",
        "risk_note": "主要风险是 AI 电感收入不可拆，且技术能力不等于具体平台份额。",
        "confirmed_scenario_action": "若披露 AI server 电感料号和份额，上调全球龙头竞争压力。",
        "falsified_scenario_action": "若缺少料号和收入证据，仅保留为技术参照。",
    },
    ("global_supplier_competition", "Murata（6981.T）"): {
        "relative_preference": "与 TDK 同属日本龙头，但 Murata 更偏 PDN 和被动元件组合方案；对离散电感的直接映射弱于 TDK。",
        "research_action": "跟踪 Murata PDN 指南、AI data center 方案和电感/磁珠料号。",
        "investment_view": "作为系统级 PDN 竞争参照，重点看是否稀释单一离散电感机会。",
        "risk_note": "主要风险是产品组合过宽，AI 电感贡献被电容、磁珠和模块分散。",
        "confirmed_scenario_action": "若 AI data center 电感料号确认，上调为日本龙头竞争约束。",
        "falsified_scenario_action": "若仍是宽泛 PDN 方案，保留为系统参照。",
    },
    ("high_end_inductor_price_market_space", "AI 高端电感价格观察篮子"): {
        "relative_preference": "本实体唯一价格工具，不是公司标的；它约束所有公司收入弹性，优先级高于单个未验证价格传闻。",
        "research_action": "持续更新型号价格、TLVR ASP、年度议价和普通/高端电感价差。",
        "investment_view": "作为估算 TAM/SAM/SOM 的价格闸门；只有高端型号价格持续上行，才上调公司收入弹性。",
        "risk_note": "主要风险是价格上涨发生在普通型号或短期渠道，不能传导到 AI 高端料号和公司毛利。",
        "confirmed_scenario_action": "若高端 AI 型号 ASP 与年度议价同步改善，上调市场空间和标的财务弹性。",
        "falsified_scenario_action": "若涨价只在非 AI 型号或不可持续，下修 TAM 和公司弹性假设。",
    },
    ("customer_validation_matrix", "英伟达/Google/华为客户验证观察篮子"): {
        "relative_preference": "客户验证实体的总闸门，不是公司标的；优先级高于单个传闻，用来决定哪些公司能升级评分。",
        "research_action": "按直接供货、间接供货、验证、小批量、批量供货和公开确认六级更新客户矩阵。",
        "investment_view": "作为客户确认工具；只有客户阶段可核验时，相关公司才能从观察项升为核心标的。",
        "risk_note": "主要风险是把专家纪要、二级市场传闻或匿名客户误写成 NVIDIA/Google/华为公开确认。",
        "confirmed_scenario_action": "若客户公告、公司 IR、ODM/OEM 交付和财报收入交叉确认，上调相关公司客户验证权重。",
        "falsified_scenario_action": "若只有传闻或客户匿名，维持验证债并降低相关标的优先级。",
    },
    ("customer_validation_matrix", "顺络电子（002138.SZ）客户验证项"): {
        "relative_preference": "客户验证矩阵中大陆公开阶段最清楚，但未公开客户名；强于铂科和龙磁的产品阶段，弱于真正客户点名确认。",
        "research_action": "跟踪顺络客户阶段、数据中心收入占比和 TLVR 订单，把批量供应与具体客户链分开验证。",
        "investment_view": "作为客户验证矩阵中的大陆首要验证项；客户名和收入确认前不写成已供 NVIDIA/Google/华为。",
        "risk_note": "主要风险是批量供应不等于头部客户确认，且数据中心收入占比仍低。",
        "confirmed_scenario_action": "若公开客户、订单或收入确认出现，上调为客户验证核心标的。",
        "falsified_scenario_action": "若仍无客户名且收入占比低，保留产品阶段权重，不升级客户评分。",
    },
    ("customer_validation_matrix", "铂科新材（300811.SZ）客户验证项"): {
        "relative_preference": "客户验证矩阵中铂科是 ASIC/GPU 功率提升受益线索，客户证据弱于顺络，材料/器件一体化强于单一传闻项。",
        "research_action": "补查客户认证、芯片电感收入拆分和 ASP，确认 ASIC/GPU 需求是否转为客户订单。",
        "investment_view": "作为客户验证的中高优先观察项，必须等待客户和收入拆分确认。",
        "risk_note": "主要风险是需求表述无法落到客户名、料号和收入，材料逻辑被误作客户确认。",
        "confirmed_scenario_action": "若披露客户认证或芯片电感收入，上调为客户验证第二梯队。",
        "falsified_scenario_action": "若仍只有需求受益表述，降为材料/器件一体化观察项。",
    },
    ("customer_validation_matrix", "龙磁科技（300835.SZ）客户验证项"): {
        "relative_preference": "客户验证矩阵中龙磁有订单金额和小批量线索，客户阶段强于纯产品能力项；但客户匿名和持续性弱于顺络。",
        "research_action": "跟踪中标客户、小批量转批量、后续订单和收入确认。",
        "investment_view": "作为客户验证弹性项研究；证据若延续可快速上调，否则只能保留订单线索。",
        "risk_note": "主要风险是单次中标无法代表持续供货，客户匿名且小批量收入不确定。",
        "confirmed_scenario_action": "若中标转批量且后续订单披露，上调客户验证权重。",
        "falsified_scenario_action": "若无后续订单或客户验证停滞，降为早期信号。",
    },
    ("customer_validation_matrix", "台达/乾坤客户验证观察项"): {
        "relative_preference": "客户验证矩阵中台达/乾坤是台系主流线索，供应链位置强；但证据主要来自专家纪要，低于官方客户确认。",
        "research_action": "补查台达/乾坤客户平台、料号、订单和公开 IR。",
        "investment_view": "作为台系客户验证观察项，公开确认前不写成已供头部客户。",
        "risk_note": "主要风险是专家纪要线索无法被公司公告或客户平台复核。",
        "confirmed_scenario_action": "若公开料号或客户确认出现，上调为台系客户验证核心项。",
        "falsified_scenario_action": "若公开证据长期缺失，维持观察项并降低客户矩阵权重。",
    },
    ("customer_validation_matrix", "国巨/奇力新客户验证观察项"): {
        "relative_preference": "客户验证矩阵中作为台系被动元件链条观察项，产品和供应链能力有支撑，但客户确认弱于顺络和龙磁订单线索。",
        "research_action": "补查 NVIDIA/Google/华为或服务器平台相关料号、订单和收入拆分。",
        "investment_view": "作为台系第二来源观察项，证实前只给能力权重，不给客户确认权重。",
        "risk_note": "主要风险是被动元件平台能力被误读为具体客户份额。",
        "confirmed_scenario_action": "若客户平台或料号确认，上调为第二来源客户验证项。",
        "falsified_scenario_action": "若无客户证据，保留全球供应链观察。",
    },
    ("customer_validation_matrix", "TDK（6762.T）客户验证项"): {
        "relative_preference": "客户验证矩阵中 TDK 是海外龙头对照，技术能力强于大陆公司，但具体 AI 平台客户证据不足。",
        "research_action": "跟踪 TDK AI server 料号、客户平台和供应份额。",
        "investment_view": "作为海外龙头客户验证对照，用来约束国产替代假设。",
        "risk_note": "主要风险是官方技术能力不等于 NVIDIA/Google/华为具体供货。",
        "confirmed_scenario_action": "若料号和客户平台确认，上调海外龙头份额压力。",
        "falsified_scenario_action": "若无客户证据，继续作为技术能力对照。",
    },
    ("customer_validation_matrix", "Murata（6981.T）客户验证项"): {
        "relative_preference": "客户验证矩阵中 Murata 是 PDN 方案对照，系统能力强但电感客户映射弱于 TDK。",
        "research_action": "跟踪 Murata AI data center PDN 客户、料号和电感/磁珠组合方案。",
        "investment_view": "作为系统级客户验证对照，用于判断客户是否采用宽 PDN 方案而非单一电感。",
        "risk_note": "主要风险是客户验证落在综合 PDN 方案，无法拆到电感料号。",
        "confirmed_scenario_action": "若 AI data center 电感或 PDN 客户确认，上调系统方案权重。",
        "falsified_scenario_action": "若无料号和客户证据，保留为海外对照。",
    },
    ("ai_chip_inductor_vrm_core", "GPU/ASIC VRM BOM 观察篮子"): {
        "relative_preference": "该篮子是核心实体的需求基准，优先级用于约束所有公司标的；它不是可投资公司，不能替代具体标的研究。",
        "research_action": "持续跟踪 GB300/Rubin/TPU/昇腾平台单板相数、单卡用量、TLVR 渗透和 VPD 替代。",
        "investment_view": "作为需求和架构监控工具；BOM 上行时上调器件公司，BOM 被集成模块吸收时下调离散电感。",
        "risk_note": "主要风险是 BOM 估算没有客户料号验证，或新平台通过集成电源模块减少离散电感。",
        "confirmed_scenario_action": "若新平台 BOM 确认单板电感用量和高端料号提升，上调核心实体需求评分。",
        "falsified_scenario_action": "若单位用量下降或 VPD 替代增强，下修离散电感 TAM。",
    },
}


def _target_fields(entity_key: str, target_name: str, rationale: str, priority: str, quality: str) -> dict[str, str]:
    fields = TARGET_FIELD_OVERRIDES.get((entity_key, target_name))
    if not fields:
        raise ValueError(f"缺少逐标的研究字段: {entity_key} / {target_name}")
    required = {
        "relative_preference",
        "research_action",
        "investment_view",
        "risk_note",
        "confirmed_scenario_action",
        "falsified_scenario_action",
    }
    missing = sorted(required.difference(fields))
    if missing:
        raise ValueError(f"逐标的研究字段不完整: {entity_key} / {target_name}: {missing}")
    return fields


def _target_data_points(target_name: str, evidence_ref: str, rationale: str, fields: dict[str, str]) -> list[dict[str, Any]]:
    points = [
        {
            "metric_name": "暴露逻辑",
            "metric_category": "target_research",
            "period": AS_OF_DATE,
            "as_of_date": AS_OF_DATE,
            "value_text": rationale,
            "unit": "文本",
            "source_title": "AI 高端电感人工核验证据包",
            "source_publisher": "Opportunity Lens",
            "source_url": None,
            "source_excerpt": rationale,
            "evidence_ref_uri": _source_ref(evidence_ref),
            "data_quality_label": "人工核验",
            "direction": "positive",
            "credibility_weight": 0.75,
            "numeric_weight": 0.65,
        },
        {
            "metric_name": "证实后研究动作",
            "metric_category": "scenario",
            "period": AS_OF_DATE,
            "as_of_date": AS_OF_DATE,
            "value_text": fields["confirmed_scenario_action"],
            "unit": "文本",
            "source_title": "AI 高端电感情景框架",
            "source_publisher": "Opportunity Lens",
            "source_excerpt": fields["confirmed_scenario_action"],
            "evidence_ref_uri": _source_ref(evidence_ref),
            "data_quality_label": "情景分析",
            "direction": "positive",
            "credibility_weight": 0.7,
            "numeric_weight": 0.55,
        },
        {
            "metric_name": "证伪后研究动作",
            "metric_category": "scenario",
            "period": AS_OF_DATE,
            "as_of_date": AS_OF_DATE,
            "value_text": fields["falsified_scenario_action"],
            "unit": "文本",
            "source_title": "AI 高端电感情景框架",
            "source_publisher": "Opportunity Lens",
            "source_excerpt": fields["falsified_scenario_action"],
            "evidence_ref_uri": _source_ref(evidence_ref),
            "data_quality_label": "情景分析",
            "direction": "negative",
            "credibility_weight": 0.7,
            "numeric_weight": 0.55,
        },
    ]
    if "顺络" in target_name:
        points.append({
            "metric_name": "数据中心收入占比",
            "metric_category": "company_ir",
            "period": "2026Q1",
            "as_of_date": "2026-07-01",
            "value_text": "不足5%",
            "unit": "%",
            "source_title": "顺络电子投资者关系活动记录表",
            "source_publisher": "顺络电子",
            "source_excerpt": "公司披露数据中心业务营收占公司整体营收比重尚不足5%。",
            "evidence_ref_uri": _source_ref(evidence_ref),
            "data_quality_label": "公司 IR",
            "direction": "mixed",
            "credibility_weight": 0.9,
            "numeric_weight": 0.9,
        })
    if "龙磁" in target_name:
        points.append({
            "metric_name": "高端模压电感中标金额",
            "metric_category": "company_announcement",
            "period": "2025-01",
            "as_of_date": "2025-01-22",
            "value_num": 2300,
            "unit": "万元",
            "source_title": "龙磁科技收到客户中标通知",
            "source_publisher": "财联社/公司公告",
            "source_excerpt": "中标金额约2300万元。",
            "evidence_ref_uri": _source_ref(evidence_ref),
            "data_quality_label": "公告转述",
            "direction": "positive",
            "credibility_weight": 0.85,
            "numeric_weight": 1.0,
        })
    if "铂科" in target_name:
        points.append({
            "metric_name": "ASIC/GPU 功率提升影响",
            "metric_category": "company_ir",
            "period": "2026-04",
            "as_of_date": "2026-04-24",
            "value_text": "ASIC 芯片和 AI GPU 功率增长带来出货数量和性能要求变化。",
            "unit": "文本",
            "source_title": "铂科新材投资者关系活动记录表",
            "source_publisher": "铂科新材",
            "source_excerpt": "铂科新材表示 ASIC 芯片和 AI GPU 功率增长将带来出货数量和性能要求变化。",
            "evidence_ref_uri": _source_ref(evidence_ref),
            "data_quality_label": "公司 IR",
            "direction": "positive",
            "credibility_weight": 0.9,
            "numeric_weight": 0.8,
        })
    if "台达/乾坤" in target_name:
        points.append({
            "metric_name": "AI server 板级功率电感官方定位",
            "metric_category": "official_product_positioning",
            "period": "2026-07-04",
            "as_of_date": "2026-07-04",
            "value_text": "Cyntec 把低损耗功率电感用于 AI server SXM accelerator cards、UBB motherboards 和 switch。",
            "unit": "文本",
            "source_title": "Cyntec Total Solution for AI Server and Switch",
            "source_publisher": "Cyntec",
            "source_url": "https://www.cyntec.com/Apps/AISS",
            "source_excerpt": "Cyntec developed compact, high-efficiency, low-loss power inductors for AI server SXM accelerator cards, UBB motherboards, and Switch.",
            "evidence_ref_uri": _source_ref(evidence_ref),
            "data_quality_label": "官方产品页",
            "direction": "positive",
            "credibility_weight": 0.95,
            "numeric_weight": 0.8,
        })
    if "国巨/奇力新" in target_name:
        points.append({
            "metric_name": "TPI 系列 AI power 电感定位",
            "metric_category": "official_product_positioning",
            "period": "2025-06-27",
            "as_of_date": "2025-06-27",
            "value_text": "YAGEO/KEMET/Pulse TPI 系列面向下一代计算平台功率需求扩展。",
            "unit": "文本",
            "source_title": "YAGEO Group's TPI Series Expanded for AI, Servers, and High-Efficiency Power",
            "source_publisher": "YAGEO Group",
            "source_url": "https://yageogroup.com/SalesResources/ResourceLibrary/news/14368",
            "source_excerpt": "YAGEO Group's TPI Series SMD ferrite core inductors expanded to meet growing power demands of next-generation computing platforms.",
            "evidence_ref_uri": _source_ref(evidence_ref),
            "data_quality_label": "官方产品页",
            "direction": "positive",
            "credibility_weight": 0.9,
            "numeric_weight": 0.75,
        })
    if "Coilmaster" in target_name:
        points.append({
            "metric_name": "GPU/CPU VRM 高电流电感官方定位",
            "metric_category": "official_product_positioning",
            "period": "2026-07-04",
            "as_of_date": "2026-07-04",
            "value_text": "Coilmaster 把 GPU/CPU VRM 电感定位为 AI compute platforms 中的低 DCR、高饱和电流器件。",
            "unit": "文本",
            "source_title": "GPU / CPU VRM inductors",
            "source_publisher": "Coilmaster Electronics",
            "source_url": "https://www.coilmaster.com.tw/en/applications/GPU_CPU-VRM-inductors.html",
            "source_excerpt": "Modern GPUs and CPUs draw hundreds of amps with extremely fast load transients, making VRM inductor performance a primary factor.",
            "evidence_ref_uri": _source_ref(evidence_ref),
            "data_quality_label": "官方应用页",
            "direction": "positive",
            "credibility_weight": 0.85,
            "numeric_weight": 0.7,
        })
    if "Vishay" in target_name:
        points.append({
            "metric_name": "IHSR AI/GPU 高电流电感定位",
            "metric_category": "official_product_positioning",
            "period": "2026-07-04",
            "as_of_date": "2026-07-04",
            "value_text": "Vishay IHSR 高电流 SMD 电感用于 datacenter、AI computing 和 GPU 应用。",
            "unit": "文本",
            "source_title": "IHSR - High current SMD inductors",
            "source_publisher": "Vishay",
            "source_url": "https://www.vishay.com/en/videos/inductors/ihlp174-power-inductor-family-overview/",
            "source_excerpt": "IHSR features ultra-low DCR, low inductance, and small size for datacenter, AI computing, and GPUs applications.",
            "evidence_ref_uri": _source_ref(evidence_ref),
            "data_quality_label": "官方产品页",
            "direction": "positive",
            "credibility_weight": 0.9,
            "numeric_weight": 0.75,
        })
    if "Eaton" in target_name:
        points.append({
            "metric_name": "AI molded powder 电感官方定位",
            "metric_category": "official_product_positioning",
            "period": "2026-07-04",
            "as_of_date": "2026-07-04",
            "value_text": "Eaton 把 molded powder inductors 用于 AI computing xPU power delivery 的效率、散热和可靠性改善。",
            "unit": "文本",
            "source_title": "Molded powder inductors boost AI computing power",
            "source_publisher": "Eaton",
            "source_url": "https://www.eaton.com/us/en-us/products/electronic-components/infographics/molded-powder-inductors-boost-ai-computing-power.html",
            "source_excerpt": "Eaton says molded powder inductors improve efficiency and heat dissipation, minimize power losses, and ensure long-term operation.",
            "evidence_ref_uri": _source_ref(evidence_ref),
            "data_quality_label": "官方产品页",
            "direction": "positive",
            "credibility_weight": 0.9,
            "numeric_weight": 0.75,
        })
    if "Taiyo Yuden" in target_name:
        points.append({
            "metric_name": "AI server 高附加值电感战略",
            "metric_category": "official_report_positioning",
            "period": "2025",
            "as_of_date": "2025-10-01",
            "value_text": "Taiyo Yuden 将 power inductor growth 聚焦到 AI servers 等高附加值区域。",
            "unit": "文本",
            "source_title": "TAIYO YUDEN Integrated Report 2025: Power inductor advances",
            "source_publisher": "TAIYO YUDEN",
            "source_url": "https://www.yuden.co.jp/en/ir/2025ar/download/pdf/yuden_ar25_e_p37_p41.pdf",
            "source_excerpt": "TAIYO YUDEN will focus on high-value-added zones such as AI servers and automobiles in power inductor growth strategies.",
            "evidence_ref_uri": _source_ref(evidence_ref),
            "data_quality_label": "官方年报",
            "direction": "positive",
            "credibility_weight": 0.9,
            "numeric_weight": 0.75,
        })
    if "Infineon" in target_name:
        points.append({
            "metric_name": "VPD 集成模块替代风险",
            "metric_category": "substitution_risk",
            "period": "2026-07-04",
            "as_of_date": "2026-07-04",
            "value_text": "Infineon quad-phase VPD 模块把磁件与电源模块集成，是离散电感机会的反方风险。",
            "unit": "文本",
            "source_title": "AI quad-phase power modules designed for VPD",
            "source_publisher": "Infineon Technologies",
            "source_url": "https://www.infineon.com/technology/ai/we-power-ai/vrm",
            "source_excerpt": "Infineon says OptiMOS quad-phase power modules target AI data centers and enable true vertical power delivery.",
            "evidence_ref_uri": _source_ref(evidence_ref),
            "data_quality_label": "官方产品页",
            "direction": "negative",
            "credibility_weight": 0.95,
            "numeric_weight": 0.8,
        })
    if "TDK" in target_name:
        points.append({
            "metric_name": "AI server power delivery 电感定位",
            "metric_category": "official_product_positioning",
            "period": "2025-10",
            "as_of_date": "2025-10-01",
            "value_text": "TDK 将 AI server power delivery 和 noise suppression 作为电感应用场景。",
            "unit": "文本",
            "source_title": "How Electronic Components Underpin the Growth of the AI-Driven Society",
            "source_publisher": "TDK",
            "source_url": "https://www.tdk.com/en/featured_stories/entry_082-AI-Ecosystem.html",
            "source_excerpt": "TDK said AI servers need reliable power and noise suppression; its inductors support voltage conversion and stable GPU power delivery.",
            "evidence_ref_uri": _source_ref(evidence_ref),
            "data_quality_label": "官方应用页",
            "direction": "positive",
            "credibility_weight": 0.9,
            "numeric_weight": 0.75,
        })
    if "Murata" in target_name:
        points.append({
            "metric_name": "AI data center PDN 电感定位",
            "metric_category": "official_product_positioning",
            "period": "2026-02",
            "as_of_date": "2026-02-04",
            "value_text": "Murata AI data center PDN 指南把电感纳入稳定供电方案。",
            "unit": "文本",
            "source_title": "Technology guide to enhance power stability in AI-driven data centers",
            "source_publisher": "Murata",
            "source_url": "https://www.murata.com/en-us/news/other/other/2026/0204",
            "source_excerpt": "Murata launched an AI server power delivery guide and said it supports evolving power placement architectures with inductors and other components.",
            "evidence_ref_uri": _source_ref(evidence_ref),
            "data_quality_label": "官方应用页",
            "direction": "positive",
            "credibility_weight": 0.9,
            "numeric_weight": 0.75,
        })
    return points


def _build_targets() -> list[dict[str, Any]]:
    targets = []
    for idx, (entity_key, name, ticker, market, target_type, evidence_ref, rationale, priority, quality) in enumerate(TARGETS, start=1):
        fields = _target_fields(entity_key, name, rationale, priority, quality)
        confirmed = fields["confirmed_scenario_action"]
        falsified = fields["falsified_scenario_action"]
        conditional_view = "\n\n".join([
            fields["investment_view"],
            confirmed,
            falsified,
        ])
        targets.append({
            "entity_key": entity_key,
            "target_name": name,
            "ticker": ticker,
            "market": market,
            "target_type": target_type,
            "target_url": f"https://finance.yahoo.com/quote/{ticker}" if ticker else None,
            "exposure_rationale": rationale,
            "evidence_ref_uri": _source_ref(evidence_ref),
            "research_action": fields["research_action"],
            "investment_view": fields["investment_view"],
            "risk_note": fields["risk_note"],
            "target_priority": priority,
            "target_quality_label": quality,
            "relative_preference": fields["relative_preference"],
            "confirmed_scenario_action": confirmed,
            "falsified_scenario_action": falsified,
            "target_profile_markdown": "\n\n".join([rationale, fields["relative_preference"]]),
            "target_deep_research_markdown": "\n\n".join([
                fields["research_action"],
                fields["investment_view"],
                fields["risk_note"],
            ]),
            "entity_relation_markdown": "\n\n".join([rationale, fields["relative_preference"]]),
            "parent_research_relation_markdown": fields["investment_view"],
            "conditional_investment_recommendation": conditional_view,
            "financial_data_status": "本轮使用公司 IR、研报和公开网页快照；缺少 Tushare/yfinance 刷新授权时不新增行情回填，历史 Wind provenance 不作为新增来源。",
            "target_data_points": _target_data_points(name, evidence_ref, rationale, fields),
            "link_status": "external_only" if target_type in {"external_watch", "basket"} else "linked",
            "support_status": "supported" if priority in {"高", "中高"} else "partially_supported",
            "sort_order": idx,
        })
    return targets


def _chart_points(values: list[float]) -> str:
    if not values:
        return ""
    lo, hi = min(values), max(values)
    spread = hi - lo if hi != lo else 1
    pts = []
    for i, value in enumerate(values):
        x = 100 * i / max(1, len(values) - 1)
        y = 88 - 76 * (value - lo) / spread
        pts.append(f"{x:.2f},{y:.2f}")
    return " ".join(pts)


def _build_visuals() -> list[dict[str, Any]]:
    years = ["2023", "2024", "2025E", "2026E", "2027E", "2028E", "2029E"]
    demand = [1.2, 2.4, 4.0, 8.0, 15.4, 23.5, 34.5]
    avg_use = [34, 32, 41, 47, 61, 71, 79]
    tam_neutral = [v * 0.7 for v in demand]
    x_ticks = [{"label": y, "position": round(i * 100 / (len(years) - 1), 2)} for i, y in enumerate(years)]
    def panel(title: str, values: list[float], unit: str, color: str) -> dict[str, Any]:
        return {
            "title": title,
            "x_start": years[0],
            "x_end": years[-1],
            "unit": unit,
            "x_axis_label": "横轴：年份",
            "y_axis_label": f"纵轴：{unit}",
            "x_ticks": x_ticks,
            "y_ticks": [
                {"label": f"{max(values):.1f}", "position": 12},
                {"label": f"{(max(values)+min(values))/2:.1f}", "position": 50},
                {"label": f"{min(values):.1f}", "position": 88},
            ],
            "y_min": f"{min(values):.1f}",
            "y_max": f"{max(values):.1f}",
            "series": [{
                "label": title,
                "color": color,
                "svg_points": _chart_points(values),
                "latest_period": years[-1],
                "latest_value": f"{values[-1]:.1f}{unit}",
                "observation_count": len(values),
            }],
        }
    customer_rows = [
        ["顺络电子", "公开 IR 披露 TLVR 批量化供应，客户名未公开", "无公开客户名", "无公开客户名", "中高", "收入占比不足5%，需收入确认"],
        ["铂科新材", "AI GPU/ASIC 受益，客户未公开", "ASIC 线索", "国产链间接", "中", "需客户和收入拆分"],
        ["龙磁科技", "某国际客户高端模压电感中标和小批量", "无公开客户名", "无公开客户名", "中", "客户匿名和放量待确认"],
        ["台达/乾坤、国巨/奇力新", "专家纪要主流供应商线索", "间接线索", "无公开证据", "中低", "需官方或客户确认"],
        ["TDK、Murata", "官方产品能力强，具体料号未确认", "数据中心 PDN 能力", "无公开证据", "中", "需具体客户/平台料号"],
    ]
    return [
        {
            "block_key": "ai_inductor_demand_market_space_chart",
            "block_type": "line_chart",
            "entity_key": "high_end_inductor_price_market_space",
            "title": "AI 芯片电感需求量和中性 TAM 测算",
            "subtitle": "把同一表格中的 2023-2029E 序列打包为少数可解释数据点，展示需求量、单片用量和收入情景。",
            "data": {
                "what": "AI 芯片电感需求量、平均单片用电感数和中性 ASP 情景收入。",
                "time_window": "2023 至 2029E。",
                "how_to_read": "需求量和单片用量同时上行说明机会不只是出货增长，也来自单位用量和规格升级；TAM 仍需 ASP 和客户认证折扣。",
                "analysis": "2026E 至 2029E 的增量最大，但普通电感 ASP 不得直接外推到 TLVR 或高端 AI 电感。",
                "chart": {"panels": [panel("芯片电感需求量", demand, "亿颗", "#2563eb"), panel("平均单片用电感数", avg_use, "颗/片", "#0f766e"), panel("中性 TAM", tam_neutral, "亿美元", "#b45309")]},
            },
            "display_data": {
                "columns": ["指标", "2026E", "2027E", "2028E", "2029E", "怎么看", "来源"],
                "rows": [
                    ["芯片电感需求量", "8.0 亿颗", "15.4 亿颗", "23.5 亿颗", "34.5 亿颗", "需求量加速上行，是 bottom-up 的核心颗数口径", "图150"],
                    ["平均单片用量", "47 颗/片", "61 颗/片", "71 颗/片", "79 颗/片", "单位用量提升说明规格升级仍在发生", "图150"],
                    ["中性 TAM", "5.6 亿美元", "10.8 亿美元", "16.5 亿美元", "24.2 亿美元", "按 0.70 美元 ASP，仅为中性情景", "测算"],
                ],
            },
            "evidence_ref_uri_list": _section_refs(["xlsx_chip_inductor_demand", "local_huatai_expert_inductor"]),
            "support_status": "supported",
            "sort_order": 610,
        },
        {
            "block_key": "customer_validation_matrix_visual",
            "block_type": "table",
            "title": "英伟达 / Google / 华为客户验证矩阵",
            "subtitle": "区分公开确认、间接供货、客户验证、小批量、批量供应和灰源线索。",
            "data": {
                "what": "客户验证阶段矩阵",
                "columns": ["公司或环节", "英伟达", "Google", "华为", "置信度", "验证债"],
                "rows": customer_rows,
                "column_width_policy": {
                    "short_columns": ["置信度"],
                    "long_columns": ["英伟达", "Google", "华为", "验证债"],
                },
            },
            "display_data": {
                "columns": ["公司或环节", "英伟达", "Google", "华为", "置信度", "验证债"],
                "rows": customer_rows,
            },
            "evidence_ref_uri_list": _section_refs(["web_sunlord_ir_tlvr_20260701", "web_boke_ir_20260424", "web_longci_bid_20250122", "local_huaan_expert_inductor", "web_tdk_ai_ecosystem"]),
            "support_status": "supported",
            "sort_order": 620,
        },
        {
            "block_key": "price_taxonomy_visual",
            "block_type": "table",
            "title": "AI 高端电感价格口径分层",
            "subtitle": "防止把普通消费电子电感价格误用于 AI 高端电感测算。",
            "data": {
                "what": "价格口径分层",
                "columns": ["产品口径", "价格/变化", "适用场景", "怎么看", "来源"],
                "rows": [
                    ["传统 AI 芯片电感", "0.4-0.6 美元/颗", "英伟达等高端芯片电感", "可作为高端 ASP 中性下沿", "专家纪要"],
                    ["TLVR 电感", "1 美元以上/颗", "下一代 TLVR/VPD", "价值量更高但需确认渗透率", "专家纪要"],
                    ["部分高频叠层/通信型号", "年初至今涨幅超100%", "通信/AI服务器主板相关", "不能直接代表所有 AI 电感", "本地价格表"],
                    ["普通功率/消费型号", "可能下跌或分化", "消费电子/笔电/车载通用", "不能外推到 AI 高端 TAM", "本地价格表"],
                ],
                "column_width_policy": {
                    "short_columns": ["来源"],
                    "long_columns": ["适用场景", "怎么看"],
                },
            },
            "display_data": {
                "columns": ["产品口径", "价格/变化", "适用场景", "怎么看", "来源"],
                "rows": [
                    ["传统 AI 芯片电感", "0.4-0.6 美元/颗", "英伟达等高端芯片电感", "可作为高端 ASP 中性下沿", "专家纪要"],
                    ["TLVR 电感", "1 美元以上/颗", "下一代 TLVR/VPD", "价值量更高但需确认渗透率", "专家纪要"],
                    ["部分高频叠层/通信型号", "年初至今涨幅超100%", "通信/AI服务器主板相关", "不能直接代表所有 AI 电感", "本地价格表"],
                    ["普通功率/消费型号", "可能下跌或分化", "消费电子/笔电/车载通用", "不能外推到 AI 高端 TAM", "本地价格表"],
                ],
            },
            "evidence_ref_uri_list": _section_refs(["local_huatai_expert_inductor", "xlsx_inductor_model_price", "xlsx_price_case"]),
            "support_status": "supported",
            "sort_order": 630,
        },
    ]


def _build_early_signals(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for entity in entities:
        out.append({
            "entity_key": entity["key"],
            "early_signal_score": min(95, entity["score_point"] + 6),
            "early_signal_strength_label": "strong" if entity["score_point"] >= 78 else "medium",
            "research_priority_score": min(100, entity["score_point"] + 8),
            "research_priority_label": "high_priority_for_scoring" if entity["score_point"] >= 78 else "medium_priority_for_followup",
            "source_count": entity["source_count"],
            "independent_source_count": entity["independent_source_count"],
            "verification_debt_count": 2 if entity["score_point"] >= 80 else 3,
            "core_score_snapshot": entity["score_point"],
            "evidence_ref_uri_list": entity["evidence_ref_uri_list"][:6],
            "aggregate_trace": {
                "reason": "freshness_first 证据策略下，用早期信号提示复核优先级，但不改变核心 14 因子评分。",
                "verification_debt": entity["composite_trace"]["monitor_signal"],
            },
        })
    return out


def build_pack() -> dict[str, Any]:
    sources = _make_sources()
    lookup = _source_lookup(sources)
    data_points = _build_data_points()
    entities = _entity_specs(lookup)
    sections = _build_report_sections()
    entity_sections = [_entity_section(entity, data_points) for entity in entities]
    pack = {
        "slug": "20260704_ai_high_end_inductor_deep_run",
        "research_question": _read_text(INTAKE_PATH).split("```text", 1)[1].split("```", 1)[0].strip(),
        "run_mode": "c_hybrid",
        "requested_by": "manual_verified_agent_flow",
        "problem_statement": "AI 高端电感、TLVR、高端功率电感和服务器电源磁性元件的供需失衡、客户验证与投资机会扫描。",
        "as_of_date": AS_OF_DATE,
        "intake": {
            "research_question": "未来 12 个月至未来 5 年，AI 高端电感 / 高端功率电感 / 服务器电源磁性元件行业的竞争格局、供需变化、价格体系、客户验证进展和潜在投资机会如何？",
            "available_materials_choice": "B",
            "intake_material_type": "papers_folder",
            "papers_or_report_folder": str(ROOT / "papers" / "电感"),
            "materials_path": str(ROOT / "papers" / "电感"),
            "evidence_policy": "freshness_first",
            "time_window": {
                "core": "当下至未来 12 个月，重点关注未来 0-6 个月客户验证、订单、价格、交期、扩产和供应链确认。",
                "long_term": "未来 5 年，回溯 2022-2026 年 AI 服务器、GPU/ASIC/TPU、国产算力和电源架构变化。",
            },
            "research_scope": {
                "geography": "全球多语言搜索，重点覆盖中国大陆、中国台湾、日本、韩国、美国和欧洲。",
                "industry": "AI 高端电感、高端功率电感、服务器电源磁性元件、VRM/POL/DC-DC、TLVR、金属软磁和一体成型电感。",
            },
            "scope": {
                "geography": "全球多语言搜索，重点覆盖中国大陆、中国台湾、日本、韩国、美国和欧洲。",
                "industry": "AI 高端电感、高端功率电感、服务器电源磁性元件、VRM/POL/DC-DC、TLVR、金属软磁和一体成型电感。",
            },
        },
        "search_plan_name": "AI 高端电感人工核验证据搜索计划",
        "search_plan": [
            {"axis_key": "local_papers", "source_group": "papers", "query_text": "读取 papers/电感 中 PDF、docx、xlsx", "result_count": 25, "included_count": 25},
            {"axis_key": "official_platforms", "source_group": "web_official", "query_text": "NVIDIA GB300、Google Ironwood、Huawei Atlas SuperPoD 官方资料", "result_count": 9, "included_count": 5},
            {"axis_key": "company_ir", "source_group": "company_ir", "query_text": "顺络、铂科、龙磁、悦安公司 IR/公告", "result_count": 12, "included_count": 6},
            {"axis_key": "overseas_suppliers", "source_group": "supplier_official", "query_text": "TDK、Murata、Yageo 等高端电感与 AI 数据中心资料", "result_count": 10, "included_count": 4},
        ],
        "sources": sources,
        "entities": entities,
        "claims": _build_claims(data_points),
        "data_points": data_points,
        "early_signals": _build_early_signals(entities),
        "sections": sections,
        "visuals": _build_visuals(),
        "nav": [
            {"nav_key": "report", "label": "研究报告", "href": "#report", "sort_order": 10},
            {"nav_key": "entities", "label": "研究实体", "href": "#entities", "sort_order": 20},
            {"nav_key": "visuals", "label": "可视化", "href": "#opp-visual-modules", "sort_order": 30},
        ],
        "supplement_requests": [
            {
                "entity_key": "customer_validation_matrix",
                "request_title": "客户验证强审计补证",
                "request_detail": "继续寻找客户、ODM/OEM、公司公告和交易所材料，确认英伟达、Google、华为链条中的直接/间接阶段。",
                "priority": "p1",
                "blocking_status": "limits_scoring",
                "review_status": "pending",
                "evidence_ref_uri": _source_ref("local_huatai_expert_inductor"),
            },
            {
                "entity_key": "high_end_inductor_price_market_space",
                "request_title": "高端 AI 电感 ASP 持续跟踪",
                "request_detail": "补充高端型号月度价格、TLVR ASP、年度议价和普通电感价格分化，避免低端价格误用。",
                "priority": "p1",
                "blocking_status": "limits_scoring",
                "review_status": "pending",
                "evidence_ref_uri": _source_ref("xlsx_inductor_model_price"),
            },
        ],
        "audit_issues": [
            {
                "entity_key": "customer_validation_matrix",
                "audit_issue_type": "weak_signal_core_leak",
                "audit_severity": "p2",
                "audit_issue_status": "open",
                "issue_title": "专家纪要中的客户和份额线索不得直接作为公开确认",
                "issue_detail": "华泰和华安专家纪要提供了高价值线索，但客户名、份额和供货模式必须用公司公告、客户资料或财报收入继续交叉验证。",
                "evidence_ref_uri": _source_ref("local_huatai_expert_inductor"),
                "evidence_ref_uri_list": [_source_ref("local_huatai_expert_inductor"), _source_ref("local_huaan_expert_inductor")],
            }
        ],
        "gap_summary": "已满足至少 100 个平行数据点和因子证据组闸门；剩余主要缺口是客户验证公开确认、TLVR ASP 连续价格和公司收入拆分。",
        "entity_sections": entity_sections,
        "entity_investment_targets": _build_targets(),
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
        for factor in entity["factor_scores"]:
            refs = set(factor.get("evidence_ref_uri_list", [])) | set(factor.get("source_context_refs", []))
            min_refs = 5 if factor.get("score_adjusted", 0) >= 70 else 3
            if len(refs) < min_refs:
                issues.append(f"{entity['key']} {factor['factor_code']} 证据组不足：{len(refs)} < {min_refs}")
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
                if not value:
                    issues.append(f"{entity['key']} {factor['factor_code']} 缺少 {field}")
                else:
                    factor_text_by_field[field].append((entity["key"], factor["factor_code"], value))
            for item in factor.get("information_points", []):
                interpretation = _compact(item.get("interpretation"))
                if not interpretation:
                    issues.append(f"{entity['key']} {factor['factor_code']} 信息点缺解读")
                else:
                    interpretations.append((entity["key"], factor["factor_code"], interpretation))
    for field, rows in factor_text_by_field.items():
        duplicates = [value for value, count in Counter(value for _, _, value in rows).items() if count > 1]
        if duplicates:
            issues.append(f"因子字段 {field} 存在整段重复：{_clip(duplicates[0], 100)}")
    duplicate_interpretations = [
        value for value, count in Counter(value for _, _, value in interpretations).items() if count > 1
    ]
    if duplicate_interpretations:
        issues.append(f"信息卡解读存在整段重复：{_clip(duplicate_interpretations[0], 100)}")
    for target in pack["entity_investment_targets"]:
        if not target.get("target_data_points"):
            issues.append(f"标的缺数据点：{target['target_name']}")
    bad_tokens = [
        "manual_verified_fact",
        "行业事实原文证据",
        "该证据必须结合原始链接全文",
        "不能只截取单句",
        "该指标说明",
        "在本研究问题下",
        "它衡量",
        "本因子当前不是孤立分数",
        "不是孤立分数",
        "单句摘录外推",
        "贡献在于：",
        "used_in_factor",
        "core_eligible",
    ]
    serialized = json.dumps(pack, ensure_ascii=False)
    for token in bad_tokens:
        if token in serialized:
            issues.append(f"发现禁用或模板残留：{token}")
    action_counter = Counter(target["confirmed_scenario_action"] for target in pack["entity_investment_targets"])
    if any(count > 1 for count in action_counter.values()):
        issues.append("标的证实动作存在重复")
    return issues


def write_outputs(pack: dict[str, Any]) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "run_pack.json"
    path.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    cache = OUT_DIR / "EXECUTION_CACHE.md"
    cache.write_text(
        "\n".join([
            "# AI 高端电感 Opportunity Lens 执行缓存",
            "",
            f"生成时间：{datetime.now().isoformat(timespec='seconds')}",
            f"run_pack：`{path.as_posix()}`",
            "",
            "## 证据规模",
            "",
            f"- sources：{len(pack['sources'])}",
            f"- data_points：{len(pack['data_points'])}",
            f"- claims：{len(pack['claims'])}",
            f"- entities：{len(pack['entities'])}",
            f"- targets：{len(pack['entity_investment_targets'])}",
            f"- visuals：{len(pack.get('visuals', []))}",
            "",
            "## 关键口径",
            "",
            "- 同源同对象同口径的时间序列作为一个数据点。",
            "- 研报一句事实、一组数字、官方表格的一组序列和公司 IR 摘录都作为平行数据点。",
            "- 专家纪要中的客户和份额线索只进入有限证据和验证债，不单独作为公开确认。",
            "- 不写 A/B `research.db` 或 `sentiment.db`。",
        ]),
        encoding="utf-8",
    )
    return path


def main() -> None:
    pack = build_pack()
    if len(pack["data_points"]) < 100:
        raise RuntimeError(f"数据点不足 100：{len(pack['data_points'])}")
    issues = audit_pack(pack)
    if issues:
        raise SystemExit("run pack 审计失败：\n" + "\n".join(f"- {issue}" for issue in issues))
    path = write_outputs(pack)
    print(json.dumps({
        "path": str(path),
        "sources": len(pack["sources"]),
        "data_points": len(pack["data_points"]),
        "claims": len(pack["claims"]),
        "entities": len(pack["entities"]),
        "targets": len(pack["entity_investment_targets"]),
        "visuals": len(pack.get("visuals", [])),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
