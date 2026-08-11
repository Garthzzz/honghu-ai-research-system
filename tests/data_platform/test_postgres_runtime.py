from __future__ import annotations

import pytest

from tools.data_platform.postgres_runtime import PostgresRoleSettings, PostgresRuntimeSettings


def _settings(**overrides) -> PostgresRuntimeSettings:
    values = {
        "enabled": True,
        "host": "db.internal",
        "port": 5432,
        "dbname": "honghu",
        "sslmode": "require",
        "connect_timeout_seconds": 5,
        "reader": PostgresRoleSettings("reader", "service", "reader"),
        "writer": PostgresRoleSettings("writer", "service", "writer"),
    }
    values.update(overrides)
    return PostgresRuntimeSettings(**values)


def test_production_runtime_requires_explicit_enable_and_protected_transport() -> None:
    with pytest.raises(ValueError, match="not explicitly enabled"):
        _settings(enabled=False).validate()
    with pytest.raises(ValueError, match="protected transport"):
        _settings(sslmode="disable").validate()


def test_reader_and_writer_roles_must_be_distinct() -> None:
    with pytest.raises(ValueError, match="must be distinct"):
        _settings(
            reader=PostgresRoleSettings("same", "service", "reader"),
            writer=PostgresRoleSettings("same", "service", "writer"),
        ).validate()
