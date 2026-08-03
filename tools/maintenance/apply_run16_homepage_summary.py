"""Synchronize Run16's four homepage question summaries from its frozen pack.

Read-only by default. ``--apply`` changes only ``section_title`` and
``body_markdown`` for the four run-level report sections; entity research,
sources, models, portfolios and review records are not rewritten.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from pathlib import Path

from tools.opportunity_lens.run_pack_contract import public_markdown_character_count


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data/opportunity_lens.db"
PACK_PATH = ROOT / "opportunity_lens/research_outputs/20260801_ai_app_full_chain_portfolio_run16/run16_pack_stage.json"
RUN_ID = 16
SECTION_KEYS = ("summary", "core_research_map", "portfolio_overview", "risk_overview")


def _sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_pack() -> tuple[dict[str, dict[str, str]], dict[str, dict[str, object]]]:
    pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
    sections = {
        str(row["section_key"]): {
            "title": str(row["section_title"]),
            "body": str(row["body_markdown"]),
        }
        for row in pack["sections"]
    }
    if tuple(sections) != SECTION_KEYS:
        raise RuntimeError(f"Run16 首页 section 顺序或集合异常：{tuple(sections)}")
    if any(row["title"] == "摘要" for row in sections.values()):
        raise RuntimeError("Run16 pack 仍含冗余的‘摘要’标题")
    lengths = {
        key: public_markdown_character_count(row["body"])
        for key, row in sections.items()
    }
    invalid = {key: n for key, n in lengths.items() if not 200 <= n <= 600}
    if invalid:
        raise RuntimeError(f"Run16 首页问题摘要不在200—600字：{invalid}")
    sources = {str(row["ref"]): row for row in pack["sources"]}
    return sections, sources


def _resolve_source_refs(
    conn: sqlite3.Connection,
    sections: dict[str, dict[str, str]],
    sources: dict[str, dict[str, object]],
) -> None:
    used_refs = {
        ref
        for row in sections.values()
        for ref in re.findall(r"source_ref:([A-Za-z0-9_.-]+)", row["body"])
    }
    resolved: dict[str, int] = {}
    for ref in sorted(used_refs):
        source = sources.get(ref)
        if not source:
            raise RuntimeError(f"pack 中不存在正文 source_ref：{ref}")
        rows = conn.execute(
            """SELECT id FROM opportunity_source
                WHERE run_id=? AND title=? AND COALESCE(publisher,'')=COALESCE(?,'')""",
            (RUN_ID, source.get("title"), source.get("publisher")),
        ).fetchall()
        if len(rows) != 1:
            raise RuntimeError(f"source_ref 未唯一解析：{ref}，命中{len(rows)}条")
        resolved[ref] = int(rows[0]["id"])
    for row in sections.values():
        row["body"] = re.sub(
            r"source_ref:([A-Za-z0-9_.-]+)",
            lambda match: str(resolved[match.group(1)]),
            row["body"],
        )
        if "source_ref:" in row["body"]:
            raise RuntimeError("正文仍含未解析 source_ref")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    sections, sources = _load_pack()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        _resolve_source_refs(conn, sections, sources)
        run = conn.execute(
            "SELECT id,display_title,run_readiness_status FROM opportunity_run WHERE id=?",
            (RUN_ID,),
        ).fetchone()
        if not run or run["display_title"] != "AI应用与全产业链组合研究":
            raise RuntimeError("run_id=16 身份不匹配")
        rows = conn.execute(
            """SELECT id,section_key,section_title,body_markdown
                 FROM opportunity_report_section
                WHERE run_id=? AND entity_id IS NULL ORDER BY sort_order,id""",
            (RUN_ID,),
        ).fetchall()
        if tuple(row["section_key"] for row in rows) != SECTION_KEYS:
            raise RuntimeError("live Run16 首页 section 集合或顺序异常")
        changes = []
        for row in rows:
            target = sections[row["section_key"]]
            changes.append(
                {
                    "id": row["id"],
                    "section_key": row["section_key"],
                    "old_title": row["section_title"],
                    "new_title": target["title"],
                    "old_hash": _sha(row["body_markdown"]),
                    "new_hash": _sha(target["body"]),
                    "visible_characters": public_markdown_character_count(target["body"]),
                    "changed": row["section_title"] != target["title"] or row["body_markdown"] != target["body"],
                }
            )
        if args.apply:
            conn.execute("BEGIN IMMEDIATE")
            for row in rows:
                target = sections[row["section_key"]]
                conn.execute(
                    "UPDATE opportunity_report_section SET section_title=?,body_markdown=? WHERE id=?",
                    (target["title"], target["body"], row["id"]),
                )
            conn.execute("UPDATE opportunity_run SET updated_at=datetime('now') WHERE id=?", (RUN_ID,))
            if conn.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("foreign_key_check 未通过")
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("integrity_check 未通过")
            conn.commit()
        print(json.dumps({"mode": "apply" if args.apply else "dry_run", "run_id": RUN_ID, "changes": changes}, ensure_ascii=False, indent=2))
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
