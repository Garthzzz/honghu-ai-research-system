from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.migration.stage4_execution_readiness import evaluate


ROOT = Path(__file__).resolve().parents[2]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path, dict]:
    repo = tmp_path / "repo"
    evidence = tmp_path / "evidence"
    (repo / "config/migration").mkdir(parents=True)
    evidence.mkdir()
    route = {
        "cutover_unit": "user_content_notes",
        "authority_state": "S0",
        "backend": "sqlite_transition",
        "sqlite_writer_enabled": True,
        "production_postgresql_enabled": False,
    }
    (repo / "config/migration/user_content_backend_route.json").write_text(
        json.dumps(route), encoding="utf-8"
    )
    tracked_target = ROOT / "config/migration/target_rpo_rto_proposal.json"
    target_path = repo / "config/migration/target_rpo_rto_proposal.json"
    target_path.write_bytes(tracked_target.read_bytes())
    evidence_target = evidence / "target.json"
    evidence_target.write_bytes(tracked_target.read_bytes())
    bundle = {
        "schema_version": "honghu.stage4_execution_evidence_bundle.v1",
        "subject": {
            "application_commit_sha": "a" * 40,
            "environment_id": "production",
            "bootstrap_config_sha256": "b" * 64,
        },
        "artifacts": {
            "target_rpo_rto": {
                "path": "target.json",
                "sha256": _sha(evidence_target),
            }
        },
    }
    return repo, evidence, bundle


def test_readiness_binds_approved_target_rpo_rto_evidence(tmp_path: Path) -> None:
    repo, evidence, bundle = _fixture(tmp_path)
    result = evaluate(repo_root=repo, evidence_root=evidence, bundle=bundle)
    assert not any("target RPO/RTO" in item for item in result["engineering_blockers"])


def test_readiness_rejects_self_attested_target_rpo_rto_change(tmp_path: Path) -> None:
    repo, evidence, bundle = _fixture(tmp_path)
    target = evidence / "target.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["targets"][1]["target_rpo"] = "at most 500 minutes"
    target.write_text(json.dumps(payload), encoding="utf-8")
    bundle["artifacts"]["target_rpo_rto"]["sha256"] = _sha(target)
    result = evaluate(repo_root=repo, evidence_root=evidence, bundle=bundle)
    assert "RPO/RTO evidence is not the approved tracked proposal" in result[
        "engineering_blockers"
    ]
