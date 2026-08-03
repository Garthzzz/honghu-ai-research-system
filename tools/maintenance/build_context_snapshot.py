from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.opportunity_lens.constants import RUN_PACK_SCHEMA_VERSION, SCHEMA_VERSION  # noqa: E402
from tools.research_core.config import contract_version  # noqa: E402

DEFAULT_MD = ROOT / "codex_context" / "LIVE_STATE.md"
DEFAULT_JSON = ROOT / "cache" / "context" / "live_state.json"


def _connect_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _db_summary(path: Path, count_tables: list[str]) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path.relative_to(ROOT)), "exists": False}
    conn = _connect_readonly(path)
    try:
        counts = {}
        existing = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in count_tables:
            if table in existing:
                counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        return {
            "path": str(path.relative_to(ROOT)),
            "exists": True,
            "bytes": path.stat().st_size,
            "tables": int(conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]),
            "views": int(conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='view'").fetchone()[0]),
            "triggers": int(conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'").fetchone()[0]),
            "row_counts": counts,
        }
    finally:
        conn.close()


def collect() -> dict[str, Any]:
    research = ROOT / "data" / "research.db"
    opportunity = ROOT / "data" / "opportunity_lens.db"
    state = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "workflow_contract_version": contract_version(),
        "expected_opportunity_schema_version": SCHEMA_VERSION,
        "expected_run_pack_schema_version": RUN_PACK_SCHEMA_VERSION,
        "databases": {
            "research": _db_summary(research, ["industry", "source", "industry_data_point", "company", "company_profile", "news_item", "voice_post", "event"]),
            "sentiment": _db_summary(ROOT / "data" / "sentiment.db", ["senti_raw", "senti_post", "stock_kline", "recruit_job", "event_item"]),
            "financial": _db_summary(ROOT / "data" / "financial.db", ["financial_security", "financial_observation", "financial_model_run", "financial_reconciliation"]),
            "opportunity_lens": _db_summary(opportunity, ["opportunity_run", "opportunity_source", "opportunity_data_point", "opportunity_entity", "opportunity_factor_score", "opportunity_entity_investment_target", "opportunity_agent_review_log", "opportunity_quality_gate_result"]),
        },
        "industries": [],
        "opportunity_runs": [],
        "filesystem": {
            "industry_markdown_files": len(list((ROOT / "docs" / "industries").glob("*.md"))),
            "opportunity_intake_requests": len(list((ROOT / "opportunity_lens" / "intake_requests").glob("*.md"))),
            "opportunity_run_packs": len(list((ROOT / "opportunity_lens" / "research_outputs").glob("*/run_pack.json"))),
        },
    }
    if research.exists():
        conn = _connect_readonly(research)
        try:
            state["industries"] = [dict(row) for row in conn.execute(
                """
                SELECT i.id,i.name,i.status,
                       (SELECT COUNT(*) FROM industry_data_point d WHERE d.industry_id=i.id) AS data_points,
                       (SELECT COUNT(*) FROM company_industry ci WHERE ci.industry_id=i.id) AS companies
                FROM industry i ORDER BY i.id
                """
            )]
        finally:
            conn.close()
    if opportunity.exists():
        conn = _connect_readonly(opportunity)
        try:
            tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            review_expr = (
                "(SELECT COUNT(*) FROM opportunity_agent_review_log l WHERE l.run_id=r.id)"
                if "opportunity_agent_review_log" in tables else "0"
            )
            gate_expr = (
                "(SELECT COUNT(*) FROM opportunity_quality_gate_result g WHERE g.run_id=r.id)"
                if "opportunity_quality_gate_result" in tables else "0"
            )
            state["opportunity_runs"] = [dict(row) for row in conn.execute(
                f"""
                SELECT r.id,r.research_question,r.run_status,r.run_readiness_status,r.evidence_policy,
                       {review_expr} AS review_logs,
                       {gate_expr} AS quality_gates
                FROM opportunity_run r ORDER BY r.id
                """
            )]
            if "opportunity_schema_meta" in tables:
                keys = (
                    "schema_version",
                    "research_workflow_contract_version",
                    "run_pack_schema_version",
                )
                placeholders = ",".join("?" for _ in keys)
                state["opportunity_versions"] = {
                    row["key"]: row["value"]
                    for row in conn.execute(
                        f"SELECT key,value FROM opportunity_schema_meta WHERE key IN ({placeholders})",
                        keys,
                    )
                }
        finally:
            conn.close()
    return state


