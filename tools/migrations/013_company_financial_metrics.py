#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""公司六项核心财务指标字段迁移。

本迁移只扩展 ``company`` 兼容聚合层；每次真实刷新仍必须同时通过
``tools.pipeline.db_writer.write_data_point`` 写入可溯源的
``industry_data_point`` 原子。

安全约定：

* 默认仅验证，不写数据库；显式 ``--apply`` 才执行 ALTER。
* 可用 ``--db`` 指向临时数据库完成迁移和 ``foreign_key_check`` 后，再由
  获得授权的执行流程作用于 live 库。
* 迁移幂等，不回填、不猜测任何历史 EPS/BPS 或来源。
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = ROOT / "data" / "research.db"

COMPANY_FINANCIAL_COLUMNS: tuple[tuple[str, str], ...] = (
    ("eps_ttm", "REAL"),
    ("bps_mrq", "REAL"),
    ("per_share_currency", "TEXT"),
    ("financial_metrics_as_of", "TEXT"),
    ("financial_metrics_source_id", "INTEGER REFERENCES source(id)"),
)
FINANCIAL_SOURCE_INDEX = "idx_company_financial_metrics_source"


def columns_of(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")')}


def migrate(conn: sqlite3.Connection) -> list[str]:
    """幂等添加字段并返回本次实际新增列名。"""
    tables = {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    missing_tables = sorted({"company", "source"} - tables)
    if missing_tables:
        raise RuntimeError("缺少迁移依赖表：" + ", ".join(missing_tables))
    existing = columns_of(conn, "company")
    added: list[str] = []
    for name, declaration in COMPANY_FINANCIAL_COLUMNS:
        if name in existing:
            continue
        conn.execute(f'ALTER TABLE company ADD COLUMN "{name}" {declaration}')
        added.append(name)
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS {FINANCIAL_SOURCE_INDEX} "
        "ON company(financial_metrics_source_id)"
    )
    return added


def verify(conn: sqlite3.Connection) -> None:
    cols = columns_of(conn, "company")
    missing = [name for name, _ in COMPANY_FINANCIAL_COLUMNS if name not in cols]
    if missing:
        raise RuntimeError(f"013 迁移字段缺失：{', '.join(missing)}")
    source_foreign_keys = {
        str(row[3])
        for row in conn.execute("PRAGMA foreign_key_list(company)")
        if str(row[2]) == "source"
    }
    if "financial_metrics_source_id" not in source_foreign_keys:
        raise RuntimeError("financial_metrics_source_id 缺少 source(id) 外键")
    index = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
        (FINANCIAL_SOURCE_INDEX,),
    ).fetchone()
    if index is None:
        raise RuntimeError(f"013 迁移索引缺失：{FINANCIAL_SOURCE_INDEX}")
    violations = list(conn.execute("PRAGMA foreign_key_check"))
    if violations:
        raise RuntimeError(f"foreign_key_check 失败：{len(violations)} 条")


def _connect(path: Path, *, writable: bool) -> sqlite3.Connection:
    if writable:
        conn = sqlite3.connect(str(path))
    else:
        conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _column_names(items: Iterable[tuple[str, str]]) -> str:
    return ", ".join(name for name, _ in items)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="显式执行迁移；省略时仅验证目标库是否已包含字段。",
    )
    args = parser.parse_args(argv)
    db_path = args.db.resolve()
    if not db_path.exists():
        parser.error(f"数据库不存在：{db_path}")

    conn = _connect(db_path, writable=args.apply)
    try:
        if args.apply:
            before_count = conn.execute("SELECT COUNT(*) FROM company").fetchone()[0]
            conn.execute("BEGIN IMMEDIATE")
            added = migrate(conn)
            verify(conn)
            after_count = conn.execute("SELECT COUNT(*) FROM company").fetchone()[0]
            if before_count != after_count:
                raise RuntimeError(
                    f"company 行数发生变化：{before_count} -> {after_count}"
                )
            conn.commit()
            print(f"013 migration applied: added={added or 'none'} rows={after_count}")
        else:
            verify(conn)
            print(
                "013 migration verified: "
                + _column_names(COMPANY_FINANCIAL_COLUMNS)
            )
        return 0
    except Exception:
        if args.apply:
            conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
