#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Apply the validated HDI research package to the live research DB and Viewer.

The unified ingest entry owns all ``industry_data_point`` writes.  This adapter
only registers profile-only sources, upserts industry/company aggregates, and
renders the standard A/B Markdown artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

try:
    from .hdi_research_data import COMPANY_SPECS, SOURCE_SPECS
except ImportError:
    from hdi_research_data import COMPANY_SPECS, SOURCE_SPECS


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "research.db"
FINANCIAL_DB = ROOT / "data" / "financial.db"
DOCS_DIR = ROOT / "docs" / "industries"
CACHE_DIR = ROOT / "cache" / "hdi_research"
INDUSTRY_NAME = "HDI板"
RUN_TAG = "hdi_b_20260726"
AS_OF_DATE = "2026-07-26"

DOC_FILES = {
    "main": "HDI板.md",
    "Q0": "HDI板_Q0_历史发展.md",
    "Q1": "HDI板_Q1_竞争格局.md",
    "companies": "HDI板_公司透视.md",
    "valuation": "HDI板_估值对比.md",
    "Q2": "HDI板_Q2_市场空间.md",
    "Q3": "HDI板_Q3_公司壁垒.md",
    "Q4": "HDI板_Q4_行业特征.md",
    "Q5": "HDI板_Q5_综述.md",
}

COMPANY_LINKS = {
    "华通电脑": 589,
    "AT&S": 218,
    "TTM Technologies": 562,
    "欣兴电子": 467,
    "健鼎科技": 563,
    "名幸电子": 593,
    "臻鼎科技": 561,
    "胜宏科技": 555,
    "鹏鼎控股": 556,
    "景旺电子": 558,
    "红板科技": 633,
    "沪电股份": 326,
    "深南电路": 472,
    "方正科技": 582,
    "生益电子": 583,
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_file(spec: dict[str, Any]) -> str | None:
    name = spec.get("source_file")
    return f"papers/HDI/{name}" if name else None


def _source_audit_note(spec: dict[str, Any]) -> str:
    parts = [
        f"文档级独立键={spec['independence_key']}",
        str(spec.get("independence_rationale") or "").strip(),
    ]
    market_key = str(spec.get("market_data_independence_key") or "").strip()
    if market_key:
        parts.extend(
            [
                f"市场数据底层独立键={market_key}",
                str(spec.get("market_data_independence_rationale") or "").strip(),
            ]
        )
    return "；".join(part.rstrip("。；") for part in parts if part) + "。"


def register_sources(conn: sqlite3.Connection, industry_id: int) -> dict[str, int]:
    """Register sources used only by company profiles or narrative analysis."""
    source_ids: dict[str, int] = {}
    for spec in SOURCE_SPECS:
        file_path = _source_file(spec)
        source_url = spec.get("source_url")
        row = None
        if file_path:
            row = conn.execute("select id from source where file_path=?", (file_path,)).fetchone()
        elif source_url:
            row = conn.execute(
                "select id from source where source_url=? or url=?",
                (source_url, source_url),
            ).fetchone()
        if row:
            source_id = int(row["id"])
            conn.execute(
                "update source set note=? where id=?",
                (_source_audit_note(spec), source_id),
            )
        else:
            source_id = int(
                conn.execute(
                    """
                    insert into source(
                      title,source_type,publisher,publish_date,quality_tier,
                      is_forward_looking,file_path,url,value_layer,source_url,
                      source_subtype,fetch_timestamp,fetch_method,domain,language,
                      is_primary_source,source_credibility,source_channel,note
                    ) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        spec["title"],
                        spec.get("source_type", "website_material"),
                        spec.get("publisher"),
                        spec.get("publish_date"),
                        int(spec.get("quality_tier", 3)),
                        int(
                            spec.get("source_ref")
                            in {
                                "victory_h_prospectus",
                                "gs_ai_pcb_tam",
                                "nomura_victory_20260713",
                                "yx_victory_20260709",
                                "ubs_pengding_20260529",
                                "gf_pengding_20260630",
                                "cj_kinwong_20260628",
                                "trendforce_rubin_hdi",
                            }
                        ),
                        file_path,
                        source_url,
                        "双层" if int(spec.get("quality_tier", 3)) <= 2 else "信息流",
                        source_url,
                        "company_filing"
                        if spec.get("is_primary_source") and file_path
                        else "official_web"
                        if spec.get("is_primary_source")
                        else "research_report",
                        f"{AS_OF_DATE}T09:00:00+08:00",
                        spec.get("fetch_method", "web_fetch"),
                        urlparse(source_url).netloc if source_url else None,
                        spec.get("language", "zh"),
                        int(bool(spec.get("is_primary_source"))),
                        spec.get("source_credibility", "trusted_project_source"),
                        spec.get("source_channel", "web"),
                        _source_audit_note(spec),
                    ),
                ).lastrowid
            )
        conn.execute(
            """
            insert or ignore into source_entity(source_id,entity_type,entity_id,coverage)
            values(?,?,?,?)
            """,
            (source_id, "industry", industry_id, "主要覆盖"),
        )
        source_ids[spec["source_ref"]] = source_id
    return source_ids


def upsert_profiles(
    conn: sqlite3.Connection, industry_id: int, source_ids: dict[str, int]
) -> None:
    for item in COMPANY_SPECS:
        company_id = int(item["company_id"])
        row = conn.execute(
            "select id,name,ticker,listing_status from company where id=?", (company_id,)
        ).fetchone()
        if not row or row["name"] != item["name"]:
            raise RuntimeError(
                f"公司身份不匹配 company_id={company_id}: "
                f"expected={item['name']} actual={row['name'] if row else None}"
            )
        source_ref_ids = [
            source_ids[ref]
            for ref in item.get("source_refs", [item["source_ref"]])
        ] + [source_ids["redboard_sse_reply"]]
        source_ref_ids = sorted(set(source_ref_ids))
        conn.execute(
            """
            insert into company_industry(company_id,industry_id,role,note)
            values(?,?,?,?)
            on conflict(company_id,industry_id) do update set
              role=excluded.role,note=excluded.note
            """,
            (
                company_id,
                industry_id,
                item["role"],
                f"{item['summary']} 财务和估值读取独立公司财务数据库，不复制供应商快照。",
            ),
        )
        conn.execute(
            "delete from company_profile where company_id=? and industry_id=?",
            (company_id, industry_id),
        )
        conn.execute(
            """
            insert into company_profile(
              company_id,industry_id,period,global_share,global_share_as_of,
              global_rank,china_share,china_share_as_of,china_rank,
              main_products,main_customers,customer_concentration,tech_node,
              recent_events,risks,is_china_tech_leader,in_global_table,
              in_china_table,listing_status,source_ids,summary,display_note,
              brief_intro,brief_intro_src,last_updated,last_verified_at
            ) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                company_id,
                industry_id,
                "2025/2026",
                item.get("global_share"),
                "2023" if item.get("global_share") is not None else None,
                item.get("global_rank"),
                item.get("china_share"),
                "2024" if item.get("china_share") is not None else None,
                item.get("china_rank"),
                item["products"],
                "按终端和平台披露核验；未公开客户名称不补写",
                None,
                item["tech"],
                json.dumps(
                    [
                        {
                            "date": AS_OF_DATE,
                            "title": "HDI业务近期进展",
                            "detail": item["recent"],
                            "source_ids": source_ref_ids,
                            "is_major": True,
                        }
                    ],
                    ensure_ascii=False,
                ),
                json.dumps(
                    [
                        {
                            "label": "核心风险",
                            "text": item["risk"],
                            "source_id": source_ids[item["source_ref"]],
                        }
                    ],
                    ensure_ascii=False,
                ),
                int(
                    item["name"]
                    in {
                        "胜宏科技",
                        "鹏鼎控股",
                        "景旺电子",
                        "沪电股份",
                        "深南电路",
                        "红板科技",
                    }
                ),
                int(item.get("global_rank") is not None),
                int(item.get("china_rank") is not None),
                row["listing_status"] or ("listed" if row["ticker"] else "unlisted"),
                json.dumps(source_ref_ids),
                item["summary"],
                (
                    f"{item['role']}。{item['tech']} 近期：{item['recent']} "
                    "结构化财务与当前估值由公司详情页实时读取公司财务数据库。"
                ),
                item["summary"],
                "公司年报、公告与行业份额资料",
                AS_OF_DATE,
                AS_OF_DATE,
            ),
        )


def _frontmatter(
    industry_id: int, title: str, *, dimension: str | None = None
) -> str:
    rows = [
        "---",
        "entity_type: industry",
        f"entity_id: {industry_id}",
        f"name: {INDUSTRY_NAME}",
        "parent: PCB制造",
        "status: 深度跟踪",
        "tier: 1",
        f"last_updated: {AS_OF_DATE}",
        "author: codex_research_loop",
        "ai_synthesized: true",
        "research_track: B",
        "research_prompt: HDI板研究Prompt.md",
        f"document_title: {title}",
        'core_dynamic: "AI服务器把HDI需求从手机主板扩展到高层、高密度和高可靠互连，但增长由架构、认证、良率与有效供给共同决定。"',
        'data_tier_note: "市场统计、机构预测、本次情景估算和公司实际值分层展示；全球公司份额与中国大陆产值地份额不混算。"',
    ]
    if dimension:
        rows.append(f"research_dimension: {dimension}")
    rows += ["---", ""]
    return "\n".join(rows)


def _c(source_ids: dict[str, int], *refs: str) -> str:
    return " ".join(f"^src:{source_ids[ref]}" for ref in refs)


def _link(name: str) -> str:
    company_id = COMPANY_LINKS[name]
    return f"[{name}](/company/{company_id})"


def _source_index(
    conn: sqlite3.Connection, source_ids: dict[str, int], refs: Iterable[str]
) -> str:
    ids = [source_ids[ref] for ref in dict.fromkeys(refs)]
    rows = []
    for source_id in ids:
        row = conn.execute(
            "select id,title,publisher,publish_date,quality_tier from source where id=?",
            (source_id,),
        ).fetchone()
        rows.append(
            f"- ^src:{row['id']} {row['title']}（{row['publisher'] or '发布方未标注'}，"
            f"{row['publish_date'] or '日期未标注'}，来源等级 T{row['quality_tier']}）"
        )
    return "\n## 来源索引\n\n" + "\n".join(rows) + "\n"


def _write_doc(
    conn: sqlite3.Connection,
    source_ids: dict[str, int],
    industry_id: int,
    key: str,
    title: str,
    body: str,
    refs: list[str],
) -> Path:
    path = DOCS_DIR / DOC_FILES[key]
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (
        _frontmatter(industry_id, title, dimension=key if key.startswith("Q") else None)
        + body.strip()
        + "\n"
        + _source_index(conn, source_ids, refs)
    )
    path.write_text(text, encoding="utf-8")
    return path


def _load_financial_inputs() -> tuple[
    dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]
]:
    actual = json.loads(
        (CACHE_DIR / "wind_actual_snapshot.json").read_text(encoding="utf-8")
    )
    ledger = json.loads(
        (CACHE_DIR / "financial_assumption_ledger.json").read_text(encoding="utf-8")
    )
    reconcile = json.loads(
        (CACHE_DIR / "external_reconciliation_summary.json").read_text(encoding="utf-8")
    )
    overseas = json.loads(
        (CACHE_DIR / "overseas_peer_snapshot.json").read_text(encoding="utf-8")
    )
    return actual, ledger, reconcile, overseas


