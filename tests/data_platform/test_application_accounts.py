from __future__ import annotations

import pytest
from werkzeug.security import check_password_hash

from tools.data_platform.application_accounts import (
    ALLOWED_PERMISSIONS,
    normalize_subject,
    password_hash,
    validate_password,
    validate_permissions,
    _translate,
)


def test_subject_and_permission_catalog_fail_closed() -> None:
    assert normalize_subject("  Research-User_1 ") == "research-user_1"
    with pytest.raises(ValueError):
        normalize_subject("管理员")
    with pytest.raises(ValueError, match="未授权"):
        validate_permissions(["account_admin:read", "windows:admin"])
    with pytest.raises(ValueError, match="同时包含"):
        validate_permissions(["account_admin:manage"])
    assert set(validate_permissions(ALLOWED_PERMISSIONS)) == set(ALLOWED_PERMISSIONS)


def test_password_policy_and_irreversible_scrypt_hash() -> None:
    with pytest.raises(ValueError):
        validate_password("analyst", "password123")
    with pytest.raises(ValueError):
        validate_password("analyst", "Analyst-Strong-2026!")
    encoded = password_hash("analyst", "Strong-Research-2026!")
    assert encoded.startswith("scrypt:32768:8:1$")
    assert "Strong-Research-2026!" not in encoded
    assert check_password_hash(encoded, "Strong-Research-2026!")


def test_postgres_error_text_is_not_exposed_to_http_layer() -> None:
    class Error(Exception):
        sqlstate = "42501"

    error = _translate(Error("secret schema.function_name and internal detail"))
    assert "schema.function" not in str(error)
    assert "secret" not in str(error)
