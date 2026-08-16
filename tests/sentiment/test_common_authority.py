from __future__ import annotations

import sqlite3

from tools.data_platform import shared_identity
from tools.sentiment import common


def test_research_read_uses_current_shared_identity_authority(monkeypatch) -> None:
    sentinel = object()
    monkeypatch.setattr(
        shared_identity,
        "connect_shared_identity_database",
        lambda path: sentinel,
    )
    assert common.research_ro_conn() is sentinel


def test_sentiment_postgresql_adapter_uses_unit_authority_not_file_path() -> None:
    class PostgreSQLCompatibility:
        unit = "sentiment_analytics"

        def execute(self, _sql: str):
            raise AssertionError("legacy SQLite file-path probe must not run")

    connection = PostgreSQLCompatibility()
    common.assert_senti_only(connection)  # type: ignore[arg-type]
    common.attach_research_ro(connection)  # type: ignore[arg-type]


def test_sentiment_sqlite_path_guard_remains_fail_closed(tmp_path) -> None:
    wrong = sqlite3.connect(tmp_path / "research.db")
    try:
        try:
            common.assert_senti_only(wrong)
        except RuntimeError as exc:
            assert "门C" in str(exc)
        else:
            raise AssertionError("non-sentiment SQLite writer was accepted")
    finally:
        wrong.close()
