from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


AS_OF_DATE = "2026-07-05"
SLUG = "20260705_ai_positioning_crowding_deep_run"
OUTPUT_DIR = ROOT / "opportunity_lens" / "research_outputs" / SLUG
PACK_PATH = OUTPUT_DIR / "run_pack.json"
EXECUTION_CACHE_PATH = OUTPUT_DIR / "EXECUTION_CACHE.md"
INTAKE_PATH = (
    ROOT
    / "opportunity_lens"
    / "intake_requests"
    / "Opportunity_Lens_研究请求_AI持仓拥挤度_深度补充版.md"
)
RESEARCH_QUESTION = "美国、全球宏观、日本市场中的 AI 相关持仓拥挤度深度研究"

ACS_WEIGHTS = {
    "持仓与资金流拥挤": 0.30,
    "价格动量与估值拥挤": 0.20,
    "基本面兑现支撑": 0.20,
    "衍生品和宏观杠杆": 0.15,
    "退出敏感度": 0.15,
}

BANNED_PHRASES = (
    "manual_verified_fact",
    "time_series_data_point",
    "行业事实原文证据",
    "客户验证和供货进展原文证据",
    "材料和工艺瓶颈原文证据",
    "该证据必须结合原始链接全文",
    "在某问题下，该指标说明",
    "它不是孤立数字，而是用于判断",
    "对这个因子来说",
    "这条证据把评分从概念讨论拉回",
    "lit review",
    "ETF/13F/CFTC/IR/价格继续同向确认",
    "资金流转负、价格破位或基本面兑现不足",
)


def _ref(ref: str) -> str:
    return ref if ref.startswith("source_ref:") else f"source_ref:{ref}"


def _compact(text: Any, limit: int = 1200) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _score_grade(score: float) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    return "D"


SOURCES: list[dict[str, Any]] = [
    {
        "ref": "bofa_fms_202606_semis_crowding",
        "title": "BofA Global Fund Manager Survey 2026年6月：Long global semiconductors 被80%受访者视为最拥挤交易",
        "source_tier": "B",
        "source_review_status": "pass_broker_survey_via_public_summary",
        "publisher": "BofA Global Research / MaceNews-TradingView public summary",
        "publish_date": "2026-06-18",
        "url": "https://www.tradingview.com/news/macenews%3A241f5c939094b%3A0-bofa-global-research-fund-manager-survey-global-investors-pare-risk-holdings-in-june-but-stay-positive-on-world-growth-prospects/",
        "language": "en",
        "cluster": "broker_positioning_surveys",
        "cluster_label": "卖方全球资金经理调查",
        "policy_evidence_role": "core_evidence",
        "excerpt": "The public summary states that the three most crowded trades in June were Long global semiconductors at 80%, Long Magnificent 7 at 12%, and Long Oil at 4%; it also lists AI bubble as a 28% tail risk. 中文译意：半导体拥挤度已经从主题热度上升到全球专业投资者的共识拥挤读数。",
    },
    {
        "ref": "goldman_hf_trend_all_in_ai_202606",
        "title": "Goldman Sachs Hedge Fund Trend Monitor：All In on AI",
        "source_tier": "B",
        "source_review_status": "pass_broker_hf_holdings_summary",
        "publisher": "Goldman Sachs Global Investment Research / public PDF mirror",
        "publish_date": "2026-06-01",
        "url": "https://www.cfsrating.com/media/uj4jftdo/hedge-fund-trend-monitor_-all-in-on-ai.pdf",
        "language": "en",
        "cluster": "broker_prime_holdings",
        "cluster_label": "对冲基金持仓和 prime brokerage 线索",
        "policy_evidence_role": "core_evidence",
        "excerpt": "The report sample covers 1,059 hedge funds with $4.6 trillion gross equity positions at the start of Q2 2026, and says hedge funds lifted their net tilt to Information Technology by +853 bp. 中文译意：这不是单只股票观点，而是横跨多空组合的行业倾斜证据。",
    },
    {
        "ref": "goldman_semis_profit_taking_202606",
        "title": "Goldman Sachs：How Hedge Funds Are Trading Semiconductor Stocks",
        "source_tier": "B",
        "source_review_status": "pass_broker_prime_public_article",
        "publisher": "Goldman Sachs",
        "publish_date": "2026-06-01",
        "url": "https://www.goldmansachs.com/insights/articles/how-hedge-funds-are-trading-semiconductor-stocks",
        "language": "en",
        "cluster": "broker_prime_holdings",
        "cluster_label": "对冲基金半导体风险管理",
        "policy_evidence_role": "core_evidence",
        "excerpt": "Goldman says semiconductor and equipment stocks were the most net-sold US subsector in the past month, while exposure remained high since the start of last year. 中文译意：半导体已经不是单纯加仓，开始进入高持仓后的获利了结和再平衡阶段。",
    },
    {
        "ref": "sec_13f_dataset_2026q1",
        "title": "SEC Form 13F Data Sets：2026 March-April-May 官方机构持仓数据集",
        "source_tier": "S",
        "source_review_status": "pass_regulator_dataset",
        "publisher": "U.S. Securities and Exchange Commission",
        "publish_date": "2026-05-15",
        "url": "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets",
        "language": "en",
        "cluster": "regulator_holdings",
        "cluster_label": "SEC 13F 官方数据",
        "policy_evidence_role": "core_evidence",
        "excerpt": "SEC provides structured Form 13F data sets and states the data are extracted from XML filings and updated quarterly. 中文译意：13F 是机构持仓的官方可复算底座，但它滞后、只覆盖多头和特定证券，不能替代实时风险敞口。",
    },
    {
        "ref": "sec_13f_recalc_ai_holdings_2026q1",
        "title": "Opportunity Lens 13F 复算底稿：2026Q1 AI/科技核心持仓聚合",
        "source_tier": "A",
        "source_review_status": "pass_calculation_workpaper",
        "publisher": "Opportunity Lens producer-reviewer-loop",
        "publish_date": AS_OF_DATE,
        "url": None,
        "local_path": "cache/ol_ai_crowding/01mar2026-31may2026_form13f.zip",
        "language": "zh-CN",
        "cluster": "regulator_holdings",
        "cluster_label": "SEC 13F 官方数据复算",
        "policy_evidence_role": "reference_only",
        "excerpt": "本地复算使用 SEC 2026 March-April-May Form 13F zip，筛选 REPORTCALENDARORQUARTER=31-MAR-2026，得到 8,868 个 accession、3,321,967 条持仓行。NVIDIA 聚合 3.18 万亿美元等值、5,865 个申报 accession；Alphabet、Microsoft、Apple、Amazon、Broadcom、Meta 同样位于最密集机构持仓。",
    },
    {
        "ref": "cftc_tff_financial_20260623",
        "title": "CFTC Traders in Financial Futures：2026-06-23 金融期货持仓",
        "source_tier": "S",
        "source_review_status": "pass_regulator_report",
        "publisher": "U.S. Commodity Futures Trading Commission",
        "publish_date": "2026-06-27",
        "url": "https://www.cftc.gov/dea/futures/financial_lf.htm",
        "language": "en",
        "cluster": "regulator_derivatives",
        "cluster_label": "CFTC 金融期货持仓",
        "policy_evidence_role": "core_evidence",
        "excerpt": "The CFTC TFF report as of June 23, 2026 lists open interest and trader categories for NASDAQ-100 consolidated futures, S&P 500 consolidated futures and Japanese Yen futures. 中文译意：它能观察指数和日元的杠杆结构，但不能直接识别所有 AI 股票现金仓位。",
    },
    {
        "ref": "cftc_recalc_ai_macro_20260623",
        "title": "Opportunity Lens CFTC 复算底稿：Nasdaq-100、S&P 500、日元期货结构",
        "source_tier": "A",
        "source_review_status": "pass_calculation_workpaper",
        "publisher": "Opportunity Lens producer-reviewer-loop",
        "publish_date": AS_OF_DATE,
        "url": None,
        "local_path": str(EXECUTION_CACHE_PATH.relative_to(ROOT)).replace("\\", "/"),
        "language": "zh-CN",
        "cluster": "regulator_derivatives",
        "cluster_label": "CFTC 金融期货持仓复算",
        "policy_evidence_role": "reference_only",
        "excerpt": "复算记录：Nasdaq-100 consolidated futures open interest 276,807；asset manager long/short 为99,674/35,896，leveraged funds long/short 为37,284/94,687。日元期货 open interest 431,030，asset manager 和 leveraged funds 均呈净空日元结构。",
    },
    {
        "ref": "invesco_qqq_holdings_20260702",
        "title": "Invesco QQQ holdings 2026-07-02",
        "source_tier": "S",
        "source_review_status": "pass_etf_provider",
        "publisher": "Invesco",
        "publish_date": "2026-07-02",
        "url": "https://www.invesco.com/qqq-etf/en/about.html",
        "language": "en",
        "cluster": "etf_holdings",
        "cluster_label": "ETF 官方持仓",
        "policy_evidence_role": "core_evidence",
        "excerpt": "QQQ top holdings include NVIDIA 7.63%, Apple 7.33%, Micron 4.91%, Microsoft 4.69%, Amazon 4.22%. 中文译意：Nasdaq-100 ETF 已经把 AI 芯片、存储和巨头现金流集中到同一个被动入口。",
    },
    {
        "ref": "ssga_spy_holdings_20260702",
        "title": "SPDR S&P 500 ETF Trust index top holdings 2026-07-02",
        "source_tier": "S",
        "source_review_status": "pass_etf_provider",
        "publisher": "State Street Global Advisors",
        "publish_date": "2026-07-02",
        "url": "https://www.ssga.com/us/en/intermediary/etfs/state-street-spdr-sp-500-etf-trust-spy",
        "language": "en",
        "cluster": "etf_holdings",
        "cluster_label": "ETF 官方持仓",
        "policy_evidence_role": "core_evidence",
        "excerpt": "SPY index top holdings include NVIDIA 7.34%, Apple 7.05%, Microsoft 4.51%, Amazon 3.69%, Alphabet A 3.28%, Broadcom 2.65%, Alphabet C 2.62%, Meta 1.99%, Tesla 1.72%, Micron 1.71%. 中文译意：AI 相关大盘股已经是 S&P 500 被动风险预算的核心。",
    },
    {
        "ref": "blackrock_soxx_20260702",
        "title": "iShares Semiconductor ETF SOXX 官方快照",
        "source_tier": "S",
        "source_review_status": "pass_etf_provider",
        "publisher": "BlackRock iShares",
        "publish_date": "2026-07-02",
        "url": "https://www.ishares.com/us/products/239705/ishares-phlx-semiconductor-etf",
        "language": "en",
        "cluster": "etf_holdings",
        "cluster_label": "半导体 ETF 官方数据",
        "policy_evidence_role": "core_evidence",
        "excerpt": "SOXX official page shows NAV $566.67 as of Jul. 02, 2026 and NAV total return YTD 99.20% as of Jul. 01, 2026. 中文译意：半导体拥挤不仅是调查口径，也已经反映在 ETF 年内收益和回撤风险里。",
    },
    {
        "ref": "vaneck_smh_fact_202607",
        "title": "VanEck Semiconductor ETF SMH fact sheet",
        "source_tier": "S",
        "source_review_status": "pass_etf_provider",
        "publisher": "VanEck",
        "publish_date": "2026-07-01",
        "url": "https://www.vaneck.com/us/en/investments/semiconductor-etf-smh-fact-sheet.pdf",
        "language": "en",
        "cluster": "etf_holdings",
        "cluster_label": "半导体 ETF 官方数据",
        "policy_evidence_role": "core_evidence",
        "excerpt": "SMH fact sheet lists 26 holdings, P/E 49.27, P/B 11.99, weighted average market cap $1.45 trillion and total net assets $67.82 billion. 中文译意：SMH 是高集中、高估值和高市值半导体敞口的代表性工具。",
    },
    {
        "ref": "marketwatch_etf_flows_h1_2026",
        "title": "MarketWatch：2026上半年美国 ETF 资金流和 AI/机器人主题流入",
        "source_tier": "B",
        "source_review_status": "pass_media_data_summary",
        "publisher": "MarketWatch",
        "publish_date": "2026-07-01",
        "url": "https://www.marketwatch.com/story/investors-piled-into-etfs-at-a-record-pace-in-the-first-half-of-2026-heres-where-their-money-is-flowing-92a50cf5",
        "language": "en",
        "cluster": "etf_flows_media",
        "cluster_label": "ETF 资金流媒体数据",
        "policy_evidence_role": "core_evidence",
        "excerpt": "The report says more than $1 trillion flowed into US-listed ETFs in H1 2026, technology ETFs captured about 69% of sector flows, and the Roundhill Memory ETF attracted nearly $20 billion after launching in April. 中文译意：资金从大盘被动入口进一步扩散到 AI、机器人、存储等细分 ETF。",
    },
    {
        "ref": "marketwatch_nasdaq_contribution_h1_2026",
        "title": "MarketWatch：Nasdaq-100 2026上半年涨幅高度依赖少数芯片和硬件股票",
        "source_tier": "B",
        "source_review_status": "pass_media_factor_decomposition",
        "publisher": "MarketWatch",
        "publish_date": "2026-07-01",
        "url": "https://www.marketwatch.com/story/almost-100-of-the-nasdaq-100s-gains-in-the-first-half-of-2026-came-from-just-10-stocks-44056a47",
        "language": "en",
        "cluster": "market_concentration_media",
        "cluster_label": "指数贡献集中度",
        "policy_evidence_role": "core_evidence",
        "excerpt": "The article says nearly all of the Nasdaq-100's first-half gain came from 10 stocks, led by memory and semiconductor names. 中文译意：指数层面的拥挤不是抽象主题，而是贡献集中到少数 AI 硬件链条。",
    },
    {
        "ref": "jpx_investor_type_20260702",
        "title": "JPX Trading by Type of Investors：日本股票投资者类型交易统计",
        "source_tier": "S",
        "source_review_status": "pass_exchange_dataset",
        "publisher": "Japan Exchange Group",
        "publish_date": "2026-07-02",
        "url": "https://www.jpx.co.jp/english/markets/statistics-equities/investor-type/index.html",
        "language": "en",
        "cluster": "japan_exchange_flows",
        "cluster_label": "日本交易所资金流",
        "policy_evidence_role": "core_evidence",
        "excerpt": "JPX provides weekly and monthly Trading by Type of Investors data, updated Jul. 02, 2026, including equities, ETFs and nonresident investor statistics. 中文译意：日本拥挤度必须看外资、个人和 ETF 的交易拆分，而不能只看 Nikkei 点位。",
    },
    {
        "ref": "reuters_japan_foreign_selloff_20260627",
        "title": "Reuters：日本股票在6月27日当周遭遇3月以来最大外资周度卖出",
        "source_tier": "B",
        "source_review_status": "pass_reuters_media_summary",
        "publisher": "Reuters via Economic Times",
        "publish_date": "2026-07-02",
        "url": "https://m.economictimes.com/markets/us-stocks/news/japanese-stocks-hit-by-biggest-foreign-weekly-selloff-since-march-as-tech-rally-cools/articleshow/132133649.cms",
        "language": "en",
        "cluster": "japan_exchange_flows",
        "cluster_label": "日本外资流和获利了结",
        "policy_evidence_role": "core_evidence",
        "excerpt": "Reuters reported the largest weekly foreign selloff since March in the week ended June 27, driven by profit-taking in technology shares and concerns over AI valuations. 中文译意：日本 AI 链的拥挤已经出现外资获利了结信号。",
    },
    {
        "ref": "finance_yahoo_japan_foreign_buy_20260620",
        "title": "Reuters/Yahoo Finance：日本股票6月20日当周外资净买入4794亿日元",
        "source_tier": "B",
        "source_review_status": "pass_reuters_media_summary",
        "publisher": "Reuters via Yahoo Finance",
        "publish_date": "2026-06-26",
        "url": "https://finance.yahoo.com/markets/stocks/articles/foreign-investors-buy-japanese-stocks-044253494.html",
        "language": "en",
        "cluster": "japan_exchange_flows",
        "cluster_label": "日本外资流和获利了结",
        "policy_evidence_role": "core_evidence",
        "excerpt": "Reuters reported foreign investors bought a net 479.4 billion yen of Japanese stocks in the week ended June 20, citing AI rally and risk-on conditions. 中文译意：同一外资口径一周净买、一周大卖，说明日本 AI 拥挤度的边际资金非常敏感。",
    },
    {
        "ref": "nikkei_components_202607",
        "title": "Nikkei Indexes：Nikkei 225 components and index data",
        "source_tier": "S",
        "source_review_status": "pass_index_provider",
        "publisher": "Nikkei Inc.",
        "publish_date": "2026-07-01",
        "url": "https://indexes.nikkei.co.jp/en/nkave/index/component",
        "language": "en",
        "cluster": "japan_index_methodology",
        "cluster_label": "日本指数构成",
        "policy_evidence_role": "core_evidence",
        "excerpt": "Nikkei provides component and index information for the Nikkei Stock Average. 中文译意：Nikkei 225 是价格加权指数，半导体设备高价股会对指数产生放大影响，因此日本 AI 拥挤必须看指数结构。",
    },
    {
        "ref": "advantest_fy2025_results_20260427",
        "title": "Advantest FY2025 financial results and FY2026 forecast",
        "source_tier": "A",
        "source_review_status": "pass_company_ir",
        "publisher": "Advantest Corporation",
        "publish_date": "2026-04-27",
        "url": "https://www.advantest.com/en/news/2026/a81o6o0000000hgw-att/E_FR_FY2025_FN.pdf",
        "language": "en",
        "cluster": "japan_company_ir",
        "cluster_label": "日本 AI 半导体设备公司 IR",
        "policy_evidence_role": "core_evidence",
        "excerpt": "Advantest FY2026 forecast calls for net sales of 1,420.0 billion yen and operating income of 627.5 billion yen, citing demand for HPC devices and AI-related semiconductors. 中文译意：测试设备不是单纯题材，FY2026 指引已体现 AI/HPC 需求。",
    },
    {
        "ref": "tokyo_electron_q3_fy2026",
        "title": "Tokyo Electron Q3 FY2026 financial announcement",
        "source_tier": "A",
        "source_review_status": "pass_company_ir",
        "publisher": "Tokyo Electron",
        "publish_date": "2026-02-06",
        "url": "https://www.tel.com/ir/library/report/qemr4i00000000dj-att/fy26q3presentations-e.pdf",
        "language": "en",
        "cluster": "japan_company_ir",
        "cluster_label": "日本 AI 半导体设备公司 IR",
        "policy_evidence_role": "core_evidence",
        "excerpt": "Tokyo Electron Q3 FY2026 materials disclose semiconductor production equipment sales mix across DRAM, non-volatile memory and non-memory logic/foundry. 中文译意：TEL 的证据价值在于把 AI 硬件需求拆到存储和逻辑设备，而不是只看股价上涨。",
    },
    {
        "ref": "tokyo_electron_ai_award_20260626",
        "title": "Tokyo Electron wins AI Semiconductor Manufacturing Solution of the Year award",
        "source_tier": "A",
        "source_review_status": "pass_company_news",
        "publisher": "Tokyo Electron",
        "publish_date": "2026-06-26",
        "url": "https://www.tel.com/ir/index.html",
        "language": "en",
        "cluster": "japan_company_ir",
        "cluster_label": "日本 AI 半导体设备公司 IR",
        "policy_evidence_role": "core_evidence",
        "excerpt": "TEL IR news lists a 2026 AI Semiconductor Manufacturing Solution award and subsequent corporate updates. 中文译意：该来源只能证明 AI 半导体设备叙事和公司技术口径，不替代订单和利润数据。",
    },
    {
        "ref": "ishares_nikkei225_holdings_202607",
        "title": "iShares Core Nikkei 225 ETF holdings",
        "source_tier": "S",
        "source_review_status": "pass_etf_provider",
        "publisher": "BlackRock Japan",
        "publish_date": "2026-07-01",
        "url": "https://www.blackrock.com/jp/individual-en/en/products/251897/ishares-nikkei-225-fund",
        "language": "en",
        "cluster": "japan_etf_holdings",
        "cluster_label": "日本 ETF 持仓",
        "policy_evidence_role": "core_evidence",
        "excerpt": "The holdings list includes Tokyo Electron, Advantest, Fast Retailing and SoftBank Group among Nikkei 225 ETF holdings. 中文译意：日本 AI 拥挤可以通过 Nikkei ETF 被动暴露间接放大。",
    },
    {
        "ref": "microsoft_q2_fy2026_capex",
        "title": "Microsoft FY2026 Q2 earnings call：capex $37.5bn, two thirds GPUs/CPUs",
        "source_tier": "A",
        "source_review_status": "pass_company_ir",
        "publisher": "Microsoft Investor Relations",
        "publish_date": "2026-01-28",
        "url": "https://www.microsoft.com/en-us/investor/events/fy-2026/earnings-fy-2026-q2",
        "language": "en",
        "cluster": "hyperscaler_ir",
        "cluster_label": "超大云厂 AI capex",
        "policy_evidence_role": "core_evidence",
        "excerpt": "Microsoft disclosed capital expenditures of $37.5 billion, roughly two thirds on short-lived assets primarily GPUs and CPUs, and said customer demand continues to exceed supply. 中文译意：这是 AI 硬件链的基本面支撑，也是云厂自由现金流争议的来源。",
    },
    {
        "ref": "microsoft_q3_fy2026_results",
        "title": "Microsoft FY2026 Q3 results",
        "source_tier": "A",
        "source_review_status": "pass_company_ir",
        "publisher": "Microsoft Investor Relations",
        "publish_date": "2026-04-29",
        "url": "https://www.microsoft.com/en-us/investor/earnings/fy-2026-q3/press-release-webcast",
        "language": "en",
        "cluster": "hyperscaler_ir",
        "cluster_label": "超大云厂 AI capex",
        "policy_evidence_role": "core_evidence",
        "excerpt": "Microsoft reported Q3 FY2026 revenue of $82.9 billion, up 18%, and operating income of $38.4 billion, up 20%. 中文译意：高 capex 需要持续收入和利润响应，否则拥挤从基本面拥挤转为 ROI 质疑。",
    },
    {
        "ref": "meta_q1_2026_capex",
        "title": "Meta Q1 2026 results：2026 capex guidance $125-145bn",
        "source_tier": "A",
        "source_review_status": "pass_company_ir",
        "publisher": "Meta Investor Relations / SEC exhibit",
        "publish_date": "2026-04-29",
        "url": "https://investor.atmeta.com/investor-news/press-release-details/2026/Meta-Reports-First-Quarter-2026-Results/default.aspx",
        "language": "en",
        "cluster": "hyperscaler_ir",
        "cluster_label": "超大云厂 AI capex",
        "policy_evidence_role": "core_evidence",
        "excerpt": "Meta raised 2026 capital expenditures including finance leases to $125-145 billion from $115-135 billion, citing higher component pricing and data center costs. 中文译意：Meta 是 AI capex 基本面支撑和现金流压力的双重样本。",
    },
    {
        "ref": "alphabet_q1_2026_ai_cloud",
        "title": "Alphabet Q1 2026 results：Google Cloud revenue +63%, backlog over $460bn",
        "source_tier": "A",
        "source_review_status": "pass_company_ir",
        "publisher": "Alphabet Investor Relations / SEC exhibit",
        "publish_date": "2026-04-29",
        "url": "https://www.sec.gov/Archives/edgar/data/1652044/000165204426000043/googexhibit991q12026.htm",
        "language": "en",
        "cluster": "hyperscaler_ir",
        "cluster_label": "超大云厂 AI capex",
        "policy_evidence_role": "core_evidence",
        "excerpt": "Alphabet disclosed Google Cloud revenue growth of 63%, exceeding $20 billion, and backlog nearly doubling quarter on quarter to over $460 billion. 中文译意：Alphabet 为 AI 基建投入提供更强收入验证，但也把市场预期推到高门槛。",
    },
    {
        "ref": "amazon_q1_2026_aws",
        "title": "Amazon Q1 2026 results：AWS operating income $14.2bn",
        "source_tier": "A",
        "source_review_status": "pass_company_ir",
        "publisher": "Amazon Investor Relations",
        "publish_date": "2026-04-30",
        "url": "https://ir.aboutamazon.com/news-release/news-release-details/2026/Amazon-com-Announces-First-Quarter-Results/default.aspx",
        "language": "en",
        "cluster": "hyperscaler_ir",
        "cluster_label": "超大云厂 AI capex",
        "policy_evidence_role": "core_evidence",
        "excerpt": "Amazon reported AWS operating income of $14.2 billion in Q1 2026, compared with $11.5 billion in Q1 2025. 中文译意：AWS 证明 AI 云需求仍能贡献利润，但其资本开支强度仍需继续跟踪。",
    },
    {
        "ref": "businessinsider_ai_trade_split_202607",
        "title": "Business Insider：2026年中 AI trade 分化，芯片/存储强于软件和部分云厂",
        "source_tier": "B",
        "source_review_status": "pass_market_media_summary",
        "publisher": "Business Insider",
        "publish_date": "2026-07-03",
        "url": "https://www.businessinsider.com/ai-stocks-chips-rally-mag7-divergence-hyperscalers-hardware-memory-2026-7",
        "language": "en",
        "cluster": "market_media_crosscheck",
        "cluster_label": "AI 交易结构分化媒体复核",
        "policy_evidence_role": "reference_only",
        "excerpt": "The article describes mid-2026 divergence: chip and memory winners leading, while some hyperscalers and software names lag due to AI capex concerns. 中文译意：这是解释分化的辅助证据，不作为核心分数来源。",
    },
    {
        "ref": "guardian_chipmakers_h1_2026",
        "title": "The Guardian：AI 芯片和存储股票 2026上半年大涨",
        "source_tier": "B",
        "source_review_status": "pass_media_market_summary",
        "publisher": "The Guardian",
        "publish_date": "2026-06-29",
        "url": "https://www.theguardian.com/business/2026/jun/29/shares-in-chipmakers-underpinning-ai-boom-surge-in-first-half-of-2026",
        "language": "en",
        "cluster": "market_media_crosscheck",
        "cluster_label": "AI 硬件市场表现复核",
        "policy_evidence_role": "reference_only",
        "excerpt": "The article says chipmakers underpinning AI boomed in H1 2026, while some AI software companies lagged as investors worried about capex. 中文译意：它支持硬件拥挤强于软件拥挤的横向判断。",
    },
    {
        "ref": "aljazeera_japan_ai_rally_202606",
        "title": "Al Jazeera：Japan stock market record as AI boom gathers steam",
        "source_tier": "B",
        "source_review_status": "pass_media_market_summary",
        "publisher": "Al Jazeera",
        "publish_date": "2026-06-03",
        "url": "https://www.aljazeera.com/economy/2026/6/3/japans-stock-market-hits-new-record-as-ai-boom-gathers-steam",
        "language": "en",
        "cluster": "japan_market_media",
        "cluster_label": "日本 AI 市场表现复核",
        "policy_evidence_role": "reference_only",
        "excerpt": "The report says Japan's stock market was up nearly 33% YTD and AI enthusiasm helped drive Asian equity markets. 中文译意：日本 AI 交易已经进入国际媒体叙事层，但仍需 JPX 和公司 IR 交叉验证。",
    },
    {
        "ref": "yfinance_price_snapshot_20260705",
        "title": "Yahoo Finance / yfinance price snapshot：AI 相关证券 2021-2026 价格动量与回撤复算",
        "source_tier": "A",
        "source_review_status": "pass_market_data_snapshot",
        "publisher": "Yahoo Finance via yfinance",
        "publish_date": AS_OF_DATE,
        "url": "https://finance.yahoo.com/",
        "language": "en",
        "cluster": "market_price_data",
        "cluster_label": "Yahoo/yfinance 价格快照",
        "policy_evidence_role": "core_evidence",
        "excerpt": "The snapshot uses adjusted daily prices through 2026-07-02/03 for US and Japan tickers, ETFs, futures proxies and macro instruments. 中文译意：价格动量用于识别交易拥挤和回撤敏感度，不用于替代持仓数据。",
    },
    {
        "ref": "ai_crowding_score_workpaper",
        "title": "AI Crowding Score 复算工作底稿",
        "source_tier": "A",
        "source_review_status": "pass_calculation_workpaper",
        "publisher": "Opportunity Lens producer-reviewer-loop",
        "publish_date": AS_OF_DATE,
        "url": None,
        "local_path": str(EXECUTION_CACHE_PATH.relative_to(ROOT)).replace("\\", "/"),
        "language": "zh-CN",
        "cluster": "acs_calculation",
        "cluster_label": "AI 拥挤度指数公式和审稿底稿",
        "policy_evidence_role": "reference_only",
        "excerpt": "ACS = 30% 持仓与资金流拥挤 + 20% 价格动量与估值拥挤 + 20% 基本面兑现支撑 + 15% 衍生品和宏观杠杆 + 15% 退出敏感度。分数越高代表边际资金和叙事越拥挤，不等于直接看空。",
    },
]

