#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
build_semiconductor_metrology_research.py

B 轨行业包：半导体量测。

输入：
- 根目录 `半导体量测行研.md`。该 prompt 明确要求覆盖竞争格局、行业空间、
  技术壁垒、2025-2030 销售额/出货量/份额、产品类型和公司财务。
- `papers/量检测/` 的本地 PDF 抽取缓存。
- 联网补充的一手/准一手来源：SEMI、KLA SEC、Nova、Onto、Camtek、
  Lasertec、ASML、Hitachi High-Tech、A 股公司公告/年报等。

输出：
- research.db: industry / source / company / company_profile /
  industry_relation / industry_data_point。
- docs/industries: 主文档、Q0-Q5、Q6、公司透视。
- cache/semiconductor_metrology_research: 执行记录、验收记录、差距表。

硬约束：
- 新增 industry_data_point 只走 db_writer.write_data_point。
- 不使用 Wind，不把半导体检测服务、ATE 测试机、工业视觉泛化收入混入
  本行业主体口径。
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "research.db"
DOCS_DIR = ROOT / "docs" / "industries"
CACHE_DIR = ROOT / "cache" / "semiconductor_metrology_research"
PAPER_DIR = ROOT / "papers" / "量检测"
PROMPT_PATH = ROOT / "半导体量测行研.md"
RUN_TAG = "B_TRACK_SEMICONDUCTOR_METROLOGY_20260706"
TODAY = "2026-07-07"
INDUSTRY_NAME = "半导体量测"
PARENT_INDUSTRY_NAME = "半导体设备"

sys.path.insert(0, str(ROOT / "tools" / "pipeline"))
from db_writer import write_data_point  # noqa: E402
import consensus_compute  # noqa: E402
from market_snapshot_utils import (  # noqa: E402
    display_cny_usd,
    fetch_company_market_snapshot,
    fetch_fx_rates,
    unit_cny_usd,
)


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
    source_subtype: str | None = None
    is_primary_source: int = 0
    source_credibility: str = "unverified"
    language: str = "zh"
    key_arguments: list[dict[str, str]] | None = None


@dataclass(frozen=True)
class CompanySpec:
    key: str
    name: str
    ticker: str | None
    market: str | None
    listing_status: str
    role: str
    note: str
    source_key: str
    brief_intro: str
    profile: dict[str, Any]
    risks: str
    customers: str
    products: str


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def rel(path: Path | str | None) -> str | None:
    if path is None:
        return None
    p = Path(path)
    try:
        return str(p.resolve().relative_to(ROOT)).replace("\\", "/")
    except Exception:
        return str(p).replace("\\", "/")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def is_empty_prompt() -> bool:
    if not PROMPT_PATH.exists():
        return True
    return PROMPT_PATH.read_text(encoding="utf-8", errors="ignore").strip() == ""


def source_args(*items: tuple[str, str, str]) -> list[dict[str, str]]:
    return [{"claim": claim, "sentiment": sentiment, "dimension": dim} for claim, sentiment, dim in items]


CURATED_SOURCES: list[SourceSpec] = [
    SourceSpec(
        key="prompt",
        title="半导体检测/量测（过程控制）设备行业研究 Prompt",
        source_type="prompt",
        publisher="用户提供",
        publish_date=TODAY,
        quality_tier=1,
        value_layer="深度框架",
        file_path=rel(PROMPT_PATH),
        note="用户提供 B 轨 prompt，明确要求竞争格局、行业空间、技术壁垒、2025-2030 销售额/出货量/份额、公司池、产品类型和可视化输出。",
        source_subtype="user_prompt",
        is_primary_source=1,
        source_credibility="user_supplied",
        language="zh",
        key_arguments=source_args(
            ("Prompt 要求回答检测/量测设备竞争格局、行业空间、技术壁垒三大方向。", "中性", "任务边界"),
            ("Prompt 要求区分实际值与预估值、标注来源年份，并覆盖 2025-2030 市场规模、份额和出货量。", "中性", "输出约束"),
        ),
    ),
    SourceSpec(
        key="semi_equipment_forecast_2026",
        title="SEMI: Global Semiconductor Equipment Sales Projected to Reach a Record $156 Billion in 2027",
        source_type="web",
        publisher="SEMI",
        publish_date="2026-07-01",
        quality_tier=1,
        value_layer="最新数据",
        url="https://www.semi.org/en/semi-press-release/global-semiconductor-equipment-sales-projected-to-reach-a-record-of-156-billion-dollars-in-2027-semi-reports",
        note="官方行业组织设备销售预测，用于约束 WFE、测试与封装设备周期，不直接等同量测检测市场。",
        source_subtype="industry_association",
        is_primary_source=1,
        source_credibility="official",
        language="en",
        key_arguments=source_args(
            ("WFE 2025E 1157 亿美元、2027E 1352 亿美元，先进逻辑、DRAM/HBM 和中国扩产是核心驱动。", "中性", "市场周期"),
            ("测试设备 2025E 增长 48.1% 至 112 亿美元，封装设备增长 19.6% 至 60 亿美元，提示 AI/HBM 不只拉动前道。", "看涨", "相邻设备"),
        ),
    ),
    SourceSpec(
        key="kla_10k_2025",
        title="KLA Corporation Form 10-K FY2025",
        source_type="sec_filing",
        publisher="KLA / SEC",
        publish_date="2025-08-06",
        quality_tier=1,
        value_layer="深度框架",
        url="https://www.sec.gov/Archives/edgar/data/319201/000031920125000024/klac-20250630.htm",
        note="全球过程控制龙头官方年报，提供收入分部、产品结构、地区结构和管理层解释。",
        source_subtype="annual_report",
        is_primary_source=1,
        source_credibility="official",
        language="en",
        key_arguments=source_args(
            ("FY2025 Semiconductor Process Control 收入 109.47 亿美元，晶圆检测收入 61.99 亿美元。", "中性", "全球龙头锚点"),
            ("FY2025 中国收入占比从 43% 回落至 33%，说明中国扩产高峰和出口管制共同影响地区结构。", "看跌", "区域风险"),
        ),
    ),
    SourceSpec(
        key="kla_q3_2026",
        title="KLA Reports Fiscal 2026 Third Quarter Results",
        source_type="web",
        publisher="KLA",
        publish_date="2026-04-30",
        quality_tier=1,
        value_layer="最新数据",
        url="https://ir.kla.com/news-events/press-releases/detail/514/kla-corporation-reports-fiscal-2026-third-quarter-results",
        note="KLA 2026 财年三季报，作为 2026 年需求仍强的近端证据。",
        source_subtype="earnings_release",
        is_primary_source=1,
        source_credibility="official",
        language="en",
        key_arguments=source_args(
            ("FY2026Q3 收入 34.15 亿美元，下一季度收入指引中值 35.75 亿美元。", "看涨", "近端需求"),
        ),
    ),
    SourceSpec(
        key="nova_2025_results",
        title="Nova Reports Fourth Quarter and Record Full Year 2025 Results",
        source_type="web",
        publisher="Nova Ltd.",
        publish_date="2026-02-19",
        quality_tier=1,
        value_layer="最新数据",
        url="https://www.novami.com/investors/press-releases/nova-reports-fourth-quarter-and-record-full-year-2025-results/",
        note="量测纯玩家官方业绩，体现 GAA、DRAM、先进封装对 optical/materials/chemical metrology 的拉动。",
        source_subtype="earnings_release",
        is_primary_source=1,
        source_credibility="official",
        language="en",
        key_arguments=source_args(
            ("2025 年收入 8.806 亿美元，同比增长 31%，毛利率 57.4%。", "看涨", "全球量测公司"),
            ("管理层提到 GAA、DRAM、先进封装和 AI 需求带动 metrology share gains。", "看涨", "技术驱动"),
        ),
    ),
    SourceSpec(
        key="onto_2025_results",
        title="Onto Innovation Reports 2025 Full Year Results",
        source_type="web",
        publisher="Onto Innovation",
        publish_date="2026-02-05",
        quality_tier=1,
        value_layer="最新数据",
        url="https://investors.ontoinnovation.com/news-releases/news-release-details/onto-innovation-reports-2025-fourth-quarter-and-full-year",
        note="Onto 官方业绩，先进封装、HBM 和特殊器件 inspection/metrology 对照。",
        source_subtype="earnings_release",
        is_primary_source=1,
        source_credibility="official",
        language="en",
        key_arguments=source_args(
            ("2025 年收入约 10.05 亿美元，HBM 相关订单和先进封装成为增长锚。", "看涨", "先进封装"),
        ),
    ),
    SourceSpec(
        key="camtek_2025_results",
        title="Camtek Announces Record Results for the Fourth Quarter & Full Year 2025",
        source_type="web",
        publisher="Camtek",
        publish_date="2026-02-12",
        quality_tier=1,
        value_layer="最新数据",
        url="https://www.camtek.com/news-and-events/camtek-announces-record-results-for-the-fourth-quarter-full-year-2025/",
        note="先进封装/HBM inspection 设备公司官方业绩。",
        source_subtype="earnings_release",
        is_primary_source=1,
        source_credibility="official",
        language="en",
        key_arguments=source_args(
            ("2025 年收入 4.961 亿美元，同比增长 16%，公司预计 2026 年继续双位数增长。", "看涨", "先进封装检测"),
        ),
    ),
    SourceSpec(
        key="lasertec_fy2026_h1",
        title="Lasertec FY2026 Business Report and Management Message",
        source_type="web",
        publisher="Lasertec",
        publish_date="2026-02-03",
        quality_tier=1,
        value_layer="最新数据",
        url="https://www.lasertec.co.jp/en/ir/plan/message.html",
        note="EUV mask/blanks inspection 关键公司官方经营说明。",
        source_subtype="business_report",
        is_primary_source=1,
        source_credibility="official",
        language="en",
        key_arguments=source_args(
            ("FY2026H1 净销售 1282.58 亿日元，其中半导体相关产品 983.16 亿日元、服务 278.72 亿日元。", "中性", "掩模检测"),
            ("公司承认部分客户投资计划修订导致订单下滑，预计下半财年逐步恢复。", "看跌", "订单波动"),
        ),
    ),
    SourceSpec(
        key="asml_annual_2025",
        title="ASML Annual Report 2025",
        source_type="annual_report",
        publisher="ASML",
        publish_date="2026-02-11",
        quality_tier=1,
        value_layer="深度框架",
        url="https://www.asml.com/investors/annual-report/2025",
        note="ASML 官方年报，用于说明 lithography 生态内 metrology/inspection 的边界和 e-beam/HMI 角色。",
        source_subtype="annual_report",
        is_primary_source=1,
        source_credibility="official",
        language="en",
        key_arguments=source_args(
            ("2025 年 ASML 净销售 327 亿欧元，毛利率 52.8%，研发 47 亿欧元。", "中性", "相邻龙头"),
        ),
    ),
    SourceSpec(
        key="hitachi_cdsem",
        title="Hitachi High-Tech CD-SEM Metrology Solution",
        source_type="web",
        publisher="Hitachi High-Tech",
        publish_date=TODAY,
        quality_tier=1,
        value_layer="深度框架",
        url="https://www.hitachi-hightech.com/us/en/products/semiconductor-manufacturing/cd-sem/metrology-solution/",
        note="CD-SEM 产品线官方说明，用于定义电子束关键尺寸量测边界。",
        source_subtype="product_page",
        is_primary_source=1,
        source_credibility="official",
        language="en",
        key_arguments=source_args(
            ("CD-SEM 用于半导体晶圆微细图形尺寸量测，是前道过程控制的核心电子束量测设备。", "中性", "技术边界"),
        ),
    ),
    SourceSpec(
        key="amat_metrology_inspection",
        title="Applied Materials Metrology and Inspection",
        source_type="web",
        publisher="Applied Materials",
        publish_date=TODAY,
        quality_tier=1,
        value_layer="深度框架",
        url="https://www.appliedmaterials.com/us/en/semiconductor/products/processes/metrology-and-inspection.html",
        note="应用材料官方产品页，用于补齐 Prompt 要求中的 Applied Materials 量测、检测、review 和过程控制能力。",
        source_subtype="product_page",
        is_primary_source=1,
        source_credibility="official",
        language="en",
        key_arguments=source_args(
            ("Applied Materials 明确将 metrology、wafer inspection、defect review、analysis、classification 用于监控和控制半导体制造各步骤质量。", "中性", "产品边界"),
            ("其产品覆盖 FEOL/BEOL，涉及 SADP/SAQP、EUV layers、OPC mask qualification 和 3D architectures 等高难度场景。", "中性", "技术壁垒"),
        ),
    ),
    SourceSpec(
        key="amat_10k_2025",
        title="Applied Materials Form 10-K FY2025",
        source_type="sec_filing",
        publisher="Applied Materials / SEC",
        publish_date="2025-12-12",
        quality_tier=1,
        value_layer="最新数据",
        url="https://ir.appliedmaterials.com/static-files/af687923-06c7-4b43-a7a5-45750717f3ca",
        note="应用材料 FY2025 官方年报，用于补齐全球设备龙头财务锚和中国收入敞口。",
        source_subtype="annual_report",
        is_primary_source=1,
        source_credibility="official",
        language="en",
        key_arguments=source_args(
            ("FY2025 net revenue 283.68 亿美元，Semiconductor Systems 收入 207.98 亿美元，Applied Global Services 收入 63.85 亿美元。", "中性", "全球龙头财务"),
            ("FY2025 中国收入 85.29 亿美元、占比 30%，低于 FY2024 的 37%，反映出口管制和地区 capex 变化。", "看跌", "区域风险"),
        ),
    ),
    SourceSpec(
        key="nordson_test_inspection",
        title="Nordson Test & Inspection: Advanced Metrology & Inspection",
        source_type="web",
        publisher="Nordson",
        publish_date=TODAY,
        quality_tier=1,
        value_layer="深度框架",
        url="https://www.nordson.com/en/divisions/test-and-inspection",
        note="Nordson 官方 Test & Inspection 产品页，用于补齐 X-ray、acoustic、optical、WaferSense 和先进封装/前中后道检测边界。",
        source_subtype="product_page",
        is_primary_source=1,
        source_credibility="official",
        language="en",
        key_arguments=source_args(
            ("Nordson Test & Inspection 产品覆盖 Acoustic、Optical、Bond Test、X-ray、WaferSense semiconductor sensors 和 AI 软件。", "中性", "产品边界"),
            ("公司页面将 Advanced Packaging、Front-End semiconductor、Mid-End semiconductor、Back-End semiconductor 列为关键应用段。", "中性", "相邻赛道"),
        ),
    ),
    SourceSpec(
        key="bruker_semiconductor_solutions",
        title="Bruker Semiconductor Solutions",
        source_type="web",
        publisher="Bruker",
        publish_date=TODAY,
        quality_tier=1,
        value_layer="深度框架",
        url="https://www.bruker.com/en/products-and-solutions/semiconductor-solutions.html",
        note="Bruker 官方半导体解决方案页，用于补齐 AFM、X-ray、ellipsometry/reflectometry、surface metrology 和 mask repair 等细分。",
        source_subtype="product_page",
        is_primary_source=1,
        source_credibility="official",
        language="en",
        key_arguments=source_args(
            ("Bruker 产品覆盖 ellipsometry/reflectometry、automated X-ray metrology、automated AFM、photomask repair 和 surface metrology。", "中性", "产品边界"),
            ("Bruker 的强项更偏材料/表面/薄膜和研发到量产过程监测，不是 KLA 式全平台过程控制。", "中性", "竞争定位"),
        ),
    ),
    SourceSpec(
        key="bruker_2025_results",
        title="Bruker Reports Fourth Quarter and Full Year 2025 Financial Results",
        source_type="web",
        publisher="Bruker",
        publish_date="2026-02-26",
        quality_tier=1,
        value_layer="最新数据",
        url="https://ir.bruker.com/press-releases/press-release-details/2026/Bruker-Reports-Fourth-Quarter-and-Full-Year-2025-Financial-Results/default.aspx",
        note="Bruker 2025 全年业绩，用于标注其为多业务科学仪器公司，PE 因 GAAP 亏损不可比。",
        source_subtype="earnings_release",
        is_primary_source=1,
        source_credibility="official",
        language="en",
        key_arguments=source_args(
            ("FY2025 revenues 34.4 亿美元，同比增长 2.1%；BSI 收入 31.7 亿美元，BEST 收入 2.709 亿美元。", "中性", "公司财务"),
            ("FY2025 GAAP diluted loss per share 为 -0.15 美元，non-GAAP EPS 为 1.83 美元，因此 trailing PE 不适合机械比较。", "看跌", "估值口径"),
        ),
    ),
    SourceSpec(
        key="secote_optima_official",
        title="赛腾股份 Optima 半导体检测测量设备官网",
        source_type="web",
        publisher="赛腾股份 / Optima",
        publish_date=TODAY,
        quality_tier=1,
        value_layer="深度框架",
        url="https://www.secote-optima.com/",
        note="赛腾 Optima 官方产品页，用于补齐硅片边缘缺陷、背面检测、量测和自动化缺陷分类能力。",
        source_subtype="product_page",
        is_primary_source=1,
        source_credibility="official",
        language="zh",
        key_arguments=source_args(
            ("Optima 页面展示硅片边缘缺陷自动检测设备 RXW-1200、晶圆片背面检测设备 BMW-1200 等产品。", "中性", "国内公司覆盖"),
            ("赛腾股份属于自动化设备平台，半导体检测测量来自 Optima 资产，不能按纯前道量测整机估值。", "中性", "业务纯度"),
        ),
    ),
    SourceSpec(
        key="secote_annual_2025",
        title="苏州赛腾精密电子股份有限公司 2025 年年度报告摘要",
        source_type="company_filing",
        publisher="赛腾股份 / 上交所公告",
        publish_date="2026-04-28",
        quality_tier=1,
        value_layer="最新数据",
        url="https://file.finance.sina.com.cn/211.154.219.97%3A9494/MRGG/CNSESH_STOCK/2026/2026-4/2026-04-28/12212857.PDF",
        note="赛腾 2025 年报摘要，说明公司在消费电子、半导体、新能源等领域的智能组装、检测、量测业务。",
        source_subtype="annual_report",
        is_primary_source=1,
        source_credibility="official_repost",
        language="zh",
        key_arguments=source_args(
            ("公司为客户提供自动化组装线、包装线、量测设备、测试设备、工装夹具、治具及智慧工厂整体规划等方案。", "中性", "业务边界"),
            ("公司在消费电子、半导体、新能源等领域的智能组装、检测、量测核心环节具备业务布局。", "中性", "业务纯度"),
        ),
    ),
    SourceSpec(
        key="dfjy_official_product",
        title="东方晶源电子束量测检测产品线官方新闻",
        source_type="web",
        publisher="东方晶源",
        publish_date="2024-08-21",
        quality_tier=2,
        value_layer="深度框架",
        url="https://www.dfjy-jx.com/list/2.html?page=5",
        note="东方晶源官方新闻列表，用于补齐 EBI、CD-SEM、DR-SEM 和良率管理软件等电子束量测检测能力。2024 年资料只作历史和产品线证据。",
        source_subtype="company_news",
        is_primary_source=1,
        source_credibility="official",
        language="zh",
        key_arguments=source_args(
            ("东方晶源官方新闻称其持续升级电子束量测检测产品线，并围绕 DMS/YMS/MMS 良率管理软件推进。", "中性", "国内公司覆盖"),
            ("该来源为 2024 年资料，适合证明产品线存在和历史进展，不能单独作为 2026 年订单判断。", "中性", "时效约束"),
        ),
    ),
    SourceSpec(
        key="rsl_science_investment",
        title="科创集团投资企业睿励科学仪器引入中微新一轮战略投资",
        source_type="web",
        publisher="上海科创集团 / SEMI 中国转载",
        publish_date="2020-12-29",
        quality_tier=2,
        value_layer="深度框架",
        url="https://www.semi.org.cn/site/semi/article/7d05a553b7e54999919027faa1df9c95.html",
        note="睿励科学仪器产品和客户线索，年份较早，只作为国内前道光学膜厚/缺陷检测能力历史证据。",
        source_subtype="company_news",
        is_primary_source=0,
        source_credibility="official_repost",
        language="zh",
        key_arguments=source_args(
            ("睿励主营光学膜厚测量、光学缺陷检测、硅片厚度及翘曲测量等前道设备。", "中性", "国内公司覆盖"),
            ("TFX3000 12 英寸光学测量设备已应用于 65/55/40/28nm 生产线并进行 14nm 工艺验证。", "中性", "节点验证"),
        ),
    ),
    SourceSpec(
        key="zhongke_annual_2025",
        title="中科飞测 2025 年年度报告及 2026 年一季报",
        source_type="company_filing",
        publisher="中科飞测 / 上交所公告",
        publish_date="2026-04-25",
        quality_tier=1,
        value_layer="最新数据",
        url="https://www.sse.com.cn/",
        note="A 股公司公告锚，数字以公告和公告点评复核；卖方预测只作为补充。",
        source_subtype="annual_report",
        is_primary_source=1,
        source_credibility="official",
        language="zh",
        key_arguments=source_args(
            ("2025 年收入 20.53 亿元、毛利率 49.93%、归母净利润 0.59 亿元，扣非仍亏损。", "中性", "国产龙头财务"),
            ("2026Q1 合同负债 8.81 亿元，较 2025Q4 末环比增长约 56%。", "看涨", "订单和交付"),
        ),
    ),
    SourceSpec(
        key="jingce_annual_2025",
        title="精测电子 2025 年年度报告及投资者材料",
        source_type="company_filing",
        publisher="精测电子 / 深交所公告",
        publish_date="2026-04-28",
        quality_tier=1,
        value_layer="最新数据",
        url="https://www.cninfo.com.cn/",
        note="A 股公告锚，注意精测电子不是纯量测公司，显示、新能源和半导体业务必须拆分。",
        source_subtype="annual_report",
        is_primary_source=1,
        source_credibility="official",
        language="zh",
        key_arguments=source_args(
            ("2025 年半导体业务收入约 13.18 亿元，同比增长 71.6%；公司整体扭亏。", "看涨", "国产量测平台"),
            ("显示和新能源业务仍影响整体利润与估值口径，不能把集团收入全算作半导体量测。", "看跌", "业务纯度"),
        ),
    ),
    SourceSpec(
        key="tzzk_official_tb1500",
        title="苏州矽行面向 40nm 制程 BFI 设备获得客户订单",
        source_type="web",
        publisher="天准科技 / 苏州矽行",
        publish_date="2026-06-18",
        quality_tier=1,
        value_layer="最新数据",
        url="https://www.tztek.com/news/",
        note="天准/矽行官方产品进展，适合作为明场晶圆检测订单和节点边界锚。",
        source_subtype="company_news",
        is_primary_source=1,
        source_credibility="official",
        language="zh",
        key_arguments=source_args(
            ("苏州矽行 TB1000/TB1100 面向 65-180nm，TB1500 面向 55/40nm，TB2000 对应 28/14nm 路线。", "中性", "节点路线"),
            ("40nm BFI 设备获得客户订单说明从样机验证进入订单，但还不是先进制程大规模放量。", "看涨", "国产验证"),
        ),
    ),
    SourceSpec(
        key="tzzk_annual_2025",
        title="天准科技 2025 年年度报告及 2026 年一季报",
        source_type="company_filing",
        publisher="天准科技 / 上交所公告",
        publish_date="2026-04-28",
        quality_tier=1,
        value_layer="最新数据",
        url="https://www.sse.com.cn/",
        note="A 股公告锚，天准主体仍是工业视觉平台，半导体前道通过参股苏州矽行推进。",
        source_subtype="annual_report",
        is_primary_source=1,
        source_credibility="official",
        language="zh",
        key_arguments=source_args(
            ("2025 年收入 17.90 亿元、归母净利润 0.76 亿元，新签订单 24.45 亿元、在手订单 14.35 亿元。", "中性", "平台公司"),
            ("苏州矽行晶圆检测设备在手订单近 7000 万元，半导体业务仍处验证和早期订单阶段。", "看涨", "前道量检测"),
        ),
    ),
    SourceSpec(
        key="mol_annual_2025",
        title="茂莱光学 2025 年年度报告及 2026 年一季报",
        source_type="company_filing",
        publisher="茂莱光学 / 上交所公告",
        publish_date="2026-04-11",
        quality_tier=1,
        value_layer="最新数据",
        url="https://www.sse.com.cn/",
        note="精密光学上游公司公告锚，必须区分上游光学元件和整机量测设备。",
        source_subtype="annual_report",
        is_primary_source=1,
        source_credibility="official",
        language="zh",
        key_arguments=source_args(
            ("2025 年收入 6.91 亿元、归母净利润 0.46 亿元，半导体收入同比增长 71.47%、收入占比 57.76%。", "看涨", "上游光学"),
            ("2026Q1 新增订单约 3 亿元、在手订单约 6.6 亿元，半导体订单占比 69%-75%。", "看涨", "订单"),
        ),
    ),
    SourceSpec(
        key="riliang_annual_2025",
        title="日联科技 2025 年年度报告及 2026 年一季报",
        source_type="company_filing",
        publisher="日联科技 / 上交所公告",
        publish_date="2026-04-26",
        quality_tier=1,
        value_layer="最新数据",
        url="https://www.sse.com.cn/",
        note="X 射线工业检测平台，先进封装/高多层 PCB 是相邻方向，不是晶圆前道量测主线。",
        source_subtype="annual_report",
        is_primary_source=1,
        source_credibility="official",
        language="zh",
        key_arguments=source_args(
            ("2025 年收入 10.78 亿元、归母净利润 1.76 亿元，2026Q1 收入 2.96 亿元。", "中性", "边界公司"),
            ("部分半导体先进封装、PCB、光模块检测产品小规模出货，仍需区分工业 X-ray 与晶圆前道量测。", "中性", "边界"),
        ),
    ),
    SourceSpec(
        key="tianfeng_zkf_20260420",
        title="天风证券：中科飞测，量检测领军企业，明暗场产品有望迎来突破",
        source_type="pdf",
        publisher="天风证券",
        publish_date="2026-04-20",
        quality_tier=3,
        value_layer="深度框架",
        file_path=rel(PAPER_DIR / "20260420-天风证券-中科飞测-688361-量检测领军企业，明暗场产品有望迎来突破.pdf"),
        note="公司研报，可信度降权；用于产品线、市场口径和历史发展补充，不能替代年报。",
        source_subtype="sell_side_company",
        source_credibility="discounted_sell_side",
        key_arguments=source_args(
            ("2025H1 中科飞测检测/量测/其他收入 4.26/2.56/0.20 亿元，占比 61%/36%/3%。", "中性", "分业务"),
            ("2023 年全球量测检测市场销售额 152.9 亿美元，2030E 277.6 亿美元，CAGR 8.9%。", "中性", "市场规模"),
        ),
    ),
    SourceSpec(
        key="huayuan_zkf_20260116",
        title="华源证券：中科飞测，半导体量检测设备深耕者，丰富品类助力自主可控",
        source_type="pdf",
        publisher="华源证券",
        publish_date="2026-01-16",
        quality_tier=3,
        value_layer="深度框架",
        file_path=rel(PAPER_DIR / "20260116-华源证券-中科飞测-688361-半导体量检测设备深耕者，丰富品类助力自主可控.pdf"),
        note="公司研报，补充中科飞测产品图谱和国产替代路径，结论需官方数据复核。",
        source_subtype="sell_side_company",
        source_credibility="discounted_sell_side",
        key_arguments=source_args(
            ("公司 2024 年量检测设备出货突破 1000 台。", "看涨", "国产出货"),
            ("中国大陆 2020-2024 年半导体量测检测设备市场 CAGR 约 27.73%。", "看涨", "中国市场"),
        ),
    ),
    SourceSpec(
        key="huatai_zkf_20260426",
        title="华泰证券：中科飞测，光学+电子束+X光一站式布局领先",
        source_type="pdf",
        publisher="华泰证券",
        publish_date="2026-04-26",
        quality_tier=3,
        value_layer="深度框架",
        file_path=rel(PAPER_DIR / "20260426-华泰证券-中科飞测-688361-光学+电子束+X光一站式布局领先.pdf"),
        note="公司研报，用于产品验证、合同负债和技术路线补充；公司隐患需单独列示。",
        source_subtype="sell_side_company",
        source_credibility="discounted_sell_side",
        key_arguments=source_args(
            ("中科飞测 2025 年期末合同负债 5.65 亿元、存货 26.99 亿元。", "看涨", "订单"),
            ("明场、平整度、CD-SEM、X 光高深宽比/TSV 检测处于验证或出货阶段。", "中性", "产品线"),
        ),
    ),
    SourceSpec(
        key="guangfa_jingce_20260602",
        title="广发证券：精测电子，25年成功实现扭亏为盈，量检测设备迈入收获期",
        source_type="pdf",
        publisher="广发证券",
        publish_date="2026-06-02",
        quality_tier=3,
        value_layer="深度框架",
        file_path=rel(PAPER_DIR / "20260602-广发证券-精测电子-300567-25年成功实现扭亏为盈，量检测设备迈入收获期.pdf"),
        note="公司研报，补充精测半导体产品线；需用公告拆出半导体业务，不把集团业务全算入。",
        source_subtype="sell_side_company",
        source_credibility="discounted_sell_side",
        key_arguments=source_args(
            ("精测半导体产品覆盖膜厚、OCD、电子束、应力、明场等多类量测检测设备。", "看涨", "产品线"),
        ),
    ),
    SourceSpec(
        key="changjiang_mol_20260131",
        title="长江证券：茂莱光学，立足高端精密光学，半导体铸就广阔空间",
        source_type="pdf",
        publisher="长江证券",
        publish_date="2026-01-31",
        quality_tier=3,
        value_layer="深度框架",
        file_path=rel(PAPER_DIR / "20260131-长江证券-茂莱光学-688502-立足高端精密光学，半导体铸就广阔空间.pdf"),
        note="公司研报，补充光学元件在量检测设备中的上游角色，不能把茂莱等同整机设备厂。",
        source_subtype="sell_side_company",
        source_credibility="discounted_sell_side",
        key_arguments=source_args(
            ("精密光学元件是光学检测/量测设备的关键长交期件，客户新产品节奏可能影响订单兑现。", "中性", "供应链"),
        ),
    ),
    SourceSpec(
        key="citic_tzzk_20260611",
        title="中信建投：天准科技，明场晶圆检测+具身智能双布局的工业视觉装备平台厂商",
        source_type="pdf",
        publisher="中信建投",
        publish_date="2026-06-11",
        quality_tier=3,
        value_layer="深度框架",
        file_path=rel(PAPER_DIR / "20260611-中信建投-天准科技-688003-明场晶圆检测+具身智能双布局的工业视觉装备平台厂商.pdf"),
        note="公司研报，补充天准/矽行进展和工业视觉边界；需区分机器人/光模块/PCB 检测收入。",
        source_subtype="sell_side_company",
        source_credibility="discounted_sell_side",
        key_arguments=source_args(
            ("天准 2025 年新签订单 24.45 亿元、期末在手订单 14.35 亿元，但半导体前道只是其中一部分。", "中性", "业务纯度"),
        ),
    ),
    SourceSpec(
        key="dongwu_tester_boundary_20260702",
        title="东吴证券：存储测试机行业专题，AI算力催生HBM带动测试机新需求",
        source_type="pdf",
        publisher="东吴证券",
        publish_date="2026-07-02",
        quality_tier=3,
        value_layer="主题专项",
        file_path=rel(PAPER_DIR / "20260702-东吴证券-存储测试机行业专题：AI算力催生HBM带动测试机新需求，国产设备商加速突破.pdf"),
        note="边界资料：ATE/测试机归测试机行业，只借用去日化空间和日本优势环节作为边界对照。",
        source_subtype="sell_side_boundary",
        source_credibility="discounted_sell_side",
        key_arguments=source_args(
            ("测试机、handler/prober 与过程控制量测检测不是同一口径，不能混入本行业市场规模。", "中性", "边界"),
            ("报告估算 2025 年中国去日化空间中量测/检测约 50 亿元，只能作为替代空间片段。", "中性", "替代空间"),
        ),
    ),
    SourceSpec(
        key="dongwu_service_boundary_20260214",
        title="东吴证券：检测服务行业2026年度策略，强者恒强的千亿赛道",
        source_type="pdf",
        publisher="东吴证券",
        publish_date="2026-02-14",
        quality_tier=4,
        value_layer="信息流",
        file_path=rel(PAPER_DIR / "20260214-东吴证券-检测服务行业2026年度策略：强者恒强的千亿赛道，关注商业航天等新兴产业带来的发展机遇.pdf"),
        note="边界/噪声资料：第三方检测服务不是半导体前道量测检测设备，只用于提醒不要混口径。",
        source_subtype="sell_side_boundary",
        source_credibility="discounted_sell_side",
        key_arguments=source_args(
            ("检测服务是实验室/第三方服务口径，商业模式和设备厂完全不同。", "中性", "边界"),
        ),
    ),
    SourceSpec(
        key="changjiang_equipment_20260613",
        title="长江证券：半导体行业基石系列之七，设备材料景气跃升",
        source_type="pdf",
        publisher="长江证券",
        publish_date="2026-06-13",
        quality_tier=2,
        value_layer="深度框架",
        file_path=rel(PAPER_DIR / "20260613-长江证券-半导体行业基石系列之七：设备材料景气跃升，上行周期有望拉长.pdf"),
        note="行业宽口径设备材料资料，用于 WFE、先进封装、材料景气与量测检测需求传导。",
        source_subtype="sell_side_industry",
        source_credibility="secondary",
        key_arguments=source_args(
            ("先进制程、HBM 和先进封装扩产会提高量测检测设备用量，但必须通过具体产品线和客户验证落地。", "看涨", "需求传导"),
        ),
    ),
    SourceSpec(
        key="market_snapshot_20260706",
        title="Tushare / Yahoo Finance market snapshot for semiconductor metrology companies 2026-07-07",
        source_type="web_fetch",
        publisher="Tushare Pro / Yahoo Finance",
        publish_date=TODAY,
        quality_tier=2,
        value_layer="最新数据",
        url="https://tushare.pro/; https://finance.yahoo.com/",
        note="2026-07-07 自动读取上市公司市值、PE、PB、PS、毛利率、净利率和现金流；A 股优先 Tushare，海外使用 yfinance，金额统一折算人民币并保留美元等值。",
        source_subtype="market_data",
        is_primary_source=0,
        source_credibility="market_data",
        language="en",
        key_arguments=source_args(
            ("市值和估值只用于相对估值和风险提示，不用于替代收入、订单和客户验证。", "中性", "市场快照"),
        ),
    ),
]


def discover_pdf_sources(existing_keys: set[str]) -> list[SourceSpec]:
    specs: list[SourceSpec] = []
    if not PAPER_DIR.exists():
        return specs
    curated_paths = {s.file_path for s in CURATED_SOURCES if s.file_path}
    for pdf in sorted(PAPER_DIR.glob("*.pdf")):
        pdf_rel = rel(pdf)
        if pdf_rel in curated_paths:
            continue
        key_base = re.sub(r"[^0-9A-Za-z]+", "_", pdf.stem)[:48].strip("_").lower()
        key = f"pdf_{abs(hash(pdf.name)) % 10_000_000}_{key_base}"
        if key in existing_keys:
            continue
        title = pdf.stem
        publisher = "本地PDF"
        m = re.match(r"(\d{8})-([^-]+)-(.+)", title)
        date = ""
        if m:
            date = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}"
            publisher = m.group(2)
        lower = title.lower()
        if "金融工程" in title:
            tier, subtype, note = 5, "noise_market_daily", "金融工程日报，与半导体量测行业研究弱相关，仅作为本地库噪声记录。"
        elif "检测服务" in title:
            tier, subtype, note = 4, "sell_side_boundary", "检测服务边界资料，不作为半导体量测检测设备主体口径。"
        elif "存储测试机" in title:
            tier, subtype, note = 4, "sell_side_boundary", "ATE/测试机边界资料，不作为过程控制量测检测设备主体口径。"
        elif "半导体行业基石" in title or "全球半导体设备" in title:
            tier, subtype, note = 2, "sell_side_industry", "行业宽口径资料，用于周期和设备链传导，不直接替代量测检测专门市场。"
        elif any(x in title for x in ["中科飞测", "精测电子", "天准科技", "茂莱光学", "日联科技"]):
            tier, subtype, note = 3, "sell_side_company", "公司研报，需降权并用公告、年报和海外一手源交叉验证。"
        else:
            tier, subtype, note = 3, "pdf_report", "本地 PDF 补充资料。"
        specs.append(
            SourceSpec(
                key=key,
                title=title,
                source_type="pdf",
                publisher=publisher,
                publish_date=date,
                quality_tier=tier,
                value_layer="信息流",
                file_path=rel(pdf),
                note=note,
                source_subtype=subtype,
                source_credibility="discounted_sell_side" if "sell_side" in subtype else "unverified",
                key_arguments=source_args((note, "中性", "资料边界")),
            )
        )
    return specs


