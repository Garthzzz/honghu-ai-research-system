from __future__ import annotations

"""Apply the copper B-track narrative package after unified claim ingest.

All ``industry_data_point`` rows are owned by ``ingest_research``.  This
adapter only resolves narrative-only sources, links the three deeply modelled
listed companies, writes their industry-specific operating shares, renders
public Markdown and emits deterministic audits.  The competitive universe is
wider and is carried by research facts rather than empty company cards.
"""

import argparse
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .copper_research_content import make_documents
from .copper_research_data import SOURCE_SPECS


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "research.db"
DOCS_DIR = ROOT / "docs" / "industries"
CACHE_DIR = ROOT / "cache" / "copper_research"
INDUSTRY_ID = 26
INDUSTRY_NAME = "铜"
AS_OF_DATE = "2026-07-26"

COMPANIES = (
    {
        "id": 635,
        "name": "紫金矿业",
        "role": "全球综合矿业龙头；铜、金、锂多金属与多项目扩建",
        "products": "矿产铜、矿产金、锂、锌及冶炼产品",
        "tech": "低品位资源开发、地下采矿、大型选冶与跨国项目建设运营",
        "summary": (
            "2025年矿产铜108.5万吨、权益铜88.6万吨；中国境内运营矿山铜"
            "约42.98万吨、占国内矿山铜约23.88%。核心观察为Kamoa恢复、"
            "塞尔维亚和巨龙爬坡，以及多项目资本开支的现金回收。"
        ),
        "risk": "铜金价格回落、Kamoa恢复慢于计划、跨国税费与多项目资本开支失控。",
        "source_refs": (
            "zijin_ar2025",
            "zijin_q1_2026",
            "ivanhoe_kamoa_20260331",
            "usgs_mcs_2026",
        ),
        "global_rank": 4,
        "reported_production_kt": 1085.126,
        "global_share": 4.718,
        "attributable_production_kt": 885.569,
        "attributable_share": 3.850,
        "china_production_kt": 429.809,
        "china_share": 23.878,
        "china_rank": 1,
        "in_china_table": 1,
    },
    {
        "id": 634,
        "name": "洛阳钼业",
        "role": "刚果（金）铜钴大型生产商；兼有钼钨铌磷与全球贸易平台",
        "products": "矿产铜、钴、钼、钨、铌、磷及金属贸易",
        "tech": "TFM/KFM大型湿法与选冶运营、铜钴共生资源开发、全球物流贸易",
        "summary": (
            "2025年铜产量74.1万吨，铜矿业务毛利率55.16%；铜量来自刚果（金）"
            "TFM/KFM，中国境内矿山铜份额为0。核心观察为产量成本、KFM二期、"
            "刚果（金）政策和IXM营运资金。"
        ),
        "risk": "刚果（金）电力、硫酸、税费、出口与现金汇回风险，以及铜钴价格波动。",
        "source_refs": ("cmoc_ar2025", "cmoc_q1_2026", "drc_eiti", "usgs_mcs_2026"),
        "global_rank": 8,
        "reported_production_kt": 741.149,
        "global_share": 3.222,
        "china_share": 0.0,
        "china_rank": None,
        "in_china_table": 0,
    },
    {
        "id": 636,
        "name": "五矿资源",
        "role": "全球铜矿运营商；Las Bambas现金流与Khoemacau扩建",
        "products": "铜精矿、电解铜、锌、铅及伴生金属",
        "tech": "大型露天矿、地下矿与选厂运营，跨区域项目开发和扩建",
        "summary": (
            "2025年Las Bambas、Kinsevere与Khoemacau合计产铜50.6万吨；"
            "三座铜矿均在海外，中国境内矿山铜份额为0。核心观察为Las Bambas"
            "成本、Khoemacau扩建、少数股东和债务。"
        ),
        "risk": "秘鲁社区物流、Khoemacau延期、Kinsevere成本、少数股东分配与债务。",
        "source_refs": ("mmg_ar2025", "mmg_q2_2026", "usgs_mcs_2026"),
        "global_rank": 11,
        "reported_production_kt": 505.745,
        "global_share": 2.199,
        "china_share": 0.0,
        "china_rank": None,
        "in_china_table": 0,
    },
)


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _source_file(spec: dict[str, Any]) -> str | None:
    name = spec.get("source_file")
    return f"papers/铜/{name}" if name else None


