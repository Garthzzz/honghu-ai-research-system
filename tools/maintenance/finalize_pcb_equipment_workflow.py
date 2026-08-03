#!/usr/bin/env python
"""Audit and update the B-track execution manifest for PCB equipment research."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.research_core.workflow import ResearchWorkflowRun


ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = ROOT / "cache" / "research_runs" / "pcb_equipment_b_20260719"
CLAIMS = ROOT / "cache" / "pcb_equipment_research" / "pcb_equipment_corrected_claims_v3.json"
AUDIT_OUTPUT = ROOT / "cache" / "pcb_equipment_research" / "workflow_gate_audit.json"
DEFAULT_DB = ROOT / "cache" / "pcb_equipment_research" / "research_validation_final_20260719_2125.db"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT)).replace("\\", "/")


def _table_errors(text: str) -> int:
    lines = text.splitlines()
    errors = 0
    for index, line in enumerate(lines[:-1]):
        if not line.lstrip().startswith("|"):
            continue
        if index + 1 >= len(lines) or not re.match(r"^\s*\|?\s*:?-{3,}", lines[index + 1]):
            continue
        expected = line.count("|")
        cursor = index + 2
        while cursor < len(lines) and lines[cursor].lstrip().startswith("|"):
            if lines[cursor].count("|") != expected:
                errors += 1
            cursor += 1
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--browser-audit", type=Path)
    parser.add_argument("--snapshot-output", type=Path,
                        help="可选：将本次更新后的execution manifest冻结到独立快照文件")
    args = parser.parse_args()
    db_path = args.db.resolve()
    browser_path = args.browser_audit.resolve() if args.browser_audit else None

    docs = {
        "main": ROOT / "docs" / "industries" / "PCB专用设备.md",
        "q0": ROOT / "docs" / "industries" / "PCB专用设备_Q0_历史发展.md",
        "q1": ROOT / "docs" / "industries" / "PCB专用设备_Q1_竞争格局.md",
        "q2": ROOT / "docs" / "industries" / "PCB专用设备_Q2_市场空间.md",
        "q3": ROOT / "docs" / "industries" / "PCB专用设备_Q3_公司壁垒.md",
        "q4": ROOT / "docs" / "industries" / "PCB专用设备_Q4_行业特征.md",
        "q5": ROOT / "docs" / "industries" / "PCB专用设备_Q5_综述.md",
    }
    floors = {"main": 12_000, "q0": 7_000, "q1": 10_000, "q2": 12_000,
              "q3": 12_000, "q4": 9_000, "q5": 12_000}
    charts = sorted((ROOT / "tools" / "viewer" / "static" / "generated" / "pcb_equipment").glob("*.png"))
    raw_financial = ROOT / "cache" / "pcb_equipment_research" / "company_financial_snapshot.json"
    financial = ROOT / "cache" / "pcb_equipment_research" / "staging_financial_contract" / "company_financial_snapshot_v2.json"
    ledger = ROOT / "cache" / "pcb_equipment_research" / "calculation_ledger.json"
    extraction = ROOT / "cache" / "pcb_equipment_research" / "pdf_extraction_index.json"
    application = ROOT / "cache" / "pcb_equipment_research" / "application_manifest.json"
    producer = ROOT / "cache" / "pcb_equipment_research" / "producer_manifest.json"
    source_map = ROOT / "cache" / "db_queue" / "pcb_equipment_b_20260719_source_map.json"

    claims = json.loads(CLAIMS.read_text(encoding="utf-8"))
    sources = claims.get("sources") or []
    points = claims.get("data_points") or []
    source_refs = {str(source.get("source_ref")) for source in sources}
    required_source_fields = {
        "source_ref", "title", "publisher", "publish_date", "source_type", "quality_tier",
        "language", "fetch_method", "independence_key", "independence_basis",
    }
    missing_source_metadata = [
        source.get("source_ref") for source in sources
        if any(source.get(field) in (None, "") for field in required_source_fields)
    ]
    invalid_points: list[int] = []
    for index, point in enumerate(points):
        valid = (
            point.get("source_ref") in source_refs
            and bool(str(point.get("metric") or "").strip())
            and bool(str(point.get("period") or point.get("as_of_date") or "").strip())
            and bool(str(point.get("unit") or "").strip())
            and bool(str(point.get("source_excerpt") or "").strip())
            and point.get("extraction_method") in {"pdf_direct", "web_fetch", "inferred"}
        )
        if point.get("value_num") is not None:
            valid = valid and isinstance(point["value_num"], (int, float)) and math.isfinite(point["value_num"])
        if not valid:
            invalid_points.append(index)
    identity_keys = [
        tuple(str(point.get(key)) for key in (
            "source_ref", "company", "metric", "period", "as_of_date", "value_num",
            "value_text", "unit", "scope_key",
        ))
        for point in points
    ]
    exact_duplicate_count = sum(
        count - 1 for count in collections.Counter(identity_keys).values() if count > 1
    )

    conn = sqlite3.connect(db_path)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        fk_errors = len(conn.execute("PRAGMA foreign_key_check").fetchall())
        db_counts = {
            "data_points": conn.execute(
                "SELECT COUNT(*) FROM industry_data_point WHERE industry_id=23"
            ).fetchone()[0],
            "profiles": conn.execute(
                "SELECT COUNT(*) FROM company_profile WHERE industry_id=23"
            ).fetchone()[0],
            "company_links": conn.execute(
                "SELECT COUNT(*) FROM company_industry WHERE industry_id=23"
            ).fetchone()[0],
            "shares": conn.execute(
                "SELECT COUNT(*) FROM company_sub_market_share WHERE industry_id=23"
            ).fetchone()[0],
        }
        registered_source_ids = {
            int(row[0]) for row in conn.execute("SELECT id FROM source")
        }
    finally:
        conn.close()

    doc_results: dict[str, Any] = {}
    cited_source_ids: set[int] = set()
    machine_terms = re.compile(
        r"\b(?:canonical|intake|low/mode/high|parameter owner)\b|"
        r"(?:字段完成度|输出覆盖卡|决策验证债|七字段事件监控 dashboard)"
    )
    for key, path in docs.items():
        text = path.read_text(encoding="utf-8")
        citations = {int(value) for value in re.findall(r"\^src:(\d+)", text)}
        cited_source_ids.update(citations)
        doc_results[key] = {
            "path": _rel(path),
            "sha256": _sha256(path),
            "characters": len(text),
            "minimum_characters": floors[key],
            "meets_floor": len(text) >= floors[key],
            "table_pipe_errors": _table_errors(text),
            "citation_count": len(re.findall(r"\^src:\d+", text)),
            "unique_source_ids": sorted(citations),
            "machine_term_hits": machine_terms.findall(text),
        }
    unresolved_citations = sorted(cited_source_ids - registered_source_ids)

    browser_green = False
    browser_result: dict[str, Any] | None = None
    if browser_path:
        browser_result = json.loads(browser_path.read_text(encoding="utf-8"))
        browser_green = browser_result.get("verdict") == "GREEN" and not browser_result.get("findings")

    checks = {
        "contract": (
            len(points) == 1064
            and all(result["meets_floor"] for result in doc_results.values())
            and all(result["table_pipe_errors"] == 0 for result in doc_results.values())
            and all(not result["machine_term_hits"] for result in doc_results.values())
            and db_counts == {"data_points": 1066, "profiles": 30, "company_links": 30, "shares": 3}
        ),
        "evidence_integrity": not invalid_points and integrity == "ok" and fk_errors == 0,
        "provenance": not missing_source_metadata and not unresolved_citations and bool(cited_source_ids),
        "duplication": exact_duplicate_count == 0,
        "scope_and_units": not invalid_points and all(
            point.get("unit") and (point.get("period") or point.get("as_of_date")) for point in points
        ),
    }
    audit_payload = {
        "schema_version": "pcb_equipment.workflow_gate_audit.v1",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "claims": {"path": _rel(CLAIMS), "sha256": _sha256(CLAIMS), "data_points": len(points),
                   "sources": len(sources), "invalid_point_indices": invalid_points,
                   "missing_source_metadata": missing_source_metadata,
                   "exact_duplicate_count": exact_duplicate_count},
        "documents": doc_results,
        "database": {"path": _rel(db_path), "sha256": _sha256(db_path), "integrity": integrity,
                     "foreign_key_errors": fk_errors, "counts": db_counts},
        "citations": {"unique_source_ids": sorted(cited_source_ids),
                      "unresolved_source_ids": unresolved_citations},
        "browser_audit": ({"path": _rel(browser_path), "sha256": _sha256(browser_path),
                           "verdict": browser_result.get("verdict")} if browser_result else None),
        "gates": {gate: ("GREEN" if passed else "RED") for gate, passed in checks.items()},
    }
    AUDIT_OUTPUT.write_text(
        json.dumps(audit_payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    run = ResearchWorkflowRun.load(RUN_DIR)
    required_inputs = [
        CLAIMS, raw_financial, financial, ledger, extraction, application, producer, source_map, db_path,
        *docs.values(), *charts,
    ]
    if browser_path:
        required_inputs.append(browser_path)
    run.record_input_artifacts(required_inputs)
    run.configure_reviews(
        artifacts=["calculations", "company_financials", "public_markdown", "public_ui"],
        risks=["new_methodology", "derived_metric", "conflicting_sources"],
    )

    doc_ref = {key: [_rel(path)] for key, path in docs.items()}
    # Requirement evidence must match the citations actually frozen in each public
    # document. Deriving it prevents a hand-maintained representative list from
    # claiming sources that the section does not cite or omitting cited sources.
    section_evidence = {
        key: [f"source_id:{source_id}" for source_id in result["unique_source_ids"]]
        for key, result in doc_results.items()
    }
    limitation_notes = {
        "req.bc82214f07c6": "公开资料缺少层数、板厚、孔径比、应用与可靠性的统一连续量化序列；报告以可核验节点构建阶段时间轴，不能据此计算连续提升幅度。",
        "req.312c89d702ac": "设备升级收益只有少数参数与价格样本可量化；多数良率、人工、材料损耗、周期和单台价值缺少同口径前后对照。",
        "req.4f533cf9ec75": "可核验全部PCB专用设备的全球及主要亚洲区域序列，但18层以上独立市场、欧洲与北美拆分客观不可得。",
        "req.2a257e37f53d": "只核验到全设备与DI的CR5及3条严格分母份额；CR10、HHI和多数细分份额缺少同一分母，未强行计算。",
        "req.a15c01d637cb": "仅大族数控、芯碁微装披露局部产能产量；全球需求、供需缺口、完整交期和关键瓶颈无法统一量化。",
        "req.4ddb30915ae8": "九家下游逐项给出项目事实和证据缺口，但完整高多层产能、设备清单及采购台数金额未公开。",
        "req.47d30b4e17ce": "项目事实与设备需求判断已分列；公开资料不足以逐项目量化新增、技改和维护更新的台数与金额。",
        "req.f4e8742572c9": "型号、参数和公开客户只在局部形成闭环；完整交期、采购型号和全部客户验证不公开。",
        "req.693642385ae9": "23个上市经济实体中15个目标四期完整，8个不完整；日本主体及部分集团接口缺期，多数公司也不拆PCB设备分部财务。",
        "req.6458f6a4292a": "上市不足期、接口缺失、私营、品牌和集团口径已逐主体解释；无法把缺失期或未披露分部补造成完整四期。",
        "req.1ca4f673cc6f": "仅保留3条具有严格市场分母的公司份额，无法构造共同分母下的全公司全球/中国排名。",
        "req.12bc8ff837bb": "市场序列与结构图已完成；因份额分母不兼容，竞争气泡图使用集团财务参照而非伪造份额×增速。",
        "req.5be700c7202b": "多个主体缺完整PE、PS或财务指标，且集团与PCB品牌业务边界不同；只在同币种、同业务组内比较。",
        "req.db64100aaa22": "层数与应用的技术关系可以核验，但各层数区间产值、面积和份额缺少可靠统一分母。",
        "req.73448352092a": "公开输入不足以建立带月产能分母的标准产线；4.886亿元仅为示意设备篮子，不是标准线、完整BOM或预算。",
        "req.feb437d62bc0": "缺少统一月产能、板尺寸、产品结构、设备数量和备机率输入，因此没有伪造标准线；报告公开示意篮子输入与限制。",
        "req.e4a2accabafa": "下游项目已映射可能受益设备，但无法形成2025—2030完整新增、技改与维护设备台数序列。",
        "req.e5d612bbcf77": "只采用公开单价样本锚；单机毛利、高低端同口径价差和完整定价资料普遍不披露。",
        "req.5d78e34f489f": "完成市场趋势、设备结构和示意篮子图；真实扩产需求瀑布及完整量价规模交叉验证因输入不可得而未构造。",
        "req.d4e41498be31": "只有少数公开参数可以同口径比较；良率、稼动率、MTBF和维护周期不足，因此按合同未绘制技术雷达。",
        "req.d37ecebdd45e": "报告给出条件化行业与技术路线情景，但公开资料不足以逐公司量化未来研发、扩产和客户认证概率。",
    }

    all_doc_refs = [_rel(path) for path in docs.values()]
    chart_refs = [_rel(path) for path in charts]
    company_artifacts = [
        _rel(db_path), _rel(raw_financial), _rel(financial), _rel(application),
        "tools/viewer/app.py",
        "tools/viewer/templates/industry_companies.html",
        "tools/viewer/templates/company_tag.html",
    ]
    valuation_artifacts = [
        _rel(db_path), _rel(raw_financial), _rel(financial),
        "tools/viewer/app.py",
        "tools/viewer/templates/industry_valuation.html",
    ]
    viewer_artifacts = [
        *all_doc_refs, *company_artifacts, *valuation_artifacts, *chart_refs,
        "tools/viewer/templates/industry.html",
    ]
    mapped_source_ids = sorted(set(json.loads(source_map.read_text(encoding="utf-8")).values()))
    profile_evidence = [f"source_id:{source_id}" for source_id in mapped_source_ids]

    default_doc_targets = {
        1: ["main"], 2: ["q0"], 3: ["q1"], 4: ["q2"],
        5: ["q3"], 6: ["q4"], 7: ["q5"],
    }
    hint_doc_targets = {
        "主文档": ["main"],
        "主文档与Q3": ["main", "q3"],
        "Q0历史发展": ["q0"],
        "Q1竞争格局": ["q1"],
        "Q1与Q2": ["q1", "q2"],
        "Q1图表": ["q1"],
        "Q2市场空间": ["q2"],
        "Q2图表": ["q2"],
        "Q3公司壁垒": ["q3"],
        "Q4行业特征": ["q4"],
        "Q5综述": ["q5"],
        "Q1与公司透视": ["q1"],
    }

    for index, requirement in enumerate(run.brief.requirements, 1):
        rid = requirement.requirement_id
        hint = str(requirement.output_hint or "").strip()
        doc_keys = default_doc_targets.get(index, hint_doc_targets.get(hint, []))
        artifacts = [ref for key in doc_keys for ref in doc_ref[key]]
        evidence = [ref for key in doc_keys for ref in section_evidence[key]]

        if hint in {"全部公开产物", "全部公开栏目", "Viewer九栏目", "对应章节与Q6"}:
            doc_keys = list(docs)
            artifacts = list(viewer_artifacts)
            evidence = [ref for key in doc_keys for ref in section_evidence[key]] + profile_evidence
        elif hint == "公司透视":
            artifacts = list(company_artifacts)
            evidence = list(profile_evidence)
        elif hint == "估值对比":
            artifacts = list(valuation_artifacts)
            evidence = ["source_id:813", "source_id:814", "source_id:702"]
        elif hint == "公司透视与估值":
            artifacts = [*company_artifacts, *valuation_artifacts]
            evidence = list(profile_evidence)
        elif hint == "Q1与公司透视":
            artifacts = [*doc_ref["q1"], *company_artifacts]
            evidence = [*section_evidence["q1"], *profile_evidence]
        elif hint == "证据底稿":
            artifacts = [_rel(extraction), _rel(CLAIMS), _rel(source_map), _rel(producer), *all_doc_refs]
            evidence = [f"source_ref:{source_ref}" for source_ref in sorted(source_refs)]
        elif hint in {"Q1图表", "Q2图表"}:
            artifacts = [*artifacts, *chart_refs, _rel(ledger)]

        artifacts = list(dict.fromkeys(artifacts))
        evidence = list(dict.fromkeys(evidence))
        status = "completed_with_limitation" if rid in limitation_notes else "completed"
        note = limitation_notes.get(rid)
        if index in {33, 49}:
            artifacts = list(dict.fromkeys([*artifacts, _rel(ledger)]))
        if index == 52:
            if browser_green and browser_path:
                artifacts = list(dict.fromkeys([*artifacts, _rel(browser_path)]))
            else:
                status = "pending"
                note = None
        run.record_requirement_coverage(
            rid,
            status,
            artifact_refs=artifacts,
            evidence_refs=evidence,
            note=note,
        )

    gate_refs = [_rel(AUDIT_OUTPUT), _rel(CLAIMS), _rel(db_path), *all_doc_refs]
    for gate, passed in checks.items():
        run.record_gate(
            gate,
            "GREEN" if passed else "RED",
            findings=[] if passed else [{"severity": "P0", "summary": f"{gate} machine audit failed"}],
            artifact_refs=gate_refs,
        )
    run.record_stage(
        "candidate_validation",
        "completed" if all(checks.values()) else "failed",
        audit_path=_rel(AUDIT_OUTPUT),
        audit_hash="sha256:" + _sha256(AUDIT_OUTPUT),
        browser_audit_green=browser_green,
        requirement_completed=sum(
            item.status == "completed" for item in run.manifest.requirement_coverage.values()
        ),
        requirement_completed_with_limitation=sum(
            item.status == "completed_with_limitation" for item in run.manifest.requirement_coverage.values()
        ),
        requirement_pending=sum(
            item.status == "pending" for item in run.manifest.requirement_coverage.values()
        ),
    )

    snapshot_path = None
    if args.snapshot_output:
        snapshot_path = args.snapshot_output.resolve()
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_bytes(run.manifest_path.read_bytes())

    print(json.dumps({
        "manifest": _rel(run.manifest_path),
        "manifest_sha256": _sha256(run.manifest_path),
        "audit": _rel(AUDIT_OUTPUT),
        "audit_sha256": _sha256(AUDIT_OUTPUT),
        "gates": audit_payload["gates"],
        "browser_green": browser_green,
        "coverage": collections.Counter(
            item.status for item in run.manifest.requirement_coverage.values()
        ),
        "required_reviews": run.manifest.required_reviews,
        "snapshot": (_rel(snapshot_path) if snapshot_path else None),
        "snapshot_sha256": (_sha256(snapshot_path) if snapshot_path else None),
    }, ensure_ascii=False, indent=2, default=dict))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