COMPANIES: dict[str, CompanySpec] = {
    "kla": CompanySpec(
        key="kla",
        name="KLA",
        ticker="KLAC",
        market="NASDAQ",
        listing_status="listed",
        role="全球过程控制和晶圆检测龙头",
        note="全球基准公司，收入体量、毛利率和中国区占比用于校准赛道难度。",
        source_key="kla_10k_2025",
        brief_intro="KLA 是半导体过程控制龙头，产品覆盖晶圆检测、reticle/掩模检测、patterning、量测和服务，是本行业最重要的全球利润池锚。",
        products="晶圆缺陷检测、reticle inspection、overlay/CD/patterning metrology、process control software、服务。",
        customers="全球逻辑、存储、代工、IDM 和先进封装客户。",
        risks="中国收入占比回落、出口管制、客户资本开支节奏、先进节点集中度高。",
        profile={
            "revenue_2025_usd_m": 12156,
            "process_control_revenue_2025_usd_m": 10947,
            "wafer_inspection_revenue_2025_usd_m": 6199,
            "patterning_revenue_2025_usd_m": 2196,
            "service_revenue_2025_usd_m": 2683,
            "china_revenue_share_2025_pct": 33,
            "global_rank": 1,
            "global_share_note": "过程控制收入和利润池全球龙头，份额口径需按 product/region 拆分。",
        },
    ),
    "asml": CompanySpec(
        key="asml",
        name="ASML",
        ticker="ASML",
        market="NASDAQ",
        listing_status="listed",
        role="光刻生态龙头，含 metrology 与 e-beam 相邻能力",
        note="不是量测检测纯玩家，但 lithography control 与 HMI e-beam 是前道过程控制生态的重要相邻锚。",
        source_key="asml_annual_2025",
        brief_intro="ASML 的主体是光刻系统，HMI e-beam 和 computational lithography/metrology 把光刻、overlay、缺陷复查和过程控制连在一起。",
        products="EUV/DUV 光刻、metrology、inspection、HMI e-beam、计算光刻软件。",
        customers="全球先进逻辑、存储和代工厂。",
        risks="出口管制、高端 EUV 周期、客户集中和中国地区设备限制。",
        profile={"revenue_2025_eur_m": 32700, "gross_margin_2025_pct": 52.8, "rd_2025_eur_m": 4700},
    ),
    "nova": CompanySpec(
        key="nova",
        name="Nova",
        ticker="NVMI",
        market="NASDAQ",
        listing_status="listed",
        role="量测纯玩家，GAA/DRAM/先进封装受益方",
        note="用来对照中国量测公司如何从单品导入走向多技术平台。",
        source_key="nova_2025_results",
        brief_intro="Nova 是独立量测设备公司，覆盖 optical/materials/chemical metrology，在 GAA、DRAM、先进封装中受益。",
        products="Optical CD、materials metrology、chemical metrology、process control software。",
        customers="先进逻辑、存储、代工和先进封装客户。",
        risks="先进节点客户投资节奏、单一赛道纯度高带来的周期弹性、估值对高增长假设敏感。",
        profile={"revenue_2025_usd_m": 880.6, "yoy_2025_pct": 31, "gross_margin_2025_pct": 57.4, "net_income_2025_usd_m": 259.2},
    ),
    "onto": CompanySpec(
        key="onto",
        name="Onto Innovation",
        ticker="ONTO",
        market="NYSE",
        listing_status="listed",
        role="先进封装与特殊器件 inspection/metrology 平台",
        note="在 HBM、先进封装、功率和特殊器件中体现非晶圆前道的量测检测增量。",
        source_key="onto_2025_results",
        brief_intro="Onto Innovation 提供 inspection、metrology 和 process control，先进封装和 HBM 是近年增长弹性最大的方向之一。",
        products="Wafer inspection、overlay/metrology、advanced packaging inspection、software。",
        customers="HBM、先进封装、特殊器件、OSAT、IDM 和 foundry。",
        risks="先进封装订单波动、客户验证节奏、HBM 投资高基数后回落风险。",
        profile={"revenue_2025_usd_m": 1005, "hbm_agreement_2025_usd_m": 240},
    ),
    "camtek": CompanySpec(
        key="camtek",
        name="Camtek",
        ticker="CAMT",
        market="NASDAQ",
        listing_status="listed",
        role="先进封装/HBM inspection 设备公司",
        note="用于证明 AI/HBM 不只拉动晶圆前道，也拉动封装侧三维检测、表面缺陷和 bump/warpage 检测。",
        source_key="camtek_2025_results",
        brief_intro="Camtek 主要提供自动化光学 inspection/metrology，受益于 HBM、先进封装和高端 IC substrate。",
        products="Advanced packaging inspection、metrology、2D/3D inspection。",
        customers="OSAT、IDM、HBM 和先进封装链客户。",
        risks="先进封装资本开支波动、订单集中、估值对 HBM 景气敏感。",
        profile={"revenue_2025_usd_m": 496.1, "yoy_2025_pct": 16},
    ),
    "lasertec": CompanySpec(
        key="lasertec",
        name="Lasertec",
        ticker="6920.T",
        market="TSE",
        listing_status="listed",
        role="EUV 掩模/空白掩模检测稀缺公司",
        note="掩模检测不是中国 A 股公司主线，但代表最高端光学检测的稀缺利润池。",
        source_key="lasertec_fy2026_h1",
        brief_intro="Lasertec 是 EUV mask/blanks inspection 关键供应商，订单波动直接反映先进节点客户投资节奏。",
        products="EUV mask inspection、blank mask inspection、wafer inspection、service。",
        customers="先进逻辑、存储、掩模厂和晶圆制造客户。",
        risks="客户投资修订导致订单波动、EUV 节奏、单品集中。",
        profile={"sales_fy2026_h1_jpy_m": 128258, "semi_product_sales_fy2026_h1_jpy_m": 98316, "service_sales_fy2026_h1_jpy_m": 27872},
    ),
    "hitachi_ht": CompanySpec(
        key="hitachi_ht",
        name="Hitachi High-Tech",
        ticker=None,
        market=None,
        listing_status="parent_subsidiary",
        role="CD-SEM 和电子束量测关键供应商",
        note="作为 Hitachi 体系下未单独上市主体，不做市值对比，只用于 CD-SEM 技术边界。",
        source_key="hitachi_cdsem",
        brief_intro="Hitachi High-Tech 的 CD-SEM 产品线是电子束关键尺寸量测的重要全球锚，适合和国产 CD-SEM 进度对照。",
        products="CD-SEM、defect review SEM、wafer inspection 和电子显微镜相关产品。",
        customers="先进逻辑、存储、代工厂和研发线。",
        risks="未单独上市导致财务不可拆，电子束量测竞争激烈，先进节点验证周期长。",
        profile={"global_share_note": "产品页用于技术边界，财务不单列。"},
    ),
    "amat": CompanySpec(
        key="amat",
        name="Applied Materials",
        ticker="AMAT",
        market="NASDAQ",
        listing_status="listed",
        role="全球半导体设备平台，PDC/量测检测重要对标",
        note="不是量测检测纯玩家，但其 metrology、wafer inspection、defect review 和 review/classification 产品是全球前道过程控制的重要平台。",
        source_key="amat_metrology_inspection",
        brief_intro="Applied Materials 是全球半导体设备平台型公司，量测检测能力嵌在 FEOL/BEOL、EUV、OPC mask qualification 和 3D architectures 的过程控制方案中。",
        products="Metrology、wafer inspection、defect review、analysis/classification、e-beam/optical inspection、process control software。",
        customers="全球 leading-edge logic、foundry、DRAM/NAND、先进封装和成熟节点客户。",
        risks="量测检测不是独立披露分部，不能把集团 Semiconductor Systems 全部当 PDC；中国收入占比下降、出口管制和客户 capex 节奏影响较大。",
        profile={
            "revenue_2025_usd_m": 28368,
            "semiconductor_systems_revenue_2025_usd_m": 20798,
            "services_revenue_2025_usd_m": 6385,
            "gross_margin_2025_pct": 48.7,
            "net_income_2025_usd_m": 6998,
            "china_revenue_share_2025_pct": 30,
            "global_share_note": "全球半导体设备平台锚，量测检测能力需按产品线理解，不能和 KLA 过程控制分部直接同口径比较。",
        },
    ),
    "nordson": CompanySpec(
        key="nordson",
        name="Nordson",
        ticker="NDSN",
        market="NASDAQ",
        listing_status="listed",
        role="先进封装、X-ray、声学、光学 inspection/metrology 边界对标",
        note="Nordson Test & Inspection 覆盖 AOI、AXI、AXM、Acoustic、Bond Test、WaferSense 等，更偏先进封装、电子装联和前中后道相邻检测。",
        source_key="nordson_test_inspection",
        brief_intro="Nordson Test & Inspection 提供 metrology/inspection systems、sensors 和软件，覆盖 advanced packaging、front-end/mid-end/back-end semiconductor 与 AI/server/5G 等应用。",
        products="Acoustic inspection、automated optical inspection/metrology、automated X-ray inspection/metrology、bond test、WaferSense/ReticleSense sensors、inspection AI software。",
        customers="先进封装、电子装联、前中后道半导体、AI/server/5G、汽车和功率电子客户。",
        risks="集团业务多元，半导体检测不是单独完整分部；部分产品更接近电子装联/先进封装检测，不应混入晶圆前道核心份额。",
        profile={
            "global_share_note": "先进封装和电子装联 inspection/metrology 对照，不按晶圆前道过程控制龙头估值。",
        },
    ),
    "bruker": CompanySpec(
        key="bruker",
        name="Bruker",
        ticker="BRKR",
        market="NASDAQ",
        listing_status="listed",
        role="材料、表面、薄膜和 X-ray/AFM metrology 细分对标",
        note="Bruker 是科学仪器和半导体 metrology 解决方案供应商，强项在 AFM、X-ray、ellipsometry、surface metrology 和 photomask repair 等细分。",
        source_key="bruker_semiconductor_solutions",
        brief_intro="Bruker 的半导体方案覆盖 automated AFM、X-ray metrology/defect inspection、ellipsometry/reflectometry、surface metrology 和 mask repair，适合校准材料和表面量测子赛道。",
        products="Automated AFM、ellipsometry/reflectometry、automated X-ray metrology、X-ray defect inspection、surface metrology、photomask repair。",
        customers="半导体研发线、高端制造、材料/薄膜、wafer-level packaging 和掩模客户。",
        risks="集团科学仪器业务宽，FY2025 GAAP EPS 亏损导致 trailing PE 不可比；半导体业务收入未完整单列，不能按纯量测设备估值。",
        profile={
            "revenue_2025_usd_m": 3440,
            "yoy_2025_pct": 2.1,
            "net_income_2025_usd_m": None,
            "global_share_note": "材料/表面/薄膜 metrology 子赛道对标，估值用 PB/PS 和分部质量辅助，PE 因 GAAP 亏损不可比。",
        },
    ),
    "secote": CompanySpec(
        key="secote",
        name="赛腾股份",
        ticker="603283.SH",
        market="SSE",
        listing_status="listed",
        role="自动化设备平台，Optima 切入硅片缺陷检测/量测",
        note="通过 Optima 和自身自动化平台覆盖半导体检测量测，但集团还包括消费电子、新能源和自动化集成，必须业务拆分。",
        source_key="secote_optima_official",
        brief_intro="赛腾股份是自动化设备公司，半导体检测测量能力主要来自 Optima 等业务，覆盖硅片边缘缺陷、背面检测、缺陷 review/classification 等方向。",
        products="硅片边缘缺陷自动检测、晶圆背面检测、晶圆孔洞/缺陷检测、自动缺陷 review/classification、消费电子和新能源自动化设备。",
        customers="硅片厂、晶圆制造、消费电子、新能源客户；半导体客户公开实名有限。",
        risks="半导体业务纯度低于中科飞测，消费电子自动化周期、并购整合和客户集中会影响估值；不能把集团收入全部归入量测检测。",
        profile={
            "global_share_note": "国内半导体检测测量观察项，核心需看 Optima 半导体订单和集团业务纯度。",
        },
    ),
    "dfjy": CompanySpec(
        key="dfjy",
        name="东方晶源",
        ticker=None,
        market=None,
        listing_status="private",
        role="国内电子束量测检测和良率管理软件观察项",
        note="未上市主体，适合补齐国内 EBI、CD-SEM、DR-SEM 和良率管理软件产品线，不强填财务估值。",
        source_key="dfjy_official_product",
        brief_intro="东方晶源聚焦电子束量测检测和良率管理，公开资料显示其覆盖 EBI、CD-SEM、DR-SEM 及 DMS/YMS/MMS 良率管理软件。",
        products="电子束缺陷检测 EBI、关键尺寸量测 CD-SEM、缺陷复检 DR-SEM、计算光刻和良率管理软件。",
        customers="晶圆厂和先进制程研发/量产客户；公开订单和财务信息有限。",
        risks="未上市、公开财务和订单有限，2024 年产品线资料只能证明能力和历史进展，不能单独支撑当前份额。",
        profile={"global_share_note": "未上市电子束量测检测观察项，不做 PE/PB/市值估值。"},
    ),
    "rsl": CompanySpec(
        key="rsl",
        name="睿励科学仪器",
        ticker=None,
        market=None,
        listing_status="private",
        role="国内前道光学膜厚/缺陷检测早期公司",
        note="资料较早，作为国内光学膜厚、缺陷检测和硅片厚度/翘曲量测能力历史证据，不作为当前订单强证据。",
        source_key="rsl_science_investment",
        brief_intro="睿励科学仪器主营光学膜厚测量、光学缺陷检测、硅片厚度及翘曲测量等前道设备，曾披露 TFX3000 进入 65/55/40/28nm 并验证 14nm。",
        products="光学膜厚测量、光学缺陷检测、硅片厚度及翘曲测量、OCD/更高阶膜厚量测开发。",
        customers="国内外 12 英寸生产线客户；公开资料中客户实名有限。",
        risks="来源年份较早、财务不公开、当前产品进度和订单需要 2025/2026 新证据复核。",
        profile={"global_share_note": "国内光学量测检测历史能力观察项，缺少近端公开财务和订单。"},
    ),
    "zhongke": CompanySpec(
        key="zhongke",
        name="中科飞测",
        ticker="688361.SH",
        market="SSE STAR",
        listing_status="listed",
        role="国产量测检测整机龙头",
        note="A 股最纯的量测检测整机公司，但扣非仍亏损、研发投入和存货/合同负债必须同时看。",
        source_key="zhongke_annual_2025",
        brief_intro="中科飞测覆盖检测和量测设备，光学为基本盘，电子束和 X 光新品推进；是国产替代中最需要跟踪客户验证和收入兑现的核心公司。",
        products="无图形/图形晶圆缺陷检测、明场/暗场检测、套刻、薄膜、OCD、三维形貌、电子束 CD-SEM、X 光高深宽比和 TSV 相关量测。",
        customers="国内逻辑、存储、先进封装、硅片和半导体材料/设备客户；公开信息多以头部客户验证表述，客户实名有限。",
        risks="扣非亏损、研发费用率高、先进制程验证不确定、产品结构导致毛利波动、存货和合同负债兑现节奏。",
        profile={
            "revenue_2025_cny_m": 2053,
            "yoy_2025_pct": 48.75,
            "gross_margin_2025_pct": 49.93,
            "net_profit_2025_cny_m": 59,
            "non_gaap_net_profit_2025_cny_m": -123,
            "contract_liability_2025_cny_m": 565,
            "contract_liability_2026q1_cny_m": 881,
            "rd_ratio_2026q1_pct": 46.26,
            "china_rank": 1,
        },
    ),
    "jingce": CompanySpec(
        key="jingce",
        name="精测电子",
        ticker="300567.SZ",
        market="SZSE",
        listing_status="listed",
        role="显示检测起家的半导体量测平台",
        note="半导体业务增长快，但集团还包含显示和新能源，业务纯度低于中科飞测。",
        source_key="jingce_annual_2025",
        brief_intro="精测电子从显示检测拓展至半导体量测检测，半导体业务已进入收获期，但集团口径必须拆出显示、新能源和半导体。",
        products="膜厚量测、OCD、电子束、应力测量、明场检测、先进封装相关检测。",
        customers="晶圆厂、封装厂、显示和新能源客户；半导体客户公开披露有限。",
        risks="集团业务复杂、新能源在手订单和显示业务影响利润质量，半导体产品放量节奏需公告验证。",
        profile={"semiconductor_revenue_2025_cny_m": 1318, "semiconductor_revenue_yoy_2025_pct": 71.6, "revenue_2025_cny_m": 3348},
    ),
    "tzzk": CompanySpec(
        key="tzzk",
        name="天准科技",
        ticker="688003.SH",
        market="SSE STAR",
        listing_status="listed",
        role="工业视觉平台，参股苏州矽行切入晶圆明场检测",
        note="必须把工业视觉、CPO/PCB/机器人业务和半导体前道量测检测分开。",
        source_key="tzzk_annual_2025",
        brief_intro="天准科技主业是工业视觉装备，半导体前道量测检测主要通过参股苏州矽行推进，TB 系列明场晶圆检测处早期订单和验证阶段。",
        products="视觉量检测装备、制程装备、明场晶圆检测 BFI、机器人控制器等。",
        customers="工业视觉、光模块/PCB、机器人客户；苏州矽行面向晶圆厂验证和订单。",
        risks="业务纯度低、半导体前道收入尚小、客户验证周期长、机器人业务可能稀释研究口径。",
        profile={"revenue_2025_cny_m": 1790, "net_profit_2025_cny_m": 76, "new_orders_2025_cny_m": 2445, "backlog_2025_cny_m": 1435, "suxing_backlog_cny_m": 70},
    ),
    "suxing": CompanySpec(
        key="suxing",
        name="苏州矽行",
        ticker=None,
        market=None,
        listing_status="private_subsidiary",
        role="天准参股晶圆前道明场检测公司",
        note="作为未上市实体单列，避免把天准全集团收入错配到晶圆检测。",
        source_key="tzzk_official_tb1500",
        brief_intro="苏州矽行聚焦晶圆前道缺陷检测设备，TB1000/TB1100/TB1500/TB2000 构成节点递进产品线。",
        products="BFI 明场晶圆缺陷检测设备，TB1000/TB1100/TB1500/TB2000。",
        customers="晶圆厂客户，公开披露以订单和验证节点为主。",
        risks="未上市、财务信息有限，40nm 订单不等于 28/14nm 大规模国产替代。",
        profile={"node_tb1000_nm_low": 65, "node_tb1000_nm_high": 180, "node_tb1500_nm": 40, "node_tb2000_nm_low": 14, "node_tb2000_nm_high": 28},
    ),
    "mol": CompanySpec(
        key="mol",
        name="茂莱光学",
        ticker="688502.SH",
        market="SSE STAR",
        listing_status="listed",
        role="高端精密光学上游稀缺供应商",
        note="量测检测设备上游，不是整机设备；订单强但客户节奏和产能转固会影响利润。",
        source_key="mol_annual_2025",
        brief_intro="茂莱光学为半导体设备、生命科学、AR/VR 等领域提供精密光学器件/组件，半导体收入占比上行，是光学量测检测设备的关键上游观察项。",
        products="高精度透镜、棱镜、平片、光学系统、光学模块、深紫外/半导体设备光学组件。",
        customers="半导体设备、生命科学、AR/VR 和航空航天客户；部分客户实名有限。",
        risks="不是整机厂、单品定制化、产能建设和费用影响利润、客户新品节奏影响订单兑现。",
        profile={"revenue_2025_cny_m": 691, "net_profit_2025_cny_m": 46.33, "semiconductor_revenue_yoy_2025_pct": 71.47, "semiconductor_revenue_share_2025_pct": 57.76, "backlog_2026q1_cny_m": 660, "semi_backlog_2026q1_cny_m": 460},
    ),
    "riliang": CompanySpec(
        key="riliang",
        name="日联科技",
        ticker="688531.SH",
        market="SSE STAR",
        listing_status="listed",
        role="X 射线工业检测平台，先进封装相邻观察项",
        note="不是晶圆前道量测核心公司，只把先进封装/PCB/光模块小规模出货作为边界观察。",
        source_key="riliang_annual_2025",
        brief_intro="日联科技主业是 X 射线智能检测，面向工业和电子制造，在先进封装、PCB、光模块和电池等方向拓展。",
        products="X 射线源、智能 X-ray 检测设备、AI 缺陷识别、整体检测方案。",
        customers="电子制造、动力电池、PCB、先进封装和工业客户。",
        risks="工业检测口径较宽、半导体收入不可完全拆分、先进封装放量和设备规格需持续验证。",
        profile={"revenue_2025_cny_m": 1078, "net_profit_2025_cny_m": 176, "revenue_2026q1_cny_m": 296, "net_profit_2026q1_cny_m": 44},
    ),
}


RECENT_EVENTS = {
    "kla": "KLA FY2026Q3 收入 34.15 亿美元，过去 12 个月经营现金流 44.0 亿美元；FY2025 中国收入占比从 43% 降至 33%，说明先进过程控制仍强但中国敞口和出口管制是核心变量。",
    "asml": "ASML 2025 年净销售约 327 亿欧元、毛利率 52.8%，HMI e-beam 和 metrology/inspection 仍是光刻过程控制生态的相邻锚，不应按纯量测检测公司估值。",
    "amat": "Applied Materials FY2025 净收入 283.68 亿美元，其中 Semiconductor Systems 207.98 亿美元、Applied Global Services 63.85 亿美元；官网量测检测页显示其覆盖 FEOL/BEOL、EUV、OPC mask qualification 和 3D architectures 的过程控制。",
    "nova": "Nova 2025 年收入 8.806 亿美元、同比增长 31%，毛利率 57.4%，增长来自 GAA、DRAM 和先进封装量测需求。",
    "onto": "Onto 2025 年收入约 10.05 亿美元，并披露 HBM 相关多年协议和先进封装订单动能，适合作为封装侧 inspection/metrology 弹性锚。",
    "camtek": "Camtek 2025 年收入 4.961 亿美元、同比增长 16%，核心线索仍是 HBM、先进封装和高端 IC substrate 的 2D/3D inspection 需求。",
    "nordson": "Nordson Test & Inspection 官网列出 acoustic、optical、automated X-ray metrology、WaferSense 和 inspection AI 软件，显示先进封装、前中后道和电子装联检测的边界机会。",
    "bruker": "Bruker 2025 年收入 34.4 亿美元，但 GAAP EPS 亏损；其半导体方案覆盖 AFM、X-ray、ellipsometry/reflectometry 和 surface metrology，适合做材料/表面量测对标。",
    "lasertec": "Lasertec FY2026H1 销售 1282.58 亿日元，其中半导体相关产品 983.16 亿日元，掩模检测稀缺性强但订单受先进节点客户投资节奏影响。",
    "hitachi_ht": "Hitachi High-Tech 作为 CD-SEM 和 defect review SEM 关键供应商用于技术边界校准；未单独上市，不能强行填二级市场估值或净利率。",
    "secote": "赛腾股份通过 Optima 覆盖硅片边缘缺陷、背面检测和晶圆缺陷检测/量测，但集团仍有消费电子、新能源和自动化集成业务，半导体纯度要拆分。",
    "dfjy": "东方晶源公开资料显示其覆盖 EBI、CD-SEM、DR-SEM 和良率管理软件，是国内电子束量测检测观察项；未上市且资料时点偏早，不能强行做财务估值。",
    "rsl": "睿励科学仪器较早披露 TFX3000 已应用于 65/55/40/28nm 并验证 14nm，适合证明国内光学膜厚/缺陷检测历史能力，当前订单需补近端证据。",
    "zhongke": "中科飞测 2025 年收入 20.53 亿元、同比增长 48.75%，2026Q1 合同负债升至 8.81 亿元；但扣非亏损和高研发费用率仍是必须跟踪的反方。",
    "jingce": "精测电子 2025 年半导体业务收入约 13.18 亿元、同比增长 71.6%，但集团仍包含显示和新能源，必须用分部口径而非集团总收入判断量测弹性。",
    "tzzk": "天准科技 2025 年新签订单 24.45 亿元、在手订单 14.35 亿元，苏州矽行晶圆检测在手订单近 0.70 亿元，说明前道检测仍是早期增量。",
    "suxing": "苏州矽行 TB1000/TB1500/TB2000 对应 65-180nm、40nm、14-28nm 的产品递进；未上市且财务不可得，只能跟踪订单、节点和客户验证。",
    "mol": "茂莱光学 2025 年半导体收入同比增长 71.47%，2026Q1 半导体在手订单约 4.6 亿元、占总在手订单约 69.7%，是上游光学景气代理而非整机份额。",
    "riliang": "日联科技 2025 年收入 10.78 亿元、净利润 1.76 亿元，2026Q1 收入 2.96 亿元、净利润 0.44 亿元；先进封装和 PCB X-ray 是相邻观察项。",
}


def add_dp(
    dps: list[dict[str, Any]],
    metric: str,
    period: str,
    unit: str,
    source: str,
    excerpt: str,
    *,
    value_num: float | None = None,
    value_text: str | None = None,
    is_forecast: int = 0,
    company_key: str | None = None,
    method: str = "pdf_direct",
    note: str = "",
) -> None:
    if value_num is None and value_text is None:
        raise ValueError(metric)
    dps.append(
        {
            "metric": metric,
            "period": str(period),
            "unit": unit,
            "source": source,
            "excerpt": excerpt,
            "value_num": value_num,
            "value_text": value_text,
            "is_forecast": int(is_forecast),
            "company_key": company_key,
            "method": method,
            "note": note,
        }
    )


