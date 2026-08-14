from __future__ import annotations

from pathlib import Path

import pytest

from tools.migration.stage4_apply_postgresql_migrations import (
    MIGRATION_IDENTIFIERS,
    MigrationApplyError,
    render_role_grant,
    render_schema_migration,
)


ROOT = Path(__file__).resolve().parents[2]


def test_schema_renderer_removes_psql_meta_and_binds_exact_sha() -> None:
    rendered = render_schema_migration(
        "\\set ON_ERROR_STOP on\nSELECT :'migration_sha256';", "a" * 64
    )
    assert "\\set" not in rendered
    assert ":'migration_sha256'" not in rendered
    assert "'" + "a" * 64 + "'" in rendered


def test_schema_renderer_binds_reviewed_role_identifiers() -> None:
    rendered = render_schema_migration(
        "\\set ON_ERROR_STOP on\nSELECT :'migration_sha256';\nGRANT SELECT ON x TO :\"reader_role\";",
        "a" * 64,
        identifiers={"reader_role": "honghu_viewer_reader"},
    )
    assert ':"reader_role"' not in rendered
    assert '"honghu_viewer_reader"' in rendered


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


def test_every_reviewed_schema_role_is_bound_to_the_production_role_contract() -> None:
    for name, identifiers in MIGRATION_IDENTIFIERS.items():
        source = (ROOT / "migrations" / "postgresql" / name).read_text(
            encoding="utf-8"
        )
        rendered = render_schema_migration(source, "a" * 64, identifiers=identifiers)
        assert ':"' not in rendered
        assert "honghu_reader" not in rendered
        assert '"honghu_viewer_reader"' in rendered