def _actual_row(actual: dict[str, Any], ticker: str) -> dict[str, float | None]:
    annual = actual["wind"]["annual"]["2025"][ticker]
    current = actual["wind"]["current"][ticker]
    return {
        "revenue": annual.get("OPER_REV") / 1e8 if annual.get("OPER_REV") is not None else None,
        "profit": annual.get("NP_BELONGTO_PARCOMSH") / 1e8
        if annual.get("NP_BELONGTO_PARCOMSH") is not None
        else None,
        "ocf": annual.get("NET_CASH_FLOWS_OPER_ACT") / 1e8
        if annual.get("NET_CASH_FLOWS_OPER_ACT") is not None
        else None,
        "capex": annual.get("CASH_PAY_ACQ_CONST_FIOLTA") / 1e8
        if annual.get("CASH_PAY_ACQ_CONST_FIOLTA") is not None
        else None,
        "roe": annual.get("ROE"),
        "roa": annual.get("ROA2"),
        "gross_margin": annual.get("GROSSPROFITMARGIN"),
        "net_margin": annual.get("NETPROFITMARGIN"),
        "market_cap": current.get("MKT_CAP_ARD") / 1e8
        if current.get("MKT_CAP_ARD") is not None
        else None,
        "price": current.get("CLOSE"),
        "pe_ttm": current.get("PE_TTM"),
        "pe_ftm": current.get("PE_EST_FTM"),
        "pb": current.get("PB_LF"),
        "roe_ttm": current.get("ROE_TTM"),
        "roa_ttm": current.get("ROA2_TTM"),
    }


def _benchmark(
    reconcile: dict[str, Any], ticker: str, metric: str, year: int
) -> tuple[float | None, int]:
    for row in reconcile["details"]:
        if (
            row["ticker"] == ticker
            and row["metric"] == metric
            and int(row["year"]) == year
        ):
            return float(row["benchmark_median"]), int(row["report_count"])
    return None, 0


