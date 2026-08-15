\set ON_ERROR_STOP on

-- Required psql variable: migration_role.  S1 preparation tools must be able
-- to compare the current authority revision before invoking the narrowly
-- scoped SECURITY DEFINER transition function.  This is read-only control-
-- plane access; it does not grant S2/S3 transition or application writes.
BEGIN;

SELECT set_config('honghu.migration_sha256', :'migration_sha256', true);

GRANT USAGE ON SCHEMA operations TO :"migration_role";
GRANT SELECT ON operations.cutover_unit_authority TO :"migration_role";

INSERT INTO operations.schema_migration(
    migration_id, migration_sha256, phase, forward_only
) VALUES (
    '0009_stage4_s1_authority_read_grant',
    :'migration_sha256',
    'expand',
    false
)
ON CONFLICT (migration_id) DO NOTHING;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM operations.schema_migration
         WHERE migration_id='0009_stage4_s1_authority_read_grant'
           AND migration_sha256=current_setting('honghu.migration_sha256')
    ) THEN
        RAISE EXCEPTION 'migration identity exists with a different SHA256';
    END IF;
END $$;

COMMIT;
