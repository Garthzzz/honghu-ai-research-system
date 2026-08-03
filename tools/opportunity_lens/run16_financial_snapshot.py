from __future__ import annotations

"""Collect bounded Wind artifacts for the AI application/full-chain run.

The command deliberately separates two stages:

``actual``
    Current market fields, FY2021-FY2025 actuals, 2025Q1/2026Q1 actuals and
    one year of forward-adjusted daily closes.  No consensus field is read.

``consensus``
    FY1-FY3 Wind consensus.  This stage refuses to run unless a frozen
    independent-model artifact is supplied, so the research workflow cannot
    accidentally read the benchmark before freezing its own forecast.

Both stages only write JSON artifacts.  Import into ``financial.db`` remains a
separate validated operation through ``tools.financial.opportunity_profile_export``.
"""

import argparse
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from tools.pipeline.wind_http_provider import (
    WindHttpUnavailable,
    assert_wind_request_scope,
    latest_completed_trade_date,
    load_wind_http_client,
)


ROOT = Path(__file__).resolve().parents[2]
SHANGHAI = timezone(timedelta(hours=8))

CURRENT_FIELDS = (
    "close",
    "pe_ttm",
    "pe_est_ftm",
    "pb_lf",
    "ps_ttm",
    "mkt_cap_ard",
    "free_float_shares",
    "roe_ttm",
    "roa2_ttm",
    "eps_ttm",
    "bps_new",
    "ev2_to_ebitda",
    "peg",
)

