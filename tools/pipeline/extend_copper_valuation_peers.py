from __future__ import annotations

"""Provision the copper-only A/H peer set used by the valuation page.

This command changes company identity/profile data only.  It does not fetch
market or financial observations and never writes industry_data_point.
"""

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from tools.financial.constants import DB_PATH as DEFAULT_FINANCIAL_DB
from tools.pipeline.ensure_listed_company_profile import (
    DEFAULT_RESEARCH_DB,
    ensure_listed_company_profile,
)


INDUSTRY_ID = 26
AS_OF_DATE = "2026-07-28"

PEERS: tuple[dict[str, Any], ...] = (
    {
        "name": "中国有色矿业",
        "ticker": "1258.HK",
        "market": "港股",
        "listing_status": "hk",
        "category": "资源矿山",
        "role": "资源矿山 · 港股；赞比亚铜矿采选与冶炼平台",
        "products": "铜精矿、粗铜、阳极铜、阴极铜及硫酸",
        "tech": "赞比亚铜带矿山采选、湿法与火法冶炼的一体化运营",
        "summary": (
            "中国有色矿业是中国有色集团在海外的铜钴资源开发平台，核心资产位于"
            "赞比亚。公司同时包含矿山和冶炼环节，利润既受铜价与矿山产量影响，"
            "也受电力、冶炼加工和所在国税费约束。"
        ),
        "risk": "赞比亚电力、税费和外汇风险，矿冶产能利用率及单一区域集中度。",
        "source_url": "https://www.cnmcl.net/cn/about-us/company-profile/",
        "source_title": "中国有色矿业公司简介",
        "aliases": ("CNMC", "China Nonferrous Mining"),
    },
    {
        "name": "西部矿业",
        "ticker": "601168.SH",
        "market": "A股",
        "listing_status": "a_share",
        "category": "资源矿山",
        "role": "资源矿山 · A股；西部多金属矿山与冶炼平台",
        "products": "铜、铅、锌、铁等矿产品及有色金属冶炼产品",
        "tech": "高海拔矿山采选、大型多金属资源开发与冶炼协同",
        "summary": (
            "西部矿业拥有玉龙铜矿等资源资产，铜是重要盈利来源，但公司同时经营"
            "铅锌、铁矿和冶炼业务。比较时应把矿山铜利润与冶炼收入分开，重点观察"
            "玉龙产量、品位、扩建资本和资源税费。"
        ),
        "risk": "高海拔运营、铜价与品位波动、项目扩建资本开支和多金属周期。",
        "source_url": "https://www.westmining.com/",
        "source_title": "西部矿业官方网站",
        "aliases": ("Western Mining",),
    },
    {
        "name": "江西铜业",
        "ticker": "600362.SH",
        "market": "A股",
        "listing_status": "a_share",
        "category": "矿冶一体化",
        "role": "矿冶一体化 · A股；国内大型铜矿、冶炼与加工企业",
        "products": "阴极铜、铜精矿、铜杆线、贵金属及硫酸",
        "tech": "大型铜矿采选、闪速冶炼、电解精炼与铜加工一体化",
        "summary": (
            "江西铜业同时拥有自有铜矿、全球精矿采购、冶炼和铜加工业务。营业收入"
            "规模不能直接代表铜价弹性；自有矿权益量、冶炼加工费、副产品和营运"
            "资金共同决定利润与现金流。"
        ),
        "risk": "冶炼加工费低位、自有矿增量不足、库存和贸易占资、金属价格波动。",
        "source_url": "https://www.jxcc.com/",
        "source_title": "江西铜业集团官方网站",
        "aliases": ("Jiangxi Copper",),
    },
    {
        "name": "铜陵有色",
        "ticker": "000630.SZ",
        "market": "A股",
        "listing_status": "a_share",
        "category": "矿冶一体化",
        "role": "矿冶一体化 · A股；铜矿、冶炼与铜加工平台",
        "products": "阴极铜、铜精矿、铜材、黄金、白银及硫酸",
        "tech": "铜矿采选、闪速冶炼、电解精炼和铜加工协同",
        "summary": (
            "铜陵有色覆盖矿山、冶炼和加工，冶炼规模大于自有矿供给。公司收入随"
            "铜价变化显著，但利润更依赖自有矿贡献、加工费、副产品价格和营运资金。"
        ),
        "risk": "低加工费、原料采购与库存占资、自有矿兑现、汇率和副产品价格。",
        "source_url": "https://www.tnmg.com.cn/",
        "source_title": "铜陵有色金属集团官方网站",
        "aliases": ("Tongling Nonferrous",),
    },
    {
        "name": "云南铜业",
        "ticker": "000878.SZ",
        "market": "A股",
        "listing_status": "a_share",
        "category": "矿冶一体化",
        "role": "矿冶一体化 · A股；矿山、冶炼与精炼铜平台",
        "products": "阴极铜、铜精矿、贵金属、硫酸及铜加工产品",
        "tech": "铜矿采选、火法冶炼、电解精炼和伴生资源综合回收",
        "summary": (
            "云南铜业以冶炼和阴极铜为主体，并拥有部分矿山资源。估值对比应区分"
            "铜价带来的收入放大与加工费、自有矿和副产品带来的实际利润变化。"
        ),
        "risk": "精矿加工费、原料与库存占资、冶炼检修、环保和资源自给率。",
        "source_url": "https://www.yunnan-copper.com/",
        "source_title": "云南铜业官方网站",
        "aliases": ("Yunnan Copper",),
    },
    {
        "name": "海亮股份",
        "ticker": "002203.SZ",
        "market": "A股",
        "listing_status": "a_share",
        "category": "铜加工材料",
        "role": "铜加工材料 · A股；全球铜管、铜棒与导体材料制造商",
        "products": "铜管、铜棒、铜排、铜箔及其他铜加工材",
        "tech": "高效连续铸轧、精密铜管加工与全球制造交付",
        "summary": (
            "海亮股份处在铜产业链加工环节，通常以加工费和周转效率获利，而不是"
            "直接赚取铜价上涨。比较时重点看销量、加工费、存货套保、营运资金和"
            "资本开支，不把高收入误当高铜价弹性。"
        ),
        "risk": "加工费竞争、库存和套保错配、海外运营、营运资金与扩产回报。",
        "source_url": "https://www.hailiangstock.com/about.html",
        "source_title": "海亮股份公司简介",
        "aliases": ("Hailiang",),
    },
    {
        "name": "博威合金",
        "ticker": "601137.SH",
        "market": "A股",
        "listing_status": "a_share",
        "category": "铜加工材料",
        "role": "铜加工材料 · A股；高性能铜合金材料平台",
        "products": "高性能铜合金板带、线材、棒材及精密材料",
        "tech": "合金成分设计、熔铸、精密轧制与高端连接器材料开发",
        "summary": (
            "博威合金的铜相关价值主要来自高性能合金配方、客户认证和加工附加值，"
            "并非简单跟随铜价。公司还有新能源业务，横向比较需要把材料盈利和"
            "非铜业务分开。"
        ),
        "risk": "高端材料认证和需求波动、原料传导滞后、新能源业务扰动与扩产回报。",
        "source_url": "https://www.bowayalloy.com/",
        "source_title": "博威合金官方网站",
        "aliases": ("Boway Alloy",),
    },
    {
        "name": "金田股份",
        "ticker": "601609.SH",
        "market": "A股",
        "listing_status": "a_share",
        "category": "铜加工材料",
        "role": "铜加工材料 · A股；规模化铜及铜合金材料制造平台",
        "products": "铜棒、铜管、铜线、铜排、铜带及高性能铜合金材料",
        "tech": "再生铜利用、熔铸、连续加工、精密铜材与高导电高强铜合金制造",
        "summary": (
            "金田股份是规模化铜及铜合金材料制造企业，铜加工总量大、产品覆盖面广，"
            "并延伸至稀土永磁材料。估值时应重点观察加工费、产品结构、存货套保、"
            "营运资金和资本开支，不能把铜价上涨带来的收入增长直接当作利润增长。"
        ),
        "risk": "加工费竞争、原料与存货价格错配、营运资金占用、扩产回报和非铜业务波动。",
        "source_url": "https://www.jtgroup.com.cn/about",
        "source_title": "宁波金田铜业官方网站公司简介",
        "aliases": ("Jintian Copper", "Ningbo Jintian Copper"),
    },
)


