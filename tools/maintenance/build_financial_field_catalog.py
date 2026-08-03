#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成公司财务建模可用字段总目录。

本工具只用于受控的数据源能力盘点：

- Tushare 读取官方文档页面的输出字段表，不请求全市场数据；
- yfinance 只读取命令行指定的少量证券样本；
- Ricequant 只查询 ``system.columns`` 元数据；
- Wind 不在本工具中发起任何请求，目录只使用已经单证券验证的静态白名单。

输出是能力目录，不是数据事实。字段存在不代表任意公司、任意报告期均非空。
"""
from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "docs" / "公司财务建模可用字段总目录_20260722.md"


@dataclass(frozen=True)
class CatalogRow:
    source: str
    interface: str
    feature_name: str
    description: str
    market: str
    time_scope: str
    frequency: str
    status: str


TUSHARE_DOCS = {
    "daily_basic": 32,
    "income": 33,
    "balancesheet": 36,
    "cashflow": 44,
    "fina_indicator": 79,
    "forecast": 45,
    "express": 46,
    "report_rc": 292,
}

TUSHARE_TIME = {
    "daily_basic": ("历史/当前；交易日长历史", "交易日"),
    "income": ("历史；官方全历史，项目实测5年以上", "季报/中报/三季报/年报，期间累计"),
    "balancesheet": ("历史；官方全历史，项目实测5年以上", "季度/年度报告期末时点"),
    "cashflow": ("历史；官方全历史，项目实测5年以上", "季报/中报/三季报/年报，期间累计"),
    "fina_indicator": ("历史；官方全历史，项目实测5年以上", "随财报更新；季度/年度/TTM衍生口径"),
    "forecast": ("近期未来；单个即将披露报告期，不是多年预测", "公司触发式业绩预告"),
    "express": ("近期实际/准实际；单个已结束报告期", "公司触发式业绩快报"),
    "report_rc": ("未来；实测FY1—FY3，最长由券商报告实际覆盖决定", "逐机构、逐报告、逐目标财年；事件更新"),
}

TUSHARE_STATUS = {
    "daily_basic": "官方字段表；当前账户单证券实测可用",
    "income": "官方字段表；当前账户单证券单期实测可用",
    "balancesheet": "官方字段表；当前账户单证券单期实测可用",
    "cashflow": "官方字段表；当前账户单证券单期实测可用",
    "fina_indicator": "官方字段表；当前账户单证券单期实测可用",
    "forecast": "官方字段表；当前账户实测有记录，但仅部分公司/报告期披露",
    "express": "官方字段表；接口可调用，600519样本窗口为空，不保证每期有值",
    "report_rc": "官方字段表；当前账户实测FY1—FY3逐机构记录可用",
}


WIND_GROUPS: dict[str, tuple[list[tuple[str, str]], str, str]] = {
    "WSS 当前行情与估值": (
        [
            ("close", "收盘价"), ("pe_ttm", "市盈率TTM"),
            ("pe_est_ftm", "未来12个月市盈率"), ("pb_lf", "市净率"),
            ("ps_ttm", "市销率TTM"), ("mkt_cap_ard", "总市值"),
            ("dividendyield2", "股息率"), ("roe_ttm", "净资产收益率TTM"),
            ("roa2_ttm", "总资产收益率TTM"), ("eps_ttm", "每股收益TTM"),
            ("bps_new", "最新每股净资产"), ("ev", "企业价值"),
            ("ev2_to_ebitda", "企业价值/EBITDA"), ("peg", "PEG"),
            ("pcf_ocf_ttm", "市现率/经营现金流TTM"),
        ],
        "历史/当前；可指定交易日，序列深度取决于WSD请求范围",
        "交易日快照；WSD可做日/周/月",
    ),
    "WSS 利润表": (
        [
            ("tot_oper_rev", "营业总收入"), ("oper_rev", "营业收入"),
            ("tot_oper_cost", "营业总成本"), ("oper_cost", "营业成本"),
            ("selling_dist_exp", "销售费用"), ("gerl_admin_exp", "管理费用"),
            ("fin_exp_is", "财务费用"), ("tot_profit", "利润总额"),
            ("net_profit_is", "净利润"), ("np_belongto_parcomsh", "归母净利润"),
            ("minority_int_inc", "少数股东损益"), ("non_oper_rev", "营业外收入"),
            ("non_oper_exp", "营业外支出"), ("ebit", "EBIT"),
            ("ebitda", "EBITDA"), ("rd_exp", "研发费用"),
        ],
        "历史；可按报告期读取，项目已验证年度与季度报告期",
        "季报/中报/三季报/年报；WSS按报告期",
    ),
    "WSS 资产负债表": (
        [
            ("monetary_cap", "货币资金"), ("acct_rcv", "应收账款"),
            ("inventories", "存货"), ("tot_cur_assets", "流动资产合计"),
            ("fix_assets", "固定资产"), ("const_in_prog", "在建工程"),
            ("intang_assets", "无形资产"), ("goodwill", "商誉"),
            ("st_borrow", "短期借款"), ("lt_borrow", "长期借款"),
            ("bonds_payable", "应付债券"), ("tot_cur_liab", "流动负债合计"),
            ("tot_equity", "股东权益合计"), ("tot_assets", "总资产"),
            ("tot_liab", "总负债"), ("total_shares", "总股本"),
        ],
        "历史；可按报告期读取，项目已验证年度与季度报告期",
        "季度/年度报告期末时点",
    ),
    "WSS 现金流与资本投入": (
        [
            ("net_cash_flows_oper_act", "经营活动现金流净额"),
            ("net_cash_flows_inv_act", "投资活动现金流净额"),
            ("net_cash_flows_fnc_act", "筹资活动现金流净额"),
            ("net_incr_cash_cash_equ_dm", "现金及现金等价物净增加额"),
            ("cash_recp_sg_and_rs", "销售商品、提供劳务收到现金"),
            ("cash_pay_dist_dpcp_int_exp", "分红、利润分配及利息支付现金"),
            ("cash_pay_acq_const_fiolta", "购建固定/无形/其他长期资产支付现金，CAPEX现金口径代理"),
            ("depr_fa_coga_dpba", "固定资产等折旧"),
            ("amort_intang_assets", "无形资产摊销"),
            ("fcff", "供应商口径企业自由现金流"),
            ("fcfe", "供应商口径股权自由现金流"),
        ],
        "历史；可按报告期读取",
        "季报/中报/三季报/年报，期间累计",
    ),
    "WSS 盈利质量与效率": (
        [
            ("grossprofitmargin", "毛利率"), ("netprofitmargin", "净利率"),
            ("roe", "净资产收益率"), ("roa2", "总资产收益率"),
            ("roic", "投入资本回报率"), ("debttoassets", "资产负债率"),
            ("current", "流动比率"), ("quick", "速动比率"),
            ("assetsturn", "总资产周转率"), ("invturn", "存货周转率"),
            ("arturn", "应收账款周转率"),
        ],
        "历史；可按报告期或TTM读取",
        "季度/年度/TTM，取决于字段口径",
    ),
    "WSS 单季度": (
        [
            ("qfa_oper_rev", "单季度营业收入"),
            ("qfa_net_profit_is", "单季度净利润"),
            ("qfa_net_cash_flows_oper_act", "单季度经营现金流"),
            ("qfa_roe", "单季度ROE"), ("qfa_roa", "单季度ROA"),
            ("qfa_yoysales", "单季度收入同比"),
            ("qfa_yoyprofit", "单季度利润同比"),
        ],
        "历史；项目已验证多个季度报告期",
        "单季度",
    ),
    "WSS 一致预期": (
        [
            *[(f"west_sales_fy{i}", f"FY{i}一致预期收入") for i in (1, 2, 3)],
            *[(f"west_netprofit_fy{i}", f"FY{i}一致预期净利润") for i in (1, 2, 3)],
            *[(f"west_eps_fy{i}", f"FY{i}一致预期EPS") for i in (1, 2, 3)],
            *[(f"west_avgroe_fy{i}", f"FY{i}一致预期平均ROE") for i in (1, 2, 3)],
            ("west_sales_cagr", "一致预期收入复合增速"),
            ("west_netprofit_cagr", "一致预期净利润复合增速"),
            *[(f"west_sales_fy1_{m}m", f"FY1收入在{m}个月前的一致预期") for m in (1, 3, 6)],
            *[(f"west_netprofit_fy1_{m}m", f"FY1净利润在{m}个月前的一致预期") for m in (1, 3, 6)],
            *[(f"west_eps_fy1_{m}m", f"FY1 EPS在{m}个月前的一致预期") for m in (1, 3, 6)],
        ],
        "未来3个财年；修正序列回看1/3/6个月；没有已验证FY4/FY5",
        "预测截面；可按交易日保存快照",
    ),
}


def _clean(value: str) -> str:
    return " ".join(str(value or "").replace("|", "／").split())


def _tushare_rows(session: requests.Session) -> list[CatalogRow]:
    result: list[CatalogRow] = []
    for interface, doc_id in TUSHARE_DOCS.items():
        url = f"https://tushare.pro/document/2?doc_id={doc_id}"
        response = session.get(url, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        tables = soup.find_all("table")
        if len(tables) < 2:
            raise RuntimeError(f"Tushare {interface} 文档没有输出字段表")
        output_table = tables[1]
        time_scope, frequency = TUSHARE_TIME[interface]
        for tr in output_table.find_all("tr")[1:]:
            cells = [_clean(td.get_text(" ", strip=True)) for td in tr.find_all(["td", "th"])]
            if len(cells) < 3:
                continue
            feature = cells[0]
            description = cells[-1]
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", feature):
                continue
            result.append(CatalogRow(
                source="Tushare Pro",
                interface=interface,
                feature_name=feature,
                description=description,
                market="A股",
                time_scope=time_scope,
                frequency=frequency,
                status=TUSHARE_STATUS[interface],
            ))
    return result


def _wind_rows() -> list[CatalogRow]:
    rows: list[CatalogRow] = []
    for interface, (fields, time_scope, frequency) in WIND_GROUPS.items():
        for feature, description in fields:
            rows.append(CatalogRow(
                source="Wind 内网HTTP",
                interface=interface,
                feature_name=feature,
                description=description,
                market="A股",
                time_scope=time_scope,
                frequency=frequency,
                status="2026-07-22 单证券窄字段实测有效；未验证字段不列入",
            ))
    return rows


YF_PROPERTIES = {
    "financials": ("利润表", "年度，样本约4—5年"),
    "quarterly_financials": ("利润表", "季度，样本约5—6期"),
    "ttm_income_stmt": ("利润表", "TTM，1个滚动期"),
    "balance_sheet": ("资产负债表", "年度，样本约5年"),
    "quarterly_balance_sheet": ("资产负债表", "季度，样本约5—6期"),
    "cash_flow": ("现金流量表", "年度，样本约4—5年"),
    "quarterly_cash_flow": ("现金流量表", "季度，样本约5—6期"),
    "ttm_cash_flow": ("现金流量表", "TTM，1个滚动期"),
}

YF_ANALYSIS = {
    "earnings_estimate": "未来0Q/+1Q/0Y/+1Y；最远下一财年",
    "revenue_estimate": "未来0Q/+1Q/0Y/+1Y；最远下一财年",
    "eps_trend": "未来0Q/+1Q/0Y/+1Y；当前及7/30/60/90日前预测",
    "eps_revisions": "未来0Q/+1Q/0Y/+1Y；7/30日上调下调计数",
    "growth_estimates": "未来0Q/+1Q/0Y/+1Y及LTG长期增长率",
    "earnings_history": "历史最近4个季度实际值与预测差",
    "recommendations_summary": "当前及过去3个月评级分布",
}


def _market_name(symbol: str) -> str:
    return "A股" if symbol.endswith((".SS", ".SZ")) else "美股"


def _yfinance_rows(symbols: Iterable[str]) -> list[CatalogRow]:
    import yfinance as yf

    info_markets: dict[str, set[str]] = defaultdict(set)
    statement_seen: dict[tuple[str, str], set[str]] = defaultdict(set)
    analysis_seen: dict[tuple[str, str], set[str]] = defaultdict(set)
    targets_seen: dict[str, set[str]] = defaultdict(set)

    for symbol in symbols:
        ticker = yf.Ticker(symbol)
        market = _market_name(symbol)
        try:
            for key in ticker.get_info():
                info_markets[str(key)].add(market)
        except Exception:
            pass
        for prop in YF_PROPERTIES:
            try:
                frame = getattr(ticker, prop)
                for feature in frame.index.tolist():
                    statement_seen[(prop, str(feature))].add(market)
            except Exception:
                continue
        for prop in YF_ANALYSIS:
            try:
                obj = getattr(ticker, prop)
                if hasattr(obj, "columns"):
                    for feature in obj.columns.tolist():
                        analysis_seen[(prop, str(feature))].add(market)
            except Exception:
                continue
        try:
            for key in ticker.analyst_price_targets:
                targets_seen[str(key)].add(market)
        except Exception:
            pass

    rows: list[CatalogRow] = []
    for feature, markets in info_markets.items():
        rows.append(CatalogRow(
            source="yfinance/Yahoo Finance",
            interface="get_info",
            feature_name=feature,
            description=re.sub(r"(?<!^)(?=[A-Z])", " ", feature),
            market="/".join(sorted(markets)) + "；其他市场逐股检查",
            time_scope="当前/TTM/最近财报；部分字段含未来12个月",
            frequency="在线快照，字段级更新时间不完全一致",
            status="2026-07-22 小样本实际返回；动态字典，逐股可能为空",
        ))
    for (prop, feature), markets in statement_seen.items():
        scope, frequency = YF_PROPERTIES[prop]
        rows.append(CatalogRow(
            source="yfinance/Yahoo Finance",
            interface=prop,
            feature_name=feature,
            description=f"{scope}原始行项目",
            market="/".join(sorted(markets)),
            time_scope="历史；接口返回深度不是稳定合同",
            frequency=frequency,
            status="2026-07-22 AAPL/600519小样本实际返回列名",
        ))
    for (prop, feature), markets in analysis_seen.items():
        rows.append(CatalogRow(
            source="yfinance/Yahoo Finance",
            interface=prop,
            feature_name=f"{prop}.{feature}",
            description="分析师预测/修正/评级原始字段",
            market="/".join(sorted(markets)),
            time_scope=YF_ANALYSIS[prop],
            frequency="预测截面或事件更新",
            status="2026-07-22 小样本实际返回；A股覆盖显著弱于美股",
        ))
    for feature, markets in targets_seen.items():
        rows.append(CatalogRow(
            source="yfinance/Yahoo Finance",
            interface="analyst_price_targets",
            feature_name=f"analyst_price_targets.{feature}",
            description="分析师目标价",
            market="/".join(sorted(markets)),
            time_scope="当前目标价截面；不是多年财务预测",
            frequency="事件/截面更新",
            status="2026-07-22 小样本实际返回；A股可能仅current",
        ))
    return rows


def _ricequant_rows() -> list[CatalogRow]:
    url = os.getenv("RICEQUANT_HTTP_URL")
    user = os.getenv("RICEQUANT_USER")
    password = os.getenv("RICEQUANT_PASSWORD")
    if not (url and user and password):
        raise RuntimeError("生成完整目录需要 RICEQUANT_HTTP_URL/USER/PASSWORD 环境变量")
    sql = (
        "SELECT table,name,type FROM system.columns "
        "WHERE database='ricequant' AND table IN "
        "('stock_daily_basic','stock_fina_indicator','stock_analyst_consensus',"
        "'stock_analyst_adjustment') ORDER BY table,position FORMAT JSONEachRow"
    )
    response = requests.post(url, data=sql.encode("utf-8"), auth=(user, password), timeout=30)
    response.raise_for_status()
    rows: list[CatalogRow] = []
    for line in response.text.splitlines():
        item = json.loads(line)
        table = item["table"]
        feature = item["name"]
        if table == "stock_daily_basic":
            time_scope = "历史/当前；2001年至今"
            frequency = "交易日"
            status = "2026-07-22 system.columns实测；中国证券"
        elif table == "stock_fina_indicator":
            time_scope = "历史PIT；2006年至今，最近财报沿交易日展开"
            frequency = "交易日ASOF快照；底层随财报变化"
            status = "2026-07-22 system.columns实测；底层来自Tushare，不是独立源"
        elif table == "stock_analyst_consensus":
            time_scope = "历史预测因子；2016年至今；0/1/2期限映射尚无正式字典"
            frequency = "交易日；5/10/30/60/90/180日窗口"
            status = "2026-07-22 system.columns实测；只有ROE/ROA因子，不能当绝对预测"
        else:
            time_scope = "历史预测修正因子；2016年至今；0/1/2期限映射尚无正式字典"
            frequency = "交易日；31/61/91/181日窗口"
            status = "2026-07-22 system.columns实测；aa_ew公式未取得，只能作信号"
        rows.append(CatalogRow(
            source="公司内网 Ricequant",
            interface=table,
            feature_name=feature,
            description=f"ClickHouse {item['type']} 原始列",
            market="A股/中国证券；无美股",
            time_scope=time_scope,
            frequency=frequency,
            status=status,
        ))
    return rows


CONTACT_TOKENS = {
    "address", "city", "country", "fax", "phone", "website", "zip", "email",
    "longname", "shortname", "chairman", "manager", "secretary", "office",
    "introduction", "business_scope", "main_business", "companyofficers",
}
META_TOKENS = {
    "date", "ann_date", "f_ann_date", "end_date", "report_date", "trade_date",
    "update_flag", "report_type", "end_type", "ts_code", "order_book_id",
    "quarter", "rd", "report_title", "org_name", "author_name", "symbol",
}
VALUATION_TOKENS = (
    "pe", "pb", "ps", "peg", "price", "marketcap", "market_cap", "mkt_cap",
    "enterprise", "ev2", "ev_", "bookvalue", "book_value", "dividendyield",
    "dv_", "pcf", "target", "tp",
)
EARNINGS_TOKENS = (
    "revenue", "sales", "profit", "income", "eps", "ebit", "ebitda", "margin",
    "oper_rev", "operating", "cost", "expense", "tax", "rd_exp", "research",
    "gross", "roe", "roa", "roic", "cogs", "prem", "commis", "interest",
)
MODEL_TOKENS = (
    "asset", "liab", "equity", "debt", "borrow", "cash", "receiv", "invent",
    "payable", "capital", "share", "ppe", "fix_", "goodwill", "intang",
    "working", "fcf", "cashflow", "cash_flow", "dividend", "depreci", "amort",
    "lease", "bond", "reserve", "capex", "expenditure", "turn", "ratio",
)
RISK_TOKENS = ("risk", "beta", "governance", "heldpercent", "short", "volatility")


def _contains(text: str, tokens: Iterable[str]) -> bool:
    return any(token in text for token in tokens)


def _relationship(row: CatalogRow) -> tuple[str, str]:
    text = f"{row.interface} {row.feature_name} {row.description}".lower().replace(" ", "_")
    base_name = row.feature_name.lower()
    if row.interface in {"stock_analyst_consensus", "stock_analyst_adjustment"}:
        return (
            "盈利质量、预期方向和估值情绪间接；当前不是可解释的财务金额",
            "中：取得期限映射、公式和单位后用于修正信号，当前不进入金额模型",
        )
    if row.interface in {
        "earnings_estimate", "revenue_estimate", "eps_trend", "eps_revisions",
        "growth_estimates", "earnings_history",
    }:
        return (
            "盈利预测直接；通过EPS、收入和修正方向影响估值",
            "高：美股盈利对账核心；A股必须先检查非空覆盖",
        )
    if row.interface in {"analyst_price_targets", "recommendations_summary"}:
        return (
            "估值或市场定价直接/间接；不生成三表和盈利金额",
            "中：用于市场预期和定价对账，不作为独立内在价值",
        )
    if base_name in META_TOKENS or any(base_name.endswith("." + token) for token in META_TOKENS):
        return "间接：证券匹配、报告期、公告日和PIT口径审计", "高：防止时间穿越和口径错配"
    if any(token in base_name.replace("_", "") for token in CONTACT_TOKENS):
        return "基本无直接关系；只用于主体识别或联系信息", "低：不进入估值或盈利模型"
    valuation = _contains(text, VALUATION_TOKENS)
    earnings = _contains(text, EARNINGS_TOKENS)
    model = _contains(text, MODEL_TOKENS)
    risk = _contains(text, RISK_TOKENS)
    parts: list[str] = []
    if valuation:
        parts.append("估值直接")
    if earnings:
        parts.append("盈利预测/盈利质量直接")
    if model:
        parts.append("三表、现金流或资本结构直接")
    if risk and not parts:
        parts.append("估值风险溢价间接")
    if not parts:
        if any(token in text for token in ("volume", "turnover", "high", "low", "open", "change")):
            return "市场交易状态间接；不直接生成盈利或三表", "中低：用于估值时点和流动性核验"
        if "analyst" in row.interface or "con_" in text or "aa_ew" in text:
            return "盈利预期方向和估值情绪间接；不是财务金额", "中：取得正式字段定义后可用于修正信号"
        return "关系较弱或仅适用于特定行业/审计场景", "低至中：按公司经济类型选用"
    if valuation and (earnings or model):
        utility = "高：核心估值与财务建模输入/核验"
    elif earnings or model:
        utility = "高：核心盈利、三表或现金流输入/核验"
    else:
        utility = "高：核心估值输入/核验"
    return "；".join(parts), utility


def _escape(value: object) -> str:
    return _clean(str(value)).replace("`", "&#96;")


def render(rows: list[CatalogRow]) -> str:
    source_order = {
        "Wind 内网HTTP": 0,
        "Tushare Pro": 1,
        "yfinance/Yahoo Finance": 2,
        "公司内网 Ricequant": 3,
    }
    rows = sorted(rows, key=lambda row: (
        source_order.get(row.source, 99), row.interface.lower(), row.feature_name.lower()
    ))
    counts = Counter(row.source for row in rows)
    lines = [
        "# 公司财务建模可用字段总目录",
        "",
        f"生成日期：{date.today().isoformat()}。本目录共 **{len(rows):,}** 行原始字段。",
        "",
        "本目录回答的是“当前项目能从哪些链路取得哪些原始字段”，不是“每家公司每期一定有值”。"
        "`当前验证状态`必须与字段名一起阅读：官方文档字段、当前账号实测字段和仅有元数据的内部因子不能混为一谈。",
        "",
        "未来期限的核心结论：Wind 和 Tushare 当前最多稳定覆盖未来三个财年；yfinance标准结构最远到下一财年；"
        "内网Ricequant的0/1/2期限尚无正式映射；当前没有已验证的通用FY4/FY5绝对财务预测。未来五年必须由内部经营驱动和三表模型生成。",
        "",
        "## 未来数据期限总览",
        "",
        "| 数据源 | A股未来覆盖 | 美股未来覆盖 | 当前可直接使用的最长确定期限 | 五年建模结论 |",
        "|---|---|---|---|---|",
        "| Wind内网HTTP | 收入、净利润、EPS、平均ROE到FY1—FY3；FTM PE；1/3/6个月预测修正 | 当前代理的美股FY1—FY3样本系统性为空 | 3个财年 | FY4—FY5必须内部预测 |",
        "| Tushare | `report_rc`逐机构收入、利润、EPS、PE、ROE等实测到FY1—FY3；公司预告只覆盖近期报告期 | 当前账户无美股财务权限 | 3个财年，且由券商报告实际覆盖决定 | FY4—FY5必须内部预测 |",
        "| yfinance | 0Q、+1Q、0Y、+1Y，A股EPS和修正经常为空 | 0Q、+1Q、0Y、+1Y，另有LTG长期增速但不是逐年财务表 | 下一财年 | 不能用LTG替代FY2—FY5三表 |",
        "| 公司内网Ricequant | ROE/ROA及调整因子的0/1/2期限，但正式期限映射和公式尚未取得 | 无 | 不能在当前合同下认定为FY1—FY3 | 只作修正信号，不生成五年金额 |",
        "",
        "字段数量按来源：" + "；".join(f"{source} {count:,}行" for source, count in counts.items()) + "。",
        "",
        "## 统一字段表",
        "",
        "| 来源 | 接口/表 | 原始 feature_name | 指标或科目含义 | 市场 | 过去/未来与长度 | 频率/更新方式 | 与估值、盈利和公司财务建模的关系 | 本课题有用性 | 当前验证状态与限制 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        relation, utility = _relationship(row)
        lines.append(
            "| " + " | ".join([
                _escape(row.source), _escape(row.interface), f"`{_escape(row.feature_name)}`",
                _escape(row.description), _escape(row.market), _escape(row.time_scope),
                _escape(row.frequency), _escape(relation), _escape(utility), _escape(row.status),
            ]) + " |"
        )
    lines.extend([
        "",
        "## 不应误读的边界",
        "",
        "- Wind目录只列入单证券窄字段实测成功的原始字段；没有把猜测字段或Wind全产品宣传当成本项目可用能力。",
        "- Tushare字段来自官方输出表；当前账户已验证相关A股接口可调用，但保险、银行或少见科目是否非空由公司业务决定。",
        "- yfinance字段来自AAPL与600519小样本的动态返回；Yahoo可随证券、时间和接口版本改变行项目，必须冻结原始快照。",
        "- 内网`stock_fina_indicator`底层来自Tushare，不能作为第二个独立来源；分析师两表只有因子，不能替代收入、利润或现金流预测。",
        "- Tushare美股财务接口虽有官方文档，但当前账户无权限，因此没有放进“当前可用字段”主表。RQData官方519项一致预期因子尚未映射进内网，也不计入当前可用字段。",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="生成公司财务建模可用字段总目录")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--yfinance-symbol", action="append", default=[])
    args = parser.parse_args()

    symbols = args.yfinance_symbol or ["AAPL", "600519.SS"]
    session = requests.Session()
    rows = _wind_rows()
    rows.extend(_tushare_rows(session))
    rows.extend(_yfinance_rows(symbols))
    rows.extend(_ricequant_rows())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(rows), encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "row_count": len(rows),
        "source_counts": dict(Counter(row.source for row in rows)),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
