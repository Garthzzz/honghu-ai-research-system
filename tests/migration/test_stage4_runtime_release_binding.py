from __future__ import annotations

import pytest

from tools.migration.stage4_runtime_release_binding import (
    RuntimeBindingError,
    bind_runtime,
)


def _runtime() -> dict:
    return {
        "schema_version": "honghu.postgresql_production_runtime.v1",
        "environment_id": "production",
        "application_commit_sha": "a" * 40,
        "host": "127.0.0.1",
        "port": 55440,
        "dbname": "honghu_research",
        "sslmode": "verify-full",
        "sslrootcert": "D:/root.crt",
        "service_name": "HonghuPostgreSQL17",
        "application_route": "sqlite_transition",
        "roles": {},
    }


def test_runtime_binding_changes_only_release_identity_not_authority() -> None:
    source = _runtime()
    result = bind_runtime(source, commit_sha="b" * 40)
    assert source["application_commit_sha"] == "a" * 40
    assert result["application_commit_sha"] == "b" * 40
    assert result["application_route"] == "sqlite_transition"
    assert result["runtime_binding"]["infrastructure_reinstalled"] is False
    assert result["runtime_binding"]["authority_changed"] is False
    assert len(result["runtime_binding_identity_sha256"]) == 64


@pytest.mark.parametrize(
    "field,value",
    [
        ("environment_id", "dev"),
        ("application_route", "postgresql_production"),
        ("sslmode", "require"),
    ],
)
def test_runtime_binding_rejects_wrong_environment_authority_or_tls(
    field: str, value: str
) -> None:
    source = _runtime()
    source[field] = value
    with pytest.raises(RuntimeBindingError):
        bind_runtime(source, commit_sha="b" * 40)


def test_runtime_binding_rejects_non_exact_commit() -> None:
    with pytest.raises(RuntimeBindingError):
        bind_runtime(_runtime(), commit_sha="b" * 12)
