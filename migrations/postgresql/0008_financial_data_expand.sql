\set ON_ERROR_STOP on

BEGIN;

SELECT set_config('honghu.migration_sha256', :'migration_sha256', true);

CREATE SCHEMA IF NOT EXISTS financial_data;

CREATE TABLE IF NOT EXISTS financial_data.unit_snapshot (
    cutover_unit text PRIMARY KEY CHECK (cutover_unit = 'financial_data'),
    source_snapshot_id text NOT NULL,
    source_identity_sha256 text NOT NULL CHECK (source_identity_sha256 ~ '^[0-9a-f]{64}$'),
    shared_identity_snapshot_id text NOT NULL,
    shared_identity_mapping_sha256 text NOT NULL CHECK (shared_identity_mapping_sha256 ~ '^[0-9a-f]{64}$'),
    source_row_count bigint NOT NULL CHECK (source_row_count >= 0),
    target_row_count bigint NOT NULL CHECK (target_row_count >= 0),
    source_content_sha256 text NOT NULL CHECK (source_content_sha256 ~ '^[0-9a-f]{64}$'),
    target_content_sha256 text NOT NULL CHECK (target_content_sha256 ~ '^[0-9a-f]{64}$'),
    authority_state text NOT NULL CHECK (authority_state IN ('S0','S1','S2','S3','S4')),
    formal_business_data boolean NOT NULL DEFAULT false,
    promoted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (source_row_count = target_row_count),
    CHECK (source_content_sha256 = target_content_sha256),
    CHECK (
        (authority_state IN ('S0','S1','S2') AND formal_business_data=false) OR
        (authority_state IN ('S3','S4') AND formal_business_data=true)
    )
);

-- S1 preserves the exact SQLite row contract as immutable, non-formal
-- migration material.  Security identity is not copied into this owning
-- schema: security_id references are reconciled against shared_identity.
CREATE TABLE IF NOT EXISTS financial_data.legacy_record (
    source_table text NOT NULL CHECK (source_table IN (
        'financial_schema_meta','financial_source_snapshot',
        'financial_observation','financial_observation_revision',
        'financial_model_run','financial_model_input','financial_model_output',
        'financial_reconciliation'
    )),
    legacy_id text NOT NULL,
    stable_key text NOT NULL CHECK (btrim(stable_key) <> ''),
    row_sha256 text NOT NULL CHECK (row_sha256 ~ '^[0-9a-f]{64}$'),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload)='object'),
    source_snapshot_id text NOT NULL,
    source_ordinal bigint NOT NULL CHECK (source_ordinal > 0),
    formal_business_data boolean NOT NULL DEFAULT false,
    revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0),
    promoted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (source_table,legacy_id)
);

CREATE INDEX IF NOT EXISTS financial_data_legacy_record_stable_key_idx
    ON financial_data.legacy_record(stable_key);
CREATE INDEX IF NOT EXISTS financial_data_legacy_record_snapshot_idx
    ON financial_data.legacy_record(source_snapshot_id,source_table,source_ordinal);

CREATE OR REPLACE VIEW financial_data.observation_v1 AS
SELECT
    (payload->>'id')::bigint AS id,
    stable_key,
    (payload->>'security_id')::bigint AS security_id,
    payload->>'observation_key' AS observation_key,
    payload->>'metric_name' AS metric_name,
    nullif(payload->>'value_num','')::double precision AS value_num,
    payload->>'value_text' AS value_text,
    payload->>'unit' AS unit,
    payload->>'fact_type' AS fact_type,
    nullif(payload->>'as_of_date','')::date AS as_of_date,
    payload,
    revision
FROM financial_data.legacy_record
WHERE source_table='financial_observation';

CREATE OR REPLACE VIEW financial_data.model_run_v1 AS
SELECT
    (payload->>'id')::bigint AS id,
    stable_key,
    nullif(payload->>'security_id','')::bigint AS security_id,
    payload->>'run_key' AS run_key,
    payload->>'skill_name' AS skill_name,
    payload->>'model_name' AS model_name,
    payload->>'status' AS status,
    payload,
    revision
FROM financial_data.legacy_record
WHERE source_table='financial_model_run';

REVOKE ALL ON SCHEMA financial_data FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA financial_data FROM PUBLIC;

GRANT USAGE ON SCHEMA financial_data TO :"migration_role", :"reader_role";
GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA financial_data TO :"migration_role";
GRANT SELECT ON ALL TABLES IN SCHEMA financial_data TO :"reader_role";

INSERT INTO operations.schema_migration(
    migration_id,migration_sha256,phase,forward_only
) VALUES (
    '0008_financial_data_expand',:'migration_sha256','expand',false
) ON CONFLICT (migration_id) DO NOTHING;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM operations.schema_migration
         WHERE migration_id='0008_financial_data_expand'
           AND migration_sha256=current_setting('honghu.migration_sha256')
    ) THEN
        RAISE EXCEPTION 'migration identity exists with a different SHA256';
    END IF;
END $$;

COMMIT;
