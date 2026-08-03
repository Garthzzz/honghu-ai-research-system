from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.pipeline.wind_http_provider import (
    WindHttpUnavailable,
    assert_wind_request_scope,
    load_wind_http_client,
)


SECURITIES = {
    "innolight": {"ticker": "300308.SZ", "name": "中际旭创"},
    "eoptolink": {"ticker": "300502.SZ", "name": "新易盛"},
    "luxshare": {"ticker": "002475.SZ", "name": "立讯精密"},
    "byd": {"ticker": "002594.SZ", "name": "比亚迪"},
}

ANNUAL_FIELDS = (
    "oper_rev",
    "np_belongto_parcomsh",
    "net_cash_flows_oper_act",
    "cash_pay_acq_const_fiolta",
    "tot_assets",
    "tot_equity",
    "roe",
    "roa2",
    "grossprofitmargin",
    "netprofitmargin",
)
REPORT_DATES = tuple(f"{year}1231" for year in range(2021, 2026))
PB_START = "2021-01-01"
PB_END = "2026-07-22"


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _canonical_hash(payload: Any) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _frame_records(frame: Any) -> list[dict[str, Any]]:
    if frame is None or getattr(frame, "empty", True):
        return []
    records: list[dict[str, Any]] = []
    for index, row in frame.iterrows():
        record: dict[str, Any] = {"index": str(index)}
        for column, value in row.items():
            clean = value.item() if hasattr(value, "item") else value
            record[str(column).lower()] = _finite(clean)
        records.append(record)
    return records


def _request_or_raise(
    client: Any,
    method: str,
    *args: str,
) -> Any:
    result = getattr(client, method)(*args)
    error_code = int(getattr(result, "ErrorCode", -1))
    if error_code != 0:
        raise WindHttpUnavailable(
            f"Wind {method} 失败：ErrorCode={error_code}"
        )
    return result


def collect() -> dict[str, Any]:
    security_count = len(SECURITIES)
    estimated_annual = security_count * len(ANNUAL_FIELDS) * len(REPORT_DATES)
    estimated_pb = security_count * 68
    assert_wind_request_scope(
        security_count=security_count,
        field_count=len(ANNUAL_FIELDS),
        estimated_observations=estimated_annual,
    )
    assert_wind_request_scope(
        security_count=security_count,
        field_count=1,
        estimated_observations=estimated_pb,
    )

    client = load_wind_http_client()
    tickers = ",".join(spec["ticker"] for spec in SECURITIES.values())
    annual: dict[str, Any] = {}
    for report_date in REPORT_DATES:
        result = _request_or_raise(
            client,
            "wss",
            tickers,
            ",".join(ANNUAL_FIELDS),
            f"rptDate={report_date};rptType=1;unit=1",
        )
        annual[report_date] = {
            "raw_feature_names": list(ANNUAL_FIELDS),
            "records": _frame_records(getattr(result, "dfData", None)),
        }

    monthly_pb: dict[str, Any] = {}
    for key, spec in SECURITIES.items():
        result = _request_or_raise(
            client,
            "wsd",
            spec["ticker"],
            "pb_lf",
            PB_START,
            PB_END,
            "Period=M",
        )
        monthly_pb[key] = {
            "ticker": spec["ticker"],
            "name": spec["name"],
            "raw_feature_name": "pb_lf",
            "frequency": "monthly",
            "records": _frame_records(getattr(result, "dfData", None)),
        }

    payload: dict[str, Any] = {
        "snapshot_version": "run13.pb_return_history.v1",
        "accessed_at_utc": datetime.now(timezone.utc).isoformat(),
        "provider": "Wind内网HTTP代理",
        "request_scope": {
            "securities": [spec["ticker"] for spec in SECURITIES.values()],
            "annual_fields": list(ANNUAL_FIELDS),
            "annual_report_dates": list(REPORT_DATES),
            "pb_field": "pb_lf",
            "pb_date_range": [PB_START, PB_END],
            "pb_frequency": "monthly",
            "estimated_observations": estimated_annual + estimated_pb,
            "large_request_permission_required": False,
        },
        "annual": annual,
        "monthly_pb": monthly_pb,
        "interpretation_boundary": (
            "年度财务值来自指定报告期的Wind截面；月度PB用于形成历史估值带。"
            "PB与ROE/ROA配对时仍须使用财务披露日或其后首个可得PB，不能把年末"
            "尚未公开的年度指标与年末股价直接配对。"
        ),
    }
    payload["content_sha256"] = _canonical_hash(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="受控提取Run13四家公司五年财务和月度PB历史"
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
                "estimated_observations": payload["request_scope"][
                    "estimated_observations"
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
