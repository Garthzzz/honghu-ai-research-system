from __future__ import annotations

"""Collect a bounded Wind financial snapshot for the HDI B-track research run.

This collector deliberately writes JSON artifacts only.  Import into
``financial.db`` is a separate, validated step through
``tools.financial.opportunity_profile_export``.
"""

import argparse
import hashlib
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.financial.accounting_sanity import (
    normalize_nonmeaningful_annual_roe,
)
from tools.pipeline.wind_http_provider import (
    WindHttpUnavailable,
    assert_wind_request_scope,
    load_wind_http_client,
)


ROOT = Path(__file__).resolve().parents[2]
RESEARCH_DB = ROOT / "data" / "research.db"
DEFAULT_OUTPUT = ROOT / "cache" / "hdi_research" / "wind_actual_snapshot.json"
DEFAULT_EXPORT = (
    ROOT / "cache" / "hdi_research" / "financial_actual_profile_export.json"
)
TRADE_DATE = "2026-07-24"
YEARS = tuple(range(2021, 2026))

TICKERS = (
    "300476.SZ",  # 胜宏科技
    "002938.SZ",  # 鹏鼎控股
    "603228.SH",  # 景旺电子
    "002463.SZ",  # 沪电股份
    "002916.SZ",  # 深南电路
    "600601.SH",  # 方正科技
    "002815.SZ",  # 崇达技术
    "688183.SH",  # 生益电子
    "002913.SZ",  # 奥士康
    "603936.SH",  # 博敏电子
    "001389.SZ",  # 广合科技
    "603459.SH",  # 红板科技
    "002384.SZ",  # 东山精密
    "603920.SH",  # 世运电路
)

CURRENT_FIELDS = (
    "close",
    "pe_ttm",
    "pe_est_ftm",
    "pb_lf",
    "ps_ttm",
    "mkt_cap_ard",
    "roe_ttm",
    "roa2_ttm",
    "eps_ttm",
    "bps_new",
    "ev2_to_ebitda",
    "peg",
)

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

CURRENT_SPECS = {
    "CLOSE": ("close", "元/股", "CNY"),
    "PE_TTM": ("pe_ttm", "倍", None),
    "PE_EST_FTM": ("pe_forward", "倍", None),
    "PB_LF": ("pb", "倍", None),
    "PS_TTM": ("ps_ttm", "倍", None),
    "MKT_CAP_ARD": ("market_cap_cny", "亿元人民币", "CNY"),
    "ROE_TTM": ("roe", "%", None),
    "ROA2_TTM": ("roa", "%", None),
    "EPS_TTM": ("eps_ttm", "元/股", "CNY"),
    "BPS_NEW": ("bps_mrq", "元/股", "CNY"),
    "EV2_TO_EBITDA": ("ev_ebitda", "倍", None),
    "PEG": ("peg", "倍", None),
}

HISTORICAL_SPECS = {
    "OPER_REV": ("revenue", "亿元人民币", "CNY", 1e8),
    "NP_BELONGTO_PARCOMSH": ("net_profit_parent", "亿元人民币", "CNY", 1e8),
    "NET_CASH_FLOWS_OPER_ACT": (
        "operating_cash_flow",
        "亿元人民币",
        "CNY",
        1e8,
    ),
    "CASH_PAY_ACQ_CONST_FIOLTA": ("capex_cash_paid", "亿元人民币", "CNY", 1e8),
    "TOT_ASSETS": ("total_assets", "亿元人民币", "CNY", 1e8),
    "TOT_EQUITY": ("total_equity", "亿元人民币", "CNY", 1e8),
    "TOT_LIAB": ("total_liabilities", "亿元人民币", "CNY", 1e8),
    "ROE": ("roe", "%", None, 1.0),
    "ROA2": ("roa", "%", None, 1.0),
    "GROSSPROFITMARGIN": ("gross_margin", "%", None, 1.0),
    "NETPROFITMARGIN": ("net_margin", "%", None, 1.0),
}


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


def _company_identity() -> dict[str, dict[str, Any]]:
    conn = sqlite3.connect(RESEARCH_DB)
    conn.row_factory = sqlite3.Row
    try:
        placeholders = ",".join("?" for _ in TICKERS)
        rows = conn.execute(
            f"""SELECT id,name,ticker,market,listing_status
                  FROM company
                 WHERE upper(ticker) IN ({placeholders})""",
            tuple(code.upper() for code in TICKERS),
        ).fetchall()
    finally:
        conn.close()
    result = {str(row["ticker"]).upper(): dict(row) for row in rows}
    missing = [ticker for ticker in TICKERS if ticker not in result]
    if missing:
        raise ValueError(f"HDI Wind公司身份尚未核验完整: {missing}")
    return result


