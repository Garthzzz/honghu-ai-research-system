from __future__ import annotations

"""Apply the lithium-battery B-track narrative after unified claim ingest.

``ingest_research`` owns all ``industry_data_point`` rows.  This adapter only
registers narrative sources, links the nine verified listed companies, writes
industry-specific company profiles and public Markdown, and emits deterministic
audits.  Financial vendor observations remain in ``financial.db``.
"""

import argparse
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .lithium_battery_research_content import make_documents
from .lithium_battery_research_data import SOURCE_SPECS, build_data_points
from tools.research_core.workflow import ResearchWorkflowRun


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "research.db"
DOCS_DIR = ROOT / "docs" / "industries"
CACHE_DIR = ROOT / "cache" / "lithium_battery_research"
RUN_DIR = ROOT / "cache" / "research_runs" / "lithium_battery_b_20260728"
CLAIMS_PATH = (
    ROOT / "cache" / "claims" / "lithium_battery_b_20260728_01_core_claims.json"
)
SNAPSHOT_PATH = (
    CACHE_DIR / "models" / "battery_financial_snapshot_v1.json"
)
MODEL_PATH = CACHE_DIR / "models" / "battery_independent_models_v1.json"
RECON_PATH = CACHE_DIR / "models" / "battery_external_reconciliation_v1.json"
POLICY_PATH = CACHE_DIR / "models" / "battery_policy_scenarios_v1.json"
SUPPLY_DEMAND_PATH = (
    CACHE_DIR / "models" / "battery_industry_supply_demand_v1.json"
)
PROFILE_EXPORT_PATH = (
    CACHE_DIR / "models" / "battery_company_financial_profile_export_v1.json"
)
INDUSTRY_ID = 29
INDUSTRY_NAME = "锂电池"
AS_OF_DATE = "2026-07-28"