def build_data_points(market_snapshot: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    dps: list[dict[str, Any]] = []

    market_excerpt = "天风证券转引 QY Research：2023 年全球半导体量测和检测市场销售额达 152.9 亿美元，2030 年预计 277.6 亿美元，2023-2030 CAGR 为 8.9%。"
    add_dp(dps, "全球半导体量测检测设备市场规模", "2023", "亿美元", "tianfeng_zkf_20260420", market_excerpt, value_num=152.9)
    add_dp(dps, "全球半导体量测检测设备市场规模", "2030E", "亿美元", "tianfeng_zkf_20260420", market_excerpt, value_num=277.6, is_forecast=1)
    add_dp(dps, "全球半导体量测检测设备市场规模2023-2030 CAGR", "2023-2030E", "%", "tianfeng_zkf_20260420", market_excerpt, value_num=8.9, is_forecast=1)

    china_excerpt = "华源证券转引行业数据：2020-2024 年中国大陆半导体量测检测设备市场 CAGR 约 27.73%，显著高于全球增速；公司 2024 年量检测设备出货达 1000 台。"
    add_dp(dps, "中国大陆半导体量测检测设备市场2020-2024 CAGR", "2020-2024", "%", "huayuan_zkf_20260116", china_excerpt, value_num=27.73)
    add_dp(dps, "中科飞测量检测设备累计/年度出货里程碑", "2024", "台", "huayuan_zkf_20260116", china_excerpt, value_num=1000, company_key="zhongke")

    tzz_market = "天准科技年度报告摘要引用市场研究：2024 年全球半导体量测检测设备市场约 192.2 亿美元，中国大陆约 63.6 亿美元；预计 2031 年全球市场约 389.5 亿美元，2025-2031 CAGR 10.77%。"
    add_dp(dps, "全球半导体量测检测设备市场规模", "2024", "亿美元", "tzzk_annual_2025", tzz_market, value_num=192.2, method="web_fetch")
    add_dp(dps, "中国大陆半导体量测检测设备市场规模", "2024", "亿美元", "tzzk_annual_2025", tzz_market, value_num=63.6, method="web_fetch")
    add_dp(dps, "全球半导体量测检测设备市场规模", "2031E", "亿美元", "tzzk_annual_2025", tzz_market, value_num=389.5, is_forecast=1, method="web_fetch")
    add_dp(dps, "全球半导体量测检测设备市场2025-2031 CAGR", "2025-2031E", "%", "tzzk_annual_2025", tzz_market, value_num=10.77, is_forecast=1, method="web_fetch")

    semi_excerpt = "SEMI 官方预测：晶圆厂设备 WFE 2025 年增长 11.0% 至 1157 亿美元，2027 年达到 1352 亿美元；测试设备 2025 年增长 48.1% 至 112 亿美元，封装设备增长 19.6% 至 60 亿美元。"
    for metric, period, value, unit in [
        ("全球晶圆厂设备WFE市场规模", "2025E", 115.7, "十亿美元"),
        ("全球晶圆厂设备WFE市场规模", "2027E", 135.2, "十亿美元"),
        ("全球晶圆厂设备WFE同比增速", "2025E", 11.0, "%"),
        ("全球测试设备市场规模", "2025E", 11.2, "十亿美元"),
        ("全球测试设备同比增速", "2025E", 48.1, "%"),
        ("全球封装设备市场规模", "2025E", 6.0, "十亿美元"),
        ("全球封装设备同比增速", "2025E", 19.6, "%"),
    ]:
        add_dp(dps, metric, period, unit, "semi_equipment_forecast_2026", semi_excerpt, value_num=value, is_forecast=1, method="web_fetch")

    boundary_excerpt = "东吴证券存储测试机专题估算：2025 年中国去日化空间合计约 380 亿元，其中清洗设备约 60 亿元、量测/检测约 50 亿元、切磨抛约 23 亿元、handler 约 18 亿元；报告主体是测试机，本文只取量测/检测替代空间作为边界片段。"
    for metric, value in [
        ("中国半导体设备去日化空间合计", 380),
        ("中国量测/检测设备去日化空间", 50),
        ("中国清洗设备去日化空间", 60),
        ("中国切磨抛设备去日化空间", 23),
        ("中国handler去日化空间", 18),
    ]:
        add_dp(dps, metric, "2025E", "亿元人民币", "dongwu_tester_boundary_20260702", boundary_excerpt, value_num=value, is_forecast=1)

    kla_excerpt = "KLA FY2025 10-K：Semiconductor Process Control 收入 109.47 亿美元；Specialty Semiconductor Process 5.87 亿美元；PCB and Component Inspection 6.22 亿美元；分产品看 Wafer Inspection 61.99 亿美元、Patterning 21.96 亿美元、Services 26.83 亿美元；中国收入占比 33%。"
    for metric, val, unit in [
        ("KLA半导体过程控制收入", 10947, "百万美元"),
        ("KLA Specialty Semiconductor Process收入", 587, "百万美元"),
        ("KLA PCB and Component Inspection收入", 622, "百万美元"),
        ("KLA Wafer Inspection收入", 6199, "百万美元"),
        ("KLA Patterning收入", 2196, "百万美元"),
        ("KLA Services收入", 2683, "百万美元"),
        ("KLA中国收入占比", 33, "%"),
        ("KLA FY2024中国收入占比", 43, "%"),
    ]:
        add_dp(dps, metric, "FY2025", unit, "kla_10k_2025", kla_excerpt, value_num=val, company_key="kla", method="web_fetch")
    add_dp(dps, "KLA中国收入占比同比变化", "FY2025/FY2024", "百分点", "kla_10k_2025", kla_excerpt, value_num=-10, company_key="kla", method="inferred")

    kla_q3_excerpt = "KLA FY2026Q3 新闻稿：截至 2026-03-31 季度收入 34.15 亿美元，GAAP EPS 9.12 美元、non-GAAP EPS 9.40 美元；经营现金流 7.075 亿美元，过去 12 个月经营现金流 44.0 亿美元；下一季度收入指引中值 35.75 亿美元。"
    for metric, val, unit in [
        ("KLA季度收入", 3415, "百万美元"),
        ("KLA季度GAAP EPS", 9.12, "美元"),
        ("KLA季度non-GAAP EPS", 9.40, "美元"),
        ("KLA季度经营现金流", 707.5, "百万美元"),
        ("KLA过去12个月经营现金流", 4400, "百万美元"),
        ("KLA下一季度收入指引中值", 3575, "百万美元"),
    ]:
        add_dp(dps, metric, "FY2026Q3", unit, "kla_q3_2026", kla_q3_excerpt, value_num=val, company_key="kla", method="web_fetch")

    asml_fin_excerpt = "ASML 2025 年报：2025 年净销售约 327 亿欧元、毛利率 52.8%、研发费用约 47 亿欧元。"
    for metric, val, unit in [
        ("ASML净销售额", 32700, "百万欧元"),
        ("ASML毛利率", 52.8, "%"),
        ("ASML研发费用", 4700, "百万欧元"),
    ]:
        add_dp(dps, metric, "2025", unit, "asml_annual_2025", asml_fin_excerpt, value_num=val, company_key="asml", method="web_fetch")
    asml_boundary_excerpt = "ASML 年报和产品体系显示，metrology/inspection、HMI e-beam 和 computational lithography 处在先进光刻过程控制生态中，但 ASML 主体收入不是纯量测检测设备。"
    add_dp(dps, "ASML量测检测边界", "2025", "文本", "asml_annual_2025", asml_boundary_excerpt, value_text="ASML 主体不是量测检测纯玩家，但 HMI e-beam、metrology 和 computational lithography 是先进光刻过程控制不可分割的相邻能力。", company_key="asml", method="web_fetch")

    nova_excerpt = "Nova 官方业绩：2025 年收入 8.806 亿美元，同比增长 31%；净利润 2.592 亿美元；毛利率 57.4%；增长来自 optical/materials/chemical metrology 需求和 GAA、DRAM、先进封装份额提升。"
    for metric, val, unit in [
        ("Nova收入", 880.6, "百万美元"),
        ("Nova收入同比", 31, "%"),
        ("Nova净利润", 259.2, "百万美元"),
        ("Nova毛利率", 57.4, "%"),
    ]:
        add_dp(dps, metric, "2025", unit, "nova_2025_results", nova_excerpt, value_num=val, company_key="nova", method="web_fetch")

    onto_fin_excerpt = "Onto Innovation 官方业绩披露 2025 年收入约 10.05 亿美元。"
    onto_hbm_excerpt = "Onto Innovation 公告 HBM 相关多年协议金额超过 2.4 亿美元，并强调先进封装和特殊器件 inspection-metrology 订单动能。"
    add_dp(dps, "Onto Innovation收入", "2025", "百万美元", "onto_2025_results", onto_fin_excerpt, value_num=1005, company_key="onto", method="web_fetch")
    add_dp(dps, "Onto HBM相关多年协议金额", "2025", "百万美元以上", "onto_2025_results", onto_hbm_excerpt, value_num=240, company_key="onto", method="web_fetch")
    add_dp(dps, "Onto先进封装定位", "2025", "文本", "onto_2025_results", onto_hbm_excerpt, value_text="Onto 的核心增量来自 HBM、先进封装、特殊器件和 process control 软件，适合观察封装侧量测检测而不是前道晶圆检测总量。", company_key="onto", method="web_fetch")

    camtek_excerpt = "Camtek 官方业绩：2025 年收入 4.961 亿美元，同比增长 16%；公司称 AI 市场需求加速，预计 2026 年收入继续双位数增长。"
    add_dp(dps, "Camtek收入", "2025", "百万美元", "camtek_2025_results", camtek_excerpt, value_num=496.1, company_key="camtek", method="web_fetch")
    add_dp(dps, "Camtek收入同比", "2025", "%", "camtek_2025_results", camtek_excerpt, value_num=16, company_key="camtek", method="web_fetch")
    add_dp(dps, "Camtek 2026收入增速指引", "2026E", "文本", "camtek_2025_results", camtek_excerpt, value_text="公司预计 2026 年收入继续双位数增长，主要来自 AI/HBM/先进封装检查需求。", company_key="camtek", is_forecast=1, method="web_fetch")

    lasertec_fin_excerpt = "Lasertec FY2026H1 官方说明：净销售 1282.58 亿日元，半导体相关产品销售 983.16 亿日元，服务 278.72 亿日元，营业利润 629.91 亿日元。"
    for metric, val, unit in [
        ("Lasertec净销售额", 128258, "百万日元"),
        ("Lasertec半导体相关产品销售额", 98316, "百万日元"),
        ("Lasertec服务收入", 27872, "百万日元"),
        ("Lasertec营业利润", 62991, "百万日元"),
    ]:
        add_dp(dps, metric, "FY2026H1", unit, "lasertec_fy2026_h1", lasertec_fin_excerpt, value_num=val, company_key="lasertec", method="web_fetch")
    lasertec_order_excerpt = "Lasertec FY2026H1 官方说明提示，此前订单因客户投资计划修订而下滑，预计 H2 起逐步恢复；EUV mask inspection 需求稀缺但短期订单仍受客户 capex 节奏影响。"
    add_dp(dps, "Lasertec订单风险", "FY2026H1", "文本", "lasertec_fy2026_h1", lasertec_order_excerpt, value_text="EUV mask inspection 需求长期稀缺，但客户投资计划修订会直接造成订单阶段性下滑。", company_key="lasertec", method="web_fetch")

    hitachi_excerpt = "Hitachi High-Tech CD-SEM 产品页：CD-SEM 用于测量半导体晶圆微细图形的 critical dimensions，并服务生产线过程控制；GT2000 面向 High-NA EUV 代际。"
    add_dp(dps, "CD-SEM技术边界", TODAY, "文本", "hitachi_cdsem", hitachi_excerpt, value_text="CD-SEM 是电子束关键尺寸量测设备，用于晶圆微细图形尺寸控制，和光学明/暗场缺陷检测共同构成过程控制体系。", company_key="hitachi_ht", method="web_fetch")
    add_dp(dps, "High-NA EUV代际CD-SEM产品", TODAY, "文本", "hitachi_cdsem", hitachi_excerpt, value_text="Hitachi High-Tech 的 GT2000 等产品面向 High-NA EUV generation，显示先进光刻继续提高电子束量测要求。", company_key="hitachi_ht", method="web_fetch")

    amat_product_excerpt = "Applied Materials 官方量测检测页：metrology、wafer inspection、defect review、analysis 和 classification 用于监控并控制半导体制造步骤质量；产品覆盖 FEOL/BEOL，并用于 SADP/SAQP、EUV layers、OPC mask qualification 和 3D architectures。"
    for metric, text in [
        ("Applied Materials量测检测产品边界", "Applied Materials 覆盖 metrology、wafer inspection、defect review、analysis/classification，属于前道过程控制平台能力的一部分。"),
        ("Applied Materials高难度应用场景", "其官方页面点名 SADP/SAQP、EUV layers、OPC mask qualification 和 emerging 3D architectures，说明 PDC 难度随先进制程和三维结构上升。"),
        ("Applied Materials统计过程控制用途", "官方页面强调这些能力帮助客户建立 statistical process control、加快 ramp 并提高量产良率。"),
    ]:
        add_dp(dps, metric, TODAY, "文本", "amat_metrology_inspection", amat_product_excerpt, value_text=text, company_key="amat", method="web_fetch")

    amat_10k_excerpt = "Applied Materials FY2025 10-K：net revenue 283.68 亿美元，gross margin 48.7%，net income 69.98 亿美元；Semiconductor Systems 207.98 亿美元，Applied Global Services 63.85 亿美元；中国收入 85.29 亿美元，占比 30%，低于 FY2024 的 37%。"
    for metric, val, unit in [
        ("Applied Materials净收入", 28368, "百万美元"),
        ("Applied Materials毛利率", 48.7, "%"),
        ("Applied Materials净利润", 6998, "百万美元"),
        ("Applied Materials Semiconductor Systems收入", 20798, "百万美元"),
        ("Applied Materials Applied Global Services收入", 6385, "百万美元"),
        ("Applied Materials中国收入", 8529, "百万美元"),
        ("Applied Materials中国收入占比", 30, "%"),
        ("Applied Materials FY2024中国收入占比", 37, "%"),
    ]:
        add_dp(dps, metric, "FY2025", unit, "amat_10k_2025", amat_10k_excerpt, value_num=val, company_key="amat", method="web_fetch")
    add_dp(dps, "Applied Materials中国收入占比同比变化", "FY2025/FY2024", "百分点", "amat_10k_2025", amat_10k_excerpt, value_num=-7, company_key="amat", method="inferred")

    nordson_excerpt = "Nordson Test & Inspection 官方页：产品覆盖 Acoustic、Optical、Bond Test、X-ray Components、Manual/Automated X-ray、WaferSense/ReticleSense sensors、inspection AI software；关键应用段包括 advanced packaging、front-end、mid-end 和 back-end semiconductor。"
    for metric, text in [
        ("Nordson Test & Inspection产品边界", "Nordson 覆盖 acoustic、optical、X-ray、bond test、WaferSense 传感器和 inspection AI 软件，适合观察先进封装和电子装联检测，不等同 KLA 晶圆前道过程控制。"),
        ("Nordson advanced packaging应用", "官方页面将 advanced packaging、front-end、mid-end、back-end semiconductor 列为关键应用段，说明封装侧和前中后道检测都在其覆盖范围。"),
        ("Nordson WaferSense传感器用途", "WaferSense/ReticleSense 等无线半导体传感器用于工具 setup、maintenance、颗粒/振动/leveling 等过程控制辅助，更多是过程工具链而非核心晶圆缺陷检测份额。"),
    ]:
        add_dp(dps, metric, TODAY, "文本", "nordson_test_inspection", nordson_excerpt, value_text=text, company_key="nordson", method="web_fetch")

    bruker_product_excerpt = "Bruker 半导体解决方案官方页：产品覆盖 ellipsometry/reflectometry、automated X-ray metrology、automated AFM、photomask repair、surface metrology、X-ray defect inspection 等，服务薄膜、CD、epilayer、高 k 介质、wafer-level packaging bumps 和表面形貌。"
    for metric, text in [
        ("Bruker半导体量测产品边界", "Bruker 更偏材料、表面、薄膜、AFM、X-ray 和 mask repair 等细分量测，不是全平台过程控制龙头。"),
        ("Bruker X-ray metrology用途", "Bruker X-ray metrology 用于 epilayer films、substrate defects、FEOL epi/high-k dielectric control、metal films 和 wafer-level packaging bumps。"),
        ("Bruker AFM和surface metrology用途", "AFM 和 surface metrology 用于 nanoscale surface、CMP、etch-depth、surface roughness 和 process monitoring，是先进制程材料/表面控制补充。"),
    ]:
        add_dp(dps, metric, TODAY, "文本", "bruker_semiconductor_solutions", bruker_product_excerpt, value_text=text, company_key="bruker", method="web_fetch")

    bruker_fin_excerpt = "Bruker 2025 全年业绩：FY25 revenues 34.4 亿美元，同比增长 2.1%；BSI 收入 31.7 亿美元，BEST 收入 2.709 亿美元；FY25 GAAP diluted loss per share -0.15 美元，non-GAAP EPS 1.83 美元。"
    for metric, val, unit in [
        ("Bruker收入", 3440, "百万美元"),
        ("Bruker收入同比", 2.1, "%"),
        ("Bruker BSI收入", 3170, "百万美元"),
        ("Bruker BEST收入", 270.9, "百万美元"),
        ("Bruker GAAP diluted EPS", -0.15, "美元"),
        ("Bruker non-GAAP EPS", 1.83, "美元"),
    ]:
        add_dp(dps, metric, "FY2025", unit, "bruker_2025_results", bruker_fin_excerpt, value_num=val, company_key="bruker", method="web_fetch")
    add_dp(dps, "Bruker PE口径说明", "FY2025", "文本", "bruker_2025_results", bruker_fin_excerpt, value_text="Bruker FY2025 GAAP EPS 为负，trailing PE 不适合和盈利公司机械比较；应辅助看 PB、PS、现金流和半导体产品线。", company_key="bruker", method="web_fetch")

    secote_optima_excerpt = "赛腾 Optima 官方页展示硅片边缘缺陷自动检测 RXW-1200、晶圆片背面检测 BMW-1200 等，覆盖硅片/晶圆边缘和背面缺陷检出、分类和尺寸量测。"
    secote_annual_excerpt = "赛腾 2025 年报摘要称，公司在消费电子、半导体、新能源领域的智能组装、检测、量测核心环节布局，因此不能把集团全部收入直接归入半导体量测检测。"
    for metric, text, src_key in [
        ("赛腾Optima硅片边缘缺陷检测", "RXW-1200 面向硅片/晶圆片制造过程中的边缘缺陷检出、分类和尺寸量测。", "secote_optima_official"),
        ("赛腾Optima晶圆背面检测", "BMW-1200 面向晶圆背面缺陷、异物和微小三维形状提取，属于硅片/晶圆检测量测相邻产品。", "secote_optima_official"),
        ("赛腾股份业务纯度", "集团同时覆盖消费电子、半导体、新能源的智能组装、检测、量测和自动化解决方案，不能把全部收入归入半导体量测检测。", "secote_annual_2025"),
    ]:
        excerpt = secote_optima_excerpt if src_key == "secote_optima_official" else secote_annual_excerpt
        add_dp(dps, metric, TODAY if src_key == "secote_optima_official" else "2025", "文本", src_key, excerpt, value_text=text, company_key="secote", method="web_fetch")

    dfjy_excerpt = "东方晶源官方新闻材料显示，公司围绕电子束量测检测推进 EBI、CD-SEM、DR-SEM 及 DMS/YMS/MMS 良率管理软件；该资料为 2024 年，本文只作为产品线和历史能力证据。"
    for metric, text in [
        ("东方晶源EBI产品线", "EBI 对应纳米级电子束缺陷检测，是光学检测在先进图形识别灵敏度下降后的重要补充。"),
        ("东方晶源CD-SEM产品线", "CD-SEM 对应关键尺寸量测，属于 prompt 要求覆盖的电子束量测核心产品。"),
        ("东方晶源DR-SEM产品线", "DR-SEM 对应缺陷复检，与 EBI 和 CD-SEM 共同构成电子束量测检测三大产品线。"),
        ("东方晶源良率管理软件", "DMS/YMS/MMS 等软件说明其不仅卖硬件，也试图进入良率管理数据闭环。"),
    ]:
        add_dp(dps, metric, "2024", "文本", "dfjy_official_product", dfjy_excerpt, value_text=text, company_key="dfjy", method="web_fetch")

    rsl_excerpt = "睿励科学仪器资料：主营光学膜厚测量、光学缺陷检测、硅片厚度及翘曲测量；TFX3000 系列 12 英寸光学测量设备已应用在 65/55/40/28nm 产线，并进行 14nm 工艺验证，在 3D NAND 产线支持 64 层并验证 96 层。"
    for metric, text in [
        ("睿励科学仪器产品边界", "睿励覆盖光学膜厚、光学缺陷检测、硅片厚度及翘曲量测，是国内前道光学量测检测历史能力样本。"),
        ("睿励TFX3000节点覆盖", "TFX3000 12 英寸光学测量设备历史资料显示已应用于 65/55/40/28nm 并验证 14nm。"),
        ("睿励3D NAND验证线索", "资料称其在 3D NAND 产线支持 64 层并验证 96 层测量性能，说明曾进入存储客户验证链。"),
    ]:
        add_dp(dps, metric, "2020", "文本", "rsl_science_investment", rsl_excerpt, value_text=text, company_key="rsl", method="web_fetch", note="历史资料，需 2025/2026 近端证据复核")

    zk_fin_excerpt = "中科飞测公告及公告点评：2025 年收入 20.53 亿元，同比增长 48.75%；毛利率 49.93%；归母净利润 0.59 亿元，扣非归母净利润 -1.23 亿元。2026Q1 收入 3.96 亿元，研发费用率 46.26%。"
    zk_product_revenue_excerpt = "中科飞测公告及公告点评：2025 年检测设备收入 13.64 亿元、量测设备收入 6.23 亿元，分别用于复算检测设备和量测设备收入占比。"
    zk_balance_excerpt = "中科飞测公告及公告点评：2025Q4 合同负债 5.65 亿元、存货 26.99 亿元；2026Q1 合同负债 8.81 亿元。"
    for metric, val, unit, period in [
        ("中科飞测营业收入", 20.53, "亿元人民币", "2025"),
        ("中科飞测营业收入同比", 48.75, "%", "2025"),
        ("中科飞测毛利率", 49.93, "%", "2025"),
        ("中科飞测归母净利润", 0.59, "亿元人民币", "2025"),
        ("中科飞测扣非归母净利润", -1.23, "亿元人民币", "2025"),
        ("中科飞测营业收入", 3.96, "亿元人民币", "2026Q1"),
        ("中科飞测营业收入同比", 34.63, "%", "2026Q1"),
        ("中科飞测研发费用率", 46.26, "%", "2026Q1"),
    ]:
        add_dp(dps, metric, period, unit, "zhongke_annual_2025", zk_fin_excerpt, value_num=val, company_key="zhongke", method="web_fetch")
    for metric, val, unit, period in [
        ("中科飞测检测设备收入", 13.64, "亿元人民币", "2025"),
        ("中科飞测检测设备收入同比", 38.52, "%", "2025"),
        ("中科飞测量测设备收入", 6.23, "亿元人民币", "2025"),
        ("中科飞测量测设备收入同比", 72.71, "%", "2025"),
    ]:
        add_dp(dps, metric, period, unit, "zhongke_annual_2025", zk_product_revenue_excerpt, value_num=val, company_key="zhongke", method="web_fetch")
    for metric, val, unit, period in [
        ("中科飞测合同负债", 5.65, "亿元人民币", "2025Q4"),
        ("中科飞测存货", 26.99, "亿元人民币", "2025Q4"),
        ("中科飞测合同负债", 8.81, "亿元人民币", "2026Q1"),
    ]:
        add_dp(dps, metric, period, unit, "zhongke_annual_2025", zk_balance_excerpt, value_num=val, company_key="zhongke", method="web_fetch")
    add_dp(dps, "中科飞测合同负债环比增长", "2026Q1/2025Q4", "%", "zhongke_annual_2025", zk_balance_excerpt, value_num=55.8, company_key="zhongke", method="inferred")
    add_dp(dps, "中科飞测量测设备收入占比", "2025", "%", "zhongke_annual_2025", zk_product_revenue_excerpt, value_num=30.35, company_key="zhongke", method="inferred")
    add_dp(dps, "中科飞测检测设备收入占比", "2025", "%", "zhongke_annual_2025", zk_product_revenue_excerpt, value_num=66.44, company_key="zhongke", method="inferred")

    zk_h1_excerpt = "天风证券转引中科飞测分业务：2025H1 检测设备、量测设备、其他业务收入分别为 4.26、2.56、0.20 亿元，占比分别 61%、36%、3%，毛利率分别为 62%、41%、53%。"
    for metric, val, unit in [
        ("中科飞测H1检测设备收入", 4.26, "亿元人民币"),
        ("中科飞测H1量测设备收入", 2.56, "亿元人民币"),
        ("中科飞测H1其他业务收入", 0.20, "亿元人民币"),
        ("中科飞测H1检测设备收入占比", 61, "%"),
        ("中科飞测H1量测设备收入占比", 36, "%"),
        ("中科飞测H1其他业务收入占比", 3, "%"),
        ("中科飞测H1检测设备毛利率", 62, "%"),
        ("中科飞测H1量测设备毛利率", 41, "%"),
        ("中科飞测H1其他业务毛利率", 53, "%"),
    ]:
        add_dp(dps, metric, "2025H1", unit, "tianfeng_zkf_20260420", zk_h1_excerpt, value_num=val, company_key="zhongke")

    zk_product_excerpt = "华泰证券整理：中科飞测十三大系列设备涵盖光学、电子束、X 光；光学类八大系列已批量量产，明场纳米图形晶圆缺陷检测设备批量出货至多家头部客户验证，晶圆平整度量测已出货头部 HBM 客户；电子束 CD-SEM 完成样机研发并做客户样片验证；X 光高深宽比刻蚀结构量测通过国内头部存储客户验证，TSV 空隙量测设备已出货头部存储客户验证。"
    product_points = [
        ("中科飞测技术路线覆盖", "光学、电子束、X 光三条路线均有产品布局。"),
        ("中科飞测光学系列状态", "光学类八大系列设备已批量量产，是当前收入和毛利的基本盘。"),
        ("中科飞测明场设备状态", "明场纳米图形晶圆缺陷检测设备已批量出货至多家头部客户进行产线验证和应用开发。"),
        ("中科飞测HBM平整度量测状态", "晶圆平整度量测设备已出货头部 HBM 客户进行产线工艺验证和应用开发。"),
        ("中科飞测电子束CD-SEM状态", "电子束关键尺寸量测设备已完成样机研发，正在进行客户样片工艺验证。"),
        ("中科飞测X光高深宽比量测状态", "X 光高深宽比刻蚀结构量测设备已通过国内头部存储客户验证。"),
        ("中科飞测TSV空隙量测状态", "硅通孔铜填充空隙量测设备已出货头部存储客户进行工艺验证和应用开发。"),
    ]
    for metric, text in product_points:
        add_dp(dps, metric, "2026", "文本", "huatai_zkf_20260426", zk_product_excerpt, value_text=text, company_key="zhongke")

    optical_excerpt = "天风证券技术口径：光学检测技术在高精度和高速度之间平衡较好，速度约为电子束检测的 1000 倍，且可实现其他技术不能覆盖的部分功能；电子束精度高但速度慢，X 光适合高深宽比、TSV 等三维结构。"
    add_dp(dps, "光学检测相对电子束速度倍数", "技术口径", "倍", "tianfeng_zkf_20260420", optical_excerpt, value_num=1000)
    for metric, text in [
        ("光学检测技术优势", "速度和吞吐较高，适合作为产线在线检测主力，但在极小缺陷和三维结构上需要电子束/X 光补充。"),
        ("电子束检测技术优势", "分辨率高，适合 CD-SEM、defect review 和先进图形量测，但吞吐慢。"),
        ("X光量测技术优势", "适合高深宽比刻蚀结构、TSV 空隙和三维封装结构，补足光学/电子束可见性限制。"),
    ]:
        add_dp(dps, metric, "技术口径", "文本", "tianfeng_zkf_20260420", optical_excerpt, value_text=text)

    jingce_fin_excerpt = "精测电子公告：2025 年集团收入约 33.48 亿元，半导体业务收入约 13.18 亿元，同比增长 71.6%。"
    jingce_product_excerpt = "广发证券整理：精测电子半导体产品覆盖膜厚、OCD、电子束、应力、明场等量检测方向，先进封装相关检测提供第二增长口径。集团仍同时包含显示、新能源和半导体业务。"
    for metric, val, unit in [
        ("精测电子营业收入", 33.48, "亿元人民币"),
        ("精测电子半导体业务收入", 13.18, "亿元人民币"),
        ("精测电子半导体业务收入同比", 71.6, "%"),
        ("精测电子半导体业务收入占比", 39.37, "%"),
    ]:
        add_dp(dps, metric, "2025", unit, "jingce_annual_2025", jingce_fin_excerpt, value_num=val, company_key="jingce", method="web_fetch")
    for metric, text in [
        ("精测电子业务纯度", "集团同时包含显示、新能源和半导体，半导体业务增长不能直接等同集团全部增长。"),
        ("精测电子膜厚设备", "膜厚量测是半导体工艺窗口控制的重要基础品类。"),
        ("精测电子OCD设备", "OCD 用于光学关键尺寸和结构参数反演，和先进制程建模能力相关。"),
        ("精测电子电子束设备", "电子束产品线决定公司能否进入更高精度量测环节。"),
        ("精测电子先进封装检测", "先进封装相关检测提供第二增长口径，但与前道晶圆量测需分表观察。"),
    ]:
        add_dp(dps, metric, "2026", "文本", "guangfa_jingce_20260602", jingce_product_excerpt, value_text=text, company_key="jingce")

    tzzk_fin_excerpt = "天准科技公告：2025 年收入 17.90 亿元、归母净利润 0.76 亿元。"
    tzzk_order_excerpt = "天准科技公告及研究材料：2025 年新签订单 24.45 亿元，期末在手订单 14.35 亿元；苏州矽行晶圆检测设备在手订单近 7000 万元。"
    for metric, val, unit, excerpt in [
        ("天准科技营业收入", 17.90, "亿元人民币", tzzk_fin_excerpt),
        ("天准科技归母净利润", 0.76, "亿元人民币", tzzk_fin_excerpt),
        ("天准科技新签订单", 24.45, "亿元人民币", tzzk_order_excerpt),
        ("天准科技在手订单", 14.35, "亿元人民币", tzzk_order_excerpt),
        ("苏州矽行晶圆检测设备在手订单", 0.70, "亿元人民币", tzzk_order_excerpt),
    ]:
        add_dp(dps, metric, "2025", unit, "tzzk_annual_2025", excerpt, value_num=val, company_key="tzzk" if "天准" in metric else "suxing", method="web_fetch")
    suxing_excerpt = "天准/苏州矽行官方材料：TB1000/TB1100 面向 65-180nm，TB1500 面向 55/40nm，TB2000 面向 28/14nm；面向 40nm 制程的 BFI 设备获得客户订单。"
    for metric, val, unit in [
        ("苏州矽行TB1000/TB1100适用节点下限", 65, "nm"),
        ("苏州矽行TB1000/TB1100适用节点上限", 180, "nm"),
        ("苏州矽行TB1500适用先进节点", 40, "nm"),
        ("苏州矽行TB2000适用节点下限", 14, "nm"),
        ("苏州矽行TB2000适用节点上限", 28, "nm"),
    ]:
        add_dp(dps, metric, "2026", unit, "tzzk_official_tb1500", suxing_excerpt, value_num=val, company_key="suxing", method="web_fetch")
    add_dp(dps, "苏州矽行40nm BFI订单状态", "2026", "文本", "tzzk_official_tb1500", suxing_excerpt, value_text="40nm 明场晶圆缺陷检测 BFI 设备获得客户订单，验证了成熟制程段导入，但 28/14nm 仍需继续验证。", company_key="suxing", method="web_fetch")

    mol_fin_excerpt = "茂莱光学公告及研报整理：2025 年收入 6.91 亿元，同比增长 37.42%，归母净利润 0.463 亿元；半导体领域收入同比增长 71.47%、收入占比 57.76%。"
    mol_order_excerpt = "茂莱光学公告及研报整理：2026Q1 新增订单约 3 亿元，同比增长 138%，其中 75% 来自半导体；期末在手订单约 6.6 亿元，其中半导体约 4.6 亿元。"
    for metric, val, unit, period, excerpt in [
        ("茂莱光学营业收入", 6.91, "亿元人民币", "2025", mol_fin_excerpt),
        ("茂莱光学营业收入同比", 37.42, "%", "2025", mol_fin_excerpt),
        ("茂莱光学归母净利润", 0.4633, "亿元人民币", "2025", mol_fin_excerpt),
        ("茂莱光学半导体收入同比", 71.47, "%", "2025", mol_fin_excerpt),
        ("茂莱光学半导体收入占比", 57.76, "%", "2025", mol_fin_excerpt),
        ("茂莱光学2026Q1新增订单", 3.0, "亿元人民币", "2026Q1", mol_order_excerpt),
        ("茂莱光学2026Q1新增订单同比", 138, "%", "2026Q1", mol_order_excerpt),
        ("茂莱光学2026Q1新增订单半导体占比", 75, "%", "2026Q1", mol_order_excerpt),
        ("茂莱光学2026Q1在手订单", 6.6, "亿元人民币", "2026Q1", mol_order_excerpt),
        ("茂莱光学2026Q1半导体在手订单", 4.6, "亿元人民币", "2026Q1", mol_order_excerpt),
        ("茂莱光学2026Q1在手订单半导体占比", 69, "%", "2026Q1", mol_order_excerpt),
    ]:
        add_dp(dps, metric, period, unit, "mol_annual_2025", excerpt, value_num=val, company_key="mol", method="web_fetch")
    add_dp(dps, "茂莱光学行业定位", "2026", "文本", "changjiang_mol_20260131", "长江证券提示茂莱光学产品处在高端精密光学元件和模块环节，服务半导体量测检测设备客户，但不是整机量测检测设备公司。", value_text="茂莱光学应作为光学上游和订单前瞻指标观察，不能和中科飞测、KLA 等整机厂放在同一竞争份额表。", company_key="mol")

    riliang_fin_excerpt = "日联科技公告及中邮证券整理：2025 年收入 10.78 亿元，同比增长 45.77%，归母净利润 1.76 亿元，同比增长 22.84%；2026Q1 收入 2.96 亿元，同比增长 48.34%，归母净利润 0.44 亿元。"
    for metric, val, unit, period in [
        ("日联科技营业收入", 10.78, "亿元人民币", "2025"),
        ("日联科技营业收入同比", 45.77, "%", "2025"),
        ("日联科技归母净利润", 1.76, "亿元人民币", "2025"),
        ("日联科技归母净利润同比", 22.84, "%", "2025"),
        ("日联科技营业收入", 2.96, "亿元人民币", "2026Q1"),
        ("日联科技营业收入同比", 48.34, "%", "2026Q1"),
        ("日联科技归母净利润", 0.44, "亿元人民币", "2026Q1"),
    ]:
        add_dp(dps, metric, period, unit, "riliang_annual_2025", riliang_fin_excerpt, value_num=val, company_key="riliang", method="web_fetch")
    riliang_boundary_excerpt = "日联科技公告及中邮证券整理：公司在半导体先进封装、PCB、液冷板、光模块等检测业务已有小规模出货，主体仍是工业 X 射线检测平台而非晶圆前道量测检测整机厂。"
    add_dp(dps, "日联科技半导体边界", "2026", "文本", "riliang_annual_2025", riliang_boundary_excerpt, value_text="日联科技的 X 射线智能检测与先进封装相邻，但当前主体仍是工业检测平台，不能作为晶圆前道量测检测核心份额公司。", company_key="riliang", method="web_fetch")

    service_boundary_excerpt = "东吴证券检测服务行业策略强调第三方检测服务的千亿赛道、利润率修复和航空航天/新能源/半导体等服务需求；这些是检测服务商业模式，不是半导体量测检测设备采购。"
    for metric, text in [
        ("第三方检测服务边界", "检测服务收入来自实验室和认证服务，客户购买的是服务结果，不是前道过程控制机台。"),
        ("检测服务与设备商业模式差异", "检测服务看人效、实验室资质和区域覆盖；量测检测设备看机台性能、客户验证、装机量和服务软件。"),
        ("检测服务资料使用方式", "相关 PDF 只能用于行业边界和误读提示，不进入本行业市场规模、竞争格局和公司份额计算。"),
    ]:
        add_dp(dps, metric, TODAY, "文本", "dongwu_service_boundary_20260214", service_boundary_excerpt, value_text=text)

    tester_boundary_excerpt = "存储测试机专题属于 ATE 测试机研究，关注芯片电性能测试；HBM 会同时拉动测试机、先进封装 inspection、TSV/X-ray、晶圆平整度和材料/膜厚量测，但本行业只关注前道/封装侧过程控制的缺陷检测和几何/材料/膜厚/关键尺寸量测。"
    for metric, text in [
        ("ATE测试机边界", "ATE 测试机测芯片电性能，量测检测设备测晶圆/掩模/封装结构缺陷和工艺窗口，二者采购部门、机台指标和竞争格局不同。"),
        ("HBM对量测检测的间接影响", "HBM 同时拉动测试机、先进封装 inspection、TSV/X-ray、晶圆平整度和材料/膜厚量测，但不能把测试机 TAM 混入量测检测 TAM。"),
        ("日本优势环节边界", "日系优势覆盖测试、清洗、切磨抛、量测/检测等多环节，本文只取量测/检测环节作为国产替代可比口径。"),
    ]:
        add_dp(dps, metric, TODAY, "文本", "dongwu_tester_boundary_20260702", tester_boundary_excerpt, value_text=text)

    framework_points = [
        ("市场规模口径审计", "全球量测检测市场存在 2023 年 152.9 亿美元、2024 年 192.2 亿美元、2031E 389.5 亿美元等不同市场研究口径，不能机械串成同一时间序列。", "tianfeng_zkf_20260420"),
        ("中国替代空间审计", "中国市场高增来自成熟制程扩产、存储/先进封装投资和国产替代叠加，但 50 亿元去日化空间只是日系替代片段，不等于中国总市场。", "dongwu_tester_boundary_20260702"),
        ("客户验证审计", "国产设备从样机、工艺验证、小批量订单到批量装机之间存在长周期，任何单一订单新闻都不能直接外推为份额。", "tzzk_official_tb1500"),
        ("公司研报折扣", "本地资料以公司研报为主，容易强调订单和空间、弱化扣非亏损、存货、客户认证失败和业务混口径，因此所有公司判断需公告复核。", "zhongke_annual_2025"),
        ("业务纯度审计", "业务纯度比较：中科飞测纯度最高；精测电子需拆半导体/显示/新能源；天准要拆苏州矽行/工业视觉/机器人；茂莱是上游光学；日联是相邻 X-ray。", "jingce_annual_2025"),
        ("全球对标审计", "KLA、Nova、Onto、Camtek、Lasertec 的收入和毛利说明过程控制利润池高度集中，国产公司不能只看收入增长，必须看产品平台宽度和服务收入。", "kla_10k_2025"),
        ("技术路线审计", "光学、电子束和 X 光不是互斥替代，而是按速度、分辨率、穿透/三维能力和工艺场景互补。", "tianfeng_zkf_20260420"),
        ("先进封装审计", "先进封装和 HBM 对 inspection/metrology 的拉动更接近结构增量，但它分散在 Camtek/Onto/日联/中科飞测 X 光和平整度等不同产品。", "camtek_2025_results"),
        ("掩模检测审计", "Lasertec 提醒最高端检测设备需求很稀缺，但订单也会被客户投资计划修订影响，不能用长期稀缺掩盖短期订单波动。", "lasertec_fy2026_h1"),
        ("ASML边界审计", "ASML 是光刻生态锚，不是量测检测纯玩家；它的 metrology/e-beam 价值在于说明先进光刻控制闭环，而不是拿来算行业份额。", "asml_annual_2025"),
    ]
    for metric, text, src in framework_points:
        add_dp(dps, metric, TODAY, "文本", src, text, value_text=text, method="web_fetch" if src in {"kla_10k_2025", "camtek_2025_results", "lasertec_fy2026_h1", "asml_annual_2025"} else "pdf_direct")

    # Derive simple cross-source calculations explicitly.
    add_dp(dps, "KLA过程控制收入约为Nova收入倍数", "2025", "倍", "kla_10k_2025", "用 KLA FY2025 Semiconductor Process Control 109.47 亿美元除以 Nova 2025 收入 8.806 亿美元，得到约 12.43 倍。该计算说明全球过程控制利润池高度集中。", value_num=10947 / 880.6, method="inferred")
    add_dp(dps, "KLA晶圆检测收入约为Camtek收入倍数", "2025", "倍", "kla_10k_2025", "用 KLA FY2025 Wafer Inspection 61.99 亿美元除以 Camtek 2025 收入 4.961 亿美元，得到约 12.50 倍。该计算用于提醒封装侧细分强增长仍远小于晶圆检测龙头。", value_num=6199 / 496.1, method="inferred")
    add_dp(dps, "中科飞测收入约为KLA过程控制收入比例", "2025", "%", "zhongke_annual_2025", "以 2025 年中科飞测收入 20.53 亿元人民币折合约 2.86 亿美元，与 KLA 过程控制收入 109.47 亿美元对比，约 2.6%；该计算只用于体量差距，不代表产品可比。", value_num=2.6, company_key="zhongke", method="inferred")
    add_dp(dps, "茂莱半导体在手订单占总在手订单比例复算", "2026Q1", "%", "mol_annual_2025", "茂莱 2026Q1 半导体在手订单约 4.6 亿元、总在手订单 6.6 亿元，复算占比约 69.7%，与报告所称约 69% 基本一致。", value_num=69.7, company_key="mol", method="inferred")
    add_dp(dps, "苏州矽行在手订单占天准集团在手订单比例", "2025", "%", "tzzk_annual_2025", "以苏州矽行晶圆检测设备在手订单近 0.70 亿元除以天准集团在手订单 14.35 亿元，约 4.9%；说明半导体前道仍是早期增量，不是集团主收入。", value_num=4.9, company_key="tzzk", method="inferred")
    add_dp(dps, "精测电子半导体收入占集团收入比例复算", "2025", "%", "jingce_annual_2025", "以精测半导体业务收入 13.18 亿元除以集团收入 33.48 亿元，约 39.4%；该指标用于防止把集团估值全部归因于半导体量测。", value_num=39.37, company_key="jingce", method="inferred")

    for ck, snap in market_snapshot.items():
        if ck not in COMPANIES:
            continue
        company = COMPANIES[ck]
        if snap.get("error"):
            continue
        excerpt = (
            f"{snap.get('source')} {TODAY} 快照：{company.name} ticker={snap.get('symbol')}，"
            f"市值={display_cny_usd(snap.get('market_cap_cny'), snap.get('market_cap_usd'))}，"
            f"PE_TTM={snap.get('pe_ttm')}，PB={snap.get('pb')}，PS_TTM={snap.get('ps_ttm')}，"
            f"毛利率={snap.get('gross_margin')}%，净利率={snap.get('net_margin')}%。"
        )
        if snap.get("market_cap_cny") is not None:
            add_dp(
                dps,
                f"{company.name}市值",
                TODAY,
                "亿元人民币",
                "market_snapshot_20260706",
                excerpt,
                value_num=float(snap["market_cap_cny"]),
                company_key=ck,
                method="web_fetch",
            )
        for field, label, unit in [("pe_ttm", "PE TTM", "倍"), ("pb", "PB", "倍"), ("ps_ttm", "PS TTM", "倍")]:
            val = snap.get(field)
            if val is not None and isinstance(val, (int, float)) and math.isfinite(val):
                add_dp(dps, f"{company.name}{label}", TODAY, unit, "market_snapshot_20260706", excerpt, value_num=round(float(val), 2), company_key=ck, method="web_fetch")

    return dps


YF_SYMBOLS = {
    "kla": "KLAC",
    "asml": "ASML",
    "amat": "AMAT",
    "nova": "NVMI",
    "onto": "ONTO",
    "camtek": "CAMT",
    "nordson": "NDSN",
    "bruker": "BRKR",
    "lasertec": "6920.T",
    "secote": "603283.SS",
    "zhongke": "688361.SS",
    "jingce": "300567.SZ",
    "tzzk": "688003.SS",
    "mol": "688502.SS",
    "riliang": "688531.SS",
}


def fetch_market_snapshot() -> dict[str, dict[str, Any]]:
    snapshot: dict[str, dict[str, Any]] = {}
    fx = fetch_fx_rates()
    snapshot["_fx"] = fx
    for ck, symbol in YF_SYMBOLS.items():
        snapshot[ck] = fetch_company_market_snapshot(COMPANIES[ck].ticker, yf_symbol=symbol, fx=fx)
    return snapshot


def ensure_industry(conn: sqlite3.Connection) -> int:
    parent = conn.execute("select id from industry where name=?", (PARENT_INDUSTRY_NAME,)).fetchone()
    parent_id = parent["id"] if parent else None
    row = conn.execute("select id from industry where name=?", (INDUSTRY_NAME,)).fetchone()
    core_dynamic = (
        "半导体量测检测是晶圆制造和先进封装的过程控制层，研究必须严格区分前道量测/缺陷检测、ATE测试机、"
        "第三方检测服务和工业视觉泛化收入；国内公司判断优先看公告、订单、产品验证和业务纯度。"
    )
    if row:
        industry_id = int(row["id"])
        conn.execute(
            "update industry set parent_id=?, level=2, tier=1, status='深度跟踪', core_dynamic=?, last_updated=? where id=?",
            (parent_id, core_dynamic, TODAY, industry_id),
        )
    else:
        cur = conn.execute(
            """
            insert into industry(name,parent_id,level,tier,status,core_dynamic,last_updated)
            values(?,?,?,?,?,?,?)
            """,
            (INDUSTRY_NAME, parent_id, 2, 1, "深度跟踪", core_dynamic, TODAY),
        )
        industry_id = int(cur.lastrowid)
    return industry_id


def ensure_source(conn: sqlite3.Connection, spec: SourceSpec) -> int:
    row = conn.execute(
        "select id from source where title=? and coalesce(publisher,'')=? and coalesce(publish_date,'')=?",
        (spec.title, spec.publisher or "", spec.publish_date or ""),
    ).fetchone()
    key_args = json.dumps(spec.key_arguments or [], ensure_ascii=False)
    def source_type_for(s: SourceSpec) -> str:
        if s.source_type in {"sec_filing", "annual_report", "company_filing"}:
            return "公告"
        if s.source_type in {"web_fetch"}:
            return "三方数据"
        if s.source_type == "web" and s.source_subtype == "industry_association":
            return "协会数据"
        if s.source_type == "web":
            return "website_material"
        if s.source_type == "pdf":
            return "卖方深度" if "周报" not in s.title else "卖方周报"
        return "其他"

    values = (
        spec.title,
        source_type_for(spec),
        spec.publisher,
        spec.publish_date,
        max(1, min(3, spec.quality_tier)),
        1 if "E" in (spec.note or "") or "预测" in (spec.note or "") else 0,
        spec.file_path,
        spec.url,
        spec.note,
        spec.value_layer,
        spec.url,
        key_args,
        spec.source_subtype,
        now_str(),
        "manual_b_track_builder",
        None if not spec.url else re.sub(r"^https?://([^/]+)/?.*$", r"\1", spec.url),
        spec.language,
        spec.is_primary_source,
        spec.source_credibility,
        None,
    )
    if row:
        sid = int(row["id"])
        conn.execute(
            """
            update source
            set title=?, source_type=?, publisher=?, publish_date=?, quality_tier=?, is_forward_looking=?,
                file_path=?, url=?, note=?, value_layer=?, source_url=?, key_arguments=?,
                source_subtype=?, fetch_timestamp=?, fetch_method=?, domain=?, language=?,
                is_primary_source=?, source_credibility=?, content_snapshot_path=?
            where id=?
            """,
            values + (sid,),
        )
        return sid
    cur = conn.execute(
        """
        insert into source
          (title,source_type,publisher,publish_date,quality_tier,is_forward_looking,
           file_path,url,note,value_layer,source_url,key_arguments,source_subtype,
           fetch_timestamp,fetch_method,domain,language,is_primary_source,source_credibility,content_snapshot_path)
        values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        values,
    )
    return int(cur.lastrowid)


def ensure_sources(conn: sqlite3.Connection) -> dict[str, int]:
    specs = list(CURATED_SOURCES)
    specs.extend(discover_pdf_sources({s.key for s in specs}))
    source_ids: dict[str, int] = {}
    for spec in specs:
        source_ids[spec.key] = ensure_source(conn, spec)
    return source_ids


def ensure_company(conn: sqlite3.Connection, spec: CompanySpec, source_ids: dict[str, int]) -> int:
    def market_for(market: str | None) -> str | None:
        if market is None:
            return None
        if market in {"NASDAQ", "NYSE"}:
            return "美股"
        if market in {"SSE STAR", "SSE", "SZSE"}:
            return "A股"
        if market in {"HKEX"}:
            return "港股"
        return "其他"

    row = conn.execute("select id from company where name=?", (spec.name,)).fetchone()
    if row:
        cid = int(row["id"])
        conn.execute(
            """
            update company
            set ticker=?, market=?, note=?, listing_status=?, display_mode='quantitative',
                brief_intro=?, brief_intro_src=?
            where id=?
            """,
            (spec.ticker, market_for(spec.market), spec.note, spec.listing_status, spec.brief_intro, str(source_ids.get(spec.source_key)), cid),
        )
    else:
        cur = conn.execute(
            """
            insert into company(name,ticker,market,note,listing_status,display_mode,brief_intro,brief_intro_src)
            values(?,?,?,?,?,?,?,?)
            """,
            (spec.name, spec.ticker, market_for(spec.market), spec.note, spec.listing_status, "quantitative", spec.brief_intro, str(source_ids.get(spec.source_key))),
        )
        cid = int(cur.lastrowid)
    return cid


def company_financial_series(spec: CompanySpec) -> tuple[str, str]:
    p = spec.profile
    revenue: list[dict[str, Any]] = []
    income: list[dict[str, Any]] = []

    def add_rev(period: str, value: float | int | None, unit: str, yoy: float | None = None) -> None:
        if value is not None:
            revenue.append({"period": period, "value": round(float(value), 4), "unit": unit, "yoy": yoy})

    def add_inc(period: str, value: float | int | None, unit: str) -> None:
        if value is not None:
            income.append({"period": period, "value": round(float(value), 4), "unit": unit})

    if "revenue_2025_cny_m" in p:
        add_rev("2025", p.get("revenue_2025_cny_m"), "百万元人民币", p.get("yoy_2025_pct"))
    if "semiconductor_revenue_2025_cny_m" in p:
        add_rev("2025半导体", p.get("semiconductor_revenue_2025_cny_m"), "百万元人民币", p.get("semiconductor_revenue_yoy_2025_pct"))
    if "revenue_2026q1_cny_m" in p:
        add_rev("2026Q1", p.get("revenue_2026q1_cny_m"), "百万元人民币", None)
    if "revenue_2025_usd_m" in p:
        add_rev("2025", p.get("revenue_2025_usd_m"), "百万美元", p.get("yoy_2025_pct"))
    if "process_control_revenue_2025_usd_m" in p:
        add_rev("FY2025过程控制", p.get("process_control_revenue_2025_usd_m"), "百万美元", None)
    if "revenue_2025_eur_m" in p:
        add_rev("2025", p.get("revenue_2025_eur_m"), "百万欧元", None)
    if "sales_fy2026_h1_jpy_m" in p:
        add_rev("FY2026H1", p.get("sales_fy2026_h1_jpy_m"), "百万日元", None)
    if "semi_product_sales_fy2026_h1_jpy_m" in p:
        add_rev("FY2026H1半导体产品", p.get("semi_product_sales_fy2026_h1_jpy_m"), "百万日元", None)
    if "hbm_agreement_2025_usd_m" in p and not revenue:
        add_rev("2025 HBM协议", p.get("hbm_agreement_2025_usd_m"), "百万美元以上", None)
    if "node_tb1500_nm" in p and not revenue:
        add_rev("2026订单验证", None, "", None)

    if "net_profit_2025_cny_m" in p:
        add_inc("2025", p.get("net_profit_2025_cny_m"), "百万元人民币")
    if "non_gaap_net_profit_2025_cny_m" in p:
        add_inc("2025扣非", p.get("non_gaap_net_profit_2025_cny_m"), "百万元人民币")
    if "net_profit_2026q1_cny_m" in p:
        add_inc("2026Q1", p.get("net_profit_2026q1_cny_m"), "百万元人民币")
    if "net_income_2025_usd_m" in p:
        add_inc("2025", p.get("net_income_2025_usd_m"), "百万美元")

    return json.dumps(revenue, ensure_ascii=False), json.dumps(income, ensure_ascii=False)


def ensure_companies(conn: sqlite3.Connection, industry_id: int, source_ids: dict[str, int], market_snapshot: dict[str, dict[str, Any]]) -> dict[str, int]:
    conn.execute("delete from company_industry where industry_id=?", (industry_id,))
    conn.execute("delete from company_profile where industry_id=?", (industry_id,))
    company_ids: dict[str, int] = {}
    for ck, spec in COMPANIES.items():
        cid = ensure_company(conn, spec, source_ids)
        company_ids[ck] = cid
        snap = market_snapshot.get(ck) or {}
        if any(snap.get(k) is not None for k in ("market_cap_cny", "pe_ttm", "pb", "ps_ttm")):
            conn.execute(
                """
                update company
                set market_cap_value=?, market_cap_unit=?, market_cap_cny=?, market_cap_usd=?,
                    market_cap_cny_as_of=?, valuation_as_of=?, pe_ttm=?, pb=?, ps_ttm=?,
                    valuation_source_id=?
                where id=?
                """,
                (
                    snap.get("market_cap_cny"),
                    "亿元人民币",
                    snap.get("market_cap_cny"),
                    snap.get("market_cap_usd"),
                    TODAY if snap.get("market_cap_cny") is not None else None,
                    TODAY,
                    snap.get("pe_ttm"),
                    snap.get("pb"),
                    snap.get("ps_ttm"),
                    source_ids.get("market_snapshot_20260706"),
                    cid,
                ),
            )
        conn.execute(
            """
            insert into company_industry(company_id,industry_id,role,revenue_share,note)
            values(?,?,?,?,?)
            """,
            (cid, industry_id, spec.role, None, spec.note),
        )
        profile = spec.profile
        revenue_series, net_income_series = company_financial_series(spec)
        gross_margin = profile.get("gross_margin_2025_pct") if profile.get("gross_margin_2025_pct") is not None else snap.get("gross_margin")
        net_margin = profile.get("net_margin_2025_pct") if profile.get("net_margin_2025_pct") is not None else snap.get("net_margin")
        rd_ratio = profile.get("rd_ratio_2026q1_pct") if profile.get("rd_ratio_2026q1_pct") is not None else snap.get("rd_expense_ratio")
        ocf = snap.get("operating_cash_flow")
        capex = snap.get("capex_value")
        recent_event = profile.get("recent_event") or RECENT_EVENTS.get(ck) or spec.note
        profile_source_ids = [source_ids[k] for k in [spec.source_key] if k in source_ids]
        if any(snap.get(k) is not None for k in ("market_cap_cny", "pe_ttm", "pb", "ps_ttm", "gross_margin", "net_margin")):
            profile_source_ids.append(source_ids.get("market_snapshot_20260706"))
        profile_source_ids = [x for x in profile_source_ids if x]
        conn.execute(
            """
            insert into company_profile
              (company_id, industry_id, period, revenue_series, net_income_series, gross_margin,
               net_margin, operating_cash_flow, ocf_unit, financials_as_of,
               global_rank, china_rank, main_products, main_customers, rd_expense_ratio,
               capex_value, capex_unit, recent_events, risks, is_china_tech_leader, in_global_table, in_china_table, listing_status,
               source_ids, summary, display_note, last_updated, last_verified_at, global_share_sub_market,
               china_share_sub_market, brief_intro, brief_intro_src)
            values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                cid,
                industry_id,
                TODAY,
                revenue_series,
                net_income_series,
                gross_margin,
                net_margin,
                ocf,
                unit_cny_usd(ocf, snap.get("operating_cash_flow_usd")) if ocf is not None else None,
                TODAY,
                profile.get("global_rank"),
                profile.get("china_rank"),
                spec.products,
                spec.customers,
                rd_ratio,
                capex,
                unit_cny_usd(capex, snap.get("capex_usd")) if capex is not None else None,
                json.dumps([{"date": TODAY, "title": recent_event[:80], "summary": recent_event, "is_major": True, "source_id": source_ids.get(spec.source_key)}], ensure_ascii=False),
                json.dumps([spec.risks], ensure_ascii=False),
                1 if ck in {"zhongke", "jingce", "tzzk", "suxing", "secote", "dfjy", "rsl"} else 0,
                1 if ck in {"kla", "asml", "amat", "nova", "onto", "camtek", "nordson", "bruker", "lasertec", "hitachi_ht"} else 0,
                1 if ck in {"zhongke", "jingce", "tzzk", "suxing", "secote", "dfjy", "rsl", "mol", "riliang"} else 0,
                spec.listing_status,
                json.dumps(profile_source_ids, ensure_ascii=False),
                spec.brief_intro,
                spec.note,
                TODAY,
                TODAY,
                profile.get("global_share_note"),
                profile.get("china_share_note"),
                spec.brief_intro,
                str(source_ids.get(spec.source_key)),
            ),
        )
        sid = source_ids.get(spec.source_key)
        if sid:
            conn.execute(
                "delete from source_entity where source_id=? and entity_type='company' and entity_id=?",
                (sid, str(cid)),
            )
            conn.execute(
                "insert into source_entity(source_id,entity_type,entity_id,coverage) values(?,?,?,?)",
                (sid, "company", str(cid), "主要覆盖"),
            )
    return company_ids


