from __future__ import annotations

"""Apply the two B-track lithium narrative libraries after unified claims ingest.

The adapter never inserts ``industry_data_point`` and never copies supplier
financial observations into research.db.  It links canonical companies,
writes industry-specific qualitative profiles, renders the public Markdown
package and binds the frozen model artifacts into each execution manifest.
"""

import argparse
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from tools.research_core.workflow import ResearchWorkflowRun

from .lithium_research_content import make_documents
from .lithium_research_data import COMPANY_FILES, SOURCE_SPECS


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "research.db"
DOCS_DIR = ROOT / "docs" / "industries"
CACHE_DIR = ROOT / "cache" / "lithium_research"
MODEL_PATH = CACHE_DIR / "models" / "lithium_company_independent_models_v1.json"
RECON_PATH = CACHE_DIR / "models" / "lithium_external_reconciliation_v1.json"
LITHIUM_SD_PATH = CACHE_DIR / "models" / "lithium_supply_demand_model_v1.json"
CARBONATE_SD_PATH = CACHE_DIR / "models" / "carbonate_supply_demand_model_v1.json"
AS_OF_DATE = "2026-07-27"
RUNS = {"锂": "lithium_b_20260727", "碳酸锂": "lithium_carbonate_b_20260727"}


PROFILE_META: dict[str, dict[str, str]] = {
    "赣锋锂业": {
        "role": "全球资源与锂盐一体化；多资源国、多产品和电池回收布局",
        "products": "锂精矿、碳酸锂、氢氧化锂、氯化锂及电池材料与回收",
        "tech": "硬岩矿、盐湖、锂盐转化和回收多工艺组合",
        "risk": "海外多项目爬坡、权益与汇回、资本开支以及锂价下行。",
    },
    "融捷股份": {
        "role": "四川硬岩矿资源弹性；采选为主、锂盐权益补充",
        "products": "锂精矿、少量锂盐及相关业务",
        "tech": "甲基卡硬岩锂矿采选",
        "risk": "采选衔接、品位、关联交易、扩产审批和单项目波动。",
    },
    "盛新锂能": {
        "role": "非洲与四川资源结合的锂盐一体化企业",
        "products": "锂精矿、碳酸锂、氢氧化锂和锂金属",
        "tech": "硬岩矿采选与锂盐转换",
        "risk": "非洲政策、木绒项目兑现、外购矿价差与资本开支。",
    },
    "盐湖股份": {
        "role": "钾肥现金流与察尔汗盐湖提锂组合",
        "products": "氯化钾、碳酸锂",
        "tech": "盐湖卤水提锂与钾锂协同",
        "risk": "新增装置爬坡、产品质量、季节与钾锂价格共同波动。",
    },
    "大中矿业": {
        "role": "铁矿现金流基础上的锂项目期权",
        "products": "铁精粉、球团及规划碳酸锂",
        "tech": "铁矿采选与硬岩锂矿开发、锂盐转换",
        "risk": "鸡脚山和加达项目投产时间、品位、融资及锂价。",
    },
    "雅化集团": {
        "role": "锂盐加工、非洲/四川资源与民爆双主业",
        "products": "氢氧化锂、碳酸锂、锂精矿和民爆产品",
        "tech": "锂盐转换、硬岩矿采选和客户认证",
        "risk": "外购矿价差、Kamativi与李家沟供给、客户与库存。",
    },
    "天华新能": {
        "role": "高镍用氢氧化锂为主、碳酸锂与非洲资源补充",
        "products": "氢氧化锂、碳酸锂及防静电超净产品",
        "tech": "锂盐精制、客户认证和海外资源协同",
        "risk": "产品结构、Ogapa爬坡、原料价格与客户需求。",
    },
    "天齐锂业": {
        "role": "Greenbushes低成本资源与全球锂化学品权益平台",
        "products": "锂精矿、碳酸锂、氢氧化锂及SQM权益收益",
        "tech": "高品位硬岩矿采选与锂化学品转换",
        "risk": "少数股东、海外税费、资本结构、SQM收益与锂价。",
    },
    "永杉锂业": {
        "role": "以外购原料和加工价差为主的锂盐企业",
        "products": "碳酸锂、氢氧化锂",
        "tech": "锂盐加工、产线切换与库存管理",
        "risk": "原料—产品价差、库存、利用率和扩产兑现。",
    },
    "中矿资源": {
        "role": "Bikita资源自给与国内锂盐转换一体化",
        "products": "锂精矿、碳酸锂、氢氧化锂及铯铷业务",
        "tech": "多品位硬岩矿采选、锂盐转换和稀有金属加工",
        "risk": "津巴布韦本地加工政策、产量成本、运输和资本开支。",
    },
    "藏格矿业": {
        "role": "钾肥现金流、青海盐湖提锂与海外项目期权",
        "products": "氯化钾、碳酸锂",
        "tech": "盐湖提锂与钾锂联产",
        "risk": "小体量锂产量、Mamico间接权益、海外项目与钾肥周期。",
    },
    "西藏城投": {
        "role": "盐湖资源项目期权与存量地产业务组合",
        "products": "规划碳酸锂、房地产与相关业务",
        "tech": "盐湖提锂项目开发",
        "risk": "规划到稳定产量的时间、融资、权益法与地产现金流。",
    },
    "永兴材料": {
        "role": "低成本锂云母与特钢双主业",
        "products": "碳酸锂、锂云母精矿和不锈钢棒线材",
        "tech": "锂云母采选冶、渣处理和特钢制造",
        "risk": "矿山与冶炼稳定性、环保尾渣、品位、锂价和特钢周期。",
    },
}


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _source_file(spec: dict[str, Any]) -> str | None:
    value = spec.get("source_file")
    return f"papers/锂/{value}" if value else None


