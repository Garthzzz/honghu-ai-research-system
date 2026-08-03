from __future__ import annotations

"""Build and operate exact-commit immutable application releases.

This module deliberately does not copy databases, papers, backups, credentials,
or user content.  A release is code from one Git commit; external runtime
authorities are attached explicitly during preflight and process launch.
"""

import hashlib
import json
import os
import re
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
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


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


def build_release(
    repo_root: str | Path,
    deploy_root: str | Path,
    *,
    commit: str,
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
    selected, governance_only = selected_deployment_paths(repo, sha, policy)
    source_commit_time = str(
        _git(repo, "show", "-s", "--format=%cI", sha)
    ).strip()
    releases_root = deploy / "releases"
    target = releases_root / sha
    releases_root.mkdir(parents=True, exist_ok=True)
    if target.exists():
        existing = verify_release(target)
        if existing.get("commit_sha") != sha:
            raise ReleaseError(f"existing release identity mismatch: {target}")
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
            import shutil

            shutil.rmtree(staging)
        raise
    return verify_release(target)


def _sqlite_tables(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def inspect_sqlite_contract(
    data_root: str | Path, compatibility: Mapping[str, Any]
) -> dict[str, Any]:
    root = Path(data_root).resolve()
    results: dict[str, Any] = {}
    failures: list[str] = []
    required_map = compatibility.get("required_tables", {})
    for name, required_values in required_map.items():
        path = root / str(name)
        if not path.is_file():
            failures.append(f"missing database: {name}")
            continue
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5)
            conn.execute("PRAGMA query_only=ON")
            tables = _sqlite_tables(conn)
            missing = sorted(set(str(v) for v in required_values) - tables)
            user_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            schema_rows = [
                f"{row[0]}:{row[1] or ''}"
                for row in conn.execute(
                    "SELECT name, sql FROM sqlite_master "
                    "WHERE type IN ('table','index','view','trigger') ORDER BY type,name"
                )
            ]
            if missing:
                failures.append(f"{name} missing required tables: {missing}")
            results[str(name)] = {
                "backend": "sqlite-transition",
                "user_version": user_version,
                "table_count": len(tables),
                "required_tables_present": not missing,
                "schema_fingerprint": _sha256_bytes(
                    ("\n".join(schema_rows) + "\n").encode("utf-8")
                ),
            }
        except Exception as exc:
            failures.append(f"{name} read-only inspection failed: {type(exc).__name__}: {exc}")
        finally:
            if conn is not None:
                conn.close()
    return {
        "backend": "sqlite-transition",
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
    require_content: bool = True,
) -> dict[str, Any]:
    release = Path(release_dir).resolve()
    manifest = verify_release(release)
    compatibility = manifest["schema_compatibility"]
    schema_report = inspect_sqlite_contract(data_root, compatibility)
    failures = list(schema_report["failures"])
    code_requirements = [
        "config/research_workflow.yaml",
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
    if require_content:
        for relative in ("docs/industries", "papers"):
            if not (content / relative).exists():
                failures.append(f"missing external content path: {relative}")
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
    release, pointer = resolve_current_release(deploy_root)
    manifest = verify_release(release)
    schema = inspect_sqlite_contract(data_root, manifest["schema_compatibility"])
    return {
        "ok": bool(schema["compatible"]),
        "release": {
            "commit_sha": manifest["commit_sha"],
            "manifest_sha256": manifest["manifest_sha256"],
            "activated_at": pointer.get("activated_at"),
        },
        "viewer_mode": "readonly_candidate",
        "database_contract": schema,
    }


def iter_release_files(release_dir: str | Path) -> Iterable[Path]:
    root = Path(release_dir).resolve()
    manifest = verify_release(root)
    for item in manifest["files"]:
        yield root / str(item["path"])
