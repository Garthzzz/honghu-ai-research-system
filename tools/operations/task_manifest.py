from __future__ import annotations

"""Strict, secret-free contract for reviewed production task triggers."""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


TASK_ID = re.compile(r"^IndustryDemo_[A-Za-z0-9_]+$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
UNITS = {
    "operations_governance",
    "dynamic_intelligence",
    "sentiment_analytics",
    "financial_data",
}
SCHEDULE_KINDS = {"weekday_interval", "weekdays_at", "weekly_at", "monthly_at"}
WINDOW_KINDS = {"quarter_hour", "business_date", "iso_week", "business_date_slot", "calendar_month"}
TASK_MODULES = {
    "IndustryDemo_DynamicTick": "tools.dynamic.scheduler",
    "IndustryDemo_EventIngest": "tools.sentiment.event_ingest",
    "IndustryDemo_RecruitWeekly": "tools.sentiment.recruit_weekly",
    "IndustryDemo_Retail_Preopen": "tools.sentiment.retail_window_tick",
    "IndustryDemo_Retail_Morning": "tools.sentiment.retail_window_tick",
    "IndustryDemo_Retail_Afternoon": "tools.sentiment.retail_window_tick",
    "IndustryDemo_SentimentRetention": "tools.maintenance.sentiment_retention",
    "IndustryDemo_ValuationMarket_1140": "tools.financial.valuation_market_refresh",
    "IndustryDemo_ValuationMarket_1510": "tools.financial.valuation_market_refresh",
    "IndustryDemo_ValuationAI_Monthly": "tools.financial.valuation_ai_refresh",
}


class TaskManifestError(ValueError):
    pass


@dataclass(frozen=True)
class TaskDefinition:
    task_id: str
    cutover_unit: str
    writer_units: tuple[str, ...]
    schedule: dict[str, Any]
    window: dict[str, Any]
    freshness_seconds: int
    execution_timeout_seconds: int
    command: tuple[str, ...]
    legacy_definition_sha256: str
    legacy_principal: str


@dataclass(frozen=True)
class TaskManifest:
    path: Path
    sha256: str
    timezone: str
    runner_host: str
    legacy_runner_host: str
    legacy_runner_host_identity_sha256: str
    local_disabled_evidence_max_age_seconds: int
    tasks: dict[str, TaskDefinition]


def _command(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) < 2:
        raise TaskManifestError("task command must be a non-empty argv array")
    command = tuple(str(item) for item in value)
    if command[0] != "-m" or not command[1].startswith("tools."):
        raise TaskManifestError("task command must use a reviewed tools.* module")
    if any(not item or any(char in item for char in "\r\n&|;<>\x00") for item in command):
        raise TaskManifestError("task command contains an unsafe token")
    return command


def _clock(value: Any, *, field: str) -> tuple[int, int]:
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value):
        raise TaskManifestError(f"{field} is not a valid 24-hour time")
    return tuple(int(item) for item in value.split(":"))  # type: ignore[return-value]


