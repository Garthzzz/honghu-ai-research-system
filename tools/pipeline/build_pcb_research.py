#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Build the B-track PCB manufacturing research package.

The script intentionally keeps source registration, structured data points,
company profiles, and markdown generation in one reproducible place.  It writes
industry_data_point only through db_writer.write_data_point().
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from textwrap import dedent

from db_writer import write_data_point
from market_snapshot_utils import display_cny_usd, fetch_company_market_snapshot, fetch_fx_rates, unit_cny_usd


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "research.db"
DOCS_DIR = ROOT / "docs" / "industries"
PAPERS_DIR = ROOT / "papers" / "pcb"
CACHE_DIR = ROOT / "cache" / "pcb_research"

TODAY = "2026-07-07"
INDUSTRY_NAME = "PCB制造"
RUN_TAG = "PCB_B_TRACK_20260706"
FX = {
    "USD": 6.7938,
    "TWD": 0.2029,
    "JPY": 0.041817,
    "CNY": 1.0,
}

SOURCE_TYPE_MAP = {
    "prompt": "其他",
    "pdf_report": "三方数据",
    "sellside_report": "卖方深度",
    "annual_report": "公告",
    "api_snapshot": "三方数据",
}


def json_text(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def profile_series_rows(series: dict | None) -> list | None:
    if not isinstance(series, dict):
        return series
    unit = series.get("unit")
    periods = [k for k in series.keys() if k != "unit"]

    def _sort_key(period: str):
        text = str(period)
        digits = "".join(ch for ch in text if ch.isdigit())
        return (int(digits[:4]) if digits else 0, text)

    rows = []
    prev = None
    for period in sorted(periods, key=_sort_key):
        value = series.get(period)
        yoy = None
        if isinstance(value, (int, float)) and isinstance(prev, (int, float)) and prev:
            yoy = (float(value) / float(prev) - 1.0) * 100.0
        rows.append({
            "period": str(period),
            "value": value,
            "unit": unit,
            "yoy": round(yoy, 1) if yoy is not None else None,
        })
        if isinstance(value, (int, float)):
            prev = value
    return rows


def profile_event_rows(text: str | None, source_id: int | None, date: str | None) -> list | None:
    if not text:
        return None
    title = text.split("；", 1)[0].strip()
    return [{
        "date": date or TODAY,
        "title": title[:80],
        "summary": text,
        "is_major": True,
        "source_id": source_id,
    }]


def profile_risk_rows(text: str | None, source_id: int | None) -> list | None:
    if not text:
        return None
    parts = [p.strip() for p in text.replace("；", ";").split(";") if p.strip()]
    return [{"text": p, "source_id": source_id} for p in parts]


SOURCES = {
    "prompt": {
        "title": "PCB制造产业研究数据整理Prompt",
        "publisher": "用户提供",
        "source_type": "prompt",
        "publish_date": TODAY,
        "file_path": "PCB制造产业研究数据整理Prompt.md",
        "quality_tier": 1,
        "note": "B轨研究员prompt，规定PCB裸板制造口径、七栏目输出和公司透视要求。",
        "is_primary_source": 1,
    },
    "prismark": {
        "title": "Prismark 2026 Q1 PCB and Substrate Market Overview and Outlook zh-Hans",
        "publisher": "Prismark Partners LLC",
        "source_type": "pdf_report",
        "publish_date": "2026-03-01",
        "file_path": "papers/pcb/Prismark 2026 Q1 PCB and Substrate Market Overview and Outlook zh-Hans.pdf",
        "quality_tier": 2,
        "note": "PCB与封装基板市场专业数据库/演示，作为市场规模和产品结构核心锚点。",
        "is_primary_source": 0,
    },
    "changjiang_20250804": {
        "title": "20250804-长江证券-机械行业PCB设备：AI需求带动+技术升级，下游资本开支扩张",
        "publisher": "长江证券",
        "source_type": "sellside_report",
        "publish_date": "2025-08-04",
        "file_path": "papers/pcb/20250804-长江证券-机械行业PCB设备：AI需求带动+技术升级，下游资本开支扩张.pdf",
        "quality_tier": 3,
        "note": "转引Prismark，补充2024应用端分布和产品结构说明。",
        "is_primary_source": 0,
    },
    "guangfa_20250901": {
        "title": "20250901-广发证券-AI PCB设备行业深度：PCB技术迭代，国产设备耗材进击正当时",
        "publisher": "广发证券",
        "source_type": "sellside_report",
        "publish_date": "2025-09-01",
        "file_path": "papers/pcb/20250901-广发证券-AI PCB设备行业深度：PCB技术迭代，国产设备耗材进击正当时.pdf",
        "quality_tier": 3,
        "note": "高多层、HDI、中国产地、AI服务器PCB和扩产公告的二级整理。",
        "is_primary_source": 0,
    },
    "xingye_20250811": {
        "title": "20250811-兴业证券-电子行业算力专题4：AIPCB技术迭代，规模高速增长，上游CCL、铜等环节迎量价双升",
        "publisher": "兴业证券",
        "source_type": "sellside_report",
        "publish_date": "2025-08-11",
        "file_path": "papers/pcb/20250811-兴业证券-电子行业算力专题4：AIPCB技术迭代，规模高速增长，上游CCL、铜等环节迎量价双升.pdf",
        "quality_tier": 3,
        "note": "AI服务器板卡架构、HDI/HLC规格、CoWoP和算力PCB需求测算。",
        "is_primary_source": 0,
    },
    "huajin_20250930": {
        "title": "20250930-华金证券-算力系列报告之PCB行业：AI算力硬件迭代催生PCB行业结构性增长机遇",
        "publisher": "华金证券",
        "source_type": "sellside_report",
        "publish_date": "2025-09-30",
        "file_path": "papers/pcb/20250930-华金证券-算力系列报告之PCB行业：AI算力硬件迭代催生PCB行业结构性增长机遇.pdf",
        "quality_tier": 3,
        "note": "公司技术能力、客户认证和高阶产品进展整理。",
        "is_primary_source": 0,
    },
    "caixin_20251225": {
        "title": "20251225-财信证券-元件行业：AI推动PCB产业高端化——材料升级、工艺迭代与产品创新",
        "publisher": "财信证券",
        "source_type": "sellside_report",
        "publish_date": "2025-12-25",
        "file_path": "papers/pcb/20251225-财信证券-元件行业：AI推动PCB产业高端化——材料升级、工艺迭代与产品创新.pdf",
        "quality_tier": 3,
        "note": "PCB产业链公司2025年前三季度经营、资本开支和材料升级。",
        "is_primary_source": 0,
    },
    "guojin_20251101": {
        "title": "20251101-国金证券-电子行业专题研究报告：AI产业链业绩亮眼，继续看好AI_PCB及核心算力硬件",
        "publisher": "国金证券",
        "source_type": "sellside_report",
        "publish_date": "2025-11-01",
        "file_path": "papers/pcb/20251101-国金证券-电子行业专题研究报告：AI产业链业绩亮眼，继续看好AI_PCB及核心算力硬件.pdf",
        "quality_tier": 3,
        "note": "2025年前三季度PCB公司经营情况和AI PCB景气验证。",
        "is_primary_source": 0,
    },
    "shouchuang_20260415": {
        "title": "20260415-首创证券-电子行业深度报告：AI算力浪潮起，PCB迎结构性机遇",
        "publisher": "首创证券",
        "source_type": "sellside_report",
        "publish_date": "2026-04-15",
        "file_path": "papers/pcb/20260415-首创证券-电子行业深度报告：AI算力浪潮起，PCB迎结构性机遇.pdf",
        "quality_tier": 3,
        "note": "PCB制造流程、认证壁垒、数据中心PCB空间和前十大厂商整理。",
        "is_primary_source": 0,
    },
    "huaxi_20260524": {
        "title": "20260524-华西证券-计算机行业周报：新一代服务器拉动PCB，产业链开启高增长",
        "publisher": "华西证券",
        "source_type": "sellside_report",
        "publish_date": "2026-05-24",
        "file_path": "papers/pcb/20260524-华西证券-计算机行业周报：新一代服务器拉动PCB，产业链开启高增长.pdf",
        "quality_tier": 3,
        "note": "PCB产业链分类、覆铜板成本占比和材料提价。",
        "is_primary_source": 0,
    },
    "dongguan_20260427": {
        "title": "20260427-东莞证券-电子行业双周报：关注AI PCB产业链",
        "publisher": "东莞证券",
        "source_type": "sellside_report",
        "publish_date": "2026-04-27",
        "file_path": "papers/pcb/20260427-东莞证券-电子行业双周报：关注AI PCB产业链.pdf",
        "quality_tier": 3,
        "note": "转引公司公告的2026Q1沪电股份、深南电路等业绩。",
        "is_primary_source": 0,
    },
    "dongguan_20260511": {
        "title": "20260511-东莞证券-电子行业双周报：PCB产业链2025年及26Q1业绩高增",
        "publisher": "东莞证券",
        "source_type": "sellside_report",
        "publish_date": "2026-05-11",
        "file_path": "papers/pcb/20260511-东莞证券-电子行业双周报：PCB产业链2025年及26Q1业绩高增.pdf",
        "quality_tier": 3,
        "note": "转引广合科技2026Q1公告及产业链高景气。",
        "is_primary_source": 0,
    },
    "dongguan_20260512": {
        "title": "20260512-东莞证券-电子行业PCB产业链2025年及26Q1业绩综述：下游需求旺盛，产业链业绩高增",
        "publisher": "东莞证券",
        "source_type": "sellside_report",
        "publish_date": "2026-05-12",
        "file_path": "papers/pcb/20260512-东莞证券-电子行业PCB产业链2025年及26Q1业绩综述：下游需求旺盛，产业链业绩高增.pdf",
        "quality_tier": 3,
        "note": "PCB行业2026Q1收入、利润、毛利率、净利率聚合口径。",
        "is_primary_source": 0,
    },
    "shenghong_annual": {
        "title": "胜宏科技（惠州）股份有限公司2025年年度报告",
        "publisher": "胜宏科技",
        "source_type": "annual_report",
        "publish_date": "2026-04-01",
        "file_path": "papers/pcb/胜宏科技.pdf",
        "quality_tier": 1,
        "note": "公司公告原文，2025年财务、研发、产线和技术能力。",
        "is_primary_source": 1,
    },
    "wus_annual": {
        "title": "沪士电子股份有限公司2025年度报告",
        "publisher": "沪电股份",
        "source_type": "annual_report",
        "publish_date": "2026-03-01",
        "file_path": "papers/pcb/沪电股份.pdf",
        "quality_tier": 1,
        "note": "公司公告原文，2025年财务、PCB业务、泰国产能和前沿工艺。",
        "is_primary_source": 1,
    },
    "shennan_annual": {
        "title": "深南电路股份有限公司2025年年度报告",
        "publisher": "深南电路",
        "source_type": "annual_report",
        "publish_date": "2026-03-01",
        "file_path": "papers/pcb/深南电路.pdf",
        "quality_tier": 1,
        "note": "公司公告原文，2025年PCB、封装基板、电子装联和财务。",
        "is_primary_source": 1,
    },
    "avary_annual": {
        "title": "鹏鼎控股（深圳）股份有限公司2025年年度报告",
        "publisher": "鹏鼎控股",
        "source_type": "annual_report",
        "publish_date": "2026-03-01",
        "file_path": "papers/pcb/鹏鼎控股.pdf",
        "quality_tier": 1,
        "note": "公司公告原文，2025年FPC、HDI/HLC、AI服务器和全球产能。",
        "is_primary_source": 1,
    },
    "dongshan_annual": {
        "title": "苏州东山精密制造股份有限公司2025年年度报告",
        "publisher": "东山精密",
        "source_type": "annual_report",
        "publish_date": "2026-04-22",
        "file_path": "papers/pcb/东山精密.pdf",
        "quality_tier": 1,
        "note": "公司公告原文，2025年光模块+AI PCB布局和财务。",
        "is_primary_source": 1,
    },
    "kinwong_annual": {
        "title": "深圳市景旺电子股份有限公司2025年年度报告",
        "publisher": "景旺电子",
        "source_type": "annual_report",
        "publish_date": "2026-03-01",
        "file_path": "papers/pcb/景旺电子.pdf",
        "quality_tier": 1,
        "note": "公司公告原文，2025年AI基础设施PCB、高阶HDI和财务。",
        "is_primary_source": 1,
    },
    "olympic_annual": {
        "title": "广东世运电路科技股份有限公司2025年年度报告",
        "publisher": "世运电路",
        "source_type": "annual_report",
        "publish_date": "2026-03-01",
        "file_path": "papers/pcb/世运电路.pdf",
        "quality_tier": 1,
        "note": "公司公告原文，2025年财务、嵌入式PCB中试线和高阶产品。",
        "is_primary_source": 1,
    },
    "northeast_shenghong_20260505": {
        "title": "20260505-东北证券-胜宏科技-300476-AI PCB龙头业绩高增，高端产能布局加速成长",
        "publisher": "东北证券",
        "source_type": "sellside_report",
        "publish_date": "2026-05-05",
        "file_path": "papers/pcb/20260505-东北证券-胜宏科技-300476-AI PCB龙头业绩高增，高端产能布局加速成长.pdf",
        "quality_tier": 3,
        "note": "胜宏科技2026Q1业绩点评，转引一季报。",
        "is_primary_source": 0,
    },
    "cms_shenghong_20260505": {
        "title": "20260505-招商证券-胜宏科技-300476-AI PCB全球龙头地位夯实，Rubin备货望带来新增长动能",
        "publisher": "招商证券",
        "source_type": "sellside_report",
        "publish_date": "2026-05-05",
        "file_path": "papers/pcb/20260505-招商证券-胜宏科技-300476-AI PCB全球龙头地位夯实，Rubin备货望带来新增长动能.pdf",
        "quality_tier": 3,
        "note": "胜宏科技2026Q1毛利率、净利率和订单结构点评。",
        "is_primary_source": 0,
    },
    "kaiyuan_dongshan_20260430": {
        "title": "20260430-开源证券-东山精密-002384-公司信息更新报告：2026Q1业绩高增，“光模块+AIPCB”打开成长空间",
        "publisher": "开源证券",
        "source_type": "sellside_report",
        "publish_date": "2026-04-30",
        "file_path": "papers/pcb/20260430-开源证券-东山精密-002384-公司信息更新报告：2026Q1业绩高增，“光模块+AIPCB”打开成长空间.pdf",
        "quality_tier": 3,
        "note": "东山精密2025年报和2026Q1业绩点评。",
        "is_primary_source": 0,
    },
    "guangfa_guanghe_20260604": {
        "title": "20260604-广发证券-广合科技-001389-服务器PCB核心厂商，把握算力升级机遇",
        "publisher": "广发证券",
        "source_type": "sellside_report",
        "publish_date": "2026-06-04",
        "file_path": "papers/pcb/20260604-广发证券-广合科技-001389-服务器PCB核心厂商，把握算力升级机遇.pdf",
        "quality_tier": 3,
        "note": "广合科技服务器PCB客户覆盖与高端产品资料。",
        "is_primary_source": 0,
    },
    "yfinance_20260706": {
        "title": "Tushare / Yahoo Finance PCB manufacturer market snapshot 2026-07-07",
        "publisher": "Tushare Pro / Yahoo Finance",
        "source_type": "api_snapshot",
        "publish_date": TODAY,
        "file_path": "",
        "url": "https://tushare.pro/; https://finance.yahoo.com/",
        "quality_tier": 2,
        "note": "2026-07-07通过Tushare/yfinance读取价格、市值、PE/PB/PS、毛利率、净利率、现金流和capex；A股优先Tushare，海外使用yfinance，金额统一人民币并保留美元等值。",
        "is_primary_source": 0,
    },
}


COMPANIES = {
    "shenghong": {
        "name": "胜宏科技",
        "ticker": "300476.SZ",
        "market": "A股",
        "listing_status": "a_share",
        "brief_intro": "AI服务器PCB全球第一梯队，2025年年报披露高多层、HDI、mSAP分事业部，具备100层以上高多层和30层HDI能力。",
        "source": "shenghong_annual",
        "role": "AI服务器HLC/HDI核心制造商",
        "profile": {
            "period": "2025",
            "revenue_series": {"2023": 79.3125, "2024": 107.3147, "2025": 192.9231, "unit": "亿元人民币"},
            "net_income_series": {"2023": 6.7135, "2024": 11.5443, "2025": 43.1199, "unit": "亿元人民币"},
            "gross_margin": None,
            "net_margin": 22.35,
            "operating_cash_flow": 46.0265,
            "ocf_unit": "亿元人民币",
            "financials_as_of": "2025-12-31",
            "rd_expense_ratio": 4.03,
            "capex_value": 36.54,
            "capex_unit": "亿元人民币，2025年前三季度口径",
            "global_rank": 7,
            "main_products": "高多层HLC、HDI、mSAP、多层MLB，AI算力卡、数据中心交换机、HPC PCB。",
            "main_customers": "国内外头部科技企业；公开年报未披露客户名称。",
            "tech_node": "100层以上高多层板；全球首批6阶24层HDI大规模生产；10阶30层HDI与16层Any-layer HDI能力。",
            "recent_events": "2026Q1营收55.19亿元、归母净利12.88亿元；惠州九/十/十一项目和泰国、越南高端产能推进。",
            "risks": "上游覆铜板、铜球、铜箔和半固化片价格传导滞后；AI客户订单集中与产能扩张节奏。",
            "is_china_tech_leader": 1,
            "in_global_table": 1,
            "in_china_table": 1,
            "summary": "胜宏的核心不是传统PCB规模，而是高阶AI服务器产品量产和客户绑定；财务弹性已在2025和2026Q1利润率中体现。",
        },
    },
    "wus": {
        "name": "沪电股份",
        "ticker": "002463.SZ",
        "market": "A股",
        "listing_status": "a_share",
        "brief_intro": "数据通讯和智能汽车PCB龙头，2025年PCB业务181.43亿元、毛利率36.91%，泰国基地进入高利用率阶段。",
        "source": "wus_annual",
        "role": "高频高速HLC/数据通信PCB龙头",
        "profile": {
            "period": "2025",
            "revenue_series": {"2023": 89.3831, "2024": 133.4154, "2025": 189.4522, "unit": "亿元人民币"},
            "net_income_series": {"2023": 15.1254, "2024": 25.8724, "2025": 38.2231, "unit": "亿元人民币"},
            "gross_margin": 36.91,
            "net_margin": 20.18,
            "operating_cash_flow": 38.7197,
            "ocf_unit": "亿元人民币",
            "financials_as_of": "2025-12-31",
            "rd_expense_ratio": 6.02,
            "capex_value": 21.04,
            "capex_unit": "亿元人民币，2025年前三季度口径",
            "global_rank": 6,
            "main_products": "AI服务器及HPC、高速交换机/路由器、汽车智能及电动化PCB。",
            "main_customers": "全球头部数据通信和汽车客户；泰国数据通讯事业部已有超70%海外客户认证。",
            "tech_node": "超高层堆栈、高频高速、HDI、高通流；2026年初规划CoWoP和mSAP孵化平台。",
            "recent_events": "泰国数据通讯事业部2026Q1产能利用率超90%；2026Q1营收62.14亿元、归母12.42亿元。",
            "risks": "高端扩产带来同质化竞争、材料供应和海外运营风险。",
            "is_china_tech_leader": 1,
            "in_global_table": 1,
            "in_china_table": 1,
            "summary": "沪电的壁垒来自数据通讯客户认证、材料/工艺协同和国内外产能矩阵，而不是单纯扩产。",
        },
    },
    "shennan": {
        "name": "深南电路",
        "ticker": "002916.SZ",
        "market": "A股",
        "listing_status": "a_share",
        "brief_intro": "平台型电子电路公司，PCB、封装基板和电子装联三线布局，2025年PCB业务143.59亿元。",
        "source": "shennan_annual",
        "role": "PCB+封装基板平台型厂商",
        "profile": {
            "period": "2025",
            "revenue_series": {"2023": 135.2643, "2024": 179.0745, "2025": 236.4698, "unit": "亿元人民币"},
            "net_income_series": {"2023": 13.9811, "2024": 18.7757, "2025": 32.7574, "unit": "亿元人民币"},
            "gross_margin": 35.53,
            "net_margin": 13.85,
            "operating_cash_flow": 38.3834,
            "ocf_unit": "亿元人民币",
            "financials_as_of": "2025-12-31",
            "rd_expense_ratio": 6.73,
            "capex_value": None,
            "capex_unit": None,
            "global_rank": 4,
            "main_products": "通信、数据中心、汽车PCB；BT/FC-CSP/FC-BGA封装基板；电子装联。",
            "main_customers": "通信、数据中心、汽车和存储客户；公开年报未披露客户名称。",
            "tech_node": "PCB业务算力产品竞争力强化；FC-BGA 22层及以下量产，24层及以上研发打样。",
            "recent_events": "泰国工厂和南通四期2025H2连线投产；2026Q1营收65.96亿元、归母8.50亿元。",
            "risks": "平台业务复杂度高，封装基板良率和客户导入节奏决定估值弹性。",
            "is_china_tech_leader": 1,
            "in_global_table": 1,
            "in_china_table": 1,
            "summary": "深南的关键是从PCB向封装基板延伸；若FC-BGA高层数突破兑现，价值边界会从板厂向载板平台迁移。",
        },
    },
    "avary": {
        "name": "鹏鼎控股",
        "ticker": "002938.SZ",
        "market": "A股",
        "listing_status": "a_share",
        "brief_intro": "全球PCB头部企业，FPC底盘深厚，正在向AI服务器IHDI/HLC、光模块SLP和全球化产能迁移。",
        "source": "avary_annual",
        "role": "FPC龙头向AI服务器IHDI/HLC迁移",
        "profile": {
            "period": "2025",
            "revenue_series": {"2023": 320.6605, "2024": 351.4038, "2025": 391.4701, "unit": "亿元人民币"},
            "net_income_series": {"2023": 32.8695, "2024": 36.2035, "2025": 37.3784, "unit": "亿元人民币"},
            "gross_margin": None,
            "net_margin": 9.55,
            "operating_cash_flow": 72.8579,
            "ocf_unit": "亿元人民币",
            "financials_as_of": "2025-12-31",
            "rd_expense_ratio": 6.28,
            "capex_value": 80.0,
            "capex_unit": "亿元人民币，淮安园区2025H2-2028计划投入",
            "global_rank": 1,
            "main_products": "FPC、SLP、HDI、RPCB、Rigid Flex、IHDI/HLC服务器板、光模块板。",
            "main_customers": "智能终端、云服务器、光通讯客户；HLC产品正获或推进云服务厂商认证。",
            "tech_node": "6阶以上HDI量产能力，高阶HDI/SLP领先；AI服务器IHDI、HLC和内埋元件/低损耗材料开发。",
            "recent_events": "2025年汽车/服务器用板收入21.19亿元、同比+106.67%；AI服务器类产品收入较2024年增长超1倍。",
            "risks": "消费电子底盘较大，AI服务器转型要看HLC认证和新产能爬坡，而非只看总营收。",
            "is_china_tech_leader": 1,
            "in_global_table": 1,
            "in_china_table": 1,
            "summary": "鹏鼎最大的变量是从端侧FPC龙头变成云侧高阶IHDI/HLC供应商；认证和海外产能决定重估幅度。",
        },
    },
    "dongshan": {
        "name": "东山精密",
        "ticker": "002384.SZ",
        "market": "A股",
        "listing_status": "a_share",
        "brief_intro": "消费电子精密制造底盘叠加Multek高端PCB与索尔思光模块，2025年开始强化AI PCB产能。",
        "source": "dongshan_annual",
        "role": "AI PCB+光模块协同型厂商",
        "profile": {
            "period": "2025",
            "revenue_series": {"2023": 336.5121, "2024": 367.7037, "2025": 401.2486, "unit": "亿元人民币"},
            "net_income_series": {"2023": 19.6453, "2024": 10.8564, "2025": 13.8607, "unit": "亿元人民币"},
            "gross_margin": 14.09,
            "net_margin": 3.47,
            "operating_cash_flow": 53.0714,
            "ocf_unit": "亿元人民币",
            "financials_as_of": "2025-12-31",
            "rd_expense_ratio": 3.53,
            "capex_value": 10.0,
            "capex_unit": "亿美元，高端PCB扩产计划上限",
            "global_rank": 3,
            "main_products": "消费电子核心器件、汽车零部件、Multek高端PCB、AI PCB、光模块/光芯片。",
            "main_customers": "AI数据中心客户和消费电子客户；公开年报未披露客户名称。",
            "tech_node": "HDI和高多层PCB产能建设，适配AI数据中心高端PCB需求。",
            "recent_events": "2026Q1营收131.38亿元、归母11.10亿元，光模块并表与AI PCB推动盈利跃升。",
            "risks": "光模块并表造成口径复杂；PCB制造贡献需要与光模块业务分拆观察。",
            "is_china_tech_leader": 1,
            "in_global_table": 1,
            "in_china_table": 1,
            "summary": "东山不是纯PCB估值，核心是“光模块+AI PCB”的协同能否提高客户粘性和单机价值。",
        },
    },
    "kinwong": {
        "name": "景旺电子",
        "ticker": "603228.SS",
        "market": "A股",
        "listing_status": "a_share",
        "brief_intro": "多品类PCB厂商，AI基础设施、800G/1.6T光模块、汽车电子和卫星应用并进。",
        "source": "kinwong_annual",
        "role": "高阶HDI/HLC和光模块PCB扩张厂商",
        "profile": {
            "period": "2025",
            "revenue_series": {"2023": 107.5730, "2024": 126.5937, "2025": 153.0805, "unit": "亿元人民币"},
            "net_income_series": {"2024": 11.6903, "2025": 12.3097, "unit": "亿元人民币"},
            "gross_margin": 16.95,
            "net_margin": 8.04,
            "operating_cash_flow": 19.3122,
            "ocf_unit": "亿元人民币",
            "financials_as_of": "2025-12-31",
            "rd_expense_ratio": 6.07,
            "capex_value": None,
            "capex_unit": None,
            "global_rank": 11,
            "main_products": "40层以上HLC、6阶22层HDI、14层mSAP HDI、多层PTFE FPC、800G/1.6T光模块PCB。",
            "main_customers": "全球AI计算基础设施领先客户、光模块头部客户、汽车电子客户。",
            "tech_node": "M7至M9级别及PTFE材料量产加工能力；9阶HDI 90天通过客户认证；11阶HDI认证启动。",
            "recent_events": "珠海金湾基地聚焦高阶HDI、HLC、SLP，泰国基地主体结构封顶。",
            "risks": "高端产品占比提升仍在爬坡，毛利率受材料涨价和新基地投产节奏影响。",
            "is_china_tech_leader": 1,
            "in_global_table": 1,
            "in_china_table": 1,
            "summary": "景旺是从传统多品类板厂向AI基础设施高阶板升级的样本，认证速度和M9材料能力是跟踪重点。",
        },
    },
    "olympic": {
        "name": "世运电路",
        "ticker": "603920.SS",
        "market": "A股",
        "listing_status": "a_share",
        "brief_intro": "汽车PCB底盘深厚，并在高多层、HDI、嵌入式PCB和AI服务器板上形成早期突破。",
        "source": "olympic_annual",
        "role": "汽车PCB向AI服务器/嵌入式PCB延伸",
        "profile": {
            "period": "2025",
            "revenue_series": {"2023": 45.1908, "2024": 50.2203, "2025": 55.7689, "unit": "亿元人民币"},
            "net_income_series": {"2025": 6.84, "unit": "亿元人民币"},
            "gross_margin": 14.73,
            "net_margin": 12.27,
            "operating_cash_flow": 9.2072,
            "ocf_unit": "亿元人民币",
            "financials_as_of": "2025-12-31",
            "rd_expense_ratio": 4.15,
            "capex_value": None,
            "capex_unit": None,
            "global_rank": 34,
            "main_products": "汽车PCB、28层AI服务器线路板、5阶HDI、6oz厚铜多层板、嵌入式PCB模组。",
            "main_customers": "汽车、能源管理、AI数据中心与高功率通信设备客户；公开年报未披露客户名称。",
            "tech_node": "28层AI服务器板、5阶HDI、芯片内嵌式PCB中试线。",
            "recent_events": "2026Q1建成芯片内嵌式PCB中试线，芯创智载项目预计2026年中投产。",
            "risks": "规模小于头部AI PCB厂，嵌入式PCB商业化需要客户验证和良率爬坡。",
            "is_china_tech_leader": 0,
            "in_global_table": 1,
            "in_china_table": 1,
            "summary": "世运的看点不是当前规模，而是汽车功率电子与AI数据中心电源管理对嵌入式PCB的交叉拉动。",
        },
    },
    "guanghe": {
        "name": "广合科技",
        "ticker": "001389.SZ",
        "market": "A股",
        "listing_status": "a_share",
        "brief_intro": "服务器PCB核心厂商，覆盖全球前十大服务器制造商中的八家，高阶HDI和AI服务器产品突破。",
        "source": "guangfa_guanghe_20260604",
        "role": "服务器PCB高增长厂商",
        "profile": {
            "period": "2026Q1",
            "revenue_series": {"2026Q1": 19.14, "unit": "亿元人民币"},
            "net_income_series": {"2026Q1": 3.93, "unit": "亿元人民币"},
            "gross_margin": None,
            "net_margin": 20.53,
            "operating_cash_flow": None,
            "ocf_unit": None,
            "financials_as_of": "2026-03-31",
            "rd_expense_ratio": None,
            "capex_value": None,
            "capex_unit": None,
            "global_rank": None,
            "main_products": "数据中心、云计算、AI、高速交换机、新代际服务器和光模块PCB。",
            "main_customers": "全球前十大服务器制造商中的八家；具体客户未公开披露。",
            "tech_node": "2025H1在高阶HDI、AI服务器、高速交换机、新代际服务器、光模块等产品持续突破。",
            "recent_events": "2026Q1营收19.14亿元、归母3.93亿元。",
            "risks": "业务集中在服务器景气链，客户和订单波动对短期盈利弹性影响大。",
            "is_china_tech_leader": 1,
            "in_global_table": 0,
            "in_china_table": 1,
            "summary": "广合是服务器PCB弹性标的，跟踪重点是头部服务器客户份额和高阶HDI放量。",
        },
    },
    "unimicron": {
        "name": "欣兴电子",
        "ticker": "3037.TW",
        "market": "台股",
        "listing_status": "other_listed",
        "brief_intro": "全球PCB与IC载板头部厂商，Prismark 2025E收入42.25亿美元，位居全球第二。",
        "source": "prismark",
        "role": "全球HDI/载板对照龙头",
        "profile": {
            "period": "2025E",
            "revenue_series": {"2024": 35.94, "2025E": 42.25, "unit": "亿美元"},
            "summary": "欣兴是全球高端PCB和载板的外部对照，代表台系在HDI/载板能力上的成熟度。",
            "global_rank": 2,
            "in_global_table": 1,
            "main_products": "HDI、IC载板、PCB。",
            "risks": "台系产能与客户结构更偏全球CSP和消费电子，需与A股公司口径分开比较。",
        },
    },
    "zhen_ding": {
        "name": "臻鼎科技",
        "ticker": "4958.TW",
        "market": "台股",
        "listing_status": "other_listed",
        "brief_intro": "全球PCB收入第一梯队，Prismark 2025E收入58.69亿美元。",
        "source": "prismark",
        "role": "全球PCB收入第一龙头",
        "profile": {
            "period": "2025E",
            "revenue_series": {"2024": 53.40, "2025E": 58.69, "unit": "亿美元"},
            "summary": "臻鼎提供全球PCB平台型规模上限参照，也通过鹏鼎控股反映大陆上市平台的一部分能力。",
            "global_rank": 1,
            "in_global_table": 1,
            "main_products": "FPC、HDI、HLC、IC载板、SLP。",
            "risks": "集团与鹏鼎控股口径不能混同，需按上市主体和业务归属拆分。",
        },
    },
    "ttm": {
        "name": "TTM Technologies",
        "ticker": "TTMI",
        "market": "美股",
        "listing_status": "other_listed",
        "brief_intro": "美国高可靠PCB和系统级制造商，Prismark 2025E收入29.06亿美元。",
        "source": "prismark",
        "role": "北美高可靠PCB对照厂商",
        "profile": {
            "period": "2025E",
            "revenue_series": {"2024": 24.43, "2025E": 29.06, "unit": "亿美元"},
            "summary": "TTM是北美军事、航空、网络和高可靠板卡对照，地缘和本土供应链属性强。",
            "global_rank": 5,
            "in_global_table": 1,
            "main_products": "高可靠刚性PCB、射频/微波、航空航天和网络通信板。",
            "risks": "美国本土供应链溢价与中国/台系大规模制造口径不同。",
        },
    },
    "compeq": {
        "name": "华通Compeq",
        "ticker": "2313.TW",
        "market": "台股",
        "listing_status": "other_listed",
        "brief_intro": "台系PCB头部厂，Prismark 2025E收入24.46亿美元。",
        "source": "prismark",
        "role": "台系HDI/HLC对照厂商",
        "profile": {
            "period": "2025E",
            "revenue_series": {"2024": 22.56, "2025E": 24.46, "unit": "亿美元"},
            "summary": "华通是台系高阶板能力参照，和欣兴、健鼎共同构成大陆厂商的外部比较组。",
            "global_rank": 8,
            "in_global_table": 1,
            "main_products": "HDI、多层板、通信与消费电子PCB。",
            "risks": "客户结构和制程结构需与A股公司拆分比较。",
        },
    },
    "tripod": {
        "name": "健鼎科技",
        "ticker": "3044.TW",
        "market": "台股",
        "listing_status": "other_listed",
        "brief_intro": "台系PCB头部厂，Prismark 2025E收入23.61亿美元。",
        "source": "prismark",
        "role": "台系多层板对照厂商",
        "profile": {
            "period": "2025E",
            "revenue_series": {"2024": 20.50, "2025E": 23.61, "unit": "亿美元"},
            "summary": "健鼎科技是多层板和车用/服务器板的全球对照，反映台系制造效率与客户粘性。",
            "global_rank": 9,
            "in_global_table": 1,
            "main_products": "多层板、HDI、汽车和服务器PCB。",
            "risks": "台股主体披露与A股公司年报口径不同。",
        },
    },
    "ibiden": {
        "name": "Ibiden",
        "ticker": "4062.T",
        "market": "日股",
        "listing_status": "other_listed",
        "brief_intro": "日本IC载板/高端PCB龙头，Prismark 2025E收入14.97亿美元。",
        "source": "prismark",
        "role": "日系高端载板对照厂商",
        "profile": {
            "period": "2025E",
            "revenue_series": {"2024": 12.42, "2025E": 14.97, "unit": "亿美元"},
            "summary": "Ibiden代表ABF载板和先进封装供应链的高壁垒参照，CoWoP若推进会影响其价值边界。",
            "global_rank": 18,
            "in_global_table": 1,
            "main_products": "IC载板、高端PCB。",
            "risks": "若CoWoP/SLP替代路线成熟，部分载板价值可能向PCB转移；但短期仍是高壁垒环节。",
        },
    },
    "meiko": {
        "name": "Meiko Electronics",
        "ticker": "6787.T",
        "market": "日股",
        "listing_status": "other_listed",
        "brief_intro": "日本PCB头部厂，Prismark 2025E收入15.17亿美元。",
        "source": "prismark",
        "role": "日系汽车/高可靠PCB对照厂商",
        "profile": {
            "period": "2025E",
            "revenue_series": {"2024": 13.06, "2025E": 15.17, "unit": "亿美元"},
            "summary": "Meiko是汽车和高可靠应用对照，适合作为世运、景旺等汽车/工控板厂的外部参照。",
            "global_rank": 17,
            "in_global_table": 1,
            "main_products": "汽车、通信、工业PCB。",
            "risks": "日系高可靠认证周期与中国AI服务器扩产节奏不同。",
        },
    },
}


YFINANCE = {
    "shenghong": {"price": 308.0700, "market_cap": 302766524539.04, "currency": "CNY", "pe_ttm": 56.8395, "pe_forward": 20.6800, "pb": 16.1310},
    "wus": {"price": 135.3500, "market_cap": 260462616478.33, "currency": "CNY", "pe_ttm": 60.9685, "pe_forward": 29.9139, "pb": 15.5129},
    "shennan": {"price": 454.4800, "market_cap": 309576601579.12, "currency": "CNY", "pe_ttm": 86.8987, "pe_forward": 43.0034, "pb": 17.1127},
    "avary": {"price": 96.7700, "market_cap": 224268014614.84, "currency": "CNY", "pe_ttm": 60.4812, "pe_forward": 33.9544, "pb": 6.4617},
    "dongshan": {"price": 232.7300, "market_cap": 426270013096.89, "currency": "CNY", "pe_ttm": 204.1491, "pe_forward": 63.0970, "pb": 18.7052},
    "kinwong": {"price": 71.9700, "market_cap": 70949482364.82, "currency": "CNY", "pe_ttm": 63.6903, "pe_forward": 42.3353, "pb": 5.3276},
    "guanghe": {"price": 203.0000, "market_cap": 95959960292.00, "currency": "CNY", "pe_ttm": 73.5507, "pe_forward": 28.4460, "pb": 11.8866},
    "olympic": {"price": 45.4600, "market_cap": 32758126071.10, "currency": "CNY", "pe_ttm": 60.6133, "pe_forward": 26.5848, "pb": 5.0310},
    "unimicron": {"price": 969.0000, "market_cap": 1525347243378.00, "currency": "TWD", "pe_ttm": 222.2477, "pe_forward": 31.0271, "pb": 13.5743},
    "zhen_ding": {"price": 613.0000, "market_cap": 661684984115.00, "currency": "TWD", "pe_ttm": 90.9496, "pe_forward": 26.0196, "pb": 5.2165},
    "compeq": {"price": 229.5000, "market_cap": 275107043020.50, "currency": "TWD", "pe_ttm": 42.0330, "pe_forward": 18.8424, "pb": 5.8378},
    "tripod": {"price": 520.0000, "market_cap": 273315120000.00, "currency": "TWD", "pe_ttm": 26.8873, "pe_forward": 14.9647, "pb": 4.6879},
    "ibiden": {"price": 23345.0000, "market_cap": 6518987037920.00, "currency": "JPY", "pe_ttm": 108.6977, "pe_forward": 75.5599, "pb": 11.8512},
    "meiko": {"price": 29330.0000, "market_cap": 752804662960.00, "currency": "JPY", "pe_ttm": 38.6099, "pe_forward": 46.5039, "pb": 5.5245},
    "ttm": {"price": 155.9800, "market_cap": 16198531759.12, "currency": "USD", "pe_ttm": 84.7717, "pe_forward": 28.8852, "pb": 8.8139},
}


MARKET_SNAPSHOT: dict[str, dict] = {}


RECENT_EVENTS = {
    "unimicron": "欣兴电子位列 Prismark 2025E 全球 PCB 供应商第二，收入约 42.25 亿美元，是 ABF/HDI/高端载板景气和台系供给的核心对照。",
    "zhen_ding": "臻鼎科技位列 Prismark 2025E 全球 PCB 供应商第一，收入约 58.69 亿美元，规模和消费电子/服务器结构迁移用于校准鹏鼎等大集团口径。",
    "compeq": "华通 Compeq 位列 Prismark 2025E 全球前列，收入约 24.46 亿美元，是台系 HDI、通讯和高阶板供给能力对照。",
    "tripod": "健鼎科技位列 Prismark 2025E 全球前列，收入约 22.99 亿美元，用于对照汽车、服务器和高可靠 PCB 的台系制造能力。",
    "ibiden": "Ibiden 位列 Prismark 2025E 全球前列，收入约 25.62 亿美元，是 ABF/封装基板和日系高端载板能力的关键对照。",
    "meiko": "Meiko Electronics 位列 Prismark 2025E 全球前列，收入约 11.13 亿美元，是汽车、高可靠和日系 PCB 供应链对照。",
    "ttm": "TTM Technologies 位列 Prismark 2025E 全球前列，收入约 29.06 亿美元，是北美高可靠、国防航天和地缘供应链对照。",
}


def fetch_pcb_market_snapshot() -> dict[str, dict]:
    fx = fetch_fx_rates()
    snapshot: dict[str, dict] = {"_fx": fx}
    for key, meta in COMPANIES.items():
        ticker = meta.get("ticker")
        if not ticker:
            snapshot[key] = {"error": "无上市 ticker，无法取得二级市场估值。"}
            continue
        snap = fetch_company_market_snapshot(ticker, yf_symbol=ticker, fx=fx)
        if snap.get("error") and key in YFINANCE:
            old = dict(YFINANCE[key])
            old.update(
                {
                    "source": "legacy_yfinance_fallback",
                    "symbol": ticker,
                    "error": snap.get("error"),
                    "market_cap_cny": round(old["market_cap"] * fx.get(old["currency"], 1.0) / 1e8, 2),
                }
            )
            old["market_cap_usd"] = round(old["market_cap_cny"] / fx["USD"], 2)
            old["market_cap_value"] = old["market_cap_cny"]
            old["market_cap_unit"] = "亿元人民币"
            snapshot[key] = old
        else:
            snapshot[key] = snap
    return snapshot


def market_for_company(key: str) -> dict:
    return MARKET_SNAPSHOT.get(key) or YFINANCE.get(key) or {}


def _normalize_money_unit(value, unit: str | None, *, fallback_currency: str = "CNY") -> tuple[float | None, str | None]:
    if value is None:
        return None, unit
    try:
        val = float(value)
    except (TypeError, ValueError):
        return value, unit
    fx = MARKET_SNAPSHOT.get("_fx") or FX
    text = unit or ""
    suffix = ""
    if "，" in text:
        suffix = "，" + text.split("，", 1)[1]
    if "亿美元" in text:
        cny = round(val * fx.get("USD", FX["USD"]), 2)
        usd = round(val, 2)
    elif "亿元人民币" in text or fallback_currency == "CNY":
        cny = round(val, 2)
        usd = round(cny / fx.get("USD", FX["USD"]), 2)
    else:
        rate = fx.get(fallback_currency, 1.0)
        cny = round(val * rate, 2)
        usd = round(cny / fx.get("USD", FX["USD"]), 2)
    return cny, f"亿元人民币（约 {usd:.2f} 亿美元）{suffix}"


def ensure_source(conn: sqlite3.Connection, key: str, meta: dict) -> int:
    row = conn.execute(
        "select id from source where title=? and coalesce(file_path,'')=coalesce(?, '')",
        (meta["title"], meta.get("file_path", "")),
    ).fetchone()
    fields = {
        "title": meta["title"],
        "source_type": SOURCE_TYPE_MAP.get(meta.get("source_type"), meta.get("source_type", "其他")),
        "publisher": meta.get("publisher"),
        "author": meta.get("author"),
        "publish_date": meta.get("publish_date"),
        "quality_tier": meta.get("quality_tier"),
        "is_forward_looking": meta.get("is_forward_looking", 0),
        "file_path": meta.get("file_path", ""),
        "url": meta.get("url"),
        "note": meta.get("note"),
        "value_layer": meta.get("value_layer", "信息流"),
        "source_url": meta.get("url"),
        "key_arguments": meta.get("key_arguments"),
        "source_subtype": meta.get("source_subtype"),
        "fetch_timestamp": TODAY,
        "fetch_method": "local_pdf_or_api_snapshot",
        "domain": meta.get("domain"),
        "language": meta.get("language", "zh"),
        "is_primary_source": meta.get("is_primary_source", 0),
        "source_credibility": meta.get("source_credibility", "trusted_project_source"),
        "content_snapshot_path": meta.get("content_snapshot_path"),
    }
    if row:
        sid = int(row[0])
        assignments = ",".join([f"{k}=?" for k in fields if k != "title"])
        values = [v for k, v in fields.items() if k != "title"] + [sid]
        conn.execute(f"update source set {assignments} where id=?", values)
        return sid
    cols = ",".join(fields.keys())
    qs = ",".join(["?"] * len(fields))
    cur = conn.execute(f"insert into source ({cols}) values ({qs})", list(fields.values()))
    return int(cur.lastrowid)


def ensure_industry(conn: sqlite3.Connection) -> int:
    row = conn.execute("select id from industry where name=?", (INDUSTRY_NAME,)).fetchone()
    core_dynamic = (
        "PCB制造本轮核心变量不是总量复苏，而是AI服务器、高速网络和先进封装边界变化驱动"
        "HLC/HDI/SLP/mSAP/CoWoP等高端板价值量抬升；同时CCL、铜箔、树脂、玻纤布涨价"
        "把利润在上游和头部制造商之间重新分配。"
    )
    if row:
        iid = int(row[0])
        conn.execute(
            "update industry set tier=?, status=?, core_dynamic=?, last_updated=? where id=?",
            (1, "深度跟踪", core_dynamic, TODAY, iid),
        )
        return iid
    cur = conn.execute(
        """
        insert into industry(name,parent_id,level,tier,status,core_dynamic,last_updated)
        values(?,?,?,?,?,?,?)
        """,
        (INDUSTRY_NAME, None, 1, 1, "深度跟踪", core_dynamic, TODAY),
    )
    return int(cur.lastrowid)


def ensure_company(conn: sqlite3.Connection, key: str, industry_id: int, source_ids: dict) -> int:
    meta = COMPANIES[key]
    row = conn.execute("select id from company where name=?", (meta["name"],)).fetchone()
    yf = market_for_company(key)
    market_cap_cny = None
    market_cap_usd = None
    market_cap_value = None
    market_cap_unit = None
    if yf and not yf.get("error") and yf.get("market_cap_cny") is not None:
        market_cap_value = yf.get("market_cap_cny")
        market_cap_unit = "亿元人民币"
        market_cap_cny = yf.get("market_cap_cny")
        market_cap_usd = yf.get("market_cap_usd")
    fields = {
        "name": meta["name"],
        "ticker": meta.get("ticker"),
        "market": meta.get("market") if meta.get("market") in {"A股", "港股", "美股", "其他"} else "其他",
        "note": meta.get("role"),
        "listing_status": meta.get("listing_status"),
        "pe_ttm": yf.get("pe_ttm") if yf else None,
        "pe_forward": yf.get("pe_forward") if yf else None,
        "pb": yf.get("pb") if yf else None,
        "ps_ttm": yf.get("ps_ttm") if yf else None,
        "market_cap_value": market_cap_value,
        "market_cap_unit": market_cap_unit,
        "valuation_as_of": TODAY if yf and not yf.get("error") else None,
        "display_mode": "quantitative",
        "valuation_source_id": source_ids.get("yfinance_20260706") if yf and not yf.get("error") else None,
        "brief_intro": meta.get("brief_intro"),
        "brief_intro_src": f"source:{source_ids.get(meta.get('source'))}" if meta.get("source") else None,
        "market_cap_cny": market_cap_cny,
        "market_cap_usd": market_cap_usd,
        "market_cap_cny_as_of": TODAY if yf and not yf.get("error") else None,
    }
    if row:
        cid = int(row[0])
        assignments = ",".join([f"{k}=?" for k in fields if k != "name"])
        values = [v for k, v in fields.items() if k != "name"] + [cid]
        conn.execute(f"update company set {assignments} where id=?", values)
    else:
        cols = ",".join(fields.keys())
        qs = ",".join(["?"] * len(fields))
        cur = conn.execute(f"insert into company ({cols}) values ({qs})", list(fields.values()))
        cid = int(cur.lastrowid)
    conn.execute(
        """
        insert into company_industry(company_id, industry_id, role, note)
        values(?,?,?,?)
        on conflict(company_id, industry_id) do update set
            role=excluded.role,
            note=excluded.note
        """,
        (cid, industry_id, meta.get("role"), meta.get("brief_intro")),
    )
    write_company_profile(conn, cid, industry_id, key, source_ids)
    return cid


def write_company_profile(conn: sqlite3.Connection, company_id: int, industry_id: int, key: str, source_ids: dict) -> None:
    meta = COMPANIES[key]
    profile = meta.get("profile", {})
    if not profile:
        return
    yf = market_for_company(key)
    period = profile.get("period", "2025")
    source_list = [source_ids.get(meta.get("source"))]
    if yf and not yf.get("error"):
        source_list.append(source_ids["yfinance_20260706"])
    source_list = [x for x in source_list if x]
    primary_source_id = source_ids.get(meta.get("source"))
    gross_margin = profile.get("gross_margin") if profile.get("gross_margin") is not None else yf.get("gross_margin")
    net_margin = profile.get("net_margin") if profile.get("net_margin") is not None else yf.get("net_margin")
    operating_cash_flow = profile.get("operating_cash_flow") if profile.get("operating_cash_flow") is not None else yf.get("operating_cash_flow")
    rd_ratio = profile.get("rd_expense_ratio") if profile.get("rd_expense_ratio") is not None else yf.get("rd_expense_ratio")
    capex_value = profile.get("capex_value") if profile.get("capex_value") is not None else yf.get("capex_value")
    operating_cash_flow, ocf_unit = _normalize_money_unit(operating_cash_flow, profile.get("ocf_unit")) if operating_cash_flow is not None else (None, None)
    if profile.get("capex_value") is not None:
        capex_value, capex_unit = _normalize_money_unit(capex_value, profile.get("capex_unit"))
    else:
        capex_unit = unit_cny_usd(capex_value, yf.get("capex_usd")) if capex_value is not None else None
    recent_events = profile.get("recent_events") or RECENT_EVENTS.get(key) or profile.get("summary") or meta.get("brief_intro")
    fields = {
        "company_id": company_id,
        "industry_id": industry_id,
        "period": period,
        "revenue_series": json_text(profile_series_rows(profile.get("revenue_series"))) if profile.get("revenue_series") else None,
        "net_income_series": json_text(profile_series_rows(profile.get("net_income_series"))) if profile.get("net_income_series") else None,
        "gross_margin": gross_margin,
        "net_margin": net_margin,
        "operating_cash_flow": operating_cash_flow,
        "ocf_unit": ocf_unit,
        "financials_as_of": profile.get("financials_as_of"),
        "global_share": profile.get("global_share"),
        "global_share_as_of": profile.get("global_share_as_of"),
        "global_rank": profile.get("global_rank"),
        "china_share": profile.get("china_share"),
        "china_share_as_of": profile.get("china_share_as_of"),
        "china_rank": profile.get("china_rank"),
        "share_rank_change": profile.get("share_rank_change"),
        "revenue_share_in_industry": profile.get("revenue_share_in_industry"),
        "main_products": profile.get("main_products"),
        "main_customers": profile.get("main_customers"),
        "customer_concentration": profile.get("customer_concentration"),
        "rd_expense_ratio": rd_ratio,
        "capex_value": capex_value,
        "capex_unit": capex_unit,
        "tech_node": profile.get("tech_node"),
        "recent_events": json_text(profile_event_rows(recent_events, primary_source_id, profile.get("financials_as_of") or TODAY)) if recent_events else None,
        "risks": json_text(profile_risk_rows(profile.get("risks"), primary_source_id)) if profile.get("risks") else None,
        "is_china_tech_leader": profile.get("is_china_tech_leader", 0),
        "in_global_table": profile.get("in_global_table", 0),
        "in_china_table": profile.get("in_china_table", 0),
        "listing_status": meta.get("listing_status"),
        "source_ids": json_text(source_list),
        "summary": profile.get("summary"),
        "display_note": f"{RUN_TAG}: B轨PCB制造公司透视，估值/财务为Tushare或yfinance {TODAY}快照；金额统一人民币，括号补美元等值。",
        "last_updated": TODAY,
        "last_verified_at": TODAY,
        "brief_intro": meta.get("brief_intro"),
        "brief_intro_src": f"source:{primary_source_id}" if primary_source_id else None,
    }
    cols = ",".join(fields.keys())
    qs = ",".join(["?"] * len(fields))
    update_cols = [k for k in fields if k not in {"company_id", "industry_id", "period"}]
    update_clause = ",".join([f"{k}=excluded.{k}" for k in update_cols])
    conn.execute(
        f"""
        insert into company_profile({cols}) values({qs})
        on conflict(company_id, industry_id, period) do update set {update_clause}
        """,
        list(fields.values()),
    )


def add_dp(dps: list, metric: str, period: str, unit: str, source: str, excerpt: str, *,
           value_num=None, value_text=None, is_forecast=0, company_key=None, method="pdf_direct", note=None):
    dps.append({
        "metric": metric,
        "period": period,
        "unit": unit,
        "source": source,
        "excerpt": excerpt,
        "value_num": value_num,
        "value_text": value_text,
        "is_forecast": is_forecast,
        "company_key": company_key,
        "method": method,
        "note": note,
    })


def build_data_points() -> list[dict]:
    dps: list[dict] = []
    prismark_product_excerpt = "Prismark表：PCB市场产品结构的变化，2025E合计85,152百万美元、2030F合计123,348百万美元，2025E/2024为15.8%，2025-2030 CAGR为7.7%。"
    product_rows = [
        ("大宗商品/单双面等低端PCB市场规模", {2023: 7757, 2024: 7947, 2025: 8440, 2026: 8754, 2030: 9709}, 6.2, 2.8),
        ("多层板PCB市场规模", {2023: 26534, 2024: 27994, 2025: 33150, 2026: 37729, 2030: 48636}, 18.4, 8.0),
        ("HDI PCB市场规模", {2023: 10536, 2024: 12518, 2025: 15769, 2026: 18055, 2030: 24490}, 26.0, 9.2),
        ("封装基板市场规模", {2023: 12498, 2024: 12602, 2025: 14891, 2026: 17947, 2030: 24985}, 18.2, 10.9),
        ("柔性板FPC市场规模", {2023: 12191, 2024: 12504, 2025: 12903, 2026: 13295, 2030: 15527}, 3.2, 3.8),
        ("全球PCB总市场规模", {2023: 69517, 2024: 73565, 2025: 85152, 2026: 95780, 2030: 123348}, 15.8, 7.7),
    ]
    product_excerpts = {
        "大宗商品/单双面等低端PCB市场规模": "Prismark产品结构表：大宗商品/单双面等低端PCB 2025E为8,440百万美元，2030F为9,709百万美元，2025-2030 CAGR为2.8%。",
        "多层板PCB市场规模": "Prismark产品结构表：多层板PCB 2025E为33,150百万美元，2030F为48,636百万美元，2025-2030 CAGR为8.0%。",
        "HDI PCB市场规模": "Prismark产品结构表：HDI PCB 2025E为15,769百万美元，2030F为24,490百万美元，2025E同比增速26.0%，2025-2030 CAGR为9.2%。",
        "封装基板市场规模": "Prismark产品结构表：封装基板2025E为14,891百万美元，2030F为24,985百万美元，2025-2030 CAGR为10.9%。",
        "柔性板FPC市场规模": "Prismark产品结构表：柔性板FPC 2025E为12,903百万美元，2030F为15,527百万美元，2025-2030 CAGR为3.8%。",
        "全球PCB总市场规模": prismark_product_excerpt,
    }
    for metric, vals, yoy25, cagr in product_rows:
        product_excerpt = product_excerpts.get(metric, prismark_product_excerpt)
        for year, val in vals.items():
            add_dp(dps, metric, f"{year}{'E' if year == 2025 else 'F' if year in (2026, 2030) else ''}", "百万美元", "prismark", product_excerpt, value_num=val, is_forecast=1 if year >= 2025 else 0)
        add_dp(dps, f"{metric} 2025E同比增速", "2025E/2024", "%", "prismark", product_excerpt, value_num=yoy25, is_forecast=1)
        add_dp(dps, f"{metric} 2025-2030 CAGR", "2025E-2030F", "%", "prismark", product_excerpt, value_num=cagr, is_forecast=1)

    prismark_region_excerpt = "Prismark地区表：2025E中国PCB产值48,969百万美元、同比19.2%，2030F中国68,535百万美元；东南亚/其他2025E 7,218百万美元、2030F 13,642百万美元，CAGR 13.6%。"
    region_rows = [
        ("美洲PCB产值", {2023: 3206, 2024: 3493, 2025: 3796, 2026: 4029, 2030: 4781}, 7.5, 4.7),
        ("欧洲PCB产值", {2023: 1728, 2024: 1638, 2025: 1864, 2026: 1993, 2030: 2307}, 13.8, 4.4),
        ("日本PCB产值", {2023: 6078, 2024: 5840, 2025: 6499, 2026: 7257, 2030: 9468}, 11.3, 7.8),
        ("中国PCB产值", {2023: 37794, 2024: 41213, 2025: 48969, 2026: 55269, 2030: 68535}, 19.2, 7.0),
        ("韩国PCB产值", {2023: 6737, 2024: 6631, 2025: 6905, 2026: 7783, 2030: 10013}, 4.1, 7.7),
        ("台湾PCB产值", {2023: 8406, 2024: 8669, 2025: 9902, 2026: 11565, 2030: 14602}, 14.1, 8.1),
        ("东南亚及其他PCB产值", {2023: 5567, 2024: 6081, 2025: 7218, 2026: 7885, 2030: 13642}, 17.0, 13.6),
    ]
    for metric, vals, yoy25, cagr in region_rows:
        for year, val in vals.items():
            add_dp(dps, metric, f"{year}{'E' if year == 2025 else 'F' if year in (2026, 2030) else ''}", "百万美元", "prismark", prismark_region_excerpt, value_num=val, is_forecast=1 if year >= 2025 else 0)
        add_dp(dps, f"{metric} 2025E同比增速", "2025E/2024", "%", "prismark", prismark_region_excerpt, value_num=yoy25, is_forecast=1)
        add_dp(dps, f"{metric} 2025-2030 CAGR", "2025E-2030F", "%", "prismark", prismark_region_excerpt, value_num=cagr, is_forecast=1)

    top40_excerpt = "Prismark 2025年第四季度PCB供应商40强表：Top40合计2024年56,672百万美元、2025E 67,455百万美元，同比增长19.0%。"
    top40 = [
        ("臻鼎科技PCB收入", "zhen_ding", 5869, 9.9, 1),
        ("欣兴电子PCB收入", "unimicron", 4225, 17.5, 2),
        ("东山精密PCB收入", "dongshan", 3605, 4.5, 3),
        ("深南电路PCB收入", "shennan", 3295, 32.2, 4),
        ("TTM Technologies PCB收入", "ttm", 2906, 19.0, 5),
        ("沪电股份PCB收入", "wus", 2760, 40.8, 6),
        ("胜宏科技PCB收入", "shenghong", 2686, 79.9, 7),
        ("华通Compeq PCB收入", "compeq", 2446, 8.4, 8),
        ("健鼎科技PCB收入", "tripod", 2361, 15.2, 9),
        ("景旺电子PCB收入", "kinwong", 2100, 19.2, 11),
        ("AT&S PCB收入", None, 1933, 15.9, 12),
        ("世运电路PCB收入", "olympic", 752, 44.8, 34),
    ]
    for metric, ck, val, yoy, rank in top40:
        add_dp(dps, metric, "2025E", "百万美元", "prismark", top40_excerpt, value_num=val, is_forecast=1, company_key=ck)
        add_dp(dps, f"{metric} 2025E同比增速", "2025E/2024", "%", "prismark", top40_excerpt, value_num=yoy, is_forecast=1, company_key=ck)
        add_dp(dps, f"{metric} 全球排名", "2025E", "名", "prismark", top40_excerpt, value_num=rank, is_forecast=1, company_key=ck)
    add_dp(dps, "全球PCB供应商Top40合计收入", "2025E", "百万美元", "prismark", top40_excerpt, value_num=67455, is_forecast=1)
    add_dp(dps, "全球PCB供应商Top40合计收入同比", "2025E/2024", "%", "prismark", top40_excerpt, value_num=19.0, is_forecast=1)

    app_excerpt = "长江证券转引Prismark：2024年手机占比19%、产值138.86亿美元；服务器/存储占比15%、产值109.16亿美元、同比33.1%；汽车电子91.95亿美元、占13%；消费电子89.72亿美元、占12%。"
    apps = [
        ("手机PCB产值", 2024, 138.86, "亿美元"),
        ("手机PCB需求占比", 2024, 19.0, "%"),
        ("手机PCB产值同比", 2024, 6.1, "%"),
        ("服务器/存储PCB产值", 2024, 109.16, "亿美元"),
        ("服务器/存储PCB需求占比", 2024, 15.0, "%"),
        ("服务器/存储PCB产值同比", 2024, 33.1, "%"),
        ("汽车电子PCB产值", 2024, 91.95, "亿美元"),
        ("汽车电子PCB需求占比", 2024, 13.0, "%"),
        ("汽车电子PCB产值同比", 2024, 0.5, "%"),
        ("消费电子PCB产值", 2024, 89.72, "亿美元"),
        ("消费电子PCB需求占比", 2024, 12.0, "%"),
        ("消费电子PCB产值同比", 2024, -1.7, "%"),
        ("服务器/存储PCB 2024-2029 CAGR", "2024-2029E", 11.6, "%"),
    ]
    for metric, period, val, unit in apps:
        add_dp(dps, metric, str(period), unit, "changjiang_20250804", app_excerpt, value_num=val, is_forecast=1 if "2029" in str(period) else 0)

    guangfa_excerpt = "广发证券转引Prismark：2024年全球高多层板产值24.21亿美元、中国10.58亿美元、占43.7%；全球HDI 125.18亿美元、中国78.49亿美元、占62.7%。"
    for metric, val, unit in [
        ("全球18层以上高多层板产值", 24.21, "亿美元"),
        ("中国18层以上高多层板产值", 10.58, "亿美元"),
        ("中国18层以上高多层板产值占全球比重", 43.7, "%"),
        ("全球HDI产值", 125.18, "亿美元"),
        ("中国HDI产值", 78.49, "亿美元"),
        ("中国HDI产值占全球比重", 62.7, "%"),
        ("全球18层以上高多层板产值同比", 40.2, "%"),
        ("全球HDI产值同比", 18.8, "%"),
        ("中国18层以上高多层板产值同比", 67.4, "%"),
        ("中国HDI产值同比", 21.0, "%"),
    ]:
        add_dp(dps, metric, "2024", unit, "guangfa_20250901", guangfa_excerpt, value_num=val)

    server_excerpt = "广发证券：2023年全球服务器/数据存储PCB市场82.01亿美元、占11.8%；2024年109.16亿美元、占14.84%；2029E 189.21亿美元、占19.99%，2024-2029 CAGR 11.6%。"
    for year, val, share, forecast in [(2020, 58.76, 9.01, 0), (2023, 82.01, 11.80, 0), (2024, 109.16, 14.84, 0), (2029, 189.21, 19.99, 1)]:
        add_dp(dps, "全球服务器/数据存储PCB市场规模", f"{year}{'E' if forecast else ''}", "亿美元", "guangfa_20250901", server_excerpt, value_num=val, is_forecast=forecast)
        add_dp(dps, "全球服务器/数据存储PCB市场占比", f"{year}{'E' if forecast else ''}", "%", "guangfa_20250901", server_excerpt, value_num=share, is_forecast=forecast)
    add_dp(dps, "全球服务器/数据存储PCB市场2024-2029 CAGR", "2024-2029E", "%", "guangfa_20250901", server_excerpt, value_num=11.6, is_forecast=1)
    add_dp(dps, "全球AI服务器整机出货量", "2024", "万台", "guangfa_20250901", "广发证券：TrendForce数据，2024年全球AI服务器整机出货量将达167.2万台，同比增长38.4%。", value_num=167.2)
    add_dp(dps, "全球AI服务器整机出货同比", "2024", "%", "guangfa_20250901", "广发证券：TrendForce数据，2024年全球AI服务器整机出货量将达167.2万台，同比增长38.4%。", value_num=38.4)

    prismark_ai_excerpt = "Prismark：2025年服务器PCB/基板市场157亿美元，2025-2030 CAGR 17.2%；AI服务器PCB和基板中HLC/HLC+HDI约50%，封装基板约35%。"
    add_dp(dps, "服务器/存储/AI PCB及基板市场规模", "2025E", "亿美元", "prismark", prismark_ai_excerpt, value_num=157, is_forecast=1)
    add_dp(dps, "服务器/存储/AI PCB及基板市场2025-2030 CAGR", "2025E-2030F", "%", "prismark", prismark_ai_excerpt, value_num=17.2, is_forecast=1)
    add_dp(dps, "AI服务器PCB和基板中HLC/HLC+HDI占比", "2025E", "%", "prismark", prismark_ai_excerpt, value_num=50, is_forecast=1)
    add_dp(dps, "AI服务器PCB和基板中封装基板占比", "2025E", "%", "prismark", prismark_ai_excerpt, value_num=35, is_forecast=1)

    xingye_excerpt = "兴业证券：NVL72机柜18个Compute tray和9个Switch tray；单个compute tray由2块OAM组成，每块OAM配置2颗GPU和1颗CPU，OAM PCB为22层5阶HDI、CCL使用M8。"
    for metric, val, unit in [
        ("NVIDIA NVL72 Compute tray数量", 18, "个/机柜"),
        ("NVIDIA NVL72 Switch tray数量", 9, "个/机柜"),
        ("NVL72单个compute tray OAM数量", 2, "块"),
        ("NVL72单块OAM GPU数量", 2, "颗"),
        ("NVL72单块OAM CPU数量", 1, "颗"),
        ("GB200 OAM PCB层数", 22, "层"),
        ("GB200 OAM HDI阶数", 5, "阶"),
    ]:
        add_dp(dps, metric, "GB200/NVL72", unit, "xingye_20250811", xingye_excerpt, value_num=val)
    add_dp(dps, "GB200 OAM CCL材料等级", "GB200/NVL72", "文本", "xingye_20250811", xingye_excerpt, value_text="M8材料")
    add_dp(dps, "AWS Trainium2 UBB PCB层数", "AWS T2", "层", "xingye_20250811", "兴业证券：AWS T2 rack包含Compute Tray，UBB是26层高多层板，采用M8材料；单个Rack包括16个Compute Tray和5个Switch Tray，对应32颗Trainium2芯片。", value_num=26)
    add_dp(dps, "AWS Trainium2单Rack Compute Tray数量", "AWS T2", "个", "xingye_20250811", "兴业证券：单个Rack包括16个Compute Tray和5个Switch Tray，对应32颗Trainium2芯片。", value_num=16)
    add_dp(dps, "AWS Trainium2单Rack Switch Tray数量", "AWS T2", "个", "xingye_20250811", "兴业证券：单个Rack包括16个Compute Tray和5个Switch Tray，对应32颗Trainium2芯片。", value_num=5)
    add_dp(dps, "AWS Trainium2单Rack芯片数量", "AWS T2", "颗", "xingye_20250811", "兴业证券：单个Rack包括16个Compute Tray和5个Switch Tray，对应32颗Trainium2芯片。", value_num=32)
    add_dp(dps, "CoWoP SLP线宽线距下限", "Rubin Ultra探索方案", "微米", "xingye_20250811", "兴业证券：SLP为更高规格的HDI，最低可以做到15-18μm；现HDI线宽线距约50μm，IC载板约10μm。", value_num=15)
    add_dp(dps, "传统HDI线宽线距约值", "Rubin Ultra探索方案", "微米", "xingye_20250811", "兴业证券：SLP为更高规格的HDI，最低可以做到15-18μm；现HDI线宽线距约50μm，IC载板约10μm。", value_num=50)
    add_dp(dps, "IC载板线宽线距约值", "Rubin Ultra探索方案", "微米", "xingye_20250811", "兴业证券：SLP为更高规格的HDI，最低可以做到15-18μm；现HDI线宽线距约50μm，IC载板约10μm。", value_num=10)
    add_dp(dps, "全球算力PCB需求规模", "2025E", "亿元人民币", "xingye_20250811", "兴业证券测算：2025-2027年全球算力PCB需求规模分别达到502、848和1226亿元，增速80%、69%、45%。", value_num=502, is_forecast=1)
    add_dp(dps, "全球算力PCB需求规模", "2026E", "亿元人民币", "xingye_20250811", "兴业证券测算：2025-2027年全球算力PCB需求规模分别达到502、848和1226亿元，增速80%、69%、45%。", value_num=848, is_forecast=1)
    add_dp(dps, "全球算力PCB需求规模", "2027E", "亿元人民币", "xingye_20250811", "兴业证券测算：2025-2027年全球算力PCB需求规模分别达到502、848和1226亿元，增速80%、69%、45%。", value_num=1226, is_forecast=1)
    add_dp(dps, "全球ASIC服务器PCB需求规模", "2027E", "亿元人民币", "xingye_20250811", "兴业证券测算：ASIC服务器PCB需求2024年不超过百亿元，2027年有望接近600亿元。", value_num=600, is_forecast=1)

    material_excerpt = "华西证券：覆铜板成本占PCB生产成本30%-40%；覆铜板自身成本中铜箔42.1%、树脂26.1%、玻纤布19.1%，合计87.3%。"
    for metric, val, unit in [
        ("覆铜板成本占PCB生产成本下限", 30, "%"),
        ("覆铜板成本占PCB生产成本上限", 40, "%"),
        ("覆铜板成本中铜箔占比", 42.1, "%"),
        ("覆铜板成本中树脂占比", 26.1, "%"),
        ("覆铜板成本中玻纤布占比", 19.1, "%"),
        ("覆铜板三大主材成本合计占比", 87.3, "%"),
    ]:
        add_dp(dps, metric, "2026", unit, "huaxi_20260524", material_excerpt, value_num=val)
    add_dp(dps, "PCB铜箔在覆铜板CCL原材料成本占比下限", "2025", "%", "xingye_20250811", "兴业证券跟踪：铜冠铜箔招股书援引GGII，PCB铜箔在覆铜板CCL原材料成本中占比30%-50%。", value_num=30)
    add_dp(dps, "PCB铜箔在覆铜板CCL原材料成本占比上限", "2025", "%", "xingye_20250811", "兴业证券跟踪：铜冠铜箔招股书援引GGII，PCB铜箔在覆铜板CCL原材料成本中占比30%-50%。", value_num=50)

    capex_excerpt = "广发证券：东山精密投资不超过10亿美元用于高端PCB扩产；鹏鼎追加约20亿元，高雄IC载板/HDI+HLC，25-26年capex上修至70亿元；沪电约43亿元高端PCB；胜宏2025投资计划30亿元。"
    for metric, val, unit, ck in [
        ("东山精密高端PCB扩产投资上限", 10, "亿美元", "dongshan"),
        ("鹏鼎控股高雄IC载板/HDI+HLC追加投资", 20, "亿元人民币", "avary"),
        ("鹏鼎控股25-26年capex上修金额", 70, "亿元人民币", "avary"),
        ("沪电股份高端PCB投资计划", 43, "亿元人民币", "wus"),
        ("胜宏科技2025扩产投资计划", 30, "亿元人民币", "shenghong"),
    ]:
        add_dp(dps, metric, "2025-2026", unit, "guangfa_20250901", capex_excerpt, value_num=val, is_forecast=1, company_key=ck)

    # Company official financial and technology points.
    company_points = [
        ("shenghong", "shenghong_annual", "胜宏科技2025年报：2025年营业收入19,292,313,457.36元、归母净利润4,311,988,274.40元；研发费用777,643,427.06元；经营活动现金流量净额4,602,652,783.97元。", [
            ("胜宏科技营业收入", "2025", 192.9231, "亿元人民币"),
            ("胜宏科技营业收入同比", "2025", 79.77, "%"),
            ("胜宏科技归母净利润", "2025", 43.1199, "亿元人民币"),
            ("胜宏科技归母净利润同比", "2025", 273.52, "%"),
            ("胜宏科技研发费用", "2025", 7.7764, "亿元人民币"),
            ("胜宏科技经营活动现金流量净额", "2025", 46.0265, "亿元人民币"),
            ("胜宏科技高多层板制造能力", "2025", 100, "层以上"),
            ("胜宏科技量产HDI层数", "2025", 24, "层"),
            ("胜宏科技量产HDI阶数", "2025", 6, "阶"),
            ("胜宏科技高阶HDI技术层数", "2025", 30, "层"),
            ("胜宏科技高阶HDI技术阶数", "2025", 10, "阶"),
        ]),
        ("wus", "wus_annual", "沪电股份2025年报：公司整体营业收入约189.45亿元、归母净利润约38.22亿元；PCB业务收入181.43亿元、毛利率36.91%；研发投入约11.4亿元，泰国数据通讯事业部超70%海外客户完成认证、2026Q1产能利用率超90%。", [
            ("沪电股份营业收入", "2025", 189.4522, "亿元人民币"),
            ("沪电股份营业收入同比", "2025", 42.00, "%"),
            ("沪电股份归母净利润", "2025", 38.2231, "亿元人民币"),
            ("沪电股份归母净利润同比", "2025", 47.74, "%"),
            ("沪电股份PCB业务收入", "2025", 181.43, "亿元人民币"),
            ("沪电股份PCB业务毛利率", "2025", 36.91, "%"),
            ("沪电股份研发投入", "2025", 11.4, "亿元人民币"),
            ("沪电股份经营活动现金流量净额", "2025", 38.7197, "亿元人民币"),
            ("沪电股份泰国数据通讯事业部海外客户认证完成比例", "2026Q1", 70, "%以上"),
            ("沪电股份泰国数据通讯事业部产能利用率", "2026Q1", 90, "%以上"),
        ]),
        ("shennan", "shennan_annual", "深南电路2025年报：营业总收入236.47亿元、归母净利润32.76亿元；PCB业务143.59亿元、毛利率35.53%；封装基板41.48亿元、毛利率22.58%；研发费用15.914亿元。", [
            ("深南电路营业收入", "2025", 236.4698, "亿元人民币"),
            ("深南电路营业收入同比", "2025", 32.05, "%"),
            ("深南电路归母净利润", "2025", 32.7574, "亿元人民币"),
            ("深南电路归母净利润同比", "2025", 74.47, "%"),
            ("深南电路PCB业务收入", "2025", 143.59, "亿元人民币"),
            ("深南电路PCB业务毛利率", "2025", 35.53, "%"),
            ("深南电路封装基板业务收入", "2025", 41.48, "亿元人民币"),
            ("深南电路封装基板业务毛利率", "2025", 22.58, "%"),
            ("深南电路电子装联业务收入", "2025", 30.75, "亿元人民币"),
            ("深南电路研发费用", "2025", 15.9141, "亿元人民币"),
            ("深南电路FC-BGA量产层数", "2025", 22, "层及以下"),
            ("深南电路FC-BGA研发打样层数", "2025", 24, "层及以上"),
        ]),
        ("avary", "avary_annual", "鹏鼎控股2025年报：2025年营业收入391.47亿元、归母净利润37.38亿元；汽车/服务器用板21.19亿元、同比106.67%、毛利率21.55%；研发投入24.59亿元，占收入6.28%。", [
            ("鹏鼎控股营业收入", "2025", 391.4701, "亿元人民币"),
            ("鹏鼎控股营业收入同比", "2025", 11.40, "%"),
            ("鹏鼎控股归母净利润", "2025", 37.3784, "亿元人民币"),
            ("鹏鼎控股归母净利润同比", "2025", 3.25, "%"),
            ("鹏鼎控股通讯用板业务收入", "2025", 254.37, "亿元人民币"),
            ("鹏鼎控股消费电子及计算机用板收入", "2025", 112.87, "亿元人民币"),
            ("鹏鼎控股汽车/服务器用板收入", "2025", 21.19, "亿元人民币"),
            ("鹏鼎控股汽车/服务器用板收入同比", "2025", 106.67, "%"),
            ("鹏鼎控股汽车/服务器用板毛利率", "2025", 21.55, "%"),
            ("鹏鼎控股研发投入", "2025", 24.59, "亿元人民币"),
            ("鹏鼎控股研发投入占收入比", "2025", 6.28, "%"),
            ("鹏鼎控股AI服务器类产品收入增速", "2025", 100, "%以上"),
            ("鹏鼎控股淮安高阶PCB产能计划投入", "2025H2-2028", 80, "亿元人民币"),
            ("鹏鼎控股高端PCB项目生产基地拟投资", "2026", 110, "亿元人民币"),
        ]),
        ("dongshan", "dongshan_annual", "东山精密2025年报：2025年营业收入401.25亿元、净利润13.86亿元、经营性现金净流入53.07亿元；加快HDI和高多层PCB产能，适配AI数据中心需求。", [
            ("东山精密营业收入", "2025", 401.2486, "亿元人民币"),
            ("东山精密营业收入同比", "2025", 9.12, "%"),
            ("东山精密归母净利润", "2025", 13.8607, "亿元人民币"),
            ("东山精密归母净利润同比", "2025", 27.67, "%"),
            ("东山精密经营活动现金流量净额", "2025", 53.0714, "亿元人民币"),
            ("东山精密计算机通信和其他电子业务收入", "2025", 396.4373, "亿元人民币"),
            ("东山精密计算机通信和其他电子业务毛利率", "2025", 13.85, "%"),
            ("东山精密研发费用", "2025", 14.1723, "亿元人民币"),
        ]),
        ("kinwong", "kinwong_annual", "景旺电子2025年报：2025年收入153.08亿元、归母净利润12.31亿元；PCB业务收入143.73亿元、毛利率16.95%；AI基础设施产品包括40层以上HLC、6阶22层HDI、14层mSAP HDI。", [
            ("景旺电子营业收入", "2025", 153.0805, "亿元人民币"),
            ("景旺电子营业收入同比", "2025", 20.92, "%"),
            ("景旺电子归母净利润", "2025", 12.3097, "亿元人民币"),
            ("景旺电子归母净利润同比", "2025", 5.30, "%"),
            ("景旺电子PCB业务收入", "2025", 143.7262, "亿元人民币"),
            ("景旺电子PCB业务毛利率", "2025", 16.95, "%"),
            ("景旺电子经营活动现金流量净额", "2025", 19.3122, "亿元人民币"),
            ("景旺电子研发费用", "2025", 9.2993, "亿元人民币"),
            ("景旺电子AI基础设施HLC层数能力", "2025", 40, "层以上"),
            ("景旺电子AI基础设施HDI层数", "2025", 22, "层"),
            ("景旺电子AI基础设施HDI阶数", "2025", 6, "阶"),
            ("景旺电子mSAP HDI层数", "2025", 14, "层"),
            ("景旺电子9阶HDI客户认证周期", "2025", 90, "天"),
        ]),
        ("olympic", "olympic_annual", "世运电路2025年报：2025年营业收入55.77亿元、归母净利润6.84亿元；PCB业务收入51.58亿元、毛利率14.73%；2026Q1建成芯片内嵌式PCB中试线。", [
            ("世运电路营业收入", "2025", 55.7689, "亿元人民币"),
            ("世运电路营业收入同比", "2025", 11.05, "%"),
            ("世运电路归母净利润", "2025", 6.84, "亿元人民币"),
            ("世运电路归母净利润同比", "2025", 1.37, "%"),
            ("世运电路PCB业务收入", "2025", 51.5804, "亿元人民币"),
            ("世运电路PCB业务毛利率", "2025", 14.73, "%"),
            ("世运电路经营活动现金流量净额", "2025", 9.2072, "亿元人民币"),
            ("世运电路研发费用", "2025", 2.3138, "亿元人民币"),
            ("世运电路AI服务器线路板量产能力", "2025", 28, "层"),
            ("世运电路HDI量产能力", "2025", 5, "阶"),
        ]),
    ]
    company_metric_excerpt_overrides = {
        "胜宏科技高多层板制造能力": "胜宏科技2025年报披露，公司具备100层以上高多层板制造能力，该条用于验证高端HLC制造上限，不能用财务摘要替代。",
        "胜宏科技量产HDI层数": "胜宏科技2025年报披露，公司是全球首批实现6阶24层HDI大规模生产的PCB制造企业；该条用于量产HDI层数验证。",
        "胜宏科技量产HDI阶数": "胜宏科技2025年报披露，公司是全球首批实现6阶24层HDI大规模生产的PCB制造企业；该条用于量产HDI阶数验证。",
        "胜宏科技高阶HDI技术层数": "胜宏科技2025年报披露，公司已具备10阶30层HDI和16层Any-layer HDI技术能力；该条用于高阶HDI技术层数验证。",
        "胜宏科技高阶HDI技术阶数": "胜宏科技2025年报披露，公司已具备10阶30层HDI和16层Any-layer HDI技术能力；该条用于高阶HDI技术阶数验证。",
        "沪电股份泰国数据通讯事业部海外客户认证完成比例": "沪电股份2025年报披露，泰国生产基地数据通讯事业部已有超过70%海外客户完成认证；该条用于海外客户准入验证。",
        "沪电股份泰国数据通讯事业部产能利用率": "沪电股份2025年报披露，泰国生产基地数据通讯事业部2026年一季度产能利用率超过90%；该条用于海外产能爬坡验证。",
        "深南电路FC-BGA量产层数": "深南电路2025年报披露，FC-BGA封装基板22层及以下产品已实现量产；该条用于量产载板层数验证。",
        "深南电路FC-BGA研发打样层数": "深南电路2025年报披露，FC-BGA封装基板24层及以上产品处于研发打样阶段；该条用于高层数载板研发边界验证。",
        "鹏鼎控股AI服务器类产品收入增速": "鹏鼎控股2025年报披露，AI服务器类产品收入较2024年增长超过1倍；该条用于判断AI PCB业务是否从线索进入收入兑现。",
        "鹏鼎控股淮安高阶PCB产能计划投入": "鹏鼎控股2025年报披露，2025年下半年至2028年计划在淮安投入80亿元扩充高阶PCB产能；该条用于高阶PCB产能期权验证。",
        "鹏鼎控股高端PCB项目生产基地拟投资": "鹏鼎控股公告披露，公司拟投资110亿元建设高端PCB项目生产基地；该条用于高端PCB扩产规模验证。",
        "景旺电子AI基础设施HLC层数能力": "景旺电子2025年报披露，AI基础设施产品包括40层以上HLC；该条用于高多层板规格能力验证。",
        "景旺电子AI基础设施HDI层数": "景旺电子2025年报披露，AI基础设施产品包括6阶22层HDI；该条用于高阶HDI层数验证。",
        "景旺电子AI基础设施HDI阶数": "景旺电子2025年报披露，AI基础设施产品包括6阶22层HDI；该条用于高阶HDI阶数验证。",
        "景旺电子mSAP HDI层数": "景旺电子2025年报披露，AI基础设施产品包括14层mSAP HDI；该条用于mSAP HDI层数验证。",
        "景旺电子9阶HDI客户认证周期": "景旺电子2025年报披露，9阶HDI产品客户认证周期约90天；该条用于高阶HDI认证周期验证。",
        "世运电路AI服务器线路板量产能力": "世运电路2025年报披露，公司具备28层AI服务器线路板量产能力；该条用于AI服务器板层数能力验证。",
        "世运电路HDI量产能力": "世运电路2025年报披露，公司具备5阶HDI量产能力；该条用于HDI量产阶数验证。",
    }
    for ck, source, excerpt, rows in company_points:
        for metric, period, val, unit in rows:
            metric_excerpt = company_metric_excerpt_overrides.get(metric, excerpt)
            add_dp(dps, metric, period, unit, source, metric_excerpt, value_num=val, company_key=ck)

    q1_rows = [
        ("shenghong", "cms_shenghong_20260505", "招商证券转引胜宏科技2026Q1季报：营收55.19亿元、同比+28.0%、环比+6.7%；归母净利润12.88亿元、同比+39.95%；毛利率34.46%，净利率23.34%。", [
            ("胜宏科技营业收入", 55.19, "亿元人民币"),
            ("胜宏科技归母净利润", 12.88, "亿元人民币"),
            ("胜宏科技毛利率", 34.46, "%"),
            ("胜宏科技净利率", 23.34, "%"),
        ]),
        ("dongshan", "kaiyuan_dongshan_20260430", "开源证券转引东山精密2026一季报：2026Q1营收131.38亿元、归母净利润11.10亿元、毛利率19.33%、净利率8.56%。", [
            ("东山精密营业收入", 131.38, "亿元人民币"),
            ("东山精密归母净利润", 11.10, "亿元人民币"),
            ("东山精密毛利率", 19.33, "%"),
            ("东山精密净利率", 8.56, "%"),
        ]),
        ("wus", "dongguan_20260427", "东莞证券转引公司公告：沪电股份2026Q1营业收入62.14亿元，同比增长53.91%；归母净利润12.42亿元，同比增长62.90%。", [
            ("沪电股份营业收入", 62.14, "亿元人民币"),
            ("沪电股份归母净利润", 12.42, "亿元人民币"),
        ]),
        ("shennan", "dongguan_20260427", "东莞证券转引公司公告：深南电路2026Q1营业收入65.96亿元，同比增长37.90%；归母净利润8.50亿元，同比增长73.01%。", [
            ("深南电路营业收入", 65.96, "亿元人民币"),
            ("深南电路归母净利润", 8.50, "亿元人民币"),
        ]),
        ("guanghe", "dongguan_20260511", "东莞证券转引广合科技公告：2026Q1营业收入19.14亿元，同比增长71.35%；归母净利润3.93亿元，同比增长63.31%。", [
            ("广合科技营业收入", 19.14, "亿元人民币"),
            ("广合科技归母净利润", 3.93, "亿元人民币"),
        ]),
    ]
    for ck, source, excerpt, rows in q1_rows:
        for metric, val, unit in rows:
            add_dp(dps, metric, "2026Q1", unit, source, excerpt, value_num=val, company_key=ck)

    fx = MARKET_SNAPSHOT.get("_fx") or FX
    market_snapshot_excerpt = (
        f"Tushare/yfinance快照：{TODAY}读取价格、市值、PE、PB、PS、毛利率、净利率和现金流；"
        f"汇率USDCNY={fx.get('USD')}、TWDCNY={fx.get('TWD')}、JPYCNY={fx.get('JPY')}。"
    )
    for ck in COMPANIES:
        yf = market_for_company(ck)
        if not yf or yf.get("error"):
            continue
        excerpt = (
            f"{market_snapshot_excerpt} {COMPANIES[ck]['name']}市值={display_cny_usd(yf.get('market_cap_cny'), yf.get('market_cap_usd'))}，"
            f"PE_TTM={yf.get('pe_ttm')}，PB={yf.get('pb')}，PS_TTM={yf.get('ps_ttm')}，"
            f"毛利率={yf.get('gross_margin')}%，净利率={yf.get('net_margin')}%。"
        )
        if yf.get("market_cap_cny") is not None:
            add_dp(dps, f"{COMPANIES[ck]['name']}市值", TODAY, "亿元人民币", "yfinance_20260706", excerpt, value_num=yf["market_cap_cny"], company_key=ck, method="web_fetch")
        for field, metric in [("pe_ttm", "PE TTM"), ("pb", "PB"), ("ps_ttm", "PS TTM")]:
            if yf.get(field) is not None:
                add_dp(dps, f"{COMPANIES[ck]['name']}{metric}", TODAY, "倍", "yfinance_20260706", excerpt, value_num=yf[field], company_key=ck, method="web_fetch")

    add_dp(dps, "PCB行业2026Q1聚合营业收入", "2026Q1", "亿元人民币", "dongguan_20260512", "东莞证券：PCB行业Q1营业收入646.57亿元，同比增长28.99%；归母净利润64.83亿元，同比增长38.49%；毛利率24.47%，净利率9.96%。", value_num=646.57)
    add_dp(dps, "PCB行业2026Q1聚合营业收入同比", "2026Q1", "%", "dongguan_20260512", "东莞证券：PCB行业Q1营业收入646.57亿元，同比增长28.99%；归母净利润64.83亿元，同比增长38.49%；毛利率24.47%，净利率9.96%。", value_num=28.99)
    add_dp(dps, "PCB行业2026Q1聚合归母净利润", "2026Q1", "亿元人民币", "dongguan_20260512", "东莞证券：PCB行业Q1营业收入646.57亿元，同比增长28.99%；归母净利润64.83亿元，同比增长38.49%；毛利率24.47%，净利率9.96%。", value_num=64.83)
    add_dp(dps, "PCB行业2026Q1聚合归母净利润同比", "2026Q1", "%", "dongguan_20260512", "东莞证券：PCB行业Q1营业收入646.57亿元，同比增长28.99%；归母净利润64.83亿元，同比增长38.49%；毛利率24.47%，净利率9.96%。", value_num=38.49)
    add_dp(dps, "PCB行业2026Q1聚合毛利率", "2026Q1", "%", "dongguan_20260512", "东莞证券：PCB行业Q1毛利率24.47%，同比提升2.87个百分点；净利率9.96%，同比提升0.72个百分点。", value_num=24.47)
    add_dp(dps, "PCB行业2026Q1聚合净利率", "2026Q1", "%", "dongguan_20260512", "东莞证券：PCB行业Q1毛利率24.47%，同比提升2.87个百分点；净利率9.96%，同比提升0.72个百分点。", value_num=9.96)

    return dps


def write_data_points(conn: sqlite3.Connection, industry_id: int, source_ids: dict, company_ids: dict) -> int:
    conn.execute(
        "delete from industry_data_point where industry_id=? and note like ?",
        (industry_id, f"{RUN_TAG}%"),
    )
    count = 0
    for item in build_data_points():
        company_id = company_ids.get(item.get("company_key")) if item.get("company_key") else None
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
            as_of_date=item["period"] if item["period"].startswith("2026-") else None,
            sentiment="中性",
            note=note,
            company_id=company_id,
        )
        count += 1
    return count


