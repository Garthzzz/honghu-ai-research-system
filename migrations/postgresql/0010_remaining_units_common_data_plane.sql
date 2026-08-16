\set ON_ERROR_STOP on

BEGIN;

SELECT set_config('honghu.migration_sha256', :'migration_sha256', true);

CREATE SCHEMA IF NOT EXISTS domain_data;

CREATE TABLE IF NOT EXISTS domain_data.unit_dependency (
    cutover_unit text NOT NULL,
    dependency_unit text NOT NULL,
    PRIMARY KEY (cutover_unit, dependency_unit),
    CHECK (cutover_unit <> dependency_unit)
);

INSERT INTO domain_data.unit_dependency(cutover_unit,dependency_unit) VALUES
    ('financial_data','shared_identity'),
    ('research_publication','shared_identity'),
    ('dynamic_intelligence','shared_identity'),
    ('operations_governance','shared_identity'),
    ('operations_governance','dynamic_intelligence'),
    ('investment_hypotheses','shared_identity'),
    ('investment_hypotheses','research_publication'),
    ('investment_hypotheses','dynamic_intelligence'),
    ('opportunity_lens','shared_identity'),
    ('opportunity_lens','financial_data'),
    ('opportunity_lens','research_publication'),
    ('opportunity_lens','dynamic_intelligence'),
    ('sentiment_analytics','shared_identity'),
    ('sentiment_analytics','dynamic_intelligence')
ON CONFLICT DO NOTHING;

-- The already reconciled migration.source_row set remains immutable.  A
-- formal snapshot points to it and copy-on-write overlays hold only subsequent
-- mutations.  Activating 2.24M staged rows is therefore O(1), not a second
-- bulk backfill, while old SQLite remains a migration/audit baseline only.
CREATE TABLE IF NOT EXISTS domain_data.formal_unit_snapshot (
    cutover_unit text PRIMARY KEY CHECK (cutover_unit IN (
        'financial_data','research_publication','dynamic_intelligence',
        'operations_governance','investment_hypotheses','opportunity_lens',
        'sentiment_analytics'
    )),
    source_snapshot_id text NOT NULL UNIQUE REFERENCES migration.unit_snapshot(snapshot_id),
    source_identity_sha256 text NOT NULL CHECK (source_identity_sha256 ~ '^[0-9a-f]{64}$'),
    source_content_sha256 text NOT NULL CHECK (source_content_sha256 ~ '^[0-9a-f]{64}$'),
    source_row_count bigint NOT NULL CHECK (source_row_count >= 0),
    source_watermark jsonb NOT NULL,
    application_commit_sha text NOT NULL CHECK (application_commit_sha ~ '^[0-9a-f]{40}$'),
    formal_revision bigint NOT NULL DEFAULT 1 CHECK (formal_revision > 0),
    activated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS domain_data.record_overlay (
    cutover_unit text NOT NULL REFERENCES domain_data.formal_unit_snapshot(cutover_unit),
    source_database text NOT NULL,
    source_table text NOT NULL,
    source_key text NOT NULL,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload)='object'),
    row_sha256 text NOT NULL CHECK (row_sha256 ~ '^[0-9a-f]{64}$'),
    -- Existing baseline rows start at revision 1 and their first overlay is
    -- revision 2.  A genuinely new post-cutover object has no baseline row,
    -- so its first durable overlay is revision 1.
    revision bigint NOT NULL CHECK (revision > 0),
    deleted boolean NOT NULL DEFAULT false,
    operation_key text NOT NULL,
    updated_by text NOT NULL CHECK (btrim(updated_by) <> ''),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(cutover_unit,source_database,source_table,source_key)
);

CREATE TABLE IF NOT EXISTS domain_data.mutation_result (
    cutover_unit text NOT NULL,
    operation_scope text NOT NULL,
    idempotency_key text NOT NULL,
    request_sha256 text NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
    result_payload jsonb NOT NULL CHECK (jsonb_typeof(result_payload)='object'),
    committed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(cutover_unit,operation_scope,idempotency_key)
);

CREATE TABLE IF NOT EXISTS audit.domain_record_revision (
    audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cutover_unit text NOT NULL,
    source_database text NOT NULL,
    source_table text NOT NULL,
    source_key text NOT NULL,
    from_revision bigint NOT NULL,
    to_revision bigint NOT NULL,
    previous_payload jsonb,
    replacement_payload jsonb NOT NULL,
    deleted boolean NOT NULL,
    operation_key text NOT NULL,
    actor text NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE(cutover_unit,operation_key)
);

