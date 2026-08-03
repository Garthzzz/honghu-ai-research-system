#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Stage 2c-G migration 003 - 对齐当时的 canonical schema；历史协议已归档。

任务 4(??重做)要求 industry_thesis 用 **散文式** consensus_narrative + consensus_overridden_by_human,
而非我先前的 consensus_view(数字罗列摘要 = 命令明确指出的"错误理解")。

本迁移:
1. industry_thesis 重建为 canonical 列名:
   consensus_narrative / consensus_source_ids / consensus_generated_at /
   consensus_overridden_by_human / contrarian_thesis / monitoring_signals / conviction_level / author / updated_at
   - 保留旧行的 user 字段(contrarian/monitoring/conviction/author);
   - consensus_narrative 留空(降级:等 Anthropic API token,先 pending);旧 consensus_view 数字摘要丢弃。
2. company_thesis:删除纯 AI 数字摘要行(consensus_view 有值但无任何 user 内容)——
   canonical 公司 thesis 不含 AI 一致预期(那是行业级散文)。保留含 user 内容的行。
"""
import sqlite3
from pathlib import Path
DB = Path(__file__).resolve().parent.parent.parent / "data" / "research.db"

NEW_IT = """
CREATE TABLE industry_thesis_new (
  id                            INTEGER PRIMARY KEY,
  industry_id                   INTEGER NOT NULL UNIQUE,
  consensus_narrative           TEXT,             -- ?? AI 散文式综合分析(走势+原因+数据串联)
  consensus_source_ids          TEXT,             -- JSON 溯源
  consensus_generated_at        TEXT,
  consensus_overridden_by_human INTEGER DEFAULT 0,
  contrarian_thesis             TEXT,
  monitoring_signals            TEXT,
  conviction_level              INTEGER,
  author                        TEXT DEFAULT 'zhengze',
  updated_at                    TEXT DEFAULT (datetime('now','localtime'))
);
"""

def main():
    con = sqlite3.connect(str(DB)); cur = con.cursor()
    cols = {r[1] for r in cur.execute("PRAGMA table_info(industry_thesis)")}
    if "consensus_narrative" in cols:
        print("industry_thesis 已是 canonical,跳过重建")
    else:
        cur.executescript(NEW_IT)
        # 迁移旧行:保留 user 字段;consensus_narrative 留空(降级 pending)
        old = cur.execute("""SELECT industry_id, contrarian_thesis, monitoring_signals,
                                    conviction_level, author, updated_at
                             FROM industry_thesis""").fetchall()
        for iid, contra, mon, conv, author, upd in old:
            cur.execute("""INSERT INTO industry_thesis_new(industry_id, consensus_narrative,
                           consensus_overridden_by_human, contrarian_thesis, monitoring_signals,
                           conviction_level, author, updated_at)
                           VALUES(?, NULL, 0, ?,?,?,?,?)""",
                        (iid, contra, mon, conv, (author or 'zhengze'), upd))
        cur.execute("DROP TABLE industry_thesis")
        cur.execute("ALTER TABLE industry_thesis_new RENAME TO industry_thesis")
        print(f"industry_thesis 重建完成,迁移 {len(old)} 行(consensus_narrative 留空=pending)")

    # company_thesis:删纯 AI 摘要行(无 user 内容)
    deleted = cur.execute("""DELETE FROM company_thesis
        WHERE (consensus_view IS NOT NULL AND TRIM(consensus_view)<>'')
          AND (contrarian_thesis IS NULL OR TRIM(contrarian_thesis)='')
          AND (monitoring_signals IS NULL OR TRIM(monitoring_signals)='')""").rowcount
    con.commit()
    print(f"company_thesis 删除纯 AI 摘要行:{deleted}")
    it_cols = [r[1] for r in cur.execute("PRAGMA table_info(industry_thesis)")]
    print("industry_thesis 列:", it_cols)
    print("industry_thesis 行:", cur.execute("SELECT COUNT(*) FROM industry_thesis").fetchone()[0])
    print("company_thesis 行:", cur.execute("SELECT COUNT(*) FROM company_thesis").fetchone()[0])
    con.close()
    print("MIGRATION 003 DONE")

if __name__ == "__main__":
    main()
