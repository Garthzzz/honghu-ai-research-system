from __future__ import annotations

import pytest

from tools.operations.stage5_sentiment_batch_rehearsal import (
    RehearsalError,
    _mutation,
    run_rehearsal,
)


def test_rehearsal_refuses_production_or_non_loopback_targets(tmp_path) -> None:
    common = dict(
        root=tmp_path,
        admin_user="test",
        database="honghu_stage3_fixture",
        row_count=1000,
    )
    with pytest.raises(RehearsalError, match="non-production loopback"):
        run_rehearsal(host="10.0.0.1", port=55432, **common)
    with pytest.raises(RehearsalError, match="non-production loopback"):
        run_rehearsal(host="127.0.0.1", port=5432, **common)


def test_rehearsal_mutation_identity_is_stable() -> None:
    assert _mutation("row-1") == _mutation("row-1")
    assert _mutation("row-1")["request_sha256"] != _mutation("row-2")[
        "request_sha256"
    ]
