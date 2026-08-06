from __future__ import annotations

"""Build and operate exact-commit immutable application releases.

This module deliberately does not copy databases, papers, backups, credentials,
or user content.  A release is code from one Git commit; external runtime
authorities are attached explicitly during preflight and process launch.
"""

import hashlib
import copy
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


POLICY_RELATIVE = Path("config/deployment_policy.json")
COMPATIBILITY_RELATIVE = Path("config/release_schema_compatibility.json")
MANIFEST_NAME = "RELEASE_MANIFEST.json"
MANIFEST_HASH_NAME = "RELEASE_MANIFEST.sha256"
CURRENT_POINTER_NAME = "current"
LEDGER_RELATIVE = Path("runtime/deployment_ledger.jsonl")
QUARANTINE_RELATIVE = Path("runtime/release_quarantine")
CANDIDATE_PROCESS_RECORD_RELATIVE = Path("runtime/viewer_candidate_process.json")
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_RELEASE_HEALTH_CACHE: dict[tuple[str, str], dict[str, Any]] = {}


class ReleaseError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical_json(payload: object) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _compatibility_fingerprint(compatibility: Mapping[str, Any]) -> str:
    return _sha256_bytes(_canonical_json(dict(compatibility)))


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_json(payload))


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ReleaseError(f"expected JSON object: {path}")
    return value


def _git(repo_root: Path, *args: str, binary: bool = False) -> str | bytes:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise ReleaseError(f"git {' '.join(args)} failed: {message}")
    return result.stdout if binary else result.stdout.decode("utf-8", errors="strict")


def resolve_commit(repo_root: Path, commit: str) -> str:
    sha = str(_git(repo_root, "rev-parse", "--verify", f"{commit}^{{commit}}")).strip().lower()
    if not FULL_SHA_RE.fullmatch(sha):
        raise ReleaseError(f"not a full commit SHA: {sha}")
    return sha


def _tree_paths(repo_root: Path, sha: str) -> list[str]:
    raw = _git(repo_root, "ls-tree", "-r", "--name-only", "-z", sha, binary=True)
    assert isinstance(raw, bytes)
    paths = [item.decode("utf-8") for item in raw.split(b"\0") if item]
    if len(paths) != len(set(paths)):
        raise ReleaseError("commit tree contains duplicate path identities")
    return sorted(paths)


def _normalized_relative(value: str) -> str:
    normalized = value.replace("\\", "/").lstrip("/")
    parts = Path(normalized).parts
    if not normalized or ".." in parts or Path(normalized).is_absolute():
        raise ReleaseError(f"unsafe repository path: {value}")
    return normalized


def _external_content_contracts(
    closure: object,
) -> list[dict[str, str]]:
    """Normalize manifest-declared content paths and their presence contract.

    Older immutable releases used a plain ``paths`` list.  It remains readable
    as a strict required-path contract for code-only rollback inspection, while
    new releases must use ``path_contracts`` to distinguish required content
    from optional page enhancements.
    """

    if not isinstance(closure, list):
        raise ReleaseError("external runtime closure must be a list")
    records: list[dict[str, str]] = []
    seen: set[str] = set()
    for group in closure:
        if not isinstance(group, Mapping) or group.get("authority") != "content_root":
            continue
        raw_contracts = group.get("path_contracts")
        if raw_contracts is None:
            raw_contracts = [
                {"path": item, "presence": "required", "kind": "directory"}
                for item in group.get("paths", [])
            ]
        if not isinstance(raw_contracts, list):
            raise ReleaseError("content path_contracts must be a list")
        for raw in raw_contracts:
            if not isinstance(raw, Mapping):
                raise ReleaseError("content path contract must be an object")
            relative = _normalized_relative(str(raw.get("path") or ""))
            presence = str(raw.get("presence") or "").lower()
            kind = str(raw.get("kind") or "directory").lower()
            if presence not in {"required", "optional"}:
                raise ReleaseError(
                    f"unsupported content presence contract for {relative}: {presence}"
                )
            if kind not in {"directory", "file"}:
                raise ReleaseError(f"unsupported content path kind for {relative}: {kind}")
            if relative in seen:
                raise ReleaseError(f"duplicate external content path contract: {relative}")
            seen.add(relative)
            records.append(
                {
                    "path": relative,
                    "presence": presence,
                    "kind": kind,
                    "purpose": str(raw.get("purpose") or ""),
                }
            )
    return records


