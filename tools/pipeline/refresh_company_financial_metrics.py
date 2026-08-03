#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""统一刷新公司估值与六项核心财务指标。

该模块把外部抓取与数据库应用拆成三个显式阶段：

1. 默认 ``--dry-run``：只读数据库，生成覆盖全部 company 的计划 manifest；
2. ``--fetch-only``：按规范化 ticker 去重调用 Wind/Tushare/yfinance，只写 manifest；
3. ``--apply-manifest``：不联网，验证 manifest 和公司全集后原子应用到目标库。

真实数据源策略为 A 股使用内网 Wind HTTP 代理为主、Tushare 逐字段补缺，其他市场
使用 yfinance；A 股两源均不可用时才回落 yfinance。合并快照必须在 manifest 中保留
每个字段的实际 provider、symbol、时点和方法。没有 ticker、未上市、没有行业归属或
接口不可得都必须留下明确状态。

结构化行情、估值与财务事实只写入独立 ``financial.db``。``research.db.company``
中的旧数值列仅保留为历史兼容字段，刷新任务不再更新它们，也不再把供应商数据复制
成普通 ``industry_data_point``。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

try:  # package import
    from . import db_writer
    from .data_source_policy import assert_provider_allowed
    from .market_snapshot_utils import fetch_company_market_snapshot, fetch_live_fx_rates
    from .tushare_provider import is_a_share_ticker, ts_code_from_ticker
    from ..financial.constants import DB_PATH as DEFAULT_FINANCIAL_DB
    from ..financial.db import initialize_database as initialize_financial_database
    from ..financial.repository import (
        record_source_snapshot as record_financial_source,
        upsert_observation as upsert_financial_observation,
        upsert_security as upsert_financial_security,
    )
except ImportError:  # direct script import
    import db_writer  # type: ignore
    from data_source_policy import assert_provider_allowed  # type: ignore
    from market_snapshot_utils import fetch_company_market_snapshot, fetch_live_fx_rates  # type: ignore
    from tushare_provider import is_a_share_ticker, ts_code_from_ticker  # type: ignore
    from tools.financial.constants import DB_PATH as DEFAULT_FINANCIAL_DB  # type: ignore
    from tools.financial.db import initialize_database as initialize_financial_database  # type: ignore
    from tools.financial.repository import (  # type: ignore
        record_source_snapshot as record_financial_source,
        upsert_observation as upsert_financial_observation,
        upsert_security as upsert_financial_security,
    )


ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = ROOT / "data" / "research.db"
MANIFEST_SCHEMA_VERSION = "company_financial_refresh.v3"

NONPUBLIC_STATUSES = {
    "delisted",
    "unlisted",
    "private",
    "private_subsidiary",
    "parent_subsidiary",
    "soe",
    "pre_ipo",
}

PROVIDER_META = {
    "wind": {
        "canonical": "api_wind",
        "publisher": "Wind 万得",
        "title": "Wind 内网 HTTP 代理公司估值与财务刷新",
        "url": "https://www.wind.com.cn/",
        "domain": "wind.com.cn",
        "quality_tier": 2,
        "language": "zh",
    },
    "tushare": {
        "canonical": "api_tushare",
        "publisher": "Tushare Pro",
        "title": "Tushare 公司估值与财务刷新",
        "url": "https://tushare.pro/",
        "domain": "tushare.pro",
        "quality_tier": 2,
        "language": "zh",
    },
    "yfinance": {
        "canonical": "api_yfinance",
        "publisher": "Yahoo Finance / yfinance",
        "title": "Yahoo Finance/yfinance 公司估值与财务刷新",
        "url": "https://finance.yahoo.com/",
        "domain": "finance.yahoo.com",
        "quality_tier": 2,
        "language": "en",
    },
}

MARKET_FIELDS = {
    "pe_ttm",
    "pe_forward",
    "pb",
    "ps_ttm",
    "ev_ebitda",
    "peg",
    "market_cap_cny",
    "market_cap_usd",
}
FINANCIAL_FIELDS = {"roe", "roa", "eps_ttm", "bps_mrq"}
NUMERIC_FIELDS = MARKET_FIELDS | FINANCIAL_FIELDS

# A fetch manifest is an application artifact, not an archive reader.  Very old
# observations are still useful in research history, but must not be promoted to
# the ``company`` current-value layer.  Market observations older than a month
# and financial observations older than roughly eighteen months therefore fail
# closed.  The latter window accommodates different fiscal calendars while still
# rejecting a provider's stale multi-year profile value.
FIELD_MAX_AGE_DAYS = {
    **{field: 31 for field in MARKET_FIELDS},
    **{field: 550 for field in FINANCIAL_FIELDS},
}
LOCAL_TIMEZONE = timezone(timedelta(hours=8))
NOT_APPLICABLE_FIELDS = {"pe_ttm", "pe_forward"}

# field -> (公开 metric 名, 固定 unit；None 表示按 per_share_currency 生成)
DP_FIELD_SPECS: dict[str, tuple[str, str | None]] = {
    "pe_ttm": ("市盈率PE_TTM", "倍"),
    "pe_forward": ("市盈率PE_Forward", "倍"),
    "pb": ("市净率PB", "倍"),
    "ps_ttm": ("市销率PS_TTM", "倍"),
    "ev_ebitda": ("企业价值倍数EV_EBITDA", "倍"),
    "peg": ("市盈增长比PEG", "倍"),
    "market_cap_cny": ("总市值", "亿元人民币"),
    "market_cap_usd": ("总市值_美元等值", "亿美元"),
    "roe": ("净资产收益率ROE", "%"),
    "roa": ("总资产收益率ROA", "%"),
    "eps_ttm": ("每股收益EPS_TTM", None),
    "bps_mrq": ("每股净资产BPS_MRQ", None),
}

# 独立财务库使用稳定英文 metric；中文 metric 仅保留给历史兼容记录。
FINANCIAL_FIELD_SPECS: dict[str, tuple[str, str | None, str]] = {
    "pe_ttm": ("pe_ttm", "倍", "market"),
    "pe_forward": ("pe_forward", "倍", "consensus"),
    "pb": ("pb", "倍", "market"),
    "ps_ttm": ("ps_ttm", "倍", "market"),
    "ev_ebitda": ("ev_ebitda", "倍", "market"),
    "peg": ("peg", "倍", "market"),
    "market_cap_cny": ("market_cap", "亿元人民币", "market"),
    "market_cap_usd": ("market_cap_usd", "亿美元", "market"),
    "roe": ("roe", "%", "actual"),
    "roa": ("roa", "%", "actual"),
    "eps_ttm": ("eps_ttm", None, "actual"),
    "bps_mrq": ("bps_mrq", None, "actual"),
}

REQUIRED_NEW_COLUMNS = {
    "eps_ttm",
    "bps_mrq",
    "per_share_currency",
    "financial_metrics_as_of",
    "financial_metrics_source_id",
}
REQUIRED_COMPANY_COLUMNS = REQUIRED_NEW_COLUMNS | NUMERIC_FIELDS | {
    "market_cap_value",
    "market_cap_unit",
    "valuation_as_of",
    "valuation_source_id",
}

SnapshotFetcher = Callable[..., Mapping[str, Any]]
FxProvider = Callable[[], Mapping[str, float]]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _is_iso_date(value: Any) -> bool:
    raw = str(value or "")
    try:
        return bool(raw) and date.fromisoformat(raw).isoformat() == raw
    except ValueError:
        return False


