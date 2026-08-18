from __future__ import annotations

"""PostgreSQL-authoritative, process-memory compatibility for shared identity.

The compatibility cache is an ephemeral SQLite shared-memory database.  It is
rebuilt only from PostgreSQL and attached through TEMP views, so legacy joins
can continue during the mixed migration window without reading or mutating the
old SQLite identity tables.  PostgreSQL connection/authority failures abort;
there is deliberately no fallback to the SQLite baseline.
"""

import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tools.data_platform.background_refresh import submit_background_refresh

from .routing import AuthorityState, Backend, CutoverRoute


SHARED_IDENTITY_TABLES = (
    "company",
    "company_identity_alias",
    "company_identity_redirect",
    "company_industry",
    "company_profile",
    "company_sub_market_share",
    "industry",
    "industry_relation",
    "researcher",
    "theme",
    "theme_company",
    "theme_industry",
    "financial_security",
    "financial_security_company_link",
)

DEFAULT_COLUMNS = {
    "company": ("id", "name", "ticker", "market", "listing_status"),
    "company_identity_alias": ("id", "canonical_company_id", "alias", "alias_type", "source"),
    "company_identity_redirect": (
        "old_company_id",
        "canonical_company_id",
        "old_name",
        "canonical_name",
        "ticker",
        "reason",
        "verified_at",
    ),
    "company_industry": ("id", "company_id", "industry_id", "role", "revenue_share", "note"),
    "company_profile": ("id", "company_id", "industry_id", "period"),
    "company_sub_market_share": ("id", "company_id", "industry_id", "sub_market", "geo", "share"),
    "industry": ("id", "name", "parent_id", "level", "tier", "status"),
    "industry_relation": ("id", "upstream_id", "downstream_id", "relation_type"),
    "researcher": ("id", "name", "display_name", "is_active"),
    "theme": ("id", "name", "category", "summary", "status"),
    "theme_company": ("id", "theme_id", "company_id", "impact", "note"),
    "theme_industry": ("id", "theme_id", "industry_id", "impact", "note"),
    "financial_security": (
        "id", "research_company_id", "canonical_name", "ticker", "market",
        "listing_status", "reporting_currency", "name_en", "fiscal_year_end",
        "identity_status",
    ),
    "financial_security_company_link": ("research_company_id", "security_id", "link_role"),
}


class SharedIdentityError(RuntimeError):
    pass


class SharedIdentityConflict(SharedIdentityError):
    pass


class SharedIdentityWriterFenced(SharedIdentityError):
    pass


