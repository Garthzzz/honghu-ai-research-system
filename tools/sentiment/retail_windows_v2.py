#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""散户情绪市场窗口 V2：schema、raw 映射、聚合与公平评分队列。

本模块只依赖 ``sentiment.db`` 内部表，不连接外部服务。调用方负责在进入聚合前
完成抓取和打分，并用 ``retail_window_ledger.status`` 如实记录 partial/failed。
旧三层桶表继续保留；V2 表使用独立名字，避免两套时间语义混写。
"""
from __future__ import annotations

import json
import hashlib
import math
import sqlite3
from collections import defaultdict, deque
from datetime import date, datetime, timedelta
from typing import Iterable

try:
    from . import common, senti3
except ImportError:  # 兼容 ``python tools/sentiment/retail_windows_v2.py``
    import common  # type: ignore
    import senti3  # type: ignore


AGGREGATION_VERSION = "retail.aggregate.v3"
SCORING_VERSION = "retail.mixed_source_and_deepseek.v1"


V2_DDL = """
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
  retention_state    TEXT NOT NULL DEFAULT 'live',
  sealed_at           TEXT,
  seal_reason         TEXT,
  raw_purge_after     TEXT,
  raw_purged_at       TEXT,
  aggregate_sha256    TEXT,
  UNIQUE(session_date, slot)
);
CREATE INDEX IF NOT EXISTS ix_retail_window_due
  ON retail_window_ledger(status, scheduled_for);

CREATE TABLE IF NOT EXISTS yuqing_feed_raw (
  dedup_key    TEXT PRIMARY KEY,
  post_id      TEXT,
  platform     TEXT NOT NULL,
  title        TEXT,
  content_text TEXT,
  url          TEXT,
  author       TEXT,
  author_uid   TEXT,
  publish_time TEXT NOT NULL,
  fetched_at   TEXT NOT NULL,
  source_status TEXT NOT NULL,
  window_id    TEXT NOT NULL REFERENCES retail_window_ledger(window_id) ON DELETE RESTRICT,
  raw_json_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_yuqing_feed_window
  ON yuqing_feed_raw(window_id, platform, publish_time);

-- 星瀚 /subject/infos 的 timestamp 是分页快照边界。活跃 checkpoint 必须同时
-- 保存该 timestamp 和下一页 offset，进程重启后才能精确续页而不是按发布时间猜测。
CREATE TABLE IF NOT EXISTS yuqing_fetch_checkpoint (
  window_id            TEXT NOT NULL REFERENCES retail_window_ledger(window_id) ON DELETE CASCADE,
  subject_id           TEXT NOT NULL,
  request_variant      TEXT NOT NULL,
  segment_start        TEXT NOT NULL,
  segment_end          TEXT NOT NULL,
  request_begin_ms     INTEGER NOT NULL,
  request_end_ms       INTEGER NOT NULL,
  snapshot_timestamp_ms INTEGER NOT NULL,
  next_offset          INTEGER NOT NULL DEFAULT 0 CHECK(next_offset >= 0),
  page_size            INTEGER NOT NULL CHECK(page_size > 0),
  pages_committed      INTEGER NOT NULL DEFAULT 0 CHECK(pages_committed >= 0),
  records_seen         INTEGER NOT NULL DEFAULT 0 CHECK(records_seen >= 0),
  created_at           TEXT NOT NULL,
  updated_at           TEXT NOT NULL,
  PRIMARY KEY(window_id, subject_id, request_variant, segment_start, segment_end)
);
CREATE INDEX IF NOT EXISTS ix_yuqing_fetch_checkpoint_window
  ON yuqing_fetch_checkpoint(window_id, updated_at);

-- checkpoint 只代表尚未结束的页游标；短页证明片段结束后删除 checkpoint，
-- 并在本表保留完成事实，避免来源级重跑再次从首页付费抓取同一片段。
CREATE TABLE IF NOT EXISTS yuqing_fetch_segment_run (
  window_id            TEXT NOT NULL REFERENCES retail_window_ledger(window_id) ON DELETE CASCADE,
  subject_id           TEXT NOT NULL,
  request_variant      TEXT NOT NULL,
  segment_start        TEXT NOT NULL,
  segment_end          TEXT NOT NULL,
  status               TEXT NOT NULL CHECK(status IN ('running','partial','complete','failed')),
  snapshot_timestamp_ms INTEGER,
  pages_committed      INTEGER NOT NULL DEFAULT 0 CHECK(pages_committed >= 0),
  records_seen         INTEGER NOT NULL DEFAULT 0 CHECK(records_seen >= 0),
  error_code           TEXT,
  started_at           TEXT NOT NULL,
  finished_at          TEXT,
  updated_at           TEXT NOT NULL,
  PRIMARY KEY(window_id, subject_id, request_variant, segment_start, segment_end)
);
CREATE INDEX IF NOT EXISTS ix_yuqing_fetch_segment_window
  ON yuqing_fetch_segment_run(window_id, status, updated_at);

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
  company_id             INTEGER NOT NULL,
  ticker                 TEXT,
  window_id              TEXT NOT NULL REFERENCES retail_window_ledger(window_id) ON DELETE CASCADE,
  raw_count              INTEGER NOT NULL DEFAULT 0,
  scored_count           INTEGER NOT NULL DEFAULT 0,
  pos                    INTEGER NOT NULL DEFAULT 0,
  neg                    INTEGER NOT NULL DEFAULT 0,
  neu                    INTEGER NOT NULL DEFAULT 0,
  net_plain              REAL,
  net_weighted           REAL,
  weighted_pos           REAL NOT NULL DEFAULT 0,
  weighted_neg           REAL NOT NULL DEFAULT 0,
  weighted_neu           REAL NOT NULL DEFAULT 0,
  platform_label_json    TEXT NOT NULL DEFAULT '{}',
  coverage               REAL NOT NULL DEFAULT 0,
  significant            INTEGER NOT NULL DEFAULT 0,
  usable                 INTEGER NOT NULL DEFAULT 0,
  n_xueqiu               INTEGER NOT NULL DEFAULT 0,
  n_eastmoney            INTEGER NOT NULL DEFAULT 0,
  n_ths                  INTEGER NOT NULL DEFAULT 0,
  n_weibo                INTEGER NOT NULL DEFAULT 0,
  n_guba                 INTEGER NOT NULL DEFAULT 0,
  aggregation_version    TEXT NOT NULL DEFAULT 'legacy',
  scoring_version        TEXT NOT NULL DEFAULT 'legacy',
  weight_version         TEXT NOT NULL DEFAULT 'legacy',
  aggregate_sha256       TEXT,
  computed_at            TEXT NOT NULL,
  PRIMARY KEY(company_id, window_id)
);
CREATE INDEX IF NOT EXISTS ix_senti_retail_window_window
  ON senti_retail_window(window_id, company_id);

