from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.operations.task_manifest import TaskManifestError, load_task_manifest


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "config/operations/production_tasks.json"


def test_production_manifest_has_exactly_eleven_safe_tasks():
    manifest = load_task_manifest(MANIFEST)
    assert len(manifest.tasks) == 11
    assert manifest.runner_host == "DESKTOP-VGD07J4"
    assert all(task.command[0] == "-m" for task in manifest.tasks.values())
    assert all(task.command[1].startswith("tools.") for task in manifest.tasks.values())
    assert not any("--compact" in task.command for task in manifest.tasks.values())
    assert manifest.legacy_runner_host == "WIN-G7VO0DD37CE"
    assert manifest.legacy_runner_host != manifest.runner_host
    assert manifest.local_disabled_evidence_max_age_seconds == 900
    assert all(task.legacy_definition_sha256 for task in manifest.tasks.values())
    assert {task.legacy_principal for task in manifest.tasks.values()} == {
        "zhang", "not_applicable_new_task"
    }
    assert manifest.tasks["IndustryDemo_ValuationMarket_1140"].schedule["at"] == "11:40"
    assert manifest.tasks["IndustryDemo_ValuationMarket_1510"].schedule["at"] == "15:10"
    assert manifest.tasks["IndustryDemo_ValuationMarket_1610"].schedule["at"] == "16:10"
    assert manifest.tasks["IndustryDemo_ValuationAI_Monthly"].schedule == {
        "kind": "monthly_at", "day": 5, "at": "07:30"
    }


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda data: data.update(timezone="UTC"), "timezone"),
        (lambda data: data["tasks"].append(dict(data["tasks"][0])), "duplicated"),
        (lambda data: data["tasks"][0].update(command=["cmd", "/c", "echo"]), "reviewed"),
        (lambda data: data["tasks"][0].update(command=["-m", "tools.x", "a&b"]), "unsafe"),
        (lambda data: data["tasks"][0].update(writer_units=["unknown"]), "writer unit"),
        (lambda data: data.update(legacy_runner_host=data["runner_host"]), "distinct"),
        (lambda data: data.update(legacy_runner_host_identity_sha256="fake"), "host identity"),
        (lambda data: data.update(local_disabled_evidence_max_age_seconds=0), "freshness"),
        (lambda data: data["tasks"][0].update(legacy_definition_sha256="fake"), "legacy definition"),
    ],
)
def test_manifest_fails_closed(tmp_path: Path, mutator, message: str):
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    mutator(data)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(TaskManifestError, match=message):
        load_task_manifest(path)
