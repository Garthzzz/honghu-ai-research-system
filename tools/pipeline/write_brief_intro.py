# -*- coding: utf-8 -*-
"""逐条写入 company.brief_intro / brief_intro_src。
读 cache/intro_batch2_data.json:  [{"id":188,"intro":"...","src":"..."}, ...]
短事务逐条 commit, busy_timeout=30000, 只更新这两列。
用法: python tools/pipeline/write_brief_intro.py cache/intro_batch2_data.json
"""
import sqlite3, sys, json, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def main(path):
    with open(path, 'r', encoding='utf-8') as f:
        items = json.load(f)
    con = sqlite3.connect('data/research.db')
    con.execute('PRAGMA busy_timeout=30000')
    ok = 0
    for it in items:
        cid = it['id']; intro = it['intro'].strip(); src = it['src'].strip()
        assert intro and src, f"empty intro/src for {cid}"
        cur = con.cursor()
        cur.execute('UPDATE company SET brief_intro=?, brief_intro_src=? WHERE id=?',
                    (intro, src, cid))
        con.commit()  # 逐条 commit, 短事务
        # 回读校验
        row = cur.execute('SELECT name, length(brief_intro) FROM company WHERE id=?', (cid,)).fetchone()
        print(f"OK id={cid} {row[0]} intro_len={row[1]}")
        ok += 1
    con.close()
    print(f"TOTAL_WRITTEN {ok}")

if __name__ == '__main__':
    main(sys.argv[1])
