\set ON_ERROR_STOP on

-- Required psql variable: migration_role.  This role may prepare/backfill an
-- S0/S1 candidate but receives no application writer route and no S2 grant.
BEGIN;

GRANT USAGE ON SCHEMA migration, operations, user_content, audit
    TO :"migration_role";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA migration
    TO :"migration_role";
GRANT SELECT, INSERT, UPDATE ON user_content.analyst_note
    TO :"migration_role";
GRANT SELECT, INSERT ON audit.user_content_revision
    TO :"migration_role";
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA user_content, audit
    TO :"migration_role";
GRANT SELECT ON operations.cutover_unit_authority,
    operations.cutover_dependency_mapping TO :"migration_role";
GRANT SELECT, INSERT ON operations.bootstrap_recovery_sentinel
    TO :"migration_role";
REVOKE EXECUTE ON FUNCTION operations.transition_user_content_notes(
    text, bigint, text, text, text, jsonb, text, text, text
) FROM :"migration_role";
GRANT EXECUTE ON FUNCTION operations.prepare_user_content_notes_authority_s1(
    text, bigint, text, text, text, text
) TO :"migration_role";
GRANT EXECUTE ON FUNCTION operations.register_user_content_notes_dependency_mapping(
    bigint, text, text, text, text, text, jsonb, text, text, text, text
) TO :"migration_role";

COMMIT;