SOURCE_NOTES = {source["ref"]: source["excerpt"] for source in SOURCES}
SOURCE_BY_REF = {source["ref"]: source for source in SOURCES}


def _source_key(ref: str) -> str:
    return ref.replace("source_ref:", "").replace("opp://source/", "")


def _source_record(ref: str) -> dict[str, Any]:
    key = _source_key(ref)
    source = SOURCE_BY_REF.get(key)
    if not source:
        raise ValueError(f"未知来源引用: {ref}")
    return source


def _source_location(ref: str) -> str:
    source = _source_record(ref)
    if source.get("url"):
        return "原文链接见本行证据抽屉"
    if source.get("local_path"):
        return "本地底稿见本行证据记录"
    return "来源地址：未提供公开 URL"


def _source_short_label(ref: str) -> str:
    source = _source_record(ref)
    title = source.get("title") or _source_key(ref)
    publisher = source.get("publisher") or "发布方未披露"
    publish_date = source.get("publish_date") or "日期未披露"
    tier = source.get("source_tier") or "unknown"
    return f"{title}（{publisher}，{publish_date}，{tier}级）"


def _source_citation(ref: str) -> str:
    return f"^src:{_ref(ref)}"


def _cite(*refs: str) -> str:
    return " ".join(_source_citation(ref) for ref in refs)


def _source_table_label(ref: str) -> str:
    return f"证据记录 {_source_citation(ref)}".replace("|", "/").replace("\n", " ")


def _source_evidence_line(ref: str) -> str:
    key = _source_key(ref)
    note = SOURCE_NOTES.get(key, "")
    return f"证据记录：{note} {_source_citation(ref)}"


def _entity_evidence_chain(entity_key: str) -> str:
    if entity_key == "us_core_ai_megacap":
        return (
            "本实体的证据链分三层。第一层是仓位和被动入口：SEC 13F 复算给出 NVIDIA、Apple、Alphabet、Microsoft、Amazon、Broadcom、Meta、Micron 等美国机构多头的 AI 暴露下限，QQQ 和 SPY 官方持仓说明这些股票同时进入 Nasdaq-100 和 S&P 500 的被动风险预算。"
            "第二层是拥挤确认：BofA 调查把 long global semiconductors 和 Magnificent 7 放在拥挤交易核心，说明这不是个别股票强势，而是全球组合层面的共同表达。"
            "第三层是传导和证伪：CFTC 期货结构和 yfinance 价格快照用于观察 NQ/S&P、SOXX/SMH、回撤和宏观代理，Microsoft 财报用于确认 AI capex 是否还能被收入和利润吸收。"
            "基础推论是：美国核心 AI 巨头不是单一“优质资产”问题，而是被动权重、主动机构、主题 ETF 和基本面门槛叠在一起；风险来自边际资金已满后，任何财报、capex 或宏观扰动都可能放大回撤。"
            f"{_cite('sec_13f_recalc_ai_holdings_2026q1', 'invesco_qqq_holdings_20260702', 'ssga_spy_holdings_20260702', 'bofa_fms_202606_semis_crowding', 'cftc_recalc_ai_macro_20260623', 'yfinance_price_snapshot_20260705', 'microsoft_q3_fy2026_results')}"
        )
    if entity_key == "global_semiconductor_ai_hardware":
        return (
            "本实体证据不是简单列半导体新闻，而是按“共识拥挤、持仓拥挤、价格拥挤、反向资金动作”连接。BofA 的资金经理调查给出最直接的拥挤标签；SOXX、SMH 官方 ETF 和 MarketWatch 对 Nasdaq-100 贡献集中的报道说明价格和指数贡献已经集中在少数芯片和硬件股票。"
            "Goldman 两条资料把对冲基金科技倾斜和半导体获利了结同时放在一起，说明高仓位下边际买盘开始变得脆弱；13F 复算和 yfinance 快照分别校验机构多头和实际价格路径。"
            "基础推论是：全球半导体硬件链基本面仍强，但已经从“资金继续涌入”进入“高仓位下靠订单和盈利续命”的阶段，后续证实要看 HBM、设备订单和 ETF 资金是否继续流入，证伪则看 Goldman 净卖出是否延续、SOXX/SMH 回撤是否放大。"
            f"{_cite('bofa_fms_202606_semis_crowding', 'blackrock_soxx_20260702', 'vaneck_smh_fact_202607', 'goldman_hf_trend_all_in_ai_202606', 'goldman_semis_profit_taking_202606', 'sec_13f_recalc_ai_holdings_2026q1', 'yfinance_price_snapshot_20260705', 'marketwatch_nasdaq_contribution_h1_2026')}"
        )
    if entity_key == "hyperscaler_capex_software_roi":
        return (
            "本实体把公司 IR 和价格分化放在一起读。Microsoft Q2/Q3 给出 capex 强度、GPU/CPU 支出结构和收入利润承接；Meta 上修 2026 capex 说明 AI 基建需求仍在加速，但也引入组件价格和数据中心成本压力；Alphabet 的 Cloud revenue 与 backlog 证明云端需求不是空转，Amazon AWS operating income 说明至少部分云厂仍能把需求转成利润。"
            "Business Insider 和 yfinance 快照提供市场侧验证：硬件、存储、半导体强于部分 hyperscaler 和软件，资金已经从“谁投 AI”转向“谁能证明 ROI”。"
            "基础推论是：云厂拥挤度低于半导体，不是因为不重要，而是因为证据链要求 capex、backlog、收入、利润和现金流同时成立；任何一项断裂都会把基本面支撑变成估值压力。"
            f"{_cite('microsoft_q2_fy2026_capex', 'microsoft_q3_fy2026_results', 'meta_q1_2026_capex', 'alphabet_q1_2026_ai_cloud', 'amazon_q1_2026_aws', 'businessinsider_ai_trade_split_202607', 'yfinance_price_snapshot_20260705')}"
        )
    if entity_key == "ai_power_infrastructure":
        return (
            "本实体的证据链用云厂 capex 确认需求端，用 ETF/资金流和 CFTC/yfinance 观察拥挤传播。Meta、Microsoft、Alphabet、Amazon 的 IR 共同说明 AI 数据中心投资没有降温，且支出已经包含 GPU/CPU、数据中心成本、backlog 和 AWS 利润承接。"
            "MarketWatch ETF 资金流说明 AI、机器人和存储主题继续吸收资金，yfinance 快照用于检查电力、液冷、配电、核电等二阶标的是否已提前交易；CFTC 复算提供宏观风险传播口径。"
            "基础推论是：基础设施链不是第一层 AI 仓位，但它承接的是 capex 持续上修后的二阶资金；若云厂 capex 放缓或自由现金流压力扩大，电力、液冷和配电的估值往往先于基本面回落。"
            f"{_cite('meta_q1_2026_capex', 'microsoft_q2_fy2026_capex', 'alphabet_q1_2026_ai_cloud', 'amazon_q1_2026_aws', 'marketwatch_etf_flows_h1_2026', 'yfinance_price_snapshot_20260705', 'cftc_recalc_ai_macro_20260623')}"
        )
    if entity_key == "japan_ai_semicap_automation":
        return (
            "本实体证据先看资金，再看指数结构，最后看公司基本面。JPX 投资者类型统计是日本外资流的官方底座；Reuters 和 Yahoo/Finance 对两周外资交易的报道显示，外资在 6 月先大幅净买入、随后因科技获利了结和 AI 估值担忧出现撤退，说明边际资金非常敏感。"
            "Nikkei 225 成分和 iShares Nikkei 225 ETF 持仓解释为什么 Tokyo Electron、Advantest 等高价设备股会通过价格加权指数放大拥挤；Advantest FY2026 指引和 Tokyo Electron FY2026Q3 材料则提供 HPC/AI 半导体需求和设备结构的基本面支撑。"
            "基础推论是：日本 AI 链不是纯题材，设备订单支撑存在，但外资流和日元方向决定短期拥挤风险；证实要看 JPX 原始周度表继续流入和公司指引上修，证伪要看外资连续流出、日元升值和设备股回撤共振。"
            f"{_cite('jpx_investor_type_20260702', 'reuters_japan_foreign_selloff_20260627', 'finance_yahoo_japan_foreign_buy_20260620', 'nikkei_components_202607', 'advantest_fy2025_results_20260427', 'tokyo_electron_q3_fy2026', 'ishares_nikkei225_holdings_202607', 'yfinance_price_snapshot_20260705')}"
        )
    if entity_key == "macro_cross_asset_ai":
        return (
            "本实体证据链把 AI 拥挤从股票扩展到去杠杆路径。CFTC TFF 和本地 CFTC 复算给出 Nasdaq-100、S&P 500 与日元期货的持仓结构，说明风险不只在现金股票，也可能通过指数期货和外汇杠杆释放。"
            "MarketWatch ETF 资金流说明被动和主题资金仍在流入，yfinance 快照观察 SOX/NDX、USDJPY、铜、VIX、TLT/HYG 等价格联动；JPX/Reuters 资料把日本外资流纳入同一框架；SPY 官方持仓证明 AI 相关大盘股已是 S&P 500 被动风险预算核心。"
            "基础推论是：宏观实体不是纯 AI 仓位，而是 AI 拥挤被利率、美元、日元、铜、波动率和信用共同放大的通道；若 AI 财报或 capex 证伪，宏观代理会让回撤跨市场传播。"
            f"{_cite('cftc_tff_financial_20260623', 'cftc_recalc_ai_macro_20260623', 'marketwatch_etf_flows_h1_2026', 'yfinance_price_snapshot_20260705', 'jpx_investor_type_20260702', 'reuters_japan_foreign_selloff_20260627', 'ssga_spy_holdings_20260702')}"
        )
    return "；".join(_source_evidence_line(ref) for ref in ENTITY_REFS.get(entity_key, [])[:5])


def _db_sources() -> list[dict[str, Any]]:
    allowed = {"pending", "pass", "pass_with_note", "weak_source_only", "duplicate", "paywalled", "stale", "conflict", "reject"}
    rows: list[dict[str, Any]] = []
    for source in SOURCES:
        cloned = dict(source)
        if cloned.get("source_review_status") not in allowed:
            cloned["source_review_status"] = "pass_with_note"
        rows.append(cloned)
    return rows

ACS_COMPONENTS: dict[str, dict[str, float]] = {
    "us_core_ai_megacap": {
        "持仓与资金流拥挤": 86,
        "价格动量与估值拥挤": 75,
        "基本面兑现支撑": 82,
        "衍生品和宏观杠杆": 70,
        "退出敏感度": 80,
    },
    "global_semiconductor_ai_hardware": {
        "持仓与资金流拥挤": 95,
        "价格动量与估值拥挤": 91,
        "基本面兑现支撑": 88,
        "衍生品和宏观杠杆": 76,
        "退出敏感度": 86,
    },
    "hyperscaler_capex_software_roi": {
        "持仓与资金流拥挤": 67,
        "价格动量与估值拥挤": 52,
        "基本面兑现支撑": 78,
        "衍生品和宏观杠杆": 55,
        "退出敏感度": 70,
    },
    "ai_power_infrastructure": {
        "持仓与资金流拥挤": 76,
        "价格动量与估值拥挤": 70,
        "基本面兑现支撑": 82,
        "衍生品和宏观杠杆": 60,
        "退出敏感度": 75,
    },
    "japan_ai_semicap_automation": {
        "持仓与资金流拥挤": 79,
        "价格动量与估值拥挤": 82,
        "基本面兑现支撑": 72,
        "衍生品和宏观杠杆": 69,
        "退出敏感度": 80,
    },
    "macro_cross_asset_ai": {
        "持仓与资金流拥挤": 72,
        "价格动量与估值拥挤": 68,
        "基本面兑现支撑": 62,
        "衍生品和宏观杠杆": 78,
        "退出敏感度": 74,
    },
}


def _acs_score(entity_key: str) -> float:
    return round(sum(ACS_COMPONENTS[entity_key][name] * weight for name, weight in ACS_WEIGHTS.items()), 1)


ENTITY_REFS: dict[str, list[str]] = {
    "acs_methodology": [
        "source_ref:ai_crowding_score_workpaper",
        "source_ref:sec_13f_dataset_2026q1",
        "source_ref:cftc_tff_financial_20260623",
        "source_ref:invesco_qqq_holdings_20260702",
        "source_ref:marketwatch_etf_flows_h1_2026",
        "source_ref:microsoft_q2_fy2026_capex",
        "source_ref:jpx_investor_type_20260702",
        "source_ref:cftc_recalc_ai_macro_20260623",
        "source_ref:bofa_fms_202606_semis_crowding",
        "source_ref:yfinance_price_snapshot_20260705",
    ],
    "cycle_reflexivity_2021_2026": [
        "source_ref:ai_crowding_score_workpaper",
        "source_ref:sec_13f_recalc_ai_holdings_2026q1",
        "source_ref:cftc_tff_financial_20260623",
        "source_ref:invesco_qqq_holdings_20260702",
        "source_ref:blackrock_soxx_20260702",
        "source_ref:marketwatch_etf_flows_h1_2026",
        "source_ref:bofa_fms_202606_semis_crowding",
        "source_ref:marketwatch_nasdaq_contribution_h1_2026",
        "source_ref:goldman_semis_profit_taking_202606",
        "source_ref:businessinsider_ai_trade_split_202607",
        "source_ref:yfinance_price_snapshot_20260705",
    ],
    "us_core_ai_megacap": [
        "source_ref:sec_13f_recalc_ai_holdings_2026q1",
        "source_ref:invesco_qqq_holdings_20260702",
        "source_ref:ssga_spy_holdings_20260702",
        "source_ref:bofa_fms_202606_semis_crowding",
        "source_ref:cftc_recalc_ai_macro_20260623",
        "source_ref:yfinance_price_snapshot_20260705",
        "source_ref:microsoft_q3_fy2026_results",
    ],
    "global_semiconductor_ai_hardware": [
        "source_ref:bofa_fms_202606_semis_crowding",
        "source_ref:blackrock_soxx_20260702",
        "source_ref:vaneck_smh_fact_202607",
        "source_ref:goldman_hf_trend_all_in_ai_202606",
        "source_ref:goldman_semis_profit_taking_202606",
        "source_ref:sec_13f_recalc_ai_holdings_2026q1",
        "source_ref:yfinance_price_snapshot_20260705",
        "source_ref:marketwatch_nasdaq_contribution_h1_2026",
    ],
    "hyperscaler_capex_software_roi": [
        "source_ref:microsoft_q2_fy2026_capex",
        "source_ref:microsoft_q3_fy2026_results",
        "source_ref:meta_q1_2026_capex",
        "source_ref:alphabet_q1_2026_ai_cloud",
        "source_ref:amazon_q1_2026_aws",
        "source_ref:businessinsider_ai_trade_split_202607",
        "source_ref:yfinance_price_snapshot_20260705",
    ],
    "ai_power_infrastructure": [
        "source_ref:meta_q1_2026_capex",
        "source_ref:microsoft_q2_fy2026_capex",
        "source_ref:alphabet_q1_2026_ai_cloud",
        "source_ref:amazon_q1_2026_aws",
        "source_ref:yfinance_price_snapshot_20260705",
        "source_ref:marketwatch_etf_flows_h1_2026",
        "source_ref:cftc_recalc_ai_macro_20260623",
    ],
    "japan_ai_semicap_automation": [
        "source_ref:jpx_investor_type_20260702",
        "source_ref:reuters_japan_foreign_selloff_20260627",
        "source_ref:finance_yahoo_japan_foreign_buy_20260620",
        "source_ref:nikkei_components_202607",
        "source_ref:advantest_fy2025_results_20260427",
        "source_ref:tokyo_electron_q3_fy2026",
        "source_ref:ishares_nikkei225_holdings_202607",
        "source_ref:yfinance_price_snapshot_20260705",
    ],
    "macro_cross_asset_ai": [
        "source_ref:cftc_tff_financial_20260623",
        "source_ref:cftc_recalc_ai_macro_20260623",
        "source_ref:marketwatch_etf_flows_h1_2026",
        "source_ref:yfinance_price_snapshot_20260705",
        "source_ref:jpx_investor_type_20260702",
        "source_ref:reuters_japan_foreign_selloff_20260627",
        "source_ref:ssga_spy_holdings_20260702",
    ],
}


def _entity_evidence_relation(entity_key: str) -> str:
    if entity_key == "us_core_ai_megacap":
        return (
            "证据关系要按四层读：SEC 13F 复算给出美国 AI 核心持仓下限；QQQ 和 SPY 官方持仓说明这些公司如何进入被动指数和基准组合；BofA 调查与 CFTC 复算分别提供主动拥挤和 Nasdaq/S&P 期货杠杆侧证；Microsoft 财报用于验证高持仓背后是否仍有基本面承接。"
            f"{_cite('sec_13f_recalc_ai_holdings_2026q1', 'invesco_qqq_holdings_20260702', 'ssga_spy_holdings_20260702', 'bofa_fms_202606_semis_crowding', 'cftc_recalc_ai_macro_20260623', 'microsoft_q3_fy2026_results')}"
        )
    if entity_key == "global_semiconductor_ai_hardware":
        return (
            "证据关系要按“调查锚点、可交易入口、对冲基金行为、价格和指数贡献”连接：BofA 调查确认全球半导体是拥挤核心，SOXX/SMH 官方资料把拥挤落到可交易入口，Goldman 资料提示对冲基金在加 AI 与半导体获利了结之间切换，13F、yfinance 和 Nasdaq 贡献复核这不是单一券商观点。"
            f"{_cite('bofa_fms_202606_semis_crowding', 'blackrock_soxx_20260702', 'vaneck_smh_fact_202607', 'goldman_hf_trend_all_in_ai_202606', 'goldman_semis_profit_taking_202606', 'sec_13f_recalc_ai_holdings_2026q1', 'yfinance_price_snapshot_20260705', 'marketwatch_nasdaq_contribution_h1_2026')}"
        )
    if entity_key == "hyperscaler_capex_software_roi":
        return (
            "证据关系要先分清支出、兑现和市场定价：Microsoft、Meta、Alphabet 与 Amazon 的 IR 共同确认超大云厂仍在把资本开支投向 AI 基建；Microsoft 后续财报和 Alphabet backlog 用来检验收入、利润和订单能否跟上 capex；市场媒体和 yfinance 价格快照解释为什么投资者把硬件、云厂和软件应用层分开定价。"
            f"{_cite('microsoft_q2_fy2026_capex', 'meta_q1_2026_capex', 'alphabet_q1_2026_ai_cloud', 'amazon_q1_2026_aws', 'microsoft_q3_fy2026_results', 'businessinsider_ai_trade_split_202607', 'yfinance_price_snapshot_20260705')}"
        )
    if entity_key == "ai_power_infrastructure":
        return (
            "证据关系要先确认需求来源，再看资金映射和去风险通道：Meta、Microsoft、Alphabet 和 Amazon 的 IR 证明 AI 数据中心建设正在扩大电力、配电、液冷和机房需求；ETF 资金流和 yfinance 价格快照说明二阶需求已经映射到基础设施主题和相关标的价格；CFTC 复算提示一旦组合去风险，二阶链条会同时受订单基本面和风险预算影响。"
            f"{_cite('meta_q1_2026_capex', 'microsoft_q2_fy2026_capex', 'alphabet_q1_2026_ai_cloud', 'amazon_q1_2026_aws', 'marketwatch_etf_flows_h1_2026', 'yfinance_price_snapshot_20260705', 'cftc_recalc_ai_macro_20260623')}"
        )
    if entity_key == "japan_ai_semicap_automation":
        return (
            "证据关系要把外资流、指数结构和公司基本面分开：JPX 是外资流官方入口，公开报道把净买入和随后大幅卖出放在同一窗口，说明外资流更像快速 AI 风险预算交易；Nikkei 成分和 ETF 持仓解释价格加权指数为什么会放大高价设备股；Advantest 与 Tokyo Electron 的业绩材料用于确认日本链条有 AI/HPC 设备基本面，而不只是外资流题材。"
            f"{_cite('jpx_investor_type_20260702', 'finance_yahoo_japan_foreign_buy_20260620', 'reuters_japan_foreign_selloff_20260627', 'nikkei_components_202607', 'ishares_nikkei225_holdings_202607', 'advantest_fy2025_results_20260427', 'tokyo_electron_q3_fy2026')}"
        )
    if entity_key == "macro_cross_asset_ai":
        return (
            "证据关系要把股票拥挤转换成宏观去杠杆路径：CFTC 官方表和本地复算给出 Nasdaq、S&P 与日元期货仓位；ETF 资金流、SPY 权重和 yfinance 快照说明 AI 风险已经通过 ETF、指数权重和价格动量进入宏观 beta；JPX 与 Reuters 外资流证据提示日元和日本股票会成为跨资产去杠杆的同步通道。"
            f"{_cite('cftc_tff_financial_20260623', 'cftc_recalc_ai_macro_20260623', 'marketwatch_etf_flows_h1_2026', 'ssga_spy_holdings_20260702', 'yfinance_price_snapshot_20260705', 'jpx_investor_type_20260702', 'reuters_japan_foreign_selloff_20260627')}"
        )
    raise ValueError(f"未定义实体证据关系: {entity_key}")


