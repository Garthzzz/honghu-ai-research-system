from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


def _connect(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def _tables(conn: sqlite3.Connection) -> list[str]:
    return [
        str(row["name"])
        for row in conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        )
    ]


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    escaped = table.replace('"', '""')
    return [str(row["name"]) for row in conn.execute(f'PRAGMA table_info("{escaped}")')]


def _row_count(conn: sqlite3.Connection, table: str) -> int:
    escaped = table.replace('"', '""')
    return int(conn.execute(f'SELECT COUNT(*) FROM "{escaped}"').fetchone()[0])


def compare_databases(
    before_path: Path,
    after_path: Path,
    *,
    allowed_row_count_changes: set[str] | None = None,
) -> dict[str, Any]:
    if not before_path.is_file() or not after_path.is_file():
        raise FileNotFoundError("迁移前后数据库路径都必须存在")
    before = _connect(before_path)
    after = _connect(after_path)
    try:
        before_tables = _tables(before)
        after_tables = _tables(after)
        before_set = set(before_tables)
        after_set = set(after_tables)
        missing_tables = sorted(before_set - after_set)
        new_tables = sorted(after_set - before_set)
        allowed_row_count_changes = allowed_row_count_changes or set()
        row_count_changes: list[dict[str, Any]] = []
        column_changes: dict[str, dict[str, list[str]]] = {}
        for table in sorted(before_set & after_set):
            before_count = _row_count(before, table)
            after_count = _row_count(after, table)
            if before_count != after_count:
                row_count_changes.append(
                    {
                        "table": table,
                        "before": before_count,
                        "after": after_count,
                        "allowed": table in allowed_row_count_changes,
                    }
                )
            before_columns = set(_columns(before, table))
            after_columns = set(_columns(after, table))
            added = sorted(after_columns - before_columns)
            removed = sorted(before_columns - after_columns)
            if added or removed:
                column_changes[table] = {"added": added, "removed": removed}

        integrity = str(after.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_key_issues = [dict(row) for row in after.execute("PRAGMA foreign_key_check")]
        unexpected_row_count_changes = [item for item in row_count_changes if not item["allowed"]]
        passed = (
            not missing_tables
            and not unexpected_row_count_changes
            and integrity == "ok"
            and not foreign_key_issues
        )
        return {
            "passed": passed,
            "before": str(before_path.resolve()),
            "after": str(after_path.resolve()),
            "before_table_count": len(before_tables),
            "after_table_count": len(after_tables),
            "missing_tables": missing_tables,
            "new_tables": new_tables,
            "row_count_changes": row_count_changes,
            "unexpected_row_count_changes": unexpected_row_count_changes,
            "column_changes": column_changes,
            "integrity_check": integrity,
            "foreign_key_issues": foreign_key_issues,
        }
    finally:
        before.close()
        after.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="只读比较 SQLite 迁移前后结构和数据完整性")
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--allow-row-count-change",
        action="append",
        default=[],
        metavar="TABLE",
        help="显式允许行数变化的元数据/迁移记录表；可重复使用",
    )
    args = parser.parse_args()
    result = compare_databases(
        args.before,
        args.after,
        allowed_row_count_changes=set(args.allow_row_count_change),
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