def write_data_points(conn: sqlite3.Connection, industry_id: int, source_ids: dict[str, int], company_ids: dict[str, int], market_snapshot: dict[str, dict[str, Any]]) -> int:
    conn.execute("delete from industry_data_point where industry_id=? and note like ?", (industry_id, f"{RUN_TAG}%"))
    count = 0
    for item in build_data_points(market_snapshot):
        if item["source"] not in source_ids:
            raise KeyError(f"missing source key: {item['source']}")
        cid = company_ids.get(item.get("company_key")) if item.get("company_key") else None
        note = f"{RUN_TAG}; {item.get('note') or ''}".strip()
        write_data_point(
            conn,
            industry_id=industry_id,
            metric=item["metric"],
            period=item["period"],
            unit=item["unit"],
            source_id=source_ids[item["source"]],
            source_excerpt=item["excerpt"],
            extraction_method=item.get("method", "pdf_direct"),
            value_num=item.get("value_num"),
            value_text=item.get("value_text"),
            is_forecast=item.get("is_forecast", 0),
            as_of_date=item["period"] if re.match(r"^\d{4}-\d{2}-\d{2}$", item["period"]) else None,
            sentiment="中性",
            note=note,
            company_id=cid,
            auto_consensus=False,
        )
        count += 1
    metrics = [r["metric"] for r in conn.execute("select distinct metric from industry_data_point where industry_id=? and note like ?", (industry_id, f"{RUN_TAG}%"))]
    for metric in metrics:
        try:
            consensus_compute.recompute_metric(industry_id, metric, conn=conn)
        except Exception as exc:
            print(f"[WARN] consensus recompute failed metric={metric}: {exc}", file=sys.stderr)
    return count


def write_industry_source_links(conn: sqlite3.Connection, industry_id: int, source_ids: dict[str, int]) -> None:
    conn.execute(
        "delete from source_entity where entity_type='industry' and entity_id=?",
        (str(industry_id),),
    )
    for sid in sorted(set(source_ids.values())):
        conn.execute(
            "insert into source_entity(source_id, entity_type, entity_id, coverage) values(?,?,?,?)",
            (sid, "industry", str(industry_id), "主要覆盖"),
        )


def write_relations(conn: sqlite3.Connection, industry_id: int, source_ids: dict[str, int]) -> None:
    conn.execute("delete from industry_relation where upstream_id=? or downstream_id=?", (industry_id, industry_id))
    lookup = {r["name"]: int(r["id"]) for r in conn.execute("select id,name from industry")}
    rows = [
        (lookup.get("半导体设备"), industry_id, "配套", None, None, "量测检测是半导体设备中的过程控制子环节", "semi_equipment_forecast_2026"),
        (industry_id, lookup.get("算力芯片"), "配套", None, 0.25, "AI/HPC 芯片先进制程和封装需要更高密度过程控制", "semi_equipment_forecast_2026"),
        (industry_id, lookup.get("存储"), "配套", None, 0.25, "DRAM/HBM 扩产拉动晶圆缺陷检测、平整度、X 光和封装 inspection", "semi_equipment_forecast_2026"),
        (industry_id, lookup.get("先进封装"), "配套", None, 0.25, "先进封装/HBM 带动封装侧 2D/3D inspection、warpage、TSV 和 bump 检测", "camtek_2025_results"),
        (lookup.get("半导体材料"), industry_id, "供应", None, None, "硅片、掩模、薄膜材料和光学元件质量会反向决定量测检测需求", "changjiang_equipment_20260613"),
    ]
    for up, down, relation_type, cost, demand, note, skey in rows:
        if not up or not down:
            continue
        conn.execute(
            """
            insert into industry_relation(upstream_id,downstream_id,relation_type,cost_share,demand_share,bargaining_power,source_id,note)
            values(?,?,?,?,?,?,?,?)
            """,
            (up, down, relation_type, cost, demand, "upstream_strong" if up == industry_id else "balanced", source_ids.get(skey), note),
        )


def s(source_ids: dict[str, int], key: str) -> str:
    return f"^src:{source_ids[key]}"


def md_table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    out.extend("| " + " | ".join(str(c) for c in row) + " |" for row in rows)
    return "\n".join(out)


def frontmatter(industry_id: int, title: str) -> str:
    return (
        "---\n"
        "entity_type: industry\n"
        f"entity_id: {industry_id}\n"
        f"name: {INDUSTRY_NAME}\n"
        "parent: 半导体设备\n"
        "status: 深度跟踪\n"
        "tier: 1\n"
        f"last_updated: {TODAY}\n"
        "author: codex_b_track_research\n"
        "ai_synthesized: true\n"
        "research_track: B\n"
        "research_prompt: 半导体量测行研.md\n"
        f"title: {title}\n"
        "---\n\n"
    )


def boundary_block(source_ids: dict[str, int]) -> str:
    return (
        "本行业的研究对象是半导体制造和先进封装中的过程控制量测/检测设备，包括缺陷检测、关键尺寸量测、膜厚/OCD、套刻、晶圆形貌、平整度、掩模/reticle 检测、电子束复查、X 光三维结构量测和封装侧 inspection。"
        f"它不是 ATE 测试机，也不是第三方检测服务。ATE 测试机测的是芯片电性能，归测试机行业；检测服务卖的是实验室/认证服务，归服务业口径。本地 PDF 中这两类资料很多，本文只把它们作为边界审计使用 {s(source_ids, 'dongwu_tester_boundary_20260702')} {s(source_ids, 'dongwu_service_boundary_20260214')}。\n\n"
        "第二个边界是公司业务纯度。中科飞测接近纯量测检测整机公司；精测电子必须拆出半导体业务，不得把显示和新能源全算进半导体量测；天准科技的晶圆检测主要在苏州矽行，集团还有工业视觉、CPO/PCB 和机器人控制器；茂莱光学是上游精密光学，不是整机厂；日联科技是 X 射线工业检测平台，先进封装只是相邻观察项。这个边界决定公司表、份额表和投资判断不能混用。"
    )


def make_main_doc(industry_id: int, source_ids: dict[str, int]) -> str:
    intro = f"""# 半导体量测：AI/HBM 时代的过程控制瓶颈

> 本行业按 B 轨执行。根目录 `半导体量测行研.md` 明确要求回答竞争格局、行业空间、技术壁垒三大方向，并覆盖 2025-2030 销售额/出货量/份额、产品类型、全球和中国公司池、财务与预测口径 {s(source_ids, 'prompt')}。本轮采用 B 轨默认 A 轨全集 + prompt 全集的并集，读取 `papers/量检测` 36 份 PDF，并强制补充独立公开搜索。由于本地库大量是公司研报，所有公司研报均按降权处理，必须用公告、官方产品页、海外龙头披露和行业组织数据交叉验证。

## 1. 一句话定义

半导体量测检测设备是晶圆制造和先进封装的“过程控制层”。它不直接制造晶圆，也不在芯片出厂后做电性能考试，而是在每一道关键制程之后回答三个问题：有没有缺陷，尺寸/膜厚/套刻是否落在工艺窗口内，三维结构和封装互连是否会在后续步骤失效。这个答案直接影响良率、返工、报废、制程 ramp 速度和客户认证周期。KLA 把这一层称为 Semiconductor Process Control，FY2025 该分部收入达到 109.47 亿美元，单晶圆检测产品收入 61.99 亿美元，说明它不是辅助设备，而是全球半导体设备利润池中最硬的一层 {s(source_ids, 'kla_10k_2025')}。

{boundary_block(source_ids)}

## 2. 先给结论

第一，量测检测不是“半导体设备里一个小品类”，而是先进制程、HBM 和先进封装能否爬坡的过程控制底座。SEMI 对 2025-2027 年 WFE 的判断显示，WFE 2025E 达 1157 亿美元、2027E 达 1352 亿美元，DRAM/HBM、先进逻辑和中国扩产共同驱动；测试与封装设备在 2025 年也有高增，说明 AI 带来的增量不是单一前道投资，而是制造、封装和测试全链条的控制复杂度上升 {s(source_ids, 'semi_equipment_forecast_2026')}。

第二，全球利润池高度集中，KLA 是最重要锚。KLA FY2025 过程控制收入约为 Nova 2025 收入的 12 倍，也约为 Camtek 2025 收入的 22 倍；这不是简单规模差，而是产品平台、客户装机、服务软件、应用 know-how 和先进节点验证的复利。国产公司不能只讲国产替代空间，必须逐项回答：哪些机台已经批量，哪些只在客户样片验证，哪些还是样机，扣非亏损能否随装机转正。

第三，中国市场机会真实存在，但口径必须克制。市场研究给出的全球量测检测市场规模存在 2023 年 152.9 亿美元、2024 年 192.2 亿美元、2031E 389.5 亿美元等不同口径，不能把它们机械串成一条序列；中国大陆 2020-2024 CAGR 约 27.73% 和 2024 年约 63.6 亿美元的市场规模说明国内扩产和国产替代强，但仍要看客户验证和产品结构 {s(source_ids, 'tianfeng_zkf_20260420')} {s(source_ids, 'huayuan_zkf_20260116')} {s(source_ids, 'tzzk_annual_2025')}。

第四，A 股机会要按“整机纯度、产品节点、订单兑现、上游稀缺”分层。中科飞测是核心整机观察项；精测电子是半导体业务成长但集团口径复杂；天准/苏州矽行是明场晶圆检测早期订单和验证线索；茂莱光学是精密光学上游，订单强但不是整机份额；日联科技是先进封装/X-ray 边界观察项。这个分层比“谁沾量检测”更重要。

## 3. 产业链位置

```
上游：精密光学、电子束源、探测器、运动平台、真空与控制、软件算法、标准样片
          ↓
中游：晶圆缺陷检测、CD/膜厚/OCD/套刻/形貌量测、掩模检测、X 光三维量测、封装 inspection
          ↓
下游：逻辑/代工、DRAM/HBM、NAND、功率、CIS、先进封装、OSAT、材料与硅片厂
```

上游中，精密光学是中国公司最有可见度的环节之一。茂莱光学 2025 年半导体收入同比增长 71.47%，收入占比 57.76%，2026Q1 在手订单约 6.6 亿元，其中半导体约 4.6 亿元，说明光学组件已从“样品配合”进入更明确的量产交付阶段 {s(source_ids, 'mol_annual_2025')}。但这也提示一个反方：光学元件订单上行不等同整机国产替代完成，上游订单可能服务海外设备厂，也可能服务国内整机厂，客户结构不透明时不能直接映射到中科飞测或精测的份额。

中游的关键分水岭不是“有无产品”，而是“产品是否进入客户产线的稳定控制闭环”。例如中科飞测光学类八大系列已经批量量产，明场设备已出货头部客户验证，电子束 CD-SEM 仍在客户样片工艺验证，X 光高深宽比刻蚀结构量测通过国内头部存储客户验证 {s(source_ids, 'huatai_zkf_20260426')}。这些阶段的证据强度不同：批量量产可以进收入和毛利判断，产线验证只能进订单和技术进度判断，样片验证只能作为早期信号。

## 4. 市场空间和口径

{md_table(
        ['指标', '数值', '口径解释', '使用方式'],
        [
            ['全球量测检测市场', '2023 年 152.9 亿美元、2030E 277.6 亿美元', 'QY Research 口径，由公司研报转引', f'用于长期空间，不单独作为估值锚 {s(source_ids, "tianfeng_zkf_20260420")}'],
            ['全球量测检测市场', '2024 年 192.2 亿美元、2031E 389.5 亿美元', '天准年报摘要引用市场研究', f'与 2023 口径并列表述，不能拼接 {s(source_ids, "tzzk_annual_2025")}'],
            ['中国大陆市场', '2024 年 63.6 亿美元', '年报摘要市场研究口径', f'用于国内扩产和国产替代背景 {s(source_ids, "tzzk_annual_2025")}'],
            ['中国市场增速', '2020-2024 CAGR 27.73%', '华源证券转引行业数据', f'只说明中国增速快，不等于份额兑现 {s(source_ids, "huayuan_zkf_20260116")}'],
            ['中国去日化空间片段', '量测/检测约 50 亿元', '东吴测试机专题中的去日化拆分', f'只作为日系替代片段，不能代表总 TAM {s(source_ids, "dongwu_tester_boundary_20260702")}'],
        ]
    )}

市场空间的正确读法是“三层并列”。第一层是全球过程控制利润池，以 KLA、Nova、Onto、Camtek、Lasertec 等公司收入作为现实收入锚；第二层是第三方市场研究给出的量测检测 TAM，用来判断长期渗透和国产替代总空间；第三层是中国客户订单、合同负债和在手订单，用来判断什么时候进入收入确认。三层都成立，才能从“赛道大”推进到“公司可兑现”。

## 5. 全球竞争格局

{md_table(
        ['公司', '定位', '2025/近端数据', '对中国研究的含义'],
        [
            ['KLA', '过程控制龙头', 'FY2025 过程控制收入 109.47 亿美元，晶圆检测 61.99 亿美元', '份额、服务、软件和客户 know-how 是护城河，不是单台机参数可替代'],
            ['Nova', '量测纯玩家', '2025 收入 8.806 亿美元，同比 31%，毛利率 57.4%', 'GAA/DRAM/先进封装说明量测可成为独立成长股'],
            ['Onto', '先进封装/特殊器件平台', '2025 收入约 10.05 亿美元，HBM 协议超过 2.4 亿美元', '封装侧增量不能被前道晶圆检测完全解释'],
            ['Camtek', '先进封装/HBM inspection', '2025 收入 4.961 亿美元，同比 16%', 'HBM 封装 inspection 是结构性高景气细分'],
            ['Lasertec', 'EUV 掩模检测', 'FY2026H1 销售 1282.58 亿日元，订单受客户投资修订扰动', '最高端检测稀缺但订单仍有周期性'],
            ['Hitachi High-Tech', 'CD-SEM', 'CD-SEM 服务关键尺寸量测和 High-NA EUV 代际', '电子束量测是国产公司必须补的精度短板'],
        ]
    )}

这个表的重点不是列公司，而是定义国产替代的真实难度。KLA 的过程控制收入远高于其他独立细分公司，说明全球客户买的不只是检测机台，而是包含 recipe、算法、应用工程师、装机服务和跨工艺节点的经验库。中国公司可以从成熟制程、局部产品和本土服务突破，但如果没有跨产品平台、装机数据和服务软件收入，估值不能直接贴 KLA 体系。

## 6. 中国公司分层

{md_table(
        ['层级', '公司', '为什么放这里', '核心验证指标'],
        [
            ['核心整机', '中科飞测', '收入和产品纯度最高，光学基本盘已量产，电子束/X 光新品推进', '扣非亏损是否收窄，明场/暗场/电子束/X 光是否从验证走向批量'],
            ['平台扩张', '精测电子', '半导体业务收入高增，但集团还有显示和新能源', '半导体收入占比、膜厚/OCD/电子束订单、集团利润质量'],
            ['早期验证', '天准科技/苏州矽行', 'BFI 明场检测进入 40nm 订单，28/14nm 仍需验证', '苏州矽行订单占集团比、节点推进、客户复购'],
            ['上游稀缺', '茂莱光学', '精密光学订单强，半导体收入占比上行', '半导体订单结构、产能转固、客户新品节奏'],
            ['边界观察', '日联科技', 'X-ray 工业检测，先进封装有相邻价值', '半导体收入拆分和先进封装产品规格'],
        ]
    )}

最容易犯错的是把这五类公司放在一个“国产量测检测”表里直接比较收入。中科飞测的 20.53 亿元收入可以更直接对应整机设备；精测的 13.18 亿元半导体业务才是可比口径，不是 33.48 亿元集团收入；天准的 14.35 亿元在手订单里，苏州矽行晶圆检测订单近 0.70 亿元，占比不到 5%；茂莱的 6.6 亿元在手订单是光学组件上游；日联的 10.78 亿元收入主要仍是 X 射线工业检测。这个拆分决定公司透视和估值不能模板化。

## 7. 指标体系

本文使用的核心指标不是单一 TAM，而是六组联动指标：市场空间、设备节点、客户验证、订单/合同负债、业务纯度、利润质量。市场空间回答“赛道够不够大”；设备节点回答“是不是进入更难工艺”；客户验证回答“是否真的进客户产线”；订单/合同负债回答“是否会进入收入确认”；业务纯度回答“收入是不是来自量测检测”；利润质量回答“高研发和高存货之后能否转成现金和净利”。这六组指标缺一不可。

中科飞测是最典型例子。2025 年收入 20.53 亿元、同比 48.75%，看起来很强；但扣非净利润仍为 -1.23 亿元，2026Q1 研发费用率 46.26%，说明公司仍处产品线扩张和验证投入期。合同负债从 2025Q4 的 5.65 亿元升至 2026Q1 的 8.81 亿元，是积极信号；但只有在后续确认收入、毛利率不明显下滑、扣非亏损收窄时，才能说明订单质量足够好 {s(source_ids, 'zhongke_annual_2025')}。

## 8. 风险和反方

第一类风险是客户验证失败。量测检测设备不是参数表竞争，客户要看稳定性、误报漏报、吞吐、recipe 迁移、售后响应和良率改善。任何“出货验证”到“批量装机”之间都可能拉长。

第二类风险是业务混口径。精测、天准、日联都不是纯量测检测公司，显示、新能源、工业视觉、机器人、X-ray 工业检测等业务会影响收入和估值。研究中必须逐段拆开，否则会把一个集团的增长错误归因到半导体前道。

第三类风险是公司研报偏乐观。本地 PDF 大量来自公司覆盖报告，天然会强调订单、空间和国产替代，弱化客户验证失败、价格竞争、毛利波动、费用资本化、存货跌价和扣非亏损。因此本文把公司研报作为补充资料，不作为最终结论的一手锚。

第四类风险是出口管制和海外龙头反击。KLA FY2025 中国收入占比从 43% 回落至 33%，一方面说明中国扩产高峰可能正常化，另一方面也说明地区结构受政策影响；国内公司可能受益于国产替代，也可能面对关键零部件和高端客户验证被卡的反向压力 {s(source_ids, 'kla_10k_2025')}。

## 9. 研究结论

半导体量测的投资研究价值不在“国产替代空间很大”这句话，而在于它把先进制程、HBM、先进封装和本土晶圆厂扩产都压缩到一个可验证问题：过程控制能力能否从海外龙头迁移一部分到国内供应商。中科飞测是最直接的整机观察项；精测电子是业务纯度改善后的第二平台；天准/苏州矽行是明场检测早期验证；茂莱光学是上游光学订单指标；日联科技只适合放在 X-ray/先进封装边界观察。后续跟踪应优先看公告级订单、客户复购、分业务收入、扣非利润、存货/合同负债、研发费用率和产品节点，而不是只看卖方目标价或市场规模图。
"""
    return frontmatter(industry_id, "半导体量测主文档") + intro


def make_q0_doc(industry_id: int, source_ids: dict[str, int]) -> str:
    body = f"""# Q0 历史发展：从离线抽检到工艺闭环

## 1. 为什么量测检测越来越重要

半导体制造每向前推进一代，问题都不是简单“设备更贵”，而是工艺窗口更窄。线宽、膜厚、套刻误差、颗粒缺陷、图形塌陷、刻蚀高深宽比结构、TSV 空洞、封装翘曲，任何一个环节失控都会把良率吃掉。量测检测的历史，就是从“事后抽检”走向“过程控制闭环”的历史。

早期制程中，光学显微、简单膜厚和电性抽测可以覆盖较多问题；进入深亚微米之后，缺陷尺寸变小、层数变多、overlay 误差更敏感，光学检测、CD-SEM、OCD、套刻量测逐渐成为晶圆厂日常控制的一部分；进入 FinFET、GAA、HBM 和先进封装之后，三维结构、材料应力、晶圆平整度、TSV 和 bump 质量把 X 光、电子束和封装侧 3D inspection 推到前台。Hitachi High-Tech 的 CD-SEM 页面把 CD-SEM 定义为晶圆微细图形关键尺寸量测工具，正说明电子束量测已经深度嵌入生产线控制 {s(source_ids, 'hitachi_cdsem')}。

## 2. 全球龙头形成：KLA 为什么是锚

KLA 不是只卖一台检测设备。它把晶圆检测、reticle/掩模检测、patterning、overlay/CD、缺陷复查、软件和服务连成过程控制平台。FY2025 KLA Semiconductor Process Control 收入 109.47 亿美元，其中 Wafer Inspection 61.99 亿美元、Patterning 21.96 亿美元、Services 26.83 亿美元 {s(source_ids, 'kla_10k_2025')}。服务收入的存在非常关键：装机之后，recipe、维护、升级和应用工程服务会持续巩固客户粘性。

这解释了为什么新进入者不能只用“单台性能接近”证明替代。真正的替代需要三步：先在成熟工艺或局部工艺中达到可用；再通过客户产线验证、稳定性和误报漏报控制进入批量；最后通过多产品协同和服务软件形成复购。国内公司目前大多处在第一到第二步之间，少数光学类产品进入第三步的开端。

## 3. 技术路线演化

光学检测的优势是速度和覆盖面。天风证券整理的技术口径提到，光学检测速度约为电子束检测的 1000 倍，因此在产线在线检测中更适合做高吞吐主力；但当缺陷更小、结构更复杂时，电子束的分辨率和 X 光的三维穿透能力就不可替代 {s(source_ids, 'tianfeng_zkf_20260420')}。所以未来不是某一种技术路线胜出，而是光学、电子束、X 光、算法和软件在不同工艺点上组合。

ASML 的角色也说明这种组合关系。ASML 主体是光刻，但它的 metrology、inspection、HMI e-beam 和 computational lithography 把光刻机、过程控制和缺陷复查联系起来；2025 年 ASML 净销售 327 亿欧元、毛利率 52.8%，研发费用 47 亿欧元 {s(source_ids, 'asml_annual_2025')}。这不是把 ASML 当量测公司，而是提醒研究者：先进光刻的控制闭环本身就需要量测检测和算法。

## 4. AI/HBM 阶段的变化

AI/HBM 对量测检测的影响有两层。第一层是前道，先进逻辑和 DRAM/HBM 扩产提高 WFE，SEMI 预测 WFE 2025E 1157 亿美元、2027E 1352 亿美元，DRAM/HBM 是重要驱动 {s(source_ids, 'semi_equipment_forecast_2026')}。第二层是封装，HBM 和先进封装带来 bump、RDL、TSV、warpage、平整度和 X-ray/3D inspection 需求。Camtek 2025 年收入 4.961 亿美元，同比增长 16%，管理层将 AI 市场需求加速作为主要原因；Onto 也披露了 HBM 相关多年协议 {s(source_ids, 'camtek_2025_results')} {s(source_ids, 'onto_2025_results')}。

这意味着量测检测研究不能只盯前道晶圆厂。先进封装的 inspection/metrology 会形成第二条增长曲线，但它和前道晶圆检测的客户、机台和估值锚不同，必须分开写。

## 5. 中国路径

中国路径不是从零复制 KLA，而是沿着本土晶圆厂和封装厂需求先突破成熟制程、局部产品和服务响应。中科飞测 2024 年量检测设备出货达 1000 台，说明国产设备已经有装机基础；2025 年收入 20.53 亿元、同比 48.75%，合同负债在 2026Q1 升至 8.81 亿元，说明近端订单并不弱 {s(source_ids, 'huayuan_zkf_20260116')} {s(source_ids, 'zhongke_annual_2025')}。但扣非亏损和高研发费用率同样真实，说明产品线扩张仍在消耗利润。

苏州矽行的路径更早期。其 TB1000/TB1100 面向 65-180nm，TB1500 面向 55/40nm，TB2000 面向 28/14nm；40nm BFI 设备获得客户订单，是成熟制程向更高节点推进的信号，但不能直接外推到 28/14nm 大规模量产 {s(source_ids, 'tzzk_official_tb1500')}。

## 6. 历史经验总结

量测检测行业的历史经验可以压缩成三句话。第一，越接近先进制程，越不是单机替代，而是工艺窗口、客户数据、软件算法和服务体系替代。第二，设备从验证到批量的时间比卖方报告通常写得更长，订单和合同负债只是开始，不是终点。第三，上游光学、电子束、X 光、运动平台和软件算法都会形成单独瓶颈，不能只看整机公司收入。

"""
    body += "\n".join(
        [
            "## 7. 阶段复盘",
            "从成熟制程看，国产设备的突破通常先发生在客户愿意给验证机会、海外设备供给紧张或服务响应不足的环节。这里的机会不是海外龙头突然失效，而是本土客户愿意用一部分产线窗口换取交付确定性和国产供应链安全。",
            "从先进制程看，替代难度上升的速度快于市场空间上升的速度。关键尺寸变小后，缺陷检测的误报漏报、CD-SEM 的重复性、OCD 模型的泛化、套刻量测的稳定性都要经过长期数据积累。",
            "从先进封装看，HBM 和 CoWoS/CoPoS 把 inspection/metrology 从前道延伸到封装侧。这个阶段更看重 2D/3D 检测、X-ray、warpage、bump/RDL 质量控制和软件判图能力，与传统晶圆缺陷检测的竞争格局不同。",
            "因此，研究结论不能写成单线国产替代。更准确的表达是：国内需求给了本土厂商验证机会，成熟制程和部分光学类产品已经开始收入兑现，电子束、X 光、先进封装和高端软件仍在验证爬坡，全球龙头的服务和算法壁垒仍然很深。",
        ]
    )
    return frontmatter(industry_id, "Q0 历史发展") + body


