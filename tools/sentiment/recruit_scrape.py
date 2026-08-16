#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""招聘代理:每周抓各公司官网招贤纳士页 → recruit_job(open/closed 比对新增/下架)+ recruit_change_log(历史)。
只写 sentiment.db。??绝不伪造 JD:官网 JS 渲染走 Playwright 真浏览器;抓不到标 status,不造。
??一次性配置各家招聘页位置在 SOURCES(URL + 抽取器);新公司在此加一行。
用法:python recruit_scrape.py [--only 300308.SZ]
"""
from __future__ import annotations
import os, sys, re, json, hashlib, argparse
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common
from tools.data_platform.run_domain_operation import derived_operation_id

# ?? 各公司官网招贤纳士页位置(一次性记录;待补的标 url=None status=todo)
SOURCES = [
    {"ticker": "300308.SZ", "name": "中际旭创", "url": "https://www.zj-innolight.com/index/index/join.html", "extractor": "innolight"},
    {"ticker": "300502.SZ", "name": "新易盛",   "url": "https://eoptolink.zhiye.com/campus", "extractor": "beisen"},
    {"ticker": "300394.SZ", "name": "天孚通信", "url": "https://tfcsz.zhiye.com/social", "extractor": "beisen"},
    {"ticker": "002230.SZ", "name": "科大讯飞", "url": "https://iflytek.zhiye.com/social", "extractor": "beisen"},  # 北森,复用
    {"ticker": "301308.SZ", "name": "江波龙",   "url": "https://longsys.zhiye.com/social", "extractor": "beisen"},  # 北森,复用
    # URL已一次性勘定,但页面非标准列表(自有SaaS / generic 抓到产品名而非岗位)→ todo 待定制抽取器,不上噪声
    {"ticker": "000977.SZ", "name": "浪潮信息", "url": "https://inspur.hcmcloud.cn/recruit", "extractor": "inspur"},  # 海岳HCM:DOM(关弹窗→社招→虚拟滚动)
    {"ticker": "688008.SH", "name": "澜起科技", "url": "https://www.montage-tech.com/cn/Open_Positions", "extractor": "montage"},  # Drupal服务端渲染 div.job-title
    {"ticker": "002371.SZ", "name": "北方华创", "url": "https://career.naura.com/social", "extractor": "beisen"},  # 真ATS=career.naura.com 北森,复用
    # 无在线岗位列表:投递走微信公众号/邮箱,官网无可抓的在招岗位列表 → 客观不可得,如实标注,绝不伪造
    {"ticker": "601138.SH", "name": "工业富联", "url": "https://campus.fii-foxconn.com/", "extractor": "manual"},  # 社招走微信「灯塔学苑」+邮箱
    {"ticker": "002156.SZ", "name": "通富微电", "url": "https://www.tfme.com/news/4/", "extractor": "manual"},      # 招贤纳士页岗位陈旧,投递走微信/邮箱
    {"ticker": "002463.SZ", "name": "沪电股份", "url": "http://www.wustec.com/hr.php", "extractor": "manual"},      # 自建页反爬,投递走邮箱
]

# ?? 静态官网招聘页的 CSS 选择器(extractor="css" 用;按 ticker 一次性勘定)。
#   title=职位标题选择器(必填);loc=地点(可选);dept=部门(可选)。
#   选择器要尽量精确锁到职位标题元素,避开表头/导航;_scrape_css 仍过滤导航词。
CSS_STATIC = {
    # —— batch2(31家)中的静态官网招聘页选择器 ——
    "688048.SH": {"title": ".div1.fnt_16"},                                                                # 长光华芯 everbrightphotonics(首页,站点有分页)
    "688449.SH": {"title": ".col-sm-3 .card-body .title"},                                                 # 联芸科技 maxio-tech /job(col-sm-3=岗位卡,col-sm-4=福利卡排除)
    "300806.SZ": {"title": ".worknav h4"},                                                                 # 斯迪克 sidike About/join
    "300456.SZ": {"title": "p.e_text-19.fnt_18"},                                                          # 赛微电子 smeiic Human(职位发布日偏旧)
    "688072.SH": {"title": "table tr td:nth-child(2)",                                                     # 拓荆科技 piotech Join/join 表格(发布时间|职位|地点|薪资)
                  "loc": "table tr td:nth-child(3)"},
    "301312.SZ": {"title": "h3.g-search-content"},                                                         # 智立方 incubecn 社招faq h3
    "688126.SH": {"title": ".join_listItem .list_name a"},                                                 # 沪硅产业(子公司新昇 zingsemi,投递转51job)
    "688498.SH": {"title": "#n_zhaopin dl dd h5 .top01"},                                                  # 源杰科技 静态dl/dd
    "688205.SH": {"title": ".e_loop-65 .s_title a"},                                                       # 德科立 上线了CMS,职位链/JobPosting_Detail
    "688195.SH": {"title": ".news-item .news-h"},                                                          # 腾景科技 optowide list
    "688808.SH": {"title": "li.wow.fadeInUp .clearfix>div:nth-child(1)",                                   # 联讯仪器 cn.semight 列表
                  "loc": "li.wow.fadeInUp .clearfix>div:nth-child(2)"},
    "002957.SZ": {"title": ".joinshgw-menu .main span:nth-child(1)",                                       # 科瑞技术 colibri /Join
                  "loc": ".joinshgw-menu .main span:nth-child(2)"},
    "688766.SH": {"title": ".me_bottom .one p.f26"},                                                       # 普冉股份 (仅当前页)
    "300042.SZ": {"title": ".job-data-row .job-data-cell:nth-child(1)"},                                   # 朗科科技 表格
    "688521.SH": {"title": ".careertabcont h3"},                                                           # 芯原股份 verisilicon
    "688120.SH": {"title": ".table-row .table-row-item:nth-child(2)",                                      # 华海清科 表格(类别/职位/学历/地点)
                  "loc": ".table-row .table-row-item:nth-child(4)",
                  "dept": ".table-row .table-row-item:nth-child(1)"},
    "688200.SH": {"title": ".job_item .item .tit span:nth-child(1)",                                       # 华峰测控 hftc
                  "loc": ".job_item .item .tit span:nth-child(2)"},
    "688234.SH": {"title": ".zpbox table tr:not(.bgt) td:nth-child(1)",                                    # 天岳先进 sicc 社招表
                  "loc": ".zpbox table tr:not(.bgt) td:nth-child(2)"},
    "300054.SZ": {"title": ".e_loop-4 .s_summary a"},                                                      # 鼎龙股份 上线了CMS h3标题
    "688362.SH": {"title": ".fyzplbsub .fyzpzw"},                                                          # 甬矽电子 forehope(Playwright可过,本地requests :80拒)
}
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
JOB_RE = re.compile(r"(工程师|经理|主管|专员|总监|研发|测试|架构师|顾问|分析师|设计师|助理|实习生?|运营|产品|算法|开发|采购|销售|财务|质量|工艺|结构|硬件|软件|光学|封装|HR|IT|总裁|代表|储备干部|技术员|物料|生产|工程|项目)")
_BAD = re.compile(r"(登录|注册|首页|关于|联系|搜索|更多|查看|投递|简历|社会招聘|校园招聘|招贤纳士|人才招聘|职位名称|岗位名称|招聘职位|工作地点|发布时间|招聘人数|返回|下一页|上一页|版权|备案|Copyright|©|cookie)")


def sha1(s):
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def _scrape_beisen(pg, url):
    """北森(Beisen / *.zhiye.com)平台:截获页面对 GetJobAdPageList 的请求拿 PortalId,
    再用同 context 的 request 重放 PageSize=200 一次取全(社招 Category=1 + 校招=2)。
    PortalId 每家不同但自动发现 → 对所有北森门户通用(新易盛/天孚/未来)。
    ?? 兼容新版布局(/jobs):新版请求体 PortalId 为空串(服务端靠 Host/cookie 识别租户),
      故只要捕到 GetJobAdPageList 端点即可,重放沿用同 context 的 cookie(PortalId 传空也返职位)。"""
    cap = {}
    def on_req(r):
        if "GetJobAdPageList" in r.url and r.post_data and "api" not in cap:
            try:
                pd = json.loads(r.post_data)
                cap["id"] = pd.get("PortalId", "")    # 新版为空串;老版为真实租户号,均接受
                cap["api"] = r.url
            except Exception:
                pass
    pg.on("request", on_req)
    try:                                              # 北森常驻轮询→networkidle永不触发,用 domcontentloaded
        pg.goto(url, timeout=35000, wait_until="domcontentloaded")
    except Exception:
        pass
    for _ in range(24):                               # 轮询等职位列表 XHR 触发(最多~12s,缓解美国IP→中国站时序)
        if cap.get("api"):
            break
        pg.wait_for_timeout(500)
    if "api" not in cap:
        return None                                   # 没截到 API → 交回 None,不脑补
    jobs, seen = [], set()
    for cat in (["1"], ["2"]):                          # 1=社会招聘 2=校园招聘
        body = {"Category": cat, "PageIndex": 0, "PageSize": 200, "KeyWords": "",
                "SpecialType": 0, "PortalId": cap.get("id", ""),
                "DisplayFields": ["Category", "JobAdName", "Org", "LocNames"]}
        try:
            resp = pg.request.post(cap["api"], data=json.dumps(body),
                                   headers={"content-type": "application/json",
                                            "x-requested-with": "XMLHttpRequest", "referer": url})
            d = resp.json()
        except Exception:
            continue
        for it in (d.get("Data") or []):
            title = re.sub(r"\s+", " ", (it.get("JobAdName") or "")).strip()
            if not title or title in seen or len(title) > 40 or _BAD.search(title):
                continue
            seen.add(title)
            loc = "/".join([x for x in (it.get("LocNames") or []) if x]) or None
            dept = it.get("Org") or None
            jobs.append({"title": title, "dept": dept, "location": loc})
    return jobs


def _scrape_beisen_api(pg, url):
    """北森门户落地页不自动触发 GetJobAdPageList(envicool/cnnp 等)时的兜底:
    从 portal-oss URL / GetPageGlobalModules / 页面 HTML 发现 PortalId,
    直连 https://{host}/api/JobAd/GetJobAdPageList 重放取全(社招 Category=1 + 校招=2)。"""
    host = url.split("//", 1)[-1].split("/", 1)[0]
    cap = {}
    def on_req(r):
        if "pid" not in cap:
            m = re.search(r"portal-oss\.zhiye\.com/(\d{4,})/", r.url)
            if m:
                cap["pid"] = m.group(1)
    def on_resp(r):
        if "pid" not in cap and "GetPageGlobalModules" in r.url:
            try:
                m = re.search(r'[Pp]ortalId["\':=\s]+"?(\d{4,})', json.dumps(r.json()))
                if m:
                    cap["pid"] = m.group(1)
            except Exception:
                pass
    pg.on("request", on_req)
    pg.on("response", on_resp)
    try:
        pg.goto(url, timeout=40000, wait_until="domcontentloaded")
    except Exception:
        return None
    for _ in range(20):
        if cap.get("pid"):
            break
        pg.wait_for_timeout(500)
    if not cap.get("pid"):                              # 末路:扫页面 HTML
        try:
            m = re.search(r'[Pp]ortalId["\':=\s]+"?(\d{4,})', pg.content())
            if m:
                cap["pid"] = m.group(1)
        except Exception:
            pass
    if not cap.get("pid"):
        return None                                    # 发现不到 PortalId → None,不脑补
    api = f"https://{host}/api/JobAd/GetJobAdPageList"
    jobs, seen = [], set()
    for cat in (["1"], ["2"]):
        body = {"Category": cat, "PageIndex": 0, "PageSize": 500, "KeyWords": "",
                "SpecialType": 0, "PortalId": cap["pid"],
                "DisplayFields": ["Category", "JobAdName", "Org", "LocNames"]}
        try:
            resp = pg.request.post(api, data=json.dumps(body),
                                   headers={"content-type": "application/json",
                                            "x-requested-with": "XMLHttpRequest", "referer": url})
            d = resp.json()
        except Exception:
            continue
        for it in (d.get("Data") or []):
            title = re.sub(r"\s+", " ", (it.get("JobAdName") or "")).strip()
            if not title or title in seen or len(title) > 50 or _BAD.search(title):
                continue
            seen.add(title)
            loc = "/".join([x for x in (it.get("LocNames") or []) if x]) or None
            dept = it.get("Org") or None
            jobs.append({"title": title, "dept": dept, "location": loc})
    return jobs


