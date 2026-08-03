from __future__ import annotations

import sqlite3

from tools.pipeline.consensus_compute import recompute_after_insert


def test_recompute_after_insert_keeps_company_in_peer_group() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE industry_data_point(
          id INTEGER PRIMARY KEY,
          industry_id INTEGER NOT NULL,
          company_id INTEGER,
          metric TEXT NOT NULL,
          period TEXT NOT NULL,
          as_of_date TEXT,
          is_forecast INTEGER NOT NULL,
          value_num REAL,
          source_id INTEGER,
          extraction_method TEXT NOT NULL,
          consensus_status TEXT DEFAULT 'unevaluated',
          peer_count INTEGER,
          peer_median REAL,
          peer_std REAL,
          deviation_from_median REAL
        );
        CREATE TABLE data_point_peer_group(
          group_id INTEGER PRIMARY KEY AUTOINCREMENT,
          industry_id INTEGER NOT NULL,
          company_id INTEGER,
          metric TEXT NOT NULL,
          as_of_date TEXT NOT NULL,
          is_forecast INTEGER NOT NULL,
          peer_count INTEGER,
          peer_median REAL,
          peer_mean REAL,
          peer_std REAL,
          peer_min REAL,
          peer_max REAL,
          computed_at TEXT
        );
        INSERT INTO industry_data_point(
          id, industry_id, company_id, metric, period, as_of_date,
          is_forecast, value_num, extraction_method
        ) VALUES (
          1, 23, 566, 'KLA PCB and Component Inspection分部收入',
          'FY2025（截至2025-06-30）', '2025-06-30', 0, 6.21721, 'inferred'
        );
        """
    )

    assert recompute_after_insert(1, conn=conn) == 1
    row = conn.execute(
        """SELECT consensus_status, peer_count, peer_median, peer_std,
                  deviation_from_median
           FROM industry_data_point WHERE id = 1"""
    ).fetchone()
    assert row["consensus_status"] == "孤证"
    assert row["peer_count"] == 1
    assert row["peer_median"] == 6.21721
    assert row["peer_std"] == 0.0
    assert row["deviation_from_median"] == 0.0

    group = conn.execute(
        """SELECT company_id, peer_count, peer_median
           FROM data_point_peer_group"""
    ).fetchone()
    assert group["company_id"] == 566
    assert group["peer_count"] == 1
    assert group["peer_median"] == 6.21721