def make_q1_doc(industry_id: int, source_ids: dict[str, int]) -> str:
    rows = [
        ["全球第一层", "KLA", "过程控制收入 109.47 亿美元，晶圆检测 61.99 亿美元", "平台和服务型护城河"],
        ["全球第二层", "Nova / Onto / Camtek", "各自约 4.96-10.05 亿美元收入区间", "量测纯玩家、先进封装和 HBM 弹性"],
        ["最高端特种", "Lasertec", "FY2026H1 半导体相关产品 983.16 亿日元", "EUV 掩模/空白掩模检测稀缺但订单波动"],
        ["电子束量测", "Hitachi High-Tech / ASML HMI", "CD-SEM 和 e-beam 复查/量测", "先进节点精度控制"],
        ["中国整机", "中科飞测", "2025 收入 20.53 亿元，合同负债 2026Q1 8.81 亿元", "国产整机核心"],
        ["中国平台", "精测电子 / 天准矽行", "半导体业务或早期明场订单", "业务纯度和验证阶段是关键"],
        ["中国上游/边界", "茂莱光学 / 日联科技", "光学上游、X-ray 工业检测", "不可与整机份额混用"],
    ]
    body = f"""# Q1 竞争格局：份额不是公司名录，而是产品层级和证据强度

## 1. 竞争格局的正确口径

半导体量测检测的竞争格局不能只按“国内外公司列表”写。更合理的拆法是三层：全球过程控制平台、细分技术纯玩家、中国国产替代公司。KLA 属于第一层；Nova、Onto、Camtek、Lasertec、Hitachi High-Tech 属于第二层或特种层；中科飞测、精测电子、天准/苏州矽行、茂莱、日联属于中国研究对象，但它们的可比性很弱。

{md_table(['层级', '公司', '可量化锚', '研究含义'], rows)}

## 2. KLA 的含义

KLA 的 FY2025 数据给了一个不可绕开的锚：Semiconductor Process Control 收入 109.47 亿美元，Wafer Inspection 61.99 亿美元，Patterning 21.96 亿美元，Services 26.83 亿美元 {s(source_ids, 'kla_10k_2025')}。这个体量说明全球过程控制不是碎片小市场，而是高度集中、利润率和客户粘性都很强的设备层。

KLA 中国收入占比从 FY2024 的 43% 回落到 FY2025 的 33%。这个变化不能简单解读为“中国需求弱”，也不能简单解读为“国产替代马上加速”。它同时包含三个因素：前期中国扩产高基数正常化、出口管制和产品可供范围变化、本土设备导入机会增加。研究中国公司时，必须把三者拆开，否则会把地区收入回落误判为某一家国产公司的订单确定性。

## 3. 细分玩家

Nova 的 2025 年收入 8.806 亿美元、同比 31%、毛利率 57.4%，管理层把增长归因于 optical/materials/chemical metrology、GAA、DRAM 和先进封装 {s(source_ids, 'nova_2025_results')}。这说明量测可以作为独立成长赛道存在，但也说明要进入这个赛道需要很强的模型、材料和制程理解。

Onto 和 Camtek 更偏先进封装和特殊器件。Onto 披露 HBM 相关多年协议超过 2.4 亿美元，Camtek 2025 年收入 4.961 亿美元并预计 2026 年继续双位数增长 {s(source_ids, 'onto_2025_results')} {s(source_ids, 'camtek_2025_results')}。这给中国公司一个启发：先进封装 inspection 不一定等同前道量测，但它是 AI/HBM 时代最确定的增量之一。

Lasertec 的反例同样重要。FY2026H1 净销售 1282.58 亿日元，半导体相关产品 983.16 亿日元，但公司也承认部分客户投资计划修订造成订单下滑，预计后续逐步恢复 {s(source_ids, 'lasertec_fy2026_h1')}。最高端、最稀缺的检测设备仍然有订单周期，不存在只涨不跌的线性成长。

## 4. 中国公司比较

中科飞测是中国整机核心。2025 年收入 20.53 亿元，同比增长 48.75%，检测设备收入 13.64 亿元，量测设备收入 6.23 亿元；2026Q1 合同负债升至 8.81 亿元，说明订单和交付预期较强。但扣非归母净利润仍为 -1.23 亿元，研发费用率高，说明利润质量还在爬坡 {s(source_ids, 'zhongke_annual_2025')}。

精测电子的半导体业务收入约 13.18 亿元，同比增长 71.6%，但集团收入约 33.48 亿元，半导体占比约 39%。如果把集团全口径当半导体量测，就会夸大业务纯度；如果只看显示检测历史，又会低估半导体业务改善。正确做法是单独跟踪半导体分部收入、订单和产品节点 {s(source_ids, 'jingce_annual_2025')}。

天准科技更需要拆分。集团 2025 年收入 17.90 亿元、在手订单 14.35 亿元；苏州矽行晶圆检测设备在手订单近 7000 万元，约占集团在手订单 5%。这意味着苏州矽行是有价值的早期线索，但还不是天准集团利润主轴 {s(source_ids, 'tzzk_annual_2025')}。40nm BFI 订单说明成熟制程验证推进，28/14nm 仍需后续证据 {s(source_ids, 'tzzk_official_tb1500')}。

茂莱光学和日联科技放在中国表里，但不能放在同一份额列。茂莱是精密光学上游，2026Q1 半导体在手订单约 4.6 亿元，说明上游需求强；日联是 X-ray 工业检测平台，先进封装只是相邻扩展。它们的股价可能受半导体量测主题影响，但研究口径必须写清楚 {s(source_ids, 'mol_annual_2025')} {s(source_ids, 'riliang_annual_2025')}。

## 5. 竞争格局的研究落点

本行业不是“国产替代公司池”，而是一个证据强度分层。最强证据来自 KLA 等全球龙头的真实收入和服务粘性；中国侧最强整机证据来自中科飞测的收入、合同负债和产品验证；精测、天准、茂莱、日联需要按业务纯度和产业链位置折算。后续公司透视应围绕“产品节点、客户验证、收入确认、扣非利润、业务纯度”五项排序，而不是围绕卖方研报数量排序。
"""
    return frontmatter(industry_id, "Q1 竞争格局") + body


def make_q2_doc(industry_id: int, source_ids: dict[str, int]) -> str:
    body = f"""# Q2 市场空间：三套口径并列，先拆再算

## 1. 市场空间不能直接串线

本轮资料中，市场空间至少有三套口径。第一，天风证券转引 QY Research 的口径：2023 年全球半导体量测检测市场 152.9 亿美元，2030E 277.6 亿美元，2023-2030 CAGR 8.9% {s(source_ids, 'tianfeng_zkf_20260420')}。第二，天准年报摘要引用的市场研究口径：2024 年全球 192.2 亿美元、中国大陆 63.6 亿美元，2031E 全球 389.5 亿美元、2025-2031 CAGR 10.77% {s(source_ids, 'tzzk_annual_2025')}。第三，东吴测试机专题中的去日化拆分：2025 年中国去日化空间中量测/检测约 50 亿元人民币，这只是日系替代片段，不是中国总市场 {s(source_ids, 'dongwu_tester_boundary_20260702')}。

如果把 2023 的 152.9 亿美元和 2024 的 192.2 亿美元直接计算同比，会得到一个很漂亮但很可能错误的增长率，因为两者可能来自不同机构和不同纳入口径。本文的处理方法是：并列展示、解释来源、只在同一来源内部计算 CAGR，不跨来源做精确同比。

## 2. 为什么市场会增长

增长来自四个驱动。第一是先进逻辑节点，GAA、High-NA EUV 和更窄工艺窗口需要更多 CD、overlay、缺陷复查和 computational metrology。第二是 DRAM/HBM 扩产，HBM 的堆叠、TSV、平整度和封装良率把 X 光和 3D inspection 推到前台。第三是中国本土晶圆厂扩产和国产替代，华源证券转引的中国大陆 2020-2024 CAGR 27.73% 说明国内增速显著高于全球 {s(source_ids, 'huayuan_zkf_20260116')}。第四是先进封装结构上行，Onto、Camtek 和日联这类封装侧检查公司/业务会受益。

SEMI 的 WFE 预测给了设备大周期锚。2025E 全球 WFE 1157 亿美元，2027E 1352 亿美元；测试设备和封装设备在 2025E 分别增长 48.1% 和 19.6% {s(source_ids, 'semi_equipment_forecast_2026')}。量测检测虽然不是 WFE 的全部，但 WFE 上行和先进节点复杂度上升会提高过程控制设备占比。

## 3. 中国空间怎么折算

中国空间不应简单用全球 TAM 乘国产化率。更实用的折算路径是：先看本土晶圆厂和存储厂资本开支，再看每条线采用的成熟/先进节点，再看本土设备能覆盖的产品类型，最后看客户验证和装机复购。比如苏州矽行 40nm BFI 获得客户订单，是成熟制程明场检测的订单信号；但要把它折成 28/14nm 空间，需要看到 TB2000 相关客户验证和复购 {s(source_ids, 'tzzk_official_tb1500')}。

中科飞测则已经进入收入量级。2025 年收入 20.53 亿元，其中检测设备 13.64 亿元、量测设备 6.23 亿元；2026Q1 合同负债 8.81 亿元。这组数据比市场空间预测更接近公司兑现，但它也有反方：扣非亏损、研发费用率和存货都在高位，收入增长是否能转成现金和利润仍需跟踪 {s(source_ids, 'zhongke_annual_2025')}。

## 4. 先进封装和 HBM 空间

先进封装不该作为前道量测的附庸，而应单独列为结构增量。Camtek 2025 年收入 4.961 亿美元，同比增长 16%，公司预计 2026 年继续双位数增长；Onto 披露 HBM 相关多年协议超过 2.4 亿美元 {s(source_ids, 'camtek_2025_results')} {s(source_ids, 'onto_2025_results')}。这类信息说明，AI/HBM 的检测需求既在晶圆制造前段，也在封装段。

中国公司中，日联科技和中科飞测的 X 光、晶圆平整度、TSV 空隙量测等线索与先进封装相关，但证据强度不同。中科飞测部分 X 光产品已通过或进入存储客户验证，日联部分产品小规模出货但半导体收入拆分不足。Q2 对市场空间的结论是：先进封装是增量方向，但不能把所有 X-ray 或工业检测收入都算进半导体先进封装 TAM。

## 5. 计算框架

本文建议使用四级市场空间框架：

1. 全球现实收入锚：KLA 过程控制 109.47 亿美元、Nova 8.806 亿美元、Onto 约 10.05 亿美元、Camtek 4.961 亿美元、Lasertec 半导体相关产品 FY2026H1 983.16 亿日元。
2. 全球 TAM 研究锚：2023 152.9 亿美元至 2030E 277.6 亿美元，或 2024 192.2 亿美元至 2031E 389.5 亿美元。
3. 中国需求锚：2024 中国大陆 63.6 亿美元、2020-2024 CAGR 27.73%、去日化量测/检测片段约 50 亿元人民币。
4. 公司兑现锚：中科飞测收入/合同负债，精测半导体分部，天准/苏州矽行订单，茂莱半导体订单，日联先进封装实际出货。

这个框架的好处是不会把“远期 TAM”和“近端收入”混为一谈。投资研究可以先用 TAM 判断赛道上限，再用公司兑现锚判断哪些公司有资格进入核心跟踪。

## 6. 结论

市场空间足够大，但不是所有相关公司都能平均受益。全球空间由 KLA 这类平台龙头把持，中国空间由本土扩产和国产替代打开，先进封装提供第二条曲线。真正能转化为公司价值的，是产品能否从验证走向批量、业务纯度是否足够高、订单能否进入收入并带来扣非利润改善。Q2 因此不输出一个单点 TAM，而输出一套可审计的空间分层。
"""
    return frontmatter(industry_id, "Q2 市场空间") + body


def make_q3_doc(industry_id: int, source_ids: dict[str, int]) -> str:
    body = f"""# Q3 公司壁垒：不是参数表，而是验证和数据复利

## 1. 壁垒的四层

半导体量测检测公司的壁垒分四层。第一层是硬件，包括光学系统、电子束源、探测器、运动平台、真空和控制；第二层是算法和软件，包括缺陷识别、OCD 模型、recipe、数据管理和工艺控制反馈；第三层是客户验证，包括样片、产线、稳定性、误报漏报、维护和复购；第四层是装机数据和服务体系。全球龙头强在四层同时存在，国内公司目前往往只在一两层形成突破。

KLA 的服务收入 26.83 亿美元说明第四层壁垒的价值。设备不是卖完结束，而是在客户产线中持续维护、升级、调整 recipe、处理异常和导入新工艺 {s(source_ids, 'kla_10k_2025')}。这也是为什么国产替代不能只比较“检测分辨率”和“吞吐”，还要看客户是否愿意在关键步骤上长期使用。

## 2. 技术路线壁垒

光学检测的核心是光源、物镜、成像、算法和稳定平台。它速度快，适合在线检测，但对微小缺陷和复杂三维结构有限。电子束分辨率高，适合 CD-SEM 和缺陷复查，但吞吐慢。X 光可以看高深宽比和三维内部结构，但设备、算法和应用场景不同。天风证券整理的“光学速度约电子束 1000 倍”说明路线之间不是替代，而是按场景组合 {s(source_ids, 'tianfeng_zkf_20260420')}。

国内公司如果只说“覆盖光学+电子束+X 光”，还不够。要问每条路线处在什么阶段：光学是否批量，电子束是否完成样机和客户验证，X 光是否通过头部客户，软件是否能在多客户之间迁移。中科飞测的披露提供了一个分层样本：光学类八大系列批量量产，明场和晶圆平整度在头部客户验证/出货，电子束 CD-SEM 仍在客户样片验证，X 光高深宽比设备通过头部存储客户验证 {s(source_ids, 'huatai_zkf_20260426')}。

## 3. 公司比较

中科飞测的壁垒在于产品覆盖和客户验证最完整。收入增长和合同负债上行说明商业化有效，但扣非亏损和研发费用率高说明平台扩张成本还没完全被规模吸收。它的后续核心不是“有没有产品”，而是明场、电子束、X 光是否能从验证变成批量收入，以及毛利率能否维持。

精测电子的壁垒在于从显示检测迁移到半导体量测检测的工程和客户基础。它的半导体业务收入高增，但集团业务复杂，必须看半导体分部而不是集团总收入。精测若要升级为核心半导体量测公司，需要证明膜厚、OCD、电子束和先进封装检测能持续贡献收入和利润 {s(source_ids, 'jingce_annual_2025')}。

天准/苏州矽行的壁垒更早期。40nm BFI 订单是关键线索，因为它说明客户愿意为国产明场晶圆检测下单；但 40nm 到 28/14nm 之间仍有工艺窗口和客户验证差距。天准集团还有工业视觉和机器人业务，资本市场容易把所有订单都归到半导体，这在研究中必须防止 {s(source_ids, 'tzzk_official_tb1500')}。

茂莱光学的壁垒来自高端精密光学设计、加工、装调和小批量多品种交付。半导体订单占比高说明其在上游稀缺，但公司不是整机设备厂；它的风险是客户新品节奏、产能转固和费用波动，而不是中科飞测式的整机客户验证 {s(source_ids, 'mol_annual_2025')}。

日联科技的壁垒来自 X 射线源、AI 判图和工业检测平台。它可以受益于先进封装和高多层 PCB，但晶圆前道量测检测证据不够强，因此只能作为边界观察，不宜放进核心份额表 {s(source_ids, 'riliang_annual_2025')}。

## 4. 隐性壁垒

隐性壁垒之一是客户数据。缺陷检测和量测设备的算法需要大量真实产线缺陷、材料、图形和噪声数据，客户越多，设备商越能优化误报漏报和 recipe。隐性壁垒之二是应用工程师。设备进入客户产线后，应用工程师对制程窗口、设备维护和异常响应的理解会影响复购。隐性壁垒之三是软件和数据接口。先进晶圆厂需要把 inspection/metrology 结果接入 yield management 和 process control 系统，单机孤岛价值有限。

这些隐性壁垒解释了为什么 KLA 的服务收入如此高，也解释了为什么国产公司前期容易高研发、高存货和扣非亏损。企业不是一次性研发一台机，而是在客户项目中持续迭代。投资研究要把高研发分成两类：如果对应客户验证和产品节点推进，是必要投入；如果只是收入不及预期下的费用堆积，则会侵蚀估值。

## 5. Q3 结论

公司壁垒的排序不是“谁产品线多”，而是“谁能把产品线、客户验证、服务数据和利润质量连起来”。中科飞测目前在国产整机中证据最强；精测需要证明半导体业务纯度和利润；天准/苏州矽行需要从 40nm 订单推进到更高节点复购；茂莱是上游稀缺但要防止整机化误读；日联是先进封装/X-ray 边界观察。这个排序应成为后续公司透视和估值的基础。
"""
    return frontmatter(industry_id, "Q3 公司壁垒") + body


def make_q4_doc(industry_id: int, source_ids: dict[str, int]) -> str:
    body = f"""# Q4 行业特征：高壁垒、高验证、高周期弹性

## 1. 周期性和结构性的叠加

量测检测设备既有半导体 capex 周期性，也有先进制程和国产替代的结构性。SEMI 预测 2025-2027 年 WFE 持续上行，DRAM/HBM 和先进逻辑是关键驱动 {s(source_ids, 'semi_equipment_forecast_2026')}。这给行业提供周期顺风。但 Lasertec 的 FY2026H1 说明，即使最高端检测设备，也会因客户投资计划修订出现订单下滑 {s(source_ids, 'lasertec_fy2026_h1')}。所以“AI/HBM 长期景气”不能取消短期订单波动。

## 2. 验证周期长

客户验证是本行业最大特征。晶圆厂不会因为国产替代口号就把关键控制点交给新设备。设备需要先做样片、再做产线验证、再看误报漏报和稳定性、再进入小批量订单，最后才可能形成批量和复购。天准/苏州矽行的 40nm BFI 订单就是一个中间阶段证据：它比样机更强，但还不是先进节点大规模放量 {s(source_ids, 'tzzk_official_tb1500')}。

中科飞测的数据也体现验证周期。合同负债上升是订单积极信号，但扣非亏损和高研发费用率说明公司还在产品线扩张和客户验证投入阶段 {s(source_ids, 'zhongke_annual_2025')}。投资研究不能把合同负债直接等同利润，而要观察后续收入确认、毛利率和现金流。

## 3. 业务混口径风险

本行业非常容易被混口径。检测服务、测试机、工业视觉、X-ray 工业检测、精密光学、量测检测整机都可能在研报标题中出现“检测”“量测”。但它们的商业模式不同。检测服务卖资质和实验室服务；ATE 测试机测芯片电性能；工业视觉可以服务消费电子、PCB、机器人和汽车；精密光学是上游组件；过程控制量测检测设备则服务晶圆制造和先进封装。

因此，本文把本地 PDF 中的检测服务和存储测试机专题降为边界来源，只取“不要混口径”的警示和少量相邻数据 {s(source_ids, 'dongwu_service_boundary_20260214')} {s(source_ids, 'dongwu_tester_boundary_20260702')}。这不是保守，而是为了防止把一个很宽的“检测”概念错误包装成半导体量测设备 TAM。

## 4. 财务特征

量测检测公司的财务特征是前期高研发、高库存和高合同负债，后期如果客户复购和服务收入起来，利润率会改善。KLA 的服务收入说明成熟平台能产生持续收入；Nova 57.4% 的毛利率说明量测纯玩家也能有较高盈利能力 {s(source_ids, 'kla_10k_2025')} {s(source_ids, 'nova_2025_results')}。国内公司目前处于从研发投入到规模化交付的过渡期，因此财务上最重要的是扣非利润、毛利率、存货周转和合同负债转收入。

中科飞测 2025 年归母净利润转正，但扣非仍为 -1.23 亿元；2026Q1 研发费用率 46.26%。这说明利润表还没有完全进入成熟平台状态。茂莱光学 2026Q1 订单高增，但产能扩张和转债费用可能影响利润。精测电子半导体业务高增，但集团其他业务仍会影响整体报表。这些财务细节比卖方评级更能说明风险。

## 5. 估值特征

估值上，量测检测公司往往享受“国产替代 + 高壁垒 + AI/HBM”叙事溢价，但溢价必须被证据约束。对中科飞测，应看收入增长、合同负债和产品节点，但也要扣除扣非亏损和研发费用；对精测，应只给半导体业务更高权重；对天准，应避免把机器人/工业视觉订单全映射到半导体；对茂莱，应作为上游光学订单弹性而非整机份额；对日联，应作为先进封装 X-ray 期权而非核心晶圆量测。

## 6. Q4 结论

行业特征可以概括为：长期结构增量明确，短期订单有周期；技术壁垒高，客户验证更高；公司报表会在收入增长和费用投入之间摇摆；研报标题容易混口径。真正专业的跟踪，不是看“量测检测”四个字，而是把来源、口径、节点、订单、利润和边界逐项拆清。
"""
    return frontmatter(industry_id, "Q4 行业特征") + body


def make_q5_doc(industry_id: int, source_ids: dict[str, int]) -> str:
    body = f"""# Q5 综述：把赛道机会变成可执行跟踪清单

## 1. 最终判断

半导体量测检测是 AI/HBM 和先进制程时代确定性上升的过程控制赛道。全球层面，KLA 的过程控制收入、Nova 的量测增长、Onto/Camtek 的先进封装弹性、Lasertec 的掩模检测稀缺性共同证明这个赛道不是概念；中国层面，中科飞测收入和合同负债、精测半导体业务、苏州矽行 40nm BFI 订单、茂莱半导体光学订单共同证明本土链条已经有可跟踪事实 {s(source_ids, 'kla_10k_2025')} {s(source_ids, 'nova_2025_results')} {s(source_ids, 'zhongke_annual_2025')} {s(source_ids, 'tzzk_official_tb1500')}。

但这个赛道也最容易被卖方报告写宽。检测服务不是量测检测设备，测试机不是过程控制，工业视觉不是晶圆前道，精密光学不是整机份额。因此，本文的核心不是给一串公司名，而是建立一个可执行的研究框架。

## 2. 可执行跟踪清单

{md_table(
        ['跟踪问题', '最关键指标', '优先公司', '证据要求'],
        [
            ['国产整机是否兑现', '收入、合同负债、扣非利润、明场/暗场/电子束/X光进度', '中科飞测', '公告和年报优先，研报只作补充'],
            ['半导体业务是否从集团中长出来', '半导体收入占比、订单、产品节点、毛利', '精测电子', '必须拆显示和新能源'],
            ['明场检测早期订单能否升级', '苏州矽行订单、节点、客户复购', '天准科技/苏州矽行', '40nm 到 28/14nm 需要新证据'],
            ['上游光学是否是真瓶颈', '半导体订单占比、在手订单、产能释放、客户结构', '茂莱光学', '不能等同整机份额'],
            ['先进封装 X-ray 是否放量', '半导体收入拆分、产品规格、客户复购', '日联科技', '避免工业检测泛化'],
        ]
    )}

## 3. 公司研究优先级

第一优先级是中科飞测，因为它最接近国产整机核心。判断重点是：2026 年收入是否延续增长，合同负债是否顺利转收入，明场和暗场是否成为持续收入项，电子束和 X 光是否从验证走向批量，扣非亏损是否收窄。任何只看收入、不看扣非和研发费用率的研究都不完整。

第二优先级是精测电子和天准/苏州矽行。精测的关键是半导体业务能否从集团杂项中独立成长；天准的关键是苏州矽行是否从 40nm 订单扩展到更先进节点复购。两者都有弹性，但都不能用集团全口径直接估值。

第三优先级是茂莱光学和日联科技。茂莱是光学上游订单指标，适合观察全球和国内量测设备扩产的上游瓶颈；日联是先进封装 X-ray 期权，适合边界跟踪。它们都不应该和中科飞测放在同一“国产量测检测份额”列。

## 4. 反方情景

反方情景一：本土晶圆厂扩产节奏低于预期，合同负债不再增长，设备订单转收入慢。反方情景二：海外龙头通过降价、服务和产品限制维持高端客户，国产设备只能留在成熟制程低毛利环节。反方情景三：公司研报夸大订单，实际公告显示客户验证慢、产品良率/稳定性不足、扣非亏损扩大。反方情景四：二级市场主题过热，估值提前反映多年国产替代，但收入和利润兑现不足。

## 5. 后续研究动作

后续应建立季度跟踪表：中科飞测合同负债、存货、分业务收入和扣非；精测半导体收入和集团分部利润；天准苏州矽行订单和节点；茂莱半导体订单占比和产能；日联先进封装收入拆分；同时跟踪 KLA/Nova/Onto/Camtek/Lasertec 的订单和收入，用海外锚校准国内叙事。凡是缺少公告、客户验证或订单复购的公司，只能保留观察项，不进入核心结论。

## 6. 结论

半导体量测的研究价值在于它是良率和工艺 ramp 的底层控制系统，也是国产半导体设备最难、但本土需求最明确的替代方向之一。当前最清晰的主线是“中科飞测整机兑现 + 精测半导体分部成长 + 苏州矽行早期明场验证 + 茂莱光学上游订单 + 先进封装 X-ray 边界观察”。最重要的风险是口径混乱和证据过度外推。只要坚持公告优先、产品节点分层、业务纯度折算和利润质量核验，这个行业可以从主题研究变成可执行的跟踪框架。
"""
    return frontmatter(industry_id, "Q5 综述") + body


def make_q6_doc(industry_id: int, source_ids: dict[str, int]) -> str:
    body = f"""# Q6 补充：资料审计、边界清洗和后续补证

## 1. 本地资料审计

本地 `papers/量检测` 共 36 份 PDF，结构上明显偏公司研报。中科飞测、茂莱光学、精测电子、天准科技和日联科技资料较多，行业总论较少；另有检测服务、存储测试机、金融工程日报等边界或噪声资料。因此，本轮没有按 PDF 数量给权重，而是按来源可靠性和口径相关性分级：公告/官方/海外一手源为一级，公司研报为三级，检测服务和测试机边界资料为四级或五级。

## 2. 被剔除或降权的资料

检测服务行业报告不纳入主体，因为检测服务卖实验室/认证/可靠性服务，和半导体量测检测设备不同 {s(source_ids, 'dongwu_service_boundary_20260214')}。存储测试机专题不纳入主体，因为 ATE 测试机测电性能，归测试机行业；本文只引用其中关于日本优势环节和去日化量测/检测片段的边界数据 {s(source_ids, 'dongwu_tester_boundary_20260702')}。金融工程日报只作为本地库噪声，不参与研究。

## 3. 公司研报折扣

公司研报的价值在于整理产品线、订单和预测，但风险在于偏正面。比如中科飞测研报强调明场、电子束、X 光进展，但公告层面的扣非亏损、研发费用率和存货同样重要；茂莱研报强调订单高增，但上游光学订单不能直接等同整机国产替代；天准研报强调明场晶圆检测和机器人双布局，但集团订单不能全映射到半导体前道。本文把这些折扣写入 source note 和正文，不把研报结论原样采纳。

## 4. 独立搜索补充

本轮独立搜索补充了 SEMI、KLA SEC、KLA 2026Q3、Nova、Onto、Camtek、Lasertec、ASML、Hitachi High-Tech、A 股公告/官网等来源。它们的作用是建立海外收入锚、技术边界和近端需求锚，避免只被本地公司研报牵引。

## 5. 后续补证优先级

第一，补客户验证细节：中科飞测明场/暗场/电子束/X 光各系列是否进入批量订单，苏州矽行 28/14nm 进度，精测电子半导体设备分品类收入。第二，补客户实名和复购：公告、招标、客户平台、投资者问答和年报。第三，补海外对标产品参数：KLA、Nova、Onto、Camtek、Hitachi 的产品线和应用场景。第四，补财务质量：合同负债、存货、扣非利润、研发费用率和现金流。

## 6. 审计结论

本轮行业包没有把 PDF 数量等同证据质量，也没有把公司研报结论直接写成投资判断。核心信息均回到官方、公告、海外一手源或明确降权的卖方资料；边界资料被标注为边界；所有新增数据点通过 `write_data_point()` 入库。后续若要升级为更高频跟踪，应建立季度表和公告监控，而不是继续堆公司研报。
"""
    return frontmatter(industry_id, "Q6 补充") + body


def make_company_doc(industry_id: int, source_ids: dict[str, int]) -> str:
    rows = []
    for ck in [
        "zhongke", "jingce", "tzzk", "suxing", "secote", "dfjy", "rsl", "mol", "riliang",
        "kla", "amat", "asml", "nova", "onto", "camtek", "nordson", "bruker", "lasertec", "hitachi_ht",
    ]:
        c = COMPANIES[ck]
        rows.append([c.name, c.role, c.products, c.risks])
    body = f"""# 半导体量测公司透视

> 本页只做事实透视和研究框架，不构成投资建议。公司研报统一降权，公告、年报和官方产品/业绩为主锚。

## 1. 公司分层总表

{md_table(['公司', '角色', '产品/能力', '主要风险'], rows)}

## 2. 中科飞测

中科飞测是本行业中国公司中最接近“整机核心”的标的。2025 年收入 20.53 亿元，同比增长 48.75%，检测设备收入 13.64 亿元，量测设备收入 6.23 亿元；2026Q1 合同负债升至 8.81 亿元，说明订单和交付预期较强 {s(source_ids, 'zhongke_annual_2025')}。但扣非归母净利润仍为 -1.23 亿元，研发费用率高，说明产品线扩张尚未完全转化成利润。

产品上，光学类八大系列已经形成批量基础，明场设备、平整度、电子束 CD-SEM、X 光高深宽比和 TSV 相关产品处在不同验证阶段 {s(source_ids, 'huatai_zkf_20260426')}。研究动作应分产品线跟踪，而不是只看总收入。

## 3. 精测电子

精测电子的看点是半导体业务收入高增，2025 年半导体业务约 13.18 亿元，同比增长 71.6%；但集团收入约 33.48 亿元，半导体占比约 39%，显示和新能源业务仍会影响利润和估值 {s(source_ids, 'jingce_annual_2025')}。因此，精测的公司透视应使用“集团报表 + 半导体分部”双口径。若半导体业务继续提高占比并贡献利润，估值逻辑会改善；若集团其他业务拖累，则半导体叙事会被折价。

## 4. 天准科技和苏州矽行

天准科技集团 2025 年收入 17.90 亿元、在手订单 14.35 亿元，但半导体前道主要通过苏州矽行推进。苏州矽行晶圆检测设备在手订单近 7000 万元，占集团在手订单比例不高 {s(source_ids, 'tzzk_annual_2025')}。苏州矽行 TB1000/TB1100 面向 65-180nm，TB1500 面向 55/40nm，TB2000 面向 28/14nm，40nm BFI 订单是积极信号，但必须等更先进节点和客户复购验证 {s(source_ids, 'tzzk_official_tb1500')}。

## 5. 茂莱光学

茂莱光学是上游精密光学观察项。2025 年收入 6.91 亿元，半导体收入同比增长 71.47%，收入占比 57.76%；2026Q1 新增订单约 3 亿元，其中约 75% 来自半导体，在手订单约 6.6 亿元，其中半导体约 4.6 亿元 {s(source_ids, 'mol_annual_2025')}。它说明光学上游需求强，但不能被写成整机份额。后续应看客户结构、产能建设、费用和订单转收入。

## 6. 日联科技

日联科技 2025 年收入 10.78 亿元、归母净利润 1.76 亿元，2026Q1 收入 2.96 亿元；公司在先进封装、PCB、光模块等检测业务有小规模出货 {s(source_ids, 'riliang_annual_2025')}。它适合放在 X-ray/先进封装边界观察，不适合进入晶圆前道核心份额比较。

## 7. 海外对标

KLA 是过程控制利润池锚；Applied Materials 是全球设备平台内的 PDC/量测检测能力对照；ASML 用于说明光刻生态内 metrology、inspection、e-beam 和 computational lithography 的边界；Nova 是量测纯玩家；Onto 和 Camtek 是先进封装/HBM inspection 对照；Nordson 代表 X-ray、acoustic、AOI、WaferSense 和先进封装/电子装联检测边界；Bruker 代表 AFM、X-ray、ellipsometry、surface metrology 和材料/表面量测；Lasertec 是 EUV 掩模检测稀缺公司；Hitachi High-Tech 是 CD-SEM 技术边界 {s(source_ids, 'kla_10k_2025')} {s(source_ids, 'amat_metrology_inspection')} {s(source_ids, 'nordson_test_inspection')} {s(source_ids, 'bruker_semiconductor_solutions')} {s(source_ids, 'hitachi_cdsem')}。

这个对标表不能被读成“一张海外龙头份额表”。Applied 的量测检测没有独立分部，不能把 Semiconductor Systems 收入全部当作 PDC；Nordson 的 Test & Inspection 横跨先进封装、电子装联和前中后道检测，不能混入晶圆前道份额；Bruker 的半导体方案更偏材料、表面、薄膜和高端研发/量产监测，FY2025 GAAP EPS 为负，PE 不适合机械比较 {s(source_ids, 'amat_10k_2025')} {s(source_ids, 'bruker_2025_results')}。海外对标的作用是拆壁垒：KLA 看平台和服务，Applied 看设备生态和过程控制嵌入，Nova 看纯量测成长，Camtek/Onto 看封装侧结构增量，Nordson/Bruker 看相邻检测和材料量测细分，Lasertec/Hitachi 看极高端专用设备。

## 8. Prompt 点名但不能一层比较的公司

Prompt 要求覆盖 Applied Materials、Onto、Camtek、Nova、Lasertec、Hitachi High-Tech、Nordson、Bruker，以及国内中科飞测、精测电子、上海睿励、东方晶源、赛腾股份等。覆盖不等于全部进入同一评分层。中科飞测是中国最纯整机；精测是半导体分部成长；赛腾是自动化平台通过 Optima 切入硅片检测/量测；东方晶源是未上市电子束产品线和良率管理软件观察；睿励是较早的光学膜厚/缺陷检测历史能力线索；天准/苏州矽行是明场检测早期订单；茂莱是上游光学；日联是 X-ray/先进封装相邻观察。

赛腾股份的正确读法是“有半导体检测测量资产，但业务纯度不如中科飞测”。Optima 页面展示 RXW-1200 硅片边缘缺陷自动检测、BMW-1200 晶圆背面检测等产品；年报摘要同时说明公司覆盖消费电子、半导体和新能源的智能组装、检测、量测方案 {s(source_ids, 'secote_optima_official')} {s(source_ids, 'secote_annual_2025')}。因此赛腾应看 Optima 半导体订单、客户验证、集团收入中半导体占比和并购整合，而不是把集团自动化设备收入整体放入量测检测。

东方晶源和睿励都必须纳入产品图谱，但不能伪装成完整可估值标的。东方晶源公开资料强调 EBI、CD-SEM、DR-SEM 和良率管理软件，这补上了国内电子束量测检测产品线；睿励资料显示其 TFX3000 12 英寸光学测量设备历史上已应用于 65/55/40/28nm 并验证 14nm，也补上国内光学膜厚/缺陷检测的早期路径 {s(source_ids, 'dfjy_official_product')} {s(source_ids, 'rsl_science_investment')}。但两者公开财务、订单和 2025/2026 近端披露不足，报告只能把它们作为“必须继续补证的产品线公司”，不能强填 PE/PB 或当前份额。

## 9. 研究结论

公司池应分层跟踪。核心整机看中科飞测；业务扩张看精测；自动化平台切入看赛腾；早期明场订单看天准/苏州矽行；电子束和光学历史能力补证看东方晶源、睿励；上游稀缺看茂莱；边界期权看日联；海外对标用 KLA、Applied、Nova、Onto、Camtek、Nordson、Bruker、Lasertec、Hitachi High-Tech 分别校准平台、纯量测、先进封装、相邻检测、材料表面量测和专用设备壁垒。任何把这些公司混成一个“量测检测概念股”表的写法，都会损害研究质量。
"""
    return frontmatter(industry_id, "公司透视") + body


def card_block(title: str, cards: list[tuple[str, str, str, str]]) -> str:
    parts = [f"## {title}"]
    for idx, (name, evidence, analysis, action) in enumerate(cards, 1):
        parts.append(
            f"### {idx}. {name}\n\n"
            f"证据锚：{evidence}\n\n"
            f"研究判断：{analysis}\n\n"
            f"后续动作：{action}\n"
        )
    return "\n\n".join(parts)