def _scrape_montage(pg, url):
    """澜起科技 montage-tech.com/cn/Open_Positions:Drupal 服务端渲染,每个岗位一块 div.job-head。"""
    try:
        pg.goto(url, timeout=35000, wait_until="domcontentloaded")
        pg.wait_for_timeout(3000)
    except Exception:
        return None
    rows = pg.eval_on_selector_all("div.job-head", """els => els.map(e => ({
        t: ((e.querySelector('.job-title')||{}).innerText || '').trim(),
        d: ((e.querySelector('.job-department')||{}).innerText || '').trim(),
        l: ((e.querySelector('.job-location')||{}).innerText || '').trim() }))""")
    if not rows:                                       # 兜底:直接抓 .job-title(div,非筛选 option)
        ts = pg.eval_on_selector_all("div.job-title", "els => els.map(e => (e.innerText||'').trim())")
        rows = [{"t": t, "d": "", "l": ""} for t in ts]
    jobs, seen = [], set()
    for r in rows:
        t = re.sub(r"\s+", " ", r.get("t") or "").strip()
        if not t or t in seen or len(t) > 70:
            continue
        seen.add(t)
        jobs.append({"title": t, "dept": (r.get("d") or None), "location": (r.get("l") or None)})
    return jobs


def _scrape_inspur(pg, url):
    """浪潮信息 inspur.hcmcloud.cn:SPA + 隐私弹窗 + 社招tab + 虚拟滚动表格(行 div.table-cell[col-key=name])。"""
    try:
        pg.goto(url, timeout=40000, wait_until="domcontentloaded")
        pg.wait_for_timeout(5000)
    except Exception:
        return None
    for txt in ("我已阅读并同意", "同意并继续", "同意", "我知道了"):   # 关隐私弹窗
        try:
            el = pg.query_selector(f"text={txt}")
            if el:
                el.click(timeout=2000); pg.wait_for_timeout(1500); break
        except Exception:
            pass
    try:                                               # 切到「社会招聘」
        el = pg.query_selector("text=社会招聘")
        if el:
            el.click(timeout=2000); pg.wait_for_timeout(3500)
    except Exception:
        pass
    sel = 'div.table-cell[col-key="name"] .cell-content'
    seen, last_n, stall = {}, -1, 0
    for _ in range(50):                                # 虚拟滚动:逐屏滚动累积(下屏会回收上屏 DOM)
        for t in pg.eval_on_selector_all(sel, "els => els.map(e => (e.innerText||'').trim())"):
            tt = re.sub(r"\s+", " ", t or "").strip()
            if tt and 2 <= len(tt) <= 40:
                seen[tt] = 1
        if len(seen) == last_n:
            stall += 1
            if stall >= 4:
                break
        else:
            stall, last_n = 0, len(seen)
        try:
            pg.mouse.move(600, 400); pg.mouse.wheel(0, 1400); pg.wait_for_timeout(700)
        except Exception:
            break
    return [{"title": t, "dept": None, "location": None} for t in seen]