def _manifest_reference_date(value: Any) -> date:
    """Return the manifest's Shanghai calendar date.

    Providers report Asian trade dates before the same UTC date rolls over.  A
    UTC-date-only comparison would incorrectly classify those observations as
    future data, so the manifest timezone is made explicit here.
    """
    try:
        generated = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("refresh manifest generated_at 不是 ISO datetime") from exc
    if generated.tzinfo is None:
        raise ValueError("refresh manifest generated_at 必须包含时区")
    return generated.astimezone(LOCAL_TIMEZONE).date()


def _valid_field_date(field: str, value: Any, reference_date: date | None) -> tuple[str | None, str | None]:
    """Validate one provider observation date and return ``(date, error)``."""
    raw = str(value or "").strip()
    if not _is_iso_date(raw):
        return None, "missing_or_invalid_as_of"
    if reference_date is None:
        return raw, None
    observed = date.fromisoformat(raw)
    if observed > reference_date:
        return None, "future_as_of"
    max_age = FIELD_MAX_AGE_DAYS[field]
    if (reference_date - observed).days > max_age:
        return None, f"stale_as_of_over_{max_age}d"
    return raw, None


def normalize_yfinance_symbol(ticker: str | None) -> str:
    """把数据库 ticker 归一为 yfinance symbol，同时用于请求去重。"""
    raw = str(ticker or "").strip().upper()
    if not raw:
        return ""
    if raw.endswith(".SH"):
        return raw[:-3] + ".SS"
    if raw.endswith(".HK"):
        digits = raw[:-3]
        if digits.isdigit():
            return (digits.lstrip("0") or "0").rjust(4, "0") + ".HK"
    return raw


def fetch_identity(ticker: str | None) -> dict[str, str] | None:
    raw = str(ticker or "").strip().upper()
    if not raw:
        return None
    if is_a_share_ticker(raw):
        ts_code = ts_code_from_ticker(raw)
        if not ts_code:
            return None
        return {
            "provider_preference": "api_wind",
            "normalized_symbol": ts_code,
            "yf_symbol": normalize_yfinance_symbol(raw),
            "fetch_key": f"api_wind:{ts_code}",
        }
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.^=\-]{0,31}", raw):
        return None
    symbol = normalize_yfinance_symbol(raw)
    if not symbol:
        return None
    return {
        "provider_preference": "api_yfinance",
        "normalized_symbol": symbol,
        "yf_symbol": symbol,
        "fetch_key": f"api_yfinance:{symbol}",
    }


def _validate_snapshot_identity(entry: Mapping[str, Any], snapshot: Mapping[str, Any]) -> None:
    """Bind a snapshot to the entry's provider-specific security identity."""
    provider = str(snapshot.get("provider") or "").strip().lower()
    symbol = str(snapshot.get("symbol") or "").strip().upper()
    preferred = str(entry.get("provider_preference") or "")
    if provider in {"wind", "tushare"}:
        if preferred != "api_wind":
            raise ValueError(
                f"company_id={entry['company_id']} 非 A 股不得绑定 Wind/Tushare snapshot"
            )
        expected = str(entry.get("normalized_symbol") or "").strip().upper()
    elif provider == "yfinance":
        expected = str(entry.get("yf_symbol") or "").strip().upper()
    else:
        raise ValueError(f"company_id={entry['company_id']} snapshot provider 非法")
    if not symbol or symbol != expected:
        raise ValueError(
            f"company_id={entry['company_id']} snapshot.symbol 与 ticker/yf_symbol 不匹配"
        )
    field_providers = snapshot.get("field_providers")
    field_symbols = snapshot.get("field_symbols")
    if not isinstance(field_providers, Mapping) or not isinstance(field_symbols, Mapping):
        return
    for field, field_provider_raw in field_providers.items():
        field_provider = str(field_provider_raw or "").strip().lower()
        field_symbol = str(field_symbols.get(field) or "").strip().upper()
        if field_provider in {"wind", "tushare"}:
            field_expected = str(entry.get("normalized_symbol") or "").strip().upper()
        elif field_provider == "yfinance":
            field_expected = str(entry.get("yf_symbol") or "").strip().upper()
        else:
            raise ValueError(
                f"company_id={entry['company_id']} {field} field provider 非法"
            )
        if not field_symbol or field_symbol != field_expected:
            raise ValueError(
                f"company_id={entry['company_id']} {field} field symbol 与证券身份不匹配"
            )
    for field, status in (snapshot.get("field_statuses") or {}).items():
        if not isinstance(status, Mapping):
            raise ValueError(f"company_id={entry['company_id']} {field} status 非法")
        status_provider = str(status.get("provider") or provider).strip().lower()
        status_symbol = str(status.get("symbol") or symbol).strip().upper()
        if status_provider in {"wind", "tushare"}:
            status_expected = str(entry.get("normalized_symbol") or "").strip().upper()
        elif status_provider == "yfinance":
            status_expected = str(entry.get("yf_symbol") or "").strip().upper()
        else:
            raise ValueError(f"company_id={entry['company_id']} {field} status provider 非法")
        if status_symbol != status_expected:
            raise ValueError(f"company_id={entry['company_id']} {field} status symbol 不匹配")


def _readonly_connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _row_value(row: sqlite3.Row, key: str, default: Any = None) -> Any:
    """Read a compatibility column that may be absent in older test/deploy schemas."""
    return row[key] if key in row.keys() else default


def _industry_map(conn: sqlite3.Connection) -> dict[int, list[int]]:
    result: dict[int, list[int]] = defaultdict(list)
    for row in conn.execute(
        "SELECT company_id, industry_id FROM company_industry ORDER BY company_id, industry_id"
    ):
        result[int(row[0])].append(int(row[1]))
    return dict(result)


def _universe_payload(entries: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "company_id": int(entry["company_id"]),
            "name": str(entry.get("name") or ""),
            "ticker": str(entry.get("ticker") or ""),
            "listing_status": str(entry.get("listing_status") or ""),
            "industry_ids": [int(x) for x in entry.get("industry_ids") or []],
        }
        for entry in entries
    ]


