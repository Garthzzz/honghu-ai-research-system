\set ON_ERROR_STOP on
BEGIN;
SELECT set_config('honghu.migration_sha256', :'migration_sha256', true);

DO $$
BEGIN
 IF EXISTS(
   SELECT 1 FROM valuation_tracker.market_snapshot
    WHERE raw_field='mkt_cap_ard'
      AND source_ref NOT LIKE 'Wind WSQ.rt_mkt_cap+rt_susp_flag:%'
 ) THEN
   RAISE EXCEPTION 'legacy market snapshot provenance cannot be corrected safely';
 END IF;
END $$;

INSERT INTO valuation_tracker.mutation_audit(
 operation_scope,idempotency_key,request_sha256,object_type,object_key,
 action,before_payload,after_payload,actor
)
SELECT
 'migration_0023_correct_market_provenance',
 'snapshot:'||snapshot_id::text,
 encode(sha256(convert_to(jsonb_build_object(
   'snapshot_id',snapshot_id,'before','mkt_cap_ard','after','rt_mkt_cap',
   'source_ref',source_ref
 )::text,'UTF8')),'hex'),
 'market_snapshot',snapshot_id::text,'correct_provenance',
 jsonb_build_object('raw_field','mkt_cap_ard','source_ref',source_ref),
 jsonb_build_object('raw_field','rt_mkt_cap','source_ref',source_ref),
 'migration:0023_valuation_market_realtime_provenance'
FROM valuation_tracker.market_snapshot
WHERE raw_field='mkt_cap_ard'
ON CONFLICT(operation_scope,idempotency_key,object_type,object_key) DO NOTHING;

ALTER TABLE valuation_tracker.market_snapshot
 DROP CONSTRAINT market_snapshot_raw_field_check;
UPDATE valuation_tracker.market_snapshot
 SET raw_field='rt_mkt_cap'
 WHERE raw_field='mkt_cap_ard';
ALTER TABLE valuation_tracker.market_snapshot
 ADD CONSTRAINT market_snapshot_raw_field_check CHECK(raw_field='rt_mkt_cap');

