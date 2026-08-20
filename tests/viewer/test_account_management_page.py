from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_account_page_masks_passwords_and_states_system_boundary() -> None:
    source = (ROOT / "tools/viewer/templates/account_management.html").read_text(encoding="utf-8")
    assert source.count('type="password"') >= 3
    assert 'aria-pressed="false"' in source
    assert "Windows、VM、文件、命令、服务、计划任务" in source
    assert "account_admin:manage" not in source.split("<script>", 1)[0]


def test_account_editor_keeps_an_explicit_save_action_visible() -> None:
    source = (ROOT / "tools/viewer/templates/account_management.html").read_text(encoding="utf-8")
    assert 'id="am-save-button"' in source
    assert ">保存账号</button>" in source
    assert ".am-form-foot{position:sticky;bottom:0" in source
    assert "saveButton.textContent=mode==='password'?'保存新密码':'保存账号'" in source
    assert "尚未保存修改，确定关闭吗？" in source
    assert "if(submitting)return" in source
    assert "$('.am-close').addEventListener('click',()=>close())" in source
    assert "$('.am-cancel').addEventListener('click',()=>close())" in source


def test_viewer_has_no_http_subprocess_execution_path() -> None:
    source = (ROOT / "tools/viewer/app.py").read_text(encoding="utf-8")
    assert "import subprocess" not in source
    assert "subprocess.run" not in source
    assert '@app.route("/refresh/<int:industry_id>", methods=["GET"])' in source
    template = (ROOT / "tools/viewer/templates/refresh_confirm.html").read_text(encoding="utf-8")
    assert 'method="post"' not in template


def test_application_account_migration_uses_dedicated_writer_and_no_table_dml_grant() -> None:
    source = (ROOT / "migrations/postgresql/0026_application_account_management.sql").read_text(encoding="utf-8")
    assert 'honghu_writer_application_identity' in source
    assert 'TO :"writer_role"' in source
    assert "GRANT INSERT" not in source and "GRANT UPDATE" not in source and "GRANT DELETE" not in source
    assert "the last active superadmin is protected" in source
    assert "account_revision_changed" in source
    assert source.count("p_password_fingerprint IS NULL") == 2
    assert "p_verified IS DISTINCT FROM true" in source
    assert "is_superadmin = (permissions @> ARRAY['account_admin:manage']" in source
    assert source.count("p_is_superadmin IS DISTINCT FROM") == 2
    assert "local_set_authentication_proof_v1" in source
    assert "application authentication proof is invalid" in source
    assert "application_identity.security_audit" in source
    assert 'GRANT USAGE ON SCHEMA application_identity TO :"migration_role"' in source


def test_application_identity_role_is_forced_to_least_privilege() -> None:
    provision = (ROOT / "tools/migration/provision_application_identity_role.py").read_text(encoding="utf-8")
    verify = (ROOT / "tools/migration/stage4_production_verify.py").read_text(encoding="utf-8")
    for token in ("NOSUPERUSER", "NOCREATEDB", "NOCREATEROLE", "NOREPLICATION", "NOBYPASSRLS", "NOINHERIT"):
        assert token in provision
    assert "pg_auth_members" in provision
    assert "has_database_privilege" in provision
    assert "if not role_exists:" in provision
    assert "explicit recovery is required" in provision
    assert "effective parameter logging settings are unsafe" in provision
    assert "has_schema_privilege" in verify
    assert "has_table_privilege" in verify
    finalizer = (ROOT / "tools/migration/finalize_application_identity_auth_proof.py").read_text(encoding="utf-8")
    assert "local_set_authentication_proof_v1" in finalizer
    assert "no secret value was printed" in finalizer
    orchestrator = (ROOT / "tools/migration/provision_application_identity_production.py").read_text(encoding="utf-8")
    run_body = orchestrator.split("def run(", 1)[1]
    assert run_body.index("provision(runtime_path") < run_body.index("_apply_exact(")
    assert run_body.index("_apply_exact(") < run_body.index("finalize(")
    assert "log_parameter_max_length_on_error=0" in orchestrator
    assert "def _preflight(" in orchestrator
    assert "def _verify_writer_effective(" in orchestrator
    account_store = (ROOT / "tools/data_platform/application_accounts.py").read_text(encoding="utf-8")
    assert "_verify_runtime_security_boundary" in account_store
    assert "current_setting('log_parameter_max_length_on_error')" in account_store


def test_postgresql_rehearsal_never_provisions_or_rotates_production_writer() -> None:
    source = (ROOT / "tools/migration/rehearse_application_account_management.py").read_text(encoding="utf-8")
    assert "provision(runtime_path" not in source
    assert 'writer_role = "honghu_account_rehearsal_"' in source
    assert 'password_loader=lambda _service,_account: writer_password' in source
    assert 'DROP ROLE IF EXISTS' in source
    assert '"production_writer_credential_unchanged":True' in source
