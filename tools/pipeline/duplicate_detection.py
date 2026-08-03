"""数据点重复检测 — 找"同一 industry × metric × as_of_date × value_num × is_forecast 在 ≥ 3 个不同 source_id 出现"的数据点。

诊断 M3/M4 通宵任务的批量复制嫌疑。
支持 --industry / --output 命令行参数。
也支持以 export_dp_ids 模式 dump 全部疑似 dp_id 给 remediation。
"""
import sys, sqlite3, json, argparse
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = Path('D:/quant/industry_demo')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--industry', type=int, default=None, help='限定 industry_id')
    ap.add_argument('--output', type=str, default='cache/duplicate_data_points.md')
    ap.add_argument('--export-dp-ids', type=str, default=None, help='dump 疑似 dp_id 清单到 json 文件')
    args = ap.parse_args()

    conn = sqlite3.connect(str(ROOT/'data/research.db'))
    conn.row_factory = sqlite3.Row

    industries = {r['id']: r['name'] for r in conn.execute('SELECT id, name FROM industry')}

    where_clause = ""
    params = []
    if args.industry:
        where_clause = "AND industry_id = ?"
        params = [args.industry]

    groups = conn.execute(f"""
SELECT industry_id, metric, as_of_date, value_num, is_forecast,
       COUNT(DISTINCT source_id) AS n_sources,
       GROUP_CONCAT(DISTINCT source_id) AS sids,
       GROUP_CONCAT(id) AS dp_ids,
       COUNT(*) AS n_dp
FROM industry_data_point
WHERE source_id IS NOT NULL AND value_num IS NOT NULL {where_clause}
GROUP BY industry_id, metric, as_of_date, value_num, is_forecast
HAVING COUNT(DISTINCT source_id) >= 3
ORDER BY industry_id, n_sources DESC, metric
""", params).fetchall()

    print(f'发现 {len(groups)} 个 dup group (≥ 3 source 同 value)\n')

    by_industry = {}
    all_dup_dp_ids = []
    for g in groups:
        iid = g['industry_id']
        by_industry.setdefault(iid, []).append(g)
        for dp_id in g['dp_ids'].split(','):
            all_dup_dp_ids.append(int(dp_id))

    lines = []
    lines.append('# 数据点重复检测报告')
    lines.append('')
    lines.append('## 检测规则')
    lines.append('')
    lines.append('"同一 industry × metric × as_of_date × value_num × is_forecast 在 ≥ 3 个不同 source_id 出现"被视为疑似批量复制。')
    lines.append('')
    lines.append('真实研究数据应当呈现:不同卖方对同一 metric 给出**略有差异**的数字。')
    lines.append('如果 ≥ 3 个 source 给出**完全相同**的数字,大概率是 ETL 批量分发,而非真实独立预测。')
    lines.append('')
    lines.append('## 总结')
    lines.append('')
    lines.append(f'| Industry | Dup group 数 (≥3 src) | Dup group 数 (≥10 src) | Dup group 数 (≥30 src) |')
    lines.append(f'|---|---|---|---|')
    for iid in sorted(by_industry.keys()):
        gs = by_industry[iid]
        n_ge3 = len(gs)
        n_ge10 = sum(1 for g in gs if g['n_sources'] >= 10)
        n_ge30 = sum(1 for g in gs if g['n_sources'] >= 30)
        lines.append(f'| {industries.get(iid, "?")}({iid}) | {n_ge3} | {n_ge10} | {n_ge30} |')
    lines.append('')

    for iid in sorted(by_industry.keys()):
        iname = industries.get(iid, '?')
        gs = by_industry[iid]
        lines.append(f'## {iname} (id={iid}) — {len(gs)} dup groups')
        lines.append('')
        for g in gs:
            sids = [int(s) for s in g['sids'].split(',')]
            src_rows = conn.execute(f"SELECT id, title, publisher, publish_date FROM source WHERE id IN ({','.join(map(str, sids[:8]))})").fetchall()
            src_strs = [f"#{r['id']} [{r['publisher'] or 'NA'} {r['publish_date'] or ''}] {(r['title'] or '')[:40]}" for r in src_rows]
            suffix = f' ... + {len(sids) - 8} more' if len(sids) > 8 else ''
            v_desc = f"{g['value_num']}"
            is_fc = '(forecast)' if g['is_forecast'] else ''
            lines.append(f"### `{g['metric']}` @ `{g['as_of_date']}` = **{v_desc}** {is_fc} — {g['n_sources']} sources")
            lines.append('')
            for s in src_strs:
                lines.append(f'- {s}')
            if suffix:
                lines.append(f'- {suffix}')
            lines.append('')
        lines.append('---')
        lines.append('')

    out_path = ROOT / args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text('\n'.join(lines), encoding='utf-8')
    print(f'\n=== 输出 → {out_path}')
    print(f'总 dup groups (≥3 src): {len(groups)}')
    print(f'按 industry:')
    for iid in sorted(by_industry.keys()):
        gs = by_industry[iid]
        print(f'  {industries.get(iid, "?"):8s}: {len(gs)} groups')

    if args.export_dp_ids:
        ep = ROOT / args.export_dp_ids
        ep.parent.mkdir(parents=True, exist_ok=True)
        # 同时按 industry 分类
        by_ind_ids = {}
        for g in groups:
            for dp_id in g['dp_ids'].split(','):
                by_ind_ids.setdefault(g['industry_id'], []).append(int(dp_id))
        ep.write_text(json.dumps({
            'all_dup_dp_ids': sorted(set(all_dup_dp_ids)),
            'by_industry': {str(k): sorted(set(v)) for k, v in by_ind_ids.items()},
        }, indent=2), encoding='utf-8')
        print(f'  dp_ids dump → {ep}')
    conn.close()

if __name__ == '__main__':
    main()
