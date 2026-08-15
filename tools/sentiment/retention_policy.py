"""Active lifecycle constants for short-lived sentiment source records."""

from __future__ import annotations


RAW_RETENTION_DAYS = 3
INCOMPLETE_FINALIZATION_DAYS = 3


def validate() -> None:
    if RAW_RETENTION_DAYS != 3 or INCOMPLETE_FINALIZATION_DAYS != 3:
        raise RuntimeError("sentiment raw lifecycle must remain the approved three days")
