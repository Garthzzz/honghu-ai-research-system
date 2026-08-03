#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""一次性:补齐意见领袖 bio + expertise_tags + is_featured。

bio/tags 取自各账号真实近期帖文内容(grounded),不编造未经证实的头衔;
对公认身份(顾文军=芯谋研究 / Rohan Paul=AI newsletter 作者)给出确定描述。
is_featured=1 的为"高质量索引",上首页/观点流卡片墙;其余经筛选手动找出。

幂等:按 id UPDATE。用法:python seed_leader_profiles.py
"""
from __future__ import annotations
import sqlite3, sys, json
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB = Path(__file__).resolve().parent.parent.parent / "data" / "research.db"

# id: (bio, [expertise_tags], is_featured)
PROFILES = {
    3:  ("Atreides Management CIO,科技/AI 多头基金经理,长期跟踪 AI 与半导体周期",
         ["美股", "AI", "半导体", "成长股"], 1),
    4:  ("SemiAnalysis 创始人/CEO,半导体供应链与先进制程深度分析",
         ["半导体供应链", "HBM", "GPU", "先进封装"], 1),
    5:  ("美股交易/市场情绪派(Reddit 风格),常以 cashtag 跟踪个股($MRVL/$ARM/$INTC 等)",
         ["美股", "半导体", "市场情绪", "个股交易"], 1),
    6:  ("Tesla / SpaceX / xAI CEO,AI 与算力基建风向标;发帖噪声高,经相关性闸过滤",
         ["AI", "算力基建", "xAI"], 0),
    7:  ("AI/ML 资讯作者(newsletter),聚合大模型与 AI 产业最新动态",
         ["AI", "大模型", "机器学习", "科技资讯"], 1),
    8:  ("日本视角半导体观察,关注先进封装与 AI 芯片(常引 TrendForce 等)",
         ["半导体", "先进封装", "AI芯片", "日本"], 0),
    9:  ("市场行为 / 消费趋势博主,偏宏观与行为金融杂谈",
         ["市场行为", "消费趋势", "宏观"], 0),
    10: ("芯谋研究(ICwise)创始人,半导体产业资深分析师,关注国产替代与产业链涨价",
         ["半导体", "国产替代", "产业链", "芯片制造"], 1),
    11: ("微博科技成长投资博主,聚焦算力 / 存储 / A股科技成长",
         ["算力", "存储", "A股科技", "成长股"], 1),
    12: ("微博中短线交易博主,跟踪半导体与美股/韩股仓位与情绪",
         ["半导体", "美股", "交易仓位", "短线"], 0),
}


def main():
    con = sqlite3.connect(str(DB)); cur = con.cursor()
    n = 0
    for lid, (bio, tags, feat) in PROFILES.items():
        row = cur.execute("SELECT id, name FROM opinion_leader WHERE id=?", (lid,)).fetchone()
        if not row:
            print(f"  ! id={lid} 不存在,跳过"); continue
        cur.execute(
            "UPDATE opinion_leader SET bio=?, expertise_tags=?, is_featured=?, updated_at=datetime('now','localtime') WHERE id=?",
            (bio, json.dumps(tags, ensure_ascii=False), feat, lid))
        n += 1
        print(f"  #{lid} {row[1]:<12} featured={feat} tags={tags}")
    con.commit()
    print(f"更新 {n} 位领袖")
    feats = cur.execute("SELECT id, name FROM opinion_leader WHERE is_featured=1 AND is_active=1 ORDER BY id").fetchall()
    print("精选(featured & active):", [f"{r[0]}:{r[1]}" for r in feats])
    con.close()


if __name__ == "__main__":
    main()