def _matches_policy(path: str, policy: Mapping[str, Any]) -> bool:
    exact = {str(item) for item in policy.get("include_exact", [])}
    prefixes = tuple(str(item) for item in policy.get("include_prefixes", []))
    return path in exact or path.startswith(prefixes)


def _assert_not_forbidden(path: str, policy: Mapping[str, Any]) -> None:
    lowered = path.lower()
    for prefix in policy.get("forbidden_prefixes", []):
        if lowered.startswith(str(prefix).lower()):
            raise ReleaseError(f"forbidden release path selected: {path}")
    for suffix in policy.get("forbidden_suffixes", []):
        if lowered.endswith(str(suffix).lower()):
            raise ReleaseError(f"forbidden release suffix selected: {path}")


def selected_deployment_paths(
    repo_root: Path, sha: str, policy: Mapping[str, Any]
) -> tuple[list[str], list[str]]:
    selected: list[str] = []
    governance_only: list[str] = []
    for raw in _tree_paths(repo_root, sha):
        path = _normalized_relative(raw)
        if _matches_policy(path, policy):
            _assert_not_forbidden(path, policy)
            selected.append(path)
        else:
            governance_only.append(path)
    if not selected:
        raise ReleaseError("deployment policy selected no files")
    required = {str(item) for item in policy.get("include_exact", [])}
    missing = sorted(required - set(selected))
    if missing:
        raise ReleaseError(f"deployment policy requires untracked files: {missing}")
    return selected, governance_only


def _manifest_hash(release_dir: Path) -> str:
    return _sha256_file(release_dir / MANIFEST_NAME)


def verify_release(release_dir: str | Path) -> dict[str, Any]:
    root = Path(release_dir).resolve()
    manifest_path = root / MANIFEST_NAME
    hash_path = root / MANIFEST_HASH_NAME
    if not manifest_path.is_file() or not hash_path.is_file():
        raise ReleaseError(f"release metadata missing: {root}")
    manifest = _load_json(manifest_path)
    expected_manifest_hash = hash_path.read_text(encoding="ascii").strip().lower()
    actual_manifest_hash = _manifest_hash(root)
    if expected_manifest_hash != actual_manifest_hash:
        raise ReleaseError("release manifest hash mismatch")
    expected: dict[str, dict[str, Any]] = {
        str(item["path"]): item for item in manifest.get("files", [])
    }
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
        and path.name not in {MANIFEST_NAME, MANIFEST_HASH_NAME}
    }
    if actual != set(expected):
        missing = sorted(set(expected) - actual)
        extra = sorted(actual - set(expected))
        raise ReleaseError(f"release file set mismatch; missing={missing[:5]}, extra={extra[:5]}")
    for relative, record in expected.items():
        path = root / relative
        if path.stat().st_size != int(record["size"]):
            raise ReleaseError(f"release size mismatch: {relative}")
        if _sha256_file(path) != str(record["sha256"]):
            raise ReleaseError(f"release content mismatch: {relative}")
    manifest["manifest_sha256"] = actual_manifest_hash
    return manifest


def _existing_release_inventory(release_dir: Path) -> dict[str, Any]:
    """Describe an invalid release without changing it or exposing file content."""

    files = sorted(
        path.relative_to(release_dir).as_posix()
        for path in release_dir.rglob("*")
        if path.is_file()
    )
    return {
        "file_count": len(files),
        "relative_paths_sha256": _sha256_bytes(
            ("\n".join(files) + "\n").encode("utf-8")
        ),
        "bytecode_paths": [
            path for path in files if path.lower().endswith((".pyc", ".pyo"))
        ],
        "manifest_identity": (
            _sha256_file(release_dir / MANIFEST_NAME)
            if (release_dir / MANIFEST_NAME).is_file()
            else None
        ),
    }


