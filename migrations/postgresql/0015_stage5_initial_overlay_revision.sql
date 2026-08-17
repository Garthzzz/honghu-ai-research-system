\set ON_ERROR_STOP on

BEGIN;
SELECT set_config('honghu.migration_sha256', :'migration_sha256', true);

-- Compatibility widening for post-cutover inserts. Baseline-backed updates
-- still advance 1 -> 2; objects created after cutover must be allowed to
-- persist their first revision as 0 -> 1. Authority, ACL, idempotency, and
-- stale-revision contracts are unchanged.
ALTER TABLE domain_data.record_overlay
    DROP CONSTRAINT IF EXISTS record_overlay_revision_check;
ALTER TABLE domain_data.record_overlay
    ADD CONSTRAINT record_overlay_revision_check CHECK (revision > 0) NOT VALID;
ALTER TABLE domain_data.record_overlay
    VALIDATE CONSTRAINT record_overlay_revision_check;

INSERT INTO operations.schema_migration(migration_id,migration_sha256,phase,forward_only)
VALUES('0015_stage5_initial_overlay_revision',:'migration_sha256','expand',false)
ON CONFLICT(migration_id) DO NOTHING;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM operations.schema_migration
        WHERE migration_id='0015_stage5_initial_overlay_revision'
          AND migration_sha256=current_setting('honghu.migration_sha256'))
    THEN RAISE EXCEPTION 'migration identity exists with a different SHA256'; END IF;
END $$;
COMMIT;
