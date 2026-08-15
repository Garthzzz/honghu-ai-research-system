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
        if "reader_role" in identifiers:
            assert '"honghu_viewer_reader"' in rendered


def test_s1_migration_role_gets_only_authority_read_access() -> None:
    source = (
        ROOT
        / "migrations"
        / "postgresql"
        / "0009_stage4_s1_authority_read_grant.sql"
    ).read_text(encoding="utf-8")
    rendered = render_schema_migration(
        source,
        "a" * 64,
        identifiers={"migration_role": "honghu_migration"},
    )
    assert "GRANT USAGE ON SCHEMA operations" in rendered
    assert "GRANT SELECT ON operations.cutover_unit_authority" in rendered
    assert "INSERT ON operations.cutover_unit_authority" not in rendered
    assert "UPDATE ON operations.cutover_unit_authority" not in rendered
    assert "DELETE ON operations.cutover_unit_authority" not in rendered
    assert "transition_cutover_unit" not in rendered
    assert "0009_stage4_s1_authority_read_grant" in rendered
    assert "migration_sha256=current_setting('honghu.migration_sha256')" in rendered
    assert 'TO "honghu_migration"' in rendered


def test_shared_identity_reader_can_bind_cache_to_authority_revision() -> None:
    source = (
        ROOT
        / "migrations"
        / "postgresql"
        / "0006_shared_identity_role_grants.sql"
    ).read_text(encoding="utf-8")
    rendered = render_role_grant(
        source,
        {
            "writer_role": "honghu_writer_shared_identity",
            "reader_role": "honghu_viewer_reader",
            "controller_role": "honghu_controller",
            "audit_reader_role": "honghu_audit_reader",
        },
    )
    assert (
        'GRANT SELECT ON operations.cutover_unit_authority TO "honghu_viewer_reader"'
        in rendered
    )
    assert "UPDATE ON operations.cutover_unit_authority" not in rendered
    assert "DELETE ON operations.cutover_unit_authority" not in rendered


def test_s1_callers_do_not_require_control_plane_update_privilege() -> None:
    callers = (
        "stage4_shared_identity_s1.py",
        "stage4_financial_data_s1.py",
        "stage4_generic_unit_s1.py",
    )
    for name in callers:
        source = (ROOT / "tools" / "migration" / name).read_text(encoding="utf-8")
        assert "FROM operations.cutover_unit_authority" in source
        assert "FOR UPDATE" not in source
        assert "FOR SHARE" not in source

    # The least-privilege caller supplies an expected state/revision.  The
    # SECURITY DEFINER control plane remains responsible for the real row lock
    # and rejects a stale concurrent transition atomically.
    controller = (
        ROOT / "migrations" / "postgresql" / "0002_user_content_notes_cutover_expand.sql"
    ).read_text(encoding="utf-8")
    transition = controller.split(
        "CREATE OR REPLACE FUNCTION operations.transition_cutover_unit", 1
    )[1].split("$$;", 1)[0]
    assert "FOR UPDATE" in transition
    assert "p_expected_revision" in transition
