#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""T3/T10:情绪方向分(指标①,DeepSeek 自算)。
增强:few-shot 股吧黑话 + 关键词粗筛(只判有信息量帖)+ 理由输出 + 蒸馏语料(senti_label_corpus)。
对 senti_post 未打标帖分类 看涨(+1)/看跌(-1)/中性(0)→ 聚合 direction∈[-1,1]。
?? 自算非平台原生:labeled_by='deepseek_self',tier≤2,^src 原帖;dynamic 去重(只判未打标);每 run 封顶顺延。
?? 定位为弱信号(股吧水军噪声大),与发帖量分开展示。分类基于标题(股吧短帖标题≈正文主旨;全文抓取见 RUN_LOG 口径说明)。
用法:python senti_direction.py [--max-posts 240] [--batch 14]
"""
from __future__ import annotations
import sys, re, argparse
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dynamic"))
import common
from senti_aggregate import recompute_company
try:
    import llm_client
except Exception:
    llm_client = None

_SCORE = {"看涨": 1.0, "看跌": -1.0, "中性": 0.0}
# 关键词粗筛:纯噪声直接判中性不耗 token
_NOISE = re.compile(r"^[\s\W]*$|^(顶|沙发|板凳|前排|哈哈+|666+|第一|签到|路过|默哀|啊+|呵呵)[\s\W]*$")
SYS = ("你是A股股吧情绪分类器,熟悉股民黑话。判断发帖者对该股的情绪:看涨/看跌/中性。\n"
       "黑话示例:一字板/涨停/秒板/上车/满仓干/起飞/yyds→看涨;套牢/割肉/跌停/出货/天台/骗炮/诱多/接盘→看跌;"
       "洗盘/震荡/横盘/观望/明天看/不好说→中性。反讽要看实质(如'又涨停了真好'抱怨套牢→看跌)。\n"
       "只输出JSON,每条给 label 和一句极简 reason。")


def prefilter(title):
    """返回 (need_llm, default_label)。纯噪声 → 不判 LLM,记中性。"""
    t = (title or "").strip()
    if len(t) < 3 or _NOISE.match(t):
        return False, "中性"
    return True, None


def classify_batch(titles):
    if not (llm_client and llm_client.enabled()):
        return [(None, None)] * len(titles)
    lst = "\n".join(f"{i}. {t}" for i, t in enumerate(titles))
    usr = (f"对以下 {len(titles)} 条股吧标题分类:\n{lst}\n"
           f"输出JSON:{{\"items\":[{{\"label\":\"看涨|看跌|中性\",\"reason\":\"...\"}}]}}(长度{len(titles)},按序对齐)")
    r = llm_client.chat_json(SYS, usr, max_tokens=900)
    if isinstance(r, dict) and isinstance(r.get("items"), list) and len(r["items"]) == len(titles):
        return [(it.get("label"), it.get("reason")) for it in r["items"]]
    return [(None, None)] * len(titles)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-posts", type=int, default=240)
    ap.add_argument("--batch", type=int, default=14)
    args = ap.parse_args()
    con = common.get_senti_db()
    common.assert_senti_only(con)                       # 门C
    rows = con.execute("""SELECT id, company_id, ticker, post_id, title FROM senti_post
                          WHERE labeled_by IS NULL AND title IS NOT NULL AND TRIM(title)<>''
                          ORDER BY ts_hour DESC LIMIT ?""", (args.max_posts,)).fetchall()
    print(f"待打标帖:{len(rows)}")
    now = common.now_iso(); labeled = 0; noise = 0; affected = set()
    model = "deepseek-chat"

    # 先粗筛:纯噪声直接记中性(不耗 LLM)
    to_llm = []
    for r in rows:
        need, dflt = prefilter(r["title"])
        if not need:
            con.execute("UPDATE senti_post SET sentiment_label='中性', label_score=0, labeled_by='prefilter', labeled_at=? WHERE id=?", (now, r["id"]))
            noise += 1; affected.add(r["company_id"])
        else:
            to_llm.append(r)
    con.commit()

    if not (llm_client and llm_client.enabled()):
        print("DeepSeek 未启用 → 仅粗筛,LLM 方向分留空(未就绪),不造数"); con.close(); return

    for i in range(0, len(to_llm), args.batch):
        batch = to_llm[i:i + args.batch]
        res = classify_batch([r["title"] for r in batch])
        for r, (lab, reason) in zip(batch, res):
            if lab not in _SCORE:
                continue
            sc = _SCORE[lab]
            con.execute("UPDATE senti_post SET sentiment_label=?, label_score=?, labeled_by='deepseek_self', labeled_at=? WHERE id=?",
                        (lab, sc, now, r["id"]))
            # 蒸馏语料(LLM 当标注器 → 将来微调本地金融股吧模型)
            con.execute("""INSERT OR IGNORE INTO senti_label_corpus(post_id,company_id,ticker,text,label,label_score,reason,model,labeled_at)
                           VALUES(?,?,?,?,?,?,?,?,?)""",
                        (r["post_id"], r["company_id"], r["ticker"], r["title"], lab, sc, reason, model, now))
            labeled += 1; affected.add(r["company_id"])
        con.commit()

    for cid in affected:
        recompute_company(con, cid, now)
    con.commit()

    cov = con.execute("SELECT COUNT(DISTINCT company_id) FROM senti_post WHERE labeled_by='deepseek_self'").fetchone()[0]
    corpus = con.execute("SELECT COUNT(*) FROM senti_label_corpus").fetchone()[0]
    print(f"=== T10 方向分:LLM打标 {labeled} / 粗筛中性 {noise} / 覆盖 {cov} 股 | 蒸馏语料 {corpus} 行 ===")
    print("?? 自算(DeepSeek)非平台原生,tier≤2,^src 原帖;弱信号,与发帖量分开。基于标题(口径见RUN_LOG)。")
    if llm_client:
        print("DeepSeek:", getattr(llm_client, "USAGE", ""))
    con.close()


if __name__ == "__main__":
    main()
