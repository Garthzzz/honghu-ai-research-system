#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""电力 #13 公司透视最小可用集:5 家主力的 company_profile(grounded 归母)+ PE(网搜单源)。

铁律:绝不编造。归母用已入库 grounded dp 口径(方正 ^src:397);PE 仅长江电力/中国核电
有可靠网搜单源(标 unverified、单源待核实、as_of=2026-05-31),其余 PE/PB/PS 留空(待 API)。
估值只填 PE/PB/PS(SOP §9#8 修正)。每个估值数值落 web_fetch dp 溯源。
"""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools" / "pipeline"))
import db_writer

IND = 13
# 公司: (name, ticker, 2025归母亿元, 2025yoy, 2026Q1yoy, china_rank, pe_ttm or None, summary)
COMPS = [
    ("长江电力", "600900.SH", 345.03, "+6%", "+30.5%", 1, 17.99,
     "长江干流梯级大水电龙头,现金流最稳、估值锚公用事业;2026Q1 来水改善归母大增"),
    ("华能国际", "600011.SH", 144.10, "+42%", "-9.8%", 2, None,
     "火电弹性代表,2025 煤价大跌驱动归母 +42%;2026Q1 随煤价反弹微降,容量电价托底"),
    ("中国广核", "003816.SZ", 97.65, "-10%", "-9.3%", 3, None,
     "核电牌照寡头之一(CR2),高利用小时低碳基荷;2025 归母 -10%"),
    ("中国核电", "601985.SH", 93.04, "+6%", "-34.2%", 4, 17.46,
     "核电牌照寡头之一(CR2),在运在建机组领先;2026Q1 核电板块电价/检修扰动归母下行"),
    ("龙源电力", "001289.SZ", 45.26, "-29%", "-14.8%", 5, None,
     "绿电龙头,2025 归母 -29%,受新能源电价/利用率承压,是绿电板块缩影"),
]
PE_EXCERPT = {
    "长江电力": "长江电力(600900)2026-05-31 收盘价 27.75 元,市盈率(TTM)约 17.99 倍(证券时报/investing 等财经站)",
    "中国核电": "中国核电(601985)市盈率(TTM)约 17.46 倍(gurufocus/搜狐证券等财经站,2026-05)",
}


def main():
    conn = db_writer.get_db()
    conn.execute("PRAGMA foreign_keys=ON")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(company)")}
    cp_cols = {r[1] for r in conn.execute("PRAGMA table_info(company_profile)")}

    # 1) 注册 1 个网搜估值 source(灰/单源,待多源核实)
    vsrc = conn.execute(
        """INSERT INTO source(title, source_type, publisher, publish_date, quality_tier,
            is_forward_looking, value_layer, fetch_method, source_credibility, language,
            is_primary_source, source_subtype, url)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("电力公司估值快照(2026-05-31 网搜单源)", "三方数据", "财经数据站(证券时报/investing/gurufocus 等)",
         "2026-05-31", 3, 0, "公司专项", "web_fetch", "unverified", "zh", 0, "financial_database",
         "https://www.stcn.com/")).lastrowid
    conn.execute("INSERT OR IGNORE INTO source_entity(source_id, entity_type, entity_id, coverage) VALUES(?,?,?,?)",
                 (vsrc, "industry", IND, "部分覆盖"))
    print(f"估值 source 注册: #{vsrc}")

    name2id = {r[1]: r[0] for r in conn.execute("SELECT id,name FROM company")}
    n_prof = 0
    for (name, ticker, ni, yoy25, yoyq1, rank, pe, summ) in COMPS:
        cid = name2id.get(name)
        if not cid:
            cid = conn.execute("INSERT INTO company(name) VALUES(?)", (name,)).lastrowid
            name2id[name] = cid
        conn.execute("INSERT OR IGNORE INTO company_industry(company_id, industry_id) VALUES(?,?)", (cid, IND))
        # company 基础字段
        sets, vals = [], []
        if "ticker" in cols:
            sets.append("ticker=?"); vals.append(ticker)
        if "listing_status" in cols:
            sets.append("listing_status=?"); vals.append("a_share")
        if pe is not None and "pe_ttm" in cols:
            sets.append("pe_ttm=?"); vals.append(pe)
            if "valuation_as_of" in cols:
                sets.append("valuation_as_of=?"); vals.append("2026-05-31")
            if "valuation_source_id" in cols:
                sets.append("valuation_source_id=?"); vals.append(vsrc)
        if sets:
            conn.execute(f"UPDATE company SET {','.join(sets)} WHERE id=?", (*vals, cid))
        # PE → web_fetch dp 溯源
        if pe is not None:
            db_writer.write_data_point(
                conn, industry_id=IND, metric="市盈率PE(TTM)", period="2026-05-31", unit="倍",
                source_id=vsrc, source_excerpt=PE_EXCERPT[name], extraction_method="web_fetch",
                value_num=pe, as_of_date="2026-05-31", sentiment="不适用", company_id=cid,
                note="网搜单源,待 API/多源核实", auto_consensus=False)
        # company_profile
        ni_series = json.dumps([
            {"period": "2025", "value": ni, "unit": "亿元", "yoy": yoy25, "source_ids": [397]},
            {"period": "2026Q1", "value": None, "unit": "亿元", "yoy": yoyq1, "source_ids": [397]},
        ], ensure_ascii=False)
        prof = {
            "company_id": cid, "industry_id": IND, "period": "2026Q1",
            "net_income_series": ni_series, "china_rank": rank, "in_china_table": 1,
            "in_global_table": 0, "is_china_tech_leader": 0,
            "listing_status": "a_share", "summary": summ,
            "source_ids": json.dumps([397, vsrc]), "last_verified_at": "2026-06-09",
        }
        prof = {k: v for k, v in prof.items() if k in cp_cols}
        keys = ",".join(prof.keys()); ph = ",".join("?" * len(prof))
        conn.execute(f"INSERT OR REPLACE INTO company_profile({keys}) VALUES({ph})", tuple(prof.values()))
        n_prof += 1
        print(f"  {name} (#{cid}) rank={rank} 2025归母={ni}亿{yoy25} PE={pe or '待回填'}")
    conn.commit()
    print(f"\ncompany_profile 写入 {n_prof} 家(in_china_table=1)")
    print(f"PE 已填: 长江电力 17.99 / 中国核电 17.46(网搜单源 as_of 2026-05-31);其余 PE/PB/PS 待 API 回填")
    conn.close()


if __name__ == "__main__":
    main()
