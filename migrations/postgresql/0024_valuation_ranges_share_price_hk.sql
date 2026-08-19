\set ON_ERROR_STOP on
BEGIN;
SELECT set_config('honghu.migration_sha256', :'migration_sha256', true);

ALTER TABLE valuation_tracker.valuation_version
  ADD COLUMN lower_value numeric(28,8),
  ADD COLUMN base_value numeric(28,8),
  ADD COLUMN upper_value numeric(28,8);

UPDATE valuation_tracker.valuation_version
   SET lower_value=ceiling_value,base_value=ceiling_value,upper_value=ceiling_value;

-- Keep the reviewed v1 workbook importer compatible for clean-environment
-- bootstrap. New application writes use v2 and always submit an explicit
-- range; legacy inserts are represented honestly as a one-point range.
CREATE OR REPLACE FUNCTION valuation_tracker.fill_legacy_valuation_range_v1()
RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,valuation_tracker AS $$
BEGIN
 NEW.lower_value:=coalesce(NEW.lower_value,NEW.ceiling_value);
 NEW.base_value:=coalesce(NEW.base_value,NEW.ceiling_value);
 NEW.upper_value:=coalesce(NEW.upper_value,NEW.ceiling_value);
 NEW.ceiling_value:=NEW.upper_value;
 RETURN NEW;
END; $$;
CREATE TRIGGER fill_legacy_valuation_range_v1
BEFORE INSERT OR UPDATE ON valuation_tracker.valuation_version
FOR EACH ROW EXECUTE FUNCTION valuation_tracker.fill_legacy_valuation_range_v1();

ALTER TABLE valuation_tracker.valuation_version
  ALTER COLUMN lower_value SET NOT NULL,
  ALTER COLUMN base_value SET NOT NULL,
  ALTER COLUMN upper_value SET NOT NULL,
  ADD CONSTRAINT valuation_version_range_check CHECK(
    lower_value>0 AND lower_value<=base_value AND base_value<=upper_value
    AND ceiling_value=upper_value
  );

ALTER TABLE valuation_tracker.market_run DROP CONSTRAINT market_run_slot_check;
ALTER TABLE valuation_tracker.market_run
  ADD CONSTRAINT market_run_slot_check CHECK(slot IN ('1140','1510','1610'));
ALTER TABLE valuation_tracker.market_snapshot DROP CONSTRAINT market_snapshot_slot_check;
ALTER TABLE valuation_tracker.market_snapshot
  ADD CONSTRAINT market_snapshot_slot_check CHECK(slot IN ('1140','1510','1610')),
  ADD COLUMN share_price_value numeric(28,8),
  ADD COLUMN share_price_currency text,
  ADD COLUMN share_price_unit text,
  ADD COLUMN share_price_raw_field text;
ALTER TABLE valuation_tracker.market_snapshot
  ADD CONSTRAINT market_snapshot_price_check CHECK(
    (share_price_value IS NULL AND share_price_currency IS NULL
      AND share_price_unit IS NULL AND share_price_raw_field IS NULL)
    OR (share_price_value>0 AND share_price_currency IN ('CNY','HKD')
      AND share_price_unit='元' AND share_price_raw_field='rt_last')
  );
ALTER TABLE valuation_tracker.market_snapshot DROP CONSTRAINT market_snapshot_currency_check;
ALTER TABLE valuation_tracker.market_snapshot
  ADD CONSTRAINT market_snapshot_currency_check CHECK(currency IN ('CNY','HKD'));

