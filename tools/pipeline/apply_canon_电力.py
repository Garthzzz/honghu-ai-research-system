#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""应用 electric metric/period 规范化映射 + 重算 consensus + 门1 自检。

只改 metric/period/as_of_date(=canonical period,因 consensus 用 as_of_date 分组)/is_forecast,
不动 value_num/value_text/source_id/source_excerpt/company_id(原值留存于 电力_dp_dump.json)。
"""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools" / "pipeline"))
import db_writer, consensus_compute

IND = 13
canon = json.loads((ROOT / "cache" / "db_queue" / "电力_metric_canon.json").read_text(encoding="utf-8"))
conn = db_writer.get_db()

n = 0
for c in canon:
    did = c["id"]; metric = c["metric"].strip(); period = str(c["period"]).strip()
    isf = 1 if c.get("is_forecast") else 0
    r = conn.execute("SELECT industry_id FROM industry_data_point WHERE id=?", (did,)).fetchone()
    if not r or r["industry_id"] != IND:
        continue
    # as_of_date 设为 canonical period,使 consensus 分组键 = metric+period
    conn.execute("UPDATE industry_data_point SET metric=?, period=?, as_of_date=?, is_forecast=? WHERE id=?",
                 (metric, period, period, isf, did))
    n += 1
conn.commit()
print(f"规范化应用: {n} 条 dp 更新 metric/period/as_of_date/is_forecast")

# 重算 consensus(全行业)
try:
    consensus_compute.recompute_all(IND, conn=conn)
except Exception as e:
    print(f"[WARN] recompute_all 失败,退回逐 metric:{e}", file=sys.stderr)
    for (m,) in conn.execute("SELECT DISTINCT metric FROM industry_data_point WHERE industry_id=?", (IND,)).fetchall():
        try: consensus_compute.recompute_metric(IND, m, conn=conn)
        except Exception as e2: print(f"  metric={m} 失败 {e2}", file=sys.stderr)
conn.commit()

# 自检
dist = dict(conn.execute("SELECT consensus_status, COUNT(*) FROM industry_data_point WHERE industry_id=? GROUP BY consensus_status", (IND,)).fetchall())
print("\n=== #13 consensus 分布(规范化后)===")
for k in ("共识", "主流", "次主流", "孤证", "离群", "unevaluated"):
    print(f"  {k}: {dist.get(k, 0)}")
multi = conn.execute("""SELECT metric, period, COUNT(DISTINCT source_id) c, COUNT(*) n
    FROM industry_data_point WHERE industry_id=? GROUP BY metric, period HAVING c>=2 ORDER BY c DESC, n DESC""", (IND,)).fetchall()
print(f"\n多源同指标同期 组数: {len(multi)}")
for g in multi[:15]:
    members = conn.execute("""SELECT source_id, value_num, consensus_status FROM industry_data_point
        WHERE industry_id=? AND metric=? AND period=? AND value_num IS NOT NULL""", (IND, g["metric"], g["period"])).fetchall()
    vals = ", ".join(f"src{m['source_id']}:{m['value_num']}({m['consensus_status']})" for m in members)
    print(f"  [{g['c']}源] {g['metric']} · {g['period']} → {vals}")

mainstream = dist.get("主流", 0) + dist.get("次主流", 0)
print(f"\n?? 门1 判定: 主流+次主流 = {mainstream}")
print("门1: " + ("PASS ??(>0 主流/次主流,consensus 生效)" if mainstream > 0 else "FAIL ??(仍 0,规范化无效 → HALT)"))
conn.close()
