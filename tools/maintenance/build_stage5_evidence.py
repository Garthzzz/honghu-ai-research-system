from __future__ import annotations

"""Build secret-free Stage 5 code identity evidence for the checked-out SHA."""

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "cache" / "git_bootstrap" / "stage5_evidence" / "stage5_code_identity.json"
FILES = (
    "config/migration/stage5_storage_attestation_public.cer",
    "config/operations/production_tasks.json",
    "migrations/postgresql/0013_stage5_task_operations.sql",
    "migrations/postgresql/0014_stage5_delegated_unit_writers.sql",
    "migrations/postgresql/0015_stage5_initial_overlay_revision.sql",
    "migrations/postgresql/0016_stage5_bounded_mutation_batch_result.sql",
    "migrations/postgresql/0017_stage5_set_based_sentiment_delete_batch.sql",
    "tools/operations/task_manifest.py",
    "tools/operations/task_runner.py",
    "tools/operations/task_child.py",
    "tools/operations/task_credential_transfer.py",
    "tools/operations/task_enable_evidence.py",
    "tools/operations/task_service_preflight.py",
    "tools/operations/backup_credential_transfer.py",
    "tools/operations/task_business_probe.py",
    "tools/operations/Install-ProductionTasks.ps1",
    "tools/operations/Provision-ProductionTaskRunner.ps1",
    "tools/operations/Collect-LocalDisabledTaskEvidence.ps1",
    "tools/operations/Collect-StorageEncryptionEvidence.ps1",
    "tools/operations/Collect-StorageIdentityTransitionEvidence.ps1",
    "tools/operations/Invoke-Stage5-ContinuousRecovery.ps1",
    "tools/operations/Provision-Stage5RecoveryMaintenance.ps1",
    "tools/operations/wal_offvm_sync.py",
    "tools/operations/storage_identity_transition.py",
    "tools/migration/stage4_recovery_set.py",
    "tools/operations/stage5_recovery_cycle.py",
    "tools/operations/recovery_metrics.py",
    "tools/operations/recovery_health.py",
    "tools/operations/stage5_health.py",
    "tools/operations/stage5_sentiment_batch_rehearsal.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def commit_sha() -> str:
    value = os.environ.get("GITHUB_SHA", "").strip().lower()
    if not value:
        value = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip().lower()
    if len(value) != 40:
        raise RuntimeError("checked-out commit identity is unavailable")
    return value


def main() -> int:
    missing = [item for item in FILES if not (ROOT / item).is_file()]
    if missing:
        raise RuntimeError(f"Stage 5 code identity is incomplete: {missing}")
    payload = {
        "schema_version": "honghu.stage5_code_identity.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "commit_sha": commit_sha(),
        "commit_role": "pull_request_merge_commit" if os.environ.get("GITHUB_EVENT_NAME") == "pull_request" else "branch_commit",
        "pull_request_head_sha": os.environ.get("GITHUB_HEAD_SHA") or None,
        "vm_deploy_eligible": os.environ.get("GITHUB_EVENT_NAME") != "pull_request",
        "files": [
            {"path": item, "sha256": sha256(ROOT / item), "size": (ROOT / item).stat().st_size}
            for item in FILES
        ],
        "runtime_evidence_in_git": False,
        "secrets_recorded": False,
    }
    payload["identity_sha256"] = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"commit_sha": payload["commit_sha"], "identity_sha256": payload["identity_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
