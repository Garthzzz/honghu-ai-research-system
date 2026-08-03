#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
增量更新机制 — incremental_update.py(任务 6 骨架)

用途:
  行研更新快(月/季度级别)。不可能每次新增几份 source 就重跑完整 5-step pipeline。
  本脚本扫描 papers/<industry>/ 下的新文件(db source 表未入库的),列差异,
  让后续 SCIENTIST session 只处理新 source。

设计:
  1. 不重读旧 source(白名单跳过)
  2. 不重写 Q0-Q5 完整 md
  3. 不重跑 adversarial review(除非用户显式 --force-adv)
  4. 不触发 thesis 重审(除非 KPI 阈值触发)

调用:
  python tools/pipeline/incremental_update.py --industry <id> [--dry-run]

dry-run 模式:
  - 只扫描 + 列差异 + 反查 md_section_version
  - 不写 db
  - viewer 的 /refresh/<industry_id> 默认走 dry-run

实际抽取:
  - 本脚本不自动调用 LLM 抽取 claim；生产与审查由当前工作流分离
  - dry-run 输出给 user,user 开 fresh SCIENTIST session 接力做实际 claim 抽取
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# Windows 控制台默认 cp936,强制 stdout/stderr UTF-8 以便正确显示中文。
# Python 3.7+ 支持 .reconfigure()。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 不依赖 viewer/app 模块,独立运行
ROOT       = Path(__file__).resolve().parent.parent.parent
DB_PATH    = ROOT / "data" / "research.db"
DOCS_DIR   = ROOT / "docs"
PAPERS_DIR = ROOT / "papers"
CACHE_DIR  = ROOT / "cache"
INC_DIR    = CACHE_DIR / "incremental"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.pipeline.paper_paths import normalize_new_paper_file


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_industry(conn: sqlite3.Connection, industry_id: int) -> Optional[sqlite3.Row]:
    cur = conn.execute("SELECT * FROM industry WHERE id=?", (industry_id,))
    return cur.fetchone()


def scan_papers_for(industry_name: str) -> List[str]:
    """扫描 papers/<industry>/ 目录,返回所有 file (相对 papers/ 的 POSIX 路径)。"""
    sub = PAPERS_DIR / industry_name
    if not sub.exists():
        return []
    out: List[str] = []
    for p in sorted(sub.rglob("*")):
        if p.is_file() and not p.name.startswith("."):
            rel = p.relative_to(PAPERS_DIR)
            out.append(str(rel).replace("\\", "/"))
    return out


def get_indexed_file_paths(conn: sqlite3.Connection) -> Set[str]:
    """db 中 source.file_path 全集,统一为相对 papers/ 的 POSIX 形式。"""
    indexed: Set[str] = set()
    cur = conn.execute("SELECT file_path FROM source WHERE file_path IS NOT NULL AND file_path != ''")
    for row in cur.fetchall():
        fp = (row["file_path"] or "").replace("\\", "/").lstrip("/")
        if fp.startswith("papers/"):
            fp = fp[len("papers/"):]
        indexed.add(fp)
    return indexed


def find_new_files(industry_name: str, conn: sqlite3.Connection) -> List[str]:
    """papers/<industry>/ 内但 db source 表未入库的文件。"""
    in_papers = scan_papers_for(industry_name)
    indexed = get_indexed_file_paths(conn)
    normalized: List[str] = []
    for relative in in_papers:
        if relative in indexed:
            continue
        source = PAPERS_DIR / Path(relative)
        safe = normalize_new_paper_file(source, project_root=ROOT)
        normalized.append(safe.relative_to(PAPERS_DIR).as_posix())
    return normalized


def get_industry_metrics(conn: sqlite3.Connection, industry_id: int) -> List[str]:
    """该 industry 已有的 metric 集合(供反查 md_section_version 用)。"""
    cur = conn.execute(
        "SELECT DISTINCT metric FROM industry_data_point WHERE industry_id=?",
        (industry_id,),
    )
    return [r["metric"] for r in cur.fetchall()]


def find_pending_sections(
    conn: sqlite3.Connection,
    industry_name: str,
    triggered_metrics: List[str],
) -> List[sqlite3.Row]:
    """反查 md_section_version:若 section 涉及的 metric 与 triggered_metrics 有交集,
    则标 review_pending(实际 dry-run 不写,只列出 candidate)。
    """
    path_like = f"%/industries/{industry_name}%"
    cur = conn.execute(
        "SELECT * FROM md_section_version WHERE md_path LIKE ?",
        (path_like,),
    )
    candidates = cur.fetchall()
    if not triggered_metrics:
        return []
    triggered_set = set(triggered_metrics)
    hits: List[sqlite3.Row] = []
    for row in candidates:
        raw = row["metrics_covered"] or "[]"
        try:
            cov = json.loads(raw)
            if isinstance(cov, list) and any(m in triggered_set for m in cov):
                hits.append(row)
        except Exception:
            continue
    return hits


