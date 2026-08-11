\set ON_ERROR_STOP on

BEGIN;

SELECT set_config('honghu.migration_sha256', :'migration_sha256', true);

CREATE TABLE IF NOT EXISTS operations.cutover_unit_authority (
    cutover_unit text PRIMARY KEY,
    state text NOT NULL CHECK (state IN ('S0', 'S1', 'S2', 'S3', 'S4')),
    authoritative_backend text NOT NULL CHECK (
        authoritative_backend IN ('sqlite_transition', 'postgresql_production')
    ),
    writer_identity text,
    cutover_epoch text,
    sqlite_final_watermark jsonb,
    postgresql_first_formal_commit jsonb,
    state_revision bigint NOT NULL DEFAULT 1 CHECK (state_revision > 0),
    approval_reference text NOT NULL CHECK (btrim(approval_reference) <> ''),
    updated_by text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (
        (state IN ('S0', 'S1') AND authoritative_backend = 'sqlite_transition') OR
        (state IN ('S2', 'S3', 'S4') AND authoritative_backend = 'postgresql_production')
    ),
    CHECK (
        (state IN ('S0', 'S1')
            AND writer_identity IS NULL
            AND cutover_epoch IS NULL
            AND sqlite_final_watermark IS NULL
            AND postgresql_first_formal_commit IS NULL) OR
        (state = 'S2'
            AND nullif(btrim(writer_identity), '') IS NOT NULL
            AND nullif(btrim(cutover_epoch), '') IS NOT NULL
            AND sqlite_final_watermark IS NOT NULL
            AND postgresql_first_formal_commit IS NULL) OR
        (state IN ('S3', 'S4')
            AND nullif(btrim(writer_identity), '') IS NOT NULL
            AND nullif(btrim(cutover_epoch), '') IS NOT NULL
            AND sqlite_final_watermark IS NOT NULL
            AND postgresql_first_formal_commit IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS audit.cutover_unit_authority_revision (
    audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cutover_unit text NOT NULL,
    state_revision bigint NOT NULL,
    from_state text,
    to_state text NOT NULL,
    authoritative_backend text NOT NULL,
    writer_identity text,
    cutover_epoch text,
    sqlite_final_watermark jsonb,
    postgresql_first_formal_commit jsonb,
    actor text NOT NULL,
    approval_reference text NOT NULL CHECK (btrim(approval_reference) <> ''),
    reason text NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (cutover_unit, state_revision),
    CHECK (
        (to_state IN ('S0', 'S1') AND authoritative_backend = 'sqlite_transition') OR
        (to_state IN ('S2', 'S3', 'S4') AND authoritative_backend = 'postgresql_production')
    ),
    CHECK (to_state NOT IN ('S2', 'S3', 'S4') OR nullif(btrim(writer_identity), '') IS NOT NULL),
    CHECK (to_state NOT IN ('S2', 'S3', 'S4') OR nullif(btrim(cutover_epoch), '') IS NOT NULL),
    CHECK (to_state NOT IN ('S3', 'S4') OR postgresql_first_formal_commit IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS operations.cutover_verification_write (
    cutover_unit text NOT NULL,
    cutover_epoch text NOT NULL,
    verification_key text NOT NULL,
    writer_identity text NOT NULL,
    request_hash text NOT NULL,
    result_payload jsonb NOT NULL,
    verified_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (cutover_unit, cutover_epoch, verification_key)
);

CREATE TABLE IF NOT EXISTS operations.cutover_dependency_mapping (
    cutover_unit text NOT NULL,
    entity_type text NOT NULL,
    source_database text NOT NULL,
    source_table text NOT NULL,
    legacy_id text NOT NULL,
    stable_key text NOT NULL,
    source_watermark jsonb NOT NULL,
    source_evidence_identity text NOT NULL CHECK (btrim(source_evidence_identity) <> ''),
    mapping_revision bigint NOT NULL DEFAULT 1 CHECK (mapping_revision > 0),
    approval_reference text NOT NULL CHECK (btrim(approval_reference) <> ''),
    verified_by text NOT NULL CHECK (btrim(verified_by) <> ''),
    verified_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (cutover_unit, entity_type, source_database, source_table, legacy_id),
    UNIQUE (cutover_unit, entity_type, legacy_id),
    UNIQUE (cutover_unit, entity_type, stable_key)
);

CREATE TABLE IF NOT EXISTS audit.cutover_dependency_mapping_revision (
    audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cutover_unit text NOT NULL,
    entity_type text NOT NULL,
    source_database text NOT NULL,
    source_table text NOT NULL,
    legacy_id text NOT NULL,
    stable_key text NOT NULL,
    mapping_revision bigint NOT NULL CHECK (mapping_revision > 0),
    source_watermark jsonb NOT NULL,
    source_evidence_identity text NOT NULL CHECK (btrim(source_evidence_identity) <> ''),
    actor text NOT NULL CHECK (btrim(actor) <> ''),
    approval_reference text NOT NULL CHECK (btrim(approval_reference) <> ''),
    reason text NOT NULL CHECK (btrim(reason) <> ''),
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (
        cutover_unit, entity_type, source_database, source_table,
        legacy_id, mapping_revision
    )
);

ALTER TABLE user_content.analyst_note
    ADD COLUMN IF NOT EXISTS q_label text,
    ADD COLUMN IF NOT EXISTS entity_key text,
    ADD COLUMN IF NOT EXISTS legacy_entity_id_text text,
    ADD COLUMN IF NOT EXISTS legacy_note_id bigint,
    ADD COLUMN IF NOT EXISTS legacy_created_at_text text,
    ADD COLUMN IF NOT EXISTS legacy_updated_at_text text;

-- Dropping NOT NULL is an expand-compatible relaxation: the old function can
-- still supply both fields, while the v2 contract can preserve nullable legacy
-- titles and text entity identities such as theme ids.
ALTER TABLE user_content.analyst_note
    ALTER COLUMN entity_id DROP NOT NULL,
    ALTER COLUMN title DROP NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS analyst_note_legacy_id_unique
    ON user_content.analyst_note (legacy_note_id)
    WHERE legacy_note_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS analyst_note_entity_key_index
    ON user_content.analyst_note (entity_type, entity_key)
    WHERE entity_key IS NOT NULL;

CREATE OR REPLACE VIEW user_content.analyst_note_read_v1 AS
SELECT
    n.note_id AS id,
    n.note_key,
    n.entity_type,
    n.entity_id,
    n.legacy_entity_id_text,
    n.entity_key,
    coalesce(n.q_label, n.q_number::text) AS q_number,
    n.note_type,
    n.title,
    n.content,
    n.author,
    n.revision,
    n.created_at,
    n.updated_at
FROM user_content.analyst_note n
WHERE n.deleted_at IS NULL;

CREATE OR REPLACE FUNCTION operations.transition_cutover_unit(
    p_cutover_unit text,
    p_expected_state text,
    p_expected_revision bigint,
    p_to_state text,
    p_backend text,
    p_writer_identity text,
    p_cutover_epoch text,
    p_sqlite_final_watermark jsonb,
    p_actor text,
    p_approval_reference text,
    p_reason text
) RETURNS TABLE(cutover_unit text, state text, state_revision bigint)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations, audit, user_content
AS $$
DECLARE
    v_current operations.cutover_unit_authority%ROWTYPE;
    v_next_revision bigint;
BEGIN
    IF nullif(btrim(p_actor), '') IS NULL
       OR nullif(btrim(p_reason), '') IS NULL
       OR nullif(btrim(p_approval_reference), '') IS NULL THEN
        RAISE EXCEPTION 'actor, approval reference and reason are required'
            USING ERRCODE = '22023';
    END IF;
    IF p_to_state IN ('S0', 'S1') AND p_backend <> 'sqlite_transition' THEN
        RAISE EXCEPTION 'S0/S1 authority backend must remain SQLite'
            USING ERRCODE = '22023';
    END IF;
    IF p_to_state IN ('S2', 'S3', 'S4') AND p_backend <> 'postgresql_production' THEN
        RAISE EXCEPTION 'S2/S3/S4 authority backend must remain PostgreSQL'
            USING ERRCODE = '22023';
    END IF;
    IF p_to_state IN ('S0', 'S1') AND (
        p_writer_identity IS NOT NULL OR
        p_cutover_epoch IS NOT NULL OR
        p_sqlite_final_watermark IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'S0/S1 cannot carry writer, epoch or SQLite watermark'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_current
      FROM operations.cutover_unit_authority a
     WHERE a.cutover_unit = p_cutover_unit
     FOR UPDATE;

    IF NOT FOUND THEN
        IF p_expected_state <> 'ABSENT' OR p_expected_revision <> 0 OR p_to_state <> 'S0' THEN
            RAISE EXCEPTION 'cutover authority state is absent' USING ERRCODE = '40001';
        END IF;
        INSERT INTO operations.cutover_unit_authority(
            cutover_unit, state, authoritative_backend, state_revision,
            approval_reference, updated_by
        ) VALUES (
            p_cutover_unit, 'S0', 'sqlite_transition', 1,
            p_approval_reference, p_actor
        ) RETURNING * INTO v_current;
        INSERT INTO audit.cutover_unit_authority_revision(
            cutover_unit, state_revision, from_state, to_state,
            authoritative_backend, actor, approval_reference, reason
        ) VALUES (
            p_cutover_unit, 1, NULL, 'S0', 'sqlite_transition',
            p_actor, p_approval_reference, p_reason
        );
        RETURN QUERY SELECT v_current.cutover_unit, v_current.state, v_current.state_revision;
        RETURN;
    END IF;

    IF v_current.state <> p_expected_state OR v_current.state_revision <> p_expected_revision THEN
        RAISE EXCEPTION 'stale cutover authority revision' USING ERRCODE = '40001';
    END IF;
    IF NOT (
        (p_expected_state = 'S0' AND p_to_state = 'S1') OR
        (p_expected_state = 'S1' AND p_to_state IN ('S0', 'S2')) OR
        (p_expected_state = 'S2' AND p_to_state = 'S1') OR
        (p_expected_state = 'S3' AND p_to_state = 'S4')
    ) THEN
        RAISE EXCEPTION 'disallowed cutover transition % -> %', p_expected_state, p_to_state
            USING ERRCODE = '22023';
    END IF;
    IF p_to_state = 'S2' AND (
        nullif(btrim(p_writer_identity), '') IS NULL OR
        nullif(btrim(p_cutover_epoch), '') IS NULL OR
        p_sqlite_final_watermark IS NULL OR
        p_backend <> 'postgresql_production'
    ) THEN
        RAISE EXCEPTION 'S2 requires writer, epoch, SQLite watermark and approval reference'
            USING ERRCODE = '22023';
    END IF;
    IF p_expected_state = 'S2' AND p_to_state = 'S1'
       AND v_current.postgresql_first_formal_commit IS NOT NULL THEN
        RAISE EXCEPTION 'S2 cannot return to S1 after a formal commit' USING ERRCODE = '55000';
    END IF;
    IF p_expected_state = 'S3' AND p_to_state = 'S4' AND (
        p_backend <> v_current.authoritative_backend OR
        p_writer_identity IS DISTINCT FROM v_current.writer_identity OR
        p_cutover_epoch IS DISTINCT FROM v_current.cutover_epoch OR
        p_sqlite_final_watermark IS DISTINCT FROM v_current.sqlite_final_watermark OR
        p_approval_reference = v_current.approval_reference
    ) THEN
        RAISE EXCEPTION 'S3 to S4 must preserve authority identity and use a new approval reference'
            USING ERRCODE = '22023';
    END IF;

    v_next_revision := v_current.state_revision + 1;
    UPDATE operations.cutover_unit_authority a SET
        state = p_to_state,
        authoritative_backend = p_backend,
        writer_identity = CASE WHEN p_to_state IN ('S0', 'S1') THEN NULL ELSE p_writer_identity END,
        cutover_epoch = CASE WHEN p_to_state IN ('S0', 'S1') THEN NULL ELSE p_cutover_epoch END,
        sqlite_final_watermark = CASE
            WHEN p_to_state IN ('S0', 'S1') THEN NULL ELSE p_sqlite_final_watermark END,
        postgresql_first_formal_commit = CASE
            WHEN p_to_state IN ('S0', 'S1', 'S2') THEN NULL ELSE a.postgresql_first_formal_commit END,
        state_revision = v_next_revision,
        approval_reference = p_approval_reference,
        updated_by = p_actor,
        updated_at = clock_timestamp()
    WHERE a.cutover_unit = p_cutover_unit
    RETURNING * INTO v_current;

    INSERT INTO audit.cutover_unit_authority_revision(
        cutover_unit, state_revision, from_state, to_state,
        authoritative_backend, writer_identity, cutover_epoch,
        sqlite_final_watermark, postgresql_first_formal_commit,
        actor, approval_reference, reason
    ) VALUES (
        p_cutover_unit, v_next_revision, p_expected_state, p_to_state,
        v_current.authoritative_backend, v_current.writer_identity, v_current.cutover_epoch,
        v_current.sqlite_final_watermark, v_current.postgresql_first_formal_commit,
        p_actor, p_approval_reference, p_reason
    );
    RETURN QUERY SELECT v_current.cutover_unit, v_current.state, v_current.state_revision;
END;
$$;

CREATE OR REPLACE FUNCTION operations.record_cutover_verification(
    p_cutover_unit text,
    p_writer_identity text,
    p_verification_key text,
    p_request_hash text,
    p_result_payload jsonb
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations, audit, user_content
AS $$
DECLARE
    v_authority operations.cutover_unit_authority%ROWTYPE;
    v_existing operations.cutover_verification_write%ROWTYPE;
BEGIN
    SELECT * INTO v_authority
      FROM operations.cutover_unit_authority a
     WHERE a.cutover_unit = p_cutover_unit
     FOR UPDATE;
    IF NOT FOUND OR v_authority.state <> 'S2'
       OR v_authority.writer_identity <> p_writer_identity THEN
        RAISE EXCEPTION 'verification write is not authorized' USING ERRCODE = '42501';
    END IF;
    SELECT * INTO v_existing
      FROM operations.cutover_verification_write v
     WHERE v.cutover_unit = p_cutover_unit
       AND v.cutover_epoch = v_authority.cutover_epoch
       AND v.verification_key = p_verification_key;
    IF FOUND THEN
        IF v_existing.request_hash <> p_request_hash THEN
            RAISE EXCEPTION 'verification idempotency conflict' USING ERRCODE = '23505';
        END IF;
        RETURN v_existing.result_payload;
    END IF;
    INSERT INTO operations.cutover_verification_write(
        cutover_unit, cutover_epoch, verification_key,
        writer_identity, request_hash, result_payload
    ) VALUES (
        p_cutover_unit, v_authority.cutover_epoch, p_verification_key,
        p_writer_identity, p_request_hash, p_result_payload
    );
    RETURN p_result_payload;
END;
$$;

CREATE OR REPLACE FUNCTION operations.transition_user_content_notes(
    p_expected_state text,
    p_expected_revision bigint,
    p_to_state text,
    p_writer_identity text,
    p_cutover_epoch text,
    p_sqlite_final_watermark jsonb,
    p_actor text,
    p_approval_reference text,
    p_reason text
) RETURNS TABLE(cutover_unit text, state text, state_revision bigint)
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog, operations, audit, user_content
AS $$
    SELECT * FROM operations.transition_cutover_unit(
        'user_content_notes', p_expected_state, p_expected_revision,
        p_to_state,
        CASE
            WHEN p_to_state IN ('S0', 'S1') THEN 'sqlite_transition'
            WHEN p_to_state IN ('S2', 'S3', 'S4') THEN 'postgresql_production'
            ELSE NULL
        END,
        p_writer_identity, p_cutover_epoch,
        p_sqlite_final_watermark, p_actor, p_approval_reference, p_reason
    );
$$;

CREATE OR REPLACE FUNCTION operations.record_user_content_notes_verification(
    p_writer_identity text,
    p_verification_key text,
    p_request_hash text,
    p_result_payload jsonb
) RETURNS jsonb
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog, operations, audit, user_content
AS $$
    SELECT operations.record_cutover_verification(
        'user_content_notes', p_writer_identity, p_verification_key,
        p_request_hash, p_result_payload
    );
$$;

CREATE OR REPLACE FUNCTION operations.register_user_content_notes_dependency_mapping(
    p_expected_authority_revision bigint,
    p_entity_type text,
    p_source_database text,
    p_source_table text,
    p_legacy_id text,
    p_stable_key text,
    p_source_watermark jsonb,
    p_source_evidence_identity text,
    p_actor text,
    p_approval_reference text,
    p_reason text
) RETURNS TABLE(legacy_id text, stable_key text, mapping_revision bigint)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations, audit, user_content
AS $$
DECLARE
    v_authority operations.cutover_unit_authority%ROWTYPE;
    v_existing operations.cutover_dependency_mapping%ROWTYPE;
BEGIN
    IF p_expected_authority_revision IS NULL
       OR nullif(btrim(p_entity_type), '') IS NULL
       OR nullif(btrim(p_source_database), '') IS NULL
       OR nullif(btrim(p_source_table), '') IS NULL
       OR nullif(btrim(p_legacy_id), '') IS NULL
       OR nullif(btrim(p_stable_key), '') IS NULL
       OR p_source_watermark IS NULL
       OR nullif(btrim(p_source_evidence_identity), '') IS NULL
       OR nullif(btrim(p_actor), '') IS NULL
       OR nullif(btrim(p_approval_reference), '') IS NULL
       OR nullif(btrim(p_reason), '') IS NULL THEN
        RAISE EXCEPTION 'mapping registration requires authority revision, source evidence, approval and reason'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_authority
      FROM operations.cutover_unit_authority a
     WHERE a.cutover_unit = 'user_content_notes'
     FOR UPDATE;
    IF NOT FOUND OR v_authority.state NOT IN ('S1', 'S3', 'S4') THEN
        RAISE EXCEPTION 'dependency mapping changes are fenced in the current authority state'
            USING ERRCODE = '42501';
    END IF;
    IF v_authority.state_revision <> p_expected_authority_revision THEN
        RAISE EXCEPTION 'stale cutover authority revision for dependency mapping'
            USING ERRCODE = '40001';
    END IF;

    SELECT * INTO v_existing
      FROM operations.cutover_dependency_mapping m
     WHERE m.cutover_unit = 'user_content_notes'
       AND m.entity_type = p_entity_type
       AND m.source_database = p_source_database
       AND m.source_table = p_source_table
       AND m.legacy_id = p_legacy_id
     FOR UPDATE;
    IF FOUND THEN
        IF v_existing.stable_key <> p_stable_key
           OR v_existing.source_watermark <> p_source_watermark
           OR v_existing.source_evidence_identity <> p_source_evidence_identity THEN
            RAISE EXCEPTION 'dependency mapping identity conflict'
                USING ERRCODE = '23505';
        END IF;
        RETURN QUERY SELECT
            v_existing.legacy_id, v_existing.stable_key, v_existing.mapping_revision;
        RETURN;
    END IF;

    IF EXISTS (
        SELECT 1
          FROM operations.cutover_dependency_mapping m
         WHERE m.cutover_unit = 'user_content_notes'
           AND m.entity_type = p_entity_type
           AND m.stable_key = p_stable_key
    ) THEN
        RAISE EXCEPTION 'stable dependency identity is already mapped'
            USING ERRCODE = '23505';
    END IF;

    INSERT INTO operations.cutover_dependency_mapping(
        cutover_unit, entity_type, source_database, source_table,
        legacy_id, stable_key, source_watermark, source_evidence_identity,
        mapping_revision, approval_reference, verified_by
    ) VALUES (
        'user_content_notes', p_entity_type, p_source_database, p_source_table,
        p_legacy_id, p_stable_key, p_source_watermark, p_source_evidence_identity,
        1, p_approval_reference, p_actor
    ) RETURNING * INTO v_existing;

    INSERT INTO audit.cutover_dependency_mapping_revision(
        cutover_unit, entity_type, source_database, source_table,
        legacy_id, stable_key, mapping_revision, source_watermark,
        source_evidence_identity, actor, approval_reference, reason
    ) VALUES (
        'user_content_notes', p_entity_type, p_source_database, p_source_table,
        p_legacy_id, p_stable_key, v_existing.mapping_revision, p_source_watermark,
        p_source_evidence_identity, p_actor, p_approval_reference, p_reason
    );

    RETURN QUERY SELECT
        v_existing.legacy_id, v_existing.stable_key, v_existing.mapping_revision;
END;
$$;

-- Internal authority helper shared by every formal analyst-note mutation.
-- It is intentionally not granted to application or controller roles: callers
-- must first satisfy their operation-specific writer, revision, mapping and
-- idempotency contracts.  Because PostgreSQL functions execute in the caller's
-- transaction, the business mutation and an S2 -> S3 revision commit or roll
-- back together.
CREATE OR REPLACE FUNCTION operations.promote_user_content_notes_on_first_formal_mutation(
    p_operation_scope text,
    p_idempotency_key text,
    p_object_key text,
    p_actor text
) RETURNS operations.cutover_unit_authority
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations, audit
AS $$
DECLARE
    v_authority operations.cutover_unit_authority%ROWTYPE;
    v_next_authority_revision bigint;
BEGIN
    IF nullif(btrim(p_operation_scope), '') IS NULL
       OR p_operation_scope NOT IN (
           'user_content.put_analyst_note_v2',
           'user_content.soft_delete_analyst_note_v2'
       )
       OR nullif(btrim(p_idempotency_key), '') IS NULL
       OR nullif(btrim(p_object_key), '') IS NULL
       OR nullif(btrim(p_actor), '') IS NULL THEN
        RAISE EXCEPTION 'formal mutation identity and actor are required'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_authority
      FROM operations.cutover_unit_authority a
     WHERE a.cutover_unit = 'user_content_notes'
     FOR UPDATE;
    IF NOT FOUND OR v_authority.state NOT IN ('S2', 'S3', 'S4')
       OR v_authority.authoritative_backend <> 'postgresql_production' THEN
        RAISE EXCEPTION 'formal mutation authority is fenced'
            USING ERRCODE = '42501';
    END IF;

    IF v_authority.state = 'S2' THEN
        v_next_authority_revision := v_authority.state_revision + 1;
        UPDATE operations.cutover_unit_authority a SET
            state = 'S3',
            postgresql_first_formal_commit = jsonb_build_object(
                'operation_scope', p_operation_scope,
                'idempotency_key', p_idempotency_key,
                'object_key', p_object_key,
                'transaction_id', txid_current()::text,
                'recorded_at', clock_timestamp()
            ),
            state_revision = v_next_authority_revision,
            updated_by = p_actor,
            updated_at = clock_timestamp()
        WHERE a.cutover_unit = 'user_content_notes'
        RETURNING * INTO v_authority;
        INSERT INTO audit.cutover_unit_authority_revision(
            cutover_unit, state_revision, from_state, to_state,
            authoritative_backend, writer_identity, cutover_epoch,
            sqlite_final_watermark, postgresql_first_formal_commit,
            actor, approval_reference, reason
        ) VALUES (
            'user_content_notes', v_next_authority_revision, 'S2', 'S3',
            v_authority.authoritative_backend, v_authority.writer_identity,
            v_authority.cutover_epoch, v_authority.sqlite_final_watermark,
            v_authority.postgresql_first_formal_commit, p_actor,
            v_authority.approval_reference,
            'first formal analyst-note business mutation'
        );
    END IF;
    RETURN v_authority;
END;
$$;

CREATE OR REPLACE FUNCTION user_content.put_analyst_note_v2(
    p_note_key text,
    p_entity_type text,
    p_legacy_entity_id text,
    p_entity_key text,
    p_q_label text,
    p_note_type text,
    p_title text,
    p_content text,
    p_author text,
    p_expected_revision bigint,
    p_idempotency_key text,
    p_request_hash text,
    p_writer_identity text
) RETURNS TABLE(note_key text, revision bigint, deleted boolean, authority_state text)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations, audit, user_content
AS $$
DECLARE
    v_authority operations.cutover_unit_authority%ROWTYPE;
    v_mapping operations.cutover_dependency_mapping%ROWTYPE;
    v_existing operations.idempotency_record%ROWTYPE;
    v_note user_content.analyst_note%ROWTYPE;
    v_action text;
    v_result jsonb;
    v_request jsonb;
BEGIN
    IF p_expected_revision IS NULL OR nullif(p_idempotency_key, '') IS NULL
       OR nullif(p_request_hash, '') IS NULL OR nullif(p_note_key, '') IS NULL THEN
        RAISE EXCEPTION 'note key, expected revision, idempotency key and request hash are required'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO v_authority
      FROM operations.cutover_unit_authority a
     WHERE a.cutover_unit = 'user_content_notes'
     FOR UPDATE;
    IF NOT FOUND OR v_authority.state NOT IN ('S2', 'S3', 'S4')
       OR v_authority.authoritative_backend <> 'postgresql_production'
       OR v_authority.writer_identity <> p_writer_identity
       OR p_writer_identity <> session_user THEN
        RAISE EXCEPTION 'PostgreSQL analyst-note writer is fenced' USING ERRCODE = '42501';
    END IF;
    SELECT * INTO v_mapping
      FROM operations.cutover_dependency_mapping m
     WHERE m.cutover_unit = 'user_content_notes'
       AND m.entity_type = p_entity_type
       AND m.legacy_id = p_legacy_entity_id
       AND m.stable_key = p_entity_key
       AND nullif(btrim(m.source_evidence_identity), '') IS NOT NULL;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unverified entity identity mapping' USING ERRCODE = '23503';
    END IF;

    v_request := jsonb_build_object(
        'note_key', p_note_key, 'entity_type', p_entity_type,
        'legacy_entity_id', p_legacy_entity_id, 'entity_key', p_entity_key,
        'q_label', p_q_label, 'note_type', p_note_type, 'title', p_title,
        'content', p_content, 'author', p_author, 'expected_revision', p_expected_revision
    );
    SELECT * INTO v_existing
      FROM operations.idempotency_record
     WHERE operation_scope = 'user_content.put_analyst_note_v2'
       AND idempotency_key = p_idempotency_key;
    IF FOUND THEN
        IF v_existing.request_hash <> p_request_hash OR v_existing.request_payload <> v_request THEN
            RAISE EXCEPTION 'idempotency key conflict' USING ERRCODE = '23505';
        END IF;
        RETURN QUERY SELECT
            v_existing.result_payload->>'note_key',
            (v_existing.result_payload->>'revision')::bigint,
            (v_existing.result_payload->>'deleted')::boolean,
            v_authority.state;
        RETURN;
    END IF;

    SELECT * INTO v_note FROM user_content.analyst_note n
     WHERE n.note_key = p_note_key FOR UPDATE;
    IF NOT FOUND THEN
        IF p_expected_revision <> 0 THEN
            RAISE EXCEPTION 'stale revision: object absent' USING ERRCODE = '40001';
        END IF;
        INSERT INTO user_content.analyst_note(
            note_key, entity_type, entity_id, legacy_entity_id_text,
            entity_key, q_number, q_label,
            note_type, title, content, author
        ) VALUES (
            p_note_key, p_entity_type,
            CASE WHEN p_legacy_entity_id ~ '^[0-9]+$' THEN p_legacy_entity_id::bigint ELSE NULL END,
            p_legacy_entity_id, p_entity_key, NULL, p_q_label,
            p_note_type, p_title, p_content, p_author
        ) RETURNING * INTO v_note;
        v_action := 'create';
    ELSE
        IF v_note.revision <> p_expected_revision THEN
            RAISE EXCEPTION 'stale revision' USING ERRCODE = '40001';
        END IF;
        UPDATE user_content.analyst_note n SET
            entity_type = p_entity_type,
            entity_id = CASE
                WHEN p_legacy_entity_id ~ '^[0-9]+$' THEN p_legacy_entity_id::bigint ELSE NULL END,
            legacy_entity_id_text = p_legacy_entity_id,
            entity_key = p_entity_key,
            q_number = NULL,
            q_label = p_q_label,
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

    v_authority := operations.promote_user_content_notes_on_first_formal_mutation(
        'user_content.put_analyst_note_v2', p_idempotency_key, p_note_key, p_author
    );

    v_result := jsonb_build_object(
        'note_key', v_note.note_key, 'revision', v_note.revision, 'deleted', false
    );
    INSERT INTO audit.user_content_revision(
        object_type, object_key, revision, action, actor,
        idempotency_key, payload
    ) VALUES (
        'analyst_note', v_note.note_key, v_note.revision, v_action, p_author,
        p_idempotency_key, to_jsonb(v_note)
    );
    INSERT INTO operations.idempotency_record(
        operation_scope, idempotency_key, request_hash, request_payload, result_payload
    ) VALUES (
        'user_content.put_analyst_note_v2', p_idempotency_key,
        p_request_hash, v_request, v_result
    );
    RETURN QUERY SELECT v_note.note_key, v_note.revision, false, v_authority.state;
END;
$$;

CREATE OR REPLACE FUNCTION user_content.soft_delete_analyst_note_v2(
    p_note_key text,
    p_actor text,
    p_expected_revision bigint,
    p_idempotency_key text,
    p_request_hash text,
    p_writer_identity text
) RETURNS TABLE(note_key text, revision bigint, deleted boolean, authority_state text)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations, audit, user_content
AS $$
DECLARE
    v_authority operations.cutover_unit_authority%ROWTYPE;
    v_existing operations.idempotency_record%ROWTYPE;
    v_note user_content.analyst_note%ROWTYPE;
    v_result jsonb;
    v_request jsonb;
BEGIN
    IF p_expected_revision IS NULL OR nullif(p_idempotency_key, '') IS NULL
       OR nullif(p_request_hash, '') IS NULL OR nullif(p_note_key, '') IS NULL THEN
        RAISE EXCEPTION 'note key, expected revision, idempotency key and request hash are required'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO v_authority
      FROM operations.cutover_unit_authority a
     WHERE a.cutover_unit = 'user_content_notes'
     FOR UPDATE;
    IF NOT FOUND OR v_authority.state NOT IN ('S2', 'S3', 'S4')
       OR v_authority.authoritative_backend <> 'postgresql_production'
       OR v_authority.writer_identity <> p_writer_identity
       OR p_writer_identity <> session_user THEN
        RAISE EXCEPTION 'PostgreSQL analyst-note writer is fenced' USING ERRCODE = '42501';
    END IF;
    v_request := jsonb_build_object(
        'note_key', p_note_key, 'actor', p_actor, 'expected_revision', p_expected_revision
    );
    SELECT * INTO v_existing
      FROM operations.idempotency_record
     WHERE operation_scope = 'user_content.soft_delete_analyst_note_v2'
       AND idempotency_key = p_idempotency_key;
    IF FOUND THEN
        IF v_existing.request_hash <> p_request_hash OR v_existing.request_payload <> v_request THEN
            RAISE EXCEPTION 'idempotency key conflict' USING ERRCODE = '23505';
        END IF;
        RETURN QUERY SELECT
            v_existing.result_payload->>'note_key',
            (v_existing.result_payload->>'revision')::bigint,
            (v_existing.result_payload->>'deleted')::boolean,
            v_authority.state;
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
    v_authority := operations.promote_user_content_notes_on_first_formal_mutation(
        'user_content.soft_delete_analyst_note_v2',
        p_idempotency_key, p_note_key, p_actor
    );
    v_result := jsonb_build_object(
        'note_key', v_note.note_key, 'revision', v_note.revision, 'deleted', true
    );
    INSERT INTO audit.user_content_revision(
        object_type, object_key, revision, action, actor,
        idempotency_key, payload
    ) VALUES (
        'analyst_note', v_note.note_key, v_note.revision, 'soft_delete', p_actor,
        p_idempotency_key, to_jsonb(v_note)
    );
    INSERT INTO operations.idempotency_record(
        operation_scope, idempotency_key, request_hash, request_payload, result_payload
    ) VALUES (
        'user_content.soft_delete_analyst_note_v2', p_idempotency_key,
        p_request_hash, v_request, v_result
    );
    RETURN QUERY SELECT v_note.note_key, v_note.revision, true, v_authority.state;
END;
$$;

REVOKE ALL ON FUNCTION operations.transition_cutover_unit(
    text, text, bigint, text, text, text, text, jsonb, text, text, text
) FROM PUBLIC;
REVOKE ALL ON FUNCTION operations.record_cutover_verification(
    text, text, text, text, jsonb
) FROM PUBLIC;
REVOKE ALL ON FUNCTION operations.transition_user_content_notes(
    text, bigint, text, text, text, jsonb, text, text, text
) FROM PUBLIC;
REVOKE ALL ON FUNCTION operations.record_user_content_notes_verification(
    text, text, text, jsonb
) FROM PUBLIC;
REVOKE ALL ON FUNCTION operations.register_user_content_notes_dependency_mapping(
    bigint, text, text, text, text, text, jsonb, text, text, text, text
) FROM PUBLIC;
REVOKE ALL ON FUNCTION operations.promote_user_content_notes_on_first_formal_mutation(
    text, text, text, text
) FROM PUBLIC;
REVOKE ALL ON FUNCTION user_content.put_analyst_note_v2(
    text, text, text, text, text, text, text, text, text,
    bigint, text, text, text
) FROM PUBLIC;
REVOKE ALL ON FUNCTION user_content.soft_delete_analyst_note_v2(
    text, text, bigint, text, text, text
) FROM PUBLIC;
REVOKE ALL ON FUNCTION user_content.put_analyst_note(
    text, text, bigint, integer, text, text, text, text, bigint, text, text
) FROM PUBLIC;
REVOKE ALL ON FUNCTION user_content.soft_delete_analyst_note(
    text, text, bigint, text, text
) FROM PUBLIC;

INSERT INTO operations.schema_migration(
    migration_id, migration_sha256, phase, forward_only
) VALUES (
    '0002_user_content_notes_cutover_expand',
    :'migration_sha256',
    'expand',
    false
) ON CONFLICT (migration_id) DO NOTHING;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM operations.schema_migration
         WHERE migration_id = '0002_user_content_notes_cutover_expand'
           AND migration_sha256 = current_setting('honghu.migration_sha256')
    ) THEN
        RAISE EXCEPTION 'migration identity exists with a different SHA256';
    END IF;
END $$;

COMMIT;