def build_docs(
    conn: sqlite3.Connection,
    industry_id: int,
    source_ids: dict[str, int],
) -> list[Path]:
    actual, ledger, reconcile, overseas = _load_financial_inputs()
    c = lambda *refs: _c(source_ids, *refs)

    main_refs = [
        "ipc_4104",
        "ttm_10k_2025",
        "redboard_sse_reply",
        "shennan_ar2025",
        "wus_ar2025",
        "gs_ai_pcb_tam",
        "ipc_microvia_warning",
        "nvidia_gb200_userguide",
        "trendforce_rubin_hdi",
    ]
    main = f"""
# HDI板：从手机主板走向AI服务器高密度互连

> **核心结论。** HDI不是“层数更多的PCB”，而是用激光微孔、盲埋孔、顺序增层、铜填孔与细线路，在有限面积内提高互连密度。2024年全球HDI产值约125.18亿美元，最新Prismark预测2030年达到244.90亿美元；增长最快的增量来自AI服务器和高速交换，但传统手机仍是当前最大应用。高端机会因此同时具备“旧市场大、新市场快”的特征，不能把全部HDI都当AI，也不能把全部AI PCB都当HDI。{c('ipc_4104','shennan_ar2025','redboard_sse_reply')}

![全球HDI市场预测](/static/generated/hdi/global_hdi_market.png)

## 1. 问题：HDI到底包括什么

### 证据与数据

IPC/JPCA-4104把HDI关键结构限定为不大于0.15毫米的微孔、不大于0.35毫米的焊盘，以及不大于0.15毫米的增层介质；TTM的公开口径把微孔、细线路和多层微孔互连作为先进HDI的核心。两者共同说明：HDI首先由**孔、线和互连结构**定义，而不是由总层数单独定义。{c('ipc_4104','ttm_10k_2025')}

| 产品 | 主要结构 | 本研究是否纳入HDI市场 | 与AI服务器的关系 |
|---|---|---|---|
| 普通多层板/HLC | 机械通孔、多层压合，层数可很高 | 只有同时采用HDI结构的部分纳入 | 大量服务器主板和背板仍属于高多层通孔板 |
| 1+N+1、2+N+2 HDI | 单面一至两次顺序增层，可错孔或叠孔 | 纳入 | 管理板、网卡、部分加速模组与交换板 |
| 高阶HDI/Any-layer | 三阶以上或任意层激光微孔互连 | 纳入 | OAM、UBB、ASIC模组及高密度交换互连 |
| SLP/mSAP | 更细线路、类载板工艺 | 单列，不与普通HDI机械合并 | 可能用于超细线路板卡，但当前AI服务器量产证据有限 |
| IC载板 | 承载裸芯片封装 | 排除 | 属于封装基板市场 |
| FPC、刚挠结合板 | 柔性或刚柔复合介质 | 排除独立市场，相关公司能力单列 | 用于局部连接，不替代全部刚性主板 |

### 研究与分析

HDI升级解决的是高I/O封装下的逃线和空间问题。机械通孔会贯穿多层并占用布线通道；微孔和via-in-pad把垂直互连压缩到需要的层间，使BGA焊盘周围能布置更多高速信号与电源网络。越高阶的顺序增层意味着更多激光钻孔、填孔电镀、对位和压合循环，单位面积价值通常上升，但每增加一次循环也增加累积报废风险。

### 总结

**判断企业能力时，至少要同时看HDI阶数、微孔结构、量产状态、良率、客户认证和可复制产能；“最高层数”或“能打样”都不能独立代表商业壁垒。**

## 2. 问题：产业链的价值增量落在哪里

### 证据与数据

上游包括低损耗覆铜板、超低轮廓铜箔、玻纤布、树脂、半固化片、油墨与湿化学品，也包括激光钻孔、LDI曝光、压合、填孔电镀、AOI/X-ray和可靠性测试设备。中游从内层图形、棕化、顺序压合、激光微孔、除胶渣、沉铜填孔到表面处理和终检。下游覆盖手机、消费电子、汽车、通信、服务器和AI算力系统。2024年全球HDI应用中，通信为66.25亿美元，其中手机56.74亿美元；服务器为12.84亿美元，仍不是最大分母。{c('redboard_sse_reply')}

![2024年全球HDI应用结构](/static/generated/hdi/hdi_application_2024.png)

### 研究与分析

AI服务器带来的变化不是单纯增加板面积，而是提高每块板的层数、增层次数、材料等级、钻孔数量和验证强度。NVIDIA官方文档显示GB200 NVL72由18个计算托盘、9个NVLink交换托盘以及管理交换、供电和液冷部件构成；这能证明板卡节点显著增加，但官方文档没有公开每块PCB尺寸、供应商和HDI工艺，因此不能从“27个托盘”直接推导HDI面积。TrendForce对Rubin的前瞻判断进一步指出，24层HDI交换托盘和更高层中板可能替代部分线缆连接；在正式BOM和量产料号出现前，这只能作为需求上行情景。{c('nvidia_gb200_userguide','trendforce_rubin_hdi')}

### 总结

**真正的价值量来自“更多互连节点 × 更高工艺复杂度 × 更严格可靠性”，而不是服务器出货量乘一个固定PCB单价。**

## 3. 问题：市场和竞争是否同时进入上行周期

### 证据与数据

| 指标 | 结果 | 口径 |
|---|---:|---|
| 全球HDI市场 | 2024年125.18亿美元；2030E 244.90亿美元 | Prismark 2025Q4产品市场 |
| 2025—2030E CAGR | 9.2% | 最新预测版本 |
| 全球CR3/CR5/CR7 | 24.4% / 37.2% / 48.9% | 2023年全球公司HDI销售额 |
| 中国大陆CR3/CR5/CR10 | 13.2% / 17.5% / 25.1% | 2024年大陆生产地公司HDI销售额 |
| 中国大陆生产地占全球 | 62.7% | 2024年产地口径，不是中国企业全球份额 |

{c('redboard_sse_reply','shennan_ar2025')}

### 建模方法

集中度按同年、同地域、同市场分母的公司份额直接加总：**CRn＝前n家公司份额之和**。全球榜和中国大陆榜年份、地域及分母不同，因此分别计算，绝不拼成一个“全球中国厂商排名”。

### 研究与分析

全球HDI头部份额由{_link('华通电脑')}、{_link('AT&S')}、{_link('TTM Technologies')}、{_link('欣兴电子')}、{_link('健鼎科技')}、{_link('名幸电子')}和{_link('臻鼎科技')}占据，前七家合计48.9%；但大陆产值地榜前十家只有25.1%，说明大陆制造基地多、生产分散，而全球高阶客户关系和技术组合仍较集中。对于A股，{_link('胜宏科技')}、{_link('鹏鼎控股')}、{_link('景旺电子')}、{_link('沪电股份')}、{_link('深南电路')}和{_link('红板科技')}的机会不应仅按大陆份额排序，而应看AI平台对应的高阶HDI/HLC量产与资本回报。{c('redboard_sse_reply')}

### 总结

**行业需求上行已经有市场预测和公司扩产支持；供给端是否短缺仍取决于高阶有效产能，而不是所有HDI名义产能。**

## 4. 重点阅读路径

- [历史发展与地域迁移](/industry/{industry_id}/q/Q0)：从手机HDI、Any-layer到AI高层HDI。
- [竞争格局](/industry/{industry_id}/q/Q1)：全球/大陆CR3与CR5、公司分层和有效供给。
- [公司透视](/industry/{industry_id}/companies)：重点公司经营、产能、风险和可点击公司详情。
- [估值对比](/industry/{industry_id}/valuation)：Wind实际财务、独立FY1—FY3模型和近期研报对账。
- [市场空间](/industry/{industry_id}/q/Q2)：总HDI与AI服务器HDI的分层模型。
- [公司壁垒](/industry/{industry_id}/q/Q3)：流程、良率、可靠性和国产替代。
- [行业特征](/industry/{industry_id}/q/Q4)：订单、折旧、现金流和周期。
- [综合判断](/industry/{industry_id}/q/Q5)：结论、风险与验证指标。
"""

    q0_refs = [
        "ipc_4104",
        "ipc_microvia_warning",
        "ttm_10k_2025",
        "ttm_hdi_product",
        "ats_ar2025_26",
        "compeq_ar2024",
        "meiko_ar2025",
        "zdt_ar2025",
        "redboard_sse_reply",
        "trendforce_rubin_hdi",
    ]
    q0 = f"""
# Q0 历史发展：HDI如何从手机主板演进到AI服务器

## 1. 问题：HDI为何出现

### 证据与数据

表面贴装和BGA封装持续细间距化后，传统贯通孔占用的布线通道成为限制。IPC在1999年的HDI材料规范已把微孔、微小焊盘和薄增层介质单列；这说明HDI并非AI时代才出现，而是消费电子小型化积累了二十余年的制造体系。{c('ipc_4104')}

### 研究与分析

早期一阶HDI通过单次激光微孔和顺序增层解决手机主板逃线；二阶与多阶HDI继续增加盲孔层、叠孔和铜填孔。Any-layer把激光微孔扩展到任意相邻层，使厚度和布线密度进一步优化；SLP/mSAP则把部分线宽线距推向载板化。技术每前进一步，设备、材料和良率约束都更强。

### 总结

**HDI的历史主线是“封装I/O密度上升—机械孔空间不足—微孔和增层次数增加—可靠性验证加严”，不是简单的层数竞赛。**

## 2. 问题：技术演进如何映射到终端

### 证据与数据

| 阶段 | 主要终端 | 典型结构 | 新增制造门槛 |
|---|---|---|---|
| 1990s末—2000s | 功能手机、早期便携设备 | 1+N+1，错孔为主 | 激光微孔、薄介质、基础填孔 |
| 2010s前半 | 智能手机、平板 | 2+N+2及更高阶，叠孔增加 | 多次压合、铜填孔、层间对位 |
| 2010s后半 | 高端手机、可穿戴 | Any-layer、SLP/mSAP | 任意层互连、细线路和翘曲控制 |
| 2020s前半 | 汽车域控、通信、高速网络 | 高可靠HDI、刚挠结合 | 热循环、CAF、寿命和跨工厂一致性 |
| 2025年以后 | AI服务器、交换托盘、ASIC系统 | 4+N+4至6+N+6、高层HDI/HLC融合 | 低损耗材料、高层对位、大板翘曲、平台认证 |

TTM披露常规生产超过30层、复杂板可超过70层，并把多层微孔互连定义为先进HDI；这说明服务器高层板与HDI正在交叉，但两者仍不能画等号。IPC对微孔潜在失效的警告表明，一些缺陷可在回流焊或服役后才暴露，传统截面验收并不足以覆盖全部可靠性风险。{c('ttm_10k_2025','ipc_microvia_warning')}

### 研究与分析

AI服务器把手机时代积累的HDI能力重新组合：板更大、层数更高、通道速率和功耗更高，热循环更严苛。Rubin的cableless前瞻架构把一部分原由铜缆承担的连接移回交换托盘和中板，HDI与HLC由过去的“二选一”转为同一块板上的复合能力。{c('trendforce_rubin_hdi')}

### 总结

**Any-layer经验是进入AI高阶HDI的必要能力之一，但不是充分条件；大尺寸、高层、低损耗和长期可靠性是新增门槛。**

## 3. 问题：全球制造分工如何变化

### 证据与数据

中国台湾和日本企业长期掌握手机、消费电子及汽车高阶HDI客户；欧美企业更偏高可靠、工业、航天国防和高混合生产；韩国供应链受智能终端与存储客户带动；中国大陆在2024年已承接全球62.7%的HDI生产地价值；东南亚则成为客户地域分散与新增高端产能的重要承载地。{c('redboard_sse_reply','compeq_ar2024','meiko_ar2025','zdt_ar2025','ats_ar2025_26')}

### 研究与分析

“大陆生产占比高”并不表示大陆总部企业已取得相同的全球高端份额，因为华通、臻鼎、名幸等外资企业也在大陆设厂。真正的产业迁移有两条：一条是大陆本土企业从消费/通信板进入AI高阶HDI；另一条是台湾、日本和欧美龙头把增量产能转向东南亚或本土，以满足客户供应链韧性要求。两条迁移都会增加资本开支，只有认证与稼动率兑现后才转化为利润。

### 总结

**未来三年的竞争不是单向“国产替代”，而是大陆技术升级与全球产能再布局同时发生；客户、工厂和总部三个地域维度必须分开。**
"""

    q1_refs = [
        "redboard_sse_reply",
        "shennan_ar2025",
        "wus_ar2025",
        "victory_h_prospectus",
        "prismark_top100_2024",
        "compeq_ar2024",
        "ats_ar2025_26",
        "ttm_10k_2025",
        "meiko_ar2025",
        "zdt_ar2025",
        "zdt_huaian_investment",
        "victory_ar2025",
        "pengding_ar2025",
        "kinwong_ar2025",
    ]
    q1 = f"""
# Q1 竞争格局：全球高端集中，大陆产值分散

## 1. 问题：全球与中国市场有多集中

### 证据与数据

| 榜单与分母 | CR3 | CR5 | 扩展集中度 | 头部公司 |
|---|---:|---:|---:|---|
| 2023年全球HDI公司销售额 | 24.4% | 37.2% | CR7 48.9% | 华通、AT&S、TTM、欣兴、健鼎、名幸、臻鼎 |
| 2024年中国大陆生产地HDI销售额 | 13.2% | 17.5% | CR10 25.1% | 沪电、汕头超声、方正、建滔、胜宏、红板等 |

全球CR3＝10.0%＋7.7%＋6.7%＝24.4%；全球CR5再加6.6%和6.2%＝37.2%。大陆CR3＝8.0%＋2.8%＋2.4%＝13.2%；大陆CR5再加2.2%和2.1%＝17.5%。所有加总均保留原年份和原分母。{c('redboard_sse_reply')}

![HDI全球与大陆生产地竞争格局](/static/generated/hdi/hdi_competition.png)

### 研究与分析

全球榜更集中，反映大型客户长期认证、跨工厂交付和高阶量产能力形成壁垒；大陆榜更分散，反映生产基地众多且包含外资工厂。{_link('华通电脑')}以10.0%位居全球第一，{_link('AT&S')}和{_link('TTM Technologies')}分别为7.7%和6.7%；大陆榜中{_link('沪电股份')}以8.0%领先，但其HDI与AI高多层业务并存，不能把8.0%直接解释为高阶Any-layer份额。{c('redboard_sse_reply')}

### 总结

**全球CR5 37.2%说明头部客户关系和技术能力集中；大陆CR5 17.5%说明产地分散。两者不是矛盾，而是统计主体不同。**

## 2. 问题：最新市场预测为何明显上修

### 证据与数据

| 预测版本 | 2024 | 2025E | 2026E | 2029E/2030E | 对应增速 |
|---|---:|---:|---:|---:|---:|
| Prismark 2025Q4 | 125.18 | 157.69 | 180.55 | 2030E 244.90 | 2025—2030 CAGR 9.2% |
| Frost & Sullivan较早版本 | 128.00 | 未单列 | 未单列 | 2029E 169.00 | 显著低于最新预测 |

单位均为亿美元，但预测时间、样本和对AI高层HDI的纳入不同，不能取平均。最新Prismark路径隐含2024—2030约11.8%的复合增速；较早F&S路径只反映当时对高阶HDI渗透的判断。{c('shennan_ar2025','victory_h_prospectus')}

### 研究与分析

上修的核心来自AI服务器、交换设备和高阶ASIC架构，而不是手机HDI突然二次爆发。最新预测更适合作为当前市场基线，但预测越乐观，越需要用公司订单、设备搬入、良率、稼动率和现金流验证。若AI平台延后或cableless设计未按预期落地，较早的低路径仍是有效反方。

### 总结

**当前应采用244.90亿美元作为2030年最新基准，同时把169亿美元旧路径保留为需求/渗透率下行情景，而不是把两者平均成一个没有含义的中点。**

## 3. 问题：中国大陆与海外产能怎样分工

### 证据与数据

| 地区 | 2024实际/可得值 | 2030E | 2025—2030E CAGR | 口径说明 |
|---|---:|---:|---:|---|
| 中国大陆 | 78.49亿美元 | 161.26亿美元 | 9.1% | 生产地，不按总部归属 |
| 亚洲其他地区 | 未获得同表2024拆分 | 69.02亿美元 | 10.3% | 含中国台湾、韩国及东南亚等生产地 |
| 美洲 | 未获得同表2024拆分 | 5.91亿美元 | 5.4% | 生产地 |
| 欧洲 | 未获得同表2024拆分 | 3.10亿美元 | 6.6% | 生产地 |
| 日本 | 未获得同表2024拆分 | 5.62亿美元 | 5.2% | 生产地 |

2024年全球125.18亿美元减去大陆78.49亿美元，海外生产地合计约46.69亿美元；最新Prismark预测2030年中国大陆仍占约65.8%，亚洲其他地区增长最快。这里不能把“亚洲其他地区”进一步硬拆成台湾、韩国与东南亚，因为同一预测表未给出可比基年和单独数值。{c('redboard_sse_reply','wus_ar2025')}

### 研究与分析

大陆继续承担全球最大制造份额，台湾、日本和欧美企业则通过大陆、东南亚和本土工厂组合交付。总部地、生产地和最终需求地不是一回事：台湾企业在大陆生产的HDI计入大陆产值，但全球公司份额仍归台湾总部；美国云厂商需求也可能由亚洲工厂生产。区域判断若混用三个维度，会高估本土替代或低估跨国龙头。

### 总结

**2030年增量仍以中国大陆和亚洲其他地区为主；大陆本土企业能否受益，要看公司份额和高阶产品，而不是只看生产地总量。**

## 4. 问题：公司该怎样分层

### 证据与数据

| 层级 | 公司 | 可验证优势 | 需要继续验证 |
|---|---|---|---|
| 全球综合HDI龙头 | {_link('华通电脑')}、{_link('AT&S')}、{_link('TTM Technologies')}、{_link('欣兴电子')}、{_link('健鼎科技')}、{_link('名幸电子')}、{_link('臻鼎科技')} | 2023年全球份额、长期客户与跨区域产能 | AI高层HDI的独立收入和利润率 |
| 大陆AI高阶扩张 | {_link('胜宏科技')}、{_link('鹏鼎控股')}、{_link('景旺电子')}、{_link('红板科技')} | 产线、扩产、样品/量产和实际财务 | 客户认证、有效良率与自由现金流 |
| HLC与HDI交叉龙头 | {_link('沪电股份')}、{_link('深南电路')}、{_link('生益电子')} | 服务器/通信高多层板、材料和工艺协同 | 不能把全部AI高多层收入算作HDI |
| 大陆其他参与者 | {_link('方正科技')}等 | 大陆产值地份额和升级能力 | 高阶HDI具体阶数、客户和量产状态 |

{c('redboard_sse_reply','prismark_top100_2024','victory_ar2025','pengding_ar2025','kinwong_ar2025')}

### 研究与分析

{_link('胜宏科技')}已披露6+24 HDI量产、10+30能力和16层Any-layer能力；{_link('鹏鼎控股')}在淮安和泰国布局IHDI/HLC，规模选择权大但折旧压力也大；{_link('景旺电子')}以珠海HDI/SLP与泰国扩产承接升级；{_link('臻鼎科技')}计划在淮安投入80亿元扩充MSAP、HDI和HLC。每家公司都存在“名义投资—设备搬入—客户认证—批量良率—收入—现金流”的连续门槛，不能在第一步发生时就确认最后一步。{c('victory_ar2025','pengding_ar2025','kinwong_ar2025','zdt_huaian_investment')}

### 总结

**全球份额适合识别客户与规模壁垒；投资排序还必须叠加AI业务纯度、量产状态、资本开支和估值，不能仅按榜单名次。**

## 5. 问题：供给是否真的短缺

### 建模方法

高阶HDI有效供给不等于厂房名义面积。本研究使用：

**有效供给＝名义产能 × 设备可用率 × 目标产品稼动率 × 合格良率 × 已完成客户认证比例。**

公司普遍不披露这五个输入的同口径序列，因此本研究不伪造行业“缺口平方米”。判断短缺改用设备搬入、认证状态、交期、涨价、季度毛利率、在建工程转固和经营现金流交叉验证。

### 研究与分析

当前证据支持高阶能力稀缺，而不支持所有HDI全面缺货。头部公司同时扩产，说明需求预期强；但扩产金额大且2026—2028集中释放，也意味着一旦平台延后或新厂良率改善快于需求，折旧和价格竞争会迅速压低利润率。标准手机HDI、汽车高可靠HDI和AI高层HDI的供需状态应分别跟踪。

### 总结

**基准判断是“高阶有效产能阶段性偏紧、标准HDI并非全面短缺”；验证点是订单、良率和稼动率，而不是公告中的规划面积。**
"""

    company_refs = [
        "redboard_sse_reply",
        "compeq_ar2024",
        "ats_ar2025_26",
        "ttm_10k_2025",
        "meiko_ar2025",
        "zdt_ar2025",
        "victory_ar2025",
        "victory_q1_2026",
        "victory_h_prospectus",
        "pengding_ar2025",
        "pengding_q1_2026",
        "kinwong_ar2025",
        "kinwong_q1_2026",
        "shennan_ar2025",
        "wus_ar2025",
    ]
    core_tickers = [
        ("300476.SZ", "胜宏科技"),
        ("002938.SZ", "鹏鼎控股"),
        ("603228.SH", "景旺电子"),
        ("603459.SH", "红板科技"),
    ]
    actual_rows = []
    forecast_rows = []
    for ticker, name in core_tickers:
        a = _actual_row(actual, ticker)
        model = ledger["companies"][ticker]
        f26, f27, f28 = (model["forecasts"][str(y)] for y in (2026, 2027, 2028))
        p26 = f26["revenue"] * f26["net_margin"] / 100
        p27 = f27["revenue"] * f27["net_margin"] / 100
        p28 = f28["revenue"] * f28["net_margin"] / 100
        actual_rows.append(
            f"| {_link(name)} | {a['revenue']:.2f} | {a['profit']:.2f} | "
            f"{a['gross_margin']:.2f}% | {a['roe']:.2f}% | {a['ocf']:.2f} | {a['capex']:.2f} |"
        )
        forecast_rows.append(
            f"| {_link(name)} | {f26['revenue']:.2f} / {p26:.2f} | "
            f"{f27['revenue']:.2f} / {p27:.2f} | {f28['revenue']:.2f} / {p28:.2f} | "
            f"{model['target_pe'][0]:.0f}—{model['target_pe'][1]:.0f}倍 | {model['key_risk']} |"
        )
    companies = f"""
# 公司透视：谁真正拥有高阶HDI的量产和财务兑现能力

## 1. 问题：全球龙头的优势是什么

### 证据与数据

| 公司 | 2023全球HDI份额 | 技术与终端定位 | 主要判断 |
|---|---:|---|---|
| {_link('华通电脑')} | 10.0% | 手机HDI基本盘，向AI服务器、高速网络和光模块迁移 | 总份额第一，但AI利润结构需单独验证 |
| {_link('AT&S')} | 7.7% | 高端HDI、载板、汽车和工业高可靠 | 专利与工艺强，重资产载板周期影响回报 |
| {_link('TTM Technologies')} | 6.7% | Ultra-HDI、高可靠、航天国防与系统集成 | 北美战略稀缺性高，不等同亚洲大批量模式 |
| {_link('欣兴电子')} | 6.6% | Any-layer、SLP、载板和AI高阶互连 | 客户广、技术面宽，需区分载板与HDI利润 |
| {_link('健鼎科技')} | 6.2% | 消费、服务器、汽车HDI | 规模稳定，AI高阶纯度公开资料有限 |
| {_link('名幸电子')} | 6.2% | 高可靠HDI、汽车与服务器 | 越南扩张增强交付，资本效率需跟踪 |
| {_link('臻鼎科技')} | 5.5% | 手机HDI、MSAP、FPC并向AI/HLC扩张 | 80亿元项目带来增长与折旧双向弹性 |

{c('redboard_sse_reply','compeq_ar2024','ats_ar2025_26','ttm_10k_2025','meiko_ar2025','zdt_ar2025')}

### 研究与分析

全球七强并非同一种商业模式。{_link('华通电脑')}、{_link('欣兴电子')}和{_link('臻鼎科技')}更接近大批量消费电子与先进互连平台；{_link('AT&S')}兼具载板和欧洲高成本结构；{_link('TTM Technologies')}在北美高可靠与国防业务的价格、批量和认证周期不同；{_link('名幸电子')}与{_link('健鼎科技')}则在汽车、服务器和消费之间分散。份额只能说明规模，不能单独决定估值。

### 总结

**全球龙头的共同壁垒是长期客户、跨工厂复制和良率；差异在业务纯度、终端周期、资本强度和地缘布局。**

## 2. 问题：A股重点公司的财务基数怎样

### 证据与数据

以下是2025年集团口径Wind实际值，单位为亿元人民币；它们不是HDI分部收入。结构化数据由公司详情页从独立公司财务数据库动态读取。

| 公司 | 收入 | 归母净利润 | 毛利率 | ROE | 经营现金流 | 资本开支现金支出 |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(actual_rows)}

{c('victory_ar2025','pengding_ar2025','kinwong_ar2025','redboard_sse_reply')}

### 研究与分析

{_link('胜宏科技')}2025年收入192.92亿元、归母净利润43.12亿元、ROE 33.76%，已经把AI产品升级转化成高利润，但66.17亿元资本开支高于46.03亿元经营现金流，说明扩产期自由现金流承压。{_link('鹏鼎控股')}规模最大，2025年收入391.47亿元、净利润37.38亿元，但ROE 11.28%，高端IHDI/HLC扩产能否提升资产回报比收入增长更关键。{_link('景旺电子')}2025年收入153.08亿元、净利润12.31亿元，泰国和珠海扩产带来选择权，2026Q1利润下降提醒新产线并不自动提升盈利。{_link('红板科技')}体量较小、2025年收入36.77亿元而ROE达26.43%，上市后高估值对成长持续性要求更高。

### 总结

**胜宏已经处于利润兑现期，鹏鼎和景旺更接近大规模再投资期，红板则是小基数高回报但估值敏感；四家公司不能套同一增长率或同一估值倍数。**

## 3. 问题：未来三年怎样建模

### 建模方法

独立模型在读取近期卖方预测前冻结，核心公式为：

**营业收入＝上年收入 ×（1＋产能/平台/产品组合驱动的增长率）**  
**归母净利润＝营业收入 × 情景净利率**  
**经营现金流＝归母净利润 × 现金转换率**  
**扩张期现金余量＝经营现金流－资本开支现金支出**

模型不是把行业增速直接套给公司，而是结合2025实际财务、2026Q1表现、工厂投产、HDI阶数、客户认证和资本开支设置公司差异化输入。

| 公司 | 2026E收入/净利 | 2027E收入/净利 | 2028E收入/净利 | 估值参考倍数 | 核心风险 |
|---|---:|---:|---:|---:|---|
{chr(10).join(forecast_rows)}

### 研究与分析

{_link('胜宏科技')}的模型把泰国A1量产和A2/A3爬坡纳入收入，但没有采用卖方最乐观的平台份额；{_link('鹏鼎控股')}的模型承认淮安与泰国带来的规模选择权，同时压低初期净利率以反映折旧；{_link('景旺电子')}的收入假设接近近期单家研报，但利润更保守，差异来自新产线利润率；{_link('红板科技')}缺少两家以上近期卖方模型，因此只用公司实际和情景区间，不伪造“一致预期”。{c('victory_q1_2026','victory_h_prospectus','pengding_q1_2026','kinwong_q1_2026')}

### 总结

**未来三年的最敏感变量不是行业CAGR，而是AI高阶产品收入占比、新厂良率、折旧和现金转换率。公司详情页已保存独立模型、估值结果和市场隐含要求。**

## 4. 问题：HLC与HDI交叉公司如何看

### 研究与分析

{_link('沪电股份')}和{_link('深南电路')}在服务器、高速交换和高多层板上具备强竞争力，但公开财务通常不把HDI结构单独拆出；因此公司页展示完整集团财务和估值，行业研究只把有直接HDI证据的产品纳入份额或市场空间。{_link('生益电子')}处于高端材料/PCB交叉位置，受益于M8/M9材料和高层板升级，但不应因AI收入增长就自动归入Any-layer龙头。{c('wus_ar2025','shennan_ar2025')}

### 总结

**AI服务器受益公司池可以宽于严格HDI公司池；市场规模、份额和公司盈利模型必须使用各自正确分母。**
"""

    valuation_refs = [
        "victory_ar2025",
        "victory_q1_2026",
        "victory_h_prospectus",
        "nomura_victory_20260713",
        "pengding_ar2025",
        "pengding_q1_2026",
        "ubs_pengding_20260529",
        "gf_pengding_20260630",
        "kinwong_ar2025",
        "kinwong_q1_2026",
        "cj_kinwong_20260628",
        "redboard_sse_reply",
        "ttm_q1_2026",
        "ats_fy2025_26_results",
        "twse_company_master_20260725",
        "twse_compeq_20260724",
        "twse_unimicron_20260724",
        "twse_tripod_20260724",
        "twse_zdt_20260724",
        "twse_compeq_price_20260724",
        "twse_unimicron_price_20260724",
        "twse_tripod_price_20260724",
        "twse_zdt_price_20260724",
        "yfinance_compeq_20260726",
        "yfinance_unimicron_20260726",
        "yfinance_tripod_20260726",
        "yfinance_zdt_20260726",
        "yfinance_ttm_20260726",
        "yfinance_ats_20260726",
    ]
    val_rows = []
    for ticker, name in core_tickers:
        a = _actual_row(actual, ticker)
        model = ledger["companies"][ticker]
        f27 = model["forecasts"]["2027"]
        model_profit = f27["revenue"] * f27["net_margin"] / 100
        low, high = model["target_pe"]
        equity_low, equity_high = model_profit * low, model_profit * high
        bench, count = _benchmark(reconcile, ticker, "归母净利润", 2027)
        bench_text = f"{bench:.2f}（{count}家）" if bench is not None else "未形成可比中位数"
        diff_text = (
            f"{(model_profit / bench - 1) * 100:.2f}%"
            if bench
            else "不计算"
        )
        pe_ftm_text = f"{a['pe_ftm']:.2f}" if a["pe_ftm"] is not None else "暂缺"
        val_rows.append(
            f"| {_link(name)} | {a['market_cap']:.2f} | {a['pe_ttm']:.2f} / "
            f"{pe_ftm_text} | {a['pb']:.2f} | "
            f"{model_profit:.2f} | {bench_text} | {diff_text} | "
            f"{equity_low:.2f}—{equity_high:.2f} |"
        )
    overseas_by_name = {row["name"]: row for row in overseas["rows"]}
    twse_rows = []
    for name in ["华通电脑", "欣兴电子", "健鼎科技", "臻鼎科技"]:
        row = overseas_by_name[name]
        official = row["twse_official"]
        yf = row["yfinance"]
        roe = yf.get("returnOnEquity")
        roe_text = f"{roe * 100:.2f}%" if roe is not None else "暂缺"
        forward_pe = yf.get("forwardPE")
        ev_ebitda = yf.get("enterpriseToEbitda")
        twse_rows.append(
            f"| {_link(name)} | {official['market_cap_twd_bn']:.2f} | "
            f"{official['pe']:.2f} | {official['pb']:.2f} | "
            f"{forward_pe:.2f} | {ev_ebitda:.2f} | {roe_text} |"
        )
    ttm_yf = overseas_by_name["TTM Technologies"]["yfinance"]
    ats_yf = overseas_by_name["AT&S"]["yfinance"]
    ttm_op = overseas["official_operating_snapshots"]["TTMI"]
    ats_op = overseas["official_operating_snapshots"]["ATS.VI"]
    overseas_operating_rows = [
        (
            f"| {_link('TTM Technologies')} | 2026Q1 | USD | "
            f"{ttm_yf['marketCap'] / 1e9:.2f} | {ttm_op['revenue_mn']:.1f} / "
            f"{ttm_op['revenue_yoy_pct']:.1f}% | {ttm_op['adjusted_ebitda_margin_pct']:.1f}%* | "
            f"{ttm_op['operating_cash_flow_mn']:.1f} / {ttm_op['capex_mn']:.1f} | "
            f"{ttm_yf['forwardPE']:.2f} | {ttm_yf['priceToBook']:.2f} | "
            f"{ttm_yf['enterpriseToEbitda']:.2f} |"
        ),
        (
            f"| {_link('AT&S')} | FY2025/26 | EUR | "
            f"{ats_yf['marketCap'] / 1e9:.2f} | {ats_op['revenue_mn']:.1f} / "
            f"{ats_op['revenue_yoy_pct']:.1f}% | {ats_op['ebitda_margin_pct']:.1f}% | "
            f"{ats_op['operating_cash_flow_mn']:.1f} / {ats_op['capex_mn']:.1f} | "
            f"{ats_yf['forwardPE']:.2f} | {ats_yf['priceToBook']:.2f} | "
            f"{ats_yf['enterpriseToEbitda']:.2f} |"
        ),
    ]
    valuation = f"""
# 估值对比：高增长需要用利润兑现和资本回报约束

## 1. 问题：当前市场在定价什么

### 证据与数据

数据时点为2026年7月24日；市值单位为亿元人民币，利润为归母口径。近期外部模型只使用最近两个季度内报告：胜宏为野村2026-07-13与永兴2026-07-09，鹏鼎为UBS 2026-05-29与广发2026-06-30，景旺为长江2026-06-28。红板未获得足够的近期可比模型，因此不填中位数。

| 公司 | 当前市值 | PE TTM/FTM | PB | 本研究2027E净利 | 近期机构2027E中位数 | 本研究差异 | 2027E利润×目标PE市值 |
|---|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(val_rows)}

{c('nomura_victory_20260713','ubs_pengding_20260529','gf_pengding_20260630','cj_kinwong_20260628')}

### 研究与分析

{_link('胜宏科技')}当前前瞻PE约17.73倍，看似低于TTM 48.30倍，但它依赖未来一年利润大幅增长；本研究2027E净利润107.50亿元比两家近期机构中位数低23.99%，主要差在产能爬坡和平台份额，而非估值公式。{_link('鹏鼎控股')}本研究2027E净利润52.50亿元比两家近期机构中位数低30.21%，核心分歧是IHDI/HLC扩产能否迅速从折旧转成利润。{_link('景旺电子')}本研究2027E利润18.70亿元比长江证券低33.52%，收入只低4.19%，说明真正的分歧在新产线利润率。{_link('红板科技')}当前PB约15.55倍，必须用持续高ROE和利润增长支撑，单一小基数成长叙事不足以给出精确目标价。

### 总结

**本研究比近期卖方更保守，差异集中在利润率和产能兑现，而不是对行业方向的否定。市场最关键的验证是季度毛利率、在建工程转固后稼动率和经营现金流。**

## 2. 问题：哪些估值方法适用

### 建模方法

核心方法为FY2归母净利润乘以目标PE；目标倍数根据增长、客户与执行风险设区间，不与其他方法机械平均。PB—ROE只作为资产回报诊断：

**合理PB＝（可持续ROE－长期增长率）÷（股权成本－长期增长率）。**

当长期增长接近股权成本时公式极敏感，因此只用于检查当前PB要求的回报强度。DCF在高资本开支期对终值和营运资本极敏感，缺少分业务长期现金流时不作为核心；PS仅用于利润率尚未稳定的对照；EV/EBITDA需注意PCB企业折旧高、不同地区租赁和折旧口径差异。

### 研究与分析

{_link('胜宏科技')}适合PE、EV/EBITDA和现金流压力测试，PB—ROE为辅助；{_link('鹏鼎控股')}账面资产和ROE更有解释力，可同时使用PE与PB—ROE；{_link('景旺电子')}新厂爬坡期应同时看PE和EV/EBITDA；{_link('红板科技')}估值受到流通市值、小基数和上市初期预期影响，更应强调区间与证伪条件。

### 总结

**估值结果的核心不是“选最高的模型”，而是用适用的方法回答：当前价格要求公司在何时达到多少利润、ROE和现金流。**

## 3. 问题：海外与大陆公司能否直接横向比较

### 证据与数据

中国台湾四家公司的收盘价、已发行股本、PE和PB均由台交所单证券接口核验；本币市值按“已发行普通股数×2026年7月24日收盘价÷10亿”计算。前瞻PE、EV/EBITDA和ROE为2026年7月26日yfinance窄字段快照，只作辅助对账。

| 公司 | 市值（十亿新台币） | 台交所PE | 台交所PB | 前瞻PE | EV/EBITDA | ROE |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(twse_rows)}

{c('twse_company_master_20260725','twse_compeq_20260724','twse_compeq_price_20260724','twse_unimicron_20260724','twse_unimicron_price_20260724','twse_tripod_20260724','twse_tripod_price_20260724','twse_zdt_20260724','twse_zdt_price_20260724','yfinance_compeq_20260726','yfinance_unimicron_20260726','yfinance_tripod_20260726','yfinance_zdt_20260726')}

欧美两家公司用各自最新官方报告补经营数据，行情倍数仍来自同日yfinance快照。收入、经营现金流和资本开支均为百万本币，市值为十亿本币。

| 公司 | 最近期间 | 本币 | 市值 | 收入 / 同比 | EBITDA率 | 经营现金流 / 资本开支 | 前瞻PE | PB | EV/EBITDA |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(overseas_operating_rows)}

\\* TTM使用公司披露的Adjusted EBITDA，属于非GAAP指标；AT&S为公司报告的EBITDA。两者财年、业务组合和调整项不同，不能直接按高低排序。{c('ttm_q1_2026','ats_fy2025_26_results','yfinance_ttm_20260726','yfinance_ats_20260726')}

### 研究与分析

估值高低首先反映盈利所处阶段，不等于HDI能力强弱。{_link('欣兴电子')}台交所PE为123.38倍、PB为11.75倍，而yfinance前瞻PE降至24.83倍，说明当前价格主要依赖未来盈利修复；{_link('健鼎科技')}PE 19.10倍、PB 3.54倍和前瞻PE 11.31倍明显更低，但其成熟产品和多场景收入也意味着AI高阶HDI纯度不同。{_link('臻鼎科技')}当前PB 4.10倍低于华通和欣兴，同时ROE约7.14%，市场是否重估取决于淮安高端扩产能否把较低资产回报转成更高利润。

{_link('TTM Technologies')}2026Q1收入同比增长30%，数据中心与网络占收入36%，但经营现金流仅2,170万美元、资本开支1.068亿美元，当季自由现金流约为-8,510万美元；这说明AI需求改善不等于资本回报已经兑现。{_link('AT&S')}2025/26财年收入增长12.7%、EBITDA率23.3%，期间利润仍亏损2,560万欧元；公司对2026/27财年给出30%—35%收入增长、25%—29% EBITDA率和约4亿欧元资本开支指引。AT&S当前高PB和前瞻PE同样要求新产能利用率、利润和现金流共同改善。

海外和中国台湾龙头的财年、币种、业务组合与会计口径不同：{_link('AT&S')}含载板和重资产欧洲工厂，{_link('TTM Technologies')}含航天国防与系统集成，{_link('臻鼎科技')}含FPC与消费电子，{_link('华通电脑')}的手机HDI权重较高。因此可比较的是“当前倍数要求什么盈利与现金流”，不是把全组PE/PB机械排序。

### 总结

**跨市场数据并非客观不可得，但必须分层使用：交易所核验当前估值，公司公告核验经营兑现，yfinance只补可比倍数。当前A股、台股和欧美龙头的高估值都在押注利润修复或AI扩产，真正可比的验证项是增量利润、自由现金流和可持续ROE。**
"""

    q2_refs = [
        "shennan_ar2025",
        "redboard_sse_reply",
        "gs_ai_pcb_tam",
        "nvidia_gb200_userguide",
        "trendforce_rubin_hdi",
        "victory_h_prospectus",
    ]
    q2 = f"""
# Q2 市场空间：总HDI与AI服务器HDI必须分层计算

## 1. 问题：全球HDI的基准市场有多大

### 证据与数据

| 年份 | 全球HDI市场（亿美元） | 数据属性 |
|---|---:|---|
| 2023 | 105.36 | 实际值 |
| 2024 | 125.18 | 实际值 |
| 2025E | 157.69 | Prismark预测 |
| 2026E | 180.55 | Prismark预测 |
| 2030E | 244.90 | Prismark预测 |

2025—2030E复合增速为9.2%。2024年应用中，通信66.25亿美元、消费电子15.85亿美元、计算机14.19亿美元、服务器12.84亿美元、汽车10.69亿美元；手机仍占45.3%左右，服务器约10.3%。{c('redboard_sse_reply','shennan_ar2025')}

![全球HDI市场预测](/static/generated/hdi/global_hdi_market.png)

### 研究与分析

总市场基线说明AI服务器是最快增量而非当前最大存量。若直接把“AI PCB 271.22亿美元”与“全球HDI 244.90亿美元”比较，会混入高多层通孔板、中板、背板和交换板中的非HDI部分，形成重复或越界。

### 总结

**244.90亿美元是2030年当前最可用的全球HDI基准；AI需求模型必须作为其中的结构分项，不得另加到总市场之上。**

## 2. 问题：AI服务器哪些节点真正使用HDI

### 证据与数据

NVIDIA官方文档显示GB200 NVL72包含18个计算托盘、9个NVLink交换托盘、管理交换与配套部件；这验证了机架级系统具有多类板卡节点，但未披露每块PCB面积和工艺。Goldman Sachs把AI服务器PCB拆为GPU服务器、OAM、UBB、主板、中板、背板、交换机板和其他，并进一步把产品技术拆成高多层RPCB与HDI。TrendForce则预期Rubin交换托盘采用24层HDI，中板等部分可达到更高层数。{c('nvidia_gb200_userguide','gs_ai_pcb_tam','trendforce_rubin_hdi')}

| 节点 | HDI判断 | 主要依据 | 不能直接推出什么 |
|---|---|---|---|
| OAM/加速模组 | 高概率采用高阶HDI | 高I/O BGA逃线、5+N+5等卖方技术拆分 | 不能把全部OAM价值都视为同一阶数 |
| UBB/通用基板 | 混合 | 平台可能采用高多层通孔或HDI | 不能按名称自动纳入HDI |
| CPU主板 | 以普通多层/局部HDI为主 | 节点密度低于加速模组 | 不能套手机Any-layer渗透率 |
| 中板/背板 | HLC与HDI交叉 | cableless架构提高互连密度 | 超高层不自动等于HDI |
| NIC/DPU/交换板 | 中高概率 | 端口密度、SerDes与BGA逃线 | 需按板卡和平台逐代核验 |
| 电源/液冷控制 | 多为普通板，局部高可靠 | 功率与控制功能 | 不应为了扩大TAM全部纳入 |

### 总结

**AI服务器HDI需求集中在OAM、高密度交换和部分中板/ASIC模组；主板、背板和控制板中仍有大量高多层通孔板。**

## 3. 问题：AI服务器HDI的价值量怎样测算

### 建模方法

公开资料没有同口径的“服务器出货量 × 每台HDI板数 × 单板面积 × 良率”完整输入。继续搜索NVIDIA官方硬件文档、平台资料和板厂报告后，只能核验托盘与板卡节点，不能获得正式PCB尺寸和供应商BOM。因此本研究采用可复算的价值量主模型：

**AI服务器HDI价值＝AI服务器PCB总价值 × HDI技术占比。**

Goldman模型中，HDI价值为2025E 18.94亿美元、2026E 37.89亿美元、2027E 100.14亿美元；对应AI服务器PCB总价值47.06、100.17和271.22亿美元，HDI占比分别为40.2%、37.8%和36.9%。占比没有上升，价值仍快速增长，原因是总板卡节点和单机价值同步扩大。{c('gs_ai_pcb_tam')}

| 年份 | AI服务器PCB总值 | 其中HDI | HDI占比 | 结论 |
|---|---:|---:|---:|---|
| 2025E | 47.06 | 18.94 | 40.2% | 以5+N+5为主 |
| 2026E | 100.17 | 37.89 | 37.8% | OAM和交换板放量 |
| 2027E | 271.22 | 100.14 | 36.9% | Rubin/ASIC架构假设贡献大 |

单位为亿美元。2027后的情景采用：

**2030 AI服务器HDI＝min〔2027 HDI ×（1＋后续增速）³，2030全球HDI × AI占比上限〕。**

后续增速取15%/20%/25%，得到2030年约152/173/196亿美元；上限约为2030全球HDI的62%/71%/80%。这是本研究情景，不是外部机构原始预测。

![AI服务器PCB节点价值情景](/static/generated/hdi/ai_server_pcb_tam.png)

### 研究与分析

模型最敏感的是架构而非物理面积。若Rubin cableless和ASIC高层HDI按期量产，交换托盘、中板和OAM的价值可以快速上升；若系统通过线缆、连接器或更少板卡实现互连，HDI占比会低于情景。由于板面积和ASP都受层数、材料与良率影响，用“平方米”作为唯一主模型反而会低估结构升级。

### 总结

**基准情景把2030年AI服务器HDI放在约173亿美元；152—196亿美元是高不确定区间，必须用平台BOM、HDI料号和板厂收入逐年校准。**

## 4. 问题：哪些反方会改变市场空间

### 研究与分析

第一，GPU/ASIC出货或AI资本开支不及预期，会直接减少板卡数量。第二，架构保留更多高速线缆而非中板互连，会降低HDI/HLC价值。第三，设计降本可能把部分Any-layer退回局部HDI或高多层通孔。第四，SLP、刚挠结合或连接器方案可能重新分配价值。第五，新增高阶产能若快速爬坡，市场产值仍增长但ASP和利润率可能下行。

### 总结

**需求风险会同时影响出货、HDI渗透和ASP，不能只把总TAM统一下调10%；最先需要验证的是板卡架构与量产料号。**
"""

    q3_refs = [
        "ipc_4104",
        "ipc_microvia_warning",
        "ttm_hdi_product",
        "ttm_10k_2025",
        "victory_ar2025",
        "victory_h_prospectus",
        "ats_patent_quality",
        "redboard_sse_reply",
    ]
    q3 = f"""
# Q3 公司壁垒：良率、可靠性和客户认证比最高阶数更重要

## 1. 问题：高阶HDI怎样制造

### 证据与数据

| 工序 | 关键控制 | 高阶HDI新增难点 | 可验证指标 |
|---|---|---|---|
| 内层成像与蚀刻 | 线宽线距、铜厚、阻抗 | 细线路与低损耗材料附着 | 线宽公差、阻抗分布 |
| 棕化与压合 | 树脂流动、层厚、翘曲 | 多次顺序压合累积偏移 | 压合次数、层间对位、翘曲 |
| 激光钻孔 | 孔径、锥度、残胶 | 微孔数量大、叠孔应力集中 | 孔径、孔形、钻孔节拍 |
| 除胶渣/沉铜 | 孔壁清洁与覆盖 | 微孔底部活化和界面完整 | 孔壁空洞、界面缺陷 |
| 铜填孔电镀 | 填充、凹陷、过镀 | 叠孔平整度和铜结晶 | 填孔率、dimple、铜厚均匀性 |
| 顺序增层 | 每层重复成像/压合/钻孔 | 良率按多次循环累积 | 各段良率、最终一次通过率 |
| 表面处理与成型 | 平整度、可焊性、尺寸 | 大板翘曲和高密度焊盘 | 翘曲、离子污染、尺寸 |
| 可靠性验证 | 回流、热循环、CAF、寿命 | 潜在微孔失效可能晚发 | IST、热冲击、失效截面 |

{c('ipc_4104','ipc_microvia_warning','ttm_hdi_product')}

### 研究与分析

高阶HDI不是把单项参数做到极限，而是让全部工序在批量中稳定。叠孔结构把应力集中在微孔界面；增层次数增加会让早期微小偏差在后续压合放大；低损耗材料又可能改变钻孔、树脂流动和铜附着。单次样板通过电测，不能证明回流焊和长期热循环可靠。

### 总结

**壁垒由多工序联合良率构成，任何一个瓶颈都能让最终有效产能远低于名义产能。**

## 2. 问题：怎样区分能力、认证和量产

### 证据与数据

TTM公开微孔可小至100微米、焊盘约200微米，并披露30层以上常规生产和70层以上复杂板能力；{_link('胜宏科技')}披露6+24量产、10+30能力和16层Any-layer开发/能力信息。两家公司披露维度不同，不能直接做一张“谁更强”的雷达图。{c('ttm_hdi_product','ttm_10k_2025','victory_ar2025')}

### 研究与分析

公司能力应按四级记录：技术储备、样品/送样、客户认证、批量量产。进入量产后还要看良率、交期、跨工厂复制和收入贡献。客户名单若因保密未披露，应写“目前没有直接证据”，不能从卖方或招聘信息反推具名客户。

### 总结

**只有“通过客户认证并在目标工厂稳定量产”才能进入有效供给；实验室极限和样板只影响技术上限。**

## 3. 问题：国产替代的机会和边界

### 证据与数据

中国大陆2024年HDI生产地占全球62.7%，但大陆榜中既有本土企业也有外资工厂；全球七强仍以台湾、日本、欧美企业为主。{_link('胜宏科技')}、{_link('沪电股份')}、{_link('方正科技')}和{_link('红板科技')}已进入大陆HDI产值前列，但不同公司的高阶HDI收入与客户结构披露不一。{c('redboard_sse_reply')}

### 研究与分析

标准HDI的国产化重点是规模、成本和稳定交付；高阶HDI的门槛转向Any-layer、多层叠孔、低损耗大板与AI客户认证；汽车和海外客户还要求更长寿命与地域交付。替代并非一次完成，而是从样品、非核心料号、小批量、主力料号到跨平台复制逐步发生。

### 总结

**中国本土企业的最大机会在AI高阶产品升级，而不是把62.7%的大陆产地份额改写成本土高端份额。**

## 4. 问题：资本开支和导入周期如何约束壁垒

### 研究与分析

公开项目通常披露总投资、厂房和产能，但很少同时披露设备清单、目标产品、验证周期和稳定良率，因此不存在一条适用于所有公司的“标准HDI产线投资额”。实际过程通常经历厂房建设、设备安装、工艺验证、客户认证、小批量和爬坡；越高阶、越高可靠，周期越长。判断时应跟踪在建工程转固、折旧增加、样品收入、季度毛利率、现金流和订单，而不是把投资公告当成收入。

### 总结

**资本开支既是进入壁垒，也是盈利风险；在认证和稼动率兑现前，新增产能先表现为现金流流出和折旧。**
"""

    q4_refs = [
        "victory_ar2025",
        "victory_q1_2026",
        "pengding_ar2025",
        "pengding_q1_2026",
        "kinwong_ar2025",
        "kinwong_q1_2026",
        "redboard_sse_reply",
        "ipc_microvia_warning",
        "trendforce_rubin_hdi",
    ]
    q4 = f"""
# Q4 行业特征：订单先行、折旧滞后，良率决定利润弹性

## 1. 问题：HDI公司的收入怎样形成

### 研究与分析

HDI通常经历NPI打样、工艺评审、可靠性验证、客户认证、小批量和批量量产。新平台收入与客户产品周期绑定，切换供应商需要重新验证材料、叠层、孔结构和可靠性，因此主力料号具有粘性；但客户集中也会放大议价和平台延期风险。公司“进入供应链”不等于立刻获得主力份额，收入取决于认证料号、分配份额、出货和良率。

### 总结

**订单和认证领先收入，收入领先现金流；跟踪HDI不能只看当季利润。**

## 2. 问题：成本和利润率由什么决定

### 证据与数据

HDI成本包括覆铜板、铜箔、树脂与化学品、直接人工、能源、设备折旧、良率损失和质量成本。高阶产品会增加激光钻孔、填孔电镀和压合循环；一块板在后段报废会损失此前全部材料和工时，因此良率对毛利的影响是非线性的。IPC微孔可靠性警告说明晚发缺陷还可能带来返工、保修和客户切换风险。{c('ipc_microvia_warning')}

### 建模方法

单块合格品成本可写为：

**合格品单位成本＝（材料＋人工＋能源＋折旧＋质量成本）÷最终良率。**

因此良率由90%降至80%，即使分子不变，单位成本也会上升12.5%；在多次压合和高价值材料上，实际影响可能更大。

### 研究与分析

铜价和汇率会影响材料端，但高端HDI短期利润更容易被产品组合、良率和稼动率主导。新工厂投产初期折旧先确认、认证收入后确认，毛利率可能先降后升；若客户需求不足，折旧摊薄失败会让利润增长明显慢于收入。

### 总结

**观察利润弹性要把ASP、材料、良率、稼动率和折旧同时放进模型，不能只用收入增速。**

## 3. 问题：行业周期怎样传导

### 证据与数据

消费电子HDI受手机换机和库存周期影响；汽车HDI受车型平台和长认证周期影响；AI服务器则由云厂商资本开支、GPU/ASIC平台、网络架构和电力/液冷配套驱动。TrendForce对Rubin cableless架构的判断属于2026年以后前瞻，其兑现取决于平台量产。{c('trendforce_rubin_hdi')}

| 指标类型 | 领先指标 | 同步指标 | 滞后指标 |
|---|---|---|---|
| 需求 | 云厂商资本开支、GPU/ASIC路线图、客户认证 | 订单、交期、出货 | 板厂收入 |
| 供给 | 厂房/设备订单、招聘、在建工程 | 设备搬入、试产、稼动率 | 转固、折旧、价格竞争 |
| 盈利 | 产品组合和报价 | 毛利率、良率、费用率 | 经营现金流、ROE |

### 研究与分析

AI资本开支上行时，订单和设备投资先出现；产能形成后，若需求继续增长，良率和稼动率推动利润放大；若需求拐头，新产线折旧和库存会让利润下行快于收入。手机、汽车与AI周期不同步，有多终端组合的公司波动较低，但AI纯度也更低。

### 总结

**HDI是高固定成本、长认证、强产品周期行业；景气顶部最危险的信号是扩产集中释放而订单和交期不再上升。**

## 4. 问题：海外产能是护城河还是负担

### 研究与分析

泰国、越南和北美产能可以满足客户地域分散、关税和供应链安全要求，也能进入新的客户认证体系；代价是建设成本、人工效率、跨工厂复制和较长爬坡。{_link('鹏鼎控股')}、{_link('景旺电子')}、{_link('胜宏科技')}以及{_link('名幸电子')}都在不同程度上扩充海外能力。投资价值取决于这些工厂是否获得高阶料号和足够稼动率，而不是“有海外厂”这一标签本身。{c('victory_ar2025','pengding_ar2025','kinwong_ar2025')}

### 总结

**海外布局在认证兑现时提高客户粘性，在订单不足时放大折旧和管理成本；必须逐厂跟踪。**
"""

    q5_refs = [
        "redboard_sse_reply",
        "shennan_ar2025",
        "victory_h_prospectus",
        "gs_ai_pcb_tam",
        "trendforce_rubin_hdi",
        "ipc_microvia_warning",
        "victory_ar2025",
        "pengding_ar2025",
        "kinwong_ar2025",
    ]
    q5 = f"""
# Q5 综述：高阶HDI景气向上，但估值已经要求快速兑现

## 核心判断（摘要）

> **一句话核心判断：** 2025—2030年全球HDI有望保持约9.2%的复合增长，AI服务器HDI可能显著快于行业；真正稀缺的是已认证、可稳定量产的高阶有效产能，而不是名义规划产能。{c('shennan_ar2025','redboard_sse_reply')}

**结论一：市场扩张有数据支撑，但预测分歧很大。** 最新Prismark给出2030年244.90亿美元，较早F&S路径只有2029年169亿美元。基准采用最新预测，下行情景保留旧路径；未来每年用服务器HDI收入、平台BOM和板厂订单重新校准。{c('shennan_ar2025','victory_h_prospectus')}

**结论二：全球高端能力集中、大陆生产分散。** 全球CR3/CR5为24.4%/37.2%，大陆生产地CR3/CR5为13.2%/17.5%；大陆占全球产值62.7%不等于中国本土企业高端份额。{c('redboard_sse_reply')}

**结论三：AI PCB不是HDI。** Goldman模型中2027年AI服务器PCB为271.22亿美元，其中HDI为100.14亿美元；Rubin的24层HDI交换托盘提供上行线索，但正式BOM和量产料号仍是验证条件。{c('gs_ai_pcb_tam','trendforce_rubin_hdi')}

**结论四：公司利润取决于良率和现金流。** {_link('胜宏科技')}已处于高利润兑现和大扩产并行阶段；{_link('鹏鼎控股')}、{_link('景旺电子')}更依赖新产线稼动率；{_link('红板科技')}小基数高ROE但估值敏感。{c('victory_ar2025','pengding_ar2025','kinwong_ar2025')}

## 主要风险及影响估算

| 风险 | 基准假设 | 下行情景影响 | 观察条件 |
|---|---|---|---|
| AI服务器HDI渗透不及预期 | 2030约173亿美元 | 若后2027增速降至15%，约152亿美元，较基准低约12% | 平台BOM、HDI料号、板卡结构 |
| 全球HDI回到旧预测路径 | 2030基准244.90亿美元 | 靠近169亿美元量级，较基准低约31% | Prismark滚动预测、板厂订单 |
| 扩产快于需求 | 高阶有效产能偏紧 | ASP、毛利率和ROE同时下行；重资产公司影响更大 | 交期、稼动率、毛利率、转固 |
| 良率低于计划 | 模型净利率逐步稳定 | 良率90%降至80%时，其他成本不变的单位成本约升12.5% | 一次通过率、返工、客诉 |
| 客户/平台集中 | 主力平台按期量产 | 单一平台延迟会同时下修收入与利润率 | 客户资本开支、认证、份额 |
| 铜价、汇率、贸易 | 成本可部分传导 | 传导滞后压毛利，海外厂投资回报下降 | 铜价、汇率、关税、地区收入 |

{c('shennan_ar2025','victory_h_prospectus','ipc_microvia_warning')}

## 研究与分析

行业方向和投资回报不能混为一谈。总HDI增长、AI服务器板卡价值上升和公司扩产都支持景气，但A股多家公司当前估值已经隐含未来利润快速增长。近期卖方对{_link('胜宏科技')}、{_link('鹏鼎控股')}和{_link('景旺电子')}的2027年利润普遍高于本研究独立模型，差异主要来自新厂产能、产品份额和净利率。若季度财务证明良率和稼动率持续超预期，本研究估值区间应上调；若收入增长但现金流、ROE或毛利率下降，则说明资本开支尚未转化为经济利润。

## 总结

**行业层面偏积极，个股层面应按“认证—量产—良率—利润—现金流”逐级确认。优先关注有高阶HDI直接证据、海外交付能力和现金流改善的公司；避免只凭最大阶数、扩产金额或AI标签追高。**
"""

    paths = [
        _write_doc(conn, source_ids, industry_id, "main", "HDI板主文档", main, main_refs),
        _write_doc(conn, source_ids, industry_id, "Q0", "HDI板历史发展", q0, q0_refs),
        _write_doc(conn, source_ids, industry_id, "Q1", "HDI板竞争格局", q1, q1_refs),
        _write_doc(conn, source_ids, industry_id, "companies", "HDI板公司透视", companies, company_refs),
        _write_doc(conn, source_ids, industry_id, "valuation", "HDI板估值对比", valuation, valuation_refs),
        _write_doc(conn, source_ids, industry_id, "Q2", "HDI板市场空间", q2, q2_refs),
        _write_doc(conn, source_ids, industry_id, "Q3", "HDI板公司壁垒", q3, q3_refs),
        _write_doc(conn, source_ids, industry_id, "Q4", "HDI板行业特征", q4, q4_refs),
        _write_doc(conn, source_ids, industry_id, "Q5", "HDI板综合判断", q5, q5_refs),
    ]
    return paths


