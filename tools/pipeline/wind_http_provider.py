#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""项目内网 Wind HTTP 代理的受控提供层。

只加载项目根目录 ``WindPy.py``，不使用本机正式 Wind SDK。调用被限制为明确
字段白名单和单证券快照；代理地址、直连/no-proxy 与超时由根目录客户端统一处理。
本模块不写数据库，写入仍必须经过 refresh manifest 和 ``db_writer``。
"""
from __future__ import annotations

import importlib.util
import math
from datetime import datetime, time, timezone, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parent.parent.parent
SHANGHAI = timezone(timedelta(hours=8))

UNAPPROVED_MAX_SECURITIES_PER_REQUEST = 10
UNAPPROVED_MAX_FIELDS_PER_REQUEST = 20
UNAPPROVED_MAX_ESTIMATED_OBSERVATIONS_PER_REQUEST = 5_000

CURRENT_WSS_FIELDS = (
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

FIELD_MAP = {
    "pe_ttm": "PE_TTM",
    "pe_forward": "PE_EST_FTM",
    "pb": "PB_LF",
    "ps_ttm": "PS_TTM",
    "ev_ebitda": "EV2_TO_EBITDA",
    "peg": "PEG",
    "roe": "ROE_TTM",
    "roa": "ROA2_TTM",
    "eps_ttm": "EPS_TTM",
    "bps_mrq": "BPS_NEW",
}


class WindHttpUnavailable(RuntimeError):
    """内网代理不可达、返回错误或响应结构无效。"""


class WindLargeRequestPermissionRequired(PermissionError):
    """Wind 请求超过默认小型范围，必须先取得用户明确授权。"""


def assert_wind_request_scope(
    *,
    security_count: int,
    field_count: int,
    estimated_observations: int,
    large_request_approved: bool = False,
) -> None:
    """阻止未授权的大批证券、宽字段或长历史请求。

    这里校验单次请求。任务级调用方还必须按活动合同累计当日证券数和预计观测数，
    不得把一个大任务拆成很多小请求绕过门禁。
    """
    values = {
        "security_count": security_count,
        "field_count": field_count,
        "estimated_observations": estimated_observations,
    }
    if any(isinstance(value, bool) or int(value) < 0 for value in values.values()):
        raise ValueError(f"Wind 请求规模必须是非负整数：{values}")
    violations = []
    if security_count > UNAPPROVED_MAX_SECURITIES_PER_REQUEST:
        violations.append(
            f"证券数{security_count}>{UNAPPROVED_MAX_SECURITIES_PER_REQUEST}"
        )
    if field_count > UNAPPROVED_MAX_FIELDS_PER_REQUEST:
        violations.append(f"字段数{field_count}>{UNAPPROVED_MAX_FIELDS_PER_REQUEST}")
    if estimated_observations > UNAPPROVED_MAX_ESTIMATED_OBSERVATIONS_PER_REQUEST:
        violations.append(
            "预计观测数"
            f"{estimated_observations}>{UNAPPROVED_MAX_ESTIMATED_OBSERVATIONS_PER_REQUEST}"
        )
    if violations and not large_request_approved:
        raise WindLargeRequestPermissionRequired(
            "Wind 请求超过默认小型取数范围，执行前必须向用户说明证券范围、字段、"
            "日期区间和预计观测数并取得明确 permission：" + "；".join(violations)
        )


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


@lru_cache(maxsize=1)
def load_wind_http_client():
    """显式加载项目根目录代理，避免误导入正式 SDK 的同名模块。"""
    path = ROOT / "WindPy.py"
    if not path.is_file():
        raise WindHttpUnavailable(f"项目 Wind HTTP 客户端不存在：{path}")
    spec = importlib.util.spec_from_file_location("industry_demo_wind_http", path)
    if spec is None or spec.loader is None:
        raise WindHttpUnavailable("无法创建项目 Wind HTTP 客户端加载器")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    client = getattr(module, "w", None)
    if client is None:
        raise WindHttpUnavailable("项目 WindPy.py 未导出 w 客户端")
    return client


def _parse_wind_date(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw or raw.lower() in {"nat", "nan", "none"}:
        return None
    raw = raw[:10]
    try:
        return datetime.fromisoformat(raw).date().isoformat()
    except ValueError:
        return None


def latest_completed_trade_date(*, client=None, now: datetime | None = None) -> str:
    """返回最近已完成的 A 股交易日，避免盘中把未完成行情当收盘快照。"""
    actual_client = client or load_wind_http_client()
    current = now or datetime.now(SHANGHAI)
    if current.tzinfo is None:
        current = current.replace(tzinfo=SHANGHAI)
    else:
        current = current.astimezone(SHANGHAI)
    completed_today = current.weekday() < 5 and current.time() >= time(16, 30)
    offset = 0 if completed_today else -1
    result = actual_client.tdaysoffset(offset, current.date().isoformat(), "")
    if int(getattr(result, "ErrorCode", -1)) != 0:
        raise WindHttpUnavailable(
            f"Wind tdaysoffset 失败：ErrorCode={getattr(result, 'ErrorCode', None)}"
        )
    candidates: list[Any] = []
    data = getattr(result, "Data", None)
    if isinstance(data, (list, tuple)):
        for row in data:
            if isinstance(row, (list, tuple)):
                candidates.extend(row)
            else:
                candidates.append(row)
    candidates.extend(getattr(result, "Times", None) or [])
    for candidate in candidates:
        parsed = _parse_wind_date(candidate)
        if parsed:
            return parsed
    raise WindHttpUnavailable("Wind tdaysoffset 返回中没有可解析交易日")


def a_share_trading_day_evidence(
    trade_date: str, *, client=None
) -> dict[str, Any]:
    """Validate one date against both SSE and SZSE Wind calendars."""
    parsed = _parse_wind_date(trade_date)
    if not parsed:
        raise WindHttpUnavailable("trade_date must be an ISO date")
    actual_client = client or load_wind_http_client()
    results: dict[str, dict[str, Any]] = {}
    for exchange in ("SSE", "SZSE"):
        response = actual_client.tdays(parsed, parsed, f"TradingCalendar={exchange}")
        code = int(getattr(response, "ErrorCode", -1))
        if code != 0:
            raise WindHttpUnavailable(
                f"Wind {exchange} trading calendar failed: ErrorCode={code}"
            )
        candidates: list[Any] = []
        data = getattr(response, "Data", None)
        if isinstance(data, (list, tuple)):
            for row in data:
                candidates.extend(row if isinstance(row, (list, tuple)) else [row])
        candidates.extend(getattr(response, "Times", None) or [])
        dates = sorted({value for item in candidates if (value := _parse_wind_date(item))})
        results[exchange] = {"dates": dates, "exact_match": parsed in dates}
    return {
        "provider": "Wind.tdays",
        "trade_date": parsed,
        "exchanges": results,
        "is_trading_day": all(item["exact_match"] for item in results.values()),
        "weekday_heuristic_used": False,
    }


def hk_trading_day_evidence(trade_date: str, *, client=None) -> dict[str, Any]:
    """Validate one ISO date against Wind's HKEX trading calendar."""
    parsed = _parse_wind_date(trade_date)
    if not parsed:
        raise WindHttpUnavailable("trade_date must be an ISO date")
    actual_client = client or load_wind_http_client()
    response = actual_client.tdays(parsed, parsed, "TradingCalendar=HKEX")
    code = int(getattr(response, "ErrorCode", -1))
    if code != 0:
        raise WindHttpUnavailable(
            f"Wind HKEX trading calendar failed: ErrorCode={code}"
        )
    candidates: list[Any] = []
    data = getattr(response, "Data", None)
    if isinstance(data, (list, tuple)):
        for row in data:
            candidates.extend(row if isinstance(row, (list, tuple)) else [row])
    candidates.extend(getattr(response, "Times", None) or [])
    dates = sorted({value for item in candidates if (value := _parse_wind_date(item))})
    return {
        "provider": "Wind.tdays",
        "trade_date": parsed,
        "exchanges": {"HKEX": {"dates": dates, "exact_match": parsed in dates}},
        "is_trading_day": parsed in dates,
        "weekday_heuristic_used": False,
    }


