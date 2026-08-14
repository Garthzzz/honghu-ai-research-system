from __future__ import annotations

"""Shared naming and compatibility rules for Stage 4 runtime evidence."""

from typing import Any, Mapping


class RuntimeContractError(RuntimeError):
    pass


def tracked_static_default_route(runtime: Mapping[str, Any]) -> str:
    """Return the tracked bootstrap default without claiming live authority.

    ``application_route`` was the v1 field name.  It described the immutable
    tracked/bootstrap default, not the authoritative backend after a cutover.
    New evidence uses ``tracked_static_default_route`` and accepts the old name
    only as an equal-valued compatibility alias.
    """

    current = runtime.get("tracked_static_default_route")
    legacy = runtime.get("application_route")
    if current is None:
        current = legacy
    if current != "sqlite_transition":
        raise RuntimeContractError(
            "tracked static default route is not the frozen SQLite transition baseline"
        )
    if legacy is not None and legacy != current:
        raise RuntimeContractError(
            "legacy application_route conflicts with tracked_static_default_route"
        )
    return str(current)