def load_task_manifest(path: str | Path) -> TaskManifest:
    source = Path(path).resolve()
    raw = source.read_bytes()
    payload = json.loads(raw.decode("utf-8-sig"))
    if payload.get("schema_version") != "honghu.production_task_manifest.v1":
        raise TaskManifestError("unsupported production task manifest")
    if payload.get("timezone") != "Asia/Shanghai":
        raise TaskManifestError("production tasks require Asia/Shanghai timezone")
    host = str(payload.get("runner_host") or "").strip().upper()
    if not host:
        raise TaskManifestError("runner host is required")
    legacy_host = str(payload.get("legacy_runner_host") or "").strip().upper()
    legacy_host_identity = str(
        payload.get("legacy_runner_host_identity_sha256") or ""
    ).strip().lower()
    max_evidence_age = int(payload.get("local_disabled_evidence_max_age_seconds") or 0)
    if not legacy_host or legacy_host == host:
        raise TaskManifestError("legacy runner host must be distinct from the VM runner host")
    if not SHA256.fullmatch(legacy_host_identity):
        raise TaskManifestError("legacy runner host identity is invalid")
    if not 60 <= max_evidence_age <= 3600:
        raise TaskManifestError("local disabled evidence freshness is outside bounds")
    definitions: dict[str, TaskDefinition] = {}
    for raw_task in payload.get("tasks") or ():
        task_id = str(raw_task.get("task_id") or "")
        unit = str(raw_task.get("cutover_unit") or "")
        writers = tuple(str(item) for item in raw_task.get("writer_units") or ())
        schedule = dict(raw_task.get("schedule") or {})
        window = dict(raw_task.get("window") or {})
        if not TASK_ID.fullmatch(task_id) or task_id in definitions:
            raise TaskManifestError("task identity is invalid or duplicated")
        if unit not in UNITS or not writers or any(item not in UNITS for item in writers):
            raise TaskManifestError(f"task {task_id} has an unreviewed writer unit")
        if unit not in writers:
            raise TaskManifestError(f"task {task_id} primary unit is not a writer unit")
        if schedule.get("kind") not in SCHEDULE_KINDS:
            raise TaskManifestError(f"task {task_id} schedule is unsupported")
        if window.get("kind") not in WINDOW_KINDS:
            raise TaskManifestError(f"task {task_id} logical window is unsupported")
        if window.get("kind") == "quarter_hour" and int(window.get("minutes") or 0) != int(schedule.get("minutes") or 0):
            raise TaskManifestError(f"task {task_id} interval/window cadence differs")
        if window.get("kind") == "business_date_slot":
            if task_id.startswith("IndustryDemo_ValuationMarket_"):
                expected_slot = task_id.removeprefix(
                    "IndustryDemo_ValuationMarket_"
                )
            else:
                expected_slot = task_id.removeprefix(
                    "IndustryDemo_Retail_"
                ).casefold()
            if window.get("slot") != expected_slot:
                raise TaskManifestError(f"task {task_id} slot identity differs")
        freshness = int(raw_task.get("freshness_seconds") or 0)
        timeout = int(raw_task.get("execution_timeout_seconds") or 0)
        # Retail preserves its bounded three-window catch-up contract.  Its
        # reviewed worst case is one lock wait + one orphan wait + four
        # sequential 12-hour windows, so a one-day cap would terminate a
        # healthy writer before its own child budgets expire.
        if not 60 <= freshness <= 45 * 86400 or not 60 <= timeout <= 3 * 86400:
            raise TaskManifestError(f"task {task_id} time contract is outside bounds")
        if task_id not in TASK_MODULES:
            raise TaskManifestError("the reviewed production-task identity set changed")
        command = _command(raw_task.get("command"))
        if command[1] != TASK_MODULES[task_id]:
            raise TaskManifestError(f"task {task_id} module is not the reviewed producer")
        legacy_definition_sha256 = str(
            raw_task.get("legacy_definition_sha256") or ""
        ).strip().lower()
        legacy_principal = str(raw_task.get("legacy_principal") or "").strip()
        if not SHA256.fullmatch(legacy_definition_sha256) or not legacy_principal:
            raise TaskManifestError(f"task {task_id} legacy definition identity is invalid")
        kind = schedule["kind"]
        if kind == "weekday_interval":
            start = _clock(schedule.get("start"), field=f"task {task_id} start")
            end = _clock(schedule.get("end"), field=f"task {task_id} end")
            minutes = int(schedule.get("minutes") or 0)
            if start >= end or not 1 <= minutes <= 1440:
                raise TaskManifestError(f"task {task_id} interval schedule is invalid")
        else:
            _clock(schedule.get("at"), field=f"task {task_id} at")
            if kind == "weekly_at" and schedule.get("weekday") != "Monday":
                raise TaskManifestError(f"task {task_id} weekly schedule is unreviewed")
            if kind == "monthly_at" and not 1 <= int(schedule.get("day") or 0) <= 28:
                raise TaskManifestError(f"task {task_id} monthly day is invalid")
        definitions[task_id] = TaskDefinition(
            task_id=task_id,
            cutover_unit=unit,
            writer_units=writers,
            schedule=schedule,
            window=window,
            freshness_seconds=freshness,
            execution_timeout_seconds=timeout,
            command=command,
            legacy_definition_sha256=legacy_definition_sha256,
            legacy_principal=legacy_principal,
        )
    if set(definitions) != set(TASK_MODULES):
        raise TaskManifestError("the production manifest differs from the reviewed task set")
    return TaskManifest(
        path=source,
        sha256=hashlib.sha256(raw).hexdigest(),
        timezone="Asia/Shanghai",
        runner_host=host,
        legacy_runner_host=legacy_host,
        legacy_runner_host_identity_sha256=legacy_host_identity,
        local_disabled_evidence_max_age_seconds=max_evidence_age,
        tasks=definitions,
    )