def _wss_rows(
    client: Any,
    *,
    fields: tuple[str, ...],
    options: str,
    estimated_observations: int,
) -> dict[str, dict[str, float | None]]:
    assert_wind_request_scope(
        security_count=len(TICKERS),
        field_count=len(fields),
        estimated_observations=estimated_observations,
        large_request_approved=True,
    )
    response = client.wss(",".join(TICKERS), ",".join(fields), options)
    error_code = int(getattr(response, "ErrorCode", -1))
    if error_code != 0:
        raise WindHttpUnavailable(
            f"HDI Wind WSS failed: ErrorCode={error_code}, options={options}"
        )
    frame = getattr(response, "dfData", None)
    if frame is None or getattr(frame, "empty", True):
        raise WindHttpUnavailable(f"HDI Wind WSS returned an empty frame: {options}")
    result: dict[str, dict[str, float | None]] = {}
    for ticker, row in frame.iterrows():
        result[str(ticker).upper()] = {
            str(column).upper(): _finite(value) for column, value in row.items()
        }
    return result


def collect() -> dict[str, Any]:
    identities = _company_identity()
    client = load_wind_http_client()
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    current = _wss_rows(
        client,
        fields=CURRENT_FIELDS,
        options=f"tradeDate={TRADE_DATE.replace('-', '')};unit=1",
        estimated_observations=len(TICKERS) * len(CURRENT_FIELDS),
    )
    annual: dict[str, dict[str, dict[str, float | None]]] = {}
    for year in YEARS:
        annual[str(year)] = _wss_rows(
            client,
            fields=HISTORICAL_FIELDS,
            options=f"rptDate={year}1231;rptType=1;unit=1",
            estimated_observations=len(TICKERS) * len(HISTORICAL_FIELDS),
        )
    payload: dict[str, Any] = {
        "snapshot_version": "hdi_b_20260726.wind_actual.v1",
        "research_run_ref": "hdi_b_20260726",
        "accessed_at_utc": fetched_at,
        "scope_audit": {
            "permission": "user explicitly approved oversized Wind access for the HDI task",
            "security_count": len(TICKERS),
            "tickers": list(TICKERS),
            "current_field_count": len(CURRENT_FIELDS),
            "annual_field_count": len(HISTORICAL_FIELDS),
            "annual_years": list(YEARS),
            "estimated_observations": (
                len(TICKERS) * len(CURRENT_FIELDS)
                + len(TICKERS) * len(HISTORICAL_FIELDS) * len(YEARS)
            ),
            "purpose": "HDI重点A股公司的历史财务、回报率、现金流和当前估值",
            "full_market_request": False,
        },
        "companies": identities,
        "wind": {
            "trade_date": TRADE_DATE,
            "current_fields": list(CURRENT_FIELDS),
            "historical_fields": list(HISTORICAL_FIELDS),
            "current": current,
            "annual": annual,
        },
    }
    payload["content_sha256"] = _sha256(payload)
    return payload


def _source_snapshot(
    *,
    key: str,
    ticker: str,
    company_name: str,
    source_ref: str,
    title: str,
    as_of_date: str,
    content_hash: str,
    raw_snapshot_path: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "key": key,
        "provider": "wind",
        "source_channel": "structured_api",
        "source_ref": source_ref,
        "title": title,
        "publisher": "Wind",
        "as_of_date": as_of_date,
        "content_hash": content_hash,
        "raw_snapshot_path": raw_snapshot_path,
        "metadata": {
            "ticker": ticker,
            "company_name": company_name,
            "database_boundary": "financial.db only",
            **metadata,
        },
    }


