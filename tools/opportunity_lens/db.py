from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .constants import DB_PATH


def connect(db_path: str | Path = DB_PATH, readonly: bool = False) -> sqlite3.Connection:
    path = Path(db_path)
    if readonly:
        uri = f"file:{path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def execute_schema(conn: sqlite3.Connection) -> None:
    schema_path = Path(__file__).with_name("schema.sql")
    conn.executescript(schema_path.read_text(encoding="utf-8"))


def dict_row(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def dict_rows(rows) -> list[dict]:
    return [dict_row(r) for r in rows]


def table_names(conn: sqlite3.Connection) -> list[str]:
    return [
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'opportunity_%' ORDER BY name"
        )
    ]


def table_counts(conn: sqlite3.Connection, tables: list[str] | None = None) -> dict[str, int]:
    names = tables or table_names(conn)
    return {name: int(conn.execute(f"SELECT COUNT(*) AS n FROM {name}").fetchone()["n"]) for name in names}


def object_uri(object_type: str, object_id: int) -> str:
    return f"opp://{object_type}/{int(object_id)}"