def _source_note(spec: dict[str, Any]) -> str:
    return (
        f"文档级独立键={spec['independence_key']}；"
        f"{str(spec.get('independence_rationale') or '').rstrip('。')}。"
    )


def register_sources(
    conn: sqlite3.Connection, industry_id: int
) -> dict[str, int]:
    source_ids: dict[str, int] = {}
    for spec in SOURCE_SPECS:
        file_path = _source_file(spec)
        source_url = spec.get("source_url")
        row = None
        if file_path:
            row = conn.execute(
                "SELECT id FROM source WHERE file_path=?", (file_path,)
            ).fetchone()
        if row is None and source_url:
            row = conn.execute(
                "SELECT id FROM source WHERE source_url=? OR url=?",
                (source_url, source_url),
            ).fetchone()
        if row:
            source_id = int(row["id"])
            conn.execute(
                """UPDATE source
                      SET note=COALESCE(NULLIF(note,''),?)
                    WHERE id=?""",
                (_source_note(spec), source_id),
            )
        else:
            source_id = int(
                conn.execute(
                    """
                    INSERT INTO source(
                      title,source_type,publisher,publish_date,quality_tier,
                      is_forward_looking,file_path,url,value_layer,source_url,
                      source_subtype,fetch_timestamp,fetch_method,domain,language,
                      is_primary_source,source_credibility,source_channel,note
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        spec["title"],
                        spec.get("source_type", "website_material"),
                        spec.get("publisher"),
                        spec.get("publish_date"),
                        int(spec.get("quality_tier", 3)),
                        int(not bool(spec.get("is_primary_source"))),
                        file_path,
                        source_url,
                        "双层" if int(spec.get("quality_tier", 3)) <= 2 else "信息流",
                        source_url,
                        (
                            "company_filing"
                            if spec.get("is_primary_source") and file_path
                            else "official_web"
                            if spec.get("is_primary_source")
                            else "research_report"
                        ),
                        f"{AS_OF_DATE}T12:00:00+08:00",
                        spec.get("fetch_method", "web_fetch"),
                        urlparse(source_url).netloc if source_url else None,
                        spec.get("language", "zh"),
                        int(bool(spec.get("is_primary_source"))),
                        spec.get("source_credibility", "trusted_project_source"),
                        spec.get("source_channel", "web"),
                        _source_note(spec),
                    ),
                ).lastrowid
            )
        conn.execute(
            """
            INSERT OR IGNORE INTO source_entity(
              source_id,entity_type,entity_id,coverage
            ) VALUES(?,?,?,?)
            """,
            (source_id, "industry", str(industry_id), "主要覆盖"),
        )
        source_ids[str(spec["source_ref"])] = source_id
    return source_ids


def upsert_company_profiles(
    conn: sqlite3.Connection,
    industry_id: int,
    source_ids: dict[str, int],
) -> None:
    for item in COMPANIES:
        row = conn.execute(
            "SELECT id,name,ticker,market,listing_status FROM company WHERE id=?",
            (item["id"],),
        ).fetchone()
        if not row or str(row["name"]) != item["name"]:
            raise RuntimeError(
                f"公司身份不匹配 company_id={item['id']} expected={item['name']} "
                f"actual={row['name'] if row else None}"
            )
        ids = sorted(source_ids[ref] for ref in item["source_refs"])
        conn.execute(
            """
            INSERT INTO company_industry(company_id,industry_id,role,note)
            VALUES(?,?,?,?)
            ON CONFLICT(company_id,industry_id) DO UPDATE SET
              role=excluded.role,note=excluded.note
            """,
            (
                item["id"],
                industry_id,
                item["role"],
                item["summary"]
                + " 财务、市场估值和独立模型只读引用financial.db，不复制供应商快照。",
            ),
        )
        conn.execute(
            "DELETE FROM company_profile WHERE company_id=? AND industry_id=?",
            (item["id"], industry_id),
        )
        conn.execute(
            """
            INSERT INTO company_profile(
              company_id,industry_id,period,global_share,global_share_as_of,
              global_share_sub_market,global_rank,
              china_share,china_share_as_of,china_share_sub_market,china_rank,
              main_products,main_customers,customer_concentration,tech_node,
              recent_events,risks,is_china_tech_leader,in_global_table,
              in_china_table,listing_status,source_ids,summary,display_note,
              brief_intro,brief_intro_src,last_updated,last_verified_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                item["id"],
                industry_id,
                "2025A/2026E",
                item["global_share"],
                "2025",
                "全球矿山铜（公司披露/运营口径）",
                item["global_rank"],
                item["china_share"],
                "2025",
                "中国境内矿山铜（运营/并表代理口径）",
                item["china_rank"],
                item["products"],
                "面向全球冶炼、贸易和工业客户；未公开客户不补写",
                None,
                item["tech"],
                json.dumps(
                    [
                        {
                            "date": AS_OF_DATE,
                            "title": "铜业务经营与项目进展",
                            "detail": item["summary"],
                            "source_ids": ids,
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
                            "source_id": ids[0],
                        }
                    ],
                    ensure_ascii=False,
                ),
                1,
                1,
                item["in_china_table"],
                row["listing_status"],
                json.dumps(ids, ensure_ascii=False),
                item["summary"],
                (
                    "项目产量必须区分100%与权益口径；完整财务和估值读取公司财务库，"
                    "行业画像不复制Wind、Tushare或yfinance快照。"
                ),
                item["summary"],
                ids[0],
                AS_OF_DATE,
                AS_OF_DATE,
            ),
        )
        conn.execute(
            "DELETE FROM company_sub_market_share WHERE company_id=? AND industry_id=?",
            (item["id"], industry_id),
        )
        conn.execute(
            """
            INSERT INTO company_sub_market_share(
              company_id,industry_id,sub_market,geo,share,share_as_of,rank,
              source_ids,source_excerpt_ref,credibility,display_note
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                item["id"],
                industry_id,
                "全球矿山铜（公司披露/运营口径）",
                "global",
                item["global_share"],
                "2025",
                item["global_rank"],
                json.dumps(ids, ensure_ascii=False),
                f"{item['name']}2025年公司披露铜产量",
                "公司正式披露＋USGS全球分母复算",
                (
                    f"份额＝{item['reported_production_kt']:.3f}千吨÷"
                    "USGS全球矿山铜产量23000千吨；用于比较运营规模，"
                    "不等同于归母权益份额。"
                ),
                ),
            )
        if item["china_share"] > 0:
            conn.execute(
                """
                INSERT INTO company_sub_market_share(
                  company_id,industry_id,sub_market,geo,share,share_as_of,rank,
                  source_ids,source_excerpt_ref,credibility,display_note
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    item["id"],
                    industry_id,
                    "中国境内矿山铜（运营/并表代理口径）",
                    "china",
                    item["china_share"],
                    "2025",
                    item["china_rank"],
                    json.dumps(ids, ensure_ascii=False),
                    f"{item['name']}2025年中国境内运营矿山铜产量",
                    "公司正式披露＋USGS中国分母复算",
                    (
                        f"境内份额＝{item['china_production_kt']:.3f}千吨÷"
                        "USGS中国矿山铜产量1800千吨；不计仅按权益披露且"
                        "由其他企业运营的矿山，避免公司运营份额重复。"
                    ),
                ),
            )
        if "attributable_share" in item:
            conn.execute(
                """
                INSERT INTO company_sub_market_share(
                  company_id,industry_id,sub_market,geo,share,share_as_of,rank,
                  source_ids,source_excerpt_ref,credibility,display_note
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    item["id"],
                    industry_id,
                    "全球矿山铜（权益口径）",
                    "global",
                    item["attributable_share"],
                    "2025",
                    None,
                    json.dumps(ids, ensure_ascii=False),
                    f"{item['name']}2025年权益矿产铜产量",
                    "公司正式披露＋USGS全球分母复算",
                    (
                        f"权益份额＝{item['attributable_production_kt']:.3f}千吨÷"
                        "USGS全球矿山铜产量23000千吨。"
                    ),
                ),
            )
        for source_id in ids:
            conn.execute(
                """
                INSERT OR IGNORE INTO source_entity(
                  source_id,entity_type,entity_id,coverage
                ) VALUES(?,?,?,?)
                """,
                (source_id, "company", str(item["id"]), "主要覆盖"),
            )


def remove_claim_ingest_placeholder_companies(
    conn: sqlite3.Connection, industry_id: int
) -> list[int]:
    """移除本轮竞争事实误触发的无证券身份占位公司。

    行业数据点仍保留，只把 ``company_id`` 置空。只有名称匹配、ticker 与
    market 为空、无画像、无其他行业归属，且公司引用仅来自本轮境内矿山
    指标时才允许删除，避免误伤任何既有公司身份。
    """
    removed: list[int] = []
    for name in ("江西铜业", "西部矿业", "中国黄金国际"):
        row = conn.execute(
            """
            SELECT c.id
              FROM company c
             WHERE c.name=? AND c.ticker IS NULL AND c.market IS NULL
               AND NOT EXISTS(
                 SELECT 1 FROM company_profile p WHERE p.company_id=c.id
               )
               AND NOT EXISTS(
                 SELECT 1 FROM company_industry ci
                  WHERE ci.company_id=c.id AND ci.industry_id<>?
               )
               AND NOT EXISTS(
                 SELECT 1 FROM industry_data_point dp
                  WHERE dp.company_id=c.id
                    AND NOT (
                      dp.industry_id=?
                      AND dp.metric LIKE ? || '中国境内矿山铜%'
                    )
               )
            """,
            (name, industry_id, industry_id, name),
        ).fetchone()
        if row is None:
            continue
        company_id = int(row["id"])
        conn.execute(
            """
            UPDATE industry_data_point
               SET company_id=NULL
             WHERE company_id=? AND industry_id=?
               AND metric LIKE ? || '中国境内矿山铜%'
            """,
            (company_id, industry_id, name),
        )
        conn.execute(
            "DELETE FROM company_industry WHERE company_id=? AND industry_id=?",
            (company_id, industry_id),
        )
        conn.execute("DELETE FROM company WHERE id=?", (company_id,))
        removed.append(company_id)
    return removed


def write_documents(
    industry_id: int, source_ids: dict[str, int]
) -> dict[str, dict[str, Any]]:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    documents = make_documents(industry_id, source_ids)
    result: dict[str, dict[str, Any]] = {}
    for name, text in documents.items():
        path = DOCS_DIR / name
        path.write_text(text.rstrip() + "\n", encoding="utf-8")
        result[name] = {
            "path": str(path.relative_to(ROOT)).replace("\\", "/"),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
            "citation_count": len(re.findall(r"\^src:\d+", text)),
            "has_chapter_summary": (
                "## 本章综述" in text
                if re.search(r"_Q[0-7]_", name)
                else True
            ),
        }
    dimension_manifest = [
        {"q": "Q0", "short": "历史发展", "full": "历史发展与周期"},
        {"q": "Q1", "short": "竞争格局", "full": "竞争格局"},
        {"q": "Q2", "short": "市场空间", "full": "市场空间与供需"},
        {"q": "Q3", "short": "公司壁垒", "full": "公司壁垒"},
        {"q": "Q4", "short": "行业特征", "full": "行业特征与盈利机制"},
        {"q": "Q5", "short": "资源政治", "full": "全球项目与资源政治"},
        {"q": "Q6", "short": "综述", "full": "综合判断"},
        {"q": "Q7", "short": "补充", "full": "方法、监控与资料边界"},
    ]
    manifest_path = DOCS_DIR / "铜_dimensions.json"
    manifest_path.write_text(
        json.dumps(dimension_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    result[manifest_path.name] = {
        "path": str(manifest_path.relative_to(ROOT)).replace("\\", "/"),
        "bytes": manifest_path.stat().st_size,
        "sha256": _sha256(manifest_path),
        "dimension_count": len(dimension_manifest),
    }
    return result


def audit(
    conn: sqlite3.Connection,
    source_ids: dict[str, int],
    documents: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    q_files = [name for name in documents if re.search(r"_Q[0-7]_", name)]
    missing_summaries = [
        name for name in q_files if not documents[name]["has_chapter_summary"]
    ]
    registered = {
        int(row["id"])
        for row in conn.execute(
            "SELECT id FROM source WHERE id IN (%s)"
            % ",".join("?" for _ in source_ids.values()),
            tuple(source_ids.values()),
        )
    }
    cited_ids: set[int] = set()
    for name in documents:
        if not name.endswith(".md"):
            continue
        text = (DOCS_DIR / name).read_text(encoding="utf-8")
        cited_ids.update(int(value) for value in re.findall(r"\^src:(\d+)", text))
    unknown_citations = sorted(cited_ids - registered)
    data_point_count = int(
        conn.execute(
            "SELECT COUNT(*) FROM industry_data_point WHERE industry_id=?",
            (INDUSTRY_ID,),
        ).fetchone()[0]
    )
    company_count = int(
        conn.execute(
            "SELECT COUNT(*) FROM company_industry WHERE industry_id=?",
            (INDUSTRY_ID,),
        ).fetchone()[0]
    )
    if missing_summaries or unknown_citations:
        raise RuntimeError(
            f"公开文档审计失败 missing_summaries={missing_summaries} "
            f"unknown_citations={unknown_citations}"
        )
    return {
        "industry_id": INDUSTRY_ID,
        "industry_name": INDUSTRY_NAME,
        "source_count": len(source_ids),
        "data_point_count": data_point_count,
        "company_count": company_count,
        "document_count": len(documents),
        "q_document_count": len(q_files),
        "all_q_have_front_summary": True,
        "unknown_citations": [],
        "documents": documents,
    }


def apply(*, db_path: Path = DB_PATH) -> dict[str, Any]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        row = conn.execute(
            "SELECT id,name FROM industry WHERE id=?", (INDUSTRY_ID,)
        ).fetchone()
        if not row or row["name"] != INDUSTRY_NAME:
            raise RuntimeError(
                f"铜行业身份不匹配 expected=({INDUSTRY_ID},{INDUSTRY_NAME}) "
                f"actual={dict(row) if row else None}"
            )
        conn.execute("BEGIN IMMEDIATE")
        source_ids = register_sources(conn, INDUSTRY_ID)
        upsert_company_profiles(conn, INDUSTRY_ID, source_ids)
        removed_placeholder_company_ids = remove_claim_ingest_placeholder_companies(
            conn, INDUSTRY_ID
        )
        conn.execute(
            """
            UPDATE industry
               SET status='深度跟踪',tier=1,last_updated=?
             WHERE id=?
            """,
            (AS_OF_DATE, INDUSTRY_ID),
        )
        documents = write_documents(INDUSTRY_ID, source_ids)
        result = audit(conn, source_ids, documents)
        result["removed_placeholder_company_ids"] = removed_placeholder_company_ids
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    audit_path = CACHE_DIR / "copper_apply_audit.json"
    audit_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    result["audit_path"] = str(audit_path.relative_to(ROOT)).replace("\\", "/")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    args = parser.parse_args(argv)
    print(json.dumps(apply(db_path=args.db.resolve()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
