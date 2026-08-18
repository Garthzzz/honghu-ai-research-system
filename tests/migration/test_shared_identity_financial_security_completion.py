from __future__ import annotations

from pathlib import Path

from tools.migration.stage4_apply_postgresql_migrations import (
    MIGRATION_IDENTIFIERS,
    REVIEWED_MIGRATIONS,
    render_schema_migration,
)


ROOT = Path(__file__).resolve().parents[2]
NAME = "0020_shared_identity_financial_security_completion.sql"


def _text() -> str:
    return (ROOT / "migrations/postgresql" / NAME).read_text(encoding="utf-8")


def test_financial_identity_completion_migration_is_reviewed_and_rendered() -> None:
    assert NAME in REVIEWED_MIGRATIONS
    assert MIGRATION_IDENTIFIERS[NAME] == {
        "writer_role": "honghu_writer_shared_identity",
    }
    rendered = render_schema_migration(
        _text(), "b" * 64, identifiers=MIGRATION_IDENTIFIERS[NAME]
    )
    assert ':"writer_role"' not in rendered
    assert 'TO "honghu_writer_shared_identity"' in rendered


def test_v3_is_fenced_idempotent_and_binds_stable_desired_identity() -> None:
    text = _text()
    assert "complete_company_identity_v3" in text
    assert "pg_advisory_xact_lock" in text
    assert "v_authority.state_revision IS DISTINCT FROM p_state_revision" in text
    assert "'company',p_company - 'previous_name'" in text
    assert "v_existing.request_sha256 IS DISTINCT FROM v_request_sha" in text
    assert "payload->>'name' IS DISTINCT FROM p_company->>'previous_name'" in text


def test_v3_requires_exact_company_security_and_link_sets() -> None:
    text = _text()
    assert "financial security is missing or ambiguous" in text
    assert "financial security link is missing or ambiguous" in text
    assert "v_security.legacy_id IS DISTINCT FROM v_security_id::text" in text
    assert "v_link.legacy_id IS DISTINCT FROM v_company_id::text" in text
    assert "v_link.payload->>'security_id' IS DISTINCT FROM v_security_id::text" in text
    assert "v_link.payload->>'link_role' IS DISTINCT FROM 'canonical'" in text


def test_v3_updates_only_reviewed_identity_fields_with_record_audit() -> None:
    text = _text()
    assert "'financial_market'" in text
    assert "'financial_listing_status'" in text
    assert "'reporting_currency'" in text
    assert "INSERT INTO shared_identity.record_revision_audit" in text
    assert "source_database='financial.db' AND source_table='financial_security'" in text
    assert "financial_security_company_link" in text
    assert "sqlite" not in text.lower()