def _scrape_css(pg, url, conf):
    """通用静态官网招聘页:用每家一次性勘定的 CSS 选择器(conf={'title':sel,'loc':sel?,'dept':sel?})
    取职位标题/地点/部门。选择器没勘定 → None(不脑补)。仍过滤导航词/产品名兜底。"""
    if not conf or not conf.get("title"):
        return None
    try:
        pg.goto(url, timeout=35000, wait_until="domcontentloaded")
        pg.wait_for_timeout(3000)
    except Exception:
        return None
    JS = "els => els.map(e => (e.innerText||e.textContent||'').trim())"
    try:
        titles = pg.eval_on_selector_all(conf["title"], JS)
    except Exception:
        return None
    locs = pg.eval_on_selector_all(conf["loc"], JS) if conf.get("loc") else []
    depts = pg.eval_on_selector_all(conf["dept"], JS) if conf.get("dept") else []
    jobs, seen = [], set()
    for i, t in enumerate(titles):
        tt = re.sub(r"\s+", " ", t or "").strip()
        if not tt or tt in seen or not (2 <= len(tt) <= 60) or _BAD.search(tt):
            continue
        seen.add(tt)
        loc = re.sub(r"\s+", " ", locs[i]).strip() if i < len(locs) and locs[i] else None
        dept = re.sub(r"\s+", " ", depts[i]).strip() if i < len(depts) and depts[i] else None
        jobs.append({"title": tt, "dept": (dept or None), "location": (loc or None)})
    return jobs


