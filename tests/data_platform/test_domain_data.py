from __future__ import annotations

import base64
import hashlib
import json

import pytest

from tools.data_platform.domain_data import (
    DomainDataError,
    DomainDataWriterFenced,
    MAX_IN_MEMORY_COMPATIBILITY_ROWS,
    PostgresDomainCompatibilityConnection,
    PostgresDomainReadCache,
    connect_domain_database,
)
from tools.data_platform.local_authority_fence import write_authority_fence


class _Cursor:
    def __init__(self, *, one=None, rows=None):
        self._one = one
        self._rows = rows or []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._rows


class _Connection:
    def __init__(self, *, state="S3", backend="postgresql_production"):
        self.state = state
        self.backend = backend
        self.closed = False
        self.watermark = {
            "tables": [
                {
                    "source_database": "research.db",
                    "source_table": "sample",
                    "schema": {
                        "columns": [
                            {"cid": 0, "name": "id", "type": "INTEGER", "pk": 1},
                            {"cid": 1, "name": "name", "type": "TEXT", "pk": 0},
                            {"cid": 2, "name": "raw", "type": "BLOB", "pk": 0},
                        ]
                    },
                }
            ]
        }

    def execute(self, sql, _params=None):
        if "unit_runtime_contract_v1" in sql:
            return _Cursor(
                one=(
                    self.state,
                    self.backend,
                    3,
                    "epoch",
                    "snapshot",
                    "a" * 64,
                    "b" * 64,
                    2,
                    self.watermark,
                    1,
                    1,
                    2,
                    "2026-08-15T00:00:00+00:00",
                )
            )
        assert "read_unit_records_v1" in sql
        return _Cursor(
            rows=[
                (
                    "research.db",
                    "sample",
                    1,
                    "key-1",
                    "c" * 64,
                    {"id": 1, "name": "formal", "raw": {"$binary_base64": base64.b64encode(b"x").decode()}},
                    1,
                    False,
                ),
                (
                    "research.db",
                    "sample",
                    2,
                    "key-2",
                    "d" * 64,
                    {"id": 2, "name": "deleted", "raw": None},
                    2,
                    True,
                ),
            ]
        )

    def close(self):
        self.closed = True


def test_domain_cache_projects_formal_baseline_and_overlay_without_deleted_rows() -> None:
    connection = _Connection()
    cache = PostgresDomainReadCache("research_publication", lambda: connection)
    sqlite = cache.connect()
    row = sqlite.execute("SELECT id,name,raw FROM sample").fetchone()
    assert tuple(row) == (1, "formal", b"x")
    assert sqlite.execute("SELECT count(*) FROM sample").fetchone()[0] == 1
    with pytest.raises(Exception):
        sqlite.execute("INSERT INTO sample VALUES (3,'forbidden',NULL)")
    assert connection.closed is True
    cache.close()


@pytest.mark.parametrize(
    ("state", "backend"),
    [("S1", "sqlite_transition"), ("S3", "sqlite_transition")],
)
def test_domain_cache_fails_closed_without_postgresql_authority(state, backend) -> None:
    cache = PostgresDomainReadCache(
        "research_publication", lambda: _Connection(state=state, backend=backend)
    )
    with pytest.raises(DomainDataError, match="not authoritative"):
        cache.connect()


def _row_key(identifier: int) -> str:
    payload = [["id", identifier]]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class _WriterReadConnection:
    def __init__(self):
        self.closed = False
        self.watermark = {
            "tables": [
                {
                    "source_database": "research.db",
                    "source_table": "sample",
                    "schema": {
                        "columns": [
                            {"cid": 0, "name": "id", "type": "INTEGER", "pk": 1},
                            {"cid": 1, "name": "name", "type": "TEXT", "pk": 0},
                        ]
                    },
                }
            ]
        }

    def execute(self, sql, _params=None):
        if "unit_runtime_contract_v1" in sql:
            return _Cursor(
                one=(
                    "S3",
                    "postgresql_production",
                    "honghu_writer_research_publication",
                    self.watermark,
                    1,
                )
            )
        assert "read_unit_records_v1" in sql
        return _Cursor(
            rows=[
                (
                    "research.db",
                    "sample",
                    1,
                    _row_key(1),
                    "c" * 64,
                    {"id": 1, "name": "before"},
                    1,
                    False,
                )
            ]
        )

    def close(self):
        self.closed = True