def resolve_source_ids(
    conn: sqlite3.Connection,
    industry_ids: dict[str, int],
) -> dict[str, int]:
    result: dict[str, int] = {}
    for spec in SOURCE_SPECS:
        file_path = _source_file(spec)
        url = spec.get("source_url")
        row = None
        if file_path:
            row = conn.execute(
                "SELECT id FROM source WHERE file_path=?", (file_path,)
            ).fetchone()
        if row is None and url:
            row = conn.execute(
                "SELECT id FROM source WHERE source_url=? OR url=?", (url, url)
            ).fetchone()
        if row is None:
            raise RuntimeError(f"统一claims入库后仍找不到来源: {spec['source_ref']}")
        source_id = int(row["id"])
        result[str(spec["source_ref"])] = source_id
        for industry_id in industry_ids.values():
            conn.execute(
                """
                INSERT OR IGNORE INTO source_entity(
                  source_id,entity_type,entity_id,coverage
                ) VALUES(?,?,?,?)
                """,
                (source_id, "industry", str(industry_id), "主要覆盖"),
            )
    return result


def upsert_company_profiles(
    conn: sqlite3.Connection,
    *,
    industry_ids: dict[str, int],
    source_ids: dict[str, int],
    model: dict[str, Any],
) -> None:
    for company_model in model["companies"]:
        name = company_model["company"]
        company_id = int(company_model["research_company_id"])
        ticker = company_model["ticker"]
        identity = conn.execute(
            "SELECT id,name,ticker,market,listing_status FROM company WHERE id=?",
            (company_id,),
        ).fetchone()
        if not identity or identity["name"] != name or identity["ticker"] != ticker:
            raise RuntimeError(
                f"公司身份不匹配 id={company_id} expected=({name},{ticker}) "
                f"actual={dict(identity) if identity else None}"
            )
        meta = PROFILE_META[name]
        annual_ref = f"ar_{ticker.replace('.', '_')}_2025"
        annual_source_id = source_ids[annual_ref]
        evidence = company_model["project_and_operating_evidence"]
        limitations = company_model["limitations"]
        evidence_text = "；".join(
            str(item).rstrip("。；; ") for item in evidence
        ) + "。"
        limitation_text = "；".join(
            str(item).rstrip("。；; ") for item in limitations
        ) + "。"
        for industry_name, industry_id in industry_ids.items():
            role = (
                meta["role"]
                if industry_name == "锂"
                else meta["role"] + "；碳酸锂价格与资源/加工价差传导主体"
            )
            summary = (
                f"{company_model['model_type']}。"
                + evidence_text
                + " 财务、行情与估值采用截至研究日的结构化数据和冻结模型。"
            )
            conn.execute(
                """
                INSERT INTO company_industry(company_id,industry_id,role,note)
                VALUES(?,?,?,?)
                ON CONFLICT(company_id,industry_id) DO UPDATE SET
                  role=excluded.role,note=excluded.note
                """,
                (company_id, industry_id, role, summary),
            )
            conn.execute(
                "DELETE FROM company_profile WHERE company_id=? AND industry_id=?",
                (company_id, industry_id),
            )
            events = [
                {
                    "date": AS_OF_DATE,
                    "title": "2025实际与2026—2028项目验证",
                    "detail": item,
                    "source_ids": [annual_source_id],
                    "is_major": True,
                }
                for item in evidence
            ]
            risks = [
                {
                    "label": "业务与项目风险",
                    "text": meta["risk"],
                    "source_id": annual_source_id,
                },
                {
                    "label": "模型边界",
                    "text": limitation_text,
                    "source_id": annual_source_id,
                },
            ]
            conn.execute(
                """
                INSERT INTO company_profile(
                  company_id,industry_id,period,
                  main_products,main_customers,customer_concentration,tech_node,
                  recent_events,risks,is_china_tech_leader,in_global_table,
                  in_china_table,listing_status,source_ids,summary,display_note,
                  brief_intro,brief_intro_src,last_updated,last_verified_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    company_id,
                    industry_id,
                    "2025A/2026—2028E",
                    meta["products"],
                    "电池材料、正极、电芯、贸易与工业客户；未公开客户不补写",
                    None,
                    meta["tech"],
                    json.dumps(events, ensure_ascii=False),
                    json.dumps(risks, ensure_ascii=False),
                    1,
                    1,
                    1,
                    identity["listing_status"],
                    json.dumps([annual_source_id], ensure_ascii=False),
                    summary,
                    (
                        "行业画像呈现项目和经营事实；动态财务、市场数据、一致预期、"
                        "独立模型和市场隐含结果按各自时点分层更新。"
                    ),
                    f"{role}。{evidence[0]}",
                    annual_source_id,
                    AS_OF_DATE,
                    AS_OF_DATE,
                ),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO source_entity(
                  source_id,entity_type,entity_id,coverage
                ) VALUES(?,?,?,?)
                """,
                (annual_source_id, "company", str(company_id), "主要覆盖"),
            )


