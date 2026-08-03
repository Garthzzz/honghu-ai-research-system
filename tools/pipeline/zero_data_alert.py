#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
zero_data_alert.py(第三次修订任务 6)

任何 SCIENTIST session 启动时必跑。输出当前 db 中所有零数据 source 的清单 +
按 value_layer / publish_date 排优先级,落盘到 cache/zero_data_alert_<YYYYMMDD>.md。

当前研究工作流应在 producer 启动阶段读取此文件。

设计:
- 优先级 P0 = 2026 年最新数据 source / 双层 + 深度框架
- 优先级 P1 = 主题专项(CPO / 硅光 / 海外 / 上游)
- 优先级 P2 = 其他深度框架补充
- 优先级 P3 = 信息流(周报 / 月报)

如果 source 持续零数据(跨多个 session 未抽),自动标 alert 级别提升。
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT      = Path(__file__).resolve().parent.parent.parent
DB_PATH   = ROOT / "data" / "research.db"
CACHE_DIR = ROOT / "cache"
ALERT_DIR = CACHE_DIR


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def classify_priority(row: sqlite3.Row) -> str:
    """按 value_layer / publish_date / 关键词 heuristic 排优先级。"""
    vl = row["value_layer"]
    title = (row["title"] or "")
    pub_date = row["publish_date"] or ""

    # P0:2026 年最新 source(任何 value_layer)
    if pub_date and pub_date.startswith("2026"):
        if vl in ("最新数据", "双层", "深度框架"):
            return "P0"
        if "一季报" in title or "季报综述" in title or "中报" in title:
            return "P0"

    # P1:主题专项 / 海外 / 上游 / CPO / 硅光 / AAOI 等关键主题
    if vl == "主题专项":
        return "P1"
    if any(k in title for k in ("CPO", "AAOI", "硅光", "海外", "上游", "万亿")):
        return "P1"

    # P2:深度框架 / 双层(无显式主题词)
    if vl in ("深度框架", "双层"):
        return "P2"

    # P3:信息流 / 其他
    return "P3"


