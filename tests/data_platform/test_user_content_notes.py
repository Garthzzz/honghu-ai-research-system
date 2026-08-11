from __future__ import annotations

import sqlite3

import pytest

from tools.data_platform.routing import AuthorityState, Backend, CutoverRoute
from tools.data_platform.user_content_notes import (
    AnalystNoteCapabilityUnavailable,
    AnalystNoteMutation,
    AnalystNoteWriterFenced,
    SQLiteAnalystNoteRepository,
    build_analyst_note_repository,
    canonical_request_hash,
)


def _route(*, writer_enabled: bool = True) -> CutoverRoute:
    return CutoverRoute(
        cutover_unit="user_content_notes",
        backend=Backend.SQLITE_TRANSITION,
        writer_operation="analyst_note_mutation",
        transaction_boundary="one note mutation",
        authority_state=AuthorityState.S0,
        sqlite_writer_enabled=writer_enabled,
    )


def _factory(path):
    def connect() -> sqlite3.Connection:
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        return connection

    return connect


def _schema(path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE analyst_note(
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   entity_type TEXT NOT NULL,
                   entity_id INTEGER NOT NULL,
                   q_number TEXT,
                   note_type TEXT NOT NULL DEFAULT 'general',
                   title TEXT,
                   content TEXT NOT NULL,
                   author TEXT NOT NULL,
                   created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                   updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
               )"""
        )


def _mutation(*, expected_revision: int = 0) -> AnalystNoteMutation:
    return AnalystNoteMutation(
        note_key="note:client-generated",
        entity_type="company",
        legacy_entity_id="7",
        entity_key="company:688041.SH",
        q_label=None,
        note_type="general",
        title=None,
        content="trusted actor test",
        expected_revision=expected_revision,
        idempotency_key="operation-1",
    )


def test_sqlite_s0_create_and_list_use_server_actor(tmp_path) -> None:
    path = tmp_path / "research.db"
    _schema(path)
    repository = SQLiteAnalystNoteRepository(_factory(path), _route())

    created = repository.put(_mutation(), actor="principal:analyst")
    assert created.author == "principal:analyst"
    assert created.note_key.startswith("sqlite-legacy:")
    assert created.revision is None

    rows = repository.list_notes(
        entity_type="company",
        legacy_entity_id="7",
        entity_key="ignored-in-sqlite",
        q_label=None,
    )
    assert [row.content for row in rows] == ["trusted actor test"]
    assert rows[0].author == "principal:analyst"


def test_sqlite_s0_does_not_fake_revision_idempotency_or_soft_delete(tmp_path) -> None:
    path = tmp_path / "research.db"
    _schema(path)
    repository = SQLiteAnalystNoteRepository(_factory(path), _route())

    with pytest.raises(AnalystNoteCapabilityUnavailable, match="revision-aware"):
        repository.put(_mutation(expected_revision=1), actor="principal:analyst")
    with pytest.raises(AnalystNoteCapabilityUnavailable, match="hard delete is disabled"):
        repository.soft_delete(
            note_key="sqlite-legacy:1",
            expected_revision=1,
            idempotency_key="delete-1",
            actor="principal:analyst",
        )


def test_missing_postgres_factory_fails_closed(tmp_path) -> None:
    path = tmp_path / "research.db"
    _schema(path)
    production = CutoverRoute(
        cutover_unit="user_content_notes",
        backend=Backend.POSTGRESQL_PRODUCTION,
        writer_operation="analyst_note_mutation",
        transaction_boundary="one note mutation",
        authority_state=AuthorityState.S2,
        sqlite_writer_enabled=False,
        production_postgresql_enabled=True,
        writer_identity="honghu_user_content_writer",
        approval_reference="approved-cutover",
    )
    with pytest.raises(AnalystNoteWriterFenced, match="without a connection factory"):
        build_analyst_note_repository(
            production,
            sqlite_connection_factory=_factory(path),
            postgres_read_connection_factory=None,
            postgres_write_connection_factory=None,
        )


def test_request_hash_is_canonical() -> None:
    assert canonical_request_hash({"b": 2, "a": 1}) == canonical_request_hash(
        {"a": 1, "b": 2}
    )
