\set ON_ERROR_STOP on

BEGIN;

SELECT set_config('honghu.migration_sha256', :'migration_sha256', true);

CREATE TABLE IF NOT EXISTS shared_identity.mutation_audit (
    audit_id bigserial PRIMARY KEY,
    operation_scope text NOT NULL,
    idempotency_key text NOT NULL,
    object_key text NOT NULL,
    action text NOT NULL,
    actor text NOT NULL,
    request_sha256 text NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
    result_payload jsonb NOT NULL CHECK (jsonb_typeof(result_payload) = 'object'),
    committed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (operation_scope,idempotency_key)
);

CREATE OR REPLACE FUNCTION shared_identity.assert_formal_writer_v1(
    p_writer_identity text
) RETURNS operations.cutover_unit_authority
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, shared_identity, operations
AS $$
DECLARE
    v_authority operations.cutover_unit_authority%ROWTYPE;
BEGIN
    SELECT * INTO v_authority
      FROM operations.cutover_unit_authority
     WHERE cutover_unit='shared_identity'
     FOR UPDATE;
    IF NOT FOUND
       OR v_authority.state NOT IN ('S3','S4')
       OR v_authority.authoritative_backend <> 'postgresql_production'
       OR v_authority.writer_identity <> p_writer_identity THEN
        RAISE EXCEPTION 'shared identity writer is fenced'
            USING ERRCODE='42501';
    END IF;
    RETURN v_authority;
END;
$$;

CREATE OR REPLACE FUNCTION shared_identity.next_legacy_identity_v1(
    p_source_database text,
    p_source_table text
) RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, shared_identity
AS $$
DECLARE
    v_next bigint;
BEGIN
    IF p_source_database NOT IN ('research.db','financial.db')
       OR p_source_table NOT IN (
           'company','company_identity_alias','researcher',
           'financial_security','financial_security_company_link'
       ) THEN
        RAISE EXCEPTION 'identity allocator scope is not approved'
            USING ERRCODE='42501';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'shared_identity:' || p_source_database || ':' || p_source_table, 0
    ));
    SELECT COALESCE(max((payload->>'id')::bigint),0) + 1 INTO v_next
      FROM shared_identity.legacy_record
     WHERE source_database=p_source_database
       AND source_table=p_source_table
       AND payload ? 'id'
       AND payload->>'id' ~ '^[0-9]+$';
    RETURN v_next;
END;
$$;

