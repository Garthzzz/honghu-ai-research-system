from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from typing import Any, Callable, Iterable, Protocol

from .routing import AuthorityState, Backend, CutoverRoute


class AnalystNoteError(RuntimeError):
    code = "analyst_note_error"
    http_status = 500


class AnalystNoteConflict(AnalystNoteError):
    code = "analyst_note_conflict"
    http_status = 409


class AnalystNoteStaleRevision(AnalystNoteConflict):
    code = "stale_revision"


class AnalystNoteMappingMissing(AnalystNoteConflict):
    code = "identity_mapping_missing"


class AnalystNoteWriterFenced(AnalystNoteError):
    code = "writer_fenced"
    http_status = 503


class AnalystNoteCapabilityUnavailable(AnalystNoteError):
    code = "capability_unavailable"
    http_status = 409


@dataclass(frozen=True)
class AnalystNoteMutation:
    note_key: str
    entity_type: str
    legacy_entity_id: str
    entity_key: str
    q_label: str | None
    note_type: str
    title: str | None
    content: str
    expected_revision: int
    idempotency_key: str


@dataclass(frozen=True)
class AnalystNoteRecord:
    id: int | None
    note_key: str
    entity_type: str
    legacy_entity_id: str
    entity_key: str | None
    q_number: str | None
    note_type: str
    title: str | None
    content: str
    author: str
    revision: int | None
    created_at: str | None
    updated_at: str | None
    deleted: bool
    backend: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AnalystNoteRepository(Protocol):
    def list_notes(
        self, *, entity_type: str, legacy_entity_id: str, entity_key: str, q_label: str | None
    ) -> list[AnalystNoteRecord]: ...

    def put(self, mutation: AnalystNoteMutation, *, actor: str) -> AnalystNoteRecord: ...

    def soft_delete(
        self,
        *,
        note_key: str,
        expected_revision: int,
        idempotency_key: str,
        actor: str,
    ) -> AnalystNoteRecord: ...

    def note_key_from_legacy_id(self, legacy_note_id: int) -> str: ...