ACTUAL_FIELDS = (
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


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _load_universe(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw.get("securities") if isinstance(raw, dict) else raw
    if not isinstance(rows, list) or not rows:
        raise ValueError("证券配置必须是非空 securities 数组")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"第 {index} 个证券配置不是对象")
        ticker = str(row.get("ticker") or "").strip().upper()
        name = str(row.get("name") or "").strip()
        key = str(row.get("key") or ticker).strip()
        if not ticker.endswith((".SH", ".SZ", ".BJ")) or not name or not key:
            raise ValueError(f"第 {index} 个证券缺少有效 key/name/A股 ticker")
        if ticker in seen:
            raise ValueError(f"证券配置重复: {ticker}")
        seen.add(ticker)
        result.append({**row, "ticker": ticker, "name": name, "key": key})
    if len(result) > 10:
        raise PermissionError(
            "本工具的未授权硬上限为10只证券；超过时必须先取得用户对证券、字段、"
            "日期区间和预计观测量的明确许可，并使用专门的大请求工具。"
        )
    return result


def _frame_rows(frame: Any) -> dict[str, dict[str, float | None]]:
    if frame is None or getattr(frame, "empty", True):
        return {}
    result: dict[str, dict[str, float | None]] = {}
    for index, row in frame.iterrows():
        result[str(index).upper()] = {
            str(column).upper(): _finite(value) for column, value in row.items()
        }
    return result


def _wss_rows(
    client: Any,
    securities: Iterable[dict[str, Any]],
    fields: tuple[str, ...],
    options: str,
) -> dict[str, dict[str, float | None]]:
    security_rows = list(securities)
    assert_wind_request_scope(
        security_count=len(security_rows),
        field_count=len(fields),
        estimated_observations=len(security_rows) * len(fields),
    )
    response = client.wss(
        ",".join(row["ticker"] for row in security_rows),
        ",".join(fields),
        options,
    )
    error_code = int(getattr(response, "ErrorCode", -1))
    if error_code != 0:
        raise WindHttpUnavailable(
            f"Wind WSS failed: ErrorCode={error_code}, options={options}"
        )
    rows = _frame_rows(getattr(response, "dfData", None))
    missing = [row["ticker"] for row in security_rows if row["ticker"] not in rows]
    if missing:
        raise WindHttpUnavailable(f"Wind WSS 返回缺少证券行: {missing}")
    return rows


def _price_history(
    client: Any,
    securities: list[dict[str, Any]],
    start_date: str,
    end_date: str,
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for security in securities:
        response = client.wsd(
            security["ticker"], "close", start_date, end_date, "PriceAdj=F"
        )
        error_code = int(getattr(response, "ErrorCode", -1))
        if error_code != 0:
            raise WindHttpUnavailable(
                f"Wind WSD failed: ticker={security['ticker']}, ErrorCode={error_code}"
            )
        frame = getattr(response, "dfData", None)
        if frame is None or getattr(frame, "empty", True):
            raise WindHttpUnavailable(
                f"Wind WSD returned empty history: {security['ticker']}"
            )
        rows: list[dict[str, Any]] = []
        for index, row in frame.iterrows():
            close = _finite(row.get("CLOSE"))
            if close is None:
                continue
            as_of = getattr(index, "date", lambda: index)()
            rows.append({"date": str(as_of), "close_forward_adjusted": close})
        result[security["ticker"]] = rows
    return result


def collect_actual(universe_path: Path) -> dict[str, Any]:
    securities = _load_universe(universe_path)
    client = load_wind_http_client()
    trade_date = latest_completed_trade_date(client=client)
    end = datetime.fromisoformat(trade_date).date()
    start = end - timedelta(days=370)
    report_dates = [
        *(f"{year}1231" for year in range(2021, 2026)),
        "20250331",
        "20260331",
    ]
    expected_price_observations = len(securities) * 250
    total_estimate = (
        len(securities) * len(CURRENT_FIELDS)
        + len(securities) * len(ACTUAL_FIELDS) * len(report_dates)
        + expected_price_observations
    )
    if total_estimate > 5_000:
        raise PermissionError(
            f"预计观测量 {total_estimate} 超过未授权单任务安全范围，必须先取得用户许可"
        )
    current = _wss_rows(
        client,
        securities,
        CURRENT_FIELDS,
        f"tradeDate={trade_date.replace('-', '')};unit=1",
    )
    reported: dict[str, dict[str, dict[str, float | None]]] = {}
    for report_date in report_dates:
        reported[report_date] = _wss_rows(
            client,
            securities,
            ACTUAL_FIELDS,
            f"rptDate={report_date};rptType=1;unit=1",
        )
    prices = _price_history(
        client, securities, start.isoformat(), end.isoformat()
    )
    for security in securities:
        row = current[security["ticker"]]
        close = _finite(row.get("CLOSE"))
        free_float_shares = _finite(row.get("FREE_FLOAT_SHARES"))
        row["FREE_FLOAT_MARKET_CAP_CNY_100M"] = (
            close * free_float_shares / 1e8
            if close is not None and free_float_shares is not None
            else None
        )
    payload: dict[str, Any] = {
        "snapshot_version": "run16.ai_actual_market_history.v1",
        "stage": "actual_before_consensus",
        "accessed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "trade_date": trade_date,
        "universe": securities,
        "request_audit": {
            "security_count": len(securities),
            "current_fields": list(CURRENT_FIELDS),
            "actual_fields": list(ACTUAL_FIELDS),
            "report_dates": report_dates,
            "price_date_range": [start.isoformat(), end.isoformat()],
            "price_adjustment": "Wind PriceAdj=F",
            "estimated_observations": total_estimate,
            "large_request_permission_required": False,
            "purpose": "AI应用与全产业链核心候选的独立财务建模、自由流通市值权重和相关性辅助分析",
            "consensus_fields_read": [],
        },
        "wind": {
            "current": current,
            "reported": reported,
            "price_history": prices,
        },
    }
    payload["content_sha256"] = _sha256(payload)
    return payload


def collect_consensus(universe_path: Path, freeze_artifact: Path) -> dict[str, Any]:
    securities = _load_universe(universe_path)
    if not freeze_artifact.is_file():
        raise FileNotFoundError(f"独立模型冻结文件不存在: {freeze_artifact}")
    freeze_payload = json.loads(freeze_artifact.read_text(encoding="utf-8"))
    if not freeze_payload.get("independent_before_consensus"):
        raise ValueError("独立模型冻结文件未声明 independent_before_consensus=true")
    freeze_hash = _file_sha256(freeze_artifact)
    client = load_wind_http_client()
    trade_date = latest_completed_trade_date(client=client)
    rows = _wss_rows(
        client,
        securities,
        CONSENSUS_FIELDS,
        f"tradeDate={trade_date.replace('-', '')};unit=1",
    )
    payload: dict[str, Any] = {
        "snapshot_version": "run16.ai_external_consensus.v1",
        "stage": "external_reconciliation_after_independent_freeze",
        "accessed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "trade_date": trade_date,
        "universe": securities,
        "independent_freeze": {
            "path": str(freeze_artifact.resolve().relative_to(ROOT)).replace("\\", "/"),
            "sha256": freeze_hash,
            "declared_output_hash": freeze_payload.get("output_hash"),
        },
        "request_audit": {
            "security_count": len(securities),
            "fields": list(CONSENSUS_FIELDS),
            "estimated_observations": len(securities) * len(CONSENSUS_FIELDS),
            "large_request_permission_required": False,
            "purpose": "独立FY1-FY3预测冻结后的Wind一致预期对账",
        },
        "wind": {"consensus": rows},
    }
    payload["content_sha256"] = _sha256(payload)
    return payload


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="stage", required=True)
    actual = sub.add_parser("actual")
    actual.add_argument("--universe", type=Path, required=True)
    actual.add_argument("--output", type=Path, required=True)
    consensus = sub.add_parser("consensus")
    consensus.add_argument("--universe", type=Path, required=True)
    consensus.add_argument("--freeze-artifact", type=Path, required=True)
    consensus.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.stage == "actual":
        payload = collect_actual(args.universe.resolve())
    else:
        payload = collect_consensus(
            args.universe.resolve(), args.freeze_artifact.resolve()
        )
    _write(args.output.resolve(), payload)
    print(
        json.dumps(
            {
                "stage": payload["stage"],
                "output": str(args.output.resolve()),
                "sha256": payload["content_sha256"],
                "securities": len(payload["universe"]),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
