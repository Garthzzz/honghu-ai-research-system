\set ON_ERROR_STOP on
BEGIN;
SELECT set_config('honghu.migration_sha256', :'migration_sha256', true);

-- Retention deletes can contain hundreds of thousands of authoritative
-- records.  Keep the generic path for mixed/upsert batches, but execute an
-- all-delete sentiment chunk as one set-based statement.  The caller keeps
-- every bounded chunk in one PostgreSQL transaction, preserving the complete
-- retention ledger/raw-delete atomicity and exact replay contract.
CREATE OR REPLACE FUNCTION domain_data.apply_mutation_batch_v1(
    p_cutover_unit text,p_operation_scope text,p_idempotency_key text,
    p_request_sha256 text,p_mutations jsonb,p_writer_identity text,p_actor text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,domain_data,migration,operations,audit
AS $$
DECLARE
    v_existing domain_data.mutation_result%ROWTYPE;
    v_authority operations.cutover_unit_authority%ROWTYPE;
    v_formal domain_data.formal_unit_snapshot%ROWTYPE;
    v_item jsonb;
    v_index bigint:=0;
    v_count bigint:=0;
    v_overlay_count bigint:=0;
    v_audit_count bigint:=0;
    v_row_result_count bigint:=0;
    v_result jsonb;
    v_all_sentiment_deletes boolean:=false;
BEGIN
    IF jsonb_typeof(p_mutations)<>'array' OR jsonb_array_length(p_mutations)=0 THEN
        RAISE EXCEPTION 'mutation batch must be a non-empty array' USING ERRCODE='22023';
    END IF;
    IF p_request_sha256 !~ '^[0-9a-f]{64}$'
       OR nullif(btrim(p_operation_scope),'') IS NULL
       OR nullif(btrim(p_idempotency_key),'') IS NULL
       OR nullif(btrim(p_actor),'') IS NULL THEN
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

    v_all_sentiment_deletes := p_cutover_unit='sentiment_analytics' AND NOT EXISTS (
        SELECT 1 FROM jsonb_array_elements(p_mutations) AS item
         WHERE coalesce(item->>'delete','false')<>'true'
    );
    IF v_all_sentiment_deletes THEN
        SELECT * INTO v_authority FROM operations.cutover_unit_authority
         WHERE cutover_unit=p_cutover_unit FOR UPDATE;
        IF NOT FOUND OR v_authority.state NOT IN ('S3','S4')
           OR v_authority.authoritative_backend<>'postgresql_production'
           OR v_authority.writer_identity<>p_writer_identity
           OR NOT pg_has_role(session_user,p_writer_identity,'MEMBER') THEN
            RAISE EXCEPTION 'mutation batch writer is fenced' USING ERRCODE='42501';
        END IF;
        SELECT * INTO v_formal FROM domain_data.formal_unit_snapshot
         WHERE cutover_unit=p_cutover_unit;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'formal unit snapshot is absent' USING ERRCODE='55000';
        END IF;
        IF EXISTS (
            SELECT 1 FROM jsonb_array_elements(p_mutations) AS item
             WHERE coalesce(item->>'request_sha256','') !~ '^[0-9a-f]{64}$'
                OR coalesce(item->>'row_sha256','') !~ '^[0-9a-f]{64}$'
                OR coalesce(jsonb_typeof(item->'payload'),'')<>'object'
                OR coalesce(item->>'expected_revision','') !~ '^[0-9]+$'
                OR nullif(btrim(item->>'source_database'),'') IS NULL
                OR nullif(btrim(item->>'source_table'),'') IS NULL
                OR nullif(btrim(item->>'source_key'),'') IS NULL
        ) THEN
            RAISE EXCEPTION 'sentiment delete mutation identity is incomplete' USING ERRCODE='22023';
        END IF;
        IF EXISTS (
            SELECT 1 FROM jsonb_array_elements(p_mutations) AS item
             WHERE NOT EXISTS (
                SELECT 1 FROM jsonb_array_elements(
                    coalesce(v_formal.source_watermark->'tables','[]'::jsonb)
                ) AS owned
                 WHERE owned->>'source_database'=item->>'source_database'
                   AND owned->>'source_table'=item->>'source_table'
             )
        ) THEN
            RAISE EXCEPTION 'sentiment delete batch contains an object outside formal unit ownership'
                USING ERRCODE='42501';
        END IF;
        IF EXISTS (
            SELECT 1 FROM jsonb_array_elements(p_mutations) AS item
             GROUP BY item->>'source_database',item->>'source_table',item->>'source_key'
            HAVING count(*)<>1
        ) THEN
            RAISE EXCEPTION 'sentiment delete batch contains duplicate record identities'
                USING ERRCODE='22023';
        END IF;
        IF EXISTS (
            SELECT 1
              FROM jsonb_array_elements(p_mutations) WITH ORDINALITY AS entry(item,ordinality)
              JOIN domain_data.mutation_result existing
                ON existing.cutover_unit=p_cutover_unit
               AND existing.operation_scope=p_operation_scope||':row'
               AND existing.idempotency_key=(
                    p_idempotency_key||':'||lpad(entry.ordinality::text,8,'0')
               )
        ) THEN
            RAISE EXCEPTION 'sentiment delete batch has incomplete row idempotency state'
                USING ERRCODE='55000';
        END IF;
        IF EXISTS (
            WITH input AS MATERIALIZED (
                SELECT entry.ordinality,
                       entry.item->>'source_database' AS source_database,
                       entry.item->>'source_table' AS source_table,
                       entry.item->>'source_key' AS source_key,
                       (entry.item->>'expected_revision')::bigint AS expected_revision
                  FROM jsonb_array_elements(p_mutations) WITH ORDINALITY AS entry(item,ordinality)
            ), resolved AS MATERIALIZED (
                SELECT input.*,
                       CASE WHEN overlay.source_key IS NOT NULL THEN overlay.revision
                            WHEN base.source_key IS NOT NULL THEN 1 ELSE 0 END AS current_revision
                  FROM input
                  LEFT JOIN domain_data.record_overlay overlay
                    ON overlay.cutover_unit=p_cutover_unit
                   AND overlay.source_database=input.source_database
                   AND overlay.source_table=input.source_table
                   AND overlay.source_key=input.source_key
                  LEFT JOIN migration.source_row base
                    ON base.snapshot_id=v_formal.source_snapshot_id
                   AND base.source_database=input.source_database
                   AND base.source_table=input.source_table
                   AND base.source_key=input.source_key
            )
            SELECT 1 FROM resolved
             WHERE current_revision=0 OR current_revision<>expected_revision
        ) THEN
            RAISE EXCEPTION 'stale or missing sentiment delete record revision'
                USING ERRCODE='40001';
        END IF;

        WITH input AS MATERIALIZED (
            SELECT entry.ordinality,
                   entry.item->>'request_sha256' AS request_sha256,
                   entry.item->>'source_database' AS source_database,
                   entry.item->>'source_table' AS source_table,
                   entry.item->>'source_key' AS source_key,
                   entry.item->'payload' AS payload,
                   entry.item->>'row_sha256' AS row_sha256,
                   (entry.item->>'expected_revision')::bigint AS expected_revision
              FROM jsonb_array_elements(p_mutations) WITH ORDINALITY AS entry(item,ordinality)
        ), resolved AS MATERIALIZED (
            SELECT input.*,
                   CASE WHEN overlay.source_key IS NOT NULL THEN overlay.revision ELSE 1 END AS current_revision,
                   coalesce(overlay.payload,base.payload) AS previous_payload,
                   p_idempotency_key||':'||lpad(input.ordinality::text,8,'0') AS row_operation_key
              FROM input
              LEFT JOIN domain_data.record_overlay overlay
                ON overlay.cutover_unit=p_cutover_unit
               AND overlay.source_database=input.source_database
               AND overlay.source_table=input.source_table
               AND overlay.source_key=input.source_key
              LEFT JOIN migration.source_row base
                ON base.snapshot_id=v_formal.source_snapshot_id
               AND base.source_database=input.source_database
               AND base.source_table=input.source_table
               AND base.source_key=input.source_key
        ), overlay_write AS (
            INSERT INTO domain_data.record_overlay(
                cutover_unit,source_database,source_table,source_key,payload,row_sha256,
                revision,deleted,operation_key,updated_by
            )
            SELECT p_cutover_unit,source_database,source_table,source_key,payload,row_sha256,
                   current_revision+1,true,row_operation_key,p_actor
              FROM resolved
            ON CONFLICT(cutover_unit,source_database,source_table,source_key) DO UPDATE SET
                payload=excluded.payload,row_sha256=excluded.row_sha256,
                revision=excluded.revision,deleted=true,
                operation_key=excluded.operation_key,updated_by=excluded.updated_by,
                updated_at=clock_timestamp()
            RETURNING 1
        ), audit_write AS (
            INSERT INTO audit.domain_record_revision(
                cutover_unit,source_database,source_table,source_key,
                from_revision,to_revision,previous_payload,replacement_payload,
                deleted,operation_key,actor
            )
            SELECT p_cutover_unit,source_database,source_table,source_key,
                   current_revision,current_revision+1,previous_payload,payload,
                   true,row_operation_key,p_actor
              FROM resolved
            RETURNING 1
        ), row_result_write AS (
            INSERT INTO domain_data.mutation_result(
                cutover_unit,operation_scope,idempotency_key,request_sha256,result_payload
            )
            SELECT p_cutover_unit,p_operation_scope||':row',row_operation_key,
                   request_sha256,jsonb_build_object(
                       'cutover_unit',p_cutover_unit,'source_table',source_table,
                       'source_key',source_key,'revision',current_revision+1,'deleted',true
                   )
              FROM resolved
            RETURNING 1
        )
        SELECT (SELECT count(*) FROM resolved),
               (SELECT count(*) FROM overlay_write),
               (SELECT count(*) FROM audit_write),
               (SELECT count(*) FROM row_result_write)
          INTO v_count,v_overlay_count,v_audit_count,v_row_result_count;
        IF v_count=0 OR v_overlay_count<>v_count OR v_audit_count<>v_count
           OR v_row_result_count<>v_count THEN
            RAISE EXCEPTION 'set-based sentiment delete batch did not mutate every row'
                USING ERRCODE='55000';
        END IF;
        v_index:=v_count;
    ELSE
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
    END IF;
    v_result:=jsonb_build_object(
        'cutover_unit',p_cutover_unit,'operation_scope',p_operation_scope,
        'idempotency_key',p_idempotency_key,'request_sha256',p_request_sha256,
        'mutation_count',v_index,'result_detail','summary_only',
        'row_results','stored_in_mutation_result','mutations_omitted',true,
        'execution_mode',CASE WHEN v_all_sentiment_deletes THEN 'set_based_delete' ELSE 'row_fenced' END
    );
    INSERT INTO domain_data.mutation_result(
        cutover_unit,operation_scope,idempotency_key,request_sha256,result_payload
    ) VALUES (p_cutover_unit,p_operation_scope,p_idempotency_key,p_request_sha256,v_result);
    RETURN v_result;
END;
$$;

INSERT INTO operations.schema_migration(migration_id,migration_sha256,phase,forward_only)
VALUES('0017_stage5_set_based_sentiment_delete_batch',:'migration_sha256','expand',false)
ON CONFLICT(migration_id) DO NOTHING;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM operations.schema_migration
        WHERE migration_id='0017_stage5_set_based_sentiment_delete_batch'
          AND migration_sha256=current_setting('honghu.migration_sha256'))
    THEN RAISE EXCEPTION 'migration identity exists with a different SHA256'; END IF;
END $$;
COMMIT;
