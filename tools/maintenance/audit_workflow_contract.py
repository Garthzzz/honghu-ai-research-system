from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.opportunity_lens.constants import (
    DB_PATH as OPPORTUNITY_DB_PATH,
    RESEARCH_WORKFLOW_CONTRACT_VERSION,
    RUN_PACK_SCHEMA_VERSION,
    SCHEMA_VERSION,
)
from tools.opportunity_lens.migrate import REQUIRED_COLUMNS, REQUIRED_TABLES
from tools.research_core.config import load_workflow_config, resolve_track_config


ACTIVE_TEXT_FILES = (
    "AGENTS.md",
    "config/research_workflow.yaml",
    "docs/research/RESEARCH_WORKFLOW_V2.md",
    "docs/research/ACTIVE_FILE_AUTHORITY.md",
    "codex_context/LIVE_STATE.md",
    "codex_context/PROJECT_COMPLETE_UNDERSTANDING.md",
    "codex_context/FILE_DB_INDEX.md",
    "opportunity_lens/MODULE_CONTEXT.md",
    "opportunity_lens/HUMAN_READABILITY_STANDARD.md",
    "STANDARD_行研流程_20260609.md",
    "FRAMEWORK_双轨行研_20260628.md",
    "STANDARD_PROMPT驱动行研_20260628.md",
    "CHECKLIST_新行业接入_20260628.md",
    "templates/数据呈现与重写标准.md",
    "skills/README.md",
    "skills/通用基础层/adaptive-research-workflow/SKILL.md",
    "skills/通用基础层/fresh-session-bootstrap/SKILL.md",
    "skills/通用基础层/verifier-protocol/SKILL.md",
    "skills/通用基础层/continuous-execution/SKILL.md",
    "skills/通用基础层/phase-handoff-protocol/SKILL.md",
    "skills/通用基础层/progress-logging/SKILL.md",
    "skills/工程层/parallel-subagent-orchestration/SKILL.md",
    "skills/工程层/session-reporting/SKILL.md",
    "skills/研究层/conducting-literature-review/SKILL.md",
    "skills/行研专用层/source-quality-tier/SKILL.md",
    "skills/行研专用层/claim-extraction-from-source/SKILL.md",
    "skills/行研专用层/industry-md-template/SKILL.md",
    "审核代理/verifier-domain-research.md",
)

FORBIDDEN_ACTIVE_PATTERNS = {
    "legacy_stage_name": re.compile(
        r"science_logic|writing_and_citation|calculation_recompute|"
        r"financial_completeness|browser_dom_visual"
    ),
    "broken_placeholder": re.compile(r"\?\?"),
    "old_workflow_contract": re.compile(r"research\.workflow\.v1(?!\d)"),
}

RUNTIME_INTEGRATION_MARKERS = {
    "tools/pipeline/ingest_research.py": (
        "ResearchWorkflowRun.start(",
        "ContentAddressedCache(",
        "run.configure_reviews(",
        "run.record_requirement_coverage(",
        "run.record_gate(\"contract\"",
        "run.record_gate(\"evidence_integrity\"",
        "run.record_gate(\"provenance\"",
        "run.record_gate(\"duplication\"",
        "run.record_gate(\"scope_and_units\"",
    ),
    "tools/opportunity_lens/manual_run_loader.py": (
        "ContentAddressedCache(",
        "build_pack_workflow_state(",
        '"research_brief"',
        '"research_execution_manifest"',
    ),
    "tools/opportunity_lens/workflow_bridge.py": (
        "compile_research_brief(",
        "ExecutionManifest(",
        "manifest.set_review_plan(",
        "manifest.record_requirement_coverage(",
    ),
    "tools/research_core/config.py": (
        "_load_workflow_config_cached",
        "stat.st_mtime_ns",
        "deepcopy(data)",
    ),
}


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")')}


