from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pytest

from tools.release.user_content_production import (
    ProductionServeError,
    configure_environment,
    verify_research_content_contracts,
)


@pytest.fixture(autouse=True)
def _restore_production_environment(monkeypatch: pytest.MonkeyPatch):
    names = (
        "HONGHU_DATA_ROOT",
        "HONGHU_CONTENT_ROOT",
        "HONGHU_STATE_ROOT",
        "HONGHU_VIEWER_MODE",
        "HONGHU_RELEASE_COMMIT",
        "HONGHU_RELEASE_MANIFEST",
        "HONGHU_USER_CONTENT_ROUTE_CONFIG",
        "HONGHU_USER_CONTENT_POSTGRES_CONFIG",
        "HONGHU_USER_CONTENT_IDENTITY_MAPPING",
        "HONGHU_USER_CONTENT_SECURITY_CONFIG",
        "HONGHU_PRODUCTION_LAUNCH_ID",
        "HONGHU_SHARED_IDENTITY_ROUTE_CONFIG",
        "HONGHU_SHARED_IDENTITY_POSTGRES_CONFIG",
        "HONGHU_POSTGRES_RUNTIME_CONFIG",
        "HONGHU_CUTOVER_UNIT_REGISTRY",
        "HONGHU_RESEARCH_CONTENT_CONTRACT_COUNT",
        "HONGHU_RESEARCH_CONTENT_FILE_COUNT",
        "HONGHU_RESEARCH_CONTENT_CONTRACT_SHA256",
    )
    for name in names:
        monkeypatch.setenv(name, os.environ.get(name, "__pytest_restore_absent__"))
    yield


