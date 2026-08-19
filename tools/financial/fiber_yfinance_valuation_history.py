from __future__ import annotations

"""Build and apply bounded point-in-time PE/PB histories for fiber peers.

The derived multiples use each month-end unadjusted close and the latest annual
EPS/BPS that was publicly available at that month end.  They are intentionally
labelled as annual-report approximations, not vendor historical TTM multiples.
"""

import argparse
import hashlib
import json
import math
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tools.financial.constants import DB_PATH
from tools.financial.db import connect, transaction
from tools.financial.repository import record_source_snapshot, upsert_observation


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "config" / "financial" / "fiber_yfinance_valuation_history_v1.json"
TARGETS = (
    {"company_id": 59, "ticker": "5802.T", "currency": "JPY"},
    {"company_id": 203, "ticker": "GLW", "currency": "USD"},
    {"company_id": 704, "ticker": "PRY.MI", "currency": "EUR"},
)
START_DATE = "2022-01-01"
AS_OF_DATE = "2026-08-20"


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _series(frame: Any, names: tuple[str, ...]) -> Any:
    for name in names:
        if name in getattr(frame, "index", ()):
            return frame.loc[name]
    return None


def _available_from(period_end: date) -> date:
    if period_end.month <= 3:
        return period_end + timedelta(days=60)
    return date(period_end.year + 1, 4, 30)


def _annual_anchors(income: Any, balance: Any) -> list[dict[str, Any]]:
    net_income = _series(income, ("Net Income Common Stockholders", "Net Income"))
    income_shares = _series(income, ("Diluted Average Shares", "Basic Average Shares"))
    balance_shares = _series(balance, ("Ordinary Shares Number", "Share Issued"))
    equity = _series(balance, ("Stockholders Equity", "Total Equity Gross Minority Interest"))
    anchors: list[dict[str, Any]] = []
    for column in getattr(income, "columns", ()):
        period_end = date.fromisoformat(str(column)[:10])
        balance_column = next(
            (item for item in getattr(balance, "columns", ()) if str(item)[:10] == period_end.isoformat()),
            None,
        )
        net = _finite(net_income.get(column)) if net_income is not None else None
        shares = _finite(income_shares.get(column)) if income_shares is not None else None
        if shares is None and balance_column is not None and balance_shares is not None:
            shares = _finite(balance_shares.get(balance_column))
        book = _finite(equity.get(balance_column)) if balance_column is not None and equity is not None else None
        if net is None or shares is None or book is None or shares <= 0 or book <= 0:
            continue
        anchors.append({
            "periodEnd": period_end.isoformat(),
            "availableFrom": _available_from(period_end).isoformat(),
            "netIncome": net,
            "bookValue": book,
            "shares": shares,
            "eps": net / shares,
            "bps": book / shares,
        })
    return sorted(anchors, key=lambda item: item["availableFrom"])


def _month_end_closes(frame: Any) -> list[dict[str, Any]]:
    if frame is None or getattr(frame, "empty", True):
        return []
    series = frame["Close"]
    if getattr(series, "ndim", 1) > 1:
        series = series.iloc[:, 0]
    by_month: dict[str, dict[str, Any]] = {}
    for index, raw in series.dropna().items():
        value = _finite(raw)
        if value is None or value <= 0:
            continue
        day = str(index)[:10]
        by_month[day[:7]] = {"date": day, "close": value}
    return [by_month[key] for key in sorted(by_month)]