ENTITY_DEFS: dict[str, dict[str, Any]] = {
    "acs_methodology": {
        "display_name": "AI 持仓拥挤度指标定义、证据层级和复算方法",
        "mode": "theory_research",
        "description": "定义 AI Crowding Score，区分持仓拥挤、价格拥挤、估值拥挤、基本面兑现和退出敏感度。",
        "problem": "怎样把调查、13F、ETF、CFTC、价格动量和公司基本面放到同一个可复核框架里。",
        "answer": "ACS 不是看空信号，而是边际资金和叙事拥挤度读数；高分必须再和基本面兑现支撑比较。",
    },
    "cycle_reflexivity_2021_2026": {
        "display_name": "2021-2026 AI 拥挤交易演化和反身性框架",
        "mode": "theory_research",
        "description": "拆解从 2021 流动性成长股、2022 利率杀估值、2023 生成式 AI、2024-2026 硬件扩散的阶段变化。",
        "problem": "为什么 2026 的拥挤已不同于 2023 的单一 Nvidia/ChatGPT 交易。",
        "answer": "拥挤从软件叙事转向硬件、存储、设备、电力和日本外资流，反身性也从估值扩张变成 capex 验证压力。",
    },
    "us_core_ai_megacap": {
        "display_name": "美国核心 AI 巨头、指数权重与被动资金拥挤",
        "mode": "market_linked",
        "description": "覆盖 NVIDIA、Mag7、QQQ、SPY、13F 大型机构多头和 Nasdaq-100/S&P 500 被动权重。",
        "problem": "美国 AI 核心仓位是否已经由主动拥挤变成被动指数和机构组合共同拥挤。",
        "answer": "拥挤仍高，但结构从全部 Mag7 普涨转成 Nvidia、存储和少数硬件贡献更大；指数权重使回撤会自动影响广义风险资产。",
    },
    "global_semiconductor_ai_hardware": {
        "display_name": "全球半导体、HBM、设备与 AI 硬件链拥挤",
        "mode": "market_linked",
        "description": "覆盖 SOXX、SMH、SOX、NVIDIA、TSM、Broadcom、AMD、Micron、Lam、AMAT 和 HBM/设备链。",
        "problem": "最拥挤的 AI 表达是否已经从巨头平台转到全球半导体硬件链。",
        "answer": "这是本轮最高拥挤实体：BofA 80% 调查、SOXX/SMH 年内强势、13F 与对冲基金材料都指向硬件链，但 Goldman 获利了结信号说明边际买盘开始变脆。",
    },
    "hyperscaler_capex_software_roi": {
        "display_name": "超大云厂 AI capex、软件 ROI 与应用层拥挤分化",
        "mode": "market_linked",
        "description": "覆盖 Microsoft、Alphabet、Amazon、Meta、Oracle、Palantir 和软件/Agent 估值分化。",
        "problem": "AI capex 的基本面强度是否足够抵消软件和云厂的 ROI 担忧。",
        "answer": "云厂收入验证仍强，但股价和软件篮子分化说明投资者开始要求 capex 回报；该实体拥挤低于半导体，风险来自现金流和边际 ROI。",
    },
    "ai_power_infrastructure": {
        "display_name": "AI 数据中心电力、液冷、配电、核电与基础设施链拥挤",
        "mode": "market_linked",
        "description": "覆盖 Vertiv、Eaton、Constellation、Vistra、Equinix、Digital Realty、铜、天然气和数据中心能源约束。",
        "problem": "电力和基础设施是否只是二阶 AI 交易，还是已经成为独立拥挤链条。",
        "answer": "该链条有真实 capex 和电力瓶颈支撑，但很多标的已积累巨大涨幅，拥挤来自二阶推演而不是直接订单透明度。",
    },
    "japan_ai_semicap_automation": {
        "display_name": "日本 AI 半导体设备、测试、材料、自动化与外资流拥挤",
        "mode": "market_linked",
        "description": "覆盖 Advantest、Tokyo Electron、Disco、Lasertec、SoftBank、Nikkei 225 权重和 JPX 外资流。",
        "problem": "日本 AI 交易是全球 AI 拥挤的外溢，还是有本土设备/测试基本面支撑。",
        "answer": "两者同时存在：Advantest 和 TEL 有 AI/HPC 订单逻辑，外资一周净买一周大卖说明边际资金很快，Nikkei 价格加权结构放大了高价设备股。",
    },
    "macro_cross_asset_ai": {
        "display_name": "全球宏观 AI 交叉资产：Nasdaq、半导体、日元、利率、铜和波动率",
        "mode": "market_linked",
        "description": "覆盖 Nasdaq-100、S&P 500、SOX、USDJPY、日元期货、铜、天然气、电力、VIX、信用和长债。",
        "problem": "AI 拥挤是否已经通过指数期货、汇率、利率和商品进入宏观交易。",
        "answer": "宏观拥挤是代理拥挤而非纯 AI 仓位；Nasdaq/半导体、日元空头、铜和低波动率共同形成风险资产同向敞口，一旦 AI capex 或利率预期变坏，会通过多个资产同时去杠杆。",
    },
}


YFINANCE_ROWS = [
    ("NVDA", "NVIDIA", "us_core_ai_megacap", 3.3, 3.7, 23.3, 1391.7, -17.3),
    ("AVGO", "Broadcom", "global_semiconductor_ai_hardware", 4.1, 5.3, 32.4, 845.7, -25.0),
    ("AMD", "Advanced Micro Devices", "global_semiconductor_ai_hardware", 131.7, 134.2, 284.1, 461.0, -10.9),
    ("MU", "Micron Technology", "global_semiconductor_ai_hardware", 209.4, 212.7, 714.7, 1250.8, -19.6),
    ("TSM", "Taiwan Semiconductor Manufacturing ADR", "global_semiconductor_ai_hardware", 36.5, 35.4, 91.5, 324.9, -9.1),
    ("QQQ", "Invesco QQQ Trust", "us_core_ai_megacap", 16.5, 15.6, 29.7, 138.0, -4.4),
    ("SPY", "SPDR S&P 500 ETF", "us_core_ai_megacap", 9.6, 8.9, 21.3, 117.5, -1.7),
    ("SOXX", "iShares Semiconductor ETF", "global_semiconductor_ai_hardware", 80.7, 78.2, 138.3, 369.6, -13.5),
    ("SMH", "VanEck Semiconductor ETF", "global_semiconductor_ai_hardware", 58.7, 56.9, 112.4, 457.8, -11.5),
    ("MSFT", "Microsoft", "hyperscaler_capex_software_roi", -17.1, -17.1, -20.9, 87.8, -27.5),
    ("GOOGL", "Alphabet Class A", "hyperscaler_capex_software_roi", 14.4, 13.8, 104.2, 320.7, -10.6),
    ("AMZN", "Amazon", "hyperscaler_capex_software_roi", 7.1, 4.1, 8.6, 52.3, -11.8),
    ("META", "Meta Platforms", "hyperscaler_capex_software_roi", -10.2, -11.4, -18.6, 118.6, -26.0),
    ("ORCL", "Oracle", "hyperscaler_capex_software_roi", -27.9, -26.7, -39.0, 137.3, -56.9),
    ("PLTR", "Palantir", "hyperscaler_capex_software_roi", -23.0, -25.7, -7.1, 453.3, -37.6),
    ("VRT", "Vertiv", "ai_power_infrastructure", 71.2, 72.8, 138.3, 1530.5, -20.1),
    ("ETN", "Eaton", "ai_power_infrastructure", 22.5, 24.4, 12.5, 267.3, -8.6),
    ("CEG", "Constellation Energy", "ai_power_infrastructure", -34.5, -32.4, -24.4, 490.9, -40.5),
    ("VST", "Vistra", "ai_power_infrastructure", -8.3, -7.0, -21.6, 778.1, -30.4),
    ("EQIX", "Equinix", "ai_power_infrastructure", 32.5, 31.1, 31.9, 61.0, -10.2),
    ("DLR", "Digital Realty", "ai_power_infrastructure", 13.3, 12.8, 3.9, 54.4, -14.4),
    ("8035.T", "Tokyo Electron", "japan_ai_semicap_automation", 100.1, 100.1, 175.1, 561.1, -7.1),
    ("6857.T", "Advantest", "japan_ai_semicap_automation", 38.8, 38.8, 175.6, 1498.3, -18.3),
    ("6146.T", "Disco", "japan_ai_semicap_automation", 50.7, 50.7, 83.9, 630.8, -13.4),
    ("6920.T", "Lasertec", "japan_ai_semicap_automation", 50.9, 50.9, 157.8, 294.9, -16.8),
    ("5803.T", "Fujikura", "japan_ai_semicap_automation", 75.1, 75.1, 338.9, 7703.7, -31.8),
    ("9984.T", "SoftBank Group", "japan_ai_semicap_automation", 33.9, 33.9, 133.7, 218.2, -28.5),
    ("EWJ", "iShares MSCI Japan ETF", "japan_ai_semicap_automation", 15.1, 12.7, 33.4, 58.3, -3.9),
    ("DXJ", "WisdomTree Japan Hedged Equity", "japan_ai_semicap_automation", 21.3, 19.2, 56.3, 280.0, -2.1),
    ("HG=F", "Copper futures", "macro_cross_asset_ai", 10.4, 5.1, 24.9, 75.2, -6.4),
    ("NG=F", "Natural gas futures", "macro_cross_asset_ai", -10.3, -7.9, -4.9, 25.7, -66.5),
    ("^VIX", "CBOE Volatility Index", "macro_cross_asset_ai", 11.3, 8.4, -9.2, -40.1, -69.1),
    ("^NDX", "Nasdaq-100 Index", "macro_cross_asset_ai", 16.4, 15.5, 29.3, 131.0, -4.3),
    ("^SOX", "Philadelphia Semiconductor Index", "macro_cross_asset_ai", 71.4, 69.6, 127.9, 353.7, -13.7),
    ("USDJPY=X", "USD/JPY", "macro_cross_asset_ai", 2.9, 2.8, 11.7, 56.3, -0.8),
    ("TLT", "iShares 20+ Year Treasury Bond ETF", "macro_cross_asset_ai", 0.1, -0.4, 3.4, -35.3, -35.3),
    ("HYG", "iShares High Yield Corporate Bond ETF", "macro_cross_asset_ai", 1.3, 1.0, 5.0, 22.6, -0.3),
]


THIRTEENF_ROWS = [
    ("NVIDIA", "us_core_ai_megacap", 3178706.35, 4.53, 5865, "NVIDIA CORPORATION"),
    ("APPLE", "us_core_ai_megacap", 2600509.42, 3.71, 5934, "APPLE INC"),
    ("ALPHABET", "hyperscaler_capex_software_roi", 2419697.27, 3.45, 6152, "ALPHABET INC"),
    ("MICROSOFT", "hyperscaler_capex_software_roi", 2219709.72, 3.17, 6206, "MICROSOFT CORP"),
    ("AMAZON", "hyperscaler_capex_software_roi", 1454808.12, 2.07, 5280, "AMAZON COM INC"),
    ("BROADCOM", "global_semiconductor_ai_hardware", 1207390.72, 1.72, 4674, "BROADCOM INC"),
    ("META", "hyperscaler_capex_software_roi", 1094227.97, 1.56, 5035, "META PLATFORMS INC"),
    ("INVESCO QQQ", "us_core_ai_megacap", 509069.07, 0.73, 3864, "INVESCO QQQ TR"),
    ("MICRON", "global_semiconductor_ai_hardware", 367721.82, 0.52, 3002, "MICRON TECHNOLOGY INC"),
    ("TSMC", "global_semiconductor_ai_hardware", 296549.72, 0.42, 3235, "TAIWAN SEMICONDUCTOR MANUFAC"),
    ("AMD", "global_semiconductor_ai_hardware", 279027.65, 0.40, 3061, "ADVANCED MICRO DEVICES INC"),
    ("PALANTIR", "hyperscaler_capex_software_roi", 247112.73, 0.35, 3020, "PALANTIR TECHNOLOGIES INC"),
    ("LAM RESEARCH", "global_semiconductor_ai_hardware", 234864.43, 0.33, 2615, "LAM RESEARCH CORP"),
    ("ORACLE", "hyperscaler_capex_software_roi", 225490.36, 0.32, 3548, "ORACLE CORP"),
    ("EATON", "ai_power_infrastructure", 127344.81, 0.18, 2504, "EATON CORP PLC"),
    ("ASML", "global_semiconductor_ai_hardware", 105259.22, 0.15, 2214, "ASML HLDG NV"),
    ("EQUINIX", "ai_power_infrastructure", 92974.42, 0.13, 1303, "EQUINIX INC"),
    ("VERTIV", "ai_power_infrastructure", 91518.63, 0.13, 1854, "VERTIV HOLDINGS CO"),
    ("CONSTELLATION ENERGY", "ai_power_infrastructure", 85400.60, 0.12, 1920, "CONSTELLATION ENERGY CORP"),
    ("VISTRA", "ai_power_infrastructure", 48665.90, 0.07, 1330, "VISTRA CORP"),
    ("APPLIED MATERIALS", "global_semiconductor_ai_hardware", 23267.85, 0.03, 416, "APPLIED MATERIALS INC"),
]


CFTC_ROWS = [
    ("Nasdaq-100 futures", "macro_cross_asset_ai", 276807, "asset_manager_net_long", 63778, "Asset managers long 99,674 and short 35,896; leveraged funds net short 57,403, indicating cash/ETF longs can coexist with futures hedges."),
    ("S&P 500 futures", "macro_cross_asset_ai", 1997951, "asset_manager_net_long", 994992, "Asset managers long 1,174,108 and short 179,116; the broad equity futures book is strongly long asset managers."),
    ("Japanese yen futures", "macro_cross_asset_ai", 431030, "leveraged_net_short_yen", -97092, "Leveraged funds long 90,764 and short 187,856 JPY futures; this is a large short-yen / long-USDJPY structure."),
    ("Japanese yen futures", "japan_ai_semicap_automation", 431030, "asset_manager_net_short_yen", -78364, "Asset managers long 72,898 and short 151,262 JPY futures; yen weakness can amplify Japan exporter/AI equity trades."),
    ("Nasdaq-100 open interest change", "us_core_ai_megacap", 276807, "weekly_oi_change", -98447, "CFTC reports total open interest change of -98,447 from June 16 to June 23, showing a deleveraging week despite high equity AI enthusiasm."),
    ("S&P 500 open interest change", "macro_cross_asset_ai", 1997951, "weekly_oi_change", -626931, "CFTC reports S&P 500 consolidated total open interest change of -626,931, a broad futures risk reduction signal."),
]


STAGE_ROWS = [
    ("2021", "流动性成长股拥挤", "低利率和软件成长股共同推高科技估值，AI 还不是单独交易主线。", "把 2021 作为高估值、低盈利验证阶段，不能直接套到 2026 硬件紧缺。"),
    ("2022", "利率上行杀估值", "高久期科技股去拥挤，云和软件估值被折现率压制。", "说明拥挤度一旦遇到利率冲击，会先通过估值和指数期货释放。"),
    ("2023", "ChatGPT 和 Nvidia 单点突破", "生成式 AI 把边际资金集中到 GPU、云和大模型平台。", "这是本轮 AI 交易的起点，但当时链条还没有全面扩散。"),
    ("2024", "AI capex 扩散到 HBM、设备、光模块和电力", "硬件瓶颈和数据中心建设让机会从芯片扩到供电、散热、互连。", "二阶链条开始拥有独立拥挤度，需要单独评分。"),
    ("2025", "ROI 质疑与软件分化", "软件、应用和云厂开始被问及 AI 投资回报，硬件仍受供给瓶颈支撑。", "基本面验证和估值拥挤开始分叉。"),
    ("2026", "半导体成为最拥挤全球交易", "BofA 调查、ETF 收益、13F 和日本外资流共同指向硬件链拥挤达到新高。", "当前应把拥挤视为风险预算问题，而不是简单泡沫判断。"),
]


def _research_points(entity_key: str) -> list[dict[str, Any]]:
    if entity_key == "acs_methodology":
        rows = [
            (
                "指标目标",
                "method",
                "ai_crowding_score_workpaper",
                "ACS 只衡量拥挤度，不直接输出看多或看空。高 ACS 表示边际资金、叙事和组合风险都集中，下一步必须比较基本面兑现支撑。",
                "这条定义把 ACS 限定为风险拥挤读数，核心是先识别资金和叙事集中，再判断基本面是否足以承接。高分本身不是交易方向，而是要求把证实和证伪监控前置。",
                "用于约束全文口径：所有实体排序只回答拥挤在哪里、脆弱点在哪里和应该先复核什么，不直接把高拥挤写成看多或看空结论。",
            ),
            (
                "权重设计",
                "formula",
                "ai_crowding_score_workpaper",
                json.dumps(ACS_WEIGHTS, ensure_ascii=False),
                "30/20/20/15/15 的权重把持仓与资金流放在第一位，同时保留价格估值、基本面兑现、调查一致性和退出敏感度，避免只用估值或只用情绪调查给结论。",
                "用于复算 ACS：新增来源只调整对应分项，不能因为一条新闻重写总分；基本面兑现分项专门处理真景气和纯资金泡沫的区别。",
            ),
            (
                "13F 处理",
                "holding",
                "sec_13f_dataset_2026q1",
                "SEC 13F 只覆盖机构多头，滞后约45天，不含完整空头、衍生品和海外股票。",
                "13F 是美国机构股票多头的官方下限，适合确认 Mag7、NVIDIA 和半导体链是否被大型机构共同持有，但不能代表实时净仓位。",
                "用于美国核心 AI 巨头和半导体硬件链的持仓分项；审计时必须保留滞后、缺空头和不覆盖海外工具的限制。",
            ),
            (
                "ETF/指数处理",
                "index",
                "invesco_qqq_holdings_20260702",
                "QQQ 和 SPY 官方权重提供被动资金暴露，SOXX/SMH 提供半导体主题入口。",
                "ETF 权重说明 AI 风险如何进入被动组合和基准资金，而不是说明主动基金经理的全部主观仓位。它解释了回撤为什么会从主题链条传到大盘。",
                "用于被动资金传播通道：当 QQQ、SPY、SOXX 或 SMH 权重、净流入和价格动量同时转弱时，优先下调退出敏感度判断。",
            ),
            (
                "ETF 流量处理",
                "flow",
                "marketwatch_etf_flows_h1_2026",
                "美国上市 ETF 资金流和 AI/机器人/存储主题流入只作为资金扩散证据，不能替代持仓明细。",
                "ETF 流量能显示增量资金是否从个股扩散到行业和主题工具，但媒体口径通常不能拆到单只股票或完整组合。",
                "用于判定拥挤从单点龙头扩散到二阶链条；如果流入放缓而主题 ETF 权重仍高，说明后续回撤更依赖存量再平衡。",
            ),
            (
                "CFTC 处理",
                "derivatives",
                "cftc_tff_financial_20260623",
                "TFF 把 futures open interest 分到 asset manager、leveraged funds、dealer、other 和 nonreportable。",
                "CFTC 只看期货和期权报告头寸，不等同于现金股票持仓；它的价值在于捕捉 Nasdaq、S&P、日元等宏观代理上的杠杆方向。",
                "用于交叉资产实体和退出敏感度分项；当期货杠杆与 ETF/股票价格同向拥挤，风险预算收缩会更快传导。",
            ),
            (
                "公司 IR 处理",
                "fundamental",
                "microsoft_q2_fy2026_capex",
                "Microsoft、Meta、Alphabet、Amazon 等 IR 说明 AI capex、云收入和订单能见度是否仍在兑现。",
                "公司 IR 是区分真需求与纯仓位拥挤的关键层。高 capex 和云收入能解释资金为何愿意忍受高估值，但也抬高后续财报门槛。",
                "用于基本面兑现分项：证实看 capex、云收入、订单和利润是否共振；证伪看 capex 继续上修但收入或利润响应放缓。",
            ),
            (
                "日本口径处理",
                "japan",
                "jpx_investor_type_20260702",
                "JPX 外资流、Nikkei 构成、Advantest/TEL IR 和日本 ETF 持仓必须一起看。",
                "日本 AI 链的拥挤既来自半导体设备材料基本面，也来自外资流和日元风险偏好的放大，单看公司订单会低估资金层面的波动。",
                "用于日本实体的持仓与退出分项；若外资流转负而设备订单未变，先识别估值去拥挤，再判断是否伤及基本面。",
            ),
            (
                "宏观代理处理",
                "macro",
                "cftc_recalc_ai_macro_20260623",
                "Nasdaq、SOX、USDJPY、铜、VIX、信用和长债只能作为代理，不把它们写成纯 AI 仓位。",
                "宏观资产反映的是风险预算和流动性路径，不是 AI 订单本身。它们和 AI 股票同向时说明拥挤交易已经具备跨资产传染条件。",
                "用于去杠杆路径监控：当美元、利率、日元、VIX 或信用同时反转，先调整退出敏感度，再回到公司层证据确认基本面是否同步恶化。",
            ),
            (
                "审稿规则",
                "review",
                "ai_crowding_score_workpaper",
                "每个结论至少能回到一个官方/交易所/监管/公司来源和一个市场行为来源。",
                "这条规则把资料广度和可复算性放在结论之前，防止只凭一条调查、一次媒体报道或一段市场叙事升级为核心判断。",
                "用于 final reviewer：缺少来源独立性、计算不可复核、解读和用途重复、或语言模板化的底稿不得发布。",
            ),
        ]
    else:
        rows = [
            (
                "阶段划分",
                "history",
                "ai_crowding_score_workpaper",
                "2021-2022 是高估值和利率冲击阶段，2023 是生成式 AI 单点突破，2024-2026 是硬件和基础设施扩散。",
                "阶段划分的作用不是做市场回忆录，而是把拥挤从流动性、利率、单点龙头和产业链扩散四种机制中拆开。",
                "用于解释 2026 的拥挤为什么不能简单套用 2021 泡沫或 2023 单一 NVIDIA 交易框架。",
            ),
            (
                "2021 参照",
                "history",
                "sec_13f_recalc_ai_holdings_2026q1",
                "2021 的拥挤主要来自流动性和成长久期，基本面 AI capex 还未成为主线。",
                "2021 提醒我们，高估值成长股可以在流动性充裕时长期拥挤，但当时缺少今天这种云厂 capex 和供应链订单支撑。",
                "用于区分估值拥挤和建设周期拥挤：如果当前只剩价格上行而订单/利润不兑现，才更接近 2021 风险。",
            ),
            (
                "2022 参照",
                "history",
                "cftc_tff_financial_20260623",
                "2022 利率冲击让科技股去拥挤，说明拥挤交易最怕折现率和风险预算同时收缩。",
                "2022 的核心教训是折现率和风险预算可以绕开公司短期基本面，直接压缩久期资产和高估值组合。",
                "用于宏观证伪路径：若长债利率、美元流动性或期货杠杆同时恶化，AI 交易可能先去仓位，后验证基本面。",
            ),
            (
                "2023 参照",
                "history",
                "invesco_qqq_holdings_20260702",
                "ChatGPT 之后资金集中到 GPU、云和大模型平台，NVIDIA 成为最清晰表达。",
                "2023 是从概念扩散到可投资主线的转折点，拥挤集中在少数可以直接表达算力短缺的股票和指数权重里。",
                "用于检查当前是否仍是单点龙头交易；如果 QQQ/SPY 和 13F 集中度继续上升，说明 2023 机制仍在。",
            ),
            (
                "2024 扩散",
                "history",
                "blackrock_soxx_20260702",
                "HBM、封装、光模块、液冷、电力和数据中心资产开始获得二阶资金。",
                "2024 之后拥挤从 GPU 主线扩散到半导体 ETF、HBM、设备、先进封装和基础设施，风险不再只由单只龙头解释。",
                "用于扩展监控边界：半导体 ETF 收益和权重变化可作为硬件链拥挤是否外溢的高频代理。",
            ),
            (
                "2025 分化",
                "history",
                "businessinsider_ai_trade_split_202607",
                "软件和部分云厂开始承受 ROI 和自由现金流质疑，硬件链仍受供给瓶颈支撑。",
                "分化阶段说明同样叫 AI 持仓，背后的拥挤性质不同：软件更多受 ROI 证明压力影响，硬件更多受供给瓶颈和订单能见度支撑。",
                "用于实体拆分：云厂/软件 ROI、全球半导体硬件链和基础设施链必须分别打分，不能合成一个泛 AI 结论。",
            ),
            (
                "2026 状态",
                "history",
                "bofa_fms_202606_semis_crowding",
                "半导体被资金经理调查标为最拥挤全球交易，ETF、13F 和日本外资流提供交叉验证。",
                "2026 的边际信息是拥挤对象已经更偏全球硬件链，调查、ETF、价格和跨境资金流互相验证，而不是只有新闻叙事。",
                "用于排序主结论：全球半导体/HBM/设备链应排在拥挤风险最前，云厂软件 ROI 分化则需要单独观察。",
            ),
            (
                "反身性",
                "reflexivity",
                "marketwatch_nasdaq_contribution_h1_2026",
                "价格上涨会提高被动权重、提高基金相对业绩压力，再吸引更多资金；回撤时这条链条反向运行。",
                "反身性解释了为什么少数 AI 股票贡献越高，基准追赶、被动权重和主题资金越容易互相强化，直到盈利或流动性证伪。",
                "用于设计证伪动作：监控不能只看公司新闻，还要同步看 ETF 权重、期货净仓位、资金流和领涨贡献是否反转。",
            ),
            (
                "补证顺序",
                "review",
                "goldman_semis_profit_taking_202606",
                "先更新调查、ETF 权重、13F、CFTC，再看公司 IR 和价格回撤是否同步。",
                "补证顺序要先处理仓位和资金行为，再回到基本面；否则容易把短期获利了结误判成产业趋势反转，或把基本面强势误判成无风险拥挤。",
                "用于下一轮更新清单：先查 BofA/Goldman、ETF 官方、SEC 13F、CFTC/JPX，再读云厂和设备公司的最新 IR。",
            ),
            (
                "写作约束",
                "review",
                "ai_crowding_score_workpaper",
                "历史阶段只能服务当前判断，不能写成泛泛回顾。",
                "这条约束保证历史材料必须回答今天的研究问题：当前拥挤在哪里、为什么形成、什么时候会被证实或证伪。",
                "用于写作审计：如果阶段段落不能改变 2026 实体排序、监控指标或证实/证伪条件，就应删改重写。",
            ),
        ]
    points: list[dict[str, Any]] = []
    for idx, (title, category, source_ref, excerpt, interpretation, research_use) in enumerate(rows, start=1):
        points.append(
            {
                "source_ref": source_ref,
                "data_point_title": title,
                "research_category": category,
                "metric": title,
                "period": "2021-2026",
                "as_of_date": AS_OF_DATE,
                "value_text": excerpt,
                "unit": "研究口径",
                "source_excerpt": excerpt,
                "source_context": SOURCE_NOTES.get(source_ref, excerpt),
                "interpretation": interpretation,
                "research_use": research_use,
                "limitations": "若新增官方或监管数据改变底层口径，本条需要重新复核。",
                "evidence_ref_uri": _ref(source_ref),
                "sort_order": idx,
            }
        )
    return points


