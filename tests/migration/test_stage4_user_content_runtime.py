from __future__ import annotations

from pathlib import Path

import pytest

from tools.migration.stage4_user_content_runtime import (
    UserContentRuntimeError,
    compile_viewer_runtime,
)


def _source(root: Path) -> dict:
    return {
        "schema_version": "honghu.postgresql_production_runtime.v1",
        "environment_id": "production",
        "tracked_static_default_route": "sqlite_transition",
        "application_route": "sqlite_transition",
        "host": "localhost",
        "port": 55440,
        "dbname": "honghu_research",
        "sslmode": "verify-full",
        "sslrootcert": str(root),
        "roles": {
            "reader": {
                "user": "reader",
                "credential_service": "reader-service",
                "credential_account": "reader",
            },
            "writer_user_content_notes": {
                "user": "writer",
                "credential_service": "writer-service",
                "credential_account": "writer",
            },
        },
    }


def test_runtime_compiler_preserves_verified_tls_and_only_credential_identity(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root.crt"
    root.write_text("public certificate", encoding="utf-8")
    result = compile_viewer_runtime(_source(root))
    assert result["schema_version"] == "honghu.postgresql_runtime.v2"
    assert result["sslmode"] == "verify-full"
    assert result["sslrootcert"] == str(root.resolve())
    assert result["reader"]["user"] == "reader"
    assert "password" not in str(result).lower()
    assert len(result["runtime_identity_sha256"]) == 64


def test_runtime_compiler_fails_closed_on_wrong_authority_tls_or_roles(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.crt"
    with pytest.raises(UserContentRuntimeError, match="root certificate"):
        compile_viewer_runtime(_source(missing))
    root = tmp_path / "root.crt"
    root.write_text("public certificate", encoding="utf-8")
    source = _source(root)
    source["tracked_static_default_route"] = "postgresql_production"
    with pytest.raises(UserContentRuntimeError, match="conflicts|static default route"):
        compile_viewer_runtime(source)
    source = _source(root)
    source["roles"]["writer_user_content_notes"] = dict(source["roles"]["reader"])
    with pytest.raises(UserContentRuntimeError, match="distinct"):
        compile_viewer_runtime(source)


def test_runtime_compiler_rejects_generic_writer_instead_of_unit_role(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root.crt"
    root.write_text("public certificate", encoding="utf-8")
    source = _source(root)
    source["roles"]["writer"] = source["roles"].pop("writer_user_content_notes")
    with pytest.raises(UserContentRuntimeError, match="writer_user_content_notes"):
        compile_viewer_runtime(source)
