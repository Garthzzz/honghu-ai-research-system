#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Stage 3-H P1.2 migration 007 — industry 表 v2 生效(8 → 10),user 决策已定

决策:光芯片(2)/光器件(4)→合并到光模块(1);电芯片(3)→新"芯片";封装设备(5)→新"半导体";
      删 2/3/4/5;数通交换机(6)→改名"交换机";新增 9-14。
现有引用实测:仅 industry_relation.upstream_id 有 4 条引用 2/3/4/5(无 idp/cp/source_entity 引用)。
不动 idp/cp/news/voice/event 行数据(news/voice tag 由 P1.4 重分类生成 id;event JSON 仅含 1/7/8 不变)。
"""
import sqlite3, sys
from pathlib import Path
from datetime import datetime
DB = Path(__file__).resolve().parent.parent.parent / "data" / "research.db"
NOW = datetime.now().isoformat(timespec="seconds")

NEW = [(9, "芯片"), (10, "半导体"), (11, "云服务器厂商"), (12, "液冷散热"), (13, "电力"), (14, "AI应用")]
REPOINT = {2: 1, 4: 1, 3: 9, 5: 10}   # 旧 id → 合并目标

def main():
    con = sqlite3.connect(str(DB)); cur = con.cursor()
    before = cur.execute("SELECT COUNT(*) FROM industry").fetchone()[0]
    # 1. 新增 6 行(level=1, tier=2 基础跟踪)
    for iid, name in NEW:
        cur.execute("""INSERT OR IGNORE INTO industry(id,name,level,tier,status,created_at,last_updated)
                       VALUES(?,?,1,2,'基础跟踪',?,?)""", (iid, name, NOW, NOW[:10]))
    # 2. industry_relation:先删"重指向后会变自环"的边(CHECK upstream!=downstream),再重指向
    for old, new in REPOINT.items():
        cur.execute("DELETE FROM industry_relation WHERE (upstream_id=? AND downstream_id=?) OR (upstream_id=? AND downstream_id=?)",
                    (old, new, new, old))
    for old, new in REPOINT.items():
        cur.execute("UPDATE industry_relation SET upstream_id=? WHERE upstream_id=?", (new, old))
        cur.execute("UPDATE industry_relation SET downstream_id=? WHERE downstream_id=?", (new, old))
    # 3. 其他表防御性重指向(实测为 0,但保险)
    for tbl, col in [("industry_data_point","industry_id"),("company_profile","industry_id"),
                     ("company_industry","industry_id"),("theme_industry","industry_id"),
                     ("data_point_peer_group","industry_id"),("company_sub_market_share","industry_id")]:
        for old, new in REPOINT.items():
            try: cur.execute(f"UPDATE {tbl} SET {col}=? WHERE {col}=?", (new, old))
            except Exception: pass
    for old, new in REPOINT.items():
        cur.execute("UPDATE source_entity SET entity_id=? WHERE entity_type='industry' AND entity_id=?", (str(new), str(old)))
    # 4. 改名 6 → 交换机
    cur.execute("UPDATE industry SET name='交换机' WHERE id=6")
    # 5. 删旧 2/3/4/5
    cur.execute("DELETE FROM industry WHERE id IN (2,3,4,5)")
    con.commit()
    # 验收
    rows = cur.execute("SELECT id,name FROM industry ORDER BY id").fetchall()
    print(f"industry: {before} → {len(rows)} 行")
    for r in rows: print(f"  id={r[0]:<3} {r[1]}")
    # dangling FK 检查
    dang = 0
    for tbl, col in [("industry_data_point","industry_id"),("company_profile","industry_id"),
                     ("industry_relation","upstream_id"),("industry_relation","downstream_id")]:
        d = cur.execute(f"SELECT COUNT(*) FROM {tbl} WHERE {col} NOT IN (SELECT id FROM industry) AND {col} IS NOT NULL").fetchone()[0]
        if d: print(f"  ?? dangling {tbl}.{col}: {d}"); dang += d
    print("dangling FK:", dang, "(应 0)")
    assert len(rows) == 10, "应 10 行"
    con.close()
    print("MIGRATION 007 DONE")

if __name__ == "__main__":
    main()