def _release_protection_reason(deploy_root: Path, sha: str) -> str | None:
    """Fail closed when an invalid release may be current or running.

    A stale process record is intentionally treated as protection.  The
    Windows deployer must first validate/remove it through
    ``Stop-HonghuVerifiedCandidate``; the builder never guesses process state.
    """

    current_path = deploy_root / CURRENT_POINTER_NAME
    if current_path.exists():
        try:
            current = _load_json(current_path)
        except Exception as exc:
            return f"current pointer is unreadable ({type(exc).__name__})"
        if str(current.get("commit_sha") or "").lower() == sha:
            return "release is referenced by current pointer"

    process_record_path = deploy_root / CANDIDATE_PROCESS_RECORD_RELATIVE
    if process_record_path.exists():
        try:
            process_record = _load_json(process_record_path)
        except Exception as exc:
            return f"candidate process record is unreadable ({type(exc).__name__})"
        if str(process_record.get("commit_sha") or "").lower() == sha:
            return "release is referenced by candidate process record"
    return None


def _quarantine_invalid_release(
    deploy_root: Path,
    target: Path,
    *,
    sha: str,
    verification_error: str,
) -> dict[str, Any]:
    protection = _release_protection_reason(deploy_root, sha)
    if protection:
        raise ReleaseError(
            f"invalid release is protected and cannot be quarantined automatically: {protection}"
        )
    if target.is_symlink():
        raise ReleaseError("invalid release path is a symlink; refusing automatic quarantine")

    quarantine_root = deploy_root / QUARANTINE_RELATIVE
    quarantine_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    identity = f"{sha}-{stamp}-{uuid.uuid4().hex[:12]}"
    quarantine_path = quarantine_root / identity
    inventory = _existing_release_inventory(target)
    target.rename(quarantine_path)
    record = {
        "schema_version": "honghu.release_quarantine.v1",
        "quarantine_id": identity,
        "recorded_at": _utc_now(),
        "commit_sha": sha,
        "reason": "existing_release_failed_exact_verification",
        "verification_error": verification_error,
        "original_path": str(target),
        "quarantined_path": str(quarantine_path),
        "inventory": inventory,
        "current_pointer_protected": False,
        "candidate_process_record_protected": False,
    }
    record_path = quarantine_root / f"{identity}.json"
    _write_json(record_path, record)
    record["record_path"] = str(record_path)
    return record


