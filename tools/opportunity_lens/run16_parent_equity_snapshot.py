from __future__ import annotations

"""Collect a narrow parent-company equity fallback for Run16.

The collector requests one A-share security at a time and keeps only
``balancesheet.total_hldr_eqy_exc_min_int`` plus identity/audit fields.  It
does not write any live database and never prints credentials.
"""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.pipeline.tushare_provider import fetch_balancesheet_rows


def _sha256(payload: Any) -> str:
    raw = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _latest_annual_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        period = str(row.get("end_date") or "")
        if len(period) != 8 or not period.endswith(("1231", "0331")):
            continue
        value = row.get("total_hldr_eqy_exc_min_int")
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if value <= 0:
            continue
        current = result.get(period)
        order = (str(row.get("f_ann_date") or ""), str(row.get("ann_date") or ""), str(row.get("update_flag") or ""))
        current_order = (
            str(current.get("f_ann_date") or ""),
            str(current.get("ann_date") or ""),
            str(current.get("update_flag") or ""),
        ) if current else ("", "", "")
        if current is None or order >= current_order:
            result[period] = {
                "ts_code": row.get("ts_code"),
                "ann_date": row.get("ann_date"),
                "f_ann_date": row.get("f_ann_date"),
                "end_date": period,
                "report_type": row.get("report_type"),
                "comp_type": row.get("comp_type"),
                "total_hldr_eqy_exc_min_int": value,
                "update_flag": row.get("update_flag"),
            }
    return result


def build(tickers: list[str]) -> dict[str, Any]:
    by_ticker: dict[str, Any] = {}
    requests: list[dict[str, Any]] = []
    for ticker in tickers:
        ticker = ticker.strip().upper()
        rows = fetch_balancesheet_rows(ticker, years=("2021", "2022", "2023", "2024", "2025", "2026"))
        selected = _latest_annual_rows(rows)
        if "20251231" not in selected:
            raise RuntimeError(f"{ticker} 缺少 FY2025 归母权益")
        by_ticker[ticker] = selected
        requests.append(
            {
                "ticker": ticker,
                "api_name": "balancesheet",
                "raw_feature_name": "total_hldr_eqy_exc_min_int",
                "requested_years": [2021, 2022, 2023, 2024, 2025, 2026],
                "returned_rows": len(rows),
                "selected_periods": sorted(selected),
            }
        )
    payload: dict[str, Any] = {
        "artifact_version": "run16.parent_equity_tushare.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider": "Tushare",
        "fallback_policy": "Wind未提供可与归母净利润一致配对的归母权益时，仅按字段使用Tushare补缺；不覆盖其他Wind非空值。",
        "by_ticker": by_ticker,
        "request_audit": requests,
    }
    payload["content_sha256"] = _sha256(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = build(args.ticker)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "security_count": len(payload["by_ticker"]),
                "content_sha256": payload["content_sha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
