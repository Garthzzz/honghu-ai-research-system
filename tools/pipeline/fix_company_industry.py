#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""问题1:company_industry 去重 + 唯一索引 + 从 dp 回填 + 计数对齐。
- 备份 → 按 (company_id,industry_id) 去重(非空 role/revenue_share/note 合并入 keeper)→
  建 UNIQUE(company_id,industry_id) → 回填所有行业(从 dp 的 distinct company_id,缺链补)。
- 不动 company / industry_data_point 的任何实质数据。
"""
from __future__ import annotations
import sqlite3, sys, json
from datetime import datetime
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent.parent
DB = ROOT / "data" / "research.db"
BK = ROOT / "cache" / "backup"; BK.mkdir(parents=True, exist_ok=True)
TS = datetime.now().strftime("%Y%m%d_%H%M%S")


def counts(con):
    out = {}
    for iid, nm in con.execute("SELECT id,name FROM industry").fetchall():
        cir = con.execute("SELECT COUNT(*) FROM company_industry WHERE industry_id=?", (iid,)).fetchone()[0]
        cid = con.execute("SELECT COUNT(DISTINCT company_id) FROM company_industry WHERE industry_id=?", (iid,)).fetchone()[0]
        dpd = con.execute("SELECT COUNT(DISTINCT company_id) FROM industry_data_point WHERE industry_id=? AND company_id IS NOT NULL", (iid,)).fetchone()[0]
        if cir or dpd:
            out[iid] = (nm, cir, cid, dpd)
    return out


def main():
    con = sqlite3.connect(str(DB)); con.row_factory = sqlite3.Row
    # 1. 备份
    rows = [dict(r) for r in con.execute("SELECT * FROM company_industry")]
    bkpath = BK / f"company_industry_{TS}.json"
    bkpath.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[备份] {len(rows)} 行 → {bkpath.relative_to(ROOT)}")

    before = counts(con)
    n_before = con.execute("SELECT COUNT(*) FROM company_industry").fetchone()[0]
    dup_pairs = con.execute("SELECT COUNT(*) FROM (SELECT 1 FROM company_industry GROUP BY company_id,industry_id HAVING COUNT(*)>1)").fetchone()[0]
    print(f"[改前] 总行 {n_before} | 重复对 {dup_pairs}")

    # 2. 去重(合并非空字段入 keeper=min id)
    deleted = 0
    groups = con.execute("""SELECT company_id,industry_id, COUNT(*) c, MIN(id) keep
                            FROM company_industry GROUP BY company_id,industry_id HAVING c>1""").fetchall()
    for g in groups:
        sibs = con.execute("SELECT id,role,revenue_share,note FROM company_industry WHERE company_id=? AND industry_id=? ORDER BY id",
                           (g["company_id"], g["industry_id"])).fetchall()
        keep = g["keep"]
        role = next((s["role"] for s in sibs if s["role"]), None)
        rev = next((s["revenue_share"] for s in sibs if s["revenue_share"] is not None), None)
        note = next((s["note"] for s in sibs if s["note"]), None)
        con.execute("UPDATE company_industry SET role=?, revenue_share=?, note=? WHERE id=?", (role, rev, note, keep))
        for s in sibs:
            if s["id"] != keep:
                con.execute("DELETE FROM company_industry WHERE id=?", (s["id"],)); deleted += 1
    con.commit()
    print(f"[去重] 删除 {deleted} 行(每对留 min id,合并非空字段)")

    # 3. 唯一索引
    con.execute("DROP INDEX IF EXISTS uq_company_industry")
    con.execute("CREATE UNIQUE INDEX uq_company_industry ON company_industry(company_id, industry_id)")
    con.commit()
    print("[索引] 建 UNIQUE uq_company_industry(company_id,industry_id)")

    # 4. 回填所有行业(从 dp distinct company_id,缺链补;OR IGNORE 靠新索引去重)
    print("[回填] 各行业从 dp 补缺链:")
    for iid, nm in con.execute("SELECT id,name FROM industry").fetchall():
        dp_comps = [r[0] for r in con.execute(
            "SELECT DISTINCT company_id FROM industry_data_point WHERE industry_id=? AND company_id IS NOT NULL", (iid,)).fetchall()]
        added = 0
        for cid in dp_comps:
            r = con.execute("INSERT OR IGNORE INTO company_industry(company_id,industry_id,role) VALUES(?,?,?)",
                            (cid, iid, "from_dp"))
            added += r.rowcount
        if added:
            print(f"  #{iid} {nm}: 回填 {added}")
    con.commit()

    # 5. 验收
    after = counts(con)
    n_after = con.execute("SELECT COUNT(*) FROM company_industry").fetchone()[0]
    resid = con.execute("SELECT COUNT(*) FROM (SELECT 1 FROM company_industry GROUP BY company_id,industry_id HAVING COUNT(*)>1)").fetchone()[0]
    print(f"\n[改后] 总行 {n_after} | 残留重复对 {resid}")
    print("\n=== 逐行业 ci_distinct vs dp_distinct 对齐表 ===")
    print("iid | name | 改前ci行 | 改后ci_distinct | dp_distinct | 对齐")
    for iid in sorted(set(before) | set(after)):
        nb = before.get(iid, ("?", 0, 0, 0)); na = after.get(iid, (nb[0], 0, 0, 0))
        ok = "??" if na[2] >= na[3] and na[2] >= nb[2] else "??"
        print(f"  {iid:<3} {na[0]:<8} {nb[1]:>4} → {na[2]:>4} (distinct) | dp {na[3]:>4} | {ok}")
    con.close()
    print("\nDONE")


if __name__ == "__main__":
    main()
