#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Tushare Pro 最小数据提供层。

用途：作为 A 股 Wind 主源的逐字段补缺、公告/重述审计和当前 K 线实现，给行业库
提供统一的 Tushare 调用边界。token 从环境变量或本地 token 文件读取，任何日志
都不得打印 token。
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import requests


ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_TUSHARE_URL = "http://api.tushare.pro"


class TushareUnavailable(RuntimeError):
    """Tushare token 或网络不可用。"""


class TushareApiError(RuntimeError):
    """Tushare API 返回非 0 code。"""


def load_tushare_token() -> str | None:
    token = os.getenv("TUSHARE_TOKEN")
    if token and token.strip():
        return token.strip()
    for path in (
        ROOT / "tushare_token.txt",
        Path("D:/quant/data2/tushare_token.txt"),
    ):
        try:
            if path.exists():
                raw = path.read_text(encoding="utf-8").strip()
                if raw:
                    return raw.splitlines()[0].strip()
        except OSError:
            continue
    return None


def tushare_available() -> bool:
    return bool(load_tushare_token())


def call_tushare(
    api_name: str,
    params: dict[str, Any] | None = None,
    fields: str | Iterable[str] | None = None,
    *,
    timeout: int = 45,
) -> list[dict[str, Any]]:
    token = load_tushare_token()
    if not token:
        raise TushareUnavailable(
            "未找到 Tushare token。请设置环境变量 TUSHARE_TOKEN，或在项目根/"
            "D:/quant/data2/tushare_token.txt 放置 token。"
        )
    if isinstance(fields, (list, tuple)):
        fields = ",".join(str(x) for x in fields)
    body = {
        "api_name": api_name,
        "token": token,
        "params": params or {},
        "fields": fields or "",
    }
    try:
        resp = requests.post(DEFAULT_TUSHARE_URL, json=body, timeout=timeout)
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        raise TushareUnavailable(f"Tushare 网络请求失败：{type(exc).__name__}") from exc
    except ValueError as exc:
        raise TushareUnavailable("Tushare 返回非 JSON 响应") from exc

    code = payload.get("code", 0)
    if code != 0:
        msg = str(payload.get("msg") or "")[:180]
        raise TushareApiError(f"Tushare {api_name} 返回 code={code}: {msg}")
    data = payload.get("data") or {}
    cols = data.get("fields") or []
    rows = data.get("items") or []
    return [dict(zip(cols, row)) for row in rows]


def is_a_share_ticker(ticker: str | None) -> bool:
    t = (ticker or "").strip().upper()
    return t.endswith((".SH", ".SZ", ".BJ", ".SS"))


def ts_code_from_ticker(ticker: str | None) -> str | None:
    t = (ticker or "").strip().upper()
    if not t:
        return None
    if t.endswith(".SS"):
        return t[:-3] + ".SH"
    if t.endswith((".SH", ".SZ", ".BJ")):
        return t
    return None


def _sort_desc(rows: list[dict[str, Any]], *keys: str) -> list[dict[str, Any]]:
    def key(row: dict[str, Any]) -> tuple[str, ...]:
        return tuple(str(row.get(k) or "") for k in keys)

    return sorted(rows, key=key, reverse=True)


def fnum(value: Any) -> float | None:
    try:
        f = float(value)
        if f != f or f in (float("inf"), float("-inf")):
            return None
        return f
    except (TypeError, ValueError):
        return None