def write_source_entity_links(conn: sqlite3.Connection, source_ids: dict, company_ids: dict, industry_id: int | None = None) -> None:
    if source_ids and company_ids:
        conn.execute(
            f"delete from source_entity where source_id in ({','.join(['?'] * len(source_ids))}) and entity_type='company'",
            list(source_ids.values()),
        )
    for ck, meta in COMPANIES.items():
        sid = source_ids.get(meta.get("source"))
        cid = company_ids.get(ck)
        if sid and cid:
            conn.execute(
                """
                insert into source_entity(source_id, entity_type, entity_id, coverage)
                values(?,?,?,?)
                """,
                (sid, "company", str(cid), "主要覆盖"),
            )
    if industry_id is not None and source_ids:
        conn.execute(
            "delete from source_entity where entity_type='industry' and entity_id=?",
            (str(industry_id),),
        )
        for sid in sorted(set(source_ids.values())):
            conn.execute(
                """
                insert into source_entity(source_id, entity_type, entity_id, coverage)
                values(?,?,?,?)
                """,
                (sid, "industry", str(industry_id), "主要覆盖"),
            )


def write_industry_relations(conn: sqlite3.Connection, industry_id: int, source_ids: dict) -> None:
    conn.execute("delete from industry_relation where note like ?", (f"{RUN_TAG}%",))
    industries = {r[1]: r[0] for r in conn.execute("select id,name from industry").fetchall()}
    rels = []
    if "半导体材料" in industries:
        rels.append((industries["半导体材料"], industry_id, "供应", 0.35, "覆铜板、铜箔、树脂、玻纤布、半固化片等是PCB性能和成本核心，覆铜板约占PCB生产成本30%-40%。", source_ids["huaxi_20260524"]))
    if "AI服务器" in industries:
        rels.append((industry_id, industries["AI服务器"], "配套", None, "AI服务器/HPC/高速交换机推动HLC、HDI、SLP和mSAP价值量提升。", source_ids["guangfa_20250901"]))
    if "通信" in industries:
        rels.append((industry_id, industries["通信"], "配套", None, "800G/1.6T/224G SerDes推动高频高速和高层板需求。", source_ids["shouchuang_20260415"]))
    for upstream, downstream, rtype, cost_share, note, sid in rels:
        conn.execute(
            """
            insert into industry_relation(upstream_id, downstream_id, relation_type, cost_share, source_id, note)
            values(?,?,?,?,?,?)
            """,
            (upstream, downstream, rtype, cost_share, sid, f"{RUN_TAG}: {note}"),
        )


