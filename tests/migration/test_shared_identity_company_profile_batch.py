from __future__ import annotations

from pathlib import Path

from tools.migration.stage4_apply_postgresql_migrations import (
    MIGRATION_IDENTIFIERS,
    REVIEWED_MIGRATIONS,
    render_schema_migration,
)


ROOT = Path(__file__).resolve().parents[2]
NAME = "0019_shared_identity_company_profile_batch.sql"


def test_company_profile_migration_is_reviewed_and_role_rendered() -> None:
    assert NAME in REVIEWED_MIGRATIONS
    assert MIGRATION_IDENTIFIERS[NAME] == {
        "writer_role": "honghu_writer_shared_identity",
        "audit_reader_role": "honghu_audit_reader",
    }
    text = (ROOT / "migrations/postgresql" / NAME).read_text(encoding="utf-8")
    rendered = render_schema_migration(
        text,
        "a" * 64,
        identifiers=MIGRATION_IDENTIFIERS[NAME],
    )
    assert ':"writer_role"' not in rendered
    assert 'TO "honghu_writer_shared_identity"' in rendered


def test_company_profile_mutation_is_fenced_bounded_and_field_scoped() -> None:
    text = (ROOT / "migrations/postgresql" / NAME).read_text(encoding="utf-8")
    assert "pg_advisory_xact_lock" in text
    assert "jsonb_build_object('actor',p_actor,'batch',p_batch)::text" in text
    assert "v_authority.state_revision IS DISTINCT FROM p_state_revision" in text
    assert "v_update_ids <> v_relationship_ids" in text
    assert "'source_mapping_sha256',p_batch->>'source_mapping_sha256'" in text
    assert "legacy_id=v_company_id::text" in text
    assert "payload->>'id'=v_company_id::text" in text
    assert "stable_key=v_row->>'stable_key'" in text
    assert "'id','name','stored_name','stable_key','brief_intro','brief_intro_src'" in text
    assert "company profile row contains unsupported or incomplete fields" in text
    assert "UPDATE company SET" not in text
    assert "sqlite" not in text.lower()


def test_company_identity_completion_is_fenced_exact_and_audited() -> None:
    text = (ROOT / "migrations/postgresql" / NAME).read_text(encoding="utf-8")
    section = text.split(
        "CREATE OR REPLACE FUNCTION shared_identity.complete_company_identity_v2", 1
    )[1].split(
        "CREATE OR REPLACE FUNCTION shared_identity.apply_company_profile_batch_v1", 1
    )[0]
    assert "legacy_id=v_company_id::text" in section
    assert "payload->>'id' IS DISTINCT FROM v_company_id::text" in section
    assert "payload->>'name' IS DISTINCT FROM p_company->>'previous_name'" in section
    assert "v_record.stable_key IS DISTINCT FROM p_stable_key" in section
    assert "nullif(btrim(p_company->>'ticker'),'') IS NULL" in section
    assert "nullif(btrim(p_company->>'market'),'') IS NULL" in section
    assert "v_authority.state_revision IS DISTINCT FROM p_state_revision" in section
    assert "INSERT INTO shared_identity.record_revision_audit" in section


def test_new_company_keeps_research_and_financial_identity_fields_separate() -> None:
    text = (ROOT / "migrations/postgresql" / NAME).read_text(encoding="utf-8")
    section = text.split(
        "CREATE OR REPLACE FUNCTION shared_identity.ensure_listed_company_v2", 1
    )[1].split(
        "CREATE OR REPLACE FUNCTION shared_identity.complete_company_identity_v2", 1
    )[0]
    payloads = section.split("v_payload := jsonb_build_object(")[1:3]
    assert len(payloads) == 2
    research_payload, financial_payload = payloads
    assert "p_company->>'market'" in research_payload
    assert "p_company->>'listing_status'" in research_payload
    assert "financial_market" not in research_payload
    assert "reporting_currency" not in research_payload
    assert "p_company->>'financial_market'" in financial_payload
    assert "p_company->>'financial_listing_status'" in financial_payload
    assert "p_company->>'reporting_currency'" in financial_payload
