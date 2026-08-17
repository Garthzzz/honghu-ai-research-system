from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from tools.dynamic import scheduler
from tools.maintenance import sentiment_retention
from tools.sentiment import retail_window_tick, recruit_weekly


ROOT = Path(__file__).resolve().parents[2]


def test_recruit_children_are_isolated_and_have_distinct_retry_stable_steps(
    monkeypatch,
) -> None:
    monkeypatch.setenv("HONGHU_OPERATION_ID", "stage5:IndustryDemo_RecruitWeekly:2026-W34")
    monkeypatch.setenv("HONGHU_RELEASE_BOOTSTRAP", r"D:\release\direct_candidate.py")
    monkeypatch.setenv("HONGHU_LOCKED_SITE_PACKAGES", r"D:\python-env\site-packages")
    completed = SimpleNamespace(returncode=0, stdout="ok", stderr="")
    with mock.patch.object(recruit_weekly.subprocess, "run", return_value=completed) as run:
        assert recruit_weekly.run("recruit_scrape.py") is True
        assert recruit_weekly.run("recruit_classify.py") is True

    first, second = run.call_args_list
    assert first.args[0][1:4] == ["-I", "-B", "-S"]
    assert first.args[0][-2:] == ["--task-module", "tools.sentiment.recruit_scrape"]
    assert second.args[0][-2:] == ["--task-module", "tools.sentiment.recruit_classify"]
    assert first.kwargs["env"]["HONGHU_OPERATION_ID"].endswith(":step:recruit_scrape")
    assert second.kwargs["env"]["HONGHU_OPERATION_ID"].endswith(":step:recruit_classify")
    assert first.kwargs["env"]["HONGHU_OPERATION_ID"] != second.kwargs["env"]["HONGHU_OPERATION_ID"]


def test_recruit_classification_failure_propagates_nonzero(monkeypatch) -> None:
    weekday = mock.Mock()
    weekday.weekday.return_value = 0
    weekday.isocalendar.return_value = (2026, 34, 1)
    clock = mock.Mock()
    clock.now.return_value = weekday
    monkeypatch.setattr(recruit_weekly, "datetime", clock)
    monkeypatch.setattr(recruit_weekly.sys.stdout, "reconfigure", lambda **_: None)
    with mock.patch.object(recruit_weekly, "run", side_effect=[True, False]) as child, mock.patch(
        "tools.data_platform.run_domain_operation.install_operation_context"
    ):
        assert recruit_weekly.main() == 2
    assert [item.args[0] for item in child.call_args_list] == [
        "recruit_scrape.py",
        "recruit_classify.py",
    ]


def test_event_partial_fetch_is_a_failed_task_exit(monkeypatch) -> None:
    # Import through the same legacy module name used by the existing tests;
    # no database or network request is performed.
    sentiment_dir = ROOT / "tools" / "sentiment"
    monkeypatch.syspath_prepend(str(sentiment_dir))
    import event_ingest

    args = argparse.Namespace(max_llm=0, per_stock=1, all=False, verbose=False)
    senti = mock.MagicMock()
    research = mock.MagicMock()
    research.execute.return_value.fetchone.return_value = (1, "Test Company")
    monkeypatch.setattr(event_ingest, "CORE_TICKERS", ["000001.SZ"])
    monkeypatch.setattr(event_ingest.quiet_hours, "is_weekend", lambda: False)
    monkeypatch.setattr(event_ingest.argparse.ArgumentParser, "parse_args", lambda _self: args)
    monkeypatch.setattr(event_ingest.common, "get_senti_db", lambda **_: senti)
    monkeypatch.setattr(event_ingest.common, "assert_senti_only", lambda _con: None)
    monkeypatch.setattr(event_ingest.common, "load_closed_set", lambda: ({1}, None))
    monkeypatch.setattr(event_ingest.common, "research_ro_conn", lambda: research)
    monkeypatch.setattr(event_ingest, "get_orgid", lambda *_: (None, None, None))
    monkeypatch.setattr(
        event_ingest,
        "score_pending",
        lambda *_: {"pending_before": 0, "attempted": 0, "judged": 0, "pending_after": 0},
    )
    monkeypatch.setattr(event_ingest, "llm_client", None)

    assert event_ingest.main() == 2
    assert senti.close.call_count == 2
    research.close.assert_called_once()