def review_docs(
    conn: sqlite3.Connection,
    industry_id: int,
    paths: list[Path],
    source_ids: dict[str, int],
) -> dict[str, Any]:
    valid_ids = {int(row["id"]) for row in conn.execute("select id from source")}
    issues: list[str] = []
    details = []
    forbidden = (
        "canonical",
        "intake",
        "字段完成度",
        "输出覆盖卡",
        "参数 owner",
        "D0",
        "D1",
        "D2",
        "low/mode/high",
        "专属边界",
        "破坏程度",
    )
    all_paragraphs: dict[str, list[str]] = {}
    for path in paths:
        text = path.read_text(encoding="utf-8")
        citations = [int(x) for x in re.findall(r"\^src:(\d+)", text)]
        invalid = sorted(set(citations) - valid_ids)
        if invalid:
            issues.append(f"{path.name}: 无效source引用 {invalid}")
        for token in forbidden:
            if token in text:
                issues.append(f"{path.name}: 包含公开禁用词 {token}")
        if "## 来源索引" not in text:
            issues.append(f"{path.name}: 缺来源索引")
        if len(text) < 2200:
            issues.append(f"{path.name}: 正文过短 {len(text)}")
        if text.count("### 总结") + text.count("## 总结") < 2 and "Q5" not in path.name:
            issues.append(f"{path.name}: 小节总结不足")
        for idx, paragraph in enumerate(re.split(r"\n\s*\n", text)):
            clean = re.sub(r"\^src:\d+", "", paragraph)
            clean = re.sub(r"\s+", "", clean)
            if len(clean) < 160 or clean.startswith(("|", "---", "#")):
                continue
            all_paragraphs.setdefault(clean, []).append(f"{path.name}:{idx}")
        details.append(
            {
                "file": path.name,
                "characters": len(text),
                "citations": len(citations),
                "tables": len(re.findall(r"^\|---", text, re.MULTILINE)),
                "sha256": _sha256(path),
            }
        )
    duplicates = {k[:120]: v for k, v in all_paragraphs.items() if len(v) > 1}
    if duplicates:
        issues.append(f"发现{len(duplicates)}段跨文档长文本完全重复")
    profile_count = int(
        conn.execute(
            "select count(*) from company_profile where industry_id=?", (industry_id,)
        ).fetchone()[0]
    )
    if profile_count < len(COMPANY_SPECS):
        issues.append(f"公司画像不足 {profile_count}/{len(COMPANY_SPECS)}")
    review = {
        "run_tag": RUN_TAG,
        "industry_id": industry_id,
        "status": "GREEN" if not issues else "RED",
        "documents": details,
        "profile_count": profile_count,
        "registered_source_count": len(source_ids),
        "duplicate_paragraphs": duplicates,
        "issues": issues,
    }
    path = CACHE_DIR / "document_and_profile_review.json"
    path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    return review


