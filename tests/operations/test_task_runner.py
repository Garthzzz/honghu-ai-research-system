from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tools.operations.task_manifest import load_task_manifest
from tools.operations.task_runner import (
    _classify,
    _isolated_child_command,
    _most_recent_scheduled_at,
    logical_window,
)


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = load_task_manifest(ROOT / "config/operations/production_tasks.json")
BEIJING = ZoneInfo("Asia/Shanghai")


def test_logical_windows_are_retry_stable():
    current = datetime(2026, 8, 17, 10, 37, tzinfo=BEIJING)
    assert logical_window(MANIFEST.tasks["IndustryDemo_DynamicTick"], current).endswith("10:30+08:00")
    assert logical_window(MANIFEST.tasks["IndustryDemo_EventIngest"], current) == "2026-08-17"
    assert logical_window(MANIFEST.tasks["IndustryDemo_RecruitWeekly"], current) == "2026-W34"
    assert logical_window(MANIFEST.tasks["IndustryDemo_Retail_Morning"], current) == "2026-08-17:morning"


def test_exit_classification_does_not_treat_partial_or_timeout_as_success():
    assert _classify(0, False) == ("succeeded", None)
    assert _classify(75, False) == ("deferred", "resource_lock_deferred")
    assert _classify(2, False) == ("failed", "producer_or_reconciliation_failure")
    assert _classify(0, True) == ("failed", "timeout")


def test_expected_trigger_respects_overnight_and_weekend_gaps():
    dynamic = MANIFEST.tasks["IndustryDemo_DynamicTick"]
    event = MANIFEST.tasks["IndustryDemo_EventIngest"]
    assert _most_recent_scheduled_at(
        dynamic, datetime(2026, 8, 17, 7, 0, tzinfo=BEIJING)
    ).isoformat() == "2026-08-14T20:00:00+08:00"
    assert _most_recent_scheduled_at(
        dynamic, datetime(2026, 8, 17, 10, 37, tzinfo=BEIJING)
    ).isoformat() == "2026-08-17T10:30:00+08:00"
    assert _most_recent_scheduled_at(
        event, datetime(2026, 8, 16, 12, 0, tzinfo=BEIJING)
    ).isoformat() == "2026-08-14T10:30:00+08:00"


def test_stage5_migration_is_expand_only_and_least_privilege():
    sql = (ROOT / "migrations/postgresql/0013_stage5_task_operations.sql").read_text(encoding="utf-8")
    assert "production_task_definition" in sql
    assert "production_task_run" in sql
    assert "writer_operations_governance" in sql
    assert "business_checkpoint_before" in sql
    assert "DROP " not in sql.upper()
    assert "transition_cutover_unit" not in sql


def test_child_command_is_import_isolated_and_bytecode_free(tmp_path, monkeypatch):
    release = tmp_path / "release"
    bootstrap = release / "tools" / "release" / "direct_candidate.py"
    bootstrap.parent.mkdir(parents=True)
    bootstrap.write_text("# bootstrap\n", encoding="utf-8")
    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()
    command = _isolated_child_command(
        release_dir=release,
        site_packages=site_packages,
        task=MANIFEST.tasks["IndustryDemo_DynamicTick"],
    )
    assert command[1:4] == ["-I", "-B", "-S"]
    assert command[4] == str(bootstrap.resolve())
    assert command[5:7] == ["--site-packages", str(site_packages.resolve())]
    assert command[7:9] == ["--module", "tools.operations.task_child"]
    assert command[9:12] == ["--task-module", "tools.dynamic.scheduler", "--"]
