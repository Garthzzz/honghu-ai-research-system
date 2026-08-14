from __future__ import annotations

"""Fail-closed local marker for a unit whose SQLite writer was retired.

The marker is operational state, not the authority source. PostgreSQL's
authority ledger remains authoritative; this file prevents an old local CLI
from silently writing a stale SQLite migration baseline.
"""

import json
from pathlib import Path
from typing import Any


class LocalAuthorityFenceError(RuntimeError):
    pass


BLOCKING_STATES = {"S2_PENDING", "S2", "S3", "S4"}


def authority_fence_path(data_root: str | Path, cutover_unit: str) -> Path:
    unit = str(cutover_unit or "").strip()
    if not unit or not unit.replace("_", "").isalnum():
        raise LocalAuthorityFenceError("invalid cutover unit for local fence")
    return Path(data_root).resolve() / "authority" / f"{unit}.json"


def load_authority_fence(
    data_root: str | Path, cutover_unit: str
) -> dict[str, Any] | None:
    path = authority_fence_path(data_root, cutover_unit)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != "honghu.local_authority_fence.v1"
    ):
        raise LocalAuthorityFenceError("local authority fence is malformed")
    if payload.get("cutover_unit") != cutover_unit:
        raise LocalAuthorityFenceError("local authority fence unit mismatch")
    state = str(payload.get("authority_state") or "")
    backend = str(payload.get("authoritative_backend") or "")
    if state in BLOCKING_STATES and backend != "postgresql_production":
        raise LocalAuthorityFenceError("blocking local fence has an invalid backend")
    if state in {"S0", "S1"} and backend != "sqlite_transition":
        raise LocalAuthorityFenceError("SQLite local fence has an invalid backend")
    if state not in BLOCKING_STATES | {"S0", "S1"}:
        raise LocalAuthorityFenceError("local authority fence has an unknown state")
    return payload


def assert_sqlite_write_allowed(data_root: str | Path, cutover_unit: str) -> None:
    payload = load_authority_fence(data_root, cutover_unit)
    if payload is None:
        return
    if payload["authority_state"] in BLOCKING_STATES:
        raise LocalAuthorityFenceError(
            f"{cutover_unit} SQLite writer is retired by local authority fence "
            f"state={payload['authority_state']}"
        )