def append_route_record() -> None:
    path = ROOT / "docs" / "行业接入记录.md"
    text = path.read_text(encoding="utf-8")
    line = (
        f"| PCB制造 | {TODAY} | **B** | `PCB制造产业研究数据整理Prompt.md`(项目根目录) | "
        "147 | 根目录命中PCB制造研究员prompt，内容明确要求七栏目、公司透视、2025年报和2026Q1；papers/pcb含147份PDF，按B轨执行并写入research.db |\n"
    )
    if "| PCB制造 |" not in text:
        lines = text.splitlines(keepends=True)
        insert_at = len(lines)
        for i, ln in enumerate(lines):
            if ln.startswith("| 既有 A 轨"):
                insert_at = i
                break
        lines.insert(insert_at, line)
        path.write_text("".join(lines), encoding="utf-8")


def source_ref(source_ids: dict, key: str) -> str:
    return f"^src:{source_ids[key]}"


def write_docs(industry_id: int, source_ids: dict, company_ids: dict) -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    s = lambda key: source_ref(source_ids, key)
    company_url = f"/industry/{industry_id}/companies"
    val_url = f"/industry/{industry_id}/valuation"

    main = f"""---
title: PCB制造
industry: PCB制造
updated: {TODAY}
track: B
prompt: PCB制造产业研究数据整理Prompt.md
core_dynamic: "AI服务器、高速网络和先进封装边界变化把PCB从传统连接载体推向高层数、高密度、高速材料和半导体级工艺平台。"
---

# PCB制造

## 0. 口径和一句话结论

本文的 PCB 制造只指裸板制造和封装基板/类载板等相邻板级载体，不把 PCB 设备、CCL/铜箔/玻纤布/树脂等上游材料，也不把 SMT/电子装联当作本行业收入主体。上游材料只作为成本、供给和性能约束进入分析；电子装联只在深南电路等公司口径中单独标注，不混入 PCB 裸板收入。

一句话结论：PCB 制造的机会不是“电子终端复苏”这么粗，而是 AI 服务器、HPC、高速交换机、光模块和先进封装边界变化把 PCB 规格从普通多层板推向 HLC、HDI、SLP、mSAP 和 CoWoP 探索。Prismark 将 2025E 全球 PCB 总市场上调到 851.52 亿美元、同比 15.8%，2030F 达 1233.48 亿美元；结构上，多层板、HDI 和封装基板显著快于柔性板和低端板 {s('prismark')}。中国 2025E PCB 产值 489.69 亿美元、同比 19.2%，仍是最大且增速最快的核心产地之一，但东南亚/其他地区 2025-2030 CAGR 13.6%，说明全球客户的 China+1 和海外交付正在同步抬高产能布局门槛 {s('prismark')}。

## 1. 产业链拆解

PCB 制造处在“材料/耗材 → 裸板制造 → 电子系统/服务器/汽车/通信”的中游。上游包括覆铜板、半固化片、铜球、铜箔、干膜、油墨、金盐等；中游通过开料、内层图形、蚀刻、棕化、层压、钻孔、沉铜、电镀、外层图形、阻焊、表面处理、外形加工、电测和成品检验，把材料加工成裸板或相邻载体 {s('shouchuang_20260415')}。下游包括 AI 服务器、HPC、交换机、光模块、手机、汽车电子、工控、医疗和航空航天。

覆铜板是最关键的成本和性能锚。华西证券整理口径显示，覆铜板占 PCB 生产成本 30%-40%，其自身成本中铜箔 42.1%、树脂 26.1%、玻纤布 19.1%，三项合计 87.3% {s('huaxi_20260524')}。这意味着 AI PCB 涨价不是板厂单方面提价，而是材料、制程、良率和客户认证共同推动；如果材料涨价快于板厂传导，利润会向上游 CCL/铜箔转移，反之高端板厂可用客户认证和交付稀缺性保住毛利。

## 2. 市场空间和结构

| 指标 | 2024 | 2025E | 2030F | 2025E同比 | 2025-2030 CAGR | 解读 |
|---|---:|---:|---:|---:|---:|---|
| 全球PCB总市场 | 735.65亿美元 | 851.52亿美元 | 1233.48亿美元 | 15.8% | 7.7% | 2025不是弱复苏，是AI基础设施把周期拉成结构性扩张 {s('prismark')} |
| 多层板 | 279.94亿美元 | 331.50亿美元 | 486.36亿美元 | 18.4% | 8.0% | HLC和高速网络是主要增量 {s('prismark')} |
| HDI | 125.18亿美元 | 157.69亿美元 | 244.90亿美元 | 26.0% | 9.2% | 高阶HDI从手机迁移到AI服务器/OAM/光模块 {s('prismark')} |
| 封装基板 | 126.02亿美元 | 148.91亿美元 | 249.85亿美元 | 18.2% | 10.9% | ABF/FCBGA仍是先进封装核心，CoWoP是中长期变量 {s('prismark')} |
| 柔性板 | 125.04亿美元 | 129.03亿美元 | 155.27亿美元 | 3.2% | 3.8% | 消费电子复苏但成长斜率低于AI高端板 {s('prismark')} |

应用端看，2024年服务器/存储 PCB 市场 109.16 亿美元、同比 33.1%，占比 15%，已成为增长最快的下游；手机仍占 19%、138.86 亿美元，但增速只有 6.1%；汽车 91.95 亿美元、占 13%、同比 0.5%；消费电子 89.72 亿美元、占 12%、同比下降 1.7% {s('changjiang_20250804')}。广发证券转引 Prismark 进一步给出，服务器/数据存储 PCB 2024-2029 CAGR 为 11.6%，2029E 达 189.21 亿美元、占比 19.99% {s('guangfa_20250901')}。因此 Q2 的正确读法是：总市场增长重要，但更重要的是服务器/数据存储、高阶HDI、HLC和封装基板把利润池重新切分。

## 3. AI服务器为何改变PCB价值量

AI 服务器不是把传统服务器数量放大，而是板级架构发生变化。GB200/NVL72 机柜含 18 个 Compute tray 和 9 个 Switch tray；一个 Compute tray 由 2 块 OAM 组成，单块 OAM 配 2 颗 GPU 和 1 颗 CPU，OAM PCB 为 22 层 5 阶 HDI，使用 M8 材料 {s('xingye_20250811')}。AWS Trainium2 rack 也采用类似结构，UBB 为 26 层高多层板并使用 M8，单 Rack 含 16 个 Compute Tray、5 个 Switch Tray、32 颗 Trainium2 芯片 {s('xingye_20250811')}。

更高一层的变化是 CoWoP/SLP/mSAP。Prismark 描述 CoWoP 目标是将“芯片+中介层”直接键合到先进平台 PCB 上，省去基板和焊球，并利用 mSAP 将 RDL 中介层嵌入 SLP，线宽线距可达约 15 微米 {s('prismark')}。兴业证券同时提醒 CoWoP 仍在探索，优势是互连路径更短、电源完整性更好、可能绕开有机基板瓶颈，缺点是主板工艺、返修、良率和系统协同要求陡升 {s('xingye_20250811')}。所以 CoWoP 不应被写成已确定放量的收入，而应作为“PCB价值边界可能上移”的验证项。

## 4. 竞争格局

Prismark 2025E 供应商 40 强显示，Top40 合计收入 674.55 亿美元、同比 19.0%；臻鼎 58.69 亿美元第一，欣兴 42.25 亿美元第二，东山精密 36.05 亿美元第三，深南 32.95 亿美元第四，TTM 29.06 亿美元第五，沪电 27.60 亿美元、同比 40.8%，胜宏 26.86 亿美元、同比 79.9% {s('prismark')}。这个排序说明两件事：第一，PCB 仍是全球分散竞争，头部份额并未形成半导体设备那种寡头；第二，AI高端板把增速从传统规模厂转向具备高层数、HDI、材料加工和客户认证能力的厂商。

| 公司 | 2025E收入/2025收入 | 核心位置 | 关键验证 |
|---|---:|---|---|
| 胜宏科技 | Prismark 26.86亿美元；2025营收192.92亿元 | AI服务器高端板弹性最强 | 100层以上HLC、6阶24层HDI、10阶30层HDI，2026Q1利润率继续提升 {s('shenghong_annual')} {s('cms_shenghong_20260505')} |
| 沪电股份 | Prismark 27.60亿美元；PCB业务181.43亿元 | 数据通信/HLC龙头 | PCB业务毛利率36.91%，泰国数据通讯2026Q1产能利用率超90% {s('wus_annual')} |
| 深南电路 | Prismark 32.95亿美元；PCB业务143.59亿元 | PCB+封装基板平台 | PCB毛利率35.53%，FC-BGA 22层及以下量产、24层以上打样 {s('shennan_annual')} |
| 鹏鼎控股 | 2025营收391.47亿元 | FPC龙头向服务器IHDI/HLC迁移 | 汽车/服务器用板收入21.19亿元、同比106.67%，AI服务器产品收入较2024增长超1倍 {s('avary_annual')} |
| 东山精密 | Prismark 36.05亿美元；2025营收401.25亿元 | 光模块+AI PCB协同 | 高端PCB扩产上限10亿美元，2026Q1营收和利润跃升 {s('guangfa_20250901')} {s('kaiyuan_dongshan_20260430')} |
| 景旺电子 | Prismark 21.00亿美元；2025营收153.08亿元 | 高阶HDI/HLC升级 | 40层以上HLC、6阶22层HDI、14层mSAP HDI，9阶HDI 90天认证 {s('kinwong_annual')} |
| 世运电路 | Prismark 7.52亿美元；2025营收55.77亿元 | 汽车PCB向嵌入式/AI板延伸 | 28层AI服务器板、5阶HDI，2026Q1芯片内嵌PCB中试线 {s('olympic_annual')} |

公司详情见 [公司透视]({company_url})，估值快照见 [估值页]({val_url})。

## 5. 数据缺口和后续跟踪

本轮已覆盖 147 份本地 PDF、Prismark 市场表、公司年报、2026Q1转引公告和 yfinance 市值快照。仍需继续补三类一手数据：一是非A股海外公司的年报分业务毛利率和 capex；二是客户层面的具体认证/料号，因为年报普遍只披露“头部客户”而不点名；三是 CoWoP/SLP 量产节奏，目前公开证据仍以技术路线和研发/中试为主，不能提前写成确定收入。

"""

    q0 = f"""---
title: PCB制造_Q0_历史发展
industry: PCB制造
updated: {TODAY}
track: B
---

# Q0 历史发展：从普通连接板到AI系统互连平台

## 一、阶段划分

PCB 的早期主线是消费电子、通信和汽车电子驱动的规模扩张，核心竞争力是稳定良率、交付、成本和客户认证。移动互联网时代推动 FPC、HDI、任意层互联和轻薄化；云计算和 5G 时代推高高速材料、多层板、背钻、阻抗控制和高频高速；AI服务器时代则把 PCB 的角色从“承载电路”推到“高速系统互连和电源管理平台”。沪电年报把这个变化说得很直接：PCB 技术核心从传统电路支撑演变为高速系统互联与电源管理集成平台，对信号完整性、电源完整性、高密复杂结构和可靠性提出更高要求 {s('wus_annual')}。

## 二、工艺演进

传统减成法适合一般多层板；HDI通过激光钻孔、微盲孔、叠孔和任意层互联提高密度；SLP/mSAP进一步把线宽线距压向 ABF 与普通 HDI 之间；CoWoP 则尝试把先进封装中的部分功能下沉到平台 PCB。兴业证券给出的技术标尺是：SLP 线宽/线距可做到 15-18 微米，现有 HDI 约 50 微米，IC载板约 10 微米 {s('xingye_20250811')}。Prismark也指出 CoWoP 利用 mSAP 将 RDL 中介层嵌入 SLP，目标是省去基板和焊球 {s('prismark')}。

| 阶段 | 典型板型 | 层数/线宽 | 材料 | 主要应用 | 投资含义 |
|---|---|---|---|---|---|
| 传统电子周期 | 单双面、多层板 | 4-16层为主 | FR-4等通用材料 | PC、手机、消费电子、汽车 | 成本、交期和产能利用率决定利润 |
| 云计算/高速网络 | 高速多层板、HLC | 26-40层以上 | M6/M7/M8低损耗材料 | 400G/800G/1.6T交换机、服务器 | 材料认证、背钻、阻抗和良率成为壁垒 |
| AI服务器 | HLC+高阶HDI | GB200 OAM 22层5阶HDI；AWS UBB 26层M8 | M8，向M9演进 | GPU/ASIC rack、OAM、UBB、switch tray | 单机价值量提升，客户认证和产能稀缺决定毛利 {s('xingye_20250811')} |
| 半导体化探索 | SLP/mSAP/CoWoP | SLP 15-18微米；mSAP约15微米 | 高稳定树脂、低CTE、HVLP铜箔 | Rubin/CoWoP探索、先进封装边界 | 尚未确定量产，先跟研发/中试/客户验证 |

## 三、CoWoP 的真实含义

CoWoP 不应被理解成“PCB厂马上替代ABF载板”。更严谨的理解是，AI系统开始把芯片、封装、板级互连和电源完整性一起设计，PCB厂如果能把 mSAP、SLP、低翘曲、低CTE和高可靠良率做出来，就可能承接一部分过去不属于裸板厂的价值。但这条路的反方同样清楚：裸片直接上板带来返修难、良率要求极低、热-机械应力复杂和系统协同设计难题 {s('xingye_20250811')}。因此本文把 CoWoP 列为中长期“价值边界上移”变量，不作为 2026 年收入确定性。

## 四、历史结论

PCB历史上每一轮成长都不是单纯“面积增加”，而是下游系统结构改变后，把更高层数、更低损耗、更小线宽、更复杂孔结构和更严认证周期压到板厂。AI服务器是类似但更强的一轮：它同时提高层数、材料等级、HDI阶数、客户协同和产能资本开支。这解释了为什么胜宏、沪电、深南、鹏鼎、景旺等公司同在PCB行业，却表现出完全不同的收入弹性和毛利率。
"""

    q1 = f"""---
title: PCB制造_Q1_竞争格局
industry: PCB制造
updated: {TODAY}
track: B
---

# Q1 竞争格局：分散行业里的高端板再集中

## 一、全球格局

PCB制造长期是分散行业，但 AI 高端化正在让“有客户认证、有高阶工艺、有全球产能”的厂商获得增速溢价。Prismark 2025E Top40 合计 674.55 亿美元、同比 19.0%；前十中既有台系臻鼎、欣兴、华通、健鼎，也有大陆/中国上市公司东山、深南、沪电、胜宏、景旺，还有美国 TTM、日本 Ibiden、Meiko 等高可靠或载板厂 {s('prismark')}。

| 2025E排名 | 公司 | 2025E收入 | 同比 | 解释 |
|---:|---|---:|---:|---|
| 1 | 臻鼎科技 | 58.69亿美元 | 9.9% | 平台型规模最大，FPC/HDI/HLC/载板布局完整 {s('prismark')} |
| 2 | 欣兴电子 | 42.25亿美元 | 17.5% | 台系HDI/载板成熟龙头 {s('prismark')} |
| 3 | 东山精密 | 36.05亿美元 | 4.5% | 规模领先但PCB口径要与光模块协同拆开看 {s('prismark')} |
| 4 | 深南电路 | 32.95亿美元 | 32.2% | PCB+封装基板平台弹性强 {s('prismark')} |
| 5 | TTM | 29.06亿美元 | 19.0% | 北美高可靠供应链对照 {s('prismark')} |
| 6 | 沪电股份 | 27.60亿美元 | 40.8% | 数据通信HLC受益最直接 {s('prismark')} |
| 7 | 胜宏科技 | 26.86亿美元 | 79.9% | AI服务器高阶板弹性最高 {s('prismark')} |

## 二、地区格局

中国仍是全球最大 PCB 生产基地，2025E产值489.69亿美元、同比19.2%，2030F达685.35亿美元；台湾2025E 99.02亿美元、2030F 146.02亿美元；东南亚/其他地区2025E 72.18亿美元、2030F 136.42亿美元，2025-2030 CAGR 13.6% {s('prismark')}。这不是简单“产能外迁”，而是双轨：高端工艺仍集中在中国大陆、台湾、日本和美国头部厂，客户又要求泰国、越南、马来西亚等海外交付冗余。沪电、鹏鼎、景旺等年报里的泰国布局，本质上是在解决地缘和客户认证，不只是追低成本 {s('wus_annual')} {s('avary_annual')}。

## 三、中国厂商的强弱项

中国厂商优势在 HLC/HDI 产值占比和扩产速度。广发证券转引 Prismark：2024年全球18层以上高多层板24.21亿美元，中国10.58亿美元、占43.7%；全球HDI 125.18亿美元，中国78.49亿美元、占62.7% {s('guangfa_20250901')}。弱项在于最前沿载板、SLP/mSAP、低翘曲、极低损耗材料和客户联合设计经验仍需证明，尤其 CoWoP 这类路线涉及封装厂、芯片厂、系统厂和PCB厂的协同，不是单一板厂能独立完成。

## 四、公司分层

| 层级 | 公司 | 核心判断 | 证伪点 |
|---|---|---|---|
| AI服务器高弹性 | 胜宏、沪电、深南、鹏鼎、广合 | 已经有2025和2026Q1收入/利润或客户认证证据 | 若高阶产品毛利率下滑、在建工程转固后产能利用率不足，估值会压缩 |
| 高阶转型 | 景旺、东山、世运 | 技术和产能布局明确，但不同业务口径需拆分 | 光模块并表、汽车/消费电子底盘掩盖PCB真实弹性 |
| 海外对照 | 臻鼎、欣兴、华通、健鼎、TTM、Ibiden、Meiko | 提供成熟高端制造和客户认证参照 | 不适合直接用A股估值逻辑比较 |
| 上游材料 | 生益科技、建滔、铜箔/玻纤布/树脂厂 | 材料涨价和M8/M9升级受益 | 本文不纳入PCB制造主公司池，只在成本和价值链中跟踪 |

→ 公司明细见 [公司透视]({company_url})。
"""

    q2 = f"""---
title: PCB制造_Q2_市场空间
industry: PCB制造
updated: {TODAY}
track: B
---

# Q2 市场空间：总量、结构和AI服务器三套口径并列

## 一、总市场

Prismark口径下，全球PCB总市场2024年735.65亿美元，2025E为851.52亿美元、同比15.8%，2026F为957.80亿美元，2030F为1233.48亿美元，2025-2030 CAGR为7.7% {s('prismark')}。若按{TODAY}快照的USDCNY={FX['USD']:.4f}折算，2025E约{851.52 * FX['USD']:.2f}亿元人民币，2030F约{1233.48 * FX['USD']:.2f}亿元人民币。这个人民币换算只是阅读辅助，不能与国内厂商收入直接相加，因为全球收入包括不同地区和币种口径。

## 二、产品拆分

| 产品 | 2025E | 2030F | CAGR | 投资解释 |
|---|---:|---:|---:|---|
| 多层板 | 331.50亿美元 | 486.36亿美元 | 8.0% | AI和高速网络推动HLC占比提升 {s('prismark')} |
| HDI | 157.69亿美元 | 244.90亿美元 | 9.2% | 高阶HDI从手机扩展到OAM、光模块、服务器 {s('prismark')} |
| 封装基板 | 148.91亿美元 | 249.85亿美元 | 10.9% | ABF/FCBGA仍高壁垒，和CoWoP形成边界竞争 {s('prismark')} |
| FPC | 129.03亿美元 | 155.27亿美元 | 3.8% | 消费电子恢复但成长斜率较低 {s('prismark')} |
| 大宗/低端 | 84.40亿美元 | 97.09亿美元 | 2.8% | 总量稳定，但不是本轮利润弹性来源 {s('prismark')} |

## 三、应用拆分

服务器/存储是最重要的增量。2024年全球服务器/存储PCB 109.16亿美元、占14.84%；2029E 189.21亿美元、占19.99%，2024-2029 CAGR 11.6% {s('guangfa_20250901')}。长江证券同样指出，2024年服务器/存储PCB同比增长33.1%，是增长最快的下游；而手机虽然仍占19%，但增速只有6.1% {s('changjiang_20250804')}。

数据中心PCB还可以用更窄的口径验证。首创证券援引灼识咨询，2024-2029年全球数据中心PCB市场CAGR为10.9%，从2024年的125亿美元增至2029年的210亿美元；其中AI服务器及HPC CAGR 20.8%，交换机/路由器 CAGR 15.2%，2029年分别达80亿美元和102亿美元 {s('shouchuang_20260415')}。这说明AI服务器不是“PCB总市场里的一小块”，而是高端板价格、良率和客户认证的主要驱动。

## 四、区域和产能

2025E中国PCB产值489.69亿美元，仍是全球最大；东南亚/其他地区2025E 72.18亿美元、2030F 136.42亿美元，CAGR 13.6% {s('prismark')}。区域结构对公司的含义是：国内高端制程能力仍是核心，但海外交付已经成为大客户认证的一部分。沪电泰国数据通讯事业部已有超70%海外客户完成认证、2026Q1产能利用率超90%；鹏鼎泰国一厂2025年5月试产并通过多家客户认证，后续多座厂房建设 {s('wus_annual')} {s('avary_annual')}。

## 五、市场空间结论

本行业不能只用“全球PCB 7.7% CAGR”估值。更贴近投资研究的拆法是：低端/通用板按周期品和产能利用率看；FPC按消费电子复苏和端侧AI看；HLC/HDI/SLP/mSAP按AI服务器、交换机、光模块和先进封装边界看；封装基板按ABF/BT和芯片客户认证看。胜宏、沪电、深南、鹏鼎、景旺、广合等公司的估值差，来自它们分别站在这些曲线的不同位置。
"""

    q3 = f"""---
title: PCB制造_Q3_公司壁垒
industry: PCB制造
updated: {TODAY}
track: B
---

# Q3 公司壁垒：客户认证、工艺窗口、产能兑现和财务弹性

## 一、壁垒框架

PCB制造的壁垒不是“会做板”三个字，而是四层叠加：第一，客户认证和共同开发，尤其AI服务器、高速交换机和光模块客户的认证周期长、失效率容忍度低；第二，工艺能力，包括高层数、微盲孔、背钻残段、阻抗控制、mSAP、SLP、低翘曲和材料加工；第三，产能兑现，包括设备、良率、人员和海外基地；第四，财务弹性，即材料涨价、折旧上升、扩产和价格传导之间的平衡。

## 二、核心公司壁垒

### 胜宏科技

胜宏的证据链最直接：2025年收入192.92亿元、同比79.77%，归母43.12亿元、同比273.52%，研发费用7.78亿元、同比72.88%，经营现金流46.03亿元 {s('shenghong_annual')}。技术上，公司披露100层以上高多层板制造能力，是全球首批实现6阶24层HDI大规模生产、具备10阶30层HDI和16层Any-layer HDI能力的企业 {s('shenghong_annual')}。2026Q1继续验证利润质量：营收55.19亿元、归母12.88亿元、毛利率34.46%、净利率23.34% {s('cms_shenghong_20260505')}。

投资含义：胜宏不是传统“PCB收入大公司”，而是高端AI服务器产品占比提升后的利润重估。需要证伪的是：在惠州、泰国、越南产能释放后，高端订单能否继续填满；覆铜板涨价能否继续传导；客户集中和NVIDIA/Rubin节奏变化是否造成利润波动。

### 沪电股份

沪电的壁垒在数据通信场景。2025年公司收入189.45亿元、归母38.22亿元，其中PCB业务181.43亿元、毛利率36.91%，研发投入约11.4亿元 {s('wus_annual')}。年报明确把资源倾斜到数据通讯应用领域高阶硬件所需的高附加值核心PCB产品，并披露泰国数据通讯事业部已有超70%海外客户完成认证，2026Q1产能利用率超90% {s('wus_annual')}。

投资含义：沪电更像“数据通信HLC/高频高速工艺+海外认证”的纯度标的。证伪点是新增高端产能如果逐步同质化，成熟技术平台准入门槛被摊薄，毛利率会先反映压力。

### 深南电路

深南的壁垒是平台化。2025年收入236.47亿元、归母32.76亿元；PCB业务143.59亿元、毛利率35.53%；封装基板41.48亿元、毛利率22.58%；电子装联30.75亿元、毛利率15.00% {s('shennan_annual')}。封装基板方面，FC-BGA 22层及以下已量产，24层及以上研发打样按期推进 {s('shennan_annual')}。

投资含义：深南的弹性不只在PCB，也在封装基板和电子装联的组合。若AI服务器带动PCB订单，同时FC-BGA高层数突破，平台价值会放大；若载板良率或客户导入慢，估值要回到PCB业务本身。

### 鹏鼎控股

鹏鼎传统底盘是通讯用板和消费电子/FPC，但2025年汽车/服务器用板收入21.19亿元、同比106.67%，毛利率21.55%；AI服务器类产品收入较2024年增长超1倍 {s('avary_annual')}。公司计划2025H2-2028在淮安投入80亿元扩充高阶PCB产能，并于2026年初签署110亿元高端PCB项目生产基地投资协议 {s('avary_annual')}。

投资含义：鹏鼎的关键是从端侧FPC龙头向云侧IHDI/HLC迁移。不能只看总收入391.47亿元，因为消费电子底盘会稀释AI服务器弹性；要跟踪汽车/服务器用板、IHDI/HLC认证、泰国量产和淮安产能。

### 景旺电子、广合科技、世运电路

景旺披露应用于AI基础设施的40层以上HLC、6阶22层HDI、14层mSAP HDI大规模量产，并启动11阶HDI认证；9阶HDI仅90天通过客户认证 {s('kinwong_annual')}。广合长期服务国内外服务器客户，2026Q1营收19.14亿元、归母3.93亿元，服务器PCB弹性强 {s('dongguan_20260511')}。世运已具备28层AI服务器线路板、5阶HDI批量生产能力，并在2026Q1建成芯片内嵌式PCB中试线 {s('olympic_annual')}。

这三类公司共同特征是“高端化证据存在，但体量、业务结构或商业化阶段不同”。景旺要看高阶HDI/HLC收入占比提升；广合要看客户份额和高阶产能持续性；世运要看嵌入式PCB是否从技术样品进入可重复量产。

## 三、壁垒结论

真正能穿越周期的PCB公司，需要同时满足：客户早期协同、可验证高阶工艺、产能爬坡和财务兑现。只披露“布局AI PCB”但没有层数、HDI阶数、客户认证、营收毛利和资本开支证据的公司，只能列观察项，不能和胜宏、沪电、深南这类已经验证利润弹性的公司同权重比较。
"""

    q4 = f"""---
title: PCB制造_Q4_行业特征
industry: PCB制造
updated: {TODAY}
track: B
---

# Q4 行业特征：定制化、认证周期、材料价格和产能周期

## 一、利润模型

PCB制造利润来自“材料成本+加工难度+良率+客户认证+交付可靠性”的组合。普通板厂更像加工制造，利润受产能利用率和原材料波动影响；AI服务器HLC/HDI厂商则在客户认证、工艺窗口和交付稀缺中获得价格和毛利率。2025年可以看到明显分化：沪电PCB业务毛利率36.91%，深南PCB业务毛利率35.53%，胜宏2026Q1毛利率34.46%；而景旺PCB业务毛利率16.95%、世运PCB业务毛利率14.73% {s('wus_annual')} {s('shennan_annual')} {s('cms_shenghong_20260505')} {s('kinwong_annual')} {s('olympic_annual')}。

## 二、价格形成

低端PCB价格由材料、面积、层数和竞争决定；高端AI PCB价格还包含制程风险、良率、认证周期、供应紧张和客户急单溢价。上游覆铜板占PCB生产成本30%-40%，铜箔、树脂、玻纤布占覆铜板成本87.3%，因此材料价格上涨会先压缩板厂利润，再通过产品价格传导给客户 {s('huaxi_20260524')}。胜宏年报也提示，覆铜板、半固化片、铜球、铜箔等原材料成本占产品成本比重较高，向下游传导存在滞后 {s('shenghong_annual')}。

## 三、客户和销售模式

PCB是高度定制化产品。首创证券整理：企业需通过客户全面认证才能获得正式供货资格，大客户认证周期通常1-2年；通过认证后往往形成长期稳定合作关系 {s('shouchuang_20260415')}。这解释了为什么同样扩产，高端客户已认证公司和新进入者估值不同。沪电泰国数据通讯事业部超70%海外客户完成认证，鹏鼎HLC产品陆续获得或推进云服务厂商认证，景旺9阶HDI 90天通过客户认证，都是比“产能多少”更重要的信号 {s('wus_annual')} {s('avary_annual')} {s('kinwong_annual')}。

## 四、周期和风险

PCB周期有四个层次：终端需求周期、材料价格周期、资本开支周期和技术迭代周期。2026Q1行业聚合数据仍强，东莞证券统计PCB行业营收646.57亿元、同比28.99%，归母64.83亿元、同比38.49%，毛利率24.47%、净利率9.96% {s('dongguan_20260512')}。但如果未来AI资本开支降速、材料涨价不能传导、新增产能集中释放或客户认证失败，利润弹性会快速反转。

## 五、行业特征结论

PCB制造不是单一周期品，也不是简单先进制造。它在低端是成本竞争，在高端是客户和工艺竞争，在AI服务器上又叠加系统架构变化。研究时必须把“总市场、细分板型、客户认证、材料传导、产能位置、财务兑现”放在同一张表里，否则容易把一个普通扩产故事误判成高端成长故事。
"""

    q5 = f"""---
title: PCB制造_Q5_综述
industry: PCB制造
updated: {TODAY}
track: B
---

# Q5 综述：PCB制造的研究结论和跟踪框架

## 一、核心判断

本轮 PCB 制造研究的结论是：行业总量进入新一轮上行，但投资研究要抓结构，而不是只抓总量。Prismark 2025E全球PCB市场851.52亿美元、同比15.8%，到2030F为1233.48亿美元 {s('prismark')}；服务器/存储PCB 2024-2029 CAGR 11.6%，AI服务器和HPC、交换机/路由器又是其中更高斜率的子项 {s('guangfa_20250901')} {s('shouchuang_20260415')}。这意味着HLC、HDI、SLP、mSAP、低损耗材料和客户联合设计，是决定公司相对收益的关键。

## 二、公司结论

胜宏科技是利润弹性最强的AI服务器高阶板代表，技术证据和财务证据都最集中；沪电股份是数据通信高频高速/HLC的高确定性代表，海外客户认证和泰国利用率验证交付能力；深南电路是平台型代表，PCB+封装基板+电子装联使其既有确定性也有载板突破期权；鹏鼎控股是FPC龙头向AI服务器IHDI/HLC迁移的转型标的；东山精密要拆分光模块和AI PCB，不能用合并口径替代PCB判断；景旺、广合、世运是第二梯队弹性观察，分别看高阶HDI/HLC、服务器客户份额和嵌入式PCB商业化。

## 三、风险结论

最大的反方不是“PCB没有需求”，而是三个错配：第一，材料涨价先于板厂价格传导，压缩毛利；第二，扩产转固快于客户认证和订单释放，折旧吞噬利润；第三，CoWoP、Rubin、ASIC服务器等技术路线被过早定价，但量产和良率尚未证明。对估值较高的公司，2026Q1强业绩不是终点，后续要继续用季度毛利率、在建工程、经营现金流、客户认证和高端产品收入占比复核。

## 四、下一步数据要求

后续优先补三类数据：海外公司年报分业务数据和capex；A股公司2026半年报中高端PCB收入/毛利率/在建工程转固；客户侧公开平台、招标、IR、服务器BOM或供应链证据。没有这些证据前，客户名称和份额只能写“公开不可得/待补充”，不能用二级市场传闻替代。
"""

    company_doc = f"""---
title: PCB制造_公司透视
industry: PCB制造
updated: {TODAY}
track: B
---

# PCB制造 公司透视

结构化公司数据已写入 `company`、`company_industry` 和 `company_profile`，viewer 页面见 [公司透视]({company_url})、[估值页]({val_url})。本页只保留研究员阅读用的横向比较。

| 公司 | 市值折算 | 2025/2026Q1验证 | 核心能力 | 主要风险 |
|---|---:|---|---|---|
| 胜宏科技 | 3027.7亿元人民币 | 2025收入192.92亿元、归母43.12亿元；2026Q1收入55.19亿元、归母12.88亿元 | 100层以上HLC、6阶24层HDI、10阶30层HDI、AI服务器高端板规模化 | 高估值、材料涨价传导、客户集中和新产能爬坡 {s('shenghong_annual')} {s('cms_shenghong_20260505')} |
| 沪电股份 | 2604.6亿元人民币 | 2025收入189.45亿元、PCB毛利率36.91%；2026Q1收入62.14亿元 | 数据通信HLC、高频高速、泰国海外客户认证 | 高端产能同质化、原材料成本、海外运营 {s('wus_annual')} |
| 深南电路 | 3095.8亿元人民币 | 2025收入236.47亿元，PCB/封装基板/装联三线增长 | PCB+FC-BGA/BT载板平台，FC-BGA 22层以下量产 | 载板良率和客户导入节奏，平台业务复杂度 {s('shennan_annual')} |
| 鹏鼎控股 | 2242.7亿元人民币 | 2025收入391.47亿元，汽车/服务器用板21.19亿元、同比106.67% | FPC底盘，高阶HDI/SLP/IHDI/HLC转云侧 | 消费电子底盘稀释AI弹性，HLC认证和新产能爬坡 {s('avary_annual')} |
| 东山精密 | 4262.7亿元人民币 | 2025收入401.25亿元；2026Q1收入131.38亿元、归母11.10亿元 | Multek高端PCB+索尔思光模块协同 | 光模块并表导致PCB口径需拆分，高估值 {s('dongshan_annual')} {s('kaiyuan_dongshan_20260430')} |
| 景旺电子 | 709.5亿元人民币 | 2025收入153.08亿元、PCB毛利率16.95% | 40层以上HLC、6阶22层HDI、14层mSAP HDI、M7-M9材料能力 | 高端占比爬坡、毛利率低于AI龙头 {s('kinwong_annual')} |
| 广合科技 | 959.6亿元人民币 | 2026Q1收入19.14亿元、归母3.93亿元 | 服务器PCB客户覆盖和高阶HDI突破 | 订单集中和服务器周期波动 {s('dongguan_20260511')} |
| 世运电路 | 327.6亿元人民币 | 2025收入55.77亿元、PCB毛利率14.73% | 28层AI服务器板、5阶HDI、嵌入式PCB中试线 | 商业化早期、规模和客户验证仍需补证 {s('olympic_annual')} |

海外对照组：臻鼎、欣兴、华通、健鼎代表台系规模和HDI/载板能力；TTM代表北美高可靠供应链；Ibiden、Meiko代表日系载板/汽车高可靠能力。其估值和市值已按 Tushare/yfinance {TODAY} 快照入库，金额统一用人民币亿元为主、括号补美元等值，不与A股收入直接相加 {s('yfinance_20260706')}。
"""

    q6 = f"""---
title: PCB制造_Q6_补充
industry: PCB制造
updated: {TODAY}
track: B
---

# Q6 补充：审计口径和未完成项

## 一、已完成

- B轨判定已写入 `docs/行业接入记录.md`。
- `research.db` 已新增/更新 `industry=PCB制造`、source、company、company_profile、company_industry、industry_relation 和 industry_data_point。
- 数据点全部通过 `tools/pipeline/db_writer.py::write_data_point()` 写入；没有直接 INSERT `industry_data_point`。
- 本地 `papers/pcb` 147份PDF已抽取全文到 `cache/pcb_research/extracted_text/`。

## 二、口径限制

1. 市场规模以 Prismark 为主，券商转引作为补充；不同机构预测不可直接拼接成单一时间序列。
2. 公司客户名称以公开年报和报告披露为准；未点名的头部客户不强行写为英伟达、Google、AWS或华为供应。
3. CoWoP、SLP、mSAP为技术边界变量，不等于确定量产收入。
4. 生益科技、建滔、铜箔、玻纤布、树脂企业是上游材料，不纳入PCB制造公司池，只作为成本和价值链约束。
5. 估值为Tushare/yfinance {TODAY}快照，PE/PB/PS会随行情变化，使用时必须看日期。

## 三、后续补证顺序

第一优先级：2026半年报中高端PCB收入、毛利率、capex、在建工程转固和经营现金流。第二优先级：客户认证和料号级证据，尤其GPU/ASIC服务器、光模块、交换机板。第三优先级：海外公司年报分业务数据。第四优先级：CoWoP/SLP实际中试、良率、客户验证和量产路线。
"""

    files = {
        "PCB制造.md": main,
        "PCB制造_Q0_历史发展.md": q0,
        "PCB制造_Q1_竞争格局.md": q1,
        "PCB制造_Q2_市场空间.md": q2,
        "PCB制造_Q3_公司壁垒.md": q3,
        "PCB制造_Q4_行业特征.md": q4,
        "PCB制造_Q5_综述.md": q5,
        "PCB制造_Q6_补充.md": q6,
        "PCB制造_公司透视.md": company_doc,
    }
    for name, content in files.items():
        normalized = dedent(content).strip() + "\n"
        (DOCS_DIR / name).write_text(normalized, encoding="utf-8")

    synth = {
        "industry_id": industry_id,
        "industry": INDUSTRY_NAME,
        "run_tag": RUN_TAG,
        "date": TODAY,
        "source_ids": source_ids,
        "company_ids": company_ids,
        "notes": [
            "B-track task from PCB制造产业研究数据整理Prompt.md",
            "industry_data_point rows are written only through write_data_point()",
            "Market and company analysis uses local PDF excerpts plus yfinance valuation snapshot",
        ],
    }
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / "PCB制造_synthesis.json").write_text(json.dumps(synth, ensure_ascii=False, indent=2), encoding="utf-8")
    (CACHE_DIR / "PCB制造_执行审计.md").write_text(
        dedent(f"""
        # PCB制造 B轨执行审计

        - 日期：{TODAY}
        - 行业：PCB制造
        - DB：data/research.db
        - 数据源：papers/pcb 147份PDF；Tushare/yfinance {TODAY}快照
        - 数据点写入：仅使用 `write_data_point()`
        - 文档：docs/industries/PCB制造*.md

        ## 核验结论

        已按B轨执行；主报告、Q0-Q5、Q6和公司透视均生成。未把设备、上游材料或SMT装联混入PCB制造主口径；上游材料只作为成本和产业链约束。
        """).strip() + "\n",
        encoding="utf-8",
    )


