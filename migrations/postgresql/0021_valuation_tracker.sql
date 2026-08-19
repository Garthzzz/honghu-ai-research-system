\set ON_ERROR_STOP on

BEGIN;
SELECT set_config('honghu.migration_sha256', :'migration_sha256', true);

CREATE SCHEMA IF NOT EXISTS valuation_tracker;

CREATE TABLE valuation_tracker.workbook_import (
    workbook_sha256 text PRIMARY KEY CHECK (workbook_sha256 ~ '^[0-9a-f]{64}$'),
    workbook_name text NOT NULL,
    rows_sha256 text NOT NULL CHECK (rows_sha256 ~ '^[0-9a-f]{64}$'),
    row_count integer NOT NULL CHECK (row_count = 7),
    source_payload jsonb NOT NULL CHECK (jsonb_typeof(source_payload)='object'),
    imported_by text NOT NULL CHECK (btrim(imported_by)<>''),
    imported_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE valuation_tracker.watchlist (
    watchlist_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    stable_key text NOT NULL UNIQUE,
    title text NOT NULL,
    workbook_sha256 text NOT NULL REFERENCES valuation_tracker.workbook_import,
    revision bigint NOT NULL DEFAULT 1 CHECK (revision>0),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE valuation_tracker.member (
    member_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    watchlist_id bigint NOT NULL REFERENCES valuation_tracker.watchlist,
    company_id bigint NOT NULL,
    security_id bigint NOT NULL,
    canonical_name text NOT NULL,
    canonical_ticker text NOT NULL,
    market text NOT NULL,
    board text NOT NULL,
    display_order integer NOT NULL CHECK (display_order>0),
    source_row_number integer NOT NULL CHECK (source_row_number BETWEEN 2 AND 8),
    source_row jsonb NOT NULL CHECK (jsonb_typeof(source_row)='object'),
    identity_correction jsonb NOT NULL CHECK (jsonb_typeof(identity_correction)='object'),
    enabled boolean NOT NULL DEFAULT true,
    current_researcher_version_id bigint,
    current_ai_version_id bigint,
    current_policy_revision bigint NOT NULL DEFAULT 1 CHECK (current_policy_revision>0),
    revision bigint NOT NULL DEFAULT 1 CHECK (revision>0),
    UNIQUE(watchlist_id,company_id),
    UNIQUE(watchlist_id,security_id),
    UNIQUE(watchlist_id,display_order)
);

CREATE TABLE valuation_tracker.valuation_version (
    version_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    member_id bigint NOT NULL REFERENCES valuation_tracker.member,
    valuation_kind text NOT NULL CHECK (valuation_kind IN ('researcher','ai')),
    origin text NOT NULL CHECK (origin IN ('workbook_seed','manual','scheduled_ai')),
    status text NOT NULL CHECK (status IN ('candidate','published','superseded','rejected')),
    valuation_date date NOT NULL,
    target_year integer CHECK (target_year BETWEEN 2000 AND 2200),
    ceiling_value numeric(28,8) NOT NULL CHECK (ceiling_value>0),
    currency text NOT NULL CHECK (currency IN ('CNY','HKD','USD','JPY','EUR')),
    amount_unit text NOT NULL CHECK (amount_unit='亿元'),
    expected_net_profit numeric(28,8),
    method_summary text NOT NULL CHECK (btrim(method_summary)<>''),
    change_reason text NOT NULL CHECK (btrim(change_reason)<>''),
    operating_context jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(operating_context)='object'),
    profit_context jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(profit_context)='object'),
    cash_flow_context jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(cash_flow_context)='object'),
    shareholder_return_context jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(shareholder_return_context)='object'),
    valuation_methods jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(valuation_methods)='array'),
    market_context jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(market_context)='object'),
    sources jsonb NOT NULL CHECK (jsonb_typeof(sources)='array' AND jsonb_array_length(sources)>0),
    model_name text,
    prompt_sha256 text CHECK (prompt_sha256 IS NULL OR prompt_sha256 ~ '^[0-9a-f]{64}$'),
    frozen_input jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(frozen_input)='object'),
    input_sha256 text NOT NULL CHECK (input_sha256 ~ '^[0-9a-f]{64}$'),
    output_sha256 text NOT NULL CHECK (output_sha256 ~ '^[0-9a-f]{64}$'),
    supersedes_version_id bigint REFERENCES valuation_tracker.valuation_version,
    created_by text NOT NULL CHECK (btrim(created_by)<>''),
    reviewed_by text,
    published_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK ((status IN ('published','superseded')) = (published_at IS NOT NULL)),
    CHECK (origin<>'scheduled_ai' OR (model_name IS NOT NULL AND prompt_sha256 IS NOT NULL))
);

ALTER TABLE valuation_tracker.member
    ADD CONSTRAINT member_current_researcher_fk FOREIGN KEY(current_researcher_version_id)
        REFERENCES valuation_tracker.valuation_version,
    ADD CONSTRAINT member_current_ai_fk FOREIGN KEY(current_ai_version_id)
        REFERENCES valuation_tracker.valuation_version;

CREATE TABLE valuation_tracker.alert_policy_revision (
    member_id bigint NOT NULL REFERENCES valuation_tracker.member,
    policy_revision bigint NOT NULL CHECK (policy_revision>0),
    researcher_ratio_threshold numeric(12,6) NOT NULL CHECK (researcher_ratio_threshold>0),
    ai_ratio_threshold numeric(12,6) NOT NULL CHECK (ai_ratio_threshold>0),
    operator text NOT NULL DEFAULT 'gte' CHECK (operator='gte'),
    max_snapshot_age_hours integer NOT NULL DEFAULT 48 CHECK (max_snapshot_age_hours BETWEEN 1 AND 720),
    created_by text NOT NULL,
    reason text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(member_id,policy_revision)
);

CREATE TABLE valuation_tracker.market_run (
    trade_date date NOT NULL,
    slot text NOT NULL CHECK(slot IN ('1140','1510')),
    status text NOT NULL CHECK(status IN ('completed','skipped_non_trading_day','failed')),
    calendar_provider text NOT NULL,
    calendar_evidence jsonb NOT NULL CHECK(jsonb_typeof(calendar_evidence)='object'),
    observed_count integer NOT NULL CHECK(observed_count>=0),
    request_sha256 text NOT NULL CHECK(request_sha256 ~ '^[0-9a-f]{64}$'),
    actor text NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(trade_date,slot)
);

