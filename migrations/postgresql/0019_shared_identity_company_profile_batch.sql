\set ON_ERROR_STOP on

BEGIN;
SELECT set_config('honghu.migration_sha256', :'migration_sha256', true);

CREATE TABLE IF NOT EXISTS shared_identity.record_revision_audit (
    audit_id bigserial PRIMARY KEY,
    operation_scope text NOT NULL,
    idempotency_key text NOT NULL,
    request_sha256 text NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
    source_database text NOT NULL,
    source_table text NOT NULL,
    legacy_id text NOT NULL,
    action text NOT NULL CHECK (action IN ('create','update')),
    from_revision bigint NOT NULL CHECK (from_revision >= 0),
    to_revision bigint NOT NULL CHECK (to_revision = from_revision + 1),
    previous_row_sha256 text,
    replacement_row_sha256 text NOT NULL CHECK (replacement_row_sha256 ~ '^[0-9a-f]{64}$'),
    previous_payload jsonb,
    replacement_payload jsonb NOT NULL CHECK (jsonb_typeof(replacement_payload) = 'object'),
    actor text NOT NULL,
    changed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (operation_scope,idempotency_key,source_database,source_table,legacy_id)
);

CREATE OR REPLACE FUNCTION shared_identity.ensure_industry_v1(
    p_industry jsonb,
    p_stable_key text,
    p_idempotency_key text,
    p_writer_identity text,
    p_authority_state text,
    p_cutover_epoch text,
    p_approval_reference text,
    p_state_revision bigint,
    p_actor text
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, shared_identity, operations
AS $$
DECLARE
    v_existing shared_identity.mutation_result%ROWTYPE;
    v_authority operations.cutover_unit_authority%ROWTYPE;
    v_record shared_identity.legacy_record%ROWTYPE;
    v_id bigint;
    v_parent_id bigint;
    v_next_id bigint;
    v_row_sha text;
    v_request_sha text;
    v_result jsonb;
    v_operation_scope constant text := 'shared_identity.ensure_industry_v1';
BEGIN
    IF jsonb_typeof(p_industry) <> 'object'
       OR EXISTS (
           SELECT 1 FROM jsonb_object_keys(p_industry) AS item(key)
            WHERE item.key NOT IN (
                'id','name','parent_id','level','tier','status','core_dynamic',
                'last_updated','created_at'
            )
       )
       OR jsonb_typeof(p_industry->'id') IS DISTINCT FROM 'number'
       OR jsonb_typeof(p_industry->'parent_id') IS DISTINCT FROM 'number'
       OR nullif(btrim(p_industry->>'name'),'') IS NULL
       OR nullif(btrim(p_stable_key),'') IS NULL
       OR nullif(btrim(p_idempotency_key),'') IS NULL
       OR nullif(btrim(p_actor),'') IS NULL
       OR nullif(btrim(p_writer_identity),'') IS NULL
       OR nullif(btrim(p_authority_state),'') IS NULL
       OR nullif(btrim(p_cutover_epoch),'') IS NULL
       OR nullif(btrim(p_approval_reference),'') IS NULL
       OR p_state_revision IS NULL THEN
        RAISE EXCEPTION 'industry mutation identity is incomplete'
            USING ERRCODE='22023';
    END IF;
    v_request_sha := encode(sha256(convert_to(
        jsonb_build_object(
            'actor',p_actor,'industry',p_industry,'stable_key',p_stable_key
        )::text,'UTF8'
    )),'hex');
    PERFORM pg_advisory_xact_lock(hashtextextended(
        v_operation_scope || ':' || p_idempotency_key, 0
    ));
    v_authority := shared_identity.assert_formal_writer_v1(p_writer_identity);
    IF NOT pg_has_role(session_user,p_writer_identity,'MEMBER')
       OR v_authority.state IS DISTINCT FROM p_authority_state
       OR v_authority.cutover_epoch IS DISTINCT FROM p_cutover_epoch
       OR v_authority.approval_reference IS DISTINCT FROM p_approval_reference
       OR v_authority.state_revision IS DISTINCT FROM p_state_revision THEN
        RAISE EXCEPTION 'industry authority token is stale or incomplete'
            USING ERRCODE='42501';
    END IF;
    SELECT * INTO v_existing
      FROM shared_identity.mutation_result
     WHERE operation_scope=v_operation_scope
       AND idempotency_key=p_idempotency_key;
    IF FOUND THEN
        IF v_existing.request_sha256 IS DISTINCT FROM v_request_sha THEN
            RAISE EXCEPTION 'industry idempotency conflict' USING ERRCODE='23505';
        END IF;
        RETURN v_existing.result_payload;
    END IF;

    v_id := (p_industry->>'id')::bigint;
    v_parent_id := nullif(p_industry->>'parent_id','')::bigint;
    SELECT * INTO v_record
      FROM shared_identity.legacy_record
     WHERE source_database='research.db' AND source_table='industry'
       AND legacy_id=v_id::text AND formal_business_data=true
     FOR UPDATE;
    IF FOUND THEN
        IF v_record.stable_key IS DISTINCT FROM p_stable_key
           OR v_record.payload->>'name' IS DISTINCT FROM p_industry->>'name' THEN
            RAISE EXCEPTION 'industry identity conflicts with formal mapping'
                USING ERRCODE='23505';
        END IF;
        v_result := jsonb_build_object(
            'industry_id',v_id,'stable_key',p_stable_key,'created',false
        );
        RETURN shared_identity.record_mutation_v1(
            v_operation_scope,p_idempotency_key,v_request_sha,p_stable_key,
            'ensure_existing',p_actor,v_result,0
        );
    END IF;
    IF v_parent_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM shared_identity.legacy_record
         WHERE source_database='research.db' AND source_table='industry'
           AND legacy_id=v_parent_id::text AND formal_business_data=true
    ) THEN
        RAISE EXCEPTION 'industry parent is absent' USING ERRCODE='23503';
    END IF;
    IF EXISTS (
        SELECT 1 FROM shared_identity.legacy_record
         WHERE source_database='research.db' AND source_table='industry'
           AND stable_key=p_stable_key AND formal_business_data=true
    ) THEN
        RAISE EXCEPTION 'industry stable identity already exists'
            USING ERRCODE='23505';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'shared_identity:research.db:industry', 0
    ));
    SELECT COALESCE(max(legacy_id::bigint),0)+1 INTO v_next_id
      FROM shared_identity.legacy_record
     WHERE source_database='research.db' AND source_table='industry'
       AND legacy_id ~ '^[0-9]+$';
    IF v_next_id <> v_id THEN
        RAISE EXCEPTION 'industry id allocation does not preserve expected id'
            USING ERRCODE='40001';
    END IF;
    PERFORM shared_identity.append_formal_record_v1(
        'research.db','industry',v_id::text,p_stable_key,'entity',p_industry
    );
    v_row_sha := encode(sha256(convert_to(p_industry::text,'UTF8')),'hex');
    INSERT INTO shared_identity.record_revision_audit(
        operation_scope,idempotency_key,request_sha256,source_database,
        source_table,legacy_id,action,from_revision,to_revision,
        previous_row_sha256,replacement_row_sha256,previous_payload,
        replacement_payload,actor
    ) VALUES (
        v_operation_scope,p_idempotency_key,v_request_sha,
        'research.db','industry',v_id::text,'create',0,1,NULL,v_row_sha,
        NULL,p_industry,p_actor
    );
    v_result := jsonb_build_object(
        'industry_id',v_id,'stable_key',p_stable_key,'created',true
    );
    RETURN shared_identity.record_mutation_v1(
        v_operation_scope,p_idempotency_key,v_request_sha,p_stable_key,
        'create',p_actor,v_result,1
    );
