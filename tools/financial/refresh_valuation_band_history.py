from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from tools.financial.constants import DB_PATH
from tools.financial.db import connect, transaction, verify_database
from tools.financial.repository import record_source_snapshot, upsert_observation
from tools.pipeline.wind_http_provider import (
    WindHttpUnavailable,
    assert_wind_request_scope,
    load_wind_http_client,
)


DEFAULT_COMPANY_IDS = (1, 2, 14, 414)
FIELDS = ("close", "pe_ttm", "pb_lf")
FIELD_SPECS = {
    "close": ("close", "元/股"),
    "pe_ttm": ("pe_ttm", "倍"),
    "pb_lf": ("pb", "倍"),
}


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _records(frame: Any, *, fallback_date: str | None = None) -> list[dict[str, Any]]:
    if frame is None or getattr(frame, "empty", True):
        return []
    result = []
    for index, row in frame.iterrows():
        date_value = str(index)[:10]
        try:
            date.fromisoformat(date_value)
        except ValueError:
            if not fallback_date:
                continue
            date_value = fallback_date
        values = {
            str(column).lower(): _finite(value.item() if hasattr(value, "item") else value)
            for column, value in row.items()
        }
        result.append({"date": date_value, "values": values})
    return result


def _request(client: Any, ticker: str, start: str, end: str, options: str) -> list[dict[str, Any]]:
    response = client.wsd(ticker, ",".join(FIELDS), start, end, options)
    error_code = int(getattr(response, "ErrorCode", -1))
    if error_code != 0:
        raise WindHttpUnavailable(
            f"Wind WSD失败：ticker={ticker}, ErrorCode={error_code}"
        )
    return _records(getattr(response, "dfData", None), fallback_date=end if start == end else None)


def refresh(
    *,
    db_path: Path = DB_PATH,
    company_ids: tuple[int, ...] = DEFAULT_COMPANY_IDS,
    start: str = "2021-01-01",
    monthly_end: str = "2026-06-30",
    valuation_date: str = "2026-07-22",
) -> dict[str, Any]:
    """Refresh narrow Wind valuation-band facts directly into financial.db only."""
    if not company_ids or len(company_ids) > 10:
        raise ValueError("估值带刷新只允许1—10家公司")
    estimated_months = 67
    estimated_observations = len(company_ids) * (
        estimated_months * len(FIELDS) + len(FIELDS)
    )
    assert_wind_request_scope(
        security_count=len(company_ids),
        field_count=len(FIELDS),
        estimated_observations=estimated_observations,
    )
    conn = connect(db_path)
    try:
        placeholders = ",".join("?" for _ in company_ids)
        securities = [
            dict(row)
            for row in conn.execute(
                f"""SELECT DISTINCT s.id,s.canonical_name,s.ticker
                       FROM financial_security s
                       JOIN financial_security_company_link l ON l.security_id=s.id
                      WHERE l.research_company_id IN ({placeholders})
                      ORDER BY l.research_company_id""",
                company_ids,
            )
        ]
    finally:
        conn.close()
    if len(securities) != len(set(company_ids)):
        raise ValueError("部分公司尚未建立规范 financial_security 映射")

    client = load_wind_http_client()
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payloads: list[dict[str, Any]] = []
    for security in securities:
        ticker = str(security["ticker"] or "").strip()
        if not ticker:
            raise ValueError(f"{security['canonical_name']}缺少证券代码")
        monthly = _request(
            client, ticker, start, monthly_end, "Period=M;PriceAdj=F"
        )
        current = _request(
            client, ticker, valuation_date, valuation_date, "PriceAdj=F"
        )
        payloads.append({
            "security": security,
            "monthly": monthly,
            "current": current,
        })

    counts = {"inserted": 0, "revised": 0, "unchanged": 0}
    conn = connect(db_path)
    try:
        with transaction(conn):
            for payload in payloads:
                security = payload["security"]
                for frequency, rows in (
                    ("monthly", payload["monthly"]),
                    ("snapshot", payload["current"]),
                ):
                    if not rows:
                        continue
                    scope_end = monthly_end if frequency == "monthly" else valuation_date
                    source_payload = {
                        "ticker": security["ticker"],
                        "fields": FIELDS,
                        "start": start if frequency == "monthly" else valuation_date,
                        "end": scope_end,
                        "frequency": frequency,
                        "rows": rows,
                    }
                    content_hash = "sha256:" + hashlib.sha256(
                        json.dumps(
                            source_payload,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ).hexdigest()
                    source_id = record_source_snapshot(
                        conn,
                        provider="wind",
                        source_channel="structured_api",
                        source_ref=(
                            f"wind:WSD:{security['ticker']}:"
                            f"{','.join(FIELDS)}:{frequency}:{scope_end}"
                        ),
                        title=f"{security['canonical_name']} Wind估值带窄字段",
                        publisher="Wind",
                        as_of_date=scope_end,
                        fetched_at=fetched_at,
                        content_hash=content_hash,
                        metadata={
                            "security_count": 1,
                            "field_count": len(FIELDS),
                            "frequency": frequency,
                            "date_range": [
                                start if frequency == "monthly" else valuation_date,
                                scope_end,
                            ],
                            "database_boundary": "financial.db only",
                        },
                    )
                    for row in rows:
                        for raw_field, (metric_name, unit) in FIELD_SPECS.items():
                            value = row["values"].get(raw_field)
                            if value is None:
                                continue
                            _, status = upsert_observation(
                                conn,
                                return_status=True,
                                security_id=int(security["id"]),
                                metric_name=metric_name,
                                value_num=value,
                                unit=unit,
                                currency="CNY" if metric_name == "close" else None,
                                period_end=row["date"],
                                frequency=frequency,
                                fact_type="market",
                                as_of_date=row["date"],
                                provider="wind",
                                raw_feature_name=f"Wind WSD.{raw_field}",
                                source_snapshot_id=source_id,
                                quality_status="usable",
                                scenario_name="reported",
                            )
                            counts[status] += 1
        verification = verify_database(db_path)
    finally:
        conn.close()
    return {
        "database": str(Path(db_path).resolve()),
        "company_ids": list(company_ids),
        "fields": list(FIELDS),
        "date_range": [start, monthly_end],
        "valuation_date": valuation_date,
        "estimated_observations": estimated_observations,
        **counts,
        "verification": verification,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="小型Wind估值带刷新：仅写financial.db，不写research/opportunity库"
    )
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument(
        "--company-ids",
        default=",".join(str(value) for value in DEFAULT_COMPANY_IDS),
    )
    parser.add_argument("--start", default="2021-01-01")
    parser.add_argument("--monthly-end", default="2026-06-30")
    parser.add_argument("--valuation-date", default="2026-07-22")
    args = parser.parse_args(argv)
    company_ids = tuple(
        int(value.strip())
        for value in str(args.company_ids).split(",")
        if value.strip()
    )
    result = refresh(
        db_path=args.db.resolve(),
        company_ids=company_ids,
        start=args.start,
        monthly_end=args.monthly_end,
        valuation_date=args.valuation_date,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
