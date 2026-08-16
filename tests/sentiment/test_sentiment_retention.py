from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.maintenance import sentiment_retention
from tools.sentiment import retail_windows_v2, senti3, senti_aggregate_3layer


RAW_DDL = """
CREATE TABLE senti_raw (
  id INTEGER PRIMARY KEY,
  company_id INTEGER NOT NULL,
  ticker TEXT NOT NULL,
  source_layer TEXT NOT NULL,
  platform TEXT NOT NULL,
  attitude INTEGER,
  heat_value INTEGER,
  publish_time TEXT
);
CREATE TABLE senti_retail_daily (
  id INTEGER PRIMARY KEY,
  company_id INTEGER NOT NULL,
  trade_date TEXT NOT NULL
);
CREATE TABLE heat_volume_daily (
  id INTEGER PRIMARY KEY,
  company_id INTEGER NOT NULL,
  trade_date TEXT NOT NULL
);
"""


def _database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(RAW_DDL)
    retail_windows_v2.ensure_schema(connection)
    connection.commit()
    return connection


def _raw(
    connection: sqlite3.Connection,
    *,
    row_id: int,
    company_id: int,
    publish_time: str,
) -> None:
    connection.execute(
        """INSERT INTO senti_raw(
             id,company_id,ticker,source_layer,platform,attitude,
             heat_value,publish_time)
           VALUES(?,?,?,?,?,?,?,?)""",
        (
            row_id,
            company_id,
            f"{company_id:06d}.SZ",
            "retail",
            "guba",
            1,
            5,
            publish_time,
        ),
    )


def _map(
    connection: sqlite3.Connection,
    *,
    row_id: int,
    window_id: str,
) -> None:
    connection.execute(
        """INSERT INTO senti_raw_window(
             raw_id,window_id,mapping_version,mapped_at)
           VALUES(?,?,?,?)""",
        (
            row_id,
            window_id,
            senti3.MARKET_WINDOW_VERSION,
            "2026-07-20T14:00:00+08:00",
        ),
    )


def test_dry_run_does_not_change_database(tmp_path: Path) -> None:
    path = tmp_path / "sentiment.db"
    connection = _database(path)
    before = connection.total_changes
    connection.close()

    plan = sentiment_retention.build_plan(
        path,
        as_of=datetime.fromisoformat("2026-08-20T12:00:00+08:00"),
        grace_days=14,
        include_legacy=False,
        include_incomplete=False,
        legacy_cutover="2026-07-15",
    )

    assert plan["schema_ready"]
    connection = sqlite3.connect(path)
    assert connection.total_changes == 0
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    connection.close()
    assert before >= 0


def test_complete_window_survives_raw_purge_as_permanent_fact(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sentiment.db"
    connection = _database(path)
    window = senti3.market_window(date(2026, 7, 20), "morning")
    retail_windows_v2.ensure_window(connection, window)
    _raw(
        connection,
        row_id=1,
        company_id=10,
        publish_time="2026-07-20T10:00:00+08:00",
    )
    _map(connection, row_id=1, window_id=window.window_id)
    retail_windows_v2.mark_window_status(
        connection,
        window.window_id,
        "complete",
        timestamp="2026-07-20T14:05:00+08:00",
    )
    connection.commit()
    connection.close()

    result = sentiment_retention.apply_retention(
        path,
        as_of=datetime.fromisoformat("2026-08-20T12:00:00+08:00"),
        grace_days=14,
        include_legacy=False,
        include_incomplete=False,
        incomplete_age_days=30,
        legacy_cutover="2026-07-15",
    )

    assert result["result"]["purged_windows"] == 1
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    assert connection.execute("SELECT COUNT(*) FROM senti_raw").fetchone()[0] == 0
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM senti_retail_window"
        ).fetchone()[0]
        == 1
    )
    ledger = connection.execute(
        """SELECT retention_state,raw_purged_at,aggregate_sha256
           FROM retail_window_ledger WHERE window_id=?""",
        (window.window_id,),
    ).fetchone()
    assert ledger["retention_state"] == "purged"
    assert ledger["raw_purged_at"]
    assert ledger["aggregate_sha256"]
    retail_windows_v2.aggregate_trading_day(
        connection,
        "2026-07-20",
        significance_min=0,
    )
    daily = connection.execute(
        "SELECT raw_count,net_weighted FROM senti_retail_trading_daily"
    ).fetchone()
    assert tuple(daily) == (1, 1.0)
    connection.close()


