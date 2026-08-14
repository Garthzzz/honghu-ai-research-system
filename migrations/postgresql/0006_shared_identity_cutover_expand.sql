\set ON_ERROR_STOP on

BEGIN;

SELECT set_config('honghu.migration_sha256', :'migration_sha256', true);

CREATE TABLE IF NOT EXISTS shared_identity.mutation_result (
    operation_scope text NOT NULL,
    idempotency_key text NOT NULL,
    request_sha256 text NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
    object_key text NOT NULL CHECK (btrim(object_key) <> ''),
    result_payload jsonb NOT NULL CHECK (jsonb_typeof(result_payload) = 'object'),
    committed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (operation_scope,idempotency_key)
);

CREATE OR REPLACE VIEW operations.shared_identity_authority_v1 AS
SELECT cutover_unit,state,authoritative_backend,writer_identity,cutover_epoch,
       approval_reference,state_revision
  FROM operations.cutover_unit_authority
 WHERE cutover_unit='shared_identity';

-- Unit-agnostic control-plane primitive.  It is intentionally not granted to
-- application roles: a domain mutation must first satisfy its own identity,
-- idempotency, revision and writer-fence checks, then call this helper inside
-- the same transaction.
CREATE OR REPLACE FUNCTION operations.promote_cutover_unit_on_first_formal_mutation(
    p_cutover_unit text,
    p_operation_scope text,
    p_idempotency_key text,
    p_object_key text,
    p_writer_identity text,
    p_actor text,
    p_reason text
) RETURNS operations.cutover_unit_authority
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations, audit
AS $$
DECLARE
    v_authority operations.cutover_unit_authority%ROWTYPE;
    v_next_revision bigint;
BEGIN
    IF nullif(btrim(p_cutover_unit),'') IS NULL
       OR nullif(btrim(p_operation_scope),'') IS NULL
       OR nullif(btrim(p_idempotency_key),'') IS NULL
       OR nullif(btrim(p_object_key),'') IS NULL
       OR nullif(btrim(p_writer_identity),'') IS NULL
       OR nullif(btrim(p_actor),'') IS NULL
       OR nullif(btrim(p_reason),'') IS NULL THEN
        RAISE EXCEPTION 'formal mutation authority identity is incomplete'
            USING ERRCODE='22023';
    END IF;
    SELECT * INTO v_authority
      FROM operations.cutover_unit_authority
     WHERE cutover_unit=p_cutover_unit
     FOR UPDATE;
    IF NOT FOUND OR v_authority.state NOT IN ('S2','S3','S4')
       OR v_authority.authoritative_backend <> 'postgresql_production'
       OR v_authority.writer_identity <> p_writer_identity THEN
        RAISE EXCEPTION 'formal mutation authority is fenced'
            USING ERRCODE='42501';
    END IF;
    IF v_authority.state='S2' THEN
        v_next_revision := v_authority.state_revision + 1;
        UPDATE operations.cutover_unit_authority SET
            state='S3',
            postgresql_first_formal_commit=jsonb_build_object(
                'operation_scope',p_operation_scope,
                'idempotency_key',p_idempotency_key,
                'object_key',p_object_key,
                'transaction_id',txid_current()::text,
                'recorded_at',clock_timestamp()
            ),
            state_revision=v_next_revision,
            updated_by=p_actor,
            updated_at=clock_timestamp()
         WHERE cutover_unit=p_cutover_unit
         RETURNING * INTO v_authority;
        INSERT INTO audit.cutover_unit_authority_revision(
            cutover_unit,state_revision,from_state,to_state,
            authoritative_backend,writer_identity,cutover_epoch,
            sqlite_final_watermark,postgresql_first_formal_commit,
            actor,approval_reference,reason
        ) VALUES (
            p_cutover_unit,v_next_revision,'S2','S3',
            v_authority.authoritative_backend,v_authority.writer_identity,
            v_authority.cutover_epoch,v_authority.sqlite_final_watermark,
            v_authority.postgresql_first_formal_commit,p_actor,
            v_authority.approval_reference,p_reason
        );
    END IF;
    RETURN v_authority;
END;
$$;

CREATE OR REPLACE FUNCTION operations.transition_shared_identity(
    p_expected_state text,
    p_expected_revision bigint,
    p_to_state text,
    p_writer_identity text,
    p_cutover_epoch text,
    p_sqlite_final_watermark jsonb,
    p_actor text,
    p_approval_reference text,
    p_reason text
) RETURNS TABLE(cutover_unit text,state text,state_revision bigint)
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog, operations, audit
AS $$
    SELECT * FROM operations.transition_cutover_unit(
        'shared_identity',p_expected_state,p_expected_revision,p_to_state,
        CASE WHEN p_to_state IN ('S0','S1') THEN 'sqlite_transition'
             WHEN p_to_state IN ('S2','S3','S4') THEN 'postgresql_production'
             ELSE NULL END,
        p_writer_identity,p_cutover_epoch,p_sqlite_final_watermark,
        p_actor,p_approval_reference,p_reason
    );
$$;