CREATE OR REPLACE FUNCTION valuation_tracker.record_market_batch_v1(
 p_trade_date date,p_slot text,p_observed_at timestamptz,p_calendar_provider text,p_calendar_evidence jsonb,p_items jsonb,
 p_idempotency_key text,p_writer_identity text,p_authority_state text,p_cutover_epoch text,p_approval_reference text,p_state_revision bigint,p_actor text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,valuation_tracker,operations AS $$
DECLARE v_request text; v_old valuation_tracker.mutation_result%ROWTYPE; v_item jsonb; v_member valuation_tracker.member%ROWTYPE; v_count int; v_result jsonb;
BEGIN
 IF p_slot NOT IN ('1140','1510') OR jsonb_typeof(p_calendar_evidence) IS DISTINCT FROM 'object' OR jsonb_typeof(p_items) IS DISTINCT FROM 'array' OR jsonb_array_length(p_items) IS DISTINCT FROM 6
    OR (p_observed_at AT TIME ZONE 'Asia/Shanghai')::date IS DISTINCT FROM p_trade_date
    OR (p_observed_at AT TIME ZONE 'Asia/Shanghai')::time
       < (CASE WHEN p_slot='1140' THEN '11:40' ELSE '15:10' END)::time
    OR p_calendar_provider IS DISTINCT FROM 'Wind.tdays:SSE+SZSE'
    OR p_calendar_evidence->'is_trading_day' IS DISTINCT FROM 'true'::jsonb
    OR p_calendar_evidence->>'slot' IS DISTINCT FROM p_slot
    OR p_calendar_evidence->>'trigger_time' IS DISTINCT FROM
       (CASE WHEN p_slot='1140' THEN '11:40' ELSE '15:10' END)
    OR coalesce((p_calendar_evidence->>'late_seconds')::bigint,-1)<0
    OR nullif(btrim(p_idempotency_key),'') IS NULL OR nullif(btrim(p_actor),'') IS NULL THEN
   RAISE EXCEPTION 'market batch contract is invalid' USING ERRCODE='22023';
 END IF;
 SELECT count(DISTINCT (x->>'security_id')::bigint) INTO v_count FROM jsonb_array_elements(p_items) x;
 IF v_count IS DISTINCT FROM 6 THEN
   RAISE EXCEPTION 'market batch security set is not unique' USING ERRCODE='22023';
 END IF;
 IF (SELECT array_agg((x->>'security_id')::bigint ORDER BY (x->>'security_id')::bigint) FROM jsonb_array_elements(p_items)x)
       IS DISTINCT FROM
    (SELECT array_agg(security_id ORDER BY security_id) FROM valuation_tracker.member WHERE enabled AND market IN ('上海','深圳')) THEN
   RAISE EXCEPTION 'market batch security set differs from A-share watchlist' USING ERRCODE='23503';
 END IF;
 v_request:=encode(sha256(convert_to(jsonb_build_object(
   'actor',p_actor,'date',p_trade_date,'slot',p_slot,'observed_at',p_observed_at,
   'calendar',p_calendar_evidence,'items',p_items
 )::text,'UTF8')),'hex');
 PERFORM pg_advisory_xact_lock(hashtextextended('valuation_tracker.market:'||p_trade_date::text||':'||p_slot,0));
 PERFORM valuation_tracker.assert_writer_v1(
   p_writer_identity,p_authority_state,p_cutover_epoch,p_approval_reference,p_state_revision
 );
 SELECT * INTO v_old FROM valuation_tracker.mutation_result
  WHERE operation_scope='record_market_batch_v1' AND idempotency_key=p_idempotency_key;
 IF FOUND THEN
   IF v_old.request_sha256 IS DISTINCT FROM v_request THEN
     RAISE EXCEPTION 'market batch idempotency conflict' USING ERRCODE='23505';
   END IF;
   RETURN v_old.result_payload;
 END IF;
 FOR v_item IN SELECT value FROM jsonb_array_elements(p_items) LOOP
   SELECT * INTO v_member FROM valuation_tracker.member
    WHERE security_id=(v_item->>'security_id')::bigint AND enabled;
   IF NOT FOUND
      OR v_member.canonical_ticker IS DISTINCT FROM upper(v_item->>'ticker')
      OR (v_item->>'market_cap_value')::numeric<=0
      OR v_item->>'currency' IS DISTINCT FROM 'CNY'
      OR v_item->>'unit' IS DISTINCT FROM '亿元'
      OR v_item->>'raw_field' IS DISTINCT FROM 'rt_mkt_cap'
      OR nullif(btrim(v_item->>'source_ref'),'') IS NULL
      OR v_item->>'source_ref' NOT LIKE 'Wind WSQ.rt_mkt_cap+rt_susp_flag:%'
      OR (v_item->>'raw_sha256') !~ '^[0-9a-f]{64}$' THEN
     RAISE EXCEPTION 'market observation identity, value, or provenance is invalid' USING ERRCODE='22023';
   END IF;
   IF nullif(v_item->>'trading_status','') IS NULL
      OR v_item->>'trading_status' NOT IN ('trading','suspended') THEN
     RAISE EXCEPTION 'market trading status is invalid' USING ERRCODE='22023';
   END IF;
   INSERT INTO valuation_tracker.market_snapshot(
     member_id,security_id,trade_date,slot,observed_at,provider,raw_field,
     trading_status,market_cap_value,currency,amount_unit,source_ref,raw_sha256,request_sha256
   ) VALUES(
     v_member.member_id,v_member.security_id,p_trade_date,p_slot,p_observed_at,
     'Wind',v_item->>'raw_field',v_item->>'trading_status',
     (v_item->>'market_cap_value')::numeric,'CNY','亿元',
     v_item->>'source_ref',v_item->>'raw_sha256',v_request
   );
 END LOOP;
 INSERT INTO valuation_tracker.market_run
 VALUES(p_trade_date,p_slot,'completed',p_calendar_provider,p_calendar_evidence,6,v_request,p_actor,clock_timestamp());
 v_result:=jsonb_build_object(
   'trade_date',p_trade_date,'slot',p_slot,'observed_count',6,'status','completed'
 );
 INSERT INTO valuation_tracker.mutation_result
 VALUES('record_market_batch_v1',p_idempotency_key,v_request,v_result,clock_timestamp());
 INSERT INTO valuation_tracker.mutation_audit(
   operation_scope,idempotency_key,request_sha256,object_type,object_key,action,after_payload,actor
 ) VALUES(
   'record_market_batch_v1',p_idempotency_key,v_request,'market_batch',
   p_trade_date::text||':'||p_slot,'create',v_result,p_actor
 );
 RETURN v_result;
END; $$;

REVOKE ALL ON FUNCTION valuation_tracker.record_market_batch_v1(
 date,text,timestamptz,text,jsonb,jsonb,text,text,text,text,text,bigint,text
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION valuation_tracker.record_market_batch_v1(
 date,text,timestamptz,text,jsonb,jsonb,text,text,text,text,text,bigint,text
) TO :"writer_role";

INSERT INTO operations.schema_migration(migration_id,migration_sha256,phase,forward_only)
VALUES('0023_valuation_market_realtime_provenance',:'migration_sha256','expand',false)
ON CONFLICT(migration_id) DO NOTHING;
DO $$ BEGIN
 IF NOT EXISTS(
   SELECT 1 FROM operations.schema_migration
   WHERE migration_id='0023_valuation_market_realtime_provenance'
     AND migration_sha256=current_setting('honghu.migration_sha256')
 ) THEN RAISE EXCEPTION 'migration identity exists with different SHA256'; END IF;
END $$;
COMMIT;
