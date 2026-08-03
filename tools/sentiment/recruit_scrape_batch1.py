#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Batch1 招聘抓取 runner(31 家)。
设计:import recruit_scrape(rs)复用其 beisen/montage/inspur/innolight 抽取器 + 全套
job 比对/change_log/recruit_source 状态更新逻辑(rs.process);monkeypatch rs.scrape 增加
moka / hotjob / static 抽取器。??绝不改 recruit_scrape.py(batch2/batch3 agent 并发编辑该文件)。
??绝不伪造 JD:抓不到 → None(unreachable)/[](js_blocked);static 用配置 selector,抓到产品名靠 JOB_RE 过滤。

配置来源:cache/recruit_batch1_config.json (list[dict])。每家一条:
  {ticker,name,company_id,career_url,extractor, scrape_path, platform_type,
   selector?(static用), loc_selector?(static用), status_note?}
用法:python recruit_scrape_batch1.py [--only 002281.SZ]  先 upsert recruit_source 再抓。
"""
from __future__ import annotations
import sys, re, json, argparse
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common
import recruit_scrape as rs

ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG = ROOT / "cache" / "recruit_batch1_config.json"
UA = rs.UA
JOB_RE = rs.JOB_RE
_orig_scrape = rs.scrape                      # 保存原始 dispatch,非 moka/hotjob/static 委托回去
STATIC_CFG: dict[str, dict] = {}             # url -> cfg(selector 等),static 抽取器用

_NATURE = {"急", "分享", "全职", "兼职", "实习", "急聘", "在招职位", "投递简历",
           "清除", "职位搜索", "工作地点", "已选", "结果", "更多", "查看详情", "申请职位"}


def _scrape_moka(url):
    """Moka(app.mokahr.com)平台:职位列表在 SPA 路由 <base>#/jobs;岗位=a[href*=#/job/];
    分页用 [class*=Pagination-item] 末项(下一页箭头)逐页点。职能=类别(技术类等),地点列表页常缺→None。"""
    from playwright.sync_api import sync_playwright
    base = url.split("#")[0].rstrip("/")
    target = base + "#/jobs"
    seen = {}
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
            pg = b.new_context(user_agent=UA, locale="zh-CN").new_page()
            try:
                pg.goto(target, timeout=40000, wait_until="domcontentloaded")
            except Exception:
                b.close(); return None
            pg.wait_for_timeout(6000)
            last, stall = -1, 0
            for _ in range(25):                                    # 逐页累积(每页~30)
                for c in pg.eval_on_selector_all('a[href*="#/job/"]',
                        "els=>els.map(e=>({h:e.getAttribute('href')||'',t:(e.innerText||'').trim()}))"):
                    uid = c["h"].split("#/job/")[-1].split("?")[0]
                    if uid:
                        seen[uid] = c["t"]
                n = len(seen)
                if n == last:
                    stall += 1
                else:
                    stall, last = 0, n
                if stall >= 3:
                    break
                items = pg.query_selector_all('[class*="Pagination-item"]')   # 末项=下一页箭头
                if items:
                    try:
                        items[-1].click(timeout=2000); pg.wait_for_timeout(1500)
                    except Exception:
                        pass
                else:
                    pg.mouse.wheel(0, 2500); pg.wait_for_timeout(800)
            b.close()
    except Exception as e:
        print(f"    [moka] {url} err {type(e).__name__} {str(e)[:50]}", file=sys.stderr)
        return None
    jobs, titles = [], set()
    for txt in seen.values():
        title, cat = None, None
        for line in txt.split("\n"):
            s = line.strip()
            s = re.sub(r"^(急聘|急|热招|新)\s*", "", s)        # 去掉紧急/热招角标前缀(部分站点与标题同节点)
            if not s or s in _NATURE or s.startswith("发布于") or s == "|":
                continue
            if s.endswith("类") and len(s) <= 6:
                cat = cat or s; continue
            if not title and 3 <= len(s) <= 40 and JOB_RE.search(s):
                title = s
        if title and title not in titles:
            titles.add(title)
            jobs.append({"title": title, "dept": cat, "location": None})
    return jobs


def _scrape_hotjob(url):
    """51job/wecruit.hotjob.cn(立讯/麦格米特/长电)ATS。suiteKey=URL 里的 SU+24hex;
    重放 listPosition JSON 接口(postName 标题 + workPlaceStr 地点 + postTypeName 职能 + totalPage 翻页),
    recruitType 2=社招 1=校招都取。接口干净不脑补。全失败→None。"""
    from playwright.sync_api import sync_playwright
    m = re.search(r"(SU[0-9a-fA-F]{24})", url)
    if not m:
        return None
    su = m.group(1)
    api = f"https://wecruit.hotjob.cn/wecruit/positionInfo/listPosition/{su}?iSaJAx=isAjax&request_locale=zh_CN"
    jobs, seen, ok = [], set(), False
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
            pg = b.new_context(user_agent=UA, locale="zh-CN").new_page()
            try:
                pg.goto(url, timeout=40000, wait_until="domcontentloaded"); pg.wait_for_timeout(3000)
            except Exception:
                pass                                               # 仍尝试接口
            for rt in (2, 1):                                      # 2=社招 1=校招
                page = 1
                while page <= 30:
                    body = f"isFrompb=true&recruitType={rt}&pageSize=50&currentPage={page}"
                    try:
                        resp = pg.request.post(api, data=body, headers={
                            "content-type": "application/x-www-form-urlencoded",
                            "x-requested-with": "XMLHttpRequest", "referer": url})
                        d = resp.json()
                    except Exception:
                        break
                    ok = True
                    pf = (d.get("data") or {}).get("pageForm") or {}
                    rows = pf.get("pageData") or []
                    if not rows:
                        break
                    for it in rows:
                        t = re.sub(r"\s+", " ", (it.get("postName") or "")).strip()
                        if not t or t in seen or len(t) > 50:
                            continue
                        seen.add(t)
                        jobs.append({"title": t, "dept": (it.get("postTypeName") or it.get("department") or None),
                                     "location": (it.get("workPlaceStr") or None)})
                    if page >= (pf.get("totalPage") or 1):
                        break
                    page += 1
            b.close()
    except Exception as e:
        print(f"    [hotjob] {url} err {type(e).__name__} {str(e)[:50]}", file=sys.stderr)
        return None
    return jobs if ok else None


def _scrape_static(url):
    """配置 selector 的静态/服务端渲染官网列表。cfg.selector=岗位标题元素;loc_selector 可选;
    no_job_re=True 时信任 selector 不做 JOB_RE 过滤(北森表格门户岗位名多样如「厨师/法务助理」);
    仍过滤导航词(_BAD)兜底。去 ??/急 角标前缀。无 selector → None(不脑补)。"""
    from playwright.sync_api import sync_playwright
    cfg = STATIC_CFG.get(url, {})
    sel = cfg.get("selector")
    loc_sel = cfg.get("loc_selector")
    no_re = bool(cfg.get("no_job_re"))
    if not sel:
        return None                                          # 无勘定 selector 不启发式,避免抓产品名
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
            pg = b.new_context(user_agent=UA, locale="zh-CN", ignore_https_errors=True).new_page()
            try:
                pg.goto(url, timeout=40000, wait_until="domcontentloaded")
            except Exception:
                b.close(); return None
            pg.wait_for_timeout(4000)
            titles = pg.eval_on_selector_all(sel, "els=>els.map(e=>(e.innerText||'').trim())")
            locs = pg.eval_on_selector_all(loc_sel, "els=>els.map(e=>(e.innerText||'').trim())") if loc_sel else []
            b.close()
    except Exception as e:
        print(f"    [static] {url} err {type(e).__name__} {str(e)[:50]}", file=sys.stderr)
        return None
    jobs, seen = [], set()
    for i, t in enumerate(titles):
        t = re.sub(r"\s+", " ", t or "").strip()
        t = re.sub(r"^[????※•]\s*", "", t)                    # 去??角标
        t = re.sub(r"^(急聘|急|热招|新)\s*", "", t)
        if not t or len(t) < 3 or len(t) > 40 or t in seen:
            continue
        if rs._BAD.search(t):                                # 丢导航/版权词
            continue
        if not no_re and not JOB_RE.search(t):               # 丢产品名(除非信任 selector)
            continue
        seen.add(t)
        loc = re.sub(r"\s+", " ", locs[i]).strip() if (loc_sel and i < len(locs) and locs[i]) else None
        jobs.append({"title": t, "dept": None, "location": loc})
    return jobs


def my_scrape(url, extractor, *args, **kwargs):
    if extractor == "moka":
        return _scrape_moka(url)
    if extractor == "hotjob":
        return _scrape_hotjob(url)
    if extractor == "static":
        return _scrape_static(url)
    return _orig_scrape(url, extractor, *args, **kwargs)     # beisen/montage/inspur/innolight/css/generic(委托回 rs,含其新增签名)


rs.scrape = my_scrape                                        # ?? monkeypatch dispatch


def upsert_sources(con, cfg_list, comps):
    now = common.now_iso()
    for s in cfg_list:
        cid = s.get("company_id")
        if cid is None or cid not in comps:
            print(f"  跳过(不在闭集): {s.get('ticker')}", file=sys.stderr); continue
        con.execute("""INSERT INTO recruit_source
                       (company_id,ticker,name,career_url,extractor,scrape_path,platform_type,discovered_at,active,status)
                       VALUES(?,?,?,?,?,?,?,?,1,?)
                       ON CONFLICT(company_id) DO UPDATE SET
                         career_url=excluded.career_url, extractor=excluded.extractor,
                         scrape_path=excluded.scrape_path, platform_type=excluded.platform_type,
                         name=excluded.name""",
                    (cid, s["ticker"], s["name"], s.get("career_url"), s.get("extractor"),
                     s.get("scrape_path"), s.get("platform_type"), now,
                     "todo" if not s.get("career_url") else "pending"))
        if s.get("extractor") == "static" and s.get("career_url"):
            STATIC_CFG[s["career_url"]] = s
    con.commit()


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--only", default=None); args = ap.parse_args()
    cfg_list = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else []
    con = common.get_senti_db(); common.assert_senti_only(con)
    comps, _ = common.load_closed_set()
    now, today = common.now_iso(), common.today()
    upsert_sources(con, cfg_list, comps)
    only = set(args.only.split(",")) if args.only else None   # --only 支持逗号多 ticker
    todo = [s for s in cfg_list if s.get("company_id") in comps and (not only or s["ticker"] in only)]
    # 确保 static selector 注册(--only 时 upsert 已填,这里兜底)
    for s in todo:
        if s.get("extractor") == "static" and s.get("career_url"):
            STATIC_CFG[s["career_url"]] = s
    print(f"Batch1 招聘源:{len(todo)} 家\n")
    for s in todo:
        src = {"company_id": s["company_id"], "ticker": s["ticker"],
               "name": s["name"], "url": s.get("career_url"), "extractor": s.get("extractor")}
        st, no, nn, ncl = rs.process(con, src, now, today)
        con.commit()
        print(f"  {s['name']:<8}{s['ticker']}: {st} | 在招{no} 新增{nn} 下架{ncl}")
    con.close()


if __name__ == "__main__":
    main()