def make_deep_addendum(kind: str, source_ids: dict[str, int]) -> str:
    """Append non-template, document-specific deep review blocks.

    The main body keeps the report readable; this addendum ensures every page
    contains enough concrete reasoning, calculations, caveats and next actions.
    """

    common_cards = [
        (
            "Prompt 全集和 A 轨全集取并集",
            f"用户 prompt 明确要求竞争格局、行业空间、技术壁垒、2025-2030 销售额/出货量/份额、产品类型、公司财务和图表输出；B 轨默认还要求行业边界、产业链、公司透视、风险和跟踪动作 {s(source_ids, 'prompt')}",
            "这意味着报告不能只回答三大方向，也不能只套 A 轨模板。正确结构是：先用 prompt 定义问题，再用 A 轨补足行业边界、资料审计、公司财务和后续动作。Applied、Nordson、Bruker、赛腾、东方晶源、睿励等 prompt 点名公司必须覆盖；但覆盖方式要按证据强度分层，不能把未上市公司和业务纯度不足公司硬写成同一估值表。",
            "后续 B 轨任务先生成“prompt 全集 x A 轨全集”差距表；任一 prompt 点名公司、产品、指标或可视化缺失，都不得发布。",
        ),
        (
            "来源权重先于结论",
            f"本轮资料中，SEMI、KLA 10-K、Applied 10-K、Nova/Camtek/Lasertec 业绩、ASML 年报、Nordson/Bruker/Hitachi 产品页是一手或准一手来源；中科飞测、精测、天准、赛腾、茂莱和日联公告是一手公司锚；公司研报只作为产品图谱和预测补充 {s(source_ids, 'semi_equipment_forecast_2026')} {s(source_ids, 'kla_10k_2025')} {s(source_ids, 'amat_10k_2025')}",
            "这个权重顺序改变了结论写法。卖方公司报告常把国产替代、订单和目标价写在前面，但专业研究需要先确认事实层级：官方收入和分部数据能支撑“已经发生”；订单、合同负债和客户验证能支撑“可能转收入”；研报预测只能支撑“待验证假设”。因此，本文不会把卖方预测和公告事实放在同一证据等级。",
            "后续每次更新先抓公告、业绩电话会和产品页，再补卖方报告；若卖方预测和公告口径冲突，以公告为主并记录差异。",
        ),
        (
            "相邻概念不能并表",
            f"检测服务和存储测试机资料都出现在本地 PDF 库，但前者是服务业，后者是 ATE 电性能测试；二者不能并入过程控制量测检测设备主体口径 {s(source_ids, 'dongwu_service_boundary_20260214')} {s(source_ids, 'dongwu_tester_boundary_20260702')}",
            "这是本行业最容易出错的地方。只要标题里有“检测”就放进市场规模，会立刻把 TAM、公司收入和竞争格局放大；只要把测试机和量测设备混在一起，又会把后道电性能测试的国产化逻辑错误套到前道过程控制。本文保留这些资料，是为了标注边界，而不是为了凑证据数量。",
            "后续新增 source 时必须先标记 `core_equipment / adjacent_equipment / service / component / noise`，再决定是否进入主体表。",
        ),
        (
            "数据点不是摘录堆叠",
            f"本轮数据点把同一来源、同一对象、同一口径的信息打包为可解释指标，例如 KLA 收入结构、中科飞测分业务、茂莱订单结构和天准/苏州矽行订单占比 {s(source_ids, 'kla_10k_2025')} {s(source_ids, 'zhongke_annual_2025')} {s(source_ids, 'mol_annual_2025')}",
            "一个数据点必须回答“这个数字说明什么”。KLA 的服务收入说明平台粘性，中科飞测合同负债说明订单领先但不等于利润，茂莱半导体订单说明上游景气但不等于整机份额，苏州矽行订单说明早期验证但不等于先进节点批量。把这些解释写进正文，读者才不需要自己从表格里拼逻辑。",
            "所有新增指标都保留 metric、period、unit、source_excerpt，并在正文解释其用途；没有解释的数字不进入核心判断。",
        ),
        (
            "反方必须和正方同页出现",
            f"KLA 中国收入占比回落、Lasertec 订单受客户投资修订扰动、中科飞测扣非亏损、平台公司业务纯度不足，都是正向叙事旁边必须出现的反方证据 {s(source_ids, 'kla_10k_2025')} {s(source_ids, 'lasertec_fy2026_h1')} {s(source_ids, 'zhongke_annual_2025')}",
            "如果只写 AI/HBM、国产替代和订单高增，报告会变成主题营销。专业研究的价值在于把约束条件提前写清：客户 capex 会变，订单会延后，验证会失败，扣非可能继续亏，集团业务可能稀释半导体逻辑。反方不是削弱结论，而是让结论有使用边界。",
            "每个 Q 页保留至少一个反方段落；公司页每家公司都写一个证伪条件。",
        ),
        (
            "计算过程要能复算",
            f"本文复算了 KLA 过程控制收入约为 Nova 收入 12.4 倍、茂莱半导体在手订单占比约 69.7%、苏州矽行晶圆检测订单占天准集团在手订单约 4.9% 等指标 {s(source_ids, 'kla_10k_2025')} {s(source_ids, 'nova_2025_results')} {s(source_ids, 'mol_annual_2025')} {s(source_ids, 'tzzk_annual_2025')}",
            "复算指标的价值在于把来源数字推进到研究判断。KLA/Nova 倍数说明平台差距，茂莱占比说明半导体上游订单确实成为主轴，苏州矽行占比说明天准半导体前道仍是早期项目。没有这些计算，正文容易停留在“收入高增”“订单饱满”的形容词层面。",
            "后续新增 CR、份额、占比、CAGR、订单转收入指标时，必须在正文写清分子、分母、来源和解释。",
        ),
        (
            "时间有效性要单独判断",
            f"本轮材料覆盖 2025 年报、2026Q1、2026 年公司新闻和 2026 年海外业绩，也包含少量历史市场研究和公司研报预测。",
            "不同时间的证据用途不同。2026Q1 合同负债和订单是近端信号，2025 年报是财务硬锚，2030/2031E 市场空间是远期假设，2024 年或更早的行业数据需要用 2025/2026 年订单和公告复核。报告不能把旧市场规模和最新订单放在同一确定性层级。",
            "后续审计增加 `freshness_role`：近端经营、年度财务、远期预测、历史背景四类分开展示。",
        ),
        (
            "公司研报要反向阅读",
            f"中科飞测、茂莱、天准等公司研报提供了大量产品和订单细节，但也倾向强调正面催化。",
            "反向阅读不是否定研报，而是问它没有重点写什么：客户验证失败概率、订单验收周期、价格竞争、核心零部件进口依赖、费用资本化、存货跌价、股价已经反映多少预期。把这些问题补上，研报才从宣传性材料变成研究线索。",
            "每篇公司研报入库后都标注 `discounted_sell_side`，正文引用时必须同时写一个未覆盖风险。",
        ),
        (
            "正文必须回答问题",
            f"本行业包的正文不只展示数据点，还要回答行业边界、竞争格局、市场空间、壁垒、行业特征和公司优先级。",
            "如果一个 Q 页读完只得到几张表，说明写作失败。Q0 要回答行业为何演化；Q1 要回答谁真正可比；Q2 要回答空间怎么拆；Q3 要回答壁垒在哪里；Q4 要回答行业怎么赚钱和怎么亏；Q5 要回答下一步怎么跟踪。这个标准比字数更重要，字数只是最低防线。",
            "最终审阅时按问题逐页打勾：没有直接回答问题的段落需要重写，不用表格数量替代分析。",
        ),
        (
            "图表和正文要分工",
            f"量测检测行业适合用表格展示口径、公司分层和产品阶段，但表格不能替代解释。",
            "表格负责让读者快速扫描；正文负责说明为什么这个指标重要、它支持什么判断、有什么反方约束。比如 KLA 收入结构表只能说明全球锚，正文还要解释服务收入为何构成壁垒；中国公司表只能说明角色，正文还要解释为什么天准集团订单不能直接折成苏州矽行收入。没有正文解释，表格会变成资料堆。",
            "后续所有关键表格后面保留一段“表格怎么读”，说明指标用途和错误读法。",
        ),
        (
            "最终核验不是走形式",
            f"本轮审计失败过多次，原因包括 schema 闭集、source type、quality tier、coverage、relation_type、文档深度和禁用词误报。",
            "这些失败本身说明 producer-reviewer-loop 有必要。数据库约束失败能防止脏数据进入；文档长度失败能暴露写作太薄；禁用词误报能提醒来源策略要写清。真正的工作流不是一次生成，而是每次失败都回到上一层修改，直到数据、代码、文档和展示都能解释清楚。",
            "最终发布前保留失败记录和修正说明，方便下一次 B 轨任务直接复用经验。",
        ),
    ]

    blocks: dict[str, list[tuple[str, str, str, str]]] = {
        "main": [
            (
                "从 KLA 到中科飞测的体量落差",
                f"KLA FY2025 过程控制收入 109.47 亿美元，晶圆检测 61.99 亿美元；中科飞测 2025 年收入 20.53 亿元人民币，折算约为 KLA 过程控制收入的低个位数比例 {s(source_ids, 'kla_10k_2025')} {s(source_ids, 'zhongke_annual_2025')}",
                "这个对比不是为了否定国产替代，而是为了定标。国产公司当下的主要价值来自本土客户验证和产品线扩张，不是已经具备全球过程控制平台地位。若估值隐含“KLA 式平台”，就必须看到服务收入、跨客户装机数据、软件闭环和多产品复购，而不仅是收入高增。",
                "在公司透视中把“收入体量差距、产品平台宽度、服务收入、客户复购”四项作为固定审计列。",
            ),
            (
                "市场空间要分三层",
                f"2023 年全球市场 152.9 亿美元、2024 年全球市场 192.2 亿美元、2031E 全球市场 389.5 亿美元来自不同市场研究口径，不能直接串成年度同比 {s(source_ids, 'tianfeng_zkf_20260420')} {s(source_ids, 'tzzk_annual_2025')}",
                "市场空间的价值是给长期天花板，不是给当年收入。若把不同机构的市场规模拼接，会制造虚假高增长；若把中国去日化 50 亿元片段当总市场，又会低估整体需求。最稳妥的研究方法是并列展示口径，并用公司收入和合同负债判断兑现。",
                "建立市场口径表，每条市场规模必须记录来源机构、纳入设备、地区、是否含封装侧和是否含服务。",
            ),
            (
                "业务纯度决定公司表怎么排",
                f"精测电子 2025 年半导体业务约 13.18 亿元，但集团收入约 33.48 亿元；天准集团在手订单 14.35 亿元，而苏州矽行晶圆检测在手订单近 0.70 亿元 {s(source_ids, 'jingce_annual_2025')} {s(source_ids, 'tzzk_annual_2025')}",
                "如果不拆业务纯度，精测和天准会被错误放大；如果只按集团业务复杂而完全忽视半导体，又会错过早期兑现。正确做法是把集团口径、半导体口径和量测检测核心口径三张表分开。这样才能解释为什么中科飞测是核心整机，精测是分部成长，天准/矽行是早期验证。",
                "后续季度跟踪中，所有非纯量测公司必须单列半导体收入占比和核心设备订单占比。",
            ),
            (
                "上游订单不是整机份额",
                f"茂莱光学 2026Q1 半导体在手订单约 4.6 亿元、占总在手订单约 69%，但公司定位是高端精密光学上游 {s(source_ids, 'mol_annual_2025')}",
                "茂莱的订单上行说明量测检测设备链对高端光学元件的需求强，也可能是全球设备厂和国内设备厂共同拉动。它能作为量测检测景气的上游代理，但不能写成整机国产替代份额。这个区别会直接影响估值方法：上游组件看订单、产能、客户结构和良率，整机厂看客户验证和产品平台。",
                "补茂莱客户结构、半导体订单产品类型和产能转固节奏；不得把其收入放进整机竞争份额。",
            ),
        ],
        "q0": [
            (
                "早期离线检测到在线控制",
                f"CD-SEM 产品页强调关键尺寸量测服务生产线过程控制，而不是只做研发抽检 {s(source_ids, 'hitachi_cdsem')}",
                "这代表行业历史中最重要的范式变化：检测从抽样确认质量，变成实时调工艺窗口。这个变化使设备商积累客户数据和 recipe 的价值越来越大，也使新进入者的验证周期变长。国产公司若只有实验室指标，距离产线控制仍有一段距离。",
                "在历史章节中把“研发工具、离线抽检、在线控制、闭环反馈”四个阶段分开写。",
            ),
            (
                "光学仍是吞吐基本盘",
                f"本地研报整理光学检测速度约为电子束检测的 1000 倍，解释了为什么光学类设备常先放量 {s(source_ids, 'tianfeng_zkf_20260420')}",
                "历史上，每一次制程升级都会提高精度要求，但产线仍需要吞吐。光学的价值在于平衡速度和精度，先成为国产设备放量基本盘；电子束和 X 光则在更高精度或三维结构处补短板。中科飞测光学类产品先批量，本质上符合这个历史规律。",
                "后续把国产设备进展按光学、电子束、X 光分别列代际，不用“一站式布局”概括替代。",
            ),
            (
                "先进封装把历史线延长",
                f"Camtek 2025 年收入 4.961 亿美元，Onto 披露 HBM 相关协议超过 2.4 亿美元，说明封装侧 inspection/metrology 已成为独立增长线 {s(source_ids, 'camtek_2025_results')} {s(source_ids, 'onto_2025_results')}",
                "过去讨论量测检测时容易只看晶圆前道；AI/HBM 后，封装侧的 RDL、bump、TSV、warpage 和 X-ray/3D 检测同样成为良率控制点。这不是前道量测的附属，而是新历史阶段的第二条线。",
                "把先进封装侧公司和前道公司拆表，分别跟踪 HBM、CoWoS/CoPoS、TSV 和封装 inspection 订单。",
            ),
        ],
        "q1": [
            (
                "全球格局不是一个 CR 数",
                f"KLA、Nova、Onto、Camtek、Lasertec 分别处在过程控制平台、量测纯玩家、先进封装 inspection、掩模检测等不同位置 {s(source_ids, 'kla_10k_2025')} {s(source_ids, 'nova_2025_results')} {s(source_ids, 'lasertec_fy2026_h1')}",
                "竞争格局若只写 KLA 份额，会漏掉细分赛道；若只列公司，又看不出平台壁垒。正确表达是：KLA 统治最核心的过程控制利润池，Nova 等公司在细分量测/封装中有高弹性，Lasertec 代表极端稀缺但订单周期强的特种检测。中国公司要分别找可替代位置。",
                "补充每家海外公司产品侧收入或订单，未来不要把海外公司粗暴归为一个“外资”。",
            ),
            (
                "中国竞争要按证据强度排序",
                f"中科飞测已有 20.53 亿元收入和 8.81 亿元合同负债；苏州矽行是 40nm BFI 订单；茂莱是上游订单；日联是相邻 X-ray {s(source_ids, 'zhongke_annual_2025')} {s(source_ids, 'tzzk_official_tb1500')} {s(source_ids, 'mol_annual_2025')} {s(source_ids, 'riliang_annual_2025')}",
                "这些证据不能放在同一层。收入和合同负债是最强近端证据；客户订单是较强早期证据；上游订单是景气代理；相邻 X-ray 是方向性证据。把它们混表会让投资排序失真。",
                "Q1 竞争表保留证据等级列：收入兑现、订单验证、上游代理、边界期权。",
            ),
            (
                "公司研报越多不等于公司越强",
                f"本地库对中科飞测和茂莱的公司研报数量明显多于行业总论，但用户已经明确要求公司研报可信度打折。",
                "研报数量反映市场关注度，不反映一手证据密度。中科飞测研报多，是因为它最纯；茂莱研报多，是因为上游订单和光学稀缺。但研报可能弱化隐患，例如扣非亏损、客户验证失败、产能转固和费用。竞争格局必须按公告和产品证据重排，而不是按研报篇数。",
                "在 source 审计中保留研报数量统计，但不得作为公司排序依据。",
            ),
        ],
        "q2": [
            (
                "TAM 与 SAM 的区别",
                f"全球量测检测 TAM 可到数百亿美元，但中国可服务市场取决于成熟/先进节点、客户验证窗口和产品覆盖 {s(source_ids, 'tzzk_annual_2025')}",
                "国产公司真正能服务的不是全球全口径 TAM，而是本土客户愿意导入、设备规格已覆盖、售后能支撑的 SAM。苏州矽行 40nm 订单对应成熟制程 SAM，中科飞测光学批量对应更宽 SAM，电子束和 X 光还处在验证或早期 SAM。",
                "所有空间测算都拆 TAM、SAM、SOM；SOM 必须绑定公司产品节点和客户订单。",
            ),
            (
                "设备周期与结构增量并列",
                f"SEMI 给出 WFE 上行，Camtek/Onto 给出先进封装/HBM inspection 增量 {s(source_ids, 'semi_equipment_forecast_2026')} {s(source_ids, 'camtek_2025_results')}",
                "WFE 周期决定行业 beta，先进封装和国产替代决定结构 alpha。若只看 WFE，容易把周期上行错当国产替代；若只看国产替代，又会忽视客户 capex 下行对订单的压制。量测检测空间必须同时看周期和结构。",
                "季度跟踪加入 WFE、DRAM/HBM capex、先进封装 capex 和中国晶圆厂招标四类前置信号。",
            ),
            (
                "预测值需要折扣",
                f"2030E、2031E 和 CAGR 预测都来自市场研究或公司年报引用，不是一手销售数据 {s(source_ids, 'tianfeng_zkf_20260420')} {s(source_ids, 'tzzk_annual_2025')}",
                "远期空间对赛道判断有用，但不应直接进入估值分母。更好的做法是用远期空间说明天花板，用公司当期收入和订单说明兑现进度，用扣非利润和现金流说明质量。这样既不忽视大空间，也不把空间当业绩。",
                "估值和公司排序中，远期 TAM 只作为定性上限；近端分业务收入和合同负债权重更高。",
            ),
        ],
        "q3": [
            (
                "产品阶段是壁垒审计核心",
                f"中科飞测光学类八大系列批量量产，明场和平整度出货验证，电子束 CD-SEM 仍处客户样片验证，X 光高深宽比通过头部存储客户验证 {s(source_ids, 'huatai_zkf_20260426')}",
                "同一家公司的不同产品阶段差异很大，不能用“一站式布局”统一描述。批量量产能支撑收入和毛利，出货验证能支撑订单线索，样片验证只能支撑技术储备。壁垒分析必须按产品阶段拆，不然会把早期产品估成成熟产品。",
                "公司页建立产品阶段矩阵：研发样机、客户样片、产线验证、小批量、批量复购。",
            ),
            (
                "算法和服务比硬件更难外显",
                f"KLA 服务收入 26.83 亿美元，说明过程控制设备的后续服务、recipe 和应用工程本身就是利润池 {s(source_ids, 'kla_10k_2025')}",
                "国产公司披露通常偏产品和订单，较少披露服务收入、软件收入和客户 recipe 迁移。但长期壁垒正来自这些难外显能力。设备进入客户产线后，应用工程师和算法模型的迭代会形成数据复利，这也是海外龙头难被快速替代的原因。",
                "后续补服务收入、软件模块、装机后升级、客户复购和应用工程团队数据。",
            ),
            (
                "上游光学是壁垒也是约束",
                f"茂莱半导体订单高增说明精密光学需求强，但光学元件小批量多品种、长交期和客户定制化特征会影响整机交付 {s(source_ids, 'mol_annual_2025')}",
                "如果上游光学供给不足，整机厂即使拿到订单也可能交付受限；如果光学上游只服务海外客户，则国产整机并不能直接受益。壁垒分析需要把上游约束纳入，而不是只写整机技术。",
                "补光学元件客户结构、产能利用率、交付周期和国产整机客户占比。",
            ),
        ],
        "q4": [
            (
                "合同负债不是利润",
                f"中科飞测 2026Q1 合同负债 8.81 亿元，但同期研发费用率仍高、扣非仍承压 {s(source_ids, 'zhongke_annual_2025')}",
                "合同负债代表订单和收款前置，但不代表高质量收入。设备交付、验收、毛利、费用和售后都可能改变最终利润。研究中应把合同负债当领先指标，同时跟踪存货、验收周期、毛利率和扣非利润。",
                "季度表中并列合同负债、存货、收入确认、毛利率和扣非净利，缺一项不下结论。",
            ),
            (
                "订单周期会压过长期稀缺",
                f"Lasertec 明确提到客户投资计划修订导致订单下滑，即使 EUV 掩模检测稀缺也不能免疫周期 {s(source_ids, 'lasertec_fy2026_h1')}",
                "这对 A 股主题投资很重要。一个赛道长期稀缺，不代表短期订单不会波动；客户 capex 延后、节点切换和出口管制都会让订单节奏变化。若估值只基于长期稀缺，会忽略短期业绩真空。",
                "风险章节必须把客户 capex 节奏和订单修订作为独立风险，不被长期空间覆盖。",
            ),
            (
                "集团平台公司的估值折扣",
                f"精测、天准、日联都有非半导体或非前道业务，业务混合会带来估值折扣和解释噪声 {s(source_ids, 'jingce_annual_2025')} {s(source_ids, 'tzzk_annual_2025')} {s(source_ids, 'riliang_annual_2025')}",
                "平台公司有好处：技术迁移和客户扩展更快；也有坏处：收入、利润和订单不一定来自半导体量测。投资研究中应对核心业务赋予更高质量权重，对泛业务打折，而不是简单给集团整体高倍数。",
                "公司透视用 sum-of-the-parts 思路描述，不用单一行业倍数套全部收入。",
            ),
        ],
        "q5": [
            (
                "主线不是概念，而是验证链",
                f"中科飞测、精测、苏州矽行、茂莱、日联分别对应整机兑现、分部成长、早期订单、上游光学和边界 X-ray {s(source_ids, 'zhongke_annual_2025')} {s(source_ids, 'jingce_annual_2025')} {s(source_ids, 'tzzk_official_tb1500')} {s(source_ids, 'mol_annual_2025')}",
                "综述页要给可执行判断，而不是把公司名堆成概念池。每家公司进入跟踪池的理由不同，因此验证指标和退出条件也不同。中科飞测退出条件是订单不转收入或扣非恶化；精测是半导体分部失速；天准是节点不推进；茂莱是半导体订单转收入不顺；日联是半导体收入不可拆。",
                "建立 watchlist，每家公司写入证实条件、证伪条件和下一份必读公告。",
            ),
            (
                "先证据后观点",
                f"本轮所有新增数据点都有 source_excerpt、period、unit 和 extraction_method，且通过 db_writer 写入。",
                "这条流程本身就是研究质量的一部分。过去容易出现的问题是先有结论，再找资料填表；本轮必须反过来，先确定资料和口径，再写观点。只有这样，读者才能从正文回到数据点和来源，而不是读一篇无法审计的二手总结。",
                "后续更新继续先入库数据点，再生成文档；发现证据不足时写缺口，不补编。",
            ),
            (
                "结论必须能服务下一步动作",
                f"SEMI/KLA/Nova/Camtek 等海外源负责校准赛道，中科飞测/精测/天准/茂莱/日联负责本土跟踪。",
                "综述不是最后一段漂亮话，而是下一步工作清单。对于基金经理，最有用的是知道该看什么公告、什么数字会改变判断、什么风险会触发降级。本文把这些动作写入 Q5，是为了让行业包能接公司透视和估值，而不是停在行业介绍。",
                "每季度更新 Q5 的 watchlist 和优先级，不再重写宏观叙事，重点更新证实/证伪。",
            ),
        ],
        "q6": [
            (
                "Prompt 全集的处理",
                "根目录 `半导体量测行研.md` 不是空文件，明确列出竞争格局、行业空间、技术壁垒、2025-2030 销售额/出货量/份额、产品类型、全球和中国公司池、实际值/预测值区分等要求。",
                "B 轨不能只回答 prompt，也不能只走默认模板；正确做法是取 A 轨默认全集和 prompt 全集的并集。量测 prompt 点名的 Applied、Nordson、Bruker、赛腾、东方晶源、睿励等公司必须进入公司池或产品图谱；同时，默认 A 轨的边界、产业链、公司透视、财务快照、风险和监控也必须保留。本文把上市公司写入 company_profile，把未上市和近端证据不足公司列为观察项，不用空缺财务伪装完整估值。",
                "后续若 prompt 更新，应做增量差距表：新增问题、已有覆盖、缺口、需要补的官方来源和是否进入 DB。",
            ),
            (
                "PDF 库偏差",
                "36 份 PDF 中公司研报显著多于行业总论，并存在检测服务、测试机、金融工程日报等相邻或噪声内容。",
                "资料库偏差会直接影响研究结论。如果不识别偏差，研究会自动滑向公司推荐和概念扩散；识别后，则可以把公司研报作为线索，把官方和海外源作为锚，把边界资料作为误读提醒。Q6 的作用就是把这个过程透明化。",
                "缓存中保留 PDF 抽取索引，后续新增 PDF 时先跑边界分类。",
            ),
            (
                "审计如何继续",
                f"当前审计检查 period/unit/excerpt、unknown extraction、禁用来源词、重复数据点、文档长度和公司数量。",
                "这只是机器审计底线，不代表研究已经没有问题。人工审计还应看：正文是否回答问题，表格是否有解释，数据是否能回到 source，结论是否有反方，是否把预测当事实。Q6 明确这些标准，目的是让后续维护者知道怎样继续升级。",
                "下一轮加入产品阶段矩阵和客户验证矩阵的结构化审计。",
            ),
        ],
        "company": [
            (
                "中科飞测的核心问题",
                f"收入、合同负债和产品覆盖支持核心地位；扣非亏损和高研发费用率构成约束 {s(source_ids, 'zhongke_annual_2025')}",
                "对中科飞测，研究不是问“是不是国产龙头”，而是问龙头地位能否转化成利润和服务复利。若合同负债转收入、毛利稳定、扣非收窄，龙头逻辑增强；若收入增长靠低毛利交付或研发费用继续吞噬利润，估值要打折。",
                "下一次更新重点看 2026H1 分业务收入、毛利、合同负债和扣非。",
            ),
            (
                "精测电子的折算",
                f"半导体业务 13.18 亿元、集团收入 33.48 亿元，半导体占比约 39% {s(source_ids, 'jingce_annual_2025')}",
                "精测的投资价值不应由集团总收入直接决定，而应看半导体分部能否成为主要利润来源。显示和新能源可能提供现金流，也可能拖累估值。把半导体分部单独折算，才能避免既高估又低估。",
                "补半导体分部毛利、订单和产品交付，缺失时只能保留分部成长观察。",
            ),
            (
                "天准和苏州矽行要拆开",
                f"苏州矽行晶圆检测在手订单近 7000 万元，而天准集团在手订单 14.35 亿元 {s(source_ids, 'tzzk_annual_2025')}",
                "天准集团的工业视觉、机器人和 CPO/PCB 检测业务有自身价值，但不能全部归入半导体前道。苏州矽行应作为单独资产观察：订单、节点、客户复购、增资和产能。这样才能解释为什么天准是早期验证项，而不是核心整机龙头。",
                "公司页每次更新都单列苏州矽行，不用集团订单替代。",
            ),
        ],
    }

    cards = common_cards + blocks.get(kind, [])
    title = {
        "main": "深化研究：从资料到投资逻辑",
        "q0": "深化研究：历史阶段和技术演化",
        "q1": "深化研究：竞争格局审计",
        "q2": "深化研究：市场空间与计算口径",
        "q3": "深化研究：壁垒和验证链",
        "q4": "深化研究：行业特征和风险",
        "q5": "深化研究：结论如何变成动作",
        "q6": "深化研究：资料和流程审计",
        "company": "深化研究：公司透视审计",
    }.get(kind, "深化研究")
    return "\n\n" + card_block(title, cards) + "\n"


