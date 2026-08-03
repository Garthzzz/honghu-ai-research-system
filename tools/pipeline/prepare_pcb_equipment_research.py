#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Prepare claims, calculation ledgers and Plotly figures for PCB equipment.

This producer is deliberately DB-free.  Formal data-point loading is performed
later by the unified ``ingest_research.py`` entry.
"""

from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import math
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import plotly.graph_objects as go
from plotly.subplots import make_subplots

try:
    from .company_financial_series_utils import rounded_pct_change_with_interval
    from .pcb_equipment_research_data import (
        AS_OF_DATE,
        CFMEE_DI_PRODUCTS,
        COMPANY_IDENTITIES,
        DOWNSTREAM_PROJECTS,
        EQUIPMENT_CAGR_2025_2029,
        EQUIPMENT_MARKET_USD_M,
        GLOBAL_MARKET_USD_M,
        HANS_2025_10M_PRODUCTS,
        REGIONAL_CAGR_2025_2029,
        REGIONAL_MARKET_USD_M,
        RUN_TAG,
        SOURCES,
        STANDARD_LINE,
    )
except ImportError:
    from company_financial_series_utils import rounded_pct_change_with_interval
    from pcb_equipment_research_data import (
        AS_OF_DATE,
        CFMEE_DI_PRODUCTS,
        COMPANY_IDENTITIES,
        DOWNSTREAM_PROJECTS,
        EQUIPMENT_CAGR_2025_2029,
        EQUIPMENT_MARKET_USD_M,
        GLOBAL_MARKET_USD_M,
        HANS_2025_10M_PRODUCTS,
        REGIONAL_CAGR_2025_2029,
        REGIONAL_MARKET_USD_M,
        RUN_TAG,
        SOURCES,
        STANDARD_LINE,
    )


ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / "cache" / "pcb_equipment_research"
CLAIMS_DIR = ROOT / "cache" / "claims"
VIS_DIR = ROOT / "tools" / "viewer" / "static" / "generated" / "pcb_equipment"
FINANCIAL_PATH = CACHE_DIR / "company_financial_snapshot.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_payload(spec) -> dict[str, Any]:
    row = {
        "source_ref": spec.key,
        "title": spec.title,
        "publisher": spec.publisher,
        "publish_date": spec.publish_date,
        "source_type": spec.source_type,
        "quality_tier": spec.quality_tier,
        "value_layer": spec.value_layer,
        "source_credibility": "whitelisted" if spec.primary else "trusted_project_source",
        "source_subtype": spec.source_subtype,
        "language": spec.language,
        "is_primary_source": spec.primary,
        "is_forward_looking": int("预测" in spec.note or spec.source_type.startswith("卖方")),
        "fetch_method": spec.fetch_method or ("pdf_local" if spec.file_path else "web_fetch"),
        "fetch_timestamp": f"{AS_OF_DATE}T19:00:00+08:00",
        "content_snapshot_path": spec.snapshot_path,
        "independence_key": spec.key,
        "independence_basis": spec.note or "独立原始来源。",
        "note": spec.note,
    }
    if spec.file_path:
        row["source_file"] = spec.file_path
    else:
        row["source_url"] = spec.url
        row["domain"] = spec.url.split("/")[2] if spec.url else None
    return row


def _dp(
    source: str,
    metric: str,
    period: str,
    unit: str,
    excerpt: str,
    *,
    value_num: float | int | None = None,
    value_text: str | None = None,
    company: str | None = None,
    forecast: bool = False,
    method: str = "pdf_direct",
    scope: str = "all_pcb_special_equipment",
    note: str = "",
    as_of: str | None = None,
) -> dict[str, Any]:
    if value_num is not None and not math.isfinite(float(value_num)):
        raise ValueError(f"non-finite {metric}")
    if as_of:
        resolved_as_of = as_of
    elif match := re.fullmatch(r"(\d{4})M(\d{1,2})", period):
        year, month = int(match.group(1)), int(match.group(2))
        resolved_as_of = f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"
    elif match := re.fullmatch(r"(\d{4})Q([1-4])", period):
        year, quarter = int(match.group(1)), int(match.group(2))
        month = quarter * 3
        resolved_as_of = f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"
    elif match := re.fullmatch(r"(\d{4})(?:E|F)?", period):
        resolved_as_of = f"{match.group(1)}-12-31"
    else:
        resolved_as_of = AS_OF_DATE
    return {
        "source_ref": source,
        "company": company,
        "metric": metric,
        "period": period,
        "as_of_date": resolved_as_of,
        "value_num": value_num,
        "value_text": value_text,
        "unit": unit,
        "is_forecast": int(forecast),
        "sentiment": "不适用",
        "extraction_method": method,
        "scope_key": scope,
        "source_excerpt": excerpt[:500],
        "note": note,
    }


def market_claims() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for year, value in GLOBAL_MARKET_USD_M.items():
        inferred = year == 2030
        rows.append(_dp(
            "hans_h", "全球PCB专用设备市场规模", f"{year}{'E' if year >= 2025 else ''}", "百万美元",
            "[PDF第127-128页] 全球PCB专用设备市场2024年70.85亿美元，2025E至2029E为81.76/91.20/99.73/107.29/113.88亿美元，2025-2029年CAGR 8.6%。",
            value_num=value, forecast=year >= 2025, method="inferred" if inferred else "pdf_direct",
            note=("公式=2029年11388百万美元×(1+8.6%)，四舍五入为12367百万美元；仅作单年外推，非机构原表。" if inferred else "Prismark/灼识咨询机构预测；全部PCB专用设备，不是18层以上专用市场。"),
        ))
    for year, values in REGIONAL_MARKET_USD_M.items():
        for region, value in values.items():
            inferred = year == 2030
            rows.append(_dp(
                "hans_h", f"{region}PCB专用设备市场规模", f"{year}E", "百万美元",
                "[PDF第127页] 招股书按中国、中国台湾、韩国、日本、美洲、东南亚和其他地区列示2025E-2029E设备收入市场。",
                value_num=value, forecast=True, method="inferred" if inferred else "pdf_direct",
                scope=f"region_{region}_all_pcb_equipment",
                note=("2030=2029值×招股书2025-2029对应地区CAGR；欧洲未单列，美洲也不等于北美，不能伪拆。" if inferred else "机构预测；区域为设备收入市场口径。欧洲未单列，美洲不应改名为北美。"),
            ))
    for year, values in EQUIPMENT_MARKET_USD_M.items():
        for category, value in values.items():
            inferred = year == 2030
            rows.append(_dp(
                "hans_h", f"全球{category}设备市场规模", f"{year}E", "百万美元",
                "[PDF第128页] 全球PCB专用设备按钻孔、曝光、检测、电镀、压合、成型、贴附和其他分类列示2025E-2029E收入市场。",
                value_num=value, forecast=True, method="inferred" if inferred else "pdf_direct",
                scope=f"equipment_category_{category}_global",
                note=(f"2030=2029值×(1+{EQUIPMENT_CAGR_2025_2029[category]}%)；各类独立外推后的加总与总市场外推有小幅舍入差，非机构原表。" if inferred else "机构预测；大类内部包含不同技术路线，不能直接等同18层以上高多层专用需求。"),
            ))
    rows.extend([
        _dp("hans_h", "全球PCB专用设备CR5", "2024", "%", "[PDF第134页] 按2024年收入，全球前五大PCB专用设备制造商合计份额20.9%。", value_num=20.9, scope="global_all_equipment_revenue", note="发行人委聘灼识咨询估计；竞争者匿名，无法可靠计算CR10或HHI。"),
        _dp("hans_h", "大族数控全球PCB专用设备份额", "2024", "%", "[PDF第134页] 大族数控按2024年全球销售收入排名第一，全球份额约6.5%。", value_num=6.5, company="大族数控", scope="global_all_equipment_revenue", note="发行人委聘灼识咨询估计。"),
        _dp("hans_h", "中国PCB专用设备CR5", "2024", "%", "[PDF第135页] 按2024年中国收入，前五大制造商合计份额约23.9%。", value_num=23.9, scope="china_all_equipment_revenue", note="发行人委聘灼识咨询估计。"),
        _dp("hans_h", "大族数控中国PCB专用设备份额", "2024", "%", "[PDF第135页] 大族数控按2024年中国销售收入份额约10.1%。", value_num=10.1, company="大族数控", scope="china_all_equipment_revenue", note="发行人委聘灼识咨询估计。"),
        _dp("cfmee_h", "全球PCB直接成像设备市场规模", "2025", "亿元人民币", "[PDF第88-95页] 灼识咨询估计2025年全球PCB直接成像设备市场57亿元，2030年93亿元。", value_num=57.0, forecast=True, scope="global_pcb_direct_imaging", note="发行人委聘灼识咨询估计；仅PCB直接成像，不是全部曝光设备。"),
        _dp("cfmee_h", "全球PCB直接成像设备市场规模", "2030E", "亿元人民币", "[PDF第88-95页] 灼识咨询估计2025年全球PCB直接成像设备市场57亿元，2030年93亿元。", value_num=93.0, forecast=True, scope="global_pcb_direct_imaging", note="机构预测；仅PCB直接成像。"),
        _dp("cfmee_h", "全球PCB直接成像设备CR5", "2025", "%", "[PDF第11页] 2025年前五大PCB直接成像设备供应商合计份额约59.1%。", value_num=59.1, scope="global_pcb_direct_imaging_revenue", note="与全部PCB设备CR5分母不同。"),
        _dp("cfmee_h", "芯碁微装全球PCB直接成像设备份额", "2025", "%", "[PDF第11页] 芯碁微装按2025年PCB直接成像营业收入计全球份额18.8%。", value_num=18.8, company="芯碁微装", scope="global_pcb_direct_imaging_revenue", note="发行人委聘灼识咨询估计。"),
    ])
    return rows


def company_product_claims() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for category, values in HANS_2025_10M_PRODUCTS.items():
        excerpt = "[PDF第187页] 大族数控披露2025年前十个月按设备大类收入、销量及平均售价。"
        rows += [
            _dp("hans_h", f"大族数控{category}设备收入", "2025M10", "亿元人民币", excerpt, value_num=values["revenue_yi"], company="大族数控", scope=f"hans_{category}_category", note="公司实际值；大类收入，不等于18层以上收入。"),
            _dp("hans_h", f"大族数控{category}设备销量", "2025M10", "台", excerpt, value_num=values["volume"], company="大族数控", scope=f"hans_{category}_category", note="公司实际值。"),
            _dp("hans_h", f"大族数控{category}设备平均售价", "2025M10", "万元/台", excerpt, value_num=values["asp_wan"], company="大族数控", scope=f"hans_{category}_category", note="公司大类实际平均价，不能冒充具体高端型号报价。"),
        ]
    for year, values in CFMEE_DI_PRODUCTS.items():
        excerpt = "[PDF第131-132页] 芯碁微装披露PCB直接成像设备及自动线销量和平均售价。"
        rows += [
            _dp("cfmee_h", "芯碁微装PCB直接成像设备销量", str(year), "台", excerpt, value_num=values["volume"], company="芯碁微装", scope="cfmee_pcb_di_and_lines", note="公司实际值；包含设备及自动线。"),
            _dp("cfmee_h", "芯碁微装PCB直接成像设备平均售价", str(year), "万元/台", excerpt, value_num=values["asp_wan"], company="芯碁微装", scope="cfmee_pcb_di_and_lines", note="公司实际平均价；产品组合变化会影响同比。"),
        ]
        if values.get("revenue_yi") is not None:
            rows.append(_dp("cfmee_h", "芯碁微装PCB直接成像设备收入", str(year), "亿元人民币", excerpt, value_num=values["revenue_yi"], company="芯碁微装", scope="cfmee_pcb_di_and_lines", note="公司实际值。"))
    rows.extend([
        _dp("hans_h", "大族数控3D背钻Z轴深度控制", "2025", "mil", "[PDF第188-190页] 3D背钻Z轴深度控制4±2 mil，XY精度D+4 mil。", value_text="4±2", company="大族数控", scope="hans_3d_backdrill", note="公司产品参数；D为工具直径。"),
        _dp("hans_h", "大族数控INLINE LDI产能", "2025", "片/小时", "[PDF第191页] INLINE LDI最高480片/小时、对位精度±10μm。", value_num=480, company="大族数控", scope="hans_inline_ldi", note="公司规格；片尺寸和工艺条件影响实际产能。"),
        _dp("hans_h", "大族数控INLINE LDI对位精度", "2025", "μm", "[PDF第191页] INLINE LDI最高480片/小时、对位精度±10μm。", value_text="±10", company="大族数控", scope="hans_inline_ldi", note="公司规格。"),
        _dp("hans_h", "大族数控电测最大测试点数", "2025", "测试点", "[PDF第193-197页] 电测幅面650×965mm，最高768,000测试点。", value_num=768000, company="大族数控", scope="hans_electrical_test", note="公司规格。"),
        _dp("hans_h", "大族数控机械成型精度", "2025", "μm", "[PDF第193-197页] 机械成型精度±50μm，激光成型±20μm。", value_text="±50", company="大族数控", scope="hans_routing", note="公司规格。"),
        _dp("dongwei_a", "东威刚性板脉冲VCP适用板厚上限", "2019", "mm", "[PDF第17、74-75页] 刚性板脉冲VCP适用板厚0.1-8.0mm。", value_num=8.0, company="东威科技", scope="dongwei_rigid_pulse_vcp", note="历史公司参数，2024年以前资料，仅作技术基线。"),
        _dp("dongwei_a", "东威刚性板脉冲VCP铜厚均匀性", "2019", "μm", "[PDF第17、74-75页] 铜厚均匀性25μm±2.5μm。", value_text="25±2.5", company="东威科技", scope="dongwei_rigid_pulse_vcp", note="历史公司参数。"),
        _dp("dongwei_a", "东威刚性板脉冲VCP纵横比能力", "2019", "比值", "[PDF第17、74-75页] 纵横比20:1时TP≥95%，16:1时TP≥110%。", value_text="20:1（TP≥95%）", company="东威科技", scope="dongwei_rigid_pulse_vcp", note="历史公司参数；TP定义按发行人原文。"),
        _dp("cfmee_h", "芯碁微装PCB直接成像有效产能", "2025", "台/年", "[PDF第12、143页] 2025年有效产能580台、实际产量581台、利用率100.2%。", value_num=580, company="芯碁微装", scope="cfmee_all_direct_imaging_capacity", note="包含PCB DI与半导体直写，不能全部视为高多层PCB产能。"),
        _dp("cfmee_h", "芯碁微装PCB直接成像产能利用率", "2025", "%", "[PDF第12、143页] 2025年有效产能580台、实际产量581台、利用率100.2%。", value_num=100.2, company="芯碁微装", scope="cfmee_all_direct_imaging_capacity", note="公司实际值；产品混合口径。"),
        _dp("cfmee_h", "芯碁微装前五大客户收入占比", "2025", "%", "[PDF第146-148页] 2025年前五大客户收入5.856亿元，占41.6%。", value_num=41.6, company="芯碁微装", scope="cfmee_customer_concentration", note="客户匿名，不得反推名称。"),
        _dp("cfmee_h", "芯碁微装中国内地收入占比", "2025", "%", "[PDF第146-148页] 2025年中国内地收入11.335亿元，占80.5%。", value_num=80.5, company="芯碁微装", scope="cfmee_revenue_region", note="公司收入地区不等于地区市场规模。"),
    ])
    for project in DOWNSTREAM_PROJECTS:
        equipment_yi = project["capacity_wan_sqm"] * 10000 * project["equipment_yuan_per_sqm"] / 1e8
        rows += [
            _dp("guangfa_202607", f"{project['company']}{project['project']}总投资", "2023-2026项目", "亿元人民币", "[PDF第24-26页] 广发证券转引项目总投资、规划产能及机器设备投入强度。", value_num=project["investment_yi"], company=None, forecast=True, scope=f"downstream_project_{project['company']}", as_of="2026-07-01", note="卖方转引项目资料；as_of为汇总报告发布日，项目本身跨多期；正式采购判断仍应回到发行人公告。"),
            _dp("guangfa_202607", f"{project['company']}{project['project']}规划产能", "2023-2026项目", "万平方米/年", "[PDF第24-26页] 广发证券转引项目总投资、规划产能及机器设备投入强度。", value_num=project["capacity_wan_sqm"], forecast=True, scope=f"downstream_project_{project['company']}", as_of="2026-07-01", note="项目规划值；as_of为汇总报告发布日，产品结构不同。"),
            _dp("guangfa_202607", f"{project['company']}{project['project']}机器设备投资强度", "2023-2026项目", "元/平方米年产能", "[PDF第24-26页] 广发证券转引项目总投资、规划产能及机器设备投入强度。", value_num=project["equipment_yuan_per_sqm"], forecast=True, scope=f"downstream_project_{project['company']}", as_of="2026-07-01", note="项目口径；as_of为汇总报告发布日；高端HDI/SLP项目不能直接代替18+高多层产线。"),
            _dp("guangfa_202607", f"{project['company']}{project['project']}机器设备投资额估算", "2023-2026项目", "亿元人民币", "[PDF第24-26页] 项目规划产能与单位产能机器设备投入强度。", value_num=round(equipment_yi, 2), forecast=True, method="inferred", scope=f"downstream_project_{project['company']}", as_of="2026-07-01", note=f"公式={project['capacity_wan_sqm']}万平方米×10000×{project['equipment_yuan_per_sqm']}元/平方米÷1e8={equipment_yi:.2f}亿元；as_of为汇总报告发布日；卖方转引输入。"),
        ]
    countable_subtotal = 0.0
    for item in STANDARD_LINE:
        if item["investment_yi"] is None:
            rows.append(_dp(
                "guangfa_202607", f"无产能尺度示意设备篮子{item['category']}可计算状态", "2026E", "状态",
                "[PDF第23-26页] 公开项目未披露可把不同检测路线或自动化模块还原为同一产线BOM的数量与单价。",
                value_text="目前没有同口径数量、单价或完整BOM，未计入可计数小计", forecast=True,
                method="inferred", scope="illustrative_18plus_equipment_basket_v2",
                note=f"{item['basis']}；不使用残差补数。",
            ))
            continue
        countable_subtotal += item["investment_yi"]
        rows.append(_dp(
            "guangfa_202607", f"无产能尺度示意设备篮子{item['category']}投资额", "2026E", "亿元人民币",
            "[PDF第23-26页] 红板采购样本及多个项目设备均价；本研究只设示意设备数量。",
            value_num=item["investment_yi"], forecast=True, method="inferred",
            scope="illustrative_18plus_equipment_basket_v2",
            note=f"本研究估算；公式={item['count']}×{item['asp_wan']}万元÷10000≈{item['investment_yi']}亿元（四舍五入至0.001亿元）。{item['basis']}；不对应任何月产能、板尺寸或稼动率。",
        ))
    core_subtotal = countable_subtotal - next(
        item["investment_yi"] for item in STANDARD_LINE if item["category"].startswith("激光钻孔")
    )
    rows.append(_dp(
        "guangfa_202607", "无产能尺度示意设备篮子可计数公开样本部分", "2026E", "亿元人民币",
        "[PDF第23-26页] 公开客户采购和产品大类均价只能形成不完整、无产能尺度的示意篮子。",
        value_num=round(countable_subtotal, 3), forecast=True, method="inferred",
        scope="illustrative_18plus_equipment_basket_v2",
        note=f"公式=七项有数量和价格锚的示意值相加={countable_subtotal:.3f}亿元；其中可选HDI激光模块0.636亿元，不含该模块为{core_subtotal:.3f}亿元。AOI/AVI/X-ray和其他湿制程/自动化未用残差补数；不是完整整线或采购预算。",
    ))
    return rows


def financial_claims(financial: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    name_by_key = {
        item.get("listed_key"): item["name"]
        for item in COMPANY_IDENTITIES
        if item.get("listed_key") and item.get("ticker")
    }
    for company in financial["companies"]:
        key = company["key"]
        name = name_by_key.get(key, company["name"])
        provider = company["market_snapshot"].get("source") or company["financial_series"].get("source")
        source = "tushare" if provider == "tushare" or company["market"] == "A股" else "yfinance"
        market = company["market_snapshot"]
        market_date = market.get("trade_date") or AS_OF_DATE
        market_fields = [
            ("市值", "market_cap_cny", "亿元人民币"), ("PE_TTM", "pe_ttm", "倍"),
            ("PB", "pb", "倍"), ("PS_TTM", "ps_ttm", "倍"), ("ROE", "roe", "%"),
            ("ROA", "roa", "%"), ("EPS_TTM", "eps_ttm", f"{market.get('per_share_currency') or '原币'}/股"),
            ("BPS_MRQ", "bps_mrq", f"{market.get('per_share_currency') or '原币'}/股"),
        ]
        for label, field, unit in market_fields:
            value = market.get(field)
            if value is None:
                continue
            reconciliation = market.get("bps_basis_reconciliation") or {}
            if field == "bps_mrq" and reconciliation.get("direct_current_pb_recalculation_allowed") is False:
                continue
            field_date = (market.get("field_as_of") or {}).get(field) or market_date
            method_meta = (market.get("field_methods") or {}).get(field) or {}
            extraction_method = method_meta.get("extraction_method") or "web_fetch"
            method_note: list[str] = []
            if method_meta.get("formula"):
                method_note.append(f"公式={method_meta['formula']}")
            if method_meta.get("inputs"):
                method_note.append(f"输入={json.dumps(method_meta['inputs'], ensure_ascii=False, sort_keys=True)}")
            if method_meta.get("basis"):
                method_note.append(f"口径={method_meta['basis']}")
            rows.append(_dp(
                source, f"{name}{label}", field_date, unit,
                f"{provider} {company['ticker']} @{field_date}: {field}={value}。",
                value_num=value, company=name, method=extraction_method,
                scope=f"company_market_{field}", as_of=field_date,
                note="；".join(method_note) if method_note else "结构化行情/财务接口原值；行情与财务期按field_as_of分别标注。",
            ))

        periods = {row.get("period"): row for row in company["financial_series"].get("periods") or []}
        for period in ("2023", "2024", "2025", "2026Q1"):
            row = periods.get(period)
            if not row:
                continue
            basis = row.get("statement_basis") or "provider_statement"
            currency = row.get("currency") or ""
            end_date = row.get("end_date") or ""
            report_date = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}" if len(end_date) == 8 else AS_OF_DATE
            if key == "cohu" and period == "2026Q1":
                report_date = market.get("financial_metrics_as_of") or "2026-03-28"
            if key == "kla" and period == "2026Q1":
                display_period = "FY2026Q3（截至2026-03-31）"
            elif key == "cohu" and period == "2026Q1":
                display_period = "2026Q1（截至2026-03-28）"
            else:
                display_period = period

            for label, field in (("营业收入", "revenue"), ("净利润", "net_income"), ("研发费用", "rd_expense"), ("经营现金流", "operating_cash_flow"), ("资本开支", "capex")):
                obj = row.get(field) or {}
                value = obj.get("cny_yi")
                if value is None:
                    continue
                inferred = currency != "CNY"
                local_yi = obj.get("local_yi")
                usd_yi = obj.get("usd_yi")
                fx_to_cny = obj.get("fx_to_cny") or company["financial_series"].get("fx_to_cny")
                fx_as_of = company["financial_series"].get("fx_as_of")
                currency_views = (
                    f"原币{local_yi}亿{currency}，人民币{value}亿元"
                    + (f"，美元{usd_yi}亿美元" if usd_yi is not None else "")
                )
                rows.append(_dp(
                    source, f"{name}{label}", display_period, "亿元人民币",
                    f"{row.get('source')} {company['ticker']} {row.get('end_date')}: {label}{currency_views}。",
                    value_num=value, company=name, method="inferred" if inferred else "web_fetch",
                    scope=f"company_financial_{field}", as_of=report_date,
                    note=(
                        f"原币/人民币/美元三视图：{currency_views}；"
                        + (
                            f"换算公式=原币金额×人民币即期汇率；fx_to_cny={fx_to_cny}，"
                            f"汇率日期/抓取日={fx_as_of}；"
                            if inferred
                            else "人民币原币同币种；"
                        )
                        + f"期间={display_period}，截至={report_date}；{basis}。"
                    ),
                ))

            for label, field in (("毛利率", "gross_margin"), ("净利率", "net_margin"), ("ROE", "roe"), ("研发费用率", "rd_ratio"), ("营业收入同比", "revenue_yoy"), ("净利润同比", "net_income_yoy")):
                value = row.get(field)
                display_label = label
                if source == "yfinance" and field == "roe":
                    display_label = "单季净利润/期末权益（非年化）" if "Q" in period else "净利润/期末权益"
                prior_label = str(int(period[:4]) - 1) + (period[4:] if "Q" in period else "")
                prior_row = periods.get(prior_label) or {}
                input_field = "revenue" if field == "revenue_yoy" else "net_income" if field == "net_income_yoy" else None
                current_obj = row.get(input_field) or {} if input_field else {}
                prior_obj = prior_row.get(input_field) or {} if input_field else {}
                current_input = current_obj.get("local_yi") if input_field else None
                prior_input = prior_obj.get("local_yi") if input_field else None
                current_raw = current_obj.get("local_raw") if input_field else None
                prior_raw = prior_obj.get("local_raw") if input_field else None

                if field in {"revenue_yoy", "net_income_yoy"}:
                    if current_input is None or prior_input in (None, 0):
                        continue
                elif value is None:
                    continue

                net_income_yoy_meta = None
                if field == "net_income_yoy":
                    net_income_yoy_meta = row.get("net_income_yoy_meta")
                    if not isinstance(net_income_yoy_meta, dict):
                        raise ValueError(
                            f"{company['ticker']} {display_period} 缺少结构化 net_income_yoy_meta；"
                            "为防止误用provider原值，生成终止"
                        )
                    if not net_income_yoy_meta.get("valid_for_comparison"):
                        state_label = net_income_yoy_meta.get("state_label") or "无法比较"
                        provider_original = net_income_yoy_meta.get("provider_original_value_pct")
                        legacy_derived = net_income_yoy_meta.get("legacy_snapshot_derived_value_pct")
                        provenance = (
                            f"provider原始同比={provider_original}%"
                            if provider_original is not None
                            else (
                                f"旧快照派生同比={legacy_derived}%（非provider直接披露）"
                                if legacy_derived is not None
                                else "provider未直接披露同比"
                            )
                        )
                        rows.append(_dp(
                            source,
                            f"{name}净利润同比变化",
                            display_period,
                            "状态",
                            f"{row.get('source')} {company['ticker']} {row.get('end_date')}: "
                            f"本期净利润{current_input}亿{currency}，上年同期{prior_input}亿{currency}；"
                            f"{provenance}。",
                            value_text=state_label,
                            company=name,
                            method="inferred",
                            scope="company_financial_net_income_yoy_status",
                            as_of=report_date,
                            note=(
                                f"state={net_income_yoy_meta.get('state')}；"
                                "valid_for_comparison=false；"
                                f"输入：本期净利润={current_input}亿{currency}，"
                                f"上年同期={prior_input}亿{currency}；{provenance}仅保留溯源，"
                                "绝不作为增长率、排序或跨公司比较输入。"
                            ),
                        ))
                        continue

                if field == "net_income_yoy":
                    value = net_income_yoy_meta.get("comparison_value_pct")
                    if value is None:
                        raise ValueError(
                            f"{company['ticker']} {display_period} 标记可比较但缺少 comparison_value_pct"
                        )
                    formula_note = (
                        f"公式={net_income_yoy_meta.get('formula')}；"
                        f"结构化输入={current_input}亿{currency}/{prior_input}亿{currency}；"
                        "valid_for_comparison=true；provider原始同比不作为计算输入"
                    )
                    extraction_method = "inferred"
                elif field == "revenue_yoy":
                    if current_raw is not None and prior_raw is not None:
                        value = round((current_raw / prior_raw - 1) * 100, 2)
                        formula_note = (
                            "公式=（本期值÷上年同期值-1）×100%；"
                            f"未取整输入={current_raw}{currency}/{prior_raw}{currency}"
                        )
                    else:
                        rounded_change = rounded_pct_change_with_interval(current_input, prior_input)
                        if rounded_change is None:
                            continue
                        value = rounded_change["value"]
                        formula_note = (
                            "公式=（本期值÷上年同期值-1）×100%；"
                            f"展示输入={current_input}亿{currency}/{prior_input}亿{currency}；"
                            "当前快照未保存接口未取整金额，本研究直接用四舍五入至0.01亿原币的"
                            "展示输入计算，因此结果可按展示值复算，但可能与接口按未取整金额计算的同比不同"
                        )
                        if rounded_change["unstable"]:
                            high_text = "无有限上界" if not math.isfinite(float(rounded_change["high"])) else f"{rounded_change['high']}%"
                            rows.append(_dp(
                                source,
                                f"{name}{display_label}变化",
                                display_period,
                                "状态",
                                f"{row.get('source')} {company['ticker']} {row.get('end_date')}: 展示输入为本期{current_input}亿{currency}、上年同期{prior_input}亿{currency}。",
                                value_text="低基数，百分比不稳定",
                                company=name,
                                method="inferred",
                                scope=f"company_financial_{field}_status",
                                as_of=report_date,
                                note=(
                                    f"展示值点估计={rounded_change['value']}%；按每个输入±0.005亿原币的四舍五入范围，"
                                    f"同比约为{rounded_change['low']}%至{high_text}，区间宽度超过20个百分点；"
                                    "不展示单一同比百分比，改看绝对金额和净利率。"
                                ),
                            ))
                            continue
                    extraction_method = "inferred"
                elif field == "net_margin":
                    margin_meta = row.get("net_margin_meta") or {}
                    formula_note = (
                        f"公式={margin_meta.get('formula') or '同期间归母/可归属净利润÷营业收入×100%'}；"
                        f"期间={margin_meta.get('period') or display_period}，"
                        f"截至={margin_meta.get('end_date') or report_date}；"
                        f"净利润口径={margin_meta.get('net_income_basis') or 'snapshot stored net income'}；"
                        f"provider原比率={margin_meta.get('provider_original_value_pct')}%仅保留溯源，"
                        "不作为本研究净利率输出"
                    )
                    extraction_method = "inferred"
                elif field == "gross_margin":
                    margin_meta = row.get("gross_margin_meta") or {}
                    formula_note = (
                        f"口径={margin_meta.get('basis') or '报表毛利率字段'}；"
                        f"期间={margin_meta.get('period') or display_period}，"
                        f"截至={margin_meta.get('end_date') or report_date}"
                    )
                    extraction_method = (
                        "web_fetch" if margin_meta.get("provider_reported") else "inferred"
                    )
                elif source == "yfinance":
                    formula_by_field = {
                        "gross_margin": "毛利÷营业收入×100%",
                        "net_margin": "净利润÷营业收入×100%",
                        "roe": "净利润÷期末归属权益×100%",
                        "rd_ratio": "研发费用绝对值÷营业收入绝对值×100%",
                    }
                    formula_note = f"公式={formula_by_field.get(field, field)}；输入来自同一yfinance报表期"
                    extraction_method = "inferred"
                else:
                    formula_note = "Tushare fina_indicator接口值"
                    extraction_method = "web_fetch"
                rows.append(_dp(
                    source, f"{name}{display_label}", display_period, "%",
                    f"{row.get('source')} {company['ticker']} {row.get('end_date')}: {display_label}={value}%。",
                    value_num=value, company=name, method=extraction_method,
                    scope=f"company_financial_{field}", as_of=report_date,
                    note=f"{formula_note}；{basis}；跨市场会计准则和财年不同。",
                ))
    return rows


def source_key_arguments() -> list[dict[str, str]]:
    return [
        {"source_ref": "hans_h", "argument": "全部PCB设备市场2025-2029年增长由钻孔、曝光、检测、区域扩产和资本密集度共同推动；该总量不能直接改名为18层以上市场。", "sentiment": "中性", "dimension": "market_scope"},
        {"source_ref": "cfmee_h", "argument": "PCB直接成像子市场集中度显著高于全部PCB设备，但两者分母不同，不能横向比较后直接断言所有曝光技术路线同等集中。", "sentiment": "中性", "dimension": "competition"},
        {"source_ref": "dongwei_a", "argument": "脉冲VCP的板厚、纵横比与铜厚均匀性参数说明深孔电镀是高多层可靠性瓶颈；历史参数需要当前型号复核。", "sentiment": "中性", "dimension": "technology"},
        {"source_ref": "hans_a", "argument": "A股招股书提供早期机械钻孔、激光钻孔、LDI和测试设备的商业化节点及历史参数，适合做路线演进基线，不代表当前规格。", "sentiment": "中性", "dimension": "technology_history"},
        {"source_ref": "cfmee_a", "argument": "A股招股书证明芯碁直接成像历史客户与产品大类销售，但不能据此确认当前型号或18层以上用途。", "sentiment": "中性", "dimension": "customer_history"},
        {"source_ref": "guangfa_202607", "argument": "客户项目样本显示高端HDI/SLP设备投资强度显著高于常规项目，但不能用HDI项目单位投资替代18层以上高多层标准线。", "sentiment": "中性", "dimension": "capex"},
        {"source_ref": "dongwu_202602", "argument": "东吴证券把高多层机械通孔/背钻与HDI激光微孔分开，并把设备量价增量视为机构研究判断，而非客户采购事实。", "sentiment": "中性", "dimension": "technology_route"},
        {"source_ref": "kla_pcb", "argument": "KLA当前PCB与IC载板产品继承Orbotech的AOI、直接成像与制程控制组合，品牌和集团财务必须分开描述。", "sentiment": "中性", "dimension": "entity_resolution"},
        {"source_ref": "kla_ttm", "argument": "KLA官方披露TTM采用Neos 800阻焊方案，这是具名客户案例，但不能外推到其他型号或所有高多层产线。", "sentiment": "中性", "dimension": "customer_validation"},
        {"source_ref": "mks_esi", "argument": "ESI是MKS旗下PCB激光微加工品牌，不是独立上市主体；产品证据归品牌，财务估值归MKS。", "sentiment": "中性", "dimension": "entity_resolution"},
        {"source_ref": "mycronic_atg", "argument": "Mycronic于2021年从Cohu收购atg Luther & Maelzer，当前atg业务归Mycronic，Cohu仅是历史卖方。", "sentiment": "中性", "dimension": "entity_resolution"},
        {"source_ref": "nidec_history", "argument": "Nidec-Read于2014年成为Nidec全资子公司，并于2023年更名Nidec Advance Technology，无独立上市财务。", "sentiment": "中性", "dimension": "entity_resolution"},
        {"source_ref": "amada_via", "argument": "Via Mechanics于2025年成为AMADA全资子公司，当前估值和集团财务归AMADA。", "sentiment": "中性", "dimension": "entity_resolution"},
        {"source_ref": "ushio_via", "argument": "Via Mechanics在2018年已出售曝光业务，当前产品卡位不能沿用旧研报中的曝光业务描述。", "sentiment": "中性", "dimension": "entity_resolution"},
        {"source_ref": "camtek_sale", "argument": "Camtek于2017年完成出售PCB业务，当前主营半导体检测，不应列入当前PCB设备估值可比组。", "sentiment": "中性", "dimension": "entity_resolution"},
        {"source_ref": "mitsubishi_drill", "argument": "三菱电机当前官方PCB钻孔产品以激光钻孔为主，集团财务未单独披露PCB设备分部。", "sentiment": "中性", "dimension": "company_scope"},
        {"source_ref": "via_solution", "argument": "Via Mechanics当前官方方案覆盖机械钻孔、激光钻孔和成型，其高多层卡位应以钻孔/成型而非已出售曝光业务为主。", "sentiment": "中性", "dimension": "company_scope"},
        {"source_ref": "jcu_products", "argument": "JCU同时销售表面处理化学品和部分自动化设备，集团收入不能全部计入PCB设备市场。", "sentiment": "中性", "dimension": "company_scope"},
        {"source_ref": "lpkf_scope", "argument": "LPKF的PCB产品证据主要落在原型制作和激光细分，公开资料不足以证明其属于高产量18层以上核心产线供应商。", "sentiment": "中性", "dimension": "company_scope"},
    ]


def write_claims(
    output: Path | None = None,
    *,
    financial_path: Path = FINANCIAL_PATH,
) -> dict[str, Any]:
    financial = json.loads(financial_path.read_text(encoding="utf-8"))
    data_points = [*market_claims(), *company_product_claims(), *financial_claims(financial)]
    payload = {
        "meta": {
            "industry": "PCB专用设备",
            "run_tag": RUN_TAG,
            "research_question": "18层以上高多层PCB专用设备的工艺、市场、竞争、壁垒、公司经营和估值如何？",
            "scope": {"focus": "18层以上高多层PCB", "market_data": "全部PCB设备与细分设备，严格分开"},
        },
        "sources": [_source_payload(spec) for spec in SOURCES],
        "data_points": data_points,
        "key_arguments": source_key_arguments(),
    }
    CLAIMS_DIR.mkdir(parents=True, exist_ok=True)
    output = output or (CLAIMS_DIR / f"{RUN_TAG}_01_full_claims.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"path": output, "sha256": _sha256(output), "data_point_count": len(data_points)}


def write_calculation_ledger() -> dict[str, Any]:
    countable_rows = [row for row in STANDARD_LINE if row["investment_yi"] is not None]
    countable_total = round(sum(row["investment_yi"] for row in countable_rows), 3)
    optional_hdi = next(row["investment_yi"] for row in countable_rows if row["category"].startswith("激光钻孔"))
    core_without_hdi = round(countable_total - optional_hdi, 3)
    regional_extrapolation = [
        {
            "region": region,
            "input_2029_usd_m": REGIONAL_MARKET_USD_M[2029][region],
            "source_cagr_pct": cagr,
            "formula": "round(input_2029_usd_m * (1 + source_cagr_pct / 100))",
            "recalculated_2030_usd_m": round(REGIONAL_MARKET_USD_M[2029][region] * (1 + cagr / 100)),
            "stored_2030_usd_m": REGIONAL_MARKET_USD_M[2030][region],
        }
        for region, cagr in REGIONAL_CAGR_2025_2029.items()
    ]
    equipment_extrapolation = [
        {
            "category": category,
            "input_2029_usd_m": EQUIPMENT_MARKET_USD_M[2029][category],
            "source_cagr_pct": cagr,
            "formula": "round(input_2029_usd_m * (1 + source_cagr_pct / 100))",
            "recalculated_2030_usd_m": round(EQUIPMENT_MARKET_USD_M[2029][category] * (1 + cagr / 100)),
            "stored_2030_usd_m": EQUIPMENT_MARKET_USD_M[2030][category],
        }
        for category, cagr in EQUIPMENT_CAGR_2025_2029.items()
    ]
    ledger = {
        "schema_version": "pcb_equipment.calculation_ledger.v1",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "calculations": [
            {
                "name": "2030全球PCB专用设备市场单年外推",
                "formula": "2029 market * (1 + 2025-2029 CAGR)",
                "inputs": {"2029_usd_m": 11388, "cagr": 0.086},
                "result_usd_m": 12367,
                "recalculated": round(11388 * 1.086),
                "limitation": "非Prismark/CIC原表；仅用于满足2030观察窗，不应被视为机构预测。",
            },
            {
                "name": "2030地区市场单年外推明细",
                "rows": regional_extrapolation,
                "component_sum_2030_usd_m": sum(row["stored_2030_usd_m"] for row in regional_extrapolation),
                "global_total_2030_usd_m": GLOBAL_MARKET_USD_M[2030],
                "rounding_difference_usd_m": sum(row["stored_2030_usd_m"] for row in regional_extrapolation) - GLOBAL_MARKET_USD_M[2030],
                "limitation": "各地区按来源披露的一位小数CAGR分别外推并取整，合计比总量外推高23百万美元；这是分项CAGR舍入传播，不强行配平。",
            },
            {
                "name": "2030设备类别市场单年外推明细",
                "rows": equipment_extrapolation,
                "component_sum_2030_usd_m": sum(row["stored_2030_usd_m"] for row in equipment_extrapolation),
                "global_total_2030_usd_m": GLOBAL_MARKET_USD_M[2030],
                "rounding_difference_usd_m": sum(row["stored_2030_usd_m"] for row in equipment_extrapolation) - GLOBAL_MARKET_USD_M[2030],
                "limitation": "各设备类别按来源披露的一位小数CAGR分别外推并取整，合计比总量外推高16百万美元；这是分项CAGR舍入传播，不强行配平。",
            },
            {
                "name": "无产能尺度的示意设备篮子可计数部分",
                "formula": "sum(hypothetical_count * public_category_average_price / 10000)，只统计可明确列示数量与价格锚的七项",
                "inputs": countable_rows,
                "countable_with_optional_hdi_yi_cny": countable_total,
                "countable_without_optional_hdi_yi_cny": core_without_hdi,
                "optional_hdi_module_yi_cny": optional_hdi,
                "single_factor_check": {"mechanical_drill_quantity_plus_or_minus_20pct_yi_cny": 0.468},
                "excluded_unpriced_rows": [row for row in STANDARD_LINE if row["investment_yi"] is None],
                "limitation": "没有月产能、板尺寸、产品结构、节拍、稼动率、良率、备机率和完整BOM；不是标准产线总额、采购预算或预测区间。AOI/AVI/X-ray不可互换，其他湿制程和自动化不以残差补数。",
            },
            {
                "name": "下游项目机器设备投资额",
                "formula": "capacity_wan_sqm * 10,000 * equipment_yuan_per_sqm / 100,000,000",
                "results": [
                    {**row, "equipment_investment_yi": round(row["capacity_wan_sqm"] * 10000 * row["equipment_yuan_per_sqm"] / 1e8, 2)}
                    for row in DOWNSTREAM_PROJECTS
                ],
                "limitation": "输入来自卖方转引项目披露，且多数为HDI/SLP，不可替代18层以上高多层标准产线。",
            },
        ],
    }
    output = CACHE_DIR / "calculation_ledger.json"
    output.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"path": output, "sha256": _sha256(output)}


def _layout(title: str, height: int = 620) -> dict[str, Any]:
    return {
        "title": {"text": title, "x": 0.02, "xanchor": "left"}, "template": "plotly_white",
        "height": height, "font": {"family": "Microsoft YaHei, Arial", "size": 14, "color": "#17212b"},
        "margin": {"l": 80, "r": 45, "t": 85, "b": 85},
        "legend": {"orientation": "h", "y": -0.20, "x": 0},
    }


def _write_figure(fig: go.Figure, filename: str) -> None:
    path = VIS_DIR / filename
    fig.update_layout(width=1280)
    # The installed Kaleido build can hang on this Windows host.  The project
    # already has a deterministic Chromium capture path, so use it directly.
    from playwright.sync_api import sync_playwright
    render = CACHE_DIR / "plotly_render"
    render.mkdir(parents=True, exist_ok=True)
    html_path = render / f"{Path(filename).stem}.html"
    fig.write_html(str(html_path), include_plotlyjs=True, full_html=True, config={"displayModeBar": False})
    chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=chrome, args=["--disable-gpu"])
        page = browser.new_page(viewport={"width": 1320, "height": int(fig.layout.height or 620) + 60}, device_scale_factor=1.2)
        page.goto(html_path.resolve().as_uri(), wait_until="load")
        page.wait_for_selector(".js-plotly-plot", state="visible")
        page.locator(".js-plotly-plot").first.screenshot(path=str(path), animations="disabled")
        browser.close()


def generate_charts(*, financial_path: Path = FINANCIAL_PATH) -> list[dict[str, Any]]:
    VIS_DIR.mkdir(parents=True, exist_ok=True)
    for stale_name in ("standard_line_waterfall.png", "moat_evidence_radar.png"):
        stale_path = VIS_DIR / stale_name
        if stale_path.exists():
            stale_path.unlink()
    colors = ["#2f6b9a", "#49a078", "#e9a23b", "#d65f5f", "#8267a7", "#76b7b2", "#9c755f", "#bab0ab"]
    years = list(range(2025, 2031))
    fig = go.Figure()
    for i, category in enumerate(EQUIPMENT_MARKET_USD_M[2025]):
        fig.add_bar(x=years, y=[EQUIPMENT_MARKET_USD_M[y][category] / 100 for y in years], name=category, marker_color=colors[i])
    fig.update_layout(**_layout("全球PCB专用设备市场：按设备类别拆分（亿美元）"), barmode="stack")
    fig.update_xaxes(title="2025-2029为Prismark/CIC预测；2030为本研究按各类CAGR单年外推")
    fig.update_yaxes(title="亿美元", gridcolor="#e5e7eb")
    _write_figure(fig, "equipment_market_stack.png")

    regions = list(REGIONAL_MARKET_USD_M[2025])
    fig = go.Figure()
    for i, region in enumerate(regions):
        fig.add_bar(x=years, y=[REGIONAL_MARKET_USD_M[y][region] / 100 for y in years], name=region, marker_color=colors[i])
    fig.update_layout(**_layout("全球PCB专用设备市场：按地区拆分（亿美元）"), barmode="stack")
    fig.update_xaxes(title="欧洲未单列；美洲不等同北美；2030为本研究单年外推")
    fig.update_yaxes(title="亿美元", gridcolor="#e5e7eb")
    _write_figure(fig, "regional_market_stack.png")

    fig = make_subplots(
        rows=1,
        cols=2,
        horizontal_spacing=0.18,
        subplot_titles=("2024年全部PCB专用设备", "2025年PCB直接成像设备"),
    )
    fig.add_trace(
        go.Bar(
            x=[20.9, 23.9, 6.5, 10.1],
            y=["全球市场CR5", "中国市场CR5", "大族全球份额", "大族中国份额"],
            orientation="h",
            marker_color=["#2f6b9a", "#49a078", "#76b7b2", "#8267a7"],
            text=["20.9%", "23.9%", "6.5%", "10.1%"],
            textposition="outside",
            cliponaxis=False,
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Bar(
            x=[59.1, 18.8],
            y=["全球市场CR5", "芯碁全球份额"],
            orientation="h",
            marker_color=["#e9a23b", "#d65f5f"],
            text=["59.1%", "18.8%"],
            textposition="outside",
            cliponaxis=False,
        ),
        row=1,
        col=2,
    )
    fig.update_layout(**_layout("集中度与公司份额：两个市场分开比较", 560), showlegend=False)
    fig.update_layout(margin={"l": 120, "r": 55, "t": 110, "b": 80})
    fig.update_xaxes(title="收入份额（%）", range=[0, 29], gridcolor="#e5e7eb", row=1, col=1)
    fig.update_xaxes(title="收入份额（%）", range=[0, 68], gridcolor="#e5e7eb", row=1, col=2)
    _write_figure(fig, "share_comparison.png")

    basket_rows = [row for row in STANDARD_LINE if row["investment_yi"] is not None]
    investments = [row["investment_yi"] for row in basket_rows]
    fig = go.Figure(go.Waterfall(
        x=[row["category"] for row in basket_rows] + ["可计数部分"],
        y=investments + [sum(investments)], measure=["relative"] * len(investments) + ["total"],
        text=[f"{v:.2f}" for v in investments] + [f"{sum(investments):.2f}"], textposition="outside",
        connector={"line": {"color": "#9ca3af"}}, increasing={"marker": {"color": "#2f6b9a"}}, totals={"marker": {"color": "#d65f5f"}},
    ))
    fig.update_layout(**_layout("无产能尺度示意设备篮子：仅可计数公开样本部分（亿元）", 650), showlegend=False)
    fig.update_xaxes(tickangle=-25)
    fig.update_yaxes(title="亿元人民币", gridcolor="#e5e7eb")
    _write_figure(fig, "equipment_basket_waterfall.png")

    financial = json.loads(financial_path.read_text(encoding="utf-8"))
    bubble = []
    for row in financial["companies"]:
        if row["key"] in {"cohu", "camtek"}:
            continue
        m = row["market_snapshot"]
        periods = {p.get("period"): p for p in row["financial_series"].get("periods") or []}
        y24, y25 = periods.get("2024"), periods.get("2025")
        current = ((y25 or {}).get("revenue") or {}).get("local_yi")
        prior = ((y24 or {}).get("revenue") or {}).get("local_yi")
        change = rounded_pct_change_with_interval(current, prior)
        if (
            not y25 or m.get("market_cap_cny") is None
            or (y25.get("revenue") or {}).get("cny_yi") is None
            or not change or change.get("unstable")
        ):
            continue
        bubble.append((row["name"], m["market_cap_cny"], float(change["value"]), (y25["revenue"] or {})["cny_yi"], row["market"]))
    fig = go.Figure()
    for market, color in [("A股", "#d65f5f"), ("美股", "#2f6b9a"), ("其他", "#49a078")]:
        subset = [x for x in bubble if x[4] == market]
        if not subset:
            continue
        fig.add_trace(go.Scatter(
            x=[x[1] for x in subset], y=[x[2] for x in subset], mode="markers+text", name=market,
            text=[x[0] for x in subset], textposition="top center",
            marker={"size": [max(16, min(65, math.sqrt(abs(x[3])) * 5)) for x in subset], "color": color, "opacity": 0.70, "line": {"color": "white", "width": 1.5}},
            customdata=[[x[3]] for x in subset], hovertemplate="%{text}<br>市值%{x:.1f}亿元<br>2025收入同比%{y:.1f}%<br>2025集团收入%{customdata[0]:.1f}亿元<extra></extra>",
        ))
    fig.update_layout(**_layout("上市主体市值—集团收入增速参照图（不可作为PCB设备份额比较）", 680))
    fig.update_xaxes(
        title="市值（亿元人民币，对数轴）", type="log", gridcolor="#e5e7eb",
        tickmode="array", tickvals=[10, 30, 100, 300, 1000, 3000, 10000],
        ticktext=["10", "30", "100", "300", "1,000", "3,000", "10,000"],
    )
    fig.update_yaxes(title="2025营业收入同比（%）", gridcolor="#e5e7eb")
    _write_figure(fig, "company_bubble.png")

    return [{"path": str(p.relative_to(ROOT)).replace("\\", "/"), "sha256": _sha256(p)} for p in sorted(VIS_DIR.glob("*.png"))]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--derived-only", action="store_true",
        help="Regenerate only calculation ledger/charts and bind the already-ingested immutable claims file.",
    )
    parser.add_argument(
        "--claims-output", type=Path,
        help="Write regenerated claims to a separate correction artifact instead of replacing the default claims path.",
    )
    parser.add_argument(
        "--financial-input",
        type=Path,
        default=FINANCIAL_PATH,
        help="Financial snapshot used by claims/charts; staging runs should pass the normalized v2 snapshot.",
    )
    parser.add_argument(
        "--claims-only",
        action="store_true",
        help="Generate only claims; do not write live cache ledgers or chart assets.",
    )
    args = parser.parse_args()
    if args.derived_only and args.claims_output:
        parser.error("--derived-only and --claims-output cannot be used together")
    if args.claims_only and args.derived_only:
        parser.error("--claims-only and --derived-only cannot be used together")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if args.derived_only:
        claims_path = CLAIMS_DIR / f"{RUN_TAG}_01_full_claims.json"
        if not claims_path.exists():
            raise FileNotFoundError(f"immutable claims file does not exist: {claims_path}")
        claims_payload = json.loads(claims_path.read_text(encoding="utf-8"))
        claims_result = {
            "path": claims_path,
            "sha256": _sha256(claims_path),
            "data_point_count": len(claims_payload.get("data_points") or []),
            "mode": "immutable_existing_claims_with_post_ingest_correction_manifest",
        }
    else:
        claims_result = write_claims(
            args.claims_output.resolve() if args.claims_output else None,
            financial_path=args.financial_input.resolve(),
        )
    if args.claims_only:
        print(json.dumps({
            "claims": {
                **claims_result,
                "path": str(claims_result["path"].resolve()),
            },
            "generation_mode": "claims_only_no_live_cache_or_chart_writes",
        }, ensure_ascii=False, indent=2, default=str))
        return
    result = {
        "claims": claims_result,
        "calculation_ledger": write_calculation_ledger(),
        "charts": generate_charts(financial_path=args.financial_input.resolve()),
    }
    serializable = {
        "claims": {**result["claims"], "path": str(result["claims"]["path"].relative_to(ROOT)).replace("\\", "/")},
        "calculation_ledger": {**result["calculation_ledger"], "path": str(result["calculation_ledger"]["path"].relative_to(ROOT)).replace("\\", "/")},
        "charts": result["charts"],
        "generation_mode": "derived_only" if args.derived_only else "full",
    }
    claim_artifacts: list[dict[str, Any]] = []
    for role, path in (
        ("immutable_ingested_claims", CLAIMS_DIR / f"{RUN_TAG}_01_full_claims.json"),
        ("corrected_final_claims", Path(claims_result["path"])),
    ):
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        claim_artifacts.append({
            "role": role,
            "path": str(path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": _sha256(path),
            "data_point_count": len(payload.get("data_points") or []),
            "key_argument_count": len(payload.get("key_arguments") or []),
        })
    serializable["claim_artifacts"] = claim_artifacts
    manifest = CACHE_DIR / "producer_manifest.json"
    manifest.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({**serializable, "manifest_sha256": _sha256(manifest)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
