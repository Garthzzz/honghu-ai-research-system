\set ON_ERROR_STOP on
BEGIN;

-- Keep row-level authority, revision and idempotency checks while bounding the
-- batch response.  Appending every row result to an ever-growing jsonb array
-- copied the full array on every iteration and made large retention batches
-- O(n^2).  Per-row mutation_result rows remain the durable audit trail.
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
        PERFORM domain_data.mutate_record_v1(
            p_cutover_unit,p_operation_scope||':row',
            p_idempotency_key||':'||lpad(v_index::text,8,'0'),
            v_item->>'request_sha256',v_item->>'source_database',
            v_item->>'source_table',v_item->>'source_key',v_item->'payload',
            v_item->>'row_sha256',(v_item->>'expected_revision')::bigint,
            coalesce((v_item->>'delete')::boolean,false),p_writer_identity,p_actor
        );
    END LOOP;
    v_result:=jsonb_build_object(
        'cutover_unit',p_cutover_unit,
        'operation_scope',p_operation_scope,
        'idempotency_key',p_idempotency_key,
        'request_sha256',p_request_sha256,
        'mutation_count',v_index,
        'result_detail','summary_only',
        'row_results','stored_in_mutation_result',
        'mutations_omitted',true
    );
    INSERT INTO domain_data.mutation_result(
        cutover_unit,operation_scope,idempotency_key,request_sha256,result_payload
    ) VALUES (p_cutover_unit,p_operation_scope,p_idempotency_key,p_request_sha256,v_result);
    RETURN v_result;
END;
$$;

INSERT INTO operations.schema_migration(migration_id,migration_sha256,phase,forward_only)
VALUES('0016_stage5_bounded_mutation_batch_result',:'migration_sha256','expand',false)
ON CONFLICT(migration_id) DO NOTHING;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM operations.schema_migration
        WHERE migration_id='0016_stage5_bounded_mutation_batch_result'
          AND migration_sha256=current_setting('honghu.migration_sha256'))
    THEN RAISE EXCEPTION 'migration identity exists with a different SHA256'; END IF;
END $$;
COMMIT;
