"""光模块 db unit 标准化迁移(R1-2).

规则:
1. 出货量类合并到 metric='全行业出货量(M units)' / unit='百万只':
   - "万只" → ÷100 转 "百万只"
   - "千只" → ÷1000 转 "百万只"
   - "百万只" 保持
   - "百万通道" 不属于"只"语义,保留原 metric/unit(放回原 metric)
2. TAM_USD:
   - "百万美元" → ÷100 转 "亿美元"
   - "亿元"币种不同 → 移到新 metric 'TAM_CNY' / unit '亿元'(等 viewer 区分币种)
   - "亿美元" 保持
3. 其他 unit 文字归一:
   - CPO容量:T → Tbps
   - 中国厂商前十席位数:席/10 → 席
   - 光引擎数:"个 6.4Tbps Davisson DR 光引擎" → "个";colors → 颗(不动)
   - 单产品端口数:"个 1.6TbE 端口" → "个"
   - 速率单价:"美元" → "美元/只"
   - 单GPU光模块配比:"倍" / "只" → "只/GPU"
"""
import sys, sqlite3
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

conn = sqlite3.connect('data/research.db')
conn.row_factory = sqlite3.Row

log = []
def upd(sql, params, desc):
    cur = conn.execute(sql, params)
    n = cur.rowcount
    log.append(f'{desc}: {n} rows')
    return n

# ============= 出货量类 =============
# 1a. metric='全行业出货量(M units)' AND unit='万只' → value/100, unit='百万只'
upd("UPDATE industry_data_point SET value_num=value_num/100.0, unit='百万只' WHERE industry_id=1 AND metric='全行业出货量(M units)' AND unit='万只'",
    (), '出货量(M units) 万只→百万只')

# 1b. metric='全行业出货量(M units)' AND unit='千只' → value/1000, unit='百万只'
upd("UPDATE industry_data_point SET value_num=value_num/1000.0, unit='百万只' WHERE industry_id=1 AND metric='全行业出货量(M units)' AND unit='千只'",
    (), '出货量(M units) 千只→百万只')

# 1c. metric='全行业出货量(万只)' 全部并入 '全行业出货量(M units)' (除百万通道)
#    AND unit='万只' → value/100, unit='百万只'
upd("UPDATE industry_data_point SET metric='全行业出货量(M units)', value_num=value_num/100.0, unit='百万只' WHERE industry_id=1 AND metric='全行业出货量(万只)' AND unit='万只'",
    (), '出货量(万只) 万只→并入(M units) 百万只')

# 1d. metric='全行业出货量(万只)' AND unit='百万通道' → 保留 metric 不变,这是 SiPh 通道数,语义不同
# 不动

# ============= TAM_USD =============
# 2a. unit='百万美元' → ÷100, unit='亿美元'
upd("UPDATE industry_data_point SET value_num=value_num/100.0, unit='亿美元' WHERE industry_id=1 AND metric='TAM_USD' AND unit='百万美元'",
    (), 'TAM_USD 百万美元→亿美元')

# 2b. unit='亿元' → 改 metric='TAM_CNY'(币种不能混算)
upd("UPDATE industry_data_point SET metric='TAM_CNY' WHERE industry_id=1 AND metric='TAM_USD' AND unit='亿元'",
    (), 'TAM_USD 亿元→改 metric=TAM_CNY')

# ============= 其他 unit 文字归一 =============
# CPO容量:T → Tbps
upd("UPDATE industry_data_point SET unit='Tbps' WHERE industry_id=1 AND metric='CPO容量(Tbps)' AND unit='T'",
    (), 'CPO容量 T→Tbps')

# 中国厂商前十席位数:席/10 → 席
upd("UPDATE industry_data_point SET unit='席' WHERE industry_id=1 AND metric='中国厂商前十席位数(席)' AND unit='席/10'",
    (), '前十席位数 席/10→席')

# 光引擎数:含 Davisson 描述的 unit 文字归一为 "个"
upd("UPDATE industry_data_point SET unit='个' WHERE industry_id=1 AND metric='光引擎数(个)' AND unit LIKE '%Davisson%'",
    (), '光引擎数 描述→个')

# 单产品端口数:"个 1.6TbE 端口" → "个"
upd("UPDATE industry_data_point SET unit='个' WHERE industry_id=1 AND metric='单产品端口数' AND unit LIKE '个 %'",
    (), '单产品端口数 含描述→个')

# 速率单价(USD):美元 → 美元/只
upd("UPDATE industry_data_point SET unit='美元/只' WHERE industry_id=1 AND metric='速率单价(USD)' AND unit='美元'",
    (), '速率单价 美元→美元/只')

# 单GPU光模块配比(只):倍 / 只 → 只/GPU
upd("UPDATE industry_data_point SET unit='只/GPU' WHERE industry_id=1 AND metric='单GPU光模块配比(只)' AND unit IN ('倍', '只')",
    (), '单GPU光模块配比 倍/只→只/GPU')

# GPU出货量(千台):百万颗 → 这是 different concept (颗 vs 台),保留 metric 不变;但 unit 文字归一
# 实际 metric name 已含"(千台)",百万颗 是另一概念,不动

conn.commit()

# 输出 log
out = ['# R1-2 unit 标准化迁移 log', '']
out.append('## 操作日志')
out.append('')
for line in log:
    out.append(f'- {line}')
out.append('')

# 验证:跑一次 unit 不一致 query
out.append('## 验证:metric × unit 仍有冲突的')
out.append('')
out.append('| metric | unit | count | range |')
out.append('|---|---|---|---|')
rows = list(conn.execute('''
SELECT metric, unit, COUNT(*) n, MIN(value_num) mn, MAX(value_num) mx
FROM industry_data_point WHERE industry_id=1 AND value_num IS NOT NULL
GROUP BY metric, unit
HAVING metric IN (
  SELECT metric FROM industry_data_point WHERE industry_id=1 AND value_num IS NOT NULL
  GROUP BY metric HAVING COUNT(DISTINCT unit) > 1
)
ORDER BY metric, unit
'''))
for r in rows:
    out.append(f'| {r["metric"]} | {r["unit"]} | {r["n"]} | {r["mn"]} - {r["mx"]} |')

if not rows:
    out.append('| (已全部统一 ??) | - | - | - |')

with open('cache/R1_unit_migration_log.md', 'w', encoding='utf-8') as f:
    f.write('\n'.join(out))

print('=== Migration 完成 ===')
for line in log:
    print(f'  {line}')

print(f'\n=== 剩余 unit 不统一 metric: {len(rows)} 个组 ===')
for r in rows:
    print(f'  {r["metric"]:30s} {r["unit"]:12s} n={r["n"]:3d}')

conn.close()
