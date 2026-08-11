from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class Backend(str, Enum):
    SQLITE_TRANSITION = "sqlite_transition"
    POSTGRESQL_DEVTEST = "postgresql_devtest"
    POSTGRESQL_PRODUCTION = "postgresql_production"


class AuthorityState(str, Enum):
    S0 = "S0"
    S1 = "S1"
    S2 = "S2"
    S3 = "S3"
    S4 = "S4"


@dataclass(frozen=True)
class CutoverRoute:
    """Explicit backend choice for one audited cutover unit.

    This contract intentionally has no fallback backend. A connection failure is
    an error; it must never cause a write to be retried against SQLite.
    """

    cutover_unit: str
    backend: Backend
    writer_operation: str
    transaction_boundary: str
    authority_state: AuthorityState = AuthorityState.S0
    sqlite_writer_enabled: bool = True
    production_postgresql_enabled: bool = False
    writer_identity: str | None = None
    approval_reference: str | None = None
    route_revision: int = 1

    def validate(self, *, allow_production: bool = False) -> None:
        if not self.cutover_unit.strip():
            raise ValueError("cutover_unit is required")
        if not self.writer_operation.strip():
            raise ValueError("writer_operation is required")
        if not self.transaction_boundary.strip():
            raise ValueError("transaction_boundary is required")
        if self.route_revision < 1:
            raise ValueError("route_revision must be positive")
        if self.backend is Backend.POSTGRESQL_DEVTEST:
            if self.authority_state not in {AuthorityState.S0, AuthorityState.S1}:
                raise ValueError("dev/test PostgreSQL cannot represent production S2/S3/S4")
            if self.production_postgresql_enabled:
                raise ValueError("dev/test PostgreSQL cannot enable production routing")
        elif self.authority_state in {AuthorityState.S0, AuthorityState.S1}:
            if self.backend is not Backend.SQLITE_TRANSITION:
                raise ValueError("S0/S1 route must use sqlite_transition")
            if not self.sqlite_writer_enabled:
                raise ValueError("S0/S1 route must retain the SQLite writer")
            if self.production_postgresql_enabled:
                raise ValueError("S0/S1 route cannot enable production PostgreSQL")
        else:
            if self.backend is not Backend.POSTGRESQL_PRODUCTION:
                raise ValueError("S2/S3/S4 route must use postgresql_production")
            if self.sqlite_writer_enabled:
                raise ValueError("S2/S3/S4 route must fence the SQLite writer")
            if not self.production_postgresql_enabled:
                raise ValueError("production PostgreSQL requires an explicit enable")
            if not (self.writer_identity or "").strip():
                raise ValueError("production PostgreSQL requires writer_identity")
            if not (self.approval_reference or "").strip():
                raise ValueError("production PostgreSQL requires approval_reference")
        if self.backend is Backend.POSTGRESQL_PRODUCTION and not allow_production:
            raise PermissionError("production PostgreSQL requires an explicit runtime authorization")

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "CutoverRoute":
        if payload.get("schema_version") != "honghu.user_content_route.v1":
            raise ValueError("unsupported user-content route schema")
        return cls(
            cutover_unit=str(payload.get("cutover_unit") or ""),
            backend=Backend(str(payload.get("backend") or "")),
            writer_operation=str(payload.get("writer_operation") or ""),
            transaction_boundary=str(payload.get("transaction_boundary") or ""),
            authority_state=AuthorityState(str(payload.get("authority_state") or "")),
            sqlite_writer_enabled=bool(payload.get("sqlite_writer_enabled")),
            production_postgresql_enabled=bool(
                payload.get("production_postgresql_enabled")
            ),
            writer_identity=(str(payload["writer_identity"]) if payload.get("writer_identity") else None),
            approval_reference=(
                str(payload["approval_reference"])
                if payload.get("approval_reference")
                else None
            ),
            route_revision=int(payload.get("route_revision") or 0),
        )


def require_backend(route: CutoverRoute, expected: Backend) -> None:
    """Fail closed instead of silently falling back to a different store."""

    route.validate()
    if route.backend is not expected:
        raise RuntimeError(
            f"backend mismatch for {route.cutover_unit}: "
            f"expected {expected.value}, got {route.backend.value}"
        )


def load_cutover_route(
    tracked_default: str | Path,
    *,
    runtime_override: str | Path | None = None,
) -> CutoverRoute:
    """Load one explicit authority route without fallback or merge semantics.

    A runtime override replaces the tracked S0 route as one complete, audited
    document.  Missing or malformed overrides fail; they never fall back to the
    tracked SQLite route after an operator attempted to select PostgreSQL.
    """

    selected = Path(runtime_override) if runtime_override else Path(tracked_default)
    payload = json.loads(selected.read_text(encoding="utf-8"))
    route = CutoverRoute.from_mapping(payload)
    route.validate(allow_production=runtime_override is not None)
    return route