def _scrape_moka(pg, url):
    """Moka(app.mokahr.com)SPA:落地页只给「城市×计数」摘要,需进 #/jobs 列表页抓职位卡。
    职位卡 = a[href*='#/job/'],干净标题在内部 [class*='title-'](兜底解析卡片文本行);
    分页用 [class*='Pagination-item'] 数字页码(无「下一页」文本)。
    ?? API 响应加密(necromancer 字段)不可直接解析,故走渲染后 DOM;抓不到职位卡→None 不脑补。
    URL 形如 https://app.mokahr.com/social-recruitment/<slug>/<siteId>(社招;校招另一 siteId 不在此抓)。"""
    base = url.split("#")[0]
    try:
        pg.goto(base, timeout=40000, wait_until="domcontentloaded")
        pg.wait_for_timeout(5000)
        pg.goto(base + "#/jobs", timeout=40000, wait_until="domcontentloaded")
        pg.wait_for_timeout(6000)
    except Exception:
        return None
    extract_js = (
        "() => { const out=[];"
        "document.querySelectorAll('a[href*=\"#/job/\"]').forEach(a=>{"
        "  const te=a.querySelector('[class*=\"title-\"]');"
        "  let title = te ? te.innerText.trim() : '';"
        "  const ls=(a.innerText||'').split('\\n').map(s=>s.trim()).filter(Boolean);"
        "  if(!title){ title = ls.find(s=>!/^(急|紧急|new|NEW|HOT|热)$/.test(s) && !/^发布于/.test(s)) || ''; }"
        "  let dept=null; const idx=ls.findIndex(s=>/^发布于/.test(s));"
        "  if(idx>=0 && ls[idx+1]) dept=ls[idx+1];"
        "  out.push({title, dept}); }); return out; }"
    )
    total = None
    try:
        m = re.search(r"(\d+)\s*结果", pg.eval_on_selector("body", "e=>e.innerText") or "")
        if m:
            total = int(m.group(1))
    except Exception:
        pass
    collected = {}

    def add():
        try:
            for r in pg.evaluate(extract_js):
                t = re.sub(r"\s+", " ", (r.get("title") or "")).strip()
                if t and 2 <= len(t) <= 40:
                    collected.setdefault(t, r.get("dept"))
        except Exception:
            pass

    add()
    if not collected:
        return None                                    # 没渲染出职位卡 → None,不脑补

    def pager_items():
        out = []
        for it in pg.query_selector_all('[class*="Pagination-item"]'):
            t = (it.inner_text() or "").strip()
            if t.isdigit():
                out.append((int(t), it))
        return out

    def click_page(n):
        for v, it in pager_items():
            if v == n:
                try:
                    it.click(timeout=3000); return True
                except Exception:
                    return False
        return False

    target, guard, last_shift = 2, 0, -1
    while (total is None or len(collected) < total) and guard < 60:
        guard += 1
        if click_page(target):
            pg.wait_for_timeout(2500); add(); target += 1; continue
        below = [v for v, _ in pager_items() if v < target]
        if below and max(below) != last_shift:
            last_shift = max(below); click_page(last_shift); pg.wait_for_timeout(2000); continue
        break
    return [{"title": t, "dept": d, "location": None} for t, d in collected.items()]