CREATE OR REPLACE VIEW operations.remaining_unit_authority_v1 AS
SELECT cutover_unit,state,authoritative_backend,writer_identity,cutover_epoch,
       sqlite_final_watermark,postgresql_first_formal_commit,
       approval_reference,state_revision
  FROM operations.cutover_unit_authority
 WHERE cutover_unit IN (
    'financial_data','research_publication','dynamic_intelligence',
    'operations_governance','investment_hypotheses','opportunity_lens',
    'sentiment_analytics'
 );

CREATE OR REPLACE FUNCTION domain_data.read_unit_records_v1(p_cutover_unit text)
RETURNS TABLE(
    source_database text,source_table text,source_ordinal bigint,source_key text,
    row_sha256 text,payload jsonb,revision bigint,deleted boolean
)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=pg_catalog,domain_data,migration
AS $$
    SELECT * FROM (
    WITH active AS (
        SELECT source_snapshot_id FROM domain_data.formal_unit_snapshot
         WHERE cutover_unit=p_cutover_unit
    ), base AS (
        SELECT r.source_database,r.source_table,r.source_ordinal,r.source_key,
               r.row_sha256,r.payload
          FROM migration.source_row r JOIN active a ON a.source_snapshot_id=r.snapshot_id
         WHERE r.cutover_unit=p_cutover_unit
    ), overlay AS (
        SELECT * FROM domain_data.record_overlay WHERE cutover_unit=p_cutover_unit
    )
    SELECT b.source_database,b.source_table,b.source_ordinal,b.source_key,
           coalesce(o.row_sha256,b.row_sha256),coalesce(o.payload,b.payload),
           coalesce(o.revision,1::bigint),coalesce(o.deleted,false)
      FROM base b LEFT JOIN overlay o USING(source_database,source_table,source_key)
    UNION ALL
    SELECT o.source_database,o.source_table,0::bigint,o.source_key,
           o.row_sha256,o.payload,o.revision,o.deleted
      FROM overlay o
     WHERE NOT EXISTS (
        SELECT 1 FROM base b WHERE b.source_database=o.source_database
          AND b.source_table=o.source_table AND b.source_key=o.source_key
     )
    ) records
    ORDER BY source_database,source_table,source_ordinal,source_key;
$$;

CREATE OR REPLACE FUNCTION operations.transition_remaining_unit(
    p_cutover_unit text,p_expected_state text,p_expected_revision bigint,
    p_to_state text,p_writer_identity text,p_cutover_epoch text,
    p_sqlite_final_watermark jsonb,p_actor text,p_approval_reference text,p_reason text
) RETURNS TABLE(cutover_unit text,state text,state_revision bigint)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,operations,domain_data
AS $$
DECLARE v_missing text;
BEGIN
    IF p_cutover_unit NOT IN (
        'financial_data','research_publication','dynamic_intelligence',
        'operations_governance','investment_hypotheses','opportunity_lens',
        'sentiment_analytics'
    ) THEN RAISE EXCEPTION 'unit is outside remaining Stage 4 scope' USING ERRCODE='42501'; END IF;
    IF p_to_state='S2' THEN
        SELECT d.dependency_unit INTO v_missing
          FROM domain_data.unit_dependency d
          LEFT JOIN operations.cutover_unit_authority a
            ON a.cutover_unit=d.dependency_unit
         WHERE d.cutover_unit=p_cutover_unit
           AND (a.cutover_unit IS NULL OR a.state NOT IN ('S3','S4')
                OR a.authoritative_backend<>'postgresql_production')
         LIMIT 1;
        IF v_missing IS NOT NULL THEN
            RAISE EXCEPTION 'dependency is not PostgreSQL authoritative: %',v_missing
                USING ERRCODE='42501';
        END IF;
    END IF;
    RETURN QUERY SELECT * FROM operations.transition_cutover_unit(
        p_cutover_unit,p_expected_state,p_expected_revision,p_to_state,
        CASE WHEN p_to_state IN ('S0','S1') THEN 'sqlite_transition'
             WHEN p_to_state IN ('S2','S3','S4') THEN 'postgresql_production' END,
        p_writer_identity,p_cutover_epoch,p_sqlite_final_watermark,
        p_actor,p_approval_reference,p_reason
    );
END;
$$;