def _source_id(conn: sqlite3.Connection, peer: dict[str, Any]) -> int:
    row = conn.execute(
        "SELECT id FROM source WHERE source_url=? OR url=? ORDER BY id LIMIT 1",
        (peer["source_url"], peer["source_url"]),
    ).fetchone()
    if row:
        return int(row["id"])
    return int(
        conn.execute(
            """
            INSERT INTO source(
              title,source_type,publisher,publish_date,quality_tier,
              is_forward_looking,url,note,value_layer,source_url,
              source_subtype,fetch_timestamp,fetch_method,domain,language,
              is_primary_source,source_credibility,source_channel
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                peer["source_title"],
                "website_material",
                peer["name"],
                None,
                1,
                0,
                peer["source_url"],
                "仅用于上市主体、证券代码和业务边界核验。",
                "信息流",
                peer["source_url"],
                "official_web",
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "web_fetch",
                urlparse(peer["source_url"]).netloc,
                "zh",
                1,
                "official_primary",
                "web",
            ),
        ).lastrowid
    )


def _upsert_profile(
    conn: sqlite3.Connection,
    *,
    company_id: int,
    source_id: int,
    peer: dict[str, Any],
) -> None:
    relation_note = (
        f"{peer['category']}估值组。结构化财务与市场数据只读引用financial.db；"
        "本画像只记录业务边界和产业链位置。"
    )
    conn.execute(
        """
        INSERT INTO company_industry(company_id,industry_id,role,note)
        VALUES(?,?,?,?)
        ON CONFLICT(company_id,industry_id) DO UPDATE SET
          role=excluded.role,note=excluded.note
        """,
        (company_id, INDUSTRY_ID, peer["role"], relation_note),
    )
    conn.execute(
        """
        UPDATE company
           SET brief_intro=?,
               brief_intro_src=?
         WHERE id=?
        """,
        (
            peer["summary"],
            f"{peer['source_title']}（{AS_OF_DATE}核验）",
            company_id,
        ),
    )
    event = json.dumps(
        [
            {
                "date": AS_OF_DATE,
                "title": "纳入铜产业链估值同行",
                "detail": peer["summary"],
                "source_ids": [source_id],
                "is_major": False,
            }
        ],
        ensure_ascii=False,
    )
    risks = json.dumps(
        [{"label": "核心风险", "text": peer["risk"], "source_id": source_id}],
        ensure_ascii=False,
    )
    conn.execute(
        """
        INSERT INTO company_profile(
          company_id,industry_id,period,main_products,main_customers,
          customer_concentration,tech_node,recent_events,risks,
          is_china_tech_leader,in_global_table,in_china_table,listing_status,
          source_ids,summary,display_note,brief_intro,brief_intro_src,
          last_updated,last_verified_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(company_id,industry_id,period) DO UPDATE SET
          main_products=excluded.main_products,
          main_customers=excluded.main_customers,
          customer_concentration=excluded.customer_concentration,
          tech_node=excluded.tech_node,
          recent_events=excluded.recent_events,
          risks=excluded.risks,
          listing_status=excluded.listing_status,
          source_ids=excluded.source_ids,
          summary=excluded.summary,
          display_note=excluded.display_note,
          brief_intro=excluded.brief_intro,
          brief_intro_src=excluded.brief_intro_src,
          last_updated=excluded.last_updated,
          last_verified_at=excluded.last_verified_at
        """,
        (
            company_id,
            INDUSTRY_ID,
            "2026Q3",
            peer["products"],
            "公开客户结构按公司披露更新；未披露客户不补写",
            None,
            peer["tech"],
            event,
            risks,
            0,
            0,
            0,
            peer["listing_status"],
            json.dumps([source_id]),
            peer["summary"],
            relation_note,
            peer["summary"],
            str(source_id),
            AS_OF_DATE,
            AS_OF_DATE,
        ),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO source_entity(source_id,entity_type,entity_id,coverage)
        VALUES(?,?,?,?)
        """,
        (source_id, "company", str(company_id), "身份与业务边界"),
    )


def apply(
    *,
    research_db: Path,
    financial_db: Path,
    confirm_live: bool,
) -> dict[str, Any]:
    results = []
    for peer in PEERS:
        result = ensure_listed_company_profile(
            canonical_name=peer["name"],
            ticker=peer["ticker"],
            market=peer["market"],
            listing_status=peer["listing_status"],
            verification_source_ref=peer["source_url"],
            aliases=peer["aliases"],
            research_db_path=research_db,
            financial_db_path=financial_db,
            confirm_live=confirm_live,
        )
        results.append({**result, "category": peer["category"], "ticker": peer["ticker"]})

    conn = sqlite3.connect(research_db)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("BEGIN IMMEDIATE")
        for peer, result in zip(PEERS, results, strict=True):
            source_id = _source_id(conn, peer)
            _upsert_profile(
                conn,
                company_id=int(result["company_id"]),
                source_id=source_id,
                peer=peer,
            )
        foreign_key_issues = conn.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_issues:
            raise RuntimeError(f"research.db foreign_key_check失败: {foreign_key_issues}")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {
        "industry_id": INDUSTRY_ID,
        "peer_count": len(results),
        "peers": results,
        "research_db": str(research_db),
        "financial_db": str(financial_db),
    }


def audit(research_db: Path, financial_db: Path) -> dict[str, Any]:
    conn = sqlite3.connect(research_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT c.id,c.name,c.ticker,c.market,ci.role,
                       cp.summary,cp.main_products
                  FROM company c
                  JOIN company_industry ci
                    ON ci.company_id=c.id AND ci.industry_id=?
                  LEFT JOIN company_profile cp
                    ON cp.company_id=c.id AND cp.industry_id=ci.industry_id
                 WHERE upper(c.ticker) IN (%s)
                 ORDER BY c.ticker
                """
                % ",".join("?" for _ in PEERS),
                (INDUSTRY_ID, *(peer["ticker"] for peer in PEERS)),
            )
        ]
    finally:
        conn.close()
    fin = sqlite3.connect(financial_db)
    try:
        mapped = int(
            fin.execute(
                """
                SELECT COUNT(DISTINCT l.research_company_id)
                  FROM financial_security_company_link l
                 WHERE l.research_company_id IN (%s)
                """
                % ",".join("?" for _ in rows),
                tuple(row["id"] for row in rows),
            ).fetchone()[0]
        ) if rows else 0
    finally:
        fin.close()
    return {
        "expected": len(PEERS),
        "research_rows": len(rows),
        "financial_mappings": mapped,
        "complete_profiles": sum(
            1 for row in rows if row["summary"] and row["main_products"] and row["role"]
        ),
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--research-db", type=Path, default=DEFAULT_RESEARCH_DB)
    parser.add_argument("--financial-db", type=Path, default=DEFAULT_FINANCIAL_DB)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-live", action="store_true")
    args = parser.parse_args(argv)
    research_db = args.research_db.resolve()
    financial_db = args.financial_db.resolve()
    if args.apply:
        result = apply(
            research_db=research_db,
            financial_db=financial_db,
            confirm_live=args.confirm_live,
        )
        result["audit"] = audit(research_db, financial_db)
    else:
        result = {
            "dry_run": True,
            "industry_id": INDUSTRY_ID,
            "research_db": str(research_db),
            "financial_db": str(financial_db),
            "peers": [
                {
                    "name": peer["name"],
                    "ticker": peer["ticker"],
                    "market": peer["market"],
                    "category": peer["category"],
                    "identity_source": peer["source_url"],
                }
                for peer in PEERS
            ],
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