def test_event_company_streams_have_retry_stable_operation_identities(
    monkeypatch,
) -> None:
    sentiment_dir = ROOT / "tools" / "sentiment"
    monkeypatch.syspath_prepend(str(sentiment_dir))
    import event_ingest

    monkeypatch.setenv(
        "HONGHU_OPERATION_ID", "stage5:IndustryDemo_EventIngest:2026-08-17"
    )
    calls: list[dict] = []
    connection = mock.MagicMock()
    monkeypatch.setattr(
        event_ingest.common,
        "get_senti_db",
        lambda **kwargs: calls.append(kwargs) or connection,
    )
    monkeypatch.setattr(event_ingest.common, "assert_senti_only", lambda _con: None)

    event_ingest._operation_connection("company:688041:org")
    event_ingest._operation_connection("company:688041:announcements")
    event_ingest._operation_connection("scoring")

    assert [item["operation_scope"] for item in calls] == [
        "event_ingest_step",
        "event_ingest_step",
        "event_ingest_step",
    ]
    assert [item["operation_id"] for item in calls] == [
        "stage5:IndustryDemo_EventIngest:2026-08-17:step:company:688041:org",
        "stage5:IndustryDemo_EventIngest:2026-08-17:step:company:688041:announcements",
        "stage5:IndustryDemo_EventIngest:2026-08-17:step:scoring",
    ]


def test_dynamic_schedule_phases_have_retry_stable_operation_identities(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "HONGHU_OPERATION_ID", "stage5:IndustryDemo_DynamicTick:2026-08-17T10:30"
    )
    calls: list[dict] = []
    connection = mock.MagicMock()
    monkeypatch.setattr(
        scheduler,
        "connect_operations",
        lambda *_args, **kwargs: calls.append(kwargs) or connection,
    )

    scheduler._operation_connection("schedule:41:acquire:2026-08-17T10:30:00")
    scheduler._operation_connection("schedule:41:outcome:2026-08-17T10:30:00")

    assert [item["operation_id"] for item in calls] == [
        "stage5:IndustryDemo_DynamicTick:2026-08-17T10:30:step:"
        "schedule:41:acquire:2026-08-17T10:30:00",
        "stage5:IndustryDemo_DynamicTick:2026-08-17T10:30:step:"
        "schedule:41:outcome:2026-08-17T10:30:00",
    ]


def test_recruit_company_streams_have_retry_stable_operation_identities(
    monkeypatch,
) -> None:
    sentiment_dir = ROOT / "tools" / "sentiment"
    monkeypatch.syspath_prepend(str(sentiment_dir))
    import recruit_scrape

    monkeypatch.setenv(
        "HONGHU_OPERATION_ID", "stage5:IndustryDemo_RecruitWeekly:2026-W34:step:recruit_scrape"
    )
    calls: list[dict] = []
    connection = mock.MagicMock()
    monkeypatch.setattr(
        recruit_scrape.common,
        "get_senti_db",
        lambda **kwargs: calls.append(kwargs) or connection,
    )
    monkeypatch.setattr(recruit_scrape.common, "assert_senti_only", lambda _con: None)

    recruit_scrape._operation_connection("source-registry")
    recruit_scrape._operation_connection("company:336:688041.SH")

    assert [item["operation_id"] for item in calls] == [
        "stage5:IndustryDemo_RecruitWeekly:2026-W34:step:recruit_scrape:"
        "step:source-registry",
        "stage5:IndustryDemo_RecruitWeekly:2026-W34:step:recruit_scrape:"
        "step:company:336:688041.SH",
    ]


@pytest.mark.parametrize(
    ("target_type", "target_id", "expected_step"),
    [
        ("voice_leader", 7, "schedule:41:voice:7"),
        ("news_source", 9, "schedule:41:news:9"),
    ],
)
def test_dynamic_target_failure_propagates_and_preserves_target_identity(
    monkeypatch, target_type: str, target_id: int, expected_step: str
) -> None:
    monkeypatch.setenv("HONGHU_OPERATION_ID", "stage5:IndustryDemo_DynamicTick:2026-08-17T10:30")
    monkeypatch.setenv("HONGHU_RELEASE_BOOTSTRAP", r"D:\release\direct_candidate.py")
    monkeypatch.setenv("HONGHU_LOCKED_SITE_PACKAGES", r"D:\python-env\site-packages")
    completed = SimpleNamespace(returncode=9, stdout="", stderr="producer failed")
    row = {
        "id": 41,
        "target_type": target_type,
        "target_id": target_id,
        "target_label": "target",
    }
    with mock.patch.object(scheduler, "log"), mock.patch.object(
        scheduler.subprocess, "run", return_value=completed
    ) as run:
        with pytest.raises(RuntimeError, match="rc=9"):
            scheduler.run_fetch(None, row)
    assert run.call_args.kwargs["env"]["HONGHU_OPERATION_ID"] == (
        f"stage5:IndustryDemo_DynamicTick:2026-08-17T10:30:step:{expected_step}"
    )
    assert run.call_args.args[0][1:4] == ["-I", "-B", "-S"]


