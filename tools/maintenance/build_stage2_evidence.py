from __future__ import annotations

"""Generate exact-commit Phase 2 release evidence without reading live data."""

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from tools.maintenance.build_stage1_evidence import build_evidence as build_inventory
from tools.release.dev_fixture import build_dev_fixture
from tools.release.manager import (
    activate_release,
    build_release,
    inspect_sqlite_contract,
    preflight_release,
    resolve_current_release,
    rollback_release,
)
from tools.release.readonly_smoke import run_representative_smoke
from tools.release.runtime_environment import verify_runtime


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "cache" / "git_bootstrap" / "stage2_evidence"


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(ROOT), *args], text=True, encoding="utf-8"
    ).strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _github_binding(current: str, branch: str) -> dict:
    event_name = os.environ.get("GITHUB_EVENT_NAME")
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    event: dict = {}
    if event_path:
        path = Path(event_path)
        if path.is_file():
            try:
                event = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                event = {}
    pull_request = event.get("pull_request") or {}
    pr_head_sha = ((pull_request.get("head") or {}).get("sha") or None)
    pr_base_sha = ((pull_request.get("base") or {}).get("sha") or None)
    commit_role = "pull_request_merge" if event_name == "pull_request" else "branch_commit"
    return {
        "repository": "Garthzzz/honghu-ai-research-system",
        "branch_or_ref": branch or "detached-head",
        "commit_sha": current,
        "commit_role": commit_role,
        "event_name": event_name,
        "github_ref": os.environ.get("GITHUB_REF"),
        "pull_request_head_sha": pr_head_sha.lower() if pr_head_sha else None,
        "pull_request_base_sha": pr_base_sha.lower() if pr_base_sha else None,
        "eligible_as_vm_candidate_sha": event_name == "push",
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
    }


def _reserve_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _listener_pid(port: int) -> int | None:
    if os.name != "nt":
        return None
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "$row=Get-NetTCPConnection -State Listen -LocalPort "
                f"{port} -ErrorAction SilentlyContinue|Select-Object -First 1;"
                "if($null-ne$row){$row.OwningProcess}"
            ),
        ],
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    value = result.stdout.strip()
    return int(value) if result.returncode == 0 and value.isdigit() else None


def _port_is_released(port: int) -> bool:
    for _ in range(30):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                pass
        except OSError:
            return True
        time.sleep(0.1)
    return False


def _exercise_candidate_lifecycle(
    *,
    deploy: Path,
    fixture: Path,
    release: Path,
    current: str,
    preflight: dict,
) -> dict:
    runtime = deploy / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    preflight_path = runtime / "candidate_preflight.json"
    preflight_path.write_text(
        json.dumps(preflight, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    preflight_sha = _sha256(preflight_path)
    port = _reserve_local_port()
    launch_id = "c1" * 16
    stdout_path = runtime / "candidate.stdout.log"
    stderr_path = runtime / "candidate.stderr.log"
    command = [
        sys.executable,
        "-B",
        "-m",
        "tools.release.cli",
        "serve-readonly-candidate",
        "--deploy-root",
        str(deploy),
        "--data-root",
        str(fixture / "data"),
        "--content-root",
        str(fixture / "content"),
        "--state-root",
        str(runtime),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--launch-id",
        launch_id,
        "--expected-commit",
        current,
        "--preflight-report",
        str(preflight_path),
        "--preflight-report-sha256",
        preflight_sha,
    ]
    process: subprocess.Popen[bytes] | None = None
    smoke: dict | None = None
    listener_pid: int | None = None
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        try:
            process = subprocess.Popen(
                command,
                cwd=release,
                stdout=stdout,
                stderr=stderr,
            )
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/api/health", timeout=2
                    ) as response:
                        if int(response.status) == 200:
                            break
                except (OSError, urllib.error.URLError):
                    time.sleep(0.25)
            else:
                raise RuntimeError("candidate health did not become ready within 60 seconds")
            if process.poll() is not None:
                raise RuntimeError(
                    "candidate exited before health: "
                    + stderr_path.read_text(encoding="utf-8", errors="replace")[-2000:]
                )
            listener_pid = _listener_pid(port)
            smoke = run_representative_smoke(
                f"http://127.0.0.1:{port}",
                fixture / "data",
                fixture / "content",
                expected_commit=current,
                expected_launch_id=launch_id,
                expected_pid=process.pid,
            )
            if not smoke["ok"]:
                raise RuntimeError(
                    "representative candidate smoke failed: "
                    + json.dumps(smoke, ensure_ascii=False, sort_keys=True)
                )
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=15)
    released = _port_is_released(port)
    pycache_dirs = [
        path.relative_to(release).as_posix()
        for path in release.rglob("__pycache__")
    ]
    pid_matches_listener = listener_pid is None or listener_pid == process.pid
    result = {
        "ok": bool(smoke and smoke["ok"] and released and not pycache_dirs and pid_matches_listener),
        "process_pid": process.pid if process is not None else None,
        "listener_pid": listener_pid,
        "listener_pid_observed": listener_pid is not None,
        "pid_matches_listener": pid_matches_listener,
        "port_released_after_stop": released,
        "release_pycache_dirs": pycache_dirs,
        "preflight_report_sha256": preflight_sha,
        "representative_smoke": smoke,
    }
    if not result["ok"]:
        raise RuntimeError(f"candidate lifecycle evidence failed: {result}")
    return result


