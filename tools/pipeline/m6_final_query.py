"""M6 final state query"""
import sqlite3, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
conn = sqlite3.connect('data/research.db')
conn.row_factory = sqlite3.Row

print('=== M6 Final State ===\n')
print('1. 各 industry × extraction_method:')
for r in conn.execute("""
SELECT i.name, d.extraction_method, COUNT(*) c FROM industry_data_point d
JOIN industry i ON d.industry_id = i.id
GROUP BY i.name, d.extraction_method ORDER BY i.id, c DESC
"""):
    print(f'  {r[0]:8s} {r[1]:18s}: {r[2]}')

print('\n2. 各 industry 高质量 dp (pdf_direct + web_fetch, peer_count >= 3):')
for r in conn.execute("""
SELECT i.name, COUNT(*) c FROM industry_data_point d
JOIN industry i ON d.industry_id = i.id
WHERE d.extraction_method IN ('pdf_direct', 'web_fetch') AND d.peer_count >= 3
GROUP BY i.name ORDER BY c DESC
"""):
    print(f'  {r[0]:8s}: {r[1]}')

print('\n3. demo 时光模块可信展示 dp 数 (extraction_method=pdf_direct):')
r = conn.execute("SELECT COUNT(*) FROM industry_data_point WHERE industry_id=1 AND extraction_method='pdf_direct'").fetchone()
print(f'  光模块 pdf_direct: {r[0]}')

print('\n4. 整体 viewer 在 "原文" 筛选下的 dp 总数:')
r = conn.execute("SELECT COUNT(*) FROM industry_data_point WHERE extraction_method='pdf_direct'").fetchone()
print(f'  pdf_direct 全库: {r[0]}')

print('\n5. demo 可信弹药盘点 (user 验证 query):')
header_fmt = '  {:10s} {:^5s} {:10s} {:>6s} {:>5s} {:>7s} {:>5s} {:>6s}'
row_fmt    = '  {:10s} {:^5} {:10s} {:>6} {:>5} {:>7} {:>5} {:>6}'
print(header_fmt.format('industry', 'tier', 'status', '原文', '网搜', '模板估', '未标', '合计'))
for r in conn.execute("""
SELECT i.name, i.tier, i.status,
  SUM(CASE WHEN d.extraction_method='pdf_direct' THEN 1 ELSE 0 END) AS pdf_direct,
  SUM(CASE WHEN d.extraction_method='web_fetch' THEN 1 ELSE 0 END) AS web_fetch,
  SUM(CASE WHEN d.extraction_method='template_estimate' THEN 1 ELSE 0 END) AS template_estimate,
  SUM(CASE WHEN d.extraction_method='unknown' THEN 1 ELSE 0 END) AS unknown,
  COUNT(d.id) AS total
FROM industry i LEFT JOIN industry_data_point d ON i.id=d.industry_id
WHERE i.status IN ('深度跟踪', '仅记录')
GROUP BY i.id ORDER BY i.tier
"""):
    print(row_fmt.format(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7]))
conn.close()
