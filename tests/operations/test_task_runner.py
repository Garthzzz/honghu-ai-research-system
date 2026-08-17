from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tools.operations.task_manifest import load_task_manifest
from tools.operations.task_runner import (
    _classify,
    _controlled_retail_session_date,
    _dynamic_compatibility_retry_environment,
    _install_dynamic_compatibility_retry_environment,
    _isolated_child_command,
    _most_recent_scheduled_at,
    logical_window,
    set_definition_enabled,
)
import inspect
import pytest


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = load_task_manifest(ROOT / "config/operations/production_tasks.json")
BEIJING = ZoneInfo("Asia/Shanghai")


def test_logical_windows_are_retry_stable():
    current = datetime(2026, 8, 17, 10, 37, tzinfo=BEIJING)
    assert logical_window(MANIFEST.tasks["IndustryDemo_DynamicTick"], current).endswith("10:30+08:00")
    assert logical_window(MANIFEST.tasks["IndustryDemo_EventIngest"], current) == "2026-08-17"
    assert logical_window(MANIFEST.tasks["IndustryDemo_RecruitWeekly"], current) == "2026-W34"
    assert logical_window(MANIFEST.tasks["IndustryDemo_Retail_Morning"], current) == "2026-08-17:morning"


def test_controlled_retail_session_is_prior_exact_and_disabled_only():
    task = MANIFEST.tasks["IndustryDemo_Retail_Preopen"]
    now = datetime(2026, 8, 17, 5, 0, tzinfo=BEIJING)
    assert _controlled_retail_session_date(
        task,
        logical_window_value="2026-08-14:preopen",
        value="2026-08-14",
        allow_disabled=True,
        now=now,
    ) == "2026-08-14"
    for window, value, allowed in (
        ("2026-08-14:morning", "2026-08-14", True),
        ("2026-08-17:preopen", "2026-08-17", True),
        ("2026-08-15:preopen", "2026-08-15", True),
        ("2026-08-14:preopen", "2026-08-14", False),
    ):
        with pytest.raises(Exception):
            _controlled_retail_session_date(
                task,
                logical_window_value=window,
                value=value,
                allow_disabled=allowed,
                now=now,
            )


def test_non_retail_task_cannot_receive_controlled_session_date():
    with pytest.raises(Exception):
        _controlled_retail_session_date(
            MANIFEST.tasks["IndustryDemo_EventIngest"],
            logical_window_value="2026-08-14",
            value="2026-08-14",
            allow_disabled=True,
            now=datetime(2026, 8, 17, 5, 0, tzinfo=BEIJING),
        )


def test_dynamic_compatibility_retry_is_explicit_and_disabled_only():
    dynamic = MANIFEST.tasks["IndustryDemo_DynamicTick"]
    assert _dynamic_compatibility_retry_environment(
        dynamic, allow_disabled=True, requested=False
    ) == {}
    assert _dynamic_compatibility_retry_environment(
        dynamic, allow_disabled=True, requested=True
    ) == {"HONGHU_DYNAMIC_COMPATIBILITY_RETRY": "1"}
    with pytest.raises(Exception):
        _dynamic_compatibility_retry_environment(
            dynamic, allow_disabled=False, requested=True
        )
    with pytest.raises(Exception):
        _dynamic_compatibility_retry_environment(
            MANIFEST.tasks["IndustryDemo_EventIngest"],
            allow_disabled=True,
            requested=True,
        )

    inherited = {"HONGHU_DYNAMIC_COMPATIBILITY_RETRY": "1", "SAFE": "kept"}
    _install_dynamic_compatibility_retry_environment(inherited, {})
    assert inherited == {"SAFE": "kept"}
    _install_dynamic_compatibility_retry_environment(
        inherited, {"HONGHU_DYNAMIC_COMPATIBILITY_RETRY": "1"}
    )
    assert inherited == {
        "SAFE": "kept",
        "HONGHU_DYNAMIC_COMPATIBILITY_RETRY": "1",
    }


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


def test_delegated_task_writer_keeps_unit_owner_and_membership_fences():
    sql = (
        ROOT / "migrations/postgresql/0014_stage5_delegated_unit_writers.sql"
    ).read_text(encoding="utf-8")
    assert "pg_has_role(session_user,p_writer_identity,'MEMBER')" in sql
    assert "p_writer_identity<>('honghu_writer_'||p_cutover_unit)" in sql
    assert "v_authority.writer_identity<>p_writer_identity" in sql
    assert "session_user<>p_writer_identity" not in sql
    assert "session_user<>('honghu_writer_'||p_cutover_unit)" not in sql
    assert "DROP " not in sql.upper()


def test_new_post_cutover_objects_start_at_revision_one():
    base_sql = (
        ROOT / "migrations/postgresql/0010_remaining_units_common_data_plane.sql"
    ).read_text(encoding="utf-8")
    migration_sql = (
        ROOT / "migrations/postgresql/0015_stage5_initial_overlay_revision.sql"
    ).read_text(encoding="utf-8")
    assert "revision bigint NOT NULL CHECK (revision > 0)" in base_sql
    assert "CHECK (revision > 0) NOT VALID" in migration_sql
    assert "VALIDATE CONSTRAINT record_overlay_revision_check" in migration_sql
    assert "0015_stage5_initial_overlay_revision" in migration_sql


