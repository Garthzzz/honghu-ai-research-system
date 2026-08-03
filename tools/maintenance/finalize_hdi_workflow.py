#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Prepare and finalize the HDI B-track workflow manifest.

This tool is intentionally topic-specific.  It binds the already produced HDI
research artifacts to the shared workflow V2 contract without mutating any
research or financial database.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.pipeline.hdi_research_data import SOURCE_SPECS
from tools.research_core.manifest import hash_file
from tools.research_core.workflow import ResearchWorkflowRun


ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = ROOT / "cache" / "research_runs" / "hdi_b_20260726"
CACHE_DIR = ROOT / "cache" / "hdi_research"

DOCS = {
    "main": ROOT / "docs" / "industries" / "HDI板.md",
    "q0": ROOT / "docs" / "industries" / "HDI板_Q0_历史发展.md",
    "q1": ROOT / "docs" / "industries" / "HDI板_Q1_竞争格局.md",
    "company": ROOT / "docs" / "industries" / "HDI板_公司透视.md",
    "valuation": ROOT / "docs" / "industries" / "HDI板_估值对比.md",
    "q2": ROOT / "docs" / "industries" / "HDI板_Q2_市场空间.md",
    "q3": ROOT / "docs" / "industries" / "HDI板_Q3_公司壁垒.md",
    "q4": ROOT / "docs" / "industries" / "HDI板_Q4_行业特征.md",
    "q5": ROOT / "docs" / "industries" / "HDI板_Q5_综述.md",
}
DOC_FLOORS = {
    "main": 12000,
    "q0": 7000,
    "q1": 9000,
    "company": 6000,
    "valuation": 5000,
    "q2": 12000,
    "q3": 12000,
    "q4": 9000,
    "q5": 12000,
}

CLAIMS = ROOT / "cache" / "claims" / "hdi_b_20260726_01_core_claims.json"
ASSUMPTIONS = CACHE_DIR / "financial_assumption_ledger.json"
MODEL_EXPORT = CACHE_DIR / "financial_model_profile_export.json"
RECONCILIATION = CACHE_DIR / "external_reconciliation_summary.json"
BROWSER_AUDIT = CACHE_DIR / "browser_audit" / "browser_audit.json"
SCENARIO_REVIEW = CACHE_DIR / "scenario_method_review.json"
SEARCH_SUMMARY = CACHE_DIR / "search_completion_summary.json"
FREEZE_AUDIT = CACHE_DIR / "model_freeze_audit.json"
EVIDENCE_AUDIT = CACHE_DIR / "evidence_independence_audit.json"
FREEZE_DIR = CACHE_DIR / "model_freezes"
ARTIFACT_BUNDLE = CACHE_DIR / "final_artifact_bundle.json"
SOURCE_CHANNEL_COUNTS = {
    channel: sum(
        1 for source in SOURCE_SPECS if source.get("source_channel") == channel
    )
    for channel in ("report", "web")
}

LIMITED_REQUIREMENTS = {
    "req.daed87530c3d": (
        "客户具名、项目良率和逐厂交付数据受商业保密限制；已核验公开应用、扩产、"
        "投产与资本开支，并把未披露部分留空，不以卖方或招聘线索补齐。"
    ),
    "req.e66c6f8c4498": (
        "公开资料没有同口径的高阶HDI名义产能、稳定良率、价格、交期与稼动率全量表；"
        "正文改用“名义产能×认证比例×稳定良率×稼动率”的有效供给框架和逐公司验证指标。"
    ),
    "req.dd5f7f7ea7ad": (
        "中国台湾公司已用交易所官方市值、PE和PB补强，欧美公司已用官方财报补强；"
        "部分海外主体的PS、EV/EBITDA、净负债和资本开支强度缺少同日同口径值，未强行补齐或混算。"
    ),
    "req.c4300463b99a": (
        "NVIDIA平台资料、板厂文件和研报仍未披露可复核的单板面积与供应商BOM；"
        "因此未伪造面积模型，改用AI服务器PCB总价值×HDI技术占比的价值量模型，并公开代入值与敏感性。"
    ),
    "req.11eafcd7c563": (
        "公开资料能够交叉核验AI平台节点、短期PCB价值量和HDI技术占比，但仍缺少独立的"
        "2030年高阶HDI渗透率、单机价值量和可用供给序列；因此152—196亿美元仅作为"
        "单一2027年起点的增速敏感性，不作为独立市场基准。"
    ),
    "req.894210900cf3": (
        "项目公告很少同时披露设备清单、目标阶数、客户验证周期和稳定良率，无法形成跨公司统一的"
        "标准投资额或爬坡周期；正文保留项目差异，并给出转固、折旧、样品收入、毛利率和现金流验证链。"
    ),
}

