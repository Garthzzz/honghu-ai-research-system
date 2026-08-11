from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tools.migration.stage4_identity_mapping import build_identity_mapping
from tools.migration.stage4_readiness_bundle import build_bundle


ROOT = Path(__file__).resolve().parents[2]
SUBJECT = {
    "environment_id": "fixture",
    "candidate_id": "fixture-candidate",
    "commit_sha": "a" * 40,
    "config_sha256": "b" * 64,
}


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _envelope(evidence_type: str, subject: dict | None = None) -> dict:
    return {
        "schema_version": "honghu.stage4_readiness_evidence.v1",
        "evidence_type": evidence_type,
        "subject": subject or SUBJECT,
        "observed_at_utc": "2026-08-12T00:00:00+00:00",
        "valid_until_utc": "2026-08-14T00:00:00+00:00",
        "payload": {},
    }


def _inputs(tmp_path: Path) -> dict[str, Path]:
    database = tmp_path / "mapping.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE company(id INTEGER PRIMARY KEY,name TEXT,ticker TEXT,market TEXT);
            CREATE TABLE industry(id INTEGER PRIMARY KEY,name TEXT,parent_id INTEGER);
            CREATE TABLE theme(id TEXT PRIMARY KEY,name TEXT);
            INSERT INTO company VALUES(1,'Fixture','000001.SZ','A股');
            INSERT INTO industry VALUES(1,'Fixture Industry',NULL);
            INSERT INTO theme VALUES('fixture','Fixture Theme');
            """
        )
    mapping = build_identity_mapping(database)
    mapping_path = _write(tmp_path / "mapping.json", mapping)
    approval_path = _write(
        tmp_path / "approval.json",
        {
            "counts": {"name_and_market_fallback": 0},
            "cutover_level_approved": False,
            "approval_reference": None,
        },
    )
    adapter_path = _write(
        tmp_path / "adapter.json",
        {
            "status": "pass",
            "production_cutover_authorized": False,
            "live_sqlite_schema_unchanged": True,
            "live_sqlite_file_hashes_unchanged": True,
            "adapter_result": {"status": "pass"},
        },
    )
    return {
        "mapping_path": mapping_path,
        "mapping_approval_path": approval_path,
        "adapter_rehearsal_path": adapter_path,
        "topology_path": _write(tmp_path / "topology.json", _envelope("postgresql_topology")),
        "recovery_path": _write(tmp_path / "recovery.json", _envelope("recovery")),
    }


def test_bundle_binds_typed_artifacts_and_real_github_facts(tmp_path, monkeypatch) -> None:
    import tools.migration.stage4_readiness_bundle as module

    def github(url: str) -> dict:
        if url.endswith("/branches/main"):
            return {
                "protected": True,
                "commit": {"sha": "c" * 40},
                "protection": {
                    "required_status_checks": {
                        "contexts": ["boundary-and-contracts", "python-clean-environment"]
                    }
                },
            }
        return {
            "check_runs": [
                {"name": name, "status": "completed", "conclusion": "success"}
                for name in ("boundary-and-contracts", "python-clean-environment")
            ]
        }

    monkeypatch.setattr(module, "_github_json", github)
    bundle = build_bundle(
        root=ROOT,
        evidence_root=tmp_path / "evidence",
        subject=SUBJECT,
        github_repository="fixture/repository",
        **_inputs(tmp_path),
    )
    assert bundle["production_cutover_authorized"] is False
    assert set(bundle["artifacts"]) == {
        "identity_mapping_manifest",
        "identity_mapping_approval",
        "application_contract",
        "postgresql_topology",
        "recovery",
        "repository_governance",
        "cutover_decision",
    }
    repository = json.loads(
        (tmp_path / "evidence" / "repository_governance.json").read_text(encoding="utf-8")
    )
    assert repository["payload"]["repository"]["required_checks_green"] is True
    assert repository["payload"]["repository"]["production_authority_approved"] is False


def test_bundle_rejects_cross_subject_topology(tmp_path, monkeypatch) -> None:
    inputs = _inputs(tmp_path)
    topology = _envelope("postgresql_topology", {**SUBJECT, "candidate_id": "other"})
    _write(inputs["topology_path"], topology)
    with pytest.raises(ValueError, match="subject"):
        build_bundle(
            root=ROOT,
            evidence_root=tmp_path / "evidence",
            subject=SUBJECT,
            github_repository="fixture/repository",
            **inputs,
        )
