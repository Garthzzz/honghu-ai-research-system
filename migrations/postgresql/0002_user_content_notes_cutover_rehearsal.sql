\set ON_ERROR_STOP on

SELECT set_config('honghu.rehearsal_writer_identity', :'writer_identity', false);

-- S1 abandon rehearsal.
SELECT * FROM operations.transition_cutover_unit(
    'rehearsal_s1_abandon', 'ABSENT', 0, 'S0', 'sqlite_transition',
    NULL, NULL, NULL, 'rehearsal', 'stage4-design-only', 'initialize S0'
);
SELECT * FROM operations.transition_cutover_unit(
    'rehearsal_s1_abandon', 'S0', 1, 'S1', 'sqlite_transition',
    NULL, NULL, NULL, 'rehearsal', 'stage4-design-only', 'prepare S1'
);
SELECT * FROM operations.transition_cutover_unit(
    'rehearsal_s1_abandon', 'S1', 2, 'S0', 'sqlite_transition',
    NULL, NULL, NULL, 'rehearsal', 'stage4-design-only', 'abandon before writer cutover'
);

-- S2 rollback is allowed only while there is no formal business commit.
SELECT * FROM operations.transition_cutover_unit(
    'rehearsal_s2_no_formal_write', 'ABSENT', 0, 'S0', 'sqlite_transition',
    NULL, NULL, NULL, 'rehearsal', 'stage4-design-only', 'initialize S0'
);
SELECT * FROM operations.transition_cutover_unit(
    'rehearsal_s2_no_formal_write', 'S0', 1, 'S1', 'sqlite_transition',
    NULL, NULL, NULL, 'rehearsal', 'stage4-design-only', 'prepare S1'
);
SELECT * FROM operations.transition_cutover_unit(
    'rehearsal_s2_no_formal_write', 'S1', 2, 'S2', 'postgresql_production',
    'stage4-rehearsal-writer', 'epoch-s2-rollback', '{"source_count":0}'::jsonb,
    'rehearsal', 'stage4-design-only', 'enter controlled S2'
);
SELECT operations.record_cutover_verification(
    'rehearsal_s2_no_formal_write', 'stage4-rehearsal-writer',
    'verification-1', 'verification-hash-1', '{"ok":true}'::jsonb
);
SELECT * FROM operations.transition_cutover_unit(
    'rehearsal_s2_no_formal_write', 'S2', 3, 'S1', 'sqlite_transition',
    NULL, NULL, NULL, 'rehearsal', 'stage4-design-only',
    'watermark and audit prove no formal write'
);

-- Initialize the actual first-unit authority, enter S1, and prove its writer is fenced.
SET SESSION AUTHORIZATION :"controller_role";
SELECT * FROM operations.transition_user_content_notes(
    'ABSENT', 0, 'S0', NULL, NULL, NULL,
    'rehearsal', 'stage4-s0-approved', 'initialize S0'
);
SELECT * FROM operations.transition_user_content_notes(
    'S0', 1, 'S1', NULL, NULL, NULL,
    'rehearsal', 'stage4-s1-approved', 'prepare mapping and backfill'
);
SELECT * FROM operations.register_user_content_notes_dependency_mapping(
    2, 'theme', 'research.db', 'theme', 'ai_datacenter',
    'theme:ai_datacenter', '{"fixture":"theme-v1"}'::jsonb,
    'sha256:theme-v1', 'rehearsal', 'stage4-mapping-approved',
    'verified theme identity from the read-only source snapshot'
);
SELECT * FROM operations.register_user_content_notes_dependency_mapping(
    2, 'company', 'research.db', 'company', '1',
    'company:300308.SZ:A-share', '{"fixture":"company-v1"}'::jsonb,
    'sha256:company-v1', 'rehearsal', 'stage4-mapping-approved',
    'verified company identity from the read-only source snapshot'
);
-- A legacy database may contain multiple historical aliases for one canonical
-- security.  Legacy identities remain unique and auditable; the stable
-- business identity is intentionally many-to-one.
SELECT * FROM operations.register_user_content_notes_dependency_mapping(
    2, 'company', 'research.db', 'company', '554',
    'company:COHU:US-equity', '{"fixture":"company-alias-v1"}'::jsonb,
    'sha256:company-alias-v1', 'rehearsal', 'stage4-mapping-approved',
    'verified first legacy alias for one canonical security'
);
SELECT * FROM operations.register_user_content_notes_dependency_mapping(
    2, 'company', 'research.db', 'company', '491',
    'company:COHU:US-equity', '{"fixture":"company-alias-v2"}'::jsonb,
    'sha256:company-alias-v2', 'rehearsal', 'stage4-mapping-approved',
    'verified second legacy alias for the same canonical security'
);
RESET SESSION AUTHORIZATION;