END;
$$;

CREATE OR REPLACE FUNCTION shared_identity.ensure_listed_company_v2(
    p_company jsonb,
    p_stable_key text,
    p_idempotency_key text,
    p_writer_identity text,
    p_authority_state text,
    p_cutover_epoch text,
    p_approval_reference text,
    p_state_revision bigint,
    p_actor text
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, shared_identity, operations
AS $$
DECLARE
    v_existing shared_identity.mutation_result%ROWTYPE;
    v_authority operations.cutover_unit_authority%ROWTYPE;
    v_record shared_identity.legacy_record%ROWTYPE;
    v_company_id bigint;
    v_next_id bigint;
    v_security_id bigint;
    v_alias_id bigint;
    v_alias text;
    v_payload jsonb;
    v_row_sha text;
    v_request_sha text;
    v_result jsonb;
    v_added bigint := 0;
    v_operation_scope constant text := 'shared_identity.ensure_listed_company_v2';
BEGIN
    IF jsonb_typeof(p_company) <> 'object'
       OR EXISTS (
           SELECT 1 FROM jsonb_object_keys(p_company) AS item(key)
            WHERE item.key NOT IN (
                'id','name','ticker','market','listing_status',
                'financial_market','financial_listing_status','reporting_currency',
                'name_en','fiscal_year_end','verification_source_ref','aliases'
            )
       )
       OR jsonb_typeof(p_company->'id') IS DISTINCT FROM 'number'
       OR jsonb_typeof(p_company->'aliases') <> 'array'
       OR nullif(btrim(p_company->>'name'),'') IS NULL
       OR nullif(btrim(p_company->>'ticker'),'') IS NULL
       OR nullif(btrim(p_company->>'market'),'') IS NULL
       OR nullif(btrim(p_company->>'listing_status'),'') IS NULL
       OR nullif(btrim(p_company->>'financial_market'),'') IS NULL
       OR nullif(btrim(p_company->>'financial_listing_status'),'') IS NULL
       OR nullif(btrim(p_company->>'reporting_currency'),'') IS NULL
       OR nullif(btrim(p_company->>'verification_source_ref'),'') IS NULL
       OR nullif(btrim(p_stable_key),'') IS NULL
       OR nullif(btrim(p_idempotency_key),'') IS NULL
       OR nullif(btrim(p_writer_identity),'') IS NULL
       OR nullif(btrim(p_authority_state),'') IS NULL
       OR nullif(btrim(p_cutover_epoch),'') IS NULL
       OR nullif(btrim(p_approval_reference),'') IS NULL
       OR p_state_revision IS NULL
       OR nullif(btrim(p_actor),'') IS NULL THEN
        RAISE EXCEPTION 'listed company v2 mutation identity is incomplete'
            USING ERRCODE='22023';
    END IF;
    v_request_sha := encode(sha256(convert_to(
        jsonb_build_object(
            'actor',p_actor,'company',p_company,'stable_key',p_stable_key
        )::text,'UTF8'
    )),'hex');
    PERFORM pg_advisory_xact_lock(hashtextextended(
        v_operation_scope || ':' || p_idempotency_key, 0
    ));
    v_authority := shared_identity.assert_formal_writer_v1(p_writer_identity);
    IF NOT pg_has_role(session_user,p_writer_identity,'MEMBER')
       OR v_authority.state IS DISTINCT FROM p_authority_state
       OR v_authority.cutover_epoch IS DISTINCT FROM p_cutover_epoch
       OR v_authority.approval_reference IS DISTINCT FROM p_approval_reference
       OR v_authority.state_revision IS DISTINCT FROM p_state_revision THEN
        RAISE EXCEPTION 'listed company v2 authority token is stale or incomplete'
            USING ERRCODE='42501';
    END IF;
    SELECT * INTO v_existing
      FROM shared_identity.mutation_result
     WHERE operation_scope=v_operation_scope
       AND idempotency_key=p_idempotency_key;
    IF FOUND THEN
        IF v_existing.request_sha256 IS DISTINCT FROM v_request_sha THEN
            RAISE EXCEPTION 'listed company v2 idempotency conflict'
                USING ERRCODE='23505';
        END IF;
        RETURN v_existing.result_payload;
    END IF;

    v_company_id := (p_company->>'id')::bigint;
    SELECT * INTO v_record
      FROM shared_identity.legacy_record
     WHERE source_database='research.db' AND source_table='company'
       AND legacy_id=v_company_id::text AND formal_business_data=true
     FOR UPDATE;
    IF FOUND THEN
        IF v_record.stable_key IS DISTINCT FROM p_stable_key
           OR v_record.payload->>'name' IS DISTINCT FROM p_company->>'name'
           OR upper(v_record.payload->>'ticker') IS DISTINCT FROM upper(p_company->>'ticker')
           OR v_record.payload->>'market' IS DISTINCT FROM p_company->>'market'
           OR v_record.payload->>'listing_status' IS DISTINCT FROM p_company->>'listing_status' THEN
            RAISE EXCEPTION 'listed company v2 conflicts with formal identity'
                USING ERRCODE='23505';
        END IF;
        v_result := jsonb_build_object(
            'company_id',v_company_id,'stable_key',p_stable_key,'created',false
        );
        RETURN shared_identity.record_mutation_v1(
            v_operation_scope,p_idempotency_key,v_request_sha,p_stable_key,
            'ensure_existing',p_actor,v_result,0
        );
    END IF;
    IF EXISTS (
        SELECT 1 FROM shared_identity.legacy_record
         WHERE source_database='research.db' AND source_table='company'
           AND formal_business_data=true
           AND (
               stable_key=p_stable_key
               OR lower(btrim(payload->>'name'))=lower(btrim(p_company->>'name'))
               OR (
                   upper(btrim(payload->>'ticker'))=upper(btrim(p_company->>'ticker'))
                   AND lower(btrim(payload->>'market'))=lower(btrim(p_company->>'market'))
               )
           )
    ) THEN
        RAISE EXCEPTION 'listed company v2 identity already exists'
            USING ERRCODE='23505';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'shared_identity:research.db:company', 0
    ));
    SELECT COALESCE(max(legacy_id::bigint),0)+1 INTO v_next_id
      FROM shared_identity.legacy_record
     WHERE source_database='research.db' AND source_table='company'
       AND legacy_id ~ '^[0-9]+$';
    IF v_next_id <> v_company_id THEN
        RAISE EXCEPTION 'company id allocation does not preserve expected id'
            USING ERRCODE='40001';
    END IF;
    v_payload := jsonb_build_object(
        'id',v_company_id,'name',btrim(p_company->>'name'),
        'ticker',upper(btrim(p_company->>'ticker')),
        'market',btrim(p_company->>'market'),
        'listing_status',btrim(p_company->>'listing_status'),
        'note','identity verification source: ' || btrim(p_company->>'verification_source_ref'),
        'created_at',clock_timestamp()
    );
    PERFORM shared_identity.append_formal_record_v1(
        'research.db','company',v_company_id::text,p_stable_key,'entity',v_payload
    );
    v_row_sha := encode(sha256(convert_to(v_payload::text,'UTF8')),'hex');
    INSERT INTO shared_identity.record_revision_audit(
        operation_scope,idempotency_key,request_sha256,source_database,
        source_table,legacy_id,action,from_revision,to_revision,
        previous_row_sha256,replacement_row_sha256,previous_payload,
        replacement_payload,actor
    ) VALUES (
        v_operation_scope,p_idempotency_key,v_request_sha,'research.db',
        'company',v_company_id::text,'create',0,1,NULL,v_row_sha,NULL,v_payload,p_actor
    );
    v_added := v_added + 1;

    v_security_id := shared_identity.next_legacy_identity_v1(
        'financial.db','financial_security'
    );
    v_payload := jsonb_build_object(
        'id',v_security_id,'research_company_id',v_company_id,
        'canonical_name',btrim(p_company->>'name'),
        'ticker',upper(btrim(p_company->>'ticker')),
        'market',btrim(p_company->>'financial_market'),
        'listing_status',btrim(p_company->>'financial_listing_status'),
        'reporting_currency',upper(btrim(p_company->>'reporting_currency')),
        'name_en',p_company->'name_en',
        'fiscal_year_end',p_company->'fiscal_year_end',
        'identity_status','verified','created_at',clock_timestamp(),
        'updated_at',clock_timestamp()
    );
    PERFORM shared_identity.append_formal_record_v1(
        'financial.db','financial_security',v_security_id::text,
        p_stable_key,'entity',v_payload
    );
    v_row_sha := encode(sha256(convert_to(v_payload::text,'UTF8')),'hex');
    INSERT INTO shared_identity.record_revision_audit(
        operation_scope,idempotency_key,request_sha256,source_database,
        source_table,legacy_id,action,from_revision,to_revision,
        previous_row_sha256,replacement_row_sha256,previous_payload,
        replacement_payload,actor
    ) VALUES (
        v_operation_scope,p_idempotency_key,v_request_sha,'financial.db',
        'financial_security',v_security_id::text,'create',0,1,NULL,v_row_sha,
        NULL,v_payload,p_actor
    );
    v_added := v_added + 1;
    v_payload := jsonb_build_object(
        'research_company_id',v_company_id,'security_id',v_security_id,
        'link_role','canonical','created_at',clock_timestamp(),
        'updated_at',clock_timestamp()
    );
    PERFORM shared_identity.append_formal_record_v1(
        'financial.db','financial_security_company_link',v_company_id::text,
        'shared-identity:financial.db:financial_security_company_link:' || v_company_id,
        'mapping',v_payload
    );
    v_row_sha := encode(sha256(convert_to(v_payload::text,'UTF8')),'hex');
    INSERT INTO shared_identity.record_revision_audit(
        operation_scope,idempotency_key,request_sha256,source_database,
        source_table,legacy_id,action,from_revision,to_revision,
        previous_row_sha256,replacement_row_sha256,previous_payload,
        replacement_payload,actor
    ) VALUES (
        v_operation_scope,p_idempotency_key,v_request_sha,'financial.db',
        'financial_security_company_link',v_company_id::text,'create',0,1,
        NULL,v_row_sha,NULL,v_payload,p_actor
    );
    v_added := v_added + 1;
    FOR v_alias IN
        SELECT DISTINCT btrim(value)
          FROM jsonb_array_elements_text(p_company->'aliases')
         WHERE nullif(btrim(value),'') IS NOT NULL
        UNION SELECT btrim(p_company->>'name')
    LOOP
        v_alias_id := shared_identity.next_legacy_identity_v1(
            'research.db','company_identity_alias'
        );
        v_payload := jsonb_build_object(
            'id',v_alias_id,'canonical_company_id',v_company_id,
            'alias',v_alias,'alias_type','verified_name',
            'source',btrim(p_company->>'verification_source_ref'),
            'created_at',clock_timestamp()
        );
        PERFORM shared_identity.append_formal_record_v1(
            'research.db','company_identity_alias',v_alias_id::text,
            'shared-identity:research.db:company_identity_alias:' || v_alias_id,
            'mapping',v_payload
        );
        v_row_sha := encode(sha256(convert_to(v_payload::text,'UTF8')),'hex');
        INSERT INTO shared_identity.record_revision_audit(
            operation_scope,idempotency_key,request_sha256,source_database,
            source_table,legacy_id,action,from_revision,to_revision,
            previous_row_sha256,replacement_row_sha256,previous_payload,
            replacement_payload,actor
        ) VALUES (
            v_operation_scope,p_idempotency_key,v_request_sha,'research.db',
            'company_identity_alias',v_alias_id::text,'create',0,1,NULL,v_row_sha,
            NULL,v_payload,p_actor
        );
        v_added := v_added + 1;
    END LOOP;
    v_result := jsonb_build_object(
        'company_id',v_company_id,'financial_security_id',v_security_id,
        'stable_key',p_stable_key,'created',true,'records_added',v_added
    );
    RETURN shared_identity.record_mutation_v1(
        v_operation_scope,p_idempotency_key,v_request_sha,p_stable_key,
        'create',p_actor,v_result,v_added
    );
