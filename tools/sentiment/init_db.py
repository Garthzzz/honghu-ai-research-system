#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""M0:建 data/sentiment.db(独立库)+ schema + seed 元信息。幂等。只写 sentiment.db(门C)。"""
from __future__ import annotations
import sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

META = {
    "口径": "指标②=东财股吧每股每日发帖量;既定口径:3日MA vs 20日MA 上穿预警 + 99分位 + 滞涨减仓 + 显著门槛>10",
    "指标①状态": "原生情绪方向分无干净源(舆情API IP阻塞+专题级;东财人气/千评=人气资金非方向;同花顺反爬),v1 跳过留 NULL,见 RUN_LOG 门B",
    "覆盖": "核心池 A股(光模块/算力芯片/HBM/存储/AI算力);美/港股降级 KOL/news 标'覆盖弱'",
    "隔离": "C1 独立 data/sentiment.db,脚本只写本库;research.db 仅只读 ATTACH",
    "免责": "情绪为讨论量代理非基本面;事件 AI 摘要 tier≤2 视觉标记;抓不到标'不显著/覆盖弱/客观不可得',不造数",
    "抓取": "东财股吧经 Playwright 真浏览器(raw HTTP 被验证码挡);出口IP美国段→覆盖以生产中国IP为准",
}


def main():
    schema = (Path(__file__).resolve().parent / "schema_sentiment.sql").read_text(encoding="utf-8")
    con = common.get_senti_db()
    common.assert_senti_only(con)                 # 门C
    con.executescript(schema)
    for k, v in META.items():
        con.execute("INSERT OR REPLACE INTO senti_meta(k, v) VALUES(?, ?)", (k, v))
    con.commit()
    tbls = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    print(f"sentiment.db 建成,表 {len(tbls)} 张:")
    for t in tbls:
        print("  -", t)
    comps, inds = common.load_closed_set()
    print(f"闭集校验源(research.db 只读): company={len(comps)} industry={len(inds)}")
    con.close()
    print("M0 DONE")


if __name__ == "__main__":
    main()