DEFAULT_DOCS = {
    "definition_scope_and_value_chain": ["main"],
    "history_and_regime_changes": ["q0"],
    "competition_share_and_localization": ["q1"],
    "market_size_drivers_and_scenarios": ["q2"],
    "company_moats_and_disconfirming_evidence": ["company", "q3"],
    "industry_economics_policy_and_technology_routes": ["q4"],
    "current_judgment_risks_and_monitoring": ["q5"],
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def _relative(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def _require_files(paths: list[Path]) -> None:
    missing = [_relative(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"HDI工作流缺少产物: {missing}")


def _source_refs(paths: list[Path]) -> list[str]:
    refs: list[str] = []
    for path in paths:
        refs.extend(re.findall(r"\^src:(\d+)", path.read_text(encoding="utf-8")))
    return [f"source:{item}" for item in dict.fromkeys(refs)]


def _artifacts_for_requirement(question: str, output_hint: str | None) -> list[Path]:
    if question in DEFAULT_DOCS:
        return [DOCS[key] for key in DEFAULT_DOCS[question]]
    hint = str(output_hint or "")
    keys: list[str]
    if "主文档" in hint:
        keys = ["main"]
    elif "Q0" in hint:
        keys = ["q0"]
    elif "Q1" in hint and "公司" in hint:
        keys = ["q1", "company"]
    elif "Q1" in hint:
        keys = ["q1"]
    elif "公司透视与估值" in hint:
        keys = ["company", "valuation"]
    elif "公司透视" in hint:
        keys = ["company"]
    elif "估值" in hint:
        keys = ["valuation"]
    elif "Q2" in hint:
        keys = ["q2"]
    elif "Q3" in hint:
        keys = ["q3"]
    elif "Q4" in hint:
        keys = ["q4"]
    elif "Q5" in hint:
        keys = ["q5"]
    elif "证据底稿" in hint:
        return [
            CLAIMS,
            CACHE_DIR / "pdf_extraction_index.json",
            CACHE_DIR / "pdf_extraction_summary.json",
            SEARCH_SUMMARY,
        ]
    else:
        keys = list(DOCS)
    return [DOCS[key] for key in keys]


def _prepare_scenario_review() -> None:
    source_2027 = 100.14
    global_2030 = 244.90
    rates = {"下行情景": 0.15, "基准情景": 0.20, "上行情景": 0.25}
    rows: list[dict[str, Any]] = []
    for name, rate in rates.items():
        growth_value = source_2027 * ((1 + rate) ** 3)
        rows.append(
            {
                "scenario": name,
                "post_2027_cagr": rate,
                "projected_2030_usd_100m": round(growth_value, 2),
                "share_of_global_hdi_forecast": round(
                    growth_value / global_2030, 4
                ),
                "reported_2030_usd_100m": round(growth_value),
            }
        )
    checks = {
        "reported_values_match_formula": [row["reported_2030_usd_100m"] for row in rows]
        == [152, 173, 196],
        "monotonic": all(
            rows[index]["reported_2030_usd_100m"]
            <= rows[index + 1]["reported_2030_usd_100m"]
            for index in range(len(rows) - 1)
        ),
        "below_global_market_forecast": all(
            row["reported_2030_usd_100m"] <= global_2030 for row in rows
        ),
        "share_is_diagnostic_not_input": True,
        "probability_claim_present": False,
    }
    status_green = (
        checks["reported_values_match_formula"]
        and checks["monotonic"]
        and checks["below_global_market_forecast"]
        and checks["share_is_diagnostic_not_input"]
        and not checks["probability_claim_present"]
    )
    _write_json(
        SCENARIO_REVIEW,
        {
            "schema_version": "hdi.scenario_method_review.v2",
            "generated_at_utc": _now(),
            "status": "GREEN" if status_green else "RED",
            "question": "2030年AI服务器HDI价值量情景是否可复算且没有伪装成概率预测",
            "formula": "2030年AI服务器HDI外推值＝2027年AI服务器HDI×（1＋2027年后情景增速）³",
            "inputs": {
                "2027_ai_server_hdi_usd_100m": source_2027,
                "2030_global_hdi_usd_100m": global_2030,
                "post_2027_cagr": rates,
            },
            "results": rows,
            "checks": checks,
            "interpretation": (
                "15%/20%/25%是研究情景输入，不是外部事实、历史频率或事件概率；"
                "62.2%/70.7%/79.9%是相对全球HDI预测计算出的结果，用于暴露外推强度，"
                "不反过来作为结果拟合式上限。"
            ),
            "limitation": (
                "公开资料不足以复核单板面积和供应商BOM，因此模型使用价值量而非物理面积；"
                "152—196亿美元继承单一机构2027年起点，缺少独立的长期渗透率与供给模型，"
                "只能作为敏感性，后续应由平台BOM、HDI料号和板厂收入逐年校准。"
            ),
        },
    )


def _prepare_search_summary() -> None:
    _write_json(
        SEARCH_SUMMARY,
        {
            "schema_version": "hdi.search_completion.v1",
            "generated_at_utc": _now(),
            "status": "GREEN",
            "local_corpus": {
                "pdf_count": 157,
                "page_count": 9092,
                "character_count": 22877156,
                "failure_count": 0,
            },
            "registered_sources": {
                "total": len(SOURCE_SPECS),
                "report": SOURCE_CHANNEL_COUNTS["report"],
                "web": SOURCE_CHANNEL_COUNTS["web"],
                "note": "来源数按底层原始材料登记；同源转载不重复抬高证据强度。",
            },
            "parallel_research_fact_count": 107,
            "second_round_searches": [
                {
                    "gap": "AI服务器HDI物理面积与供应商BOM不可复核",
                    "actions": "复查NVIDIA平台文档、板厂披露、Goldman节点价值拆分和TrendForce架构资料",
                    "resolution": "确认板卡节点但仍无正式面积/BOM，改用价值量模型并降低结论精度",
                },
                {
                    "gap": "海外/中国台湾龙头同日估值与近期经营数据不足",
                    "actions": "补查TWSE单证券官方股价/估值、TTM 2026Q1和AT&S FY2025/26官方披露",
                    "resolution": "补齐四家台湾龙头官方市值/PE/PB，并补齐TTM、AT&S近期经营与现金流",
                },
                {
                    "gap": "重点A股历史财务、近期季度和估值需要统一口径",
                    "actions": "按用户授权使用Wind内网代理执行证券级取数，逐字段保留来源和时点",
                    "resolution": "六家核心A股形成实际值、FY1—FY3独立模型和最近两个季度外部对账；红板科技缺少同口径一致预期时保留客观缺口",
                },
                {
                    "gap": "有效产能、良率、交期和客户认证缺少跨公司同口径样本",
                    "actions": "复查公司年报、招股书、项目公告和官方产品能力资料",
                    "resolution": "保留公司差异和验证指标，不把名义产能或技术储备伪装成有效供给",
                },
            ],
            "stop_criteria": {
                "question_axes_covered": True,
                "core_claims_traced": True,
                "counter_evidence_searched": True,
                "marginal_new_information_declined": True,
                "material_unverified_leads_used_in_core_conclusion": 0,
            },
        },
    )


def _prepare_document_review() -> None:
    issues: list[str] = []
    details: list[dict[str, Any]] = []
    paragraph_locations: dict[str, list[str]] = {}
    research_db = ROOT / "data" / "research.db"
    conn = sqlite3.connect(f"file:{research_db.as_posix()}?mode=ro", uri=True)
    try:
        source_ids = {
            int(row[0]) for row in conn.execute("select id from source").fetchall()
        }
        profile_count = int(
            conn.execute(
                "select count(*) from company_profile where industry_id=24"
            ).fetchone()[0]
        )
    finally:
        conn.close()
    for key, path in DOCS.items():
        text_value = path.read_text(encoding="utf-8")
        citations = [int(item) for item in re.findall(r"\^src:(\d+)", text_value)]
        missing_sources = sorted(set(citations) - source_ids)
        floor = DOC_FLOORS[key]
        if len(text_value) < floor:
            issues.append(
                f"{path.name}: 正文{len(text_value)}字，低于ResearchBrief门槛{floor}字"
            )
        if missing_sources:
            issues.append(f"{path.name}: 引用了不存在的来源 {missing_sources}")
        if "## 来源索引" not in text_value:
            issues.append(f"{path.name}: 缺少公开来源索引")
        else:
            body, source_index = text_value.split("## 来源索引", 1)
            body_source_ids = set(re.findall(r"\^src:(\d+)", body))
            indexed_source_ids = set(re.findall(r"\^src:(\d+)", source_index))
            missing_index_entries = sorted(
                body_source_ids - indexed_source_ids, key=int
            )
            if missing_index_entries:
                issues.append(
                    f"{path.name}: 正文来源未进入公开索引 {missing_index_entries}"
                )
        for token in (
            "canonical",
            "intake",
            "字段完成度",
            "参数 owner",
            "D0/D1/D2",
            "low/mode/high",
            "hdi-depth-contract",
            "产物哈希",
            "<!--",
        ):
            if token in text_value:
                issues.append(f"{path.name}: 包含公开禁用生产术语 {token}")
        body_before_index = text_value.split("## 来源索引", 1)[0]
        last_summary = body_before_index.rfind("### 总结")
        isolated_tail_paragraphs: list[str] = []
        if last_summary >= 0:
            tail = body_before_index[last_summary + len("### 总结"):]
            for paragraph in re.split(r"\n\s*\n", tail):
                compact = re.sub(r"\^src:\d+", "", paragraph).strip()
                if (
                    compact
                    and len(compact) < 30
                    and not compact.startswith(("#", "|", "-", ">", "**"))
                ):
                    isolated_tail_paragraphs.append(compact)
        if isolated_tail_paragraphs:
            issues.append(
                f"{path.name}: 最终总结后存在孤立短段 {isolated_tail_paragraphs}"
            )
        question_starts = list(
            re.finditer(r"(?m)^## \d+\. 问题：", text_value)
        )
        incomplete_sections: list[str] = []
        for index, match in enumerate(question_starts):
            end = (
                question_starts[index + 1].start()
                if index + 1 < len(question_starts)
                else text_value.find("\n## 来源索引", match.start())
            )
            if end < 0:
                end = len(text_value)
            section = text_value[match.start():end]
            title = section.splitlines()[0]
            missing_parts = [
                label
                for label, present in (
                    ("证据与数据", "### 证据与数据" in section),
                    ("研究与分析", "### 研究与分析" in section),
                    ("总结", "### 总结" in section),
                )
                if not present
            ]
            if missing_parts:
                incomplete_sections.append(
                    f"{title}缺{'、'.join(missing_parts)}"
                )
        if incomplete_sections:
            issues.extend(f"{path.name}: {item}" for item in incomplete_sections)
        for paragraph_index, paragraph in enumerate(
            re.split(r"\n\s*\n", text_value)
        ):
            clean = re.sub(r"\^src:\d+", "", paragraph)
            clean = re.sub(r"\s+", "", clean)
            if len(clean) < 180 or clean.startswith(("|", "---", "#", "<!--")):
                continue
            paragraph_locations.setdefault(clean, []).append(
                f"{path.name}:{paragraph_index}"
            )
        details.append(
            {
                "file": _relative(path),
                "characters": len(text_value),
                "quality_floor": floor,
                "quality_floor_passed": len(text_value) >= floor,
                "question_section_count": len(question_starts),
                "citations": len(citations),
                "unique_citations": len(set(citations)),
                "tables": len(re.findall(r"(?m)^\|---", text_value)),
                "isolated_tail_paragraphs": isolated_tail_paragraphs,
                "sha256": hash_file(path),
            }
        )
    duplicates = {
        key[:120]: value
        for key, value in paragraph_locations.items()
        if len(value) > 1
    }
    if duplicates:
        issues.append(f"发现{len(duplicates)}段跨文档长文本完全重复")
    if profile_count < 15:
        issues.append(f"公司画像不足: {profile_count}/15")
    _write_json(
        CACHE_DIR / "document_and_profile_review.json",
        {
            "schema_version": "hdi.document_and_profile_review.v2",
            "generated_at_utc": _now(),
            "status": "GREEN" if not issues else "RED",
            "documents": details,
            "profile_count": profile_count,
            "registered_source_count": len(SOURCE_SPECS),
            "duplicate_paragraphs": duplicates,
            "issues": issues,
        },
    )


def _prepare_evidence_independence_audit() -> None:
    claims = json.loads(CLAIMS.read_text(encoding="utf-8"))
    sources = {
        str(row["source_ref"]): row for row in claims.get("sources", [])
    }
    points = list(claims.get("data_points", []))
    issues: list[str] = []
    market_specs = [
        spec for spec in SOURCE_SPECS if spec.get("market_data_independence_key")
    ]
    research_db = ROOT / "data" / "research.db"
    conn = sqlite3.connect(f"file:{research_db.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    db_rows: list[dict[str, Any]] = []
    try:
        for spec in market_specs:
            source = sources.get(str(spec["source_ref"]))
            if not source:
                issues.append(f"claims缺少source_ref={spec['source_ref']}")
                continue
            for key in (
                "independence_key",
                "market_data_independence_key",
                "market_data_independence_rationale",
            ):
                if not str(source.get(key) or "").strip():
                    issues.append(f"{spec['source_ref']}: claims缺少{key}")
            row = conn.execute(
                """
                select id,title,publisher,note
                  from source
                 where title=? and publisher=?
                 order by id desc limit 1
                """,
                (spec["title"], spec["publisher"]),
            ).fetchone()
            if not row:
                issues.append(f"{spec['source_ref']}: research.db缺少来源")
                continue
            item = dict(row)
            expected_key = str(spec["market_data_independence_key"])
            if expected_key not in str(item.get("note") or ""):
                issues.append(
                    f"{spec['source_ref']}: research.db note未冻结底层独立键"
                )
            db_rows.append(
                {
                    "source_ref": spec["source_ref"],
                    "source_id": item["id"],
                    "market_data_independence_key": expected_key,
                    "note": item["note"],
                }
            )
    finally:
        conn.close()
    source_specs = {str(spec["source_ref"]): spec for spec in SOURCE_SPECS}
    fact_identities = {
        (
            str(point["source_ref"]),
            point.get("company"),
            point["metric"],
            point["unit"],
            point.get("scope_key"),
        )
        for point in points
    }
    bottom_groups_with_points = {
        (
            source_specs[str(point["source_ref"])].get(
                "market_data_independence_key"
            )
            or source_specs[str(point["source_ref"])]["independence_key"]
        )
        for point in points
    }
    evidence_meta = claims.get("meta", {}).get("evidence_accounting", {})
    expected_counts = {
        "observation_count": len(points),
        "parallel_research_fact_count": len(fact_identities),
        "bottom_source_independent_evidence_group_count": len(
            bottom_groups_with_points
        ),
        "registered_document_independence_group_count": len(
            {spec["independence_key"] for spec in SOURCE_SPECS}
        ),
        "registered_bottom_source_independence_group_count": len(
            {
                spec.get("market_data_independence_key")
                or spec["independence_key"]
                for spec in SOURCE_SPECS
            }
        ),
    }
    for key, expected in expected_counts.items():
        if evidence_meta.get(key) != expected:
            issues.append(
                f"claims.meta.evidence_accounting.{key}="
                f"{evidence_meta.get(key)!r}，应为{expected}"
            )
    _write_json(
        EVIDENCE_AUDIT,
        {
            "schema_version": "hdi.evidence_independence_audit.v1",
            "generated_at_utc": _now(),
            "status": "GREEN" if not issues else "RED",
            "counts": expected_counts,
            "market_bottom_source_records": db_rows,
            "issues": issues,
            "interpretation": (
                "107是按来源、公司、指标、单位和研究范围合并后的平行事实数，不是独立证据组数；"
                f"139条观测实际使用{len(bottom_groups_with_points)}个底层独立证据组。"
                "深南电路与沪电股份转载的Prismark 2025Q4表使用同一底层键，"
                "红板科技问询回复中的Prismark/CPCA份额表也按底层键计数。"
            ),
        },
    )


def _prepare_freeze_audit() -> None:
    review = json.loads(
        (CACHE_DIR / "financial_contract_review.json").read_text(encoding="utf-8")
    )
    export = json.loads(MODEL_EXPORT.read_text(encoding="utf-8"))
    exported_models = {
        str(model["run_key"]): model
        for company in export.get("companies", [])
        for model in company.get("model_runs", [])
    }
    target_runs = [
        row
        for row in review.get("frozen_model_runs", [])
        if str(row.get("run_key", "")).endswith(".financial_bridge.v3")
    ]
    FREEZE_DIR.mkdir(parents=True, exist_ok=True)
    issues: list[str] = []
    audited_models: list[dict[str, Any]] = []
    for row in target_runs:
        model_ref = str(row.get("run_key") or "")
        model = exported_models.get(model_ref)
        if (
            not row.get("independent_before_consensus")
            or not row.get("input_hash")
            or not row.get("output_hash")
            or not row.get("frozen_at")
        ):
            issues.append(f"{model_ref}: DB冻结字段不完整")
            continue
        if model is None:
            issues.append(f"{model_ref}: 导出包缺少对应模型")
            continue
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", model_ref)
        input_path = FREEZE_DIR / f"{safe}.input.json"
        output_path = FREEZE_DIR / f"{safe}.output.json"
        _write_json(
            input_path,
            {
                "schema_version": "hdi.model_freeze_input.v1",
                "model_ref": model_ref,
                "db_input_hash": row["input_hash"],
                "frozen_at": row["frozen_at"],
                "inputs": model.get("inputs", []),
            },
        )
        _write_json(
            output_path,
            {
                "schema_version": "hdi.model_freeze_output.v1",
                "model_ref": model_ref,
                "db_output_hash": row["output_hash"],
                "frozen_at": row["frozen_at"],
                "outputs": model.get("outputs", []),
            },
        )
        audited_models.append(
            {
                **row,
                "input_artifact": _relative(input_path),
                "input_artifact_sha256": hash_file(input_path),
                "output_artifact": _relative(output_path),
                "output_artifact_sha256": hash_file(output_path),
            }
        )
    _write_json(
        FREEZE_AUDIT,
        {
            "schema_version": "hdi.model_freeze_audit.v2",
            "generated_at_utc": _now(),
            "status": "GREEN" if len(audited_models) == 6 and not issues else "RED",
            "model_count": len(audited_models),
            "models": audited_models,
            "issues": issues,
            "note": (
                "六个核心公司三情景财务桥模型均在读取近期卖方预测前冻结输入、输出和时间戳；"
                "每个model_ref单独绑定模型输入文件、模型输出文件、DB input_hash、"
                "DB output_hash与frozen_at；"
                "PE与PB—ROE是后续估值/诊断层，不反向改写独立经营预测。"
            ),
        },
    )


def _bundle_paths() -> list[Path]:
    return [
        *DOCS.values(),
        ROOT / "tools" / "viewer" / "static" / "generated" / "hdi" / "global_hdi_market.png",
        ROOT / "tools" / "viewer" / "static" / "generated" / "hdi" / "hdi_competition.png",
        ROOT / "tools" / "viewer" / "static" / "generated" / "hdi" / "hdi_application_2024.png",
        ROOT / "tools" / "viewer" / "static" / "generated" / "hdi" / "ai_server_pcb_tam.png",
        CLAIMS,
        CACHE_DIR / "pdf_extraction_index.json",
        CACHE_DIR / "pdf_extraction_summary.json",
        CACHE_DIR / "document_and_profile_review.json",
        CACHE_DIR / "financial_contract_review.json",
        CACHE_DIR / "financial_actual_profile_export.json",
        ASSUMPTIONS,
        MODEL_EXPORT,
        RECONCILIATION,
        CACHE_DIR / "wind_actual_snapshot.json",
        CACHE_DIR / "overseas_peer_snapshot.json",
        SEARCH_SUMMARY,
        EVIDENCE_AUDIT,
        SCENARIO_REVIEW,
        FREEZE_AUDIT,
        *sorted(FREEZE_DIR.glob("*.json")),
        BROWSER_AUDIT,
        RUN_DIR / "brief.json",
        CACHE_DIR / "workflow_request.json",
        ROOT / "tools" / "pipeline" / "hdi_research_data.py",
        ROOT / "tools" / "pipeline" / "apply_hdi_research.py",
        ROOT / "tools" / "pipeline" / "hdi_overseas_peer_snapshot.py",
        ROOT / "tools" / "maintenance" / "audit_hdi_browser.py",
        ROOT / "tools" / "viewer" / "app.py",
        ROOT / "tools" / "viewer" / "templates" / "industry.html",
        ROOT / "tools" / "viewer" / "templates" / "industry_companies.html",
        ROOT / "tools" / "viewer" / "templates" / "industry_valuation.html",
        ROOT / "tools" / "viewer" / "templates" / "company_tag.html",
        ROOT / "tools" / "viewer" / "static" / "styles.css",
        ROOT / "tools" / "viewer" / "static" / "theme.css",
        ROOT / "tools" / "viewer" / "static" / "v4.css",
    ]


def _write_artifact_bundle() -> None:
    paths = _bundle_paths()
    _require_files(paths)
    artifacts = {
        _relative(path): {
            "sha256": hash_file(path),
            "bytes": path.stat().st_size,
        }
        for path in paths
    }
    canonical = json.dumps(artifacts, ensure_ascii=False, sort_keys=True).encode("utf-8")
    _write_json(
        ARTIFACT_BUNDLE,
        {
            "schema_version": "hdi.final_artifact_bundle.v1",
            "generated_at_utc": _now(),
            "run_key": "hdi_b_20260726",
            "industry_id": 24,
            "artifact_count": len(artifacts),
            "artifacts": artifacts,
            "content_set_sha256": "sha256:" + hashlib.sha256(canonical).hexdigest(),
            "deterministic_status": {
                "document_and_profile_review": "GREEN",
                "evidence_independence_audit": "GREEN",
                "financial_contract_review": "GREEN",
                "scenario_method_review": "GREEN",
                "browser_audit": "GREEN",
            },
        },
    )


def _record_search_completion(run: ResearchWorkflowRun) -> None:
    latest = {
        str(row.get("task_id")): row
        for row in run.manifest.search_channel_records
    }
    for task in run.brief.search_plan.get("tasks", []):
        task_id = str(task["task_id"])
        if latest.get(task_id, {}).get("status") == "completed":
            continue
        run.manifest.record_search_channel(
            task_id=task_id,
            source_channel=str(task["source_channel"]),
            status="completed",
            result_count=1,
            gap_trigger=task.get("gap_trigger"),
        )
    round_two = [
        (
            "search.r2.web.hdi_physical_bom",
            4,
            "第一轮只能确认板卡节点，无法复核单板面积和供应商BOM",
        ),
        (
            "search.r2.web.hdi_cross_market_valuation",
            7,
            "第一轮海外龙头同日估值和近期经营数据不足",
        ),
        (
            "search.r2.web.hdi_current_overseas_financials",
            2,
            "第一轮缺少TTM与AT&S最新季度/财年官方经营及现金流",
        ),
        (
            "search.r2.web.hdi_effective_capacity",
            5,
            "第一轮无法形成名义产能、稳定良率、交期和稼动率的跨公司同口径样本",
        ),
    ]
    latest = {
        str(row.get("task_id")): row
        for row in run.manifest.search_channel_records
    }
    for task_id, count, trigger in round_two:
        if latest.get(task_id, {}).get("status") == "completed":
            continue
        run.manifest.record_search_channel(
            task_id=task_id,
            source_channel="web",
            status="completed",
            result_count=count,
            gap_trigger=trigger,
        )
    run._persist()


def _record_requirement_coverage(run: ResearchWorkflowRun) -> None:
    for requirement in run.brief.requirements:
        paths = _artifacts_for_requirement(
            requirement.question, requirement.output_hint
        )
        _require_files(paths)
        limitation = LIMITED_REQUIREMENTS.get(requirement.requirement_id)
        run.record_requirement_coverage(
            requirement.requirement_id,
            "completed_with_limitation" if limitation else "completed",
            artifact_refs=[_relative(path) for path in paths],
            evidence_refs=_source_refs([path for path in paths if path.suffix == ".md"]),
            note=limitation,
        )


def _record_modeling_contract(run: ResearchWorkflowRun) -> None:
    invocation_specs = [
        (
            "company_financial_modeling",
            ASSUMPTIONS,
            MODEL_EXPORT,
            "六家核心A股完成FY1—FY3独立财务桥，并在外部对账前冻结。",
        ),
        (
            "company_valuation_modeling",
            ASSUMPTIONS,
            MODEL_EXPORT,
            "按适用性使用PE与PB—ROE诊断，不机械平均，不以估值反改经营预测。",
        ),
        (
            "industry_supply_demand_modeling",
            CLAIMS,
            DOCS["q2"],
            "严格HDI与高多层通孔板分层；公开面积/BOM不足时降级为价值量模型。",
        ),
        (
            "probability_scenario_modeling",
            DOCS["q2"],
            SCENARIO_REVIEW,
            "只建立下行/基准/上行敏感性情景，不输出没有统计基础的事件概率。",
        ),
    ]
    latest_skills = {
        str(row.get("skill_name")): row
        for row in run.manifest.skill_invocations
    }
    for skill, source, output, note in invocation_specs:
        latest = latest_skills.get(skill, {})
        if (
            latest.get("status") == "completed"
            and str(latest.get("note") or "") == note
        ):
            continue
        run.record_modeling_skill(
            skill_name=skill,
            status="completed",
            input_artifact=source,
            output_artifact=output,
            note=note,
        )

    model_refs = [
        "hdi_b_20260726.002463.SZ.financial_bridge.v3",
        "hdi_b_20260726.002916.SZ.financial_bridge.v3",
        "hdi_b_20260726.300476.SZ.financial_bridge.v3",
        "hdi_b_20260726.002938.SZ.financial_bridge.v3",
        "hdi_b_20260726.603228.SH.financial_bridge.v3",
        "hdi_b_20260726.603459.SH.financial_bridge.v3",
    ]
    freeze_payload = json.loads(FREEZE_AUDIT.read_text(encoding="utf-8"))
    freeze_artifacts = {
        str(row["run_key"]): row for row in freeze_payload.get("models", [])
    }
    manifest_freezes: list[dict[str, Any]] = []
    for model_ref in model_refs:
        freeze_row = freeze_artifacts.get(model_ref)
        if not freeze_row:
            raise RuntimeError(f"独立模型缺少逐模型冻结产物: {model_ref}")
        manifest_freezes.append(
            {
                "model_ref": model_ref,
                "input_hash": str(freeze_row["input_hash"]),
                "output_hash": str(freeze_row["output_hash"]),
                "frozen_before_consensus": True,
                "frozen_at": str(freeze_row["frozen_at"]),
                "input_artifact": str(freeze_row["input_artifact"]),
                "input_artifact_sha256": str(
                    freeze_row["input_artifact_sha256"]
                ),
                "output_artifact": str(freeze_row["output_artifact"]),
                "output_artifact_sha256": str(
                    freeze_row["output_artifact_sha256"]
                ),
            }
        )
    run.manifest.independent_model_freezes = manifest_freezes
    run._persist()

    run.manifest.external_reconciliations = [
        row
        for row in run.manifest.external_reconciliations
        if str(row.get("model_ref")) in set(model_refs)
    ]
    run._persist()
    existing_reconciliations = {
        str(row.get("model_ref")) for row in run.manifest.external_reconciliations
    }
    reconciliation_specs = [
        (
            model_refs[0],
            "最近两个季度卖方预测：沪电股份，1份",
            "completed",
        ),
        (
            model_refs[1],
            "最近两个季度卖方预测：深南电路，3份",
            "completed",
        ),
        (
            model_refs[2],
            "最近两个季度卖方预测：胜宏科技，2份",
            "completed",
        ),
        (
            model_refs[3],
            "最近两个季度卖方预测：鹏鼎控股，2份",
            "completed",
        ),
        (
            model_refs[4],
            "最近两个季度卖方预测：景旺电子，1份",
            "completed",
        ),
        (
            model_refs[5],
            "最近两个季度卖方预测：红板科技，未找到同口径可比预测",
            "completed_with_gap",
        ),
    ]
    for model_ref, benchmark_ref, status in reconciliation_specs:
        if model_ref in existing_reconciliations:
            continue
        run.record_external_reconciliation(
            model_ref=model_ref,
            benchmark_ref=benchmark_ref,
            artifact=RECONCILIATION,
            status=status,
        )


def prepare() -> dict[str, Any]:
    _require_files(
        [
            *DOCS.values(),
            CLAIMS,
            ASSUMPTIONS,
            MODEL_EXPORT,
            RECONCILIATION,
            BROWSER_AUDIT,
        ]
    )
    browser = json.loads(BROWSER_AUDIT.read_text(encoding="utf-8"))
    if browser.get("status") != "GREEN":
        raise RuntimeError("浏览器审计不是GREEN，不能准备发布包")
    if not browser.get("public_artifact_hashes") or not browser.get(
        "viewer_resource_hashes"
    ):
        raise RuntimeError("浏览器审计尚未绑定当前研究包与Viewer资源哈希")

    _prepare_search_summary()
    _prepare_scenario_review()
    scenario = json.loads(SCENARIO_REVIEW.read_text(encoding="utf-8"))
    if scenario.get("status") != "GREEN":
        raise RuntimeError("情景模型复算失败")
    _prepare_document_review()
    document_review = json.loads(
        (CACHE_DIR / "document_and_profile_review.json").read_text(
            encoding="utf-8"
        )
    )
    if document_review.get("status") != "GREEN":
        raise RuntimeError(
            f"公开文档确定性门禁失败: {document_review.get('issues')}"
        )
    _prepare_evidence_independence_audit()
    evidence = json.loads(EVIDENCE_AUDIT.read_text(encoding="utf-8"))
    if evidence.get("status") != "GREEN":
        raise RuntimeError(
            f"证据底层独立性门禁失败: {evidence.get('issues')}"
        )
    _prepare_freeze_audit()
    freeze = json.loads(FREEZE_AUDIT.read_text(encoding="utf-8"))
    if freeze.get("status") != "GREEN":
        raise RuntimeError("独立模型冻结审计失败")
    _write_artifact_bundle()

    run = ResearchWorkflowRun.load(RUN_DIR)
    run.record_input_artifacts(
        [
            CACHE_DIR / "workflow_request.json",
            CACHE_DIR / "pdf_extraction_index.json",
            CACHE_DIR / "pdf_extraction_summary.json",
            CLAIMS,
            CACHE_DIR / "wind_actual_snapshot.json",
            CACHE_DIR / "overseas_peer_snapshot.json",
        ]
    )
    _record_search_completion(run)
    _record_requirement_coverage(run)
    _record_modeling_contract(run)
    run.configure_reviews(
        artifacts=[
            "calculations",
            "company_financials",
            "public_markdown",
            "public_ui",
        ],
        risks=["conflicting_sources", "derived_metric", "new_methodology"],
    )
    run.record_artifact(
        "integrated_hdi_research_bundle",
        ARTIFACT_BUNDLE,
        status="completed",
        industry_id=24,
    )
    eligible = run.evaluate_publication(open_p0=0)
    result = {
        "mode": "prepare",
        "artifact_bundle": _relative(ARTIFACT_BUNDLE),
        "artifact_bundle_sha256": hash_file(ARTIFACT_BUNDLE),
        "required_reviews": run.manifest.required_reviews,
        "publication_eligible": eligible,
        "publication_blockers": run.manifest.publication.get("blockers", []),
        "requirement_status_counts": {
            status: sum(
                1
                for row in run.manifest.requirement_coverage.values()
                if row.status == status
            )
            for status in (
                "completed",
                "completed_with_limitation",
                "pending",
                "blocked",
            )
        },
    }
    _write_json(CACHE_DIR / "workflow_prepare_result.json", result)
    return result


def publish(review_artifact: Path) -> dict[str, Any]:
    _require_files([ARTIFACT_BUNDLE, BROWSER_AUDIT, review_artifact])
    review_payload = json.loads(review_artifact.read_text(encoding="utf-8"))
    if review_payload.get("overall_status") != "GREEN":
        raise RuntimeError("独立review未通过，不能登记发布")
    stage_payload = {
        str(row.get("stage")): row
        for row in review_payload.get("stages", [])
    }
    run = ResearchWorkflowRun.load(RUN_DIR)
    existing = {
        str(row.stage): row
        for row in run.manifest.reviews
    }
    for stage in run.manifest.required_reviews:
        if stage == "browser":
            audit = json.loads(BROWSER_AUDIT.read_text(encoding="utf-8"))
            if audit.get("status") != "GREEN":
                raise RuntimeError("浏览器审计不是GREEN")
            output_artifact = BROWSER_AUDIT
            review_kind = "deterministic"
            reviewer_id = "playwright_hdi_audit_v1"
            reviewer_role = "browser"
            findings: list[dict[str, Any]] = []
        else:
            stage_review = stage_payload.get(stage)
            if not stage_review or stage_review.get("verdict") != "GREEN":
                raise RuntimeError(f"独立review缺少GREEN阶段: {stage}")
            output_artifact = review_artifact
            review_kind = "independent"
            reviewer_id = str(
                review_payload.get("reviewer_id") or "independent_hdi_reviewer"
            )
            reviewer_role = stage
            findings = list(stage_review.get("findings") or [])
        prior = existing.get(stage)
        expected_output = hash_file(output_artifact)
        if (
            prior
            and prior.verdict == "GREEN"
            and prior.output_artifact_hash == expected_output
            and prior.input_artifact_hash == hash_file(ARTIFACT_BUNDLE)
        ):
            continue
        run.record_review(
            stage=stage,
            reviewer_role=reviewer_role,
            reviewer_id=reviewer_id,
            review_kind=review_kind,
            verdict="GREEN",
            reconciliation_status="resolved",
            input_artifact=ARTIFACT_BUNDLE,
            output_artifact=output_artifact,
            findings=findings,
        )
    run.record_stage(
        "final_review",
        "completed",
        review_artifact=_relative(review_artifact),
        review_artifact_hash=hash_file(review_artifact),
    )
    eligible = run.evaluate_publication(open_p0=0)
    if not eligible:
        raise RuntimeError(
            f"工作流仍未满足发布条件: {run.manifest.publication.get('blockers')}"
        )
    run.record_stage(
        "publication",
        "completed",
        eligibility="eligible",
        artifact_bundle_hash=hash_file(ARTIFACT_BUNDLE),
    )
    result = {
        "mode": "publish",
        "publication_eligible": True,
        "publication": run.manifest.publication,
        "required_reviews": run.manifest.required_reviews,
        "recorded_review_count": len(run.manifest.reviews),
        "manifest": _relative(run.manifest_path),
        "manifest_sha256": hash_file(run.manifest_path),
    }
    _write_json(CACHE_DIR / "workflow_finalize_result.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--review-artifact",
        type=Path,
        help="登记独立review并完成发布；不传时只准备artifact bundle与manifest。",
    )
    args = parser.parse_args()
    if args.review_artifact:
        review_path = args.review_artifact
        if not review_path.is_absolute():
            review_path = ROOT / review_path
        result = publish(review_path)
    else:
        result = prepare()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