def upsert_relations(
    conn: sqlite3.Connection,
    industry_ids: dict[str, int],
    source_ids: dict[str, int],
) -> None:
    conn.execute(
        """
        INSERT INTO industry_relation(
          upstream_id,downstream_id,relation_type,cost_share,demand_share,
          bargaining_power,source_id,note
        ) VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(upstream_id,downstream_id,relation_type) DO UPDATE SET
          source_id=excluded.source_id,note=excluded.note
        """,
        (
            industry_ids["锂"],
            industry_ids["碳酸锂"],
            "衍生",
            None,
            None,
            "balanced",
            source_ids["usgs_mcs_2026"],
            (
                "全球锂资源折合LCE是上游资源口径，碳酸锂是产品口径；"
                "需要经过精矿/卤水、收率、产品结构与贸易转换，不能直接等同。"
            ),
        ),
    )


def write_documents(
    industry_ids: dict[str, int],
    source_ids: dict[str, int],
) -> dict[str, dict[str, Any]]:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    result: dict[str, dict[str, Any]] = {}
    dimensions = [
        {"q": "Q0", "short": "历史发展", "full": "历史发展与周期"},
        {"q": "Q1", "short": "竞争格局", "full": "竞争格局"},
        {"q": "Q2", "short": "市场空间", "full": "市场空间与供需"},
        {"q": "Q3", "short": "公司壁垒", "full": "公司壁垒"},
        {"q": "Q4", "short": "行业特征", "full": "行业经济性与估值"},
        {"q": "Q5", "short": "资源政治", "full": "全球项目、政策与贸易"},
        {"q": "Q6", "short": "综述", "full": "综合判断"},
        {"q": "Q7", "short": "补充", "full": "方法、监控与资料边界"},
    ]
    for industry, industry_id in industry_ids.items():
        docs = make_documents(industry, industry_id, source_ids)
        for name, text in docs.items():
            path = DOCS_DIR / name
            path.write_text(text.rstrip() + "\n", encoding="utf-8")
            result[name] = {
                "path": path.relative_to(ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
                "citation_count": len(re.findall(r"\^src:\d+", text)),
                "has_chapter_summary": (
                    "## 本章综述" in text if re.search(r"_Q[0-7]_", name) else True
                ),
            }
        manifest_path = DOCS_DIR / f"{industry}_dimensions.json"
        manifest_path.write_text(
            json.dumps(dimensions, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        result[manifest_path.name] = {
            "path": manifest_path.relative_to(ROOT).as_posix(),
            "bytes": manifest_path.stat().st_size,
            "sha256": _sha256(manifest_path),
            "dimension_count": len(dimensions),
        }
    return result


def audit(
    conn: sqlite3.Connection,
    *,
    industry_ids: dict[str, int],
    source_ids: dict[str, int],
    documents: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    registered = {
        int(row[0])
        for row in conn.execute(
            "SELECT id FROM source WHERE id IN (%s)"
            % ",".join("?" for _ in source_ids.values()),
            tuple(source_ids.values()),
        )
    }
    per_industry: dict[str, Any] = {}
    for industry, industry_id in industry_ids.items():
        q_files = [
            name for name in documents if re.match(fr"^{re.escape(industry)}_Q[0-7]_", name)
        ]
        missing_summaries = [
            name for name in q_files if not documents[name]["has_chapter_summary"]
        ]
        md_files = [
            name
            for name in documents
            if name.endswith(".md")
            and (name == f"{industry}.md" or name.startswith(f"{industry}_"))
        ]
        cited: set[int] = set()
        forbidden_hits: list[dict[str, str]] = []
        short_documents: list[dict[str, Any]] = []
        for name in md_files:
            text = (DOCS_DIR / name).read_text(encoding="utf-8")
            cited.update(int(value) for value in re.findall(r"\^src:(\d+)", text))
            for token in (
                "canonical",
                "intake",
                "字段完成度",
                "输出覆盖卡",
                "参数 owner",
                "D0/D1/D2",
                "low/mode/high",
            ):
                if token in text:
                    forbidden_hits.append({"file": name, "token": token})
            minimum = 3500 if name == f"{industry}.md" else 1800
            if len(text) < minimum:
                short_documents.append(
                    {"file": name, "chars": len(text), "minimum": minimum}
                )
        unknown_citations = sorted(cited - registered)
        counts = conn.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM industry_data_point WHERE industry_id=?),
              (SELECT COUNT(*) FROM company_profile WHERE industry_id=?),
              (SELECT COUNT(*) FROM company_industry WHERE industry_id=?)
            """,
            (industry_id, industry_id, industry_id),
        ).fetchone()
        if (
            missing_summaries
            or unknown_citations
            or forbidden_hits
            or short_documents
            or int(counts[0]) < 100
            or int(counts[1]) != 13
            or int(counts[2]) != 13
        ):
            raise RuntimeError(
                f"{industry}公开产物审计失败: missing_summaries={missing_summaries}, "
                f"unknown_citations={unknown_citations}, forbidden={forbidden_hits}, "
                f"short={short_documents}, counts={tuple(counts)}"
            )
        per_industry[industry] = {
            "industry_id": industry_id,
            "data_point_count": int(counts[0]),
            "company_profile_count": int(counts[1]),
            "company_link_count": int(counts[2]),
            "document_count": len(md_files),
            "q_document_count": len(q_files),
            "all_q_have_front_summary": True,
            "unknown_citations": [],
            "forbidden_public_terms": [],
        }
    return {"industries": per_industry, "documents": documents}


def update_workflow_manifests(
    industry_ids: dict[str, int],
    documents: dict[str, dict[str, Any]],
    source_ids: dict[str, int],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for industry, run_key in RUNS.items():
        run = ResearchWorkflowRun.load(ROOT / "cache" / "research_runs" / run_key)
        doc_paths = [
            ROOT / item["path"]
            for name, item in documents.items()
            if name.endswith(".md")
            and (name == f"{industry}.md" or name.startswith(f"{industry}_"))
        ]
        run.record_input_artifacts(
            [MODEL_PATH, RECON_PATH, LITHIUM_SD_PATH, CARBONATE_SD_PATH]
        )
        for path in doc_paths:
            run.record_artifact("narrative_render", path, industry=industry)
        for company in _load(MODEL_PATH)["companies"]:
            run.record_independent_model_freeze(
                model_ref=f"{industry}:{company['ticker']}:FY1-FY3",
                input_artifact=ROOT / company["freeze"]["input_path"],
                output_artifact=ROOT / company["freeze"]["output_path"],
            )
        run.record_external_reconciliation(
            model_ref=f"{industry}:13_company_models",
            benchmark_ref="Wind一致预期＋Tushare最近两个季度逐机构预测",
            artifact=RECON_PATH,
        )
        for skill_name, output in (
            ("company_financial_modeling", MODEL_PATH),
            ("company_valuation_modeling", RECON_PATH),
            (
                "industry_supply_demand_modeling",
                LITHIUM_SD_PATH if industry == "锂" else CARBONATE_SD_PATH,
            ),
            (
                "probability_scenario_modeling",
                LITHIUM_SD_PATH if industry == "锂" else CARBONATE_SD_PATH,
            ),
        ):
            run.record_modeling_skill(
                skill_name=skill_name,
                status="completed",
                input_artifact=MODEL_PATH,
                output_artifact=output,
                note="按路由完成冻结模型、情景、估值门禁与外部对账。",
            )
        evidence_refs = [
            f"source:{value}" for value in sorted(set(source_ids.values()))
        ]
        for requirement in run.brief.requirements:
            run.record_requirement_coverage(
                requirement.requirement_id,
                "completed",
                artifact_refs=[str(path.relative_to(ROOT)) for path in doc_paths],
                evidence_refs=evidence_refs,
                note="正文、结构化数据、公司页和冻结模型已共同覆盖；动态财务只读引用financial.db。",
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
        run.record_stage(
            "research_package",
            "completed",
            industry_id=industry_ids[industry],
            document_count=len(doc_paths),
            company_profile_count=13,
        )
        result[industry] = {
            "brief": str(run.brief_path.relative_to(ROOT)),
            "manifest": str(run.manifest_path.relative_to(ROOT)),
            "manifest_sha256": _sha256(run.manifest_path),
            "required_reviews": list(run.manifest.required_reviews),
        }
    return result


def apply(
    *,
    db_path: Path = DB_PATH,
    update_workflow: bool = False,
) -> dict[str, Any]:
    model = _load(MODEL_PATH)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        industry_ids: dict[str, int] = {}
        for industry in RUNS:
            row = conn.execute(
                "SELECT id,name FROM industry WHERE name=?", (industry,)
            ).fetchone()
            if not row:
                raise RuntimeError(f"行业不存在，请先运行prepare与统一ingest: {industry}")
            industry_ids[industry] = int(row["id"])
        conn.execute("BEGIN IMMEDIATE")
        source_ids = resolve_source_ids(conn, industry_ids)
        upsert_company_profiles(
            conn,
            industry_ids=industry_ids,
            source_ids=source_ids,
            model=model,
        )
        upsert_relations(conn, industry_ids, source_ids)
        conn.executemany(
            """
            UPDATE industry
               SET status='深度跟踪',tier=1,last_updated=?
             WHERE id=?
            """,
            [(AS_OF_DATE, value) for value in industry_ids.values()],
        )
        documents = write_documents(industry_ids, source_ids)
        result = audit(
            conn,
            industry_ids=industry_ids,
            source_ids=source_ids,
            documents=documents,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    if update_workflow:
        result["workflow"] = update_workflow_manifests(
            industry_ids, documents, source_ids
        )
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    audit_path = CACHE_DIR / "lithium_dual_research_apply_audit.json"
    audit_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    result["audit_path"] = audit_path.relative_to(ROOT).as_posix()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--update-workflow", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            apply(db_path=args.db, update_workflow=args.update_workflow),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
