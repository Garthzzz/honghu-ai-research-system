-- ════════════════════════════════════════════════════════════════════════
-- data/sentiment.db — 独立 情绪/事件/代理/叙事 库(阶段二 M0；旧专题表已退役)
-- C1 铁律:本库与 research.db 物理隔离;情绪/事件/代理/专题脚本【只写本库】。
--          viewer 用 ATTACH research.db?mode=ro 只读 JOIN company/industry。
-- 溯源铁律:每条数据 source_url(^src) + as_of(数据归属时点) + fetched_at(抓取时刻)。
-- 闭集:entity_id 只认 research.db 已有 company.id / industry.id(应用层 valid_company/valid_industry 校验)。
-- ════════════════════════════════════════════════════════════════════════

-- ── 抓取去重账本(复用 news dynamic_seen 范式:被丢也记账,防重判)──
CREATE TABLE IF NOT EXISTS senti_seen (
  seen_key      TEXT PRIMARY KEY,         -- sha1(kind|source|native_id)
  kind          TEXT,                     -- post / event / ...
  first_seen_at TEXT
);

-- ── 情绪原子时序:每股每日(指标②发帖量 = 既定口径核心)──
CREATE TABLE IF NOT EXISTS senti_discussion_daily (
  id              INTEGER PRIMARY KEY,
  company_id      INTEGER NOT NULL,       -- 闭集 research.db company.id
  ticker          TEXT,
  trade_date      TEXT NOT NULL,          -- YYYY-MM-DD
  post_count      INTEGER,                -- ?? 指标②:当日发帖量
  read_count      INTEGER,                -- 当日阅读量(可选辅助)
  popularity_rank INTEGER,                -- 东财人气榜排名(辅助,非情绪方向)
  fund_flow_main  REAL,                   -- 主力净流入(辅助,非情绪方向)
  native_sentiment      REAL,             -- ?? 指标①原生情绪方向分:当前 NULL(无干净源,见 RUN_LOG 门B)
  native_sentiment_src  TEXT,
  platform        TEXT DEFAULT 'eastmoney',
  source_url      TEXT NOT NULL,          -- ^src
  as_of           TEXT,
  fetched_at      TEXT NOT NULL,
  UNIQUE(company_id, trade_date, platform)
);
CREATE INDEX IF NOT EXISTS idx_sdd_company_date ON senti_discussion_daily(company_id, trade_date DESC);

