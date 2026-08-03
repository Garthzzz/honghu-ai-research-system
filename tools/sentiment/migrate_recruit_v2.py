#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""招聘代理 v2 schema 迁移(只写 sentiment.db):为金融视角补充
  ① job_function 职能(研发/制造/销售/...)② location 地理(已存,补规范化 location_norm)
  ③ domain 影响领域(从职位标题 + 公司主营行业推断的技术/业务领域)。
并加 recruit_job.post_function/domain/location_city 列 + recruit_source 抓取路径审计列。幂等。
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

DDL = [
    # recruit_job:职能 / 领域 / 城市规范化
    "ALTER TABLE recruit_job ADD COLUMN job_function TEXT",      # 研发/制造工艺/测试质量/销售市场/供应链/职能管理/其它
    "ALTER TABLE recruit_job ADD COLUMN domain TEXT",            # 影响领域(光模块/存储/AI芯片/硅光/光芯片/...,可多个逗号分隔)
    "ALTER TABLE recruit_job ADD COLUMN location_city TEXT",     # 主要城市(规范化首城)
    "ALTER TABLE recruit_job ADD COLUMN classified_at TEXT",
    # recruit_source:抓取路径审计(这是"有记录的任务"核心)
    "ALTER TABLE recruit_source ADD COLUMN scrape_path TEXT",    # 抓取路径说明(API端点/DOM选择器/勘定备注)
    "ALTER TABLE recruit_source ADD COLUMN platform_type TEXT",  # beisen/moka/workday/官网定制/海岳HCM/无在线列表
    "ALTER TABLE recruit_source ADD COLUMN discovered_at TEXT",  # 招聘页勘定时间
]


def main():
    con = common.get_senti_db()
    common.assert_senti_only(con)                      # 门C
    for sql in DDL:
        try:
            con.execute(sql)
        except Exception as e:
            if "duplicate column" not in str(e):
                print("  skip:", str(e)[:60])
    con.commit()
    cols_j = [r[1] for r in con.execute("PRAGMA table_info(recruit_job)")]
    cols_s = [r[1] for r in con.execute("PRAGMA table_info(recruit_source)")]
    print("?? recruit v2 迁移完成")
    print("  recruit_job 新列:", [c for c in ("job_function", "domain", "location_city", "classified_at") if c in cols_j])
    print("  recruit_source 新列:", [c for c in ("scrape_path", "platform_type", "discovered_at") if c in cols_s])
    con.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
