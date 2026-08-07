\set ON_ERROR_STOP on

BEGIN;

SELECT set_config('honghu.migration_sha256', :'migration_sha256', true);

CREATE SCHEMA IF NOT EXISTS operations;
CREATE SCHEMA IF NOT EXISTS audit;
CREATE SCHEMA IF NOT EXISTS user_content;

CREATE TABLE IF NOT EXISTS operations.schema_migration (
    migration_id text PRIMARY KEY,
    migration_sha256 text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    phase text NOT NULL CHECK (phase IN ('expand', 'migrate', 'transition', 'contract')),
    forward_only boolean NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS operations.idempotency_record (
    operation_scope text NOT NULL,
    idempotency_key text NOT NULL,
    request_hash text NOT NULL,
    result_payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (operation_scope, idempotency_key)
);

CREATE TABLE IF NOT EXISTS user_content.analyst_note (
    note_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    note_key text NOT NULL UNIQUE,
    entity_type text NOT NULL,
    entity_id bigint NOT NULL,
    q_number integer,
    note_type text NOT NULL,
    title text NOT NULL,
    content text NOT NULL,
    author text NOT NULL,
    revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    deleted_at timestamptz,
    CHECK (length(note_key) BETWEEN 1 AND 200)
);

CREATE TABLE IF NOT EXISTS audit.user_content_revision (
    audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    object_type text NOT NULL,
    object_key text NOT NULL,
    revision bigint NOT NULL,
    action text NOT NULL CHECK (action IN ('create', 'update', 'soft_delete')),
    actor text NOT NULL,
    idempotency_key text NOT NULL,
    payload jsonb NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (object_type, object_key, revision)
);

CREATE TABLE IF NOT EXISTS operations.legacy_identity_mapping (
    source_database text NOT NULL,
    source_table text NOT NULL,
    legacy_id text NOT NULL,
    target_schema text NOT NULL,
    target_table text NOT NULL,
    stable_key text NOT NULL,
    target_surrogate_id bigint,
    verified_at timestamptz,
    PRIMARY KEY (source_database, source_table, legacy_id),
    UNIQUE (target_schema, target_table, stable_key)
);

CREATE OR REPLACE FUNCTION user_content.put_analyst_note(
    p_note_key text,
    p_entity_type text,
    p_entity_id bigint,
    p_q_number integer,
    p_note_type text,
    p_title text,
    p_content text,
    p_author text,
    p_expected_revision bigint,
    p_idempotency_key text,
    p_request_hash text
) RETURNS TABLE(note_key text, revision bigint, deleted boolean)
LANGUAGE plpgsql
AS $$
DECLARE
    v_existing operations.idempotency_record%ROWTYPE;
    v_note user_content.analyst_note%ROWTYPE;
    v_action text;
    v_result jsonb;
BEGIN
    SELECT * INTO v_existing
      FROM operations.idempotency_record
     WHERE operation_scope = 'user_content.put_analyst_note'
       AND idempotency_key = p_idempotency_key;
    IF FOUND THEN
        IF v_existing.request_hash <> p_request_hash THEN
            RAISE EXCEPTION 'idempotency key conflict' USING ERRCODE = '23505';
        END IF;
        RETURN QUERY SELECT
            v_existing.result_payload->>'note_key',
            (v_existing.result_payload->>'revision')::bigint,
            (v_existing.result_payload->>'deleted')::boolean;
        RETURN;
    END IF;

    SELECT * INTO v_note FROM user_content.analyst_note n
     WHERE n.note_key = p_note_key FOR UPDATE;
    IF NOT FOUND THEN
        IF p_expected_revision <> 0 THEN
            RAISE EXCEPTION 'stale revision: expected %, object absent', p_expected_revision
                USING ERRCODE = '40001';
        END IF;
        INSERT INTO user_content.analyst_note(
            note_key, entity_type, entity_id, q_number, note_type,
            title, content, author
        ) VALUES (
            p_note_key, p_entity_type, p_entity_id, p_q_number, p_note_type,
            p_title, p_content, p_author
        ) RETURNING * INTO v_note;
        v_action := 'create';
    ELSE
        IF v_note.revision <> p_expected_revision THEN
            RAISE EXCEPTION 'stale revision: expected %, actual %',
                p_expected_revision, v_note.revision USING ERRCODE = '40001';
        END IF;
        UPDATE user_content.analyst_note n SET
            entity_type = p_entity_type,
            entity_id = p_entity_id,
            q_number = p_q_number,
            note_type = p_note_type,
            title = p_title,
            content = p_content,
            author = p_author,
            revision = n.revision + 1,
            updated_at = clock_timestamp(),
            deleted_at = NULL
        WHERE n.note_key = p_note_key
        RETURNING * INTO v_note;
        v_action := 'update';
    END IF;

    v_result := jsonb_build_object(
        'note_key', v_note.note_key,
        'revision', v_note.revision,
        'deleted', false
    );
    INSERT INTO audit.user_content_revision(
        object_type, object_key, revision, action, actor,
        idempotency_key, payload
    ) VALUES (
        'analyst_note', v_note.note_key, v_note.revision, v_action, p_author,
        p_idempotency_key, to_jsonb(v_note)
    );
    INSERT INTO operations.idempotency_record(
        operation_scope, idempotency_key, request_hash, result_payload
    ) VALUES (
        'user_content.put_analyst_note', p_idempotency_key, p_request_hash, v_result
    );
    RETURN QUERY SELECT v_note.note_key, v_note.revision, false;
END;
$$;

CREATE OR REPLACE FUNCTION user_content.soft_delete_analyst_note(
    p_note_key text,
    p_actor text,
    p_expected_revision bigint,
    p_idempotency_key text,
    p_request_hash text
) RETURNS TABLE(note_key text, revision bigint, deleted boolean)
LANGUAGE plpgsql
AS $$
DECLARE
    v_existing operations.idempotency_record%ROWTYPE;
    v_note user_content.analyst_note%ROWTYPE;
    v_result jsonb;
BEGIN
    SELECT * INTO v_existing
      FROM operations.idempotency_record
     WHERE operation_scope = 'user_content.soft_delete_analyst_note'
       AND idempotency_key = p_idempotency_key;
    IF FOUND THEN
        IF v_existing.request_hash <> p_request_hash THEN
            RAISE EXCEPTION 'idempotency key conflict' USING ERRCODE = '23505';
        END IF;
        RETURN QUERY SELECT
            v_existing.result_payload->>'note_key',
            (v_existing.result_payload->>'revision')::bigint,
            (v_existing.result_payload->>'deleted')::boolean;
        RETURN;
    END IF;

    SELECT * INTO v_note FROM user_content.analyst_note n
     WHERE n.note_key = p_note_key FOR UPDATE;
    IF NOT FOUND OR v_note.revision <> p_expected_revision THEN
        RAISE EXCEPTION 'stale revision or missing object' USING ERRCODE = '40001';
    END IF;
    UPDATE user_content.analyst_note n SET
        revision = n.revision + 1,
        updated_at = clock_timestamp(),
        deleted_at = clock_timestamp()
    WHERE n.note_key = p_note_key
    RETURNING * INTO v_note;

    v_result := jsonb_build_object(
        'note_key', v_note.note_key,
        'revision', v_note.revision,
        'deleted', true
    );
    INSERT INTO audit.user_content_revision(
        object_type, object_key, revision, action, actor,
        idempotency_key, payload
    ) VALUES (
        'analyst_note', v_note.note_key, v_note.revision, 'soft_delete', p_actor,
        p_idempotency_key, to_jsonb(v_note)
    );
    INSERT INTO operations.idempotency_record(
        operation_scope, idempotency_key, request_hash, result_payload
    ) VALUES (
        'user_content.soft_delete_analyst_note', p_idempotency_key, p_request_hash, v_result
    );
    RETURN QUERY SELECT v_note.note_key, v_note.revision, true;
END;
$$;

INSERT INTO operations.schema_migration(
    migration_id, migration_sha256, phase, forward_only
) VALUES (
    '0001_user_content_notes_expand',
    :'migration_sha256',
    'expand',
    false
) ON CONFLICT (migration_id) DO NOTHING;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM operations.schema_migration
         WHERE migration_id = '0001_user_content_notes_expand'
           AND migration_sha256 = current_setting('honghu.migration_sha256')
    ) THEN
        RAISE EXCEPTION 'migration identity exists with a different SHA256';
    END IF;
END $$;

COMMIT;