def write_diff_report(
    industry_id: int,
    industry_name: str,
    new_files: List[str],
    pending_hits: List[sqlite3.Row],
    snapshot_state: Dict,
    dry_run: bool,
) -> Path:
    """把扫描结果落盘到 cache/incremental/<date>_diff.md,供 user review。"""
    INC_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = INC_DIR / f"{ts}_industry{industry_id}_{industry_name}_diff.md"

    lines: List[str] = []
    lines.append(f"# 增量扫描差异报告 — {industry_name}")
    lines.append("")
    lines.append(f"- 时间: {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"- 行业: id={industry_id} name={industry_name}")
    lines.append(f"- 模式: {'dry-run(未写库)' if dry_run else '实写'}")
    lines.append(f"- 当前 source 总数: {snapshot_state.get('source_count', 0)}")
    lines.append(f"- 当前 data_point 总数: {snapshot_state.get('data_point_count', 0)}")
    lines.append("")

    lines.append("## 新增 source 文件(papers/ 内但 db 未入库)")
    lines.append("")
    if new_files:
        for f in new_files:
            lines.append(f"- `papers/{f}`")
    else:
        lines.append("(无新文件)")
    lines.append("")

    lines.append("## 可能受影响的 md 章节(由历史 metric 反查)")
    lines.append("")
    if pending_hits:
        for h in pending_hits:
            lines.append(f"- `{h['md_path']}` {h['section_anchor'] or ''} — last_updated={h['last_updated']}")
            if h["summary"]:
                lines.append(f"  - {h['summary']}")
    else:
        lines.append("(暂无反查命中。新 source 入库后,若触及与现有 section 相同的 metric,会自动标 review_pending=1。)")
    lines.append("")

    lines.append("## 下一步操作建议")
    lines.append("")
    if new_files:
        lines.append("1. 开 fresh SCIENTIST session,任务限定:**只处理上面列出的新 source 文件**")
        lines.append("2. 按 source 的 value_layer 走对应抽取协议(深度框架/最新数据/双层/公司专项/主题专项/信息流)")
        lines.append("3. 抽出的 claim / data_point 入 db,自动反查 md_section_version 命中的 section 标 review_pending=1")
        lines.append("4. user review 后,再开 SCIENTIST session 只更新指定 section")
    else:
        lines.append("- papers/ 内无新文件,无需操作。可考虑通过 Claude web search 主动下载新 source 到 `papers/<industry>/auto_downloaded/` 后再扫描。")
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def write_snapshot(
    conn: sqlite3.Connection,
    industry_id: int,
    new_files: List[str],
    note: str,
) -> int:
    """写 source_snapshot 行(实际入库时调用)。dry-run 不调用。"""
    cur = conn.execute("SELECT COUNT(*) AS n FROM source WHERE id IN (SELECT source_id FROM source_entity WHERE entity_type='industry' AND entity_id=?)", (str(industry_id),))
    src_count = cur.fetchone()["n"]
    cur = conn.execute("SELECT COUNT(*) AS n FROM industry_data_point WHERE industry_id=?", (industry_id,))
    dp_count = cur.fetchone()["n"]
    snap_date = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute(
        "INSERT INTO source_snapshot (snapshot_date, industry_id, source_count, data_point_count, new_source_ids, note) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (snap_date, industry_id, src_count, dp_count, json.dumps([]), note),
    )
    conn.commit()
    return cur.lastrowid


def main() -> int:
    parser = argparse.ArgumentParser(description="增量更新机制 — 扫描 papers/ 下未入库 source")
    parser.add_argument("--industry", type=int, required=True, help="industry.id")
    parser.add_argument("--dry-run", action="store_true", default=False, help="只扫描不写库(默认从 viewer 触发)")
    parser.add_argument("--note", type=str, default="", help="本次扫描的备注(实写模式记入 source_snapshot)")
    args = parser.parse_args()

    conn = get_db()
    ind = get_industry(conn, args.industry)
    if not ind:
        print(f"[FAIL] industry id={args.industry} 不存在", file=sys.stderr)
        return 2

    industry_name = ind["name"]
    print(f"[INFO] 增量扫描 industry id={args.industry} name={industry_name}")
    print(f"[INFO] 模式: {'dry-run' if args.dry_run else '实写'}")

    new_files = find_new_files(industry_name, conn)
    print(f"[INFO] 检测到新文件: {len(new_files)} 个")
    for f in new_files:
        print(f"       + papers/{f}")

    triggered_metrics = get_industry_metrics(conn, args.industry)
    pending_hits = find_pending_sections(conn, industry_name, triggered_metrics)
    print(f"[INFO] 可能受影响的 md 章节: {len(pending_hits)} 个")
    for h in pending_hits:
        print(f"       ~ {h['md_path']} {h['section_anchor'] or ''}")

    src_count = conn.execute(
        "SELECT COUNT(*) AS n FROM source_entity WHERE entity_type='industry' AND entity_id=?",
        (str(args.industry),),
    ).fetchone()["n"]
    dp_count = conn.execute(
        "SELECT COUNT(*) AS n FROM industry_data_point WHERE industry_id=?",
        (args.industry,),
    ).fetchone()["n"]

    diff_path = write_diff_report(
        args.industry, industry_name, new_files, pending_hits,
        {"source_count": src_count, "data_point_count": dp_count},
        args.dry_run,
    )
    print(f"[INFO] 差异报告已写入: {diff_path.relative_to(ROOT)}")

    if not args.dry_run:
        snap_id = write_snapshot(conn, args.industry, new_files, args.note or "incremental_update.py 扫描")
        print(f"[INFO] 快照已记录: source_snapshot.snapshot_id={snap_id}")
    else:
        print(f"[INFO] dry-run 模式,未写 db。")

    conn.close()
    print(f"[DONE] 增量扫描完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