def _observations(
    prices: list[dict[str, Any]], anchors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for price in prices:
        eligible = [item for item in anchors if item["availableFrom"] <= price["date"]]
        if not eligible:
            continue
        anchor = eligible[-1]
        eps = float(anchor["eps"])
        bps = float(anchor["bps"])
        result.append({
            **price,
            "financialPeriodEnd": anchor["periodEnd"],
            "financialAvailableFrom": anchor["availableFrom"],
            "eps": eps,
            "bps": bps,
            "peAnnualApprox": float(price["close"]) / eps if eps > 0 else None,
            "pbApprox": float(price["close"]) / bps,
        })
    return result


def build() -> dict[str, Any]:
    import yfinance as yf

    companies = []
    end = (date.fromisoformat(AS_OF_DATE) + timedelta(days=1)).isoformat()
    for target in TARGETS:
        security = yf.Ticker(target["ticker"])
        prices = _month_end_closes(security.history(
            start=START_DATE, end=end, interval="1d", auto_adjust=False, actions=False,
        ))
        anchors = _annual_anchors(security.income_stmt, security.balance_sheet)
        observations = _observations(prices, anchors)
        if len(observations) < 12:
            raise RuntimeError(f"{target['ticker']}可复算月末估值历史不足12期")
        companies.append({
            **target,
            "annualAnchors": anchors,
            "observations": observations,
            "positivePeObservations": sum(
                item["peAnnualApprox"] is not None for item in observations
            ),
            "pbObservations": len(observations),
        })
    payload = {
        "schemaVersion": "fiber.yfinance_valuation_history.v1",
        "asOfDate": AS_OF_DATE,
        "startDate": START_DATE,
        "sourceContract": {
            "price": "Yahoo Finance month-end unadjusted Close",
            "financials": "Yahoo Finance annual income statement and balance sheet",
            "lookAheadControl": (
                "March fiscal years become usable 60 days after period end; "
                "other fiscal years become usable on the following April 30"
            ),
            "formula": (
                "PE近似值＝月末收盘价÷当时已公开年报EPS；"
                "PB近似值＝月末收盘价÷当时已公开年报BPS"
            ),
            "limitation": (
                "点时年报口径近似，不冒充Yahoo Finance历史TTM倍数；"
                "财年之间不滚动更新TTM利润或季度净资产。"
            ),
        },
        "companies": companies,
    }
    payload["contentSha256"] = _sha(payload)
    return payload


def _load_verified(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = str(payload.pop("contentSha256", ""))
    actual = _sha(payload)
    payload["contentSha256"] = expected
    if not expected or actual != expected:
        raise ValueError("Yahoo Finance估值历史内容哈希不匹配")
    if {int(item["company_id"]) for item in payload.get("companies") or []} != {59, 203, 704}:
        raise ValueError("Yahoo Finance估值历史公司集合不完整")
    return payload


def apply(path: Path = DEFAULT_OUTPUT, *, db_path: Path = DB_PATH) -> dict[str, Any]:
    payload = _load_verified(path)
    read = connect(db_path, readonly=True)
    try:
        securities = {}
        for company in payload["companies"]:
            row = read.execute(
                """SELECT s.id,s.ticker,l.research_company_id
                     FROM financial_security s
                     JOIN financial_security_company_link l ON l.security_id=s.id
                    WHERE l.research_company_id=?""",
                (int(company["company_id"]),),
            ).fetchone()
            if row is None or str(row["ticker"] or "").upper() != str(company["ticker"]).upper():
                raise ValueError(f"公司与证券身份不匹配：{company['company_id']}")
            securities[int(company["company_id"])] = int(row["id"])
    finally:
        read.close()

    counts = {"inserted": 0, "revised": 0, "unchanged": 0}
    operation_id = f"fiber-yfinance-band:{payload['contentSha256']}"
    actor = str(os.environ.get("HONGHU_AUDIT_ACTOR") or "HonghuTaskRunner")
    connection = connect(
        db_path,
        operation_scope="fiber_yfinance_valuation_history_v1",
        operation_id=operation_id,
        actor=actor,
    )
    exact = {}
    try:
        with transaction(connection):
            for company in payload["companies"]:
                source_id = record_source_snapshot(
                    connection,
                    provider="yfinance",
                    source_channel="structured_api",
                    source_ref=(
                        f"yfinance:fiber_point_in_time_valuation:{company['ticker']}:"
                        f"{payload['asOfDate']}"
                    ),
                    title=f"{company['ticker']}月末收盘价与点时年报口径PE/PB",
                    publisher="Yahoo Finance",
                    as_of_date=payload["asOfDate"],
                    fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    content_hash="sha256:" + payload["contentSha256"],
                    raw_snapshot_path=path.relative_to(ROOT).as_posix(),
                    metadata={
                        **payload["sourceContract"],
                        "database_boundary": "financial.db only",
                    },
                )
                for item in company["observations"]:
                    values = (
                        ("close", item["close"], f"{company['currency']}/股", "yfinance.history.month_end_close", None),
                        ("pb", item["pbApprox"], "倍", "yfinance.derived.point_in_time.pb", "PB近似值＝月末收盘价÷当时已公开年报BPS"),
                        ("pe_ttm", item["peAnnualApprox"], "倍", "yfinance.derived.point_in_time.pe_ttm", "PE近似值＝月末收盘价÷当时已公开年报EPS"),
                    )
                    for metric, value, unit, raw_feature, formula in values:
                        if value is None:
                            continue
                        _, status = upsert_observation(
                            connection,
                            return_status=True,
                            revision_reason="fiber_yfinance_point_in_time_valuation_refresh",
                            security_id=securities[int(company["company_id"])],
                            metric_name=metric,
                            value_num=float(value),
                            unit=unit,
                            currency=company["currency"] if metric == "close" else None,
                            period_end=item["date"],
                            frequency="monthly",
                            fact_type="market",
                            as_of_date=item["date"],
                            announcement_date=item["financialAvailableFrom"],
                            provider="yfinance",
                            raw_feature_name=raw_feature,
                            source_snapshot_id=source_id,
                            formula=formula,
                            input_refs=[
                                f"financial_period_end:{item['financialPeriodEnd']}",
                                f"financial_available_from:{item['financialAvailableFrom']}",
                                f"eps:{item['eps']}", f"bps:{item['bps']}",
                            ],
                            quality_status="usable" if metric == "close" else "limited",
                            scenario_name="reported",
                        )
                        counts[status] += 1
        for company in payload["companies"]:
            security_id = securities[int(company["company_id"])]
            exact[str(company["company_id"])] = {
                metric: int(connection.execute(
                    """SELECT count(*) FROM financial_observation
                        WHERE security_id=? AND metric_name=? AND frequency='monthly'
                          AND provider='yfinance' AND raw_feature_name=?
                          AND quality_status<>'superseded'""",
                    (security_id, metric, feature),
                ).fetchone()[0])
                for metric, feature in (
                    ("close", "yfinance.history.month_end_close"),
                    ("pb", "yfinance.derived.point_in_time.pb"),
                    ("pe_ttm", "yfinance.derived.point_in_time.pe_ttm"),
                )
            }
            if min(exact[str(company["company_id"])].values()) < 12:
                raise RuntimeError(f"写后复读不足12期：{company['company_id']}")
    finally:
        connection.close()
    return {"contentSha256": payload["contentSha256"], "counts": counts, "readback": exact}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--db", type=Path, default=DB_PATH)
    args = parser.parse_args(argv)
    if args.apply:
        result = apply(args.output.resolve(), db_path=args.db.resolve())
    else:
        payload = build()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result = {
            "output": args.output.relative_to(ROOT).as_posix(),
            "contentSha256": payload["contentSha256"],
            "companies": {
                item["ticker"]: {
                    "pb": item["pbObservations"],
                    "positivePe": item["positivePeObservations"],
                }
                for item in payload["companies"]
            },
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
