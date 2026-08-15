\set ON_ERROR_STOP on

-- Required identifier variables: writer_role, reader_role, controller_role,
-- audit_reader_role.  No credential value is accepted by this migration.
BEGIN;

REVOKE ALL ON SCHEMA shared_identity FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA shared_identity FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA shared_identity FROM PUBLIC;

GRANT USAGE ON SCHEMA shared_identity TO :"writer_role", :"reader_role";
GRANT USAGE ON SCHEMA operations TO :"writer_role", :"reader_role", :"controller_role";
GRANT USAGE ON SCHEMA audit TO :"audit_reader_role";

GRANT SELECT ON shared_identity.legacy_record,
    shared_identity.unit_snapshot,
    shared_identity.company_v1,
    shared_identity.industry_v1,
    shared_identity.theme_v1 TO :"reader_role";
GRANT SELECT ON operations.shared_identity_authority_v1
    TO :"writer_role", :"reader_role";
-- The compatibility cache binds every refresh to the generic authority
-- revision.  This is control-plane read access only; no mutation privilege is
-- granted to the Viewer role.
GRANT SELECT ON operations.cutover_unit_authority TO :"reader_role";
GRANT SELECT ON audit.cutover_unit_authority_revision TO :"audit_reader_role";

GRANT EXECUTE ON FUNCTION shared_identity.activate_snapshot_v1(
    text,bigint,text,text,text,text
) TO :"writer_role";
GRANT EXECUTE ON FUNCTION operations.transition_shared_identity(
    text,bigint,text,text,text,jsonb,text,text,text
) TO :"controller_role";

COMMIT;
