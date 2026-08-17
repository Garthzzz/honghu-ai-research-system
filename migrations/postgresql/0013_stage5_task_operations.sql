\set ON_ERROR_STOP on

BEGIN;
SELECT set_config('honghu.migration_sha256', :'migration_sha256', true);

CREATE TABLE IF NOT EXISTS operations.production_task_definition (
    task_id text PRIMARY KEY,
    manifest_sha256 text NOT NULL CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
    application_commit_sha text NOT NULL CHECK (application_commit_sha ~ '^[0-9a-f]{40}$'),
    cutover_unit text NOT NULL,
    writer_units jsonb NOT NULL CHECK (jsonb_typeof(writer_units) = 'array'),
    runner_host text NOT NULL CHECK (btrim(runner_host) <> ''),
    freshness_seconds integer NOT NULL CHECK (freshness_seconds > 0),
    enabled boolean NOT NULL DEFAULT false,
    definition_revision bigint NOT NULL DEFAULT 1 CHECK (definition_revision > 0),
    registered_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS operations.production_task_run (
    task_id text NOT NULL REFERENCES operations.production_task_definition(task_id),
    logical_window text NOT NULL CHECK (btrim(logical_window) <> ''),
    run_attempt bigint NOT NULL CHECK (run_attempt > 0),
    operation_id_sha256 text NOT NULL CHECK (operation_id_sha256 ~ '^[0-9a-f]{64}$'),
    manifest_sha256 text NOT NULL CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
    application_commit_sha text NOT NULL CHECK (application_commit_sha ~ '^[0-9a-f]{40}$'),
    runner_host text NOT NULL,
    runner_principal text NOT NULL,
    status text NOT NULL CHECK (status IN ('running','succeeded','failed','deferred','skipped','abandoned','uncertain')),
    failure_classification text,
    return_code integer,
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    heartbeat_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    finished_at timestamptz,
    output_tail_sha256 text,
    business_checkpoint_before jsonb,
    business_checkpoint_after jsonb,
    PRIMARY KEY (task_id, logical_window, run_attempt)
);

CREATE INDEX IF NOT EXISTS production_task_run_status_idx
    ON operations.production_task_run(task_id, status, started_at DESC);

CREATE OR REPLACE VIEW operations.production_task_health_v1 AS
SELECT d.task_id,d.manifest_sha256,d.application_commit_sha,d.cutover_unit,
       d.writer_units,d.runner_host,d.freshness_seconds,d.enabled,
       r.logical_window,r.run_attempt,r.status,r.failure_classification,
       r.return_code,r.started_at,r.heartbeat_at,r.finished_at,
       r.business_checkpoint_before,r.business_checkpoint_after,
       s.last_success_at,
       CASE WHEN s.last_success_at IS NULL THEN NULL
            ELSE extract(epoch FROM (clock_timestamp()-s.last_success_at))::bigint END
            AS seconds_since_last_success
  FROM operations.production_task_definition d
  LEFT JOIN LATERAL (
      SELECT * FROM operations.production_task_run x
       WHERE x.task_id=d.task_id ORDER BY x.started_at DESC,x.run_attempt DESC LIMIT 1
  ) r ON true
  LEFT JOIN LATERAL (
      SELECT max(x.finished_at) AS last_success_at
        FROM operations.production_task_run x
       WHERE x.task_id=d.task_id AND x.status='succeeded'
  ) s ON true;

REVOKE ALL ON operations.production_task_definition,operations.production_task_run FROM PUBLIC;
REVOKE ALL ON operations.production_task_health_v1 FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON operations.production_task_definition,
    operations.production_task_run TO :"writer_operations_governance";
GRANT SELECT ON operations.production_task_health_v1 TO :"reader_role",
    :"writer_operations_governance", :"audit_reader_role";

INSERT INTO operations.schema_migration(migration_id,migration_sha256,phase,forward_only)
VALUES('0013_stage5_task_operations',:'migration_sha256','expand',false)
ON CONFLICT(migration_id) DO NOTHING;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM operations.schema_migration
        WHERE migration_id='0013_stage5_task_operations'
          AND migration_sha256=current_setting('honghu.migration_sha256'))
    THEN RAISE EXCEPTION 'migration identity exists with a different SHA256'; END IF;
END $$;
COMMIT;