def audit_workflow(root: Path = ROOT, opportunity_db: Path = OPPORTUNITY_DB_PATH) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    config = load_workflow_config(root / "config" / "research_workflow.yaml")
    if config["contract_version"] != RESEARCH_WORKFLOW_CONTRACT_VERSION:
        findings.append({"code": "workflow_version_mismatch", "severity": "RED"})
    if resolve_track_config("c")["pack_schema_version"] != RUN_PACK_SCHEMA_VERSION:
        findings.append({"code": "pack_version_mismatch", "severity": "RED"})

    canonical_stages = set(config["common"]["review"]["canonical_review_stages"])
    required_c_stages = set(config["tracks"]["c"]["publish_requires_review_records"])
    if not required_c_stages <= canonical_stages:
        findings.append({
            "code": "unknown_required_review_stage",
            "severity": "RED",
            "detail": sorted(required_c_stages - canonical_stages),
        })

    for relative in ACTIVE_TEXT_FILES:
        path = root / relative
        if not path.is_file():
            findings.append({"code": "active_file_missing", "severity": "RED", "path": relative})
            continue
        text = path.read_text(encoding="utf-8")
        for code, pattern in FORBIDDEN_ACTIVE_PATTERNS.items():
            if pattern.search(text):
                findings.append({"code": code, "severity": "RED", "path": relative})

    for relative, markers in RUNTIME_INTEGRATION_MARKERS.items():
        path = root / relative
        if not path.is_file():
            findings.append({"code": "runtime_integration_file_missing", "severity": "RED", "path": relative})
            continue
        source = path.read_text(encoding="utf-8")
        for marker in markers:
            if marker not in source:
                findings.append({
                    "code": "runtime_integration_marker_missing",
                    "severity": "RED",
                    "path": relative,
                    "marker": marker,
                })

    cache_consumers = []
    for path in (root / "tools").rglob("*.py"):
        if path.name in {
            "content_cache.py",
            "audit_workflow_contract.py",
            "benchmark_research_workflow.py",
        } or "secrets" in path.parts:
            continue
        if "ContentAddressedCache(" in path.read_text(encoding="utf-8", errors="ignore"):
            cache_consumers.append(str(path.relative_to(root)))
    if len(cache_consumers) < 2:
        findings.append({
            "code": "content_cache_not_wired_to_ab_and_c",
            "severity": "RED",
            "consumers": sorted(cache_consumers),
        })

    requirements = (root / "requirements.txt").read_text(encoding="utf-8").lower()
    # Wind 通过项目根目录 WindPy.py 对接固定内网 HTTP 代理，不依赖 PyPI
    # ``windpy`` 包；Akshare 仍是禁止的新数据源依赖。
    for dependency in ("akshare",):
        active_lines = [
            line.strip()
            for line in requirements.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        if any(line.split("=")[0].split(">")[0].strip() == dependency for line in active_lines):
            findings.append({"code": "disabled_dependency", "severity": "RED", "dependency": dependency})

    direct_insert = re.compile(r"INSERT\s+INTO\s+industry_data_point", flags=re.IGNORECASE)
    for path in (root / "tools").rglob("*.py"):
        if path.name == "db_writer.py" or "secrets" in path.parts:
            continue
        if direct_insert.search(path.read_text(encoding="utf-8", errors="ignore")):
            findings.append({
                "code": "direct_industry_data_point_insert",
                "severity": "RED",
                "path": str(path.relative_to(root)),
            })

    if not opportunity_db.is_file():
        findings.append({"code": "opportunity_db_missing", "severity": "RED", "path": str(opportunity_db)})
    else:
        uri = f"file:{opportunity_db.resolve().as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        try:
            row = conn.execute(
                "SELECT value FROM opportunity_schema_meta WHERE key='schema_version'"
            ).fetchone()
            if not row or row[0] != SCHEMA_VERSION:
                findings.append({
                    "code": "live_schema_version_mismatch",
                    "severity": "RED",
                    "expected": SCHEMA_VERSION,
                    "actual": row[0] if row else None,
                })
            live_tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            missing_tables = sorted(REQUIRED_TABLES - live_tables)
            if missing_tables:
                findings.append({
                    "code": "live_schema_tables_missing",
                    "severity": "RED",
                    "tables": missing_tables,
                })
            for table, expected in REQUIRED_COLUMNS.items():
                if table not in live_tables:
                    continue
                missing = sorted(expected - _columns(conn, table))
                if missing:
                    findings.append({
                        "code": "live_schema_columns_missing",
                        "severity": "RED",
                        "table": table,
                        "columns": missing,
                    })
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                findings.append({"code": "sqlite_integrity", "severity": "RED", "detail": integrity})
            fk = conn.execute("PRAGMA foreign_key_check").fetchall()
            if fk:
                findings.append({"code": "sqlite_foreign_key", "severity": "RED", "count": len(fk)})
        finally:
            conn.close()

    return {
        "passed": not any(item["severity"] == "RED" for item in findings),
        "workflow_contract_version": config["contract_version"],
        "run_pack_schema_version": RUN_PACK_SCHEMA_VERSION,
        "opportunity_schema_version": SCHEMA_VERSION,
        "active_file_count": len(ACTIVE_TEXT_FILES),
        "runtime_integration_file_count": len(RUNTIME_INTEGRATION_MARKERS),
        "content_cache_consumers": sorted(cache_consumers),
        "findings": findings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="只读审计 A/B/C V2 工作流契约一致性")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--opportunity-db", type=Path, default=OPPORTUNITY_DB_PATH)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit_workflow(args.root, args.opportunity_db)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
