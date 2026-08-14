from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from tools.release.user_content_production import (
    ProductionServeError,
    configure_environment,
)


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