SET SESSION AUTHORIZATION :"writer_role";
DO $$
BEGIN
    BEGIN
        PERFORM * FROM user_content.put_analyst_note_v2(
            'fenced-note', 'company', '1', 'company:300308.SZ:A-share', NULL,
            'general', NULL, 'must be fenced', 'rehearsal', 0,
            'fenced-idempotency', 'fenced-hash',
            current_setting('honghu.rehearsal_writer_identity')
        );
        RAISE EXCEPTION 'S1 business write unexpectedly succeeded';
    EXCEPTION WHEN insufficient_privilege THEN
        NULL;
    END;
END $$;
RESET SESSION AUTHORIZATION;

-- A non-empty synthetic legacy backfill preserves Q labels, nullable title,
-- text entity id and raw local timestamp strings.
INSERT INTO user_content.analyst_note(
    note_key, entity_type, entity_id, legacy_entity_id_text, entity_key,
    q_number, q_label, note_type, title, content, author, legacy_note_id,
    legacy_created_at_text, legacy_updated_at_text
) VALUES (
    'analyst-note:research.db:42', 'theme', NULL, 'ai_datacenter',
    'theme:ai_datacenter', NULL, 'Q6', 'risk', NULL,
    'synthetic legacy backfill', 'rehearsal', 42,
    '2026-08-11 09:00:00', '2026-08-11 09:00:00'
);

SET SESSION AUTHORIZATION :"controller_role";
SELECT * FROM operations.transition_user_content_notes(
    'S1', 2, 'S2',
    :'writer_identity', 'epoch-user-content',
    '{"source_count":1,"source_max_legacy_id":42}'::jsonb,
    'rehearsal', 'stage4-s2-approved', 'enter controlled S2'
);

SELECT operations.record_user_content_notes_verification(
    :'writer_identity',
    'verification-1', 'verification-hash-1', '{"ok":true}'::jsonb
);
SELECT operations.record_user_content_notes_verification(
    :'writer_identity',
    'verification-1', 'verification-hash-1', '{"ok":true}'::jsonb
);
RESET SESSION AUTHORIZATION;

-- A failed delete cannot advance S2.  The first successful formal operation is
-- a soft delete of a non-empty backfilled row, and it advances S2 -> S3 in the
-- same transaction as the note revision, audit and idempotency record.
SET SESSION AUTHORIZATION :"writer_role";
DO $$
BEGIN
    BEGIN
        PERFORM * FROM user_content.soft_delete_analyst_note_v2(
            'analyst-note:missing', 'rehearsal', 1,
            'missing-delete-1', 'missing-delete-hash-1',
            current_setting('honghu.rehearsal_writer_identity')
        );
        RAISE EXCEPTION 'missing S2 delete unexpectedly succeeded';
    EXCEPTION WHEN serialization_failure THEN
        NULL;
    END;