def build_release(
    repo_root: str | Path,
    deploy_root: str | Path,
    *,
    commit: str,
    quarantine_invalid_inactive: bool = False,
) -> dict[str, Any]:
    repo = Path(repo_root).resolve()
    deploy = Path(deploy_root).resolve()
    sha = resolve_commit(repo, commit)
    policy_bytes = _git(repo, "show", f"{sha}:{POLICY_RELATIVE.as_posix()}", binary=True)
    compatibility_bytes = _git(
        repo, "show", f"{sha}:{COMPATIBILITY_RELATIVE.as_posix()}", binary=True
    )
    assert isinstance(policy_bytes, bytes) and isinstance(compatibility_bytes, bytes)
    policy = json.loads(policy_bytes.decode("utf-8"))
    compatibility = json.loads(compatibility_bytes.decode("utf-8"))
    if policy.get("schema_version") != "honghu.deployment_policy.v1":
        raise ReleaseError("unsupported deployment policy")
    if compatibility.get("schema_version") != "honghu.release_schema_compatibility.v1":
        raise ReleaseError("unsupported schema compatibility contract")
    _external_content_contracts(policy.get("external_runtime_closure", []))
    selected, governance_only = selected_deployment_paths(repo, sha, policy)
    source_commit_time = str(
        _git(repo, "show", "-s", "--format=%cI", sha)
    ).strip()
    releases_root = deploy / "releases"
    target = releases_root / sha
    releases_root.mkdir(parents=True, exist_ok=True)
    quarantine_record: dict[str, Any] | None = None
    if target.exists():
        try:
            existing = verify_release(target)
        except ReleaseError as exc:
            if not quarantine_invalid_inactive:
                raise
            quarantine_record = _quarantine_invalid_release(
                deploy,
                target,
                sha=sha,
                verification_error=str(exc),
            )
        else:
            if existing.get("commit_sha") != sha:
                raise ReleaseError(f"existing release identity mismatch: {target}")
            existing["build_disposition"] = "reused_verified_release"
            return existing

    staging = releases_root / f".{sha}.staging-{os.getpid()}-{uuid.uuid4().hex}"
    staging.mkdir(parents=False)
    records: list[dict[str, Any]] = []
    try:
        for relative in selected:
            payload = _git(repo, "show", f"{sha}:{relative}", binary=True)
            assert isinstance(payload, bytes)
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
            records.append(
                {"path": relative, "size": len(payload), "sha256": _sha256_bytes(payload)}
            )
        manifest = {
            "schema_version": "honghu.application_release.v1",
            "commit_sha": sha,
            # This is commit metadata, not the wall-clock build time. Keeping
            # the manifest deterministic makes the same commit produce the
            # same release identity on every clean host.
            "source_commit_time": source_commit_time,
            "file_count": len(records),
            "content_bytes": sum(int(item["size"]) for item in records),
            "files": records,
            "deployment_policy_sha256": _sha256_bytes(policy_bytes),
            "schema_compatibility_sha256": _sha256_bytes(compatibility_bytes),
            "schema_compatibility": compatibility,
            "external_runtime_closure": policy.get("external_runtime_closure", []),
            "governance_tracked_count": len(governance_only),
            "governance_tracked_paths_sha256": _sha256_bytes(
                ("\n".join(governance_only) + "\n").encode("utf-8")
            ),
            "contains_live_data": False,
            "contains_papers_or_evidence": False,
            "contains_secrets": False,
        }
        _write_json(staging / MANIFEST_NAME, manifest)
        (staging / MANIFEST_HASH_NAME).write_text(
            _manifest_hash(staging) + "\n", encoding="ascii"
        )
        verify_release(staging)
        staging.rename(target)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    result = verify_release(target)
    result["build_disposition"] = (
        "quarantined_invalid_inactive_and_rebuilt"
        if quarantine_record is not None
        else "built_new_release"
    )
    if quarantine_record is not None:
        result["quarantine_record"] = {
            "quarantine_id": quarantine_record["quarantine_id"],
            "record_path": quarantine_record["record_path"],
            "verification_error": quarantine_record["verification_error"],
            "inventory": quarantine_record["inventory"],
        }
    return result


