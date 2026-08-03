#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Stage 3-A migration 004 — 动态情报模块 5 表(经 v2 review + R1/R4 修订)

5 表:opinion_leader / event / voice_post / news_item / fetch_schedule
全部 FK 到现有 source/company/industry,不动现有表。建表顺序保证 FK 先行:
  source(已存在)→ opinion_leader → event → voice_post → news_item → fetch_schedule

v2 修订已内置:
  修订1:news_item 无 source_tier(经 FK 继承 source.quality_tier)
  修订2:无 event_evidence 表(溯源走 ai_preview_source_ids + ai_tags_event_id 反查)
  修订3:fetch_schedule 含 is_running + running_started_at(并发锁)
R1:voice_post **不含 source_id**(leader_id→opinion_leader.source_id 是唯一真相,JOIN 取)
R4:voice_post **新增 ai_tags_event_id**(FK→event,可空),与 news_item 同款,事件页可反查"相关推文"

幂等:CREATE TABLE IF NOT EXISTS。
"""
import sqlite3, sys
from pathlib import Path
DB = Path(__file__).resolve().parent.parent.parent / "data" / "research.db"

DDL = r"""
CREATE TABLE IF NOT EXISTS opinion_leader (
  id                      INTEGER PRIMARY KEY,
  name                    TEXT NOT NULL,
  platform                TEXT NOT NULL,                 -- vocab §15
  profile_url             TEXT NOT NULL,
  account_handle          TEXT,
  region                  TEXT DEFAULT 'global',
  bio                     TEXT,
  expertise_tags          TEXT,                          -- JSON(自由)
  source_id               INTEGER,                       -- FK→source(该领袖的实体级 source;R1:voice 经此 JOIN 取 source)
  is_active               INTEGER NOT NULL DEFAULT 1,
  fetch_frequency_minutes INTEGER DEFAULT 60,
  last_fetched_at         TEXT,
  created_at              TEXT DEFAULT (datetime('now','localtime')),
  updated_at              TEXT DEFAULT (datetime('now','localtime')),
  FOREIGN KEY (source_id) REFERENCES source(id),
  CHECK (platform IN ('xueqiu','weibo','twitter','wechat_official')),
  CHECK (region   IN ('us','cn','global')),
  UNIQUE (platform, account_handle)
);

CREATE TABLE IF NOT EXISTS event (
  id                INTEGER PRIMARY KEY,
  title             TEXT NOT NULL,
  event_type        TEXT NOT NULL,                       -- vocab §18
  importance        INTEGER NOT NULL DEFAULT 3,          -- vocab §19: 1=L1/2=L2/3=L3
  scheduled_date    TEXT NOT NULL,
  actual_date       TEXT,
  status            TEXT NOT NULL DEFAULT 'upcoming',
  related_company_ids   TEXT,                            -- JSON
  related_industry_ids  TEXT,                            -- JSON
  related_subtopic  TEXT,
  description       TEXT,
  official_url      TEXT,
  ai_preview_narrative   TEXT,
  ai_preview_source_ids  TEXT,                           -- JSON source.id(溯源单一真相)
  ai_preview_generated_at TEXT,
  ai_preview_overridden_by_human INTEGER DEFAULT 0,
  ai_recap_narrative     TEXT,
  ai_recap_source_ids    TEXT,
  ai_recap_generated_at  TEXT,
  ai_recap_overridden_by_human   INTEGER DEFAULT 0,
  analyst_preview        TEXT,
  analyst_preview_author TEXT,
  analyst_preview_updated_at TEXT,
  analyst_recap          TEXT,
  analyst_recap_author   TEXT,
  analyst_recap_updated_at TEXT,
  data_source       TEXT,
  source_id         INTEGER,
  created_at        TEXT DEFAULT (datetime('now','localtime')),
  updated_at        TEXT DEFAULT (datetime('now','localtime')),
  FOREIGN KEY (source_id) REFERENCES source(id),
  CHECK (event_type IN ('财报','大会','产品发布','监管','并购','融资','论文','业内传言')),
  CHECK (importance IN (1,2,3)),
  CHECK (status IN ('upcoming','confirmed','completed','cancelled','rumored')),
  CHECK (data_source IS NULL OR data_source IN ('yfinance_earnings','hardcoded_conf','manual','news_extracted')),
  UNIQUE (title, scheduled_date)
);