CREATE TABLE IF NOT EXISTS senti_retail_trading_daily (
  company_id             INTEGER NOT NULL,
  ticker                 TEXT,
  session_date           TEXT NOT NULL,
  raw_count              INTEGER NOT NULL DEFAULT 0,
  scored_count           INTEGER NOT NULL DEFAULT 0,
  pos                    INTEGER NOT NULL DEFAULT 0,
  neg                    INTEGER NOT NULL DEFAULT 0,
  neu                    INTEGER NOT NULL DEFAULT 0,
  net_plain              REAL,
  net_weighted           REAL,
  weighted_pos           REAL NOT NULL DEFAULT 0,
  weighted_neg           REAL NOT NULL DEFAULT 0,
  weighted_neu           REAL NOT NULL DEFAULT 0,
  platform_label_json    TEXT NOT NULL DEFAULT '{}',
  coverage               REAL NOT NULL DEFAULT 0,
  significant            INTEGER NOT NULL DEFAULT 0,
  usable                 INTEGER NOT NULL DEFAULT 0,
  n_xueqiu               INTEGER NOT NULL DEFAULT 0,
  n_eastmoney            INTEGER NOT NULL DEFAULT 0,
  n_ths                  INTEGER NOT NULL DEFAULT 0,
  n_weibo                INTEGER NOT NULL DEFAULT 0,
  n_guba                 INTEGER NOT NULL DEFAULT 0,
  completed_windows      INTEGER NOT NULL DEFAULT 0,
  expected_windows       INTEGER NOT NULL DEFAULT 3,
  complete               INTEGER NOT NULL DEFAULT 0,
  aggregation_version    TEXT NOT NULL DEFAULT 'legacy',
  scoring_version        TEXT NOT NULL DEFAULT 'legacy',
  weight_version         TEXT NOT NULL DEFAULT 'legacy',
  aggregate_sha256       TEXT,
  computed_at            TEXT NOT NULL,
  PRIMARY KEY(company_id, session_date)
);
CREATE INDEX IF NOT EXISTS ix_senti_retail_daily_date
  ON senti_retail_trading_daily(session_date, company_id);

CREATE TABLE IF NOT EXISTS sentiment_retention_run (
  run_id                 TEXT PRIMARY KEY,
  mode                   TEXT NOT NULL,
  dry_run                INTEGER NOT NULL,
  grace_days             INTEGER NOT NULL,
  cutoff                 TEXT NOT NULL,
  include_legacy         INTEGER NOT NULL DEFAULT 0,
  include_incomplete     INTEGER NOT NULL DEFAULT 0,
  state                  TEXT NOT NULL,
  plan_json              TEXT NOT NULL DEFAULT '{}',
  result_json            TEXT NOT NULL DEFAULT '{}',
  started_at             TEXT NOT NULL,
  finished_at            TEXT,
  error                  TEXT
);

