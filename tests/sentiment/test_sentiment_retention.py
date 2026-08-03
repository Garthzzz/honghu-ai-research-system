from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

from tools.maintenance import sentiment_retention
from tools.sentiment import retail_windows_v2, senti3


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


def test_legacy_cutover_purges_only_unmapped_weekend_retail_rows(
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
    remaining = connection.execute(
        "SELECT id FROM senti_raw ORDER BY id"
    ).fetchall()
    assert remaining == [(2,)]
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
