from __future__ import annotations

"""为 A/B source 增加研报/网络独立渠道标记；历史行只做可回滚分类补录。"""

import argparse
import json
import sqlite3
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "research.db"


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def apply(conn: sqlite3.Connection) -> dict[str, int]:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(source)")}
    if "source_channel" not in columns:
        conn.execute(
            "ALTER TABLE source ADD COLUMN source_channel TEXT NOT NULL DEFAULT 'legacy_unspecified' "
            "CHECK(source_channel IN ('report','web','legacy_unspecified'))"
        )
    conn.execute(
        "UPDATE source SET source_channel='report' "
        "WHERE source_channel='legacy_unspecified' AND file_path IS NOT NULL AND trim(file_path)<>''"
    )
    conn.execute(
        "UPDATE source SET source_channel='web' "
        "WHERE source_channel='legacy_unspecified' AND (source_url IS NOT NULL OR url IS NOT NULL)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_source_channel ON source(source_channel)")
    return {
        str(row["source_channel"]): int(row["n"])
        for row in conn.execute("SELECT source_channel,count(*) n FROM source GROUP BY source_channel")
    }


def verify(path: Path) -> dict[str, object]:
    conn = _connect(path)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(source)")}
        counts = {
            str(row["source_channel"]): int(row["n"])
            for row in conn.execute("SELECT source_channel,count(*) n FROM source GROUP BY source_channel")
        } if "source_channel" in columns else {}
        return {
            "source_channel_column": "source_channel" in columns,
            "counts": counts,
            "integrity_check": conn.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_issues": len(list(conn.execute("PRAGMA foreign_key_check"))),
        }
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-live", action="store_true")
    args = parser.parse_args(argv)
    target = args.db.resolve()
    if args.apply:
        if target == DEFAULT_DB.resolve() and not args.confirm_live:
            parser.error("写 live research.db 必须给出 --confirm-live")
        conn = _connect(target)
        try:
            conn.execute("BEGIN IMMEDIATE")
            counts = apply(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        result = {"database": str(target), "counts": counts, "verification": verify(target)}
    else:
        with tempfile.TemporaryDirectory(prefix="source_channel_migration_") as td:
            temp = Path(td) / "research.db"
            source_conn = sqlite3.connect(f"file:{target.as_posix()}?mode=ro", uri=True)
            destination_conn = sqlite3.connect(str(temp))
            try:
                source_conn.backup(destination_conn)
            finally:
                destination_conn.close()
                source_conn.close()
            conn = _connect(temp)
            try:
                conn.execute("BEGIN IMMEDIATE")
                counts = apply(conn)
                conn.commit()
            finally:
                conn.close()
            result = {"database": "temporary_validation", "counts": counts, "verification": verify(temp)}
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
