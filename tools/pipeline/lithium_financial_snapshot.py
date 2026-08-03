from __future__ import annotations

"""Collect a bounded Wind-first financial snapshot for the lithium research.

The collector writes one immutable JSON artifact and never writes a database.
Wind is the primary source for A-share market, historical and consensus data.
Tushare is collected alongside it for field-level gaps, filing revision audit
and institution-level forecasts from the most recent six months.
"""

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from tools.pipeline.tushare_provider import call_tushare
from tools.pipeline.wind_http_provider import (
    WindHttpUnavailable,
    assert_wind_request_scope,
    fetch_current_market_financial_snapshot,
    load_wind_http_client,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "cache" / "lithium_research" / "lithium_financial_snapshot.json"
TRADE_DATE = "2026-07-24"
FETCHED_AT_DATE = "2026-07-27"
YEARS = (2021, 2022, 2023, 2024, 2025)
TICKERS = (
    "002460.SZ",
    "002192.SZ",
    "002240.SZ",
    "000792.SZ",
    "001203.SZ",
    "002497.SZ",
    "300390.SZ",
    "002466.SZ",
    "603399.SH",
    "002738.SZ",
    "000408.SZ",
    "600773.SH",
    "002756.SZ",
)
BATCHES = (TICKERS[:7], TICKERS[7:])

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
TUSHARE_REPORT_FIELDS = (
    "ts_code,report_date,report_title,report_type,classify,org_name,author_name,"
    "quarter,op_rt,op_pr,tp,np,eps,pe,roe,ev_ebitda,rating,max_price,min_price,"
    "create_time"
)


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    ).encode("utf-8")


def _hash(payload: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(payload)).hexdigest()


def _frame_rows(frame: Any) -> dict[str, dict[str, float | None]]:
    if frame is None or getattr(frame, "empty", True):
        return {}
    clean = frame.where(frame.notna(), None)
    result: dict[str, dict[str, float | None]] = {}
    for index, row in clean.iterrows():
        result[str(index).upper()] = {
            str(column).lower(): _finite(
                value.item() if hasattr(value, "item") else value
            )
            for column, value in row.items()
        }
    return result


def _wind_wss(
    client: Any,
    tickers: Iterable[str],
    fields: tuple[str, ...],
    options: str,
) -> dict[str, Any]:
    securities = tuple(tickers)
    assert_wind_request_scope(
        security_count=len(securities),
        field_count=len(fields),
        estimated_observations=len(securities) * len(fields),
    )
    response = client.wss(",".join(securities), ",".join(fields), options)
    error_code = int(getattr(response, "ErrorCode", -1))
    if error_code != 0:
        raise WindHttpUnavailable(
            f"Wind WSS failed: ErrorCode={error_code}; options={options}"
        )
    rows = _frame_rows(getattr(response, "dfData", None))
    if not rows:
        raise WindHttpUnavailable(f"Wind WSS returned no rows: {options}")
    return {
        "tickers": list(securities),
        "fields": list(fields),
        "options": options,
        "rows": rows,
    }


def _collect_wind() -> dict[str, Any]:
    client = load_wind_http_client()
    current: dict[str, Any] = {}
    for ticker in TICKERS:
        current[ticker] = fetch_current_market_financial_snapshot(
            ticker,
            trade_date=TRADE_DATE,
            client=client,
        )
    annual: dict[str, list[dict[str, Any]]] = {}
    for year in YEARS:
        annual[str(year)] = [
            _wind_wss(
                client,
                batch,
                HISTORICAL_FIELDS,
                f"rptDate={year}1231;rptType=1;unit=1",
            )
            for batch in BATCHES
        ]
    q1_2026 = [
        _wind_wss(
            client,
            batch,
            HISTORICAL_FIELDS,
            "rptDate=20260331;rptType=1;unit=1",
        )
        for batch in BATCHES
    ]
    consensus = [
        _wind_wss(
            client,
            batch,
            CONSENSUS_FIELDS,
            f"tradeDate={TRADE_DATE.replace('-', '')};unit=1",
        )
        for batch in BATCHES
    ]
    return {
        "status": "ok",
        "trade_date": TRADE_DATE,
        "current": current,
        "annual": annual,
        "q1_2026": q1_2026,
        "consensus_fy1_fy3": consensus,
    }


