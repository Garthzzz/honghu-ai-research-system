#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""修正两项经当前官方/提供商核验的上市身份状态。

* 双鸿（3324）在台湾柜买市场交易，Yahoo Finance 当前标识为 ``3324.TWO``；
  旧 ``3324.TW`` 返回空对象，导致股价和财务长期不更新。
* 新光电气 / SHINKO ELECTRIC（6967.T）已由公司官方公告于 2025-06-06
  从东京证券交易所退市，不能继续作为当前上市行情抓取失败项。

本迁移只在 id、名称和旧 ticker 全部命中时更新；默认只验证，显式 ``--apply``
才写入。写默认 live research.db 还必须加 ``--confirm-live``。
"""
from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = ROOT / "data" / "research.db"


@dataclass(frozen=True)
class Correction:
    company_id: int
    name: str
    old_ticker: str
    new_ticker: str
    new_listing_status: str
    new_market: str
    new_display_mode: str


CORRECTIONS = (
    Correction(262, "双鸿", "3324.TW", "3324.TWO", "other_listed", "其他", "quantitative"),
    Correction(598, "新光电气", "6967.T", "6967.T", "delisted", "其他", "qualitative_only"),
)


def _connect(path: Path, *, writable: bool) -> sqlite3.Connection:
    if writable:
        conn = sqlite3.connect(str(path))
    else:
        conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
        conn.execute("PRAGMA query_only=ON")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _row(conn: sqlite3.Connection, correction: Correction) -> sqlite3.Row:
    row = conn.execute(
        "SELECT id,name,ticker,listing_status,market,display_mode FROM company WHERE id=?",
        (correction.company_id,),
    ).fetchone()
    if row is None or row["name"] != correction.name:
        raise RuntimeError(
            f"company_id={correction.company_id} 名称前置条件不一致；拒绝猜测身份"
        )
    return row


def apply(conn: sqlite3.Connection) -> int:
    updated = 0
    for item in CORRECTIONS:
        row = _row(conn, item)
        final = (
            item.new_ticker,
            item.new_listing_status,
            item.new_market,
            item.new_display_mode,
        )
        current = (row["ticker"], row["listing_status"], row["market"], row["display_mode"])
        if current == final:
            continue
        if row["ticker"] != item.old_ticker:
            raise RuntimeError(
                f"company_id={item.company_id} 旧 ticker={row['ticker']!r}，"
                f"预期 {item.old_ticker!r}；拒绝覆盖"
            )
        cursor = conn.execute(
            """UPDATE company
               SET ticker=?,listing_status=?,market=?,display_mode=?
               WHERE id=? AND name=? AND ticker=?""",
            (*final, item.company_id, item.name, item.old_ticker),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"company_id={item.company_id} 更新前置条件失效")
        updated += 1
    return updated


def verify(conn: sqlite3.Connection) -> None:
    for item in CORRECTIONS:
        row = _row(conn, item)
        current = (row["ticker"], row["listing_status"], row["market"], row["display_mode"])
        expected = (
            item.new_ticker,
            item.new_listing_status,
            item.new_market,
            item.new_display_mode,
        )
        if current != expected:
            raise RuntimeError(f"company_id={item.company_id} 身份修正尚未应用：{current}")
    violations = list(conn.execute("PRAGMA foreign_key_check"))
    if violations:
        raise RuntimeError(f"foreign_key_check 失败：{len(violations)} 条")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-live", action="store_true")
    args = parser.parse_args(argv)
    path = args.db.resolve()
    if not path.exists():
        parser.error(f"数据库不存在：{path}")
    if args.apply and path == DEFAULT_DB.resolve() and not args.confirm_live:
        parser.error("写默认 live research.db 必须显式 --confirm-live")
    conn = _connect(path, writable=args.apply)
    try:
        if args.apply:
            before = conn.execute("SELECT COUNT(*) FROM company").fetchone()[0]
            conn.execute("BEGIN IMMEDIATE")
            updated = apply(conn)
            verify(conn)
            after = conn.execute("SELECT COUNT(*) FROM company").fetchone()[0]
            if before != after:
                raise RuntimeError(f"company 行数变化：{before}->{after}")
            conn.commit()
            print(f"014 identity corrections applied: updated={updated} rows={after}")
        else:
            verify(conn)
            print("014 identity corrections verified")
        return 0
    except Exception:
        if args.apply:
            conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
