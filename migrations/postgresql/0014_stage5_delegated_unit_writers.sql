\set ON_ERROR_STOP on

BEGIN;
SELECT set_config('honghu.migration_sha256', :'migration_sha256', true);

-- A production task login is a constrained member of exactly the reviewed
-- unit writer role.  The durable authority row continues to name the owning
-- writer role; callers cannot nominate another identity, and non-members are
-- rejected.  This preserves least privilege without weakening the S3/S4
-- authority, object ownership, revision, or idempotency fences.
CREATE OR REPLACE FUNCTION domain_data.mutate_record_v1(
    p_cutover_unit text,p_operation_scope text,p_idempotency_key text,p_request_sha256 text,
    p_source_database text,p_source_table text,p_source_key text,p_payload jsonb,
    p_row_sha256 text,p_expected_revision bigint,p_delete boolean,
    p_writer_identity text,p_actor text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,domain_data,migration,operations,audit
AS $$
DECLARE
    v_existing domain_data.mutation_result%ROWTYPE;
    v_authority operations.cutover_unit_authority%ROWTYPE;
    v_formal domain_data.formal_unit_snapshot%ROWTYPE;
    v_overlay domain_data.record_overlay%ROWTYPE;
    v_base_payload jsonb;
    v_current_revision bigint:=0;
    v_previous jsonb;
    v_result jsonb;
BEGIN
    IF p_request_sha256 !~ '^[0-9a-f]{64}$' OR p_row_sha256 !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(p_payload)<>'object' OR nullif(btrim(p_operation_scope),'') IS NULL
       OR nullif(btrim(p_idempotency_key),'') IS NULL OR nullif(btrim(p_actor),'') IS NULL THEN
        RAISE EXCEPTION 'record mutation identity is incomplete' USING ERRCODE='22023';
    END IF;
    IF p_cutover_unit NOT IN (
        'financial_data','research_publication','dynamic_intelligence',
        'operations_governance','investment_hypotheses','opportunity_lens',
        'sentiment_analytics'
    ) OR p_writer_identity<>('honghu_writer_'||p_cutover_unit)
       OR NOT pg_has_role(session_user,p_writer_identity,'MEMBER') THEN
        RAISE EXCEPTION 'record mutation caller does not own cutover unit' USING ERRCODE='42501';
    END IF;
    SELECT * INTO v_existing FROM domain_data.mutation_result
     WHERE cutover_unit=p_cutover_unit AND operation_scope=p_operation_scope
       AND idempotency_key=p_idempotency_key;
    IF FOUND THEN
        IF v_existing.request_sha256<>p_request_sha256 THEN
            RAISE EXCEPTION 'record mutation idempotency conflict' USING ERRCODE='23505';
        END IF;
        RETURN v_existing.result_payload;
    END IF;
    SELECT * INTO v_authority FROM operations.cutover_unit_authority
     WHERE cutover_unit=p_cutover_unit FOR UPDATE;
    IF NOT FOUND OR v_authority.state NOT IN ('S3','S4')
       OR v_authority.authoritative_backend<>'postgresql_production'
       OR v_authority.writer_identity<>p_writer_identity
       OR NOT pg_has_role(session_user,p_writer_identity,'MEMBER') THEN
        RAISE EXCEPTION 'record mutation writer is fenced' USING ERRCODE='42501';
    END IF;
    SELECT * INTO v_formal FROM domain_data.formal_unit_snapshot
     WHERE cutover_unit=p_cutover_unit;
    IF NOT FOUND THEN RAISE EXCEPTION 'formal unit snapshot is absent' USING ERRCODE='55000'; END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM jsonb_array_elements(coalesce(v_formal.source_watermark->'tables','[]'::jsonb)) AS item
         WHERE item->>'source_database'=p_source_database
           AND item->>'source_table'=p_source_table
    ) THEN
        RAISE EXCEPTION 'record mutation object is outside formal unit ownership: %.%',
            p_source_database,p_source_table USING ERRCODE='42501';
    END IF;
    SELECT * INTO v_overlay FROM domain_data.record_overlay
     WHERE cutover_unit=p_cutover_unit AND source_database=p_source_database
       AND source_table=p_source_table AND source_key=p_source_key FOR UPDATE;
    IF FOUND THEN
        v_current_revision:=v_overlay.revision; v_previous:=v_overlay.payload;
    ELSE
        SELECT r.payload INTO v_base_payload FROM migration.source_row r
         WHERE r.snapshot_id=v_formal.source_snapshot_id
           AND r.source_database=p_source_database AND r.source_table=p_source_table
           AND r.source_key=p_source_key;
        IF FOUND THEN v_current_revision:=1; v_previous:=v_base_payload; END IF;
    END IF;
    IF v_current_revision<>p_expected_revision THEN
        RAISE EXCEPTION 'stale domain record revision' USING ERRCODE='40001';
    END IF;
    IF p_delete AND v_current_revision=0 THEN
        RAISE EXCEPTION 'cannot delete missing domain record' USING ERRCODE='40001';
    END IF;
    INSERT INTO domain_data.record_overlay(
        cutover_unit,source_database,source_table,source_key,payload,row_sha256,
        revision,deleted,operation_key,updated_by
    ) VALUES (
        p_cutover_unit,p_source_database,p_source_table,p_source_key,p_payload,p_row_sha256,
        v_current_revision+1,p_delete,p_idempotency_key,p_actor
    ) ON CONFLICT(cutover_unit,source_database,source_table,source_key) DO UPDATE SET
        payload=excluded.payload,row_sha256=excluded.row_sha256,revision=excluded.revision,
        deleted=excluded.deleted,operation_key=excluded.operation_key,
        updated_by=excluded.updated_by,updated_at=clock_timestamp();
    INSERT INTO audit.domain_record_revision(
        cutover_unit,source_database,source_table,source_key,from_revision,to_revision,
        previous_payload,replacement_payload,deleted,operation_key,actor
    ) VALUES (
        p_cutover_unit,p_source_database,p_source_table,p_source_key,v_current_revision,
        v_current_revision+1,v_previous,p_payload,p_delete,p_idempotency_key,p_actor
    );
    v_result:=jsonb_build_object(
        'cutover_unit',p_cutover_unit,'source_table',p_source_table,
        'source_key',p_source_key,'revision',v_current_revision+1,'deleted',p_delete
    );
    INSERT INTO domain_data.mutation_result(
        cutover_unit,operation_scope,idempotency_key,request_sha256,result_payload
    ) VALUES (p_cutover_unit,p_operation_scope,p_idempotency_key,p_request_sha256,v_result);
    RETURN v_result;