CREATE TABLE IF NOT EXISTS sentiment_schema_meta (
  migration_id           TEXT PRIMARY KEY,
  applied_at             TEXT NOT NULL,
  detail                 TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sentiment_retention_window (
  run_id                 TEXT NOT NULL REFERENCES sentiment_retention_run(run_id)
                         ON DELETE CASCADE,
  window_id              TEXT NOT NULL,
  action                 TEXT NOT NULL,
  prior_status           TEXT,
  raw_rows               INTEGER NOT NULL DEFAULT 0,
  mapping_rows           INTEGER NOT NULL DEFAULT 0,
  feed_rows              INTEGER NOT NULL DEFAULT 0,
  estimated_bytes        INTEGER NOT NULL DEFAULT 0,
  aggregate_sha256       TEXT,
  created_at             TEXT NOT NULL,
  PRIMARY KEY(run_id, window_id, action)
);
"""


def ensure_schema(con: sqlite3.Connection) -> None:
    # ``Connection.executescript`` may implicitly commit an already-open
    # transaction.  Migrations call this helper inside one atomic transaction,
    # so execute complete statements one by one instead.
    statement = ""
    for line in V2_DDL.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            sql = statement.strip()
            if sql:
                con.execute(sql)
            statement = ""
    if statement.strip():
        raise RuntimeError("incomplete V2 DDL statement")
    feed_columns = {row[1] for row in con.execute("PRAGMA table_info(yuqing_feed_raw)")}
    if feed_columns and "source_status" not in feed_columns:
        con.execute(
            "ALTER TABLE yuqing_feed_raw ADD COLUMN source_status TEXT NOT NULL DEFAULT 'legacy_unknown'"
        )
    _ensure_columns(
        con,
        "retail_window_ledger",
        {
            "retention_state": "TEXT NOT NULL DEFAULT 'live'",
            "sealed_at": "TEXT",
            "seal_reason": "TEXT",
            "raw_purge_after": "TEXT",
            "raw_purged_at": "TEXT",
            "aggregate_sha256": "TEXT",
        },
    )
    aggregate_columns = {
        "weighted_pos": "REAL NOT NULL DEFAULT 0",
        "weighted_neg": "REAL NOT NULL DEFAULT 0",
        "weighted_neu": "REAL NOT NULL DEFAULT 0",
        "platform_label_json": "TEXT NOT NULL DEFAULT '{}'",
        "aggregation_version": "TEXT NOT NULL DEFAULT 'legacy'",
        "scoring_version": "TEXT NOT NULL DEFAULT 'legacy'",
        "weight_version": "TEXT NOT NULL DEFAULT 'legacy'",
        "aggregate_sha256": "TEXT",
    }
    _ensure_columns(con, "senti_retail_window", aggregate_columns)
    _ensure_columns(con, "senti_retail_trading_daily", aggregate_columns)
    _ensure_yuqing_request_variant_schema(con)
    con.execute(
        """INSERT OR IGNORE INTO sentiment_schema_meta(
             migration_id,applied_at,detail)
           VALUES(?,?,?)""",
        (
            "sentiment.window_retention.v1",
            common.now_iso(),
            "窗口永久聚合、封存和原始评论滚动保留",
        ),
    )


def _ensure_columns(
    con: sqlite3.Connection,
    table: str,
    columns: dict[str, str],
) -> None:
    existing = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
    for name, declaration in columns.items():
        if name not in existing:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")


def _pk_columns(con: sqlite3.Connection, table: str) -> list[str]:
    """Return primary-key columns in their declared order."""
    rows = con.execute(f"PRAGMA table_info({table})").fetchall()
    return [row[1] for row in sorted((row for row in rows if row[5]), key=lambda row: row[5])]


def _ensure_yuqing_request_variant_schema(con: sqlite3.Connection) -> None:
    """Idempotently preserve request variants in pagination/audit state.

    Older databases keyed both tables by ``(window_id, subject_id, segment)``.
    Existing rows are authoritative all-media request state and are migrated as
    such.  The variant key remains for schema compatibility; the retired generic
    Weibo request is no longer produced or required.
    """
    expected_pk = [
        "window_id", "subject_id", "request_variant", "segment_start", "segment_end",
    ]
    tables = ("yuqing_fetch_checkpoint", "yuqing_fetch_segment_run")
    if all(_pk_columns(con, table) == expected_pk for table in tables):
        return

    checkpoint_columns = {
        row[1] for row in con.execute("PRAGMA table_info(yuqing_fetch_checkpoint)")
    }
    segment_columns = {
        row[1] for row in con.execute("PRAGMA table_info(yuqing_fetch_segment_run)")
    }
    checkpoint_variant = (
        "COALESCE(NULLIF(request_variant,''),'all')"
        if "request_variant" in checkpoint_columns else "'all'"
    )
    segment_variant = (
        "COALESCE(NULLIF(request_variant,''),'all')"
        if "request_variant" in segment_columns else "'all'"
    )

    con.execute("SAVEPOINT migrate_yuqing_request_variant")
    try:
        con.execute("DROP TABLE IF EXISTS yuqing_fetch_checkpoint__variant_new")
        con.execute("DROP TABLE IF EXISTS yuqing_fetch_segment_run__variant_new")
        con.execute(
            """CREATE TABLE yuqing_fetch_checkpoint__variant_new (
                 window_id TEXT NOT NULL REFERENCES retail_window_ledger(window_id) ON DELETE CASCADE,
                 subject_id TEXT NOT NULL,
                 request_variant TEXT NOT NULL,
                 segment_start TEXT NOT NULL,
                 segment_end TEXT NOT NULL,
                 request_begin_ms INTEGER NOT NULL,
                 request_end_ms INTEGER NOT NULL,
                 snapshot_timestamp_ms INTEGER NOT NULL,
                 next_offset INTEGER NOT NULL DEFAULT 0 CHECK(next_offset >= 0),
                 page_size INTEGER NOT NULL CHECK(page_size > 0),
                 pages_committed INTEGER NOT NULL DEFAULT 0 CHECK(pages_committed >= 0),
                 records_seen INTEGER NOT NULL DEFAULT 0 CHECK(records_seen >= 0),
                 created_at TEXT NOT NULL,
                 updated_at TEXT NOT NULL,
                 PRIMARY KEY(window_id,subject_id,request_variant,segment_start,segment_end)
               )"""
        )
        con.execute(
            """CREATE TABLE yuqing_fetch_segment_run__variant_new (
                 window_id TEXT NOT NULL REFERENCES retail_window_ledger(window_id) ON DELETE CASCADE,
                 subject_id TEXT NOT NULL,
                 request_variant TEXT NOT NULL,
                 segment_start TEXT NOT NULL,
                 segment_end TEXT NOT NULL,
                 status TEXT NOT NULL CHECK(status IN ('running','partial','complete','failed')),
                 snapshot_timestamp_ms INTEGER,
                 pages_committed INTEGER NOT NULL DEFAULT 0 CHECK(pages_committed >= 0),
                 records_seen INTEGER NOT NULL DEFAULT 0 CHECK(records_seen >= 0),
                 error_code TEXT,
                 started_at TEXT NOT NULL,
                 finished_at TEXT,
                 updated_at TEXT NOT NULL,
                 PRIMARY KEY(window_id,subject_id,request_variant,segment_start,segment_end)
               )"""
        )
        con.execute(
            f"""INSERT INTO yuqing_fetch_checkpoint__variant_new(
                   window_id,subject_id,request_variant,segment_start,segment_end,
                   request_begin_ms,request_end_ms,snapshot_timestamp_ms,next_offset,page_size,
                   pages_committed,records_seen,created_at,updated_at)
                 SELECT window_id,subject_id,{checkpoint_variant},segment_start,segment_end,
                        request_begin_ms,request_end_ms,snapshot_timestamp_ms,next_offset,page_size,
                        pages_committed,records_seen,created_at,updated_at
                 FROM yuqing_fetch_checkpoint"""
        )
        con.execute(
            f"""INSERT INTO yuqing_fetch_segment_run__variant_new(
                   window_id,subject_id,request_variant,segment_start,segment_end,status,
                   snapshot_timestamp_ms,pages_committed,records_seen,error_code,
                   started_at,finished_at,updated_at)
                 SELECT window_id,subject_id,{segment_variant},segment_start,segment_end,status,
                        snapshot_timestamp_ms,pages_committed,records_seen,error_code,
                        started_at,finished_at,updated_at
                 FROM yuqing_fetch_segment_run"""
        )
        con.execute("DROP TABLE yuqing_fetch_checkpoint")
        con.execute("DROP TABLE yuqing_fetch_segment_run")
        con.execute(
            "ALTER TABLE yuqing_fetch_checkpoint__variant_new RENAME TO yuqing_fetch_checkpoint"
        )
        con.execute(
            "ALTER TABLE yuqing_fetch_segment_run__variant_new RENAME TO yuqing_fetch_segment_run"
        )
        con.execute(
            "CREATE INDEX ix_yuqing_fetch_checkpoint_window "
            "ON yuqing_fetch_checkpoint(window_id,updated_at)"
        )
        con.execute(
            "CREATE INDEX ix_yuqing_fetch_segment_window "
            "ON yuqing_fetch_segment_run(window_id,status,updated_at)"
        )
        con.execute("RELEASE SAVEPOINT migrate_yuqing_request_variant")
    except Exception:
        con.execute("ROLLBACK TO SAVEPOINT migrate_yuqing_request_variant")
        con.execute("RELEASE SAVEPOINT migrate_yuqing_request_variant")
        raise


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="minutes")


def ensure_window(con: sqlite3.Connection, window: senti3.MarketWindow) -> str:
    """幂等登记一个 V2 窗口；相同 id 的边界不允许静默漂移。"""
    segments = json.dumps([[_iso(a), _iso(b)] for a, b in window.segments], ensure_ascii=False)
    con.execute(
        """INSERT INTO retail_window_ledger(
             window_id,window_version,session_date,slot,window_start,window_end,
             scheduled_for,segments_json,effective_minutes,status)
           VALUES(?,?,?,?,?,?,?,?,?,'pending')
           ON CONFLICT(window_id) DO NOTHING""",
        (
            window.window_id,
            window.version,
            window.session_date.isoformat(),
            window.slot,
            _iso(window.window_start),
            _iso(window.window_end),
            _iso(window.scheduled_for),
            segments,
            window.effective_minutes,
        ),
    )
    row = con.execute(
        """SELECT window_version,session_date,slot,window_start,window_end,segments_json
           FROM retail_window_ledger WHERE window_id=?""",
        (window.window_id,),
    ).fetchone()
    expected = (
        window.version,
        window.session_date.isoformat(),
        window.slot,
        _iso(window.window_start),
        _iso(window.window_end),
        segments,
    )
    if row is None or tuple(row) != expected:
        raise RuntimeError(f"window contract drift: {window.window_id}")
    return window.window_id


def _parse_publish_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo is not None else None


def map_retail_raw_rows(
    con: sqlite3.Connection,
    *,
    since: str | None = None,
    until: str | None = None,
    raw_ids: Iterable[int] | None = None,
    trading_days: set[date] | None = None,
    mapped_at: str | None = None,
) -> dict[str, int]:
    """把真实发布时间映射到唯一 V2 window；周末/休市/坏时间均不映射。"""
    ensure_schema(con)
    where = ["source_layer='retail'", "platform<>'weibo'", "publish_time IS NOT NULL"]
    params: list[object] = []
    if since:
        where.append("publish_time>=?")
        params.append(since)
    if until:
        where.append("publish_time<?")
        params.append(until)
    ids = [int(v) for v in raw_ids] if raw_ids is not None else []
    if raw_ids is not None:
        if not ids:
            return {"seen": 0, "mapped": 0, "excluded_non_session": 0, "invalid_time": 0}
        where.append(f"id IN ({','.join('?' for _ in ids)})")
        params.extend(ids)
    rows = con.execute(
        f"SELECT id,publish_time FROM senti_raw WHERE {' AND '.join(where)} ORDER BY id",
        params,
    ).fetchall()
    now = mapped_at or common.now_iso()
    stat = {"seen": len(rows), "mapped": 0, "excluded_non_session": 0, "invalid_time": 0}
    for row in rows:
        raw_id = row["id"] if hasattr(row, "keys") else row[0]
        dt = _parse_publish_time(row["publish_time"] if hasattr(row, "keys") else row[1])
        if dt is None:
            con.execute("DELETE FROM senti_raw_window WHERE raw_id=?", (raw_id,))
            stat["invalid_time"] += 1
            continue
        window = senti3.market_window_for_timestamp(dt, trading_days)
        if window is None:
            con.execute("DELETE FROM senti_raw_window WHERE raw_id=?", (raw_id,))
            stat["excluded_non_session"] += 1
            continue
        ensure_window(con, window)
        con.execute(
            """INSERT INTO senti_raw_window(raw_id,window_id,mapping_version,mapped_at)
               VALUES(?,?,?,?)
               ON CONFLICT(raw_id) DO UPDATE SET
                 window_id=excluded.window_id,
                 mapping_version=excluded.mapping_version,
                 mapped_at=excluded.mapped_at""",
            (raw_id, window.window_id, senti3.MARKET_WINDOW_VERSION, now),
        )
        stat["mapped"] += 1
    return stat


def store_yuqing_feed_record(
    con: sqlite3.Connection,
    record: dict,
    *,
    platform: str,
    expected_window_id: str | None = None,
    trading_days: set[date] | None = None,
    fetched_at: str | None = None,
    source_status: str = "ok",
) -> str | None:
    """先于公司归因保存星瀚原始记录；休市日或越窗记录完全跳过。

    只保存研究所需字段和内容哈希，不保存 API token、cookie 或整包原始 JSON。
    返回实际 ``window_id``；返回 ``None`` 表示发布时间无效、周末/休市或不在
    调用方声明的窗口内。
    """
    if str(platform or "").strip().lower() == "weibo":
        return None
    publish_time = record.get("publish_time")
    dt = _parse_publish_time(publish_time)
    if dt is None:
        return None
    window = senti3.market_window_for_timestamp(dt, trading_days)
    if window is None or (expected_window_id and window.window_id != expected_window_id):
        return None
    ensure_schema(con)
    ensure_window(con, window)
    selected = {
        key: record.get(key)
        for key in (
            "dedup_key", "post_id", "title", "text", "url", "author", "author_uid",
            "publish_time", "web_name", "domain", "channel", "media_type", "sim_hash",
        )
    }
    raw_hash = hashlib.sha256(
        json.dumps(selected, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    dedup_key = str(record.get("dedup_key") or "").strip()
    if not dedup_key:
        return None
    now = fetched_at or common.now_iso()
    con.execute(
        """INSERT INTO yuqing_feed_raw(
             dedup_key,post_id,platform,title,content_text,url,author,author_uid,
             publish_time,fetched_at,source_status,window_id,raw_json_hash)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(dedup_key) DO UPDATE SET
             post_id=COALESCE(excluded.post_id,yuqing_feed_raw.post_id),
             platform=excluded.platform,
             title=CASE WHEN LENGTH(COALESCE(excluded.title,''))>
                              LENGTH(COALESCE(yuqing_feed_raw.title,''))
                        THEN excluded.title ELSE yuqing_feed_raw.title END,
             content_text=CASE WHEN LENGTH(COALESCE(excluded.content_text,''))>
                                     LENGTH(COALESCE(yuqing_feed_raw.content_text,''))
                               THEN excluded.content_text ELSE yuqing_feed_raw.content_text END,
             url=COALESCE(excluded.url,yuqing_feed_raw.url),
             author=COALESCE(excluded.author,yuqing_feed_raw.author),
             author_uid=COALESCE(excluded.author_uid,yuqing_feed_raw.author_uid),
             publish_time=excluded.publish_time,
             fetched_at=excluded.fetched_at,
             source_status=excluded.source_status,
             window_id=excluded.window_id,
             raw_json_hash=excluded.raw_json_hash""",
        (
            dedup_key,
            record.get("post_id"),
            platform or "unclassified",
            record.get("title"),
            record.get("text"),
            record.get("url"),
            record.get("author"),
            record.get("author_uid"),
            publish_time,
            now,
            source_status,
            window.window_id,
            raw_hash,
        ),
    )
    return window.window_id


def _finite_ratio(num: float, den: float) -> float | None:
    if not den:
        return None
    value = num / den
    return value if math.isfinite(value) else None


def _canonical_ticker(values: Iterable[str | None]) -> str | None:
    clean = [str(v).strip().upper() for v in values if v and str(v).strip()]
    for value in clean:
        if "." in value and any(ch.isdigit() for ch in value):
            return value
    return clean[0] if clean else None


def _empty_aggregate() -> dict:
    return {
        "tickers": [],
        "raw": 0,
        "scored": 0,
        "pos": 0,
        "neg": 0,
        "neu": 0,
        "wp": 0.0,
        "wn": 0.0,
        "wnu": 0.0,
        "platform_labels": {},
        "n_xueqiu": 0,
        "n_eastmoney": 0,
        "n_ths": 0,
        "n_weibo": 0,
        "n_guba": 0,
    }


def _aggregate_rows(rows: Iterable[sqlite3.Row], weights: dict[str, float]) -> dict[int, dict]:
    agg: dict[int, dict] = defaultdict(
        _empty_aggregate
    )
    for row in rows:
        if str(row["platform"] or "").strip().lower() == "weibo":
            continue
        cid = int(row["canonical_company_id"] or row["company_id"])
        item = agg[cid]
        item["tickers"].append(row["ticker"])
        item["raw"] += 1
        platform = str(row["platform"] or "")
        key = f"n_{platform}"
        if key in item:
            item[key] += 1
        attitude = row["attitude"]
        if attitude not in (1, 2, 3):
            continue
        item["scored"] += 1
        label = "pos" if attitude == 1 else ("neg" if attitude == 2 else "neu")
        item[label] += 1
        platform_labels = item["platform_labels"].setdefault(
            platform,
            {"pos": 0, "neg": 0, "neu": 0},
        )
        platform_labels[label] += 1
        heat = max(float(row["heat_value"] or 0), 1.0)
        weighted = heat * float(weights.get(platform, 1.0))
        item[{"pos": "wp", "neg": "wn", "neu": "wnu"}[label]] += weighted
    return agg


def _weight_version(weights: dict[str, float]) -> str:
    payload = json.dumps(
        {str(key): float(value) for key, value in sorted(weights.items())},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "retail.weights.sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _payload_sha256(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _metric(
    item: dict,
    significance_min: int,
    run_complete: bool,
    *,
    weights: dict[str, float],
) -> dict:
    scored = item["scored"]
    raw = item["raw"]
    plain = _finite_ratio(item["pos"] - item["neg"], scored)
    weighted = _finite_ratio(item["wp"] - item["wn"], item["wp"] + item["wn"] + item["wnu"])
    significant = int(scored > significance_min)
    return {
        **item,
        "ticker": _canonical_ticker(item["tickers"]),
        "net_plain": plain,
        "net_weighted": weighted,
        "weighted_pos": float(item["wp"]),
        "weighted_neg": float(item["wn"]),
        "weighted_neu": float(item["wnu"]),
        "platform_label_json": json.dumps(
            item["platform_labels"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        "coverage": (scored / raw) if raw else 0.0,
        "significant": significant,
        "usable": int(bool(run_complete and significant)),
        "aggregation_version": AGGREGATION_VERSION,
        "scoring_version": SCORING_VERSION,
        "weight_version": _weight_version(weights),
    }


def _fact_payload(item: dict, identity: dict) -> dict:
    return {
        **identity,
        "ticker": item["ticker"],
        "raw_count": item["raw"],
        "scored_count": item["scored"],
        "pos": item["pos"],
        "neg": item["neg"],
        "neu": item["neu"],
        "net_plain": item["net_plain"],
        "net_weighted": item["net_weighted"],
        "weighted_pos": item["weighted_pos"],
        "weighted_neg": item["weighted_neg"],
        "weighted_neu": item["weighted_neu"],
        "platform_label_json": item["platform_label_json"],
        "coverage": item["coverage"],
        "significant": item["significant"],
        "usable": item["usable"],
        "n_xueqiu": item["n_xueqiu"],
        "n_eastmoney": item["n_eastmoney"],
        "n_ths": item["n_ths"],
        "n_weibo": item["n_weibo"],
        "n_guba": item["n_guba"],
        "aggregation_version": item["aggregation_version"],
        "scoring_version": item["scoring_version"],
        "weight_version": item["weight_version"],
    }


def _window_bundle_sha256(con: sqlite3.Connection, window_id: str) -> str:
    rows = con.execute(
        """SELECT company_id,aggregate_sha256
           FROM senti_retail_window
           WHERE window_id=?
           ORDER BY company_id""",
        (window_id,),
    ).fetchall()
    return _payload_sha256(
        {
            "window_id": window_id,
            "aggregation_version": AGGREGATION_VERSION,
            "rows": [
                [int(row["company_id"]), str(row["aggregate_sha256"] or "")]
                for row in rows
            ],
        }
    )


def window_has_active_work(con: sqlite3.Connection, window_id: str) -> bool:
    checkpoint = con.execute(
        "SELECT 1 FROM yuqing_fetch_checkpoint WHERE window_id=? LIMIT 1",
        (window_id,),
    ).fetchone()
    if checkpoint:
        return True
    source_run = con.execute(
        """SELECT 1 FROM retail_window_source_run
           WHERE window_id=? AND status='running' LIMIT 1""",
        (window_id,),
    ).fetchone()
    if source_run:
        return True
    segment_run = con.execute(
        """SELECT 1 FROM yuqing_fetch_segment_run
           WHERE window_id=? AND status='running' LIMIT 1""",
        (window_id,),
    ).fetchone()
    return bool(segment_run)


def seal_window(
    con: sqlite3.Connection,
    window_id: str,
    *,
    grace_days: int = 0,
    allow_incomplete: bool = False,
    sealed_at: str | None = None,
) -> dict:
    """Freeze one window after recomputing all permanent facts from raw."""
    ensure_schema(con)
    if grace_days < 0:
        raise ValueError("grace_days must be non-negative")
    ledger = con.execute(
        """SELECT status,finished_at,window_end,retention_state
           FROM retail_window_ledger WHERE window_id=?""",
        (window_id,),
    ).fetchone()
    if not ledger:
        raise ValueError(f"window 不存在: {window_id}")
    status = str(ledger["status"])
    if status == "running" or window_has_active_work(con, window_id):
        raise RuntimeError(f"活动 window 不可封存: {window_id}")
    complete = status == "complete"
    if not complete and not allow_incomplete:
        raise RuntimeError(f"非完整 window 需要显式授权: {window_id} status={status}")
    now_text = sealed_at or common.now_iso()
    now = datetime.fromisoformat(now_text)
    anchor_text = str(ledger["finished_at"] or ledger["window_end"] or now_text)
    anchor = datetime.fromisoformat(anchor_text)
    purge_after = anchor + timedelta(days=grace_days)
    aggregate_window(
        con,
        window_id,
        computed_at=now_text,
        recompute_daily=False,
    )
    refreshed = con.execute(
        """SELECT aggregate_sha256,raw_count,scored_count
           FROM retail_window_ledger WHERE window_id=?""",
        (window_id,),
    ).fetchone()
    if not refreshed or not str(refreshed["aggregate_sha256"] or ""):
        raise RuntimeError(f"window 聚合哈希为空: {window_id}")
    retention_state = "sealed_complete" if complete else "sealed_incomplete"
    con.execute(
        """UPDATE retail_window_ledger SET
             retention_state=?,sealed_at=?,seal_reason=?,raw_purge_after=?,
             raw_purged_at=NULL
           WHERE window_id=?""",
        (
            retention_state,
            now_text,
            "complete_verified" if complete else f"incomplete_explicit:{status}",
            purge_after.isoformat(timespec="seconds"),
            window_id,
        ),
    )
    return {
        "window_id": window_id,
        "status": status,
        "retention_state": retention_state,
        "raw_count": int(refreshed["raw_count"] or 0),
        "scored_count": int(refreshed["scored_count"] or 0),
        "aggregate_sha256": str(refreshed["aggregate_sha256"]),
        "sealed_at": now_text,
        "raw_purge_after": purge_after.isoformat(timespec="seconds"),
    }


def aggregate_window(
    con: sqlite3.Connection,
    window_id: str,
    *,
    weights: dict[str, float] | None = None,
    significance_min: int = senti3.SIGNIFICANCE_MIN,
    computed_at: str | None = None,
    recompute_daily: bool = True,
) -> int:
    """从 raw + 映射重算一个窗口；post volume 严格只计 ``source_layer=retail``。"""
    ensure_schema(con)
    ledger = con.execute(
        "SELECT status,session_date FROM retail_window_ledger WHERE window_id=?", (window_id,)
    ).fetchone()
    if not ledger:
        raise ValueError(f"window 不存在: {window_id}")
    rows = con.execute(
        """SELECT r.company_id,r.ticker,r.platform,r.attitude,r.heat_value,
                  d.canonical_company_id
           FROM senti_raw_window rw
           JOIN senti_raw r ON r.id=rw.raw_id
           LEFT JOIN company_id_redirect d ON d.old_company_id=r.company_id
           WHERE rw.window_id=? AND r.source_layer='retail' AND r.platform<>'weibo'
           ORDER BY r.company_id,r.id""",
        (window_id,),
    ).fetchall()
    cfg_weights = weights or senti3.DEFAULT_RETAIL_WEIGHTS
    grouped = _aggregate_rows(rows, cfg_weights)
    now = computed_at or common.now_iso()
    con.execute("DELETE FROM senti_retail_window WHERE window_id=?", (window_id,))
    ledger_status = ledger["status"] if hasattr(ledger, "keys") else ledger[0]
    ledger_session_date = ledger["session_date"] if hasattr(ledger, "keys") else ledger[1]
    run_complete = ledger_status == "complete"
    for cid, raw_item in grouped.items():
        item = _metric(
            raw_item,
            significance_min,
            run_complete,
            weights=cfg_weights,
        )
        fact_payload = _fact_payload(
            item,
            {"company_id": cid, "window_id": window_id},
        )
        aggregate_sha256 = _payload_sha256(fact_payload)
        con.execute(
            """INSERT INTO senti_retail_window(
                 company_id,ticker,window_id,raw_count,scored_count,pos,neg,neu,
                 net_plain,net_weighted,weighted_pos,weighted_neg,weighted_neu,
                 platform_label_json,coverage,significant,usable,
                 n_xueqiu,n_eastmoney,n_ths,n_weibo,n_guba,
                 aggregation_version,scoring_version,weight_version,
                 aggregate_sha256,computed_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                cid, item["ticker"], window_id, item["raw"], item["scored"],
                item["pos"], item["neg"], item["neu"], item["net_plain"], item["net_weighted"],
                item["weighted_pos"], item["weighted_neg"], item["weighted_neu"],
                item["platform_label_json"], item["coverage"], item["significant"],
                item["usable"], item["n_xueqiu"], item["n_eastmoney"], item["n_ths"],
                item["n_weibo"], item["n_guba"], item["aggregation_version"],
                item["scoring_version"], item["weight_version"], aggregate_sha256, now,
            ),
        )
    window_sha256 = _window_bundle_sha256(con, window_id)
    con.execute(
        """UPDATE retail_window_ledger SET
             raw_count=?, scored_count=?, aggregate_sha256=?
           WHERE window_id=?""",
        (
            sum(v["raw"] for v in grouped.values()),
            sum(v["scored"] for v in grouped.values()),
            window_sha256,
            window_id,
        ),
    )
    if recompute_daily:
        aggregate_trading_day(
            con,
            ledger_session_date,
            weights=cfg_weights,
            significance_min=significance_min,
            computed_at=now,
        )
    return len(grouped)