def _scrape_yanmade(pg, url):
    """燕麦科技 job.yanmade.com:自建系统但有干净 JSON API
    getJobInfoListBy{Gra=社招,Exer=校招}.action?page&limit → data[].{job_name,job_city,jobTy_name}。"""
    base = "https://job.yanmade.com"
    try:
        pg.goto(url, timeout=35000, wait_until="domcontentloaded")
        pg.wait_for_timeout(1500)
    except Exception:
        return None
    jobs, seen, got_any = [], set(), False
    for action in ("getJobInfoListByGra.action", "getJobInfoListByExer.action"):
        for page in range(1, 13):
            api = f"{base}/{action}?page={page}&limit=50"
            try:
                resp = pg.request.get(api, headers={"x-requested-with": "XMLHttpRequest", "referer": url})
                d = resp.json()
            except Exception:
                break
            rows = d.get("data") or []
            got_any = got_any or bool(resp.ok)
            if not rows:
                break
            for it in rows:
                title = re.sub(r"\s+", " ", (it.get("job_name") or "")).strip()
                if not title or title in seen or not (2 <= len(title) <= 60):
                    continue
                seen.add(title)
                loc = it.get("job_city") or None
                dept = it.get("jobTy_name") or it.get("job_direction") or None
                jobs.append({"title": title, "dept": dept, "location": loc})
            if len(rows) < 50:
                break
    return jobs if got_any else None


