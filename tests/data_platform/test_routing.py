import pytest

from tools.data_platform.routing import Backend, CutoverRoute, require_backend


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


def test_production_backend_is_not_allowed_in_stage3() -> None:
    route = CutoverRoute(
        cutover_unit="user_content_notes",
        backend=Backend.POSTGRESQL_PRODUCTION,
        writer_operation="put_analyst_note",
        transaction_boundary="one note revision and audit",
    )
    with pytest.raises(PermissionError, match="outside the Stage 3 contract"):
        route.validate()