def test_legacy_cutover_requires_and_preserves_legacy_aggregates(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sentiment.db"
    connection = _database(path)
    window = senti3.market_window(date(2026, 7, 10), "morning")
    retail_windows_v2.ensure_window(connection, window)
    _raw(
        connection,
        row_id=1,
        company_id=10,
        publish_time="2026-07-10T10:00:00+08:00",
    )
    _map(connection, row_id=1, window_id=window.window_id)
    connection.execute(
        "INSERT INTO senti_retail_daily(company_id,trade_date) VALUES(?,?)",
        (10, "2026-07-10"),
    )
    connection.execute(
        "INSERT INTO heat_volume_daily(company_id,trade_date) VALUES(?,?)",
        (10, "2026-07-10"),
    )
    connection.commit()
    connection.close()

    result = sentiment_retention.apply_retention(
        path,
        as_of=datetime.fromisoformat("2026-08-20T12:00:00+08:00"),
        grace_days=14,
        include_legacy=True,
        include_incomplete=False,
        incomplete_age_days=30,
        legacy_cutover="2026-07-15",
    )

    assert result["result"]["purged_windows"] == 1
    connection = sqlite3.connect(path)
    assert connection.execute("SELECT COUNT(*) FROM senti_raw").fetchone()[0] == 0
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM retail_window_ledger"
        ).fetchone()[0]
        == 0
    )
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM senti_retail_daily"
        ).fetchone()[0]
        == 1
    )
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM heat_volume_daily"
        ).fetchone()[0]
        == 1
    )
    connection.close()


