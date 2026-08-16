from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.operations.task_manifest import TaskManifestError, load_task_manifest


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "config/operations/production_tasks.json"


def test_production_manifest_has_exactly_seven_safe_tasks():
    manifest = load_task_manifest(MANIFEST)
    assert len(manifest.tasks) == 7
    assert manifest.runner_host == "DESKTOP-VGD07J4"
    assert all(task.command[0] == "-m" for task in manifest.tasks.values())
    assert all(task.command[1].startswith("tools.") for task in manifest.tasks.values())
    assert not any("--compact" in task.command for task in manifest.tasks.values())


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda data: data.update(timezone="UTC"), "timezone"),
        (lambda data: data["tasks"].append(dict(data["tasks"][0])), "duplicated"),
        (lambda data: data["tasks"][0].update(command=["cmd", "/c", "echo"]), "reviewed"),
        (lambda data: data["tasks"][0].update(command=["-m", "tools.x", "a&b"]), "unsafe"),
        (lambda data: data["tasks"][0].update(writer_units=["unknown"]), "writer unit"),
    ],
)
def test_manifest_fails_closed(tmp_path: Path, mutator, message: str):
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    mutator(data)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(TaskManifestError, match=message):
        load_task_manifest(path)
