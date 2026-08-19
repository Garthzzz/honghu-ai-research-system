from __future__ import annotations

"""Refresh the six A-share market-cap snapshots for one reviewed intraday slot."""

import argparse
import hashlib
import json
import os
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from tools.data_platform.postgres_runtime import (
    build_catalog_connection_factory,
    load_postgres_runtime_catalog,
)
from tools.financial.valuation_tracker import ValuationTrackerRepository, sha256_json
from tools.pipeline.wind_http_provider import (
    a_share_trading_day_evidence,
    fetch_intraday_market_cap,
    load_wind_http_client,
)


BEIJING = ZoneInfo("Asia/Shanghai")
SLOT_TIMES = {"1140": time(11, 40), "1510": time(15, 10)}


def _repository(path: Path) -> ValuationTrackerRepository:
    catalog = load_postgres_runtime_catalog(path)
    return ValuationTrackerRepository(
        build_catalog_connection_factory(catalog, role="reader"),
        build_catalog_connection_factory(catalog, role="writer_financial_data"),
    )


def run(slot: str, *, now: datetime | None = None) -> dict:
    if slot not in SLOT_TIMES:
        raise ValueError("slot must be 1140 or 1510")
    current = (now or datetime.now(BEIJING)).astimezone(BEIJING)
    if current.time() < SLOT_TIMES[slot]:
        raise RuntimeError(f"slot {slot} has not reached its trigger time")
    runtime = Path(os.environ["HONGHU_POSTGRES_RUNTIME_CONFIG"])
    actor = str(os.environ.get("HONGHU_AUDIT_ACTOR") or "HonghuTaskRunner")
    operation_id = str(
        os.environ.get("HONGHU_OPERATION_ID")
        or f"valuation-market:{current.date().isoformat()}:{slot}"
    )
    repo = _repository(runtime)
    idem = hashlib.sha256(operation_id.encode("utf-8")).hexdigest()
    for scope, key in (
        ("record_market_batch_v1", f"market-batch:{idem}"),
        ("record_market_skip_v1", f"market-skip:{idem}"),
    ):
        committed = repo.committed_task_result(scope, key)
        if committed is not None:
            return committed
    client = load_wind_http_client()
    evidence = a_share_trading_day_evidence(
        current.date().isoformat(), client=client
    )
    evidence.update({
        "slot": slot,
        "trigger_time": SLOT_TIMES[slot].isoformat(timespec="minutes"),
        "executed_at": current.isoformat(),
        "late_seconds": max(
            0,
            int(
                (
                    current
                    - current.replace(
                        hour=SLOT_TIMES[slot].hour,
                        minute=SLOT_TIMES[slot].minute,
                        second=0,
                        microsecond=0,
                    )
                ).total_seconds()
            ),
        ),
    })
    if not evidence["is_trading_day"]:
        return repo.record_market_skip(
            current.date(), slot, "Wind.tdays:SSE+SZSE", evidence,
            actor=actor, idempotency_key=f"market-skip:{idem}",
        )
    items = []
    for member in repo.a_share_members():
        observed = fetch_intraday_market_cap(
            member["canonical_ticker"],
            trade_date=current.date().isoformat(),
            client=client,
        )
        item = {
            "member_id": member["member_id"],
            "security_id": member["security_id"],
            "ticker": member["canonical_ticker"],
            "market_cap_value": observed["market_cap_value"],
            "currency": observed["currency"],
            "unit": observed["unit"],
            "trading_status": observed["trading_status"],
            "source_ref": observed["source_ref"],
            "raw_sha256": sha256_json(observed),
        }
        items.append(item)
    result = repo.record_market_batch(
        current.date(), slot, current, "Wind.tdays:SSE+SZSE", evidence, items,
        actor=actor, idempotency_key=f"market-batch:{idem}",
    )
    result["task_scope"] = {
        "security_count": 6,
        "field_count": 2,
        "estimated_observations": 12,
        "task_daily_security_calls": 12,
        "large_request_permission_required": False,
    }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slot", choices=sorted(SLOT_TIMES), required=True)
    args = parser.parse_args(argv)
    print(json.dumps(run(args.slot), ensure_ascii=False, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