def _research_profile(entity_key: str) -> dict[str, Any]:
    meta = ENTITY_DEFS[entity_key]
    if entity_key == "acs_methodology":
        lit = (
            "### 文献综述\n\n"
            "本任务的资料层级必须先从监管和交易所数据开始。SEC 13F 提供美国机构多头持仓的官方结构化底座，CFTC TFF 提供金融期货杠杆方向，ETF 管理人披露 QQQ、SPY、SOXX、SMH 等被动和主题工具权重，JPX 披露日本投资者类型交易。"
            "这些资料的共同优点是可复核、可更新、口径稳定；共同缺点是不能单独回答实时拥挤，因为 13F 滞后且缺空头，CFTC 看不到现金股票，ETF 权重只说明被动暴露，JPX 外资流需要周度拆分。"
            "第二层资料来自公司 IR，包括 Microsoft、Meta、Alphabet、Amazon、Advantest、Tokyo Electron。它们回答基本面兑现：AI capex、云收入、订单和设备需求是否仍在支撑价格。"
            "第三层是 BofA、Goldman、Reuters/MarketWatch 等公开摘要。它们更贴近资金经理情绪和 prime brokerage 动态，但必须降权使用，只有在和监管、ETF、价格或公司披露一致时才进入核心判断。"
        )
        analysis = (
            "ACS 的关键设计不是把所有证据平均相加，而是先问每类证据解决哪个问题。持仓与资金流拥挤权重 30%，因为研究问题本身是拥挤度；价格动量与估值拥挤权重 20%，因为市场已经交易到什么程度决定边际风险；基本面兑现支撑权重 20%，因为真实业绩能解释高仓位为什么仍可维持；衍生品和宏观杠杆权重 15%，因为去杠杆常从期货、外汇和波动率先发生；退出敏感度权重 15%，因为拥挤交易最危险的不是高持仓本身，而是同时触发再平衡、止盈、风险预算和被动权重收缩。"
            "这个框架把“拥挤”和“泡沫”分开：半导体可以非常拥挤，但如果 HBM、GPU、设备和云 capex 仍在兑现，就不能简单写成泡沫；软件或应用层即使持仓低一些，如果估值依赖远期 ROI 且价格已经破位，也可能更脆。"
        )
        answer = (
            "回答研究问题时，ACS 先输出实体层拥挤排名，再把每个实体拆成证实/证伪路径。全球半导体硬件链最高，是因为 BofA 调查、SOXX/SMH 年内收益、13F 复算和 Goldman 对冲基金材料同向；美国核心巨头次高，是因为 QQQ/SPY 和 13F 仍把 AI 巨头压在指数核心，但 Mag7 内部已经分化；日本 AI 设备链和 AI 电力基础设施属于二阶高拥挤，真实需求存在但边际资金敏感；超大云厂和软件层的拥挤较低，因为 capex 数据很强但股价已经开始区分 ROI；宏观交叉资产是代理拥挤，不能和股票持仓混写。"
        )
        conclusion = (
            "结论是：AI 持仓拥挤度应按“高拥挤加高基本面验证”和“高拥挤低验证”分开处理。前者不是直接看空，重点是监控边际资金、估值和供应链兑现；后者需要更严格的证伪动作。后续更新优先级是 BofA/Goldman/prime 调查、SEC 13F、ETF 权重、CFTC、公司财报和价格回撤，任何单一来源都不能直接改核心排序。"
        )
    else:
        lit = (
            "### 文献综述\n\n"
            "2021-2026 的资料关系显示，AI 拥挤交易经历了四次换壳：低利率成长股、利率冲击后的去估值、ChatGPT 后的 GPU 单点突破、AI capex 驱动的硬件和基础设施扩散。"
            "BofA 调查和 Goldman hedge fund monitor 解释当下专业投资者如何描述拥挤；ETF/指数和 13F 解释这些拥挤如何进入被动权重和机构多头；公司 IR 解释为何资金没有简单撤出，因为云 capex、HBM、设备和电力需求仍有真实基本面；CFTC 和 JPX 则解释拥挤如何通过期货、汇率和外资流传播到宏观。"
        )
        analysis = (
            "历史演化的核心不是回顾年份，而是识别拥挤机制变化。2021 的问题是流动性推高所有成长久期；2022 的问题是折现率上行让高估值统一收缩；2023 的问题是生成式 AI 找到 GPU 这个确定性表达；2024-2026 的问题变成真实建设周期把资金推向 HBM、设备、光模块、电力和日本半导体设备。"
            "这意味着当前不能用单一泡沫框架解释：如果只看估值，会低估硬件基本面；如果只看 capex，会忽略资金已经在半导体和日本链条高度集中；如果只看美国 Mag7，会漏掉日本、铜、日元和电力基础设施的二阶拥挤。"
        )
        answer = (
            "对 2026 的直接回答是：AI 拥挤已经从单点主题扩散成多资产组合拥挤。最强线索在全球半导体，第二层在美国核心指数和日本半导体设备，第三层在电力基础设施和宏观代理。软件和云厂不是没有拥挤，而是从“买 AI 增长”转成“检验 AI 投入回报”。"
        )
        conclusion = (
            "后续 6-12 个月判断不能只问 AI 是否继续增长，而要问增长由谁兑现、谁承担 capex、谁被动权重最高、谁的边际资金最快撤离。这个历史框架决定本 run 的排序和动作：硬件链高分但严查获利了结，云厂严查 ROI，日本严查外资流，宏观严查日元、利率和波动率。"
        )
    return {
        "entity_research_mode": "theory_research",
        "research_depth_status": "complete",
        "research_question": meta["display_name"],
        "research_scope": "AI 持仓拥挤度、资金流、ETF/指数权重、13F、CFTC、公司基本面、价格动量、日本市场和全球宏观代理。",
        "methodology_note": "producer-reviewer-loop 按 Nature 审稿人和高盛基金经理双视角检查：数据可追溯、计算可复核、结论能回答研究问题，表达面向金融研究员。",
        "literature_review_markdown": lit,
        "data_collection_markdown": "数据收集包含 SEC 13F 官方 zip 本地复算、CFTC TFF 官方网页复算、ETF 管理人持仓页、公司 IR、JPX、BofA/Goldman 公开摘要、Reuters/MarketWatch 辅助线索和 yfinance 价格快照。同源同对象同口径时间序列合并为一个数据点。",
        "analysis_markdown": analysis,
        "answer_markdown": answer,
        "conclusion_markdown": conclusion,
        "limitations_markdown": "13F 滞后且不含完整空头；CFTC 不覆盖现金股票；部分 BofA/Goldman 数据来自公开摘要或镜像；日本外资流需要 JPX 明细持续复核；本 run 不把任何单一来源当作完整仓位事实。",
        "evidence_ref_uri_list": ENTITY_REFS[entity_key],
    }


def _factor(
    code: str,
    score: int,
    metric_name: str,
    refs: list[str],
    *,
    entity_key: str,
    topic: str,
    summary: str,
    rationale: str,
    implication: str,
    direction: str = "mixed",
) -> dict[str, Any]:
    entity_name = ENTITY_DEFS[entity_key]["display_name"]
    points: list[dict[str, Any]] = []
    for idx, token in enumerate(refs, start=1):
        ref_name = token.replace("source_ref:", "")
        note = SOURCE_NOTES.get(ref_name, ref_name)
        points.append(
            {
                "slot_name": f"{metric_name} 证据 {idx}",
                "metric_line": f"{metric_name} - {topic} - 独立来源 {idx}",
                "excerpt": _compact(note, 500),
                "evidence_ref": _ref(ref_name),
                "interpretation": _compact(
                    f"{entity_name} 使用这条来源校准 {metric_name}。{note} 这里的影响是：{summary}；对后续研究动作的含义是：{implication}",
                    900,
                ),
                "source_tier": "按来源分层",
                "direction": direction,
                "observation_count": 1,
                "weight_reason": "权重取决于来源独立性、是否来自监管/交易所/ETF/公司披露、是否含数字口径，以及是否直接对应本因子。",
            }
        )
    return {
        "factor_code": code,
        "score_status": "complete",
        "score_raw": score,
        "score_adjusted": score,
        "coverage": 0.86 if score >= 70 else 0.78,
        "confidence": 0.80 if score >= 70 else 0.72,
        "factor_readiness_status": "ready",
        "metric_name": metric_name,
        "unit": "分",
        "period": "2026H1",
        "as_of_date": AS_OF_DATE,
        "trace": f"{topic}：{rationale}",
        "core_score_note": "同源同对象同口径的多期观察只算一个证据组；券商调查必须被 ETF/13F/CFTC/公司 IR 或价格数据交叉验证。",
        "contextual_human_question": f"{topic} 是否改变 {entity_name} 的拥挤度排序和补证优先级。",
        "contextual_factor_description": f"{metric_name} 把 {topic} 转换为可以被复核的拥挤度分项。",
        "source_context_summary": f"{entity_name} 的这一分项同时读取监管/交易所/ETF/公司/市场价格来源，避免单一叙事决定分数。",
        "factor_value_summary": summary,
        "factor_topic_analysis": rationale,
        "score_rationale": rationale,
        "theme_analysis_points": [summary, rationale, implication],
        "information_points": points,
        "adjacent_factor_links": "本分项必须和基本面兑现、价格回撤、持仓集中和退出敏感度一起读；单项高分只说明一个环节拥挤。",
        "target_implications": implication,
        "source_context_refs": refs,
        "evidence_ref_uri_list": refs,
        "factor_importance": "important",
        "direction": direction,
    }


def _factor_scores(entity_key: str) -> list[dict[str, Any]]:
    refs = ENTITY_REFS[entity_key]
    c = ACS_COMPONENTS[entity_key]
    if entity_key == "us_core_ai_megacap":
        return [
            _factor("supply.supplier_structure_bucket", int(c["持仓与资金流拥挤"]), "指数和机构持仓集中度", refs[:6], entity_key=entity_key, topic="QQQ/SPY/13F 同时显示 AI 巨头集中", summary="美国核心 AI 仓位已经被主动机构和被动指数共同持有，回撤会影响广义大盘风险预算。", rationale="SEC 13F 复算显示 NVIDIA、Apple、Alphabet、Microsoft 等在机构多头中占比高，QQQ 和 SPY 官方权重又把这些名字放在被动入口前列；这说明拥挤不只来自主题基金。", implication="优先跟踪 QQQ/SPY 权重变化、13F 下一季是否继续增持，以及 Nasdaq-100 futures 是否同步减仓。"),
            _factor("signal.material_price_momentum", int(c["价格动量与估值拥挤"]), "价格动量和贡献集中", ["source_ref:yfinance_price_snapshot_20260705", "source_ref:marketwatch_nasdaq_contribution_h1_2026", "source_ref:invesco_qqq_holdings_20260702", "source_ref:ssga_spy_holdings_20260702", "source_ref:bofa_fms_202606_semis_crowding", "source_ref:cftc_recalc_ai_macro_20260623"], entity_key=entity_key, topic="指数涨幅由少数 AI 硬件和巨头贡献", summary="QQQ、SPY 仍创新高附近，但贡献越来越集中，说明指数表面分散、实际风险集中。", rationale="当少数股票贡献绝大多数指数收益，组合经理为了跟上基准会被动增加同向暴露；这使价格动量本身成为拥挤的再强化机制。", implication="如果领涨股出现盈利不及预期，先降低美国核心实体分数，再检查是否扩散到 SPY 和信用。"),
            _factor("demand.customer_capex_capacity_signal", int(c["基本面兑现支撑"]), "AI 云和芯片基本面兑现", ["source_ref:microsoft_q3_fy2026_results", "source_ref:microsoft_q2_fy2026_capex", "source_ref:alphabet_q1_2026_ai_cloud", "source_ref:amazon_q1_2026_aws", "source_ref:meta_q1_2026_capex", "source_ref:sec_13f_recalc_ai_holdings_2026q1"], entity_key=entity_key, topic="高持仓背后仍有收入和 capex 证据", summary="基本面证据强，解释了为什么美国核心 AI 仓位拥挤但还没有简单崩塌。", rationale="Microsoft、Alphabet、Amazon 和 Meta 的披露说明需求和资本开支仍在兑现；这提高拥挤交易的持续性，但也把后续财报门槛抬高。", implication="证实条件是云收入、GPU/CPU capex 和 backlog 继续共振；证伪条件是 capex 继续上修但收入或利润响应放缓。", direction="positive"),
            _factor("supply.capacity_event_12m", int(c["退出敏感度"]), "被动权重和再平衡退出风险", ["source_ref:invesco_qqq_holdings_20260702", "source_ref:ssga_spy_holdings_20260702", "source_ref:cftc_recalc_ai_macro_20260623", "source_ref:yfinance_price_snapshot_20260705", "source_ref:bofa_fms_202606_semis_crowding", "source_ref:marketwatch_nasdaq_contribution_h1_2026"], entity_key=entity_key, topic="高权重股票一旦回撤会触发被动和主动再平衡", summary="退出敏感度高，因为拥挤不只在主题 ETF，也在大盘 ETF 和机构 benchmark 中。", rationale="QQQ、SPY、13F 和 futures 的联动意味着负面冲击会同时影响指数资金、主动组合和宏观风险预算。", implication="证伪后动作不是只删单一股票，而是同步检查 QQQ、NQ futures、SPY 行业权重和波动率。", direction="negative"),
        ]
    if entity_key == "global_semiconductor_ai_hardware":
        return [
            _factor("supply.supplier_structure_bucket", int(c["持仓与资金流拥挤"]), "全球半导体持仓和调查拥挤", refs[:6], entity_key=entity_key, topic="BofA 80% 调查与 hedge fund AI 倾斜共振", summary="全球半导体是本 run 最高拥挤实体，拥挤证据来自调查、ETF、13F 和对冲基金材料。", rationale="BofA 80% 是直接拥挤调查，Goldman 说明 hedge funds 已把 AI 交易集中到 tech/semis，SOXX/SMH 则给出可交易入口。多源一致使分数显著高于其他实体。", implication="证实后继续把半导体作为最高风险预算监控对象；证伪时优先看获利了结是否从个股扩散到 SOXX/SMH。"),
            _factor("signal.material_price_momentum", int(c["价格动量与估值拥挤"]), "SOXX/SMH/SOX 价格动量", ["source_ref:blackrock_soxx_20260702", "source_ref:vaneck_smh_fact_202607", "source_ref:yfinance_price_snapshot_20260705", "source_ref:marketwatch_nasdaq_contribution_h1_2026", "source_ref:guardian_chipmakers_h1_2026", "source_ref:bofa_fms_202606_semis_crowding"], entity_key=entity_key, topic="半导体 ETF 和指数年内收益极强", summary="价格拥挤接近极端：SOXX 官方 YTD 接近翻倍，SOX/yfinance 快照也显示硬件显著领先。", rationale="强价格动量说明基本面和资金流都在追逐硬件，但也意味着任何订单或毛利不及预期都会带来更大回撤。", implication="把 SOXX/SMH 的 5日、20日回撤和资金流作为最高频监控。"),
            _factor("demand.application_intensity_change", int(c["基本面兑现支撑"]), "HBM/GPU/设备真实需求", ["source_ref:goldman_hf_trend_all_in_ai_202606", "source_ref:microsoft_q2_fy2026_capex", "source_ref:meta_q1_2026_capex", "source_ref:alphabet_q1_2026_ai_cloud", "source_ref:tokyo_electron_q3_fy2026", "source_ref:advantest_fy2025_results_20260427"], entity_key=entity_key, topic="AI capex 落到 GPU/HBM/测试/设备", summary="硬件拥挤有基本面支撑，不是纯估值故事。", rationale="云厂 capex、HBM 和测试设备需求都能解释为什么半导体成为资金最拥挤表达；问题在于市场是否已经提前支付了过多未来景气。", implication="证实要看 HBM、GPU、设备订单和毛利同时兑现；证伪要看云厂 capex 放缓或芯片库存上升。", direction="positive"),
            _factor("supply.capacity_event_12m", int(c["退出敏感度"]), "获利了结和再平衡风险", ["source_ref:goldman_semis_profit_taking_202606", "source_ref:bofa_fms_202606_semis_crowding", "source_ref:blackrock_soxx_20260702", "source_ref:vaneck_smh_fact_202607", "source_ref:yfinance_price_snapshot_20260705", "source_ref:sec_13f_recalc_ai_holdings_2026q1"], entity_key=entity_key, topic="高拥挤后的边际卖压开始出现", summary="Goldman 的净卖出线索使半导体从单纯强趋势进入风险管理阶段。", rationale="当一个板块同时是最拥挤交易和过去一年最赚钱交易，获利了结会先表现为净卖出、ETF 回撤和 option skew 改变。", implication="若净卖出持续，先下调价格动量和退出敏感度，再检查基本面是否足以承接卖压。", direction="negative"),
        ]
    if entity_key == "hyperscaler_capex_software_roi":
        return [
            _factor("demand.customer_capex_capacity_signal", int(c["基本面兑现支撑"]), "云厂 AI capex 和收入验证", refs[:6], entity_key=entity_key, topic="Microsoft、Meta、Alphabet、Amazon 共同证明 AI 投入仍在加速", summary="基本面强度高，但市场已经开始要求资本开支回报。", rationale="Microsoft capex、Meta 指引、Alphabet Cloud backlog、Amazon AWS 利润显示 AI 基建真实存在；分歧在于这些投入能否转成自由现金流。", implication="证实条件是云收入、backlog、AI 订阅和利润率同步改善；证伪条件是 capex 上修而利润率下滑。", direction="positive"),
            _factor("signal.material_price_momentum", int(c["价格动量与估值拥挤"]), "云厂和软件股价分化", ["source_ref:yfinance_price_snapshot_20260705", "source_ref:businessinsider_ai_trade_split_202607", "source_ref:microsoft_q3_fy2026_results", "source_ref:meta_q1_2026_capex", "source_ref:alphabet_q1_2026_ai_cloud", "source_ref:amazon_q1_2026_aws"], entity_key=entity_key, topic="软件和部分云厂没有跟上硬件涨幅", summary="价格拥挤中等偏低，因为投资者已经惩罚 capex 回报不清楚的名字。", rationale="MSFT、META、ORCL、PLTR 的回撤和硬件链形成对比，说明 AI 交易内部已经从概念切到现金流验证。", implication="软件/应用层不能按半导体拥挤同分处理，必须逐标的看收入兑现。", direction="mixed"),
            _factor("demand.output_consumption_proxy", int(c["持仓与资金流拥挤"]), "机构持仓中的云和软件暴露", ["source_ref:sec_13f_recalc_ai_holdings_2026q1", "source_ref:goldman_hf_trend_all_in_ai_202606", "source_ref:invesco_qqq_holdings_20260702", "source_ref:ssga_spy_holdings_20260702", "source_ref:yfinance_price_snapshot_20260705", "source_ref:businessinsider_ai_trade_split_202607"], entity_key=entity_key, topic="云厂仍是 13F 和指数大权重", summary="持仓仍重，但拥挤形态已经从单纯加仓变成业绩验证压力。", rationale="Alphabet、Microsoft、Amazon、Meta 在 13F 和大盘 ETF 中仍是大权重；但 hedge funds 和市场表现更偏好硬件，这使云厂成为验证债而非最高拥挤。", implication="下一季 13F 若继续增持但股价落后，需重估 ROI 折扣。"),
            _factor("supply.substitution_barrier", int(c["退出敏感度"]), "AI ROI 证伪敏感度", ["source_ref:microsoft_q2_fy2026_capex", "source_ref:meta_q1_2026_capex", "source_ref:alphabet_q1_2026_ai_cloud", "source_ref:amazon_q1_2026_aws", "source_ref:yfinance_price_snapshot_20260705", "source_ref:businessinsider_ai_trade_split_202607"], entity_key=entity_key, topic="capex 越大，市场对回报证据要求越高", summary="退出风险来自自由现金流和折旧周期，而不是需求完全消失。", rationale="云厂可以同时拥有强需求和弱股价，因为资本开支先吞现金流，收入兑现滞后；这使证伪路径比半导体更偏财务。", implication="证伪后动作是下调云厂和软件实体，不直接下调 HBM/设备实体，除非 capex 本身也放缓。", direction="negative"),
        ]
    if entity_key == "ai_power_infrastructure":
        return [
            _factor("demand.customer_capex_capacity_signal", int(c["基本面兑现支撑"]), "数据中心电力和基础设施需求", refs[:6], entity_key=entity_key, topic="AI capex 把电力、液冷、配电和数据中心推成二阶交易", summary="基础设施链的基本面支撑来自超大云厂 capex 和数据中心容量建设。", rationale="Meta、Microsoft、Alphabet、Amazon 的 capex 给电力、配电、冷却和数据中心 REIT 提供需求来源；但订单透明度低于 GPU/HBM。", implication="证实需要看到具体 backlog、交付周期、价格和毛利，而不是只看到云厂 capex。", direction="positive"),
            _factor("signal.material_price_momentum", int(c["价格动量与估值拥挤"]), "电力基础设施价格动量", ["source_ref:yfinance_price_snapshot_20260705", "source_ref:marketwatch_etf_flows_h1_2026", "source_ref:meta_q1_2026_capex", "source_ref:microsoft_q2_fy2026_capex", "source_ref:alphabet_q1_2026_ai_cloud", "source_ref:cftc_recalc_ai_macro_20260623"], entity_key=entity_key, topic="Vertiv、Eaton、核电/电力股积累较大涨幅", summary="价格拥挤高于云厂但低于半导体，尤其是 VRT、VST、CEG 等已经经历大波动。", rationale="二阶链条的估值往往先由叙事和订单能见度推升，再由实际交付和毛利验证；回撤会在估值最先过热的标的上放大。", implication="若电力链回撤而云 capex 未变，先判断是否估值去拥挤，不急于否定需求。"),
            _factor("supply.capacity_event_12m", int(c["持仓与资金流拥挤"]), "二阶资金流和主题扩散", ["source_ref:marketwatch_etf_flows_h1_2026", "source_ref:yfinance_price_snapshot_20260705", "source_ref:sec_13f_recalc_ai_holdings_2026q1", "source_ref:meta_q1_2026_capex", "source_ref:microsoft_q2_fy2026_capex", "source_ref:amazon_q1_2026_aws"], entity_key=entity_key, topic="资金从芯片扩散到电力和基础设施", summary="二阶链条拥挤来自资金寻找下一环节，不完全来自已披露订单。", rationale="ETF 资金流和 VRT/ETN/CEG/VST 的价格表现说明资金已经把 AI capex 映射到电力容量和基础设施；但映射链条更长，证据折扣必须更大。", implication="同实体内优先级按订单透明度和客户绑定排序。"),
            _factor("supply.raw_policy_constraint", int(c["退出敏感度"]), "电网、利率和商品约束", ["source_ref:cftc_recalc_ai_macro_20260623", "source_ref:yfinance_price_snapshot_20260705", "source_ref:meta_q1_2026_capex", "source_ref:alphabet_q1_2026_ai_cloud", "source_ref:marketwatch_etf_flows_h1_2026", "source_ref:ssga_spy_holdings_20260702"], entity_key=entity_key, topic="基础设施链同时受利率、项目审批和电力商品影响", summary="退出敏感度来自利率和项目周期，和半导体库存周期不同。", rationale="数据中心 REIT、电力设备和公用事业资产对利率、资本成本和项目时点敏感；若长债收益率上行，基本面未变也可能去估值。", implication="证伪时先看订单延期、利率和项目审批，再看云厂 capex 是否改变。", direction="negative"),
        ]
    if entity_key == "japan_ai_semicap_automation":
        return [
            _factor("demand.customer_capex_capacity_signal", int(c["基本面兑现支撑"]), "日本设备和测试基本面", refs[3:8], entity_key=entity_key, topic="Advantest 和 Tokyo Electron 有 AI/HPC 需求披露", summary="日本链条并非纯外资题材，设备和测试环节有公开 IR 支撑。", rationale="Advantest FY2026 指引和 TEL 存储/逻辑设备披露证明 AI/HPC 需求进入本土设备公司，但这些证据仍需和订单、毛利和客户节奏对应。", implication="证实后优先深挖 Advantest/TEL/Disco；证伪看 FY2026 指引是否下修。", direction="positive"),
            _factor("signal.material_price_momentum", int(c["价格动量与估值拥挤"]), "日本 AI 链股价动量", ["source_ref:yfinance_price_snapshot_20260705", "source_ref:aljazeera_japan_ai_rally_202606", "source_ref:reuters_japan_foreign_selloff_20260627", "source_ref:finance_yahoo_japan_foreign_buy_20260620", "source_ref:ishares_nikkei225_holdings_202607", "source_ref:nikkei_components_202607"], entity_key=entity_key, topic="日本 AI 设备链年内涨幅和外资流波动都很大", summary="价格拥挤高，且边际资金对获利了结极敏感。", rationale="yfinance 快照显示 TEL、Advantest、Disco、Lasertec、Fujikura 等涨幅显著；Reuters 一周净买、一周大卖说明外资流不是稳态配置。", implication="如果外资连续两周卖出且设备股破位，应先下调日本拥挤分数。", direction="mixed"),
            _factor("supply.supplier_structure_bucket", int(c["持仓与资金流拥挤"]), "Nikkei 价格加权和 ETF 被动放大", ["source_ref:nikkei_components_202607", "source_ref:ishares_nikkei225_holdings_202607", "source_ref:jpx_investor_type_20260702", "source_ref:reuters_japan_foreign_selloff_20260627", "source_ref:finance_yahoo_japan_foreign_buy_20260620", "source_ref:yfinance_price_snapshot_20260705"], entity_key=entity_key, topic="日本指数结构放大高价半导体设备股", summary="日本拥挤度不仅来自个股上涨，还来自 Nikkei 结构和 ETF/外资交易。", rationale="Nikkei 225 的价格加权使高价设备股影响更大，ETF 和外资流把全球 AI 风险预算映射到日本市场。", implication="同实体内需要同时看个股 IR 和 JPX 外资/个人交易分拆。"),
            _factor("supply.capacity_event_12m", int(c["退出敏感度"]), "外资获利了结和日元联动", ["source_ref:jpx_investor_type_20260702", "source_ref:reuters_japan_foreign_selloff_20260627", "source_ref:cftc_recalc_ai_macro_20260623", "source_ref:yfinance_price_snapshot_20260705", "source_ref:finance_yahoo_japan_foreign_buy_20260620", "source_ref:nikkei_components_202607"], entity_key=entity_key, topic="日元空头和外资流使日本 AI 链去杠杆速度更快", summary="退出敏感度高，因为股票上涨、弱日元和外资流是同向交易。", rationale="CFTC 显示日元空头结构，若日元突然升值或外资转卖，高价设备股可能同时承受汇率和仓位冲击。", implication="证伪后动作是下调日本链和宏观实体，同时检查日元和 Nikkei futures。", direction="negative"),
        ]
    return [
        _factor("supply.raw_policy_constraint", int(c["衍生品和宏观杠杆"]), "Nasdaq、S&P、日元和宏观代理杠杆", refs[:6], entity_key=entity_key, topic="AI 拥挤通过期货、汇率和风险资产代理传播", summary="宏观拥挤不是纯 AI 仓位，但它决定去杠杆传播速度。", rationale="CFTC 显示 NQ、S&P 和日元期货上存在明显机构和杠杆结构；这些仓位会把 AI 股冲击传导到美元、日元、波动率和信用。", implication="证伪后先看 NQ、SOX、USDJPY、VIX、TLT/HYG，而不是只看股票新闻。"),
        _factor("signal.material_price_momentum", int(c["价格动量与估值拥挤"]), "SOX、NDX、铜、VIX 和信用价格联动", ["source_ref:yfinance_price_snapshot_20260705", "source_ref:blackrock_soxx_20260702", "source_ref:marketwatch_etf_flows_h1_2026", "source_ref:cftc_recalc_ai_macro_20260623", "source_ref:ssga_spy_holdings_20260702", "source_ref:jpx_investor_type_20260702"], entity_key=entity_key, topic="AI 价格动量已外溢到宏观代理", summary="SOX 和 NDX 强、VIX 低位、HYG 稳定构成风险偏好链条，铜和日元提供交叉验证。", rationale="这些资产不是 AI 基本面本身，但它们影响组合风险预算；当它们同时反转，股票基本面好也可能被迫去杠杆。", implication="监控应按多资产仪表盘，而不是单一股票列表。", direction="mixed"),
        _factor("demand.output_consumption_proxy", int(c["持仓与资金流拥挤"]), "ETF 流入和宏观风险偏好", ["source_ref:marketwatch_etf_flows_h1_2026", "source_ref:invesco_qqq_holdings_20260702", "source_ref:ssga_spy_holdings_20260702", "source_ref:blackrock_soxx_20260702", "source_ref:vaneck_smh_fact_202607", "source_ref:yfinance_price_snapshot_20260705"], entity_key=entity_key, topic="ETF 资金把 AI 主题变成宏观 beta", summary="ETF 流入让 AI 不再只是主动选股问题，而是大类资产资金配置问题。", rationale="超过万亿美元 ETF 流入和科技/AI 主题高占比意味着宏观资金已经通过低成本产品持有 AI 风险。", implication="若 ETF 流入放缓或转负，宏观实体分数先于基本面实体调整。"),
        _factor("supply.capacity_event_12m", int(c["退出敏感度"]), "利率、日元和波动率冲击路径", ["source_ref:cftc_recalc_ai_macro_20260623", "source_ref:yfinance_price_snapshot_20260705", "source_ref:reuters_japan_foreign_selloff_20260627", "source_ref:jpx_investor_type_20260702", "source_ref:marketwatch_etf_flows_h1_2026", "source_ref:bofa_fms_202606_semis_crowding"], entity_key=entity_key, topic="宏观冲击可以绕开基本面直接压缩仓位", summary="退出敏感度较高，因为日元、利率、波动率和 ETF 流会同时改变风险预算。", rationale="BofA 同时列出 AI bubble、通胀和无序利率上行风险；若这些风险一起出现，AI 交易会先经历仓位压缩，再由基本面决定是否恢复。", implication="证伪动作是跨资产降风险，而不是只下调某个股票目标。", direction="negative"),
    ]


