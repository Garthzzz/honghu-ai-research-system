from __future__ import annotations

import json
import sqlite3

import pytest

from tools.data_platform.domain_data import _sha256_json
from tools.data_platform.sentiment_projection import (
    PersistentSentimentConnection,
    PersistentSentimentProjection,
    SentimentProjectionError,
    _InterprocessLock,
    _create_projection_schema,
)


SCHEMAS = {
    "sample": {
        "database": "sentiment.db",
        "columns": [
            {"cid": 0, "name": "id", "type": "INTEGER", "pk": 1},
            {"cid": 1, "name": "name", "type": "TEXT", "pk": 0},
        ],
        "primary": [{"cid": 0, "name": "id", "type": "INTEGER", "pk": 1}],
        "indexes": [],
    }
}


def test_contending_projection_lock_waits_and_fails_with_domain_error(tmp_path) -> None:
    path = tmp_path / "projection.lock"
    first = _InterprocessLock(path, timeout_seconds=0.1)
    second = _InterprocessLock(path, timeout_seconds=0.1)
    first.acquire()
    try:
        with pytest.raises(SentimentProjectionError, match="timed out waiting"):
            second.acquire()
    finally:
        first.release()


class _Lock:
    def __init__(self) -> None:
        self.released = False

    def release(self) -> None:
        self.released = True


class _Cursor:
    def __init__(self, value) -> None:
        self.value = value

    def fetchone(self):
        return self.value


class _Writer:
    def __init__(self, attempts, *, fail: bool = False) -> None:
        self.attempts = attempts
        self.fail = fail

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, _sql, params):
        self.attempts.append(params)
        if self.fail:
            raise OSError("response lost")
        return _Cursor(({"ok": True},))


def _connection(tmp_path, factory):
    path = tmp_path / "projection.db"
    raw = sqlite3.connect(path)
    raw.row_factory = sqlite3.Row
    _create_projection_schema(raw, SCHEMAS)
    raw.execute("INSERT INTO sample VALUES(1,'before')")
    row_sha = _sha256_json({"id": 1, "name": "before"})
    raw.execute(
        "INSERT INTO __honghu_record_state VALUES(?,?,?,?,?,?,?)",
        ("sentiment.db", "sample", _sha256_json([["id", 1]]), 1, 0, row_sha, 1),
    )
    raw.commit()
    lock = _Lock()
    wrapped = PersistentSentimentConnection(
        raw,
        lock,  # type: ignore[arg-type]
        factory,
        SCHEMAS,
        writer_identity="honghu_writer_sentiment_analytics",
        operation_scope="window",
        operation_id="window-1",
        actor="principal:test",
    )
    return wrapped, lock


def test_persistent_sentiment_projection_tracks_only_real_changes(tmp_path) -> None:
    attempts = []
    connection, lock = _connection(tmp_path, lambda: _Writer(attempts))

    ignored = connection.execute("INSERT OR IGNORE INTO sample VALUES(1,'ignored')")
    assert ignored.rowcount == 0
    connection.commit()
    assert attempts == []

    connection.execute("UPDATE sample SET name='after' WHERE id=1")
    connection.commit()
    assert len(attempts) == 1
    mutation = json.loads(attempts[0][4])[0]
    assert mutation["expected_revision"] == 1
    assert mutation["payload"] == {"id": 1, "name": "after"}

    connection.execute("DELETE FROM sample WHERE id=1")
    connection.commit()
    mutation = json.loads(attempts[1][4])[0]
    assert mutation["expected_revision"] == 2
    assert mutation["delete"] is True
    assert mutation["payload"] == {"id": 1, "name": "after"}
    connection.close()
    assert lock.released is True


def test_persistent_sentiment_projection_reuses_uncertain_batch(tmp_path) -> None:
    attempts = []
    fail = [True]

    def factory():
        return _Writer(attempts, fail=bool(fail.pop(0)) if fail else False)

    connection, _lock = _connection(tmp_path, factory)
    connection.execute("UPDATE sample SET name='uncertain' WHERE id=1")
    with pytest.raises(SentimentProjectionError, match="uncertain"):
        connection.commit()
    with pytest.raises(SentimentProjectionError, match="cannot be locally rolled back"):
        connection.rollback()
    connection.commit()
    assert len(attempts) == 2
    assert attempts[0][2:5] == attempts[1][2:5]
    connection.close()


def test_persistent_sentiment_insert_then_delete_is_a_net_noop(tmp_path) -> None:
    attempts = []
    connection, _lock = _connection(tmp_path, lambda: _Writer(attempts))
    connection.execute("INSERT INTO sample VALUES(2,'temporary')")
    connection.execute("DELETE FROM sample WHERE id=2")
    connection.commit()
    assert attempts == []
    connection.close()


def test_persistent_sentiment_projection_rejects_primary_key_mutation(tmp_path) -> None:
    connection, _lock = _connection(tmp_path, lambda: _Writer([]))
    with pytest.raises(sqlite3.IntegrityError, match="primary-key mutation"):
        connection.execute("UPDATE sample SET id=2 WHERE id=1")
    connection.rollback()
    connection.close()


def test_persistent_sentiment_projection_attaches_as_readonly_dependency(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projection = PersistentSentimentProjection(tmp_path, lambda: None)
    source = sqlite3.connect(projection.database_path)
    _create_projection_schema(source, SCHEMAS)
    source.execute("INSERT INTO sample VALUES(1,'from-postgresql-projection')")
    source.execute(
        "INSERT INTO __honghu_projection_meta VALUES(1,?,?,?,?,?)",
        ("formal", "overlay", "{}", 1, "2026-08-15T00:00:00Z"),
    )
    source.commit()
    source.close()
    monkeypatch.setattr(
        projection,
        "ensure_current_locked",
        lambda: {"schemas": SCHEMAS},
    )
    consumer = sqlite3.connect(
        "file:sentiment_dependency_test?mode=memory&cache=private", uri=True
    )
    projection.attach(consumer)
    assert consumer.execute("SELECT name FROM sample WHERE id=1").fetchone()[0] == (
        "from-postgresql-projection"
    )
    with pytest.raises(sqlite3.OperationalError):
        consumer.execute("UPDATE sample SET name='forbidden' WHERE id=1")
    consumer.close()


def test_persistent_sentiment_reader_is_file_readonly_before_router_fence(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projection = PersistentSentimentProjection(tmp_path, lambda: None)
    source = sqlite3.connect(projection.database_path)
    _create_projection_schema(source, SCHEMAS)
    source.execute("INSERT INTO sample VALUES(1,'from-postgresql-projection')")
    source.execute(
        "INSERT INTO __honghu_projection_meta VALUES(1,?,?,?,?,?)",
        ("formal", "overlay", "{}", 1, "2026-08-15T00:00:00Z"),
    )
    source.commit()
    source.close()
    monkeypatch.setattr(projection, "ensure_current_locked", lambda: {"schemas": SCHEMAS})

    connection = projection.connect_readonly(finalize_readonly=False)
    try:
        # TEMP dependency assembly remains possible, while the main database
        # is already protected by its read-only URI.
        connection.execute("CREATE TEMP VIEW dependency_probe AS SELECT 1 AS ok")
        assert connection.execute("SELECT ok FROM dependency_probe").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("UPDATE sample SET name='forbidden' WHERE id=1")
    finally:
        connection.close()
