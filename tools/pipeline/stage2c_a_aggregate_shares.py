# -*- coding: utf-8 -*-
"""Stage 2c-A:把 idp 份额类 dp 聚合到 company_profile.global_share/china_share/global_rank/china_rank。
纯工程,零网搜,零新 dp,只读 idp 只写 company_profile。幂等:只填空(保护 2a/2b 既有值,红线7)。
用法:python stage2c_a_aggregate_shares.py [--commit]   (默认 DRY_RUN 只分析不写)
"""
import sqlite3, sys, io, json, argparse, re
from datetime import datetime
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DB = 'data/research.db'
TODAY = '2026-06-01'
TODAY_YM = (2026, 6)
METRICS = ('全球DRAM份额','全球NAND份额','公司市占率(%)','市占率(%)','HBM市占率(%)','NOR市占率(%)')
INDUSTRIES = (1, 7)   # 红线10:跳过 8 大模型

GLOBAL_KW = ['全球','global','worldwide','world','international']
CHINA_KW  = ['中国','国内','国产','domestic','china']   # 大小写不敏感处理;'国产'修复长鑫误判
REGION_ONLY = ['北美','欧洲','美国','日本','韩国']   # 单独出现且无全球/中国 → pending

def norm_asof(s):
    """as_of_date → (year, month) 可比元组;无法解析/空 → (0,0) 视为最旧。"""
    if not s: return (0, 0)
    s = s.strip()
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})', s)
    if m: return (int(m.group(1)), int(m.group(2)))
    m = re.match(r'^(\d{4})Q([1-4])', s)
    if m: return (int(m.group(1)), int(m.group(2))*3)   # Q1→3 Q2→6 Q3→9 Q4→12
    m = re.match(r'^(\d{4})E?$', s)
    if m: return (int(m.group(1)), 0)                    # 裸年/估算年 → 月0
    m = re.match(r'^(\d{4})', s)
    if m: return (int(m.group(1)), 0)
    return (0, 0)

