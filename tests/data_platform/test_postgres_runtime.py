from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from tools.data_platform.postgres_runtime import PostgresRoleSettings, PostgresRuntimeSettings


def _settings(**overrides) -> PostgresRuntimeSettings:
    values = {
        "enabled": True,
        "host": "db.internal",
        "port": 5432,
        "dbname": "honghu",
        "sslmode": "require",
        "sslrootcert": "",
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


def test_verified_tls_requires_and_passes_exact_root_certificate(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root.crt"
    with pytest.raises(ValueError, match="root certificate"):
        _settings(sslmode="verify-full", sslrootcert=str(root)).validate()

    root.write_text("synthetic public root", encoding="utf-8")
    settings = _settings(sslmode="verify-full", sslrootcert=str(root))
    captured: dict[str, object] = {}
    monkeypatch.setitem(
        sys.modules,
        "psycopg",
        SimpleNamespace(connect=lambda **kwargs: captured.update(kwargs) or object()),
    )
    from tools.data_platform.postgres_runtime import build_postgres_connection_factory

    build_postgres_connection_factory(
        settings,
        role="reader",
        password_loader=lambda _service, _account: "synthetic-password",
    )()
    assert captured["sslmode"] == "verify-full"
    assert captured["sslrootcert"] == str(root)