class _WriterConnection:
    def __init__(self, calls, *, fail=False):
        self.calls = calls
        self.fail = fail

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params):
        if self.fail:
            raise OSError("response lost")
        self.calls.append((sql, params))
        return _Cursor(one=({"mutation_count": len(json.loads(params[4]))},))


def test_compatibility_connection_commits_one_idempotent_postgresql_batch() -> None:
    calls = []
    connection = PostgresDomainCompatibilityConnection(
        "research_publication",
        _WriterReadConnection,
        lambda: _WriterConnection(calls),
        owned_objects=frozenset({("research.db", "sample")}),
        writer_identity="honghu_writer_research_publication",
        operation_scope="publication",
        operation_id="release-123",
        actor="authenticated:analyst",
    )
    connection.execute("UPDATE sample SET name='after' WHERE id=1")
    connection.execute("INSERT INTO sample(id,name) VALUES(2,'new')")
    connection.commit()
    assert len(calls) == 1
    params = calls[0][1]
    assert params[0:3] == (
        "research_publication",
        "publication",
        "release-123:00000001",
    )
    mutations = json.loads(params[4])
    assert [(item["expected_revision"], item["delete"]) for item in mutations] == [
        (1, False),
        (0, False),
    ]
    assert all(len(item["request_sha256"]) == 64 for item in mutations)
    connection.execute("DELETE FROM sample WHERE id=1")
    connection.commit()
    assert json.loads(calls[1][1][4])[0]["delete"] is True
    assert calls[1][1][2] == "release-123:00000002"
    connection.close()


def test_compatibility_connection_requires_stable_operation_identity() -> None:
    with pytest.raises(DomainDataWriterFenced, match="stable operation identity"):
        PostgresDomainCompatibilityConnection(
            "research_publication",
            _WriterReadConnection,
            lambda: _WriterConnection([]),
            owned_objects=frozenset({("research.db", "sample")}),
            writer_identity="honghu_writer_research_publication",
            operation_scope="publication",
            operation_id="",
            actor="authenticated:analyst",
        )


def test_uncertain_postgresql_response_fails_closed() -> None:
    connection = PostgresDomainCompatibilityConnection(
        "research_publication",
        _WriterReadConnection,
        lambda: _WriterConnection([], fail=True),
        owned_objects=frozenset({("research.db", "sample")}),
        writer_identity="honghu_writer_research_publication",
        operation_scope="publication",
        operation_id="release-uncertain",
        actor="authenticated:analyst",
    )
    connection.execute("UPDATE sample SET name='uncertain' WHERE id=1")
    with pytest.raises(DomainDataError, match="uncertain"):
        connection.commit()
    connection.close()


def test_uncertain_postgresql_response_reuses_exact_batch_identity() -> None:
    calls = []
    attempts = []

    class UncertainThenReplay(_WriterConnection):
        def execute(self, sql, params):
            attempts.append((sql, params))
            if len(attempts) == 1:
                raise OSError("commit response lost")
            calls.append((sql, params))
            return _Cursor(one=({"mutation_count": len(json.loads(params[4]))},))

    connection = PostgresDomainCompatibilityConnection(
        "research_publication",
        _WriterReadConnection,
        lambda: UncertainThenReplay(calls),
        owned_objects=frozenset({("research.db", "sample")}),
        writer_identity="honghu_writer_research_publication",
        operation_scope="publication",
        operation_id="release-replay",
        actor="authenticated:analyst",
    )
    connection.execute("UPDATE sample SET name='after-uncertain' WHERE id=1")
    with pytest.raises(DomainDataError, match="uncertain"):
        connection.commit()
    with pytest.raises(DomainDataError, match="cannot prove"):
        connection.rollback()
    connection.commit()

    assert len(attempts) == 2
    assert attempts[0][1][2] == attempts[1][1][2] == "release-replay:00000001"
    assert attempts[0][1][3] == attempts[1][1][3]
    assert attempts[0][1][4] == attempts[1][1][4]
    connection.close()


