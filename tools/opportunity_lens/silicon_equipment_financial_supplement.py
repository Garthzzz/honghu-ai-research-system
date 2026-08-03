from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from tools.opportunity_lens.silicon_run_pack_support import source_uri


"""设备侧七个上市标的的合规财务补充。

年度序列仅来自项目允许的 Tushare/yfinance。A 股年度值于 2026-07-20
通过 ``company_financial_series_utils.fetch_company_financial_series`` 只读取得；
首批三个标的当前估值复用 ``cache/company_financial_fetch_final_20260715_v2.json``。
PVA TePla、东京精密、晶盛机电和 KLA 于 2026-07-20 通过项目受控入口只读刷新，
市场日统一为 2026-07-17。本模块不连接或写入 live DB，固定值与本文件哈希一起
进入研究包，避免运行时悄然漂移。
"""


FINANCIAL_SUPPLEMENT_SOURCES: tuple[dict[str, Any], ...] = (
    {
        "source_id": "FIN-EQ-JS-ANNUAL",
        "publisher": "Tushare Pro",
        "title": "Tushare财务报表快照：晶升股份（688478.SH）",
        "title_zh": "Tushare财务报表快照：晶升股份（688478.SH）",
        "date": "2026-07-20",
        "original_url_or_locator": "https://tushare.pro/document/2?doc_id=33",
        "local_locator": "只读API记录：ts_code=688478.SH；income、fina_indicator、cashflow；end_date=20231231、20241231、20251231；抓取日2026-07-20。",
        "language": "zh",
        "tier": "approved_financial_database",
        "independence_key": "provider:tushare:688478.SH",
        "independence_rationale": "同一发行人的Tushare损益、财务指标和现金流快照合并为一个证据组。",
        "excerpt": (
            "Tushare income/fina_indicator/cashflow：晶升股份2023年收入4.06亿元、归母净利润0.71亿元、"
            "毛利率33.46%、经营现金流-0.92亿元、资本开支0.76亿元；2024年收入4.25亿元、归母净利润0.54亿元、"
            "毛利率26.07%、经营现金流0.03亿元、资本开支0.95亿元；2025年收入1.16亿元、归母净利润-0.38亿元、"
            "毛利率15.03%、经营现金流-0.51亿元、资本开支0.68亿元。"
        ),
        "excerpt_zh": (
            "Tushare income/fina_indicator/cashflow：晶升股份2023年收入4.06亿元、归母净利润0.71亿元、"
            "毛利率33.46%、经营现金流-0.92亿元、资本开支0.76亿元；2024年收入4.25亿元、归母净利润0.54亿元、"
            "毛利率26.07%、经营现金流0.03亿元、资本开支0.95亿元；2025年收入1.16亿元、归母净利润-0.38亿元、"
            "毛利率15.03%、经营现金流-0.51亿元、资本开支0.68亿元。"
        ),
    },
    {
        "source_id": "FIN-EQ-JS-MARKET",
        "publisher": "Tushare Pro",
        "title": "Tushare估值与财务指标快照：晶升股份（688478.SH）",
        "title_zh": "Tushare估值与财务指标快照：晶升股份（688478.SH）",
        "date": "2026-07-14",
        "original_url_or_locator": "https://tushare.pro/document/2?doc_id=32",
        "local_locator": "只读API记录：ts_code=688478.SH；daily_basic trade_date=20260714；fina_indicator end_date=20260331；抓取日2026-07-20。",
        "language": "zh",
        "tier": "approved_financial_database",
        "independence_key": "provider:tushare:688478.SH",
        "independence_rationale": "与年度报表属于同一Tushare发行人数据组，不重复计作独立确认。",
        "excerpt": (
            "Tushare快照：晶升股份2026-07-14总市值85.16亿元、PB 5.68倍、PS_TTM 178.42倍；"
            "最近财务指标截至2026-03-31，ROE -0.58%、ROA -0.65%、BPS 10.83元。"
            "亏损口径下PE_TTM与EPS_TTM未返回可展示值，不能写成0。"
        ),
        "excerpt_zh": (
            "Tushare快照：晶升股份2026-07-14总市值85.16亿元、PB 5.68倍、PS_TTM 178.42倍；"
            "最近财务指标截至2026-03-31，ROE -0.58%、ROA -0.65%、BPS 10.83元。"
            "亏损口径下PE_TTM与EPS_TTM未返回可展示值，不能写成0。"
        ),
    },
    {
        "source_id": "FIN-EQ-AMAT-ANNUAL",
        "publisher": "Yahoo Finance / yfinance",
        "title": "yfinance annual income statement snapshot for Applied Materials (AMAT)",
        "title_zh": "yfinance年度损益快照：Applied Materials（AMAT）",
        "date": "2026-07-20",
        "original_url_or_locator": "https://finance.yahoo.com/quote/AMAT/financials/",
        "local_locator": "只读接口记录：yfinance Ticker('AMAT').income_stmt与cashflow；FY2022—FY2025列；抓取日2026-07-20。",
        "language": "en",
        "tier": "approved_financial_database",
        "independence_key": "provider:yfinance:AMAT",
        "independence_rationale": "同一发行人的yfinance年度报表与当前估值合并为一个证据组。",
        "excerpt": (
            "yfinance income_stmt for AMAT: FY2022 revenue/net income USD 25.785/6.525 billion; "
            "operating cash flow/capex USD 5.399/0.787 billion and gross margin 46.51%; FY2023 "
            "revenue/net income/operating cash flow/capex USD 26.517/6.856/8.700/1.106 billion and gross margin 46.70%; "
            "FY2024 USD 27.176/7.177/8.677/1.190 billion and gross margin 47.46%; "
            "FY2025 USD 28.368/6.998/7.958/2.260 billion and gross margin 48.67%."
        ),
        "excerpt_zh": (
            "yfinance损益表及现金流量表：Applied Materials 2022财年收入/净利润/经营现金流/资本开支为"
            "257.85/65.25/53.99/7.87亿美元，毛利率46.51%；2023财年为265.17/68.56/87.00/11.06亿美元，"
            "毛利率46.70%；2024财年为271.76/71.77/86.77/11.90亿美元，毛利率47.46%；"
            "2025财年为283.68/69.98/79.58/22.60亿美元，毛利率48.67%。"
        ),
    },
    {
        "source_id": "FIN-EQ-AMAT-MARKET",
        "publisher": "Yahoo Finance / yfinance",
        "title": "yfinance valuation and financial-metric snapshot for Applied Materials (AMAT)",
        "title_zh": "yfinance估值与财务指标快照：Applied Materials（AMAT）",
        "date": "2026-07-14",
        "original_url_or_locator": "https://finance.yahoo.com/quote/AMAT/",
        "local_locator": "只读接口记录：yfinance Ticker('AMAT').get_info()；market snapshot 2026-07-14；抓取日2026-07-20。",
        "language": "en",
        "tier": "approved_financial_database",
        "independence_key": "provider:yfinance:AMAT",
        "independence_rationale": "与年度报表属于同一yfinance发行人数据组，不重复计作独立确认。",
        "excerpt": (
            "yfinance snapshot for AMAT on 2026-07-14: market cap CNY 3200.295 billion "
            "(USD 472.962 billion), trailing PE 54.06, forward PE 35.58, price-to-book 19.78; "
            "price-to-sales was not returned by the interface; latest metrics ROE 39.69%, ROA 14.86%, "
            "trailing EPS USD 11.02 and book value per share USD 30.11."
        ),
        "excerpt_zh": (
            "yfinance快照：Applied Materials在2026-07-14总市值32,002.95亿元人民币（约4,729.62亿美元），"
            "PE_TTM 54.06倍、前瞻PE 35.58倍、PB 19.78倍，PS_TTM接口未返回；最近财务指标ROE 39.69%、ROA 14.86%、"
            "EPS_TTM 11.02美元、BPS 30.11美元。"
        ),
    },
    {
        "source_id": "FIN-EQ-HUHAI-ANNUAL",
        "publisher": "Tushare Pro",
        "title": "Tushare财务报表快照：华海清科（688120.SH）",
        "title_zh": "Tushare财务报表快照：华海清科（688120.SH）",
        "date": "2026-07-20",
        "original_url_or_locator": "https://tushare.pro/document/2?doc_id=33",
        "local_locator": "只读API记录：ts_code=688120.SH；income、fina_indicator、cashflow；end_date=20231231、20241231、20251231；抓取日2026-07-20。",
        "language": "zh",
        "tier": "approved_financial_database",
        "independence_key": "provider:tushare:688120.SH",
        "independence_rationale": "同一发行人的Tushare损益、财务指标和现金流快照合并为一个证据组。",
        "excerpt": (
            "Tushare income/fina_indicator/cashflow：华海清科2023年收入25.08亿元、归母净利润7.24亿元、"
            "毛利率46.02%、经营现金流6.53亿元、资本开支3.40亿元；2024年收入34.06亿元、归母净利润10.23亿元、"
            "毛利率43.20%、经营现金流11.55亿元、资本开支3.22亿元；2025年收入46.48亿元、归母净利润10.84亿元、"
            "毛利率41.81%、经营现金流8.00亿元、资本开支2.22亿元。"
        ),
        "excerpt_zh": (
            "Tushare income/fina_indicator/cashflow：华海清科2023年收入25.08亿元、归母净利润7.24亿元、"
            "毛利率46.02%、经营现金流6.53亿元、资本开支3.40亿元；2024年收入34.06亿元、归母净利润10.23亿元、"
            "毛利率43.20%、经营现金流11.55亿元、资本开支3.22亿元；2025年收入46.48亿元、归母净利润10.84亿元、"
            "毛利率41.81%、经营现金流8.00亿元、资本开支2.22亿元。"
        ),
    },
    {
        "source_id": "FIN-EQ-HUHAI-MARKET",
        "publisher": "Tushare Pro",
        "title": "Tushare估值与财务指标快照：华海清科（688120.SH）",
        "title_zh": "Tushare估值与财务指标快照：华海清科（688120.SH）",
        "date": "2026-07-14",
        "original_url_or_locator": "https://tushare.pro/document/2?doc_id=32",
        "local_locator": "只读API记录：ts_code=688120.SH；daily_basic trade_date=20260714；fina_indicator end_date=20260331；抓取日2026-07-20。",
        "language": "zh",
        "tier": "approved_financial_database",
        "independence_key": "provider:tushare:688120.SH",
        "independence_rationale": "与年度报表属于同一Tushare发行人数据组，不重复计作独立确认。",
        "excerpt": (
            "Tushare快照：华海清科2026-07-14总市值1,528.72亿元、PE_TTM 139.28倍、PB 19.80倍、"
            "PS_TTM 30.96倍；最近财务指标截至2026-03-31，ROE 3.26%、ROA 2.21%、"
            "EPS_TTM 2.2186元、BPS 21.83元。"
        ),
        "excerpt_zh": (
            "Tushare快照：华海清科2026-07-14总市值1,528.72亿元、PE_TTM 139.28倍、PB 19.80倍、"
            "PS_TTM 30.96倍；最近财务指标截至2026-03-31，ROE 3.26%、ROA 2.21%、"
            "EPS_TTM 2.2186元、BPS 21.83元。"
        ),
    },
    {
        "source_id": "FIN-EQ-HUHAI-DIVIDEND",
        "publisher": "华海清科／上海证券交易所",
        "title": "国泰海通证券股份有限公司关于华海清科股份有限公司差异化分红送转特殊除权除息事项的核查意见",
        "title_zh": "华海清科2025年度差异化分红送转除权除息核查意见",
        "date": "2026-06-04",
        "original_url_or_locator": "https://star.sse.com.cn/disclosure/listedinfo/announcement/c/new/2026-06-04/688120_20260604_6XKC.pdf",
        "local_locator": (
            "PDF第1—3页，‘差异化分红送转方案及除权除息计算依据’；检索‘每10股转增4.00股’、"
            "‘虚拟分派的流通股份变动比例’和‘0.39892’。"
        ),
        "language": "zh",
        "tier": "T1-监管披露",
        "independence_key": "issuer:hwatsing:2025_dividend_adjustment",
        "independence_rationale": "发行人在上交所披露的权益分派及除权口径，与Tushare行情快照分开计证。",
        "excerpt": (
            "公司本次拟向全体股东每10股派发现金红利4.00元（含税），同时以资本公积金每10股转增4.00股。"
            "虚拟分派的流通股份变动比例=（参与分配的股本总数×实际分派的送转比例）÷总股本"
            "=（352,697,840×0.40）÷353,651,991≈0.39892。"
        ),
        "excerpt_zh": (
            "公司本次拟向全体股东每10股派发现金红利4.00元（含税），同时以资本公积金每10股转增4.00股。"
            "虚拟分派的流通股份变动比例=（参与分配的股本总数×实际分派的送转比例）÷总股本"
            "=（352,697,840×0.40）÷353,651,991≈0.39892。"
        ),
    },
    {
        "source_id": "FIN-EQ-PVA-MARKET",
        "publisher": "Yahoo Finance / yfinance",
        "title": "yfinance valuation and financial-metric snapshot for PVA TePla (TPE.DE)",
        "title_zh": "yfinance估值与财务指标快照：PVA TePla（TPE.DE）",
        "date": "2026-07-17",
        "original_url_or_locator": "https://finance.yahoo.com/quote/TPE.DE/",
        "local_locator": "只读接口记录：yfinance Ticker('TPE.DE').get_info()；market snapshot 2026-07-17；财务指标期2026-03-31；抓取日2026-07-20。",
        "language": "en",
        "tier": "approved_financial_database",
        "independence_key": "provider:yfinance:TPE.DE",
        "independence_rationale": "同一证券代码的yfinance估值、盈利指标和同批汇率换算合并为一个证据组。",
        "excerpt": (
            "yfinance get_info snapshot for TPE.DE on 2026-07-17: market cap CNY 5.782 billion "
            "(USD 0.854 billion), trailing PE 366.40, price-to-book 5.58 and price-to-sales 3.11. "
            "Metrics dated 2026-03-31 were ROE 1.40%, ROA 1.66%, trailing EPS EUR 0.10, book value per share EUR 6.57, "
            "gross margin 30.78%, net margin 0.84% and operating cash flow CNY 0.013 billion; FY2025 capex was CNY 0.197 billion."
        ),
        "excerpt_zh": (
            "yfinance只读快照：PVA TePla在2026-07-17总市值57.82亿元人民币（约8.54亿美元），"
            "PE_TTM 366.40倍、PB 5.58倍、PS_TTM 3.11倍；截至2026-03-31的指标为ROE 1.40%、"
            "ROA 1.66%、EPS_TTM 0.10欧元、BPS 6.57欧元、毛利率30.78%、净利率0.84%、"
            "经营现金流0.13亿元人民币；2025年资本开支1.97亿元人民币。人民币市值按同批实时汇率换算。"
        ),
    },
    {
        "source_id": "FIN-EQ-ACCRETECH-MARKET",
        "publisher": "Yahoo Finance / yfinance",
        "title": "yfinance valuation and financial-metric snapshot for Tokyo Seimitsu (7729.T)",
        "title_zh": "yfinance估值与财务指标快照：东京精密（7729.T）",
        "date": "2026-07-17",
        "original_url_or_locator": "https://finance.yahoo.com/quote/7729.T/",
        "local_locator": "只读接口记录：yfinance Ticker('7729.T').get_info()；market snapshot 2026-07-17；财务指标期2026-03-31；抓取日2026-07-20。",
        "language": "en",
        "tier": "approved_financial_database",
        "independence_key": "provider:yfinance:7729.T",
        "independence_rationale": "同一证券代码的yfinance估值、盈利指标和同批汇率换算合并为一个证据组。",
        "excerpt": (
            "yfinance get_info snapshot for 7729.T on 2026-07-17: market cap CNY 28.783 billion "
            "(USD 4.253 billion), trailing PE 28.17, price-to-book 3.61 and price-to-sales 4.15. "
            "Metrics dated 2026-03-31 were ROE 13.45%, ROA 8.63%, trailing EPS JPY 605.45, book value per share JPY 4,723.02, "
            "gross margin 41.27%, net margin 14.83%, operating cash flow CNY 1.040 billion and capex CNY 0.484 billion."
        ),
        "excerpt_zh": (
            "yfinance只读快照：东京精密在2026-07-17总市值287.83亿元人民币（约42.53亿美元），"
            "PE_TTM 28.17倍、PB 3.61倍、PS_TTM 4.15倍；截至2026-03-31的指标为ROE 13.45%、"
            "ROA 8.63%、EPS_TTM 605.45日元、BPS 4,723.02日元、毛利率41.27%、净利率14.83%、"
            "经营现金流10.40亿元人民币、资本开支4.84亿元人民币。人民币市值按同批实时汇率换算。"
        ),
    },
    {
        "source_id": "FIN-EQ-JINGSHENG-MARKET",
        "publisher": "Tushare Pro",
        "title": "Tushare估值与财务指标快照：晶盛机电（300316.SZ）",
        "title_zh": "Tushare估值与财务指标快照：晶盛机电（300316.SZ）",
        "date": "2026-07-17",
        "original_url_or_locator": "https://tushare.pro/document/2?doc_id=32",
        "local_locator": "只读API记录：ts_code=300316.SZ；daily_basic trade_date=20260717；fina_indicator与cashflow end_date=20260331；抓取日2026-07-20。",
        "language": "zh",
        "tier": "approved_financial_database",
        "independence_key": "provider:tushare:300316.SZ",
        "independence_rationale": "同一证券代码的Tushare日行情、估值、财务指标和现金流合并为一个证据组。",
        "excerpt": (
            "Tushare只读快照：晶盛机电2026-07-17总市值490.42亿元、PE_TTM 118.35倍、PB 2.85倍、"
            "PS_TTM 4.93倍；最近财务指标截至2026-03-31，ROE 0.60%、ROA 0.45%、"
            "EPS_TTM 0.3164元、BPS 13.15元、毛利率29.44%、净利率5.50%、"
            "经营现金流-2.35亿元、资本开支1.49亿元。"
        ),
        "excerpt_zh": (
            "Tushare只读快照：晶盛机电2026-07-17总市值490.42亿元、PE_TTM 118.35倍、PB 2.85倍、"
            "PS_TTM 4.93倍；最近财务指标截至2026-03-31，ROE 0.60%、ROA 0.45%、"
            "EPS_TTM 0.3164元、BPS 13.15元、毛利率29.44%、净利率5.50%、"
            "经营现金流-2.35亿元、资本开支1.49亿元。"
        ),
    },
    {
        "source_id": "FIN-EQ-KLA-MARKET",
        "publisher": "Yahoo Finance / yfinance",
        "title": "yfinance valuation and financial-metric snapshot for KLA (KLAC)",
        "title_zh": "yfinance估值与财务指标快照：KLA（KLAC）",
        "date": "2026-07-17",
        "original_url_or_locator": "https://finance.yahoo.com/quote/KLAC/",
        "local_locator": "只读接口记录：yfinance Ticker('KLAC').get_info()；market snapshot 2026-07-17；财务指标期2026-03-31；抓取日2026-07-20。",
        "language": "en",
        "tier": "approved_financial_database",
        "independence_key": "provider:yfinance:KLAC",
        "independence_rationale": "同一证券代码的yfinance估值、盈利指标和同批汇率换算合并为一个证据组。",
        "excerpt": (
            "yfinance get_info snapshot for KLAC on 2026-07-17: market cap USD 277.910 billion, "
            "converted with the same-run FX snapshot to CNY 1,880.812 billion; trailing PE 60.27, "
            "price-to-book 47.69 and price-to-sales 21.22. Metrics dated 2026-03-31 were ROE 94.98%, "
            "ROA 21.28%, trailing EPS USD 3.53, book value per share USD 4.46, gross margin 61.45%, "
            "net margin 35.66% and operating cash flow CNY 29.789 billion; FY2025 capex was CNY 2.302 billion."
        ),
        "excerpt_zh": (
            "yfinance只读快照：KLA在2026-07-17总市值2,779.10亿美元，按同批实时汇率折算为"
            "18,808.12亿元人民币；PE_TTM 60.27倍、PB 47.69倍、PS_TTM 21.22倍；截至2026-03-31"
            "的指标为ROE 94.98%、ROA 21.28%、EPS_TTM 3.53美元、BPS 4.46美元、毛利率61.45%、"
            "净利率35.66%、经营现金流297.89亿元人民币；2025财年资本开支23.02亿元人民币。人民币折算值与旧缓存"
            "的微小差异来自汇率口径，不代表经营变化。"
        ),
    },
)


