from __future__ import annotations

"""One-time, append-audited recovery for missing A-share closing prices."""

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
    fetch_intraday_market_quote,
    load_wind_http_client,
)


BEIJING = ZoneInfo("Asia/Shanghai")


def _repository(path: Path) -> ValuationTrackerRepository:
    catalog = load_postgres_runtime_catalog(path)
    return ValuationTrackerRepository(
        build_catalog_connection_factory(catalog, role="reader"),
        build_catalog_connection_factory(catalog, role="writer_financial_data"),
    )


def run(*, now: datetime | None = None) -> dict:
    current = (now or datetime.now(BEIJING)).astimezone(BEIJING)
    if current.time() < time(15, 10):
        raise RuntimeError("closing-price reconciliation is allowed only after 15:10")
    runtime = Path(os.environ["HONGHU_POSTGRES_RUNTIME_CONFIG"])
    actor = str(os.environ.get("HONGHU_AUDIT_ACTOR") or "HonghuDeploymentReconcile")
    repo = _repository(runtime)
    operation_id = f"valuation-market-price-reconcile:{current.date().isoformat()}:1510:v1"
    idempotency_key = "price-reconcile:" + hashlib.sha256(operation_id.encode()).hexdigest()
    committed = repo.committed_task_result("backfill_market_price_v1", idempotency_key)
    if committed is not None:
        return committed
    client = load_wind_http_client()
    calendar = a_share_trading_day_evidence(current.date().isoformat(), client=client)
    if calendar.get("is_trading_day") is not True:
        raise RuntimeError("price reconciliation requires a verified A-share trading day")
    items = []
    for member in repo.a_share_members():
        quote = fetch_intraday_market_quote(
            member["canonical_ticker"], trade_date=current.date().isoformat(), client=client
        )
        items.append({
            "security_id": member["security_id"],
            "ticker": member["canonical_ticker"],
            "share_price_value": quote["share_price_value"],
            "share_price_currency": quote["share_price_currency"],
            "share_price_unit": quote["share_price_unit"],
            "share_price_raw_field": quote["share_price_raw_field"],
            "share_price_source_ref": quote["source_ref"],
            "share_price_raw_sha256": sha256_json(quote),
        })
    result = repo.backfill_market_prices(
        current.date(), "1510", current, items,
        actor=actor, idempotency_key=idempotency_key,
    )
    result["task_scope"] = {
        "security_count": 6,
        "field_count": 1,
        "estimated_observations": 6,
        "large_request_permission_required": False,
    }
    return result


def main() -> int:
    print(json.dumps(run(), ensure_ascii=False, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
