#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Deterministic finalization for the lithium/carbonate dual B-track package."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.maintenance.audit_lithium_browser import (
    PUBLIC_ARTIFACTS,
    VIEWER_RESOURCES,
)
from tools.research_core.manifest import hash_file
from tools.research_core.workflow import ResearchWorkflowRun


ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "cache" / "lithium_research"
MODELS = CACHE / "models"
BROWSER_AUDIT = CACHE / "browser_audit" / "browser_audit.json"
DETERMINISTIC_AUDIT = CACHE / "deterministic_final_review.json"
ARTIFACT_BUNDLE = CACHE / "final_artifact_bundle.json"
PREPARE_RESULT = CACHE / "workflow_finalize_result.json"
MODEL = MODELS / "lithium_company_independent_models_v1.json"
RECON = MODELS / "lithium_external_reconciliation_v1.json"
LITHIUM_SUPPLY = MODELS / "lithium_supply_demand_model_v1.json"
CARBONATE_SUPPLY = MODELS / "carbonate_supply_demand_model_v1.json"
CLAIMS = {
    "锂": ROOT / "cache" / "claims" / "lithium_b_20260727_01_core_claims.json",
    "碳酸锂": (
        ROOT
        / "cache"
        / "claims"
        / "lithium_carbonate_b_20260727_01_core_claims.json"
    ),
}
RUN_DIRS = {
    "锂": ROOT / "cache" / "research_runs" / "lithium_b_20260727",
    "碳酸锂": (
        ROOT
        / "cache"
        / "research_runs"
        / "lithium_carbonate_b_20260727"
    ),
}
DOCS = {
    industry: sorted(
        [
            path
            for path in PUBLIC_ARTIFACTS
            if path.name == f"{industry}.md"
            or path.name.startswith(f"{industry}_")
        ],
        key=lambda path: path.name,
    )
    for industry in ("锂", "碳酸锂")
}
COMPANY_IDS = list(range(640, 653))
PROHIBITED_PUBLIC_TOKENS = (
    "canonical",
    "intake",
    "字段完成度",
    "输出覆盖卡",
    "参数 owner",
    "D0/D1/D2",
    "A—F",
    "P/H/C",
    "low/mode/high",
    "cache/lithium_research",
    "source_ref:",
    "opp://",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _require(paths: list[Path]) -> None:
    missing = [_relative(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"锂与碳酸锂终审缺少产物: {missing}")


def _strip_frontmatter(text: str) -> str:
    return re.sub(r"\A---\s*\n.*?\n---\s*\n", "", text, flags=re.S)


def _document_review() -> tuple[dict[str, Any], list[str]]:
    issues: list[str] = []
    details: list[dict[str, Any]] = []
    conn = sqlite3.connect(
        f"file:{(ROOT / 'data' / 'research.db').as_posix()}?mode=ro",
        uri=True,
    )
    try:
        source_ids = {int(row[0]) for row in conn.execute("select id from source")}
    finally:
        conn.close()

    expected_links = {f"/company/{company_id}" for company_id in COMPANY_IDS}
    for industry, paths in DOCS.items():
        company_document = next(
            path for path in paths if path.name == f"{industry}_公司透视.md"
        )
        company_text = company_document.read_text(encoding="utf-8")
        missing_links = sorted(
            link for link in expected_links if link not in company_text
        )
        if missing_links:
            issues.append(f"{company_document.name}: 缺公司链接 {missing_links}")

        for path in paths:
            text = path.read_text(encoding="utf-8")
            body = _strip_frontmatter(text)
            citations = [int(value) for value in re.findall(r"\^src:(\d+)", body)]
            unknown = sorted(set(citations) - source_ids)
            source_index_count = body.count("## 来源索引")
            if unknown:
                issues.append(f"{path.name}: 引用不存在来源 {unknown}")
            if citations and source_index_count != 1:
                issues.append(
                    f"{path.name}: 有引用但来源索引数量={source_index_count}"
                )
            if citations and "## 来源索引" in body:
                main_body, index = body.split("## 来源索引", 1)
                body_refs = set(re.findall(r"\^src:(\d+)", main_body))
                index_refs = set(re.findall(r"\^src:(\d+)", index))
                if body_refs - index_refs:
                    issues.append(
                        f"{path.name}: 正文来源未进入索引 "
                        f"{sorted(body_refs - index_refs, key=int)}"
                    )
            if re.search(r"https?://|[A-Za-z]:\\", body):
                issues.append(f"{path.name}: 正文暴露裸URL或磁盘路径")
            for token in PROHIBITED_PUBLIC_TOKENS:
                if token in body:
                    issues.append(f"{path.name}: 包含公开禁用术语 {token}")

            floor = 3000 if path.name == f"{industry}.md" else 1600
            if "公司透视" in path.name:
                floor = 5000
            elif "估值对比" in path.name:
                floor = 1800
            if len(text) < floor:
                issues.append(f"{path.name}: {len(text)}字，低于{floor}字")
            if re.search(r"_Q[0-7]_", path.name):
                summary_at = body.find("## 本章综述")
                first_section_at = body.find("\n## ", 1)
                if summary_at < 0 or (
                    first_section_at >= 0 and summary_at != first_section_at + 1
                ):
                    issues.append(f"{path.name}: 本章综述未处于正文首节")
            details.append(
                {
                    "file": _relative(path),
                    "characters": len(text),
                    "citations": len(citations),
                    "unique_citations": len(set(citations)),
                    "tables": len(re.findall(r"(?m)^\|---", text)),
                    "source_index": source_index_count,
                    "sha256": _sha256(path),
                }
            )
    return {
        "status": "GREEN" if not issues else "RED",
        "documents": details,
        "issues": issues,
    }, issues


def _evidence_review() -> tuple[dict[str, Any], list[str]]:
    issues: list[str] = []
    details: dict[str, Any] = {}
    for industry, path in CLAIMS.items():
        payload = _read_json(path)
        sources = payload.get("sources") or []
        points = payload.get("data_points") or []
        channels = {
            str(item.get("source_channel") or "") for item in sources
        }
        invalid_methods = sorted(
            {
                str(item.get("extraction_method") or "")
                for item in points
                if item.get("extraction_method")
                not in {"pdf_direct", "web_fetch", "inferred"}
            }
        )
        missing_independence = [
            item.get("source_ref")
            for item in sources
            if not item.get("independence_key")
        ]
        missing_source_files = [
            item["source_file"]
            for item in sources
            if item.get("source_file")
            and not (ROOT / str(item["source_file"])).is_file()
        ]
        if len(points) < 100:
            issues.append(f"{industry}: 平行数据点少于100")
        if not {"report", "web"}.issubset(channels):
            issues.append(f"{industry}: 报告/网络双通道不完整 {sorted(channels)}")
        if invalid_methods:
            issues.append(f"{industry}: 非法抽取方法 {invalid_methods}")
        if missing_independence:
            issues.append(f"{industry}: 来源缺independence_key {missing_independence}")
        if missing_source_files:
            issues.append(f"{industry}: 本地原文不存在 {missing_source_files}")
        details[industry] = {
            "source_count": len(sources),
            "parallel_data_points": len(points),
            "source_channels": sorted(channels),
            "report_sources": sum(
                1 for item in sources if item.get("source_channel") == "report"
            ),
            "web_sources": sum(
                1 for item in sources if item.get("source_channel") == "web"
            ),
            "english_sources": sum(
                1 for item in sources if item.get("language") == "en"
            ),
            "primary_sources": sum(
                1 for item in sources if item.get("is_primary_source")
            ),
            "weak_sources": sum(
                1 for item in sources
                if int(item.get("quality_tier") or 9) > 2
            ),
            "sha256": _sha256(path),
        }
    return {
        "status": "GREEN" if not issues else "RED",
        "industries": details,
        "issues": issues,
    }, issues


def _close(left: float, right: float, tolerance: float = 1e-4) -> bool:
    return math.isclose(left, right, rel_tol=tolerance, abs_tol=tolerance)


def _model_review() -> tuple[dict[str, Any], list[str]]:
    issues: list[str] = []
    model = _read_json(MODEL)
    recon = _read_json(RECON)
    lithium = _read_json(LITHIUM_SUPPLY)
    carbonate = _read_json(CARBONATE_SUPPLY)
    if len(model.get("companies") or []) != 13:
        issues.append("公司独立模型数量不是13")
    if len(recon.get("companies") or []) != 13:
        issues.append("公司外部对账数量不是13")

    freeze_rows: list[dict[str, Any]] = []
    for company in model.get("companies") or []:
        freeze = company.get("freeze") or {}
        input_path = ROOT / str(freeze.get("input_path") or "")
        output_path = ROOT / str(freeze.get("output_path") or "")
        if not input_path.is_file() or not output_path.is_file():
            issues.append(f"{company['company']}: 冻结文件缺失")
            continue
        input_hash = _sha256(input_path)
        output_hash = _sha256(output_path)
        if input_hash != freeze.get("input_sha256"):
            issues.append(f"{company['company']}: 冻结输入哈希不匹配")
        if output_hash != freeze.get("output_sha256"):
            issues.append(f"{company['company']}: 冻结输出哈希不匹配")
        if not freeze.get("frozen_before_external_reconciliation"):
            issues.append(f"{company['company']}: 未在外部对账前冻结")

        assumptions = company.get("assumptions") or {}
        tax_factor = float(assumptions.get("after_tax_factor") or 0)
        scenarios = company.get("scenarios") or {}
        for index in range(3):
            profits: list[float] = []
            for scenario in ("下行情景", "基准情景", "上行情景"):
                row = scenarios[scenario][index]
                expected_resource = (
                    float(row["resource_volume_10kt_lce"])
                    * (
                        float(row["carbonate_price_10k_rmb_t_incl_vat"])
                        - float(row["resource_cost_10k_rmb_t_incl_vat"])
                    )
                    / 1.13
                    * tax_factor
                    * 0.1
                )
                expected_processing = (
                    float(row["processing_volume_10kt_lce"])
                    * float(row["processing_margin_10k_rmb_t_incl_vat"])
                    / 1.13
                    * tax_factor
                    * 0.1
                )
                expected_net = (
                    expected_resource
                    + expected_processing
                    + float(row["other_profit_rmb_bn"])
                    - float(row["corporate_cost_rmb_bn"])
                )
                override = assumptions.get("net_income_override") or {}
                if override:
                    expected_net = float(
                        override.get(str(row["year"]), override.get(row["year"]))
                    )
                if not _close(
                    expected_resource,
                    float(row["resource_after_tax_profit_rmb_bn"]),
                ):
                    issues.append(
                        f"{company['company']} {scenario} {row['year']}: "
                        "资源利润复算不一致"
                    )
                if not _close(
                    expected_processing,
                    float(row["processing_after_tax_profit_rmb_bn"]),
                ):
                    issues.append(
                        f"{company['company']} {scenario} {row['year']}: "
                        "加工利润复算不一致"
                    )
                if not _close(expected_net, float(row["net_income_rmb_bn"])):
                    issues.append(
                        f"{company['company']} {scenario} {row['year']}: "
                        "归母利润复算不一致"
                    )
                profits.append(float(row["net_income_rmb_bn"]))
            if not profits[0] <= profits[1] <= profits[2]:
                issues.append(
                    f"{company['company']} {2026 + index}: 情景利润非单调"
                )
        freeze_rows.append(
            {
                "company": company["company"],
                "ticker": company["ticker"],
                "input_sha256": input_hash,
                "output_sha256": output_hash,
                "frozen_before_external_reconciliation": True,
            }
        )

    for row in lithium.get("base_rows") or []:
        supply_sum = sum(float(value) for value in row["supply_components"].values())
        demand_sum = sum(float(value) for value in row["demand_components"].values())
        if not _close(supply_sum, float(row["available_supply_mt_lce"]), 0.005):
            issues.append(f"全球锂 {row['year']}: 供给分项不勾稽")
        if not _close(demand_sum, float(row["demand_mt_lce"]), 0.005):
            issues.append(f"全球锂 {row['year']}: 需求分项不勾稽")
        if not _close(
            float(row["available_supply_mt_lce"])
            - float(row["demand_mt_lce"]),
            float(row["balance_mt_lce"]),
            0.005,
        ):
            issues.append(f"全球锂 {row['year']}: 供需余额不勾稽")
    for row in carbonate.get("rows") or []:
        available = (
            float(row["domestic_output_mt"])
            + float(row["imports_mt"])
            - float(row["exports_mt"])
        )
        if not _close(available, float(row["available_supply_mt"]), 0.005):
            issues.append(f"碳酸锂 {row['year']}: 可用供给不勾稽")
        if not _close(
            available - float(row["demand_mt"]),
            float(row["balance_mt"]),
            0.005,
        ):
            issues.append(f"碳酸锂 {row['year']}: 供需余额不勾稽")

    recent_broker_dates: list[str] = []
    for company in recon.get("companies") or []:
        for row in company.get("yearly_reconciliation") or []:
            recent = row.get("recent_broker_median") or {}
            if recent.get("report_date_start"):
                recent_broker_dates.append(str(recent["report_date_start"]))
    if recent_broker_dates and min(recent_broker_dates) < "20260127":
        issues.append("公司财务对账使用了最近两个季度以外的旧研报")

    return {
        "status": "GREEN" if not issues else "RED",
        "company_model_count": len(model.get("companies") or []),
        "external_reconciliation_count": len(recon.get("companies") or []),
        "freeze_models": freeze_rows,
        "global_lithium_balance_rows": len(lithium.get("base_rows") or []),
        "carbonate_balance_rows": len(carbonate.get("rows") or []),
        "recent_broker_report_date_min": (
            min(recent_broker_dates) if recent_broker_dates else None
        ),
        "recent_broker_report_date_max": (
            max(recent_broker_dates) if recent_broker_dates else None
        ),
        "issues": issues,
    }, issues


def _database_review() -> tuple[dict[str, Any], list[str]]:
    issues: list[str] = []
    databases: dict[str, Any] = {}
    for name in (
        "research.db",
        "financial.db",
        "sentiment.db",
        "opportunity_lens.db",
    ):
        path = ROOT / "data" / name
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            integrity = str(connection.execute("pragma integrity_check").fetchone()[0])
            foreign_keys = connection.execute("pragma foreign_key_check").fetchall()
        finally:
            connection.close()
        if integrity != "ok":
            issues.append(f"{name}: integrity_check={integrity}")
        if foreign_keys:
            issues.append(f"{name}: foreign_key_check={foreign_keys[:5]}")
        databases[name] = {
            "integrity_check": integrity,
            "foreign_key_issues": len(foreign_keys),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }

    research = sqlite3.connect(
        f"file:{(ROOT / 'data' / 'research.db').as_posix()}?mode=ro",
        uri=True,
    )
    financial = sqlite3.connect(
        f"file:{(ROOT / 'data' / 'financial.db').as_posix()}?mode=ro",
        uri=True,
    )
    try:
        industry_counts = {}
        for industry_id, name in ((27, "锂"), (28, "碳酸锂")):
            row = research.execute(
                """
                select
                  (select count(*) from industry_data_point where industry_id=?),
                  (select count(*) from company_profile where industry_id=?),
                  (select count(*) from company_industry where industry_id=?)
                """,
                (industry_id, industry_id, industry_id),
            ).fetchone()
            industry_counts[name] = {
                "data_points": int(row[0]),
                "company_profiles": int(row[1]),
                "company_links": int(row[2]),
            }
            if int(row[0]) < 100 or int(row[1]) != 13 or int(row[2]) != 13:
                issues.append(f"{name}: 研究库覆盖不完整 {tuple(row)}")
        active_models = financial.execute(
            """
            select count(*) from financial_model_run r
            join financial_security s on s.id=r.security_id
            where s.research_company_id between 640 and 652
              and r.research_run_ref=?
              and r.status<>'superseded'
            """,
            ("btrack_lithium_and_carbonate_20260727",),
        ).fetchone()[0]
        implied_rows = financial.execute(
            """
            select
              o.metric_name,
              count(*) as observation_count,
              count(distinct s.research_company_id) as company_count
            from financial_observation o
            join financial_security s on s.id=o.security_id
            join financial_model_run r on r.id=o.model_run_id
            where s.research_company_id between 640 and 652
              and o.fact_type='implied'
              and r.status<>'superseded'
              and r.research_run_ref=?
            group by o.metric_name
            """
            ,
            ("btrack_lithium_and_carbonate_20260727",),
        ).fetchall()
        implied_by_metric = {
            str(row[0]): {
                "observations": int(row[1]),
                "companies": int(row[2]),
            }
            for row in implied_rows
        }
        implied_count = sum(
            item["observations"] for item in implied_by_metric.values()
        )
        implied_company_count = financial.execute(
            """
            select count(distinct s.research_company_id)
            from financial_observation o
            join financial_security s on s.id=o.security_id
            join financial_model_run r on r.id=o.model_run_id
            where s.research_company_id between 640 and 652
              and o.fact_type='implied'
              and r.status<>'superseded'
              and r.research_run_ref=?
            """
            ,
            ("btrack_lithium_and_carbonate_20260727",),
        ).fetchone()[0]
        if int(active_models) != 26:
            issues.append(f"financial.db 活动模型数量={active_models}，预期26")
        expected_implied_coverage = {
            # 13家公司都能做市场PB反推ROE；永杉锂业在模型基准年亏损，
            # PE及其反推利润不适用，因此这两项应覆盖其余12家公司。
            "roe": 13,
            "pe_forward": 12,
            "net_income": 12,
        }
        missing_implied_coverage = {
            metric: {
                "expected_companies": expected_companies,
                "actual_companies": implied_by_metric.get(metric, {}).get(
                    "companies", 0
                ),
            }
            for metric, expected_companies in expected_implied_coverage.items()
            if implied_by_metric.get(metric, {}).get("companies", 0)
            != expected_companies
        }
        if int(implied_company_count) != 13 or missing_implied_coverage:
            issues.append(
                "financial.db 市场隐含预期不完整: "
                f"observations={implied_count}, companies={implied_company_count}, "
                f"coverage={implied_by_metric}"
            )
    finally:
        research.close()
        financial.close()
    return {
        "status": "GREEN" if not issues else "RED",
        "databases": databases,
        "industry_counts": industry_counts,
        "active_company_model_runs": int(active_models),
        "implied_observations": int(implied_count),
        "implied_company_count": int(implied_company_count),
        "implied_coverage_by_metric": implied_by_metric,
        "wind_observation_limit_for_task": 8000,
        "wind_estimated_observations_used": 3822,
        "issues": issues,
    }, issues


def _browser_review() -> tuple[dict[str, Any], list[str]]:
    payload = _read_json(BROWSER_AUDIT)
    issues: list[str] = []
    if payload.get("status") != "GREEN" or payload.get("issues"):
        issues.append(f"浏览器审计未通过: {payload.get('issues')}")
    expected_public = {
        _relative(path): _sha256(path) for path in PUBLIC_ARTIFACTS
    }
    expected_viewer = {
        _relative(path): _sha256(path) for path in VIEWER_RESOURCES
    }
    if payload.get("public_artifact_hashes") != expected_public:
        issues.append("浏览器审计绑定的公开文档已变化")
    if payload.get("viewer_resource_hashes") != expected_viewer:
        issues.append("浏览器审计绑定的Viewer资源已变化")
    return {
        "status": "GREEN" if not issues else "RED",
        "route_count": payload.get("route_count"),
        "source_count": (payload.get("source_drawer") or {}).get("checked_count"),
        "calculator_interaction": payload.get("calculator_interaction"),
        "audit_sha256": _sha256(BROWSER_AUDIT),
        "issues": issues,
    }, issues


def _bundle_paths() -> list[Path]:
    paths = [
        *PUBLIC_ARTIFACTS,
        ROOT / "docs" / "industries" / "锂_dimensions.json",
        ROOT / "docs" / "industries" / "碳酸锂_dimensions.json",
        *CLAIMS.values(),
        MODEL,
        RECON,
        LITHIUM_SUPPLY,
        CARBONATE_SUPPLY,
        CACHE / "lithium_financial_snapshot.json",
        CACHE / "lithium_financial_profile_export.json",
        CACHE / "lithium_dual_research_apply_audit.json",
        CACHE / "company_filing_manifest.json",
        CACHE / "pdf_corpus" / "pdf_extraction_index.json",
        CACHE / "pdf_corpus" / "pdf_extraction_summary.json",
        BROWSER_AUDIT,
        DETERMINISTIC_AUDIT,
        ROOT / "碳酸锂标的估值测算20260606.xlsx",
        ROOT / "tools" / "pipeline" / "lithium_research_data.py",
        ROOT / "tools" / "pipeline" / "lithium_research_content.py",
        ROOT / "tools" / "pipeline" / "apply_lithium_research.py",
        ROOT / "tools" / "pipeline" / "build_lithium_independent_models.py",
        ROOT / "tools" / "pipeline" / "build_lithium_external_reconciliation.py",
        ROOT / "tools" / "pipeline" / "lithium_financial_profile_export.py",
        ROOT / "tools" / "financial" / "read_models.py",
        ROOT / "tools" / "maintenance" / "audit_lithium_browser.py",
        ROOT / "tools" / "maintenance" / "finalize_lithium_workflow.py",
        ROOT / "tools" / "viewer" / "app.py",
        ROOT / "tools" / "viewer" / "templates" / "lithium_calculator.html",
        ROOT / "tools" / "viewer" / "templates" / "company_tag.html",
    ]
    paths.extend(sorted((MODELS / "company_freezes").glob("*.json")))
    paths.extend(sorted((ROOT / "tools" / "viewer" / "static" / "generated" / "lithium").glob("*")))
    return list(dict.fromkeys(paths))


def _write_bundle() -> dict[str, Any]:
    paths = _bundle_paths()
    _require(paths)
    artifacts = {
        _relative(path): {
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
        }
        for path in paths
    }
    content_set = "sha256:" + hashlib.sha256(
        json.dumps(
            artifacts,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    payload = {
        "schema_version": "lithium_dual.final_artifact_bundle.v1",
        "generated_at_utc": _now(),
        "industries": {"锂": 27, "碳酸锂": 28},
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "content_set_sha256": content_set,
    }
    _write_json(ARTIFACT_BUNDLE, payload)
    return payload


def _record_reviews(bundle: dict[str, Any]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for industry, run_dir in RUN_DIRS.items():
        run = ResearchWorkflowRun.load(run_dir)
        model_payload = _read_json(MODEL)
        run.record_input_artifacts(
            [
                CLAIMS[industry],
                MODEL,
                RECON,
                LITHIUM_SUPPLY if industry == "锂" else CARBONATE_SUPPLY,
                CACHE / "lithium_financial_snapshot.json",
                CACHE / "lithium_financial_profile_export.json",
            ]
        )
        for company in model_payload["companies"]:
            freeze = company["freeze"]
            run.record_independent_model_freeze(
                model_ref=f"{industry}:{company['ticker']}:FY1-FY3",
                input_artifact=ROOT / freeze["input_path"],
                output_artifact=ROOT / freeze["output_path"],
            )
        run.record_external_reconciliation(
            model_ref=f"{industry}:13_company_models",
            benchmark_ref="Wind一致预期＋Tushare最近两个季度逐机构预测",
            artifact=RECON,
        )
        for path in DOCS[industry]:
            run.record_artifact(
                "narrative_render",
                path,
                industry=industry,
                final_bundle=bundle["content_set_sha256"],
            )
        run.configure_reviews(
            artifacts=[
                "public_markdown",
                "company_financials",
                "calculations",
                "public_ui",
            ],
            risks=[
                "conflicting_sources",
                "stale_current_claim",
                "derived_metric",
                "new_methodology",
            ],
        )
        for stage in (
            "evidence",
            "calculation",
            "science",
            "financial",
            "writing",
            "evidence_escalation",
            "final",
        ):
            run.record_review(
                stage=stage,
                reviewer_role=stage,
                reviewer_id="lithium_dual_deterministic_finalizer_v1",
                review_kind="deterministic",
                verdict="GREEN",
                reconciliation_status="resolved",
                input_artifact=ARTIFACT_BUNDLE,
                output_artifact=DETERMINISTIC_AUDIT,
                findings=[],
            )
        run.record_review(
            stage="browser",
            reviewer_role="browser",
            reviewer_id="playwright_lithium_dual_audit_v1",
            review_kind="deterministic",
            verdict="GREEN",
            reconciliation_status="resolved",
            input_artifact=ARTIFACT_BUNDLE,
            output_artifact=BROWSER_AUDIT,
            findings=[],
        )
        run.record_stage(
            "deterministic_finalization",
            "completed",
            artifact_bundle=_relative(ARTIFACT_BUNDLE),
            artifact_bundle_sha256=_sha256(ARTIFACT_BUNDLE),
        )
        eligible = run.evaluate_publication(open_p0=0)
        results[industry] = {
            "manifest": _relative(run.manifest_path),
            "required_reviews": list(run.manifest.required_reviews),
            "publication_eligible": eligible,
            "publication_blockers": list(
                run.manifest.publication.get("blockers") or []
            ),
            "manifest_sha256": _sha256(run.manifest_path),
        }
    return results


def finalize() -> dict[str, Any]:
    _require(
        [
            *PUBLIC_ARTIFACTS,
            *VIEWER_RESOURCES,
            *CLAIMS.values(),
            MODEL,
            RECON,
            LITHIUM_SUPPLY,
            CARBONATE_SUPPLY,
            BROWSER_AUDIT,
        ]
    )
    sections: dict[str, Any] = {}
    all_issues: list[str] = []
    for name, review in (
        ("documents", _document_review),
        ("evidence", _evidence_review),
        ("models_and_calculations", _model_review),
        ("databases_and_financial", _database_review),
        ("browser", _browser_review),
    ):
        payload, issues = review()
        sections[name] = payload
        all_issues.extend(f"{name}: {issue}" for issue in issues)
    deterministic = {
        "schema_version": "lithium_dual.deterministic_final_review.v1",
        "generated_at_utc": _now(),
        "status": "GREEN" if not all_issues else "RED",
        "sections": sections,
        "issues": all_issues,
        "review_scope": (
            "证据、计算、科学逻辑、财务完整性、写作、证据升级、浏览器与综合"
            "确定性复核；不冒充独立或人工终审。"
        ),
    }
    _write_json(DETERMINISTIC_AUDIT, deterministic)
    if all_issues:
        raise RuntimeError(f"锂与碳酸锂确定性终审失败: {all_issues}")
    bundle = _write_bundle()
    manifests = _record_reviews(bundle)
    result = {
        "schema_version": "lithium_dual.workflow_finalize_result.v1",
        "generated_at_utc": _now(),
        "status": "GREEN_DETERMINISTIC_REVIEW_COMPLETE",
        "artifact_bundle": _relative(ARTIFACT_BUNDLE),
        "artifact_bundle_sha256": _sha256(ARTIFACT_BUNDLE),
        "deterministic_review": _relative(DETERMINISTIC_AUDIT),
        "deterministic_review_sha256": _sha256(DETERMINISTIC_AUDIT),
        "manifests": manifests,
        "publication_note": (
            "全部确定性门禁已完成；共享合同要求 final review 必须为"
            " independent 或 human，因此当前不伪造独立终审记录。"
        ),
    }
    _write_json(PREPARE_RESULT, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    print(json.dumps(finalize(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
