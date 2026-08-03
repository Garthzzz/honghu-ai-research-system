"""光模块 db scope 分流 (R1-3 部分).

异常组的根因:peer group key (metric × as_of × is_forecast) 把不同 scope 当作 peer,
例如 TAM_USD 把"全球光模块 TAM" 和 "InP 衬底 TAM" 混算。

解决:按 note 关键词把 metric 拆成 scope-specific。

策略保守:只拆已确认混 scope 的 metric (TAM_USD / 全行业出货量(M units) / 技术路线渗透率)。
不动 metric content (note/excerpt 保留),只改 metric column。
"""
import sys, sqlite3, re
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

conn = sqlite3.connect('data/research.db')
conn.row_factory = sqlite3.Row

log = []

# ============= TAM_USD scope 分流 =============
# 拆 metric 规则(基于 note 含关键词):
TAM_RULES = [
    # (note 正则,新 metric)
    (r'InP.*衬底', 'TAM_USD_InP衬底'),
    (r'(光芯片|源杰)', 'TAM_USD_光芯片'),
    (r'(封测设备|光模块封测)', 'TAM_USD_封测设备'),
    (r'CPO', 'TAM_USD_CPO'),
    (r'(数通光模块|全球数通)', 'TAM_USD_数通'),
    (r'电信光模块', 'TAM_USD_电信'),
    (r'(硅光|SiPh)', 'TAM_USD_硅光'),
    (r'AI光模块', 'TAM_USD_AI光模块'),
    (r'(端侧|端侧 AI)', 'TAM_USD_端侧AI_不属于光模块'),  # 标记为 scope 错
    (r'(800G\+1.6T|800G\+|高速光模块)', 'TAM_USD_高速光模块'),
    (r'光收发器', 'TAM_USD_光收发器'),
    (r'薄膜铌酸锂', 'TAM_USD_薄膜铌酸锂'),
    (r'(中国光模块|中国市场)', 'TAM_USD_中国市场'),
    (r'光互连', 'TAM_USD_光互连'),  # 光互连 ⊇ 光模块,scope 略大但接近
    # 否则:TAM_USD 整体光模块(LightCounting/Yole 全球光模块/中商口径)— 默认保持
]

def assign_scope_tam(note):
    if not note:
        return None
    for pat, new_metric in TAM_RULES:
        if re.search(pat, note):
            return new_metric
    return None

rows = list(conn.execute("SELECT id, note FROM industry_data_point WHERE industry_id=1 AND metric='TAM_USD'"))
n_split = 0
for r in rows:
    new_m = assign_scope_tam(r['note'])
    if new_m:
        conn.execute('UPDATE industry_data_point SET metric=? WHERE id=?', (new_m, r['id']))
        n_split += 1
log.append(f'TAM_USD 按 scope 分流: {n_split} dp')

# 看剩余 TAM_USD(应该都是光模块整体 TAM)
rest = conn.execute("SELECT id, value_num, unit, note, as_of_date FROM industry_data_point WHERE industry_id=1 AND metric='TAM_USD' ORDER BY value_num").fetchall()
log.append(f'剩余 TAM_USD (光模块整体): {len(rest)}')

# ============= 出货量(M units) scope 分流 =============
SHIP_RULES = [
    (r'(1\.6T|1.6T 全层|1.6T 出货)', '出货量_1.6T(百万只)'),
    (r'(800G,|800G 全层|800G\+)', '出货量_800G(百万只)'),
    (r'3\.2T', '出货量_3.2T(百万只)'),
    (r'数通光模块', '出货量_数通(百万只)'),
    (r'(硅光|SiPh|Yole 硅光)', '出货量_硅光(百万只)'),
    (r'高速光模块', '出货量_高速光模块(百万只)'),
    (r'400G\+ 数通', '出货量_400G(百万只)'),
    # 否则:全球光模块整体 — 默认保持
]
rows = list(conn.execute("SELECT id, note FROM industry_data_point WHERE industry_id=1 AND metric='全行业出货量(M units)'"))
n_split2 = 0
for r in rows:
    note = r['note'] or ''
    for pat, new_m in SHIP_RULES:
        if re.search(pat, note):
            conn.execute('UPDATE industry_data_point SET metric=? WHERE id=?', (new_m, r['id']))
            n_split2 += 1
            break
