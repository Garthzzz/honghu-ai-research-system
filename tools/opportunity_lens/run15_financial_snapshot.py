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


TICKER = "601877.SH"
COMPANY_NAME = "正泰电器"
COMPANY_ID = 632
TRADE_DATE = "2026-07-24"
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
            values[str(column).lower()] = (
                float(value) if value is not None else None
            )
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


def _wss(client: Any, fields: tuple[str, ...], options: str) -> dict[str, Any]:
    assert_wind_request_scope(
        security_count=1,
        field_count=len(fields),
        estimated_observations=len(fields),
    )
    response = client.wss(TICKER, ",".join(fields), options)
    error_code = int(getattr(response, "ErrorCode", -1))
    if error_code != 0:
        raise WindHttpUnavailable(
            f"Wind WSS failed for {TICKER}: ErrorCode={error_code}"
        )
    return {
        "status": "ok",
        "fields": list(fields),
        "options": options,
        "rows": _frame_rows(getattr(response, "dfData", None)),
    }


def collect(
    *,
    include_consensus: bool,
    include_tushare: bool = True,
) -> dict[str, Any]:
    client = load_wind_http_client()
    estimated = 12 + 5 * len(HISTORICAL_FIELDS)
    if include_consensus:
        estimated += len(CONSENSUS_FIELDS)
    payload: dict[str, Any] = {
        "snapshot_version": "run15.chint_financial_snapshot.v1",
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
            "wind_consensus_fields": (
                len(CONSENSUS_FIELDS) if include_consensus else 0
            ),
            "wind_estimated_observations": estimated,
            "large_request_permission_required": False,
            "purpose": "单证券窄字段财务建模与外部对账",
        },
        "wind": {},
        "tushare": {},
    }
    try:
        payload["wind"]["current"] = fetch_current_market_financial_snapshot(
            TICKER,
            trade_date=TRADE_DATE,
            client=client,
        )
    except WindHttpUnavailable as exc:
        payload["wind"]["status"] = "unavailable"
        payload["wind"]["error_type"] = type(exc).__name__
    else:
        payload["wind"]["status"] = "ok"
        payload["wind"]["historical_annual"] = {
            year: _wss(
                client,
                HISTORICAL_FIELDS,
                f"rptDate={year}1231;rptType=1;unit=1",
            )
            for year in YEARS[:-1]
        }
        if include_consensus:
            payload["wind"]["consensus_fy1_fy3"] = _wss(
                client,
                CONSENSUS_FIELDS,
                f"tradeDate={TRADE_DATE.replace('-', '')};unit=1",
            )
    if include_tushare:
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
    else:
        payload["tushare"] = {
            "status": "not_requested",
            "reason": "本次只重试已获授权的Wind单证券窄字段请求",
        }
    payload["content_sha256"] = _canonical_hash(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="正泰电器 Run15 单证券窄字段 Wind/Tushare 财务快照"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--include-consensus",
        action="store_true",
        help="仅在独立模型冻结后读取 FY1-FY3 一致预期",
    )
    parser.add_argument(
        "--wind-only",
        action="store_true",
        help="本次不触发Tushare，仅采集Wind单证券窄字段快照",
    )
    args = parser.parse_args()
    payload = collect(
        include_consensus=args.include_consensus,
        include_tushare=not args.wind_only,
    )
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
                "consensus_included": args.include_consensus,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