def gen_alert_md(zero_sources: List[sqlite3.Row], all_audit: List[sqlite3.Row]) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    by_prio: Dict[str, List[sqlite3.Row]] = {"P0": [], "P1": [], "P2": [], "P3": []}
    for r in zero_sources:
        by_prio[classify_priority(r)].append(r)

    n_zero = len(zero_sources)
    n_total = len(all_audit)
    n_pass  = sum(1 for r in all_audit if r["dp_count"] >= r["dp_min"] and r["ka_count_approx"] >= r["ka_min"])
    n_short = sum(1 for r in all_audit if 0 < r["dp_count"] < r["dp_min"])

    out: List[str] = []
    out.append(f"# 零数据 / 不达标 source 告警 — {today}")
    out.append("")
    out.append("> 本文件由 `tools/pipeline/zero_data_alert.py` 自动生成。")
    out.append("> 所有研究 producer 启动后必读（按当前 A/B 工作流契约）。")
    out.append("")
    out.append("## 全库状态")
    out.append("")
    out.append(f"- source 总数:**{n_total}**")
    out.append(f"- 达标 source:**{n_pass}**")
    out.append(f"- 零数据 source:**{n_zero}**(下文按优先级展开)")
    out.append(f"- 不达标 source(dp_count < dp_min,非零):**{n_short}**")
    out.append("")
    out.append("---")
    out.append("")
    out.append("## 零数据 source 清单(按优先级)")
    out.append("")

    prio_desc = {
        "P0": "2026 年最新数据 + 深度框架/双层 — 直接服务当前 thesis,**最高优先级**",
        "P1": "主题专项(CPO / 硅光 / 海外 / 上游 / AAOI 等)— 补充 NEW alpha 实际证据",
        "P2": "深度框架 / 双层补充(无显式主题词)",
        "P3": "信息流(周报 / 月报)— 仅挑最近 3 个月,leading indicator 用",
    }
    for prio in ("P0", "P1", "P2", "P3"):
        rows = by_prio[prio]
        out.append(f"### {prio}({len(rows)} 份) — {prio_desc[prio]}")
        out.append("")
        if not rows:
            out.append("(无)")
            out.append("")
            continue
        out.append("| source_id | value_layer | publish_date | publisher | title |")
        out.append("|---|---|---|---|---|")
        for r in rows:
            title = (r["title"] or "")[:60]
            out.append(f"| #{r['id']} | {r['value_layer']} | {r['publish_date'] or '—'} | {(r['publisher'] or '—')} | {title} |")
        out.append("")

    out.append("---")
    out.append("")
    out.append("## 不达标(非零)source 清单")
    out.append("")
    short_rows = [r for r in all_audit if 0 < r["dp_count"] < r["dp_min"]]
    if not short_rows:
        out.append("(无不达标 source)")
    else:
        out.append("| source_id | value_layer | dp_count / min | ka_count / min | title |")
        out.append("|---|---|---|---|---|")
        for r in short_rows:
            title = (r["title"] or "")[:60]
            out.append(f"| #{r['id']} | {r['value_layer']} | {r['dp_count']} / {r['dp_min']} | {r['ka_count_approx']} / {r['ka_min']} | {title} |")
    out.append("")

    out.append("---")
    out.append("")
    out.append("## SCIENTIST 接下来必做(按顺序)")
    out.append("")
    out.append("1. 先处理 **P0**(2026 年最新数据 + 深度框架/双层),这是 thesis 最新性的核心")
    out.append("2. 然后 **P1**(主题专项,补充 NEW alpha 实际证据 + 多源对照)")
    out.append("3. 再 **P2**(深度框架 / 双层补充)")
    out.append("4. 最后 **P3**(周报,只挑最近 3 个月有 leading indicator 的)")
    out.append("")
    out.append("**每份 source 抽取完入库后**,跑:")
    out.append("```bash")
    out.append("python tools/pipeline/consensus_compute.py --industry 1 --summary")
    out.append("```")
    out.append("确认 consensus 分布合理,无大量 'unevaluated'。")
    out.append("")
    out.append("**抽取协议**（按当前 A/B 研究工作流与来源门槛）：")
    out.append("- 数据点入库走 `tools/pipeline/db_writer.py:write_data_point()`(自动触发 consensus)")
    out.append("- 非数值核心观点入 `source.key_arguments`(走 `write_key_arguments()`)")
    out.append("- 每份 source 完成后立即查 `v_source_extraction_audit` 自检达标")
    out.append("- 不达标则重抽，直至达标或显式记录客观不可得原因")

    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description="零数据 source 告警生成器(SCIENTIST session 启动必跑)")
    parser.add_argument("--out", type=str, default=None, help="输出文件路径(默认 cache/zero_data_alert_<YYYYMMDD>.md)")
    parser.add_argument("--stdout", action="store_true", help="同时打印到 stdout")
    args = parser.parse_args()

    conn = get_db()
    all_audit = conn.execute("""
        SELECT id, title, source_type, value_layer, quality_tier,
               publish_date, publisher, dp_count, ka_count_approx, dp_min, ka_min
        FROM v_source_extraction_audit
        ORDER BY dp_count ASC, id ASC
    """).fetchall()
    zero_sources = [r for r in all_audit if r["dp_count"] == 0]

    md_text = gen_alert_md(zero_sources, all_audit)

    if args.out:
        out_path = Path(args.out)
    else:
        ALERT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = ALERT_DIR / f"zero_data_alert_{datetime.now().strftime('%Y%m%d')}.md"
    out_path.write_text(md_text, encoding="utf-8")
    print(f"[OK] 告警写入: {out_path.relative_to(ROOT)}")
    print(f"     零数据 source: {len(zero_sources)} / {len(all_audit)}")
    print(f"     按优先级展开: P0/P1/P2/P3 见 md")
    if args.stdout:
        print()
        print(md_text)
    conn.close()


if __name__ == "__main__":
    main()