def universe_sha256(entries: Iterable[Mapping[str, Any]]) -> str:
    payload = json.dumps(
        _universe_payload(entries),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_company_plan(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    industries = _industry_map(conn)
    entries: list[dict[str, Any]] = []
    rows = conn.execute(
        "SELECT id, name, ticker, listing_status FROM company ORDER BY id"
    ).fetchall()
    for row in rows:
        company_id = int(row["id"])
        ticker = str(row["ticker"] or "").strip()
        listing_status = str(row["listing_status"] or "").strip().lower()
        industry_ids = industries.get(company_id, [])
        identity = fetch_identity(ticker)
        reasons: list[str] = []
        if listing_status in NONPUBLIC_STATUSES:
            reasons.append("nonpublic_company")
        if not ticker:
            reasons.append("missing_ticker")
        elif identity is None:
            reasons.append("unsupported_ticker")
        if not industry_ids:
            reasons.append("missing_industry_relation")

        if "nonpublic_company" in reasons:
            status = "not_applicable_nonpublic"
        elif "missing_ticker" in reasons:
            status = "blocked_no_ticker"
        elif "unsupported_ticker" in reasons:
            status = "blocked_unsupported_ticker"
        else:
            # company 级六指标不依赖行业关系；无行业时仍抓取并更新 company，
            # 只是不能写需要 industry_id 的 industry_data_point。
            status = "planned"

        entry: dict[str, Any] = {
            "company_id": company_id,
            "name": str(row["name"] or ""),
            "ticker": ticker,
            "listing_status": listing_status or None,
            "industry_ids": industry_ids,
            "canonical_industry_id": min(industry_ids) if industry_ids else None,
            "status": status,
            "reasons": reasons,
        }
        if identity:
            entry.update(identity)
        entries.append(entry)
    return entries


def _sanitize_method(raw: Any) -> dict[str, Any]:
    method = dict(raw) if isinstance(raw, Mapping) else {}
    extraction_method = str(method.get("extraction_method") or "web_fetch")
    if extraction_method not in {"web_fetch", "inferred"}:
        extraction_method = "web_fetch"
    clean: dict[str, Any] = {"extraction_method": extraction_method}
    if method.get("formula"):
        clean["formula"] = str(method["formula"])[:300]
    if method.get("basis"):
        clean["basis"] = str(method["basis"])[:200]
    if isinstance(method.get("api_fields"), (list, tuple)):
        clean["api_fields"] = [str(x)[:100] for x in method["api_fields"][:8]]
    if isinstance(method.get("inputs"), Mapping):
        inputs: dict[str, Any] = {}
        for key, value in list(method["inputs"].items())[:12]:
            if value is None or isinstance(value, bool):
                continue
            number = _finite(value)
            inputs[str(key)[:80]] = number if number is not None else str(value)[:120]
        if inputs:
            clean["inputs"] = inputs
    return clean


def sanitize_snapshot(
    raw: Mapping[str, Any],
    *,
    reference_date: date | None = None,
) -> dict[str, Any]:
    """只保留带真实时点的可应用字段。

    数值、provider、字段时点是一个不可拆分的证据单元。缺少真实交易日/报告期、
    日期在 manifest 未来或超过当前值最大时效窗口的字段会逐字段 fail closed，
    而不是用抓取日补造时点。非正 PE 保留为带时点的 ``not_applicable`` 动作，
    使 apply 能清掉旧负 PE，同时不会把它写成可比较数据点。
    """
    source = str(raw.get("source") or "").strip().lower()
    if source not in PROVIDER_META:
        error = str(raw.get("error") or "未知或缺失 provider")[:240]
        return {"status": "provider_error", "error": error, "errors": []}
    canonical_provider = PROVIDER_META[source]["canonical"]
    assert_provider_allowed(canonical_provider, context="company financial refresh")

    warnings: list[str] = []
    values: dict[str, float] = {}
    field_statuses: dict[str, dict[str, str]] = {}
    field_as_of_raw = raw.get("field_as_of")
    field_methods_raw = raw.get("field_methods")
    field_providers_raw = raw.get("field_providers")
    field_symbols_raw = raw.get("field_symbols")
    field_providers: dict[str, str] = {}
    field_symbols: dict[str, str] = {}
    for field in sorted(NUMERIC_FIELDS):
        value = _finite(raw.get(field))
        if value is None:
            continue
        field_provider = str(
            (field_providers_raw or {}).get(field) or source
            if isinstance(field_providers_raw, Mapping)
            else source
        ).strip().lower()
        if field_provider not in PROVIDER_META:
            warnings.append(f"{field}:unknown_field_provider")
            continue
        assert_provider_allowed(
            PROVIDER_META[field_provider]["canonical"],
            context=f"company financial refresh field={field}",
        )
        field_symbol = str(
            (field_symbols_raw or {}).get(field) or raw.get("symbol") or ""
            if isinstance(field_symbols_raw, Mapping)
            else raw.get("symbol") or ""
        ).strip()[:40]
        if not field_symbol:
            warnings.append(f"{field}:missing_field_symbol")
            continue
        raw_as_of = (
            (field_as_of_raw or {}).get(field)
            if isinstance(field_as_of_raw, Mapping)
            else None
        )
        field_date, date_error = _valid_field_date(field, raw_as_of, reference_date)
        if date_error:
            warnings.append(f"{field}:{date_error}")
            continue
        assert field_date is not None
        if field in NOT_APPLICABLE_FIELDS and value <= 0:
            warnings.append(f"{field}:nonpositive_not_comparable")
            field_statuses[field] = {
                "status": "not_applicable",
                "reason": "nonpositive_pe",
                "as_of": field_date,
                "provider": field_provider,
                "symbol": field_symbol,
            }
            continue
        if field in {
            "pb",
            "ps_ttm",
            "market_cap_cny",
            "market_cap_usd",
        } and value <= 0:
            warnings.append(f"{field}:nonpositive_invalid")
            continue
        values[field] = value
        field_providers[field] = field_provider
        field_symbols[field] = field_symbol

    raw_statuses = raw.get("field_statuses")
    if isinstance(raw_statuses, Mapping):
        for field, raw_status in raw_statuses.items():
            if field not in NOT_APPLICABLE_FIELDS or not isinstance(raw_status, Mapping):
                continue
            if raw_status.get("status") != "not_applicable":
                continue
            status_provider = str(raw_status.get("provider") or source).strip().lower()
            status_symbol = str(
                raw_status.get("symbol") or raw.get("symbol") or ""
            ).strip()[:40]
            if status_provider not in PROVIDER_META or not status_symbol:
                warnings.append(f"{field}:invalid_status_provenance")
                continue
            assert_provider_allowed(
                PROVIDER_META[status_provider]["canonical"],
                context=f"company financial refresh status field={field}",
            )
            field_date, date_error = _valid_field_date(
                field,
                raw_status.get("as_of"),
                reference_date,
            )
            if date_error:
                warnings.append(f"{field}:{date_error}")
                continue
            if field in values:
                warnings.append(f"{field}:value_and_status_conflict")
                values.pop(field, None)
            field_statuses[field] = {
                "status": "not_applicable",
                "reason": "nonpositive_pe",
                "as_of": str(field_date),
                "provider": status_provider,
                "symbol": status_symbol,
            }

    field_as_of = {
        field: str((field_as_of_raw or {}).get(field) or "")
        for field in values
        if isinstance(field_as_of_raw, Mapping)
    }
    field_methods = {
        field: _sanitize_method((field_methods_raw or {}).get(field))
        for field in values
        if isinstance(field_methods_raw, Mapping)
    }
    for field in values:
        field_methods.setdefault(field, {"extraction_method": "web_fetch"})

    currency = str(raw.get("per_share_currency") or raw.get("currency") or "").upper()[:12]
    snapshot = {
        "status": "success" if values or field_statuses else "no_data",
        "provider": source,
        "canonical_provider": canonical_provider,
        "symbol": str(raw.get("symbol") or "")[:40],
        "currency": str(raw.get("currency") or "").upper()[:12] or None,
        "per_share_currency": currency or None,
        "trade_date": str(raw.get("trade_date") or "")[:32] or None,
        "financial_metrics_as_of": str(
            raw.get("financial_metrics_as_of") or raw.get("financials_as_of") or ""
        )[:32]
        or None,
        "values": values,
        "field_as_of": field_as_of,
        "field_methods": field_methods,
        "field_providers": field_providers,
        "field_symbols": field_symbols,
        "field_statuses": field_statuses,
        "warnings": warnings,
        "errors": [
            str(x)[:240]
            for x in (
                raw.get("errors")
                if isinstance(raw.get("errors"), (list, tuple))
                else [raw.get("errors")]
                if raw.get("errors")
                else []
            )[:8]
        ],
    }
    if raw.get("error"):
        snapshot["errors"].append(str(raw["error"])[:240])
    # 兼容 company 的人民币主口径聚合列，不作为独立 DP 重复写入。
    market_cap_value = _finite(raw.get("market_cap_value"))
    if market_cap_value is not None:
        snapshot["market_cap_value"] = market_cap_value
        snapshot["market_cap_unit"] = str(raw.get("market_cap_unit") or "")[:40] or None
    return snapshot


def _default_fetcher(*, ticker: str, yf_symbol: str, fx: Mapping[str, float]) -> Mapping[str, Any]:
    return fetch_company_market_snapshot(ticker, yf_symbol=yf_symbol, fx=dict(fx))


def _status_summary(entries: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(str(entry.get("status") or "unknown") for entry in entries).items()))


def _manifest_summary(entries: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(entries)
    unique_fetches = {
        str(entry["fetch_key"])
        for entry in rows
        if entry.get("fetch_key")
        and entry.get("status") in {"planned", "success", "no_data", "provider_error"}
    }
    provider_counts: Counter[str] = Counter()
    field_provider_counts: Counter[str] = Counter()
    blocker_counts: Counter[str] = Counter()
    field_company_counts: Counter[str] = Counter()
    field_issuer_counts: Counter[str] = Counter()
    evidence_companies: set[int] = set()
    for entry in rows:
        blocker_counts.update(str(reason) for reason in entry.get("reasons") or [])
        if entry.get("status") != "success":
            continue
        snapshot = entry.get("snapshot") or {}
        provider_counts.update([str(snapshot.get("provider") or "unknown")])
        values = snapshot.get("values") or {}
        per_field_providers = snapshot.get("field_providers") or {}
        if isinstance(per_field_providers, Mapping):
            field_provider_counts.update(
                str(per_field_providers.get(field) or snapshot.get("provider") or "unknown")
                for field in values
            )
        field_company_counts.update(str(field) for field in values)
        if entry.get("writes_data_points"):
            evidence_companies.add(int(entry["company_id"]))
            field_issuer_counts.update(str(field) for field in values)
    return {
        "total_companies": len(rows),
        "unique_fetches": len(unique_fetches),
        "evidence_company_count": len(evidence_companies),
        "status_counts": _status_summary(rows),
        "provider_company_counts": dict(sorted(provider_counts.items())),
        "field_provider_value_counts": dict(sorted(field_provider_counts.items())),
        "blocked_reason_counts": dict(sorted(blocker_counts.items())),
        "field_company_counts": dict(sorted(field_company_counts.items())),
        "field_issuer_counts": dict(sorted(field_issuer_counts.items())),
    }


def _annotate_evidence_companies(entries: Iterable[dict[str, Any]]) -> None:
    """Choose one stable evidence owner per normalized ticker.

    Duplicate bilingual/alias company rows still receive current aggregate values,
    but must not inflate research fact counts for the same issuer and provider row.
    """
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        if entry.get("fetch_key") and entry.get("status") == "planned":
            groups[str(entry["fetch_key"])].append(entry)
    for group in groups.values():
        evidence_candidates = [
            entry for entry in group if entry.get("canonical_industry_id") is not None
        ]
        evidence_company_id = (
            min(int(entry["company_id"]) for entry in evidence_candidates)
            if evidence_candidates else None
        )
        for entry in group:
            entry["evidence_company_id"] = evidence_company_id
            entry["writes_data_points"] = (
                evidence_company_id is not None
                and int(entry["company_id"]) == evidence_company_id
            )


def _compute_run_id(manifest: Mapping[str, Any]) -> str:
    payload = dict(manifest)
    payload.pop("run_id", None)
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:20]


def _finalize_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    entries = manifest["companies"]
    manifest["summary"] = _manifest_summary(entries)
    manifest["run_id"] = _compute_run_id(manifest)
    return manifest


def build_refresh_manifest(
    db_path: Path,
    *,
    fetch: bool = False,
    fetcher: SnapshotFetcher | None = None,
    fx_provider: FxProvider | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """只读构建全公司 manifest；``fetch=False`` 时绝不调用 provider。"""
    db_path = db_path.resolve()
    conn = _readonly_connect(db_path)
    try:
        entries = load_company_plan(conn)
    finally:
        conn.close()

    _annotate_evidence_companies(entries)

    manifest_generated_at = generated_at or _utc_now()
    reference_date = _manifest_reference_date(manifest_generated_at)
    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "mode": "fetch" if fetch else "dry_run",
        "generated_at": manifest_generated_at,
        "database_name": db_path.name,
        "universe_sha256": universe_sha256(entries),
        "companies": entries,
    }
    if not fetch:
        return _finalize_manifest(manifest)

    actual_fetcher = fetcher or _default_fetcher
    actual_fx_provider = fx_provider or fetch_live_fx_rates
    fx = {
        str(currency).upper(): value
        for currency, raw_value in actual_fx_provider().items()
        if (value := _finite(raw_value)) is not None and value > 0
    }
    fx.setdefault("CNY", 1.0)
    manifest["fx_rates_to_cny"] = fx
    manifest["fx_warnings"] = (
        [] if fx.get("USD") else ["USD/CNY 实时报价不可得；不生成依赖该汇率的人民币/美元换算值"]
    )

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        if entry["status"] == "planned":
            groups[str(entry["fetch_key"])].append(entry)

    for group in groups.values():
        representative = group[0]
        try:
            raw = actual_fetcher(
                ticker=str(representative["ticker"]),
                yf_symbol=str(representative["yf_symbol"]),
                fx=fx,
            )
            snapshot = sanitize_snapshot(raw, reference_date=reference_date)
        except Exception as exc:
            snapshot = {
                "status": "provider_error",
                "error": f"{type(exc).__name__}: {str(exc)[:200]}",
                "errors": [],
            }
        for entry in group:
            entry["status"] = snapshot["status"]
            entry["snapshot"] = snapshot
    return _finalize_manifest(manifest)


def write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{_compute_run_id(manifest)}.tmp")
    try:
        temp_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("refresh manifest 顶层必须是 object")
    return payload


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ValueError("refresh manifest schema_version 不匹配")
    if manifest.get("mode") != "fetch":
        raise ValueError("只有 fetch manifest 可以应用；dry-run 不能写库")
    manifest_date = _manifest_reference_date(manifest.get("generated_at"))
    current_date = datetime.now(LOCAL_TIMEZONE).date()
    if manifest_date > current_date:
        raise ValueError("refresh manifest generated_at 位于未来")
    # Apply-time freshness is authoritative: a manifest that was valid when
    # fetched cannot promote observations after they have aged out in cache.
    reference_date = max(manifest_date, current_date)
    companies = manifest.get("companies")
    if not isinstance(companies, list) or not companies:
        raise ValueError("refresh manifest companies 必须是非空数组")
    if universe_sha256(companies) != manifest.get("universe_sha256"):
        raise ValueError("refresh manifest company 全集哈希校验失败")
    if manifest.get("run_id") != _compute_run_id(manifest):
        raise ValueError("refresh manifest run_id 校验失败")
    fx_rates = manifest.get("fx_rates_to_cny")
    if not isinstance(fx_rates, Mapping) or (_finite(fx_rates.get("CNY")) or 0) != 1:
        raise ValueError("refresh manifest 缺少有效 FX 快照基准")
    ids = [int(entry.get("company_id")) for entry in companies if isinstance(entry, Mapping)]
    if len(ids) != len(companies) or len(ids) != len(set(ids)):
        raise ValueError("refresh manifest company_id 缺失或重复")
    if any(entry.get("status") == "planned" for entry in companies):
        raise ValueError("refresh manifest 抓取尚未完成，仍存在 planned company")
    summary = manifest.get("summary") or {}
    if int(summary.get("total_companies") or -1) != len(companies):
        raise ValueError("refresh manifest 未覆盖完整 company 清单")
    if summary.get("status_counts") != _status_summary(companies):
        raise ValueError("refresh manifest status_counts 与明细不一致")
    unique_fetches = {
        str(entry["fetch_key"])
        for entry in companies
        if entry.get("fetch_key")
        and entry.get("status") in {"planned", "success", "no_data", "provider_error"}
    }
    if int(summary.get("unique_fetches") or -1) != len(unique_fetches):
        raise ValueError("refresh manifest unique_fetches 与明细不一致")

    evidence_groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for entry in companies:
        industry_ids = [int(x) for x in entry.get("industry_ids") or []]
        expected_industry_id = min(industry_ids) if industry_ids else None
        if entry.get("canonical_industry_id") != expected_industry_id:
            raise ValueError(
                f"company_id={entry['company_id']} canonical_industry_id 不一致"
            )
        if entry.get("status") != "success":
            continue
        identity = fetch_identity(str(entry.get("ticker") or ""))
        if not identity or entry.get("fetch_key") != identity["fetch_key"]:
            raise ValueError(f"company_id={entry['company_id']} fetch identity 不一致")
        evidence_groups[str(entry["fetch_key"])].append(entry)
        snapshot = entry.get("snapshot")
        if not isinstance(snapshot, Mapping):
            raise ValueError(f"company_id={entry['company_id']} success 但缺 snapshot")
        if snapshot.get("status") != "success" or not isinstance(snapshot.get("values"), Mapping):
            raise ValueError(f"company_id={entry['company_id']} snapshot 状态或 values 非法")
        _validate_snapshot_identity(entry, snapshot)
        clean = sanitize_snapshot(
            {
                "source": snapshot.get("provider"),
                "symbol": snapshot.get("symbol"),
                "currency": snapshot.get("currency"),
                "per_share_currency": snapshot.get("per_share_currency"),
                "trade_date": snapshot.get("trade_date"),
                "financial_metrics_as_of": snapshot.get("financial_metrics_as_of"),
                "field_as_of": snapshot.get("field_as_of"),
                "field_methods": snapshot.get("field_methods"),
                "field_providers": snapshot.get("field_providers"),
                "field_symbols": snapshot.get("field_symbols"),
                "field_statuses": snapshot.get("field_statuses"),
                **dict(snapshot.get("values") or {}),
            },
            reference_date=reference_date,
        )
        if clean["status"] != "success":
            raise ValueError(f"company_id={entry['company_id']} snapshot 无有效数值")
        if clean["values"] != dict(snapshot["values"]):
            raise ValueError(f"company_id={entry['company_id']} snapshot 数值未通过严格清洗")
        if clean["field_methods"] != dict(snapshot.get("field_methods") or {}):
            raise ValueError(f"company_id={entry['company_id']} field_methods 未通过严格清洗")
        if clean["field_providers"] != dict(snapshot.get("field_providers") or {}):
            raise ValueError(f"company_id={entry['company_id']} field_providers 未通过严格清洗")
        if clean["field_symbols"] != dict(snapshot.get("field_symbols") or {}):
            raise ValueError(f"company_id={entry['company_id']} field_symbols 未通过严格清洗")
        if clean["field_as_of"] != dict(snapshot.get("field_as_of") or {}):
            raise ValueError(f"company_id={entry['company_id']} field_as_of 未通过严格清洗")
        if clean["field_statuses"] != dict(snapshot.get("field_statuses") or {}):
            raise ValueError(f"company_id={entry['company_id']} field_statuses 未通过严格清洗")
        if (FINANCIAL_FIELDS & {"eps_ttm", "bps_mrq"} & clean["values"].keys()) and not clean.get(
            "per_share_currency"
        ):
            raise ValueError(f"company_id={entry['company_id']} EPS/BPS 缺少每股币种")
        if set(clean["field_as_of"]) != set(clean["values"]):
            raise ValueError(f"company_id={entry['company_id']} 每个数值必须有独立 as_of")
        if any(not _is_iso_date(value) for value in clean["field_as_of"].values()):
            raise ValueError(f"company_id={entry['company_id']} field_as_of 必须是 ISO 日期")
        status_fields = set(clean["field_statuses"])
        if status_fields - NOT_APPLICABLE_FIELDS or status_fields & set(clean["values"]):
            raise ValueError(f"company_id={entry['company_id']} not_applicable 字段非法")
        for field, method in clean["field_methods"].items():
            if not method.get("api_fields"):
                raise ValueError(f"company_id={entry['company_id']} {field} 缺少 provider 字段")
            if method.get("extraction_method") == "inferred" and not method.get("formula"):
                raise ValueError(f"company_id={entry['company_id']} {field} 推导值缺少公式")

    for fetch_key, group in evidence_groups.items():
        evidence_candidates = [
            entry for entry in group if entry.get("canonical_industry_id") is not None
        ]
        evidence_company_id = (
            min(int(entry["company_id"]) for entry in evidence_candidates)
            if evidence_candidates else None
        )
        for entry in group:
            if entry.get("evidence_company_id") != evidence_company_id:
                raise ValueError(f"{fetch_key} evidence_company_id 不一致")
            expected_writer = (
                evidence_company_id is not None
                and int(entry["company_id"]) == evidence_company_id
            )
            if entry.get("writes_data_points") is not expected_writer:
                raise ValueError(f"{fetch_key} writes_data_points 不一致")
    if summary != _manifest_summary(companies):
        raise ValueError("refresh manifest summary 与明细不一致")


def _company_columns(conn: sqlite3.Connection) -> set[str]:
    return {str(row[1]) for row in conn.execute("PRAGMA table_info(company)")}


def _current_universe(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return load_company_plan(conn)


def _source_columns(conn: sqlite3.Connection) -> set[str]:
    return {str(row[1]) for row in conn.execute("PRAGMA table_info(source)")}


def _get_or_create_source(
    conn: sqlite3.Connection,
    *,
    provider: str,
    run_id: str,
    generated_at: str,
) -> int:
    meta = PROVIDER_META[provider]
    canonical = str(meta["canonical"])
    assert_provider_allowed(canonical, context="company financial refresh source")
    title = f"{meta['title']} · run {run_id}"
    row = conn.execute(
        "SELECT id FROM source WHERE title=? AND fetch_method=?",
        (title, canonical),
    ).fetchone()
    if row:
        return int(row[0])

    available = _source_columns(conn)
    payload = {
        "title": title,
        "source_type": "三方数据",
        "publisher": meta["publisher"],
        "publish_date": generated_at[:10],
        "quality_tier": meta["quality_tier"],
        "is_forward_looking": 0,
        "value_layer": "公司专项",
        "fetch_method": canonical,
        "source_credibility": "whitelisted",
        "language": meta["language"],
        "is_primary_source": 0,
        "source_subtype": "financial_database",
        "url": meta["url"],
        "source_url": meta["url"],
        "domain": meta["domain"],
        "fetch_timestamp": generated_at,
        "note": f"统一公司财务刷新 manifest run_id={run_id}",
    }
    columns = [name for name in payload if name in available]
    placeholders = ",".join("?" for _ in columns)
    sql = (
        f"INSERT INTO source ({','.join(columns)}) "
        f"VALUES ({placeholders})"
    )
    return int(conn.execute(sql, tuple(payload[name] for name in columns)).lastrowid)


def _entry_snapshot(entry: Mapping[str, Any], *, reference_date: date) -> dict[str, Any]:
    snapshot = dict(entry.get("snapshot") or {})
    # 再清洗一次，避免应用被手工篡改的 NaN/Infinity/未知字段。
    raw = {
        "source": snapshot.get("provider"),
        "symbol": snapshot.get("symbol"),
        "currency": snapshot.get("currency"),
        "per_share_currency": snapshot.get("per_share_currency"),
        "trade_date": snapshot.get("trade_date"),
        "financial_metrics_as_of": snapshot.get("financial_metrics_as_of"),
        "field_as_of": snapshot.get("field_as_of"),
        "field_methods": snapshot.get("field_methods"),
        "field_providers": snapshot.get("field_providers"),
        "field_symbols": snapshot.get("field_symbols"),
        "field_statuses": snapshot.get("field_statuses"),
        "market_cap_value": snapshot.get("market_cap_value"),
        "market_cap_unit": snapshot.get("market_cap_unit"),
        **dict(snapshot.get("values") or {}),
    }
    return sanitize_snapshot(raw, reference_date=reference_date)


def _source_excerpt(
    *,
    provider: str,
    symbol: str,
    field: str,
    value: float,
    as_of: str,
    method: Mapping[str, Any],
) -> str:
    fields = ",".join(str(x) for x in method.get("api_fields") or [])
    parts = [
        f"provider={PROVIDER_META[provider]['canonical']}",
        f"symbol={symbol}",
        f"field={field}",
        f"value={value}",
        f"as_of={as_of}",
    ]
    if fields:
        parts.append(f"api_fields={fields}")
    if method.get("formula"):
        parts.append(f"formula={method['formula']}")
    if method.get("basis"):
        parts.append(f"basis={method['basis']}")
    if method.get("inputs"):
        parts.append(
            "inputs="
            + json.dumps(method["inputs"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
    return "; ".join(parts)[:1000]


def _latest_field_as_of(
    conn: sqlite3.Connection,
    *,
    company_id: int,
    metric: str,
    aggregate_as_of: Any,
    aggregate_value: Any,
) -> str | None:
    """Resolve a field-specific lower bound from governed facts then aggregate."""
    rows = conn.execute(
        """SELECT as_of_date FROM industry_data_point
           WHERE company_id=? AND metric=? AND as_of_date IS NOT NULL
           ORDER BY as_of_date DESC""",
        (company_id, metric),
    ).fetchall()
    for row in rows:
        candidate = str(row[0] or "")
        if _is_iso_date(candidate):
            return candidate
    fallback = str(aggregate_as_of or "")
    if aggregate_value is not None and _is_iso_date(fallback):
        return fallback
    return None


def _find_provider_data_point(
    conn: sqlite3.Connection,
    *,
    industry_id: int,
    company_id: int,
    metric: str,
    as_of_date: str,
    canonical_provider: str,
) -> sqlite3.Row | None:
    rows = conn.execute(
        """SELECT dp.*
           FROM industry_data_point AS dp
           JOIN source AS s ON s.id=dp.source_id
           WHERE dp.industry_id=? AND dp.company_id=? AND dp.metric=?
             AND dp.as_of_date=? AND s.fetch_method=?
           ORDER BY dp.id""",
        (industry_id, company_id, metric, as_of_date, canonical_provider),
    ).fetchall()
    if len(rows) > 1:
        raise RuntimeError(
            "已存在同 provider/company/industry/metric/as_of 重复数据点，"
            f"拒绝继续膨胀：company_id={company_id} metric={metric} as_of={as_of_date}"
        )
    return rows[0] if rows else None


def _revision_note(existing: sqlite3.Row, item: Mapping[str, Any], *, revised_at: str) -> str:
    audit = {
        "kind": "company_financial_value_revision",
        "revised_at": revised_at,
        "prior": {
            "value_num": existing["value_num"],
            "unit": existing["unit"],
            "source_id": existing["source_id"],
            "source_excerpt": existing["source_excerpt"],
            "extraction_method": existing["extraction_method"],
            "last_verified_at": existing["last_verified_at"],
        },
        "replacement": {
            "value_num": item["value_num"],
            "unit": item["unit"],
            "source_id": item["source_id"],
            "source_excerpt": item["source_excerpt"],
            "extraction_method": item["extraction_method"],
        },
    }
    prefix = str(existing["note"] or "").rstrip()
    current_note = str(item.get("note") or "").strip()
    parts = [part for part in (prefix, "REVISION_JSON=" + json.dumps(
        audit, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ), "CURRENT_NOTE=" + current_note if current_note else "") if part]
    return "\n".join(parts)


def _reconcile_data_point(
    conn: sqlite3.Connection,
    item: Mapping[str, Any],
    *,
    canonical_provider: str,
    verified_date: str,
) -> str:
    """Return ``insert``, ``unchanged`` or ``revised`` without fact inflation."""
    existing = _find_provider_data_point(
        conn,
        industry_id=int(item["industry_id"]),
        company_id=int(item["company_id"]),
        metric=str(item["metric"]),
        as_of_date=str(item["as_of_date"]),
        canonical_provider=canonical_provider,
    )
    if existing is None:
        return "insert"
    old_value = _finite(existing["value_num"])
    new_value = _finite(item["value_num"])
    same_value = (
        old_value is not None
        and new_value is not None
        and math.isclose(old_value, new_value, rel_tol=1e-12, abs_tol=1e-12)
    )
    if same_value and str(existing["unit"] or "") == str(item["unit"] or ""):
        previous_verified = str(existing["last_verified_at"] or "")
        conn.execute(
            "UPDATE industry_data_point SET last_verified_at=? WHERE id=?",
            (max(previous_verified, verified_date), int(existing["id"])),
        )
        return "unchanged"
    note = _revision_note(existing, item, revised_at=verified_date)
    conn.execute(
        """UPDATE industry_data_point
           SET value_num=?, value_text=NULL, unit=?, source_id=?, source_excerpt=?,
               note=?, extraction_method=?, last_verified_at=?
           WHERE id=?""",
        (
            float(item["value_num"]),
            str(item["unit"]),
            int(item["source_id"]),
            str(item["source_excerpt"]),
            note,
            str(item["extraction_method"]),
            verified_date,
            int(existing["id"]),
        ),
    )
    return "revised"


def apply_refresh_manifest(
    db_path: Path,
    manifest: Mapping[str, Any],
    *,
    confirm_live: bool = False,
    financial_db_path: Path | None = None,
    write_legacy_company_aggregate: bool = False,
) -> dict[str, Any]:
    """不联网，默认只把逐字段事实写入 ``financial.db``。

    ``write_legacy_company_aggregate`` 仅供隔离测试和历史迁移；live 任务禁止启用，
    防止随时变化的供应商快照重新进入 ``research.db``。
    """
    validate_manifest(manifest)
    db_path = db_path.resolve()
    if db_path == DEFAULT_DB.resolve() and not confirm_live:
        raise PermissionError("应用 live research.db 必须显式 confirm_live=True")
    if db_path == DEFAULT_DB.resolve() and write_legacy_company_aggregate:
        raise PermissionError("live 刷新禁止更新 research.db.company 的旧财务聚合列")

    financial_db_path = (
        Path(financial_db_path).resolve()
        if financial_db_path is not None
        else (DEFAULT_FINANCIAL_DB.resolve() if db_path == DEFAULT_DB.resolve() else db_path.with_name("financial.db"))
    )
    if financial_db_path == DEFAULT_FINANCIAL_DB.resolve() and db_path != DEFAULT_DB.resolve():
        raise PermissionError("临时 research.db 不得隐式写入 live financial.db")
    initialize_financial_database(financial_db_path)

    conn = db_writer.get_db(db_path)
    try:
        conn.execute("ATTACH DATABASE ? AS financial", (str(financial_db_path),))
        current = _current_universe(conn)
        if universe_sha256(current) != manifest.get("universe_sha256"):
            raise RuntimeError("company 全集在 fetch 后发生变化，拒绝应用过期 manifest")
        current_ids = {int(x["company_id"]) for x in current}
        manifest_ids = {int(x["company_id"]) for x in manifest["companies"]}
        if current_ids != manifest_ids:
            raise RuntimeError("manifest 未覆盖目标库当前全部 company")

        columns = _company_columns(conn)
        missing = sorted(REQUIRED_COMPANY_COLUMNS - columns)
        if missing:
            raise RuntimeError(
                "目标库缺少公司刷新前置字段（含 013_company_financial_metrics）："
                + ", ".join(missing)
            )

        generated_at = str(manifest["generated_at"])
        manifest_date = _manifest_reference_date(generated_at)
        reference_date = max(
            manifest_date,
            datetime.now(LOCAL_TIMEZONE).date(),
        )
        verified_date = manifest_date.isoformat()
        run_id = str(manifest["run_id"])
        source_ids: dict[str, int] = {}
        company_updates = 0
        financial_observations_upserted = 0
        financial_observations_inserted = 0
        financial_observations_revised = 0
        financial_observations_unchanged = 0
        financial_not_applicable_upserted = 0
        skipped_older_fields = 0
        cleared_nonpositive_pe = 0

        conn.execute("BEGIN IMMEDIATE")
        for entry in manifest["companies"]:
            if entry.get("status") != "success":
                continue
            company_id = int(entry["company_id"])
            industry_id = (
                int(entry["canonical_industry_id"])
                if entry.get("canonical_industry_id") is not None else None
            )
            snapshot = _entry_snapshot(entry, reference_date=reference_date)
            if snapshot["status"] != "success":
                raise RuntimeError(f"company_id={company_id} snapshot 应用前校验失败")
            _validate_snapshot_identity(entry, snapshot)
            provider = str(snapshot["provider"])
            values = dict(snapshot["values"])
            field_providers = dict(snapshot.get("field_providers") or {})
            field_symbols = dict(snapshot.get("field_symbols") or {})
            field_statuses = dict(snapshot.get("field_statuses") or {})
            current_company = conn.execute(
                "SELECT * FROM company WHERE id=?",
                (company_id,),
            ).fetchone()
            if current_company is None:
                raise RuntimeError(f"company_id={company_id} 在应用期间消失")

            financial_security_id = upsert_financial_security(
                conn,
                research_company_id=company_id,
                canonical_name=str(current_company["name"]),
                ticker=str(_row_value(current_company, "ticker") or "") or None,
                market=str(_row_value(current_company, "market") or "") or None,
                listing_status=str(_row_value(current_company, "listing_status") or "") or None,
                reporting_currency=str(_row_value(current_company, "per_share_currency") or snapshot.get("per_share_currency") or "") or None,
                schema="financial",
            )

            accepted_values: dict[str, float] = {}
            accepted_statuses: dict[str, Mapping[str, Any]] = {}
            for field, value in values.items():
                metric = DP_FIELD_SPECS[field][0]
                aggregate_as_of = (
                    current_company["valuation_as_of"]
                    if field in MARKET_FIELDS
                    else current_company["financial_metrics_as_of"]
                )
                lower_bound = _latest_field_as_of(
                    conn,
                    company_id=company_id,
                    metric=metric,
                    aggregate_as_of=aggregate_as_of,
                    aggregate_value=current_company[field],
                )
                incoming_as_of = str(snapshot["field_as_of"][field])
                if lower_bound and incoming_as_of < lower_bound:
                    skipped_older_fields += 1
                    continue
                accepted_values[field] = float(value)
            for field, status in field_statuses.items():
                metric = DP_FIELD_SPECS[field][0]
                lower_bound = _latest_field_as_of(
                    conn,
                    company_id=company_id,
                    metric=metric,
                    aggregate_as_of=current_company["valuation_as_of"],
                    aggregate_value=current_company[field],
                )
                incoming_as_of = str(status["as_of"])
                if lower_bound and incoming_as_of < lower_bound:
                    skipped_older_fields += 1
                    continue
                accepted_statuses[field] = status

            if write_legacy_company_aggregate:
                needed_providers = {
                    str(field_providers.get(field) or provider)
                    for field in accepted_values
                }
                needed_providers.update(
                    str(status.get("provider") or provider)
                    for status in accepted_statuses.values()
                )
                for needed_provider in sorted(needed_providers):
                    if needed_provider not in source_ids:
                        source_ids[needed_provider] = _get_or_create_source(
                            conn,
                            provider=needed_provider,
                            run_id=run_id,
                            generated_at=generated_at,
                        )

            def aggregate_source_id(fields: Iterable[str]) -> int | None:
                candidates = [
                    str(field_providers.get(field) or provider)
                    for field in fields
                    if field in accepted_values
                ]
                if not candidates:
                    return None
                chosen = provider if provider in candidates else candidates[0]
                return source_ids.get(chosen)

            market_source_id = aggregate_source_id(MARKET_FIELDS)
            financial_source_id = aggregate_source_id(FINANCIAL_FIELDS)
            if market_source_id is None and accepted_statuses:
                status_provider = str(
                    next(iter(accepted_statuses.values())).get("provider") or provider
                )
                market_source_id = source_ids.get(status_provider)
            updates: dict[str, Any] = {
                field: value
                for field, value in accepted_values.items()
                if field in columns
            }
            for field in accepted_statuses:
                updates[field] = None
                if current_company[field] is not None:
                    cleared_nonpositive_pe += 1

            market_success = bool(
                (MARKET_FIELDS & accepted_values.keys()) or accepted_statuses
            )
            financial_success = bool(FINANCIAL_FIELDS & accepted_values.keys())

            # Legacy negative PE is never comparable.  When any dated market
            # observation is accepted, clear such values even if this provider
            # omitted PE, so a refreshed shared source/date cannot coexist with
            # a stale negative multiple.
            if market_success:
                for pe_field in NOT_APPLICABLE_FIELDS:
                    current_pe = _finite(current_company[pe_field])
                    if current_pe is not None and current_pe <= 0 and pe_field not in accepted_values:
                        if pe_field not in updates:
                            cleared_nonpositive_pe += 1
                        updates[pe_field] = None
            if market_success:
                market_dates = [
                    snapshot.get("field_as_of", {}).get(field)
                    for field in MARKET_FIELDS & accepted_values.keys()
                ]
                market_dates.extend(
                    str(status["as_of"]) for status in accepted_statuses.values()
                )
                incoming_market_as_of = max(
                    value for value in market_dates if _is_iso_date(value)
                )
                existing_market_as_of = str(current_company["valuation_as_of"] or "")
                updates["valuation_as_of"] = max(existing_market_as_of, incoming_market_as_of)
                if not existing_market_as_of or incoming_market_as_of >= existing_market_as_of:
                    updates["valuation_source_id"] = market_source_id
                if accepted_values.get("market_cap_cny") is not None:
                    updates["market_cap_value"] = accepted_values["market_cap_cny"]
                    updates["market_cap_unit"] = "亿元人民币"
            if financial_success:
                financial_dates = [
                    snapshot.get("field_as_of", {}).get(field)
                    for field in FINANCIAL_FIELDS & accepted_values.keys()
                ]
                incoming_financial_as_of = max(
                    value for value in financial_dates if _is_iso_date(value)
                )
                existing_financial_as_of = str(
                    current_company["financial_metrics_as_of"] or ""
                )
                updates["financial_metrics_as_of"] = max(
                    existing_financial_as_of,
                    incoming_financial_as_of,
                )
                if (
                    not existing_financial_as_of
                    or incoming_financial_as_of >= existing_financial_as_of
                ):
                    updates["financial_metrics_source_id"] = financial_source_id
            if (
                {"eps_ttm", "bps_mrq"} & accepted_values.keys()
                and snapshot.get("per_share_currency")
            ):
                updates["per_share_currency"] = snapshot["per_share_currency"]

            if updates and write_legacy_company_aggregate:
                assignments = ", ".join(f'"{key}"=?' for key in updates)
                conn.execute(
                    f"UPDATE company SET {assignments} WHERE id=?",
                    (*updates.values(), company_id),
                )
                company_updates += 1

            # 每个字段单独保留真实 provider、symbol、时点和转换公式。结构化 API
            # 数据只进入 financial.db，不再作为普通行业证据点重复入库。
            for field, (metric, fixed_unit, fact_type) in FINANCIAL_FIELD_SPECS.items():
                if field not in accepted_values:
                    continue
                field_provider = str(field_providers.get(field) or provider)
                field_as_of = str(snapshot["field_as_of"][field])
                method = dict(snapshot.get("field_methods", {}).get(field) or {})
                formula = str(method.get("formula") or "").strip()
                symbol = str(
                    field_symbols.get(field)
                    or snapshot.get("symbol")
                    or entry.get("normalized_symbol")
                    or ""
                )
                raw_features = list(method.get("api_fields") or [])
                raw_feature = ",".join(str(x) for x in raw_features) or field
                source_snapshot_id = record_financial_source(
                    conn,
                    provider=field_provider,
                    source_channel="structured_api",
                    source_ref=f"{field_provider}:{symbol}:{raw_feature}:{field_as_of}",
                    title=str(PROVIDER_META[field_provider]["title"]),
                    publisher=str(PROVIDER_META[field_provider]["publisher"]),
                    as_of_date=field_as_of,
                    fetched_at=generated_at,
                    metadata={
                        "refresh_run_id": run_id,
                        "symbol": symbol,
                        "field": field,
                        "basis": method.get("basis"),
                    },
                    schema="financial",
                )
                unit = fixed_unit or f"{snapshot.get('per_share_currency') or '原币'}/股"
                _, observation_status = upsert_financial_observation(
                    conn,
                    schema="financial",
                    return_status=True,
                    revision_reason=f"company_refresh_manifest:{run_id}",
                    security_id=financial_security_id,
                    metric_name=metric,
                    value_num=float(accepted_values[field]),
                    unit=unit,
                    currency=(snapshot.get("per_share_currency") if field in {"eps_ttm", "bps_mrq"} else "CNY" if field == "market_cap_cny" else "USD" if field == "market_cap_usd" else None),
                    period_end=field_as_of,
                    frequency="daily" if field in MARKET_FIELDS else "reporting_period",
                    fact_type=fact_type,
                    as_of_date=field_as_of,
                    provider=field_provider,
                    raw_feature_name=raw_feature,
                    source_snapshot_id=source_snapshot_id,
                    formula=formula or None,
                    input_refs=list((method.get("inputs") or {}).keys()),
                    legacy_ref=f"company-financial-refresh:{run_id}:{company_id}:{field}",
                )
                financial_observations_upserted += 1
                if observation_status == "inserted":
                    financial_observations_inserted += 1
                elif observation_status == "revised":
                    financial_observations_revised += 1
                else:
                    financial_observations_unchanged += 1

            for field, status in accepted_statuses.items():
                metric, fixed_unit, fact_type = FINANCIAL_FIELD_SPECS[field]
                field_provider = str(status.get("provider") or provider)
                symbol = str(status.get("symbol") or snapshot.get("symbol") or "")
                field_as_of = str(status["as_of"])
                source_snapshot_id = record_financial_source(
                    conn, provider=field_provider, source_channel="structured_api",
                    source_ref=f"{field_provider}:{symbol}:{field}:not_applicable:{field_as_of}",
                    title=str(PROVIDER_META[field_provider]["title"]),
                    publisher=str(PROVIDER_META[field_provider]["publisher"]),
                    as_of_date=field_as_of, fetched_at=generated_at,
                    metadata={"refresh_run_id": run_id, "status": dict(status)},
                    schema="financial",
                )
                _, observation_status = upsert_financial_observation(
                    conn, schema="financial", security_id=financial_security_id,
                    return_status=True, revision_reason=f"company_refresh_manifest:{run_id}",
                    metric_name=metric, value_text=str(status.get("reason") or "not_applicable"),
                    unit=fixed_unit or f"{snapshot.get('per_share_currency') or '原币'}/股",
                    period_end=field_as_of, frequency="daily", fact_type=fact_type,
                    as_of_date=field_as_of, provider=field_provider, raw_feature_name=field,
                    source_snapshot_id=source_snapshot_id, quality_status="not_applicable",
                    legacy_ref=f"company-financial-refresh:{run_id}:{company_id}:{field}:na",
                )
                financial_not_applicable_upserted += 1
                if observation_status == "inserted":
                    financial_observations_inserted += 1
                elif observation_status == "revised":
                    financial_observations_revised += 1
                else:
                    financial_observations_unchanged += 1

        violations = list(conn.execute("PRAGMA foreign_key_check"))
        if violations:
            raise RuntimeError(f"foreign_key_check 失败：{len(violations)} 条")
        financial_violations = list(conn.execute("PRAGMA financial.foreign_key_check"))
        if financial_violations:
            raise RuntimeError(f"financial.db foreign_key_check 失败：{len(financial_violations)} 条")
        conn.commit()
        return {
            "run_id": run_id,
            "company_updates": company_updates,
            "research_company_aggregate_written": bool(
                write_legacy_company_aggregate and company_updates
            ),
            "financial_observations_upserted": financial_observations_upserted,
            "financial_observations_inserted": financial_observations_inserted,
            "financial_observations_revised": financial_observations_revised,
            "financial_observations_unchanged": financial_observations_unchanged,
            "financial_not_applicable_upserted": financial_not_applicable_upserted,
            "data_points_inserted": 0,
            "data_points_revised": 0,
            "data_points_skipped_existing": 0,
            "fields_skipped_older_as_of": skipped_older_fields,
            "nonpositive_pe_cleared": cleared_nonpositive_pe,
            "sources": source_ids,
            "financial_db": str(financial_db_path),
            "status_counts": manifest["summary"]["status_counts"],
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _default_manifest_path(mode: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return ROOT / "cache" / f"company_financial_refresh_{mode}_{stamp}.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument(
        "--financial-db",
        type=Path,
        help="独立财务数据库；默认 live research.db 对应 data/financial.db，临时库对应同目录 financial.db。",
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true", help="只生成全公司计划（默认）")
    modes.add_argument("--fetch-only", action="store_true", help="联网抓取并生成 manifest，不写 DB")
    modes.add_argument("--apply-manifest", type=Path, help="应用已有 fetch manifest，不联网")
    parser.add_argument("--manifest", type=Path, help="dry-run/fetch-only 输出路径")
    parser.add_argument(
        "--confirm-live",
        action="store_true",
        help="允许 --apply-manifest 写入默认 live research.db；临时库不需要。",
    )
    args = parser.parse_args(argv)
    db_path = args.db.resolve()
    if not db_path.exists():
        parser.error(f"数据库不存在：{db_path}")

    if args.apply_manifest:
        manifest = load_manifest(args.apply_manifest.resolve())
        result = apply_refresh_manifest(
            db_path,
            manifest,
            confirm_live=args.confirm_live,
            financial_db_path=args.financial_db,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    fetch = bool(args.fetch_only)
    manifest = build_refresh_manifest(db_path, fetch=fetch)
    path = (args.manifest or _default_manifest_path("fetch" if fetch else "dry_run")).resolve()
    write_manifest(path, manifest)
    print(
        json.dumps(
            {
                "mode": manifest["mode"],
                "manifest": str(path),
                "run_id": manifest["run_id"],
                **manifest["summary"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
