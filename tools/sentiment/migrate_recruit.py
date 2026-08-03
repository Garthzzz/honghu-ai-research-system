#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""招聘代理:建 recruit_source(每家官网招聘页配置/位置记录)+ recruit_job(岗位 + first/last_seen + open/closed)
+ recruit_change_log(每周新增/下架历史)。只写 sentiment.db。幂等。"""
from __future__ import annotations
import sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

DDL = """
CREATE TABLE IF NOT EXISTS recruit_source (
  id INTEGER PRIMARY KEY, company_id INTEGER, ticker TEXT, name TEXT,
  career_url TEXT,                 -- ?? 每家官网招贤纳士页位置(一次性记录)
  method TEXT DEFAULT 'playwright', -- playwright / http
  extractor TEXT DEFAULT 'generic', -- generic 或具名定制抽取器
  active INTEGER DEFAULT 1,
  status TEXT,                     -- ok / js_blocked / unreachable / todo
  last_checked TEXT, n_jobs INTEGER, note TEXT,
  UNIQUE(company_id)
);
CREATE TABLE IF NOT EXISTS recruit_job (
  id INTEGER PRIMARY KEY, company_id INTEGER, ticker TEXT,
  job_key TEXT,                    -- sha1(company|title|dept|location)
  title TEXT, dept TEXT, location TEXT, post_date TEXT, url TEXT,
  first_seen TEXT, last_seen TEXT,
  status TEXT DEFAULT 'open',      -- open(在招) / closed(已下架)
  source_url TEXT, fetched_at TEXT,
  UNIQUE(company_id, job_key)
);
CREATE INDEX IF NOT EXISTS idx_rjob_co ON recruit_job(company_id, status);
CREATE TABLE IF NOT EXISTS recruit_change_log (
  id INTEGER PRIMARY KEY, company_id INTEGER, ticker TEXT, run_date TEXT,
  n_open INTEGER, n_new INTEGER, n_closed INTEGER,
  new_titles TEXT, closed_titles TEXT, fetched_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_rchg_co ON recruit_change_log(company_id, run_date DESC);
"""


def main():
    con = common.get_senti_db()
    common.assert_senti_only(con)
    con.executescript(DDL)
    con.execute("INSERT OR REPLACE INTO senti_meta(k,v) VALUES(?,?)",
                ("招聘", "recruit_*:各公司官网招贤纳士页每周抓取;recruit_job first/last_seen+open/closed 比对新增/下架;recruit_change_log 历史。官网JS渲染→Playwright。绝不伪造JD。"))
    con.commit()
    print("招聘表建成:recruit_source / recruit_job / recruit_change_log")
    con.close()


if __name__ == "__main__":
    main()