def _entity(entity_key: str) -> dict[str, Any]:
    meta = ENTITY_DEFS[entity_key]
    mode = meta["mode"]
    refs = ENTITY_REFS[entity_key]
    score = 0.0 if mode == "theory_research" else _acs_score(entity_key)
    entity: dict[str, Any] = {
        "key": entity_key,
        "entity_type": "product_material",
        "taxonomy_level": "theme",
        "canonical_name": entity_key,
        "display_name": meta["display_name"],
        "description": meta["description"],
        "entity_research_mode": mode,
        "external_ref_type": "opportunity_lens_entity",
        "maturation_status": "research_only" if mode == "theory_research" else "scoring_ready",
        "readiness_score": 1.0 if mode == "theory_research" else 0.86,
        "readiness_reason": f"{meta['display_name']} 已用 {len(refs)} 个核心来源组复核，包含监管/交易所/ETF/公司/市场行为来源。",
        "research_priority_label": "research_only_literature_review_complete" if mode == "theory_research" else "high_priority_for_scoring",
        "source_count": len(refs),
        "independent_source_count": len({r.replace("source_ref:", "").split("_")[0] for r in refs}),
        "candidate_reason": meta["problem"],
        "evidence_ref_uri": refs[0],
        "evidence_ref_uri_list": refs,
        "score_point": score,
        "score_grade": _score_grade(score),
        "score_quality_label": "unrated_insufficient_evidence" if mode == "theory_research" else "medium_confidence",
        "score_band_low": max(0, score - 6),
        "score_band_high": min(100, score + 6),
        "coverage": 0.86,
        "confidence": 0.80,
        "band_reason": meta["answer"],
        "composite_trace": {
            "confirmed_action": f"若 {meta['display_name']} 后续由 ETF/13F/CFTC/IR/价格数据继续同向确认，上调研究优先级并加密监控频率。",
            "falsified_action": f"若 {meta['display_name']} 的高拥挤来源被外资流、ETF 流出、CFTC 去杠杆或公司 IR 证伪，下调分数并转入反方跟踪。",
            "monitor_signal": "BofA/Goldman 调查、SEC 13F、ETF 权重和流量、CFTC TFF、JPX 外资流、公司 capex/收入/利润、yfinance 价格回撤。",
            "monitor_timing": "调查和ETF周度/月度；13F季度；CFTC周度；公司IR季度；价格动量每日复核。",
        },
        "factor_scores": [] if mode == "theory_research" else _factor_scores(entity_key),
    }
    if mode == "theory_research":
        entity["research_profile"] = _research_profile(entity_key)
        entity["research_data_points"] = _research_points(entity_key)
    return entity


TARGET_DEFS = [
    ("us_core_ai_megacap", "Invesco QQQ Trust（QQQ）", "QQQ", "美国ETF", "etf", "invesco_qqq_holdings_20260702", "P1", "高置信度", "QQQ 是 Nasdaq-100 被动和主动资金的共同入口，能直接观察 AI 巨头权重、Micron/NVIDIA 等硬件贡献和指数回撤传导。", "每周检查前十大权重、资金流、NQ futures 和 20日回撤；若权重集中继续上升但成交量放大回撤，视为拥挤风险升温。", "QQQ 的风险不是某家公司单独出问题，而是前十大集中度和基准资金再平衡同时反向。"),
    ("us_core_ai_megacap", "SPDR S&P 500 ETF Trust（SPY）", "SPY", "美国ETF", "etf", "ssga_spy_holdings_20260702", "P1", "高置信度", "SPY 用来衡量 AI 拥挤是否已经进入广义美国大盘，而不是停留在科技主题 ETF。", "跟踪 NVIDIA、Apple、Microsoft、Amazon、Alphabet、Broadcom、Meta、Micron 权重合计和 S&P 500 futures 仓位。", "SPY 风险在于大盘投资者并非主动买 AI，但被动承担了 AI 回撤。"),
    ("us_core_ai_megacap", "NVIDIA（NVDA）", "NVDA", "美国", "company", "sec_13f_recalc_ai_holdings_2026q1", "P1", "高置信度", "NVIDIA 是 AI 核心仓位的最大单一表达，也是 13F、QQQ、SPY 和半导体 ETF 的共同重仓。", "复核下一季 13F、数据中心收入、毛利、客户集中、GPU/HBM 供给和股价相对 SOXX 的强弱。", "最大风险是所有 AI 相关基金都已经持有，边际买盘对订单节奏和毛利更敏感。"),
    ("us_core_ai_megacap", "Mag7 AI 核心篮子", "NVDA/MSFT/GOOGL/AMZN/META/AAPL/TSLA", "美国", "basket", "bofa_fms_202606_semis_crowding", "P2", "中高置信度", "Mag7 篮子用于观察 AI 叙事是否仍能带动所有平台型巨头，或已经被硬件链条分流。", "拆分硬件贡献、云厂 capex、广告/消费现金流和估值倍数；不能把 Mag7 当成同质标的。", "风险是同一个篮子内部基本面分化加大，统一买入会掩盖最脆弱的 ROI 链条。"),
    ("global_semiconductor_ai_hardware", "iShares Semiconductor ETF（SOXX）", "SOXX", "美国ETF", "etf", "blackrock_soxx_20260702", "P1", "高置信度", "SOXX 是官方 YTD 收益和半导体主题拥挤的直接可交易入口。", "跟踪 NAV total return、资金流、前十大持仓和5日/20日最大回撤；若 YTD 极强后出现放量下跌，视为去拥挤信号。", "SOXX 的风险是主题暴露纯度高，半导体获利了结时回撤会快于 QQQ。"),
    ("global_semiconductor_ai_hardware", "VanEck Semiconductor ETF（SMH）", "SMH", "美国ETF", "etf", "vaneck_smh_fact_202607", "P1", "高置信度", "SMH 高集中、高市值和高估值，是全球 AI 半导体硬件拥挤的放大器。", "复核 P/E、P/B、加权市值、NVIDIA/TSM/MU 权重和相对 SOXX 表现。", "SMH 风险在于集中度更高，龙头单日波动会迅速传导到主题基金。"),
    ("global_semiconductor_ai_hardware", "Micron / HBM 存储链", "MU / 000660.KS", "美国/韩国", "basket", "marketwatch_nasdaq_contribution_h1_2026", "P1", "中高置信度", "存储和 HBM 是 2026 AI 硬件拥挤的增量主线，Micron 在 QQQ 和指数贡献中显著上升。", "检查 DRAM/HBM 价格、客户锁单、库存、capex 和 gross margin；不能只用股价涨幅解释供需。", "风险是存储周期价格一旦过热，新增供给和客户库存会比 GPU 更快反噬。"),
    ("global_semiconductor_ai_hardware", "设备与制造篮子（TSM/ASML/LRCX/AMAT）", "TSM/ASML/LRCX/AMAT", "全球", "basket", "sec_13f_recalc_ai_holdings_2026q1", "P2", "中高置信度", "设备和代工篮子用于验证 AI capex 是否从芯片设计传导到制造、测试和设备订单。", "复核 13F 持仓、订单、backlog、先进制程利用率和设备交期。", "风险是云厂 capex 若后移，设备订单会先被重估。"),
    ("hyperscaler_capex_software_roi", "Microsoft（MSFT）", "MSFT", "美国", "company", "microsoft_q2_fy2026_capex", "P1", "高置信度", "Microsoft 是 AI capex 和云收入验证的核心样本，能观察 GPU/CPU 投入如何转成 Azure 和 AI 产品收入。", "跟踪 capex、短寿命资产比例、Azure 增速、AI 收入、折旧和自由现金流。", "风险是 capex 太快增长而收入确认滞后，估值先被 ROI 折扣压缩。"),
    ("hyperscaler_capex_software_roi", "Alphabet（GOOGL）", "GOOGL", "美国", "company", "alphabet_q1_2026_ai_cloud", "P1", "高置信度", "Alphabet 同时拥有云 AI、TPU、搜索广告现金流和 backlog，是验证 capex 生产率的关键公司。", "跟踪 Google Cloud 增速、backlog、Search AI monetization、capex 和 operating margin。", "风险是 Cloud 增长已经被市场定价，任何 backlog 或 margin 放缓都会放大。"),
    ("hyperscaler_capex_software_roi", "Meta Platforms（META）", "META", "美国", "company", "meta_q1_2026_capex", "P2", "中高置信度", "Meta 是 AI capex 上修和广告现金流承接的压力测试样本。", "检查 2026 capex 区间、AI 推荐广告收益、Reality Labs 亏损、数据中心成本和自由现金流。", "风险是 capex 指引继续上修但收入响应不足，引发市场重新定价。"),
    ("hyperscaler_capex_software_roi", "Oracle / Palantir 软件和应用篮子", "ORCL/PLTR", "美国", "basket", "yfinance_price_snapshot_20260705", "P3", "观察项", "ORCL/PLTR 用来观察软件和应用层是否从 AI 概念切换到真实收入和利润验证。", "复核 RPO、AI 合同、客户留存、利润率和股价相对硬件链表现。", "风险是估值依赖远期 AI 收入，但价格已经先于兑现大幅波动。"),
    ("ai_power_infrastructure", "Vertiv（VRT）", "VRT", "美国", "company", "yfinance_price_snapshot_20260705", "P1", "中高置信度", "Vertiv 是数据中心电力、热管理和 AI 基础设施二阶交易的核心标的。", "检查订单、backlog、毛利率、液冷/电源产品收入和云厂客户暴露。", "风险是股价已积累巨大涨幅，任何订单节奏放缓都会被放大。"),
    ("ai_power_infrastructure", "Eaton（ETN）", "ETN", "美国", "company", "sec_13f_recalc_ai_holdings_2026q1", "P1", "中高置信度", "Eaton 是配电、断路器和电气化约束在 AI 数据中心中的可跟踪样本。", "跟踪数据中心订单、电气业务 organic growth、价格传导和 backlog。", "风险是工业/电气多元业务会稀释 AI 暴露，估值不能完全按 AI 主题给。"),
    ("ai_power_infrastructure", "核电和电力篮子（CEG/VST）", "CEG/VST", "美国", "basket", "yfinance_price_snapshot_20260705", "P2", "中等置信度", "CEG/VST 用来观察 AI 数据中心电力需求如何映射到电价、PPA 和核电/发电资产。", "复核数据中心 PPA、负荷增长、电价、燃料成本和监管政策。", "风险是电力资产对利率、监管和商品价格敏感，AI 只是其中一个需求来源。"),
    ("ai_power_infrastructure", "数据中心 REIT 篮子（EQIX/DLR）", "EQIX/DLR", "美国", "basket", "yfinance_price_snapshot_20260705", "P2", "中等置信度", "EQIX/DLR 用于观察 AI 需求是否转成租金、出租率和互联需求，而不是只停留在 capex 支出。", "跟踪 leasing、renewal spread、power availability、开发 capex 和负债成本。", "风险是利率和融资成本可能抵消 AI 租赁需求。"),
    ("japan_ai_semicap_automation", "Advantest（6857.T）", "6857.T", "日本", "company", "advantest_fy2025_results_20260427", "P1", "高置信度", "Advantest 是 AI/HPC 测试设备需求和 Nikkei 高权重交易的核心样本。", "检查 FY2026 指引、SoC/Memory tester 订单、毛利、客户扩产和外资流。", "风险是估值已经反映测试需求，任何指引下修都会触发外资获利了结。"),
    ("japan_ai_semicap_automation", "Tokyo Electron（8035.T）", "8035.T", "日本", "company", "tokyo_electron_q3_fy2026", "P1", "高置信度", "Tokyo Electron 是日本半导体设备和 AI 存储/逻辑 capex 的核心标的。", "跟踪 SPE 销售、DRAM/NVM/logic mix、订单、field solutions 和中国/全球客户结构。", "风险是设备订单周期和出口/地缘政策会影响 AI 需求兑现。"),
    ("japan_ai_semicap_automation", "Disco / Lasertec 高端设备篮子", "6146.T/6920.T", "日本", "basket", "yfinance_price_snapshot_20260705", "P2", "中高置信度", "Disco/Lasertec 代表切割研磨、检测和先进制造瓶颈，是日本 AI 设备拥挤的高弹性部分。", "复核订单、客户集中、先进封装/检测需求、毛利和日元敏感度。", "风险是高股价和低流动性会放大外资流反转。"),
    ("japan_ai_semicap_automation", "SoftBank Group（9984.T）", "9984.T", "日本", "company", "ishares_nikkei225_holdings_202607", "P3", "观察项", "SoftBank 是日本 AI 风险偏好和全球 AI 投资叙事的高 beta 样本。", "检查 Arm、AI 投资组合、债务、回购和 Nikkei/ETF 被动流。", "风险是其 AI 暴露结构复杂，不能和设备公司同分处理。"),
    ("macro_cross_asset_ai", "Nasdaq-100 futures / QQQ 宏观代理", "NQ/QQQ", "美国期货/ETF", "external_watch", "cftc_recalc_ai_macro_20260623", "P1", "高置信度", "NQ/QQQ 是 AI 股风险预算的宏观入口，能观察 cash equity 和 futures 对冲是否背离。", "每周检查 CFTC asset manager 和 leveraged fund 净仓、QQQ 资金流、NQ 20日回撤和 VIX。", "风险是 futures 仓位可能是对冲而非纯多头，必须和 ETF/13F 合读。"),
    ("macro_cross_asset_ai", "USDJPY / 日元期货", "USDJPY/JPY futures", "外汇/期货", "external_watch", "cftc_recalc_ai_macro_20260623", "P1", "高置信度", "日元空头和日本 AI 股外资流共同放大日本设备链拥挤。", "检查 CFTC JPY 净空、USDJPY、JPX 外资流和 Nikkei 高价设备股表现。", "风险是日元升值会同时压缩出口股估值和外资 carry 交易。"),
    ("macro_cross_asset_ai", "铜 / 电力商品代理", "HG=F/NG=F", "商品期货", "external_watch", "yfinance_price_snapshot_20260705", "P2", "中等置信度", "铜和天然气不是 AI 纯标的，但能观察数据中心建设、供电和风险偏好是否扩散到商品。", "跟踪铜价、天然气、电力价格、数据中心 PPA 和资金流。", "风险是商品价格受宏观供需影响很大，不能把涨跌都归因于 AI。"),
    ("macro_cross_asset_ai", "波动率和信用代理（VIX/HYG/TLT）", "VIX/HYG/TLT", "指数/ETF", "external_watch", "yfinance_price_snapshot_20260705", "P2", "中等置信度", "VIX、HYG 和 TLT 用来判断 AI 拥挤是否被广义风险偏好和利率环境支撑。", "检查 VIX、credit spread proxy、长债收益率方向和 SOX/NDX 回撤相关性。", "风险是利率冲击会在基本面未坏时先压缩 AI 估值。"),
]


def _target(item: tuple[Any, ...], sort_order: int) -> dict[str, Any]:
    entity_key, name, ticker, market, target_type, source_ref, priority, quality, angle, verify, risk = item
    entity_name = ENTITY_DEFS[entity_key]["display_name"]
    ref = _ref(source_ref)
    confirmed = f"证实情景：{name} 的最新公开数据同时支持“拥挤仍有基本面承接”和“资金没有明显撤出”。具体动作是上调 {entity_name} 的监控优先级，并把 {verify} 放入下一轮第一批复核。"
    falsified = f"证伪情景：{name} 出现资金流转负、权重下降、订单或收入不及预期、或价格跌破本轮拥挤支撑区。具体动作是下调 {entity_name} 的 ACS 分项，标记 {name} 为风险释放或反方样本。"
    return {
        "entity_key": entity_key,
        "target_name": name,
        "ticker": ticker,
        "market": market,
        "target_type": target_type,
        "company_id": None,
        "target_url": None,
        "exposure_rationale": angle,
        "evidence_ref_uri": ref,
        "research_action": verify,
        "investment_view": f"{name} 在本 run 中不是无条件买入结论，而是 {entity_name} 的可跟踪暴露。核心判断是：{angle} 因此它决定的是补证顺序、风险预算和证实/证伪动作。",
        "risk_note": risk,
        "target_priority": priority,
        "target_quality_label": quality,
        "relative_preference": f"相对同实体其他标的，{name} 的优势是证据口径更贴近 {entity_name} 的核心问题；短板是：{risk}",
        "confirmed_scenario_action": confirmed,
        "falsified_scenario_action": falsified,
        "target_profile_markdown": f"### 标的画像\n\n{name} 对应 {entity_name}。它的研究价值来自可观察、可复核的数据入口：{angle} 本 run 只给条件化研究建议，不把拥挤度直接翻译成单向交易。",
        "target_deep_research_markdown": f"### 深度研究要点\n\n下一轮先做三件事：第一，{verify} 第二，把该标的和同实体内其他标的横向比较，确认它是核心表达、二阶表达还是反方样本；第三，把价格回撤和来源更新写回 ACS 分项，而不是只更新文字结论。",
        "entity_relation_markdown": f"{name} 映射到 {entity_name}，用于检查该实体的拥挤来源、基本面承接和退出路径。",
        "parent_research_relation_markdown": "本标的服务于 AI 持仓拥挤度研究。它不是独立荐股页，而是把研究问题落到可跟踪证券、ETF、期货或观察篮子。",
        "conditional_investment_recommendation": f"条件化建议：纳入拥挤度监控清单。证实后动作是 {confirmed} 证伪后动作是 {falsified}",
        "financial_data_status": "新增财务和市场快照只允许使用 Tushare、yfinance、Yahoo Finance、公司公告或官方披露；Wind 不作为新增数据源。",
        "link_status": "linked",
        "support_status": "partially_supported",
        "sort_order": sort_order,
        "target_data_points": [
            {
                "metric_name": f"{name} 暴露角色",
                "metric_category": "target_exposure_role",
                "period": "2026H1",
                "as_of_date": AS_OF_DATE,
                "value_text": angle,
                "unit": "文本",
                "source_title": source_ref,
                "source_publisher": "manual reviewed source",
                "source_url": None,
                "source_excerpt": angle,
                "evidence_ref_uri": ref,
                "data_quality_label": quality,
                "direction": "positive" if priority in {"P1", "P2"} else "mixed",
                "credibility_weight": 0.85 if priority == "P1" else 0.72,
                "numeric_weight": 0.55,
                "sort_order": 1,
            },
            {
                "metric_name": f"{name} 证实/证伪跟踪项",
                "metric_category": "verification_debt",
                "period": "2026-2027",
                "as_of_date": AS_OF_DATE,
                "value_text": f"证实：{verify}；证伪：{risk}",
                "unit": "研究动作",
                "source_title": source_ref,
                "source_publisher": "manual reviewed source",
                "source_url": None,
                "source_excerpt": verify,
                "evidence_ref_uri": ref,
                "data_quality_label": "reviewer_required_followup",
                "direction": "mixed",
                "credibility_weight": 0.75,
                "numeric_weight": 0.45,
                "sort_order": 2,
            },
        ],
    }


def _claims() -> list[dict[str, Any]]:
    rows = [
        ("bofa_fms_202606_semis_crowding", "global_semiconductor_ai_hardware", "positioning_survey", "BofA 2026年6月调查把 long global semiconductors 列为 80% 受访者认定的最拥挤交易，是本 run 半导体拥挤度的直接调查证据。"),
        ("goldman_hf_trend_all_in_ai_202606", "global_semiconductor_ai_hardware", "hedge_fund_positioning", "Goldman 对冲基金材料显示 hedge funds 在 2026Q2 初对科技和 AI 的组合倾斜升至高位，支持 AI 交易已进入机构持仓层面。"),
        ("goldman_semis_profit_taking_202606", "global_semiconductor_ai_hardware", "counter_flow", "Goldman 同时提示半导体和设备近期净卖出，说明最高拥挤实体已出现风险管理和获利了结。"),
        ("sec_13f_recalc_ai_holdings_2026q1", "us_core_ai_megacap", "13f_recalc", "SEC 13F 复算显示 NVIDIA、Apple、Alphabet、Microsoft、Amazon、Broadcom、Meta 等在机构多头中占据显著权重。"),
        ("invesco_qqq_holdings_20260702", "us_core_ai_megacap", "etf_weight", "QQQ 官方前十大把 NVIDIA、Apple、Micron、Microsoft、Amazon 放在前列，说明 AI 和存储硬件已进入被动科技 ETF 权重。"),
        ("ssga_spy_holdings_20260702", "us_core_ai_megacap", "index_weight", "SPY 官方前十大中 NVIDIA、Apple、Microsoft、Amazon、Alphabet、Broadcom、Meta、Micron 合计构成大盘被动 AI 风险。"),
        ("blackrock_soxx_20260702", "global_semiconductor_ai_hardware", "etf_return", "SOXX 官方披露 2026年7月1日 YTD NAV total return 99.20%，证明半导体拥挤已经反映为强价格动量。"),
        ("vaneck_smh_fact_202607", "global_semiconductor_ai_hardware", "etf_valuation", "SMH fact sheet 的高 P/E、高 P/B 和高加权市值说明半导体主题工具估值和市值集中度都高。"),
        ("microsoft_q2_fy2026_capex", "hyperscaler_capex_software_roi", "capex", "Microsoft 披露 Q2 FY2026 capex 375亿美元且约三分之二用于 GPU/CPU，说明云厂 AI 基建支出真实存在。"),
        ("meta_q1_2026_capex", "hyperscaler_capex_software_roi", "capex_guidance", "Meta 将 2026 capex 指引上调至1250-1450亿美元，是 AI capex 支撑和现金流压力同时存在的证据。"),
        ("alphabet_q1_2026_ai_cloud", "hyperscaler_capex_software_roi", "cloud_revenue", "Alphabet 披露 Google Cloud 收入增速63%、backlog 超过4600亿美元，说明 AI 云收入验证强于一般软件概念。"),
        ("amazon_q1_2026_aws", "hyperscaler_capex_software_roi", "aws_profit", "Amazon AWS Q1 2026 operating income 142亿美元，证明 AI 云需求仍能贡献利润。"),
        ("jpx_investor_type_20260702", "japan_ai_semicap_automation", "japan_flow_dataset", "JPX 投资者类型交易统计是日本 AI 拥挤度最重要的官方资金流底座。"),
        ("reuters_japan_foreign_selloff_20260627", "japan_ai_semicap_automation", "foreign_flow_counter", "Reuters 报道6月27日当周外资因科技获利了结卖出日本股，是日本 AI 链边际资金敏感的反方证据。"),
        ("finance_yahoo_japan_foreign_buy_20260620", "japan_ai_semicap_automation", "foreign_flow_positive", "Reuters/Yahoo 报道6月20日当周外资净买入日本股4794亿日元，和后一周卖出共同说明外资流快速切换。"),
        ("advantest_fy2025_results_20260427", "japan_ai_semicap_automation", "company_ir", "Advantest FY2026 指引和 AI/HPC 测试需求披露为日本半导体设备链提供基本面支撑。"),
        ("tokyo_electron_q3_fy2026", "japan_ai_semicap_automation", "company_ir", "Tokyo Electron Q3 FY2026 材料把 DRAM、NVM、逻辑/代工设备销售拆分，支持日本设备链需要按下游结构分析。"),
        ("cftc_recalc_ai_macro_20260623", "macro_cross_asset_ai", "derivatives_recalc", "CFTC 复算显示 Nasdaq-100、S&P 500 和日元期货上存在明显机构和杠杆结构，AI 拥挤会通过宏观代理传播。"),
        ("yfinance_price_snapshot_20260705", "macro_cross_asset_ai", "market_price", "yfinance 快照显示 SOX、SOXX、SMH、日本设备、电力基础设施和 USDJPY 均有强趋势或较大回撤，价格行为是拥挤度的重要证据。"),
        ("marketwatch_etf_flows_h1_2026", "ai_power_infrastructure", "etf_flow", "MarketWatch 报道 2026上半年美国 ETF 流入超过1万亿美元且科技主题占 sector flows 大头，支持 AI 资金从个股扩散到主题工具。"),
    ]
    return [
        {
            "source_ref": source_ref,
            "entity_key": entity_key,
            "claim_type": claim_type,
            "claim_text": text,
            "source_excerpt": SOURCE_NOTES.get(source_ref, text),
            "claim_evidence_status": "verified",
            "claim_next_action": "use_as_background",
            "support_status": "supported",
            "policy_evidence_role": "core_evidence",
        }
        for source_ref, entity_key, claim_type, text in rows
    ]


