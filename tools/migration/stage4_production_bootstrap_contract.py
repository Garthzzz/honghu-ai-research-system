from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from tools.migration.stage4_json_io import read_json


class BootstrapContractError(RuntimeError):
    pass


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_VERSION = "17.10"
EXPECTED_SOURCE_HOST = "get.enterprisedb.com"


def _sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_and_validate_config(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    if payload.get("schema_version") != "honghu.stage4_production_postgresql_bootstrap.v1":
        raise BootstrapContractError("unsupported production bootstrap schema")
    if payload.get("environment_id") != "production":
        raise BootstrapContractError("bootstrap environment must be production")
    pg = payload.get("postgresql") or {}
    if pg.get("version") != EXPECTED_VERSION:
        raise BootstrapContractError("PostgreSQL version is not the approved fixed version")
    archive_sha = str(pg.get("archive_sha256") or "")
    if not SHA256_RE.fullmatch(archive_sha):
        raise BootstrapContractError("PostgreSQL archive SHA256 is invalid")
    source = urlparse(str(pg.get("source_url") or ""))
    if source.scheme != "https" or source.hostname != EXPECTED_SOURCE_HOST:
        raise BootstrapContractError("PostgreSQL archive source is not approved")
    if pg.get("host") != "127.0.0.1":
        raise BootstrapContractError("initial production topology must remain loopback-only")
    expected_cluster_contract = {
        "encoding": "UTF8",
        "locale_provider": "builtin",
        "builtin_locale": "C.UTF-8",
        "text_search_config": "simple",
        "data_checksums": True,
    }
    actual_cluster_contract = {
        key: pg.get(key) for key in expected_cluster_contract
    }
    if actual_cluster_contract != expected_cluster_contract:
        raise BootstrapContractError(
            "PostgreSQL cluster locale/encoding/checksum contract is not approved"
        )
    if pg.get("allowed_cidrs") != ["127.0.0.1/32", "::1/128"]:
        raise BootstrapContractError("initial PostgreSQL network scope is broader than approved")
    ports = {int(pg.get("port") or 0), int(pg.get("restore_test_port") or 0)}
    if len(ports) != 2 or any(port <= 1024 or port in {8080, 18080, 5432} for port in ports):
        raise BootstrapContractError("PostgreSQL ports are unsafe or ambiguous")
    guard = payload.get("authority_guard") or {}
    expected_guard = {
        "allowed_states": ["S0", "S1"],
        "required_backend": "sqlite_transition",
        "sqlite_writer_enabled": True,
        "production_postgresql_enabled": False,
        "forbid_s2_s3": True,
        "forbid_formal_business_mutation": True,
        "forbid_dual_or_shadow_write": True,
    }
    if guard != expected_guard:
        raise BootstrapContractError("authority guard does not preserve the S0/S1 boundary")
    return payload


def validate_inputs(
    *, config_path: Path, repo_root: Path, commit_sha: str, archive_path: Path
) -> dict[str, Any]:
    config = load_and_validate_config(config_path)
    if not GIT_SHA_RE.fullmatch(commit_sha):
        raise BootstrapContractError("full lowercase Git SHA is required")
    if not archive_path.is_file():
        raise FileNotFoundError(archive_path)
    actual_archive_sha = _file_sha(archive_path)
    expected_archive_sha = config["postgresql"]["archive_sha256"]
    if actual_archive_sha != expected_archive_sha:
        raise BootstrapContractError("PostgreSQL archive hash mismatch")
    route_path = repo_root / config["source"]["tracked_route"]
    route = read_json(route_path)
    guard = config["authority_guard"]
    if route.get("authority_state") not in guard["allowed_states"]:
        raise BootstrapContractError("tracked route is outside S0/S1")
    if route.get("backend") != guard["required_backend"]:
        raise BootstrapContractError("tracked authority backend is not SQLite")
    if route.get("sqlite_writer_enabled") is not guard["sqlite_writer_enabled"]:
        raise BootstrapContractError("tracked SQLite writer is not enabled")
    if route.get("production_postgresql_enabled") is not guard["production_postgresql_enabled"]:
        raise BootstrapContractError("tracked PostgreSQL application route is enabled")
    identity = {
        "application_commit_sha": commit_sha,
        "bootstrap_config_sha256": _file_sha(config_path),
        "archive_sha256": actual_archive_sha,
        "tracked_route_sha256": _file_sha(route_path),
        "authority_state": route["authority_state"],
        "authoritative_backend": route["backend"],
    }
    return {**identity, "input_identity_sha256": _sha(identity)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = validate_inputs(
        config_path=args.config,
        repo_root=args.repo_root,
        commit_sha=args.commit_sha,
        archive_path=args.archive,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
