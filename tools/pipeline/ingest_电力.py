#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""电力 #13 入库:cache/claims/电力_*.json → source + industry_data_point(走 db_writer)。

铁律遵循:
- 所有 dp 走 write_data_point(7 必填齐,extraction_method='pdf_direct',consensus 自动重算)。
- source 按 file_path 去重(幂等;再跑不重复建源)。
- 绝不编造:只入 JSON 里 agent 从 PDF verbatim 抽出的;unit/excerpt 缺失则跳过并计数。
- company 级 dp:按名查/建 company 并 tag company_industry(13)。
- 输出 source_id 映射 → cache/db_queue/电力_source_map.json,供 md 的 ^src 引用。
"""
from __future__ import annotations
import json, sys, re
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools" / "pipeline"))
import db_writer

IND_ID = 13
CLAIMS = sorted((ROOT / "cache" / "claims").glob("电力_*_claims.json"))
VALID_STYPE = {'卖方深度','卖方周报','公告','业绩说明会','招股书','协会数据','三方数据','财经媒体','自媒体','claude_lit_review','website_material','其他'}
VALID_VLAYER = {'深度框架','最新数据','双层','公司专项','主题专项','信息流'}
VALID_SENT = {'看涨','看跌','中性','不适用'}


def norm_date(s):
    if not s:
        return None
    s = str(s).strip()
    m = re.match(r'^(\d{4})(\d{2})(\d{2})$', s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return s


def to_num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def main():
    conn = db_writer.get_db()
    conn.execute("PRAGMA foreign_keys=ON")
    # 公司 name→id 缓存
    comp_cache = {r["name"]: r["id"] for r in conn.execute("SELECT id,name FROM company")}

    def get_company_id(name):
        name = (name or "").strip()
        if not name:
            return None
        if name in comp_cache:
            cid = comp_cache[name]
        else:
            cur = conn.execute("INSERT INTO company(name) VALUES(?)", (name,))
            cid = cur.lastrowid
            comp_cache[name] = cid
        # tag company_industry(13)
        conn.execute("INSERT OR IGNORE INTO company_industry(company_id, industry_id) VALUES(?,?)", (cid, IND_ID))
        return cid

    # 已有 source(按 file_path 去重)
    src_by_path = {r["file_path"]: r["id"] for r in conn.execute(
        "SELECT id,file_path FROM source WHERE file_path IS NOT NULL")}

    src_map = {}          # source_file(basename) → source_id
    stats = {"sources_new": 0, "sources_reuse": 0, "dp_ok": 0, "dp_skip": 0,
             "ka": 0, "companies": 0}
    ka_by_src = {}        # source_file → [arguments]

    # ── pass 1: 注册 sources ──
    for jf in CLAIMS:
        data = json.loads(jf.read_text(encoding="utf-8"))
        for s in data.get("sources", []):
            sf = s.get("source_file")
            if not sf or sf in src_map:
                continue
            fp = f"papers/电力/{sf}"
            if fp in src_by_path:
                src_map[sf] = src_by_path[fp]; stats["sources_reuse"] += 1
                continue
            stype = s.get("source_type") if s.get("source_type") in VALID_STYPE else "其他"
            vlayer = s.get("value_layer") if s.get("value_layer") in VALID_VLAYER else "信息流"
            try:
                tier = int(s.get("quality_tier") or 3)
            except (TypeError, ValueError):
                tier = 3
            tier = tier if tier in (1, 2, 3) else 3
            cur = conn.execute("""
                INSERT INTO source(title, source_type, publisher, publish_date, quality_tier,
                    is_forward_looking, file_path, value_layer, fetch_method, source_credibility,
                    language, is_primary_source, source_subtype)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (s.get("title") or sf, stype, s.get("publisher"), norm_date(s.get("publish_date")),
                 tier, 0, fp, vlayer, "pdf_local", "whitelisted", "zh", 0, "research_report"))
            sid = cur.lastrowid
            src_map[sf] = sid; stats["sources_new"] += 1
            # source_entity → industry 13
            conn.execute("""INSERT OR IGNORE INTO source_entity(source_id, entity_type, entity_id, coverage)
                            VALUES(?,?,?,?)""", (sid, "industry", IND_ID, "主要覆盖"))
    conn.commit()

    # ── pass 2: data_points + key_arguments ──
    for jf in CLAIMS:
        data = json.loads(jf.read_text(encoding="utf-8"))
        for dp in data.get("data_points", []):
            sf = dp.get("source_file")
            sid = src_map.get(sf)
            excerpt = (dp.get("source_excerpt") or "").strip()
            unit = (dp.get("unit") or "").strip()
            vnum = to_num(dp.get("value_num"))
            vtext = dp.get("value_text")
            vtext = str(vtext).strip() if vtext not in (None, "") else None
            metric = (dp.get("metric") or "").strip()
            period = (dp.get("period") or "").strip() or (dp.get("as_of_date") or "").strip()
            if not (sid and excerpt and unit and metric and period and (vnum is not None or vtext)):
                stats["dp_skip"] += 1
                continue
            sent = dp.get("sentiment") if dp.get("sentiment") in VALID_SENT else "不适用"
            cid = get_company_id(dp.get("company"))
            try:
                db_writer.write_data_point(
                    conn, industry_id=IND_ID, metric=metric, period=period,
                    unit=unit, source_id=sid, source_excerpt=excerpt[:200],
                    extraction_method="pdf_direct",
                    value_num=vnum, value_text=(None if vnum is not None else vtext),
                    is_forecast=1 if dp.get("is_forecast") else 0,
                    as_of_date=norm_date(dp.get("as_of_date")), sentiment=sent,
                    company_id=cid, note=dp.get("note"), auto_consensus=False)
                stats["dp_ok"] += 1
            except Exception as e:
                stats["dp_skip"] += 1
                print(f"[skip] {metric[:30]} | {e}", file=sys.stderr)
        for ka in data.get("key_arguments", []):
            sf = ka.get("source_file"); arg = (ka.get("argument") or "").strip()
            if sf in src_map and arg:
                ka_by_src.setdefault(sf, []).append({"claim": arg})
    conn.commit()

    # key_arguments 入 source
    for sf, args in ka_by_src.items():
        try:
            n = db_writer.write_key_arguments(conn, src_map[sf], args, merge=True)
            stats["ka"] += len(args)
        except Exception as e:
            print(f"[ka skip] {sf} | {e}", file=sys.stderr)
    conn.commit()

    # 全量重算 consensus(行业 13)
    import consensus_compute
    try:
        consensus_compute.recompute_all(IND_ID, conn=conn)
    except Exception as e:
        print(f"[WARN] recompute_all 失败: {e}", file=sys.stderr)
    conn.commit()

    stats["companies"] = conn.execute(
        "SELECT COUNT(DISTINCT company_id) FROM industry_data_point WHERE industry_id=? AND company_id IS NOT NULL",
        (IND_ID,)).fetchone()[0]

    # 输出 source_id 映射 + 报告
    out = ROOT / "cache" / "db_queue"
    (out / "电力_source_map.json").write_text(
        json.dumps(src_map, ensure_ascii=False, indent=2), encoding="utf-8")

    # 报告
    total_dp = conn.execute("SELECT COUNT(*) FROM industry_data_point WHERE industry_id=?", (IND_ID,)).fetchone()[0]
    cons = conn.execute("SELECT consensus_status, COUNT(*) FROM industry_data_point WHERE industry_id=? GROUP BY consensus_status", (IND_ID,)).fetchall()
    per_src = conn.execute("""SELECT s.id, s.title, s.value_layer, COUNT(dp.id) n
        FROM source s LEFT JOIN industry_data_point dp ON dp.source_id=s.id AND dp.industry_id=?
        WHERE s.file_path LIKE 'papers/电力/%' GROUP BY s.id ORDER BY n DESC""", (IND_ID,)).fetchall()
    lines = ["# 电力 #13 入库报告", "",
             f"- 新建 source: {stats['sources_new']} | 复用: {stats['sources_reuse']}",
             f"- 数据点入库: {stats['dp_ok']} | 跳过(缺字段): {stats['dp_skip']}",
             f"- key_arguments: {stats['ka']} | 关联公司: {stats['companies']}",
             f"- 行业 13 data_point 总数: {total_dp}", "",
             "## consensus 分布"]
    for c in cons:
        lines.append(f"- {c[0]}: {c[1]}")
    lines += ["", "## 每源 dp 数(source_id | value_layer | n | title)"]
    for r in per_src:
        lines.append(f"- src#{r['id']} | {r['value_layer']} | {r['n']} | {r['title'][:50]}")
    (out / "电力_ingest_report.md").write_text("\n".join(lines), encoding="utf-8")
    conn.close()
    print("\n".join(lines))
    print(f"\nsource_map → cache/db_queue/电力_source_map.json")


if __name__ == "__main__":
    main()
