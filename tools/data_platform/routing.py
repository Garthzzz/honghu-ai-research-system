from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable


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
    cutover_epoch: str | None = None
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
            if not (self.cutover_epoch or "").strip():
                raise ValueError("production PostgreSQL requires cutover_epoch")
        if self.backend is Backend.POSTGRESQL_PRODUCTION and not allow_production:
            raise PermissionError("production PostgreSQL requires an explicit runtime authorization")

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "CutoverRoute":
        if payload.get("schema_version") not in {
            "honghu.user_content_route.v1",
            "honghu.cutover_route.v1",
        }:
            raise ValueError("unsupported cutover route schema")
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
            cutover_epoch=(str(payload["cutover_epoch"]) if payload.get("cutover_epoch") else None),
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


PRODUCTION_CUTOVER_UNITS = (
    "user_content_notes",
    "shared_identity",
    "financial_data",
    "research_publication",
    "dynamic_intelligence",
    "operations_governance",
    "investment_hypotheses",
    "opportunity_lens",
    "sentiment_analytics",
)


@dataclass(frozen=True)
class CutoverUnitDefinition:
    name: str
    owner: str
    dependencies: tuple[str, ...]
    owned_objects: frozenset[tuple[str, str]]
    writer_operation_ids: frozenset[str]
    transaction_boundary_ids: frozenset[str]


class CutoverUnitRegistry:
    """Reviewed ownership registry; it is not a live authority source."""

    def __init__(self, payload: dict[str, Any]) -> None:
        validation = payload.get("validation") or {}
        if validation.get("passed") is not True:
            raise ValueError("cutover-unit registry validation is not green")
        if any(
            validation.get(name)
            for name in (
                "ownership_conflicts",
                "unknown_operation_owners",
                "unowned_live_tables",
                "configured_objects_not_in_live_schema",
            )
        ):
            raise ValueError("cutover-unit registry contains unresolved ownership")
        units = payload.get("units") or {}
        self.registry_sha256 = str(payload.get("registry_sha256") or "")
        if len(self.registry_sha256) != 64:
            raise ValueError("cutover-unit registry identity is missing")
        self.units: dict[str, CutoverUnitDefinition] = {}
        for name in PRODUCTION_CUTOVER_UNITS:
            value = units.get(name)
            if not isinstance(value, dict):
                raise ValueError(f"production cutover unit is absent: {name}")
            self.units[name] = CutoverUnitDefinition(
                name=name,
                owner=str(value.get("owner") or ""),
                dependencies=tuple(str(item) for item in value.get("dependencies") or ()),
                owned_objects=frozenset(
                    (
                        str(item.get("database") or ""),
                        str(item.get("object") or item.get("table") or ""),
                    )
                    for item in value.get("objects") or ()
                    if str(item.get("object_type") or item.get("kind") or "table")
                    == "table"
                ),
                writer_operation_ids=frozenset(
                    str(item.get("operation_id"))
                    for item in value.get("writer_operations") or ()
                ),
                transaction_boundary_ids=frozenset(
                    str(item.get("transaction_id"))
                    for item in value.get("transaction_boundaries") or ()
                ),
            )
            if not self.units[name].owner:
                raise ValueError(f"cutover unit has no accountable owner: {name}")
            if not self.units[name].owned_objects:
                raise ValueError(f"cutover unit has no owned writable objects: {name}")

    @classmethod
    def from_path(cls, path: str | Path) -> "CutoverUnitRegistry":
        return cls(json.loads(Path(path).read_text(encoding="utf-8-sig")))

    def definition(self, unit: str) -> CutoverUnitDefinition:
        try:
            return self.units[unit]
        except KeyError as exc:
            raise ValueError(f"unknown production cutover unit: {unit}") from exc


