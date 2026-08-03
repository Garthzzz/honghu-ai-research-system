#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全局市场/财务数据源策略。

当前用户策略：A 股允许使用项目根目录 ``WindPy.py`` 对接的内网 Wind HTTP
代理，并以 Wind 为主、Tushare 为逐字段补缺和审计补充；其他市场仍以 Yahoo
Finance/yfinance 为主。Akshare 继续禁止作为新增市场、估值、财务或 K 线来源。
"""
from __future__ import annotations

from typing import Iterable


ALLOWED_MARKET_DATA_PROVIDERS = ("api_wind", "api_tushare", "api_yfinance")
DISABLED_MARKET_DATA_PROVIDERS = ("akshare",)
PROVIDER_ALIASES = {
    "wind": "api_wind",
    "windpy": "api_wind",
    "api_wind": "api_wind",
    "tushare": "api_tushare",
    "api_tushare": "api_tushare",
    "yfinance": "api_yfinance",
    "yahoo finance": "api_yfinance",
    "yahoo_finance": "api_yfinance",
    "api_yfinance": "api_yfinance",
}


def is_wind_provider(value: object) -> bool:
    s = str(value or "").strip().lower()
    return s in {"wind", "api_wind", "windpy"} or "wind" in s


def normalize_provider(value: object) -> str:
    raw = str(value or "").strip()
    lowered = raw.lower()
    if lowered == "akshare":
        raise RuntimeError("Akshare 已禁止作为新增市场、估值、财务或 K 线数据源。")
    return PROVIDER_ALIASES.get(lowered, raw)


def assert_provider_allowed(provider: object, *, context: str = "") -> None:
    if str(provider or "").strip().lower() == "akshare":
        prefix = f"{context}: " if context else ""
        raise RuntimeError(prefix + "Akshare 已禁止作为新增市场、估值、财务或 K 线数据源。")
    canonical = PROVIDER_ALIASES.get(str(provider or "").strip().lower(), str(provider or "").strip())
    if canonical and canonical not in ALLOWED_MARKET_DATA_PROVIDERS:
        raise RuntimeError(
            f"市场/财务数据源 {provider!r} 不在允许列表内；当前只允许 "
            "api_wind、api_tushare 与 api_yfinance。"
        )


def assert_market_data_providers_allowed(
    providers: Iterable[object], *, context: str = ""
) -> None:
    for provider in providers:
        assert_provider_allowed(provider, context=context)


def assert_no_wind_providers(providers: Iterable[object], *, context: str = "") -> None:
    """兼容旧调用名；现在只执行通用允许列表校验，不再拒绝 Wind。"""
    assert_market_data_providers_allowed(providers, context=context)
