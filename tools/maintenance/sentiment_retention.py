"""`sentiment.db` 原始评论的封存、滚动保留和物理压缩工具。

默认命令只输出计划。任何 schema、封存、删除或文件替换都要求 ``--apply``。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from tools.sentiment import retail_windows_v2, retention_policy, senti3


ROOT = Path(__file__).resolve().parents[2]
from tools.runtime_paths import resolve_runtime_layout
DEFAULT_DB = resolve_runtime_layout(ROOT).data_root / "sentiment.db"
BEIJING = ZoneInfo("Asia/Shanghai")
# 逐帖原文是短生命周期计算材料；窗口终结后三个自然日为统一上限。
DEFAULT_GRACE_DAYS = retention_policy.RAW_RETENTION_DAYS
DEFAULT_LEGACY_CUTOVER = "2026-07-15"
DEFAULT_INCOMPLETE_AGE_DAYS = retention_policy.INCOMPLETE_FINALIZATION_DAYS
PAYLOAD_SAMPLE_ROWS = 10_000
TERMINAL_SEGMENT_STATES = {"complete", "partial", "failed"}
TERMINAL_SOURCE_STATES = {"complete", "partial", "empty", "failed", "skipped"}
UNMAPPED_AGGREGATION_VERSION = "sentiment.unmapped_daily.v1"


def _now() -> datetime:
    return datetime.now(BEIJING)


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _connect(
    path: Path,
    *,
    read_only: bool = False,
    operation_id: str | None = None,
    physical_sqlite: bool = False,
) -> Any:
    if not physical_sqlite:
        from tools.data_platform.domain_data import connect_domain_database

        connection = connect_domain_database(
            "sentiment_analytics",
            path,
            readonly=read_only,
            operation_scope="sentiment_retention",
            operation_id=operation_id,
        )
    elif read_only:
        connection = sqlite3.connect(
            path.resolve().as_uri() + "?mode=ro",
            uri=True,
            timeout=30,
        )
    else:
        connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")
    if not read_only:
        connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row["name"])
        for row in connection.execute(f"PRAGMA table_info({table})")
    }


def schema_ready(connection: sqlite3.Connection) -> bool:
    ledger = _columns(connection, "retail_window_ledger")
    window = _columns(connection, "senti_retail_window")
    return {
        "retention_state",
        "sealed_at",
        "raw_purge_after",
        "raw_purged_at",
        "aggregate_sha256",
    }.issubset(ledger) and {
        "weighted_pos",
        "weighted_neg",
        "weighted_neu",
        "aggregation_version",
        "aggregate_sha256",
    }.issubset(window)


def _table_count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _average_payload(connection: sqlite3.Connection, table: str) -> float:
    columns = [
        str(row["name"])
        for row in connection.execute(f"PRAGMA table_info({table})")
    ]
    if not columns:
        return 0.0
    expression = "+".join(
        f'COALESCE(LENGTH(CAST("{name}" AS BLOB)),0)'
        for name in columns
    )
    row = connection.execute(
        f"""SELECT AVG(({expression})+16)
            FROM (
              SELECT * FROM {table}
              ORDER BY rowid DESC
              LIMIT {PAYLOAD_SAMPLE_ROWS}
            )"""
    ).fetchone()
    return float(row[0] or 0.0)


def _window_counts(connection: sqlite3.Connection, window_id: str) -> dict[str, int]:
    return {
        "raw_rows": int(
            connection.execute(
                "SELECT COUNT(*) FROM senti_raw_window WHERE window_id=?",
                (window_id,),
            ).fetchone()[0]
        ),
        "mapping_rows": int(
            connection.execute(
                "SELECT COUNT(*) FROM senti_raw_window WHERE window_id=?",
                (window_id,),
            ).fetchone()[0]
        ),
        "feed_rows": int(
            connection.execute(
                "SELECT COUNT(*) FROM yuqing_feed_raw WHERE window_id=?",
                (window_id,),
            ).fetchone()[0]
        ),
    }


def _effective_purge_after(row: sqlite3.Row, grace_days: int) -> datetime | None:
    """Use the frozen retention watermark; only legacy rows need derivation.

    A retry may update ``finished_at`` long after the semantic data window.  Once
    a window is sealed, ``raw_purge_after`` is the audited lifecycle boundary
    and must not be extended by a later retry timestamp.
    """
    frozen = str(row["raw_purge_after"] or "")
    if frozen:
        return datetime.fromisoformat(frozen)
    anchor = str(row["finished_at"] or row["window_end"] or "")
    if not anchor:
        return None
    return datetime.fromisoformat(anchor) + timedelta(days=grace_days)


def _terminal_checkpoint_evidence(
    connection: sqlite3.Connection,
    window_id: str,
) -> dict[str, Any]:
    """Prove that every resumable cursor belongs to a terminal segment.

    Callers hold the same exclusive tick lock used by the scheduler.  The
    transition SQLite backend additionally owns a ``BEGIN IMMEDIATE``
    transaction; the PostgreSQL-authoritative compatibility projection already
    owns its unique writer lock and one bounded mutation transaction.  Status
    evidence, rather than a stale PID guess, decides whether a cursor can be
    retired.
    """
    source_rows = connection.execute(
        """SELECT source,status,error_code,finished_at
           FROM retail_window_source_run WHERE window_id=? ORDER BY source""",
        (window_id,),
    ).fetchall()
    source_blockers = [
        f"source:{row['source']}:{row['status']}"
        for row in source_rows
        if str(row["status"]) not in TERMINAL_SOURCE_STATES
    ]
    checkpoints = connection.execute(
        """SELECT q.window_id,q.subject_id,q.request_variant,q.segment_start,
                  q.segment_end,q.updated_at,s.status segment_status,
                  s.updated_at segment_updated_at,s.error_code
           FROM yuqing_fetch_checkpoint q
           LEFT JOIN yuqing_fetch_segment_run s
             ON s.window_id=q.window_id
            AND s.subject_id=q.subject_id
            AND s.request_variant=q.request_variant
            AND s.segment_start=q.segment_start
            AND s.segment_end=q.segment_end
           WHERE q.window_id=?
           ORDER BY q.subject_id,q.request_variant,q.segment_start,q.segment_end""",
        (window_id,),
    ).fetchall()
    checkpoint_blockers = []
    terminal_counts: dict[str, int] = {}
    for row in checkpoints:
        status = str(row["segment_status"] or "missing")
        terminal_counts[status] = terminal_counts.get(status, 0) + 1
        if status not in TERMINAL_SEGMENT_STATES:
            checkpoint_blockers.append(
                "checkpoint:"
                f"{row['subject_id']}:{row['request_variant']}:"
                f"{row['segment_start']}:{status}"
            )
    running_segments = int(
        connection.execute(
            """SELECT COUNT(*) FROM yuqing_fetch_segment_run
               WHERE window_id=? AND status='running'""",
            (window_id,),
        ).fetchone()[0]
    )
    blockers = source_blockers + checkpoint_blockers
    if running_segments:
        blockers.append(f"running_segments:{running_segments}")
    if not source_rows:
        blockers.append("source_audit_absent")
    return {
        "eligible": not blockers,
        "checkpoint_count": len(checkpoints),
        "terminal_segment_counts": terminal_counts,
        "source_statuses": {
            str(row["source"]): str(row["status"]) for row in source_rows
        },
        "blockers": blockers,
    }


def _verify_window_aggregate_contract(
    connection: sqlite3.Connection,
    window_id: str,
) -> dict[str, int]:
    ledger = connection.execute(
        """SELECT raw_count,scored_count,aggregate_sha256
           FROM retail_window_ledger WHERE window_id=?""",
        (window_id,),
    ).fetchone()
    mapped = int(
        connection.execute(
            "SELECT COUNT(*) FROM senti_raw_window WHERE window_id=?",
            (window_id,),
        ).fetchone()[0]
    )
    totals = connection.execute(
        """SELECT COUNT(*) fact_rows,COALESCE(SUM(raw_count),0) raw_count,
                  COALESCE(SUM(scored_count),0) scored_count,
                  SUM(CASE WHEN aggregate_sha256 IS NULL OR aggregate_sha256=''
                           THEN 1 ELSE 0 END) missing_hashes
           FROM senti_retail_window WHERE window_id=?""",
        (window_id,),
    ).fetchone()
    if (
        not ledger
        or not str(ledger["aggregate_sha256"] or "")
        or mapped != int(ledger["raw_count"] or 0)
        or int(totals["raw_count"] or 0) != int(ledger["raw_count"] or 0)
        or int(totals["scored_count"] or 0) != int(ledger["scored_count"] or 0)
        or int(totals["missing_hashes"] or 0)
    ):
        raise RuntimeError(f"window permanent aggregate mismatch: {window_id}")
    return {
        "mapped_raw": mapped,
        "fact_rows": int(totals["fact_rows"] or 0),
        "raw_count": int(totals["raw_count"] or 0),
        "scored_count": int(totals["scored_count"] or 0),
    }


def _candidate_complete(
    connection: sqlite3.Connection,
    *,
    as_of: datetime,
    grace_days: int,
) -> list[dict[str, Any]]:
    if not schema_ready(connection):
        return []
    rows = connection.execute(
        """SELECT window_id,status,session_date,finished_at,window_end,
                  raw_purge_after,retention_state,aggregate_sha256
           FROM retail_window_ledger
           WHERE retention_state='sealed_complete'
             AND raw_purged_at IS NULL
           ORDER BY session_date,window_id""",
    ).fetchall()
    output = []
    for row in rows:
        window_id = str(row["window_id"])
        effective_purge_after = _effective_purge_after(row, grace_days)
        if effective_purge_after is None:
            continue
        if effective_purge_after > as_of:
            continue
        blocked = retail_windows_v2.window_has_active_work(connection, window_id)
        output.append(
            {
                **dict(row),
                "effective_raw_purge_after": effective_purge_after.isoformat(
                    timespec="seconds"
                ),
                **_window_counts(connection, window_id),
                "eligible": not blocked,
                "excluded_reason": "active_work" if blocked else None,
            }
        )
    return output


def _candidate_incomplete(
    connection: sqlite3.Connection,
    *,
    as_of: datetime,
    grace_days: int,
) -> list[dict[str, Any]]:
    if not schema_ready(connection):
        return []
    rows = connection.execute(
        """SELECT window_id,status,session_date,finished_at,window_end,
                  raw_purge_after,retention_state,aggregate_sha256
           FROM retail_window_ledger
           WHERE retention_state='sealed_incomplete'
             AND raw_purged_at IS NULL
           ORDER BY session_date,window_id""",
    ).fetchall()
    output = []
    for row in rows:
        window_id = str(row["window_id"])
        effective_purge_after = _effective_purge_after(row, grace_days)
        if effective_purge_after is None:
            continue
        if effective_purge_after > as_of:
            continue
        blocked = retail_windows_v2.window_has_active_work(connection, window_id)
        output.append(
            {
                **dict(row),
                "effective_raw_purge_after": effective_purge_after.isoformat(
                    timespec="seconds"
                ),
                **_window_counts(connection, window_id),
                "eligible": not blocked,
                "excluded_reason": "active_work" if blocked else None,
            }
        )
    return output


def _candidate_live_incomplete_for_seal(
    connection: sqlite3.Connection,
    *,
    as_of: datetime,
    grace_days: int,
) -> list[dict[str, Any]]:
    cutoff = (as_of - timedelta(days=grace_days)).isoformat(timespec="seconds")
    rows = connection.execute(
        """SELECT window_id,status,session_date,window_end,retention_state,
                  aggregate_sha256
           FROM retail_window_ledger
           WHERE status IN ('partial','failed')
             AND retention_state='live'
             AND raw_purged_at IS NULL
             AND window_end<=?
           ORDER BY window_end,window_id""",
        (cutoff,),
    ).fetchall()
    output = []
    for row in rows:
        window_id = str(row["window_id"])
        terminal = _terminal_checkpoint_evidence(connection, window_id)
        output.append(
            {
                **dict(row),
                **_window_counts(connection, window_id),
                "terminal_checkpoint_evidence": terminal,
                "eligible": bool(terminal["eligible"]),
                "excluded_reason": (
                    None
                    if terminal["eligible"]
                    else "terminal_evidence:" + ",".join(terminal["blockers"])
                ),
            }
        )
    return output


def _legacy_coverage(
    connection: sqlite3.Connection,
    session_date: str,
) -> tuple[bool, dict[str, int]]:
    counts = {
        "sentiment_daily": int(
            connection.execute(
                "SELECT COUNT(*) FROM senti_retail_daily WHERE trade_date=?",
                (session_date,),
            ).fetchone()[0]
        ),
        "volume_daily": int(
            connection.execute(
                "SELECT COUNT(*) FROM heat_volume_daily WHERE trade_date=?",
                (session_date,),
            ).fetchone()[0]
        ),
    }
    return all(counts.values()), counts


def _legacy_aggregate_sha256(
    connection: sqlite3.Connection,
    session_date: str,
) -> str:
    payload: dict[str, list[list[Any]]] = {}
    for table in ("senti_retail_daily", "heat_volume_daily"):
        columns = [
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({table})")
        ]
        rows = connection.execute(
            f"""SELECT * FROM {table}
                WHERE trade_date=?
                ORDER BY company_id,id""",
            (session_date,),
        ).fetchall()
        payload[table] = [
            [row[column] for column in columns]
            for row in rows
        ]
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


def _candidate_legacy(
    connection: sqlite3.Connection,
    *,
    cutover_date: str,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """SELECT window_id,status,session_date
           FROM retail_window_ledger
           WHERE session_date<? AND status='pending'
           ORDER BY session_date,window_id""",
        (cutover_date,),
    ).fetchall()
    output = []
    date_hashes: dict[str, str] = {}
    for row in rows:
        window_id = str(row["window_id"])
        feed_rows = int(
            connection.execute(
                "SELECT COUNT(*) FROM yuqing_feed_raw WHERE window_id=?",
                (window_id,),
            ).fetchone()[0]
        )
        source_rows = int(
            connection.execute(
                "SELECT COUNT(*) FROM retail_window_source_run WHERE window_id=?",
                (window_id,),
            ).fetchone()[0]
        )
        checkpoint_rows = int(
            connection.execute(
                "SELECT COUNT(*) FROM yuqing_fetch_checkpoint WHERE window_id=?",
                (window_id,),
            ).fetchone()[0]
        )
        covered, coverage = _legacy_coverage(
            connection,
            str(row["session_date"]),
        )
        session_date = str(row["session_date"])
        if covered and session_date not in date_hashes:
            date_hashes[session_date] = _legacy_aggregate_sha256(
                connection,
                session_date,
            )
        blocked = bool(feed_rows or source_rows or checkpoint_rows or not covered)
        reason = None
        if feed_rows or source_rows or checkpoint_rows:
            reason = "contains_v2_runtime_state"
        elif not covered:
            reason = "legacy_aggregate_gap"
        output.append(
            {
                **dict(row),
                **_window_counts(connection, window_id),
                "legacy_coverage": coverage,
                "legacy_aggregate_sha256": date_hashes.get(session_date),
                "eligible": not blocked,
                "excluded_reason": reason,
            }
        )
    return output


def _candidate_legacy_weekend_orphans(
    connection: sqlite3.Connection,
    *,
    cutover_date: str,
) -> list[dict[str, Any]]:
    row = connection.execute(
        """SELECT COUNT(*) raw_rows
           FROM senti_raw r
           WHERE r.source_layer='retail'
             AND r.publish_time<?
             AND strftime('%w',substr(r.publish_time,1,10)) IN ('0','6')
             AND NOT EXISTS(
               SELECT 1 FROM senti_raw_window rw WHERE rw.raw_id=r.id
             )""",
        (cutover_date,),
    ).fetchone()
    raw_rows = int(row["raw_rows"] or 0)
    return [
        {
            "window_id": f"legacy_weekend_unmapped_before:{cutover_date}",
            "status": "legacy_unmapped",
            "session_date": None,
            "raw_rows": raw_rows,
            "mapping_rows": 0,
            "feed_rows": 0,
            "eligible": bool(raw_rows),
            "excluded_reason": None if raw_rows else "empty",
        }
    ]


def _candidate_unmapped_raw(
    connection: sqlite3.Connection,
    *,
    cutoff: datetime,
) -> list[dict[str, Any]]:
    cutoff_text = cutoff.isoformat(timespec="seconds")
    raw_columns = _columns(connection, "senti_raw")
    fetched_expression = "r.fetched_at" if "fetched_at" in raw_columns else "r.publish_time"
    row = connection.execute(
        f"""SELECT COUNT(*) raw_rows,
                  COUNT(DISTINCT substr(COALESCE(r.publish_time,{fetched_expression}),1,10)
                        || ':' || company_id || ':' || source_layer || ':' || platform)
                    aggregate_groups
           FROM senti_raw r
           WHERE {fetched_expression}<=?
             AND NOT EXISTS(
               SELECT 1 FROM senti_raw_window rw WHERE rw.raw_id=r.id
             )""",
        (cutoff_text,),
    ).fetchone()
    raw_rows = int(row["raw_rows"] or 0)
    if not raw_rows:
        return []
    aggregate_sha256 = None
    if _columns(connection, "senti_unmapped_daily"):
        aggregate_sha256 = _unmapped_bundle_sha256(connection)
    return [
        {
            "window_id": f"unmapped_raw_before:{cutoff_text}",
            "status": "unmapped_legacy",
            "session_date": None,
            "cutoff": cutoff_text,
            "raw_rows": raw_rows,
            "mapping_rows": 0,
            "feed_rows": 0,
            "aggregate_groups": int(row["aggregate_groups"] or 0),
            "aggregate_sha256": aggregate_sha256,
            "eligible": True,
            "excluded_reason": None,
        }
    ]


def _legacy_pending_orphan_rows(
    connection: sqlite3.Connection,
    *,
    cutoff: datetime,
) -> list[sqlite3.Row]:
    raw_columns = _columns(connection, "senti_raw")
    fetched_expression = "r.fetched_at" if "fetched_at" in raw_columns else "r.publish_time"
    cutoff_text = cutoff.isoformat(timespec="seconds")
    return connection.execute(
        f"""SELECT l.window_id,l.window_end,l.attempts,l.raw_count,l.scored_count,
                  COUNT(rw.raw_id) mapping_rows
           FROM retail_window_ledger l
           JOIN senti_raw_window rw ON rw.window_id=l.window_id
           JOIN senti_raw r ON r.id=rw.raw_id
           WHERE l.status='pending'
             AND l.retention_state='live'
             AND l.raw_purged_at IS NULL
             AND l.attempts=0
             AND l.window_end<=?
             AND NOT EXISTS(
               SELECT 1 FROM retail_window_source_run s WHERE s.window_id=l.window_id
             )
             AND NOT EXISTS(
               SELECT 1 FROM yuqing_fetch_segment_run s WHERE s.window_id=l.window_id
             )
             AND NOT EXISTS(
               SELECT 1 FROM yuqing_fetch_checkpoint c WHERE c.window_id=l.window_id
             )
             AND NOT EXISTS(
               SELECT 1 FROM yuqing_feed_raw f WHERE f.window_id=l.window_id
             )
             AND NOT EXISTS(
               SELECT 1
               FROM senti_raw_window rw2
               JOIN senti_raw r2 ON r2.id=rw2.raw_id
               JOIN senti_retail_daily d
                 ON d.company_id=r2.company_id AND d.trade_date=l.session_date
               WHERE rw2.window_id=l.window_id
             )
             AND NOT EXISTS(
               SELECT 1
               FROM senti_raw_window rw2
               JOIN senti_raw r2 ON r2.id=rw2.raw_id
               JOIN heat_volume_daily d
                 ON d.company_id=r2.company_id AND d.trade_date=l.session_date
               WHERE rw2.window_id=l.window_id
             )
           GROUP BY l.window_id,l.window_end,l.attempts,l.raw_count,l.scored_count
           HAVING SUM(CASE WHEN {fetched_expression}>? THEN 1 ELSE 0 END)=0
           ORDER BY l.window_end,l.window_id""",
        (cutoff_text, cutoff_text),
    ).fetchall()


def _candidate_legacy_pending_orphans(
    connection: sqlite3.Connection,
    *,
    cutoff: datetime,
) -> list[dict[str, Any]]:
    return [
        {
            "window_id": str(row["window_id"]),
            "status": "pending",
            "session_date": None,
            "window_end": str(row["window_end"]),
            "raw_rows": int(row["mapping_rows"]),
            "mapping_rows": int(row["mapping_rows"]),
            "feed_rows": 0,
            "eligible": True,
            "excluded_reason": None,
            "reason": "zero_attempt_legacy_mapping_without_run_audit",
        }
        for row in _legacy_pending_orphan_rows(
            connection,
            cutoff=cutoff,
        )
    ]


def _unmapped_bundle_sha256(connection: sqlite3.Connection) -> str:
    if not _columns(connection, "senti_unmapped_daily"):
        return ""
    rows = connection.execute(
        """SELECT trade_date,company_id,source_layer,platform,aggregate_sha256
           FROM senti_unmapped_daily
           ORDER BY trade_date,company_id,source_layer,platform"""
    ).fetchall()
    return hashlib.sha256(
        _json([list(row) for row in rows]).encode("utf-8")
    ).hexdigest()


def _freeze_unmapped_raw(
    connection: sqlite3.Connection,
    *,
    cutoff: datetime,
    computed_at: str,
) -> dict[str, Any]:
    cutoff_text = cutoff.isoformat(timespec="seconds")
    raw_columns = _columns(connection, "senti_raw")
    fetched_expression = "r.fetched_at" if "fetched_at" in raw_columns else "r.publish_time"
    heat_expression = "r.heat_value" if "heat_value" in raw_columns else "0"
    read_expression = "r.read_count" if "read_count" in raw_columns else "0"
    reply_expression = "r.reply_count" if "reply_count" in raw_columns else "0"
    rows = connection.execute(
        f"""SELECT r.company_id,COALESCE(d.canonical_company_id,r.company_id) canonical_company_id,
                  r.ticker,r.source_layer,r.platform,r.attitude,
                  {heat_expression} heat_value,{read_expression} read_count,
                  {reply_expression} reply_count,
                  substr(COALESCE(r.publish_time,{fetched_expression}),1,10) trade_date
           FROM senti_raw r
           LEFT JOIN company_id_redirect d ON d.old_company_id=r.company_id
           WHERE {fetched_expression}<=?
             AND NOT EXISTS(
               SELECT 1 FROM senti_raw_window rw WHERE rw.raw_id=r.id
             )
           ORDER BY trade_date,canonical_company_id,r.source_layer,r.platform,r.id""",
        (cutoff_text,),
    ).fetchall()
    groups: dict[tuple[str, int, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (
            str(row["trade_date"]),
            int(row["canonical_company_id"]),
            str(row["source_layer"]),
            str(row["platform"]),
        )
        item = groups.setdefault(
            key,
            {
                "tickers": [],
                "raw_count": 0,
                "scored_count": 0,
                "pos": 0,
                "neg": 0,
                "neu": 0,
                "weighted_pos": 0.0,
                "weighted_neg": 0.0,
                "weighted_neu": 0.0,
                "heat_value_sum": 0.0,
                "read_count_sum": 0,
                "reply_count_sum": 0,
            },
        )
        item["tickers"].append(str(row["ticker"] or ""))
        item["raw_count"] += 1
        heat = max(float(row["heat_value"] or 0.0), 1.0)
        item["heat_value_sum"] += float(row["heat_value"] or 0.0)
        item["read_count_sum"] += int(row["read_count"] or 0)
        item["reply_count_sum"] += int(row["reply_count"] or 0)
        attitude = row["attitude"]
        if attitude not in (1, 2, 3):
            continue
        item["scored_count"] += 1
        label = "pos" if attitude == 1 else ("neg" if attitude == 2 else "neu")
        item[label] += 1
        item[f"weighted_{label}"] += heat * senti3.retail_weight(key[3])

    for key, delta in groups.items():
        trade_date, company_id, source_layer, platform = key
        prior = connection.execute(
            """SELECT * FROM senti_unmapped_daily
               WHERE trade_date=? AND company_id=? AND source_layer=? AND platform=?""",
            key,
        ).fetchone()
        numeric = (
            "raw_count",
            "scored_count",
            "pos",
            "neg",
            "neu",
            "weighted_pos",
            "weighted_neg",
            "weighted_neu",
            "heat_value_sum",
            "read_count_sum",
            "reply_count_sum",
        )
        merged = {
            name: (float(prior[name]) if prior and name.startswith(("weighted_", "heat_")) else int(prior[name]))
            + delta[name]
            if prior
            else delta[name]
            for name in numeric
        }
        tickers = [value for value in delta["tickers"] if value]
        ticker = min(tickers) if tickers else (str(prior["ticker"] or "") if prior else "")
        payload = {
            "trade_date": trade_date,
            "company_id": company_id,
            "ticker": ticker or None,
            "source_layer": source_layer,
            "platform": platform,
            **merged,
            "aggregation_version": UNMAPPED_AGGREGATION_VERSION,
        }
        aggregate_sha256 = hashlib.sha256(
            _json(payload).encode("utf-8")
        ).hexdigest()
        connection.execute(
            """INSERT INTO senti_unmapped_daily(
                 trade_date,company_id,ticker,source_layer,platform,raw_count,
                 scored_count,pos,neg,neu,weighted_pos,weighted_neg,weighted_neu,
                 heat_value_sum,read_count_sum,reply_count_sum,aggregation_version,
                 aggregate_sha256,computed_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(trade_date,company_id,source_layer,platform) DO UPDATE SET
                 ticker=excluded.ticker,raw_count=excluded.raw_count,
                 scored_count=excluded.scored_count,pos=excluded.pos,neg=excluded.neg,
                 neu=excluded.neu,weighted_pos=excluded.weighted_pos,
                 weighted_neg=excluded.weighted_neg,weighted_neu=excluded.weighted_neu,
                 heat_value_sum=excluded.heat_value_sum,
                 read_count_sum=excluded.read_count_sum,
                 reply_count_sum=excluded.reply_count_sum,
                 aggregation_version=excluded.aggregation_version,
                 aggregate_sha256=excluded.aggregate_sha256,computed_at=excluded.computed_at""",
            (
                trade_date,
                company_id,
                ticker or None,
                source_layer,
                platform,
                *(merged[name] for name in numeric),
                UNMAPPED_AGGREGATION_VERSION,
                aggregate_sha256,
                computed_at,
            ),
        )
    return {
        "cutoff": cutoff_text,
        "raw_rows": len(rows),
        "aggregate_groups": len(groups),
        "aggregate_sha256": _unmapped_bundle_sha256(connection),
    }


def _retire_legacy_pending_orphans(
    connection: sqlite3.Connection,
    *,
    cutoff: datetime,
    retired_at: str,
) -> list[dict[str, Any]]:
    """Detach inert legacy mappings so their numeric facts can be frozen.

    These are not failed production runs: they have zero attempts and no
    source, segment, checkpoint or feed audit.  Their status remains
    ``pending`` for historical truth; only their raw lifecycle is closed as an
    explicitly incomplete legacy orphan.
    """
    cutoff_text = cutoff.isoformat(timespec="seconds")
    raw_columns = _columns(connection, "senti_raw")
    fetched_expression = "r.fetched_at" if "fetched_at" in raw_columns else "r.publish_time"
    candidates = _legacy_pending_orphan_rows(connection, cutoff=cutoff)
    retired: list[dict[str, Any]] = []
    for row in candidates:
        window_id = str(row["window_id"])
        raw_rows = connection.execute(
            f"""SELECT r.id,r.company_id,r.ticker,r.source_layer,r.platform,
                       r.attitude,r.heat_value,r.publish_time,{fetched_expression} fetched_at
                FROM senti_raw_window rw
                JOIN senti_raw r ON r.id=rw.raw_id
                WHERE rw.window_id=?
                ORDER BY r.id""",
            (window_id,),
        ).fetchall()
        if not raw_rows:
            continue
        if any(str(item["fetched_at"] or "") > cutoff_text for item in raw_rows):
            continue
        if int(row["raw_count"] or 0) or int(row["scored_count"] or 0):
            raise RuntimeError(
                f"legacy pending orphan has ledger facts and needs manual review: {window_id}"
            )
        payload = [
            {
                "id": int(item["id"]),
                "company_id": int(item["company_id"]),
                "ticker": str(item["ticker"] or ""),
                "source_layer": str(item["source_layer"]),
                "platform": str(item["platform"]),
                "attitude": item["attitude"],
                "heat_value": float(item["heat_value"] or 0.0),
                "publish_time": str(item["publish_time"] or ""),
                "fetched_at": str(item["fetched_at"] or ""),
            }
            for item in raw_rows
        ]
        aggregate_sha256 = hashlib.sha256(
            _json(payload).encode("utf-8")
        ).hexdigest()
        mapping_rows = int(
            connection.execute(
                "DELETE FROM senti_raw_window WHERE window_id=?",
                (window_id,),
            ).rowcount
        )
        purge_after = (
            datetime.fromisoformat(str(row["window_end"]))
            + timedelta(days=retention_policy.RAW_RETENTION_DAYS)
        ).isoformat(timespec="seconds")
        connection.execute(
            """UPDATE retail_window_ledger SET
                 retention_state='purged_incomplete',sealed_at=?,
                 seal_reason='legacy_pending_orphan_numeric_frozen',
                 raw_purge_after=?,raw_purged_at=?,aggregate_sha256=?
               WHERE window_id=?""",
            (
                retired_at,
                purge_after,
                retired_at,
                aggregate_sha256,
                window_id,
            ),
        )
        retired.append(
            {
                "window_id": window_id,
                "status": "pending",
                "retention_state": "purged_incomplete",
                "raw_rows": len(raw_rows),
                "mapping_rows": mapping_rows,
                "aggregate_sha256": aggregate_sha256,
                "reason": "zero_attempt_legacy_mapping_without_run_audit",
            }
        )
    return retired


def _delete_unmapped_raw(
    connection: sqlite3.Connection,
    *,
    cutoff: str,
) -> dict[str, Any]:
    raw_columns = _columns(connection, "senti_raw")
    fetched_expression = "r.fetched_at" if "fetched_at" in raw_columns else "r.publish_time"
    delete_fetched_expression = (
        "senti_raw.fetched_at" if "fetched_at" in raw_columns else "senti_raw.publish_time"
    )
    before = int(
        connection.execute(
            f"""SELECT COUNT(*) FROM senti_raw r
               WHERE {fetched_expression}<=?
                 AND NOT EXISTS(
                   SELECT 1 FROM senti_raw_window rw WHERE rw.raw_id=r.id
                 )""",
            (cutoff,),
        ).fetchone()[0]
    )
    bundle = _unmapped_bundle_sha256(connection)
    if before and not bundle:
        raise RuntimeError("unmapped raw aggregate was not frozen")
    connection.execute(
        f"""DELETE FROM senti_raw
           WHERE {delete_fetched_expression}<=?
             AND NOT EXISTS(
               SELECT 1 FROM senti_raw_window rw WHERE rw.raw_id=senti_raw.id
             )""",
        (cutoff,),
    )
    after = int(
        connection.execute(
            f"""SELECT COUNT(*) FROM senti_raw r
               WHERE {fetched_expression}<=?
                 AND NOT EXISTS(
                   SELECT 1 FROM senti_raw_window rw WHERE rw.raw_id=r.id
                 )""",
            (cutoff,),
        ).fetchone()[0]
    )
    if after or bundle != _unmapped_bundle_sha256(connection):
        raise RuntimeError("unmapped raw purge verification failed")
    return {
        "raw_rows": before,
        "mapping_rows": 0,
        "feed_rows": 0,
        "aggregate_sha256": bundle,
    }


def _build_plan_for_connection(
    connection: sqlite3.Connection,
    db_path: Path,
    *,
    as_of: datetime,
    grace_days: int,
    include_legacy: bool,
    include_incomplete: bool,
    legacy_cutover: str,
) -> dict[str, Any]:
    ready = schema_ready(connection)
    complete = _candidate_complete(
        connection,
        as_of=as_of,
        grace_days=grace_days,
    )
    incomplete = (
        _candidate_incomplete(
            connection,
            as_of=as_of,
            grace_days=grace_days,
        )
        if include_incomplete else []
    )
    seal_incomplete_candidates = (
        _candidate_live_incomplete_for_seal(
            connection,
            as_of=as_of,
            grace_days=grace_days,
        )
        if include_incomplete else []
    )
    legacy = (
        _candidate_legacy(connection, cutover_date=legacy_cutover)
        if include_legacy else []
    )
    unmapped = _candidate_unmapped_raw(
        connection,
        cutoff=as_of - timedelta(days=retention_policy.RAW_RETENTION_DAYS),
    )
    pending_orphans = (
        _candidate_legacy_pending_orphans(
            connection,
            cutoff=as_of - timedelta(days=retention_policy.RAW_RETENTION_DAYS),
        )
        if include_incomplete else []
    )
    # The former weekend-only orphan rule is subsumed by the three-day
    # numeric-freeze contract for every source layer and platform.
    legacy_orphans: list[dict[str, Any]] = []
    averages = {
        table: _average_payload(connection, table)
        for table in ("senti_raw", "senti_raw_window", "yuqing_feed_raw")
    }
    all_candidates = (
        complete
        + incomplete
        + seal_incomplete_candidates
        + pending_orphans
        + legacy
        + legacy_orphans
        + unmapped
    )
    for row in all_candidates:
        row["estimated_bytes"] = int(
            row["raw_rows"] * averages["senti_raw"]
            + row["mapping_rows"] * averages["senti_raw_window"]
            + row["feed_rows"] * averages["yuqing_feed_raw"]
        )
    return {
        "schema_version": "industry_demo.sentiment_retention_plan.v2",
        "db_path": str(db_path.resolve()),
        "db_bytes": db_path.stat().st_size,
        "as_of": as_of.isoformat(timespec="seconds"),
        "grace_days": grace_days,
        "legacy_cutover": legacy_cutover,
        "schema_ready": ready,
        "table_counts": {
            table: _table_count(connection, table)
            for table in (
                "senti_raw",
                "senti_raw_window",
                "yuqing_feed_raw",
                "senti_retail_window",
                "senti_retail_trading_daily",
                "senti_unmapped_daily",
            )
            if _columns(connection, table)
        },
        "complete": complete,
        "incomplete": incomplete,
        "seal_incomplete_candidates": seal_incomplete_candidates,
        "legacy_pending_orphans": pending_orphans,
        "legacy": legacy,
        "legacy_orphans": legacy_orphans,
        "unmapped": unmapped,
        "eligible_windows": sum(
            1
            for row in all_candidates
            if row["eligible"]
        ),
        "estimated_reclaim_bytes": sum(
            int(row["estimated_bytes"])
            for row in all_candidates
            if row["eligible"]
        ),
    }


def build_plan(
    db_path: Path,
    *,
    as_of: datetime,
    grace_days: int,
    include_legacy: bool,
    include_incomplete: bool,
    legacy_cutover: str,
) -> dict[str, Any]:
    with closing(_connect(db_path, read_only=True)) as connection:
        return _build_plan_for_connection(
            connection,
            db_path,
            as_of=as_of,
            grace_days=grace_days,
            include_legacy=include_legacy,
            include_incomplete=include_incomplete,
            legacy_cutover=legacy_cutover,
        )


def migrate_and_seal(
    connection: sqlite3.Connection,
    *,
    grace_days: int,
    now: datetime,
    include_incomplete: bool = False,
    incomplete_age_days: int = DEFAULT_INCOMPLETE_AGE_DAYS,
) -> dict[str, Any]:
    retail_windows_v2.ensure_schema(connection)
    complete_rows = connection.execute(
        """SELECT window_id,session_date
           FROM retail_window_ledger
           WHERE status='complete' AND raw_purged_at IS NULL
           ORDER BY session_date,window_id"""
    ).fetchall()
    migrated = []
    session_dates: set[str] = set()
    for row in complete_rows:
        window_id = str(row["window_id"])
        if retail_windows_v2.window_has_active_work(connection, window_id):
            continue
        mapped = int(
            connection.execute(
                "SELECT COUNT(*) FROM senti_raw_window WHERE window_id=?",
                (window_id,),
            ).fetchone()[0]
        )
        ledger_raw = int(
            connection.execute(
                "SELECT raw_count FROM retail_window_ledger WHERE window_id=?",
                (window_id,),
            ).fetchone()[0]
        )
        fact_rows = int(
            connection.execute(
                "SELECT COUNT(*) FROM senti_retail_window WHERE window_id=?",
                (window_id,),
            ).fetchone()[0]
        )
        if not mapped and (ledger_raw or fact_rows):
            continue
        sealed = retail_windows_v2.seal_window(
                connection,
                window_id,
                grace_days=grace_days,
                sealed_at=now.isoformat(timespec="seconds"),
            )
        sealed["aggregate_contract"] = _verify_window_aggregate_contract(
            connection, window_id
        )
        migrated.append(sealed)
        session_dates.add(str(row["session_date"]))
    for session_date in sorted(session_dates):
        retail_windows_v2.aggregate_trading_day(
            connection,
            session_date,
            computed_at=now.isoformat(timespec="seconds"),
        )
    incomplete = []
    if include_incomplete:
        incomplete_before = (now - timedelta(days=incomplete_age_days)).isoformat(
            timespec="seconds"
        )
        rows = connection.execute(
            """SELECT window_id,scheduled_for,window_end
               FROM retail_window_ledger
               WHERE status IN ('partial','failed')
                 AND window_end<=?
                 AND retention_state='live'
                 AND raw_purged_at IS NULL
               ORDER BY window_end,window_id""",
            (incomplete_before,),
        ).fetchall()
        for row in rows:
            window_id = str(row["window_id"])
            terminal = _terminal_checkpoint_evidence(connection, window_id)
            if not terminal["eligible"]:
                continue
            mapped = int(
                connection.execute(
                    "SELECT COUNT(*) FROM senti_raw_window WHERE window_id=?",
                    (window_id,),
                ).fetchone()[0]
            )
            facts = int(
                connection.execute(
                    "SELECT COUNT(*) FROM senti_retail_window WHERE window_id=?",
                    (window_id,),
                ).fetchone()[0]
            )
            if not mapped and facts:
                continue
            retired_checkpoints = int(
                connection.execute(
                    "DELETE FROM yuqing_fetch_checkpoint WHERE window_id=?",
                    (window_id,),
                ).rowcount
            )
            sealed = retail_windows_v2.seal_window(
                connection,
                window_id,
                grace_days=grace_days,
                allow_incomplete=True,
                sealed_at=now.isoformat(timespec="seconds"),
            )
            sealed["aggregate_contract"] = _verify_window_aggregate_contract(
                connection, window_id
            )
            sealed["terminal_checkpoint_evidence"] = terminal
            sealed["retired_checkpoints"] = retired_checkpoints
            incomplete.append(sealed)
    legacy_pending_orphans = (
        _retire_legacy_pending_orphans(
            connection,
            cutoff=now - timedelta(days=retention_policy.RAW_RETENTION_DAYS),
            retired_at=now.isoformat(timespec="seconds"),
        )
        if include_incomplete else []
    )
    unmapped = _freeze_unmapped_raw(
        connection,
        cutoff=now - timedelta(days=retention_policy.RAW_RETENTION_DAYS),
        computed_at=now.isoformat(timespec="seconds"),
    )
    return {
        "migrated_windows": len(migrated),
        "sealed_incomplete_windows": len(incomplete),
        "session_dates": sorted(session_dates),
        "windows": migrated,
        "incomplete_windows": incomplete,
        "legacy_pending_orphans": legacy_pending_orphans,
        "unmapped": unmapped,
    }


def _delete_complete_window(
    connection: sqlite3.Connection,
    window_id: str,
    *,
    purged_at: str,
) -> dict[str, Any]:
    if retail_windows_v2.window_has_active_work(connection, window_id):
        raise RuntimeError(f"活动 window 不可清理: {window_id}")
    ledger = connection.execute(
        """SELECT status,retention_state,aggregate_sha256
           FROM retail_window_ledger WHERE window_id=?""",
        (window_id,),
    ).fetchone()
    if (
        not ledger
        or str(ledger["status"]) != "complete"
        or str(ledger["retention_state"]) != "sealed_complete"
        or not str(ledger["aggregate_sha256"] or "")
    ):
        raise RuntimeError(f"window 未达到完整封存门槛: {window_id}")
    counts = _window_counts(connection, window_id)
    aggregate_sha256 = str(ledger["aggregate_sha256"])
    connection.execute(
        "DELETE FROM yuqing_feed_raw WHERE window_id=?",
        (window_id,),
    )
    connection.execute(
        """DELETE FROM senti_raw
           WHERE id IN (
             SELECT raw_id FROM senti_raw_window WHERE window_id=?
           )""",
        (window_id,),
    )
    connection.execute(
        "DELETE FROM senti_raw_window WHERE window_id=?",
        (window_id,),
    )
    connection.execute(
        """UPDATE retail_window_ledger
           SET retention_state='purged',raw_purged_at=?
           WHERE window_id=?""",
        (purged_at, window_id),
    )
    after_hash = connection.execute(
        "SELECT aggregate_sha256 FROM retail_window_ledger WHERE window_id=?",
        (window_id,),
    ).fetchone()[0]
    if str(after_hash) != aggregate_sha256:
        raise RuntimeError(f"window 聚合哈希在清理后改变: {window_id}")
    return {**counts, "aggregate_sha256": aggregate_sha256}


def _delete_incomplete_window(
    connection: sqlite3.Connection,
    window_id: str,
    *,
    purged_at: str,
) -> dict[str, Any]:
    if retail_windows_v2.window_has_active_work(connection, window_id):
        raise RuntimeError(f"活动 incomplete window 不可清理: {window_id}")
    ledger = connection.execute(
        """SELECT status,retention_state,aggregate_sha256
           FROM retail_window_ledger WHERE window_id=?""",
        (window_id,),
    ).fetchone()
    if (
        not ledger
        or str(ledger["status"]) not in {"partial", "failed"}
        or str(ledger["retention_state"]) != "sealed_incomplete"
        or not str(ledger["aggregate_sha256"] or "")
    ):
        raise RuntimeError(f"window 未达到不完整封存门槛: {window_id}")
    counts = _window_counts(connection, window_id)
    aggregate_sha256 = str(ledger["aggregate_sha256"])
    connection.execute(
        "DELETE FROM yuqing_feed_raw WHERE window_id=?",
        (window_id,),
    )
    connection.execute(
        """DELETE FROM senti_raw
           WHERE id IN (
             SELECT raw_id FROM senti_raw_window WHERE window_id=?
           )""",
        (window_id,),
    )
    connection.execute(
        "DELETE FROM senti_raw_window WHERE window_id=?",
        (window_id,),
    )
    connection.execute(
        """UPDATE retail_window_ledger
           SET retention_state='purged_incomplete',raw_purged_at=?
           WHERE window_id=?""",
        (purged_at, window_id),
    )
    return {**counts, "aggregate_sha256": aggregate_sha256}


def _delete_legacy_window(
    connection: sqlite3.Connection,
    window_id: str,
) -> dict[str, Any]:
    row = connection.execute(
        """SELECT status,session_date FROM retail_window_ledger
           WHERE window_id=?""",
        (window_id,),
    ).fetchone()
    if not row or str(row["status"]) != "pending":
        raise RuntimeError(f"legacy window 状态已改变: {window_id}")
    covered, coverage = _legacy_coverage(
        connection,
        str(row["session_date"]),
    )
    if not covered:
        raise RuntimeError(f"legacy aggregate 不完整: {window_id} {coverage}")
    aggregate_sha256 = _legacy_aggregate_sha256(
        connection,
        str(row["session_date"]),
    )
    if retail_windows_v2.window_has_active_work(connection, window_id):
        raise RuntimeError(f"legacy window 存在活动状态: {window_id}")
    if connection.execute(
        "SELECT COUNT(*) FROM yuqing_feed_raw WHERE window_id=?",
        (window_id,),
    ).fetchone()[0]:
        raise RuntimeError(f"legacy window 含 V2 feed: {window_id}")
    counts = _window_counts(connection, window_id)
    connection.execute(
        """DELETE FROM senti_raw
           WHERE id IN (
             SELECT raw_id FROM senti_raw_window WHERE window_id=?
           )""",
        (window_id,),
    )
    connection.execute(
        "DELETE FROM senti_raw_window WHERE window_id=?",
        (window_id,),
    )
    connection.execute(
        "DELETE FROM retail_window_ledger WHERE window_id=?",
        (window_id,),
    )
    after_sha256 = _legacy_aggregate_sha256(
        connection,
        str(row["session_date"]),
    )
    if after_sha256 != aggregate_sha256:
        raise RuntimeError(f"legacy aggregate 在清理后改变: {window_id}")
    return {**counts, "aggregate_sha256": aggregate_sha256}


def _delete_legacy_weekend_orphans(
    connection: sqlite3.Connection,
    *,
    cutover_date: str,
) -> dict[str, Any]:
    before = int(
        connection.execute(
            """SELECT COUNT(*) FROM senti_raw r
               WHERE r.source_layer='retail'
                 AND r.publish_time<?
                 AND strftime('%w',substr(r.publish_time,1,10)) IN ('0','6')
                 AND NOT EXISTS(
                   SELECT 1 FROM senti_raw_window rw WHERE rw.raw_id=r.id
                 )""",
            (cutover_date,),
        ).fetchone()[0]
    )
    connection.execute(
        """DELETE FROM senti_raw
           WHERE source_layer='retail'
             AND publish_time<?
             AND strftime('%w',substr(publish_time,1,10)) IN ('0','6')
             AND NOT EXISTS(
               SELECT 1 FROM senti_raw_window rw WHERE rw.raw_id=senti_raw.id
             )""",
        (cutover_date,),
    )
    after = int(
        connection.execute(
            """SELECT COUNT(*) FROM senti_raw r
               WHERE r.source_layer='retail'
                 AND r.publish_time<?
                 AND strftime('%w',substr(r.publish_time,1,10)) IN ('0','6')
                 AND NOT EXISTS(
                   SELECT 1 FROM senti_raw_window rw WHERE rw.raw_id=r.id
                 )""",
            (cutover_date,),
        ).fetchone()[0]
    )
    if after:
        raise RuntimeError(f"legacy weekend orphan 清理不完整: {after}")
    return {
        "raw_rows": before,
        "mapping_rows": 0,
        "feed_rows": 0,
        "aggregate_sha256": None,
    }


def _retention_mutation_operation_id(as_of: datetime, run_id: str) -> str:
    """Keep retry identity stable while retaining a unique audit attempt id."""

    root_operation_id = os.environ.get("HONGHU_OPERATION_ID", "").strip()
    if not root_operation_id:
        return run_id
    from tools.data_platform.run_domain_operation import derived_operation_id

    return derived_operation_id(f"retention:{as_of.date().isoformat()}")


def apply_retention(
    db_path: Path,
    *,
    as_of: datetime,
    grace_days: int,
    include_legacy: bool,
    include_incomplete: bool,
    incomplete_age_days: int,
    legacy_cutover: str,
) -> dict[str, Any]:
    run_id = f"retention-{as_of.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
    # ``run_id`` identifies this audit attempt and may be unique, but the
    # PostgreSQL mutation identity must remain stable when Task Scheduler
    # retries the same business window.  Reusing a random run id here would
    # turn an uncertain response into a second logical mutation.
    mutation_operation_id = _retention_mutation_operation_id(as_of, run_id)
    started_at = _now().isoformat(timespec="seconds")
    with closing(_connect(db_path, operation_id=mutation_operation_id)) as connection:
        # The PostgreSQL-authoritative compatibility connection is an in-memory
        # projection whose lifetime already defines one atomic mutation batch.
        # Starting a second SQLite transaction inside that projection fails and
        # would prevent the unique VM retention runner from making progress.
        # The retired S0/S1 SQLite path keeps its original early write lock.
        if connection.__class__.__module__ == "sqlite3":
            connection.execute("BEGIN IMMEDIATE")
        try:
            migration = migrate_and_seal(
                connection,
                grace_days=grace_days,
                now=as_of,
                include_incomplete=include_incomplete,
                incomplete_age_days=incomplete_age_days,
            )
            plan = _build_plan_for_connection(
                connection,
                db_path,
                as_of=as_of,
                grace_days=grace_days,
                include_legacy=include_legacy,
                include_incomplete=include_incomplete,
                legacy_cutover=legacy_cutover,
            )
            connection.execute(
                """INSERT INTO sentiment_retention_run(
                     run_id,mode,dry_run,grace_days,cutoff,include_legacy,
                     include_incomplete,state,plan_json,result_json,started_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    run_id,
                    "seal_and_purge",
                    0,
                    grace_days,
                    as_of.isoformat(timespec="seconds"),
                    int(include_legacy),
                    int(include_incomplete),
                    "running",
                    _json(plan),
                    "{}",
                    started_at,
                ),
            )
            results = []
            for action, rows in (
                ("purge_complete", plan["complete"]),
                ("purge_incomplete", plan["incomplete"]),
                ("purge_legacy", plan["legacy"]),
                ("purge_unmapped", plan["unmapped"]),
            ):
                for row in rows:
                    if not row["eligible"]:
                        continue
                    window_id = str(row["window_id"])
                    if action == "purge_complete":
                        outcome = _delete_complete_window(
                            connection,
                            window_id,
                            purged_at=as_of.isoformat(timespec="seconds"),
                        )
                    elif action == "purge_incomplete":
                        outcome = _delete_incomplete_window(
                            connection,
                            window_id,
                            purged_at=as_of.isoformat(timespec="seconds"),
                        )
                    elif action == "purge_legacy":
                        outcome = _delete_legacy_window(connection, window_id)
                    else:
                        outcome = _delete_unmapped_raw(
                            connection,
                            cutoff=str(row["cutoff"]),
                        )
                    connection.execute(
                        """INSERT INTO sentiment_retention_window(
                             run_id,window_id,action,prior_status,raw_rows,
                             mapping_rows,feed_rows,estimated_bytes,
                             aggregate_sha256,created_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        (
                            run_id,
                            window_id,
                            action,
                            row.get("status"),
                            outcome["raw_rows"],
                            outcome["mapping_rows"],
                            outcome["feed_rows"],
                            int(row["estimated_bytes"]),
                            outcome["aggregate_sha256"],
                            as_of.isoformat(timespec="seconds"),
                        ),
                    )
                    results.append(
                        {"window_id": window_id, "action": action, **outcome}
                    )
            result = {
                "migration": migration,
                "purged_windows": len(results),
                "windows": results,
            }
            connection.execute(
                """UPDATE sentiment_retention_run
                   SET state='complete',result_json=?,finished_at=?
                   WHERE run_id=?""",
                (_json(result), _now().isoformat(timespec="seconds"), run_id),
            )
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            if integrity != "ok" or foreign_keys:
                raise RuntimeError(
                    f"清理后 SQLite 校验失败 integrity={integrity} "
                    f"foreign_keys={foreign_keys[:5]}"
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {
        "run_id": run_id,
        "plan": plan,
        "result": result,
        "integrity_check": "ok",
        "foreign_key_issues": 0,
    }


def compact_database(
    db_path: Path,
    *,
    backup_confirmation: Path,
) -> dict[str, Any]:
    from tools.data_platform.routing import Backend, load_environment_authority_matrix

    matrix = load_environment_authority_matrix()
    if (
        matrix is not None
        and matrix.routes["sentiment_analytics"].backend
        is Backend.POSTGRESQL_PRODUCTION
    ):
        raise RuntimeError(
            "physical SQLite compaction is inapplicable after sentiment PostgreSQL "
            "cutover; the retired SQLite file remains an audit baseline and the "
            "PostgreSQL projection is rebuilt outside that file"
        )
    backup_confirmation = backup_confirmation.resolve()
    if not backup_confirmation.exists():
        raise FileNotFoundError(
            f"缺少外部备份确认路径: {backup_confirmation}"
        )
    db_path = db_path.resolve()
    if db_path.parent != (ROOT / "data").resolve():
        raise ValueError("只允许压缩项目 data/ 下的 sentiment.db")
    before_bytes = db_path.stat().st_size
    temp_path = db_path.with_name("sentiment.compacted.tmp.db")
    rollback_path = db_path.with_name("sentiment.precompact.rollback.db")
    for path in (temp_path, rollback_path):
        if path.exists():
            path.unlink()
    with closing(_connect(db_path, physical_sqlite=True)) as connection:
        checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if int(checkpoint[0]) != 0:
            raise RuntimeError(f"WAL checkpoint 被活动连接阻塞: {tuple(checkpoint)}")
        quoted = str(temp_path).replace("'", "''")
        connection.execute(f"VACUUM INTO '{quoted}'")
    wal_path = db_path.with_name(db_path.name + "-wal")
    shm_path = db_path.with_name(db_path.name + "-shm")
    if wal_path.exists() and wal_path.stat().st_size:
        temp_path.unlink(missing_ok=True)
        raise RuntimeError(f"WAL 仍包含未清空数据: {wal_path}")
    for sidecar in (wal_path, shm_path):
        sidecar.unlink(missing_ok=True)
    with closing(
        _connect(temp_path, read_only=True, physical_sqlite=True)
    ) as compacted:
        integrity = compacted.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = compacted.execute("PRAGMA foreign_key_check").fetchall()
        counts = {
            table: _table_count(compacted, table)
            for table in (
                "senti_raw",
                "senti_raw_window",
                "yuqing_feed_raw",
                "senti_retail_window",
                "senti_retail_trading_daily",
            )
        }
    if integrity != "ok" or foreign_keys:
        temp_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"压缩库校验失败 integrity={integrity} foreign_keys={foreign_keys[:5]}"
        )
    expected_root = (ROOT / "data").resolve()
    if any(path.resolve().parent != expected_root for path in (db_path, temp_path, rollback_path)):
        raise RuntimeError("压缩替换路径越界")
    os.replace(db_path, rollback_path)
    try:
        os.replace(temp_path, db_path)
        with closing(_connect(db_path, physical_sqlite=True)) as installed:
            journal_mode = str(
                installed.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            )
            installed_integrity = installed.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0]
            installed_fk = installed.execute("PRAGMA foreign_key_check").fetchall()
        if (
            installed_integrity != "ok"
            or installed_fk
            or journal_mode.lower() != "wal"
        ):
            raise RuntimeError(
                f"安装后校验失败 integrity={installed_integrity} "
                f"foreign_keys={installed_fk[:5]} journal_mode={journal_mode}"
            )
        rollback_path.unlink()
    except Exception:
        if db_path.exists():
            db_path.unlink()
        os.replace(rollback_path, db_path)
        raise
    return {
        "before_bytes": before_bytes,
        "after_bytes": db_path.stat().st_size,
        "reclaimed_bytes": before_bytes - db_path.stat().st_size,
        "sha256": _sha256_file(db_path),
        "checkpoint": list(checkpoint),
        "integrity_check": "ok",
        "foreign_key_issues": 0,
        "table_counts": counts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--grace-days", type=int, default=DEFAULT_GRACE_DAYS)
    parser.add_argument("--as-of")
    parser.add_argument("--include-legacy", action="store_true")
    parser.add_argument(
        "--include-expired-incomplete",
        action="store_true",
        help="显式封存并清理超过期限的 partial/failed 窗口",
    )
    parser.add_argument(
        "--incomplete-age-days",
        type=int,
        default=DEFAULT_INCOMPLETE_AGE_DAYS,
    )
    parser.add_argument(
        "--legacy-cutover",
        default=DEFAULT_LEGACY_CUTOVER,
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("--backup-confirmation", type=Path)
    args = parser.parse_args()
    as_of = (
        datetime.fromisoformat(args.as_of)
        if args.as_of
        else _now()
    )
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=BEIJING)
    if args.grace_days < 0:
        raise SystemExit("--grace-days 不能为负数")
    if args.compact:
        if not args.apply or not args.backup_confirmation:
            raise SystemExit(
                "--compact 必须同时提供 --apply 和 --backup-confirmation"
            )
        from tools.sentiment.retail_window_tick import exclusive_tick_lock

        with exclusive_tick_lock():
            result = compact_database(
                args.db,
                backup_confirmation=args.backup_confirmation,
            )
    elif args.apply:
        from tools.sentiment.retail_window_tick import exclusive_tick_lock

        with exclusive_tick_lock():
            result = apply_retention(
                args.db,
                as_of=as_of,
                grace_days=args.grace_days,
                include_legacy=args.include_legacy,
                include_incomplete=args.include_expired_incomplete,
                incomplete_age_days=args.incomplete_age_days,
                legacy_cutover=args.legacy_cutover,
            )
    else:
        result = build_plan(
            args.db,
            as_of=as_of,
            grace_days=args.grace_days,
            include_legacy=args.include_legacy,
            include_incomplete=args.include_expired_incomplete,
            legacy_cutover=args.legacy_cutover,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