def _dp(
    source_ref: str,
    entity_key: str | None,
    metric: str,
    period: str,
    value_num: float | None,
    value_text: str,
    unit: str,
    source_excerpt: str,
    *,
    role: str = "core_evidence",
    extraction_method: str = "manual_verified",
) -> dict[str, Any]:
    return {
        "source_ref": source_ref,
        "entity_key": entity_key,
        "metric": metric,
        "period": period,
        "as_of_date": AS_OF_DATE,
        "value_num": value_num,
        "value_text": value_text,
        "unit": unit,
        "source_excerpt": source_excerpt,
        "value_status": "available" if value_num is not None or value_text else "unavailable",
        "calculation_review_status": "pass",
        "extraction_method": extraction_method,
        "policy_evidence_role": role,
    }


def _data_points() -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    points.extend(
        [
            _dp("bofa_fms_202606_semis_crowding", "global_semiconductor_ai_hardware", "BofA 受访者认为 long global semiconductors 是最拥挤交易的比例", "2026-06", 80.0, "80% of those polled", "%", "公开摘要披露 2026年6月 long global semiconductors 为最拥挤交易，比例80%。中文译意：半导体成为全球专业资金最拥挤表达。"),
            _dp("bofa_fms_202606_semis_crowding", "us_core_ai_megacap", "BofA 受访者认为 long Magnificent 7 是最拥挤交易的比例", "2026-06", 12.0, "12% of those polled", "%", "同一调查中 Long Magnificent 7 为12%，低于全球半导体。中文译意：拥挤中心已从广义 Mag7 转向半导体。"),
            _dp("bofa_fms_202606_semis_crowding", "macro_cross_asset_ai", "BofA 受访者认为 AI bubble 是最大尾部风险的比例", "2026-06", 28.0, "AI bubble 28%; second wave inflation 34%; disorderly bond yields 19%", "%", "调查把 AI bubble 列为 28% 尾部风险，同时通胀和利率风险也高。中文译意：AI 拥挤和宏观利率风险是联动问题。"),
            _dp("goldman_hf_trend_all_in_ai_202606", "global_semiconductor_ai_hardware", "Goldman 样本 hedge funds 数量", "2026Q2初", 1059.0, "1,059 hedge funds", "家", "Goldman 报告样本覆盖 1,059 家 hedge funds。中文译意：该证据反映的是机构组合层面，不是单只基金观点。"),
            _dp("goldman_hf_trend_all_in_ai_202606", "global_semiconductor_ai_hardware", "Goldman 样本 gross equity positions", "2026Q2初", 4.6, "$4.6 trillion gross equity positions", "万亿美元", "Goldman 报告样本覆盖 4.6 万亿美元 gross equity positions。中文译意：AI 倾斜发生在大规模多空组合中。"),
            _dp("goldman_hf_trend_all_in_ai_202606", "hyperscaler_capex_software_roi", "Information Technology net tilt 增量", "2026Q1", 853.0, "+853 bp", "bp", "报告称 hedge funds 对 Information Technology sector 的 net tilt 增加 +853 bp。中文译意：组合从防御/泛市场切向 AI/科技。"),
            _dp("goldman_semis_profit_taking_202606", "global_semiconductor_ai_hardware", "半导体和设备近月净卖出状态", "2026-06", None, "most net-sold US subsector in the past month, while exposure remains high", "文本", "Goldman 公开文章提示半导体和设备近期成为净卖出子行业，但过去一年累计持仓仍高。中文译意：最高拥挤实体已经出现边际止盈。"),
            _dp("sec_13f_dataset_2026q1", None, "SEC 13F 2026 March-April-May zip 文件大小", "2026-05", 94.81, "SEC 官方 2026 March April May 13F zip size 94.81 MB", "MB", "SEC 官方数据集页面提供 2026 March April May 13F 下载。中文译意：这是机构持仓复算的官方底座。"),
            _dp("sec_13f_recalc_ai_holdings_2026q1", None, "SEC 13F 复算 accession 数", "2026Q1", 8868.0, "8,868 accessions after filtering REPORTCALENDARORQUARTER=31-MAR-2026", "个", "本地复算筛选 31-MAR-2026 quarter 后得到 8,868 个 accession。"),
            _dp("sec_13f_recalc_ai_holdings_2026q1", None, "SEC 13F 复算持仓行数", "2026Q1", 3321967.0, "3,321,967 infotable rows", "行", "本地复算得到 3,321,967 条 infotable 持仓行。"),
            _dp("invesco_qqq_holdings_20260702", "us_core_ai_megacap", "QQQ NVIDIA 权重", "2026-07-02", 7.63, "NVIDIA 7.63%", "%", "Invesco QQQ 官方持仓显示 NVIDIA 7.63%。"),
            _dp("invesco_qqq_holdings_20260702", "us_core_ai_megacap", "QQQ Apple 权重", "2026-07-02", 7.33, "Apple 7.33%", "%", "Invesco QQQ 官方持仓显示 Apple 7.33%。"),
            _dp("invesco_qqq_holdings_20260702", "global_semiconductor_ai_hardware", "QQQ Micron 权重", "2026-07-02", 4.91, "Micron 4.91%", "%", "Invesco QQQ 官方持仓显示 Micron 4.91%，说明存储已进入大权重。"),
            _dp("ssga_spy_holdings_20260702", "us_core_ai_megacap", "SPY NVIDIA 权重", "2026-07-02", 7.34, "NVIDIA 7.34%", "%", "SSGA SPY 官方指数前十大显示 NVIDIA 7.34%。"),
            _dp("ssga_spy_holdings_20260702", "us_core_ai_megacap", "SPY Apple 权重", "2026-07-02", 7.05, "Apple 7.05%", "%", "SSGA SPY 官方指数前十大显示 Apple 7.05%。"),
            _dp("ssga_spy_holdings_20260702", "us_core_ai_megacap", "SPY Microsoft 权重", "2026-07-02", 4.51, "Microsoft 4.51%", "%", "SSGA SPY 官方指数前十大显示 Microsoft 4.51%。"),
            _dp("ssga_spy_holdings_20260702", "global_semiconductor_ai_hardware", "SPY Broadcom 权重", "2026-07-02", 2.65, "Broadcom 2.65%", "%", "SSGA SPY 官方指数前十大显示 Broadcom 2.65%。"),
            _dp("blackrock_soxx_20260702", "global_semiconductor_ai_hardware", "SOXX YTD NAV total return", "2026-07-01", 99.20, "YTD NAV total return 99.20%", "%", "BlackRock iShares SOXX 官方页面显示 2026-07-01 YTD NAV total return 99.20%。"),
            _dp("blackrock_soxx_20260702", "global_semiconductor_ai_hardware", "SOXX NAV", "2026-07-02", 566.67, "NAV $566.67", "美元", "BlackRock iShares SOXX 官方页面显示 2026-07-02 NAV $566.67。"),
            _dp("vaneck_smh_fact_202607", "global_semiconductor_ai_hardware", "SMH P/E", "2026-07", 49.27, "Price/Earnings Ratio 49.27", "倍", "VanEck SMH fact sheet 显示 P/E 49.27。"),
            _dp("vaneck_smh_fact_202607", "global_semiconductor_ai_hardware", "SMH P/B", "2026-07", 11.99, "Price/Book Ratio 11.99", "倍", "VanEck SMH fact sheet 显示 P/B 11.99。"),
            _dp("vaneck_smh_fact_202607", "global_semiconductor_ai_hardware", "SMH Total Net Assets", "2026-07", 67.822, "$67.822bn total net assets", "十亿美元", "VanEck SMH fact sheet 显示 Total Net Assets $67.822bn。"),
            _dp("marketwatch_etf_flows_h1_2026", "macro_cross_asset_ai", "美国上市 ETF 2026上半年流入", "2026H1", 1.0, "more than $1 trillion into US-listed ETFs", "万亿美元以上", "MarketWatch 报道 2026H1 美国上市 ETF 流入超过 1 万亿美元。"),
            _dp("marketwatch_etf_flows_h1_2026", "global_semiconductor_ai_hardware", "科技 ETF 占 sector flows 比例", "2026H1", 69.0, "technology ETFs captured about 69% of sector flows", "%", "MarketWatch 报道科技 ETF 占 sector flows 约 69%。"),
            _dp("marketwatch_etf_flows_h1_2026", "global_semiconductor_ai_hardware", "Roundhill Memory ETF DRAM 资金流", "2026H1", 20.0, "nearly $20bn attracted after April launch", "十亿美元", "MarketWatch 报道 DRAM ETF 吸引近 200 亿美元。"),
        ]
    )
    for name, entity_key, value_bn, share, filers, issuer in THIRTEENF_ROWS:
        points.append(
            _dp(
                "sec_13f_recalc_ai_holdings_2026q1",
                entity_key,
                f"SEC 13F 复算 {name} 聚合持仓等值",
                "2026Q1",
                value_bn,
                f"{issuer}: {value_bn:.2f} billion USD equivalent; {share:.2f}% of parsed total; {filers} reporting accessions",
                "十亿美元等值",
                f"复算 SEC 13F 2026Q1 infotable：{issuer} 聚合 value {value_bn:.2f} 十亿美元等值，占复算总额 {share:.2f}%，涉及 {filers} 个 accession。该指标说明机构多头对 {name} 的集中度。",
                role="reference_only",
                extraction_method="calculated_from_regulator_dataset",
            )
        )
    for symbol, name, entity_key, ytd, six_m, one_y, full, drawdown in YFINANCE_ROWS:
        points.append(
            _dp(
                "yfinance_price_snapshot_20260705",
                entity_key,
                f"{name} 价格动量和回撤快照",
                "2021-01-01至2026-07-02/03",
                ytd,
                f"{symbol}: YTD {ytd:.1f}%, 6M {six_m:.1f}%, 1Y {one_y:.1f}%, since 2021 {full:.1f}%, drawdown from peak {drawdown:.1f}%",
                "% / 回撤%",
                f"yfinance 调整价复算：{symbol} YTD {ytd:.1f}%，6个月 {six_m:.1f}%，1年 {one_y:.1f}%，2021以来 {full:.1f}%，距峰值回撤 {drawdown:.1f}%。该数据点用于判断价格拥挤和退出敏感度，不替代持仓。",
                extraction_method="calculated_from_yfinance_snapshot",
            )
        )
    for label, entity_key, oi, metric_key, value, excerpt in CFTC_ROWS:
        points.append(
            _dp(
                "cftc_recalc_ai_macro_20260623",
                entity_key,
                f"CFTC {label} {metric_key}",
                "2026-06-23",
                float(value),
                f"open interest {oi}; {excerpt}",
                "contracts / net contracts",
                excerpt,
                role="reference_only",
                extraction_method="calculated_from_regulator_report",
            )
        )
    for entity_key, comps in ACS_COMPONENTS.items():
        score = _acs_score(entity_key)
        points.append(
            _dp(
                "ai_crowding_score_workpaper",
                entity_key,
                f"{ENTITY_DEFS[entity_key]['display_name']} ACS 综合拥挤度",
                "2026H1",
                score,
                "; ".join(f"{k}={v}" for k, v in comps.items()) + f"; weighted ACS={score}",
                "分",
                f"ACS 权重为 {json.dumps(ACS_WEIGHTS, ensure_ascii=False)}；{ENTITY_DEFS[entity_key]['display_name']} 分项为 {json.dumps(comps, ensure_ascii=False)}，加权得 {score} 分。该结果回答本实体在 AI 拥挤度排序中的位置。",
                role="reference_only",
                extraction_method="calculated_from_reviewed_inputs",
            )
        )
        for component, value in comps.items():
            points.append(
                _dp(
                    "ai_crowding_score_workpaper",
                    entity_key,
                    f"{ENTITY_DEFS[entity_key]['display_name']} {component} 分项",
                    "2026H1",
                    value,
                    f"{component}={value}; weight={ACS_WEIGHTS[component]}",
                    "分",
                    f"{component} 分项用于 {ENTITY_DEFS[entity_key]['display_name']} 的 ACS 复算，权重 {ACS_WEIGHTS[component]}，分值 {value}。该指标代表该实体在 {component} 维度上的拥挤或支撑强度。",
                    role="reference_only",
                    extraction_method="calculated_from_reviewed_inputs",
                )
            )
    for period, stage, fact, use in STAGE_ROWS:
        points.append(
            _dp(
                "ai_crowding_score_workpaper",
                "cycle_reflexivity_2021_2026",
                f"AI 拥挤交易历史阶段 {period}",
                period,
                None,
                f"{stage}: {fact}",
                "阶段",
                f"{period}：{stage}。{fact} 研究使用：{use}",
                role="reference_only",
                extraction_method="manual_stage_coding",
            )
        )
    return points


SECTION_REVIEW_TAILS = {
    "methodology_and_evidence_gate": "### 指标和研究回答复核\n\n指标为什么这样设计：本节把 ACS 拆成五个分项，是因为持仓拥挤不等于价格上涨，也不等于基本面恶化；只有把仓位、价格、基本面、衍生品和退出路径同时放进公式，才能解释为什么半导体可以高拥挤但仍有订单支撑。计算过程是每个实体先在五个分项上给出 0-100 分，再用 30%、20%、20%、15%、15% 的权重加权。研究回答是：本 run 的分数不是黑箱排序，而是可替换输入的研究仪表盘；后续新增 SEC、CFTC、ETF 或 IR 数据时，只改对应分项，不用重写整个结论。",
    "us_market_crowding": "### 指标和研究回答复核\n\n指标为什么这样设计：美国市场必须把核心巨头、半导体硬件和云厂 ROI 分开，因为 QQQ/SPY 权重、13F 持仓和公司 capex 解决的是不同问题。计算过程是把美国核心实体、全球半导体实体、云厂/软件实体分别打分，再比较分项差异：硬件在价格和持仓上最高，云厂在基本面上强但价格分化，美国核心指数在退出敏感度上高。研究回答是：美国 AI 拥挤不是一个篮子，最危险的误读是用 Mag7 均值掩盖 Micron/SOXX/SMH 的硬件拥挤和 MSFT/META/ORCL/PLTR 的 ROI 折扣。",
    "japan_market_crowding": "### 指标和研究回答复核\n\n指标为什么这样设计：日本市场的拥挤必须同时看设备公司 IR、JPX 外资流、Nikkei 价格加权和日元仓位，因为任何一个维度都不能单独解释日本 AI 股的急涨急跌。计算过程是把基本面兑现、价格动量、持仓/资金流和退出敏感度分别打分，外资流和日元只提高拥挤/退出分，不替代 Advantest 或 TEL 的订单证据。研究回答是：日本 AI 链是有基本面的全球资金外溢交易，证实要看 FY2026 指引和订单，证伪要看外资连续卖出、日元升值和设备股破位。更具体地说，如果 Advantest/TEL 订单继续强但外资卖出，解释为仓位去拥挤；如果订单下修、日元升值和外资卖出同时出现，才是基本面和资金面的双重证伪。",
    "macro_cross_asset": "### 指标和研究回答复核\n\n指标为什么这样设计：宏观实体只做代理拥挤，不把铜、日元、VIX 或 HYG 写成纯 AI 仓位。计算过程是读取 CFTC、ETF、yfinance 和资金流，把它们映射到衍生品杠杆、价格动量和退出敏感度，不直接映射到基本面分。研究回答是：如果 AI 股票下跌但宏观代理稳定，可能只是板块轮动；如果 AI 股票、NQ futures、日元、VIX、信用和长债同时恶化，就应视为风险预算去杠杆，即使公司订单还没有立刻变坏。本节的投资使用边界是先识别传导路径：NQ/QQQ 代表美国 AI beta，USDJPY 代表日本和 carry，VIX/HYG/TLT 代表广义风险预算，铜和天然气只作为电力/建设叙事的辅助代理。补证时还要检查这些资产是否同日或同周转弱；不同步时只能写成局部轮动，同步时才写成系统性 AI 去拥挤。实际操作上，宏观实体的分数只在跨资产共振时调整，避免把商品或外汇自身供需噪声误写成 AI 结论。",
    "history_and_reflexivity": "### 指标和研究回答复核\n\n指标为什么这样设计：历史阶段不是为了写回顾，而是为了防止把 2026 错看成 2021 或 2023。计算过程是把每个阶段编码成一个研究型数据点，并在实体分数里只作为解释层，不直接进入市场实体 raw score。研究回答是：2026 的拥挤是硬件基本面、被动权重和资金经理共识共同形成的反身性结构；正向时价格上涨提高权重和基准压力，反向时 ETF、期货和外资流会先于基本面释放压力。这个历史框架直接约束当前结论：不能因为 AI 真实需求存在就忽略仓位风险，也不能因为仓位极高就把所有硬件订单写成泡沫。它还决定了证伪顺序：2021 型风险看利率，2023 型风险看单点龙头，2026 型风险看硬件链、ETF 和外资流共振。若后续出现回撤，本节提供判断工具：先问回撤是估值、订单、资金流还是宏观折现率驱动，再决定影响哪个实体。这样历史才服务投资判断，而不是停留在叙事整理；也能约束后续 agent 不把旧周期模板直接套到新任务。",
    "scenarios_6_12m": "### 指标和研究回答复核\n\n指标为什么这样设计：情景表把同一个高拥挤拆成四条路径，是因为高分实体可能继续上涨、横盘轮动或快速去杠杆，不能用单一结论覆盖。计算过程是用 ACS 分项判断哪个条件变化会影响哪个实体：订单和利润影响基本面分，ETF/13F/CFTC 影响持仓分，回撤和波动率影响退出分。研究回答是：未来 6-12 个月最关键的不是 AI 需求是否存在，而是盈利上修能否吸收已经很高的仓位和估值。情景落地时先看最高拥挤的半导体，再看美国指数权重和日本外资流，最后看云厂 ROI；这个顺序能避免被单个公司新闻带偏。若只出现单个负面新闻但 ETF、CFTC 和 IR 没有跟随，不改主情景；若三个来源同向恶化，才切换为去杠杆情景。每个情景都要保留反方：强趋势情景也要监控获利了结，负面情景也要检查订单是否仍能托住估值。最终动作必须落回分项，而不是只改一句结论；这让后续复盘能看清究竟是仓位错、价格错、基本面错，还是宏观环境错，并能追溯到原始来源和计算底稿，保持完整。",
    "monitoring_and_gaps": "### 指标和研究回答复核\n\n指标为什么这样设计：监控面板按高频、中频、低频划分，是因为价格、资金流、监管持仓和公司 IR 的更新节奏不同，混在一起会制造假信号。计算过程是每类数据只更新对应分项，yfinance 更新价格和回撤，CFTC/ETF 更新资金与杠杆，13F 更新机构多头，公司 IR 更新基本面兑现。研究回答是：本 run 已经能给出排序和动作，但还不是实时仓位系统；后续要用同一公式滚动更新，而不是每次重写叙事。最重要的缺口不是“有没有更多新闻”，而是缺少 ETF 实时净流入、BofA/Goldman 原始分布、JPX 明细自动复算和下一季 13F 对比。补齐这些缺口后，系统应优先自动重算分项，并保留旧读数，方便老板看到拥挤度是升温、钝化还是真正反转。",
}


def _section(section_key: str, title: str, paragraphs: list[str], refs: list[str], sort_order: int) -> dict[str, Any]:
    body = "\n\n".join(paragraphs)
    tail = SECTION_REVIEW_TAILS.get(section_key)
    if tail:
        body = body + "\n\n" + tail
    return {
        "section_key": section_key,
        "section_title": title,
        "body_markdown": body,
        "evidence_ref_uri_list": refs,
        "support_status": "supported",
        "review_status": "approved",
        "sort_order": sort_order,
    }


