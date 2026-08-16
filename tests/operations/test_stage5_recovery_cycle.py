from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from tools.operations import stage5_recovery_cycle as cycle


NOW = datetime(2026, 8, 16, 10, 0, tzinfo=timezone.utc)
SEGMENT = "00000001000000000000000A"


class _Cursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _Connection:
    def __init__(self, row):
        self.row = row
        self.closed = False
        self.autocommit = False
        self.queries: list[str] = []

    def execute(self, sql):
        self.queries.append(" ".join(sql.split()))
        return _Cursor(self.row if "clock_timestamp" in sql else ("0/1",))

    def close(self):
        self.closed = True


def test_cycle_rotates_wal_and_publishes_verified_target(tmp_path, monkeypatch):
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / SEGMENT).write_bytes(b"wal")
    connection = _Connection((NOW, "0/A000100", SEGMENT))
    monkeypatch.setattr(cycle, "load_postgres_runtime_catalog", lambda _: object())
    observed = {}

    def fake_sync(**kwargs):
        observed.update(kwargs)
        return {
            "latest_recoverable_at_utc": NOW.isoformat(),
            "manifest_identity_sha256": "a" * 64,
            "storage": {"derived_storage_identity": "b" * 64},
            "at_rest_encryption": {"status": "verified", "verified": True},
        }

    monkeypatch.setattr(cycle, "sync_archived_wal", fake_sync)
    result = cycle.run_cycle(
        runtime_catalog=tmp_path / "runtime.json",
        source_archive=archive,
        destination=tmp_path / "offvm",
        expected_storage_identity="b" * 64,
        at_rest_encryption_evidence={"status": "verified"},
        wal_segment_size_bytes=3,
        connection_factory=lambda: connection,
    )
    assert result["status"] == "pass"
    assert result["formal_business_data_written"] is False
    assert observed["target_wal_segment"] == SEGMENT
    assert observed["recoverable_target_at"] == NOW
    assert any("pg_switch_wal" in query for query in connection.queries)
    assert connection.closed is True


def test_cycle_fails_when_archived_segment_is_incomplete(tmp_path, monkeypatch):
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / SEGMENT).write_bytes(b"short")
    connection = _Connection((NOW, "0/A000100", SEGMENT))
    monkeypatch.setattr(cycle, "load_postgres_runtime_catalog", lambda _: object())
    with pytest.raises(cycle.RecoveryCycleError, match="not completely archived"):
        cycle.run_cycle(
            runtime_catalog=tmp_path / "runtime.json",
            source_archive=archive,
            destination=tmp_path / "offvm",
            expected_storage_identity="b" * 64,
            at_rest_encryption_evidence={"status": "verified"},
            wal_segment_size_bytes=16,
            timeout_seconds=0,
            connection_factory=lambda: connection,
        )


def test_invalid_postgresql_wal_identity_fails_closed(tmp_path, monkeypatch):
    archive = tmp_path / "archive"
    archive.mkdir()
    connection = _Connection((NOW, "0/A000100", "not-a-wal"))
    monkeypatch.setattr(cycle, "load_postgres_runtime_catalog", lambda _: object())
    with pytest.raises(cycle.RecoveryCycleError, match="invalid WAL"):
        cycle.run_cycle(
            runtime_catalog=tmp_path / "runtime.json",
            source_archive=archive,
            destination=tmp_path / "offvm",
            expected_storage_identity="b" * 64,
            at_rest_encryption_evidence={"status": "verified"},
            timeout_seconds=0,
            connection_factory=lambda: connection,
        )