def test_retail_children_use_isolated_modules_and_per_window_source_identities(
    monkeypatch,
) -> None:
    monkeypatch.setenv("HONGHU_OPERATION_ID", "stage5:IndustryDemo_Retail_Morning:2026-08-17:morning")
    monkeypatch.setenv("HONGHU_RELEASE_BOOTSTRAP", r"D:\release\direct_candidate.py")
    monkeypatch.setenv("HONGHU_LOCKED_SITE_PACKAGES", r"D:\python-env\site-packages")
    completed = SimpleNamespace(returncode=0, stdout="ok", stderr="")
    commands = [
        retail_window_tick.ChildCommand(
            "guba", "senti_fetch_guba.py", ("--window-id", "2026-08-17:morning"), 10
        ),
        retail_window_tick.ChildCommand(
            "score", "senti_score.py", ("--window-id", "2026-08-17:morning"), 10
        ),
    ]
    with mock.patch.object(retail_window_tick.subprocess, "run", return_value=completed) as run:
        assert all(retail_window_tick.run_child(command).ok for command in commands)

    guba, score = run.call_args_list
    assert guba.args[0][1:4] == ["-I", "-B", "-S"]
    assert "tools.sentiment.senti_fetch_guba" in guba.args[0]
    assert "tools.sentiment.senti_score" in score.args[0]
    guba_id = guba.kwargs["env"]["HONGHU_OPERATION_ID"]
    score_id = score.kwargs["env"]["HONGHU_OPERATION_ID"]
    assert guba_id.endswith(":step:retail:2026-08-17:morning:guba")
    assert score_id.endswith(":step:retail:2026-08-17:morning:score")
    assert guba_id != score_id


def test_retention_uses_stable_task_window_identity_not_random_audit_run(monkeypatch) -> None:
    monkeypatch.setenv("HONGHU_OPERATION_ID", "stage5:IndustryDemo_SentimentRetention:2026-08-17")
    as_of = datetime.fromisoformat("2026-08-17T03:00:00+08:00")
    first = sentiment_retention._retention_mutation_operation_id(as_of, "random-audit-run-a")
    second = sentiment_retention._retention_mutation_operation_id(as_of, "random-audit-run-b")
    assert first == second
    assert first == (
        "stage5:IndustryDemo_SentimentRetention:2026-08-17:"
        "step:retention:2026-08-17"
    )


def test_manual_retention_without_governed_runner_keeps_explicit_attempt_identity(
    monkeypatch,
) -> None:
    monkeypatch.delenv("HONGHU_OPERATION_ID", raising=False)
    as_of = datetime.fromisoformat("2026-08-17T03:00:00+08:00")
    assert sentiment_retention._retention_mutation_operation_id(as_of, "manual-run") == (
        "manual-run"
    )


def test_retail_historical_trial_requires_runner_authorization() -> None:
    source = (ROOT / "tools/sentiment/retail_window_tick.py").read_text(
        encoding="utf-8"
    )
    assert 'HONGHU_TASK_CONTROLLED_TRIAL") != "1"' in source
    assert "controlled session date is not authorized" in source


def test_active_task_mutable_paths_resolve_outside_immutable_release(tmp_path) -> None:
    state_root = tmp_path / "state"
    data_root = tmp_path / "data"
    content_root = tmp_path / "content"
    environment = dict(os.environ)
    environment.update(
        {
            "HONGHU_STATE_ROOT": str(state_root),
            "HONGHU_DATA_ROOT": str(data_root),
            "HONGHU_CONTENT_ROOT": str(content_root),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    script = r'''
import json
from tools.dynamic import scheduler
from tools.maintenance import sentiment_retention
from tools.sentiment import common, retail_window_tick, senti3
print(json.dumps({
    "scheduler_db": str(scheduler.DB),
    "scheduler_log": str(scheduler.LOGDIR),
    "sentiment_db": str(common.SENTI_DB),
    "research_db": str(common.RESEARCH_DB),
    "secrets": str(common.SECRETS),
    "retail_lock": str(retail_window_tick.TICK_LOCK_PATH),
    "yuqing_cache": str(senti3.CACHE_YUQING),
    "retention_db": str(sentiment_retention.DEFAULT_DB),
}, sort_keys=True))
'''
    completed = subprocess.run(
        [sys.executable, "-B", "-c", script],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert Path(payload["scheduler_db"]).is_relative_to(data_root)
    assert Path(payload["sentiment_db"]).is_relative_to(data_root)
    assert Path(payload["research_db"]).is_relative_to(data_root)
    assert Path(payload["retention_db"]).is_relative_to(data_root)
    assert Path(payload["scheduler_log"]).is_relative_to(state_root)
    assert Path(payload["retail_lock"]).is_relative_to(state_root)
    assert Path(payload["yuqing_cache"]).is_relative_to(state_root)
    assert Path(payload["secrets"]).is_relative_to(content_root)
    for value in payload.values():
        assert not Path(value).is_relative_to(ROOT)