def financial_review() -> dict[str, Any]:
    conn = sqlite3.connect(FINANCIAL_DB)
    conn.row_factory = sqlite3.Row
    try:
        runs = list(
            conn.execute(
                """
                select run_key,skill_name,model_name,status,
                       independent_before_consensus,input_hash,output_hash,frozen_at
                 from financial_model_run
                 where research_run_ref=? and status<>'superseded'
                 order by run_key
                """,
                (RUN_TAG,),
            )
        )
        securities = {
            row["ticker"]
            for row in conn.execute(
                """
                select distinct fs.ticker
                  from financial_observation fo
                  join financial_security fs on fs.id=fo.security_id
                 where fo.as_of_date='2026-07-24'
                """
            )
        }
        issues = []
        if len(runs) < 12:
            issues.append(f"独立财务/估值模型不足: {len(runs)}/12")
        for row in runs:
            # PB—ROE is a market-linked reverse diagnostic.  It deliberately
            # reads current PB, so it is not labelled independent before
            # consensus; frozen inputs and outputs are still mandatory.
            requires_independent_flag = "pb_roe_diagnostic" not in row["run_key"]
            if (
                requires_independent_flag
                and not row["independent_before_consensus"]
            ) or not row["frozen_at"]:
                issues.append(f"模型未冻结: {row['run_key']}")
            if not row["input_hash"] or not row["output_hash"]:
                issues.append(f"模型缺输入/输出哈希: {row['run_key']}")
        required = {
            "002463.SZ", "002916.SZ", "300476.SZ",
            "002938.SZ", "603228.SH", "603459.SH",
        }
        if not required <= securities:
            issues.append(f"核心公司财务快照缺失: {sorted(required - securities)}")
        result = {
            "reviewer": "deterministic_financial_contract_check",
            "status": "GREEN" if not issues else "RED",
            "model_run_count": len(runs),
            "frozen_model_runs": [dict(row) for row in runs],
            "current_snapshot_security_count": len(securities),
            "issues": issues,
        }
        (CACHE_DIR / "financial_contract_review.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return result
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DB_PATH))
    args = parser.parse_args()
    db_path = Path(args.db)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        industry = conn.execute(
            "select id from industry where name=?", (INDUSTRY_NAME,)
        ).fetchone()
        if not industry:
            raise RuntimeError("请先运行 prepare_hdi_research.py 创建行业壳")
        industry_id = int(industry["id"])
        conn.execute("begin immediate")
        source_ids = register_sources(conn, industry_id)
        upsert_profiles(conn, industry_id, source_ids)
        conn.commit()
        paths = build_docs(conn, industry_id, source_ids)
        review = review_docs(conn, industry_id, paths, source_ids)
        financial = financial_review()
        print(
            json.dumps(
                {
                    "industry_id": industry_id,
                    "sources": len(source_ids),
                    "profiles": len(COMPANY_SPECS),
                    "documents": [str(p) for p in paths],
                    "document_review": review,
                    "financial_review": financial,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