def _sqlite_tables(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def _safe_sqlite_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ReleaseError(f"unsafe SQLite contract identifier: {value!r}")
    return value


def _read_contract_objects(conn: sqlite3.Connection) -> dict[str, str]:
    return {
        str(row[0]): str(row[1])
        for row in conn.execute(
            "SELECT name,type FROM sqlite_master "
            "WHERE type IN ('table','view','index','trigger')"
        )
    }


def _contract_columns(conn: sqlite3.Connection, object_name: str) -> set[str]:
    name = _safe_sqlite_identifier(object_name)
    return {str(row[1]) for row in conn.execute(f'PRAGMA table_info("{name}")')}


def _run_readonly_probe(conn: sqlite3.Connection, sql: str) -> None:
    normalized = sql.strip().rstrip(";").strip()
    if ";" in normalized or not re.match(r"^(SELECT|WITH|PRAGMA)\b", normalized, re.I):
        raise ReleaseError("schema compatibility probes must be one read-only statement")
    conn.execute(normalized).fetchone()


def inspect_sqlite_contract(
    data_root: str | Path, compatibility: Mapping[str, Any]
) -> dict[str, Any]:
    root = Path(data_root).resolve()
    results: dict[str, Any] = {}
    failures: list[str] = []
    database_contracts = compatibility.get("databases")
    if not isinstance(database_contracts, Mapping):
        database_contracts = {
            name: {
                "required_objects": {
                    str(table): {"type": "table", "required_columns": []}
                    for table in required_values
                }
            }
            for name, required_values in compatibility.get("required_tables", {}).items()
        }
    for name, raw_contract in database_contracts.items():
        contract = raw_contract if isinstance(raw_contract, Mapping) else {}
        path = root / str(name)
        if not path.is_file():
            failures.append(f"missing database: {name}")
            continue
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5)
            conn.execute("PRAGMA query_only=ON")
            query_only = int(conn.execute("PRAGMA query_only").fetchone()[0]) == 1
            if not query_only:
                failures.append(f"{name}: read-only inspection did not enable query_only")
            tables = _sqlite_tables(conn)
            objects = _read_contract_objects(conn)
            required_objects = contract.get("required_objects", {})
            object_failures: list[str] = []
            checked_objects: dict[str, Any] = {}
            for object_name, raw_requirement in required_objects.items():
                requirement = raw_requirement if isinstance(raw_requirement, Mapping) else {}
                expected_type = str(requirement.get("type", "table"))
                actual_type = objects.get(str(object_name))
                required_columns = {
                    str(column) for column in requirement.get("required_columns", [])
                }
                actual_columns = (
                    _contract_columns(conn, str(object_name)) if actual_type in {"table", "view"} else set()
                )
                missing_columns = sorted(required_columns - actual_columns)
                if actual_type != expected_type:
                    object_failures.append(
                        f"{object_name} expected {expected_type}, found {actual_type or 'missing'}"
                    )
                if missing_columns:
                    object_failures.append(
                        f"{object_name} missing columns {missing_columns}"
                    )
                checked_objects[str(object_name)] = {
                    "expected_type": expected_type,
                    "actual_type": actual_type,
                    "required_columns_present": not missing_columns,
                    "missing_columns": missing_columns,
                }
            user_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            version_range = contract.get("user_version", {})
            min_version = version_range.get("min") if isinstance(version_range, Mapping) else None
            max_version = version_range.get("max") if isinstance(version_range, Mapping) else None
            if min_version is not None and user_version < int(min_version):
                object_failures.append(f"user_version {user_version} below {min_version}")
            if max_version is not None and user_version > int(max_version):
                object_failures.append(f"user_version {user_version} above {max_version}")
            probe_results: list[dict[str, Any]] = []
            for index, raw_probe in enumerate(contract.get("probe_queries", []), start=1):
                probe = raw_probe if isinstance(raw_probe, Mapping) else {"sql": raw_probe}
                probe_id = str(probe.get("id") or f"probe-{index}")
                try:
                    _run_readonly_probe(conn, str(probe.get("sql") or ""))
                    probe_results.append({"id": probe_id, "ok": True})
                except Exception as exc:
                    object_failures.append(f"probe {probe_id} failed: {type(exc).__name__}: {exc}")
                    probe_results.append({"id": probe_id, "ok": False})
            schema_rows = [
                f"{row[0]}:{row[1] or ''}"
                for row in conn.execute(
                    "SELECT name, sql FROM sqlite_master "
                    "WHERE type IN ('table','index','view','trigger') ORDER BY type,name"
                )
            ]
            schema_fingerprint = _sha256_bytes(
                ("\n".join(schema_rows) + "\n").encode("utf-8")
            )
            fingerprint_policy = contract.get("schema_fingerprint", {})
            accepted_fingerprints = {
                str(value).lower()
                for value in (
                    fingerprint_policy.get("accepted", [])
                    if isinstance(fingerprint_policy, Mapping)
                    else []
                )
            }
            fingerprint_mode = (
                str(fingerprint_policy.get("mode", "audit_only"))
                if isinstance(fingerprint_policy, Mapping)
                else "audit_only"
            )
            if fingerprint_mode == "enforced" and schema_fingerprint not in accepted_fingerprints:
                object_failures.append("schema fingerprint is not in the accepted set")
            if object_failures:
                failures.extend(f"{name}: {message}" for message in object_failures)
            results[str(name)] = {
                "backend": "sqlite-transition",
                "connection_mode": "ro",
                "query_only": query_only,
                "user_version": user_version,
                "table_count": len(tables),
                "required_objects": checked_objects,
                "probe_queries": probe_results,
                "schema_fingerprint": schema_fingerprint,
                "schema_fingerprint_mode": fingerprint_mode,
                "declared_contract_compatible": not object_failures,
            }
        except Exception as exc:
            failures.append(f"{name} read-only inspection failed: {type(exc).__name__}: {exc}")
        finally:
            if conn is not None:
                conn.close()
    return {
        "backend": "sqlite-transition",
        "compatibility_scope": compatibility.get(
            "compatibility_scope", "declared_read_contract"
        ),
        "compatibility_contract_sha256": _compatibility_fingerprint(compatibility),
        "compatible": not failures,
        "databases": results,
        "failures": failures,
    }