FINANCIAL_SUPPLEMENT_TARGETS: dict[str, dict[str, Any]] = {
    "crystal_rise": {
        "target_name": "晶升股份",
        "ticker": "688478.SH",
        "market": "上海证券交易所科创板",
        "annual_source_ref": "FIN-EQ-JS-ANNUAL",
        "market_source_ref": "FIN-EQ-JS-MARKET",
        "annuals": [
            {"period": "2023", "as_of_date": "2023-12-31", "revenue": 4.06, "net_profit": 0.71, "gross_margin": 33.46, "operating_cash_flow": -0.92, "capex": 0.76},
            {"period": "2024", "as_of_date": "2024-12-31", "revenue": 4.25, "net_profit": 0.54, "gross_margin": 26.07, "operating_cash_flow": 0.03, "capex": 0.95},
            {"period": "2025", "as_of_date": "2025-12-31", "revenue": 1.16, "net_profit": -0.38, "gross_margin": 15.03, "operating_cash_flow": -0.51, "capex": 0.68},
        ],
        "valuation_text": (
            "总市值85.16亿元；PB 5.68倍；PS_TTM 178.42倍；ROE -0.58%；ROA -0.65%；BPS 10.83元；"
            "PE_TTM和EPS_TTM不适用/不可得。2025年已转为亏损，不能把PE缺失写成0或与盈利公司直接比较。"
        ),
        "financial_status": (
            "已取得Tushare 2023—2025三年财务及2026-07-14估值。2025年收入和毛利率明显下降并转亏，"
            "当前PE不适用；集团财务仍不能替代12英寸单晶炉专题收入。"
        ),
    },
    "applied_materials": {
        "target_name": "Applied Materials",
        "ticker": "AMAT.US",
        "market": "NASDAQ",
        "annual_source_ref": "FIN-EQ-AMAT-ANNUAL",
        "market_source_ref": "FIN-EQ-AMAT-MARKET",
        "annuals": [
            {"period": "FY2022", "as_of_date": "2022-10-31", "revenue": 257.85, "net_profit": 65.25, "gross_margin": 46.51, "operating_cash_flow": 53.99, "capex": 7.87},
            {"period": "FY2023", "as_of_date": "2023-10-31", "revenue": 265.17, "net_profit": 68.56, "gross_margin": 46.70, "operating_cash_flow": 87.00, "capex": 11.06},
            {"period": "FY2024", "as_of_date": "2024-10-31", "revenue": 271.76, "net_profit": 71.77, "gross_margin": 47.46, "operating_cash_flow": 86.77, "capex": 11.90},
            {"period": "FY2025", "as_of_date": "2025-10-31", "revenue": 283.68, "net_profit": 69.98, "gross_margin": 48.67, "operating_cash_flow": 79.58, "capex": 22.60},
        ],
        "valuation_text": (
            "总市值32,002.95亿元人民币（约4,729.62亿美元）；滚动市盈率（PE-TTM）54.06倍；前瞻市盈率35.58倍；"
            "市净率19.78倍；滚动市销率接口未返回、当前不可得；净资产收益率39.69%；总资产收益率14.86%；"
            "滚动每股收益（EPS-TTM）11.02美元；每股净资产30.11美元。"
        ),
        "financial_status": (
            "已取得yfinance FY2022—FY2025四年财务及2026-07-14估值。合并收入连续增长但FY2025净利润低于FY2024；"
            "滚动市销率接口未返回，不能按0补写；硅外延专用收入和目标项目合同仍未单列，集团高估值不能作为项目盈利证据。"
        ),
    },
    "huahai_qingke": {
        "target_name": "华海清科",
        "ticker": "688120.SH",
        "market": "上海证券交易所科创板",
        "annual_source_ref": "FIN-EQ-HUHAI-ANNUAL",
        "market_source_ref": "FIN-EQ-HUHAI-MARKET",
        "corporate_action_source_ref": "FIN-EQ-HUHAI-DIVIDEND",
        "pre_action_bps": 21.83,
        "share_change_ratio": 0.39892,
        "adjusted_bps": 15.6048952048723,
        "annuals": [
            {"period": "2023", "as_of_date": "2023-12-31", "revenue": 25.08, "net_profit": 7.24, "gross_margin": 46.02, "operating_cash_flow": 6.53, "capex": 3.40},
            {"period": "2024", "as_of_date": "2024-12-31", "revenue": 34.06, "net_profit": 10.23, "gross_margin": 43.20, "operating_cash_flow": 11.55, "capex": 3.22},
            {"period": "2025", "as_of_date": "2025-12-31", "revenue": 46.48, "net_profit": 10.84, "gross_margin": 41.81, "operating_cash_flow": 8.00, "capex": 2.22},
        ],
        "valuation_text": (
            "总市值1,528.72亿元；PE_TTM 139.28倍；PB 19.80倍；PS_TTM 30.96倍；ROE 3.26%；"
            "ROA 2.21%；EPS_TTM 2.2186元；除权同口径BPS 15.60元。"
            "原始2026-03-31 BPS为21.83元；按权益分派的0.39892流通股份变动比例调整："
            "21.83÷(1+0.39892)=15.6049元。"
        ),
        "financial_status": (
            "已取得Tushare 2023—2025三年财务及2026-07-14估值。收入和净利润增长，但毛利率连续回落且当前估值较高；"
            "2026-03-31每股净资产已按上交所披露的送转比例调整到除权后同口径。"
            "集团财务仍不能替代大硅片CMP、研磨和终洗的专题收入与毛利。"
        ),
    },
}


