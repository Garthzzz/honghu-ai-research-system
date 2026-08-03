#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""通用:应用 metric/period 规范化映射 + 单位拆分 + 重算 consensus + 门2 自检。
用法:python apply_canon.py --industry-id N --canon cache/db_queue/<tag>_metric_canon.json
只改 metric/period/as_of_date(=period)/is_forecast,不动 value/source/excerpt。
"""
from __future__ import annotations
import json, sys, argparse
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools" / "pipeline"))
import db_writer, consensus_compute


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--industry-id", type=int, required=True)
    ap.add_argument("--canon", required=True)
    args = ap.parse_args()
    IND = args.industry_id
    conn = db_writer.get_db()
    canon = json.loads(Path(args.canon).read_text(encoding="utf-8"))
    n = 0
    for c in canon:
        did = c["id"]
        r = conn.execute("SELECT industry_id FROM industry_data_point WHERE id=?", (did,)).fetchone()
        if not r or r["industry_id"] != IND: continue
        metric = c["metric"].strip(); period = str(c["period"]).strip()
        isf = 1 if c.get("is_forecast") else 0
        conn.execute("UPDATE industry_data_point SET metric=?, period=?, as_of_date=?, is_forecast=? WHERE id=?",
                     (metric, period, period, isf, did))
        n += 1
    conn.commit()
    # 单位拆分
    bad = conn.execute("""SELECT metric,period FROM industry_data_point WHERE industry_id=?
        GROUP BY metric,period HAVING COUNT(DISTINCT unit)>1""", (IND,)).fetchall()
    split = 0
    for b in bad:
        for r in conn.execute("SELECT id,unit FROM industry_data_point WHERE industry_id=? AND metric=? AND period=?",
                              (IND, b["metric"], b["period"])).fetchall():
            conn.execute("UPDATE industry_data_point SET metric=? WHERE id=?", (f"{b['metric']}·{r['unit']}", r["id"]))
            split += 1
    conn.commit()
    consensus_compute.recompute_all(IND, conn=conn); conn.commit()

    dist = dict(conn.execute("SELECT consensus_status,COUNT(*) FROM industry_data_point WHERE industry_id=? GROUP BY consensus_status", (IND,)).fetchall())
    print(f"应用规范化 {n} 条 + 单位拆分 {split} 条")
    print("consensus:", {k: dist.get(k, 0) for k in ("共识","主流","次主流","孤证","离群","unevaluated")})
    multi = conn.execute("""SELECT metric,period,COUNT(DISTINCT source_id) c FROM industry_data_point WHERE industry_id=?
        GROUP BY metric,period HAVING c>=2 ORDER BY c DESC""", (IND,)).fetchall()
    print(f"多源同指标同期组数: {len(multi)} | 前8:", [f"{g['metric']}·{g['period']}({g['c']}源)" for g in multi[:8]])
    left = conn.execute("SELECT COUNT(*) FROM (SELECT 1 FROM industry_data_point WHERE industry_id=? GROUP BY metric,period HAVING COUNT(DISTINCT unit)>1)", (IND,)).fetchone()[0]
    print("剩余混合单位组(应0):", left)
    # dangling 检查
    dang = conn.execute("""SELECT COUNT(*) FROM industry_data_point dp LEFT JOIN source s ON s.id=dp.source_id
        WHERE dp.industry_id=? AND s.id IS NULL""", (IND,)).fetchone()[0]
    ms = dist.get("主流", 0) + dist.get("次主流", 0)
    print(f"dangling source_id: {dang} | 主流+次主流: {ms}")
    print("?? 门2: " + ("PASS ??" if (ms > 0 and dang == 0) else f"FAIL ?? (主流+次主流={ms}, dangling={dang})"))
    conn.close()


if __name__ == "__main__":
    main()