def test_uncertain_postgresql_response_rejects_changed_local_state() -> None:
    connection = PostgresDomainCompatibilityConnection(
        "research_publication",
        _WriterReadConnection,
        lambda: _WriterConnection([], fail=True),
        owned_objects=frozenset({("research.db", "sample")}),
        writer_identity="honghu_writer_research_publication",
        operation_scope="publication",
        operation_id="release-mutated-after-uncertain",
        actor="authenticated:analyst",
    )
    connection.execute("UPDATE sample SET name='first-state' WHERE id=1")
    with pytest.raises(DomainDataError, match="uncertain"):
        connection.commit()
    connection.execute("UPDATE sample SET name='different-state' WHERE id=1")
    with pytest.raises(DomainDataError, match="state changed"):
        connection.commit()
    connection.close()


def test_compatibility_connection_recreates_a_tombstone_at_next_revision() -> None:
    class TombstoneRead(_WriterReadConnection):
        def execute(self, sql, _params=None):
            if "unit_runtime_contract_v1" in sql:
                return _Cursor(
                    one=(
                        "S3",
                        "postgresql_production",
                        "honghu_writer_research_publication",
                        self.watermark,
                        1,
                    )
                )
            return _Cursor(
                rows=[
                    (
                        "research.db",
                        "sample",
                        1,
                        _row_key(1),
                        "c" * 64,
                        {"id": 1, "name": "deleted"},
                        4,
                        True,
                    )
                ]
            )

    calls = []
    connection = PostgresDomainCompatibilityConnection(
        "research_publication",
        TombstoneRead,
        lambda: _WriterConnection(calls),
        owned_objects=frozenset({("research.db", "sample")}),
        writer_identity="honghu_writer_research_publication",
        operation_scope="publication",
        operation_id="recreate-1",
        actor="authenticated:analyst",
    )
    connection.execute("INSERT INTO sample(id,name) VALUES(1,'restored')")
    connection.commit()
    assert json.loads(calls[0][1][4])[0]["expected_revision"] == 4
    connection.close()


def test_large_unit_writer_requires_a_separate_persistent_adapter() -> None:
    class LargeRead(_WriterReadConnection):
        def execute(self, sql, _params=None):
            if "unit_runtime_contract_v1" in sql:
                return _Cursor(
                    one=(
                        "S3",
                        "postgresql_production",
                        "honghu_writer_research_publication",
                        self.watermark,
                        MAX_IN_MEMORY_COMPATIBILITY_ROWS + 1,
                    )
                )
            return super().execute(sql, _params)

    with pytest.raises(DomainDataWriterFenced, match="persistent unit adapter"):
        PostgresDomainCompatibilityConnection(
            "research_publication",
            LargeRead,
            lambda: _WriterConnection([]),
            owned_objects=frozenset({("research.db", "sample")}),
            writer_identity="honghu_writer_research_publication",
            operation_scope="publication",
            operation_id="large-1",
            actor="authenticated:analyst",
        )


def test_large_unit_reader_requires_a_persistent_projection() -> None:
    class LargeRead(_Connection):
        def execute(self, sql, params=None):
            cursor = super().execute(sql, params)
            if "unit_runtime_contract_v1" in sql:
                row = list(cursor.fetchone())
                row[7] = MAX_IN_MEMORY_COMPATIBILITY_ROWS + 1
                return _Cursor(one=tuple(row))
            raise AssertionError("large read must fail before record materialization")

    cache = PostgresDomainReadCache("sentiment_analytics", LargeRead)
    with pytest.raises(DomainDataError, match="persistent unit projection"):
        cache.connect()


def test_local_s3_fence_blocks_sqlite_writer_without_runtime_matrix(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HONGHU_POSTGRES_RUNTIME_CONFIG", raising=False)
    monkeypatch.delenv("HONGHU_CUTOVER_UNIT_REGISTRY", raising=False)
    database = tmp_path / "research.db"
    database.touch()
    write_authority_fence(
        tmp_path,
        cutover_unit="research_publication",
        authority_state="S3",
        authoritative_backend="postgresql_production",
        authority_evidence_sha256="a" * 64,
        approval_reference="user-approved",
        cutover_epoch="epoch-1",
    )
    with pytest.raises(Exception, match="SQLite writer is retired"):
        connect_domain_database(
            "research_publication", database, readonly=False
        )
