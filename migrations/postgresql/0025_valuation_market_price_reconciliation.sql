\set ON_ERROR_STOP on
BEGIN;
SELECT set_config('honghu.migration_sha256', :'migration_sha256', true);

ALTER TABLE valuation_tracker.market_snapshot
  ADD COLUMN share_price_observed_at timestamptz,
  ADD COLUMN share_price_source_ref text,
  ADD COLUMN share_price_raw_sha256 text;

UPDATE valuation_tracker.market_snapshot
   SET share_price_observed_at=observed_at,
       share_price_source_ref=source_ref,
       share_price_raw_sha256=raw_sha256
 WHERE share_price_value IS NOT NULL;

ALTER TABLE valuation_tracker.market_snapshot
  ADD CONSTRAINT market_snapshot_price_provenance_check CHECK(
    (share_price_value IS NULL AND share_price_observed_at IS NULL
      AND share_price_source_ref IS NULL AND share_price_raw_sha256 IS NULL)
    OR (share_price_value IS NOT NULL AND share_price_observed_at IS NOT NULL
      AND nullif(btrim(share_price_source_ref),'') IS NOT NULL
      AND share_price_source_ref LIKE 'Wind WSQ.rt_last+rt_mkt_cap+rt_susp_flag:%'
      AND share_price_raw_sha256 ~ '^[0-9a-f]{64}$')
  );

CREATE OR REPLACE FUNCTION valuation_tracker.fill_market_price_provenance_v1()
RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,valuation_tracker AS $$
BEGIN
 IF NEW.share_price_value IS NOT NULL THEN
   NEW.share_price_observed_at:=coalesce(NEW.share_price_observed_at,NEW.observed_at);
   NEW.share_price_source_ref:=coalesce(NEW.share_price_source_ref,NEW.source_ref);
   NEW.share_price_raw_sha256:=coalesce(NEW.share_price_raw_sha256,NEW.raw_sha256);
 END IF;
 RETURN NEW;
END; $$;
REVOKE ALL ON FUNCTION valuation_tracker.fill_market_price_provenance_v1() FROM PUBLIC;
CREATE TRIGGER valuation_market_price_provenance_insert
BEFORE INSERT ON valuation_tracker.market_snapshot
FOR EACH ROW EXECUTE FUNCTION valuation_tracker.fill_market_price_provenance_v1();

