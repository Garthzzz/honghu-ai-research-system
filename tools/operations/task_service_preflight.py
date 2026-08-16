from __future__ import annotations

"""Run access and PostgreSQL identity probes as the real task service account."""

import argparse
import getpass
import hashlib
import json
import os
import socket
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.data_platform.postgres_runtime import (
    build_catalog_connection_factory,
    load_postgres_runtime_catalog,
)
from tools.operations.task_credential_transfer import TASK_ROLES, import_transfer
from tools.operations.task_manifest import load_task_manifest


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise RuntimeError("identity document is not an object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _readable(path: Path) -> bool:
    if path.is_file():
        with path.open("rb") as handle:
            handle.read(1)
        return True
    if path.is_dir():
        next(path.iterdir(), None)
        return True
    return False


def _write_is_denied(directory: Path) -> bool:
    probe = directory / f".honghu-stage5-readonly-probe-{uuid.uuid4().hex}.tmp"
    try:
        with probe.open("xb") as handle:
            handle.write(b"permission-probe")
            handle.flush()
            os.fsync(handle.fileno())
    except (PermissionError, OSError):
        return not probe.exists()
    else:
        return False
    finally:
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass


def _writable(directory: Path) -> bool:
    probe = directory / f".honghu-stage5-writable-probe-{uuid.uuid4().hex}.tmp"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with probe.open("xb") as handle:
            handle.write(b"runtime-probe")
            handle.flush()
            os.fsync(handle.fileno())
        return probe.read_bytes() == b"runtime-probe"
    finally:
        probe.unlink(missing_ok=True)


def run_service_account_preflight(
    *,
    release_dir: Path,
    site_packages: Path,
    manifest_path: Path,
    runtime_catalog_path: Path,
    registry_path: Path,
    runtime_dir: Path,
    data_root: Path,
    content_root: Path,
    expected_principal: str,
) -> dict[str, Any]:
    release_dir = release_dir.resolve()
    manifest = load_task_manifest(manifest_path)
    release_identity = _json(release_dir / "RELEASE_MANIFEST.json")
    commit = str(release_identity.get("commit_sha") or "").lower()
    if len(commit) != 40:
        raise RuntimeError("exact release commit identity is missing")
    current_principal = getpass.getuser()
    expected_leaf = expected_principal.rsplit("\\", 1)[-1]
    if current_principal.casefold() != expected_leaf.casefold():
        raise RuntimeError("preflight is not running as the reviewed task principal")
    if socket.gethostname().upper() != manifest.runner_host:
        raise RuntimeError("preflight is not running on the reviewed task host")

    read_only_roots = {
        "release": release_dir,
        "release_config": (release_dir / "config").resolve(),
        "locked_site_packages": site_packages.resolve(),
        "data": data_root.resolve(),
        "content": content_root.resolve(),
        "postgres_runtime_config": runtime_catalog_path.resolve().parent,
    }
    access: dict[str, dict[str, bool]] = {}
    for name, path in read_only_roots.items():
        access[name] = {
            "readable": _readable(path),
            "write_denied": _write_is_denied(path),
        }
    writable_roots = {
        "runtime": runtime_dir.resolve(),
        "lock": (runtime_dir / "locks").resolve(),
        "log": (runtime_dir / "task_logs").resolve(),
        "evidence": (runtime_dir / "evidence").resolve(),
    }
    writable = {name: _writable(path) for name, path in writable_roots.items()}

    catalog = load_postgres_runtime_catalog(runtime_catalog_path)
    roles = []
    for role_name in sorted(TASK_ROLES):
        expected_user = catalog.role(role_name).user
        connection = build_catalog_connection_factory(catalog, role=role_name)()
        try:
            current_user, current_database, tls = connection.execute(
                "SELECT current_user,current_database(),current_setting('ssl')"
            ).fetchone()
        finally:
            connection.close()
        roles.append(
            {
                "role": role_name,
                "expected_user": expected_user,
                "current_user": str(current_user),
                "current_database": str(current_database),
                "current_user_correct": str(current_user) == expected_user,
                "database_correct": str(current_database) == catalog.dbname,
                "tls_enabled": str(tls).casefold() == "on",
            }
        )
    access_ok = all(
        item["readable"] and item["write_denied"] for item in access.values()
    ) and all(writable.values())
    roles_ok = len(roles) == len(TASK_ROLES) and all(
        item["current_user_correct"] and item["database_correct"] and item["tls_enabled"]
        for item in roles
    )
    return {
        "schema_version": "honghu.production_task_service_preflight.v1",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "runner_host": manifest.runner_host,
        "principal": expected_principal,
        "application_commit_sha": commit,
        "release_manifest_sha256": _sha256(release_dir / "RELEASE_MANIFEST.json"),
        "task_manifest_sha256": manifest.sha256,
        "runtime_catalog_sha256": _sha256(runtime_catalog_path),
        "cutover_registry_sha256": _sha256(registry_path),
        "access": access,
        "writable": writable,
        "postgresql_roles": roles,
        "access_verified": access_ok,
        "postgresql_roles_verified": roles_ok,
        "overall_verified": access_ok and roles_ok,
        "secret_recorded": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credential-transfer", type=Path, required=True)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--site-packages", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--runtime-catalog", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--content-root", type=Path, required=True)
    parser.add_argument("--expected-principal", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result: dict[str, Any]
    try:
        transfer = import_transfer(args.credential_transfer, args.runtime_catalog)
        result = run_service_account_preflight(
            release_dir=args.release_dir,
            site_packages=args.site_packages,
            manifest_path=args.manifest,
            runtime_catalog_path=args.runtime_catalog,
            registry_path=args.registry,
            runtime_dir=args.runtime_dir,
            data_root=args.data_root,
            content_root=args.content_root,
            expected_principal=args.expected_principal,
        )
        result["credential_transfer_verified"] = bool(transfer.get("verified"))
        result["credential_transfer_removed"] = not args.credential_transfer.exists()
        result["overall_verified"] = bool(
            result["overall_verified"]
            and result["credential_transfer_verified"]
            and result["credential_transfer_removed"]
        )
    except Exception as exc:
        result = {
            "schema_version": "honghu.production_task_service_preflight.v1",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "overall_verified": False,
            "failure_class": type(exc).__name__,
            "secret_recorded": False,
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "schema_version": result["schema_version"],
                "overall_verified": bool(result.get("overall_verified")),
                "secret_recorded": False,
            },
            sort_keys=True,
        )
    )
    return 0 if result.get("overall_verified") else 1


if __name__ == "__main__":
    raise SystemExit(main())