CREATE OR REPLACE FUNCTION domain_data.activate_unit_snapshot_v1(
    p_cutover_unit text,p_source_snapshot_id text,p_expected_authority_revision bigint,
    p_idempotency_key text,p_request_sha256 text,p_application_commit_sha text,
    p_writer_identity text,p_actor text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,domain_data,migration,operations,audit
AS $$
DECLARE
    v_existing domain_data.mutation_result%ROWTYPE;
    v_authority operations.cutover_unit_authority%ROWTYPE;
    v_snapshot migration.unit_snapshot%ROWTYPE;
    v_reconciliation jsonb;
    v_result jsonb;
BEGIN
    IF p_request_sha256 !~ '^[0-9a-f]{64}$'
       OR p_application_commit_sha !~ '^[0-9a-f]{40}$'
       OR nullif(btrim(p_idempotency_key),'') IS NULL
       OR nullif(btrim(p_actor),'') IS NULL THEN
        RAISE EXCEPTION 'activation mutation identity is incomplete' USING ERRCODE='22023';
    END IF;
    IF p_cutover_unit NOT IN (
        'financial_data','research_publication','dynamic_intelligence',
        'operations_governance','investment_hypotheses','opportunity_lens',
        'sentiment_analytics'
    ) OR session_user<>('honghu_writer_'||p_cutover_unit)
       OR p_writer_identity<>session_user THEN
        RAISE EXCEPTION 'activation caller does not own cutover unit' USING ERRCODE='42501';
    END IF;
    SELECT * INTO v_existing FROM domain_data.mutation_result
     WHERE cutover_unit=p_cutover_unit AND operation_scope='activate_unit_snapshot_v1'
       AND idempotency_key=p_idempotency_key;
    IF FOUND THEN
        IF v_existing.request_sha256<>p_request_sha256 THEN
            RAISE EXCEPTION 'activation idempotency conflict' USING ERRCODE='23505';
        END IF;
        RETURN v_existing.result_payload;
    END IF;
    SELECT * INTO v_authority FROM operations.cutover_unit_authority
     WHERE cutover_unit=p_cutover_unit FOR UPDATE;
    IF NOT FOUND OR v_authority.state<>'S2'
       OR v_authority.authoritative_backend<>'postgresql_production'
       OR v_authority.writer_identity<>p_writer_identity
       OR v_authority.state_revision<>p_expected_authority_revision
       OR session_user<>p_writer_identity THEN
        RAISE EXCEPTION 'unit activation is fenced or stale' USING ERRCODE='42501';
    END IF;
    SELECT * INTO v_snapshot FROM migration.unit_snapshot
     WHERE snapshot_id=p_source_snapshot_id AND cutover_unit=p_cutover_unit
       AND lifecycle_state='reconciled' AND formal_business_data=false FOR SHARE;
    IF NOT FOUND THEN RAISE EXCEPTION 'reconciled S1 snapshot is missing' USING ERRCODE='40001'; END IF;
    v_reconciliation:=v_snapshot.reconciliation;
    IF (v_reconciliation->>'status')<>'pass'
       OR (v_reconciliation->>'source_row_count')::bigint<>(v_reconciliation->>'target_row_count')::bigint
       OR v_reconciliation->>'source_content_sha256'<>v_reconciliation->>'target_content_sha256' THEN
        RAISE EXCEPTION 'S1 snapshot reconciliation is not exact' USING ERRCODE='40001';
    END IF;
    INSERT INTO domain_data.formal_unit_snapshot(
        cutover_unit,source_snapshot_id,source_identity_sha256,source_content_sha256,
        source_row_count,source_watermark,application_commit_sha
    ) VALUES (
        p_cutover_unit,p_source_snapshot_id,v_snapshot.source_identity_sha256,
        v_reconciliation->>'source_content_sha256',
        (v_reconciliation->>'source_row_count')::bigint,v_snapshot.source_watermark,
        p_application_commit_sha
    );
    IF p_cutover_unit='financial_data' THEN
        UPDATE financial_data.legacy_record
           SET formal_business_data=true
         WHERE source_snapshot_id=p_source_snapshot_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'financial S1 material is absent' USING ERRCODE='40001';
        END IF;
        UPDATE financial_data.unit_snapshot SET
            authority_state='S3',formal_business_data=true,promoted_at=clock_timestamp()
         WHERE cutover_unit='financial_data' AND source_snapshot_id=p_source_snapshot_id
           AND authority_state='S1' AND formal_business_data=false;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'financial S1 snapshot is stale' USING ERRCODE='40001';
        END IF;
    END IF;
    PERFORM operations.promote_cutover_unit_on_first_formal_mutation(
        p_cutover_unit,'domain_data.activate_unit_snapshot_v1',p_idempotency_key,
        p_source_snapshot_id,p_writer_identity,p_actor,
        'activate reconciled copy-on-write domain snapshot as formal PostgreSQL authority'
    );
    v_result:=jsonb_build_object(
        'cutover_unit',p_cutover_unit,'authority_state','S3',
        'source_snapshot_id',p_source_snapshot_id,
        'application_commit_sha',p_application_commit_sha,
        'source_snapshot_application_commit_sha',v_snapshot.application_commit_sha,
        'formal_row_count',(v_reconciliation->>'source_row_count')::bigint
    );
    INSERT INTO domain_data.mutation_result(
        cutover_unit,operation_scope,idempotency_key,request_sha256,result_payload
    ) VALUES (p_cutover_unit,'activate_unit_snapshot_v1',p_idempotency_key,p_request_sha256,v_result);
    RETURN v_result;
END;
$$;

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
    ) OR session_user<>('honghu_writer_'||p_cutover_unit)
       OR p_writer_identity<>session_user THEN
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
       OR v_authority.writer_identity<>p_writer_identity OR session_user<>p_writer_identity THEN
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

