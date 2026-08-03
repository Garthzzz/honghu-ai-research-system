# -*- coding: utf-8 -*-
"""
Stage 3-G B1 + B2 + B3(数据完整性,确定性,不动 idp/cp)

B1:event.description 去 metadata("config 硬编码/user 维护"),换事实性介绍(不编造)
B2:news.importance 5 档确定性评分(publisher tier + 头部公司命中 + 重要关键词 + 突发),UPDATE 137 条
B3:opinion_leader.expertise_tags 填充(4 领袖)
"""
import sqlite3, sys, io, json
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
DB = Path(__file__).resolve().parent.parent.parent / "data" / "research.db"

# B1 大会事实性介绍(基于公开已知,不编造)
CONF_DESC = {
    "NVIDIA GTC 2026": "NVIDIA 年度 GPU 技术大会,通常发布数据中心 GPU 新品、CUDA 软件栈与 AI 工具链更新;市场关注 Blackwell 后续与 Rubin 路线图。",
    "OFC 2026": "光纤通信领域全球顶级会议(Optical Fiber Communication);光模块 / 硅光 / CPO 厂商集中发布,数通光互联技术风向标。",
    "Computex 2026": "台北国际电脑展;服务器 / AI PC / GPU 生态厂商集中亮相,AI 硬件供应链的重要窗口。",
    "WWDC 2026": "苹果全球开发者大会;关注端侧 AI、操作系统 AI 能力与开发者框架更新。",
    "ISSCC 2026": "国际固态电路会议;半导体芯片前沿技术(含存储 / AI 加速器)的学术与产业风向。",
    "Hot Chips 2026": "高性能芯片架构会议;GPU / AI 加速器 / HBM 等架构细节披露的重要场合。",
}
IND_WATCH = {1: "光模块板块 800G/1.6T 出货与 ASP", 7: "存储板块 DRAM/HBM 价格与出货", 8: "大模型板块营收与算力投入"}
HEAD_COMPANIES = {"三星", "SK海力士", "美光", "中际旭创", "新易盛", "英伟达", "NVIDIA", "台积电", "Meta", "Google", "OpenAI", "Anthropic"}
IMP_KW = ["涨价", "提价", "收购", "并购", "突破", "制裁", "出口管制", "断供", "停产", "量产", "发布", "签约", "实体清单"]


def b1(con):
    cur = con.cursor(); n = 0
    # 大会
    for title, desc in CONF_DESC.items():
        r = cur.execute("UPDATE event SET description=? WHERE title=? AND event_type='大会'", (desc, title))
        n += r.rowcount
    # 财报:含 metadata 痕迹的重写为事实行
    for eid, title, rcj in cur.execute("""SELECT id, title, related_company_ids FROM event
            WHERE event_type='财报' AND (description LIKE '%config%' OR description LIKE '%user 维护%' OR description LIKE '%推算%')""").fetchall():
        cos = json.loads(rcj or "[]")
        ind = None
        if cos:
            row = cur.execute("SELECT industry_id FROM company_profile WHERE company_id=? LIMIT 1", (cos[0],)).fetchone()
            ind = row[0] if row else None
        watch = IND_WATCH.get(ind, "相关板块业绩")
        sd = cur.execute("SELECT scheduled_date FROM event WHERE id=?", (eid,)).fetchone()[0]
        desc = f"{title}(预估披露日 {sd},具体财季 / 币种以公司公告为准);关注 {watch} 指引。"
        cur.execute("UPDATE event SET description=? WHERE id=?", (desc, eid)); n += 1
    con.commit()
    left = cur.execute("SELECT COUNT(*) FROM event WHERE description LIKE '%config%' OR description LIKE '%user 维护%'").fetchone()[0]
    print(f"B1:重写 {n} 个 event description;残留 metadata: {left}(应 0)")


def b2(con):
    cur = con.cursor()
    rows = cur.execute("""SELECT n.id, n.title, n.content_text, n.is_breaking, n.ai_tags_company, s.quality_tier
                          FROM news_item n LEFT JOIN source s ON s.id=n.source_id""").fetchall()
    dist = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for nid, title, content, brk, cosj, tier in rows:
        text = f"{title} {content or ''}"
        score = 0.0
        score += {1: 2.0, 2: 1.0, 3: 0.0}.get(tier, 0.0)          # publisher 质量
        try:
            cos = json.loads(cosj or "[]")
        except Exception:
            cos = []
        conames = {cur.execute("SELECT name FROM company WHERE id=?", (c,)).fetchone()[0] for c in cos} if cos else set()
        if conames & HEAD_COMPANIES:
            score += 1.0                                          # 头部公司命中
        if any(k in text for k in IMP_KW):
            score += 1.0                                          # 重要关键词
        if brk:
            score += 2.0                                          # 突发
        # 映射 3 档(news_item.importance CHECK IN(1,2,3);红线禁重建表 → 用 3 档,命令允许"3 或 5 档")
        imp = 1 if score >= 3 else 2 if score >= 1.5 else 3
        cur.execute("UPDATE news_item SET importance=? WHERE id=?", (imp, nid))
        dist[imp] += 1
    con.commit()
    print(f"B2:news importance 3 档分布 L1={dist[1]} L2={dist[2]} L3={dist[3]}(L4/L5 需重建表放宽 CHECK,红线禁 → 用 3 档)")


def b3(con):
    cur = con.cursor()
    tags = {
        "汤诗语": ["中国A股", "半导体", "光模块", "AI产业链"],
        "莫大仙岳居": ["中国A股", "TMT", "中证"],
        "Gavin Baker": ["美股", "AI", "半导体", "SaaS"],
        "Dylan Patel": ["半导体供应链", "HBM", "GPU", "制造工艺"],
    }
    n = 0
    for name, t in tags.items():
        r = cur.execute("UPDATE opinion_leader SET expertise_tags=? WHERE name=?", (json.dumps(t, ensure_ascii=False), name))
        n += r.rowcount
    con.commit()
    filled = cur.execute("SELECT COUNT(*) FROM opinion_leader WHERE expertise_tags IS NOT NULL").fetchone()[0]
    print(f"B3:expertise_tags 填充 {n};已填 {filled}/4")


def main():
    con = sqlite3.connect(str(DB))
    b1(con); b2(con); b3(con)
    con.close()
    print("B123 DONE")


if __name__ == "__main__":
    main()