END $$;
RESET SESSION AUTHORIZATION;
SET SESSION AUTHORIZATION :"controller_role";
-- Verification writes are accepted only in S2, so this proves the failed
-- delete did not advance the authority row without granting base-table SELECT.
SELECT operations.record_user_content_notes_verification(
    :'writer_identity',
    'verification-after-failed-delete', 'verification-after-failed-delete-hash',
    '{"failed_delete_left_authority_in_s2":true}'::jsonb
);
RESET SESSION AUTHORIZATION;
SET SESSION AUTHORIZATION :"writer_role";
SELECT * FROM user_content.soft_delete_analyst_note_v2(
    'analyst-note:research.db:42', 'rehearsal', 1,
    'first-formal-delete-1', 'first-formal-delete-hash-1',
    :'writer_identity'
);
-- Simulated uncertain client response after the delete commit.
SELECT * FROM user_content.soft_delete_analyst_note_v2(
    'analyst-note:research.db:42', 'rehearsal', 1,
    'first-formal-delete-1', 'first-formal-delete-hash-1',
    :'writer_identity'
);

-- Create and update remain governed formal mutations after S3.
SELECT * FROM user_content.put_analyst_note_v2(
    'analyst-note:new:idempotent-1', 'theme', 'ai_datacenter',
    'theme:ai_datacenter', 'Q6', 'thesis', NULL,
    'first formal note', 'rehearsal', 0,
    'formal-create-1', 'formal-create-hash-1', :'writer_identity'
);

-- A shared-identity row created after the initial mapping freeze cannot be
-- referenced until a controller records a separately evidenced mapping.
DO $$
BEGIN
    BEGIN
        PERFORM * FROM user_content.put_analyst_note_v2(
            'analyst-note:new-company', 'company', '2',
            'company:688041.SH:A-share', NULL, 'general', NULL,
            'must remain fenced before mapping', 'rehearsal', 0,
            'unmapped-company-1', 'unmapped-company-hash-1',
            current_setting('honghu.rehearsal_writer_identity')
        );
        RAISE EXCEPTION 'unmapped dependency unexpectedly succeeded';
    EXCEPTION WHEN foreign_key_violation THEN
        NULL;
    END;
END $$;
RESET SESSION AUTHORIZATION;

SET SESSION AUTHORIZATION :"controller_role";
SELECT * FROM operations.register_user_content_notes_dependency_mapping(
    4, 'company', 'research.db', 'company', '2',
    'company:688041.SH:A-share', '{"fixture":"company-v2"}'::jsonb,
    'sha256:company-v2', 'rehearsal', 'stage4-incremental-mapping-approved',
    'verified a new SQLite-authoritative company after note cutover'
);
RESET SESSION AUTHORIZATION;

SET SESSION AUTHORIZATION :"writer_role";
SELECT * FROM user_content.put_analyst_note_v2(
    'analyst-note:new-company', 'company', '2',
    'company:688041.SH:A-share', NULL, 'general', NULL,
    'mapped after controlled evidence', 'rehearsal', 0,
    'mapped-company-1', 'mapped-company-hash-1',
    :'writer_identity'
);
-- Simulated uncertain client response: replay the same operation identity.
SELECT * FROM user_content.put_analyst_note_v2(
    'analyst-note:new:idempotent-1', 'theme', 'ai_datacenter',
    'theme:ai_datacenter', 'Q6', 'thesis', NULL,
    'first formal note', 'rehearsal', 0,
    'formal-create-1', 'formal-create-hash-1', :'writer_identity'
);

DO $$
BEGIN
    BEGIN
        PERFORM * FROM user_content.put_analyst_note_v2(
            'analyst-note:new:idempotent-1', 'theme', 'ai_datacenter',
            'theme:ai_datacenter', 'Q6', 'thesis', NULL,
            'stale overwrite', 'rehearsal', 0,
            'stale-update-1', 'stale-update-hash-1',
            current_setting('honghu.rehearsal_writer_identity')
        );
        RAISE EXCEPTION 'stale update unexpectedly succeeded';
    EXCEPTION WHEN serialization_failure THEN
        NULL;
    END;
END $$;

