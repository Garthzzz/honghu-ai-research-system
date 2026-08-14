\set ON_ERROR_STOP on

BEGIN;

SELECT set_config('honghu.migration_sha256', :'migration_sha256', true);

CREATE SCHEMA IF NOT EXISTS shared_identity;

CREATE TABLE IF NOT EXISTS shared_identity.unit_snapshot (
    cutover_unit text PRIMARY KEY CHECK (cutover_unit = 'shared_identity'),
    source_snapshot_id text NOT NULL,
    source_identity_sha256 text NOT NULL CHECK (source_identity_sha256 ~ '^[0-9a-f]{64}$'),
    mapping_manifest_sha256 text NOT NULL CHECK (mapping_manifest_sha256 ~ '^[0-9a-f]{64}$'),
    source_row_count bigint NOT NULL CHECK (source_row_count >= 0),
    target_row_count bigint NOT NULL CHECK (target_row_count >= 0),
    source_content_sha256 text NOT NULL CHECK (source_content_sha256 ~ '^[0-9a-f]{64}$'),
    target_content_sha256 text NOT NULL CHECK (target_content_sha256 ~ '^[0-9a-f]{64}$'),
    authority_state text NOT NULL CHECK (authority_state IN ('S0','S1','S2','S3','S4')),
    formal_business_data boolean NOT NULL,
    formal_revision bigint NOT NULL DEFAULT 0 CHECK (formal_revision >= 0),
    current_formal_row_count bigint NOT NULL DEFAULT 0 CHECK (current_formal_row_count >= 0),
    activated_at timestamptz,
    promoted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (source_row_count = target_row_count),
    CHECK (source_content_sha256 = target_content_sha256),
    CONSTRAINT shared_identity_snapshot_formal_state_check CHECK (
        (authority_state IN ('S0','S1','S2') AND formal_business_data = false) OR
        (authority_state IN ('S3','S4') AND formal_business_data = true)
    )
);

CREATE TABLE IF NOT EXISTS shared_identity.legacy_record (
    source_database text NOT NULL CHECK (
        source_database IN ('research.db','financial.db')
    ),
    source_table text NOT NULL CHECK (
        source_table IN (
            'company','company_identity_alias','company_identity_redirect',
            'company_industry','company_profile','company_sub_market_share',
            'industry','industry_relation','researcher','theme','theme_company',
            'theme_industry','financial_security','financial_security_company_link'
        )
    ),
    legacy_id text NOT NULL,
    stable_key text NOT NULL CHECK (btrim(stable_key) <> ''),
    record_kind text NOT NULL CHECK (record_kind IN ('entity','relationship','profile','mapping')),
    row_sha256 text NOT NULL CHECK (row_sha256 ~ '^[0-9a-f]{64}$'),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    source_snapshot_id text NOT NULL,
    source_ordinal bigint NOT NULL CHECK (source_ordinal > 0),
    formal_business_data boolean NOT NULL DEFAULT false,
    revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0),
    promoted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (source_database, source_table, legacy_id)
);

CREATE INDEX IF NOT EXISTS shared_identity_record_stable_key_idx
    ON shared_identity.legacy_record(stable_key);
CREATE INDEX IF NOT EXISTS shared_identity_record_table_idx
    ON shared_identity.legacy_record(source_table, source_ordinal);

CREATE OR REPLACE VIEW shared_identity.company_v1 AS
SELECT
    (payload->>'id')::bigint AS id,
    stable_key,
    payload->>'name' AS name,
    payload->>'ticker' AS ticker,
    payload->>'market' AS market,
    payload->>'listing_status' AS listing_status,
    payload,
    revision
FROM shared_identity.legacy_record
WHERE source_database='research.db' AND source_table='company';

CREATE OR REPLACE VIEW shared_identity.industry_v1 AS
SELECT
    (payload->>'id')::bigint AS id,
    stable_key,
    payload->>'name' AS name,
    nullif(payload->>'parent_id','')::bigint AS parent_id,
    nullif(payload->>'level','')::integer AS level,
    nullif(payload->>'tier','')::integer AS tier,
    payload->>'status' AS status,
    payload,
    revision
FROM shared_identity.legacy_record
WHERE source_database='research.db' AND source_table='industry';

CREATE OR REPLACE VIEW shared_identity.theme_v1 AS
SELECT
    payload->>'id' AS id,
    stable_key,
    payload->>'name' AS name,
    payload->>'category' AS category,
    payload->>'summary' AS summary,
    payload->>'status' AS status,
    payload,
    revision
FROM shared_identity.legacy_record
WHERE source_database='research.db' AND source_table='theme';

CREATE OR REPLACE FUNCTION operations.prepare_cutover_unit_authority_s1(
    p_cutover_unit text,
    p_expected_state text,
    p_expected_revision bigint,
    p_to_state text,
    p_actor text,
    p_approval_reference text,
    p_reason text
) RETURNS TABLE(cutover_unit text, state text, state_revision bigint)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations, audit
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
    SELECT * FROM operations.transition_cutover_unit(
        p_cutover_unit, p_expected_state, p_expected_revision, p_to_state,
        'sqlite_transition', NULL, NULL, NULL,
        p_actor, p_approval_reference, p_reason
    );
END;
$$;

REVOKE ALL ON SCHEMA shared_identity FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA shared_identity FROM PUBLIC;
REVOKE ALL ON FUNCTION operations.prepare_cutover_unit_authority_s1(
    text,text,bigint,text,text,text,text
) FROM PUBLIC;

GRANT USAGE ON SCHEMA shared_identity TO :"migration_role", :"reader_role";
GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA shared_identity TO :"migration_role";
GRANT SELECT ON ALL TABLES IN SCHEMA shared_identity TO :"reader_role";
GRANT EXECUTE ON FUNCTION operations.prepare_cutover_unit_authority_s1(
    text,text,bigint,text,text,text,text
) TO :"migration_role";

INSERT INTO operations.schema_migration(
    migration_id, migration_sha256, phase, forward_only
) VALUES (
    '0005_shared_identity_expand', :'migration_sha256', 'expand', false
)
ON CONFLICT (migration_id) DO NOTHING;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM operations.schema_migration
         WHERE migration_id='0005_shared_identity_expand'
           AND migration_sha256=current_setting('honghu.migration_sha256')
    ) THEN
        RAISE EXCEPTION 'migration identity exists with a different SHA256';
    END IF;
END $$;

COMMIT;
