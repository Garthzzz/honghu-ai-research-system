#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Apply the validated PCB-equipment research package to one research DB.

The script never writes ``industry_data_point``; those facts are loaded only by
the unified ingest entry.  This adapter creates the industry shell, company and
relation aggregates, and the standard Markdown artifacts consumed by Viewer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from .company_financial_series_utils import rounded_pct_change_with_interval
    from .pcb_equipment_research_data import (
        AS_OF_DATE,
        COMPANY_EVENT_SOURCE_KEYS,
        COMPANY_IDENTITIES,
        INDUSTRY_NAME,
        SOURCES,
    )
except ImportError:
    from company_financial_series_utils import rounded_pct_change_with_interval
    from pcb_equipment_research_data import (
        AS_OF_DATE,
        COMPANY_EVENT_SOURCE_KEYS,
        COMPANY_IDENTITIES,
        INDUSTRY_NAME,
        SOURCES,
    )


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "research.db"
DOCS_DIR = ROOT / "docs" / "industries"
CACHE_DIR = ROOT / "cache" / "pcb_equipment_research"
SOURCE_MAP_PATH = ROOT / "cache" / "db_queue" / "pcb_equipment_b_20260719_source_map.json"
FINANCIAL_PATH = CACHE_DIR / "company_financial_snapshot.json"
COMPANY_CARDS_PATH = CACHE_DIR / "agent_company_cards.md"