def classify(metric, excerpt, note):
    """返回 ('global'|'china'|'pending', 命中关键词说明)"""
    if metric in ('全球DRAM份额', '全球NAND份额'):
        return 'global', 'metric名含"全球"'
    if '中国' in metric or '国产' in metric:
        return 'china', 'metric名含"中国/国产"'
    text = f"{excerpt or ''} {note or ''}"
    low = text.lower()
    if '产能' in text:   # 产能份额 ≠ 市场份额(如长鑫"占国产DRAM产能90%")
        return 'pending', '"产能"份额非市场份额'
    hitg = [k for k in GLOBAL_KW if (k in text if not k.isascii() else k in low)]
    hitc = [k for k in CHINA_KW  if (k in text if not k.isascii() else k in low)]
    if hitg and not hitc:
        return 'global', f'excerpt/note含{hitg}'
    if hitc and not hitg:
        return 'china', f'excerpt/note含{hitc}'
    if hitg and hitc:
        # 同时出现:以 metric/上下文为准,记 pending 让 user 看(保守)
        return 'pending', f'全球{hitg}+中国{hitc}同现,歧义'
    if '海外' in text:
        return 'global', 'excerpt/note含"海外"(口径以全球为主)'
    hitr = [k for k in REGION_ONLY if k in text]
    if hitr:
        return 'pending', f'仅区域{hitr},非全球非中国'
    return 'pending', '无全球/中国关键词'

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--commit', action='store_true', help='真正写入(默认 dry-run)')
    args = ap.parse_args()
    DRY = not args.commit
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    cur = c.cursor()
    log = []   # 详细日志行
    pending = []   # ambiguous / sanity 失败 / 冲突
    slop = []  # 跨公司同值
    def L(s): log.append(s)

    L(f"# Stage 2c-A 聚合日志 ({'DRY-RUN' if DRY else 'COMMIT'}) {TODAY}\n")

    # 黑名单 source
    blk = set(r[0] for r in cur.execute("SELECT id FROM source WHERE source_credibility='blacklisted'"))
    # qualitative_only 公司(user 决策,不展示数字)→ 跳过填充
    qual = set(r[0] for r in cur.execute("SELECT id FROM company WHERE display_mode='qualitative_only'"))

    # 跨公司同值检测准备:industry+metric+value → companies
    samevalue = {}

    fills = []   # (company_id, industry_id, field, value, as_of, source_ids, display_note, submarket)
    for ind in INDUSTRIES:
        ph = ','.join('?'*len(METRICS))
        rows = cur.execute(f"""SELECT dp.id,dp.company_id,co.name,dp.metric,dp.value_num,dp.unit,dp.as_of_date,
            dp.consensus_status,dp.source_id,dp.is_forecast,dp.source_excerpt,dp.note
            FROM industry_data_point dp JOIN company co ON co.id=dp.company_id
            WHERE dp.industry_id=? AND dp.company_id IS NOT NULL AND dp.metric IN ({ph})""",
            (ind,)+METRICS).fetchall()
        # 分桶:(company_id, bucket) → list of dict
        buckets = {}
        for r in rows:
            dpid, cid, name, metric, val, unit, asof, cons, sid, isfc, ex, note = (
                r['id'],r['company_id'],r['name'],r['metric'],r['value_num'],r['unit'],
                r['as_of_date'],r['consensus_status'],r['source_id'],r['is_forecast'],r['source_excerpt'],r['note'])
            # sanity A5
            if val is None or not (0 < val <= 100):
                pending.append(f"SANITY ind{ind} dp{dpid} {name} [{metric}]={val}{unit} → value 不在(0,100],跳过"); continue
            if unit != '%':
                pending.append(f"SANITY ind{ind} dp{dpid} {name} [{metric}]={val}{unit} → unit≠%,跳过"); continue
            if sid in blk:
                pending.append(f"SANITY ind{ind} dp{dpid} {name} src{sid} 黑名单,跳过"); continue
            # 排除前瞻/未来日期(前瞻份额非当前市场地位)
            ym = norm_asof(asof)
            if isfc == 1 or ym > TODAY_YM:
                pending.append(f"FORECAST ind{ind} dp{dpid} {name} [{metric}]={val}% @{asof}(is_forecast={isfc})→前瞻,不入当前份额"); continue
            bucket, why = classify(metric, ex, note)
            submarket = (note or ex or '')[:40]
            if bucket == 'pending':
                pending.append(f"AMBIG ind{ind} dp{dpid} {name} [{metric}]={val}% @{asof} → {why};excerpt:{(ex or '')[:50]}")
                continue
            buckets.setdefault((cid, name, bucket), []).append(
                dict(dpid=dpid, val=val, asof=asof, ym=ym, cons=cons, sid=sid, sub=submarket, why=why, metric=metric))
            samevalue.setdefault((ind, round(val,2)), set()).add(cid)

        # A3 取值 per (company,bucket)
        for (cid, name, bucket), dps in buckets.items():
            field = 'global_share' if bucket == 'global' else 'china_share'
            asof_field = 'global_share_as_of' if bucket == 'global' else 'china_share_as_of'
            # 既有值保护(红线7)
            prof = cur.execute(f"SELECT {field} FROM company_profile WHERE company_id=? AND industry_id=?", (cid, ind)).fetchone()
            if prof is None:
                pending.append(f"NOPROFILE ind{ind} {name}(c{cid}) 无 company_profile 行,跳过 {bucket}"); continue
            if prof[0] is not None:
                L(f"[已有跳过] ind{ind} {name} {field}={prof[0]}(保护既有,不覆盖)")
                continue
            if cid in qual:
                pending.append(f"QUALONLY ind{ind} {name}(c{cid}) display_mode=qualitative_only(user 2b决策),有 {bucket} share 候选但跳过填充(等 user 解除)")
                continue
            # A3 step1:最新 as_of
            maxym = max(d['ym'] for d in dps)
            latest = [d for d in dps if d['ym'] == maxym]
            # A3 step2:同 as_of 多源 → consensus
            note_tag = ''
            chosen_val = None
            if len(latest) == 1:
                chosen = latest[0]
            else:
                cons_set = [d for d in latest if d['cons'] in ('共识','主流')]
                submain = [d for d in latest if d['cons'] == '次主流']
                solo = [d for d in latest if d['cons'] == '孤证']
                nonoutlier = [d for d in latest if d['cons'] != '离群']
                if cons_set:
                    chosen = cons_set[0]
                elif submain:
                    vals = sorted(d['val'] for d in submain)
                    med = vals[len(vals)//2] if len(vals)%2 else (vals[len(vals)//2-1]+vals[len(vals)//2])/2
                    chosen = min(submain, key=lambda d: abs(d['val']-med))   # 仅用于 as_of/dpid 标注
                    chosen_val = round(med, 2)
                    note_tag = f"次主流取{len(submain)}源中位{chosen_val}(" + "/".join(f"{d['val']}%" for d in sorted(submain,key=lambda d:d['val'])) + ")"
                elif nonoutlier:
                    chosen = nonoutlier[0]
                else:
                    chosen = latest[0]
                if all(d['cons']=='孤证' for d in latest): note_tag='单源孤证'
            if chosen_val is None: chosen_val = chosen['val']
            allsids = sorted(set(d['sid'] for d in latest))
            dn = f"{bucket}份额聚合自 dp{chosen['dpid']}({chosen['metric']},{chosen['asof']},{chosen['cons']},{chosen['sub']}){';'+note_tag if note_tag else ''}"
            fills.append((cid, ind, field, asof_field, chosen_val, chosen['asof'], allsids, dn, bucket))
            L(f"[填充] ind{ind} {name} {field}={chosen_val}% @{chosen['asof']} cons={chosen['cons']} sids={allsids} ←{len(dps)}条候选 sub={chosen['sub']} {note_tag}")

    # 跨公司同值检测
    for (ind, v), cids in samevalue.items():
        if len(cids) >= 3:
            slop.append(f"同值 ind{ind} value={v}% 跨 {len(cids)} 公司 {sorted(cids)}(可能批量复制,人工核)")

    # 写入(填空)
    if not DRY:
        for cid, ind, field, asof_field, val, asof, sids, dn, bucket in fills:
            cur.execute(f"""UPDATE company_profile SET {field}=?, {asof_field}=?,
                source_ids=CASE WHEN source_ids IS NULL OR source_ids='' THEN ? ELSE source_ids END,
                display_note=COALESCE(display_note,'')||' | '||?, last_updated=?
                WHERE company_id=? AND industry_id=?""",
                (val, asof, json.dumps(sids), dn, TODAY, cid, ind))
        c.commit()

    # A4 rank:?? 不自动写(存储 global_share 混 DRAM/NAND/HDD 子市场不可比;且会覆盖 2a 既有 curated rank,红线7)
    #          → 只生成"按 share 派生的建议排序"落 pending,由 user 拍板。rank 字段零写入。
    L("\n## A4 rank 建议(不写库,仅供 user 决策)")
    rank_suggest = []
    rank_writes = []   # 始终空(不写)
    for ind in INDUSTRIES:
        for bucket, sharef, rankf, tablef in [('global','global_share','global_rank','in_global_table'),
                                               ('china','china_share','china_rank','in_china_table')]:
            rows = cur.execute(f"""SELECT company_id, (SELECT name FROM company WHERE id=company_id) nm,
                {sharef} sh, {rankf} rk FROM company_profile
                WHERE industry_id=? AND {tablef}=1 AND {sharef} IS NOT NULL
                ORDER BY {sharef} DESC""", (ind,)).fetchall()
            if not rows: continue
            order = [f"{i+1}.{r['nm']}({r['sh']}%{'｜现有rank='+str(r['rk']) if r['rk'] is not None else ''})" for i,r in enumerate(rows)]
            rank_suggest.append(f"ind{ind} {rankf} 按share降序建议:{' > '.join(order)}")
            L(f"[rank建议] {rank_suggest[-1]}")
    # ?? rank 不写库

    # 输出日志
    L(f"\n## 汇总:填充 share {len(fills)} 条;rank 写入 0 条(仅建议 {len(rank_suggest)} 组);pending {len(pending)};跨公司同值 {len(slop)}")
    open('cache/STAGE2C_A_AGGREGATION_LOG.md','w',encoding='utf-8').write('\n'.join(log))
    open('cache/STAGE2C_A_pending_raw.md','w',encoding='utf-8').write(
        '# Pending / Sanity / 冲突\n\n' + '\n'.join(f'- {p}' for p in pending) +
        '\n\n# 跨公司同值(反slop)\n\n' + '\n'.join(f'- {s}' for s in slop) +
        '\n\n# rank 派生建议(未写库,user 决策)\n\n' + '\n'.join(f'- {r}' for r in rank_suggest))
    print('\n'.join(log[-40:]))
    print(f"\n=== {'DRY-RUN(未写)' if DRY else 'COMMITTED'} | share填充 {len(fills)} | rank填充 {len(rank_writes)} | pending {len(pending)} | 同值 {len(slop)} ===")
    c.close()

if __name__ == '__main__':
    main()
