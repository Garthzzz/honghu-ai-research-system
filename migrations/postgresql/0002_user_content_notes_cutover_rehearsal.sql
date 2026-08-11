\set ON_ERROR_STOP on

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

-- Initialize the actual first-unit authority in S0 and prove its writer is fenced.
SELECT * FROM operations.transition_cutover_unit(
    'user_content_notes', 'ABSENT', 0, 'S0', 'sqlite_transition',
    NULL, NULL, NULL, 'rehearsal', 'stage4-design-only', 'initialize S0'
);

INSERT INTO operations.cutover_dependency_mapping(
    cutover_unit, entity_type, source_database, source_table,
    legacy_id, stable_key, source_watermark
) VALUES
    ('user_content_notes', 'theme', 'research.db', 'theme',
     'ai_datacenter', 'theme:ai_datacenter', '{"fixture":"theme-v1"}'::jsonb),
    ('user_content_notes', 'company', 'research.db', 'company',
     '1', 'company:300308.SZ:A-share', '{"fixture":"company-v1"}'::jsonb);

SET SESSION AUTHORIZATION :"writer_role";
DO $$
BEGIN
    BEGIN
        PERFORM * FROM user_content.put_analyst_note_v2(
            'fenced-note', 'company', '1', 'company:300308.SZ:A-share', NULL,
            'general', NULL, 'must be fenced', 'rehearsal', 0,
            'fenced-idempotency', 'fenced-hash', 'honghu_stage4_writer_rehearsal'
        );
        RAISE EXCEPTION 'S0 business write unexpectedly succeeded';
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

SELECT * FROM operations.transition_cutover_unit(
    'user_content_notes', 'S0', 1, 'S1', 'sqlite_transition',
    NULL, NULL, NULL, 'rehearsal', 'stage4-design-only', 'backfill reconciled'
);
SELECT * FROM operations.transition_cutover_unit(
    'user_content_notes', 'S1', 2, 'S2', 'postgresql_production',
    :'writer_identity', 'epoch-user-content',
    '{"source_count":1,"source_max_legacy_id":42}'::jsonb,
    'rehearsal', 'stage4-design-only', 'enter controlled S2'
);

SELECT operations.record_cutover_verification(
    'user_content_notes', :'writer_identity',
    'verification-1', 'verification-hash-1', '{"ok":true}'::jsonb
);
SELECT operations.record_cutover_verification(
    'user_content_notes', :'writer_identity',
    'verification-1', 'verification-hash-1', '{"ok":true}'::jsonb
);

-- The first formal write and S2 -> S3 transition occur in one transaction.
SET SESSION AUTHORIZATION :"writer_role";
SELECT * FROM user_content.put_analyst_note_v2(
    'analyst-note:new:idempotent-1', 'theme', 'ai_datacenter',
    'theme:ai_datacenter', 'Q6', 'thesis', NULL,
    'first formal note', 'rehearsal', 0,
    'formal-create-1', 'formal-create-hash-1', 'honghu_stage4_writer_rehearsal'
);
-- Simulated uncertain client response: replay the same operation identity.
SELECT * FROM user_content.put_analyst_note_v2(
    'analyst-note:new:idempotent-1', 'theme', 'ai_datacenter',
    'theme:ai_datacenter', 'Q6', 'thesis', NULL,
    'first formal note', 'rehearsal', 0,
    'formal-create-1', 'formal-create-hash-1', 'honghu_stage4_writer_rehearsal'
);

DO $$
BEGIN
    BEGIN
        PERFORM * FROM user_content.put_analyst_note_v2(
            'analyst-note:new:idempotent-1', 'theme', 'ai_datacenter',
            'theme:ai_datacenter', 'Q6', 'thesis', NULL,
            'stale overwrite', 'rehearsal', 0,
            'stale-update-1', 'stale-update-hash-1', 'honghu_stage4_writer_rehearsal'
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
    'formal-update-1', 'formal-update-hash-1', 'honghu_stage4_writer_rehearsal'
);
SELECT * FROM user_content.soft_delete_analyst_note_v2(
    'analyst-note:new:idempotent-1', 'rehearsal', 2,
    'formal-delete-1', 'formal-delete-hash-1', 'honghu_stage4_writer_rehearsal'
);
SELECT * FROM user_content.soft_delete_analyst_note_v2(
    'analyst-note:new:idempotent-1', 'rehearsal', 2,
    'formal-delete-1', 'formal-delete-hash-1', 'honghu_stage4_writer_rehearsal'
);
RESET SESSION AUTHORIZATION;

DO $$
DECLARE
    v_state text;
    v_formal jsonb;
    v_q_label text;
    v_entity_id bigint;
    v_legacy_entity_id text;
    v_title text;
    v_revision bigint;
    v_deleted timestamptz;
BEGIN
    SELECT state, postgresql_first_formal_commit
      INTO v_state, v_formal
      FROM operations.cutover_unit_authority
     WHERE cutover_unit = 'user_content_notes';
    IF v_state <> 'S3' OR v_formal IS NULL THEN
        RAISE EXCEPTION 'formal write did not durably establish S3';
    END IF;
    SELECT q_label, entity_id, legacy_entity_id_text, title
      INTO v_q_label, v_entity_id, v_legacy_entity_id, v_title
      FROM user_content.analyst_note
     WHERE legacy_note_id = 42;
    IF v_q_label <> 'Q6' OR v_entity_id IS NOT NULL
       OR v_legacy_entity_id <> 'ai_datacenter' OR v_title IS NOT NULL THEN
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
    'user_content_audit_count', (SELECT count(*) FROM audit.user_content_revision),
    'idempotency_count', (SELECT count(*) FROM operations.idempotency_record),
    'verification_count', (SELECT count(*) FROM operations.cutover_verification_write),
    's1_abandon_state', (
        SELECT state FROM operations.cutover_unit_authority
         WHERE cutover_unit = 'rehearsal_s1_abandon'
    ),
    's2_rollback_state', (
        SELECT state FROM operations.cutover_unit_authority
         WHERE cutover_unit = 'rehearsal_s2_no_formal_write'
    )
);
