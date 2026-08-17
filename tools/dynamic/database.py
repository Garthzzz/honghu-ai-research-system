from __future__ import annotations

"""Authoritative connection boundary for dynamic-intelligence writers."""

from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
from tools.runtime_paths import resolve_runtime_layout
DEFAULT_DB = resolve_runtime_layout(ROOT).data_root / "research.db"


def connect_dynamic(
    db_path: str | Path = DEFAULT_DB,
    *,
    readonly: bool = False,
    operation_scope: str = "dynamic_intelligence_mutation",
    operation_id: str | None = None,
    actor: str | None = None,
) -> Any:
    from tools.data_platform.domain_data import connect_domain_database

    return connect_domain_database(
        "dynamic_intelligence",
        db_path,
        readonly=readonly,
        operation_scope=operation_scope,
        operation_id=operation_id,
        actor=actor,
    )


def connect_operations(
    db_path: str | Path = DEFAULT_DB,
    *,
    readonly: bool = False,
    operation_scope: str = "operations_checkpoint_mutation",
    operation_id: str | None = None,
    actor: str | None = None,
) -> Any:
    from tools.data_platform.domain_data import connect_domain_database

    return connect_domain_database(
        "operations_governance",
        db_path,
        readonly=readonly,
        operation_scope=operation_scope,
        operation_id=operation_id,
        actor=actor,
    )