def _wss_row(
    ticker: str,
    fields: tuple[str, ...],
    *,
    options: str,
    client=None,
    large_request_approved: bool = False,
) -> dict[str, Any]:
    assert_wind_request_scope(
        security_count=1,
        field_count=len(fields),
        estimated_observations=len(fields),
        large_request_approved=large_request_approved,
    )
    actual_client = client or load_wind_http_client()
    result = actual_client.wss(ticker, ",".join(fields), options)
    error_code = int(getattr(result, "ErrorCode", -1))
    if error_code != 0:
        raise WindHttpUnavailable(f"Wind wss 失败：ErrorCode={error_code}")
    frame = getattr(result, "dfData", None)
    if frame is None or getattr(frame, "empty", True):
        raise WindHttpUnavailable("Wind wss 返回空表")
    try:
        row = frame.iloc[0]
        return {str(column).upper(): row[column] for column in frame.columns}
    except Exception as exc:
        raise WindHttpUnavailable("Wind wss 响应结构无法解析") from exc


def _wsq_row(
    ticker: str,
    fields: tuple[str, ...],
    *,
    client=None,
    large_request_approved: bool = False,
) -> dict[str, Any]:
    """Return one real-time Wind quote row under the narrow-scope gate."""
    assert_wind_request_scope(
        security_count=1,
        field_count=len(fields),
        estimated_observations=len(fields),
        large_request_approved=large_request_approved,
    )
    actual_client = client or load_wind_http_client()
    result = actual_client.wsq(ticker, ",".join(fields))
    error_code = int(getattr(result, "ErrorCode", -1))
    if error_code != 0:
        raise WindHttpUnavailable(f"Wind wsq failed: ErrorCode={error_code}")
    frame = getattr(result, "dfData", None)
    if frame is None or getattr(frame, "empty", True):
        raise WindHttpUnavailable("Wind wsq returned an empty table")
    try:
        row = frame.iloc[0]
        return {str(column).upper(): row[column] for column in frame.columns}
    except Exception as exc:
        raise WindHttpUnavailable("Wind wsq response cannot be parsed") from exc