def get_or_create_tushare_source(conn, *, title: str = "Tushare Pro 数据快照") -> int:
    row = conn.execute(
        "SELECT id FROM source WHERE title=? AND fetch_method='api_tushare'",
        (title,),
    ).fetchone()
    if row:
        return row["id"] if hasattr(row, "keys") else row[0]
    return conn.execute(
        """INSERT INTO source(title, source_type, publisher, publish_date, quality_tier,
           is_forward_looking, value_layer, fetch_method, source_credibility, language,
           is_primary_source, source_subtype, url)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            title,
            "三方数据",
            "Tushare Pro",
            date.today().isoformat(),
            2,
            0,
            "公司专项",
            "api_tushare",
            "whitelisted",
            "zh",
            0,
            "financial_database",
            "https://tushare.pro/",
        ),
    ).lastrowid


def fetch_daily_basic_latest(ts_code: str) -> dict[str, Any] | None:
    fields = (
        "ts_code,trade_date,close,turnover_rate,turnover_rate_f,volume_ratio,"
        "pe,pe_ttm,pb,ps,ps_ttm,dv_ratio,dv_ttm,total_share,float_share,"
        "free_share,total_mv,circ_mv"
    )
    rows = call_tushare("daily_basic", {"ts_code": ts_code}, fields)
    return _sort_desc(rows, "trade_date")[0] if rows else None


def fetch_daily_rows(ts_code: str, *, start_date: str | None = None, end_date: str | None = None) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"ts_code": ts_code}
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    fields = "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"
    return _sort_desc(call_tushare("daily", params, fields), "trade_date")


def fetch_income_rows(ts_code: str, *, years: Iterable[str] | None = None) -> list[dict[str, Any]]:
    fields = (
        "ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,"
        "total_revenue,revenue,operate_profit,total_profit,n_income,"
        "n_income_attr_p,rd_exp,update_flag"
    )
    rows = call_tushare("income", {"ts_code": ts_code}, fields)
    if years:
        ys = {str(y) for y in years}
        rows = [r for r in rows if str(r.get("end_date") or "")[:4] in ys]
    return _sort_desc(rows, "end_date", "ann_date", "f_ann_date")


def fetch_fina_indicator_latest(ts_code: str) -> dict[str, Any] | None:
    fields = (
        "ts_code,ann_date,end_date,eps,bps,grossprofit_margin,netprofit_margin,roe,roa,"
        "rd_exp_to_operting_revenue,update_flag"
    )
    rows = call_tushare("fina_indicator", {"ts_code": ts_code}, fields)
    return _sort_desc(rows, "end_date", "ann_date")[0] if rows else None


def fetch_fina_indicator_rows(ts_code: str, *, years: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """返回财务指标历史序列，供行业包复核年度与季度口径。"""
    fields = (
        "ts_code,ann_date,end_date,eps,bps,grossprofit_margin,netprofit_margin,roe,roa,"
        "rd_exp_to_operting_revenue,update_flag"
    )
    rows = call_tushare("fina_indicator", {"ts_code": ts_code}, fields)
    if years:
        ys = {str(y) for y in years}
        rows = [r for r in rows if str(r.get("end_date") or "")[:4] in ys]
    return _sort_desc(rows, "end_date", "ann_date")


def fetch_cashflow_latest(ts_code: str) -> dict[str, Any] | None:
    fields = "ts_code,ann_date,end_date,n_cashflow_act,c_pay_acq_const_fiolta,update_flag"
    rows = call_tushare("cashflow", {"ts_code": ts_code}, fields)
    return _sort_desc(rows, "end_date", "ann_date")[0] if rows else None


def fetch_cashflow_rows(ts_code: str, *, years: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """返回现金流历史序列，保留经营现金流正负号。"""
    fields = "ts_code,ann_date,end_date,n_cashflow_act,c_pay_acq_const_fiolta,update_flag"
    rows = call_tushare("cashflow", {"ts_code": ts_code}, fields)
    if years:
        ys = {str(y) for y in years}
        rows = [r for r in rows if str(r.get("end_date") or "")[:4] in ys]
    return _sort_desc(rows, "end_date", "ann_date")


def fetch_balancesheet_rows(
    ts_code: str,
    *,
    years: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """返回资产负债表历史序列，覆盖竞争研究所需营运资本和产能代理。"""

    fields = (
        "ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,total_assets,"
        "accounts_receiv,inventories,fix_assets,cip,contract_liab,"
        "total_hldr_eqy_exc_min_int,update_flag"
    )
    rows = call_tushare("balancesheet", {"ts_code": ts_code}, fields)
    if years:
        ys = {str(y) for y in years}
        rows = [r for r in rows if str(r.get("end_date") or "")[:4] in ys]
    return _sort_desc(rows, "end_date", "ann_date", "f_ann_date")


def fetch_stock_company_latest(ts_code: str) -> dict[str, Any] | None:
    """返回当前公司员工数快照；接口不提供可审计的逐年历史。"""

    fields = "ts_code,employees,main_business,business_scope"
    rows = call_tushare("stock_company", {"ts_code": ts_code}, fields)
    return rows[0] if rows else None


def fetch_disclosure_date_latest(ts_code: str) -> dict[str, Any] | None:
    fields = "ts_code,ann_date,end_date,pre_date,actual_date,modify_date"
    rows = call_tushare("disclosure_date", {"ts_code": ts_code}, fields)
    today = date.today().strftime("%Y%m%d")
    future = [r for r in rows if str(r.get("pre_date") or "") >= today]
    source = future if future else rows
    return _sort_desc(source, "pre_date", "ann_date")[0] if source else None