SELECT * FROM user_content.put_analyst_note_v2(
    'analyst-note:new:idempotent-1', 'theme', 'ai_datacenter',
    'theme:ai_datacenter', 'Q6', 'thesis', NULL,
    'updated formal note', 'rehearsal', 1,
    'formal-update-1', 'formal-update-hash-1', :'writer_identity'
);
SELECT * FROM user_content.soft_delete_analyst_note_v2(
    'analyst-note:new:idempotent-1', 'rehearsal', 2,
    'formal-delete-1', 'formal-delete-hash-1', :'writer_identity'
);
SELECT * FROM user_content.soft_delete_analyst_note_v2(
    'analyst-note:new:idempotent-1', 'rehearsal', 2,
    'formal-delete-1', 'formal-delete-hash-1', :'writer_identity'
);
RESET SESSION AUTHORIZATION;

-- S3 -> S4 requires a new approval, preserves the PostgreSQL authority
-- identity, and rejects both a wrong backend and parameter drift.
DO $$
BEGIN
    BEGIN
        PERFORM * FROM operations.transition_cutover_unit(
            'user_content_notes', 'S3', 4, 'S4', 'sqlite_transition',
            current_setting('honghu.rehearsal_writer_identity'), 'epoch-user-content',
            '{"source_count":1,"source_max_legacy_id":42}'::jsonb,
            'rehearsal', 'stage4-s4-approved', 'wrong backend must fail'
        );
        RAISE EXCEPTION 'S4 with SQLite backend unexpectedly succeeded';
    EXCEPTION WHEN invalid_parameter_value THEN
        NULL;
    END;
END $$;

SET SESSION AUTHORIZATION :"controller_role";
DO $$
BEGIN
    BEGIN
        PERFORM * FROM operations.transition_user_content_notes(
            'S3', 4, 'S4', current_setting('honghu.rehearsal_writer_identity'),
            'epoch-user-content',
            '{"source_count":1,"source_max_legacy_id":42}'::jsonb,
            'rehearsal', NULL, 'missing approval must fail'
        );
        RAISE EXCEPTION 'S4 without approval unexpectedly succeeded';
    EXCEPTION WHEN invalid_parameter_value THEN
        NULL;
    END;
    BEGIN
        PERFORM * FROM operations.transition_user_content_notes(
            'S3', 4, 'S4', 'different-writer', 'epoch-user-content',
            '{"source_count":1,"source_max_legacy_id":42}'::jsonb,
            'rehearsal', 'stage4-s4-approved', 'writer drift must fail'
        );
        RAISE EXCEPTION 'S4 with writer drift unexpectedly succeeded';
    EXCEPTION WHEN invalid_parameter_value THEN
        NULL;
    END;
    BEGIN
        PERFORM * FROM operations.transition_user_content_notes(
            'S3', 4, 'S4', current_setting('honghu.rehearsal_writer_identity'),
            'epoch-user-content',
            '{"source_count":1,"source_max_legacy_id":42}'::jsonb,
            'rehearsal', 'stage4-s2-approved', 'reused approval must fail'
        );
        RAISE EXCEPTION 'S4 with reused approval unexpectedly succeeded';
    EXCEPTION WHEN invalid_parameter_value THEN
        NULL;
    END;
END $$;
SELECT * FROM operations.transition_user_content_notes(
    'S3', 4, 'S4', :'writer_identity',
    'epoch-user-content',
    '{"source_count":1,"source_max_legacy_id":42}'::jsonb,
    'rehearsal', 'stage4-s4-approved',
    'observation and recovery gates approved for S4'
);
RESET SESSION AUTHORIZATION;

DO $$
DECLARE
    v_state text;
    v_backend text;
    v_writer text;
    v_epoch text;
    v_watermark jsonb;
    v_formal jsonb;
    v_approval text;
    v_formal_scope text;
    v_formal_object_key text;
    v_q_label text;
    v_entity_id bigint;
    v_legacy_entity_id text;
    v_title text;
    v_revision bigint;
    v_deleted timestamptz;
