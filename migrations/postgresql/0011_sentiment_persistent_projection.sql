\set ON_ERROR_STOP on

BEGIN;

SELECT set_config('honghu.migration_sha256', :'migration_sha256', true);

-- Application readers need one constrained control-plane projection; they do
-- not receive broad SELECT on authority, migration, overlay or audit tables.
CREATE OR REPLACE FUNCTION domain_data.unit_runtime_contract_v1(p_cutover_unit text)
RETURNS TABLE(
    state text,authoritative_backend text,state_revision bigint,
    writer_identity text,cutover_epoch text,approval_reference text,
    source_snapshot_id text,source_identity_sha256 text,
    source_content_sha256 text,source_row_count bigint,source_watermark jsonb,
    formal_revision bigint,application_commit_sha text,
    overlay_count bigint,overlay_revision_sum bigint,overlay_last_update text
)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=pg_catalog,domain_data,operations
AS $$
    SELECT a.state,a.authoritative_backend,a.state_revision,a.writer_identity,
           a.cutover_epoch,a.approval_reference,s.source_snapshot_id,
           s.source_identity_sha256,s.source_content_sha256,s.source_row_count,
           s.source_watermark,s.formal_revision,s.application_commit_sha,
           coalesce(o.overlay_count,0),coalesce(o.revision_sum,0),
           coalesce(o.last_update,'')
      FROM operations.cutover_unit_authority a
      JOIN domain_data.formal_unit_snapshot s USING(cutover_unit)
      LEFT JOIN LATERAL (
            SELECT count(*) overlay_count,sum(revision) revision_sum,
                   max(updated_at)::text last_update
              FROM domain_data.record_overlay r
             WHERE r.cutover_unit=a.cutover_unit
      ) o ON true
     WHERE a.cutover_unit=p_cutover_unit
       AND a.state IN ('S3','S4')
       AND a.authoritative_backend='postgresql_production';
$$;

-- The large sentiment compatibility cache is a disposable local projection.
-- It refreshes only the small copy-on-write overlay after its initial build,
-- rather than downloading the complete formal snapshot for every scheduler
-- tick.  Both functions remain read-only and require durable PG authority.
CREATE OR REPLACE FUNCTION domain_data.read_unit_overlay_v1(p_cutover_unit text)
RETURNS TABLE(
    source_database text,source_table text,source_key text,
    payload jsonb,row_sha256 text,revision bigint,deleted boolean
)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=pg_catalog,domain_data,operations
AS $$
    SELECT o.source_database,o.source_table,o.source_key,o.payload,
           o.row_sha256,o.revision,o.deleted
      FROM domain_data.record_overlay o
      JOIN operations.cutover_unit_authority a
        ON a.cutover_unit=o.cutover_unit
     WHERE o.cutover_unit=p_cutover_unit
       AND a.state IN ('S3','S4')
       AND a.authoritative_backend='postgresql_production'
     ORDER BY o.source_database,o.source_table,o.source_key;
$$;

REVOKE ALL ON FUNCTION domain_data.unit_runtime_contract_v1(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION domain_data.read_unit_overlay_v1(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION domain_data.unit_runtime_contract_v1(text) TO :"reader_role";
GRANT EXECUTE ON FUNCTION domain_data.read_unit_overlay_v1(text) TO :"reader_role";

INSERT INTO operations.schema_migration(migration_id,migration_sha256,phase,forward_only)
VALUES('0011_sentiment_persistent_projection',:'migration_sha256','expand',false)
ON CONFLICT(migration_id) DO NOTHING;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM operations.schema_migration
         WHERE migration_id='0011_sentiment_persistent_projection'
           AND migration_sha256=current_setting('honghu.migration_sha256')
    ) THEN RAISE EXCEPTION 'migration identity exists with a different SHA256'; END IF;
END $$;

COMMIT;
