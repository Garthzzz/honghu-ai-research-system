\set ON_ERROR_STOP on

BEGIN;

SELECT set_config('honghu.migration_sha256', :'migration_sha256', true);

CREATE SCHEMA IF NOT EXISTS migration;

CREATE TABLE IF NOT EXISTS migration.unit_snapshot (
    snapshot_id text PRIMARY KEY,
    cutover_unit text NOT NULL,
    source_identity_sha256 text NOT NULL CHECK (source_identity_sha256 ~ '^[0-9a-f]{64}$'),
    application_commit_sha text NOT NULL CHECK (application_commit_sha ~ '^[0-9a-f]{40}$'),
    registry_sha256 text NOT NULL CHECK (registry_sha256 ~ '^[0-9a-f]{64}$'),
    source_created_at timestamptz NOT NULL,
    imported_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    source_watermark jsonb NOT NULL,
    target_watermark jsonb NOT NULL,
    reconciliation jsonb NOT NULL,
    lifecycle_state text NOT NULL CHECK (lifecycle_state IN ('staging', 'reconciled', 'superseded')),
    formal_business_data boolean NOT NULL DEFAULT false CHECK (formal_business_data = false)
);

CREATE TABLE IF NOT EXISTS migration.source_row (
    snapshot_id text NOT NULL REFERENCES migration.unit_snapshot(snapshot_id) ON DELETE CASCADE,
    cutover_unit text NOT NULL,
    source_database text NOT NULL,
    source_table text NOT NULL,
    source_ordinal bigint NOT NULL CHECK (source_ordinal > 0),
    source_key text NOT NULL,
    row_sha256 text NOT NULL CHECK (row_sha256 ~ '^[0-9a-f]{64}$'),
    payload jsonb NOT NULL,
    PRIMARY KEY (snapshot_id, source_database, source_table, source_ordinal)
);

CREATE INDEX IF NOT EXISTS migration_source_row_key_idx
    ON migration.source_row(snapshot_id, source_database, source_table, source_key);

CREATE INDEX IF NOT EXISTS migration_source_row_unit_idx
    ON migration.source_row(cutover_unit, source_database, source_table);

CREATE TABLE IF NOT EXISTS migration.unit_delta_ledger (
    delta_id text PRIMARY KEY,
    cutover_unit text NOT NULL,
    base_snapshot_id text NOT NULL REFERENCES migration.unit_snapshot(snapshot_id),
    source_identity_sha256 text NOT NULL CHECK (source_identity_sha256 ~ '^[0-9a-f]{64}$'),
    captured_at timestamptz NOT NULL,
    source_watermark jsonb NOT NULL,
    row_count bigint NOT NULL CHECK (row_count >= 0),
    content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    applied_at timestamptz,
    status text NOT NULL CHECK (status IN ('captured', 'applied', 'reconciled', 'rejected')),
    expires_after_cutover boolean NOT NULL DEFAULT true CHECK (expires_after_cutover = true)
);

CREATE TABLE IF NOT EXISTS operations.bootstrap_recovery_sentinel (
    operation_id text PRIMARY KEY,
    committed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    formal_business_data boolean NOT NULL DEFAULT false
        CHECK (formal_business_data = false)
);

-- The migration principal may initialize and prepare S1, but it must not be
-- able to request the production-authority transition.  S2+ remains behind
-- the separately governed controller role and a later human authorization.
CREATE OR REPLACE FUNCTION operations.prepare_user_content_notes_authority_s1(
    p_expected_state text,
    p_expected_revision bigint,
    p_to_state text,
    p_actor text,
    p_approval_reference text,
    p_reason text
) RETURNS TABLE(cutover_unit text, state text, state_revision bigint)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations, audit, user_content
AS $$
BEGIN
    IF NOT (
        (p_expected_state = 'ABSENT' AND p_expected_revision = 0 AND p_to_state = 'S0') OR
        (p_expected_state = 'S0' AND p_expected_revision > 0 AND p_to_state = 'S1')
    ) THEN
        RAISE EXCEPTION 'migration authority preparation is limited to ABSENT->S0 or S0->S1'
            USING ERRCODE = '42501';
    END IF;
    RETURN QUERY
    SELECT * FROM operations.transition_user_content_notes(
        p_expected_state, p_expected_revision, p_to_state,
        NULL, NULL, NULL,
        p_actor, p_approval_reference, p_reason
    );
END;
$$;

REVOKE ALL ON FUNCTION operations.prepare_user_content_notes_authority_s1(
    text, bigint, text, text, text, text
) FROM PUBLIC;

REVOKE ALL ON SCHEMA migration FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA migration FROM PUBLIC;
REVOKE ALL ON operations.bootstrap_recovery_sentinel FROM PUBLIC;

INSERT INTO operations.schema_migration(
    migration_id, migration_sha256, phase, forward_only
)
VALUES (
    '0003_stage4_migration_staging',
    :'migration_sha256',
    'expand',
    false
)
ON CONFLICT (migration_id) DO NOTHING;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM operations.schema_migration
         WHERE migration_id = '0003_stage4_migration_staging'
           AND migration_sha256 = current_setting('honghu.migration_sha256')
    ) THEN
        RAISE EXCEPTION 'migration identity exists with a different SHA256';
    END IF;
END $$;

COMMIT;
