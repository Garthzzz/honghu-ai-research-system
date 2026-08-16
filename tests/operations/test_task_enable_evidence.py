from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tools.operations.task_enable_evidence import (
    TaskEnableEvidenceError,
    _normalized_text_sha256,
    verify_local_disabled_evidence,
)
from tools.operations.task_manifest import load_task_manifest


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "config/operations/production_tasks.json"
COLLECTOR = ROOT / "tools/operations/Collect-LocalDisabledTaskEvidence.ps1"
NOW = datetime(2026, 8, 17, 1, 0, tzinfo=timezone.utc)


def _payload() -> dict[str, object]:
    manifest = load_task_manifest(MANIFEST_PATH)
    tasks = [
        {
            "task_id": task_id,
            "present": True,
            "enabled": False,
            "state": "Disabled",
            "principal": definition.legacy_principal,
            "definition_sha256": definition.legacy_definition_sha256,
            "expected_definition_sha256": definition.legacy_definition_sha256,
            "definition_matches_manifest": True,
        }
        for task_id, definition in manifest.tasks.items()
    ]
    return {
        "schema_version": "honghu.local_task_disabled_evidence.v2",
        "checked_at": (NOW - timedelta(seconds=30)).isoformat(),
        "source_host": manifest.legacy_runner_host,
        "source_host_identity_sha256": manifest.legacy_runner_host_identity_sha256,
        "machine_guid_recorded": False,
        "manifest_sha256": manifest.sha256,
        "collector_sha256": _normalized_text_sha256(COLLECTOR),
        "tasks": tasks,
        "all_present": True,
        "all_disabled": True,
        "all_definitions_match": True,
        "legacy_runner_process_count": 0,
        "legacy_runner_processes": [],
        "secrets_recorded": False,
    }


def _verify(tmp_path: Path, payload: dict[str, object]) -> dict[str, object]:
    path = tmp_path / "local-disabled.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return verify_local_disabled_evidence(
        load_task_manifest(MANIFEST_PATH), path, collector_path=COLLECTOR, now=NOW
    )


def test_complete_fresh_local_disabled_evidence_passes(tmp_path: Path) -> None:
    result = _verify(tmp_path, _payload())
    assert result["verified"] is True
    assert result["task_count"] == 7
    assert result["legacy_runner_process_count"] == 0


def test_collector_identity_is_stable_across_lf_and_crlf(tmp_path: Path) -> None:
    lf = tmp_path / "lf.ps1"
    crlf = tmp_path / "crlf.ps1"
    lf.write_bytes(b"one\ntwo\n")
    crlf.write_bytes(b"one\r\ntwo\r\n")
    assert _normalized_text_sha256(lf) == _normalized_text_sha256(crlf)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda data: data.update(schema_version="honghu.local_task_disabled_evidence.v1"),
        lambda data: data.update(checked_at=(NOW - timedelta(hours=2)).isoformat()),
        lambda data: data.update(source_host="FORGED"),
        lambda data: data.update(source_host_identity_sha256="0" * 64),
        lambda data: data.update(manifest_sha256="0" * 64),
        lambda data: data.update(collector_sha256="0" * 64),
        lambda data: data["tasks"].pop(),
        lambda data: data["tasks"][0].update(enabled=True),
        lambda data: data["tasks"][0].update(definition_sha256="0" * 64),
        lambda data: data.update(legacy_runner_process_count=1),
        lambda data: data.update(legacy_runner_processes=[{"pid": 123}]),
        lambda data: data.pop("all_definitions_match"),
    ],
)
def test_old_forged_or_incomplete_evidence_fails_closed(
    tmp_path: Path, mutator
) -> None:
    payload = copy.deepcopy(_payload())
    mutator(payload)
    with pytest.raises(TaskEnableEvidenceError):
        _verify(tmp_path, payload)