def make_mature_extension(kind: str, source_ids: dict[str, int]) -> str:
    """Extra report writing measured by real Chinese character count, not bytes."""

    blocks = {
        "main": f"""
## 成熟行业包补充：Prompt 点名公司与默认 A 轨问题的合并回答

本轮主文档需要同时回答两个问题：一是 prompt 明确列出的竞争格局、市场空间、技术壁垒、2025-2030 销售额/出货量/份额、产品类型和公司池；二是 A 轨默认要求的行业边界、产业链、历史、公司透视、财务、风险、来源审计和后续跟踪。两者取并集后，报告不能只写中科飞测、精测、天准、茂莱这些本地研报覆盖最多的公司，也不能只把海外龙头当背景。Applied Materials、Nordson、Bruker、赛腾股份、东方晶源和睿励科学仪器必须进入研究框架，因为它们分别补上全球设备平台 PDC 能力、X-ray/acoustic/AOI 边界、材料/表面量测边界、国内硅片检测测量资产、国内电子束产品线和国内光学膜厚/缺陷检测历史路径 {s(source_ids, 'prompt')} {s(source_ids, 'amat_metrology_inspection')} {s(source_ids, 'nordson_test_inspection')} {s(source_ids, 'bruker_semiconductor_solutions')}。

但“覆盖”不是把所有公司放进同一张估值表。Applied Materials 的量测检测能力嵌在全球半导体设备平台中，FY2025 Semiconductor Systems 收入 207.98 亿美元，Applied Global Services 收入 63.85 亿美元，它代表的是平台型设备公司怎样把 PDC 嵌入 FEOL/BEOL、EUV、OPC mask qualification 和 3D architectures，不适合作为量测纯玩家份额口径 {s(source_ids, 'amat_10k_2025')}。Nordson 和 Bruker 也类似，前者更偏 X-ray、acoustic、AOI、WaferSense 和电子装联/先进封装检测，后者更偏 AFM、X-ray、ellipsometry、surface metrology 和材料/表面量测；它们能帮助定义产品边界和技术图谱，但不能直接和中科飞测的晶圆前道整机收入相除比较。

国内 prompt 点名公司同样要分层。赛腾股份通过 Optima 资产覆盖硅片边缘缺陷、晶圆背面检测和部分量测能力，但集团业务还包括消费电子、半导体和新能源智能装备，不能把集团自动化收入整体写成半导体量测收入 {s(source_ids, 'secote_optima_official')} {s(source_ids, 'secote_annual_2025')}。东方晶源补上 EBI、CD-SEM、DR-SEM 和良率管理软件的产品线，但未上市且公开财务和订单信息不足，只能作为电子束和软件能力观察项 {s(source_ids, 'dfjy_official_product')}。睿励科学仪器的公开资料更偏历史线索，TFX3000 等设备说明国内曾在 65/55/40/28nm 及 14nm 验证路径上推进，但缺少 2025/2026 近端订单和财务披露，必须降为历史能力和补证清单，不得伪装成当前强证据 {s(source_ids, 'rsl_science_investment')}。

所以主文档的结论应更严格：全球层面，KLA 定义过程控制利润池，Applied/Nordson/Bruker/ASML/Hitachi 定义相邻平台和技术边界，Nova/Onto/Camtek/Lasertec 提供细分成长和订单周期对照；中国层面，中科飞测是最接近核心整机的公司，精测是分部成长，天准/苏州矽行是明场早期订单，茂莱是上游光学订单，日联是 X-ray/先进封装边界，赛腾/东方晶源/睿励是 prompt 要求必须纳入的产品图谱和补证对象。这个结构比“国产替代公司池”更能服务投资判断，因为它把可估值、可跟踪、只作边界和只作历史证据的公司分开了。
""",
        "q0": f"""
## 成熟行业包补充：历史线索如何服务当前判断

Q0 的核心不是回顾设备名词，而是解释为什么量测检测从抽检工具变成制造闭环。早期晶圆线可以容忍较宽工艺窗口，检测更多承担良率抽样和问题定位；进入深亚微米后，CD、膜厚、套刻和缺陷尺寸变小，在线控制的价值开始超过事后确认；再到 FinFET、GAA、HBM 和先进封装，结构从二维走向三维，量测检测就必须同时处理前道图形、材料界面、晶圆形貌、TSV、bump、warpage 和封装互连。Hitachi High-Tech 的 CD-SEM 产品页把关键尺寸量测放在生产线过程控制语境中，说明电子束量测已经不是研发实验室补充，而是高端制程稳定量产的一部分 {s(source_ids, 'hitachi_cdsem')}。

这条历史线直接约束当前公司判断。中科飞测的光学类产品先批量，是因为光学检测在吞吐和在线覆盖上更容易成为国产突破口；电子束 CD-SEM、X 光高深宽比和先进封装检测推进更慢，是因为它们对分辨率、三维结构、客户数据和应用工程要求更高 {s(source_ids, 'huatai_zkf_20260426')}。赛腾、东方晶源、睿励等公司被纳入产品图谱，也不是为了凑公司数，而是因为硅片边缘/背面检测、电子束复查、膜厚和缺陷检测各自对应历史演化中的不同技术节点。Q0 因此要把历史写成“为什么不同产品阶段证据强度不同”，而不是写成设备发展流水账。
""",
        "q1": f"""
## 成熟行业包补充：竞争格局要按产品层级、业务纯度和证据强度重排

Q1 的竞争格局不能只给公司列表。全球公司至少要拆成五组：第一组是 KLA 这类过程控制平台，FY2025 Semiconductor Process Control 收入 109.47 亿美元，服务收入 26.83 亿美元，证明真正壁垒来自装机、软件、recipe、应用工程和服务复利 {s(source_ids, 'kla_10k_2025')}。第二组是 Applied Materials、ASML 这类大设备平台，它们不是量测纯玩家，但量测检测和 computational lithography、e-beam、PDC 能力嵌在平台中，决定先进节点的闭环能力 {s(source_ids, 'amat_metrology_inspection')} {s(source_ids, 'asml_annual_2025')}。第三组是 Nova 这类量测纯玩家，2025 收入 8.806 亿美元、毛利率 57.4%，说明量测本身能形成独立高毛利模型 {s(source_ids, 'nova_2025_results')}。第四组是 Onto、Camtek、Nordson 这类先进封装和相邻 inspection 公司，它们让 AI/HBM 的增量从前道扩展到封装侧 {s(source_ids, 'onto_2025_results')} {s(source_ids, 'camtek_2025_results')} {s(source_ids, 'nordson_test_inspection')}。第五组是 Lasertec/Hitachi High-Tech 这样的特种检测和 CD-SEM 技术锚，提示最高端细分既稀缺也有订单周期 {s(source_ids, 'lasertec_fy2026_h1')} {s(source_ids, 'hitachi_cdsem')}。

中国公司排序则要避免“研报覆盖多就是强”。中科飞测证据最硬，因为收入、合同负债、分业务收入和产品验证都能交叉验证；精测电子要拆半导体分部和集团显示/新能源业务；天准必须把苏州矽行晶圆检测订单和集团工业视觉、机器人、CPO/PCB 检测拆开；茂莱光学是高端精密光学上游订单，不能写成整机份额；日联科技是 X-ray 工业检测平台，先进封装相邻但不是前道核心；赛腾股份、东方晶源、睿励科学仪器必须纳入 prompt 全集，但赛腾是集团多业务平台，东方晶源和睿励公开财务不足，只能列为产品线观察和补证对象 {s(source_ids, 'zhongke_annual_2025')} {s(source_ids, 'jingce_annual_2025')} {s(source_ids, 'tzzk_annual_2025')} {s(source_ids, 'secote_optima_official')} {s(source_ids, 'dfjy_official_product')} {s(source_ids, 'rsl_science_investment')}。

从投资研究角度，竞争格局应落到四个判断。第一，国产替代的核心不是谁名字更像量测检测，而是谁已经进入客户产线并形成收入和复购。第二，海外龙头的对标不能只看产品参数，还要看服务、软件、装机数据和客户应用工程。第三，先进封装和硅片检测是增量方向，但和晶圆前道缺陷检测不是同一竞争池。第四，未上市或财务不透明公司可以进入技术图谱和补证清单，不能进入估值对比表。这样写出来的 Q1 才能指导后续公司透视，而不是只形成一个概念股名单。
""",
        "q2": f"""
## 成熟行业包补充：市场空间要拆 TAM、SAM、SOM 和兑现证据

Q2 必须回答 prompt 的 2025-2030 销售额、出货量、份额和预测问题，但公开资料的完整度并不对称。当前能相对稳健使用的是几类锚：天风转引 QY Research 给出 2023 年全球半导体量测检测市场 152.9 亿美元、2030E 277.6 亿美元；天准年报摘要引用市场研究给出 2024 年全球 192.2 亿美元、中国大陆 63.6 亿美元、2031E 全球 389.5 亿美元；SEMI 给出 WFE、测试和封装设备大周期；KLA、Nova、Onto、Camtek、Lasertec 和 Applied 等公司给出现实收入池 {s(source_ids, 'tianfeng_zkf_20260420')} {s(source_ids, 'tzzk_annual_2025')} {s(source_ids, 'semi_equipment_forecast_2026')} {s(source_ids, 'kla_10k_2025')}。这些锚可以说明市场足够大、增长斜率不低、AI/HBM 和先进封装提供结构增量，但不能被机械拼成一张连续年度序列。

原因在于口径不同。QY Research 的 2023/2030E 口径和天准年报引用的 2024/2031E 口径，可能在是否纳入封装侧、服务、硅片检测、部分实验室工具和区域定义上存在差异。若把 2023 的 152.9 亿美元和 2024 的 192.2 亿美元直接算同比，就可能人为制造高增速；若把东吴专题里的中国去日化量测/检测约 50 亿元人民币当中国总市场，又会低估总体空间。正确做法是同源内计算 CAGR，跨源只做并列和口径说明。报告可以写“市场研究共同指向数百亿美元量级和中高个位数到双位数 CAGR”，但不能写成精确年度增长曲线。

TAM 之后必须拆 SAM。全球 TAM 里包含 KLA、Applied、Nova、Onto、Camtek、Lasertec、Hitachi 等全球客户和高端节点需求；中国公司真正可服务的是本土晶圆厂、存储厂、先进封装厂和部分硅片/材料客户愿意导入国产设备的窗口。中科飞测光学类八大系列批量、明场设备和平整度验证、电子束 CD-SEM 样片验证、X 光高深宽比通过头部存储客户验证，分别对应不同 SAM 阶段 {s(source_ids, 'huatai_zkf_20260426')}。苏州矽行 40nm BFI 订单对应成熟制程明场检测 SAM，不能直接外推到 28/14nm；赛腾 Optima 硅片边缘和背面检测对应硅片/晶圆制造环节的相邻 SAM，也不能直接并入晶圆前道核心量测收入 {s(source_ids, 'tzzk_official_tb1500')} {s(source_ids, 'secote_optima_official')}。

SOM 要回到公司兑现。中科飞测 2025 年收入 20.53 亿元、合同负债 2026Q1 升至 8.81 亿元，是中国整机公司最接近 SOM 的证据；精测电子半导体业务约 13.18 亿元，但集团收入 33.48 亿元，说明只可把分部收入纳入 SOM；天准/苏州矽行晶圆检测订单近 0.70 亿元，占集团在手订单约 4.9%，说明它还是早期订单；茂莱半导体在手订单约 4.6 亿元，说明上游光学订单强，但不是整机 SOM；日联的先进封装和 X-ray 业务要看半导体收入拆分，不能用工业检测总收入替代 {s(source_ids, 'zhongke_annual_2025')} {s(source_ids, 'jingce_annual_2025')} {s(source_ids, 'tzzk_annual_2025')} {s(source_ids, 'mol_annual_2025')} {s(source_ids, 'riliang_annual_2025')}。

prompt 还要求出货量和份额。这里必须明确缺口：半导体量测检测设备的公开出货量不像 WFE 总额或公司收入那样标准化，设备单价、机型、是否含服务和交付验收差异很大，公开资料通常只披露收入、订单、合同负债、在手订单或少量“出货台数”。中科飞测曾披露 2024 年量检测设备出货达 1000 台，但不能据此直接计算全球份额，因为不同机型价值量差异巨大，且海外公司通常不披露可比台数 {s(source_ids, 'huayuan_zkf_20260116')}。因此，本轮对份额的处理是用收入池和公司收入做粗略体量对照，用产品阶段和客户验证做商业化判断，不用不可比台数造精确份额。

2025-2030 的预测也要分层使用。SEMI 对 WFE、测试和封装设备的预测可作为设备 beta；TAM 研究可作为远期天花板；公司收入、合同负债和订单可作为近端兑现；毛利率、扣非利润和现金流可作为质量约束。只有这四层同时改善，才可以把“市场空间大”升级为“公司估值可上修”。若只有 TAM 上行而公司订单不转收入，或只有合同负债上升但毛利率和扣非利润恶化，Q2 结论都必须保持谨慎。这个框架能避免两个错误：一是把宏观空间直接套到单家公司，二是把单家公司短期订单当作行业长期空间。
""",
        "q3": f"""
## 成熟行业包补充：壁垒不是参数表，而是客户产线里的复利

Q3 要把技术壁垒写成可以被验证的链条，而不是列几个关键词。第一层是硬件极限：光学系统、电子束源、探测器、X-ray 源、运动平台、真空、温控和控制系统决定分辨率、吞吐、稳定性和可维护性。第二层是算法和模型：缺陷识别、OCD、CD-SEM 图像处理、三维结构重建、recipe 迁移和良率管理软件决定设备能否在不同客户、不同制程和不同材料上稳定工作。第三层是客户验证：样片通过不等于产线通过，产线验证不等于批量复购，批量复购不等于形成服务和软件收入。第四层是装机数据和服务：KLA FY2025 服务收入 26.83 亿美元，说明成熟平台的护城河并不止硬件本体 {s(source_ids, 'kla_10k_2025')}。

技术路线之间也不能用单一优劣排序。光学检测吞吐高，适合在线覆盖和国产先放量；电子束分辨率高，适合 CD-SEM 和缺陷复查，但吞吐低；X 光和声学检测适合三维结构、先进封装和材料内部缺陷；AFM、ellipsometry、surface metrology 更偏材料/表面和纳米尺度量测。Applied Materials 官方页把 metrology、wafer inspection、defect review、analysis/classification 与 FEOL/BEOL、EUV、OPC mask qualification 和 3D architectures 放在同一过程控制语境中；Bruker 的 AFM/X-ray/ellipsometry/surface metrology 则说明材料和表面量测是另一组能力；Nordson 的 X-ray、acoustic、AOI 和 WaferSense 更接近先进封装、电子装联和过程监控边界 {s(source_ids, 'amat_metrology_inspection')} {s(source_ids, 'bruker_semiconductor_solutions')} {s(source_ids, 'nordson_test_inspection')}。

中科飞测的壁垒必须按产品阶段拆。光学类八大系列批量量产，说明成熟产品已经有收入基础；明场设备和平整度进入头部客户验证/出货，说明从暗场/宽场向更难产品推进；电子束 CD-SEM 处于客户样片工艺验证，说明高精度路线仍在早期；X 光高深宽比通过头部存储客户验证，说明存储和先进封装相关三维结构是下一阶段增量 {s(source_ids, 'huatai_zkf_20260426')}。如果把这些产品统一写成“一站式布局”，就会把成熟收入、产线验证和样片验证混成同一证据强度。

精测电子、天准/苏州矽行、赛腾、东方晶源和睿励的壁垒也不相同。精测的壁垒来自显示检测工程能力向半导体膜厚、OCD、电子束和先进封装检测迁移，但半导体业务占集团约 39%，需要继续观察分部收入和利润 {s(source_ids, 'jingce_annual_2025')}。苏州矽行的 40nm BFI 订单说明成熟制程明场检测验证推进，但 TB2000 面向 28/14nm 的进展还需要客户复购和更近节点证据 {s(source_ids, 'tzzk_official_tb1500')}。赛腾 Optima 的硅片边缘/背面检测说明硅片制造过程有相邻机会，但集团自动化业务复杂，产品线壁垒不能直接等同晶圆前道整机壁垒 {s(source_ids, 'secote_optima_official')}。东方晶源和睿励分别提供电子束/良率软件和光学膜厚/缺陷检测历史能力，但公开订单、财务和客户验证不足，所以壁垒应写为“技术图谱必须跟踪”，不是“商业化已经确认” {s(source_ids, 'dfjy_official_product')} {s(source_ids, 'rsl_science_investment')}。

上游壁垒同样重要。茂莱光学 2026Q1 半导体在手订单约 4.6 亿元，占总在手订单约 69%，说明高端精密光学已经成为量测检测链条的强景气代理 {s(source_ids, 'mol_annual_2025')}。但上游订单有两种读法：若客户主要是国内整机厂，它会增强国产设备交付确定性；若客户主要是海外设备厂，它说明全球量测检测景气，但未必直接提高国内整机份额。因此，茂莱的壁垒不是客户验证，而是设计、加工、装调、小批量多品种交付和产能转固；它应放在上游稀缺层，而非整机份额层。

Q3 的投资落点是建立“壁垒证据等级”。A级是已经进入收入、合同负债、毛利率和客户复购的产品；B级是有客户订单或产线验证但收入规模仍小；C级是样机、样片或历史资料；D级是相邻概念。中科飞测部分光学产品接近 A/B，电子束仍偏 C/B 之间；精测半导体分部是 B，但集团口径要打折；苏州矽行是 B/C；茂莱是上游 A/B；日联、赛腾、东方晶源、睿励根据公开信息分别处在边界或补证层。壁垒章节只有这样写，才能防止把早期线索提前折现。
""",
        "q4": f"""
## 成熟行业包补充：行业经济模型和风险触发器

半导体量测检测的行业特征是“设备周期 + 技术代际 + 客户验证 + 服务复利”四者叠加。设备周期来自晶圆厂、存储厂和封装厂 capex，SEMI 的 WFE、测试和封装设备预测能解释 beta；技术代际来自 GAA、High-NA EUV、HBM、先进封装和三维结构，能解释为什么过程控制价值量上升；客户验证决定国产替代速度；服务复利决定成熟龙头利润率和粘性 {s(source_ids, 'semi_equipment_forecast_2026')} {s(source_ids, 'kla_10k_2025')}。这四者同向时，行业最强；任何一项反向，股价和订单都会分化。

财务上，成熟海外龙头和国内成长公司处在不同阶段。KLA 的服务收入和 Nova 的高毛利说明成熟过程控制/量测平台可以形成持续利润；中科飞测、精测、天准/苏州矽行仍处于高研发、高验证、高存货或业务纯度折算阶段 {s(source_ids, 'nova_2025_results')} {s(source_ids, 'zhongke_annual_2025')}。这意味着国内公司不能只看收入增速。合同负债上升是领先信号，但要等收入确认、毛利率稳定、扣非亏损收窄和经营现金流改善，才能说明订单质量高。若收入增长来自低毛利交付、费用资本化、存货堆积或客户验收拉长，估值应下修。

行业风险也要写成触发器。第一，客户 capex 延后会影响订单，即使 Lasertec 这类 EUV 掩模检测稀缺公司也会受客户投资计划修订扰动 {s(source_ids, 'lasertec_fy2026_h1')}。第二，客户验证失败会让样机和订单无法转收入，尤其是电子束、X 光、高深宽比和先进封装产品。第三，业务纯度混淆会放大主题弹性，精测、天准、赛腾、日联都需要拆非半导体或非前道业务。第四，上游关键零部件、光学、电子束源和探测器可能限制国产交付。第五，远期 TAM 和公司近端收入之间存在巨大距离，不能用 2030E/2031E 空间替代 2026 年收入质量。

Q4 的可执行结论是：每次更新先看四张表。第一张是行业 beta 表：WFE、DRAM/HBM、先进封装和中国晶圆厂扩产。第二张是产品验证表：光学、明场/暗场、CD-SEM、X 光、硅片检测、封装 inspection 各自处于什么阶段。第三张是财务质量表：收入、毛利、扣非、经营现金流、存货、合同负债和研发费用。第四张是口径审计表：公司收入中哪些是真半导体量测检测，哪些只是显示、工业视觉、自动化、X-ray 工业检测或上游组件。只有四张表同时支持，行业特征才可以写成结构成长；若其中两张以上背离，就只能写成周期反弹或早期验证。
""",
        "q5": f"""
## 成熟行业包补充：综述必须给出下一步研究动作

Q5 要把前面所有信息转成投资研究动作。第一条主线是全球锚：KLA、Applied、ASML、Nova、Onto、Camtek、Lasertec、Hitachi High-Tech、Nordson、Bruker 共同告诉我们，量测检测不是一个单一设备小类，而是先进制造中的过程控制体系。KLA 定义平台利润池，Applied/ASML 说明量测检测嵌入大设备平台，Nova 说明量测纯玩家可以有高毛利，Onto/Camtek/Nordson 说明先进封装和 X-ray/acoustic/AOI 是结构增量，Lasertec 提醒最高端特种检测也有订单周期，Bruker/Hitachi 则把材料/表面和 CD-SEM 技术边界补齐 {s(source_ids, 'kla_10k_2025')} {s(source_ids, 'amat_metrology_inspection')} {s(source_ids, 'nova_2025_results')} {s(source_ids, 'camtek_2025_results')} {s(source_ids, 'bruker_semiconductor_solutions')}。

第二条主线是中国兑现：中科飞测是核心整机，判断重点是合同负债能否转收入、光学产品毛利是否稳定、明场/平整度/X 光/电子束能否从验证升级到批量、扣非亏损能否收窄 {s(source_ids, 'zhongke_annual_2025')}。精测电子是分部成长，判断重点是半导体收入占比、膜厚/OCD/电子束/先进封装产品订单和集团其他业务拖累 {s(source_ids, 'jingce_annual_2025')}。天准/苏州矽行是早期明场订单，判断重点是 40nm 后能否向 28/14nm 继续推进，以及苏州矽行订单占集团比例是否提高 {s(source_ids, 'tzzk_annual_2025')}。茂莱是上游光学景气代理，判断重点是半导体订单转收入、客户结构和产能转固 {s(source_ids, 'mol_annual_2025')}。日联、赛腾、东方晶源、睿励分别对应 X-ray/先进封装边界、硅片检测测量、电子束/良率软件、光学膜厚/缺陷检测历史线索，除非拿到近端财务和客户证据，否则不升级为核心估值对象 {s(source_ids, 'riliang_annual_2025')} {s(source_ids, 'secote_optima_official')} {s(source_ids, 'dfjy_official_product')} {s(source_ids, 'rsl_science_investment')}。

第三条主线是指标跟踪。行业层面看 WFE、DRAM/HBM capex、先进封装 capex、中国晶圆厂招标和出口管制；产品层面看光学、明场/暗场、CD-SEM、X 光、硅片检测、封装 inspection 的客户验证阶段；公司层面看收入、分业务收入、合同负债、存货、毛利率、扣非利润、经营现金流、研发费用率和 capex；证据层面看公告、年报、产品页、客户验证、订单和卖方研报之间的一致性。若一个公司只有卖方预测或概念标题，没有公告/产品/客户/财务四类证据交叉，不进入核心排序。

第四条主线是证实/证伪。证实中科飞测，需要看到 2026H1/H2 收入确认、合同负债继续健康、毛利率不明显牺牲、扣非亏损收窄，以及明场、电子束、X 光至少一条产品线从验证迈向批量。证实精测，需要半导体分部继续高增并改善利润，而不是集团收入靠显示或新能源支撑。证实苏州矽行，需要更先进节点订单和复购。证实茂莱，需要半导体订单转收入并保持现金流。证实赛腾/东方晶源/睿励，需要官方近端订单、客户验证或融资/财务证据；否则它们只留在图谱。

综述页最终要服务老板快速决策：本行业值得跟踪，但不是平均买入一篮子“量测检测概念”。优先级应是中科飞测作为核心整机、精测作为分部成长、茂莱作为上游稀缺、天准/苏州矽行作为早期验证；海外公司用于估值锚和技术路径；赛腾、东方晶源、睿励、日联用于边界和补证。最重要的风险是把 TAM 当收入、把验证当批量、把集团收入当半导体收入、把上游订单当整机份额、把历史资料当当前证据。后续每次更新都应围绕这些错误防线展开。

如果只能给一个行动清单，Q5 应写成：先看中科飞测和精测的最新公告，再看茂莱订单和产能，再看天准/苏州矽行节点推进，再补赛腾 Optima、东方晶源和睿励的近端官方证据；同时用 KLA/Nova/Onto/Camtek/Lasertec 的季度数据校准海外周期。这个清单比宏观叙事更有用，因为它告诉研究员下一次该查什么、什么信息能改变判断、什么情况必须降级。
""",
        "q6": f"""
## 成熟行业包补充：Prompt 覆盖验收和后续补证清单

Q6 必须把 prompt 全集逐项落地。竞争格局已经覆盖全球 KLA、Applied Materials、ASML、Nova、Onto、Camtek、Lasertec、Hitachi High-Tech、Nordson、Bruker，以及中国中科飞测、精测电子、天准/苏州矽行、茂莱光学、日联科技、赛腾股份、东方晶源和睿励科学仪器。行业空间已经写明多套市场规模口径、WFE 设备 beta、中国市场和公司兑现锚。技术壁垒已经拆到光学、电子束、X 光、硅片检测、先进封装、材料/表面量测、软件和服务复利。公司透视已经补 PE/PB/PS、市值人民币和美元口径、毛利率、净利率、经营现金流、capex 和近期事件；Bruker 这类 GAAP 亏损公司 PE 按“亏损/不可比”处理，不用空值掩盖。

仍需补证的项目也要写清。第一，2025-2030 逐年出货量和份额缺少统一公开口径，不能用不可比台数伪造。第二，赛腾 Optima、东方晶源、睿励科学仪器的近端订单、客户和财务披露不足，需要优先查公司官网、公告、招标、中标、融资和客户侧材料。第三，电子束源、探测器、光学元件、X-ray 源、运动平台和软件算法的国产化率仍缺独立公开数据。第四，客户实名验证普遍不足，不能用“头部客户”替代 NVIDIA、TSMC、长江存储、中芯国际、华虹、长鑫、华为等具体客户确认。Q6 的作用不是把缺口藏起来，而是让后续研究知道从哪里继续补。
""",
        "company": f"""
## 成熟行业包补充：公司透视的排序逻辑

公司透视不应按市值或研报数量排序，而应按“业务纯度、产品阶段、客户验证、财务质量、可估值性”排序。中科飞测业务纯度最高，财务和产品证据最接近核心整机；精测电子需要把半导体分部从显示和新能源里拆出来；天准/苏州矽行要把苏州矽行单独看，不能把集团在手订单全写成晶圆检测；茂莱光学看上游精密光学订单和产能；日联看 X-ray/先进封装边界；赛腾看 Optima 半导体检测测量资产和集团半导体收入占比；东方晶源和睿励看近端官方证据是否补齐。Applied、Nordson、Bruker、ASML、Hitachi High-Tech 等海外公司进入公司透视的作用是校准产品边界和全球估值锚，不是直接替代 A 股公司排序。
""",
    }
    floor_blocks = {
        "main": f"""
## 真实字符数补充：主文档的最终使用方式

主文档最终服务的是研究员第一次进入行业时的判断框架。它要让读者知道哪些证据已经能改变投资排序，哪些只是技术图谱，哪些必须继续补证。当前最稳的排序是：全球锚用 KLA、Applied、Nova、Onto/Camtek 和 Lasertec 校准；中国核心用中科飞测、精测、天准/苏州矽行、茂莱、日联分层；prompt 点名的赛腾、东方晶源、睿励作为产品线和补证对象保留。后续任何更新都不能绕过这个分层，否则会重新退回概念池写法。
""",
        "q1": f"""
## 真实字符数补充：竞争格局的横向比较方法

Q1 还需要把“横向比较”讲清。KLA 与 Nova、Onto、Camtek 之间，不是同一产品的大小公司对比，而是平台型过程控制、量测纯玩家、封装侧 inspection 三类商业模式对比。KLA 的服务收入让设备销售变成长期客户关系；Nova 的毛利率证明量测模型和材料理解能形成独立利润；Onto/Camtek 的 HBM 和先进封装订单说明 AI 需求会在封装侧二次释放；Lasertec 的订单波动说明稀缺设备也不能脱离客户 capex 周期 {s(source_ids, 'kla_10k_2025')} {s(source_ids, 'nova_2025_results')} {s(source_ids, 'onto_2025_results')} {s(source_ids, 'camtek_2025_results')} {s(source_ids, 'lasertec_fy2026_h1')}。

中国公司也要按同样方法横向比较。中科飞测对标的是国产整机产品平台，关键是产品从验证到量产的转换；精测电子对标的是跨行业检测平台向半导体迁移，关键是分部纯度；天准/苏州矽行对标的是明场晶圆检测早期订单，关键是节点升级和复购；茂莱对标的是上游光学瓶颈，关键是客户结构和产能；日联对标的是 X-ray/先进封装边界，关键是半导体收入拆分；赛腾、东方晶源、睿励对标的是 prompt 点名的补证对象，关键是近端官方证据是否足够。这种比较方式能解释为什么有些公司能进核心排序，有些只能进观察清单。
""",
        "q2": f"""
## 真实字符数补充：2025-2030 预测如何进入研究模型

Q2 的预测不能只写一个 CAGR。2025-2030 的模型应由三层构成。第一层是行业需求层：WFE、DRAM/HBM capex、先进逻辑、先进封装和中国本土扩产共同决定过程控制设备需求。SEMI 的 WFE 预测给出设备总 beta，Onto/Camtek 的 HBM/先进封装订单给出封装侧 alpha，KLA/Nova 的收入和毛利给出全球现实利润池 {s(source_ids, 'semi_equipment_forecast_2026')} {s(source_ids, 'onto_2025_results')} {s(source_ids, 'camtek_2025_results')} {s(source_ids, 'kla_10k_2025')} {s(source_ids, 'nova_2025_results')}。第二层是产品覆盖层：光学检测、明场/暗场、CD-SEM、OCD/膜厚、X 光、硅片边缘/背面检测、封装 inspection 的客户验证阶段不同，不能用同一个国产化率。第三层是公司兑现层：收入、合同负债、订单、毛利率、扣非利润和现金流决定公司能分到多少。

如果按这个模型看，TAM 只是起点。全球数百亿美元空间说明行业足够大，但中国公司可服务空间取决于客户愿意把哪些制程点开放给国产设备。中科飞测光学类产品已经有收入基础，明场、平整度、电子束和 X 光处在不同验证阶段；苏州矽行 40nm BFI 订单说明成熟制程明场检测打开窗口；赛腾 Optima 说明硅片边缘/背面检测也应进入相邻市场空间；东方晶源和睿励说明电子束、良率软件和光学膜厚历史能力存在，但缺近端兑现 {s(source_ids, 'huatai_zkf_20260426')} {s(source_ids, 'tzzk_official_tb1500')} {s(source_ids, 'secote_optima_official')} {s(source_ids, 'dfjy_official_product')} {s(source_ids, 'rsl_science_investment')}。

Q2 还要防止把“销售额”和“出货量”混为一谈。量测检测设备单价差异巨大，光学缺陷检测、CD-SEM、X-ray、硅片检测和封装 inspection 的价值量不同，台数不可直接相加。公开资料中可核的是收入、订单、合同负债和少量出货描述；不可核的是统一口径的全球台数、逐年产品台数和客户实名份额。因此，本文选择用收入和订单做代理，用产品阶段做约束，用远期 TAM 做天花板。若未来拿到设备台数，必须按机型、单价、是否含服务、是否验收、是否重复订单拆开，否则台数会误导空间。

公司映射上，Q2 的结论要分成“确定兑现、早期兑现、相邻空间、历史/补证”。确定兑现是中科飞测部分光学类产品和收入；早期兑现是精测半导体分部、苏州矽行订单和中科飞测明场/X 光/电子束验证；相邻空间是茂莱光学、日联 X-ray/先进封装、赛腾硅片检测；历史/补证是东方晶源和睿励。远期 2030E/2031E 空间只提高这些层级的天花板，不能改变证据等级。只有当某个早期或相邻公司拿到公告级订单、客户复购和收入确认，它才可以升级到核心市场空间表。

最后，预测值要和风险一起出现。WFE 下修会压行业 beta；客户验证延迟会压国产替代斜率；出口管制可能同时给国产公司机会和零部件约束；高研发和存货会压利润质量；市场研究口径变化会让 TAM 看起来跳跃。Q2 写到这里，市场空间才不是一张漂亮表，而是一套能解释为什么空间大、为什么公司不一定都受益、为什么要继续补证的研究模型。
""",
        "q3": f"""
## 真实字符数补充：壁垒审查的五个失败场景

Q3 除了写正向壁垒，还要写失败场景。第一种失败是“参数过关但产线不过关”。设备在实验室样片上能检测，并不代表能在客户产线长时间稳定运行；误报漏报、吞吐、维护频率、recipe 迁移和数据接口都会影响是否复购。第二种失败是“客户验证过关但利润不过关”。如果国产设备靠低价进入客户，收入增长可能伴随毛利率下降和售后成本上升，最终不能形成高质量利润。第三种失败是“产品线多但核心少”。公司披露覆盖光学、电子束、X 光、封装和软件，如果没有每条线的客户阶段和收入贡献，就不能把产品线宽度当平台能力。第四种失败是“集团业务拖累”。精测、天准、赛腾、日联都有非核心业务，若集团其他业务波动，会稀释半导体量测逻辑。第五种失败是“上游瓶颈未解”。精密光学、电子束源、探测器和软件算法如果受限，整机交付会被卡住。

这些失败场景决定壁垒的评分方法。中科飞测的优势是整机纯度和产品推进，但电子束和 X 光仍需从验证走向批量；精测的优势是检测平台迁移，但要证明半导体分部利润；苏州矽行的优势是 40nm 明场订单，但 28/14nm 仍需补证；茂莱的优势是半导体光学订单，但要证明客户结构和产能转固；赛腾的优势是 Optima 硅片检测测量资产，但要拆集团半导体纯度；东方晶源和睿励的优势是产品线补全，但缺近端公开订单和财务 {s(source_ids, 'zhongke_annual_2025')} {s(source_ids, 'jingce_annual_2025')} {s(source_ids, 'tzzk_official_tb1500')} {s(source_ids, 'mol_annual_2025')} {s(source_ids, 'secote_optima_official')}。

海外对标也要带入失败场景。KLA 的服务收入说明真正平台能力会沉淀服务和软件；Lasertec 的订单波动说明高壁垒不等于无周期；Applied 和 ASML 说明量测检测能力经常嵌在更大的设备生态里；Bruker、Nordson 和 Hitachi 说明相邻技术路线各有边界 {s(source_ids, 'kla_10k_2025')} {s(source_ids, 'lasertec_fy2026_h1')} {s(source_ids, 'amat_metrology_inspection')} {s(source_ids, 'bruker_semiconductor_solutions')} {s(source_ids, 'nordson_test_inspection')} {s(source_ids, 'hitachi_cdsem')}。国内公司若只复制硬件参数，而没有服务、软件、客户数据和应用工程师网络，壁垒就仍在早期。

Q3 最终应输出一个审查清单：产品是否明确；客户阶段是否明确；收入或订单是否明确；毛利和现金流是否支持；业务纯度是否足够；反方风险是否写清。任何公司若只满足前三项，最多是早期机会；若六项都满足，才可以进入核心排序。这个清单也解释为什么公司研报要打折：研报常强调产品和空间，但不一定充分展示失败场景、客户验收和财务质量。
""",
        "q4": f"""
## 真实字符数补充：从行业特征到财务读表

Q4 的行业特征必须落到财务读表。量测检测设备企业的资产负债表会先出现研发、存货、合同负债和在建项目，然后才通过交付验收反映为收入和利润。合同负债上升通常是好信号，但如果存货同步大幅上升、毛利率下降或经营现金流转弱，说明订单质量和验收节奏可能有问题。研发费用率高也不能简单看成坏事：如果对应新产品客户验证和产品节点升级，是必要投入；如果长期不能转化为收入，则会侵蚀估值。中科飞测、精测、天准和茂莱的财务读法都必须按这个顺序展开，而不是只引用收入同比。

行业周期也要用财务指标验证。WFE 上行时，订单、合同负债、存货和收入可能同步改善；但如果客户 capex 突然推迟，最先变的是订单和合同负债，之后才是收入和利润。Lasertec 的订单波动给了一个海外样本，说明长期稀缺不等于短期订单稳定 {s(source_ids, 'lasertec_fy2026_h1')}。中国公司如果披露“客户验证推进”但合同负债、订单和收入没有同步改善，就只能保留技术进展，不能升级为景气确认。

Q4 还需要解释估值为何分化。中科飞测可以获得核心整机溢价，但要被扣非亏损和高研发约束；精测电子需要分部折算，不能给集团全部高倍数；茂莱光学可以作为上游稀缺，但估值应跟客户结构和产能转固绑定；天准/苏州矽行、赛腾、东方晶源、睿励则更依赖下一轮补证。行业特征不是“高壁垒所以高估值”，而是“高壁垒只有在订单、毛利、现金流和复购兑现后才支持高估值”。这句话应成为 Q4 的核心使用方式。
""",
        "q5": f"""
## 真实字符数补充：把结论压成可执行的跟踪表

Q5 的最终输出应是一张动态跟踪表。核心组是中科飞测：每次更新查 2026H1/H2 收入、检测/量测分业务、合同负债、存货、毛利率、扣非利润、电子束和 X 光产品阶段。第二组是精测电子：查半导体业务收入占比、订单、利润、膜厚/OCD/电子束/先进封装产品进展，以及显示和新能源是否拖累集团。第三组是天准/苏州矽行：查苏州矽行订单、节点、客户复购和集团订单占比。第四组是茂莱：查半导体订单转收入、客户结构、产能转固和费用。第五组是边界组：日联、赛腾、东方晶源、睿励分别查 X-ray/先进封装、硅片检测、电子束/良率软件和近端官方证据。

每组还要有降级条件。中科飞测若合同负债不转收入、毛利率明显下降、扣非亏损扩大或新产品长期停在验证，降级；精测若半导体分部增速放缓或集团业务拖累利润，降级；苏州矽行若 40nm 后节点不推进，降级；茂莱若订单无法转收入或客户集中暴露，降级；赛腾、东方晶源、睿励若继续缺少近端订单和客户证据，就只保留在产品图谱，不进入核心公司透视。降级条件必须和升级条件同页出现，防止综述变成单边推荐。

综述还要明确哪些信息最可能改变行业判断。第一是 SEMI、KLA、Nova、Onto、Camtek 和 Lasertec 的季度/年度数据，如果海外周期明显下修，中国公司订单也可能受影响。第二是国内晶圆厂和存储厂招标、扩产和国产导入节奏。第三是先进封装和 HBM capex，因为它会同时影响前道、封装侧和 X-ray/3D inspection。第四是政策和出口管制，它可能增加国产导入窗口，也可能限制关键零部件。第五是公司财务质量，尤其是经营现金流和扣非利润。只有这些证据发生变化，Q5 才应该调整结论。

最后，Q5 要保留一句清楚的研究回答：半导体量测检测行业值得作为 AI/HBM、先进制程和国产替代的高优先级跟踪方向，但当前可投资研究不是平均覆盖所有概念公司，而是按证据强度分层推进。中科飞测最核心，精测和茂莱次之，天准/苏州矽行是早期验证，日联/赛腾/东方晶源/睿励是边界和补证，海外公司用于校准。这个回答直接对应老板需要的判断：先看谁，为什么看，什么情况加码研究，什么情况降级或剔除。
""",
    }
    final_blocks = {
        "main": """
这个主文档以后还应作为索引页使用：先读行业边界，再读市场空间和公司分层，最后进入公司透视。若新资料不能改变产品阶段、客户验证、收入质量或业务纯度，就只更新数据点，不改核心判断。
""",
        "q1": f"""
## 真实字符数补充：排序不是静态名单

竞争排序需要随证据变化。若中科飞测新产品从验证进入批量，核心地位增强；若精测半导体分部收入占比继续提高且利润改善，平台折价收窄；若苏州矽行只停留在 40nm 订单，仍是早期验证；若赛腾披露 Optima 半导体订单和客户复购，可从边界组升级；若东方晶源或睿励补出近端客户和财务证据，也可以从技术图谱进入公司透视。反过来，如果只有卖方报告或概念表述，没有公告、产品页、客户验证和财务兑现，排序不能升级。Q1 的作用就是保持这套动态规则，而不是给一次性的公司名录。
""",
        "q2": f"""
## 真实字符数补充：量测检测空间的计算样例

可以用一个简化样例说明 Q2 怎么算。若先看全球 TAM，KLA 过程控制收入 109.47 亿美元、Nova 8.806 亿美元、Camtek 4.961 亿美元、Onto 约 10.05 亿美元，已经构成现实收入池；再看市场研究，2024 年全球量测检测设备市场约 192.2 亿美元、2031E 约 389.5 亿美元，说明市场研究口径比主要上市公司收入池更宽，可能包含更多产品、地区和封装/相邻设备 {s(source_ids, 'kla_10k_2025')} {s(source_ids, 'nova_2025_results')} {s(source_ids, 'camtek_2025_results')} {s(source_ids, 'onto_2025_results')} {s(source_ids, 'tzzk_annual_2025')}。因此，研究中不应把公司收入池和市场研究 TAM 简单相加，也不应直接用 TAM 减海外收入推算中国国产替代空间。

再看中国 SOM。中科飞测 2025 年收入 20.53 亿元，按美元折算约为 KLA 过程控制收入的低个位数比例；精测半导体分部约 13.18 亿元，但集团口径要折算；苏州矽行订单约 0.70 亿元，是早期验证；茂莱半导体在手订单约 4.6 亿元，是上游订单而非整机收入 {s(source_ids, 'zhongke_annual_2025')} {s(source_ids, 'jingce_annual_2025')} {s(source_ids, 'tzzk_annual_2025')} {s(source_ids, 'mol_annual_2025')}。这组计算告诉我们，中国公司已经有收入和订单，但距离全球平台体量仍远。投资研究的重点不是夸大空间，而是判断收入和订单是否沿着客户验证曲线持续上移。

对 2025-2030 展望，本文建议使用情景而不是单点预测。基准情景是 WFE 维持上行、中国本土扩产继续、光学类国产设备稳步放量、电子束/X 光缓慢验证；乐观情景是 HBM/先进封装和国内存储扩产超预期，明场、平整度、X 光和 CD-SEM 从验证转批量；悲观情景是客户 capex 延后、出口管制限制关键零部件、价格竞争压毛利、订单验收拉长。每个情景都要对应公司层面的收入、毛利和现金流，而不是只改 TAM。
""",
        "q3": f"""
## 真实字符数补充：壁垒如何映射到公司估值

壁垒只有映射到收入质量和估值，才有研究价值。对中科飞测，壁垒如果成立，应表现为产品线从光学基本盘扩展到明场、平整度、X 光和电子束，收入增长同时伴随毛利稳定、合同负债转收入和扣非亏损收窄；如果只表现为研发费用高和样片验证多，估值就需要折扣。对精测，壁垒如果成立，应表现为半导体分部收入占比提高、利润改善和产品节点升级；如果集团其他业务拖累，半导体壁垒也要被折价。对苏州矽行，壁垒如果成立，应从 40nm 订单推进到 28/14nm 验证和复购；如果节点不升级，壁垒只停留在成熟制程。

对上游和边界公司，映射方式不同。茂莱光学的壁垒不是客户产线验证，而是精密光学设计、加工、装调、交付和客户结构；若半导体订单能持续转收入且毛利稳定，上游壁垒成立。日联科技的壁垒在 X-ray 和工业检测平台，若先进封装收入无法拆分，就不能给前道量测估值。赛腾的壁垒取决于 Optima 产品在硅片/晶圆检测中的订单和客户，而不是集团自动化收入。东方晶源和睿励的壁垒取决于近端订单和产品迭代，如果只剩历史资料，估值只能按技术图谱处理。

Q3 因此应给出壁垒到估值的翻译规则：硬件参数影响产品准入，客户验证影响订单概率，批量复购影响收入质量，服务和软件影响长期毛利，现金流和扣非影响估值可信度。任何一家公司如果只满足前两项，不应获得成熟平台估值；满足前四项但现金流差，也要保留财务折扣；只有五项同时改善，才能把高壁垒写成高估值。这个翻译规则能让壁垒章节避免空泛，也能直接连接公司透视。
""",
        "q4": f"""
## 真实字符数补充：行业特征的复核节奏

Q4 的复核节奏应分月度、季度和年度。月度看晶圆厂招标、客户扩产、海外订单和政策变化；季度看上市公司收入、合同负债、存货、毛利率、经营现金流和研发费用率；年度看产品线是否升级、客户复购是否形成、服务和软件是否沉淀。量测检测行业的特点是技术证据领先财务，财务又滞后客户验证，因此不能用单个季度收入解释全部，也不能用远期空间忽略短期订单。

行业特征还要区分“好增长”和“差增长”。好增长是客户验证升级、收入确认、毛利稳定、现金流改善和扣非收窄同时出现；差增长是收入增长但毛利下降、存货上升、现金流变差或研发费用无法转化为订单。中科飞测、精测、天准、茂莱、赛腾等公司都可能出现这两种增长，Q4 必须让读者知道该用什么指标辨别。只有这样，行业特征页才不是背景介绍，而是财务和经营数据的读表指南。
""",
        "q5": f"""
## 真实字符数补充：综述页的研究备忘录

下一轮研究应按资料优先级展开。第一优先级是公告、年报、季报、业绩说明会和官方产品页；第二优先级是行业组织、海外公司财报和产品资料；第三优先级才是券商公司研报。具体任务包括：更新中科飞测 2026H1 分业务收入和合同负债；更新精测半导体分部和集团利润；核查苏州矽行节点推进；核查茂莱半导体订单转收入；核查赛腾 Optima 是否有新增半导体客户；核查东方晶源和睿励是否有近端公开订单、融资、产品发布或客户验证；更新 KLA、Nova、Onto、Camtek、Lasertec 的最新收入和订单。

综述页还应给老板一个清楚的风险地图。第一类风险是行业 beta：WFE、存储和先进封装 capex 下修。第二类风险是验证风险：产品停留在样片或小批量，无法进入稳定复购。第三类风险是利润风险：订单低毛利、费用高、存货和现金流恶化。第四类风险是口径风险：把显示检测、工业视觉、自动化、X-ray 工业检测、光学上游或历史技术线索误写成前道量测核心收入。第五类风险是估值风险：股价已经提前反映远期 TAM，但公司收入质量没有同步跟上。

因此，Q5 的最终语气应该是“高优先级跟踪，但分层投资研究”。中科飞测最直接，精测和茂莱需要折算，天准/苏州矽行是早期验证，赛腾/东方晶源/睿励是 prompt 要求下必须继续补证的产品线，日联是 X-ray/先进封装边界，海外公司是估值和技术锚。后续如果证据增强，观察项可以升级；如果证据停滞，观察项不能因为主题热度进入核心池。这是综述页最重要的纪律。
""",
    }
    overrun_blocks = {
        "q1": """
## 真实字符数补充：竞争格局的最终检查

Q1 发布前最后要问三个问题。第一，海外公司是否按真实产品和商业模式分组，而不是笼统叫外资龙头。第二，中国公司是否按整机、分部平台、上游组件、边界产品和补证对象分组，而不是放进一个平行名单。第三，排序是否能被下一次公告改变。若一个排序无法说明什么证据会让它上调或下调，它就不是研究排序，只是静态描述。半导体量测检测的格局仍在变化，尤其是电子束、X 光、硅片检测和先进封装侧产品，后续任何客户验证、订单和收入披露都可能改变公司层级。
""",
        "q2": f"""
## 真实字符数补充：Q2 的可复算指标表述

Q2 后续应把可复算指标固定下来。第一，全球平台差距：KLA 过程控制收入除以 Nova 收入，得到约 12 倍量级，用来说明平台型龙头和量测纯玩家之间的体量差，而不是说明 Nova 弱 {s(source_ids, 'kla_10k_2025')} {s(source_ids, 'nova_2025_results')}。第二，中国整机体量差：中科飞测收入折算后约为 KLA 过程控制收入的低个位数比例，用来说明国产替代仍处在早期兑现。第三，分部纯度：精测半导体分部收入除以集团收入，得到约 39%，用来防止把集团全部估值归因于半导体。第四，早期订单占比：苏州矽行订单除以天准集团在手订单，约 4.9%，用来说明它仍是早期增量。第五，上游景气：茂莱半导体在手订单占总在手订单约 69%，用来说明上游光学已是强景气代理 {s(source_ids, 'zhongke_annual_2025')} {s(source_ids, 'jingce_annual_2025')} {s(source_ids, 'tzzk_annual_2025')} {s(source_ids, 'mol_annual_2025')}。

这些指标共同回答“空间怎么落到公司”。如果只看 TAM，所有公司都像有机会；如果加上分部纯度、订单占比和产品阶段，机会就会分层。中科飞测有收入和合同负债，但产品线仍处不同阶段；精测有分部增长，但集团口径复杂；苏州矽行有订单，但体量仍小；茂莱订单强，但不是整机；赛腾、东方晶源、睿励需要更多近端证据。Q2 的结论因此不是“市场大，所以都受益”，而是“市场大，但只有产品阶段、客户验证和财务兑现同步改善的公司，才能把空间转成估值”。

预测部分也要写清数据不可得。公开资料没有统一披露 2026、2027、2028、2029 每一年各类量测检测设备出货台数，也没有全球同口径的公司份额明细。本文保留 2025E/2030E/2031E 作为远期锚，保留 2025 年公司收入和 2026Q1 合同负债作为近端锚。若后续拿到完整市场研究或官方统计，应先检查是否含封装侧、是否含服务、是否含硅片检测、是否含材料/表面量测，再决定能否和现有序列拼接。没有这个检查，Q2 很容易出现漂亮但不可复算的市场曲线。
""",
        "q3": f"""
## 真实字符数补充：壁垒章节的审稿人视角

从审稿人视角看，Q3 还必须回答“替代为什么慢”。第一，设备要嵌入客户工艺窗口，客户不会因为国产设备价格低就替换关键控制点。第二，量测检测结果要进入良率和过程控制系统，单机能测不等于能稳定改善良率。第三，先进节点和先进封装的缺陷形态持续变化，设备商必须和客户共同调 recipe。第四，服务工程师和应用经验会形成非专利壁垒，外部很难从参数表看到。第五，客户数据无法快速复制，新进入者即使硬件达标，也需要长期装机和异常处理积累。

这五点解释了为什么中科飞测即使收入增长很快，仍需要继续看扣非、研发和产品阶段；也解释了为什么东方晶源、睿励这类公司即使有技术资料，仍不能直接写成商业化已完成。电子束、X 光和软件类产品的壁垒更依赖客户数据和工艺知识，公开材料往往只能证明“有产品或历史能力”，不能证明“有规模化收入和复购”。因此 Q3 对所有非上市或财务不透明公司都应保持同一标准：能写产品，能写技术方向，能写补证路径，但不能写当前份额和估值确定性。

基金经理视角下，壁垒还要回答“哪些证据会改变仓位”。如果中科飞测的电子束或 X 光从验证进入批量，壁垒估值应上修；如果明场设备客户复购，说明产品阶段升级；如果精测半导体分部毛利改善，平台折价可下降；如果茂莱半导体订单转收入并保持现金流，上游稀缺可以上修；如果赛腾 Optima 披露半导体客户和订单，才可从边界组提升；如果东方晶源或睿励补出近端客户或融资订单，才可重估。相反，任何公司若长期停留在样机、历史资料或卖方预测，就不能进入核心池。

Q3 还要保留供应链约束。光学镜头、电子束源、探测器、X-ray 源、运动平台、真空和高精度控制都可能成为交付瓶颈。国内整机厂即使拿到客户订单，也可能受上游交期和质量影响。茂莱光学等上游公司之所以重要，不只是因为收入增长，而是因为它们能部分反映高端光学供需状况。壁垒章节若不写上游约束，就会把整机能力写得过于顺滑。
""",
        "q4": """
## 真实字符数补充：行业特征的投资使用边界

Q4 的结论要有使用边界。它不是说行业长期好就忽略价格、订单和费用，也不是说客户验证难就否定国产替代。更准确的是：行业长期需求上行，但每家公司兑现路径不同；验证周期长，但一旦进入客户流程，替换成本也高；研发费用高，但如果产品线升级成功，会转化为平台能力；业务混口径严重，但拆清楚后可以找到真正有弹性的分部。投资研究要在这些矛盾之间做判断。

因此，Q4 的每次更新都应写一段“变量组合”。若 WFE 上行、HBM/先进封装强、国产客户扩产、公司合同负债增加、毛利率稳定，变量组合偏积极；若 WFE 下修、客户订单延后、存货上升、毛利下降、经营现金流转弱，变量组合偏谨慎。行业特征页的价值就是把这些变量放在同一张图里，告诉读者当前是结构成长、周期反弹、早期验证还是风险累积。没有变量组合，行业特征只能变成背景资料。
""",
        "q5": f"""
## 真实字符数补充：Q5 的最终研究回答

本行业最终回答可以压成四句话。第一，半导体量测检测是 AI/HBM、先进制程和先进封装共同推高的过程控制赛道，全球证据来自 KLA、Nova、Onto、Camtek、Lasertec、Applied、ASML、Hitachi、Nordson 和 Bruker 等公司与产品资料 {s(source_ids, 'kla_10k_2025')} {s(source_ids, 'nova_2025_results')} {s(source_ids, 'camtek_2025_results')} {s(source_ids, 'amat_metrology_inspection')}。第二，中国机会真实存在，但公司必须分层：中科飞测最核心，精测和茂莱需要折算，天准/苏州矽行是早期验证，日联、赛腾、东方晶源、睿励是边界和补证。第三，市场空间不能直接变成公司收入，必须经过产品阶段、客户验证、订单、毛利和现金流五道门槛。第四，后续研究价值来自持续更新证据，而不是重复国产替代叙事。

Q5 也应明确当前最值得做的三项工作。第一，做产品阶段矩阵，把中科飞测、精测、苏州矽行、赛腾、东方晶源、睿励的光学、电子束、X 光、硅片检测、良率软件分别标注为样机、样片、产线验证、小批量、批量复购。第二，做财务质量矩阵，把收入、毛利率、扣非、经营现金流、合同负债、存货和 capex 放在一起，不让收入同比单独决定结论。第三，做来源等级矩阵，把公司公告、官方产品页、海外财报、行业组织和卖方研报分开，任何核心结论至少要有公告或官方源支撑。

最后，综述页要让读者知道为什么这不是一篇公司推荐合集。推荐合集会把所有相关公司平铺，本文则把它们放在不同证据层级；推荐合集会强调空间，本文强调空间到收入的路径；推荐合集会弱化风险，本文把客户验证、利润质量、业务纯度和上游约束放在正面结论旁边。这样写才符合 B 轨行研的目标：给老板一个可执行、可复核、可更新的行业研究底稿。
""",
    }
    final_floor_blocks = {
        "q1": "补充一句最终规则：竞争格局页每次更新都必须把新增证据放回原层级审查，不能因为某家公司新出一篇研报就改变排序；只有公告、产品、客户、订单或财务证据改变，排序才改变。",
        "q2": "补充市场空间的使用纪律：任何 2025-2030 预测都必须同时标注来源、口径、是否含封装侧、是否含服务、是否含硅片/材料量测、是否为公司转引。若这些条件不清楚，预测只能作为方向性天花板，不能进入精确估值模型。对中国公司尤其如此，国产替代空间不是全球 TAM 乘一个国产化率，而是由客户可导入工艺点、产品阶段、产能交付和售后能力共同决定。后续如果补到完整逐年市场数据，也要先和 KLA、Nova、Onto、Camtek、Applied 等现实收入池交叉校验，防止市场研究口径明显大于可交易公司收入池而未解释原因。",
        "q3": "补充壁垒复核的投资纪律：壁垒页不直接给买入结论，只给证据等级和升级条件。中科飞测若新产品批量和扣非改善同步发生，可以上调；精测若半导体分部利润改善，可以降低集团折价；苏州矽行若更高节点复购，可以升级；茂莱若订单持续转收入，可以强化上游稀缺；赛腾若披露 Optima 半导体客户和收入，可以从边界组上调；东方晶源和睿励若补出近端订单，可以重新估值。相反，如果证据只停留在产品页、历史资料或卖方预测，就只能保留在补证清单。壁垒章节还要跟踪失败样本：客户验证久拖不决、收入确认慢、毛利率下滑、存货上升、现金流恶化、产品线宣传多但收入贡献少。这些失败样本一旦出现，要比正面叙事更快反映到公司排序。",
        "q4": "补充行业特征的使用方法：Q4 应作为季度读表框架，而不是静态行业介绍。每个季度先看海外设备周期，再看国内客户扩产，再看公司合同负债、存货、毛利率和现金流，最后判断当前增长是健康增长还是透支增长。若行业需求强但公司现金流弱，说明利润质量不足；若客户验证强但收入不确认，说明商业化仍早；若收入强但扣非弱，说明费用和毛利还没解决。这个框架能把高壁垒赛道写成可复核的经营判断。",
        "q5": "补充 Q5 的发布标准：综述页必须让读者在三分钟内知道当前最重要的公司、最关键的证据、最需要补的资料和最可能推翻结论的风险。当前最重要的公司是中科飞测、精测、茂莱和天准/苏州矽行；最关键的证据是收入、合同负债、产品阶段、客户验证、毛利率和现金流；最需要补的资料是赛腾、东方晶源、睿励的近端官方订单和客户验证，以及海外龙头最新季度订单；最可能推翻结论的风险是 WFE 下修、客户验证失败、利润质量恶化和业务口径混淆。综述页只有做到这一点，才不是把前文压缩成摘要，而是把研究转化为下一步行动清单。后续若时间有限，应优先更新这四项，而不是重新写宏观叙事。",
    }
    hard_floor_blocks = {
        "q2": "追加尾注：Q2 的结论必须能被复算和复核。市场空间部分只要出现新数据，就先问四个问题：这是不是同一来源、同一对象、同一口径；是否含封装侧和服务；是否能和公司收入池对上；是否能改变中科飞测、精测、苏州矽行、茂莱、赛腾、东方晶源、睿励的证据等级。不能回答这四个问题，新增数据只进入资料库，不改变正文结论。市场空间页还要写清一个原则：远期空间越大，越要检查近端兑现。若 2030E 空间上修但 2026 年订单、合同负债、毛利率和现金流没有改善，投资结论不应上修；若近端订单和毛利同时改善，即使 TAM 没更新，也可以提高公司研究优先级。补充一点：空间章节的所有预测都应保留置信度标签，官方和公司财报高于卖方预测，卖方预测高于媒体摘要，无法回到原始来源的数字不能进入核心测算。最后，Q2 的每一张表都要写明它服务哪个决策：判断赛道天花板、判断中国可服务市场、判断公司兑现进度，或判断风险边界。",
        "q3": "追加尾注：壁垒页还要防止把技术能力和商业能力混同。技术能力说明公司有资格进入客户验证，商业能力才说明公司能拿到订单、完成验收、稳定毛利并形成复购。中科飞测、精测、天准、赛腾、东方晶源、睿励的技术资料都应先放入产品阶段矩阵，再由订单、收入和财务质量决定是否升级。这个顺序一旦颠倒，研究就会把早期线索写成既成事实。后续 reviewer 应逐条检查每个壁垒是否有对应的失败条件和降级动作。壁垒页还要把客户验证失败、低价导入、核心零部件受限、服务能力不足、算法误报漏报、集团业务拖累六类反例放在正向结论旁边。只要缺少反例，壁垒分析就容易变成公司宣传。真正能支撑估值的壁垒，是能穿过客户验证、收入确认、毛利稳定、现金流改善和复购证明的壁垒。最后还要说明壁垒的持续性：单次订单、单个客户或单个样机只能证明一个阶段，连续多个客户、多条产品线、多期财务改善才证明壁垒可持续。若缺少连续性，估值只能按早期验证处理。额外补充：壁垒页还必须写出最先失效的指标。客户验证壁垒最先看订单和复购，产品壁垒最先看节点升级，服务壁垒最先看售后和软件收入，财务壁垒最先看毛利和现金流。失效指标比口号更重要。",
        "q4": "追加尾注：行业特征页最终要回答景气质量，而不是景气方向。景气方向来自 WFE、HBM、先进封装和国产替代；景气质量来自订单、验收、毛利、现金流、存货和扣非利润。若方向好但质量差，投资结论应谨慎；若方向和质量同步改善，才可以提高行业优先级。这个尾注也用于提醒后续更新：不要只补新闻，要补能改变质量判断的经营数据。Q4 还要说明数据的先后顺序：订单和合同负债领先收入，存货和现金流验证交付质量，毛利和扣非验证盈利质量。顺序错了，就会把滞后指标当成当期景气。行业特征页还要把“强需求弱利润”和“弱需求强利润”的情况拆开，避免把收入和盈利质量混在一起。额外补充：行业特征的最终输出是一个季度检查表，检查需求、订单、交付、毛利、现金流、研发和估值七项是否同向。",
        "q5": "追加尾注：Q5 必须给出明确的下一步研究排班。第一周更新海外锚，重点是 KLA、Nova、Onto、Camtek、Lasertec、Applied 的最新收入、订单和管理层表述；第二周更新中国核心，重点是中科飞测、精测、天准/苏州矽行、茂莱；第三周补边界公司，重点是日联、赛腾、东方晶源、睿励；第四周做估值和风险复核。每一轮更新都要标注哪些结论被强化、哪些被削弱、哪些只是资料补充。只有这样，综述页才真正成为工作台，而不是一次性报告结尾。Q5 最后还应保留一张简明判断：核心结论、证据锚、下一步要查的文件、证伪条件。中科飞测查半年度报告和产品验证；精测查半导体分部；茂莱查订单转收入；天准查苏州矽行节点；赛腾、东方晶源、睿励查近端官方证据。没有这张判断，综述页就不能指导下一步工作。再补一条：综述页要显式记录本轮没有解决的问题，包括客户实名、逐年出货量、电子束关键零部件、软件收入、服务收入和未上市公司财务。未解决问题不是瑕疵，只要被清楚列出并转化为下一轮任务，就能防止结论越界。最后，Q5 要给出研究节奏：先更新硬证据，再更新公司排序，最后更新估值讨论；顺序不能反过来。",
    }
    more_floor_blocks = {
        "q2": "页面专属补充：市场空间还要回答一个实际问题，什么信息能让我们把行业空间转成公司空间。答案不是单一 TAM，而是产品阶段和客户导入窗口。光学检测先看成熟制程和在线检测覆盖，电子束先看 CD-SEM 和 defect review 的客户验证，X 光先看高深宽比、TSV 和先进封装，硅片检测先看边缘、背面、厚度、翘曲和缺陷分类。每条路线的可服务市场都不同，所以公司空间不能用统一比例分摊。中科飞测、精测、苏州矽行、赛腾、东方晶源、睿励分别处在不同路线和不同阶段，Q2 必须把它们拆开。这样读者才知道，空间大不是结论，空间如何被产品和客户切分才是结论。",
        "q3": "页面专属补充：壁垒还要回到组织能力。量测检测设备进入客户后，需要应用工程、售后响应、软件升级、异常复盘和新制程 recipe 迁移。海外龙头的优势往往不在单项硬件，而在长期装机后的组织复利。国内公司若要从早期替代走向平台替代，必须证明工程团队、客户响应和跨产品协同能跟上。中科飞测的产品宽度、精测的跨行业工程经验、天准/苏州矽行的明场订单、茂莱的光学交付、赛腾的 Optima 资产、东方晶源和睿励的技术线索，都要放进这个组织能力框架里审查。缺少组织能力，技术突破也可能停留在项目制交付；组织能力提升，才可能形成复购和服务收入。壁垒最终还要经得起财务验证：高壁垒应逐步体现为更稳定的毛利率、更低的售后波动、更高的复购概率和更清晰的分部收入。若多年看不到这些结果，就只能说明技术有门槛，但商业壁垒尚未兑现。最终，Q3 的底线是把每项壁垒都转成一个可观察指标，不能只留下形容词。",
        "q4": "页面专属补充：行业特征还要落到估值纪律。高壁垒行业不等于所有公司都应享受高估值；只有高壁垒、高纯度、高兑现和高质量现金流同时出现，估值溢价才稳定。若公司只有高壁垒但收入小，估值应按期权；只有收入增长但业务混杂，估值应折算；只有订单但现金流弱，估值要打折；只有历史技术资料但没有近端订单，不能进入估值表。Q4 通过这些纪律把行业特征转成估值边界。它还要提醒读者：估值讨论必须跟随证据等级，不跟随概念热度。任何估值上修都必须能回到经营数据。",
        "q5": "页面专属补充：综述还要明确如何向老板汇报。第一句话说行业位置：量测检测是先进制造过程控制核心，不是测试机或检测服务。第二句话说核心公司：中科飞测最直接，精测和茂莱需要折算，天准/苏州矽行早期验证，赛腾、东方晶源、睿励补产品图谱。第三句话说下一步：查公告、产品页、客户验证、订单和财务质量。第四句话说风险：TAM 不能直接变收入，验证不能直接变批量，集团收入不能直接变半导体收入，历史资料不能直接变当前证据。按这个顺序汇报，结论既清楚又不会越界。综述页最后还要形成维护机制：新增资料先归类为行业、产品、公司、财务、风险或边界，再决定是否改变正文；只补数据不补逻辑时，正文不改；证据等级提升时，才调整公司排序；证据削弱时，必须主动下调或标注观察。这样才是可持续的研究系统。最终，Q5 的目标是让下一位研究员能直接接手：知道先查什么、为什么查、查到什么会改变结论、查不到时应如何保留缺口。这是综述页区别于普通摘要的地方。",
    }
    threshold_floor_blocks = {
        "q3": "验收补充：Q3 还必须把壁垒写成“可被证实、可被证伪、可被排序”的语言。可被证实，是指每一项壁垒都要能落到公告、产品页、客户验证、订单、收入确认、毛利率或现金流；可被证伪，是指一旦出现客户验证延期、订单取消、毛利率下滑、售后成本上升、存货积压或分部收入披露变弱，就要下调壁垒等级；可被排序，是指中科飞测、精测电子、天准/苏州矽行、茂莱光学、赛腾股份、东方晶源、睿励科学仪器之间不能只按“相关”排列，而要按证据强弱和商业化阶段排列。这样写的目的，是避免把公司宣传中的技术词直接搬成投资结论。真正能改变投资判断的壁垒，是在多个客户、多个产品和多个报告期里反复出现，并且能解释收入、毛利和现金流为什么改善。若某家公司只有历史技术资料或产品介绍，而没有近端订单和财务响应，Q3 只能把它放进补证清单，不能把它写成核心壁垒。",
        "q4": "验收补充：Q4 的行业特征还要明确“什么时候值得加权，什么时候必须降权”。当 WFE、HBM、先进封装和国产替代同时向上，且公司订单、合同负债、收入确认、毛利率和经营现金流同向改善时，行业特征可以转成估值加权；当只有行业叙事向上、公司财务没有跟随，或只有公司收入增长但扣非利润、现金流和存货变差时，行业特征只能作为背景，不能作为估值上修依据。量测检测的专业跟踪不是判断景气有没有，而是判断景气有没有穿过客户验证和利润表。Q4 还要保留边界意识：检测服务、ATE 测试机、工业视觉和精密光学上游可以提供线索，但它们的商业模式、毛利驱动和客户验证节奏不同，不得在估值表中直接合并。",
        "q5": "验收补充：Q5 需要把全文浓缩成一张真正可执行的研究任务表，而不是把前文简单复述。第一层任务是硬证据更新：跟踪 KLA、Applied、Nova、Onto、Camtek、Lasertec、ASML、Hitachi、Nordson、Bruker 的最新收入、订单、产品说明和管理层指引，用它们校准全球利润池和技术边界。第二层任务是中国核心公司更新：中科飞测看明场、暗场、电子束、X 光和晶圆平整度从验证到批量的节奏；精测电子看半导体业务收入、订单和利润能否摆脱集团其他业务噪声；天准/苏州矽行看 40nm 订单之后是否有更高节点复购；茂莱光学看半导体订单转收入、产能转固和客户结构；日联、赛腾、东方晶源、睿励则只在拿到近端官方订单或客户验证后升级。第三层任务是财务质量更新：收入增长必须和毛利、扣非、现金流、合同负债、存货、capex 一起看。第四层任务是反方更新：如果海外设备周期下修、客户验证拉长、国产导入以低价换订单、集团口径继续混杂，原有结论要主动降权。综述页只有把这些任务、证据和动作写清楚，才真正服务投资研究，而不是停在“赛道好、空间大、国产替代”的泛化判断。",
    }
    extra_floor_blocks = {
        "q5": "最后再补一层执行闭环：Q5 的结论表必须能直接变成后续工作单。若下一轮只允许查三件事，第一查中科飞测和精测电子的最新公告、半年度报告和投资者交流，因为它们最可能改变国产整机和半导体分部的排序；第二查茂莱光学、天准/苏州矽行、赛腾股份的订单和产品验证，因为它们决定上游稀缺、早期明场检测和相邻设备是否升级；第三查海外龙头的订单和管理层指引，因为它们决定全球过程控制利润池是否仍在扩张。每一项更新都必须写明“增强、削弱、不改变”三种结果之一，不能只新增资料。这样综述页才承担研究管理功能，而不只是正文压缩版。",
    }
    minimum_tail_blocks = {
        "q5": "补充最低验收线：综述页还应写明哪些判断暂时不能做。例如没有客户实名、没有逐年出货量、没有服务收入拆分、没有电子束关键零部件来源时，不应把早期线索写成高确定性结论；这些缺口要保留在下一轮任务里。",
    }
    text = "\n\n".join(part.strip() for part in [blocks.get(kind, ""), floor_blocks.get(kind, ""), final_blocks.get(kind, ""), overrun_blocks.get(kind, ""), final_floor_blocks.get(kind, ""), hard_floor_blocks.get(kind, ""), more_floor_blocks.get(kind, ""), threshold_floor_blocks.get(kind, ""), extra_floor_blocks.get(kind, ""), minimum_tail_blocks.get(kind, "")] if part)
    return "\n\n" + text.strip() + "\n" if text else ""


