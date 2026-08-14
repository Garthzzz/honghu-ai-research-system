from __future__ import annotations

import pytest

from tools.migration.stage4_apply_postgresql_migrations import (
    MigrationApplyError,
    render_role_grant,
    render_schema_migration,
)


def test_schema_renderer_removes_psql_meta_and_binds_exact_sha() -> None:
    rendered = render_schema_migration(
        "\\set ON_ERROR_STOP on\nSELECT :'migration_sha256';", "a" * 64
    )
    assert "\\set" not in rendered
    assert ":'migration_sha256'" not in rendered
    assert "'" + "a" * 64 + "'" in rendered


def test_role_renderer_quotes_only_safe_reviewed_identifiers() -> None:
    rendered = render_role_grant(
        'GRANT SELECT ON x TO :"reader_role";',
        {"reader_role": "honghu_viewer_reader"},
    )
    assert '"honghu_viewer_reader"' in rendered
    with pytest.raises(MigrationApplyError, match="unsafe"):
        render_role_grant(
            'GRANT SELECT ON x TO :"reader_role";',
            {"reader_role": "reader; DROP DATABASE x"},
        )


def test_renderer_rejects_unbound_role_variable() -> None:
    with pytest.raises(MigrationApplyError, match="unrendered"):
        render_role_grant('GRANT SELECT ON x TO :"reader_role";', {})