def test_research_content_contract_is_hash_bound_and_fail_closed(
    tmp_path: Path,
) -> None:
    release = tmp_path / "release"
    contracts = release / "config" / "research_content_contracts"
    contracts.mkdir(parents=True)
    content = tmp_path / "content"
    document = content / "docs" / "industries" / "光纤.md"
    document.parent.mkdir(parents=True)
    document.write_text("# 光纤行业深度研究\n", encoding="utf-8")
    payload = document.read_bytes()
    (contracts / "optical_fiber.json").write_text(
        json.dumps(
            {
                "schema_version": "honghu.research_content_contract.v1",
                "industry_id": 50,
                "industry_name": "光纤",
                "required_files": [
                    {
                        "path": "docs/industries/光纤.md",
                        "size": len(payload),
                        "sha256": __import__("hashlib").sha256(payload).hexdigest(),
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = verify_research_content_contracts(release, content)
    assert result["contract_count"] == 1
    assert result["file_count"] == 1
    assert len(str(result["sha256"])) == 64

    document.write_text("# 被篡改\n", encoding="utf-8")
    with pytest.raises(ProductionServeError, match="content (size|hash) mismatch"):
        verify_research_content_contracts(release, content)

    document.unlink()
    with pytest.raises(ProductionServeError, match="missing research content"):
        verify_research_content_contracts(release, content)


def _args(tmp_path: Path) -> argparse.Namespace:
    release = tmp_path / "release"
    release.mkdir()
    directories = {}
    for name in ("data", "content", "state"):
        path = tmp_path / name
        path.mkdir()
        directories[name] = path
    files = {}
    for name in ("route", "postgres", "mapping", "security"):
        path = tmp_path / f"{name}.json"
        path.write_text("{}", encoding="utf-8")
        files[name] = path
    return argparse.Namespace(
        release_dir=release,
        expected_commit="a" * 40,
        data_root=directories["data"],
        content_root=directories["content"],
        state_root=directories["state"],
        route_config=files["route"],
        postgres_config=files["postgres"],
        identity_mapping=files["mapping"],
        security_config=files["security"],
        shared_identity_route=None,
        shared_identity_postgres_config=None,
        launch_id="test-launch-id",
    )


def test_production_environment_requires_exact_release_and_fenced_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = _args(tmp_path)
    monkeypatch.setattr(
        "tools.release.user_content_production.verify_release",
        lambda _release: {"commit_sha": "a" * 40},
    )
    args.route_config.write_text(json.dumps({
        "authority_state": "S2",
        "backend": "postgresql_production",
        "sqlite_writer_enabled": False,
        "production_postgresql_enabled": True,
    }), encoding="utf-8")
    configure_environment(args)
    assert __import__("os").environ["HONGHU_USER_CONTENT_ROUTE_CONFIG"] == str(
        args.route_config.resolve()
    )
    assert __import__("os").environ["HONGHU_PRODUCTION_LAUNCH_ID"] == "test-launch-id"

    route = json.loads(args.route_config.read_text(encoding="utf-8"))
    route["sqlite_writer_enabled"] = True
    args.route_config.write_text(json.dumps(route), encoding="utf-8")
    with pytest.raises(ProductionServeError, match="fence SQLite"):
        configure_environment(args)


def test_production_environment_rejects_wrong_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = _args(tmp_path)
    monkeypatch.setattr(
        "tools.release.user_content_production.verify_release",
        lambda _release: {"commit_sha": "b" * 40},
    )
    with pytest.raises(ProductionServeError, match="exact commit"):
        configure_environment(args)


def test_production_environment_accepts_only_paired_fenced_shared_identity_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = _args(tmp_path)
    monkeypatch.setattr(
        "tools.release.user_content_production.verify_release",
        lambda _release: {"commit_sha": "a" * 40},
    )
    args.route_config.write_text(json.dumps({
        "authority_state": "S3",
        "backend": "postgresql_production",
        "sqlite_writer_enabled": False,
        "production_postgresql_enabled": True,
    }), encoding="utf-8")
    shared_route = tmp_path / "shared-route.json"
    shared_runtime = tmp_path / "shared-runtime.json"
    shared_runtime.write_text("{}", encoding="utf-8")
    shared_route.write_text(json.dumps({
        "schema_version": "honghu.cutover_route.v1",
        "cutover_unit": "shared_identity",
        "authority_state": "S3",
        "backend": "postgresql_production",
        "sqlite_writer_enabled": False,
        "production_postgresql_enabled": True,
    }), encoding="utf-8")
    args.shared_identity_route = shared_route
    args.shared_identity_postgres_config = shared_runtime
    configure_environment(args)
    assert __import__("os").environ["HONGHU_SHARED_IDENTITY_ROUTE_CONFIG"] == str(
        shared_route.resolve()
    )

    args.shared_identity_postgres_config = None
    with pytest.raises(ProductionServeError, match="supplied together"):
        configure_environment(args)


def test_common_authority_matrix_replaces_per_unit_runtime_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = _args(tmp_path)
    args.route_config = None
    args.postgres_config = None
    args.identity_mapping = None
    args.postgres_runtime_catalog = tmp_path / "catalog.json"
    args.cutover_unit_registry = tmp_path / "registry.json"
    args.postgres_runtime_catalog.write_text("{}", encoding="utf-8")
    args.cutover_unit_registry.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "tools.release.user_content_production.verify_release",
        lambda _release: {"commit_sha": "a" * 40},
    )
    catalog = type("Catalog", (), {"application_commit_sha": "a" * 40})()
    monkeypatch.setattr(
        "tools.release.user_content_production.load_postgres_runtime_catalog",
        lambda _path: catalog,
    )
    monkeypatch.setattr(
        "tools.release.user_content_production.build_catalog_connection_factory",
        lambda *_a, **_k: object(),
    )
    route = type("Route", (), {"authority_state": type("State", (), {"value": "S3"})()})()
    matrix = type("Matrix", (), {"routes": {"user_content_notes": route, "shared_identity": route}})()
    monkeypatch.setattr(
        "tools.release.user_content_production.load_authority_matrix",
        lambda *_a, **_k: (object(), matrix),
    )
    configure_environment(args)
    assert os.environ["HONGHU_VIEWER_MODE"] == "production_hybrid"
    assert os.environ["HONGHU_CUTOVER_UNIT_REGISTRY"] == str(args.cutover_unit_registry.resolve())

    args.route_config = tmp_path / "legacy-route.json"
    with pytest.raises(ProductionServeError, match="cannot be combined"):
        configure_environment(args)
