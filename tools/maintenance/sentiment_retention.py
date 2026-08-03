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

from tools.sentiment import retail_windows_v2


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "sentiment.db"
BEIJING = ZoneInfo("Asia/Shanghai")
# 完整窗口在永久聚合、版本与哈希校验通过后即可删除逐帖原文。
# 未完成窗口仍由独立的显式门禁保护，不能因该值为 0 被顺带清理。
DEFAULT_GRACE_DAYS = 0
DEFAULT_LEGACY_CUTOVER = "2026-07-15"
DEFAULT_INCOMPLETE_AGE_DAYS = 30
PAYLOAD_SAMPLE_ROWS = 10_000


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


def _connect(path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    if read_only:
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
        anchor_text = str(
            row["finished_at"] or row["window_end"] or row["raw_purge_after"] or ""
        )
        if not anchor_text:
            continue
        effective_purge_after = datetime.fromisoformat(anchor_text) + timedelta(
            days=grace_days
        )
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
        anchor_text = str(
            row["finished_at"] or row["window_end"] or row["raw_purge_after"] or ""
        )
        if not anchor_text:
            continue
        effective_purge_after = datetime.fromisoformat(anchor_text) + timedelta(
            days=grace_days
        )
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
        legacy = (
            _candidate_legacy(connection, cutover_date=legacy_cutover)
            if include_legacy else []
        )
        legacy_orphans = (
            _candidate_legacy_weekend_orphans(
                connection,
                cutover_date=legacy_cutover,
            )
            if include_legacy else []
        )
        averages = {
            table: _average_payload(connection, table)
            for table in ("senti_raw", "senti_raw_window", "yuqing_feed_raw")
        }
        for row in complete + incomplete + legacy + legacy_orphans:
            row["estimated_bytes"] = int(
                row["raw_rows"] * averages["senti_raw"]
                + row["mapping_rows"] * averages["senti_raw_window"]
                + row["feed_rows"] * averages["yuqing_feed_raw"]
            )
        return {
            "schema_version": "industry_demo.sentiment_retention_plan.v1",
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
                )
            },
            "complete": complete,
            "incomplete": incomplete,
            "legacy": legacy,
            "legacy_orphans": legacy_orphans,
            "eligible_windows": sum(
                1
                for row in complete + incomplete + legacy + legacy_orphans
                if row["eligible"]
            ),
            "estimated_reclaim_bytes": sum(
                int(row["estimated_bytes"])
                for row in complete + incomplete + legacy + legacy_orphans
                if row["eligible"]
            ),
        }


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
        migrated.append(
            retail_windows_v2.seal_window(
                connection,
                window_id,
                grace_days=grace_days,
                sealed_at=now.isoformat(timespec="seconds"),
            )
        )
        session_dates.add(str(row["session_date"]))
    for session_date in sorted(session_dates):
        retail_windows_v2.aggregate_trading_day(
            connection,
            session_date,
            computed_at=now.isoformat(timespec="seconds"),
        )
    incomplete = []
    if include_incomplete:
        incomplete_before = (
            now - timedelta(days=incomplete_age_days)
        ).isoformat(timespec="seconds")
        rows = connection.execute(
            """SELECT window_id FROM retail_window_ledger
               WHERE status IN ('partial','failed')
                 AND scheduled_for<=?
                 AND raw_purged_at IS NULL
               ORDER BY scheduled_for,window_id""",
            (incomplete_before,),
        ).fetchall()
        for row in rows:
            window_id = str(row["window_id"])
            if retail_windows_v2.window_has_active_work(connection, window_id):
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
            incomplete.append(
                retail_windows_v2.seal_window(
                    connection,
                    window_id,
                    grace_days=grace_days,
                    allow_incomplete=True,
                    sealed_at=now.isoformat(timespec="seconds"),
                )
            )
    return {
        "migrated_windows": len(migrated),
        "sealed_incomplete_windows": len(incomplete),
        "session_dates": sorted(session_dates),
        "windows": migrated,
        "incomplete_windows": incomplete,
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
    started_at = _now().isoformat(timespec="seconds")
    with closing(_connect(db_path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        migration = migrate_and_seal(
            connection,
            grace_days=grace_days,
            now=as_of,
            include_incomplete=include_incomplete,
            incomplete_age_days=incomplete_age_days,
        )
        connection.commit()

    plan = build_plan(
        db_path,
        as_of=as_of,
        grace_days=grace_days,
        include_legacy=include_legacy,
        include_incomplete=include_incomplete,
        legacy_cutover=legacy_cutover,
    )
    with closing(_connect(db_path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
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
            ("purge_legacy_weekend_orphan", plan["legacy_orphans"]),
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
                    outcome = _delete_legacy_weekend_orphans(
                        connection,
                        cutover_date=legacy_cutover,
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
    with closing(_connect(db_path)) as connection:
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
    with closing(_connect(temp_path, read_only=True)) as compacted:
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
        with closing(_connect(db_path)) as installed:
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