def canonical_request_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _row_mapping(cursor: Any, row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return row
    if hasattr(row, "keys"):
        return dict(row)
    names = [description[0] for description in cursor.description]
    return dict(zip(names, row))


def _legacy_note_key(note_id: int) -> str:
    return f"sqlite-legacy:{note_id}"


def _legacy_note_id(note_key: str) -> int:
    prefix = "sqlite-legacy:"
    if not note_key.startswith(prefix):
        raise AnalystNoteCapabilityUnavailable(
            "legacy SQLite can address only sqlite-legacy note keys"
        )
    try:
        return int(note_key[len(prefix) :])
    except ValueError as exc:
        raise AnalystNoteCapabilityUnavailable("invalid legacy note key") from exc


class SQLiteAnalystNoteRepository:
    """Truthful S0 compatibility adapter for the unchanged legacy table.

    It intentionally does not claim durable revision, idempotency, update, or
    soft-delete support that the live SQLite schema does not have.
    """

    def __init__(self, connection_factory: Callable[[], sqlite3.Connection], route: CutoverRoute):
        route.validate()
        if route.backend is not Backend.SQLITE_TRANSITION:
            raise ValueError("SQLite repository requires sqlite_transition")
        self._connect = connection_factory
        self.route = route

    @staticmethod
    def _record(row: dict[str, Any]) -> AnalystNoteRecord:
        note_id = int(row["id"])
        return AnalystNoteRecord(
            id=note_id,
            note_key=_legacy_note_key(note_id),
            entity_type=str(row["entity_type"]),
            legacy_entity_id=str(row["entity_id"]),
            entity_key=None,
            q_number=row.get("q_number"),
            note_type=str(row.get("note_type") or "general"),
            title=row.get("title"),
            content=str(row["content"]),
            author=str(row.get("author") or ""),
            revision=None,
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
            deleted=False,
            backend=Backend.SQLITE_TRANSITION.value,
        )

    def list_notes(
        self, *, entity_type: str, legacy_entity_id: str, entity_key: str, q_label: str | None
    ) -> list[AnalystNoteRecord]:
        del entity_key
        conn = self._connect()
        try:
            sql = "SELECT * FROM analyst_note WHERE entity_type=? AND entity_id=?"
            params: list[Any] = [entity_type, legacy_entity_id]
            if q_label:
                sql += " AND q_number=?"
                params.append(q_label)
            sql += " ORDER BY created_at DESC, id DESC"
            rows = [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]
            return [self._record(row) for row in rows]
        finally:
            conn.close()

    def put(self, mutation: AnalystNoteMutation, *, actor: str) -> AnalystNoteRecord:
        if not self.route.sqlite_writer_enabled:
            raise AnalystNoteWriterFenced("SQLite analyst-note writer is fenced")
        if mutation.expected_revision != 0:
            raise AnalystNoteCapabilityUnavailable(
                "legacy SQLite does not support revision-aware analyst-note update"
            )
        conn = self._connect()
        try:
            cursor = conn.execute(
                """INSERT INTO analyst_note(
                       entity_type, entity_id, q_number, note_type, title, content, author
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    mutation.entity_type,
                    mutation.legacy_entity_id,
                    mutation.q_label,
                    mutation.note_type,
                    mutation.title,
                    mutation.content,
                    actor,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM analyst_note WHERE id=?", (cursor.lastrowid,)
            ).fetchone()
            if row is None:
                raise AnalystNoteError("legacy insert committed without a readable row")
            return self._record(dict(row))
        finally:
            conn.close()

    def soft_delete(
        self,
        *,
        note_key: str,
        expected_revision: int,
        idempotency_key: str,
        actor: str,
    ) -> AnalystNoteRecord:
        del note_key, expected_revision, idempotency_key, actor
        raise AnalystNoteCapabilityUnavailable(
            "legacy SQLite hard delete is disabled; soft delete requires the approved PostgreSQL route"
        )

    def note_key_from_legacy_id(self, legacy_note_id: int) -> str:
        return _legacy_note_key(legacy_note_id)


class PostgresAnalystNoteRepository:
    def __init__(
        self,
        read_connection_factory: Callable[[], Any],
        write_connection_factory: Callable[[], Any],
        route: CutoverRoute,
    ):
        route.validate(allow_production=True)
        if route.backend is not Backend.POSTGRESQL_PRODUCTION:
            raise ValueError("PostgreSQL repository requires postgresql_production")
        self._read_connect = read_connection_factory
        self._write_connect = write_connection_factory
        self.route = route

    def _assert_authority(self, cursor: Any) -> None:
        cursor.execute(
            """SELECT state, authoritative_backend, writer_identity, approval_reference
                 FROM operations.user_content_notes_authority_v1
                WHERE cutover_unit = %s""",
            (self.route.cutover_unit,),
        )
        row = cursor.fetchone()
        if row is None:
            raise AnalystNoteWriterFenced("PostgreSQL authority row is missing")
        authority = _row_mapping(cursor, row)
        if (
            authority["state"] != self.route.authority_state.value
            or authority["authoritative_backend"] != Backend.POSTGRESQL_PRODUCTION.value
            or authority["writer_identity"] != self.route.writer_identity
            or authority["approval_reference"] != self.route.approval_reference
        ):
            raise AnalystNoteWriterFenced(
                "runtime route does not match PostgreSQL cutover authority"
            )

    @staticmethod
    def _record(row: dict[str, Any], *, deleted: bool = False) -> AnalystNoteRecord:
        return AnalystNoteRecord(
            id=int(row["id"]) if row.get("id") is not None else None,
            note_key=str(row["note_key"]),
            entity_type=str(row["entity_type"]),
            legacy_entity_id=str(
                row.get("legacy_entity_id_text")
                if row.get("legacy_entity_id_text") is not None
                else row.get("entity_id")
            ),
            entity_key=row.get("entity_key"),
            q_number=row.get("q_number"),
            note_type=str(row.get("note_type") or "general"),
            title=row.get("title"),
            content=str(row.get("content") or ""),
            author=str(row.get("author") or ""),
            revision=int(row["revision"]) if row.get("revision") is not None else None,
            created_at=str(row["created_at"]) if row.get("created_at") is not None else None,
            updated_at=str(row["updated_at"]) if row.get("updated_at") is not None else None,
            deleted=deleted,
            backend=Backend.POSTGRESQL_PRODUCTION.value,
        )

    def list_notes(
        self, *, entity_type: str, legacy_entity_id: str, entity_key: str, q_label: str | None
    ) -> list[AnalystNoteRecord]:
        del legacy_entity_id
        with self._read_connect() as conn:
            with conn.cursor() as cursor:
                self._assert_authority(cursor)
                sql = (
                    "SELECT * FROM user_content.analyst_note_read_v1 "
                    "WHERE entity_type=%s AND entity_key=%s"
                )
                params: list[Any] = [entity_type, entity_key]
                if q_label:
                    sql += " AND q_number=%s"
                    params.append(q_label)
                sql += " ORDER BY created_at DESC, id DESC"
                cursor.execute(sql, tuple(params))
                return [
                    self._record(_row_mapping(cursor, row)) for row in cursor.fetchall()
                ]

    def put(self, mutation: AnalystNoteMutation, *, actor: str) -> AnalystNoteRecord:
        request_payload = {
            "note_key": mutation.note_key,
            "entity_type": mutation.entity_type,
            "legacy_entity_id": mutation.legacy_entity_id,
            "entity_key": mutation.entity_key,
            "q_label": mutation.q_label,
            "note_type": mutation.note_type,
            "title": mutation.title,
            "content": mutation.content,
            "author": actor,
            "expected_revision": mutation.expected_revision,
        }
        try:
            with self._write_connect() as conn:
                with conn.cursor() as cursor:
                    self._assert_authority(cursor)
                    cursor.execute(
                        """SELECT * FROM user_content.put_analyst_note_v2(
                            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                        )""",
                        (
                            mutation.note_key,
                            mutation.entity_type,
                            mutation.legacy_entity_id,
                            mutation.entity_key,
                            mutation.q_label,
                            mutation.note_type,
                            mutation.title,
                            mutation.content,
                            actor,
                            mutation.expected_revision,
                            mutation.idempotency_key,
                            canonical_request_hash(request_payload),
                            self.route.writer_identity,
                        ),
                    )
                    result = _row_mapping(cursor, cursor.fetchone())
                    return AnalystNoteRecord(
                        id=None,
                        note_key=mutation.note_key,
                        entity_type=mutation.entity_type,
                        legacy_entity_id=mutation.legacy_entity_id,
                        entity_key=mutation.entity_key,
                        q_number=mutation.q_label,
                        note_type=mutation.note_type,
                        title=mutation.title,
                        content=mutation.content,
                        author=actor,
                        revision=int(result["revision"]),
                        created_at=None,
                        updated_at=None,
                        deleted=bool(result["deleted"]),
                        backend=Backend.POSTGRESQL_PRODUCTION.value,
                    )
        except Exception as exc:
            raise translate_postgres_error(exc) from exc

    def soft_delete(
        self,
        *,
        note_key: str,
        expected_revision: int,
        idempotency_key: str,
        actor: str,
    ) -> AnalystNoteRecord:
        payload = {
            "note_key": note_key,
            "actor": actor,
            "expected_revision": expected_revision,
        }
        try:
            with self._write_connect() as conn:
                with conn.cursor() as cursor:
                    self._assert_authority(cursor)
                    cursor.execute(
                        """SELECT * FROM user_content.soft_delete_analyst_note_v2(
                            %s,%s,%s,%s,%s,%s
                        )""",
                        (
                            note_key,
                            actor,
                            expected_revision,
                            idempotency_key,
                            canonical_request_hash(payload),
                            self.route.writer_identity,
                        ),
                    )
                    result = _row_mapping(cursor, cursor.fetchone())
                    return AnalystNoteRecord(
                        id=None,
                        note_key=note_key,
                        entity_type="",
                        legacy_entity_id="",
                        entity_key=None,
                        q_number=None,
                        note_type="",
                        title=None,
                        content="",
                        author=actor,
                        revision=int(result["revision"]),
                        created_at=None,
                        updated_at=None,
                        deleted=bool(result["deleted"]),
                        backend=Backend.POSTGRESQL_PRODUCTION.value,
                    )
        except Exception as exc:
            raise translate_postgres_error(exc) from exc

    def note_key_from_legacy_id(self, legacy_note_id: int) -> str:
        try:
            with self._read_connect() as conn:
                with conn.cursor() as cursor:
                    self._assert_authority(cursor)
                    cursor.execute(
                        "SELECT note_key FROM user_content.analyst_note_identity_v1 WHERE legacy_note_id=%s",
                        (legacy_note_id,),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise AnalystNoteStaleRevision("legacy analyst note does not exist")
                    return str(_row_mapping(cursor, row)["note_key"])
        except Exception as exc:
            raise translate_postgres_error(exc) from exc


def translate_postgres_error(exc: Exception) -> AnalystNoteError:
    sqlstate = getattr(exc, "sqlstate", None)
    message = str(exc)
    if isinstance(exc, AnalystNoteError):
        return exc
    if sqlstate == "40001":
        return AnalystNoteStaleRevision(message)
    if sqlstate == "23503":
        return AnalystNoteMappingMissing(message)
    if sqlstate == "23505":
        return AnalystNoteConflict(message)
    if sqlstate == "42501":
        return AnalystNoteWriterFenced(message)
    return AnalystNoteError(message)


def build_analyst_note_repository(
    route: CutoverRoute,
    *,
    sqlite_connection_factory: Callable[[], sqlite3.Connection],
    postgres_read_connection_factory: Callable[[], Any] | None = None,
    postgres_write_connection_factory: Callable[[], Any] | None = None,
) -> AnalystNoteRepository:
    if route.backend is Backend.SQLITE_TRANSITION:
        return SQLiteAnalystNoteRepository(sqlite_connection_factory, route)
    if route.backend is Backend.POSTGRESQL_PRODUCTION:
        if postgres_read_connection_factory is None or postgres_write_connection_factory is None:
            raise AnalystNoteWriterFenced(
                "production PostgreSQL was selected without a connection factory"
            )
        return PostgresAnalystNoteRepository(
            postgres_read_connection_factory,
            postgres_write_connection_factory,
            route,
        )
    raise AnalystNoteWriterFenced("dev/test backend is not a production Viewer route")
