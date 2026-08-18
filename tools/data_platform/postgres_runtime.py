from __future__ import annotations

import json
import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class PostgresRoleSettings:
    user: str
    credential_service: str
    credential_account: str

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "PostgresRoleSettings":
        role = cls(
            user=str(payload.get("user") or ""),
            credential_service=str(payload.get("credential_service") or ""),
            credential_account=str(payload.get("credential_account") or ""),
        )
        role.validate()
        return role

    def validate(self) -> None:
        if not self.user:
            raise ValueError("PostgreSQL role user is required")
        if not self.credential_service or not self.credential_account:
            raise ValueError("PostgreSQL role Credential Manager identity is required")


@dataclass(frozen=True)
class PostgresRuntimeSettings:
    enabled: bool
    host: str
    port: int
    dbname: str
    sslmode: str
    sslrootcert: str
    connect_timeout_seconds: int
    reader: PostgresRoleSettings
    writer: PostgresRoleSettings

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "PostgresRuntimeSettings":
        if payload.get("schema_version") != "honghu.postgresql_runtime.v2":
            raise ValueError("unsupported PostgreSQL runtime schema")
        settings = cls(
            enabled=bool(payload.get("enabled")),
            host=str(payload.get("host") or ""),
            port=int(payload.get("port") or 0),
            dbname=str(payload.get("dbname") or ""),
            sslmode=str(payload.get("sslmode") or "require"),
            sslrootcert=str(payload.get("sslrootcert") or ""),
            connect_timeout_seconds=int(payload.get("connect_timeout_seconds") or 5),
            reader=PostgresRoleSettings.from_mapping(payload.get("reader") or {}),
            writer=PostgresRoleSettings.from_mapping(payload.get("writer") or {}),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not self.enabled:
            raise ValueError("PostgreSQL runtime is not explicitly enabled")
        if not self.host or not 1 <= self.port <= 65535:
            raise ValueError("PostgreSQL host and port are required")
        if not self.dbname:
            raise ValueError("PostgreSQL database is required")
        if self.sslmode not in {"require", "verify-ca", "verify-full"}:
            raise ValueError("production PostgreSQL requires protected transport")
        if self.sslmode in {"verify-ca", "verify-full"}:
            root = Path(self.sslrootcert).resolve() if self.sslrootcert else None
            if root is None or not root.is_file():
                raise ValueError("verified PostgreSQL TLS requires an existing root certificate")
        self.reader.validate()
        self.writer.validate()
        if self.reader.user == self.writer.user:
            raise ValueError("PostgreSQL reader and writer roles must be distinct")
        if not 1 <= self.connect_timeout_seconds <= 30:
            raise ValueError("connect timeout is outside the approved bound")


def load_postgres_runtime_settings(path: str | Path) -> PostgresRuntimeSettings:
    return PostgresRuntimeSettings.from_mapping(
        json.loads(Path(path).read_text(encoding="utf-8"))
    )


def build_postgres_connection_factory(
    settings: PostgresRuntimeSettings,
    *,
    role: str,
    password_loader: Callable[[str, str], str | None] | None = None,
) -> Callable[[], Any]:
    settings.validate()
    selected = {"reader": settings.reader, "writer": settings.writer}.get(role)
    if selected is None:
        raise ValueError("PostgreSQL runtime role must be reader or writer")

    def connect() -> Any:
        loader = password_loader
        if loader is None:
            import keyring

            loader = keyring.get_password
        password = loader(selected.credential_service, selected.credential_account)
        if not password:
            raise RuntimeError("PostgreSQL credential is unavailable")
        import psycopg

        return psycopg.connect(
            host=settings.host,
            port=settings.port,
            dbname=settings.dbname,
            user=selected.user,
            password=password,
            sslmode=settings.sslmode,
            sslrootcert=(settings.sslrootcert or None),
            connect_timeout=settings.connect_timeout_seconds,
        )

    return connect


@dataclass(frozen=True)
class PostgresRuntimeCatalog:
    """Production runtime with named least-privilege roles.

    The Stage 4 bootstrap writes one catalog containing the shared endpoint and
    all domain roles.  Application code selects a role by audited purpose; it
    must not manufacture per-unit connection files or fall back to another
    role when a credential is absent.
    """

    host: str
    port: int
    dbname: str
    sslmode: str
    sslrootcert: str
    connect_timeout_seconds: int
    roles: dict[str, PostgresRoleSettings]
    environment_id: str
    application_commit_sha: str

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "PostgresRuntimeCatalog":
        if payload.get("schema_version") != "honghu.postgresql_production_runtime.v1":
            raise ValueError("unsupported production PostgreSQL runtime catalog")
        roles = {
            str(name): PostgresRoleSettings.from_mapping(value)
            for name, value in (payload.get("roles") or {}).items()
        }
        catalog = cls(
            host=str(payload.get("host") or ""),
            port=int(payload.get("port") or 0),
            dbname=str(payload.get("dbname") or ""),
            sslmode=str(payload.get("sslmode") or ""),
            sslrootcert=str(payload.get("sslrootcert") or ""),
            connect_timeout_seconds=int(payload.get("connect_timeout_seconds") or 5),
            roles=roles,
            environment_id=str(payload.get("environment_id") or ""),
            application_commit_sha=str(payload.get("application_commit_sha") or ""),
        )
        catalog.validate()
        return catalog

    def validate(self) -> None:
        if self.environment_id != "production":
            raise ValueError("runtime catalog is not production")
        if not self.host or not 1 <= self.port <= 65535 or not self.dbname:
            raise ValueError("runtime catalog endpoint is incomplete")
        if self.sslmode not in {"verify-ca", "verify-full"}:
            raise ValueError("production runtime catalog requires verified TLS")
        root = Path(self.sslrootcert).resolve() if self.sslrootcert else None
        if root is None or not root.is_file():
            raise ValueError("runtime catalog TLS root is unavailable")
        if not 1 <= self.connect_timeout_seconds <= 30:
            raise ValueError("runtime catalog connect timeout is outside the approved bound")
        if not self.roles:
            raise ValueError("runtime catalog has no roles")
        for role in self.roles.values():
            role.validate()

    def role(self, name: str) -> PostgresRoleSettings:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise ValueError(f"runtime role is unavailable: {name}") from exc


def load_postgres_runtime_catalog(path: str | Path) -> PostgresRuntimeCatalog:
    return PostgresRuntimeCatalog.from_mapping(
        json.loads(Path(path).read_text(encoding="utf-8-sig"))
    )


def build_catalog_connection_factory(
    catalog: PostgresRuntimeCatalog,
    *,
    role: str,
    password_loader: Callable[[str, str], str | None] | None = None,
    pool_size: int = 0,
) -> Callable[[], Any]:
    """Build a fail-closed factory for one named catalog role.

    ``pool_size`` is intentionally opt-in.  Viewer read projections repeatedly
    check several PostgreSQL authority units during one HTTP request; opening a
    new TLS connection (and querying Credential Manager) for every check made
    page latency grow with the number of compatibility caches.  A bounded pool
    keeps those read sessions reusable while writer factories retain their
    existing one-connection-per-transaction behavior.
    """

    catalog.validate()
    selected = catalog.role(role)

    if pool_size < 0:
        raise ValueError("PostgreSQL pool size cannot be negative")

    cached_password: str | None = None
    password_lock = threading.Lock()

    def read_password() -> str:
        loader = password_loader
        if loader is None:
            import keyring

            loader = keyring.get_password
        password = loader(selected.credential_service, selected.credential_account)
        if not password:
            raise RuntimeError(
                f"PostgreSQL credential is unavailable for role {role}"
            )
        return password

    def pooled_password() -> str:
        nonlocal cached_password
        with password_lock:
            if cached_password is None:
                cached_password = read_password()
            return cached_password

    def open_connection(*, password: str, autocommit: bool = False) -> Any:
        import psycopg

        kwargs = {
            "host": catalog.host,
            "port": catalog.port,
            "dbname": catalog.dbname,
            "user": selected.user,
            "password": password,
            "sslmode": catalog.sslmode,
            "sslrootcert": catalog.sslrootcert,
            "connect_timeout": catalog.connect_timeout_seconds,
        }
        if autocommit:
            kwargs["autocommit"] = True
        return psycopg.connect(**kwargs)

    if pool_size:
        available: queue.LifoQueue[Any] = queue.LifoQueue(maxsize=pool_size)
        pool_lock = threading.Lock()
        created = 0

        class PooledReadLease:
            def __init__(self, connection: Any) -> None:
                self._connection = connection
                self._released = False

            def __getattr__(self, name: str) -> Any:
                return getattr(self._connection, name)

            def __enter__(self) -> "PooledReadLease":
                return self

            def __exit__(self, exc_type, exc, traceback) -> None:
                self.close()

            def close(self) -> None:
                nonlocal created
                if self._released:
                    return
                self._released = True
                connection = self._connection
                if bool(getattr(connection, "closed", False)) or bool(
                    getattr(connection, "broken", False)
                ):
                    with pool_lock:
                        created -= 1
                    return
                try:
                    available.put_nowait(connection)
                except queue.Full:
                    connection.close()
                    with pool_lock:
                        created -= 1

        def pooled_connect() -> Any:
            nonlocal created
            try:
                connection = available.get_nowait()
            except queue.Empty:
                with pool_lock:
                    if created < pool_size:
                        created += 1
                        create_new = True
                    else:
                        create_new = False
                if create_new:
                    try:
                        connection = open_connection(
                            password=pooled_password(), autocommit=True
                        )
                    except Exception:
                        with pool_lock:
                            created -= 1
                        raise
                else:
                    connection = available.get(
                        timeout=catalog.connect_timeout_seconds
                    )
            return PooledReadLease(connection)

        return pooled_connect

    def connect() -> Any:
        return open_connection(password=read_password())

    return connect