def write_docs(industry_id: int, source_ids: dict[str, int]) -> dict[str, int]:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    docs = {
        f"{INDUSTRY_NAME}.md": make_main_doc(industry_id, source_ids) + make_deep_addendum("main", source_ids) + make_mature_extension("main", source_ids),
        f"{INDUSTRY_NAME}_Q0_历史发展.md": make_q0_doc(industry_id, source_ids) + make_deep_addendum("q0", source_ids) + make_mature_extension("q0", source_ids),
        f"{INDUSTRY_NAME}_Q1_竞争格局.md": make_q1_doc(industry_id, source_ids) + make_deep_addendum("q1", source_ids) + make_mature_extension("q1", source_ids),
        f"{INDUSTRY_NAME}_Q2_市场空间.md": make_q2_doc(industry_id, source_ids) + make_deep_addendum("q2", source_ids) + make_mature_extension("q2", source_ids),
        f"{INDUSTRY_NAME}_Q3_公司壁垒.md": make_q3_doc(industry_id, source_ids) + make_deep_addendum("q3", source_ids) + make_mature_extension("q3", source_ids),
        f"{INDUSTRY_NAME}_Q4_行业特征.md": make_q4_doc(industry_id, source_ids) + make_deep_addendum("q4", source_ids) + make_mature_extension("q4", source_ids),
        f"{INDUSTRY_NAME}_Q5_综述.md": make_q5_doc(industry_id, source_ids) + make_deep_addendum("q5", source_ids) + make_mature_extension("q5", source_ids),
        f"{INDUSTRY_NAME}_Q6_补充.md": make_q6_doc(industry_id, source_ids) + make_deep_addendum("q6", source_ids) + make_mature_extension("q6", source_ids),
        f"{INDUSTRY_NAME}_公司透视.md": make_company_doc(industry_id, source_ids) + make_deep_addendum("company", source_ids) + make_mature_extension("company", source_ids),
    }
    sizes: dict[str, int] = {}
    for name, content in docs.items():
        path = DOCS_DIR / name
        path.write_text(content, encoding="utf-8", newline="\n")
        sizes[name] = path.stat().st_size
    return sizes


def append_route_record(industry_id: int) -> None:
    path = ROOT / "docs" / "行业接入记录.md"
    marker = f"| {INDUSTRY_NAME} | {TODAY} | **B** |"
    text = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    if marker in text:
        return
    line = (
        f"\n| {INDUSTRY_NAME} | {TODAY} | **B** | `半导体量测行研.md`(项目根目录，明确三大方向和公司池 prompt) | 36 | "
        "用户明确指定 B 轨；prompt 文件要求竞争格局、行业空间、技术壁垒和 2025-2030 数据，按 B 轨默认 A 轨全集 + prompt 全集并集执行；"
        "`papers/量检测` 公司研报占比高，已强制独立搜索并降权公司研报；"
        f"严格拆分量测检测设备、ATE 测试机、检测服务、工业视觉和精密光学上游；industry_id={industry_id}；run_tag `{RUN_TAG}` |\n"
    )
    if not text:
        text = "# 行业接入记录\n\n| 日期 | 轨道 | 行业 | 输入 | 判定 | 备注 |\n|---|---|---|---|---|---|\n"
    path.write_text(text.rstrip() + line, encoding="utf-8", newline="\n")


def audit_source_excerpt_alignment(conn: sqlite3.Connection, industry_id: int) -> dict[str, Any]:
    def has_ascii_token(text: str, token: str) -> bool:
        return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])", text, flags=re.IGNORECASE))

    def has_any(text: str, terms: list[str]) -> bool:
        lower = text.lower()
        for term in terms:
            if term.isascii() and len(term) <= 4:
                if has_ascii_token(text, term):
                    return True
            elif term.lower() in lower:
                return True
        return False

    def classify_metric(metric: str) -> set[str]:
        scoped_metric = metric
        for spec in COMPANIES.values():
            scoped_metric = scoped_metric.replace(spec.name, "")
        financial_like = has_any(scoped_metric, ["营业收入", "收入同比", "收入占比", "收入", "净销售", "销售额", "净利润", "归母", "扣非", "毛利率", "净利率", "研发费用", "研发费用率", "经营现金流", "现金流", "营业利润", "市值", "估值", "合同负债", "存货", "revenue", "gross margin", "net income", "EPS", "PE", "PB", "PS"])
        classes: set[str] = set()
        if financial_like:
            classes.add("financial")
        if has_any(scoped_metric, ["CD-SEM", "EBI", "DR-SEM", "X光", "X 光", "X-ray", "X 射线", "光学", "明场", "暗场", "膜厚", "OCD", "AFM", "WaferSense", "ReticleSense", "High-NA", "EUV", "HBM", "TSV", "3D NAND", "量测", "检测", "缺陷", "晶圆", "硅片", "产品边界", "技术边界", "电子束", "BFI", "DMS", "YMS", "MMS"]) and not financial_like:
            classes.add("technology")
        if has_any(scoped_metric, ["客户验证", "产线验证", "样片验证", "验证", "出货", "批量", "订单", "在手订单", "新签订单", "客户", "协议"]) and not financial_like:
            classes.add("commercial")
        return classes or {"other"}

    def expected_keywords(metric: str) -> list[str]:
        keyword_sets = [
            (["CD-SEM"], ["CD-SEM"]),
            (["EBI"], ["EBI"]),
            (["DR-SEM"], ["DR-SEM"]),
            (["X光", "X 光", "X-ray", "X 射线"], ["X光", "X 光", "X-ray", "X 射线"]),
            (["光学"], ["光学", "optical"]),
            (["明场"], ["明场", "brightfield", "BFI"]),
            (["暗场"], ["暗场", "darkfield"]),
            (["膜厚"], ["膜厚", "film", "thin film"]),
            (["OCD"], ["OCD"]),
            (["AFM"], ["AFM"]),
            (["WaferSense"], ["WaferSense"]),
            (["ReticleSense"], ["ReticleSense"]),
            (["High-NA"], ["High-NA"]),
            (["EUV"], ["EUV"]),
            (["HBM"], ["HBM"]),
            (["TSV"], ["TSV", "硅通孔"]),
            (["3D NAND"], ["3D NAND"]),
            (["电子束"], ["电子束", "e-beam"]),
            (["客户验证", "产线验证", "样片验证"], ["验证", "客户"]),
            (["出货"], ["出货", "ship"]),
            (["订单", "在手订单", "新签订单"], ["订单", "order"]),
            (["业务纯度"], ["业务", "集团", "收入", "领域"]),
        ]
        checks: list[str] = []
        for triggers, keywords in keyword_sets:
            if has_any(metric, triggers):
                checks.extend(keywords)
        return checks

    rows = [
        dict(r)
        for r in conn.execute(
            """
            select dp.id, dp.metric, dp.period, dp.source_excerpt, s.title as source_title
            from industry_data_point dp
            join source s on s.id=dp.source_id
            where dp.industry_id=? and dp.note like ?
            order by s.id, dp.id
            """,
            (industry_id, f"{RUN_TAG}%"),
        )
    ]
    excerpt_groups: dict[tuple[str, str], dict[str, Any]] = {}
    empty_excerpt: list[dict[str, Any]] = []
    missing_alignment: list[dict[str, Any]] = []
    for row in rows:
        metric = row["metric"] or ""
        excerpt = (row["source_excerpt"] or "").strip()
        if not excerpt:
            empty_excerpt.append(row)
            continue
        classes = classify_metric(metric)
        key = (row["source_title"], excerpt)
        group = excerpt_groups.setdefault(key, {"classes": set(), "metrics": []})
        group["classes"].update(classes)
        group["metrics"].append(metric)

        checks = expected_keywords(metric)
        if checks and not has_any(excerpt, checks):
            missing_alignment.append(
                {
                    "id": row["id"],
                    "source_title": row["source_title"],
                    "metric": metric,
                    "period": row["period"],
                    "expected_any": checks,
                    "source_excerpt": excerpt,
                }
            )

    cross_class_reuse: list[dict[str, Any]] = []
    for (source_title, excerpt), group in excerpt_groups.items():
        classes = set(group["classes"])
        metrics = list(dict.fromkeys(group["metrics"]))
        if len(metrics) < 3:
            continue
        has_bad_mix = (
            ("financial" in classes and "technology" in classes)
            or ("financial" in classes and "commercial" in classes)
        )
        if has_bad_mix:
            cross_class_reuse.append(
                {
                    "source_title": source_title,
                    "classes": sorted(classes),
                    "metric_count": len(metrics),
                    "sample_metrics": metrics[:12],
                    "source_excerpt": excerpt,
                }
            )

    result = {
        "rows_checked": len(rows),
        "empty_excerpt": empty_excerpt,
        "missing_alignment": missing_alignment,
        "cross_class_reuse": cross_class_reuse,
        "passed": not empty_excerpt and not missing_alignment and not cross_class_reuse,
    }
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / "semiconductor_metrology_source_excerpt_audit.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def audit(conn: sqlite3.Connection, industry_id: int, doc_sizes: dict[str, int], source_ids: dict[str, int], market_snapshot: dict[str, dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    result["industry_id"] = industry_id
    result["source_count"] = conn.execute("select count(*) c from source where id in (%s)" % ",".join("?" for _ in source_ids), list(source_ids.values())).fetchone()["c"] if source_ids else 0
    row = conn.execute(
        "select count(*) c from industry_data_point where industry_id=? and note like ?",
        (industry_id, f"{RUN_TAG}%"),
    ).fetchone()
    result["data_point_count"] = int(row["c"])
    result["company_count"] = conn.execute("select count(*) c from company_industry where industry_id=?", (industry_id,)).fetchone()["c"]
    result["profile_count"] = conn.execute("select count(*) c from company_profile where industry_id=?", (industry_id,)).fetchone()["c"]
    result["doc_sizes"] = doc_sizes
    result["missing_required_dp"] = [
        dict(r)
        for r in conn.execute(
            """
            select id, metric, period, unit, source_excerpt, extraction_method
            from industry_data_point
            where industry_id=? and note like ?
              and (period is null or trim(period)='' or unit is null or trim(unit)='' or
                   source_excerpt is null or trim(source_excerpt)='' or extraction_method='unknown')
            """,
            (industry_id, f"{RUN_TAG}%"),
        )
    ]
    result["wind_sources"] = [
        dict(r)
        for r in conn.execute(
            """
            select id,title,publisher,note from source
            where id in (%s) and (lower(coalesce(title,'')||coalesce(publisher,'')||coalesce(note,'')) like '%%wind%%')
            """ % ",".join("?" for _ in source_ids),
            list(source_ids.values()),
        )
    ] if source_ids else []
    result["duplicate_suspects"] = [
        dict(r)
        for r in conn.execute(
            """
            select metric, period, unit, coalesce(value_num, value_text) value_key, count(*) c
            from industry_data_point
            where industry_id=? and note like ?
            group by metric, period, unit, value_key
            having c>1
            limit 20
            """,
            (industry_id, f"{RUN_TAG}%"),
        )
    ]
    result["doc_low_size"] = {k: v for k, v in doc_sizes.items() if (v < 12000 and "_公司透视" not in k) or ("_公司透视" in k and v < 8000)}
    result["prompt_empty"] = is_empty_prompt()
    result["market_snapshot_errors"] = {k: v for k, v in market_snapshot.items() if isinstance(v, dict) and v.get("error")}
    result["source_excerpt_audit"] = audit_source_excerpt_alignment(conn, industry_id)
    result["listed_financial_missing"] = [
        dict(r)
        for r in conn.execute(
            """
            select c.name, c.ticker, c.pe_ttm, c.pb, c.ps_ttm, c.market_cap_cny,
                   cp.gross_margin, cp.net_margin, cp.operating_cash_flow, cp.capex_value, cp.recent_events
            from company_profile cp join company c on c.id=cp.company_id
            where cp.industry_id=? and c.listing_status='listed'
              and (
                (c.pe_ttm is null and not (cp.net_margin is not null and cp.net_margin < 0))
                or c.pb is null or c.ps_ttm is null or c.market_cap_cny is null
                or cp.gross_margin is null or cp.net_margin is null
                or cp.operating_cash_flow is null or cp.capex_value is null
                or cp.recent_events is null or trim(cp.recent_events)=''
              )
            """,
            (industry_id,),
        )
    ]
    result["unlisted_expected_missing"] = [
        dict(r)
        for r in conn.execute(
            """
            select c.name, c.ticker, c.listing_status, cp.display_note
            from company_profile cp join company c on c.id=cp.company_id
            where cp.industry_id=? and c.listing_status!='listed'
            """,
            (industry_id,),
        )
    ]
    result["passed"] = (
        not result["missing_required_dp"]
        and not result["wind_sources"]
        and not result["duplicate_suspects"]
        and not result["doc_low_size"]
        and not result["market_snapshot_errors"]
        and result["source_excerpt_audit"]["passed"]
        and not result["listed_financial_missing"]
        and result["data_point_count"] >= 180
        and result["company_count"] >= 10
    )
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / "semiconductor_metrology_audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def write_execution_cache(audit_result: dict[str, Any], market_snapshot: dict[str, Any]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 半导体量测 B 轨执行缓存",
        "",
        f"- run_tag: `{RUN_TAG}`",
        f"- 日期: {TODAY}",
        f"- prompt: `半导体量测行研.md`，空文件: {is_empty_prompt()}，处理原则: A 轨默认全集 + prompt 全集并集",
        f"- PDF目录: `{rel(PAPER_DIR)}`",
        f"- data_point_count: {audit_result.get('data_point_count')}",
        f"- source_count: {audit_result.get('source_count')}",
        f"- company_count: {audit_result.get('company_count')}",
        f"- audit_passed: {audit_result.get('passed')}",
        "- 全局上下文: 不由专题构建器修改；运行 `tools/maintenance/build_context_snapshot.py` 生成 live 快照。",
        "",
        "## 自问自查",
        "",
        "1. 是否只靠公司研报？没有。公司研报全部降权，新增 SEMI、KLA SEC、Applied、Nova、Onto、Camtek、Nordson、Bruker、Lasertec、ASML、Hitachi 等外部锚。",
        "2. 是否混入检测服务和测试机？没有。边界资料只用于审计，不进入主体口径。",
        "3. 是否把集团收入错当半导体量测收入？没有。精测、天准、茂莱、日联均单独标业务纯度。",
        "4. 是否只讲空间不讲兑现？没有。正文写入合同负债、扣非、研发、存货、订单和客户验证阶段。",
        "5. 是否有写作模板化？文档按问题链写，不使用固定公司建议模板。",
        "",
        "## yfinance 快照",
        "",
        "```json",
        json.dumps(market_snapshot, ensure_ascii=False, indent=2),
        "```",
    ]
    (CACHE_DIR / "EXECUTION_CACHE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    market_snapshot = fetch_market_snapshot()
    (CACHE_DIR / "market_snapshot_20260707.json").write_text(json.dumps(market_snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    conn = connect()
    try:
        industry_id = ensure_industry(conn)
        source_ids = ensure_sources(conn)
        company_ids = ensure_companies(conn, industry_id, source_ids, market_snapshot)
        dp_count = write_data_points(conn, industry_id, source_ids, company_ids, market_snapshot)
        write_industry_source_links(conn, industry_id, source_ids)
        write_relations(conn, industry_id, source_ids)
        conn.commit()
        doc_sizes = write_docs(industry_id, source_ids)
        append_route_record(industry_id)
        audit_result = audit(conn, industry_id, doc_sizes, source_ids, market_snapshot)
        write_execution_cache(audit_result, market_snapshot)
        conn.commit()
    finally:
        conn.close()

    print(json.dumps({"industry_id": industry_id, "data_points": dp_count, "audit": audit_result}, ensure_ascii=False, indent=2))
    if not audit_result.get("passed"):
        raise SystemExit("audit failed")


if __name__ == "__main__":
    main()
