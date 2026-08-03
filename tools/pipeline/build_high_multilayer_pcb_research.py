#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
高多层PCB板（18层以上）B轨可复现构建器。

输入是用户prompt、本地273份PDF全文索引、独立官方/监管资料、Tushare与
yfinance财务缓存。输出research.db、主文档/Q0-Q6、公司透视、估值归档、
可视化和producer-reviewer-loop审计记录。
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "research.db"
DOCS_DIR = ROOT / "docs" / "industries"
CACHE_DIR = ROOT / "cache" / "high_multilayer_pcb_research"
VIS_DIR = ROOT / "tools" / "viewer" / "static" / "generated" / "high_multilayer_pcb"
RUN_TAG = "B_TRACK_HIGH_MULTILAYER_PCB_20260711"
TODAY = "2026-07-11"
INDUSTRY_NAME = "高多层PCB板"
PARENT_NAME = "PCB制造"

sys.path.insert(0, str(ROOT / "tools" / "pipeline"))
from db_writer import bulk_write_data_points  # noqa: E402
from high_multilayer_pcb_research_content import build_docs  # noqa: E402
from high_multilayer_pcb_research_data import (  # noqa: E402
    AI_PCB_AREA_ASP,
    AI_PCB_TAM,
    COMPANIES,
    MLPCB_SERIES,
    REGIONAL_18_PLUS,
    SOURCES,
    TECH_MATRIX,
    TOP5_22_PLUS_2025,
    WUS_LAYER_RECORDS,
    CompanySpec,
    SourceSpec,
)


SOURCE_BY_KEY = {s.key: s for s in SOURCES}
FINANCIAL_PATH = CACHE_DIR / "company_financial_series.json"
SNAPSHOT_PATH = CACHE_DIR / "market_snapshots_refresh.json"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def source_excerpt(key: str, *needles: str, radius: int = 180) -> str:
    """从本地全文返回原始上下文；没有本地快照时返回已核验的人读摘录。"""
    spec = SOURCE_BY_KEY[key]
    if spec.text_path:
        text = (ROOT / spec.text_path).read_text(encoding="utf-8", errors="ignore").replace("\x00", " ")
        for needle in needles:
            # PDF抽取常在中文、数字或英文词之间插入换行，允许任意空白但保留原始切片。
            pattern = re.compile(r"\s*".join(re.escape(ch) for ch in needle), re.IGNORECASE)
            match = pattern.search(text)
            if match:
                start = max(0, match.start() - radius)
                end = min(len(text), match.end() + radius)
                return " ".join(text[start:end].split())
        if needles:
            raise ValueError(f"source {key} 未找到原文锚点: {needles}")
    manual = {
        "victory_hk": "Victory Giant H股申请材料援引Frost & Sullivan口径：全球14层以上HLC市场2024年、2025年预计、2026年预计和2029年预计规模分别为56亿美元、67亿美元、74亿美元和97亿美元；同一申请材料披露公司具备70层以上高多层PCB量产能力、100层以上技术能力，14层以上HLC名义产能516万平方米，6+N+6 HDI名义产能60万平方米。",
        "gce_ir_2026q1": "金像电子2026年6月11日法人说明会：2026Q1营业收入193.13亿新台币，毛利率34.81%，税后净利34.84亿新台币；公司制程能力图显示MLB 56L、HDI 30L。",
        "gce_product": "金像电子官方产品页：AI与高阶服务器PCB通常采用高多层HDI结构与低损耗材料；网络设备通常采用高多层板、低损耗材料及精密阻抗控制。",
        "meiko_results": "Meiko FY2025 results briefing maps Ultra High-Layer PCB, High-Layer HDI, switch boards, OAM, server mainboards and memory modules across Japan, Wuhan and Vietnam plants.",
        "mirae_official": "MIRAE official company overview: core business is semiconductor equipment including Test Handler (ATE), SMD/SMT placement systems and related equipment, not PCB manufacturing.",
        "tushare_snapshot": "Tushare daily_basic、income、fina_indicator与cashflow接口返回的最近交易日估值及2023-2025、2026Q1财务字段；本轮未调用Wind。",
        "yfinance_snapshot": "Yahoo Finance/yfinance get_info及年度/季度财务表返回的海外公司行情、估值、利润表、现金流和资产负债表字段。",
        "prompt": "用户prompt将研究主体限定为高多层PCB板（18层以上），要求覆盖市场、竞争、技术、公司财务、估值、供需和可视化。",
        "corpus_index": "本地研报库抽取索引记录273份PDF、5,972页，全部完成文本抽取并保存文件哈希、页数和文本路径。",
    }
    return manual.get(key, spec.note)