def _tushare_rows(api_name: str, ticker: str, fields: str) -> list[dict[str, Any]]:
    return call_tushare(api_name, {"ts_code": ticker}, fields, timeout=45)


def _current_report_rows(ticker: str) -> list[dict[str, Any]]:
    rows = call_tushare(
        "report_rc",
        {
            "ts_code": ticker,
            "start_date": "20260127",
            "end_date": FETCHED_AT_DATE.replace("-", ""),
        },
        TUSHARE_REPORT_FIELDS,
        timeout=45,
    )
    return sorted(
        rows,
        key=lambda row: (
            str(row.get("report_date") or ""),
            str(row.get("org_name") or ""),
            str(row.get("quarter") or ""),
        ),
        reverse=True,
    )


def _collect_tushare() -> dict[str, Any]:
    result: dict[str, Any] = {}
    for ticker in TICKERS:
        result[ticker] = {
            "daily_basic": _tushare_rows(
                "daily_basic",
                ticker,
                "ts_code,trade_date,close,pe,pe_ttm,pb,ps_ttm,dv_ttm,"
                "total_share,float_share,total_mv,circ_mv",
            )[:1],
            "income_2021_2026": _tushare_rows(
                "income",
                ticker,
                "ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,"
                "total_revenue,revenue,operate_profit,total_profit,n_income,"
                "n_income_attr_p,rd_exp,update_flag",
            ),
            "balancesheet_2021_2026": _tushare_rows(
                "balancesheet",
                ticker,
                "ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,"
                "total_assets,total_liab,total_hldr_eqy_exc_min_int,"
                "accounts_receiv,inventories,fix_assets,cip,contract_liab,"
                "update_flag",
            ),
            "cashflow_2021_2026": _tushare_rows(
                "cashflow",
                ticker,
                "ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,"
                "n_cashflow_act,c_pay_acq_const_fiolta,update_flag",
            ),
            "fina_indicator_2021_2026": _tushare_rows(
                "fina_indicator",
                ticker,
                "ts_code,ann_date,end_date,eps,bps,grossprofit_margin,"
                "netprofit_margin,roe,roa,rd_exp_to_operting_revenue,update_flag",
            ),
            "institution_forecasts_recent_six_months": _current_report_rows(ticker),
        }
        for key in (
            "income_2021_2026",
            "balancesheet_2021_2026",
            "cashflow_2021_2026",
            "fina_indicator_2021_2026",
        ):
            result[ticker][key] = [
                row
                for row in result[ticker][key]
                if str(row.get("end_date") or "")[:4]
                in {"2021", "2022", "2023", "2024", "2025", "2026"}
            ]
    return {
        "status": "ok",
        "forecast_window": "2026-01-27 to 2026-07-27",
        "securities": result,
    }


def collect() -> dict[str, Any]:
    estimated_wind_observations = len(TICKERS) * (
        12 + len(HISTORICAL_FIELDS) * (len(YEARS) + 1) + len(CONSENSUS_FIELDS)
    )
    payload: dict[str, Any] = {
        "snapshot_version": "lithium_b_20260727.financial_snapshot.v1",
        "research_run_ref": "lithium_b_20260727",
        "accessed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope_audit": {
            "wind_security_count": len(TICKERS),
            "wind_tickers": list(TICKERS),
            "wind_request_batch_sizes": [len(batch) for batch in BATCHES],
            "wind_max_fields_per_request": max(
                12, len(HISTORICAL_FIELDS), len(CONSENSUS_FIELDS)
            ),
            "wind_estimated_observations": estimated_wind_observations,
            "large_request_permission_required": False,
            "purpose": (
                "锂与碳酸锂两套行业研究的13家重点公司历史财务、当前估值、"
                "FY1—FY3一致预期与独立模型对账"
            ),
        },
    }
    try:
        payload["wind"] = _collect_wind()
    except WindHttpUnavailable as exc:
        payload["wind"] = {
            "status": "unavailable",
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:240],
        }
    try:
        payload["tushare"] = _collect_tushare()
    except Exception as exc:  # noqa: BLE001 - external provider audit artifact
        payload["tushare"] = {
            "status": "unavailable",
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:240],
        }
    payload["content_sha256"] = _hash(payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    payload = collect()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "content_sha256": payload["content_sha256"],
                "wind_status": payload["wind"]["status"],
                "tushare_status": payload["tushare"]["status"],
                "estimated_wind_observations": payload["scope_audit"][
                    "wind_estimated_observations"
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