DOC_FILES = {
    "main": "PCB专用设备.md",
    "Q0": "PCB专用设备_Q0_历史发展.md",
    "Q1": "PCB专用设备_Q1_竞争格局.md",
    "Q2": "PCB专用设备_Q2_市场空间.md",
    "Q3": "PCB专用设备_Q3_公司壁垒.md",
    "Q4": "PCB专用设备_Q4_行业特征.md",
    "Q5": "PCB专用设备_Q5_综述.md",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_industry(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT id FROM industry WHERE name=?", (INDUSTRY_NAME,)).fetchone()
    core = "AI服务器与高速交换推动高多层PCB扩产；设备价值量由精度、良率、认证、交付和资本开支共同决定。"
    if row:
        industry_id = int(row["id"])
        conn.execute(
            "UPDATE industry SET parent_id=NULL,level=1,tier=1,status='深度跟踪',core_dynamic=?,last_updated=? WHERE id=?",
            (core, AS_OF_DATE, industry_id),
        )
        return industry_id
    return int(conn.execute(
        "INSERT INTO industry(name,parent_id,level,tier,status,core_dynamic,last_updated) VALUES(?,NULL,1,1,'深度跟踪',?,?)",
        (INDUSTRY_NAME, core, AS_OF_DATE),
    ).lastrowid)


def source_ids_from_map() -> dict[str, int]:
    mapping = json.loads(SOURCE_MAP_PATH.read_text(encoding="utf-8"))
    result: dict[str, int] = {}
    for spec in SOURCES:
        lookup = f"file:{spec.file_path}" if spec.file_path else f"url:{spec.url}"
        if lookup in mapping:
            result[spec.key] = int(mapping[lookup])
    missing = sorted(spec.key for spec in SOURCES if spec.key not in result)
    if missing:
        raise RuntimeError(f"source map missing: {missing}")
    return result


def _latest_period(company: dict[str, Any], period: str = "2025") -> dict[str, Any]:
    for row in company.get("financial_series", {}).get("periods") or []:
        if row.get("period") == period:
            return row
    return {}


def _profile_financial_context(company: dict[str, Any]) -> dict[str, Any]:
    financial = company.get("financial_series") or {}
    coverage = financial.get("coverage") or {}
    metric_period = coverage.get("profile_metric_period")
    metric_row = _latest_period(company, str(metric_period)) if metric_period else {}
    if not metric_row:
        for candidate in ("2025", "2024", "2023"):
            metric_row = _latest_period(company, candidate)
            if metric_row:
                metric_period = candidate
                break
    metric_end_date = coverage.get("profile_metric_end_date")
    if not metric_end_date and metric_row.get("end_date"):
        digits = "".join(ch for ch in str(metric_row["end_date"]) if ch.isdigit())[:8]
        if len(digits) == 8:
            metric_end_date = f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    latest_series_date = coverage.get("latest_displayed_series_date")
    financials_as_of = metric_end_date or latest_series_date
    displayed_periods = coverage.get("displayed_profit_and_loss_periods") or []
    period_label = (
        f"核心财务指标={metric_period or '无完整年度'}"
        f"（截至{metric_end_date or '无'}）；损益序列={'、'.join(displayed_periods) or '无'}"
    )
    return {
        "metric_row": metric_row,
        "metric_period": metric_period,
        "metric_end_date": metric_end_date,
        "latest_displayed_series_date": latest_series_date,
        "financials_as_of": financials_as_of,
        "period_label": period_label,
        "coverage_note": coverage.get("company_note") or "未生成公司级财务覆盖说明。",
    }


def _series(company: dict[str, Any], field: str, source_id: int | None) -> str:
    rows: list[dict[str, Any]] = []
    all_periods = {r.get("period"): r for r in company.get("financial_series", {}).get("periods") or []}
    for period in ("2023", "2024", "2025", "2026Q1"):
        value = all_periods.get(period)
        if not value:
            continue
        obj = value.get(field) or {}
        cny = obj.get("cny_yi")
        if cny is None:
            continue
        prior_label = str(int(period[:4]) - 1) + (period[4:] if "Q" in period else "")
        prior_obj = (all_periods.get(prior_label) or {}).get(field) or {}
        # 同比必须使用同币种、同一冻结展示精度的原币亿元输入；人民币
        # 换算值还叠加了汇率和二次舍入，不能作为海外公司的增长率分母。
        current_local = obj.get("local_yi")
        prior_local = prior_obj.get("local_yi")
        rounded_change = rounded_pct_change_with_interval(current_local, prior_local)
        yoy = float(rounded_change["value"]) if rounded_change else None
        change_status = None
        change_meta: dict[str, Any] | None = None
        if field == "net_income":
            change_meta = value.get("net_income_yoy_meta")
            if not isinstance(change_meta, dict):
                # Fail closed: a legacy/provider percentage must never leak into
                # the company chart as a comparable growth rate.
                yoy = None
                change_status = "同比可比性未结构化，未展示增长率"
            elif change_meta.get("valid_for_comparison"):
                yoy = change_meta.get("comparison_value_pct")
                change_status = None
            else:
                yoy = None
                change_status = change_meta.get("state_label") or "无法比较"
        if change_status is None and rounded_change and rounded_change["unstable"]:
            yoy = None
            high = rounded_change["high"]
            high_text = "无有限上界" if not math.isfinite(float(high)) else f"{high}%"
            change_status = (
                "低基数，百分比不稳定；按展示金额的四舍五入范围，"
                f"同比约为{rounded_change['low']}%至{high_text}"
            )
        display_period = period
        if company.get("key") == "kla" and period == "2026Q1":
            display_period = "FY2026Q3（截至2026-03-31）"
        elif company.get("key") == "cohu" and period == "2026Q1":
            display_period = "2026Q1（截至2026-03-28）"
        rows.append({
            "period": display_period,
            "value": round(float(cny), 2),
            "unit": "亿元人民币" + (f"（约{float(obj['usd_yi']):.2f}亿美元）" if obj.get("usd_yi") is not None else ""),
            "cny_yi": cny,
            "usd_yi": obj.get("usd_yi"),
            "local_yi": obj.get("local_yi"),
            "local_currency": obj.get("local_currency") or value.get("currency"),
            "original_display": (
                f"{obj.get('local_yi')}亿{obj.get('local_currency') or value.get('currency')}"
                if obj.get("local_yi") is not None
                else None
            ),
            "end_date": value.get("end_date"),
            "metric_period": value.get("period"),
            "yoy": yoy,
            "change_status": change_status,
            "yoy_state": change_meta.get("state") if change_meta else None,
            "yoy_valid_for_comparison": (
                change_meta.get("valid_for_comparison") if change_meta else None
            ),
            "source_ids": [source_id] if source_id else [],
            "basis": value.get("statement_basis"),
            "coverage_note": (company.get("financial_series", {}).get("coverage") or {}).get("company_note"),
        })
    return json.dumps(rows, ensure_ascii=False)


def _profile_source_keys(item: dict[str, Any]) -> list[str]:
    name = item["name"]
    listed = item.get("listed_key")
    company_pages = {
        "大族激光": ["hans_laser_group"],
        "东威科技": ["dongwei_web"],
        "正业科技": ["zhengye_pcb"],
        "天准科技": ["tianzhun_electronics"],
        "英诺激光": ["inno_laser_web"],
        "燕麦科技": ["yanmade_web"],
        "矩子科技": ["jutze_web"],
        "凯格精机": ["gage_web"],
        "宜美智": ["ymz_web"],
        "大量科技": ["taliang_web"],
        "志圣工业": ["csun_web"],
        "SCREEN Holdings": ["screen_ledia"],
        "Schmoll": ["schmoll_web"],
        "Cohu": ["cohu_atg_sale"],
        "AMADA": ["amada_via"],
    }
    keys: list[str] = list(company_pages.get(name, []))
    if listed in {"hans_cnc", "hans_laser"}:
        keys += ["hans_h", "hans_a"]
    if listed == "dongwei":
        keys += ["dongwei_a"]
    if listed == "cfmee":
        keys += ["cfmee_h", "cfmee_a"]
    if name == "KLA" or name == "Orbotech":
        keys += ["kla_pcb", "kla_ttm", "kla_2025_10k"]
    if name in {"MKS Instruments", "ESI"}:
        keys += ["mks_esi"]
    if "atg" in name or name == "Mycronic" or name == "Cohu":
        keys += ["mycronic_atg", "mycronic_atg_current"]
    if "Nidec" in name:
        keys += ["nidec_history"]
    if name == "Via Mechanics":
        keys += ["amada_via", "ushio_via", "via_solution"]
    if name == "Camtek":
        keys += ["camtek_sale"]
    if name == "三菱电机":
        keys += ["mitsubishi_drill"]
    if name == "JCU":
        keys += ["jcu_products"]
    if name == "LPKF":
        keys += ["lpkf_scope"]
    if item.get("ticker"):
        keys.append("tushare" if item.get("market") == "A股" else "yfinance")
    return list(dict.fromkeys(keys))


def _official_profile_event(
    item: dict[str, Any],
    source_keys: list[str],
    source_ids: dict[str, int],
) -> list[dict[str, Any]]:
    """Return real dated corporate actions; identity verification stays in source_ids."""
    specs = {spec.key: spec for spec in SOURCES}
    official_key = COMPANY_EVENT_SOURCE_KEYS.get(item["name"])
    if official_key is None:
        return []
    if official_key not in source_keys or official_key not in source_ids or official_key not in specs:
        raise RuntimeError(f"{item['name']}缺少公司事件来源{official_key}")
    spec = specs[official_key]
    if not spec.publish_date or spec.publish_date == "未标明":
        raise RuntimeError(f"{item['name']}的公司事件缺少实际日期")
    return [{
        "date": spec.publish_date,
        "title": spec.title,
        "summary": spec.note or item["group"],
        "source_id": source_ids[official_key],
    }]


def _profile_display_note(
    item: dict[str, Any],
    listing_status: str,
    market: dict[str, Any],
    financial_context: dict[str, Any],
) -> str:
    """Explain only the financial convention that applies to this entity."""
    prefix = f"{item['group']}。"
    if listing_status == "private":
        return prefix + "私营主体没有可核验的独立公开财务，因此不展示估值、利润率或现金流。"
    if listing_status == "subsidiary_or_brand":
        return (
            prefix
            + "该主体没有独立上市财务；如需财务参照，只能查看其归属母公司或集团，"
            "不得把集团收入、利润或估值当作该业务主体的独立数据。"
        )

    if not financial_context.get("metric_period"):
        return prefix + "公开接口没有返回可比损益序列，因此不参与最新增长和盈利能力比较。"
    note = (
        f"{prefix}估值行情日为{market.get('trade_date') or '无可用行情日'}；"
        "毛利率、重算净利率、经营现金流、研发费用率和资本开支采用"
        f"{financial_context['metric_period']}，截至"
        f"{financial_context['metric_end_date'] or '无可用日期'}；"
        f"损益序列最新展示日为{financial_context['latest_displayed_series_date'] or '无'}。"
        "净利率按同期间归母/可归属净利润÷营业收入重算；毛利率保留报表或数据商口径。"
    )
    if item.get("market") == "A股":
        note += "A股2026年一季度损益为年初至期末累计口径。"
    else:
        note += "海外上市公司的损益和资产负债数据按该公司自身财年及报告期展示。"
    return note


def _clean_company_card_text(value: str) -> str:
    """Remove draft-only locators while retaining the human-readable claim."""
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", str(value or ""))
    text = re.sub(r"`[^`]+`", "", text)
    text = re.split(r"\s*来源：", text, maxsplit=1)[0]
    return re.sub(r"\s+", " ", text).strip()


def load_company_cards() -> dict[str, dict[str, str]]:
    """Parse the reviewed 28-card evidence draft into Viewer profile fields."""
    if not COMPANY_CARDS_PATH.is_file():
        return {}
    text = COMPANY_CARDS_PATH.read_text(encoding="utf-8")
    headings = list(re.finditer(r"^###\s+\d+\.\s+(.+?)\s*$", text, flags=re.MULTILINE))
    aliases = {
        "SCREEN": "SCREEN Holdings",
        "Nidec-Read（现 Nidec Advance Technology）": "Nidec Advance Technology（原Nidec-Read）",
        "Atg L&M（现 atg Mycronic）": "atg Mycronic（原atg L&M）",
    }
    field_labels = {
        "identity": "身份与财务边界",
        "products": "产品卡位",
        "customers": "公开客户与验证",
        "advantages_and_risks": "优势与短板",
    }
    result: dict[str, dict[str, str]] = {}
    for index, match in enumerate(headings):
        raw_name = match.group(1).strip()
        name = aliases.get(raw_name, raw_name)
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        body = text[match.end():end]
        card: dict[str, str] = {}
        for key, label in field_labels.items():
            field = re.search(
                rf"^-\s+\*\*{re.escape(label)}：\*\*\s*(.+?)\s*$",
                body,
                flags=re.MULTILINE,
            )
            if field:
                card[key] = _clean_company_card_text(field.group(1))
        if card:
            result[name] = card
    return result


def ensure_companies(
    conn: sqlite3.Connection,
    industry_id: int,
    source_ids: dict[str, int],
    *,
    financial_path: Path = FINANCIAL_PATH,
) -> dict[str, int]:
    financial = json.loads(financial_path.read_text(encoding="utf-8"))
    financial_by_key = {row["key"]: row for row in financial["companies"]}
    company_cards = load_company_cards()
    ids: dict[str, int] = {}
    for item in COMPANY_IDENTITIES:
        row = conn.execute("SELECT id FROM company WHERE name=?", (item["name"],)).fetchone()
        if row:
            company_id = int(row["id"])
        else:
            company_id = int(conn.execute("INSERT INTO company(name) VALUES(?)", (item["name"],)).lastrowid)
        ids[item["name"]] = company_id
        fin = financial_by_key.get(item.get("listed_key")) if item.get("ticker") else None
        market = fin.get("market_snapshot", {}) if fin else {}
        reconciliation = market.get("bps_basis_reconciliation") or {}
        safe_bps = market.get("bps_mrq") if reconciliation.get("direct_current_pb_recalculation_allowed") is not False else None
        listing_status = "listed" if item.get("ticker") else ("private" if item["name"] in {"宜美智", "Schmoll"} else "subsidiary_or_brand")
        conn.execute(
            """
            UPDATE company SET ticker=?,market=?,listing_status=?,note=?,brief_intro=?,brief_intro_src=?,
              pe_ttm=?,pe_forward=?,pb=?,ps_ttm=?,ev_ebitda=?,peg=?,roe=?,roa=?,eps_ttm=?,bps_mrq=?,
              per_share_currency=?,market_cap_cny=?,market_cap_usd=?,market_cap_value=?,market_cap_unit=?,
              valuation_as_of=?,market_cap_cny_as_of=?,financial_metrics_as_of=?,valuation_source_id=?,
              financial_metrics_source_id=?,display_mode='quantitative'
            WHERE id=?
            """,
            (
                item.get("ticker"), item.get("market"), listing_status, item["group"], item["summary"],
                f"^src:{source_ids[_profile_source_keys(item)[0]]}" if _profile_source_keys(item) else None,
                market.get("pe_ttm"), market.get("pe_forward"), market.get("pb"), market.get("ps_ttm"),
                market.get("ev_ebitda"), market.get("peg"), market.get("roe"), market.get("roa"),
                market.get("eps_ttm"), safe_bps, market.get("per_share_currency"), market.get("market_cap_cny"),
                market.get("market_cap_usd"), market.get("market_cap_cny"), "亿元人民币" if market.get("market_cap_cny") is not None else None,
                market.get("trade_date"), market.get("trade_date"), market.get("financial_metrics_as_of"),
                source_ids.get("tushare" if item.get("market") == "A股" else "yfinance") if item.get("ticker") else None,
                source_ids.get("tushare" if item.get("market") == "A股" else "yfinance") if item.get("ticker") else None,
                company_id,
            ),
        )
        conn.execute(
            "INSERT OR IGNORE INTO company_industry(company_id,industry_id) VALUES(?,?)",
            (company_id, industry_id),
        )
        conn.execute(
            "UPDATE company_industry SET role=?,note=? WHERE company_id=? AND industry_id=?",
            (item["role"], item["group"], company_id, industry_id),
        )
        source_keys = _profile_source_keys(item)
        profile_source_ids = [source_ids[key] for key in source_keys if key in source_ids]
        recent_events_json = json.dumps(
            _official_profile_event(item, source_keys, source_ids),
            ensure_ascii=False,
        )
        card = company_cards.get(item["name"], {})
        profile_summary = item["summary"]
        if card.get("identity"):
            profile_summary = f"{profile_summary} {card['identity']}"
        main_products = card.get("products") or item["products"]
        main_customers = card.get("customers") or item["customers"]
        risk_text = card.get("advantages_and_risks") or "集团财务纯度、客户具名、18层以上收入拆分及持续量产验证不足。"
        risks_json = json.dumps([{
            "type": "company_specific",
            "text": risk_text,
            "source_id": profile_source_ids[0] if profile_source_ids else None,
        }], ensure_ascii=False)
        financial_context = _profile_financial_context(fin or {})
        latest = financial_context["metric_row"]
        gross_margin = latest.get("gross_margin")
        net_margin = latest.get("net_margin")
        ocf = (latest.get("operating_cash_flow") or {}).get("cny_yi")
        capex = (latest.get("capex") or {}).get("cny_yi")
        rd_ratio = latest.get("rd_ratio")
        revenue_series = _series(fin or {}, "revenue", source_ids.get("tushare" if item.get("market") == "A股" else "yfinance"))
        net_income_series = _series(fin or {}, "net_income", source_ids.get("tushare" if item.get("market") == "A股" else "yfinance"))
        display_note = _profile_display_note(
            item,
            listing_status,
            market,
            financial_context,
        )
        if item["name"] in {"芯碁微装", "凯格精机"}:
            display_note += " 当前BPS与交易日PB的股本口径未完成复权对账，故暂不展示BPS。"
        conn.execute("DELETE FROM company_profile WHERE company_id=? AND industry_id=?", (company_id, industry_id))
        conn.execute(
            """
            INSERT INTO company_profile(
              company_id,industry_id,period,revenue_series,net_income_series,gross_margin,net_margin,
              operating_cash_flow,ocf_unit,financials_as_of,rd_expense_ratio,capex_value,capex_unit,
              main_products,main_customers,tech_node,recent_events,risks,is_china_tech_leader,
              in_global_table,in_china_table,listing_status,source_ids,summary,display_note,
              last_updated,last_verified_at,brief_intro,brief_intro_src,main_customers_src_id,tech_node_src_id
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                company_id, industry_id,
                financial_context["period_label"] if fin else "未单独披露",
                revenue_series, net_income_series, gross_margin, net_margin,
                ocf, "亿元人民币" if ocf is not None else None,
                financial_context["financials_as_of"],
                rd_ratio, capex, "亿元人民币" if capex is not None else None, main_products, main_customers,
                item["role"], recent_events_json, risks_json,
                0, 0, 0,
                listing_status, json.dumps(profile_source_ids, ensure_ascii=False), profile_summary, display_note,
                AS_OF_DATE, AS_OF_DATE, profile_summary, f"^src:{profile_source_ids[0]}" if profile_source_ids else None,
                profile_source_ids[0] if profile_source_ids else None, profile_source_ids[0] if profile_source_ids else None,
            ),
        )
    conn.execute(
        """
        UPDATE company_profile
        SET is_china_tech_leader=0,in_global_table=0,in_china_table=0
        WHERE industry_id=?
        """,
        (industry_id,),
    )
    return ids


def ensure_sub_market_shares(
    conn: sqlite3.Connection,
    industry_id: int,
    company_ids: dict[str, int],
    source_ids: dict[str, int],
) -> None:
    """Write only the three issuer-disclosed, denominator-specific share facts."""
    rows = (
        {
            "company": "大族数控",
            "sub_market": "全部PCB专用设备",
            "geo": "全球",
            "share": 6.5,
            "share_as_of": "2024",
            "rank": 1,
            "source_key": "hans_h",
            "source_excerpt_ref": "大族数控H股招股书第134页",
            "display_note": "2024年全球全部PCB专用设备市场；发行人委聘灼识咨询估计。",
        },
        {
            "company": "大族数控",
            "sub_market": "全部PCB专用设备",
            "geo": "中国",
            "share": 10.1,
            "share_as_of": "2024",
            "rank": 1,
            "source_key": "hans_h",
            "source_excerpt_ref": "大族数控H股招股书第135页",
            "display_note": "2024年中国全部PCB专用设备市场；发行人委聘灼识咨询估计。",
        },
        {
            "company": "芯碁微装",
            "sub_market": "PCB直接成像设备",
            "geo": "全球",
            "share": 18.8,
            "share_as_of": "2025",
            "rank": None,
            "source_key": "cfmee_h",
            "source_excerpt_ref": "芯碁微装H股招股章程第11页",
            "display_note": "2025年全球PCB直接成像设备市场；发行人委聘灼识咨询估计，原文未给出可核验排名。",
        },
    )
    conn.execute(
        "DELETE FROM company_sub_market_share WHERE industry_id=?",
        (industry_id,),
    )
    for row in rows:
        conn.execute(
            """
            INSERT INTO company_sub_market_share(
              company_id,industry_id,sub_market,geo,share,share_as_of,rank,
              source_ids,source_excerpt_ref,credibility,display_note
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                company_ids[row["company"]],
                industry_id,
                row["sub_market"],
                row["geo"],
                row["share"],
                row["share_as_of"],
                row["rank"],
                json.dumps([source_ids[row["source_key"]]], ensure_ascii=False),
                row["source_excerpt_ref"],
                "发行人招股文件所载独立行业顾问估计",
                row["display_note"],
            ),
        )

    conn.execute(
        """
        UPDATE company_profile
        SET global_share=NULL,global_share_as_of=NULL,global_rank=NULL,
            china_share=NULL,china_share_as_of=NULL,china_rank=NULL,
            global_share_sub_market=NULL,china_share_sub_market=NULL
        WHERE industry_id=?
        """,
        (industry_id,),
    )
    conn.execute(
        """
        UPDATE company_profile
        SET global_share=6.5,global_share_as_of='2024',global_rank=1,
            global_share_sub_market='全部PCB专用设备',
            china_share=10.1,china_share_as_of='2024',china_rank=1,
            china_share_sub_market='全部PCB专用设备'
        WHERE industry_id=? AND company_id=?
        """,
        (industry_id, company_ids["大族数控"]),
    )
    conn.execute(
        """
        UPDATE company_profile
        SET global_share=18.8,global_share_as_of='2025',global_rank=NULL,
            global_share_sub_market='PCB直接成像设备'
        WHERE industry_id=? AND company_id=?
        """,
        (industry_id, company_ids["芯碁微装"]),
    )


def ensure_relations(conn: sqlite3.Connection, industry_id: int, source_ids: dict[str, int]) -> None:
    for downstream_name, note in (
        ("PCB制造", "曝光、压合、钻孔、电镀、检测、成型和自动化设备服务全部PCB制造。"),
        ("高多层PCB板", "本研究重点为18层以上高多层板的压合、机械钻背钻、深孔电镀、成像与检测。"),
    ):
        downstream = conn.execute("SELECT id FROM industry WHERE name=?", (downstream_name,)).fetchone()
        if not downstream:
            continue
        conn.execute(
            """
            INSERT INTO industry_relation(upstream_id,downstream_id,relation_type,source_id,note)
            VALUES(?,?,'供应',?,?)
            ON CONFLICT(upstream_id,downstream_id,relation_type)
            DO UPDATE SET source_id=excluded.source_id,note=excluded.note
            """,
            (industry_id, int(downstream["id"]), source_ids["hans_h"], note),
        )


def extract_section(path: Path, marker: str, next_markers: list[str]) -> str:
    text = path.read_text(encoding="utf-8")
    start = text.find(marker)
    if start < 0:
        raise ValueError(f"missing marker {marker} in {path}")
    start += len(marker)
    ends = [text.find(value, start) for value in next_markers]
    ends = [value for value in ends if value >= 0]
    end = min(ends) if ends else len(text)
    section = text[start:end].strip().strip("-").strip()
    # 每个编号章节都是同一层级；子章节仍保留四级标题。避免只把第1节
    # 升为二级标题、后续章节误嵌套在第1节之下。
    return re.sub(r"^### (?=\d+\.)", "## ", section, flags=re.MULTILINE)


def citationize(text: str, source_ids: dict[str, int]) -> str:
    phrase_map = (
        (("大族数控 H 股", "大族 H 股"), "hans_h"),
        ((
            "大族数控 2026 年 H 股招股书", "大族流程图", "4,499 台", "3D 背钻",
            "490.2 万元/台", "10,000 片/小时", "机械/激光成型精度", "±50/±20μm",
            "16—22 周", "2—8 周", "6—8 周", "8—10 周", "768,000 点",
            "D+4mil", "4±2mil", "81.76 亿美元", "17.35 亿美元", "47.47 亿美元",
            "大族 2024 年推出并销售 2 台", "大族 2024 年仅销售 2 台",
            "大族压合 2024 年售出 2 台", "压合 2024 年仅售 2 台",
            "压合设备 2024 年只有 2 台", "25μm 探针",
        ), "hans_h"),
        (("大族数控 A 股",), "hans_a"),
        (("芯碁微装 H 股",), "cfmee_h"),
        (("芯碁微装 A 股",), "cfmee_a"),
        (("东威科技招股", "东威招股"), "dongwei_a"),
        ((
            "20:1", "TP≥95%", "25μm±2.5μm", "25μm±4μm", "鹏鼎、健鼎",
            "节水约 60%", "节电约 30%", "节省铜球约 13%",
        ), "dongwei_a"),
        ((
            "475 台", "227.35 万元", "100.2%", "2025 年芯碁 PCB DI",
            "MAS/NEX", "200—480/230—480", "10.799 亿元", "57 亿元",
            "验收一般为 1—3 个月", "验收过程通常需要 1—3 个月",
        ), "cfmee_h"),
        (("广发证券", "红板科技"), "guangfa_202607"),
        (("东吴证券",), "dongwu_202602"),
        (("Tushare",), "tushare"),
        (("yfinance", "Yahoo Finance"), "yfinance"),
        (("Orbotech", "KLA PCB产品", "KLA 的 PCB", "KLA/SCREEN"), "kla_pcb"),
        (("TTM采用", "TTM 采用", "TTM 客户案例", "Neos 800"), "kla_ttm"),
        (("KLA FY2025", "KLA FY 2025", "PCB & Component Inspection"), "kla_2025_10k"),
        (("ESI", "MKS"), "mks_esi"),
        (("atg", "Mycronic", "Cohu"), "mycronic_atg"),
        (("atg Mycronic", "当前atg", "当前 atg"), "mycronic_atg_current"),
        (("Nidec-Read", "Nidec Advance"), "nidec_history"),
        (("Via Mechanics", "AMADA"), "amada_via"),
        (("Camtek",), "camtek_sale"),
        (("三菱电机",), "mitsubishi_drill"),
        (("JCU",), "jcu_products"),
        (("LPKF",), "lpkf_scope"),
        (("TTM 2024", "TTM Technologies 2024", "TTM 官方年报"), "ttm_2024_10k"),
        (("ISU Petasys", "ISU 官方"), "isu_business"),
        (("第五工厂", "3,000 亿韩元", "3000 亿韩元"), "isu_factory"),
        (("深南电路泰国", "深南泰国"), "shennan_thailand"),
        (("金像电子 2024", "金像电子年报"), "gce_2024"),
    )
    output: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("> 本文件是可供正式研究包") or stripped.startswith("> 本文件为可直接复用"):
            continue
        refs: list[int] = []
        explicit_keys = re.findall(r"\[\[src:([a-z0-9_]+)\]\]", line)
        line = re.sub(r"\s*\[\[src:[a-z0-9_]+\]\]", "", line)
        for key in explicit_keys:
            if key not in source_ids:
                raise ValueError(f"底稿引用了未注册来源: {key}")
            refs.append(source_ids[key])
        for phrases, key in phrase_map:
            if any(phrase in line for phrase in phrases):
                refs.append(source_ids[key])
        missing_tokens = [
            f"^src:{source_id}"
            for source_id in dict.fromkeys(refs)
            if f"^src:{source_id}" not in line
        ]
        if missing_tokens:
            citation_text = " ".join(missing_tokens)
            # A token appended after the closing pipe becomes an unintended,
            # headerless column.  Keep citations inside the final data cell so
            # tables retain their authored column contract and do not overflow.
            if line.lstrip().startswith("|") and line.rstrip().endswith("|"):
                line = f"{line.rstrip()[:-1].rstrip()} {citation_text} |"
            else:
                line = f"{line} {citation_text}"
        output.append(line.rstrip())
    return "\n".join(output).strip()


def frontmatter(industry_id: int, dimension: str, title: str) -> str:
    return (
        "---\n"
        "entity_type: industry\n"
        f"entity_id: {industry_id}\n"
        f"name: {INDUSTRY_NAME}\n"
        f"research_dimension: {dimension}\n"
        "status: 深度跟踪\n"
        "tier: 1\n"
        f"last_updated: {AS_OF_DATE}\n"
        "author: codex_research_workflow_v2\n"
        "ai_synthesized: true\n"
        "research_track: B\n"
        "research_prompt: PCB板专用设备prompt.md\n"
        f"document_title: {title}\n"
        "data_tier_note: 全部PCB设备、18层以上高多层相关设备、HDI与载板口径严格分开；2030为本研究单年外推。\n"
        "---\n\n"
    )


def bibliography(source_ids: dict[str, int], used_source_ids: set[int]) -> str:
    lines = ["## 来源索引", ""]
    for spec in SOURCES:
        if spec.key not in source_ids or source_ids[spec.key] not in used_source_ids:
            continue
        stale = "；用于历史基线" if spec.publish_date[:4].isdigit() and int(spec.publish_date[:4]) <= 2024 else ""
        date_label = f"页面未标明发布日；网页核验日{AS_OF_DATE}" if spec.publish_date == "未标明" else spec.publish_date
        lines.append(f"- ^src:{source_ids[spec.key]} {spec.publisher}《{spec.title}》（{date_label}{stale}）")
    return "\n".join(lines)


def insert_before_statement(text: str, extra: str) -> str:
    statement = "本研究基于公开信息、公司披露及第三方机构资料整理，存在数据口径、时效性和估算假设等限制，不构成任何投资建议。"
    pos = text.rfind(statement)
    if pos < 0:
        return f"{text}\n\n{extra}"
    before = text[:pos].rstrip()
    return f"{before}\n\n{extra}\n\n{statement}"


def write_documents(
    industry_id: int,
    source_ids: dict[str, int],
    *,
    docs_dir: Path = DOCS_DIR,
    source_cache_dir: Path = CACHE_DIR,
) -> dict[str, dict[str, Any]]:
    core = source_cache_dir / "agent_core_draft.md"
    market = source_cache_dir / "agent_market_draft.md"
    economics = source_cache_dir / "agent_economics_synthesis_draft.md"
    sections = {
        "main": extract_section(core, "## 【主文档】", ["## 【Q0 历史发展】"]),
        "Q0": extract_section(core, "## 【Q0 历史发展】", ["## 【Q3 公司壁垒】"]),
        "Q3": extract_section(core, "## 【Q3 公司壁垒】", ["## 本草稿使用的主要一手材料"]),
        "Q1": extract_section(market, "## 【Q1 竞争格局】", ["## 【Q2 市场空间】"]),
        "Q2": extract_section(market, "## 【Q2 市场空间】", ["## 本草稿使用的主要证据"]),
        "Q4": extract_section(economics, "## 【Q4 行业特征】", ["## 【Q5 综述】"]),
        "Q5": extract_section(economics, "## 【Q5 综述】", []),
    }
    chart_blocks = {
        "Q1": """
## 关键竞争图表

![PCB设备区域市场结构](/static/generated/pcb_equipment/regional_market_stack.png)

> 图表口径：2025—2029为Prismark/灼识咨询机构预测；2030为本研究按各地区披露CAGR单年外推。分项独立取整后的2030合计比总量外推高0.23亿美元，来自一位小数CAGR的舍入传播，不强行配平。欧洲未单列，美洲不等同北美。 ^src:{hans_h}

![可核验份额和集中度](/static/generated/pcb_equipment/share_comparison.png)

> 图表口径：全球/中国全设备采用2024年收入；PCB直接成像采用2025年收入。三组分母不同，只能分别解读。 ^src:{hans_h} ^src:{cfmee_h}

![上市主体市值与集团收入增速参照图](/static/generated/pcb_equipment/company_bubble.png)

> 图表口径：横轴为2026-07-17市值，纵轴为可得的2025集团收入同比，气泡为集团收入；仅纳入字段相对完整的上市经济主体。母子公司和多业务集团不能直接横比，该图只作经营与估值参照，不是竞争份额图。大族全设备份额与芯碁DI份额分母不同，公开资料不足以画同一口径“份额—增速”气泡图。 ^src:{tushare} ^src:{yfinance} ^src:{hans_h} ^src:{cfmee_h}
""",
        "Q2": """
## 市场与产线测算图

![全球PCB设备市场按设备类别拆分](/static/generated/pcb_equipment/equipment_market_stack.png)

> 图表口径：2025—2029为Prismark/灼识咨询机构预测；2030为本研究按各设备类别披露CAGR单年外推。分项独立取整后的2030合计比总量外推高0.16亿美元，来自一位小数CAGR的舍入传播，不强行配平。全部PCB设备口径，不是18层以上专用市场。 ^src:{hans_h}

![无产能尺度示意设备篮子](/static/generated/pcb_equipment/equipment_basket_waterfall.png)

> 图表口径：只汇总七项“假设数量×公开价格锚”可计算部分，共4.886亿元；其中0.636亿元为可选HDI激光模块，不含可选模块为4.250亿元。AOI/AVI/X-ray及其他湿制程和自动化因没有同口径数量、单价或完整BOM而不计入，不能把图中小计解释成标准整线、采购报价或投资预测。 ^src:{guangfa_202607} ^src:{hans_h}
""",
    }
    titles = {
        "main": "PCB专用设备：边界、工艺与核心设备",
        "Q0": "PCB专用设备历史发展与技术路线演进",
        "Q1": "PCB专用设备竞争格局",
        "Q2": "PCB专用设备市场空间与产线测算",
        "Q3": "PCB专用设备公司壁垒",
        "Q4": "PCB专用设备行业特征",
        "Q5": "PCB专用设备研究综述",
    }
    labels = {"main": "主文档", "Q0": "Q0 历史发展", "Q1": "Q1 竞争格局", "Q2": "Q2 市场空间", "Q3": "Q3 公司壁垒", "Q4": "Q4 行业特征", "Q5": "Q5 综述"}
    result: dict[str, dict[str, Any]] = {}
    docs_dir.mkdir(parents=True, exist_ok=True)
    for key, body in sections.items():
        body = citationize(body, source_ids)
        if key in chart_blocks:
            body += "\n\n" + chart_blocks[key].format(**source_ids).strip()
        used_source_ids = {int(value) for value in re.findall(r"\^src:(\d+)", body)}
        source_index = bibliography(source_ids, used_source_ids)
        body = re.sub(r"^### 1\. ", "## 1. ", body, count=1, flags=re.MULTILINE)
        body = f"# 【{labels[key]}】{titles[key]}\n\n{body}"
        if key == "Q5":
            body = insert_before_statement(body, source_index)
        else:
            body = f"{body}\n\n{source_index}"
        path = docs_dir / DOC_FILES[key]
        path.write_text(frontmatter(industry_id, key, titles[key]) + body.strip() + "\n", encoding="utf-8")
        result[key] = {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha256(path)}
    return result


def write_md_versions(conn: sqlite3.Connection, documents: dict[str, dict[str, Any]], source_ids: dict[str, int]) -> None:
    source_json = json.dumps(sorted(source_ids.values()), ensure_ascii=False)
    for key, meta in documents.items():
        conn.execute(
            """
            INSERT INTO md_section_version(md_path,section_anchor,last_updated,last_source_ids,metrics_covered,review_pending,summary)
            VALUES(?,?,?,?,?,0,?)
            ON CONFLICT(md_path,section_anchor) DO UPDATE SET
              last_updated=excluded.last_updated,last_source_ids=excluded.last_source_ids,
              metrics_covered=excluded.metrics_covered,review_pending=0,summary=excluded.summary
            """,
            (meta["path"], key, AS_OF_DATE, source_json, json.dumps([key], ensure_ascii=False), f"PCB专用设备B轨{key}正式正文"),
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--bootstrap-only", action="store_true")
    parser.add_argument("--financial-input", type=Path, default=FINANCIAL_PATH)
    parser.add_argument("--manifest", type=Path, default=CACHE_DIR / "application_manifest.json")
    parser.add_argument(
        "--staging-docs-dir",
        type=Path,
        help="只向指定暂存目录重生成文档；不打开或写入数据库。",
    )
    parser.add_argument("--industry-id", type=int, default=23)
    args = parser.parse_args()
    if args.staging_docs_dir:
        source_ids = source_ids_from_map()
        documents = write_documents(
            args.industry_id,
            source_ids,
            docs_dir=args.staging_docs_dir.resolve(),
        )
        print(json.dumps({
            "mode": "staging_documents_only_no_database_write",
            "industry_id": args.industry_id,
            "documents": documents,
        }, ensure_ascii=False, indent=2))
        return
    conn = connect(args.db.resolve())
    conn.execute("BEGIN IMMEDIATE")
    try:
        industry_id = ensure_industry(conn)
        if args.bootstrap_only:
            conn.commit()
            print(json.dumps({"industry_id": industry_id, "db": str(args.db)}, ensure_ascii=False))
            return
        source_ids = source_ids_from_map()
        company_ids = ensure_companies(
            conn,
            industry_id,
            source_ids,
            financial_path=args.financial_input.resolve(),
        )
        ensure_sub_market_shares(conn, industry_id, company_ids, source_ids)
        ensure_relations(conn, industry_id, source_ids)
        documents = write_documents(industry_id, source_ids)
        write_md_versions(conn, documents, source_ids)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    manifest = {
        "industry_id": industry_id,
        "company_count": len(company_ids),
        "documents": documents,
        "source_ids": source_ids,
        "applied_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    output = args.manifest.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({**manifest, "manifest_sha256": sha256(output)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