def fetch_intraday_market_quote(
    ticker: str, *, trade_date: str, client=None
) -> dict[str, Any]:
    """Read an unadjusted real-time price and total market cap.

    Units: ``share_price_value`` is CNY/share for A shares and HKD/share for
    Hong Kong shares; ``market_cap_value`` is hundred-million units of the
    same currency.  ``observed_at`` is supplied by the caller in
    Asia/Shanghai and is not inferred from the quote payload.
    """
    symbol = str(ticker or "").strip().upper()
    parsed = _parse_wind_date(trade_date)
    if not symbol.endswith((".SH", ".SZ", ".HK")) or not parsed:
        raise WindHttpUnavailable(
            "intraday market quote requires an A/H-share ticker and ISO date"
        )
    # mkt_cap_ard is an end-of-day WSS field and is NULL during the current
    # session on the production proxy.  The two intraday slots must therefore
    # use Wind's real-time WSQ market cap and explicit suspension flag.
    row = _wsq_row(
        symbol,
        ("rt_last", "rt_mkt_cap", "rt_susp_flag"),
        client=client,
    )
    raw_price = _finite(row.get("RT_LAST"))
    raw = _finite(row.get("RT_MKT_CAP"))
    if raw_price is None or raw_price <= 0 or raw is None or raw <= 0:
        raise WindHttpUnavailable(
            f"Wind price or market cap is empty or invalid for {symbol}"
        )
    raw_suspension = row.get("RT_SUSP_FLAG")
    normalized_suspension = str(raw_suspension).strip().casefold()
    if normalized_suspension in {"0", "0.0", "否", "false", "normal"}:
        trading_status = "trading"
    elif normalized_suspension in {"1", "1.0", "是", "true", "suspended"}:
        trading_status = "suspended"
    else:
        raise WindHttpUnavailable(
            f"Wind suspension flag is empty or unsupported for {symbol}: "
            f"{raw_suspension!r}"
        )
    currency = "HKD" if symbol.endswith(".HK") else "CNY"
    return {
        "ticker": symbol,
        "trade_date": parsed,
        "raw_field": "rt_mkt_cap",
        "raw_value": raw,
        "market_cap_value": raw / 1e8,
        "currency": currency,
        "unit": "亿元",
        "share_price_value": raw_price,
        "share_price_currency": currency,
        "share_price_unit": "元",
        "share_price_raw_field": "rt_last",
        "provider": "Wind",
        "trading_status": trading_status,
        "raw_trading_status": str(raw_suspension).strip(),
        "source_ref": (
            f"Wind WSQ.rt_last+rt_mkt_cap+rt_susp_flag:{symbol}:{parsed}"
        ),
    }


