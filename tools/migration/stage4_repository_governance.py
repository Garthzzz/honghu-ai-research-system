from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUIRED_CHECKS = {"boundary-and-contracts", "python-clean-environment"}


def _get(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "honghu-stage4-governance-audit",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def collect(repository: str, commit_sha: str) -> dict[str, Any]:
    base = f"https://api.github.com/repos/{repository}"
    repo = _get(base)
    main = _get(f"{base}/branches/main")
    checks = _get(f"{base}/commits/{commit_sha}/check-runs")
    completed = {
        item.get("name"): item.get("conclusion")
        for item in checks.get("check_runs") or []
        if item.get("status") == "completed"
    }
    protection = main.get("protection") or {}
    contexts = set(
        (protection.get("required_status_checks") or {}).get("contexts") or []
    )
    owner = (repo.get("owner") or {}).get("login")
    core = {
        "schema_version": "honghu.repository_governance_evidence.v1",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "repository": repository,
        "visibility": repo.get("visibility"),
        "owner": owner,
        "owner_type": (repo.get("owner") or {}).get("type"),
        "default_branch": repo.get("default_branch"),
        "main_commit_sha": (main.get("commit") or {}).get("sha"),
        "subject_commit_sha": commit_sha,
        "main_protected": bool(main.get("protected")),
        "required_checks": sorted(REQUIRED_CHECKS),
        "required_contexts": sorted(contexts),
        "subject_check_conclusions": completed,
        "required_checks_green": all(
            completed.get(name) == "success" for name in REQUIRED_CHECKS
        ),
        "force_push_delete_protection": {
            "status": "previously_verified_but_not_publicly_reconfirmable",
            "reason": "the detailed branch protection endpoint requires authenticated company-governance evidence",
        },
        "production_authority": {
            "approved": False,
            "reason": "repository remains under a personal account and no company-control exception is recorded",
        },
        "not_publicly_verifiable": [
            "second company administrator or executable handover",
            "owner and administrator 2FA/recovery",
            "company-controlled deploy credential",
            "admin enforcement/detail beyond the public branch summary",
        ],
    }
    return {**core, "evidence_sha256": _sha(core)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default="Garthzzz/honghu-ai-research-system")
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = collect(args.repository, args.commit_sha)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
