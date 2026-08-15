from __future__ import annotations

import pytest

from tools.migration.stage4_remaining_unit_rehearsal import (
    RemainingUnitRehearsalError,
    validate_target,
)


def test_rehearsal_target_is_loopback_and_explicitly_nonproduction() -> None:
    validate_target("127.0.0.1", "honghu_stage4_rehearsal")
    with pytest.raises(RemainingUnitRehearsalError, match="loopback"):
        validate_target("10.5.1.240", "honghu_stage4_rehearsal")
    with pytest.raises(RemainingUnitRehearsalError, match="isolated rehearsal"):
        validate_target("127.0.0.1", "honghu_production")
