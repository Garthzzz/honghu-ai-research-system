\set ON_ERROR_STOP on

BEGIN;

SELECT set_config('honghu.migration_sha256', :'migration_sha256', true);

-- The authority ledger records a logical writer operation identity, while
-- session_user is the least-privilege PostgreSQL login role.  They are
-- deliberately separate dimensions.  EXECUTE ACLs on the SECURITY DEFINER
-- functions authenticate the database role; the function continues to bind
-- every mutation to the logical writer identity frozen in the authority row.
DO $$
DECLARE
    v_signature regprocedure;
    v_definition text;
    v_clause constant text := E'\n       OR p_writer_identity <> session_user';
BEGIN
    FOREACH v_signature IN ARRAY ARRAY[
        'user_content.put_analyst_note_v2(text,text,text,text,text,text,text,text,text,bigint,text,text,text)'::regprocedure,
        'user_content.soft_delete_analyst_note_v2(text,text,bigint,text,text,text)'::regprocedure
    ] LOOP
        SELECT pg_get_functiondef(v_signature) INTO v_definition;
        IF position(v_clause IN v_definition) = 0 THEN
            RAISE EXCEPTION 'expected writer/session identity clause missing from %', v_signature;
        END IF;
        v_definition := replace(v_definition, v_clause, '');
        IF position('p_writer_identity <> session_user' IN v_definition) <> 0 THEN
            RAISE EXCEPTION 'writer/session identity clause was not removed from %', v_signature;
        END IF;
        EXECUTE v_definition;
    END LOOP;
END $$;

DO $$
BEGIN
    IF position(
        'p_writer_identity <> session_user'
        IN pg_get_functiondef(
            'user_content.put_analyst_note_v2(text,text,text,text,text,text,text,text,text,bigint,text,text,text)'::regprocedure
        )
    ) <> 0 OR position(
        'p_writer_identity <> session_user'
        IN pg_get_functiondef(
            'user_content.soft_delete_analyst_note_v2(text,text,bigint,text,text,text)'::regprocedure
        )
    ) <> 0 THEN
        RAISE EXCEPTION 'logical writer identity remains coupled to PostgreSQL session role';
    END IF;
END $$;

INSERT INTO operations.schema_migration(
    migration_id, migration_sha256, phase, forward_only
) VALUES (
    '0004_user_content_writer_identity_separation',
    :'migration_sha256',
    'expand',
    false
) ON CONFLICT (migration_id) DO NOTHING;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM operations.schema_migration
         WHERE migration_id = '0004_user_content_writer_identity_separation'
           AND migration_sha256 = current_setting('honghu.migration_sha256')
    ) THEN
        RAISE EXCEPTION 'migration identity exists with a different SHA256';
    END IF;
END $$;

COMMIT;