def render_markdown(state: dict[str, Any]) -> str:
    lines = [
        "# Live State",
        "",
        f"生成时间：`{state['generated_at']}`  ",
        f"工作流契约：`{state['workflow_contract_version']}`",
        f"C 轨 schema：`{state.get('opportunity_versions', {}).get('schema_version', '不可得')}`；run pack：`{state.get('opportunity_versions', {}).get('run_pack_schema_version', '不可得')}`",
        "",
        "> 本文件由只读脚本 `tools/maintenance/build_context_snapshot.py` 生成。数字是快照，不是永久事实；执行具体任务前仍应查询相关 live 对象。",
        "",
        "## 数据库",
        "",
        "| 数据库 | tables | views | triggers | 大小字节 |",
        "|---|---:|---:|---:|---:|",
    ]
    for summary in state["databases"].values():
        lines.append(
            f"| `{summary['path']}` | {summary.get('tables','-')} | {summary.get('views','-')} | "
            f"{summary.get('triggers','-')} | {summary.get('bytes','-')} |"
        )
    lines.extend(["", "关键行数：", ""])
    for name, summary in state["databases"].items():
        values = "，".join(f"`{table}`={count}" for table, count in summary.get("row_counts", {}).items())
        lines.append(f"- {name}：{values or '数据库不存在'}")

    lines.extend([
        "",
        "## 行业",
        "",
        "| id | 行业 | 状态 | 数据点 | 公司关联 |",
        "|---:|---|---|---:|---:|",
    ])
    for row in state["industries"]:
        lines.append(f"| {row['id']} | {row['name']} | {row['status']} | {row['data_points']} | {row['companies']} |")

    lines.extend([
        "",
        "## Opportunity Lens",
        "",
        "| run | 研究问题 | process | readiness | policy | reviewer log | quality gate |",
        "|---:|---|---|---|---|---:|---:|",
    ])
    for row in state["opportunity_runs"]:
        question = str(row.get("research_question") or "").replace("|", "\\|")
        lines.append(
            f"| {row['id']} | {question} | {row['run_status']} | {row['run_readiness_status']} | "
            f"{row['evidence_policy']} | {row.get('review_logs',0)} | {row.get('quality_gates',0)} |"
        )

    fs = state["filesystem"]
    lines.extend([
        "",
        "## 文件快照",
        "",
        f"- 行业 Markdown：{fs['industry_markdown_files']}",
        f"- Opportunity Lens intake request：{fs['opportunity_intake_requests']}",
        f"- Opportunity Lens run pack：{fs['opportunity_run_packs']}",
        "",
        "## 实现边界",
        "",
        "- A/B 行研写 `research.db`；结构化公司财务、市场快照、一致预期和模型账本写 `financial.db`；情绪、招聘、K 线和供应链情绪写 `sentiment.db`；C 轨写 `opportunity_lens.db`。",
        "- C 轨仍没有通用真实 crawler 和真实 PDF renderer。",
        "- 端口 8080 是会话状态，本快照不永久声称服务在线。",
        "- 历史 run 的 published 状态不自动等于存在 V2 reviewer log；表中 reviewer log 数量是直接证据。",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="只读生成项目 live context 快照。")
    parser.add_argument("--output", default=str(DEFAULT_MD))
    parser.add_argument("--json-output", default=str(DEFAULT_JSON))
    args = parser.parse_args()
    state = collect()
    md_path = Path(args.output)
    json_path = Path(args.json_output)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_markdown(state), encoding="utf-8")
    json_path.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    print(f"live context 已生成: {md_path}")


if __name__ == "__main__":
    main()