def audit_financial_completeness(conn: sqlite3.Connection, industry_id: int) -> dict:
    listed_missing = [
        dict(r)
        for r in conn.execute(
            """
            select c.name, c.ticker, c.pe_ttm, c.pb, c.ps_ttm, c.market_cap_cny,
                   cp.gross_margin, cp.net_margin, cp.operating_cash_flow, cp.capex_value, cp.recent_events
            from company_profile cp join company c on c.id=cp.company_id
            where cp.industry_id=? and c.listing_status in ('a_share','listed','other_listed')
              and (
                c.pe_ttm is null or c.pb is null or c.ps_ttm is null or c.market_cap_cny is null
                or cp.gross_margin is null or cp.net_margin is null
                or cp.operating_cash_flow is null or cp.capex_value is null
                or cp.recent_events is null or trim(cp.recent_events)=''
              )
            """,
            (industry_id,),
        )
    ]
    snapshot_errors = {k: v for k, v in MARKET_SNAPSHOT.items() if isinstance(v, dict) and v.get("error") and k in COMPANIES}
    result = {
        "listed_missing": listed_missing,
        "snapshot_errors": snapshot_errors,
        "passed": not listed_missing and not snapshot_errors,
    }
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / "PCB制造_financial_audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def audit_source_excerpt_alignment(conn: sqlite3.Connection, industry_id: int) -> dict:
    def classify_metric(metric: str) -> set[str]:
        classes: set[str] = set()
        if any(k in metric for k in ["营业收入", "归母净利润", "净利润", "毛利率", "净利率", "研发", "现金流", "PE", "PB", "PS", "市值"]):
            classes.add("financial")
        if any(k in metric for k in ["HDI", "HLC", "FC-BGA", "mSAP", "CoWoP", "SLP", "UBB", "OAM", "层数", "阶数", "高多层", "量产能力", "制造能力", "线宽"]):
            classes.add("technology")
        if any(k in metric for k in ["客户认证", "认证完成", "产能利用率", "订单", "在手订单"]):
            classes.add("commercial")
        if any(k in metric for k in ["投资", "扩产", "capex", "产能计划", "项目"]):
            classes.add("capex")
        return classes or {"other"}

    def expected_keywords(metric: str) -> list[str]:
        keyword_sets = [
            (["HDI"], ["HDI"]),
            (["HLC", "高多层"], ["HLC", "高多层", "多层"]),
            (["FC-BGA"], ["FC-BGA"]),
            (["mSAP"], ["mSAP"]),
            (["CoWoP"], ["CoWoP"]),
            (["SLP"], ["SLP"]),
            (["UBB"], ["UBB"]),
            (["OAM"], ["OAM"]),
            (["层数", "量产能力", "制造能力"], ["层", "量产", "制造能力", "高多层"]),
            (["阶数"], ["阶"]),
            (["客户认证", "认证完成"], ["认证"]),
            (["产能利用率"], ["产能利用率"]),
            (["投资", "扩产", "capex", "产能计划", "项目"], ["投资", "扩产", "capex", "产能"]),
        ]
        checks: list[str] = []
        for triggers, keywords in keyword_sets:
            if any(t in metric for t in triggers):
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
    excerpt_groups: dict[tuple[str, str], dict[str, object]] = {}
    missing_alignment: list[dict] = []
    empty_excerpt: list[dict] = []
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
        if checks and not any(k.lower() in excerpt.lower() for k in checks):
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

    cross_class_reuse: list[dict] = []
    for (source_title, excerpt), group in excerpt_groups.items():
        classes = set(group["classes"])
        metrics = list(dict.fromkeys(group["metrics"]))
        if len(metrics) < 3:
            continue
        has_bad_mix = (
            ("technology" in classes and "financial" in classes)
            or ("commercial" in classes and "financial" in classes)
        )
        if has_bad_mix:
            cross_class_reuse.append(
                {
                    "source_title": source_title,
                    "classes": sorted(classes),
                    "metric_count": len(metrics),
                    "sample_metrics": metrics[:10],
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
    (CACHE_DIR / "PCB制造_source_excerpt_audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    global MARKET_SNAPSHOT
    MARKET_SNAPSHOT = fetch_pcb_market_snapshot()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / "PCB制造_market_snapshot_20260707.json").write_text(
        json.dumps(MARKET_SNAPSHOT, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        source_ids = {key: ensure_source(conn, key, meta) for key, meta in SOURCES.items()}
        industry_id = ensure_industry(conn)
        company_ids = {key: ensure_company(conn, key, industry_id, source_ids) for key in COMPANIES}
        write_source_entity_links(conn, source_ids, company_ids, industry_id)
        write_industry_relations(conn, industry_id, source_ids)
        dp_count = write_data_points(conn, industry_id, source_ids, company_ids)
        from pcb_enhanced_docs import write_enhanced_docs
        write_enhanced_docs(DOCS_DIR, CACHE_DIR, industry_id, source_ids, SOURCES, TODAY)
        append_route_record()
        financial_audit = audit_financial_completeness(conn, industry_id)
        excerpt_audit = audit_source_excerpt_alignment(conn, industry_id)
        if not financial_audit["passed"]:
            raise RuntimeError(f"PCB制造 financial audit failed: {financial_audit}")
        if not excerpt_audit["passed"]:
            raise RuntimeError(f"PCB制造 source excerpt audit failed: {excerpt_audit}")
        conn.commit()
        print(json.dumps({
            "status": "ok",
            "industry_id": industry_id,
            "source_count": len(source_ids),
            "company_count": len(company_ids),
            "data_point_count": dp_count,
            "docs": 9,
            "financial_audit": financial_audit,
            "source_excerpt_audit": excerpt_audit,
        }, ensure_ascii=False, indent=2))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
