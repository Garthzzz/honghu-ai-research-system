#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""T10:把已入库 senti_post 的时间从'最后更新'修正为'原帖发布时间'(post_id 前14位时间戳),
并补 time_caliber 口径列。重算聚合。只写 sentiment.db。幂等。"""
from __future__ import annotations
import sys, re
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common
from senti_aggregate import recompute_company

_PIDTS = re.compile(r"^(20\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})")


def main():
    con = common.get_senti_db()
    common.assert_senti_only(con)
    try:
        con.execute("ALTER TABLE senti_post ADD COLUMN time_caliber TEXT")
    except Exception:
        pass
    rows = con.execute("SELECT id, post_id FROM senti_post").fetchall()
    fixed = lu = 0
    for r in rows:
        m = _PIDTS.match(str(r["post_id"]))
        if m:
            yr, mo, da, hh, mm, ss = (int(g) for g in m.groups())
            if not (1 <= mo <= 12 and 1 <= da <= 31 and 0 <= hh <= 23 and 0 <= mm <= 59):
                continue
            ts_hour = f"{yr:04d}-{mo:02d}-{da:02d}T{hh:02d}:00"
            td = f"{yr:04d}-{mo:02d}-{da:02d}"
            posted = f"{yr:04d}-{mo:02d}-{da:02d}T{hh:02d}:{mm:02d}+08:00"
            con.execute("UPDATE senti_post SET ts_hour=?, trade_date=?, posted_at=?, time_caliber='post_time' WHERE id=?",
                        (ts_hour, td, posted, r["id"]))
            fixed += 1
        else:
            con.execute("UPDATE senti_post SET time_caliber='last_update' WHERE id=?", (r["id"],))
            lu += 1
    con.commit()
    # 重算全部公司聚合(时间桶变了)
    now = common.now_iso()
    for cid in [x[0] for x in con.execute("SELECT DISTINCT company_id FROM senti_post")]:
        recompute_company(con, cid, now)
    con.commit()
    nb = con.execute("SELECT COUNT(*) FROM senti_post WHERE trade_date NOT GLOB '[0-9][0-9][0-9][0-9]-[01][0-9]-[0-3][0-9]'").fetchone()[0]
    print(f"=== T10 时间修正:原帖时间 {fixed} 帖 / 最后更新口径 {lu} 帖 | 非法日期 {nb}(应0)===")
    con.close()


if __name__ == "__main__":
    main()
