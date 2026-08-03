#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""招聘页平台探针:加载候选 URL,截获网络请求 + 采样页面候选岗位文本,判定 ATS 平台。
不入库、不伪造,只输出分类供 recruit_source 配置参考。
用法:python recruit_probe.py "<url1>" "<url2>" ...
判定信号:GetJobAdPageList/zhiye.com/beisen→beisen;mokahr→moka;workday;hcmcloud→inspur(海岳);hotjob.cn→51job
"""
from __future__ import annotations
import sys, re, json
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
JOB_RE = re.compile(r"(工程师|经理|主管|专员|总监|研发|测试|架构师|顾问|分析师|设计师|助理|实习|运营|产品|算法|开发|采购|销售|财务|质量|工艺|结构|硬件|软件|光学|封装|技术员|生产|工程|项目|总裁|代表|储备)")


def classify(reqs, final_url, html):
    blob = " ".join(reqs) + " " + final_url + " " + (html[:5000] if html else "")
    low = blob.lower()
    sig = []
    if "getjobadpagelist" in low or ".zhiye.com" in low or "beisen" in low:
        sig.append("beisen")
    if "mokahr.com" in low or "mokahr" in low:
        sig.append("moka")
    if "myworkdayjobs" in low or "workday" in low:
        sig.append("workday")
    if "hcmcloud.cn" in low or "海岳" in blob or "inspur-hr" in low:
        sig.append("inspur/海岳HCM")
    if "hotjob.cn" in low:
        sig.append("51job/hotjob")
    if "zhaopin.com" in low:
        sig.append("智联")
    if "lagou" in low or "liepin" in low or "zhipin" in low:
        sig.append("第三方招聘站")
    return sig


def probe(url):
    from playwright.sync_api import sync_playwright
    reqs, final_url, html, title = [], url, "", ""
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        pg = b.new_context(user_agent=UA, locale="zh-CN").new_page()
        pg.on("request", lambda r: reqs.append(r.url))
        try:
            pg.goto(url, timeout=35000, wait_until="domcontentloaded")
            pg.wait_for_timeout(4000)
            final_url = pg.url
            title = pg.title()
            html = pg.content()
        except Exception as e:
            b.close()
            return {"url": url, "error": f"{type(e).__name__}: {str(e)[:80]}"}
        # 采样候选岗位文本 + 选择器线索(叶子元素 tag/class 按岗位命中密度排序)
        try:
            texts = pg.eval_on_selector_all(
                "a, li, td, h3, h4, h5, p, span, div",
                "els => els.map(e => (e.innerText||'').trim()).filter(t => t && t.length>=3 && t.length<=30)")
        except Exception:
            texts = []
        try:
            hints = pg.evaluate("""(reSrc)=>{
              const re=new RegExp(reSrc); const agg={};
              for(const e of document.querySelectorAll('*')){
                if(e.children.length<=1){
                  const t=(e.innerText||'').trim();
                  if(t&&t.length>=3&&t.length<=30&&re.test(t)){
                    const tag=e.tagName.toLowerCase();
                    const cls=(e.className||'').toString().trim().split(/\\s+/)[0]||'';
                    const sel=cls?(tag+'.'+cls):tag;
                    agg[sel]=(agg[sel]||0)+1;
                  }
                }
              }
              return Object.entries(agg).sort((a,b)=>b[1]-a[1]).slice(0,8);
            }""", JOB_RE.pattern)
        except Exception:
            hints = []
        b.close()
    cand, seen = [], set()
    for t in texts:
        t = re.sub(r"\s+", " ", t).strip()
        if t and t not in seen and JOB_RE.search(t) and len(t) <= 30:
            seen.add(t)
            cand.append(t)
    sig = classify(reqs, final_url, html)
    beisen_api = [r for r in reqs if "GetJobAdPageList" in r]
    return {"url": url, "final_url": final_url, "title": title[:60],
            "platform_signals": sig, "beisen_api_hit": bool(beisen_api),
            "n_candidate_jobs": len(cand), "sample_jobs": cand[:12],
            "selector_hints": hints, "n_requests": len(reqs)}


def main():
    for url in sys.argv[1:]:
        for attempt in range(3):
            r = probe(url)
            if "error" not in r:
                break
            print(f"  [retry {attempt+1}] {url} {r['error']}", file=sys.stderr)
        print(json.dumps(r, ensure_ascii=False))


if __name__ == "__main__":
    main()
