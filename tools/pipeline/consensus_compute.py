#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
多源对照算法 — consensus_compute.py(第三次修订任务 2b)

对每个 (industry_id|company_id, metric, as_of_date, is_forecast) 组合(peer group):
1. 找出所有该 peer group 内的 data_point
2. 计算 median / std / mean / min / max
3. 更新 data_point_peer_group 表
4. 更新每个 data_point 的 consensus_status:

   - peer_count == 1         → 孤证
   - peer_count == 2         → 次主流(无法判断离群)
   - peer_count in {3, 4}    → 与 median 比对:
                                  |value - median| / |median| < 0.15  → 主流
                                  else                                 → 次主流
   - peer_count >= 5         → 按 std 分级:
                                  ±0.5σ 内  → 共识
                                  ±1σ 内    → 主流
                                  ±2σ 内    → 次主流
                                  外        → 离群

接口:
- recompute_all(industry_id)                  全量重算
- recompute_metric(industry_id, metric)       某 metric 所有 peer group 重算
- recompute_after_insert(data_point_id)       单 data_point 插入后重算其 peer group(供 db_writer hook)

?? 算法不靠人工判断(per user 要求 Level 2)。
?? 仅对 value_num 非空的 data_point 计算共识;value_text-only 的 data_point 共识状态保持 'unevaluated'。
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import statistics
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT    = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "data" / "research.db"