CREATE OR REPLACE FUNCTION shared_identity.append_formal_record_v1(
    p_source_database text,
    p_source_table text,
    p_legacy_id text,
    p_stable_key text,
    p_record_kind text,
    p_payload jsonb
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, shared_identity
AS $$
DECLARE
    v_snapshot_id text;
    v_ordinal bigint;
    v_row_sha text;
BEGIN
    IF jsonb_typeof(p_payload) <> 'object'
       OR nullif(btrim(p_legacy_id),'') IS NULL
       OR nullif(btrim(p_stable_key),'') IS NULL THEN
        RAISE EXCEPTION 'shared identity record is incomplete' USING ERRCODE='22023';
    END IF;
    SELECT source_snapshot_id INTO v_snapshot_id
      FROM shared_identity.unit_snapshot
     WHERE cutover_unit='shared_identity'
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'shared identity formal snapshot is missing' USING ERRCODE='40001';
    END IF;
    SELECT COALESCE(max(source_ordinal),0)+1 INTO v_ordinal
      FROM shared_identity.legacy_record
     WHERE source_database=p_source_database AND source_table=p_source_table;
    v_row_sha := encode(sha256(convert_to(p_payload::text,'UTF8')),'hex');
    INSERT INTO shared_identity.legacy_record(
        source_database,source_table,legacy_id,stable_key,record_kind,
        row_sha256,payload,source_snapshot_id,source_ordinal,
        formal_business_data,revision
    ) VALUES (
        p_source_database,p_source_table,p_legacy_id,p_stable_key,p_record_kind,
        v_row_sha,p_payload,v_snapshot_id,v_ordinal,true,1
    );
END;
$$;

CREATE OR REPLACE FUNCTION shared_identity.record_mutation_v1(
    p_operation_scope text,
    p_idempotency_key text,
    p_request_sha256 text,
    p_object_key text,
    p_action text,
    p_actor text,
    p_result jsonb,
    p_added_rows bigint
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, shared_identity
AS $$
BEGIN
    INSERT INTO shared_identity.mutation_result(
        operation_scope,idempotency_key,request_sha256,object_key,result_payload
    ) VALUES (
        p_operation_scope,p_idempotency_key,p_request_sha256,p_object_key,p_result
    );
    INSERT INTO shared_identity.mutation_audit(
        operation_scope,idempotency_key,object_key,action,actor,
        request_sha256,result_payload
    ) VALUES (
        p_operation_scope,p_idempotency_key,p_object_key,p_action,p_actor,
        p_request_sha256,p_result
    );
    UPDATE shared_identity.unit_snapshot SET
        formal_revision=formal_revision+1,
        current_formal_row_count=current_formal_row_count+p_added_rows
     WHERE cutover_unit='shared_identity'
       AND authority_state IN ('S3','S4')
       AND formal_business_data=true;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'shared identity formal snapshot is not writable'
            USING ERRCODE='42501';
    END IF;
    RETURN p_result;
END;
$$;

CREATE OR REPLACE FUNCTION shared_identity.create_researcher_v1(
    p_name text,
    p_display_name text,
    p_focus_summary text,
    p_focus_industries jsonb,
    p_bio text,
    p_idempotency_key text,
    p_request_sha256 text,
    p_writer_identity text,
    p_actor text
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, shared_identity, operations
AS $$
DECLARE
    v_existing shared_identity.mutation_result%ROWTYPE;
    v_id bigint;
    v_payload jsonb;
    v_stable_key text;
    v_result jsonb;
BEGIN
    IF nullif(btrim(p_name),'') IS NULL
       OR nullif(btrim(p_idempotency_key),'') IS NULL
       OR nullif(btrim(p_actor),'') IS NULL
       OR p_request_sha256 !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(COALESCE(p_focus_industries,'[]'::jsonb)) <> 'array' THEN
        RAISE EXCEPTION 'researcher mutation identity is incomplete' USING ERRCODE='22023';
    END IF;
    SELECT * INTO v_existing FROM shared_identity.mutation_result
     WHERE operation_scope='shared_identity.create_researcher_v1'
       AND idempotency_key=p_idempotency_key;
    IF FOUND THEN
        IF v_existing.request_sha256 <> p_request_sha256 THEN
            RAISE EXCEPTION 'researcher idempotency conflict' USING ERRCODE='23505';
        END IF;
        RETURN v_existing.result_payload;
    END IF;
    PERFORM shared_identity.assert_formal_writer_v1(p_writer_identity);
    IF EXISTS (
        SELECT 1 FROM shared_identity.legacy_record
         WHERE source_database='research.db' AND source_table='researcher'
           AND formal_business_data=true
           AND lower(btrim(payload->>'name'))=lower(btrim(p_name))
    ) THEN
        RAISE EXCEPTION 'researcher name already exists' USING ERRCODE='23505';
    END IF;
    v_id := shared_identity.next_legacy_identity_v1('research.db','researcher');
    v_payload := jsonb_build_object(
        'id',v_id,'name',btrim(p_name),
        'display_name',COALESCE(nullif(btrim(p_display_name),''),btrim(p_name)),
        'focus_summary',nullif(btrim(p_focus_summary),''),
        'focus_industries',COALESCE(p_focus_industries,'[]'::jsonb),
        'bio',nullif(btrim(p_bio),''),'is_active',1,
        'joined_at',clock_timestamp(),'created_at',clock_timestamp(),
        'updated_at',clock_timestamp()
    );
    v_stable_key := 'researcher:name:' || encode(
        sha256(convert_to(to_jsonb(lower(btrim(p_name)))::text,'UTF8')),'hex'
    );
    PERFORM shared_identity.append_formal_record_v1(
        'research.db','researcher',v_id::text,v_stable_key,'entity',v_payload
    );
    v_result := jsonb_build_object(
        'researcher_id',v_id,'stable_key',v_stable_key,'created',true
    );
    RETURN shared_identity.record_mutation_v1(
        'shared_identity.create_researcher_v1',p_idempotency_key,
        p_request_sha256,v_stable_key,'create',p_actor,v_result,1
    );
END;
$$;

CREATE OR REPLACE FUNCTION shared_identity.ensure_listed_company_v1(
    p_canonical_name text,
    p_ticker text,
    p_market text,
    p_listing_status text,
    p_verification_source_ref text,
    p_aliases jsonb,
    p_stable_key text,
    p_idempotency_key text,
    p_request_sha256 text,
    p_writer_identity text,
    p_actor text
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, shared_identity, operations
AS $$
DECLARE
    v_existing shared_identity.mutation_result%ROWTYPE;
    v_company shared_identity.legacy_record%ROWTYPE;
    v_company_id bigint;
    v_security_id bigint;
    v_alias_id bigint;
    v_payload jsonb;
    v_result jsonb;
    v_alias text;
    v_added bigint := 0;
BEGIN
    IF nullif(btrim(p_canonical_name),'') IS NULL
       OR nullif(btrim(p_ticker),'') IS NULL
       OR nullif(btrim(p_market),'') IS NULL
       OR nullif(btrim(p_listing_status),'') IS NULL
       OR nullif(btrim(p_verification_source_ref),'') IS NULL
       OR nullif(btrim(p_stable_key),'') IS NULL
       OR nullif(btrim(p_idempotency_key),'') IS NULL
       OR nullif(btrim(p_actor),'') IS NULL
       OR p_request_sha256 !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(COALESCE(p_aliases,'[]'::jsonb)) <> 'array' THEN
        RAISE EXCEPTION 'listed company mutation identity is incomplete' USING ERRCODE='22023';
    END IF;
    SELECT * INTO v_existing FROM shared_identity.mutation_result
     WHERE operation_scope='shared_identity.ensure_listed_company_v1'
       AND idempotency_key=p_idempotency_key;
    IF FOUND THEN
        IF v_existing.request_sha256 <> p_request_sha256 THEN
            RAISE EXCEPTION 'listed company idempotency conflict' USING ERRCODE='23505';
        END IF;
        RETURN v_existing.result_payload;
    END IF;
    PERFORM shared_identity.assert_formal_writer_v1(p_writer_identity);
    SELECT * INTO v_company FROM shared_identity.legacy_record
     WHERE source_database='research.db' AND source_table='company'
       AND formal_business_data=true
       AND upper(btrim(payload->>'ticker'))=upper(btrim(p_ticker))
       AND lower(btrim(payload->>'market'))=lower(btrim(p_market))
     FOR UPDATE;
    IF FOUND THEN
        IF v_company.stable_key <> p_stable_key
           OR lower(btrim(v_company.payload->>'name')) <> lower(btrim(p_canonical_name)) THEN
            RAISE EXCEPTION 'listed company identity conflicts with the formal mapping'
                USING ERRCODE='23505';
        END IF;
        SELECT (payload->>'id')::bigint INTO v_security_id
          FROM shared_identity.legacy_record
         WHERE source_database='financial.db'
           AND source_table='financial_security'
           AND stable_key=p_stable_key AND formal_business_data=true
         LIMIT 1;
        v_company_id := (v_company.payload->>'id')::bigint;
        IF v_security_id IS NULL THEN
            v_security_id := shared_identity.next_legacy_identity_v1(
                'financial.db','financial_security'
            );
            v_payload := jsonb_build_object(
                'id',v_security_id,'research_company_id',v_company_id,
                'canonical_name',btrim(p_canonical_name),
                'ticker',upper(btrim(p_ticker)),'market',btrim(p_market),
                'listing_status',btrim(p_listing_status),
                'identity_status','verified','created_at',clock_timestamp(),
                'updated_at',clock_timestamp()
            );
            PERFORM shared_identity.append_formal_record_v1(
                'financial.db','financial_security',v_security_id::text,
                p_stable_key,'entity',v_payload
            );
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
            v_added := v_added + 2;
        END IF;
        FOR v_alias IN
            SELECT DISTINCT btrim(value)
              FROM jsonb_array_elements_text(COALESCE(p_aliases,'[]'::jsonb))
             WHERE nullif(btrim(value),'') IS NOT NULL
            UNION SELECT btrim(p_canonical_name)
        LOOP
            IF NOT EXISTS (
                SELECT 1 FROM shared_identity.legacy_record
                 WHERE source_database='research.db'
                   AND source_table='company_identity_alias'
                   AND formal_business_data=true
                   AND (payload->>'canonical_company_id')::bigint=v_company_id
                   AND lower(btrim(payload->>'alias'))=lower(v_alias)
            ) THEN
                v_alias_id := shared_identity.next_legacy_identity_v1(
                    'research.db','company_identity_alias'
                );
                v_payload := jsonb_build_object(
                    'id',v_alias_id,'canonical_company_id',v_company_id,
                    'alias',v_alias,'alias_type','verified_name',
                    'source',btrim(p_verification_source_ref),
                    'created_at',clock_timestamp()
                );
                PERFORM shared_identity.append_formal_record_v1(
                    'research.db','company_identity_alias',v_alias_id::text,
                    'shared-identity:research.db:company_identity_alias:' || v_alias_id,
                    'mapping',v_payload
                );
                v_added := v_added + 1;
            END IF;
        END LOOP;
        v_result := jsonb_build_object(
            'company_id',v_company_id,
            'financial_security_id',v_security_id,
            'stable_key',p_stable_key,'created',false,
            'records_added',v_added
        );
        RETURN shared_identity.record_mutation_v1(
            'shared_identity.ensure_listed_company_v1',p_idempotency_key,
            p_request_sha256,p_stable_key,
            CASE WHEN v_added=0 THEN 'ensure_existing' ELSE 'ensure_completed' END,
            p_actor,v_result,v_added
        );
    END IF;
    IF EXISTS (
        SELECT 1 FROM shared_identity.legacy_record
         WHERE source_database='research.db' AND source_table='company'
           AND formal_business_data=true
           AND lower(btrim(payload->>'name'))=lower(btrim(p_canonical_name))
    ) OR EXISTS (
        SELECT 1 FROM shared_identity.legacy_record
         WHERE source_database='research.db' AND source_table='company'
           AND formal_business_data=true AND stable_key=p_stable_key
    ) THEN
        RAISE EXCEPTION 'listed company name or stable identity already exists'
            USING ERRCODE='23505';
    END IF;
    v_company_id := shared_identity.next_legacy_identity_v1('research.db','company');
    v_payload := jsonb_build_object(
        'id',v_company_id,'name',btrim(p_canonical_name),
        'ticker',upper(btrim(p_ticker)),'market',btrim(p_market),
        'listing_status',btrim(p_listing_status),
        'note','identity verification source: ' || btrim(p_verification_source_ref),
        'created_at',clock_timestamp()
    );
    PERFORM shared_identity.append_formal_record_v1(
        'research.db','company',v_company_id::text,p_stable_key,'entity',v_payload
    );
    v_added := v_added + 1;
    v_security_id := shared_identity.next_legacy_identity_v1('financial.db','financial_security');
    v_payload := jsonb_build_object(
        'id',v_security_id,'research_company_id',v_company_id,
        'canonical_name',btrim(p_canonical_name),'ticker',upper(btrim(p_ticker)),
        'market',btrim(p_market),'listing_status',btrim(p_listing_status),
        'identity_status','verified','created_at',clock_timestamp(),
        'updated_at',clock_timestamp()
    );
    PERFORM shared_identity.append_formal_record_v1(
        'financial.db','financial_security',v_security_id::text,
        p_stable_key,'entity',v_payload
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
    v_added := v_added + 1;
    FOR v_alias IN
        SELECT DISTINCT btrim(value)
          FROM jsonb_array_elements_text(COALESCE(p_aliases,'[]'::jsonb))
         WHERE nullif(btrim(value),'') IS NOT NULL
        UNION SELECT btrim(p_canonical_name)
    LOOP
        v_alias_id := shared_identity.next_legacy_identity_v1(
            'research.db','company_identity_alias'
        );
        v_payload := jsonb_build_object(
            'id',v_alias_id,'canonical_company_id',v_company_id,
            'alias',v_alias,'alias_type','verified_name',
            'source',btrim(p_verification_source_ref),'created_at',clock_timestamp()
        );
        PERFORM shared_identity.append_formal_record_v1(
            'research.db','company_identity_alias',v_alias_id::text,
            'shared-identity:research.db:company_identity_alias:' || v_alias_id,
            'mapping',v_payload
        );
        v_added := v_added + 1;
    END LOOP;
    v_result := jsonb_build_object(
        'company_id',v_company_id,'financial_security_id',v_security_id,
        'stable_key',p_stable_key,'created',true,'records_added',v_added
    );
    RETURN shared_identity.record_mutation_v1(
        'shared_identity.ensure_listed_company_v1',p_idempotency_key,
        p_request_sha256,p_stable_key,'create',p_actor,v_result,v_added
    );
END;
$$;

REVOKE ALL ON shared_identity.mutation_audit FROM PUBLIC;
REVOKE ALL ON FUNCTION shared_identity.assert_formal_writer_v1(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION shared_identity.next_legacy_identity_v1(text,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION shared_identity.append_formal_record_v1(
    text,text,text,text,text,jsonb
) FROM PUBLIC;
REVOKE ALL ON FUNCTION shared_identity.record_mutation_v1(
    text,text,text,text,text,text,jsonb,bigint
) FROM PUBLIC;
REVOKE ALL ON FUNCTION shared_identity.create_researcher_v1(
    text,text,text,jsonb,text,text,text,text,text
) FROM PUBLIC;
REVOKE ALL ON FUNCTION shared_identity.ensure_listed_company_v1(
    text,text,text,text,text,jsonb,text,text,text,text,text
) FROM PUBLIC;

INSERT INTO operations.schema_migration(
    migration_id,migration_sha256,phase,forward_only
) VALUES (
    '0007_shared_identity_mutation_expand',:'migration_sha256','expand',false
) ON CONFLICT (migration_id) DO NOTHING;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM operations.schema_migration
         WHERE migration_id='0007_shared_identity_mutation_expand'
           AND migration_sha256=current_setting('honghu.migration_sha256')
    ) THEN
        RAISE EXCEPTION 'migration identity exists with a different SHA256';
    END IF;
END $$;

COMMIT;
