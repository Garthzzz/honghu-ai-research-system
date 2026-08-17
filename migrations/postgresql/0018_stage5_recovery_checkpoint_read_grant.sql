\set ON_ERROR_STOP on

-- The isolated recovery verifier captures the nine-unit authority snapshot
-- and the reviewed seven-task checkpoint snapshot in one read-only,
-- repeatable-read transaction. The migration principal already owns the
-- authority-side SELECT grants; this narrow grant closes only the Stage 5
-- checkpoint half. It confers no task mutation or authority-transition
-- capability.
BEGIN;

SELECT set_config('honghu.migration_sha256', :'migration_sha256', true);

GRANT SELECT ON operations.production_task_definition,
    operations.production_task_run TO :"migration_role";

INSERT INTO operations.schema_migration(
    migration_id, migration_sha256, phase, forward_only
) VALUES (
    '0018_stage5_recovery_checkpoint_read_grant',
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
         WHERE migration_id='0018_stage5_recovery_checkpoint_read_grant'
           AND migration_sha256=current_setting('honghu.migration_sha256')
    ) THEN
        RAISE EXCEPTION 'migration identity exists with a different SHA256';
    END IF;
END $$;

COMMIT;