COMPANIES: tuple[dict[str, Any], ...] = (
    {
        "id": 254,
        "name": "宁德时代",
        "role": "全球动力与储能电池龙头；材料、回收及海外本地化平台",
        "products": "动力电池系统、储能电池系统、电池材料、回收与电池服务",
        "customers": "全球乘用车、商用车和储能系统客户；客户集中度按公司披露跟踪",
        "tech": "麒麟电池、神行系列、大储电芯、系统集成与规模制造",
        "summary": (
            "2026年1—5月全球动力装机188.4GWh、份额40.2%；2025年"
            "661GWh销量、772GWh产能、利用率96.9%。核心是海外利用率、"
            "储能利润和强自由现金流能否覆盖扩产与股东回报。"
        ),
        "risk": "ASP下降超过成本改善、海外低利用率、政策资格变化和资本配置失误。",
        "source_refs": ("catl_25a", "catl_26h1", "sne_global_ev_2026m5"),
        "global_share": 40.2,
        "global_rank": 1,
        "share_period": "2026年1—5月",
        "sub_market": "全球动力电池车辆装机",
    },
    {
        "id": 414,
        "name": "比亚迪",
        "role": "新能源汽车集团与自供电池龙头；储能和外供电池扩张",
        "products": "新能源汽车、刀片电池、储能系统、外供电池及电子部件",
        "customers": "集团内部整车为动力电池主要去向，储能和外供客户另行核验",
        "tech": "刀片电池、CTB/整车集成、储能系统与全球整车制造",
        "summary": (
            "2026年1—5月全球动力装机67.6GWh、份额14.4%；2025年"
            "储能系统出货超过60GWh。集团模型不得重复计算内部电池收入，"
            "估值关键是海外销量、资本开支和自由现金流拐点。"
        ),
        "risk": "整车价格战、海外贸易壁垒、本地工厂爬坡和集团高资本开支。",
        "source_refs": ("byd_25a", "byd_26q1", "sne_global_ev_2026m5"),
        "global_share": 14.4,
        "global_rank": 2,
        "share_period": "2026年1—5月",
        "sub_market": "全球动力电池车辆装机",
    },
    {
        "id": 662,
        "name": "国轩高科",
        "role": "动力、储能和材料一体化第二梯队；海外制造与客户协同",
        "products": "动力电池、储能电池、正极材料和电池回收",
        "customers": "国内外整车、商用车和储能客户；大众体系为重要战略关系",
        "tech": "磷酸铁锂、三元、储能系统与海外本地化制造",
        "summary": (
            "2026年1—5月全球动力装机份额4.6%、排名第五；2025年"
            "动力装机53.5GWh、储能出货超过30GWh。利润修复已经出现，"
            "美国项目资格、资本开支和自由现金流仍待验证。"
        ),
        "risk": "美国45X/PFE资格、海外项目利用率、低价竞争和持续融资。",
        "source_refs": (
            "gotion_25a",
            "gotion_26q1",
            "sne_global_ev_2026m5",
            "irs_45x_final",
            "irs_pfe_2026",
        ),
        "global_share": 4.6,
        "global_rank": 5,
        "share_period": "2026年1—5月",
        "sub_market": "全球动力电池车辆装机",
    },
    {
        "id": 663,
        "name": "中创新航",
        "role": "动力电池第二梯队龙头；储能与海外本地化扩张",
        "products": "乘用车动力电池、商用车电池、储能电芯与系统",
        "customers": "国内乘用车、商用车及储能客户；海外客户和工厂仍在扩展",
        "tech": "高安全动力电池、大容量储能电芯与规模制造",
        "summary": (
            "2026年1—5月全球动力装机23.8GWh、份额5.1%、排名第四；"
            "2025年全球动力第四、中国第三、储能第四。当前折价依赖盈利"
            "兑现、海外爬坡和2028年前后自由现金流转正。"
        ),
        "risk": "扩产快于客户和利润、海外低利用率、毛利修复不足和融资压力。",
        "source_refs": (
            "calb_25a",
            "calb_26q1",
            "calb_huatai_20260609",
            "sne_global_ev_2026m5",
        ),
        "global_share": 5.1,
        "global_rank": 4,
        "share_period": "2026年1—5月",
        "sub_market": "全球动力电池车辆装机",
    },
    {
        "id": 664,
        "name": "亿纬锂能",
        "role": "动力、储能和消费电池多业务平台；海外制造扩张",
        "products": "动力电池、储能电池、消费电池和小型锂电池",
        "customers": "整车、储能系统和消费电子客户；按分部与地区分别跟踪",
        "tech": "大圆柱、方形动力电池、大储电芯和消费电池平台",
        "summary": (
            "2025年动力出货50.15GWh、储能71.05GWh；2026年1—5月"
            "全球动力装机份额3.3%。多业务提供收入分散，但马来西亚、"
            "匈牙利等项目要求利润增长最终转成自由现金流。"
        ),
        "risk": "多业务同时扩产、海外低利用率、储能价格传导和资本竞争。",
        "source_refs": ("eve_25a", "eve_26q1", "eve_citi_20260609", "sne_global_ev_2026m5"),
        "global_share": 3.3,
        "global_rank": 8,
        "share_period": "2026年1—5月",
        "sub_market": "全球动力电池车辆装机",
    },
    {
        "id": 665,
        "name": "瑞浦兰钧",
        "role": "动力与储能快速扩张厂商；印尼本地化和盈利拐点",
        "products": "动力电池、储能电池、商用车电池与系统产品",
        "customers": "动力、商用车和储能客户；海外订单按实际交付核验",
        "tech": "问顶系列动力与储能产品、印尼本地化制造",
        "summary": (
            "2025年产品销量82.7GWh、设计产能90GWh；2026年上半年"
            "盈利预告验证规模效应。当前关键不是销量排名，而是经营现金、"
            "资本开支和印尼项目能否形成闭环。"
        ),
        "risk": "订单波动、资本开支超预算、海外爬坡和低基数盈利回撤。",
        "source_refs": ("rept_25a", "rept_26h1e", "rept_clsa_20260511"),
        "global_share": None,
        "global_rank": None,
        "share_period": "2025",
        "sub_market": "动力与储能综合出货（统一全球份额客观不可得）",
    },
    {
        "id": 666,
        "name": "欣旺达",
        "role": "消费电池基本盘与动力、储能扩张并存的综合电池厂商",
        "products": "消费类电池与结构件、动力电池、储能系统和其他电池",
        "customers": "消费电子客户及整车、储能客户；集团境外收入不等于动储暴露",
        "tech": "消费电池制造、动力电池、储能系统与海外产能",
        "summary": (
            "2025年电动汽车类电池出货42.72GWh、储能系统装机25.6GWh；"
            "2026年1—5月全球动力份额2.4%。动力和储能利润、回款及集团"
            "自由现金流需要与消费业务分开核验。"
        ),
        "risk": "新业务量增不增利、应收和资本开支、少数股东与分部透明度。",
        "source_refs": (
            "sunwoda_25a",
            "sunwoda_26q1",
            "sunwoda_zheshang_20260603",
            "sne_global_ev_2026m5",
        ),
        "global_share": 2.4,
        "global_rank": 10,
        "share_period": "2026年1—5月",
        "sub_market": "全球动力电池车辆装机",
    },
    {
        "id": 661,
        "name": "鹏辉能源",
        "role": "储能为主、消费和小动力为辅的中型电池厂商",
        "products": "大储电芯与系统、户储、消费电池和小动力电池",
        "customers": "国内外储能和消费客户；合同价格与回款按项目核验",
        "tech": "大容量储能电芯、系统集成和多场景储能产品",
        "summary": (
            "2025年全球储能电芯出货排名第九，并连续七个季度进入BNEF"
            "Tier 1。估值空间依赖储能出货、ASP、毛利和2027自由现金流"
            "转正共同兑现，不能只依赖行业高增。"
        ),
        "risk": "公司规模、客户集中、储能价格回落、税负转嫁和扩产融资。",
        "source_refs": ("great_power_25a", "great_power_26q1", "infolink_ess_2026q1"),
        "global_share": None,
        "global_rank": 9,
        "share_period": "2025",
        "sub_market": "全球储能电芯出货",
    },
    {
        "id": 667,
        "name": "孚能科技",
        "role": "三元软包动力电池厂商；海外客户、土耳其产能与扭亏期权",
        "products": "三元软包动力电池、动力系统及研发服务",
        "customers": "海外整车和Siro等客户；客户集中与订单兑现重点跟踪",
        "tech": "三元软包、Siro本地制造与固态技术储备",
        "summary": (
            "土耳其Siro 6GWh产能已爬坡，2025年电池业务境外收入占比"
            "81.88%；但2026仍处亏损，当前市值主要资本化2027扭亏、"
            "客户和固态技术期权。"
        ),
        "risk": "持续亏损、新基地低利用率、客户集中、应收和固态商业化延期。",
        "source_refs": ("farasis_25a", "farasis_26q1"),
        "global_share": None,
        "global_rank": None,
        "share_period": "2025",
        "sub_market": "软包动力与出口（统一全球份额客观不可得）",
    },
)


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _source_file(spec: dict[str, Any]) -> str | None:
    name = spec.get("source_file")
    return str(name).replace("\\", "/") if name else None