def test_large_mutation_batch_result_is_bounded_without_weakening_row_fences():
    sql = (
        ROOT
        / "migrations/postgresql/0016_stage5_bounded_mutation_batch_result.sql"
    ).read_text(encoding="utf-8")
    function = sql.split(
        "CREATE OR REPLACE FUNCTION domain_data.apply_mutation_batch_v1", 1
    )[1].split("$$;", 1)[0]
    assert "PERFORM domain_data.mutate_record_v1" in function
    assert "pg_has_role(session_user,p_writer_identity,'MEMBER')" in function
    assert "p_writer_identity<>('honghu_writer_'||p_cutover_unit)" in function
    assert "SECURITY DEFINER" in function
    assert "SET search_path=pg_catalog,domain_data" in function
    assert "v_results" not in function
    assert "jsonb_build_array" not in function
    assert "'mutation_count',v_index" in function
    assert "'idempotency_key',p_idempotency_key" in function
    assert "'request_sha256',p_request_sha256" in function
    assert "'result_detail','summary_only'" in function
    assert "'mutations_omitted',true" in function


def test_sentiment_delete_batch_is_set_based_without_weakening_fences():
    sql = (
        ROOT
        / "migrations/postgresql/0017_stage5_set_based_sentiment_delete_batch.sql"
    ).read_text(encoding="utf-8")
    function = sql.split(
        "CREATE OR REPLACE FUNCTION domain_data.apply_mutation_batch_v1", 1
    )[1].split("$$;", 1)[0]
    assert "p_cutover_unit='sentiment_analytics'" in function
    assert "v_authority.state NOT IN ('S3','S4')" in function
    assert "v_authority.authoritative_backend<>'postgresql_production'" in function
    assert "v_authority.writer_identity<>p_writer_identity" in function
    assert "pg_has_role(session_user,p_writer_identity,'MEMBER')" in function
    assert "v_formal.source_watermark->'tables'" in function
    assert "current_revision<>expected_revision" in function
    assert "INSERT INTO domain_data.record_overlay" in function
    assert "INSERT INTO audit.domain_record_revision" in function
    assert "INSERT INTO domain_data.mutation_result" in function
    assert "PERFORM domain_data.mutate_record_v1" in function
    assert "'execution_mode',CASE WHEN v_all_sentiment_deletes" in function
    assert "SECURITY DEFINER" in function


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


def test_outer_runner_owns_job_before_authority_or_child_work():
    source = inspect.getsource(
        __import__("tools.operations.task_runner", fromlist=["run_task"]).run_task
    )
    assert source.index("ensure_self_killing_job()") < source.index(
        "_validate_authority(task)"
    )


def test_runtime_roots_are_bound_before_authority_and_checkpoint_probes():
    source = inspect.getsource(__import__("tools.operations.task_runner", fromlist=["run_task"]).run_task)
    state_assignment = source.index('"HONGHU_STATE_ROOT"')
    authority_probe = source.index("_validate_authority(task)")
    checkpoint_probe = source.index("checkpoint_before = probe_business_checkpoint")
    assert state_assignment < authority_probe < checkpoint_probe


def test_idempotent_skip_returns_full_exact_release_evidence_contract():
    source = inspect.getsource(__import__("tools.operations.task_runner", fromlist=["run_task"]).run_task)
    assert '"status": "skipped"' in source
    assert '"application_commit_sha": commit' in source
    assert '"prior_success_application_commit_sha": str(prior[4])' in source
    assert '"business_checkpoint_after_sha256"' in source


def test_definition_enable_is_exact_identity_checked_before_update():
    source = inspect.getsource(set_definition_enabled)
    assert "manifest_sha256,application_commit_sha,runner_host" in source
    assert "task definition identity does not match exact release" in source
    assert "definition_revision=definition_revision+1" in source


def test_outer_timeout_covers_reviewed_child_and_catch_up_budgets():
    dynamic = MANIFEST.tasks["IndustryDemo_DynamicTick"]
    recruit = MANIFEST.tasks["IndustryDemo_RecruitWeekly"]
    retail = [
        MANIFEST.tasks["IndustryDemo_Retail_Preopen"],
        MANIFEST.tasks["IndustryDemo_Retail_Morning"],
        MANIFEST.tasks["IndustryDemo_Retail_Afternoon"],
    ]
    retention = MANIFEST.tasks["IndustryDemo_SentimentRetention"]

    # Event-calendar dispatch can run two 600-second producers sequentially.
    assert dynamic.execution_timeout_seconds >= 2 * 600 + 300
    # Recruit runs two sequential children with independent 5400-second caps.
    assert recruit.execution_timeout_seconds >= 2 * 5400 + 600
    # Retail preserves one current window plus the reviewed three-window
    # catch-up, one lock wait and one orphan wait (62 hours total).
    for task in retail:
        assert "--no-auto-backfill" not in task.command
        assert task.execution_timeout_seconds >= (8 + 6 + 4 * 12) * 3600
    assert retention.execution_timeout_seconds >= 12 * 3600


def test_scheduler_hard_limit_exceeds_runner_timeout_for_cleanup():
    installer = (ROOT / "tools/operations/Install-ProductionTasks.ps1").read_text(
        encoding="utf-8-sig"
    )
    assert "execution_timeout_seconds + 900" in installer
    assert "PT${schedulerLimitMinutes}M" in installer