CREATE OR REPLACE FUNCTION valuation_tracker.backfill_market_price_v1(
 p_trade_date date,p_slot text,p_reconciled_at timestamptz,p_items jsonb,
 p_idempotency_key text,p_writer_identity text,p_authority_state text,
 p_cutover_epoch text,p_approval_reference text,p_state_revision bigint,p_actor text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,valuation_tracker,operations AS $$
DECLARE v_request text; v_old valuation_tracker.mutation_result%ROWTYPE;
 v_item jsonb; v_member valuation_tracker.member%ROWTYPE;
 v_snapshot valuation_tracker.market_snapshot%ROWTYPE; v_count int:=0; v_result jsonb;
BEGIN
 IF p_slot IS DISTINCT FROM '1510'
    OR jsonb_typeof(p_items) IS DISTINCT FROM 'array'
    OR jsonb_array_length(p_items) IS DISTINCT FROM 6
    OR (p_reconciled_at AT TIME ZONE 'Asia/Shanghai')::date IS DISTINCT FROM p_trade_date
    OR (p_reconciled_at AT TIME ZONE 'Asia/Shanghai')::time < '15:10'::time
    OR nullif(btrim(p_idempotency_key),'') IS NULL
    OR nullif(btrim(p_actor),'') IS NULL THEN
   RAISE EXCEPTION 'market price reconciliation contract is invalid' USING ERRCODE='22023';
 END IF;
 IF (SELECT count(DISTINCT (x->>'security_id')::bigint)
       FROM jsonb_array_elements(p_items)x) IS DISTINCT FROM 6
    OR (SELECT array_agg((x->>'security_id')::bigint ORDER BY (x->>'security_id')::bigint)
          FROM jsonb_array_elements(p_items)x) IS DISTINCT FROM
       (SELECT array_agg(security_id ORDER BY security_id)
          FROM valuation_tracker.member
         WHERE enabled AND market IN ('上海','深圳')) THEN
   RAISE EXCEPTION 'market price reconciliation security set differs' USING ERRCODE='23503';
 END IF;
 v_request:=encode(sha256(convert_to(jsonb_build_object(
   'actor',p_actor,'date',p_trade_date,'slot',p_slot,
   'reconciled_at',p_reconciled_at,'items',p_items
 )::text,'UTF8')),'hex');
 PERFORM pg_advisory_xact_lock(hashtextextended(
   'valuation_tracker.price_reconcile:'||p_trade_date::text||':'||p_slot,0));
 PERFORM valuation_tracker.assert_writer_v1(
   p_writer_identity,p_authority_state,p_cutover_epoch,p_approval_reference,p_state_revision
 );
 SELECT * INTO v_old FROM valuation_tracker.mutation_result
  WHERE operation_scope='backfill_market_price_v1' AND idempotency_key=p_idempotency_key;
 IF FOUND THEN
   IF v_old.request_sha256 IS DISTINCT FROM v_request THEN
     RAISE EXCEPTION 'market price reconciliation idempotency conflict' USING ERRCODE='23505';
   END IF;
   RETURN v_old.result_payload;
 END IF;
 FOR v_item IN SELECT value FROM jsonb_array_elements(p_items) LOOP
   SELECT * INTO v_member FROM valuation_tracker.member
    WHERE security_id=(v_item->>'security_id')::bigint
      AND enabled AND market IN ('上海','深圳');
   IF NOT FOUND OR v_member.canonical_ticker IS DISTINCT FROM upper(v_item->>'ticker')
      OR (v_item->>'share_price_value')::numeric<=0
      OR v_item->>'share_price_currency' IS DISTINCT FROM 'CNY'
      OR v_item->>'share_price_unit' IS DISTINCT FROM '元'
      OR v_item->>'share_price_raw_field' IS DISTINCT FROM 'rt_last'
      OR nullif(btrim(v_item->>'share_price_source_ref'),'') IS NULL
      OR v_item->>'share_price_source_ref' NOT LIKE 'Wind WSQ.rt_last+rt_mkt_cap+rt_susp_flag:%'
      OR (v_item->>'share_price_raw_sha256') !~ '^[0-9a-f]{64}$' THEN
     RAISE EXCEPTION 'market price reconciliation item is invalid' USING ERRCODE='22023';
   END IF;
   SELECT * INTO v_snapshot FROM valuation_tracker.market_snapshot
    WHERE security_id=v_member.security_id AND trade_date=p_trade_date
      AND slot=p_slot AND provider='Wind' FOR UPDATE;
   IF NOT FOUND OR v_snapshot.member_id IS DISTINCT FROM v_member.member_id
      OR v_snapshot.share_price_value IS NOT NULL
      OR v_snapshot.share_price_currency IS NOT NULL
      OR v_snapshot.share_price_unit IS NOT NULL
      OR v_snapshot.share_price_raw_field IS NOT NULL
      OR v_snapshot.share_price_observed_at IS NOT NULL
      OR v_snapshot.share_price_source_ref IS NOT NULL
      OR v_snapshot.share_price_raw_sha256 IS NOT NULL THEN
     RAISE EXCEPTION 'market snapshot is absent, ambiguous, or already priced' USING ERRCODE='23505';
   END IF;
   UPDATE valuation_tracker.market_snapshot SET
      share_price_value=(v_item->>'share_price_value')::numeric,
      share_price_currency='CNY',share_price_unit='元',share_price_raw_field='rt_last',
      share_price_observed_at=p_reconciled_at,
      share_price_source_ref=v_item->>'share_price_source_ref',
      share_price_raw_sha256=v_item->>'share_price_raw_sha256'
    WHERE snapshot_id=v_snapshot.snapshot_id;
   INSERT INTO valuation_tracker.mutation_audit(
     operation_scope,idempotency_key,request_sha256,object_type,object_key,action,
     before_payload,after_payload,actor
   ) VALUES('backfill_market_price_v1',p_idempotency_key,v_request,'market_snapshot',
     v_snapshot.snapshot_id::text,'fill_missing_share_price',to_jsonb(v_snapshot),
     jsonb_build_object('share_price_value',(v_item->>'share_price_value')::numeric,
       'share_price_currency','CNY','share_price_unit','元','share_price_raw_field','rt_last',
       'share_price_observed_at',p_reconciled_at,
       'share_price_source_ref',v_item->>'share_price_source_ref',
       'share_price_raw_sha256',v_item->>'share_price_raw_sha256'),p_actor);
   v_count:=v_count+1;
 END LOOP;
 v_result:=jsonb_build_object('trade_date',p_trade_date,'slot',p_slot,
   'reconciled_count',v_count,'status','completed','fields_overwritten',false);
 INSERT INTO valuation_tracker.mutation_result VALUES(
   'backfill_market_price_v1',p_idempotency_key,v_request,v_result,clock_timestamp());
 RETURN v_result;
END; $$;

CREATE OR REPLACE FUNCTION valuation_tracker.replay_task_result_v1(
 p_operation_scope text,p_idempotency_key text,p_writer_identity text,
 p_authority_state text,p_cutover_epoch text,p_approval_reference text,
 p_state_revision bigint
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,valuation_tracker,operations AS $$
DECLARE v_result jsonb;
BEGIN
 IF p_operation_scope NOT IN (
      'record_market_batch_v2','record_market_skip_v2','record_ai_candidates_v2',
      'record_ai_candidates_v1','backfill_market_price_v1'
    ) OR nullif(btrim(p_idempotency_key),'') IS NULL THEN
   RAISE EXCEPTION 'scheduled replay identity is invalid' USING ERRCODE='22023';
 END IF;
 PERFORM valuation_tracker.assert_writer_v1(
   p_writer_identity,p_authority_state,p_cutover_epoch,p_approval_reference,p_state_revision
 );
 SELECT result_payload INTO v_result FROM valuation_tracker.mutation_result
  WHERE operation_scope=p_operation_scope AND idempotency_key=p_idempotency_key;
 RETURN v_result;
END; $$;

REVOKE ALL ON FUNCTION valuation_tracker.backfill_market_price_v1(
 date,text,timestamptz,jsonb,text,text,text,text,text,bigint,text
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION valuation_tracker.backfill_market_price_v1(
 date,text,timestamptz,jsonb,text,text,text,text,text,bigint,text
) TO :"writer_role";

INSERT INTO operations.schema_migration(migration_id,migration_sha256,phase,forward_only)
VALUES('0025_valuation_market_price_reconciliation',:'migration_sha256','expand',false)
ON CONFLICT(migration_id) DO NOTHING;
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM operations.schema_migration
   WHERE migration_id='0025_valuation_market_price_reconciliation'
     AND migration_sha256=current_setting('honghu.migration_sha256')) THEN
   RAISE EXCEPTION 'migration identity exists with different SHA256';
 END IF;
END $$;
COMMIT;