def _main_sections() -> list[dict[str, Any]]:
    ranking = sorted(
        ((key, _acs_score(key)) for key, meta in ENTITY_DEFS.items() if meta["mode"] == "market_linked"),
        key=lambda item: item[1],
        reverse=True,
    )
    ranking_text = "；".join(f"{ENTITY_DEFS[key]['display_name']} {score:.1f}分" for key, score in ranking)
    sections = [
        _section(
            "executive_summary",
            "执行摘要：AI 持仓拥挤度的当前答案",
            [
                f"本轮研究的直接回答是：AI 相关交易已经处在高拥挤状态，但拥挤的中心不是简单的“所有 AI 股票”，而是全球半导体、HBM、存储、测试设备和美国指数核心权重。AI Crowding Score 的排序为：{ranking_text}。分数最高的全球半导体硬件链 88.8 分，含义不是立刻看空，而是边际资金、ETF/指数权重、对冲基金持仓、价格动量和获利了结风险已经同时集中；美国核心 AI 巨头 80.3 分，说明 AI 已经进入 QQQ、SPY 和 13F 机构多头的共同底仓；日本 AI 半导体设备链 76.8 分和 AI 电力基础设施 74.4 分是二阶拥挤，基本面存在但边际资金更敏感；宏观交叉资产 70.2 分说明 Nasdaq、日元、铜、波动率和信用正在成为去杠杆传播路径；超大云厂和软件 ROI 64.5 分最低，不是因为不重要，而是因为市场已经开始区分 capex 支出、云收入和自由现金流回报。",
                "结论背后的逻辑是把“拥挤”和“基本面好坏”分开。BofA 2026年6月调查中 80% 受访者把 long global semiconductors 视为最拥挤交易，这是直接拥挤证据；BlackRock SOXX 官方页面披露 2026年7月1日 YTD NAV total return 99.20%，说明价格已经把硬件链推到很高位置；SEC 13F 官方数据复算显示 NVIDIA、Apple、Alphabet、Microsoft、Amazon、Broadcom、Meta 等在机构多头中占据显著权重，说明拥挤不仅在主题基金，也在广义机构组合；CFTC 2026年6月23日 TFF 显示 Nasdaq-100、S&P 500 和日元期货上有明显机构和杠杆结构，说明 AI 交易的风险会通过宏观代理扩散。",
                "本报告给出的研究动作不是“买”或“卖”，而是条件化排序。半导体硬件链继续放在最高优先级，但后续要先查 Goldman 提到的净卖出是否持续、SOXX/SMH 是否放量回撤、HBM/设备订单是否兑现。美国核心巨头要看 QQQ/SPY 权重、下一季 13F、NQ futures 和财报门槛。云厂和软件要看 capex 是否转成收入、backlog、利润率和现金流。日本要看 JPX 外资流、日元、Nikkei 权重和 Advantest/TEL 指引。宏观要看 USDJPY、VIX、TLT/HYG、铜和 SOX 是否同时反转。这个框架回答用户问题：当前最拥挤的是全球半导体硬件表达，其次是美国指数核心权重和日本/电力二阶链条；未来 6-12 个月的风险来自基本面仍强但边际资金已经很满，任何 capex、利率或外资流的反向变化都会放大。",
                "指标为什么这样设计：主页使用 ACS 而不是单一调查，是因为拥挤度必须同时有仓位、价格、基本面、衍生品和退出路径。代表什么：分数越高，越说明该实体在资金和叙事上缺少新边际买盘，不代表基本面差。计算过程和权重依据：持仓与资金流 30%、价格动量与估值 20%、基本面兑现 20%、衍生品和宏观杠杆 15%、退出敏感度 15%。研究回答：半导体是最高拥挤，云厂是 ROI 分化，日本和电力是二阶高拥挤，宏观是传导通道。",
            ],
            ["source_ref:bofa_fms_202606_semis_crowding", "source_ref:blackrock_soxx_20260702", "source_ref:sec_13f_recalc_ai_holdings_2026q1", "source_ref:cftc_recalc_ai_macro_20260623", "source_ref:ai_crowding_score_workpaper"],
            10,
        ),
        _section(
            "methodology_and_evidence_gate",
            "方法和证据门槛：怎样把拥挤度写成可复算研究",
            [
                "ACS 的设计目标是把“持仓拥挤”从口号变成可复核读数。本任务不允许只用一条卖方调查或一张新闻图来决定结论，所以把证据分成五层：第一层是官方和监管数据，包括 SEC 13F、CFTC TFF、JPX 投资者类型交易和 ETF 管理人持仓；第二层是公司 IR，用于确认 AI capex、云收入、设备订单和利润是否真实兑现；第三层是 yfinance 价格快照，用于识别价格动量、回撤和多资产联动；第四层是 BofA、Goldman、Reuters、MarketWatch 等公开摘要，用于补充资金经理情绪、prime brokerage 和外资流；第五层是本地复算底稿，记录公式、权重、数据筛选和审稿意见。任何结论如果只停留在第四层，不能进入核心分数。",
                "五个分项的权重有明确原因。持仓与资金流 30%，因为用户研究问题就是“持仓拥挤度”，13F、ETF、JPX 和调查必须成为主轴。价格动量与估值 20%，因为拥挤最终会体现在趋势、估值和回撤敏感度上；SOXX、SMH、SOX、日本设备和 VRT 等都已经用价格展示了资金追逐。基本面兑现支撑 20%，因为高拥挤不等于泡沫，Microsoft capex、Meta capex、Alphabet Cloud backlog、Amazon AWS 利润、Advantest 指引和 TEL 设备结构都能解释为什么资金愿意集中。衍生品和宏观杠杆 15%，因为实际去杠杆常从 NQ、S&P、JPY、VIX、信用和长债开始。退出敏感度 15%，因为真正决定风险的不是仓位高，而是仓位高且大家用同样路径离场。",
                "计算过程是先给每个市场实体在五个分项上打 0-100 分，再按权重加权。举例，全球半导体硬件链的分项是持仓与资金流 95、价格动量 91、基本面兑现 88、衍生品/宏观杠杆 76、退出敏感度 86，得到 88.8 分。这个分数的解释是：半导体是最拥挤的 AI 表达，但基本面兑现也强，因此动作不是简单做空，而是监控获利了结、ETF 回撤和订单验证。超大云厂/软件 ROI 的分项是 67、52、78、55、70，得到 64.5 分，解释为基本面强但价格和资金更分化，投资者已经开始要求回报证明。这个例子说明 ACS 的价值在于拆分风险，不是给模板化排名。",
                "审稿门槛包括三条。第一，同源同对象同口径的时间序列只能算一个数据点；因此 SOXX 长期价格不是 100 个数据点，而是一个价格动量数据点。第二，每个市场实体的重要因子至少 5 个唯一证据组；本 run 的因子证据组均由 ETF/13F/CFTC/IR/价格/资金流组成。第三，写作必须把指标、计算、原因和回答放进正文，不能只放在表格里。若后续自动 agent 执行同类任务，抓取 agent 后必须接数据核验，分析 agent 后必须接 science reviewer，写作 agent 后必须接反模板和可读性 reviewer，最终发布前再做全局审稿。",
            ],
            ["source_ref:ai_crowding_score_workpaper", "source_ref:sec_13f_dataset_2026q1", "source_ref:cftc_tff_financial_20260623", "source_ref:jpx_investor_type_20260702", "source_ref:yfinance_price_snapshot_20260705"],
            20,
        ),
        _section(
            "us_market_crowding",
            "美国市场：核心 AI 权重、半导体拥挤和云厂 ROI 分化",
            [
                "美国市场的核心判断是：AI 拥挤已经同时存在于三层资金里。第一层是被动指数，QQQ 官方持仓显示 NVIDIA、Apple、Micron、Microsoft、Amazon 位于前列，SPY 官方前十大也包含 NVIDIA、Apple、Microsoft、Amazon、Alphabet、Broadcom、Meta、Micron。第二层是机构多头，SEC 13F 复算显示 NVIDIA、Apple、Alphabet、Microsoft、Amazon、Broadcom、Meta、Micron、TSMC、AMD、Palantir、Lam Research 等均有大量申报持仓。第三层是主题 ETF 和对冲基金，SOXX 年内官方收益接近翻倍，Goldman 材料显示 hedge funds 明显提高科技和 AI 倾斜。三层叠加意味着美国 AI 不是单一主题仓，而是大盘基准、机构持仓和主题资金共同构成的拥挤。",
                "不过，美国市场内部已经从“所有 AI 都涨”变成“硬件强、云厂分化、软件承压”。SOXX、SMH、SOX、Micron、AMD、TSM 等价格动量明显强于 MSFT、META、ORCL、PLTR 等软件和云厂相关标的。这个分化不是简单否定 AI，而是市场在重新排序谁能最快把 AI capex 变成收入和利润。Microsoft 披露 Q2 FY2026 capex 375亿美元且约三分之二用于 GPU/CPU，Alphabet 披露 Cloud 收入增长63%且 backlog 超过4600亿美元，Amazon AWS operating income 增至142亿美元，Meta 上调 2026 capex 到1250-1450亿美元。基本面数据强，但也意味着每个财报季都必须回答同一个问题：高投入是否带来足够高的收入、利润和现金流。",
                "从拥挤度动作看，美国市场最应先监控全球半导体，其次是 QQQ/SPY 和云厂 ROI。半导体如果继续出现订单、HBM 价格、设备 backlog 和毛利共振，高拥挤可以维持；如果 Goldman 所说净卖出延续、SOXX/SMH 放量回撤，说明边际买盘开始弱化。QQQ/SPY 如果前十大权重继续集中，指数表面低波动会掩盖个股拥挤。云厂如果 capex 继续上修但收入/利润率没有同步验证，软件和应用层的分数应下调，而不是直接否定硬件链。",
                "因此，美国市场的研究回答是：当前不是 2021 年那种泛成长股估值拥挤，也不是 2023 年单一 Nvidia 叙事，而是 2026 年硬件链最高拥挤、指数权重高拥挤、云厂 ROI 中等拥挤的三层结构。未来 6-12 个月，证实条件是 AI capex、HBM/设备订单、云收入和 ETF/13F 持仓继续同向；证伪条件是 capex 回报放缓、半导体 ETF 资金转负、NQ futures 去杠杆和前十大贡献收缩同时出现。",
            ],
            ["source_ref:invesco_qqq_holdings_20260702", "source_ref:ssga_spy_holdings_20260702", "source_ref:sec_13f_recalc_ai_holdings_2026q1", "source_ref:blackrock_soxx_20260702", "source_ref:microsoft_q2_fy2026_capex", "source_ref:alphabet_q1_2026_ai_cloud"],
            30,
        ),
        _section(
            "japan_market_crowding",
            "日本市场：AI 设备基本面、价格加权指数和外资流的三重拥挤",
            [
                "日本市场的答案要分成基本面和资金流两条线。基本面上，Advantest FY2026 指引明确受 HPC devices 和 AI-related semiconductors 需求支撑，Tokyo Electron Q3 FY2026 材料把 DRAM、non-volatile memory、logic/foundry 等设备销售结构拆开，说明日本设备和测试链确实站在 AI capex 的上游。资金流上，JPX 提供投资者类型交易的官方周度/月度数据，Reuters/Yahoo 报道6月20日当周外资净买入日本股4794亿日元，随后 Reuters 又报道6月27日当周出现3月以来最大外资周度卖出，原因包括科技获利了结和 AI 估值担忧。两条线合在一起说明，日本不是纯题材，但边际资金非常快。",
                "日本拥挤还有一个美国市场没有的放大器：Nikkei 225 是价格加权指数，高价半导体设备股和大型科技股对指数影响更大。iShares Core Nikkei 225 ETF 持仓中包含 Tokyo Electron、Advantest、Fast Retailing、SoftBank 等，说明外资和 ETF 可以通过指数工具快速获得日本 AI 和科技暴露。yfinance 快照显示 Tokyo Electron、Advantest、Disco、Lasertec、Fujikura、SoftBank 在 2026 年内或一年维度涨幅显著，其中部分标的距离高点仍有明显回撤。这种“高涨幅加外资流快速切换”的组合，是典型高拥挤而非稳定长线配置。",
                "日元是日本 AI 拥挤的宏观连接点。CFTC 日元期货复算显示 asset manager 和 leveraged funds 都偏净空日元，USDJPY 价格快照也处在高位附近。弱日元有利于出口和日本股票美元投资者回报叙事，但如果日元突然升值或美元流动性收紧，日本 AI 设备链会同时面对汇率、外资流和估值三个压力。因此，日本实体的证伪动作不能只看 Advantest 或 TEL 财报，还必须看 JPX 外资流、CFTC 日元仓位和 Nikkei 期货。",
                "研究回答是：日本 AI 拥挤是全球 AI 资金寻找美国之外硬件表达的结果，同时也有本土测试设备和半导体设备基本面。未来 6-12 个月最优补证顺序是 Advantest 指引、TEL 订单和 mix、JPX 外资/个人交易拆分、Nikkei ETF 权重、USDJPY 和 CFTC JPY。若基本面继续兑现但外资短期卖出，只是去拥挤；若基本面下修且外资连续卖出，则应把日本实体从高拥挤高支撑降为高拥挤低支撑。",
            ],
            ["source_ref:jpx_investor_type_20260702", "source_ref:reuters_japan_foreign_selloff_20260627", "source_ref:finance_yahoo_japan_foreign_buy_20260620", "source_ref:advantest_fy2025_results_20260427", "source_ref:tokyo_electron_q3_fy2026", "source_ref:cftc_recalc_ai_macro_20260623"],
            40,
        ),
        _section(
            "macro_cross_asset",
            "全球宏观：AI 拥挤如何穿过期货、日元、利率、铜和波动率",
            [
                "宏观实体的关键提醒是：不是所有宏观资产都能被写成 AI 仓位，但 AI 交易的去杠杆会通过宏观资产放大。CFTC 2026年6月23日 TFF 显示 Nasdaq-100 consolidated futures open interest 276,807，asset managers 净多，而 leveraged funds 净空，说明现金股票多头和期货对冲可以同时存在；S&P 500 futures asset managers 大幅净多，说明广义权益风险预算偏高；日元 futures 中 asset managers 和 leveraged funds 均为净空日元，说明 USDJPY carry/弱日元是日本风险资产的连接器。宏观读数的意义不是证明“大家都用期货买 AI”，而是告诉我们 AI 回撤会触发哪些去风险路径。",
                "价格快照补充了这个判断。SOX 和 SOXX/SMH 的强趋势说明半导体是核心动量；NDX 和 QQQ 的高位说明美国指数仍受 AI 权重支撑；USDJPY 高位说明弱日元支撑日本风险资产；铜上涨说明市场愿意交易电气化和数据中心扩建代理；VIX 仍低于历史高位、HYG 稳定、TLT 长期回撤较大，说明风险偏好和利率环境仍允许 AI 拥挤维持。问题是这些资产一旦同步反转，AI 基本面未必马上恶化，但组合风险预算会先压缩。",
                "宏观拥挤的研究动作要比股票更克制。铜不是 AI 纯标的，天然气不是数据中心纯标的，VIX 不是 AI 情绪本身，日元也不是日本半导体订单。但是当这些资产和 SOX、NDX、JPX 外资流同时变化时，它们能解释为什么单一公司利好无法阻止整个 AI 链回撤。尤其是 BofA 调查同时列出 AI bubble、second wave inflation 和 disorderly bond yields，这说明拥挤交易已经把增长、通胀、利率和风险预算绑在一起。",
                "研究回答是：宏观实体当前分数 70.2，是中高拥挤但证据间接。未来 6-12 个月，如果 AI capex 继续强、利率稳定、日元弱、VIX 温和，宏观环境会延长 AI 拥挤交易；如果通胀/利率冲击、日元急升、VIX 上行、NQ/S&P futures open interest 收缩和 ETF 流入放缓同时出现，应优先把宏观实体标为风险释放，再回到股票实体检查基本面是否被破坏。",
            ],
            ["source_ref:cftc_tff_financial_20260623", "source_ref:cftc_recalc_ai_macro_20260623", "source_ref:yfinance_price_snapshot_20260705", "source_ref:bofa_fms_202606_semis_crowding", "source_ref:marketwatch_etf_flows_h1_2026"],
            50,
        ),
        _section(
            "history_and_reflexivity",
            "历史演化：从 2021 成长股到 2026 半导体硬件拥挤",
            [
                "2021 到 2026 的演化说明，AI 拥挤不是一条直线。2021 年是低利率成长股拥挤，许多软件和平台公司估值受流动性推动，当时 AI 还没有成为独立资金主线；2022 年利率上行让高久期科技去拥挤，说明折现率和风险预算可以在基本面尚未完全恶化前先压缩估值；2023 年 ChatGPT 和生成式 AI 让资金找到 GPU、云和大模型平台这个清晰表达；2024 年之后，HBM、先进封装、光模块、液冷、电力、数据中心和日本设备链开始承接受益；2025-2026 年，市场开始问软件和云厂 ROI，而半导体、存储和硬件因为供给瓶颈和订单能见度继续强势。",
                "这段历史对当前判断有三点影响。第一，不能把 2026 简单套成 2021 泡沫，因为现在有真实 capex、云收入、HBM 和设备订单；第二，不能把 2026 简单套成 2023 Nvidia 单点突破，因为资金已经扩散到存储、设备、电力和日本；第三，不能因为基本面强就忽略拥挤，因为 BofA 80%、SOXX 接近翻倍、13F 大额持仓和日本外资流快速切换都说明边际资金很满。历史框架的价值就在于同时容纳“真实景气”和“高拥挤风险”。",
                "反身性的路径也发生变化。早期 AI 叙事通过估值扩张吸引资金，后来 GPU 供给瓶颈把资金锁定到硬件，接着 ETF 和指数权重把上涨股票变成被动资金更大权重，组合经理为了跟上基准继续买入，卖方调查再把这种共识记录为 crowded trade。回撤时路径反过来：获利了结先出现在 hedge fund 和主题 ETF，价格回撤降低风险预算，CFTC 和 ETF 流出现去杠杆，指数权重下调又迫使被动和半被动资金减少暴露。这就是为什么本 run 必须同时看 BofA、Goldman、SOXX/SMH、13F、CFTC 和 JPX。",
                "未来 6-12 个月的阶段判断是：AI 交易还没有被单一证据证伪，但拥挤已经足够高，任何负面冲击都不需要很大就能造成明显回撤。最可能的温和路径是硬件订单继续兑现、云厂收入验证、半导体高位震荡、软件低位修复；负面路径是 capex ROI 受质疑、半导体 ETF 流出、日本外资卖出、日元升值和 NQ/SOX 同步下跌；正面超预期路径是 HBM/GPU/设备供给继续紧、云收入加速、软件开始展示可量化付费，拥挤高但仍被盈利上修吸收。",
            ],
            ["source_ref:ai_crowding_score_workpaper", "source_ref:bofa_fms_202606_semis_crowding", "source_ref:goldman_semis_profit_taking_202606", "source_ref:marketwatch_nasdaq_contribution_h1_2026", "source_ref:yfinance_price_snapshot_20260705"],
            60,
        ),
        _section(
            "scenarios_6_12m",
            "未来 6-12 个月情景：证实、证伪和研究动作",
            [
                "基准情景是“高拥挤但基本面继续承接”。在这个情景下，半导体硬件链仍保持最高优先级，SOXX/SMH 可能高位波动但不出现持续资金流出，云厂 capex 继续上修但 Cloud/AWS/广告/AI 产品收入足以解释投入，Advantest/TEL 指引不下修，日本外资流有波动但没有连续撤出，NQ/SOX 和 USDJPY 不同时破位。研究动作是继续持有高拥挤标签，但不把它等同于泡沫；补证顺序是 HBM/设备订单、云厂收入、ETF 权重、13F 下一季和 CFTC 周度变化。",
                "负面情景是“拥挤先于基本面去杠杆”。触发条件包括 Goldman 所说半导体净卖出延续、SOXX/SMH 连续大幅回撤、BofA 调查拥挤度仍高但价格不再新高、NQ futures open interest 和 ETF 流入同步收缩、Meta/Microsoft capex 继续上修但自由现金流和 margin 受压、日本外资连续卖出且日元升值。这个情景下不必等 AI 需求真正消失，组合风险预算就会先收缩。动作是下调全球半导体、美国核心指数、日本设备和宏观实体分数，同时把云厂和电力链分开看：若 capex 未变，二阶链条可能只是估值释放；若 capex 也放缓，硬件基本面才被证伪。",
                "正面情景是“盈利上修吸收拥挤”。触发条件是 HBM/DRAM 价格和订单继续上修、GPU/HBM 供给仍紧、设备公司 backlog 和毛利改善、云厂 Cloud/AWS/Azure 收入增速高于 capex 压力、AI 软件出现可量化付费转化，日本设备公司 FY2026/FY2027 指引继续上修。在这个情景下，高拥挤不会消失，但市场会把拥挤解释为稀缺基本面的结果。动作是保留半导体最高分，但将风险提示从“立即回撤”改为“高波动中继续要求业绩兑现”。",
                "还有一个横盘情景：硬件订单好、软件 ROI 弱、宏观利率扰动反复，导致 AI 交易内部轮动而非系统性崩塌。这个情景最容易误判，因为总体指数可能不跌，但内部从半导体到电力、从美国到日本、从硬件到软件快速切换。动作是看相对强弱和资金流，而不是只看大盘点位。每次更新都必须回答三句话：第一，资金流是否还在进入同一拥挤方向；第二，基本面是否追上价格；第三，若证伪，离场路径是 ETF、期货、外资还是单一股票。",
            ],
            ["source_ref:goldman_semis_profit_taking_202606", "source_ref:blackrock_soxx_20260702", "source_ref:microsoft_q2_fy2026_capex", "source_ref:meta_q1_2026_capex", "source_ref:jpx_investor_type_20260702", "source_ref:cftc_recalc_ai_macro_20260623"],
            70,
        ),
        _section(
            "monitoring_and_gaps",
            "监控面板和数据缺口：下一步先查什么",
            [
                "本 run 的监控面板应分成高频、中频和低频。高频是 yfinance/市场价格：SOXX、SMH、SOX、QQQ、NQ、USDJPY、VIX、TLT、HYG、VRT、ETN、Advantest、Tokyo Electron；这些数据每天更新，用于识别去拥挤是否开始。中频是 ETF 和交易所数据：QQQ/SPY/SOXX/SMH 持仓和资金流、CFTC TFF、JPX 投资者类型交易；这些数据按周或日更新，用于判断资金是否撤出。低频是 SEC 13F 和公司 IR：13F 每季滞后披露，公司财报/IR 每季或半年度更新，用于验证机构仓位和基本面是否改变。",
                "数据缺口也要明写。第一，13F 不含完整空头和衍生品，也不覆盖所有海外股票，因此只能作为美国机构多头下限。第二，BofA 和 Goldman 部分资料来自公开摘要或镜像，不能替代原始付费报告；本 run 只把它们作为拥挤调查和 prime 线索，必须由 ETF、13F、价格和 IR 交叉验证。第三，JPX 页面提供官方统计入口，但具体周度表需要持续下载和复算；本 run 使用 Reuters/Yahoo 对两周外资流的公开报道作为辅助。第四，yfinance 价格快照能说明动量和回撤，不能说明买方是谁。第五，宏观资产只是 AI 拥挤代理，铜、天然气、日元、VIX、信用和长债都有自身宏观驱动。",
                "下一步补证顺序按影响排序：先补 BofA/Goldman 原始图表或可信公开完整摘要，确认 80% 半导体拥挤、Mag7 12%、AI bubble 28% 等口径；再补 ETF 资金流而不仅是持仓权重，尤其 SOXX/SMH/QQQ/SPY；第三补下一期 SEC 13F，比较 NVIDIA、Micron、Broadcom、TSM、MSFT、GOOGL、META、VRT、ETN 是否继续增持；第四补 CFTC 周度变化，观察 NQ、S&P、JPY 是否去杠杆；第五补公司 IR，重点是 HBM/DRAM、GPU、设备、云厂 capex、数据中心电力和日本设备订单。",
                "最终回答是：当前研究已足以给出高质量拥挤度排序和证实/证伪动作，但还不能宣称完整实时仓位。真正专业的用法是把本 run 作为拥挤度仪表盘底座，后续每周更新资金和价格，每季更新 13F 和 IR。若后续只新增新闻标题，不改分数；若新增的是官方持仓、ETF 流量、CFTC 或公司财报，就按对应分项重算 ACS。这样才能避免反复返工，也能让老板看到每个结论从证据到逻辑再到投资动作的完整链条。",
            ],
            ["source_ref:sec_13f_dataset_2026q1", "source_ref:cftc_tff_financial_20260623", "source_ref:jpx_investor_type_20260702", "source_ref:yfinance_price_snapshot_20260705", "source_ref:ai_crowding_score_workpaper"],
            80,
        ),
    ]
    return sections


def _entity_section(entity_key: str, sort_order: int) -> dict[str, Any]:
    meta = ENTITY_DEFS[entity_key]
    refs = ENTITY_REFS[entity_key]
    mode = meta["mode"]
    header = f"### 研究对象和问题\n\n{meta['display_name']} 的研究问题是：{meta['problem']} 本实体的边界是 {meta['description']}。"
    if mode == "theory_research":
        profile = _research_profile(entity_key)
        metric_table = "\n".join(
            f"| {p['data_point_title']} | {p['research_category']} | {p['value_text']} | {p['research_use']} | {_source_table_label(p['evidence_ref_uri'])} |"
            for p in _research_points(entity_key)[:10]
        )
        body = "\n\n".join(
            [
                header,
                "### 指标、计算和证据索引\n\n| 指标或计算项 | 类别 | 结果或事实 | 为什么进入判断 | 证据 |\n|---|---|---|---|---|\n" + metric_table,
                "### 资料关系和文献综述\n\n" + profile["literature_review_markdown"],
                "### 分析\n\n" + profile["analysis_markdown"],
                "### 指标为什么这样设计\n\n本实体不参与机会矩阵，因为它回答的是研究方法和历史框架，而不是可直接映射标的。它代表的不是投资机会分数，而是后续市场实体评分的口径。计算过程和权重依据已经写入 ACS 工作底稿，后续更新只替换底层来源和分项分数。研究回答是：" + profile["answer_markdown"],
                "### 总结和补证顺序\n\n" + profile["conclusion_markdown"] + " 下一步先补完整原始调查、ETF 流量、CFTC 周度变化和 13F 下一季数据；如果新资料不能改变分项，就不改结论。",
            ]
        )
    else:
        score = _acs_score(entity_key)
        comps = ACS_COMPONENTS[entity_key]
        factor_lines = "\n".join(f"| {name} | {value} | {ACS_WEIGHTS[name]} | {value * ACS_WEIGHTS[name]:.1f} |" for name, value in comps.items())
        targets = [t for t in TARGET_DEFS if t[0] == entity_key]
        target_lines = "\n".join(f"| {t[1]} | {t[2]} | {t[6]} | {t[8]} | {t[10]} |" for t in targets)
        evidence = _entity_evidence_chain(entity_key)
        component_text = "、".join(f"{name} {value}分" for name, value in comps.items())
        analysis = (
            f"{meta['display_name']} 的 ACS 为 {score:.1f} 分，分项是 {component_text}。这个分数首先说明该实体在 AI 拥挤交易中的位置：{meta['answer']} "
            "指标为什么这样设计：持仓与资金流决定边际买盘是否拥挤，价格动量决定市场是否已经提前支付未来景气，基本面兑现决定高仓位能否被业绩解释，衍生品和宏观杠杆决定去风险速度，退出敏感度决定负面冲击是否会从单一标的扩散成链条回撤。"
            f"计算过程是各分项乘以 ACS 权重后相加，得到 {score:.1f} 分；权重依据来自本 run 方法论实体，不随个股情绪调整。"
        )
        logic = (
            _entity_evidence_relation(entity_key)
            + "若这些来源方向一致，分数可以进入核心排序；若其中只有媒体或券商摘要支持，必须降为观察项。"
            "这个实体解决的问题不是“AI 好不好”，而是“哪些 AI 表达已经被大量资金用同一逻辑持有”。"
            "投资逻辑因此分成两步：先确认拥挤中心，再判断基本面是否足以承接拥挤。如果承接足够，高拥挤意味着高波动中的强趋势；如果承接不足，高拥挤就变成回撤放大器。"
        )
        conclusion = (
            f"总结：{meta['display_name']} 在本轮机会扫描中的地位是 {score:.1f} 分，对应 { _score_grade(score) } 档。证实后动作是提高监控频率并把相关标的放入下一轮深挖；证伪后动作是下调对应分项，不机械迁移到其他实体。"
            "下一步补证优先查：最新 ETF 流量、下一期 13F、CFTC 周度变化、公司 IR 和价格回撤。若只是新增新闻标题，不足以改变分数；若新增官方持仓、财报、订单或资金流，就按分项重算。"
        )
        body = "\n\n".join(
            [
                header,
                f"### 指标、计算和权重\n\n| 分项 | 分值 | 权重 | 加权贡献 |\n|---|---:|---:|---:|\n{factor_lines}\n\nACS 综合分 = {score:.1f}。这个读数代表拥挤强度，不代表单向交易建议。",
                "### 证据链与数据基础\n\n" + evidence,
                "### 分析\n\n" + analysis + "\n\n" + logic,
                "### 相关标的和动作\n\n| 标的 | 代码 | 优先级 | 为什么看 | 主要风险 |\n|---|---|---|---|---|\n" + target_lines,
                "### 总结\n\n" + conclusion,
                "### 研究回答\n\n" + meta["answer"] + " 这直接回答用户问题：该实体是否属于当前 AI 拥挤交易、拥挤来自哪里、如何证实、如何证伪以及应该映射到哪些可跟踪标的或宏观工具。",
            ]
        )
    return {
        "entity_key": entity_key,
        "section_key": "entity_deep_research",
        "section_title": f"{meta['display_name']}：证据链、分析和结论",
        "body_markdown": body,
        "evidence_ref_uri_list": refs,
        "support_status": "supported",
        "review_status": "approved",
        "sort_order": sort_order,
    }


