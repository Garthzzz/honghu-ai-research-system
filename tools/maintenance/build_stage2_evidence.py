from __future__ import annotations

"""Generate exact-commit Phase 2 release evidence without reading live data."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
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


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "cache" / "git_bootstrap" / "stage2_evidence"


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(ROOT), *args], text=True, encoding="utf-8"
    ).strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
        "binding": {
            "repository": "Garthzzz/honghu-ai-research-system",
            "branch_or_ref": branch or "detached-head",
            "commit_sha": current,
            "github_run_id": os.environ.get("GITHUB_RUN_ID"),
            "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        },
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
        "schema_compatibility_scope": schema.get("compatibility_scope"),
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
                "rollback_performed": evidence["rollback_rehearsal"]["performed"],
                "database_hashes_unchanged": evidence["rollback_rehearsal"][
                    "database_hashes_unchanged"
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0 if evidence["preflight"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