def preflight_release(
    release_dir: str | Path,
    *,
    data_root: str | Path,
    content_root: str | Path,
    state_root: str | Path,
) -> dict[str, Any]:
    release = Path(release_dir).resolve()
    manifest = verify_release(release)
    compatibility = manifest["schema_compatibility"]
    schema_report = inspect_sqlite_contract(data_root, compatibility)
    failures = list(schema_report["failures"])
    code_requirements = [
        "config/research_workflow.yaml",
        "config/battery_calculator_models/battery_calculator_model_v1.json",
        "config/copper_calculator_models/copper_calculator_model_v1.json",
        "config/lithium_calculator_models/lithium_company_independent_models_v1.json",
        "config/lithium_calculator_models/lithium_external_reconciliation_v1.json",
        "config/lithium_calculator_project_ledger.json",
        "requirements.lock.txt",
        "tools/viewer/app.py",
        "tools/viewer/templates",
        "tools/viewer/static",
        "tools/viewer/static/vendor/plotly.min.js",
    ]
    for relative in code_requirements:
        if not (release / relative).exists():
            failures.append(f"missing release code path: {relative}")
    content = Path(content_root).resolve()
    content_checks: list[dict[str, Any]] = []
    required_missing: list[str] = []
    optional_missing: list[str] = []
    invalid_paths: list[str] = []
    content_contracts = _external_content_contracts(
        manifest.get("external_runtime_closure", [])
    )
    for contract in content_contracts:
        relative = contract["path"]
        candidate = content / relative
        present = candidate.is_dir() if contract["kind"] == "directory" else candidate.is_file()
        exists_with_wrong_kind = candidate.exists() and not present
        if exists_with_wrong_kind:
            invalid_paths.append(relative)
            failures.append(
                f"external content path has wrong kind: {relative} "
                f"(expected {contract['kind']})"
            )
            status = "invalid_kind"
        elif present:
            status = "present"
        elif contract["presence"] == "required":
            required_missing.append(relative)
            failures.append(f"missing required external content path: {relative}")
            status = "required_missing"
        else:
            optional_missing.append(relative)
            status = "optional_missing"
        content_checks.append({**contract, "present": present, "status": status})
    state = Path(state_root).resolve()
    state.mkdir(parents=True, exist_ok=True)
    probe = state / f".write-probe-{uuid.uuid4().hex}"
    try:
        probe.write_text("phase2", encoding="ascii")
        probe.unlink()
    except Exception as exc:
        failures.append(f"state root is not writable: {type(exc).__name__}: {exc}")
    return {
        "ok": not failures,
        "checked_at": _utc_now(),
        "commit_sha": manifest["commit_sha"],
        "manifest_sha256": manifest["manifest_sha256"],
        "viewer_mode": "readonly_candidate",
        "runtime_closure": {
            "code_root": str(release),
            "data_root": str(Path(data_root).resolve()),
            "content_root": str(content),
            "state_root": str(state),
            "code_requirements": code_requirements,
            "external_content_requirements": [
                item["path"] for item in content_contracts if item["presence"] == "required"
            ],
            "external_content_optional": [
                item["path"] for item in content_contracts if item["presence"] == "optional"
            ],
            "external_content_contract": {
                "enforced": True,
                "checks": content_checks,
                "required_missing": required_missing,
                "optional_missing": optional_missing,
                "invalid_paths": invalid_paths,
            },
        },
        "schema": schema_report,
        "failures": failures,
    }


def _current_path(deploy_root: Path) -> Path:
    return deploy_root / CURRENT_POINTER_NAME


