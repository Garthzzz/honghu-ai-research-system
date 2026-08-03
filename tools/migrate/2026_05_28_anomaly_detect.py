"""光模块 db 异常值检测(R1-3).

对每个 peer group (industry × metric × as_of_date × is_forecast),
找出 max/min > 10 倍的组(数量级错误)。
"""
import sys, sqlite3
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

conn = sqlite3.connect('data/research.db')
conn.row_factory = sqlite3.Row

print('=== 光模块 peer group 数量级异常(max/min > 10)===\n')
rows = list(conn.execute('''
SELECT metric, as_of_date, is_forecast, COUNT(*) n,
       MIN(value_num) mn, MAX(value_num) mx,
       GROUP_CONCAT(id) ids,
       GROUP_CONCAT(value_num) vals,
       GROUP_CONCAT(unit) units
FROM industry_data_point
WHERE industry_id=1 AND value_num IS NOT NULL AND value_num > 0
GROUP BY metric, COALESCE(as_of_date, period), is_forecast
HAVING COUNT(*) >= 2 AND MIN(value_num) > 0 AND MAX(value_num)/MIN(value_num) > 10
ORDER BY (MAX(value_num)/MIN(value_num)) DESC
'''))

for r in rows:
    ratio = r['mx'] / r['mn']
    print(f'### {r["metric"]} @ {r["as_of_date"]} fc={r["is_forecast"]}')
    print(f'  n={r["n"]} min={r["mn"]} max={r["mx"]} ratio={ratio:.1f}×')
    ids = r['ids'].split(',')
    vals = r['vals'].split(',')
    units = r['units'].split(',')
    for i, v, u in zip(ids, vals, units):
        # 拿 note + source
        d = conn.execute(f'SELECT note, source_id, source_excerpt FROM industry_data_point WHERE id={i}').fetchone()
        print(f'    #{i:>4s} {v:>10s}{u:8s} src={d["source_id"]} note={(d["note"] or "")[:60]}')
    print()

conn.close()
print(f'\n=== 总异常组: {len(rows)} ===')