CURRENT_VALUATION_SNAPSHOTS: dict[str, dict[str, str]] = {
    "pva_tepla": {
        "target_name": "PVA TePla",
        "source_ref": "FIN-EQ-PVA-MARKET",
        "market_as_of": "2026-07-17",
        "financial_metrics_as_of": "2026-03-31",
        "valuation_text": (
            "总市值57.82亿元人民币（约8.54亿美元）；PE_TTM 366.40倍；PB 5.58倍；PS_TTM 3.11倍；"
            "截至2026-03-31，ROE 1.40%、ROA 1.66%、EPS_TTM 0.10欧元、BPS 6.57欧元、"
            "毛利率30.78%、净利率0.84%、经营现金流0.13亿元人民币；2025年资本开支1.97亿元人民币。"
        ),
        "financial_status": (
            "已取得三期发行人财务及2026-07-17 yfinance估值；盈利和每股指标截至2026-03-31，"
            "资本开支对应2025-12-31。集团与半导体系统财务均不能替代硅片长晶设备专题收入。"
        ),
    },
    "accretech": {
        "target_name": "东京精密／ACCRETECH",
        "source_ref": "FIN-EQ-ACCRETECH-MARKET",
        "market_as_of": "2026-07-17",
        "financial_metrics_as_of": "2026-03-31",
        "valuation_text": (
            "总市值287.83亿元人民币（约42.53亿美元）；PE_TTM 28.17倍；PB 3.61倍；PS_TTM 4.15倍；"
            "截至2026-03-31，ROE 13.45%、ROA 8.63%、EPS_TTM 605.45日元、BPS 4,723.02日元、"
            "毛利率41.27%、净利率14.83%、经营现金流10.40亿元人民币、资本开支4.84亿元人民币。"
        ),
        "financial_status": (
            "已取得三期发行人财务及2026-07-17 yfinance估值；盈利、每股指标和现金流口径截至2026-03-31。"
            "合并财务不能替代硅片研磨、边缘成型和脱片清洗设备的专题收入。"
        ),
    },
    "jingsheng": {
        "target_name": "晶盛机电",
        "source_ref": "FIN-EQ-JINGSHENG-MARKET",
        "market_as_of": "2026-07-17",
        "financial_metrics_as_of": "2026-03-31",
        "valuation_text": (
            "总市值490.42亿元人民币（约72.46亿美元）；PE_TTM 118.35倍；PB 2.85倍；PS_TTM 4.93倍；"
            "截至2026-03-31，ROE 0.60%、ROA 0.45%、EPS_TTM 0.3164元、BPS 13.15元、"
            "毛利率29.44%、净利率5.50%、经营现金流-2.35亿元、资本开支1.49亿元。"
        ),
        "financial_status": (
            "已取得三期发行人财务及2026-07-17 Tushare估值；盈利、每股指标和现金流口径截至2026-03-31。"
            "集团报表受光伏等业务影响，不能替代半导体硅片设备专题收入。"
        ),
    },
    "kla": {
        "target_name": "KLA",
        "source_ref": "FIN-EQ-KLA-MARKET",
        "market_as_of": "2026-07-17",
        "financial_metrics_as_of": "2026-03-31",
        "valuation_text": (
            "总市值18,808.12亿元人民币（约2,779.10亿美元）；PE_TTM 60.27倍；PB 47.69倍；PS_TTM 21.22倍；"
            "截至2026-03-31，ROE 94.98%、ROA 21.28%、EPS_TTM 3.53美元、BPS 4.46美元、"
            "毛利率61.45%、净利率35.66%、经营现金流297.89亿元人民币；2025财年资本开支23.02亿元人民币。"
            "人民币市值使用本次同批USDCNY快照折算，与旧缓存的微小差异不代表经营变化。"
        ),
        "financial_status": (
            "已取得三期发行人财务及2026-07-17 yfinance估值；盈利和每股指标截至2026-03-31，"
            "资本开支对应2025-06-30。人民币市值按本次同批汇率折算，汇率微差不解释为经营变化；"
            "集团制程控制财务不能替代裸硅片检测专题收入。"
        ),
    },
}