@dataclass(frozen=True)
class AuthorityMatrix:
    registry_sha256: str
    routes: dict[str, CutoverRoute]

    def route_for(
        self,
        unit: str,
        *,
        writer_operation: str,
        transaction_boundary: str,
    ) -> CutoverRoute:
        try:
            base = self.routes[unit]
        except KeyError as exc:
            raise RuntimeError(f"authority route is missing for unit {unit}") from exc
        route = CutoverRoute(
            cutover_unit=base.cutover_unit,
            backend=base.backend,
            writer_operation=writer_operation,
            transaction_boundary=transaction_boundary,
            authority_state=base.authority_state,
            sqlite_writer_enabled=base.sqlite_writer_enabled,
            production_postgresql_enabled=base.production_postgresql_enabled,
            writer_identity=base.writer_identity,
            cutover_epoch=base.cutover_epoch,
            approval_reference=base.approval_reference,
            route_revision=base.route_revision,
        )
        route.validate(allow_production=True)
        return route

    def health_payload(self) -> dict[str, dict[str, Any]]:
        return {
            unit: {
                "state": route.authority_state.value,
                "authoritative_backend": route.backend.value,
                "sqlite_writer_enabled": route.sqlite_writer_enabled,
                "writer_identity": route.writer_identity,
                "cutover_epoch": route.cutover_epoch,
                "authority_revision": route.route_revision,
            }
            for unit, route in sorted(self.routes.items())
        }


def load_authority_matrix(
    registry_path: str | Path,
    connection_factory: Callable[[], Any],
) -> tuple[CutoverUnitRegistry, AuthorityMatrix]:
    """Resolve live per-unit authority from PostgreSQL without fallback.

    The tracked registry supplies ownership/dependencies only.  S0--S4 and the
    authoritative backend are read from the durable PostgreSQL control plane;
    a missing row or inconsistent state aborts application startup.
    """

    registry = CutoverUnitRegistry.from_path(registry_path)
    connection = connection_factory()
    try:
        rows = connection.execute(
            """
            SELECT cutover_unit,state,authoritative_backend,writer_identity,
                   cutover_epoch,approval_reference,state_revision
              FROM operations.cutover_unit_authority
             WHERE cutover_unit=ANY(%s)
             ORDER BY cutover_unit
            """,
            (list(PRODUCTION_CUTOVER_UNITS),),
        ).fetchall()
    finally:
        connection.close()
    routes: dict[str, CutoverRoute] = {}
    for row in rows:
        unit, state, backend, writer, epoch, approval, revision = row
        unit = str(unit)
        registry.definition(unit)
        authority_state = AuthorityState(str(state))
        selected_backend = Backend(str(backend))
        production = authority_state in {AuthorityState.S2, AuthorityState.S3, AuthorityState.S4}
        route = CutoverRoute(
            cutover_unit=unit,
            backend=selected_backend,
            writer_operation="authority_matrix_probe",
            transaction_boundary="authority_matrix_read",
            authority_state=authority_state,
            sqlite_writer_enabled=not production,
            production_postgresql_enabled=production,
            writer_identity=str(writer) if writer is not None else None,
            cutover_epoch=str(epoch) if epoch is not None else None,
            approval_reference=str(approval) if approval is not None else None,
            route_revision=int(revision),
        )
        route.validate(allow_production=True)
        routes[unit] = route
    missing = sorted(set(PRODUCTION_CUTOVER_UNITS) - set(routes))
    if missing:
        raise RuntimeError(f"authority matrix is incomplete: {missing}")
    return registry, AuthorityMatrix(registry.registry_sha256, routes)


def load_environment_authority_matrix() -> AuthorityMatrix | None:
    """Load the common production matrix selected by explicit environment.

    Absence means the process is using the tracked SQLite defaults.  A partial
    selection or any PostgreSQL/control-plane failure is fatal and never falls
    back to a per-unit SQLite route.
    """

    runtime_path = os.environ.get("HONGHU_POSTGRES_RUNTIME_CONFIG")
    registry_path = os.environ.get("HONGHU_CUTOVER_UNIT_REGISTRY")
    if not runtime_path and not registry_path:
        return None
    if not runtime_path or not registry_path:
        raise RuntimeError(
            "production PostgreSQL runtime and cutover registry must be supplied together"
        )
    from tools.data_platform.postgres_runtime import (
        build_catalog_connection_factory,
        load_postgres_runtime_catalog,
    )

    catalog = load_postgres_runtime_catalog(runtime_path)
    reader = build_catalog_connection_factory(catalog, role="reader")
    return load_authority_matrix(registry_path, reader)[1]
