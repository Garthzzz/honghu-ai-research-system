from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Backend(str, Enum):
    SQLITE_TRANSITION = "sqlite_transition"
    POSTGRESQL_DEVTEST = "postgresql_devtest"
    POSTGRESQL_PRODUCTION = "postgresql_production"


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

    def validate(self, *, allow_production: bool = False) -> None:
        if not self.cutover_unit.strip():
            raise ValueError("cutover_unit is required")
        if not self.writer_operation.strip():
            raise ValueError("writer_operation is required")
        if not self.transaction_boundary.strip():
            raise ValueError("transaction_boundary is required")
        if self.backend is Backend.POSTGRESQL_PRODUCTION and not allow_production:
            raise PermissionError("production PostgreSQL is outside the Stage 3 contract")


def require_backend(route: CutoverRoute, expected: Backend) -> None:
    """Fail closed instead of silently falling back to a different store."""

    route.validate()
    if route.backend is not expected:
        raise RuntimeError(
            f"backend mismatch for {route.cutover_unit}: "
            f"expected {expected.value}, got {route.backend.value}"
        )
