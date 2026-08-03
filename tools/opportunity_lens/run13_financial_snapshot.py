from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, timezone
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


SECURITIES = {
    "innolight": {"ts_code": "300308.SZ", "name": "中际旭创"},
    "eoptolink": {"ts_code": "300502.SZ", "name": "新易盛"},
    "luxshare": {"ts_code": "002475.SZ", "name": "立讯精密"},
    "byd": {"ts_code": "002594.SZ", "name": "比亚迪"},
}

CONSENSUS_FIELDS = (
    "west_sales_fy1", "west_sales_fy2", "west_sales_fy3",
    "west_netprofit_fy1", "west_netprofit_fy2", "west_netprofit_fy3",
    "west_eps_fy1", "west_eps_fy2", "west_eps_fy3",
    "west_avgroe_fy1", "west_avgroe_fy2", "west_avgroe_fy3",
)
HISTORICAL_FIELDS = (
    "oper_rev", "np_belongto_parcomsh", "net_cash_flows_oper_act",
    "cash_pay_acq_const_fiolta", "tot_assets", "tot_equity",
    "roe", "roa2", "grossprofitmargin", "netprofitmargin",
)


def _frame_rows(frame: Any) -> dict[str, dict[str, float | None]]:
    if frame is None or getattr(frame, "empty", True):
        return {}
    clean = frame.where(frame.notna(), None)
    return {
        str(index): {
            str(column).lower(): (
                float(value.item() if hasattr(value, "item") else value)
                if value is not None
                else None
            )
            for column, value in row.items()
        }
        for index, row in clean.iterrows()
    }


def _canonical_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _wind_snapshot(ts_code: str) -> dict[str, Any]:
    """Run a single-security, narrow-field Wind snapshot."""
    try:
        return {
            "status": "ok",
            "snapshot": fetch_current_market_financial_snapshot(
                ts_code,
                trade_date="2026-07-22",
            ),
        }
    except WindHttpUnavailable as exc:
        return {
            "status": "unavailable_fallback_to_tushare",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def _wind_matrix(fields: tuple[str, ...], options: str) -> dict[str, Any]:
    assert_wind_request_scope(
        security_count=len(SECURITIES),
        field_count=len(fields),
        estimated_observations=len(SECURITIES) * len(fields),
    )
    client = load_wind_http_client()
    tickers = ",".join(spec["ts_code"] for spec in SECURITIES.values())
    result = client.wss(tickers, ",".join(fields), options)
    error_code = int(getattr(result, "ErrorCode", -1))
    if error_code != 0:
        raise WindHttpUnavailable(f"Wind wss 失败：ErrorCode={error_code}")
    return {
        "status": "ok",
        "fields": list(fields),
        "options_without_endpoint": options,
        "rows": _frame_rows(getattr(result, "dfData", None)),
    }


def collect() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "snapshot_version": "run13.financial_snapshot.v4",
        "accessed_at_utc": datetime.now(timezone.utc).isoformat(),
        "accessed_at_china_date": date.today().isoformat(),
        "scope_note": "仅查询中际旭创、新易盛、立讯精密和比亚迪四只A股；当前估值为单证券窄字段，2025年财务和FY1—FY3一致预期各为四证券窄字段矩阵，合计远低于Wind小型取数门禁。Tushare只保留为逐字段补缺和公告期复核，没有全市场或长历史请求。",
        "wind_request_audit": {
            "security_count": 4,
            "current_fields_per_security": 12,
            "historical_fields": len(HISTORICAL_FIELDS),
            "consensus_fields": len(CONSENSUS_FIELDS),
            "estimated_observations": 4 * (12 + len(HISTORICAL_FIELDS) + len(CONSENSUS_FIELDS)),
            "large_request_permission_required": False,
        },
        "securities": {},
    }
    payload["wind_historical_fy2025"] = _wind_matrix(
        HISTORICAL_FIELDS,
        "rptDate=20251231;rptType=1;unit=1",
    )
    payload["wind_consensus_fy1_fy3"] = _wind_matrix(
        CONSENSUS_FIELDS,
        "tradeDate=20260722;unit=1",
    )
    for key, spec in SECURITIES.items():
        payload["securities"][key] = {
            "identity": spec,
            "wind": _wind_snapshot(spec["ts_code"]),
            "tushare": {
                "daily_basic_latest": fetch_daily_basic_latest(spec["ts_code"]),
                "income_2023_2026": fetch_income_rows(spec["ts_code"], years=("2023", "2024", "2025", "2026")),
                "fina_indicator_2023_2026": fetch_fina_indicator_rows(spec["ts_code"], years=("2023", "2024", "2025", "2026")),
                "cashflow_2023_2026": fetch_cashflow_rows(spec["ts_code"], years=("2023", "2024", "2025", "2026")),
                "balancesheet_2023_2026": fetch_balancesheet_rows(spec["ts_code"], years=("2023", "2024", "2025", "2026")),
            },
        }
    payload["content_sha256"] = _canonical_hash(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = collect()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "sha256": payload["content_sha256"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