def resolve_current_release(deploy_root: str | Path) -> tuple[Path, dict[str, Any]]:
    root = Path(deploy_root).resolve()
    pointer = _load_json(_current_path(root))
    sha = str(pointer.get("commit_sha", "")).lower()
    if not FULL_SHA_RE.fullmatch(sha):
        raise ReleaseError("invalid current release pointer")
    release = (root / "releases" / sha).resolve()
    if release.parent != (root / "releases").resolve():
        raise ReleaseError("current release escaped release root")
    manifest = verify_release(release)
    if manifest["manifest_sha256"] != pointer.get("manifest_sha256"):
        raise ReleaseError("current pointer manifest identity mismatch")
    return release, pointer


def resolve_preflighted_release(
    deploy_root: str | Path,
    *,
    preflight_report: Mapping[str, Any],
    data_root: str | Path,
    content_root: str | Path,
    state_root: str | Path,
) -> tuple[Path, dict[str, Any]]:
    """Resolve current without rehashing every file after a bound preflight.

    The deployer performs the expensive exact-file verification immediately
    before launch and passes its SHA-bound report.  This function rechecks the
    small immutable identities and runtime roots, preventing the candidate
    process and health polling from repeatedly hashing hundreds of files.
    """

    root = Path(deploy_root).resolve()
    current_path = _current_path(root)
    pointer = _load_json(current_path)
    sha = str(pointer.get("commit_sha", "")).lower()
    if not FULL_SHA_RE.fullmatch(sha):
        raise ReleaseError("invalid current release pointer")
    release = (root / "releases" / sha).resolve()
    if release.parent != (root / "releases").resolve():
        raise ReleaseError("current release escaped release root")
    manifest = _load_json(release / MANIFEST_NAME)
    manifest_sha = _manifest_hash(release)
    if manifest_sha != pointer.get("manifest_sha256"):
        raise ReleaseError("current pointer manifest identity mismatch")
    if manifest.get("commit_sha") != sha:
        raise ReleaseError("release manifest commit identity mismatch")
    if not preflight_report.get("ok"):
        raise ReleaseError("bound preflight did not pass")
    if preflight_report.get("commit_sha") != sha:
        raise ReleaseError("bound preflight commit differs from current")
    if preflight_report.get("manifest_sha256") != manifest_sha:
        raise ReleaseError("bound preflight manifest differs from current")
    runtime = preflight_report.get("runtime_closure") or {}
    expected_roots = {
        "data_root": str(Path(data_root).resolve()),
        "content_root": str(Path(content_root).resolve()),
        "state_root": str(Path(state_root).resolve()),
    }
    for key, expected in expected_roots.items():
        if str(runtime.get(key)) != expected:
            raise ReleaseError(f"bound preflight {key} differs from launch")
    content_contract = runtime.get("external_content_contract") or {}
    if not content_contract.get("enforced"):
        raise ReleaseError("bound preflight did not enforce external content contracts")
    if content_contract.get("required_missing") or content_contract.get("invalid_paths"):
        raise ReleaseError("bound preflight has unresolved required external content")
    schema = preflight_report.get("schema") or {}
    expected_contract = _compatibility_fingerprint(manifest["schema_compatibility"])
    if not schema.get("compatible") or schema.get("compatibility_contract_sha256") != expected_contract:
        raise ReleaseError("bound preflight schema contract is not valid for release")
    return release, pointer


def prime_release_health_cache(
    deploy_root: str | Path,
    data_root: str | Path,
    *,
    pointer: Mapping[str, Any],
    preflight_report: Mapping[str, Any],
) -> None:
    root = Path(deploy_root).resolve()
    current_bytes = _current_path(root).read_bytes()
    payload = {
        "ok": bool((preflight_report.get("schema") or {}).get("compatible")),
        "release": {
            "commit_sha": pointer.get("commit_sha"),
            "manifest_sha256": pointer.get("manifest_sha256"),
            "activated_at": pointer.get("activated_at"),
            "preflight_checked_at": preflight_report.get("checked_at"),
        },
        "viewer_mode": "readonly_candidate",
        "database_contract": preflight_report.get("schema"),
    }
    _RELEASE_HEALTH_CACHE[(str(root), str(Path(data_root).resolve()))] = {
        "current_sha256": _sha256_bytes(current_bytes),
        "payload": payload,
    }


