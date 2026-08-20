from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tools.migration.stage4_user_content_security_provision import (
    SecurityProvisionError,
    _settings,
)


ROOT = Path(__file__).resolve().parents[2]


def test_security_provision_never_accepts_plaintext_secret_on_cli() -> None:
    source = (
        ROOT / "tools/migration/stage4_user_content_security_provision.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    options = {
        constant.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_argument"
        for constant in node.args
        if isinstance(constant, ast.Constant) and isinstance(constant.value, str)
    }
    assert "--password" not in options
    assert "--session-secret" not in options
    assert "sys.stdin.buffer.read()" in source
    assert "CRYPTPROTECT_LOCAL_MACHINE" in source
    assert "WinVaultKeyring" in source
    assert '"secret_values_recorded": False' in source
    assert '"password_hashes_recorded": False' in source


def test_generate_can_separate_client_acceptance_from_server_hash_service() -> None:
    source = (
        ROOT / "tools/migration/stage4_user_content_security_provision.py"
    ).read_text(encoding="utf-8")
    assert "--acceptance-credential-service" in source
    assert "acceptance_service" in source
    assert 'keyring.set_password(acceptance_service, subject, password)' in source


def test_production_security_config_has_distinct_writer_and_reader() -> None:
    import json

    payload = json.loads(
        (ROOT / "config/migration/user_content_security_production.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["enabled"] is True
    assert payload["require_https"] is True
    assert "analyst_note:write" in payload["principals"]["research-operator"]
    assert "analyst_note:write" not in payload["principals"]["research-auditor"]
    assert "analyst_note:read" in payload["principals"]["research-auditor"]
    assert payload["password_idempotency_secret_service"] != payload["session_secret_service"]
    assert payload["authentication_proof_secret_service"] not in {
        payload["session_secret_service"], payload["password_idempotency_secret_service"]
    }
    assert payload["password_idempotency_secret_version"] == 1
    assert payload["authentication_proof_secret_version"] == 1


def test_security_settings_reject_secret_identity_reuse_and_wrong_version(tmp_path: Path) -> None:
    import json

    source = json.loads(
        (ROOT / "config/migration/user_content_security_production.json").read_text(
            encoding="utf-8"
        )
    )
    source["password_idempotency_secret_service"] = source["session_secret_service"]
    source["password_idempotency_secret_account"] = source["session_secret_account"]
    reused = tmp_path / "reused.json"
    reused.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(SecurityProvisionError, match="must be distinct"):
        _settings(reused)

    source = json.loads(
        (ROOT / "config/migration/user_content_security_production.json").read_text(
            encoding="utf-8"
        )
    )
    source["authentication_proof_secret_version"] = 2
    wrong_version = tmp_path / "wrong-version.json"
    wrong_version.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(SecurityProvisionError, match="version must be 1"):
        _settings(wrong_version)
