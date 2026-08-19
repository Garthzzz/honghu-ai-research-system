\set ON_ERROR_STOP on
BEGIN;

CREATE TABLE IF NOT EXISTS valuation_tracker.ai_refresh_run(
    valuation_month date PRIMARY KEY,
    valuation_date date NOT NULL,
    status text NOT NULL CHECK(status IN ('no_candidate')),
    evaluated_count integer NOT NULL CHECK(evaluated_count > 0),
    candidate_count integer NOT NULL CHECK(candidate_count = 0),
    skipped jsonb NOT NULL CHECK(jsonb_typeof(skipped) = 'array'),
    prompt_sha256 text NOT NULL CHECK(prompt_sha256 ~ '^[0-9a-f]{64}$'),
    model_name text NOT NULL,
    request_sha256 text NOT NULL CHECK(request_sha256 ~ '^[0-9a-f]{64}$'),
    actor text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK(valuation_month = date_trunc('month', valuation_date)::date)
);

CREATE OR REPLACE FUNCTION valuation_tracker.record_ai_no_candidates_v1(
 p_valuation_date date,p_skipped jsonb,p_prompt_sha256 text,p_model_name text,
 p_idempotency_key text,p_writer_identity text,p_authority_state text,p_cutover_epoch text,
 p_approval_reference text,p_state_revision bigint,p_actor text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,valuation_tracker,operations AS $$
DECLARE v_request text; v_old valuation_tracker.mutation_result%ROWTYPE;
        v_result jsonb; v_month date; v_enabled_count int;
BEGIN
 v_month:=date_trunc('month',p_valuation_date)::date;
 SELECT count(*) INTO v_enabled_count FROM valuation_tracker.member WHERE enabled;
 IF jsonb_typeof(p_skipped) IS DISTINCT FROM 'array'
    OR jsonb_array_length(p_skipped) IS DISTINCT FROM v_enabled_count
    OR v_enabled_count<=0 OR p_prompt_sha256 !~ '^[0-9a-f]{64}$'
    OR nullif(btrim(p_model_name),'') IS NULL
    OR nullif(btrim(p_idempotency_key),'') IS NULL
    OR nullif(btrim(p_actor),'') IS NULL THEN
   RAISE EXCEPTION 'AI no-candidate run contract is invalid' USING ERRCODE='22023';
 END IF;
 IF (SELECT count(DISTINCT (x->>'member_id')::bigint) FROM jsonb_array_elements(p_skipped)x)
       IS DISTINCT FROM v_enabled_count
    OR (SELECT array_agg((x->>'member_id')::bigint ORDER BY (x->>'member_id')::bigint)
          FROM jsonb_array_elements(p_skipped)x)
       IS DISTINCT FROM
       (SELECT array_agg(member_id ORDER BY member_id) FROM valuation_tracker.member WHERE enabled)
    OR EXISTS(
       SELECT 1 FROM jsonb_array_elements(p_skipped)x
       LEFT JOIN valuation_tracker.member m
         ON m.member_id=(x->>'member_id')::bigint AND m.enabled
       WHERE m.member_id IS NULL
          OR m.company_id IS DISTINCT FROM (x->>'company_id')::bigint
          OR m.security_id IS DISTINCT FROM (x->>'security_id')::bigint
          OR nullif(btrim(x->>'reason'),'') IS NULL
          OR EXISTS(SELECT 1 FROM jsonb_object_keys(x)k
                    WHERE k NOT IN ('member_id','company_id','security_id','reason'))
    ) THEN
   RAISE EXCEPTION 'AI no-candidate member set is invalid' USING ERRCODE='23503';
 END IF;
 v_request:=encode(sha256(convert_to(jsonb_build_object(
   'actor',p_actor,'date',p_valuation_date,'skipped',p_skipped,
   'prompt_sha256',p_prompt_sha256,'model_name',p_model_name
 )::text,'UTF8')),'hex');
 PERFORM pg_advisory_xact_lock(hashtextextended('valuation_tracker.ai:'||p_idempotency_key,0));
 PERFORM valuation_tracker.assert_writer_v1(
   p_writer_identity,p_authority_state,p_cutover_epoch,p_approval_reference,p_state_revision
 );
 SELECT * INTO v_old FROM valuation_tracker.mutation_result
  WHERE operation_scope='record_ai_no_candidates_v1'
    AND idempotency_key=p_idempotency_key;
 IF FOUND THEN
   IF v_old.request_sha256 IS DISTINCT FROM v_request THEN
     RAISE EXCEPTION 'AI no-candidate idempotency conflict' USING ERRCODE='23505';
   END IF;
   RETURN v_old.result_payload;
 END IF;
 INSERT INTO valuation_tracker.ai_refresh_run(
   valuation_month,valuation_date,status,evaluated_count,candidate_count,skipped,
   prompt_sha256,model_name,request_sha256,actor
 ) VALUES(
   v_month,p_valuation_date,'no_candidate',v_enabled_count,0,p_skipped,
   p_prompt_sha256,p_model_name,v_request,p_actor
 );
 v_result:=jsonb_build_object(
   'valuation_date',p_valuation_date,'evaluated_count',v_enabled_count,
   'candidate_count',0,'status','no_candidate','human_values_overwritten',false
 );
 INSERT INTO valuation_tracker.mutation_result
 VALUES('record_ai_no_candidates_v1',p_idempotency_key,v_request,v_result,clock_timestamp());
 INSERT INTO valuation_tracker.mutation_audit(
   operation_scope,idempotency_key,request_sha256,object_type,object_key,
   action,after_payload,actor
 ) VALUES(
   'record_ai_no_candidates_v1',p_idempotency_key,v_request,'ai_refresh_run',
   v_month::text,'record_no_candidate',jsonb_build_object('result',v_result,'skipped',p_skipped),p_actor
 );
 RETURN v_result;
END; $$;

REVOKE ALL ON valuation_tracker.ai_refresh_run FROM PUBLIC;
REVOKE ALL ON FUNCTION valuation_tracker.record_ai_no_candidates_v1(
 date,jsonb,text,text,text,text,text,text,text,bigint,text
) FROM PUBLIC;
GRANT SELECT ON valuation_tracker.ai_refresh_run TO :"reader_role",:"writer_role",:"audit_reader_role";
GRANT EXECUTE ON FUNCTION valuation_tracker.record_ai_no_candidates_v1(
 date,jsonb,text,text,text,text,text,text,text,bigint,text
) TO :"writer_role";

INSERT INTO operations.schema_migration(migration_id,migration_sha256,phase,forward_only)
VALUES('0022_valuation_ai_no_candidate_run',:'migration_sha256','expand',false)
ON CONFLICT(migration_id) DO NOTHING;
DO $$ BEGIN
 IF NOT EXISTS(
   SELECT 1 FROM operations.schema_migration
   WHERE migration_id='0022_valuation_ai_no_candidate_run'
     AND migration_sha256=current_setting('honghu.migration_sha256')
 ) THEN RAISE EXCEPTION 'migration identity exists with different SHA256'; END IF;
END $$;
COMMIT;