END;
$$;

CREATE OR REPLACE FUNCTION domain_data.apply_mutation_batch_v1(
    p_cutover_unit text,p_operation_scope text,p_idempotency_key text,
    p_request_sha256 text,p_mutations jsonb,p_writer_identity text,p_actor text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,domain_data
AS $$
DECLARE
    v_existing domain_data.mutation_result%ROWTYPE;
    v_item jsonb;
    v_results jsonb:='[]'::jsonb;
    v_index bigint:=0;
    v_result jsonb;
BEGIN
    IF jsonb_typeof(p_mutations)<>'array' OR jsonb_array_length(p_mutations)=0 THEN
        RAISE EXCEPTION 'mutation batch must be a non-empty array' USING ERRCODE='22023';
    END IF;
    IF p_request_sha256 !~ '^[0-9a-f]{64}$'
       OR nullif(btrim(p_operation_scope),'') IS NULL
       OR nullif(btrim(p_idempotency_key),'') IS NULL THEN
        RAISE EXCEPTION 'mutation batch identity is incomplete' USING ERRCODE='22023';
    END IF;
    IF p_writer_identity<>('honghu_writer_'||p_cutover_unit)
       OR NOT pg_has_role(session_user,p_writer_identity,'MEMBER') THEN
        RAISE EXCEPTION 'mutation batch caller does not own cutover unit' USING ERRCODE='42501';
    END IF;
    SELECT * INTO v_existing FROM domain_data.mutation_result
     WHERE cutover_unit=p_cutover_unit AND operation_scope=p_operation_scope
       AND idempotency_key=p_idempotency_key;
    IF FOUND THEN
        IF v_existing.request_sha256<>p_request_sha256 THEN
            RAISE EXCEPTION 'mutation batch idempotency conflict' USING ERRCODE='23505';
        END IF;
        RETURN v_existing.result_payload;
    END IF;
    FOR v_item IN SELECT value FROM jsonb_array_elements(p_mutations) LOOP
        v_index:=v_index+1;
        v_result:=domain_data.mutate_record_v1(
            p_cutover_unit,p_operation_scope||':row',
            p_idempotency_key||':'||lpad(v_index::text,8,'0'),
            v_item->>'request_sha256',v_item->>'source_database',
            v_item->>'source_table',v_item->>'source_key',v_item->'payload',
            v_item->>'row_sha256',(v_item->>'expected_revision')::bigint,
            coalesce((v_item->>'delete')::boolean,false),p_writer_identity,p_actor
        );
        v_results:=v_results||jsonb_build_array(v_result);
    END LOOP;
    v_result:=jsonb_build_object(
        'cutover_unit',p_cutover_unit,'operation_scope',p_operation_scope,
        'mutation_count',v_index,'mutations',v_results
    );
    INSERT INTO domain_data.mutation_result(
        cutover_unit,operation_scope,idempotency_key,request_sha256,result_payload
    ) VALUES (p_cutover_unit,p_operation_scope,p_idempotency_key,p_request_sha256,v_result);
    RETURN v_result;
END;
$$;

INSERT INTO operations.schema_migration(migration_id,migration_sha256,phase,forward_only)
VALUES('0014_stage5_delegated_unit_writers',:'migration_sha256','expand',false)
ON CONFLICT(migration_id) DO NOTHING;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM operations.schema_migration
        WHERE migration_id='0014_stage5_delegated_unit_writers'
          AND migration_sha256=current_setting('honghu.migration_sha256'))
    THEN RAISE EXCEPTION 'migration identity exists with a different SHA256'; END IF;
END $$;
COMMIT;