-- Snapshot activation is the first formal shared-identity publication.  It
-- changes the reconciled target from disposable S1 material into the sole
-- business read authority and advances S2->S3 atomically.  It does not invent
-- or alter an identity row.
CREATE OR REPLACE FUNCTION shared_identity.activate_snapshot_v1(
    p_expected_source_snapshot_id text,
    p_expected_authority_revision bigint,
    p_idempotency_key text,
    p_request_sha256 text,
    p_writer_identity text,
    p_actor text
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, shared_identity, operations, audit
AS $$
DECLARE
    v_existing shared_identity.mutation_result%ROWTYPE;
    v_authority operations.cutover_unit_authority%ROWTYPE;
    v_snapshot shared_identity.unit_snapshot%ROWTYPE;
    v_result jsonb;
    v_count bigint;
BEGIN
    IF p_request_sha256 !~ '^[0-9a-f]{64}$'
       OR nullif(btrim(p_idempotency_key),'') IS NULL
       OR nullif(btrim(p_actor),'') IS NULL THEN
        RAISE EXCEPTION 'activation mutation identity is incomplete'
            USING ERRCODE='22023';
    END IF;
    SELECT * INTO v_existing FROM shared_identity.mutation_result
     WHERE operation_scope='shared_identity.activate_snapshot_v1'
       AND idempotency_key=p_idempotency_key;
    IF FOUND THEN
        IF v_existing.request_sha256 <> p_request_sha256 THEN
            RAISE EXCEPTION 'activation idempotency conflict' USING ERRCODE='23505';
        END IF;
        RETURN v_existing.result_payload;
    END IF;
    SELECT * INTO v_authority FROM operations.cutover_unit_authority
     WHERE cutover_unit='shared_identity' FOR UPDATE;
    IF NOT FOUND OR v_authority.state <> 'S2'
       OR v_authority.authoritative_backend <> 'postgresql_production'
       OR v_authority.writer_identity <> p_writer_identity
       OR v_authority.state_revision <> p_expected_authority_revision THEN
        RAISE EXCEPTION 'shared identity activation is fenced or stale'
            USING ERRCODE='42501';
    END IF;
    SELECT * INTO v_snapshot FROM shared_identity.unit_snapshot
     WHERE cutover_unit='shared_identity' FOR UPDATE;
    IF NOT FOUND OR v_snapshot.source_snapshot_id <> p_expected_source_snapshot_id
       OR v_snapshot.authority_state <> 'S1'
       OR v_snapshot.formal_business_data THEN
        RAISE EXCEPTION 'shared identity S1 snapshot is missing or stale'
            USING ERRCODE='40001';
    END IF;
    UPDATE shared_identity.legacy_record
       SET formal_business_data=true
     WHERE source_snapshot_id=p_expected_source_snapshot_id;
    GET DIAGNOSTICS v_count=ROW_COUNT;
    IF v_count <> v_snapshot.target_row_count THEN
        RAISE EXCEPTION 'shared identity activation row count changed'
            USING ERRCODE='40001';
    END IF;
    PERFORM operations.promote_cutover_unit_on_first_formal_mutation(
        'shared_identity','shared_identity.activate_snapshot_v1',
        p_idempotency_key,p_expected_source_snapshot_id,p_writer_identity,
        p_actor,'activate reconciled shared identity snapshot as formal authority'
    );
    UPDATE shared_identity.unit_snapshot SET
        authority_state='S3',formal_business_data=true,
        formal_revision=formal_revision+1,
        current_formal_row_count=v_count,
        activated_at=clock_timestamp()
     WHERE cutover_unit='shared_identity';
    v_result=jsonb_build_object(
        'cutover_unit','shared_identity','authority_state','S3',
        'source_snapshot_id',p_expected_source_snapshot_id,
        'formal_row_count',v_count
    );
    INSERT INTO shared_identity.mutation_result(
        operation_scope,idempotency_key,request_sha256,object_key,result_payload
    ) VALUES (
        'shared_identity.activate_snapshot_v1',p_idempotency_key,
        p_request_sha256,p_expected_source_snapshot_id,v_result
    );
    RETURN v_result;
END;
$$;

REVOKE ALL ON FUNCTION operations.promote_cutover_unit_on_first_formal_mutation(
    text,text,text,text,text,text,text
) FROM PUBLIC;
REVOKE ALL ON FUNCTION operations.transition_shared_identity(
    text,bigint,text,text,text,jsonb,text,text,text
) FROM PUBLIC;
REVOKE ALL ON FUNCTION shared_identity.activate_snapshot_v1(
    text,bigint,text,text,text,text
) FROM PUBLIC;
REVOKE ALL ON shared_identity.mutation_result FROM PUBLIC;
REVOKE ALL ON operations.shared_identity_authority_v1 FROM PUBLIC;

INSERT INTO operations.schema_migration(
    migration_id,migration_sha256,phase,forward_only
) VALUES (
    '0006_shared_identity_cutover_expand',:'migration_sha256','expand',false
) ON CONFLICT (migration_id) DO NOTHING;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM operations.schema_migration
         WHERE migration_id='0006_shared_identity_cutover_expand'
           AND migration_sha256=current_setting('honghu.migration_sha256')
    ) THEN
        RAISE EXCEPTION 'migration identity exists with a different SHA256';
    END IF;
END $$;

COMMIT;
