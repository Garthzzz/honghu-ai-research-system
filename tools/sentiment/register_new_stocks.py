#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""T4 新股注册（只写 sentiment.db，绝不写 research.db）。

- 新股先进入 ``senti_company``；ticker 未知时留空，绝不把公司名伪装成 ticker。
- 只有已验证的 A 股 ticker 才进入 ``company_alias``。未知 ticker 的公司暂不参与
  自动归因，待身份核验后由 V2 alias sync 接管。
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common
from migrate_retail_windows_v2 import IDENTITY_REDIRECTS, VERIFIED_SENTI_COMPANIES

ROOT = Path(__file__).resolve().parent.parent.parent
NEW_ID_BASE = 900001


VERIFIED_A_SHARE_TICKER = re.compile(r"^\d{6}\.(?:SZ|SH|BJ)$", re.IGNORECASE)


def register_stocks(con, now):
    data = json.loads((ROOT / "cache" / "_t1_universe.json").read_text(encoding="utf-8"))
    new_names = data["new_outside"]
    n_co, n_alias = 0, 0
    verified = {item.company_id: item for item in VERIFIED_SENTI_COMPANIES}
    redirected = {item.old_company_id for item in IDENTITY_REDIRECTS}
    has_redirect_table = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='company_id_redirect'"
    ).fetchone()
    for i, name in enumerate(new_names):
        cid = NEW_ID_BASE + i
        identity = verified.get(cid)
        if identity and identity.name != name:
            raise ValueError(
                f"新股缓存顺序与已验证身份冲突: {cid} {name!r} != {identity.name!r}"
            )
        if has_redirect_table and cid in redirected and con.execute(
            "SELECT 1 FROM company_id_redirect WHERE old_company_id=?", (cid,)
        ).fetchone():
            # 已归并到 canonical research company，绝不重新创建 duplicate。
            con.execute("DELETE FROM company_alias WHERE company_id=?", (cid,))
            continue
        verified_ticker = identity.ticker if identity else None
        cur = con.execute("""INSERT INTO senti_company(id,name,ticker,industry,created_at,note)
            VALUES(?,?,?,?,?,?) ON CONFLICT(name) DO NOTHING""",
            (
                cid,
                name,
                verified_ticker,
                None,
                now,
                "Tushare stock_basic 精确名称核验" if verified_ticker else "ticker待核验",
            ))
        if cur.rowcount:
            n_co += 1
        # 取实际 id/ticker；历史 ticker=name 污染也在下次显式运行时清除。
        row = con.execute("SELECT id,ticker FROM senti_company WHERE name=?", (name,)).fetchone()
        rid, ticker = int(row[0]), str(verified_ticker or row[1] or "").strip().upper()
        if verified_ticker:
            con.execute("UPDATE senti_company SET ticker=? WHERE id=?", (ticker, rid))
        if not VERIFIED_A_SHARE_TICKER.fullmatch(ticker):
            con.execute("UPDATE senti_company SET ticker=NULL WHERE id=?", (rid,))
            con.execute("DELETE FROM company_alias WHERE company_id=?", (rid,))
            continue
        for alias, alias_type in ((name, "name"), (ticker, "ticker"), (ticker[:6], "code")):
            cur2 = con.execute(
                """INSERT INTO company_alias(company_id,ticker,alias,alias_type)
                   VALUES(?,?,?,?)
                   ON CONFLICT(company_id,alias) DO UPDATE SET
                     ticker=excluded.ticker,alias_type=excluded.alias_type""",
                (rid, ticker, alias, alias_type),
            )
            n_alias += max(cur2.rowcount, 0)
    return n_co, n_alias


def main():
    con = common.get_senti_db()
    common.assert_senti_only(con)
    now = common.now_iso()
    n_co, n_alias = register_stocks(con, now)
    con.commit()
    tot_co = con.execute("SELECT COUNT(*) FROM senti_company").fetchone()[0]
    print(f"新股注册:本次新增 {n_co} 家(senti_company 共 {tot_co})；已验证别名写入 {n_alias} 条")
    con.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