-- One compatibility transaction may update several legacy-shaped rows.  The
-- batch identity belongs to the surrounding business mutation (publication,
-- model refresh, task window, or authenticated Viewer request).  Retrying an
-- uncertain response with the same identity returns the already committed
-- result; changing the payload under that identity fails closed.
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
    IF session_user<>('honghu_writer_'||p_cutover_unit)
       OR p_writer_identity<>session_user THEN
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

REVOKE ALL ON SCHEMA domain_data FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA domain_data FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA domain_data FROM PUBLIC;
REVOKE ALL ON operations.remaining_unit_authority_v1 FROM PUBLIC;
REVOKE ALL ON FUNCTION operations.transition_remaining_unit(
    text,text,bigint,text,text,text,jsonb,text,text,text
) FROM PUBLIC;

GRANT USAGE ON SCHEMA domain_data,operations TO :"reader_role", :"controller_role",
    :"writer_financial_data", :"writer_research_publication", :"writer_dynamic_intelligence",
    :"writer_operations_governance", :"writer_investment_hypotheses",
    :"writer_opportunity_lens", :"writer_sentiment_analytics";
GRANT EXECUTE ON FUNCTION domain_data.read_unit_records_v1(text) TO :"reader_role";
GRANT SELECT ON operations.remaining_unit_authority_v1 TO :"reader_role", :"controller_role";
GRANT EXECUTE ON FUNCTION operations.transition_remaining_unit(
    text,text,bigint,text,text,text,jsonb,text,text,text
) TO :"controller_role";
GRANT EXECUTE ON FUNCTION operations.record_cutover_verification(text,text,text,text,jsonb)
    TO :"controller_role";
GRANT EXECUTE ON FUNCTION domain_data.activate_unit_snapshot_v1(
    text,text,bigint,text,text,text,text,text
) TO :"writer_financial_data", :"writer_research_publication", :"writer_dynamic_intelligence",
    :"writer_operations_governance", :"writer_investment_hypotheses",
    :"writer_opportunity_lens", :"writer_sentiment_analytics";
GRANT EXECUTE ON FUNCTION domain_data.mutate_record_v1(
    text,text,text,text,text,text,text,jsonb,text,bigint,boolean,text,text
) TO :"writer_financial_data", :"writer_research_publication", :"writer_dynamic_intelligence",
    :"writer_operations_governance", :"writer_investment_hypotheses",
    :"writer_opportunity_lens", :"writer_sentiment_analytics";
GRANT EXECUTE ON FUNCTION domain_data.apply_mutation_batch_v1(
    text,text,text,text,jsonb,text,text
) TO :"writer_financial_data", :"writer_research_publication", :"writer_dynamic_intelligence",
    :"writer_operations_governance", :"writer_investment_hypotheses",
    :"writer_opportunity_lens", :"writer_sentiment_analytics";
GRANT SELECT ON audit.domain_record_revision TO :"audit_reader_role";

INSERT INTO operations.schema_migration(migration_id,migration_sha256,phase,forward_only)
VALUES('0010_remaining_units_common_data_plane',:'migration_sha256','expand',false)
ON CONFLICT(migration_id) DO NOTHING;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM operations.schema_migration
         WHERE migration_id='0010_remaining_units_common_data_plane'
           AND migration_sha256=current_setting('honghu.migration_sha256')
    ) THEN RAISE EXCEPTION 'migration identity exists with a different SHA256'; END IF;
END $$;

COMMIT;
