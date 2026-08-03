from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.pipeline.tushare_provider import (
    fetch_balancesheet_rows,
    fetch_cashflow_rows,
    fetch_daily_basic_latest,
    fetch_fina_indicator_rows,
    fetch_income_rows,
)
from tools.pipeline.wind_http_provider import (
    WindHttpUnavailable,
    assert_wind_request_scope,
    fetch_current_market_financial_snapshot,
    load_wind_http_client,
)


TICKER = "603799.SH"
COMPANY_NAME = "华友钴业"
COMPANY_ID = 631
TRADE_DATE = "2026-07-23"
YEARS = ("2021", "2022", "2023", "2024", "2025", "2026")

HISTORICAL_FIELDS = (
    "oper_rev",
    "np_belongto_parcomsh",
    "net_cash_flows_oper_act",
    "cash_pay_acq_const_fiolta",
    "tot_assets",
    "tot_equity",
    "tot_liab",
    "roe",
    "roa2",
    "grossprofitmargin",
    "netprofitmargin",
)
CONSENSUS_FIELDS = (
    "west_sales_fy1",
    "west_sales_fy2",
    "west_sales_fy3",
    "west_netprofit_fy1",
    "west_netprofit_fy2",
    "west_netprofit_fy3",
    "west_eps_fy1",
    "west_eps_fy2",
    "west_eps_fy3",
    "west_avgroe_fy1",
    "west_avgroe_fy2",
    "west_avgroe_fy3",
)


def _frame_rows(frame: Any) -> dict[str, dict[str, float | None]]:
    if frame is None or getattr(frame, "empty", True):
        return {}
    clean = frame.where(frame.notna(), None)
    result: dict[str, dict[str, float | None]] = {}
    for index, row in clean.iterrows():
        values: dict[str, float | None] = {}
        for column, raw in row.items():
            value = raw.item() if hasattr(raw, "item") else raw
            values[str(column).lower()] = float(value) if value is not None else None
        result[str(index)] = values
    return result


def _canonical_hash(payload: Any) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _wss(
    client: Any,
    fields: tuple[str, ...],
    options: str,
) -> dict[str, Any]:
    assert_wind_request_scope(
        security_count=1,
        field_count=len(fields),
        estimated_observations=len(fields),
    )
    response = client.wss(TICKER, ",".join(fields), options)
    error_code = int(getattr(response, "ErrorCode", -1))
    if error_code != 0:
        raise WindHttpUnavailable(f"Wind WSS失败：ErrorCode={error_code}")
    return {
        "status": "ok",
        "fields": list(fields),
        "options": options,
        "rows": _frame_rows(getattr(response, "dfData", None)),
    }


def collect() -> dict[str, Any]:
    client = load_wind_http_client()
    payload: dict[str, Any] = {
        "snapshot_version": "run14.huayou_financial_snapshot.v1",
        "accessed_at_utc": datetime.now(timezone.utc).isoformat(),
        "company": {
            "company_id": COMPANY_ID,
            "name": COMPANY_NAME,
            "ticker": TICKER,
        },
        "scope_audit": {
            "wind_security_count": 1,
            "wind_current_fields": 12,
            "wind_historical_fields_per_year": len(HISTORICAL_FIELDS),
            "wind_historical_years": 5,
            "wind_consensus_fields": len(CONSENSUS_FIELDS),
            "wind_estimated_observations": (
                12 + 5 * len(HISTORICAL_FIELDS) + len(CONSENSUS_FIELDS)
            ),
            "large_request_permission_required": False,
            "database_boundary": "抓取底稿不直接写库；最终仅经独立财务导出写入financial.db",
        },
        "wind": {},
        "tushare": {},
    }
    payload["wind"]["current"] = fetch_current_market_financial_snapshot(
        TICKER,
        trade_date=TRADE_DATE,
        client=client,
    )
    annual: dict[str, Any] = {}
    for year in YEARS[:-1]:
        annual[year] = _wss(
            client,
            HISTORICAL_FIELDS,
            f"rptDate={year}1231;rptType=1;unit=1",
        )
    payload["wind"]["historical_annual"] = annual
    payload["wind"]["consensus_fy1_fy3"] = _wss(
        client,
        CONSENSUS_FIELDS,
        f"tradeDate={TRADE_DATE.replace('-', '')};unit=1",
    )
    payload["tushare"] = {
        "daily_basic_latest": fetch_daily_basic_latest(TICKER),
        "income_2021_2026": fetch_income_rows(TICKER, years=YEARS),
        "fina_indicator_2021_2026": fetch_fina_indicator_rows(
            TICKER, years=YEARS
        ),
        "cashflow_2021_2026": fetch_cashflow_rows(TICKER, years=YEARS),
        "balancesheet_2021_2026": fetch_balancesheet_rows(
            TICKER, years=YEARS
        ),
    }
    payload["content_sha256"] = _canonical_hash(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="华友钴业Run14单证券窄字段Wind/Tushare财务快照"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = collect()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "sha256": payload["content_sha256"],
                "wind_estimated_observations": payload["scope_audit"][
                    "wind_estimated_observations"
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