log.append(f'出货量(M units) 按 scope 分流: {n_split2} dp')

# ============= 技术路线渗透率 scope 分流 =============
PEN_RULES = [
    (r'(硅光 800G|硅光 整体出货)', '渗透率_硅光占800G+(%)'),
    (r'(硅光占比|硅光 整体出货占比|硅光.*占)', '渗透率_硅光(%)'),
    (r'CPO 占 800G\+', '渗透率_CPO占800G+(%)'),
    (r'CPO', '渗透率_CPO(%)'),
    (r'LPO', '渗透率_LPO(%)'),
    (r'(800G占|800G 占)', '渗透率_800G(%)'),
    (r'1.6T', '渗透率_1.6T(%)'),
]
rows = list(conn.execute("SELECT id, note FROM industry_data_point WHERE industry_id=1 AND metric='技术路线渗透率(%)'"))
n_split3 = 0
for r in rows:
    note = r['note'] or ''
    for pat, new_m in PEN_RULES:
        if re.search(pat, note):
            conn.execute('UPDATE industry_data_point SET metric=? WHERE id=?', (new_m, r['id']))
            n_split3 += 1
            break
log.append(f'技术路线渗透率(%) 按 scope 分流: {n_split3} dp')

# 删除明显垃圾:端侧 AI(scope 错)
rows = list(conn.execute("SELECT id, value_num, unit, note FROM industry_data_point WHERE industry_id=1 AND metric='TAM_USD_端侧AI_不属于光模块'"))
for r in rows:
    print(f'  DELETE #{r["id"]}: {r["value_num"]}{r["unit"]} {r["note"]}')
n_del = conn.execute("DELETE FROM industry_data_point WHERE industry_id=1 AND metric='TAM_USD_端侧AI_不属于光模块'").rowcount
log.append(f'删除 scope 错的端侧 AI TAM: {n_del} dp')

# CPO 容量异常 — 看一下
# 上面 51.2T vs 102.4Tbps 不算异常,是早期 vs 升级版本,保留

conn.commit()

# 重新跑异常检测
print('\n=== Migration log ===')
for line in log:
    print(f'  {line}')

print('\n=== 剩余异常组(max/min > 10)===')
rows2 = list(conn.execute('''
SELECT metric, as_of_date, is_forecast, COUNT(*) n,
       MIN(value_num) mn, MAX(value_num) mx
FROM industry_data_point WHERE industry_id=1 AND value_num > 0
GROUP BY metric, COALESCE(as_of_date, period), is_forecast
HAVING COUNT(*) >= 2 AND MAX(value_num)/MIN(value_num) > 10
ORDER BY MAX(value_num)/MIN(value_num) DESC
LIMIT 20
'''))
for r in rows2:
    print(f'  {r["metric"]:35s} @{r["as_of_date"]} fc={r["is_forecast"]} n={r["n"]} min={r["mn"]:.2f} max={r["mx"]:.2f}')

# 写 cache
out = ['# R1-3 异常值检测 + scope 分流 log', '']
out.append('## 操作日志')
out.append('')
for line in log:
    out.append(f'- {line}')
out.append('')
out.append('## 异常组剩余(max/min > 10)')
out.append('')
out.append('| metric | as_of | fc | n | min | max | 评 |')
out.append('|---|---|---|---|---|---|---|')
for r in rows2:
    note = ''
    if 'GPU出货量' in r['metric']:
        note = '千台 vs 百万颗概念不同,可拆 metric (留待后续)'
    out.append(f'| {r["metric"]} | {r["as_of_date"]} | {r["is_forecast"]} | {r["n"]} | {r["mn"]:.2f} | {r["mx"]:.2f} | {note} |')
if not rows2:
    out.append('| (已全部解决 ??) | - | - | - | - | - | - |')

with open('cache/R1_anomaly_review.md', 'w', encoding='utf-8') as f:
    f.write('\n'.join(out))

conn.close()