def get_db(db_path: Optional[Path] = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path or DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ── peer group key 抽取 ────────────────────────────────
def _group_key(row: sqlite3.Row) -> Tuple:
    """从 data_point row 提取 peer group 5 元组 key。
    industry_id 必有;company_id 用 industry_data_point.company_id(2026-05-28 迁移加列)。
    """
    try:
        cid = row["company_id"]
    except (KeyError, IndexError):
        cid = None
    return (
        row["industry_id"],
        cid,
        row["metric"],
        row["as_of_date"] or row["period"],
        int(row["is_forecast"]),
    )


def _classify(value: float, peer_values: List[float]) -> Tuple[str, Optional[float], Optional[float], Optional[float]]:
    """根据当前 data_point 的 value 与 peer_values(含自身)计算分级。
    返回 (consensus_status, peer_median, peer_std, deviation_from_median)。
    """
    n = len(peer_values)
    if n == 0:
        return ("unevaluated", None, None, None)
    median = statistics.median(peer_values)
    std = statistics.pstdev(peer_values) if n >= 2 else 0.0
    # deviation as fraction of |median|; if median == 0, use std-based metric
    if abs(median) > 1e-9:
        dev = (value - median) / abs(median)
    else:
        dev = 0.0 if abs(value) < 1e-9 else (value / 1.0)
    abs_dev = abs(dev)

    if n == 1:
        return ("孤证", median, std, dev)
    if n == 2:
        return ("次主流", median, std, dev)
    if n in (3, 4):
        if abs_dev < 0.15:
            return ("主流", median, std, dev)
        else:
            return ("次主流", median, std, dev)
    # n >= 5
    if std < 1e-9:
        # 完全一致 → 共识
        return ("共识", median, std, dev)
    z = abs(value - median) / std
    if z <= 0.5:
        return ("共识", median, std, dev)
    if z <= 1.0:
        return ("主流", median, std, dev)
    if z <= 2.0:
        return ("次主流", median, std, dev)
    return ("离群", median, std, dev)


def _list_peer_data_points(
    conn: sqlite3.Connection, group_key: Tuple
) -> List[sqlite3.Row]:
    """返回某 peer group 内所有 value_num 非空的 data_point(含 extraction_method)。
    调用方负责过滤 template_estimate(GOLD 第四次修订:不让模板进入共识)。
    """
    industry_id, company_id, metric, as_of, is_forecast = group_key
    if as_of is None:
        return []
    # company_id 必须进入 peer 过滤:不同公司的同名 metric(如各家 CapEx / 市占率)
    # 不应算作 peer,否则会产生"N 家公司值算一个 peer group"的虚假共识。
    sql = """
        SELECT id, value_num, period, as_of_date, source_id, extraction_method
        FROM industry_data_point
        WHERE industry_id = ?
          AND metric = ?
          AND (COALESCE(NULLIF(as_of_date, ''), period) = ?)
          AND is_forecast = ?
          AND value_num IS NOT NULL
          AND ((company_id = ?) OR (company_id IS NULL AND ? IS NULL))
    """
    rows = conn.execute(sql, (industry_id, metric, as_of, is_forecast, company_id, company_id)).fetchall()
    return rows


def _upsert_peer_group(
    conn: sqlite3.Connection,
    group_key: Tuple,
    peer_values: List[float],
) -> None:
    industry_id, company_id, metric, as_of, is_forecast = group_key
    n = len(peer_values)
    if n == 0:
        return
    median = statistics.median(peer_values)
    mean   = statistics.fmean(peer_values)
    std    = statistics.pstdev(peer_values) if n >= 2 else 0.0
    pmin   = min(peer_values)
    pmax   = max(peer_values)
    now    = datetime.now().isoformat(timespec="seconds")
    existing = conn.execute("""
        SELECT group_id
        FROM data_point_peer_group
        WHERE industry_id = ?
          AND ((company_id = ?) OR (company_id IS NULL AND ? IS NULL))
          AND metric = ?
          AND as_of_date = ?
          AND is_forecast = ?
        ORDER BY group_id
        LIMIT 1
    """, (industry_id, company_id, company_id, metric, as_of, is_forecast)).fetchone()
    if existing:
        group_id = existing["group_id"] if hasattr(existing, "keys") else existing[0]
        conn.execute("""
            UPDATE data_point_peer_group
            SET peer_count = ?,
                peer_median = ?,
                peer_mean = ?,
                peer_std = ?,
                peer_min = ?,
                peer_max = ?,
                computed_at = ?
            WHERE group_id = ?
        """, (n, median, mean, std, pmin, pmax, now, group_id))
        conn.execute("""
            DELETE FROM data_point_peer_group
            WHERE industry_id = ?
              AND ((company_id = ?) OR (company_id IS NULL AND ? IS NULL))
              AND metric = ?
              AND as_of_date = ?
              AND is_forecast = ?
              AND group_id <> ?
        """, (industry_id, company_id, company_id, metric, as_of, is_forecast, group_id))
    else:
        conn.execute("""
            INSERT INTO data_point_peer_group
                (industry_id, company_id, metric, as_of_date, is_forecast,
                 peer_count, peer_median, peer_mean, peer_std, peer_min, peer_max, computed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (industry_id, company_id, metric, as_of, is_forecast,
              n, median, mean, std, pmin, pmax, now))


def _recompute_group(conn: sqlite3.Connection, group_key: Tuple) -> int:
    """重算单个 peer group。返回更新的 data_point 数。

    GOLD 第四次修订:**template_estimate 不进入 peer group 统计**,避免虚假共识。
    - 真 peers (extraction_method != 'template_estimate') 用于 _upsert_peer_group + _classify
    - tpl peers (extraction_method == 'template_estimate') 各自标 孤证 / peer_count = 1
      不参与真共识计算,也不污染真 peers 的 median/std
    """
    peers = _list_peer_data_points(conn, group_key)
    if not peers:
        return 0
    real_peers = [r for r in peers if r["extraction_method"] != "template_estimate"]
    tpl_peers  = [r for r in peers if r["extraction_method"] == "template_estimate"]
    real_values = [r["value_num"] for r in real_peers]

    if real_values:
        _upsert_peer_group(conn, group_key, real_values)

    n_updated = 0
    # 1. 真 peers 按 real_values 分类
    for r in real_peers:
        status, median, std, dev = _classify(r["value_num"], real_values)
        conn.execute("""
            UPDATE industry_data_point
            SET consensus_status = ?,
                peer_count = ?,
                peer_median = ?,
                peer_std = ?,
                deviation_from_median = ?
            WHERE id = ?
        """, (status, len(real_values), median, std, dev, r["id"]))
        n_updated += 1
    # 2. template_estimate peers 全部标 孤证 / peer_count = 1 / 不参与真共识
    for r in tpl_peers:
        conn.execute("""
            UPDATE industry_data_point
            SET consensus_status = '孤证',
                peer_count = 1,
                peer_median = NULL,
                peer_std = NULL,
                deviation_from_median = NULL
            WHERE id = ?
        """, (r["id"],))
        n_updated += 1
    return n_updated


def recompute_after_insert(data_point_id: int, conn: Optional[sqlite3.Connection] = None) -> int:
    """单点插入后重算其 peer group。db_writer.py 用。"""
    own_conn = conn is None
    if own_conn:
        conn = get_db()
    try:
        row = conn.execute("""
            SELECT id, industry_id, company_id, metric, period, as_of_date, is_forecast
            FROM industry_data_point WHERE id = ?
        """, (data_point_id,)).fetchone()
        if not row:
            return 0
        gk = _group_key(row)
        n = _recompute_group(conn, gk)
        if own_conn:
            conn.commit()
        return n
    finally:
        if own_conn:
            conn.close()


def recompute_metric(industry_id: int, metric: str, conn: Optional[sqlite3.Connection] = None) -> int:
    """重算某 industry × metric 的所有 peer group。"""
    own_conn = conn is None
    if own_conn:
        conn = get_db()
    try:
        # 找出该 industry × metric 下所有 distinct (company_id, as_of_date, is_forecast)
        rows = conn.execute("""
            SELECT DISTINCT industry_id, company_id, metric,
                   COALESCE(NULLIF(as_of_date, ''), period) AS as_of,
                   is_forecast
            FROM industry_data_point
            WHERE industry_id = ? AND metric = ? AND value_num IS NOT NULL
        """, (industry_id, metric)).fetchall()
        total = 0
        for r in rows:
            gk = (r["industry_id"], r["company_id"], r["metric"], r["as_of"], r["is_forecast"])
            total += _recompute_group(conn, gk)
        if own_conn:
            conn.commit()
        return total
    finally:
        if own_conn:
            conn.close()


def recompute_all(industry_id: Optional[int] = None, conn: Optional[sqlite3.Connection] = None) -> Tuple[int, int]:
    """全量重算。返回 (peer_group 数, 更新 data_point 数)。"""
    own_conn = conn is None
    if own_conn:
        conn = get_db()
    try:
        sql = """
            SELECT DISTINCT industry_id, company_id, metric,
                   COALESCE(NULLIF(as_of_date, ''), period) AS as_of,
                   is_forecast
            FROM industry_data_point
            WHERE value_num IS NOT NULL
        """
        params = ()
        if industry_id is not None:
            sql += " AND industry_id = ?"
            params = (industry_id,)
        rows = conn.execute(sql, params).fetchall()
        n_groups = 0
        n_dp_updated = 0
        for r in rows:
            gk = (r["industry_id"], r["company_id"], r["metric"], r["as_of"], r["is_forecast"])
            updated = _recompute_group(conn, gk)
            if updated > 0:
                n_groups += 1
                n_dp_updated += updated
        if own_conn:
            conn.commit()
        return (n_groups, n_dp_updated)
    finally:
        if own_conn:
            conn.close()


def main():
    parser = argparse.ArgumentParser(description="多源对照算法 — 重算 consensus_status")
    parser.add_argument("--industry", type=int, default=None, help="可选:仅重算某 industry_id")
    parser.add_argument("--metric", type=str, default=None, help="可选:仅重算某 metric(需配合 --industry)")
    parser.add_argument("--summary", action="store_true", help="完成后打印 consensus 分布")
    args = parser.parse_args()

    conn = get_db()
    if args.metric and args.industry is not None:
        n = recompute_metric(args.industry, args.metric, conn=conn)
        conn.commit()
        print(f"[OK] 重算 industry={args.industry} metric={args.metric}:更新 {n} 个 data_point")
    else:
        n_groups, n_dp = recompute_all(args.industry, conn=conn)
        conn.commit()
        print(f"[OK] 重算 {n_groups} 个 peer group,更新 {n_dp} 个 data_point")

    if args.summary:
        print("\n=== 共识分布 ===")
        for r in conn.execute("SELECT consensus_status, COUNT(*) AS n FROM industry_data_point GROUP BY consensus_status ORDER BY n DESC"):
            print(f"  {r['consensus_status']:8s} : {r['n']:4d}")
        print(f"\n=== peer_group 总数 {conn.execute('SELECT COUNT(*) AS n FROM data_point_peer_group').fetchone()['n']} ===")
        print("=== peer_count 分布(top 10 metric × as_of)===")
        for r in conn.execute("SELECT metric, as_of_date, peer_count FROM data_point_peer_group ORDER BY peer_count DESC LIMIT 10"):
            print(f"  peer={r['peer_count']:2d}  {r['metric']:35s}  {r['as_of_date']}")
    conn.close()


if __name__ == "__main__":
    main()
