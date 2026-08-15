\set ON_ERROR_STOP on

-- The production cutover controller commits S2 -> S3 with narrowly scoped
-- controller/writer roles, then the migration principal independently reads
-- the durable formal snapshot for reconciliation evidence.  This grant is
-- read-only and does not permit authority transition or domain mutation.
BEGIN;

SELECT set_config('honghu.migration_sha256', :'migration_sha256', true);

GRANT USAGE ON SCHEMA domain_data TO :"migration_role";
GRANT SELECT ON domain_data.formal_unit_snapshot TO :"migration_role";

INSERT INTO operations.schema_migration(
    migration_id, migration_sha256, phase, forward_only
) VALUES (
    '0012_remaining_unit_reconciliation_read_grant',
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
         WHERE migration_id='0012_remaining_unit_reconciliation_read_grant'
           AND migration_sha256=current_setting('honghu.migration_sha256')
    ) THEN
        RAISE EXCEPTION 'migration identity exists with a different SHA256';
    END IF;
END $$;

COMMIT;