def source_rows() -> list[dict[str, Any]]:
    return [deepcopy(row) for row in FINANCIAL_SUPPLEMENT_SOURCES]


def target_spec(target_id: str) -> dict[str, Any]:
    if target_id not in FINANCIAL_SUPPLEMENT_TARGETS:
        raise KeyError(target_id)
    return deepcopy(FINANCIAL_SUPPLEMENT_TARGETS[target_id])


def current_snapshot_spec(target_id: str) -> dict[str, str]:
    if target_id not in CURRENT_VALUATION_SNAPSHOTS:
        raise KeyError(target_id)
    return deepcopy(CURRENT_VALUATION_SNAPSHOTS[target_id])


def build_current_valuation_data_point(
    target_id: str,
    *,
    sources_by_ref: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    spec = CURRENT_VALUATION_SNAPSHOTS[target_id]
    ref = str(spec["source_ref"])
    if ref not in sources_by_ref:
        raise ValueError(f"当前估值引用未知来源：{ref}")
    source = sources_by_ref[ref]
    point: dict[str, Any] = {
        "metric_name": f"{spec['target_name']}当前估值与盈利状态",
        "metric_category": "current_valuation_and_profitability",
        "period": str(spec["market_as_of"]),
        "as_of_date": str(spec["market_as_of"]),
        "unit": "市值为亿元人民币（括号为亿美元）；倍数和比例除外；EPS/BPS按证券原币",
        "value_text": str(spec["valuation_text"]),
        "data_quality_label": "Tushare/yfinance只读估值与财务指标快照",
        "direction": "mixed",
        "credibility_weight": 1.0,
        "numeric_weight": 1.0,
        "source_title": source.get("title") or source.get("title_zh"),
        "source_title_zh": source.get("title_zh") or source.get("title"),
        "source_publisher": source.get("publisher"),
        "source_url": source.get("url"),
        "source_language": source.get("language"),
        "source_excerpt": source.get("excerpt") or source.get("excerpt_zh"),
        "evidence_ref_uri": source_uri(ref),
    }
    if not str(source.get("language") or "").lower().startswith("zh"):
        point["source_excerpt_zh"] = source.get("excerpt_zh") or ""
    return point


def build_target_data_points(
    target_id: str,
    *,
    product_source_ref: str,
    product_evidence: str,
    sources_by_ref: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    spec = FINANCIAL_SUPPLEMENT_TARGETS[target_id]
    refs = {
        product_source_ref,
        str(spec["annual_source_ref"]),
        str(spec["market_source_ref"]),
    }
    if spec.get("corporate_action_source_ref"):
        refs.add(str(spec["corporate_action_source_ref"]))
    missing = refs - set(sources_by_ref)
    if missing:
        raise ValueError(f"财务补充引用未知来源：{sorted(missing)}")

    def common(ref: str) -> dict[str, Any]:
        source = sources_by_ref[ref]
        payload: dict[str, Any] = {
            "source_title": source.get("title") or source.get("title_zh"),
            "source_title_zh": source.get("title_zh") or source.get("title"),
            "source_publisher": source.get("publisher"),
            "source_url": source.get("url"),
            "source_language": source.get("language"),
            "source_excerpt": source.get("excerpt") or source.get("excerpt_zh"),
            "evidence_ref_uri": source_uri(ref),
        }
        if str(source.get("language") or "").lower() != "zh-cn":
            payload["source_excerpt_zh"] = source.get("excerpt_zh") or ""
        return payload

    product_source = sources_by_ref[product_source_ref]
    points: list[dict[str, Any]] = [
        {
            "metric_name": f"{spec['target_name']}的硅片设备直接证据",
            "metric_category": "product_and_customer_validation",
            "period": str(product_source.get("publish_date") or "截至研究日"),
            "unit": "事实",
            "value_text": product_evidence,
            **common(product_source_ref),
        }
    ]
    annual_ref = str(spec["annual_source_ref"])
    currency_unit = "亿元人民币" if spec["ticker"].endswith(".SH") else "亿美元"
    for row in spec["annuals"]:
        values = f"收入{row['revenue']:.2f}{currency_unit}；净利润{row['net_profit']:.2f}{currency_unit}"
        if row.get("gross_margin") is not None:
            values += f"；毛利率{float(row['gross_margin']):.2f}%"
        if row.get("operating_cash_flow") is not None:
            values += f"；经营现金流{float(row['operating_cash_flow']):.2f}{currency_unit}"
        if row.get("capex") is not None:
            values += f"；资本开支{float(row['capex']):.2f}{currency_unit}"
        points.append(
            {
                "metric_name": f"{spec['target_name']}{row['period']}核心财务",
                "metric_category": "financial_history",
                "period": str(row["period"]),
                "as_of_date": str(row["as_of_date"]),
                "unit": f"{currency_unit}，比例除外",
                "value_text": values,
                "data_quality_label": "Tushare/yfinance财务报表",
                "direction": "mixed",
                "credibility_weight": 1.0,
                "numeric_weight": 1.0,
                **common(annual_ref),
            }
        )
    market_ref = str(spec["market_source_ref"])
    corporate_action_ref = str(spec.get("corporate_action_source_ref") or "")
    if corporate_action_ref:
        points.append(
            {
                "metric_name": f"{spec['target_name']}权益分派与每股净资产口径调整",
                "metric_category": "corporate_action_adjustment",
                "period": "2026-06-04",
                "as_of_date": "2026-06-04",
                "unit": "元／股",
                "value_text": (
                    f"权益分派每10股转增4股；差异化送转对应流通股份变动比例{float(spec['share_change_ratio']):.5f}。"
                    f"2026-03-31原始BPS {float(spec['pre_action_bps']):.2f}元÷"
                    f"(1+{float(spec['share_change_ratio']):.5f})="
                    f"{float(spec['adjusted_bps']):.4f}元，作为2026-07-14 PB的同口径BPS。"
                ),
                "data_quality_label": "上交所权益分派公告与可复算除权公式",
                "direction": "neutral",
                "credibility_weight": 1.0,
                "numeric_weight": 1.0,
                **common(corporate_action_ref),
            }
        )
    points.append(
        {
            "metric_name": f"{spec['target_name']}当前估值与盈利状态",
            "metric_category": "current_valuation_and_profitability",
            "period": "2026-07-14",
            "as_of_date": "2026-07-14",
            "unit": "多指标",
            "value_text": str(spec["valuation_text"]),
            "data_quality_label": "Tushare/yfinance估值快照",
            "direction": "mixed",
            "credibility_weight": 1.0,
            "numeric_weight": 1.0,
            **(
                {"additional_evidence_ref_uri_list": [source_uri(corporate_action_ref)]}
                if corporate_action_ref
                else {}
            ),
            **common(market_ref),
        }
    )
    return points