CREATE TABLE valuation_tracker.market_snapshot (
    snapshot_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    member_id bigint NOT NULL REFERENCES valuation_tracker.member,
    security_id bigint NOT NULL,
    trade_date date NOT NULL,
    slot text NOT NULL CHECK(slot IN ('1140','1510')),
    observed_at timestamptz NOT NULL,
    provider text NOT NULL CHECK(provider='Wind'),
    raw_field text NOT NULL CHECK(raw_field='mkt_cap_ard'),
    trading_status text NOT NULL CHECK(trading_status IN ('trading','suspended')),
    market_cap_value numeric(28,8) NOT NULL CHECK(market_cap_value>0),
    currency text NOT NULL CHECK(currency='CNY'),
    amount_unit text NOT NULL CHECK(amount_unit='亿元'),
    source_ref text NOT NULL,
    raw_sha256 text NOT NULL CHECK(raw_sha256 ~ '^[0-9a-f]{64}$'),
    request_sha256 text NOT NULL CHECK(request_sha256 ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE(security_id,trade_date,slot,provider)
);

CREATE TABLE valuation_tracker.mutation_result (
    operation_scope text NOT NULL,
    idempotency_key text NOT NULL,
    request_sha256 text NOT NULL CHECK(request_sha256 ~ '^[0-9a-f]{64}$'),
    result_payload jsonb NOT NULL CHECK(jsonb_typeof(result_payload)='object'),
    committed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(operation_scope,idempotency_key)
);

CREATE TABLE valuation_tracker.mutation_audit (
    audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    operation_scope text NOT NULL,
    idempotency_key text NOT NULL,
    request_sha256 text NOT NULL,
    object_type text NOT NULL,
    object_key text NOT NULL,
    action text NOT NULL,
    before_payload jsonb,
    after_payload jsonb NOT NULL,
    actor text NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE(operation_scope,idempotency_key,object_type,object_key)
);

CREATE INDEX valuation_member_order_idx ON valuation_tracker.member(watchlist_id,enabled,display_order);
CREATE INDEX valuation_version_latest_idx ON valuation_tracker.valuation_version(member_id,valuation_kind,created_at DESC,version_id DESC);
CREATE INDEX valuation_market_latest_idx ON valuation_tracker.market_snapshot(member_id,observed_at DESC,snapshot_id DESC);

CREATE OR REPLACE FUNCTION valuation_tracker.assert_writer_v1(
    p_writer_identity text,p_authority_state text,p_cutover_epoch text,
    p_approval_reference text,p_state_revision bigint
) RETURNS operations.cutover_unit_authority
LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,operations
AS $$
DECLARE v operations.cutover_unit_authority%ROWTYPE;
BEGIN
    IF nullif(btrim(p_writer_identity),'') IS NULL OR nullif(btrim(p_authority_state),'') IS NULL
       OR nullif(btrim(p_cutover_epoch),'') IS NULL OR nullif(btrim(p_approval_reference),'') IS NULL
       OR p_state_revision IS NULL OR p_writer_identity IS DISTINCT FROM 'honghu_writer_financial_data'
       OR NOT pg_has_role(session_user,p_writer_identity,'MEMBER') THEN
        RAISE EXCEPTION 'valuation tracker writer identity is incomplete' USING ERRCODE='42501';
    END IF;
    SELECT * INTO v FROM operations.cutover_unit_authority
     WHERE cutover_unit='financial_data' FOR UPDATE;
    IF NOT FOUND OR v.state NOT IN ('S3','S4') OR v.authoritative_backend<>'postgresql_production'
       OR v.writer_identity IS DISTINCT FROM p_writer_identity
       OR v.state IS DISTINCT FROM p_authority_state
       OR v.cutover_epoch IS DISTINCT FROM p_cutover_epoch
       OR v.approval_reference IS DISTINCT FROM p_approval_reference
       OR v.state_revision IS DISTINCT FROM p_state_revision THEN
        RAISE EXCEPTION 'valuation tracker authority is stale or fenced' USING ERRCODE='42501';
    END IF;
    RETURN v;
END; $$;

CREATE OR REPLACE FUNCTION valuation_tracker.replay_task_result_v1(
    p_operation_scope text,p_idempotency_key text,p_writer_identity text,
    p_authority_state text,p_cutover_epoch text,p_approval_reference text,
    p_state_revision bigint
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,valuation_tracker,operations
AS $$
DECLARE v_result jsonb;
BEGIN
    IF p_operation_scope NOT IN ('record_market_batch_v1','record_market_skip_v1','record_ai_candidates_v1')
       OR nullif(btrim(p_idempotency_key),'') IS NULL THEN
        RAISE EXCEPTION 'scheduled replay identity is invalid' USING ERRCODE='22023';
    END IF;
    PERFORM valuation_tracker.assert_writer_v1(
        p_writer_identity,p_authority_state,p_cutover_epoch,
        p_approval_reference,p_state_revision
    );
    SELECT result_payload INTO v_result
      FROM valuation_tracker.mutation_result
     WHERE operation_scope=p_operation_scope AND idempotency_key=p_idempotency_key;
    RETURN v_result;
END; $$;

CREATE OR REPLACE FUNCTION valuation_tracker.seed_workbook_v1(
    p_batch jsonb,p_idempotency_key text,p_writer_identity text,p_authority_state text,
    p_cutover_epoch text,p_approval_reference text,p_state_revision bigint,p_actor text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,valuation_tracker,shared_identity,operations
AS $$
DECLARE v_sha text; v_rows jsonb; v_request text; v_old valuation_tracker.mutation_result%ROWTYPE;
        v_watchlist bigint; v_row jsonb; v_company shared_identity.legacy_record%ROWTYPE;
        v_security shared_identity.legacy_record%ROWTYPE; v_link shared_identity.legacy_record%ROWTYPE;
        v_member bigint; v_version bigint; v_keys integer; v_result jsonb;
BEGIN
    IF jsonb_typeof(p_batch)<>'object' OR nullif(btrim(p_idempotency_key),'') IS NULL OR nullif(btrim(p_actor),'') IS NULL THEN
        RAISE EXCEPTION 'workbook seed identity is incomplete' USING ERRCODE='22023'; END IF;
    v_sha:=p_batch->>'workbook_sha256'; v_rows:=p_batch->'rows';
    IF v_sha IS DISTINCT FROM '453ded4b67ad53848ffd90ab27ddcad21ba3262d623e3946de613c414091e3e0'
       OR jsonb_typeof(v_rows)<>'array' OR jsonb_array_length(v_rows)<>7
       OR p_batch->>'workbook_name' IS DISTINCT FROM '股票篮子.xlsx'
       OR (p_batch->>'rows_sha256') !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'workbook seed does not match frozen source' USING ERRCODE='22023'; END IF;
    SELECT count(DISTINCT (x->>'display_order')::int) INTO v_keys FROM jsonb_array_elements(v_rows) x;
    IF v_keys<>7 OR EXISTS(SELECT 1 FROM jsonb_array_elements(v_rows) x WHERE
        (x->>'company_id')::bigint<=0 OR (x->>'security_id')::bigint<=0 OR
        nullif(btrim(x->>'canonical_name'),'') IS NULL OR nullif(btrim(x->>'canonical_ticker'),'') IS NULL OR
        (x->>'ceiling_value')::numeric<=0 OR (x->>'currency') NOT IN ('CNY','HKD')) THEN
        RAISE EXCEPTION 'workbook row contract is invalid' USING ERRCODE='22023'; END IF;
    v_request:=encode(sha256(convert_to(jsonb_build_object('actor',p_actor,'batch',p_batch)::text,'UTF8')),'hex');
    PERFORM pg_advisory_xact_lock(hashtextextended('valuation_tracker.seed:'||p_idempotency_key,0));
    PERFORM valuation_tracker.assert_writer_v1(p_writer_identity,p_authority_state,p_cutover_epoch,p_approval_reference,p_state_revision);
    SELECT * INTO v_old FROM valuation_tracker.mutation_result WHERE operation_scope='seed_workbook_v1' AND idempotency_key=p_idempotency_key;
    IF FOUND THEN IF v_old.request_sha256 IS DISTINCT FROM v_request THEN RAISE EXCEPTION 'workbook seed idempotency conflict' USING ERRCODE='23505'; END IF; RETURN v_old.result_payload; END IF;
    IF EXISTS(SELECT 1 FROM valuation_tracker.workbook_import WHERE workbook_sha256<>v_sha) THEN
        RAISE EXCEPTION 'a different workbook seed already exists' USING ERRCODE='23505'; END IF;
    INSERT INTO valuation_tracker.workbook_import VALUES(v_sha,p_batch->>'workbook_name',p_batch->>'rows_sha256',7,p_batch,p_actor,clock_timestamp()) ON CONFLICT DO NOTHING;
    INSERT INTO valuation_tracker.watchlist(stable_key,title,workbook_sha256) VALUES('market-cap-space-v1','市值空间与估值跟踪',v_sha)
      ON CONFLICT(stable_key) DO UPDATE SET title=excluded.title,updated_at=clock_timestamp() RETURNING watchlist_id INTO v_watchlist;
    FOR v_row IN SELECT value FROM jsonb_array_elements(v_rows) LOOP
      SELECT * INTO STRICT v_company FROM shared_identity.legacy_record WHERE source_database='research.db' AND source_table='company'
        AND legacy_id=v_row->>'company_id' AND formal_business_data=true;
      SELECT * INTO STRICT v_security FROM shared_identity.legacy_record WHERE source_database='financial.db' AND source_table='financial_security'
        AND legacy_id=v_row->>'security_id' AND formal_business_data=true;
      SELECT * INTO STRICT v_link FROM shared_identity.legacy_record WHERE source_database='financial.db' AND source_table='financial_security_company_link'
        AND legacy_id=v_row->>'company_id' AND formal_business_data=true;
      IF v_company.payload->>'name' IS DISTINCT FROM v_row->>'canonical_name'
         OR upper(v_company.payload->>'ticker') IS DISTINCT FROM upper(v_row->>'canonical_ticker')
         OR upper(v_security.payload->>'ticker') IS DISTINCT FROM upper(v_row->>'canonical_ticker')
         OR v_security.payload->>'research_company_id' IS DISTINCT FROM v_row->>'company_id'
         OR v_link.payload->>'security_id' IS DISTINCT FROM v_row->>'security_id'
         OR v_link.payload->>'link_role' IS DISTINCT FROM 'canonical' THEN
        RAISE EXCEPTION 'workbook company identity mismatch: %',v_row->>'canonical_name' USING ERRCODE='23503'; END IF;
      INSERT INTO valuation_tracker.member(watchlist_id,company_id,security_id,canonical_name,canonical_ticker,market,board,display_order,source_row_number,source_row,identity_correction)
      VALUES(v_watchlist,(v_row->>'company_id')::bigint,(v_row->>'security_id')::bigint,v_row->>'canonical_name',upper(v_row->>'canonical_ticker'),v_row->>'market',v_row->>'board',(v_row->>'display_order')::int,(v_row->>'source_row_number')::int,v_row->'source_row',v_row->'identity_correction')
      ON CONFLICT(watchlist_id,company_id) DO UPDATE SET security_id=excluded.security_id,canonical_name=excluded.canonical_name,canonical_ticker=excluded.canonical_ticker RETURNING member_id INTO v_member;
      IF NOT EXISTS(SELECT 1 FROM valuation_tracker.valuation_version WHERE member_id=v_member AND origin='workbook_seed') THEN
        INSERT INTO valuation_tracker.valuation_version(member_id,valuation_kind,origin,status,valuation_date,target_year,ceiling_value,currency,amount_unit,expected_net_profit,method_summary,change_reason,valuation_methods,sources,input_sha256,output_sha256,created_by,published_at)
        VALUES(v_member,'researcher','workbook_seed','published',(p_batch->>'valuation_date')::date,2028,(v_row->>'ceiling_value')::numeric,v_row->>'currency','亿元',nullif(v_row->>'expected_net_profit','')::numeric,'研究员 Excel 基线；隐含估值倍数仅作可复算参考，不代表 AI 模型结论','首次导入股票篮子',jsonb_build_array(jsonb_build_object('method','研究员市值天花板','implied_pe',(v_row->>'ceiling_value')::numeric/nullif((v_row->>'expected_net_profit')::numeric,0))),jsonb_build_array(jsonb_build_object('title','股票篮子.xlsx','sha256',v_sha,'row',v_row->>'source_row_number')),encode(sha256(convert_to(v_row::text,'UTF8')),'hex'),encode(sha256(convert_to(jsonb_build_object('ceiling',v_row->>'ceiling_value','currency',v_row->>'currency')::text,'UTF8')),'hex'),p_actor,clock_timestamp()) RETURNING version_id INTO v_version;
        UPDATE valuation_tracker.member SET current_researcher_version_id=v_version WHERE member_id=v_member;
        INSERT INTO valuation_tracker.alert_policy_revision(member_id,policy_revision,researcher_ratio_threshold,ai_ratio_threshold,created_by,reason) VALUES(v_member,1,1,1,p_actor,'初始规则：当前市值达到或超过相应估值天花板时警示');
      END IF;
    END LOOP;
    v_result:=jsonb_build_object('watchlist_id',v_watchlist,'member_count',7,'workbook_sha256',v_sha);
    INSERT INTO valuation_tracker.mutation_result VALUES('seed_workbook_v1',p_idempotency_key,v_request,v_result,clock_timestamp());
    INSERT INTO valuation_tracker.mutation_audit(operation_scope,idempotency_key,request_sha256,object_type,object_key,action,after_payload,actor)
      VALUES('seed_workbook_v1',p_idempotency_key,v_request,'watchlist',v_watchlist::text,'seed',p_batch,p_actor);
    RETURN v_result;
END; $$;

CREATE OR REPLACE FUNCTION valuation_tracker.edit_valuation_v1(
    p_member_id bigint,p_kind text,p_payload jsonb,p_expected_member_revision bigint,
    p_idempotency_key text,p_writer_identity text,p_authority_state text,p_cutover_epoch text,
    p_approval_reference text,p_state_revision bigint,p_actor text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,valuation_tracker,operations AS $$
DECLARE v_member valuation_tracker.member%ROWTYPE; v_old valuation_tracker.mutation_result%ROWTYPE;
        v_request text; v_version bigint; v_previous bigint; v_result jsonb;
BEGIN
 IF p_kind NOT IN ('researcher','ai') OR jsonb_typeof(p_payload)<>'object' OR (p_payload->>'ceiling_value')::numeric<=0
    OR (p_payload->>'currency') NOT IN ('CNY','HKD','USD','JPY','EUR') OR nullif(btrim(p_payload->>'method_summary'),'') IS NULL
    OR nullif(btrim(p_payload->>'change_reason'),'') IS NULL OR jsonb_typeof(p_payload->'sources')<>'array' OR jsonb_array_length(p_payload->'sources')=0
    OR jsonb_typeof(p_payload->'valuation_methods')<>'array' OR jsonb_array_length(p_payload->'valuation_methods')=0
    OR EXISTS(SELECT 1 FROM jsonb_array_elements(p_payload->'sources') x WHERE nullif(btrim(x->>'title'),'') IS NULL OR nullif(btrim(x->>'source_type'),'') IS NULL)
    OR EXISTS(SELECT 1 FROM jsonb_array_elements(p_payload->'valuation_methods') x WHERE nullif(btrim(x->>'name'),'') IS NULL)
    OR nullif(btrim(p_idempotency_key),'') IS NULL OR nullif(btrim(p_actor),'') IS NULL THEN RAISE EXCEPTION 'valuation edit is invalid' USING ERRCODE='22023'; END IF;
 v_request:=encode(sha256(convert_to(jsonb_build_object('actor',p_actor,'member_id',p_member_id,'kind',p_kind,'payload',p_payload,'expected_revision',p_expected_member_revision)::text,'UTF8')),'hex');
 PERFORM pg_advisory_xact_lock(hashtextextended('valuation_tracker.edit:'||p_idempotency_key,0));
 PERFORM valuation_tracker.assert_writer_v1(p_writer_identity,p_authority_state,p_cutover_epoch,p_approval_reference,p_state_revision);
 SELECT * INTO v_old FROM valuation_tracker.mutation_result WHERE operation_scope='edit_valuation_v1' AND idempotency_key=p_idempotency_key;
 IF FOUND THEN IF v_old.request_sha256 IS DISTINCT FROM v_request THEN RAISE EXCEPTION 'valuation edit idempotency conflict' USING ERRCODE='23505'; END IF; RETURN v_old.result_payload; END IF;
 SELECT * INTO v_member FROM valuation_tracker.member WHERE member_id=p_member_id AND enabled FOR UPDATE;
 IF NOT FOUND OR v_member.revision IS DISTINCT FROM p_expected_member_revision THEN RAISE EXCEPTION 'stale valuation member revision' USING ERRCODE='40001'; END IF;
 IF (CASE WHEN v_member.market='香港' THEN 'HKD' ELSE 'CNY' END) IS DISTINCT FROM p_payload->>'currency' THEN RAISE EXCEPTION 'valuation currency differs from canonical security currency' USING ERRCODE='22023'; END IF;
 v_previous:=CASE WHEN p_kind='researcher' THEN v_member.current_researcher_version_id ELSE v_member.current_ai_version_id END;
 IF v_previous IS NOT NULL THEN UPDATE valuation_tracker.valuation_version SET status='superseded' WHERE version_id=v_previous AND status='published'; END IF;
 INSERT INTO valuation_tracker.valuation_version(member_id,valuation_kind,origin,status,valuation_date,target_year,ceiling_value,currency,amount_unit,expected_net_profit,method_summary,change_reason,operating_context,profit_context,cash_flow_context,shareholder_return_context,valuation_methods,market_context,sources,model_name,prompt_sha256,input_sha256,output_sha256,supersedes_version_id,created_by,reviewed_by,published_at)
 VALUES(p_member_id,p_kind,'manual','published',(p_payload->>'valuation_date')::date,nullif(p_payload->>'target_year','')::int,(p_payload->>'ceiling_value')::numeric,p_payload->>'currency','亿元',nullif(p_payload->>'expected_net_profit','')::numeric,p_payload->>'method_summary',p_payload->>'change_reason',coalesce(p_payload->'operating_context','{}'),coalesce(p_payload->'profit_context','{}'),coalesce(p_payload->'cash_flow_context','{}'),coalesce(p_payload->'shareholder_return_context','{}'),coalesce(p_payload->'valuation_methods','[]'),coalesce(p_payload->'market_context','{}'),p_payload->'sources',p_payload->>'model_name',nullif(p_payload->>'prompt_sha256',''),encode(sha256(convert_to(p_payload::text,'UTF8')),'hex'),encode(sha256(convert_to(jsonb_build_object('ceiling',p_payload->>'ceiling_value','currency',p_payload->>'currency','method',p_payload->>'method_summary')::text,'UTF8')),'hex'),v_previous,p_actor,p_actor,clock_timestamp()) RETURNING version_id INTO v_version;
 UPDATE valuation_tracker.member SET current_researcher_version_id=CASE WHEN p_kind='researcher' THEN v_version ELSE current_researcher_version_id END,current_ai_version_id=CASE WHEN p_kind='ai' THEN v_version ELSE current_ai_version_id END,revision=revision+1 WHERE member_id=p_member_id;
 v_result:=jsonb_build_object('member_id',p_member_id,'version_id',v_version,'kind',p_kind,'revision',p_expected_member_revision+1);
 INSERT INTO valuation_tracker.mutation_result VALUES('edit_valuation_v1',p_idempotency_key,v_request,v_result,clock_timestamp());
 INSERT INTO valuation_tracker.mutation_audit(operation_scope,idempotency_key,request_sha256,object_type,object_key,action,before_payload,after_payload,actor) VALUES('edit_valuation_v1',p_idempotency_key,v_request,'valuation_version',v_version::text,'publish',jsonb_build_object('previous_version_id',v_previous),p_payload,p_actor);
 RETURN v_result;
END; $$;

CREATE OR REPLACE FUNCTION valuation_tracker.edit_alert_policy_v1(
 p_member_id bigint,p_researcher_threshold numeric,p_ai_threshold numeric,p_max_age integer,p_reason text,p_expected_policy_revision bigint,
 p_idempotency_key text,p_writer_identity text,p_authority_state text,p_cutover_epoch text,p_approval_reference text,p_state_revision bigint,p_actor text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,valuation_tracker,operations AS $$
DECLARE v_member valuation_tracker.member%ROWTYPE; v_request text; v_result jsonb; v_old valuation_tracker.mutation_result%ROWTYPE;
BEGIN
 IF p_researcher_threshold<=0 OR p_ai_threshold<=0 OR p_max_age NOT BETWEEN 1 AND 720 OR nullif(btrim(p_reason),'') IS NULL THEN RAISE EXCEPTION 'alert policy is invalid' USING ERRCODE='22023'; END IF;
 v_request:=encode(sha256(convert_to(jsonb_build_object('actor',p_actor,'member',p_member_id,'r',p_researcher_threshold,'a',p_ai_threshold,'age',p_max_age,'reason',p_reason,'expected',p_expected_policy_revision)::text,'UTF8')),'hex');
 PERFORM pg_advisory_xact_lock(hashtextextended('valuation_tracker.policy:'||p_idempotency_key,0)); PERFORM valuation_tracker.assert_writer_v1(p_writer_identity,p_authority_state,p_cutover_epoch,p_approval_reference,p_state_revision);
 SELECT * INTO v_old FROM valuation_tracker.mutation_result WHERE operation_scope='edit_alert_policy_v1' AND idempotency_key=p_idempotency_key; IF FOUND THEN IF v_old.request_sha256 IS DISTINCT FROM v_request THEN RAISE EXCEPTION 'policy idempotency conflict' USING ERRCODE='23505'; END IF; RETURN v_old.result_payload; END IF;
 SELECT * INTO v_member FROM valuation_tracker.member WHERE member_id=p_member_id FOR UPDATE; IF NOT FOUND OR v_member.current_policy_revision IS DISTINCT FROM p_expected_policy_revision THEN RAISE EXCEPTION 'stale policy revision' USING ERRCODE='40001'; END IF;
 INSERT INTO valuation_tracker.alert_policy_revision VALUES(p_member_id,p_expected_policy_revision+1,p_researcher_threshold,p_ai_threshold,'gte',p_max_age,p_actor,p_reason,clock_timestamp()); UPDATE valuation_tracker.member SET current_policy_revision=current_policy_revision+1,revision=revision+1 WHERE member_id=p_member_id;
 v_result:=jsonb_build_object('member_id',p_member_id,'policy_revision',p_expected_policy_revision+1,'member_revision',v_member.revision+1); INSERT INTO valuation_tracker.mutation_result VALUES('edit_alert_policy_v1',p_idempotency_key,v_request,v_result,clock_timestamp()); INSERT INTO valuation_tracker.mutation_audit(operation_scope,idempotency_key,request_sha256,object_type,object_key,action,after_payload,actor) VALUES('edit_alert_policy_v1',p_idempotency_key,v_request,'alert_policy',p_member_id::text,'revise',jsonb_build_object('researcher_threshold',p_researcher_threshold,'ai_threshold',p_ai_threshold,'max_age',p_max_age,'reason',p_reason),p_actor); RETURN v_result;
END; $$;

CREATE OR REPLACE FUNCTION valuation_tracker.record_market_batch_v1(
 p_trade_date date,p_slot text,p_observed_at timestamptz,p_calendar_provider text,p_calendar_evidence jsonb,p_items jsonb,
 p_idempotency_key text,p_writer_identity text,p_authority_state text,p_cutover_epoch text,p_approval_reference text,p_state_revision bigint,p_actor text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,valuation_tracker,operations AS $$
DECLARE v_request text; v_old valuation_tracker.mutation_result%ROWTYPE; v_item jsonb; v_member valuation_tracker.member%ROWTYPE; v_count int; v_result jsonb;
BEGIN
 IF p_slot NOT IN ('1140','1510') OR jsonb_typeof(p_calendar_evidence)<>'object' OR jsonb_typeof(p_items)<>'array' OR jsonb_array_length(p_items)<>6
    OR (p_observed_at AT TIME ZONE 'Asia/Shanghai')::date IS DISTINCT FROM p_trade_date
    OR (p_observed_at AT TIME ZONE 'Asia/Shanghai')::time
       < (CASE WHEN p_slot='1140' THEN '11:40' ELSE '15:10' END)::time
    OR p_calendar_provider IS DISTINCT FROM 'Wind.tdays:SSE+SZSE'
    OR p_calendar_evidence->'is_trading_day' IS DISTINCT FROM 'true'::jsonb
    OR p_calendar_evidence->>'slot' IS DISTINCT FROM p_slot
    OR p_calendar_evidence->>'trigger_time' IS DISTINCT FROM CASE WHEN p_slot='1140' THEN '11:40' ELSE '15:10' END
    OR coalesce((p_calendar_evidence->>'late_seconds')::bigint,-1)<0
    OR nullif(btrim(p_idempotency_key),'') IS NULL OR nullif(btrim(p_actor),'') IS NULL THEN RAISE EXCEPTION 'market batch contract is invalid' USING ERRCODE='22023'; END IF;
 SELECT count(DISTINCT (x->>'security_id')::bigint) INTO v_count FROM jsonb_array_elements(p_items) x; IF v_count<>6 THEN RAISE EXCEPTION 'market batch security set is not unique' USING ERRCODE='22023'; END IF;
 IF (SELECT array_agg((x->>'security_id')::bigint ORDER BY (x->>'security_id')::bigint) FROM jsonb_array_elements(p_items)x) IS DISTINCT FROM (SELECT array_agg(security_id ORDER BY security_id) FROM valuation_tracker.member WHERE enabled AND market IN ('上海','深圳')) THEN RAISE EXCEPTION 'market batch security set differs from A-share watchlist' USING ERRCODE='23503'; END IF;
 v_request:=encode(sha256(convert_to(jsonb_build_object('actor',p_actor,'date',p_trade_date,'slot',p_slot,'observed_at',p_observed_at,'calendar',p_calendar_evidence,'items',p_items)::text,'UTF8')),'hex'); PERFORM pg_advisory_xact_lock(hashtextextended('valuation_tracker.market:'||p_trade_date::text||':'||p_slot,0)); PERFORM valuation_tracker.assert_writer_v1(p_writer_identity,p_authority_state,p_cutover_epoch,p_approval_reference,p_state_revision);
 SELECT * INTO v_old FROM valuation_tracker.mutation_result WHERE operation_scope='record_market_batch_v1' AND idempotency_key=p_idempotency_key; IF FOUND THEN IF v_old.request_sha256 IS DISTINCT FROM v_request THEN RAISE EXCEPTION 'market batch idempotency conflict' USING ERRCODE='23505'; END IF; RETURN v_old.result_payload; END IF;
 FOR v_item IN SELECT value FROM jsonb_array_elements(p_items) LOOP SELECT * INTO v_member FROM valuation_tracker.member WHERE security_id=(v_item->>'security_id')::bigint AND enabled; IF NOT FOUND OR v_member.canonical_ticker IS DISTINCT FROM upper(v_item->>'ticker') OR (v_item->>'market_cap_value')::numeric<=0 OR v_item->>'currency'<>'CNY' OR v_item->>'unit'<>'亿元' OR nullif(btrim(v_item->>'source_ref'),'') IS NULL OR (v_item->>'raw_sha256') !~ '^[0-9a-f]{64}$' THEN RAISE EXCEPTION 'market observation identity or value is invalid' USING ERRCODE='22023'; END IF;
 IF nullif(v_item->>'trading_status','') IS NULL OR v_item->>'trading_status' NOT IN ('trading','suspended') THEN RAISE EXCEPTION 'market trading status is invalid' USING ERRCODE='22023'; END IF;
 INSERT INTO valuation_tracker.market_snapshot(member_id,security_id,trade_date,slot,observed_at,provider,raw_field,trading_status,market_cap_value,currency,amount_unit,source_ref,raw_sha256,request_sha256) VALUES(v_member.member_id,v_member.security_id,p_trade_date,p_slot,p_observed_at,'Wind','mkt_cap_ard',v_item->>'trading_status',(v_item->>'market_cap_value')::numeric,'CNY','亿元',v_item->>'source_ref',v_item->>'raw_sha256',v_request); END LOOP;
 INSERT INTO valuation_tracker.market_run VALUES(p_trade_date,p_slot,'completed',p_calendar_provider,p_calendar_evidence,6,v_request,p_actor,clock_timestamp()); v_result:=jsonb_build_object('trade_date',p_trade_date,'slot',p_slot,'observed_count',6,'status','completed'); INSERT INTO valuation_tracker.mutation_result VALUES('record_market_batch_v1',p_idempotency_key,v_request,v_result,clock_timestamp()); INSERT INTO valuation_tracker.mutation_audit(operation_scope,idempotency_key,request_sha256,object_type,object_key,action,after_payload,actor) VALUES('record_market_batch_v1',p_idempotency_key,v_request,'market_batch',p_trade_date::text||':'||p_slot,'create',v_result,p_actor); RETURN v_result;
END; $$;

CREATE OR REPLACE FUNCTION valuation_tracker.record_market_skip_v1(
 p_trade_date date,p_slot text,p_calendar_provider text,p_calendar_evidence jsonb,
 p_idempotency_key text,p_writer_identity text,p_authority_state text,p_cutover_epoch text,
 p_approval_reference text,p_state_revision bigint,p_actor text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,valuation_tracker,operations AS $$
DECLARE v_request text; v_old valuation_tracker.mutation_result%ROWTYPE; v_result jsonb;
BEGIN
 IF p_slot NOT IN ('1140','1510') OR jsonb_typeof(p_calendar_evidence)<>'object'
    OR p_calendar_provider IS DISTINCT FROM 'Wind.tdays:SSE+SZSE'
    OR p_calendar_evidence->'is_trading_day' IS DISTINCT FROM 'false'::jsonb
    OR p_calendar_evidence->>'slot' IS DISTINCT FROM p_slot
    OR p_calendar_evidence->>'trigger_time' IS DISTINCT FROM CASE WHEN p_slot='1140' THEN '11:40' ELSE '15:10' END
    OR nullif(btrim(p_idempotency_key),'') IS NULL OR nullif(btrim(p_actor),'') IS NULL THEN
   RAISE EXCEPTION 'market skip contract is invalid' USING ERRCODE='22023'; END IF;
 v_request:=encode(sha256(convert_to(jsonb_build_object('actor',p_actor,'date',p_trade_date,'slot',p_slot,'calendar',p_calendar_evidence)::text,'UTF8')),'hex');
 PERFORM pg_advisory_xact_lock(hashtextextended('valuation_tracker.market:'||p_trade_date::text||':'||p_slot,0));
 PERFORM valuation_tracker.assert_writer_v1(p_writer_identity,p_authority_state,p_cutover_epoch,p_approval_reference,p_state_revision);
 SELECT * INTO v_old FROM valuation_tracker.mutation_result WHERE operation_scope='record_market_skip_v1' AND idempotency_key=p_idempotency_key;
 IF FOUND THEN IF v_old.request_sha256 IS DISTINCT FROM v_request THEN RAISE EXCEPTION 'market skip idempotency conflict' USING ERRCODE='23505'; END IF; RETURN v_old.result_payload; END IF;
 INSERT INTO valuation_tracker.market_run VALUES(p_trade_date,p_slot,'skipped_non_trading_day',p_calendar_provider,p_calendar_evidence,0,v_request,p_actor,clock_timestamp());
 v_result:=jsonb_build_object('trade_date',p_trade_date,'slot',p_slot,'observed_count',0,'status','skipped_non_trading_day');
 INSERT INTO valuation_tracker.mutation_result VALUES('record_market_skip_v1',p_idempotency_key,v_request,v_result,clock_timestamp());
 INSERT INTO valuation_tracker.mutation_audit(operation_scope,idempotency_key,request_sha256,object_type,object_key,action,after_payload,actor)
 VALUES('record_market_skip_v1',p_idempotency_key,v_request,'market_batch',p_trade_date::text||':'||p_slot,'skip',v_result,p_actor);
 RETURN v_result;
END; $$;

CREATE OR REPLACE FUNCTION valuation_tracker.record_ai_candidates_v1(
 p_valuation_date date,p_batch jsonb,p_prompt_sha256 text,p_model_name text,
 p_idempotency_key text,p_writer_identity text,p_authority_state text,p_cutover_epoch text,
 p_approval_reference text,p_state_revision bigint,p_actor text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,valuation_tracker,operations AS $$
DECLARE v_request text; v_old valuation_tracker.mutation_result%ROWTYPE; v_item jsonb;
        v_member valuation_tracker.member%ROWTYPE; v_version bigint; v_count int:=0; v_result jsonb;
        v_input_sha text; v_output_sha text;
BEGIN
 IF jsonb_typeof(p_batch) IS DISTINCT FROM 'array' OR jsonb_array_length(p_batch) NOT BETWEEN 1 AND 7
    OR p_prompt_sha256 !~ '^[0-9a-f]{64}$' OR nullif(btrim(p_model_name),'') IS NULL
    OR nullif(btrim(p_idempotency_key),'') IS NULL OR nullif(btrim(p_actor),'') IS NULL THEN
   RAISE EXCEPTION 'AI candidate batch contract is invalid' USING ERRCODE='22023'; END IF;
 IF (SELECT count(DISTINCT (x->>'member_id')::bigint) FROM jsonb_array_elements(p_batch)x)<>jsonb_array_length(p_batch) THEN
   RAISE EXCEPTION 'AI candidate members are duplicated' USING ERRCODE='22023'; END IF;
 v_request:=encode(sha256(convert_to(jsonb_build_object('actor',p_actor,'date',p_valuation_date,'batch',p_batch,'prompt_sha256',p_prompt_sha256,'model_name',p_model_name)::text,'UTF8')),'hex');
 PERFORM pg_advisory_xact_lock(hashtextextended('valuation_tracker.ai:'||p_idempotency_key,0));
 PERFORM valuation_tracker.assert_writer_v1(p_writer_identity,p_authority_state,p_cutover_epoch,p_approval_reference,p_state_revision);
 SELECT * INTO v_old FROM valuation_tracker.mutation_result WHERE operation_scope='record_ai_candidates_v1' AND idempotency_key=p_idempotency_key;
 IF FOUND THEN IF v_old.request_sha256 IS DISTINCT FROM v_request THEN RAISE EXCEPTION 'AI candidate idempotency conflict' USING ERRCODE='23505'; END IF; RETURN v_old.result_payload; END IF;
 FOR v_item IN SELECT value FROM jsonb_array_elements(p_batch) LOOP
   SELECT * INTO v_member FROM valuation_tracker.member WHERE member_id=(v_item->>'member_id')::bigint AND enabled;
   IF NOT FOUND OR v_member.company_id IS DISTINCT FROM (v_item->>'company_id')::bigint
      OR v_member.security_id IS DISTINCT FROM (v_item->>'security_id')::bigint
      OR EXISTS(SELECT 1 FROM jsonb_object_keys(v_item) k WHERE k NOT IN ('member_id','company_id','security_id','target_year','ceiling_value','currency','expected_net_profit','method_summary','change_reason','operating_context','profit_context','cash_flow_context','shareholder_return_context','valuation_methods','market_context','sources','frozen_input'))
      OR (v_item->>'ceiling_value')::numeric<=0 OR (v_item->>'currency') NOT IN ('CNY','HKD','USD','JPY','EUR')
      OR (CASE WHEN v_member.market='香港' THEN 'HKD' ELSE 'CNY' END) IS DISTINCT FROM v_item->>'currency'
      OR jsonb_typeof(v_item->'valuation_methods')<>'array' OR jsonb_array_length(v_item->'valuation_methods')<2
      OR jsonb_typeof(v_item->'sources')<>'array' OR jsonb_array_length(v_item->'sources')<2
      OR jsonb_typeof(v_item->'frozen_input') IS DISTINCT FROM 'object'
      OR (SELECT count(DISTINCT x->>'run_key') FROM jsonb_array_elements(v_item->'valuation_methods') x) IS DISTINCT FROM jsonb_array_length(v_item->'valuation_methods')
      OR (SELECT count(DISTINCT (x->>'run_id')::bigint) FROM jsonb_array_elements(v_item->'valuation_methods') x) IS DISTINCT FROM jsonb_array_length(v_item->'valuation_methods')
      OR EXISTS(SELECT 1 FROM jsonb_array_elements(v_item->'valuation_methods') x WHERE nullif(btrim(x->>'run_key'),'') IS NULL OR nullif(btrim(x->>'run_id'),'') IS NULL OR x->>'currency' IS DISTINCT FROM v_item->>'currency' OR x->>'output_name' !~ '(目标市值|股权价值|股权现金流价值)' OR x->>'unit' !~ '(亿元人民币|人民币亿元|CNY亿元|亿元CNY|亿港元|港元亿元|HKD亿元|亿元HKD|亿美元|USD亿元|亿元USD|亿日元|JPY亿元|亿元JPY|亿欧元|EUR亿元|亿元EUR)')
      OR (SELECT count(DISTINCT btrim(x->>'title')||':'||btrim(x->>'source_type')) FROM jsonb_array_elements(v_item->'sources') x) < 2
      OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(v_item->'sources') x WHERE x->>'source_type'='model_reconciliation')
      OR nullif(btrim(v_item->>'method_summary'),'') IS NULL OR nullif(btrim(v_item->>'change_reason'),'') IS NULL THEN
     RAISE EXCEPTION 'AI candidate is incomplete or mismatched' USING ERRCODE='22023'; END IF;
   v_input_sha:=encode(sha256(convert_to((v_item->'frozen_input')::text,'UTF8')),'hex');
   v_output_sha:=encode(sha256(convert_to((v_item-'input_sha256'-'output_sha256')::text,'UTF8')),'hex');
   INSERT INTO valuation_tracker.valuation_version(member_id,valuation_kind,origin,status,valuation_date,target_year,ceiling_value,currency,amount_unit,expected_net_profit,method_summary,change_reason,operating_context,profit_context,cash_flow_context,shareholder_return_context,valuation_methods,market_context,sources,model_name,prompt_sha256,frozen_input,input_sha256,output_sha256,created_by)
   VALUES(v_member.member_id,'ai','scheduled_ai','candidate',p_valuation_date,nullif(v_item->>'target_year','')::int,(v_item->>'ceiling_value')::numeric,v_item->>'currency','亿元',nullif(v_item->>'expected_net_profit','')::numeric,v_item->>'method_summary',v_item->>'change_reason',coalesce(v_item->'operating_context','{}'),coalesce(v_item->'profit_context','{}'),coalesce(v_item->'cash_flow_context','{}'),coalesce(v_item->'shareholder_return_context','{}'),v_item->'valuation_methods',coalesce(v_item->'market_context','{}'),v_item->'sources',p_model_name,p_prompt_sha256,v_item->'frozen_input',v_input_sha,v_output_sha,p_actor) RETURNING version_id INTO v_version;
   INSERT INTO valuation_tracker.mutation_audit(operation_scope,idempotency_key,request_sha256,object_type,object_key,action,after_payload,actor)
   VALUES('record_ai_candidates_v1',p_idempotency_key,v_request,'valuation_version',v_version::text,'create_candidate',v_item,p_actor);
   v_count:=v_count+1;
 END LOOP;
 v_result:=jsonb_build_object('valuation_date',p_valuation_date,'candidate_count',v_count,'status','candidate_only','human_values_overwritten',false);
 INSERT INTO valuation_tracker.mutation_result VALUES('record_ai_candidates_v1',p_idempotency_key,v_request,v_result,clock_timestamp());
 RETURN v_result;
END; $$;

CREATE OR REPLACE VIEW valuation_tracker.watchlist_member_v1 AS
SELECT m.*,w.title,w.stable_key,p.researcher_ratio_threshold,p.ai_ratio_threshold,p.max_snapshot_age_hours,
       rv.ceiling_value researcher_ceiling,rv.currency researcher_currency,rv.valuation_date researcher_date,
       rv.method_summary researcher_method,rv.change_reason researcher_change_reason,rv.sources researcher_sources,
       av.ceiling_value ai_ceiling,av.currency ai_currency,av.valuation_date ai_date,av.method_summary ai_method,
       av.change_reason ai_change_reason,av.sources ai_sources,av.operating_context,av.profit_context,av.cash_flow_context,
       av.shareholder_return_context,av.valuation_methods,av.market_context,av.created_at ai_updated_at
FROM valuation_tracker.member m JOIN valuation_tracker.watchlist w USING(watchlist_id)
JOIN valuation_tracker.alert_policy_revision p ON p.member_id=m.member_id AND p.policy_revision=m.current_policy_revision
LEFT JOIN valuation_tracker.valuation_version rv ON rv.version_id=m.current_researcher_version_id
LEFT JOIN valuation_tracker.valuation_version av ON av.version_id=m.current_ai_version_id;

REVOKE ALL ON SCHEMA valuation_tracker FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA valuation_tracker FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA valuation_tracker FROM PUBLIC;
GRANT USAGE ON SCHEMA valuation_tracker TO :"reader_role",:"writer_role",:"audit_reader_role";
GRANT SELECT ON valuation_tracker.watchlist,valuation_tracker.member,valuation_tracker.valuation_version,
 valuation_tracker.alert_policy_revision,valuation_tracker.market_run,valuation_tracker.market_snapshot,
 valuation_tracker.watchlist_member_v1 TO :"reader_role",:"writer_role",:"audit_reader_role";
GRANT SELECT ON valuation_tracker.mutation_result,valuation_tracker.mutation_audit TO :"writer_role",:"audit_reader_role";
GRANT EXECUTE ON FUNCTION valuation_tracker.seed_workbook_v1(jsonb,text,text,text,text,text,bigint,text),
 valuation_tracker.replay_task_result_v1(text,text,text,text,text,text,bigint),
 valuation_tracker.edit_valuation_v1(bigint,text,jsonb,bigint,text,text,text,text,text,bigint,text),
 valuation_tracker.edit_alert_policy_v1(bigint,numeric,numeric,integer,text,bigint,text,text,text,text,text,bigint,text),
 valuation_tracker.record_market_batch_v1(date,text,timestamptz,text,jsonb,jsonb,text,text,text,text,text,bigint,text),
 valuation_tracker.record_market_skip_v1(date,text,text,jsonb,text,text,text,text,text,bigint,text),
 valuation_tracker.record_ai_candidates_v1(date,jsonb,text,text,text,text,text,text,text,bigint,text)
 TO :"writer_role";
GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA valuation_tracker TO :"writer_role";

INSERT INTO operations.schema_migration(migration_id,migration_sha256,phase,forward_only)
VALUES('0021_valuation_tracker',:'migration_sha256','expand',false) ON CONFLICT(migration_id) DO NOTHING;
DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM operations.schema_migration WHERE migration_id='0021_valuation_tracker' AND migration_sha256=current_setting('honghu.migration_sha256')) THEN RAISE EXCEPTION 'migration identity exists with different SHA256'; END IF; END $$;
COMMIT;
