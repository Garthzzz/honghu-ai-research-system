from __future__ import annotations

"""Read-only domain checkpoint probes for the seven production tasks."""

import hashlib
import json
from pathlib import Path
from typing import Any


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _rows(connection: Any, query: str, parameters: tuple[Any, ...] = ()) -> list[list[Any]]:
    return [list(row) for row in connection.execute(query, parameters).fetchall()]


def probe(task_id: str, logical_window: str, *, data_root: Path) -> dict[str, Any]:
    """Capture a task-specific business checkpoint without mutating authority."""

    from tools.data_platform.domain_data import connect_domain_database

    if task_id == "IndustryDemo_DynamicTick":
        unit, database = "operations_governance", data_root / "research.db"
        query = """SELECT COUNT(*),
                          COALESCE(SUM(CASE WHEN is_running=1 THEN 1 ELSE 0 END),0),
                          COALESCE(SUM(CASE WHEN status IN ('error','paused') THEN 1 ELSE 0 END),0),
                          MAX(last_run_at),MAX(updated_at)
                     FROM fetch_schedule WHERE is_active=1"""
        parameters: tuple[Any, ...] = ()
        kind = "dynamic_fetch_schedule"
    elif task_id == "IndustryDemo_EventIngest":
        unit, database = "sentiment_analytics", data_root / "sentiment.db"
        query = "SELECT COUNT(*),MAX(fetched_at),COALESCE(SUM(CASE WHEN materiality IS NULL OR sentiment IS NULL THEN 1 ELSE 0 END),0) FROM event_item"
        parameters = ()
        kind = "event_item"
    elif task_id == "IndustryDemo_RecruitWeekly":
        unit, database = "sentiment_analytics", data_root / "sentiment.db"
        query = "SELECT COUNT(*),MAX(run_date),MAX(fetched_at) FROM recruit_change_log"
        parameters = ()
        kind = "recruit_change_log"
    elif task_id.startswith("IndustryDemo_Retail_"):
        unit, database = "sentiment_analytics", data_root / "sentiment.db"
        query = "SELECT window_id,status,raw_count,scored_count,aggregate_sha256,finished_at,sealed_at FROM retail_window_ledger WHERE window_id=?"
        parameters = (logical_window,)
        kind = "retail_window_ledger"
    elif task_id == "IndustryDemo_SentimentRetention":
        unit, database = "sentiment_analytics", data_root / "sentiment.db"
        query = "SELECT run_id,state,started_at,finished_at,result_json,error FROM sentiment_retention_run ORDER BY started_at DESC LIMIT 1"
        parameters = ()
        kind = "sentiment_retention_run"
    else:
        raise ValueError(f"unreviewed production task probe: {task_id}")
    connection = connect_domain_database(unit, database, readonly=True)
    try:
        observed = _rows(connection, query, parameters)
    finally:
        connection.close()
    payload = {
        "schema_version": "honghu.production_task_business_checkpoint.v1",
        "task_id": task_id,
        "logical_window": logical_window,
        "unit": unit,
        "probe_kind": kind,
        "rows": observed,
    }
    return {**payload, "identity_sha256": _sha(payload)}
