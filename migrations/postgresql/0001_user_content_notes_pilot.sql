\set ON_ERROR_STOP on

SELECT * FROM user_content.put_analyst_note(
  'pilot-note-001', 'company', 1, NULL, 'research', 'Initial', 'Body v1',
  'stage3-pilot', 0, 'put-001', 'hash-put-001'
);

-- Uncertain-response retry: the same key and payload must return the prior result.
SELECT * FROM user_content.put_analyst_note(
  'pilot-note-001', 'company', 1, NULL, 'research', 'Initial', 'Body v1',
  'stage3-pilot', 0, 'put-001', 'hash-put-001'
);

SELECT * FROM user_content.put_analyst_note(
  'pilot-note-001', 'company', 1, NULL, 'research', 'Updated', 'Body v2',
  'stage3-pilot', 1, 'put-002', 'hash-put-002'
);

SELECT * FROM user_content.soft_delete_analyst_note(
  'pilot-note-001', 'stage3-pilot', 2, 'delete-001', 'hash-delete-001'
);

DO $$
DECLARE
  v_note user_content.analyst_note%ROWTYPE;
  v_audit_count bigint;
BEGIN
  SELECT * INTO v_note FROM user_content.analyst_note WHERE note_key='pilot-note-001';
  IF v_note.revision <> 3 OR v_note.deleted_at IS NULL THEN
    RAISE EXCEPTION 'revision/soft-delete invariant failed';
  END IF;
  SELECT count(*) INTO v_audit_count FROM audit.user_content_revision
    WHERE object_key='pilot-note-001';
  IF v_audit_count <> 3 THEN
    RAISE EXCEPTION 'audit invariant failed: %', v_audit_count;
  END IF;
END $$;

-- Stale updates and idempotency conflicts must fail inside their own
-- subtransactions, leaving the validated note unchanged.
DO $$
BEGIN
  BEGIN
    PERFORM * FROM user_content.put_analyst_note(
      'pilot-note-001', 'company', 1, NULL, 'research', 'Stale', 'Must not win',
      'stage3-pilot', 1, 'put-stale', 'hash-put-stale'
    );
    RAISE EXCEPTION 'stale update unexpectedly succeeded';
  EXCEPTION WHEN serialization_failure THEN
    NULL;
  END;
END $$;

DO $$
BEGIN
  BEGIN
    PERFORM * FROM user_content.put_analyst_note(
      'pilot-note-001', 'company', 1, NULL, 'research', 'Conflict', 'Must not win',
      'stage3-pilot', 3, 'put-001', 'different-request-hash'
    );
    RAISE EXCEPTION 'idempotency conflict unexpectedly succeeded';
  EXCEPTION WHEN unique_violation THEN
    NULL;
  END;
END $$;

SELECT jsonb_build_object(
  'status', 'pass',
  'note_count', (SELECT count(*) FROM user_content.analyst_note),
  'audit_count', (SELECT count(*) FROM audit.user_content_revision),
  'idempotency_count', (SELECT count(*) FROM operations.idempotency_record),
  'final_revision', (SELECT revision FROM user_content.analyst_note WHERE note_key='pilot-note-001'),
  'soft_deleted', (SELECT deleted_at IS NOT NULL FROM user_content.analyst_note WHERE note_key='pilot-note-001')
) AS pilot_result;
