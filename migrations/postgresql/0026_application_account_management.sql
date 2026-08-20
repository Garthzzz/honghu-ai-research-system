\set ON_ERROR_STOP on

BEGIN;
SELECT set_config('honghu.migration_sha256', :'migration_sha256', true);

CREATE SCHEMA IF NOT EXISTS application_identity;

CREATE TABLE application_identity.authority (
    authority_key text PRIMARY KEY CHECK (authority_key='application_accounts'),
    enabled boolean NOT NULL,
    writer_identity text NOT NULL CHECK (writer_identity='honghu_writer_application_identity'),
    authority_revision bigint NOT NULL CHECK (authority_revision>0),
    approval_reference text NOT NULL CHECK (btrim(approval_reference)<>''),
    authentication_proof_sha256 text NOT NULL CHECK(authentication_proof_sha256 ~ '^[0-9a-f]{64}$'),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

INSERT INTO application_identity.authority(
    authority_key,enabled,writer_identity,authority_revision,approval_reference,authentication_proof_sha256
) VALUES(
    'application_accounts',true,'honghu_writer_application_identity',1,
    'user-approved-application-account-management-2026-08-20',repeat('0',64)
) ON CONFLICT(authority_key) DO NOTHING;

CREATE TABLE application_identity.account (
    account_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    subject text NOT NULL UNIQUE CHECK(subject ~ '^[a-z0-9][a-z0-9._-]{2,63}$'),
    display_name text NOT NULL CHECK(btrim(display_name)<>'' AND length(display_name)<=100),
    credential_backend text NOT NULL CHECK(credential_backend IN ('windows_keyring','postgresql_hash')),
    password_hash text,
    password_algorithm text,
    permissions text[] NOT NULL,
    is_superadmin boolean NOT NULL DEFAULT false,
    status text NOT NULL CHECK(status IN ('active','disabled','deleted')),
    must_change_password boolean NOT NULL DEFAULT false,
    revision bigint NOT NULL DEFAULT 1 CHECK(revision>0),
    auth_revision bigint NOT NULL DEFAULT 1 CHECK(auth_revision>0),
    failed_login_count integer NOT NULL DEFAULT 0 CHECK(failed_login_count>=0),
    locked_until timestamptz,
    last_login_at timestamptz,
    created_by text NOT NULL,
    updated_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    deleted_at timestamptz,
    CHECK (
      (credential_backend='windows_keyring' AND password_hash IS NULL AND password_algorithm IS NULL)
      OR
      (credential_backend='postgresql_hash' AND password_hash IS NOT NULL AND password_algorithm='werkzeug-scrypt-v1')
    ),
    CHECK(cardinality(permissions)>0),
    CHECK(permissions <@ ARRAY[
      'analyst_note:read','analyst_note:write','shared_identity:write',
      'valuation_tracker:read','valuation_tracker:write','valuation_tracker:publish',
      'account_admin:read','account_admin:manage'
    ]::text[]),
    CHECK(NOT is_superadmin OR permissions @> ARRAY['account_admin:read','account_admin:manage']::text[]),
    CHECK(is_superadmin = (permissions @> ARRAY['account_admin:manage']::text[])),
    CHECK(NOT permissions @> ARRAY['account_admin:manage']::text[] OR permissions @> ARRAY['account_admin:read']::text[]),
    CHECK((status='deleted')=(deleted_at IS NOT NULL))
);

CREATE TABLE application_identity.session (
    session_hash text PRIMARY KEY CHECK(session_hash ~ '^[0-9a-f]{64}$'),
    account_id bigint NOT NULL REFERENCES application_identity.account,
    auth_revision bigint NOT NULL,
    authenticated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    last_seen_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    revoke_reason text,
    user_agent_sha256 text CHECK(user_agent_sha256 IS NULL OR user_agent_sha256 ~ '^[0-9a-f]{64}$'),
    remote_address_sha256 text CHECK(remote_address_sha256 IS NULL OR remote_address_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE application_identity.account_revision_audit (
    audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    operation_scope text NOT NULL,
    idempotency_key text NOT NULL,
    request_sha256 text NOT NULL CHECK(request_sha256 ~ '^[0-9a-f]{64}$'),
    subject text NOT NULL,
    action text NOT NULL,
    before_payload jsonb,
    after_payload jsonb NOT NULL CHECK(jsonb_typeof(after_payload)='object'),
    actor text NOT NULL,
    reason text NOT NULL CHECK(btrim(reason)<>''),
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE(operation_scope,idempotency_key)
);

CREATE TABLE application_identity.mutation_result (
    operation_scope text NOT NULL,
    idempotency_key text NOT NULL,
    request_sha256 text NOT NULL CHECK(request_sha256 ~ '^[0-9a-f]{64}$'),
    result_payload jsonb NOT NULL CHECK(jsonb_typeof(result_payload)='object'),
    committed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(operation_scope,idempotency_key)
);

CREATE TABLE application_identity.security_audit (
    security_audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    action text NOT NULL CHECK(action IN ('authentication_proof_initialized','authentication_proof_verified','authentication_proof_rotated')),
    actor text NOT NULL CHECK(btrim(actor)<>''),
    reason text NOT NULL CHECK(btrim(reason)<>''),
    key_version integer NOT NULL CHECK(key_version=1),
    authority_revision_before bigint NOT NULL CHECK(authority_revision_before>0),
    authority_revision_after bigint NOT NULL CHECK(authority_revision_after>=authority_revision_before),
    sessions_revoked boolean NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX application_session_account_idx
  ON application_identity.session(account_id,revoked_at,expires_at);
CREATE INDEX application_account_status_idx
  ON application_identity.account(status,is_superadmin,subject);

INSERT INTO application_identity.account(
  subject,display_name,credential_backend,password_hash,password_algorithm,
  permissions,is_superadmin,status,must_change_password,created_by,updated_by
) VALUES
('research-operator','研究平台管理员','windows_keyring',NULL,NULL,ARRAY[
  'analyst_note:read','analyst_note:write','shared_identity:write',
  'valuation_tracker:read','valuation_tracker:write','valuation_tracker:publish',
  'account_admin:read','account_admin:manage'
]::text[],true,'active',false,'migration-0026','migration-0026'),
('research-auditor','研究只读审核','windows_keyring',NULL,NULL,ARRAY[
  'analyst_note:read','valuation_tracker:read'
]::text[],false,'active',false,'migration-0026','migration-0026')
ON CONFLICT(subject) DO NOTHING;

CREATE OR REPLACE FUNCTION application_identity.assert_writer_v1()
RETURNS void LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,application_identity AS $$
DECLARE v application_identity.authority%ROWTYPE;
BEGIN
  SELECT * INTO v FROM application_identity.authority
   WHERE authority_key='application_accounts';
  IF NOT FOUND OR NOT v.enabled
     OR v.writer_identity IS DISTINCT FROM 'honghu_writer_application_identity'
     OR NOT pg_has_role(session_user,v.writer_identity,'MEMBER') THEN
    RAISE EXCEPTION 'application account writer is fenced' USING ERRCODE='42501';
  END IF;
END; $$;

CREATE OR REPLACE FUNCTION application_identity.assert_writer_locked_v1()
RETURNS void LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,application_identity AS $$
DECLARE v application_identity.authority%ROWTYPE;
BEGIN
  SELECT * INTO v FROM application_identity.authority
   WHERE authority_key='application_accounts' FOR UPDATE;
  IF NOT FOUND OR NOT v.enabled
     OR v.writer_identity IS DISTINCT FROM 'honghu_writer_application_identity'
     OR NOT pg_has_role(session_user,v.writer_identity,'MEMBER') THEN
    RAISE EXCEPTION 'application account writer is fenced' USING ERRCODE='42501';
  END IF;
END; $$;

CREATE OR REPLACE FUNCTION application_identity.public_account_v1(
  p_account application_identity.account
) RETURNS jsonb LANGUAGE sql IMMUTABLE
SET search_path=pg_catalog,application_identity AS $$
  SELECT jsonb_build_object(
    'subject',p_account.subject,'display_name',p_account.display_name,
    'permissions',to_jsonb(p_account.permissions),'is_superadmin',p_account.is_superadmin,
    'status',p_account.status,'must_change_password',p_account.must_change_password,
    'revision',p_account.revision,'auth_revision',p_account.auth_revision,
    'last_login_at',p_account.last_login_at,'created_at',p_account.created_at,
    'updated_at',p_account.updated_at
  )
$$;

CREATE OR REPLACE FUNCTION application_identity.assert_admin_session_v1(p_session_hash text)
RETURNS application_identity.account LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,application_identity AS $$
DECLARE v_account application_identity.account%ROWTYPE;
BEGIN
  PERFORM application_identity.assert_writer_locked_v1();
  IF p_session_hash IS NULL OR p_session_hash !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'administrator session is invalid' USING ERRCODE='42501';
  END IF;
  SELECT a.* INTO v_account
    FROM application_identity.session s
    JOIN application_identity.account a ON a.account_id=s.account_id
   WHERE s.session_hash=p_session_hash AND s.revoked_at IS NULL
     AND s.expires_at>clock_timestamp()
     AND s.last_seen_at>clock_timestamp()-interval '30 minutes'
     AND s.auth_revision=a.auth_revision AND a.status='active'
     AND a.permissions @> ARRAY['account_admin:manage']::text[]
     AND s.authenticated_at>clock_timestamp()-interval '15 minutes'
   FOR UPDATE OF a;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'recent administrator authentication is required' USING ERRCODE='42501';
  END IF;
  RETURN v_account;
END; $$;

CREATE OR REPLACE FUNCTION application_identity.login_verifier_v1(p_subject text)
RETURNS TABLE(
  subject text,credential_backend text,password_hash text,status text,
  locked_until timestamptz,auth_revision bigint
) LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,application_identity AS $$
BEGIN
  PERFORM application_identity.assert_writer_v1();
  RETURN QUERY SELECT a.subject,a.credential_backend,a.password_hash,a.status,a.locked_until,a.auth_revision
    FROM application_identity.account a WHERE a.subject=lower(btrim(p_subject));
END; $$;

CREATE OR REPLACE FUNCTION application_identity.complete_login_v1(
  p_subject text,p_verified boolean,p_expected_auth_revision bigint,p_authentication_proof text,
  p_session_hash text,p_expires_at timestamptz,
  p_user_agent_sha256 text,p_remote_address_sha256 text
) RETURNS TABLE(
  subject text,permissions text[],revision bigint,auth_revision bigint,must_change_password boolean
) LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,application_identity AS $$
DECLARE v application_identity.account%ROWTYPE;
DECLARE v_proof_sha text;
BEGIN
  PERFORM application_identity.assert_writer_v1();
  SELECT authentication_proof_sha256 INTO v_proof_sha
    FROM application_identity.authority WHERE authority_key='application_accounts';
  IF nullif(p_authentication_proof,'') IS NULL OR length(p_authentication_proof)>256
     OR v_proof_sha=repeat('0',64)
     OR encode(sha256(convert_to(p_authentication_proof,'UTF8')),'hex') IS DISTINCT FROM v_proof_sha THEN
    RAISE EXCEPTION 'application authentication proof is invalid' USING ERRCODE='42501';
  END IF;
  SELECT * INTO v FROM application_identity.account
   WHERE account.subject=lower(btrim(p_subject)) FOR UPDATE;
  IF NOT FOUND THEN RETURN; END IF;
  IF p_verified IS DISTINCT FROM true OR p_expected_auth_revision IS DISTINCT FROM v.auth_revision
     OR v.status<>'active'
     OR (v.locked_until IS NOT NULL AND v.locked_until>clock_timestamp()) THEN
    UPDATE application_identity.account SET
      failed_login_count=failed_login_count+1,
      locked_until=CASE WHEN failed_login_count+1>=5
        THEN clock_timestamp()+interval '15 minutes' ELSE locked_until END,
      updated_at=clock_timestamp()
    WHERE account_id=v.account_id;
    RETURN;
  END IF;
  IF p_session_hash !~ '^[0-9a-f]{64}$'
     OR p_expires_at<=clock_timestamp() OR p_expires_at>clock_timestamp()+interval '9 hours'
     OR (p_user_agent_sha256 IS NOT NULL AND p_user_agent_sha256 !~ '^[0-9a-f]{64}$')
     OR (p_remote_address_sha256 IS NOT NULL AND p_remote_address_sha256 !~ '^[0-9a-f]{64}$') THEN
    RAISE EXCEPTION 'session identity is invalid' USING ERRCODE='22023';
  END IF;
  UPDATE application_identity.account SET failed_login_count=0,locked_until=NULL,
    last_login_at=clock_timestamp(),updated_at=clock_timestamp()
   WHERE account_id=v.account_id RETURNING * INTO v;
  INSERT INTO application_identity.session(
    session_hash,account_id,auth_revision,expires_at,user_agent_sha256,remote_address_sha256
  ) VALUES(p_session_hash,v.account_id,v.auth_revision,p_expires_at,p_user_agent_sha256,p_remote_address_sha256);
  RETURN QUERY SELECT v.subject,v.permissions,v.revision,v.auth_revision,v.must_change_password;
END; $$;

CREATE OR REPLACE FUNCTION application_identity.local_set_authentication_proof_v1(
  p_authentication_proof_sha256 text,p_reason text,p_key_version integer
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,application_identity AS $$
DECLARE v_old text; v_revision bigint; v_revoked boolean:=false;
BEGIN
  IF session_user IS DISTINCT FROM 'honghu_migration'
     OR p_authentication_proof_sha256 IS NULL
     OR p_authentication_proof_sha256 !~ '^[0-9a-f]{64}$'
     OR p_authentication_proof_sha256=repeat('0',64)
     OR nullif(btrim(p_reason),'') IS NULL OR p_key_version IS DISTINCT FROM 1 THEN
    RAISE EXCEPTION 'local authentication proof provisioning is fenced' USING ERRCODE='42501';
  END IF;
  SELECT authentication_proof_sha256,authority_revision INTO v_old,v_revision FROM application_identity.authority
   WHERE authority_key='application_accounts' FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'application identity authority is absent' USING ERRCODE='23503'; END IF;
  IF v_old IS NOT DISTINCT FROM p_authentication_proof_sha256 THEN
    INSERT INTO application_identity.security_audit(
      action,actor,reason,key_version,authority_revision_before,authority_revision_after,sessions_revoked
    ) VALUES(
      'authentication_proof_verified','vm-local-provisioner',p_reason,p_key_version,v_revision,v_revision,false
    );
    RETURN true;
  END IF;
  IF v_old IS DISTINCT FROM repeat('0',64) AND v_old IS DISTINCT FROM p_authentication_proof_sha256 THEN
    UPDATE application_identity.session SET revoked_at=clock_timestamp(),revoke_reason='authentication_proof_rotated'
     WHERE revoked_at IS NULL;
    v_revoked:=FOUND;
  END IF;
  UPDATE application_identity.authority SET authentication_proof_sha256=p_authentication_proof_sha256,
    authority_revision=authority_revision+1,updated_at=clock_timestamp()
   WHERE authority_key='application_accounts';
  INSERT INTO application_identity.security_audit(
    action,actor,reason,key_version,authority_revision_before,authority_revision_after,sessions_revoked
  ) VALUES(
    CASE WHEN v_old=repeat('0',64) THEN 'authentication_proof_initialized' ELSE 'authentication_proof_rotated' END,
    'vm-local-provisioner',p_reason,p_key_version,v_revision,v_revision+1,v_revoked
  );
  RETURN true;
END; $$;

CREATE OR REPLACE FUNCTION application_identity.resolve_session_v1(p_session_hash text)
RETURNS TABLE(
  subject text,permissions text[],revision bigint,auth_revision bigint,must_change_password boolean
) LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,application_identity AS $$
DECLARE v_session application_identity.session%ROWTYPE;
DECLARE v application_identity.account%ROWTYPE;
BEGIN
  PERFORM application_identity.assert_writer_v1();
  IF p_session_hash IS NULL OR p_session_hash !~ '^[0-9a-f]{64}$' THEN RETURN; END IF;
  SELECT * INTO v_session FROM application_identity.session
   WHERE session_hash=p_session_hash FOR UPDATE;
  IF NOT FOUND OR v_session.revoked_at IS NOT NULL OR v_session.expires_at<=clock_timestamp()
     OR v_session.last_seen_at<=clock_timestamp()-interval '30 minutes' THEN RETURN; END IF;
  SELECT * INTO v FROM application_identity.account WHERE account_id=v_session.account_id;
  IF NOT FOUND OR v.status<>'active' OR v.auth_revision IS DISTINCT FROM v_session.auth_revision THEN
    UPDATE application_identity.session SET revoked_at=clock_timestamp(),revoke_reason='account_revision_changed'
     WHERE session_hash=p_session_hash AND revoked_at IS NULL;
    RETURN;
  END IF;
  UPDATE application_identity.session SET last_seen_at=clock_timestamp()
   WHERE session_hash=p_session_hash;
  RETURN QUERY SELECT v.subject,v.permissions,v.revision,v.auth_revision,v.must_change_password;
END; $$;

CREATE OR REPLACE FUNCTION application_identity.logout_v1(p_session_hash text)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,application_identity AS $$
BEGIN
  PERFORM application_identity.assert_writer_v1();
  UPDATE application_identity.session SET revoked_at=clock_timestamp(),revoke_reason='logout'
   WHERE session_hash=p_session_hash AND revoked_at IS NULL;
  RETURN FOUND;
END; $$;

CREATE OR REPLACE FUNCTION application_identity.list_accounts_v1(p_session_hash text)
RETURNS TABLE(
  subject text,display_name text,permissions text[],is_superadmin boolean,status text,
  must_change_password boolean,revision bigint,auth_revision bigint,
  last_login_at timestamptz,created_at timestamptz,updated_at timestamptz
) LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,application_identity AS $$
BEGIN
  PERFORM application_identity.assert_writer_v1();
  IF NOT EXISTS(
    SELECT 1 FROM application_identity.session s
    JOIN application_identity.account a ON a.account_id=s.account_id
    WHERE s.session_hash=p_session_hash AND s.revoked_at IS NULL
      AND s.expires_at>clock_timestamp() AND s.last_seen_at>clock_timestamp()-interval '30 minutes'
      AND s.auth_revision=a.auth_revision AND a.status='active'
      AND a.permissions @> ARRAY['account_admin:read']::text[]
  ) THEN
    RAISE EXCEPTION 'account read permission is required' USING ERRCODE='42501';
  END IF;
  RETURN QUERY SELECT a.subject,a.display_name,a.permissions,a.is_superadmin,a.status,
    a.must_change_password,a.revision,a.auth_revision,a.last_login_at,a.created_at,a.updated_at
    FROM application_identity.account a ORDER BY (a.status='active') DESC,a.is_superadmin DESC,a.subject;
END; $$;

CREATE OR REPLACE FUNCTION application_identity.create_account_v1(
  p_session_hash text,p_subject text,p_display_name text,p_password_hash text,p_password_fingerprint text,
  p_permissions text[],p_is_superadmin boolean,p_reason text,p_idempotency_key text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,application_identity AS $$
DECLARE v_actor application_identity.account%ROWTYPE; v_new application_identity.account%ROWTYPE;
DECLARE v_request text; v_result jsonb; v_old application_identity.mutation_result%ROWTYPE;
BEGIN
  v_actor:=application_identity.assert_admin_session_v1(p_session_hash);
  IF p_subject !~ '^[a-z0-9][a-z0-9._-]{2,63}$' OR p_subject IS DISTINCT FROM lower(p_subject)
    OR nullif(btrim(p_display_name),'') IS NULL OR length(p_display_name)>100
    OR nullif(p_password_hash,'') IS NULL OR p_password_hash NOT LIKE 'scrypt:%' OR length(p_password_hash)>500
    OR p_password_fingerprint IS NULL OR p_password_fingerprint !~ '^[0-9a-f]{64}$'
    OR p_permissions IS NULL OR cardinality(p_permissions)=0 OR array_position(p_permissions,NULL) IS NOT NULL
    OR NOT p_permissions <@ ARRAY['analyst_note:read','analyst_note:write','shared_identity:write','valuation_tracker:read','valuation_tracker:write','valuation_tracker:publish','account_admin:read','account_admin:manage']::text[]
    OR (p_is_superadmin AND NOT p_permissions @> ARRAY['account_admin:read','account_admin:manage']::text[])
    OR p_is_superadmin IS DISTINCT FROM (p_permissions @> ARRAY['account_admin:manage']::text[])
    OR nullif(btrim(p_reason),'') IS NULL OR nullif(btrim(p_idempotency_key),'') IS NULL THEN
    RAISE EXCEPTION 'account create request is invalid' USING ERRCODE='22023';
  END IF;
  v_request:=encode(sha256(convert_to(jsonb_build_object('subject',p_subject,'display_name',p_display_name,
    'password_fingerprint',p_password_fingerprint,'permissions',p_permissions,'is_superadmin',p_is_superadmin,
    'reason',p_reason,'actor',v_actor.subject)::text,'UTF8')),'hex');
  PERFORM pg_advisory_xact_lock(hashtextextended('application_identity:create:'||p_subject,0));
  SELECT * INTO v_old FROM application_identity.mutation_result
   WHERE operation_scope='create_account_v1' AND idempotency_key=p_idempotency_key;
  IF FOUND THEN
    IF v_old.request_sha256 IS DISTINCT FROM v_request THEN RAISE EXCEPTION 'idempotency conflict' USING ERRCODE='23505'; END IF;
    RETURN v_old.result_payload;
  END IF;
  INSERT INTO application_identity.account(subject,display_name,credential_backend,password_hash,password_algorithm,
    permissions,is_superadmin,status,must_change_password,created_by,updated_by)
  VALUES(p_subject,p_display_name,'postgresql_hash',p_password_hash,'werkzeug-scrypt-v1',
    (SELECT array_agg(DISTINCT x ORDER BY x) FROM unnest(p_permissions)x),p_is_superadmin,'active',false,v_actor.subject,v_actor.subject)
  RETURNING * INTO v_new;
  v_result:=application_identity.public_account_v1(v_new);
  INSERT INTO application_identity.account_revision_audit(operation_scope,idempotency_key,request_sha256,subject,action,before_payload,after_payload,actor,reason)
  VALUES('create_account_v1',p_idempotency_key,v_request,p_subject,'create',NULL,v_result,v_actor.subject,p_reason);
  INSERT INTO application_identity.mutation_result VALUES('create_account_v1',p_idempotency_key,v_request,v_result,clock_timestamp());
  RETURN v_result;
END; $$;

CREATE OR REPLACE FUNCTION application_identity.update_account_v1(
  p_session_hash text,p_subject text,p_display_name text,p_permissions text[],
  p_is_superadmin boolean,p_active boolean,p_expected_revision bigint,p_reason text,p_idempotency_key text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,application_identity AS $$
DECLARE v_actor application_identity.account%ROWTYPE; v_target application_identity.account%ROWTYPE;
DECLARE v_before jsonb; v_result jsonb; v_request text; v_old application_identity.mutation_result%ROWTYPE;
BEGIN
  v_actor:=application_identity.assert_admin_session_v1(p_session_hash);
  IF nullif(btrim(p_display_name),'') IS NULL OR length(p_display_name)>100 OR p_expected_revision<1
    OR p_permissions IS NULL OR cardinality(p_permissions)=0 OR array_position(p_permissions,NULL) IS NOT NULL
    OR p_is_superadmin IS NULL OR p_active IS NULL
    OR NOT p_permissions <@ ARRAY['analyst_note:read','analyst_note:write','shared_identity:write','valuation_tracker:read','valuation_tracker:write','valuation_tracker:publish','account_admin:read','account_admin:manage']::text[]
    OR (p_is_superadmin AND NOT p_permissions @> ARRAY['account_admin:read','account_admin:manage']::text[])
    OR p_is_superadmin IS DISTINCT FROM (p_permissions @> ARRAY['account_admin:manage']::text[])
    OR nullif(btrim(p_reason),'') IS NULL OR nullif(btrim(p_idempotency_key),'') IS NULL THEN
    RAISE EXCEPTION 'account update request is invalid' USING ERRCODE='22023';
  END IF;
  v_request:=encode(sha256(convert_to(jsonb_build_object('subject',p_subject,'display_name',p_display_name,
    'permissions',p_permissions,'is_superadmin',p_is_superadmin,'active',p_active,
    'expected_revision',p_expected_revision,'reason',p_reason,'actor',v_actor.subject)::text,'UTF8')),'hex');
  PERFORM pg_advisory_xact_lock(hashtextextended('application_identity:superadmin-invariant',0));
  SELECT * INTO v_old FROM application_identity.mutation_result WHERE operation_scope='update_account_v1' AND idempotency_key=p_idempotency_key;
  IF FOUND THEN
    IF v_old.request_sha256 IS DISTINCT FROM v_request THEN RAISE EXCEPTION 'idempotency conflict' USING ERRCODE='23505'; END IF;
    RETURN v_old.result_payload;
  END IF;
  SELECT * INTO v_target FROM application_identity.account WHERE subject=p_subject FOR UPDATE;
  IF NOT FOUND OR v_target.status='deleted' OR v_target.revision IS DISTINCT FROM p_expected_revision THEN
    RAISE EXCEPTION 'account revision is stale' USING ERRCODE='40001';
  END IF;
  IF v_target.account_id=v_actor.account_id AND (NOT p_active OR NOT p_is_superadmin OR NOT p_permissions @> ARRAY['account_admin:manage']::text[]) THEN
    RAISE EXCEPTION 'an administrator cannot disable or demote the current account' USING ERRCODE='42501';
  END IF;
  IF v_target.is_superadmin AND v_target.status='active' AND (NOT p_active OR NOT p_is_superadmin)
     AND (SELECT count(*) FROM application_identity.account WHERE status='active' AND is_superadmin) <= 1 THEN
    RAISE EXCEPTION 'the last active superadmin is protected' USING ERRCODE='42501';
  END IF;
  v_before:=application_identity.public_account_v1(v_target);
  UPDATE application_identity.account SET display_name=p_display_name,
    permissions=(SELECT array_agg(DISTINCT x ORDER BY x) FROM unnest(p_permissions)x),
    is_superadmin=p_is_superadmin,status=CASE WHEN p_active THEN 'active' ELSE 'disabled' END,
    revision=revision+1,auth_revision=auth_revision+1,updated_by=v_actor.subject,updated_at=clock_timestamp()
   WHERE account_id=v_target.account_id RETURNING * INTO v_target;
  UPDATE application_identity.session SET revoked_at=clock_timestamp(),revoke_reason='account_changed'
   WHERE account_id=v_target.account_id AND revoked_at IS NULL;
  v_result:=application_identity.public_account_v1(v_target);
  INSERT INTO application_identity.account_revision_audit VALUES(DEFAULT,'update_account_v1',p_idempotency_key,v_request,p_subject,'update',v_before,v_result,v_actor.subject,p_reason,DEFAULT);
  INSERT INTO application_identity.mutation_result VALUES('update_account_v1',p_idempotency_key,v_request,v_result,clock_timestamp());
  RETURN v_result;
END; $$;

CREATE OR REPLACE FUNCTION application_identity.reset_password_v1(
  p_session_hash text,p_subject text,p_password_hash text,p_password_fingerprint text,p_expected_revision bigint,
  p_reason text,p_idempotency_key text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,application_identity AS $$
DECLARE v_actor application_identity.account%ROWTYPE; v_target application_identity.account%ROWTYPE;
DECLARE v_before jsonb; v_result jsonb; v_request text; v_old application_identity.mutation_result%ROWTYPE;
BEGIN
  v_actor:=application_identity.assert_admin_session_v1(p_session_hash);
  IF p_subject=v_actor.subject THEN RAISE EXCEPTION 'use the personal password-change flow for the current administrator' USING ERRCODE='42501'; END IF;
  IF p_password_hash NOT LIKE 'scrypt:%' OR length(p_password_hash)>500
     OR p_password_fingerprint IS NULL OR p_password_fingerprint !~ '^[0-9a-f]{64}$' OR p_expected_revision<1
     OR nullif(btrim(p_reason),'') IS NULL OR nullif(btrim(p_idempotency_key),'') IS NULL THEN
    RAISE EXCEPTION 'password reset request is invalid' USING ERRCODE='22023';
  END IF;
  v_request:=encode(sha256(convert_to(jsonb_build_object('subject',p_subject,'password_fingerprint',p_password_fingerprint,
    'expected_revision',p_expected_revision,'reason',p_reason,'actor',v_actor.subject)::text,'UTF8')),'hex');
  PERFORM pg_advisory_xact_lock(hashtextextended('application_identity:password:'||p_subject,0));
  SELECT * INTO v_old FROM application_identity.mutation_result WHERE operation_scope='reset_password_v1' AND idempotency_key=p_idempotency_key;
  IF FOUND THEN
    IF v_old.request_sha256 IS DISTINCT FROM v_request THEN RAISE EXCEPTION 'idempotency conflict' USING ERRCODE='23505'; END IF;
    RETURN v_old.result_payload;
  END IF;
  SELECT * INTO v_target FROM application_identity.account WHERE subject=p_subject FOR UPDATE;
  IF NOT FOUND OR v_target.status='deleted' OR v_target.revision IS DISTINCT FROM p_expected_revision THEN RAISE EXCEPTION 'account revision is stale' USING ERRCODE='40001'; END IF;
  v_before:=application_identity.public_account_v1(v_target);
  UPDATE application_identity.account SET credential_backend='postgresql_hash',password_hash=p_password_hash,
    password_algorithm='werkzeug-scrypt-v1',must_change_password=false,revision=revision+1,
    auth_revision=auth_revision+1,updated_by=v_actor.subject,updated_at=clock_timestamp()
   WHERE account_id=v_target.account_id RETURNING * INTO v_target;
  UPDATE application_identity.session SET revoked_at=clock_timestamp(),revoke_reason='password_reset'
   WHERE account_id=v_target.account_id AND revoked_at IS NULL;
  v_result:=application_identity.public_account_v1(v_target);
  INSERT INTO application_identity.account_revision_audit VALUES(DEFAULT,'reset_password_v1',p_idempotency_key,v_request,p_subject,'reset_password',v_before,v_result,v_actor.subject,p_reason,DEFAULT);
  INSERT INTO application_identity.mutation_result VALUES('reset_password_v1',p_idempotency_key,v_request,v_result,clock_timestamp());
  RETURN v_result;
END; $$;

CREATE OR REPLACE FUNCTION application_identity.delete_account_v1(
  p_session_hash text,p_subject text,p_expected_revision bigint,p_reason text,p_idempotency_key text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,application_identity AS $$
DECLARE v_actor application_identity.account%ROWTYPE; v_target application_identity.account%ROWTYPE;
DECLARE v_before jsonb; v_result jsonb; v_request text; v_old application_identity.mutation_result%ROWTYPE;
BEGIN
  v_actor:=application_identity.assert_admin_session_v1(p_session_hash);
  IF p_subject=v_actor.subject THEN RAISE EXCEPTION 'an administrator cannot delete the current account' USING ERRCODE='42501'; END IF;
  IF p_expected_revision<1 OR nullif(btrim(p_reason),'') IS NULL OR nullif(btrim(p_idempotency_key),'') IS NULL THEN RAISE EXCEPTION 'account delete request is invalid' USING ERRCODE='22023'; END IF;
  v_request:=encode(sha256(convert_to(jsonb_build_object('subject',p_subject,'expected_revision',p_expected_revision,
    'reason',p_reason,'actor',v_actor.subject)::text,'UTF8')),'hex');
  PERFORM pg_advisory_xact_lock(hashtextextended('application_identity:superadmin-invariant',0));
  SELECT * INTO v_old FROM application_identity.mutation_result WHERE operation_scope='delete_account_v1' AND idempotency_key=p_idempotency_key;
  IF FOUND THEN
    IF v_old.request_sha256 IS DISTINCT FROM v_request THEN RAISE EXCEPTION 'idempotency conflict' USING ERRCODE='23505'; END IF;
    RETURN v_old.result_payload;
  END IF;
  SELECT * INTO v_target FROM application_identity.account WHERE subject=p_subject FOR UPDATE;
  IF NOT FOUND OR v_target.status='deleted' OR v_target.revision IS DISTINCT FROM p_expected_revision THEN RAISE EXCEPTION 'account revision is stale' USING ERRCODE='40001'; END IF;
  IF v_target.is_superadmin AND v_target.status='active'
     AND (SELECT count(*) FROM application_identity.account WHERE status='active' AND is_superadmin)<=1 THEN
    RAISE EXCEPTION 'the last active superadmin is protected' USING ERRCODE='42501';
  END IF;
  v_before:=application_identity.public_account_v1(v_target);
  UPDATE application_identity.account SET status='deleted',deleted_at=clock_timestamp(),password_hash=NULL,
    password_algorithm=NULL,credential_backend='windows_keyring',permissions=ARRAY['analyst_note:read']::text[],
    is_superadmin=false,must_change_password=false,revision=revision+1,auth_revision=auth_revision+1,
    updated_by=v_actor.subject,updated_at=clock_timestamp()
   WHERE account_id=v_target.account_id RETURNING * INTO v_target;
  UPDATE application_identity.session SET revoked_at=clock_timestamp(),revoke_reason='account_deleted'
   WHERE account_id=v_target.account_id AND revoked_at IS NULL;
  v_result:=application_identity.public_account_v1(v_target);
  INSERT INTO application_identity.account_revision_audit VALUES(DEFAULT,'delete_account_v1',p_idempotency_key,v_request,p_subject,'delete',v_before,v_result,v_actor.subject,p_reason,DEFAULT);
  INSERT INTO application_identity.mutation_result VALUES('delete_account_v1',p_idempotency_key,v_request,v_result,clock_timestamp());
  RETURN v_result;
END; $$;

CREATE OR REPLACE FUNCTION application_identity.local_reset_superadmin_v1(
  p_subject text,p_password_hash text,p_reason text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,application_identity AS $$
DECLARE v_target application_identity.account%ROWTYPE; v_before jsonb; v_result jsonb; v_request text;
BEGIN
  IF session_user IS DISTINCT FROM 'honghu_migration'
     OR p_password_hash NOT LIKE 'scrypt:%' OR nullif(btrim(p_reason),'') IS NULL THEN
    RAISE EXCEPTION 'local superadmin recovery is fenced' USING ERRCODE='42501';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('application_identity:local-superadmin',0));
  SELECT * INTO v_target FROM application_identity.account
   WHERE subject=lower(btrim(p_subject)) AND status='active' AND is_superadmin FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'active superadmin does not exist' USING ERRCODE='23503';
  END IF;
  v_before:=application_identity.public_account_v1(v_target);
  UPDATE application_identity.account SET credential_backend='postgresql_hash',password_hash=p_password_hash,
    password_algorithm='werkzeug-scrypt-v1',must_change_password=false,failed_login_count=0,locked_until=NULL,
    revision=revision+1,auth_revision=auth_revision+1,updated_by='vm-local-recovery',updated_at=clock_timestamp()
   WHERE account_id=v_target.account_id RETURNING * INTO v_target;
  UPDATE application_identity.session SET revoked_at=clock_timestamp(),revoke_reason='vm_local_password_reset'
   WHERE account_id=v_target.account_id AND revoked_at IS NULL;
  v_result:=application_identity.public_account_v1(v_target);
  v_request:=encode(sha256(convert_to(jsonb_build_object('subject',v_target.subject,
    'password_changed',true,'reason',p_reason,'actor','vm-local-recovery')::text,'UTF8')),'hex');
  INSERT INTO application_identity.account_revision_audit(
    operation_scope,idempotency_key,request_sha256,subject,action,before_payload,after_payload,actor,reason
  ) VALUES('local_reset_superadmin_v1','local-'||gen_random_uuid()::text,v_request,v_target.subject,
    'local_reset_password',v_before,v_result,'vm-local-recovery',p_reason);
  RETURN v_result;
END; $$;

REVOKE ALL ON SCHEMA application_identity FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA application_identity FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA application_identity FROM PUBLIC;
GRANT USAGE ON SCHEMA application_identity TO :"writer_role";
GRANT EXECUTE ON FUNCTION application_identity.login_verifier_v1(text) TO :"writer_role";
GRANT EXECUTE ON FUNCTION application_identity.complete_login_v1(text,boolean,bigint,text,text,timestamptz,text,text) TO :"writer_role";
GRANT EXECUTE ON FUNCTION application_identity.resolve_session_v1(text) TO :"writer_role";
GRANT EXECUTE ON FUNCTION application_identity.logout_v1(text) TO :"writer_role";
GRANT EXECUTE ON FUNCTION application_identity.list_accounts_v1(text) TO :"writer_role";
GRANT EXECUTE ON FUNCTION application_identity.create_account_v1(text,text,text,text,text,text[],boolean,text,text) TO :"writer_role";
GRANT EXECUTE ON FUNCTION application_identity.update_account_v1(text,text,text,text[],boolean,boolean,bigint,text,text) TO :"writer_role";
GRANT EXECUTE ON FUNCTION application_identity.reset_password_v1(text,text,text,text,bigint,text,text) TO :"writer_role";
GRANT EXECUTE ON FUNCTION application_identity.delete_account_v1(text,text,bigint,text,text) TO :"writer_role";
GRANT USAGE ON SCHEMA application_identity TO :"migration_role";
GRANT EXECUTE ON FUNCTION application_identity.local_reset_superadmin_v1(text,text,text) TO :"migration_role";
GRANT EXECUTE ON FUNCTION application_identity.local_set_authentication_proof_v1(text,text,integer) TO :"migration_role";
GRANT USAGE ON SCHEMA application_identity TO :"audit_reader_role";
GRANT SELECT ON application_identity.account_revision_audit TO :"audit_reader_role";
GRANT SELECT ON application_identity.security_audit TO :"audit_reader_role";

INSERT INTO operations.schema_migration(migration_id,migration_sha256,phase,forward_only)
VALUES('0026_application_account_management',:'migration_sha256','expand',false)
ON CONFLICT(migration_id) DO NOTHING;
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM operations.schema_migration
   WHERE migration_id='0026_application_account_management'
     AND migration_sha256=current_setting('honghu.migration_sha256')) THEN
   RAISE EXCEPTION 'migration identity exists with different SHA256';
 END IF;
END $$;
COMMIT;
