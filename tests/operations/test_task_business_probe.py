from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from tools.operations import task_business_probe


class FakeConnection:
    def __init__(self, row):
        self.row = row
        self.query = None
        self.parameters = None
        self.closed = False

    def execute(self, query, parameters=()):
        self.query = query
        self.parameters = parameters
        return self

    def fetchall(self):
        return [self.row]

    def close(self):
        self.closed = True


@pytest.mark.parametrize(
    ("task_id", "expected_kind"),
    [
        ("IndustryDemo_DynamicTick", "dynamic_fetch_schedule"),
        ("IndustryDemo_EventIngest", "event_item"),
        ("IndustryDemo_RecruitWeekly", "recruit_change_log"),
        ("IndustryDemo_Retail_Morning", "retail_window_ledger"),
        ("IndustryDemo_SentimentRetention", "sentiment_retention_run"),
    ],
)
def test_probes_are_read_only_and_identity_bound(task_id, expected_kind):
    connection = FakeConnection((1, "checkpoint"))
    with mock.patch(
        "tools.data_platform.domain_data.connect_domain_database",
        return_value=connection,
    ) as connect:
        result = task_business_probe.probe(
            task_id,
            "2026-08-17:morning",
            data_root=Path(r"D:\runtime-data"),
        )
    assert connect.call_args.kwargs["readonly"] is True
    assert result["probe_kind"] == expected_kind
    assert len(result["identity_sha256"]) == 64
    assert connection.closed is True


def test_unknown_task_has_no_generic_probe_fallback():
    with pytest.raises(ValueError, match="unreviewed"):
        task_business_probe.probe(
            "IndustryDemo_Unknown",
            "2026-08-17",
            data_root=Path(r"D:\runtime-data"),
        )