BEGIN
    SELECT state, authoritative_backend, writer_identity, cutover_epoch,
           sqlite_final_watermark, postgresql_first_formal_commit,
           approval_reference
      INTO v_state, v_backend, v_writer, v_epoch, v_watermark, v_formal, v_approval
      FROM operations.cutover_unit_authority
     WHERE cutover_unit = 'user_content_notes';
    IF v_state <> 'S4' OR v_backend <> 'postgresql_production'
       OR v_writer <> current_setting('honghu.rehearsal_writer_identity')
       OR v_epoch <> 'epoch-user-content'
       OR v_watermark <> '{"source_count":1,"source_max_legacy_id":42}'::jsonb
       OR v_formal IS NULL OR v_approval <> 'stage4-s4-approved' THEN
        RAISE EXCEPTION 'S4 did not preserve the approved PostgreSQL authority identity';
    END IF;
    v_formal_scope := v_formal->>'operation_scope';
    v_formal_object_key := v_formal->>'object_key';
    IF v_formal_scope <> 'user_content.soft_delete_analyst_note_v2'
       OR v_formal_object_key <> 'analyst-note:research.db:42' THEN
        RAISE EXCEPTION 'delete-first formal watermark was not preserved';
    END IF;
    SELECT q_label, entity_id, legacy_entity_id_text, title, deleted_at
      INTO v_q_label, v_entity_id, v_legacy_entity_id, v_title, v_deleted
      FROM user_content.analyst_note
     WHERE legacy_note_id = 42;
    IF v_q_label <> 'Q6' OR v_entity_id IS NOT NULL
       OR v_legacy_entity_id <> 'ai_datacenter' OR v_title IS NOT NULL
       OR v_deleted IS NULL THEN
        RAISE EXCEPTION 'legacy compatibility reconciliation failed';
    END IF;
    SELECT revision, deleted_at INTO v_revision, v_deleted
      FROM user_content.analyst_note
     WHERE note_key = 'analyst-note:new:idempotent-1';
    IF v_revision <> 3 OR v_deleted IS NULL THEN
        RAISE EXCEPTION 'revision or soft-delete invariant failed';
    END IF;
END $$;

SELECT jsonb_build_object(
    'status', 'pass',
    'authority_state', (
        SELECT state FROM operations.cutover_unit_authority
         WHERE cutover_unit = 'user_content_notes'
    ),
    'authority_revision_count', (
        SELECT count(*) FROM audit.cutover_unit_authority_revision
         WHERE cutover_unit = 'user_content_notes'
    ),
    'note_count', (SELECT count(*) FROM user_content.analyst_note),
    'soft_deleted_count', (
        SELECT count(*) FROM user_content.analyst_note WHERE deleted_at IS NOT NULL
    ),
    'first_formal_operation_scope', (
        SELECT postgresql_first_formal_commit->>'operation_scope'
          FROM operations.cutover_unit_authority
         WHERE cutover_unit = 'user_content_notes'
    ),
    'first_formal_object_key', (
        SELECT postgresql_first_formal_commit->>'object_key'
          FROM operations.cutover_unit_authority
         WHERE cutover_unit = 'user_content_notes'
    ),
    'user_content_audit_count', (SELECT count(*) FROM audit.user_content_revision),
    'idempotency_count', (SELECT count(*) FROM operations.idempotency_record),
    'verification_count', (SELECT count(*) FROM operations.cutover_verification_write),
    'dependency_mapping_audit_count', (
        SELECT count(*) FROM audit.cutover_dependency_mapping_revision
         WHERE cutover_unit = 'user_content_notes'
    ),
    'stable_alias_count', (
        SELECT count(*) FROM operations.cutover_dependency_mapping
         WHERE cutover_unit = 'user_content_notes'
           AND stable_key = 'company:COHU:US-equity'
    ),
    's1_abandon_state', (
        SELECT state FROM operations.cutover_unit_authority
         WHERE cutover_unit = 'rehearsal_s1_abandon'
    ),
    's2_rollback_state', (
        SELECT state FROM operations.cutover_unit_authority
         WHERE cutover_unit = 'rehearsal_s2_no_formal_write'
    )
);