def aggregate_trading_day(
    con: sqlite3.Connection,
    session_date: str,
    *,
    weights: dict[str, float] | None = None,
    significance_min: int = senti3.SIGNIFICANCE_MIN,
    computed_at: str | None = None,
) -> int:
    """按 session_date 从永久窗口事实重算交易日；仅 complete 窗口贡献。"""
    ensure_schema(con)
    completed = con.execute(
        """SELECT COUNT(*) FROM retail_window_ledger
           WHERE session_date=? AND status='complete'""",
        (session_date,),
    ).fetchone()[0]
    rows = con.execute(
        """SELECT f.*
           FROM senti_retail_window f
           JOIN retail_window_ledger w ON w.window_id=f.window_id
           WHERE w.session_date=? AND w.status='complete'
           ORDER BY f.company_id,f.window_id""",
        (session_date,),
    ).fetchall()
    cfg_weights = weights or senti3.DEFAULT_RETAIL_WEIGHTS
    legacy_windows = sorted(
        {
            str(row["window_id"])
            for row in rows
            if str(row["aggregation_version"] or "legacy")
            != AGGREGATION_VERSION
        }
    )
    if legacy_windows:
        raise RuntimeError(
            "交易日聚合发现未迁移窗口: " + ",".join(legacy_windows[:10])
        )
    grouped: dict[int, dict] = defaultdict(_empty_aggregate)
    for row in rows:
        cid = int(row["company_id"])
        item = grouped[cid]
        item["tickers"].append(row["ticker"])
        item["raw"] += int(row["raw_count"] or 0)
        item["scored"] += int(row["scored_count"] or 0)
        item["pos"] += int(row["pos"] or 0)
        item["neg"] += int(row["neg"] or 0)
        item["neu"] += int(row["neu"] or 0)
        item["wp"] += float(row["weighted_pos"] or 0.0)
        item["wn"] += float(row["weighted_neg"] or 0.0)
        item["wnu"] += float(row["weighted_neu"] or 0.0)
        for key in (
            "n_xueqiu",
            "n_eastmoney",
            "n_ths",
            "n_weibo",
            "n_guba",
        ):
            item[key] += int(row[key] or 0)
        try:
            platform_labels = json.loads(row["platform_label_json"] or "{}")
        except (TypeError, ValueError):
            platform_labels = {}
        for platform, labels in platform_labels.items():
            target = item["platform_labels"].setdefault(
                str(platform),
                {"pos": 0, "neg": 0, "neu": 0},
            )
            for label in ("pos", "neg", "neu"):
                target[label] += int((labels or {}).get(label) or 0)
    now = computed_at or common.now_iso()
    day_complete = completed == len(senti3.MARKET_WINDOW_SLOTS)
    con.execute("DELETE FROM senti_retail_trading_daily WHERE session_date=?", (session_date,))
    for cid, raw_item in grouped.items():
        item = _metric(
            raw_item,
            significance_min,
            day_complete,
            weights=cfg_weights,
        )
        fact_payload = _fact_payload(
            item,
            {"company_id": cid, "session_date": session_date},
        )
        aggregate_sha256 = _payload_sha256(fact_payload)
        con.execute(
            """INSERT INTO senti_retail_trading_daily(
                 company_id,ticker,session_date,raw_count,scored_count,pos,neg,neu,
                 net_plain,net_weighted,weighted_pos,weighted_neg,weighted_neu,
                 platform_label_json,coverage,significant,usable,
                 n_xueqiu,n_eastmoney,n_ths,n_weibo,n_guba,completed_windows,
                 expected_windows,complete,aggregation_version,scoring_version,
                 weight_version,aggregate_sha256,computed_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                cid, item["ticker"], session_date, item["raw"], item["scored"],
                item["pos"], item["neg"], item["neu"], item["net_plain"], item["net_weighted"],
                item["weighted_pos"], item["weighted_neg"], item["weighted_neu"],
                item["platform_label_json"], item["coverage"], item["significant"],
                item["usable"], item["n_xueqiu"], item["n_eastmoney"], item["n_ths"],
                item["n_weibo"], item["n_guba"], completed,
                len(senti3.MARKET_WINDOW_SLOTS), int(day_complete),
                item["aggregation_version"], item["scoring_version"],
                item["weight_version"], aggregate_sha256, now,
            ),
        )
    return len(grouped)


def prepare_window_score_sample(
    con: sqlite3.Connection,
    window_id: str,
    *,
    max_per_company: int = 50,
    top_by_heat: int = 40,
    random_floor: int = 10,
) -> dict[str, int]:
    """Create one stable, fair Guba score sample per company and market window.

    Raw post volume remains complete.  ``sampled`` only gates LLM scoring; posts
    outside the sample keep ``attitude=NULL`` and therefore cannot be fabricated
    as neutral.  Existing labels are retained and count toward the quota so a
    retry never discards paid/verified work.
    """
    rows = con.execute(
        """SELECT r.id,COALESCE(d.canonical_company_id,r.company_id) company_id,
                  COALESCE(r.heat_value,0) heat_value,r.attitude,r.title
           FROM senti_raw_window rw
           JOIN senti_raw r ON r.id=rw.raw_id
           LEFT JOIN company_id_redirect d ON d.old_company_id=r.company_id
           WHERE rw.window_id=? AND r.source_layer='retail' AND r.platform='guba'
           ORDER BY company_id,r.id""",
        (window_id,),
    ).fetchall()
    groups: dict[int, list] = defaultdict(list)
    all_ids = []
    for row in rows:
        all_ids.append((int(row["id"]),))
        if str(row["title"] or "").strip():
            groups[int(row["company_id"])].append(row)
    selected_ids: set[int] = set()
    for company_id, items in groups.items():
        selected, _excluded = senti3.select_sample(
            [(int(row["id"]), row["heat_value"], row["attitude"] is not None) for row in items],
            max_per_bucket=max_per_company,
            top_by_heat=top_by_heat,
            random_floor=random_floor,
            seed=senti3._stable_seed(f"{window_id}|guba|{company_id}"),
        )
        selected_ids.update(selected)
    if all_ids:
        con.executemany("UPDATE senti_raw SET sampled=0 WHERE id=?", all_ids)
    if selected_ids:
        con.executemany(
            "UPDATE senti_raw SET sampled=1 WHERE id=?",
            [(row_id,) for row_id in sorted(selected_ids)],
        )
    con.commit()
    selected_unscored = con.execute(
        f"""SELECT COUNT(*) FROM senti_raw
             WHERE id IN ({','.join('?' for _ in selected_ids)}) AND attitude IS NULL""",
        tuple(sorted(selected_ids)),
    ).fetchone()[0] if selected_ids else 0
    return {
        "companies": len(groups),
        "eligible": sum(len(items) for items in groups.values()),
        "sampled": len(selected_ids),
        "excluded": len(all_ids) - len(selected_ids),
        "unscored": int(selected_unscored),
    }


def fair_score_candidate_ids(
    con: sqlite3.Connection,
    window_id: str,
    *,
    max_total: int | None = None,
    per_company_target: int | None = None,
) -> tuple[list[int], dict[str, int]]:
    """按公司轮转选择待打分 guba 样本，杜绝全局 heat 排序造成的饥饿。"""
    rows = con.execute(
        """SELECT r.id,COALESCE(d.canonical_company_id,r.company_id) company_id,
                  COALESCE(r.heat_value,0) heat_value,r.publish_time
           FROM senti_raw_window rw
           JOIN senti_raw r ON r.id=rw.raw_id
           LEFT JOIN company_id_redirect d ON d.old_company_id=r.company_id
           WHERE rw.window_id=? AND r.source_layer='retail' AND r.platform='guba'
             AND r.attitude IS NULL AND COALESCE(r.sampled,1)=1
             AND r.title IS NOT NULL AND TRIM(r.title)<>''
           ORDER BY company_id,heat_value DESC,publish_time DESC,r.id""",
        (window_id,),
    ).fetchall()
    original_total = len(rows)
    queues: dict[int, deque[int]] = defaultdict(deque)
    for row in rows:
        q = queues[int(row["company_id"])]
        if per_company_target is None or len(q) < per_company_target:
            q.append(int(row["id"]))
    selected: list[int] = []
    active = deque(sorted(queues))
    limit = max_total if max_total is not None and max_total >= 0 else None
    while active and (limit is None or len(selected) < limit):
        cid = active.popleft()
        queue = queues[cid]
        selected.append(queue.popleft())
        if queue:
            active.append(cid)
    return selected, {
        "companies": len(queues),
        "candidates": original_total,
        "selected": len(selected),
        "remaining": original_total - len(selected),
        "complete": int(original_total == len(selected)),
    }


def mark_window_status(
    con: sqlite3.Connection,
    window_id: str,
    status: str,
    *,
    source_status: dict | None = None,
    error: str | None = None,
    timestamp: str | None = None,
) -> None:
    if status not in {"pending", "running", "partial", "complete", "failed"}:
        raise ValueError(f"非法 window status: {status}")
    now = timestamp or common.now_iso()
    cur = con.execute(
        """UPDATE retail_window_ledger SET status=?,
             source_status_json=COALESCE(?,source_status_json),
             error=?,
             started_at=CASE WHEN ?='running' THEN COALESCE(started_at,?) ELSE started_at END,
             finished_at=CASE
               WHEN ?='running' THEN NULL
               WHEN ? IN ('partial','complete','failed') THEN ?
               ELSE finished_at
             END,
             attempts=attempts+CASE WHEN ?='running' THEN 1 ELSE 0 END
           WHERE window_id=?""",
        (
            status,
            json.dumps(source_status, ensure_ascii=False, sort_keys=True) if source_status is not None else None,
            error,
            status,
            now,
            status,
            status,
            now,
            status,
            window_id,
        ),
    )
    if cur.rowcount == 0:
        raise ValueError(f"window 不存在: {window_id}")


__all__ = [
    "AGGREGATION_VERSION",
    "SCORING_VERSION",
    "V2_DDL",
    "aggregate_trading_day",
    "aggregate_window",
    "ensure_schema",
    "ensure_window",
    "fair_score_candidate_ids",
    "map_retail_raw_rows",
    "mark_window_status",
    "prepare_window_score_sample",
    "seal_window",
    "store_yuqing_feed_record",
    "window_has_active_work",
]
