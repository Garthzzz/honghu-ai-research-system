"""SCIENTIST session 收尾自动化校验脚本(GOLD 第四次修订)。

SCIENTIST 每个 session 结束前必跑。输出:
- 本 session 新增 dp 数 + 按 extraction_method 分布
- duplicate_detection 结果(本行业)
- 不达标 source 清单
- 不诚实 extraction_method 标注的告警

只有 audit 全过才允许 commit。
"""
import sys, argparse, sqlite3, json
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = Path('D:/quant/industry_demo')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--industry', type=int, required=True, help='本 session 涉及的 industry_id')
    ap.add_argument('--since', type=str, default=None, help='只统计 created_at >= 此时点的 dp(可选 ISO datetime)')
    ap.add_argument('--output', type=str, default='cache/scientist_session_audit.md')
    args = ap.parse_args()

    conn = sqlite3.connect(str(ROOT/'data/research.db'))
    conn.row_factory = sqlite3.Row
    ind = conn.execute("SELECT * FROM industry WHERE id=?", (args.industry,)).fetchone()
    if not ind:
        print(f'ERROR: industry id={args.industry} 不存在')
        sys.exit(1)

    where_time = ""
    params = [args.industry]
    if args.since:
        where_time = " AND dp.created_at >= ?"
        params.append(args.since)

    # 1. dp 总数 + 按 extraction_method 分布
    print(f'=== {ind["name"]} (id={args.industry}) session audit ===\n')
    total = conn.execute(f"SELECT COUNT(*) FROM industry_data_point dp WHERE dp.industry_id=?{where_time}", params).fetchone()[0]
    print(f'本行业 dp 总数: {total}')

    em_dist = list(conn.execute(f"""
        SELECT extraction_method, COUNT(*) c FROM industry_data_point dp
        WHERE industry_id=?{where_time}
        GROUP BY extraction_method ORDER BY c DESC
    """, params))
    print('extraction_method 分布:')
    pdf_n = web_n = tmpl_n = inf_n = unk_n = 0
    for r in em_dist:
        print(f'  {r["extraction_method"]:18s}: {r["c"]}')
        if r["extraction_method"] == 'pdf_direct': pdf_n = r["c"]
        elif r["extraction_method"] == 'web_fetch': web_n = r["c"]
        elif r["extraction_method"] == 'template_estimate': tmpl_n = r["c"]
        elif r["extraction_method"] == 'inferred': inf_n = r["c"]
        elif r["extraction_method"] == 'unknown': unk_n = r["c"]

    # 2. 警告条件
    warnings = []
    if total > 0 and tmpl_n / total > 0.30:
        warnings.append(f'?? template_estimate 占比 {100*tmpl_n//total}% 超过 30%,可信度受限')
    if unk_n > 0:
        warnings.append(f'?? {unk_n} 条 dp extraction_method=unknown,新数据不应使用 unknown')

    # 3. duplicate detection 本行业
    dup_groups = list(conn.execute("""
        SELECT metric, as_of_date, value_num, is_forecast,
               COUNT(DISTINCT source_id) AS n_sources,
               GROUP_CONCAT(note, ' || ') AS notes
        FROM industry_data_point
        WHERE industry_id=? AND source_id IS NOT NULL AND value_num IS NOT NULL
        GROUP BY metric, as_of_date, value_num, is_forecast
        HAVING COUNT(DISTINCT source_id) >= 3
        ORDER BY n_sources DESC
    """, (args.industry,)))
    print(f'\n重复检测(≥3 source 同 value): {len(dup_groups)} groups')

    # 检查是否含合理三方 cite(white list)
    THIRD_PARTY_KW = ['LightCounting', 'Yole', 'Omdia', 'IDC', 'Gartner', '信通院',
                     'CINNO', 'Counterpoint', 'TrendForce', 'WSTS', 'Tushare', 'Yahoo Finance', '朝阳永续']
    dup_with_3rd, dup_suspect = 0, 0
    for g in dup_groups:
        notes = g['notes'] or ''
        if any(kw in notes for kw in THIRD_PARTY_KW):
            dup_with_3rd += 1
        else:
            dup_suspect += 1
    if dup_suspect > 0:
        warnings.append(f'?? {dup_suspect} dup groups 没有显式 cite 三方机构,疑似批量复制,需 review')

    # 4. 不达标 source(基于 v_source_extraction_audit)
    short_srcs = list(conn.execute(f"""
        SELECT v.id, v.title, v.dp_count, v.dp_min, v.ka_count_approx, v.ka_min
        FROM v_source_extraction_audit v
        JOIN source_entity se ON se.source_id=v.id
        WHERE se.entity_type='industry' AND se.entity_id=?
          AND (v.dp_count < v.dp_min OR v.ka_count_approx < v.ka_min)
        ORDER BY v.dp_count ASC
    """, (str(args.industry),)))
    print(f'\n不达标 source: {len(short_srcs)} 份')

    # 5. 写输出 md
    out_path = ROOT / args.output
    lines = []
    lines.append(f'# SCIENTIST Session Audit — {ind["name"]} (id={args.industry})')
    lines.append('')
    lines.append('## extraction_method 分布')
    lines.append('')
    lines.append('| method | count |')
    lines.append('|---|---|')
    for r in em_dist:
        lines.append(f'| {r["extraction_method"]} | {r["c"]} |')
    lines.append('')
    lines.append('## 重复检测 (≥3 source 同 value)')
    lines.append('')
    lines.append(f'- 总 dup groups: {len(dup_groups)}')
    lines.append(f'- 含三方机构 cite 的 dup(合理): {dup_with_3rd}')
    lines.append(f'- ?? 疑似批量复制(无三方 cite): {dup_suspect}')
    lines.append('')
    if dup_suspect > 0:
        lines.append('### 疑似批量复制清单(需 SCIENTIST review)')
        lines.append('')
        for g in dup_groups[:20]:
            notes = g['notes'] or ''
            if any(kw in notes for kw in THIRD_PARTY_KW):
                continue
            lines.append(f"- `{g['metric']}` @ `{g['as_of_date']}` = {g['value_num']} — {g['n_sources']} sources")
        lines.append('')
    lines.append('## 不达标 source')
    lines.append('')
    if short_srcs:
        for r in short_srcs[:30]:
            lines.append(f"- #{r['id']} {(r['title'] or '')[:50]} dp={r['dp_count']}/{r['dp_min']} ka={r['ka_count_approx']}/{r['ka_min']}")
    else:
        lines.append('全达标 ??')
    lines.append('')
    lines.append('## 警告')
    lines.append('')
    if warnings:
        for w in warnings:
            lines.append(f'- {w}')
    else:
        lines.append('全过 ??')

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text('\n'.join(lines), encoding='utf-8')

    print('\n=== 警告 ===')
    if warnings:
        for w in warnings:
            print(f'  {w}')
    else:
        print('  无 ??')

    print(f'\n输出 → {out_path}')

    if warnings:
        print('\n[FAIL] 有警告,SCIENTIST 必须 review 后才能 commit')
        sys.exit(1)
    print('\n[PASS] session audit 通过')
    conn.close()


if __name__ == '__main__':
    main()