-- ── 情绪衍生指标(既定口径:3日MA/20日MA/上穿/99分位/滞涨减仓/显著门槛>10)──
CREATE TABLE IF NOT EXISTS senti_indicator_daily (
  id            INTEGER PRIMARY KEY,
  company_id    INTEGER NOT NULL,
  trade_date    TEXT NOT NULL,
  post_count    INTEGER,
  ma3           REAL,
  ma20          REAL,
  cross_up      INTEGER,                  -- ma3 上穿 ma20(0/1)
  pct_rank      REAL,                     -- 当日发帖量在窗口内分位(0–1)
  pct99_alert   INTEGER,                  -- >=0.99 分位预警(0/1)
  stagnation_cut_signal INTEGER,          -- 滞涨减仓(价格滞涨 + 讨论高分位;价格缺则 NULL)
  significant   INTEGER,                  -- post_count>10(0/1)
  ready         INTEGER,                  -- 历史>=20交易日才就绪(0/1)
  computed_at   TEXT,
  UNIQUE(company_id, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_sid_company_date ON senti_indicator_daily(company_id, trade_date DESC);

-- ── 事件(公告 + 新闻 + 催化)──
CREATE TABLE IF NOT EXISTS event_item (
  id           INTEGER PRIMARY KEY,
  entity_type  TEXT,                      -- company / industry
  entity_id    INTEGER,                   -- 闭集
  event_type   TEXT,                      -- announcement / news / catalyst
  title        TEXT NOT NULL,
  summary_ai   TEXT,                      -- DeepSeek 摘要(tier≤2)
  url          TEXT,
  published_at TEXT,
  source       TEXT,                      -- cninfo / cls / ...
  sentiment    TEXT,                      -- 正面 / 负面 / 中性(DeepSeek)
  materiality  TEXT,                      -- 高 / 中 / 低(DeepSeek)
  ai_tagged_by TEXT,
  ai_tier      INTEGER DEFAULT 2,         -- AI 产出 tier≤2
  source_url   TEXT,
  as_of        TEXT,
  fetched_at   TEXT NOT NULL,
  UNIQUE(source, url)
);
CREATE INDEX IF NOT EXISTS idx_event_entity ON event_item(entity_type, entity_id, published_at DESC);

-- ── cninfo 公告:ticker → orgId 映射(公告查询需 stock=code,orgId)──
CREATE TABLE IF NOT EXISTS event_orgid_map (
  ticker     TEXT PRIMARY KEY,
  code       TEXT,
  org_id     TEXT,
  name       TEXT,
  market     TEXT,                        -- szse / sse
  updated_at TEXT
);

-- ── 代理变量(job 三层:source→vertical→target;C6 降级,真实公司闭集)──
CREATE TABLE IF NOT EXISTS proxy_node (
  id INTEGER PRIMARY KEY, layer TEXT, name TEXT, entity_id INTEGER,
  jd_count INTEGER, prob REAL, gtm_stage TEXT, note TEXT, as_of TEXT, fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS proxy_edge (
  id INTEGER PRIMARY KEY, src_node INTEGER, dst_node INTEGER, weight REAL, first_seen TEXT
);
CREATE TABLE IF NOT EXISTS proxy_risk (
  id INTEGER PRIMARY KEY, entity_id INTEGER, vertical TEXT, impact REAL, exposure REAL,
  risk TEXT, first_seen TEXT, source_url TEXT, as_of TEXT, fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS proxy_series (
  id INTEGER PRIMARY KEY, entity_id INTEGER, metric TEXT, trade_date TEXT, value REAL, unit TEXT,
  source_url TEXT, as_of TEXT, fetched_at TEXT
);

-- ── 叙事追踪(轻量)──
CREATE TABLE IF NOT EXISTS narrative (
  id INTEGER PRIMARY KEY, theme TEXT, stance TEXT,    -- 看多/看空/中性
  summary_md TEXT, evidence_refs TEXT, updated_at TEXT
);

-- ── 元信息(口径/来源/免责说明,viewer 页脚展示)──
CREATE TABLE IF NOT EXISTS senti_meta (k TEXT PRIMARY KEY, v TEXT);

-- ── 散户情绪市场窗口 V2（canonical DDL 同 retail_windows_v2.py）──
CREATE TABLE IF NOT EXISTS company_id_redirect (
  old_company_id       INTEGER PRIMARY KEY,
  canonical_company_id INTEGER NOT NULL,
  canonical_name       TEXT NOT NULL,
  reason               TEXT NOT NULL,
  verified_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS retail_window_ledger (
  window_id          TEXT PRIMARY KEY,
  window_version     TEXT NOT NULL,
  session_date       TEXT NOT NULL,
  slot               TEXT NOT NULL CHECK(slot IN ('preopen','morning','afternoon')),
  window_start       TEXT NOT NULL,
  window_end         TEXT NOT NULL,
  scheduled_for      TEXT NOT NULL,
  segments_json      TEXT NOT NULL,
  effective_minutes  INTEGER NOT NULL CHECK(effective_minutes > 0),
  status             TEXT NOT NULL DEFAULT 'pending'
                     CHECK(status IN ('pending','running','partial','complete','failed')),
  attempts           INTEGER NOT NULL DEFAULT 0,
  source_status_json TEXT NOT NULL DEFAULT '{}',
  raw_count          INTEGER NOT NULL DEFAULT 0,
  scored_count       INTEGER NOT NULL DEFAULT 0,
  started_at         TEXT,
  finished_at        TEXT,
  error              TEXT,
  UNIQUE(session_date, slot)
);
CREATE INDEX IF NOT EXISTS ix_retail_window_due
  ON retail_window_ledger(status, scheduled_for);

-- 公司归因前的舆情中性原始层。只保存业务内容及哈希，不保存 token/cookie/raw JSON。
CREATE TABLE IF NOT EXISTS yuqing_feed_raw (
  dedup_key     TEXT PRIMARY KEY,
  post_id       TEXT,
  platform      TEXT NOT NULL,
  title         TEXT,
  content_text  TEXT,
  url           TEXT,
  author        TEXT,
  author_uid    TEXT,
  publish_time  TEXT NOT NULL,
  fetched_at    TEXT NOT NULL,
  source_status TEXT NOT NULL,
  window_id     TEXT NOT NULL REFERENCES retail_window_ledger(window_id) ON DELETE RESTRICT,
  raw_json_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_yuqing_feed_window
  ON yuqing_feed_raw(window_id, platform, publish_time);

-- 星瀚分页 checkpoint。API subject_id 与本地 request_variant 分离：
-- 全媒体和微博专项都可能使用空 subject_id，但必须拥有独立快照与 offset。
CREATE TABLE IF NOT EXISTS yuqing_fetch_checkpoint (
  window_id             TEXT NOT NULL REFERENCES retail_window_ledger(window_id) ON DELETE CASCADE,
  subject_id            TEXT NOT NULL,
  request_variant       TEXT NOT NULL,
  segment_start         TEXT NOT NULL,
  segment_end           TEXT NOT NULL,
  request_begin_ms      INTEGER NOT NULL,
  request_end_ms        INTEGER NOT NULL,
  snapshot_timestamp_ms INTEGER NOT NULL,
  next_offset           INTEGER NOT NULL DEFAULT 0 CHECK(next_offset >= 0),
  page_size             INTEGER NOT NULL CHECK(page_size > 0),
  pages_committed       INTEGER NOT NULL DEFAULT 0 CHECK(pages_committed >= 0),
  records_seen          INTEGER NOT NULL DEFAULT 0 CHECK(records_seen >= 0),
  created_at            TEXT NOT NULL,
  updated_at            TEXT NOT NULL,
  PRIMARY KEY(window_id,subject_id,request_variant,segment_start,segment_end)
);
CREATE INDEX IF NOT EXISTS ix_yuqing_fetch_checkpoint_window
  ON yuqing_fetch_checkpoint(window_id,updated_at);

CREATE TABLE IF NOT EXISTS yuqing_fetch_segment_run (
  window_id             TEXT NOT NULL REFERENCES retail_window_ledger(window_id) ON DELETE CASCADE,
  subject_id            TEXT NOT NULL,
  request_variant       TEXT NOT NULL,
  segment_start         TEXT NOT NULL,
  segment_end           TEXT NOT NULL,
  status                TEXT NOT NULL CHECK(status IN ('running','partial','complete','failed')),
  snapshot_timestamp_ms INTEGER,
  pages_committed       INTEGER NOT NULL DEFAULT 0 CHECK(pages_committed >= 0),
  records_seen          INTEGER NOT NULL DEFAULT 0 CHECK(records_seen >= 0),
  error_code            TEXT,
  started_at            TEXT NOT NULL,
  finished_at           TEXT,
  updated_at            TEXT NOT NULL,
  PRIMARY KEY(window_id,subject_id,request_variant,segment_start,segment_end)
);
CREATE INDEX IF NOT EXISTS ix_yuqing_fetch_segment_window
  ON yuqing_fetch_segment_run(window_id,status,updated_at);

CREATE TABLE IF NOT EXISTS retail_window_source_run (
  window_id    TEXT NOT NULL REFERENCES retail_window_ledger(window_id) ON DELETE CASCADE,
  source       TEXT NOT NULL,
  status       TEXT NOT NULL CHECK(status IN ('pending','running','partial','complete','empty','failed','skipped')),
  records_seen INTEGER NOT NULL DEFAULT 0,
  inserted     INTEGER NOT NULL DEFAULT 0,
  error_code   TEXT,
  started_at   TEXT,
  finished_at  TEXT,
  PRIMARY KEY(window_id, source)
);

CREATE TABLE IF NOT EXISTS senti_raw_window (
  raw_id          INTEGER PRIMARY KEY REFERENCES senti_raw(id) ON DELETE CASCADE,
  window_id       TEXT NOT NULL REFERENCES retail_window_ledger(window_id) ON DELETE CASCADE,
  mapping_version TEXT NOT NULL,
  mapped_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_senti_raw_window_window
  ON senti_raw_window(window_id, raw_id);

CREATE TABLE IF NOT EXISTS senti_retail_window (
  company_id      INTEGER NOT NULL,
  ticker          TEXT,
  window_id       TEXT NOT NULL REFERENCES retail_window_ledger(window_id) ON DELETE CASCADE,
  raw_count       INTEGER NOT NULL DEFAULT 0,
  scored_count    INTEGER NOT NULL DEFAULT 0,
  pos             INTEGER NOT NULL DEFAULT 0,
  neg             INTEGER NOT NULL DEFAULT 0,
  neu             INTEGER NOT NULL DEFAULT 0,
  net_plain       REAL,
  net_weighted    REAL,
  coverage        REAL NOT NULL DEFAULT 0,
  significant     INTEGER NOT NULL DEFAULT 0,
  usable          INTEGER NOT NULL DEFAULT 0,
  n_xueqiu        INTEGER NOT NULL DEFAULT 0,
  n_eastmoney     INTEGER NOT NULL DEFAULT 0,
  n_ths           INTEGER NOT NULL DEFAULT 0,
  n_weibo         INTEGER NOT NULL DEFAULT 0,
  n_guba          INTEGER NOT NULL DEFAULT 0,
  computed_at     TEXT NOT NULL,
  PRIMARY KEY(company_id, window_id)
);
CREATE INDEX IF NOT EXISTS ix_senti_retail_window_window
  ON senti_retail_window(window_id, company_id);

CREATE TABLE IF NOT EXISTS senti_retail_trading_daily (
  company_id        INTEGER NOT NULL,
  ticker            TEXT,
  session_date      TEXT NOT NULL,
  raw_count         INTEGER NOT NULL DEFAULT 0,
  scored_count      INTEGER NOT NULL DEFAULT 0,
  pos               INTEGER NOT NULL DEFAULT 0,
  neg               INTEGER NOT NULL DEFAULT 0,
  neu               INTEGER NOT NULL DEFAULT 0,
  net_plain         REAL,
  net_weighted      REAL,
  coverage          REAL NOT NULL DEFAULT 0,
  significant       INTEGER NOT NULL DEFAULT 0,
  usable            INTEGER NOT NULL DEFAULT 0,
  n_xueqiu          INTEGER NOT NULL DEFAULT 0,
  n_eastmoney       INTEGER NOT NULL DEFAULT 0,
  n_ths             INTEGER NOT NULL DEFAULT 0,
  n_weibo           INTEGER NOT NULL DEFAULT 0,
  n_guba            INTEGER NOT NULL DEFAULT 0,
  completed_windows INTEGER NOT NULL DEFAULT 0,
  expected_windows  INTEGER NOT NULL DEFAULT 3,
  complete          INTEGER NOT NULL DEFAULT 0,
  computed_at       TEXT NOT NULL,
  PRIMARY KEY(company_id, session_date)
);
CREATE INDEX IF NOT EXISTS ix_senti_retail_daily_date
  ON senti_retail_trading_daily(session_date, company_id);

-- 超过三天且未能映射到 V2 窗口的历史 raw 不保留逐帖正文，只冻结数值事实。
-- 该表与 V2 窗口聚合分开，避免把 legacy 行重复计入正式窗口统计。
CREATE TABLE IF NOT EXISTS senti_unmapped_daily (
  trade_date             TEXT NOT NULL,
  company_id             INTEGER NOT NULL,
  ticker                 TEXT,
  source_layer           TEXT NOT NULL,
  platform               TEXT NOT NULL,
  raw_count              INTEGER NOT NULL,
  scored_count           INTEGER NOT NULL,
  pos                    INTEGER NOT NULL,
  neg                    INTEGER NOT NULL,
  neu                    INTEGER NOT NULL,
  weighted_pos           REAL NOT NULL,
  weighted_neg           REAL NOT NULL,
  weighted_neu           REAL NOT NULL,
  heat_value_sum         REAL NOT NULL,
  read_count_sum         INTEGER NOT NULL,
  reply_count_sum        INTEGER NOT NULL,
  aggregation_version    TEXT NOT NULL,
  aggregate_sha256       TEXT NOT NULL,
  computed_at            TEXT NOT NULL,
  PRIMARY KEY(trade_date, company_id, source_layer, platform)
);
CREATE INDEX IF NOT EXISTS ix_senti_unmapped_daily_date
  ON senti_unmapped_daily(trade_date, company_id);