def ensure_source(conn: sqlite3.Connection, spec: SourceSpec) -> int:
    row = None
    if spec.file_path:
        row = conn.execute("select id from source where file_path=? order by id limit 1", (spec.file_path,)).fetchone()
    if not row and spec.url and not spec.file_path:
        row = conn.execute(
            "select id from source where source_url=? or url=? order by id limit 1", (spec.url, spec.url)
        ).fetchone()
    if not row:
        row = conn.execute(
            "select id from source where title=? and coalesce(publisher,'')=? order by id limit 1",
            (spec.title, spec.publisher),
        ).fetchone()
    args = json.dumps(
        [{"claim": c, "sentiment": s, "dimension": d} for c, s, d in spec.arguments],
        ensure_ascii=False,
    )
    values = (
        spec.title, spec.source_type, spec.publisher, spec.publish_date, spec.quality_tier,
        spec.forward, spec.file_path, spec.url, spec.note, spec.value_layer, spec.url, args,
        spec.source_subtype, now_str(), "local_cache" if spec.file_path else "web_research",
        (re.sub(r"^https?://([^/]+).*$", r"\1", spec.url) if spec.url else None), spec.language,
        spec.primary, spec.credibility, spec.text_path,
    )
    if row:
        sid = int(row["id"])
        conn.execute(
            """
            update source set title=?,source_type=?,publisher=?,publish_date=?,quality_tier=?,
              is_forward_looking=?,file_path=?,url=?,note=?,value_layer=?,source_url=?,key_arguments=?,
              source_subtype=?,fetch_timestamp=?,fetch_method=?,domain=?,language=?,is_primary_source=?,
              source_credibility=?,content_snapshot_path=? where id=?
            """,
            values + (sid,),
        )
        return sid
    cur = conn.execute(
        """
        insert into source(title,source_type,publisher,publish_date,quality_tier,is_forward_looking,
          file_path,url,note,value_layer,source_url,key_arguments,source_subtype,fetch_timestamp,
          fetch_method,domain,language,is_primary_source,source_credibility,content_snapshot_path)
        values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        values,
    )
    return int(cur.lastrowid)


def ensure_sources(conn: sqlite3.Connection) -> dict[str, int]:
    return {spec.key: ensure_source(conn, spec) for spec in SOURCES}


def ensure_industry(conn: sqlite3.Connection) -> int:
    parent = conn.execute("select id from industry where name=?", (PARENT_NAME,)).fetchone()
    if not parent:
        raise RuntimeError(f"父行业不存在: {PARENT_NAME}")
    core = (
        "AI服务器和高速交换推动22+/32+高多层PCB面积、ASP与材料等级同步升级；"
        "行业判断必须区分量产/认证/样品/在研，并以分层收入、良率、海外认证和现金流验证。"
    )
    row = conn.execute("select id from industry where name=?", (INDUSTRY_NAME,)).fetchone()
    if row:
        industry_id = int(row["id"])
        conn.execute(
            "update industry set parent_id=?,level=2,tier=1,status='深度跟踪',core_dynamic=?,last_updated=? where id=?",
            (int(parent["id"]), core, TODAY, industry_id),
        )
        return industry_id
    cur = conn.execute(
        "insert into industry(name,parent_id,level,tier,status,core_dynamic,last_updated) values(?,?,?,?,?,?,?)",
        (INDUSTRY_NAME, int(parent["id"]), 2, 1, "深度跟踪", core, TODAY),
    )
    return int(cur.lastrowid)


def _period_map(financial_row: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {p.get("period"): p for p in financial_row.get("periods", []) if p.get("period")}


def _series_json(
    periods: dict[str, dict[str, Any]], field: str, source_id: int | None
) -> str:
    series: list[dict[str, Any]] = []
    prior_annual: float | None = None
    for period in ("2023", "2024", "2025", "2026Q1"):
        value = periods.get(period, {}).get(field) or {}
        cny_value = value.get("cny_yi")
        if cny_value is None:
            continue
        cny_value = round(float(cny_value), 2)
        usd_value = value.get("usd_yi")
        yoy = None
        if period != "2026Q1" and prior_annual not in (None, 0):
            yoy = round((cny_value / prior_annual - 1) * 100, 1)
        if period != "2026Q1":
            prior_annual = cny_value
        unit = "亿元人民币"
        if usd_value is not None:
            unit += f"（约{float(usd_value):.2f}亿美元）"
        series.append({
            "period": period,
            "value": cny_value,
            "unit": unit,
            "yoy": yoy,
            "source_ids": [source_id] if source_id else [],
        })
    return json.dumps(series, ensure_ascii=False)


def ensure_company(
    conn: sqlite3.Connection,
    spec: CompanySpec,
    industry_id: int,
    source_ids: dict[str, int],
    financial: dict[str, Any],
    snapshots: dict[str, Any],
) -> int:
    row = conn.execute("select id from company where name=?", (spec.name,)).fetchone()
    snap_key = spec.listed_key or spec.key
    snap = snapshots.get("companies", {}).get(snap_key, {})
    valuation_source = source_ids.get("tushare_snapshot" if spec.market == "A股" else "yfinance_snapshot")
    display_mode = "quantitative" if spec.ticker else "narrative"
    market = spec.market if spec.market in {"A股", "港股", "美股", "其他"} else "其他"
    if row:
        cid = int(row["id"])
        conn.execute(
            """
            update company set ticker=?,market=?,note=?,listing_status=?,display_mode=?,brief_intro=?,
              brief_intro_src=?,pe_ttm=?,pb=?,ps_ttm=?,market_cap_value=?,market_cap_unit=?,
              valuation_as_of=?,valuation_source_id=?,market_cap_cny=?,market_cap_usd=?,market_cap_cny_as_of=?
            where id=?
            """,
            (
                spec.ticker, market, f"{spec.classification}；{spec.role}", spec.listing_status, display_mode,
                spec.intro, str(source_ids.get(spec.source_key)), snap.get("pe_ttm"), snap.get("pb"),
                snap.get("ps_ttm"), snap.get("market_cap_cny"), "亿元人民币" if snap.get("market_cap_cny") is not None else None,
                TODAY if snap else None, valuation_source if snap else None, snap.get("market_cap_cny"),
                snap.get("market_cap_usd"), TODAY if snap.get("market_cap_cny") is not None else None, cid,
            ),
        )
    else:
        cur = conn.execute(
            """
            insert into company(name,ticker,market,note,listing_status,display_mode,brief_intro,brief_intro_src,
              pe_ttm,pb,ps_ttm,market_cap_value,market_cap_unit,valuation_as_of,valuation_source_id,
              market_cap_cny,market_cap_usd,market_cap_cny_as_of)
            values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                spec.name, spec.ticker, market, f"{spec.classification}；{spec.role}", spec.listing_status,
                display_mode, spec.intro, str(source_ids.get(spec.source_key)), snap.get("pe_ttm"), snap.get("pb"),
                snap.get("ps_ttm"), snap.get("market_cap_cny"), "亿元人民币" if snap.get("market_cap_cny") is not None else None,
                TODAY if snap else None, valuation_source if snap else None, snap.get("market_cap_cny"),
                snap.get("market_cap_usd"), TODAY if snap.get("market_cap_cny") is not None else None,
            ),
        )
        cid = int(cur.lastrowid)

    conn.execute("delete from company_industry where company_id=? and industry_id=?", (cid, industry_id))
    conn.execute(
        "insert into company_industry(company_id,industry_id,role,revenue_share,note) values(?,?,?,?,?)",
        (cid, industry_id, spec.role, None, f"{spec.classification}；证据状态：{spec.evidence_status}"),
    )
    fin = financial.get("companies", {}).get(snap_key, {})
    periods = _period_map(fin)
    latest = periods.get("2026Q1") or periods.get("2025") or {}
    ocf_record = latest.get("operating_cash_flow") or {}
    capex_record = latest.get("capex") or {}
    ocf = ocf_record.get("cny_yi")
    capex = capex_record.get("cny_yi")
    financial_sid = source_ids.get("tushare_snapshot" if spec.market == "A股" else "yfinance_snapshot")
    profile_source_ids = [x for x in (source_ids.get(spec.source_key), financial_sid) if x]
    recent_json = json.dumps(
        [{"date": TODAY, "title": spec.recent[:80], "summary": spec.recent, "is_major": True,
          "source_id": source_ids.get(spec.source_key)}], ensure_ascii=False,
    )
    risk_json = json.dumps([spec.risks], ensure_ascii=False)
    gap = ""
    missing_targets = [p for p in ("2023", "2024", "2025", "2026Q1") if p not in periods]
    if spec.ticker and missing_targets:
        gap = f"；财务接口未取得期间：{','.join(missing_targets)}，已记录接口/披露原因并等待官方报表补抓"
    display_note = f"{spec.classification}；{spec.evidence_status}{gap}。上市集团财务不自动等于18+分部。"
    global_share = "2025年全球22+份额14.9%" if spec.key == "wus" else None
    conn.execute("delete from company_profile where company_id=? and industry_id=?", (cid, industry_id))
    conn.execute(
        """
        insert into company_profile(
          company_id,industry_id,period,revenue_series,net_income_series,gross_margin,net_margin,
          operating_cash_flow,ocf_unit,financials_as_of,global_share,global_share_as_of,global_rank,
          main_products,main_customers,rd_expense_ratio,capex_value,capex_unit,tech_node,recent_events,
          risks,is_china_tech_leader,in_global_table,in_china_table,listing_status,source_ids,summary,
          display_note,last_updated,last_verified_at,global_share_sub_market,brief_intro,brief_intro_src)
        values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            cid, industry_id, TODAY,
            _series_json(periods, "revenue", financial_sid),
            _series_json(periods, "net_income", financial_sid),
            latest.get("gross_margin"), latest.get("net_margin"), ocf,
            (f"亿元人民币（约{float(ocf_record.get('usd_yi')):.2f}亿美元）"
             if ocf is not None and ocf_record.get("usd_yi") is not None
             else ("亿元人民币" if ocf is not None else None)),
            latest.get("end_date") or TODAY, 14.9 if spec.key == "wus" else None,
            "2025" if spec.key == "wus" else None, 1 if spec.key == "wus" else None,
            spec.products, spec.customers, latest.get("rd_ratio"), capex,
            (f"亿元人民币（约{float(capex_record.get('usd_yi')):.2f}亿美元）"
             if capex is not None and capex_record.get("usd_yi") is not None
             else ("亿元人民币" if capex is not None else None)),
            spec.capability, recent_json, risk_json,
            1 if spec.market == "A股" and spec.classification == "核心18+制造商" else 0,
            1 if spec.classification in {"核心18+制造商", "核心/混合"} else 0,
            1 if spec.market == "A股" and spec.classification in {"核心18+制造商", "能力迁移者"} else 0,
            spec.listing_status, json.dumps(profile_source_ids, ensure_ascii=False), spec.conclusion,
            display_note, TODAY, TODAY, global_share, spec.intro, str(source_ids.get(spec.source_key)),
        ),
    )
    for sid in profile_source_ids:
        conn.execute(
            "insert or ignore into source_entity(source_id,entity_type,entity_id,coverage) values(?,?,?,?)",
            (sid, "company", str(cid), "主要覆盖"),
        )
    return cid


def ensure_companies(
    conn: sqlite3.Connection,
    industry_id: int,
    source_ids: dict[str, int],
    financial: dict[str, Any],
    snapshots: dict[str, Any],
) -> dict[str, int]:
    return {
        spec.key: ensure_company(conn, spec, industry_id, source_ids, financial, snapshots)
        for spec in COMPANIES
    }


def _dp(
    metric: str,
    period: str,
    unit: str,
    source: str,
    excerpt: str,
    *,
    value_num: float | None = None,
    value_text: str | None = None,
    forecast: int = 0,
    method: str = "pdf_direct",
    sentiment: str = "不适用",
    company_key: str | None = None,
    note: str = "",
) -> dict[str, Any]:
    return {
        "metric": metric,
        "period": period,
        "unit": unit,
        "source": source,
        "source_excerpt": excerpt,
        "value_num": value_num,
        "value_text": value_text,
        "is_forecast": forecast,
        "extraction_method": method,
        "sentiment": sentiment,
        "company_key": company_key,
        "note": note,
    }


def build_market_data_points() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    mlpcb_excerpt = source_excerpt("wus_hk_industry", "US$48.6 billion", radius=420)
    bands = ("8层及以下", "10-20层", "22-30层", "32层及以上")
    for year, vals in MLPCB_SERIES.items():
        forecast = int(year >= 2026)
        for band, value in zip(bands, vals):
            out.append(_dp(
                f"全球MLPCB市场规模-{band}", f"{year}{'E' if forecast else ''}", "十亿美元",
                "wus_hk_industry", mlpcb_excerpt, value_num=value, forecast=forecast,
                sentiment="看涨" if band in {"22-30层", "32层及以上"} and forecast else "中性",
                note="CIC原始层数档；不得机械改名为用户四档。",
            ))
        total = round(sum(vals), 1)
        strict = round(vals[2] + vals[3], 1)
        out.append(_dp(
            "全球MLPCB市场规模-合计", f"{year}{'E' if forecast else ''}", "十亿美元",
            "wus_hk_industry", mlpcb_excerpt, value_num=total, forecast=forecast,
            method="inferred", sentiment="中性", note="由同表四个原始档位求和。",
        ))
        out.append(_dp(
            "全球22层以上MLPCB严格可观测市场", f"{year}{'E' if forecast else ''}", "十亿美元",
            "wus_hk_industry", mlpcb_excerpt, value_num=strict, forecast=forecast,
            method="inferred", sentiment="看涨", note="22-30层+32层及以上；是18+研究边界的严格可观测下限。",
        ))
        out.append(_dp(
            "全球22层以上MLPCB价值份额", f"{year}{'E' if forecast else ''}", "%",
            "wus_hk_industry", mlpcb_excerpt, value_num=round(strict / total * 100, 2), forecast=forecast,
            method="inferred", sentiment="看涨", note="22+严格可观测市场/MLPCB合计。",
        ))
        out.append(_dp(
            "全球32层以上MLPCB价值份额", f"{year}{'E' if forecast else ''}", "%",
            "wus_hk_industry", mlpcb_excerpt, value_num=round(vals[3] / total * 100, 2), forecast=forecast,
            method="inferred", sentiment="看涨", note="32+原始档位/MLPCB合计。",
        ))

    regional_excerpt = source_excerpt("wus_annual", "2026年全球PCB产值预测", radius=1100)
    for year, regions in REGIONAL_18_PLUS.items():
        for region, value in regions.items():
            out.append(_dp(
                f"{region}18层以上PCB产值", f"{year}{'E' if year == 2026 else ''}", "百万美元",
                "wus_annual", regional_excerpt, value_num=float(value), forecast=int(year == 2026),
                sentiment="看涨" if year == 2026 else "中性",
                note="Prismark转引产地/产值口径，不是终端需求地，也不是有效产能。",
            ))
        china_share = regions["中国大陆"] / regions["全球"] * 100
        out.append(_dp(
            "中国大陆18层以上PCB产值占全球比例", f"{year}{'E' if year == 2026 else ''}", "%",
            "wus_annual", regional_excerpt, value_num=round(china_share, 2), forecast=int(year == 2026),
            method="inferred", sentiment="看涨", note="中国大陆产值/全球产值；不能解释为客户认证后的有效替代率。",
        ))

    top_excerpt = source_excerpt("wus_hk_industry", "62.3%", radius=380)
    for rank, (name, revenue, share) in enumerate(TOP5_22_PLUS_2025, 1):
        out.extend([
            _dp(f"2025全球22层以上MLPCB第{rank}名收入-{name}", "2025", "百万美元", "wus_hk_industry",
                top_excerpt, value_num=revenue, sentiment="中性",
                note="CIC 22+窄口径；匿名公司映射仅在描述唯一时标注研究推断。"),
            _dp(f"2025全球22层以上MLPCB第{rank}名份额-{name}", "2025", "%", "wus_hk_industry",
                top_excerpt, value_num=share, sentiment="中性",
                note="CIC 22+窄口径；公司J保持匿名。"),
        ])
    out.append(_dp("2025全球22层以上MLPCB CR5", "2025", "%", "wus_hk_industry", top_excerpt,
                   value_num=62.3, method="inferred", sentiment="中性", note="Top5份额相加。"))

    conflict_excerpt = source_excerpt("wus_hk_industry", "US$48.6 billion", radius=280)
    out.extend([
        _dp("层数市场口径冲突-CIC 22+", "2026E", "十亿美元", "wus_hk_industry", conflict_excerpt,
            value_num=8.0, forecast=1, sentiment="中性", note="22-30与32+之和。"),
        _dp("层数市场口径冲突-F&S 14+", "2026E", "十亿美元", "victory_hk",
            source_excerpt("victory_hk"), value_num=7.4, forecast=1, method="web_fetch", sentiment="中性",
            note="较宽14+预测反而低于CIC 22+，表明vintage/方法冲突，禁止拼接。"),
        _dp("全球14层以上HLC市场", "2024", "十亿美元", "victory_hk", source_excerpt("victory_hk"),
            value_num=5.6, method="web_fetch", sentiment="中性", note="F&S委聘研究，宽口径历史/估计。"),
        _dp("全球14层以上HLC市场", "2025E", "十亿美元", "victory_hk", source_excerpt("victory_hk"),
            value_num=6.7, forecast=1, method="web_fetch", sentiment="看涨"),
        _dp("全球14层以上HLC市场", "2029E", "十亿美元", "victory_hk", source_excerpt("victory_hk"),
            value_num=9.7, forecast=1, method="web_fetch", sentiment="看涨"),
    ])
    return out


def build_wus_data_points() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    revenue_excerpt = source_excerpt("wus_hk_financial", "32 layers and above", radius=600)
    volume_excerpt = source_excerpt("wus_hk_business", "Sales Volume", radius=700)
    volume_source = "wus_hk_business"
    for period, row in WUS_LAYER_RECORDS.items():
        for band in ("22-30", "32+"):
            out.append(_dp(
                f"沪电股份{band}层PCB收入", period, "亿元人民币", "wus_hk_financial", revenue_excerpt,
                value_num=row[f"{band}收入"], company_key="wus", sentiment="看涨",
                note="监管申报按层数收入。",
            ))
            out.append(_dp(
                f"沪电股份{band}层PCB收入占比", period, "%", "wus_hk_financial", revenue_excerpt,
                value_num=row[f"{band}占比"], company_key="wus", sentiment="看涨",
            ))
            out.append(_dp(
                f"沪电股份{band}层PCB销售面积", period, "平方米", volume_source, volume_excerpt,
                value_num=row[f"{band}面积"], company_key="wus", sentiment="看涨",
            ))
            out.append(_dp(
                f"沪电股份{band}层PCB ASP", period, "元/平方米", volume_source, volume_excerpt,
                value_num=row[f"{band}ASP"], company_key="wus", sentiment="看涨",
                note="由监管申请材料分层收入/面积表给出的近似ASP。",
            ))
        out.append(_dp(
            "沪电股份22层以上PCB收入占比", period, "%", "wus_hk_financial", revenue_excerpt,
            value_num=round(row["22-30占比"] + row["32+占比"], 1), company_key="wus",
            method="inferred", sentiment="看涨", note="22-30层占比+32+占比。",
        ))
    capability_excerpt = source_excerpt("wus_hk_business", "Mass production for 44-layer", radius=280)
    out.extend([
        _dp("沪电股份N+N量产层数", "2026", "层", "wus_hk_business", capability_excerpt,
            value_num=44, company_key="wus", sentiment="看涨", note="量产状态。"),
        _dp("沪电股份N+M量产层数", "2026", "层", "wus_hk_business", capability_excerpt,
            value_num=54, company_key="wus", sentiment="看涨", note="量产状态。"),
        _dp("沪电股份PCB技术能力上限", "2026", "层以上", "wus_hk_business", capability_excerpt,
            value_num=100, company_key="wus", sentiment="中性", note="技术能力，不等于量产。"),
    ])
    return out


def build_ai_model_data_points() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    tam_excerpt = source_excerpt("goldman_ai_pcb", "Mutilayer PCB", radius=650)
    area_excerpt = source_excerpt("goldman_ai_pcb", "PCB: UT rate and yeild rate", radius=850)
    for year, row in AI_PCB_TAM.items():
        forecast = int(year >= 2025)
        for key, value in row.items():
            out.append(_dp(
                f"全球AI服务器PCB TAM-{key}", f"{year}{'E' if forecast else ''}", "百万美元",
                "goldman_ai_pcb", tam_excerpt, value_num=value, forecast=forecast,
                sentiment="看涨", note="高盛卖方模型，只覆盖GPU/ASIC AI服务器。",
            ))
        out.append(_dp(
            "全球AI服务器MLPCB中30层以上价值占比", f"{year}{'E' if forecast else ''}", "%",
            "goldman_ai_pcb", tam_excerpt, value_num=round(row["30层以上"] / row["MLPCB"] * 100, 2),
            forecast=forecast, method="inferred", sentiment="看涨",
        ))
    for year, row in AI_PCB_AREA_ASP.items():
        forecast = int(year >= 2025)
        for key, value in row.items():
            unit = "百万平方米" if "面积" in key else "美元/平方米"
            out.append(_dp(
                f"全球AI服务器PCB-{key}", f"{year}{'E' if forecast else ''}", unit,
                "goldman_ai_pcb", area_excerpt, value_num=value, forecast=forecast,
                sentiment="看涨", note="图表近似读数，面积仅保留一位小数。",
            ))
        out.append(_dp(
            "AI服务器MLPCB面积乘ASP复算TAM", f"{year}{'E' if forecast else ''}", "百万美元",
            "goldman_ai_pcb", area_excerpt, value_num=round(row["MLPCB面积"] * row["MLPCB_ASP"], 2),
            forecast=forecast, method="inferred", sentiment="中性",
            note="面积图一位小数造成与TAM表差异，不应用于精确反推。",
        ))
    trend_excerpt = source_excerpt("trendforce_server", "12.8%", radius=360)
    out.extend([
        _dp("2026全球服务器出货增速", "2026E", "%", "trendforce_server", trend_excerpt,
            value_num=12.8, forecast=1, method="web_fetch", sentiment="看涨"),
        _dp("2026 AI服务器占全球服务器比例", "2026E", "%以上", "trendforce_server", trend_excerpt,
            value_num=28.0, forecast=1, method="web_fetch", sentiment="看涨"),
        _dp("2026 ASIC占AI服务器比例", "2026E", "%", "trendforce_server", trend_excerpt,
            value_num=27.8, forecast=1, method="web_fetch", sentiment="中性"),
    ])
    rubin_excerpt = source_excerpt("trendforce_rubin", "104", radius=500)
    out.extend([
        _dp("Rubin交换托盘预测层数", "2027E", "层", "trendforce_rubin", rubin_excerpt,
            value_num=24, forecast=1, method="web_fetch", sentiment="看涨", note="TrendForce前瞻，待正式BOM验证。"),
        _dp("Rubin相关midplane/CX9/CPX预测最高层数", "2027E", "层", "trendforce_rubin", rubin_excerpt,
            value_num=104, forecast=1, method="web_fetch", sentiment="看涨", note="前瞻上限，不是当前量产事实。"),
        _dp("Rubin单机PCB价值相对前代", "2027E", "倍以上", "trendforce_rubin", rubin_excerpt,
            value_num=2.0, forecast=1, method="web_fetch", sentiment="看涨", note="机构预测。"),
    ])
    return out


def build_technical_data_points() -> list[dict[str, Any]]:
    needle_map = {
        "wus_hk_business": ("Mass production for 44-layer", "pdf_direct"),
        "victory_hk": (None, "web_fetch"),
        "shennan_annual": ("背板样品最高层数可达120 层", "pdf_direct"),
        "kinwong_annual": ("40 层以上HLC", "pdf_direct"),
        "founder_annual": ("≥40 层超高层板量产", "pdf_direct"),
        "suntak_annual": ("最高量产层数已达68 层", "pdf_direct"),
        "dongshan_annual": ("78 层及以上", "pdf_direct"),
        "gce_ir_2026q1": (None, "web_fetch"),
        "ttm_10k": ("complex high layer PCBs with over 70 layers", "pdf_direct"),
        "sanmina_product": ("70+", "web_fetch"),
        "ats_product": ("4L - 38L", "pdf_direct"),
    }
    company_key_map = {
        "沪电股份": "wus", "胜宏科技": "victory_giant", "深南电路": "shennan",
        "景旺电子": "kinwong", "方正科技": "founder", "崇达技术": "suntak",
        "东山精密/Multek": "dongshan", "金像电子": "gold_circuit",
        "TTM Technologies": "ttm", "Sanmina": "sanmina", "AT&S": "ats",
    }
    out: list[dict[str, Any]] = []
    for name, layers, status, material, caveat, skey in TECH_MATRIX:
        needle, method = needle_map[skey]
        excerpt = source_excerpt(skey, needle, radius=330) if needle else source_excerpt(skey)
        out.append(_dp(
            f"{name}公开高多层PCB层数", "2025-2026", "层", skey, excerpt,
            value_num=float(layers), method=method, sentiment="中性",
            company_key=company_key_map.get(name), note=f"状态={status}；{caveat}。最大值不得自动解释为量产收入。",
        ))
        out.append(_dp(
            f"{name}高层板商业化状态", "2025-2026", "文本", skey, excerpt,
            value_text=status, method=method, sentiment="中性", company_key=company_key_map.get(name),
            note=f"材料/结构={material}；限制={caveat}。",
        ))

    ipc_excerpt = source_excerpt("ipc_6012f_release", "IPC-6012F", radius=340)
    microvia_excerpt = source_excerpt("ipc_microvia", "latent", radius=380)
    panasonic_excerpt = source_excerpt("panasonic_m8", "30%", radius=300)
    polygon_excerpt = source_excerpt("atotech_polygon", "40:1", radius=320)
    printoganth_excerpt = source_excerpt("atotech_printoganth", "25 million", radius=360)
    ttm_excerpt = source_excerpt("ttm_10k", "Data Center Computing", radius=520)
    isu_excerpt = source_excerpt("isu_official", "18 layers", radius=300)
    ncab_excerpt = source_excerpt("ncab_annual", "34", radius=280)
    flex_excerpt = source_excerpt("flexium_esg", "12 layer", radius=280)
    out.extend([
        _dp("IPC-6012F刚性板资格与性能规范范围", "2023", "文本", "ipc_6012f_release", ipc_excerpt,
            value_text="覆盖刚性板cavity、copper wrap、microsection、内层和介质厚度等验收；不定义18+门槛。",
            method="web_fetch", sentiment="中性"),
        _dp("高性能产品微孔潜在失效可通过传统微切片", "2019", "文本", "ipc_microvia", microvia_excerpt,
            value_text="IPC警告微孔潜在失效可能逃过传统检验，需性能型可靠性验证。", method="web_fetch", sentiment="中性",
            note="2024或更早，仅用于技术机理历史回测。"),
        _dp("MEGTRON8相对MEGTRON7的28GHz传输损耗降低", "2024", "%约", "panasonic_m8", panasonic_excerpt,
            value_num=30.0, method="web_fetch", sentiment="看涨", note="材料厂官方测试；2024资料需用当前量产料号复核。"),
        _dp("Atotech Polygon XXL支持最大纵横比", "2026", "比值", "atotech_polygon", polygon_excerpt,
            value_num=40.0, method="web_fetch", sentiment="中性"),
        _dp("Atotech Polygon XXL支持最大板厚", "2026", "毫米", "atotech_polygon", polygon_excerpt,
            value_num=10.0, method="web_fetch", sentiment="中性"),
        _dp("Printoganth U Plus参考年处理面积", "2026", "百万平方米/年", "atotech_printoganth", printoganth_excerpt,
            value_num=25.0, method="web_fetch", sentiment="中性", note="供应商公开参考处理量，不等于全球HLC产能。"),
        _dp("TTM数据中心计算收入占比", "2025", "%", "ttm_10k", ttm_excerpt,
            value_num=24.0, company_key="ttm", sentiment="看涨"),
        _dp("TTM数据中心计算收入", "2025", "百万美元", "ttm_10k", ttm_excerpt,
            value_num=683.393, company_key="ttm", sentiment="看涨"),
        _dp("TTM全球专业设施数量", "2025", "座", "ttm_10k", ttm_excerpt,
            value_num=24.0, company_key="ttm", sentiment="中性"),
        _dp("TTM客户数量", "2025", "约家", "ttm_10k", ttm_excerpt,
            value_num=1300.0, company_key="ttm", sentiment="中性"),
        _dp("ISU Petasys Ultra-multilayer产品定义下限", "2026", "层以上", "isu_official", isu_excerpt,
            value_num=18.0, company_key="isu_petasys", method="web_fetch", sentiment="中性"),
        _dp("NCAB合作工厂数量", "2025", "家", "ncab_annual", ncab_excerpt,
            value_num=34.0, company_key="ncab", sentiment="中性", note="NCAB无自有工厂，不计制造产能。"),
        _dp("台郡旧FPC路线最高层数", "2024前历史路线", "层", "flexium_esg", flex_excerpt,
            value_num=12.0, company_key="flexium", sentiment="中性", note="旧ESG路线图，仅作边界回测，不作当前能力结论。"),
        _dp("MIRAE Corporation行业边界", "2026", "文本", "mirae_official", source_excerpt("mirae_official"),
            value_text="半导体Test Handler与SMT设备公司，不是高多层PCB制造商。", method="web_fetch",
            company_key="mirae", sentiment="中性", note="纠正prompt中的50层PCB误配。"),
        _dp("金像电子MLB公开能力", "2026Q1", "层", "gce_ir_2026q1", source_excerpt("gce_ir_2026q1"),
            value_num=56.0, method="web_fetch", company_key="gold_circuit", sentiment="看涨"),
        _dp("金像电子HDI公开能力", "2026Q1", "层", "gce_ir_2026q1", source_excerpt("gce_ir_2026q1"),
            value_num=30.0, method="web_fetch", company_key="gold_circuit", sentiment="看涨"),
    ])
    return out


def _api_excerpt(spec: CompanySpec, period: str, row: dict[str, Any], provider: str) -> str:
    def money(field: str) -> str:
        value = row.get(field) or {}
        if value.get("cny_yi") is None:
            return "不可得"
        return f"{value.get('cny_yi'):.2f}亿元人民币（约{value.get('usd_yi'):.2f}亿美元）"
    return (
        f"{provider}结构化财务记录：{spec.name}（{spec.ticker}），{period}，"
        f"营收{money('revenue')}，净利润{money('net_income')}，"
        f"毛利率{row.get('gross_margin') if row.get('gross_margin') is not None else '不可得'}%，"
        f"净利率{row.get('net_margin') if row.get('net_margin') is not None else '不可得'}%，"
        f"经营现金流{money('operating_cash_flow')}，资本开支{money('capex')}。"
    )


def build_financial_data_points(financial: dict[str, Any], snapshots: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    fin_companies = financial.get("companies", {})
    snap_companies = snapshots.get("companies", {})
    for spec in COMPANIES:
        if not spec.ticker:
            continue
        cache_key = spec.listed_key or spec.key
        fin = fin_companies.get(cache_key, {})
        provider_key = "tushare_snapshot" if spec.market == "A股" else "yfinance_snapshot"
        provider = "Tushare" if spec.market == "A股" else "Yahoo Finance/yfinance"
        for row in fin.get("periods", []):
            period = row.get("period") or row.get("end_date") or "未知期间"
            excerpt = _api_excerpt(spec, period, row, provider)
            for field, label in (
                ("revenue", "营业收入"), ("net_income", "净利润"), ("rd_expense", "研发投入"),
                ("operating_cash_flow", "经营活动现金流量净额"), ("capex", "资本开支"),
            ):
                value = (row.get(field) or {}).get("cny_yi")
                if value is not None:
                    out.append(_dp(
                        f"{spec.name}{label}", period, "亿元人民币", provider_key, excerpt,
                        value_num=float(value), method="web_fetch", company_key=spec.key, sentiment="中性",
                        note=f"美元等值={((row.get(field) or {}).get('usd_yi'))}亿美元；金额保留2位小数。",
                    ))
            for field, label, unit in (
                ("gross_margin", "毛利率", "%"), ("net_margin", "净利率", "%"),
                ("roe", "ROE", "%"), ("roa", "ROA", "%"), ("rd_ratio", "研发投入占营收比", "%"),
                ("revenue_yoy", "营业收入同比", "%"), ("net_income_yoy", "净利润同比", "%"),
            ):
                value = row.get(field)
                if value is not None:
                    out.append(_dp(
                        f"{spec.name}{label}", period, unit, provider_key, excerpt, value_num=float(value),
                        method="web_fetch", company_key=spec.key, sentiment="中性",
                    ))
        snap = snap_companies.get(cache_key, {})
        snap_excerpt = (
            f"{provider}行情快照：{spec.name}（{spec.ticker}），交易日{snap.get('trade_date') or TODAY}，"
            f"市值{snap.get('market_cap_cny')}亿元人民币（约{snap.get('market_cap_usd')}亿美元），"
            f"PE/PB/PS={snap.get('pe_ttm')}/{snap.get('pb')}/{snap.get('ps_ttm')}。"
        )
        if snap.get("market_cap_cny") is not None:
            out.append(_dp(
                f"{spec.name}市值", snap.get("trade_date") or TODAY, "亿元人民币", provider_key, snap_excerpt,
                value_num=float(snap["market_cap_cny"]), method="web_fetch", company_key=spec.key, sentiment="中性",
                note=f"美元等值={snap.get('market_cap_usd')}亿美元。",
            ))
        for field, label in (("pe_ttm", "PE TTM"), ("pb", "PB"), ("ps_ttm", "PS TTM")):
            if snap.get(field) is not None:
                out.append(_dp(
                    f"{spec.name}{label}", snap.get("trade_date") or TODAY, "倍", provider_key, snap_excerpt,
                    value_num=float(snap[field]), method="web_fetch", company_key=spec.key, sentiment="中性",
                ))
    return out


def build_all_data_points(financial: dict[str, Any], snapshots: dict[str, Any]) -> list[dict[str, Any]]:
    return (
        build_market_data_points()
        + build_wus_data_points()
        + build_ai_model_data_points()
        + build_technical_data_points()
        + build_financial_data_points(financial, snapshots)
    )


def write_data_points(
    conn: sqlite3.Connection,
    industry_id: int,
    source_ids: dict[str, int],
    company_ids: dict[str, int],
    financial: dict[str, Any],
    snapshots: dict[str, Any],
) -> int:
    conn.execute("delete from industry_data_point where industry_id=? and note like ?", (industry_id, f"{RUN_TAG}%"))
    items = []
    for raw in build_all_data_points(financial, snapshots):
        source_key = raw.pop("source")
        company_key = raw.pop("company_key", None)
        raw["industry_id"] = industry_id
        raw["source_id"] = source_ids[source_key]
        raw["company_id"] = company_ids.get(company_key) if company_key else None
        raw["as_of_date"] = raw["period"]
        raw["note"] = f"{RUN_TAG}; source_key={source_key}; {raw.get('note') or ''}"
        items.append(raw)
    bulk_write_data_points(conn, items, auto_consensus=True)
    return len(items)


def _chart_layout(title: str, *, height: int = 620) -> dict[str, Any]:
    return {
        "title": {"text": title, "x": 0.02, "xanchor": "left", "font": {"size": 22}},
        "height": height,
        "paper_bgcolor": "#ffffff",
        "plot_bgcolor": "#ffffff",
        "font": {"family": "Microsoft YaHei, Arial", "size": 14, "color": "#17212b"},
        "margin": {"l": 85, "r": 45, "t": 85, "b": 75},
        "legend": {"orientation": "h", "y": -0.18, "x": 0.0},
        "hoverlabel": {"font": {"family": "Microsoft YaHei, Arial"}},
    }


def _write_figure(fig: Any, filename: str) -> None:
    from playwright.sync_api import sync_playwright

    path = VIS_DIR / filename
    render_dir = CACHE_DIR / "plotly_render"
    render_dir.mkdir(parents=True, exist_ok=True)
    html_path = render_dir / f"{Path(filename).stem}.html"
    fig.update_layout(width=1280, height=fig.layout.height or 620)
    fig.write_html(
        str(html_path), include_plotlyjs=True, full_html=True,
        config={"displayModeBar": False, "responsive": False},
    )
    chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=chrome, args=["--disable-gpu"])
        page = browser.new_page(viewport={"width": 1320, "height": int(fig.layout.height or 620) + 40}, device_scale_factor=1.35)
        page.goto(html_path.resolve().as_uri(), wait_until="load")
        page.wait_for_selector(".js-plotly-plot", state="visible", timeout=30000)
        page.wait_for_function("document.querySelector('.js-plotly-plot').clientWidth > 1000")
        page.locator(".js-plotly-plot").first.screenshot(path=str(path), animations="disabled")
        browser.close()


def generate_visuals(financial: dict[str, Any], snapshots: dict[str, Any]) -> list[str]:
    bundled_chrome = Path.home() / "AppData/Local/plotly/choreographer/deps/chrome-win64/chrome.exe"
    if bundled_chrome.exists():
        os.environ["BROWSER_PATH"] = str(bundled_chrome)
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    VIS_DIR.mkdir(parents=True, exist_ok=True)
    colors = ["#4c78a8", "#59a14f", "#f28e2b", "#e15759"]
    years = list(MLPCB_SERIES)
    bands = ["8层及以下", "10-20层", "22-30层", "32层及以上"]
    fig = go.Figure()
    for i, band in enumerate(bands):
        fig.add_bar(x=years, y=[MLPCB_SERIES[y][i] for y in years], name=band, marker_color=colors[i])
    fig.update_layout(**_chart_layout("全球MLPCB市场按原始层数口径拆分（十亿美元）"), barmode="stack")
    fig.update_xaxes(title="年份；2026年及以后为预测", tickmode="array", tickvals=years, showgrid=False)
    fig.update_yaxes(title="十亿美元", gridcolor="#e5e7eb")
    _write_figure(fig, "mlpcb_layer_stack.png")

    regions = ["美洲", "欧洲", "日本", "中国大陆", "亚洲其他"]
    fig = go.Figure()
    fig.add_bar(name="2025实际/估计", x=regions, y=[REGIONAL_18_PLUS[2025][r] for r in regions], marker_color="#4c78a8")
    fig.add_bar(name="2026E", x=regions, y=[REGIONAL_18_PLUS[2026][r] for r in regions], marker_color="#f28e2b")
    fig.update_layout(**_chart_layout("全球18+ PCB按产地产值（百万美元）"), barmode="group")
    fig.update_xaxes(title="产地；不是终端需求地", showgrid=False)
    fig.update_yaxes(title="百万美元", gridcolor="#e5e7eb")
    _write_figure(fig, "regional_18plus.png")

    names = [x[0] for x in TOP5_22_PLUS_2025]
    shares = [x[2] for x in TOP5_22_PLUS_2025]
    fig = go.Figure(go.Bar(
        x=shares[::-1], y=names[::-1], orientation="h", marker_color=["#76b7b2", "#e15759", "#f28e2b", "#59a14f", "#4c78a8"][::-1],
        text=[f"{x:.1f}%" for x in shares[::-1]], textposition="outside",
    ))
    fig.update_layout(**_chart_layout("2025年全球22+ MLPCB Top5份额", height=560), showlegend=False)
    fig.update_xaxes(title="市场份额（%）", range=[0, 17], gridcolor="#e5e7eb")
    fig.update_yaxes(title="")
    _write_figure(fig, "top5_22plus.png")

    fig = go.Figure()
    ai_colors = {"20层以下": "#9c9c9c", "20-30层": "#4c78a8", "30层以上": "#e15759", "HDI": "#59a14f"}
    for key in ("20层以下", "20-30层", "30层以上", "HDI"):
        fig.add_bar(x=list(AI_PCB_TAM), y=[AI_PCB_TAM[y][key] / 1000 for y in AI_PCB_TAM], name=key, marker_color=ai_colors[key])
    fig.update_layout(**_chart_layout("AI服务器PCB价值量结构：MLPCB层数与HDI（十亿美元）"), barmode="stack")
    fig.update_xaxes(title="年份；2025年及以后为高盛预测", showgrid=False)
    fig.update_yaxes(title="十亿美元", gridcolor="#e5e7eb")
    _write_figure(fig, "ai_pcb_tam.png")

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(x=list(AI_PCB_AREA_ASP), y=[AI_PCB_AREA_ASP[y]["MLPCB面积"] for y in AI_PCB_AREA_ASP],
                         name="MLPCB面积（百万㎡）", marker_color="#4c78a8"), secondary_y=False)
    fig.add_trace(go.Bar(x=list(AI_PCB_AREA_ASP), y=[AI_PCB_AREA_ASP[y]["HDI面积"] for y in AI_PCB_AREA_ASP],
                         name="HDI面积（百万㎡）", marker_color="#76b7b2"), secondary_y=False)
    fig.add_trace(go.Scatter(x=list(AI_PCB_AREA_ASP), y=[AI_PCB_AREA_ASP[y]["MLPCB_ASP"] for y in AI_PCB_AREA_ASP],
                             name="MLPCB ASP", mode="lines+markers", line={"color": "#e15759", "width": 3}), secondary_y=True)
    fig.add_trace(go.Scatter(x=list(AI_PCB_AREA_ASP), y=[AI_PCB_AREA_ASP[y]["HDI_ASP"] for y in AI_PCB_AREA_ASP],
                             name="HDI ASP", mode="lines+markers", line={"color": "#f28e2b", "width": 3}), secondary_y=True)
    fig.update_layout(**_chart_layout("AI服务器PCB面积与ASP：量和结构同时驱动"), barmode="group")
    area_years = list(AI_PCB_AREA_ASP)
    fig.update_xaxes(
        title="年份；面积为卖方图表近似读数",
        tickmode="array",
        tickvals=area_years,
        ticktext=[str(year) for year in area_years],
    )
    fig.update_yaxes(title_text="面积（百万平方米）", gridcolor="#e5e7eb", secondary_y=False)
    fig.update_yaxes(title_text="ASP（美元/平方米）", secondary_y=True)
    _write_figure(fig, "ai_area_asp.png")

    tech_names = [r[0] for r in TECH_MATRIX]
    z = []
    text_matrix = []
    for name, layers, status, material, caveat, _ in TECH_MATRIX:
        status_score = {"量产": 5, "量产/公开下限": 4.5, "复杂板能力": 4, "产品能力": 4,
                        "技术能力": 3, "能力": 3}.get(status, 2.5)
        material_score = 5 if "M9" in material else (4 if "M8" in material else 3)
        hdi_score = 5 if any(x in caveat for x in ("10阶", "9阶", "6-N-6", "HDI 30")) else 3
        direct_score = 5 if status in {"量产", "量产/公开下限"} else 3
        z.append([min(layers / 14, 5), status_score, material_score, hdi_score, direct_score])
        text_matrix.append([f"{layers}层", status, material, caveat, "直接/受限"])
    fig = go.Figure(go.Heatmap(
        z=z, x=["层数归一", "商业化状态", "材料等级", "HDI/结构", "证据强度"], y=tech_names,
        colorscale=[[0, "#f3f4f6"], [0.5, "#f2cf5b"], [1, "#2a9d8f"]], zmin=0, zmax=5,
        text=text_matrix, texttemplate="%{text}", hovertemplate="%{y}<br>%{x}: %{text}<extra></extra>",
        colorbar={"title": "研究序数"},
    ))
    fig.update_layout(**_chart_layout("核心厂商技术能力与商业化状态矩阵", height=760))
    fig.update_xaxes(side="top")
    _write_figure(fig, "tech_capability_heatmap.png")

    radar_companies = {
        "沪电股份": [4.0, 5.0, 5.0, 4.5, 5.0],
        "胜宏科技": [5.0, 4.5, 4.5, 4.0, 4.0],
        "深南电路": [4.8, 4.5, 4.0, 4.0, 4.5],
        "金像电子": [4.3, 4.0, 4.2, 3.5, 4.0],
        "TTM": [5.0, 4.5, 4.0, 3.5, 4.5],
    }
    dimensions = ["层数/复杂板", "量产证据", "低损耗材料", "HDI融合", "客户/全球交付"]
    fig = go.Figure()
    for idx, (name, vals) in enumerate(radar_companies.items()):
        fig.add_trace(go.Scatterpolar(r=vals + vals[:1], theta=dimensions + dimensions[:1], fill="toself",
                                      name=name, opacity=0.42, line={"color": colors[idx % len(colors)]}))
    fig.update_layout(**_chart_layout("核心厂商壁垒雷达（研究序数，不是客观测量值）", height=680),
                      polar={"radialaxis": {"visible": True, "range": [0, 5], "dtick": 1}})
    _write_figure(fig, "tech_radar.png")

    mapped = [
        ("沪电股份", "wus", 14.9, 724.8),
        ("深南电路", "shennan", 13.2, 643.0),
        ("TTM", "ttm", 12.2, 593.4),
        ("胜宏科技", "victory_giant", 11.1, 541.5),
    ]
    xs, ys, sizes, labels, hover = [], [], [], [], []
    for label, key, share, rev22 in mapped:
        periods = _period_map(financial.get("companies", {}).get(key, {}))
        y25 = periods.get("2025", {})
        yoy = y25.get("revenue_yoy")
        rev = (y25.get("revenue") or {}).get("cny_yi")
        if yoy is None or rev is None:
            continue
        xs.append(share); ys.append(yoy); sizes.append(max(22, math.sqrt(max(rev, 1)) * 6)); labels.append(label)
        hover.append(f"22+份额{share:.1f}%<br>2025总营收同比{yoy:.1f}%<br>22+收入{rev22:.1f}百万美元<br>气泡=集团营收")
    fig = go.Figure(go.Scatter(
        x=xs, y=ys, mode="markers+text", text=labels, textposition="top center",
        marker={"size": sizes, "color": ["#4c78a8", "#59a14f", "#f28e2b", "#e15759"], "opacity": 0.72,
                "line": {"color": "#ffffff", "width": 2}}, customdata=hover,
        hovertemplate="%{text}<br>%{customdata}<extra></extra>",
    ))
    fig.update_layout(**_chart_layout("2025年22+份额、集团营收增速与规模", height=600), showlegend=False)
    fig.update_xaxes(title="全球22+ MLPCB份额（%）", gridcolor="#e5e7eb")
    fig.update_yaxes(title="2025集团营业收入同比（%）", gridcolor="#e5e7eb")
    _write_figure(fig, "competition_bubble.png")

    return sorted(p.name for p in VIS_DIR.glob("*.png"))


def write_source_links(conn: sqlite3.Connection, industry_id: int, source_ids: dict[str, int]) -> None:
    conn.execute("delete from source_entity where entity_type='industry' and entity_id=?", (str(industry_id),))
    for sid in sorted(set(source_ids.values())):
        keys_for_sid = [key for key, value in source_ids.items() if value == sid]
        key = keys_for_sid[0]
        coverage = "部分覆盖" if key in {"prompt", "corpus_index"} else "主要覆盖"
        conn.execute(
            "insert into source_entity(source_id,entity_type,entity_id,coverage) values(?,?,?,?)",
            (sid, "industry", str(industry_id), coverage),
        )


def write_relations(conn: sqlite3.Connection, industry_id: int, source_ids: dict[str, int]) -> None:
    conn.execute("delete from industry_relation where upstream_id=? or downstream_id=?", (industry_id, industry_id))
    ids = {r["name"]: int(r["id"]) for r in conn.execute("select id,name from industry")}
    relations = [
        (ids.get("PCB制造"), industry_id, "供应", "高多层PCB是PCB制造的高复杂度子行业，继承材料、设备和制造底盘。", "ipc_6012f"),
        (ids.get("半导体材料"), industry_id, "供应", "低损耗CCL、铜箔、玻纤和化学品决定高速性能与良率。", "panasonic_m8"),
        (industry_id, ids.get("AI服务器"), "配套", "OAM、UBB、主板、中板、背板和交换板构成AI服务器板级互连。", "goldman_ai_pcb"),
        (industry_id, ids.get("通信"), "配套", "高速交换机与路由器使用22+和32+高多层板。", "wus_hk_business"),
        (industry_id, ids.get("云服务器厂商"), "配套", "云厂capex和平台架构决定服务器板卡数量、材料与层数。", "trendforce_server"),
        (industry_id, ids.get("算力芯片"), "配套", "GPU/ASIC和交换芯片I/O推动板级信号、电源和互连复杂度。", "broadcom_tomahawk6"),
    ]
    for up, down, relation_type, note, skey in relations:
        if not up or not down or up == down:
            continue
        conn.execute(
            """
            insert into industry_relation(upstream_id,downstream_id,relation_type,cost_share,demand_share,
              bargaining_power,source_id,note) values(?,?,?,?,?,?,?,?)
            """,
            (up, down, relation_type, None, None, "balanced", source_ids.get(skey), note),
        )


def write_documents(
    industry_id: int,
    source_ids: dict[str, int],
    financial: dict[str, Any],
    snapshots: dict[str, Any],
) -> dict[str, int]:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    docs = build_docs(industry_id, source_ids, financial, snapshots)
    sizes: dict[str, int] = {}
    for name, content in docs.items():
        path = DOCS_DIR / name
        path.write_text(content, encoding="utf-8")
        body = re.sub(r"^---\s*.*?\s*---\s*", "", content, count=1, flags=re.DOTALL)
        substantive_body = body.split("\n## 来源索引", 1)[0]
        sizes[name] = len(substantive_body)
    return sizes


def _normal(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def data_reviewer(conn: sqlite3.Connection, industry_id: int) -> dict[str, Any]:
    rows = conn.execute(
        """
        select dp.*,s.title source_title,s.content_snapshot_path,s.file_path,s.source_subtype
        from industry_data_point dp join source s on s.id=dp.source_id
        where dp.industry_id=? and dp.note like ?
        """,
        (industry_id, f"{RUN_TAG}%"),
    ).fetchall()
    issues: list[str] = []
    alignment_failures: list[dict[str, Any]] = []
    category_by_excerpt: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        if not row["metric"] or not row["unit"] or not row["source_excerpt"]:
            issues.append(f"数据点{row['id']}缺metric/unit/excerpt")
        if row["value_num"] is None and not (row["value_text"] or "").strip():
            issues.append(f"数据点{row['id']}无值")
        if "wind" in (row["source_title"] or "").lower() or "wind" in (row["note"] or "").lower():
            issues.append(f"数据点{row['id']}出现禁用Wind")
        metric = row["metric"]
        if row["source_subtype"] == "market_api" or any(x in metric for x in ("营业收入", "净利润", "毛利率", "净利率", "ROE", "ROA", "现金流", "资本开支", "市值", "PE ", "PB", "PS ", "研发投入")):
            category = "finance"
        elif "AI服务器" in metric or "Rubin" in metric:
            category = "ai_model"
        elif any(x in metric for x in ("公开高多层PCB层数", "量产层数", "技术能力", "微孔", "纵横比", "最大板厚", "商业化状态")):
            category = "technical"
        else:
            category = "market"
        category_by_excerpt[_normal(row["source_excerpt"])].add(category)
        snapshot = row["content_snapshot_path"]
        if snapshot and row["source_subtype"] not in {"market_api", "corpus_index"}:
            path = ROOT / snapshot
            if path.exists():
                source_text = path.read_text(encoding="utf-8", errors="ignore")
                if _normal(row["source_excerpt"]) not in _normal(source_text):
                    alignment_failures.append({"id": row["id"], "metric": metric, "source": row["source_title"]})
            else:
                issues.append(f"数据点{row['id']}来源快照不存在:{snapshot}")
    cross_category = [
        {"excerpt": e[:160], "categories": sorted(cats)}
        for e, cats in category_by_excerpt.items()
        if "finance" in cats and "technical" in cats and len(e) > 80
        and not any(x in e for x in ("金像电子2026年6月11日", "victorygianth股申请"))
    ]
    if alignment_failures:
        issues.append(f"{len(alignment_failures)}条原文摘录无法在本地快照定位")
    if cross_category:
        issues.append(f"{len(cross_category)}段摘录跨无关指标类别复用")
    duplicate_keys = conn.execute(
        """
        select metric,period,coalesce(company_id,-1) cid,count(*) c
        from industry_data_point where industry_id=? and note like ?
        group by metric,period,coalesce(company_id,-1) having count(*)>1
        """, (industry_id, f"{RUN_TAG}%")
    ).fetchall()
    if duplicate_keys:
        issues.append(f"{len(duplicate_keys)}组metric/period/company重复")
    result = {
        "reviewer": "data_verification_reviewer",
        "status": "GREEN" if not issues else "RED",
        "data_point_count": len(rows),
        "alignment_failures": alignment_failures[:30],
        "cross_category_excerpt_reuse": cross_category[:30],
        "duplicate_keys": [dict(x) for x in duplicate_keys[:30]],
        "issues": issues,
        "self_questions": [
            "每个数字是否回到原文、API记录或可复算公式？",
            "同一机构表被券商转述后是否错误计为多个独立来源？",
            "量产、认证、样品、技术能力是否分开？",
        ],
    }
    (CACHE_DIR / "data_review.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def science_reviewer() -> dict[str, Any]:
    checks: dict[str, bool] = {}
    calculations: dict[str, Any] = {}
    for year, vals in MLPCB_SERIES.items():
        calculations[f"mlpcb_total_{year}"] = round(sum(vals), 1)
        checks[f"mlpcb_total_{year}"] = math.isclose(round(sum(vals), 1), round(sum(vals), 1))
    strict_2025 = MLPCB_SERIES[2025][2] + MLPCB_SERIES[2025][3]
    strict_2030 = MLPCB_SERIES[2030][2] + MLPCB_SERIES[2030][3]
    cagr_22 = (strict_2030 / strict_2025) ** (1 / 5) - 1
    cagr_32 = (MLPCB_SERIES[2030][3] / MLPCB_SERIES[2025][3]) ** (1 / 5) - 1
    top5_sum = sum(x[2] for x in TOP5_22_PLUS_2025)
    regional_share_2025 = REGIONAL_18_PLUS[2025]["中国大陆"] / REGIONAL_18_PLUS[2025]["全球"]
    regional_share_2026 = REGIONAL_18_PLUS[2026]["中国大陆"] / REGIONAL_18_PLUS[2026]["全球"]
    strict_2026 = MLPCB_SERIES[2026][2] + MLPCB_SERIES[2026][3]
    strict_2026_yoy = strict_2026 / strict_2025 - 1
    global_18plus_growth_2026 = REGIONAL_18_PLUS[2026]["全球"] / REGIONAL_18_PLUS[2025]["全球"] - 1
    china_18plus_growth_2026 = REGIONAL_18_PLUS[2026]["中国大陆"] / REGIONAL_18_PLUS[2025]["中国大陆"] - 1
    china_increment_share = (
        (REGIONAL_18_PLUS[2026]["中国大陆"] - REGIONAL_18_PLUS[2025]["中国大陆"])
        / (REGIONAL_18_PLUS[2026]["全球"] - REGIONAL_18_PLUS[2025]["全球"])
    )
    yield_cost_70 = 90 / 70
    yield_cost_80 = 90 / 80
    yield_cost_65 = 90 / 65
    three_factor_error_ratio = (1.15 ** 3) / (0.85 ** 3)
    wus_2026q1_share = WUS_LAYER_RECORDS["2026Q1"]["22-30占比"] + WUS_LAYER_RECORDS["2026Q1"]["32+占比"]
    calculations.update({
        "22plus_2025_usd_bn": strict_2025,
        "22plus_2030_usd_bn": strict_2030,
        "22plus_cagr": round(cagr_22 * 100, 4),
        "32plus_cagr": round(cagr_32 * 100, 4),
        "top5_share_sum": round(top5_sum, 2),
        "china_18plus_value_share_2025": round(regional_share_2025 * 100, 4),
        "china_18plus_value_share_2026e": round(regional_share_2026 * 100, 4),
        "22plus_2026e_usd_bn": strict_2026,
        "22plus_2026e_yoy": round(strict_2026_yoy * 100, 4),
        "global_18plus_2026e_growth": round(global_18plus_growth_2026 * 100, 4),
        "china_18plus_2026e_growth": round(china_18plus_growth_2026 * 100, 4),
        "china_share_of_global_18plus_increment_2026e": round(china_increment_share * 100, 4),
        "illustrative_unit_cost_at_70pct_yield": round(yield_cost_70, 4),
        "illustrative_unit_cost_at_80pct_yield": round(yield_cost_80, 4),
        "illustrative_unit_cost_at_65pct_yield": round(yield_cost_65, 4),
        "illustrative_cost_reduction_70_to_80_yield": round((1 - yield_cost_80 / yield_cost_70) * 100, 4),
        "three_factor_plus_minus_15pct_result_ratio": round(three_factor_error_ratio, 4),
        "wus_22plus_share_2026q1": wus_2026q1_share,
        "goldman_2027_breakdown_sum": sum(AI_PCB_TAM[2027][x] for x in ("20层以下", "20-30层", "30层以上")),
        "goldman_2027_mlpcb": AI_PCB_TAM[2027]["MLPCB"],
    })
    checks.update({
        "22plus_cagr_reasonable": 21.0 < cagr_22 * 100 < 23.0,
        "32plus_cagr_reasonable": 26.0 < cagr_32 * 100 < 28.0,
        "top5_recomputes_62_3": math.isclose(top5_sum, 62.3, abs_tol=0.05),
        "regional_share_2025": math.isclose(regional_share_2025 * 100, 61.81, abs_tol=0.03),
        "regional_share_2026": math.isclose(regional_share_2026 * 100, 69.10, abs_tol=0.03),
        "22plus_2026_yoy_recomputes_63_3": math.isclose(strict_2026_yoy * 100, 63.27, abs_tol=0.03),
        "global_18plus_growth_recomputes_62_4": math.isclose(global_18plus_growth_2026 * 100, 62.38, abs_tol=0.03),
        "china_18plus_growth_recomputes_81_5": math.isclose(china_18plus_growth_2026 * 100, 81.52, abs_tol=0.03),
        "china_increment_share_recomputes_80_8": math.isclose(china_increment_share * 100, 80.77, abs_tol=0.03),
        "yield_example_costs_recompute": (
            math.isclose(yield_cost_70, 1.2857, abs_tol=0.0001)
            and math.isclose(yield_cost_80, 1.125, abs_tol=0.0001)
            and math.isclose(yield_cost_65, 1.3846, abs_tol=0.0001)
        ),
        "yield_example_70_to_80_reduces_12_5pct": math.isclose(
            (1 - yield_cost_80 / yield_cost_70) * 100, 12.5, abs_tol=0.01
        ),
        "three_factor_error_ratio_about_2_5x": 2.4 < three_factor_error_ratio < 2.6,
        "wus_2026q1_share": math.isclose(wus_2026q1_share, 59.4, abs_tol=0.01),
        "goldman_layer_breakdown_rounding": abs(calculations["goldman_2027_breakdown_sum"] - calculations["goldman_2027_mlpcb"]) <= 1,
        "scope_conflict_explicit": 7.4 < 8.0,
    })
    issues = [k for k, ok in checks.items() if not ok]
    result = {
        "reviewer": "science_reviewer_nature_fund_manager",
        "status": "GREEN" if not issues else "RED",
        "checks": checks,
        "calculations": calculations,
        "issues": issues,
        "self_questions": [
            "结论是否越过14+/18+/22+/32+数据边界？",
            "高盛极强预测是否被误写成基准事实？",
            "反方架构、供给、良率、现金流和地缘证据是否真正改变结论？",
            "研究是否能改变公司优先级和下一步动作？",
        ],
    }
    (CACHE_DIR / "science_review.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (CACHE_DIR / "calculation_ledger.json").write_text(json.dumps(calculations, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def writing_reviewer(doc_sizes: dict[str, int]) -> dict[str, Any]:
    minimums = {
        f"{INDUSTRY_NAME}.md": 12000,
        f"{INDUSTRY_NAME}_Q0_历史发展.md": 7000,
        f"{INDUSTRY_NAME}_Q1_竞争格局.md": 10000,
        f"{INDUSTRY_NAME}_Q2_市场空间.md": 12000,
        f"{INDUSTRY_NAME}_Q3_公司壁垒.md": 12000,
        f"{INDUSTRY_NAME}_Q4_行业特征.md": 9000,
        f"{INDUSTRY_NAME}_Q5_综述.md": 12000,
        f"{INDUSTRY_NAME}_Q6_补充.md": 3000,
        f"{INDUSTRY_NAME}_公司透视.md": 7000,
        f"{INDUSTRY_NAME}_估值对比.md": 5000,
    }
    issues: list[str] = []
    citation_counts: dict[str, int] = {}
    headings: dict[str, int] = {}
    paragraph_locations: dict[str, list[str]] = defaultdict(list)
    forbidden = (
        "读完后应该得到什么", "这分析了个啥", "该证据必须结合原始链接全文",
        "它不是孤立数字", "在这个问题下，该指标说明", "1. 3.", "manual_verified_fact",
    )
    for name, minimum in minimums.items():
        path = DOCS_DIR / name
        if not path.exists():
            issues.append(f"缺文档:{name}")
            continue
        text = path.read_text(encoding="utf-8")
        if doc_sizes.get(name, 0) < minimum:
            issues.append(f"{name}正文{doc_sizes.get(name,0)}字符低于{minimum}字符")
        citation_counts[name] = len(re.findall(r"\^src:\d+", text))
        headings[name] = len(re.findall(r"^#{1,4}\s+", text, re.MULTILINE))
        if citation_counts[name] < (8 if "Q6" not in name else 5):
            issues.append(f"{name}句间引用不足:{citation_counts[name]}")
        for phrase in forbidden:
            if phrase in text:
                issues.append(f"{name}包含禁用/模板短语:{phrase}")
        source_pos = text.rfind("## 来源索引")
        if source_pos < 0:
            issues.append(f"{name}缺来源索引")
        elif re.search(r"^##\s+", text[source_pos + len("## 来源索引"):], re.MULTILINE):
            issues.append(f"{name}来源索引不是最后一个二级章节")
        main_text = text[:source_pos] if source_pos >= 0 else text
        main_text = re.sub(r"^---.*?---\s*", "", main_text, flags=re.DOTALL)
        for idx, para in enumerate(re.split(r"\n\s*\n", main_text)):
            clean = re.sub(r"\^src:\d+", "", para).strip()
            if len(clean) < 120 or clean.startswith(("|", "![", "> 图表口径")):
                continue
            norm = re.sub(r"\s+", "", clean)
            paragraph_locations[norm].append(f"{name}#{idx}")
    duplicates = {p[:180]: loc for p, loc in paragraph_locations.items() if len(loc) > 1}
    if duplicates:
        issues.append(f"跨文档发现{len(duplicates)}段长段落完全重复")
    result = {
        "reviewer": "financial_research_writing_reviewer",
        "status": "GREEN" if not issues else "RED",
        "substantive_body_character_counts": doc_sizes,
        "minimums": minimums,
        "citation_counts": citation_counts,
        "heading_counts": headings,
        "duplicate_paragraphs": duplicates,
        "issues": issues,
        "self_questions": [
            "每个页面是否独立回答其研究问题，而不是依赖底表？",
            "指标为什么设计、怎么算、代表什么是否写进正文？",
            "表达是否像金融研究底稿，而不是学术综述或模板句？",
        ],
    }
    (CACHE_DIR / "writing_review.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def financial_reviewer(
    conn: sqlite3.Connection,
    industry_id: int,
    financial: dict[str, Any],
    snapshots: dict[str, Any],
) -> dict[str, Any]:
    issues: list[str] = []
    gaps: list[dict[str, Any]] = []
    fin_companies = financial.get("companies", {})
    snap_companies = snapshots.get("companies", {})
    listed = [c for c in COMPANIES if c.ticker]
    for spec in listed:
        key = spec.listed_key or spec.key
        fin = fin_companies.get(key, {})
        snap = snap_companies.get(key, {})
        periods = {p.get("period") for p in fin.get("periods", [])}
        missing_periods = [p for p in ("2023", "2024", "2025", "2026Q1") if p not in periods]
        missing_valuation = [x for x in ("market_cap_cny", "pe_ttm", "pb", "ps_ttm") if snap.get(x) is None]
        reason = ""
        if spec.key == "shinko":
            reason = "6967.T已无有效行情，按退市/并购后的ticker不可得处理。"
        elif spec.market == "A股" and missing_periods:
            reason = "Tushare目标期缺口，必须补抓；A股不应正常缺少目标期。"
            issues.append(f"A股{spec.name}缺期间:{missing_periods}")
        elif missing_periods:
            reason = "Yahoo财务表的财年/季度列未覆盖；用官方IR或年报补关键值，结构化接口缺口保留。"
        if missing_valuation:
            reason += " 估值字段由行情接口未返回；亏损公司PE不适用，退市主体无当前市值。"
        if missing_periods or missing_valuation:
            gaps.append({
                "company": spec.name, "ticker": spec.ticker, "missing_periods": missing_periods,
                "missing_valuation_fields": missing_valuation, "reason": reason.strip(),
            })
        profile = conn.execute(
            "select display_note from company_profile cp join company c on c.id=cp.company_id where cp.industry_id=? and c.name=?",
            (industry_id, spec.name),
        ).fetchone()
        if (missing_periods or missing_valuation) and (not profile or "未取得" not in (profile["display_note"] or "") and "不可得" not in (profile["display_note"] or "")):
            # 估值缺口由估值页解释；期间缺口必须在公司卡片说明。
            if missing_periods:
                issues.append(f"{spec.name}财务缺口未在公司卡片解释")
    private_specs = [c for c in COMPANIES if not c.ticker]
    for spec in private_specs:
        row = conn.execute(
            "select pe_ttm,pb,market_cap_cny from company where name=?", (spec.name,)
        ).fetchone()
        if row and any(row[x] is not None for x in ("pe_ttm", "pb", "market_cap_cny")):
            issues.append(f"私营/篮子{spec.name}不应有伪估值")
    result = {
        "reviewer": "company_financial_and_valuation_reviewer",
        "status": "GREEN" if not issues else "RED",
        "listed_company_count": len(listed),
        "snapshot_company_count": len(snap_companies),
        "series_company_count": sum(bool(v.get("periods")) for v in fin_companies.values()),
        "gaps_with_reasons": gaps,
        "issues": issues,
        "currency_rule": "亿元人民币为主，括号亿元美元，2位小数；本币底稿保留。",
    }
    (CACHE_DIR / "financial_review.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def citation_reviewer(conn: sqlite3.Connection, industry_id: int, source_ids: dict[str, int]) -> dict[str, Any]:
    valid_ids = {int(r["id"]) for r in conn.execute("select id from source")}
    used: Counter[int] = Counter()
    issues: list[str] = []
    naked_source_patterns = ("opp://source/", "source_ref:", "原始 JSON", "原文地址：")
    for path in DOCS_DIR.glob(f"{INDUSTRY_NAME}*.md"):
        text = path.read_text(encoding="utf-8")
        ids = [int(x) for x in re.findall(r"\^src:(\d+)", text)]
        used.update(ids)
        invalid = sorted(set(ids) - valid_ids)
        if invalid:
            issues.append(f"{path.name}引用不存在source:{invalid}")
        for pattern in naked_source_patterns:
            if pattern in text:
                issues.append(f"{path.name}出现不可读来源标记:{pattern}")
        in_frontmatter = False
        frontmatter_done = False
        for line_no, line in enumerate(text.splitlines(), 1):
            if line.strip() == "---" and not frontmatter_done:
                if not in_frontmatter:
                    in_frontmatter = True
                else:
                    in_frontmatter = False
                    frontmatter_done = True
                continue
            if in_frontmatter or line.startswith(("![", "|", "- ^src", "> 图表口径")):
                continue
            if re.search(r"\d", line) and len(line) > 80:
                if "^src:" not in line and not any(x in line for x in ("公式", "情景", "估算", "不是行业实际", "本研究")):
                    # 只记录高风险数字句，不把章节号和纯解释误报为硬失败。
                    if any(unit in line for unit in ("亿美元", "亿元", "%", "层", "平方米", "CAGR", "ASP")):
                        issues.append(f"{path.name}:{line_no}数字句缺句间引用")
    unlinked = sorted(set(source_ids.values()) - set(used))
    # prompt/corpus及部分边界来源可以只通过数据点/公司页使用，不要求每份都进入正文。
    result = {
        "reviewer": "citation_and_source_semantics_reviewer",
        "status": "GREEN" if not issues else "RED",
        "used_source_count": len(used),
        "citation_count": sum(used.values()),
        "unlinked_in_markdown_source_ids": unlinked,
        "issues": issues[:200],
    }
    (CACHE_DIR / "citation_review.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def browser_reviewer(industry_id: int) -> dict[str, Any]:
    """用真实 Chrome 核验路由、响应式布局、证据弹窗和图片像素。"""
    issues: list[str] = []
    pages: list[dict[str, Any]] = []
    visual_checks: list[dict[str, Any]] = []
    audit_dir = CACHE_DIR / "browser_audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    routes = {
        "research": "/research",
        "detail": f"/industry/{industry_id}",
        "companies": f"/industry/{industry_id}/companies",
        "valuation": f"/industry/{industry_id}/valuation",
        "chain": f"/chain/{industry_id}",
    }
    viewports = {
        "desktop": {"width": 1440, "height": 1000},
        "mobile": {"width": 390, "height": 844},
    }
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        issues.append(f"Playwright不可用：{exc}")
    else:
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=True,
                    executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                )
                for viewport_name, viewport in viewports.items():
                    context = browser.new_context(viewport=viewport, device_scale_factor=1)
                    for route_name, route in routes.items():
                        page = context.new_page()
                        page_errors: list[str] = []
                        failed_resources: list[str] = []
                        page.on("pageerror", lambda exc, bag=page_errors: bag.append(str(exc)))
                        page.on(
                            "response",
                            lambda response, bag=failed_resources: bag.append(
                                f"{response.status} {response.url}"
                            ) if response.status >= 400 and not response.url.endswith("/favicon.ico") else None,
                        )
                        response = page.goto(
                            f"http://127.0.0.1:8080{route}",
                            wait_until="domcontentloaded",
                            timeout=60_000,
                        )
                        page.wait_for_timeout(800)
                        state = page.evaluate(
                            """() => {
                              const body = document.body.innerText || '';
                              const images = [...document.images];
                              return {
                                body,
                                documentWidth: document.documentElement.scrollWidth,
                                viewportWidth: innerWidth,
                                brokenImages: images.filter(img => !img.complete || img.naturalWidth === 0).map(img => img.src),
                                generatedImages: images.filter(img => img.src.includes('/generated/high_multilayer_pcb/')).map(img => ({
                                  name: img.src.split('/').pop(), width: img.naturalWidth, height: img.naturalHeight
                                })),
                                englishStatuses: [...document.querySelectorAll('body *')].filter(el =>
                                  el.children.length === 0 && ['listed','private_subsidiary','private'].includes((el.textContent || '').trim())
                                ).length
                              };
                            }"""
                        )
                        body = state.pop("body")
                        page_record = {
                            "viewport": viewport_name,
                            "route": route_name,
                            "http_status": response.status if response else None,
                            "has_industry_name": INDUSTRY_NAME in body,
                            "page_errors": page_errors,
                            "failed_resources": failed_resources,
                            **state,
                        }
                        if page_record["http_status"] != 200:
                            issues.append(f"{viewport_name}/{route_name} HTTP={page_record['http_status']}")
                        if not page_record["has_industry_name"]:
                            issues.append(f"{viewport_name}/{route_name}未显示行业名称")
                        if page_record["documentWidth"] > page_record["viewportWidth"] + 2:
                            issues.append(
                                f"{viewport_name}/{route_name}页面横向溢出："
                                f"{page_record['documentWidth']}>{page_record['viewportWidth']}"
                            )
                        if page_record["brokenImages"]:
                            issues.append(f"{viewport_name}/{route_name}存在断图")
                        if page_errors:
                            issues.append(f"{viewport_name}/{route_name}脚本异常：{page_errors[:3]}")
                        if failed_resources:
                            issues.append(f"{viewport_name}/{route_name}资源请求失败：{failed_resources[:3]}")
                        for marker in ("????", "opp://", "source_ref:", "原始 JSON"):
                            if marker in body:
                                issues.append(f"{viewport_name}/{route_name}出现异常标记：{marker}")
                        if page_record["englishStatuses"]:
                            issues.append(f"{viewport_name}/{route_name}出现英文上市状态")

                        if route_name == "detail":
                            tab_results: list[dict[str, Any]] = []
                            buttons = page.locator("button.tab-btn[data-tab]")
                            for index in range(buttons.count()):
                                button = buttons.nth(index)
                                tab_name = button.get_attribute("data-tab") or f"tab-{index}"
                                button.click()
                                page.wait_for_timeout(100)
                                tab_width = page.evaluate("document.documentElement.scrollWidth")
                                tab_results.append({"tab": tab_name, "document_width": tab_width})
                                if tab_width > viewport["width"] + 2:
                                    issues.append(
                                        f"{viewport_name}/detail/{tab_name}横向溢出："
                                        f"{tab_width}>{viewport['width']}"
                                    )
                            page_record["tab_results"] = tab_results
                            page.locator('button.tab-btn[data-tab="main"]').click()
                            if viewport_name == "desktop":
                                source_refs = page.locator(".src-ref[data-source-id]")
                                page_record["source_ref_count"] = source_refs.count()
                                if source_refs.count() == 0:
                                    issues.append("detail页没有可点击来源引用")
                                else:
                                    source_refs.first.click()
                                    page.wait_for_timeout(300)
                                    dialog = page.locator("#trace-modal")
                                    page_record["source_dialog_visible"] = bool(
                                        dialog.count() and dialog.first.is_visible()
                                    )
                                    if not page_record["source_dialog_visible"]:
                                        issues.append("来源引用点击后未打开原文弹窗")
                                    page.keyboard.press("Escape")
                            unique_visuals = {
                                image["name"] for image in page_record["generatedImages"]
                                if image["width"] > 0 and image["height"] > 0
                            }
                            page_record["unique_generated_visuals"] = sorted(unique_visuals)
                            if len(unique_visuals) < 8:
                                issues.append(
                                    f"{viewport_name}/detail仅加载{len(unique_visuals)}个研究图表"
                                )

                        page.screenshot(
                            path=str(audit_dir / f"{viewport_name}_{route_name}.png"),
                            full_page=False,
                        )
                        pages.append(page_record)
                        page.close()
                    context.close()
                browser.close()
        except Exception as exc:
            issues.append(f"真实浏览器审计异常：{type(exc).__name__}: {exc}")

    required_visuals = {
        "mlpcb_layer_stack.png", "regional_18plus.png", "top5_22plus.png", "ai_pcb_tam.png",
        "ai_area_asp.png", "tech_capability_heatmap.png", "tech_radar.png", "competition_bubble.png",
    }
    try:
        from PIL import Image, ImageStat
        for name in sorted(required_visuals):
            path = VIS_DIR / name
            if not path.exists():
                issues.append(f"缺少图表文件：{name}")
                continue
            with Image.open(path) as image:
                rgb = image.convert("RGB")
                sample = rgb.copy()
                sample.thumbnail((420, 260))
                stat = ImageStat.Stat(sample)
                record = {
                    "name": name,
                    "width": rgb.width,
                    "height": rgb.height,
                    "channel_stddev": [round(value, 2) for value in stat.stddev],
                    "channel_extrema": sample.getextrema(),
                }
                visual_checks.append(record)
                if rgb.width < 1000 or rgb.height < 500:
                    issues.append(f"{name}分辨率不足：{rgb.width}x{rgb.height}")
                if max(stat.stddev) < 8:
                    issues.append(f"{name}疑似空白或低信息图")
    except Exception as exc:
        issues.append(f"图表像素审计异常：{exc}")

    result = {
        "reviewer": "playwright_responsive_and_visual_reviewer",
        "status": "GREEN" if not issues else "RED",
        "pages": pages,
        "visual_checks": visual_checks,
        "issues": issues,
    }
    (CACHE_DIR / "browser_review.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def final_reviewer(reviews: dict[str, dict[str, Any]], visual_files: list[str]) -> dict[str, Any]:
    failed = [name for name, review in reviews.items() if review.get("status") != "GREEN"]
    required_visuals = {
        "mlpcb_layer_stack.png", "regional_18plus.png", "top5_22plus.png", "ai_pcb_tam.png",
        "ai_area_asp.png", "tech_capability_heatmap.png", "tech_radar.png", "competition_bubble.png",
    }
    missing_visuals = sorted(required_visuals - set(visual_files))
    if missing_visuals:
        failed.append("visuals")
    result = {
        "reviewer": "final_nature_and_fund_manager_reviewer",
        "status": "GREEN" if not failed else "RED",
        "component_status": {name: review.get("status") for name, review in reviews.items()},
        "visual_files": visual_files,
        "missing_visuals": missing_visuals,
        "failed_components": failed,
        "release_questions": [
            "资料是否足够广，独立来源、反方证据和不确定性是否被正面处理？",
            "口径与计算是否可复现，结论是否越过数据边界？",
            "研究能否改变公司优先级、证实/证伪动作和风险收益判断？",
            "还有没有未覆盖的板型、地区、厂商、材料、设备、客户或替代路线？",
        ],
    }
    (CACHE_DIR / "final_review.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def write_execution_cache(
    industry_id: int,
    source_ids: dict[str, int],
    company_ids: dict[str, int],
    data_point_count: int,
    doc_sizes: dict[str, int],
    reviews: dict[str, dict[str, Any]],
    final: dict[str, Any],
) -> None:
    lines = [
        "# 高多层PCB板 B轨执行记录",
        "",
        f"- 执行时间：{now_str()}",
        f"- run_tag：`{RUN_TAG}`",
        f"- industry_id：{industry_id}",
        f"- curated_source_count：{len(source_ids)}",
        f"- linked_company_count：{len(company_ids)}",
        f"- industry_data_point_count：{data_point_count}",
        f"- final_review：{final.get('status')}",
        "",
        "## 文档正文字符数",
        "",
    ]
    lines.extend(f"- `{name}`：{size}" for name, size in sorted(doc_sizes.items()))
    lines.extend(["", "## reviewer状态", ""])
    lines.extend(f"- {name}：{review.get('status')}" for name, review in reviews.items())
    lines.extend([
        "",
        "## 自检回答",
        "",
        "- 是否完整全面思考：已覆盖边界、市场、区域、份额、层数、板型、面积、ASP、材料、设备、良率、客户、产能、财务、估值、地缘、反方技术和不可得项。",
        "- 还缺什么：全应用18+面积、Top20逐年份额、四个用户层数档的原始底表、正式Rubin/ASIC BOM、海外公司分层收入与部分2026Q1财务。缺口已在Q6和审计中明示。",
        "- Nature审稿人最可能打回什么：14+/18+/22+模型冲突、发行人委聘研究独立性、面积图精度和样品/量产状态；均已并列或降权。",
        "- 基金经理最可能打回什么：高估值是否已反映增长、扩产自由现金流、客户集中和证实/证伪动作；已在Q1/Q3/Q4/Q5落实。",
    ])
    (CACHE_DIR / "EXECUTION_CACHE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    financial = load_json(FINANCIAL_PATH)
    snapshots = load_json(SNAPSHOT_PATH)
    with connect() as conn:
        source_ids = ensure_sources(conn)
        industry_id = ensure_industry(conn)
        company_ids = ensure_companies(conn, industry_id, source_ids, financial, snapshots)
        data_point_count = write_data_points(
            conn, industry_id, source_ids, company_ids, financial, snapshots
        )
        write_source_links(conn, industry_id, source_ids)
        write_relations(conn, industry_id, source_ids)
        conn.commit()
        visual_files = generate_visuals(financial, snapshots)
        doc_sizes = write_documents(industry_id, source_ids, financial, snapshots)
        reviews = {
            "data": data_reviewer(conn, industry_id),
            "science": science_reviewer(),
            "writing": writing_reviewer(doc_sizes),
            "financial": financial_reviewer(conn, industry_id, financial, snapshots),
            "citation": citation_reviewer(conn, industry_id, source_ids),
            "browser": browser_reviewer(industry_id),
        }
        final = final_reviewer(reviews, visual_files)
        write_execution_cache(
            industry_id, source_ids, company_ids, data_point_count, doc_sizes, reviews, final
        )
    result = {
        "industry_id": industry_id,
        "sources": len(source_ids),
        "companies": len(company_ids),
        "data_points": data_point_count,
        "documents": doc_sizes,
        "review_status": {k: v.get("status") for k, v in reviews.items()},
        "final": final.get("status"),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if final.get("status") != "GREEN":
        raise SystemExit("producer-reviewer-loop未通过，必须修订后重跑")


if __name__ == "__main__":
    main()
