import pytest

import json

from tools.data_platform.routing import (
    PRODUCTION_CUTOVER_UNITS,
    AuthorityState,
    Backend,
    CutoverRoute,
    load_authority_matrix,
    load_cutover_route,
    require_backend,
)


class _MatrixConnection:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, _sql, _params):
        return self

    def fetchall(self):
        return self.rows

    def close(self):
        pass


def _registry_payload():
    return {
        "registry_sha256": "a" * 64,
        "validation": {
            "passed": True,
            "ownership_conflicts": [],
            "unknown_operation_owners": [],
            "unowned_live_tables": [],
            "configured_objects_not_in_live_schema": [],
        },
        "units": {
            unit: {
                "owner": f"owner-{unit}",
                "dependencies": [],
                "objects": [
                    {
                        "database": "research.db",
                        "object": f"table_{unit}",
                        "object_type": "table",
                    }
                ],
                "writer_operations": [],
                "transaction_boundaries": [],
            }
            for unit in PRODUCTION_CUTOVER_UNITS
        },
    }


def test_authority_matrix_resolves_all_units_without_per_unit_files(tmp_path) -> None:
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps(_registry_payload()), encoding="utf-8")
    rows = []
    for unit in PRODUCTION_CUTOVER_UNITS:
        if unit in {"user_content_notes", "shared_identity"}:
            rows.append((unit, "S3", "postgresql_production", f"writer-{unit}", "epoch", "approval", 3))
        else:
            rows.append((unit, "S1", "sqlite_transition", None, None, None, 1))
    _, matrix = load_authority_matrix(registry, lambda: _MatrixConnection(rows))
    assert matrix.routes["shared_identity"].authority_state is AuthorityState.S3
    assert matrix.routes["financial_data"].backend is Backend.SQLITE_TRANSITION
    assert set(matrix.health_payload()) == set(PRODUCTION_CUTOVER_UNITS)


def test_authority_matrix_fails_closed_when_unit_missing_or_state_backend_conflicts(tmp_path) -> None:
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps(_registry_payload()), encoding="utf-8")
    rows = [
        (unit, "S1", "sqlite_transition", None, None, None, 1)
        for unit in PRODUCTION_CUTOVER_UNITS[:-1]
    ]
    with pytest.raises(RuntimeError, match="incomplete"):
        load_authority_matrix(registry, lambda: _MatrixConnection(rows))
    rows.append((PRODUCTION_CUTOVER_UNITS[-1], "S3", "sqlite_transition", "writer", "epoch", "approval", 2))
    with pytest.raises(ValueError, match="must use postgresql"):
        load_authority_matrix(registry, lambda: _MatrixConnection(rows))


def test_route_has_no_implicit_fallback() -> None:
    route = CutoverRoute(
        cutover_unit="user_content_notes",
        backend=Backend.POSTGRESQL_DEVTEST,
        writer_operation="put_analyst_note",
        transaction_boundary="one note revision and audit",
    )
    require_backend(route, Backend.POSTGRESQL_DEVTEST)
    with pytest.raises(RuntimeError, match="backend mismatch"):
        require_backend(route, Backend.SQLITE_TRANSITION)


def test_production_backend_requires_explicit_runtime_authorization() -> None:
    route = CutoverRoute(
        cutover_unit="user_content_notes",
        backend=Backend.POSTGRESQL_PRODUCTION,
        writer_operation="put_analyst_note",
        transaction_boundary="one note revision and audit",
        authority_state=AuthorityState.S2,
        sqlite_writer_enabled=False,
        production_postgresql_enabled=True,
        writer_identity="honghu_user_content_writer",
        cutover_epoch="epoch-001",
        approval_reference="approval-001",
    )
    with pytest.raises(PermissionError, match="explicit runtime authorization"):
        route.validate()


def test_default_route_is_s0_sqlite(tmp_path) -> None:
    path = tmp_path / "route.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "honghu.user_content_route.v1",
                "cutover_unit": "user_content_notes",
                "route_revision": 1,
                "authority_state": "S0",
                "backend": "sqlite_transition",
                "sqlite_writer_enabled": True,
                "production_postgresql_enabled": False,
                "writer_identity": None,
                "approval_reference": None,
                "writer_operation": "analyst_note_mutation",
                "transaction_boundary": "one note",
            }
        ),
        encoding="utf-8",
    )
    route = load_cutover_route(path)
    assert route.backend is Backend.SQLITE_TRANSITION
    assert route.authority_state is AuthorityState.S0


@pytest.mark.parametrize(
    ("state", "backend", "sqlite_writer", "pg_enabled"),
    [
        ("S0", "postgresql_production", True, False),
        ("S2", "postgresql_production", True, True),
        ("S3", "sqlite_transition", False, True),
        ("S4", "postgresql_production", False, False),
    ],
)
def test_authority_route_mismatch_fails_closed(
    tmp_path, state, backend, sqlite_writer, pg_enabled
) -> None:
    path = tmp_path / "route.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "honghu.user_content_route.v1",
                "cutover_unit": "user_content_notes",
                "route_revision": 1,
                "authority_state": state,
                "backend": backend,
                "sqlite_writer_enabled": sqlite_writer,
                "production_postgresql_enabled": pg_enabled,
                "writer_identity": "writer",
                "approval_reference": "approval",
                "writer_operation": "analyst_note_mutation",
                "transaction_boundary": "one note",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises((ValueError, PermissionError)):
        load_cutover_route(path, runtime_override=path)


def test_missing_runtime_override_never_falls_back_to_sqlite(tmp_path) -> None:
    tracked = tmp_path / "tracked.json"
    tracked.write_text(
        json.dumps(
            {
                "schema_version": "honghu.user_content_route.v1",
                "cutover_unit": "user_content_notes",
                "route_revision": 1,
                "authority_state": "S0",
                "backend": "sqlite_transition",
                "sqlite_writer_enabled": True,
                "production_postgresql_enabled": False,
                "writer_identity": None,
                "approval_reference": None,
                "writer_operation": "analyst_note_mutation",
                "transaction_boundary": "one note",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(FileNotFoundError):
        load_cutover_route(tracked, runtime_override=tmp_path / "missing.json")
