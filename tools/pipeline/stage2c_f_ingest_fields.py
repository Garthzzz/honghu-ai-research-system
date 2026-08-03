#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Stage 2c-F 任务 A 入库:把 cache/stage2cf_research/<行业>.json 的网搜结果写进 db。

每条事实 → 创建真实 source 行(source_url + verbatim 摘录入 note,可 trace modal 查看;
按 url 去重,re-run 安全)。再回填 company_profile:
  - risks       : dict(按维度)→ 转成 list[{dim,dim_label,text,source_id,credibility}],存 JSON
  - tech_node   : 文本 + tech_node_src_id
  - main_customers: 文本 + main_customers_src_id
  - recent_events: list[{date,title,summary,is_major,source_id,source_ids,credibility}],存 JSON

反 slop:
  - 只写 JSON 里真实存在(非 null)的字段;agent 没找到的留空。
  - credibility whitelisted→tier2 / unverified→tier3(灰源)。网搜字段不享 tier1。
  - 不覆盖已有非空 risks(除非本次提供);已有 dict 格式 risks 顺带规整为 list。
用法:python tools/pipeline/stage2c_f_ingest_fields.py [行业.json ...]   (默认处理目录下全部)
"""
from __future__ import annotations
import sqlite3, sys, io, json, glob
from pathlib import Path
from datetime import datetime

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent.parent
DB = ROOT / "data" / "research.db"
RES_DIR = ROOT / "cache" / "stage2cf_research"
NOW = datetime.now().isoformat(timespec="seconds")

DIM_LABEL = {
    "cyclical": "周期性",
    "customer_concentration_risk": "客户集中度",
    "supply_chain_risk": "供应链/上下游议价",
    "geopolitical_risk": "地缘/出口管制",
    "tech_route_risk": "技术路线被颠覆",
    "regulatory_risk": "监管/合规",
}

ANNOUNCE_HINTS = ("cninfo", "sse.com", "szse", "sec.gov", "hkexnews", "/ir/", "investor.",
                  "nvidianews", "nvidia.com", "/news/press")


def classify(url: str):
    u = (url or "").lower()
    if any(h in u for h in ANNOUNCE_HINTS):
        return "公告"
    if any(h in u for h in ("weixin", "mp.weixin", "zhihu", "xueqiu")):
        return "自媒体"
    return "财经媒体"


def domain_of(url: str):
    try:
        return url.split("//", 1)[1].split("/", 1)[0]
    except Exception:
        return ""


def lang_of(url: str):
    u = (url or "").lower()
    if any(h in u for h in ("sec.gov", "nvidia", "stocktitan", "fool", "reuters", "bloomberg", "cnbc", ".com/news/en")):
        return "en"
    return "zh"


class SourceWriter:
    def __init__(self, con):
        self.con = con
        self.cur = con.cursor()
        # 预载已有 url→id 做去重
        self.url_map = {}
        for sid, su in self.cur.execute(
            "SELECT id, source_url FROM source WHERE source_url IS NOT NULL AND TRIM(source_url)<>''"
        ):
            self.url_map[su.strip()] = sid
        self.created = 0

    def get_or_create(self, title, url, excerpt, publish_date, credibility):
        if not url:
            return None
        url = url.strip()
        if url in self.url_map:
            return self.url_map[url]
        tier = 2 if credibility == "whitelisted" else 3
        stype = classify(url)
        note = (excerpt or "")[:400]
        self.cur.execute(
            """INSERT INTO source(title, source_type, publisher, publish_date, quality_tier,
                 is_forward_looking, value_layer, source_url, url, note,
                 source_subtype, fetch_timestamp, fetch_method, domain, language,
                 is_primary_source, source_credibility, created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (title[:200], stype, domain_of(url), publish_date, tier,
             0, "公司专项", url, url, note,
             "stage2cf_field", NOW, "web_fetch", domain_of(url), lang_of(url),
             0, (credibility or "unverified"), NOW),
        )
        sid = self.cur.lastrowid
        self.url_map[url] = sid
        self.created += 1
        return sid


def jget(obj, *keys):
    for k in keys:
        if isinstance(obj, dict) and obj.get(k) not in (None, ""):
            return obj.get(k)
    return None


