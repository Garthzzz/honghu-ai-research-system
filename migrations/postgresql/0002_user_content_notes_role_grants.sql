\set ON_ERROR_STOP on

-- Required psql variables are identifiers, not credentials:
--   writer_role, reader_role, controller_role, audit_reader_role
BEGIN;

REVOKE ALL ON SCHEMA user_content, operations, audit FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA user_content, operations, audit FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA user_content, operations FROM PUBLIC;

GRANT USAGE ON SCHEMA user_content TO :"writer_role", :"reader_role";
GRANT USAGE ON SCHEMA operations TO :"controller_role";
GRANT USAGE ON SCHEMA audit TO :"audit_reader_role";

GRANT SELECT ON user_content.analyst_note_read_v1 TO :"reader_role";
GRANT SELECT ON audit.user_content_revision,
    audit.cutover_unit_authority_revision,
    audit.cutover_dependency_mapping_revision TO :"audit_reader_role";

GRANT EXECUTE ON FUNCTION user_content.put_analyst_note_v2(
    text, text, text, text, text, text, text, text, text,
    bigint, text, text, text
) TO :"writer_role";
GRANT EXECUTE ON FUNCTION user_content.soft_delete_analyst_note_v2(
    text, text, bigint, text, text, text
) TO :"writer_role";
GRANT EXECUTE ON FUNCTION operations.transition_user_content_notes(
    text, bigint, text, text, text, jsonb, text, text, text
) TO :"controller_role";
GRANT EXECUTE ON FUNCTION operations.record_user_content_notes_verification(
    text, text, text, jsonb
) TO :"controller_role";
GRANT EXECUTE ON FUNCTION operations.register_user_content_notes_dependency_mapping(
    bigint, text, text, text, text, text, jsonb, text, text, text, text
) TO :"controller_role";

COMMIT;