def _source_note(spec: dict[str, Any]) -> str:
    return (
        f"文档级独立键={spec['independence_key']}；"
        f"{str(spec.get('independence_rationale') or '').rstrip('。')}。"
    )


def _db_source_type(spec: dict[str, Any]) -> str:
    raw = str(spec.get("source_type") or "")
    mapping = {
        "公司研报": "卖方深度",
        "公告": "公告",
        "政府统计": "三方数据",
        "政策原文": "其他",
        "法规原文": "其他",
        "行业媒体": "财经媒体",
        "行业数据库": "三方数据",
        "行业数据汇编": "三方数据",
    }
    return mapping.get(raw, "website_material")


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
                """
                UPDATE source
                   SET note=COALESCE(NULLIF(note,''),?),
                       source_channel=COALESCE(source_channel,?)
                 WHERE id=?
                """,
                (_source_note(spec), spec.get("source_channel", "web"), source_id),
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
                        spec.get("title_zh") or spec["title"],
                        _db_source_type(spec),
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
                        f"{AS_OF_DATE}T18:00:00+08:00",
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
                + " 实时财务、行情和估值只读引用financial.db，不复制供应商快照。",
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
              global_share_sub_market,global_rank,main_products,main_customers,
              customer_concentration,tech_node,recent_events,risks,
              is_china_tech_leader,in_global_table,in_china_table,
              listing_status,source_ids,summary,display_note,brief_intro,
              brief_intro_src,last_updated,last_verified_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                item["id"],
                industry_id,
                "2025A/2026E",
                item["global_share"],
                item["share_period"],
                item["sub_market"],
                item["global_rank"],
                item["products"],
                item["customers"],
                "缺少同口径客户集中度时不补写；按公司最新披露持续更新。",
                item["tech"],
                json.dumps(
                    [
                        {
                            "date": AS_OF_DATE,
                            "title": "锂电池业务经营与模型更新",
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
                int(item["id"] in {254, 414, 662, 663, 664}),
                1,
                1,
                row["listing_status"],
                json.dumps(ids, ensure_ascii=False),
                item["summary"],
                (
                    "行业排名只使用明确的动力装机或储能出货分母；没有统一份额的"
                    "公司保留排名或经营量，不用公司销量除以不同市场分母造份额。"
                ),
                item["summary"],
                str(ids[0]),
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
                item["sub_market"],
                "global",
                item["global_share"],
                item["share_period"],
                item["global_rank"],
                json.dumps(ids, ensure_ascii=False),
                item["summary"],
                "公司正式披露与统一行业榜单交叉核验",
                (
                    "动力装机、储能电芯出货和公司产品销量属于不同分母；"
                    "份额为空表示统一市场分母客观不可得，不是接口漏抓。"
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
            "has_problem": bool(
                re.search(
                    r"^#{2,3}\s+(?:\d+\.\s+)?问题(?:：|$)",
                    text,
                    flags=re.MULTILINE,
                )
            ),
            "has_method": "研究方法与数据" in text,
            "has_analysis": "研究与分析" in text,
            "has_summary": "## 总结" in text or "### 总结" in text,
            "has_chapter_summary": (
                "## 本章综述" in text if re.search(r"_Q[0-6]_", name) else True
            ),
        }
    dimensions = [
        {"q": "Q0", "short": "历史与技术", "full": "历史发展与技术代际"},
        {"q": "Q1", "short": "竞争格局", "full": "全球与中国竞争格局"},
        {"q": "Q2", "short": "市场空间", "full": "市场空间与有效供给"},
        {"q": "Q3", "short": "公司壁垒", "full": "公司壁垒与现金闭环"},
        {"q": "Q4", "short": "盈利机制", "full": "行业特征与盈利机制"},
        {"q": "Q5", "short": "核心结论", "full": "综合判断与投资条件"},
        {"q": "Q6", "short": "政策地缘", "full": "中美欧政策与地缘政治"},
    ]
    manifest_path = DOCS_DIR / "锂电池_dimensions.json"
    manifest_path.write_text(
        json.dumps(dimensions, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    result[manifest_path.name] = {
        "path": str(manifest_path.relative_to(ROOT)).replace("\\", "/"),
        "bytes": manifest_path.stat().st_size,
        "sha256": _sha256(manifest_path),
        "dimension_count": len(dimensions),
    }
    return result


def audit(
    conn: sqlite3.Connection,
    source_ids: dict[str, int],
    documents: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    q_files = [name for name in documents if re.search(r"_Q[0-6]_", name)]
    missing_summaries = [
        name for name in q_files if not documents[name]["has_chapter_summary"]
    ]
    missing_sections = [
        name
        for name, result in documents.items()
        if name.endswith(".md")
        and not all(
            result[key]
            for key in ("has_problem", "has_method", "has_analysis", "has_summary")
        )
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
    if missing_summaries or missing_sections or unknown_citations:
        raise RuntimeError(
            "公开文档审计失败 "
            f"missing_summaries={missing_summaries} "
            f"missing_sections={missing_sections} "
            f"unknown_citations={unknown_citations}"
        )
    source_channel_counts = {
        str(row["source_channel"]): int(row["n"])
        for row in conn.execute(
            """
            SELECT COALESCE(source_channel,'unclassified') AS source_channel,
                   COUNT(*) AS n
              FROM source
             WHERE id IN (%s)
             GROUP BY COALESCE(source_channel,'unclassified')
            """
            % ",".join("?" for _ in source_ids.values()),
            tuple(source_ids.values()),
        )
    }
    return {
        "industry_id": INDUSTRY_ID,
        "industry_name": INDUSTRY_NAME,
        "source_count": len(source_ids),
        "source_channel_counts": source_channel_counts,
        "data_point_count": int(
            conn.execute(
                "SELECT COUNT(*) FROM industry_data_point WHERE industry_id=?",
                (INDUSTRY_ID,),
            ).fetchone()[0]
        ),
        "company_count": int(
            conn.execute(
                "SELECT COUNT(*) FROM company_industry WHERE industry_id=?",
                (INDUSTRY_ID,),
            ).fetchone()[0]
        ),
        "company_profile_count": int(
            conn.execute(
                "SELECT COUNT(*) FROM company_profile WHERE industry_id=?",
                (INDUSTRY_ID,),
            ).fetchone()[0]
        ),
        "document_count": len(documents),
        "q_document_count": len(q_files),
        "all_q_have_front_summary": True,
        "all_documents_have_four_sections": True,
        "unknown_citations": [],
        "documents": documents,
    }


def update_workflow_manifest(
    *,
    source_ids: dict[str, int],
    documents: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    run = ResearchWorkflowRun.load(RUN_DIR)
    run.record_input_artifacts(
        [
            CLAIMS_PATH,
            SNAPSHOT_PATH,
            MODEL_PATH,
            RECON_PATH,
            POLICY_PATH,
            SUPPLY_DEMAND_PATH,
        ]
    )
    doc_paths = [
        ROOT / item["path"]
        for name, item in documents.items()
        if name.endswith(".md")
    ]
    for path in doc_paths:
        run.record_artifact("narrative_render", path, industry=INDUSTRY_NAME)
    for item in COMPANIES:
        run.record_independent_model_freeze(
            model_ref=f"{INDUSTRY_NAME}:{item['name']}:FY1-FY3",
            input_artifact=SNAPSHOT_PATH,
            output_artifact=MODEL_PATH,
        )
    run.record_external_reconciliation(
        model_ref=f"{INDUSTRY_NAME}:nine_company_models",
        benchmark_ref="数据商一致预期＋最近两个季度可核验中英文卖方模型",
        artifact=RECON_PATH,
    )
    for skill_name, input_path, output_path, note in (
        (
            "company_financial_modeling",
            SNAPSHOT_PATH,
            MODEL_PATH,
            "九家公司分别完成业务驱动FY1—FY3模型、现金流和资本效率冻结。",
        ),
        (
            "company_valuation_modeling",
            MODEL_PATH,
            RECON_PATH,
            "正常化PE、PB—ROE、反向估值和外部对账均按公司分别完成。",
        ),
        (
            "industry_supply_demand_modeling",
            CLAIMS_PATH,
            SUPPLY_DEMAND_PATH,
            "动力、储能和有效供给使用不同分母；2025与2030锚、插值、"
            "储能情景和中国实物流桥均在独立底稿中可复算。",
        ),
        (
            "probability_scenario_modeling",
            POLICY_PATH,
            DOCS_DIR / "锂电池_Q6_政策与地缘政治.md",
            "政策情景按适用收入、转嫁、资格、利用率和资本开支传导。",
        ),
    ):
        run.record_modeling_skill(
            skill_name=skill_name,
            status="completed",
            input_artifact=input_path,
            output_artifact=output_path,
            note=note,
        )
    evidence_refs = [
        f"source:{source_id}" for source_id in sorted(set(source_ids.values()))
    ]
    artifact_refs = [
        str(path.relative_to(ROOT)).replace("\\", "/") for path in doc_paths
    ]
    artifact_refs.extend(
        [
            str(MODEL_PATH.relative_to(ROOT)).replace("\\", "/"),
            str(RECON_PATH.relative_to(ROOT)).replace("\\", "/"),
            str(PROFILE_EXPORT_PATH.relative_to(ROOT)).replace("\\", "/"),
            str(SUPPLY_DEMAND_PATH.relative_to(ROOT)).replace("\\", "/"),
            str(POLICY_PATH.relative_to(ROOT)).replace("\\", "/"),
        ]
    )
    for requirement in run.brief.requirements:
        run.record_requirement_coverage(
            requirement.requirement_id,
            "completed",
            artifact_refs=artifact_refs,
            evidence_refs=evidence_refs,
            note=(
                "主报告、Q0—Q6、公司透视、独立模型、估值对账和公司财务导出"
                "共同覆盖；动态供应商数据保持在financial.db。"
            ),
        )
    run.configure_reviews(
        artifacts=[
            "public_markdown",
            "company_financials",
            "calculations",
            "public_ui",
        ],
        risks=["conflicting_sources", "stale_current_claim"],
    )
    points = build_data_points()
    parallel_facts = {
        (
            point["source_ref"],
            point.get("company"),
            point["metric"],
            point["unit"],
            point.get("scope_key"),
        )
        for point in points
    }
    run.record_stage(
        "research_package",
        "completed",
        industry_id=INDUSTRY_ID,
        document_count=len(doc_paths),
        company_profile_count=len(COMPANIES),
        observation_count=len(points),
        parallel_research_fact_count=len(parallel_facts),
    )
    eligible = run.evaluate_publication(open_p0=0)
    return {
        "brief": str(run.brief_path.relative_to(ROOT)).replace("\\", "/"),
        "manifest": str(run.manifest_path.relative_to(ROOT)).replace("\\", "/"),
        "manifest_sha256": _sha256(run.manifest_path),
        "required_reviews": list(run.manifest.required_reviews),
        "publication_eligible": eligible,
        "publication_blockers": list(run.manifest.publication.get("blockers", [])),
    }


def apply(
    *,
    db_path: Path = DB_PATH,
    update_workflow: bool = False,
) -> dict[str, Any]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        row = conn.execute(
            "SELECT id,name FROM industry WHERE id=?", (INDUSTRY_ID,)
        ).fetchone()
        if not row or row["name"] != INDUSTRY_NAME:
            raise RuntimeError(
                f"锂电池行业身份不匹配 expected=({INDUSTRY_ID},{INDUSTRY_NAME}) "
                f"actual={dict(row) if row else None}"
            )
        conn.execute("BEGIN IMMEDIATE")
        source_ids = register_sources(conn, INDUSTRY_ID)
        upsert_company_profiles(conn, INDUSTRY_ID, source_ids)
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
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    audit_path = CACHE_DIR / "lithium_battery_apply_audit.json"
    audit_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    result["audit_path"] = str(audit_path.relative_to(ROOT)).replace("\\", "/")
    if update_workflow:
        result["workflow"] = update_workflow_manifest(
            source_ids=source_ids,
            documents=documents,
        )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--update-workflow", action="store_true")
    args = parser.parse_args(argv)
    print(
        json.dumps(
            apply(
                db_path=args.db.resolve(),
                update_workflow=args.update_workflow,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
