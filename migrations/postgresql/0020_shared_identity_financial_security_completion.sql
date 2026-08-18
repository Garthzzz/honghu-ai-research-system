\set ON_ERROR_STOP on

BEGIN;
SELECT set_config('honghu.migration_sha256', :'migration_sha256', true);

CREATE OR REPLACE FUNCTION shared_identity.complete_company_identity_v3(
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
    v_company shared_identity.legacy_record%ROWTYPE;
    v_security shared_identity.legacy_record%ROWTYPE;
    v_link shared_identity.legacy_record%ROWTYPE;
    v_company_id bigint;
    v_security_id bigint;
    v_matches bigint;
    v_replacement jsonb;
    v_row_sha text;
    v_request_sha text;
    v_result jsonb;
    v_company_updated boolean := false;
    v_security_updated boolean := false;
    v_operation_scope constant text := 'shared_identity.complete_company_identity_v3';
BEGIN
    IF jsonb_typeof(p_company) <> 'object'
       OR EXISTS (
           SELECT 1 FROM jsonb_object_keys(p_company) AS item(key)
            WHERE item.key NOT IN (
                'id','previous_name','name','ticker','market','listing_status',
                'financial_market','financial_listing_status','reporting_currency',
                'name_en','fiscal_year_end','verification_source_ref'
            )
       )
       OR jsonb_typeof(p_company->'id') IS DISTINCT FROM 'number'
       OR nullif(btrim(p_company->>'previous_name'),'') IS NULL
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
        RAISE EXCEPTION 'company and financial identity completion input is incomplete'
            USING ERRCODE='22023';
    END IF;
    v_company_id := (p_company->>'id')::bigint;
    IF v_company_id <= 0 THEN
        RAISE EXCEPTION 'company identity completion id is invalid'
            USING ERRCODE='22023';
    END IF;
    v_request_sha := encode(sha256(convert_to(
        jsonb_build_object(
            'actor',p_actor,
            'company',p_company - 'previous_name',
            'stable_key',p_stable_key
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
    SELECT * INTO v_company
      FROM shared_identity.legacy_record
     WHERE source_database='research.db' AND source_table='company'
       AND legacy_id=v_company_id::text AND formal_business_data=true
     FOR UPDATE;
    IF NOT FOUND
       OR v_company.payload->>'id' IS DISTINCT FROM v_company_id::text
       OR v_company.payload->>'name' IS DISTINCT FROM p_company->>'previous_name'
       OR v_company.stable_key IS DISTINCT FROM p_stable_key THEN
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
    v_replacement := v_company.payload || jsonb_build_object(
        'name',btrim(p_company->>'name'),
        'ticker',upper(btrim(p_company->>'ticker')),
        'market',btrim(p_company->>'market'),
        'listing_status',btrim(p_company->>'listing_status'),
        'identity_verification_source',btrim(p_company->>'verification_source_ref')
    );
    IF v_replacement <> v_company.payload THEN
        v_row_sha := encode(sha256(convert_to(v_replacement::text,'UTF8')),'hex');
        INSERT INTO shared_identity.record_revision_audit(
            operation_scope,idempotency_key,request_sha256,source_database,
            source_table,legacy_id,action,from_revision,to_revision,
            previous_row_sha256,replacement_row_sha256,previous_payload,
            replacement_payload,actor
        ) VALUES (
            v_operation_scope,p_idempotency_key,v_request_sha,
            v_company.source_database,v_company.source_table,v_company.legacy_id,
            'update',v_company.revision,v_company.revision+1,
            v_company.row_sha256,v_row_sha,v_company.payload,v_replacement,p_actor
        );
        UPDATE shared_identity.legacy_record SET
            payload=v_replacement,row_sha256=v_row_sha,
            revision=revision+1,promoted_at=clock_timestamp()
         WHERE source_database=v_company.source_database
           AND source_table=v_company.source_table
           AND legacy_id=v_company.legacy_id;
        v_company_updated := true;
    END IF;

    SELECT count(*) INTO v_matches
      FROM shared_identity.legacy_record
     WHERE source_database='financial.db' AND source_table='financial_security'
       AND formal_business_data=true
       AND payload->>'research_company_id'=v_company_id::text;
    IF v_matches <> 1 THEN
        RAISE EXCEPTION 'financial security is missing or ambiguous: %', v_company_id
            USING ERRCODE='23503';
    END IF;
    SELECT * INTO v_security
      FROM shared_identity.legacy_record
     WHERE source_database='financial.db' AND source_table='financial_security'
       AND formal_business_data=true
       AND payload->>'research_company_id'=v_company_id::text
     FOR UPDATE;
    v_security_id := (v_security.payload->>'id')::bigint;
    IF v_security_id <= 0
       OR v_security.legacy_id IS DISTINCT FROM v_security_id::text
       OR v_security.stable_key IS DISTINCT FROM p_stable_key THEN
        RAISE EXCEPTION 'financial security identity does not match company: %', v_company_id
            USING ERRCODE='23503';
    END IF;
    IF EXISTS (
        SELECT 1 FROM shared_identity.legacy_record
         WHERE source_database='financial.db' AND source_table='financial_security'
           AND formal_business_data=true AND legacy_id <> v_security.legacy_id
           AND upper(btrim(payload->>'ticker'))=upper(btrim(p_company->>'ticker'))
           AND lower(btrim(payload->>'market'))=lower(btrim(p_company->>'financial_market'))
    ) THEN
        RAISE EXCEPTION 'financial security identity conflicts with another formal security'
            USING ERRCODE='23505';
    END IF;

    SELECT count(*) INTO v_matches
      FROM shared_identity.legacy_record
     WHERE source_database='financial.db'
       AND source_table='financial_security_company_link'
       AND formal_business_data=true
       AND payload->>'research_company_id'=v_company_id::text;
    IF v_matches <> 1 THEN
        RAISE EXCEPTION 'financial security link is missing or ambiguous: %', v_company_id
            USING ERRCODE='23503';
    END IF;
    SELECT * INTO v_link
      FROM shared_identity.legacy_record
     WHERE source_database='financial.db'
       AND source_table='financial_security_company_link'
       AND formal_business_data=true
       AND payload->>'research_company_id'=v_company_id::text
     FOR UPDATE;
    IF v_link.legacy_id IS DISTINCT FROM v_company_id::text
       OR v_link.payload->>'security_id' IS DISTINCT FROM v_security_id::text
       OR v_link.payload->>'link_role' IS DISTINCT FROM 'canonical' THEN
        RAISE EXCEPTION 'financial security link does not match company: %', v_company_id
            USING ERRCODE='23503';
    END IF;

    v_replacement := v_security.payload || jsonb_build_object(
        'research_company_id',v_company_id,
        'canonical_name',btrim(p_company->>'name'),
        'ticker',upper(btrim(p_company->>'ticker')),
        'market',btrim(p_company->>'financial_market'),
        'listing_status',btrim(p_company->>'financial_listing_status'),
        'reporting_currency',upper(btrim(p_company->>'reporting_currency')),
        'name_en',p_company->'name_en',
        'fiscal_year_end',p_company->'fiscal_year_end',
        'identity_status','verified'
    );
    IF v_replacement <> v_security.payload THEN
        v_row_sha := encode(sha256(convert_to(v_replacement::text,'UTF8')),'hex');
        INSERT INTO shared_identity.record_revision_audit(
            operation_scope,idempotency_key,request_sha256,source_database,
            source_table,legacy_id,action,from_revision,to_revision,
            previous_row_sha256,replacement_row_sha256,previous_payload,
            replacement_payload,actor
        ) VALUES (
            v_operation_scope,p_idempotency_key,v_request_sha,
            v_security.source_database,v_security.source_table,v_security.legacy_id,
            'update',v_security.revision,v_security.revision+1,
            v_security.row_sha256,v_row_sha,v_security.payload,v_replacement,p_actor
        );
        UPDATE shared_identity.legacy_record SET
            payload=v_replacement,row_sha256=v_row_sha,
            revision=revision+1,promoted_at=clock_timestamp()
         WHERE source_database=v_security.source_database
           AND source_table=v_security.source_table
           AND legacy_id=v_security.legacy_id;
        v_security_updated := true;
    END IF;

    v_result := jsonb_build_object(
        'company_id',v_company_id,'security_id',v_security_id,
        'stable_key',p_stable_key,'company_updated',v_company_updated,
        'financial_security_updated',v_security_updated
    );
    RETURN shared_identity.record_mutation_v1(
        v_operation_scope,p_idempotency_key,v_request_sha,p_stable_key,
        'complete_company_and_financial_identity',p_actor,v_result,0
    );
END;
$$;

REVOKE ALL ON FUNCTION shared_identity.complete_company_identity_v3(
    jsonb,text,text,text,text,text,text,bigint,text
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION shared_identity.complete_company_identity_v3(
    jsonb,text,text,text,text,text,text,bigint,text
) TO :"writer_role";

INSERT INTO operations.schema_migration(migration_id,migration_sha256,phase,forward_only)
VALUES('0020_shared_identity_financial_security_completion',:'migration_sha256','expand',false)
ON CONFLICT(migration_id) DO NOTHING;
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM operations.schema_migration
         WHERE migration_id='0020_shared_identity_financial_security_completion'
           AND migration_sha256=current_setting('honghu.migration_sha256')
    ) THEN
        RAISE EXCEPTION 'migration identity exists with a different SHA256';
    END IF;
END $$;

COMMIT;
