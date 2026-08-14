\set ON_ERROR_STOP on

BEGIN;

GRANT USAGE ON SCHEMA shared_identity TO :"writer_role", :"audit_reader_role";
GRANT SELECT ON shared_identity.mutation_audit TO :"audit_reader_role";
GRANT EXECUTE ON FUNCTION shared_identity.create_researcher_v1(
    text,text,text,jsonb,text,text,text,text,text
) TO :"writer_role";
GRANT EXECUTE ON FUNCTION shared_identity.ensure_listed_company_v1(
    text,text,text,text,text,jsonb,text,text,text,text,text
) TO :"writer_role";

COMMIT;