def build_export(payload: dict[str, Any], *, snapshot_path: Path) -> dict[str, Any]:
    content_hash = str(payload["content_sha256"])
    raw_path = str(snapshot_path.relative_to(ROOT)).replace("\\", "/")
    companies: list[dict[str, Any]] = []
    for ticker in TICKERS:
        identity = payload["companies"][ticker]
        name = str(identity["name"])
        current_key = f"wind_current_{ticker}"
        snapshots = [
            _source_snapshot(
                key=current_key,
                ticker=ticker,
                company_name=name,
                source_ref=(
                    f"wind:WSS:{ticker}:{','.join(CURRENT_FIELDS)}:{TRADE_DATE}"
                ),
                title=f"{name} Wind当前估值与TTM财务快照",
                as_of_date=TRADE_DATE,
                content_hash=content_hash,
                raw_snapshot_path=raw_path,
                metadata={
                    "field_count": len(CURRENT_FIELDS),
                    "frequency": "snapshot",
                    "date_range": [TRADE_DATE, TRADE_DATE],
                },
            )
        ]
        observations: list[dict[str, Any]] = []
        current_row = payload["wind"]["current"].get(ticker, {})
        for raw_field, (metric, unit, currency) in CURRENT_SPECS.items():
            value = _finite(current_row.get(raw_field))
            if value is None:
                continue
            if raw_field == "MKT_CAP_ARD":
                value /= 1e8
            observations.append(
                {
                    "metric_name": metric,
                    "value_num": value,
                    "unit": unit,
                    "currency": currency,
                    "period_end": TRADE_DATE,
                    "frequency": "snapshot",
                    "fact_type": "market",
                    "as_of_date": TRADE_DATE,
                    "provider": "wind",
                    "raw_feature_name": f"Wind WSS.{raw_field.lower()}",
                    "source_snapshot_key": current_key,
                    "quality_status": "usable",
                    "scenario_name": "reported",
                }
            )
        for year in YEARS:
            year_text = str(year)
            period_end = f"{year}-12-31"
            annual_key = f"wind_annual_{ticker}_{year}"
            snapshots.append(
                _source_snapshot(
                    key=annual_key,
                    ticker=ticker,
                    company_name=name,
                    source_ref=(
                        f"wind:WSS:{ticker}:{','.join(HISTORICAL_FIELDS)}:"
                        f"rptDate={year}1231"
                    ),
                    title=f"{name} Wind {year}年年度财务快照",
                    as_of_date=period_end,
                    content_hash=content_hash,
                    raw_snapshot_path=raw_path,
                    metadata={
                        "field_count": len(HISTORICAL_FIELDS),
                        "frequency": "annual",
                        "report_date": period_end,
                        "rpt_type": 1,
                    },
                )
            )
            row = payload["wind"]["annual"][year_text].get(ticker, {})
            for raw_field, (metric, unit, currency, divisor) in (
                HISTORICAL_SPECS.items()
            ):
                value = _finite(row.get(raw_field))
                if value is None:
                    continue
                observations.append(
                    {
                        "metric_name": metric,
                        "value_num": value / divisor,
                        "unit": unit,
                        "currency": currency,
                        "period_start": f"{year}-01-01",
                        "period_end": period_end,
                        "fiscal_year": year,
                        "fiscal_period": "FY",
                        "frequency": "annual",
                        "fact_type": "actual",
                        "as_of_date": period_end,
                        "provider": "wind",
                        "raw_feature_name": f"Wind WSS.{raw_field.lower()}",
                        "source_snapshot_key": annual_key,
                        "quality_status": "usable",
                        "scenario_name": "reported",
                    }
                )
        observations = normalize_nonmeaningful_annual_roe(observations)
        companies.append(
            {
                "research_company_id": int(identity["id"]),
                "security": {
                    "canonical_name": name,
                    "ticker": ticker,
                    "market": str(identity["market"] or "A股"),
                    "listing_status": str(identity["listing_status"] or "a_share"),
                    "reporting_currency": "CNY",
                    "identity_status": "verified",
                },
                "source_snapshots": snapshots,
                "model_runs": [],
                "observations": observations,
            }
        )
    return {
        "export_schema_version": "company_financial_profile_export.v1",
        "research_run_ref": "hdi_b_20260726",
        "as_of_date": TRADE_DATE,
        "source_artifacts": [
            {
                "path": raw_path,
                "sha256": _file_sha256(snapshot_path),
            }
        ],
        "companies": companies,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--export", type=Path, default=DEFAULT_EXPORT)
    parser.add_argument(
        "--reuse-snapshot",
        action="store_true",
        help="只从现有原始快照重建导出包，不调用Wind",
    )
    args = parser.parse_args(argv)
    output = args.output.resolve()
    export_path = args.export.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    export_path.parent.mkdir(parents=True, exist_ok=True)
    if args.reuse_snapshot:
        if not output.is_file():
            raise FileNotFoundError(f"现有Wind原始快照不存在: {output}")
        payload = json.loads(output.read_text(encoding="utf-8"))
    else:
        payload = collect()
        output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
    export_payload = build_export(payload, snapshot_path=output)
    export_path.write_text(
        json.dumps(export_payload, ensure_ascii=False, indent=2, default=str)
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "snapshot": str(output),
                "export": str(export_path),
                "security_count": len(TICKERS),
                "estimated_observations": payload["scope_audit"][
                    "estimated_observations"
                ],
                "non_null_observations": sum(
                    len(company["observations"])
                    for company in export_payload["companies"]
                ),
                "sha256": payload["content_sha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