END;
$$;

CREATE OR REPLACE FUNCTION shared_identity.complete_company_identity_v2(
    p_company jsonb,
    p_stable_key text,
    p_idempotency_key text,
    p_writer_identity text,
    p_authority_state text,
    p_cutover_epoch text,
    p_approval_reference text,
    p_state_revision bigint,
    p_actor text
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, shared_identity, operations
AS $$
DECLARE
    v_existing shared_identity.mutation_result%ROWTYPE;
    v_authority operations.cutover_unit_authority%ROWTYPE;
    v_record shared_identity.legacy_record%ROWTYPE;
    v_company_id bigint;
    v_matches bigint;
    v_replacement jsonb;
    v_row_sha text;
    v_request_sha text;
    v_result jsonb;
    v_updated boolean := false;
    v_operation_scope constant text := 'shared_identity.complete_company_identity_v2';
BEGIN
    IF jsonb_typeof(p_company) <> 'object'
       OR EXISTS (
           SELECT 1 FROM jsonb_object_keys(p_company) AS item(key)
            WHERE item.key NOT IN (
                'id','previous_name','name','ticker','market','listing_status',
                'verification_source_ref'
            )
       )
       OR jsonb_typeof(p_company->'id') IS DISTINCT FROM 'number'
       OR nullif(btrim(p_company->>'previous_name'),'') IS NULL
       OR nullif(btrim(p_company->>'name'),'') IS NULL
       OR nullif(btrim(p_company->>'ticker'),'') IS NULL
       OR nullif(btrim(p_company->>'market'),'') IS NULL
       OR nullif(btrim(p_company->>'listing_status'),'') IS NULL
       OR nullif(btrim(p_company->>'verification_source_ref'),'') IS NULL
       OR nullif(btrim(p_stable_key),'') IS NULL
       OR nullif(btrim(p_idempotency_key),'') IS NULL
       OR nullif(btrim(p_writer_identity),'') IS NULL
       OR nullif(btrim(p_authority_state),'') IS NULL
       OR nullif(btrim(p_cutover_epoch),'') IS NULL
       OR nullif(btrim(p_approval_reference),'') IS NULL
       OR p_state_revision IS NULL
       OR nullif(btrim(p_actor),'') IS NULL THEN
        RAISE EXCEPTION 'company identity completion input is incomplete'
            USING ERRCODE='22023';
    END IF;
    v_company_id := (p_company->>'id')::bigint;
    IF v_company_id <= 0 THEN
        RAISE EXCEPTION 'company identity completion id is invalid'
            USING ERRCODE='22023';
    END IF;
    v_request_sha := encode(sha256(convert_to(
        jsonb_build_object(
            'actor',p_actor,'company',p_company,'stable_key',p_stable_key
        )::text,'UTF8'
    )),'hex');
    PERFORM pg_advisory_xact_lock(hashtextextended(
        v_operation_scope || ':' || p_idempotency_key, 0
    ));
    v_authority := shared_identity.assert_formal_writer_v1(p_writer_identity);
    IF NOT pg_has_role(session_user,p_writer_identity,'MEMBER')
       OR v_authority.state IS DISTINCT FROM p_authority_state
       OR v_authority.cutover_epoch IS DISTINCT FROM p_cutover_epoch
       OR v_authority.approval_reference IS DISTINCT FROM p_approval_reference
       OR v_authority.state_revision IS DISTINCT FROM p_state_revision THEN
        RAISE EXCEPTION 'company identity completion authority token is stale or incomplete'
            USING ERRCODE='42501';
    END IF;
    SELECT * INTO v_existing
      FROM shared_identity.mutation_result
     WHERE operation_scope=v_operation_scope
       AND idempotency_key=p_idempotency_key;
    IF FOUND THEN
        IF v_existing.request_sha256 IS DISTINCT FROM v_request_sha THEN
            RAISE EXCEPTION 'company identity completion idempotency conflict'
                USING ERRCODE='23505';
        END IF;
        RETURN v_existing.result_payload;
    END IF;

    SELECT count(*) INTO v_matches
      FROM shared_identity.legacy_record
     WHERE source_database='research.db' AND source_table='company'
       AND formal_business_data=true AND payload->>'id'=v_company_id::text;
    IF v_matches <> 1 THEN
        RAISE EXCEPTION 'company payload id is missing or ambiguous: %', v_company_id
            USING ERRCODE='23503';
    END IF;
    SELECT * INTO v_record
      FROM shared_identity.legacy_record
     WHERE source_database='research.db' AND source_table='company'
       AND legacy_id=v_company_id::text AND formal_business_data=true
     FOR UPDATE;
    IF NOT FOUND
       OR v_record.payload->>'id' IS DISTINCT FROM v_company_id::text
       OR v_record.payload->>'name' IS DISTINCT FROM p_company->>'previous_name'
       OR v_record.stable_key IS DISTINCT FROM p_stable_key THEN
        RAISE EXCEPTION 'company formal identity does not match completion precondition: %', v_company_id
            USING ERRCODE='23503';
    END IF;
    IF EXISTS (
        SELECT 1 FROM shared_identity.legacy_record
         WHERE source_database='research.db' AND source_table='company'
           AND formal_business_data=true AND legacy_id <> v_company_id::text
           AND upper(btrim(payload->>'ticker'))=upper(btrim(p_company->>'ticker'))
           AND lower(btrim(payload->>'market'))=lower(btrim(p_company->>'market'))
    ) THEN
        RAISE EXCEPTION 'company security identity conflicts with another formal company'
            USING ERRCODE='23505';
    END IF;
    v_replacement := v_record.payload || jsonb_build_object(
        'name',btrim(p_company->>'name'),
        'ticker',upper(btrim(p_company->>'ticker')),
        'market',btrim(p_company->>'market'),
        'listing_status',btrim(p_company->>'listing_status'),
        'identity_verification_source',btrim(p_company->>'verification_source_ref')
    );
    IF v_replacement <> v_record.payload THEN
        v_row_sha := encode(sha256(convert_to(v_replacement::text,'UTF8')),'hex');
        INSERT INTO shared_identity.record_revision_audit(
            operation_scope,idempotency_key,request_sha256,source_database,
            source_table,legacy_id,action,from_revision,to_revision,
            previous_row_sha256,replacement_row_sha256,previous_payload,
            replacement_payload,actor
        ) VALUES (
            v_operation_scope,p_idempotency_key,v_request_sha,
            v_record.source_database,v_record.source_table,v_record.legacy_id,
            'update',v_record.revision,v_record.revision+1,
            v_record.row_sha256,v_row_sha,v_record.payload,v_replacement,p_actor
        );
        UPDATE shared_identity.legacy_record SET
            payload=v_replacement,row_sha256=v_row_sha,
            revision=revision+1,promoted_at=clock_timestamp()
         WHERE source_database=v_record.source_database
           AND source_table=v_record.source_table
           AND legacy_id=v_record.legacy_id;
        v_updated := true;
    END IF;
    v_result := jsonb_build_object(
        'company_id',v_company_id,'stable_key',p_stable_key,'updated',v_updated
    );
    RETURN shared_identity.record_mutation_v1(
        v_operation_scope,p_idempotency_key,v_request_sha,p_stable_key,
        'complete_identity',p_actor,v_result,0
    );
END;
$$;

CREATE OR REPLACE FUNCTION shared_identity.apply_company_profile_batch_v1(
    p_batch jsonb,
    p_idempotency_key text,
    p_writer_identity text,
    p_authority_state text,
    p_cutover_epoch text,
    p_approval_reference text,
    p_state_revision bigint,
    p_actor text
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, shared_identity, operations
AS $$
DECLARE
    v_existing shared_identity.mutation_result%ROWTYPE;
    v_authority operations.cutover_unit_authority%ROWTYPE;
    v_record shared_identity.legacy_record%ROWTYPE;
    v_row jsonb;
    v_replacement jsonb;
    v_result jsonb;
    v_industry_id bigint;
    v_industry_name text;
    v_company_id bigint;
    v_legacy_id bigint;
    v_matches bigint;
    v_company_count bigint := 0;
    v_relationship_count bigint := 0;
    v_profile_count bigint := 0;
    v_added bigint := 0;
    v_row_sha text;
    v_request_sha text;
    v_update_ids bigint[];
    v_relationship_ids bigint[];
    v_profile_ids bigint[];
    v_update_total bigint;
    v_relationship_total bigint;
    v_profile_total bigint;
    v_operation_scope constant text := 'shared_identity.apply_company_profile_batch_v1';
BEGIN
    IF jsonb_typeof(p_batch) <> 'object'
       OR jsonb_typeof(p_batch->'company_updates') <> 'array'
       OR jsonb_typeof(p_batch->'company_industry') <> 'array'
       OR jsonb_typeof(p_batch->'company_profiles') <> 'array'
       OR jsonb_array_length(p_batch->'company_updates') NOT BETWEEN 1 AND 100
       OR jsonb_array_length(p_batch->'company_industry') NOT BETWEEN 1 AND 100
       OR jsonb_array_length(p_batch->'company_profiles') NOT BETWEEN 1 AND 100
       OR coalesce(p_batch->>'source_mapping_sha256','') !~ '^[0-9a-f]{64}$'
       OR nullif(btrim(p_idempotency_key),'') IS NULL
       OR nullif(btrim(p_actor),'') IS NULL
       OR nullif(btrim(p_writer_identity),'') IS NULL
       OR nullif(btrim(p_authority_state),'') IS NULL
       OR nullif(btrim(p_cutover_epoch),'') IS NULL
       OR nullif(btrim(p_approval_reference),'') IS NULL
       OR p_state_revision IS NULL THEN
        RAISE EXCEPTION 'company profile batch identity or bounds are invalid'
            USING ERRCODE='22023';
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_object_keys(p_batch) AS item(key)
         WHERE item.key NOT IN (
             'industry_id','industry_name','company_updates',
             'company_industry','company_profiles','source_mapping_sha256'
         )
    ) THEN
        RAISE EXCEPTION 'company profile batch contains unsupported fields'
            USING ERRCODE='22023';
    END IF;
    v_request_sha := encode(sha256(convert_to(
        jsonb_build_object('actor',p_actor,'batch',p_batch)::text,'UTF8'
    )),'hex');

    PERFORM pg_advisory_xact_lock(hashtextextended(
        v_operation_scope || ':' || p_idempotency_key, 0
    ));
    v_authority := shared_identity.assert_formal_writer_v1(p_writer_identity);
    IF NOT pg_has_role(session_user,p_writer_identity,'MEMBER')
       OR v_authority.state IS DISTINCT FROM p_authority_state
       OR v_authority.cutover_epoch IS DISTINCT FROM p_cutover_epoch
       OR v_authority.approval_reference IS DISTINCT FROM p_approval_reference
       OR v_authority.state_revision IS DISTINCT FROM p_state_revision THEN
        RAISE EXCEPTION 'company profile batch authority token is stale or incomplete'
            USING ERRCODE='42501';
    END IF;

    SELECT * INTO v_existing
      FROM shared_identity.mutation_result
     WHERE operation_scope=v_operation_scope
       AND idempotency_key=p_idempotency_key;
    IF FOUND THEN
        IF v_existing.request_sha256 IS DISTINCT FROM v_request_sha THEN
            RAISE EXCEPTION 'company profile batch idempotency conflict'
                USING ERRCODE='23505';
        END IF;
        RETURN v_existing.result_payload;
    END IF;

    v_industry_id := (p_batch->>'industry_id')::bigint;
    v_industry_name := btrim(p_batch->>'industry_name');
    SELECT count(*) INTO v_matches
      FROM shared_identity.legacy_record
     WHERE source_database='research.db' AND source_table='industry'
       AND formal_business_data=true
       AND legacy_id=v_industry_id::text
       AND payload->>'id'=v_industry_id::text
       AND payload->>'name'=v_industry_name;
    IF v_matches <> 1 THEN
        RAISE EXCEPTION 'company profile batch industry identity is missing or ambiguous'
            USING ERRCODE='23503';
    END IF;

    SELECT array_agg((value->>'id')::bigint ORDER BY (value->>'id')::bigint),
           count(*)
      INTO v_update_ids,v_update_total
      FROM jsonb_array_elements(p_batch->'company_updates');
    SELECT array_agg((value->>'company_id')::bigint ORDER BY (value->>'company_id')::bigint),
           count(*)
      INTO v_relationship_ids,v_relationship_total
      FROM jsonb_array_elements(p_batch->'company_industry');
    SELECT array_agg((value->>'company_id')::bigint ORDER BY (value->>'company_id')::bigint),
           count(*)
      INTO v_profile_ids,v_profile_total
      FROM jsonb_array_elements(p_batch->'company_profiles');
    IF cardinality(v_update_ids) <> cardinality(ARRAY(SELECT DISTINCT unnest(v_update_ids)))
       OR cardinality(v_relationship_ids) <> cardinality(ARRAY(SELECT DISTINCT unnest(v_relationship_ids)))
       OR cardinality(v_profile_ids) <> cardinality(ARRAY(SELECT DISTINCT unnest(v_profile_ids)))
       OR v_update_ids <> v_relationship_ids OR v_update_ids <> v_profile_ids
       OR v_update_total <> v_relationship_total OR v_update_total <> v_profile_total THEN
        RAISE EXCEPTION 'company profile batch company sets are duplicated or inconsistent'
            USING ERRCODE='22023';
    END IF;

    FOR v_row IN SELECT value FROM jsonb_array_elements(p_batch->'company_updates') LOOP
        IF EXISTS (
            SELECT 1 FROM jsonb_object_keys(v_row) AS item(key)
             WHERE item.key NOT IN (
                 'id','name','stored_name','stable_key','brief_intro','brief_intro_src'
             )
        ) OR jsonb_typeof(v_row->'id') IS DISTINCT FROM 'number'
          OR nullif(btrim(v_row->>'name'),'') IS NULL
          OR nullif(btrim(v_row->>'stored_name'),'') IS NULL
          OR nullif(btrim(v_row->>'stable_key'),'') IS NULL
          OR nullif(btrim(v_row->>'brief_intro'),'') IS NULL THEN
            RAISE EXCEPTION 'company update contains unsupported or incomplete fields'
                USING ERRCODE='22023';
        END IF;
        v_company_id := (v_row->>'id')::bigint;
        SELECT count(*) INTO v_matches
          FROM shared_identity.legacy_record
         WHERE source_database='research.db' AND source_table='company'
           AND formal_business_data=true
           AND legacy_id=v_company_id::text
           AND payload->>'id'=v_company_id::text
           AND payload->>'name'=v_row->>'stored_name'
           AND stable_key=v_row->>'stable_key';
        IF v_matches <> 1 THEN
            RAISE EXCEPTION 'company identity is missing or ambiguous: %', v_company_id
                USING ERRCODE='23503';
        END IF;
        SELECT count(*) INTO v_matches
          FROM shared_identity.legacy_record
         WHERE source_database='research.db' AND source_table='company'
           AND formal_business_data=true
           AND payload->>'id'=v_company_id::text;
        IF v_matches <> 1 THEN
            RAISE EXCEPTION 'company payload id is missing or ambiguous: %', v_company_id
                USING ERRCODE='23503';
        END IF;
        SELECT * INTO v_record
          FROM shared_identity.legacy_record
         WHERE source_database='research.db' AND source_table='company'
           AND formal_business_data=true
           AND legacy_id=v_company_id::text
           AND payload->>'id'=v_company_id::text
           AND payload->>'name'=v_row->>'stored_name'
           AND stable_key=v_row->>'stable_key'
         FOR UPDATE;
        v_replacement := v_record.payload || jsonb_build_object(
            'brief_intro',v_row->'brief_intro',
            'brief_intro_src',v_row->'brief_intro_src'
        );
        IF v_replacement <> v_record.payload THEN
            v_row_sha := encode(sha256(convert_to(v_replacement::text,'UTF8')),'hex');
            INSERT INTO shared_identity.record_revision_audit(
                operation_scope,idempotency_key,request_sha256,source_database,
                source_table,legacy_id,action,from_revision,to_revision,
                previous_row_sha256,replacement_row_sha256,previous_payload,
                replacement_payload,actor
            ) VALUES (
                v_operation_scope,p_idempotency_key,v_request_sha,
                v_record.source_database,v_record.source_table,v_record.legacy_id,
                'update',v_record.revision,v_record.revision+1,v_record.row_sha256,
                v_row_sha,v_record.payload,v_replacement,p_actor
            );
            UPDATE shared_identity.legacy_record SET
                payload=v_replacement,row_sha256=v_row_sha,
                revision=revision+1,promoted_at=clock_timestamp()
             WHERE source_database=v_record.source_database
               AND source_table=v_record.source_table
               AND legacy_id=v_record.legacy_id;
        END IF;
        v_company_count := v_company_count + 1;
    END LOOP;

    FOR v_row IN SELECT value FROM jsonb_array_elements(p_batch->'company_industry') LOOP
        IF EXISTS (
            SELECT 1 FROM jsonb_object_keys(v_row) AS item(key)
             WHERE item.key NOT IN ('company_id','industry_id','role','revenue_share','note')
        ) OR jsonb_typeof(v_row->'company_id') IS DISTINCT FROM 'number'
          OR jsonb_typeof(v_row->'industry_id') IS DISTINCT FROM 'number'
          OR (v_row->>'industry_id')::bigint IS DISTINCT FROM v_industry_id
          OR nullif(btrim(v_row->>'role'),'') IS NULL
          OR nullif(btrim(v_row->>'note'),'') IS NULL THEN
            RAISE EXCEPTION 'company-industry row contains unsupported or incomplete fields'
                USING ERRCODE='22023';
        END IF;
        v_company_id := (v_row->>'company_id')::bigint;
        SELECT count(*) INTO v_matches
          FROM shared_identity.legacy_record
         WHERE source_database='research.db' AND source_table='company_industry'
           AND formal_business_data=true
           AND (payload->>'company_id')::bigint=v_company_id
           AND (payload->>'industry_id')::bigint=v_industry_id;
        IF v_matches > 1 THEN
            RAISE EXCEPTION 'duplicate company-industry identity: %', v_company_id
                USING ERRCODE='23505';
        ELSIF v_matches = 1 THEN
            SELECT * INTO v_record
              FROM shared_identity.legacy_record
             WHERE source_database='research.db' AND source_table='company_industry'
               AND formal_business_data=true
               AND (payload->>'company_id')::bigint=v_company_id
               AND (payload->>'industry_id')::bigint=v_industry_id
             FOR UPDATE;
            v_replacement := v_record.payload || (v_row - 'company_id' - 'industry_id');
            IF v_replacement <> v_record.payload THEN
                v_row_sha := encode(sha256(convert_to(v_replacement::text,'UTF8')),'hex');
                INSERT INTO shared_identity.record_revision_audit(
                    operation_scope,idempotency_key,request_sha256,source_database,
                    source_table,legacy_id,action,from_revision,to_revision,
                    previous_row_sha256,replacement_row_sha256,previous_payload,
                    replacement_payload,actor
                ) VALUES (
                    v_operation_scope,p_idempotency_key,v_request_sha,
                    v_record.source_database,v_record.source_table,v_record.legacy_id,
                    'update',v_record.revision,v_record.revision+1,v_record.row_sha256,
                    v_row_sha,v_record.payload,v_replacement,p_actor
                );
                UPDATE shared_identity.legacy_record SET
                    payload=v_replacement,row_sha256=v_row_sha,
                    revision=revision+1,promoted_at=clock_timestamp()
                 WHERE source_database=v_record.source_database
                   AND source_table=v_record.source_table
                   AND legacy_id=v_record.legacy_id;
            END IF;
        ELSE
            PERFORM pg_advisory_xact_lock(hashtextextended(
                'shared_identity:research.db:company_industry', 0
            ));
            SELECT COALESCE(max(legacy_id::bigint),0)+1 INTO v_legacy_id
              FROM shared_identity.legacy_record
             WHERE source_database='research.db' AND source_table='company_industry'
               AND legacy_id ~ '^[0-9]+$';
            v_replacement := v_row || jsonb_build_object('id',v_legacy_id);
            PERFORM shared_identity.append_formal_record_v1(
                'research.db','company_industry',v_legacy_id::text,
                'shared-identity:research.db:company_industry:' || v_legacy_id,
                'relationship',v_replacement
            );
            v_row_sha := encode(sha256(convert_to(v_replacement::text,'UTF8')),'hex');
            INSERT INTO shared_identity.record_revision_audit(
                operation_scope,idempotency_key,request_sha256,source_database,
                source_table,legacy_id,action,from_revision,to_revision,
                previous_row_sha256,replacement_row_sha256,previous_payload,
                replacement_payload,actor
            ) VALUES (
                v_operation_scope,p_idempotency_key,v_request_sha,
                'research.db','company_industry',v_legacy_id::text,'create',0,1,
                NULL,v_row_sha,NULL,v_replacement,p_actor
            );
            v_added := v_added + 1;
        END IF;
        v_relationship_count := v_relationship_count + 1;
    END LOOP;

    FOR v_row IN SELECT value FROM jsonb_array_elements(p_batch->'company_profiles') LOOP
        IF EXISTS (
            SELECT 1 FROM jsonb_object_keys(v_row) AS item(key)
             WHERE item.key NOT IN (
                 'brief_intro','brief_intro_src','capex_unit','capex_value',
                 'china_rank','china_share','china_share_as_of','china_share_sub_market',
                 'company_id','created_at','customer_concentration','display_note',
                 'financials_as_of','global_rank','global_share','global_share_as_of',
                 'global_share_sub_market','gross_margin','in_china_table','in_global_table',
                 'industry_id','is_china_tech_leader','last_updated','last_verified_at',
                 'listing_status','main_customers','main_customers_src_id','main_products',
                 'net_income_series','net_margin','ocf_unit','operating_cash_flow','period',
                 'private_round','private_valuation_as_of','private_valuation_unit',
                 'private_valuation_value','rd_expense_ratio','recent_events','revenue_series',
                 'revenue_share_in_industry','risks','share_rank_change','source_ids','summary',
                 'tech_node','tech_node_src_id'
             )
        ) OR jsonb_typeof(v_row->'company_id') IS DISTINCT FROM 'number'
          OR jsonb_typeof(v_row->'industry_id') IS DISTINCT FROM 'number'
          OR (v_row->>'industry_id')::bigint IS DISTINCT FROM v_industry_id
          OR nullif(btrim(v_row->>'summary'),'') IS NULL
          OR nullif(btrim(v_row->>'period'),'') IS NULL
          OR NOT (v_row ? 'source_ids')
          OR jsonb_typeof(v_row->'source_ids') IS DISTINCT FROM 'string'
          OR jsonb_typeof((v_row->>'source_ids')::jsonb) IS DISTINCT FROM 'array'
          OR jsonb_array_length((v_row->>'source_ids')::jsonb) < 1
          OR EXISTS (
              SELECT 1 FROM jsonb_array_elements_text((v_row->>'source_ids')::jsonb) AS source_id(value)
               WHERE source_id.value !~ '^[0-9]+$' OR source_id.value::bigint <= 0
          )
          OR jsonb_typeof(v_row->'brief_intro_src') IS DISTINCT FROM 'number'
          OR (v_row->>'brief_intro_src')::bigint <= 0
          OR EXISTS (
              SELECT 1 FROM (VALUES
                  ('in_china_table'),('in_global_table'),
                  ('is_china_tech_leader')
              ) AS boolean_field(name)
               WHERE jsonb_typeof(v_row->boolean_field.name) IS DISTINCT FROM 'number'
                  OR (v_row->>boolean_field.name)::integer NOT IN (0,1)
          )
          OR (
              v_row ? 'private_round'
              AND v_row->'private_round' <> 'null'::jsonb
              AND (
                  jsonb_typeof(v_row->'private_round') IS DISTINCT FROM 'number'
                  OR (v_row->>'private_round')::integer NOT IN (0,1)
              )
          )
          OR EXISTS (
              SELECT 1 FROM (VALUES
                  ('capex_value'),('china_rank'),('china_share'),('global_rank'),
                  ('global_share'),('gross_margin'),('net_margin'),
                  ('operating_cash_flow'),('private_valuation_value'),
                  ('rd_expense_ratio'),('revenue_share_in_industry'),
                  ('share_rank_change')
              ) AS numeric_field(name)
               WHERE v_row ? numeric_field.name
                 AND v_row->numeric_field.name <> 'null'::jsonb
                 AND jsonb_typeof(v_row->numeric_field.name) IS DISTINCT FROM 'number'
          )
          OR EXISTS (
              SELECT 1 FROM (VALUES
                  ('china_share_as_of'),('global_share_as_of'),('financials_as_of'),
                  ('last_updated'),('last_verified_at'),('private_valuation_as_of')
              ) AS date_field(name)
               WHERE v_row ? date_field.name
                 AND v_row->date_field.name <> 'null'::jsonb
                 AND (
                     jsonb_typeof(v_row->date_field.name) IS DISTINCT FROM 'string'
                     OR v_row->>date_field.name !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                 )
          )
          OR EXISTS (
              SELECT 1 FROM (VALUES
                  ('revenue_series'),('net_income_series'),('recent_events'),('risks')
              ) AS series_field(name)
               WHERE NOT (v_row ? series_field.name)
                  OR jsonb_typeof(v_row->series_field.name) IS DISTINCT FROM 'string'
                  OR jsonb_typeof((v_row->>series_field.name)::jsonb) IS DISTINCT FROM 'array'
                  OR jsonb_array_length((v_row->>series_field.name)::jsonb) < 1
          ) THEN
            RAISE EXCEPTION 'company profile row contains unsupported or incomplete fields'
                USING ERRCODE='22023';
        END IF;
        v_company_id := (v_row->>'company_id')::bigint;
        SELECT count(*) INTO v_matches
          FROM shared_identity.legacy_record
         WHERE source_database='research.db' AND source_table='company_profile'
           AND formal_business_data=true
           AND (payload->>'company_id')::bigint=v_company_id
           AND (payload->>'industry_id')::bigint=v_industry_id;
        IF v_matches > 1 THEN
            RAISE EXCEPTION 'duplicate company profile identity: %', v_company_id
                USING ERRCODE='23505';
        ELSIF v_matches = 1 THEN
            SELECT * INTO v_record
              FROM shared_identity.legacy_record
             WHERE source_database='research.db' AND source_table='company_profile'
               AND formal_business_data=true
               AND (payload->>'company_id')::bigint=v_company_id
               AND (payload->>'industry_id')::bigint=v_industry_id
             FOR UPDATE;
            v_replacement := v_record.payload || v_row;
            IF v_replacement <> v_record.payload THEN
                v_row_sha := encode(sha256(convert_to(v_replacement::text,'UTF8')),'hex');
                INSERT INTO shared_identity.record_revision_audit(
                    operation_scope,idempotency_key,request_sha256,source_database,
                    source_table,legacy_id,action,from_revision,to_revision,
                    previous_row_sha256,replacement_row_sha256,previous_payload,
                    replacement_payload,actor
                ) VALUES (
                    v_operation_scope,p_idempotency_key,v_request_sha,
                    v_record.source_database,v_record.source_table,v_record.legacy_id,
                    'update',v_record.revision,v_record.revision+1,v_record.row_sha256,
                    v_row_sha,v_record.payload,v_replacement,p_actor
                );
                UPDATE shared_identity.legacy_record SET
                    payload=v_replacement,row_sha256=v_row_sha,
                    revision=revision+1,promoted_at=clock_timestamp()
                 WHERE source_database=v_record.source_database
                   AND source_table=v_record.source_table
                   AND legacy_id=v_record.legacy_id;
            END IF;
        ELSE
            PERFORM pg_advisory_xact_lock(hashtextextended(
                'shared_identity:research.db:company_profile', 0
            ));
            SELECT COALESCE(max(legacy_id::bigint),0)+1 INTO v_legacy_id
              FROM shared_identity.legacy_record
             WHERE source_database='research.db' AND source_table='company_profile'
               AND legacy_id ~ '^[0-9]+$';
            v_replacement := v_row || jsonb_build_object('id',v_legacy_id);
            PERFORM shared_identity.append_formal_record_v1(
                'research.db','company_profile',v_legacy_id::text,
                'shared-identity:research.db:company_profile:' || v_legacy_id,
                'profile',v_replacement
            );
            v_row_sha := encode(sha256(convert_to(v_replacement::text,'UTF8')),'hex');
            INSERT INTO shared_identity.record_revision_audit(
                operation_scope,idempotency_key,request_sha256,source_database,
                source_table,legacy_id,action,from_revision,to_revision,
                previous_row_sha256,replacement_row_sha256,previous_payload,
                replacement_payload,actor
            ) VALUES (
                v_operation_scope,p_idempotency_key,v_request_sha,
                'research.db','company_profile',v_legacy_id::text,'create',0,1,
                NULL,v_row_sha,NULL,v_replacement,p_actor
            );
            v_added := v_added + 1;
        END IF;
        v_profile_count := v_profile_count + 1;
    END LOOP;

    v_result := jsonb_build_object(
        'industry_id',v_industry_id,'company_updates',v_company_count,
        'company_industry',v_relationship_count,'company_profiles',v_profile_count,
        'records_added',v_added,
        'source_mapping_sha256',p_batch->>'source_mapping_sha256'
    );
    RETURN shared_identity.record_mutation_v1(
        v_operation_scope,p_idempotency_key,v_request_sha,
        'industry:' || v_industry_id || ':company-profiles',
        'upsert_company_profile_batch',p_actor,v_result,v_added
    );
END;
$$;

REVOKE ALL ON shared_identity.record_revision_audit FROM PUBLIC;
REVOKE ALL ON FUNCTION shared_identity.ensure_industry_v1(
    jsonb,text,text,text,text,text,text,bigint,text
) FROM PUBLIC;
REVOKE ALL ON FUNCTION shared_identity.apply_company_profile_batch_v1(
    jsonb,text,text,text,text,text,bigint,text
) FROM PUBLIC;
REVOKE ALL ON FUNCTION shared_identity.ensure_listed_company_v2(
    jsonb,text,text,text,text,text,text,bigint,text
) FROM PUBLIC;
REVOKE ALL ON FUNCTION shared_identity.complete_company_identity_v2(
    jsonb,text,text,text,text,text,text,bigint,text
) FROM PUBLIC;
GRANT SELECT ON shared_identity.record_revision_audit TO :"audit_reader_role";
GRANT EXECUTE ON FUNCTION shared_identity.ensure_industry_v1(
    jsonb,text,text,text,text,text,text,bigint,text
) TO :"writer_role";
GRANT EXECUTE ON FUNCTION shared_identity.apply_company_profile_batch_v1(
    jsonb,text,text,text,text,text,bigint,text
) TO :"writer_role";
GRANT EXECUTE ON FUNCTION shared_identity.ensure_listed_company_v2(
    jsonb,text,text,text,text,text,text,bigint,text
) TO :"writer_role";
GRANT EXECUTE ON FUNCTION shared_identity.complete_company_identity_v2(
    jsonb,text,text,text,text,text,text,bigint,text
) TO :"writer_role";

INSERT INTO operations.schema_migration(migration_id,migration_sha256,phase,forward_only)
VALUES('0019_shared_identity_company_profile_batch',:'migration_sha256','expand',false)
ON CONFLICT(migration_id) DO NOTHING;
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM operations.schema_migration
         WHERE migration_id='0019_shared_identity_company_profile_batch'
           AND migration_sha256=current_setting('honghu.migration_sha256')
    ) THEN
        RAISE EXCEPTION 'migration identity exists with a different SHA256';
    END IF;
END $$;

COMMIT;