def test_three_day_lifecycle_freezes_and_purges_all_old_unmapped_rows(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sentiment.db"
    connection = _database(path)
    _raw(
        connection,
        row_id=1,
        company_id=10,
        publish_time="2026-07-11T10:00:00+08:00",
    )
    _raw(
        connection,
        row_id=2,
        company_id=10,
        publish_time="2026-07-10T10:00:00+08:00",
    )
    connection.commit()
    connection.close()

    result = sentiment_retention.apply_retention(
        path,
        as_of=datetime.fromisoformat("2026-08-20T12:00:00+08:00"),
        grace_days=14,
        include_legacy=True,
        include_incomplete=False,
        incomplete_age_days=30,
        legacy_cutover="2026-07-15",
    )

    assert result["result"]["purged_windows"] == 1
    connection = sqlite3.connect(path)
    assert connection.execute("SELECT COUNT(*) FROM senti_raw").fetchone()[0] == 0
    frozen = connection.execute(
        """SELECT trade_date,raw_count,scored_count,pos,aggregate_sha256
           FROM senti_unmapped_daily ORDER BY trade_date"""
    ).fetchall()
    assert len(frozen) == 2
    assert [tuple(row[:4]) for row in frozen] == [
        ("2026-07-10", 1, 1, 1),
        ("2026-07-11", 1, 1, 1),
    ]
    assert all(row[4] for row in frozen)
    connection.close()


def _terminal_checkpoint(
    connection: sqlite3.Connection,
    *,
    window_id: str,
    status: str = "partial",
) -> None:
    key = (window_id, "subject-1", "all", "2026-07-20T09:00:00+08:00", "2026-07-20T10:00:00+08:00")
    connection.execute(
        """INSERT INTO retail_window_source_run(
             window_id,source,status,records_seen,inserted,error_code,started_at,finished_at)
           VALUES(?,?,?,?,?,?,?,?)""",
        (
            window_id,
            "xinghan",
            "failed" if status != "running" else "running",
            1,
            1,
            "terminal_test",
            "2026-07-20T10:00:00+08:00",
            None if status == "running" else "2026-07-20T10:05:00+08:00",
        ),
    )
    connection.execute(
        """INSERT INTO yuqing_fetch_segment_run(
             window_id,subject_id,request_variant,segment_start,segment_end,status,
             snapshot_timestamp_ms,pages_committed,records_seen,error_code,
             started_at,finished_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (*key, status, 1, 1, 1, "terminal_test", "2026-07-20T10:00:00+08:00",
         None if status == "running" else "2026-07-20T10:05:00+08:00",
         "2026-07-20T10:05:00+08:00"),
    )
    connection.execute(
        """INSERT INTO yuqing_fetch_checkpoint(
             window_id,subject_id,request_variant,segment_start,segment_end,
             request_begin_ms,request_end_ms,snapshot_timestamp_ms,next_offset,
             page_size,pages_committed,records_seen,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (*key, 1, 2, 3, 10, 30, 1, 1,
         "2026-07-20T10:00:00+08:00", "2026-07-20T10:05:00+08:00"),
    )


def test_terminal_partial_is_sealed_and_purged_without_becoming_complete(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sentiment.db"
    connection = _database(path)
    window = senti3.market_window(date(2026, 7, 20), "morning")
    retail_windows_v2.ensure_window(connection, window)
    _raw(connection, row_id=1, company_id=10, publish_time="2026-07-20T10:00:00+08:00")
    _map(connection, row_id=1, window_id=window.window_id)
    _terminal_checkpoint(connection, window_id=window.window_id)
    retail_windows_v2.mark_window_status(
        connection, window.window_id, "partial", timestamp="2026-07-20T14:05:00+08:00"
    )
    connection.commit()
    connection.close()

    result = sentiment_retention.apply_retention(
        path,
        as_of=datetime.fromisoformat("2026-07-24T14:06:00+08:00"),
        grace_days=3,
        include_legacy=False,
        include_incomplete=True,
        incomplete_age_days=3,
        legacy_cutover="2026-07-15",
    )

    assert result["result"]["migration"]["sealed_incomplete_windows"] == 1
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    ledger = connection.execute(
        "SELECT status,retention_state,aggregate_sha256 FROM retail_window_ledger"
    ).fetchone()
    assert tuple(ledger[:2]) == ("partial", "purged_incomplete")
    assert ledger["aggregate_sha256"]
    assert connection.execute("SELECT COUNT(*) FROM senti_raw").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM yuqing_fetch_checkpoint").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM yuqing_fetch_segment_run").fetchone()[0] == 1
    connection.close()


def test_running_checkpoint_blocks_incomplete_finalization(tmp_path: Path) -> None:
    path = tmp_path / "sentiment.db"
    connection = _database(path)
    window = senti3.market_window(date(2026, 7, 20), "morning")
    retail_windows_v2.ensure_window(connection, window)
    _raw(connection, row_id=1, company_id=10, publish_time="2026-07-20T10:00:00+08:00")
    _map(connection, row_id=1, window_id=window.window_id)
    _terminal_checkpoint(connection, window_id=window.window_id, status="running")
    retail_windows_v2.mark_window_status(
        connection, window.window_id, "partial", timestamp="2026-07-20T14:05:00+08:00"
    )
    connection.commit()
    connection.close()

    result = sentiment_retention.apply_retention(
        path,
        as_of=datetime.fromisoformat("2026-07-24T14:06:00+08:00"),
        grace_days=3,
        include_legacy=False,
        include_incomplete=True,
        incomplete_age_days=3,
        legacy_cutover="2026-07-15",
    )
    assert result["result"]["migration"]["sealed_incomplete_windows"] == 0
    connection = sqlite3.connect(path)
    assert connection.execute("SELECT COUNT(*) FROM senti_raw").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM yuqing_fetch_checkpoint").fetchone()[0] == 1
    connection.close()


def test_recent_unmapped_raw_remains_in_three_day_working_set(tmp_path: Path) -> None:
    path = tmp_path / "sentiment.db"
    connection = _database(path)
    _raw(connection, row_id=1, company_id=10, publish_time="2026-08-18T11:59:59+08:00")
    _raw(connection, row_id=2, company_id=10, publish_time="2026-08-17T11:59:59+08:00")
    connection.commit()
    connection.close()

    sentiment_retention.apply_retention(
        path,
        as_of=datetime.fromisoformat("2026-08-20T12:00:00+08:00"),
        grace_days=3,
        include_legacy=False,
        include_incomplete=True,
        incomplete_age_days=3,
        legacy_cutover="2026-07-15",
    )
    connection = sqlite3.connect(path)
    remaining = connection.execute("SELECT id FROM senti_raw ORDER BY id").fetchall()
    assert remaining == [(1,)]
    assert connection.execute("SELECT SUM(raw_count) FROM senti_unmapped_daily").fetchone()[0] == 1
    connection.close()


def test_zero_attempt_legacy_pending_mapping_is_frozen_not_marked_complete(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sentiment.db"
    connection = _database(path)
    window = senti3.market_window(date(2026, 2, 20), "preopen")
    retail_windows_v2.ensure_window(connection, window)
    _raw(connection, row_id=1, company_id=10, publish_time="2026-02-19T18:40:00+08:00")
    _map(connection, row_id=1, window_id=window.window_id)
    connection.commit()
    connection.close()

    plan = sentiment_retention.build_plan(
        path,
        as_of=datetime.fromisoformat("2026-08-20T12:00:00+08:00"),
        grace_days=3,
        include_legacy=False,
        include_incomplete=True,
        legacy_cutover="2026-07-15",
    )
    assert [item["window_id"] for item in plan["legacy_pending_orphans"]] == [
        window.window_id
    ]
    connection = sqlite3.connect(path)
    assert connection.execute("SELECT COUNT(*) FROM senti_raw_window").fetchone()[0] == 1
    assert connection.execute("SELECT retention_state FROM retail_window_ledger").fetchone()[0] == "live"
    connection.close()

    result = sentiment_retention.apply_retention(
        path,
        as_of=datetime.fromisoformat("2026-08-20T12:00:00+08:00"),
        grace_days=3,
        include_legacy=False,
        include_incomplete=True,
        incomplete_age_days=3,
        legacy_cutover="2026-07-15",
    )

    orphan = result["result"]["migration"]["legacy_pending_orphans"]
    assert [(item["window_id"], item["raw_rows"]) for item in orphan] == [
        (window.window_id, 1)
    ]
    connection = sqlite3.connect(path)
    ledger = connection.execute(
        """SELECT status,retention_state,seal_reason,raw_purged_at
           FROM retail_window_ledger WHERE window_id=?""",
        (window.window_id,),
    ).fetchone()
    assert ledger[:3] == (
        "pending",
        "purged_incomplete",
        "legacy_pending_orphan_numeric_frozen",
    )
    assert ledger[3]
    assert connection.execute("SELECT COUNT(*) FROM senti_raw").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM senti_raw_window").fetchone()[0] == 0
    assert connection.execute("SELECT SUM(raw_count) FROM senti_unmapped_daily").fetchone()[0] == 1
    connection.close()

def test_compaction_rebuilds_and_keeps_database_valid(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "industry_demo"
    data_dir = root / "data"
    data_dir.mkdir(parents=True)
    path = data_dir / "sentiment.db"
    connection = _database(path)
    connection.executemany(
        """INSERT INTO senti_raw(
             id,company_id,ticker,source_layer,platform,attitude,
             heat_value,publish_time)
           VALUES(?,?,?,?,?,?,?,?)""",
        [
            (
                row_id,
                10,
                "000010.SZ",
                "retail",
                "guba",
                1,
                1,
                "2026-07-20T10:00:00+08:00",
            )
            for row_id in range(1, 101)
        ],
    )
    connection.commit()
    connection.execute("DELETE FROM senti_raw WHERE id<=90")
    connection.commit()
    connection.close()
    backup = tmp_path / "industry_demo_backup_test"
    backup.mkdir()
    monkeypatch.setattr(sentiment_retention, "ROOT", root)

    result = sentiment_retention.compact_database(
        path,
        backup_confirmation=backup,
    )

    assert result["integrity_check"] == "ok"
    assert result["foreign_key_issues"] == 0
    connection = sqlite3.connect(path)
    assert connection.execute("SELECT COUNT(*) FROM senti_raw").fetchone()[0] == 10
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    connection.close()


def test_legacy_full_history_rebuild_fails_closed_after_raw_purge(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sentiment.db"
    connection = _database(path)
    connection.execute(
        """INSERT INTO retail_window_ledger(
             window_id,window_version,session_date,slot,window_start,window_end,
             scheduled_for,segments_json,effective_minutes,
             status,retention_state,raw_purged_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "2026-07-20:morning",
            senti3.MARKET_WINDOW_VERSION,
            "2026-07-20",
            "morning",
            "2026-07-20T09:30:00+08:00",
            "2026-07-20T11:30:00+08:00",
            "2026-07-20T11:35:00+08:00",
            "[]",
            120,
            "complete",
            "purged",
            "2026-07-24T12:00:00+08:00",
        ),
    )
    connection.execute(
        "INSERT INTO senti_retail_daily(id,company_id,trade_date) VALUES(?,?,?)",
        (1, 10, "2026-07-20"),
    )
    connection.commit()

    with pytest.raises(RuntimeError, match="full-history senti_raw aggregation is retired"):
        senti_aggregate_3layer.agg_retail(
            connection,
            "2026-08-20T12:00:00+08:00",
            {},
            10,
            0.5,
        )

    assert connection.execute("SELECT COUNT(*) FROM senti_retail_daily").fetchone()[0] == 1
    connection.close()


def test_retention_connection_uses_authoritative_unit_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: dict[str, object] = {}
    connection = sqlite3.connect(":memory:")

    def fake_connect(unit, path, **kwargs):
        observed.update(unit=unit, path=path, **kwargs)
        return connection

    monkeypatch.setattr(
        "tools.data_platform.domain_data.connect_domain_database", fake_connect
    )
    result = sentiment_retention._connect(
        tmp_path / "sentiment.db",
        operation_id="retention-window-identity",
    )

    assert result is connection
    assert observed["unit"] == "sentiment_analytics"
    assert observed["readonly"] is False
    assert observed["operation_scope"] == "sentiment_retention"
    assert observed["operation_id"] == "retention-window-identity"
    connection.close()


def test_physical_compaction_is_fenced_after_postgresql_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.data_platform.routing import Backend

    path = tmp_path / "industry_demo" / "data" / "sentiment.db"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not-opened")
    backup = tmp_path / "industry_demo_backup_package"
    backup.mkdir()
    monkeypatch.setattr(sentiment_retention, "ROOT", path.parents[1])
    monkeypatch.setattr(
        "tools.data_platform.routing.load_environment_authority_matrix",
        lambda: SimpleNamespace(
            routes={
                "sentiment_analytics": SimpleNamespace(
                    backend=Backend.POSTGRESQL_PRODUCTION
                )
            }
        ),
    )

    with pytest.raises(RuntimeError, match="inapplicable after sentiment PostgreSQL"):
        sentiment_retention.compact_database(
            path,
            backup_confirmation=backup,
        )