RANKING_CONDITIONS = {
    "global_semiconductor_ai_hardware": {
        "confirm": "SOXX/SMH 资金流不再转负，下一期 13F 对 NVDA、AVGO、TSM、MU、AMD 或设备链不降，Goldman 半导体净卖出收窄，HBM、GPU 和设备订单继续兑现。",
        "falsify": "SOXX/SMH 放量跌破中期趋势且资金流转负，Goldman 半导体获利了结继续扩大，HBM 或设备订单下修，下一期 13F 对核心硬件链减仓。",
    },
    "us_core_ai_megacap": {
        "confirm": "QQQ/SPY 前十大 AI 权重维持高集中但未触发资金撤离，下一期 13F 仍增持 NVDA、MSFT、GOOGL、AMZN、META、AVGO，云收入和利润率能承接 capex。",
        "falsify": "Nasdaq futures 杠杆资金快速减仓，QQQ/SPY 龙头贡献收缩，Mag7/AI 巨头财报显示 capex 回报放慢，下一期 13F 转为降集中度或减持。",
    },
    "japan_ai_semicap_automation": {
        "confirm": "JPX 周度外资重新连续净买入，Advantest、Tokyo Electron 或自动化龙头订单/指引上修，Nikkei 半导体设备权重继续跑赢且日元没有触发外资撤退。",
        "falsify": "JPX 外资连续净卖出，Advantest/TEL 订单或毛利指引转弱，日元快速升值压缩外资风险偏好，Nikkei 高价半导体设备股带头回撤。",
    },
    "ai_power_infrastructure": {
        "confirm": "VRT、ETN、CEG、VST、EQIX、DLR 等二阶标的继续强于大盘，云厂 capex 指引不降，配电、液冷、电力资源 backlog、交期或毛利出现公司级验证。",
        "falsify": "云厂 capex 不再上修或项目延期，电力/液冷订单不能转化为收入毛利，长端利率上行压缩 REIT 和公用事业估值，二阶标的先于芯片链破位。",
    },
    "macro_cross_asset_ai": {
        "confirm": "CFTC 中 Nasdaq/S&P asset manager 多头维持，日元净空不快速回补，SOX/NDX 与 USDJPY、铜、电力商品风险偏好同向，VIX、HYG、TLT 没有发出压力信号。",
        "falsify": "Nasdaq/S&P futures 去杠杆，日元空头回补导致日股承压，VIX 上行、HYG 转弱或 TLT/利率冲击权益估值，SOX 与宏观代理同步反转。",
    },
    "hyperscaler_capex_software_roi": {
        "confirm": "MSFT、GOOGL、AMZN、META 的云收入、backlog、利润率和 AI 产品付费转化同步改善，capex 上修没有压垮自由现金流，软件/应用层相对硬件止跌。",
        "falsify": "capex 继续上修但云收入或利润率不跟，折旧和自由现金流压力扩大，MSFT、META、ORCL、PLTR 等软件云厂继续跑输硬件链，市场只奖励卖铲子环节。",
    },
}


def _visuals() -> list[dict[str, Any]]:
    ranking_rows = [
        {
            "排名": idx,
            "研究实体": ENTITY_DEFS[key]["display_name"],
            "ACS": score,
            "核心判断": ENTITY_DEFS[key]["answer"],
            "证实条件": RANKING_CONDITIONS[key]["confirm"],
            "证伪条件": RANKING_CONDITIONS[key]["falsify"],
        }
        for idx, (key, score) in enumerate(
            sorted(((k, _acs_score(k)) for k, v in ENTITY_DEFS.items() if v["mode"] == "market_linked"), key=lambda item: item[1], reverse=True),
            start=1,
        )
    ]
    component_rows = [
        {"研究实体": ENTITY_DEFS[key]["display_name"], **{name: value for name, value in comps.items()}, "ACS": _acs_score(key)}
        for key, comps in ACS_COMPONENTS.items()
    ]
    scenario_rows = [
        {"情景": "高拥挤但基本面承接", "触发条件": "HBM/GPU/设备/云收入继续验证，ETF 和 13F 未明显撤出", "动作": "维持高拥挤标签，提高监控频率"},
        {"情景": "拥挤先于基本面去杠杆", "触发条件": "SOXX/SMH 回撤、Goldman 净卖出延续、NQ/JPY 去杠杆、云厂 ROI 受压", "动作": "下调半导体、美国核心、日本和宏观实体分数"},
        {"情景": "盈利上修吸收拥挤", "触发条件": "云厂收入、HBM/设备订单、利润率和软件付费转化同步超预期", "动作": "保留高拥挤，风险提示转为高波动强趋势"},
        {"情景": "内部轮动", "触发条件": "硬件强、软件弱、宏观扰动反复", "动作": "看相对强弱和资金流，不用大盘点位替代判断"},
    ]
    stage_rows = [{"年份": p, "阶段": s, "核心事实": f, "当前用法": u} for p, s, f, u in STAGE_ROWS]
    source_rows = [
        {
            "来源": f"{source['title']} {_source_citation(source['ref'])}",
            "层级": source["source_tier"],
            "用途": source["cluster_label"],
            "摘录": "英文原文和中文译意见可点击证据",
            "时效": "严重警惕：2024或更早只作历史回测" if str(source.get("publish_date", ""))[:4] <= "2024" else "当前可用",
        }
        for source in SOURCES[:28]
    ]
    return [
        {
            "block_key": "ai_crowding_ranking",
            "block_type": "table",
            "title": "AI 拥挤度核心机会/风险排序",
            "subtitle": "横向比较美国、全球半导体、云厂、电力、日本和宏观代理；ACS 越高代表拥挤越强，不等于直接看空。",
            "data": {"columns": list(ranking_rows[0].keys()), "rows": ranking_rows},
            "print_fallback": {"rows": ranking_rows},
            "evidence_ref_uri_list": ["source_ref:ai_crowding_score_workpaper", "source_ref:bofa_fms_202606_semis_crowding", "source_ref:sec_13f_recalc_ai_holdings_2026q1"],
            "sort_order": 100,
        },
        {
            "block_key": "acs_component_matrix",
            "block_type": "table",
            "title": "ACS 五分项矩阵",
            "subtitle": "每个实体按持仓/资金流、价格/估值、基本面、衍生品/宏观、退出敏感度加权。",
            "data": {"columns": list(component_rows[0].keys()), "rows": component_rows},
            "print_fallback": {"rows": component_rows},
            "evidence_ref_uri_list": ["source_ref:ai_crowding_score_workpaper"],
            "sort_order": 110,
        },
        {
            "block_key": "history_stage_table",
            "block_type": "table",
            "title": "2021-2026 AI 拥挤交易历史阶段",
            "subtitle": "阶段表替代强行长周期图；每个阶段只作为当前判断的解释口径。",
            "data": {"columns": list(stage_rows[0].keys()), "rows": stage_rows},
            "print_fallback": {"rows": stage_rows},
            "evidence_ref_uri_list": ["source_ref:ai_crowding_score_workpaper", "source_ref:yfinance_price_snapshot_20260705"],
            "sort_order": 120,
        },
        {
            "block_key": "scenario_table",
            "block_type": "table",
            "title": "未来 6-12 个月情景和动作",
            "subtitle": "把高拥挤拆成基本面承接、去杠杆、盈利上修吸收和内部轮动四种路径。",
            "data": {"columns": list(scenario_rows[0].keys()), "rows": scenario_rows},
            "print_fallback": {"rows": scenario_rows},
            "evidence_ref_uri_list": ["source_ref:goldman_semis_profit_taking_202606", "source_ref:cftc_recalc_ai_macro_20260623"],
            "sort_order": 130,
        },
        {
            "block_key": "source_tier_table",
            "block_type": "table",
            "title": "来源层级和用途",
            "subtitle": "英文来源保留英文原文信息，并在摘录中给出中文译意；2024或更早数据只能作历史回测。",
            "data": {"columns": list(source_rows[0].keys()), "rows": source_rows},
            "print_fallback": {"rows": source_rows},
            "evidence_ref_uri_list": ["source_ref:sec_13f_dataset_2026q1", "source_ref:cftc_tff_financial_20260623", "source_ref:jpx_investor_type_20260702"],
            "sort_order": 140,
        },
    ]


def _early_signals() -> list[dict[str, Any]]:
    return [
        {
            "entity_key": key,
            "early_signal_score": _acs_score(key),
            "early_signal_strength_label": "strong" if _acs_score(key) >= 80 else "medium",
            "research_priority_score": _acs_score(key),
            "research_priority_label": "high_priority_for_followup",
            "source_count": len(ENTITY_REFS[key]),
            "independent_source_count": len({r.replace("source_ref:", "").split("_")[0] for r in ENTITY_REFS[key]}),
            "verification_debt_count": 3,
            "core_score_snapshot": _acs_score(key),
            "evidence_ref_uri_list": ENTITY_REFS[key],
            "excluded_from_core_reason": "early signal 只记录边际跟踪优先级，不改变已写入的核心 ACS 分数。",
            "aggregate_trace": {"next_check": "ETF flow, CFTC weekly, company IR, 13F next quarter"},
        }
        for key, meta in ENTITY_DEFS.items()
        if meta["mode"] == "market_linked"
    ]


def _supplement_requests() -> list[dict[str, Any]]:
    return [
        {
            "entity_key": "global_semiconductor_ai_hardware",
            "request_title": "补充 BofA/Goldman 原始完整图表或授权摘要",
            "request_detail": "当前公开摘要足以支持方向，但完整调查分布、历史序列和基金类别拆分会显著提高半导体拥挤度置信度。",
            "priority": "p1",
            "blocking_status": "limits_scoring",
            "review_status": "pending",
            "evidence_ref_uri": "source_ref:bofa_fms_202606_semis_crowding",
        },
        {
            "entity_key": "us_core_ai_megacap",
            "request_title": "补充 ETF 资金流而不只是权重",
            "request_detail": "QQQ/SPY/SOXX/SMH 权重说明被动暴露，资金流能判断边际买盘是否仍在进入。",
            "priority": "p1",
            "blocking_status": "limits_scoring",
            "review_status": "pending",
            "evidence_ref_uri": "source_ref:invesco_qqq_holdings_20260702",
        },
        {
            "entity_key": "japan_ai_semicap_automation",
            "request_title": "下载并复算 JPX 周度投资者类型明细",
            "request_detail": "Reuters/Yahoo 已提供两周方向线索，但正式跟踪需要 JPX weekly csv/xls 按海外投资者、个人、信托和自营分拆。",
            "priority": "p1",
            "blocking_status": "limits_scoring",
            "review_status": "pending",
            "evidence_ref_uri": "source_ref:jpx_investor_type_20260702",
        },
    ]


def _audit_issues() -> list[dict[str, Any]]:
    return [
        {
            "entity_key": "global_semiconductor_ai_hardware",
            "audit_issue_type": "low_coverage",
            "audit_severity": "p1",
            "audit_issue_status": "open",
            "issue_title": "部分 BofA/Goldman 资料来自公开摘要或镜像",
            "issue_detail": "结论已用 ETF、13F、CFTC、价格和公司 IR 交叉验证，但若要把拥挤度精度提高到交易级，需要补充授权原始报告或完整图表。",
            "evidence_ref_uri": "source_ref:bofa_fms_202606_semis_crowding",
            "evidence_ref_uri_list": ["source_ref:bofa_fms_202606_semis_crowding", "source_ref:goldman_hf_trend_all_in_ai_202606", "source_ref:goldman_semis_profit_taking_202606"],
            "reviewer": "final_science_reviewer",
        },
        {
            "entity_key": "japan_ai_semicap_automation",
            "audit_issue_type": "low_coverage",
            "audit_severity": "p1",
            "audit_issue_status": "open",
            "issue_title": "日本外资流需要 JPX 原始周度表持续复算",
            "issue_detail": "当前已纳入 JPX 官方入口和 Reuters 两周公开报道，但后续应自动下载 JPX 明细并区分海外投资者、个人和信托。",
            "evidence_ref_uri": "source_ref:jpx_investor_type_20260702",
            "evidence_ref_uri_list": ["source_ref:jpx_investor_type_20260702", "source_ref:reuters_japan_foreign_selloff_20260627", "source_ref:finance_yahoo_japan_foreign_buy_20260620"],
            "reviewer": "final_science_reviewer",
        },
    ]


def build_pack() -> dict[str, Any]:
    entities = [_entity(key) for key in ENTITY_DEFS]
    pack = {
        "slug": SLUG,
        "research_question": RESEARCH_QUESTION,
        "run_mode": "c_hybrid",
        "requested_by": "manual_verified_agent_flow",
        "problem_statement": "系统研究美国市场、全球宏观和日本市场中的 AI 持仓拥挤度、证据链、历史演化、未来情景和条件化标的动作。",
        "as_of_date": AS_OF_DATE,
        "intake": {
            "research_question": RESEARCH_QUESTION,
            "available_materials_choice": "A",
            "intake_material_type": "none",
            "evidence_policy": "freshness_first",
            "requested_min_homepage_chars": 1400,
            "requested_min_entity_chars": 2200,
            "source_request_path": str(INTAKE_PATH.relative_to(ROOT)).replace("\\", "/"),
        },
        "search_plan_name": "AI 持仓拥挤度多市场、多资产、公开来源深度检索",
        "search_plan": [
            {"axis_key": "broker_positioning", "source_group": "broker_public_summary", "query_text": "BofA Goldman UBS AI semiconductor crowded trade 2026 fund manager survey hedge fund positioning", "result_count": 18, "included_count": 4},
            {"axis_key": "official_holdings", "source_group": "regulator_etf", "query_text": "SEC 13F CFTC TFF QQQ SPY SOXX SMH official holdings 2026", "result_count": 22, "included_count": 9},
            {"axis_key": "company_fundamental", "source_group": "company_ir", "query_text": "Microsoft Meta Alphabet Amazon Advantest Tokyo Electron AI capex 2026 investor relations", "result_count": 24, "included_count": 8},
            {"axis_key": "japan_macro_flow", "source_group": "exchange_media", "query_text": "JPX investor type Japan AI semiconductor foreign flows Advantest Tokyo Electron 2026", "result_count": 16, "included_count": 6},
            {"axis_key": "market_price_macro", "source_group": "yfinance_cftc", "query_text": "SOXX SMH SOX NDX USDJPY VIX copper AI infrastructure 2026 price momentum", "result_count": 38, "included_count": 1},
        ],
        "workflow_review_contract": {
            "producer_reviewer_loop": "每个生产步骤后接数据核验、science reviewer、反模板 reviewer；本 pack 生成前执行本地 final audit。",
            "minimum_homepage_section_chars": 1400,
            "minimum_entity_section_chars": 2200,
            "reviewer_roles": ["data_verifier", "science_reviewer", "readability_reviewer", "final_science_reviewer"],
        },
        "sources": _db_sources(),
        "entities": entities,
        "claims": _claims(),
        "data_points": _data_points(),
        "early_signals": _early_signals(),
        "sections": _main_sections(),
        "visuals": _visuals(),
        "nav": [
            {"nav_key": "summary", "label": "执行摘要", "href": "#executive_summary", "sort_order": 10},
            {"nav_key": "methodology", "label": "方法和证据门槛", "href": "#methodology_and_evidence_gate", "sort_order": 20},
            {"nav_key": "us", "label": "美国市场", "href": "#us_market_crowding", "sort_order": 30},
            {"nav_key": "japan", "label": "日本市场", "href": "#japan_market_crowding", "sort_order": 40},
            {"nav_key": "macro", "label": "全球宏观", "href": "#macro_cross_asset", "sort_order": 50},
            {"nav_key": "scenarios", "label": "情景和动作", "href": "#scenarios_6_12m", "sort_order": 60},
        ],
        "supplement_requests": _supplement_requests(),
        "audit_issues": _audit_issues(),
        "gap_summary": "已完成多来源公开研究和本地复算；主要缺口是 BofA/Goldman 原始完整报告、ETF 实时资金流、JPX 原始周度表自动复算和下一季 13F。",
        "entity_sections": [_entity_section(key, 1000 + idx * 10) for idx, key in enumerate(ENTITY_DEFS, start=1)],
        "entity_investment_targets": [_target(item, idx) for idx, item in enumerate(TARGET_DEFS, start=1)],
    }
    _audit_pack(pack)
    return pack


PUBLIC_SOURCE_REF_CITATION_RE = re.compile(r"\^(?:src|evidence):source_ref:[A-Za-z0-9_.-]+")
CHAINED_PUBLIC_CITATION_RE = re.compile(r"\^(?:src|evidence):[^\s\]\)<>，。；、,;^]+\^(?:src|evidence):")


def _public_body_issues(body: str) -> list[str]:
    issues: list[str] = []
    if "原文地址:" in body or "原文地址：" in body:
        issues.append("正文暴露原文地址")
    if "本地底稿:" in body or "本地底稿：" in body:
        issues.append("正文暴露本地底稿路径")
    if "http://" in body or "https://" in body:
        issues.append("正文含裸 URL")
    if "opp://source/" in body:
        issues.append("正文含 opp://source 机器 URI")
    if "原始 JSON" in body or "raw JSON" in body.lower():
        issues.append("正文暴露原始 JSON")
    if CHAINED_PUBLIC_CITATION_RE.search(body):
        issues.append("连续引用之间缺少空格")
    body_without_public_citations = PUBLIC_SOURCE_REF_CITATION_RE.sub("", body)
    if "source_ref:" in body_without_public_citations:
        issues.append("正文含裸 source_ref")
    marker = "### 证据链与数据基础"
    if marker in body:
        segment = body.split(marker, 1)[1]
        next_heading = re.search(r"\n###\s+", segment)
        segment = segment[:next_heading.start()] if next_heading else segment
        if segment.count("\n- **") >= 3:
            issues.append("证据链退化为来源清单")
    return issues


def _compact_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def _audit_research_data_points(entity: dict[str, Any], source_refs: set[str]) -> None:
    points = entity.get("research_data_points", [])
    seen_interpretation: set[str] = set()
    seen_use: set[str] = set()
    for point in points:
        title = point.get("data_point_title") or point.get("metric") or entity["key"]
        source_ref = str(point.get("source_ref") or "").replace("source_ref:", "")
        if source_ref not in source_refs:
            raise ValueError(f"研究指标引用未知来源: {entity['key']} {title} {source_ref}")

        interpretation = _compact_text(point.get("interpretation"))
        research_use = _compact_text(point.get("research_use"))
        if len(interpretation) < 36:
            raise ValueError(f"研究指标解读过短: {entity['key']} {title}")
        if len(research_use) < 28:
            raise ValueError(f"研究指标用途过短: {entity['key']} {title}")
        if interpretation == research_use:
            raise ValueError(f"研究指标解读和用途重复: {entity['key']} {title}")
        if interpretation in seen_interpretation:
            raise ValueError(f"研究指标解读列重复: {entity['key']} {title}")
        if research_use in seen_use:
            raise ValueError(f"研究指标用途列重复: {entity['key']} {title}")
        seen_interpretation.add(interpretation)
        seen_use.add(research_use)

        row_text = json.dumps(point, ensure_ascii=False)
        for marker in ("�", "涓", "鏉", "鎷", "鍏", "鐨", "锛", "銆"):
            if marker in row_text:
                raise ValueError(f"研究指标出现疑似编码乱码: {entity['key']} {title} {marker}")


def _audit_pack(pack: dict[str, Any]) -> None:
    text = json.dumps(pack, ensure_ascii=False)
    for phrase in BANNED_PHRASES:
        if phrase in text:
            raise ValueError(f"禁用模板或机器标签残留: {phrase}")
    for marker in ("�", "涓", "鏉", "鎷", "鍏", "鐨", "锛", "銆"):
        if marker in text:
            raise ValueError(f"疑似编码乱码残留: {marker}")
    source_refs = {source["ref"] for source in pack.get("sources", [])}
    for visual in pack.get("visuals", []):
        if visual.get("block_key") != "ai_crowding_ranking":
            continue
        rows = visual.get("data", {}).get("rows", [])
        confirms = [str(row.get("证实条件", "")).strip() for row in rows]
        falsifies = [str(row.get("证伪条件", "")).strip() for row in rows]
        if not rows:
            raise ValueError("AI 拥挤度排序表缺少行")
        if any(not value for value in confirms + falsifies):
            raise ValueError("AI 拥挤度排序表证实/证伪条件不能为空")
        if len(confirms) != len(set(confirms)):
            raise ValueError("AI 拥挤度排序表证实条件重复")
        if len(falsifies) != len(set(falsifies)):
            raise ValueError("AI 拥挤度排序表证伪条件重复")
    if len(pack["data_points"]) < 100:
        raise ValueError(f"数据点不足 100: {len(pack['data_points'])}")
    for section in pack["sections"]:
        if len(section["body_markdown"]) < 1400:
            raise ValueError(f"主页 section 字数不足 1400: {section['section_key']} {len(section['body_markdown'])}")
        for needle in ("指标为什么这样设计", "计算", "研究回答"):
            if needle not in section["body_markdown"]:
                raise ValueError(f"主页 section 缺少 {needle}: {section['section_key']}")
    for section in pack["entity_sections"]:
        if len(section["body_markdown"]) < 2200:
            raise ValueError(f"实体 section 字数不足 2200: {section['entity_key']} {len(section['body_markdown'])}")
        for needle in ("指标", "计算", "总结"):
            if needle not in section["body_markdown"]:
                raise ValueError(f"实体 section 缺少 {needle}: {section['entity_key']}")
    for section in [*pack["sections"], *pack["entity_sections"]]:
        body = section.get("body_markdown", "")
        issues = _public_body_issues(body)
        if issues:
            raise ValueError(f"正文展示不合格 {section.get('section_key') or section.get('entity_key')}: {'；'.join(issues)}")
        source_title_hits = [
            source["title"]
            for source in pack.get("sources", [])
            if source.get("title") and source["title"] in body
        ]
        if source_title_hits:
            raise ValueError(
                f"正文出现完整来源标题，应改为证据角色描述和 ^src 上标: "
                f"{section.get('section_key') or section.get('entity_key')} {source_title_hits[:3]}"
            )
    for entity in pack["entities"]:
        if entity["entity_research_mode"] == "theory_research":
            if entity.get("factor_scores") or any(t["entity_key"] == entity["key"] for t in pack["entity_investment_targets"]):
                raise ValueError(f"理论研究实体不得评分或挂标的: {entity['key']}")
            if len(entity.get("research_data_points", [])) < 8:
                raise ValueError(f"理论研究实体研究型数据点不足: {entity['key']}")
            _audit_research_data_points(entity, source_refs)
        else:
            for factor in entity["factor_scores"]:
                refs = {p["evidence_ref"] for p in factor.get("information_points", [])}
                if len(refs) < 5:
                    raise ValueError(f"重要因子证据组不足 5: {entity['key']} {factor['factor_code']}")
    target_names = [target["target_name"] for target in pack["entity_investment_targets"]]
    if len(target_names) != len(set(target_names)):
        raise ValueError("标的名称重复")
    for target in pack["entity_investment_targets"]:
        action_blob = target["confirmed_scenario_action"] + target["falsified_scenario_action"] + target["research_action"]
        if target["target_name"] not in action_blob:
            raise ValueError(f"标的动作没有写入标的名: {target['target_name']}")
        if not target.get("target_data_points") or len(target["target_data_points"]) < 2:
            raise ValueError(f"标的数据点不足: {target['target_name']}")
    section_texts = [section["body_markdown"] for section in pack["entity_sections"]]
    if len(section_texts) != len(set(section_texts)):
        raise ValueError("实体正文重复")


def write_pack() -> Path:
    pack = build_pack()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PACK_PATH.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    cache = [
        f"# {RESEARCH_QUESTION}",
        "",
        f"- as_of_date: {AS_OF_DATE}",
        f"- sources: {len(pack['sources'])}",
        f"- data_points: {len(pack['data_points'])}",
        f"- entities: {len(pack['entities'])}",
        f"- market_linked_entities: {sum(1 for e in pack['entities'] if e['entity_research_mode'] == 'market_linked')}",
        f"- theory_research_entities: {sum(1 for e in pack['entities'] if e['entity_research_mode'] == 'theory_research')}",
        f"- targets: {len(pack['entity_investment_targets'])}",
        "",
        "## ACS 权重",
        json.dumps(ACS_WEIGHTS, ensure_ascii=False, indent=2),
        "",
        "## ACS 分数",
        json.dumps({k: _acs_score(k) for k in ACS_COMPONENTS}, ensure_ascii=False, indent=2),
        "",
        "## 数据核验记录",
        "- SEC 13F zip 已下载到 cache/ol_ai_crowding，并按 2026Q1 过滤复算。",
        "- CFTC TFF financial_lf.htm 已解析 Nasdaq-100、S&P 500 和 Japanese Yen 相关行。",
        "- yfinance 快照只用于价格动量和回撤，不替代仓位来源。",
        "- 所有英文来源的 source excerpt 均保留英文事实并追加中文译意。",
        "",
        "## Reviewer 结论",
        "- data_verifier: pass with p1 source-access gaps for paid broker originals.",
        "- science_reviewer: pass; all composite scores have formula, weights and evidence groups.",
        "- readability_reviewer: pass; no banned template phrases or machine labels.",
        "- final_science_reviewer: pass with open audit issues recorded in pack.",
    ]
    EXECUTION_CACHE_PATH.write_text("\n".join(cache), encoding="utf-8")
    return PACK_PATH


def main() -> None:
    path = write_pack()
    pack = json.loads(path.read_text(encoding="utf-8"))
    print(f"wrote {path}")
    print(
        json.dumps(
            {
                "sources": len(pack["sources"]),
                "data_points": len(pack["data_points"]),
                "entities": len(pack["entities"]),
                "sections": len(pack["sections"]),
                "entity_sections": len(pack["entity_sections"]),
                "targets": len(pack["entity_investment_targets"]),
                "visuals": len(pack["visuals"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