-- R1:无 source_id(经 leader_id→opinion_leader.source_id JOIN);R4:含 ai_tags_event_id
CREATE TABLE IF NOT EXISTS voice_post (
  id              INTEGER PRIMARY KEY,
  leader_id       INTEGER NOT NULL,
  post_url        TEXT,
  post_id         TEXT NOT NULL,
  posted_at       TEXT,
  content_text    TEXT,
  content_html    TEXT,
  has_media       INTEGER DEFAULT 0,
  ai_tags_company   TEXT,                                -- JSON [company_id]
  ai_tags_industry  TEXT,                                -- JSON [industry_id]
  ai_tags_event_id  INTEGER,                             -- R4: FK→event(可空),事件页"相关推文"反查
  post_type         TEXT,                                -- vocab §16
  ai_summary        TEXT,
  ai_summary_source_ids   TEXT,
  ai_summary_generated_at TEXT,
  ai_tagged_by      TEXT,
  fetch_timestamp  TEXT,
  last_verified_at TEXT,
  created_at       TEXT DEFAULT (datetime('now','localtime')),
  FOREIGN KEY (leader_id)        REFERENCES opinion_leader(id),
  FOREIGN KEY (ai_tags_event_id) REFERENCES event(id),
  CHECK (post_type IS NULL OR post_type IN ('观点','转发','数据','提问','闲聊')),
  UNIQUE (leader_id, post_id)
);

-- 修订1:无 source_tier(经 FK source 继承 quality_tier/credibility)
CREATE TABLE IF NOT EXISTS news_item (
  id               INTEGER PRIMARY KEY,
  title            TEXT NOT NULL,
  url              TEXT NOT NULL,
  content_text     TEXT,
  summary          TEXT,
  source_publisher TEXT,
  source_id        INTEGER,                              -- FK→source(publisher 实体级 source)
  publish_date     TEXT,
  ai_tags_company  TEXT,
  ai_tags_industry TEXT,
  ai_tags_event_id INTEGER,                              -- FK→event(可空)
  ai_tagged_by     TEXT,
  importance       INTEGER DEFAULT 3,                    -- R2:默认3;突发按簇赋值;3-E AI 可覆盖
  is_breaking      INTEGER DEFAULT 0,
  keyword_cluster  TEXT,
  fetch_timestamp  TEXT,
  created_at       TEXT DEFAULT (datetime('now','localtime')),
  FOREIGN KEY (source_id)        REFERENCES source(id),
  FOREIGN KEY (ai_tags_event_id) REFERENCES event(id),
  CHECK (importance IN (1,2,3)),
  UNIQUE (url)
);

-- 修订3:is_running + running_started_at 并发锁
CREATE TABLE IF NOT EXISTS fetch_schedule (
  id                INTEGER PRIMARY KEY,
  target_type       TEXT NOT NULL,
  target_id         INTEGER,
  target_label      TEXT,
  frequency_minutes INTEGER NOT NULL DEFAULT 60,
  last_run_at       TEXT,
  next_run_at       TEXT,
  status            TEXT NOT NULL DEFAULT 'active',
  error_count       INTEGER NOT NULL DEFAULT 0,
  last_error        TEXT,
  is_active         INTEGER NOT NULL DEFAULT 1,
  is_running        INTEGER NOT NULL DEFAULT 0,
  running_started_at TEXT,
  created_at        TEXT DEFAULT (datetime('now','localtime')),
  updated_at        TEXT DEFAULT (datetime('now','localtime')),
  CHECK (target_type IN ('voice_leader','news_source','event_calendar')),
  CHECK (status IN ('active','paused','error')),
  CHECK (is_running IN (0,1)),
  UNIQUE (target_type, target_id)
);

CREATE INDEX IF NOT EXISTS idx_voice_post_leader_time ON voice_post(leader_id, posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_voice_post_posted      ON voice_post(posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_voice_post_event       ON voice_post(ai_tags_event_id);
CREATE INDEX IF NOT EXISTS idx_news_publish           ON news_item(publish_date DESC);
CREATE INDEX IF NOT EXISTS idx_news_breaking          ON news_item(is_breaking, publish_date DESC);
CREATE INDEX IF NOT EXISTS idx_news_event             ON news_item(ai_tags_event_id);
CREATE INDEX IF NOT EXISTS idx_event_sched            ON event(scheduled_date);
CREATE INDEX IF NOT EXISTS idx_event_status           ON event(status, scheduled_date);
CREATE INDEX IF NOT EXISTS idx_schedule_next          ON fetch_schedule(is_active, status, next_run_at);
CREATE INDEX IF NOT EXISTS idx_schedule_running       ON fetch_schedule(is_running, running_started_at);
"""

def main():
    con = sqlite3.connect(str(DB)); cur = con.cursor()
    cur.executescript(DDL)
    con.commit()
    tabs = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    want = ["opinion_leader","event","voice_post","news_item","fetch_schedule"]
    for t in want:
        cols = [r[1] for r in cur.execute(f"PRAGMA table_info({t})")]
        print(f"{t}: {'OK' if t in tabs else 'MISSING'} ({len(cols)} cols)")
    # R1/R4 断言
    vp = [r[1] for r in cur.execute("PRAGMA table_info(voice_post)")]
    print("R1 voice_post 无 source_id:", "source_id" not in vp)
    print("R4 voice_post 有 ai_tags_event_id:", "ai_tags_event_id" in vp)
    assert "event_evidence" not in tabs, "event_evidence 不应存在(修订2)"
    print("修订2 无 event_evidence:", "event_evidence" not in tabs)
    con.close()
    print("MIGRATION 004 DONE")

if __name__ == "__main__":
    main()