def scrape(url, extractor, ticker=None):
    """Playwright 抓职位标题列表。返回 list[{title,dept,location}] 或 None(抓不到)。"""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
            pg = b.new_context(user_agent=UA, locale="zh-CN").new_page()
            if extractor == "beisen":
                jobs = _scrape_beisen(pg, url)
                b.close()
                return jobs
            if extractor == "beisen_api":
                jobs = _scrape_beisen_api(pg, url)
                b.close()
                return jobs
            if extractor == "montage":
                jobs = _scrape_montage(pg, url)
                b.close()
                return jobs
            if extractor == "inspur":
                jobs = _scrape_inspur(pg, url)
                b.close()
                return jobs
            if extractor == "css":
                jobs = _scrape_css(pg, url, CSS_STATIC.get(ticker))
                b.close()
                return jobs
            if extractor == "moka":
                jobs = _scrape_moka(pg, url)
                b.close()
                return jobs
            if extractor == "yanmade":
                jobs = _scrape_yanmade(pg, url)
                b.close()
                return jobs
            pg.goto(url, timeout=35000, wait_until="domcontentloaded")
            pg.wait_for_timeout(3500)                  # 等 JS 渲染职位
            if extractor == "innolight":
                # 定制:.joindw1=职位标题(部门字段页面不规整,不强取,留 None 不造)
                titles = pg.eval_on_selector_all(".joindw1", "els => els.map(e => (e.innerText||'').trim())")
                b.close()
                jobs, seen = [], set()
                for t in titles:
                    tt = re.sub(r"\s+", " ", t or "").strip()
                    if tt and tt not in seen and 2 <= len(tt) <= 28:
                        seen.add(tt)
                        jobs.append({"title": tt, "dept": None, "location": None})
                return jobs
            # generic / beisen:抓候选职位文本(启发式)
            texts = pg.eval_on_selector_all(
                "a, li, td, h3, h4, h5, .job, .position, [class*=job], [class*=position], [class*=Job], [class*=post]",
                "els => els.map(e => (e.innerText||'').trim()).filter(t => t && t.length<=28)")
            b.close()
    except Exception as e:
        print(f"    [scrape] {url} err {type(e).__name__} {str(e)[:50]}", file=sys.stderr)
        return None
    jobs, seen = [], set()
    for t in texts:
        t = re.sub(r"\s+", " ", t).strip()
        if len(t) < 3 or len(t) > 28 or _BAD.search(t) or not JOB_RE.search(t):
            continue
        if t in seen:
            continue
        seen.add(t)
        jobs.append({"title": t, "dept": None, "location": None})
    return jobs