def _append_ledger(deploy_root: Path, payload: Mapping[str, Any]) -> None:
    path = deploy_root / LEDGER_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(dict(payload), ensure_ascii=False, sort_keys=True) + "\n")


def activate_release(
    deploy_root: str | Path,
    commit_sha: str,
    *,
    actor: str,
    schema_report: Mapping[str, Any],
    reason: str = "candidate_activation",
) -> dict[str, Any]:
    root = Path(deploy_root).resolve()
    sha = str(commit_sha).lower()
    if not FULL_SHA_RE.fullmatch(sha):
        raise ReleaseError("activation requires a full commit SHA")
    manifest = verify_release(root / "releases" / sha)
    if not schema_report.get("compatible"):
        raise ReleaseError("schema contract is not compatible with target release")
    expected_contract = _compatibility_fingerprint(manifest["schema_compatibility"])
    if schema_report.get("compatibility_contract_sha256") != expected_contract:
        raise ReleaseError("schema report was not evaluated against target release contract")
    previous: str | None = None
    current_path = _current_path(root)
    if current_path.is_file():
        previous = str(_load_json(current_path).get("commit_sha") or "") or None
    pointer = {
        "schema_version": "honghu.current_release.v1",
        "commit_sha": sha,
        "manifest_sha256": manifest["manifest_sha256"],
        "activated_at": _utc_now(),
        "actor": actor,
        "previous_commit_sha": previous,
        "schema_contract_backend": schema_report.get("backend"),
    }
    root.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".current-", dir=root)
    os.close(fd)
    temp = Path(temp_name)
    try:
        temp.write_bytes(_canonical_json(pointer))
        os.replace(temp, current_path)
    finally:
        if temp.exists():
            temp.unlink()
    _append_ledger(
        root,
        {
            "schema_version": "honghu.deployment_ledger.v1",
            "event": reason,
            **pointer,
        },
    )
    return pointer


def rollback_release(
    deploy_root: str | Path,
    *,
    actor: str,
    schema_report: Mapping[str, Any],
    target_commit: str | None = None,
) -> dict[str, Any]:
    root = Path(deploy_root).resolve()
    _, current = resolve_current_release(root)
    target = target_commit or current.get("previous_commit_sha")
    if not target:
        raise ReleaseError("no previous release is recorded for rollback")
    result = activate_release(
        root,
        str(target),
        actor=actor,
        schema_report=schema_report,
        reason="code_only_rollback",
    )
    result["rollback_from_commit_sha"] = current["commit_sha"]
    return result


def release_health_payload(
    deploy_root: str | Path,
    *,
    data_root: str | Path,
) -> dict[str, Any]:
    root = Path(deploy_root).resolve()
    key = (str(root), str(Path(data_root).resolve()))
    cached = _RELEASE_HEALTH_CACHE.get(key)
    if cached is not None and _current_path(root).is_file():
        current_hash = _sha256_file(_current_path(root))
        if current_hash == cached.get("current_sha256"):
            return copy.deepcopy(cached["payload"])
    release, pointer = resolve_current_release(deploy_root)
    manifest = verify_release(release)
    schema = inspect_sqlite_contract(data_root, manifest["schema_compatibility"])
    payload = {
        "ok": bool(schema["compatible"]),
        "release": {
            "commit_sha": manifest["commit_sha"],
            "manifest_sha256": manifest["manifest_sha256"],
            "activated_at": pointer.get("activated_at"),
        },
        "viewer_mode": "readonly_candidate",
        "database_contract": schema,
    }
    _RELEASE_HEALTH_CACHE[key] = {
        "current_sha256": _sha256_file(_current_path(root)),
        "payload": payload,
    }
    return copy.deepcopy(payload)


def iter_release_files(release_dir: str | Path) -> Iterable[Path]:
    root = Path(release_dir).resolve()
    manifest = verify_release(root)
    for item in manifest["files"]:
        yield root / str(item["path"])