_TICKER_SUFFIX_VENUES = {
    "SH": "shanghai",
    "SZ": "shenzhen",
    "BJ": "beijing",
    "HK": "hong-kong",
    "T": "tokyo",
    "KS": "korea-main",
    "KQ": "korea-kosdaq",
    "TW": "taiwan-main",
    "TWO": "taiwan-otc",
    "VI": "vienna",
    "DE": "germany",
    "ST": "stockholm",
    "MI": "milan",
}
_MARKET_VENUES = {
    "美股": "us",
    "美国": "us",
    "us": "us",
    "港股": "hong-kong",
    "香港": "hong-kong",
}


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _canonical_hash(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def company_security_stable_key(
    ticker: str, market: str, listing_status: str
) -> str:
    code = str(ticker or "").strip().upper()
    market_name = str(market or "").strip()
    status = str(listing_status or "").strip().casefold()
    venue = None
    if "." in code:
        venue = _TICKER_SUFFIX_VENUES.get(code.rsplit(".", 1)[1])
    if venue is None:
        venue = _MARKET_VENUES.get(market_name) or _MARKET_VENUES.get(
            market_name.casefold()
        )
    if venue is None and status in {"us", "hk"}:
        venue = {"us": "us", "hk": "hong-kong"}[status]
    if not code or not venue:
        raise SharedIdentityError(
            "listed company ticker is not qualified by a supported venue"
        )
    return f"company:security:{code}:venue:{venue}"


def _row_mapping(cursor: Any, row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return row
    if hasattr(row, "keys"):
        return dict(row)
    return dict(zip((item[0] for item in cursor.description), row))


class PostgresSharedIdentityRepository:
    """Formal shared-identity mutations behind an explicit S3/S4 route.

    All business writes are PostgreSQL functions with authority, writer,
    idempotency and audit checks.  The repository never attempts SQLite after
    a PostgreSQL failure.
    """

    def __init__(
        self,
        read_connection_factory: Callable[[], Any],
        write_connection_factory: Callable[[], Any],
        route: CutoverRoute,
    ) -> None:
        route.validate(allow_production=True)
        if route.cutover_unit != "shared_identity":
            raise ValueError("shared identity repository requires its owning unit")
        if route.backend is not Backend.POSTGRESQL_PRODUCTION:
            raise ValueError("shared identity repository requires PostgreSQL authority")
        if route.authority_state not in {AuthorityState.S3, AuthorityState.S4}:
            raise ValueError("formal shared identity mutations require S3 or S4")
        self._read_connect = read_connection_factory
        self._write_connect = write_connection_factory
        self.route = route

    def _assert_authority(self, cursor: Any) -> None:
        cursor.execute(
            """SELECT state,authoritative_backend,writer_identity,
                      approval_reference,cutover_epoch
                 FROM operations.shared_identity_authority_v1"""
        )
        row = cursor.fetchone()
        if row is None:
            raise SharedIdentityWriterFenced("shared identity authority row is missing")
        authority = _row_mapping(cursor, row)
        if (
            authority["state"] != self.route.authority_state.value
            or authority["authoritative_backend"]
            != Backend.POSTGRESQL_PRODUCTION.value
            or authority["writer_identity"] != self.route.writer_identity
            or authority["approval_reference"] != self.route.approval_reference
            or authority["cutover_epoch"] != self.route.cutover_epoch
        ):
            raise SharedIdentityWriterFenced(
                "runtime route does not match shared identity authority"
            )

    def create_researcher(
        self,
        *,
        name: str,
        display_name: str,
        focus_summary: str | None,
        focus_industries: list[int],
        bio: str | None,
        idempotency_key: str,
        actor: str,
    ) -> dict[str, Any]:
        request = {
            "name": name,
            "display_name": display_name,
            "focus_summary": focus_summary,
            "focus_industries": focus_industries,
            "bio": bio,
            "actor": actor,
        }
        try:
            with self._write_connect() as connection:
                with connection.cursor() as cursor:
                    self._assert_authority(cursor)
                    cursor.execute(
                        """SELECT shared_identity.create_researcher_v1(
                            %s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s
                        ) AS result""",
                        (
                            name,
                            display_name,
                            focus_summary,
                            json.dumps(focus_industries),
                            bio,
                            idempotency_key,
                            _canonical_hash(request),
                            self.route.writer_identity,
                            actor,
                        ),
                    )
                    return dict(_row_mapping(cursor, cursor.fetchone())["result"])
        except Exception as exc:
            raise translate_shared_identity_error(exc) from exc

    def ensure_listed_company(
        self,
        *,
        canonical_name: str,
        ticker: str,
        market: str,
        listing_status: str,
        verification_source_ref: str,
        aliases: list[str],
        idempotency_key: str,
        actor: str,
    ) -> dict[str, Any]:
        stable_key = company_security_stable_key(ticker, market, listing_status)
        request = {
            "canonical_name": canonical_name,
            "ticker": ticker.strip().upper(),
            "market": market,
            "listing_status": listing_status,
            "verification_source_ref": verification_source_ref,
            "aliases": aliases,
            "stable_key": stable_key,
            "actor": actor,
        }
        try:
            with self._write_connect() as connection:
                with connection.cursor() as cursor:
                    self._assert_authority(cursor)
                    cursor.execute(
                        """SELECT shared_identity.ensure_listed_company_v1(
                            %s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s
                        ) AS result""",
                        (
                            canonical_name,
                            ticker.strip().upper(),
                            market,
                            listing_status,
                            verification_source_ref,
                            json.dumps(aliases, ensure_ascii=False),
                            stable_key,
                            idempotency_key,
                            _canonical_hash(request),
                            self.route.writer_identity,
                            actor,
                        ),
                    )
                    return dict(_row_mapping(cursor, cursor.fetchone())["result"])
        except Exception as exc:
            raise translate_shared_identity_error(exc) from exc

    def ensure_listed_company_v2(
        self,
        *,
        expected_company_id: int,
        canonical_name: str,
        ticker: str,
        market: str,
        listing_status: str,
        financial_market: str,
        financial_listing_status: str,
        reporting_currency: str,
        name_en: str | None,
        fiscal_year_end: str | None,
        verification_source_ref: str,
        aliases: list[str],
        idempotency_key: str,
        actor: str,
    ) -> dict[str, Any]:
        stable_key = company_security_stable_key(ticker, market, listing_status)
        company = {
            "id": int(expected_company_id),
            "name": canonical_name,
            "ticker": ticker.strip().upper(),
            "market": market,
            "listing_status": listing_status,
            "financial_market": financial_market,
            "financial_listing_status": financial_listing_status,
            "reporting_currency": reporting_currency,
            "name_en": name_en,
            "fiscal_year_end": fiscal_year_end,
            "verification_source_ref": verification_source_ref,
            "aliases": aliases,
        }
        try:
            with self._write_connect() as connection:
                with connection.cursor() as cursor:
                    self._assert_authority(cursor)
                    cursor.execute(
                        """SELECT shared_identity.ensure_listed_company_v2(
                            %s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s
                        ) AS result""",
                        (
                            json.dumps(company, ensure_ascii=False),
                            stable_key,
                            idempotency_key,
                            self.route.writer_identity,
                            self.route.authority_state.value,
                            self.route.cutover_epoch,
                            self.route.approval_reference,
                            self.route.route_revision,
                            actor,
                        ),
                    )
                    return dict(_row_mapping(cursor, cursor.fetchone())["result"])
        except Exception as exc:
            raise translate_shared_identity_error(exc) from exc

    def apply_company_profile_batch(
        self,
        *,
        batch: dict[str, Any],
        idempotency_key: str,
        actor: str,
    ) -> dict[str, Any]:
        try:
            with self._write_connect() as connection:
                with connection.cursor() as cursor:
                    self._assert_authority(cursor)
                    cursor.execute(
                        """SELECT shared_identity.apply_company_profile_batch_v1(
                            %s::jsonb,%s,%s,%s,%s,%s,%s,%s
                        ) AS result""",
                        (
                            json.dumps(batch, ensure_ascii=False),
                            idempotency_key,
                            self.route.writer_identity,
                            self.route.authority_state.value,
                            self.route.cutover_epoch,
                            self.route.approval_reference,
                            self.route.route_revision,
                            actor,
                        ),
                    )
                    return dict(_row_mapping(cursor, cursor.fetchone())["result"])
        except Exception as exc:
            raise translate_shared_identity_error(exc) from exc

    def complete_company_identity_v3(
        self,
        *,
        expected_company_id: int,
        previous_name: str,
        canonical_name: str,
        ticker: str,
        market: str,
        listing_status: str,
        financial_market: str,
        financial_listing_status: str,
        reporting_currency: str,
        name_en: str | None,
        fiscal_year_end: str | None,
        verification_source_ref: str,
        stable_key: str,
        idempotency_key: str,
        actor: str,
    ) -> dict[str, Any]:
        company = {
            "id": int(expected_company_id),
            "previous_name": previous_name,
            "name": canonical_name,
            "ticker": ticker.strip().upper(),
            "market": market,
            "listing_status": listing_status,
            "financial_market": financial_market,
            "financial_listing_status": financial_listing_status,
            "reporting_currency": reporting_currency,
            "name_en": name_en,
            "fiscal_year_end": fiscal_year_end,
            "verification_source_ref": verification_source_ref,
        }
        try:
            with self._write_connect() as connection:
                with connection.cursor() as cursor:
                    self._assert_authority(cursor)
                    cursor.execute(
                        """SELECT shared_identity.complete_company_identity_v3(
                            %s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s
                        ) AS result""",
                        (
                            json.dumps(company, ensure_ascii=False),
                            stable_key,
                            idempotency_key,
                            self.route.writer_identity,
                            self.route.authority_state.value,
                            self.route.cutover_epoch,
                            self.route.approval_reference,
                            self.route.route_revision,
                            actor,
                        ),
                    )
                    return dict(_row_mapping(cursor, cursor.fetchone())["result"])
        except Exception as exc:
            raise translate_shared_identity_error(exc) from exc

    def complete_company_identity_v2(
        self,
        *,
        expected_company_id: int,
        previous_name: str,
        canonical_name: str,
        ticker: str,
        market: str,
        listing_status: str,
        verification_source_ref: str,
        stable_key: str,
        idempotency_key: str,
        actor: str,
    ) -> dict[str, Any]:
        company = {
            "id": int(expected_company_id),
            "previous_name": previous_name,
            "name": canonical_name,
            "ticker": ticker.strip().upper(),
            "market": market,
            "listing_status": listing_status,
            "verification_source_ref": verification_source_ref,
        }
        try:
            with self._write_connect() as connection:
                with connection.cursor() as cursor:
                    self._assert_authority(cursor)
                    cursor.execute(
                        """SELECT shared_identity.complete_company_identity_v2(
                            %s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s
                        ) AS result""",
                        (
                            json.dumps(company, ensure_ascii=False),
                            stable_key,
                            idempotency_key,
                            self.route.writer_identity,
                            self.route.authority_state.value,
                            self.route.cutover_epoch,
                            self.route.approval_reference,
                            self.route.route_revision,
                            actor,
                        ),
                    )
                    return dict(_row_mapping(cursor, cursor.fetchone())["result"])
        except Exception as exc:
            raise translate_shared_identity_error(exc) from exc

    def ensure_industry(
        self,
        *,
        industry: dict[str, Any],
        stable_key: str,
        idempotency_key: str,
        actor: str,
    ) -> dict[str, Any]:
        try:
            with self._write_connect() as connection:
                with connection.cursor() as cursor:
                    self._assert_authority(cursor)
                    cursor.execute(
                        """SELECT shared_identity.ensure_industry_v1(
                            %s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s
                        ) AS result""",
                        (
                            json.dumps(industry, ensure_ascii=False),
                            stable_key,
                            idempotency_key,
                            self.route.writer_identity,
                            self.route.authority_state.value,
                            self.route.cutover_epoch,
                            self.route.approval_reference,
                            self.route.route_revision,
                            actor,
                        ),
                    )
                    return dict(_row_mapping(cursor, cursor.fetchone())["result"])
        except Exception as exc:
            raise translate_shared_identity_error(exc) from exc


class PostgresSharedIdentityResolver:
    """Resolve legacy UI references against authoritative PostgreSQL identity.

    The frozen Stage 4 mapping remains migration/audit evidence.  Once
    ``shared_identity`` is S3/S4 it must not cap the set of identities accepted
    by dependent domains, so runtime resolution reads the current formal
    identity table and fails closed on missing or ambiguous records.
    """

    _ENTITY_TABLES = {
        "company": "company",
        "industry": "industry",
        "theme": "theme",
    }

    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connect = connection_factory

    def resolve(self, entity_type: str, legacy_id: str | int) -> str:
        table = self._ENTITY_TABLES.get(str(entity_type))
        if table is None:
            raise SharedIdentityError(f"unsupported shared identity type: {entity_type}")
        connection = self._connect()
        try:
            authority = connection.execute(
                """
                SELECT state,authoritative_backend
                  FROM operations.cutover_unit_authority
                 WHERE cutover_unit='shared_identity'
                """
            ).fetchone()
            if authority is None or str(authority[0]) not in {"S3", "S4"} or str(
                authority[1]
            ) != "postgresql_production":
                raise SharedIdentityWriterFenced(
                    "shared_identity is not PostgreSQL-authoritative"
                )
            rows = connection.execute(
                """
                SELECT stable_key
                  FROM shared_identity.legacy_record
                 WHERE source_database='research.db'
                   AND source_table=%s
                   AND legacy_id=%s
                   AND formal_business_data=true
                """,
                (table, str(legacy_id)),
            ).fetchall()
        finally:
            connection.close()
        if len(rows) != 1 or not str(rows[0][0] or "").strip():
            raise SharedIdentityError(
                f"authoritative shared identity is missing or ambiguous: {entity_type}:{legacy_id}"
            )
        return str(rows[0][0])


def translate_shared_identity_error(exc: Exception) -> SharedIdentityError:
    if isinstance(exc, SharedIdentityError):
        return exc
    sqlstate = getattr(exc, "sqlstate", None)
    if sqlstate == "23505":
        return SharedIdentityConflict(str(exc))
    if sqlstate == "42501":
        return SharedIdentityWriterFenced(str(exc))
    return SharedIdentityError(str(exc))


def _quote(identifier: str) -> str:
    if identifier not in SHARED_IDENTITY_TABLES and not identifier.replace("_", "").isalnum():
        raise SharedIdentityError(f"unsafe identity identifier: {identifier}")
    return '"' + identifier.replace('"', '""') + '"'


def _sqlite_type(values: list[Any]) -> str:
    present = [value for value in values if value is not None]
    if not present:
        return "TEXT"
    if all(isinstance(value, bool | int) for value in present):
        return "INTEGER"
    if all(isinstance(value, bool | int | float) for value in present):
        return "REAL"
    if all(isinstance(value, bytes) for value in present):
        return "BLOB"
    return "TEXT"


def _sqlite_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


class SharedIdentityReadCache:
    def __init__(
        self,
        connection_factory: Callable[[], Any],
        *,
        refresh_check_seconds: float = 30.0,
    ) -> None:
        self._connection_factory = connection_factory
        self._refresh_check_seconds = refresh_check_seconds
        # More than one reviewed adapter may need the shared-identity
        # projection in the same process (the Viewer owns one and the generic
        # domain router owns another).  A named SQLite shared-memory database
        # is process-global, so the authority/version alone is not a unique
        # cache identity.  Keep each cache instance isolated while preserving
        # stable URIs across refreshes of that instance.
        self._cache_id = uuid.uuid4().hex
        self._lock = threading.RLock()
        self._keeper: sqlite3.Connection | None = None
        self._uri: str | None = None
        self._version: str | None = None
        self._authority_token: str | None = None
        self._next_check = 0.0
        self._refreshing = False
        self._last_refresh_error: Exception | None = None

    @staticmethod
    def _authority_version(connection: Any) -> tuple[str, tuple[Any, ...]]:
        """Return a small, authority-bound cache token before loading rows."""

        authority = connection.execute(
            """
            SELECT a.state,a.authoritative_backend,a.state_revision,a.cutover_epoch,
                   s.source_snapshot_id,s.target_content_sha256,s.formal_revision,
                   s.current_formal_row_count,s.formal_business_data
              FROM operations.cutover_unit_authority a
              JOIN shared_identity.unit_snapshot s
                ON s.cutover_unit=a.cutover_unit
             WHERE a.cutover_unit='shared_identity'
            """
        ).fetchone()
        if authority is None:
            raise SharedIdentityError("shared_identity authority/snapshot row is missing")
        if str(authority[0]) not in {"S3", "S4"} or str(authority[1]) != "postgresql_production":
            raise SharedIdentityError("shared_identity PostgreSQL read route is not authoritative")
        if not bool(authority[8]):
            raise SharedIdentityError("shared_identity formal dataset is not enabled")
        version = hashlib.sha256(
            json.dumps(
                [str(value) if value is not None else None for value in authority],
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return version, tuple(authority)

    def _read_postgresql(
        self,
    ) -> tuple[str, str | None, dict[str, list[dict[str, Any]]] | None]:
        connection = self._connection_factory()
        try:
            version, authority = self._authority_version(connection)
            if version == self._authority_token and self._uri is not None:
                return version, None, None
            rows = connection.execute(
                """
                SELECT source_table,payload,row_sha256,revision,source_snapshot_id
                  FROM shared_identity.legacy_record
                 WHERE formal_business_data=true
                 ORDER BY source_table,source_ordinal
                """
            ).fetchall()
        finally:
            connection.close()
        grouped = {table: [] for table in SHARED_IDENTITY_TABLES}
        digest = hashlib.sha256()
        digest.update(version.encode("ascii"))
        for table, raw_payload, row_sha, revision, snapshot_id in rows:
            table_name = str(table)
            if table_name not in grouped:
                raise SharedIdentityError(f"unapproved PostgreSQL identity table: {table_name}")
            payload = raw_payload if isinstance(raw_payload, dict) else json.loads(raw_payload)
            if not isinstance(payload, dict):
                raise SharedIdentityError("shared identity payload is not an object")
            grouped[table_name].append(payload)
            digest.update(
                json.dumps(
                    [table_name, str(row_sha), int(revision), str(snapshot_id)],
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            digest.update(b"\n")
        row_version = digest.hexdigest()
        expected_count = int(authority[7])
        if sum(len(table_rows) for table_rows in grouped.values()) != expected_count:
            raise SharedIdentityError("shared_identity formal row count changed during refresh")
        return version, f"{version}_{row_version}", grouped

    def _build(self, version: str, grouped: dict[str, list[dict[str, Any]]]) -> None:
        uri = (
            f"file:honghu_shared_identity_{self._cache_id}_{version}"
            "?mode=memory&cache=shared"
        )
        keeper = sqlite3.connect(uri, uri=True, check_same_thread=False)
        try:
            for table in SHARED_IDENTITY_TABLES:
                rows = grouped.get(table) or []
                columns = list(DEFAULT_COLUMNS[table])
                seen: set[str] = set(columns)
                for row in rows:
                    for name in row:
                        if name not in seen:
                            seen.add(name)
                            columns.append(name)
                definitions = []
                for name in columns:
                    values = [row.get(name) for row in rows]
                    definitions.append(f'{_quote(name)} {_sqlite_type(values)}')
                keeper.execute(
                    f"CREATE TABLE {_quote(table)} ({','.join(definitions)})"
                )
                if rows:
                    marks = ",".join("?" for _ in columns)
                    keeper.executemany(
                        f"INSERT INTO {_quote(table)} VALUES ({marks})",
                        [tuple(_sqlite_value(row.get(name)) for name in columns) for row in rows],
                    )
            keeper.commit()
            keeper.execute("PRAGMA query_only=ON")
        except Exception:
            keeper.close()
            raise
        previous = self._keeper
        self._keeper = keeper
        self._uri = uri
        self._version = version
        if previous is not None:
            previous.close()

    def _refresh_in_background(self) -> None:
        try:
            authority_token, version, grouped = self._read_postgresql()
            with self._lock:
                if grouped is not None:
                    assert version is not None
                    self._build(version, grouped)
                    self._authority_token = authority_token
                self._last_refresh_error = None
        except Exception as exc:
            # Continue from the last PostgreSQL-derived copy.  The first load
            # remains synchronous and fail-closed.
            with self._lock:
                self._last_refresh_error = exc
        finally:
            with self._lock:
                self._refreshing = False

    def ensure_current(self) -> str:
        now = time.monotonic()
        with self._lock:
            if self._uri is not None and now < self._next_check:
                return self._uri
            if self._uri is None or self._refresh_check_seconds <= 0:
                authority_token, version, grouped = self._read_postgresql()
                if grouped is not None:
                    assert version is not None
                    self._build(version, grouped)
                    self._authority_token = authority_token
                self._next_check = now + self._refresh_check_seconds
            else:
                self._next_check = now + self._refresh_check_seconds
                if not self._refreshing:
                    self._refreshing = True
                    submit_background_refresh(self._refresh_in_background)
            assert self._uri is not None
            return self._uri

    def attach(self, connection: sqlite3.Connection) -> None:
        uri = self.ensure_current()
        with self._lock:
            if self._keeper is None:
                raise SharedIdentityError("shared identity cache has no keeper")
            alias = "pg_shared_identity"
            connection.execute(f"ATTACH DATABASE ? AS {_quote(alias)}", (uri,))
            for table in SHARED_IDENTITY_TABLES:
                quoted = _quote(table)
                connection.execute(
                    f"CREATE TEMP VIEW {quoted} AS "
                    f"SELECT * FROM {_quote(alias)}.{quoted}"
                )

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        try:
            self.attach(connection)
            connection.execute("PRAGMA query_only=ON")
            return connection
        except Exception:
            connection.close()
            raise

    def close(self) -> None:
        with self._lock:
            if self._keeper is not None:
                self._keeper.close()
            self._keeper = None
            self._uri = None
            self._version = None
            self._authority_token = None


_ENVIRONMENT_READ_CACHES: dict[str, SharedIdentityReadCache] = {}


def connect_shared_identity_database(sqlite_path: str | Path) -> sqlite3.Connection:
    """Open the authoritative shared-identity read surface.

    Before the shared-identity cutover this is a strictly read-only SQLite
    connection.  In S3/S4 it is a process-memory compatibility database built
    only from PostgreSQL.  A PostgreSQL/configuration failure is never allowed
    to reopen the frozen SQLite identity baseline.
    """

    from tools.data_platform.postgres_runtime import (
        build_catalog_connection_factory,
        load_postgres_runtime_catalog,
    )
    from tools.data_platform.routing import (
        Backend,
        load_environment_authority_matrix,
    )

    path = Path(sqlite_path).resolve()
    matrix = load_environment_authority_matrix()
    route = (
        matrix.route_for(
            "shared_identity",
            writer_operation="shared_identity_read",
            transaction_boundary="one authoritative identity read transaction",
        )
        if matrix is not None
        else None
    )
    if route is None or route.backend is Backend.SQLITE_TRANSITION:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        return connection
    catalog_path = os.environ.get("HONGHU_POSTGRES_RUNTIME_CONFIG")
    if not catalog_path:
        raise SharedIdentityWriterFenced(
            "PostgreSQL-authoritative shared_identity lacks a runtime catalog"
        )
    catalog = load_postgres_runtime_catalog(catalog_path)
    cache = _ENVIRONMENT_READ_CACHES.setdefault(
        str(Path(catalog_path).resolve()),
        SharedIdentityReadCache(build_catalog_connection_factory(catalog, role="reader")),
    )
    return cache.connect()