def process(con, src, now, today):
    cid = src["company_id"]; ticker = src["ticker"]; url = src.get("url")
    if not url:
        con.execute("UPDATE recruit_source SET status='todo', last_checked=? WHERE company_id=?", (now, cid))
        return "todo", 0, 0, 0
    if src.get("extractor") == "todo":                 # URL已勘定但抽取器待定制 → 只记URL不抓,不上噪声
        con.execute("UPDATE recruit_source SET status='待定制', career_url=?, last_checked=? WHERE company_id=?", (url, now, cid))
        return "待定制(URL已录,抽取器一次性待写)", 0, 0, 0
    if src.get("extractor") == "manual":               # 无在线岗位列表(微信/邮箱投递)→ 客观不可得,记URL不抓,不伪造
        con.execute("UPDATE recruit_source SET status='无在线列表', career_url=?, last_checked=? WHERE company_id=?", (url, now, cid))
        return "无在线列表(微信/邮箱投递,客观不可得)", 0, 0, 0
    jobs = scrape(url, src["extractor"], src.get("ticker"))
    if jobs is None:
        con.execute("UPDATE recruit_source SET status='unreachable', last_checked=? WHERE company_id=?", (now, cid))
        return "unreachable", 0, 0, 0
    if not jobs:
        con.execute("UPDATE recruit_source SET status='js_blocked', last_checked=?, n_jobs=0 WHERE company_id=?", (now, cid))
        return "js_blocked(0职位,可能需定制抽取)", 0, 0, 0
    seen_keys, new_titles = set(), []
    for j in jobs:
        key = sha1(f"{cid}|{j['title']}")
        seen_keys.add(key)
        row = con.execute("SELECT id FROM recruit_job WHERE company_id=? AND job_key=?", (cid, key)).fetchone()
        if row:
            con.execute("UPDATE recruit_job SET last_seen=?, status='open' WHERE id=?", (now, row[0]))
        else:
            con.execute("""INSERT INTO recruit_job(company_id,ticker,job_key,title,dept,location,first_seen,last_seen,status,source_url,fetched_at)
                           VALUES(?,?,?,?,?,?,?,?, 'open',?,?)""",
                        (cid, ticker, key, j["title"], j["dept"], j["location"], now, now, url, now))
            new_titles.append(j["title"])
    closed_titles = []
    for r in con.execute("SELECT id, job_key, title FROM recruit_job WHERE company_id=? AND status='open'", (cid,)).fetchall():
        if r["job_key"] not in seen_keys:
            con.execute("UPDATE recruit_job SET status='closed' WHERE id=?", (r["id"],))
            closed_titles.append(r["title"])
    n_open = len(seen_keys)
    con.execute("""INSERT INTO recruit_change_log(company_id,ticker,run_date,n_open,n_new,n_closed,new_titles,closed_titles,fetched_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (cid, ticker, today, n_open, len(new_titles), len(closed_titles),
                 json.dumps(new_titles, ensure_ascii=False), json.dumps(closed_titles, ensure_ascii=False), now))
    con.execute("UPDATE recruit_source SET status='ok', last_checked=?, n_jobs=? WHERE company_id=?", (now, n_open, cid))
    return "ok", n_open, len(new_titles), len(closed_titles)


def load_db_sources(con):
    """从 recruit_source 表读取已配置(career_url 非空 + extractor 非 todo)的公司,合并进抓取清单。
    这样新公司只需 INSERT recruit_source 行(career_url/extractor/scrape_path),无需改本文件 SOURCES。
    SOURCES 里已有的 ticker 以 SOURCES 为准(避免重复)。"""
    have = {s["ticker"] for s in SOURCES}
    extra = []
    for r in con.execute("""SELECT company_id, ticker, name, career_url, extractor FROM recruit_source
                            WHERE career_url IS NOT NULL AND TRIM(career_url)<>'' AND ticker NOT IN ({})"""
                         .format(",".join("?" * len(have)) or "''"), tuple(have)).fetchall():
        extra.append({"ticker": r["ticker"], "name": r["name"], "url": r["career_url"],
                      "extractor": r["extractor"] or "generic", "company_id": r["company_id"]})
    return extra


def _operation_connection(step: str):
    """Open one retry-stable mutation stream for one scrape step."""

    operation_id = (
        derived_operation_id(step)
        if os.environ.get("HONGHU_OPERATION_ID", "").strip()
        else None
    )
    connection = common.get_senti_db(
        operation_scope="recruit_scrape_step",
        operation_id=operation_id,
    )
    common.assert_senti_only(connection)
    return connection


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--only", default=None)
    args = ap.parse_args()
    comps, _ = common.load_closed_set()
    rc = common.research_ro_conn()
    now = common.now_iso(); today = common.today()
    # 合并 DB 中已配置的额外公司源(agent 录入的 93 家)
    registry_con = _operation_connection("source-registry")
    try:
        ALL_SOURCES = SOURCES + load_db_sources(registry_con)
        # upsert recruit_source(位置记录)
        for s in ALL_SOURCES:
            crow = rc.execute("SELECT id FROM company WHERE ticker=?", (s["ticker"],)).fetchone()
            s["company_id"] = crow[0] if crow else None
            if s["company_id"] is None or s["company_id"] not in comps:
                continue
            registry_con.execute("""INSERT INTO recruit_source(company_id,ticker,name,career_url,extractor,active,status)
                           VALUES(?,?,?,?,?,1,?)
                           ON CONFLICT(company_id) DO UPDATE SET career_url=excluded.career_url, extractor=excluded.extractor""",
                        (s["company_id"], s["ticker"], s["name"], s["url"], s["extractor"], "todo" if not s["url"] else "pending"))
        registry_con.commit()
    finally:
        registry_con.close()
        rc.close()

    todo = [s for s in ALL_SOURCES if s.get("company_id") and (not args.only or s["ticker"] == args.only)]
    print(f"招聘源:{len(todo)} 家(已配 URL {sum(1 for s in todo if s.get('url'))} / 待补 {sum(1 for s in todo if not s.get('url'))})\n")
    for s in todo:
        if not s.get("company_id"):
            continue
        company_con = _operation_connection(
            f"company:{s['company_id']}:{s['ticker']}"
        )
        try:
            st, no, nn, ncl = process(company_con, s, now, today)
            company_con.commit()
        finally:
            company_con.close()
        print(f"  {s['name']:<8}{s['ticker']}: {st} | 在招{no} 新增{nn} 下架{ncl}")
    print("\n说明:官网 JS 渲染走 Playwright;js_blocked=渲染出但未识别到职位(需为该家定制抽取);unreachable=沙箱网络;生产中国IP更稳。绝不伪造 JD。")


if __name__ == "__main__":
    main()
