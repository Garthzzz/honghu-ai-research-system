# -*- coding: utf-8 -*-
"""统一上市公司市场和财务快照。

A 股使用项目内网 Wind HTTP 代理为主源，Tushare 只对 Wind 当前快照的可填字段
逐项补缺；其他市场使用 Yahoo Finance/yfinance。每个合并字段保留实际 provider、
symbol、as_of 和计算方法，不能把合并快照伪装成单一来源。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

try:  # package import（unit tests / python -m）
    from .tushare_provider import (
        fetch_cashflow_latest,
        fetch_daily_basic_latest,
        fetch_fina_indicator_latest,
        fnum,
        ts_code_from_ticker,
        tushare_available,
    )
    from .wind_http_provider import fetch_current_market_financial_snapshot
except ImportError:  # script/legacy builder import
    from tushare_provider import (  # type: ignore
        fetch_cashflow_latest,
        fetch_daily_basic_latest,
        fetch_fina_indicator_latest,
        fnum,
        ts_code_from_ticker,
        tushare_available,
    )
    from wind_http_provider import fetch_current_market_financial_snapshot  # type: ignore


FALLBACK_FX_TO_CNY = {
    "CNY": 1.0,
    "USD": 6.7938,
    "HKD": 0.8690,
    "TWD": 0.2029,
    "JPY": 0.041817,
    "KRW": 0.00493,
    "EUR": 7.95,
    "SEK": 0.7240,
    "GBP": 9.24,
    "CHF": 8.50,
    "SGD": 5.30,
}

A_SHARE_SNAPSHOT_FIELDS = {
    "pe_ttm",
    "pe_forward",
    "pb",
    "ps_ttm",
    "ev_ebitda",
    "peg",
    "market_cap_cny",
    "market_cap_usd",
    "roe",
    "roa",
    "eps_ttm",
    "bps_mrq",
}

# Tushare 当前接口实际能补的字段。Wind 缺少 EV/EBITDA、PEG 或 forward PE 时
# 不为注定无法补齐的字段额外调用 Tushare。
TUSHARE_FILLABLE_FIELDS = {
    "pe_ttm",
    "pb",
    "ps_ttm",
    "market_cap_cny",
    "market_cap_usd",
    "roe",
    "roa",
    "eps_ttm",
    "bps_mrq",
}


def r2(value: Any) -> float | None:
    num = fnum(value)
    return round(num, 2) if num is not None else None


def _safe_yi(value: Any, fx: float, *, absolute: bool = False) -> float | None:
    num = fnum(value)
    if num is None:
        return None
    if absolute:
        num = abs(num)
    return round(num * fx / 1e8, 2)


def _iso_from_unix(value: Any) -> str:
    """把 yfinance 的 epoch 秒转换成 ISO 日期；不可用时返回空串。"""
    num = fnum(value)
    if num is None or num <= 0:
        return ""
    try:
        return datetime.fromtimestamp(num, tz=timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return ""


def _iso_date(value: Any, fallback: str = "") -> str:
    """Normalize provider dates without pretending an invalid date is current."""
    raw = str(value or "").strip()
    if not raw:
        return fallback
    if len(raw) == 8 and raw.isdigit():
        try:
            return datetime.strptime(raw, "%Y%m%d").date().isoformat()
        except ValueError:
            return fallback
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return fallback


def _ratio_value(numerator: Any, denominator: Any, *, digits: int = 4) -> float | None:
    n = fnum(numerator)
    d = fnum(denominator)
    if n is None or d in (None, 0):
        return None
    return round(n / d, digits)


def fetch_fx_rates(*, allow_fallback: bool = True) -> dict[str, float]:
    """Fetch currency-to-CNY rates.

    Legacy builders may opt into the dated fallback table. A real refresh should
    use ``allow_fallback=False`` so an unavailable FX quote becomes an explicit
    gap instead of silently presenting an old rate as current.
    """
    rates = dict(FALLBACK_FX_TO_CNY) if allow_fallback else {"CNY": 1.0}
    try:
        import yfinance as yf  # type: ignore

        for currency, symbol in {
            "USD": "USDCNY=X",
            "HKD": "HKDCNY=X",
            "TWD": "TWDCNY=X",
            "JPY": "JPYCNY=X",
            "KRW": "KRWCNY=X",
            "EUR": "EURCNY=X",
            "SEK": "SEKCNY=X",
            "GBP": "GBPCNY=X",
            "CHF": "CHFCNY=X",
            "SGD": "SGDCNY=X",
        }.items():
            try:
                info = yf.Ticker(symbol).get_info()
                value = fnum(info.get("regularMarketPrice") or info.get("previousClose"))
                if value:
                    rates[currency] = value
            except Exception:
                continue
    except Exception:
        pass
    return rates


def fetch_live_fx_rates() -> dict[str, float]:
    return fetch_fx_rates(allow_fallback=False)


def _from_tushare(ticker: str, fx: dict[str, float]) -> dict[str, Any] | None:
    if not tushare_available():
        return None
    ts_code = ts_code_from_ticker(ticker)
    if not ts_code:
        return None
    daily = fetch_daily_basic_latest(ts_code)
    if not daily:
        return None
    total_mv = fnum(daily.get("total_mv"))  # 万元
    price = fnum(daily.get("close"))
    pe_ttm = fnum(daily.get("pe_ttm"))
    pb = fnum(daily.get("pb"))
    usd_to_cny = fnum(fx.get("USD"))
    market_cap_cny_raw = total_mv / 10000 if total_mv is not None else None
    market_cap_cny = round(market_cap_cny_raw, 2) if market_cap_cny_raw is not None else None
    market_cap_usd_raw = (
        market_cap_cny_raw / usd_to_cny
        if market_cap_cny_raw is not None and usd_to_cny not in (None, 0)
        else None
    )
    market_cap_usd = round(market_cap_usd_raw, 2) if market_cap_usd_raw is not None else None
    fina = None
    cash = None
    try:
        fina = fetch_fina_indicator_latest(ts_code)
    except Exception as exc:
        fina = {"_error": f"{type(exc).__name__}: {str(exc)[:80]}"}
    try:
        cash = fetch_cashflow_latest(ts_code)
    except Exception as exc:
        cash = {"_error": f"{type(exc).__name__}: {str(exc)[:80]}"}
    ocf_cny = round(fnum(cash.get("n_cashflow_act")) / 1e8, 2) if cash and fnum(cash.get("n_cashflow_act")) is not None else None
    capex_cny = round(abs(fnum(cash.get("c_pay_acq_const_fiolta"))) / 1e8, 2) if cash and fnum(cash.get("c_pay_acq_const_fiolta")) is not None else None
    fina_as_of = _iso_date((fina or {}).get("end_date"))
    cash_as_of = _iso_date((cash or {}).get("end_date"))
    financial_as_of = fina_as_of
    reported_eps = fnum((fina or {}).get("eps"))
    reported_bps = fnum((fina or {}).get("bps"))

    # Tushare fina_indicator.eps 是报告期累计口径，不应把季度累计值直接冒充 TTM。
    # 优先使用同日 close/pe_ttm 得到与 PE_TTM 完全一致的 TTM EPS；只有年报期
    # 且无法推导时，才采用报告 EPS。BPS 则直接使用最近报告期 bps，缺失时由
    # 同日 close/pb 推导。
    market_observation_date = _iso_date(daily.get("trade_date"))
    eps_ttm = (
        _ratio_value(price, pe_ttm)
        if market_observation_date and fina_as_of and pe_ttm is not None and pe_ttm > 0
        else None
    )
    eps_method: dict[str, Any] | None = None
    eps_as_of = fina_as_of
    if eps_ttm is not None:
        eps_as_of = market_observation_date
        eps_method = {
            "extraction_method": "inferred",
            "formula": "Tushare daily_basic.close / daily_basic.pe_ttm",
            "basis": "TTM；由同一交易日 PE_TTM 反推，财务期以最近报告期为准",
            "api_fields": ["daily_basic.close", "daily_basic.pe_ttm"],
            "inputs": {
                "close": price,
                "pe_ttm": pe_ttm,
                "market_observation_date": market_observation_date,
                "financial_statement_as_of": fina_as_of,
            },
        }
    elif financial_as_of.endswith("-12-31") and reported_eps is not None:
        eps_ttm = r2(reported_eps)
        eps_as_of = financial_as_of
        eps_method = {
            "extraction_method": "web_fetch",
            "basis": "年度报告期 EPS；年末口径等同该年度 trailing twelve months",
            "api_fields": ["fina_indicator.eps"],
        }

    bps_mrq = r2(reported_bps)
    bps_current_basis_implied = (
        _ratio_value(price, pb)
        if market_observation_date and pb is not None and pb > 0
        else None
    )
    bps_method: dict[str, Any] | None = None
    bps_as_of = fina_as_of
    bps_basis_reconciliation: dict[str, Any]
    if bps_mrq is not None:
        relative_difference = (
            abs(bps_mrq - bps_current_basis_implied)
            / abs(bps_current_basis_implied)
            if bps_current_basis_implied not in (None, 0)
            else None
        )
        basis_mismatch = (
            relative_difference is not None and relative_difference > 0.03
        )
        bps_method = {
            "extraction_method": "web_fetch",
            "basis": (
                "最近报告期股本口径每股净资产；与交易日PB隐含当前股本口径差异超过3%，"
                "不可直接用该BPS复算当前PB"
                if basis_mismatch
                else "最近报告期每股净资产；与交易日PB隐含值在3%容差内"
            ),
            "api_fields": ["fina_indicator.bps"],
            "inputs": {
                "reported_bps": bps_mrq,
                "current_price": price,
                "current_pb": pb,
                "current_share_basis_bps_implied": bps_current_basis_implied,
                "relative_difference": relative_difference,
            },
        }
        bps_basis_reconciliation = {
            "status": (
                "reporting_period_share_basis_not_reconciled_to_market_pb"
                if basis_mismatch
                else "consistent_with_current_pb_within_3pct"
            ),
            "reported_bps": bps_mrq,
            "reported_bps_as_of": fina_as_of,
            "current_share_basis_bps_implied": bps_current_basis_implied,
            "current_market_as_of": market_observation_date,
            "relative_difference_pct": (
                round(relative_difference * 100.0, 4)
                if relative_difference is not None
                else None
            ),
            "direct_current_pb_recalculation_allowed": not basis_mismatch,
            "note": (
                "差异可能来自送转、拆并股、回购或报告期与交易日股本口径变化；"
                "保留接口原始BPS，不擅自复权。"
            ),
        }
    else:
        bps_mrq = bps_current_basis_implied if market_observation_date and fina_as_of else None
        if bps_mrq is not None:
            bps_method = {
                "extraction_method": "inferred",
                "formula": "Tushare daily_basic.close / daily_basic.pb",
                "basis": "由当前 PB 反推最近报告期每股净资产",
                "api_fields": ["daily_basic.close", "daily_basic.pb"],
                "inputs": {
                    "close": price,
                    "pb": pb,
                    "market_observation_date": market_observation_date,
                },
            }
        bps_basis_reconciliation = {
            "status": "reported_bps_missing_used_current_price_over_pb",
            "reported_bps": None,
            "reported_bps_as_of": fina_as_of,
            "current_share_basis_bps_implied": bps_current_basis_implied,
            "current_market_as_of": market_observation_date,
            "relative_difference_pct": None,
            "direct_current_pb_recalculation_allowed": True,
            "note": "报告BPS不可得，展示值由同一交易日价格/PB反推。",
        }

    market_as_of = market_observation_date
    field_methods: dict[str, dict[str, Any]] = {
        "pe_ttm": {
            "extraction_method": "web_fetch",
            "basis": "TTM",
            "api_fields": ["daily_basic.pe_ttm"],
        },
        "pb": {
            "extraction_method": "web_fetch",
            "basis": "交易日价格 / 最近报告期每股净资产",
            "api_fields": ["daily_basic.pb"],
        },
        "ps_ttm": {"extraction_method": "web_fetch", "api_fields": ["daily_basic.ps_ttm"]},
        "market_cap_cny": {
            "extraction_method": "inferred",
            "formula": "Tushare daily_basic.total_mv(万元) / 10000",
            "api_fields": ["daily_basic.total_mv"],
            "inputs": {"total_mv_wan_cny": total_mv},
        },
        "market_cap_usd": {
            "extraction_method": "inferred",
            "formula": "market_cap_cny_unrounded / yfinance USDCNY=X",
            "api_fields": ["daily_basic.total_mv", "yfinance USDCNY=X"],
            "inputs": {"market_cap_cny_yi": market_cap_cny_raw, "usd_to_cny": usd_to_cny},
        },
        "roe": {
            "extraction_method": "web_fetch",
            "basis": "Tushare fina_indicator 最近报告期口径；不可无条件视为 TTM",
            "api_fields": ["fina_indicator.roe"],
        },
        "roa": {
            "extraction_method": "web_fetch",
            "basis": "Tushare fina_indicator 最近报告期口径；不可无条件视为 TTM",
            "api_fields": ["fina_indicator.roa"],
        },
    }
    if eps_method:
        field_methods["eps_ttm"] = eps_method
    if bps_method:
        field_methods["bps_mrq"] = bps_method
    field_methods["bps_current_share_basis_implied"] = {
        "extraction_method": "inferred",
        "formula": "Tushare daily_basic.close / daily_basic.pb",
        "basis": "与当前交易日价格和PB一致的隐含当前股本口径；用于对账，不覆盖报告期BPS",
        "api_fields": ["daily_basic.close", "daily_basic.pb"],
        "inputs": {
            "close": price,
            "pb": pb,
            "market_observation_date": market_observation_date,
        },
    }
    field_as_of = {
        "pe_ttm": market_as_of,
        "pb": market_as_of,
        "ps_ttm": market_as_of,
        "market_cap_cny": market_as_of,
        "market_cap_usd": market_as_of,
        "roe": financial_as_of,
        "roa": financial_as_of,
        "eps_ttm": eps_as_of,
        "bps_mrq": bps_as_of,
        "bps_current_share_basis_implied": market_as_of,
    }
    return {
        "symbol": ts_code,
        "source": "tushare",
        "currency": "CNY",
        "trade_date": market_as_of,
        "market_cap_cny": market_cap_cny if market_as_of else None,
        "market_cap_usd": market_cap_usd if market_as_of else None,
        "market_cap_value": market_cap_cny if market_as_of else None,
        "market_cap_unit": "亿元人民币",
        "price": r2(price) if market_as_of else None,
        "pe_ttm": r2(pe_ttm) if market_as_of else None,
        "pe_forward": None,
        "pb": r2(pb) if market_as_of else None,
        "ps_ttm": r2(daily.get("ps_ttm") or daily.get("ps")) if market_as_of else None,
        "ev_ebitda": None,
        "peg": None,
        "gross_margin": r2(fina.get("grossprofit_margin")) if fina else None,
        "net_margin": r2(fina.get("netprofit_margin")) if fina else None,
        "roe": r2(fina.get("roe")) if fina and fina_as_of else None,
        "roa": r2(fina.get("roa")) if fina and fina_as_of else None,
        "eps_ttm": eps_ttm,
        "bps_mrq": bps_mrq if fina_as_of else None,
        "bps_current_share_basis_implied": (
            bps_current_basis_implied if market_as_of else None
        ),
        "bps_basis_reconciliation": bps_basis_reconciliation,
        "per_share_currency": "CNY",
        "rd_expense_ratio": r2(fina.get("rd_exp_to_operting_revenue")) if fina else None,
        "operating_cash_flow": ocf_cny,
        "operating_cash_flow_usd": (
            round(ocf_cny / usd_to_cny, 2)
            if ocf_cny is not None and usd_to_cny not in (None, 0)
            else None
        ),
        "capex_value": capex_cny,
        "capex_usd": (
            round(capex_cny / usd_to_cny, 2)
            if capex_cny is not None and usd_to_cny not in (None, 0)
            else None
        ),
        "financials_as_of": financial_as_of,
        "financial_metrics_as_of": financial_as_of,
        "field_as_of": field_as_of,
        "field_methods": field_methods,
        "errors": [x for x in [(fina or {}).get("_error"), (cash or {}).get("_error")] if x],
    }


def _from_yfinance(symbol: str, fx: dict[str, float]) -> dict[str, Any]:
    import yfinance as yf  # type: ignore

    ticker = yf.Ticker(symbol)
    info = ticker.get_info()
    quote_currency_raw = str(info.get("currency") or info.get("financialCurrency") or "USD")
    # Yahoo 的伦敦/特拉维夫/约翰内斯堡报价代码可能表示最小货币单位，
    # 但 marketCap、trailingEps/bookValue 仍以主货币单位返回。例如 LSEG.L
    # 的价格 8974 GBp、EPS 2.37 GBP。统一把价格换成主货币后，PE×EPS、
    # PB×BPS 才与展示价格同口径；provider 原始代码保留在审计字段中。
    minor_quote_units = {
        "GBp": ("GBP", 0.01),
        "GBX": ("GBP", 0.01),
        "ILA": ("ILS", 0.01),
        "ZAc": ("ZAR", 0.01),
    }
    currency, quote_price_scale = minor_quote_units.get(
        quote_currency_raw, (quote_currency_raw.upper(), 1.0)
    )
    financial_currency = str(info.get("financialCurrency") or currency).upper()
    rate = fx.get(currency)
    financial_rate = fx.get(financial_currency)
    usd_to_cny = fnum(fx.get("USD"))
    market_cap_raw = fnum(info.get("marketCap"))
    market_cap_cny_raw = (
        market_cap_raw * rate / 1e8
        if market_cap_raw is not None and rate is not None
        else None
    )
    market_cap_cny = round(market_cap_cny_raw, 2) if market_cap_cny_raw is not None else None
    if market_cap_raw is not None and currency == "USD":
        market_cap_usd_raw = market_cap_raw / 1e8
    elif market_cap_cny_raw is not None and usd_to_cny not in (None, 0):
        market_cap_usd_raw = market_cap_cny_raw / usd_to_cny
    else:
        market_cap_usd_raw = None
    market_cap_usd = round(market_cap_usd_raw, 2) if market_cap_usd_raw is not None else None
    ocf_raw = fnum(info.get("operatingCashflow"))
    ocf_as_of = ""
    ocf_cny = (
        _safe_yi(ocf_raw, financial_rate)
        if ocf_raw is not None and financial_rate is not None
        else None
    )
    capex_cny = None
    rd_expense_ratio = None
    cashflow_as_of = ""
    try:
        cf = ticker.get_cashflow(freq="yearly")
        if "CapitalExpenditure" in cf.index:
            values = cf.loc["CapitalExpenditure"].dropna()
            if not values.empty:
                cashflow_as_of = str(getattr(values.index[0], "date", lambda: values.index[0])())
                if financial_rate is not None:
                    capex_cny = _safe_yi(
                        values.iloc[0], financial_rate, absolute=True
                    )
        if ocf_cny is None and "OperatingCashFlow" in cf.index:
            values = cf.loc["OperatingCashFlow"].dropna()
            if not values.empty:
                if financial_rate is not None:
                    ocf_cny = _safe_yi(values.iloc[0], financial_rate)
    except Exception:
        pass
    try:
        income = ticker.get_income_stmt(freq="yearly")
        revenue_row = next(
            (name for name in ("TotalRevenue", "OperatingRevenue") if name in income.index),
            None,
        )
        rd_row = next(
            (
                name
                for name in (
                    "ResearchAndDevelopment",
                    "ResearchAndDevelopmentExpense",
                    "ResearchDevelopment",
                )
                if name in income.index
            ),
            None,
        )
        if revenue_row and rd_row:
            revenue = income.loc[revenue_row].dropna()
            rd = income.loc[rd_row].dropna()
            common = [column for column in income.columns if column in revenue.index and column in rd.index]
            if common:
                rev_value = fnum(revenue[common[0]])
                rd_value = fnum(rd[common[0]])
                if rev_value not in (None, 0) and rd_value is not None:
                    rd_expense_ratio = r2(abs(rd_value) / abs(rev_value) * 100)
    except Exception:
        pass
    market_as_of = _iso_from_unix(info.get("regularMarketTime"))
    financial_as_of = (
        _iso_from_unix(info.get("mostRecentQuarter"))
        or _iso_from_unix(info.get("lastFiscalYearEnd"))
    )
    if ocf_cny is not None:
        ocf_as_of = financial_as_of if ocf_raw is not None else cashflow_as_of
    price_raw = fnum(info.get("currentPrice") or info.get("regularMarketPrice"))
    price = price_raw * quote_price_scale if price_raw is not None else None
    pe_ttm = fnum(info.get("trailingPE"))
    pb = fnum(info.get("priceToBook"))
    eps_ttm = fnum(info.get("trailingEps"))
    bps_mrq = fnum(info.get("bookValue"))
    eps_method = {
        "extraction_method": "web_fetch",
        "basis": "Yahoo Finance trailing EPS；按报价主货币口径",
        "api_fields": ["info.trailingEps", "info.currency"],
        "units": {"per_share_currency": currency, "quote_currency_raw": quote_currency_raw},
    }
    bps_method = {
        "extraction_method": "web_fetch",
        "basis": "Yahoo Finance latest reported book value per share；按报价主货币口径",
        "api_fields": ["info.bookValue", "info.currency"],
        "units": {"per_share_currency": currency, "quote_currency_raw": quote_currency_raw},
    }
    if eps_ttm is None and pe_ttm is not None and pe_ttm > 0:
        eps_ttm = _ratio_value(price, pe_ttm)
        eps_method = {
            "extraction_method": "inferred",
            "formula": "normalized_quote_price / yfinance info.trailingPE",
            "basis": "TTM；由同一快照 trailingPE 反推",
            "api_fields": ["info.currentPrice", "info.trailingPE"],
            "inputs": {
                "current_price_raw": price_raw,
                "quote_price_scale": quote_price_scale,
                "normalized_quote_price": price,
                "trailing_pe": pe_ttm,
                "per_share_currency": currency,
            },
        }
    if bps_mrq is None and pb is not None and pb > 0:
        bps_mrq = _ratio_value(price, pb)
        bps_method = {
            "extraction_method": "inferred",
            "formula": "normalized_quote_price / yfinance info.priceToBook",
            "basis": "由同一快照 PB 反推最近报告期每股净资产",
            "api_fields": ["info.currentPrice", "info.priceToBook"],
            "inputs": {
                "current_price_raw": price_raw,
                "quote_price_scale": quote_price_scale,
                "normalized_quote_price": price,
                "price_to_book": pb,
                "per_share_currency": currency,
            },
        }
    if currency == "USD":
        market_cap_usd_method = {
            "extraction_method": "inferred",
            "formula": "yfinance info.marketCap(USD) / 1e8",
            "api_fields": ["info.marketCap", "info.currency"],
            "inputs": {"market_cap_usd": market_cap_raw, "currency": currency},
        }
    else:
        market_cap_usd_method = {
            "extraction_method": "inferred",
            "formula": "market_cap_cny_unrounded / yfinance USDCNY=X",
            "api_fields": ["info.marketCap", f"yfinance {currency}CNY=X", "yfinance USDCNY=X"],
            "inputs": {"market_cap_cny_yi": market_cap_cny_raw, "usd_to_cny": usd_to_cny},
        }
    field_methods = {
        "pe_ttm": {
            "extraction_method": "web_fetch",
            "basis": "Yahoo Finance trailing PE",
            "api_fields": ["info.trailingPE"],
        },
        "pe_forward": {"extraction_method": "web_fetch", "api_fields": ["info.forwardPE"]},
        "pb": {"extraction_method": "web_fetch", "api_fields": ["info.priceToBook"]},
        "ps_ttm": {"extraction_method": "web_fetch", "api_fields": ["info.priceToSalesTrailing12Months"]},
        "ev_ebitda": {"extraction_method": "web_fetch", "api_fields": ["info.enterpriseToEbitda"]},
        "peg": {"extraction_method": "web_fetch", "api_fields": ["info.trailingPegRatio", "info.pegRatio"]},
        "market_cap_cny": {
            "extraction_method": "inferred",
            "formula": "yfinance info.marketCap * currency_to_CNY / 1e8",
            "api_fields": ["info.marketCap", f"yfinance {currency}CNY=X"],
            "inputs": {"market_cap_original": market_cap_raw, "currency_to_cny": rate},
        },
        "market_cap_usd": market_cap_usd_method,
        "roe": {
            "extraction_method": "inferred",
            "formula": "yfinance info.returnOnEquity * 100",
            "basis": "Yahoo Finance returnOnEquity trailing provider definition",
            "api_fields": ["info.returnOnEquity"],
            "inputs": {"return_on_equity_ratio": fnum(info.get("returnOnEquity"))},
        },
        "roa": {
            "extraction_method": "inferred",
            "formula": "yfinance info.returnOnAssets * 100",
            "basis": "Yahoo Finance returnOnAssets trailing provider definition",
            "api_fields": ["info.returnOnAssets"],
            "inputs": {"return_on_assets_ratio": fnum(info.get("returnOnAssets"))},
        },
        "eps_ttm": eps_method,
        "bps_mrq": bps_method,
        "operating_cash_flow": {
            "extraction_method": "inferred",
            "formula": "yfinance cash-flow value * financial_currency_to_CNY / 1e8",
            "basis": "现金流按 financialCurrency 换算；不得使用证券报价货币",
            "api_fields": [
                "info.operatingCashflow or cashflow.OperatingCashFlow",
                "info.financialCurrency",
            ],
            "inputs": {
                "financial_currency": financial_currency,
                "financial_currency_to_cny": financial_rate,
            },
        },
        "capex_value": {
            "extraction_method": "inferred",
            "formula": "abs(yfinance cashflow.CapitalExpenditure) * financial_currency_to_CNY / 1e8",
            "basis": "资本开支按 financialCurrency 换算；不得使用证券报价货币",
            "api_fields": [
                "cashflow.CapitalExpenditure",
                "info.financialCurrency",
            ],
            "inputs": {
                "financial_currency": financial_currency,
                "financial_currency_to_cny": financial_rate,
            },
        },
    }
    field_as_of = {
        "pe_ttm": market_as_of,
        "pe_forward": market_as_of,
        "pb": market_as_of,
        "ps_ttm": market_as_of,
        "ev_ebitda": market_as_of,
        "peg": market_as_of,
        "market_cap_cny": market_as_of,
        "market_cap_usd": market_as_of,
        "roe": financial_as_of,
        "roa": financial_as_of,
        "eps_ttm": financial_as_of,
        "bps_mrq": financial_as_of,
        "operating_cash_flow": ocf_as_of or cashflow_as_of or financial_as_of,
        "capex_value": cashflow_as_of,
    }
    return {
        "symbol": symbol,
        "source": "yfinance",
        "currency": currency,
        "quote_currency_raw": quote_currency_raw,
        "financial_currency": financial_currency,
        "trade_date": market_as_of,
        "market_cap_cny": market_cap_cny if market_as_of else None,
        "market_cap_usd": market_cap_usd if market_as_of else None,
        "market_cap_value": market_cap_cny if market_as_of else None,
        "market_cap_unit": "亿元人民币",
        "price": r2(price) if market_as_of else None,
        "pe_ttm": r2(pe_ttm) if market_as_of else None,
        "pe_forward": r2(info.get("forwardPE")) if market_as_of else None,
        "pb": r2(pb) if market_as_of else None,
        "ps_ttm": r2(info.get("priceToSalesTrailing12Months")) if market_as_of else None,
        "ev_ebitda": r2(info.get("enterpriseToEbitda")) if market_as_of else None,
        "peg": r2(info.get("trailingPegRatio") if info.get("trailingPegRatio") is not None else info.get("pegRatio")) if market_as_of else None,
        "gross_margin": r2(fnum(info.get("grossMargins")) * 100 if fnum(info.get("grossMargins")) is not None else None),
        "net_margin": r2(fnum(info.get("profitMargins")) * 100 if fnum(info.get("profitMargins")) is not None else None),
        "roe": r2(fnum(info.get("returnOnEquity")) * 100 if fnum(info.get("returnOnEquity")) is not None else None) if financial_as_of else None,
        "roa": r2(fnum(info.get("returnOnAssets")) * 100 if fnum(info.get("returnOnAssets")) is not None else None) if financial_as_of else None,
        "eps_ttm": r2(eps_ttm) if financial_as_of else None,
        "bps_mrq": r2(bps_mrq) if financial_as_of else None,
        "per_share_currency": currency,
        "rd_expense_ratio": rd_expense_ratio,
        "operating_cash_flow": ocf_cny,
        "operating_cash_flow_usd": (
            round(ocf_cny / usd_to_cny, 2)
            if ocf_cny is not None and usd_to_cny not in (None, 0)
            else None
        ),
        "capex_value": capex_cny,
        "capex_usd": (
            round(capex_cny / usd_to_cny, 2)
            if capex_cny is not None and usd_to_cny not in (None, 0)
            else None
        ),
        "financials_as_of": cashflow_as_of or ocf_as_of or financial_as_of,
        "financial_metrics_as_of": financial_as_of,
        "field_as_of": field_as_of,
        "field_methods": field_methods,
        "errors": [],
    }


def _snapshot_value_available(snapshot: dict[str, Any], field: str) -> bool:
    return fnum(snapshot.get(field)) is not None


def _merge_wind_tushare_snapshots(
    wind_snapshot: dict[str, Any],
    tushare_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    """以 Wind 为主逐字段补缺，并保留每个字段的真实来源。"""
    result = dict(wind_snapshot)
    result["source"] = "wind"
    result["merge_policy"] = "wind_primary_tushare_fill_missing_only"
    field_providers: dict[str, str] = {}
    field_symbols: dict[str, str] = {}
    field_as_of: dict[str, str] = {}
    field_methods: dict[str, dict[str, Any]] = {}
    fallback_fields: list[str] = []

    for field in sorted(A_SHARE_SNAPSHOT_FIELDS):
        use_wind = _snapshot_value_available(wind_snapshot, field)
        source = wind_snapshot if use_wind else (tushare_snapshot or {})
        provider = "wind" if use_wind else "tushare"
        value = fnum(source.get(field))
        if value is None:
            result[field] = None
            continue
        result[field] = value
        field_providers[field] = provider
        field_symbols[field] = str(source.get("symbol") or "")
        raw_as_of = source.get("field_as_of")
        if isinstance(raw_as_of, dict) and raw_as_of.get(field):
            field_as_of[field] = str(raw_as_of[field])
        raw_methods = source.get("field_methods")
        if isinstance(raw_methods, dict) and isinstance(raw_methods.get(field), dict):
            field_methods[field] = dict(raw_methods[field])
        if not use_wind:
            fallback_fields.append(field)

    result["field_providers"] = field_providers
    result["field_symbols"] = field_symbols
    result["field_as_of"] = field_as_of
    result["field_methods"] = field_methods
    result["fallback_fields"] = fallback_fields
    result["errors"] = [
        str(item)
        for snapshot in (wind_snapshot, tushare_snapshot or {})
        for item in (
            snapshot.get("errors")
            if isinstance(snapshot.get("errors"), (list, tuple))
            else [snapshot.get("errors")]
            if snapshot.get("errors")
            else []
        )
        if item
    ]
    result["market_cap_value"] = result.get("market_cap_cny")
    result["market_cap_unit"] = "亿元人民币"
    # 两个 A 股源的每股金额均为人民币。合并日期只用于兼容展示，应用层仍逐字段取时点。
    result["currency"] = "CNY"
    result["per_share_currency"] = "CNY"
    all_dates = list(field_as_of.values())
    if all_dates:
        result["trade_date"] = max(all_dates)
        result["financial_metrics_as_of"] = max(all_dates)
    return result


def fetch_company_market_snapshot(ticker: str | None, *, yf_symbol: str | None = None, fx: dict[str, float] | None = None) -> dict[str, Any]:
    if not ticker and not yf_symbol:
        return {"error": "无上市 ticker，无法取得二级市场估值。"}
    rates = fx or fetch_fx_rates()
    source_symbol = yf_symbol or ticker or ""
    ts_code = ts_code_from_ticker(ticker or "")
    if ts_code:
        wind_error = None
        try:
            wind_result = fetch_current_market_financial_snapshot(ts_code, fx=rates)
        except Exception as exc:
            wind_result = None
            wind_error = f"Wind {type(exc).__name__}: {str(exc)[:140]}"

        if wind_result:
            missing_fillable = {
                field
                for field in TUSHARE_FILLABLE_FIELDS
                if not _snapshot_value_available(wind_result, field)
            }
            tushare_result = None
            tushare_error = None
            if missing_fillable:
                try:
                    tushare_result = _from_tushare(ts_code, rates)
                except Exception as exc:
                    tushare_error = f"Tushare {type(exc).__name__}: {str(exc)[:100]}"
            result = _merge_wind_tushare_snapshots(wind_result, tushare_result)
            if tushare_error:
                result.setdefault("errors", []).append(tushare_error)
            return result

        try:
            tushare_result = _from_tushare(ts_code, rates)
            if tushare_result:
                if wind_error:
                    tushare_result.setdefault("errors", []).append(wind_error)
                return tushare_result
        except Exception as exc:
            tushare_error = f"Tushare {type(exc).__name__}: {str(exc)[:100]}"
        else:
            tushare_error = None
    else:
        tushare_error = None
    try:
        result = _from_yfinance(source_symbol, rates)
        if tushare_error:
            result.setdefault("errors", []).append(tushare_error)
        return result
    except Exception as exc:
        return {"symbol": source_symbol, "error": f"yfinance {type(exc).__name__}: {str(exc)[:160]}", "errors": [tushare_error] if tushare_error else []}


def display_cny_usd(cny: Any, usd: Any) -> str:
    c = r2(cny)
    u = r2(usd)
    if c is None:
        return "不可得"
    if u is None:
        return f"{c:,.2f} 亿元人民币"
    return f"{c:,.2f} 亿元人民币（约 {u:,.2f} 亿美元）"


def unit_cny_usd(cny: Any, usd: Any) -> str:
    u = r2(usd)
    return f"亿元人民币（约 {u:,.2f} 亿美元）" if u is not None else "亿元人民币"