CREATE OR REPLACE FUNCTION valuation_tracker.edit_valuation_v2(
 p_member_id bigint,p_kind text,p_payload jsonb,p_expected_member_revision bigint,
 p_idempotency_key text,p_writer_identity text,p_authority_state text,p_cutover_epoch text,
 p_approval_reference text,p_state_revision bigint,p_actor text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,valuation_tracker,operations AS $$
DECLARE v_member valuation_tracker.member%ROWTYPE; v_old valuation_tracker.mutation_result%ROWTYPE;
 v_request text; v_version bigint; v_previous bigint; v_result jsonb;
 v_low numeric; v_base numeric; v_high numeric;
BEGIN
 v_low:=(p_payload->>'lower_value')::numeric;
 v_base:=(p_payload->>'base_value')::numeric;
 v_high:=(p_payload->>'upper_value')::numeric;
 IF p_kind NOT IN ('researcher','ai') OR jsonb_typeof(p_payload) IS DISTINCT FROM 'object'
    OR v_low<=0 OR v_low>v_base OR v_base>v_high
    OR (p_payload->>'currency') NOT IN ('CNY','HKD')
    OR nullif(btrim(p_payload->>'method_summary'),'') IS NULL
    OR nullif(btrim(p_payload->>'change_reason'),'') IS NULL
    OR jsonb_typeof(p_payload->'sources') IS DISTINCT FROM 'array'
    OR jsonb_array_length(p_payload->'sources')=0
    OR jsonb_typeof(p_payload->'valuation_methods') IS DISTINCT FROM 'array'
    OR jsonb_array_length(p_payload->'valuation_methods')=0
    OR EXISTS(SELECT 1 FROM jsonb_array_elements(p_payload->'sources') x
       WHERE nullif(btrim(x->>'title'),'') IS NULL OR nullif(btrim(x->>'source_type'),'') IS NULL)
    OR EXISTS(SELECT 1 FROM jsonb_array_elements(p_payload->'valuation_methods') x
       WHERE nullif(btrim(coalesce(x->>'name',x->>'method')),'') IS NULL)
    OR nullif(btrim(p_idempotency_key),'') IS NULL OR nullif(btrim(p_actor),'') IS NULL THEN
   RAISE EXCEPTION 'valuation range edit is invalid' USING ERRCODE='22023';
 END IF;
 v_request:=encode(sha256(convert_to(jsonb_build_object(
   'actor',p_actor,'member_id',p_member_id,'kind',p_kind,'payload',p_payload,
   'expected_revision',p_expected_member_revision
 )::text,'UTF8')),'hex');
 PERFORM pg_advisory_xact_lock(hashtextextended('valuation_tracker.edit.v2:'||p_idempotency_key,0));
 PERFORM valuation_tracker.assert_writer_v1(
   p_writer_identity,p_authority_state,p_cutover_epoch,p_approval_reference,p_state_revision
 );
 SELECT * INTO v_old FROM valuation_tracker.mutation_result
  WHERE operation_scope='edit_valuation_v2' AND idempotency_key=p_idempotency_key;
 IF FOUND THEN
   IF v_old.request_sha256 IS DISTINCT FROM v_request THEN
     RAISE EXCEPTION 'valuation range edit idempotency conflict' USING ERRCODE='23505';
   END IF;
   RETURN v_old.result_payload;
 END IF;
 SELECT * INTO v_member FROM valuation_tracker.member
  WHERE member_id=p_member_id AND enabled FOR UPDATE;
 IF NOT FOUND OR v_member.revision IS DISTINCT FROM p_expected_member_revision THEN
   RAISE EXCEPTION 'stale valuation member revision' USING ERRCODE='40001';
 END IF;
 IF (CASE WHEN v_member.market='香港' THEN 'HKD' ELSE 'CNY' END)
      IS DISTINCT FROM p_payload->>'currency' THEN
   RAISE EXCEPTION 'valuation currency differs from canonical security currency' USING ERRCODE='22023';
 END IF;
 v_previous:=CASE WHEN p_kind='researcher' THEN v_member.current_researcher_version_id
                  ELSE v_member.current_ai_version_id END;
 IF v_previous IS NOT NULL THEN
   UPDATE valuation_tracker.valuation_version
      SET status='superseded'
    WHERE version_id=v_previous AND status='published';
 END IF;
 INSERT INTO valuation_tracker.valuation_version(
   member_id,valuation_kind,origin,status,valuation_date,target_year,ceiling_value,
   lower_value,base_value,upper_value,currency,amount_unit,expected_net_profit,
   method_summary,change_reason,operating_context,profit_context,cash_flow_context,
   shareholder_return_context,valuation_methods,market_context,sources,model_name,
   prompt_sha256,frozen_input,input_sha256,output_sha256,supersedes_version_id,
   created_by,reviewed_by,published_at
 ) VALUES(
   p_member_id,p_kind,'manual','published',(p_payload->>'valuation_date')::date,
   nullif(p_payload->>'target_year','')::int,v_high,v_low,v_base,v_high,
   p_payload->>'currency','亿元',nullif(p_payload->>'expected_net_profit','')::numeric,
   p_payload->>'method_summary',p_payload->>'change_reason',
   coalesce(p_payload->'operating_context','{}'),coalesce(p_payload->'profit_context','{}'),
   coalesce(p_payload->'cash_flow_context','{}'),coalesce(p_payload->'shareholder_return_context','{}'),
   p_payload->'valuation_methods',coalesce(p_payload->'market_context','{}'),p_payload->'sources',
   p_payload->>'model_name',nullif(p_payload->>'prompt_sha256',''),
   coalesce(p_payload->'frozen_input','{}'),
   encode(sha256(convert_to(coalesce(p_payload->'frozen_input','{}')::text,'UTF8')),'hex'),
   encode(sha256(convert_to((p_payload-'input_sha256'-'output_sha256')::text,'UTF8')),'hex'),
   v_previous,p_actor,p_actor,clock_timestamp()
 ) RETURNING version_id INTO v_version;
 UPDATE valuation_tracker.member SET
   current_researcher_version_id=CASE WHEN p_kind='researcher' THEN v_version ELSE current_researcher_version_id END,
   current_ai_version_id=CASE WHEN p_kind='ai' THEN v_version ELSE current_ai_version_id END,
   revision=revision+1 WHERE member_id=p_member_id;
 v_result:=jsonb_build_object('member_id',p_member_id,'version_id',v_version,
   'member_revision',v_member.revision+1,'kind',p_kind,'lower_value',v_low,
   'base_value',v_base,'upper_value',v_high);
 INSERT INTO valuation_tracker.mutation_result VALUES(
   'edit_valuation_v2',p_idempotency_key,v_request,v_result,clock_timestamp());
 INSERT INTO valuation_tracker.mutation_audit(
   operation_scope,idempotency_key,request_sha256,object_type,object_key,action,
   before_payload,after_payload,actor
 ) VALUES('edit_valuation_v2',p_idempotency_key,v_request,'valuation_version',
   v_version::text,'publish_revision',jsonb_build_object('previous_version_id',v_previous),
   p_payload,p_actor);
 RETURN v_result;
END; $$;

CREATE OR REPLACE FUNCTION valuation_tracker.record_market_batch_v2(
 p_trade_date date,p_slot text,p_observed_at timestamptz,p_calendar_provider text,
 p_calendar_evidence jsonb,p_items jsonb,p_idempotency_key text,p_writer_identity text,
 p_authority_state text,p_cutover_epoch text,p_approval_reference text,
 p_state_revision bigint,p_actor text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,valuation_tracker,operations AS $$
DECLARE v_request text; v_old valuation_tracker.mutation_result%ROWTYPE; v_item jsonb;
 v_member valuation_tracker.member%ROWTYPE; v_count int; v_expected_count int;
 v_market text; v_currency text; v_trigger text; v_result jsonb;
BEGIN
 v_market:=CASE WHEN p_slot='1610' THEN '香港' ELSE 'A股' END;
 v_currency:=CASE WHEN p_slot='1610' THEN 'HKD' ELSE 'CNY' END;
 v_trigger:=CASE p_slot WHEN '1140' THEN '11:40' WHEN '1510' THEN '15:10'
                         WHEN '1610' THEN '16:10' END;
 v_expected_count:=CASE WHEN p_slot='1610' THEN 1 ELSE 6 END;
 IF p_slot NOT IN ('1140','1510','1610')
    OR jsonb_typeof(p_calendar_evidence) IS DISTINCT FROM 'object'
    OR jsonb_typeof(p_items) IS DISTINCT FROM 'array'
    OR jsonb_array_length(p_items) IS DISTINCT FROM v_expected_count
    OR (p_observed_at AT TIME ZONE 'Asia/Shanghai')::date IS DISTINCT FROM p_trade_date
    OR (p_observed_at AT TIME ZONE 'Asia/Shanghai')::time < v_trigger::time
    OR p_calendar_provider IS DISTINCT FROM
       (CASE WHEN p_slot='1610' THEN 'Wind.tdays:HKEX' ELSE 'Wind.tdays:SSE+SZSE' END)
    OR p_calendar_evidence->'is_trading_day' IS DISTINCT FROM 'true'::jsonb
    OR p_calendar_evidence->>'slot' IS DISTINCT FROM p_slot
    OR p_calendar_evidence->>'trigger_time' IS DISTINCT FROM v_trigger
    OR coalesce((p_calendar_evidence->>'late_seconds')::bigint,-1)<0
    OR nullif(btrim(p_idempotency_key),'') IS NULL OR nullif(btrim(p_actor),'') IS NULL THEN
   RAISE EXCEPTION 'market and price batch contract is invalid' USING ERRCODE='22023';
 END IF;
 SELECT count(DISTINCT (x->>'security_id')::bigint) INTO v_count
   FROM jsonb_array_elements(p_items) x;
 IF v_count IS DISTINCT FROM v_expected_count THEN
   RAISE EXCEPTION 'market batch security set is not unique' USING ERRCODE='22023';
 END IF;
 IF (SELECT array_agg((x->>'security_id')::bigint ORDER BY (x->>'security_id')::bigint)
       FROM jsonb_array_elements(p_items)x) IS DISTINCT FROM
    (SELECT array_agg(security_id ORDER BY security_id) FROM valuation_tracker.member
      WHERE enabled AND (CASE WHEN v_market='香港' THEN market='香港' ELSE market IN ('上海','深圳') END)) THEN
   RAISE EXCEPTION 'market batch security set differs from canonical watchlist segment' USING ERRCODE='23503';
 END IF;
 v_request:=encode(sha256(convert_to(jsonb_build_object(
   'actor',p_actor,'date',p_trade_date,'slot',p_slot,'observed_at',p_observed_at,
   'calendar',p_calendar_evidence,'items',p_items
 )::text,'UTF8')),'hex');
 PERFORM pg_advisory_xact_lock(hashtextextended('valuation_tracker.market.v2:'||p_trade_date::text||':'||p_slot,0));
 PERFORM valuation_tracker.assert_writer_v1(
   p_writer_identity,p_authority_state,p_cutover_epoch,p_approval_reference,p_state_revision
 );
 SELECT * INTO v_old FROM valuation_tracker.mutation_result
  WHERE operation_scope='record_market_batch_v2' AND idempotency_key=p_idempotency_key;
 IF FOUND THEN
   IF v_old.request_sha256 IS DISTINCT FROM v_request THEN
     RAISE EXCEPTION 'market batch idempotency conflict' USING ERRCODE='23505';
   END IF;
   RETURN v_old.result_payload;
 END IF;
 FOR v_item IN SELECT value FROM jsonb_array_elements(p_items) LOOP
   SELECT * INTO v_member FROM valuation_tracker.member
    WHERE security_id=(v_item->>'security_id')::bigint AND enabled;
   IF NOT FOUND OR v_member.canonical_ticker IS DISTINCT FROM upper(v_item->>'ticker')
      OR v_member.market IS DISTINCT FROM (CASE WHEN p_slot='1610' THEN '香港' ELSE v_member.market END)
      OR (v_item->>'market_cap_value')::numeric<=0 OR (v_item->>'share_price_value')::numeric<=0
      OR v_item->>'currency' IS DISTINCT FROM v_currency
      OR v_item->>'share_price_currency' IS DISTINCT FROM v_currency
      OR v_item->>'unit' IS DISTINCT FROM '亿元' OR v_item->>'share_price_unit' IS DISTINCT FROM '元'
      OR v_item->>'raw_field' IS DISTINCT FROM 'rt_mkt_cap'
      OR v_item->>'share_price_raw_field' IS DISTINCT FROM 'rt_last'
      OR nullif(btrim(v_item->>'source_ref'),'') IS NULL
      OR v_item->>'source_ref' NOT LIKE 'Wind WSQ.rt_last+rt_mkt_cap+rt_susp_flag:%'
      OR (v_item->>'raw_sha256') !~ '^[0-9a-f]{64}$'
      OR v_item->>'trading_status' NOT IN ('trading','suspended') THEN
     RAISE EXCEPTION 'market observation identity, value, currency, or provenance is invalid' USING ERRCODE='22023';
   END IF;
   INSERT INTO valuation_tracker.market_snapshot(
     member_id,security_id,trade_date,slot,observed_at,provider,raw_field,trading_status,
     market_cap_value,currency,amount_unit,source_ref,raw_sha256,request_sha256,
     share_price_value,share_price_currency,share_price_unit,share_price_raw_field
   ) VALUES(v_member.member_id,v_member.security_id,p_trade_date,p_slot,p_observed_at,
     'Wind','rt_mkt_cap',v_item->>'trading_status',(v_item->>'market_cap_value')::numeric,
     v_currency,'亿元',v_item->>'source_ref',v_item->>'raw_sha256',v_request,
     (v_item->>'share_price_value')::numeric,v_currency,'元','rt_last');
 END LOOP;
 INSERT INTO valuation_tracker.market_run VALUES(
   p_trade_date,p_slot,'completed',p_calendar_provider,p_calendar_evidence,
   v_expected_count,v_request,p_actor,clock_timestamp());
 v_result:=jsonb_build_object('trade_date',p_trade_date,'slot',p_slot,
   'observed_count',v_expected_count,'status','completed','currency',v_currency);
 INSERT INTO valuation_tracker.mutation_result VALUES(
   'record_market_batch_v2',p_idempotency_key,v_request,v_result,clock_timestamp());
 INSERT INTO valuation_tracker.mutation_audit(
   operation_scope,idempotency_key,request_sha256,object_type,object_key,action,
   after_payload,actor
 ) VALUES('record_market_batch_v2',p_idempotency_key,v_request,'market_batch',
   p_trade_date::text||':'||p_slot,'create',v_result,p_actor);
 RETURN v_result;
END; $$;

CREATE OR REPLACE FUNCTION valuation_tracker.record_market_skip_v2(
 p_trade_date date,p_slot text,p_calendar_provider text,p_calendar_evidence jsonb,
 p_idempotency_key text,p_writer_identity text,p_authority_state text,p_cutover_epoch text,
 p_approval_reference text,p_state_revision bigint,p_actor text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,valuation_tracker,operations AS $$
DECLARE v_request text; v_old valuation_tracker.mutation_result%ROWTYPE;
 v_trigger text; v_result jsonb;
BEGIN
 v_trigger:=CASE p_slot WHEN '1140' THEN '11:40' WHEN '1510' THEN '15:10'
                         WHEN '1610' THEN '16:10' END;
 IF p_slot NOT IN ('1140','1510','1610')
    OR jsonb_typeof(p_calendar_evidence) IS DISTINCT FROM 'object'
    OR p_calendar_provider IS DISTINCT FROM
       (CASE WHEN p_slot='1610' THEN 'Wind.tdays:HKEX' ELSE 'Wind.tdays:SSE+SZSE' END)
    OR p_calendar_evidence->'is_trading_day' IS DISTINCT FROM 'false'::jsonb
    OR p_calendar_evidence->>'slot' IS DISTINCT FROM p_slot
    OR p_calendar_evidence->>'trigger_time' IS DISTINCT FROM v_trigger
    OR nullif(btrim(p_idempotency_key),'') IS NULL OR nullif(btrim(p_actor),'') IS NULL THEN
   RAISE EXCEPTION 'market skip contract is invalid' USING ERRCODE='22023';
 END IF;
 v_request:=encode(sha256(convert_to(jsonb_build_object(
   'actor',p_actor,'date',p_trade_date,'slot',p_slot,'calendar',p_calendar_evidence
 )::text,'UTF8')),'hex');
 PERFORM pg_advisory_xact_lock(hashtextextended('valuation_tracker.market.v2:'||p_trade_date::text||':'||p_slot,0));
 PERFORM valuation_tracker.assert_writer_v1(
   p_writer_identity,p_authority_state,p_cutover_epoch,p_approval_reference,p_state_revision
 );
 SELECT * INTO v_old FROM valuation_tracker.mutation_result
  WHERE operation_scope='record_market_skip_v2' AND idempotency_key=p_idempotency_key;
 IF FOUND THEN
   IF v_old.request_sha256 IS DISTINCT FROM v_request THEN
     RAISE EXCEPTION 'market skip idempotency conflict' USING ERRCODE='23505';
   END IF;
   RETURN v_old.result_payload;
 END IF;
 INSERT INTO valuation_tracker.market_run VALUES(
   p_trade_date,p_slot,'skipped_non_trading_day',p_calendar_provider,
   p_calendar_evidence,0,v_request,p_actor,clock_timestamp());
 v_result:=jsonb_build_object('trade_date',p_trade_date,'slot',p_slot,
   'observed_count',0,'status','skipped_non_trading_day');
 INSERT INTO valuation_tracker.mutation_result VALUES(
   'record_market_skip_v2',p_idempotency_key,v_request,v_result,clock_timestamp());
 INSERT INTO valuation_tracker.mutation_audit(
   operation_scope,idempotency_key,request_sha256,object_type,object_key,action,
   after_payload,actor
 ) VALUES('record_market_skip_v2',p_idempotency_key,v_request,'market_batch',
   p_trade_date::text||':'||p_slot,'skip',v_result,p_actor);
 RETURN v_result;
END; $$;

CREATE OR REPLACE FUNCTION valuation_tracker.seed_ai_history_v2(
 p_batch jsonb,p_idempotency_key text,p_writer_identity text,p_authority_state text,
 p_cutover_epoch text,p_approval_reference text,p_state_revision bigint,p_actor text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,valuation_tracker,operations AS $$
DECLARE v_request text; v_old valuation_tracker.mutation_result%ROWTYPE; v_item jsonb;
 v_member valuation_tracker.member%ROWTYPE; v_version bigint; v_count int:=0; v_result jsonb;
 v_low numeric; v_base numeric; v_high numeric;
BEGIN
 IF jsonb_typeof(p_batch) IS DISTINCT FROM 'object'
    OR p_batch->>'schema_version' IS DISTINCT FROM 'honghu.valuation_history.v2'
    OR jsonb_typeof(p_batch->'versions') IS DISTINCT FROM 'array'
    OR jsonb_array_length(p_batch->'versions') IS DISTINCT FROM 11
    OR (p_batch->>'artifact_sha256') !~ '^[0-9a-f]{64}$'
    OR nullif(btrim(p_idempotency_key),'') IS NULL OR nullif(btrim(p_actor),'') IS NULL THEN
   RAISE EXCEPTION 'reviewed AI history seed is invalid' USING ERRCODE='22023';
 END IF;
 IF (SELECT count(DISTINCT (x->>'company_id')||':'||(x->>'valuation_date'))
       FROM jsonb_array_elements(p_batch->'versions') x) IS DISTINCT FROM 11 THEN
   RAISE EXCEPTION 'reviewed AI history identities are duplicated' USING ERRCODE='22023';
 END IF;
 v_request:=encode(sha256(convert_to(jsonb_build_object(
   'actor',p_actor,'batch',p_batch
 )::text,'UTF8')),'hex');
 PERFORM pg_advisory_xact_lock(hashtextextended('valuation_tracker.ai_history:'||p_idempotency_key,0));
 PERFORM valuation_tracker.assert_writer_v1(
   p_writer_identity,p_authority_state,p_cutover_epoch,p_approval_reference,p_state_revision
 );
 SELECT * INTO v_old FROM valuation_tracker.mutation_result
  WHERE operation_scope='seed_ai_history_v2' AND idempotency_key=p_idempotency_key;
 IF FOUND THEN
   IF v_old.request_sha256 IS DISTINCT FROM v_request THEN
     RAISE EXCEPTION 'reviewed AI history idempotency conflict' USING ERRCODE='23505';
   END IF;
   RETURN v_old.result_payload;
 END IF;
 FOR v_item IN SELECT value FROM jsonb_array_elements(p_batch->'versions') LOOP
   v_low:=(v_item->>'lower_value')::numeric;
   v_base:=(v_item->>'base_value')::numeric;
   v_high:=(v_item->>'upper_value')::numeric;
   SELECT * INTO v_member FROM valuation_tracker.member
    WHERE company_id=(v_item->>'company_id')::bigint AND enabled;
   IF NOT FOUND OR v_member.security_id IS DISTINCT FROM (v_item->>'security_id')::bigint
      OR v_member.canonical_ticker IS DISTINCT FROM upper(v_item->>'ticker')
      OR v_low<=0 OR v_low>v_base OR v_base>v_high
      OR (CASE WHEN v_member.market='香港' THEN 'HKD' ELSE 'CNY' END)
         IS DISTINCT FROM v_item->>'currency'
      OR jsonb_typeof(v_item->'valuation_methods') IS DISTINCT FROM 'array'
      OR jsonb_array_length(v_item->'valuation_methods')<2
      OR jsonb_typeof(v_item->'sources') IS DISTINCT FROM 'array'
      OR jsonb_array_length(v_item->'sources')<2
      OR jsonb_typeof(v_item->'frozen_input') IS DISTINCT FROM 'object'
      OR v_item->'frozen_input'='{}'::jsonb
      OR nullif(btrim(v_item->>'method_summary'),'') IS NULL
      OR nullif(btrim(v_item->>'change_reason'),'') IS NULL THEN
     RAISE EXCEPTION 'reviewed AI valuation version is incomplete or mismatched' USING ERRCODE='22023';
   END IF;
   IF NOT EXISTS(SELECT 1 FROM valuation_tracker.valuation_version
      WHERE member_id=v_member.member_id AND valuation_kind='ai'
        AND valuation_date=(v_item->>'valuation_date')::date
        AND model_name='honghu-reviewed-valuation-history-v2') THEN
     INSERT INTO valuation_tracker.valuation_version(
       member_id,valuation_kind,origin,status,valuation_date,target_year,ceiling_value,
       lower_value,base_value,upper_value,currency,amount_unit,expected_net_profit,
       method_summary,change_reason,operating_context,profit_context,cash_flow_context,
       shareholder_return_context,valuation_methods,market_context,sources,model_name,
       prompt_sha256,frozen_input,input_sha256,output_sha256,created_by
     ) VALUES(v_member.member_id,'ai','scheduled_ai','candidate',
       (v_item->>'valuation_date')::date,nullif(v_item->>'target_year','')::int,
       v_high,v_low,v_base,v_high,v_item->>'currency','亿元',
       nullif(v_item->>'expected_net_profit','')::numeric,v_item->>'method_summary',
       v_item->>'change_reason',coalesce(v_item->'operating_context','{}'),
       coalesce(v_item->'profit_context','{}'),coalesce(v_item->'cash_flow_context','{}'),
       coalesce(v_item->'shareholder_return_context','{}'),v_item->'valuation_methods',
       coalesce(v_item->'market_context','{}'),v_item->'sources',
       'honghu-reviewed-valuation-history-v2',p_batch->>'prompt_sha256',v_item->'frozen_input',
       encode(sha256(convert_to((v_item->'frozen_input')::text,'UTF8')),'hex'),
       encode(sha256(convert_to(v_item::text,'UTF8')),'hex'),p_actor
     ) RETURNING version_id INTO v_version;
     INSERT INTO valuation_tracker.mutation_audit(
       operation_scope,idempotency_key,request_sha256,object_type,object_key,action,
       after_payload,actor
     ) VALUES('seed_ai_history_v2',p_idempotency_key,v_request,'valuation_version',
       v_version::text,'seed_reviewed_candidate',v_item,p_actor);
     v_count:=v_count+1;
   END IF;
 END LOOP;
 v_result:=jsonb_build_object('status','candidate_history_seeded','inserted_count',v_count,
   'reviewed_version_count',11,'human_values_overwritten',false);
 INSERT INTO valuation_tracker.mutation_result VALUES(
   'seed_ai_history_v2',p_idempotency_key,v_request,v_result,clock_timestamp());
 RETURN v_result;
END; $$;

CREATE OR REPLACE FUNCTION valuation_tracker.record_ai_candidates_v2(
 p_valuation_date date,p_batch jsonb,p_prompt_sha256 text,p_model_name text,
 p_idempotency_key text,p_writer_identity text,p_authority_state text,p_cutover_epoch text,
 p_approval_reference text,p_state_revision bigint,p_actor text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,valuation_tracker,operations AS $$
DECLARE v_request text; v_old valuation_tracker.mutation_result%ROWTYPE; v_item jsonb;
 v_member valuation_tracker.member%ROWTYPE; v_version bigint; v_count int:=0;
 v_result jsonb; v_low numeric; v_base numeric; v_high numeric;
BEGIN
 IF jsonb_typeof(p_batch) IS DISTINCT FROM 'array'
    OR jsonb_array_length(p_batch) NOT BETWEEN 1 AND 7
    OR p_prompt_sha256 !~ '^[0-9a-f]{64}$'
    OR nullif(btrim(p_model_name),'') IS NULL
    OR nullif(btrim(p_idempotency_key),'') IS NULL
    OR nullif(btrim(p_actor),'') IS NULL THEN
   RAISE EXCEPTION 'AI range candidate batch contract is invalid' USING ERRCODE='22023';
 END IF;
 IF (SELECT count(DISTINCT (x->>'member_id')::bigint)
       FROM jsonb_array_elements(p_batch)x) IS DISTINCT FROM jsonb_array_length(p_batch) THEN
   RAISE EXCEPTION 'AI candidate members are duplicated' USING ERRCODE='22023';
 END IF;
 v_request:=encode(sha256(convert_to(jsonb_build_object(
   'actor',p_actor,'date',p_valuation_date,'batch',p_batch,
   'prompt_sha256',p_prompt_sha256,'model_name',p_model_name
 )::text,'UTF8')),'hex');
 PERFORM pg_advisory_xact_lock(hashtextextended('valuation_tracker.ai.v2:'||p_idempotency_key,0));
 PERFORM valuation_tracker.assert_writer_v1(
   p_writer_identity,p_authority_state,p_cutover_epoch,p_approval_reference,p_state_revision
 );
 SELECT * INTO v_old FROM valuation_tracker.mutation_result
  WHERE operation_scope='record_ai_candidates_v2' AND idempotency_key=p_idempotency_key;
 IF FOUND THEN
   IF v_old.request_sha256 IS DISTINCT FROM v_request THEN
     RAISE EXCEPTION 'AI range candidate idempotency conflict' USING ERRCODE='23505';
   END IF;
   RETURN v_old.result_payload;
 END IF;
 FOR v_item IN SELECT value FROM jsonb_array_elements(p_batch) LOOP
   v_low:=(v_item->>'lower_value')::numeric;
   v_base:=(v_item->>'base_value')::numeric;
   v_high:=(v_item->>'upper_value')::numeric;
   SELECT * INTO v_member FROM valuation_tracker.member
    WHERE member_id=(v_item->>'member_id')::bigint AND enabled;
   IF NOT FOUND OR v_member.company_id IS DISTINCT FROM (v_item->>'company_id')::bigint
      OR v_member.security_id IS DISTINCT FROM (v_item->>'security_id')::bigint
      OR v_low<=0 OR v_low>v_base OR v_base>v_high
      OR (CASE WHEN v_member.market='香港' THEN 'HKD' ELSE 'CNY' END)
         IS DISTINCT FROM v_item->>'currency'
      OR jsonb_typeof(v_item->'valuation_methods') IS DISTINCT FROM 'array'
      OR jsonb_array_length(v_item->'valuation_methods')<2
      OR jsonb_typeof(v_item->'sources') IS DISTINCT FROM 'array'
      OR jsonb_array_length(v_item->'sources')<2
      OR jsonb_typeof(v_item->'frozen_input') IS DISTINCT FROM 'object'
      OR v_item->'frozen_input'='{}'::jsonb
      OR nullif(btrim(v_item->>'method_summary'),'') IS NULL
      OR nullif(btrim(v_item->>'change_reason'),'') IS NULL THEN
     RAISE EXCEPTION 'AI range candidate is incomplete or mismatched' USING ERRCODE='22023';
   END IF;
   INSERT INTO valuation_tracker.valuation_version(
     member_id,valuation_kind,origin,status,valuation_date,target_year,ceiling_value,
     lower_value,base_value,upper_value,currency,amount_unit,expected_net_profit,
     method_summary,change_reason,operating_context,profit_context,cash_flow_context,
     shareholder_return_context,valuation_methods,market_context,sources,model_name,
     prompt_sha256,frozen_input,input_sha256,output_sha256,created_by
   ) VALUES(v_member.member_id,'ai','scheduled_ai','candidate',p_valuation_date,
     nullif(v_item->>'target_year','')::int,v_high,v_low,v_base,v_high,
     v_item->>'currency','亿元',nullif(v_item->>'expected_net_profit','')::numeric,
     v_item->>'method_summary',v_item->>'change_reason',
     coalesce(v_item->'operating_context','{}'),coalesce(v_item->'profit_context','{}'),
     coalesce(v_item->'cash_flow_context','{}'),coalesce(v_item->'shareholder_return_context','{}'),
     v_item->'valuation_methods',coalesce(v_item->'market_context','{}'),v_item->'sources',
     p_model_name,p_prompt_sha256,v_item->'frozen_input',
     encode(sha256(convert_to((v_item->'frozen_input')::text,'UTF8')),'hex'),
     encode(sha256(convert_to(v_item::text,'UTF8')),'hex'),p_actor
   ) RETURNING version_id INTO v_version;
   INSERT INTO valuation_tracker.mutation_audit(
     operation_scope,idempotency_key,request_sha256,object_type,object_key,action,
     after_payload,actor
   ) VALUES('record_ai_candidates_v2',p_idempotency_key,v_request,'valuation_version',
     v_version::text,'create_candidate',v_item,p_actor);
   v_count:=v_count+1;
 END LOOP;
 v_result:=jsonb_build_object('valuation_date',p_valuation_date,'candidate_count',v_count,
   'status','candidate_only','human_values_overwritten',false);
 INSERT INTO valuation_tracker.mutation_result VALUES(
   'record_ai_candidates_v2',p_idempotency_key,v_request,v_result,clock_timestamp());
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
      'record_ai_candidates_v1'
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

CREATE OR REPLACE VIEW valuation_tracker.watchlist_member_v2 AS
SELECT m.*,w.title,w.stable_key,p.researcher_ratio_threshold,p.ai_ratio_threshold,
 p.max_snapshot_age_hours,
 rv.lower_value researcher_lower,rv.base_value researcher_base,
 rv.upper_value researcher_upper,rv.currency researcher_currency,
 rv.valuation_date researcher_date,rv.method_summary researcher_method,
 rv.change_reason researcher_change_reason,rv.sources researcher_sources,
 av.lower_value ai_lower,av.base_value ai_base,av.upper_value ai_upper,
 av.currency ai_currency,av.valuation_date ai_date,av.method_summary ai_method,
 av.change_reason ai_change_reason,av.sources ai_sources,av.operating_context,
 av.profit_context,av.cash_flow_context,av.shareholder_return_context,
 av.valuation_methods,av.market_context,av.created_at ai_updated_at
FROM valuation_tracker.member m JOIN valuation_tracker.watchlist w USING(watchlist_id)
JOIN valuation_tracker.alert_policy_revision p
  ON p.member_id=m.member_id AND p.policy_revision=m.current_policy_revision
LEFT JOIN valuation_tracker.valuation_version rv ON rv.version_id=m.current_researcher_version_id
LEFT JOIN valuation_tracker.valuation_version av ON av.version_id=m.current_ai_version_id;

REVOKE ALL ON FUNCTION valuation_tracker.edit_valuation_v2(
 bigint,text,jsonb,bigint,text,text,text,text,text,bigint,text
) FROM PUBLIC;
REVOKE ALL ON FUNCTION valuation_tracker.fill_legacy_valuation_range_v1() FROM PUBLIC;
REVOKE ALL ON FUNCTION valuation_tracker.record_market_batch_v2(
 date,text,timestamptz,text,jsonb,jsonb,text,text,text,text,text,bigint,text
) FROM PUBLIC;
REVOKE ALL ON FUNCTION valuation_tracker.record_market_skip_v2(
 date,text,text,jsonb,text,text,text,text,text,bigint,text
) FROM PUBLIC;
REVOKE ALL ON FUNCTION valuation_tracker.seed_ai_history_v2(
 jsonb,text,text,text,text,text,bigint,text
) FROM PUBLIC;
REVOKE ALL ON FUNCTION valuation_tracker.record_ai_candidates_v2(
 date,jsonb,text,text,text,text,text,text,text,bigint,text
) FROM PUBLIC;
GRANT SELECT ON valuation_tracker.watchlist_member_v2 TO :"reader_role",:"writer_role",:"audit_reader_role";
GRANT EXECUTE ON FUNCTION valuation_tracker.edit_valuation_v2(
 bigint,text,jsonb,bigint,text,text,text,text,text,bigint,text
),valuation_tracker.record_market_batch_v2(
 date,text,timestamptz,text,jsonb,jsonb,text,text,text,text,text,bigint,text
),valuation_tracker.record_market_skip_v2(
 date,text,text,jsonb,text,text,text,text,text,bigint,text
),valuation_tracker.seed_ai_history_v2(
 jsonb,text,text,text,text,text,bigint,text
),valuation_tracker.record_ai_candidates_v2(
 date,jsonb,text,text,text,text,text,text,text,bigint,text
) TO :"writer_role";

INSERT INTO operations.schema_migration(migration_id,migration_sha256,phase,forward_only)
VALUES('0024_valuation_ranges_share_price_hk',:'migration_sha256','expand',false)
ON CONFLICT(migration_id) DO NOTHING;
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM operations.schema_migration
   WHERE migration_id='0024_valuation_ranges_share_price_hk'
     AND migration_sha256=current_setting('honghu.migration_sha256')) THEN
   RAISE EXCEPTION 'migration identity exists with different SHA256';
 END IF;
END $$;
COMMIT;