def fetch_intraday_market_cap(
    ticker: str, *, trade_date: str, client=None
) -> dict[str, Any]:
    """Backward-compatible alias returning the richer A-share quote payload."""
    symbol = str(ticker or "").strip().upper()
    if not symbol.endswith((".SH", ".SZ")):
        raise WindHttpUnavailable(
            "intraday market cap compatibility path only accepts A shares"
        )
    return fetch_intraday_market_quote(
        symbol, trade_date=trade_date, client=client
    )


def fetch_current_market_financial_snapshot(
    ticker: str,
    *,
    fx: Mapping[str, float] | None = None,
    trade_date: str | None = None,
    client=None,
) -> dict[str, Any]:
    """取得一只 A 股的当前行情、估值和 TTM/MRQ 核心财务快照。"""
    symbol = str(ticker or "").strip().upper()
    if not symbol.endswith((".SH", ".SZ", ".BJ")):
        raise WindHttpUnavailable(f"Wind A 股快照不支持 ticker={ticker!r}")
    actual_client = client or load_wind_http_client()
    observed_date = trade_date or latest_completed_trade_date(client=actual_client)
    parsed_date = _parse_wind_date(observed_date)
    if not parsed_date:
        raise WindHttpUnavailable("Wind trade_date 必须是有效日期")
    options = f"tradeDate={parsed_date.replace('-', '')};unit=1"
    row = _wss_row(
        symbol,
        CURRENT_WSS_FIELDS,
        options=options,
        client=actual_client,
    )

    market_cap_raw = _finite(row.get("MKT_CAP_ARD"))
    market_cap_cny = (
        round(market_cap_raw / 1e8, 2) if market_cap_raw is not None else None
    )
    usd_to_cny = _finite((fx or {}).get("USD"))
    market_cap_usd = (
        round(market_cap_cny / usd_to_cny, 2)
        if market_cap_cny is not None and usd_to_cny not in (None, 0)
        else None
    )

    values = {
        field: _finite(row.get(wind_field))
        for field, wind_field in FIELD_MAP.items()
    }
    values["market_cap_cny"] = market_cap_cny
    values["market_cap_usd"] = market_cap_usd

    field_as_of = {
        field: parsed_date for field, value in values.items() if value is not None
    }
    field_methods: dict[str, dict[str, Any]] = {}
    for field, wind_field in FIELD_MAP.items():
        if values[field] is None:
            continue
        basis = "Wind交易日快照"
        if field in {"roe", "roa", "eps_ttm"}:
            basis = "Wind在该交易日可见的TTM指标；as_of为快照日"
        elif field == "bps_mrq":
            basis = "Wind在该交易日可见的最新每股净资产；as_of为快照日而非底层报告期"
        field_methods[field] = {
            "extraction_method": "web_fetch",
            "basis": basis,
            "api_fields": [f"Wind WSS.{wind_field.lower()}"],
        }
    if market_cap_cny is not None:
        field_methods["market_cap_cny"] = {
            "extraction_method": "inferred",
            "formula": "Wind WSS.mkt_cap_ard(人民币元) / 1e8",
            "basis": "总市值，人民币亿元",
            "api_fields": ["Wind WSS.mkt_cap_ard"],
            "inputs": {"market_cap_cny_yuan": market_cap_raw},
        }
    if market_cap_usd is not None:
        field_methods["market_cap_usd"] = {
            "extraction_method": "inferred",
            "formula": "market_cap_cny_yi / yfinance USDCNY=X",
            "basis": "美元等值，不改变Wind人民币总市值主值",
            "api_fields": ["Wind WSS.mkt_cap_ard", "yfinance USDCNY=X"],
            "inputs": {
                "market_cap_cny_yi": market_cap_cny,
                "usd_to_cny": usd_to_cny,
            },
        }

    return {
        "source": "wind",
        "symbol": symbol,
        "currency": "CNY",
        "per_share_currency": "CNY",
        "trade_date": parsed_date,
        "financial_metrics_as_of": parsed_date,
        "price": _finite(row.get("CLOSE")),
        "market_cap_value": market_cap_cny,
        "market_cap_unit": "亿元人民币",
        "field_as_of": field_as_of,
        "field_methods": field_methods,
        "errors": [],
        **values,
    }