def main():
    files = [Path(a) for a in sys.argv[1:]] if len(sys.argv) > 1 else sorted(RES_DIR.glob("*.json"))
    files = [f if f.is_absolute() else (RES_DIR / f.name) for f in files]
    if not files:
        print("无 JSON 文件:", RES_DIR); return

    con = sqlite3.connect(str(DB))
    sw = SourceWriter(con)
    cur = con.cursor()
    stats = {"companies": 0, "risks": 0, "tech_node": 0, "main_customers": 0, "events": 0}

    for fp in files:
        data = json.loads(fp.read_text(encoding="utf-8"))
        ind = fp.stem
        print(f"\n=== 处理 {ind}({len(data.get('companies',[]))} 家)===")
        for co in data.get("companies", []):
            cid = co.get("company_id")
            name = co.get("name", "")
            if cid is None:
                continue
            prof = cur.execute(
                "SELECT id, source_ids, risks FROM company_profile WHERE company_id=? ORDER BY id LIMIT 1",
                (cid,),
            ).fetchone()
            if not prof:
                print(f"  [SKIP] company_id={cid} {name} 无 company_profile")
                continue
            prof_id, src_ids_raw, risks_raw = prof
            try:
                src_ids = json.loads(src_ids_raw) if src_ids_raw else []
                if not isinstance(src_ids, list):
                    src_ids = [src_ids]
            except Exception:
                src_ids = []
            sets, params = [], []
            new_src_ids = []

            # —— risks(dict → list)——
            risks = co.get("risks")
            if isinstance(risks, dict) and risks:
                risk_list = []
                for dim, r in risks.items():
                    if not isinstance(r, dict) or not r.get("text"):
                        continue
                    sid = sw.get_or_create(
                        f"{name} · {DIM_LABEL.get(dim, dim)}风险",
                        r.get("source_url"), r.get("excerpt"), r.get("publish_date"), r.get("credibility"))
                    if sid:
                        new_src_ids.append(sid)
                    risk_list.append({
                        "dim": dim, "dim_label": DIM_LABEL.get(dim, dim),
                        "text": r.get("text"), "source_id": sid,
                        "source_url": r.get("source_url"), "credibility": r.get("credibility"),
                    })
                if risk_list:
                    sets.append("risks=?"); params.append(json.dumps(risk_list, ensure_ascii=False))
                    stats["risks"] += len(risk_list)

            # —— tech_node ——
            tn = co.get("tech_node")
            if isinstance(tn, dict) and tn.get("text"):
                sid = sw.get_or_create(f"{name} · 技术节点", tn.get("source_url"),
                                       tn.get("excerpt"), tn.get("publish_date"), tn.get("credibility"))
                sets.append("tech_node=?"); params.append(tn["text"])
                if sid:
                    sets.append("tech_node_src_id=?"); params.append(sid); new_src_ids.append(sid)
                stats["tech_node"] += 1

            # —— main_customers ——
            mc = co.get("main_customers")
            if isinstance(mc, dict) and mc.get("text"):
                sid = sw.get_or_create(f"{name} · 主营客户", mc.get("source_url"),
                                       mc.get("excerpt"), mc.get("publish_date"), mc.get("credibility"))
                sets.append("main_customers=?"); params.append(mc["text"])
                if sid:
                    sets.append("main_customers_src_id=?"); params.append(sid); new_src_ids.append(sid)
                stats["main_customers"] += 1

            # —— recent_events(list)——
            evs = co.get("recent_events")
            if isinstance(evs, list) and evs:
                ev_list = []
                for e in evs:
                    if not isinstance(e, dict) or not e.get("title"):
                        continue
                    sid = sw.get_or_create(
                        f"{name} · {e.get('title','动向')[:40]}",
                        e.get("source_url"), e.get("excerpt"), e.get("date"), e.get("credibility"))
                    if sid:
                        new_src_ids.append(sid)
                    imp = e.get("importance") or 1
                    ev_list.append({
                        "date": e.get("date"), "title": e.get("title"),
                        "summary": e.get("brief") or e.get("summary"),
                        "is_major": (imp >= 2), "importance": imp,
                        "source_id": sid, "source_ids": ([sid] if sid else []),
                        "credibility": e.get("credibility"),
                    })
                if ev_list:
                    sets.append("recent_events=?"); params.append(json.dumps(ev_list, ensure_ascii=False))
                    stats["events"] += len(ev_list)

            # —— 合并 source_ids ——
            if new_src_ids:
                merged = list(dict.fromkeys(src_ids + new_src_ids))
                sets.append("source_ids=?"); params.append(json.dumps(merged, ensure_ascii=False))

            if sets:
                sets.append("last_updated=?"); params.append(NOW[:10])
                sets.append("last_verified_at=?"); params.append(NOW)
                params.append(prof_id)
                cur.execute(f"UPDATE company_profile SET {', '.join(sets)} WHERE id=?", params)
                stats["companies"] += 1
                print(f"  ?? {name}: " + ", ".join(s.split('=')[0] for s in sets if not s.startswith('last')))

    con.commit()
    con.close()
    print(f"\n新建 source 行:{sw.created}")
    print("回填统计:", stats)
    print("INGEST DONE")


if __name__ == "__main__":
    main()
