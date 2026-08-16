from __future__ import annotations

import pytest

from tools.operations.task_child import ALLOWED_TASK_MODULES, main


def test_task_child_has_only_the_seven_task_module_families():
    assert {
        "tools.dynamic.scheduler",
        "tools.sentiment.event_ingest",
        "tools.sentiment.recruit_weekly",
        "tools.sentiment.retail_window_tick",
        "tools.maintenance.sentiment_retention",
    }.issubset(ALLOWED_TASK_MODULES)


def test_task_child_rejects_an_unreviewed_module():
    with pytest.raises(SystemExit) as exc:
        main(["--task-module", "tools.viewer.app"])
    assert exc.value.code == 2
