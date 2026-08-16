from __future__ import annotations

import pytest

from tools.migration.stage4_remaining_unit_rehearsal import (
    REPRESENTATIVE_OBJECTS,
    RemainingUnitRehearsalError,
    validate_application_commit,
    validate_target,
)


def test_rehearsal_target_is_loopback_and_explicitly_nonproduction() -> None:
    validate_target("127.0.0.1", "honghu_stage4_rehearsal")
    with pytest.raises(RemainingUnitRehearsalError, match="loopback"):
        validate_target("10.5.1.240", "honghu_stage4_rehearsal")
    with pytest.raises(RemainingUnitRehearsalError, match="isolated rehearsal"):
        validate_target("127.0.0.1", "honghu_production")


def test_every_remaining_unit_has_a_distinct_representative_owned_object() -> None:
    assert set(REPRESENTATIVE_OBJECTS) == {
        "financial_data",
        "research_publication",
        "dynamic_intelligence",
        "operations_governance",
        "investment_hypotheses",
        "opportunity_lens",
        "sentiment_analytics",
    }
    assert len(set(REPRESENTATIVE_OBJECTS.values())) == len(REPRESENTATIVE_OBJECTS)


def test_rehearsal_requires_exact_application_commit() -> None:
    assert validate_application_commit("a" * 40) == "a" * 40
    with pytest.raises(RemainingUnitRehearsalError, match="exact lowercase"):
        validate_application_commit("A" * 40)