def _previous_release_capable_commit(current: str) -> str | None:
    for candidate in _git("rev-list", "--parents", current).splitlines()[1:]:
        sha = candidate.split()[0]
        result = subprocess.run(
            [
                "git",
                "-C",
                str(ROOT),
                "cat-file",
                "-e",
                f"{sha}:config/deployment_policy.json",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode == 0:
            return sha
    return None


def build_stage2_evidence(output_dir: Path) -> dict:
    current = (os.environ.get("GITHUB_SHA") or _git("rev-parse", "HEAD")).lower()
    branch = os.environ.get("GITHUB_REF_NAME") or _git("branch", "--show-current")
    generated_at = datetime.now(timezone.utc).isoformat()
    previous = _previous_release_capable_commit(current)
    python_runtime = verify_runtime(ROOT / "requirements.lock.txt")
    if not python_runtime["ok"]:
        raise RuntimeError(
            "exact-commit Python runtime verification failed: "
            + json.dumps(python_runtime, ensure_ascii=False, sort_keys=True)
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="honghu-stage2-") as temp:
        sandbox = Path(temp)
        deploy = sandbox / "deployment"
        fixture = sandbox / "fixture"
        build_dev_fixture(fixture)
        db_paths = sorted((fixture / "data").glob("*.db"))
        before = {path.name: _sha256(path) for path in db_paths}
        current_manifest = build_release(ROOT, deploy, commit=current)
        previous_manifest = (
            build_release(ROOT, deploy, commit=previous) if previous else None
        )
        preflight = preflight_release(
            deploy / "releases" / current,
            data_root=fixture / "data",
            content_root=fixture / "content",
            state_root=deploy / "runtime",
        )
        schema = inspect_sqlite_contract(
            fixture / "data", current_manifest["schema_compatibility"]
        )
        previous_schema = (
            inspect_sqlite_contract(
                fixture / "data", previous_manifest["schema_compatibility"]
            )
            if previous_manifest is not None
            else None
        )
        rollback = None
        if previous_manifest is not None:
            activate_release(
                deploy,
                previous,
                actor="stage2-evidence",
                schema_report=previous_schema,
            )
        activate_release(
            deploy,
            current,
            actor="stage2-evidence",
            schema_report=schema,
        )
        lifecycle = _exercise_candidate_lifecycle(
            deploy=deploy,
            fixture=fixture,
            release=deploy / "releases" / current,
            current=current,
            preflight=preflight,
        )
        if previous_manifest is not None:
            rollback = rollback_release(
                deploy,
                actor="stage2-evidence",
                schema_report=previous_schema,
                target_commit=previous,
            )
        _, pointer = resolve_current_release(deploy)
        after = {path.name: _sha256(path) for path in db_paths}
        shutil.copy2(
            deploy / "releases" / current / "RELEASE_MANIFEST.json",
            output_dir / "RELEASE_MANIFEST.json",
        )
        shutil.copy2(
            deploy / "releases" / current / "RELEASE_MANIFEST.sha256",
            output_dir / "RELEASE_MANIFEST.sha256",
        )
        ledger_lines = (deploy / "runtime/deployment_ledger.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    inventory = build_inventory(ROOT)
    evidence = {
        "schema_version": "honghu.stage2_runtime_evidence.v2",
        "generated_at": generated_at,
        "binding": _github_binding(current, branch),
        "release": {
            "manifest_sha256": current_manifest["manifest_sha256"],
            "file_count": current_manifest["file_count"],
            "content_bytes": current_manifest["content_bytes"],
            "contains_live_data": current_manifest["contains_live_data"],
            "contains_papers_or_evidence": current_manifest[
                "contains_papers_or_evidence"
            ],
            "contains_secrets": current_manifest["contains_secrets"],
        },
        "preflight": preflight,
        "python_runtime": python_runtime,
        "schema_compatibility_scope": schema.get("compatibility_scope"),
        "candidate_lifecycle": lifecycle,
        "rollback_rehearsal": {
            "previous_release_capable_commit": previous,
            "performed": rollback is not None,
            "final_current_commit": pointer["commit_sha"],
            "ledger_event_count": len(ledger_lines),
            "database_hashes_unchanged": before == after,
            "rollback_changes_data_authority": False,
            "rollback_changes_user_content": False,
        },
        "clean_clone_inventory": inventory["tracked_inventory"],
        "capability_specs": inventory["capability_specs"],
        "pending_review": inventory["pending_review"],
        "vm_candidate": {
            "validated_by_ci": False,
            "reason": "CI has no access to the internal VM; VM evidence is a separate Phase 2 gate.",
        },
    }
    (output_dir / "stage2_evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    evidence = build_stage2_evidence(args.output_dir.resolve())
    print(
        json.dumps(
            {
                "commit_sha": evidence["binding"]["commit_sha"],
                "manifest_sha256": evidence["release"]["manifest_sha256"],
                "preflight_ok": evidence["preflight"]["ok"],
                "candidate_lifecycle_ok": evidence["candidate_lifecycle"]["ok"],
                "rollback_performed": evidence["rollback_rehearsal"]["performed"],
                "database_hashes_unchanged": evidence["rollback_rehearsal"][
                    "database_hashes_unchanged"
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0 if evidence["preflight"]["ok"] and evidence["candidate_lifecycle"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
