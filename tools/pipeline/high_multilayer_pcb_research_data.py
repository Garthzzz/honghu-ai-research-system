#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""高多层PCB板 B 轨研究的事实、口径与公司边界定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TODAY = "2026-07-11"


@dataclass(frozen=True)
class SourceSpec:
    key: str
    title: str
    source_type: str
    publisher: str
    publish_date: str
    quality_tier: int
    value_layer: str
    note: str
    file_path: str | None = None
    url: str | None = None
    text_path: str | None = None
    source_subtype: str = ""
    primary: int = 0
    credibility: str = "unverified"
    language: str = "zh"
    forward: int = 0
    arguments: tuple[tuple[str, str, str], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CompanySpec:
    key: str
    name: str
    ticker: str | None
    market: str
    listing_status: str
    classification: str
    role: str
    evidence_status: str
    source_key: str
    intro: str
    products: str
    customers: str
    capability: str
    recent: str
    risks: str
    conclusion: str
    listed_key: str | None = None


def _args(*rows: tuple[str, str, str]) -> tuple[tuple[str, str, str], ...]:
    return rows


SOURCES: tuple[SourceSpec, ...] = (
    SourceSpec(
        "prompt", "高多层PCB板（18层以上）行业研究 Prompt", "其他", "用户提供", TODAY, 1,
        "深度框架", "B轨用户prompt；要求是prompt全集与A轨默认全集的并集。",
        file_path="高多层PCB板.md", source_subtype="user_prompt", primary=1,
        credibility="user_supplied", arguments=_args(
            ("研究主体限定为18层以上高多层PCB板，并要求与多层板、高端PCB、HDI分开。", "中性", "研究边界"),
            ("要求覆盖2025-2030市场、竞争、供需、技术、公司财务与三情景。", "中性", "交付约束"),
        ),
    ),
    SourceSpec(
        "corpus_index", "高多层板PCB板研报库全文抽取索引", "其他", "本地研究库", TODAY, 2,
        "双层", "273份PDF、5,972页全部完成文本抽取；索引用于查重、口径冲突与原文定位，不作为一手事实本身。",
        file_path="cache/high_multilayer_pcb_research/pdf_extraction_index.json", source_subtype="corpus_index",
        credibility="auditable_local_index", arguments=_args(
            ("本轮扫描273份PDF，18层、22层、32层等口径出现频率显著不同。", "中性", "证据覆盖"),
        ),
    ),
    SourceSpec(
        "ipc_6012f", "IPC-6012F: Qualification and Performance Specification for Rigid Printed Boards", "协会数据", "IPC", "2023-10-09", 1,
        "深度框架", "刚性板资格与性能规范；用于可靠性边界，不用于定义18层门槛。",
        file_path="cache/high_multilayer_pcb_research/official_sources/ipc_6012f_toc.pdf",
        url="https://www.ipc.org/TOC/IPC-6012F.pdf", text_path="cache/high_multilayer_pcb_research/official_source_text/ipc_6012f_toc.txt",
        source_subtype="industry_standard", primary=1, credibility="official", language="en",
        arguments=_args(("IPC-6012F覆盖刚性板PTH、盲埋孔、微孔、铜包覆、微切片及介质厚度等验收。", "中性", "技术规范")),
    ),
    SourceSpec(
        "ipc_6012f_release", "IPC Releases Revision F of IPC-6012", "协会数据", "IPC", "2023-10-09", 1,
        "深度框架", "IPC官方版本说明，解释新修订覆盖cavity、copper wrap、microsection等内容。",
        file_path="cache/high_multilayer_pcb_research/official_sources/ipc_6012f_release.html",
        url="https://www.ipc.org/news-release/ipc-releases-revision-f-ipc-6012-qualification-and-performance-specification-rigid",
        text_path="cache/high_multilayer_pcb_research/official_source_text/ipc_6012f_release.txt", source_subtype="standard_release",
        primary=1, credibility="official", language="en",
    ),
    SourceSpec(
        "ipc_microvia", "IPC Issues Warning on Microvia Reliability for High Performance Products", "协会数据", "IPC", "2019-03-04", 1,
        "深度框架", "微孔潜在失效与传统检验局限；旧资料仅用于技术机理，不作当前订单证据。",
        file_path="cache/high_multilayer_pcb_research/official_sources/ipc_microvia_warning.html",
        url="https://www.ipc.org/news-release/ipc-issues-warning-microvia-reliability-high-performance-products",
        text_path="cache/high_multilayer_pcb_research/official_source_text/ipc_microvia_warning.txt", source_subtype="technical_warning",
        primary=1, credibility="official", language="en",
    ),
    SourceSpec(
        "wus_hk_industry", "WUS Printed Circuit H股申请材料：Industry Overview", "招股书", "WUS / HKEX / CIC", "2026-06-05", 1,
        "双层", "最新MLPCB分层市场、应用和竞争格局；CIC为发行人委聘顾问，须标利益关系。",
        file_path="cache/high_multilayer_pcb_research/official_sources/wus_hkex_industry.pdf",
        url="https://www1.hkexnews.hk/app/sehk/2026/108618/2026060502606.htm",
        text_path="cache/high_multilayer_pcb_research/official_source_text/wus_hkex_industry.txt", source_subtype="listing_application_industry",
        primary=1, credibility="regulatory_filing_commissioned_study", language="en", forward=1,
        arguments=_args(
            ("2025年MLPCB市场332亿美元，2030E为486亿美元。", "看涨", "市场规模"),
            ("2025年22层以上市场49亿美元，2030E为131亿美元；32+增速更快。", "看涨", "层数结构"),
            ("2025年22层以上CR5为62.3%，沪电份额14.9%。", "中性", "竞争格局"),
        ),
    ),
    SourceSpec(
        "wus_hk_business", "WUS Printed Circuit H股申请材料：Business", "招股书", "WUS / HKEX", "2026-06-05", 1,
        "公司专项", "沪电产品层数、材料、量产结构、客户认证、产能和良率官方申报材料。",
        file_path="cache/high_multilayer_pcb_research/official_sources/wus_hkex_business.pdf",
        url="https://www1.hkexnews.hk/app/sehk/2026/108618/2026060502606.htm",
        text_path="cache/high_multilayer_pcb_research/official_source_text/wus_hkex_business.txt", source_subtype="listing_application_business",
        primary=1, credibility="regulatory_filing", language="en",
        arguments=_args(
            ("量产44层N+N与54层N+M PCB，具备100层以上PCB能力和10阶HDI认证技术。", "看涨", "技术能力"),
            ("22-30层使用M7+，32+使用M8+并服务AI、ASIC及高速交换。", "中性", "产品映射"),
        ),
    ),
    SourceSpec(
        "wus_hk_financial", "WUS Printed Circuit H股申请材料：Financial Information", "招股书", "WUS / HKEX", "2026-06-05", 1,
        "公司专项", "沪电按层数收入、面积、ASP、客户集中度和财务数据。",
        file_path="cache/high_multilayer_pcb_research/official_sources/wus_hkex_financial.pdf",
        url="https://www1.hkexnews.hk/app/sehk/2026/108618/2026060502606.htm",
        text_path="cache/high_multilayer_pcb_research/official_source_text/wus_hkex_financial.txt", source_subtype="listing_application_financial",
        primary=1, credibility="regulatory_filing", language="en",
    ),
    SourceSpec(
        "wus_annual", "沪电股份2025年年度报告", "公告", "沪电股份", "2026-03-25", 1,
        "公司专项", "18层以上区域产值、经营财务、产品和风险的公司公告。",
        file_path="papers/高多层板PCB板研报/沪电股份.pdf",
        text_path="cache/high_multilayer_pcb_research/extracted_text/aaac8854f1eaeced.txt", source_subtype="annual_report",
        primary=1, credibility="official",
    ),
    SourceSpec(
        "victory_annual", "胜宏科技2025年年度报告", "公告", "胜宏科技", "2026-03-13", 1,
        "公司专项", "公司财务、技术能力、研发、产能与风险。",
        file_path="papers/高多层板PCB板研报/胜宏科技.pdf",
        text_path="cache/high_multilayer_pcb_research/extracted_text/532a53c1830aa737.txt", source_subtype="annual_report",
        primary=1, credibility="official",
    ),
    SourceSpec(
        "victory_hk", "Victory Giant Technology H股申请材料", "招股书", "Victory Giant / HKEX / Frost & Sullivan", "2026-04-13", 1,
        "双层", "14+市场、技术能力、产能与收购；F&S为委聘研究，需与CIC口径交叉。",
        url="https://www.hkexnews.hk/listedco/listconews/sehk/2026/0413/2026041300005.pdf",
        source_subtype="listing_application", primary=1, credibility="regulatory_filing_commissioned_study", language="en", forward=1,
        arguments=_args(
            ("公司披露70层以上量产、100层以上技术能力，两者状态不同。", "看涨", "技术能力"),
            ("14+ HLC名义产能516万平方米，6+N+6 HDI名义产能60万平方米。", "看涨", "产能"),
        ),
    ),
    SourceSpec(
        "shennan_annual", "深南电路2025年年度报告", "公告", "深南电路", "2026-03-13", 1,
        "公司专项", "PCB、封装基板和装联分部、技术能力、产能和财务。",
        file_path="papers/高多层板PCB板研报/深南电路.pdf",
        text_path="cache/high_multilayer_pcb_research/extracted_text/d0d9fc654e946b6a.txt", source_subtype="annual_report", primary=1, credibility="official",
    ),
    SourceSpec(
        "kinwong_annual", "景旺电子2025年年度报告", "公告", "景旺电子", "2026-03-31", 1,
        "公司专项", "HLC/HDI定义、M7-M9材料、客户认证、项目产能与财务。",
        file_path="papers/高多层板PCB板研报/景旺电子.pdf",
        text_path="cache/high_multilayer_pcb_research/extracted_text/bd0353fccfb35496.txt", source_subtype="annual_report", primary=1, credibility="official",
    ),
    SourceSpec(
        "dongshan_annual", "东山精密2025年年度报告", "公告", "东山精密", "2026-04-24", 1,
        "公司专项", "Multek能力、集团业务混合、财务与扩产。",
        file_path="papers/高多层板PCB板研报/东山精密.pdf",
        text_path="cache/high_multilayer_pcb_research/extracted_text/dd8267e468f273fc.txt", source_subtype="annual_report", primary=1, credibility="official",
    ),
    SourceSpec(
        "suntak_annual", "崇达技术2025年年度报告", "公告", "崇达技术", "2026-04-25", 1,
        "公司专项", "68层量产、珠海HLC产能、产品结构和财务。",
        file_path="papers/高多层板PCB板研报/崇达技术.pdf",
        text_path="cache/high_multilayer_pcb_research/extracted_text/461702b99ef52720.txt", source_subtype="annual_report", primary=1, credibility="official",
    ),
    SourceSpec(
        "founder_annual", "方正科技2025年年度报告", "公告", "方正科技", "2026-04-18", 1,
        "公司专项", "40层以上量产、UHD认证、PCB经营和财务。",
        file_path="papers/高多层板PCB板研报/方正科技.pdf",
        text_path="cache/high_multilayer_pcb_research/extracted_text/8eb9aff3c55d8d91.txt", source_subtype="annual_report", primary=1, credibility="official",
    ),
    SourceSpec(
        "avary_annual", "鹏鼎控股2025年年度报告", "公告", "鹏鼎控股", "2026-03-31", 1,
        "公司专项", "FPC底盘、HLC/HDI迁移、云客户认证和财务。",
        file_path="papers/高多层板PCB板研报/鹏鼎控股.pdf",
        text_path="cache/high_multilayer_pcb_research/extracted_text/b48f5423eec6412f.txt", source_subtype="annual_report", primary=1, credibility="official",
    ),
    SourceSpec(
        "olympic_annual", "世运电路2025年年度报告", "公告", "世运电路", "2026-04-28", 1,
        "公司专项", "汽车PCB底盘、AI服务器板、嵌入式PCB和财务。",
        file_path="papers/高多层板PCB板研报/世运电路.pdf",
        text_path="cache/high_multilayer_pcb_research/extracted_text/837ad4c7da932ee0.txt", source_subtype="annual_report", primary=1, credibility="official",
    ),
    SourceSpec(
        "goldman_ai_pcb", "全球PCB：AI PCB/CCL市场规模与供需模型", "卖方深度", "高盛", "2026-01-06", 2,
        "主题专项", "AI服务器板型、材料、层数、面积、ASP、产能利用率和良率模型；极强增长假设需降权。",
        file_path="papers/高多层板PCB板研报/20260106-高盛-全球PCB：推出市场规模预测；2025_27年AIPCBCCL市场规模年均复合增140％179％；迈向M9 CCL30+层PCB6LHDI.pdf",
        text_path="cache/high_multilayer_pcb_research/extracted_text/fe26ba50737cf4f7.txt", source_subtype="sell_side_model", credibility="institutional_research", forward=1,
        arguments=_args(
            ("AI服务器PCB TAM由2025E 47.06亿美元升至2027E 271.22亿美元，属于高弹性卖方情景。", "看涨", "AI需求"),
            ("2027E 30层以上MLPCB价值量67.52亿美元，价值增速明显快于面积。", "看涨", "层数结构"),
        ),
    ),
    SourceSpec(
        "changjiang_ai_pcb", "AI需求加速增长，PCB升级机遇显著", "卖方深度", "长江证券", "2026-04-01", 2,
        "主题专项", "Prismark 18+区域市场、AI PCB技术和公司比较的卖方研究。",
        file_path="papers/高多层板PCB板研报/20260401-长江证券-电子行业：AI需求加速增长，PCB升级机遇显著.pdf",
        text_path="cache/high_multilayer_pcb_research/extracted_text/848feff1623159f5.txt", source_subtype="sell_side_industry", credibility="institutional_research", forward=1,
    ),
    SourceSpec(
        "citic_ai_pcb", "AI PCB需求放量、高阶升级趋势明确，打开设备耗材新空间", "卖方深度", "中信建投", "2026-07-07", 2,
        "主题专项", "设备、耗材与高阶PCB扩产链条；用于近端行业研究，不替代公司公告。",
        file_path="papers/高多层板PCB板研报/20260707-中信建投-PCB行业：AI PCB需求放量、高阶升级趋势明确，打开设备耗材新空间.pdf",
        text_path="cache/high_multilayer_pcb_research/extracted_text/4ac2dc6d07171acb.txt", source_subtype="sell_side_industry", credibility="institutional_research", forward=1,
    ),
    SourceSpec(
        "trendforce_rubin", "NVIDIA Rubin Platform Drives Major PCB Design and Material Upgrades", "三方数据", "TrendForce", "2025-11-18", 2,
        "主题专项", "Rubin平台板型、层数、材料与价值量预测；独立行业研究但仍属前瞻。",
        file_path="cache/high_multilayer_pcb_research/official_sources/trendforce_rubin_pcb.html",
        url="https://www.trendforce.com/presscenter/news/20251118-12808.html",
        text_path="cache/high_multilayer_pcb_research/official_source_text/trendforce_rubin_pcb.txt", source_subtype="industry_research",
        credibility="recognized_industry_research", language="en", forward=1,
    ),
    SourceSpec(
        "trendforce_server", "Global Server Shipments Expected to Grow 12.8% in 2026", "三方数据", "TrendForce", "2026-01-20", 2,
        "最新数据", "全球服务器、AI服务器和ASIC结构预测。",
        file_path="cache/high_multilayer_pcb_research/official_sources/trendforce_server_2026.html",
        url="https://www.trendforce.com/presscenter/news/20260120-12888.html",
        text_path="cache/high_multilayer_pcb_research/official_source_text/trendforce_server_2026.txt", source_subtype="industry_forecast",
        credibility="recognized_industry_research", language="en", forward=1,
    ),
    SourceSpec(
        "panasonic_m8", "MEGTRON 8 Low-Loss Multi-Layer Circuit Board Material", "website_material", "Panasonic Industry", "2024-05-28", 1,
        "深度框架", "M8低损耗材料官方产品与测试说明。",
        file_path="cache/high_multilayer_pcb_research/official_sources/panasonic_megtron8.html",
        url="https://industrial.panasonic.com/ww/products/pt/megtron/megtron8",
        text_path="cache/high_multilayer_pcb_research/official_source_text/panasonic_megtron8.txt", source_subtype="official_product",
        primary=1, credibility="official", language="en",
    ),
    SourceSpec(
        "atotech_polygon", "Polygon XXL for Advanced Through-Hole Metallization", "website_material", "MKS Atotech", "2026-01-01", 1,
        "深度框架", "高纵横比、超厚大板通孔电镀官方工艺参数。",
        file_path="cache/high_multilayer_pcb_research/official_sources/atotech_polygon_xxl.html",
        url="https://www.atotech.com/products/electronics/through-hole-metallization/polygon-xxl/",
        text_path="cache/high_multilayer_pcb_research/official_source_text/atotech_polygon_xxl.txt", source_subtype="official_product",
        primary=1, credibility="official", language="en",
    ),
    SourceSpec(
        "atotech_printoganth", "Printoganth U Plus for HDI and Any-Layer PCBs", "website_material", "MKS Atotech", "2026-01-01", 1,
        "深度框架", "高层数any-layer/ELIC化学铜工艺、装机与处理量参考。",
        file_path="cache/high_multilayer_pcb_research/official_sources/atotech_printoganth.html",
        url="https://www.atotech.com/products/electronics/through-hole-metallization/printoganth-u-plus/",
        text_path="cache/high_multilayer_pcb_research/official_source_text/atotech_printoganth.txt", source_subtype="official_product",
        primary=1, credibility="official", language="en",
    ),
    SourceSpec(
        "broadcom_tomahawk6", "Broadcom Tomahawk 6 102.4 Tbps Ethernet Switch", "website_material", "Broadcom", "2025-06-03", 1,
        "深度框架", "交换芯片吞吐和SerDes速率的一手架构锚点。",
        file_path="cache/high_multilayer_pcb_research/official_sources/broadcom_tomahawk6.html",
        url="https://investors.broadcom.com/news-releases/news-release-details/broadcom-delivers-tomahawk-6-worlds-first-1024-tbps-ethernet",
        text_path="cache/high_multilayer_pcb_research/official_source_text/broadcom_tomahawk6.txt", source_subtype="official_product_release",
        primary=1, credibility="official", language="en",
    ),
    SourceSpec(
        "mks_10k", "MKS Inc. Form 10-K 2025", "公告", "MKS / SEC", "2026-02-27", 1,
        "双层", "PCB化学、电镀和设备需求、AI服务器层数趋势及周期风险。",
        file_path="cache/high_multilayer_pcb_research/official_sources/mks_2025_10k.html",
        url="https://www.sec.gov/Archives/edgar/data/1049502/000104950226000013/mksi-20251231.htm",
        text_path="cache/high_multilayer_pcb_research/official_source_text/mks_2025_10k.txt", source_subtype="annual_report",
        primary=1, credibility="official", language="en",
    ),
    SourceSpec(
        "ttm_10k", "TTM Technologies Form 10-K 2025", "公告", "TTM / SEC", "2026-02-24", 1,
        "公司专项", "收入、数据中心占比、客户、工厂、层数与业务风险。",
        file_path="cache/high_multilayer_pcb_research/official_sources/ttm_2025_10k.html",
        url="https://www.sec.gov/Archives/edgar/data/1116942/000111694226000011/ttmi-20251229.htm",
        text_path="cache/high_multilayer_pcb_research/official_source_text/ttm_2025_10k.txt", source_subtype="annual_report",
        primary=1, credibility="official", language="en",
    ),
    SourceSpec(
        "ttm_product", "TTM Conventional PCB Capabilities", "website_material", "TTM Technologies", "2026-01-01", 1,
        "公司专项", "60+层、板厚、纵横比和大尺寸能力。",
        file_path="cache/high_multilayer_pcb_research/official_sources/ttm_conventional_pcb.html",
        url="https://www.ttm.com/en/solutions/conventional-pcb",
        text_path="cache/high_multilayer_pcb_research/official_source_text/ttm_conventional_pcb.txt", source_subtype="official_product",
        primary=1, credibility="official", language="en",
    ),
    SourceSpec(
        "sanmina_product", "Sanmina Advanced PCB Technology", "website_material", "Sanmina", "2026-01-01", 1,
        "公司专项", "70+层、35:1纵横比、大板和HDI工艺能力。",
        file_path="cache/high_multilayer_pcb_research/official_sources/sanmina_pcb_technology.html",
        url="https://www.sanmina.com/technology/printed-circuit-boards/",
        text_path="cache/high_multilayer_pcb_research/official_source_text/sanmina_pcb_technology.txt", source_subtype="official_product",
        primary=1, credibility="official", language="en",
    ),
    SourceSpec(
        "ats_product", "AT&S HLC and HDI PCB Portfolio 2025", "website_material", "AT&S", "2025-01-01", 1,
        "公司专项", "层数、积层、厚度、线宽线距与纵横比参数。",
        file_path="cache/high_multilayer_pcb_research/official_sources/ats_hlc_hdi_2025.pdf",
        text_path="cache/high_multilayer_pcb_research/official_source_text/ats_hlc_hdi_2025.txt", source_subtype="official_product",
        primary=1, credibility="official", language="en",
    ),
    SourceSpec(
        "ncab_annual", "NCAB Group Annual Report 2025", "公告", "NCAB Group", "2026-04-08", 1,
        "公司专项", "无自有工厂的工程/采购平台模式、合作工厂、质量交付和财务。",
        file_path="cache/high_multilayer_pcb_research/official_sources/ncab_2025_ar.pdf",
        url="https://www.ncabgroup.com/investors/reports-and-presentations/",
        text_path="cache/high_multilayer_pcb_research/official_source_text/ncab_2025_ar.txt", source_subtype="annual_report",
        primary=1, credibility="official", language="en",
    ),
    SourceSpec(
        "isu_official", "ISU Petasys Ultra-Multilayer PCB Business", "website_material", "ISU Group", "2026-01-01", 1,
        "公司专项", "韩国18+超高多层PCB直接参与者的官方产品和应用。",
        file_path="cache/high_multilayer_pcb_research/official_sources/isu_petasys.html",
        url="https://www.isu.co.kr/eng/business/it.jsp",
        text_path="cache/high_multilayer_pcb_research/official_source_text/isu_petasys.txt", source_subtype="official_company",
        primary=1, credibility="official", language="en",
    ),
    SourceSpec(
        "gce_ir_2026q1", "金像电子2026年6月11日法人说明会", "业绩说明会", "金像电子", "2026-06-11", 1,
        "最新数据", "2026Q1经营和56层MLB/30层HDI能力的公司官方材料。",
        url="https://www.gce.com.tw/file/%E6%B3%95%E8%AA%AA%E6%9C%8320260611%E4%B8%AD%E6%96%87%E7%89%88.pdf",
        source_subtype="investor_presentation", primary=1, credibility="official",
        arguments=_args(
            ("2026Q1营收193.13亿新台币、毛利率34.81%、税后净利34.84亿新台币。", "看涨", "财务"),
            ("官方能力图给出MLB 56层、HDI 30层。", "看涨", "技术能力"),
        ),
    ),
    SourceSpec(
        "gce_annual", "Gold Circuit Electronics 2024 Annual Report", "公告", "金像电子", "2025-12-02", 1,
        "公司专项", "服务器/网络产品、泰国基地和公司治理；2024资料只作历史基线。",
        file_path="cache/high_multilayer_pcb_research/official_sources/gold_circuit_2024_ar.pdf",
        url="https://www.gce.com.tw/file/st/2024AnnualReport.pdf",
        text_path="cache/high_multilayer_pcb_research/official_source_text/gold_circuit_2024_ar.txt", source_subtype="annual_report",
        primary=1, credibility="official", language="en",
    ),
    SourceSpec(
        "gce_product", "Gold Circuit Electronics Product Applications", "website_material", "金像电子", "2026-07-01", 1,
        "公司专项", "AI/高阶服务器和网络设备的高多层、低损耗、阻抗控制应用。",
        url="https://www.gce.com.tw/product.html", source_subtype="official_product", primary=1, credibility="official",
    ),
    SourceSpec(
        "meiko_results", "Meiko FY2025 Financial Results Briefing", "业绩说明会", "Meiko Electronics", "2026-05-21", 1,
        "公司专项", "AI服务器Ultra High-Layer/High-Layer HDI产品与日本、中国、越南基地布局。",
        url="https://www.meiko-elec.com/english/pdf/ir/presentation/FY2025/H2.pdf", source_subtype="investor_presentation",
        primary=1, credibility="official", language="en",
    ),
    SourceSpec(
        "meiko_annual", "Meiko Annual Report 2025", "公告", "Meiko Electronics", "2025-11-01", 1,
        "公司专项", "PCB主业、区域收入和主要客户。",
        file_path="cache/high_multilayer_pcb_research/official_sources/meiko_2025_corporate_report.pdf",
        url="https://www.meiko-elec.com/english/pdf/ir/annual/ar2025.pdf",
        text_path="cache/high_multilayer_pcb_research/official_source_text/meiko_2025_corporate_report.txt", source_subtype="annual_report",
        primary=1, credibility="official", language="en",
    ),
    SourceSpec(
        "mirae_official", "MIRAE Corporation Company Overview", "website_material", "MIRAE Corporation", "2026-01-01", 1,
        "公司专项", "官方业务为半导体测试handler与SMT设备，用于纠正prompt误配。",
        url="https://www.mirae.com/en/sub/sub1.asp", source_subtype="official_company", primary=1, credibility="official", language="en",
        arguments=_args(("MIRAE核心业务为半导体Test Handler、SMT贴片和相关设备，不是高多层PCB制造。", "中性", "边界纠错")),
    ),
    SourceSpec(
        "cmk_product", "CMK High Layer Count PCB Products", "website_material", "CMK", "2026-01-01", 1,
        "公司专项", "汽车为主的HLC/HDI产品和公开层数边界。",
        file_path="cache/high_multilayer_pcb_research/official_sources/cmk_hlc.html",
        url="https://www.cmk-corp.com/en/product/hlc/", text_path="cache/high_multilayer_pcb_research/official_source_text/cmk_hlc.txt",
        source_subtype="official_product", primary=1, credibility="official", language="en",
    ),
    SourceSpec(
        "flexium_esg", "Flexium Interconnect 2022 ESG Report", "公告", "台郡科技", "2023-06-01", 1,
        "公司专项", "旧路线图显示以FPC和最高约12层flex为主；2024或更早仅作边界回测。",
        file_path="cache/high_multilayer_pcb_research/official_sources/flexium_2022_esg.pdf",
        text_path="cache/high_multilayer_pcb_research/official_source_text/flexium_2022_esg.txt", source_subtype="esg_report",
        primary=1, credibility="official", language="en",
    ),
    SourceSpec(
        "lg_innotek", "LG Innotek Investor Relations Product Portfolio", "website_material", "LG Innotek", "2026-01-01", 1,
        "公司专项", "以package substrate、RF-SiP等为主，用于排除宽口径误并入。",
        file_path="cache/high_multilayer_pcb_research/official_sources/lg_innotek_ir.html",
        url="https://www.lginnotek.com/ir/irReport.do", text_path="cache/high_multilayer_pcb_research/official_source_text/lg_innotek_ir.txt",
        source_subtype="official_company", primary=1, credibility="official", language="en",
    ),
    SourceSpec(
        "tushare_snapshot", "Tushare公司估值与财务快照（2026-07-10交易日）", "三方数据", "Tushare", "2026-07-10", 1,
        "最新数据", "A股daily_basic、income、fina_indicator、cashflow；Wind禁用。",
        file_path="cache/high_multilayer_pcb_research/market_snapshots_refresh.json", source_subtype="market_api",
        primary=1, credibility="structured_market_api",
    ),
    SourceSpec(
        "yfinance_snapshot", "Yahoo Finance/yfinance公司估值与财务快照", "三方数据", "Yahoo Finance / yfinance", "2026-07-11", 2,
        "最新数据", "海外公司行情、估值、年度/季度财务和汇率换算；缺失字段保留原因。",
        file_path="cache/high_multilayer_pcb_research/company_financial_series.json", source_subtype="market_api",
        credibility="structured_market_api", language="en",
    ),
)


def _c(
    key: str, name: str, ticker: str | None, market: str, listing: str, classification: str,
    role: str, evidence: str, source: str, intro: str, products: str, customers: str,
    capability: str, recent: str, risks: str, conclusion: str, listed_key: str | None = None,
) -> CompanySpec:
    return CompanySpec(key, name, ticker, market, listing, classification, role, evidence, source,
                       intro, products, customers, capability, recent, risks, conclusion, listed_key)


COMPANIES: tuple[CompanySpec, ...] = (
    _c("victory_giant", "胜宏科技", "300476.SZ", "A股", "a_share", "核心18+制造商", "AI服务器HLC/HDI核心制造商", "直接证据", "victory_hk",
       "高层数和高阶HDI同步放量，2025利润弹性已兑现。", "AI服务器、交换机、高多层、HDI、mSAP", "全球头部科技客户，名称未全部公开", "70层以上量产、100层以上技术；28层8+12+8 HDI量产", "海外并购与泰国基地扩大交付半径", "高估值、客户集中、原料与良率爬坡", "技术上限领先，但投资判断应看70+量产收入而不是100+能力宣传。", "victory_giant"),
    _c("suntak", "崇达技术", "002815.SZ", "A股", "a_share", "核心18+制造商", "HMLV与高层数扩产厂商", "直接证据", "suntak_annual",
       "小批量多品种底盘向AI服务器高层数延伸。", "HLC、HDI、通信和服务器PCB", "服务器和通信客户", "最高68层量产，珠海新增月产12万平方米HLC", "珠海二期和海外布局推进", "新增产能爬坡、利润率偏低、产品纯度不透明", "能力已进入60+，但高端合计收入不能替代18+业务收入。", "suntak"),
    _c("founder", "方正科技", "600601.SH", "A股", "a_share", "核心18+制造商", "高层数与UHD升级厂商", "直接证据", "founder_annual",
       "PCB主业完成重整后向40层以上和高阶UHD升级。", "高多层、UHD、高速通信PCB", "数据中心与通信客户", "40层及以上量产，高阶UHD认证并批量交付", "高端产品占比和珠海产能提升", "估值较高、历史治理、客户与产品集中", "40+量产是直接证据，盈利兑现仍需与扩产折旧一起看。", "founder"),
    _c("shengyi_electronics", "生益电子", "688183.SH", "A股", "a_share", "核心18+制造商", "服务器/通信PCB制造商", "部分直接", "changjiang_ai_pcb",
       "背靠生益科技材料协同，重点看AI服务器和交换机高层板。", "通信、服务器、高多层PCB", "通信和数据中心客户", "公开材料显示高层数、高速板能力，精确18+收入待补", "扩产与产品结构升级", "关联交易、客户集中、精确层数收入缺失", "材料协同有价值，但不能用PCB总收入代替18+收入。", "shengyi_electronics"),
    _c("wus", "沪电股份", "002463.SZ", "A股", "a_share", "核心18+制造商", "22+全球份额第一的高纯度制造商", "直接证据", "wus_hk_financial",
       "本轮公开资料中按层数收入、销量和ASP披露最完整。", "AI/HPC、交换机、路由器、汽车PCB", "全球头部数据通信与汽车客户", "44层N+N、54层N+M量产，100层以上能力", "泰国基地产能利用率提升，22+收入占比继续上行", "客户集中、材料成本、估值与新增供给", "59.4%的22+收入占比使其成为行业最可复算样本。", "wus"),
    _c("bomin", "博敏电子", "603936.SH", "A股", "a_share", "能力迁移者", "多品类PCB向高端板迁移", "验证债", "changjiang_ai_pcb",
       "产品面广但高多层业务纯度公开不足。", "多层、HDI、刚挠结合板", "通信、汽车、工控客户", "18+量产与收入占比待官方补证", "高端项目建设", "经营现金流为负、盈利承压、口径不透明", "先列观察项，不能凭行业报告中的高端标签进入核心份额。", "bomin"),
    _c("guanghe", "广合科技", "001389.SZ", "A股", "a_share", "核心18+制造商", "高纯度服务器PCB厂商", "直接证据", "wus_hk_industry",
       "服务器PCB约占收入八成，具较高业务纯度。", "AI服务器、高速交换机、光模块PCB", "全球服务器制造商和云基础设施客户", "开发50层AI服务器PCB、HDI最高7阶", "拟新增AI HDI/HLC年产11.15万平方米", "服务器周期、客户集中、扩产与认证", "业务纯度强，但50层开发状态不等于批量收入。", "guanghe"),
    _c("shennan", "深南电路", "002916.SZ", "A股", "a_share", "核心18+制造商", "通信/数据中心PCB平台型厂商", "直接证据", "shennan_annual",
       "PCB、封装基板和装联三线平台，需严格拆分口径。", "通信、数据中心、汽车PCB和封装基板", "通信、服务器、汽车和半导体客户", "68层量产、120层背板样品", "南通与泰国产能投产", "混合业务、载板爬坡、样品量产混淆风险", "68层量产可比，120层只代表研发边界。", "shennan"),
    _c("kinwong", "景旺电子", "603228.SH", "A股", "a_share", "核心18+制造商", "HLC/高阶HDI扩张厂商", "直接证据", "kinwong_annual",
       "多品类PCB中向AI基础设施高层数、M9和高阶HDI升级。", "HLC、HDI、FPC、光模块和汽车PCB", "AI基础设施、光模块、汽车客户", "20+定义HLC，M7-M9/PTFE量产，9阶HDI 90天认证", "HLC项目120万平方米，泰国基地推进", "新基地爬坡、混合产品结构、材料成本", "技术覆盖面宽，关键是M9和高阶HDI收入何时形成。", "kinwong"),
    _c("dongshan", "东山精密", "002384.SZ", "A股", "a_share", "核心18+制造商", "Multek高端PCB与光模块协同平台", "直接证据", "dongshan_annual",
       "Multek提供高层板能力，但集团含FPC、精密制造和光模块。", "高多层、HDI、FPC、光模块", "消费电子、汽车和AI数据中心客户", "自定义HLC为16+，Multek具78+能力及M8/M9加工", "高端PCB资本开支和光模块并表", "集团口径复杂、整合执行、资本开支", "技术能力进入70+，收入与利润必须剥离光模块和消费电子。", "dongshan"),
    _c("avary", "鹏鼎控股", "002938.SZ", "A股", "a_share", "能力迁移者", "FPC龙头向IHDI/HLC迁移", "直接边界", "avary_annual",
       "全球PCB规模大，但服务器HLC仍处客户认证阶段。", "FPC、SLP、HDI、服务器IHDI/HLC", "消费电子和云客户", "公司自定义HLC为10+，高阶HDI强，服务器HLC待认证", "淮安与泰国扩产", "消费电子底盘、认证延期、折旧与利用率", "不能用全球PCB第一的总盘地位替代18+既有份额。", "avary_cn"),
    _c("zhongfu", "中富电路", "300814.SZ", "A股", "a_share", "能力迁移者", "中小规模高端PCB观察厂商", "部分直接", "changjiang_ai_pcb",
       "具通信、工控和汽车PCB基础，高层数收入公开不足。", "多层、HDI、通信和汽车PCB", "通信、工控和汽车客户", "18+细分收入和最大量产层数待补", "海外与高端产品布局", "规模、客户集中、证据不足", "保留观察，不以概念映射替代技术和收入验证。", "zhongfu"),
    _c("wanyuantong", "万源通", "920060.BJ", "A股", "a_share", "能力迁移者", "中小批量PCB厂商", "验证债", "changjiang_ai_pcb",
       "北交所PCB厂商，高多层直接披露有限。", "多层PCB、通信和工控板", "通信、工控客户", "18+量产和收入占比待补", "募投扩产", "流动性、规模、验证不足", "不因prompt点名就进入核心供应排名。", "wanyuantong"),
    _c("olympic", "世运电路", "603920.SH", "A股", "a_share", "能力迁移者", "汽车PCB向AI服务器延伸", "直接证据", "olympic_annual",
       "汽车PCB现金流底盘较稳，AI服务器和嵌入式PCB提供增量。", "汽车PCB、28层AI服务器板、嵌入式PCB", "汽车、能源和数据中心客户", "28层AI服务器板、5阶HDI", "嵌入式PCB中试线和新项目", "AI收入纯度、项目爬坡、汽车周期", "当前是28层能力和跨场景协同，不是60+层竞争者。", "olympic"),
    _c("jinlu", "金禄电子", "301282.SZ", "A股", "a_share", "能力迁移者", "汽车PCB向服务器观察", "验证债", "changjiang_ai_pcb",
       "汽车电子PCB为主，高多层AI业务公开证据不足。", "汽车、多层PCB", "汽车电子客户", "18+量产和服务器认证待补", "高端产能建设", "行业切换、客户集中、规模", "作为横向补充公司，需先取得18+料号与客户认证。", "jinlu"),
    _c("aoshikang", "奥士康", "002913.SZ", "A股", "a_share", "能力迁移者", "多层板扩张厂商", "部分直接", "changjiang_ai_pcb",
       "传统多层板规模较大，AI高层产品信息需进一步拆分。", "多层、HDI、汽车和通信PCB", "通信、消费和汽车客户", "高层数能力有研报线索，18+业务占比待公告补证", "泰国和高端产能布局", "产品纯度、海外爬坡、客户周期", "规模不等于18+份额，暂列第二层观察。", "aoshikang"),
    _c("unimicron", "欣兴电子", "3037.TW", "其他", "tse", "邻接/混合", "PCB与封装基板综合厂商", "边界证据", "wus_hk_industry",
       "全球PCB大厂，但载板与HDI占比高。", "PCB、HDI、IC载板", "半导体与电子客户", "具高层板能力，18+业务口径未独立披露", "载板和海外产能投资", "业务混合、载板周期、18+纯度", "保留全球对照，但不以总营收排名18+。", "unimicron"),
    _c("zhen_ding", "臻鼎科技", "4958.TW", "其他", "tse", "邻接/混合", "全球综合PCB平台", "边界证据", "wus_hk_industry",
       "FPC、HDI、SLP和刚性板平台，业务口径复杂。", "FPC、HDI、SLP、刚性PCB", "消费电子和服务器客户", "高阶HDI强，18+刚性板收入待拆分", "AI和海外产能升级", "消费电子集中、混合口径", "总盘规模不能直接转换为18+份额。", "zhen_ding"),
    _c("compeq", "华通电脑", "2313.TW", "其他", "tse", "核心/混合", "服务器与通信高层PCB厂商", "部分直接", "wus_hk_industry",
       "服务器、通信与卫星板较强，需补18+精确收入。", "高多层、HDI、卫星与服务器PCB", "通信、服务器和低轨卫星客户", "高层数量产具行业证据，公开层数分拆不足", "泰国与AI产能布局", "客户集中、地缘、口径缺失", "属于重要全球玩家，但份额只用已披露口径。", "compeq"),
    _c("tripod", "健鼎科技", "3044.TW", "其他", "tse", "核心/混合", "服务器/汽车HLC厂商", "直接证据", "wus_hk_industry",
       "HLC和HDI服务器产品与汽车PCB并重。", "HLC、HDI、服务器、汽车PCB", "服务器、汽车和存储客户", "M7/M8+材料、30/30um研发；旧资料32层仅作历史", "2025资本开支59.6亿新台币", "产品混合、当前最大层数缺口", "财务稳健，但当前精确18+层数能力需最新产品表补证。", "tripod"),
    _c("nanya_pcb", "南亚电路板", "8046.TW", "其他", "tse", "排除主体", "封装基板邻接公司", "直接边界", "wus_hk_industry",
       "核心是IC载板而非服务器主板HLC。", "IC载板、部分PCB", "半导体客户", "封装基板能力不等同18+刚性主板", "载板周期恢复", "赛道误并、资本开支", "保留用户点名卡片，但排除18+市场份额。", "nanya_pcb"),
    _c("flexium", "台郡科技", "6269.TW", "其他", "tse", "排除主体", "FPC厂商", "直接边界", "flexium_esg",
       "以软板为主，不应因高阶电子标签并入刚性HLC。", "FPC、软硬结合", "消费电子客户", "旧路线图最高约12层flex", "向高频高速软板升级", "客户集中、FPC周期、口径误配", "不计入18+刚性板供给。", "flexium"),
    _c("gold_circuit", "金像电子", "2368.TW", "其他", "tse", "核心18+制造商", "AI服务器/网络HLC核心厂商", "直接证据", "gce_ir_2026q1",
       "2025-2026收入和利润加速，官方能力图补齐56层MLB。", "AI服务器、网络、通信高多层PCB", "服务器和网络客户", "MLB 56层、HDI 30层", "泰国基地与2026资本开支", "高景气估值、客户集中、扩产", "是台湾最清晰的AI HLC对照之一，2026Q1财务强。", "gold_circuit"),
    _c("ibiden", "揖斐电", "4062.T", "其他", "listed", "排除主体", "封装基板龙头", "直接边界", "wus_hk_industry",
       "先进封装基板相关度高，但不是本文18+主板供给。", "FC-BGA等封装基板", "先进逻辑客户", "载板工艺不等同HLC主板", "AI载板扩产", "赛道口径、资本开支", "作为相邻价值链对照，不进入HLC份额。", "ibiden"),
    _c("nok", "旗胜/NOK", "7240.T", "其他", "listed", "排除主体", "FPC集团", "直接边界", "flexium_esg",
       "MEKTEC以FPC为主，泰国基地不能自动计入HLC。", "FPC、汽车电子连接", "汽车和消费电子客户", "刚性18+能力缺乏直接证据", "东南亚基地运营", "FPC周期、赛道误配", "不计入18+核心产能。", "nok"),
    _c("meiko", "名幸电子", "6787.T", "其他", "listed", "核心18+制造商", "AI服务器高层板综合厂商", "直接证据", "meiko_results",
       "官方把Ultra High-Layer、High-Layer HDI和服务器板分配至多基地。", "服务器主板、OAM、交换板、高层HDI", "服务器、存储和电子客户", "Ultra High-Layer产品明确，当前最大量产层数未公开", "越南与武汉AI服务器产能配置", "层数上限缺口、客户周期、海外扩产", "比prompt写的“20层”更高阶，但不能凭图推最大层数。", "meiko"),
    _c("cmk", "CMK", "6958.T", "其他", "listed", "邻接/混合", "汽车HLC/HDI厂商", "直接边界", "cmk_product",
       "有HLC产品，但主业偏汽车且公开标准层数多在18层附近。", "汽车HLC、HDI、IVH", "汽车客户", "公开IVH/通孔能力约16-18层，存在18+边界交叉", "汽车电子升级", "汽车周期、AI相关度低", "纳入边界观察，不列AI HLC第一梯队。", "cmk"),
    _c("oki", "OKI", "6703.T", "其他", "listed", "子公司/邻接", "OKI Circuit Technology母公司", "验证债", "corpus_index",
       "prompt中的24层能力需回到子公司产品资料核验。", "通信与工业电子、PCB子公司", "工业和通信客户", "24层线索未获得当前官方独立确认", "集团业务调整", "母子公司口径、非PCB业务", "仅作待补证，不以OKI集团财务代表PCB。", "oki"),
    _c("kyocera", "京瓷", "6971.T", "其他", "listed", "排除主体", "陶瓷/电子元件综合集团", "边界证据", "corpus_index",
       "PCB相关业务不是集团独立主线。", "陶瓷、封装、电子元件", "工业和电子客户", "18+主板能力证据不足", "电子元件组合调整", "集团口径、赛道误配", "不进入18+制造商份额。", "kyocera"),
    _c("fujikura", "藤仓", "5803.T", "其他", "listed", "排除主体", "线缆/FPC综合厂商", "边界证据", "corpus_index",
       "高频互连相关，但刚性18+主板证据不足。", "线缆、FPC和电子部件", "通信和汽车客户", "18+刚性板未直接验证", "数据中心互连增长", "赛道误配、集团口径", "作为互连替代路线，不计HLC供给。", "fujikura"),
    _c("shinko", "新光电气", "6967.T", "其他", "listed", "排除主体", "封装基板公司", "直接边界", "wus_hk_industry",
       "先进封装相关，当前ticker已无有效行情。", "IC封装基板", "半导体客户", "载板不等同18+主板", "并购/退市进程", "当前估值不可得、赛道误配", "保留历史公司卡片，不生成当前估值。", "shinko"),
    _c("semco", "三星电机", "009150.KS", "其他", "kospi", "排除主体", "封装基板/电子元件集团", "直接边界", "lg_innotek",
       "prompt写50层缺少当前官方HLC主板证据。", "封装基板、MLCC、相机模组", "半导体和消费电子客户", "未验证50层刚性服务器主板", "高端载板和元件扩产", "赛道误并、集团业务", "不计入18+主板供给，50层标注为未证实。", "semco"),
    _c("isu_petasys", "ISU Petasys", "007660.KS", "其他", "kospi", "核心18+制造商", "韩国Ultra-multilayer PCB核心厂商", "直接证据", "isu_official",
       "官方直接把Ultra-multilayer定义为18层以上，应用覆盖服务器和超级计算。", "18+ MLB、通信、服务器、存储和航天PCB", "全球IT客户", "18+产品定义明确，最大量产层数待补", "2025收入和利润高速增长、扩产", "客户集中、资本开支、最大层数缺口", "是prompt韩国列表中最应补入的核心公司。", "isu_petasys"),
    _c("dap", "DAP", "066900.KQ", "其他", "listed", "能力迁移者", "韩国PCB厂商", "验证债", "corpus_index",
       "具PCB制造基础，AI 18+公开资料有限。", "多层PCB、移动和汽车板", "电子客户", "18+层数和收入待补", "产品结构调整", "规模小、证据不足", "保留观察，不进入核心排名。", "dap"),
    _c("lg_innotek", "LG Innotek", "011070.KS", "其他", "kospi", "排除主体", "封装基板/模组厂商", "直接边界", "lg_innotek",
       "公开产品组合以package substrate、RF-SiP和模组为主。", "封装基板、相机、电子部件", "消费电子和半导体客户", "未验证18+服务器主板供给", "高端基板和模组投资", "赛道误并、客户集中", "不计入18+主板市场。", "lg_innotek"),
    _c("mirae", "MIRAE Corporation（未来产业）", "025560.KS", "其他", "kospi", "prompt误配", "半导体后道设备厂商", "直接纠错", "mirae_official",
       "官方业务是测试handler与SMT设备，不是PCB制造。", "Test Handler、SMT Mounter、线性马达", "半导体制造客户", "无HLC制造能力", "半导体后道设备运营", "与本行业无直接供给关系", "从高多层制造商池剔除，并保留纠错记录。", "mirae"),
    _c("ttm", "TTM Technologies", "TTMI", "美股", "us", "核心18+制造商", "欧美高层复杂PCB基准", "直接证据", "ttm_10k",
       "数据中心计算占比持续上升，同时覆盖航空航天、医疗和汽车。", "高层刚性板、HDI、RF与系统集成", "约1300家客户，前十集中度55%", "日常30+，复杂板70+；官方60+层、0.450英寸和25:1以上", "美国和马来西亚投资", "客户集中、国防/商业混合、出口限制", "海外技术基准明确，但集团收入不能全算18+。", "ttm"),
    _c("sanmina", "Sanmina", "SANM", "美股", "us", "核心/混合", "70+层PCB与EMS平台", "直接证据", "sanmina_product",
       "技术能力强，但公司收入大部分是EMS与系统制造。", "70+层、高纵横比、大尺寸、HDI PCB", "通信、工业、医疗和云客户", "70+层、35:1、42英寸大板", "先进制造产能扩张", "EMS混合口径、客户周期", "技术对标有效，市场份额和收入纯度不可直接取得。", "sanmina"),
    _c("ats", "AT&S", "ATS.VI", "其他", "listed", "核心/混合", "欧洲HLC/HDI与载板厂商", "直接证据", "ats_product",
       "具38层HLC和6-N-6 HDI，但封装基板业务占比较高。", "HLC、HDI、IC载板", "汽车、工业、计算和半导体客户", "4-38层、6-N-6、40/40um、1:19", "马来西亚和高端产线爬坡", "高负债、载板周期、混合口径", "技术参数可比，财务需看新厂爬坡和现金流。", "ats"),
    _c("ncab", "NCAB Group", "NCAB.ST", "其他", "listed", "非制造平台", "HMLV工程与采购平台", "直接证据", "ncab_annual",
       "无自有工厂，通过34家合作工厂提供工程、采购和质量管理。", "多品类PCB采购与工程服务", "工业和专业电子客户", "能力由合作工厂提供，不能计入自有产能", "并购与合作工厂网络扩张", "供应商依赖、不能当制造份额", "适合研究渠道和客户粘性，不适合计入HLC供给。", "ncab"),
    _c("wuerth", "Würth Elektronik", None, "其他", "private", "私营/能力提供者", "欧洲PCB与电子元件供应商", "验证债", "corpus_index",
       "私营集团，公开独立财务和18+收入不可得。", "PCB、电子元件和工程服务", "工业电子客户", "高多层产品能力需按具体工厂补证", "欧洲制造服务", "财务不可得、私营口径", "展示产品角色，不生成伪估值或份额。"),
    _c("mfs", "MFS Technology", None, "其他", "private_subsidiary", "子公司/混合", "胜宏旗下FPC与海外制造平台", "直接边界", "victory_hk",
       "已被胜宏收购，主体以FPC和海外平台价值为主。", "FPC及相关PCB", "国际电子客户", "不能与胜宏HLC产能重复计算", "整合进胜宏全球布局", "重复统计、子公司财务不可得", "作为胜宏海外协同，不单列HLC份额。"),
    _c("mektec_thailand", "MEKTEC泰国基地", None, "其他", "private_subsidiary", "子公司/排除", "NOK旗下FPC基地", "直接边界", "flexium_esg",
       "泰国基地属于FPC体系，不因东南亚产地并入HLC。", "FPC", "汽车和电子客户", "18+刚性板无直接证据", "区域化生产", "重复统计、赛道误并", "只在区域供应链部分说明。"),
    _c("sea_cn_bases", "大陆PCB企业东南亚基地观察篮子", None, "其他", "unlisted", "产能观察篮子", "泰国/越南高端PCB产能集合", "组合证据", "victory_hk",
       "用于跟踪沪电、胜宏、景旺、鹏鼎、金像等东南亚项目，不是独立公司。", "海外HLC/HDI产能", "国际客户", "逐项目区分设计、有效与量产产能", "2025-2027集中爬坡", "重复统计、认证和良率", "只作地区产能路线，不计入公司数量和份额。"),
)


MLPCB_SERIES = {
    2021: (18.1, 9.0, 3.0, 0.4),
    2022: (18.1, 8.7, 2.9, 0.4),
    2023: (15.8, 7.7, 2.7, 0.7),
    2024: (16.1, 8.5, 2.9, 1.1),
    2025: (16.8, 11.5, 3.4, 1.5),
    2026: (17.1, 12.7, 5.0, 3.0),
    2027: (18.2, 13.8, 5.8, 3.6),
    2028: (18.8, 14.5, 6.6, 4.1),
    2029: (19.3, 15.3, 7.5, 4.5),
    2030: (19.7, 16.0, 8.2, 4.9),
}

REGIONAL_18_PLUS = {
    2025: {"美洲": 502, "欧洲": 73, "日本": 230, "中国大陆": 3046, "亚洲其他": 1077, "全球": 4928},
    2026: {"美洲": 552, "欧洲": 82, "日本": 270, "中国大陆": 5529, "亚洲其他": 1568, "全球": 8002},
}

WUS_LAYER_RECORDS = {
    "2023": {"32+收入": 7.61065, "32+占比": 8.5, "32+面积": 16095, "32+ASP": 47300,
             "22-30收入": 26.75294, "22-30占比": 29.9, "22-30面积": 147103, "22-30ASP": 18200},
    "2024": {"32+收入": 17.68206, "32+占比": 13.3, "32+面积": 32348, "32+ASP": 54700,
             "22-30收入": 53.31494, "22-30占比": 40.0, "22-30面积": 260637, "22-30ASP": 20500},
    "2025": {"32+收入": 42.49764, "32+占比": 22.4, "32+面积": 66220, "32+ASP": 64200,
             "22-30收入": 61.63209, "22-30占比": 32.5, "22-30面积": 278908, "22-30ASP": 22100},
    "2025Q1": {"32+收入": 6.47810, "32+占比": 16.0, "32+面积": 10644, "32+ASP": 60900,
               "22-30收入": 15.33490, "22-30占比": 38.0, "22-30面积": 71266, "22-30ASP": 21500},
    "2026Q1": {"32+收入": 19.93541, "32+占比": 32.1, "32+面积": 30233, "32+ASP": 65900,
               "22-30收入": 16.95039, "22-30占比": 27.3, "22-30面积": 71556, "22-30ASP": 23700},
}

TOP5_22_PLUS_2025 = (
    ("沪电股份", 724.8, 14.9),
    ("深南电路（由CIC匿名公司D描述映射）", 643.0, 13.2),
    ("TTM Technologies（由CIC匿名公司E描述映射）", 593.4, 12.2),
    ("胜宏科技（由CIC匿名公司F描述映射）", 541.5, 11.1),
    ("匿名公司J", 530.3, 10.9),
)

AI_PCB_TAM = {
    2024: {"总PCB": 3146, "MLPCB": 2024, "20层以下": 390, "20-30层": 1379, "30层以上": 255, "HDI": 1122},
    2025: {"总PCB": 4706, "MLPCB": 2812, "20层以下": 478, "20-30层": 1972, "30层以上": 361, "HDI": 1894},
    2026: {"总PCB": 10017, "MLPCB": 6228, "20层以下": 812, "20-30层": 4034, "30层以上": 1382, "HDI": 3789},
    2027: {"总PCB": 27122, "MLPCB": 17108, "20层以下": 1333, "20-30层": 9023, "30层以上": 6752, "HDI": 10014},
}

AI_PCB_AREA_ASP = {
    2024: {"MLPCB面积": 0.4, "HDI面积": 0.3, "MLPCB_ASP": 5648, "HDI_ASP": 3734},
    2025: {"MLPCB面积": 0.4, "HDI面积": 0.4, "MLPCB_ASP": 6725, "HDI_ASP": 4346},
    2026: {"MLPCB面积": 0.6, "HDI面积": 0.6, "MLPCB_ASP": 9910, "HDI_ASP": 5856},
    2027: {"MLPCB面积": 1.3, "HDI面积": 1.2, "MLPCB_ASP": 13250, "HDI_ASP": 8629},
}

TECH_MATRIX = (
    ("沪电股份", 54, "量产", "M9/FR-4混压", "N+N/N+M、10阶HDI认证", "wus_hk_business"),
    ("胜宏科技", 70, "量产", "M8/M9", "100+仅技术能力", "victory_hk"),
    ("深南电路", 68, "量产", "低损耗高速材料", "120层仅样品", "shennan_annual"),
    ("景旺电子", 40, "量产/公开下限", "M7-M9/PTFE", "9阶HDI已认证", "kinwong_annual"),
    ("方正科技", 40, "量产/公开下限", "高速低损耗", "UHD批量", "founder_annual"),
    ("崇达技术", 68, "量产", "高速材料", "珠海HLC扩产", "suntak_annual"),
    ("东山精密/Multek", 78, "能力", "M8/M9", "量产状态需逐料号验证", "dongshan_annual"),
    ("金像电子", 56, "技术能力", "高阶低损耗", "HDI 30层", "gce_ir_2026q1"),
    ("TTM Technologies", 70, "复杂板能力", "多种高频材料", "常规30+；官方60+", "ttm_10k"),
    ("Sanmina", 70, "技术能力", "高频/厚铜", "35:1、42英寸", "sanmina_product"),
    ("AT&S", 38, "产品能力", "高速材料", "6-N-6、40/40um", "ats_product"),
)
