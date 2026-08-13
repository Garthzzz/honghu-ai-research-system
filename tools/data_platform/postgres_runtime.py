from __future__ import annotations

import json
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
